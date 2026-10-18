//! Production registry/RPC tests. Post-receipt states and integer receipts are
//! explicit fixtures, never real Native/USB/Complete or RF qualification.
use super::*;
use crate::{
    config::DaemonConfig,
    state::{AdapterState, NativeManagement},
};

fn state() -> SharedState {
    let fd = Arc::new(slk_native::Adapter::open("/dev/null").unwrap());
    let mut state = AdapterState::new(
        fd.clone(),
        DaemonConfig::default(),
        crate::bonding::BondingStore::new(&std::env::temp_dir(), "discovery-pure-state"),
        crate::profile::ProfileRegistry::new(),
    );
    state.native_control = Some(fd);
    state.native_lease = Some(Arc::new(tokio::sync::Mutex::new(NativeManagement {
        token: Some(7),
        accepting: true,
        connection_id: 0,
        initialized_off: [None; 2],
    })));
    state.controller.profile = 1;
    state.controller.generation = 23;
    state.native_discovery_policy = Some(slk_native::Ws73DiscoveryPolicy::default());
    Arc::new(tokio::sync::Mutex::new(state))
}
fn until() -> Deadline {
    Deadline::after(Duration::from_secs(2)).unwrap()
}
fn seed(service: &Arc<Coordinator>, name: &str, id: u64, prefix: Vec<u8>) -> Arc<Owner> {
    let owner = Arc::new(Owner {
        name: name.into(),
        active: AtomicBool::new(true),
        task: Mutex::new(None),
        _slot: Arc::new(service.owner_slot(name).unwrap()),
    });
    seed_owner(service, owner.clone(), id, prefix);
    owner
}
fn seed_owner(service: &Arc<Coordinator>, owner: Arc<Owner>, id: u64, prefix: Vec<u8>) {
    let mut st = service.store.lock().unwrap();
    if st.fence.current() == 0 {
        st.advance().unwrap();
    }
    st.phase = Phase::Running;
    st.scope = Some((23, 7));
    st.next = st.next.max(id);
    st.entries.insert(
        id,
        Entry {
            owner,
            prefix,
            minimum_rssi: -128,
            expires: Instant::now() + Duration::from_secs(10),
            opening: until().instant(),
            queue: VecDeque::new(),
            dropped: 0,
            kernel_lost: 0,
            reading: false,
            after_sequence: 0,
        },
    );
}
fn event(sequence: u64, generation: u64) -> slk_protocol::SleControllerEvent {
    slk_protocol::SleControllerEvent {
        seq: sequence,
        generation,
        timestamp_ns: sequence + 100,
        lost: 0,
        profile: 1,
        dev_index: 2,
        event_code: 0x180b,
        payload_len: 0,
        flags: 0,
        _reserved: 0,
        payload: [0; slk_protocol::CONTROLLER_EVENT_PAYLOAD_MAX],
    }
}
fn report(service: &Coordinator, sequence: u64, generation: u64, data: &[u8], rssi: i8) {
    let mut header = [0; 23];
    header[2..8].copy_from_slice(&[1, 2, 3, 4, 5, 6]);
    service.report(
        &event(sequence, generation),
        &slk_protocol::Ws73DiscoveryReport {
            header: &header,
            data,
            rssi,
        },
    );
}
fn receipt(enable: bool) -> slk_protocol::SleDiscoveryResult {
    slk_protocol::SleDiscoveryResult {
        version: 1,
        profile: 1,
        generation: 23,
        request_id: 41,
        operation: if enable { 3 } else { 4 },
        state: 3,
        radio_scan: if enable { 2 } else { 1 },
        opcode: 0x1002,
        count: if enable { 2 } else { 1 },
        step: if enable { 1 } else { 0 },
        ..Default::default()
    }
}

