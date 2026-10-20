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
    StreamOwnerLost(u64),
    ReadCancelled(u64),
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
    stream: Option<Vec<Stream>>,
    installed: bool,
    closed_streams: Vec<Closed>,
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
            installed: false,
            closed_streams: vec![],
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
                .is_some_and(|streams| streams.iter().all(Stream::closing))
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
        result.stream = Some(vec![Stream {
            owner,
            queue: Queue::new(info, expires),
            ready: Some(ready),
            read: None,
            close: vec![],
        }]);
        result
    }
    pub(crate) fn owns_client_sequence(&self) -> bool {
        self.stream.is_none() || !matches!(self.phase, Phase::Waiting) || self.closing()
    }
    pub(crate) fn expected_epoch(&self) -> Option<u64> {
        self.stream
            .as_ref()
            .and_then(|s| s.first())
            .map(|s| s.queue.lock().expect("checked queue").info.security_epoch)
    }
    fn stream_mut(&mut self, caller: &str, token: u64) -> Option<&mut Stream> {
        self.stream
            .as_mut()?
            .iter_mut()
            .find(|s| s.matches(caller, token))
    }
    pub(crate) fn matches(&self, caller: &str, token: u64) -> bool {
        self.stream
            .as_ref()
            .is_some_and(|s| s.iter().any(|s| s.matches(caller, token)))
    }
    /// A shared attachment owns no new wire request. Incompatible filters need
    /// the future aggregate-reconfiguration transaction,not a blind overwrite.
    pub(crate) fn can_join(&self, info: &stream::Info) -> bool {
        let Some(streams) = &self.stream else {
            return false;
        };
        if !matches!(self.phase, Phase::Waiting)
            || self.closing()
            || self.wire.is_some()
            || streams.len() >= 8
            || info.token == 0
            || streams.iter().any(|s| s.token() == info.token)
        {
            return false;
        }
        streams.iter().any(|s| {
            s.owner.current()
                && s.queue.lock().is_ok_and(|q| {
                    let mut old = q.info.handles.clone();
                    old.sort_unstable();
                    let mut new = info.handles.clone();
                    new.sort_unstable();
                    q.info.state == stream::ACTIVE
                        && Instant::now() < q.expires
                        && old == new
                        && q.info.modes == info.modes
                        && (
                            q.info.controller,
                            q.info.generation,
                            q.info.lifetime,
                            q.info.handle,
                            q.info.security_epoch,
                        ) == (
                            info.controller,
                            info.generation,
                            info.lifetime,
                            info.handle,
                            info.security_epoch,
                        )
                })
        })
    }
    pub(crate) fn join(
        &mut self,
        owner: CallerLease,
        mut info: stream::Info,
        expires: Instant,
        original: Instant,
        ready: oneshot::Sender<Result<stream::Info, String>>,
    ) {
        if !self.can_join(&info)
            || !owner.current()
            || Instant::now() >= original
            || Instant::now() >= expires
        {
            let _ = ready.send(Err(
                "subscription shared scope/capacity/original deadline".into()
            ));
            return;
        }
        info.state = stream::ACTIVE;
        let queue = Queue::new(info.clone(), expires);
        let group = self.stream.as_mut().expect("checked stream group");
        group.push(Stream {
            owner,
            queue: queue.clone(),
            ready: None,
            read: None,
            close: vec![],
        });
        if ready.send(Ok(info)).is_err() {
            let _ = queue
                .lock()
                .expect("checked queue")
                .close(stream::INITIALIZATION_CANCELLED);
        }
    }
    pub(crate) fn take_closed(&mut self) -> Vec<Closed> {
        std::mem::take(&mut self.closed_streams)
    }
    pub(crate) fn read(
        &mut self,
        caller: &str,
        token: u64,
        wait: bool,
        deadline: Instant,
        reply: oneshot::Sender<Result<stream::Batch, String>>,
    ) {
        let Some(s) = self.stream_mut(caller, token) else {
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
    pub(crate) fn renew(
        &mut self,
        caller: &str,
        token: u64,
        duration_ms: u32,
    ) -> Result<stream::Info, String> {
        let s = self
            .stream_mut(caller, token)
            .ok_or("subscription unavailable")?;
        if !s.owner.current() || s.ready.is_some() {
            return Err("subscription owner/not-ready".into());
        }
        s.queue
            .lock()
            .map_err(|_| "subscription queue poisoned")?
            .renew(duration_ms, Instant::now())
    }
    pub(crate) fn close(
        &mut self,
        caller: &str,
        token: u64,
        reply: oneshot::Sender<Result<stream::Batch, String>>,
    ) {
        let Some(s) = self.stream_mut(caller, token) else {
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
                s.iter()
                    .map(|s| {
                        let expiry = s.queue.lock().map_or(self.original, |q| q.expires);
                        let expiry = if s.ready.is_some() {
                            expiry.min(self.original)
                        } else {
                            expiry
                        };
                        s.read.as_ref().map_or(expiry, |r| expiry.min(r.deadline))
                    })
                    .min()
                    .unwrap_or(self.original)
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
        if let Some(streams) = self.stream.as_mut() {
            for s in streams.iter_mut() {
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
            }
            // Partial lease teardown never changes the physical CPCD. Remove
            // its RX route and queue first;remaining bindings retain the debt.
            if matches!(self.phase, Phase::Waiting)
                && self.failure.is_none()
                && streams.iter().any(|s| !s.closing())
            {
                let mut i = 0;
                while i < streams.len() {
                    if streams[i].closing() {
                        self.closed_streams
                            .push(streams.remove(i).finish(None, true));
                    } else {
                        i += 1;
                    }
                }
            }
            if let Some(w) = waiter.as_mut() {
                w.deadline = streams
                    .iter()
                    .map(|s| s.queue.lock().expect("checked queue").expires)
                    .max()
                    .expect("nonempty group");
                w.reply = IncomingDelivery::Stream(streams.iter().map(Stream::sink).collect());
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
                if let Some(streams) = self.stream.as_ref()
                    && !self.installed
                {
                    *waiter = Some(IncomingWait {
                        handles: self.handles.clone(),
                        modes: self.modes,
                        deadline: streams
                            .iter()
                            .map(|s| s.queue.lock().expect("checked queue").expires)
                            .max()
                            .expect("nonempty group"),
                        reply: IncomingDelivery::Stream(streams.iter().map(Stream::sink).collect()),
                    });
                    self.installed = true;
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
    pub(crate) fn finish(mut self) -> Vec<Closed> {
        if let Some(streams) = self.stream.take() {
            self.closed_streams.extend(
                streams
                    .into_iter()
                    .map(|s| s.finish(self.failure.clone(), false)),
            );
            return self.closed_streams;
        }
        let result = match (self.failure, self.payload) {
            (Some(error), _) => Err(error),
            (None, Some(packet)) if Instant::now() < self.original => Ok(packet),
            _ => Err("receive original deadline/no payload".into()),
        };
        let _ = self.reply.expect("one-shot reply").send(result);
        vec![]
    }
    pub(crate) fn apply(&mut self, event: Event) -> Result<(), String> {
        match event {
            Event::Cancelled => {
                self.failure
                    .get_or_insert_with(|| "receive caller cancelled".into());
            }
            Event::StreamOwnerLost(token) => {
                let s = self
                    .stream
                    .as_mut()
                    .and_then(|s| s.iter_mut().find(|s| s.token() == token))
                    .ok_or("stale subscription owner event")?;
                s.queue
                    .lock()
                    .map_err(|_| "subscription queue poisoned")?
                    .close(stream::OWNER_LOST)?;
            }
            Event::ReadCancelled(token) => {
                let s = self
                    .stream
                    .as_mut()
                    .and_then(|s| s.iter_mut().find(|s| s.token() == token))
                    .ok_or("stale subscription read event")?;
                s.read.take();
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
                    && let Some(streams) = self.stream.as_mut()
                {
                    for s in streams {
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
        }
        Ok(())
    }
    pub(crate) async fn event(&mut self) -> Event {
        let cancel = !self.closing();
        let wire = self.wire.is_some();
        let data = self.data.is_some();
        if let Some(streams) = self.stream.as_mut() {
            // Futures live across polling and register every owner's actual
            // watch/oneshot waker. No per-owner timer or auxiliary wire task.
            let mut events: Vec<_> = streams.iter_mut().map(|s| Box::pin(s.event())).collect();
            return tokio::select! {biased;
                event=std::future::poll_fn(|cx|{
                    for event in &mut events {if let std::task::Poll::Ready(value)=event.as_mut().poll(cx){return std::task::Poll::Ready(value);}}
                    std::task::Poll::Pending
                })=>event,
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

impl Stream {
    fn token(&self) -> u64 {
        self.queue.lock().expect("checked queue").info.token
    }
    fn matches(&self, caller: &str, token: u64) -> bool {
        self.owner.name == caller && self.queue.lock().is_ok_and(|q| q.info.token == token)
    }
    fn closing(&self) -> bool {
        self.queue.lock().map_or(true, |q| q.is_closing())
    }
    fn sink(&self) -> Sink {
        Sink {
            queue: self.queue.clone(),
            alive: self.owner.observer(),
        }
    }
    fn finish(mut self, failure: Option<String>, retained: bool) -> Closed {
        let mut q = self.queue.lock().expect("checked queue");
        let token = q.info.token;
        let result = match failure {
            Some(error) => Err(error),
            None => {
                let mut b = q.closed(true);
                if retained {
                    b.flags |= stream::REMOTE_RETAINED;
                }
                Ok(b)
            }
        };
        if let Some(ready) = self.ready.take() {
            let _ = ready.send(Err("subscription ended before ready".into()));
        }
        if let Some(read) = self.read.take() {
            let _ = read.reply.send(Err("subscription ended".into()));
        }
        for reply in self.close {
            let _ = reply.send(result.clone());
        }
        Closed {
            owner: self.owner.name.clone(),
            token,
            result,
        }
    }
    async fn event(&mut self) -> Event {
        let cancel = !self.closing();
        let ready = self.ready.is_some() && cancel;
        let read = self.read.is_some();
        if !cancel && !read {
            return std::future::pending().await;
        }
        let token = self.token();
        let mut alive = self.owner.observer();
        tokio::select! {biased;
            _=async{if *alive.borrow(){let _=alive.changed().await;}},if cancel=>Event::StreamOwnerLost(token),
            _=async{self.ready.as_mut().expect("guarded readiness").closed().await},if ready=>Event::Cancelled,
            _=async{self.read.as_mut().expect("guarded reader").reply.closed().await},if read=>Event::ReadCancelled(token),
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
        t.read(&name, 17, true, original, reply);
        drop(read);
        assert!(matches!(t.event().await, Event::ReadCancelled(17)));
        t.apply(Event::ReadCancelled(17)).unwrap();
        t.maintain(&mut waiter, Instant::now()).unwrap();
        assert!(!t.closing());
        assert!(waiter.is_some());
        assert_eq!(t.possibly_enabled, vec![19]);
        let (reply, closed) = oneshot::channel();
        t.close(&name, 17, reply);
        let now = Instant::now();
        t.maintain(&mut waiter, now).unwrap();
        let cleanup = t.wake_deadline();
        assert_eq!(cleanup, now + Duration::from_secs(5));
        assert!(t.owns_client_sequence());
        assert!(t.renew(&name, 17, 60000).is_err());
        assert_eq!(t.wake_deadline(), cleanup);
        assert_eq!(t.next(&mut waiter), Some((19, Some([0, 0]), cleanup)));
        wire(&mut t, Ok(vec![0, 0]), 19).await;
        assert!(t.finished());
        let tombstone = t.finish().pop().unwrap();
        assert_eq!(tombstone.owner, name);
        assert_eq!(tombstone.token, 17);
        let closed = closed.await.unwrap().unwrap();
        assert_eq!(closed.info.state, stream::CLOSED);
        assert_eq!(closed.flags, stream::CLEANUP_CONFIRMED);
        assert_eq!(closed.reason, stream::RELEASED);
        assert_eq!(tombstone.result, Ok(closed));
    }
    async fn shared_owner(
        service: &zbus::Connection,
        caller: &zbus::Connection,
        token: u64,
        ttl: u64,
    ) -> (CallerLease, stream::Info, Instant) {
        let original = Instant::now() + Duration::from_secs(3);
        let expires = Instant::now() + Duration::from_secs(ttl);
        let owner = CallerLease::pin(
            service,
            caller.unique_name().unwrap().to_string(),
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
            token,
            expires_ns: slk_channel::deadline::monotonic_timestamp_at(expires.into_std()).unwrap(),
            handles: vec![19],
            modes: 3,
            state: stream::STARTING,
            capacity: 16,
        };
        (owner, info, expires)
    }
    async fn shared_group(
        service: &zbus::Connection,
        caller: &zbus::Connection,
    ) -> (ReceiveTransaction, Option<IncomingWait>) {
        let (owner, info, expires) = shared_owner(service, caller, 17, 30).await;
        let original = Instant::now() + Duration::from_secs(3);
        let (ready, result) = oneshot::channel();
        let mut t =
            ReceiveTransaction::new_stream(vec![19], 3, original, owner, info, expires, ready);
        let mut waiter = None;
        assert_eq!(t.next(&mut waiter), Some((19, None, original)));
        wire(&mut t, Ok(vec![0, 0]), 19).await;
        assert_eq!(t.next(&mut waiter), Some((19, Some([3, 0]), original)));
        wire(&mut t, Ok(vec![3, 0]), 19).await;
        assert_eq!(result.await.unwrap().unwrap().state, stream::ACTIVE);
        t.maintain(&mut waiter, Instant::now()).unwrap();
        (t, waiter)
    }
    async fn shared_bus() -> (
        crate::event_loop::tests::PrivateBus,
        zbus::Connection,
        zbus::Connection,
        zbus::Connection,
    ) {
        let bus = crate::event_loop::tests::PrivateBus::start();
        let service = zbus::connection::Builder::address(bus.address.as_str())
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
        (bus, service, a, b)
    }
    async fn attach(
        t: &mut ReceiveTransaction,
        service: &zbus::Connection,
        caller: &zbus::Connection,
        token: u64,
        ttl: u64,
    ) {
        let (owner, info, expires) = shared_owner(service, caller, token, ttl).await;
        let (ready, result) = oneshot::channel();
        assert!(t.can_join(&info));
        t.join(
            owner,
            info,
            expires,
            Instant::now() + Duration::from_secs(3),
            ready,
        );
        assert_eq!(result.await.unwrap().unwrap().token, token);
    }
    #[tokio::test]
    async fn shared_release_retains_sibling_and_only_last_reference_owes_disable() {
        let (_bus, service, a, b) = shared_bus().await;
        let an = a.unique_name().unwrap().to_string();
        let bn = b.unique_name().unwrap().to_string();
        let (mut t, mut waiter) = shared_group(&service, &a).await;
        attach(&mut t, &service, &b, 18, 30).await;
        t.maintain(&mut waiter, Instant::now()).unwrap();
        let (reply, released) = oneshot::channel();
        t.close(&an, 17, reply);
        t.maintain(&mut waiter, Instant::now()).unwrap();
        let result = released.await.unwrap().unwrap();
        assert_eq!(result.flags, 3);
        assert_eq!(result.reason, stream::RELEASED);
        let tombstones = t.take_closed();
        assert_eq!(tombstones.len(), 1);
        assert_eq!(tombstones[0].owner, an);
        assert!(!t.matches(&an, 17));
        assert!(!t.matches(&an, 18));
        assert!(t.matches(&bn, 18));
        assert_eq!(t.possibly_enabled, vec![19]);
        assert!(t.cleanup.is_none());
        assert!(t.next(&mut waiter).is_none());
        assert!(!t.owns_client_sequence());
        assert!(t.renew(&an, 17, 30000).is_err());
        assert!(t.renew(&bn, 18, 30000).is_ok());
        attach(&mut t, &service, &a, 19, 30).await;
        t.maintain(&mut waiter, Instant::now()).unwrap();
        let (reply, closed) = oneshot::channel();
        t.close(&an, 19, reply);
        t.maintain(&mut waiter, Instant::now()).unwrap();
        assert_eq!(closed.await.unwrap().unwrap().flags, 3);
        let (reply, last) = oneshot::channel();
        t.close(&bn, 18, reply);
        let now = Instant::now();
        t.maintain(&mut waiter, now).unwrap();
        assert_eq!(t.wake_deadline(), now + Duration::from_secs(5));
        assert!(waiter.is_none());
        assert_eq!(
            t.next(&mut waiter),
            Some((19, Some([0, 0]), now + Duration::from_secs(5)))
        );
        assert!(!t.finished());
        wire(&mut t, Ok(vec![0, 0]), 19).await;
        assert!(t.finished());
        let closed = t.finish();
        assert_eq!(closed.len(), 2);
        assert_eq!(last.await.unwrap().unwrap().flags, 1);
    }
    #[tokio::test]
    async fn secondary_owner_watch_and_expiry_do_not_close_primary() {
        for expiry in [false, true] {
            let (_bus, service, a, b) = shared_bus().await;
            let an = a.unique_name().unwrap().to_string();
            let bn = b.unique_name().unwrap().to_string();
            let (mut t, mut waiter) = shared_group(&service, &a).await;
            attach(&mut t, &service, &b, 18, 10).await;
            t.maintain(&mut waiter, Instant::now()).unwrap();
            let now = if expiry {
                t.stream.as_ref().unwrap()[1].queue.lock().unwrap().expires
            } else {
                b.close().await.unwrap();
                let event = tokio::time::timeout(Duration::from_secs(2), t.event())
                    .await
                    .unwrap();
                assert!(matches!(event, Event::StreamOwnerLost(18)));
                t.apply(event).unwrap();
                Instant::now()
            };
            t.maintain(&mut waiter, now).unwrap();
            let closed = t.take_closed();
            assert_eq!(closed.len(), 1);
            let terminal = closed[0].result.as_ref().unwrap();
            assert_eq!(terminal.flags, 3);
            assert_eq!(
                terminal.reason,
                if expiry {
                    stream::EXPIRED
                } else {
                    stream::OWNER_LOST
                }
            );
            assert!(t.matches(&an, 17));
            assert!(!t.matches(&bn, 18));
            assert!(t.cleanup.is_none());
            assert_eq!(t.possibly_enabled, vec![19]);
        }
    }
    #[tokio::test]
    async fn secondary_read_cancellation_is_woken_and_keeps_both_leases() {
        let (_bus, service, a, b) = shared_bus().await;
        let an = a.unique_name().unwrap().to_string();
        let bn = b.unique_name().unwrap().to_string();
        let (mut t, mut waiter) = shared_group(&service, &a).await;
        attach(&mut t, &service, &b, 18, 30).await;
        t.maintain(&mut waiter, Instant::now()).unwrap();
        let (a_reply, a_wait) = oneshot::channel();
        let (b_reply, b_wait) = oneshot::channel();
        let original = Instant::now() + Duration::from_secs(3);
        t.read(&an, 17, true, original, a_reply);
        t.read(&bn, 18, true, original, b_reply);
        drop(b_wait);
        let event = tokio::time::timeout(Duration::from_secs(2), t.event())
            .await
            .unwrap();
        assert!(matches!(event, Event::ReadCancelled(18)));
        t.apply(event).unwrap();
        assert!(t.stream_mut(&an, 17).unwrap().read.is_some());
        assert!(t.stream_mut(&bn, 18).unwrap().read.is_none());
        t.maintain(&mut waiter, Instant::now()).unwrap();
        assert!(!t.closing());
        assert!(t.take_closed().is_empty());
        drop(a_wait);
    }
    #[tokio::test]
    async fn shared_admission_checks_live_identity_filter_tokens_and_capacity() {
        let (_bus, service, a, b) = shared_bus().await;
        let (mut t, _waiter) = shared_group(&service, &a).await;
        let (_, info, _) = shared_owner(&service, &b, 18, 30).await;
        assert!(t.can_join(&info));
        for field in 0..10 {
            let mut bad = info.clone();
            match field {
                0 => bad.controller += 1,
                1 => bad.generation += 1,
                2 => bad.lifetime += 1,
                3 => bad.handle += 1,
                4 => bad.security_epoch += 1,
                5 => bad.modes = 1,
                6 => bad.handles = vec![20],
                7 => bad.token = 17,
                8 => bad.token = 0,
                _ => bad.handles.push(20),
            };
            assert!(!t.can_join(&bad));
        }
        for token in 18..25 {
            attach(&mut t, &service, &b, token, 30).await;
        }
        let (_, next, _) = shared_owner(&service, &b, 25, 30).await;
        assert!(!t.can_join(&next));
        assert_eq!(t.stream.as_ref().unwrap().len(), 8);
        let (_bus, service, a, b) = shared_bus().await;
        let (t, _) = shared_group(&service, &a).await;
        let (_, info, _) = shared_owner(&service, &b, 18, 30).await;
        t.stream.as_ref().unwrap()[0].queue.lock().unwrap().expires = Instant::now();
        assert!(!t.can_join(&info));
    }
}
