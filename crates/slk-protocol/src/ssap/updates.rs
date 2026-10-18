//! T/XS 20001-2025 tables 78..80, complete property/event updates and ACKs.
//! A decoded packet is not remote subscription, authentication or app processing.
use super::value::ValueError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Item<'a> {
    pub handle: u16,
    pub value: &'a [u8],
}
#[derive(Debug, PartialEq, Eq)]
pub struct Update<'a> {
    pub indication: bool,
    pub event: bool,
    pub items: Vec<Item<'a>>,
}
/// cbindgen:ignore
impl<'a> Update<'a> {
    pub fn decode(mtu: u16, raw: &'a [u8]) -> Result<Self, ValueError> {
        if raw.len() > usize::from(mtu) {
            return Err(ValueError::Mtu);
        }
        if raw.len() < 6 {
            return Err(ValueError::Length);
        }
        if !matches!(raw[0], 15 | 16) {
            return Err(ValueError::Unsupported);
        }
        if raw[1] & !7 != 0 {
            return Err(ValueError::Reserved);
        }
        if raw[1] & 3 != 3 {
            return Err(ValueError::Unsupported);
        }
        let mut offset = 2;
        let mut items = Vec::new();
        while offset < raw.len() {
            if items.len() >= 64 || raw.len() - offset < 4 {
                return Err(ValueError::Length);
            }
            let handle = u16::from_le_bytes([raw[offset], raw[offset + 1]]);
            let len = usize::from(u16::from_le_bytes([raw[offset + 2], raw[offset + 3]]));
            offset += 4;
            if handle == 0 || len > raw.len() - offset {
                return Err(ValueError::Length);
            }
            if items.iter().any(|item: &Item<'_>| item.handle == handle) {
                return Err(ValueError::Reserved);
            }
            items.push(Item {
                handle,
                value: &raw[offset..offset + len],
            });
            offset += len;
        }
        Ok(Self {
            indication: raw[0] == 16,
            event: raw[1] & 4 != 0,
            items,
        })
    }
    pub fn encode(&self, mtu: u16, out: &mut [u8]) -> Result<usize, ValueError> {
        if self.items.is_empty() || self.items.len() > 64 {
            return Err(ValueError::Length);
        }
        let mut size = 2usize;
        for (i, item) in self.items.iter().enumerate() {
            if item.handle == 0 || self.items[..i].iter().any(|v| v.handle == item.handle) {
                return Err(ValueError::Reserved);
            }
            if item.value.len() > 65535 {
                return Err(ValueError::Mtu);
            }
            size = size
                .checked_add(4)
                .and_then(|s| s.checked_add(item.value.len()))
                .ok_or(ValueError::Mtu)?;
        }
        if size > usize::from(mtu) {
            return Err(ValueError::Mtu);
        }
        if out.len() < size {
            return Err(ValueError::Output);
        }
        out[..2].copy_from_slice(&[
            if self.indication { 16 } else { 15 },
            3 | if self.event { 4 } else { 0 },
        ]);
        let mut offset = 2;
        for item in &self.items {
            out[offset..offset + 2].copy_from_slice(&item.handle.to_le_bytes());
            out[offset + 2..offset + 4].copy_from_slice(&(item.value.len() as u16).to_le_bytes());
            offset += 4;
            out[offset..offset + item.value.len()].copy_from_slice(item.value);
            offset += item.value.len();
        }
        Ok(size)
    }
}
pub fn ack(mtu: u16, event: bool, flags: &[u8], out: &mut [u8]) -> Result<usize, ValueError> {
    if flags.is_empty() || flags.len() > 64 || flags.iter().any(|v| *v > 1) {
        return Err(ValueError::Length);
    }
    let size = 2 + flags.len();
    if size > usize::from(mtu) {
        return Err(ValueError::Mtu);
    }
    if size > out.len() {
        return Err(ValueError::Output);
    }
    out[..2].copy_from_slice(&[17, 3 | if event { 4 } else { 0 }]);
    out[2..size].copy_from_slice(flags);
    Ok(size)
}
pub fn decode_ack(mtu: u16, raw: &[u8], event: bool, count: usize) -> Result<&[u8], ValueError> {
    if raw.len() > usize::from(mtu) {
        return Err(ValueError::Mtu);
    }
    if count == 0 || count > 64 || raw.len() != 2 + count {
        return Err(ValueError::Length);
    }
    if raw[0] != 17 || raw[1] != (3 | if event { 4 } else { 0 }) {
        return Err(ValueError::Unsupported);
    }
    if raw[2..].iter().any(|v| *v > 1) {
        return Err(ValueError::Reserved);
    }
    Ok(&raw[2..])
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_vectors_multiple_values_empty_value_and_atomic_refusal() {
        for raw in [
            &[15, 3, 17, 0, 2, 0, 8, 9][..],
            &[16, 3, 17, 0, 0, 0, 18, 0, 1, 0, 7][..],
            &[16, 7, 17, 0, 1, 0, 9][..],
        ] {
            let packet = Update::decode(249, raw).unwrap();
            let mut out = [0xa5; 32];
            let n = packet.encode(249, &mut out).unwrap();
            assert_eq!(&out[..n], raw);
            let before = out;
            assert_eq!(
                packet.encode((n - 1) as u16, &mut out),
                Err(ValueError::Mtu)
            );
            assert_eq!(before, out);
        }
        let mut out = [0xa5; 8];
        let n = ack(249, false, &[1, 0], &mut out).unwrap();
        assert_eq!(&out[..n], &[17, 3, 1, 0]);
        assert_eq!(decode_ack(249, &out[..n], false, 2).unwrap(), [1, 0]);
        let before = out;
        assert!(ack(249, false, &[2], &mut out).is_err());
        assert_eq!(before, out);
    }
    #[test]
    fn malformed_fragment_reserved_duplicate_and_short_packets_fail() {
        for raw in [
            &[16, 0, 17, 0, 0, 0][..],
            &[16, 11, 17, 0, 0, 0][..],
            &[16, 3, 17, 0, 2, 0, 9][..],
            &[16, 3, 17, 0, 0, 0, 17, 0, 0, 0][..],
            &[16, 3, 0, 0, 0, 0][..],
        ] {
            assert!(Update::decode(249, raw).is_err());
        }
        for op in [15, 16] {
            for control in 0..=255 {
                for len in 0..=10 {
                    let mut raw = [0; 10];
                    raw[0] = op;
                    raw[1] = control;
                    raw[2] = 17;
                    if let Ok(packet) = Update::decode(10, &raw[..len]) {
                        let mut out = [0; 10];
                        let n = packet.encode(10, &mut out).unwrap();
                        assert_eq!(&out[..n], &raw[..len]);
                    }
                }
            }
        }
    }
}
