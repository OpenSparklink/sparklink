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
