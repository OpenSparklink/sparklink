//! Real private D-Bus and production owner/DB/authorization/render functions.
//! Canonical Ready/lease and RX context are explicit FIXTURES; /dev/null never
//! supplies a successful native ioctl. No USB, kernel locks, crypto or RF proof.
use super::*;
use crate::{
    event_loop::tests::PrivateBus, security_policy::tests::state, service::SsapManagerIface,
};
use slk_contract::ssap::SsapAuthorizationPrompt;
use tokio::sync::mpsc;
use zbus::{Connection, zvariant::OwnedObjectPath};

#[tokio::test]
async fn partial_update_caller_close_then_owner_exit_still_wakes() {
    // A real bus-owner loss after the author wait is gone. The unsubmitted
    // remainder must not lose its owner watch along with that author wait.
    let bus = PrivateBus::start();
    let server = client(&bus).await;
    let caller = client(&bus).await;
    let db = std::sync::Arc::new(std::sync::Mutex::new(
        crate::ssap_database::Database::default(),
    ));
    let slots = std::sync::Arc::new(tokio::sync::Semaphore::new(1));
    let first = Instant::now();
    let owner = crate::ssap_authorization::Owner::pin(
        &server,
        caller.unique_name().unwrap().to_string(),
        OwnedObjectPath::try_from("/").unwrap(),
        &db,
        slots.clone().try_acquire_owned().unwrap(),
        first + Duration::from_secs(5),
    )
    .await
    .unwrap();
    let (reply, mut result) = oneshot::channel();
    let mut current = UpdateRequest {
        submitted_all: false,
        handle: 17,
        owner: owner.clone(),
        mode: 2,
        epoch: 41,
        deadline: first + Duration::from_secs(4),
        drain: None,
        pdu: vec![16, 3, 17, 0, 0, 0],
        reply: Some(reply),
    };
    current.admit_part(first, false);
    let mut update = Some(current);
    let mut pending = VecDeque::from([Pending {
        sent: 1,
        bytes: vec![16, 3, 17, 0, 0, 0],
        deadline: first + Duration::from_secs(4),
        purpose: Purpose::Update,
        constraint: None,
    }]);
    result.close();
    update.as_mut().unwrap().withdrawn().await;
    retire_update_wait(&mut update, &mut pending, Instant::now());
    assert!(update.as_ref().unwrap().reply.is_none());
    assert!(update.as_ref().unwrap().needs_withdrawal_watch());
    caller.close().await.unwrap();
    tokio::time::timeout(Duration::from_secs(1), update.as_mut().unwrap().withdrawn())
        .await
        .expect("partial update lost owner wake after caller close");
    assert!(!owner.current());
    assert!(retire_update_event(&mut update, &mut pending, Instant::now()).is_err());
    assert_eq!(
        update.as_ref().unwrap().drain,
        Some(first + Duration::from_secs(5))
    );
    assert_eq!(pending.len(), 1);
    owner.shutdown().await;
    assert_eq!(slots.available_permits(), 1);
}

#[tokio::test]
async fn update_withdrawal_wakes_without_renewing_or_forgetting_admitted_work() {
    // Actual Owner watch, oneshot and production UpdateRequest methods. No
    // Native socket/USB/credit result is supplied by this test.
    let bus = PrivateBus::start();
    let server = client(&bus).await;
    let db = std::sync::Arc::new(std::sync::Mutex::new(
        crate::ssap_database::Database::default(),
    ));
    let slots = std::sync::Arc::new(tokio::sync::Semaphore::new(1));
    for owner_exit in [false, true] {
        for admitted_parts in 0..=2 {
            let caller = client(&bus).await;
            let first = Instant::now();
            let owner = crate::ssap_authorization::Owner::pin(
                &server,
                caller.unique_name().unwrap().to_string(),
                OwnedObjectPath::try_from("/").unwrap(),
                &db,
                slots.clone().try_acquire_owned().unwrap(),
                first + Duration::from_secs(5),
            )
            .await
            .unwrap();
            let (reply, mut result) = oneshot::channel();
            let mut current = UpdateRequest {
                submitted_all: false,
                handle: 17,
                owner: owner.clone(),
                mode: 2,
                epoch: 41,
                deadline: first + Duration::from_secs(4),
                drain: None,
                pdu: vec![16, 3, 17, 0, 0, 0],
                reply: Some(reply),
            };
            for part in 0..admitted_parts {
                current.admit_part(first + Duration::from_millis(part), part == 1);
            }
            // Cancel a pending subscription, then subscribe again. An earlier
            // withdrawal must still wake it: no dependency on a future edge.
            assert!(
                tokio::time::timeout(Duration::from_millis(1), current.withdrawn())
                    .await
                    .is_err()
            );
            if owner_exit {
                caller.close().await.unwrap();
            } else {
                result.close();
            }
            tokio::time::timeout(Duration::from_secs(1), current.withdrawn())
                .await
                .unwrap();
            let original = current.deadline;
            let drain = current.drain;
            let mut update = Some(current);
            let mut pending = if admitted_parts == 2 {
                VecDeque::new()
            } else {
                VecDeque::from([Pending {
                    sent: admitted_parts as usize,
                    bytes: vec![16, 3, 17, 0, 0, 0],
                    deadline: original,
                    purpose: Purpose::Update,
                    constraint: None,
                }])
            };
            retire_update_wait(&mut update, &mut pending, Instant::now());
            if owner_exit {
                assert!(result.await.unwrap().is_err());
            }
            if admitted_parts == 0 {
                assert!(update.is_none() && pending.is_empty());
            } else {
                let current = update.as_mut().unwrap();
                assert!(current.reply.is_none());
                assert_eq!(current.deadline, original);
                assert_eq!(current.drain, drain);
                assert_eq!(current.submitted_all, admitted_parts == 2);
                assert_eq!(pending.len(), usize::from(admitted_parts == 1));
                assert_eq!(current.needs_withdrawal_watch(), admitted_parts == 1);
                if admitted_parts == 1 {
                    assert_eq!(pending[0].deadline, original);
                    if owner_exit {
                        tokio::time::timeout(Duration::from_secs(1), current.withdrawn())
                            .await
                            .unwrap();
                    } else {
                        assert!(
                            tokio::time::timeout(Duration::from_millis(1), current.withdrawn())
                                .await
                                .is_err()
                        );
                    }
                }
                assert_eq!(
                    retire_update_event(&mut update, &mut pending, Instant::now()).is_err(),
                    owner_exit && admitted_parts == 1
                );
                retire_update_wait(&mut update, &mut pending, Instant::now());
                assert!(update.as_ref().unwrap().reply.is_none());
                assert_eq!(update.as_ref().unwrap().drain, drain);
            }
            owner.shutdown().await;
            assert_eq!(slots.available_permits(), 1);
        }
    }
}

