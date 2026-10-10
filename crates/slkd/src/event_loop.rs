use std::future::Future;

use libsparklink::{Event, EventReceiver, Result};
use tokio::sync::oneshot;
use tokio::task::{JoinError, JoinHandle};
use tracing::{error, info};

use crate::dbus_iface::{self, DeviceIface};
use crate::service;
use crate::state::SharedState;

pub(crate) trait EventSource: Send + 'static {
    fn next_event(&mut self) -> impl Future<Output = Result<Event>> + Send;
}

impl EventSource for EventReceiver {
    async fn next_event(&mut self) -> Result<Event> {
        EventReceiver::next_event(self).await
    }
}

/// Owns the receiver task. Graceful shutdown cancels pending receive/dispatch
/// and joins before the daemon releases its D-Bus connection and business state.
/// Drop is an emergency abort; callers should use shutdown to await fd release.
pub(crate) struct EventTask {
    cancel: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<()>>,
}

impl EventTask {
    pub(crate) fn start(
        mut receiver: impl EventSource,
        state: SharedState,
        connection: zbus::Connection,
    ) -> Self {
        let (cancel, mut cancelled) = oneshot::channel();
        let task = tokio::spawn(async move {
            loop {
                let event = tokio::select! {
                    biased;
                    _ = &mut cancelled => break,
                    event = receiver.next_event() => event,
                };
                tokio::select! {
                    biased;
                    _ = &mut cancelled => break,
                    _ = dispatch(event, &state, &connection) => {},
                }
            }
        });
        Self {
            cancel: Some(cancel),
            task: Some(task),
        }
    }

    /// Native subscribers preserve full parameters and never use the legacy ring.
    pub(crate) fn start_native(
        mut receiver: libsparklink::ControllerEventReceiver,
        state: SharedState,
        connection: zbus::Connection,
        expected: slk_protocol::SleControllerSnapshot,
    ) -> Self {
        let (cancel, mut cancelled) = oneshot::channel();
        let task = tokio::spawn(async move {
            loop {
                let event = tokio::select! {
                    biased;
                    _ = &mut cancelled => break,
                    event = receiver.next_event() => event,
                };
                tokio::select! {
                    biased;
                    _ = &mut cancelled => break,
                    _ = dispatch_native(event, &state, &connection, expected) => {},
                }
            }
        });
        Self {
            cancel: Some(cancel),
            task: Some(task),
        }
    }

    pub(crate) async fn shutdown(mut self) -> std::result::Result<(), JoinError> {
        if let Some(cancel) = self.cancel.take() {
            let _ = cancel.send(());
        }
        self.task
            .take()
            .expect("task is owned until shutdown")
            .await
    }
}

