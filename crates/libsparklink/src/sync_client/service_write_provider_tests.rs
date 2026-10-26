//! Actual C exports -> original SyncClient -> shared Dispatcher -> private bus.
//! Broker metadata/errors are parent fixtures; no daemon database/Native/RF claim.
use super::*;
use crate::ffi_service_write_provider::*;
use slk_contract::ssap::{WriteProviderReply, WriteProviderRequest};
use std::os::fd::{FromRawFd, OwnedFd};

unsafe fn service(c: *const SlkClient) -> *mut SlkLocalService {
    let mut p = property();
    p.operations = 6;
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
                0,
                ns(),
                &mut out,
            )
        },
        0
    );
    out
}
unsafe fn bind(v: *mut SlkLocalService) -> *mut SlkWriteProvider {
    let mut out = std::ptr::null_mut();
    assert_eq!(
        unsafe { slk_local_service_bind_write_provider(v, 17, ns(), &mut out) },
        0
    );
    out
}
unsafe fn info(r: *const SlkWriteProviderRequest) -> SlkWriteProviderRequestInfo {
    let mut out = std::mem::MaybeUninit::uninit();
    assert_eq!(
        unsafe { slk_write_provider_request_info(r, out.as_mut_ptr()) },
        0
    );
    unsafe { out.assume_init() }
}
async unsafe fn next(v: *const SlkWriteProvider) -> *mut SlkWriteProviderRequest {
    let mut out = std::ptr::null_mut();
    let limit = Instant::now() + Duration::from_secs(2);
    loop {
        let code = unsafe { slk_write_provider_next(v, &mut out) };
        if code == 0 {
            return out;
        }
        assert_eq!(code, -nix::libc::EAGAIN);
        assert!(Instant::now() < limit, "write callback did not arrive");
        tokio::task::yield_now().await;
    }
}
fn prompt(verify: bool) -> WriteProviderRequest {
    WriteProviderRequest {
        request_id: 7,
        identity: (2, 7, 13, 1, 41, 0, 10, 10, 0),
        property: 17,
        deadline_ns: ns(),
        operation: 13,
        data_type: 0,
        offset: 0,
        value: vec![0x31, 0x92, 0x00],
        verify,
    }
}
fn callback(
    server: &zbus::Connection,
    s: &Script,
    r: WriteProviderRequest,
) -> tokio::task::JoinHandle<zbus::Result<WriteProviderReply>> {
    let server = server.clone();
    let owner = s.owner.lock().unwrap().clone();
    let path = s.provider.lock().unwrap().clone();
    tokio::spawn(async move {
        server
            .call_method(
                Some(owner.as_str()),
                path.as_str(),
                Some("org.sparklink.SsapWriteProvider"),
                "WriteValue",
                &(r,),
            )
            .await?
            .body()
            .deserialize()
    })
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_write_ffi_preserves_bytes_and_invalid_reply_does_not_consume() {
    let (_bus, server, script, c) = fixture_with_operations(6).await;
    let v = unsafe { service(c) };
    let provider = unsafe { bind(v) };
    let mut rawfd = -1;
    assert_eq!(unsafe { slk_write_provider_fd(provider, &mut rawfd) }, 0);
    let fd = unsafe { OwnedFd::from_raw_fd(rawfd) };
    for (n, verify, command, bytes) in [
        (1, true, false, vec![0x31, 0x92, 0]),
        (2, false, false, vec![]),
        (3, false, true, vec![0; 2042]),
    ] {
        let mut p = prompt(verify);
        p.request_id = n;
        p.value = bytes.clone();
        p.operation = if command { 12 } else { 13 };
        let deadline = p.deadline_ns;
        let task = callback(&server, &script, p);
        let r = unsafe { next(provider).await };
        let i = unsafe { info(r) };
        assert_eq!(
            (
                i.request_id,
                i.connection_lifetime,
                i.security_epoch,
                i.deadline_ns
            ),
            (n, 13, 41, deadline)
        );
        assert_eq!(
            (
                i.controller.index,
                i.controller.generation,
                i.connection_handle,
                i.property
            ),
            (2, 7, 1, 17)
        );
        assert_eq!(
            (i.operation, i.data_type, i.offset, i.verify),
            (if command { 12 } else { 13 }, 0, 0, u8::from(verify))
        );
        assert_eq!((i.local_tcid, i.remote_tcid, i.pi), (10, 10, 0));
        assert_eq!(i.reserved, [0; 6]);
        let mut short = [0xa5; 2];
        let mut len = usize::MAX;
        if bytes.len() > short.len() {
            assert_eq!(
                unsafe {
                    slk_write_provider_request_value(r, short.as_mut_ptr(), short.len(), &mut len)
                },
                -nix::libc::ENOSPC
            );
            assert_eq!(short, [0xa5; 2]);
            assert_eq!(len, bytes.len());
        }
        let mut actual = vec![0u8; bytes.len()];
        assert_eq!(
            unsafe {
                slk_write_provider_request_value(r, actual.as_mut_ptr(), actual.len(), &mut len)
            },
            0
        );
        assert_eq!((actual, len), (bytes.clone(), bytes.len()));
        assert_eq!(
            unsafe { slk_write_provider_request_reply(r, 7, std::ptr::null(), 0) },
            -nix::libc::EINVAL
        );
        assert_eq!(
            unsafe { slk_write_provider_request_reply(r, 0xaf, [1].as_ptr(), 1) },
            -nix::libc::EINVAL
        );
        if verify {
            assert_eq!(
                unsafe { slk_write_provider_request_reply(r, 0, [0; 3].as_ptr(), 3) },
                -nix::libc::EINVAL
            );
        }
        let answer = if verify { bytes } else { vec![] };
        assert_eq!(
            unsafe { slk_write_provider_request_reply(r, 0, answer.as_ptr(), answer.len()) },
            0
        );
        assert_eq!(task.await.unwrap().unwrap(), (0, answer.clone()));
        assert_eq!(
            unsafe { slk_write_provider_request_reply(r, 0, answer.as_ptr(), answer.len()) },
            -nix::libc::ESTALE
        );
        unsafe { slk_write_provider_request_free(r) };
    }
    unsafe {
        slk_write_provider_free(provider);
        slk_local_service_free(v);
        slk_client_close(c);
    }
    drop(fd);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn write_admission_rejects_foreign_stale_and_malformed_without_dispatch() {
    let (bus, server, script, c) = fixture_with_operations(6).await;
    let v = unsafe { service(c) };
    let provider = unsafe { bind(v) };
    let other = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    assert!(
        callback(&other, &script, prompt(false))
            .await
            .unwrap()
            .is_err()
    );
    for case in 0..17 {
        let mut p = prompt(false);
        match case {
            0 => p.request_id = 0,
            1 => p.identity.1 += 1,
            2 => p.identity.2 = 0,
            3 => p.identity.3 = 0x1000,
            4 => p.identity.4 = 0,
            5 => p.identity.5 = 3,
            6 => p.identity.6 = 11,
            7 => p.property = 18,
            8 => p.deadline_ns = 1,
            9 => p.operation = 11,
            10 => p.data_type = 1,
            11 => p.offset = 1,
            12 => p.value = vec![0; 2043],
            13 => {
                p.operation = 12;
                p.verify = true;
            }
            14 => p.identity.0 = 0,
            15 => p.deadline_ns = u64::MAX,
            _ => p.identity.8 = 1,
        }
        assert_eq!(
            callback(&server, &script, p).await.unwrap().unwrap(),
            (0xaf, vec![]),
            "case {case}"
        );
        let mut out = std::ptr::null_mut();
        assert_eq!(
            unsafe { slk_write_provider_next(provider, &mut out) },
            -nix::libc::EAGAIN
        );
    }
    unsafe {
        slk_write_provider_free(provider);
        slk_local_service_free(v);
        slk_client_close(c);
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn write_original_expiry_service_stop_and_fd_dup_never_preserve_authority() {
    let (_bus, server, script, c) = fixture_with_operations(6).await;
    let v = unsafe { service(c) };
    let provider = unsafe { bind(v) };
    let mut p = prompt(false);
    p.deadline_ns = slk_channel::deadline::Deadline::after(Duration::from_millis(80))
        .unwrap()
        .stamp()
        .monotonic_ns;
    let task = callback(&server, &script, p);
    let r = unsafe { next(provider).await };
    assert_eq!(task.await.unwrap().unwrap(), (0xaf, vec![]));
    assert_eq!(
        unsafe { slk_write_provider_request_reply(r, 0, std::ptr::null(), 0) },
        -nix::libc::ETIMEDOUT
    );
    unsafe { slk_write_provider_request_free(r) };
    let task = callback(&server, &script, prompt(false));
    let r = unsafe { next(provider).await };
    let mut rawfd = -1;
    assert_eq!(unsafe { slk_write_provider_fd(provider, &mut rawfd) }, 0);
    let fd = unsafe { OwnedFd::from_raw_fd(rawfd) };
    unsafe { slk_local_service_free(v) };
    assert_eq!(task.await.unwrap().unwrap(), (0xaf, vec![]));
    assert_eq!(
        unsafe { slk_write_provider_request_reply(r, 0, std::ptr::null(), 0) },
        -nix::libc::ESHUTDOWN
    );
    unsafe {
        slk_write_provider_request_free(r);
        slk_write_provider_free(provider);
        slk_client_close(c)
    };
    drop(fd);
}
#[test]
fn write_ffi_layout_and_null_outputs_are_independent_contracts() {
    use std::mem::{align_of, offset_of, size_of};
    assert_eq!(
        (
            size_of::<SlkWriteProviderRequestInfo>(),
            align_of::<SlkWriteProviderRequestInfo>()
        ),
        (80, 8)
    );
    assert_eq!(offset_of!(SlkWriteProviderRequestInfo, offset), 64);
    assert_eq!(offset_of!(SlkWriteProviderRequestInfo, operation), 71);
    let mut output = std::ptr::null_mut();
    assert_eq!(
        unsafe {
            slk_local_service_bind_write_provider(std::ptr::null_mut(), 17, ns(), &mut output)
        },
        -nix::libc::EINVAL
    );
    let mut length = 999;
    assert_eq!(
        unsafe {
            slk_write_provider_request_value(std::ptr::null(), std::ptr::null_mut(), 0, &mut length)
        },
        -nix::libc::EINVAL
    );
    assert_eq!(length, 999);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn read_and_write_share_sixteen_slots_until_write_request_and_callback_drain() {
    use crate::ssap::provider::frontend::Dispatcher;
    use slk_channel::deadline::Deadline;
    let (bus, _server, _script, c) = fixture_with_operations(0).await;
    unsafe { slk_client_close(c) };
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
        zbus::zvariant::OwnedObjectPath::try_from("/mixed").unwrap(),
    )
    .unwrap();
    let _watch = dispatcher.watch();
    let controller = client.controller(PATH).await.unwrap();
    let register = |operations| {
        let controller = controller.clone();
        async move {
            controller
                .local_services()
                .register_service(
                    vec![1, 0],
                    vec![(vec![2, 0], operations, 0, vec![7, 8, 9])],
                    zbus::zvariant::OwnedObjectPath::try_from("/").unwrap(),
                    Deadline::after(Duration::from_secs(2)).unwrap(),
                )
                .await
                .unwrap()
        }
    };
    let mut writer = register(6).await;
    let inbox = dispatcher
        .bind_write(
            &mut writer,
            17,
            Deadline::after(Duration::from_secs(2)).unwrap(),
        )
        .await
        .unwrap();
    let mut registrations = Vec::new();
    let mut readers = Vec::new();
    for _ in 0..15 {
        let mut r = register(1).await;
        readers.push(
            dispatcher
                .bind(&mut r, 17, Deadline::after(Duration::from_secs(2)).unwrap())
                .await
                .unwrap(),
        );
        registrations.push(r);
    }
    // Metadata returns the same fixture handle in distinct registration scopes;
    // no multi-service wire routing or real database uniqueness is claimed.
    let mut extra = register(1).await;
    assert!(
        dispatcher
            .bind(
                &mut extra,
                17,
                Deadline::after(Duration::from_secs(2)).unwrap()
            )
            .await
            .is_err()
    );
    let d = dispatcher.clone();
    let sender = client.daemon_owner().to_string();
    let task = tokio::spawn(async move {
        d.dispatch_write(prompt(false), Some(&sender))
            .await
            .unwrap()
    });
    let request = inbox.next().await.unwrap();
    drop(inbox);
    assert_eq!(
        request.reply(0, &[]).unwrap_err().raw_os_error(),
        Some(nix::libc::ESHUTDOWN)
    );
    let outcome = task.await.unwrap();
    assert_eq!(outcome.reply(), &(0xaf, vec![]));
    drop(request);
    assert!(
        dispatcher
            .bind(
                &mut extra,
                17,
                Deadline::after(Duration::from_secs(2)).unwrap()
            )
            .await
            .is_err(),
        "callback drain still owns slot16"
    );
    drop(outcome);
    let last = dispatcher
        .bind(
            &mut extra,
            17,
            Deadline::after(Duration::from_secs(2)).unwrap(),
        )
        .await
        .unwrap();
    drop(last);
    drop(readers);
    drop(registrations);
}
struct ForeignWriter;
#[zbus::interface(name = "org.sparklink.SsapWriteProvider")]
impl ForeignWriter {
    fn marker(&self) -> bool {
        true
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn occupied_write_endpoint_removes_only_our_partial_read_installation() {
    use crate::ssap::provider::frontend::{Dispatcher, PATH as PROVIDER_PATH};
    let (bus, server, _script, c) = fixture_with_operations(6).await;
    unsafe { slk_client_close(c) };
    let connection = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .serve_at(PROVIDER_PATH, ForeignWriter)
        .unwrap()
        .build()
        .await
        .unwrap();
    let client = Client::from_connection(connection.clone()).await.unwrap();
    assert!(Dispatcher::install(&client).await.is_err());
    let proxy = zbus::fdo::IntrospectableProxy::builder(&server)
        .destination(connection.unique_name().unwrap().as_str())
        .unwrap()
        .path(PROVIDER_PATH)
        .unwrap()
        .build()
        .await
        .unwrap();
    let xml = proxy.introspect().await.unwrap();
    assert!(xml.contains("org.sparklink.SsapWriteProvider"));
    assert!(!xml.contains("org.sparklink.SsapReadProvider"));
    connection
        .object_server()
        .remove::<ForeignWriter, _>(PROVIDER_PATH)
        .await
        .unwrap();
    let d = Dispatcher::install(&client).await.unwrap();
    let _watch = d.watch();
    let xml = proxy.introspect().await.unwrap();
    assert!(xml.contains("org.sparklink.SsapReadProvider"));
    assert!(xml.contains("org.sparklink.SsapWriteProvider"));
}