#[tokio::test]
async fn caller_release_and_filtered_reads_do_not_take_peer_queue_or_authority() {
    let state = state();
    let service = state.lock().await.discovery.clone();
    seed(&service, ":1.10", 1, vec![0x31]);
    seed(&service, ":1.11", 2, vec![0x32]);
    report(&service, 1, 23, &[0x31, 1], -40);
    report(&service, 2, 23, &[0x32, 2], -41);
    assert!(reports(&state, ":1.10", 2, false, until()).await.is_err());
    assert!(release(&state, ":1.10", 2, until()).await.is_err());
    assert!(!release(&state, ":1.10", 1, until()).await.unwrap());
    let batch = reports(&state, ":1.11", 2, false, until()).await.unwrap();
    assert_eq!(batch.reports.len(), 1);
    assert_eq!(batch.reports[0].data, [0x32, 2]);
    assert_eq!(
        state
            .lock()
            .await
            .native_lease
            .as_ref()
            .unwrap()
            .lock()
            .await
            .token,
        Some(7)
    );
    assert_eq!(service.store.lock().unwrap().phase, Phase::Running);
    assert!(service.store.lock().unwrap().cleanup.is_none());
}

#[tokio::test]
async fn production_filters_generation_queue_budget_and_gap_counters() {
    let state = state();
    let service = state.lock().await.discovery.clone();
    seed(&service, ":1.1", 1, vec![0xab]);
    seed(&service, ":1.2", 2, vec![0xcd]);
    service
        .store
        .lock()
        .unwrap()
        .entries
        .get_mut(&1)
        .unwrap()
        .minimum_rssi = -70;
    report(&service, 1, 24, &[0xab], -30);
    report(&service, 2, 23, &[0xab], 127);
    report(&service, 3, 23, &[0xab], -80);
    report(&service, 4, 23, &[0xaa], -30);
    for seq in 5..44 {
        report(&service, seq, 23, &[0xab, seq as u8], -40);
    }
    service.lost(3);
    let batch = reports(&state, ":1.1", 1, false, until()).await.unwrap();
    assert_eq!(batch.dropped, 7);
    assert_eq!(batch.kernel_lost, 3);
    assert_eq!(batch.reports.len(), 32);
    assert_eq!(batch.reports.first().unwrap().sequence, 12);
    assert_eq!(batch.reports.last().unwrap().sequence, 43);
    let other = reports(&state, ":1.2", 2, false, until()).await.unwrap();
    assert!(other.reports.is_empty());
    assert_eq!(other.dropped, 0);
    assert_eq!(other.kernel_lost, 3);
}

#[test]
fn cancelled_author_retains_physical_phase_and_old_drop_cannot_remove_new_scope() {
    let service = Arc::new(Coordinator::default());
    seed(&service, ":1.1", 1, vec![]);
    service.store.lock().unwrap().phase = Phase::Starting;
    drop(Reservation {
        service: Arc::downgrade(&service),
        id: 1,
        armed: true,
    });
    {
        let st = service.store.lock().unwrap();
        assert!(st.entries.is_empty());
        assert_eq!(st.phase, Phase::Starting);
        assert!(st.cleanup.is_some());
    }
    service.invalidate(false);
    service.credential_replaced();
    seed(&service, ":1.2", 2, vec![]);
    drop(Reservation {
        service: Arc::downgrade(&service),
        id: 1,
        armed: true,
    });
    {
        let st = service.store.lock().unwrap();
        assert_eq!(st.entries.len(), 1);
        assert_eq!(st.phase, Phase::Running);
        assert!(st.cleanup.is_none());
    }
}

