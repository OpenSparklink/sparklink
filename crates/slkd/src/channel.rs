//! Native default-channel fd delegation. The kernel validates the final lifetime
//! and negotiates CMTC; basic datagrams do not promise reliable delivery.
//! This broker never synthesizes channel readiness or data.
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

pub(crate) fn open(
    controller: u16,
    generation: u64,
    lifetime: u64,
    handle: u16,
    lease: u64,
) -> std::io::Result<OwnedFd> {
    let address = Address {
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
        directions: 3,
        security: 0,
    };
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
        nix::libc::bind(
            raw,
            (&address as *const Address).cast(),
            std::mem::size_of::<Address>() as u32,
        )
    };
    if result < 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(fd)
}
