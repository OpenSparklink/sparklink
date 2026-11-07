//! Actual exports/private bus/shared production queue and callback guards.
//! Parent fixture supplies broker metadata/errors only; no daemon DB, wire,
//! kernel, RF or complete concurrent-lifetime qualification is claimed.
use super::*;
use crate::ffi_service_authorization::*;
use crate::ffi_service_provider::*;
use crate::ssap::provider::frontend::{Dispatcher, PATH as PROVIDER_PATH};
use slk_contract::ssap::{ReadProviderReply, ReadProviderRequest};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};

unsafe fn service(c: *const SlkClient) -> *mut SlkLocalService {
    let mut p = property();
    p.operations = 1;
    p.access = 36;
    let mut out = std::ptr::null_mut();
    assert_eq!(
        unsafe {
            slk_client_register_local_service(
                c,
                &id(),
                [1, 0].as_ptr(),
                2,
                &p,
                1,
                1,
                ns(),
                &mut out,
            )
        },
        0
    );
    out
}
unsafe fn bind(v: *mut SlkLocalService) -> *mut SlkReadProvider {
    let mut out = std::ptr::null_mut();
    assert_eq!(
        unsafe { slk_local_service_bind_read_provider(v, 17, ns(), &mut out) },
        0
    );
    out
}
unsafe fn fd(v: *const SlkReadProvider) -> OwnedFd {
    let mut out = -1;
    assert_eq!(unsafe { slk_read_provider_fd(v, &mut out) }, 0);
    unsafe { OwnedFd::from_raw_fd(out) }
}
fn ready(fd: &OwnedFd) -> bool {
    let mut p = nix::libc::pollfd {
        fd: fd.as_raw_fd(),
        events: nix::libc::POLLIN,
        revents: 0,
    };
    assert!(unsafe { nix::libc::poll(&mut p, 1, 0) } >= 0);
    p.revents & nix::libc::POLLIN != 0
}
async fn wait_ready(fd: &OwnedFd) {
    let end = Instant::now() + Duration::from_secs(2);
    while !ready(fd) {
        assert!(Instant::now() < end, "actual Provider notification missing");
        tokio::task::yield_now().await;
    }
}
unsafe fn next(v: *const SlkReadProvider) -> *mut SlkReadProviderRequest {
    let mut out = std::ptr::null_mut();
    assert_eq!(unsafe { slk_read_provider_next(v, &mut out) }, 0);
    out
}
unsafe fn info(r: *const SlkReadProviderRequest) -> SlkReadProviderRequestInfo {
    let mut out = std::mem::MaybeUninit::uninit();
    assert_eq!(
        unsafe { slk_read_provider_request_info(r, out.as_mut_ptr()) },
        0
    );
    unsafe { out.assume_init() }
}
fn prompt(deadline_ns: u64) -> ReadProviderRequest {
    ReadProviderRequest {
        request_id: 1,
        identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
        property: 17,
        deadline_ns,
        maximum_bytes: 32,
    }
}
fn callback(
    server: &zbus::Connection,
    s: &Script,
    r: ReadProviderRequest,
) -> tokio::task::JoinHandle<zbus::Result<ReadProviderReply>> {
    let server = server.clone();
    let owner = s.owner.lock().unwrap().clone();
    let path = s.provider.lock().unwrap().clone();
    tokio::spawn(async move {
        server
            .call_method(
                Some(owner.as_str()),
                path.as_str(),
                Some("org.sparklink.SsapReadProvider"),
                "ReadValue",
                &(r,),
            )
            .await?
            .body()
            .deserialize()
    })
}