struct Consent {
    yes: bool,
    delay: Duration,
    seen: mpsc::UnboundedSender<SsapAuthorizationPrompt>,
}
#[zbus::interface(name = "org.sparklink.SsapAuthorizer")]
impl Consent {
    async fn authorize_value(&self, prompt: SsapAuthorizationPrompt) -> bool {
        self.seen.send(prompt).unwrap();
        tokio::time::sleep(self.delay).await;
        self.yes
    }
}
async fn client(bus: &PrivateBus) -> Connection {
    zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap()
}
#[tokio::test]
async fn actual_authorizer_bus_signature_is_independent_of_shared_aliases() {
    let bus = PrivateBus::start();
    let server = client(&bus).await;
    let (seen, _received) = mpsc::unbounded_channel();
    // Builder::serve_at waits for the object-server startup barrier. A dynamic
    // .at() followed immediately by the first call can lose that call before
    // the method stream starts. No sleep/retry or weakened signature oracle.
    let owner = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .serve_at(
            "/authorizer",
            Consent {
                yes: true,
                delay: Duration::ZERO,
                seen,
            },
        )
        .unwrap()
        .build()
        .await
        .unwrap();
    let reply = tokio::time::timeout(
        Duration::from_secs(2),
        server.call_method(
            Some(owner.unique_name().unwrap().as_str()),
            "/authorizer",
            Some("org.freedesktop.DBus.Introspectable"),
            "Introspect",
            &(),
        ),
    )
    .await
    .expect("authorizer introspection original test deadline")
    .unwrap();
    let xml: String = reply.body().deserialize().unwrap();
    let method = xml
        .split_once("<method name=\"AuthorizeValue\">")
        .unwrap()
        .1
        .split_once("</method>")
        .unwrap()
        .0;
    // Literal expectations: moving one shared alias cannot silently teach both
    // endpoints the same incompatible signature. This is actual private D-Bus,
    // not kernel/RF or production system-bus permission qualification.
    let arguments = |direction| {
        method
            .lines()
            .filter(|line| {
                line.contains("<arg ") && line.contains(&format!("direction=\"{direction}\""))
            })
            .map(|line| {
                line.split_once("type=\"")
                    .unwrap()
                    .1
                    .split_once('"')
                    .unwrap()
                    .0
            })
            .collect::<Vec<_>>()
    };
    assert_eq!(arguments("in"), ["(t(qttqtuyyy)qbtayy)"]);
    assert_eq!(arguments("out"), ["b"]);
}

async fn setup(
    yes: bool,
    delay: Duration,
) -> (
    PrivateBus,
    crate::state::SharedState,
    Connection,
    Connection,
    mpsc::UnboundedReceiver<SsapAuthorizationPrompt>,
) {
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
    let owner = client(&bus).await;
    let (tx, rx) = mpsc::unbounded_channel();
    owner
        .object_server()
        .at(
            "/authorizer",
            Consent {
                yes,
                delay,
                seen: tx,
            },
        )
        .await
        .unwrap();
    (bus, state, server, owner, rx)
}
async fn register(owner: &Connection, access: u32) -> (u16, u16) {
    register_operations(owner, access, 5).await
}
async fn register_operations(owner: &Connection, access: u32, operations: u32) -> (u16, u16) {
    let proxy = zbus::Proxy::new(
        owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let (start, _, properties): (u16, u16, Vec<u16>) = proxy
        .call(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                vec![(vec![2u8, 0], operations, access, vec![7u8])],
                OwnedObjectPath::try_from("/authorizer").unwrap(),
                owned_deadline(),
            ),
        )
        .await
        .unwrap();
    (start, properties[0])
}
async fn store(state: &crate::state::SharedState) -> Store {
    state.lock().await.ssap_database.clone()
}
fn packet(request: ValuePdu<'_>, id: u64, level: u32, wait: Duration) -> ServerPacket {
    let deadline = Instant::now() + wait;
    let mut bytes = vec![0; 249];
    let n = request.encode(249, &mut bytes).unwrap();
    bytes.truncate(n);
    ServerPacket {
        bytes,
        deadline,
        mtu: 249,
        level,
        request_id: id,
        constraint: Some(slk_protocol::SleSendConstraint {
            version: 1,
            size: 48,
            minimum: level,
            controller: 0,
            generation: 7,
            lifetime: 13,
            handle: 1,
            security_epoch: 41,
            local_tcid: 10,
            remote_tcid: 10,
            pi: 0,
            deadline_monotonic_ns: monotonic_deadline(deadline).unwrap(),
            reserved: 0,
        }),
    }
}
async fn render(request: ServerPacket, database: &Store) -> Vec<u8> {
    let decision = authorize_server(request, database.clone()).await;
    server_response(
        &decision.packet,
        database,
        &decision.approvals,
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
    .unwrap()
}

#[tokio::test]
async fn actual_owner_callback_approves_reads_writes_and_uuid_without_disclosing_read_values() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::ZERO).await;
    let (_, h) = register(&owner, 36).await;
    let db = store(&state).await;
    let response = render(
        packet(
            ValuePdu::Read {
                handle: h,
                data_type: 0,
            },
            1,
            0,
            Duration::from_secs(1),
        ),
        &db,
    )
    .await;
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::ReadValue(&[7])
    );
    let prompt = seen.recv().await.unwrap();
    assert_eq!(prompt.0, 1);
    assert_eq!(prompt.1, (0, 7, 13, 1, 41, 0, 10, 10, 0));
    assert!(!prompt.3);
    assert!(prompt.5.is_empty());
    let response = render(
        packet(
            ValuePdu::Write {
                handle: h,
                data_type: 0,
                value: &[9],
                verify: true,
            },
            2,
            0,
            Duration::from_secs(1),
        ),
        &db,
    )
    .await;
    assert_eq!(db.lock().unwrap().local_read(h).unwrap(), [9]);
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::WrittenValue {
            handle: h,
            data_type: 0,
            value: &[9]
        }
    );
    let prompt = seen.recv().await.unwrap();
    assert!(prompt.3);
    assert_eq!(prompt.5, [9]);
    let mut p = packet(
        ValuePdu::Read {
            handle: h,
            data_type: 0,
        },
        3,
        0,
        Duration::from_secs(1),
    );
    let request = slk_protocol::ssap::read_uuid::Request {
        start: 16,
        end: 65535,
        data_type: 0,
        uuid: &[2, 0],
    };
    p.bytes.resize(22, 0);
    let n = request.encode(249, &mut p.bytes).unwrap();
    p.bytes.truncate(n);
    let response = render(p, &db).await;
    let entries = slk_protocol::ssap::read_uuid::decode(249, &response).unwrap();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].value, Ok(&[9][..]));
    let prompt = seen.recv().await.unwrap();
    assert_eq!((prompt.0, prompt.2, prompt.3), (3, h, false));
    assert!(prompt.5.is_empty());
}

