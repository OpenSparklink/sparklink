//! Application Channel C ABI. Native controller operations live in slk-native.
//! Each function uses the same Channel operation implementation; no Host Engine.
use slk_protocol::*;
use std::ffi::c_int;

/// Read actual capabilities of a delegated logical-channel socket.
/// Returns 0 or negative errno; output remains unchanged on error.
/// # Safety
/// `output` is null or points to a live, aligned, writable SleChannelInfo.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_channel_info(fd: c_int, output: *mut SleChannelInfo) -> c_int {
    if output.is_null() {
        return -nix::libc::EINVAL;
    }
    match slk_channel::query(fd) {
        Ok(info) => {
            unsafe {
                output.write(info);
            }
            0
        }
        Err(error) => -error.raw_os_error().unwrap_or(nix::libc::EPROTO),
    }
}

/// Coherent read-only queue and reservation observation of an authorized fd.
/// Returns0 or negative errno; output unchanged on error. No credit mutation.
/// # Safety
/// output is null or a live aligned writable SleChannelTxStatus object.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_channel_tx_status(
    fd: c_int,
    output: *mut SleChannelTxStatus,
) -> c_int {
    if output.is_null() {
        return -nix::libc::EINVAL;
    }
    match slk_channel::query_tx_status(fd) {
        Ok(value) => {
            unsafe { output.write(value) };
            0
        }
        Err(error) => -error.raw_os_error().unwrap_or(nix::libc::EPROTO),
    }
}

/// Coherent read-only Session mechanism observation of an authorized fd.
/// Returns0 or negative errno; output unchanged on error. No credit mutation.
/// # Safety
/// output is null or a live aligned writable SleSessionTxStatus object.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_session_tx_status(
    fd: c_int,
    output: *mut SleSessionTxStatus,
) -> c_int {
    if output.is_null() {
        return -nix::libc::EINVAL;
    }
    match slk_channel::query_session_tx_status(fd) {
        Ok(value) => {
            unsafe { output.write(value) };
            0
        }
        Err(error) => -error.raw_os_error().unwrap_or(nix::libc::EPROTO),
    }
}

/// Receive actual kernel receipt context alongside a datagram. Returns count
/// or -errno. Output objects unchanged on error; payload may already be copied
/// or consumed. With MSG_TRUNC count may exceed length. No future TX authority.
/// # Safety
/// Caller retains fd and valid exclusive writable buffers/output objects for
/// the full call. buffer may be null only for zero length; other outputs cannot
/// be null. No concurrent close/reuse of fd or aliasing these writable regions.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_channel_recv_security(
    fd: c_int,
    buffer: *mut u8,
    length: usize,
    flags: c_int,
    output: *mut SleMessageSecurity,
    received_flags: *mut c_int,
) -> isize {
    if output.is_null()
        || received_flags.is_null()
        || length > isize::MAX as usize
        || (buffer.is_null() && length != 0)
    {
        return -(nix::libc::EINVAL as isize);
    }
    let bytes = if length == 0 {
        &mut []
    } else {
        // SAFETY: caller provides the exclusive live region described above.
        unsafe { std::slice::from_raw_parts_mut(buffer, length) }
    };
    match slk_channel::security::recv(fd, bytes, flags) {
        Ok((count, context, actual_flags)) => {
            unsafe {
                output.write(context);
                received_flags.write(actual_flags);
            }
            count as isize
        }
        Err(error) => -(error.raw_os_error().unwrap_or(nix::libc::EPROTO) as isize),
    }
}

/// Restrictive sendmsg software admission; never USB/controller/peer completion.
/// # Safety
/// Caller holds a stable fd and live readable, nonaliased input regions through
/// the call. buffer may be null only for zero length; constraint must be valid.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_channel_send_constrained(
    fd: c_int,
    buffer: *const u8,
    length: usize,
    flags: c_int,
    constraint: *const SleSendConstraint,
) -> isize {
    if constraint.is_null() || length > isize::MAX as usize || (buffer.is_null() && length != 0) {
        return -(nix::libc::EINVAL as isize);
    }
    let bytes = if length == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(buffer, length) }
    };
    match slk_channel::security::send(fd, bytes, flags, unsafe { &*constraint }) {
        Ok(count) => count as isize,
        Err(error) => -(error.raw_os_error().unwrap_or(nix::libc::EPROTO) as isize),
    }
}

/// Prepare a restrictive intent through the already authorized fd, no Grant
/// renewal or credit reservation. Actual sendmsg must still carry the result.
/// # Safety
/// Caller holds a stable fd and exclusive live aligned writable output object.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_channel_prepare_tx(
    fd: c_int,
    minimum: u32,
    deadline: u64,
    out: *mut SleSendConstraint,
) -> c_int {
    if out.is_null() {
        return -nix::libc::EINVAL;
    }
    match slk_channel::security::prepare(fd, minimum, deadline) {
        Ok(c) => {
            unsafe { out.write(c) };
            0
        }
        Err(e) => -e.raw_os_error().unwrap_or(nix::libc::EIO),
    }
}

/// Pure requirement validation, not a grant or native security observation.
#[unsafe(no_mangle)]
pub extern "C" fn slk_ssap_access_error(bits: u32, level: u32, write: u32) -> c_int {
    if write > 1 || level > 2 {
        return -nix::libc::EINVAL;
    }
    match slk_protocol::ssap::access::SsapAccess::from_bits(bits) {
        Err(_) => -nix::libc::EINVAL,
        Ok(p) => p.check(level, write != 0).map_or_else(i32::from, |()| 0),
    }
}