#[test]
fn manager_stop_requires_exact_terminal_receipt_and_revokes_old_session() {
    let service = Arc::new(Coordinator::default());
    seed(&service, ":1.1", 1, vec![]);
    let old = service.store.lock().unwrap().fence.current();
    assert!(service.manager(23, 7, 40, 3).is_err());
    assert_eq!(service.store.lock().unwrap().entries.len(), 1);
    service.manager(23, 7, 41, 4).unwrap();
    assert!(!service.store.lock().unwrap().fence.accepts(old));
    assert!(service.store.lock().unwrap().entries.is_empty());
    for mutate in 0..9 {
        let mut r = receipt(false);
        let mut token = 7;
        match mutate {
            0 => token = 8,
            1 => r.generation = 24,
            2 => r.request_id = 42,
            3 => r.operation = 3,
            4 => r.state = 2,
            5 => r.status = 0x0b,
            6 => r.radio_scan = 2,
            7 => r.opcode = 0x1001,
            _ => r.count = 2,
        }
        service.observe_manager(token, r);
        assert_eq!(service.store.lock().unwrap().phase, Phase::Manager);
    }
    service.observe_manager(7, receipt(false));
    assert_eq!(service.store.lock().unwrap().phase, Phase::Idle);
    service.invalidate(true);
    service.credential_replaced();
    assert_eq!(service.store.lock().unwrap().phase, Phase::Fault);
}

#[test]
fn exact_start_stop_receipts_reject_pending_failed_and_wrong_recipe() {
    for enable in [false, true] {
        assert!(validate_receipt(&receipt(enable), 23, 41, enable).is_ok());
        for change in 0..11 {
            let mut r = receipt(enable);
            match change {
                0 => r.generation = 24,
                1 => r.request_id = 42,
                2 => r.operation = 6,
                3 => r.state = 1,
                4 => r.state = 2,
                5 => r.error = -110,
                6 => r.status = 0x0b,
                7 => r.count += 1,
                8 => r.opcode = 0x1001,
                9 => r.radio_scan = 0,
                _ => r.reserved[0] = 1,
            }
            assert!(validate_receipt(&r, 23, 41, enable).is_err());
        }
        assert!(validate_receipt(&receipt(enable), 0, 41, enable).is_err());
        assert!(validate_receipt(&receipt(enable), 23, 0, enable).is_err());
    }
}

#[test]
fn active_and_pending_owner_watch_budgets_are_per_caller_and_global() {
    let service = Arc::new(Coordinator::default());
    let a = service.owner_slot(":1.1").unwrap();
    let b = service.owner_slot(":1.1").unwrap();
    assert!(service.owner_slot(":1.1").is_err());
    let mut other = Vec::new();
    for id in 2..16 {
        other.push(service.owner_slot(&format!(":1.{id}")).unwrap());
    }
    assert!(service.owner_slot(":1.99").is_err());
    assert!(!service.callers.lock().unwrap().contains_key(":1.99"));
    drop(a);
    let c = service.owner_slot(":1.99").unwrap();
    assert!(service.owner_slot(":1.1").is_err());
    drop(b);
    drop(c);
    drop(other);
    assert!(service.callers.lock().unwrap().is_empty());
    assert_eq!(service.slots.available_permits(), 16);
}

#[tokio::test]
async fn per_session_native_watermark_rejects_queued_old_and_duplicate_reports() {
    let state = state();
    let service = state.lock().await.discovery.clone();
    seed(&service, ":1.1", 1, vec![]);
    service
        .store
        .lock()
        .unwrap()
        .entries
        .get_mut(&1)
        .unwrap()
        .after_sequence = 100;
    for seq in [50, 100, 101, 101, 99, 102] {
        report(&service, seq, 23, &[1], -40);
    }
    let batch = reports(&state, ":1.1", 1, false, until()).await.unwrap();
    assert_eq!(
        batch.reports.iter().map(|r| r.sequence).collect::<Vec<_>>(),
        [101, 102]
    );
    assert_eq!(batch.dropped, 0);
}

