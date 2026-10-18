//! Application broker requests. Business datagrams never traverse D-Bus here.
//! This slice exposes only existing controller/connection/channel operations.
use slk_contract::{self as contract, ConnectionInfo, ControllerId, DynamicRequest};
use std::sync::Arc;
use tokio::sync::watch;
use zbus::export::ordered_stream::OrderedStreamExt;
use zbus::{Connection, Proxy};

#[derive(Debug, thiserror::Error)]
pub enum ApplicationError {
    #[error("broker: {0}")]
    Bus(#[from] zbus::Error),
    #[error("invalid application request: {0}")]
    Invalid(&'static str),
    #[error("immutable identity unavailable or changed: {0}")]
    Identity(&'static str),
    #[error("channel: {0}")]
    Io(#[from] std::io::Error),
}
type Result<T> = std::result::Result<T, ApplicationError>;

pub(crate) async fn bounded<T>(
    client: &Client,
    deadline: slk_channel::deadline::Deadline,
    work: impl std::future::Future<Output = Result<T>>,
) -> Result<T> {
    deadline.remaining()?;
    if client.daemon_lost() {
        return Err(ApplicationError::Identity("daemon owner replaced"));
    }
    let mut lost = client.owner_loss();
    tokio::select! {
        biased;
        _ = lost.changed() => Err(ApplicationError::Identity("daemon owner replaced")),
        result = tokio::time::timeout_at(deadline.instant().into(), work) => {
            result.map_err(|_| std::io::Error::from_raw_os_error(nix::libc::ETIMEDOUT))?
        },
    }
}

/// Holds one D-Bus caller identity and pins the unique daemon owner. It never
/// silently follows a replacement daemon or opens the Native control device.
#[derive(Clone)]
pub struct Client {
    bus: Connection,
    scope: Arc<DaemonScope>,
}

/// Local observation scope only. No controller lease, protocol state or debt.
struct DaemonScope {
    owner: String,
    lost: watch::Receiver<bool>,
    terminal: watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for DaemonScope {
    fn drop(&mut self) {
        // Callback receivers must see terminal immediately, even if the task
        // has not been polled or its asynchronous destruction is delayed.
        self.terminal.send_replace(true);
        self.task.abort();
    }
}
struct LossOnExit(watch::Sender<bool>);
impl Drop for LossOnExit {
    fn drop(&mut self) {
        self.0.send_replace(true);
    }
}
impl Client {
    pub async fn open_system() -> Result<Self> {
        Self::from_connection(Connection::system().await?).await
    }
    /// An existing caller connection, useful also for explicit private-bus tests.
    /// Resolves the real service owner; there is no local backend or fallback.
    pub async fn from_connection(bus: Connection) -> Result<Self> {
        let manager = zbus::fdo::DBusProxy::new(&bus).await?;
        // Install the subscription before lookup. A release/reacquire by the
        // same unique process is still a new ownership scope, never revival.
        let mut changes = manager
            .receive_name_owner_changed_with_args(&[(0, contract::SERVICE)])
            .await?;
        let owner = manager
            .get_name_owner(contract::SERVICE.try_into().expect("constant service name"))
            .await
            .map_err(|e| ApplicationError::Bus(e.into()))?
            .to_string();
        let (terminal, lost) = watch::channel(false);
        let on_exit = LossOnExit(terminal.clone());
        let task = tokio::spawn(async move {
            let _ = changes.next().await;
            // Includes a closed/error stream, abort and task panic. The task
            // never captures the Scope Arc, so final caller release has no cycle.
            drop(on_exit);
        });
        let client = Self {
            bus,
            scope: Arc::new(DaemonScope {
                owner,
                lost,
                terminal,
                task,
            }),
        };
        client.check_owner().await?;
        Ok(client)
    }
    pub fn daemon_owner(&self) -> &str {
        &self.scope.owner
    }
    /// One bounded terminal notification shared by clones and derived views.
    /// This is not a controller event stream or an authorization epoch.
    pub fn owner_loss(&self) -> watch::Receiver<bool> {
        self.scope.lost.clone()
    }
    pub fn daemon_lost(&self) -> bool {
        *self.scope.lost.borrow()
    }
    pub(crate) async fn check_owner(&self) -> Result<()> {
        if self.daemon_lost() {
            return Err(ApplicationError::Identity("daemon owner replaced"));
        }
        let bus = zbus::fdo::DBusProxy::new(&self.bus).await?;
        let current = bus
            .get_name_owner(contract::SERVICE.try_into().expect("constant service name"))
            .await
            .map_err(|e| ApplicationError::Bus(e.into()))?;
        if current.as_str() != self.scope.owner || self.daemon_lost() {
            return Err(ApplicationError::Identity("daemon owner replaced"));
        }
        Ok(())
    }
    pub(crate) async fn proxy(&self, path: &str, interface: &'static str) -> Result<Proxy<'_>> {
        self.check_owner().await?;
        self.original_proxy(path, interface).await
    }
    // Only typed withdrawal operations may use this after scope loss. Never
    // follow the well-known name or admit new work through this private helper.
    pub(crate) async fn original_proxy(
        &self,
        path: &str,
        interface: &'static str,
    ) -> Result<Proxy<'_>> {
        Ok(zbus::proxy::Builder::<Proxy<'_>>::new(&self.bus)
            .destination(self.scope.owner.clone())?
            .path(path.to_owned())?
            .interface(interface)?
            .cache_properties(zbus::proxy::CacheProperties::No)
            .build()
            .await?)
    }
    async fn registration_paths(&self) -> Result<Vec<String>> {
        let manager = self
            .proxy(contract::MANAGER_PATH, contract::MANAGER)
            .await?;
        let paths = manager.call(contract::LIST_ADAPTERS, &()).await?;
        self.check_owner().await?;
        Ok(paths)
    }
    pub(crate) async fn check_generation(&self, id: ControllerId) -> Result<()> {
        let current: u64 = self
            .proxy(&id.path(), contract::ADAPTER)
            .await?
            .get_property("Generation")
            .await?;
        if current != id.generation {
            return Err(ApplicationError::Identity("controller generation"));
        }
        Ok(())
    }
    /// Registry membership observation, not Ready or a still-live controller.
    /// Unrelated controller properties are never a selected operation's gate.
    pub async fn controllers(&self) -> Result<Vec<ControllerId>> {
        let paths = self.registration_paths().await?;
        let mut controllers = Vec::with_capacity(paths.len());
        for path in paths {
            let id = ControllerId::from_path(&path)
                .ok_or(ApplicationError::Identity("noncanonical controller path"))?;
            if controllers.contains(&id) {
                return Err(ApplicationError::Identity("duplicate controller"));
            }
            controllers.push(id);
        }
        Ok(controllers)
    }
    /// A registered controller view; not a management lease or Ready guarantee.
    pub async fn controller(&self, path: &str) -> Result<crate::controller::Controller> {
        let id =
            ControllerId::from_path(path).ok_or(ApplicationError::Invalid("controller path"))?;
        if !self.registration_paths().await?.iter().any(|p| p == path) {
            return Err(ApplicationError::Identity("registration removed"));
        }
        self.check_generation(id).await?;
        Ok(crate::controller::Controller::new(self.clone(), id))
    }
    pub async fn daemon_identity(&self) -> Result<(String, u32, u32)> {
        let _ = self
            .proxy(contract::MANAGER_PATH, contract::MANAGER)
            .await?;
        let bus = zbus::fdo::DBusProxy::new(&self.bus).await?;
        let owner: zbus::names::BusName<'_> = self
            .scope
            .owner
            .as_str()
            .try_into()
            .map_err(|_| ApplicationError::Identity("invalid daemon owner"))?;
        let pid = bus
            .get_connection_unix_process_id(owner.clone())
            .await
            .map_err(|e| ApplicationError::Bus(e.into()))?;
        let uid = bus
            .get_connection_unix_user(owner)
            .await
            .map_err(|e| ApplicationError::Bus(e.into()))?;
        let _ = self
            .proxy(contract::MANAGER_PATH, contract::MANAGER)
            .await?;
        Ok((self.scope.owner.clone(), pid, uid))
    }
    pub async fn peer(&self, path: &str) -> Result<crate::peer::Peer> {
        let id = contract::PeerId::from_path(path)
            .ok_or(ApplicationError::Invalid("typed Peer path"))?;
        let _ = self.controller(&id.controller.path()).await?;
        Ok(crate::peer::Peer {
            client: self.clone(),
            id,
        })
    }
    pub async fn peer_info(&self, controller: &str, path: &str) -> Result<contract::PeerInfo> {
        let view = self.controller(controller).await?;
        if !contract::PeerId::from_path(path).is_some_and(|id| id.controller == view.id()) {
            return Err(ApplicationError::Identity("foreign controller peer"));
        }
        let value: contract::PeerInfo = self
            .proxy(path, contract::controller::PEER)
            .await?
            .call(contract::GET_INFO, &())
            .await?;
        if !contract::matches_peer(view.id(), path, &value) {
            return Err(ApplicationError::Identity("typed peer identity"));
        }
        self.check_generation(view.id()).await?;
        Ok(value)
    }
    /// Core observations include early setup/faults without requiring Adapter.
    pub async fn registrations(&self) -> Result<Vec<String>> {
        let paths: Vec<String> = self
            .proxy(contract::MANAGER_PATH, contract::MANAGER)
            .await?
            .call(contract::controller::LIST_REGISTRATIONS, &())
            .await?;
        let mut unique = std::collections::HashSet::new();
        if paths
            .iter()
            .any(|p| ControllerId::from_path(p).is_none() || !unique.insert(p))
        {
            return Err(ApplicationError::Identity(
                "noncanonical/duplicate registration",
            ));
        }
        Ok(paths)
    }
    pub async fn registration(&self, path: &str) -> Result<slk_protocol::SleRegistrationSnapshot> {
        let id =
            ControllerId::from_path(path).ok_or(ApplicationError::Invalid("registration path"))?;
        let (generation,version,state,profile,phase,error,index,bus): slk_protocol::RegistrationSnapshotRecord = self.proxy(path, contract::controller::REGISTRATION).await?
            .call(contract::controller::REGISTRATION_SNAPSHOT, &()).await?;
        let value = slk_protocol::SleRegistrationSnapshot {
            generation,
            version,
            state,
            profile,
            phase,
            error,
            dev_index: index,
            bus,
            ..Default::default()
        };
        if !value.valid_for(id.index, id.generation)
            || generation != id.generation
            || index != id.index
        {
            return Err(ApplicationError::Identity("registration snapshot"));
        }
        // Recheck ownership without requiring a Ready Adapter to exist.
        let _ = self.proxy(path, contract::controller::REGISTRATION).await?;
        Ok(value)
    }
    pub async fn connection(&self, controller: &str, path: &str) -> Result<ApplicationConnection> {
        let id = ControllerId::from_path(controller)
            .ok_or(ApplicationError::Invalid("controller path"))?;
        if !self
            .registration_paths()
            .await?
            .iter()
            .any(|p| p == controller)
        {
            return Err(ApplicationError::Identity("registration removed"));
        }
        self.check_generation(id).await?;
        if !path.starts_with(&format!("{controller}/peer_t")) {
            return Err(ApplicationError::Identity("foreign controller"));
        }
        let proxy = self.proxy(path, contract::CONNECTION).await?;
        let info: ConnectionInfo = proxy.call(contract::GET_INFO, &()).await?;
        if !contract::matches_connection(id, path, &info) {
            return Err(ApplicationError::Identity(
                "connection path/generation/lifetime",
            ));
        }
        Ok(ApplicationConnection {
            client: self.clone(),
            controller: id,
            path: path.to_owned(),
            identity: info,
        })
    }
}

/// Pinned physical lifetime observation, not ownership of the physical link.
/// Dropping this object does not disconnect or revoke another application's fd.
pub struct ApplicationConnection {
    pub(crate) client: Client,
    pub(crate) controller: ControllerId,
    pub(crate) path: String,
    pub(crate) identity: ConnectionInfo,
}
impl ApplicationConnection {
    /// A client view of the daemon's existing lifetime-scoped SSAP actor.
    /// Dropping this view does not disconnect the physical connection.
    pub fn ssap(&self) -> crate::ssap::RemoteSsap<'_> {
        crate::ssap::RemoteSsap::new(self)
    }
    /// Existing read-only Session mechanism observation; never drains debt.
    pub async fn transport_status(&self) -> Result<contract::TransportInfo> {
        self.live().await?;
        let value: contract::TransportInfo = self
            .client
            .proxy(&self.path, contract::CONNECTION)
            .await?
            .call(contract::TRANSPORT_STATUS, &())
            .await?;
        let current = self.info().await?;
        if value.0 != self.controller.index
            || (value.1, value.2, value.3) != (current.0, current.1, current.2)
            || !current.6
            || !current.7
        {
            return Err(ApplicationError::Identity("transport observation lifetime"));
        }
        Ok(value)
    }
    pub fn path(&self) -> &str {
        &self.path
    }
    pub async fn info(&self) -> Result<ConnectionInfo> {
        self.client.check_generation(self.controller).await?;
        let info: ConnectionInfo = self
            .client
            .proxy(&self.path, contract::CONNECTION)
            .await?
            .call(contract::GET_INFO, &())
            .await?;
        if !contract::matches_connection(self.controller, &self.path, &info)
            || (info.0, info.1, info.2, info.3, info.4, &info.5)
                != (
                    self.identity.0,
                    self.identity.1,
                    self.identity.2,
                    self.identity.3,
                    self.identity.4,
                    &self.identity.5,
                )
        {
            return Err(ApplicationError::Identity("old connection object"));
        }
        Ok(info)
    }
    pub(crate) async fn live(&self) -> Result<()> {
        let info = self.info().await?;
        if !info.6 || !info.7 {
            return Err(ApplicationError::Identity("connection unknown/down"));
        }
        Ok(())
    }
    /// Requests only the caller's scoped fd. Broker/kernel errors propagate;
    /// no management lease, weaker security fallback or software-success fd.
    pub async fn open_channel(
        &self,
        directions: u32,
        minimum: u32,
    ) -> Result<slk_channel::Channel> {
        if directions == 0 || directions & !3 != 0 || minimum > 2 {
            return Err(ApplicationError::Invalid("channel directions/security"));
        }
        self.live().await?;
        let proxy = self.client.proxy(&self.path, contract::CONNECTION).await?;
        let fd: zbus::zvariant::OwnedFd = if directions == 3 && minimum == 0 {
            proxy.call(contract::OPEN_CHANNEL, &()).await?
        } else {
            proxy
                .call(contract::OPEN_CHANNEL_SCOPED, &(directions, minimum))
                .await?
        };
        Ok(slk_channel::Channel::from_owned(fd.into())?)
    }
    /// Existing basic dynamic staging only. Negotiation/readiness and every
    /// send remain kernel obligations; a returned fd is not successful traffic.
    pub async fn prepare_dynamic_channel(
        &self,
        request: DynamicRequest,
    ) -> Result<slk_channel::Channel> {
        self.live().await?;
        let fd: zbus::zvariant::OwnedFd = self
            .client
            .proxy(&self.path, contract::CONNECTION)
            .await?
            .call(contract::PREPARE_DYNAMIC_CHANNEL, &(request,))
            .await?;
        Ok(slk_channel::Channel::from_owned(fd.into())?)
    }
}
