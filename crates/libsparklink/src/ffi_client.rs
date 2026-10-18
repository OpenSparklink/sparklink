//! Current synchronous C application broker boundary. No Native controller fd.
use crate::sync_client::{Deadline, SyncClient};
use std::{ffi::c_int, os::fd::IntoRawFd, sync::Arc};

/// Opaque caller connection. One bounded local executor; not a controller lease.
pub struct SlkClient {
    pub(crate) inner: Arc<SyncClient>,
}

/// Immutable registration identity only, not Ready, authorization or security.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SlkControllerId {
    pub generation: u64,
    pub index: u16,
    pub reserved: [u8; 6],
}

// Shared language-boundary input validation, not an identity/authorization cache.
// Caller guarantees valid immutable regions; no operation or output mutation.
pub(crate) unsafe fn connection_input(
    controller: *const SlkControllerId,
    path: *const u8,
    path_length: usize,
) -> Result<(slk_contract::ControllerId, String), i32> {
    if controller.is_null() || path.is_null() || !(1..=256).contains(&path_length) {
        return Err(nix::libc::EINVAL);
    }
    let id = unsafe { *controller };
    if id.generation == 0 || id.reserved != [0; 6] {
        return Err(nix::libc::EINVAL);
    }
    let raw = unsafe { std::slice::from_raw_parts(path, path_length) };
    let path = match std::str::from_utf8(raw) {
        Ok(path) if !path.contains('\0') => path.to_owned(),
        _ => return Err(nix::libc::EINVAL),
    };
    Ok((
        slk_contract::ControllerId {
            index: id.index,
            generation: id.generation,
        },
        path,
    ))
}

/// Connect to the system broker, pinning its current unique owner. All deadlines
/// here are absolute CLOCK_MONOTONIC nanoseconds, future and at most 30 seconds
/// away. Returns 0 or -errno; output unchanged on failure. No fallback/retry.
/// # Safety
/// output is nonnull and points to an exclusive aligned writable pointer slot.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_open_system(
    deadline_ns: u64,
    output: *mut *mut SlkClient,
) -> c_int {
    if output.is_null() {
        return -nix::libc::EINVAL;
    }
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(SyncClient::open_system);
    match result {
        Ok(inner) => {
            unsafe {
                output.write(Box::into_raw(Box::new(SlkClient {
                    inner: Arc::new(inner),
                })))
            };
            0
        }
        Err(e) => -e,
    }
}

/// Release this Client reference. Null is allowed. Derived connection views
/// retain the same executor/broker caller until their final release; it then
/// stops and joins. Does not close returned channel fds, disconnect a physical
/// link or revoke another application's Grant. Remote effects may outlive timeout.
/// # Safety
/// client is null or one live pointer returned by open_system, freed once only;
/// no concurrent calls or later use. Never share a client across fork;
/// exec/spawn before creating one in a child. Channel fd semantics unchanged.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_close(client: *mut SlkClient) {
    if !client.is_null() {
        drop(unsafe { Box::from_raw(client) });
    }
}

/// List registered controller identities, not Ready. Capacity 0 queries count.
/// Capacity is at most 256. On ENOBUFS count is the required length and buffer
/// remains unchanged. Other failures leave all outputs unchanged. No truncation.
/// Registry can change between calls; each call rechecks the pinned owner.
/// # Safety
/// client is live for the call; count is exclusive aligned writable. buffer is
/// null only when capacity=0, otherwise exclusive aligned capacity-sized region.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_controllers(
    client: *const SlkClient,
    buffer: *mut SlkControllerId,
    capacity: usize,
    count: *mut usize,
    deadline_ns: u64,
) -> c_int {
    if client.is_null() || count.is_null() || capacity > 256 || (capacity != 0 && buffer.is_null())
    {
        return -nix::libc::EINVAL;
    }
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        unsafe { &*client }
            .inner
            .call(deadline, |client| async move { client.controllers().await })
    });
    match result {
        Ok(ids) if ids.len() <= 256 => {
            unsafe { count.write(ids.len()) };
            if capacity == 0 {
                return 0;
            }
            if capacity < ids.len() {
                return -nix::libc::ENOBUFS;
            }
            for (n, id) in ids.into_iter().enumerate() {
                unsafe {
                    buffer.add(n).write(SlkControllerId {
                        generation: id.generation,
                        index: id.index,
                        reserved: [0; 6],
                    })
                };
            }
            0
        }
        Ok(_) => -nix::libc::EOVERFLOW,
        Err(e) => -e,
    }
}

/// Request an application channel for an existing exact connection object.
/// Path is UTF-8 bytes (1..256, no NUL), not a C string. reserved must be zero.
/// directions=1 TX,2 RX,3 both; minimum=0..2; broker/kernel enforce actual rights.
/// Returns an owned fd only after the shared Channel socket-domain check. fd
/// availability is not negotiation Ready, security installation or peer delivery.
/// On error output is unchanged. Timeout ends local waiting only; remote request
/// may have executed. No automatic retry, downgrade, disconnect or cancellation.
/// # Safety
/// client, controller and path are live immutable regions through the call;
/// output is exclusive aligned writable and does not alias them. No concurrent
/// client close. Caller owns successful fd and must close it independently.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_open_channel(
    client: *const SlkClient,
    controller: *const SlkControllerId,
    path: *const u8,
    path_length: usize,
    directions: u32,
    minimum: u32,
    deadline_ns: u64,
    output: *mut c_int,
) -> c_int {
    if client.is_null()
        || output.is_null()
        || directions == 0
        || directions & !3 != 0
        || minimum > 2
    {
        return -nix::libc::EINVAL;
    }
    let (id, path) = match unsafe { connection_input(controller, path, path_length) } {
        Ok(value) => value,
        Err(e) => return -e,
    };
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        unsafe { &*client }
            .inner
            .call(deadline, move |client| async move {
                client
                    .connection(&id.path(), &path)
                    .await?
                    .open_channel(directions, minimum)
                    .await
            })
    });
    match result {
        Ok(channel) => {
            unsafe { output.write(channel.into_owned_fd().into_raw_fd()) };
            0
        }
        Err(e) => -e,
    }
}
