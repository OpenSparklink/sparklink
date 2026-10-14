//! Read-only capabilities of an already delegated logical-channel socket.
//! Successful metadata is coherent at kernel admission, not future connectivity
//! or controller completion. No management lease is revealed or acquired.
use std::{io, os::fd::RawFd};

#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleChannelInfo {
    pub version: u16,
    pub size: u16,
    pub controller: u16,
    pub handle: u16,
    pub generation: u64,
    pub lifetime: u64,
    pub mtu: u16,
    pub mps: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub mode: u8,
    pub directions: u32,
    pub reserved: u32,
}
const _: () = assert!(std::mem::size_of::<SleChannelInfo>() == 40);

nix::ioctl_read!(sl_channel_info, b'S', 0xe0, SleChannelInfo);

/// cbindgen:ignore
impl SleChannelInfo {
    pub fn validate(&self) -> io::Result<()> {
        let key = (self.local_tcid, self.remote_tcid, self.pi);
        if self.version != 1
            || self.size != 40
            || self.reserved != 0
            || self.generation == 0
            || self.lifetime == 0
            || self.mtu == 0
            || self.mps == 0
            || self.mode != 0
            || self.directions == 0
            || self.directions & !3 != 0
            || !matches!(key, (31, 31, 241) | (10, 10, 0))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid channel capability snapshot",
            ));
        }
        Ok(())
    }
}

pub fn query(fd: RawFd) -> io::Result<SleChannelInfo> {
    let mut info = SleChannelInfo::default();
    // SAFETY: complete writable local ABI object, kept alive for the syscall.
    unsafe { sl_channel_info(fd, &mut info) }
        .map_err(|error| io::Error::from_raw_os_error(error as i32))?;
    info.validate()?;
    Ok(info)
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
            mps: 249,
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
        assert_eq!(
            query(-1).unwrap_err().raw_os_error(),
            Some(nix::libc::EBADF)
        );
    }
}

/// Read-only coherent software queue and native controller reservation state.
/// Peak includes rolled-back reservations; it does not mean USB or peer delivery.
#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleChannelTxStatus {
    pub version: u16,
    pub size: u16,
    pub controller: u16,
    pub handle: u16,
    pub generation: u64,
    pub lifetime: u64,
    pub packet_maximum: u16,
    pub capacity: u16,
    pub outstanding: u16,
    pub connection_debt: u16,
    pub peak_reserved: u16,
    pub queued: u16,
    pub queue_limit: u16,
    pub busy: u16,
    pub active_pdu_bytes: u32,
    pub active_pdu_offset: u32,
    pub flags: u32,
    pub reserved: u32,
    pub pool_exhaustions: u64,
}
const _: () = assert!(std::mem::size_of::<SleChannelTxStatus>() == 64);
nix::ioctl_read!(sl_channel_tx_status, b'S', 0xe1, SleChannelTxStatus);

/// cbindgen:ignore
impl SleChannelTxStatus {
    pub fn validate(&self) -> io::Result<()> {
        if self.version != 1
            || self.size != 64
            || self.generation == 0
            || self.lifetime == 0
            || self.packet_maximum == 0
            || self.packet_maximum > 2047
            || self.capacity == 0
            || self.capacity > 255
            || self.outstanding > self.capacity
            || self.connection_debt > self.outstanding
            || self.peak_reserved < self.outstanding
            || self.peak_reserved > self.capacity
            || self.queue_limit != 8
            || self.busy > 1
            || u32::from(self.queued) + u32::from(self.busy) > u32::from(self.queue_limit)
            || self.flags & !3 != 0
            || self.reserved != 0
            || self.active_pdu_bytes > 2047
            || self.active_pdu_offset > self.active_pdu_bytes
            || (self.flags & 1 == 0
                && (self.active_pdu_bytes != 0
                    || self.active_pdu_offset != 0
                    || self.flags & 2 != 0
                    || self.busy != 0))
            || (self.flags & 1 != 0 && (self.active_pdu_bytes == 0 || self.busy != 1))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid channel TX snapshot",
            ));
        }
        Ok(())
    }
}
pub fn query_tx_status(fd: RawFd) -> io::Result<SleChannelTxStatus> {
    let mut value = SleChannelTxStatus::default();
    // SAFETY: initialized complete output object lives through synchronous ioctl.
    unsafe { sl_channel_tx_status(fd, &mut value) }
        .map_err(|e| io::Error::from_raw_os_error(e as i32))?;
    value.validate()?;
    Ok(value)
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
