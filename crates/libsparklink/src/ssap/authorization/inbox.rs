//! Language-frontend policy inbox. Not an SSAP Engine/database or Native grant.
//! Registry lock is released before Queue lock; no lock spans an await. A slot
//! remains charged through callback drain and the delivered request's release.
use super::{AuthorizationContext, admit, await_decision, check_sender};
use crate::{ApplicationError, Client};
use slk_contract::ControllerId;
use slk_contract::ssap::SsapAuthorizationPrompt as Prompt;
use slk_protocol::{SsapOperations, ssap::access::SsapAccess};
use std::{
    os::fd::{AsRawFd, FromRawFd, OwnedFd},
    sync::{Arc, Mutex, Weak},
    time::Instant,
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore, oneshot, watch};

pub(crate) const PATH: &str = "/org/sparklink/sdk/ssap_authorizer";
type Result<T> = std::result::Result<T, i32>;
struct Registry {
    closed: bool,
    entries: Vec<Weak<Queue>>,
}
pub(crate) struct Dispatcher {
    daemon: String,
    lost: watch::Receiver<bool>,
    slots: Arc<Semaphore>,
    registry: Mutex<Registry>,
}
struct Endpoint(Arc<Dispatcher>);
#[zbus::interface(name = "org.sparklink.SsapAuthorizer")]
impl Endpoint {
    async fn authorize_value(
        &self,
        prompt: Prompt,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        let sender = header.sender().map(|n| n.as_str());
        check_sender(&self.0.daemon, sender)?;
        let queues = {
            let r = self
                .0
                .registry
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("authorizer registry poisoned".into()))?;
            if r.closed {
                return Ok(false);
            }
            r.entries
                .iter()
                .filter_map(Weak::upgrade)
                .collect::<Vec<_>>()
        };
        let mut selected = None;
        for queue in queues {
            if queue.matches(&prompt) {
                if selected.is_some() {
                    return Ok(false);
                } // Ambiguous receipts never choose first.
                selected = Some(queue);
            }
        }
        match selected {
            Some(queue) => queue.authorize(prompt, sender).await,
            None => Ok(false),
        }
    }
}
impl Dispatcher {
    pub(crate) async fn install(
        client: &Client,
    ) -> std::result::Result<Arc<Self>, ApplicationError> {
        let d = Arc::new(Self {
            daemon: client.daemon_owner().into(),
            lost: client.owner_loss(),
            slots: Arc::new(Semaphore::new(16)),
            registry: Mutex::new(Registry {
                closed: false,
                entries: Vec::new(),
            }),
        });
        if !client
            .bus()
            .object_server()
            .at(PATH, Endpoint(d.clone()))
            .await?
        {
            return Err(ApplicationError::Invalid(
                "caller SDK authorizer path already occupied",
            ));
        }
        Ok(d)
    }
    pub(crate) fn watch(self: &Arc<Self>) -> Watch {
        let mut lost = self.lost.clone();
        let close = CloseOnExit(Arc::downgrade(self));
        let task = tokio::spawn(async move {
            let _close = close; // Captured before spawn, including abort-before-first-poll.
            if !*lost.borrow() {
                let _ = lost.changed().await;
            }
        });
        Watch {
            dispatcher: self.clone(),
            task,
        }
    }
    pub(crate) fn reserve(
        &self,
        controller: ControllerId,
        properties: &[(SsapOperations, SsapAccess)],
    ) -> Result<Arc<Queue>> {
        if !(1..=64).contains(&properties.len()) {
            return Err(nix::libc::EINVAL);
        }
        let permit = self
            .slots
            .clone()
            .try_acquire_owned()
            .map_err(|_| nix::libc::EAGAIN)?;
        // SAFETY: creates a private nonblocking CLOEXEC eventfd, never a device.
        let fd = unsafe { nix::libc::eventfd(0, nix::libc::EFD_CLOEXEC | nix::libc::EFD_NONBLOCK) };
        if fd < 0 {
            return Err(std::io::Error::last_os_error()
                .raw_os_error()
                .unwrap_or(nix::libc::EIO));
        }
        let queue = Arc::new(Queue {
            controller,
            daemon: self.daemon.clone(),
            lost: self.lost.clone(),
            properties: properties.to_vec(),
            event: unsafe { OwnedFd::from_raw_fd(fd) },
            _permit: permit,
            state: Mutex::new(State {
                binding: Binding::Pending,
                pending: None,
                next_token: 0,
                signaled: false,
            }),
        });
        let mut r = self.registry.lock().map_err(|_| nix::libc::EIO)?;
        if r.closed || *self.lost.borrow() || self.lost.has_changed().is_err() {
            return Err(nix::libc::ESTALE);
        }
        r.entries.retain(|q| q.strong_count() != 0);
        r.entries.push(Arc::downgrade(&queue));
        Ok(queue)
    }
    fn stop(&self) {
        let queues = {
            let mut r = self.registry.lock().unwrap_or_else(|e| e.into_inner());
            r.closed = true;
            r.entries
                .iter()
                .filter_map(Weak::upgrade)
                .collect::<Vec<_>>()
        };
        for queue in queues {
            queue.stop();
        }
    }
}
pub(crate) struct Watch {
    dispatcher: Arc<Dispatcher>,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Watch {
    fn drop(&mut self) {
        self.dispatcher.stop();
        self.task.abort();
    }
}
struct CloseOnExit(Weak<Dispatcher>);
impl Drop for CloseOnExit {
    fn drop(&mut self) {
        if let Some(d) = self.0.upgrade() {
            d.stop();
        }
    }
}

enum Binding {
    Pending,
    Bound(Vec<u16>),
    Closed,
}
struct State {
    binding: Binding,
    pending: Option<Pending>,
    next_token: u64,
    signaled: bool,
}
struct Data {
    token: u64,
    prompt: Prompt,
    original: Instant,
}
struct Pending {
    data: Arc<Data>,
    reply: Option<oneshot::Sender<bool>>,
    delivered: bool,
    released: bool,
    done: bool,
}
pub(crate) struct Queue {
    controller: ControllerId,
    daemon: String,
    lost: watch::Receiver<bool>,
    properties: Vec<(SsapOperations, SsapAccess)>,
    event: OwnedFd,
    _permit: OwnedSemaphorePermit,
    state: Mutex<State>,
}
impl Queue {
    pub(crate) fn bind(&self, handles: &[u16]) -> Result<()> {
        let mut s = self.state.lock().map_err(|_| nix::libc::EIO)?;
        if !matches!(s.binding, Binding::Pending) || handles.len() != self.properties.len() {
            return Err(nix::libc::ESTALE);
        }
        s.binding = Binding::Bound(handles.to_vec());
        Ok(())
    }
    fn context<'a>(&'a self, s: &State, p: &Prompt) -> Option<AuthorizationContext<'a>> {
        let position = match &s.binding {
            Binding::Bound(h) => h.iter().position(|v| *v == p.2),
            _ => None,
        };
        let (operations, access) = self.properties[position?];
        Some(AuthorizationContext {
            daemon_owner: &self.daemon,
            owner_lost: *self.lost.borrow() || self.lost.has_changed().is_err(),
            controller: self.controller,
            property: Some(p.2),
            operations,
            access,
        })
    }
    fn matches(&self, p: &Prompt) -> bool {
        if (p.1.0, p.1.1) != (self.controller.index, self.controller.generation) {
            return false;
        }
        self.state.lock().is_ok_and(|s| match &s.binding {
            Binding::Bound(h) => h.contains(&p.2),
            _ => false,
        })
    }
    fn notify(&self, s: &mut State, ready: bool) -> Result<()> {
        if s.signaled == ready {
            return Ok(());
        }
        let mut value = 1u64;
        // SAFETY: exactly one initialized u64; private owned nonblocking fd.
        let n = unsafe {
            if ready {
                nix::libc::write(self.event.as_raw_fd(), (&value as *const u64).cast(), 8)
            } else {
                nix::libc::read(self.event.as_raw_fd(), (&mut value as *mut u64).cast(), 8)
            }
        };
        if n != 8 {
            let error = std::io::Error::last_os_error()
                .raw_os_error()
                .unwrap_or(nix::libc::EIO);
            if n >= 0 || error != nix::libc::EAGAIN {
                return Err(error);
            }
        }
        s.signaled = ready;
        Ok(())
    }
    pub(crate) fn stop(&self) {
        let mut s = self.state.lock().unwrap_or_else(|e| e.into_inner());
        s.binding = Binding::Closed;
        if let Some(p) = s.pending.as_mut()
            && let Some(reply) = p.reply.take()
        {
            let _ = reply.send(false);
        }
        let _ = self.notify(&mut s, true);
    }
    pub(crate) fn fd(&self) -> Result<OwnedFd> {
        self.event
            .try_clone()
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))
    }
    async fn authorize(
        self: &Arc<Self>,
        prompt: Prompt,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<bool> {
        let (data, result) = {
            let mut s = self
                .state
                .lock()
                .map_err(|_| zbus::fdo::Error::Failed("policy inbox poisoned".into()))?;
            let Some(context) = self.context(&s, &prompt) else {
                return Ok(false);
            };
            let Some(original) = admit(&context, sender, &prompt)? else {
                return Ok(false);
            };
            if s.pending.is_some() {
                return Ok(false);
            }
            let Some(token) = s.next_token.checked_add(1) else {
                return Ok(false);
            };
            s.next_token = token;
            let (reply, result) = oneshot::channel();
            let data = Arc::new(Data {
                token,
                prompt,
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
                s.binding = Binding::Closed;
                return Err(zbus::fdo::Error::Failed(
                    "policy notification failed".into(),
                ));
            }
            (data, result)
        };
        let _drain = Callback {
            queue: self.clone(),
            token: data.token,
        };
        let approved = await_decision(result, self.lost.clone(), data.original).await;
        let s = self
            .state
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("policy inbox poisoned".into()))?;
        let Some(context) = self.context(&s, &data.prompt) else {
            return Ok(false);
        };
        Ok(approved && admit(&context, sender, &data.prompt)?.is_some())
    }
    pub(crate) fn next(self: &Arc<Self>) -> Result<Request> {
        let mut s = self.state.lock().map_err(|_| nix::libc::EIO)?;
        if *self.lost.borrow() || self.lost.has_changed().is_err() {
            drop(s);
            self.stop();
            return Err(nix::libc::ESTALE);
        }
        if matches!(s.binding, Binding::Closed) {
            return Err(nix::libc::ESHUTDOWN);
        }
        let p = s.pending.as_mut().ok_or(nix::libc::EAGAIN)?;
        if p.delivered || p.done {
            return Err(nix::libc::EAGAIN);
        }
        if p.data.original <= Instant::now() || p.reply.as_ref().is_none_or(|r| r.is_closed()) {
            p.delivered = true;
            p.released = true;
            p.reply.take();
            self.notify(&mut s, false)?;
            return Err(nix::libc::ETIMEDOUT);
        }
        p.delivered = true;
        let data = p.data.clone();
        if let Err(error) = self.notify(&mut s, false) {
            if let Some(p) = s.pending.as_mut() {
                p.released = true;
                p.reply.take();
            }
            s.binding = Binding::Closed;
            return Err(error);
        }
        Ok(Request {
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
        let ready = matches!(s.binding, Binding::Closed);
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
pub(crate) struct Request {
    queue: Arc<Queue>,
    data: Arc<Data>,
}
impl Request {
    pub(crate) fn prompt(&self) -> &Prompt {
        &self.data.prompt
    }
    pub(crate) fn token(&self) -> u64 {
        self.data.token
    }
    pub(crate) fn reply(&self, approved: bool) -> Result<()> {
        let mut s = self.queue.state.lock().map_err(|_| nix::libc::EIO)?;
        if *self.queue.lost.borrow() || self.queue.lost.has_changed().is_err() {
            drop(s);
            self.queue.stop();
            return Err(nix::libc::ESTALE);
        }
        if matches!(s.binding, Binding::Closed) {
            return Err(nix::libc::ESHUTDOWN);
        }
        if self.data.original <= Instant::now() {
            return Err(nix::libc::ETIMEDOUT);
        }
        let context = self
            .queue
            .context(&s, &self.data.prompt)
            .ok_or(nix::libc::ESTALE)?;
        if admit(&context, Some(&self.queue.daemon), &self.data.prompt)
            .ok()
            .flatten()
            .is_none()
        {
            return Err(nix::libc::ESTALE);
        }
        let p = s
            .pending
            .as_mut()
            .filter(|p| p.data.token == self.data.token && p.delivered && !p.done)
            .ok_or(nix::libc::ESTALE)?;
        let reply = p.reply.take().ok_or(nix::libc::ESTALE)?;
        reply.send(approved).map_err(|_| nix::libc::ESTALE)
    }
}
impl Drop for Request {
    fn drop(&mut self) {
        let mut s = self.queue.state.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(p) = s.pending.as_mut()
            && p.data.token == self.data.token
        {
            p.released = true;
            if let Some(reply) = p.reply.take() {
                let _ = reply.send(false);
            }
            if p.done {
                s.pending = None;
            }
        }
    }
}
