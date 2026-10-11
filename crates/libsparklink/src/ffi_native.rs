//! Native selected-registration C interface. Negative returns are -errno;
//! legacy exports retain their existing 0/-1 convention. No implicit Runtime,
//! management acquisition, Tokio reactor or consuming legacy-stream fallback.
use super::SlkAdapter;
use crate::{ControllerEventCursor, Error, SnoopCursor};
use slk_protocol::*;
use std::{ffi::c_int, os::fd::AsRawFd};

fn errno(error: Error) -> c_int {
    -match error {
        Error::Ioctl(error) => error as c_int,
        Error::OpenDevice(error) => error.raw_os_error().unwrap_or(nix::libc::EIO),
        Error::InvalidParam(_) => nix::libc::EINVAL,
        Error::Timeout => nix::libc::ETIMEDOUT,
        Error::DeviceNotFound(_) => nix::libc::ENODEV,
        Error::ConnectionNotFound(_) => nix::libc::ENOENT,
    }
}

/// Bind this fd to one registration, without changing legacy global selection.
/// Returns 0 or negative errno. Replug invalidates this fd; open a new handle.
/// # Safety
/// `adapter` is null or a live, exclusively borrowed adapter handle.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_adapter_select(adapter: *mut SlkAdapter, index: u16) -> c_int {
    let Some(adapter) = (unsafe { adapter.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    adapter
        .inner
        .select_device(index)
        .map_or_else(errno, |()| 0)
}

/// Borrow this handle's fd for poll/epoll; never close it or change its affinity.
/// Activate controller-event/snoop mode with its poll function BEFORE adding
/// this fd to poll/epoll. Use separately opened handles for independent readers.
/// # Safety
/// `adapter` is null or a live handle. Its fd remains valid only until free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_adapter_fd(adapter: *const SlkAdapter) -> c_int {
    let Some(adapter) = (unsafe { adapter.as_ref() }) else {
        return -nix::libc::EINVAL;
    };
    adapter.inner.as_fd().as_raw_fd()
}

/// Return the registered index bitmap (indices can have holes), or -errno.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; out is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_device_mask(adapter: *const SlkAdapter, out: *mut u16) -> c_int {
    let (Some(adapter), Some(out)) = (unsafe { adapter.as_ref() }, unsafe { out.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.device_indices() {
        Ok(indices) => {
            *out = indices.into_iter().fold(0, |mask, i| mask | (1 << i));
            0
        }
        Err(error) => errno(error),
    }
}

/// Query selected registration metadata. generation=0 probes; otherwise exact.
/// This observes Host readiness; it does not enable a radio domain.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; out is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_controller_snapshot(
    adapter: *const SlkAdapter,
    generation: u64,
    out: *mut SleControllerSnapshot,
) -> c_int {
    let (Some(adapter), Some(out)) = (unsafe { adapter.as_ref() }, unsafe { out.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.controller_snapshot(generation) {
        Ok(value) => {
            *out = value;
            0
        }
        Err(error) => errno(error),
    }
}

/// Acquire Managed(1) or Diagnostic(2) on this exact generation/fd. Kernel
/// CAP_NET_ADMIN and ownership checks apply; a lease alone grants no authority.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; lease is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_management_acquire(
    adapter: *const SlkAdapter,
    generation: u64,
    mode: u32,
    lease: *mut u64,
) -> c_int {
    let (Some(adapter), Some(lease)) = (unsafe { adapter.as_ref() }, unsafe { lease.as_mut() })
    else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.acquire_management(generation, mode) {
        Ok(value) => {
            *lease = value;
            0
        }
        Err(error) => errno(error),
    }
}

/// Observe selected ownership. generation=0 probes; another fd sees no token.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; out is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_management_query(
    adapter: *const SlkAdapter,
    generation: u64,
    out: *mut SleManagementQuery,
) -> c_int {
    let (Some(adapter), Some(out)) = (unsafe { adapter.as_ref() }, unsafe { out.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.management_status(generation) {
        Ok(value) => {
            *out = value;
            0
        }
        Err(error) => errno(error),
    }
}

/// Request asynchronous release. Success is admission, not completed cleanup;
/// query ownership until Free before treating a successor as available.
/// # Safety
/// `adapter` is null or a live handle with no concurrent free/selection.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_management_release(
    adapter: *const SlkAdapter,
    generation: u64,
    lease: u64,
    mode: u32,
) -> c_int {
    let Some(adapter) = (unsafe { adapter.as_ref() }) else {
        return -nix::libc::EINVAL;
    };
    adapter
        .inner
        .release_management(generation, lease, mode)
        .map_or_else(errno, |()| 0)
}

/// Submit all typed discovery parameters using Managed ownership. Return 0
/// means admission only; result state/status/error determine actual completion.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; request is readable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_submit(
    adapter: *const SlkAdapter,
    request: *const SleDiscoverySubmit,
) -> c_int {
    let (Some(adapter), Some(request)) = (unsafe { adapter.as_ref() }, unsafe { request.as_ref() })
    else {
        return -nix::libc::EINVAL;
    };
    adapter
        .inner
        .submit_discovery(request)
        .map_or_else(errno, |()| 0)
}

