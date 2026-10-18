//! Operations on already-authorized channel fds. No device open, management
//! lease, protocol Engine or authority fallback. Callers retain the fd for each
//! syscall; successful software admission does not mean peer delivery.
pub use slk_protocol::{SleChannelInfo, SleChannelTxStatus, SleSessionTxStatus};
use std::{io, os::fd::RawFd};
pub mod deadline;
pub mod security;

nix::ioctl_read!(sl_channel_info, b'S', 0xe0, SleChannelInfo);

nix::ioctl_read!(sl_channel_tx_status, b'S', 0xe1, SleChannelTxStatus);

nix::ioctl_read!(sl_session_tx_status, b'S', 0xe2, SleSessionTxStatus);

pub fn query(fd: RawFd) -> io::Result<SleChannelInfo> {
    let mut info = SleChannelInfo::default();
    // SAFETY: complete writable local ABI object, kept alive for the syscall.
    unsafe { sl_channel_info(fd, &mut info) }
        .map_err(|error| io::Error::from_raw_os_error(error as i32))?;
    info.validate()?;
    Ok(info)
}

pub fn query_tx_status(fd: RawFd) -> io::Result<SleChannelTxStatus> {
    let mut value = SleChannelTxStatus::default();
    // SAFETY: initialized complete output object lives through synchronous ioctl.
    unsafe { sl_channel_tx_status(fd, &mut value) }
        .map_err(|e| io::Error::from_raw_os_error(e as i32))?;
    value.validate()?;
    Ok(value)
}

pub fn query_session_tx_status(fd: RawFd) -> io::Result<SleSessionTxStatus> {
    let mut value = SleSessionTxStatus::default();
    // SAFETY: complete initialized output object lives through this ioctl.
    unsafe { sl_session_tx_status(fd, &mut value) }
        .map_err(|e| io::Error::from_raw_os_error(e as i32))?;
    value.validate()?;
    Ok(value)
}

