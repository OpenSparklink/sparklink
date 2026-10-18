//! Language views over the one production ControllerEvents implementation.
//! One retained observation prevents timeout/short-buffer delivery loss. No
//! Native fd, Host, hardware cache or independent event decoder lives here.
use crate::{
    ApplicationError,
    controller_events::{ControllerEvent, ControllerEvents},
    ffi_client::{SlkClient, SlkControllerId},
    sync_client::{Deadline, SyncClient},
};
use std::{
    ffi::c_int,
    sync::{Arc, Mutex},
};

/// A directory observation, not Ready, Down, authorization or a drain barrier.
/// kind:1 Snapshot,2 Published,3 Withdrawn,4 Gap. sequence: snapshot cursor,
/// event sequence or Gap.after. oldest/current are nonzero only for Gap.
/// Controller identities are returned separately; reserved is always zero.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SlkControllerEvent {
    pub sequence: u64,
    pub oldest: u64,
    pub current: u64,
    pub kind: u32,
    pub reserved: u32,
}

struct Observation {
    stream: tokio::sync::Mutex<ControllerEvents>,
    // Filled before the executor replies. If the caller's original deadline
    // wins the response race, the same observation is still here for retry.
    pending: Mutex<Option<Arc<ControllerEvent>>>,
}

/// One pinned directory observer; retains its originating Client executor.
/// Closing it never stops a controller or releases another application's work.
pub struct SlkControllerEvents {
    executor: Arc<SyncClient>,
    observation: Arc<Observation>,
    call: Mutex<()>,
}

fn poisoned() -> ApplicationError {
    ApplicationError::Identity("controller observation boundary poisoned")
}

impl Observation {
    async fn next(
        &self,
        client: crate::Client,
        deadline: slk_channel::deadline::Deadline,
    ) -> Result<Arc<ControllerEvent>, ApplicationError> {
        client.check_owner().await?;
        let pending = self.pending.lock().map_err(|_| poisoned())?.clone();
        if let Some(event) = pending {
            deadline.remaining()?;
            return Ok(event);
        }
        let event = Arc::new(self.stream.lock().await.next(deadline).await?);
        // No await between consuming the Rust event and retaining delivery.
        *self.pending.lock().map_err(|_| poisoned())? = Some(event.clone());
        Ok(event)
    }
    fn acknowledge(&self, event: &Arc<ControllerEvent>) -> Result<(), i32> {
        let mut pending = self.pending.lock().map_err(|_| nix::libc::ESTALE)?;
        if !pending.as_ref().is_some_and(|p| Arc::ptr_eq(p, event)) {
            return Err(nix::libc::ESTALE);
        }
        *pending = None;
        Ok(())
    }
}

fn encode(event: &ControllerEvent) -> (SlkControllerEvent, &[slk_contract::ControllerId]) {
    let mut output = SlkControllerEvent::default();
    let ids = match event {
        ControllerEvent::Snapshot {
            before,
            controllers,
        } => {
            output.kind = 1;
            output.sequence = *before;
            controllers.as_slice()
        }
        ControllerEvent::Published {
            sequence,
            controller,
        } => {
            output.kind = 2;
            output.sequence = *sequence;
            std::slice::from_ref(controller)
        }
        ControllerEvent::Withdrawn {
            sequence,
            controller,
        } => {
            output.kind = 3;
            output.sequence = *sequence;
            std::slice::from_ref(controller)
        }
        ControllerEvent::Gap {
            after,
            oldest,
            current,
        } => {
            output.kind = 4;
            output.sequence = *after;
            output.oldest = *oldest;
            output.current = *current;
            &[]
        }
    };
    (output, ids)
}

/// Open the existing Rust directory stream on this Client's caller/owner scope.
/// deadline_ns is original absolute CLOCK_MONOTONIC, future and <=30s away.
/// Returns0/-errno; output unchanged on failure. Derived observer survives
/// Client close; final reference joins the same bounded executor. No retry.
/// # Safety
/// client is a live immutable SlkClient through the call; output is an exclusive
/// aligned writable pointer slot, nonaliasing. No concurrent Client close.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_client_controller_events(
    client: *const SlkClient,
    deadline_ns: u64,
    output: *mut *mut SlkControllerEvents,
) -> c_int {
    if client.is_null() || output.is_null() {
        return -nix::libc::EINVAL;
    }
    let executor = unsafe { &*client }.inner.clone();
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let original = slk_channel::deadline::Deadline::from_monotonic_ns(deadline_ns)
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))?;
        executor.call(deadline, move |client| async move {
            client.controller_events(original).await
        })
    });
    match result {
        Ok(stream) => {
            let value = SlkControllerEvents {
                executor,
                observation: Arc::new(Observation {
                    stream: tokio::sync::Mutex::new(stream),
                    pending: Mutex::new(None),
                }),
                call: Mutex::new(()),
            };
            unsafe { output.write(Box::into_raw(Box::new(value))) };
            0
        }
        Err(e) => -e,
    }
}

