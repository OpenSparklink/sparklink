//! Native typed connection RPCs. No business state lock spans ioctl/wait;
//! admission retains the same per-device credential gate used by discovery.
use crate::state::SharedState;
use libsparklink::Adapter;
use slk_protocol::{SleConnectionResult, SleConnectionSubmit};
use std::{sync::Arc, time::Duration};
fn failed(e: impl std::fmt::Display) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(e.to_string())
}
pub(crate) type Record = (u64, u64, u32, u32, i32, i32, u32, u32, u32, u32);
async fn selected(state: &SharedState) -> zbus::fdo::Result<(Arc<Adapter>, u64)> {
    let s = state.lock().await;
    if !s.present {
        return Err(failed("registration removed"));
    }
    let fd = s
        .native_control
        .clone()
        .ok_or_else(|| zbus::fdo::Error::NotSupported("native connection unavailable".into()))?;
    Ok((fd, s.controller.generation))
}
/// Allocate before submission so an abandoned RPC leaves a known query ID.
pub(crate) async fn allocate(state: &SharedState) -> zbus::fdo::Result<u64> {
    let lease = {
        let s = state.lock().await;
        if !s.present {
            return Err(failed("registration removed"));
        }
        s.native_lease
            .clone()
            .ok_or_else(|| failed("management unavailable"))?
    };
    let mut a = lease
        .try_lock_owned()
        .map_err(|_| failed("management admission or handoff busy"))?;
    if !a.accepting || a.token.is_none() {
        return Err(failed("management unavailable"));
    }
    a.connection_id = a
        .connection_id
        .checked_add(1)
        .ok_or_else(|| failed("connection id exhausted"))?;
    Ok(a.connection_id)
}
pub(crate) async fn submit(
    state: &SharedState,
    id: u64,
    address: [u8; 6],
    address_type: u8,
    handle: Option<u16>,
) -> zbus::fdo::Result<()> {
    if id == 0 {
        return Err(zbus::fdo::Error::InvalidArgs(
            "request id must be nonzero".into(),
        ));
    }
    let (fd, generation) = selected(state).await?;
    let (lease, policy) = {
        let s = state.lock().await;
        (
            s.native_lease
                .clone()
                .ok_or_else(|| failed("management unavailable"))?,
            s.config.ws73.connection.clone(),
        )
    };
    let authority = lease
        .try_lock_owned()
        .map_err(|_| failed("management admission or handoff busy"))?;
    if !authority.accepting || authority.token.is_none() || id > authority.connection_id {
        return Err(failed("management unavailable or request id not allocated"));
    }
    if !state.lock().await.present {
        return Err(failed("registration removed"));
    }
    tokio::task::spawn_blocking(move || {
        let mut authority = authority;
        let snapshot = fd.controller_snapshot(generation)?;
        if snapshot.profile != 1 || snapshot.flags != slk_protocol::CONTROLLER_READY {
            return Err(libsparklink::Error::InvalidParam("Ready WS73 required"));
        }
        let mut request = SleConnectionSubmit {
            version: 1,
            profile: snapshot.profile,
            generation,
            request_id: id,
            timeout_ms: policy.timeout_ms,
            ..Default::default()
        };
        if let Some(handle) = handle {
            request.operation = 2;
            request.handle = u32::from(handle);
            request.reason = 0x13;
        } else {
            request.operation = 1;
            request.parameters = policy.parameters();
            request.parameters.peer_address = address;
            request.parameters.peer_address_type = u32::from(address_type);
        }
        // Firmware connection procedures may affect either radio's provenance.
        authority.initialized_off = [None; 2];
        fd.submit_native_connection(&request)
    })
    .await
    .map_err(failed)?
    .map_err(failed)
}
pub(crate) async fn result(state: &SharedState, id: u64) -> zbus::fdo::Result<Record> {
    let (fd, generation) = selected(state).await?;
    let r = tokio::task::spawn_blocking(move || fd.native_connection_result(generation, id))
        .await
        .map_err(failed)?
        .map_err(failed)?
        .ok_or_else(|| {
            zbus::fdo::Error::UnknownObject("connection operation absent or evicted".into())
        })?;
    Ok(record(r))
}
fn record(r: SleConnectionResult) -> Record {
    (
        r.generation,
        r.request_id,
        r.operation,
        r.state,
        r.error,
        r.fault_error,
        r.command_status,
        r.outcome_status,
        r.handle,
        r.flags,
    )
}
pub(crate) async fn submit_disconnect(
    state: &SharedState,
    id: u64,
    address: [u8; 6],
) -> zbus::fdo::Result<()> {
    let handle = {
        let s = state.lock().await;
        s.devices
            .get(&address)
            .filter(|d| d.connection_known && d.connected)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| failed("no known physical connection for this address"))?
    };
    submit(state, id, address, 0, Some(handle)).await
}
pub(crate) async fn disconnect_address(
    state: &SharedState,
    address: [u8; 6],
) -> zbus::fdo::Result<u64> {
    let id = allocate(state).await?;
    submit_disconnect(state, id, address).await?;
    Ok(id)
}
pub(crate) async fn wait(state: &SharedState, id: u64) -> zbus::fdo::Result<()> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(16);
    loop {
        let r = result(state, id).await?;
        if r.3 >= 4 {
            return if r.3 == 4 && r.4 == 0 && r.5 == 0 && r.6 == 0 && r.7 == 0 && r.9 & 7 == 7 {
                Ok(())
            } else {
                Err(failed(format!(
                    "connection request={} state={} errno={} fault={} command_status={} outcome_status={} flags={}",
                    r.1, r.3, r.4, r.5, r.6, r.7, r.9
                )))
            };
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(failed(
                "connection observation timeout; query original request id",
            ));
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
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
    fn state() -> SharedState {
        let fd = Arc::new(Adapter::open("/dev/null").unwrap());
        let mut s = AdapterState::new(
            fd.clone(),
            DaemonConfig::default(),
            BondingStore::new(
                std::path::Path::new("/tmp"),
                "native-connection-admission-test",
            ),
            ProfileRegistry::new(),
        );
        s.native_control = Some(fd);
        s.controller.generation = 7;
        s.controller.profile = 1;
        s.native_lease = Some(Arc::new(Mutex::new(NativeManagement {
            token: Some(7),
            accepting: true,
            connection_id: 0,
            initialized_off: [None; 2],
        })));
        Arc::new(Mutex::new(s))
    }
    #[tokio::test]
    async fn allocated_ids_survive_busy_and_failed_syscall_without_touching_peer() {
        let a = state();
        let b = state();
        assert_eq!(allocate(&a).await.unwrap(), 1);
        assert_eq!(allocate(&a).await.unwrap(), 2);
        assert_eq!(allocate(&b).await.unwrap(), 1);
        let lease = a.lock().await.native_lease.clone().unwrap();
        let guard = lease.lock().await;
        assert!(allocate(&a).await.unwrap_err().to_string().contains("busy"));
        assert_eq!(allocate(&b).await.unwrap(), 2);
        drop(guard);
        // /dev/null is ENOTTY, never a simulated accepted ioctl or Ready.
        assert!(submit(&a, 2, [1; 6], 0, None).await.is_err());
        assert_eq!(allocate(&a).await.unwrap(), 3);
        assert!(
            submit(&a, 4, [1; 6], 0, None)
                .await
                .unwrap_err()
                .to_string()
                .contains("not allocated")
        );
        assert!(
            submit_disconnect(&a, 3, [1; 6])
                .await
                .unwrap_err()
                .to_string()
                .contains("no known physical")
        );
    }
}
