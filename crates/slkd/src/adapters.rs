//! Each registration has its own fd, bootstrap and subscription. Workers are
//! independent: a controller waiting for a USB timeout cannot hold the directory
//! or prevent another controller from being enumerated or removed.
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
use crate::profile::ProfileRegistry;
#[cfg(feature = "experimental-legacy-profiles")]
use crate::profile::{BatteryProfile, DeviceInfoProfile};
use crate::{
    bonding::BondingStore,
    config::DaemonConfig,
    controller::ControllerIface,
    dbus_iface::{AdapterIface, DeviceIface},
    event_loop::EventTask,
    extadv::ExtAdvIface,
    security::SecurityIface,
    service::{RemoteServiceIface, SsapManagerIface},
    state::{AdapterDirectory, AdapterRegistration, AdapterState, SharedState},
};
use libsparklink::Adapter;
use slk_protocol::{CONTROLLER_READY, SleControllerSnapshot};
use std::{sync::Arc, time::Duration};
use tokio::{
    sync::{Mutex, watch},
    task::JoinHandle,
};
use tracing::{info, warn};

const POLL: Duration = Duration::from_millis(250);

/// Withdraw authority while SharedState and outstanding RPCs still retain the
/// fd. Last-close cleanup is a crash fallback, not the normal daemon handoff.
async fn relinquish(adapter: Arc<Adapter>, generation: u64, lease: u64) -> anyhow::Result<()> {
    let fd = adapter.clone();
    match tokio::task::spawn_blocking(move || {
        fd.release_management(generation, lease, slk_protocol::MANAGEMENT_MANAGED)
    })
    .await?
    {
        Ok(()) => {}
        Err(libsparklink::Error::Ioctl(nix::errno::Errno::ENODEV)) => return Ok(()),
        Err(error) => return Err(error.into()),
    }
    let deadline = tokio::time::Instant::now() + Duration::from_secs(6);
    loop {
        let fd = adapter.clone();
        let status =
            match tokio::task::spawn_blocking(move || fd.management_status(generation)).await? {
                Ok(status) => status,
                Err(libsparklink::Error::Ioctl(nix::errno::Errno::ENODEV)) => return Ok(()),
                Err(error) => return Err(error.into()),
            };
        match status.state {
            slk_protocol::MANAGEMENT_FREE => {
                info!(
                    generation,
                    "adapter management relinquished while fd retained"
                );
                return Ok(());
            }
            slk_protocol::MANAGEMENT_FAULTED => anyhow::bail!(
                "management cleanup fault: generation={generation} errno={} status={} opcode={}",
                status.error,
                status.status,
                status.opcode
            ),
            slk_protocol::MANAGEMENT_REVOKING => {}
            // A successor may acquire between RELEASE and QUERY. Its token is
            // hidden from this fd: it has authority, the withdrawn fd does not.
            slk_protocol::MANAGEMENT_HELD if status.flags & 1 == 0 => return Ok(()),
            _ => anyhow::bail!("management authority retained after release"),
        }
        if tokio::time::Instant::now() >= deadline {
            anyhow::bail!("management cleanup observation timeout: generation={generation}");
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

pub(crate) fn object_path(snapshot: &SleControllerSnapshot) -> String {
    format!(
        "/org/sparklink/slk{}_g{}",
        snapshot.dev_index, snapshot.generation
    )
}

async fn open_selected(path: String, id: u16) -> anyhow::Result<(Adapter, SleControllerSnapshot)> {
    tokio::task::spawn_blocking(move || {
        let mut adapter = Adapter::open(path)?;
        adapter.select_device(id)?;
        let snapshot = adapter.controller_snapshot(0)?;
        Ok((adapter, snapshot))
    })
    .await?
}

/// One request id allocator per selected initialization fd. Separate nodes never
/// share an fd, operation store, or service/profile actor.
async fn initialize(
    adapter: Arc<Adapter>,
    snapshot: SleControllerSnapshot,
    mut cancelled: watch::Receiver<bool>,
) -> anyhow::Result<()> {
    if snapshot.profile == 0 || snapshot.flags == CONTROLLER_READY {
        return Ok(());
    }
    let nonce = tokio::task::spawn_blocking(|| -> std::io::Result<u64> {
        use std::io::Read;
        let mut bytes = [0; 8];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
        Ok(u64::from_ne_bytes(bytes).max(1))
    })
    .await??;
    for operation in [
        slk_protocol::DISCOVERY_ADV_CONFIGURE_OFF,
        slk_protocol::DISCOVERY_SCAN_INITIALIZE_OFF,
    ] {
        if *cancelled.borrow() {
            return Ok(());
        }
        let request_id = nonce.wrapping_add(operation as u64).max(1);
        let request = if operation == slk_protocol::DISCOVERY_ADV_CONFIGURE_OFF {
            libsparklink::ws73_basic_standby(&snapshot, request_id)?
        } else {
            libsparklink::ws73_basic_scan_standby(&snapshot, request_id)?
        };
        let fd = adapter.clone();
        // No SharedState or directory guard is held across any ioctl/wait.
        tokio::task::spawn_blocking(move || fd.submit_discovery(&request)).await??;
        let deadline = tokio::time::Instant::now() + Duration::from_secs(7);
        loop {
            if *cancelled.borrow() {
                return Ok(());
            }
            let fd = adapter.clone();
            let result = tokio::task::spawn_blocking(move || {
                fd.discovery_result(snapshot.generation, request.request_id)
            })
            .await??
            .ok_or_else(|| anyhow::anyhow!("initialization result absent or evicted"))?;
            if result.is_terminal() {
                if result.state != 3 {
                    anyhow::bail!(
                        "initialization operation={operation} state={} status=0x{:02x} errno={}",
                        result.state,
                        result.status,
                        result.error
                    );
                }
                break;
            }
            if tokio::time::Instant::now() >= deadline {
                anyhow::bail!("initialization timeout");
            }
            tokio::select! {
                _ = cancelled.changed() => {},
                _ = tokio::time::sleep(Duration::from_millis(10)) => {},
            }
        }
    }
    Ok(())
}

struct Node {
    path: String,
    state: SharedState,
    control: Arc<Adapter>,
    lease: Option<u64>,
    connection: zbus::Connection,
    event: Option<EventTask>,
    init: JoinHandle<()>,
    cancel: watch::Sender<bool>,
}
impl Node {
    async fn create(
        device: &str,
        adapter: Adapter,
        snapshot: SleControllerSnapshot,
        config: DaemonConfig,
        storage: &str,
        connection: &zbus::Connection,
        directory: &AdapterDirectory,
    ) -> anyhow::Result<Self> {
        config.validate_for_profile(snapshot.profile)?;
        let path = object_path(&snapshot);
        let device = device.to_owned();
        let receiver = tokio::task::spawn_blocking(move || -> libsparklink::Result<_> {
            let mut receiver = Adapter::open(&device)?;
            receiver.select_device(snapshot.dev_index)?;
            receiver.controller_snapshot(snapshot.generation)?;
            Ok(receiver)
        })
        .await??;
        enum Subscription {
            Legacy(libsparklink::EventReceiver),
            Native(libsparklink::ControllerEventReceiver),
        }
        // Prepare AsyncFd before publishing any D-Bus objects/actors.
        let subscription = if snapshot.profile == 0 {
            Subscription::Legacy(receiver.into_event_receiver()?)
        } else {
            Subscription::Native(receiver.into_controller_event_receiver()?)
        };
        let (adapter, lease) = tokio::task::spawn_blocking(move || -> libsparklink::Result<_> {
            let lease =
                if snapshot.profile != 0 {
                    Some(adapter.acquire_management(
                        snapshot.generation,
                        slk_protocol::MANAGEMENT_MANAGED,
                    )?)
                } else {
                    None
                };
            Ok((Arc::new(adapter), lease))
        })
        .await??;
        let control = adapter.clone();
        let storage = storage.to_owned();
        let (adapter, bonding) = tokio::task::spawn_blocking(move || {
            let key = format!(
                "p{}-{}",
                snapshot.profile,
                snapshot
                    .address
                    .iter()
                    .map(|b| format!("{b:02x}"))
                    .collect::<String>()
            );
            let mut bonding = BondingStore::new(std::path::Path::new(&storage), &key);
            if let Err(error) = bonding.load() {
                info!(%error, "no bonding metadata loaded");
            }
            (adapter, bonding)
        })
        .await?;
        #[cfg(any(test, feature = "experimental-legacy-profiles"))]
        let profiles = {
            let fd = adapter.clone();
            tokio::task::spawn_blocking(move || experimental_profiles(&fd, snapshot.profile))
                .await?
        };
        #[cfg(any(test, feature = "experimental-legacy-profiles"))]
        let mut state = AdapterState::new(adapter, config, bonding, profiles);
        #[cfg(not(any(test, feature = "experimental-legacy-profiles")))]
        let mut state = AdapterState::new(adapter, config, bonding);
        state.object_path = path.clone();
        state.controller = snapshot;
        if snapshot.profile == 1 {
            state.native_control = Some(control.clone());
        }
        let state = Arc::new(Mutex::new(state));
        // Roll back partial registration if any of the D-Bus interfaces fails.
        if let Err(error) = publish(connection, &path, &state).await {
            if let Some(lease) = lease
                && let Err(cleanup) = relinquish(control.clone(), snapshot.generation, lease).await
            {
                warn!(%cleanup, %path, "partial adapter publication cleanup failed");
            }
            remove_interfaces(connection, &path).await;
            crate::state::shutdown_services(&state).await;
            return Err(error);
        }
        let event = match subscription {
            Subscription::Legacy(receiver) => {
                EventTask::start(receiver, state.clone(), connection.clone())
            }
            Subscription::Native(receiver) => {
                EventTask::start_native(receiver, state.clone(), connection.clone(), snapshot)
            }
        };
        let (cancel, cancelled) = watch::channel(false);
        let init_control = control.clone();
        let init_state = state.clone();
        let init_connection = connection.clone();
        let init_path = path.clone();
        let init = tokio::spawn(async move {
            if let Err(error) = initialize(init_control, snapshot, cancelled).await {
                warn!(%error, index=snapshot.dev_index, generation=snapshot.generation, "adapter initialization failed");
                init_state.lock().await.initialization_error = error.to_string();
                invalidate_properties(&init_connection, &init_path, &["InitializationError"]).await;
            }
        });
        directory.lock().await.insert(
            path.clone(),
            AdapterRegistration {
                adapter: control.clone(),
                generation: snapshot.generation,
            },
        );
        info!(%path, "adapter registered");
        Ok(Self {
            path,
            state,
            control,
            lease,
            connection: connection.clone(),
            event: Some(event),
            init,
            cancel,
        })
    }
    async fn refresh(&self) -> anyhow::Result<()> {
        let fd = self.control.clone();
        let generation = self.state.lock().await.controller.generation;
        let (snapshot, radio) = tokio::task::spawn_blocking(move || -> libsparklink::Result<_> {
            let snapshot = fd.controller_snapshot(generation)?;
            let radio = if snapshot.profile == 1 {
                Some(fd.discovery_snapshot()?)
            } else {
                None
            };
            Ok((snapshot, radio))
        })
        .await??;
        let changed = {
            let mut st = self.state.lock().await;
            let mut changed = st.controller != snapshot;
            st.controller = snapshot;
            if let Some(radio) = radio {
                changed |= st.radio_advertising != radio.radio_adv
                    || st.radio_scanning != radio.radio_scan;
                st.radio_advertising = radio.radio_adv;
                st.radio_scanning = radio.radio_scan;
            }
            changed
        };
        if changed {
            invalidate_properties(
                &self.connection,
                &self.path,
                &[
                    "Ready",
                    "ControllerState",
                    "CommandCredits",
                    "ControllerError",
                    "AdvertisingState",
                    "ScanningState",
                    "Discovering",
                ],
            )
            .await;
        }
        Ok(())
    }
    async fn remove(mut self, connection: &zbus::Connection, directory: &AdapterDirectory) {
        directory.lock().await.remove(&self.path);
        self.state.lock().await.present = false;
        let _ = self.cancel.send(true);
        // Do this before awaiting event/actor/RPC teardown. Queries can finish,
        // but retained clones cannot admit another management operation.
        if let Some(lease) = self.lease.take() {
            let generation = self.state.lock().await.controller.generation;
            if let Err(error) = relinquish(self.control.clone(), generation, lease).await {
                warn!(%error, path=%self.path, "adapter management cleanup failed");
            }
        }
        invalidate_properties(connection, &self.path, &["Ready", "ControllerState"]).await;
        if let Some(event) = self.event.take() {
            let _ = event.shutdown().await;
        }
        let _ = self.init.await;
        let (device_paths, handles) = {
            let st = self.state.lock().await;
            (
                st.devices
                    .values()
                    .map(|d| d.object_path.clone())
                    .collect::<Vec<_>>(),
                st.devices
                    .values()
                    .filter_map(|d| d.conn_handle)
                    .collect::<Vec<_>>(),
            )
        };
        for path in device_paths {
            let _ = connection
                .object_server()
                .remove::<DeviceIface, _>(path.as_str())
                .await;
        }
        for handle in handles {
            let path = format!("{}/conn_{handle:04x}", self.path);
            let _ = connection
                .object_server()
                .remove::<RemoteServiceIface, _>(path.as_str())
                .await;
        }
        remove_interfaces(connection, &self.path).await;
        crate::state::shutdown_services(&self.state).await;
        info!(path=%self.path, "adapter removed");
    }
}
async fn publish(c: &zbus::Connection, path: &str, st: &SharedState) -> anyhow::Result<()> {
    c.object_server()
        .at(path, AdapterIface::new(st.clone()))
        .await?;
    c.object_server()
        .at(format!("{path}/security"), SecurityIface::new(st.clone()))
        .await?;
    c.object_server()
        .at(
            format!("{path}/services"),
            SsapManagerIface::new(st.clone()),
        )
        .await?;
    c.object_server()
        .at(format!("{path}/extadv"), ExtAdvIface::new(st.clone()))
        .await?;
    c.object_server()
        .at(
            format!("{path}/controller"),
            ControllerIface::new(st.clone()),
        )
        .await?;
    Ok(())
}
async fn remove_interfaces(c: &zbus::Connection, path: &str) {
    let _ = c.object_server().remove::<AdapterIface, _>(path).await;
    let _ = c
        .object_server()
        .remove::<SecurityIface, _>(format!("{path}/security"))
        .await;
    let _ = c
        .object_server()
        .remove::<SsapManagerIface, _>(format!("{path}/services"))
        .await;
    let _ = c
        .object_server()
        .remove::<ExtAdvIface, _>(format!("{path}/extadv"))
        .await;
    let _ = c
        .object_server()
        .remove::<ControllerIface, _>(format!("{path}/controller"))
        .await;
}

pub(crate) struct AdapterManager {
    cancel: watch::Sender<bool>,
    workers: Vec<JoinHandle<()>>,
}
impl AdapterManager {
    pub(crate) fn start(
        device: String,
        config: DaemonConfig,
        storage: String,
        connection: zbus::Connection,
        directory: AdapterDirectory,
    ) -> Self {
        let (cancel, cancelled) = watch::channel(false);
        let mut workers = Vec::new();
        let (mask, registered) = watch::channel(0u16);
        let registry_path = device.clone();
        let mut registry_cancelled = cancelled.clone();
        workers.push(tokio::spawn(async move {
            let mut registry: Option<Arc<Adapter>> = None;
            loop {
                if *registry_cancelled.borrow() {
                    break;
                }
                if registry.is_none() {
                    let path = registry_path.clone();
                    if let Ok(Ok(fd)) =
                        tokio::task::spawn_blocking(move || Adapter::open(path)).await
                    {
                        registry = Some(Arc::new(fd));
                    }
                }
                if let Some(fd) = &registry {
                    let fd = fd.clone();
                    match tokio::task::spawn_blocking(move || fd.device_indices()).await {
                        Ok(Ok(ids)) => {
                            mask.send_if_modified(|mask| {
                                let next = ids.iter().fold(0u16, |bits, id| bits | (1 << id));
                                if next == *mask {
                                    false
                                } else {
                                    *mask = next;
                                    true
                                }
                            });
                        }
                        _ => {
                            registry = None;
                            let _ = mask.send(0);
                        }
                    }
                }
                tokio::select! {
                    _ = registry_cancelled.changed() => {},
                    _ = tokio::time::sleep(POLL) => {},
                }
            }
        }));
        for id in 0..16 {
            let (device, config, storage, connection, directory, mut cancelled) = (
                device.clone(),
                config.clone(),
                storage.clone(),
                connection.clone(),
                directory.clone(),
                cancelled.clone(),
            );
            let mut registered = registered.clone();
            workers.push(tokio::spawn(async move {
                let mut node: Option<Node> = None;
                loop {
                    if *cancelled.borrow() { break; }
                    let currently_registered = *registered.borrow() & (1 << id) != 0;
                    if let Some(current) = &node {
                        if let Err(error) = current.refresh().await {
                            warn!(%error, index=id, "adapter snapshot unavailable; removing registration");
                            node.take().unwrap().remove(&connection, &directory).await;
                        }
                    } else if currently_registered
                        && let Ok((adapter, snapshot)) = open_selected(device.clone(), id).await {
                        match Node::create(&device, adapter, snapshot, config.clone(), &storage, &connection, &directory).await {
                            Ok(ready) => node = Some(ready),
                            Err(error) => warn!(%error, index=id, "adapter registration failed"),
                        }
                    }
                    tokio::select! {
                        _ = cancelled.changed() => {},
                        _ = registered.changed() => {},
                        _ = tokio::time::sleep(POLL) => {},
                    }
                }
                if let Some(node) = node { node.remove(&connection, &directory).await; }
            }));
        }
        Self { cancel, workers }
    }
    pub(crate) async fn shutdown(self) -> anyhow::Result<()> {
        let _ = self.cancel.send(true);
        for worker in self.workers {
            worker.await?;
        }
        Ok(())
    }
}

/// Invalidate cached D-Bus properties after changing state outside a setter.
/// Emit after releasing SharedState so property fetches cannot deadlock.
pub(crate) async fn invalidate_properties(c: &zbus::Connection, path: &str, names: &[&str]) {
    let changed: std::collections::HashMap<&str, zbus::zvariant::Value<'_>> = Default::default();
    if let Err(error) = c
        .emit_signal(
            None::<&str>,
            path,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            &("org.sparklink.Adapter", changed, names),
        )
        .await
    {
        warn!(%error, %path, "adapter property invalidation failed");
    }
}

#[cfg(feature = "experimental-legacy-profiles")]
fn experimental_profiles(adapter: &Adapter, profile: u32) -> ProfileRegistry {
    let mut profiles = ProfileRegistry::new();
    // Native discovery has no SSAP/Profile backend. No legacy registration.
    if profile == 0 {
        tracing::warn!("experimental legacy Profiles enabled: no service/security qualification");
        profiles.add(Box::new(BatteryProfile::new(100)));
        profiles.add(Box::new(DeviceInfoProfile::new()));
        profiles.add(Box::new(crate::hid::HidProfile::boot_keyboard()));
        profiles.init_all(adapter);
    }
    profiles
}
#[cfg(all(test, not(feature = "experimental-legacy-profiles")))]
fn experimental_profiles(_adapter: &Adapter, _profile: u32) -> ProfileRegistry {
    ProfileRegistry::new()
}
