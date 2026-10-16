//! One immutable registration/type/address/lifetime identity per physical link.
//! Properties are canonical observation, never an author operation result.
type SsapEntry = (u8, u16, u16, Vec<u8>, u32, Vec<u8>, u8);
type DynamicRequest = (u16, u16, u16, u16, u16, u8, bool);
type SsapDiscovery = (Vec<SsapEntry>, Vec<(Vec<u8>, Vec<u8>)>);
use crate::state::SharedState;
use slk_protocol::SleLinkInfo;
use zbus::interface;

pub(crate) type Info = (u64, u64, u16, u8, u8, String, bool, bool);
pub(crate) type Objects = (u64, u64, u64, bool, Vec<(String, u64, u16, u8, u8, String)>);

/// Subscribe before checking ownership or polling the receive future. Known
/// bus-owner loss cancels the call-owned queue; it does not erase queued ACKs.
pub(crate) async fn caller_scoped<T>(
    connection: &zbus::Connection,
    sender: &str,
    future: impl std::future::Future<Output = zbus::fdo::Result<T>>,
) -> zbus::fdo::Result<T> {
    use zbus::export::ordered_stream::OrderedStreamExt;
    let bus = zbus::fdo::DBusProxy::new(connection)
        .await
        .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?;
    let mut lost = bus
        .receive_name_owner_changed_with_args(&[(0, sender), (2, "")])
        .await
        .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?;
    if !bus
        .name_has_owner(
            sender
                .try_into()
                .map_err(|e: zbus::names::Error| zbus::fdo::Error::Failed(e.to_string()))?,
        )
        .await?
    {
        return Err(zbus::fdo::Error::Failed(
            "SSAP application caller retired".into(),
        ));
    }
    tokio::select! {
        biased;
        _=lost.next()=>Err(zbus::fdo::Error::Failed("SSAP application caller disappeared or owner stream closed".into())),
        result=future=>result,
    }
}
pub(crate) fn path(base: &str, reference: SleLinkInfo) -> String {
    format!(
        "{}/link_{:016x}",
        peer_path(base, reference.address_type, reference.address),
        reference.lifetime
    )
}
pub(crate) fn peer_path(base: &str, kind: u8, address: [u8; 6]) -> String {
    let address = address
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect::<String>();
    format!("{base}/peer_t{kind:02x}_{address}")
}

#[derive(Clone)]
pub(crate) struct Registration {
    pub reference: SleLinkInfo,
    pub path: String,
    pub published: bool,
}
#[derive(Clone)]
pub(crate) struct PeerRegistration {
    pub address_type: u8,
    pub address: [u8; 6],
    pub path: String,
    pub published: bool,
}
pub(crate) type PeerInfo = (u64, u8, String, bool, bool, Vec<String>);
pub(crate) struct PeerIface {
    state: SharedState,
    generation: u64,
    kind: u8,
    address: [u8; 6],
}
impl PeerIface {
    pub(crate) fn new(state: SharedState, generation: u64, kind: u8, address: [u8; 6]) -> Self {
        Self {
            state,
            generation,
            kind,
            address,
        }
    }
    async fn observation(&self) -> (bool, bool, Vec<String>) {
        let st = self.state.lock().await;
        let known = st.controller.generation == self.generation && st.native_links_known();
        let matching =
            |link: &SleLinkInfo| link.address_type == self.kind && link.address == self.address;
        let connected = known
            && st
                .native_links
                .as_ref()
                .is_some_and(|table| table.links[..table.count as usize].iter().any(matching));
        let objects = st
            .native_connection_objects
            .values()
            .filter(|entry| entry.published && matching(&entry.reference))
            .map(|entry| entry.path.clone())
            .collect();
        (known, connected, objects)
    }
}
#[interface(name = "org.sparklink.Peer")]
impl PeerIface {
    async fn get_info(&self) -> PeerInfo {
        let (known, connected, objects) = self.observation().await;
        (
            self.generation,
            self.kind,
            crate::dbus_iface::format_addr(&self.address),
            known,
            connected,
            objects,
        )
    }
    #[zbus(property)]
    fn generation(&self) -> u64 {
        self.generation
    }
    #[zbus(property)]
    fn address_type(&self) -> u8 {
        self.kind
    }
    #[zbus(property)]
    fn address(&self) -> String {
        crate::dbus_iface::format_addr(&self.address)
    }
    #[zbus(property)]
    async fn connection_known(&self) -> bool {
        self.observation().await.0
    }
    #[zbus(property)]
    async fn connected(&self) -> bool {
        self.observation().await.1
    }
}

