//! Thin synchronous views of the sole Rust Subscription; no codec, wire loop,
//! local security state or second protocol/lease implementation.
use crate::{
    ffi_connection::SlkConnection,
    ssap::subscription::Subscription,
    sync_client::{Deadline, SyncClient},
};
use slk_contract::ssap::subscription as wire;
use std::{
    ffi::c_int,
    sync::{Arc, Mutex},
};

/// This lease's routing and configuration ownership are released. Without
/// REMOTE_RETAINED, the last remote CPCD configuration was verified off.
pub const SLK_SSAP_SUBSCRIPTION_CLEANUP_CONFIRMED: u32 = 1;
/// Other same-scope leases retained the remote CPCD at this terminal
/// observation. Only valid with CLEANUP_CONFIRMED, not a current-state claim.
pub const SLK_SSAP_SUBSCRIPTION_REMOTE_RETAINED: u32 = 2;
const _: () = assert!(SLK_SSAP_SUBSCRIPTION_CLEANUP_CONFIRMED == wire::CLEANUP_CONFIRMED);
const _: () = assert!(SLK_SSAP_SUBSCRIPTION_REMOTE_RETAINED == wire::REMOTE_RETAINED);

/// Last validated lease observation; not Ready or future Native authorization.
/// Handles after handle_count and reserved bytes are zero. State0..3 follows
/// the Rust lease; token is scoped to the original bus owner/physical lifetime.
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug, Default)]
pub struct SlkSsapSubscriptionInfo {
    pub generation: u64,
    pub lifetime: u64,
    pub security_epoch: u64,
    pub token: u64,
    pub expires_ns: u64,
    pub version: u32,
    pub controller: u16,
    pub handle: u16,
    pub capacity: u16,
    pub handle_count: u16,
    pub modes: u8,
    pub state: u8,
    pub reserved: [u8; 2],
    pub handles: [u16; 32],
}
impl SlkSsapSubscriptionInfo {
    fn encode(info: &wire::Info) -> Self {
        let mut out = Self {
            generation: info.generation,
            lifetime: info.lifetime,
            security_epoch: info.security_epoch,
            token: info.token,
            expires_ns: info.expires_ns,
            version: info.version,
            controller: info.controller,
            handle: info.handle,
            capacity: info.capacity,
            handle_count: info.handles.len() as u16,
            modes: info.modes,
            state: info.state,
            ..Self::default()
        };
        out.handles[..info.handles.len()].copy_from_slice(&info.handles);
        out
    }
}

/// One complete existing PDU with its original validated receipt facts.
/// Only pdu[0..pdu_length] is meaningful;unused/reserved bytes are zero.
#[repr(C, align(8))]
#[derive(Clone, Copy)]
pub struct SlkSsapSubscriptionPacket {
    pub sequence: u64,
    pub security_epoch: u64,
    pub security_level: u32,
    pub pdu_length: u16,
    pub indication: u8,
    pub reserved: [u8; 1],
    pub pdu: [u8; 2048],
}
impl SlkSsapSubscriptionPacket {
    const fn empty() -> Self {
        Self {
            sequence: 0,
            security_epoch: 0,
            security_level: 0,
            pdu_length: 0,
            indication: 0,
            reserved: [0],
            pdu: [0; 2048],
        }
    }
    fn encode(packet: &wire::Packet) -> Self {
        let mut out = Self {
            sequence: packet.sequence,
            security_epoch: packet.security_epoch,
            security_level: packet.security_level,
            pdu_length: packet.pdu.len() as u16,
            indication: packet.indication.into(),
            ..Self::empty()
        };
        out.pdu[..packet.pdu.len()].copy_from_slice(&packet.pdu);
        out
    }
}

