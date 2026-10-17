//! Kernel-supplied receipt facts, not peer identity, policy or future TX consent.
//! A caller must retain its fd throughout the syscall. Missing/truncated facts
//! fail closed; the payload may already have been consumed/copied on error.
use std::{io, mem, os::fd::RawFd};

pub const SOL_SPARKLINK: i32 = 288;
pub const SCM_RX_SECURITY: i32 = 1;
pub const MESSAGE_SECURITY_KNOWN: u8 = 1;
pub const MESSAGE_SECURITY_CURRENT: u8 = 2;

#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleMessageSecurity {
    pub version: u16,
    pub size: u16,
    pub security: u32,
    pub generation: u64,
    pub lifetime: u64,
    pub security_epoch: u64,
    pub controller: u16,
    pub handle: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub flags: u8,
}
const _: () = assert!(mem::size_of::<SleMessageSecurity>() == 40);

impl SleMessageSecurity {
    pub fn validate(&self) -> io::Result<()> {
        let dynamic = (0x80..=0xdf).contains(&self.local_tcid)
            && (0x80..=0xdf).contains(&self.remote_tcid)
            && (241..=250).contains(&self.pi);
        let fixed = matches!(
            (self.local_tcid, self.remote_tcid, self.pi),
            (10, 10, 0) | (31, 31, 241)
        );
        if self.version != 1
            || self.size != 40
            || !fixed && !dynamic
            || self.generation == 0
            || self.lifetime == 0
            || self.security > 2
            || self.flags & !3 != 0
            || self.flags & MESSAGE_SECURITY_KNOWN == 0 && (self.security != 0 || self.flags != 0)
            || self.flags & MESSAGE_SECURITY_KNOWN != 0 && self.security_epoch == 0
        {
            return Err(io::Error::from_raw_os_error(nix::libc::EPROTO));
        }
        Ok(())
    }
}

// This is the actual syscall decoder. Kernel data is checked before any typed
// result escapes; tests/fuzz use the same bounds checks, not a simplified codec.
fn decode(control: &[u64; 8], length: usize, flags: i32) -> io::Result<SleMessageSecurity> {
    let protocol_error = || io::Error::from_raw_os_error(nix::libc::EPROTO);
    if length > mem::size_of_val(control) || flags & nix::libc::MSG_CTRUNC != 0 {
        return Err(protocol_error());
    }
    if length == 0 {
        return Err(io::Error::from_raw_os_error(nix::libc::EOPNOTSUPP));
    }
    let mut offset = 0;
    let mut found = None;
    // SAFETY: initialized, aligned owned bytes; bounds checked for every read.
    let bytes = unsafe {
        std::slice::from_raw_parts(control.as_ptr().cast::<u8>(), mem::size_of_val(control))
    };
    let header_size = unsafe { nix::libc::CMSG_LEN(0) } as usize;
    while offset < length {
        if length - offset < mem::size_of::<nix::libc::cmsghdr>() {
            return Err(protocol_error());
        }
        let header = unsafe {
            bytes
                .as_ptr()
                .add(offset)
                .cast::<nix::libc::cmsghdr>()
                .read_unaligned()
        };
        let size = header.cmsg_len as usize;
        if size != header_size + 40
            || size > length - offset
            || header.cmsg_level != SOL_SPARKLINK
            || header.cmsg_type != SCM_RX_SECURITY
            || found.is_some()
        {
            return Err(protocol_error());
        }
        let value = unsafe {
            bytes
                .as_ptr()
                .add(offset + header_size)
                .cast::<SleMessageSecurity>()
                .read_unaligned()
        };
        value.validate()?;
        found = Some(value);
        let alignment = mem::size_of::<usize>();
        offset = offset
            .checked_add(
                size.checked_add(alignment - 1).ok_or_else(protocol_error)? & !(alignment - 1),
            )
            .ok_or_else(protocol_error)?;
    }
    found.ok_or_else(protocol_error)
}

