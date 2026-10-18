//! Each registration has its own fd, bootstrap and subscription. Workers are
//! independent: a controller waiting for a USB timeout cannot hold the directory
//! or prevent another controller from being enumerated or removed.
#[cfg(test)]
use crate::profile::ProfileRegistry;
use crate::registration::RegistrationNode;
use crate::{
    config::DaemonConfig,
    controller::ControllerIface,
    dbus_iface::AdapterIface,
    event_loop::EventTask,
    security::SecurityIface,
    service::SsapManagerIface,
    state::{
        AdapterDirectory, AdapterRegistration, AdapterState, InitializationOff, NativeLease,
        NativeManagement, RegistrationDirectory, SharedState,
    },
};
use slk_native::Adapter;
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
pub(crate) async fn relinquish(
    adapter: Arc<Adapter>,
    generation: u64,
    lease: u64,
) -> anyhow::Result<()> {
    let fd = adapter.clone();
    match tokio::task::spawn_blocking(move || {
        fd.release_management(generation, lease, slk_protocol::MANAGEMENT_MANAGED)
    })
    .await?
    {
        Ok(()) => {}
        Err(slk_native::Error::Ioctl(nix::errno::Errno::ENODEV)) => return Ok(()),
        Err(error) => return Err(error.into()),
    }
    let deadline = tokio::time::Instant::now() + Duration::from_secs(20);
    loop {
        let fd = adapter.clone();
        let status =
            match tokio::task::spawn_blocking(move || fd.management_status(generation)).await? {
                Ok(status) => status,
                Err(slk_native::Error::Ioctl(nix::errno::Errno::ENODEV)) => return Ok(()),
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
    slk_contract::ControllerId {
        index: snapshot.dev_index,
        generation: snapshot.generation,
    }
    .path()
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

async fn observe_registration(
    device: &str,
    observer: &mut Option<Arc<Adapter>>,
    id: u16,
) -> anyhow::Result<Option<slk_protocol::SleRegistrationSnapshot>> {
    if observer.is_none() {
        let device = device.to_owned();
        *observer = Some(Arc::new(
            tokio::task::spawn_blocking(move || Adapter::open(device)).await??,
        ));
    }
    let fd = observer.as_ref().unwrap().clone();
    match tokio::task::spawn_blocking(move || fd.registration_snapshot(id, 0)).await? {
        Ok(snapshot) => Ok(Some(snapshot)),
        Err(slk_native::Error::Ioctl(nix::errno::Errno::ENODEV)) => Ok(None),
        Err(error) => {
            *observer = None;
            Err(error.into())
        }
    }
}

/// One request id allocator per selected initialization fd. Separate nodes never
/// share an fd, operation store, or service/profile actor.
async fn initialize(
    adapter: Arc<Adapter>,
    snapshot: SleControllerSnapshot,
    lease: Option<NativeLease>,
    policy: Option<slk_native::Ws73DiscoveryPolicy>,
    mut cancelled: watch::Receiver<bool>,
) -> anyhow::Result<()> {
    if snapshot.profile == 0 || snapshot.flags == CONTROLLER_READY {
        return Ok(());
    }
    let policy = policy.ok_or_else(|| anyhow::anyhow!("native discovery policy unavailable"))?;
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
            policy.standby(&snapshot, request_id)?
        } else {
            policy.scan_standby(&snapshot, request_id)?
        };
        let fd = adapter.clone();
        let authority = lease
            .clone()
            .ok_or_else(|| anyhow::anyhow!("bootstrap management unavailable"))?
            .lock_owned()
            .await;
        if *cancelled.borrow() || !authority.accepting || authority.token.is_none() {
            return Ok(());
        }
        let token = authority
            .token
            .ok_or_else(|| anyhow::anyhow!("bootstrap authority absent"))?;
        // No SharedState or directory guard is held across any ioctl/wait.
        tokio::task::spawn_blocking(move || {
            let mut authority = authority;
            fd.submit_discovery(&request)?;
            let domain = usize::from(operation == slk_protocol::DISCOVERY_SCAN_INITIALIZE_OFF);
            authority.initialized_off[domain] = Some(InitializationOff {
                generation: request.generation,
                token,
                request_id: request.request_id,
                operation,
            });
            Ok::<_, slk_native::Error>(())
        })
        .await??;
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
    lease: Option<NativeLease>,
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
        connection: &zbus::Connection,
        directory: &AdapterDirectory,
    ) -> anyhow::Result<Self> {
        config.validate_for_profile(snapshot.profile)?;
        let policy = if snapshot.profile == 1 {
            Some(config.ws73.for_address(snapshot.address)?)
        } else {
            None
        };
        let path = object_path(&snapshot);
        let device = device.to_owned();
        let receiver = tokio::task::spawn_blocking(move || -> slk_native::Result<_> {
            let mut receiver = Adapter::open(&device)?;
            receiver.select_device(snapshot.dev_index)?;
            receiver.controller_snapshot(snapshot.generation)?;
            Ok(receiver)
        })
        .await??;
        let subscription = receiver.into_controller_event_receiver()?;
        let (adapter, lease) = tokio::task::spawn_blocking(move || -> slk_native::Result<_> {
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
        let lease = lease.map(|token| {
            Arc::new(Mutex::new(NativeManagement {
                token: Some(token),
                accepting: true,
                connection_id: 0,
                initialized_off: [None; 2],
            }))
        });
        let control = adapter.clone();
        // Historical pairing files are not trusted credentials and are never
        // loaded by the daemon, including its experimental feature build.
        #[cfg(test)]
        let bonding =
            crate::bonding::BondingStore::new(&std::env::temp_dir(), "unused-registration-test");
        #[cfg(test)]
        let profiles = {
            let fd = adapter.clone();
            tokio::task::spawn_blocking(move || experimental_profiles(&fd, snapshot.profile))
                .await?
        };
        #[cfg(test)]
        let mut state = AdapterState::new(
            adapter,
            config,
            #[cfg(test)]
            bonding,
            profiles,
        );
        #[cfg(not(test))]
        let mut state = AdapterState::new(adapter, config);
        state.object_path = path.clone();
        state.controller = snapshot;
        if snapshot.profile == 1 {
            state.native_control = Some(control.clone());
            state.native_lease = lease.clone();
            state.native_discovery_policy = policy;
        }
        let state = Arc::new(Mutex::new(state));
        // Roll back partial registration if any of the D-Bus interfaces fails.
        if let Err(error) = publish(connection, &path, &state).await {
            if let Some(lease) = &lease
                && let Some(token) = lease.lock().await.token.take()
                && let Err(cleanup) = relinquish(control.clone(), snapshot.generation, token).await
            {
                warn!(%cleanup, %path, "partial adapter publication cleanup failed");
            }
            remove_interfaces(connection, &path).await;
            crate::state::shutdown_services(&state).await;
            return Err(error);
        }
        let event =
            EventTask::start_native(subscription, state.clone(), connection.clone(), snapshot);
        let (cancel, cancelled) = watch::channel(false);
        let init_control = control.clone();
        let init_state = state.clone();
        let init_connection = connection.clone();
        let init_path = path.clone();
        let init_lease = lease.clone();
        let init = tokio::spawn(async move {
            if let Err(error) =
                initialize(init_control, snapshot, init_lease, policy, cancelled).await
            {
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
        let (snapshot, radio) = tokio::task::spawn_blocking(move || -> slk_native::Result<_> {
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
                ],
            )
            .await;
        }
        Ok(())
    }
    async fn remove(mut self, connection: &zbus::Connection, directory: &AdapterDirectory) {
        directory.lock().await.remove(&self.path);
        let registrations = {
            let mut st = self.state.lock().await;
            st.present = false;
            let entries = st
                .native_connection_objects
                .values()
                .chain(st.retiring_connection_objects.values())
                .cloned()
                .collect::<Vec<_>>();
            // Fence even an unpublished Native creator before waiting for its
            // actual management guard. Registration, not D-Bus, owns the work.
            for entry in &entries {
                entry.owner.retire();
            }
            entries
        };
        let _ = self.cancel.send(true);
        // Do this before awaiting event/actor/RPC teardown. Queries can finish,
        // but retained clones cannot admit another management operation.
        if let Some(lease) = self.lease.take() {
            let mut lease = lease.lock().await;
            lease.accepting = false;
            lease.initialized_off = [None; 2];
            let generation = self.state.lock().await.controller.generation;
            if let Some(token) = lease.token.take()
                && let Err(error) = relinquish(self.control.clone(), generation, token).await
            {
                warn!(%error, path=%self.path, "adapter management cleanup failed");
            }
        }
        invalidate_properties(connection, &self.path, &["Ready", "ControllerState"]).await;
        if let Some(event) = self.event.take() {
            let _ = event.shutdown().await;
        }
        let _ = self.init.await;
        let peer_paths = {
            let st = self.state.lock().await;
            st.peers
                .iter()
                .map(|(key, p)| (*key, p.object_path.clone(), st.controller.generation))
                .collect::<Vec<_>>()
        };
        for entry in registrations {
            match crate::connection_object::retire_registration(connection, &entry).await {
                Ok(()) => {
                    let mut st = self.state.lock().await;
                    if st
                        .native_connection_objects
                        .get(&entry.reference.lifetime)
                        .is_some_and(|v| Arc::ptr_eq(&v.owner, &entry.owner))
                    {
                        st.native_connection_objects
                            .remove(&entry.reference.lifetime);
                    }
                    if st
                        .retiring_connection_objects
                        .get(&entry.path)
                        .is_some_and(|v| Arc::ptr_eq(&v.owner, &entry.owner))
                    {
                        st.retiring_connection_objects.remove(&entry.path);
                    }
                }
                Err(error) => {
                    warn!(%error,path=%entry.path,"connection owner retirement remains unresolved")
                }
            }
        }
        for (key, path, generation) in peer_paths {
            let Ok(iface) = connection
                .object_server()
                .interface::<_, crate::connection_object::PeerIface>(path.as_str())
                .await
            else {
                continue;
            };
            // Release the interface guard before removing from ObjectServer.
            let owned = iface.get().await.belongs_to(&self.state, generation, key);
            if !owned {
                continue;
            }
            if let Err(error) = connection
                .object_server()
                .remove::<crate::connection_object::PeerIface, _>(path.as_str())
                .await
            {
                warn!(%error,%path,"owned Peer removal failed during registration retirement");
            }
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
        connection: zbus::Connection,
        directory: AdapterDirectory,
        registrations: RegistrationDirectory,
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
            let (device, config, connection, directory, registrations, mut cancelled) = (
                device.clone(),
                config.clone(),
                connection.clone(),
                directory.clone(),
                registrations.clone(),
                cancelled.clone(),
            );
            let mut registered = registered.clone();
            workers.push(tokio::spawn(async move {
                let mut node: Option<Node> = None;
                let mut observer: Option<Arc<Adapter>> = None;
                let mut registration: Option<RegistrationNode> = None;
                loop {
                    if *cancelled.borrow() { break; }
                    let currently_registered = *registered.borrow() & (1 << id) != 0;
                    let observed = if currently_registered || registration.is_some() {
                        observe_registration(&device, &mut observer, id).await
                    } else { Ok(None) };
                    let observed = match observed {
                        Ok(snapshot) => {
                            if registration.as_ref().is_some_and(|n| snapshot.as_ref().is_none_or(|s| s.generation != n.generation())) {
                                registration.take().unwrap().remove(&connection, &registrations).await;
                            }
                            if let Some(snapshot) = snapshot {
                                if let Some(current) = registration.as_mut() {
                                    if let Err(error) = current.update(&connection, snapshot).await { warn!(%error, index=id, "registration notification failed"); }
                                } else {
                                    match RegistrationNode::create(&connection, &registrations, observer.as_ref().unwrap().clone(), snapshot).await {
                                        Ok(current) => registration = Some(current),
                                        Err(error) => warn!(%error, index=id, "registration publication failed"),
                                    }
                                }
                            }
                            snapshot
                        }
                        Err(error) => {
                            // An uncertain query is not an observed removal.
                            warn!(%error, index=id, "Core registration observation unavailable");
                            None
                        }
                    };
                    if let Some(current) = &node {
                        if let Err(error) = current.refresh().await {
                            warn!(%error, index=id, "adapter snapshot unavailable; removing registration");
                            node.take().unwrap().remove(&connection, &directory).await;
                        }
                    } else if let Some(observed) = observed.filter(|s| s.state == slk_protocol::REGISTRATION_INSTALLED)
                        && let Ok((adapter, snapshot)) = open_selected(device.clone(), id).await
                        && snapshot.generation == observed.generation {
                        match Node::create(&device, adapter, snapshot, config.clone(), &connection, &directory).await {
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
                if let Some(registration) = registration { registration.remove(&connection, &registrations).await; }
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
    invalidate_interface_properties(c, path, "org.sparklink.Adapter", names).await;
}

pub(crate) async fn invalidate_connection_properties(
    c: &zbus::Connection,
    path: &str,
    names: &[&str],
) {
    invalidate_interface_properties(c, path, "org.sparklink.Connection", names).await;
}
pub(crate) async fn invalidate_peer_properties(c: &zbus::Connection, path: &str, names: &[&str]) {
    invalidate_interface_properties(c, path, "org.sparklink.Peer", names).await;
}
async fn invalidate_interface_properties(
    c: &zbus::Connection,
    path: &str,
    interface: &str,
    names: &[&str],
) {
    let changed: std::collections::HashMap<&str, zbus::zvariant::Value<'_>> = Default::default();
    if let Err(error) = c
        .emit_signal(
            None::<&str>,
            path,
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            &(interface, changed, names),
        )
        .await
    {
        warn!(%error,%path,%interface,"property invalidation failed");
    }
}

#[cfg(test)]
fn experimental_profiles(_adapter: &Adapter, _profile: u32) -> ProfileRegistry {
    ProfileRegistry::new()
}

#[cfg(test)]
mod retired_interface_tests {
    use super::*;

    /// Actual Node::remove and connection-owned initializer on a private bus.
    /// /dev/null, no lease/event task, and a finite failed initializer are
    /// explicit dependencies: this is not Native/USB or callback-drain proof.
    #[tokio::test]
    async fn controller_retirement_joins_unpublished_and_retiring_initializers() {
        use crate::connection_object::{ConnectionIface, ConnectionOwner, Registration};
        use std::sync::atomic::{AtomicBool, Ordering};

        for already_retiring in [false, true] {
            let bus = crate::event_loop::tests::PrivateBus::start();
            let server = zbus::connection::Builder::address(bus.address.as_str())
                .unwrap()
                .build()
                .await
                .unwrap();
            let directory = AdapterDirectory::default();
            let mut states = Vec::new();
            for (index, generation) in [(2, 7), (3, 8)] {
                let mut state = AdapterState::new(
                    Adapter::open("/dev/null").unwrap(),
                    DaemonConfig::default(),
                    crate::bonding::BondingStore::new(
                        &std::env::temp_dir(),
                        "controller-retirement-fixture",
                    ),
                    ProfileRegistry::new(),
                );
                state.controller.dev_index = index;
                state.controller.generation = generation;
                state.object_path = format!("/org/sparklink/slk{index}_g{generation}");
                let state = Arc::new(Mutex::new(state));
                let (path, adapter) = {
                    let state = state.lock().await;
                    (state.object_path.clone(), state.adapter.clone())
                };
                publish(&server, &path, &state).await.unwrap();
                directory.lock().await.insert(
                    path,
                    AdapterRegistration {
                        adapter,
                        generation,
                    },
                );
                states.push(state);
            }
            let state = states[0].clone();
            let path = state.lock().await.object_path.clone();
            let other_path = states[1].lock().await.object_path.clone();
            let reference = slk_protocol::SleLinkInfo {
                lifetime: 11,
                handle: 4,
                ..Default::default()
            };
            let owner = ConnectionOwner::new(&state, 7, reference, 0);
            let entry = Registration {
                reference,
                path: crate::connection_object::path(&path, reference),
                published: already_retiring,
                owner: owner.clone(),
            };
            if already_retiring {
                server
                    .object_server()
                    .at(
                        entry.path.as_str(),
                        ConnectionIface::from_owner(state.clone(), owner.clone()).unwrap(),
                    )
                    .await
                    .unwrap();
            } else {
                state
                    .lock()
                    .await
                    .native_connection_objects
                    .insert(reference.lifetime, entry.clone());
            }
            let (entered, started) = tokio::sync::oneshot::channel();
            let (release, released) = tokio::sync::oneshot::channel();
            let caller = tokio::spawn({
                let owner = owner.clone();
                async move {
                    owner
                        .initialize_with_fixture(async move {
                            entered.send(()).unwrap();
                            tokio::time::timeout(Duration::from_secs(3), released)
                                .await
                                .expect("finite dependency release")
                                .unwrap();
                            Err("finite Native dependency failure; no Engine installed".into())
                        })
                        .await
                }
            });
            tokio::time::timeout(Duration::from_secs(1), started)
                .await
                .unwrap()
                .unwrap();
            caller.abort();
            assert!(caller.await.unwrap_err().is_cancelled());
            if already_retiring {
                owner.retire();
                state
                    .lock()
                    .await
                    .retiring_connection_objects
                    .insert(entry.path.clone(), entry.clone());
            }
            let (cancel, mut cancelled) = watch::channel(false);
            let node = Node {
                path: path.clone(),
                state: state.clone(),
                control: state.lock().await.adapter.clone(),
                lease: None,
                connection: server.clone(),
                event: None,
                init: tokio::spawn(async move { cancelled.changed().await.unwrap() }),
                cancel,
            };
            let mut retirement = tokio::spawn({
                let server = server.clone();
                let directory = directory.clone();
                async move { node.remove(&server, &directory).await }
            });
            assert!(
                tokio::time::timeout(Duration::from_millis(100), &mut retirement)
                    .await
                    .is_err(),
                "controller teardown must join the original owned initializer"
            );
            assert!(owner.is_retiring());
            assert!(!state.lock().await.present);
            assert!(!directory.lock().await.contains_key(&path));
            assert!(directory.lock().await.contains_key(&other_path));
            assert!(states[1].lock().await.present);
            assert_eq!(states[1].lock().await.controller.generation, 8);
            {
                let state = state.lock().await;
                assert_eq!(
                    state.native_connection_objects.len() + state.retiring_connection_objects.len(),
                    1,
                    "unjoined work must retain its controller resource root"
                );
            }
            let admitted = Arc::new(AtomicBool::new(false));
            let attempted = admitted.clone();
            assert!(
                owner
                    .initialize_with_fixture(async move {
                        attempted.store(true, Ordering::SeqCst);
                        Err("retired dependency must not run".into())
                    })
                    .await
                    .is_err()
            );
            assert!(!admitted.load(Ordering::SeqCst));
            assert!(
                tokio::time::timeout(
                    Duration::from_secs(1),
                    server
                        .object_server()
                        .interface::<_, AdapterIface>(other_path.as_str()),
                )
                .await
                .unwrap()
                .is_ok(),
                "one controller's held teardown cannot remove the other's interface"
            );
            release.send(()).unwrap();
            tokio::time::timeout(Duration::from_secs(1), retirement)
                .await
                .unwrap()
                .unwrap();
            assert!(state.lock().await.native_connection_objects.is_empty());
            assert!(state.lock().await.retiring_connection_objects.is_empty());
            assert!(
                server
                    .object_server()
                    .interface::<_, AdapterIface>(path.as_str())
                    .await
                    .is_err()
            );
            assert!(
                server
                    .object_server()
                    .interface::<_, ConnectionIface>(entry.path.as_str())
                    .await
                    .is_err()
            );
            remove_interfaces(&server, &other_path).await;
        }
    }

    #[tokio::test]
    async fn actual_factory_publishes_only_current_interfaces() {
        let bus = crate::event_loop::tests::PrivateBus::start();
        let server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let client = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let state = Arc::new(Mutex::new(AdapterState::new(
            Adapter::open("/dev/null").unwrap(),
            DaemonConfig::default(),
            crate::bonding::BondingStore::new(&std::env::temp_dir(), "unused-retired-factory-test"),
            ProfileRegistry::new(),
        )));
        let path = "/org/sparklink/slk2_g3";
        publish(&server, path, &state).await.unwrap();
        let name = server.unique_name().unwrap().as_str();
        let adapter = zbus::Proxy::new(&client, name, path, "org.sparklink.Adapter")
            .await
            .unwrap();
        let xml = adapter.introspect().await.unwrap();
        for member in ["ConnectDevice", "DisconnectDevice", "Discovering"] {
            assert!(!xml.contains(&format!("name=\"{member}\"")));
        }
        for member in [
            "SubmitConnect",
            "SubmitDisconnectReference",
            "StartControllerScan",
            "ScanningState",
        ] {
            assert!(xml.contains(&format!("name=\"{member}\"")));
        }
        let old = zbus::Proxy::new(
            &client,
            name,
            format!("{path}/extadv"),
            "org.sparklink.ExtAdv",
        )
        .await
        .unwrap();
        assert!(old.introspect().await.is_err());
        let device_path = format!("{path}/peer_t00_010203040506");
        server
            .object_server()
            .at(
                device_path.as_str(),
                crate::connection_object::PeerIface::new(state, 3, 0, [1, 2, 3, 4, 5, 6]),
            )
            .await
            .unwrap();
        let device = zbus::Proxy::new(&client, name, device_path.as_str(), "org.sparklink.Peer")
            .await
            .unwrap();
        let xml = device.introspect().await.unwrap();
        for member in ["Connect", "Disconnect", "GetConnectionInfo"] {
            assert!(!xml.contains(&format!("name=\"{member}\"")));
        }
        assert!(xml.contains("name=\"ObservationValid\""));
    }
}