/// One bounded destructive-read result. flags bit0 confirms this lease's
/// routing/configuration ownership release. bit1 means other same-scope leases
/// retained the remote CPCD at that terminal observation (only valid with bit0).
/// bit0 without bit1 confirms the last remote CPCD was verified off. Neither
/// means full callback/Native drain or application processing.
/// Cumulative counters and sequence gaps are not a lossless-delivery promise.
/// Only packets[0..count] are meaningful;all unused/reserved bytes are zero.
#[repr(C, align(8))]
pub struct SlkSsapSubscriptionBatch {
    pub info: SlkSsapSubscriptionInfo,
    pub last_sequence: u64,
    pub dropped_notifications: u64,
    pub refused_indications: u64,
    pub discarded_on_close: u64,
    pub flags: u32,
    pub count: u16,
    pub reason: u8,
    pub reserved: [u8; 1],
    pub packets: [SlkSsapSubscriptionPacket; 16],
}
impl SlkSsapSubscriptionBatch {
    fn encode(batch: &wire::Batch) -> Self {
        // The shared Rust Subscription already validated every boundary,scope,
        // counter and production PDU. This is representation conversion only.
        let mut out = Self {
            info: SlkSsapSubscriptionInfo::encode(&batch.info),
            last_sequence: batch.last_sequence,
            dropped_notifications: batch.dropped_notifications,
            refused_indications: batch.refused_indications,
            discarded_on_close: batch.discarded_on_close,
            flags: batch.flags,
            count: batch.packets.len() as u16,
            reason: batch.reason,
            reserved: [0],
            packets: [SlkSsapSubscriptionPacket::empty(); 16],
        };
        for (dest, source) in out.packets.iter_mut().zip(&batch.packets) {
            *dest = SlkSsapSubscriptionPacket::encode(source);
        }
        out
    }
}
const _: () = assert!(std::mem::size_of::<SlkSsapSubscriptionInfo>() == 120);
const _: () = assert!(std::mem::offset_of!(SlkSsapSubscriptionInfo, handles) == 56);
const _: () = assert!(std::mem::size_of::<SlkSsapSubscriptionPacket>() == 2072);
const _: () = assert!(std::mem::offset_of!(SlkSsapSubscriptionPacket, pdu) == 24);
const _: () = assert!(std::mem::size_of::<SlkSsapSubscriptionBatch>() == 33312);
const _: () = assert!(std::mem::offset_of!(SlkSsapSubscriptionBatch, packets) == 160);

/// Retains the originating caller and shared executor,not the parent C view.
/// This is an opaque lease,not a socket fd with dup/SCM_RIGHTS semantics.
pub struct SlkSsapSubscription {
    session: Arc<tokio::sync::Mutex<Subscription>>,
    executor: Arc<SyncClient>,
    call: Mutex<()>,
}
fn lock(view: &SlkSsapSubscription) -> Result<std::sync::MutexGuard<'_, ()>, c_int> {
    view.call.try_lock().map_err(|e| match e {
        std::sync::TryLockError::WouldBlock => -nix::libc::EAGAIN,
        _ => -nix::libc::ESTALE,
    })
}

/// Acquire the existing remote SSAP receive lease. Count1..32 unique discovered
/// handles,modes1..3,duration250..60000ms;scope-compatible leases share the
/// existing physical actor,subject to bounded admission.
/// 0/-errno;output unchanged on failure. Original absolute deadline includes
/// executor queueing and is capped at5s before queueing. Timeout is uncertain;
/// no automatic retry. Parent Connection/Client close does not release this view.
/// # Safety
/// connection/handles are live aligned immutable regions for the call;output
/// is an exclusive aligned pointer slot,nonaliasing them. No concurrent close,
/// fork use or invalid pointers. Free a successful owned view exactly once.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_connection_ssap_subscribe(
    connection: *const SlkConnection,
    handles: *const u16,
    count: usize,
    modes: u32,
    duration_ms: u32,
    deadline_ns: u64,
    output: *mut *mut SlkSsapSubscription,
) -> c_int {
    if connection.is_null()
        || handles.is_null()
        || output.is_null()
        || !(1..=32).contains(&count)
        || !(1..=3).contains(&modes)
    {
        return -nix::libc::EINVAL;
    }
    let handles = unsafe { std::slice::from_raw_parts(handles, count) };
    if !wire::valid_request(handles, modes as u8, duration_ms) {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*connection };
    let link = view.link.clone();
    let handles = handles.to_vec();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let (deadline, original) = deadline.protocol()?;
        view.inner.call(deadline, move |_| async move {
            link.ssap()
                .subscribe(handles, modes as u8, duration_ms, original)
                .await
        })
    });
    match result {
        Ok(session) => {
            let owned = SlkSsapSubscription {
                session: Arc::new(tokio::sync::Mutex::new(session)),
                executor: view.inner.clone(),
                call: Mutex::new(()),
            };
            unsafe { output.write(Box::into_raw(Box::new(owned))) };
            0
        }
        Err(error) => -error,
    }
}

