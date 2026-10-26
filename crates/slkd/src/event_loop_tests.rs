use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use slk_native::{Adapter, Error};
use tokio::sync::{Mutex, mpsc, oneshot};
use tokio::time::timeout;

use super::*;
use crate::bonding::BondingStore;
use crate::config::DaemonConfig;
use crate::controller::ControllerIface;
use crate::dbus_iface::AdapterIface;
use crate::profile::ProfileRegistry;
use crate::security::SecurityIface;
use crate::state::AdapterState;

pub(crate) struct PrivateBus {
    child: Child,
    pub(crate) address: String,
}

impl PrivateBus {
    pub(crate) fn start() -> Self {
        Self::with_config(None)
    }

    fn with_config(config: Option<&str>) -> Self {
        let executable =
            std::env::var_os("SPARKLINK_TEST_DBUS_DAEMON").unwrap_or_else(|| "dbus-daemon".into());
        let mut command = Command::new(executable);
        if let Some(config) = config {
            command.args(["--config-file", config]);
        } else {
            command.arg("--session");
        }
        let child = command
            .args(["--nofork", "--print-address=1"])
            .stdout(Stdio::piped())
            .spawn()
            .expect("dbus-daemon is required for the D-Bus regression");
        let mut bus = Self {
            child,
            address: String::new(),
        };
        let mut address = String::new();
        BufReader::new(bus.child.stdout.take().unwrap())
            .read_line(&mut address)
            .expect("read private bus address");
        assert!(!address.trim().is_empty());
        bus.address = address.trim().into();
        bus
    }
}

impl Drop for PrivateBus {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

struct SilentSource {
    events: mpsc::Receiver<Event>,
    entered: Option<oneshot::Sender<()>>,
    dropped: Option<oneshot::Sender<()>>,
}

impl EventSource for SilentSource {
    async fn next_event(&mut self) -> Result<Event> {
        if let Some(entered) = self.entered.take() {
            let _ = entered.send(());
        }
        self.events
            .recv()
            .await
            .ok_or(Error::InvalidParam("test source closed"))
    }
}

impl Drop for SilentSource {
    fn drop(&mut self) {
        if let Some(dropped) = self.dropped.take() {
            let _ = dropped.send(());
        }
    }
}

fn state() -> SharedState {
    state_with_profiles(ProfileRegistry::new())
}

fn state_with_profiles(profiles: ProfileRegistry) -> SharedState {
    Arc::new(Mutex::new(AdapterState::new(
        Adapter::open("/dev/null").unwrap(),
        DaemonConfig::default(),
        BondingStore::new(&std::env::temp_dir(), "unused-event-loop-test"),
        profiles,
    )))
}

async fn server(bus: &PrivateBus, state: SharedState) -> zbus::Connection {
    zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink/slk0", AdapterIface::new(state.clone()))
        .unwrap()
        .serve_at(
            "/org/sparklink/slk0/security",
            SecurityIface::new(state.clone()),
        )
        .unwrap()
        .serve_at(
            "/org/sparklink/slk0/controller",
            ControllerIface::new(state),
        )
        .unwrap()
        .build()
        .await
        .unwrap()
}

async fn client(bus: &PrivateBus) -> zbus::Connection {
    zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap()
}

async fn adapter_proxy(client: &zbus::Connection) -> zbus::Proxy<'_> {
    zbus::Proxy::new(
        client,
        "org.sparklink",
        "/org/sparklink/slk0",
        "org.sparklink.Adapter",
    )
    .await
    .unwrap()
}

