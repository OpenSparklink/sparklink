//! One call-owned receive transaction inside the existing physical SSAP actor.
//! This is phase/ownership bookkeeping, not another wire loop or codec. The
//! actor's sole ClientRequest performs every real read/write and keeps debt.
use super::ssap_engine::{ClientFailure, Incoming, IncomingWait};
use std::time::Duration;
use tokio::{sync::oneshot, time::Instant};

#[derive(Clone, Copy)]
enum Phase {
    Baseline(usize),
    Enable(usize),
    Waiting,
    Disable,
}
pub(crate) enum Event {
    Cancelled,
    Wire(Result<Vec<u8>, ClientFailure>),
    Data(Result<Incoming, String>),
}
pub(crate) struct ReceiveTransaction {
    handles: Vec<u16>,
    modes: u8,
    original: Instant,
    cleanup: Option<Instant>,
    phase: Phase,
    // Mark before a possibly physical write. Cancellation cannot forget it.
    possibly_enabled: Vec<u16>,
    failure: Option<String>,
    payload: Option<Incoming>,
    reply: oneshot::Sender<Result<Incoming, String>>,
    wire: Option<oneshot::Receiver<Result<Vec<u8>, ClientFailure>>>,
    data_send: Option<oneshot::Sender<Result<Incoming, String>>>,
    data: Option<oneshot::Receiver<Result<Incoming, String>>>,
}
impl ReceiveTransaction {
    pub(crate) fn new(
        handles: Vec<u16>,
        modes: u8,
        original: Instant,
        reply: oneshot::Sender<Result<Incoming, String>>,
    ) -> Self {
        let (data_send, data) = oneshot::channel();
        Self {
            handles,
            modes,
            original,
            cleanup: None,
            phase: Phase::Baseline(0),
            possibly_enabled: vec![],
            failure: None,
            payload: None,
            reply,
            wire: None,
            data_send: Some(data_send),
            data: Some(data),
        }
    }
    fn closing(&self) -> bool {
        self.failure.is_some() || self.payload.is_some()
    }
    pub(crate) fn wake_deadline(&self) -> Instant {
        self.cleanup.unwrap_or(self.original)
    }
    pub(crate) fn maintain(
        &mut self,
        waiter: &mut Option<IncomingWait>,
        now: Instant,
    ) -> Result<(), String> {
        if self.reply.is_closed() || now >= self.original {
            self.failure
                .get_or_insert_with(|| "receive caller cancelled/original deadline".into());
        }
        if self.closing() {
            let cleanup = *self.cleanup.get_or_insert(now + Duration::from_secs(5));
            // This bound starts once; it never renews the author's deadline.
            if now >= cleanup {
                return Err(
                    "unconfirmed client-configuration cleanup deadline; retire SSAP actor".into(),
                );
            }
            waiter.take();
            self.data_send.take();
            self.data.take();
            if !matches!(self.phase, Phase::Disable)
                && let Some(wire) = &mut self.wire
            {
                wire.close();
            }
        }
        Ok(())
    }
    /// No overlapping transaction may clear a pre-existing remote setting.
    /// The sole actor serializes all client value requests while this is held.
    pub(crate) fn next(
        &mut self,
        waiter: &mut Option<IncomingWait>,
    ) -> Option<(u16, Option<[u8; 2]>, Instant)> {
        if self.wire.is_some() {
            return None;
        }
        if self.closing() {
            self.phase = Phase::Disable;
        }
        match self.phase {
            Phase::Baseline(index) => Some((self.handles[index], None, self.original)),
            Phase::Enable(index) => {
                if self.data_send.is_some() {
                    *waiter = Some(IncomingWait {
                        handles: self.handles.clone(),
                        modes: self.modes,
                        deadline: self.original,
                        reply: self.data_send.take().expect("install receive queue once"),
                    });
                }
                Some((self.handles[index], Some([self.modes, 0]), self.original))
            }
            Phase::Waiting => None,
            Phase::Disable => self.possibly_enabled.first().map(|handle| {
                (
                    *handle,
                    Some([0, 0]),
                    self.cleanup.expect("cleanup started"),
                )
            }),
        }
    }
    pub(crate) fn submitted(
        &mut self,
        handle: u16,
        receiver: oneshot::Receiver<Result<Vec<u8>, ClientFailure>>,
        admitted: bool,
    ) {
        if admitted && matches!(self.phase, Phase::Enable(_)) {
            self.possibly_enabled.push(handle);
        }
        self.wire = Some(receiver);
    }
    pub(crate) fn finished(&self) -> bool {
        self.closing() && self.possibly_enabled.is_empty() && self.wire.is_none()
    }
    pub(crate) fn finish(self) {
        let result = match (self.failure, self.payload) {
            (Some(error), _) => Err(error),
            (None, Some(packet)) if Instant::now() < self.original => Ok(packet),
            _ => Err("receive original deadline/no payload".into()),
        };
        let _ = self.reply.send(result);
    }
    pub(crate) fn apply(&mut self, event: Event) -> Result<(), String> {
        match event {
            Event::Cancelled => {
                self.failure
                    .get_or_insert_with(|| "receive caller cancelled".into());
            }
            Event::Data(result) => {
                self.data.take();
                match result {
                    Ok(packet) => self.payload = Some(packet),
                    Err(error) => {
                        self.failure.get_or_insert(error);
                    }
                }
            }
            Event::Wire(result) => {
                self.wire.take();
                match self.phase {
                    Phase::Disable => {
                        if let Err(ClientFailure::WriteError { handle, error: 4 }) = &result
                            && self.possibly_enabled.first() == Some(handle)
                        {
                            // A matching,decoded response closes this physical
                            // request with failure: the remote property is no
                            // longer available. Not a verified disable or an
                            // application delivery;other handles remain owed.
                            self.failure.get_or_insert_with(|| {
                                "remote client configuration property unavailable".into()
                            });
                            self.possibly_enabled.remove(0);
                            return Ok(());
                        }
                        if result.as_deref() != Ok(&[0, 0][..]) {
                            return Err(
                                "client configuration disable not verified; retire SSAP actor"
                                    .into(),
                            );
                        }
                        self.possibly_enabled.remove(0);
                    }
                    Phase::Baseline(index) => {
                        if self.closing() {
                            return Ok(());
                        }
                        if result.as_deref() != Ok(&[0, 0][..]) {
                            self.failure = Some(
                                "remote client configuration busy/unavailable; not overwritten"
                                    .into(),
                            );
                        } else {
                            self.phase = if index + 1 == self.handles.len() {
                                Phase::Enable(0)
                            } else {
                                Phase::Baseline(index + 1)
                            };
                        }
                    }
                    Phase::Enable(index) => {
                        if self.closing() {
                            return Ok(());
                        }
                        if result.as_deref() != Ok(&[self.modes, 0][..]) {
                            self.failure = Some("client configuration enable not verified".into());
                        } else {
                            self.phase = if index + 1 == self.handles.len() {
                                Phase::Waiting
                            } else {
                                Phase::Enable(index + 1)
                            };
                        }
                    }
                    Phase::Waiting => return Err("unexpected receive transaction reply".into()),
                }
            }
        }
        Ok(())
    }
    pub(crate) async fn event(&mut self) -> Event {
        let cancel = !self.closing();
        let wire = self.wire.is_some();
        let data = self.data.is_some();
        if !cancel && !wire && !data {
            return std::future::pending().await;
        }
        tokio::select! {biased;
            _=self.reply.closed(),if cancel=>Event::Cancelled,
            value=async {self.wire.as_mut().expect("guarded wire reply").await},if wire=>
                Event::Wire(value.unwrap_or_else(|_|Err("receive physical request ended/cancelled".into()))),
            value=async {self.data.as_mut().expect("guarded receive queue").await},if data=>
                Event::Data(value.unwrap_or_else(|_|Err("receive queue closed".into()))),
        }
    }
}

