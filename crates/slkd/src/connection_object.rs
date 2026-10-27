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

use crate::deadline_error;

/// Subscribe before checking ownership or polling the receive future. Known
/// bus-owner loss cancels the call-owned queue; it does not erase queued ACKs.
pub(crate) async fn caller_scoped<T>(
    connection: &zbus::Connection,
    sender: &str,
    future: impl std::future::Future<Output = zbus::fdo::Result<T>>,
) -> zbus::fdo::Result<T> {
    caller_scoped_as(connection, sender, "SSAP application", future).await
}

pub(crate) async fn caller_scoped_as<T>(
    connection: &zbus::Connection,
    sender: &str,
    domain: &'static str,
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
        return Err(zbus::fdo::Error::Failed(format!("{domain} caller retired")));
    }
    tokio::select! {
        biased;
        _=lost.next()=>Err(zbus::fdo::Error::Failed(format!("{domain} caller disappeared or owner stream closed"))),
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
    pub owner: std::sync::Arc<ConnectionOwner>,
}

pub(crate) struct Registrations {
    pub pending: Vec<Registration>,
    pub retired: Vec<Registration>,
    pub refused: usize,
}

pub(crate) async fn retire_registration(
    connection: &zbus::Connection,
    entry: &Registration,
) -> zbus::Result<()> {
    entry.owner.shutdown().await;
    match connection
        .object_server()
        .interface::<_, ConnectionIface>(entry.path.as_str())
        .await
    {
        Ok(iface) => {
            if !iface.get().await.belongs_to(&entry.owner) {
                return Err(zbus::Error::Failure(
                    "foreign connection owner during retirement".into(),
                ));
            }
        }
        Err(zbus::Error::InterfaceNotFound) => return Ok(()),
        Err(error) => return Err(error),
    }
    connection
        .object_server()
        .remove::<ConnectionIface, _>(entry.path.as_str())
        .await?;
    Ok(())
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
    Running(tokio::task::JoinHandle<zbus::fdo::Result<()>>),
    Completed(zbus::fdo::Result<()>),
}
impl Initialization {
    fn begin<F>(&mut self, initialize: impl FnOnce() -> F)
    where
        F: std::future::Future<Output = zbus::fdo::Result<()>> + Send + 'static,
    {
        if matches!(self, Self::NotStarted) {
            *self = Self::Running(tokio::spawn(initialize()));
        }
    }

    async fn finish(&mut self) -> zbus::fdo::Result<()> {
        let result = match self {
            Self::NotStarted => return Ok(()),
            Self::Completed(result) => return result.clone(),
            Self::Running(task) => task.await.unwrap_or_else(|error| {
                Err(zbus::fdo::Error::Failed(format!(
                    "SSAP initialization task: {error}"
                )))
            }),
        };
        *self = Self::Completed(result.clone());
        result
    }
}
/// The handle stays in the owner slot while awaited. Cancelling a request
/// drops only its wait/lock, never the connection-owned initializer.
async fn initialize_once<F>(
    slot: &tokio::sync::Mutex<Initialization>,
    retiring: &std::sync::atomic::AtomicBool,
    initialize: impl FnOnce() -> F + Send + 'static,
) -> zbus::fdo::Result<()>
where
    F: std::future::Future<Output = zbus::fdo::Result<()>> + Send + 'static,
{
    use std::sync::atomic::Ordering;
    if retiring.load(Ordering::Acquire) {
        return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
    }
    let mut slot = slot.lock().await;
    if retiring.load(Ordering::Acquire) {
        return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
    }
    slot.begin(initialize);
    let result = slot.finish().await;
    if retiring.load(Ordering::Acquire) {
        return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
    }
    result
}

// Keep the established public Native refusal name/body. Internally AccessDenied
// identifies only EACCES returned by a completed creation with no returned fd;
// never infer retry eligibility by matching an error string.
fn public_native_error(error: zbus::fdo::Error) -> zbus::fdo::Error {
    match error {
        zbus::fdo::Error::AccessDenied(message) => zbus::fdo::Error::Failed(message),
        other => other,
    }
}

/// Native socket creation can sleep in the kernel. Its actual admission guard
/// stays with that work even if the async caller stops waiting. This is the
/// same owner retirement flag, not a second authorization/state source.
async fn bind_off_worker(
    retiring: std::sync::Arc<std::sync::atomic::AtomicBool>,
    creation: tokio::sync::OwnedMutexGuard<()>,
    admission: tokio::sync::OwnedMutexGuard<crate::state::NativeManagement>,
    original: Option<tokio::time::Instant>,
    bind: impl FnOnce() -> std::io::Result<std::os::fd::OwnedFd> + Send + 'static,
) -> zbus::fdo::Result<std::os::fd::OwnedFd> {
    let in_worker = retiring.clone();
    let completed = tokio::task::spawn_blocking(move || {
        let _admission = admission;
        // Keep this guard until the returned fd is consumed or discarded,
        // including the interval where the completed task is not polled.
        let held_creation = creation;
        if in_worker.load(std::sync::atomic::Ordering::Acquire) {
            return Err(zbus::fdo::Error::Failed("connection owner retiring".into()));
        }
        if original.is_some_and(|deadline| tokio::time::Instant::now() >= deadline) {
            return Err(zbus::fdo::Error::Timeout(
                "Native creation original deadline".into(),
            ));
        }
        let fd = bind().map_err(|error| {
            if error.raw_os_error() == Some(nix::libc::EOPNOTSUPP) {
                zbus::fdo::Error::NotSupported(
                    "channel mode or same-lifetime rebinding is not supported".into(),
                )
            } else if error.raw_os_error() == Some(nix::libc::EACCES) {
                // open_service's failed socket/bind closes its unbound fd.
                // sl_publish_binding rejects before attaching or kicking SMTC.
                zbus::fdo::Error::AccessDenied(format!("native channel bind: {error}"))
            } else {
                zbus::fdo::Error::Failed(format!("native channel bind: {error}"))
            }
        })?;
        if in_worker.load(std::sync::atomic::Ordering::Acquire) {
            // fd is still uniquely owned here; rejection closes the real
            // returned descriptor instead of publishing it after retirement.
            return Err(zbus::fdo::Error::Failed(
                "connection owner retired during native bind".into(),
            ));
        }
        // Field order is deliberate: discarding a queued result closes the
        // fd before releasing its creation/drain guard.
        Ok((fd, held_creation))
    })
    .await
    .map_err(|error| zbus::fdo::Error::Failed(format!("native bind task: {error}")))??;
    if retiring.load(std::sync::atomic::Ordering::Acquire) {
        return Err(zbus::fdo::Error::Failed(
            "connection owner retired before native bind receipt".into(),
        ));
    }
    if original.is_some_and(|deadline| tokio::time::Instant::now() >= deadline) {
        return Err(zbus::fdo::Error::Timeout(
            "Native creation original deadline".into(),
        ));
    }
    Ok(completed.0)
}

/// Resource owner retained by the controller before any Native creation.
/// Weak context prevents the State -> Registration -> Owner -> State cycle.
/// D-Bus views reference this owner; publication is not its lifetime root.
pub(crate) struct ConnectionOwner {
    context: std::sync::Weak<tokio::sync::Mutex<crate::state::AdapterState>>,
    generation: u64,
    reference: SleLinkInfo,
    ssap_security: u32,
    ssap: tokio::sync::Mutex<Option<crate::ssap_engine::Engine>>,
    ssap_initialization: tokio::sync::Mutex<Initialization>,
    ssap_retiring: std::sync::Arc<std::sync::atomic::AtomicBool>,
    native_creations: std::sync::Arc<tokio::sync::Mutex<()>>,
    remote_services: tokio::sync::Mutex<Option<Vec<slk_protocol::ssap::discovery::Entry>>>,
}

