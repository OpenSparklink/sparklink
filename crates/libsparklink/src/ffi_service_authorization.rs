//! Explicit application policy delivery. No foreign callback executes on the
//! caller executor. fd readiness/decision admission is not peer delivery.
use crate::{ffi_client::SlkControllerId, ffi_local_services::SlkLocalService};
use std::{ffi::c_int, os::fd::IntoRawFd};
pub const SLK_SERVICE_AUTHORIZATION_NONE: u32 = 0;
pub const SLK_SERVICE_AUTHORIZATION_REQUESTS: u32 = 1;

/// One delivered request. Holds no caller/registration/Native fd. Freeing an
/// unanswered request denies it. Its slot is retained until callback drain AND
/// request release; old handles cannot approve a later request.
pub struct SlkAuthorizationRequest {
    inner: crate::ssap::authorization::inbox::Request,
}
/// Immutable original context;local observation,not authenticated peer/Grant.
/// value[0..value_length] is the proposed write;reads have no value.
/// Fully zeroed reserved/tail/unused value bytes. May be read after service close.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkAuthorizationRequestInfo {
    pub controller: SlkControllerId,
    pub token: u64,
    pub request_id: u64,
    pub connection_lifetime: u64,
    pub security_epoch: u64,
    pub deadline_ns: u64,
    pub security_level: u32,
    pub connection_handle: u16,
    pub property: u16,
    pub value_length: u16,
    pub write: u8,
    pub local_tcid: u8,
    pub remote_tcid: u8,
    pub pi: u8,
    pub reserved: [u8; 2],
    pub value: [u8; 2042],
    pub tail: [u8; 6],
}
/// Duplicate a CLOEXEC notification fd;caller closes it. Poll only,never
/// read/write its counter. Before waiting,try next;after readiness retry next.
/// This fd carries no decision/Native authority and does not retain the caller.
/// Service close/unregister/owner loss wakes it;old request/context stays stale.
/// One consuming application per service.0/-errno,output unchanged on error.
/// # Safety
/// view live immutable;output exclusive aligned writable;no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_authorization_fd(
    view: *const SlkLocalService,
    output: *mut c_int,
) -> c_int {
    if view.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let result = unsafe { &*view }
        .approvals
        .as_ref()
        .ok_or(nix::libc::EOPNOTSUPP)
        .and_then(|q| q.fd());
    match result {
        Ok(fd) => {
            unsafe { output.write(fd.into_raw_fd()) };
            0
        }
        Err(e) => -e,
    }
}
/// Nonblocking next request;EAGAIN means no undelivered request. ESHUTDOWN means
/// local policy stopped,ESTALE original daemon lost. Output unchanged on error.
/// Keep one request alive until its decision/inspection finishes,then free it.
/// This function never queues an RPC or runs application code.
/// # Safety
/// view live;output exclusive aligned nonaliasing;no concurrent view free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_local_service_next_authorization(
    view: *const SlkLocalService,
    output: *mut *mut SlkAuthorizationRequest,
) -> c_int {
    if view.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let result = unsafe { &*view }
        .approvals
        .as_ref()
        .ok_or(nix::libc::EOPNOTSUPP)
        .and_then(|q| q.next());
    match result {
        Ok(inner) => {
            unsafe { output.write(Box::into_raw(Box::new(SlkAuthorizationRequest { inner }))) };
            0
        }
        Err(e) => -e,
    }
}
/// Copy original request context,even after expiry/close;no current qualification.
/// # Safety
/// request live immutable;output exclusive aligned writable and nonaliasing.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_authorization_request_info(
    request: *const SlkAuthorizationRequest,
    output: *mut SlkAuthorizationRequestInfo,
) -> c_int {
    if request.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let r = &unsafe { &*request }.inner;
    let p = r.prompt();
    let id = p.1;
    let mut value = SlkAuthorizationRequestInfo {
        controller: SlkControllerId {
            index: id.0,
            generation: id.1,
            reserved: [0; 6],
        },
        token: r.token(),
        request_id: p.0,
        connection_lifetime: id.2,
        security_epoch: id.4,
        deadline_ns: p.4,
        security_level: id.5,
        connection_handle: id.3,
        property: p.2,
        value_length: p.5.len() as u16,
        write: u8::from(p.3),
        local_tcid: id.6,
        remote_tcid: id.7,
        pi: id.8,
        reserved: [0; 2],
        value: [0; 2042],
        tail: [0; 6],
    };
    value.value[..p.5.len()].copy_from_slice(&p.5);
    unsafe { output.write(value) };
    0
}
/// Reply0/1 to THIS opaque request.0 means local policy accepted,not daemon
/// commit,USB/protocol ACK or application processing. Duplicate/old replies
/// ESTALE;expired ETIMEDOUT;stopped ESHUTDOWN. No new original deadline/retry.
/// # Safety
/// request live;no concurrent free. Never use inherited objects after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_authorization_request_reply(
    request: *const SlkAuthorizationRequest,
    allow: u32,
) -> c_int {
    if request.is_null() || allow > 1 {
        return -nix::libc::EINVAL;
    }
    match unsafe { &*request }.inner.reply(allow == 1) {
        Ok(()) => 0,
        Err(e) => -e,
    }
}
/// Release one request,NULL allowed. An unanswered request is denied;release
/// does not prove callback drain,remote cleanup or any physical completion.
/// # Safety
/// One live owned pointer,freed once;no concurrent calls/later use/fork copies.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_authorization_request_free(request: *mut SlkAuthorizationRequest) {
    if !request.is_null() {
        drop(unsafe { Box::from_raw(request) });
    }
}