#[cfg(test)]
mod tests {
    //! Pure production phase bookkeeping with explicit reply fixtures. This
    //! does not supply successful Native ioctls,security,credit or a second peer.
    use super::*;
    async fn wire(t: &mut ReceiveTransaction, result: Result<Vec<u8>, ClientFailure>, handle: u16) {
        let (tx, rx) = oneshot::channel();
        t.submitted(handle, rx, true);
        tx.send(result).unwrap();
        let e = t.event().await;
        t.apply(e).unwrap();
    }
    #[tokio::test]
    async fn typed_missing_property_fails_call_but_preserves_other_cleanup_and_deadline() {
        let original = Instant::now() + Duration::from_secs(3);
        let (reply, result) = oneshot::channel();
        let mut t = ReceiveTransaction::new(vec![17, 18], 2, original, reply);
        let mut waiter = None;
        for handle in [17, 18] {
            assert_eq!(t.next(&mut waiter), Some((handle, None, original)));
            wire(&mut t, Ok(vec![0, 0]), handle).await;
        }
        for handle in [17, 18] {
            assert_eq!(t.next(&mut waiter), Some((handle, Some([2, 0]), original)));
            wire(&mut t, Ok(vec![2, 0]), handle).await;
        }
        waiter
            .take()
            .unwrap()
            .reply
            .send(Ok((true, vec![16, 3, 17, 0, 0, 0])))
            .unwrap();
        let data = t.event().await;
        t.apply(data).unwrap();
        t.maintain(&mut waiter, Instant::now()).unwrap();
        let fixed = t.wake_deadline();
        assert_eq!(t.next(&mut waiter), Some((17, Some([0, 0]), fixed)));
        wire(
            &mut t,
            Err(ClientFailure::WriteError {
                handle: 17,
                error: 4,
            }),
            17,
        )
        .await;
        assert_eq!(t.possibly_enabled, vec![18]);
        assert!(!t.finished());
        assert_eq!(t.wake_deadline(), fixed);
        assert_eq!(t.next(&mut waiter), Some((18, Some([0, 0]), fixed)));
        wire(&mut t, Ok(vec![0, 0]), 18).await;
        assert!(t.finished());
        t.finish();
        // The internally received value is never upgraded to application
        // success when its original remote configuration disappeared.
        assert_eq!(
            result.await.unwrap(),
            Err("remote client configuration property unavailable".into())
        );
    }

