use std::os::fd::{AsRawFd, OwnedFd, RawFd};

use slk_protocol::{CONTROLLER_EVENT_VERSION, SleControllerEvent, SleControllerEventQuery, ioctl};
use tokio::io::unix::AsyncFd;

use crate::{Error, Result};

/// Cursor for one independently selected registration. Reset it before
/// deliberately selecting another controller; generation mismatch fails.
#[derive(Debug, Default, Clone, Copy)]
pub struct ControllerEventCursor {
    pub after_seq: u64,
    pub generation: u64,
}

pub(crate) fn poll(
    fd: RawFd,
    cursor: &mut ControllerEventCursor,
) -> Result<Option<SleControllerEvent>> {
    // All response bytes are initialized by the kernel; the input event is
    // ignored. Zero is valid for this repr(C) integer/byte-array structure.
    let mut query = unsafe { std::mem::zeroed::<SleControllerEventQuery>() };
    query.after_seq = cursor.after_seq;
    query.generation = cursor.generation;
    query.version = CONTROLLER_EVENT_VERSION;
    match unsafe { ioctl::sl_controller_event_get(fd, &mut query) } {
        Ok(_) => {
            let event = query.event;
            if event.seq <= cursor.after_seq
                || event.generation == 0
                || query.generation != event.generation
                || (cursor.generation != 0 && event.generation != cursor.generation)
                || usize::from(event.payload_len) > event.payload.len()
                || event.flags != 0
                || event._reserved != 0
                || event.lost != event.seq - cursor.after_seq - 1
            {
                return Err(Error::InvalidParam("invalid controller event response"));
            }
            cursor.after_seq = event.seq;
            cursor.generation = event.generation;
            Ok(Some(event))
        }
        Err(nix::Error::EAGAIN) => Ok(None),
        Err(error) => Err(Error::Ioctl(error)),
    }
}

/// Complete native controller events with independent, non-destructive reads.
/// Owns its fd, requires the new kernel ioctl and uses its per-owner poll
/// wakeups. It never falls back to a destructive/truncated legacy stream.
pub struct ControllerEventReceiver {
    fd: AsyncFd<OwnedFd>,
    cursor: ControllerEventCursor,
}

impl ControllerEventReceiver {
    pub(crate) fn from_fd(fd: OwnedFd) -> Result<Self> {
        tokio::runtime::Handle::try_current()
            .map_err(|_| Error::InvalidParam("event receiver requires a Tokio I/O runtime"))?;
        // The kernel chooses its poll wait queue when epoll registers this fd.
        // Activate the native subscription first; switching it afterwards leaves
        // epoll waiting on the legacy queue and loses native event wakeups.
        // Reads are non-destructive: replay from zero on the first next_event.
        poll(fd.as_raw_fd(), &mut ControllerEventCursor::default())?;
        Ok(Self {
            fd: AsyncFd::new(fd).map_err(Error::OpenDevice)?,
            cursor: ControllerEventCursor::default(),
        })
    }

    /// Fetch a complete record; overrun is explicit in event.lost.
    pub fn try_next(&mut self) -> Result<Option<SleControllerEvent>> {
        poll(self.fd.get_ref().as_raw_fd(), &mut self.cursor)
    }

    /// Wait using the kernel's native event subscription. Cancellation keeps
    /// the cursor/fd usable; unplug is a terminal ENODEV rather than EOF data.
    pub async fn next_event(&mut self) -> Result<SleControllerEvent> {
        loop {
            if let Some(event) = self.try_next()? {
                return Ok(event);
            }
            let mut ready = self.fd.readable().await.map_err(Error::OpenDevice)?;
            ready.clear_ready();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::os::unix::net::UnixStream;

    #[tokio::test]
    async fn unsupported_transport_is_rejected_before_epoll_registration() {
        let (socket, mut peer) = UnixStream::pair().unwrap();
        peer.set_read_timeout(Some(std::time::Duration::from_secs(1)))
            .unwrap();
        assert!(matches!(
            ControllerEventReceiver::from_fd(socket.into()),
            Err(Error::Ioctl(nix::Error::ENOTTY))
        ));
        assert_eq!(peer.read(&mut [0; 1]).unwrap(), 0);
    }
}