#[derive(Clone)]
pub(crate) struct ConnectionIface {
    state: SharedState,
    owner: std::sync::Arc<ConnectionOwner>,
}
impl std::ops::Deref for ConnectionIface {
    type Target = ConnectionOwner;
    fn deref(&self) -> &ConnectionOwner {
        &self.owner
    }
}
enum ChannelKind {
    User,
    Dynamic(slk_native::channel::DynamicConfig),
}
/// A ready inner error may win Tokio's timeout poll at the deadline. Check
/// the original clock before propagating either success or that inner error;
/// callers then see Timeout consistently, without parsing diagnostic strings.
fn finish_scoped_ssap_call<T>(
    original: slk_channel::deadline::Deadline,
    result: zbus::fdo::Result<T>,
) -> zbus::fdo::Result<T> {
    original.remaining().map_err(deadline_error)?;
    result
}

impl ConnectionOwner {
    async fn bind_native(
        &self,
        admission: tokio::sync::OwnedMutexGuard<crate::state::NativeManagement>,
        bind: impl FnOnce() -> std::io::Result<std::os::fd::OwnedFd> + Send + 'static,
    ) -> zbus::fdo::Result<std::os::fd::OwnedFd> {
        if self.is_retiring() {
            return Err(zbus::fdo::Error::Failed("connection owner retiring".into()));
        }
        let creation = self
            .native_creations
            .clone()
            .try_lock_owned()
            .map_err(|_| zbus::fdo::Error::Failed("connection Native creation busy".into()))?;
        bind_off_worker(self.ssap_retiring.clone(), creation, admission, None, bind)
            .await
            .map_err(public_native_error)
    }

    pub(crate) fn new(
        state: &SharedState,
        generation: u64,
        reference: SleLinkInfo,
        ssap_security: u32,
    ) -> std::sync::Arc<Self> {
        std::sync::Arc::new(Self {
            context: std::sync::Arc::downgrade(state),
            generation,
            reference,
            ssap_security,
            ssap: tokio::sync::Mutex::new(None),
            ssap_initialization: tokio::sync::Mutex::new(Initialization::NotStarted),
            ssap_retiring: std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false)),
            native_creations: std::sync::Arc::new(tokio::sync::Mutex::new(())),
            remote_services: tokio::sync::Mutex::new(None),
        })
    }
    fn context(&self) -> zbus::fdo::Result<SharedState> {
        self.context
            .upgrade()
            .ok_or_else(|| zbus::fdo::Error::Failed("controller context retired".into()))
    }
    pub(crate) fn retire(&self) {
        self.ssap_retiring
            .store(true, std::sync::atomic::Ordering::Release);
    }
    pub(crate) fn is_retiring(&self) -> bool {
        self.ssap_retiring
            .load(std::sync::atomic::Ordering::Acquire)
    }
    async fn observation(&self) -> (bool, bool) {
        let Some(context) = self.context.upgrade() else {
            return (false, false);
        };
        let st = context.lock().await;
        let known = st.controller.generation == self.generation && st.native_links_known();
        let current = known
            && st
                .native_links
                .as_ref()
                .is_some_and(|table| table.links[..table.count as usize].contains(&self.reference));
        (known, current)
    }
    async fn binding_context(
        &self,
        directions: u32,
        security: u32,
    ) -> zbus::fdo::Result<(u16, crate::state::NativeLease)> {
        if self.is_retiring() {
            return Err(zbus::fdo::Error::Failed("connection owner retiring".into()));
        }
        let context = self.context()?;
        slk_native::channel::validate(directions, security).map_err(|error| {
            if error.raw_os_error() == Some(nix::libc::EOPNOTSUPP) {
                zbus::fdo::Error::NotSupported("unsupported channel security requirement".into())
            } else {
                zbus::fdo::Error::InvalidArgs("invalid channel authorization directions".into())
            }
        })?;
        let st = context.lock().await;
        if !st.present
            || st.controller.generation != self.generation
            || !st.native_links_known()
            || !st
                .native_links
                .as_ref()
                .is_some_and(|table| table.links[..table.count as usize].contains(&self.reference))
        {
            return Err(zbus::fdo::Error::Failed(
                "connection lifetime is not current".into(),
            ));
        }
        Ok((
            st.controller.dev_index,
            st.native_lease
                .clone()
                .ok_or_else(|| zbus::fdo::Error::Failed("management unavailable".into()))?,
        ))
    }
    fn admission_token(admission: &crate::state::NativeManagement) -> zbus::fdo::Result<u64> {
        if !admission.accepting {
            return Err(zbus::fdo::Error::Failed("management unavailable".into()));
        }
        admission
            .token
            .ok_or_else(|| zbus::fdo::Error::Failed("management unavailable".into()))
    }
    async fn authorized_fd(
        &self,
        directions: u32,
        security: u32,
        kind: ChannelKind,
    ) -> zbus::fdo::Result<std::os::fd::OwnedFd> {
        let (index, lease) = self.binding_context(directions, security).await?;
        let admission = lease
            .try_lock_owned()
            .map_err(|_| zbus::fdo::Error::Failed("management handoff busy".into()))?;
        let token = Self::admission_token(&admission)?;
        let (generation, lifetime, handle) = (
            self.generation,
            self.reference.lifetime,
            self.reference.handle,
        );
        self.bind_native(admission, move || match kind {
            ChannelKind::User => slk_native::channel::open(
                index, generation, lifetime, handle, token, directions, security,
            ),
            ChannelKind::Dynamic(config) => slk_native::channel::open_dynamic(
                index, generation, lifetime, handle, token, config,
            ),
        })
        .await
    }
    async fn authorized_service_fd(
        &self,
        original: tokio::time::Instant,
        creation: tokio::sync::OwnedMutexGuard<()>,
    ) -> zbus::fdo::Result<std::os::fd::OwnedFd> {
        let security = self.ssap_security;
        let (index, lease) = self.binding_context(3, security).await?;
        // One registered initializer per connection bounds these waiters.
        // The original whole-initialization deadline includes this wait.
        let admission = tokio::time::timeout_at(original, lease.lock_owned())
            .await
            .map_err(|_| zbus::fdo::Error::Timeout("Native admission original deadline".into()))?;
        let token = Self::admission_token(&admission)?;
        let (generation, lifetime, handle) = (
            self.generation,
            self.reference.lifetime,
            self.reference.handle,
        );
        bind_off_worker(
            self.ssap_retiring.clone(),
            creation,
            admission,
            Some(original),
            move || {
                slk_native::channel::open_service(
                    index, generation, lifetime, handle, token, security,
                )
            },
        )
        .await
    }
}