impl Drop for EventTask {
    fn drop(&mut self) {
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}

async fn dispatch(event: Result<Event>, state: &SharedState, connection: &zbus::Connection) {
    match event {
        Ok(libsparklink::Event::AdvReport {
            addr,
            rssi,
            discovery_level,
            name,
            adv_data,
        }) => {
            let mut st = state.lock().await;
            let is_new = st.on_adv_report(addr, rssi, discovery_level, name.clone(), adv_data);
            if is_new {
                let object_path = st.devices[&addr].object_path.clone();
                drop(st);
                let iface = DeviceIface::new(state.clone(), addr);
                if let Err(e) = connection
                    .object_server()
                    .at(object_path.as_str(), iface)
                    .await
                {
                    error!(%e, path = %object_path, "failed to register device object");
                } else {
                    info!(
                        address = %dbus_iface::format_addr(&addr),
                        name = %name,
                        rssi,
                        "new device discovered"
                    );
                }
            }
        }
        Ok(libsparklink::Event::ConnectionStateChanged {
            handle,
            state: conn_state,
            peer_addr,
        }) => {
            let mut st = state.lock().await;
            st.on_conn_state_changed(handle, conn_state, peer_addr);
            let profiles = st.profiles.clone();
            let connected = conn_state == slk_protocol::ConnState::Connected as u8;
            drop(st);
            info!(
                address = %dbus_iface::format_addr(&peer_addr),
                handle,
                connected,
                "connection state changed"
            );

            if connected {
                let path = format!("{}/conn_{handle:04x}", state.lock().await.object_path);
                let iface = service::RemoteServiceIface::new(state.clone(), handle);
                if let Err(e) = connection.object_server().at(path.as_str(), iface).await {
                    error!(%e, path, "failed to register remote service interface");
                }
            }
            if let Err(e) = profiles.connection_changed(handle, connected).await {
                error!(%e, handle, "profile connection callback failed");
            }
        }
        Ok(libsparklink::Event::SecurityChanged {
            state: sec_state,
            method,
            encrypted,
        }) => {
            let method_label = match method {
                1 => "JustWorks",
                2 => "PSK",
                _ => "None",
            };
            info!(
                state = sec_state,
                method = method_label,
                encrypted,
                "security state changed"
            );

            // Legacy events have no peer/connection identity. Only record
            // metadata when there is exactly one possible peer; never guess
            // which HashMap entry owns an event on a multi-connection adapter.
            if sec_state >= slk_protocol::SecState::Paired as u8 {
                let record = pairing_record(state, method_label).await;
                if let Some((bonding, addr, info)) = record {
                    if let Err(e) = bonding.save(addr, info).await {
                        error!(%e, "failed to save bonding");
                    } else {
                        info!(address = %dbus_iface::format_addr(&addr), "legacy pairing metadata saved");
                    }
                }
            }
        }
        Ok(event) => {
            tracing::debug!(?event, "kernel event");
        }
        Err(e) => {
            error!(%e, "event read error");
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
    }
}

async fn dispatch_native(
    event: libsparklink::Result<slk_protocol::SleControllerEvent>,
    state: &SharedState,
    connection: &zbus::Connection,
    expected: slk_protocol::SleControllerSnapshot,
) {
    let event = match event {
        Ok(event) => event,
        Err(error) => {
            error!(%error, index=expected.dev_index, "native event read failed");
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            return;
        }
    };
    if event.generation != expected.generation
        || event.dev_index != expected.dev_index
        || event.profile != expected.profile
    {
        error!("native event identity mismatch");
        return;
    }
    let mut st = state.lock().await;
    if !st.present {
        return;
    }
    st.events_lost = st.events_lost.saturating_add(event.lost);
    let Some(report) = event.ws73_discovery() else {
        let path = st.object_path.clone();
        drop(st);
        if event.lost != 0 {
            crate::adapters::invalidate_properties(connection, &path, &["EventsLost"]).await;
        }
        return;
    };
    let address: [u8; 6] = report.header[2..8].try_into().expect("fixed WS73 address");
    let received_at_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64;
    if st.native_reports.len() == 128 {
        st.native_reports.pop_front();
    }
    st.native_reports.push_back(crate::state::NativeReport {
        sequence: event.seq,
        generation: event.generation,
        received_at_ms,
        kernel_boottime_ns: event.timestamp_ns,
        address,
        rssi: report.rssi,
        header: report.header.to_vec(),
        data: report.data.to_vec(),
        lost: event.lost,
    });
    let path = st.object_path.clone();
    drop(st);
    if event.lost != 0 {
        crate::adapters::invalidate_properties(connection, &path, &["EventsLost"]).await;
    }
    dispatch(
        Ok(Event::AdvReport {
            addr: address,
            rssi: report.rssi,
            discovery_level: 0,
            name: String::new(),
            adv_data: report.data.to_vec(),
        }),
        state,
        connection,
    )
    .await;
}

async fn pairing_record(
    state: &SharedState,
    method: &str,
) -> Option<(
    crate::bonding::BondingService,
    slk_protocol::SleAddr,
    crate::bonding::BondingInfo,
)> {
    let st = state.lock().await;
    let mut connected = st.devices.iter().filter(|(_, device)| device.connected);
    let (&addr, device) = connected.next()?;
    if connected.next().is_some() {
        tracing::warn!("cannot attribute legacy security event to multiple connected peers");
        return None;
    }
    let info = crate::bonding::BondingInfo {
        name: device.name.clone(),
        method: method.to_string(),
        enc_key_fingerprint: String::new(),
        paired_at: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
            .to_string(),
    };
    Some((st.bonding.clone(), addr, info))
}

#[cfg(test)]
#[path = "event_loop_tests.rs"]
mod tests;