/// Last locally validated observation,without RPC or renewed authority. EAGAIN
/// if another operation is live;0/-errno,output unchanged on error.
/// # Safety
/// view is live,output is an exclusive aligned writable Info,nonaliasing view.
/// No concurrent free or fork use. This contract applies to all functions below.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_subscription_info(
    view: *const SlkSsapSubscription,
    output: *mut SlkSsapSubscriptionInfo,
) -> c_int {
    if view.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let _call = match lock(view) {
        Ok(v) => v,
        Err(e) => return e,
    };
    let Ok(session) = view.session.try_lock() else {
        return -nix::libc::EAGAIN;
    };
    unsafe { output.write(SlkSsapSubscriptionInfo::encode(session.info())) };
    0
}

/// Read one full finite batch;wait0/1 only,no peek or size-query retry. Original
/// deadline<=10s covers queue/RPC;0/-errno,output unchanged on error. A consumed
/// remote reply can be uncertain after local timeout/cancellation. No truncation
/// or silent retry;protocol ACK is not application processing. Concurrent calls
/// return EAGAIN. Output is always a complete33312-byte Batch.
/// # Safety
/// Same live view contract as info;output is a full exclusive aligned writable
/// Batch,nonaliasing view. No concurrent free,invalid pointers or fork use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_subscription_read(
    view: *const SlkSsapSubscription,
    wait: u32,
    output: *mut SlkSsapSubscriptionBatch,
    deadline_ns: u64,
) -> c_int {
    if view.is_null() || output.is_null() || wait > 1 {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let _call = match lock(view) {
        Ok(v) => v,
        Err(e) => return e,
    };
    let session = view.session.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let (deadline, original) = deadline.bounded(std::time::Duration::from_secs(10))?;
        view.executor.call(deadline, move |_| async move {
            let mut session = session.lock().await;
            if session.is_closed() {
                return Err(crate::ApplicationError::Invalid("subscription closed"));
            }
            session.read(wait != 0, original).await
        })
    });
    match result {
        Ok(batch) => {
            unsafe { output.write(SlkSsapSubscriptionBatch::encode(&batch)) };
            0
        }
        Err(error) => -error,
    }
}

/// Renew the existing Rust lease only,250..60000ms. Original<=5s,0/-errno;
/// output unchanged on failure. An uncertain renewal is never automatically
/// retried and does not renew any packet/read/cleanup deadline.
/// # Safety
/// Same live view and exclusive aligned Info output contract as info.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_subscription_renew(
    view: *const SlkSsapSubscription,
    duration_ms: u32,
    output: *mut SlkSsapSubscriptionInfo,
    deadline_ns: u64,
) -> c_int {
    if view.is_null() || output.is_null() || !(250..=60000).contains(&duration_ms) {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let _call = match lock(view) {
        Ok(v) => v,
        Err(e) => return e,
    };
    let session = view.session.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let (deadline, original) = deadline.protocol()?;
        view.executor.call(deadline, move |_| async move {
            session.lock().await.renew(duration_ms, original).await
        })
    });
    match result {
        Ok(info) => {
            unsafe { output.write(SlkSsapSubscriptionInfo::encode(&info)) };
            0
        }
        Err(error) => -error,
    }
}

/// Explicit lease-release receipt through the same Rust lease. Original<=5s;
/// inspect REMOTE_RETAINED: another lease can retain the physical CPCD.
/// 0/-errno,output unchanged on failure. Failure/timeout is not confirmed cleanup;
/// local admission may already be closed. Does not free the view or disconnect.
/// # Safety
/// Same full exclusive aligned Batch output/live view contract as read.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_subscription_release(
    view: *const SlkSsapSubscription,
    output: *mut SlkSsapSubscriptionBatch,
    deadline_ns: u64,
) -> c_int {
    if view.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let _call = match lock(view) {
        Ok(v) => v,
        Err(e) => return e,
    };
    let session = view.session.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let (deadline, original) = deadline.protocol()?;
        view.executor.call(deadline, move |_| async move {
            session.lock().await.close(original).await
        })
    });
    match result {
        Ok(batch) => {
            unsafe { output.write(SlkSsapSubscriptionBatch::encode(&batch)) };
            0
        }
        Err(error) => -error,
    }
}

/// Free local ownership only,NULL allowed. Not a cleanup receipt. Call release
/// first to observe lease release (remote off only without REMOTE_RETAINED);
/// otherwise original owner loss/finite lease
/// expiry bounds daemon cleanup. Final executor release joins bounded local work.
/// # Safety
/// view is NULL or one live owned pointer,freed once;no concurrent calls or later
/// use. Never use/free an inherited object after fork.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_ssap_subscription_free(view: *mut SlkSsapSubscription) {
    if !view.is_null() {
        drop(unsafe { Box::from_raw(view) });
    }
}