/// recvmsg on an actual SparkLink fd, preserving PEEK/TRUNC/nonblocking and
/// original kernel admission rules. No management, fake context or fallback.
/// Returns (syscall count, receipt facts, msg_flags). With input MSG_TRUNC the
/// count may exceed buffer.len(); callers must not index to that count.
pub fn recv(
    fd: RawFd,
    buffer: &mut [u8],
    flags: i32,
) -> io::Result<(usize, SleMessageSecurity, i32)> {
    if flags & !(nix::libc::MSG_DONTWAIT | nix::libc::MSG_PEEK | nix::libc::MSG_TRUNC) != 0 {
        return Err(io::Error::from_raw_os_error(nix::libc::EOPNOTSUPP));
    }
    let mut domain: i32 = 0;
    let mut domain_size = mem::size_of_val(&domain) as nix::libc::socklen_t;
    // SAFETY: output pointers are live aligned locals; fd is never closed here.
    if unsafe {
        nix::libc::getsockopt(
            fd,
            nix::libc::SOL_SOCKET,
            nix::libc::SO_DOMAIN,
            (&mut domain as *mut i32).cast(),
            &mut domain_size,
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    if domain_size as usize != mem::size_of_val(&domain) || domain != 46 {
        return Err(io::Error::from_raw_os_error(nix::libc::EAFNOSUPPORT));
    }
    let mut control = [0u64; 8];
    let mut io_vec = nix::libc::iovec {
        iov_base: buffer.as_mut_ptr().cast(),
        iov_len: buffer.len(),
    };
    let mut message: nix::libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut io_vec;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: msghdr points to the exclusive live buffer and initialized control.
    let count = unsafe { nix::libc::recvmsg(fd, &mut message, flags) };
    if count < 0 {
        return Err(io::Error::last_os_error());
    }
    let context = decode(&control, message.msg_controllen, message.msg_flags)?;
    Ok((count as usize, context, message.msg_flags))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn value() -> SleMessageSecurity {
        SleMessageSecurity {
            version: 1,
            size: 40,
            security: 1,
            generation: 7,
            lifetime: 11,
            security_epoch: 2,
            controller: 1,
            handle: 3,
            local_tcid: 10,
            remote_tcid: 10,
            pi: 0,
            flags: 3,
        }
    }
    fn encoded(v: SleMessageSecurity) -> ([u64; 8], usize) {
        let mut bytes = [0u64; 8];
        let size = unsafe { nix::libc::CMSG_LEN(40) } as usize;
        let header = nix::libc::cmsghdr {
            cmsg_len: size as _,
            cmsg_level: SOL_SPARKLINK,
            cmsg_type: SCM_RX_SECURITY,
        };
        unsafe {
            bytes
                .as_mut_ptr()
                .cast::<nix::libc::cmsghdr>()
                .write(header);
            bytes
                .as_mut_ptr()
                .cast::<u8>()
                .add(nix::libc::CMSG_LEN(0) as usize)
                .cast::<SleMessageSecurity>()
                .write_unaligned(v);
        }
        (bytes, size)
    }
    #[test]
    fn actual_decoder_checks_complete_control_and_frozen_facts() {
        let v = value();
        let (c, n) = encoded(v);
        assert_eq!(decode(&c, n, 0).unwrap(), v);
        for (length, flags) in [
            (0, 0),
            (n - 1, 0),
            (n + 1, 0),
            (65, 0),
            (n, nix::libc::MSG_CTRUNC),
        ] {
            assert!(decode(&c, length, flags).is_err());
        }
        for bad in [
            SleMessageSecurity { security: 3, ..v },
            SleMessageSecurity {
                security_epoch: 0,
                ..v
            },
            SleMessageSecurity { generation: 0, ..v },
            SleMessageSecurity { flags: 2, ..v },
            SleMessageSecurity { flags: 4, ..v },
            SleMessageSecurity { flags: 0, ..v },
            SleMessageSecurity { local_tcid: 2, ..v },
            SleMessageSecurity { size: 39, ..v },
        ] {
            let (c, n) = encoded(bad);
            assert!(decode(&c, n, 0).is_err());
        }
        for v in [
            SleMessageSecurity { flags: 1, ..v },
            SleMessageSecurity {
                flags: 0,
                security: 0,
                ..v
            },
            SleMessageSecurity { security: 0, ..v },
        ] {
            let (c, n) = encoded(v);
            assert_eq!(decode(&c, n, 0).unwrap(), v);
        }
        for (level, kind) in [(1, 1), (SOL_SPARKLINK, 2)] {
            let (mut c, n) = encoded(v);
            unsafe {
                let p = c.as_mut_ptr().cast::<nix::libc::cmsghdr>();
                (*p).cmsg_level = level;
                (*p).cmsg_type = kind;
            }
            assert!(decode(&c, n, 0).is_err());
        }
    }
    #[test]
    fn cannot_treat_unix_fixture_or_invalid_fd_as_kernel_security() {
        let mut buffer = [0u8; 4];
        assert_eq!(
            recv(-1, &mut buffer, 0).unwrap_err().raw_os_error(),
            Some(nix::libc::EBADF)
        );
        use std::os::fd::AsRawFd;
        let (a, _) = std::os::unix::net::UnixDatagram::pair().unwrap();
        assert_eq!(
            recv(a.as_raw_fd(), &mut buffer, nix::libc::MSG_DONTWAIT)
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EAFNOSUPPORT)
        );
        assert_eq!(
            recv(-1, &mut buffer, nix::libc::MSG_WAITALL)
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EOPNOTSUPP)
        );
    }
}
