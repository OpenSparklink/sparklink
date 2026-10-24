#[path = "../../../crates/slk-protocol/src/ssap/value.rs"]
pub mod value;
#[path = "../../../crates/slk-protocol/src/ssap/read_uuid.rs"]
pub mod read_uuid;
#[path = "../../../crates/slk-protocol/src/ssap/updates.rs"]
pub mod updates;
#[cfg(kani)]
mod proofs {
    use super::value::ValuePdu;
    #[kani::proof]
    #[kani::unwind(20)]
    fn exact_valid_decode_reencode() {
        let input: [u8; 16] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= 16);
        let mtu: u16 = kani::any();
        if let Ok(p) = ValuePdu::decode(mtu, &input[..len]) {
            let mut output = [0xa5; 16];
            let n = p.encode(mtu, &mut output).unwrap();
            assert!(n == len);
            for i in 0..16 {
                if i < n {
                    assert!(output[i] == input[i]);
                } else {
                    assert!(output[i] == 0xa5);
                }
            }
        }
    }
    #[kani::proof]
    #[kani::unwind(20)]
    fn failed_encode_is_atomic() {
        let input: [u8; 16] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= 16);
        let mtu: u16 = kani::any();
        let capacity: usize = kani::any();
        kani::assume(capacity <= 16);
        if let Ok(p) = ValuePdu::decode(65535, &input[..len]) {
            let mut output: [u8; 16] = kani::any();
            let original = output;
            if p.encode(mtu, &mut output[..capacity]).is_err() {
                for i in 0..16 {
                    assert!(output[i] == original[i]);
                }
            }
        }
    }
}

#[cfg(kani)]
mod uuid_proofs {
    #[kani::proof]
    #[kani::unwind(20)]
    fn actual_uuid_response_roundtrip_and_atomic_refusal() {
        let raw:[u8;16]=kani::any();let len:usize=kani::any();kani::assume(len<=16);
        if let Ok(items)=super::read_uuid::decode(16,&raw[..len]) {
            let mut out=[0xa5;16];let n=super::read_uuid::encode(16,&items,&mut out).unwrap();assert_eq!(&out[..n],&raw[..len]);
            let capacity:usize=kani::any();kani::assume(capacity<=16);let before=out;
            if super::read_uuid::encode(16,&items,&mut out[..capacity]).is_err(){assert_eq!(out,before);}
        }
    }
}

#[cfg(kani)]
mod ack_proofs {
    #[kani::proof]
    #[kani::unwind(12)]
    fn actual_ack_flags_and_atomic_refusal() {
        let flags:[u8;4]=kani::any();let count:usize=kani::any();kani::assume(count<=4);
        let capacity:usize=kani::any();kani::assume(capacity<=8);
        let mtu:u16=kani::any();let event:bool=kani::any();let mut out:[u8;8]=kani::any();let before=out;
        match super::updates::ack(mtu,event,&flags[..count],&mut out[..capacity]) {
            Ok(n)=>{
                assert!(n==count+2);assert!(out[0]==17);assert!(out[1]==if event{7}else{3});
                match super::updates::decode_ack(mtu,&out[..n],event,count) {
                    Ok(decoded)=>{for i in 0..count {assert!(decoded[i]==flags[i]);assert!(flags[i]<=1);}},
                    Err(_)=>assert!(false,"encoded ACK must decode"),
                }
                for i in n..8 {assert!(out[i]==before[i]);}
            },
            Err(_)=>{for i in 0..8 {assert!(out[i]==before[i]);}},
        }
    }
}

// The exact replacement admission used by both local owner and remote write.
#[path = "../../../crates/slkd/src/ssap_database/budget.rs"]
mod value_budget;
#[cfg(kani)]
mod local_value_proofs {
    #[kani::proof]
    fn actual_replacement_budget_is_exact_and_bounded() {
        let total:usize=kani::any();let old:usize=kani::any();let new:usize=kani::any();
        let expected=total<=8192 && old<=2042 && new<=2042 && old<=total
            && (total-old)+new<=8192;
        let result=super::value_budget::replacement_bytes(total,old,new);
        assert_eq!(result.is_some(),expected,"actual admission exactly matches finite byte budgets");
        if let Some(next)=result {
            assert!(next<=8192,"committed byte total remains bounded");
            assert_eq!(next,total-old+new,"replace removes old bytes exactly once");
        }
    }
    #[kani::proof]
    fn actual_replacement_budget_composes_with_shrink_and_remove() {
        let total:usize=kani::any();let old:usize=kani::any();let new:usize=kani::any();
        kani::assume(old<=2042 && old<=total && total<=8192 && new<=2042);
        if let Some(next)=super::value_budget::replacement_bytes(total,old,new) {
            assert_eq!(super::value_budget::replacement_bytes(next,new,old),Some(total),"replacing back restores original accounting");
            assert_eq!(super::value_budget::replacement_bytes(next,new,0),Some(total-old),"empty replacement releases only its own bytes");
        }
    }
}
#[cfg(kani)]
mod local_value_negative_control {
    #[kani::proof]
    fn reject_a_false_replacement_budget_claim() {
        assert!(super::value_budget::replacement_bytes(8192,0,1).is_some(),
            "negative control must reject overbudget admission claim");
    }
}

