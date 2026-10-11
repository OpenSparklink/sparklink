//! Typed discovery controls scoped to one live registration. No business lock
//! is held across a device ioctl or a wait. IDs come from callers so admission
//! can be recovered after a disconnected D-Bus request.
use crate::state::SharedState;
use libsparklink::Adapter;
use slk_protocol::{DiscoveryResultRecord, SleControllerSnapshot, SleDiscoverySubmit};
use std::{sync::Arc, time::Duration};
fn failed(error: impl std::fmt::Display) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(error.to_string())
}

pub(crate) type ManagementRecord = (u64, u32, u32, u32, i32, u32, u32);

fn public_management(q: slk_protocol::SleManagementQuery) -> ManagementRecord {
    // The owning kernel File sees a credential. Ordinary D-Bus observers must
    // never receive it, including while inspecting a failed handoff.
    (
        q.generation,
        q.mode,
        q.state,
        q.flags,
        q.error,
        q.status,
        q.opcode,
    )
}

pub(crate) async fn management(state: &SharedState) -> zbus::fdo::Result<ManagementRecord> {
    let (fd, generation) = selected(state).await?;
    let query = tokio::task::spawn_blocking(move || fd.management_status(generation))
        .await
        .map_err(failed)?
        .map_err(failed)?;
    Ok(public_management(query))
}

async fn selected(state: &SharedState) -> zbus::fdo::Result<(Arc<Adapter>, u64)> {
    let st = state.lock().await;
    if !st.present {
        return Err(failed("registration removed"));
    }
    let fd = st.native_control.clone().ok_or_else(|| {
        zbus::fdo::Error::NotSupported("native discovery policy unavailable".into())
    })?;
    Ok((fd, st.controller.generation))
}
async fn submit(
    state: &SharedState,
    build: impl FnOnce(SleControllerSnapshot) -> libsparklink::Result<SleDiscoverySubmit>
    + Send
    + 'static,
) -> zbus::fdo::Result<Vec<u8>> {
    let (fd, generation) = selected(state).await?;
    let lease = state
        .lock()
        .await
        .native_lease
        .clone()
        .ok_or_else(|| failed("management unavailable"))?;
    let authority = lease.lock_owned().await;
    if !authority.accepting || authority.token.is_none() || !state.lock().await.present {
        return Err(failed("management unavailable or registration removed"));
    }
    tokio::task::spawn_blocking(move || {
        // Keep this guard in the blocking task even if its RPC is abandoned.
        // Cancellation/removal cannot hand off authority underneath an ioctl.
        let _authority = authority;
        let snapshot = fd.controller_snapshot(generation)?;
        let request = build(snapshot)?;
        fd.submit_discovery(&request)?;
        Ok::<_, libsparklink::Error>(request.data[..request.data_len as usize].to_vec())
    })
    .await
    .map_err(failed)?
    .map_err(failed)
}

