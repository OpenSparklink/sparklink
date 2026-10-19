//! Actual C exports/private D-Bus/caller executor. Metadata fixture only;
//! production inbox/guard/syscalls execute;no daemon DB,wire,Kernel or RF proof.
use super::*;
use crate::ffi_service_authorization::*;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};

unsafe fn authorized(c: *const SlkClient) -> *mut SlkLocalService {
    let mut p = property();
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
unsafe fn notify_fd(v: *const SlkLocalService) -> OwnedFd {
    let mut fd = -1;
    assert_eq!(unsafe { slk_local_service_authorization_fd(v, &mut fd) }, 0);
    unsafe { OwnedFd::from_raw_fd(fd) }
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
        assert!(Instant::now() < end, "actual notification missing");
        tokio::task::yield_now().await;
    }
}
unsafe fn next(v: *const SlkLocalService) -> *mut SlkAuthorizationRequest {
    let mut out = std::ptr::null_mut();
    assert_eq!(
        unsafe { slk_local_service_next_authorization(v, &mut out) },
        0
    );
    assert!(!out.is_null());
    out
}
unsafe fn info(r: *const SlkAuthorizationRequest) -> SlkAuthorizationRequestInfo {
    let mut v = std::mem::MaybeUninit::uninit();
    assert_eq!(
        unsafe { slk_authorization_request_info(r, v.as_mut_ptr()) },
        0
    );
    unsafe { v.assume_init() }
}
fn callback(
    server: &zbus::Connection,
    s: &Script,
    p: slk_contract::ssap::SsapAuthorizationPrompt,
) -> tokio::task::JoinHandle<bool> {
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
                &(p,),
            )
            .await
            .unwrap()
            .body()
            .deserialize::<bool>()
            .unwrap()
    })
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_inbox_answers_while_same_executor_is_blocked_and_holds_capacity_until_release() {
    let (_bus, server, s, c) = fixture().await;
    let v = unsafe { authorized(c) };
    let fd = unsafe { notify_fd(v) };
    assert!(!ready(&fd));
    let mut sentinel = std::ptr::dangling_mut();
    assert_eq!(
        unsafe { slk_local_service_next_authorization(v, &mut sentinel) },
        -nix::libc::EAGAIN
    );
    assert_eq!(sentinel, std::ptr::dangling_mut());
    // Parent Client closes;the derived service retains the original actual caller.
    unsafe { slk_client_close(c) };
    s.mode.store(8, Ordering::SeqCst);
    let raw = v as usize;
    let job = std::thread::spawn(move || {
        let mut b = [0xaa; 8];
        let mut n = 99;
        let result = unsafe {
            slk_local_service_read(
                raw as *const SlkLocalService,
                17,
                b.as_mut_ptr(),
                8,
                &mut n,
                ns(),
            )
        };
        (result, b, n)
    });
    wait_ready(&fd).await;
    let r = unsafe { next(v) };
    let snapshot = unsafe { info(r) };
    assert_eq!(
        (
            snapshot.controller.index,
            snapshot.controller.generation,
            snapshot.property,
            snapshot.value_length
        ),
        (2, 7, 17, 0)
    );
    assert_eq!(
        (snapshot.local_tcid, snapshot.remote_tcid, snapshot.pi),
        (10, 10, 0)
    );
    assert_eq!(snapshot.data_type, 0);
    assert!(!ready(&fd));
    assert_eq!(
        unsafe { slk_authorization_request_reply(r, 2) },
        -nix::libc::EINVAL
    );
    assert_eq!(unsafe { slk_authorization_request_reply(r, 1) }, 0);
    let (result, b, n) = job.join().unwrap();
    assert_eq!(result, 0);
    assert_eq!((n, &b[..n]), (3, [7, 8, 9].as_slice()));
    assert_eq!(
        unsafe { slk_authorization_request_reply(r, 1) },
        -nix::libc::ESTALE
    );
    // Completed callback still charged while its delivered view survives.
    assert!(!callback(&server, &s, approval_prompt(ns())).await.unwrap());
    unsafe { slk_authorization_request_free(r) };
    let message = callback(&server, &s, approval_prompt(ns()));
    wait_ready(&fd).await;
    let r = unsafe { next(v) };
    assert!(unsafe { info(r) }.token > snapshot.token);
    unsafe { slk_authorization_request_free(r) };
    assert!(!message.await.unwrap(), "drop must actually deny");
    s.mode.store(0, Ordering::SeqCst);
    assert_eq!(unsafe { slk_local_service_unregister(v, ns()) }, 0);
    assert!(ready(&fd));
    assert_eq!(
        unsafe { slk_local_service_next_authorization(v, &mut sentinel) },
        -nix::libc::ESHUTDOWN
    );
    unsafe { slk_local_service_free(v) };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_expiry_stop_uncertain_withdrawal_and_owner_loss_wake_without_reviving_requests() {
    for case in 0..3 {
        let (_bus, server, s, c) = fixture().await;
        let v = unsafe { authorized(c) };
        let fd = unsafe { notify_fd(v) };
        let deadline = if case == 0 {
            crate::Deadline::after(Duration::from_millis(500))
                .unwrap()
                .stamp()
                .monotonic_ns
        } else {
            ns()
        };
        let message = callback(&server, &s, approval_prompt(deadline));
        wait_ready(&fd).await;
        let r = unsafe { next(v) };
        if case == 0 {
            assert!(!message.await.unwrap());
            assert_eq!(
                unsafe { slk_authorization_request_reply(r, 1) },
                -nix::libc::ETIMEDOUT
            );
        } else if case == 1 {
            s.mode.store(5, Ordering::SeqCst);
            assert_eq!(
                unsafe { slk_local_service_unregister(v, ns()) },
                -nix::libc::ETIMEDOUT
            );
            assert!(ready(&fd));
            assert_eq!(
                unsafe { slk_authorization_request_reply(r, 1) },
                -nix::libc::ESHUTDOWN
            );
            assert!(!message.await.unwrap());
            assert!(!callback(&server, &s, approval_prompt(ns())).await.unwrap());
        } else {
            server.release_name("org.sparklink").await.unwrap();
            server.request_name("org.sparklink").await.unwrap();
            wait_ready(&fd).await;
            assert_eq!(
                unsafe { slk_authorization_request_reply(r, 1) },
                -nix::libc::ESTALE
            );
            assert!(!message.await.unwrap());
        }
        let snap = unsafe { info(r) };
        assert_eq!(snap.deadline_ns, deadline);
        unsafe { slk_local_service_free(v) };
        assert_ne!(unsafe { slk_authorization_request_reply(r, 1) }, 0);
        unsafe {
            slk_authorization_request_free(r);
            slk_client_close(c)
        };
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn foreign_sender_and_ambiguous_receipts_never_dispatch_policy() {
    let (bus, server, s, c) = fixture().await;
    let v = unsafe { authorized(c) };
    let fd = unsafe { notify_fd(v) };
    let foreign = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let owner = s.owner.lock().unwrap().clone();
    let path = s.authorizer.lock().unwrap().clone();
    let result = foreign
        .call_method(
            Some(owner.as_str()),
            path.as_str(),
            Some("org.sparklink.SsapAuthorizer"),
            "AuthorizeValue",
            &(approval_prompt(ns()),),
        )
        .await;
    assert!(
        matches!(result,Err(zbus::Error::MethodError(name,_,_))if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    assert!(!ready(&fd));
    // Deliberately duplicated fixture receipt;production dispatcher must not choose first.
    let other = unsafe { authorized(c) };
    assert!(!callback(&server, &s, approval_prompt(ns())).await.unwrap());
    assert!(!ready(&fd));
    unsafe { slk_local_service_free(other) };
    let m = callback(&server, &s, approval_prompt(ns()));
    wait_ready(&fd).await;
    let r = unsafe { next(v) };
    unsafe { slk_local_service_free(v) };
    assert!(ready(&fd));
    assert!(!m.await.unwrap());
    assert_eq!(
        unsafe { slk_authorization_request_reply(r, 1) },
        -nix::libc::ESHUTDOWN
    );
    unsafe {
        slk_authorization_request_free(r);
        slk_client_close(c)
    };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retired_untyped_callback_and_other_data_type_never_enter_the_policy_inbox() {
    let (_bus, server, s, c) = fixture().await;
    let view = unsafe { authorized(c) };
    let fd = unsafe { notify_fd(view) };
    let original = approval_prompt(ns());
    let old = (
        original.0,
        original.1,
        original.2,
        original.3,
        original.4,
        original.5.clone(),
    );
    let owner = s.owner.lock().unwrap().clone();
    let path = s.authorizer.lock().unwrap().clone();
    let error = tokio::time::timeout(
        Duration::from_secs(2),
        server.call_method(
            Some(owner.as_str()),
            path.as_str(),
            Some("org.sparklink.SsapAuthorizer"),
            "AuthorizeValue",
            &(old,),
        ),
    )
    .await
    .expect("retired-shape original test deadline")
    .unwrap_err();
    assert!(
        matches!(&error, zbus::Error::MethodError(name,Some(message),_)
            if name.as_str()=="org.freedesktop.zbus.Error"
                && message=="Signature mismatch: got `(t(qttqtuyyy)qbtay)`, expected `(t(qttqtuyyy)qbtayy)`"),
        "unexpected retired-shape error: {error:?}"
    );
    assert!(!ready(&fd));
    for data_type in [1, 2, 3, 255] {
        let mut p = approval_prompt(ns());
        p.6 = data_type;
        assert!(
            !tokio::time::timeout(Duration::from_secs(2), callback(&server, &s, p))
                .await
                .expect("typed refusal original test deadline")
                .unwrap()
        );
        assert!(!ready(&fd));
    }
    // The real production endpoint/inbox remains usable after every refusal.
    // A dead dispatcher is not successful unsupported-target handling.
    let valid = callback(&server, &s, approval_prompt(ns()));
    wait_ready(&fd).await;
    let request = unsafe { next(view) };
    assert_eq!(unsafe { info(request) }.data_type, 0);
    assert_eq!(unsafe { slk_authorization_request_reply(request, 1) }, 0);
    assert!(
        tokio::time::timeout(Duration::from_secs(2), valid)
            .await
            .expect("healthy request original test deadline")
            .unwrap()
    );
    unsafe {
        slk_authorization_request_free(request);
        slk_local_service_free(view);
        slk_client_close(c);
    }
}

#[test]
fn actual_request_info_layout_is_fixed_and_null_outputs_remain_unchanged() {
    assert_eq!(std::mem::size_of::<SlkAuthorizationRequestInfo>(), 2120);
    assert_eq!(
        std::mem::offset_of!(SlkAuthorizationRequestInfo, data_type),
        70
    );
    assert_eq!(std::mem::offset_of!(SlkAuthorizationRequestInfo, value), 72);
    let mut out = std::ptr::dangling_mut();
    assert_eq!(
        unsafe { slk_local_service_next_authorization(std::ptr::null(), &mut out) },
        -nix::libc::EINVAL
    );
    assert_eq!(out, std::ptr::dangling_mut());
    let mut fd = 99;
    assert_eq!(
        unsafe { slk_local_service_authorization_fd(std::ptr::null(), &mut fd) },
        -nix::libc::EINVAL
    );
    assert_eq!(fd, 99);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retiring_request_keeps_actual_sixteen_slot_budget_until_release_and_drain() {
    let (_bus, server, s, c) = fixture().await;
    let v = unsafe { authorized(c) };
    let dispatcher = unsafe { &*c }.inner.authorizers().clone();
    let properties = [(
        slk_protocol::SsapOperations::from_bits(5).unwrap(),
        slk_protocol::ssap::access::SsapAccess::from_bits(36).unwrap(),
    )];
    let id = slk_contract::ControllerId {
        index: 2,
        generation: 7,
    };
    let mut reservations = Vec::new();
    for i in 0..15 {
        let q = dispatcher.reserve(id, &properties).unwrap();
        q.bind(&[18 + i]).unwrap();
        reservations.push(q);
    }
    assert!(matches!(dispatcher.reserve(id,&properties),Err(e)if e==nix::libc::EAGAIN));
    let fd = unsafe { notify_fd(v) };
    let message = callback(&server, &s, approval_prompt(ns()));
    wait_ready(&fd).await;
    let request = unsafe { next(v) };
    unsafe { slk_local_service_free(v) };
    assert!(!message.await.unwrap());
    assert!(
        matches!(dispatcher.reserve(id,&properties),Err(e)if e==nix::libc::EAGAIN),
        "retained request is not drained capacity"
    );
    unsafe { slk_authorization_request_free(request) };
    let extra = dispatcher.reserve(id, &properties).unwrap();
    drop(extra);
    drop(reservations);
    unsafe { slk_client_close(c) };
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn plain_unknown_and_expired_registration_modes_have_no_approval_fallback() {
    let (_bus, _server, s, c) = fixture().await;
    let mut p = property();
    p.access = 36;
    for (mode, deadline, error) in [
        (0, ns(), nix::libc::EOPNOTSUPP),
        (2, ns(), nix::libc::EOPNOTSUPP),
        (1, 1, nix::libc::ETIMEDOUT),
    ] {
        let mut out = std::ptr::dangling_mut();
        assert_eq!(
            unsafe {
                slk_client_register_local_service(
                    c,
                    &id(),
                    [1, 0].as_ptr(),
                    2,
                    &p,
                    1,
                    mode,
                    deadline,
                    &mut out,
                )
            },
            -error
        );
        assert_eq!(out, std::ptr::dangling_mut());
    }
    assert_eq!(s.registrations.load(Ordering::SeqCst), 0);
    let (e, v) = unsafe { acquire(c, ns()) };
    assert_eq!(e, 0);
    let mut fd = 99;
    assert_eq!(
        unsafe { slk_local_service_authorization_fd(v, &mut fd) },
        -nix::libc::EOPNOTSUPP
    );
    assert_eq!(fd, 99);
    unsafe {
        slk_local_service_free(v);
        slk_client_close(c)
    };
}