// Include the real pure protocol module and its real dependencies,not a
// verification-specific replacement for SsapOperations or access checks.
#[path = "../../../crates/slk-protocol/src/ssap.rs"]
pub mod ssap;
#[cfg(kani)]
mod configuration_proofs {
    #[kani::proof]
    #[kani::unwind(2050)]
    fn actual_configuration_decode_matches_full_runtime_value_budget() {
        let raw:[u8;2042]=kani::any();let len:usize=kani::any();let modes:u8=kani::any();
        kani::assume(len<=raw.len());
        let value=u16::from_le_bytes([raw[0],raw[1]]);
        let expected=len==2 && (1..=3).contains(&modes) && value & !u16::from(modes)==0;
        let result=super::ssap::client_config::decode(&raw[..len],modes);
        assert_eq!(result.is_ok(),expected,"configuration admission matches exact length reserved bits and capabilities");
        if let Ok(accepted)=result {
            assert_eq!(u16::from(accepted),value,"configuration accepted bytes preserve little endian value");
            assert_eq!(accepted & !3,0,"configuration never enables reserved modes");
        }
    }
    #[kani::proof]
    fn actual_configuration_access_requires_both_authentication_and_approval() {
        let level:u32=kani::any();let approved:bool=kani::any();
        let result=super::ssap::client_config::WRITE_ACCESS.check_authorization_result(level,true,approved);
        assert_eq!(result.is_ok(),level==2 && approved,"actual descriptor write requires authenticated level and separate approval");
    }
    #[kani::proof]
    fn wrong_claim_configuration_reserved_bits_are_accepted() {
        let result=super::ssap::client_config::decode(&[4,0],3);
        assert!(result.is_ok(),"negative control wrongly permits reserved client configuration");
    }
}

