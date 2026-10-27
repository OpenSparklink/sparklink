//! Production manager/database/Owner/Engine with an actual private D-Bus peer.
//! Wire::fixture explicitly bypasses Native receipt checks; no kernel or RF proof.
use super::*;
use slk_contract::ssap::{MethodProviderReply, MethodProviderRequest};
struct Invocation {
    request: MethodProviderRequest,
    reply: oneshot::Sender<MethodProviderReply>,
}
struct Provider(mpsc::Sender<Invocation>);
#[zbus::interface(name = "org.sparklink.SsapMethodProvider")]
impl Provider {
    async fn call_method(
        &self,
        request: MethodProviderRequest,
    ) -> zbus::fdo::Result<MethodProviderReply> {
        let (reply, result) = oneshot::channel();
        self.0
            .try_send(Invocation { request, reply })
            .map_err(|_| zbus::fdo::Error::LimitsExceeded("fixture queue".into()))?;
        result
            .await
            .map_err(|_| zbus::fdo::Error::Failed("fixture released".into()))
    }
}
async fn manager(owner: &Connection) -> zbus::Proxy<'_> {
    zbus::Proxy::new(
        owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap()
}
async fn register_method(owner: &Connection, access: u32) -> (u16, u16) {
    let (start, _, handles): slk_contract::ssap::local::Registration = manager(owner)
        .await
        .call(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                Vec::<slk_contract::ssap::local::PropertyDefinition>::new(),
                vec![(vec![3u8, 0], access)],
                OwnedObjectPath::try_from("/authorizer").unwrap(),
                owned_deadline(),
            ),
        )
        .await
        .unwrap();
    assert_eq!(handles.len(), 1);
    (start, handles[0])
}
async fn bind(owner: &Connection, h: u16) -> zbus::Result<()> {
    manager(owner)
        .await
        .call(
            "BindOwnedMethodProvider",
            &(
                h,
                OwnedObjectPath::try_from("/method").unwrap(),
                owned_deadline(),
            ),
        )
        .await
}
fn wire() -> Wire {
    let (socket, _peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
    socket.set_nonblocking(true).unwrap();
    Wire::fixture(AsyncFd::new(socket.into()).unwrap())
}
fn request(h: u16, command: bool, id: u64) -> ServerPacket {
    packet(
        if command {
            ValuePdu::CallMethodCommand {
                handle: h,
                arguments: &[0x93, 0x17],
            }
        } else {
            ValuePdu::CallMethod {
                handle: h,
                arguments: &[0x93, 0x17],
            }
        },
        id,
        0,
        Duration::from_secs(2),
    )
}
fn finish(wire: &Wire, d: ServerDecision, db: &Store) -> io::Result<Option<Pending>> {
    complete_server(
        wire,
        d,
        db,
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
}
async fn next(calls: &mut mpsc::Receiver<Invocation>) -> Invocation {
    tokio::time::timeout(Duration::from_secs(1), calls.recv())
        .await
        .unwrap()
        .unwrap()
}

#[tokio::test]
async fn method_real_callback_has_distinct_policy_target_and_independent_result() {
    let (_bus, state, _server, owner, mut policy) = setup(true, Duration::ZERO).await;
    let (tx, mut calls) = mpsc::channel(4);
    owner
        .object_server()
        .at("/method", Provider(tx))
        .await
        .unwrap();
    let (_, h) = register_method(&owner, 4).await;
    bind(&owner, h).await.unwrap();
    let db = store(&state).await;
    let wire = wire();
    for (id, command, reply) in [
        (1, false, (0, vec![0x55, 0x66, 0x77])),
        (2, true, (0, vec![])),
        (3, true, (0xb1, vec![])),
    ] {
        let packet = request(h, command, id);
        let original = packet.constraint.unwrap();
        let task = tokio::spawn(resolve_server(packet, db.clone(), wire.clone()));
        let call = next(&mut calls).await;
        let prompt = policy.recv().await.unwrap();
        assert_eq!((prompt.2, prompt.3, prompt.6), (h, true, 3));
        assert_eq!(prompt.5, [0x93, 0x17]);
        assert_eq!(call.request.request_id, id);
        assert_eq!(call.request.method, h);
        assert_eq!(call.request.identity, (0, 7, 13, 1, 41, 0, 10, 10, 0));
        assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
        assert_eq!(call.request.arguments, [0x93, 0x17]);
        assert_eq!(call.request.operation, if command { 18 } else { 19 });
        assert_eq!(
            call.request.maximum_result_bytes,
            if command { 0 } else { 247 }
        );
        assert!(
            !task.is_finished(),
            "policy approval is not method completion"
        );
        call.reply.send(reply).unwrap();
        let result = finish(&wire, task.await.unwrap(), &db).unwrap();
        if command {
            assert!(result.is_none());
        } else {
            assert_eq!(result.unwrap().bytes, [20, 3, 0x55, 0x66, 0x77]);
        }
        assert!(
            db.lock().unwrap().local_read(h).is_err(),
            "method is not a stored property"
        );
    }
}

#[tokio::test]
async fn method_errors_binding_ownership_and_reply_bounds_fail_closed() {
    let (bus, state, _server, owner, _policy) = setup(false, Duration::ZERO).await;
    let (tx, mut calls) = mpsc::channel(4);
    owner
        .object_server()
        .at("/method", Provider(tx))
        .await
        .unwrap();
    let (start, h) = register_method(&owner, 4).await;
    bind(&owner, h).await.unwrap();
    let other = client(&bus).await;
    assert!(bind(&other, h).await.is_err());
    assert!(bind(&owner, h).await.is_err());
    let db = store(&state).await;
    let wire = wire();
    for (handle, error) in [(h, 9), (start, 12), (u16::MAX, 4)] {
        let d = resolve_server(request(handle, false, 1), db.clone(), wire.clone()).await;
        assert_eq!(
            finish(&wire, d, &db).unwrap().unwrap().bytes,
            [1, 0, 19, handle as u8, (handle >> 8) as u8, error]
        );
        assert!(calls.try_recv().is_err());
    }
    let (_, public) = register_method(&owner, 0).await;
    let d = resolve_server(request(public, false, 1), db.clone(), wire.clone()).await;
    assert_eq!(finish(&wire, d, &db).unwrap().unwrap().bytes[5], 0xaf);
    bind(&owner, public).await.unwrap();
    for (reply, expected) in [
        ((0, vec![1; 248]), 0xaf),
        ((1, vec![]), 0xaf),
        ((0xb0, vec![1]), 0xaf),
        ((0xb1, vec![]), 0xb1),
    ] {
        let task = tokio::spawn(resolve_server(
            request(public, false, 2),
            db.clone(),
            wire.clone(),
        ));
        next(&mut calls).await.reply.send(reply).unwrap();
        assert_eq!(
            finish(&wire, task.await.unwrap(), &db)
                .unwrap()
                .unwrap()
                .bytes,
            [1, 0, 19, public as u8, (public >> 8) as u8, expected]
        );
    }
    let (_, protected) = register_method(&owner, 2).await;
    bind(&owner, protected).await.unwrap();
    let d = resolve_server(request(protected, false, 3), db.clone(), wire.clone()).await;
    assert_eq!(finish(&wire, d, &db).unwrap().unwrap().bytes[5], 8);
    assert!(calls.try_recv().is_err());
}

#[tokio::test]
async fn method_pending_withdrawal_and_expiry_cannot_revive_result_or_other_service() {
    let (_bus, state, _server, owner, _policy) = setup(true, Duration::ZERO).await;
    let (tx, mut calls) = mpsc::channel(4);
    owner
        .object_server()
        .at("/method", Provider(tx))
        .await
        .unwrap();
    let (start, h) = register_method(&owner, 0).await;
    bind(&owner, h).await.unwrap();
    let (_, guard) = register(&owner, 0).await;
    let db = store(&state).await;
    let wire = wire();
    let task = tokio::spawn(resolve_server(
        request(h, false, 1),
        db.clone(),
        wire.clone(),
    ));
    let call = next(&mut calls).await;
    manager(&owner)
        .await
        .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    let d = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    let _ = call.reply.send((0, vec![9]));
    assert_eq!(
        finish(&wire, d, &db).unwrap().unwrap().bytes,
        [1, 0, 19, h as u8, (h >> 8) as u8, 4]
    );
    assert_eq!(db.lock().unwrap().local_read(guard).unwrap(), [7]);
    let (_, h2) = register_method(&owner, 0).await;
    assert!(h2 > h);
    bind(&owner, h2).await.unwrap();
    let mut p = request(h2, false, 2);
    p.deadline = Instant::now() + Duration::from_millis(80);
    p.constraint.as_mut().unwrap().deadline_monotonic_ns = monotonic_deadline(p.deadline).unwrap();
    let task = tokio::spawn(resolve_server(p, db.clone(), wire.clone()));
    let call = next(&mut calls).await;
    let d = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    let _ = call.reply.send((0, vec![8]));
    assert_eq!(
        finish(&wire, d, &db).err().unwrap().kind(),
        io::ErrorKind::TimedOut
    );
    assert_eq!(db.lock().unwrap().local_read(guard).unwrap(), [7]);
}

#[tokio::test]
async fn owned_method_discovery_and_shared_registration_budget() {
    use slk_protocol::ssap::discovery::{EntryClass, FindKind, FindRequest, decode_page};
    let (_bus, state, _server, owner, _policy) = setup(true, Duration::ZERO).await;
    let (start, h) = register_method(&owner, 0).await;
    let db = store(&state).await;
    let req = FindRequest {
        kind: FindKind::Primary,
        class: EntryClass::Mixed,
        start,
        end: h,
        uuid: None,
    };
    let bytes = db.lock().unwrap().find(req, 249).unwrap();
    let page = decode_page(req, 249, &bytes).unwrap();
    assert_eq!(page[0].members, 4);
    let req = FindRequest {
        kind: FindKind::Methods,
        ..req
    };
    let bytes = db.lock().unwrap().find(req, 249).unwrap();
    let page = decode_page(req, 249, &bytes).unwrap();
    assert_eq!(page[0].handle, h);
    assert_eq!(page[0].category, 3);
    let too_many = vec![(vec![3u8, 0], 0u32); 64];
    let result = manager(&owner)
        .await
        .call::<_, _, slk_contract::ssap::local::Registration>(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                vec![(vec![2u8, 0], 1u32, 0u32, Vec::<u8>::new())],
                too_many,
                OwnedObjectPath::try_from("/authorizer").unwrap(),
                owned_deadline(),
            ),
        )
        .await;
    assert!(result.is_err());
    assert_eq!(db.lock().unwrap().list().len(), 1);
}

#[tokio::test]
async fn method_bus_signature_and_owner_exit_do_not_revive_other_registration() {
    let (bus, state, _server, owner, _policy) = setup(true, Duration::ZERO).await;
    let (tx, mut calls) = mpsc::channel(4);
    owner
        .object_server()
        .at("/method", Provider(tx))
        .await
        .unwrap();
    let peer = client(&bus).await;
    let proxy = zbus::Proxy::new(
        &peer,
        owner.unique_name().unwrap().as_str(),
        "/method",
        "org.sparklink.SsapMethodProvider",
    )
    .await
    .unwrap();
    let xml = proxy.introspect().await.unwrap();
    let method = xml
        .split_once("<method name=\"CallMethod\">")
        .unwrap()
        .1
        .split_once("</method>")
        .unwrap()
        .0;
    let input: Vec<_> = method
        .lines()
        .filter(|s| s.contains("direction=\"in\""))
        .map(|s| {
            s.split_once("type=\"")
                .unwrap()
                .1
                .split_once('"')
                .unwrap()
                .0
        })
        .collect();
    assert_eq!(input, ["(t(qttqtuyyy)qtyayq)"]);
    let (_, h) = register_method(&owner, 0).await;
    bind(&owner, h).await.unwrap();
    let (_, guard) = register(&peer, 0).await;
    let db = store(&state).await;
    let wire = wire();
    let task = tokio::spawn(resolve_server(
        request(h, false, 1),
        db.clone(),
        wire.clone(),
    ));
    let call = next(&mut calls).await;
    drop(proxy);
    owner.close().await.unwrap();
    let d = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    let _ = call.reply.send((0, vec![7]));
    assert_eq!(
        finish(&wire, d, &db).unwrap().unwrap().bytes,
        [1, 0, 19, h as u8, (h >> 8) as u8, 4]
    );
    assert_eq!(db.lock().unwrap().local_read(guard).unwrap(), [7]);
    let (_, new_handle) = register_method(&peer, 0).await;
    assert!(new_handle > h);
    let d = resolve_server(request(h, false, 2), db.clone(), wire.clone()).await;
    assert_eq!(
        finish(&wire, d, &db).unwrap().unwrap().bytes,
        [1, 0, 19, h as u8, (h >> 8) as u8, 4]
    );
}