    #[test]
    fn opaque_similar_error_wrong_handle_and_other_peer_error_still_retire() {
        for error in [
            ClientFailure::Message("peer write error 4".into()),
            ClientFailure::WriteError {
                handle: 18,
                error: 4,
            },
            ClientFailure::WriteError {
                handle: 17,
                error: 9,
            },
        ] {
            // Explicit phase fixture;the full transition above uses actual
            // production admission/event methods. No Native or USB fixture.
            let (reply, _result) = oneshot::channel();
            let mut t = ReceiveTransaction::new(
                vec![17],
                2,
                Instant::now() + Duration::from_secs(3),
                reply,
            );
            t.phase = Phase::Disable;
            t.possibly_enabled.push(17);
            t.cleanup = Some(Instant::now() + Duration::from_secs(5));
            let fixed = t.wake_deadline();
            assert!(t.apply(Event::Wire(Err(error))).is_err());
            assert_eq!(t.possibly_enabled, vec![17]);
            assert_eq!(t.wake_deadline(), fixed);
            assert!(!t.finished());
        }
    }

    #[tokio::test]
    async fn cancelled_author_does_not_turn_known_absence_into_late_success() {
        let (reply, mut result) = oneshot::channel();
        let mut t =
            ReceiveTransaction::new(vec![17], 2, Instant::now() + Duration::from_secs(3), reply);
        t.possibly_enabled.push(17);
        result.close();
        let mut waiter = None;
        t.maintain(&mut waiter, Instant::now()).unwrap();
        let fixed = t.wake_deadline();
        assert_eq!(t.next(&mut waiter), Some((17, Some([0, 0]), fixed)));
        t.apply(Event::Wire(Err(ClientFailure::WriteError {
            handle: 17,
            error: 4,
        })))
        .unwrap();
        assert_eq!(t.wake_deadline(), fixed);
        assert!(t.finished());
        t.finish();
        assert_eq!(result.try_recv(), Err(oneshot::error::TryRecvError::Closed));
    }

