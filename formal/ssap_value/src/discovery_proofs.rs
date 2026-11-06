// SPDX-License-Identifier: GPL-2.0-only
//! Call the production discovery codec through its actual module tree.
//! No transport, allocator-success stub, replacement parser or peer assumption.
use super::ssap::{
    SsapOperations,
    discovery::{Entry, EntryClass, FindKind, FindRequest, decode_page, encode_page},
};

#[kani::proof]
#[kani::unwind(26)]
fn actual_find_request_preserves_bytes_and_refuses_atomically() {
    let raw: [u8; 22] = kani::any();
    let len: usize = kani::any();
    let capacity: usize = kani::any();
    let mtu: u16 = kani::any();
    kani::assume(len <= raw.len() && capacity <= raw.len());
    if let Ok(request) = FindRequest::decode(u16::MAX, &raw[..len]) {
        let mut output: [u8; 22] = kani::any();
        let before = output;
        match request.encode(mtu, &mut output[..capacity]) {
            Ok(n) => {
                assert!(
                    n == len && n <= capacity && n <= usize::from(mtu),
                    "find request encoded length stays exact and bounded"
                );
                for i in 0..22 {
                    assert!(
                        output[i] == if i < n { raw[i] } else { before[i] },
                        "find request preserves bytes and untouched tail"
                    );
                }
            }
            Err(_) => assert!(output == before, "find request refusal is atomic"),
        }
    }
}

#[kani::proof]
#[kani::unwind(40)]
fn actual_member_page_binds_original_schema_range_and_budget() {
    let raw: [u8; 32] = kani::any();
    let len: usize = kani::any();
    let class: u8 = kani::any();
    kani::assume(len <= raw.len() && class < 3);
    let event: bool = kani::any();
    let request = FindRequest {
        kind: if event {
            FindKind::Events
        } else {
            FindKind::Methods
        },
        class: match class {
            0 => EntryClass::Standard,
            1 => EntryClass::Custom,
            _ => EntryClass::Mixed,
        },
        start: kani::any(),
        end: kani::any(),
        uuid: None,
    };
    let mtu: u16 = kani::any();
    if let Ok(entries) = decode_page(request, mtu, &raw[..len]) {
        // Minimum member is 2-byte handle + 2-byte UUID + 4-byte operations
        // + 1-byte descriptor count; grouping can only add bytes.
        assert!(
            !entries.is_empty() && entries.len() <= 3 && len <= usize::from(mtu),
            "member page result is nonempty and input budget bounded"
        );
        let mut previous = 0;
        for entry in entries {
            assert!(
                entry.handle > previous
                    && entry.handle >= request.start
                    && entry.handle <= request.end
                    && entry.end == entry.handle,
                "member page preserves ordered original handle range"
            );
            assert!(
                entry.category == (if event { 4 } else { 3 }) + if entry.custom() { 8 } else { 0 },
                "member page category follows original request schema"
            );
            assert!(
                request.accepts(&entry.uuid) && matches!(entry.uuid.len(), 2 | 16),
                "member page UUID respects original class"
            );
            assert!(
                SsapOperations::from_bits(entry.operations).is_ok()
                    && entry.members == 0
                    && entry.descriptors.len() <= len,
                "member page metadata remains valid and bounded"
            );
            previous = entry.handle;
        }
    }
}

#[kani::proof]
#[kani::unwind(40)]
fn actual_member_page_roundtrip_or_exact_capacity_refusal() {
    let uuid: [u8; 16] = kani::any();
    let descriptors: [u8; 4] = kani::any();
    let count: usize = kani::any();
    kani::assume(count <= descriptors.len());
    let event: bool = kani::any();
    let custom: bool = kani::any();
    let handle: u16 = kani::any();
    let operations: u32 = kani::any();
    if handle == 0 || SsapOperations::from_bits(operations).is_err() {
        return;
    }
    let entry = Entry {
        category: (if event { 4 } else { 3 }) + if custom { 8 } else { 0 },
        handle,
        end: handle,
        uuid: uuid[..if custom { 16 } else { 2 }].to_vec(),
        operations,
        descriptors: descriptors[..count].to_vec(),
        members: 0,
    };
    let request = FindRequest {
        kind: if event {
            FindKind::Events
        } else {
            FindKind::Methods
        },
        class: EntryClass::Mixed,
        start: 1,
        end: u16::MAX,
        uuid: None,
    };
    let mtu: u16 = kani::any();
    match encode_page(request, mtu, std::slice::from_ref(&entry)) {
        Ok((raw, n)) => {
            assert!(
                n == 1 && raw.len() <= usize::from(mtu),
                "member encoder admits one exact bounded entry"
            );
            let decoded = decode_page(request, mtu, &raw).unwrap();
            assert!(decoded.len() == 1, "member roundtrip preserves entry count");
            let actual = &decoded[0];
            assert!(
                actual.category == entry.category
                    && actual.handle == entry.handle
                    && actual.end == entry.end
                    && actual.operations == entry.operations
                    && actual.members == entry.members
                    && actual.uuid.len() == entry.uuid.len()
                    && actual.descriptors.len() == entry.descriptors.len(),
                "member roundtrip preserves all scalar metadata and lengths"
            );
            // Compare every actual byte without allocating a second expected
            // Vec<Entry> or invoking Kani's unsupported pointer comparison.
            for i in 0..16 {
                if i < entry.uuid.len() {
                    assert!(
                        actual.uuid[i] == entry.uuid[i],
                        "member roundtrip preserves every UUID byte"
                    );
                }
            }
            for i in 0..4 {
                if i < entry.descriptors.len() {
                    assert!(
                        actual.descriptors[i] == entry.descriptors[i],
                        "member roundtrip preserves every descriptor byte"
                    );
                }
            }
        }
        Err(error) => assert!(
            error == super::ssap::discovery::FindError::Capacity,
            "valid member is refused only for exact capacity"
        ),
    }
}

#[kani::proof]
#[kani::unwind(26)]
fn wrong_claim_page_for_unfiltered_request_completes_uuid_query() {
    let request = FindRequest {
        kind: FindKind::Events,
        class: EntryClass::Mixed,
        start: 1,
        end: u16::MAX,
        uuid: Some(&[0x34, 0x12]),
    };
    // Opcode5 belongs to request4, not UUID request6/response7. This is an
    // intentionally false claim on the real decoder, not a weakened decoder.
    assert!(
        decode_page(request, 249, &[5, 3, 17, 0, 0x34, 0x12, 0, 0, 0, 0, 0]).is_ok(),
        "CONTROL_WRONG_FIND_OPCODE_COMPLETES_UUID_QUERY"
    );
}