pub(crate) struct ConnectionIface {
    state: SharedState,
    generation: u64,
    reference: SleLinkInfo,
    ssap: tokio::sync::Mutex<Option<crate::ssap_engine::Engine>>,
    remote_services: tokio::sync::Mutex<Option<Vec<slk_protocol::ssap::discovery::Entry>>>,
}
enum ChannelKind {
    User,
    Service,
    Dynamic(crate::channel::DynamicConfig),
}
impl ConnectionIface {
    pub(crate) fn new(state: SharedState, generation: u64, reference: SleLinkInfo) -> Self {
        Self {
            state,
            generation,
            reference,
            ssap: tokio::sync::Mutex::new(None),
            remote_services: tokio::sync::Mutex::new(None),
        }
    }
    async fn observation(&self) -> (bool, bool) {
        let st = self.state.lock().await;
        let known = st.controller.generation == self.generation && st.native_links_known();
        let current = known
            && st
                .native_links
                .as_ref()
                .is_some_and(|table| table.links[..table.count as usize].contains(&self.reference));
        (known, current)
    }
}

impl ConnectionIface {
    async fn authorized_fd(
        &self,
        directions: u32,
        security: u32,
        kind: ChannelKind,
    ) -> zbus::fdo::Result<std::os::fd::OwnedFd> {
        crate::channel::validate(directions, security).map_err(|error| {
            if error.raw_os_error() == Some(nix::libc::EOPNOTSUPP) {
                zbus::fdo::Error::NotSupported("protected channel security is not supported".into())
            } else {
                zbus::fdo::Error::InvalidArgs("invalid channel authorization directions".into())
            }
        })?;
        let (index, lease) = {
            let st = self.state.lock().await;
            if !st.present
                || st.controller.generation != self.generation
                || !st.native_links_known()
                || !st.native_links.as_ref().is_some_and(|table| {
                    table.links[..table.count as usize].contains(&self.reference)
                })
            {
                return Err(zbus::fdo::Error::Failed(
                    "connection lifetime is not current".into(),
                ));
            }
            (
                st.controller.dev_index,
                st.native_lease
                    .clone()
                    .ok_or_else(|| zbus::fdo::Error::Failed("management unavailable".into()))?,
            )
        };
        let admission = lease
            .try_lock_owned()
            .map_err(|_| zbus::fdo::Error::Failed("management handoff busy".into()))?;
        if !admission.accepting || admission.token.is_none() {
            return Err(zbus::fdo::Error::Failed("management unavailable".into()));
        }
        let token = admission
            .token
            .ok_or_else(|| zbus::fdo::Error::Failed("management unavailable".into()))?;
        let fd = match kind {
            ChannelKind::Service => crate::channel::open_service(
                index,
                self.generation,
                self.reference.lifetime,
                self.reference.handle,
                token,
            ),
            ChannelKind::User => crate::channel::open(
                index,
                self.generation,
                self.reference.lifetime,
                self.reference.handle,
                token,
                directions,
                security,
            ),
            ChannelKind::Dynamic(config) => crate::channel::open_dynamic(
                index,
                self.generation,
                self.reference.lifetime,
                self.reference.handle,
                token,
                config,
            ),
        }
        .map_err(|error| {
            if error.raw_os_error() == Some(nix::libc::EOPNOTSUPP) {
                zbus::fdo::Error::NotSupported(
                    "channel mode or same-lifetime rebinding is not supported".into(),
                )
            } else {
                zbus::fdo::Error::Failed(format!("native channel bind: {error}"))
            }
        })?;
        Ok(fd)
    }
    async fn open_authorized_channel(
        &self,
        directions: u32,
        security: u32,
    ) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        self.authorized_fd(directions, security, ChannelKind::User)
            .await
            .map(Into::into)
    }
    async fn synchronous_ssap_value(
        &self,
        handle: u16,
        value: Option<Vec<u8>>,
    ) -> zbus::fdo::Result<Vec<u8>> {
        let (known, current) = self.observation().await;
        if !known || !current {
            return Err(zbus::fdo::Error::Failed(
                "connection lifetime is not current".into(),
            ));
        }
        self.start_ssap().await?;
        let actor = self.ssap.lock().await;
        let observer = actor
            .as_ref()
            .ok_or_else(|| zbus::fdo::Error::Failed("SSAP actor unavailable".into()))?
            .observer();
        drop(actor);
        let result = observer
            .value(handle, value)
            .await
            .map_err(zbus::fdo::Error::Failed)?;
        let (known, current) = self.observation().await;
        if !known || !current {
            return Err(zbus::fdo::Error::Failed(
                "connection retired during SSAP operation".into(),
            ));
        }
        Ok(result)
    }
    async fn ssap_context(
        &self,
    ) -> (
        u16,
        std::sync::Arc<std::sync::Mutex<crate::ssap_database::Database>>,
    ) {
        let state = self.state.lock().await;
        (state.controller.dev_index, state.ssap_database.clone())
    }
    pub(crate) async fn start_ssap(&self) -> zbus::fdo::Result<()> {
        let mut actor = self.ssap.lock().await;
        if actor.is_some() {
            return Ok(());
        }
        let fd = self.authorized_fd(3, 0, ChannelKind::Service).await?;
        let (index, database) = self.ssap_context().await;
        *actor = Some(
            crate::ssap_engine::Engine::start(
                fd,
                (
                    index,
                    self.generation,
                    self.reference.lifetime,
                    self.reference.handle,
                ),
                database,
            )
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?,
        );
        Ok(())
    }
    pub(crate) async fn stop_ssap(&self) {
        if let Some(actor) = self.ssap.lock().await.take() {
            actor.stop().await;
        }
    }
}