    #[tokio::test]
    async fn transaction_checks_baselines_enables_once_and_returns_only_after_verified_disable() {
        let original = Instant::now() + Duration::from_secs(3);
        let (reply, mut result) = oneshot::channel();
        let mut t = ReceiveTransaction::new(vec![17, 18], 3, original, reply);
        let mut waiter = None;
        assert_eq!(t.next(&mut waiter), Some((17, None, original)));
        wire(&mut t, Ok(vec![0, 0]), 17).await;
        assert_eq!(t.next(&mut waiter), Some((18, None, original)));
        wire(&mut t, Ok(vec![0, 0]), 18).await;
        assert_eq!(t.next(&mut waiter), Some((17, Some([3, 0]), original)));
        assert!(waiter.is_some());
        wire(&mut t, Ok(vec![3, 0]), 17).await;
        assert_eq!(t.next(&mut waiter), Some((18, Some([3, 0]), original)));
        wire(&mut t, Ok(vec![3, 0]), 18).await;
        assert!(t.next(&mut waiter).is_none());
        waiter
            .take()
            .unwrap()
            .reply
            .send(Ok((true, vec![16, 3, 17, 0, 0, 0])))
            .unwrap();
        let event = t.event().await;
        t.apply(event).unwrap();
        t.maintain(&mut waiter, Instant::now()).unwrap();
        assert_eq!(result.try_recv(), Err(oneshot::error::TryRecvError::Empty));
        assert_eq!(t.next(&mut waiter).unwrap().0, 17);
        wire(&mut t, Ok(vec![0, 0]), 17).await;
        assert!(!t.finished());
        assert_eq!(t.next(&mut waiter).unwrap().0, 18);
        wire(&mut t, Ok(vec![0, 0]), 18).await;
        assert!(t.finished());
        t.finish();
        assert!(result.await.unwrap().unwrap().0);
    }
    #[tokio::test]
    async fn occupied_remote_configuration_is_never_overwritten_or_cleared() {
        let (reply, result) = oneshot::channel();
        let mut t =
            ReceiveTransaction::new(vec![17], 1, Instant::now() + Duration::from_secs(1), reply);
        let mut waiter = None;
        assert!(t.next(&mut waiter).unwrap().1.is_none());
        wire(&mut t, Ok(vec![1, 0]), 17).await;
        t.maintain(&mut waiter, Instant::now()).unwrap();
        assert!(t.next(&mut waiter).is_none());
        assert!(t.finished());
        t.finish();
        assert!(
            result
                .await
                .unwrap()
                .unwrap_err()
                .contains("not overwritten")
        );
    }
    #[tokio::test]
    async fn cancellation_preserves_possible_effect_and_cleanup_has_a_fixed_deadline() {
        let now = Instant::now();
        let original = now + Duration::from_secs(1);
        let (reply, mut result) = oneshot::channel();
        let mut t = ReceiveTransaction::new(vec![17], 2, original, reply);
        let mut waiter = None;
        t.next(&mut waiter);
        wire(&mut t, Ok(vec![0, 0]), 17).await;
        t.next(&mut waiter);
        let (_held, rx) = oneshot::channel();
        t.submitted(17, rx, true);
        result.close();
        t.maintain(&mut waiter, now).unwrap();
        let e = t.event().await;
        t.apply(e).unwrap();
        assert!(!t.finished());
        assert!(waiter.is_none());
        assert_eq!(t.wake_deadline(), now + Duration::from_secs(5));
        assert_eq!(
            t.next(&mut waiter),
            Some((17, Some([0, 0]), now + Duration::from_secs(5)))
        );
        t.maintain(&mut waiter, now + Duration::from_secs(2))
            .unwrap();
        assert_eq!(t.wake_deadline(), now + Duration::from_secs(5));
        assert!(
            t.maintain(&mut waiter, now + Duration::from_secs(5))
                .is_err()
        );
        let (tx, rx) = oneshot::channel();
        t.submitted(17, rx, true);
        tx.send(Err("cleanup uncertain".into())).unwrap();
        let e = t.event().await;
        assert!(t.apply(e).is_err());
        assert!(!t.finished());
    }
}
