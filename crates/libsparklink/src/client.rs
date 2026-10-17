//! Application broker requests. Business datagrams never traverse D-Bus here.
//! This slice exposes only existing controller/connection/channel operations.
use slk_contract::{self as contract, ConnectionInfo, ControllerId, DynamicRequest};
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

/// Holds one D-Bus caller identity and pins the unique daemon owner. It never
/// silently follows a replacement daemon or opens the Native control device.
#[derive(Clone)]
pub struct Client {
    bus: Connection,
    owner: String,
}
impl Client {
    pub async fn open_system() -> Result<Self> {
        Self::from_connection(Connection::system().await?).await
    }
    /// An existing caller connection, useful also for explicit private-bus tests.
    /// Resolves the real service owner; there is no local backend or fallback.
    pub async fn from_connection(bus: Connection) -> Result<Self> {
        let manager = zbus::fdo::DBusProxy::new(&bus).await?;
        let owner = manager
            .get_name_owner(contract::SERVICE.try_into().expect("constant service name"))
            .await
            .map_err(|e| ApplicationError::Bus(e.into()))?
            .to_string();
        Ok(Self { bus, owner })
    }
    pub fn daemon_owner(&self) -> &str {
        &self.owner
    }
    async fn proxy(&self, path: &str, interface: &'static str) -> Result<Proxy<'_>> {
        let bus = zbus::fdo::DBusProxy::new(&self.bus).await?;
        let current = bus
            .get_name_owner(contract::SERVICE.try_into().expect("constant service name"))
            .await
            .map_err(|e| ApplicationError::Bus(e.into()))?;
        if current.as_str() != self.owner {
            return Err(ApplicationError::Identity("daemon owner replaced"));
        }
        Ok(zbus::proxy::Builder::<Proxy<'_>>::new(&self.bus)
            .destination(self.owner.clone())?
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
        Ok(manager.call(contract::LIST_ADAPTERS, &()).await?)
    }
    async fn check_generation(&self, id: ControllerId) -> Result<()> {
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
    client: Client,
    controller: ControllerId,
    path: String,
    identity: ConnectionInfo,
}
impl ApplicationConnection {
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
            || (info.0, info.1, info.2, info.4, &info.5)
                != (
                    self.identity.0,
                    self.identity.1,
                    self.identity.2,
                    self.identity.4,
                    &self.identity.5,
                )
        {
            return Err(ApplicationError::Identity("old connection object"));
        }
        Ok(info)
    }
    async fn live(&self) -> Result<()> {
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