#[tokio::test]
async fn denial_and_missing_callback_never_read_or_mutate_protected_value() {
    let (_bus, state, _server, owner, mut seen) = setup(false, Duration::ZERO).await;
    let (_, h) = register(&owner, 36).await;
    let db = store(&state).await;
    for (id, request) in [
        (
            1,
            ValuePdu::Read {
                handle: h,
                data_type: 0,
            },
        ),
        (
            2,
            ValuePdu::Write {
                handle: h,
                data_type: 0,
                value: &[9],
                verify: true,
            },
        ),
    ] {
        let response = render(packet(request, id, 0, Duration::from_secs(1)), &db).await;
        assert!(matches!(
            ValuePdu::decode(249, &response).unwrap(),
            ValuePdu::ReadError(9) | ValuePdu::WriteError { error: 9, .. }
        ));
        assert_eq!(db.lock().unwrap().local_read(h).unwrap(), [7]);
        seen.recv().await.unwrap();
    }
    owner
        .object_server()
        .remove::<Consent, _>("/authorizer")
        .await
        .unwrap();
    let response = render(
        packet(
            ValuePdu::Read {
                handle: h,
                data_type: 0,
            },
            3,
            0,
            Duration::from_secs(1),
        ),
        &db,
    )
    .await;
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::ReadError(9)
    );
}

#[tokio::test]
async fn approval_cannot_bypass_operations_or_original_mechanism_floor() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::ZERO).await;
    let (_, h) = register(&owner, 54).await;
    let db = store(&state).await;
    let response = render(
        packet(
            ValuePdu::Read {
                handle: h,
                data_type: 0,
            },
            1,
            1,
            Duration::from_secs(1),
        ),
        &db,
    )
    .await;
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::ReadError(9)
    );
    assert!(seen.try_recv().is_err());
    let response = render(
        packet(
            ValuePdu::Read {
                handle: h,
                data_type: 0,
            },
            2,
            2,
            Duration::from_secs(1),
        ),
        &db,
    )
    .await;
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::ReadValue(&[7])
    );
    assert_eq!(seen.recv().await.unwrap().1.5, 2);
}

#[tokio::test]
async fn original_deadline_and_native_recheck_precede_value_mutation() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::from_millis(100)).await;
    let (_, h) = register(&owner, 36).await;
    let db = store(&state).await;
    let request = packet(
        ValuePdu::Write {
            handle: h,
            data_type: 0,
            value: &[9],
            verify: true,
        },
        1,
        0,
        Duration::from_millis(20),
    );
    let original = request.constraint.unwrap();
    let decision = authorize_server(request, db.clone()).await;
    seen.recv().await.unwrap();
    assert!(decision.approvals.is_empty());
    assert_eq!(decision.packet.constraint, Some(original));
    let (a, _b) = std::os::unix::net::UnixDatagram::pair().unwrap();
    a.set_nonblocking(true).unwrap();
    let wire = Wire::native(AsyncFd::new(OwnedFd::from(a)).unwrap());
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
    assert_eq!(db.lock().unwrap().local_read(h).unwrap(), [7]);
    let decision = ServerDecision {
        values: vec![],
        write: None,
        admission_error: None,
        packet: packet(
            ValuePdu::Write {
                handle: h,
                data_type: 0,
                value: &[9],
                verify: true,
            },
            2,
            0,
            Duration::from_secs(1),
        ),
        approvals: vec![],
    };
    assert!(
        complete_server(
            &wire,
            decision,
            &db,
            &mut crate::ssap_engine_config::ClientConfigurations::default()
        )
        .is_err()
    );
    assert_eq!(db.lock().unwrap().local_read(h).unwrap(), [7]);
}

#[tokio::test]
async fn wrong_caller_cannot_remove_read_or_inherit_another_owner_service() {
    let (bus, state, _server, owner, _seen) = setup(true, Duration::ZERO).await;
    let (start, h) = register(&owner, 36).await;
    let stranger = client(&bus).await;
    let proxy = zbus::Proxy::new(
        &stranger,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    assert!(
        proxy
            .call::<_, _, Vec<u8>>("ReadOwnedLocalValue", &(h, owned_deadline()))
            .await
            .is_err()
    );
    assert!(
        proxy
            .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
            .await
            .is_err()
    );
    let own = zbus::Proxy::new(
        &owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    assert_eq!(
        own.call::<_, _, Vec<u8>>("ReadOwnedLocalValue", &(h, owned_deadline()))
            .await
            .unwrap(),
        [7]
    );
    own.call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    assert!(store(&state).await.lock().unwrap().local_read(h).is_err());
}

#[tokio::test]
async fn late_approval_for_removed_property_cannot_read_recreated_value() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::from_millis(60)).await;
    let (start, h) = register(&owner, 36).await;
    let db = store(&state).await;
    let future = tokio::spawn(authorize_server(
        packet(
            ValuePdu::Read {
                handle: h,
                data_type: 0,
            },
            1,
            0,
            Duration::from_secs(1),
        ),
        db.clone(),
    ));
    seen.recv().await.unwrap();
    db.lock().unwrap().remove(start).unwrap();
    let (_, new) = register(&owner, 36).await;
    assert!(new > h);
    let decision = future.await.unwrap();
    assert!(decision.approvals.is_empty());
    let response = server_response(
        &decision.packet,
        &db,
        &decision.approvals,
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
    .unwrap();
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::ReadError(4)
    );
    assert_eq!(db.lock().unwrap().local_read(new).unwrap(), [7]);
}