/// Non-consuming result: 1 record, 0 absent/evicted, negative errno. A record
/// may still be queued/pending; failed terminal records retain raw reasons.
/// Output is unchanged on 0/error. Generation/request must both be nonzero.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; out is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_result(
    adapter: *const SlkAdapter,
    generation: u64,
    request_id: u64,
    out: *mut SleDiscoveryResult,
) -> c_int {
    let (Some(adapter), Some(out)) = (unsafe { adapter.as_ref() }, unsafe { out.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.discovery_result(generation, request_id) {
        Ok(Some(value)) => {
            *out = value;
            1
        }
        Ok(None) => 0,
        Err(error) => errno(error),
    }
}

/// Independent complete controller event: 1 record, 0 quiet, negative errno.
/// Initialize query to zero with version=1 and explicit nonzero generation.
/// Success advances after_seq; quiet/error leaves all caller bytes unchanged.
/// No raw legacy fallback. Event and snoop modes on one fd cannot be mixed.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; query is read/write.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_controller_event(
    adapter: *const SlkAdapter,
    query: *mut SleControllerEventQuery,
) -> c_int {
    let (Some(adapter), Some(query)) = (unsafe { adapter.as_ref() }, unsafe { query.as_mut() })
    else {
        return -nix::libc::EINVAL;
    };
    if query.version != CONTROLLER_EVENT_VERSION || query.flags != 0 || query.generation == 0 {
        return -nix::libc::EINVAL;
    }
    let mut cursor = ControllerEventCursor {
        generation: query.generation,
        after_seq: query.after_seq,
    };
    match adapter.inner.poll_controller_event(&mut cursor) {
        Ok(Some(value)) => {
            query.event = value;
            query.after_seq = cursor.after_seq;
            1
        }
        Ok(None) => 0,
        Err(error) => errno(error),
    }
}

/// Privileged independent DLI seam observation: 1 record, 0 quiet, -errno.
/// Initialize zero query with version=1 and explicit generation. Success alone
/// advances after_seq. CAP_NET_ADMIN applies on every call; never takes a lease
/// or consumes Host raw replies. Use a separate selected observation handle.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; query is read/write.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_snoop(adapter: *const SlkAdapter, query: *mut SleSnoopQuery) -> c_int {
    let (Some(adapter), Some(query)) = (unsafe { adapter.as_ref() }, unsafe { query.as_mut() })
    else {
        return -nix::libc::EINVAL;
    };
    if query.version != SNOOP_VERSION
        || query.flags != 0
        || query.reserved != 0
        || query.generation == 0
    {
        return -nix::libc::EINVAL;
    }
    let mut cursor = SnoopCursor {
        generation: query.generation,
        after_seq: query.after_seq,
    };
    match adapter.inner.poll_snoop(&mut cursor) {
        Ok(Some(value)) => {
            query.record = value;
            query.after_seq = cursor.after_seq;
            1
        }
        Ok(None) => 0,
        Err(error) => errno(error),
    }
}

/// Query final matched Complete receipt (CLOCK_BOOTTIME ns), 0 or -errno.
/// Pending/non-success timing is zero; output remains untouched on failure.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; out is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_timing(
    adapter: *const SlkAdapter,
    generation: u64,
    request_id: u64,
    out: *mut SleDiscoveryTiming,
) -> c_int {
    let (Some(adapter), Some(out)) = (unsafe { adapter.as_ref() }, unsafe { out.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.discovery_timing(generation, request_id) {
        Ok(value) => {
            *out = value;
            0
        }
        Err(error) => errno(error),
    }
}

/// Query the originating fd's raw diagnostic result, without consuming events.
/// Returns 1 present, 0 absent/evicted or -errno; failed queries leave out intact.
/// Requires an exact generation, nonzero seq and Diagnostic ownership/admin.
/// # Safety
/// Non-null pointers are valid, aligned, nonoverlapping; out is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_diagnostic_result(
    adapter: *const SlkAdapter,
    generation: u64,
    seq: u32,
    out: *mut SleDiagnosticResult,
) -> c_int {
    let (Some(adapter), Some(out)) = (unsafe { adapter.as_ref() }, unsafe { out.as_mut() }) else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.diagnostic_result(generation, seq) {
        Ok(Some(value)) => {
            *out = value;
            1
        }
        Ok(None) => 0,
        Err(error) => errno(error),
    }
}

/// Idempotent metadata admission/cancel; returns 0 or -errno. Request storage is
/// unchanged on failure, including syscall EFAULT. Retry the same caller-known
/// ID/fields; a failure is not evidence that the command was not admitted.
/// # Safety
/// Non-null pointers are valid/aligned/nonoverlapping; request is writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_diagnostic_submit(
    adapter: *const SlkAdapter,
    request: *mut SleDiagnosticSubmit,
) -> c_int {
    let (Some(adapter), Some(request)) = (unsafe { adapter.as_ref() }, unsafe { request.as_mut() })
    else {
        return -nix::libc::EINVAL;
    };
    match adapter.inner.diagnostic_submit(request) {
        Ok(()) => 0,
        Err(error) => errno(error),
    }
}
