//! Actual SDK/private-bus codec/cursor/owner tests. Scripted directory hints,
//! no Native controller, real resource retirement, Ready or protocol Complete.
mod support;
use libsparklink::{Client, Deadline, controller_events::ControllerEvent};
use slk_contract::controller_events as wire;
use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicU8, Ordering},
    },
    time::Duration,
};
use tokio::sync::Notify;
#[derive(Default)]
struct Script {
    mode: AtomicU8,
    entered: Notify,
    release: Notify,
    stamps: Mutex<Vec<slk_contract::Deadline>>,
}
struct Manager(Arc<Script>);
#[zbus::interface(name = "org.sparklink.Manager")]
impl Manager {
    fn list_adapters(&self) -> Vec<String> {
        Vec::new()
    }
    async fn get_controller_changes(
        &self,
        after: u64,
        wait: bool,
        stamp: slk_contract::Deadline,
    ) -> zbus::fdo::Result<wire::Batch> {
        if !wait {
            return Ok((1, 0, 0, false, vec![]));
        }
        self.0.stamps.lock().unwrap().push(stamp);
        self.0.entered.notify_one();
        match self.0.mode.load(Ordering::SeqCst) {
            1 if after == 0 => Ok((1, 1, 2, false, vec![(1, 2, 7, 1), (2, 2, 7, 2)])),
            2 if after == 0 => Ok((1, 2, 65, true, vec![])),
            3 if after == 0 => Ok((1, 1, 2, false, vec![(1, 2, 7, 1), (2, 2, 0, 2)])),
            4 if after == 0 => {
                self.0.release.notified().await;
                Ok((1, 1, 1, false, vec![(1, 2, 7, 1)]))
            }
            5 if after == 0 => {
                tokio::time::sleep(Duration::from_millis(2)).await;
                Ok((1, 0, 0, false, vec![]))
            }
            _ => Err(zbus::fdo::Error::InvalidArgs(
                "unmatched finite directory fixture".into(),
            )),
        }
    }
}
fn deadline() -> Deadline {
    Deadline::after(Duration::from_secs(2)).unwrap()
}
async fn fixture(bus: &support::Bus) -> (zbus::Connection, Client, Arc<Script>) {
    let script = Arc::new(Script::default());
    let server = zbus::connection::Builder::address(bus.address.as_str())
        .unwrap()
        .name("org.sparklink")
        .unwrap()
        .serve_at("/org/sparklink", Manager(script.clone()))
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
    (server, client, script)
}
#[tokio::test]
async fn typed_rows_are_bounded_and_pending_rows_need_no_second_rpc() {
    let bus = support::Bus::start();
    let (_server, client, s) = fixture(&bus).await;
    let mut stream = client.controller_events(deadline()).await.unwrap();
    assert_eq!(
        stream.next(deadline()).await.unwrap(),
        ControllerEvent::Snapshot {
            before: 0,
            controllers: vec![]
        }
    );
    s.mode.store(1, Ordering::SeqCst);
    assert!(
        matches!(stream.next(deadline()).await.unwrap(),ControllerEvent::Published{sequence:1,controller}if controller.index==2&&controller.generation==7)
    );
    assert!(matches!(
        stream.next(deadline()).await.unwrap(),
        ControllerEvent::Withdrawn { sequence: 2, .. }
    ));
    assert_eq!(s.stamps.lock().unwrap().len(), 1);
}
#[tokio::test]
async fn gap_and_malformed_reply_are_terminal_not_partial_application() {
    for mode in [2, 3] {
        let bus = support::Bus::start();
        let (_server, client, s) = fixture(&bus).await;
        let mut stream = client.controller_events(deadline()).await.unwrap();
        stream.next(deadline()).await.unwrap();
        s.mode.store(mode, Ordering::SeqCst);
        let result = stream.next(deadline()).await;
        if mode == 2 {
            assert_eq!(
                result.unwrap(),
                ControllerEvent::Gap {
                    after: 0,
                    oldest: 2,
                    current: 65
                }
            );
        } else {
            assert!(result.is_err());
        }
        let calls = s.stamps.lock().unwrap().len();
        assert!(stream.next(deadline()).await.is_err());
        assert_eq!(s.stamps.lock().unwrap().len(), calls);
    }
}
#[tokio::test]
async fn empty_heartbeats_keep_original_deadline_and_timeout_preserves_cursor() {
    let bus = support::Bus::start();
    let (_server, client, s) = fixture(&bus).await;
    let mut stream = client.controller_events(deadline()).await.unwrap();
    stream.next(deadline()).await.unwrap();
    s.mode.store(5, Ordering::SeqCst);
    let original = Deadline::after(Duration::from_millis(80)).unwrap();
    let expected = slk_contract::deadline_wire(original.stamp());
    assert!(
        matches!(stream.next(original).await,Err(libsparklink::ApplicationError::Io(e))if e.raw_os_error()==Some(nix::libc::ETIMEDOUT))
    );
    let stamps = s.stamps.lock().unwrap().clone();
    assert!(!stamps.is_empty());
    assert!(stamps.iter().all(|s| *s == expected));
    s.mode.store(1, Ordering::SeqCst);
    assert!(matches!(
        stream.next(deadline()).await.unwrap(),
        ControllerEvent::Published { sequence: 1, .. }
    ));
}
#[tokio::test]
async fn cancelling_wait_keeps_cursor_and_daemon_loss_discards_pending_snapshot() {
    let bus = support::Bus::start();
    let (server, client, s) = fixture(&bus).await;
    let mut stream = client.controller_events(deadline()).await.unwrap();
    stream.next(deadline()).await.unwrap();
    s.mode.store(4, Ordering::SeqCst);
    {
        let wait = stream.next(deadline());
        tokio::pin!(wait);
        tokio::select! {r=&mut wait=>panic!("fixture unexpectedly completed: {r:?}"),_=s.entered.notified()=>{}}
    }
    s.mode.store(1, Ordering::SeqCst);
    assert!(matches!(
        stream.next(deadline()).await.unwrap(),
        ControllerEvent::Published { sequence: 1, .. }
    ));
    s.release.notify_waiters();
    let mut initial = client.controller_events(deadline()).await.unwrap();
    server.release_name("org.sparklink").await.unwrap();
    let mut loss = client.owner_loss();
    tokio::time::timeout(Duration::from_secs(1), async {
        while !*loss.borrow() {
            loss.changed().await.unwrap();
        }
    })
    .await
    .unwrap();
    server.request_name("org.sparklink").await.unwrap();
    assert!(initial.next(deadline()).await.is_err());
    assert!(stream.next(deadline()).await.is_err());
}
