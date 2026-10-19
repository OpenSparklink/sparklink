//! One call-owned receive transaction inside the existing physical SSAP actor.
//! This is phase/ownership bookkeeping, not another wire loop or codec. The
//! actor's sole ClientRequest performs every real read/write and keeps debt.
use super::ssap_engine::IncomingDelivery;
use super::ssap_engine::{ClientFailure, Incoming, IncomingWait};
use crate::ssap_subscription::{CallerLease, Closed, Queue, SharedQueue, Sink};
use slk_contract::ssap::subscription as stream;
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
    StreamOwnerLost,
    ReadCancelled,
}
struct ReadWait {
    reply: oneshot::Sender<Result<stream::Batch, String>>,
    deadline: Instant,
}
struct Stream {
    owner: CallerLease,
    queue: SharedQueue,
    ready: Option<oneshot::Sender<Result<stream::Info, String>>>,
    read: Option<ReadWait>,
    close: Vec<oneshot::Sender<Result<stream::Batch, String>>>,
    installed: bool,
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
    reply: Option<oneshot::Sender<Result<Incoming, String>>>,
    stream: Option<Stream>,
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
            reply: Some(reply),
            stream: None,
            wire: None,
            data_send: Some(data_send),
            data: Some(data),
        }
    }
    fn closing(&self) -> bool {
        self.failure.is_some()
            || self.payload.is_some()
            || self
                .stream
                .as_ref()
                .is_some_and(|s| s.queue.lock().map_or(true, |q| q.is_closing()))
    }
    pub(crate) fn new_stream(
        handles: Vec<u16>,
        modes: u8,
        original: Instant,
        owner: CallerLease,
        info: stream::Info,
        expires: Instant,
        ready: oneshot::Sender<Result<stream::Info, String>>,
    ) -> Self {
        let (discard, _) = oneshot::channel();
        let mut result = Self::new(handles, modes, original, discard);
        result.reply = None;
        result.data_send = None;
        result.data = None;
        result.stream = Some(Stream {
            owner,
            queue: Queue::new(info, expires),
            ready: Some(ready),
            read: None,
            close: vec![],
            installed: false,
        });
        result
    }
    pub(crate) fn owns_client_sequence(&self) -> bool {
        self.stream.is_none() || !matches!(self.phase, Phase::Waiting) || self.closing()
    }
    pub(crate) fn expected_epoch(&self) -> Option<u64> {
        self.stream
            .as_ref()
            .map(|s| s.queue.lock().expect("checked queue").info.security_epoch)
    }
    pub(crate) fn matches(&self, caller: &str, token: u64) -> bool {
        self.stream.as_ref().is_some_and(|s| {
            s.owner.name == caller && s.queue.lock().is_ok_and(|q| q.info.token == token)
        })
    }
    pub(crate) fn read(
        &mut self,
        wait: bool,
        deadline: Instant,
        reply: oneshot::Sender<Result<stream::Batch, String>>,
    ) {
        let Some(s) = self.stream.as_mut() else {
            let _ = reply.send(Err("subscription unavailable".into()));
            return;
        };
        if reply.is_closed() {
            return;
        }
        if deadline <= Instant::now() || s.ready.is_some() || s.read.is_some() {
            let _ = reply.send(Err("subscription read pending/not-ready/expired".into()));
            return;
        }
        s.read = Some(ReadWait { reply, deadline });
        if !wait || s.queue.lock().is_ok_and(|q| q.has_data() || q.is_closing()) {
            Self::flush_read(s);
        }
    }
    fn flush_read(s: &mut Stream) {
        let Some(read) = s.read.take() else {
            return;
        };
        if read.reply.is_closed() {
            return;
        }
        if Instant::now() >= read.deadline {
            let _ = read
                .reply
                .send(Err("subscription read original deadline".into()));
            return;
        }
        let result = s
            .queue
            .lock()
            .map(|mut q| q.take_batch())
            .map_err(|_| "subscription queue poisoned".to_string());
        if let Err(Ok(batch)) = read.reply.send(result)
            && let Ok(mut q) = s.queue.lock()
        {
            q.restore(batch);
        }
    }
    pub(crate) fn renew(&mut self, duration_ms: u32) -> Result<stream::Info, String> {
        let s = self.stream.as_mut().ok_or("subscription unavailable")?;
        if !s.owner.current() || s.ready.is_some() {
            return Err("subscription owner/not-ready".into());
        }
        s.queue
            .lock()
            .map_err(|_| "subscription queue poisoned")?
            .renew(duration_ms, Instant::now())
    }
    pub(crate) fn close(&mut self, reply: oneshot::Sender<Result<stream::Batch, String>>) {
        let Some(s) = self.stream.as_mut() else {
            let _ = reply.send(Err("subscription unavailable".into()));
            return;
        };
        if s.close.len() >= 8 {
            let _ = reply.send(Err("subscription close waiters full".into()));
            return;
        }
        match s.queue.lock() {
            Ok(mut q) => {
                if let Err(e) = q.close(stream::RELEASED) {
                    let _ = reply.send(Err(e));
                    return;
                }
            }
            Err(_) => {
                let _ = reply.send(Err("subscription queue poisoned".into()));
                return;
            }
        }
        s.close.push(reply);
    }
    pub(crate) fn wake_deadline(&self) -> Instant {
        self.cleanup.unwrap_or_else(|| {
            self.stream.as_ref().map_or(self.original, |s| {
                let expiry = s.queue.lock().map_or(self.original, |q| q.expires);
                let expiry = if s.ready.is_some() {
                    expiry.min(self.original)
                } else {
                    expiry
                };
                s.read.as_ref().map_or(expiry, |r| expiry.min(r.deadline))
            })
        })
    }
    pub(crate) fn maintain(
        &mut self,
        waiter: &mut Option<IncomingWait>,
        now: Instant,
    ) -> Result<(), String> {
        if self
            .reply
            .as_ref()
            .is_some_and(|r| r.is_closed() || now >= self.original)
        {
            self.failure
                .get_or_insert_with(|| "receive caller cancelled/original deadline".into());
        }
        if let Some(s) = self.stream.as_mut() {
            let mut q = s.queue.lock().map_err(|_| "subscription queue poisoned")?;
            if !s.owner.current() {
                q.close(stream::OWNER_LOST)?;
            }
            if now >= q.expires {
                q.close(stream::EXPIRED)?;
            }
            if s.ready
                .as_ref()
                .is_some_and(|r| r.is_closed() || now >= self.original)
            {
                self.failure.get_or_insert_with(|| {
                    "subscription original creation cancelled/deadline".into()
                });
                q.close(stream::INITIALIZATION_CANCELLED)?;
            }
            let flush = s
                .read
                .as_ref()
                .is_some_and(|r| r.reply.is_closed() || now >= r.deadline)
                || q.has_data()
                || q.is_closing();
            drop(q);
            if flush {
                Self::flush_read(s);
            }
            if let Some(w) = waiter.as_mut() {
                w.deadline = s
                    .queue
                    .lock()
                    .map_err(|_| "subscription queue poisoned")?
                    .expires;
            }
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
                if let Some(s) = self.stream.as_mut()
                    && !s.installed
                {
                    *waiter = Some(IncomingWait {
                        handles: self.handles.clone(),
                        modes: self.modes,
                        deadline: s.queue.lock().expect("checked queue").expires,
                        reply: IncomingDelivery::Stream(Sink {
                            queue: s.queue.clone(),
                            alive: s.owner.observer(),
                        }),
                    });
                    s.installed = true;
                }
                if self.data_send.is_some() {
                    *waiter = Some(IncomingWait {
                        handles: self.handles.clone(),
                        modes: self.modes,
                        deadline: self.original,
                        reply: self
                            .data_send
                            .take()
                            .expect("install receive queue once")
                            .into(),
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
    pub(crate) fn finish(mut self) -> Option<Closed> {
        if let Some(mut s) = self.stream.take() {
            let mut q = s.queue.lock().expect("checked queue");
            let token = q.info.token;
            let result = match self.failure {
                Some(error) => Err(error),
                None => Ok(q.closed(true)),
            };
            if let Some(ready) = s.ready.take() {
                let _ = ready.send(Err("subscription ended before ready".into()));
            }
            if let Some(read) = s.read.take() {
                let _ = read.reply.send(Err("subscription ended".into()));
            }
            for reply in s.close {
                let _ = reply.send(result.clone());
            }
            return Some(Closed {
                owner: s.owner.name.clone(),
                token,
                result,
            });
        }
        let result = match (self.failure, self.payload) {
            (Some(error), _) => Err(error),
            (None, Some(packet)) if Instant::now() < self.original => Ok(packet),
            _ => Err("receive original deadline/no payload".into()),
        };
        let _ = self.reply.expect("one-shot reply").send(result);
        None
    }
    pub(crate) fn apply(&mut self, event: Event) -> Result<(), String> {
        match event {
            Event::Cancelled => {
                self.failure
                    .get_or_insert_with(|| "receive caller cancelled".into());
            }
            Event::StreamOwnerLost => {
                self.stream
                    .as_mut()
                    .expect("stream event")
                    .queue
                    .lock()
                    .map_err(|_| "subscription queue poisoned")?
                    .close(stream::OWNER_LOST)?;
            }
            Event::ReadCancelled => {
                self.stream.as_mut().expect("stream event").read.take();
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
                if matches!(self.phase, Phase::Waiting)
                    && let Some(s) = self.stream.as_mut()
                {
                    let mut q = s.queue.lock().map_err(|_| "subscription queue poisoned")?;
                    if s.owner.current()
                        && Instant::now() < self.original
                        && Instant::now() < q.expires
                    {
                        q.active();
                        if let Some(ready) = s.ready.take()
                            && ready.send(Ok(q.info.clone())).is_err()
                        {
                            q.close(stream::INITIALIZATION_CANCELLED)?;
                        }
                    } else {
                        q.close(stream::INITIALIZATION_CANCELLED)?;
                    }
                }
            }
        }
        Ok(())
    }
    pub(crate) async fn event(&mut self) -> Event {
        let cancel = !self.closing();
        let wire = self.wire.is_some();
        let data = self.data.is_some();
        if let Some(s) = self.stream.as_mut() {
            let mut alive = s.owner.observer();
            let ready = s.ready.is_some() && cancel;
            let read = s.read.is_some();
            if !cancel && !wire && !read {
                return std::future::pending().await;
            }
            return tokio::select! {biased;
                _=async{if *alive.borrow(){let _=alive.changed().await;}},if cancel=>Event::StreamOwnerLost,
                _=async{s.ready.as_mut().expect("guarded readiness").closed().await},if ready=>Event::Cancelled,
                _=async{s.read.as_mut().expect("guarded reader").reply.closed().await},if read=>Event::ReadCancelled,
                value=async{self.wire.as_mut().expect("guarded wire reply").await},if wire=>
                    Event::Wire(value.unwrap_or_else(|_|Err("receive physical request ended/cancelled".into()))),
            };
        }
        if !cancel && !wire && !data {
            return std::future::pending().await;
        }
        tokio::select! {biased;
            _=self.reply.as_mut().expect("one-shot reply").closed(),if cancel=>Event::Cancelled,
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

    #[tokio::test]
    async fn stream_releases_client_lane_and_read_cancel_does_not_release_configuration() {
        // The D-Bus owner is real. Wire replies and security receipts are
        // explicit post-admission fixtures; no Native ioctl/USB success stub.
        let bus = crate::event_loop::tests::PrivateBus::start();
        let service = zbus::connection::Builder::address(bus.address.as_str())
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
        let original = Instant::now() + Duration::from_secs(2);
        let expires = Instant::now() + Duration::from_secs(3);
        let owner = CallerLease::pin(
            &service,
            name.clone(),
            std::sync::Arc::new(tokio::sync::Semaphore::new(1))
                .acquire_owned()
                .await
                .unwrap(),
            original,
        )
        .await
        .unwrap();
        let info = stream::Info {
            version: 1,
            controller: 2,
            generation: 7,
            lifetime: 9,
            handle: 11,
            security_epoch: 13,
            token: 17,
            expires_ns: slk_channel::security::deadline_at(expires.into_std()).unwrap(),
            handles: vec![19],
            modes: 3,
            state: stream::STARTING,
            capacity: 16,
        };
        let (ready, result) = oneshot::channel();
        let mut t =
            ReceiveTransaction::new_stream(vec![19], 3, original, owner, info, expires, ready);
        let mut waiter = None;
        assert!(t.owns_client_sequence());
        assert_eq!(t.next(&mut waiter), Some((19, None, original)));
        wire(&mut t, Ok(vec![0, 0]), 19).await;
        assert_eq!(t.next(&mut waiter), Some((19, Some([3, 0]), original)));
        wire(&mut t, Ok(vec![3, 0]), 19).await;
        assert_eq!(result.await.unwrap().unwrap().state, stream::ACTIVE);
        assert!(!t.owns_client_sequence());
        assert!(t.matches(&name, 17));
        assert!(!t.matches(":1.999999", 17));
        assert!(!t.matches(&name, 18));
        let (reply, read) = oneshot::channel();
        t.read(true, original, reply);
        drop(read);
        assert!(matches!(t.event().await, Event::ReadCancelled));
        t.apply(Event::ReadCancelled).unwrap();
        t.maintain(&mut waiter, Instant::now()).unwrap();
        assert!(!t.closing());
        assert!(waiter.is_some());
        assert_eq!(t.possibly_enabled, vec![19]);
        let (reply, closed) = oneshot::channel();
        t.close(reply);
        let now = Instant::now();
        t.maintain(&mut waiter, now).unwrap();
        let cleanup = t.wake_deadline();
        assert_eq!(cleanup, now + Duration::from_secs(5));
        assert!(t.owns_client_sequence());
        assert!(t.renew(60000).is_err());
        assert_eq!(t.wake_deadline(), cleanup);
        assert_eq!(t.next(&mut waiter), Some((19, Some([0, 0]), cleanup)));
        wire(&mut t, Ok(vec![0, 0]), 19).await;
        assert!(t.finished());
        let tombstone = t.finish().unwrap();
        assert_eq!(tombstone.owner, name);
        assert_eq!(tombstone.token, 17);
        let closed = closed.await.unwrap().unwrap();
        assert_eq!(closed.info.state, stream::CLOSED);
        assert_eq!(closed.flags, stream::CLEANUP_CONFIRMED);
        assert_eq!(closed.reason, stream::RELEASED);
        assert_eq!(tombstone.result, Ok(closed));
    }
}
