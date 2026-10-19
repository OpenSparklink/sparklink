//! Actual SDK/private-bus serialization and delivery checks. The finite broker
//! returns explicit receipt fixtures,not Native/SSAP firmware or RF success.
use super::*;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU8, AtomicU64, AtomicUsize, Ordering},
};
const BASE: &str = "/org/sparklink/slk2_g7";
const PATH: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
#[derive(Default)]
struct State {
    mode: AtomicU8,
    sequence: AtomicU64,
    closes: AtomicUsize,
    reads: AtomicUsize,
    info: Mutex<Option<Info>>,
    stamps: Mutex<Vec<contract::Deadline>>,
    entered: tokio::sync::Notify,
    resume: tokio::sync::Notify,
}
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into()]
    }
}
struct Adapter;
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        7
    }
}
struct Broker(Arc<State>);
#[zbus::interface(name = "org.sparklink.Connection")]
impl Broker {
    fn get_info(&self) -> contract::ConnectionInfo {
        (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true)
    }
    fn subscribe_ssap_updates(
        &self,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        deadline: contract::Deadline,
    ) -> zbus::fdo::Result<Info> {
        let original = Deadline::from_stamp(contract::deadline_stamp(deadline)).unwrap();
        self.0.stamps.lock().unwrap().push(deadline);
        if self
            .0
            .info
            .lock()
            .unwrap()
            .as_ref()
            .is_some_and(|v| v.state != wire::CLOSED)
        {
            return Err(zbus::fdo::Error::LimitsExceeded(
                "explicit occupied fixture lease".into(),
            ));
        }
        let mut info = Info {
            version: 1,
            controller: 2,
            generation: 7,
            lifetime: 11,
            handle: 3,
            security_epoch: 13,
            token: 17,
            expires_ns: original.stamp().monotonic_ns + u64::from(duration_ms) * 1_000_000,
            handles,
            modes,
            state: wire::ACTIVE,
            capacity: 16,
        };
        *self.0.info.lock().unwrap() = Some(info.clone());
        if self.0.mode.load(Ordering::SeqCst) == 18 {
            info.state = wire::STARTING;
        }
        Ok(info)
    }
    async fn read_ssap_updates(
        &self,
        token: u64,
        _wait: bool,
        deadline: contract::Deadline,
    ) -> zbus::fdo::Result<Batch> {
        Deadline::from_stamp(contract::deadline_stamp(deadline)).unwrap();
        self.0.stamps.lock().unwrap().push(deadline);
        self.0.reads.fetch_add(1, Ordering::SeqCst);
        assert_eq!(token, 17);
        let mode = self.0.mode.load(Ordering::SeqCst);
        if mode == 17 {
            self.0.entered.notify_one();
            self.0.resume.notified().await;
        }
        let sequence = self.0.sequence.load(Ordering::SeqCst);
        let mut b = Batch {
            info: self.0.info.lock().unwrap().clone().unwrap(),
            last_sequence: sequence,
            dropped_notifications: 0,
            refused_indications: 0,
            discarded_on_close: 0,
            flags: 0,
            reason: 0,
            packets: vec![Packet {
                sequence,
                security_epoch: 13,
                security_level: 2,
                indication: true,
                pdu: vec![16, 3, 17, 0, 1, 0, 0xab],
            }],
        };
        match mode {
            1 => b.info.generation += 1,
            2 => b.info.security_epoch += 1,
            3 => b.packets[0].pdu = vec![1],
            4 => b.packets[0].pdu[2] = 19,
            5 => b.packets.resize(17, b.packets[0].clone()),
            6 => b.flags = wire::CLEANUP_CONFIRMED,
            7 => b.packets[0].sequence = 1,
            8 => b.packets[0].security_epoch += 1,
            9 => b.packets[0].pdu.resize(2049, 0),
            10 => {
                b.packets[0].indication = false;
                b.packets[0].pdu[0] = 15;
            }
            11 => b.info.expires_ns += 1,
            12 => b.packets[0].security_level = 3,
            13 => b.packets[0].sequence = sequence + 1,
            14 => b.dropped_notifications = u64::MAX,
            19 => {
                b.info.state = wire::CLOSING;
                b.reason = wire::EXPIRED;
                b.packets.clear();
            }
            _ => {}
        }
        Ok(b)
    }
    fn renew_ssap_subscription(
        &self,
        token: u64,
        duration_ms: u32,
        deadline: contract::Deadline,
    ) -> zbus::fdo::Result<Info> {
        assert_eq!(token, 17);
        self.0.stamps.lock().unwrap().push(deadline);
        let original = Deadline::from_stamp(contract::deadline_stamp(deadline)).unwrap();
        let mut info = self.0.info.lock().unwrap();
        let info = info.as_mut().unwrap();
        info.expires_ns = original.stamp().monotonic_ns + u64::from(duration_ms) * 1_000_000;
        let mut result = info.clone();
        if self.0.mode.load(Ordering::SeqCst) == 16 {
            result.token += 1;
        }
        Ok(result)
    }
    fn close_ssap_subscription(
        &self,
        token: u64,
        deadline: contract::Deadline,
    ) -> zbus::fdo::Result<Batch> {
        assert_eq!(token, 17);
        self.0.stamps.lock().unwrap().push(deadline);
        self.0.closes.fetch_add(1, Ordering::SeqCst);
        let mut stored = self.0.info.lock().unwrap();
        let mut info = stored.clone().unwrap();
        info.state = wire::CLOSED;
        if self.0.mode.load(Ordering::SeqCst) != 15 {
            *stored = Some(info.clone());
        }
        Ok(Batch {
            info,
            last_sequence: self.0.sequence.load(Ordering::SeqCst),
            dropped_notifications: 0,
            refused_indications: 0,
            discarded_on_close: 0,
            flags: if self.0.mode.load(Ordering::SeqCst) == 15 {
                0
            } else {
                wire::CLEANUP_CONFIRMED
            },
            reason: wire::RELEASED,
            packets: vec![],
        })
    }
}
fn until() -> Deadline {
    Deadline::after(Duration::from_secs(2)).unwrap()
}
async fn fixture() -> (
    crate::test_support::Bus,
    zbus::Connection,
    ApplicationConnection,
    Arc<State>,
) {
    let bus = crate::test_support::Bus::start();
    let state = Arc::new(State::default());
    state.sequence.store(1, Ordering::SeqCst);
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name(contract::SERVICE)
        .unwrap()
        .serve_at(contract::MANAGER_PATH, Manager)
        .unwrap()
        .serve_at(BASE, Adapter)
        .unwrap()
        .serve_at(PATH, Broker(state.clone()))
        .unwrap()
        .build()
        .await
        .unwrap();
    let caller = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let client = crate::Client::from_connection(caller).await.unwrap();
    let link = client.connection(BASE, PATH).await.unwrap();
    (bus, server, link, state)
}