impl ConnectionIface {
    async fn validate_update_targets(&self, handles: &[u16], modes: u8) -> zbus::fdo::Result<()> {
        let cache = self.remote_services.lock().await;
        let entries = cache.as_ref().ok_or_else(|| {
            zbus::fdo::Error::NotSupported(
                "actual peer discovery required before receive transaction".into(),
            )
        })?;
        let required = (u32::from(modes) << 3) | 512;
        if handles.iter().any(|handle| {
            !entries.iter().any(|e| {
                e.handle == *handle
                    && e.category & 7 == 2
                    && e.operations & required == required
                    && e.descriptors.contains(&2)
            })
        }) {
            return Err(zbus::fdo::Error::NotSupported(
                "peer has not advertised requested property update capabilities".into(),
            ));
        }
        Ok(())
    }
    pub(crate) fn from_owner(
        state: SharedState,
        owner: std::sync::Arc<ConnectionOwner>,
    ) -> zbus::fdo::Result<Self> {
        if !owner.context.ptr_eq(&std::sync::Arc::downgrade(&state)) {
            return Err(zbus::fdo::Error::Failed(
                "foreign controller service owner".into(),
            ));
        }
        Ok(Self { state, owner })
    }
    pub(crate) fn belongs_to(&self, owner: &std::sync::Arc<ConnectionOwner>) -> bool {
        std::sync::Arc::ptr_eq(&self.owner, owner)
    }
    #[cfg(test)]
    pub(crate) fn new(
        state: SharedState,
        generation: u64,
        reference: SleLinkInfo,
        security: u32,
    ) -> Self {
        let owner = ConnectionOwner::new(&state, generation, reference, security);
        Self::from_owner(state, owner).unwrap()
    }
    async fn start_ssap(&self) -> zbus::fdo::Result<()> {
        self.owner.start_ssap().await
    }
    #[cfg(test)]
    async fn prime_ssap_on_publication(&self) -> zbus::fdo::Result<()> {
        self.owner.prime_ssap_on_publication()
    }
    #[cfg(test)]
    async fn shutdown(&self) {
        self.owner.shutdown().await;
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
    async fn owned_ssap_preflight(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
        header: &zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<()> {
        let original =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(deadline))
                .map_err(deadline_error)?;
        original.remaining().map_err(deadline_error)?;
        let caller = header
            .sender()
            .ok_or_else(|| zbus::fdo::Error::AccessDenied("missing original caller".into()))?;
        tokio::time::timeout_at(original.instant().into(), async {
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "owned SSAP lifetime retired".into(),
                ));
            }
            let store = self.state.lock().await.ssap_database.clone();
            store
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?
                .owned_update(handle, caller.as_str())
                .map(|_| ())
                .map_err(zbus::fdo::Error::AccessDenied)
        })
        .await
        .map_err(|_| zbus::fdo::Error::Timeout("owned SSAP original preflight deadline".into()))?
    }
    async fn scoped_ssap_call<T, F>(
        &self,
        wire: slk_contract::Deadline,
        limit: std::time::Duration,
        header: zbus::message::Header<'_>,
        connection: &zbus::Connection,
        work: impl FnOnce(crate::ssap_engine::Observer, String, tokio::time::Instant) -> F,
    ) -> zbus::fdo::Result<T>
    where
        F: std::future::Future<Output = zbus::fdo::Result<T>>,
    {
        let original =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(wire))
                .map_err(deadline_error)?;
        if original.remaining().map_err(deadline_error)? > limit {
            return Err(zbus::fdo::Error::InvalidArgs(
                "SSAP operation exceeds its original deadline limit".into(),
            ));
        }
        let sender = header
            .sender()
            .ok_or_else(|| zbus::fdo::Error::Failed("missing SSAP owner".into()))?
            .to_string();
        let result = tokio::time::timeout_at(
            original.instant().into(),
            caller_scoped(connection, &sender, async {
                self.get_ssap_info().await?;
                let observer = self
                    .ssap
                    .lock()
                    .await
                    .as_ref()
                    .ok_or_else(|| zbus::fdo::Error::Failed("SSAP actor unavailable".into()))?
                    .observer();
                let result = work(observer, sender.clone(), original.instant().into()).await?;
                if self.observation().await != (true, true) {
                    return Err(zbus::fdo::Error::Failed(
                        "owned SSAP connection retired".into(),
                    ));
                }
                Ok(result)
            }),
        )
        .await
        .map_err(|_| zbus::fdo::Error::Timeout("owned SSAP original deadline".into()))?;
        finish_scoped_ssap_call(original, result)
    }
}

impl ConnectionOwner {
    #[cfg(test)]
    pub(crate) async fn initialize_with_fixture(
        self: &std::sync::Arc<Self>,
        dependency: impl std::future::Future<Output = Result<(), String>> + Send + 'static,
    ) -> Result<(), String> {
        // Same production owned slot and transition; only the Native
        // dependency is controlled. No socket/protocol success is simulated.
        initialize_once(
            &self.ssap_initialization,
            &self.ssap_retiring,
            move || async move { dependency.await.map_err(zbus::fdo::Error::Failed) },
        )
        .await
        .map_err(|error| match error {
            zbus::fdo::Error::Failed(message) => message,
            other => other.to_string(),
        })
    }

