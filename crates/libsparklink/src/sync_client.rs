//! Synchronous language boundary over the existing asynchronous Client.
//! One bounded executor per caller, no Host, lease, protocol or retry state.
use crate::{ApplicationError, Client};
use std::{
    future::Future,
    pin::Pin,
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

const QUEUED: usize = 8;
type Job = Box<dyn FnOnce(Client) -> Pin<Box<dyn Future<Output = ()> + Send>> + Send>;
type Result<T> = std::result::Result<T, i32>;

#[derive(Clone, Copy)]
pub(crate) struct Deadline(Instant, u64);
impl Deadline {
    pub(crate) fn from_monotonic_ns(value: u64) -> Result<Self> {
        slk_channel::deadline::local_instant_from_monotonic_ns(value)
            .map(|at| Self(at, value))
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))
    }
    fn remaining(self) -> Result<Duration> {
        slk_channel::deadline::remaining(self.0)
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))
    }
    pub(crate) fn protocol(self) -> Result<slk_channel::deadline::Deadline> {
        // Capture the existing protocol ceiling before entering the local queue.
        slk_channel::deadline::Deadline::from_monotonic_ns(self.1)
            .and_then(|deadline| deadline.capped(slk_channel::deadline::PROTOCOL_WAIT))
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))
    }
}

pub(crate) fn errno(error: ApplicationError) -> i32 {
    match error {
        ApplicationError::Invalid(_) => nix::libc::EINVAL,
        ApplicationError::Identity(_) => nix::libc::ESTALE,
        ApplicationError::Io(e) => e.raw_os_error().unwrap_or(nix::libc::EIO),
        ApplicationError::Bus(zbus::Error::MethodError(name, _, _)) => match name.as_str() {
            "org.freedesktop.DBus.Error.AccessDenied" | "org.freedesktop.DBus.Error.AuthFailed" => {
                nix::libc::EACCES
            }
            "org.freedesktop.DBus.Error.ServiceUnknown"
            | "org.freedesktop.DBus.Error.NameHasNoOwner" => nix::libc::ENOTCONN,
            "org.freedesktop.DBus.Error.UnknownObject" => nix::libc::ENOENT,
            "org.freedesktop.DBus.Error.NotSupported" => nix::libc::EOPNOTSUPP,
            "org.freedesktop.DBus.Error.InvalidArgs" => nix::libc::EINVAL,
            "org.freedesktop.DBus.Error.NoReply"
            | "org.freedesktop.DBus.Error.Timeout"
            | "org.freedesktop.DBus.Error.TimedOut" => nix::libc::ETIMEDOUT,
            "org.freedesktop.DBus.Error.LimitsExceeded" => nix::libc::ENOBUFS,
            _ => nix::libc::EIO,
        },
        ApplicationError::Bus(_) => nix::libc::EIO,
    }
}

pub(crate) struct SyncClient {
    sender: Option<tokio::sync::mpsc::Sender<Job>>,
    worker: Option<thread::JoinHandle<()>>,
}
impl SyncClient {
    pub(crate) fn open_system(deadline: Deadline) -> Result<Self> {
        Self::start(deadline, Client::open_system)
    }
    fn start<F, Fut>(deadline: Deadline, connect: F) -> Result<Self>
    where
        F: FnOnce() -> Fut + Send + 'static,
        Fut: Future<Output = std::result::Result<Client, ApplicationError>> + Send + 'static,
    {
        deadline.remaining()?;
        let (sender, mut receiver) = tokio::sync::mpsc::channel::<Job>(QUEUED);
        let (ready, result) = mpsc::sync_channel(1);
        let worker = thread::Builder::new()
            .name("slk-app-client".into())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(e) => {
                        let _ = ready.try_send(Err(e.raw_os_error().unwrap_or(nix::libc::EIO)));
                        return;
                    }
                };
                runtime.block_on(async move {
                    if deadline.remaining().is_err() {
                        let _ = ready.try_send(Err(nix::libc::ETIMEDOUT));
                        return;
                    }
                    let client = match tokio::time::timeout_at(deadline.0.into(), connect()).await {
                        Ok(Ok(client)) if deadline.remaining().is_ok() => client,
                        Ok(Err(e)) => {
                            let _ = ready.try_send(Err(errno(e)));
                            return;
                        }
                        _ => {
                            let _ = ready.try_send(Err(nix::libc::ETIMEDOUT));
                            return;
                        }
                    };
                    if ready.try_send(Ok(())).is_err() {
                        return;
                    }
                    while let Some(job) = receiver.recv().await {
                        job(client.clone()).await;
                    }
                });
                // Runtime and its owner watcher are dropped on their own thread.
            })
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EAGAIN))?;
        let handle = Self {
            sender: Some(sender),
            worker: Some(worker),
        };
        let status = result
            .recv_timeout(deadline.remaining()?)
            .map_err(|e| match e {
                mpsc::RecvTimeoutError::Timeout => nix::libc::ETIMEDOUT,
                mpsc::RecvTimeoutError::Disconnected => nix::libc::EPIPE,
            })?;
        status?;
        deadline.remaining()?;
        Ok(handle)
    }
    pub(crate) fn call<T, F, Fut>(&self, deadline: Deadline, operation: F) -> Result<T>
    where
        T: Send + 'static,
        F: FnOnce(Client) -> Fut + Send + 'static,
        Fut: Future<Output = std::result::Result<T, ApplicationError>> + Send + 'static,
    {
        deadline.remaining()?;
        let (reply, response) = mpsc::sync_channel(1);
        let job: Job = Box::new(move |client| {
            Box::pin(async move {
                // timeout_at polls an already-expired future once: explicitly refuse
                // stale queued work before invoking any production broker operation.
                if deadline.remaining().is_err() {
                    let _ = reply.try_send(Err(nix::libc::ETIMEDOUT));
                    return;
                }
                let result =
                    match tokio::time::timeout_at(deadline.0.into(), operation(client)).await {
                        Ok(value) if deadline.remaining().is_ok() => value.map_err(errno),
                        _ => Err(nix::libc::ETIMEDOUT),
                    };
                // A timed-out caller cannot leave an unclaimed fd/response alive.
                let _ = reply.try_send(result);
            })
        });
        self.sender
            .as_ref()
            .ok_or(nix::libc::EPIPE)?
            .try_send(job)
            .map_err(|e| match e {
                tokio::sync::mpsc::error::TrySendError::Full(_) => nix::libc::EAGAIN,
                tokio::sync::mpsc::error::TrySendError::Closed(_) => nix::libc::EPIPE,
            })?;
        let result = response
            .recv_timeout(deadline.remaining()?)
            .map_err(|e| match e {
                mpsc::RecvTimeoutError::Timeout => nix::libc::ETIMEDOUT,
                mpsc::RecvTimeoutError::Disconnected => nix::libc::EPIPE,
            })?;
        deadline.remaining()?;
        result
    }
}
impl Drop for SyncClient {
    fn drop(&mut self) {
        self.sender.take();
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

#[cfg(test)]
mod tests;