/// Cancel both discovery policies through the kernel's lease revocation. This
/// is not a successful STOP command or a fabricated operation result. Queries
/// retain the original IDs while the actual reply and cleanup drain.
pub(crate) async fn cancel_policies(state: &SharedState) -> zbus::fdo::Result<u64> {
    let (fd, generation) = selected(state).await?;
    let lease = state
        .lock()
        .await
        .native_lease
        .clone()
        .ok_or_else(|| failed("management unavailable"))?;
    // Do not queue background handoffs without a bound behind another RPC or
    // cancellation. The caller can retry a busy device explicitly.
    let mut authority = lease.try_lock_owned().map_err(|_| {
        zbus::fdo::Error::Failed("device management admission or handoff busy".into())
    })?;
    let state = state.clone();
    // Once started, finish the bounded handoff even if the D-Bus caller exits.
    tokio::spawn(async move {
        let outcome = async {
            let token = authority
                .token
                .filter(|_| authority.accepting)
                .ok_or_else(|| failed("management unavailable"))?;
            if !state.lock().await.present {
                return Err(failed("registration removed"));
            }
            let control = fd.clone();
            let snapshot =
                tokio::task::spawn_blocking(move || control.controller_snapshot(generation))
                    .await
                    .map_err(failed)?
                    .map_err(failed)?;
            if snapshot.profile != 1 || snapshot.flags != slk_protocol::CONTROLLER_READY {
                return Err(zbus::fdo::Error::NotSupported(
                    "policy cancellation requires a Ready WS73 registration".into(),
                ));
            }
            authority.accepting = false;
            // Keep the credential on failure so removal can retry its withdrawal;
            // submissions stay disabled until a successful new acquisition.
            crate::adapters::relinquish(fd.clone(), generation, token)
                .await
                .map_err(failed)?;
            authority.token = None;
            if !state.lock().await.present {
                return Err(failed("registration removed during policy cleanup"));
            }
            let control = fd.clone();
            let token = tokio::task::spawn_blocking(move || {
                control.acquire_management(generation, slk_protocol::MANAGEMENT_MANAGED)
            })
            .await
            .map_err(failed)?
            .map_err(failed)?;
            authority.token = Some(token);
            if !state.lock().await.present {
                // Leave the new credential for the waiting removal worker. It
                // stays inaccessible to business operations and cannot revive it.
                return Err(failed("registration removed during management acquisition"));
            }
            authority.accepting = true;
            Ok(generation)
        }
        .await;
        if let Err(error) = &outcome {
            tracing::warn!(generation, %error, "discovery policy cancellation failed");
        }
        outcome
    })
    .await
    .map_err(failed)?
}

