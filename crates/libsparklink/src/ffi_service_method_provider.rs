//! Method frontend views over the sole Rust Provider inbox. No foreign
//! callback runs on the caller executor; reply acceptance is local only.
use crate::{
    ffi_client::SlkControllerId,
    ffi_local_services::SlkLocalService,
    ssap::provider::frontend::{MethodInbox as Inbox, MethodRequest as Request},
    sync_client::Deadline,
};
use std::{ffi::c_int, os::fd::IntoRawFd};

/// Local inbox only. Does not retain a caller/registration. Free stops its
/// callback admission, not remote binding, service, connection or controller.
pub struct SlkMethodProvider {
    inner: Inbox,
}
/// One original callback. No caller/registration reference. Release and actual
/// callback drain are separate; an unanswered release becomes unavailable.
pub struct SlkMethodProviderRequest {
    inner: Request,
}
/// Immutable original context, not current authorization or peer identity.
/// All reserved bytes zero. Proposed bytes are available through the bounded value copy.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkMethodProviderRequestInfo {
    pub controller: SlkControllerId,
    pub token: u64,
    pub request_id: u64,
    pub connection_lifetime: u64,
    pub security_epoch: u64,
    pub deadline_ns: u64,
    pub security_level: u32,
    pub connection_handle: u16,
    pub method: u16,
    pub maximum_result_bytes: u16,
    pub argument_length: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub operation: u8,
    pub reserved: [u8; 8],
}
fn error(e: std::io::Error) -> c_int {
    -e.raw_os_error().unwrap_or(nix::libc::EIO)
}

