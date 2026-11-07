// SPDX-License-Identifier: GPL-2.0-only
//! Bounded device packets over the actual pinned production C HCC codec.
//! No Host credit, command matching, connection state or delivery qualification.
use std::io;

// Mapped to the pinned wire.h/codec baseline. A pin update requires reviewing
// these adapter storage bounds; the codec remains the wire-format authority.
pub const MAX_RX_BYTES: usize = 20 * 1024;
pub const MAX_RX_SLOTS: usize = 24;
pub const MAX_ACB_BYTES: usize = 2047;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub enum Boundary {
    Full = 0,
    First = 1,
    Middle = 2,
    Last = 3,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransmitKind {
    Command,
    Acb,
}
#[derive(Debug)]
pub struct EncodedPacket {
    kind: TransmitKind,
    bytes: Vec<u8>,
}
impl EncodedPacket {
    pub fn kind(&self) -> TransmitKind {
        self.kind
    }
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DevicePacket<'a> {
    /// Framing/type only; no Complete, security or command-credit interpretation.
    Event {
        code: u16,
        parameters: &'a [u8],
        original: &'a [u8],
    },
    Acb {
        handle: u16,
        boundary: Boundary,
        priority: bool,
        payload: &'a [u8],
        original: &'a [u8],
    },
    Bsle(&'a [u8]),
    Platform(&'a [u8]),
}

pub fn encode_command(sequence: u32, opcode: u16, parameters: &[u8]) -> io::Result<EncodedPacket> {
    if opcode == 0 || parameters.len() > 255 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "short command envelope required",
        ));
    }
    actual::command(sequence, opcode, parameters)
}
pub fn encode_acb(
    sequence: u32,
    handle: u16,
    boundary: Boundary,
    maximum: u16,
    payload: &[u8],
) -> io::Result<EncodedPacket> {
    if maximum == 0
        || usize::from(maximum) > MAX_ACB_BYTES
        || payload.is_empty()
        || payload.len() > usize::from(maximum)
        || handle > 0x0fff
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "bounded ACB handle/PB/payload required",
        ));
    }
    actual::acb(sequence, handle, boundary, maximum, payload)
}
/// Validate the whole HCC aggregate and every typed slot before returning any
/// packet. Returned slices borrow only this input, never callback-local memory.
pub fn decode_receive(data: &[u8], maximum_acb: u16) -> io::Result<Vec<DevicePacket<'_>>> {
    if data.len() > MAX_RX_BYTES || maximum_acb == 0 || usize::from(maximum_acb) > MAX_ACB_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "receive byte/ACB budget exceeded",
        ));
    }
    actual::receive(data, maximum_acb)
}