#[tokio::test]
async fn lease_retains_parent_caller_and_forwards_original_stamps_without_retries() {
    let (_bus, _server, link, state) = fixture().await;
    let original = until();
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, original)
        .await
        .unwrap();
    assert_eq!(
        state.stamps.lock().unwrap()[0],
        contract::deadline_wire(original.stamp())
    );
    drop(link);
    let first = sub.read(true, until()).await.unwrap();
    assert_eq!(first.packets[0].pdu, [16, 3, 17, 0, 1, 0, 0xab]);
    assert_eq!(sub.sequence, 1);
    let renewal = until();
    let info = sub.renew(2000, renewal).await.unwrap();
    assert_eq!(
        info.expires_ns,
        renewal.stamp().monotonic_ns + 2_000_000_000
    );
    assert_eq!(
        state.stamps.lock().unwrap()[2],
        contract::deadline_wire(renewal.stamp())
    );
    let closed = sub.close(until()).await.unwrap();
    assert_eq!(closed.flags, wire::CLEANUP_CONFIRMED);
    assert!(sub.read(false, until()).await.is_err());
    assert!(sub.renew(1000, until()).await.is_err());
    assert!(sub.close(until()).await.is_err());
    drop(sub);
    tokio::task::yield_now().await;
    assert_eq!(state.reads.load(Ordering::SeqCst), 1);
    assert_eq!(state.closes.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn malformed_batches_never_commit_identity_counters_or_cursor() {
    let (_bus, _server, link, state) = fixture().await;
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, until())
        .await
        .unwrap();
    sub.read(false, until()).await.unwrap();
    state.sequence.store(2, Ordering::SeqCst);
    let expected = sub.info.clone();
    for mode in 1..=14 {
        state.mode.store(mode, Ordering::SeqCst);
        assert!(
            matches!(
                sub.read(false, until()).await,
                Err(ApplicationError::Identity(_))
            ),
            "mode{mode}"
        );
        assert_eq!(sub.sequence, 1);
        assert_eq!(sub.dropped, 0);
        assert_eq!(sub.info, expected);
    }
    state.mode.store(0, Ordering::SeqCst);
    assert_eq!(sub.read(false, until()).await.unwrap().last_sequence, 2);
    sub.close(until()).await.unwrap();
}

