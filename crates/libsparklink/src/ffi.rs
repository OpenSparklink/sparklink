use std::ffi::{c_char, c_int, CStr};
use std::ptr;

use crate::Adapter;

/// Opaque adapter handle for C consumers
pub struct SlkAdapter {
    inner: Adapter,
}

/// Open a SparkLink adapter device.
/// Returns null on failure.
///
/// # Safety
/// `dev_path` must be a valid null-terminated C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_adapter_open(dev_path: *const c_char) -> *mut SlkAdapter {
    if dev_path.is_null() {
        return ptr::null_mut();
    }
    let path = match unsafe { CStr::from_ptr(dev_path) }.to_str() {
        Ok(s) => s,
        Err(_) => return ptr::null_mut(),
    };
    match Adapter::open(path) {
        Ok(adapter) => Box::into_raw(Box::new(SlkAdapter { inner: adapter })),
        Err(_) => ptr::null_mut(),
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
/// Returns -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_device_count(adapter: *const SlkAdapter) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    match adapter.inner.device_count() {
        Ok(n) => n as c_int,
        Err(_) => -1,
    }
}

/// Start scanning.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
/// `params` must point to a valid `SleScanParams` struct.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_start_scan(
    adapter: *const SlkAdapter,
    params: *const slk_protocol::SleScanParams,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    let params = match unsafe { params.as_ref() } {
        Some(p) => p,
        None => return -1,
    };
    match adapter.inner.start_scan(params) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Stop scanning.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_stop_scan(adapter: *const SlkAdapter) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    match adapter.inner.stop_scan() {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Initiate a connection.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
/// `params` must point to a valid `SleConnectParams` struct.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_connect(
    adapter: *const SlkAdapter,
    params: *const slk_protocol::SleConnectParams,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    let params = match unsafe { params.as_ref() } {
        Some(p) => p,
        None => return -1,
    };
    match adapter.inner.connect(params) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Disconnect a connection by handle.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_disconnect(adapter: *const SlkAdapter, handle: u16) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    match adapter.inner.disconnect(handle) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Get connection info.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_conn_info(
    adapter: *const SlkAdapter,
    handle: u16,
    out: *mut slk_protocol::SleConnInfo,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.conn_info(handle) {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(_) => -1,
    }
}

/// Get security info.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_sec_info(
    adapter: *const SlkAdapter,
    out: *mut slk_protocol::SleSecInfo,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.sec_info() {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(_) => -1,
    }
}

/// Initiate pairing.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `params` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_pair(
    adapter: *const SlkAdapter,
    params: *const slk_protocol::SlePairParams,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    let params = match unsafe { params.as_ref() } {
        Some(p) => p,
        None => return -1,
    };
    match adapter.inner.pair(params) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Enable encryption.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_encrypt_on(adapter: *const SlkAdapter) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    match adapter.inner.encrypt_on() {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Get SSAP summary.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_info(
    adapter: *const SlkAdapter,
    out: *mut slk_protocol::SsapSummary,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.ssap_info() {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(_) => -1,
    }
}

/// Read an SSAP property.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_read(
    adapter: *const SlkAdapter,
    handle: u16,
    out: *mut slk_protocol::SsapReadWrite,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.ssap_read(handle) {
        Ok(rw) => {
            unsafe { *out = rw };
            0
        }
        Err(_) => -1,
    }
}

/// Write an SSAP property.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `data` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_write(
    adapter: *const SlkAdapter,
    data: *const slk_protocol::SsapReadWrite,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    let data = match unsafe { data.as_ref() } {
        Some(d) => d,
        None => return -1,
    };
    match adapter.inner.ssap_write(data) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Poll for a DLI event (non-blocking).
/// Returns 1 if event available (written to `out`), 0 if no event, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_poll_event(
    adapter: *const SlkAdapter,
    out: *mut slk_protocol::SleDliEvent,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.poll_event() {
        Ok(Some(event)) => {
            unsafe { *out = event };
            1
        }
        Ok(None) => 0,
        Err(_) => -1,
    }
}

/// Get device info.
/// Returns 0 on success, -1 on error.
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
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.device_info() {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(_) => -1,
    }
}

/// Get DLI controller info.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_dli_info(
    adapter: *const SlkAdapter,
    out: *mut slk_protocol::SleDliInfo,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.dli_info() {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(_) => -1,
    }
}

/// Get PHY info.
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` and `out` must be valid non-null pointers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_phy_info(
    adapter: *const SlkAdapter,
    out: *mut slk_protocol::SlePhyInfo,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    if out.is_null() {
        return -1;
    }
    match adapter.inner.phy_info() {
        Ok(info) => {
            unsafe { *out = info };
            0
        }
        Err(_) => -1,
    }
}

/// Set device role (0 = G-node, 1 = T-node).
/// Returns 0 on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_set_role(adapter: *const SlkAdapter, role: u8) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    match adapter.inner.set_role(role) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Get device role.
/// Returns role (0 or 1) on success, -1 on error.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_get_role(adapter: *const SlkAdapter) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    match adapter.inner.get_role() {
        Ok(r) => r as c_int,
        Err(_) => -1,
    }
}

/// Invoke a method on a remote peer's SSAP service.
///
/// # Safety
/// `adapter` must be a valid non-null pointer.
/// `input` must point to `input_len` readable bytes.
/// `output` must point to `output_len` writable bytes.
/// On success, `output_len` is updated with the actual output size.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_call_method(
    adapter: *const SlkAdapter,
    conn_handle: u16,
    method_handle: u16,
    input: *const u8,
    input_len: usize,
    output: *mut u8,
    output_len: *mut usize,
) -> c_int {
    let adapter = match unsafe { adapter.as_ref() } {
        Some(a) => a,
        None => return -1,
    };
    let mut rw: slk_protocol::SsapRemoteReadWrite = unsafe { core::mem::zeroed() };
    rw.conn_handle = conn_handle;
    rw.handle = method_handle;
    let copy_len = input_len.min(rw.data.len());
    if !input.is_null() && copy_len > 0 {
        unsafe { core::ptr::copy_nonoverlapping(input, rw.data.as_mut_ptr(), copy_len) };
    }
    rw.length = copy_len as u16;
    match adapter.inner.ssap_call_method(&mut rw) {
        Ok(()) => {
            let out_len = (rw.length as usize).min(rw.data.len());
            if !output.is_null() && !output_len.is_null() {
                let max_out = unsafe { *output_len };
                let actual = out_len.min(max_out);
                unsafe { core::ptr::copy_nonoverlapping(rw.data.as_ptr(), output, actual) };
                unsafe { *output_len = actual };
            }
            0
        }
        Err(_) => -1,
    }
}
