//! Dynamic READ frontend views over the sole Rust Provider inbox. No foreign
//! callback runs on the caller executor; reply acceptance is local only.
use crate::{
    ffi_client::SlkControllerId,
    ffi_local_services::SlkLocalService,
    ssap::provider::frontend::{Inbox, Request},
    sync_client::Deadline,
};
use std::{ffi::c_int, os::fd::IntoRawFd};

/// Local inbox only. Does not retain a caller/registration. Free stops its
/// callback admission, not remote binding, service, connection or controller.
pub struct SlkReadProvider {
    inner: Inbox,
}
/// One original callback. No caller/registration reference. Release and actual
/// callback drain are separate; an unanswered release becomes unavailable.
pub struct SlkReadProviderRequest {
    inner: Request,
}
/// Immutable original context, not current authorization or peer identity.
/// All reserved bytes zero; no implicit value database or proposed write.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkReadProviderRequestInfo {
    pub controller: SlkControllerId,
    pub token: u64,
    pub request_id: u64,
    pub connection_lifetime: u64,
    pub security_epoch: u64,
    pub deadline_ns: u64,
    pub security_level: u32,
    pub connection_handle: u16,
    pub property: u16,
    pub maximum_bytes: u16,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub reserved: [u8; 11],
}
fn error(e: std::io::Error) -> c_int {
    -e.raw_os_error().unwrap_or(nix::libc::EIO)
}

/// Bind the original service's exactly READ type0 property once. Stored bytes
/// are discarded by the original broker: no rebind/unbind/fallback. A timeout
/// can follow commit and is not retried. The original absolute CLOCK_MONOTONIC
/// deadline includes executor admission. Success is local binding only, not RF.
/// 0/-errno; output unchanged on error. Free this inbox even after service close.
/// # Safety
/// Live original service; output aligned/exclusive/nonaliasing; no concurrent
/// service free or use of inherited objects after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_bind_read_provider(
    service: *mut SlkLocalService,
    property: u16,
    deadline_ns: u64,
    output: *mut *mut SlkReadProvider,
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
                .bind(&mut *registration.lock().await, property, original)
                .await
        })
    })();
    match result {
        Ok(inner) => {
            unsafe { output.write(Box::into_raw(Box::new(SlkReadProvider { inner }))) };
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
pub unsafe extern "C" fn slk_read_provider_fd(
    provider: *const SlkReadProvider,
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
pub unsafe extern "C" fn slk_read_provider_next(
    provider: *const SlkReadProvider,
    output: *mut *mut SlkReadProviderRequest,
) -> c_int {
    if provider.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    match unsafe { &*provider }.inner.try_next() {
        Ok(inner) => {
            unsafe { output.write(Box::into_raw(Box::new(SlkReadProviderRequest { inner }))) };
            0
        }
        Err(e) => error(e),
    }
}
/// Free local inbox,NULL allowed. Does not withdraw/rebind/restore stored bytes.
/// # Safety
/// One owned live pointer freed once; no concurrent call, fork copy or later use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_read_provider_free(provider: *mut SlkReadProvider) {
    if !provider.is_null() {
        drop(unsafe { Box::from_raw(provider) });
    }
}
/// Copy original immutable snapshot even after expiry/close. No current grant.
/// # Safety
/// Request live; output aligned/exclusive/writable/nonaliasing; no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_read_provider_request_info(
    request: *const SlkReadProviderRequest,
    output: *mut SlkReadProviderRequestInfo,
) -> c_int {
    if request.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let v = &unsafe { &*request }.inner;
    let r = v.request();
    let id = r.identity;
    let value = SlkReadProviderRequestInfo {
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
        property: r.property,
        maximum_bytes: r.maximum_bytes,
        local_tcid: id.6,
        remote_tcid: id.7,
        pi: id.8,
        reserved: [0; 11],
    };
    unsafe { output.write(value) };
    0
}
/// Answer once locally: status0 with 0..maximum bytes (empty is success), or
/// AF..FF with zero bytes. Invalid/oversized input leaves the request unanswered.
/// No truncation or new deadline. 0 is local acceptance, never peer delivery.
/// Duplicate ESTALE, expired ETIMEDOUT, stopped ESHUTDOWN. Reply never queues RPC.
/// # Safety
/// Request live, no concurrent free/fork use. NULL value allowed only length0;
/// otherwise value denotes a live immutable length-byte region. Invalid non-NULL
/// pointers are caller UB, not supported kernel-style EFAULT inputs.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_read_provider_request_reply(
    request: *const SlkReadProviderRequest,
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
    if length > usize::from(r.request().maximum_bytes) {
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
pub unsafe extern "C" fn slk_read_provider_request_free(request: *mut SlkReadProviderRequest) {
    if !request.is_null() {
        drop(unsafe { Box::from_raw(request) });
    }
}