#[tokio::test]
async fn actual_owner_exit_removes_only_its_services_and_cancels_pending_approval() {
    let (bus, state, _server, owner, mut seen) = setup(true, Duration::from_millis(200)).await;
    let (_, h) = register(&owner, 36).await;
    let other = client(&bus).await;
    let (_, other_h) = register(&other, 0).await;
    let db = store(&state).await;
    let future = tokio::spawn(authorize_server(
        packet(
            ValuePdu::Write {
                handle: h,
                data_type: 0,
                value: &[9],
                verify: true,
            },
            1,
            0,
            Duration::from_secs(1),
        ),
        db.clone(),
    ));
    seen.recv().await.unwrap();
    owner.close().await.unwrap();
    tokio::time::timeout(Duration::from_secs(1), async {
        while db.lock().unwrap().local_read(h).is_ok() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let decision = future.await.unwrap();
    assert!(decision.approvals.is_empty());
    assert_eq!(db.lock().unwrap().local_read(other_h).unwrap(), [7]);
    assert_eq!(state.lock().await.ssap_owner_slots.available_permits(), 15);
}

#[tokio::test]
async fn explicit_adapter_retirement_drains_watches_with_owner_and_bus_still_alive() {
    let (_bus, state, _server, owner, _seen) = setup(true, Duration::ZERO).await;
    let (_, h) = register(&owner, 36).await;
    let db = store(&state).await;
    let owners = db.lock().unwrap().retire();
    assert_eq!(owners.len(), 1);
    assert!(!owners[0].current());
    assert!(db.lock().unwrap().local_read(h).is_err());
    for owner in &owners {
        owner.shutdown().await;
    }
    drop(owners);
    assert_eq!(state.lock().await.ssap_owner_slots.available_permits(), 16);
}

fn owned_deadline() -> slk_contract::Deadline {
    slk_contract::deadline_wire(
        slk_channel::deadline::Deadline::after(Duration::from_secs(2))
            .unwrap()
            .stamp(),
    )
}

#[tokio::test]
async fn owned_description_is_public_read_only_and_preserves_property_and_cpcd() {
    // The bus, owner watches, database and server render are production code;
    // Native lease/Ready/RX identity remain the explicit setup/packet fixtures.
    let (_bus, state, _server, caller, mut prompts) = setup(true, Duration::ZERO).await;
    let (start, handle) = register_operations(&caller, 36, 8 | 512).await;
    let proxy = zbus::Proxy::new(
        &caller,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let database = store(&state).await;
    let read = || ValuePdu::Read {
        handle,
        data_type: 1,
    };
    let missing = render(packet(read(), 1, 0, Duration::from_secs(1)), &database).await;
    assert_eq!(
        ValuePdu::decode(249, &missing).unwrap(),
        ValuePdu::ReadError(13)
    );
    let before = database.lock().unwrap().list();
    let description = "é".repeat(122);
    assert_eq!(description.len(), 244);
    proxy
        .call::<_, _, ()>(
            "SetOwnedLocalDescription",
            &(handle, description.clone(), owned_deadline()),
        )
        .await
        .unwrap();
    assert_eq!(
        database.lock().unwrap().list(),
        before,
        "no new handle or permission bits"
    );
    for level in 0..=2 {
        let response = render(packet(read(), 2, level, Duration::from_secs(1)), &database).await;
        assert_eq!(
            ValuePdu::decode(249, &response).unwrap(),
            ValuePdu::ReadValue(description.as_bytes())
        );
    }
    assert!(
        prompts.try_recv().is_err(),
        "public description cannot invoke the property authorizer"
    );
    {
        use slk_protocol::ssap::discovery::{EntryClass, FindKind, FindRequest, decode_page};
        let mut db = database.lock().unwrap();
        let request = FindRequest {
            kind: FindKind::Properties,
            class: EntryClass::Mixed,
            start,
            end: handle,
            uuid: None,
        };
        let raw = db.find(request, 249).unwrap();
        let entries = decode_page(request, 249, &raw).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].handle, handle);
        assert_eq!(entries[0].descriptors, [1, 2]);
        assert_eq!(
            entries[0].operations,
            8 | 512,
            "description does not imply property READ"
        );
        assert!(db.value_targets(read(), 0).is_empty());
        let small = db.answer(read(), 20, 0).unwrap();
        assert_eq!(
            ValuePdu::decode(20, &small).unwrap(),
            ValuePdu::ReadError(16)
        );
        for data_type in [1, 3, 4, 255] {
            let write = ValuePdu::Write {
                handle,
                data_type,
                value: b"changed",
                verify: true,
            };
            assert!(db.value_targets(write, 2).is_empty());
            let response = db.answer(write, 249, 2).unwrap();
            assert_eq!(
                ValuePdu::decode(249, &response).unwrap(),
                ValuePdu::WriteError { handle, error: 13 }
            );
        }
        for data_type in [3, 4, 255] {
            let response = db
                .answer(ValuePdu::Read { handle, data_type }, 249, 0)
                .unwrap();
            assert_eq!(
                ValuePdu::decode(249, &response).unwrap(),
                ValuePdu::ReadError(13)
            );
        }
        let property = db
            .answer(
                ValuePdu::Read {
                    handle,
                    data_type: 0,
                },
                249,
                2,
            )
            .unwrap();
        assert_eq!(
            ValuePdu::decode(249, &property).unwrap(),
            ValuePdu::ReadError(6)
        );
        assert_eq!(db.local_read(handle).unwrap(), [7]);
    }
    let mut configurations = crate::ssap_engine_config::ClientConfigurations::default();
    let request = packet(
        ValuePdu::Read {
            handle,
            data_type: 2,
        },
        3,
        2,
        Duration::from_secs(1),
    );
    let cpcd = server_response(&request, &database, &[], &mut configurations).unwrap();
    assert_eq!(
        ValuePdu::decode(249, &cpcd).unwrap(),
        ValuePdu::ReadValue(&[0, 0])
    );
    for invalid in [String::new(), "a".repeat(245), "é".repeat(123)] {
        let error = proxy
            .call::<_, _, ()>(
                "SetOwnedLocalDescription",
                &(handle, invalid, owned_deadline()),
            )
            .await;
        assert!(matches!(error, Err(zbus::Error::MethodError(name, _, _))
            if name.as_str() == "org.freedesktop.DBus.Error.InvalidArgs"));
    }
    assert_eq!(
        database.lock().unwrap().set_owned_description(
            handle,
            caller.unique_name().unwrap().as_str(),
            "has\0nul".into()
        ),
        Err(crate::ssap_database::LocalValueError::Length)
    );
    let owner = database
        .lock()
        .unwrap()
        .configuration_property(handle)
        .unwrap()
        .1;
    owner.revoke(); // retained row before asynchronous retirement must be unreadable
    let retired = database.lock().unwrap().answer(read(), 249, 0).unwrap();
    assert_eq!(
        ValuePdu::decode(249, &retired).unwrap(),
        ValuePdu::ReadError(4)
    );
    assert!(
        proxy
            .call::<_, _, ()>(
                "SetOwnedLocalDescription",
                &(handle, "late", owned_deadline())
            )
            .await
            .is_err()
    );
    database.lock().unwrap().remove(start).unwrap();
    owner.shutdown().await;
}

#[tokio::test]
async fn owned_description_budget_owner_deadline_and_retirement_are_atomic() {
    let (bus, state, _server, caller, _) = setup(false, Duration::ZERO).await;
    let (start, handle) = register_operations(&caller, 0, 1).await;
    let proxy = zbus::Proxy::new(
        &caller,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let database = store(&state).await;
    assert_eq!(database.lock().unwrap().local_read(handle).unwrap(), [7]);
    database
        .lock()
        .unwrap()
        .register(
            vec![3, 0],
            (0..4)
                .map(|n| (vec![4 + n, 0], 1, 0, vec![0; 2042]))
                .collect(),
        )
        .unwrap();
    // 8168 staging + 1 owned value byte + 23 description bytes exhaust8192.
    proxy
        .call::<_, _, ()>(
            "SetOwnedLocalDescription",
            &(handle, "a".repeat(23), owned_deadline()),
        )
        .await
        .unwrap();
    let error = proxy
        .call::<_, _, ()>(
            "SetOwnedLocalDescription",
            &(handle, "b".repeat(24), owned_deadline()),
        )
        .await;
    assert!(matches!(error, Err(zbus::Error::MethodError(name, _, _))
        if name.as_str() == "org.freedesktop.DBus.Error.LimitsExceeded"));
    proxy
        .call::<_, _, ()>(
            "ReplaceOwnedLocalValue",
            &(handle, Vec::<u8>::new(), owned_deadline()),
        )
        .await
        .unwrap();
    proxy
        .call::<_, _, ()>(
            "SetOwnedLocalDescription",
            &(handle, "c".repeat(24), owned_deadline()),
        )
        .await
        .unwrap();
    let foreign = client(&bus).await;
    let other = zbus::Proxy::new(
        &foreign,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let error = other
        .call::<_, _, ()>(
            "SetOwnedLocalDescription",
            &(handle, "foreign", owned_deadline()),
        )
        .await;
    assert!(matches!(error, Err(zbus::Error::MethodError(name, _, _))
        if name.as_str() == "org.freedesktop.DBus.Error.AccessDenied"));
    let original = slk_channel::deadline::Deadline::after(Duration::from_millis(20)).unwrap();
    let held = state.lock().await;
    let error = proxy
        .call::<_, _, ()>(
            "SetOwnedLocalDescription",
            &(
                handle,
                "late",
                slk_contract::deadline_wire(original.stamp()),
            ),
        )
        .await;
    assert!(matches!(error, Err(zbus::Error::MethodError(name, _, _))
        if name.as_str() == "org.freedesktop.DBus.Error.Timeout"));
    drop(held);
    let lease = state.lock().await.native_lease.clone().unwrap();
    lease.lock().await.accepting = false;
    assert!(
        proxy
            .call::<_, _, ()>(
                "SetOwnedLocalDescription",
                &(handle, "revoked", owned_deadline())
            )
            .await
            .is_err()
    );
    lease.lock().await.accepting = true;
    state.lock().await.present = false;
    assert!(
        proxy
            .call::<_, _, ()>(
                "SetOwnedLocalDescription",
                &(handle, "retired", owned_deadline())
            )
            .await
            .is_err()
    );
    state.lock().await.present = true; // fixture only; production generations never revive this way
    let response = database
        .lock()
        .unwrap()
        .answer(
            ValuePdu::Read {
                handle,
                data_type: 1,
            },
            249,
            0,
        )
        .unwrap();
    assert_eq!(
        ValuePdu::decode(249, &response).unwrap(),
        ValuePdu::ReadValue(&[b'c'; 24])
    );
    proxy
        .call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    // The description's budget is returned with the service; staging never
    // acquires an Owned setter just because it also has a property handle.
    {
        let mut db = database.lock().unwrap();
        let (_, _, handles) = db
            .register(vec![9, 0], vec![(vec![10, 0], 1, 0, vec![0; 24])])
            .unwrap();
        assert_eq!(
            db.set_owned_description(
                handles[0],
                caller.unique_name().unwrap().as_str(),
                "x".into()
            ),
            Err(crate::ssap_database::LocalValueError::Owner)
        );
        assert!(
            db.register(vec![11, 0], vec![(vec![12, 0], 1, 0, vec![0])])
                .is_err()
        );
        db.retire();
        db.register(vec![13, 0], vec![(vec![14, 0], 1, 0, vec![0; 2042]); 4])
            .unwrap();
    }
}

#[tokio::test]
async fn cancelled_owner_initialization_keeps_capacity_until_task_drains() {
    use crate::ssap_authorization::Owner;
    use std::sync::{Arc, Mutex};
    use std::{
        future::Future,
        task::{Context, Waker},
    };
    let bus = PrivateBus::start();
    let server = client(&bus).await;
    let caller = client(&bus).await;
    let database = Arc::new(Mutex::new(crate::ssap_database::Database::default()));
    let slots = Arc::new(tokio::sync::Semaphore::new(1));
    let slot = slots.clone().try_acquire_owned().unwrap();
    let mut pin = Box::pin(Owner::pin(
        &server,
        caller.unique_name().unwrap().to_string(),
        OwnedObjectPath::try_from("/").unwrap(),
        &database,
        slot,
        Instant::now() + Duration::from_secs(1),
    ));
    // The current-thread runtime cannot poll the spawned watch until we yield.
    // Cancel the actual production initializer after spawn,before watch startup.
    assert!(
        pin.as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    drop(pin);
    assert_eq!(
        slots.available_permits(),
        0,
        "abort request is not a task-drain receipt"
    );
    tokio::time::timeout(Duration::from_secs(1), async {
        while slots.available_permits() != 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(database.lock().unwrap().list().is_empty());
}

#[tokio::test]
async fn expired_owned_rpc_and_old_shapes_never_register_read_or_remove() {
    let (_bus, state, _server, owner, _seen) = setup(true, Duration::ZERO).await;
    let db = store(&state).await;
    let proxy = zbus::Proxy::new(
        &owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let properties = vec![(vec![2u8, 0], 5u32, 0u32, vec![7u8])];
    let authorizer = OwnedObjectPath::try_from("/").unwrap();
    let mut expired = owned_deadline();
    expired.0 = 1;
    let error = proxy
        .call::<_, _, (u16, u16, Vec<u16>)>(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                properties.clone(),
                authorizer.clone(),
                expired,
            ),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(error,zbus::Error::MethodError(ref name,_,_) if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
    );
    assert!(db.lock().unwrap().list().is_empty());
    let error = proxy
        .call::<_, _, (u16, u16, Vec<u16>)>(
            "RegisterOwnedLocalService",
            &(vec![1u8, 0], properties, authorizer),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(error,zbus::Error::MethodError(ref name,Some(ref text),_) if
            name.as_str()=="org.freedesktop.zbus.Error" && text == "Signature mismatch: got `(aya(ayuuay)o)`, expected `(aya(ayuuay)o(ttttt))`"),
        "{error:?}"
    );
    let (start, handle) = register(&owner, 0).await;
    for method in ["ReadOwnedLocalValue", "UnregisterOwnedLocalService"] {
        let value = if method == "ReadOwnedLocalValue" {
            handle
        } else {
            start
        };
        let error = owner
            .call_method(
                Some("org.sparklink.AuthTest"),
                "/services",
                Some("org.sparklink.ServiceManager"),
                method,
                &(value, expired),
            )
            .await
            .unwrap_err();
        assert!(
            matches!(error,zbus::Error::MethodError(ref name,_,_) if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
        );
        let error = owner
            .call_method(
                Some("org.sparklink.AuthTest"),
                "/services",
                Some("org.sparklink.ServiceManager"),
                method,
                &(value,),
            )
            .await
            .unwrap_err();
        assert!(
            matches!(error,zbus::Error::MethodError(ref name,Some(ref text),_) if
                name.as_str()=="org.freedesktop.zbus.Error" && text == "Signature mismatch: got `q`, expected `(q(ttttt))`"),
            "{error:?}"
        );
    }
    assert_eq!(db.lock().unwrap().local_read(handle).unwrap(), [7]);
}

#[tokio::test]
async fn original_owned_rpc_deadline_covers_state_lock_and_cannot_resume_late() {
    let (_bus, state, _server, owner, _seen) = setup(true, Duration::ZERO).await;
    let db = store(&state).await;
    let proxy = zbus::Proxy::new(
        &owner,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let held = state.lock().await;
    let deadline = slk_channel::deadline::Deadline::after(Duration::from_millis(30)).unwrap();
    let body = (
        vec![1u8, 0],
        vec![(vec![2u8, 0], 5u32, 0u32, vec![7u8])],
        OwnedObjectPath::try_from("/").unwrap(),
        slk_contract::deadline_wire(deadline.stamp()),
    );
    let result = tokio::time::timeout(
        Duration::from_secs(1),
        proxy.call::<_, _, (u16, u16, Vec<u16>)>("RegisterOwnedLocalService", &body),
    )
    .await
    .unwrap();
    assert!(
        matches!(result,Err(zbus::Error::MethodError(ref name,_,_)) if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
    );
    drop(held);
    tokio::task::yield_now().await;
    assert!(db.lock().unwrap().list().is_empty());
    assert_eq!(state.lock().await.ssap_owner_slots.available_permits(), 16);
    let (start, handle) = register(&owner, 0).await;
    let before = db.lock().unwrap().list();
    let held = state.lock().await;
    let deadline = slk_channel::deadline::Deadline::after(Duration::from_millis(30)).unwrap();
    let result = tokio::time::timeout(
        Duration::from_secs(1),
        proxy.call::<_, _, ()>(
            "UnregisterOwnedLocalService",
            &(start, slk_contract::deadline_wire(deadline.stamp())),
        ),
    )
    .await
    .unwrap();
    assert!(
        matches!(result,Err(zbus::Error::MethodError(ref name,_,_)) if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
    );
    drop(held);
    tokio::task::yield_now().await;
    assert_eq!(db.lock().unwrap().list(), before);
    assert_eq!(db.lock().unwrap().local_read(handle).unwrap(), [7]);
}

#[tokio::test]
async fn owner_registration_deadline_is_not_the_active_service_lifetime() {
    use crate::ssap_authorization::Owner;
    let bus = PrivateBus::start();
    let server = client(&bus).await;
    let caller = client(&bus).await;
    let db: Store = std::sync::Arc::new(std::sync::Mutex::new(
        crate::ssap_database::Database::default(),
    ));
    let slots = std::sync::Arc::new(tokio::sync::Semaphore::new(2));
    let until = Instant::now() + Duration::from_millis(100);
    let owner = Owner::pin(
        &server,
        caller.unique_name().unwrap().to_string(),
        OwnedObjectPath::try_from("/").unwrap(),
        &db,
        slots.clone().try_acquire_owned().unwrap(),
        until,
    )
    .await
    .unwrap();
    let (start, _, handles) = db
        .lock()
        .unwrap()
        .register_owned(vec![1, 0], vec![(vec![2, 0], 5, 0, vec![7])], owner.clone())
        .unwrap();
    tokio::time::sleep_until(until).await;
    assert!(owner.current());
    assert!(!owner.can_register());
    assert_eq!(db.lock().unwrap().local_read(handles[0]).unwrap(), [7]);
    let before = db.lock().unwrap().list();
    assert!(
        db.lock()
            .unwrap()
            .register_owned(vec![3, 0], vec![(vec![4, 0], 5, 0, vec![9])], owner.clone())
            .is_err()
    );
    assert_eq!(db.lock().unwrap().list(), before);
    db.lock()
        .unwrap()
        .remove_owned(start, caller.unique_name().unwrap().as_str())
        .unwrap();
    owner.shutdown().await;
    assert_eq!(slots.available_permits(), 2);
}

#[tokio::test]
async fn actual_owned_replacement_preserves_peer_permissions_budget_and_owner() {
    let (_bus, state, _server, caller, _) = setup(false, Duration::ZERO).await;
    let own = zbus::Proxy::new(
        &caller,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let (start, _, handles): (u16, u16, Vec<u16>) = own
        .call(
            "RegisterOwnedLocalService",
            &(
                vec![1u8, 0],
                vec![(vec![2u8, 0], 1u32, 0u32, vec![7u8])],
                OwnedObjectPath::try_from("/").unwrap(),
                owned_deadline(),
            ),
        )
        .await
        .unwrap();
    let handle = handles[0];
    let db = store(&state).await;
    let methods = own.introspect().await.unwrap();
    assert!(methods.contains("ReplaceOwnedLocalValue"));
    own.call::<_, _, ()>(
        "ReplaceOwnedLocalValue",
        &(handle, vec![8u8, 9], owned_deadline()),
    )
    .await
    .unwrap();
    {
        let mut db = db.lock().unwrap();
        assert_eq!(db.local_read(handle).unwrap(), [8, 9]);
        let response = db
            .answer(
                ValuePdu::Read {
                    handle,
                    data_type: 0,
                },
                249,
                0,
            )
            .unwrap();
        assert_eq!(
            ValuePdu::decode(249, &response).unwrap(),
            ValuePdu::ReadValue(&[8, 9])
        );
        let response = db
            .answer(
                ValuePdu::Write {
                    handle,
                    data_type: 0,
                    value: &[99],
                    verify: true,
                },
                249,
                0,
            )
            .unwrap();
        assert_eq!(
            ValuePdu::decode(249, &response).unwrap(),
            ValuePdu::WriteError { handle, error: 7 }
        );
        assert_eq!(db.local_read(handle).unwrap(), [8, 9]);
        db.register(
            vec![3, 0],
            (0..4)
                .map(|n| (vec![4 + n, 0], 1, 0, vec![0; 2042]))
                .collect(),
        )
        .unwrap();
    }
    own.call::<_, _, ()>(
        "ReplaceOwnedLocalValue",
        &(handle, vec![5u8; 24], owned_deadline()),
    )
    .await
    .unwrap();
    for (value, expected) in [
        (vec![6u8; 25], "org.freedesktop.DBus.Error.LimitsExceeded"),
        (vec![6u8; 2043], "org.freedesktop.DBus.Error.InvalidArgs"),
    ] {
        let result = own
            .call::<_, _, ()>("ReplaceOwnedLocalValue", &(handle, value, owned_deadline()))
            .await;
        assert!(
            matches!(result,Err(zbus::Error::MethodError(name,_,_)) if name.as_str()==expected)
        );
        assert_eq!(db.lock().unwrap().local_read(handle).unwrap(), vec![5; 24]);
    }
    let foreign = client(&_bus).await;
    let other = zbus::Proxy::new(
        &foreign,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let result = other
        .call::<_, _, ()>(
            "ReplaceOwnedLocalValue",
            &(handle, vec![1u8], owned_deadline()),
        )
        .await;
    assert!(
        matches!(result,Err(zbus::Error::MethodError(name,_,_)) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
    own.call::<_, _, ()>(
        "ReplaceOwnedLocalValue",
        &(handle, Vec::<u8>::new(), owned_deadline()),
    )
    .await
    .unwrap();
    assert!(db.lock().unwrap().local_read(handle).unwrap().is_empty());
    own.call::<_, _, ()>("UnregisterOwnedLocalService", &(start, owned_deadline()))
        .await
        .unwrap();
    let result = own
        .call::<_, _, ()>(
            "ReplaceOwnedLocalValue",
            &(handle, vec![1u8], owned_deadline()),
        )
        .await;
    assert!(
        matches!(result,Err(zbus::Error::MethodError(name,_,_)) if name.as_str()=="org.freedesktop.DBus.Error.AccessDenied")
    );
}

#[tokio::test]
async fn actual_owned_replacement_original_expiry_and_revocation_never_commit() {
    let (_bus, state, _server, caller, _) = setup(false, Duration::ZERO).await;
    let (_start, h) = register(&caller, 0).await;
    let own = zbus::Proxy::new(
        &caller,
        "org.sparklink.AuthTest",
        "/services",
        "org.sparklink.ServiceManager",
    )
    .await
    .unwrap();
    let original = slk_channel::deadline::Deadline::after(Duration::from_millis(20)).unwrap();
    let held = state.lock().await;
    let args = (h, vec![9u8], slk_contract::deadline_wire(original.stamp()));
    let request = own.call::<_, _, ()>("ReplaceOwnedLocalValue", &args);
    assert!(
        matches!(request.await,Err(zbus::Error::MethodError(name,_,_)) if name.as_str()=="org.freedesktop.DBus.Error.Timeout")
    );
    drop(held);
    assert_eq!(
        store(&state).await.lock().unwrap().local_read(h).unwrap(),
        [7]
    );
    let lease = state.lock().await.native_lease.clone().unwrap();
    lease.lock().await.accepting = false;
    assert!(
        own.call::<_, _, ()>("ReplaceOwnedLocalValue", &(h, vec![9u8], owned_deadline()))
            .await
            .is_err()
    );
    assert_eq!(
        store(&state).await.lock().unwrap().local_read(h).unwrap(),
        [7]
    );
    lease.lock().await.accepting = true;
    state.lock().await.present = false;
    assert!(
        own.call::<_, _, ()>("ReplaceOwnedLocalValue", &(h, vec![9u8], owned_deadline()))
            .await
            .is_err()
    );
    assert_eq!(
        store(&state).await.lock().unwrap().local_read(h).unwrap(),
        [7]
    );
}

#[tokio::test]
async fn actual_database_approval_is_bound_to_the_original_data_type() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::ZERO).await;
    let (_, handle) = register(&owner, 36).await;
    let database = store(&state).await;
    let request = packet(
        ValuePdu::Write {
            handle,
            data_type: 0,
            value: &[9],
            verify: true,
        },
        23,
        0,
        Duration::from_secs(1),
    );
    let mut decision = authorize_server(request, database.clone()).await;
    assert_eq!(seen.recv().await.unwrap().6, 0);
    assert_eq!(decision.approvals.len(), 1);
    assert_eq!(decision.approvals[0].data_type, 0);
    decision.approvals[0].data_type = 2;
    let rejected = server_response(
        &decision.packet,
        &database,
        &decision.approvals,
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
    .unwrap();
    assert_eq!(
        ValuePdu::decode(249, &rejected).unwrap(),
        ValuePdu::WriteError { handle, error: 9 }
    );
    assert_eq!(database.lock().unwrap().local_read(handle).unwrap(), [7]);
    decision.approvals[0].data_type = 0;
    decision.approvals[0].write = false;
    let rejected = server_response(
        &decision.packet,
        &database,
        &decision.approvals,
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
    .unwrap();
    assert_eq!(
        ValuePdu::decode(249, &rejected).unwrap(),
        ValuePdu::WriteError { handle, error: 9 }
    );
    assert_eq!(database.lock().unwrap().local_read(handle).unwrap(), [7]);
    decision.approvals[0].write = true;
    let committed = server_response(
        &decision.packet,
        &database,
        &decision.approvals,
        &mut crate::ssap_engine_config::ClientConfigurations::default(),
    )
    .unwrap();
    assert_eq!(
        ValuePdu::decode(249, &committed).unwrap(),
        ValuePdu::WrittenValue {
            handle,
            data_type: 0,
            value: &[9]
        }
    );
    assert_eq!(database.lock().unwrap().local_read(handle).unwrap(), [9]);
}

/// Real owner/DB/policy and production configuration transitions. Receipt
/// security is an explicit fixture; this does not prove Native authentication.
#[tokio::test]
async fn actual_client_configuration_is_session_scoped_and_requires_typed_authenticated_approval() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::ZERO).await;
    let (start, handle) = register_operations(&owner, 0, 5 | 8 | 16 | 512).await;
    let database = store(&state).await;
    let mut first = crate::ssap_engine_config::ClientConfigurations::default();
    let mut other = crate::ssap_engine_config::ClientConfigurations::default();
    let read = packet(
        ValuePdu::Read {
            handle,
            data_type: 2,
        },
        1,
        0,
        Duration::from_secs(1),
    );
    let decode = |bytes: Vec<u8>| match ValuePdu::decode(249, &bytes).unwrap() {
        ValuePdu::ReadValue(value) => value.to_vec(),
        p => panic!("expected configuration read: {p:?}"),
    };
    assert_eq!(
        decode(server_response(&read, &database, &[], &mut first).unwrap()),
        [0, 0]
    );
    let plain = packet(
        ValuePdu::Write {
            handle,
            data_type: 2,
            value: &[1, 0],
            verify: true,
        },
        2,
        0,
        Duration::from_secs(1),
    );
    let denied = authorize_server(plain, database.clone()).await;
    assert!(denied.approvals.is_empty() && seen.try_recv().is_err());
    assert_eq!(
        ValuePdu::decode(
            249,
            &server_response(&denied.packet, &database, &[], &mut first).unwrap()
        )
        .unwrap(),
        ValuePdu::WriteError { handle, error: 9 }
    );
    let write = packet(
        ValuePdu::Write {
            handle,
            data_type: 2,
            value: &[3, 0],
            verify: true,
        },
        3,
        2,
        Duration::from_secs(1),
    );
    let mut decision = authorize_server(write, database.clone()).await;
    let prompt = seen.recv().await.unwrap();
    assert_eq!(
        (prompt.6, prompt.3, prompt.1.5, prompt.5),
        (2, true, 2, vec![3, 0])
    );
    assert_eq!(decision.approvals.len(), 1);
    for (data_type, write) in [(0, true), (2, false)] {
        decision.approvals[0].data_type = data_type;
        decision.approvals[0].write = write;
        assert_eq!(
            ValuePdu::decode(
                249,
                &server_response(&decision.packet, &database, &decision.approvals, &mut first)
                    .unwrap()
            )
            .unwrap(),
            ValuePdu::WriteError { handle, error: 9 }
        );
        assert_eq!(
            decode(server_response(&read, &database, &[], &mut first).unwrap()),
            [0, 0]
        );
    }
    decision.approvals[0].data_type = 2;
    decision.approvals[0].write = true;
    assert_eq!(
        ValuePdu::decode(
            249,
            &server_response(&decision.packet, &database, &decision.approvals, &mut first).unwrap()
        )
        .unwrap(),
        ValuePdu::WrittenValue {
            handle,
            data_type: 2,
            value: &[3, 0]
        }
    );
    assert_eq!(
        decode(server_response(&read, &database, &[], &mut first).unwrap()),
        [3, 0]
    );
    assert_eq!(
        decode(server_response(&read, &database, &[], &mut other).unwrap()),
        [0, 0]
    );
    assert_eq!(database.lock().unwrap().local_read(handle).unwrap(), [7]);
    let mut new_epoch = packet(
        ValuePdu::Read {
            handle,
            data_type: 2,
        },
        4,
        0,
        Duration::from_secs(1),
    );
    new_epoch.constraint.as_mut().unwrap().security_epoch = 42;
    assert_eq!(
        decode(server_response(&new_epoch, &database, &[], &mut first).unwrap()),
        [0, 0]
    );
    let config_owner = database
        .lock()
        .unwrap()
        .configuration_property(handle)
        .unwrap()
        .1;
    first.set(handle, &config_owner, 42, 1).unwrap();
    database.lock().unwrap().remove(start).unwrap();
    assert_eq!(first.get(handle, &config_owner, 42), 0);
    assert!(
        database
            .lock()
            .unwrap()
            .owned_update(handle, owner.unique_name().unwrap().as_str())
            .is_err()
    );
}

#[tokio::test]
async fn actual_configuration_invalid_values_never_dispatch_policy_or_mutate_property() {
    let (_bus, state, _server, owner, mut seen) = setup(true, Duration::ZERO).await;
    let (_, handle) = register_operations(&owner, 0, 1 | 8 | 512).await;
    let database = store(&state).await;
    let mut configurations = crate::ssap_engine_config::ClientConfigurations::default();
    for value in [&[][..], &[1][..], &[1, 0, 0][..], &[2, 0][..], &[0, 1][..]] {
        let decision = authorize_server(
            packet(
                ValuePdu::Write {
                    handle,
                    data_type: 2,
                    value,
                    verify: true,
                },
                1,
                2,
                Duration::from_secs(1),
            ),
            database.clone(),
        )
        .await;
        assert!(decision.approvals.is_empty() && seen.try_recv().is_err());
        assert_eq!(
            ValuePdu::decode(
                249,
                &server_response(&decision.packet, &database, &[], &mut configurations).unwrap()
            )
            .unwrap(),
            ValuePdu::WriteError { handle, error: 5 }
        );
        assert_eq!(database.lock().unwrap().local_read(handle).unwrap(), [7]);
    }
    let config_owner = database
        .lock()
        .unwrap()
        .configuration_property(handle)
        .unwrap()
        .1;
    for handle in 1..=64 {
        configurations.set(handle, &config_owner, 41, 1).unwrap();
    }
    assert_eq!(configurations.set(65, &config_owner, 41, 1), Err(5));
    assert_eq!(configurations.set(1, &config_owner, 0, 1), Err(9));
    assert_eq!(configurations.set(1, &config_owner, 41, 4), Err(9));
    assert_eq!(configurations.get(1, &config_owner, 41), 1);
    configurations.set(1, &config_owner, 41, 0).unwrap();
    configurations.set(65, &config_owner, 41, 1).unwrap();
}

#[tokio::test]
async fn actual_update_wait_cancellation_keeps_admitted_identity_and_original_drain() {
    let (_bus, state, _server, owner, _) = setup(true, Duration::ZERO).await;
    let (_, handle) = register_operations(&owner, 0, 5 | 8 | 16 | 512).await;
    let database = store(&state).await;
    let owner = database
        .lock()
        .unwrap()
        .configuration_property(handle)
        .unwrap()
        .1;
    let now = Instant::now();
    let deadline = now + Duration::from_secs(1);
    let drain = now + Duration::from_secs(5);
    for admitted in [false, true] {
        let (reply, mut result) = oneshot::channel();
        let mut update = Some(UpdateRequest {
            submitted_all: admitted,
            handle,
            owner: owner.clone(),
            mode: 2,
            epoch: 41,
            deadline,
            drain: admitted.then_some(drain),
            pdu: vec![16, 3, 17, 0, 0, 0],
            reply: Some(reply),
        });
        let mut pending = VecDeque::from([
            Pending {
                sent: 0,
                bytes: vec![16, 3, 17, 0, 0, 0],
                deadline,
                purpose: Purpose::Update,
                constraint: None,
            },
            Pending {
                sent: 0,
                bytes: vec![1],
                deadline,
                purpose: Purpose::ValueResponse,
                constraint: None,
            },
        ]);
        result.close();
        retire_update_wait(&mut update, &mut pending, now);
        if admitted {
            let current = update.as_ref().unwrap();
            assert!(current.reply.is_none());
            assert_eq!(
                (
                    current.handle,
                    current.mode,
                    current.epoch,
                    current.deadline,
                    current.obligation_deadline()
                ),
                (handle, 2, 41, deadline, drain)
            );
            retire_update_wait(&mut update, &mut pending, now + Duration::from_secs(2));
            assert_eq!(update.as_ref().unwrap().obligation_deadline(), drain);
        } else {
            assert!(update.is_none());
            assert_eq!(pending.len(), 1);
            assert!(matches!(pending[0].purpose, Purpose::ValueResponse));
        }
    }
}

#[path = "ssap_read_provider_tests.rs"]
mod read_provider_tests;
