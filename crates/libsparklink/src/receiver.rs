use std::os::fd::{AsRawFd, OwnedFd, RawFd};

use slk_protocol::{SleDliEvent, ioctl};
use tokio::io::unix::AsyncFd;

use crate::{Error, Event, Result, adapter::decode_event};

/// Single event consumer owning an fd independently of management state.
///
/// Drop deregisters readiness and closes the fd; cancelling `next_event` leaves
/// it usable. This is a legacy receiver, not the future fan-out subscription:
/// multiple legacy consumers still compete for the kernel DLI ring. The 50ms
/// fallback remains until the kernel reliably wakes event subscribers.
pub struct EventReceiver {
    fd: AsyncFd<OwnedFd>,
}

impl EventReceiver {
    pub(crate) fn from_fd(fd: OwnedFd) -> Result<Self> {
        tokio::runtime::Handle::try_current()
            .map_err(|_| Error::InvalidParam("event receiver requires a Tokio I/O runtime"))?;
        Ok(Self {
            fd: AsyncFd::new(fd).map_err(Error::OpenDevice)?,
        })
    }

    /// Wait without borrowing or locking an AdapterState.
    pub async fn next_event(&mut self) -> Result<Event> {
        loop {
            if let Some(raw) = poll_event(self.fd.get_ref().as_raw_fd())? {
                return decode_event(raw);
            }
            match tokio::time::timeout(std::time::Duration::from_millis(50), self.fd.readable())
                .await
            {
                Ok(Ok(mut ready)) => ready.clear_ready(),
                Ok(Err(error)) => return Err(Error::OpenDevice(error)),
                Err(_) => {}
            }
        }
    }
}

pub(crate) fn poll_event(fd: RawFd) -> Result<Option<SleDliEvent>> {
    let mut event = unsafe { std::mem::zeroed::<SleDliEvent>() };
    match unsafe { ioctl::sl_dli_poll_event(fd, &mut event) } {
        Ok(_) => Ok(Some(event)),
        Err(nix::Error::EAGAIN) => Ok(None),
        Err(error) => Err(Error::Ioctl(error)),
    }
}

#[cfg(test)]
mod tests {
    use std::io::Read;
    use std::os::unix::net::UnixStream;

    use super::*;

    #[tokio::test]
    async fn dropping_receiver_closes_owned_transport() {
        let (transport, mut peer) = UnixStream::pair().unwrap();
        peer.set_read_timeout(Some(std::time::Duration::from_secs(1)))
            .unwrap();
        let receiver = EventReceiver::from_fd(transport.into()).unwrap();
        drop(receiver);
        assert_eq!(peer.read(&mut [0u8; 1]).unwrap(), 0);
    }
}
