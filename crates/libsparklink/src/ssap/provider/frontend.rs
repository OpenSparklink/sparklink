//! One application-side value inbox, shared by Rust, CLI and language bindings.
//! No protocol engine: the original daemon owns each READ/WRITE obligation. Registry
//! locks never span queue locks or await. A delivered slot remains charged until
//! both the callback guard and the application request have been released.
use super::{ProviderKind, RequestData};
use crate::{ApplicationError, Client, Deadline, ssap::authorization::AuthorizationContext};
use slk_contract::{
    ControllerId,
    ssap::{
        PROVIDER_UNAVAILABLE, ReadProviderReply, ReadProviderRequest, WriteProviderReply,
        WriteProviderRequest,
    },
};
use slk_protocol::{SsapOperations, ssap::access::SsapAccess};
use std::{
    io,
    os::fd::{AsRawFd, FromRawFd, OwnedFd},
    sync::{
        Arc, Mutex, Weak,
        atomic::{AtomicBool, Ordering},
    },
    time::Instant,
};
use tokio::sync::{Notify, OwnedSemaphorePermit, Semaphore, oneshot, watch};
use zbus::zvariant::OwnedObjectPath;

pub(crate) const PATH: &str = "/org/sparklink/sdk/ssap_read_provider";
const CAPACITY: usize = 16;
fn io_error(code: i32) -> io::Error {
    io::Error::from_raw_os_error(code)
}

/// Original registration's local stop domain. It is not a remote removal or
/// protocol state. Weak members never keep the caller or registration alive.
#[derive(Default)]
pub(crate) struct RegistrationScope {
    closed: AtomicBool,
    state: Mutex<ScopeState>,
}
#[derive(Default)]
struct ScopeState {
    attempted: Vec<u16>,
    queues: Vec<Weak<Queue>>,
}
impl RegistrationScope {
    fn attach(&self, handle: u16, queue: &Arc<Queue>) -> io::Result<()> {
        let mut s = self.state.lock().map_err(|_| io_error(nix::libc::EIO))?;
        if self.closed.load(Ordering::Acquire) {
            return Err(io_error(nix::libc::ESHUTDOWN));
        }
        if s.attempted.contains(&handle) {
            return Err(io_error(nix::libc::EALREADY));
        }
        s.attempted.push(handle);
        s.queues.push(Arc::downgrade(queue));
        Ok(())
    }
    pub(crate) fn stop(&self) {
        // Publish before collecting members: a callback's fresh check cannot
        // slip through the interval before its individual queue is stopped.
        self.closed.store(true, Ordering::Release);
        let queues = self
            .state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .queues
            .iter()
            .filter_map(Weak::upgrade)
            .collect::<Vec<_>>();
        for q in queues {
            q.stop();
        }
    }
}