    async fn ssap_context(
        &self,
    ) -> zbus::fdo::Result<(
        u16,
        std::sync::Arc<std::sync::Mutex<crate::ssap_database::Database>>,
    )> {
        let context = self.context()?;
        let state = context.lock().await;
        Ok((state.controller.dev_index, state.ssap_database.clone()))
    }
    /// Ordinary SMTC requests the same eager start. Protected SMTC is not
    /// bound before a real mechanism exists; requests and actual security
    /// completion use start_ssap, which always asks the kernel for the frozen
    /// requirement. No timer, Agent approval or cached request grants access.
    pub(crate) fn prime_ssap_on_publication(self: &std::sync::Arc<Self>) -> zbus::fdo::Result<()> {
        if self.ssap_security != 0 {
            return Ok(());
        }
        if self.is_retiring() {
            return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
        }
        // A busy slot belongs to the existing initializer/stop waiter. Do not
        // join it from physical observation, or create an additional task.
        let Ok(mut slot) = self.ssap_initialization.try_lock() else {
            return Ok(());
        };
        if self.is_retiring() {
            return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
        }
        let owner = self.clone();
        let original = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
        slot.begin(move || owner.ssap_initializer(original));
        Ok(()) // scheduling only; never SSAP readiness or negotiation success
    }
    fn ssap_initializer(
        self: std::sync::Arc<Self>,
        original: tokio::time::Instant,
    ) -> impl std::future::Future<Output = zbus::fdo::Result<()>> + Send + 'static {
        // Executed only by the first admitted slot, before physical publication.
        // Reserving this gate cannot start wire work or confer a kernel grant.
        let reserved = self.native_creations.clone().try_lock_owned().ok();
        let owner = self;
        async move {
            let result = match tokio::time::timeout_at(original, async {
                let creation = match reserved {
                    Some(guard) => guard,
                    None => owner.native_creations.clone().lock_owned().await,
                };
                owner.initialize_ssap(original, creation).await
            })
            .await
            {
                Ok(result) => result,
                Err(_) => Err(zbus::fdo::Error::Timeout(
                    "SSAP initialization original deadline".into(),
                )),
            };
            if let Err(error) = &result {
                tracing::warn!(%error,lifetime=owner.reference.lifetime,"SSAP initializer ended with error");
            }
            result
        }
    }
    pub(crate) async fn start_ssap(self: &std::sync::Arc<Self>) -> zbus::fdo::Result<()> {
        let owner = self.clone();
        let original = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
        initialize_once(&self.ssap_initialization, &self.ssap_retiring, move || {
            owner.ssap_initializer(original)
        })
        .await
        .map_err(public_native_error)
    }
    /// Only the real completed-security path calls this. Joining comes before
    /// clearing a definite, no-fd admission refusal. Unknown failures and any
    /// already-started Engine remain terminal; bind rechecks actual authority.
    pub(crate) async fn start_ssap_after_security(
        self: &std::sync::Arc<Self>,
    ) -> zbus::fdo::Result<()> {
        self.rearm_refused_initialization().await?;
        self.start_ssap().await
    }
    async fn rearm_refused_initialization(&self) -> zbus::fdo::Result<()> {
        use std::sync::atomic::Ordering;
        if self.ssap_security != 0 {
            let mut slot = self.ssap_initialization.lock().await;
            if self.ssap_retiring.load(Ordering::Acquire) {
                return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
            }
            let _ = slot.finish().await;
            if self.ssap_retiring.load(Ordering::Acquire) {
                return Err(zbus::fdo::Error::Failed("SSAP owner retiring".into()));
            }
            if matches!(
                &*slot,
                Initialization::Completed(Err(zbus::fdo::Error::AccessDenied(_)))
            ) {
                if self.ssap.lock().await.is_some() {
                    return Err(zbus::fdo::Error::Failed(
                        "refused initializer unexpectedly owns an Engine".into(),
                    ));
                }
                *slot = Initialization::NotStarted;
            }
        }
        Ok(())
    }
    async fn initialize_ssap(
        &self,
        original: tokio::time::Instant,
        creation: tokio::sync::OwnedMutexGuard<()>,
    ) -> zbus::fdo::Result<()> {
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
        let fd = self.authorized_service_fd(original, creation).await?;
        let (index, database) = self.ssap_context().await?;
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
    pub(crate) async fn shutdown(&self) {
        // Fence new starters before taking the same slot. A Native bind already
        // begun retains its actual guard/fd until the initializer returns; do
        // not detach it and declare cleanup complete on an author's timeout.
        self.retire();
        if let Err(error) = self.ssap_initialization.lock().await.finish().await {
            tracing::debug!(%error, "SSAP initializer finished without a published owner");
        }
        // User/dynamic creation is not a service initializer. Join its actual
        // work and any queued fd receipt too, before retiring this owner.
        let _creations = self.native_creations.lock().await;
        // The Engine and its JoinHandle stay in the owner while awaiting.
        // Cancelling this wait must not detach the task or let a second stop
        // observe an empty slot before the first actual join has completed.
        let mut actor = self.ssap.lock().await;
        if let Some(engine) = actor.as_mut() {
            engine.stop().await;
        }
        actor.take();
    }
}

