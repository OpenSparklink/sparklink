//! C views over the existing owner/lifetime-pinned application Client. No SSAP
//! codec, Engine, database, retry, native lease or second broker caller.
use crate::{ApplicationConnection, ffi_client::SlkClient, sync_client::Deadline};
use std::{ffi::c_int, sync::Arc};

/// A pinned physical connection observation, not a management lease or Grant.
/// Retains its originating caller. Release never disconnects the physical link.
pub struct SlkConnection {
    // Release the view before the last executor reference is joined.
    link: Arc<ApplicationConnection>,
    inner: Arc<crate::sync_client::SyncClient>,
}

/// Bind an existing canonical connection path at its current immutable identity.
/// Same path/byte/controller validation as open_channel; no address/handle lookup.
/// Returns0 or negative errno, output unchanged on error. The view retains the
/// original Client caller after slk_client_close, never follows daemon replacement.
/// # Safety
/// Inputs are live aligned immutable regions through the call; output is an
/// exclusive aligned writable pointer slot, not aliasing them. No concurrent
/// Client close. Caller releases a successful view once via connection_close.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_connection(
    client: *const SlkClient,
    controller: *const crate::ffi_client::SlkControllerId,
    path: *const u8,
    path_length: usize,
    deadline_ns: u64,
    output: *mut *mut SlkConnection,
) -> c_int {
    if client.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let (id, path) =
        match unsafe { crate::ffi_client::connection_input(controller, path, path_length) } {
            Ok(value) => value,
            Err(e) => return -e,
        };
    let caller = unsafe { &*client };
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        caller.inner.call(deadline, move |client| async move {
            client.connection(&id.path(), &path).await
        })
    });
    match result {
        Ok(link) => {
            let view = SlkConnection {
                link: Arc::new(link),
                inner: caller.inner.clone(),
            };
            unsafe { output.write(Box::into_raw(Box::new(view))) };
            0
        }
        Err(e) => -e,
    }
}

/// Release one owned view, NULL accepted. No implicit disconnect, service
/// unregister, remote cancellation or credit refund. Final executor release
/// joins bounded local work. Returned Channel fds have independent ownership.
/// # Safety
/// connection is NULL or one live owned pointer, freed once; no concurrent
/// operations/close or later use. As with Client, do not use after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_connection_close(connection: *mut SlkConnection) {
    if !connection.is_null() {
        drop(unsafe { Box::from_raw(connection) });
    }
}

const MAX_BUFFER: usize = 65535;

fn output_valid(buffer: *mut u8, capacity: usize, length: *mut usize) -> bool {
    !buffer.is_null() && (1..=MAX_BUFFER).contains(&capacity) && !length.is_null()
}

// Do not copy/truncate until the full response is available. An undersized
// buffer is a local result-delivery failure, not cancellation of the operation.
unsafe fn copy_result(
    result: Result<Vec<u8>, i32>,
    buffer: *mut u8,
    capacity: usize,
    length: *mut usize,
) -> c_int {
    match result {
        Ok(bytes) if bytes.len() > MAX_BUFFER => -nix::libc::EOVERFLOW,
        Ok(bytes) => {
            unsafe { length.write(bytes.len()) };
            if bytes.len() > capacity {
                return -nix::libc::ENOBUFS;
            }
            unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), buffer, bytes.len()) };
            0
        }
        Err(e) => -e,
    }
}

/// Execute the existing daemon SSAP read on this fixed lifetime. Returns the
/// same bytes as Rust RemoteSsap::read, without a second decoder or local echo.
/// Capacity1..65535 is a language-boundary memory budget, not a negotiated MTU.
/// ENOBUFS updates length but leaves buffer unchanged; the remote read already
/// ran, so do not retry as a size query. Other failures leave both unchanged.
/// The original absolute deadline covers the local queue and daemon operation.
/// The existing five-second protocol ceiling is captured before queueing. A
/// timeout cannot undo remote effects; success is the existing protocol result,
/// not application processing. Requires the broker's same boot/time namespace.
/// # Safety
/// connection remains live, with no concurrent close; buffer is an exclusive
/// capacity-byte writable region, length an exclusive aligned writable slot.
/// Neither aliases connection or each other. Same fork contract as Client.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_connection_ssap_read(
    connection: *const SlkConnection,
    handle: u16,
    minimum: u32,
    buffer: *mut u8,
    capacity: usize,
    length: *mut usize,
    deadline_ns: u64,
) -> c_int {
    if connection.is_null() || handle == 0 || minimum > 2 || !output_valid(buffer, capacity, length)
    {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*connection };
    let link = view.link.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let (deadline, original) = deadline.protocol()?;
        view.inner.call(deadline, move |_| async move {
            link.ssap().read(handle, minimum, original).await
        })
    });
    unsafe { copy_result(result, buffer, capacity, length) }
}

/// Execute the existing short-write RPC, returning its exact protocol result
/// bytes. No long-write fallback, truncation, method echo or new Engine. The
/// daemon's actual negotiated size/security rules remain authoritative.
/// value_length<=65535 is a language memory budget, not long-write support;
/// oversize is EMSGSIZE before copying. Empty values are allowed. No retries.
/// Output, deadline and remote-effect semantics are identical to ssap_read.
/// In particular ENOBUFS or timeout may follow an already committed write.
/// # Safety
/// Same connection/output contract as ssap_read. value is a live immutable
/// value_length-byte region (NULL only when empty), not aliasing writable outputs.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_connection_ssap_write(
    connection: *const SlkConnection,
    handle: u16,
    minimum: u32,
    value: *const u8,
    value_length: usize,
    buffer: *mut u8,
    capacity: usize,
    length: *mut usize,
    deadline_ns: u64,
) -> c_int {
    if connection.is_null()
        || handle == 0
        || minimum > 2
        || (value.is_null() && value_length != 0)
        || !output_valid(buffer, capacity, length)
    {
        return -nix::libc::EINVAL;
    }
    if value_length > MAX_BUFFER {
        return -nix::libc::EMSGSIZE;
    }
    let deadline = match Deadline::from_monotonic_ns(deadline_ns) {
        Ok(value) => value,
        Err(e) => return -e,
    };
    let (deadline, original) = match deadline.protocol() {
        Ok(value) => value,
        Err(error) => return -error,
    };
    let value = if value_length == 0 {
        Vec::new()
    } else {
        unsafe { std::slice::from_raw_parts(value, value_length) }.to_vec()
    };
    let view = unsafe { &*connection };
    let link = view.link.clone();
    let result = view.inner.call(deadline, move |_| async move {
        link.ssap().write(handle, value, minimum, original).await
    });
    unsafe { copy_result(result, buffer, capacity, length) }
}
