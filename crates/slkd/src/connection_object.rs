//! One immutable registration/type/address/lifetime identity per physical link.
//! Properties are canonical observation, never an author operation result.
use crate::state::SharedState;
use slk_contract::DynamicRequest;
use slk_contract::ssap::Discovery as SsapDiscovery;
use slk_contract::ssap::Entry as SsapEntry;
use slk_protocol::SleLinkInfo;
use zbus::interface;

pub(crate) use slk_contract::ConnectionInfo as Info;
pub(crate) use slk_contract::ConnectionObjects as Objects;
/// Kernel mechanism facts, never policy authorization or a future TX grant.
use slk_contract::SecurityState;

fn deadline_error(error: std::io::Error) -> zbus::fdo::Error {
    match error.raw_os_error() {
        Some(nix::libc::ETIMEDOUT) => {
            zbus::fdo::Error::Timeout("SSAP value original deadline".into())
        }
        Some(nix::libc::EINVAL) => {
            zbus::fdo::Error::InvalidArgs("invalid original deadline".into())
        }
        Some(nix::libc::EOPNOTSUPP | nix::libc::ENOENT | nix::libc::EACCES) => {
            zbus::fdo::Error::NotSupported(format!(
                "clock domain unavailable or mismatched: {error}"
            ))
        }
        _ => zbus::fdo::Error::Failed(format!("original deadline: {error}")),
    }
}

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
    slk_contract::connection_path(
        base,
        reference.address_type,
        reference.address,
        reference.lifetime,
    )
}
pub(crate) use slk_contract::peer_path;