pub(crate) async fn advertise(
    state: &SharedState,
    id: u64,
    marker: Vec<u8>,
) -> zbus::fdo::Result<Vec<u8>> {
    let marker: [u8; 16] = marker
        .try_into()
        .map_err(|_| zbus::fdo::Error::InvalidArgs("marker must be exactly 16 bytes".into()))?;
    submit(state, move |snapshot| {
        libsparklink::ws73_basic_advertisement(&snapshot, id, &marker)
    })
    .await
}
pub(crate) async fn scan(state: &SharedState, id: u64) -> zbus::fdo::Result<()> {
    submit(state, move |snapshot| {
        libsparklink::ws73_basic_scan(&snapshot, id)
    })
    .await?;
    Ok(())
}
pub(crate) async fn stop(state: &SharedState, id: u64, op: u32) -> zbus::fdo::Result<()> {
    submit(state, move |snapshot| {
        libsparklink::ws73_basic_stop(&snapshot, id, op)
    })
    .await?;
    Ok(())
}
pub(crate) async fn result(
    state: &SharedState,
    id: u64,
) -> zbus::fdo::Result<DiscoveryResultRecord> {
    let (fd, generation) = selected(state).await?;
    tokio::task::spawn_blocking(move || fd.discovery_result(generation, id))
        .await
        .map_err(failed)?
        .map_err(failed)?
        .map(|r| r.as_record())
        .ok_or_else(|| zbus::fdo::Error::UnknownObject("operation absent or evicted".into()))
}
pub(crate) async fn random_id() -> zbus::fdo::Result<u64> {
    tokio::task::spawn_blocking(|| -> std::io::Result<u64> {
        use std::io::Read;
        let mut bytes = [0; 8];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
        Ok(u64::from_ne_bytes(bytes).max(1))
    })
    .await
    .map_err(failed)?
    .map_err(failed)
}
/// Compatibility StartDiscovery/StopDiscovery methods wait for success;
/// slctl uses explicit Submit* + GetDiscoveryResult to retain correlation IDs.
pub(crate) async fn wait(state: &SharedState, id: u64) -> zbus::fdo::Result<()> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(7);
    loop {
        let r = result(state, id).await?;
        if r.3 >= 3 {
            return if r.3 == 3 {
                Ok(())
            } else {
                Err(failed(format!(
                    "operation request={} state={} status=0x{:02x} errno={} opcode=0x{:04x} step={}/{}",
                    r.1, r.3, r.5, r.4, r.6, r.7, r.8
                )))
            };
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(failed(
                "operation timeout; result remains queryable by request id",
            ));
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

pub(crate) async fn timing(
    state: &SharedState,
    id: u64,
) -> zbus::fdo::Result<(u64, u64, u64, u32, u32, u16, u8)> {
    let (fd, generation) = selected(state).await?;
    let t = tokio::task::spawn_blocking(move || fd.discovery_timing(generation, id))
        .await
        .map_err(failed)?
        .map_err(failed)?;
    Ok((
        t.generation,
        t.request_id,
        t.completed_boottime_ns,
        t.operation,
        t.state,
        t.opcode,
        t.status,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        bonding::BondingStore,
        config::DaemonConfig,
        profile::ProfileRegistry,
        state::{AdapterState, NativeManagement},
    };
    use tokio::sync::Mutex;

    fn selected_null() -> SharedState {
        // No simulated successful ioctl/Ready. /dev/null must return ENOTTY if
        // reached; the test exercises admission and independent credentials.
        let fd = Arc::new(Adapter::open("/dev/null").unwrap());
        let mut state = AdapterState::new(
            fd.clone(),
            DaemonConfig::default(),
            BondingStore::new(std::path::Path::new("/tmp"), "cancel-admission-test"),
            ProfileRegistry::new(),
        );
        state.native_control = Some(fd);
        state.native_lease = Some(Arc::new(Mutex::new(NativeManagement {
            token: Some(7),
            accepting: true,
        })));
        Arc::new(Mutex::new(state))
    }

    #[test]
    fn management_projection_preserves_diagnostics_without_credential() {
        let q = slk_protocol::SleManagementQuery {
            generation: 23,
            lease: u64::MAX,
            mode: 1,
            state: 1,
            flags: 1,
            error: -110,
            status: 11,
            opcode: 0x1002,
            ..Default::default()
        };
        assert_eq!(public_management(q), (23, 1, 1, 1, -110, 11, 0x1002));
        assert_eq!(
            public_management(q),
            public_management(slk_protocol::SleManagementQuery { lease: 0, ..q })
        );
    }

    #[tokio::test]
    async fn management_query_propagates_actual_ioctl_error() {
        let state = selected_null();
        let error = management(&state).await.unwrap_err().to_string();
        assert!(error.contains("ENOTTY"), "{error}");
    }

    #[tokio::test]
    async fn busy_cancel_does_not_queue_or_block_another_device() {
        let first = selected_null();
        let peer = selected_null();
        let lease = first.lock().await.native_lease.clone().unwrap();
        let guard = lease.lock().await;
        let result = tokio::time::timeout(Duration::from_millis(100), cancel_policies(&first))
            .await
            .unwrap();
        assert!(result.unwrap_err().to_string().contains("busy"));
        let error = cancel_policies(&peer).await.unwrap_err().to_string();
        assert!(error.contains("ENOTTY"), "{error}");
        assert!(guard.accepting);
        drop(guard);
        let error = cancel_policies(&first).await.unwrap_err().to_string();
        assert!(error.contains("ENOTTY"), "{error}");
    }

    #[tokio::test]
    async fn failed_handoff_admission_and_removed_registration_are_rejected() {
        let state = selected_null();
        let lease = state.lock().await.native_lease.clone().unwrap();
        lease.lock().await.accepting = false;
        assert!(
            cancel_policies(&state)
                .await
                .unwrap_err()
                .to_string()
                .contains("management unavailable")
        );
        assert!(
            scan(&state, 19)
                .await
                .unwrap_err()
                .to_string()
                .contains("management unavailable")
        );
        state.lock().await.present = false;
        assert!(
            cancel_policies(&state)
                .await
                .unwrap_err()
                .to_string()
                .contains("registration removed")
        );
    }
}
