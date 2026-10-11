use std::sync::{Arc, Mutex, mpsc};
use std::time::Duration;

use tokio::sync::oneshot;
use tokio::time::timeout;

use super::*;
use crate::profile::{CharacteristicDef, Profile, ProfileError};

type Calls = Arc<Mutex<Vec<(u16, bool)>>>;

pub(crate) struct CallbackProbe {
    pub entered: oneshot::Receiver<()>,
    pub calls: Calls,
    release: Option<mpsc::Sender<()>>,
}

impl CallbackProbe {
    pub fn release(&mut self) {
        self.release.take().unwrap().send(()).unwrap();
    }
}

struct TestProfile {
    gate: Option<(oneshot::Sender<()>, Mutex<mpsc::Receiver<()>>)>,
    calls: Calls,
    panic_on_connect: bool,
}

impl Profile for TestProfile {
    fn name(&self) -> &str {
        "callback-regression"
    }
    fn uuid16(&self) -> u16 {
        0xFFFF
    }
    fn characteristics(&self) -> Vec<CharacteristicDef> {
        Vec::new()
    }
    fn on_read(&self, _: u16) -> Result<Vec<u8>, ProfileError> {
        Err(ProfileError::NotSupported)
    }
    fn on_write(&mut self, _: u16, _: &[u8]) -> Result<(), ProfileError> {
        Err(ProfileError::NotSupported)
    }
    fn on_connect(&mut self, handle: u16) {
        assert!(!self.panic_on_connect, "injected callback panic");
        if let Some((entered, release)) = self.gate.take() {
            let _ = entered.send(());
            release
                .into_inner()
                .unwrap()
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
        }
        self.calls.lock().unwrap().push((handle, true));
    }
    fn on_disconnect(&mut self, handle: u16) {
        self.calls.lock().unwrap().push((handle, false));
    }
}

pub(crate) fn blocking_profile() -> (Box<dyn Profile>, CallbackProbe) {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let (entered, entered_rx) = oneshot::channel();
    let (release, release_rx) = mpsc::channel();
    (
        Box::new(TestProfile {
            gate: Some((entered, Mutex::new(release_rx))),
            calls: calls.clone(),
            panic_on_connect: false,
        }),
        CallbackProbe {
            entered: entered_rx,
            calls,
            release: Some(release),
        },
    )
}

#[tokio::test]
async fn cancelled_callback_finishes_before_disconnect() {
    let (profile, mut probe) = blocking_profile();
    let mut registry = ProfileRegistry::new();
    registry.add(profile);
    let service = ProfileService::new(registry);
    let writer_service = service.clone();
    let connected = tokio::spawn(async move { writer_service.connection_changed(7, true).await });
    (&mut probe.entered).await.unwrap();
    connected.abort();
    assert!(connected.await.unwrap_err().is_cancelled());
    let reader_service = service.clone();
    let mut disconnected =
        tokio::spawn(async move { reader_service.connection_changed(7, false).await });
    assert!(
        timeout(Duration::from_millis(50), &mut disconnected)
            .await
            .is_err()
    );
    assert!(probe.calls.lock().unwrap().is_empty());
    probe.release();
    timeout(Duration::from_secs(2), disconnected)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(*probe.calls.lock().unwrap(), [(7, true), (7, false)]);
    service.shutdown().await;
}

#[tokio::test]
async fn shutdown_drains_callback_and_rejects_all_clones() {
    let (profile, mut probe) = blocking_profile();
    let mut registry = ProfileRegistry::new();
    registry.add(profile);
    let service = ProfileService::new(registry);
    let writer_service = service.clone();
    let connected = tokio::spawn(async move { writer_service.connection_changed(8, true).await });
    (&mut probe.entered).await.unwrap();
    let closing_service = service.clone();
    let mut closing = tokio::spawn(async move { closing_service.shutdown().await });
    assert!(
        timeout(Duration::from_millis(50), &mut closing)
            .await
            .is_err()
    );
    probe.release();
    timeout(Duration::from_secs(2), closing)
        .await
        .unwrap()
        .unwrap();
    connected.await.unwrap().unwrap();
    assert_eq!(*probe.calls.lock().unwrap(), [(8, true)]);
    assert!(matches!(
        service.connection_changed(8, false).await,
        Err(ProfileRuntimeError::Closed)
    ));
}

#[tokio::test]
async fn callback_panic_closes_service_before_another_callback() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let mut registry = ProfileRegistry::new();
    registry.add(Box::new(TestProfile {
        gate: None,
        calls: calls.clone(),
        panic_on_connect: true,
    }));
    let service = ProfileService::new(registry);
    match service.connection_changed(9, true).await {
        Err(ProfileRuntimeError::Task(error)) => assert!(error.is_panic()),
        result => panic!("expected callback task panic: {result:?}"),
    }
    assert!(matches!(
        service.connection_changed(9, false).await,
        Err(ProfileRuntimeError::Closed)
    ));
    assert!(calls.lock().unwrap().is_empty());
    service.shutdown().await;
}