struct Registry {
    closed: bool,
    queues: Vec<Weak<Queue>>,
}
/// Concrete dispatcher on one original Client bus. It retains no Client or bus
/// reference; endpoints and the explicit watch own its lifetime.
pub struct Dispatcher {
    daemon: String,
    caller: String,
    lost: watch::Receiver<bool>,
    path: OwnedObjectPath,
    slots: Arc<Semaphore>,
    registry: Mutex<Registry>,
}
struct Endpoint(Arc<Dispatcher>);
#[zbus::interface(name = "org.sparklink.SsapReadProvider")]
impl Endpoint {
    async fn read_value(
        &self,
        request: ReadProviderRequest,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<ReadProviderReply> {
        Ok(self
            .0
            .dispatch(request, header.sender().map(|s| s.as_str()))
            .await?
            .into_reply())
    }
}
struct WriteEndpoint(Arc<Dispatcher>);
#[zbus::interface(name = "org.sparklink.SsapWriteProvider")]
impl WriteEndpoint {
    async fn write_value(
        &self,
        request: WriteProviderRequest,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<WriteProviderReply> {
        let (status, value) = self
            .0
            .dispatch_write(request, header.sender().map(|s| s.as_str()))
            .await?
            .into_reply();
        Ok((
            u8::try_from(status).unwrap_or(PROVIDER_UNAVAILABLE as u8),
            value,
        ))
    }
}
impl Dispatcher {
    /// Prepare a concrete dispatcher for an endpoint exported by the caller.
    /// The CLI uses this adapter surface to log the final local result before
    /// returning the D-Bus reply. This does not install or bind a service.
    pub fn new(client: &Client, path: OwnedObjectPath) -> Result<Arc<Self>, ApplicationError> {
        if path.as_str() == "/" || path.as_str().len() > 255 {
            return Err(ApplicationError::Invalid("invalid provider endpoint path"));
        }
        let caller = client
            .bus()
            .unique_name()
            .ok_or(ApplicationError::Identity(
                "provider requires original bus caller",
            ))?
            .to_string();
        Ok(Arc::new(Self {
            daemon: client.daemon_owner().into(),
            caller,
            lost: client.owner_loss(),
            path,
            slots: Arc::new(Semaphore::new(CAPACITY)),
            registry: Mutex::new(Registry {
                closed: false,
                queues: Vec::new(),
            }),
        }))
    }
    /// Install the standard SDK endpoint on the original Client connection.
    /// The caller bounds installation with its existing open deadline.
    pub async fn install(client: &Client) -> Result<Arc<Self>, ApplicationError> {
        let d = Self::new(
            client,
            OwnedObjectPath::try_from(PATH).expect("constant path"),
        )?;
        // Cancelled partial installation leaves only closed bounded endpoints
        // until that original connection is dropped; it cannot admit callbacks.
        let mut install_stop = StopOnExit(Arc::downgrade(&d));
        if !client
            .bus()
            .object_server()
            .at(PATH, Endpoint(d.clone()))
            .await?
        {
            return Err(ApplicationError::Invalid(
                "caller SDK provider path already occupied",
            ));
        }
        match client
            .bus()
            .object_server()
            .at(PATH, WriteEndpoint(d.clone()))
            .await
        {
            Ok(true) => (),
            result => {
                // Remove only our newly installed READ interface, never the
                // pre-existing foreign WRITE endpoint. Client-open bounds this
                // cleanup; a failed open drops its original bus connection.
                client
                    .bus()
                    .object_server()
                    .remove::<Endpoint, _>(PATH)
                    .await?;
                result?;
                return Err(ApplicationError::Invalid(
                    "caller SDK write provider path already occupied",
                ));
            }
        }
        install_stop.0 = Weak::new();
        Ok(d)
    }
    pub fn watch(self: &Arc<Self>) -> Watch {
        let mut lost = self.lost.clone();
        let stop = StopOnExit(Arc::downgrade(self));
        let task = tokio::spawn(async move {
            let _stop = stop;
            if !*lost.borrow() {
                let _ = lost.changed().await;
            }
        });
        Watch {
            dispatcher: self.clone(),
            task,
        }
    }
    /// Stop local admission only. Existing remote bindings are not withdrawn.
    pub fn stop(&self) {
        let queues = {
            let mut r = self.registry.lock().unwrap_or_else(|e| e.into_inner());
            r.closed = true;
            r.queues
                .iter()
                .filter_map(Weak::upgrade)
                .collect::<Vec<_>>()
        };
        for q in queues {
            q.stop();
        }
    }
    /// Bind exactly once to an original read-only owned property. Success is a
    /// local broker commit, not RF publication. Any uncertain/cancelled bind
    /// closes the inbox and is never retried or given a stored-value fallback.
    pub async fn bind(
        self: &Arc<Self>,
        registration: &mut crate::ssap::local::ServiceRegistration,
        property: u16,
        original: Deadline,
    ) -> Result<Inbox, ApplicationError> {
        Ok(Inbox {
            core: self
                .bind_inner(registration, property, original, ProviderKind::Read)
                .await?,
        })
    }
    /// Original write-only binding over the same finite dispatcher and stop domain.
    /// No new queue budget, owner, deadline or callback execution thread.
    pub async fn bind_write(
        self: &Arc<Self>,
        registration: &mut crate::ssap::local::ServiceRegistration,
        property: u16,
        original: Deadline,
    ) -> Result<WriteInbox, ApplicationError> {
        Ok(WriteInbox {
            core: self
                .bind_inner(registration, property, original, ProviderKind::Write)
                .await?,
        })
    }
    async fn bind_inner(
        self: &Arc<Self>,
        registration: &mut crate::ssap::local::ServiceRegistration,
        property: u16,
        original: Deadline,
        kind: ProviderKind,
    ) -> Result<InboxCore, ApplicationError> {
        original.remaining()?;
        let client = registration.provider_client();
        if client.daemon_owner() != self.daemon
            || client.bus().unique_name().map(|s| s.as_str()) != Some(self.caller.as_str())
            || !self.lost.same_channel(&client.owner_loss())
        {
            return Err(ApplicationError::Identity(
                "provider belongs to a different original Client",
            ));
        }
        let (controller, operations, access) = registration.provider_context(property)?;
        if !kind.supports(operations) {
            return Err(io_error(nix::libc::EOPNOTSUPP).into());
        }
        let scope = registration.provider_scope();
        let queue = self.reserve(controller, property, operations, access, &scope)?;
        let inbox = InboxCore { queue };
        scope.attach(property, &inbox.queue)?;
        // Publish only after the original property has been claimed. A refused
        // duplicate bind must not momentarily shadow the already live inbox.
        self.publish(&inbox.queue)?;
        // Inbox Drop is the cancellation guard, including a lost bind reply.
        match kind {
            ProviderKind::Read => {
                registration
                    .bind_read_provider(property, self.path.clone(), original)
                    .await?
            }
            ProviderKind::Write => {
                registration
                    .bind_write_provider(property, self.path.clone(), original)
                    .await?
            }
        }
        original.remaining()?;
        if !inbox.queue.open() {
            return Err(io_error(nix::libc::ESHUTDOWN).into());
        }
        Ok(inbox)
    }
    fn reserve(
        &self,
        controller: ControllerId,
        property: u16,
        operations: SsapOperations,
        access: SsapAccess,
        scope: &Arc<RegistrationScope>,
    ) -> io::Result<Arc<Queue>> {
        let permit = self
            .slots
            .clone()
            .try_acquire_owned()
            .map_err(|_| io_error(nix::libc::EAGAIN))?;
        // SAFETY: a private nonblocking CLOEXEC eventfd, never a device fd.
        let fd = unsafe { nix::libc::eventfd(0, nix::libc::EFD_CLOEXEC | nix::libc::EFD_NONBLOCK) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        let queue = Arc::new(Queue {
            controller,
            property,
            operations,
            access,
            daemon: self.daemon.clone(),
            lost: self.lost.clone(),
            scope: scope.clone(),
            event: unsafe { OwnedFd::from_raw_fd(fd) },
            wake: Notify::new(),
            _permit: permit,
            state: Mutex::new(State {
                closed: false,
                pending: None,
                next_token: 0,
                signaled: false,
            }),
        });
        Ok(queue)
    }
    fn publish(&self, queue: &Arc<Queue>) -> io::Result<()> {
        let mut r = self.registry.lock().map_err(|_| io_error(nix::libc::EIO))?;
        if r.closed || *self.lost.borrow() || self.lost.has_changed().is_err() {
            return Err(io_error(nix::libc::ESTALE));
        }
        r.queues.retain(|q| q.strong_count() != 0);
        r.queues.push(Arc::downgrade(queue));
        Ok(())
    }
    /// The single value callback lifecycle, shared by thin SDK/CLI adapters.
    /// Keep the returned guard alive through local result reporting. Its reply
    /// says nothing about actual D-Bus/wire/peer delivery.
    pub async fn dispatch(
        self: &Arc<Self>,
        request: ReadProviderRequest,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<CallbackOutcome> {
        self.dispatch_inner(RequestData::Read(request), sender)
            .await
    }
    /// Typed WRITE adapter; shares original queue, capacity and drain lifecycle.
    pub async fn dispatch_write(
        self: &Arc<Self>,
        request: WriteProviderRequest,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<CallbackOutcome> {
        self.dispatch_inner(RequestData::Write(request), sender)
            .await
    }
    async fn dispatch_inner(
        self: &Arc<Self>,
        request: RequestData,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<CallbackOutcome> {
        super::super::authorization::check_sender(&self.daemon, sender)?;
        let queues = {
            let r = self
                .registry
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("provider registry poisoned".into()))?;
            if r.closed {
                return Ok(CallbackOutcome::unavailable());
            }
            r.queues
                .iter()
                .filter_map(Weak::upgrade)
                .collect::<Vec<_>>()
        };
        let mut selected = None;
        for q in queues {
            if q.matches(&request) {
                if selected.is_some() {
                    return Ok(CallbackOutcome::unavailable());
                }
                selected = Some(q);
            }
        }
        match selected {
            Some(q) => q.dispatch(request, sender).await,
            None => Ok(CallbackOutcome::unavailable()),
        }
    }
}
pub struct Watch {
    dispatcher: Arc<Dispatcher>,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Watch {
    fn drop(&mut self) {
        self.dispatcher.stop();
        self.task.abort();
    }
}
struct StopOnExit(Weak<Dispatcher>);
impl Drop for StopOnExit {
    fn drop(&mut self) {
        if let Some(d) = self.0.upgrade() {
            d.stop();
        }
    }
}

/// Retains callback capacity until a thin adapter has reported its final local
/// result. A reportable outcome is not remote delivery or authentication.
pub struct CallbackOutcome {
    reply: ReadProviderReply,
    reportable: bool,
    _drain: Option<Callback>,
}
impl CallbackOutcome {
    fn unavailable() -> Self {
        Self {
            reply: (PROVIDER_UNAVAILABLE, Vec::new()),
            reportable: false,
            _drain: None,
        }
    }
    pub fn reportable(&self) -> bool {
        self.reportable
    }
    pub fn reply(&self) -> &ReadProviderReply {
        &self.reply
    }
    pub fn into_reply(self) -> ReadProviderReply {
        self.reply
    }
}
struct Data {
    token: u64,
    request: RequestData,
    original: Instant,
}
struct Pending {
    data: Arc<Data>,
    reply: Option<oneshot::Sender<ReadProviderReply>>,
    delivered: bool,
    released: bool,
    done: bool,
}
struct State {
    closed: bool,
    pending: Option<Pending>,
    next_token: u64,
    signaled: bool,
}
struct Queue {
    controller: ControllerId,
    property: u16,
    operations: SsapOperations,
    access: SsapAccess,
    daemon: String,
    lost: watch::Receiver<bool>,
    scope: Arc<RegistrationScope>,
    event: OwnedFd,
    wake: Notify,
    _permit: OwnedSemaphorePermit,
    state: Mutex<State>,
}
impl Queue {
    fn open(&self) -> bool {
        !self.scope.closed.load(Ordering::Acquire)
            && !*self.lost.borrow()
            && self.lost.has_changed().is_ok()
            && self.state.lock().is_ok_and(|s| !s.closed)
    }
    fn matches(&self, r: &RequestData) -> bool {
        (r.identity().0, r.identity().1, r.property())
            == (
                self.controller.index,
                self.controller.generation,
                self.property,
            )
            && r.kind().supports(self.operations)
            && self.open()
    }
    fn context(&self, s: &State) -> AuthorizationContext<'_> {
        AuthorizationContext {
            daemon_owner: &self.daemon,
            owner_lost: *self.lost.borrow() || self.lost.has_changed().is_err(),
            controller: self.controller,
            property: if s.closed || self.scope.closed.load(Ordering::Acquire) {
                None
            } else {
                Some(self.property)
            },
            operations: self.operations,
            access: self.access,
        }
    }
    fn notify(&self, s: &mut State, ready: bool) -> io::Result<()> {
        if s.signaled != ready {
            let mut value = 1u64;
            // SAFETY: one initialized u64 and a private nonblocking eventfd.
            let n = unsafe {
                if ready {
                    nix::libc::write(self.event.as_raw_fd(), (&value as *const u64).cast(), 8)
                } else {
                    nix::libc::read(self.event.as_raw_fd(), (&mut value as *mut u64).cast(), 8)
                }
            };
            if n != 8 {
                let e = io::Error::last_os_error();
                if n >= 0 || e.raw_os_error() != Some(nix::libc::EAGAIN) {
                    return Err(e);
                }
            }
            s.signaled = ready;
        }
        self.wake.notify_waiters();
        Ok(())
    }
    fn stop(&self) {
        let mut s = self.state.lock().unwrap_or_else(|e| e.into_inner());
        s.closed = true;
        if let Some(p) = s.pending.as_mut() {
            p.reply.take();
        }
        let _ = self.notify(&mut s, true);
    }
    async fn dispatch(
        self: &Arc<Self>,
        request: RequestData,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<CallbackOutcome> {
        let (data, result) = {
            let mut s = self
                .state
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("provider inbox poisoned".into()))?;
            let Some(original) = request.admit(&self.context(&s), sender)? else {
                return Ok(CallbackOutcome::unavailable());
            };
            if s.pending.is_some() {
                return Ok(CallbackOutcome::unavailable());
            }
            let Some(token) = s.next_token.checked_add(1) else {
                return Ok(CallbackOutcome::unavailable());
            };
            s.next_token = token;
            let (reply, result) = oneshot::channel();
            let data = Arc::new(Data {
                token,
                request,
                original,
            });
            s.pending = Some(Pending {
                data: data.clone(),
                reply: Some(reply),
                delivered: false,
                released: false,
                done: false,
            });
            if self.notify(&mut s, true).is_err() {
                s.pending = None;
                s.closed = true;
                return Err(zbus::fdo::Error::Failed(
                    "provider notification failed".into(),
                ));
            }
            (data, result)
        };
        let guard = Callback {
            queue: self.clone(),
            token: data.token,
        };
        let reply = data
            .request
            .await_reply(result, self.lost.clone(), data.original)
            .await;
        let s = self
            .state
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("provider inbox poisoned".into()))?;
        let reportable = data.request.admit(&self.context(&s), sender)?.is_some();
        Ok(CallbackOutcome {
            reply: if reportable {
                reply
            } else {
                (PROVIDER_UNAVAILABLE, Vec::new())
            },
            reportable,
            _drain: Some(guard),
        })
    }
    fn next(self: &Arc<Self>) -> io::Result<RequestCore> {
        let mut s = self.state.lock().map_err(|_| io_error(nix::libc::EIO))?;
        if *self.lost.borrow() || self.lost.has_changed().is_err() {
            drop(s);
            self.stop();
            return Err(io_error(nix::libc::ESTALE));
        }
        if s.closed || self.scope.closed.load(Ordering::Acquire) {
            return Err(io_error(nix::libc::ESHUTDOWN));
        }
        let p = s
            .pending
            .as_mut()
            .ok_or_else(|| io_error(nix::libc::EAGAIN))?;
        if p.delivered || p.done {
            return Err(io_error(nix::libc::EAGAIN));
        }
        if p.data.original <= Instant::now() || p.reply.as_ref().is_none_or(|r| r.is_closed()) {
            p.delivered = true;
            p.released = true;
            p.reply.take();
            self.notify(&mut s, false)?;
            return Err(io_error(nix::libc::ETIMEDOUT));
        }
        p.delivered = true;
        let data = p.data.clone();
        if let Err(e) = self.notify(&mut s, false) {
            if let Some(p) = s.pending.as_mut() {
                p.released = true;
                p.reply.take();
            }
            s.closed = true;
            return Err(e);
        }
        Ok(RequestCore {
            queue: self.clone(),
            data,
        })
    }
    fn finish(&self, token: u64) {
        let mut s = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(p) = s.pending.as_mut()
            && p.data.token == token
        {
            p.done = true;
            if !p.delivered || p.released {
                s.pending = None;
            }
        }
        let ready = s.closed;
        let _ = self.notify(&mut s, ready);
    }
}
impl Drop for Queue {
    fn drop(&mut self) {
        self.stop();
    }
}
struct Callback {
    queue: Arc<Queue>,
    token: u64,
}
impl Drop for Callback {
    fn drop(&mut self) {
        self.queue.finish(self.token);
    }
}

/// One consuming application per inbox. Drop closes local admission; it does
/// not withdraw the registration or restore its discarded stored value.
struct InboxCore {
    queue: Arc<Queue>,
}
impl InboxCore {
    pub fn close(&self) {
        self.queue.stop();
    }
    /// Duplicate a CLOEXEC fd. Poll only; never read/write its event counter.
    /// It does not retain a caller or authorize a reply. Try next before waiting.
    pub fn fd(&self) -> io::Result<OwnedFd> {
        self.queue.event.try_clone()
    }
    pub fn try_next(&self) -> io::Result<RequestCore> {
        self.queue.next()
    }
    /// Wait for a valid original request, skipping expired undelivered entries.
    /// Waiting creates no protocol deadline; each returned request keeps its own.
    pub async fn next(&self) -> io::Result<RequestCore> {
        loop {
            let wake = self.queue.wake.notified();
            tokio::pin!(wake);
            wake.as_mut().enable();
            match self.try_next() {
                Err(e) if e.raw_os_error() == Some(nix::libc::EAGAIN) => wake.await,
                Err(e) if e.raw_os_error() == Some(nix::libc::ETIMEDOUT) => continue,
                value => return value,
            }
        }
    }
}
impl Drop for InboxCore {
    fn drop(&mut self) {
        self.close();
    }
}
/// Immutable original request plus a one-shot local reply capability. No
/// Client/registration reference is retained. Free unanswered means unavailable.
struct RequestCore {
    queue: Arc<Queue>,
    data: Arc<Data>,
}
impl RequestCore {
    pub fn token(&self) -> u64 {
        self.data.token
    }
    pub fn is_active(&self) -> bool {
        self.queue
            .state
            .lock()
            .is_ok_and(|s| self.check(&s).is_ok())
    }
    fn check(&self, s: &State) -> io::Result<()> {
        if *self.queue.lost.borrow() || self.queue.lost.has_changed().is_err() {
            return Err(io_error(nix::libc::ESTALE));
        }
        if s.closed || self.queue.scope.closed.load(Ordering::Acquire) {
            return Err(io_error(nix::libc::ESHUTDOWN));
        }
        if self.data.original <= Instant::now() {
            return Err(io_error(nix::libc::ETIMEDOUT));
        }
        if self
            .data
            .request
            .admit(&self.queue.context(s), Some(&self.queue.daemon))
            .ok()
            .flatten()
            .is_none()
        {
            return Err(io_error(nix::libc::ESTALE));
        }
        if !s.pending.as_ref().is_some_and(|p| {
            p.data.token == self.data.token
                && p.delivered
                && !p.done
                && p.reply.as_ref().is_some_and(|r| !r.is_closed())
        }) {
            return Err(io_error(nix::libc::ESTALE));
        }
        Ok(())
    }
    /// Accept one local answer. It is not daemon commit, wire or peer delivery.
    /// Invalid/oversized replies leave the request unanswered; no truncation.
    pub fn reply(&self, status: u16, value: &[u8]) -> io::Result<()> {
        self.data.request.validate_reply(status, value)?;
        let mut s = self
            .queue
            .state
            .lock()
            .map_err(|_| io_error(nix::libc::EIO))?;
        self.check(&s)?;
        let sender = s
            .pending
            .as_mut()
            .and_then(|p| p.reply.take())
            .ok_or_else(|| io_error(nix::libc::ESTALE))?;
        sender
            .send((status, value.to_vec()))
            .map_err(|_| io_error(nix::libc::ESTALE))
    }
}
impl Drop for RequestCore {
    fn drop(&mut self) {
        let mut s = self.queue.state.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(p) = s.pending.as_mut()
            && p.data.token == self.data.token
        {
            p.released = true;
            p.reply.take();
            if p.done {
                s.pending = None;
            }
        }
    }
}

/// Typed READ inbox over the shared capacity/stop/drain implementation.
pub struct Inbox {
    core: InboxCore,
}
impl Inbox {
    pub fn close(&self) {
        self.core.close()
    }
    pub fn fd(&self) -> io::Result<OwnedFd> {
        self.core.fd()
    }
    pub fn try_next(&self) -> io::Result<Request> {
        self.core.try_next().map(|core| Request { core })
    }
    pub async fn next(&self) -> io::Result<Request> {
        self.core.next().await.map(|core| Request { core })
    }
}
/// Typed WRITE inbox. Closing never rolls back an application effect or
/// withdraws its remote service. Notification fd duplicates convey readiness only.
pub struct WriteInbox {
    core: InboxCore,
}
impl WriteInbox {
    pub fn close(&self) {
        self.core.close()
    }
    pub fn fd(&self) -> io::Result<OwnedFd> {
        self.core.fd()
    }
    pub fn try_next(&self) -> io::Result<WriteRequest> {
        self.core.try_next().map(|core| WriteRequest { core })
    }
    pub async fn next(&self) -> io::Result<WriteRequest> {
        self.core.next().await.map(|core| WriteRequest { core })
    }
}
/// Original READ observation and one-shot local response capability.
pub struct Request {
    core: RequestCore,
}
impl Request {
    pub fn request(&self) -> &ReadProviderRequest {
        match &self.core.data.request {
            RequestData::Read(r) => r,
            _ => unreachable!("typed read inbox"),
        }
    }
    pub fn token(&self) -> u64 {
        self.core.token()
    }
    pub fn is_active(&self) -> bool {
        self.core.is_active()
    }
    pub fn reply(&self, status: u16, value: &[u8]) -> io::Result<()> {
        self.core.reply(status, value)
    }
}
/// Original WRITE observation and one-shot local response capability. Calling
/// reply accepts a local application result; it is not wire delivery or rollback.
pub struct WriteRequest {
    core: RequestCore,
}
impl WriteRequest {
    pub fn request(&self) -> &WriteProviderRequest {
        match &self.core.data.request {
            RequestData::Write(r) => r,
            _ => unreachable!("typed write inbox"),
        }
    }
    pub fn token(&self) -> u64 {
        self.core.token()
    }
    pub fn is_active(&self) -> bool {
        self.core.is_active()
    }
    /// Invalid status/oversize/mismatched accepted bytes leave reply authority
    /// unconsumed. Original expiry/revocation can still refuse a later answer.
    pub fn reply(&self, status: u16, accepted: &[u8]) -> io::Result<()> {
        self.core.reply(status, accepted)
    }
}
