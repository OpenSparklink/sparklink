use std::ffi::{CStr, c_char, c_int};
use std::ptr;

use crate::Adapter;

#[path = "ffi_native.rs"]
mod native;
pub use native::*;

/// Opaque adapter handle for C consumers
pub struct SlkAdapter {
    inner: Adapter,
}

/// Open a SparkLink adapter device.
/// Returns null and sets thread-local errno on failure.
///
/// # Safety
/// `dev_path` must be a valid null-terminated C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_adapter_open(dev_path: *const c_char) -> *mut SlkAdapter {
    if dev_path.is_null() {
        nix::errno::Errno::set_raw(nix::libc::EINVAL);
        return ptr::null_mut();
    }
    let path = match unsafe { CStr::from_ptr(dev_path) }.to_str() {
        Ok(s) => s,
        Err(_) => {
            nix::errno::Errno::set_raw(nix::libc::EINVAL);
            return ptr::null_mut();
        }
    };
    match Adapter::open(path) {
        Ok(adapter) => Box::into_raw(Box::new(SlkAdapter { inner: adapter })),
        Err(error) => {
            nix::errno::Errno::set_raw(-native::errno(error));
            ptr::null_mut()
        }
    }
}

/// Free an adapter handle.
///
/// # Safety
/// `adapter` must be a valid pointer returned by `slk_adapter_open`, or null.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_adapter_free(adapter: *mut SlkAdapter) {
    if !adapter.is_null() {
        drop(unsafe { Box::from_raw(adapter) });
    }
}

/// Get the device count.
/// Returns allocated registration count or negative errno; not Ready count.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_device_count(adapter: *const SlkAdapter) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -nix::libc::EINVAL,
    };
    match adapter.inner.device_count() {
        Ok(n) => n as c_int,
        Err(error) => native::errno(error),
    }
}

/// Get device info.
/// Returns 0 or negative errno; unknown legacy state is 0xff, never Ready.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_device_info(
    adapter: *const SlkAdapter,
    out: *mut slk_protocol::SciDevInfo,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -nix::libc::EINVAL,
    };
    if out.is_null() {
        return -nix::libc::EINVAL;
    }
    match adapter.inner.device_info() {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(error) => native::errno(error),
    }
}
