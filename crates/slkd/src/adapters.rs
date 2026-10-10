//! Each registration has its own fd, bootstrap and subscription. Workers are
//! independent: a controller waiting for a USB timeout cannot hold the directory
//! or prevent another controller from being enumerated or removed.
use crate::{
    bonding::BondingStore,
    config::DaemonConfig,
    controller::ControllerIface,
    dbus_iface::{AdapterIface, DeviceIface},
    event_loop::EventTask,
    extadv::ExtAdvIface,
    profile::{BatteryProfile, DeviceInfoProfile, ProfileRegistry},
    security::SecurityIface,
    service::{RemoteServiceIface, SsapManagerIface},
    state::{AdapterDirectory, AdapterState, SharedState},
};
use libsparklink::Adapter;
use slk_protocol::{CONTROLLER_READY, SleControllerSnapshot, SleDiscoverySubmit};
use std::{sync::Arc, time::Duration};
use tokio::{
    sync::{Mutex, watch},
    task::JoinHandle,
};
use tracing::{info, warn};

const POLL: Duration = Duration::from_millis(250);

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
    for operation in [2, 4] {
        if *cancelled.borrow() {
            return Ok(());
        }
        let request = SleDiscoverySubmit {
            version: 1,
            generation: snapshot.generation,
            profile: snapshot.profile,
            request_id: nonce.wrapping_add(operation as u64).max(1),
            operation,
            ..Default::default()
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
        let path = object_path(&snapshot);
        let device = device.to_owned();
        let (receiver, init_adapter) =
            tokio::task::spawn_blocking(move || -> libsparklink::Result<_> {
                let mut receiver = Adapter::open(&device)?;
                receiver.select_device(snapshot.dev_index)?;
                receiver.controller_snapshot(snapshot.generation)?;
                let mut init_adapter = Adapter::open(&device)?;
                init_adapter.select_device(snapshot.dev_index)?;
                init_adapter.controller_snapshot(snapshot.generation)?;
                Ok((receiver, init_adapter))
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
        let control = Arc::new(init_adapter);
        let storage = storage.to_owned();
        let (adapter, bonding, profiles) = tokio::task::spawn_blocking(move || {
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
            let mut profiles = ProfileRegistry::new();
            // Native discovery has no SSAP/profile backend yet. Never attempt
            // legacy profile registration against a native registration.
            if snapshot.profile == 0 {
                profiles.add(Box::new(BatteryProfile::new(100)));
                profiles.add(Box::new(DeviceInfoProfile::new()));
                profiles.add(Box::new(crate::hid::HidProfile::boot_keyboard()));
                profiles.init_all(&adapter);
            }
            (adapter, bonding, profiles)
        })
        .await?;
        let mut state = AdapterState::new(adapter, config, bonding, profiles);
        state.object_path = path.clone();
        state.controller = snapshot;
        if snapshot.profile == 1 {
            state.native_control = Some(control.clone());
        }
        let state = Arc::new(Mutex::new(state));
        // Roll back partial registration if any of the D-Bus interfaces fails.
        if let Err(error) = publish(connection, &path, &state).await {
            remove_interfaces(connection, &path).await;
            let (bonding, profiles) = {
                let st = state.lock().await;
                (st.bonding.clone(), st.profiles.clone())
            };
            tokio::join!(bonding.shutdown(), profiles.shutdown());
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
        directory.lock().await.insert(path.clone(), state.clone());
        info!(%path, "adapter registered");
        Ok(Self {
            path,
            state,
            control,
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
        invalidate_properties(connection, &self.path, &["Ready", "ControllerState"]).await;
        let _ = self.cancel.send(true);
        if let Some(event) = self.event.take() {
            let _ = event.shutdown().await;
        }
        let _ = self.init.await;
        let (device_paths, handles, bonding, profiles) = {
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
                st.bonding.clone(),
                st.profiles.clone(),
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
        tokio::join!(bonding.shutdown(), profiles.shutdown());
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
                    } else if currently_registered {
                        if let Ok((adapter, snapshot)) = open_selected(device.clone(), id).await {
                            match Node::create(&device, adapter, snapshot, config.clone(), &storage, &connection, &directory).await {
                                Ok(ready) => node = Some(ready),
                                Err(error) => warn!(%error, index=id, "adapter registration failed"),
                            }
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