#[tokio::test]
async fn bad_acquisition_and_unconfirmed_cleanup_do_not_become_success_or_reopen() {
    {
        let (_bus, _server, link, state) = fixture().await;
        state.mode.store(18, Ordering::SeqCst);
        assert!(matches!(
            link.ssap().subscribe(vec![17], 2, 1000, until()).await,
            Err(ApplicationError::Identity(_))
        ));
    }
    let (_bus, _server, link, state) = fixture().await;
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, until())
        .await
        .unwrap();
    state.mode.store(15, Ordering::SeqCst);
    assert!(matches!(
        sub.close(until()).await,
        Err(ApplicationError::Identity(_))
    ));
    assert!(sub.is_closed());
    assert!(sub.read(false, until()).await.is_err());
    assert!(sub.close(until()).await.is_err());
    drop(sub);
    tokio::task::yield_now().await;
    assert_eq!(state.closes.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn closing_observation_can_await_cleanup_and_uncertain_renewal_does_not_update_scope() {
    let (_bus, _server, link, state) = fixture().await;
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, until())
        .await
        .unwrap();
    let original_info = sub.info.clone();
    state.mode.store(16, Ordering::SeqCst);
    assert!(sub.renew(2000, until()).await.is_err());
    assert_eq!(sub.info, original_info);
    // Cleanup can report actual changed expiry after the uncertain renewal,
    // without granting new read/admission authority from that observation.
    sub.close(until()).await.unwrap();
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, until())
        .await
        .unwrap();
    state.mode.store(19, Ordering::SeqCst);
    assert_eq!(
        sub.read(true, until()).await.unwrap().info.state,
        wire::CLOSING
    );
    assert!(sub.read(false, until()).await.is_err());
    assert!(sub.renew(1000, until()).await.is_err());
    assert_eq!(
        sub.close(until()).await.unwrap().flags,
        wire::CLEANUP_CONFIRMED
    );
}

#[tokio::test]
async fn original_read_timeout_does_not_release_or_renew_the_lease() {
    let (_bus, _server, link, state) = fixture().await;
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, until())
        .await
        .unwrap();
    let info = sub.info.clone();
    state.mode.store(17, Ordering::SeqCst);
    let original = Deadline::after(Duration::from_millis(50)).unwrap();
    let call = sub.read(true, original);
    let wait = async {
        state.entered.notified().await;
    };
    let (result, ()) =
        tokio::time::timeout(Duration::from_secs(2), async { tokio::join!(call, wait) })
            .await
            .unwrap();
    assert!(
        matches!(result,Err(ApplicationError::Io(ref e)) if e.raw_os_error()==Some(nix::libc::ETIMEDOUT))
    );
    assert_eq!(sub.info, info);
    assert_eq!(state.closes.load(Ordering::SeqCst), 0);
    state.resume.notify_one();
    state.mode.store(0, Ordering::SeqCst);
    sub.close(until()).await.unwrap();
}

#[tokio::test]
async fn invalid_requests_are_rejected_before_any_broker_operation() {
    let (_bus, _server, link, state) = fixture().await;
    for (handles, modes, duration) in [
        (vec![], 2, 1000),
        (vec![0], 2, 1000),
        (vec![17, 17], 2, 1000),
        (vec![17; 33], 2, 1000),
        (vec![17], 0, 1000),
        (vec![17], 4, 1000),
        (vec![17], 2, 249),
        (vec![17], 2, 60001),
    ] {
        assert!(matches!(
            link.ssap()
                .subscribe(handles, modes, duration, until())
                .await,
            Err(ApplicationError::Invalid(_))
        ));
    }
    assert!(state.stamps.lock().unwrap().is_empty());
    assert!(state.info.lock().unwrap().is_none());
}

#[tokio::test]
async fn observed_daemon_scope_loss_never_revives_subscription_on_same_owner_reacquisition() {
    let (_bus, server, link, state) = fixture().await;
    let mut sub = link
        .ssap()
        .subscribe(vec![17], 2, 1000, until())
        .await
        .unwrap();
    let mut loss = sub.link.client.owner_loss();
    server.release_name(contract::SERVICE).await.unwrap();
    tokio::time::timeout(Duration::from_secs(2), loss.changed())
        .await
        .unwrap()
        .unwrap();
    server.request_name(contract::SERVICE).await.unwrap();
    assert!(matches!(
        sub.read(false, until()).await,
        Err(ApplicationError::Identity(_))
    ));
    assert!(matches!(
        sub.renew(1000, until()).await,
        Err(ApplicationError::Identity(_))
    ));
    assert_eq!(state.reads.load(Ordering::SeqCst), 0);
}
