//! Privileged Native creation of delegated fixed/service/staged dynamic fds.
//! Policy stays in slkd; the kernel validates lease/lifetime and negotiates CMTC.
//! This module never manufactures Ready, protocol replies or application delivery.
//! Ordinary applications use libsparklink and slk-channel, not this creator.
use std::os::fd::{FromRawFd, OwnedFd};

#[repr(C)]
struct Address {
    family: u16,
    controller: u16,
    version: u16,
    flags: u16,
    generation: u64,
    lifetime: u64,
    lease: u64,
    handle: u16,
    local_tcid: u8,
    remote_tcid: u8,
    pi: u8,
    reserved: [u8; 3],
    directions: u32,
    security: u32,
}
const _: () = assert!(std::mem::size_of::<Address>() == 48);

/// Rust Native staging input; not a C ABI or protocol capability.
/// cbindgen:ignore
#[derive(Clone, Copy)]
pub struct DynamicConfig {
    pub source_port: u16,
    pub destination_port: u16,
    pub aid: u16,
    pub mtu: u16,
    pub mps: u16,
    pub slqi: u8,
    pub passive: bool,
}
impl DynamicConfig {
    pub fn validate(&self) -> std::io::Result<()> {
        let config = self;
        if config.source_port == 0
            || config.destination_port == 0
            || config.aid == 0
            || config.mtu == 0
            || config.mtu > 2042
            || config.mps > 2047
            || u32::from(config.mps) < u32::from(config.mtu) + 5
        {
            return Err(std::io::Error::from_raw_os_error(nix::libc::EINVAL));
        }
        Ok(())
    }
}
#[repr(C)]
struct DynamicAddress {
    base: Address,
    source_port: u16,
    destination_port: u16,
    aid: u16,
    mtu: u16,
    mps: u16,
    slqi: u8,
    mode: u8,
    reserved: u32,
}
const _: () = assert!(std::mem::size_of::<DynamicAddress>() == 64);

pub fn open_dynamic(
    controller: u16,
    generation: u64,
    lifetime: u64,
    handle: u16,
    lease: u64,
    config: DynamicConfig,
) -> std::io::Result<OwnedFd> {
    config.validate()?;
    let mut base = address(controller, generation, lifetime, handle, lease, 3, 0);
    base.version = 3;
    base.local_tcid = 0;
    base.remote_tcid = 0;
    let address = DynamicAddress {
        base,
        source_port: config.source_port,
        destination_port: config.destination_port,
        aid: config.aid,
        mtu: config.mtu,
        mps: config.mps,
        slqi: config.slqi,
        mode: 0,
        reserved: 0,
    };
    open_raw_address(address, !config.passive)
}

pub fn open(
    controller: u16,
    generation: u64,
    lifetime: u64,
    handle: u16,
    lease: u64,
    directions: u32,
    security: u32,
) -> std::io::Result<OwnedFd> {
    validate(directions, security)?;
    let address = address(
        controller, generation, lifetime, handle, lease, directions, security,
    );
    open_address(address)
}
fn address(
    controller: u16,
    generation: u64,
    lifetime: u64,
    handle: u16,
    lease: u64,
    directions: u32,
    security: u32,
) -> Address {
    Address {
        family: 46,
        controller,
        version: 2,
        flags: 0,
        generation,
        lifetime,
        lease,
        handle,
        local_tcid: 31,
        remote_tcid: 31,
        pi: 241,
        reserved: [0; 3],
        directions,
        security,
    }
}
pub fn open_service(
    controller: u16,
    generation: u64,
    lifetime: u64,
    handle: u16,
    lease: u64,
    security: u32,
) -> std::io::Result<OwnedFd> {
    validate(3, security)?;
    let address = service_address(controller, generation, lifetime, handle, lease, security);
    open_address(address)
}
fn service_address(
    controller: u16,
    generation: u64,
    lifetime: u64,
    handle: u16,
    lease: u64,
    security: u32,
) -> Address {
    let mut address = address(controller, generation, lifetime, handle, lease, 3, security);
    address.local_tcid = 10;
    address.remote_tcid = 10;
    address.pi = 0;
    address
}
fn open_address(address: Address) -> std::io::Result<OwnedFd> {
    open_raw_address(address, false)
}
fn open_raw_address<T>(address: T, active: bool) -> std::io::Result<OwnedFd> {
    // SAFETY: scalar syscall arguments; successful socket returns an owned fd.
    let raw = unsafe {
        nix::libc::socket(
            46,
            nix::libc::SOCK_DGRAM | nix::libc::SOCK_CLOEXEC | nix::libc::SOCK_NONBLOCK,
            0,
        )
    };
    if raw < 0 {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: raw is a newly created, uniquely owned descriptor.
    let fd = unsafe { OwnedFd::from_raw_fd(raw) };
    // SAFETY: address is a complete initialized ABI structure valid for this call.
    let result = unsafe {
        let pointer = (&address as *const T).cast();
        let size = std::mem::size_of::<T>() as u32;
        if active {
            nix::libc::connect(raw, pointer, size)
        } else {
            nix::libc::bind(raw, pointer, size)
        }
    };
    if result < 0 {
        let error = std::io::Error::last_os_error();
        if !active || error.raw_os_error() != Some(nix::libc::EINPROGRESS) {
            return Err(error);
        }
    }
    Ok(fd)
}

/// Unpublished TX/RX and fixed-channel security requirements. The kernel
/// mints a frozen security epoch; no userspace cached grade authorizes it.
pub fn validate(directions: u32, security: u32) -> std::io::Result<()> {
    if directions == 0 || directions & !3 != 0 {
        return Err(std::io::Error::from_raw_os_error(nix::libc::EINVAL));
    }
    if security > 2 {
        return Err(std::io::Error::from_raw_os_error(nix::libc::EOPNOTSUPP));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn service_first_bind_preserves_requirement_and_identity() {
        for security in 0..=2 {
            let a = service_address(7, 11, 13, 17, 19, security);
            assert_eq!(
                (a.controller, a.generation, a.lifetime, a.handle, a.lease),
                (7, 11, 13, 17, 19)
            );
            assert_eq!(
                (a.local_tcid, a.remote_tcid, a.pi, a.directions, a.security),
                (10, 10, 0, 3, security)
            );
        }
        for security in [3, u32::MAX] {
            assert_eq!(
                open_service(7, 11, 13, 17, 19, security)
                    .unwrap_err()
                    .raw_os_error(),
                Some(nix::libc::EOPNOTSUPP)
            );
        }
    }
    #[test]
    fn scoped_requests_reject_before_socket_creation() {
        for directions in [0, 4, 7, u32::MAX] {
            assert_eq!(
                open(0, 1, 1, 0, 1, directions, 0)
                    .unwrap_err()
                    .raw_os_error(),
                Some(nix::libc::EINVAL)
            );
        }
        for security in [3, u32::MAX] {
            assert_eq!(
                open(0, 1, 1, 0, 1, 3, security).unwrap_err().raw_os_error(),
                Some(nix::libc::EOPNOTSUPP)
            );
        }
        for directions in [1, 2, 3] {
            for security in [0, 1, 2] {
                validate(directions, security).unwrap();
            }
        }
    }
}
