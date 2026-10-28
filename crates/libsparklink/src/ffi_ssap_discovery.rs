//! Immutable delivery of one existing SDK discovery result; no wire decoder,
//! remote cache, connection ownership, authorization or automatic retry.
use crate::{ffi_connection::SlkConnection, sync_client::Deadline};
use slk_contract::ssap as wire;
use std::ffi::c_int;

/// An owned historical observation. Does not retain a Client/Connection or
/// confer current lifetime, service availability, security or a Grant.
pub struct SlkSsapDiscoveryResult(wire::Discovery);

/// One bounded observed entry; unused array bytes and reserved bytes are zero.
/// UUID/descriptor bytes retain wire order. category0..4 or8..12; method3/11.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SlkSsapEntry {
    pub operations: u32,
    pub handle: u16,
    pub end: u16,
    pub category: u8,
    pub members: u8,
    pub uuid_length: u8,
    pub descriptor_length: u8,
    pub uuid: [u8; 16],
    pub descriptors: [u8; 255],
    pub reserved: [u8; 1],
}
impl SlkSsapEntry {
    fn from_validated(e: &wire::Entry) -> Self {
        let mut out = Self {
            operations: e.4,
            handle: e.1,
            end: e.2,
            category: e.0,
            members: e.6,
            uuid_length: e.3.len() as u8,
            descriptor_length: e.5.len() as u8,
            uuid: [0; 16],
            descriptors: [0; 255],
            reserved: [0; 1],
        };
        out.uuid[..e.3.len()].copy_from_slice(&e.3);
        out.descriptors[..e.5.len()].copy_from_slice(&e.5);
        out
    }
}

/// Perform one management-only SSAP discovery via the same SDK/daemon Engine.
/// kind0 structure,1 primary hierarchy,3 property,4 method; UUID empty/2/16bytes.
/// Original CLOCK_MONOTONIC deadline covers local queue/identity/daemon/pages;
/// five-second ceiling captured before queueing. Success returns one immutable
/// bounded result (80entries/96transactions); failure leaves output unchanged.
/// No retries or partial result. Timeout cannot undo already submitted work.
/// # Safety
/// connection is live without concurrent close; uuid is immutable uuid_length
/// bytes (NULL allowed only for empty). output is an exclusive aligned pointer
/// slot, not aliasing inputs. Same no-use-after-fork contract as Connection.
/// Release successful output exactly once via slk_ssap_discovery_free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_connection_ssap_discover(
    connection: *const SlkConnection,
    uuid: *const u8,
    uuid_length: usize,
    kind: u8,
    deadline_ns: u64,
    output: *mut *mut SlkSsapDiscoveryResult,
) -> c_int {
    if connection.is_null()
        || output.is_null()
        || !matches!(uuid_length, 0 | 2 | 16)
        || (uuid_length != 0 && uuid.is_null())
        || !matches!(kind, 0 | 1 | 3 | 4)
    {
        return -nix::libc::EINVAL;
    }
    let uuid = if uuid_length == 0 {
        vec![]
    } else {
        unsafe { std::slice::from_raw_parts(uuid, uuid_length) }.to_vec()
    };
    let connection = unsafe { &*connection };
    let link = connection.link.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns)
        .and_then(|d| d.protocol())
        .and_then(|(d, original)| {
            connection.inner.call(d, move |_| async move {
                link.ssap().discover_until(uuid, kind, original).await
            })
        });
    match result {
        Ok(value) => {
            unsafe { output.write(Box::into_raw(Box::new(SlkSsapDiscoveryResult(value)))) };
            0
        }
        Err(e) => -e,
    }
}

/// Copy immutable result counts; no RPC or revalidation of current state.
/// # Safety
/// result is live; entries/pages are exclusive aligned writable slots, mutually
/// disjoint and not aliasing result. No concurrent free. Failure changes neither.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_discovery_counts(
    result: *const SlkSsapDiscoveryResult,
    entries: *mut usize,
    pages: *mut usize,
) -> c_int {
    if result.is_null() || entries.is_null() || pages.is_null() {
        return -nix::libc::EINVAL;
    }
    let result = unsafe { &*result };
    unsafe {
        entries.write(result.0.0.len());
        pages.write(result.0.1.len());
    }
    0
}

/// Copy an entry by zero-based index; out-of-range ENOENT, output unchanged.
/// # Safety
/// result remains live; output is exclusive aligned writable SlkSsapEntry,
/// disjoint from result. No concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_discovery_entry(
    result: *const SlkSsapDiscoveryResult,
    index: usize,
    output: *mut SlkSsapEntry,
) -> c_int {
    if result.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    match unsafe { &*result }.0.0.get(index) {
        Some(entry) => {
            unsafe { output.write(SlkSsapEntry::from_validated(entry)) };
            0
        }
        None => -nix::libc::ENOENT,
    }
}

/// Copy request(response=0) or reply(response=1) of one zero-based transaction.
/// Capacity1..2048; ENOBUFS sets required length without changing buffer. Other
/// failures change neither. This is a local immutable copy, so a larger-buffer
/// retry never retransmits a request. Raw bytes are not peer-delivery proof.
/// # Safety
/// result remains live; buffer has capacity exclusive writable bytes; length
/// is exclusive aligned storage. All disjoint, no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_discovery_trace(
    result: *const SlkSsapDiscoveryResult,
    index: usize,
    response: u8,
    buffer: *mut u8,
    capacity: usize,
    length: *mut usize,
) -> c_int {
    if result.is_null()
        || buffer.is_null()
        || length.is_null()
        || response > 1
        || !(1..=wire::DISCOVERY_RESPONSE_BYTES).contains(&capacity)
    {
        return -nix::libc::EINVAL;
    }
    let Some((request, reply)) = unsafe { &*result }.0.1.get(index) else {
        return -nix::libc::ENOENT;
    };
    let bytes = if response == 0 { request } else { reply };
    unsafe { length.write(bytes.len()) };
    if bytes.len() > capacity {
        return -nix::libc::ENOBUFS;
    }
    unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), buffer, bytes.len()) };
    0
}

/// Free this immutable result; NULL accepted. No RPC, lease or connection action.
/// # Safety
/// NULL or one successful owned result, freed once, with no concurrent read or
/// subsequent use. Result reads never access the originating executor.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_discovery_free(result: *mut SlkSsapDiscoveryResult) {
    if !result.is_null() {
        drop(unsafe { Box::from_raw(result) });
    }
}