#[test]
fn provider_info_layout_and_ffi_invalid_outputs_are_explicit() {
    use std::mem::{offset_of, size_of};
    assert_eq!(size_of::<SlkReadProviderRequestInfo>(), 80);
    assert_eq!(offset_of!(SlkReadProviderRequestInfo, token), 16);
    assert_eq!(offset_of!(SlkReadProviderRequestInfo, security_level), 56);
    assert_eq!(offset_of!(SlkReadProviderRequestInfo, maximum_bytes), 64);
    assert_eq!(offset_of!(SlkReadProviderRequestInfo, reserved), 69);
    let mut sentinel = std::ptr::dangling_mut();
    assert_eq!(
        unsafe { slk_read_provider_next(std::ptr::null(), &mut sentinel) },
        -nix::libc::EINVAL
    );
    assert_eq!(sentinel, std::ptr::dangling_mut());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_value_inbox_answers_while_same_executor_is_blocked_and_holds_capacity() {
    let (_bus, server, s, c) = fixture_with_operations(1).await;
    let v = unsafe { service(c) };
    let p = unsafe { bind(v) };
    let f = unsafe { fd(p) };
    assert_eq!(*s.provider.lock().unwrap(), PROVIDER_PATH);
    let mut sentinel = std::ptr::dangling_mut();
    assert_eq!(
        unsafe { slk_read_provider_next(p, &mut sentinel) },
        -nix::libc::EAGAIN
    );
    assert_eq!(sentinel, std::ptr::dangling_mut());
    unsafe { slk_client_close(c) }; // Service, not inbox, retains original caller.
    s.mode.store(9, Ordering::SeqCst);
    let raw = v as usize;
    let worker = std::thread::spawn(move || {
        let mut b = [0xaa; 32];
        let mut n = 99;
        let status = unsafe {
            slk_local_service_read(
                raw as *const SlkLocalService,
                17,
                b.as_mut_ptr(),
                32,
                &mut n,
                ns(),
            )
        };
        (status, b, n)
    });
    wait_ready(&f).await;
    let r = unsafe { next(p) };
    let first = unsafe { info(r) };
    assert_eq!(
        (
            first.controller.index,
            first.controller.generation,
            first.connection_lifetime,
            first.security_epoch,
            first.property,
            first.maximum_bytes
        ),
        (2, 7, 13, 41, 17, 32)
    );
    assert_eq!(first.reserved, [0; 11]);
    assert!(!ready(&f));
    let value = [0xa1, 0xb2, 0xc3];
    assert_eq!(
        unsafe { slk_read_provider_request_reply(r, 0, value.as_ptr(), value.len()) },
        0
    );
    let (status, b, n) = worker.join().unwrap();
    assert_eq!((status, n, &b[..n]), (0, 3, value.as_slice()));
    assert_eq!(
        unsafe { slk_read_provider_request_reply(r, 0, std::ptr::null(), 0) },
        -nix::libc::ESTALE
    );
    assert_eq!(
        callback(&server, &s, prompt(ns())).await.unwrap().unwrap(),
        (0xaf, vec![])
    );
    unsafe { slk_read_provider_request_free(r) };
    let call = callback(&server, &s, prompt(ns()));
    wait_ready(&f).await;
    let r = unsafe { next(p) };
    assert!(unsafe { info(r) }.token > first.token);
    unsafe { slk_read_provider_request_free(r) }; // Unanswered, no implicit value.
    assert_eq!(call.await.unwrap().unwrap(), (0xaf, vec![]));
    assert_eq!(unsafe { slk_local_service_unregister(v, ns()) }, 0);
    unsafe {
        slk_read_provider_free(p);
        slk_local_service_free(v)
    };
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_provider_preserves_empty_values_and_errors_and_rejects_invalid_without_consuming() {
    let (_bus, server, s, c) = fixture_with_operations(1).await;
    let v = unsafe { service(c) };
    let p = unsafe { bind(v) };
    let f = unsafe { fd(p) };
    for (status, maximum_bytes, value) in [
        (0, 0, vec![]),
        (0, 32, vec![]),
        (0, 32, vec![0x53; 32]),
        (0, 2042, vec![0x7d; 2042]),
        (0xaf, 32, vec![]),
        (0xff, 32, vec![]),
    ] {
        let mut original = prompt(ns());
        original.maximum_bytes = maximum_bytes;
        let call = callback(&server, &s, original);
        wait_ready(&f).await;
        let r = unsafe { next(p) };
        assert_eq!(unsafe { info(r) }.maximum_bytes, maximum_bytes);
        for bad in [1, 9, 0xae, 0x100, u16::MAX] {
            assert_eq!(
                unsafe { slk_read_provider_request_reply(r, bad, std::ptr::null(), 0) },
                -nix::libc::EINVAL
            );
        }
        assert_eq!(
            unsafe { slk_read_provider_request_reply(r, 0xaf, [1].as_ptr(), 1) },
            -nix::libc::EINVAL
        );
        // The real public reply rejects 1/33/2043 bytes for the respective
        // original 0/32/2042 budgets, without consuming the request. The same
        // callback must then deliver its exact legal empty/full value below.
        let oversized = vec![0x81; usize::from(maximum_bytes) + 1];
        assert_eq!(
            unsafe { slk_read_provider_request_reply(r, 0, oversized.as_ptr(), oversized.len()) },
            -nix::libc::EMSGSIZE
        );
        assert_eq!(
            unsafe { slk_read_provider_request_reply(r, 0, std::ptr::null(), 1) },
            -nix::libc::EINVAL
        );
        assert_eq!(
            unsafe { slk_read_provider_request_reply(r, status, value.as_ptr(), value.len()) },
            0
        );
        assert_eq!(call.await.unwrap().unwrap(), (status, value));
        unsafe { slk_read_provider_request_free(r) };
    }
    unsafe {
        slk_read_provider_free(p);
        slk_local_service_free(v);
        slk_client_close(c)
    };
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_provider_checks_sender_identity_and_budget_before_dispatch() {
    let (bus, server, s, c) = fixture_with_operations(1).await;
    let v = unsafe { service(c) };
    let p = unsafe { bind(v) };
    let f = unsafe { fd(p) };
    for case in 0..10 {
        let mut r = prompt(ns());
        match case {
            0 => r.request_id = 0,
            1 => r.identity.0 = 3,
            2 => r.identity.1 = 8,
            3 => r.identity.2 = 0,
            4 => r.identity.4 = 0,
            5 => r.identity.6 = 11,
            6 => r.property = 18,
            7 => r.maximum_bytes = 2043,
            8 => r.deadline_ns = 1,
            _ => r.identity.5 = 3,
        }
        assert_eq!(
            callback(&server, &s, r).await.unwrap().unwrap(),
            (0xaf, vec![])
        );
        assert!(!ready(&f));
    }
    let foreign = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    assert!(callback(&foreign, &s, prompt(ns())).await.unwrap().is_err());
    assert!(!ready(&f));
    unsafe {
        slk_read_provider_free(p);
        slk_local_service_free(v);
        slk_client_close(c)
    };
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_original_expiry_free_and_withdrawal_stop_old_requests_without_rebind() {
    for case in 0..4 {
        let (_bus, server, s, c) = fixture_with_operations(1).await;
        let v = unsafe { service(c) };
        let p = unsafe { bind(v) };
        let f = unsafe { fd(p) };
        let deadline = if case == 0 {
            slk_channel::deadline::Deadline::after(Duration::from_millis(40))
                .unwrap()
                .stamp()
                .monotonic_ns
        } else {
            ns()
        };
        let call = callback(&server, &s, prompt(deadline));
        wait_ready(&f).await;
        let r = unsafe { next(p) };
        let expected = match case {
            0 => {
                tokio::time::sleep(Duration::from_millis(50)).await;
                nix::libc::ETIMEDOUT
            }
            1 => {
                unsafe { slk_read_provider_free(p) };
                nix::libc::ESHUTDOWN
            }
            2 => {
                assert_eq!(unsafe { slk_local_service_unregister(v, ns()) }, 0);
                nix::libc::ESHUTDOWN
            }
            _ => {
                unsafe { slk_local_service_free(v) };
                nix::libc::ESHUTDOWN
            }
        };
        assert_eq!(
            unsafe { slk_read_provider_request_reply(r, 0, [3].as_ptr(), 1) },
            -expected
        );
        assert_eq!(unsafe { info(r) }.deadline_ns, deadline);
        assert_eq!(call.await.unwrap().unwrap(), (0xaf, vec![]));
        unsafe { slk_read_provider_request_free(r) };
        if case != 3 {
            let mut sentinel = std::ptr::dangling_mut();
            assert!(
                unsafe { slk_local_service_bind_read_provider(v, 17, ns(), &mut sentinel) } < 0
            );
            assert_eq!(sentinel, std::ptr::dangling_mut());
            assert_eq!(s.provider_binds.load(Ordering::SeqCst), 1);
            unsafe { slk_local_service_free(v) };
        }
        if case != 1 {
            unsafe { slk_read_provider_free(p) }
        }
        unsafe { slk_client_close(c) };
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_owner_loss_wakes_inbox_and_rejects_surviving_request() {
    let (_bus, server, s, c) = fixture_with_operations(1).await;
    let v = unsafe { service(c) };
    let p = unsafe { bind(v) };
    let f = unsafe { fd(p) };
    let call = callback(&server, &s, prompt(ns()));
    wait_ready(&f).await;
    let r = unsafe { next(p) };
    server.release_name("org.sparklink").await.unwrap();
    wait_ready(&f).await;
    assert_eq!(
        unsafe { slk_read_provider_request_reply(r, 0, std::ptr::null(), 0) },
        -nix::libc::ESTALE
    );
    assert_eq!(call.await.unwrap().unwrap(), (0xaf, vec![]));
    unsafe {
        slk_read_provider_request_free(r);
        slk_read_provider_free(p);
        slk_local_service_free(v);
        slk_client_close(c)
    };
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_authorizer_and_provider_have_independent_slots_and_shared_service_stop() {
    let (_bus, server, s, c) = fixture_with_operations(1).await;
    let v = unsafe { service(c) };
    let p = unsafe { bind(v) };
    let value_fd = unsafe { fd(p) };
    let mut raw_fd = -1;
    assert_eq!(
        unsafe { slk_local_service_authorization_fd(v, &mut raw_fd) },
        0
    );
    let policy_fd = unsafe { OwnedFd::from_raw_fd(raw_fd) };
    let send_policy = || {
        let server = server.clone();
        let owner = s.owner.lock().unwrap().clone();
        let path = s.authorizer.lock().unwrap().clone();
        tokio::spawn(async move {
            server
                .call_method(
                    Some(owner.as_str()),
                    path.as_str(),
                    Some("org.sparklink.SsapAuthorizer"),
                    "AuthorizeValue",
                    &(approval_prompt(ns()),),
                )
                .await
                .unwrap()
                .body()
                .deserialize::<bool>()
                .unwrap()
        })
    };
    // Deliberately concurrent callback fixture, not a claim that the Engine
    // dispatches a value before authorization. It exercises separate budgets.
    let policy_call = send_policy();
    wait_ready(&policy_fd).await;
    let mut approval = std::ptr::null_mut();
    assert_eq!(
        unsafe { slk_local_service_next_authorization(v, &mut approval) },
        0
    );
    let value_call = callback(&server, &s, prompt(ns()));
    wait_ready(&value_fd).await;
    let request = unsafe { next(p) };
    assert!(!send_policy().await.unwrap());
    assert_eq!(
        callback(&server, &s, prompt(ns())).await.unwrap().unwrap(),
        (0xaf, vec![])
    );
    assert_eq!(unsafe { slk_local_service_unregister(v, ns()) }, 0);
    assert_eq!(
        unsafe { slk_authorization_request_reply(approval, 1) },
        -nix::libc::ESHUTDOWN
    );
    assert_eq!(
        unsafe { slk_read_provider_request_reply(request, 0, std::ptr::null(), 0) },
        -nix::libc::ESHUTDOWN
    );
    assert!(!policy_call.await.unwrap());
    assert_eq!(value_call.await.unwrap().unwrap(), (0xaf, vec![]));
    assert!(ready(&policy_fd));
    assert!(ready(&value_fd));
    unsafe {
        slk_authorization_request_free(approval);
        slk_read_provider_request_free(request);
        slk_read_provider_free(p);
        slk_local_service_free(v);
        slk_client_close(c);
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn uncertain_bind_keeps_original_attempt_and_closes_late_callback() {
    let (_bus, server, s, c) = fixture_with_operations(1).await;
    let v = unsafe { service(c) };
    s.mode.store(13, Ordering::SeqCst);
    let deadline = slk_channel::deadline::Deadline::after(Duration::from_millis(30))
        .unwrap()
        .stamp()
        .monotonic_ns;
    let mut sentinel = std::ptr::dangling_mut();
    assert_eq!(
        unsafe { slk_local_service_bind_read_provider(v, 17, deadline, &mut sentinel) },
        -nix::libc::ETIMEDOUT
    );
    assert_eq!(sentinel, std::ptr::dangling_mut());
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert_eq!(
        callback(&server, &s, prompt(ns())).await.unwrap().unwrap(),
        (0xaf, vec![])
    );
    assert_eq!(
        unsafe { slk_local_service_bind_read_provider(v, 17, ns(), &mut sentinel) },
        -nix::libc::EALREADY
    );
    assert_eq!(s.provider_binds.load(Ordering::SeqCst), 1);
    unsafe {
        slk_local_service_free(v);
        slk_client_close(c)
    };
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_client_identity_and_reportable_guard_are_production_checks() {
    let (bus, server, _s, _c) = fixture_with_operations(1).await;
    // Use actual Rust Client/registration/bind, not a test-only queue constructor.
    let connect = || async {
        Client::from_connection(
            zbus::connection::Builder::address(bus.address.as_str())
                .unwrap()
                .build()
                .await
                .unwrap(),
        )
        .await
        .unwrap()
    };
    let client = connect().await;
    let foreign = connect().await;
    let view = client.controller(PATH).await.unwrap();
    let mut registration = view
        .local_services()
        .register_service(
            vec![1, 0],
            vec![(vec![2, 0], 1, 0, vec![7, 8, 9])],
            zbus::zvariant::OwnedObjectPath::try_from("/").unwrap(),
            slk_channel::deadline::Deadline::after(Duration::from_secs(2)).unwrap(),
        )
        .await
        .unwrap();
    let d = Dispatcher::new(
        &client,
        zbus::zvariant::OwnedObjectPath::try_from(PROVIDER_PATH).unwrap(),
    )
    .unwrap();
    let watch = d.watch();
    let wrong = Dispatcher::new(
        &foreign,
        zbus::zvariant::OwnedObjectPath::try_from(PROVIDER_PATH).unwrap(),
    )
    .unwrap();
    assert!(
        wrong
            .bind(
                &mut registration,
                17,
                slk_channel::deadline::Deadline::after(Duration::from_secs(2)).unwrap()
            )
            .await
            .is_err()
    );
    let inbox = d
        .bind(
            &mut registration,
            17,
            slk_channel::deadline::Deadline::after(Duration::from_secs(2)).unwrap(),
        )
        .await
        .unwrap();
    let original = prompt(ns());
    let dispatch = d.dispatch(original.clone(), server.unique_name().map(|n| n.as_str()));
    let answer = async {
        let request = inbox.next().await.unwrap();
        assert!(request.is_active());
        assert_eq!(request.request().deadline_ns, original.deadline_ns);
        request.reply(0, &[0x7d]).unwrap();
        request
    };
    let (outcome, request) = tokio::join!(dispatch, answer);
    let outcome = outcome.unwrap();
    assert!(outcome.reportable());
    assert_eq!(outcome.reply(), &(0, vec![0x7d]));
    drop(request); // Still charged by actual endpoint outcome, as CLI logs now.
    assert!(
        !d.dispatch(prompt(ns()), server.unique_name().map(|n| n.as_str()))
            .await
            .unwrap()
            .reportable()
    );
    assert_eq!(outcome.into_reply(), (0, vec![0x7d]));
    let dispatch = d.dispatch(prompt(ns()), server.unique_name().map(|n| n.as_str()));
    let stop = async {
        let r = inbox.next().await.unwrap();
        drop(registration);
        assert!(!r.is_active());
        assert_eq!(
            r.reply(0, &[]).unwrap_err().raw_os_error(),
            Some(nix::libc::ESHUTDOWN)
        );
    };
    let (outcome, ()) = tokio::join!(dispatch, stop);
    assert!(!outcome.unwrap().reportable());
    drop(watch);
    drop(inbox);
    unsafe { slk_client_close(_c) };
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dispatcher_capacity_waits_for_last_queue_reference_not_readiness_fd() {
    use crate::ssap::local::ServiceRegistration;
    use slk_channel::deadline::Deadline;

    async fn register(client: &Client) -> ServiceRegistration {
        client
            .controller(PATH)
            .await
            .unwrap()
            .local_services()
            .register_service(
                vec![1, 0],
                vec![(vec![2, 0], 1, 0, vec![7, 8, 9])],
                zbus::zvariant::OwnedObjectPath::try_from("/").unwrap(),
                Deadline::after(Duration::from_secs(2)).unwrap(),
            )
            .await
            .unwrap()
    }
    let deadline = || Deadline::after(Duration::from_secs(2)).unwrap();
    for request_first in [true, false] {
        let (bus, server, _script, fixture_client) = fixture_with_operations(1).await;
        let client = Client::from_connection(
            zbus::connection::Builder::address(bus.address.as_str())
                .unwrap()
                .build()
                .await
                .unwrap(),
        )
        .await
        .unwrap();
        let dispatcher = Dispatcher::new(
            &client,
            zbus::zvariant::OwnedObjectPath::try_from(PROVIDER_PATH).unwrap(),
        )
        .unwrap();
        let weak = Arc::downgrade(&dispatcher);
        let watch = dispatcher.watch();
        let mut registration = register(&client).await;
        let inbox = dispatcher
            .bind(&mut registration, 17, deadline())
            .await
            .unwrap();
        let notification = inbox.fd().unwrap();
        let duplicate = notification.try_clone().unwrap();
        let dispatch = dispatcher.dispatch(prompt(ns()), server.unique_name().map(|n| n.as_str()));
        let answer = async {
            let request = inbox.next().await.unwrap();
            request.reply(0, &[0x7d]).unwrap();
            request
        };
        let (outcome, request) = tokio::join!(dispatch, answer);
        let mut outcome = Some(outcome.unwrap());
        let mut request = Some(request);
        assert!(outcome.as_ref().unwrap().reportable());

        // The broker fixture returns the same property metadata per registration.
        // Dispatch above precedes these additional registrations: this tests the
        // actual allocator/reference budget, not daemon handle allocation or
        // simultaneous routing of identically keyed properties.
        let mut held = Vec::new();
        for _ in 0..15 {
            let mut registration = register(&client).await;
            let inbox = dispatcher
                .bind(&mut registration, 17, deadline())
                .await
                .unwrap();
            held.push((registration, inbox));
        }
        let mut overflow = register(&client).await;
        let full = |result| match result {
            Err(ApplicationError::Io(e)) => assert_eq!(e.raw_os_error(), Some(nix::libc::EAGAIN)),
            _ => panic!("dispatcher must reject the seventeenth live queue"),
        };
        full(dispatcher.bind(&mut overflow, 17, deadline()).await);

        // Close admission while retaining the actual request and callback outcome.
        // Neither a duplicated notification fd nor retained request grants reply.
        drop(registration);
        drop(inbox);
        assert!(ready(&notification) && ready(&duplicate));
        assert_eq!(
            request
                .as_ref()
                .unwrap()
                .reply(0, &[0x7e])
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::ESHUTDOWN)
        );
        full(dispatcher.bind(&mut overflow, 17, deadline()).await);
        if request_first {
            drop(request.take());
        } else {
            drop(outcome.take());
        }
        full(dispatcher.bind(&mut overflow, 17, deadline()).await);
        drop(request.take());
        drop(outcome.take());
        let replacement = dispatcher
            .bind(&mut overflow, 17, deadline())
            .await
            .unwrap();
        // Notification fds still exist, but cannot keep the original queue charged.
        assert!(ready(&notification) && ready(&duplicate));
        drop((overflow, replacement));
        drop(held);

        // A second complete fill demonstrates reclamation, not just one spare slot.
        let mut held = Vec::new();
        for _ in 0..16 {
            let mut registration = register(&client).await;
            let inbox = dispatcher
                .bind(&mut registration, 17, deadline())
                .await
                .unwrap();
            held.push((registration, inbox));
        }
        let mut overflow = register(&client).await;
        full(dispatcher.bind(&mut overflow, 17, deadline()).await);
        drop((overflow, held));
        drop(watch);
        drop(dispatcher);
        // The watch task holds Weak, not an independent dispatcher owner.
        assert!(weak.upgrade().is_none());
        assert!(ready(&notification) && ready(&duplicate));
        drop((notification, duplicate));
        unsafe { slk_client_close(fixture_client) };
    }
}