#[cfg(target_os = "linux")]
mod actual {
    use super::*;
    use std::ffi::{c_int, c_uint, c_void};
    unsafe extern "C" {
        fn ws73_wire_command(
            out: *mut u8,
            capacity: usize,
            sequence: c_uint,
            opcode: c_uint,
            parameters: *const u8,
            size: usize,
        ) -> c_int;
        fn ws73_wire_acb_fragment(
            out: *mut u8,
            capacity: usize,
            sequence: c_uint,
            handle: c_uint,
            boundary: c_uint,
            maximum: c_uint,
            payload: *const u8,
            size: usize,
        ) -> c_int;
        fn ws73_wire_acb_fragment_decode(
            data: *const u8,
            size: usize,
            maximum: c_uint,
            handle: *mut c_uint,
            boundary: *mut c_uint,
            payload: *mut *const u8,
            size_out: *mut usize,
        ) -> c_int;
        fn ws73_wire_receive(
            data: *const u8,
            size: usize,
            consumer: unsafe extern "C" fn(*mut c_void, c_uint, c_uint, *const u8, usize) -> c_int,
            context: *mut c_void,
        ) -> c_int;
    }
    fn c_result(result: c_int) -> io::Result<usize> {
        if result < 0 {
            Err(io::Error::from_raw_os_error(-result))
        } else {
            Ok(result as usize)
        }
    }
    pub(super) fn command(
        sequence: u32,
        opcode: u16,
        parameters: &[u8],
    ) -> io::Result<EncodedPacket> {
        let mut bytes = vec![0; 64 + (9 + parameters.len()).max(64)];
        // SAFETY: finite owned output capacity and live immutable input; actual
        // pinned C rejects all invalid arguments before copying/writing.
        let n = c_result(unsafe {
            ws73_wire_command(
                bytes.as_mut_ptr(),
                bytes.len(),
                sequence,
                opcode.into(),
                parameters.as_ptr(),
                parameters.len(),
            )
        })?;
        if n > bytes.len() {
            return Err(io::Error::other("C output exceeds owned capacity"));
        }
        bytes.truncate(n);
        Ok(EncodedPacket {
            kind: TransmitKind::Command,
            bytes,
        })
    }
    pub(super) fn acb(
        sequence: u32,
        handle: u16,
        boundary: Boundary,
        maximum: u16,
        payload: &[u8],
    ) -> io::Result<EncodedPacket> {
        let mut bytes = vec![0; 64 + (9 + payload.len()).max(64)];
        // SAFETY: all lengths bounded above, output/input alive for this call.
        let n = c_result(unsafe {
            ws73_wire_acb_fragment(
                bytes.as_mut_ptr(),
                bytes.len(),
                sequence,
                handle.into(),
                boundary as u32,
                maximum.into(),
                payload.as_ptr(),
                payload.len(),
            )
        })?;
        if n > bytes.len() {
            return Err(io::Error::other("C output exceeds owned capacity"));
        }
        bytes.truncate(n);
        Ok(EncodedPacket {
            kind: TransmitKind::Acb,
            bytes,
        })
    }
    #[derive(Clone, Copy)]
    struct Slot {
        service: u32,
        queue: u32,
        offset: usize,
        size: usize,
    }
    struct Collector<'a> {
        input: &'a [u8],
        slots: [Option<Slot>; MAX_RX_SLOTS],
        count: usize,
    }
    fn range(input: &[u8], pointer: *const u8, size: usize) -> Option<usize> {
        let offset = (pointer as usize).checked_sub(input.as_ptr() as usize)?;
        (offset.checked_add(size)? <= input.len()).then_some(offset)
    }
    unsafe extern "C" fn collect(
        context: *mut c_void,
        service: c_uint,
        queue: c_uint,
        payload: *const u8,
        size: usize,
    ) -> c_int {
        if context.is_null() {
            return -1;
        }
        // SAFETY: receive supplies this live uniquely borrowed Collector to the
        // synchronous C function. No callback allocates, waits or can unwind.
        let context = unsafe { &mut *context.cast::<Collector<'_>>() };
        let Some(offset) = range(context.input, payload, size) else {
            return -1;
        };
        let Some(slot) = context.slots.get_mut(context.count) else {
            return -1;
        };
        *slot = Some(Slot {
            service,
            queue,
            offset,
            size,
        });
        context.count += 1;
        0
    }
    fn acb_packet(data: &[u8], maximum: u16) -> io::Result<DevicePacket<'_>> {
        let (mut handle, mut boundary, mut size) = (0, 0, 0);
        let mut payload = std::ptr::null();
        // SAFETY: live input and writable local scalars; pinned decoder returns
        // an interior pointer, validated again as an offset before borrowing.
        c_result(unsafe {
            ws73_wire_acb_fragment_decode(
                data.as_ptr(),
                data.len(),
                maximum.into(),
                &mut handle,
                &mut boundary,
                &mut payload,
                &mut size,
            )
        })?;
        let offset = range(data, payload, size)
            .ok_or_else(|| io::Error::other("C payload outside input"))?;
        let boundary = match boundary {
            0 => Boundary::Full,
            1 => Boundary::First,
            2 => Boundary::Middle,
            3 => Boundary::Last,
            _ => return Err(io::Error::other("C returned invalid PB")),
        };
        if handle > 0x0fff || data.len() < 5 {
            return Err(io::Error::other("C returned invalid ACB"));
        }
        // Projection only after the actual C decoder validated handle/flags;
        // priority remains independent, and no TCID is inferred from the handle.
        Ok(DevicePacket::Acb {
            handle: handle as u16,
            boundary,
            priority: data[2] & 0x80 != 0,
            payload: &data[offset..offset + size],
            original: data,
        })
    }
    pub(super) fn receive(data: &[u8], maximum: u16) -> io::Result<Vec<DevicePacket<'_>>> {
        let mut collector = Collector {
            input: data,
            slots: [None; MAX_RX_SLOTS],
            count: 0,
        };
        // SAFETY: synchronous callback, live input and unique stack context;
        // callback only records bounded offsets. No user callback escapes.
        c_result(unsafe {
            ws73_wire_receive(
                data.as_ptr(),
                data.len(),
                collect,
                (&mut collector as *mut Collector<'_>).cast(),
            )
        })?;
        let mut packets = Vec::with_capacity(collector.count);
        for slot in &collector.slots[..collector.count] {
            let slot = slot.ok_or_else(|| io::Error::other("C callback slot missing"))?;
            let payload = &data[slot.offset..slot.offset + slot.size];
            let packet = match (slot.service, slot.queue) {
                (5, 10) => DevicePacket::Bsle(payload),
                (1, 9) => DevicePacket::Platform(payload),
                (10, 8) => match payload.first() {
                    Some(0xa2) if payload.len() >= 5 => {
                        // Transport-level type/length framing only. Event schemas,
                        // credit, Complete matching and state stay in the Host.
                        let size = u16::from_le_bytes([payload[3], payload[4]]) as usize;
                        if size != payload.len() - 5 {
                            return Err(io::Error::new(
                                io::ErrorKind::InvalidData,
                                "DLI Event length mismatch",
                            ));
                        }
                        DevicePacket::Event {
                            code: u16::from_le_bytes([payload[1], payload[2]]),
                            parameters: &payload[5..],
                            original: payload,
                        }
                    }
                    Some(0xa3) => acb_packet(payload, maximum)?,
                    _ => {
                        return Err(io::Error::new(
                            io::ErrorKind::Unsupported,
                            "unsupported/malformed inbound SLE packet",
                        ));
                    }
                },
                _ => return Err(io::Error::other("C delivered unsupported route")),
            };
            packets.push(packet);
        }
        Ok(packets)
    }
}
#[cfg(not(target_os = "linux"))]
mod actual {
    use super::*;
    fn unsupported<T>() -> io::Result<T> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "production C wire execution not implemented for this platform",
        ))
    }
    pub(super) fn command(_: u32, _: u16, _: &[u8]) -> io::Result<EncodedPacket> {
        unsupported()
    }
    pub(super) fn acb(_: u32, _: u16, _: Boundary, _: u16, _: &[u8]) -> io::Result<EncodedPacket> {
        unsupported()
    }
    pub(super) fn receive(_: &[u8], _: u16) -> io::Result<Vec<DevicePacket<'_>>> {
        unsupported()
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    // Independent synthetic scatter inputs, not a second production decoder or
    // real controller. All codec calls execute the pinned actual C source.
    fn aggregate(slots: &[(u8, u8, &[u8])]) -> Vec<u8> {
        let mut data = vec![0; 92];
        data[0] = 2;
        for (index, &(kind, queue, payload)) in slots.iter().enumerate() {
            let slot = (4 + payload.len()).max(64);
            let start = data.len();
            data.resize(start + slot, 0);
            data[12 + index * 2..14 + index * 2].copy_from_slice(&(slot as u16).to_le_bytes());
            data[start] = kind;
            data[start + 1] = queue;
            data[start + 2..start + 4].copy_from_slice(&(payload.len() as u16).to_le_bytes());
            data[start + 4..start + 4 + payload.len()].copy_from_slice(payload);
        }
        let size = data.len() as u32;
        data[4..8].copy_from_slice(&size.to_le_bytes());
        data
    }
    #[test]
    fn actual_command_bytes_and_limits() {
        for size in [0, 1, 249, 250, 253, 254, 255] {
            let params: Vec<_> = (0..size).map(|n| n as u8).collect();
            let encoded = encode_command(0x78563412, 0x0406, &params).unwrap();
            let bytes = encoded.bytes();
            assert_eq!(encoded.kind(), TransmitKind::Command);
            assert_eq!(bytes.len(), 64 + (9 + size).max(64));
            assert_eq!(&bytes[8..12], &[0x12, 0x34, 0x56, 0x78]);
            let mut expected = vec![0xa0, 8];
            expected.extend_from_slice(&((5 + size) as u16).to_le_bytes());
            expected.extend_from_slice(&[0xa1, 6, 4]);
            expected.extend_from_slice(&(size as u16).to_le_bytes());
            expected.extend_from_slice(&params);
            assert_eq!(&bytes[64..73 + size], &expected);
            assert!(bytes[73 + size..].iter().all(|x| *x == 0));
        }
        assert!(encode_command(0, 0, &[]).is_err());
        assert!(encode_command(0, 1, &[0; 256]).is_err());
    }
    #[test]
    fn actual_acb_nonzero_handle_pb_priority_and_boundaries() {
        for size in [1, 249, 250, 253, 254, 255, 2047] {
            for boundary in [
                Boundary::Full,
                Boundary::First,
                Boundary::Middle,
                Boundary::Last,
            ] {
                let bytes = vec![0x9b; size];
                let tx = encode_acb(7, 0xabc, boundary, 2047, &bytes).unwrap();
                let mut packet = tx.bytes()[68..73 + size].to_vec();
                assert_eq!(
                    &packet[..5],
                    &[
                        0xa3,
                        0xbc,
                        0x0a | (boundary as u8) << 4,
                        size as u8,
                        (size >> 8) as u8
                    ]
                );
                packet[2] |= 0x80;
                let raw = aggregate(&[(0xa1, 8, &packet)]);
                let received = decode_receive(&raw, 2047).unwrap();
                assert_eq!(
                    received,
                    vec![DevicePacket::Acb {
                        handle: 0xabc,
                        boundary,
                        priority: true,
                        payload: &packet[5..],
                        original: &packet
                    }]
                );
            }
        }
        for (handle, maximum, size) in [
            (0x1000, 2047, 1),
            (1, 0, 1),
            (1, 2048, 1),
            (1, 2047, 0),
            (1, 254, 255),
        ] {
            assert!(encode_acb(0, handle, Boundary::Full, maximum, &vec![0; size]).is_err());
        }
    }
    #[test]
    fn whole_aggregate_and_all_typed_slots_are_atomic() {
        let event = [0xa2, 0x34, 0x12, 1, 0, 0x78];
        let valid = aggregate(&[(0xa1, 8, &event), (0x50, 10, &[2, 0, 0, 0])]);
        assert_eq!(decode_receive(&valid, 254).unwrap().len(), 2);
        for index in 0..valid.len() {
            assert!(decode_receive(&valid[..index], 254).is_err());
        }
        for (offset, byte) in [(4, 0), (14, 0xff), (156 + 2, 0xff), (156, 0x51)] {
            let mut invalid = valid.clone();
            invalid[offset] = byte;
            assert!(decode_receive(&invalid, 254).is_err());
        }
        let malformed_event = [0xa2, 1, 0, 2, 0, 0];
        assert!(
            decode_receive(
                &aggregate(&[(0xa0, 8, &event), (0xa0, 8, &malformed_event)]),
                254
            )
            .is_err()
        );
        let command = [0xa1, 6, 4, 0, 0];
        let icb = [0xa4, 0, 0, 0, 0];
        for wrong in [&command[..], &icb, &[]] {
            assert!(decode_receive(&aggregate(&[(0xa0, 8, wrong)]), 254).is_err());
        }
    }
    #[test]
    fn slots_empty_budget_padding_and_bad_acb_do_not_escape() {
        assert!(decode_receive(&[0; 12], 254).unwrap().is_empty());
        let mut nonzero = [0; 12];
        nonzero[11] = 1;
        assert!(decode_receive(&nonzero, 254).is_err());
        assert!(decode_receive(&vec![0; MAX_RX_BYTES + 1], 254).is_err());
        let event = [0xa2, 0, 0, 0, 0];
        let items: Vec<_> = (0..24).map(|_| (0xa1, 8, event.as_slice())).collect();
        assert_eq!(decode_receive(&aggregate(&items), 254).unwrap().len(), 24);
        let mut gap = aggregate(&items);
        gap[14..16].fill(0);
        assert!(decode_receive(&gap, 254).is_err());
        let mut raw = aggregate(&[(0xa0, 8, &event)]);
        raw[110..116].copy_from_slice(&[0xa2, 1, 0, 1, 0, 0]);
        assert_eq!(decode_receive(&raw, 254).unwrap().len(), 1); // padding is not another event
        for acb in [
            &[0xa3, 1, 0x40, 1, 0, 5][..],
            &[0xa3, 1, 0, 2, 0, 5],
            &[0xa3, 1, 0, 0, 0],
        ] {
            assert!(decode_receive(&aggregate(&[(0xa0, 8, acb)]), 254).is_err());
        }
    }
    #[test]
    fn sdk_platform_allocation_quirk_and_unknown_routes_remain_distinct() {
        let platform = [10, 0, 10, 0, 0, 0, 0, 0, 2, 0, 0, 0, 2, 0];
        let mut data = aggregate(&[(0x19, 9, &platform)]);
        data[94..96].copy_from_slice(&64u16.to_le_bytes());
        let decoded = decode_receive(&data, 254).unwrap();
        assert_eq!(decoded, vec![DevicePacket::Platform(&data[96..156])]);
        assert_eq!(&data[96..110], &platform);
        let unknown = aggregate(&[(0x90, 7, &[1, 2, 3])]);
        assert!(decode_receive(&unknown, 254).unwrap().is_empty());
        let event = [0xa2, 1, 0, 0, 0];
        let mut malformed = aggregate(&[(0xa0, 8, &event), (0x90, 7, &[1, 2, 3])]);
        malformed[158..160].copy_from_slice(&65u16.to_le_bytes());
        assert!(decode_receive(&malformed, 254).is_err());
        data[92] = 0x18;
        assert!(decode_receive(&data, 254).is_err());
        assert!(
            decode_receive(&vec![0; MAX_RX_BYTES], 254)
                .unwrap()
                .is_empty()
        );
    }
}
