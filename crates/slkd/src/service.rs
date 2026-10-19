use zbus::interface;

use crate::deadline_error;
use crate::state::SharedState;
use slk_channel::deadline::Deadline;

async fn owned_request<T>(
    original: Deadline,
    work: impl std::future::Future<Output = zbus::fdo::Result<T>>,
) -> zbus::fdo::Result<T> {
    original.remaining().map_err(deadline_error)?;
    let result = tokio::time::timeout_at(original.instant().into(), work)
        .await
        .map_err(|_| zbus::fdo::Error::Timeout("owned service original deadline".into()))?;
    original.remaining().map_err(deadline_error)?;
    result
}

/// Local database and caller-owned registration APIs for the sole userspace Engine.
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
    /// Caller-owned local service. '/' disables the authorizer, not access
    /// checks; authorization bits then remain unsupported. The bus policy
    /// separately controls who may register services, not controller rights.
    async fn register_owned_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<crate::ssap_database::PropertyDefinition>,
        authorizer: zbus::zvariant::OwnedObjectPath,
        deadline: slk_contract::Deadline,
        #[zbus(connection)] connection: &zbus::Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<(u16, u16, Vec<u16>)> {
        let original =
            Deadline::from_stamp(slk_contract::deadline_stamp(deadline)).map_err(deadline_error)?;
        owned_request(original, async {
            // Bounded validation precedes watches and allocation of a service.
            if properties.is_empty()
                || properties.len() > 64
                || !matches!(uuid.len(), 2 | 16)
                || !uuid.iter().any(|b| *b != 0)
            {
                return Err(zbus::fdo::Error::InvalidArgs(
                    "invalid UUID/property count".into(),
                ));
            }
            for (uuid, ops, access, value) in &properties {
                let access = slk_protocol::ssap::access::SsapAccess::from_bits(*access)
                    .map_err(|e| zbus::fdo::Error::InvalidArgs(e.into()))?;
                let ops = slk_protocol::SsapOperations::from_bits(*ops)
                    .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
                if ops.bits() & !5 != 0
                    || access.needs_local_authorization() && authorizer.as_str() == "/"
                {
                    return Err(zbus::fdo::Error::NotSupported(
                        "operation or local authorizer unavailable".into(),
                    ));
                }
                if !matches!(uuid.len(), 2 | 16)
                    || !uuid.iter().any(|b| *b != 0)
                    || value.len() > 2042
                {
                    return Err(zbus::fdo::Error::InvalidArgs(
                        "invalid property UUID/value length".into(),
                    ));
                }
            }
            let sender = crate::security_policy::sender(&header)?;
            let (database, lease, generation, slots) = {
                let state = self.state.lock().await;
                if !state.present {
                    return Err(zbus::fdo::Error::Failed("adapter retired".into()));
                }
                (
                    state.ssap_database.clone(),
                    state.native_lease.clone().ok_or_else(|| {
                        zbus::fdo::Error::NotSupported("Native management required".into())
                    })?,
                    state.controller.generation,
                    state.ssap_owner_slots.clone(),
                )
            };
            let slot = slots.try_acquire_owned().map_err(|_| {
                zbus::fdo::Error::LimitsExceeded("local service owner capacity".into())
            })?;
            let owner = crate::ssap_authorization::Owner::pin(
                connection,
                sender,
                authorizer,
                &database,
                slot,
                original.instant().into(),
            )
            .await?;
            {
                let state = self.state.lock().await;
                if !state.present
                    || state.controller.generation != generation
                    || !std::sync::Arc::ptr_eq(&database, &state.ssap_database)
                    || state
                        .native_lease
                        .as_ref()
                        .is_none_or(|current| !std::sync::Arc::ptr_eq(current, &lease))
                {
                    return Err(zbus::fdo::Error::Failed(
                        "adapter/management changed during owner registration".into(),
                    ));
                }
            }
            let admission = lease
                .try_lock_owned()
                .map_err(|_| zbus::fdo::Error::Failed("management handoff busy".into()))?;
            if !admission.accepting || admission.token.is_none() {
                return Err(zbus::fdo::Error::Failed("management revoked".into()));
            }
            let mut database = database
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?;
            original.remaining().map_err(deadline_error)?;
            database
                .register_owned(uuid, properties, owner)
                .map_err(zbus::fdo::Error::InvalidArgs)
        })
        .await
    }
    async fn unregister_owned_local_service(
        &self,
        start: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<()> {
        let original =
            Deadline::from_stamp(slk_contract::deadline_stamp(deadline)).map_err(deadline_error)?;
        owned_request(original, async {
            let caller = crate::security_policy::sender(&header)?;
            let state = self.state.lock().await;
            if !state.present {
                return Err(zbus::fdo::Error::Failed("adapter retired".into()));
            }
            let mut database = state
                .ssap_database
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?;
            original.remaining().map_err(deadline_error)?;
            database
                .remove_owned(start, &caller)
                .map_err(zbus::fdo::Error::AccessDenied)
        })
        .await
    }
    async fn read_owned_local_value(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<Vec<u8>> {
        let original =
            Deadline::from_stamp(slk_contract::deadline_stamp(deadline)).map_err(deadline_error)?;
        owned_request(original, async {
            let caller = crate::security_policy::sender(&header)?;
            let state = self.state.lock().await;
            if !state.present {
                return Err(zbus::fdo::Error::Failed("adapter retired".into()));
            }
            let database = state
                .ssap_database
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("database poisoned".into()))?;
            original.remaining().map_err(deadline_error)?;
            database
                .local_read_owned(handle, &caller)
                .map_err(zbus::fdo::Error::AccessDenied)
        })
        .await
    }
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
}

