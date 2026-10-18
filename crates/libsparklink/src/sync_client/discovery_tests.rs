//! Actual C exports -> shared SyncClient -> Rust DiscoverySession -> real private
//! D-Bus. Scripted metadata/error fixture only, not scanner/Native/RF qualification.
use super::*;
use crate::{ffi_client::*, ffi_discovery::*, test_support as support};
use slk_contract::discovery as wire;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU8, AtomicU64, Ordering},
};
const PATH: &str = "/org/sparklink/slk2_g7";
#[derive(Default)]
struct Script {
    mode: AtomicU8,
    calls: AtomicU64,
    reads: AtomicU64,
    releases: AtomicU64,
    stamps: Mutex<Vec<slk_contract::Deadline>>,
}
struct Adapter(Arc<Script>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    fn acquire_discovery(
        &self,
        prefix: Vec<u8>,
        rssi: i16,
        duration: u32,
        stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<u64> {
        assert_eq!((prefix, rssi, duration), (vec![0xab], -128, 20000));
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        self.0.stamps.lock().unwrap().push(stamp);
        if self.0.mode.load(Ordering::SeqCst) == 1 {
            return Err(zbus::fdo::Error::LimitsExceeded(
                "explicit fixture denial".into(),
            ));
        }
        Ok(7)
    }
    async fn read_discovery(
        &self,
        id: u64,
        _wait: bool,
        stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<wire::Batch> {
        assert_eq!(id, 7);
        self.0.stamps.lock().unwrap().push(stamp);
        let sequence = self.0.reads.fetch_add(1, Ordering::SeqCst) + 1;
        let mode = self.0.mode.load(Ordering::SeqCst);
        if mode == 2 {
            return Err(zbus::fdo::Error::UnknownObject(
                "expired fixture lease".into(),
            ));
        }
        if mode == 3 {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        let mut header = vec![0; 23];
        header[2..8].copy_from_slice(&[1, 2, 3, 4, 5, 6]);
        Ok(wire::Batch {
            version: 1,
            session: id,
            generation: if mode == 4 { 99 } else { 7 },
            dropped: 2,
            kernel_lost: 3,
            reports: vec![wire::Report {
                sequence,
                kernel_boottime_ns: 456,
                address_type: 0,
                address: vec![1, 2, 3, 4, 5, 6],
                rssi: -42,
                rssi_known: true,
                header,
                data: vec![0xab, 0xff],
            }],
        })
    }
    fn release_discovery(&self, id: u64, stamp: slk_contract::Deadline) -> zbus::fdo::Result<bool> {
        assert_eq!(id, 7);
        self.0.stamps.lock().unwrap().push(stamp);
        self.0.releases.fetch_add(1, Ordering::SeqCst);
        match self.0.mode.load(Ordering::SeqCst) {
            5 => Err(zbus::fdo::Error::Timeout(
                "uncertain fixture release".into(),
            )),
            6 => Ok(true),
            _ => Ok(false),
        }
    }
}
fn ns() -> u64 {
    slk_channel::deadline::Deadline::after(Duration::from_secs(2))
        .unwrap()
        .stamp()
        .monotonic_ns
}
fn id() -> SlkControllerId {
    SlkControllerId {
        generation: 7,
        index: 2,
        reserved: [0; 6],
    }
}
async fn fixture() -> (support::Bus, zbus::Connection, Arc<Script>, *mut SlkClient) {
    let bus = support::Bus::start();
    let script = Arc::new(Script::default());
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at(PATH, Adapter(script.clone()))
        .unwrap()
        .build()
        .await
        .unwrap();
    let address = bus.address.clone();
    let executor = SyncClient::start(
        Deadline::from_monotonic_ns(ns()).unwrap(),
        move || async move {
            let c = zbus::connection::Builder::address(address.as_str())?
                .build()
                .await?;
            Client::from_connection(c).await
        },
    )
    .unwrap();
    (
        bus,
        server,
        script,
        Box::into_raw(Box::new(SlkClient {
            inner: Arc::new(executor),
        })),
    )
}
unsafe fn acquire(c: *const SlkClient) -> *mut SlkDiscovery {
    let mut out = std::ptr::null_mut();
    assert_eq!(
        unsafe { slk_client_discover(c, &id(), [0xab].as_ptr(), 1, -128, 20000, ns(), &mut out) },
        0
    );
    assert!(!out.is_null());
    out
}
unsafe fn read(
    v: *mut SlkDiscovery,
    flags: u32,
    cap: usize,
    deadline: u64,
) -> (i32, SlkDiscoveryBatch, usize, Vec<SlkDiscoveryReport>) {
    let mut metadata = SlkDiscoveryBatch {
        session: 999,
        ..Default::default()
    };
    let mut count = 999;
    let mut reports: Vec<SlkDiscoveryReport> = vec![unsafe { std::mem::zeroed() }; 32];
    let e = unsafe {
        slk_discovery_read(
            v,
            &mut metadata,
            reports.as_mut_ptr(),
            cap,
            &mut count,
            flags,
            deadline,
        )
    };
    (e, metadata, count, reports)
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn production_read_retains_short_buffer_and_peek_without_second_rpc() {
    let (_bus, _server, s, c) = fixture().await;
    let v = unsafe { acquire(c) };
    unsafe { slk_client_close(c) };
    let mut actual = id();
    actual.generation = 99;
    let mut session = 0;
    assert_eq!(
        unsafe { slk_discovery_identity(v, &mut actual, &mut session) },
        0
    );
    assert_eq!((actual.index, actual.generation, session), (2, 7, 7));
    assert_eq!(actual.reserved, [0; 6]);
    let (e, m, n, reports) = unsafe { read(v, 1, 0, ns()) };
    assert_eq!((e, m.session, n), (-nix::libc::ENOBUFS, 999, 1));
    assert_eq!(reports[0].sequence, 0);
    for flags in [2, 3, 0] {
        let (e, m, n, reports) = unsafe { read(v, flags, 32, ns()) };
        assert_eq!(
            (e, m.session, m.generation, m.dropped, m.kernel_lost, n),
            (0, 7, 7, 2, 3, 1)
        );
        let r = reports[0];
        assert_eq!(
            (r.sequence, r.rssi, r.data_length, r.rssi_known),
            (1, -42, 2, 1)
        );
        assert_eq!(&r.data[..2], &[0xab, 0xff]);
        assert!(r.data[2..].iter().all(|b| *b == 0));
        assert_eq!(r.reserved, [0; 6]);
    }
    assert_eq!(s.reads.load(Ordering::SeqCst), 1);
    let (_, _, _, reports) = unsafe { read(v, 0, 32, ns()) };
    assert_eq!(reports[0].sequence, 2);
    let mut stopped = 999;
    assert_eq!(unsafe { slk_discovery_release(v, ns(), &mut stopped) }, 0);
    assert_eq!(stopped, 0);
    assert_eq!(unsafe { read(v, 0, 32, ns()) }.0, -nix::libc::EINVAL);
    assert_eq!(s.reads.load(Ordering::SeqCst), 2);
    assert_eq!(
        unsafe { slk_discovery_release(v, ns(), &mut stopped) },
        -nix::libc::EINVAL
    );
    assert_eq!(s.releases.load(Ordering::SeqCst), 1);
    unsafe {
        slk_discovery_free(v);
        slk_discovery_free(std::ptr::null_mut())
    };
    assert_eq!(std::mem::size_of::<SlkDiscoveryBatch>(), 40);
    assert_eq!(std::mem::size_of::<SlkDiscoveryReport>(), 312);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn invalid_inputs_and_expired_queue_work_do_not_call_broker_or_mutate_output() {
    let (_bus, _server, s, c) = fixture().await;
    let sentinel = std::ptr::dangling_mut::<SlkDiscovery>();
    let mut view = sentinel;
    for (prefix, len, rssi, duration) in [
        (std::ptr::null(), 1, -128, 20000),
        ([0u8; 65].as_ptr(), 65, -128, 20000),
        ([0u8; 1].as_ptr(), 1, 21, 20000),
        ([0u8; 1].as_ptr(), 1, -128, 249),
    ] {
        assert_eq!(
            unsafe { slk_client_discover(c, &id(), prefix, len, rssi, duration, ns(), &mut view) },
            -nix::libc::EINVAL
        );
        assert_eq!(view, sentinel);
    }
    assert_eq!(
        unsafe { slk_client_discover(c, &id(), [0xab].as_ptr(), 1, -128, 20000, 1, &mut view) },
        -nix::libc::ETIMEDOUT
    );
    assert_eq!(s.calls.load(Ordering::SeqCst), 0);
    s.mode.store(1, Ordering::SeqCst);
    assert_eq!(
        unsafe { slk_client_discover(c, &id(), [0xab].as_ptr(), 1, -128, 20000, ns(), &mut view) },
        -nix::libc::ENOBUFS
    );
    assert_eq!(view, sentinel);
    s.mode.store(0, Ordering::SeqCst);
    let v = unsafe { acquire(c) };
    let (e, m, n, _) = unsafe { read(v, 0, 32, 1) };
    assert_eq!((e, m.session, n), (-nix::libc::ETIMEDOUT, 999, 999));
    assert_eq!(s.reads.load(Ordering::SeqCst), 0);
    let (e, m, n, _) = unsafe { read(v, 4, 32, ns()) };
    assert_eq!((e, m.session, n), (-nix::libc::EINVAL, 999, 999));
    let locked = unsafe { &*v }.call.lock().unwrap();
    assert_eq!(unsafe { read(v, 0, 32, ns()) }.0, -nix::libc::EAGAIN);
    let mut stopped = 999;
    assert_eq!(
        unsafe { slk_discovery_release(v, ns(), &mut stopped) },
        -nix::libc::EAGAIN
    );
    assert_eq!(stopped, 999);
    drop(locked);
    assert_eq!(s.releases.load(Ordering::SeqCst), 0);
    unsafe {
        slk_discovery_release(v, ns(), &mut stopped);
        slk_discovery_free(v);
        slk_client_close(c)
    };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unknown_object_bad_generation_timeout_and_uncertain_close_keep_errors() {
    let (_bus, _server, s, c) = fixture().await;
    let v = unsafe { acquire(c) };
    for (mode, expected) in [(2, nix::libc::ENOENT), (4, nix::libc::ESTALE)] {
        s.mode.store(mode, Ordering::SeqCst);
        let (e, m, n, _) = unsafe { read(v, 0, 32, ns()) };
        assert_eq!((e, m.session, n), (-expected, 999, 999));
    }
    s.mode.store(3, Ordering::SeqCst);
    let deadline = slk_channel::deadline::Deadline::after(Duration::from_millis(20))
        .unwrap()
        .stamp()
        .monotonic_ns;
    let (e, m, n, _) = unsafe { read(v, 1, 32, deadline) };
    assert_eq!((e, m.session, n), (-nix::libc::ETIMEDOUT, 999, 999));
    assert_eq!(s.stamps.lock().unwrap().last().unwrap().0, deadline);
    s.mode.store(5, Ordering::SeqCst);
    let mut stopped = 999;
    assert_eq!(
        unsafe { slk_discovery_release(v, ns(), &mut stopped) },
        -nix::libc::ETIMEDOUT
    );
    assert_eq!(stopped, 999);
    assert_eq!(unsafe { read(v, 0, 32, ns()) }.0, -nix::libc::EINVAL);
    assert_eq!(s.releases.load(Ordering::SeqCst), 1);
    unsafe {
        slk_discovery_free(v);
        slk_client_close(c)
    };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pending_delivery_does_not_gain_new_owner_qualification() {
    let (bus, server, s, c) = fixture().await;
    let v = unsafe { acquire(c) };
    assert_eq!(unsafe { read(v, 2, 32, ns()) }.0, 0);
    server.release_name("org.sparklink").await.unwrap();
    let _replacement = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .build()
        .await
        .unwrap();
    let (e, m, n, _) = unsafe { read(v, 0, 32, ns()) };
    assert_eq!((e, m.session, n), (-nix::libc::ESTALE, 999, 999));
    assert_eq!(s.reads.load(Ordering::SeqCst), 1);
    unsafe {
        slk_discovery_free(v);
        slk_client_close(c)
    };
}
