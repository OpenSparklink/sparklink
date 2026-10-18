//! T/XS 20001-2025 tables 73/74: complete-PDU ReadByUUID.
//! Fragmented responses are explicitly unsupported; at most 64 local values.
use super::value::ValueError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Request<'a> {
    pub start: u16,
    pub end: u16,
    pub data_type: u8,
    pub uuid: &'a [u8],
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Item<'a> {
    pub handle: u16,
    pub value: Result<&'a [u8], u16>,
}
/// cbindgen:ignore
impl<'a> Request<'a> {
    pub fn decode(mtu: u16, raw: &'a [u8]) -> Result<Self, ValueError> {
        if raw.len() > usize::from(mtu) {
            return Err(ValueError::Mtu);
        }
        if raw.len() < 2 {
            return Err(ValueError::Length);
        }
        if raw[0] != 10 {
            return Err(ValueError::Unsupported);
        }
        if raw[1] & !1 != 0 {
            return Err(ValueError::Reserved);
        }
        if raw.len() != if raw[1] == 0 { 9 } else { 23 } {
            return Err(ValueError::Length);
        }
        // Invalid handle ranges are retained so the server can answer with the
        // specified ReadByUUID error and the original start handle.
        Ok(Self {
            start: u16::from_le_bytes([raw[2], raw[3]]),
            end: u16::from_le_bytes([raw[4], raw[5]]),
            data_type: raw[6],
            uuid: &raw[7..],
        })
    }
    pub fn encode(&self, mtu: u16, out: &mut [u8]) -> Result<usize, ValueError> {
        if !matches!(self.uuid.len(), 2 | 16) {
            return Err(ValueError::Length);
        }
        let n = 7 + self.uuid.len();
        if n > usize::from(mtu) {
            return Err(ValueError::Mtu);
        }
        if out.len() < n {
            return Err(ValueError::Output);
        }
        out[..2].copy_from_slice(&[10, u8::from(self.uuid.len() == 16)]);
        out[2..4].copy_from_slice(&self.start.to_le_bytes());
        out[4..6].copy_from_slice(&self.end.to_le_bytes());
        out[6] = self.data_type;
        out[7..n].copy_from_slice(self.uuid);
        Ok(n)
    }
}

pub fn decode(mtu: u16, raw: &[u8]) -> Result<Vec<Item<'_>>, ValueError> {
    if raw.len() > usize::from(mtu) {
        return Err(ValueError::Mtu);
    }
    if raw.len() < 4 {
        return Err(ValueError::Length);
    }
    if raw[0] != 11 {
        return Err(ValueError::Unsupported);
    }
    if raw[1] & 0xf0 != 0 {
        return Err(ValueError::Reserved);
    }
    if raw[1] & 3 != 3 {
        return Err(ValueError::Unsupported);
    }
    let multiple = raw[1] & 4 != 0;
    let has_error = raw[1] & 8 != 0;
    if !multiple {
        let handle = u16::from_le_bytes([raw[2], raw[3]]);
        let value = if has_error {
            if raw.len() != 6 {
                return Err(ValueError::Length);
            }
            let e = u16::from_le_bytes([raw[4], raw[5]]);
            if e & 0x8000 != 0 {
                return Err(ValueError::Reserved);
            }
            Err(e)
        } else {
            Ok(&raw[4..])
        };
        return Ok(vec![Item { handle, value }]);
    }
    let mut items = Vec::new();
    let mut offset = 2;
    let mut actual_error = false;
    while offset < raw.len() {
        if items.len() == 64 || raw.len() - offset < 4 {
            return Err(ValueError::Length);
        }
        let handle = u16::from_le_bytes([raw[offset], raw[offset + 1]]);
        let indicator = u16::from_le_bytes([raw[offset + 2], raw[offset + 3]]);
        offset += 4;
        let value = if indicator & 0x8000 != 0 {
            let len = usize::from(indicator & 0x7fff);
            if len > raw.len() - offset {
                return Err(ValueError::Length);
            }
            let v = &raw[offset..offset + len];
            offset += len;
            Ok(v)
        } else {
            actual_error = true;
            Err(indicator)
        };
        if items.last().is_some_and(|p: &Item<'_>| p.handle >= handle) {
            return Err(ValueError::Reserved);
        }
        items.push(Item { handle, value });
    }
    if items.len() < 2 || actual_error != has_error {
        return Err(ValueError::Reserved);
    }
    Ok(items)
}

pub fn encode(mtu: u16, items: &[Item<'_>], out: &mut [u8]) -> Result<usize, ValueError> {
    if items.is_empty() || items.len() > 64 || items.windows(2).any(|p| p[0].handle >= p[1].handle)
    {
        return Err(ValueError::Length);
    }
    let multiple = items.len() > 1;
    let mut n = 2usize;
    let mut has_error = false;
    for item in items {
        let len = match item.value {
            Ok(v) if v.len() <= 0x7fff => v.len(),
            Ok(_) => return Err(ValueError::Mtu),
            Err(e) if e & 0x8000 == 0 => {
                has_error = true;
                0
            }
            Err(_) => return Err(ValueError::Reserved),
        };
        n = n
            .checked_add(if multiple || item.value.is_err() {
                4
            } else {
                2
            })
            .and_then(|v| v.checked_add(len))
            .ok_or(ValueError::Mtu)?;
    }
    if n > usize::from(mtu) {
        return Err(ValueError::Mtu);
    }
    if n > out.len() {
        return Err(ValueError::Output);
    }
    out[..2].copy_from_slice(&[
        11,
        3 | if multiple { 4 } else { 0 } | if has_error { 8 } else { 0 },
    ]);
    let mut offset = 2;
    for item in items {
        out[offset..offset + 2].copy_from_slice(&item.handle.to_le_bytes());
        offset += 2;
        if multiple || item.value.is_err() {
            let indicator = match item.value {
                Ok(v) => 0x8000 | v.len() as u16,
                Err(e) => e,
            };
            out[offset..offset + 2].copy_from_slice(&indicator.to_le_bytes());
            offset += 2;
        }
        if let Ok(v) = item.value {
            out[offset..offset + v.len()].copy_from_slice(v);
            offset += v.len();
        }
    }
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn single_multi_errors_and_atomic_limits() {
        for raw in [
            &[11, 3, 17, 0, 1, 2][..],
            &[11, 11, 17, 0, 6, 0][..],
            &[11, 15, 17, 0, 2, 128, 1, 2, 18, 0, 6, 0][..],
        ] {
            let items = decode(249, raw).unwrap();
            let mut out = [0xa5; 32];
            let n = encode(249, &items, &mut out).unwrap();
            assert_eq!(&out[..n], raw);
            assert!(out[n..].iter().all(|b| *b == 0xa5));
            let before = out;
            assert!(encode((n - 1) as u16, &items, &mut out).is_err());
            assert_eq!(out, before);
        }
        for len in 0..=9 {
            for control in 0..=255 {
                let mut raw = [0; 9];
                raw[0] = 11;
                raw[1] = control;
                if let Ok(items) = decode(9, &raw[..len]) {
                    let mut out = [0; 9];
                    let n = encode(9, &items, &mut out).unwrap();
                    assert_eq!(&out[..n], &raw[..len]);
                }
            }
        }
        assert!(decode(249, &[11, 7, 17, 0, 2, 128, 1]).is_err());
        let request = Request {
            start: 16,
            end: 65535,
            data_type: 0,
            uuid: &[1; 16],
        };
        let mut out = [0; 23];
        let n = request.encode(249, &mut out).unwrap();
        assert_eq!(Request::decode(249, &out[..n]).unwrap(), request);
    }
}
