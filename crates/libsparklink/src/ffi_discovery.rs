//! C delivery view of the existing Rust discovery lease; no Native management,
//! scanner, event decoder or second permission/lease state machine.
use crate::{
    ApplicationError,
    discovery::DiscoverySession,
    ffi_client::{SlkClient, SlkControllerId, controller_input},
    sync_client::{Deadline, SyncClient},
};
use slk_contract::discovery as wire;
const _: () = assert!(wire::MAX_DATA == 255 && wire::CAPACITY == 32);
use std::{
    ffi::c_int,
    sync::{Arc, Mutex},
};

/// Batch metadata, not Ready or lossless delivery. All reserved bytes are zero.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SlkDiscoveryBatch {
    pub generation: u64,
    pub session: u64,
    pub dropped: u64,
    pub kernel_lost: u64,
    pub version: u16,
    pub reserved: [u8; 6],
}

/// Validated observation. Only data[0..data_length] is meaningful; unused data
/// and reserved bytes are zero. rssi_known=0 denotes RSSI127 (unknown).
/// kernel_boottime_ns belongs to the daemon's kernel clock, not caller RTT.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SlkDiscoveryReport {
    pub sequence: u64,
    pub kernel_boottime_ns: u64,
    pub rssi: i16,
    pub data_length: u16,
    pub address_type: u8,
    pub rssi_known: u8,
    pub address: [u8; 6],
    pub header: [u8; 23],
    pub data: [u8; 255],
    pub reserved: [u8; 6],
}
impl SlkDiscoveryReport {
    fn encode(row: &wire::Report) -> Self {
        // The sole Rust Session validates all lengths, identity and filters.
        let mut out = Self {
            sequence: row.sequence,
            kernel_boottime_ns: row.kernel_boottime_ns,
            rssi: row.rssi,
            data_length: row.data.len() as u16,
            address_type: row.address_type,
            rssi_known: row.rssi_known.into(),
            address: [0; 6],
            header: [0; 23],
            data: [0; 255],
            reserved: [0; 6],
        };
        out.address.copy_from_slice(&row.address);
        out.header.copy_from_slice(&row.header);
        out.data[..row.data.len()].copy_from_slice(&row.data);
        out
    }
}
struct Delivery {
    session: tokio::sync::Mutex<DiscoverySession>,
    // A bounded single batch, filled without await before replying to C. This
    // preserves already-received delivery on a local response/timeout race.
    pending: Mutex<Option<Arc<wire::Batch>>>,
}
fn poisoned() -> ApplicationError {
    ApplicationError::Identity("discovery delivery poisoned")
}
impl Delivery {
    async fn next(
        &self,
        client: crate::Client,
        wait: bool,
        deadline: slk_channel::deadline::Deadline,
    ) -> Result<Arc<wire::Batch>, ApplicationError> {
        client.check_owner().await?;
        let mut session = self.session.lock().await;
        if session.is_closed() {
            return Err(ApplicationError::Invalid("discovery session closed"));
        }
        if let Some(batch) = self.pending.lock().map_err(|_| poisoned())?.clone() {
            deadline.remaining()?;
            return Ok(batch);
        }
        let batch = Arc::new(session.read(wait, deadline).await?);
        *self.pending.lock().map_err(|_| poisoned())? = Some(batch.clone());
        Ok(batch)
    }
    fn acknowledge(&self, batch: &Arc<wire::Batch>) -> Result<(), i32> {
        let mut pending = self.pending.lock().map_err(|_| nix::libc::ESTALE)?;
        if !pending.as_ref().is_some_and(|p| Arc::ptr_eq(p, batch)) {
            return Err(nix::libc::ESTALE);
        }
        *pending = None;
        Ok(())
    }
}

/// Caller-owned discovery view, sharing the original Client executor and owner.
/// It is an application scan lease, never a controller-management lease.
pub struct SlkDiscovery {
    // Drop local session/delivery before joining the final executor reference.
    identity: slk_contract::ControllerId,
    id: u64,
    delivery: Arc<Delivery>,
    executor: Arc<SyncClient>,
    pub(crate) call: Mutex<()>,
}