/// One owned fd reference. Construction checks the actual socket domain, not
/// Ready, connectivity, security or future authority. Dup shares the kernel
/// binding; only the final VFS reference triggers its cleanup contract.
#[derive(Debug)]
pub struct Channel(std::os::fd::OwnedFd);
impl Channel {
    pub fn from_owned(fd: std::os::fd::OwnedFd) -> io::Result<Self> {
        use std::os::fd::AsRawFd;
        security::check_domain(fd.as_raw_fd())?;
        Ok(Self(fd))
    }
    pub fn into_owned_fd(self) -> std::os::fd::OwnedFd {
        self.0
    }
    pub fn try_clone(&self) -> io::Result<Self> {
        Ok(Self(self.0.try_clone()?))
    }
    pub fn info(&self) -> io::Result<SleChannelInfo> {
        use std::os::fd::AsRawFd;
        query(self.0.as_raw_fd())
    }
}
impl std::os::fd::AsFd for Channel {
    fn as_fd(&self) -> std::os::fd::BorrowedFd<'_> {
        std::os::fd::AsFd::as_fd(&self.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unknown_or_mixed_capabilities_are_not_usable() {
        let info = SleChannelInfo {
            version: 1,
            size: 40,
            controller: 0,
            handle: 0,
            generation: 3,
            lifetime: 7,
            mtu: 249,
            mps: 254,
            local_tcid: 31,
            remote_tcid: 31,
            pi: 241,
            directions: 3,
            ..Default::default()
        };
        info.validate().unwrap();
        for bad in [
            SleChannelInfo { version: 2, ..info },
            SleChannelInfo { size: 39, ..info },
            SleChannelInfo {
                reserved: 1,
                ..info
            },
            SleChannelInfo {
                generation: 0,
                ..info
            },
            SleChannelInfo {
                lifetime: 0,
                ..info
            },
            SleChannelInfo { mtu: 0, ..info },
            SleChannelInfo { mps: 0, ..info },
            SleChannelInfo {
                directions: 4,
                ..info
            },
            SleChannelInfo { mode: 1, ..info },
            SleChannelInfo { pi: 0, ..info },
        ] {
            assert!(bad.validate().is_err());
        }
        SleChannelInfo {
            local_tcid: 10,
            remote_tcid: 10,
            pi: 0,
            ..info
        }
        .validate()
        .unwrap();
        SleChannelInfo {
            local_tcid: 0x83,
            remote_tcid: 0x95,
            ..info
        }
        .validate()
        .unwrap();
        for bad in [
            SleChannelInfo {
                local_tcid: 0x7f,
                remote_tcid: 0x95,
                ..info
            },
            SleChannelInfo {
                local_tcid: 0x83,
                remote_tcid: 0xe0,
                ..info
            },
            SleChannelInfo {
                local_tcid: 0x83,
                remote_tcid: 0x95,
                pi: 240,
                ..info
            },
            SleChannelInfo { mps: 253, ..info },
        ] {
            assert!(bad.validate().is_err());
        }
        assert_eq!(
            query(-1).unwrap_err().raw_os_error(),
            Some(nix::libc::EBADF)
        );
    }
}

#[cfg(test)]
mod tx_status_tests {
    use super::*;
    #[test]
    fn malformed_budget_or_queue_cannot_be_used_as_status() {
        let value = SleChannelTxStatus {
            version: 1,
            size: 64,
            generation: 1,
            lifetime: 2,
            packet_maximum: 254,
            capacity: 5,
            peak_reserved: 3,
            outstanding: 2,
            connection_debt: 1,
            queue_limit: 8,
            ..Default::default()
        };
        value.validate().unwrap();
        for bad in [
            SleChannelTxStatus { size: 63, ..value },
            SleChannelTxStatus {
                outstanding: 6,
                ..value
            },
            SleChannelTxStatus {
                connection_debt: 3,
                ..value
            },
            SleChannelTxStatus {
                peak_reserved: 1,
                ..value
            },
            SleChannelTxStatus {
                queued: u16::MAX,
                busy: 1,
                ..value
            },
            SleChannelTxStatus { flags: 2, ..value },
            SleChannelTxStatus { busy: 1, ..value },
            SleChannelTxStatus {
                reserved: 1,
                ..value
            },
        ] {
            assert!(bad.validate().is_err());
        }
        SleChannelTxStatus {
            flags: 3,
            busy: 1,
            active_pdu_bytes: 2047,
            active_pdu_offset: 254,
            ..value
        }
        .validate()
        .unwrap();
        assert_eq!(
            query_tx_status(-1).unwrap_err().raw_os_error(),
            Some(nix::libc::EBADF)
        );
    }
}

#[cfg(test)]
mod session_status_tests {
    use super::*;
    #[test]
    fn malformed_or_mixed_session_observations_are_rejected() {
        let v = SleSessionTxStatus {
            version: 1,
            size: 64,
            generation: 7,
            lifetime: 11,
            capacity: 5,
            outstanding: 2,
            connection_debt: 1,
            dynamic_allocated: 4,
            dynamic_retired: 3,
            dynamic_failed: 1,
            ..Default::default()
        };
        v.validate().unwrap();
        for bad in [
            SleSessionTxStatus { version: 0, ..v },
            SleSessionTxStatus { size: 63, ..v },
            SleSessionTxStatus { generation: 0, ..v },
            SleSessionTxStatus { lifetime: 0, ..v },
            SleSessionTxStatus {
                outstanding: 6,
                ..v
            },
            SleSessionTxStatus {
                connection_debt: 3,
                ..v
            },
            SleSessionTxStatus {
                queued: 48,
                active_pdus: 1,
                ..v
            },
            SleSessionTxStatus {
                active_pdus: 2,
                ..v
            },
            SleSessionTxStatus {
                dynamic_retired: 4,
                ..v
            },
            SleSessionTxStatus { flags: 16, ..v },
            SleSessionTxStatus {
                reserved: [0, 1],
                ..v
            },
        ] {
            assert!(bad.validate().is_err());
        }
        assert_eq!(
            query_session_tx_status(-1).unwrap_err().raw_os_error(),
            Some(nix::libc::EBADF)
        );
    }
}
