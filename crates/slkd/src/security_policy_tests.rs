//! Actual policy functions and exported D-Bus interfaces on a real private bus.
//! Canonical Ready/link/lease metadata is a fixture; native ioctl is /dev/null
//! and MUST fail ENOTTY. No kernel locks, USB, crypto or successful install stub.
use super::*;
use crate::{
    bonding::BondingStore,
    config::DaemonConfig,
    connection_object::ConnectionIface,
    event_loop::tests::PrivateBus,
    profile::ProfileRegistry,
    security::SecurityIface,
    state::{AdapterState, NativeManagement},
};
use tokio::sync::mpsc;

type Args = (String, u64, u64, u64, u16, u8, u8, String, String, u64);
const SECURITY: &str = "/org/sparklink/slk0/security";
const LINK: &str = "/org/sparklink/slk0/link";
const AGENT: &str = "/test/agent";

struct Consent {
    yes: bool,
    delay: Duration,
    seen: mpsc::UnboundedSender<Args>,
}
#[zbus::interface(name = "org.sparklink.Agent")]
impl Consent {
    async fn authorize_reference_security(&self, args: Args) -> bool {
        self.seen.send(args).unwrap();
        tokio::time::sleep(self.delay).await;
        self.yes
    }
}
fn reference() -> SleLinkInfo {
    SleLinkInfo {
        lifetime: 13,
        handle: 1,
        role: 0,
        address_type: 0,
        address: [1, 2, 3, 4, 5, 6],
        ..Default::default()
    }
}
fn state() -> SharedState {
    let fd = Arc::new(Adapter::open("/dev/null").unwrap());
    let mut st = AdapterState::new(
        fd.clone(),
        DaemonConfig::default(),
        BondingStore::new(&std::env::temp_dir(), "unused-security-policy-test"),
        ProfileRegistry::new(),
    );
    st.controller.generation = 7;
    st.controller.profile = 1;
    st.controller.flags = slk_protocol::CONTROLLER_READY;
    st.native_control = Some(fd);
    st.native_lease = Some(Arc::new(Mutex::new(NativeManagement {
        token: Some(41),
        accepting: true,
        connection_id: 1,
        initialized_off: [None; 2],
    })));
    let mut table = slk_protocol::SleLinkSnapshot {
        generation: 7,
        version: 1,
        profile: 1,
        flags: 1,
        revision: 13,
        count: 1,
        ..Default::default()
    };
    table.links[0] = reference();
    assert!(table.valid_for(7));
    st.native_links = Some(table);
    Arc::new(Mutex::new(st))
}
async fn client(bus: &PrivateBus) -> zbus::Connection {
    zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap()
}
async fn server(bus: &PrivateBus, state: &SharedState) -> zbus::Connection {
    zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at(SECURITY, SecurityIface::new(state.clone()))
        .unwrap()
        .serve_at(LINK, ConnectionIface::new(state.clone(), 7, reference()))
        .unwrap()
        .build()
        .await
        .unwrap()
}
async fn security(c: &zbus::Connection) -> zbus::Proxy<'_> {
    zbus::Proxy::new(c, "org.sparklink", SECURITY, "org.sparklink.Security")
        .await
        .unwrap()
}
async fn link(c: &zbus::Connection) -> zbus::Proxy<'_> {
    zbus::Proxy::new(c, "org.sparklink", LINK, "org.sparklink.Connection")
        .await
        .unwrap()
}
async fn agent(
    bus: &PrivateBus,
    yes: bool,
    delay_ms: u64,
) -> (zbus::Connection, mpsc::UnboundedReceiver<Args>) {
    let (seen, rx) = mpsc::unbounded_channel();
    let c = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .serve_at(
            AGENT,
            Consent {
                yes,
                delay: Duration::from_millis(delay_ms),
                seen,
            },
        )
        .unwrap()
        .build()
        .await
        .unwrap();
    security(&c)
        .await
        .call::<_, _, ()>(
            "RegisterAgent",
            &(OwnedObjectPath::try_from(AGENT).unwrap(), METHOD),
        )
        .await
        .unwrap();
    (c, rx)
}
async fn allocate_rpc(c: &zbus::Connection, timeout: u32) -> u64 {
    link(c)
        .await
        .call("AllocateReferenceSecurity", &(timeout,))
        .await
        .unwrap()
}
async fn begin_rpc(c: &zbus::Connection, id: u64) {
    link(c)
        .await
        .call::<_, _, ()>("BeginReferenceSecurity", &(id, METHOD))
        .await
        .unwrap()
}
async fn read_rpc(c: &zbus::Connection, id: u64) -> Observation {
    link(c)
        .await
        .call("GetReferenceSecurityResult", &(id,))
        .await
        .unwrap()
}
async fn wait_phase(st: &SharedState, id: u64, phase: u32) -> Observation {
    let registry = registry(st).await;
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if let Some(entry) = registry.lock().await.entries.get(&id)
                && entry.observation.phase == phase
            {
                return entry.observation.clone();
            }
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("request{id} did not reach phase{phase}"))
}
async fn entered(rx: &mut mpsc::UnboundedReceiver<Args>) -> Args {
    tokio::time::timeout(Duration::from_secs(1), rx.recv())
        .await
        .unwrap()
        .unwrap()
}

