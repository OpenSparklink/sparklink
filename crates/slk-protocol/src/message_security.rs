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

/// A restriction of an existing fd Grant, never a replacement authority.
#[repr(C, align(8))]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct SleSendConstraint {
    pub version: u16,
    pub size: u16,
    pub minimum: u32,
    pub generation: u64,
    pub lifetime: u64,
    pub security_epoch: u64,
    pub controller: u16,
    pub handle: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub reserved: u8,
    pub deadline_monotonic_ns: u64,
}
pub const SCM_TX_CONSTRAINT: i32 = 2;
const _: () = assert!(mem::size_of::<SleSendConstraint>() == 48);
impl SleSendConstraint {
    pub fn validate(&self) -> io::Result<()> {
        if self.version != 1
            || self.size != 48
            || self.minimum > 2
            || self.reserved != 0
            || self.generation == 0
            || self.lifetime == 0
            || self.security_epoch == 0
            || self.deadline_monotonic_ns == 0
        {
            return Err(io::Error::from_raw_os_error(nix::libc::EINVAL));
        }
        Ok(())
    }
    /// Pins the original receipt epoch. Final kernel submission must still
    /// satisfy both this restriction and the original fd Grant.
    pub fn from_receipt(
        m: SleMessageSecurity,
        minimum: u32,
        deadline_monotonic_ns: u64,
    ) -> io::Result<Self> {
        m.validate()?;
        if m.flags != (MESSAGE_SECURITY_KNOWN | MESSAGE_SECURITY_CURRENT) || minimum > m.security {
            return Err(io::Error::from_raw_os_error(nix::libc::EACCES));
        }
        let c = Self {
            version: 1,
            size: 48,
            minimum,
            generation: m.generation,
            lifetime: m.lifetime,
            security_epoch: m.security_epoch,
            controller: m.controller,
            handle: m.handle,
            local_tcid: m.local_tcid,
            remote_tcid: m.remote_tcid,
            pi: m.pi,
            reserved: 0,
            deadline_monotonic_ns,
        };
        c.validate()?;
        Ok(c)
    }
}

/// Convert once from a local original Instant into the kernel CLOCK_MONOTONIC
/// domain. Sampling before computing remaining time avoids extending the budget.
/// The first TX constraint slice accepts at most five seconds remaining.
pub fn deadline_at(deadline: std::time::Instant) -> io::Result<u64> {
    let mut now: nix::libc::timespec = unsafe { mem::zeroed() };
    if unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_MONOTONIC, &mut now) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let left = deadline.saturating_duration_since(std::time::Instant::now());
    if left.is_zero() {
        return Err(io::Error::from_raw_os_error(nix::libc::ETIMEDOUT));
    }
    if left > std::time::Duration::from_secs(5)
        || now.tv_sec < 0
        || !(0..1_000_000_000).contains(&now.tv_nsec)
    {
        return Err(io::Error::from_raw_os_error(nix::libc::EINVAL));
    }
    (now.tv_sec as u64)
        .checked_mul(1_000_000_000)
        .and_then(|v| v.checked_add(now.tv_nsec as u64))
        .and_then(|v| v.checked_add(left.as_nanos().try_into().ok()?))
        .ok_or_else(|| io::Error::from_raw_os_error(nix::libc::EOVERFLOW))
}

nix::ioctl_readwrite!(sl_channel_prepare_tx, b'S', 0xe3, SleSendConstraint);
/// Snapshot a restriction through the existing TX fd, without renewing its
/// Grant or reserving credit. It must still accompany the actual sendmsg.
pub fn prepare(
    fd: RawFd,
    minimum: u32,
    deadline_monotonic_ns: u64,
) -> io::Result<SleSendConstraint> {
    if minimum > 2 || deadline_monotonic_ns == 0 {
        return Err(io::Error::from_raw_os_error(nix::libc::EINVAL));
    }
    check_domain(fd)?;
    let mut c = SleSendConstraint {
        version: 1,
        size: 48,
        minimum,
        deadline_monotonic_ns,
        ..Default::default()
    };
    unsafe { sl_channel_prepare_tx(fd, &mut c) }
        .map_err(|e| io::Error::from_raw_os_error(e as i32))?;
    c.validate()?;
    if c.minimum != minimum || c.deadline_monotonic_ns != deadline_monotonic_ns {
        return Err(io::Error::from_raw_os_error(nix::libc::EPROTO));
    }
    Ok(c)
}

