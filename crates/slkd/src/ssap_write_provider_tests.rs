//! Existing actual D-Bus/Owned/Engine fixture. Wire::fixture skips Native
//! receipt validation explicitly; no successful ioctl/USB/RF is claimed.
use super::*;
use slk_contract::ssap::{WriteProviderReply, WriteProviderRequest};

pub(super) struct Call {
    request: WriteProviderRequest,
    policy_calls: usize,
    reply: oneshot::Sender<WriteProviderReply>,
}
pub(super) struct Provider {
    pub(super) calls: mpsc::Sender<Call>,
    pub(super) policy_calls: Arc<AtomicUsize>,
}
#[zbus::interface(name = "org.sparklink.SsapWriteProvider")]
impl Provider {
    async fn write_value(
        &self,
        request: WriteProviderRequest,
    ) -> zbus::fdo::Result<WriteProviderReply> {
        let (reply, rx) = oneshot::channel();
        self.calls
            .try_send(Call {
                request,
                reply,
                policy_calls: self.policy_calls.load(Ordering::SeqCst),
            })
            .map_err(|_| zbus::fdo::Error::LimitsExceeded("fixture full".into()))?;
        rx.await
            .map_err(|_| zbus::fdo::Error::Failed("fixture released".into()))
    }
}
pub(super) struct WrongReply;
#[zbus::interface(name = "org.sparklink.SsapWriteProvider")]
impl WrongReply {
    fn write_value(&self, _request: WriteProviderRequest) -> bool {
        true
    }
}
fn wire() -> Wire {
    let (socket, _peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
    socket.set_nonblocking(true).unwrap();
    Wire::fixture(AsyncFd::new(socket.into()).unwrap())
}
async fn bind_writer(owner: &Connection, handle: u16, path: &str) -> zbus::Result<()> {
    manager(owner)
        .await
        .call(
            "BindOwnedWriteProvider",
            &(
                handle,
                OwnedObjectPath::try_from(path).unwrap(),
                owned_deadline(),
            ),
        )
        .await
}
async fn next(f: &mut Fixture) -> Call {
    tokio::time::timeout(Duration::from_secs(1), f.write_calls.recv())
        .await
        .unwrap()
        .unwrap()
}
fn write(handle: u16, command: bool, verify: bool, id: u64) -> ServerPacket {
    let value = &[0x93, 0x17];
    packet(
        if command {
            ValuePdu::WriteCommand {
                handle,
                data_type: 0,
                value,
            }
        } else {
            ValuePdu::Write {
                handle,
                data_type: 0,
                value,
                verify,
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

#[tokio::test]
async fn actual_write_callback_preserves_context_and_command_never_owes_response() {
    let mut f = Fixture::new().await;
    f.expected_write.store(true, Ordering::SeqCst);
    let (_, h) = register_operations(&f.owner, 4, 6).await;
    bind_writer(&f.owner, h, "/writer").await.unwrap();
    let db = store(&f.state).await;
    assert_eq!(
        db.lock().unwrap().local_read(h),
        Err(crate::ssap_database::LocalValueError::Unsupported)
    );
    let wire = wire();
    for (id, command, verify) in [(1, false, false), (2, false, true), (3, true, false)] {
        let request = write(h, command, verify, id);
        let original = request.constraint.unwrap();
        let task = tokio::spawn(resolve_server(request, db.clone(), wire.clone()));
        let call = next(&mut f).await;
        assert_eq!(call.policy_calls, id as usize);
        assert_eq!(call.request.request_id, id);
        assert_eq!(call.request.identity, (0, 7, 13, 1, 41, 0, 10, 10, 0));
        assert_eq!(call.request.deadline_ns, original.deadline_monotonic_ns);
        assert_eq!(call.request.operation, if command { 12 } else { 13 });
        assert_eq!(
            (
                call.request.property,
                call.request.data_type,
                call.request.offset
            ),
            (h, 0, 0)
        );
        assert_eq!(call.request.value, [0x93, 0x17]);
        assert_eq!(call.request.verify, verify);
        assert!(!task.is_finished(), "policy true must not finish the write");
        call.reply
            .send((0, if verify { vec![0x93, 0x17] } else { vec![] }))
            .unwrap();
        let result = finish(&wire, task.await.unwrap(), &db).unwrap();
        if command {
            assert!(result.is_none());
        } else {
            let expected = if verify {
                vec![14, 3, h as u8, (h >> 8) as u8, 0, 0x93, 0x17]
            } else {
                vec![14, 3]
            };
            assert_eq!(result.unwrap().bytes, expected);
        }
        assert_eq!(
            db.lock().unwrap().local_read(h),
            Err(crate::ssap_database::LocalValueError::Unsupported)
        );
    }
}

#[tokio::test]
async fn write_policy_refusal_wrong_callback_and_bad_status_never_commit_staging() {
    let mut f = Fixture::new().await;
    f.expected_write.store(true, Ordering::SeqCst);
    let (_, h) = register_operations(&f.owner, 4, 6).await;
    bind_writer(&f.owner, h, "/writer").await.unwrap();
    let db = store(&f.state).await;
    let wire = wire();
    f.allowed.store(false, Ordering::SeqCst);
    let d = resolve_server(write(h, false, false, 1), db.clone(), wire.clone()).await;
    assert_eq!(
        finish(&wire, d, &db).unwrap().unwrap().bytes,
        [14, 7, 1, h as u8, (h >> 8) as u8, 9]
    );
    assert!(f.write_calls.try_recv().is_err());
    f.allowed.store(true, Ordering::SeqCst);
    for (verify, reply, code) in [
        (false, (7, vec![]), 0xaf),
        (false, (0, vec![1]), 0xaf),
        (true, (0, vec![1]), 0xaf),
        (false, (0xff, vec![]), 0xff),
        (true, (0xff, vec![1]), 0xaf),
    ] {
        let task = tokio::spawn(resolve_server(
            write(h, false, verify, 2),
            db.clone(),
            wire.clone(),
        ));
        next(&mut f).await.reply.send(reply).unwrap();
        assert_eq!(
            finish(&wire, task.await.unwrap(), &db)
                .unwrap()
                .unwrap()
                .bytes,
            [14, 7, 1, h as u8, (h >> 8) as u8, code]
        );
    }
    let (_, bad) = register_operations(&f.owner, 0, 4).await;
    bind_writer(&f.owner, bad, "/wrong_writer").await.unwrap();
    let d = resolve_server(write(bad, false, false, 3), db.clone(), wire.clone()).await;
    assert_eq!(
        finish(&wire, d, &db).unwrap().unwrap().bytes,
        [14, 7, 1, bad as u8, (bad >> 8) as u8, 0xaf]
    );
}

#[tokio::test]
async fn pending_write_removal_and_original_expiry_do_not_revive_reply_or_value() {
    let mut f = Fixture::new().await;
    let (start, h) = register_operations(&f.owner, 0, 4).await;
    bind_writer(&f.owner, h, "/writer").await.unwrap();
    let db = store(&f.state).await;
    let wire = wire();
    let task = tokio::spawn(resolve_server(
        write(h, false, false, 1),
        db.clone(),
        wire.clone(),
    ));
    let call = next(&mut f).await;
    manager(&f.owner)
        .await
        .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    let d = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    let _ = call.reply.send((0, vec![]));
    assert_eq!(
        finish(&wire, d, &db).unwrap().unwrap().bytes,
        [14, 7, 1, h as u8, (h >> 8) as u8, 4]
    );
    let (_, h2) = register_operations(&f.owner, 0, 4).await;
    assert!(h2 > h);
    bind_writer(&f.owner, h2, "/writer").await.unwrap();
    let mut p = write(h2, false, false, 2);
    p.deadline = Instant::now() + Duration::from_millis(30);
    p.constraint.as_mut().unwrap().deadline_monotonic_ns = monotonic_deadline(p.deadline).unwrap();
    let task = tokio::spawn(resolve_server(p, db.clone(), wire.clone()));
    let call = next(&mut f).await;
    let d = tokio::time::timeout(Duration::from_secs(1), task)
        .await
        .unwrap()
        .unwrap();
    let _ = call.reply.send((0, vec![]));
    assert_eq!(
        finish(&wire, d, &db).err().unwrap().kind(),
        io::ErrorKind::TimedOut
    );
    assert_eq!(
        db.lock().unwrap().local_read(h2),
        Err(crate::ssap_database::LocalValueError::Unsupported)
    );
}

#[tokio::test]
async fn write_native_recheck_precedes_callback_and_callback_task_retains_only_its_wire() {
    let mut f = Fixture::new().await;
    let (_, h) = register_operations(&f.owner, 0, 4).await;
    bind_writer(&f.owner, h, "/writer").await.unwrap();
    let db = store(&f.state).await;
    let (socket, _peer) = std::os::unix::net::UnixDatagram::pair().unwrap();
    socket.set_nonblocking(true).unwrap();
    let native = Wire::native(AsyncFd::new(socket.into()).unwrap());
    let d = resolve_server(write(h, false, false, 1), db.clone(), native.clone()).await;
    assert!(d.admission_error.is_some());
    assert!(finish(&native, d, &db).is_err());
    assert!(f.write_calls.try_recv().is_err());
    let fixture = wire();
    let weak = Arc::downgrade(&fixture.fd);
    let task = tokio::spawn(resolve_server(
        write(h, false, false, 2),
        db.clone(),
        fixture.clone(),
    ));
    let call = next(&mut f).await;
    drop(fixture);
    assert!(weak.upgrade().is_some());
    task.abort();
    assert!(task.await.err().unwrap().is_cancelled());
    assert!(weak.upgrade().is_none());
    drop(call);
}

#[tokio::test]
async fn write_binding_rejects_foreign_mixed_and_rebind_without_consuming_staging() {
    let f = Fixture::new().await;
    let db = store(&f.state).await;
    let stranger = zbus::connection::Builder::address(f.bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    // Update properties require their existing CPCD capability at registration.
    for operations in [1, 3, 5, 7, 8 | 512, 16 | 512] {
        let (_, h) = register_operations(&f.owner, 0, operations).await;
        let before = db.lock().unwrap().local_read(h);
        assert!(bind_writer(&f.owner, h, "/writer").await.is_err());
        assert_eq!(db.lock().unwrap().local_read(h), before);
    }
    for operations in [2, 4, 6] {
        let (_, h) = register_operations(&f.owner, 0, operations).await;
        let before = db.lock().unwrap().local_read(h);
        assert!(bind_writer(&stranger, h, "/writer").await.is_err());
        assert!(bind_writer(&f.owner, h, "/").await.is_err());
        assert_eq!(db.lock().unwrap().local_read(h), before);
        bind_writer(&f.owner, h, "/writer").await.unwrap();
        assert!(bind_writer(&f.owner, h, "/writer").await.is_err());
        assert!(bind(&f.owner, h, "/provider").await.is_err());
        assert_eq!(
            db.lock().unwrap().local_read(h),
            Err(crate::ssap_database::LocalValueError::Unsupported)
        );
    }
}