#[derive(Clone)]
pub(crate) struct Registration {
    pub reference: SleLinkInfo,
    pub path: String,
    pub published: bool,
}
pub(crate) use slk_contract::PeerInfo;
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
    pub(crate) fn belongs_to(
        &self,
        state: &SharedState,
        generation: u64,
        key: crate::state::PeerKey,
    ) -> bool {
        self.generation == generation
            && (self.kind, self.address) == key
            && std::sync::Arc::ptr_eq(&self.state, state)
    }
    async fn observation(&self) -> (bool, bool, Vec<String>) {
        let st = self.state.lock().await;
        let (known, connected) = if st.controller.generation == self.generation {
            st.peer_connection(&(self.kind, self.address))
        } else {
            (false, false)
        };
        let objects = st
            .native_connection_objects
            .values()
            .filter(|e| {
                e.published
                    && e.reference.address_type == self.kind
                    && e.reference.address == self.address
            })
            .map(|e| e.path.clone())
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
    /// Advertisement validity and RSSI availability are independent of links.
    async fn get_observation(&self) -> zbus::fdo::Result<slk_contract::PeerObservation> {
        let st = self.state.lock().await;
        if !st.present || st.controller.generation != self.generation {
            return Err(zbus::fdo::Error::Failed("peer registration retired".into()));
        }
        let p = st
            .peers
            .get(&(self.kind, self.address))
            .filter(|p| p.publication == crate::state::PeerPublication::Published)
            .ok_or_else(|| zbus::fdo::Error::Failed("peer publication unavailable".into()))?;
        let valid = p.observation_valid();
        Ok((
            self.generation,
            self.kind,
            crate::dbus_iface::format_addr(&self.address),
            valid,
            valid && p.rssi_known,
            if valid && p.rssi_known {
                i16::from(p.rssi)
            } else {
                0
            },
            p.header.clone(),
            p.adv_data.clone(),
            p.sequence,
            p.kernel_boottime_ns,
            p.lost,
        ))
    }
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_valid(&self) -> bool {
        self.get_observation().await.is_ok_and(|v| v.3)
    }
    #[zbus(property(emits_changed_signal = "false"))]
    async fn rssi_known(&self) -> bool {
        self.get_observation().await.is_ok_and(|v| v.4)
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

enum Initialization {
    NotStarted,
    Running(tokio::task::JoinHandle<Result<(), String>>),
    Completed(Result<(), String>),
}
impl Initialization {
    async fn finish(&mut self) -> Result<(), String> {
        let result = match self {
            Self::NotStarted => return Ok(()),
            Self::Completed(result) => return result.clone(),
            Self::Running(task) => task
                .await
                .unwrap_or_else(|error| Err(format!("SSAP initialization task: {error}"))),
        };
        *self = Self::Completed(result.clone());
        result
    }
}
/// The handle stays in the owner slot while awaited. Cancelling a request
/// drops only its wait/lock, never the connection-owned initializer.
async fn initialize_once(
    slot: &tokio::sync::Mutex<Initialization>,
    retiring: &std::sync::atomic::AtomicBool,
    initialize: impl std::future::Future<Output = Result<(), String>> + Send + 'static,
) -> Result<(), String> {
    use std::sync::atomic::Ordering;
    if retiring.load(Ordering::Acquire) {
        return Err("SSAP owner retiring".into());
    }
    let mut slot = slot.lock().await;
    if retiring.load(Ordering::Acquire) {
        return Err("SSAP owner retiring".into());
    }
    if matches!(*slot, Initialization::NotStarted) {
        *slot = Initialization::Running(tokio::spawn(initialize));
    }
    let result = slot.finish().await;
    if retiring.load(Ordering::Acquire) {
        return Err("SSAP owner retiring".into());
    }
    result
}

#[derive(Clone)]
pub(crate) struct ConnectionIface {
    state: SharedState,
    generation: u64,
    reference: SleLinkInfo,
    ssap_security: u32,
    ssap: std::sync::Arc<tokio::sync::Mutex<Option<crate::ssap_engine::Engine>>>,
    ssap_initialization: std::sync::Arc<tokio::sync::Mutex<Initialization>>,
    ssap_retiring: std::sync::Arc<std::sync::atomic::AtomicBool>,
    remote_services:
        std::sync::Arc<tokio::sync::Mutex<Option<Vec<slk_protocol::ssap::discovery::Entry>>>>,
}
enum ChannelKind {
    User,
    Service,
    Dynamic(slk_native::channel::DynamicConfig),
}
impl ConnectionIface {
    pub(crate) fn new(
        state: SharedState,
        generation: u64,
        reference: SleLinkInfo,
        ssap_security: u32,
    ) -> Self {
        Self {
            state,
            generation,
            reference,
            ssap_security,
            ssap: std::sync::Arc::new(tokio::sync::Mutex::new(None)),
            ssap_initialization: std::sync::Arc::new(tokio::sync::Mutex::new(
                Initialization::NotStarted,
            )),
            ssap_retiring: std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false)),
            remote_services: std::sync::Arc::new(tokio::sync::Mutex::new(None)),
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
        slk_native::channel::validate(directions, security).map_err(|error| {
            if error.raw_os_error() == Some(nix::libc::EOPNOTSUPP) {
                zbus::fdo::Error::NotSupported("unsupported channel security requirement".into())
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
            ChannelKind::Service => slk_native::channel::open_service(
                index,
                self.generation,
                self.reference.lifetime,
                self.reference.handle,
                token,
                security,
            ),
            ChannelKind::User => slk_native::channel::open(
                index,
                self.generation,
                self.reference.lifetime,
                self.reference.handle,
                token,
                directions,
                security,
            ),
            ChannelKind::Dynamic(config) => slk_native::channel::open_dynamic(
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
        minimum: u32,
        original: slk_channel::deadline::Deadline,
    ) -> zbus::fdo::Result<Vec<u8>> {
        original.remaining().map_err(deadline_error)?;
        if minimum > 2 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "mechanism minimum0..2 required".into(),
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
            .ok_or_else(|| zbus::fdo::Error::Failed("SSAP actor unavailable".into()))?
            .observer();
        drop(actor);
        let result = observer
            .value(handle, value, minimum, original.instant().into())
            .await;
        original.remaining().map_err(deadline_error)?;
        let result = result.map_err(zbus::fdo::Error::Failed)?;
        let (known, current) = self.observation().await;
        if !known || !current {
            return Err(zbus::fdo::Error::Failed(
                "connection retired during SSAP operation".into(),
            ));
        }
        Ok(result)
    }
    async fn scoped_ssap_value(
        &self,
        handle: u16,
        value: Option<Vec<u8>>,
        minimum: u32,
        wire: slk_contract::Deadline,
        header: zbus::message::Header<'_>,
        connection: &zbus::Connection,
    ) -> zbus::fdo::Result<Vec<u8>> {
        // Decode before acquiring state/actor/lease or starting any protocol.
        let original =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(wire))
                .map_err(deadline_error)?;
        if original.remaining().map_err(deadline_error)? > slk_channel::deadline::PROTOCOL_WAIT {
            return Err(zbus::fdo::Error::InvalidArgs(
                "SSAP value deadline maximum five seconds".into(),
            ));
        }
        let sender = header
            .sender()
            .ok_or_else(|| zbus::fdo::Error::Failed("missing SSAP caller".into()))?;
        // Includes ownership subscription, locks and startup. Closing the wait
        // drops its Query receiver; physical wire obligations remain in Engine.
        let result = tokio::time::timeout_at(
            original.instant().into(),
            caller_scoped(
                connection,
                sender.as_str(),
                self.synchronous_ssap_value(handle, value, minimum, original),
            ),
        )
        .await
        .map_err(|_| zbus::fdo::Error::Timeout("SSAP value original deadline".into()))??;
        original.remaining().map_err(deadline_error)?;
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
    /// Ordinary SMTC keeps the qualified eager start. Protected SMTC is not
    /// bound before a real mechanism exists; requests and actual security
    /// completion use start_ssap, which always asks the kernel for the frozen
    /// requirement. No timer, Agent approval or cached request grants access.
    pub(crate) async fn start_ssap_on_publication(&self) -> zbus::fdo::Result<()> {
        if self.ssap_security != 0 {
            return Ok(());
        }
        self.start_ssap().await
    }
    pub(crate) async fn start_ssap(&self) -> zbus::fdo::Result<()> {
        let owner = self.clone();
        let original = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
        initialize_once(&self.ssap_initialization, &self.ssap_retiring, async move {
            owner
                .initialize_ssap(original)
                .await
                .map_err(|error| error.to_string())
        })
        .await
        .map_err(zbus::fdo::Error::Failed)
    }
    async fn initialize_ssap(&self, original: tokio::time::Instant) -> zbus::fdo::Result<()> {
        use std::sync::atomic::Ordering;
        let mut actor = self.ssap.lock().await;
        if tokio::time::Instant::now() >= original {
            return Err(zbus::fdo::Error::Timeout(
                "SSAP initialization original deadline".into(),
            ));
        }
        if self.ssap_retiring.load(Ordering::Acquire) {
            return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
        }
        if actor.is_some() {
            return Ok(());
        }
        let fd = self
            .authorized_fd(3, self.ssap_security, ChannelKind::Service)
            .await?;
        let (index, database) = self.ssap_context().await;
        if tokio::time::Instant::now() >= original {
            return Err(zbus::fdo::Error::Timeout(
                "SSAP initialization returned after original deadline".into(),
            ));
        }
        if self.ssap_retiring.load(Ordering::Acquire) {
            return Err(zbus::fdo::Error::Failed(
                "SSAP owner retired during initialization".into(),
            ));
        }
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
                original,
            )
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?,
        );
        Ok(())
    }
    pub(crate) async fn stop_ssap(&self) {
        // Fence new starters before taking the same slot. A Native bind already
        // begun retains its actual guard/fd until the initializer returns; do
        // not detach it and declare cleanup complete on an author's timeout.
        self.ssap_retiring
            .store(true, std::sync::atomic::Ordering::Release);
        if let Err(error) = self.ssap_initialization.lock().await.finish().await {
            tracing::debug!(%error, "SSAP initializer finished without a published owner");
        }
        if let Some(actor) = self.ssap.lock().await.take() {
            actor.stop().await;
        }
    }
}

#[interface(name = "org.sparklink.Connection")]
impl ConnectionIface {
    /// Fixed before the first SMTC bind; this is not a live security grade.
    #[zbus(property)]
    fn ssap_security_requirement(&self) -> u32 {
        self.ssap_security
    }
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
    /// Read the same physical Session; never use cached Agent operation state
    /// as live encryption. The kernel rechecks the original management epoch.
    async fn get_security_state(&self) -> zbus::fdo::Result<SecurityState> {
        // One original read deadline; no protocol operation or retry budget.
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "retired/unknown security lifetime".into(),
                ));
            }
            let (adapter, lease) = {
                let state = self.state.lock().await;
                (
                    state.native_control.clone().ok_or_else(|| {
                        zbus::fdo::Error::NotSupported(
                            "native security snapshot unavailable".into(),
                        )
                    })?,
                    state
                        .native_lease
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
            let generation = self.generation;
            let reference = self.reference;
            // A detached read still owns its guard/Adapter until the actual ioctl
            // returns. It cannot write keys, extend a deadline or publish a Grant.
            let value = tokio::task::spawn_blocking(move || {
                let _admission = admission;
                adapter.native_connection_security(generation, reference.lifetime, reference.handle)
            })
            .await
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
            .map_err(|e| match e {
                slk_native::Error::Ioctl(
                    nix::errno::Errno::ENOTTY | nix::errno::Errno::EOPNOTSUPP,
                ) => zbus::fdo::Error::NotSupported("kernel security snapshot unavailable".into()),
                _ => zbus::fdo::Error::Failed(e.to_string()),
            })?;
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "connection retired during security snapshot".into(),
                ));
            }
            Ok((
                value.generation,
                value.lifetime,
                value.handle,
                value.security_epoch,
                value.profile,
                value.level,
                value.flags,
                value.method,
                value.key_size,
            ))
        })
        .await
        .map_err(|_| zbus::fdo::Error::Failed("security snapshot original deadline".into()))?
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
        minimum: u32,
    ) -> zbus::fdo::Result<crate::ssap_engine::UuidValues> {
        if minimum > 2 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "mechanism minimum0..2 required".into(),
            ));
        }
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
            .read_uuid(start, end, data_type, uuid, minimum)
            .await
            .map_err(zbus::fdo::Error::Failed)?;
        if self.observation().await != (true, true) {
            return Err(zbus::fdo::Error::Failed(
                "retired read UUID lifetime".into(),
            ));
        }
        Ok(result)
    }
    async fn read_ssap_value(
        &self,
        handle: u16,
        minimum: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<Vec<u8>> {
        self.scoped_ssap_value(handle, None, minimum, deadline, header, connection)
            .await
    }
    async fn write_ssap_value(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<Vec<u8>> {
        self.scoped_ssap_value(handle, Some(value), minimum, deadline, header, connection)
            .await
    }
    /// Read-only native mechanism state via an existing owner. Do not start an
    /// SSAP Engine, open a channel, mutate credit or mint authorization here.
    async fn get_transport_status(&self) -> zbus::fdo::Result<slk_contract::TransportInfo> {
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
            Ok(slk_contract::transport_info(value))
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
        let config = slk_native::channel::DynamicConfig {
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
    async fn actual_dbus_deadline_rejects_foreign_old_shape_and_expires_before_held_state() {
        // Actual producer handler/private bus/OS clock; held state and /dev/null
        // are explicit failure dependencies, never a successful Native backend.
        let bus = crate::event_loop::tests::PrivateBus::start();
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "deadline-bus-fixture"),
            crate::profile::ProfileRegistry::new(),
        )));
        let iface = ConnectionIface::new(state.clone(), 7, SleLinkInfo::default(), 0);
        let observed = iface.clone();
        let _server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .name("org.sparklink")
            .unwrap()
            .serve_at("/org/sparklink/deadline_fixture", iface)
            .unwrap()
            .build()
            .await
            .unwrap();
        let caller = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let proxy = zbus::Proxy::new(
            &caller,
            "org.sparklink",
            "/org/sparklink/deadline_fixture",
            "org.sparklink.Connection",
        )
        .await
        .unwrap();
        let _held = state.lock().await;
        let mut bad = slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(1))
            .unwrap()
            .stamp();
        bad.boot_id[0] ^= 1;
        let wrong: zbus::Result<Vec<u8>> = tokio::time::timeout(
            std::time::Duration::from_millis(250),
            proxy.call(
                "ReadSsapValue",
                &(17u16, 0u32, slk_contract::deadline_wire(bad)),
            ),
        )
        .await
        .unwrap();
        assert!(
            matches!(wrong,Err(zbus::Error::MethodError(name,_,_))if name.as_str()=="org.freedesktop.DBus.Error.NotSupported")
        );
        let valid = slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(1))
            .unwrap()
            .stamp();
        let old: zbus::Result<Vec<u8>> = tokio::time::timeout(
            std::time::Duration::from_millis(250),
            proxy.call(
                "ReadSsapValue",
                &(
                    17u16,
                    0u32,
                    (
                        valid.monotonic_ns,
                        valid.boot_id.to_vec(),
                        valid.time_namespace_device,
                        valid.time_namespace_inode,
                    ),
                ),
            ),
        )
        .await
        .unwrap();
        // Pinned zbus rejects a malformed signature before method dispatch.
        // Decoded invalid fields use FDO InvalidArgs; this is a different stage.
        assert!(
            matches!(&old,Err(zbus::Error::MethodError(name,Some(message),_))if name.as_str()=="org.freedesktop.zbus.Error" && message.contains("got `(qu(taytt))`") && message.contains("expected `(qu(ttttt))`")),
            "exact pre-dispatch signature rejection required: {old:?}"
        );
        let original =
            slk_channel::deadline::Deadline::after(std::time::Duration::from_millis(30)).unwrap();
        let expired: zbus::Result<Vec<u8>> = tokio::time::timeout(
            std::time::Duration::from_millis(250),
            proxy.call(
                "ReadSsapValue",
                &(17u16, 0u32, slk_contract::deadline_wire(original.stamp())),
            ),
        )
        .await
        .unwrap();
        assert!(
            matches!(expired,Err(zbus::Error::MethodError(name,_,_))if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
        );
        assert!(observed.ssap.lock().await.is_none());
        assert!(matches!(
            *observed.ssap_initialization.lock().await,
            Initialization::NotStarted
        ));
    }

    #[tokio::test]
    async fn cancelling_initializer_wait_retains_one_actual_owned_task_and_failure() {
        use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
        let slot = Arc::new(Mutex::new(Initialization::NotStarted));
        let retiring = Arc::new(AtomicBool::new(false));
        let calls = Arc::new(AtomicUsize::new(0));
        let called = calls.clone();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = tokio::sync::oneshot::channel();
        let first = tokio::spawn({
            let slot = slot.clone();
            let retiring = retiring.clone();
            async move {
                initialize_once(&slot, &retiring, async move {
                    called.fetch_add(1, Ordering::SeqCst);
                    entered.send(()).unwrap();
                    released.await.unwrap();
                    Err("finite dependency failure before publication".into())
                })
                .await
            }
        });
        started.await.unwrap();
        first.abort();
        assert!(first.await.unwrap_err().is_cancelled());
        assert!(matches!(*slot.lock().await, Initialization::Running(_)));
        release.send(()).unwrap();
        let result = initialize_once(&slot, &retiring, async {
            panic!("must not retry/duplicate a cancelled wait's owned initializer")
        })
        .await;
        assert_eq!(
            result.unwrap_err(),
            "finite dependency failure before publication"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(matches!(
            *slot.lock().await,
            Initialization::Completed(Err(_))
        ));
    }

    #[tokio::test]
    async fn actual_stop_fences_starters_and_joins_callback_before_retirement() {
        use std::sync::atomic::Ordering;
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "init-retirement-fixture",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        let iface = ConnectionIface::new(state, 7, SleLinkInfo::default(), 0);
        let starter = iface.clone();
        assert!(Arc::ptr_eq(&iface.ssap, &starter.ssap));
        assert!(Arc::ptr_eq(
            &iface.remote_services,
            &starter.remote_services
        ));
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = tokio::sync::oneshot::channel();
        let start = tokio::spawn(async move {
            initialize_once(
                &starter.ssap_initialization,
                &starter.ssap_retiring,
                async move {
                    entered.send(()).unwrap();
                    released.await.unwrap();
                    Err("failure after held dependency returned".into())
                },
            )
            .await
        });
        started.await.unwrap();
        let stop = tokio::spawn({
            let owner = iface.clone();
            async move { owner.stop_ssap().await }
        });
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while !iface.ssap_retiring.load(Ordering::Acquire) {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert!(
            !stop.is_finished(),
            "cannot call unreturned dependency drained"
        );
        let denied =
            tokio::time::timeout(std::time::Duration::from_millis(100), iface.start_ssap())
                .await
                .unwrap();
        assert!(denied.is_err());
        release.send(()).unwrap();
        assert!(start.await.unwrap().unwrap_err().contains("retiring"));
        stop.await.unwrap();
        assert!(iface.ssap.lock().await.is_none());
        assert!(matches!(
            *iface.ssap_initialization.lock().await,
            Initialization::Completed(Err(_))
        ));
    }

    #[tokio::test]
    async fn actual_ssap_interface_keeps_independent_wire_signatures() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "signature-only"),
            crate::profile::ProfileRegistry::new(),
        )));
        let iface = ConnectionIface::new(state, 7, SleLinkInfo::default(), 0);
        let mut xml = String::new();
        zbus::object_server::Interface::introspect_to_writer(&iface, &mut xml, 0);
        // Literal ABI expectations independent of shared client aliases/constants.
        // No backend success fixture or protocol operation is used here.
        for (method, inputs, outputs) in [
            ("ReadSsapValue", vec!["q", "u", "(ttttt)"], vec!["ay"]),
            (
                "WriteSsapValue",
                vec!["q", "ay", "u", "(ttttt)"],
                vec!["ay"],
            ),
            (
                "DiscoverSsap",
                vec!["ay", "y"],
                vec!["(a(yqqayuayy)a(ayay))"],
            ),
            ("GetCachedSsap", vec![], vec!["a(yqqayuayy)"]),
            ("ObserveSsapIncoming", vec!["aq", "y", "u"], vec!["(bay)"]),
            (
                "ReadSsapByUuid",
                vec!["q", "q", "y", "ay", "u"],
                vec!["(a(qbqay)ayay)"],
            ),
            ("GetSsapInfo", vec![], vec!["(qttqqqayayayay)"]),
        ] {
            let start = format!("<method name=\"{method}\">");
            let body = xml
                .split_once(&start)
                .unwrap()
                .1
                .split_once("</method>")
                .unwrap()
                .0;
            let arguments = |direction| {
                body.lines()
                    .filter(|line| {
                        line.contains("<arg ")
                            && line.contains(&format!("direction=\"{direction}\""))
                    })
                    .map(|line| {
                        line.split_once("type=\"")
                            .unwrap()
                            .1
                            .split_once('"')
                            .unwrap()
                            .0
                    })
                    .collect::<Vec<_>>()
            };
            assert_eq!(arguments("in"), inputs, "{method}: {body}");
            assert_eq!(arguments("out"), outputs, "{method}: {body}");
        }
    }

    #[tokio::test]
    async fn security_snapshot_never_uses_cached_policy_or_creates_an_engine() {
        let adapter = Arc::new(slk_native::Adapter::open("/dev/null").unwrap());
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            adapter.clone(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "live-security"),
            crate::profile::ProfileRegistry::new(),
        )));
        let reference = SleLinkInfo {
            lifetime: 11,
            handle: 3,
            ..Default::default()
        };
        let iface = ConnectionIface::new(state.clone(), 7, reference, 0);
        assert!(matches!(
            iface.get_security_state().await,
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
            st.native_control = Some(adapter);
            st.native_lease = Some(Arc::new(Mutex::new(crate::state::NativeManagement {
                token: Some(1),
                accepting: true,
                connection_id: 1,
                initialized_off: [None; 2],
            })));
        }
        // Real /dev/null ioctl => ENOTTY, never a successful native fixture.
        assert!(matches!(
            iface.get_security_state().await,
            Err(zbus::fdo::Error::NotSupported(_))
        ));
        assert!(iface.ssap.lock().await.is_none());
        let _held = state.lock().await;
        let result = tokio::time::timeout(
            std::time::Duration::from_millis(1200),
            iface.get_security_state(),
        )
        .await
        .unwrap();
        assert!(
            matches!(result,Err(zbus::fdo::Error::Failed(ref e)) if e.contains("original deadline"))
        );
    }
    #[tokio::test]
    async fn protected_smtc_publication_defers_without_binding_or_mutable_policy() {
        for security in [1, 2] {
            let state =
                std::sync::Arc::new(tokio::sync::Mutex::new(crate::state::AdapterState::new(
                    slk_native::Adapter::open("/dev/null").unwrap(),
                    crate::config::DaemonConfig::default(),
                    crate::bonding::BondingStore::new(
                        std::path::Path::new("/tmp"),
                        "ssap-first-bind-policy",
                    ),
                    crate::profile::ProfileRegistry::new(),
                )));
            let iface = ConnectionIface::new(state.clone(), 7, SleLinkInfo::default(), security);
            {
                // Publication needs no native success fixture and must not
                // touch the management gate/socket before real security.
                let mut held = state.lock().await;
                held.config.ssap.channel_security = 0;
                tokio::time::timeout(
                    std::time::Duration::from_millis(100),
                    iface.start_ssap_on_publication(),
                )
                .await
                .unwrap()
                .unwrap();
            }
            assert_eq!(iface.ssap_security_requirement(), security);
            assert!(iface.ssap.lock().await.is_none());
            assert!(matches!(
                iface.start_ssap().await,
                Err(zbus::fdo::Error::Failed(_))
            ));
            assert!(iface.ssap.lock().await.is_none());
            // A failed admission does not manufacture an Engine or alter its
            // frozen security requirement. No real AF_SPARKLINK here.
            assert_eq!(iface.ssap_security_requirement(), security);
        }
    }
    #[tokio::test]
    async fn ssap_start_context_releases_one_adapter_guard_before_actor_arguments() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "ssap-context-regression",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        state.lock().await.controller.dev_index = 17;
        let iface = ConnectionIface::new(state.clone(), 7, SleLinkInfo::default(), 0);
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
            Arc::new(slk_native::Adapter::open("/dev/null").unwrap()),
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
        let iface = ConnectionIface::new(state.clone(), 7, reference, 0);
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
            Arc::new(slk_native::Adapter::open("/dev/null").unwrap()),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "grant-policy-rejection",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        let interface = ConnectionIface::new(state.clone(), 7, SleLinkInfo::default(), 0);
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
        for security in [3, u32::MAX] {
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