#[interface(name = "org.sparklink.Connection")]
impl ConnectionIface {
    /// Explicit controller-management operation. A real Complete acknowledges
    /// the preference only; neither effective payload, MTU nor Ready changes.
    async fn set_link_payload_preference(
        &self,
        requested_octets: u16,
        wire: slk_contract::Deadline,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::link_parameter::Acknowledgment> {
        if requested_octets == 0 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero16bit payload preference required".into(),
            ));
        }
        let deadline =
            slk_channel::deadline::Deadline::from_stamp(slk_contract::deadline_stamp(wire))
                .map_err(deadline_error)?;
        if deadline.remaining().map_err(deadline_error)? > slk_channel::deadline::PROTOCOL_WAIT {
            return Err(zbus::fdo::Error::InvalidArgs(
                "link preference maximum five seconds".into(),
            ));
        }
        let deadline_monotonic_ns = deadline.stamp().monotonic_ns;
        let original = deadline.instant();
        let sender = crate::security_policy::sender(&header)?;
        let work = async {
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "retired/unknown connection lifetime".into(),
                ));
            }
            let value = crate::link_command::set_payload_preference(
                &self.state,
                self.generation,
                self.reference,
                requested_octets,
                original,
                deadline_monotonic_ns,
            )
            .await?;
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "connection retired during link preference command".into(),
                ));
            }
            Ok(value)
        };
        tokio::time::timeout_at(
            tokio::time::Instant::from_std(original),
            caller_scoped_as(connection, &sender, "Native link payload preference", work),
        )
        .await
        .map_err(|_| zbus::fdo::Error::Failed("link preference original deadline".into()))?
    }

    /// Management-role RPC: submits protocol work, not a passive observer
    /// property. The system bus default/apps policy does not allow this method.
    async fn read_link_measurement(
        &self,
        kind: u8,
        timeout_ms: u32,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::link_query::Observation> {
        if !matches!(kind, 1 | 2) || !(1..=5000).contains(&timeout_ms) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "kind1RSSI/2PHY and1..5000ms required".into(),
            ));
        }
        let deadline_monotonic_ns = crate::security_policy::monotonic_ns()?
            .checked_add(u64::from(timeout_ms) * 1_000_000)
            .ok_or_else(|| zbus::fdo::Error::InvalidArgs("deadline overflow".into()))?;
        let original = std::time::Instant::now()
            .checked_add(std::time::Duration::from_millis(u64::from(timeout_ms)))
            .ok_or_else(|| zbus::fdo::Error::InvalidArgs("deadline overflow".into()))?;
        let sender = crate::security_policy::sender(&header)?;
        let work = async {
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "retired/unknown connection lifetime".into(),
                ));
            }
            let value = crate::link_command::read(
                &self.state,
                self.generation,
                self.reference,
                kind,
                original,
                deadline_monotonic_ns,
            )
            .await?;
            if self.observation().await != (true, true) {
                return Err(zbus::fdo::Error::Failed(
                    "connection retired during link observation".into(),
                ));
            }
            Ok(value)
        };
        tokio::time::timeout_at(
            tokio::time::Instant::from_std(original),
            caller_scoped_as(connection, &sender, "Native link observation", work),
        )
        .await
        .map_err(|_| zbus::fdo::Error::Failed("link observation original deadline".into()))?
    }

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
            4 => slk_protocol::ssap::discovery::FindKind::Methods,
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
    /// Own a bounded remote CPCD transaction,not an adapter-wide subscription.
    async fn receive_ssap_update(
        &self,
        handles: Vec<u16>,
        modes: u8,
        deadline: slk_contract::Deadline,
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
        {
            return Err(zbus::fdo::Error::InvalidArgs(
                "1..32 unique handles and modes1..3 required".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            std::time::Duration::from_secs(10),
            header,
            connection,
            |observer, _caller, original| async move {
                self.validate_update_targets(&handles, modes).await?;
                observer
                    .incoming(handles, modes, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    /// One caller-owned leased stream;configuration and cleanup use the same actor.
    async fn subscribe_ssap_updates(
        &self,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        deadline: slk_contract::Deadline,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Info> {
        if !slk_contract::ssap::subscription::valid_request(&handles, modes, duration_ms) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "subscription handles/modes/lease250..60000ms".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            std::time::Duration::from_secs(5),
            header,
            connection,
            |observer, caller, original| async move {
                self.validate_update_targets(&handles, modes).await?;
                let slots = self.state.lock().await.ssap_subscription_slots.clone();
                let slot = slots.try_acquire_owned().map_err(|_| {
                    zbus::fdo::Error::LimitsExceeded("subscription owner budget".into())
                })?;
                let owner =
                    crate::ssap_subscription::CallerLease::pin(connection, caller, slot, original)
                        .await
                        .map_err(zbus::fdo::Error::Failed)?;
                observer
                    .subscribe(owner, handles, modes, duration_ms, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
        .inspect_err(|error| {
            tracing::warn!(%error, generation=self.generation,
                lifetime=self.reference.lifetime, "SSAP subscription acquisition refused");
        })
    }
    async fn read_ssap_updates(
        &self,
        token: u64,
        wait: bool,
        deadline: slk_contract::Deadline,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Batch> {
        if token == 0 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero subscription token".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            std::time::Duration::from_secs(10),
            header,
            connection,
            |observer, caller, original| async move {
                observer
                    .subscription_read(caller, token, wait, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    async fn renew_ssap_subscription(
        &self,
        token: u64,
        duration_ms: u32,
        deadline: slk_contract::Deadline,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Info> {
        if token == 0 || !(250..=60000).contains(&duration_ms) {
            return Err(zbus::fdo::Error::InvalidArgs(
                "subscription token/lease".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            std::time::Duration::from_secs(5),
            header,
            connection,
            |observer, caller, original| async move {
                observer
                    .subscription_renew(caller, token, duration_ms, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    async fn close_ssap_subscription(
        &self,
        token: u64,
        deadline: slk_contract::Deadline,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<slk_contract::ssap::subscription::Batch> {
        if token == 0 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero subscription token".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            std::time::Duration::from_secs(5),
            header,
            connection,
            |observer, caller, original| async move {
                observer
                    .subscription_close(caller, token, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
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
    /// Read public type1 metadata through the original physical SSAP actor.
    /// minimum constrains the request channel, not descriptor permissions.
    async fn read_ssap_description(
        &self,
        handle: u16,
        minimum: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<Vec<u8>> {
        if handle == 0 || minimum > 2 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero description handle and mechanism minimum0..2 required".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            slk_channel::deadline::PROTOCOL_WAIT,
            header,
            connection,
            |observer, _caller, original| async move {
                observer
                    .read_description(handle, minimum, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
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
    /// No peer acknowledgement exists for Write Command. A successful call
    /// reports complete software admission only, never a remote database write.
    async fn write_ssap_command(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<()> {
        if handle == 0 || minimum > 2 || value.len() > 2042 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero handle, mechanism minimum0..2 and value<=2042 required".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            slk_channel::deadline::PROTOCOL_WAIT,
            header,
            connection,
            |observer, _caller, original| async move {
                observer
                    .write_command(handle, value, minimum, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    /// Invoke a remote method on this original physical Session. No local
    /// method database, echo or implicit retry is created by this requester.
    async fn call_ssap_method(
        &self,
        handle: u16,
        arguments: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<Vec<u8>> {
        if handle == 0 || minimum > 2 || arguments.len() > 2043 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero method handle, minimum0..2 and arguments<=2043 required".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            slk_channel::deadline::PROTOCOL_WAIT,
            header,
            connection,
            |observer, _caller, original| async move {
                observer
                    .call_method(handle, arguments, minimum, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    /// Software admission only; the peer must not send a method response.
    async fn call_ssap_method_command(
        &self,
        handle: u16,
        arguments: Vec<u8>,
        minimum: u32,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<()> {
        if handle == 0 || minimum > 2 || arguments.len() > 2043 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "nonzero method handle, minimum0..2 and arguments<=2043 required".into(),
            ));
        }
        self.scoped_ssap_call(
            deadline,
            slk_channel::deadline::PROTOCOL_WAIT,
            header,
            connection,
            |observer, _caller, original| async move {
                observer
                    .call_method_command(handle, arguments, minimum, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    /// A stage1 receipt is software admission; stage2 is peer queue ACK only.
    /// The actual unique caller must still own the property at submission.
    async fn send_owned_ssap_update(
        &self,
        handle: u16,
        indication: bool,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<slk_contract::ssap::UpdateReceipt> {
        self.owned_ssap_preflight(handle, deadline, &header).await?;
        self.scoped_ssap_call(
            deadline,
            slk_channel::deadline::PROTOCOL_WAIT,
            header,
            connection,
            |observer, caller, original| async move {
                observer
                    .update(caller, handle, indication, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
        .await
    }
    /// Observe this Session's existing client configuration, not a Ready/Grant.
    async fn get_owned_ssap_configuration(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> zbus::fdo::Result<u8> {
        self.owned_ssap_preflight(handle, deadline, &header).await?;
        self.scoped_ssap_call(
            deadline,
            slk_channel::deadline::PROTOCOL_WAIT,
            header,
            connection,
            |observer, caller, original| async move {
                observer
                    .configuration(caller, handle, original)
                    .await
                    .map_err(zbus::fdo::Error::Failed)
            },
        )
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

    fn run_fd_case_isolated(name: &str) -> bool {
        const CHILD: &str = "SPARKLINK_FD_CASE_CHILD";
        if std::env::var(CHILD).as_deref() == Ok(name) {
            return false;
        }
        // CLOEXEC does not prevent another test's fork from temporarily
        // retaining this socket before exec. Create the tested fd only in an
        // exec'd child running this exact case, with no private-bus spawns.
        // Keep the actual production call, joins and close assertions intact.
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                &format!("connection_object::grant_tests::{name}"),
                "--test-threads=1",
            ])
            .env(CHILD, name)
            .output()
            .unwrap();
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(
            output.status.success()
                && stdout.contains("running 1 test")
                && stdout.contains("test result: ok. 1 passed; 0 failed; 0 ignored;"),
            "isolated fd regression {name}: {}\n{stdout}\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
        true
    }

    fn bind_lease() -> crate::state::NativeLease {
        Arc::new(Mutex::new(crate::state::NativeManagement {
            token: Some(19),
            accepting: true,
            connection_id: 0,
            initialized_off: [None; 2],
        }))
    }

    #[tokio::test]
    async fn r5f9f_first_initializer_reserves_native_creation_before_publication() {
        // Unknown Native/table dependency prevents any AF_SPARKLINK call.
        // Test actual task admission/reservation, not a successful backend.
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "initial-native-reservation",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = ConnectionOwner::new(
            &state,
            7,
            SleLinkInfo {
                lifetime: 1,
                handle: 7,
                ..Default::default()
            },
            0,
        );
        owner.prime_ssap_on_publication().unwrap();
        assert!(
            owner.native_creations.try_lock().is_err(),
            "first service Native claim must precede exposing the physical view to app creators"
        );
        let id = match &*owner.ssap_initialization.try_lock().unwrap() {
            Initialization::Running(task) => task.id(),
            _ => panic!("one original task required"),
        };
        owner.prime_ssap_on_publication().unwrap();
        assert!(
            matches!(&*owner.ssap_initialization.try_lock().unwrap(),Initialization::Running(task) if task.id()==id)
        );
        owner.shutdown().await;
        assert!(owner.native_creations.try_lock().is_ok());
    }

    /// Actual owner retirement and blocking Native helper. Only the Native
    /// syscall is a bounded Unix-fd dependency; no real kernel/USB acceptance.
    #[tokio::test]
    async fn r5f9f_connection_retirement_waits_cancelled_native_creation() {
        if run_fd_case_isolated("r5f9f_connection_retirement_waits_cancelled_native_creation") {
            return;
        }
        use std::time::Duration;
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "native-retirement"),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = ConnectionOwner::new(
            &state,
            7,
            SleLinkInfo {
                lifetime: 1,
                handle: 7,
                ..Default::default()
            },
            0,
        );
        let lease = bind_lease();
        let admission = lease.clone().lock_owned().await;
        let (fd, peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = std::sync::mpsc::sync_channel(0);
        let waiter = tokio::spawn({
            let owner = owner.clone();
            async move {
                owner
                    .bind_native(admission, move || {
                        entered.send(()).unwrap();
                        released
                            .recv_timeout(Duration::from_secs(3))
                            .map_err(std::io::Error::other)?;
                        Ok(fd.into())
                    })
                    .await
            }
        });
        tokio::time::timeout(Duration::from_secs(1), started)
            .await
            .unwrap()
            .unwrap();
        waiter.abort();
        assert!(waiter.await.unwrap_err().is_cancelled());
        assert!(lease.try_lock().is_err(), "Native call is still in flight");
        let mut retirement = tokio::spawn({
            let owner = owner.clone();
            async move { owner.shutdown().await }
        });
        assert!(
            tokio::time::timeout(Duration::from_millis(100), &mut retirement)
                .await
                .is_err(),
            "Connection cleanup must not finish before actual Native creation returns"
        );
        assert!(owner.is_retiring());
        release.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(1), retirement)
            .await
            .unwrap()
            .unwrap();
        assert!(lease.try_lock().is_ok());
        assert_eq!(
            peer.send(&[1]).unwrap_err().kind(),
            std::io::ErrorKind::ConnectionRefused
        );
    }

    #[tokio::test]
    async fn r5f9f_retirement_waits_for_completed_but_unpolled_native_fd() {
        if run_fd_case_isolated("r5f9f_retirement_waits_for_completed_but_unpolled_native_fd") {
            return;
        }
        use std::time::Duration;
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(
                std::path::Path::new("/tmp"),
                "native-return-receipt",
            ),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = ConnectionOwner::new(
            &state,
            7,
            SleLinkInfo {
                lifetime: 1,
                handle: 7,
                ..Default::default()
            },
            0,
        );
        let lease = bind_lease();
        let admission = lease.clone().lock_owned().await;
        let (fd, peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = std::sync::mpsc::sync_channel(0);
        let creating = owner.bind_native(admission, move || {
            entered.send(()).unwrap();
            released
                .recv_timeout(Duration::from_secs(3))
                .map_err(std::io::Error::other)?;
            Ok(fd.into())
        });
        tokio::pin!(creating);
        tokio::select! {
            value = &mut creating => panic!("Native creation returned before its dependency: {value:?}"),
            _ = started => {},
        }
        release.send(()).unwrap();
        // Acquiring this actual guard witnesses the Native work has returned.
        // Do not poll its async fd receipt yet.
        drop(
            tokio::time::timeout(Duration::from_secs(1), lease.clone().lock_owned())
                .await
                .unwrap(),
        );
        let mut retirement = tokio::spawn({
            let owner = owner.clone();
            async move { owner.shutdown().await }
        });
        assert!(
            tokio::time::timeout(Duration::from_millis(100), &mut retirement)
                .await
                .is_err(),
            "a queued Native fd result is still owned work"
        );
        assert!(
            creating
                .await
                .unwrap_err()
                .to_string()
                .contains("native bind receipt")
        );
        tokio::time::timeout(Duration::from_secs(1), retirement)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            peer.send(&[1]).unwrap_err().kind(),
            std::io::ErrorKind::ConnectionRefused
        );
    }

    #[test]
    fn r5f9f_expired_service_work_cannot_begin_after_blocking_pool_queue() {
        use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
        use std::time::Duration;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .max_blocking_threads(1)
            .build()
            .unwrap();
        runtime.block_on(async {
            let (entered,started)=tokio::sync::oneshot::channel();
            let (release,released)=std::sync::mpsc::sync_channel(0);
            let blocker=tokio::task::spawn_blocking(move || {
                entered.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(3)).unwrap();
            });
            started.await.unwrap();
            let lease=bind_lease();
            let admission=lease.lock_owned().await;
            let creation=Arc::new(Mutex::new(())).lock_owned().await;
            let calls=Arc::new(AtomicUsize::new(0));let counted=calls.clone();
            let original=tokio::time::Instant::now()+Duration::from_millis(20);
            let work=bind_off_worker(Arc::new(AtomicBool::new(false)),creation,admission,Some(original),move||{
                counted.fetch_add(1,Ordering::SeqCst);
                std::fs::File::open("/dev/null").map(Into::into)
            });
            tokio::pin!(work);
            tokio::select! {
                value=&mut work=>panic!("queued work ran while the only blocking thread is held: {value:?}"),
                _=tokio::time::sleep_until(original)=>{},
            }
            release.send(()).unwrap();blocker.await.unwrap();
            assert!(matches!(work.await,Err(zbus::fdo::Error::Timeout(_))));
            assert_eq!(calls.load(Ordering::SeqCst),0);
        });
    }

    /// Actual production offload/guard and OS socket ownership. The blocked
    /// Native syscall is a finite dependency fixture, not a kernel/USB proof.
    #[tokio::test]
    async fn blocking_native_bind_keeps_runtime_live_and_closes_return_after_retirement() {
        if run_fd_case_isolated(
            "blocking_native_bind_keeps_runtime_live_and_closes_return_after_retirement",
        ) {
            return;
        }
        use std::sync::atomic::{AtomicBool, Ordering};
        use std::time::Duration;
        let lease = bind_lease();
        let retiring = Arc::new(AtomicBool::new(false));
        let admission = lease.clone().lock_owned().await;
        let (fd, peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = std::sync::mpsc::sync_channel(0);
        let runtime_thread = std::thread::current().id();
        let task = tokio::spawn(bind_off_worker(
            retiring.clone(),
            Arc::new(Mutex::new(())).lock_owned().await,
            admission,
            None,
            move || {
                entered.send(std::thread::current().id()).unwrap();
                released
                    .recv_timeout(Duration::from_secs(3))
                    .map_err(std::io::Error::other)?;
                Ok(fd.into())
            },
        ));
        // Default Tokio test is single-threaded: reaching this receipt while
        // the dependency waits establishes that the async worker is available.
        assert_ne!(
            tokio::time::timeout(Duration::from_secs(1), started)
                .await
                .unwrap()
                .unwrap(),
            runtime_thread
        );
        assert!(lease.try_lock().is_err());
        retiring.store(true, Ordering::Release);
        assert!(!task.is_finished());
        release.send(()).unwrap();
        assert!(
            task.await
                .unwrap()
                .unwrap_err()
                .to_string()
                .contains("retired during native bind")
        );
        assert!(lease.try_lock().is_ok());
        assert_eq!(
            peer.send(&[1]).unwrap_err().kind(),
            std::io::ErrorKind::ConnectionRefused
        );
    }

    #[tokio::test]
    async fn cancelled_native_bind_wait_retains_actual_admission_until_return() {
        if run_fd_case_isolated("cancelled_native_bind_wait_retains_actual_admission_until_return")
        {
            return;
        }
        use std::sync::atomic::AtomicBool;
        use std::time::Duration;
        let lease = bind_lease();
        let admission = lease.clone().lock_owned().await;
        let (fd, peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
        peer.set_nonblocking(true).unwrap();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = std::sync::mpsc::sync_channel(0);
        let task = tokio::spawn(bind_off_worker(
            Arc::new(AtomicBool::new(false)),
            Arc::new(Mutex::new(())).lock_owned().await,
            admission,
            None,
            move || {
                entered.send(()).unwrap();
                released
                    .recv_timeout(Duration::from_secs(3))
                    .map_err(std::io::Error::other)?;
                Ok(fd.into())
            },
        ));
        tokio::time::timeout(Duration::from_secs(1), started)
            .await
            .unwrap()
            .unwrap();
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        assert!(
            lease.try_lock().is_err(),
            "author cancellation cannot release actual in-flight admission"
        );
        release.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(1), async {
            loop {
                let closed = matches!(peer.send(&[1]), Err(e) if e.kind()==std::io::ErrorKind::ConnectionRefused);
                if closed && lease.try_lock().is_ok() { break; }
                tokio::task::yield_now().await;
            }
        }).await.unwrap();
    }

    #[tokio::test]
    async fn queued_retired_native_bind_does_not_run_and_errors_do_not_succeed() {
        use std::sync::atomic::AtomicBool;
        let lease = bind_lease();
        let admission = lease.clone().lock_owned().await;
        let denied = bind_off_worker(
            Arc::new(AtomicBool::new(true)),
            Arc::new(Mutex::new(())).lock_owned().await,
            admission,
            None,
            || panic!("a queued retired owner must not start Native work"),
        )
        .await
        .unwrap_err();
        assert!(denied.to_string().contains("owner retiring"));
        assert!(lease.try_lock().is_ok());
        for errno in [
            nix::libc::EOPNOTSUPP,
            nix::libc::EACCES,
            nix::libc::ETIMEDOUT,
        ] {
            let admission = lease.clone().lock_owned().await;
            let error = bind_off_worker(
                Arc::new(AtomicBool::new(false)),
                Arc::new(Mutex::new(())).lock_owned().await,
                admission,
                None,
                move || Err(std::io::Error::from_raw_os_error(errno)),
            )
            .await
            .unwrap_err();
            assert_eq!(
                matches!(error, zbus::fdo::Error::NotSupported(_)),
                errno == nix::libc::EOPNOTSUPP
            );
            assert_eq!(
                matches!(error, zbus::fdo::Error::AccessDenied(_)),
                errno == nix::libc::EACCES
            );
            if errno == nix::libc::EACCES {
                assert_eq!(
                    public_native_error(error),
                    zbus::fdo::Error::Failed(
                        "native channel bind: Permission denied (os error 13)".into()
                    )
                );
            }
            assert!(lease.try_lock().is_ok());
        }
    }

    #[tokio::test]
    async fn definite_refusal_keeps_public_contract_and_joins_before_security_rearm() {
        // Actual production slot/offload/guards, with a bounded failing Native
        // dependency. No successful kernel, mechanism, fd or Engine is supplied.
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "refused-init"),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = ConnectionOwner::new(&state, 7, SleLinkInfo::default(), 2);
        let lease = bind_lease();
        let admission = lease.clone().lock_owned().await;
        let creation = owner.native_creations.clone().lock_owned().await;
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = std::sync::mpsc::sync_channel(0);
        let retiring = owner.ssap_retiring.clone();
        owner
            .ssap_initialization
            .lock()
            .await
            .begin(move || async move {
                bind_off_worker(retiring, creation, admission, None, move || {
                    entered.send(()).unwrap();
                    released
                        .recv_timeout(std::time::Duration::from_secs(3))
                        .unwrap();
                    Err(std::io::Error::from_raw_os_error(nix::libc::EACCES))
                })
                .await
                .map(|_| panic!("fixture never returns an fd"))
            });
        started.await.unwrap();
        assert!(
            tokio::time::timeout(
                std::time::Duration::from_millis(20),
                owner.rearm_refused_initialization()
            )
            .await
            .is_err()
        );
        assert!(matches!(
            *owner.ssap_initialization.lock().await,
            Initialization::Running(_)
        ));
        assert!(lease.try_lock().is_err());
        assert!(owner.native_creations.try_lock().is_err());
        release.send(()).unwrap();
        assert_eq!(
            owner.start_ssap().await.unwrap_err(),
            zbus::fdo::Error::Failed("native channel bind: Permission denied (os error 13)".into())
        );
        assert!(matches!(
            *owner.ssap_initialization.lock().await,
            Initialization::Completed(Err(zbus::fdo::Error::AccessDenied(_)))
        ));
        assert!(lease.try_lock().is_ok());
        assert!(owner.native_creations.try_lock().is_ok());
        owner.rearm_refused_initialization().await.unwrap();
        assert!(matches!(
            *owner.ssap_initialization.lock().await,
            Initialization::NotStarted
        ));
        assert!(owner.ssap.lock().await.is_none()); // No grant/readiness fabricated.
    }

    #[tokio::test]
    async fn security_wakeup_does_not_rearm_unknown_timeout_started_or_retiring_owner() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "terminal-init"),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = ConnectionOwner::new(&state, 7, SleLinkInfo::default(), 2);
        // Explicit terminal fixtures exercise the actual state transition; a
        // successful initializer marker is not a successful Native backend.
        for result in [
            Err(zbus::fdo::Error::Failed(
                "native channel bind: Permission denied (os error 13)".into(),
            )),
            Err(zbus::fdo::Error::Timeout("unknown physical return".into())),
            Err(zbus::fdo::Error::NotSupported(
                "same-lifetime rebinding".into(),
            )),
            Ok(()),
        ] {
            *owner.ssap_initialization.lock().await = Initialization::Completed(result.clone());
            owner.rearm_refused_initialization().await.unwrap();
            match &*owner.ssap_initialization.lock().await {
                Initialization::Completed(actual) => assert_eq!(actual, &result),
                _ => panic!("only a typed completed no-fd refusal may be rearmed"),
            }
        }
        *owner.ssap_initialization.lock().await = Initialization::Completed(Err(
            zbus::fdo::Error::AccessDenied("definite no-fd refusal".into()),
        ));
        owner.retire();
        assert!(owner.rearm_refused_initialization().await.is_err());
        assert!(matches!(
            *owner.ssap_initialization.lock().await,
            Initialization::Completed(Err(zbus::fdo::Error::AccessDenied(_)))
        ));
    }

    #[tokio::test]
    async fn original_deadline_precedes_ready_inner_success_or_error() {
        let fresh =
            slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(1)).unwrap();
        assert!(matches!(
            finish_scoped_ssap_call::<()>(
                fresh,
                Err(zbus::fdo::Error::Failed("before deadline".into()))
            ),
            Err(zbus::fdo::Error::Failed(_))
        ));
        assert!(matches!(
            finish_scoped_ssap_call::<()>(
                fresh,
                Err(zbus::fdo::Error::NotSupported("capability denial".into()))
            ),
            Err(zbus::fdo::Error::NotSupported(_))
        ));
        let expired =
            slk_channel::deadline::Deadline::after(std::time::Duration::from_millis(5)).unwrap();
        tokio::time::sleep_until(expired.instant().into()).await;
        for result in [
            Ok(()),
            Err(zbus::fdo::Error::NotSupported("capability denial".into())),
            Err(zbus::fdo::Error::Failed("ready inner failure".into())),
        ] {
            assert!(matches!(
                finish_scoped_ssap_call(expired, result),
                Err(zbus::fdo::Error::Timeout(_))
            ));
        }
    }
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
    async fn controller_owner_has_no_strong_context_cycle_or_unknown_start_admission() {
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "owner-weak-context"),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = {
            let mut st = state.lock().await;
            st.controller.generation = 7;
            st.controller.profile = 1;
            let mut table = slk_protocol::SleLinkSnapshot {
                generation: 7,
                profile: 1,
                version: 1,
                flags: 1,
                count: 1,
                revision: 1,
                ..Default::default()
            };
            table.links[0] = SleLinkInfo {
                lifetime: 1,
                handle: 7,
                address: [1; 6],
                ..Default::default()
            };
            st.apply_native_links(table, 0).unwrap();
            let owner = st.connection_publications(&state).pending.remove(0).owner;
            st.invalidate_native_connections();
            assert!(st.connection_publications(&state).pending.is_empty());
            assert!(matches!(
                *owner.ssap_initialization.try_lock().unwrap(),
                Initialization::NotStarted
            ));
            owner
        };
        let weak = Arc::downgrade(&state);
        drop(state);
        assert!(
            weak.upgrade().is_none(),
            "resource owner must not keep its controller State alive forever"
        );
        assert_eq!(owner.observation().await, (false, false));
        assert!(owner.context().is_err());
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn cancelled_engine_stop_wait_keeps_original_task_and_real_fd_for_the_next_join() {
        if run_fd_case_isolated(
            "cancelled_engine_stop_wait_keeps_original_task_and_real_fd_for_the_next_join",
        ) {
            return;
        }
        use std::os::fd::OwnedFd;
        let state = Arc::new(Mutex::new(crate::state::AdapterState::new(
            slk_native::Adapter::open("/dev/null").unwrap(),
            crate::config::DaemonConfig::default(),
            crate::bonding::BondingStore::new(std::path::Path::new("/tmp"), "stop-join-owner"),
            crate::profile::ProfileRegistry::new(),
        )));
        let owner = ConnectionOwner::new(&state, 7, SleLinkInfo::default(), 0);
        let (fd, peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
        let fd: OwnedFd = fd.into();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = tokio::sync::oneshot::channel();
        let (closed, closed_rx) = tokio::sync::oneshot::channel();
        let task = tokio::spawn(async move {
            entered.send(()).unwrap();
            released.await.unwrap();
            drop(fd);
            closed.send(()).unwrap();
        });
        started.await.unwrap();
        *owner.ssap.lock().await = Some(crate::ssap_engine::Engine::task_fixture(task));
        let mut first = tokio::spawn({
            let owner = owner.clone();
            async move { owner.shutdown().await }
        });
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(100), &mut first)
                .await
                .is_err()
        );
        first.abort();
        assert!(first.await.unwrap_err().is_cancelled());
        assert!(
            owner.ssap.lock().await.is_some(),
            "cancel must not take the original Engine/task out of its owner"
        );
        assert!(!release.is_closed());
        assert_eq!(peer.send(&[1]).unwrap(), 1);
        let mut second = tokio::spawn({
            let owner = owner.clone();
            async move { owner.shutdown().await }
        });
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(100), &mut second)
                .await
                .is_err()
        );
        // Stop of an independent owner has no shared wait/lock with this task.
        let peer_owner = ConnectionOwner::new(
            &state,
            7,
            SleLinkInfo {
                lifetime: 2,
                ..Default::default()
            },
            0,
        );
        tokio::time::timeout(std::time::Duration::from_millis(100), peer_owner.shutdown())
            .await
            .unwrap();
        release.send(()).unwrap();
        second.await.unwrap();
        closed_rx.await.unwrap();
        assert!(owner.ssap.lock().await.is_none());
        // Observe the original socket peer, never a reusable process fd number.
        assert_eq!(
            peer.send(&[2]).unwrap_err().kind(),
            std::io::ErrorKind::ConnectionRefused
        );
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
                initialize_once(&slot, &retiring, move || async move {
                    called.fetch_add(1, Ordering::SeqCst);
                    entered.send(()).unwrap();
                    released.await.unwrap();
                    Err(zbus::fdo::Error::Failed(
                        "finite dependency failure before publication".into(),
                    ))
                })
                .await
            }
        });
        started.await.unwrap();
        first.abort();
        assert!(first.await.unwrap_err().is_cancelled());
        assert!(matches!(*slot.lock().await, Initialization::Running(_)));
        release.send(()).unwrap();
        let constructed = Arc::new(AtomicUsize::new(0));
        let factory_calls = constructed.clone();
        let result = initialize_once(&slot, &retiring, move || {
            factory_calls.fetch_add(1, Ordering::SeqCst);
            async { panic!("must not retry/duplicate a cancelled wait's owned initializer") }
        })
        .await;
        assert_eq!(
            result.unwrap_err(),
            zbus::fdo::Error::Failed("finite dependency failure before publication".into())
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(constructed.load(Ordering::SeqCst), 0);
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
        assert!(Arc::ptr_eq(&iface.owner, &starter.owner));
        assert!(std::ptr::eq(
            &iface.remote_services,
            &starter.remote_services
        ));
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, released) = tokio::sync::oneshot::channel();
        let start = tokio::spawn(async move {
            initialize_once(
                &starter.ssap_initialization,
                &starter.ssap_retiring,
                move || async move {
                    entered.send(()).unwrap();
                    released.await.unwrap();
                    Err(zbus::fdo::Error::Failed(
                        "failure after held dependency returned".into(),
                    ))
                },
            )
            .await
        });
        started.await.unwrap();
        let stop = tokio::spawn({
            let owner = iface.clone();
            async move { owner.shutdown().await }
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
        assert!(
            start
                .await
                .unwrap()
                .unwrap_err()
                .to_string()
                .contains("retiring")
        );
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
            ("ReadSsapDescription", vec!["q", "u", "(ttttt)"], vec!["ay"]),
            (
                "WriteSsapValue",
                vec!["q", "ay", "u", "(ttttt)"],
                vec!["ay"],
            ),
            ("WriteSsapCommand", vec!["q", "ay", "u", "(ttttt)"], vec![]),
            (
                "CallSsapMethod",
                vec!["q", "ay", "u", "(ttttt)"],
                vec!["ay"],
            ),
            (
                "CallSsapMethodCommand",
                vec!["q", "ay", "u", "(ttttt)"],
                vec![],
            ),
            (
                "DiscoverSsap",
                vec!["ay", "y"],
                vec!["(a(yqqayuayy)a(ayay))"],
            ),
            ("GetCachedSsap", vec![], vec!["a(yqqayuayy)"]),
            (
                "ReceiveSsapUpdate",
                vec!["aq", "y", "(ttttt)"],
                vec!["(bay)"],
            ),
            (
                "SubscribeSsapUpdates",
                vec!["aq", "y", "u", "(ttttt)"],
                vec!["(uqttqtttaqyyq)"],
            ),
            (
                "ReadSsapUpdates",
                vec!["t", "b", "(ttttt)"],
                vec!["((uqttqtttaqyyq)ttttuya(ttubay))"],
            ),
            (
                "RenewSsapSubscription",
                vec!["t", "u", "(ttttt)"],
                vec!["(uqttqtttaqyyq)"],
            ),
            (
                "CloseSsapSubscription",
                vec!["t", "(ttttt)"],
                vec!["((uqttqtttaqyyq)ttttuya(ttubay))"],
            ),
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
                    iface.prime_ssap_on_publication(),
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
                .unwrap()
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