#[cfg(test)]
mod validation_tests {
    use super::*;
    use crate::{bonding::BondingStore, config::DaemonConfig, state::AdapterState};
    use slk_experimental::profile::ProfileRegistry;
    use slk_native::Adapter;
    use std::sync::Arc;
    use tokio::sync::Mutex;

    #[tokio::test]
    async fn retired_service_methods_are_absent_on_actual_private_bus() {
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
        let xml = local.introspect().await.unwrap();
        for (name, expected) in [
            (
                "RegisterOwnedLocalService",
                vec!["ay", "a(ayuuay)", "o", "(ttttt)"],
            ),
            ("ReadOwnedLocalValue", vec!["q", "(ttttt)"]),
            ("UnregisterOwnedLocalService", vec!["q", "(ttttt)"]),
        ] {
            let method = xml
                .split(&format!("<method name=\"{name}\">"))
                .nth(1)
                .unwrap_or_else(|| panic!("missing {name}: {xml}"));
            let method = method.split("</method>").next().unwrap();
            let actual: Vec<_> = method
                .lines()
                .filter(|line| line.contains("direction=\"in\""))
                .map(|line| {
                    line.split("type=\"")
                        .nth(1)
                        .unwrap()
                        .split('"')
                        .next()
                        .unwrap()
                })
                .collect();
            assert_eq!(actual, expected, "{name}: {method}");
        }

        for live in [
            "RegisterOwnedLocalService",
            "UnregisterOwnedLocalService",
            "ReadOwnedLocalValue",
            "RegisterLocalService",
            "ListLocalServices",
            "RemoveLocalService",
            "ReadLocalValue",
        ] {
            assert!(xml.contains(&format!("name=\"{live}\"")), "{xml}");
        }
        for method in [
            "GetInfo",
            "RegisterServices",
            "AddService",
            "AddProperty",
            "RemoveService",
            "ListServices",
            "ReadProperty",
            "WriteProperty",
            "Notify",
            "DequeueNotification",
        ] {
            assert!(!xml.contains(&format!("name=\"{method}\"")), "{xml}");
            // Dispatch must reject the absent member before decoding its old body.
            let result = local.call::<_, _, ()>(method, &()).await;
            assert!(matches!(result, Err(zbus::Error::MethodError(name, _, _))
                if name.as_str() == "org.freedesktop.DBus.Error.UnknownMethod"));
        }
        drop((local, client, server));
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

        // Reserved operation bits retain the same production permission type.
        // The held lock proves validation rejects before state or device access.
        let invalid = tokio::time::timeout(
            std::time::Duration::from_secs(1),
            service.register_local_service(vec![1, 0], vec![(vec![2, 0], 0x49, 0, vec![])]),
        )
        .await
        .unwrap();
        assert!(matches!(invalid, Err(zbus::fdo::Error::InvalidArgs(_))));
    }
}