/// Acquire the existing passive frame-1 discovery lease. prefix length0..64,
/// minimum_rssi=-128..20 (-128 includes unknown), duration_ms250..60000.
/// deadline_ns is future absolute CLOCK_MONOTONIC, <=30s, same boot/time domain
/// as the daemon; it covers the local queue and RPC. 0/-errno, output unchanged
/// on failure. Timeout may leave a finite server lease until expiry/owner loss;
/// no automatic retry, guessed ID, global scan stop or downgrade.
/// # Safety
/// client/controller are live immutable objects; prefix is a valid immutable
/// length-byte region, null only for0. output is an exclusive aligned pointer
/// slot, nonaliasing inputs. No concurrent Client close, invalid pointer or fork use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_discover(
    client: *const SlkClient,
    controller: *const SlkControllerId,
    prefix: *const u8,
    length: usize,
    minimum_rssi: i16,
    duration_ms: u32,
    deadline_ns: u64,
    output: *mut *mut SlkDiscovery,
) -> c_int {
    if client.is_null()
        || output.is_null()
        || length > wire::MAX_PREFIX
        || (length != 0 && prefix.is_null())
    {
        return -nix::libc::EINVAL;
    }
    let id = match unsafe { controller_input(controller) } {
        Ok(id) => id,
        Err(e) => return -e,
    };
    let prefix = if length == 0 {
        &[]
    } else {
        unsafe { std::slice::from_raw_parts(prefix, length) }
    };
    if !wire::valid_filter(prefix, minimum_rssi, duration_ms) {
        return -nix::libc::EINVAL;
    }
    let executor = unsafe { &*client }.inner.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let original = slk_channel::deadline::Deadline::from_monotonic_ns(deadline_ns)
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))?;
        let prefix = prefix.to_vec();
        executor.call(deadline, move |client| async move {
            client
                .discover(id, prefix, minimum_rssi, duration_ms, original)
                .await
        })
    });
    match result {
        Ok(session) => {
            let view = SlkDiscovery {
                identity: session.controller(),
                id: session.id(),
                delivery: Arc::new(Delivery {
                    session: tokio::sync::Mutex::new(session),
                    pending: Mutex::new(None),
                }),
                executor,
                call: Mutex::new(()),
            };
            unsafe { output.write(Box::into_raw(Box::new(view))) };
            0
        }
        Err(e) => -e,
    }
}