#[test]
fn actual_success_publication_is_fail_closed_on_clock_failure_or_expiry() {
    assert_eq!(completion_at(None, 100), (8, -nix::libc::EIO));
    assert_eq!(completion_at(Some(99), 100), (4, 0));
    assert_eq!(completion_at(Some(100), 100), (7, -nix::libc::ETIMEDOUT));
    assert_eq!(
        completion_at(Some(u64::MAX), 100),
        (7, -nix::libc::ETIMEDOUT)
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_agent_unknown_method_and_other_owner_are_rejected() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let c = client(&bus).await;
    assert!(
        link(&c)
            .await
            .call::<_, _, u64>("AllocateReferenceSecurity", &(500u32,))
            .await
            .is_err()
    );
    assert!(
        security(&c)
            .await
            .call::<_, _, ()>(
                "RegisterAgent",
                &(OwnedObjectPath::try_from(AGENT).unwrap(), "unknown")
            )
            .await
            .is_err()
    );
    let (_a, _rx) = agent(&bus, false, 0).await;
    let id = allocate_rpc(&c, 500).await;
    assert!(
        link(&c)
            .await
            .call::<_, _, ()>("BeginReferenceSecurity", &(id, "unknown"))
            .await
            .is_err()
    );
    assert_eq!(read_rpc(&c, id).await.phase, 1);
    let other = client(&bus).await;
    for method in ["GetReferenceSecurityResult", "CancelReferenceSecurity"] {
        assert!(
            link(&other)
                .await
                .call_method(method, &(id,))
                .await
                .is_err()
        );
    }
    assert!(
        security(&other)
            .await
            .call::<_, _, ()>(
                "UnregisterAgent",
                &(OwnedObjectPath::try_from(AGENT).unwrap(),)
            )
            .await
            .is_err()
    );
    assert_eq!(read_rpc(&c, id).await.phase, 1);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reject_has_no_native_admission_and_duplicate_begin_is_rejected() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    let deadline = read_rpc(&c, id).await.deadline_monotonic_ns;
    begin_rpc(&c, id).await;
    let args = entered(&mut rx).await;
    assert_eq!(
        (args.1, args.2, args.3, args.4, args.8, args.9),
        (id, 7, 13, 1, METHOD.into(), deadline)
    );
    let out = wait_phase(&st, id, 5).await;
    assert!(!out.agent_approved && !out.native_admitted);
    assert_eq!((out.kernel_state, out.cleanup_error), (0, 0));
    assert!(
        link(&c)
            .await
            .call::<_, _, ()>("BeginReferenceSecurity", &(id, METHOD))
            .await
            .is_err()
    );
    assert!(
        !link(&c)
            .await
            .call::<_, _, bool>("CancelReferenceSecurity", &(id,))
            .await
            .unwrap()
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn approval_reaches_real_ioctl_failure_never_fake_install_success() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, true, 0).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    let out = wait_phase(&st, id, 8).await;
    assert!(out.agent_approved);
    assert!(!out.native_admitted);
    assert_eq!(
        (out.error, out.cleanup_error),
        (-nix::libc::ENOTTY, -nix::libc::ENOTTY)
    );
    assert_eq!(out.kernel_state, 0);
    assert!(
        st.lock()
            .await
            .native_lease
            .as_ref()
            .unwrap()
            .lock()
            .await
            .accepting
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn allocated_expiry_is_active_without_query_or_begin() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, _rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 40).await;
    let out = wait_phase(&st, id, 7).await;
    assert_eq!(out.error, -nix::libc::ETIMEDOUT);
    assert!(!out.native_admitted);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn allocated_caller_death_is_active_without_query() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, _rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 1000).await;
    drop(c);
    let out = wait_phase(&st, id, 9).await;
    assert!(!out.native_admitted);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn approval_after_original_deadline_does_not_submit_or_rewrite() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, true, 150).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 70).await;
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    wait_phase(&st, id, 7).await;
    tokio::time::sleep(Duration::from_millis(180)).await;
    let out = read_rpc(&c, id).await;
    assert_eq!(out.phase, 7);
    assert!(!out.native_admitted);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancel_before_late_approval_is_terminal_without_controller_release() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, true, 150).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    assert!(
        link(&c)
            .await
            .call::<_, _, bool>("CancelReferenceSecurity", &(id,))
            .await
            .unwrap()
    );
    wait_phase(&st, id, 6).await;
    tokio::time::sleep(Duration::from_millis(180)).await;
    let out = read_rpc(&c, id).await;
    assert_eq!(out.phase, 6);
    assert!(!out.native_admitted);
    assert_eq!(
        st.lock()
            .await
            .native_lease
            .as_ref()
            .unwrap()
            .lock()
            .await
            .token,
        Some(41)
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn caller_death_during_callback_never_submits() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, true, 150).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    drop(c);
    let out = wait_phase(&st, id, 9).await;
    assert!(!out.native_admitted);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn agent_death_then_replacement_cannot_revive_old_request() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (a, mut rx) = agent(&bus, true, 150).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    a.close().await.unwrap();
    let out = wait_phase(&st, id, 10).await;
    assert!(!out.native_admitted);
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if registry(&st).await.lock().await.agent.is_none() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let (_replacement, _rx) = agent(&bus, false, 0).await;
    let new_id = allocate_rpc(&c, 500).await;
    assert_ne!(new_id, id);
    assert_eq!(read_rpc(&c, id).await.phase, 10);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stale_identity_and_removed_connection_cannot_admit() {
    let bus = PrivateBus::start();
    let st = state();
    let server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, true, 100).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    assert!(
        observation(&st, c.unique_name().unwrap().as_str(), 8, reference(), id)
            .await
            .is_err()
    );
    let mut old = reference();
    old.lifetime += 1;
    assert!(
        cancel(&st, c.unique_name().unwrap().as_str(), 7, old, id)
            .await
            .is_err()
    );
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    st.lock().await.invalidate_native_connections();
    let out = wait_phase(&st, id, 8).await;
    assert_eq!(out.error, -nix::libc::ESTALE);
    assert!(!out.native_admitted);
    assert!(
        allocate(
            &st,
            &server,
            7,
            reference(),
            c.unique_name().unwrap().as_str(),
            500
        )
        .await
        .is_err()
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn allocation_wait_does_not_renew_original_deadline() {
    let bus = PrivateBus::start();
    let st = state();
    let server = server(&bus, &st).await;
    let (_a, _rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let locked = st.lock().await;
    let call = allocate(
        &st,
        &server,
        7,
        reference(),
        c.unique_name().unwrap().as_str(),
        20,
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(100), call)
            .await
            .unwrap()
            .is_err()
    );
    drop(locked);
    assert!(registry(&st).await.lock().await.entries.is_empty());
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retire_does_not_touch_peer_registry_and_prevents_resurrection() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, _rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    let peer = state();
    retire(&st).await;
    wait_phase(&st, id, 8).await;
    assert!(!registry(&peer).await.lock().await.retired);
    assert!(
        link(&c)
            .await
            .call::<_, _, ()>("BeginReferenceSecurity", &(id, METHOD))
            .await
            .is_err()
    );
    assert!(
        security(&c)
            .await
            .call::<_, _, ()>(
                "RegisterAgent",
                &(OwnedObjectPath::try_from(AGENT).unwrap(), METHOD)
            )
            .await
            .is_err()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn allocated_agent_unregistration_is_active_and_old_epoch_cannot_follow_replacement() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (a, _rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 1000).await;
    security(&a)
        .await
        .call::<_, _, ()>(
            "UnregisterAgent",
            &(OwnedObjectPath::try_from(AGENT).unwrap(),),
        )
        .await
        .unwrap();
    wait_phase(&st, id, 10).await;
    let (_replacement, _rx) = agent(&bus, false, 0).await;
    let new_id = allocate_rpc(&c, 1000).await;
    assert_ne!(id, new_id);
    assert_eq!(read_rpc(&c, id).await.phase, 10);
    let reg = registry(&st).await;
    let guard = reg.lock().await;
    assert_ne!(
        guard.entries[&id].agent.epoch,
        guard.entries[&new_id].agent.epoch
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pending_author_and_retained_record_budgets_are_enforced_by_production_allocate() {
    let bus = PrivateBus::start();
    let st = state();
    let server = server(&bus, &st).await;
    let (_a, _rx) = agent(&bus, false, 0).await;
    let c = client(&bus).await;
    let owner = c.unique_name().unwrap().as_str();
    let refs: Vec<_> = (1..=5)
        .map(|i| SleLinkInfo {
            lifetime: i,
            handle: i as u16,
            ..reference()
        })
        .collect();
    {
        let mut state = st.lock().await;
        let table = state.native_links.as_mut().unwrap();
        table.count = refs.len() as u32;
        for (slot, reference) in table.links.iter_mut().zip(&refs) {
            *slot = *reference;
        }
        assert!(table.valid_for(7));
    }
    let mut ids = Vec::new();
    for reference in &refs[..MAX_AUTHOR_PENDING] {
        ids.push(
            allocate(&st, &server, 7, *reference, owner, 5000)
                .await
                .unwrap(),
        );
    }
    assert!(
        allocate(&st, &server, 7, refs[4], owner, 5000)
            .await
            .is_err()
    );
    for (id, reference) in ids.iter().zip(&refs) {
        assert!(cancel(&st, owner, 7, *reference, *id).await.unwrap());
    }
    for _ in 0..=MAX_RECORDS {
        let id = allocate(&st, &server, 7, refs[0], owner, 5000)
            .await
            .unwrap();
        assert!(cancel(&st, owner, 7, refs[0], id).await.unwrap());
    }
    let reg = registry(&st).await;
    let guard = reg.lock().await;
    assert_eq!(guard.entries.len(), MAX_RECORDS);
    assert!(!guard.entries.contains_key(&ids[0]));
    assert!(
        guard
            .entries
            .values()
            .all(|e| e.observation.phase == 6 && !e.observation.native_admitted)
    );
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn duplicate_begin_while_agent_pending_invokes_only_one_callback() {
    let bus = PrivateBus::start();
    let st = state();
    let _server = server(&bus, &st).await;
    let (_a, mut rx) = agent(&bus, false, 70).await;
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 500).await;
    begin_rpc(&c, id).await;
    entered(&mut rx).await;
    assert!(
        link(&c)
            .await
            .call::<_, _, ()>("BeginReferenceSecurity", &(id, METHOD))
            .await
            .is_err()
    );
    wait_phase(&st, id, 5).await;
    assert!(rx.try_recv().is_err());
}

#[test]
fn numeric_completion_requires_local_confirmation_proof_and_installation() {
    let good = SleSecurityNegotiationResult {
        state: 11,
        flags: 119,
        ..Default::default()
    };
    assert!(Method::Numeric.completed(&good, true));
    assert!(!Method::Numeric.completed(&good, false));
    for bad in [
        SleSecurityNegotiationResult { state: 3, ..good },
        SleSecurityNegotiationResult { state: 9, ..good },
        SleSecurityNegotiationResult { flags: 7, ..good },
        SleSecurityNegotiationResult { flags: 87, ..good },
        SleSecurityNegotiationResult { error: -5, ..good },
        SleSecurityNegotiationResult { status: 1, ..good },
    ] {
        assert!(!Method::Numeric.completed(&bad, true));
    }
    assert!(!Method::NoMitm.completed(&good, true));
    assert!(Method::parse("numeric-comparison").is_err());
}

struct NumericConsent {
    seen: mpsc::UnboundedSender<(Args, u32)>,
}
#[zbus::interface(name = "org.sparklink.Agent")]
impl NumericConsent {
    async fn authorize_reference_security(&self, _args: Args) -> bool {
        true
    }
    async fn confirm_numeric_comparison(&self, args: Args, code: u32) -> bool {
        self.seen.send((args, code)).unwrap();
        false
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn numeric_method_is_frozen_and_native_failure_never_requests_confirmation() {
    let bus = PrivateBus::start();
    let st = state();
    let server = server(&bus, &st).await;
    let (seen, mut rx) = mpsc::unbounded_channel();
    let a = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .serve_at(AGENT, NumericConsent { seen })
        .unwrap()
        .build()
        .await
        .unwrap();
    security(&a)
        .await
        .call::<_, _, ()>(
            "RegisterAgent",
            &(OwnedObjectPath::try_from(AGENT).unwrap(), NUMERIC_METHOD),
        )
        .await
        .unwrap();
    let c = client(&bus).await;
    let id = allocate_rpc(&c, 1000).await;
    assert!(
        link(&c)
            .await
            .call::<_, _, ()>("BeginReferenceSecurity", &(id, METHOD))
            .await
            .is_err()
    );
    assert_eq!(read_rpc(&c, id).await.phase, 1);
    link(&c)
        .await
        .call::<_, _, ()>("BeginReferenceSecurity", &(id, NUMERIC_METHOD))
        .await
        .unwrap();
    let out = wait_phase(&st, id, 8).await;
    assert!(out.agent_approved);
    assert!(!out.native_admitted);
    assert_eq!(out.error, -nix::libc::ENOTTY);
    assert!(rx.try_recv().is_err()); // /dev/null never invents a native prompt.
    let reg = registry(&st).await;
    let entry = reg.lock().await.entries.get(&id).unwrap().clone();
    let args = (
        LINK.to_owned(),
        id,
        7,
        13,
        1,
        0,
        0,
        "01:02:03:04:05:06".to_owned(),
        NUMERIC_METHOD.to_owned(),
        out.deadline_monotonic_ns,
    );
    // Direct production callback transport only; not the native workflow.
    assert!(
        !agent_decision(&server, &entry, &args, Some(0))
            .await
            .unwrap()
    );
    let got = rx.recv().await.unwrap();
    assert_eq!(got, (args.clone(), 0));
    assert!(
        agent_decision(&server, &entry, &args, Some(1_000_000))
            .await
            .is_err()
    );
    assert!(rx.try_recv().is_err());
}
