//! Real private D-Bus and production owner/DB/authorization/render functions.
//! Canonical Ready/lease and RX context are explicit FIXTURES; /dev/null never
//! supplies a successful native ioctl. No USB, kernel locks, crypto or RF proof.
use super::*;
use crate::{
    event_loop::tests::PrivateBus, security_policy::tests::state, service::SsapManagerIface,
};
use slk_protocol::ssap::SsapAuthorizationPrompt;
use tokio::sync::mpsc;
use zbus::{Connection, zvariant::OwnedObjectPath};

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
                vec![(vec![2u8, 0], 5u32, access, vec![7u8])],
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
    server_response(&decision.packet, database, &decision.approvals).unwrap()
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
        complete_server(&wire, decision, &db).err().unwrap().kind(),
        io::ErrorKind::TimedOut
    );
    assert_eq!(db.lock().unwrap().local_read(h).unwrap(), [7]);
    let decision = ServerDecision {
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
    assert!(complete_server(&wire, decision, &db).is_err());
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
    let response = server_response(&decision.packet, &db, &decision.approvals).unwrap();
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
