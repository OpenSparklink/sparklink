//! SDK/bus contract only: synthetic bounded replies, errors and delays. No
//! Native controller, command completion, actual scanning or RF qualification.
use super::*;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU8, AtomicU64, Ordering},
};

type AcquisitionRequest = (Vec<u8>, i16, u32, slk_contract::Deadline);
#[derive(Default)]
struct State {
    mode: AtomicU8,
    reads: AtomicU64,
    releases: AtomicU64,
    requests: Mutex<Vec<AcquisitionRequest>>,
}
struct Broker(Arc<State>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Broker {
    async fn acquire_discovery(
        &self,
        prefix: Vec<u8>,
        minimum_rssi: i16,
        duration_ms: u32,
        deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<u64> {
        self.0
            .requests
            .lock()
            .unwrap()
            .push((prefix, minimum_rssi, duration_ms, deadline));
        if self.0.mode.load(Ordering::SeqCst) == 1 {
            return Err(zbus::fdo::Error::LimitsExceeded("fixture denied".into()));
        }
        Ok(7)
    }
    async fn read_discovery(
        &self,
        session: u64,
        _wait: bool,
        _deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<wire::Batch> {
        let seq = self.0.reads.fetch_add(1, Ordering::SeqCst) + 1;
        let mode = self.0.mode.load(Ordering::SeqCst);
        if mode == 5 {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        if mode == 6 {
            return Err(zbus::fdo::Error::Timeout("fixture bounded read".into()));
        }
        let mut header = vec![0; 23];
        header[2..8].copy_from_slice(&[1, 2, 3, 4, 5, 6]);
        if mode == 7 {
            header[2] ^= 1;
        }
        let report = wire::Report {
            sequence: if mode == 4 { 1 } else { seq },
            kernel_boottime_ns: seq + 100,
            address_type: 0,
            address: vec![1, 2, 3, 4, 5, 6],
            rssi: -42,
            rssi_known: mode != 2,
            header,
            data: vec![0xab, 1],
        };
        Ok(wire::Batch {
            version: 1,
            session,
            generation: if mode == 1 { 24 } else { 23 },
            dropped: 0,
            kernel_lost: 0,
            reports: vec![report; if mode == 3 { wire::CAPACITY + 1 } else { 1 }],
        })
    }
    async fn release_discovery(
        &self,
        _session: u64,
        _deadline: slk_contract::Deadline,
    ) -> zbus::fdo::Result<bool> {
        self.0.releases.fetch_add(1, Ordering::SeqCst);
        if self.0.mode.load(Ordering::SeqCst) == 6 {
            return Err(zbus::fdo::Error::Timeout("fixture uncertain close".into()));
        }
        Ok(false)
    }
}
async fn fixture() -> (
    crate::test_support::Bus,
    zbus::Connection,
    Client,
    Arc<State>,
) {
    let bus = crate::test_support::Bus::start();
    let state = Arc::new(State::default());
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink/slk2_g23", Broker(state.clone()))
        .unwrap()
        .build()
        .await
        .unwrap();
    let caller = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .build()
        .await
        .unwrap();
    let client = Client::from_connection(caller).await.unwrap();
    (bus, server, client, state)
}
fn until() -> Deadline {
    Deadline::after(Duration::from_secs(2)).unwrap()
}
fn id() -> ControllerId {
    ControllerId {
        index: 2,
        generation: 23,
    }
}

#[tokio::test]
async fn public_sdk_keeps_caller_and_original_parameters_after_parent_close() {
    let (_bus, _server, client, state) = fixture().await;
    let original = until();
    let mut discovery = client
        .discover(id(), vec![0xab], -80, 1000, original)
        .await
        .unwrap();
    drop(client);
    let batch = discovery.read(true, until()).await.unwrap();
    assert_eq!(batch.reports.len(), 1);
    assert_eq!(batch.reports[0].data, [0xab, 1]);
    assert_eq!(
        state.requests.lock().unwrap()[0],
        (
            vec![0xab],
            -80,
            1000,
            slk_contract::deadline_wire(original.stamp())
        )
    );
    assert!(!discovery.close(until()).await.unwrap());
    assert_eq!(state.releases.load(Ordering::SeqCst), 1);
    assert!(discovery.read(false, until()).await.is_err());
    assert!(discovery.close(until()).await.is_err());
    drop(discovery);
    tokio::task::yield_now().await;
    assert_eq!(state.releases.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn malformed_replies_do_not_commit_cursor_or_turn_into_success() {
    let (_bus, _server, client, state) = fixture().await;
    let mut discovery = client
        .discover(id(), vec![0xab], -80, 1000, until())
        .await
        .unwrap();
    discovery.read(false, until()).await.unwrap();
    assert_eq!(discovery.sequence, 1);
    for mode in [1, 2, 3, 4, 7] {
        state.mode.store(mode, Ordering::SeqCst);
        assert!(matches!(
            discovery.read(false, until()).await,
            Err(ApplicationError::Identity(_))
        ));
        assert_eq!(discovery.sequence, 1);
    }
    state.mode.store(0, Ordering::SeqCst);
    assert_eq!(
        discovery.read(false, until()).await.unwrap().reports[0].sequence,
        7
    );
    discovery.close(until()).await.unwrap();
}

#[tokio::test]
async fn invalid_requests_expired_deadlines_and_broker_errors_preserve_failures() {
    let (_bus, _server, client, state) = fixture().await;
    assert!(
        client
            .discover(id(), vec![0; 65], -128, 1000, until())
            .await
            .is_err()
    );
    assert!(
        client
            .discover(id(), vec![], -129, 1000, until())
            .await
            .is_err()
    );
    assert!(
        client
            .discover(id(), vec![], -128, 60_001, until())
            .await
            .is_err()
    );
    assert!(
        client
            .discover(
                id(),
                vec![],
                -128,
                1000,
                Deadline::after(Duration::ZERO).unwrap()
            )
            .await
            .is_err()
    );
    assert!(state.requests.lock().unwrap().is_empty());
    state.mode.store(1, Ordering::SeqCst);
    assert!(matches!(
        client.discover(id(), vec![], -128, 1000, until()).await,
        Err(ApplicationError::Bus(_))
    ));
    state.mode.store(0, Ordering::SeqCst);
    let mut d = client
        .discover(id(), vec![0xab], -128, 1000, until())
        .await
        .unwrap();
    state.mode.store(5, Ordering::SeqCst);
    assert!(
        matches!(d.read(true,Deadline::after(Duration::from_millis(10)).unwrap()).await,Err(ApplicationError::Io(e)) if e.raw_os_error()==Some(nix::libc::ETIMEDOUT))
    );
    assert_eq!(d.sequence, 0);
    state.mode.store(6, Ordering::SeqCst);
    assert!(matches!(
        d.read(true, until()).await,
        Err(ApplicationError::Bus(_))
    ));
    assert_eq!(d.sequence, 0);
    assert!(d.close(until()).await.is_err());
    assert!(d.closed);
    assert_eq!(state.releases.load(Ordering::SeqCst), 1);
}
