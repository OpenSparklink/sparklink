//! Actual SDK over a private bus. The data/identity fixtures do not certify
//! hardware, kernel references or RF address modes.
mod support;
use libsparklink::{ApplicationError, Client};
use std::sync::{
    Arc,
    atomic::{AtomicU64, AtomicUsize, Ordering},
};
const BASE: &str = "/org/sparklink/slk2_g7";
const PEER: &str = "/org/sparklink/slk2_g7/peer_t01_010203040506";
#[derive(Default)]
struct State {
    mode: AtomicUsize,
    generation: AtomicU64,
    calls: AtomicUsize,
}
struct Manager;
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        vec![BASE.into()]
    }
}
struct Adapter(Arc<State>);
#[zbus::interface(name = "org.sparklink.Adapter")]
impl Adapter {
    #[zbus(property(emits_changed_signal = "false"))]
    fn generation(&self) -> u64 {
        self.0.generation.load(Ordering::SeqCst)
    }
    fn list_peers(&self) -> Vec<String> {
        match self.0.mode.load(Ordering::SeqCst) {
            1 => vec![PEER.into(), PEER.into()],
            2 => vec![PEER.replace("slk2_g7", "slk3_g8")],
            3 => vec![PEER.replace("t01_", "t06_")],
            4 => vec![PEER.into(); 129],
            _ => vec![PEER.into()],
        }
    }
}
struct Peer(Arc<State>);
#[zbus::interface(name = "org.sparklink.Peer")]
impl Peer {
    fn get_info(&self) -> slk_contract::PeerInfo {
        (7, 1, "01:02:03:04:05:06".into(), false, false, vec![])
    }
    fn get_observation(&self) -> slk_contract::PeerObservation {
        self.0.calls.fetch_add(1, Ordering::SeqCst);
        let mode = self.0.mode.load(Ordering::SeqCst);
        (
            if mode == 5 { 8 } else { 7 },
            if mode == 6 { 0 } else { 1 },
            "01:02:03:04:05:06".into(),
            mode != 7 && mode != 10,
            mode >= 7 && mode != 10,
            if mode == 8 { 127 } else { -40 },
            vec![0; 23],
            vec![1, 2],
            9,
            10,
            0,
        )
    }
}
#[tokio::test]
async fn actual_peer_sdk_refuses_ambiguous_lists_stale_identity_and_fabricated_rssi()
-> anyhow::Result<()> {
    let bus = support::Bus::start();
    let s = Arc::new(State {
        generation: AtomicU64::new(7),
        ..Default::default()
    });
    let a = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .serve_at("/org/sparklink", Manager)?
        .serve_at(BASE, Adapter(s.clone()))?
        .serve_at(PEER, Peer(s.clone()))?
        .build()
        .await?;
    let client = Client::from_connection(
        zbus::connection::Builder::address(bus.address.as_str())?
            .build()
            .await?,
    )
    .await?;
    let controller = client.controller(BASE).await?;
    let peers = controller.peers().await?;
    assert_eq!(peers.len(), 1);
    let peer = &peers[0];
    let o = peer.observation().await?;
    assert!(o.valid && o.rssi.is_none());
    assert_eq!(o.data, [1, 2]);
    let i = peer.info().await?;
    assert!(!i.3 && !i.4);
    for mode in 1..=8 {
        s.mode.store(mode, Ordering::SeqCst);
        let result = if mode <= 4 {
            controller.peers().await.map(|_| ())
        } else {
            peer.observation().await.map(|_| ())
        };
        assert!(
            matches!(result, Err(ApplicationError::Identity(_))),
            "mode {mode}: {result:?}"
        );
    }
    s.mode.store(9, Ordering::SeqCst);
    assert_eq!(peer.observation().await?.rssi, Some(-40));
    s.mode.store(10, Ordering::SeqCst);
    let expired = peer.observation().await?;
    assert!(!expired.valid && expired.rssi.is_none());
    let before = s.calls.load(Ordering::SeqCst);
    s.generation.store(8, Ordering::SeqCst);
    assert!(peer.observation().await.is_err());
    assert_eq!(s.calls.load(Ordering::SeqCst), before);
    s.generation.store(7, Ordering::SeqCst);
    s.mode.store(0, Ordering::SeqCst);
    a.release_name("org.sparklink").await?;
    let _replacement = zbus::connection::Builder::address(bus.address.as_str())?
        .name("org.sparklink")?
        .build()
        .await?;
    assert!(peer.observation().await.is_err());
    assert_eq!(s.calls.load(Ordering::SeqCst), before);
    Ok(())
}