// The production fragmentation implementation, not a second model/codec.
#[path = "../../../crates/slk-protocol/src/ssap/fragments.rs"]
pub mod fragments;
#[cfg(kani)]
mod fragment_proofs {
    use super::fragments::{Plan, Reassembly};
    #[kani::proof]
    #[kani::unwind(40)]
    fn actual_fragment_encode_is_atomic_and_wire_bounded() {
        let raw: [u8; 16] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= 16);
        let mtu: u16 = kani::any();
        let sequence: bool = kani::any();
        let index: usize = kani::any();
        let cap: usize = kani::any();
        kani::assume(cap <= 24);
        let mut out: [u8; 24] = kani::any();
        let before = out;
        if let Ok(plan) = Plan::new(&raw[..len], mtu, sequence) {
            assert!(
                (1..=15).contains(&plan.count()),
                "fragment count within declared budget"
            );
            match plan.encode(index, &mut out[..cap]) {
                Ok(n) => {
                    assert!(
                        n <= usize::from(mtu) && n <= cap,
                        "fragment encoded output within wire MTU"
                    );
                    for i in n..24 {
                        assert!(out[i] == before[i], "fragment trailing output untouched");
                    }
                }
                Err(_) => {
                    for i in 0..24 {
                        assert!(out[i] == before[i], "fragment refusal is atomic");
                    }
                }
            }
        }
    }
    #[kani::proof]
    #[kani::unwind(40)]
    fn actual_fragment_completion_keeps_first_identity_and_deadline() {
        let tail: [u8; 5] = kani::any();
        let raw = [
            13, 35, 17, 0, 0, tail[0], tail[1], tail[2], tail[3], tail[4],
        ];
        let plan = Plan::new(&raw, 8, true).unwrap();
        let mut a = [0; 8];
        let mut b = [0; 8];
        let na = plan.encode(0, &mut a).unwrap();
        let nb = plan.encode(1, &mut b).unwrap();
        let identity: u8 = kani::any();
        let next: u8 = kani::any();
        let now: u64 = kani::any();
        let renewed: u64 = kani::any();
        let mut rx = Reassembly::default();
        assert!(
            rx.receive(&a[..na], 8, true, identity, 0u64, 10)
                .unwrap()
                .is_none()
        );
        let result = rx.receive(&b[..nb], 8, true, next, now, renewed);
        assert!(
            !matches!(result, Ok(None)),
            "final fragment must have terminal outcome"
        );
        match result {
            Ok(Some(c)) => {
                assert!(
                    identity == next && now < 10,
                    "fragment completion has original identity before expiry"
                );
                assert!(
                    c.context == identity && c.deadline == 10,
                    "fragment original context and deadline never renewed"
                );
                assert!(
                    c.bytes.len() == raw.len(),
                    "fragment completion preserves logical length"
                );
                for i in 0..10 {
                    assert!(
                        c.bytes[i] == raw[i],
                        "fragment completion preserves whole logical bytes"
                    );
                }
            }
            Err(_) => {
                assert!(
                    identity != next || now >= 10,
                    "valid final fragment not spuriously rejected"
                );
                assert!(
                    rx.deadline().is_none(),
                    "fragment error discards partial state"
                );
            }
            Ok(None) => {}
        }
    }
    #[kani::proof]
    #[kani::unwind(40)]
    fn actual_fragment_arbitrary_next_packet_cannot_change_qualification() {
        let raw = [9, 3, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
        let length = if kani::any() { 10 } else { 12 };
        let plan = Plan::new(&raw[..length], 8, true).unwrap();
        let mut first = [0; 8];
        let n = plan.encode(0, &mut first).unwrap();
        let next: [u8; 8] = kani::any();
        let len: usize = kani::any();
        kani::assume(len <= 8);
        let identity: u8 = kani::any();
        let now: u8 = kani::any();
        let mut rx = Reassembly::default();
        assert!(
            rx.receive(&first[..n], 8, true, 7, 0u64, 10)
                .unwrap()
                .is_none()
        );
        match rx.receive(&next[..len], 8, true, identity, u64::from(now), 1000) {
            Ok(Some(c)) => {
                assert!(
                    c.context == 7 && identity == 7 && now < 10,
                    "arbitrary fragment cannot acquire new epoch or renewed deadline"
                );
                assert!(
                    c.deadline == 10 && c.bytes.len() <= 2047,
                    "arbitrary fragment keeps original bound"
                );
            }
            Ok(None) => {
                assert!(
                    rx.deadline() == Some(10),
                    "partial fragment never renews expiry"
                );
            }
            Err(_) => {
                assert!(
                    rx.deadline().is_none(),
                    "rejected fragment cannot retain work"
                );
            }
        }
    }
}

#[cfg(kani)]
mod fragment_layout_proof {
    use super::fragments::Layout;
    #[kani::proof]
    fn actual_production_layout_bounds_all_lengths_mtu_and_indices() {
        let length: usize = kani::any();
        let mtu: u16 = kani::any();
        let index: usize = kani::any();
        match Layout::new(length, mtu) {
            Ok(layout) => {
                assert!(
                    length >= 2 && length <= 2048,
                    "layout logical length stays bounded"
                );
                assert!(
                    layout.count() >= 1 && layout.count() <= 15,
                    "layout count stays bounded"
                );
                match layout.bounds(index) {
                    Ok((start, end, size)) => {
                        assert!(
                            index < layout.count(),
                            "layout index admitted only inside count"
                        );
                        assert!(
                            start <= end && end <= length && size <= mtu as usize,
                            "layout slice and wire bounds hold"
                        );
                        if layout.count() == 1 {
                            assert!(
                                index == 0 && start == 0 && end == length && size == length,
                                "layout complete PDU unchanged"
                            );
                        } else {
                            assert!(
                                start >= 2 && start < end && size == end - start + 4,
                                "layout fragment carries nonempty body and bounded header"
                            );
                            if index == 0 {
                                assert!(
                                    start == 2,
                                    "layout first body starts after original header"
                                );
                            }
                            if index + 1 == layout.count() {
                                assert!(
                                    end == length,
                                    "layout last body ends at exact logical boundary"
                                );
                            }
                        }
                    }
                    Err(_) => assert!(
                        index >= layout.count(),
                        "layout rejects only invalid part index"
                    ),
                }
            }
            Err(_) => {
                if length >= 2 && length <= 2048 {
                    assert!(
                        length > mtu as usize,
                        "layout never rejects fitting complete PDU"
                    );
                }
            }
        }
    }
}

#[cfg(kani)]
mod fragment_layout_negative {
    #[kani::proof]
    fn actual_layout_must_reject_the_false_single_wire_claim() {
        if let Ok(layout)=super::fragments::Layout::new(2047,2042) {
            assert!(layout.count()==1,"CONTROL_OVERSIZE_LOGICAL_PDU_IS_ONE_WIRE_PACKET");
        }
    }
}
