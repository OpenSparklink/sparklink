//! Actual C exports -> SyncClient -> Rust Owned receipt -> real private bus.
//! Scripted metadata/errors only;not a database,callback,Native or RF fixture.
use super::*;
use crate::{ffi_client::*, ffi_local_services::*, test_support as support};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU8, AtomicU64, Ordering},
};
const PATH: &str = "/org/sparklink/slk2_g7";
#[derive(Default)]
struct Script {
    mode: AtomicU8,
    registrations: AtomicU64,
    reads: AtomicU64,
    removals: AtomicU64,
    owner: Mutex<String>,
    stamps: Mutex<Vec<slk_contract::Deadline>>,
}
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![PATH.into()]
    }
}
struct Adapter;
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        7
    }
}
struct Services(Arc<Script>);
#[zbus::interface(name = "org.sparklink.ServiceManager")]
impl Services {
    async fn register_owned_local_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<slk_contract::ssap::local::PropertyDefinition>,
        authorizer: zbus::zvariant::OwnedObjectPath,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<(u16, u16, Vec<u16>)> {
        assert_eq!(uuid, [1, 0]);
        assert_eq!(properties, [(vec![2, 0], 5, 0, vec![7, 8, 9])]);
        assert_eq!(authorizer.as_str(), "/");
        self.0.stamps.lock().unwrap().push(deadline);
        self.0.registrations.fetch_add(1, Ordering::SeqCst);
        *self.0.owner.lock().unwrap() = h.sender().unwrap().to_string();
        match self.0.mode.load(Ordering::SeqCst) {
            1 => {
                return Err(zbus::fdo::Error::AccessDenied(
                    "explicit fixture denial".into(),
                ));
            }
            2 => return Ok((16, 17, vec![99])),
            3 => tokio::time::sleep(Duration::from_millis(100)).await,
            _ => {}
        }
        Ok((16, 17, vec![17]))
    }
    async fn read_owned_local_value(
        &self,
        handle: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<Vec<u8>> {
        assert_eq!(handle, 17);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        self.0.stamps.lock().unwrap().push(deadline);
        self.0.reads.fetch_add(1, Ordering::SeqCst);
        if self.0.mode.load(Ordering::SeqCst) == 4 {
            return Err(zbus::fdo::Error::UnknownObject(
                "original service absent".into(),
            ));
        }
        match self.0.mode.load(Ordering::SeqCst) {
            6 => Ok(Vec::new()),
            7 => Ok(vec![1; 2043]),
            _ => Ok(vec![7, 8, 9]),
        }
    }
    fn unregister_owned_local_service(
        &self,
        start: u16,
        deadline: slk_contract::Deadline,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<()> {
        assert_eq!(start, 16);
        assert_eq!(*self.0.owner.lock().unwrap(), h.sender().unwrap().as_str());
        self.0.stamps.lock().unwrap().push(deadline);
        self.0.removals.fetch_add(1, Ordering::SeqCst);
        if self.0.mode.load(Ordering::SeqCst) == 5 {
            return Err(zbus::fdo::Error::Timeout(
                "uncertain fixture withdrawal".into(),
            ));
        }
        Ok(())
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
fn property() -> SlkServiceProperty {
    let mut p: SlkServiceProperty = unsafe { std::mem::zeroed() };
    p.operations = 5;
    p.uuid_length = 2;
    p.uuid[0] = 2;
    p.value_length = 3;
    p.value[..3].copy_from_slice(&[7, 8, 9]);
    p
}
async fn fixture() -> (support::Bus, zbus::Connection, Arc<Script>, *mut SlkClient) {
    let bus = support::Bus::start();
    let script = Arc::new(Script::default());
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager)
        .unwrap()
        .serve_at(PATH, Adapter)
        .unwrap()
        .serve_at(format!("{PATH}/services"), Services(script.clone()))
        .unwrap()
        .build()
        .await
        .unwrap();
    let address = bus.address.clone();
    let exec = SyncClient::start(
        Deadline::from_monotonic_ns(ns()).unwrap(),
        move || async move {
            Client::from_connection(
                zbus::connection::Builder::address(address.as_str())?
                    .build()
                    .await?,
            )
            .await
        },
    )
    .unwrap();
    (
        bus,
        server,
        script,
        Box::into_raw(Box::new(SlkClient {
            inner: Arc::new(exec),
        })),
    )
}
unsafe fn acquire(c: *const SlkClient, deadline: u64) -> (i32, *mut SlkLocalService) {
    let mut output = std::ptr::null_mut();
    let code = unsafe {
        slk_client_register_local_service(
            c,
            &id(),
            [1, 0].as_ptr(),
            2,
            &property(),
            1,
            deadline,
            &mut output,
        )
    };
    (code, output)
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_owned_ffi_retains_caller_short_buffer_and_explicit_withdrawal() {
    let (_bus, _server, s, c) = fixture().await;
    let deadline = ns();
    let (e, v) = unsafe { acquire(c, deadline) };
    assert_eq!(e, 0);
    unsafe { slk_client_close(c) };
    let mut receipt: SlkServiceReceipt = unsafe { std::mem::zeroed() };
    assert_eq!(unsafe { slk_local_service_receipt(v, &mut receipt) }, 0);
    assert_eq!(
        (
            receipt.controller.index,
            receipt.controller.generation,
            receipt.start,
            receipt.end,
            receipt.property_count
        ),
        (2, 7, 16, 17, 1)
    );
    assert_eq!(receipt.handles[0], 17);
    assert!(receipt.handles[1..].iter().all(|h| *h == 0));
    assert_eq!(receipt.reserved, [0; 2]);
    let mut buffer = [0xaa; 8];
    let mut length = 99;
    assert_eq!(
        unsafe { slk_local_service_read(v, 17, buffer.as_mut_ptr(), 2, &mut length, ns()) },
        -nix::libc::ENOBUFS
    );
    assert_eq!(length, 3);
    assert_eq!(buffer, [0xaa; 8]);
    assert_eq!(
        unsafe { slk_local_service_read(v, 17, buffer.as_mut_ptr(), 8, &mut length, ns()) },
        0
    );
    assert_eq!(&buffer[..3], &[7, 8, 9]);
    assert_eq!(&buffer[3..], &[0xaa; 5]);
    assert_eq!(unsafe { slk_local_service_unregister(v, ns()) }, 0);
    length = 99;
    buffer = [0xaa; 8];
    assert_eq!(
        unsafe { slk_local_service_read(v, 17, buffer.as_mut_ptr(), 8, &mut length, ns()) },
        -nix::libc::EINVAL
    );
    assert_eq!(length, 99);
    assert_eq!(buffer, [0xaa; 8]);
    assert_eq!(
        unsafe { slk_local_service_unregister(v, ns()) },
        -nix::libc::EINVAL
    );
    assert_eq!(s.removals.load(Ordering::SeqCst), 1);
    assert_eq!(s.reads.load(Ordering::SeqCst), 2);
    assert_eq!(s.stamps.lock().unwrap()[0].0, deadline);
    unsafe { slk_local_service_free(v) };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn invalid_owned_ffi_never_invokes_broker_or_changes_outputs() {
    let (_bus, _server, s, c) = fixture().await;
    for kind in 0..8 {
        let mut p = property();
        let mut count = 1;
        let mut i = id();
        let mut deadline = ns();
        let expected = match kind {
            0 => {
                p.value_length = 2043;
                nix::libc::EMSGSIZE
            }
            1 => {
                p.access = 36;
                nix::libc::EOPNOTSUPP
            }
            2 => {
                p.operations = 8;
                nix::libc::EOPNOTSUPP
            }
            3 => {
                p.access = 64;
                nix::libc::EINVAL
            }
            4 => {
                p.reserved[0] = 1;
                nix::libc::EINVAL
            }
            5 => {
                count = 0;
                nix::libc::EINVAL
            }
            6 => {
                i.reserved[0] = 1;
                nix::libc::EINVAL
            }
            _ => {
                deadline = 1;
                nix::libc::ETIMEDOUT
            }
        };
        let sentinel = std::ptr::dangling_mut::<SlkLocalService>();
        let mut out = sentinel;
        assert_eq!(
            unsafe {
                slk_client_register_local_service(
                    c,
                    &i,
                    [1, 0].as_ptr(),
                    2,
                    &p,
                    count,
                    deadline,
                    &mut out,
                )
            },
            -expected
        );
        assert_eq!(out, sentinel);
    }
    assert_eq!(s.registrations.load(Ordering::SeqCst), 0);
    unsafe { slk_client_close(c) };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn failed_owned_ffi_keeps_denial_bad_receipt_deadline_and_uncertain_removal() {
    let (_bus, server, s, c) = fixture().await;
    for (mode, error) in [
        (1, nix::libc::EACCES),
        (2, nix::libc::ESTALE),
        (3, nix::libc::ETIMEDOUT),
    ] {
        s.mode.store(mode, Ordering::SeqCst);
        let mut output = std::ptr::dangling_mut::<SlkLocalService>();
        let deadline = if mode == 3 {
            slk_channel::deadline::Deadline::after(Duration::from_millis(20))
                .unwrap()
                .stamp()
                .monotonic_ns
        } else {
            ns()
        };
        assert_eq!(
            unsafe {
                slk_client_register_local_service(
                    c,
                    &id(),
                    [1, 0].as_ptr(),
                    2,
                    &property(),
                    1,
                    deadline,
                    &mut output,
                )
            },
            -error
        );
        assert_eq!(output, std::ptr::dangling_mut::<SlkLocalService>());
    }
    tokio::time::sleep(Duration::from_millis(110)).await;
    s.mode.store(0, Ordering::SeqCst);
    let (e, v) = unsafe { acquire(c, ns()) };
    assert_eq!(e, 0);
    s.mode.store(5, Ordering::SeqCst);
    assert_eq!(
        unsafe { slk_local_service_unregister(v, ns()) },
        -nix::libc::ETIMEDOUT
    );
    let mut buffer = [0; 8];
    let mut n = 0;
    assert_eq!(
        unsafe { slk_local_service_read(v, 17, buffer.as_mut_ptr(), 8, &mut n, ns()) },
        0
    );
    s.mode.store(6, Ordering::SeqCst);
    n = 99;
    assert_eq!(
        unsafe { slk_local_service_read(v, 17, std::ptr::null_mut(), 0, &mut n, ns()) },
        0
    );
    assert_eq!(n, 0);
    s.mode.store(7, Ordering::SeqCst);
    n = 99;
    buffer = [0xaa; 8];
    assert_eq!(
        unsafe { slk_local_service_read(v, 17, buffer.as_mut_ptr(), 8, &mut n, ns()) },
        -nix::libc::EOVERFLOW
    );
    assert_eq!(n, 99);
    assert_eq!(buffer, [0xaa; 8]);
    let removals = s.removals.load(Ordering::SeqCst);
    unsafe { slk_local_service_free(v) };
    assert_eq!(s.removals.load(Ordering::SeqCst), removals);
    server.release_name("org.sparklink").await.unwrap();
    unsafe { slk_client_close(c) };
}