/// Immutable acquired lease identity only; not Ready, active scan or cleanup.
/// Returns0/-errno; outputs unchanged on error, reserved bytes always zero.
/// # Safety
/// view remains live; controller/session are exclusive aligned nonaliasing
/// writable slots. No concurrent free or invalid pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_identity(
    view: *const SlkDiscovery,
    controller: *mut SlkControllerId,
    session: *mut u64,
) -> c_int {
    if view.is_null() || controller.is_null() || session.is_null() {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    unsafe {
        controller.write(SlkControllerId {
            generation: view.identity.generation,
            index: view.identity.index,
            reserved: [0; 6],
        });
        session.write(view.id);
    }
    0
}

/// One destructive reader. flags:bit0 wait for reports,bit1 peek; other bits
/// rejected. capacity0..32, null buffer only for0. ENOBUFS sets count only and
/// retains the whole batch; other errors change no outputs. Success copies
/// metadata/count and whole reports, never truncates. Peek and a locally
/// received timeout retain one batch. Remote read timeout/cancel may still lose
/// a consumed reply; counters expose known gaps, not lossless observation.
/// Concurrent read/release on this view returns EAGAIN; a blocking read shares
/// the Client executor queue. Original deadline is never renewed.
/// # Safety
/// view stays live; output/count/buffer are exclusive, aligned, valid writable
/// nonaliasing regions, buffer sized for capacity reports. No concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_read(
    view: *const SlkDiscovery,
    output: *mut SlkDiscoveryBatch,
    buffer: *mut SlkDiscoveryReport,
    capacity: usize,
    count: *mut usize,
    flags: u32,
    deadline_ns: u64,
) -> c_int {
    if view.is_null()
        || output.is_null()
        || count.is_null()
        || capacity > wire::CAPACITY
        || (capacity != 0 && buffer.is_null())
        || flags > 3
    {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let _call = match view.call.try_lock() {
        Ok(v) => v,
        Err(std::sync::TryLockError::WouldBlock) => return -nix::libc::EAGAIN,
        Err(_) => return -nix::libc::ESTALE,
    };
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let original = slk_channel::deadline::Deadline::from_monotonic_ns(deadline_ns)
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))?;
        let delivery = view.delivery.clone();
        view.executor.call(deadline, move |client| async move {
            delivery.next(client, flags & 1 != 0, original).await
        })
    });
    match result {
        Ok(batch) => {
            if let Err(e) = Deadline::from_monotonic_ns(deadline_ns) {
                return -e;
            }
            if capacity < batch.reports.len() {
                unsafe { count.write(batch.reports.len()) };
                return -nix::libc::ENOBUFS;
            }
            if flags & 2 == 0
                && let Err(e) = view.delivery.acknowledge(&batch)
            {
                return -e;
            }
            for (n, row) in batch.reports.iter().enumerate() {
                unsafe { buffer.add(n).write(SlkDiscoveryReport::encode(row)) };
            }
            unsafe {
                output.write(SlkDiscoveryBatch {
                    generation: batch.generation,
                    session: batch.session,
                    dropped: batch.dropped,
                    kernel_lost: batch.kernel_lost,
                    version: batch.version,
                    reserved: [0; 6],
                });
                count.write(batch.reports.len());
            };
            0
        }
        Err(e) => -e,
    }
}

/// Explicitly withdraw only this discovery lease. stopped=1 only if the broker
/// confirms last-lease physical STOP;0 means this lease released while shared
/// scan remains. 0/-errno, output unchanged on failure. A timeout/error is not
/// proof of cleanup: local close may already be terminal and must not be retried
/// as a fresh lease. No disconnect or management release; pending data becomes
/// unreadable once the underlying Rust session begins close.
/// # Safety
/// view is live,stopped is an exclusive aligned writable slot; no concurrent free.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_release(
    view: *const SlkDiscovery,
    deadline_ns: u64,
    stopped: *mut u32,
) -> c_int {
    if view.is_null() || stopped.is_null() {
        return -nix::libc::EINVAL;
    }
    let view = unsafe { &*view };
    let _call = match view.call.try_lock() {
        Ok(v) => v,
        Err(std::sync::TryLockError::WouldBlock) => return -nix::libc::EAGAIN,
        Err(_) => return -nix::libc::ESTALE,
    };
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let original = slk_channel::deadline::Deadline::from_monotonic_ns(deadline_ns)
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))?;
        let delivery = view.delivery.clone();
        view.executor.call(deadline, move |_client| async move {
            delivery.session.lock().await.close(original).await
        })
    });
    match result {
        Ok(value) => {
            unsafe { stopped.write(value.into()) };
            0
        }
        Err(e) => -e,
    }
}

/// Free local delivery and this caller reference only,NULL allowed. Does not
/// report or guarantee remote STOP. Call release first to observe that result;
/// otherwise owner loss/original finite lease expiry bound server cleanup.
/// Other views can keep the caller alive after this free. Final executor join
/// waits bounded local work; Client close alone does not invalidate this view.
/// # Safety
/// view is NULL or one live owned pointer,freed once,no concurrent calls or later use.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_discovery_free(view: *mut SlkDiscovery) {
    if !view.is_null() {
        drop(unsafe { Box::from_raw(view) });
    }
}