/// Read the existing stream. flags=0 consumes on successful copy; flags=1 peeks.
/// Buffer capacity is0..256, null only for0. ENOBUFS writes required count only;
/// all other errors leave outputs unchanged. Timeout, peek and ENOBUFS retain
/// the observation; no silent truncation or resnapshot. Gap must be consumed,
/// then future calls return ESTALE until an explicit new observer is opened.
/// Concurrent next/peek on one observer returns EAGAIN; this bounded executor
/// also serializes other requests of the same Client. Waiting never extends the
/// original <=30s deadline. Local cancellation does not cancel server waiting,
/// whose own pending slot remains bounded. This is a directory hint only.
/// # Safety
/// observer is live through the call; output/count/buffer are exclusive aligned
/// writable nonaliasing objects, capacity-sized buffer. No concurrent close.
/// Rust cannot validate arbitrary C pointers; invalid/aliased regions are caller UB.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_controller_events_next(
    observer: *const SlkControllerEvents,
    output: *mut SlkControllerEvent,
    buffer: *mut SlkControllerId,
    capacity: usize,
    count: *mut usize,
    flags: u32,
    deadline_ns: u64,
) -> c_int {
    if observer.is_null()
        || output.is_null()
        || count.is_null()
        || capacity > 256
        || (capacity != 0 && buffer.is_null())
        || flags > 1
    {
        return -nix::libc::EINVAL;
    }
    let observer = unsafe { &*observer };
    let _call = match observer.call.try_lock() {
        Ok(guard) => guard,
        Err(std::sync::TryLockError::WouldBlock) => return -nix::libc::EAGAIN,
        Err(_) => return -nix::libc::ESTALE,
    };
    let result = Deadline::from_monotonic_ns(deadline_ns).and_then(|deadline| {
        let original = slk_channel::deadline::Deadline::from_monotonic_ns(deadline_ns)
            .map_err(|e| e.raw_os_error().unwrap_or(nix::libc::EIO))?;
        let observation = observer.observation.clone();
        observer.executor.call(deadline, move |client| async move {
            observation.next(client, original).await
        })
    });
    match result {
        Ok(event) => {
            let (metadata, ids) = encode(&event);
            if ids.len() > 256 {
                return -nix::libc::EOVERFLOW;
            }
            if let Err(e) = Deadline::from_monotonic_ns(deadline_ns) {
                return -e;
            }
            if capacity < ids.len() {
                unsafe { count.write(ids.len()) };
                return -nix::libc::ENOBUFS;
            }
            // Acknowledge before infallible copying to caller-provided regions;
            // validation and allocation are finished, no await or failure follows.
            if flags == 0
                && let Err(e) = observer.observation.acknowledge(&event)
            {
                return -e;
            }
            for (n, id) in ids.iter().enumerate() {
                unsafe {
                    buffer.add(n).write(SlkControllerId {
                        generation: id.generation,
                        index: id.index,
                        reserved: [0; 6],
                    })
                };
            }
            unsafe {
                output.write(metadata);
                count.write(ids.len())
            };
            0
        }
        Err(e) => -e,
    }
}

/// Release this observer only. Null allowed. No controller stop, grant revocation
/// or implicit resnapshot; retained observations are discarded. Derived views
/// and Client keep their own references to the same executor. Do not use across
/// fork: exec/spawn before opening a new Client. Final reference joins bounded work.
/// # Safety
/// observer is null or one live pointer returned by open, freed once. No
/// concurrent call/close or subsequent use of that pointer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn slk_controller_events_close(observer: *mut SlkControllerEvents) {
    if !observer.is_null() {
        drop(unsafe { Box::from_raw(observer) });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support as support;
    struct Manager;
    #[zbus::interface(name = "org.sparklink.Manager")]
    impl Manager {
        fn list_adapters(&self) -> Vec<String> {
            vec!["/org/sparklink/slk2_g7".into()]
        }
        fn get_controller_changes(
            &self,
            _after: u64,
            wait: bool,
            _stamp: slk_contract::Deadline,
        ) -> zbus::fdo::Result<slk_contract::controller_events::Batch> {
            if wait {
                return Err(zbus::fdo::Error::InvalidArgs(
                    "finite initial-snapshot fixture only".into(),
                ));
            }
            Ok((1, 0, 0, false, vec![]))
        }
    }
    #[tokio::test]
    async fn production_delivery_slot_survives_unacknowledged_result_and_rejects_wrong_ack() {
        let bus = support::Bus::start();
        let _server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .name("org.sparklink")
            .unwrap()
            .serve_at("/org/sparklink", Manager)
            .unwrap()
            .build()
            .await
            .unwrap();
        let connection = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let client = crate::Client::from_connection(connection).await.unwrap();
        let deadline =
            || slk_channel::deadline::Deadline::after(std::time::Duration::from_secs(2)).unwrap();
        let observation = Observation {
            stream: tokio::sync::Mutex::new(client.controller_events(deadline()).await.unwrap()),
            pending: Mutex::new(None),
        };
        let abandoned = observation.next(client.clone(), deadline()).await.unwrap();
        let weak = Arc::downgrade(&abandoned);
        drop(abandoned); // Receiver/consumer did not acknowledge.
        let event = observation.next(client.clone(), deadline()).await.unwrap();
        assert!(Arc::ptr_eq(&event, &weak.upgrade().unwrap()));
        let wrong = Arc::new(ControllerEvent::Snapshot {
            before: 0,
            controllers: vec![],
        });
        assert_eq!(observation.acknowledge(&wrong), Err(nix::libc::ESTALE));
        assert!(Arc::ptr_eq(
            &event,
            &observation.next(client, deadline()).await.unwrap()
        ));
        assert_eq!(observation.acknowledge(&event), Ok(()));
        assert!(observation.pending.lock().unwrap().is_none());
        assert_eq!(observation.acknowledge(&event), Err(nix::libc::ESTALE));
    }
}