#[interface(name = "org.sparklink.Connection")]
impl ConnectionIface {
    async fn get_info(&self) -> Info {
        let (known, connected) = self.observation().await;
        (
            self.generation,
            self.reference.lifetime,
            self.reference.handle,
            self.reference.role,
            self.reference.address_type,
            crate::dbus_iface::format_addr(&self.reference.address),
            known,
            connected,
        )
    }
    /// Allocate the caller-bound ID and ORIGINAL deadline before Agent waiting.
    async fn allocate_reference_security(
        &self,
        timeout_ms: u32,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<u64> {
        crate::security_policy::allocate(
            &self.state,
            connection,
            self.generation,
            self.reference,
            &crate::security_policy::sender(&header)?,
            timeout_ms,
        )
        .await
    }
    /// Admission only. Query the original ID; this does not claim encryption.
    async fn begin_reference_security(
        &self,
        request_id: u64,
        method: &str,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<()> {
        crate::security_policy::begin(
            &self.state,
            connection,
            &crate::security_policy::sender(&header)?,
            self.generation,
            self.reference,
            request_id,
            method,
        )
        .await
    }
    async fn get_reference_security_result(
        &self,
        request_id: u64,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<crate::security_policy::Observation> {
        crate::security_policy::observation(
            &self.state,
            &crate::security_policy::sender(&header)?,
            self.generation,
            self.reference,
            request_id,
        )
        .await
    }
    /// True means withdrawal requested. It is not a hardware acknowledgement.
    async fn cancel_reference_security(
        &self,
        request_id: u64,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        crate::security_policy::cancel(
            &self.state,
            &crate::security_policy::sender(&header)?,
            self.generation,
            self.reference,
            request_id,
        )
        .await
    }
    async fn submit_disconnect(&self, request_id: u64) -> zbus::fdo::Result<()> {
        if self.state.lock().await.controller.generation != self.generation {
            return Err(zbus::fdo::Error::Failed(
                "retired connection registration".into(),
            ));
        }
        crate::connection::submit(
            &self.state,
            request_id,
            self.reference.address,
            self.reference.address_type,
            Some(self.reference),
        )
        .await
    }
    async fn discover_ssap(&self, uuid: Vec<u8>, kind: u8) -> zbus::fdo::Result<SsapDiscovery> {
        let kind = match kind {
            0 => slk_protocol::ssap::discovery::FindKind::Structure,
            1 => slk_protocol::ssap::discovery::FindKind::Primary,
            3 => slk_protocol::ssap::discovery::FindKind::Properties,
            _ => {
                return Err(zbus::fdo::Error::NotSupported(
                    "find kind not supported".into(),
                ));
            }
        };
        if !uuid.is_empty() && !matches!(uuid.len(), 2 | 16) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "UUID must be2/16bytes".into(),
            ));
        }
        let (known, current) = self.observation().await;
        if !known || !current {
            return Err(zbus::fdo::Error::Failed(
                "connection lifetime is not current".into(),
            ));
        }
        self.start_ssap().await?;
        let actor = self.ssap.lock().await;
        let observer = actor
            .as_ref()
            .ok_or_else(|| zbus::fdo::Error::Failed("actor unavailable".into()))?
            .observer();
        drop(actor);
        let complete = uuid.is_empty() && kind == slk_protocol::ssap::discovery::FindKind::Primary;
        if complete {
            *self.remote_services.lock().await = None;
        }
        let (entries, trace) = observer
            .discover(if uuid.is_empty() { None } else { Some(uuid) }, kind)
            .await
            .map_err(zbus::fdo::Error::Failed)?;
        let (known, current) = self.observation().await;
        if !known || !current {
            return Err(zbus::fdo::Error::Failed(
                "connection retired during discovery".into(),
            ));
        }
        if complete {
            *self.remote_services.lock().await = Some(entries.clone());
        }
        Ok((
            entries
                .into_iter()
                .map(|e| {
                    (
                        e.category,
                        e.handle,
                        e.end,
                        e.uuid,
                        e.operations,
                        e.descriptors,
                        e.members,
                    )
                })
                .collect(),
            trace,
        ))
    }
    /// Advisory metadata for this exact lifetime, never a security/availability grant.
    async fn get_cached_ssap(&self) -> zbus::fdo::Result<Vec<SsapEntry>> {
        let _ = self.get_ssap_info().await?;
        self.remote_services
            .lock()
            .await
            .as_ref()
            .ok_or_else(|| zbus::fdo::Error::Failed("remote cache unknown".into()))
            .map(|entries| {
                entries
                    .iter()
                    .map(|e| {
                        (
                            e.category,
                            e.handle,
                            e.end,
                            e.uuid.clone(),
                            e.operations,
                            e.descriptors.clone(),
                            e.members,
                        )
                    })
                    .collect()
            })
    }
    /// Call-owned local receive interest. Does not configure peer CCC state.
    async fn observe_ssap_incoming(
        &self,
        handles: Vec<u16>,
        modes: u8,
        wait_ms: u32,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<crate::ssap_engine::Incoming> {
        if handles.is_empty()
            || handles.len() > 32
            || handles.contains(&0)
            || handles
                .iter()
                .enumerate()
                .any(|(i, h)| handles[..i].contains(h))
            || modes == 0
            || modes & !3 != 0
            || !(10..=10000).contains(&wait_ms)
        {
            return Err(zbus::fdo::Error::InvalidArgs(
                "1..32 unique handles, modes1..3 and wait10..10000ms required".into(),
            ));
        }
        let _ = self.get_ssap_info().await?;
        let cache = self.remote_services.lock().await;
        let entries = cache.as_ref().ok_or_else(|| {
            zbus::fdo::Error::NotSupported(
                "actual peer discovery required before local receive interest".into(),
            )
        })?;
        let required = u32::from(modes) << 3;
        if handles.iter().any(|handle| {
            !entries.iter().any(|e| {
                e.handle == *handle && e.category & 7 == 2 && e.operations & required == required
            })
        }) {
            return Err(zbus::fdo::Error::NotSupported(
                "peer has not advertised requested property update capabilities".into(),
            ));
        }
        drop(cache);
        let actor = self.ssap.lock().await;
        let observer = actor
            .as_ref()
            .ok_or_else(|| zbus::fdo::Error::Failed("actor unavailable".into()))?
            .observer();
        drop(actor);
        let sender = header
            .sender()
            .ok_or_else(|| zbus::fdo::Error::Failed("missing SSAP caller identity".into()))?;
        let result = caller_scoped(connection, sender.as_str(), async {
            observer
                .incoming(
                    handles,
                    modes,
                    std::time::Duration::from_millis(u64::from(wait_ms)),
                )
                .await
                .map_err(zbus::fdo::Error::Failed)
        })
        .await?;
        if self.observation().await != (true, true) {
            return Err(zbus::fdo::Error::Failed(
                "retired incoming SSAP lifetime".into(),
            ));
        }
        Ok(result)
    }
    async fn read_ssap_by_uuid(
        &self,
        start: u16,
        end: u16,
        data_type: u8,
        uuid: Vec<u8>,
    ) -> zbus::fdo::Result<crate::ssap_engine::UuidValues> {
        if start == 0 || start > end || !matches!(uuid.len(), 2 | 16) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "valid range and 2/16-byte UUID required".into(),
            ));
        }
        let _ = self.get_ssap_info().await?;
        let actor = self.ssap.lock().await;
        let observer = actor
            .as_ref()
            .ok_or_else(|| zbus::fdo::Error::Failed("actor unavailable".into()))?
            .observer();
        drop(actor);
        let result = observer
            .read_uuid(start, end, data_type, uuid)
            .await
            .map_err(zbus::fdo::Error::Failed)?;
        if self.observation().await != (true, true) {
            return Err(zbus::fdo::Error::Failed(
                "retired read UUID lifetime".into(),
            ));
        }
        Ok(result)
    }
    async fn read_ssap_value(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        self.synchronous_ssap_value(handle, None).await
    }
    async fn write_ssap_value(&self, handle: u16, value: Vec<u8>) -> zbus::fdo::Result<Vec<u8>> {
        self.synchronous_ssap_value(handle, Some(value)).await
    }
    /// Read-only native mechanism state via an existing owner. Do not start an
    /// SSAP Engine, open a channel, mutate credit or mint authorization here.
    async fn get_transport_status(&self) -> zbus::fdo::Result<crate::channel::TransportInfo> {
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(1);
        tokio::time::timeout_at(deadline, async {
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "retired/unknown transport lifetime".into(),
                ));
            }
            let index = self.state.lock().await.controller.dev_index;
            let observer = self
                .ssap
                .lock()
                .await
                .as_ref()
                .map(|actor| actor.observer())
                .ok_or_else(|| {
                    zbus::fdo::Error::NotSupported(
                        "no existing channel owner for observation".into(),
                    )
                })?;
            let value = observer
                .transport_status(deadline)
                .await
                .map_err(zbus::fdo::Error::Failed)?;
            if (
                value.controller,
                value.generation,
                value.lifetime,
                value.handle,
            ) != (
                index,
                self.generation,
                self.reference.lifetime,
                self.reference.handle,
            ) || self.observation().await != (true, true)
            {
                return Err(zbus::fdo::Error::Failed(
                    "transport observation lifetime changed".into(),
                ));
            }
            Ok(crate::channel::transport_info(value))
        })
        .await
        .map_err(|_| zbus::fdo::Error::Failed("transport observation original deadline".into()))?
    }
    async fn get_ssap_info(&self) -> zbus::fdo::Result<crate::ssap_engine::Info> {
        if self.observation().await != (true, true) {
            return Err(zbus::fdo::Error::Failed(
                "retired/unknown SSAP lifetime".into(),
            ));
        }
        self.start_ssap().await?;
        let observer = self
            .ssap
            .lock()
            .await
            .as_ref()
            .ok_or_else(|| zbus::fdo::Error::Failed("SSAP actor absent".into()))?
            .observer();
        let info = observer.info().await.map_err(zbus::fdo::Error::Failed)?;
        if self.observation().await != (true, true) {
            return Err(zbus::fdo::Error::Failed(
                "SSAP lifetime retired during exchange".into(),
            ));
        }
        Ok(info)
    }
    /// Return a staged nonblocking fd, not a fabricated connection result.
    /// Kernel CHANNEL_INFO/poll expose readiness only after actual CMTC and
    /// Runtime epoch revalidation. Port/AID routing is not authentication.
    async fn prepare_dynamic_channel(
        &self,
        request: DynamicRequest,
    ) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        let (source_port, destination_port, aid, mtu, mps, slqi, passive) = request;
        let config = crate::channel::DynamicConfig {
            source_port,
            destination_port,
            aid,
            mtu,
            mps,
            slqi,
            passive,
        };
        config
            .validate()
            .map_err(|error| zbus::fdo::Error::InvalidArgs(error.to_string()))?;
        self.authorized_fd(3, 0, ChannelKind::Dynamic(config))
            .await
            .map(Into::into)
    }
    async fn open_channel(&self) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        self.open_authorized_channel(3, 0).await
    }
    async fn open_channel_scoped(
        &self,
        directions: u32,
        security: u32,
    ) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
        self.open_authorized_channel(directions, security).await
    }
    #[zbus(property)]
    fn generation(&self) -> u64 {
        self.generation
    }
    #[zbus(property)]
    fn lifetime(&self) -> u64 {
        self.reference.lifetime
    }
    #[zbus(property)]
    fn handle(&self) -> u16 {
        self.reference.handle
    }
    #[zbus(property)]
    fn role(&self) -> u8 {
        self.reference.role
    }
    #[zbus(property)]
    fn address_type(&self) -> u8 {
        self.reference.address_type
    }
    #[zbus(property)]
    fn address(&self) -> String {
        crate::dbus_iface::format_addr(&self.reference.address)
    }
    #[zbus(property)]
    async fn connection_known(&self) -> bool {
        self.observation().await.0
    }
    #[zbus(property)]
    async fn connected(&self) -> bool {
        self.observation().await.1
    }
}

