//! One immutable registration/type/address/lifetime identity per physical link.
//! Properties are canonical observation, never an author operation result.
use crate::state::SharedState;
use slk_protocol::SleLinkInfo;
use zbus::interface;

pub(crate) type Info = (u64, u64, u16, u8, u8, String, bool, bool);
pub(crate) type Objects = (u64, u64, u64, bool, Vec<(String, u64, u16, u8, u8, String)>);

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
}
impl ConnectionIface {
    pub(crate) fn new(state: SharedState, generation: u64, reference: SleLinkInfo) -> Self {
        Self {
            state,
            generation,
            reference,
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
    async fn open_authorized_channel(
        &self,
        directions: u32,
        security: u32,
    ) -> zbus::fdo::Result<zbus::zvariant::OwnedFd> {
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
        let fd = crate::channel::open(
            index,
            self.generation,
            self.reference.lifetime,
            self.reference.handle,
            token,
            directions,
            security,
        )
        .map_err(|error| {
            if error.raw_os_error() == Some(nix::libc::EOPNOTSUPP) {
                zbus::fdo::Error::NotSupported(
                    "channel mode or same-lifetime rebinding is not supported".into(),
                )
            } else {
                zbus::fdo::Error::Failed(format!("native channel bind: {error}"))
            }
        })?;
        Ok(fd.into())
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
