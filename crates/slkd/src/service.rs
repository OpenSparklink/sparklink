use zbus::interface;

use crate::state::SharedState;

/// Explicit local database APIs; legacy facade stays unsupported and no kernel staging.
pub struct SsapManagerIface {
    state: SharedState,
}

impl SsapManagerIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.ServiceManager")]
impl SsapManagerIface {
    /// Adapter-local only; no remote service-discovery/publication receipt.
    async fn register_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<crate::ssap_database::PropertyDefinition>,
    ) -> zbus::fdo::Result<(u16, u16, Vec<u16>)> {
        for (_, ops, access, _) in &properties {
            let policy = slk_protocol::ssap::access::SsapAccess::from_bits(*access)
                .map_err(|e| zbus::fdo::Error::InvalidArgs(e.into()))?;
            if policy.needs_local_authorization() {
                return Err(zbus::fdo::Error::NotSupported(
                    "SSAP local authorization not connected".into(),
                ));
            }
            let validated = slk_protocol::SsapOperations::from_bits(*ops)
                .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
            if validated.bits() & !5 != 0 {
                return Err(zbus::fdo::Error::NotSupported(
                    "WRITE_NO_RSP/descriptor/notify/indicate permissions not connected".into(),
                ));
            }
        }
        let st = self.state.lock().await;
        if !st.present {
            return Err(zbus::fdo::Error::Failed("adapter retired".into()));
        }
        let lease = st
            .native_lease
            .clone()
            .ok_or_else(|| zbus::fdo::Error::NotSupported("Native management required".into()))?;
        let database = st.ssap_database.clone();
        drop(st);
        let lease = lease.lock().await;
        if !lease.accepting || lease.token.is_none() {
            return Err(zbus::fdo::Error::Failed("management revoked".into()));
        }
        database
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?
            .register(uuid, properties)
            .map_err(zbus::fdo::Error::InvalidArgs)
    }
    async fn list_local_services(
        &self,
    ) -> zbus::fdo::Result<Vec<crate::ssap_database::LocalService>> {
        let st = self.state.lock().await;
        if !st.present {
            return Err(zbus::fdo::Error::Failed("adapter retired".into()));
        }
        st.ssap_database
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))
            .map(|d| d.list())
    }
    async fn remove_local_service(&self, start: u16) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        if !st.present {
            return Err(zbus::fdo::Error::Failed("adapter retired".into()));
        }
        st.ssap_database
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?
            .remove(start)
            .map_err(zbus::fdo::Error::InvalidArgs)
    }
    async fn read_local_value(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let st = self.state.lock().await;
        if !st.present {
            return Err(zbus::fdo::Error::Failed("adapter retired".into()));
        }
        st.ssap_database
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?
            .local_read(handle)
            .map_err(zbus::fdo::Error::InvalidArgs)
    }
    /// Get SSAP summary (service and property counts, MTU)
    async fn get_info(&self) -> zbus::fdo::Result<SsapInfo> {
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Reject registration until the unique userspace Engine is connected.
    async fn register_services(&self) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Unsupported until a userspace service database exists
    async fn add_service(&self, uuid16: u16, primary: bool) -> zbus::fdo::Result<u16> {
        let _ = (uuid16, primary);
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Add a property (characteristic) to a service
    /// Historical permissions: READ=01, WRITE_NO_RSP=02, WRITE_WITH_RSP=04,
    /// NOTIFY=08, INDICATE=10, BROADCAST=20; reserved bits are rejected.
    async fn add_property(&self, uuid16: u16, ops: u8, value: Vec<u8>) -> zbus::fdo::Result<u16> {
        slk_protocol::SsapOperations::from_bits(u32::from(ops))
            .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        if value.len() > 248 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "legacy property input exceeds 248 bytes".into(),
            ));
        }
        let _ = (uuid16, ops, value);
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Remove a service by its start handle
    async fn remove_service(&self, start_handle: u16) -> zbus::fdo::Result<()> {
        let _ = start_handle;
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// List local services
    async fn list_services(&self) -> zbus::fdo::Result<Vec<ServiceEntry>> {
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Read a local property value
    async fn read_property(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let _ = handle;
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Write a local property value
    async fn write_property(&self, handle: u16, value: Vec<u8>) -> zbus::fdo::Result<()> {
        if value.len() > 252 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "legacy service input exceeds 252 bytes; long write is unsupported".into(),
            ));
        }
        let _ = (handle, value);
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Unsupported notification, never reports local enqueue as delivery
    async fn notify(&self, handle: u16) -> zbus::fdo::Result<()> {
        let _ = handle;
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Dequeue a pending notification
    async fn dequeue_notification(&self) -> zbus::fdo::Result<NotificationData> {
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }
}

/// D-Bus interface for remote service operations on a specific connection
pub struct RemoteServiceIface {}

impl RemoteServiceIface {
    pub fn new(_state: SharedState, _conn_handle: u16) -> Self {
        Self {}
    }
}

#[interface(name = "org.sparklink.RemoteService")]
impl RemoteServiceIface {
    /// Exchange SSAP info with the remote peer (initiate service discovery handshake)
    async fn exchange_info(&self) -> zbus::fdo::Result<()> {
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Discover services on the remote peer
    async fn discover(&self, start_handle: u16, end_handle: u16) -> zbus::fdo::Result<u16> {
        let _ = (start_handle, end_handle);
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Read a property from the remote peer
    async fn read(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let _ = handle;
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Write a property on the remote peer
    async fn write(&self, handle: u16, value: Vec<u8>) -> zbus::fdo::Result<()> {
        if value.len() > 248 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "legacy service input exceeds 248 bytes; long write is unsupported".into(),
            ));
        }
        let _ = (handle, value);
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Receive a remote notification/indication event
    async fn receive_event(&self) -> zbus::fdo::Result<NotificationData> {
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Invoke a method on a remote peer's SSAP service
    async fn call_method(&self, handle: u16, input: Vec<u8>) -> zbus::fdo::Result<Vec<u8>> {
        if input.len() > 248 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "legacy service input exceeds 248 bytes; long write is unsupported".into(),
            ));
        }
        let _ = (handle, input);
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Find a remote service by UUID (16-bit)
    async fn find_by_uuid(&self, uuid16: u16) -> zbus::fdo::Result<u16> {
        let _ = uuid16;
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }

    /// Read a remote property by UUID (16-bit)
    async fn read_by_uuid(&self, uuid16: u16) -> zbus::fdo::Result<Vec<u8>> {
        let _ = uuid16;
        Err(zbus::fdo::Error::NotSupported(
            "SSAP service database and operations are not connected; legacy kernel staging is removed".into(),
        ))
    }
}

// ----- D-Bus return types -----

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct SsapInfo {
    pub service_count: u16,
    pub property_count: u16,
    pub total_entries: u16,
    pub mtu: u16,
    pub notification_count: u16,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct ServiceEntry {
    pub start_handle: u16,
    pub end_handle: u16,
    pub uuid16: u16,
    pub primary: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct NotificationData {
    pub handle: u16,
    pub indication: bool,
    pub data: Vec<u8>,
}

#[cfg(test)]
mod validation_tests {
    use super::*;
    use crate::{bonding::BondingStore, config::DaemonConfig, state::AdapterState};
    use libsparklink::Adapter;
    use slk_experimental::profile::ProfileRegistry;
    use std::sync::Arc;
    use tokio::sync::Mutex;

    #[tokio::test]
    async fn actual_private_bus_service_calls_are_not_supported() {
        use std::process::Stdio;
        use tokio::io::{AsyncBufReadExt, BufReader};

        let executable =
            std::env::var_os("SPARKLINK_TEST_DBUS_DAEMON").unwrap_or_else(|| "dbus-daemon".into());
        let mut bus = tokio::process::Command::new(executable)
            .args(["--session", "--nofork", "--print-address=1"])
            .stdout(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .unwrap();
        let mut address = String::new();
        tokio::time::timeout(
            std::time::Duration::from_secs(3),
            BufReader::new(bus.stdout.take().unwrap()).read_line(&mut address),
        )
        .await
        .unwrap()
        .unwrap();
        let server = zbus::connection::Builder::address(address.trim())
            .unwrap()
            .name("org.sparklink.SsapRemovalTest")
            .unwrap()
            .serve_at(
                "/org/sparklink/services",
                SsapManagerIface::new(Arc::new(Mutex::new(AdapterState::new(
                    Adapter::open("/dev/null").unwrap(),
                    DaemonConfig::default(),
                    BondingStore::new(&std::env::temp_dir(), "unused-ssap-bus-test"),
                    ProfileRegistry::new(),
                )))),
            )
            .unwrap()
            .serve_at("/org/sparklink/remote", RemoteServiceIface {})
            .unwrap()
            .build()
            .await
            .unwrap();
        let client = zbus::connection::Builder::address(address.trim())
            .unwrap()
            .build()
            .await
            .unwrap();
        let local = zbus::Proxy::new(
            &client,
            "org.sparklink.SsapRemovalTest",
            "/org/sparklink/services",
            "org.sparklink.ServiceManager",
        )
        .await
        .unwrap();
        let remote = zbus::Proxy::new(
            &client,
            "org.sparklink.SsapRemovalTest",
            "/org/sparklink/remote",
            "org.sparklink.RemoteService",
        )
        .await
        .unwrap();
        for result in [
            local.call::<_, _, ()>("RegisterServices", &()).await,
            local.call::<_, _, ()>("Notify", &(1u16,)).await,
            remote.call::<_, _, ()>("ExchangeInfo", &()).await,
            remote
                .call::<_, _, ()>("Write", &(1u16, vec![1u8, 2]))
                .await,
        ] {
            assert!(matches!(result, Err(zbus::Error::MethodError(name, _, _))
                if name.as_str() == "org.freedesktop.DBus.Error.NotSupported"));
        }
        drop((local, remote, client, server));
        bus.kill().await.unwrap();
        bus.wait().await.unwrap();
    }

    #[tokio::test]
    async fn actual_service_method_rejects_invalid_input_before_state_lock_or_ioctl() {
        let state = Arc::new(Mutex::new(AdapterState::new(
            Adapter::open("/dev/null").unwrap(),
            DaemonConfig::default(),
            BondingStore::new(&std::env::temp_dir(), "unused-ssap-validation-test"),
            ProfileRegistry::new(),
        )));
        let service = SsapManagerIface::new(state.clone());
        let remote = RemoteServiceIface::new(state.clone(), 0);
        let _locked = state.lock().await;
        let unsupported = tokio::time::timeout(
            std::time::Duration::from_secs(1),
            service.register_local_service(vec![1, 0], vec![(vec![2, 0], 2, 0, vec![])]),
        )
        .await
        .unwrap();
        assert!(matches!(
            unsupported,
            Err(zbus::fdo::Error::NotSupported(_))
        ));

        // The state lock is deliberately held. Incorrect validation order
        // blocks here and fails the deadline, rather than silently succeeding.
        for (ops, value) in [(0x49, vec![]), (9, vec![0; 249])] {
            let result = tokio::time::timeout(
                std::time::Duration::from_secs(1),
                service.add_property(1, ops, value),
            )
            .await
            .unwrap();
            assert!(matches!(result, Err(zbus::fdo::Error::InvalidArgs(_))));
        }
        for result in [
            tokio::time::timeout(
                std::time::Duration::from_secs(1),
                service.write_property(1, vec![0; 253]),
            )
            .await
            .unwrap(),
            tokio::time::timeout(
                std::time::Duration::from_secs(1),
                remote.write(1, vec![0; 249]),
            )
            .await
            .unwrap(),
            tokio::time::timeout(
                std::time::Duration::from_secs(1),
                remote.call_method(1, vec![0; 249]),
            )
            .await
            .unwrap()
            .map(|_| ()),
        ] {
            assert!(matches!(result, Err(zbus::fdo::Error::InvalidArgs(_))));
        }
    }
}
