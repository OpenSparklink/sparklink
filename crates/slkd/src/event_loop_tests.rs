use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use libsparklink::{Adapter, Error};
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

struct PrivateBus {
    child: Child,
    address: String,
}

impl PrivateBus {
    fn start() -> Self {
        let executable =
            std::env::var_os("SPARKLINK_TEST_DBUS_DAEMON").unwrap_or_else(|| "dbus-daemon".into());
        let child = Command::new(executable)
            .args(["--session", "--nofork", "--print-address=1"])
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
                controller.call_method("GetDliInfo", &())
            ),
            timeout(
                Duration::from_secs(2),
                proxy.call::<_, _, ()>("StartDiscovery", &())
            ),
            timeout(
                Duration::from_secs(2),
                proxy.call::<_, _, ()>("ConnectDevice", &("01:02:03:04:05:06",))
            ),
        );
        // /dev/null is intentionally not a fake successful controller. A real
        // method error proves the handler ran; a timeout or transport error does not.
        for result in [info.map(|r| r.map(|_| ())), scan, connect] {
            match result.unwrap().unwrap_err() {
                zbus::Error::MethodError(name, _, _) => {
                    assert_eq!(name.as_str(), "org.freedesktop.DBus.Error.Failed")
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
    let path = "/org/sparklink/slk0/dev_010203040506";
    timeout(Duration::from_secs(2), async {
        loop {
            if let Ok(device) =
                zbus::Proxy::new(&client, "org.sparklink", path, "org.sparklink.Device").await
                && device
                    .get_property::<String>("Name")
                    .await
                    .is_ok_and(|name| name == "event-after-silence")
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(state.lock().await.devices.len(), 1);
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
    assert!(lock.devices.is_empty());
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
    let removal = security.call::<_, _, ()>("RemoveBond", &("01:02:03:04:05:06",));
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
        assert_eq!(st.devices[&[5; 6]].conn_handle, Some(5));
        (st.profiles.clone(), st.bonding.clone())
    };
    // The connection object is published before entering user callback code.
    let remote = zbus::Proxy::new(
        &client,
        "org.sparklink",
        "/org/sparklink/slk0/conn_0005",
        "org.sparklink.RemoteService",
    )
    .await
    .unwrap();
    timeout(Duration::from_secs(2), remote.introspect())
        .await
        .unwrap()
        .unwrap();
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
        let peer = &st.devices[&report.address];
        assert_eq!(peer.object_path, "/org/sparklink/slk3_g42/dev_010203040506");
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
    assert_eq!(state.lock().await.native_reports.len(), 1);
    {
        state.lock().await.present = false;
    }
    event.profile = 1;
    super::dispatch_native(Ok(event), &state, &connection, expected).await;
    assert_eq!(state.lock().await.native_reports.len(), 1);
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
