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
    tokio::task::spawn_blocking(move || {
        let snapshot = fd.controller_snapshot(generation)?;
        let request = build(snapshot)?;
        fd.submit_discovery(&request)?;
        Ok::<_, libsparklink::Error>(request.data[..request.data_len as usize].to_vec())
    })
    .await
    .map_err(failed)?
    .map_err(failed)
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
