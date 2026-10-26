//! Actual private D-Bus, manager, owner callbacks and database rendering.
//! RX identity/Ready/lease remain explicit fixtures. No successful Native
//! ioctl, USB submission, peer processing or RF qualification is simulated.
use super::*;
use slk_contract::ssap::{ReadProviderReply, ReadProviderRequest};
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicUsize, Ordering},
};

struct Call {
    request: ReadProviderRequest,
    sender: String,
    policy_calls: usize,
    reply: oneshot::Sender<ReadProviderReply>,
}
struct Provider {
    calls: mpsc::Sender<Call>,
    policy_calls: Arc<AtomicUsize>,
}
#[zbus::interface(name = "org.sparklink.SsapReadProvider")]
impl Provider {
    async fn read_value(
        &self,
        request: ReadProviderRequest,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<ReadProviderReply> {
        let (reply, result) = oneshot::channel();
        self.calls
            .try_send(Call {
                request,
                sender: header.sender().unwrap().to_string(),
                policy_calls: self.policy_calls.load(Ordering::SeqCst),
                reply,
            })
            .map_err(|_| zbus::fdo::Error::LimitsExceeded("fixture inbox full".into()))?;
        result
            .await
            .map_err(|_| zbus::fdo::Error::Failed("fixture request released".into()))
    }
}
struct WrongReply;
#[zbus::interface(name = "org.sparklink.SsapReadProvider")]
impl WrongReply {
    fn read_value(&self, _request: ReadProviderRequest) -> bool {
        true
    }
}
struct Policy {
    allowed: Arc<AtomicBool>,
    calls: Arc<AtomicUsize>,
    expected_write: Arc<AtomicBool>,
}
#[zbus::interface(name = "org.sparklink.SsapAuthorizer")]
impl Policy {
    fn authorize_value(&self, prompt: SsapAuthorizationPrompt) -> bool {
        assert_eq!(prompt.6, 0);
        assert_eq!(prompt.3, self.expected_write.load(Ordering::SeqCst));
        if !prompt.3 {
            assert!(prompt.5.is_empty());
        }
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.allowed.load(Ordering::SeqCst)
    }
}
struct Fixture {
    bus: PrivateBus,
    state: crate::state::SharedState,
    server: Connection,
    owner: Connection,
    calls: mpsc::Receiver<Call>,
    allowed: Arc<AtomicBool>,
    policy_calls: Arc<AtomicUsize>,
    expected_write: Arc<AtomicBool>,
    write_calls: mpsc::Receiver<write_provider_tests::Call>,
}
impl Fixture {
    async fn new() -> Self {
        let bus = PrivateBus::start();
        let state = state();
        let server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .name("org.sparklink.AuthTest")
            .unwrap()
            .serve_at("/services", SsapManagerIface::new(state.clone()))
            .unwrap()
            .build()
            .await
            .unwrap();
        let (tx, calls) = mpsc::channel(4);
        let allowed = Arc::new(AtomicBool::new(true));
        let policy_calls = Arc::new(AtomicUsize::new(0));
        let expected_write = Arc::new(AtomicBool::new(false));
        let (write_tx, write_calls) = mpsc::channel(4);
        // Builder::serve_at provides the object-server startup barrier.
        let owner = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .serve_at(
                "/provider",
                Provider {
                    calls: tx,
                    policy_calls: policy_calls.clone(),
                },
            )
            .unwrap()
            .serve_at("/wrong", WrongReply)
            .unwrap()
            .serve_at(
                "/writer",
                write_provider_tests::Provider {
                    calls: write_tx,
                    policy_calls: policy_calls.clone(),
                },
            )
            .unwrap()
            .serve_at("/wrong_writer", write_provider_tests::WrongReply)
            .unwrap()
            .serve_at(
                "/authorizer",
                Policy {
                    allowed: allowed.clone(),
                    calls: policy_calls.clone(),
                    expected_write: expected_write.clone(),
                },
            )
            .unwrap()
            .build()
            .await
            .unwrap();
        Self {
            bus,
            state,
            server,
            owner,
            calls,
            allowed,
            policy_calls,
            expected_write,
            write_calls,
        }
    }
    async fn register(&self, access: u32) -> (u16, u16) {
        register_operations(&self.owner, access, 1).await
    }
    async fn next(&mut self) -> Call {
        tokio::time::timeout(Duration::from_secs(1), self.calls.recv())
            .await
            .expect("provider callback original test deadline")
            .unwrap()
    }
}

#[path = "ssap_write_provider_tests.rs"]
mod write_provider_tests;
async fn manager(connection: &Connection) -> zbus::Proxy<'_> {
    zbus::Proxy::new(
        connection,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap()
}
async fn bind(connection: &Connection, handle: u16, path: &str) -> zbus::Result<()> {
    manager(connection)
        .await
        .call(
            "BindOwnedReadProvider",
            &(
                handle,
                OwnedObjectPath::try_from(path).unwrap(),
                owned_deadline(),
            ),
        )
        .await
}
fn read(handle: u16, id: u64, level: u32) -> ServerPacket {
    packet(
        ValuePdu::Read {
            handle,
            data_type: 0,
        },
        id,
        level,
        Duration::from_secs(2),
    )
}
fn resolved(decision: &ServerDecision, db: &Store) -> Vec<u8> {
    server_response_resolved(
        &decision.packet,
        db,
        &decision.approvals,
        &decision.values,
        decision.write.as_ref(),
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
    .unwrap()
}
fn refusal<T>(result: zbus::Result<T>, expected: &str) {
    assert!(matches!(result, Err(zbus::Error::MethodError(name, _, _))
        if name.as_str() == expected));
}

#[tokio::test]
async fn public_dynamic_reads_change_and_empty_success_preserves_original_context() {
    let mut f = Fixture::new().await;
    let (_, h) = f.register(0).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    let db = store(&f.state).await;
    for (id, lifetime, value) in [(1, 13, vec![1, 2]), (1, 29, vec![9]), (2, 29, vec![])] {
        let mut request = read(h, id, 0);
        request.constraint.as_mut().unwrap().lifetime = lifetime;
        let original = request.constraint.unwrap();
        let task = tokio::spawn(authorize_server(request, db.clone()));
        let call = f.next().await;
        assert_eq!(call.sender, f.server.unique_name().unwrap().as_str());
        assert_eq!(call.policy_calls, 0);
        assert_eq!(call.request.request_id, id);
        assert_eq!(call.request.identity, (0, 7, lifetime, 1, 41, 0, 10, 10, 0));
        assert_eq!(call.request.property, h);
        assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
        assert_eq!(call.request.maximum_bytes, 2042);
        call.reply.send((0, value.clone())).unwrap();
        let decision = task.await.unwrap();
        assert_eq!(decision.packet.constraint, Some(original));
        let mut expected = vec![9, 3];
        expected.extend(value);
        assert_eq!(resolved(&decision, &db), expected);
    }
    assert_eq!(f.policy_calls.load(Ordering::SeqCst), 0);
    // Stored data was consumed; it is never an implicit dynamic-value cache.
    refusal(
        manager(&f.owner)
            .await
            .call::<_, _, Vec<u8>>("ReadOwnedLocalValue", &(h, owned_deadline()))
            .await,
        "org.freedesktop.DBus.Error.NotSupported",
    );
}

#[tokio::test]
async fn protected_read_checks_authorization_and_security_before_provider_dispatch() {
    let mut f = Fixture::new().await;
    let (_, h) = f.register(32).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    let db = store(&f.state).await;
    f.allowed.store(false, Ordering::SeqCst);
    let denied = authorize_server(read(h, 1, 0), db.clone()).await;
    assert_eq!(resolved(&denied, &db), [9, 11, 9, 0]);
    assert!(f.calls.try_recv().is_err());
    assert_eq!(f.policy_calls.load(Ordering::SeqCst), 1);
    f.allowed.store(true, Ordering::SeqCst);
    let task = tokio::spawn(authorize_server(read(h, 2, 0), db.clone()));
    let call = f.next().await;
    assert_eq!(
        call.policy_calls, 2,
        "policy must finish before dynamic value access"
    );
    call.reply.send((0, vec![0x31])).unwrap();
    assert_eq!(resolved(&task.await.unwrap(), &db), [9, 3, 0x31]);

    // The existing access predicate prioritizes missing local authorization
    // over authentication in combined access48. Neither callback may elevate
    // a request whose original mechanism cannot meet the declared access.
    for (access, error) in [(16, 8), (48, 9), (8, 10)] {
        let (_, secure) = f.register(access).await;
        bind(&f.owner, secure, "/provider").await.unwrap();
        let denied = authorize_server(read(secure, 3, 0), db.clone()).await;
        assert_eq!(resolved(&denied, &db), [9, 11, error, 0]);
        assert!(f.calls.try_recv().is_err());
        assert_eq!(f.policy_calls.load(Ordering::SeqCst), 2);
    }
}

#[tokio::test]
async fn binding_is_owner_scoped_once_only_and_description_and_write_permissions_stay_separate() {
    let mut f = Fixture::new().await;
    let (_, h) = f.register(32).await;
    let stranger = client(&f.bus).await;
    refusal(
        bind(&stranger, h, "/provider").await,
        "org.freedesktop.DBus.Error.AccessDenied",
    );
    let (_, writable) = register_operations(&f.owner, 0, 5).await;
    refusal(
        bind(&f.owner, writable, "/provider").await,
        "org.freedesktop.DBus.Error.NotSupported",
    );
    bind(&f.owner, h, "/provider").await.unwrap();
    refusal(
        bind(&f.owner, h, "/wrong").await,
        "org.freedesktop.DBus.Error.NotSupported",
    );
    let proxy = manager(&f.owner).await;
    refusal(
        proxy
            .call::<_, _, Vec<u8>>("ReadOwnedLocalValue", &(h, owned_deadline()))
            .await,
        "org.freedesktop.DBus.Error.NotSupported",
    );
    refusal(
        proxy.call::<_, _, Vec<u8>>("ReadLocalValue", &(h,)).await,
        "org.freedesktop.DBus.Error.NotSupported",
    );
    refusal(
        proxy
            .call::<_, _, ()>(
                "ReplaceOwnedLocalValue",
                &(h, vec![0x55u8], owned_deadline()),
            )
            .await,
        "org.freedesktop.DBus.Error.NotSupported",
    );
    proxy
        .call::<_, _, ()>("SetOwnedLocalDescription", &(h, "live", owned_deadline()))
        .await
        .unwrap();
    let db = store(&f.state).await;
    let description = packet(
        ValuePdu::Read {
            handle: h,
            data_type: 1,
        },
        1,
        0,
        Duration::from_secs(2),
    );
    let decision = authorize_server(description, db.clone()).await;
    assert_eq!(resolved(&decision, &db), [9, 3, b'l', b'i', b'v', b'e']);
    let write = packet(
        ValuePdu::Write {
            handle: h,
            data_type: 0,
            value: &[3],
            verify: true,
        },
        2,
        0,
        Duration::from_secs(2),
    );
    let decision = authorize_server(write, db.clone()).await;
    assert_eq!(
        resolved(&decision, &db),
        [14, 7, 1, h as u8, (h >> 8) as u8, 7]
    );
    assert_eq!(
        db.lock().unwrap().command_authorized(
            ValuePdu::WriteCommand {
                handle: h,
                data_type: 0,
                value: &[4]
            },
            249,
            0,
            &[]
        ),
        Err(7)
    );
    assert!(f.calls.try_recv().is_err());
    assert_eq!(f.policy_calls.load(Ordering::SeqCst), 0);
    assert_eq!(db.lock().unwrap().local_read(writable).unwrap(), [7]);
}

#[tokio::test]
async fn missing_wrong_shape_oversized_and_application_errors_never_return_stored_value() {
    let mut f = Fixture::new().await;
    let db = store(&f.state).await;
    for path in ["/missing", "/wrong"] {
        let (_, h) = f.register(0).await;
        bind(&f.owner, h, path).await.unwrap();
        let decision = authorize_server(read(h, 1, 0), db.clone()).await;
        assert_eq!(resolved(&decision, &db), [9, 11, 0xaf, 0]);
        assert!(f.calls.try_recv().is_err());
    }
    let (_, h) = f.register(0).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    for (reply, expected) in [
        ((0, vec![8; 2043]), 0xaf),
        ((1, vec![]), 0xaf),
        ((0x100, vec![]), 0xaf),
        ((0xb0, vec![8]), 0xaf),
        ((0xaf, vec![]), 0xaf),
        ((0xff, vec![]), 0xff),
    ] {
        let task = tokio::spawn(authorize_server(read(h, 2, 0), db.clone()));
        f.next().await.reply.send(reply).unwrap();
        assert_eq!(resolved(&task.await.unwrap(), &db), [9, 11, expected, 0]);
    }
    // A valid callback value still cannot bypass the original negotiated MTU.
    let task = tokio::spawn(authorize_server(read(h, 3, 0), db.clone()));
    f.next().await.reply.send((0, vec![8; 248])).unwrap();
    assert_eq!(resolved(&task.await.unwrap(), &db), [9, 11, 16, 0]);
}

#[tokio::test]
async fn uuid_read_combines_stored_and_dynamic_values_in_handle_order() {
    let mut f = Fixture::new().await;
    let (_, stored) = f.register(0).await;
    let (_, first) = f.register(0).await;
    let (_, second) = f.register(0).await;
    assert_eq!((stored, first, second), (17, 19, 21));
    bind(&f.owner, first, "/provider").await.unwrap();
    bind(&f.owner, second, "/provider").await.unwrap();
    let db = store(&f.state).await;
    let mut request = read(first, 9, 0);
    request.bytes = vec![10, 0, 16, 0, 255, 255, 0, 2, 0];
    let original = request.constraint.unwrap();
    let task = tokio::spawn(authorize_server(request, db.clone()));
    let call = f.next().await;
    assert_eq!(
        (call.request.property, call.request.maximum_bytes),
        (first, 2042)
    );
    assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
    call.reply.send((0, vec![2, 3])).unwrap();
    let call = f.next().await;
    assert_eq!(
        (call.request.property, call.request.maximum_bytes),
        (second, 2040)
    );
    assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
    call.reply.send((0, vec![])).unwrap();
    assert_eq!(
        resolved(&task.await.unwrap(), &db),
        [11, 7, 17, 0, 1, 128, 7, 19, 0, 2, 128, 2, 3, 21, 0, 0, 128]
    );
}

#[tokio::test]
async fn uuid_provider_values_share_2042_bytes_and_never_truncate_oversized_pdu() {
    let mut f = Fixture::new().await;
    let (_, first) = f.register(0).await;
    let (_, second) = f.register(0).await;
    bind(&f.owner, first, "/provider").await.unwrap();
    bind(&f.owner, second, "/provider").await.unwrap();
    let db = store(&f.state).await;
    let mut request = read(first, 10, 0);
    request.bytes = vec![10, 0, 16, 0, 255, 255, 0, 2, 0];
    request.mtu = 2047; // Explicit negotiated logical-PDU budget fixture.
    let task = tokio::spawn(authorize_server(request, db.clone()));
    let call = f.next().await;
    assert_eq!(call.request.maximum_bytes, 2042);
    call.reply.send((0, vec![0x11; 1200])).unwrap();
    let call = f.next().await;
    assert_eq!(call.request.maximum_bytes, 842);
    call.reply.send((0, vec![0x22; 842])).unwrap();
    let decision = task.await.unwrap();
    assert_eq!(
        decision
            .values
            .iter()
            .map(|v| v.result.as_ref().unwrap().len())
            .sum::<usize>(),
        2042
    );
    // Two per-entry headers exceed the logical budget; no silent truncation.
    assert_eq!(resolved(&decision, &db), [9, 11, 16, 0]);
}

#[tokio::test]
async fn removed_registration_rejects_completed_and_pending_provider_results_without_handle_reuse()
{
    let mut f = Fixture::new().await;
    let (start, h) = f.register(0).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    let db = store(&f.state).await;
    let task = tokio::spawn(authorize_server(read(h, 1, 0), db.clone()));
    f.next().await.reply.send((0, vec![0x55])).unwrap();
    let decision = task.await.unwrap();
    manager(&f.owner)
        .await
        .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    let (new_start, new_h) = f.register(0).await;
    assert!(new_h > h);
    assert_eq!(resolved(&decision, &db), [9, 11, 4, 0]);
    assert_eq!(db.lock().unwrap().local_read(new_h).unwrap(), [7]);
    bind(&f.owner, new_h, "/provider").await.unwrap();
    let task = tokio::spawn(authorize_server(read(new_h, 1, 0), db.clone()));
    let pending = f.next().await;
    manager(&f.owner)
        .await
        .call::<_, _, ()>(
            "UnregisterOwnedLocalService",
            &(new_start, owned_deadline()),
        )
        .await
        .unwrap();
    let decision = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    // Native callback cancellation does not require the application to reply.
    let _ = pending.reply.send((0, vec![0x66]));
    assert_eq!(resolved(&decision, &db), [9, 11, 4, 0]);
}

#[tokio::test]
async fn removal_preserves_encoded_snapshot_but_rejects_unrendered_provider_candidate() {
    let mut f = Fixture::new().await;
    let (start, h) = f.register(0).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    let db = store(&f.state).await;

    let task = tokio::spawn(authorize_server(read(h, 1, 0), db.clone()));
    f.next().await.reply.send((0, vec![0x51, 0x52])).unwrap();
    let accepted = task.await.unwrap();
    // Exercise the production renderer's snapshot boundary only. This does
    // not fabricate the Native recheck or claim a successful TX admission.
    let encoded = resolved(&accepted, &db);
    assert_eq!(encoded, [9, 3, 0x51, 0x52]);

    let task = tokio::spawn(authorize_server(read(h, 2, 0), db.clone()));
    f.next().await.reply.send((0, vec![0x61, 0x62])).unwrap();
    let unrendered = task.await.unwrap();
    manager(&f.owner)
        .await
        .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();

    assert_eq!(resolved(&unrendered, &db), [9, 11, 4, 0]);
    // Removal invalidates unconsumed candidates, not immutable bytes already
    // produced. Their later send still requires the original Native contract.
    assert_eq!(encoded, [9, 3, 0x51, 0x52]);
    assert!(!accepted.values[0].target.binding.owner.current());
}

#[tokio::test]
async fn original_expiry_and_owner_exit_cancel_provider_waits_without_fallback_or_native_success() {
    let mut f = Fixture::new().await;
    let (_, h) = f.register(0).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    let db = store(&f.state).await;
    let request = packet(
        ValuePdu::Read {
            handle: h,
            data_type: 0,
        },
        1,
        0,
        Duration::from_millis(150),
    );
    let original = request.deadline;
    let task = tokio::spawn(authorize_server(request, db.clone()));
    let pending = f.next().await;
    let decision = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(decision.packet.deadline, original);
    assert!(Instant::now() >= original);
    let _ = pending.reply.send((0, vec![0x77]));
    assert_eq!(resolved(&decision, &db), [9, 11, 0xaf, 0]);
    let (fd, _other) = std::os::unix::net::UnixDatagram::pair().unwrap();
    fd.set_nonblocking(true).unwrap();
    let wire = Wire::native(AsyncFd::new(OwnedFd::from(fd)).unwrap());
    assert_eq!(
        complete_server(
            &wire,
            decision,
            &db,
            &mut crate::ssap_engine_config::ClientConfigurations::default()
        )
        .err()
        .unwrap()
        .kind(),
        io::ErrorKind::TimedOut
    );

    let task = tokio::spawn(authorize_server(read(h, 2, 0), db.clone()));
    let pending = f.next().await;
    f.owner.close().await.unwrap();
    let decision = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    let _ = pending.reply.send((0, vec![0x88]));
    assert_eq!(resolved(&decision, &db), [9, 11, 4, 0]);
    let replacement = client(&f.bus).await;
    let (_, new_h) = register_operations(&replacement, 0, 1).await;
    assert!(new_h > h);
    assert_eq!(db.lock().unwrap().local_read(new_h).unwrap(), [7]);
}

#[tokio::test]
async fn successful_provider_reply_does_not_bypass_native_original_context_recheck() {
    let mut f = Fixture::new().await;
    let (_, h) = f.register(0).await;
    bind(&f.owner, h, "/provider").await.unwrap();
    let db = store(&f.state).await;
    let task = tokio::spawn(authorize_server(read(h, 1, 0), db.clone()));
    f.next().await.reply.send((0, vec![0x99])).unwrap();
    let decision = task.await.unwrap();
    assert_eq!(resolved(&decision, &db), [9, 3, 0x99]);
    let (fd, _other) = std::os::unix::net::UnixDatagram::pair().unwrap();
    fd.set_nonblocking(true).unwrap();
    let wire = Wire::native(AsyncFd::new(OwnedFd::from(fd)).unwrap());
    assert!(
        complete_server(
            &wire,
            decision,
            &db,
            &mut crate::ssap_engine_config::ClientConfigurations::default()
        )
        .is_err()
    );
}