/// Bind an original method once on the owner's existing executor/dispatcher.
/// No property value, rebind, implicit retry or fallback. Original absolute
/// CLOCK_MONOTONIC deadline includes queue admission. Success is local binding
/// only.0/-errno; output unchanged on error. Free inbox even after service close.
/// # Safety
/// Live original service; output aligned/exclusive/nonaliasing; no concurrent
/// service free or use of inherited objects after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_bind_method_provider(
    service: *mut SlkLocalService,
    method: u16,
    deadline_ns: u64,
    output: *mut *mut SlkMethodProvider,
) -> c_int {
    if service.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let v = unsafe { &*service };
    let result = (|| {
        let deadline = Deadline::from_monotonic_ns(deadline_ns)?;
        let original = deadline.request()?;
        let registration = v.registration.clone();
        let dispatcher = v.executor.providers().clone();
        v.executor.call(deadline, move |_| async move {
            dispatcher
                .bind_method(&mut *registration.lock().await, method, original)
                .await
        })
    })();
    match result {
        Ok(inner) => {
            unsafe { output.write(Box::into_raw(Box::new(SlkMethodProvider { inner }))) };
            0
        }
        Err(e) => -e,
    }
}
/// Duplicate CLOEXEC notification fd, caller closes it. Poll only: never read
/// or write its counter. Try next before waiting and again after readiness.
/// It carries no reply authority and does not retain the caller.0/-errno.
/// # Safety
/// Provider live immutable, output aligned exclusive; no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_fd(
    provider: *const SlkMethodProvider,
    output: *mut c_int,
) -> c_int {
    if provider.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    match unsafe { &*provider }.inner.fd() {
        Ok(fd) => {
            unsafe { output.write(fd.into_raw_fd()) };
            0
        }
        Err(e) => error(e),
    }
}
/// Nonblocking next. EAGAIN empty, ESHUTDOWN local stopped, ESTALE original
/// daemon lost, ETIMEDOUT expired undelivered entry. Output unchanged on error.
/// One consuming application; this never queues an RPC or executes user code.
/// # Safety
/// Provider live, output exclusive/aligned/nonaliasing, no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_next(
    provider: *const SlkMethodProvider,
    output: *mut *mut SlkMethodProviderRequest,
) -> c_int {
    if provider.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    match unsafe { &*provider }.inner.try_next() {
        Ok(inner) => {
            unsafe { output.write(Box::into_raw(Box::new(SlkMethodProviderRequest { inner }))) };
            0
        }
        Err(e) => error(e),
    }
}
/// Free local inbox,NULL allowed. Does not withdraw or roll back application effects.
/// # Safety
/// One owned live pointer freed once; no concurrent call, fork copy or later use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_free(provider: *mut SlkMethodProvider) {
    if !provider.is_null() {
        drop(unsafe { Box::from_raw(provider) });
    }
}
/// Copy original immutable snapshot even after expiry/close. No current grant.
/// # Safety
/// Request live; output aligned/exclusive/writable/nonaliasing; no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_request_info(
    request: *const SlkMethodProviderRequest,
    output: *mut SlkMethodProviderRequestInfo,
) -> c_int {
    if request.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let v = &unsafe { &*request }.inner;
    let r = v.request();
    let id = r.identity;
    let value = SlkMethodProviderRequestInfo {
        controller: SlkControllerId {
            index: id.0,
            generation: id.1,
            reserved: [0; 6],
        },
        token: v.token(),
        request_id: r.request_id,
        connection_lifetime: id.2,
        security_epoch: id.4,
        deadline_ns: r.deadline_ns,
        security_level: id.5,
        connection_handle: id.3,
        method: r.method,
        maximum_result_bytes: r.maximum_result_bytes,
        argument_length: r.arguments.len() as u16,
        local_tcid: id.6,
        remote_tcid: id.7,
        pi: id.8,
        operation: r.operation,
        reserved: [0; 8],
    };
    unsafe { output.write(value) };
    0
}
/// Return one independent application result: status0 within the original
/// result budget, or AF..FF with zero bytes. Command18 permits no result bytes.
/// No argument echo, effect rollback, truncation, retry or new deadline.
/// Local acceptance is not wire/peer delivery. Invalid input leaves authority
/// unconsumed; stale, stopped or expired requests remain refused.0/-errno.
/// # Safety
/// Request live, no concurrent free/fork use. NULL value allowed only length0;
/// otherwise value denotes a live immutable length-byte region. Invalid non-NULL
/// pointers are caller UB, not supported kernel-style EFAULT inputs.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_request_reply(
    request: *const SlkMethodProviderRequest,
    status: u16,
    value: *const u8,
    length: usize,
) -> c_int {
    if request.is_null() || (value.is_null() && length != 0) {
        return -nix::libc::EINVAL;
    }
    if status != 0 && (!(0xaf..=0xff).contains(&status) || length != 0) {
        return -nix::libc::EINVAL;
    }
    let r = &unsafe { &*request }.inner;
    let maximum = usize::from(r.request().maximum_result_bytes);
    if length > maximum {
        return -nix::libc::EMSGSIZE;
    }
    let bytes = if length == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(value, length) }
    };
    match r.reply(status, bytes) {
        Ok(()) => 0,
        Err(e) => error(e),
    }
}
/// Release request,NULL allowed. Unanswered release is unavailable; this does
/// not prove callback drain, remote cleanup or any physical completion.
/// # Safety
/// One live owned pointer freed once, no concurrent calls/fork copies/later use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_request_free(request: *mut SlkMethodProviderRequest) {
    if !request.is_null() {
        drop(unsafe { Box::from_raw(request) });
    }
}

/// Copy the original arguments, including after expiry/close, without
/// consuming reply authority. Output length is always the full required size;
/// ENOSPC leaves buffer unchanged. NULL buffer is permitted for capacity0.
/// # Safety
/// Live request, exclusive aligned length output, buffer writable for capacity
/// bytes without aliasing outputs/request; no concurrent free or fork copy use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_method_provider_request_arguments(
    request: *const SlkMethodProviderRequest,
    buffer: *mut u8,
    capacity: usize,
    length: *mut usize,
) -> c_int {
    if request.is_null() || length.is_null() || (buffer.is_null() && capacity != 0) {
        return -nix::libc::EINVAL;
    }
    let bytes = &unsafe { &*request }.inner.request().arguments;
    unsafe { length.write(bytes.len()) };
    if capacity < bytes.len() {
        return -nix::libc::ENOSPC;
    }
    if !bytes.is_empty() {
        unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), buffer, bytes.len()) };
    }
    0
}
