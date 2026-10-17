//! Native typed connection RPCs. No business state lock spans ioctl/wait;
//! admission retains the same per-device credential gate used by discovery.
use crate::state::SharedState;
use libsparklink::Adapter;
use slk_protocol::{
    LINK_SNAPSHOT_KNOWN, SleConnectionResult, SleConnectionSubmit, SleLinkInfo, SleLinkSnapshot,
};
use std::{sync::Arc, time::Duration};
fn failed(e: impl std::fmt::Display) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(e.to_string())
}
pub(crate) type Record = (u64, u64, u32, u32, i32, i32, u32, u32, u32, u32);
pub(crate) type SnapshotRecord = (u64, u64, u64, u32, i32, Vec<(u64, u16, u8, u8, String)>);
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
    reference: Option<SleLinkInfo>,
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
            version: 2,
            profile: snapshot.profile,
            generation,
            request_id: id,
            timeout_ms: policy.timeout_ms,
            ..Default::default()
        };
        if let Some(reference) = reference {
            request.operation = 2;
            request.handle = u32::from(reference.handle);
            // SDK111 sle_disc_reason_t / reference Host DLI reason:
            // remote user termination is 0x10. 0x13 is a different SLE
            // error (encryption mode not acceptable), not Bluetooth's code.
            // Do not manufacture a peer Down from this request or its Status.
            request.reason = 0x10;
            request.expected_lifetime = reference.lifetime;
            request.expected_address = reference.address;
            request.expected_address_type = reference.address_type;
            request.expected_role = reference.role;
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
pub(crate) async fn snapshot(state: &SharedState) -> zbus::fdo::Result<SleLinkSnapshot> {
    let (fd, generation) = selected(state).await?;
    tokio::task::spawn_blocking(move || fd.native_link_snapshot(generation))
        .await
        .map_err(failed)?
        .map_err(failed)
}
pub(crate) async fn submit_disconnect(
    state: &SharedState,
    id: u64,
    address: [u8; 6],
) -> zbus::fdo::Result<()> {
    submit_disconnect_typed(state, id, address, None).await
}
pub(crate) fn peer_reference(
    snapshot: &SleLinkSnapshot,
    address: [u8; 6],
    address_type: Option<u8>,
) -> zbus::fdo::Result<SleLinkInfo> {
    if !snapshot.valid_for(snapshot.generation) || snapshot.flags != LINK_SNAPSHOT_KNOWN {
        return Err(failed("physical connection table unknown"));
    }
    let mut matching = snapshot.links[..snapshot.count as usize]
        .iter()
        .filter(|link| {
            link.address == address && address_type.is_none_or(|kind| kind == link.address_type)
        });
    let reference = *matching
        .next()
        .ok_or_else(|| failed("no known physical connection for this peer"))?;
    if matching.next().is_some() {
        return Err(zbus::fdo::Error::InvalidArgs(
            "ambiguous peer; select an explicit address type and connection lifetime".into(),
        ));
    }
    Ok(reference)
}
pub(crate) async fn submit_disconnect_typed(
    state: &SharedState,
    id: u64,
    address: [u8; 6],
    address_type: Option<u8>,
) -> zbus::fdo::Result<()> {
    let table = snapshot(state).await?;
    let reference = peer_reference(&table, address, address_type)?;
    // Snapshot may become stale before submission; the kernel checks this
    // exact lifetime again at admission and queue selection. No cache fallback.
    submit(state, id, address, reference.address_type, Some(reference)).await
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
    #[test]
    fn canonical_peer_selection_preserves_type_and_rejects_ambiguity() {
        let mut table = SleLinkSnapshot {
            version: 1,
            generation: 7,
            profile: 1,
            flags: 1,
            revision: 2,
            count: 2,
            ..Default::default()
        };
        table.links[0] = SleLinkInfo {
            lifetime: 1,
            handle: 7,
            role: 0,
            address_type: 0,
            address: [1; 6],
            reserved: [0; 6],
        };
        table.links[1] = SleLinkInfo {
            lifetime: 2,
            handle: 8,
            address_type: 1,
            ..table.links[0]
        };
        assert!(peer_reference(&table, [1; 6], None).is_err());
        assert_eq!(peer_reference(&table, [1; 6], Some(0)).unwrap().lifetime, 1);
        assert_eq!(peer_reference(&table, [1; 6], Some(1)).unwrap().lifetime, 2);
        table.links[1].address_type = 0;
        assert!(peer_reference(&table, [1; 6], Some(0)).is_err());
        table.flags = 0;
        table.error = -117;
        table.count = 0;
        table.links = [SleLinkInfo::default(); 16];
        assert!(
            peer_reference(&table, [1; 6], Some(0))
                .unwrap_err()
                .to_string()
                .contains("unknown")
        );
    }
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
                .contains("ENOTTY")
        );
    }
}
