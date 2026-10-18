//! Base single-response discovery (tables54..68). Ordered entries and bounded
//! parsing; no automatic multi-response mode or fragmentation promise.
use super::SsapOperations;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FindKind {
    Structure,
    Primary,
    Properties,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntryClass {
    Standard,
    Custom,
    Mixed,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FindError {
    Length,
    Reserved,
    Unsupported,
    Handle,
    Capacity,
    Metadata,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FindRequest<'a> {
    pub kind: FindKind,
    pub class: EntryClass,
    pub start: u16,
    pub end: u16,
    pub uuid: Option<&'a [u8]>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    pub category: u8,
    pub handle: u16,
    pub end: u16,
    pub uuid: Vec<u8>,
    pub operations: u32,
    pub descriptors: Vec<u8>,
    pub members: u8,
}
/// cbindgen:ignore
impl Entry {
    pub fn custom(&self) -> bool {
        self.uuid.len() == 16
    }
}
/// cbindgen:ignore
impl<'a> FindRequest<'a> {
    pub fn opcode(&self) -> u8 {
        if self.uuid.is_some() { 6 } else { 4 }
    }
    pub fn control(&self) -> u8 {
        (match self.kind {
            FindKind::Structure => 0,
            FindKind::Primary => 1,
            FindKind::Properties => 3,
        }) | match self.class {
            EntryClass::Standard => 0,
            EntryClass::Custom => 8,
            EntryClass::Mixed => 16,
        }
    }
    pub fn encode(&self, mtu: u16, out: &mut [u8]) -> Result<usize, FindError> {
        if self.start == 0 || self.start > self.end {
            return Err(FindError::Handle);
        }
        let len = 6 + self.uuid.map_or(0, |u| u.len());
        if self.uuid.is_some_and(|u| !matches!(u.len(), 2 | 16)) {
            return Err(FindError::Length);
        }
        if len > usize::from(mtu) || out.len() < len {
            return Err(FindError::Capacity);
        }
        out[0] = self.opcode();
        out[1] = self.control();
        out[2..4].copy_from_slice(&self.start.to_le_bytes());
        out[4..6].copy_from_slice(&self.end.to_le_bytes());
        if let Some(uuid) = self.uuid {
            out[6..len].copy_from_slice(uuid);
        }
        Ok(len)
    }
    pub fn decode(mtu: u16, raw: &'a [u8]) -> Result<Self, FindError> {
        if raw.len() < 6 || raw.len() > usize::from(mtu) {
            return Err(FindError::Length);
        }
        if !matches!(raw[0], 4 | 6) {
            return Err(FindError::Unsupported);
        }
        if raw[1] & 0xc0 != 0 || raw[1] & 24 == 24 {
            return Err(FindError::Reserved);
        }
        if raw[1] & 32 != 0 {
            return Err(FindError::Unsupported);
        }
        let kind = match raw[1] & 7 {
            0 => FindKind::Structure,
            1 => FindKind::Primary,
            3 => FindKind::Properties,
            _ => return Err(FindError::Unsupported),
        };
        let class = match raw[1] & 24 {
            0 => EntryClass::Standard,
            8 => EntryClass::Custom,
            _ => EntryClass::Mixed,
        };
        if (raw[0] == 4 && raw.len() != 6) || (raw[0] == 6 && !matches!(raw.len(), 8 | 22)) {
            return Err(FindError::Length);
        }
        let request = Self {
            kind,
            class,
            start: u16::from_le_bytes([raw[2], raw[3]]),
            end: u16::from_le_bytes([raw[4], raw[5]]),
            uuid: (raw[0] == 6).then_some(&raw[6..]),
        };
        if request.start == 0 || request.start > request.end {
            return Err(FindError::Handle);
        }
        Ok(request)
    }
    pub fn accepts(&self, uuid: &[u8]) -> bool {
        match self.class {
            EntryClass::Standard => uuid.len() == 2,
            EntryClass::Custom => uuid.len() == 16,
            EntryClass::Mixed => matches!(uuid.len(), 2 | 16),
        }
    }
}
fn bytes<'a>(raw: &'a [u8], offset: &mut usize, len: usize) -> Result<&'a [u8], FindError> {
    let end = offset.checked_add(len).ok_or(FindError::Length)?;
    let v = raw.get(*offset..end).ok_or(FindError::Length)?;
    *offset = end;
    Ok(v)
}
fn word(raw: &[u8], offset: &mut usize) -> Result<u16, FindError> {
    let v = bytes(raw, offset, 2)?;
    Ok(u16::from_le_bytes([v[0], v[1]]))
}
/// Decode using the original request's schema, not the received opcode alone.
pub fn decode_page(
    request: FindRequest<'_>,
    mtu: u16,
    raw: &[u8],
) -> Result<Vec<Entry>, FindError> {
    if raw.len() < 3 || raw.len() > usize::from(mtu) {
        return Err(FindError::Length);
    }
    if raw[0] != request.opcode() + 1 {
        return Err(FindError::Metadata);
    }
    if raw[1] & 0xf0 != 0 || raw[1] & 12 == 12 {
        return Err(FindError::Reserved);
    }
    if raw[1] & 3 != 3 {
        return Err(FindError::Unsupported);
    }
    let mode = (raw[1] >> 2) & 3;
    let mut offset = 2;
    let mut group_left = 0usize;
    let mut group_custom = mode == 1;
    let mut entries = Vec::new();
    let mut last = 0;
    while offset < raw.len() {
        if entries.len() >= 80 {
            return Err(FindError::Capacity);
        }
        if request.kind != FindKind::Structure && mode == 2 && group_left == 0 {
            let header = bytes(raw, &mut offset, 1)?[0];
            group_left = usize::from(header & 127);
            group_custom = header & 128 != 0;
            if group_left == 0 {
                return Err(FindError::Metadata);
            }
        }
        let handle = word(raw, &mut offset)?;
        if handle < request.start || handle > request.end || handle <= last {
            return Err(FindError::Handle);
        }
        last = handle;
        let mut category = match request.kind {
            FindKind::Primary => 0,
            FindKind::Properties => 2,
            FindKind::Structure => bytes(raw, &mut offset, 1)?[0],
        };
        if request.kind == FindKind::Structure {
            if !matches!(category, 0 | 1 | 2 | 3 | 4 | 8 | 9 | 10 | 11 | 12) {
                return Err(FindError::Unsupported);
            }
            group_custom = category & 8 != 0;
            if (mode == 0 && group_custom) || (mode == 1 && !group_custom) {
                return Err(FindError::Metadata);
            }
        } else if group_custom {
            category += 8;
        }
        let mut end = if request.kind == FindKind::Primary {
            word(raw, &mut offset)?
        } else {
            handle
        };
        if end < handle {
            return Err(FindError::Handle);
        }
        let uuid = bytes(raw, &mut offset, if group_custom { 16 } else { 2 })?.to_vec();
        if !request.accepts(&uuid) {
            return Err(FindError::Metadata);
        }
        let (operations, descriptors, members) = if request.kind == FindKind::Primary {
            let members = bytes(raw, &mut offset, 1)?[0];
            if members & 0xf0 != 0 {
                return Err(FindError::Reserved);
            }
            (0, Vec::new(), members)
        } else {
            let operations = if category & 7 >= 2 {
                let b = bytes(raw, &mut offset, 4)?;
                u32::from_le_bytes([b[0], b[1], b[2], b[3]])
            } else {
                end = 0;
                0
            };
            SsapOperations::from_bits(operations).map_err(|_| FindError::Reserved)?;
            let n = usize::from(bytes(raw, &mut offset, 1)?[0]);
            let descriptors = bytes(raw, &mut offset, n)?.to_vec();
            (operations, descriptors, 0)
        };
        entries.push(Entry {
            category,
            handle,
            end,
            uuid,
            operations,
            descriptors,
            members,
        });
        if request.kind != FindKind::Structure && mode == 2 {
            group_left -= 1;
        }
    }
    if group_left != 0 || entries.is_empty() {
        return Err(FindError::Length);
    }
    Ok(entries)
}
/// Encode one ascending prefix; callers paginate by the last returned handle.
pub fn encode_page(
    request: FindRequest<'_>,
    mtu: u16,
    entries: &[Entry],
) -> Result<(Vec<u8>, usize), FindError> {
    if entries.len() > 80 {
        return Err(FindError::Capacity);
    }
    let mut out = vec![request.opcode() + 1, 11];
    let mut count = 0;
    let mut last = 0;
    for e in entries {
        if e.handle < request.start
            || e.handle > request.end
            || e.handle <= last
            || !request.accepts(&e.uuid)
        {
            return Err(FindError::Handle);
        }
        last = e.handle;
        if (e.category & 8 != 0) != e.custom() {
            return Err(FindError::Metadata);
        }
        let mut item = Vec::new();
        if request.kind != FindKind::Structure {
            item.push(if e.custom() { 129 } else { 1 });
        }
        item.extend(e.handle.to_le_bytes());
        match request.kind {
            FindKind::Structure => {
                if !matches!(e.category, 0 | 8 | 2 | 10) {
                    return Err(FindError::Unsupported);
                }
                item.push(e.category);
            }
            FindKind::Primary => {
                if !matches!(e.category, 0 | 8) || e.end < e.handle || e.members & 0xf0 != 0 {
                    return Err(FindError::Metadata);
                }
                item.extend(e.end.to_le_bytes());
            }
            FindKind::Properties => {
                if !matches!(e.category, 2 | 10) {
                    return Err(FindError::Metadata);
                }
            }
        }
        item.extend(&e.uuid);
        if request.kind == FindKind::Primary {
            item.push(e.members);
        } else {
            if e.category & 7 >= 2 {
                SsapOperations::from_bits(e.operations).map_err(|_| FindError::Reserved)?;
                item.extend(e.operations.to_le_bytes());
            }
            if e.descriptors.len() > 255 {
                return Err(FindError::Capacity);
            }
            item.push(e.descriptors.len() as u8);
            item.extend(&e.descriptors);
        }
        if out.len() + item.len() > usize::from(mtu) {
            break;
        }
        out.extend(item);
        count += 1;
    }
    if count == 0 {
        return Err(FindError::Capacity);
    }
    Ok((out, count))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn primary_property_full_and_uuid_schema_roundtrip() {
        let primary = Entry {
            category: 0,
            handle: 16,
            end: 17,
            uuid: vec![0x0a, 6],
            operations: 0,
            descriptors: vec![],
            members: 2,
        };
        let property = Entry {
            category: 2,
            handle: 17,
            end: 17,
            uuid: vec![0x34, 0x10],
            operations: 5,
            descriptors: vec![],
            members: 0,
        };
        for kind in [FindKind::Primary, FindKind::Properties, FindKind::Structure] {
            let r = FindRequest {
                kind,
                class: EntryClass::Mixed,
                start: 16,
                end: 17,
                uuid: None,
            };
            let entries = match kind {
                FindKind::Primary => vec![primary.clone()],
                FindKind::Properties => vec![property.clone()],
                _ => vec![primary.clone(), property.clone()],
            };
            let (raw, n) = encode_page(r, 249, &entries).unwrap();
            assert_eq!(n, entries.len());
            let decoded = decode_page(r, 249, &raw).unwrap();
            assert_eq!(decoded.len(), entries.len());
            assert_eq!(
                decoded[0].handle,
                16 + u16::from(kind == FindKind::Properties)
            );
            for len in 0..raw.len() {
                if let Ok(part) = decode_page(r, 249, &raw[..len]) {
                    assert!(kind == FindKind::Structure && part.len() == 1);
                }
            }
        }
        let r = FindRequest {
            kind: FindKind::Primary,
            class: EntryClass::Custom,
            start: 1,
            end: 65535,
            uuid: Some(&[1; 16]),
        };
        let mut out = [0xa5; 22];
        assert_eq!(r.encode(249, &mut out), Ok(22));
        assert_eq!(FindRequest::decode(249, &out), Ok(r));
        let old = out;
        assert_eq!(r.encode(21, &mut out), Err(FindError::Capacity));
        assert_eq!(out, old);
    }
    #[test]
    fn pagination_and_reserved_or_unordered_data_fail_closed() {
        let r = FindRequest {
            kind: FindKind::Primary,
            class: EntryClass::Mixed,
            start: 1,
            end: 65535,
            uuid: None,
        };
        let e = Entry {
            category: 8,
            handle: 16,
            end: 17,
            uuid: vec![1; 16],
            operations: 0,
            descriptors: vec![],
            members: 2,
        };
        let mut second = e.clone();
        second.handle = 18;
        second.end = 19;
        let (raw, n) = encode_page(r, 24, &[e.clone(), second]).unwrap();
        assert_eq!(n, 1);
        assert_eq!(decode_page(r, 24, &raw).unwrap(), vec![e]);
        let mut bad = raw.clone();
        bad[1] |= 0x80;
        assert_eq!(decode_page(r, 249, &bad), Err(FindError::Reserved));
        let mut bad = raw.clone();
        bad.extend(&raw[2..]);
        assert_eq!(decode_page(r, 249, &bad), Err(FindError::Handle));
    }
}