#[tokio::test]
async fn real_bus_owner_subscription_loss_and_original_deadline_fail_closed() {
    let bus = crate::event_loop::tests::PrivateBus::start();
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let caller = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let name = caller.unique_name().unwrap().to_string();
    let service = Arc::new(Coordinator::default());
    let owner = Owner::pin(
        server.clone(),
        name.clone(),
        &service,
        service.owner_slot(&name).unwrap(),
        until().instant(),
    )
    .await
    .unwrap();
    seed_owner(&service, owner.clone(), 1, vec![]);
    seed(&service, ":1.999", 2, vec![]);
    let changed = service.changed.notified();
    tokio::pin!(changed);
    changed.as_mut().enable();
    caller.close().await.unwrap();
    tokio::time::timeout(Duration::from_secs(2), changed)
        .await
        .unwrap();
    assert!(!owner.current());
    service.store.lock().unwrap().expire(Instant::now());
    {
        let st = service.store.lock().unwrap();
        assert!(!st.entries.contains_key(&1));
        assert!(st.entries.contains_key(&2));
        assert_eq!(st.phase, Phase::Running);
    }
    let slot = service.owner_slot(":1.99999999").unwrap();
    assert!(
        Owner::pin(server, ":1.99999999".into(), &service, slot, Instant::now())
            .await
            .is_err()
    );
    let mut foreign = until().stamp();
    foreign.time_namespace_inode ^= 1;
    assert!(deadline(slk_contract::deadline_wire(foreign)).is_err());
}

#[tokio::test]
async fn actual_rpc_rejects_nonowner_and_native_failure_without_fake_success() {
    let bus = crate::event_loop::tests::PrivateBus::start();
    let state = state();
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at(
            "/org/sparklink/slk2_g23",
            crate::dbus_iface::AdapterIface::new(state.clone()),
        )
        .unwrap()
        .build()
        .await
        .unwrap();
    let a = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let b = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let pa = zbus::Proxy::new(
        &a,
        "org.sparklink",
        "/org/sparklink/slk2_g23",
        slk_contract::ADAPTER,
    )
    .await
    .unwrap();
    let pb = zbus::Proxy::new(
        &b,
        "org.sparklink",
        "/org/sparklink/slk2_g23",
        slk_contract::ADAPTER,
    )
    .await
    .unwrap();
    let service = state.lock().await.discovery.clone();
    seed(&service, a.unique_name().unwrap().as_str(), 1, vec![]);
    seed(&service, b.unique_name().unwrap().as_str(), 2, vec![]);
    let denied: zbus::Result<bool> = pb
        .call(
            wire::RELEASE,
            &(1u64, slk_contract::deadline_wire(until().stamp())),
        )
        .await;
    assert!(denied.is_err());
    let last: bool = pa
        .call(
            wire::RELEASE,
            &(1u64, slk_contract::deadline_wire(until().stamp())),
        )
        .await
        .unwrap();
    assert!(!last);
    service.invalidate(false);
    service.credential_replaced();
    let open: zbus::Result<u64> = pa
        .call(
            wire::ACQUIRE,
            &(
                vec![1u8],
                -128i16,
                1000u32,
                slk_contract::deadline_wire(until().stamp()),
            ),
        )
        .await;
    assert!(open.unwrap_err().to_string().contains("ioctl"));
    assert!(service.store.lock().unwrap().entries.is_empty());
    assert_eq!(service.store.lock().unwrap().phase, Phase::Idle);
    service.invalidate(true);
    drop(server);
}

#[tokio::test]
async fn expired_read_does_not_consume_and_last_release_never_fabricates_off() {
    let state = state();
    let service = state.lock().await.discovery.clone();
    seed(&service, ":1.1", 1, vec![]);
    report(&service, 1, 23, &[1], -40);
    let expired = Deadline::after(Duration::ZERO).unwrap();
    assert!(reports(&state, ":1.1", 1, false, expired).await.is_err());
    assert_eq!(service.store.lock().unwrap().entries[&1].queue.len(), 1);
    let (cancel, rx) = watch::channel(false);
    let worker = start_worker(&state, rx);
    assert!(release(&state, ":1.1", 1, until()).await.is_err());
    assert_eq!(service.store.lock().unwrap().phase, Phase::Fault);
    assert!(service.store.lock().unwrap().entries.is_empty());
    cancel.send(true).unwrap();
    worker.await.unwrap();
    assert!(service.slots.is_closed());
}
