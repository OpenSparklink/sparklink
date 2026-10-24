//! Bounded adapter-local service data. Handles are never reused within this
//! registration. Local insertion is not remote discovery/publication success.
//! Reply codecs receive a bounded logical-PDU budget; the sole Engine enforces
//! each physical datagram MTU and negotiated fragment support before sending.
use crate::ssap_authorization::{Approval, Owner, Target};
use slk_protocol::ssap::access::SsapAccess;
use slk_protocol::ssap::discovery::{Entry, FindKind, FindRequest, encode_page};
use slk_protocol::{SsapOperations, ssap::value::ValuePdu};
use std::collections::BTreeMap;
use std::sync::Arc;
mod budget;

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum LocalValueError {
    Owner,
    Length,
    Budget,
}

pub(crate) use slk_contract::ssap::local::{PropertyDefinition, ServiceRecord as LocalService};
struct Property {
    uuid: Vec<u8>,
    operations: SsapOperations,
    access: SsapAccess,
    value: Vec<u8>,
}
struct Service {
    end: u16,
    uuid: Vec<u8>,
    properties: BTreeMap<u16, Property>,
    owner: Option<Arc<Owner>>,
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
    /// Retirement invalidates under the value-admission mutex; join watches
    /// afterwards, outside both adapter and database locks.
    pub(crate) fn retire(&mut self) -> Vec<Arc<Owner>> {
        let owners = self
            .services
            .values()
            .filter_map(|s| s.owner.clone())
            .collect::<Vec<_>>();
        for owner in &owners {
            owner.revoke();
        }
        self.services.clear();
        self.bytes = 0;
        owners
    }
    pub(crate) fn register(
        &mut self,
        uuid: Vec<u8>,
        definitions: Vec<PropertyDefinition>,
    ) -> Result<(u16, u16, Vec<u16>), String> {
        self.register_inner(uuid, definitions, None)
    }
    pub(crate) fn register_owned(
        &mut self,
        uuid: Vec<u8>,
        definitions: Vec<PropertyDefinition>,
        owner: Arc<Owner>,
    ) -> Result<(u16, u16, Vec<u16>), String> {
        if !owner.current() {
            return Err("service owner retired".into());
        }
        self.register_inner(uuid, definitions, Some(owner))
    }
    fn register_inner(
        &mut self,
        uuid: Vec<u8>,
        definitions: Vec<PropertyDefinition>,
        owner: Option<Arc<Owner>>,
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
        for (uuid, ops, access, value) in &definitions {
            let access = SsapAccess::from_bits(*access)?;
            if access.needs_local_authorization()
                && owner.as_ref().is_none_or(|o| !o.supports_authorization())
            {
                return Err("SSAP local authorization not connected".into());
            }
            let ops = SsapOperations::from_bits(*ops).map_err(|e| e.to_string())?;
            if !uuid_valid(uuid)
                || !slk_protocol::ssap::client_config::supported_owned(
                    ops,
                    owner.as_ref().is_some_and(|o| o.supports_authorization()),
                )
            {
                return Err(
                    "unsupported operations or update capability without owned CPCD authorizer"
                        .into(),
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
            .map(|(i, (uuid, ops, access, value))| {
                (
                    (self.next + 1 + i as u32) as u16,
                    Property {
                        uuid,
                        operations: SsapOperations::from_bits(ops).expect("validated"),
                        access: SsapAccess::from_bits(access).expect("validated"),
                        value,
                    },
                )
            })
            .collect::<BTreeMap<_, _>>();
        let handles = properties.keys().copied().collect();
        // Final owned-registration admission, after validation/allocation and
        // under the same DB lock as removal/value admission. No await follows.
        if owner.as_ref().is_some_and(|o| !o.can_register()) {
            return Err("service owner retired or registration deadline expired".into());
        }
        self.services.insert(
            start,
            Service {
                end,
                uuid,
                properties,
                owner,
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
                        .map(|(h, p)| (*h, p.uuid.clone(), p.operations.bits(), p.access.bits()))
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
        if let Some(owner) = s.owner {
            owner.revoke();
        }
        Ok(())
    }
    pub(crate) fn revoke_owner(&mut self, owner: &str) {
        let starts: Vec<_> = self
            .services
            .iter()
            .filter(|(_, s)| s.owner.as_ref().is_some_and(|o| o.name == owner))
            .map(|(h, _)| *h)
            .collect();
        for start in starts {
            let _ = self.remove(start);
        }
    }
    pub(crate) fn remove_owned(&mut self, start: u16, owner: &str) -> Result<(), String> {
        if !self.services.get(&start).is_some_and(|s| {
            s.owner
                .as_ref()
                .is_some_and(|o| o.current() && o.name == owner)
        }) {
            return Err("service is not owned by caller".into());
        }
        self.remove(start)
    }
    pub(crate) fn local_read_owned(&self, handle: u16, owner: &str) -> Result<Vec<u8>, String> {
        if !self.services.values().any(|s| {
            s.properties.contains_key(&handle)
                && s.owner
                    .as_ref()
                    .is_some_and(|o| o.current() && o.name == owner)
        }) {
            return Err("property is not owned by caller".into());
        }
        self.local_read(handle)
    }
    /// The caller owns this data, independently of the peer WRITE permission.
    /// Admission and commit share the DB mutex used by retirement and wire writes.
    pub(crate) fn replace_owned_value(
        &mut self,
        handle: u16,
        owner: &str,
        value: Vec<u8>,
    ) -> Result<(), LocalValueError> {
        let service = self
            .services
            .values_mut()
            .find(|s| {
                s.properties.contains_key(&handle)
                    && s.owner
                        .as_ref()
                        .is_some_and(|o| o.current() && o.name == owner)
            })
            .ok_or(LocalValueError::Owner)?;
        if value.len() > 2042 {
            return Err(LocalValueError::Length);
        }
        let property = service.properties.get_mut(&handle).expect("owned property");
        let next = budget::replacement_bytes(self.bytes, property.value.len(), value.len())
            .ok_or(LocalValueError::Budget)?;
        property.value = value;
        self.bytes = next;
        Ok(())
    }
    fn target(&self, handle: u16, level: u32, write: bool) -> Option<Target> {
        let operation = if write {
            SsapOperations::WRITE_WITH_RSP
        } else {
            SsapOperations::READ
        };
        self.target_operation(handle, level, write, operation)
    }
    fn target_operation(
        &self,
        handle: u16,
        level: u32,
        write: bool,
        operation: SsapOperations,
    ) -> Option<Target> {
        let service = self
            .services
            .values()
            .find(|s| s.properties.contains_key(&handle))?;
        let p = service.properties.get(&handle)?;
        if !p.operations.contains(operation)
            || p.access.check(level, write) != Err(9)
            || p.access
                .check_authorization_result(level, write, true)
                .is_err()
        {
            return None;
        }
        let owner = service.owner.as_ref()?;
        if !owner.current() || !owner.supports_authorization() {
            return None;
        }
        Some(Target {
            handle,
            data_type: 0,
            owner: owner.clone(),
        })
    }
    pub(crate) fn value_targets(&self, request: ValuePdu<'_>, level: u32) -> Vec<Target> {
        if let ValuePdu::WriteCommand {
            handle,
            data_type: 0,
            ..
        } = request
        {
            return self
                .target_operation(handle, level, true, SsapOperations::WRITE_NO_RSP)
                .into_iter()
                .collect();
        }
        if let ValuePdu::Write {
            handle,
            data_type: 2,
            value,
            ..
        } = request
        {
            return self
                .configuration_property(handle)
                .ok()
                .and_then(|(modes, owner)| {
                    slk_protocol::ssap::client_config::decode(value, modes).ok()?;
                    slk_protocol::ssap::client_config::WRITE_ACCESS
                        .check_authorization_result(level, true, true)
                        .ok()
                        .map(|_| Target {
                            handle,
                            data_type: 2,
                            owner,
                        })
                })
                .into_iter()
                .collect();
        }
        let (handle, write) = match request {
            ValuePdu::Read {
                handle,
                data_type: 0,
            } => (handle, false),
            ValuePdu::Write {
                handle,
                data_type: 0,
                ..
            } => (handle, true),
            _ => return vec![],
        };
        self.target(handle, level, write).into_iter().collect()
    }
    pub(crate) fn uuid_targets(
        &self,
        request: slk_protocol::ssap::read_uuid::Request<'_>,
        level: u32,
    ) -> Vec<Target> {
        if request.start == 0 || request.start > request.end || request.data_type != 0 {
            return vec![];
        }
        self.services
            .values()
            .flat_map(|s| s.properties.range(request.start..=request.end))
            .filter(|(_, p)| p.uuid == request.uuid)
            .filter_map(|(h, _)| self.target(*h, level, false))
            .collect()
    }
    fn locally_authorized(
        &self,
        handle: u16,
        data_type: u8,
        write: bool,
        approvals: &[Approval],
    ) -> bool {
        self.services
            .values()
            .find(|s| s.properties.contains_key(&handle))
            .and_then(|s| s.owner.as_ref())
            .is_some_and(|o| {
                o.current()
                    && approvals.iter().any(|a| {
                        a.handle == handle
                            && a.data_type == data_type
                            && a.write == write
                            && Arc::ptr_eq(o, &a.owner)
                    })
            })
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
                            descriptors: if slk_protocol::ssap::client_config::modes(
                                property.operations,
                            ) != 0
                            {
                                vec![2]
                            } else {
                                vec![]
                            },
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
        level: u32,
    ) -> Result<Vec<u8>, String> {
        self.read_uuid_authorized(request, mtu, level, &[])
    }
    pub(crate) fn read_uuid_authorized(
        &self,
        request: slk_protocol::ssap::read_uuid::Request<'_>,
        mtu: u16,
        level: u32,
        approvals: &[Approval],
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
                        } else if let Err(error) = p.access.check_authorization_result(
                            level,
                            false,
                            self.locally_authorized(*handle, 0, false, approvals),
                        ) {
                            Err(u16::from(error))
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
    pub(crate) fn configuration_property(&self, handle: u16) -> Result<(u8, Arc<Owner>), u8> {
        let service = self
            .services
            .values()
            .find(|s| s.properties.contains_key(&handle))
            .ok_or(4u8)?;
        let property = service.properties.get(&handle).ok_or(4u8)?;
        let modes = slk_protocol::ssap::client_config::modes(property.operations);
        if modes == 0 || !property.operations.contains(SsapOperations::CLIENT_CFG_WR) {
            return Err(13);
        }
        let owner = service
            .owner
            .as_ref()
            .filter(|o| o.current() && o.supports_authorization())
            .ok_or(13u8)?;
        Ok((modes, owner.clone()))
    }
    pub(crate) fn owned_update(
        &self,
        handle: u16,
        caller: &str,
    ) -> Result<(Arc<Owner>, Vec<u8>), String> {
        let (_, owner) = self
            .configuration_property(handle)
            .map_err(|_| "owned update capability unavailable")?;
        if owner.name != caller {
            return Err("property is not owned by caller".into());
        }
        let value = self
            .property(handle)
            .ok_or("property retired")?
            .value
            .clone();
        Ok((owner, value))
    }
    /// Called under the DB admission mutex, with configuration owned by this
    /// one physical actor. Never store per-client state in the adapter DB.
    pub(crate) fn answer_configuration(
        &self,
        request: ValuePdu<'_>,
        mtu: u16,
        level: u32,
        epoch: Option<u64>,
        approvals: &[Approval],
        configurations: &mut crate::ssap_engine_config::ClientConfigurations,
    ) -> Result<Vec<u8>, String> {
        use slk_protocol::ssap::client_config::{self, WRITE_ACCESS};
        let (handle, write) = match request {
            ValuePdu::Read {
                handle,
                data_type: 2,
            } => (handle, false),
            ValuePdu::Write {
                handle,
                data_type: 2,
                ..
            } => (handle, true),
            _ => return Err("not a client configuration request".into()),
        };
        let property = self.configuration_property(handle);
        let epoch = epoch.filter(|epoch| *epoch != 0).ok_or(9u8);
        let mut commit = None;
        let mut bytes = [0; 2];
        let response = match (property, epoch) {
            (Err(error), _) | (_, Err(error)) if write => ValuePdu::WriteError { handle, error },
            (Err(error), _) | (_, Err(error)) => ValuePdu::ReadError(u16::from(error)),
            (Ok((supported, owner)), Ok(epoch)) => match request {
                ValuePdu::Read { .. } => {
                    bytes[0] = configurations.get(handle, &owner, epoch);
                    ValuePdu::ReadValue(&bytes)
                }
                ValuePdu::Write { value, verify, .. } => {
                    let admitted = client_config::decode(value, supported)
                        .map_err(|_| 5)
                        .and_then(|modes| {
                            WRITE_ACCESS
                                .check_authorization_result(
                                    level,
                                    true,
                                    self.locally_authorized(
                                        handle,
                                        client_config::DATA_TYPE,
                                        true,
                                        approvals,
                                    ),
                                )
                                .map(|_| modes)
                        });
                    match admitted {
                        Err(error) => ValuePdu::WriteError { handle, error },
                        Ok(modes) => {
                            commit = Some((owner, epoch, modes));
                            if verify {
                                ValuePdu::WrittenValue {
                                    handle,
                                    data_type: 2,
                                    value,
                                }
                            } else {
                                ValuePdu::Written
                            }
                        }
                    }
                }
                _ => unreachable!("validated configuration operation"),
            },
        };
        let mut output = vec![0; usize::from(mtu)];
        let mut size = response
            .encode(mtu, &mut output)
            .map_err(|e| format!("configuration response: {e:?}"))?;
        // Allocate/validate the response before changing state. A local commit
        // still does not imply the peer received that response.
        if let Some((owner, epoch, modes)) = commit
            && let Err(error) = configurations.set(handle, &owner, epoch, modes)
        {
            size = ValuePdu::WriteError { handle, error }
                .encode(mtu, &mut output)
                .map_err(|e| format!("configuration refusal: {e:?}"))?;
        }
        output.truncate(size);
        Ok(output)
    }
    pub(crate) fn local_read(&self, handle: u16) -> Result<Vec<u8>, String> {
        self.property(handle)
            .map(|p| p.value.clone())
            .ok_or_else(|| "unknown local property".into())
    }
    /// Apply one complete command without constructing a normal or error PDU.
    /// Error codes are local refusal reasons only; commands never owe a reply.
    pub(crate) fn command_authorized(
        &mut self,
        request: ValuePdu<'_>,
        mtu: u16,
        level: u32,
        approvals: &[Approval],
    ) -> Result<(), u8> {
        if !matches!(request, ValuePdu::WriteCommand { .. }) {
            return Err(2);
        }
        self.write_value(request, mtu, level, approvals)
    }
    /// Called under the database mutex after the Engine's original context
    /// recheck. Permission remains specific to the request or command opcode.
    fn write_value(
        &mut self,
        request: ValuePdu<'_>,
        mtu: u16,
        level: u32,
        approvals: &[Approval],
    ) -> Result<(), u8> {
        let (handle, data_type, value, operation) = match request {
            ValuePdu::Write {
                handle,
                data_type,
                value,
                ..
            } => (handle, data_type, value, SsapOperations::WRITE_WITH_RSP),
            ValuePdu::WriteCommand {
                handle,
                data_type,
                value,
            } => (handle, data_type, value, SsapOperations::WRITE_NO_RSP),
            _ => return Err(2),
        };
        let service = self
            .services
            .values()
            .find(|s| s.properties.contains_key(&handle))
            .ok_or(4u8)?;
        if service.owner.as_ref().is_some_and(|owner| !owner.current()) {
            return Err(4);
        }
        let property = service.properties.get(&handle).ok_or(4u8)?;
        if data_type != 0 {
            return Err(13);
        }
        if !property.operations.contains(operation) {
            return Err(7);
        }
        property.access.check_authorization_result(
            level,
            true,
            self.locally_authorized(handle, data_type, true, approvals),
        )?;
        let next =
            budget::replacement_bytes(self.bytes, property.value.len(), value.len()).ok_or(5u8)?;
        if value
            .len()
            .checked_add(5)
            .is_none_or(|size| size > usize::from(mtu))
        {
            return Err(16);
        }
        let property = self
            .services
            .values_mut()
            .find_map(|s| s.properties.get_mut(&handle))
            .expect("checked property under DB mutex");
        property.value = value.to_vec();
        self.bytes = next;
        Ok(())
    }
    /// Returns a real protocol response. Mutates only on validated single-value
    /// writes with sufficient permission, value budget and negotiated PDU size.
    pub(crate) fn answer(
        &mut self,
        request: ValuePdu<'_>,
        mtu: u16,
        level: u32,
    ) -> Result<Vec<u8>, String> {
        self.answer_authorized(request, mtu, level, &[])
    }
    pub(crate) fn answer_authorized(
        &mut self,
        request: ValuePdu<'_>,
        mtu: u16,
        level: u32,
        approvals: &[Approval],
    ) -> Result<Vec<u8>, String> {
        let mut out = vec![0; usize::from(mtu)];
        let response = match request {
            ValuePdu::Read { handle, data_type } => match self.property(handle) {
                None => ValuePdu::ReadError(4),
                Some(_) if data_type != 0 => ValuePdu::ReadError(13),
                Some(p) if !p.operations.contains(SsapOperations::READ) => ValuePdu::ReadError(6),
                Some(p)
                    if p.access
                        .check_authorization_result(
                            level,
                            false,
                            self.locally_authorized(handle, data_type, false, approvals),
                        )
                        .is_err() =>
                {
                    ValuePdu::ReadError(u16::from(
                        p.access
                            .check_authorization_result(
                                level,
                                false,
                                self.locally_authorized(handle, data_type, false, approvals),
                            )
                            .unwrap_err(),
                    ))
                }
                // T/XS 20001-2025 §7.4.4.5 requires READ_RSP for this
                // unsupported-fragmentation result, as with read-by-UUID.
                Some(p) if p.value.len() + 2 > usize::from(mtu) => ValuePdu::ReadError(16),
                Some(p) => ValuePdu::ReadValue(&p.value),
            },
            ValuePdu::Write {
                handle,
                data_type,
                value,
                verify,
            } => match self.write_value(request, mtu, level, approvals) {
                Err(16) => return Err("write exceeds negotiated PDU".into()),
                Err(error) => ValuePdu::WriteError { handle, error },
                Ok(()) if verify => ValuePdu::WrittenValue {
                    handle,
                    data_type,
                    value,
                },
                Ok(()) => ValuePdu::Written,
            },
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
    fn command_and_request_permissions_do_not_authorize_each_other() {
        for operations in [1, 3, 5, 7] {
            let mut database = Database::default();
            let (_, _, handles) = database
                .register(vec![1, 0], vec![(vec![2, 0], operations, 0, vec![1])])
                .unwrap();
            let handle = handles[0];
            let command = ValuePdu::WriteCommand {
                handle,
                data_type: 0,
                value: &[9, 8],
            };
            // The response-producing API must never render a command response.
            assert!(database.answer(command, 249, 0).is_err());
            assert_eq!(database.local_read(handle).unwrap(), [1]);
            assert_eq!(
                database.command_authorized(command, 249, 0, &[]),
                if operations & 2 != 0 { Ok(()) } else { Err(7) }
            );
            let after_command = if operations & 2 != 0 {
                vec![9, 8]
            } else {
                vec![1]
            };
            assert_eq!(database.local_read(handle).unwrap(), after_command);
            let request = ValuePdu::Write {
                handle,
                data_type: 0,
                value: &[6],
                verify: true,
            };
            assert_eq!(database.command_authorized(request, 249, 0, &[]), Err(2));
            assert_eq!(database.local_read(handle).unwrap(), after_command);
            let response = database.answer(request, 249, 0).unwrap();
            if operations & 4 != 0 {
                assert_eq!(
                    ValuePdu::decode(249, &response).unwrap(),
                    ValuePdu::WrittenValue {
                        handle,
                        data_type: 0,
                        value: &[6]
                    }
                );
                assert_eq!(database.local_read(handle).unwrap(), [6]);
            } else {
                assert_eq!(
                    ValuePdu::decode(249, &response).unwrap(),
                    ValuePdu::WriteError { handle, error: 7 }
                );
                assert_eq!(database.local_read(handle).unwrap(), after_command);
            }
        }
    }

    #[test]
    fn command_replaces_only_after_complete_length_type_and_budget_admission() {
        let mut database = Database::default();
        let (_, _, handles) = database
            .register(vec![1, 0], vec![(vec![2, 0], 3, 0, vec![1, 2])])
            .unwrap();
        let handle = handles[0];
        for (data_type, value, mtu, expected) in [
            (2, vec![4], 249, 13),
            (0, vec![4; 245], 249, 16),
            (0, vec![4; 2043], 4096, 5),
            (0, vec![], 4, 16),
        ] {
            let before = (database.bytes, database.local_read(handle).unwrap());
            assert_eq!(
                database.command_authorized(
                    ValuePdu::WriteCommand {
                        handle,
                        data_type,
                        value: &value
                    },
                    mtu,
                    0,
                    &[]
                ),
                Err(expected)
            );
            assert_eq!(
                (database.bytes, database.local_read(handle).unwrap()),
                before
            );
        }
        let maximum = vec![0x5a; 2042];
        assert_eq!(
            database.command_authorized(
                ValuePdu::WriteCommand {
                    handle,
                    data_type: 0,
                    value: &maximum
                },
                2047,
                0,
                &[]
            ),
            Ok(())
        );
        assert_eq!(database.local_read(handle).unwrap(), maximum);
        assert_eq!(database.bytes, 2042);
        assert_eq!(
            database.command_authorized(
                ValuePdu::WriteCommand {
                    handle,
                    data_type: 0,
                    value: &[]
                },
                5,
                0,
                &[]
            ),
            Ok(())
        );
        assert_eq!(database.local_read(handle).unwrap(), []);
        assert_eq!(database.bytes, 0);
        assert_eq!(
            database.command_authorized(
                ValuePdu::WriteCommand {
                    handle: 0,
                    data_type: 0,
                    value: &[1]
                },
                249,
                0,
                &[]
            ),
            Err(4)
        );

        let mut full = Database::default();
        let mut definitions = vec![(vec![2, 0], 3, 0, vec![1; 2042]); 4];
        definitions.push((vec![2, 0], 3, 0, vec![1; 24]));
        let (_, _, handles) = full.register(vec![1, 0], definitions).unwrap();
        let handle = handles[4];
        assert_eq!(full.bytes, 8192);
        assert_eq!(
            full.command_authorized(
                ValuePdu::WriteCommand {
                    handle,
                    data_type: 0,
                    value: &[2; 25]
                },
                249,
                0,
                &[]
            ),
            Err(5)
        );
        assert_eq!(full.local_read(handle).unwrap(), [1; 24]);
        assert_eq!(full.bytes, 8192);
    }

    #[tokio::test]
    async fn command_requires_the_registered_owner_approval_and_actual_security_level() {
        // Real private-bus owner watches; supplied approvals exercise the DB
        // predicate only, not an application callback or Native security proof.
        let bus = crate::event_loop::tests::PrivateBus::start();
        let server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let caller = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let foreign = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let store = Arc::new(std::sync::Mutex::new(Database::default()));
        let slots = Arc::new(tokio::sync::Semaphore::new(2));
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
        let mut owners = Vec::new();
        for connection in [&caller, &foreign] {
            owners.push(
                Owner::pin(
                    &server,
                    connection.unique_name().unwrap().to_string(),
                    zbus::zvariant::OwnedObjectPath::try_from("/authorizer").unwrap(),
                    &store,
                    slots.clone().try_acquire_owned().unwrap(),
                    deadline,
                )
                .await
                .unwrap(),
            );
        }
        {
            let mut database = store.lock().unwrap();
            let (_, _, handles) = database
                .register_owned(
                    vec![1, 0],
                    vec![(vec![2, 0], 3, 6, vec![1])],
                    owners[0].clone(),
                )
                .unwrap();
            let handle = handles[0];
            let command = ValuePdu::WriteCommand {
                handle,
                data_type: 0,
                value: &[7, 8],
            };
            let targets = database.value_targets(command, 2);
            assert_eq!(targets.len(), 1);
            assert!(Arc::ptr_eq(&targets[0].owner, &owners[0]));
            assert_eq!(database.command_authorized(command, 249, 2, &[]), Err(9));
            let foreign_approval = Approval {
                handle,
                data_type: 0,
                write: true,
                owner: owners[1].clone(),
            };
            assert_eq!(
                database.command_authorized(command, 249, 2, &[foreign_approval]),
                Err(9)
            );
            let approval = Approval {
                handle,
                data_type: 0,
                write: true,
                owner: owners[0].clone(),
            };
            assert_eq!(
                database.command_authorized(command, 249, 1, std::slice::from_ref(&approval)),
                Err(8)
            );
            assert_eq!(database.local_read(handle).unwrap(), [1]);
            assert_eq!(
                database.command_authorized(command, 249, 2, std::slice::from_ref(&approval)),
                Ok(())
            );
            assert_eq!(database.local_read(handle).unwrap(), [7, 8]);
            owners[0].revoke();
            assert_eq!(
                database.command_authorized(
                    ValuePdu::WriteCommand {
                        handle,
                        data_type: 0,
                        value: &[9]
                    },
                    249,
                    2,
                    &[approval]
                ),
                Err(4)
            );
            assert_eq!(database.local_read(handle).unwrap(), [7, 8]);
        }
        for owner in owners {
            owner.shutdown().await;
        }
    }
    #[test]
    fn attribute_security_checks_original_level_before_values_or_mutation() {
        use slk_protocol::ssap::read_uuid::{Request, decode};
        for level in 0..=2 {
            let mut d = Database::default();
            let (_, _, handles) = d
                .register(
                    vec![1, 0],
                    vec![
                        (vec![2, 0], 5, 0, vec![7]),
                        (vec![2, 0], 5, 9, vec![7]),
                        (vec![2, 0], 5, 18, vec![7]),
                    ],
                )
                .unwrap();
            for (index, handle) in handles.iter().copied().enumerate() {
                let error = if index == 2 && level < 2 {
                    Some(8)
                } else if index == 1 && level == 0 {
                    Some(10)
                } else {
                    None
                };
                let raw = d
                    .answer(
                        ValuePdu::Read {
                            handle,
                            data_type: 0,
                        },
                        249,
                        level,
                    )
                    .unwrap();
                match error {
                    Some(e) => {
                        assert_eq!(ValuePdu::decode(249, &raw).unwrap(), ValuePdu::ReadError(e))
                    }
                    None => assert_eq!(
                        ValuePdu::decode(249, &raw).unwrap(),
                        ValuePdu::ReadValue(&[7])
                    ),
                }
                let raw = d
                    .answer(
                        ValuePdu::Write {
                            handle,
                            data_type: 0,
                            value: &[9],
                            verify: true,
                        },
                        249,
                        level,
                    )
                    .unwrap();
                if let Some(e) = error {
                    assert_eq!(
                        ValuePdu::decode(249, &raw).unwrap(),
                        ValuePdu::WriteError {
                            handle,
                            error: e as u8
                        }
                    );
                    assert_eq!(d.local_read(handle).unwrap(), [7]);
                } else {
                    assert_eq!(
                        ValuePdu::decode(249, &raw).unwrap(),
                        ValuePdu::WrittenValue {
                            handle,
                            data_type: 0,
                            value: &[9]
                        }
                    );
                    assert_eq!(d.local_read(handle).unwrap(), [9]);
                }
            }
            let raw = d
                .read_uuid(
                    Request {
                        start: 16,
                        end: 65535,
                        data_type: 0,
                        uuid: &[2, 0],
                    },
                    249,
                    level,
                )
                .unwrap();
            let items = decode(249, &raw).unwrap();
            assert_eq!(items.len(), 3);
            assert_eq!(items[0].value, Ok(&[9][..]));
            assert_eq!(
                items[1].value,
                if level == 0 { Err(10) } else { Ok(&[9][..]) }
            );
            assert_eq!(
                items[2].value,
                if level < 2 { Err(8) } else { Ok(&[9][..]) }
            );
        }
        let mut d = Database::default();
        for access in [4, 32, 36, 64, 1 << 31] {
            assert!(
                d.register(vec![1, 0], vec![(vec![2, 0], 5, access, vec![1])])
                    .is_err()
            );
            assert!(d.list().is_empty());
            assert_eq!((d.bytes, d.next), (0, 16));
        }
    }
    #[test]
    fn discovery_uses_real_local_metadata_and_reserved_handle_floor() {
        use slk_protocol::ssap::discovery::{EntryClass, decode_page};
        let mut d = Database::default();
        let (start, end, handles) = d
            .register(vec![9; 16], vec![(vec![7; 16], 5, 0, vec![1])])
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
                vec![(vec![2, 0], 1, 0, vec![1, 2]), (vec![2, 0], 4, 0, vec![3])],
            )
            .unwrap();
        let r = Request {
            start: 16,
            end: 65535,
            data_type: 0,
            uuid: &[2, 0],
        };
        let raw = d.read_uuid(r, 249, 0).unwrap();
        let v = decode(249, &raw).unwrap();
        assert_eq!(v.len(), 2);
        assert_eq!(v[0].handle, h[0]);
        assert_eq!(v[0].value, Ok(&[1, 2][..]));
        assert_eq!(v[1].value, Err(6));
        assert_eq!(d.read_uuid(r, 9, 0).unwrap(), [9, 11, 16, 0]);
        assert_eq!(
            d.read_uuid(Request { start: 0, ..r }, 249, 0).unwrap(),
            [11, 11, 0, 0, 4, 0]
        );
        assert_eq!(
            d.read_uuid(Request { uuid: &[9, 0], ..r }, 249, 0).unwrap(),
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
                    249,
                    0
                )
                .unwrap()
            )
            .unwrap()[0]
                .value,
            Ok(&[1, 2][..])
        );
    }

    #[test]
    fn complete_read_boundary_rejects_without_mutation_then_accepts_next_operation() {
        for size in [62, 63, 64] {
            let mut d = Database::default();
            let value = vec![0x5a; size];
            let (_, _, handles) = d
                .register(vec![1, 0], vec![(vec![2, 0], 5, 0, value.clone())])
                .unwrap();
            let handle = handles[0];
            let read = ValuePdu::Read {
                handle,
                data_type: 0,
            };
            let raw = d.answer(read, 64, 0).unwrap();
            if size == 62 {
                assert_eq!(raw, [vec![9, 3], value.clone()].concat());
            } else {
                assert_eq!(raw, [9, 11, 16, 0]);
            }
            assert_eq!(d.local_read(handle).unwrap(), value);
            let next = ValuePdu::Write {
                handle,
                data_type: 0,
                value: &[1, 2],
                verify: true,
            };
            assert_eq!(
                d.answer(next, 64, 0).unwrap(),
                [14, 3, handle as u8, (handle >> 8) as u8, 0, 1, 2]
            );
            assert_eq!(d.answer(read, 64, 0).unwrap(), [9, 3, 1, 2]);
        }
    }
    #[test]
    fn permissions_budget_and_nonreuse_are_production_state() {
        let mut d = Database::default();
        let (start, _, hs) = d
            .register(vec![1, 0], vec![(vec![2, 0], 5, 0, vec![1])])
            .unwrap();
        let h = hs[0];
        assert_eq!(
            d.answer(
                ValuePdu::Read {
                    handle: h,
                    data_type: 0
                },
                249,
                0
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
                249,
                0
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
                249,
                0
            )
            .unwrap(),
            [9, 11, 13, 0]
        );
        d.remove(start).unwrap();
        let (_, _, hs) = d
            .register(vec![1, 0], vec![(vec![2, 0], 1, 0, vec![4])])
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
                249,
                0
            )
            .unwrap(),
            [14, 7, 1, 19, 0, 7]
        );
        assert_eq!(d.local_read(hs[0]).unwrap(), [4]);
        let before = (d.next, d.bytes, d.list());
        for ops in [32, 256, 1024, 7 | 32] {
            assert!(
                d.register(vec![1, 0], vec![(vec![2, 0], ops, 0, vec![])])
                    .is_err()
            );
            assert_eq!((d.next, d.bytes, d.list()), before);
        }

        assert!(
            d.register(vec![1, 0], vec![(vec![2, 0], 8, 0, vec![])])
                .is_err()
        );
        assert_eq!((d.next, d.bytes, d.list()), before);
        for _ in 0..15 {
            d.register(vec![1, 0], vec![(vec![2, 0], 1, 0, vec![])])
                .unwrap();
        }
        assert!(
            d.register(vec![1, 0], vec![(vec![2, 0], 1, 0, vec![])])
                .is_err()
        );
    }
}
