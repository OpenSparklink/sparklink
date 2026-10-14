//! Bounded adapter-local service data. Handles are never reused within this
//! registration. Local insertion is not remote discovery/publication success.
use slk_protocol::ssap::discovery::{Entry, FindKind, FindRequest, encode_page};
use slk_protocol::{SsapOperations, ssap::value::ValuePdu};
use std::collections::BTreeMap;

pub(crate) type PropertyDefinition = (Vec<u8>, u32, Vec<u8>);
pub(crate) type LocalService = (u16, u16, Vec<u8>, Vec<(u16, Vec<u8>, u32)>);
struct Property {
    uuid: Vec<u8>,
    operations: SsapOperations,
    value: Vec<u8>,
}
struct Service {
    end: u16,
    uuid: Vec<u8>,
    properties: BTreeMap<u16, Property>,
}
pub(crate) struct Database {
    next: u32,
    bytes: usize,
    services: BTreeMap<u16, Service>,
}
impl Default for Database {
    fn default() -> Self {
        Self {
            next: 16,
            bytes: 0,
            services: BTreeMap::new(),
        }
    }
}
impl Database {
    pub(crate) fn register(
        &mut self,
        uuid: Vec<u8>,
        definitions: Vec<PropertyDefinition>,
    ) -> Result<(u16, u16, Vec<u16>), String> {
        fn uuid_valid(v: &[u8]) -> bool {
            matches!(v.len(), 2 | 16) && v.iter().any(|b| *b != 0)
        }
        if !uuid_valid(&uuid) || definitions.is_empty() {
            return Err("invalid UUID or empty service".into());
        }
        let count: usize = self.services.values().map(|s| s.properties.len()).sum();
        if self.services.len() >= 16 || count + definitions.len() > 64 {
            return Err("local database capacity".into());
        }
        let mut added = 0;
        for (uuid, ops, value) in &definitions {
            let ops = SsapOperations::from_bits(*ops).map_err(|e| e.to_string())?;
            if !uuid_valid(uuid) || ops.bits() & !5 != 0 {
                return Err(
                    "only value READ/WRITE_WITH_RSP permissions currently supported".into(),
                );
            }
            if value.len() > 2042 {
                return Err("local value exceeds bounded database limit".into());
            }
            added += value.len();
        }
        if self.bytes + added > 8192 {
            return Err("local database byte budget".into());
        }
        let end = self.next + definitions.len() as u32;
        if end > u32::from(u16::MAX) {
            return Err("local handle namespace exhausted".into());
        }
        let start = self.next as u16;
        let end = end as u16;
        let properties = definitions
            .into_iter()
            .enumerate()
            .map(|(i, (uuid, ops, value))| {
                (
                    (self.next + 1 + i as u32) as u16,
                    Property {
                        uuid,
                        operations: SsapOperations::from_bits(ops).expect("validated"),
                        value,
                    },
                )
            })
            .collect::<BTreeMap<_, _>>();
        let handles = properties.keys().copied().collect();
        self.services.insert(
            start,
            Service {
                end,
                uuid,
                properties,
            },
        );
        self.bytes += added;
        self.next = u32::from(end) + 1;
        Ok((start, end, handles))
    }
    pub(crate) fn list(&self) -> Vec<LocalService> {
        self.services
            .iter()
            .map(|(start, s)| {
                (
                    *start,
                    s.end,
                    s.uuid.clone(),
                    s.properties
                        .iter()
                        .map(|(h, p)| (*h, p.uuid.clone(), p.operations.bits()))
                        .collect(),
                )
            })
            .collect()
    }
    pub(crate) fn remove(&mut self, start: u16) -> Result<(), String> {
        let s = self
            .services
            .remove(&start)
            .ok_or("unknown local service")?;
        self.bytes -= s.properties.values().map(|p| p.value.len()).sum::<usize>();
        Ok(())
    }
    pub(crate) fn find(&self, request: FindRequest<'_>, mtu: u16) -> Result<Vec<u8>, String> {
        let mut entries = Vec::new();
        for (start, service) in &self.services {
            let matched = request.uuid.is_none_or(|uuid| uuid == service.uuid);
            if matches!(request.kind, FindKind::Primary | FindKind::Structure)
                && matched
                && *start >= request.start
                && *start <= request.end
                && request.accepts(&service.uuid)
            {
                entries.push(Entry {
                    category: if service.uuid.len() == 16 { 8 } else { 0 },
                    handle: *start,
                    end: service.end,
                    uuid: service.uuid.clone(),
                    operations: 0,
                    descriptors: vec![],
                    members: 2,
                });
            }
            if matches!(request.kind, FindKind::Properties | FindKind::Structure) {
                for (handle, property) in &service.properties {
                    let included = matched
                        || (request.kind == FindKind::Properties
                            && request.uuid.is_some_and(|uuid| uuid == property.uuid));
                    if included
                        && *handle >= request.start
                        && *handle <= request.end
                        && request.accepts(&property.uuid)
                    {
                        entries.push(Entry {
                            category: if property.uuid.len() == 16 { 10 } else { 2 },
                            handle: *handle,
                            end: *handle,
                            uuid: property.uuid.clone(),
                            operations: property.operations.bits(),
                            descriptors: vec![],
                            members: 0,
                        });
                    }
                }
            }
        }
        if entries.is_empty() {
            let mut out = vec![0; 6];
            ValuePdu::Error {
                request: request.opcode(),
                handle: request.start,
                error: 11,
            }
            .encode(mtu, &mut out)
            .map_err(|e| format!("find error codec: {e:?}"))?;
            return Ok(out);
        }
        encode_page(request, mtu, &entries)
            .map(|v| v.0)
            .map_err(|e| format!("find page codec: {e:?}"))
    }
    pub(crate) fn read_uuid(
        &self,
        request: slk_protocol::ssap::read_uuid::Request<'_>,
        mtu: u16,
    ) -> Result<Vec<u8>, String> {
        use slk_protocol::ssap::read_uuid::{Item, encode};
        let mut items = Vec::new();
        if request.start == 0 || request.start > request.end {
            items.push(Item {
                handle: request.start,
                value: Err(4),
            });
        } else {
            for service in self.services.values() {
                for (handle, p) in service.properties.range(request.start..=request.end) {
                    if p.uuid == request.uuid {
                        let value = if request.data_type != 0 {
                            Err(13)
                        } else if !p.operations.contains(SsapOperations::READ) {
                            Err(6)
                        } else {
                            Ok(p.value.as_slice())
                        };
                        items.push(Item {
                            handle: *handle,
                            value,
                        });
                    }
                }
            }
            if items.is_empty() {
                items.push(Item {
                    handle: request.start,
                    value: Err(11),
                });
            }
        }
        let mut out = vec![0; usize::from(mtu)];
        match encode(mtu, &items, &mut out) {
            Ok(n) => {
                out.truncate(n);
                Ok(out)
            }
            // The normative no-fragmentation exception uses READ_RSP, not
            // a truncated ReadByUUID list or a fabricated success.
            Err(slk_protocol::ssap::value::ValueError::Mtu) => {
                let n = ValuePdu::ReadError(16)
                    .encode(mtu, &mut out)
                    .map_err(|e| format!("read UUID size error: {e:?}"))?;
                out.truncate(n);
                Ok(out)
            }
            Err(e) => Err(format!("read UUID codec: {e:?}")),
        }
    }
    fn property(&self, handle: u16) -> Option<&Property> {
        self.services
            .values()
            .find_map(|s| s.properties.get(&handle))
    }
    pub(crate) fn local_read(&self, handle: u16) -> Result<Vec<u8>, String> {
        self.property(handle)
            .map(|p| p.value.clone())
            .ok_or_else(|| "unknown local property".into())
    }
    /// Returns a real protocol response. Mutates only on validated single-value
    /// writes with sufficient permission, value budget and negotiated PDU size.
    pub(crate) fn answer(&mut self, request: ValuePdu<'_>, mtu: u16) -> Result<Vec<u8>, String> {
        let mut out = vec![0; usize::from(mtu)];
        let response = match request {
            ValuePdu::Read { handle, data_type } => match self.property(handle) {
                None => ValuePdu::ReadError(4),
                Some(_) if data_type != 0 => ValuePdu::ReadError(13),
                Some(p) if !p.operations.contains(SsapOperations::READ) => ValuePdu::ReadError(6),
                Some(p) if p.value.len() + 2 > usize::from(mtu) => ValuePdu::Error {
                    request: 8,
                    handle: 0,
                    error: 16,
                },
                Some(p) => ValuePdu::ReadValue(&p.value),
            },
            ValuePdu::Write {
                handle,
                data_type,
                value,
                verify,
            } => {
                let error = match self.property(handle) {
                    None => Some(4),
                    Some(_) if data_type != 0 => Some(13),
                    Some(p) if !p.operations.contains(SsapOperations::WRITE_WITH_RSP) => Some(7),
                    Some(p)
                        if value.len() > 2042
                            || self.bytes - p.value.len() + value.len() > 8192 =>
                    {
                        Some(5)
                    }
                    _ => None,
                };
                if let Some(error) = error {
                    ValuePdu::WriteError { handle, error }
                } else {
                    if value.len() + 5 > usize::from(mtu) {
                        return Err("write exceeds negotiated PDU".into());
                    }
                    let p = self
                        .services
                        .values_mut()
                        .find_map(|s| s.properties.get_mut(&handle))
                        .expect("checked property");
                    self.bytes = self.bytes - p.value.len() + value.len();
                    p.value = value.to_vec();
                    if verify {
                        ValuePdu::WrittenValue {
                            handle,
                            data_type,
                            value,
                        }
                    } else {
                        ValuePdu::Written
                    }
                }
            }
            _ => return Err("not a value request".into()),
        };
        let size = response
            .encode(mtu, &mut out)
            .map_err(|e| format!("response codec: {e:?}"))?;
        out.truncate(size);
        Ok(out)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn discovery_uses_real_local_metadata_and_reserved_handle_floor() {
        use slk_protocol::ssap::discovery::{EntryClass, decode_page};
        let mut d = Database::default();
        let (start, end, handles) = d
            .register(vec![9; 16], vec![(vec![7; 16], 5, vec![1])])
            .unwrap();
        assert_eq!((start, end, handles[0]), (16, 17, 17));
        for (kind, uuid, expected) in [
            (FindKind::Primary, None, 1),
            (FindKind::Properties, Some(&[9u8; 16][..]), 1),
            (FindKind::Properties, Some(&[7u8; 16][..]), 1),
            (FindKind::Structure, Some(&[9u8; 16][..]), 2),
        ] {
            let r = FindRequest {
                kind,
                class: EntryClass::Mixed,
                start: 1,
                end: 65535,
                uuid,
            };
            let raw = d.find(r, 249).unwrap();
            let page = decode_page(r, 249, &raw).unwrap();
            assert_eq!(page.len(), expected);
        }
        let r = FindRequest {
            kind: FindKind::Primary,
            class: EntryClass::Mixed,
            start: 18,
            end: 65535,
            uuid: None,
        };
        assert_eq!(d.find(r, 249).unwrap(), [1, 0, 4, 18, 0, 11]);
    }
    #[test]
    fn uuid_read_matches_ranges_permissions_and_never_truncates() {
        use slk_protocol::ssap::read_uuid::{Request, decode};
        let mut d = Database::default();
        let (_, _, h) = d
            .register(
                vec![1, 0],
                vec![(vec![2, 0], 1, vec![1, 2]), (vec![2, 0], 4, vec![3])],
            )
            .unwrap();
        let r = Request {
            start: 16,
            end: 65535,
            data_type: 0,
            uuid: &[2, 0],
        };
        let raw = d.read_uuid(r, 249).unwrap();
        let v = decode(249, &raw).unwrap();
        assert_eq!(v.len(), 2);
        assert_eq!(v[0].handle, h[0]);
        assert_eq!(v[0].value, Ok(&[1, 2][..]));
        assert_eq!(v[1].value, Err(6));
        assert_eq!(d.read_uuid(r, 9).unwrap(), [9, 11, 16, 0]);
        assert_eq!(
            d.read_uuid(Request { start: 0, ..r }, 249).unwrap(),
            [11, 11, 0, 0, 4, 0]
        );
        assert_eq!(
            d.read_uuid(Request { uuid: &[9, 0], ..r }, 249).unwrap(),
            [11, 11, 16, 0, 11, 0]
        );
        assert_eq!(
            decode(
                249,
                &d.read_uuid(
                    Request {
                        start: h[0],
                        end: h[0],
                        ..r
                    },
                    249
                )
                .unwrap()
            )
            .unwrap()[0]
                .value,
            Ok(&[1, 2][..])
        );
    }
    #[test]
    fn permissions_budget_and_nonreuse_are_production_state() {
        let mut d = Database::default();
        let (start, _, hs) = d
            .register(vec![1, 0], vec![(vec![2, 0], 5, vec![1])])
            .unwrap();
        let h = hs[0];
        assert_eq!(
            d.answer(
                ValuePdu::Read {
                    handle: h,
                    data_type: 0
                },
                249
            )
            .unwrap(),
            [9, 3, 1]
        );
        assert_eq!(
            d.answer(
                ValuePdu::Write {
                    handle: h,
                    data_type: 0,
                    value: &[7, 8],
                    verify: true
                },
                249
            )
            .unwrap(),
            [14, 3, 17, 0, 0, 7, 8]
        );
        assert_eq!(d.local_read(h).unwrap(), [7, 8]);
        assert_eq!(
            d.answer(
                ValuePdu::Read {
                    handle: h,
                    data_type: 2
                },
                249
            )
            .unwrap(),
            [9, 11, 13, 0]
        );
        d.remove(start).unwrap();
        let (_, _, hs) = d
            .register(vec![1, 0], vec![(vec![2, 0], 1, vec![4])])
            .unwrap();
        assert!(hs[0] > h);
        assert_eq!(
            d.answer(
                ValuePdu::Write {
                    handle: hs[0],
                    data_type: 0,
                    value: &[9],
                    verify: false
                },
                249
            )
            .unwrap(),
            [14, 7, 1, 19, 0, 7]
        );
        assert_eq!(d.local_read(hs[0]).unwrap(), [4]);
        let before = (d.next, d.bytes, d.list());
        for ops in [2, 3, 6, 7] {
            assert!(
                d.register(vec![1, 0], vec![(vec![2, 0], ops, vec![])])
                    .is_err()
            );
            assert_eq!((d.next, d.bytes, d.list()), before);
        }

        assert!(
            d.register(vec![1, 0], vec![(vec![2, 0], 8, vec![])])
                .is_err()
        );
        assert_eq!((d.next, d.bytes, d.list()), before);
        for _ in 0..15 {
            d.register(vec![1, 0], vec![(vec![2, 0], 1, vec![])])
                .unwrap();
        }
        assert!(
            d.register(vec![1, 0], vec![(vec![2, 0], 1, vec![])])
                .is_err()
        );
    }
}