/// Software admission with an explicit restrictive intent. No credit refund,
/// current-security promise after return, controller or peer completion.
pub fn send(
    fd: RawFd,
    bytes: &[u8],
    flags: i32,
    constraint: &SleSendConstraint,
) -> io::Result<usize> {
    constraint.validate()?;
    if flags & !(nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL) != 0 {
        return Err(io::Error::from_raw_os_error(nix::libc::EOPNOTSUPP));
    }
    check_domain(fd)?;
    let mut control = [0u64; 8];
    // SAFETY: aligned live buffers contain complete initialized header/payload.
    unsafe {
        control
            .as_mut_ptr()
            .cast::<nix::libc::cmsghdr>()
            .write(nix::libc::cmsghdr {
                cmsg_len: nix::libc::CMSG_LEN(48) as _,
                cmsg_level: SOL_SPARKLINK,
                cmsg_type: SCM_TX_CONSTRAINT,
            });
        control
            .as_mut_ptr()
            .cast::<u8>()
            .add(nix::libc::CMSG_LEN(0) as usize)
            .cast::<SleSendConstraint>()
            .write_unaligned(*constraint);
    }
    let mut io_vec = nix::libc::iovec {
        iov_base: bytes.as_ptr().cast_mut().cast(),
        iov_len: bytes.len(),
    };
    let mut message: nix::libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut io_vec;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = unsafe { nix::libc::CMSG_SPACE(48) } as _;
    // SAFETY: kernel only reads immutable payload, complete ancillary and msghdr.
    let count = unsafe { nix::libc::sendmsg(fd, &message, flags) };
    if count < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(count as usize)
    }
}

fn check_domain(fd: RawFd) -> io::Result<()> {
    let mut domain: i32 = 0;
    let mut domain_size = mem::size_of_val(&domain) as nix::libc::socklen_t;
    // SAFETY: live aligned output locals, caller retains fd through the syscall.
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
    Ok(())
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
    check_domain(fd)?;
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
    fn actual_constraint_constructor_and_syscall_fail_closed() {
        let m = value();
        let c = SleSendConstraint::from_receipt(m, 1, 123).unwrap();
        assert_eq!(mem::size_of_val(&c), 48);
        assert_eq!(c.security_epoch, m.security_epoch);
        assert!(
            SleSendConstraint::from_receipt(SleMessageSecurity { flags: 1, ..m }, 1, 123).is_err()
        );
        assert!(SleSendConstraint::from_receipt(m, 2, 123).is_err());
        assert!(SleSendConstraint::from_receipt(m, 1, 0).is_err());
        for bad in [
            SleSendConstraint { minimum: 3, ..c },
            SleSendConstraint { reserved: 1, ..c },
            SleSendConstraint { size: 40, ..c },
            SleSendConstraint {
                security_epoch: 0,
                ..c
            },
        ] {
            assert!(bad.validate().is_err());
        }
        assert_eq!(
            send(-1, b"x", 0, &c).unwrap_err().raw_os_error(),
            Some(nix::libc::EBADF)
        );
        assert_eq!(
            send(-1, b"x", nix::libc::MSG_WAITALL, &c)
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EOPNOTSUPP)
        );
        let unix = std::os::unix::net::UnixDatagram::unbound().unwrap();
        use std::os::fd::AsRawFd;
        assert_eq!(
            send(unix.as_raw_fd(), b"x", 0, &c)
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EAFNOSUPPORT)
        );
        assert_eq!(
            deadline_at(std::time::Instant::now())
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::ETIMEDOUT)
        );
        assert_eq!(
            deadline_at(std::time::Instant::now() + std::time::Duration::from_secs(6))
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EINVAL)
        );
        assert!(
            deadline_at(std::time::Instant::now() + std::time::Duration::from_secs(1)).unwrap() > 0
        );
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