#[cfg(test)]
mod grant_tests {
    use super::*;
    use std::sync::Arc;
    use tokio::sync::Mutex;

    #[tokio::test]
    async fn ssap_start_context_releases_one_adapter_guard_before_actor_arguments() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            libsparklink::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "ssap-context-regression",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        state.lock().await.controller.dev_index = 17;
        let iface = ConnectionIface::new(state.clone(), 7, SleLinkInfo::default());
        let (index, store) =
            tokio::time::timeout(std::time::Duration::from_millis(100), iface.ssap_context())
                .await
                .unwrap();
        let guard = state
            .try_lock()
            .expect("production snapshot must not retain adapter guard");
        assert_eq!(index, 17);
        assert!(Arc::ptr_eq(&store, &guard.ssap_database));
    }
    #[tokio::test]
    async fn transport_snapshot_never_starts_owner_and_has_one_original_deadline() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            Arc::new(libsparklink::Adapter::open("/dev/null").unwrap()),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "transport-status-test",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        let reference = SleLinkInfo {
            lifetime: 11,
            handle: 3,
            ..Default::default()
        };
        let iface = ConnectionIface::new(state.clone(), 7, reference);
        assert!(matches!(
            iface.get_transport_status().await,
            Err(zbus::fdo::Error::Failed(_))
        ));
        {
            let mut st = state.lock().await;
            st.present = true;
            st.controller.generation = 7;
            let mut table = slk_protocol::SleLinkSnapshot {
                flags: slk_protocol::LINK_SNAPSHOT_KNOWN,
                count: 1,
                ..Default::default()
            };
            table.links[0] = reference;
            st.native_links = Some(table);
        }
        assert!(matches!(
            iface.get_transport_status().await,
            Err(zbus::fdo::Error::NotSupported(_))
        ));
        assert!(iface.ssap.lock().await.is_none());
        let _held = state.lock().await;
        let result = tokio::time::timeout(
            std::time::Duration::from_millis(1200),
            iface.get_transport_status(),
        )
        .await
        .unwrap();
        assert!(
            matches!(result,Err(zbus::fdo::Error::Failed(ref error)) if error.contains("original deadline"))
        );
        assert!(iface.ssap.lock().await.is_none());
    }
    #[tokio::test]
    async fn actual_scoped_handler_rejects_before_held_business_state() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            Arc::new(libsparklink::Adapter::open("/dev/null").unwrap()),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "grant-policy-rejection",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        let interface = ConnectionIface::new(state.clone(), 7, SleLinkInfo::default());
        let _held = state.lock().await;
        for directions in [0, 4, u32::MAX] {
            let result = tokio::time::timeout(
                std::time::Duration::from_millis(100),
                interface.open_channel_scoped(directions, 0),
            )
            .await
            .unwrap();
            assert!(matches!(result, Err(zbus::fdo::Error::InvalidArgs(_))));
        }
        for request in [
            (0, 20, 30, 249, 254, 1, true),
            (10, 20, 30, 249, 253, 1, false),
            (10, 20, 0, 249, 254, 1, true),
        ] {
            let result = tokio::time::timeout(
                std::time::Duration::from_millis(100),
                interface.prepare_dynamic_channel(request),
            )
            .await
            .unwrap();
            assert!(matches!(result, Err(zbus::fdo::Error::InvalidArgs(_))));
        }
        for security in [1, 2, u32::MAX] {
            let result = tokio::time::timeout(
                std::time::Duration::from_millis(100),
                interface.open_channel_scoped(3, security),
            )
            .await
            .unwrap();
            assert!(matches!(result, Err(zbus::fdo::Error::NotSupported(_))));
        }
    }
}
