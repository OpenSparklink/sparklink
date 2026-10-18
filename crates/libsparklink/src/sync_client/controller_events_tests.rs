//! Actual C exports/Client/executor over private D-Bus; finite directory metadata
//! fixtures only, never Native state, physical drain, protocol completion or RF.
use super::*;
use crate::ffi_client::{SlkClient, SlkControllerId, slk_client_close};
use crate::ffi_controller_events::*;
use crate::test_support as support;
use slk_contract::controller_events as wire;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU8, Ordering},
};
#[derive(Default)]
struct Script {
    mode: AtomicU8,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
struct Manager(Arc<Script>);
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![
            "/org/sparklink/slk2_g7".into(),
            "/org/sparklink/slk3_g9".into(),
        ]
    }
    async fn get_controller_changes(
        &self,
        after: u64,
        wait: bool,
        _stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<wire::Batch> {
        if !wait {
            return Ok((1, 0, 0, false, vec![]));
        }
        self.0.entered.notify_one();
        match self.0.mode.load(Ordering::SeqCst) {
            1 if after == 0 => Ok((1, 1, 2, false, vec![(1, 2, 7, 1), (2, 2, 7, 2)])),
            2 if after == 0 => Ok((1, 2, 65, true, vec![])),
            3 if after == 0 => {
                self.0.release.notified().await;
                Ok((1, 1, 1, false, vec![(1, 2, 7, 1)]))
            }
            _ => Err(zbus::fdo::Error::InvalidArgs(
                "unmatched finite metadata fixture".into(),
            )),
        }
    }
}
fn ns() -> u64 {
    slk_channel::deadline::Deadline::after(Duration::from_secs(2))
        .unwrap()
        .stamp()
        .monotonic_ns
}
async fn fixture() -> (
    support::Bus,
    zbus::Connection,
    Arc<Script>,
    *mut SlkClient,
    String,
) {
    let bus = support::Bus::start();
    let script = Arc::new(Script::default());
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager(script.clone()))
        .unwrap()
        .build()
        .await
        .unwrap();
    let caller = Arc::new(Mutex::new(String::new()));
    let save = caller.clone();
    let address = bus.address.clone();
    let executor = SyncClient::start(
        Deadline::from_monotonic_ns(ns()).unwrap(),
        move || async move {
            let connection = zbus::connection::Builder::address(address.as_str())?
                .build()
                .await?;
            *save.lock().unwrap() = connection.unique_name().unwrap().to_string();
            Client::from_connection(connection).await
        },
    )
    .unwrap();
    let client = Box::into_raw(Box::new(SlkClient {
        inner: Arc::new(executor),
    }));
    let name = caller.lock().unwrap().clone();
    (bus, server, script, client, name)
}
unsafe fn observer(client: *mut SlkClient) -> *mut SlkControllerEvents {
    let mut out = std::ptr::null_mut();
    assert_eq!(
        unsafe { slk_client_controller_events(client, ns(), &mut out) },
        0
    );
    assert!(!out.is_null());
    out
}
fn id() -> SlkControllerId {
    SlkControllerId {
        generation: 999,
        index: 999,
        reserved: [0xff; 6],
    }
}
fn metadata() -> SlkControllerEvent {
    SlkControllerEvent {
        sequence: 999,
        oldest: 999,
        current: 999,
        kind: 999,
        reserved: 999,
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn c_peek_short_buffer_and_derived_reference_keep_original_caller() {
    let (_bus, server, s, client, caller) = fixture().await;
    let stream = unsafe { observer(client) };
    unsafe { slk_client_close(client) };
    let mut out = metadata();
    let mut count = 999;
    let mut ids = [id(), id()];
    assert_eq!(
        unsafe {
            slk_controller_events_next(
                stream,
                &mut out,
                std::ptr::null_mut(),
                0,
                &mut count,
                1,
                ns(),
            )
        },
        -nix::libc::ENOBUFS
    );
    assert_eq!(count, 2);
    assert_eq!(out, metadata());
    for flags in [1, 1, 0] {
        assert_eq!(
            unsafe {
                slk_controller_events_next(
                    stream,
                    &mut out,
                    ids.as_mut_ptr(),
                    2,
                    &mut count,
                    flags,
                    ns(),
                )
            },
            0
        );
        assert_eq!((out.kind, out.sequence, count), (1, 0, 2));
        assert_eq!((ids[0].index, ids[0].generation), (2, 7));
        assert_eq!(ids[1].reserved, [0; 6]);
    }
    s.mode.store(1, Ordering::SeqCst);
    out = metadata();
    count = 999;
    assert_eq!(
        unsafe {
            slk_controller_events_next(
                stream,
                &mut out,
                std::ptr::null_mut(),
                0,
                &mut count,
                0,
                ns(),
            )
        },
        -nix::libc::ENOBUFS
    );
    assert_eq!(count, 1);
    assert_eq!(out, metadata());
    for (kind, sequence) in [(2, 1), (3, 2)] {
        assert_eq!(
            unsafe {
                slk_controller_events_next(
                    stream,
                    &mut out,
                    ids.as_mut_ptr(),
                    2,
                    &mut count,
                    0,
                    ns(),
                )
            },
            0
        );
        assert_eq!((out.kind, out.sequence, count), (kind, sequence, 1));
    }
    unsafe { slk_controller_events_close(stream) };
    let manager = zbus::fdo::DBusProxy::new(&server).await.unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    while manager
        .name_has_owner(caller.as_str().try_into().unwrap())
        .await
        .unwrap()
    {
        assert!(
            Instant::now() < deadline,
            "observer retained caller after final release"
        );
        tokio::task::yield_now().await;
    }
    assert!(
        manager
            .name_has_owner("org.sparklink".try_into().unwrap())
            .await
            .unwrap()
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn c_original_deadline_late_rpc_and_gap_do_not_advance_or_resnapshot() {
    let (_bus, _server, s, client, _) = fixture().await;
    let stream = unsafe { observer(client) };
    let mut out = metadata();
    let mut count = 999;
    let mut ids = [id(), id()];
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 0, ns())
        },
        0
    );
    s.mode.store(3, Ordering::SeqCst);
    let address = stream as usize;
    let pending = thread::spawn(move || {
        let mut output = metadata();
        let mut count = 999;
        let mut ids = [id(), id()];
        let short = slk_channel::deadline::Deadline::after(Duration::from_millis(500))
            .unwrap()
            .stamp()
            .monotonic_ns;
        let result = unsafe {
            slk_controller_events_next(
                address as *const SlkControllerEvents,
                &mut output,
                ids.as_mut_ptr(),
                2,
                &mut count,
                0,
                short,
            )
        };
        (result, output, count)
    });
    tokio::time::timeout(Duration::from_secs(2), s.entered.notified())
        .await
        .expect("actual original RPC did not enter");
    out = metadata();
    count = 999;
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 0, ns())
        },
        -nix::libc::EAGAIN
    );
    assert_eq!(out, metadata());
    assert_eq!(count, 999);
    let (result, output, actual_count) = pending.join().unwrap();
    assert_eq!(result, -nix::libc::ETIMEDOUT);
    assert_eq!(output, metadata());
    assert_eq!(actual_count, 999);
    s.mode.store(1, Ordering::SeqCst);
    s.release.notify_waiters();
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 0, ns())
        },
        0
    );
    assert_eq!((out.kind, out.sequence), (2, 1));
    unsafe { slk_controller_events_close(stream) };
    let stream = unsafe { observer(client) };
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 0, ns())
        },
        0
    );
    s.mode.store(2, Ordering::SeqCst);
    for flags in [1, 1, 0] {
        assert_eq!(
            unsafe {
                slk_controller_events_next(
                    stream,
                    &mut out,
                    std::ptr::null_mut(),
                    0,
                    &mut count,
                    flags,
                    ns(),
                )
            },
            0
        );
        assert_eq!(
            (out.kind, out.sequence, out.oldest, out.current, count),
            (4, 0, 2, 65, 0)
        );
    }
    out = metadata();
    count = 999;
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 0, ns())
        },
        -nix::libc::ESTALE
    );
    assert_eq!(out, metadata());
    assert_eq!(count, 999);
    unsafe {
        slk_controller_events_close(stream);
        slk_client_close(client)
    };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn c_owner_loss_cached_snapshot_and_invalid_arguments_preserve_outputs() {
    let (_bus, server, _s, client, _) = fixture().await;
    let stream = unsafe { observer(client) };
    let mut out = metadata();
    let mut count = 999;
    let mut ids = [id(), id()];
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 1, ns())
        },
        0
    );
    server.release_name("org.sparklink").await.unwrap();
    server.request_name("org.sparklink").await.unwrap();
    out = metadata();
    count = 999;
    ids = [id(), id()];
    assert_eq!(
        unsafe {
            slk_controller_events_next(stream, &mut out, ids.as_mut_ptr(), 2, &mut count, 0, ns())
        },
        -nix::libc::ESTALE
    );
    for (capacity, flags) in [(257, 0), (0, 2)] {
        assert_eq!(
            unsafe {
                slk_controller_events_next(
                    stream,
                    &mut out,
                    ids.as_mut_ptr(),
                    capacity,
                    &mut count,
                    flags,
                    ns(),
                )
            },
            -nix::libc::EINVAL
        );
    }
    assert_eq!(
        unsafe {
            slk_controller_events_next(
                std::ptr::null(),
                &mut out,
                ids.as_mut_ptr(),
                2,
                &mut count,
                0,
                ns(),
            )
        },
        -nix::libc::EINVAL
    );
    assert_eq!(out, metadata());
    assert_eq!(count, 999);
    assert_eq!(ids[0].generation, 999);
    unsafe {
        slk_controller_events_close(stream);
        slk_client_close(client);
        slk_controller_events_close(std::ptr::null_mut())
    };
}