fn source() -> (
    SilentSource,
    mpsc::Sender<Event>,
    oneshot::Receiver<()>,
    oneshot::Receiver<()>,
) {
    let (events, rx) = mpsc::channel(8);
    let (entered, entered_rx) = oneshot::channel();
    let (dropped, dropped_rx) = oneshot::channel();
    (
        SilentSource {
            events: rx,
            entered: Some(entered),
            dropped: Some(dropped),
        },
        events,
        entered_rx,
        dropped_rx,
    )
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn old_locked_wait_reproduces_dbus_starvation() {
    let bus = PrivateBus::start();
    let state = state();
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let proxy = adapter_proxy(&client).await;
    let (mut source, _events, entered, dropped) = source();
    let waiter = tokio::spawn(async move {
        // Reproduce the removed production pattern, using the same state lock
        // and a genuinely pending event receive rather than a polling timeout.
        let _state = state.lock().await;
        let _ = source.next_event().await;
    });
    entered.await.unwrap();
    assert!(
        timeout(
            Duration::from_millis(250),
            proxy.get_property::<String>("Name")
        )
        .await
        .is_err()
    );
    waiter.abort();
    assert!(waiter.await.unwrap_err().is_cancelled());
    dropped.await.unwrap();
    assert!(
        timeout(Duration::from_secs(2), proxy.get_property::<String>("Name"))
            .await
            .unwrap()
            .is_ok()
    );
    drop(server);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn silent_30s_dbus_requests_and_event_dispatch_do_not_share_wait_lock() {
    let bus = PrivateBus::start();
    let state = state();
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let proxy = adapter_proxy(&client).await;
    let controller = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/controller",
        "org.sparklink.Controller",
    )
    .await
    .unwrap();
    let (source, events, entered, dropped) = source();
    let task = EventTask::start(source, state.clone(), server.clone());
    entered.await.unwrap();
    // The retired entry remains a negative contract check, not evidence that
    // the current connection handler acquired SharedState during silence.
    let retired = timeout(
        Duration::from_secs(2),
        proxy.call::<_, _, ()>("ConnectDevice", &("01:02:03:04:05:06",)),
    )
    .await
    .unwrap()
    .unwrap_err();
    assert!(matches!(retired, zbus::Error::MethodError(name, _, _)
        if name.as_str() == "org.freedesktop.DBus.Error.UnknownMethod"));
    let quiet = Instant::now();
    while quiet.elapsed() < Duration::from_secs(30) {
        let name = timeout(Duration::from_secs(2), proxy.get_property::<String>("Name"))
            .await
            .unwrap()
            .unwrap();
        assert!(!name.is_empty());
        let (info, scan, connect) = tokio::join!(
            timeout(
                Duration::from_secs(2),
                controller.call_method("GetLinkSummary", &())
            ),
            timeout(
                Duration::from_secs(2),
                proxy.call::<_, _, ()>("StartControllerScan", &())
            ),
            timeout(
                Duration::from_secs(2),
                proxy.call::<_, _, ()>("ConnectDeviceTyped", &("01:02:03:04:05:06", 0_u8),)
            ),
        );
        // /dev/null is intentionally not a fake successful controller. A real
        // method error proves the handler ran; a timeout or transport error does not.
        for (result, expected, expected_detail) in [
            (
                info.map(|r| r.map(|_| ())),
                "org.freedesktop.DBus.Error.NotSupported",
                None,
            ),
            (scan, "org.freedesktop.DBus.Error.NotSupported", None),
            (
                connect,
                "org.freedesktop.DBus.Error.Failed",
                Some("management unavailable"),
            ),
        ] {
            match result.unwrap().unwrap_err() {
                zbus::Error::MethodError(name, detail, _) => {
                    assert_eq!(name.as_str(), expected);
                    if let Some(expected_detail) = expected_detail {
                        assert_eq!(detail.as_deref(), Some(expected_detail));
                    }
                }
                error => panic!("unexpected D-Bus error: {error}"),
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    events
        .send(Event::AdvReport {
            addr: [1, 2, 3, 4, 5, 6],
            rssi: -40,
            discovery_level: 1,
            name: "event-after-silence".into(),
            adv_data: vec![],
        })
        .await
        .unwrap();
    let path = "/org/sparklink/slk0/peer_t00_010203040506";
    timeout(Duration::from_secs(2), async {
        loop {
            if let Ok(device) =
                zbus::Proxy::new(&client, "org.sparklink", path, "org.sparklink.Peer").await
                && device
                    .call::<_, _, slk_contract::PeerObservation>("GetObservation", &())
                    .await
                    .is_ok_and(|o| o.3 && o.4 && o.5 == -40)
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(state.lock().await.peers.len(), 1);
    // The receiver is once again blocked, but shutdown must join and drop it.
    timeout(Duration::from_secs(2), task.shutdown())
        .await
        .unwrap()
        .unwrap();
    dropped.await.unwrap();
    assert!(
        timeout(Duration::from_secs(2), proxy.get_property::<String>("Name"))
            .await
            .unwrap()
            .is_ok()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_with_business_state_locked() {
    let bus = PrivateBus::start();
    let state = state();
    let server = server(&bus, state.clone()).await;
    let (source, events, entered, dropped) = source();
    let task = EventTask::start(source, state.clone(), server);
    entered.await.unwrap();
    let lock = state.lock().await;
    events
        .send(Event::AdvReport {
            addr: [1; 6],
            rssi: -10,
            discovery_level: 1,
            name: "cancelled".into(),
            adv_data: vec![],
        })
        .await
        .unwrap();
    timeout(Duration::from_secs(2), task.shutdown())
        .await
        .unwrap()
        .unwrap();
    dropped.await.unwrap();
    assert!(lock.peers.is_empty());
}

/// Executes the same lock wait as Native retry, with a real owned socket as the
/// receiver-resource fixture. This is not a kernel event subscription or RF test.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn native_retry_pending_lock_cancel_joins_and_releases_owned_fd() {
    use tokio::io::AsyncReadExt;

    let state = state();
    let lock = state.lock().await;
    let (receiver_fd, mut peer) = tokio::net::UnixStream::pair().unwrap();
    let (cancel, mut cancelled) = oneshot::channel();
    let (entered, pending) = oneshot::channel();
    let task = tokio::spawn({
        let state = state.clone();
        async move {
            let _receiver_fd = receiver_fd;
            let mut wait = std::pin::pin!(native_retry_needed(&state, &mut cancelled));
            let mut entered = Some(entered);
            // Signal only after the actual production future returned Pending,
            // while the caller still owns the lock. No timing guess/barrier sleep.
            let result = std::future::poll_fn(|cx| {
                let result = wait.as_mut().poll(cx);
                if result.is_pending()
                    && let Some(entered) = entered.take()
                {
                    entered.send(()).unwrap();
                }
                result
            })
            .await;
            assert_eq!(result, None);
        }
    });
    let task = EventTask {
        cancel: Some(cancel),
        task: Some(task),
    };
    timeout(Duration::from_secs(2), pending)
        .await
        .unwrap()
        .unwrap();
    timeout(Duration::from_secs(2), task.shutdown())
        .await
        .expect("Native retry must cancel without releasing SharedState")
        .unwrap();
    assert_eq!(
        timeout(Duration::from_secs(1), peer.read(&mut [0; 1]))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert!(lock.peers.is_empty());
    assert!(
        state.try_lock().is_err(),
        "business lock remains held through join and fd closure"
    );
}

#[tokio::test]
async fn native_retry_cancel_precedes_ready_lock_and_sender_loss_stops() {
    let state = state();
    let (cancel, mut cancelled) = oneshot::channel();
    cancel.send(()).unwrap();
    assert_eq!(native_retry_needed(&state, &mut cancelled).await, None);
    let (cancel, mut cancelled) = oneshot::channel();
    drop(cancel);
    assert_eq!(native_retry_needed(&state, &mut cancelled).await, None);
    let (_cancel, mut cancelled) = oneshot::channel();
    assert_eq!(
        native_retry_needed(&state, &mut cancelled).await,
        Some(true)
    );
    assert!(
        state.try_lock().is_ok(),
        "snapshot releases the lock before refresh"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn blocked_bond_storage_does_not_block_dbus_adapter_or_event_shutdown() {
    let bus = PrivateBus::start();
    let state = state();
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let proxy = adapter_proxy(&client).await;
    let security = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/security",
        "org.sparklink.Security",
    )
    .await
    .unwrap();
    let (source, _events, entered, dropped) = source();
    let task = EventTask::start(source, state.clone(), server);
    entered.await.unwrap();
    let error = security
        .call::<_, _, ()>("RemoveBond", &("01:02:03:04:05:06",))
        .await
        .unwrap_err();
    assert!(
        matches!(error, zbus::Error::MethodError(ref name, _, _) if name.as_str() == "org.freedesktop.DBus.Error.UnknownMethod")
    );
    let bonding = state.lock().await.bonding.clone();
    let (storage_entered, storage_entered_rx) = oneshot::channel();
    let (release, release_rx) = std::sync::mpsc::channel();
    let writer_service = bonding.clone();
    let writer = tokio::spawn(async move {
        writer_service
            .run(move |_| {
                storage_entered.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                Ok(())
            })
            .await
    });
    storage_entered_rx.await.unwrap();
    let removal = bonding.remove([1, 2, 3, 4, 5, 6]);
    tokio::pin!(removal);
    assert!(
        timeout(Duration::from_millis(100), &mut removal)
            .await
            .is_err()
    );
    assert!(
        timeout(Duration::from_secs(2), proxy.get_property::<String>("Name"))
            .await
            .unwrap()
            .is_ok()
    );
    timeout(Duration::from_secs(2), task.shutdown())
        .await
        .unwrap()
        .unwrap();
    dropped.await.unwrap();
    release.send(()).unwrap();
    writer.await.unwrap().unwrap();
    timeout(Duration::from_secs(2), removal)
        .await
        .unwrap()
        .unwrap();
    bonding.shutdown().await;
}

#[tokio::test]
async fn legacy_pairing_metadata_requires_one_unambiguous_peer() {
    let state = state();
    assert!(pairing_record(&state, "PSK").await.is_none());
    state
        .lock()
        .await
        .on_conn_state_changed(1, slk_protocol::ConnState::Connected as u8, [1; 6]);
    let (_, addr, info) = pairing_record(&state, "PSK").await.unwrap();
    assert_eq!(addr, [1; 6]);
    assert_eq!(info.method, "PSK");
    state
        .lock()
        .await
        .on_conn_state_changed(2, slk_protocol::ConnState::Connected as u8, [2; 6]);
    assert!(pairing_record(&state, "PSK").await.is_none());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn blocked_profile_callback_leaves_state_and_dbus_responsive() {
    let bus = PrivateBus::start();
    let (profile, mut probe) = crate::profile_runtime::tests::blocking_profile();
    let mut registry = ProfileRegistry::new();
    registry.add(profile);
    let state = state_with_profiles(registry);
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let proxy = adapter_proxy(&client).await;
    let (source, events, entered, dropped) = source();
    let task = EventTask::start(source, state.clone(), server);
    entered.await.unwrap();
    events
        .send(Event::ConnectionStateChanged {
            handle: 5,
            state: slk_protocol::ConnState::Connected as u8,
            peer_addr: [5; 6],
        })
        .await
        .unwrap();
    timeout(Duration::from_secs(2), &mut probe.entered)
        .await
        .unwrap()
        .unwrap();
    assert!(
        timeout(Duration::from_secs(2), proxy.get_property::<String>("Name"))
            .await
            .unwrap()
            .is_ok()
    );
    let (profiles, bonding) = {
        let st = timeout(Duration::from_secs(2), state.lock()).await.unwrap();
        assert_eq!(st.peers[&(0, [5; 6])].conn_handle, Some(5));
        (st.profiles.clone(), st.bonding.clone())
    };
    // Historical callbacks must not publish a second, handle-only SSAP facade.
    let remote = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/conn_0005",
        "org.sparklink.RemoteService",
    )
    .await
    .unwrap();
    assert!(
        timeout(Duration::from_secs(2), remote.introspect())
            .await
            .unwrap()
            .is_err()
    );
    timeout(Duration::from_secs(2), task.shutdown())
        .await
        .unwrap()
        .unwrap();
    dropped.await.unwrap();
    let mut closing = Box::pin(profiles.shutdown());
    assert!(
        timeout(Duration::from_millis(50), &mut closing)
            .await
            .is_err()
    );
    probe.release();
    timeout(Duration::from_secs(2), closing).await.unwrap();
    assert_eq!(*probe.calls.lock().unwrap(), [(5, true)]);
    bonding.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn native_reports_preserve_identity_opaque_bytes_and_loss() {
    let bus = PrivateBus::start();
    let state = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 42,
        profile: 1,
        dev_index: 3,
        flags: 2,
        ..Default::default()
    };
    {
        let mut st = state.lock().await;
        st.controller = expected;
        st.object_path = "/org/sparklink/slk3_g42".into();
    }
    let connection = server(&bus, state.clone()).await;
    let mut event: slk_protocol::SleControllerEvent = unsafe { std::mem::zeroed() };
    event.generation = 42;
    event.profile = 1;
    event.dev_index = 3;
    event.seq = 9;
    event.event_code = 0x180b;
    event.lost = 8;
    event.payload_len = 278;
    event.payload[..23].copy_from_slice(&[
        0x87, 6, 1, 2, 3, 4, 5, 6, 4, 7, 8, 9, 10, 11, 12, 0, 1, 2, 3, 4, 5, 214, 255,
    ]);
    for (i, byte) in event.payload[23..278].iter_mut().enumerate() {
        *byte = i as u8;
    }
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    {
        let st = state.lock().await;
        assert_eq!(st.events_lost, 8);
        assert_eq!(st.native_reports.len(), 1);
        let report = &st.native_reports[0];
        assert_eq!(report.sequence, 9);
        assert_eq!(report.generation, 42);
        assert_eq!(report.address, [1, 2, 3, 4, 5, 6]);
        assert_eq!(report.rssi, -42);
        assert_eq!(report.header, event.payload[..23]);
        assert_eq!(report.data, event.payload[23..278]);
        // Raw evidence retains unsupported type 6; no public-address fallback.
        assert!(st.peers.is_empty());
        assert_eq!(st.observation_drops, 1);
    }
    event.payload[1] = 0;
    event.seq = 10;
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    {
        let st = state.lock().await;
        let peer = &st.peers[&(0, [1, 2, 3, 4, 5, 6])];
        assert_eq!(
            peer.object_path,
            "/org/sparklink/slk3_g42/peer_t00_010203040506"
        );
        assert_eq!(peer.sequence, 10);
        assert!(peer.name.is_empty() && peer.service_uuids.is_empty() && peer.tx_power.is_none());
    }
    event.generation = 43;
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    event.generation = 42;
    event.dev_index = 2;
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    event.dev_index = 3;
    event.profile = 2;
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    assert_eq!(state.lock().await.native_reports.len(), 2);
    {
        state.lock().await.present = false;
    }
    event.profile = 1;
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    assert_eq!(state.lock().await.native_reports.len(), 2);
    let (bonding, profiles) = {
        let st = state.lock().await;
        (st.bonding.clone(), st.profiles.clone())
    };
    tokio::join!(bonding.shutdown(), profiles.shutdown());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ready_property_cache_observes_host_transition() {
    let bus = PrivateBus::start();
    let state = state();
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let proxy = adapter_proxy(&client).await;
    assert!(!proxy.get_property::<bool>("Ready").await.unwrap());
    state.lock().await.controller.flags = slk_protocol::CONTROLLER_READY;
    crate::adapters::invalidate_properties(
        &server,
        "/org/sparklink/slk0",
        &["Ready", "ControllerState"],
    )
    .await;
    timeout(Duration::from_secs(2), async {
        loop {
            if proxy.get_property::<bool>("Ready").await.unwrap() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("cached Ready must follow property invalidation");
    let (bonding, profiles) = {
        let st = state.lock().await;
        (st.bonding.clone(), st.profiles.clone())
    };
    tokio::join!(bonding.shutdown(), profiles.shutdown());
}

async fn property_eventually(proxy: &zbus::Proxy<'_>, name: &str, value: bool) {
    timeout(Duration::from_secs(1), async {
        loop {
            if proxy.get_property::<bool>(name).await.unwrap() == value {
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
}

// Offline canonical ioctl dependency fixtures. Raw event payloads deliberately
// disagree with tables: production properties must follow the snapshot only.
fn native_table(
    sequence: u64,
    revision: u64,
    links: &[(u64, u16, u8, u8, [u8; 6])],
) -> slk_protocol::SleLinkSnapshot {
    let mut table = slk_protocol::SleLinkSnapshot {
        version: 1,
        profile: 1,
        generation: 7,
        event_seq: sequence,
        revision,
        flags: 1,
        count: links.len() as u32,
        ..Default::default()
    };
    for (slot, &(lifetime, handle, role, address_type, address)) in
        table.links.iter_mut().zip(links)
    {
        *slot = slk_protocol::SleLinkInfo {
            lifetime,
            handle,
            role,
            address_type,
            address,
            ..Default::default()
        };
    }
    table
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn canonical_startup_loss_resync_and_barrier_preserve_reused_handle_peer() {
    let bus = PrivateBus::start();
    let state = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    state.lock().await.controller = expected;
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let address = [1, 2, 3, 4, 5, 6];
    let original = native_table(10, 1, &[(1, 0, 0, 0, address)]);
    reconcile_native(&state, &server, expected, 0, Ok(original)).await;
    let path = state.lock().await.peers[&(0, address)].object_path.clone();
    let device = zbus::Proxy::new(
        &client,
        "org.sparklink",
        path.as_str(),
        "org.sparklink.Peer",
    )
    .await
    .unwrap();
    assert!(device.get_property::<bool>("Connected").await.unwrap());
    assert!(
        device
            .get_property::<bool>("ConnectionKnown")
            .await
            .unwrap()
    );
    assert!(!device.get_property::<bool>("RssiKnown").await.unwrap());
    let remote = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/conn_0000",
        "org.sparklink.RemoteService",
    )
    .await
    .unwrap();
    assert!(remote.introspect().await.is_err());
    let old_down = slk_protocol::SleControllerEvent {
        generation: 7,
        profile: 1,
        seq: 9,
        event_code: 5,
        ..Default::default()
    };
    dispatch_native_with(Ok(old_down), &state, &server, expected, || async {
        panic!("barrier-covered event must not query or mutate")
    })
    .await;
    assert!(device.get_property::<bool>("Connected").await.unwrap());
    let lost = slk_protocol::SleControllerEvent {
        generation: 7,
        profile: 1,
        seq: 12,
        event_code: 0x1801,
        lost: 2,
        ..Default::default()
    };
    dispatch_native_with(Ok(lost), &state, &server, expected, || async {
        Err(zbus::fdo::Error::Failed("offline query failure".into()))
    })
    .await;
    property_eventually(&device, "ConnectionKnown", false).await;
    assert_eq!(state.lock().await.native_link_barrier, 10);
    assert_eq!(state.lock().await.events_lost, 2);
    let adapter = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0",
        "org.sparklink.Adapter",
    )
    .await
    .unwrap();
    assert_eq!(
        adapter
            .get_property::<(u64, u64, bool)>("NativeLinkObservation")
            .await
            .unwrap(),
        (10, 1, false)
    );
    // A retry obtains a new lifetime with the same handle, after an omitted Down.
    let replacement = native_table(20, 3, &[(3, 0, 1, 1, address)]);
    reconcile_native(&state, &server, expected, 12, Ok(replacement)).await;
    // A typed Peer is not an address-only alias for the replacement type.
    assert!(device.introspect().await.is_err());
    let replacement_peer_path = state.lock().await.peers[&(1, address)].object_path.clone();
    assert_ne!(replacement_peer_path, path);
    let replacement_peer = zbus::Proxy::new(
        &client,
        "org.sparklink",
        replacement_peer_path,
        "org.sparklink.Peer",
    )
    .await
    .unwrap();
    assert!(
        replacement_peer
            .get_property::<bool>("Connected")
            .await
            .unwrap()
    );
    assert!(
        replacement_peer
            .get_property::<bool>("ConnectionKnown")
            .await
            .unwrap()
    );
    let mut stale_down = old_down;
    stale_down.seq = 19;
    dispatch_native_with(Ok(stale_down), &state, &server, expected, || async {
        panic!("old Down must not erase replacement lifetime")
    })
    .await;
    assert_eq!(
        state.lock().await.native_links.unwrap().links[0],
        replacement.links[0]
    );
    let current = slk_protocol::SleControllerEvent {
        seq: 21,
        ..stale_down
    };
    dispatch_native_with(Ok(current), &state, &server, expected, || async {
        Ok(native_table(21, 4, &[]))
    })
    .await;
    assert!(replacement_peer.introspect().await.is_err());
    assert_eq!(
        state.lock().await.peer_connection(&(1, address)),
        (true, false)
    );
    // Successful loss resync restores Known; author success is never consulted.
    let lost = slk_protocol::SleControllerEvent {
        seq: 25,
        lost: 1,
        ..lost
    };
    dispatch_native_with(Ok(lost), &state, &server, expected, || async {
        Ok(native_table(30, 5, &[(5, 7, 0, 0, address)]))
    })
    .await;
    // The same type/address may be observed again, but the old physical
    // Connection object's lifetime remains retired and is never rebound.
    let info: crate::connection_object::PeerInfo = device.call("GetInfo", &()).await.unwrap();
    assert!(info.3 && info.4);
    assert!(info.5.iter().all(|p| p.ends_with("/link_0000000000000005")));
    assert_eq!(state.lock().await.native_link_barrier, 30);
    assert_eq!(
        adapter
            .get_property::<(u64, u64, bool)>("NativeLinkObservation")
            .await
            .unwrap(),
        (30, 5, true)
    );
}

#[tokio::test]
async fn canonical_state_rejects_identity_rollback_and_separates_address_types_without_losing_rssi()
{
    let state = state();
    let address = [1; 6];
    let mut st = state.lock().await;
    st.controller = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    assert!(!st.native_links_known());
    st.on_adv_report(address, -45, 0, String::new(), vec![1, 2]);
    st.apply_native_links(
        native_table(20, 2, &[(1, 4, 0, 0, address), (2, 5, 1, 1, address)]),
        0,
    )
    .unwrap();
    assert_eq!(st.peer_connection(&(0, address)), (true, true));
    assert_eq!(st.peer_connection(&(1, address)), (true, true));
    assert_eq!(
        (
            st.peers[&(0, address)].rssi,
            st.peers[&(0, address)].adv_data.clone()
        ),
        (-45, vec![1, 2])
    );
    for field in ["generation", "index", "profile", "seq", "revision", "tail"] {
        let mut bad = native_table(21, 3, &[(3, 6, 0, 0, address)]);
        match field {
            "generation" => bad.generation = 8,
            "index" => bad.dev_index = 1,
            "profile" => bad.profile = 0,
            "seq" => bad.event_seq = 19,
            "revision" => bad.revision = 1,
            "tail" => bad.links[1].lifetime = 2,
            _ => unreachable!(),
        }
        assert!(st.apply_native_links(bad, 20).is_err(), "{field}");
        assert_eq!(st.peer_connection(&(0, address)), (false, false));
        assert_eq!(st.native_link_barrier, 20);
    }
    st.apply_native_links(native_table(22, 3, &[]), 20).unwrap();
    assert_eq!(st.peer_connection(&(0, address)), (true, false));
    st.present = false;
    assert_eq!(st.peer_connection(&(0, address)), (false, false));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn typed_connection_objects_separate_types_retire_lifetimes_and_preserve_unknown() {
    let bus = PrivateBus::start();
    let state = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    state.lock().await.controller = expected;
    let server = server(&bus, state.clone()).await;
    let client = client(&bus).await;
    let address = [1; 6];
    let table = native_table(10, 2, &[(1, 7, 0, 0, address), (2, 8, 1, 1, address)]);
    reconcile_native(&state, &server, expected, 0, Ok(table)).await;
    let paths = state
        .lock()
        .await
        .native_connection_objects
        .values()
        .map(|entry| entry.path.clone())
        .collect::<Vec<_>>();
    assert_ne!(paths[0], paths[1]);
    assert!(paths[0].contains("/peer_t00_"));
    assert!(paths[1].contains("/peer_t01_"));
    assert_eq!(
        state.lock().await.peer_connection(&(0, address)),
        (true, true)
    );
    assert_eq!(
        state.lock().await.peer_connection(&(1, address)),
        (true, true)
    );
    let mut objects = Vec::new();
    let mut peers = Vec::new();
    for (n, path) in paths.iter().enumerate() {
        let proxy = zbus::Proxy::new(
            &client,
            "org.sparklink",
            path.as_str(),
            "org.sparklink.Connection",
        )
        .await
        .unwrap();
        let info: crate::connection_object::Info = proxy.call("GetInfo", &()).await.unwrap();
        assert_eq!(
            (info.0, info.1, info.2, info.3, info.4, info.6, info.7),
            (7, n as u64 + 1, 7 + n as u16, n as u8, n as u8, true, true)
        );
        objects.push(proxy);
        let peer_path = path.rsplit_once("/link_").unwrap().0;
        let peer = zbus::Proxy::new(&client, "org.sparklink", peer_path, "org.sparklink.Peer")
            .await
            .unwrap();
        let info: crate::connection_object::PeerInfo = peer.call("GetInfo", &()).await.unwrap();
        assert_eq!(
            (info.0, info.1, info.3, info.4, info.5),
            (7, n as u8, true, true, vec![path.clone()])
        );
        peers.push(peer);
    }
    reconcile_native(
        &state,
        &server,
        expected,
        11,
        Err(zbus::fdo::Error::Failed("offline read failure".into())),
    )
    .await;
    for proxy in &objects {
        let info: crate::connection_object::Info = proxy.call("GetInfo", &()).await.unwrap();
        assert!(!info.6 && !info.7);
    }
    for peer in &peers {
        let info: crate::connection_object::PeerInfo = peer.call("GetInfo", &()).await.unwrap();
        assert!(!info.3 && !info.4);
    }
    assert_eq!(state.lock().await.native_connection_objects.len(), 2);
    // An unchanged lifetime may never rebind its immutable role/handle/type.
    let changed = native_table(12, 2, &[(1, 9, 1, 0, address), (2, 8, 1, 1, address)]);
    reconcile_native(&state, &server, expected, 12, Ok(changed)).await;
    assert!(!state.lock().await.native_links_known());
    let info: crate::connection_object::Info = objects[0].call("GetInfo", &()).await.unwrap();
    assert_eq!((info.2, info.3, info.4), (7, 0, 0));
    reconcile_native(&state, &server, expected, 13, Ok(native_table(13, 3, &[]))).await;
    for proxy in &objects {
        assert!(proxy.introspect().await.is_err());
        assert!(
            proxy
                .call::<_, _, ()>("SubmitDisconnect", &(99u64,))
                .await
                .is_err()
        );
    }
    assert!(state.lock().await.native_connection_objects.is_empty());
    assert!(state.lock().await.retiring_connection_objects.is_empty());
    for peer in &peers {
        assert!(
            peer.call::<_, _, crate::connection_object::PeerInfo>("GetInfo", &())
                .await
                .is_err()
        );
    }
    assert!(state.lock().await.peers.is_empty());
    let reused = native_table(14, 4, &[(4, 7, 0, 0, address)]);
    reconcile_native(&state, &server, expected, 14, Ok(reused)).await;
    let current = state.lock().await.native_connection_objects[&4]
        .path
        .clone();
    assert!(!paths.contains(&current));
    assert!(objects[0].introspect().await.is_err());
    let replacement = zbus::Proxy::new(
        &client,
        "org.sparklink",
        current.as_str(),
        "org.sparklink.Connection",
    )
    .await
    .unwrap();
    let info: crate::connection_object::Info = replacement.call("GetInfo", &()).await.unwrap();
    assert_eq!((info.1, info.2, info.6, info.7), (4, 7, true, true));
    state.lock().await.present = false;
    let info: crate::connection_object::Info = replacement.call("GetInfo", &()).await.unwrap();
    assert!(!info.6 && !info.7);
    assert!(
        replacement
            .call::<_, _, ()>("SubmitDisconnect", &(100u64,))
            .await
            .is_err()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unconnected_security_and_privacy_report_not_supported_over_dbus() {
    let bus = PrivateBus::start();
    let state = state(); // /dev/null: reaching the old ioctl would fail differently.
    let _server = server(&bus, state).await;
    let client = client(&bus).await;
    let security = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/security",
        "org.sparklink.Security",
    )
    .await
    .unwrap();
    let controller = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/controller",
        "org.sparklink.Controller",
    )
    .await
    .unwrap();
    fn error_name<T: std::fmt::Debug>(result: zbus::Result<T>, expected: &str) {
        match result.unwrap_err() {
            zbus::Error::MethodError(name, _, _) => assert_eq!(name.as_str(), expected),
            zbus::Error::FDO(error) => match *error {
                zbus::fdo::Error::NotSupported(_) => {
                    assert_eq!(expected, "org.freedesktop.DBus.Error.NotSupported")
                }
                zbus::fdo::Error::InvalidArgs(_) => {
                    assert_eq!(expected, "org.freedesktop.DBus.Error.InvalidArgs")
                }
                zbus::fdo::Error::UnknownProperty(_) => {
                    assert_eq!(expected, "org.freedesktop.DBus.Error.UnknownProperty");
                }
                zbus::fdo::Error::UnknownMethod(_) => {
                    assert_eq!(expected, "org.freedesktop.DBus.Error.UnknownMethod");
                }
                other => panic!("unexpected property error: {other}"),
            },
            other => panic!("unexpected D-Bus error: {other}"),
        }
    }
    let retired_method = "org.freedesktop.DBus.Error.UnknownMethod";
    for method in ["Encrypt", "ConfirmPasskey", "RejectPasskey", "Reset"] {
        error_name(security.call::<_, _, ()>(method, &()).await, retired_method);
    }
    error_name(
        security
            .call::<_, _, (String, String, u8, bool)>("GetInfo", &())
            .await,
        retired_method,
    );
    error_name(
        security.call::<_, _, u32>("GetPasskey", &()).await,
        retired_method,
    );
    error_name(
        security
            .call::<_, _, ()>("SetPsk", &("a1".repeat(16),))
            .await,
        retired_method,
    );
    error_name(
        security.call::<_, _, ()>("Pair", &("psk",)).await,
        retired_method,
    );
    error_name(
        security
            .call::<_, _, ()>("InputPasskey", &(123456u32,))
            .await,
        retired_method,
    );
    for property in ["Encrypted", "Paired"] {
        error_name(
            security.get_property::<bool>(property).await,
            "org.freedesktop.DBus.Error.UnknownProperty",
        );
    }
    let xml = controller.introspect().await.unwrap();
    for name in ["GetLinkSummary", "GetControllerEventPosition", "ConnCount"] {
        assert!(xml.contains(&format!("name=\"{name}\"")));
    }
    for method in [
        "GetRole",
        "SetRole",
        "GetPhyInfo",
        "SetMcs",
        "SetTxPower",
        "SetBandwidth",
        "McsSelect",
        "PhyHopNext",
        "GetPmInfo",
        "PmSetState",
        "PmForceActive",
        "AfhSetMap",
        "AfhGetMap",
        "AfhHopNext",
        "AfhClassify",
        "ConnReadPeerFeatures",
        "ConnReadPeerVersion",
        "ConnUpdateParams",
        "ConnPhyUpdate",
        "GetDliInfo",
        "DliReset",
        "GetMgmtStats",
        "RalAdd",
        "RalRemove",
        "RalClear",
        "RalSize",
        "RpaEnable",
        "RpaSetTimeout",
        "RalReadPeerRpa",
        "RalReadLocalRpa",
        "MeasReadCap",
        "MeasEnable",
        "MeasSetLinkParam",
        "MeasAction",
        "SyncUcastRemove",
        "SyncMcastRemove",
        "SyncInfo",
        "UsbDevCount",
    ] {
        assert!(!xml.contains(&format!("name=\"{method}\"")));
        error_name(
            controller.call::<_, _, ()>(method, &()).await,
            retired_method,
        );
    }
    error_name(
        security
            .call::<_, _, ()>("InputPasskey", &(1_000_000u32,))
            .await,
        retired_method,
    );
    error_name(
        security.call::<_, _, ()>("SetPsk", &("bad",)).await,
        retired_method,
    );
    error_name(
        security.call::<_, _, ()>("Pair", &("invalid",)).await,
        retired_method,
    );
    error_name(
        controller
            .call::<_, _, ()>("RalRemove", &(vec![1u8; 5],))
            .await,
        retired_method,
    );
}

#[tokio::test]
async fn actual_ssap_receive_scope_cancels_on_private_bus_caller_death() {
    let bus = PrivateBus::start();
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let caller = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let peer = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let name = caller.unique_name().unwrap().to_string();
    let name_for_task = name.clone();
    let (entered, entry) = oneshot::channel();
    let (delivery, pending) = oneshot::channel::<()>();
    let server_task = server.clone();
    let task = tokio::spawn(async move {
        crate::connection_object::caller_scoped(&server_task, &name_for_task, async move {
            let _ = entered.send(());
            pending
                .await
                .map_err(|_| zbus::fdo::Error::Failed("delivery stopped".into()))
        })
        .await
    });
    timeout(Duration::from_secs(1), entry)
        .await
        .unwrap()
        .unwrap();
    caller.close().await.unwrap();
    let result = timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    assert!(result.is_err());
    assert!(delivery.is_closed());
    let proxy = zbus::fdo::DBusProxy::new(&server).await.unwrap();
    assert!(
        proxy
            .name_has_owner(peer.unique_name().unwrap().clone().into())
            .await
            .unwrap()
    );
    assert!(
        crate::connection_object::caller_scoped(&server, &name, async { Ok(()) })
            .await
            .is_err()
    );
    assert_eq!(
        crate::connection_object::caller_scoped(
            &server,
            peer.unique_name().unwrap().as_str(),
            async { Ok(7) }
        )
        .await
        .unwrap(),
        7
    );
}

/// Actual production D-Bus export, with /dev/null and a private bus as explicit
/// fixtures: no controller state, deployed policy, kernel or RF qualification.
#[tokio::test]
async fn retired_power_and_metadata_bond_interfaces_are_absent() {
    let bus = PrivateBus::start();
    let shared = state();
    let server = server(&bus, shared.clone()).await;
    let client = client(&bus).await;
    let adapter = adapter_proxy(&client).await;
    let properties = zbus::fdo::PropertiesProxy::builder(&client)
        .destination("org.sparklink")
        .unwrap()
        .path("/org/sparklink/slk0")
        .unwrap()
        .build()
        .await
        .unwrap();
    let all = properties
        .get_all("org.sparklink.Adapter".try_into().unwrap())
        .await
        .unwrap();
    assert!(!all.contains_key("Powered"));
    assert!(
        adapter
            .get_property::<bool>("Powered")
            .await
            .unwrap_err()
            .to_string()
            .contains("UnknownProperty")
    );
    let err = properties
        .set(
            "org.sparklink.Adapter".try_into().unwrap(),
            "Powered",
            zbus::zvariant::Value::Bool(false),
        )
        .await
        .unwrap_err();
    assert!(err.to_string().contains("UnknownProperty"));
    let security = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/security",
        "org.sparklink.Security",
    )
    .await
    .unwrap();
    let err = security
        .call::<_, _, Vec<String>>("ListBonded", &())
        .await
        .unwrap_err();
    assert!(
        matches!(err, zbus::Error::MethodError(ref name, _, _) if name.as_str() == "org.freedesktop.DBus.Error.UnknownMethod")
    );
    let err = security
        .call::<_, _, ()>("RemoveBond", &("01:02:03:04:05:06",))
        .await
        .unwrap_err();
    assert!(
        matches!(err, zbus::Error::MethodError(ref name, _, _) if name.as_str() == "org.freedesktop.DBus.Error.UnknownMethod")
    );
    let introspection = zbus::fdo::IntrospectableProxy::builder(&client)
        .destination("org.sparklink")
        .unwrap()
        .path("/org/sparklink/slk0")
        .unwrap()
        .build()
        .await
        .unwrap()
        .introspect()
        .await
        .unwrap();
    assert!(!introspection.contains("name=\"Powered\""));
    assert!(
        !shared
            .lock()
            .await
            .controller
            .flags
            .eq(&slk_protocol::CONTROLLER_READY)
    );
    drop(server);
}

// Observation tests invoke the actual production cache and ObjectServer paths.
// /dev/null, private bus and manual observation age are explicit fixtures;
// they do not establish kernel/RF timing, physical links or controller Ready.
fn observation_address(n: u16) -> slk_protocol::SleAddr {
    let b = n.to_le_bytes();
    [b[0], b[1], 1, 2, 3, 4]
}

#[tokio::test]
async fn observation_count_bytes_failure_atomicity_and_connection_insertion_are_bounded() {
    use crate::state::{OBSERVATION_MAX_BYTES, OBSERVATION_MAX_ENTRIES};
    let shared = state();
    let mut st = shared.lock().await;
    for n in 0..OBSERVATION_MAX_ENTRIES as u16 {
        assert!(st.on_adv_report(observation_address(n), -3, 0, String::new(), vec![1]));
    }
    assert!(!st.on_adv_report(observation_address(400), -3, 0, String::new(), vec![1]));
    assert_eq!(st.peers.len(), OBSERVATION_MAX_ENTRIES);
    assert!(st.observation_bytes() <= OBSERVATION_MAX_BYTES);
    assert_eq!(st.observation_drops, 1);
    st.on_conn_state_changed(
        7,
        slk_protocol::ConnState::Connected as u8,
        observation_address(401),
    );
    assert!(!st.peers.contains_key(&(0, observation_address(401))));
    assert_eq!(st.observation_drops, 2);
    drop(st);
    let shared = state();
    let mut st = shared.lock().await;
    st.controller.profile = 1; // Opaque data; no legacy advertisement interpretation.
    for n in 0..128 {
        st.on_adv_report(observation_address(n), -5, 0, "name".into(), vec![1; 2048]);
    }
    assert!(st.peers.len() < OBSERVATION_MAX_ENTRIES);
    assert!(st.observation_bytes() <= OBSERVATION_MAX_BYTES && st.observation_drops > 0);
    let before = st.peers.len();
    assert!(!st.on_adv_report(
        observation_address(900),
        -9,
        0,
        String::new(),
        vec![0; 2049]
    ));
    assert!(!st.on_adv_report(observation_address(901), -9, 0, "n".repeat(257), Vec::new()));
    assert_eq!(st.peers.len(), before);
    // An existing observation must not be partly overwritten on rejection.
    let shared = state();
    let mut st = shared.lock().await;
    let a = observation_address(1);
    st.on_adv_report(a, -15, 0, "first".into(), vec![1]);
    let old = st.peers[&(0, a)].clone();
    assert!(!st.on_adv_report(a, -20, 0, "replacement".into(), vec![0; 2049]));
    assert_eq!(
        (
            st.peers[&(0, a)].name.as_str(),
            st.peers[&(0, a)].rssi,
            st.peers[&(0, a)].observed_at
        ),
        (old.name.as_str(), old.rssi, old.observed_at)
    );
}

#[tokio::test]
async fn observation_ttl_and_retry_cursor_do_not_free_or_starve_slots() {
    use crate::state::{OBSERVATION_TTL, OBSERVATION_WORK_BUDGET, PeerPublication};
    let shared = state();
    let mut st = shared.lock().await;
    for n in 0..20 {
        st.on_adv_report(observation_address(n), -1, 0, String::new(), Vec::new());
    }
    let first = st.observation_work();
    assert_eq!(first.len(), OBSERVATION_WORK_BUDGET);
    // Only an actually attempted item advances the cursor. A timeout must not
    // skip the other seven forever when every first item is blocked.
    st.observation_attempted(first[0].0);
    let second = st.observation_work();
    assert_eq!(second[0].0, first[1].0);
    assert_eq!(st.peers.len(), 20);
    let a = observation_address(0);
    st.peers.get_mut(&(0, a)).unwrap().observed_at -= OBSERVATION_TTL;
    let b = observation_address(1);
    st.peers.get_mut(&(0, b)).unwrap().observed_at -= OBSERVATION_TTL;
    st.on_conn_state_changed(3, slk_protocol::ConnState::Connected as u8, b);
    st.expire_observations(Instant::now());
    assert_eq!(st.peers[&(0, a)].publication, PeerPublication::Retiring);
    assert_ne!(st.peers[&(0, b)].publication, PeerPublication::Retiring);
    assert!(!st.on_adv_report(a, -8, 0, String::new(), Vec::new()));
    assert_eq!(st.peers.len(), 20);
    assert_eq!(st.observation_drops, 1);
}

#[tokio::test]
async fn observation_publication_conflict_retries_without_new_report_and_preserves_foreign_owner() {
    use crate::state::PeerPublication;
    let bus = PrivateBus::start();
    let shared = state();
    let foreign = state();
    let server = server(&bus, shared.clone()).await;
    let a = observation_address(7);
    shared
        .lock()
        .await
        .on_adv_report(a, -12, 0, "device".into(), vec![1]);
    let path = shared.lock().await.peers[&(0, a)].object_path.clone();
    server
        .object_server()
        .at(path.as_str(), PeerIface::new(foreign.clone(), 0, 0, a))
        .await
        .unwrap();
    maintain_observations(&shared, &server).await;
    assert_eq!(
        shared.lock().await.peers[&(0, a)].publication,
        PeerPublication::Pending
    );
    assert_eq!(shared.lock().await.observation_publication_errors, 1);
    let iface = server
        .object_server()
        .interface::<_, PeerIface>(path.as_str())
        .await
        .unwrap();
    assert!(iface.get().await.belongs_to(&foreign, 0, (0, a)));
    let client = client(&bus).await;
    let adapter = adapter_proxy(&client).await;
    assert!(
        adapter
            .call::<_, _, Vec<String>>("ListPeers", &())
            .await
            .unwrap()
            .is_empty()
    );
    server
        .object_server()
        .remove::<PeerIface, _>(path.as_str())
        .await
        .unwrap();
    maintain_observations(&shared, &server).await;
    assert_eq!(
        shared.lock().await.peers[&(0, a)].publication,
        PeerPublication::Published
    );
    assert_eq!(
        adapter
            .call::<_, _, Vec<String>>("ListPeers", &())
            .await
            .unwrap()
            .len(),
        1
    );
    let iface = server
        .object_server()
        .interface::<_, PeerIface>(path.as_str())
        .await
        .unwrap();
    assert!(iface.get().await.belongs_to(&shared, 0, (0, a)));
}

#[tokio::test]
async fn observation_expiry_unpublishes_only_its_controller_and_retains_slots_until_confirmed() {
    use crate::state::{OBSERVATION_TTL, PeerPublication};
    let bus = PrivateBus::start();
    let shared = state();
    let other = state();
    other.lock().await.object_path = "/org/sparklink/slk1_g2".into();
    let server = server(&bus, shared.clone()).await;
    let a = observation_address(8);
    for owner in [&shared, &other] {
        owner
            .lock()
            .await
            .on_adv_report(a, -11, 0, String::new(), Vec::new());
        maintain_observations(owner, &server).await;
    }
    let old_path = shared.lock().await.peers[&(0, a)].object_path.clone();
    let other_path = other.lock().await.peers[&(0, a)].object_path.clone();
    server
        .object_server()
        .at("/org/sparklink/slk1_g2", AdapterIface::new(other.clone()))
        .await
        .unwrap();
    let client = client(&bus).await;
    // A dynamic zbus Proxy does not inspect EmitsChangedSignal=false to
    // disable its default cache. The original failing run is retained. Query
    // this documented uncached observation contract explicitly; the stale
    // value assertion below is unchanged. R3's shared client must do likewise.
    let observed = zbus::proxy::Builder::<zbus::Proxy<'_>>::new(&client)
        .destination("org.sparklink")
        .unwrap()
        .path(old_path.as_str())
        .unwrap()
        .interface("org.sparklink.Peer")
        .unwrap()
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()
        .await
        .unwrap();
    let peer = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk1_g2",
        "org.sparklink.Adapter",
    )
    .await
    .unwrap();
    let adapter = zbus::proxy::Builder::<zbus::Proxy<'_>>::new(&client)
        .destination("org.sparklink")
        .unwrap()
        .path("/org/sparklink/slk0")
        .unwrap()
        .interface("org.sparklink.Adapter")
        .unwrap()
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()
        .await
        .unwrap();
    assert!(
        observed
            .get_property::<bool>("ObservationValid")
            .await
            .unwrap()
    );
    assert_eq!(adapter.get_property::<u32>("PeerCount").await.unwrap(), 1);
    let iface = server
        .object_server()
        .interface::<_, PeerIface>(old_path.as_str())
        .await
        .unwrap();
    let lock = iface.get_mut().await;
    shared
        .lock()
        .await
        .peers
        .get_mut(&(0, a))
        .unwrap()
        .observed_at -= OBSERVATION_TTL;
    // Hold a real interface lock: the production maintenance's one original
    // 100ms budget must stop, retaining the slot for a later retry.
    let (finished, peer_name) = tokio::join!(
        timeout(
            Duration::from_secs(1),
            maintain_observations(&shared, &server)
        ),
        timeout(
            Duration::from_millis(500),
            peer.get_property::<String>("Name")
        )
    );
    finished.unwrap();
    assert!(peer_name.unwrap().is_ok());
    assert_eq!(
        shared.lock().await.peers[&(0, a)].publication,
        PeerPublication::Retiring
    );
    assert_eq!(shared.lock().await.observation_retirement_errors, 1);
    assert_eq!(
        other.lock().await.peers[&(0, a)].publication,
        PeerPublication::Published
    );
    assert!(
        server
            .object_server()
            .interface::<_, PeerIface>(other_path.as_str())
            .await
            .is_ok()
    );
    drop(lock);
    // Real repeated uncached D-Bus Get, not an assumed cache invalidation.
    assert!(
        !observed
            .get_property::<bool>("ObservationValid")
            .await
            .unwrap()
    );
    maintain_observations(&shared, &server).await;
    assert!(!shared.lock().await.peers.contains_key(&(0, a)));
    assert_eq!(adapter.get_property::<u32>("PeerCount").await.unwrap(), 0);
    assert!(matches!(
        server
            .object_server()
            .interface::<_, PeerIface>(old_path.as_str())
            .await,
        Err(zbus::Error::InterfaceNotFound)
    ));
    assert!(
        server
            .object_server()
            .interface::<_, PeerIface>(other_path.as_str())
            .await
            .unwrap()
            .get()
            .await
            .belongs_to(&other, 0, (0, a))
    );
}

#[tokio::test]
async fn observation_original_maintenance_budget_includes_state_lock_wait() {
    let bus = PrivateBus::start();
    let shared = state();
    let server = server(&bus, shared.clone()).await;
    let locked = shared.lock().await;
    timeout(
        Duration::from_millis(500),
        maintain_observations(&shared, &server),
    )
    .await
    .unwrap();
    assert!(locked.peers.is_empty());
    assert_eq!(locked.observation_publication_errors, 0); // no operation started
}

#[tokio::test]
async fn observation_connection_alias_never_invents_an_advertisement() {
    let bus = PrivateBus::start();
    let shared = state();
    let server = server(&bus, shared.clone()).await;
    let a = observation_address(22);
    {
        let mut st = shared.lock().await;
        st.controller = slk_protocol::SleControllerSnapshot {
            generation: 7,
            profile: 1,
            ..Default::default()
        };
        // Explicit kernel-snapshot fixture; this is not physical-link evidence.
        st.apply_native_links(native_table(20, 2, &[(1, 4, 0, 0, a)]), 0)
            .unwrap();
        st.observation_work();
        assert!(!st.peers[&(0, a)].rssi_known);
    }
    maintain_observations(&shared, &server).await;
    let path = shared.lock().await.peers[&(0, a)].object_path.clone();
    let client = client(&bus).await;
    let device = zbus::proxy::Builder::<zbus::Proxy<'_>>::new(&client)
        .destination("org.sparklink")
        .unwrap()
        .path(path.as_str())
        .unwrap()
        .interface("org.sparklink.Peer")
        .unwrap()
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()
        .await
        .unwrap();
    assert!(
        !device
            .get_property::<bool>("ObservationValid")
            .await
            .unwrap()
    );
    dispatch(
        Ok(Event::AdvReport {
            addr: a,
            rssi: -10,
            discovery_level: 0,
            name: String::new(),
            adv_data: vec![1, 2],
        }),
        &shared,
        &server,
    )
    .await;
    assert!(
        device
            .get_property::<bool>("ObservationValid")
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn typed_native_advertisements_share_peer_identity_without_inventing_rssi_or_links() {
    // Actual producer/parser/ObjectServer; /dev/null and explicit snapshot are
    // dependency fixtures, not a firmware/RF or real concurrency qualification.
    let bus = PrivateBus::start();
    let shared = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    shared.lock().await.controller = expected;
    let server = server(&bus, shared.clone()).await;
    let client = client(&bus).await;
    let address = [1, 2, 3, 4, 5, 6];
    let mut event = slk_protocol::SleControllerEvent {
        generation: 7,
        profile: 1,
        seq: 1,
        event_code: 0x180b,
        payload_len: 25,
        ..Default::default()
    };
    event.payload[2..8].copy_from_slice(&address);
    event.payload[21] = 127;
    event.payload[22] = 2;
    event.payload[23..25].copy_from_slice(&[0xa1, 0xb2]);
    dispatch_native(Ok(event), &shared, &server, expected).await;
    let path0 = crate::connection_object::peer_path("/org/sparklink/slk0", 0, address);
    let peer0 = zbus::Proxy::new(
        &client,
        "org.sparklink",
        path0.as_str(),
        "org.sparklink.Peer",
    )
    .await
    .unwrap();
    let o: slk_contract::PeerObservation = peer0.call("GetObservation", &()).await.unwrap();
    assert!(o.3 && !o.4);
    assert_eq!((o.0, o.1, o.8), (7, 0, 1));
    assert_eq!(o.7, [0xa1, 0xb2]);
    let info: crate::connection_object::PeerInfo = peer0.call("GetInfo", &()).await.unwrap();
    assert!(!info.3 && !info.4 && info.5.is_empty());
    event.seq = 2;
    event.payload[1] = 1;
    event.payload[21] = (-50i8) as u8;
    dispatch_native(Ok(event), &shared, &server, expected).await;
    let path1 = crate::connection_object::peer_path("/org/sparklink/slk0", 1, address);
    let peer1 = zbus::Proxy::new(
        &client,
        "org.sparklink",
        path1.as_str(),
        "org.sparklink.Peer",
    )
    .await
    .unwrap();
    let o: slk_contract::PeerObservation = peer1.call("GetObservation", &()).await.unwrap();
    assert!(o.3 && o.4);
    assert_eq!((o.1, o.5, o.8), (1, -50, 2));
    event.seq = 3;
    event.payload[1] = 6;
    dispatch_native(Ok(event), &shared, &server, expected).await;
    assert_eq!(shared.lock().await.peers.len(), 2);
    assert_eq!(shared.lock().await.native_reports.len(), 3); // Unsupported identity still raw evidence.
    assert_eq!(shared.lock().await.observation_drops, 1);
    let adapter = adapter_proxy(&client).await;
    let paths: Vec<String> = adapter.call("ListPeers", &()).await.unwrap();
    assert_eq!(paths, vec![path0.clone(), path1.clone()]);
    assert!(
        adapter
            .call::<_, _, Vec<String>>("GetDevices", &())
            .await
            .is_err()
    );
    let retired = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/dev_010203040506",
        "org.sparklink.Device",
    )
    .await
    .unwrap();
    assert!(retired.introspect().await.is_err());
    // Independent literal signature; shared producer/client aliases are not its oracle.
    let xml = peer0.introspect().await.unwrap();
    let method = xml
        .split("<method name=\"GetObservation\">")
        .nth(1)
        .unwrap()
        .split("</method>")
        .next()
        .unwrap();
    assert!(method.contains("type=\"(tysbbnayayttt)\""), "{method}");
    let iface = server
        .object_server()
        .interface::<_, PeerIface>(path0.as_str())
        .await
        .unwrap();
    assert!(iface.get().await.belongs_to(&shared, 7, (0, address)));
    // Same original production budget and lifecycle, now with full peer keys.
    shared
        .lock()
        .await
        .peers
        .get_mut(&(0, address))
        .unwrap()
        .observed_at -= crate::state::OBSERVATION_TTL;
    reconcile_native(
        &shared,
        &server,
        expected,
        0,
        Ok(native_table(10, 1, &[(1, 4, 0, 0, address)])),
    )
    .await;
    let o: slk_contract::PeerObservation = peer0.call("GetObservation", &()).await.unwrap();
    let i: crate::connection_object::PeerInfo = peer0.call("GetInfo", &()).await.unwrap();
    assert!(!o.3 && !o.4);
    assert!(i.3 && i.4);
    reconcile_native(
        &shared,
        &server,
        expected,
        11,
        Err(zbus::fdo::Error::Failed("explicit unknown snapshot".into())),
    )
    .await;
    assert!(shared.lock().await.peers.contains_key(&(0, address))); // Unknown cannot authorize retirement.
    let i: crate::connection_object::PeerInfo = peer0.call("GetInfo", &()).await.unwrap();
    assert!(!i.3 && !i.4);
    reconcile_native(&shared, &server, expected, 12, Ok(native_table(12, 2, &[]))).await;
    assert!(peer0.introspect().await.is_err());
    assert!(peer1.introspect().await.is_ok());
    let i: crate::connection_object::PeerInfo = peer1.call("GetInfo", &()).await.unwrap();
    assert!(i.3 && !i.4);
}

#[tokio::test]
async fn typed_peer_replay_and_capacity_never_replace_unretired_or_pinned_slots() {
    let shared = state();
    let mut st = shared.lock().await;
    st.controller = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    let mut e = slk_protocol::SleControllerEvent {
        generation: 7,
        profile: 1,
        seq: 5,
        event_code: 0x180b,
        payload_len: 24,
        ..Default::default()
    };
    e.payload[2..8].copy_from_slice(&[1; 6]);
    e.payload[21] = (-40i8) as u8;
    e.payload[22] = 1;
    e.payload[23] = 0xaa;
    st.on_native_adv_report(&e, &e.ws73_discovery().unwrap());
    e.seq = 4;
    e.payload[21] = (-80i8) as u8;
    e.payload[23] = 0xbb;
    st.on_native_adv_report(&e, &e.ws73_discovery().unwrap());
    assert_eq!(
        (
            st.peers[&(0, [1; 6])].rssi,
            st.peers[&(0, [1; 6])].adv_data.clone()
        ),
        (-40, vec![0xaa])
    );
    for n in 0..crate::state::OBSERVATION_MAX_ENTRIES as u16 - 1 {
        st.on_adv_report(observation_address(n), -5, 0, String::new(), vec![1]);
    }
    assert_eq!(st.peers.len(), crate::state::OBSERVATION_MAX_ENTRIES);
    let linked = [9; 6];
    st.apply_native_links(native_table(10, 1, &[(1, 3, 0, 1, linked)]), 0)
        .unwrap();
    st.observation_work();
    assert!(!st.peers.contains_key(&(1, linked)));
    assert_eq!(st.peers.len(), crate::state::OBSERVATION_MAX_ENTRIES);
    assert!(
        st.peers
            .values()
            .any(|p| p.publication == crate::state::PeerPublication::Retiring)
    );
    assert!(st.observation_bytes() <= crate::state::OBSERVATION_MAX_BYTES);
    // Cleanup must actually unpublish before its old slot is reusable. Existing
    // ObjectServer tests cover timeout, conflicting owner and eventual retry.
}

/// Real registry/reconcile/ObjectServer and Tokio cancellation. The table and
/// blocked Native dependency are fixtures; no successful kernel/USB operation.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn r5f9f_physical_projection_survives_initializer_and_retirement_cancellation() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let bus = PrivateBus::start();
    let state = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    let table = native_table(10, 1, &[(1, 7, 0, 0, [1; 6])]);
    let registration = {
        let mut st = state.lock().await;
        st.controller = expected;
        st.apply_native_links(table, 0).unwrap();
        st.connection_publications(&state).pending.remove(0)
    };
    let owner = registration.owner.clone();
    let server = server(&bus, state.clone()).await;
    let calls = Arc::new(AtomicUsize::new(0));
    let (entered, started) = oneshot::channel();
    let (release, released) = oneshot::channel();
    let first = tokio::spawn({
        let owner = owner.clone();
        let calls = calls.clone();
        async move {
            owner
                .initialize_with_fixture(async move {
                    calls.fetch_add(1, Ordering::SeqCst);
                    entered.send(()).unwrap();
                    released.await.unwrap();
                    Err("finite Native dependency failure after return".into())
                })
                .await
        }
    });
    started.await.unwrap();
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    let publication = tokio::spawn({
        let state = state.clone();
        let server = server.clone();
        async move { reconcile_native(&state, &server, expected, 0, Ok(table)).await }
    });
    timeout(Duration::from_millis(100), publication)
        .await
        .expect("physical Connection publication must not wait for SSAP initialization")
        .unwrap();
    assert!(
        !release.is_closed(),
        "parent cancel cannot drop the actual dependency task"
    );
    assert!(
        server
            .object_server()
            .interface::<_, crate::connection_object::ConnectionIface>(registration.path.as_str())
            .await
            .is_ok()
    );
    let proxy = zbus::Proxy::new(
        &server,
        "org.sparklink",
        registration.path.as_str(),
        "org.sparklink.Connection",
    )
    .await
    .unwrap();
    let physical: crate::connection_object::Info = proxy.call("GetInfo", &()).await.unwrap();
    assert_eq!(
        (physical.0, physical.1, physical.6, physical.7),
        (7, 1, true, true)
    );
    assert!(Arc::ptr_eq(
        &state.lock().await.native_connection_objects[&1].owner,
        &owner
    ));
    let down = native_table(11, 2, &[]);
    let retirement = tokio::spawn({
        let state = state.clone();
        let server = server.clone();
        async move { reconcile_native(&state, &server, expected, 11, Ok(down)).await }
    });
    timeout(Duration::from_secs(1), async {
        while !owner.is_retiring() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    retirement.abort();
    assert!(retirement.await.unwrap_err().is_cancelled());
    assert!(Arc::ptr_eq(
        &state.lock().await.retiring_connection_objects[&registration.path].owner,
        &owner
    ));
    let mut retry = tokio::spawn({
        let state = state.clone();
        let server = server.clone();
        async move { reconcile_native(&state, &server, expected, 11, Ok(down)).await }
    });
    assert!(
        timeout(Duration::from_millis(100), &mut retry)
            .await
            .is_err(),
        "cleanup cannot finish while Native dependency has not returned"
    );
    assert!(!release.is_closed());
    release.send(()).unwrap();
    timeout(Duration::from_secs(1), retry)
        .await
        .unwrap()
        .unwrap();
    assert!(state.lock().await.retiring_connection_objects.is_empty());
    assert!(state.lock().await.native_connection_objects.is_empty());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        owner
            .start_ssap()
            .await
            .unwrap_err()
            .to_string()
            .contains("retiring")
    );
}

/// Actual invalid ObjectServer path and subsequent real registration/retry;
/// failed initializer dependency, not an always-successful Native fixture.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn publication_failure_and_existing_interface_retry_reuse_one_resource_owner() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let bus = PrivateBus::start();
    let state = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    let table = native_table(10, 1, &[(1, 7, 0, 0, [1; 6])]);
    let registration = {
        let mut st = state.lock().await;
        st.controller = expected;
        st.apply_native_links(table, 0).unwrap();
        st.connection_publications(&state).pending.remove(0)
    };
    let owner = registration.owner.clone();
    let calls = Arc::new(AtomicUsize::new(0));
    let called = calls.clone();
    owner
        .initialize_with_fixture(async move {
            called.fetch_add(1, Ordering::SeqCst);
            Err("original finite creator failure".into())
        })
        .await
        .unwrap_err();
    let server = server(&bus, state.clone()).await;
    state
        .lock()
        .await
        .native_connection_objects
        .get_mut(&1)
        .unwrap()
        .path = "invalid object path".into();
    reconcile_native(&state, &server, expected, 0, Ok(table)).await;
    assert!(!state.lock().await.native_connection_objects[&1].published);
    assert!(Arc::ptr_eq(
        &state.lock().await.native_connection_objects[&1].owner,
        &owner
    ));
    state
        .lock()
        .await
        .native_connection_objects
        .get_mut(&1)
        .unwrap()
        .path = registration.path.clone();
    reconcile_native(&state, &server, expected, 0, Ok(table)).await;
    assert!(state.lock().await.native_connection_objects[&1].published);
    let iface = server
        .object_server()
        .interface::<_, crate::connection_object::ConnectionIface>(registration.path.as_str())
        .await
        .unwrap();
    assert!(iface.get().await.belongs_to(&owner));
    // Simulate cancellation after at inserted but before publication metadata
    // was acknowledged. at(false) must reuse the registered original owner.
    state
        .lock()
        .await
        .native_connection_objects
        .get_mut(&1)
        .unwrap()
        .published = false;
    reconcile_native(&state, &server, expected, 0, Ok(table)).await;
    assert!(state.lock().await.native_connection_objects[&1].published);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        owner
            .start_ssap()
            .await
            .unwrap_err()
            .to_string()
            .contains("original finite creator failure")
    );
    drop(iface);
    reconcile_native(&state, &server, expected, 11, Ok(native_table(11, 2, &[]))).await;
    assert!(state.lock().await.retiring_connection_objects.is_empty());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unfinished_retirement_retains_budget_and_missing_live_owner_is_retried_after_drain() {
    let bus = PrivateBus::start();
    let state = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    let links = (1..=16)
        .map(|i| (i, i as u16, 0, 0, [i as u8; 6]))
        .collect::<Vec<_>>();
    let old = {
        let mut st = state.lock().await;
        st.controller = expected;
        assert!(st.native_lease.is_none()); // no Native socket can be created
        st.apply_native_links(native_table(10, 16, &links), 0)
            .unwrap();
        st.connection_publications(&state).pending
    };
    let next = native_table(11, 17, &[(17, 7, 0, 0, [17; 6])]);
    {
        let mut st = state.lock().await;
        st.apply_native_links(next, 11).unwrap();
        let batch = st.connection_publications(&state);
        assert_eq!(batch.refused, 1);
        assert!(batch.pending.is_empty());
        assert_eq!(batch.retired.len(), 16);
        assert_eq!(st.retiring_connection_objects.len(), 16);
        assert!(st.connection_publication_pending());
        assert!(old.iter().all(|v| v.owner.is_retiring()));
    }
    let server = server(&bus, state.clone()).await;
    // Actual stop/join and ObjectServer InterfaceNotFound for owners that have
    // never acquired a resource. No assumed successful cleanup callback.
    reconcile_native(&state, &server, expected, 11, Ok(next)).await;
    assert!(state.lock().await.retiring_connection_objects.is_empty());
    assert!(state.lock().await.native_connection_objects.is_empty());
    assert!(state.lock().await.connection_publication_pending());
    reconcile_native(&state, &server, expected, 11, Ok(next)).await;
    assert!(state.lock().await.native_connection_objects[&17].published);
    assert_eq!(state.lock().await.native_connection_objects.len(), 1);
    assert!(
        !state.lock().await.native_connection_objects[&17]
            .owner
            .is_retiring()
    );
}

#[tokio::test]
async fn retiring_registration_never_removes_another_resource_owner_at_its_path() {
    use crate::connection_object::{ConnectionIface, ConnectionOwner, retire_registration};
    let bus = PrivateBus::start();
    let shared = state();
    let expected = slk_protocol::SleControllerSnapshot {
        generation: 7,
        profile: 1,
        ..Default::default()
    };
    let entry = {
        let mut st = shared.lock().await;
        st.controller = expected;
        st.apply_native_links(native_table(10, 1, &[(1, 7, 0, 0, [1; 6])]), 0)
            .unwrap();
        st.connection_publications(&shared).pending.remove(0)
    };
    let foreign = ConnectionOwner::new(&shared, 7, entry.reference, 0);
    let server = server(&bus, shared.clone()).await;
    server
        .object_server()
        .at(
            entry.path.as_str(),
            ConnectionIface::from_owner(shared.clone(), foreign.clone()).unwrap(),
        )
        .await
        .unwrap();
    assert!(retire_registration(&server, &entry).await.is_err());
    assert!(entry.owner.is_retiring());
    assert!(!foreign.is_retiring());
    let iface = server
        .object_server()
        .interface::<_, ConnectionIface>(entry.path.as_str())
        .await
        .unwrap();
    assert!(iface.get().await.belongs_to(&foreign));
    assert!(
        shared
            .lock()
            .await
            .native_connection_objects
            .contains_key(&1)
    );
}

/// Per-task test rendezvous only; absent from the default daemon binary.
/// It changes scheduling before the production wait, never its result or state.
pub(super) struct NativeRetryProbe {
    before: oneshot::Sender<()>,
    resume: oneshot::Receiver<()>,
    pending: oneshot::Sender<()>,
}

pub(super) async fn observe_native_retry(
    wait: impl Future<Output = Option<bool>>,
    probe: Option<NativeRetryProbe>,
) -> Option<bool> {
    let Some(probe) = probe else {
        return wait.await;
    };
    probe
        .before
        .send(())
        .expect("VM test observes actual retry branch");
    probe
        .resume
        .await
        .expect("VM test releases pre-wait rendezvous");
    let mut pending = Some(probe.pending);
    let mut wait = std::pin::pin!(wait);
    std::future::poll_fn(|cx| {
        let result = wait.as_mut().poll(cx);
        if result.is_pending()
            && let Some(pending) = pending.take()
        {
            pending
                .send(())
                .expect("VM test observes real pending lock wait");
        }
        result
    })
    .await
}

/// Explicit VM-only test: real selected controller, subscription/ioctl and the
/// whole Native EventTask loop. No management lease or firmware/device writes.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "dedicated VM, exact two controller identities and real Native kernel required"]
async fn native_retry_real_subscription_vm() {
    use std::os::fd::AsRawFd;
    assert_eq!(
        std::env::var("SPARKLINK_NATIVE_EVENT_VM").as_deref(),
        Ok("1")
    );
    fn target(name: &str) -> (u16, u64) {
        let text = std::env::var(name).expect("explicit controller index:generation required");
        let (index, generation) = text.split_once(':').expect("index:generation");
        let identity = (index.parse().unwrap(), generation.parse().unwrap());
        assert_ne!(identity.1, 0);
        identity
    }
    fn selected(identity: (u16, u64)) -> Adapter {
        let mut fd = Adapter::open("/dev/sparklink").unwrap();
        fd.select_device(identity.0).unwrap();
        let s = fd.controller_snapshot(identity.1).unwrap();
        assert_eq!((s.dev_index, s.generation), identity);
        assert_eq!(s.flags, slk_protocol::CONTROLLER_READY);
        fd
    }
    let victim = target("SPARKLINK_NATIVE_EVENT_TARGET");
    let sibling = target("SPARKLINK_NATIVE_EVENT_SIBLING");
    assert_ne!(victim.0, sibling.0);
    let control = Arc::new(selected(victim));
    let sibling_control = selected(sibling);
    let before_sibling = sibling_control.controller_snapshot(sibling.1).unwrap();
    let expected = control.controller_snapshot(victim.1).unwrap();
    let links = control.native_link_snapshot(victim.1).unwrap();
    assert_eq!(links.flags, slk_protocol::LINK_SNAPSHOT_KNOWN);
    assert_eq!(
        links.count, 0,
        "run before physical connections; no competing SSAP owners"
    );
    let mut value = AdapterState::new(
        control.clone(),
        DaemonConfig::default(),
        BondingStore::new(&std::env::temp_dir(), "unused-native-event-vm"),
        ProfileRegistry::new(),
    );
    value.controller = expected;
    value.native_control = Some(control.clone());
    let state = Arc::new(Mutex::new(value));
    let bus = PrivateBus::with_config(Some("/usr/share/sparklink/native-event-test-dbus.conf"));
    let server = server(&bus, state.clone()).await;
    let subscription = selected(victim);
    let raw_fd = subscription.as_fd().as_raw_fd();
    let receiver = subscription.into_controller_event_receiver().unwrap();
    let (before, at_retry) = oneshot::channel();
    let (resume, released) = oneshot::channel();
    let (pending, at_pending) = oneshot::channel();
    let task = EventTask::start_native_inner(
        receiver,
        state.clone(),
        server,
        expected,
        Some(NativeRetryProbe {
            before,
            resume: released,
            pending,
        }),
    );
    timeout(Duration::from_secs(3), at_retry)
        .await
        .unwrap()
        .unwrap();
    let lock = state.lock().await;
    assert!(
        lock.native_links_known(),
        "actual initial kernel snapshot reconciled before retry"
    );
    assert!(lock.native_link_barrier >= links.event_seq);
    resume.send(()).unwrap();
    timeout(Duration::from_secs(2), at_pending)
        .await
        .unwrap()
        .unwrap();
    timeout(Duration::from_secs(2), task.shutdown())
        .await
        .expect("actual Native retry cancels while SharedState remains held")
        .unwrap();
    assert!(state.try_lock().is_err());
    assert_eq!(
        std::fs::read_link(format!("/proc/self/fd/{raw_fd}"))
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::NotFound,
        "actual subscription fd released at join; no substitute fd"
    );
    let after = control.controller_snapshot(victim.1).unwrap();
    let after_sibling = sibling_control.controller_snapshot(sibling.1).unwrap();
    assert_eq!(
        (after.dev_index, after.generation, after.flags),
        (expected.dev_index, expected.generation, expected.flags)
    );
    assert_eq!(
        (
            after_sibling.dev_index,
            after_sibling.generation,
            after_sibling.flags
        ),
        (
            before_sibling.dev_index,
            before_sibling.generation,
            before_sibling.flags
        )
    );
    println!(
        "NativeRetryVm: {{\"index\":{},\"generation\":{},\"sibling_index\":{},\"sibling_generation\":{},\"initial_kernel_snapshot\":true,\"retry_pending_with_lock_held\":true,\"joined_with_lock_held\":true,\"subscription_fd_closed\":true,\"both_still_ready\":true}}",
        victim.0, victim.1, sibling.0, sibling.1
    );
}
