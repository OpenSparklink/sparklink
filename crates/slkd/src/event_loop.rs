#[cfg(test)]
use std::future::Future;

#[cfg(test)]
use slk_native::Result;
use tokio::sync::oneshot;
use tokio::task::{JoinError, JoinHandle};
use tracing::error;

use crate::connection_object::PeerIface;
use crate::state::SharedState;

// Historical event fixture only. Runtime consumes typed ControllerEventReceiver
// records and complete link snapshots, never this handle-only representation.
#[cfg(test)]
#[derive(Debug)]
pub(crate) enum Event {
    AdvReport {
        addr: slk_protocol::SleAddr,
        rssi: i8,
        discovery_level: u8,
        name: String,
        adv_data: Vec<u8>,
    },
    ConnectionStateChanged {
        handle: u16,
        state: u8,
        peer_addr: slk_protocol::SleAddr,
    },
}

#[cfg(test)]
pub(crate) trait EventSource: Send + 'static {
    fn next_event(&mut self) -> impl Future<Output = Result<Event>> + Send;
}

/// Owns the receiver task. Graceful shutdown cancels pending receive/dispatch
/// and joins before the daemon releases its D-Bus connection and business state.
/// Drop is an emergency abort; callers should use shutdown to await fd release.
pub(crate) struct EventTask {
    cancel: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<()>>,
}

impl EventTask {
    #[cfg(test)]
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
        mut receiver: slk_native::ControllerEventReceiver,
        state: SharedState,
        connection: zbus::Connection,
        expected: slk_protocol::SleControllerSnapshot,
    ) -> Self {
        let (cancel, mut cancelled) = oneshot::channel();
        let task = tokio::spawn(async move {
            let mut retry = tokio::time::interval(std::time::Duration::from_secs(1));
            retry.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
            tokio::select! {
                biased;
                _ = &mut cancelled => return,
                _ = refresh_native(&state, &connection, expected, 0) => {},
            }
            loop {
                let event = tokio::select! {
                    biased;
                    _ = &mut cancelled => break,
                    _ = retry.tick() => {
                        let retry_needed = {
                            let st = state.lock().await;
                            !st.native_links_known() || st.connection_publication_pending()
                        };
                        if retry_needed {
                            tokio::select! {
                                biased;
                                _ = &mut cancelled => break,
                                _ = refresh_native(&state, &connection, expected, 0) => {},
                            }
                        }
                        tokio::select! {
                            biased;
                            _ = &mut cancelled => break,
                            _ = maintain_observations(&state, &connection) => {},
                        }
                        continue;
                    },
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

/// Real native completion may wake the sole deferred SMTC owner. The path
/// includes generation and physical lifetime, and bind still revalidates the
/// live management lease and kernel mechanism. Failure never falls back.
pub(crate) async fn start_ssap_after_security(
    state: &SharedState,
    connection: &zbus::Connection,
    generation: u64,
    reference: slk_protocol::SleLinkInfo,
) {
    let path = {
        let st = state.lock().await;
        if !st.present || st.controller.generation != generation {
            return;
        }
        match st.native_connection_objects.get(&reference.lifetime) {
            Some(v) if v.published && v.reference == reference => v.path.clone(),
            _ => return,
        }
    };
    if let Ok(iface) = connection
        .object_server()
        .interface::<_, crate::connection_object::ConnectionIface>(path.as_str())
        .await
        && let Err(error) = iface.get().await.start_ssap().await
    {
        tracing::warn!(%error, %path, "SMTC security requirement not satisfied; no fallback or rebind");
    }
}

/// The sole production advertisement consumer; no legacy connection/security
/// event branch. Caller already validated the Native generation and payload.
#[cfg(test)]
async fn publish_advertisement(
    state: &SharedState,
    connection: &zbus::Connection,
    addr: slk_protocol::SleAddr,
    rssi: i8,
    discovery_level: u8,
    name: String,
    adv_data: Vec<u8>,
) {
    let mut st = state.lock().await;
    st.on_adv_report(addr, rssi, discovery_level, name, adv_data);
    drop(st);
    maintain_observations(state, connection).await;
}

/// Historical fixture dispatch retains callback/cancel/slow-state regressions.
/// It is not a second production event receiver or a full Runtime proof.
#[cfg(test)]
async fn dispatch(event: Result<Event>, state: &SharedState, connection: &zbus::Connection) {
    match event {
        Ok(Event::AdvReport {
            addr,
            rssi,
            discovery_level,
            name,
            adv_data,
        }) => {
            publish_advertisement(
                state,
                connection,
                addr,
                rssi,
                discovery_level,
                name,
                adv_data,
            )
            .await;
        }
        Ok(Event::ConnectionStateChanged {
            handle,
            state: conn_state,
            peer_addr,
        }) => {
            let mut st = state.lock().await;
            st.on_conn_state_changed(handle, conn_state, peer_addr);
            let profiles = st.profiles.clone();
            let connected = conn_state == slk_protocol::ConnState::Connected as u8;
            drop(st);
            if let Err(e) = profiles.connection_changed(handle, connected).await {
                error!(%e, handle, "historical profile callback failed");
            }
        }
        Err(e) => {
            error!(%e, "event fixture read error");
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
    }
}

/// Only the registration's existing EventTask runs this bounded maintenance.
/// No new callback/task or unbounded retry queue. State locks never cross bus
/// registration/removal, and foreign interfaces are never removed or adopted.
async fn maintain_observations(state: &SharedState, connection: &zbus::Connection) {
    use crate::state::PeerPublication;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_millis(100);
    let Ok(mut st) = tokio::time::timeout_at(deadline, state.lock()).await else {
        return;
    };
    let generation = st.controller.generation;
    let work = st.observation_work();
    drop(st);
    for (address, path, phase) in work {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        {
            let Ok(mut st) = tokio::time::timeout_at(deadline, state.lock()).await else {
                break;
            };
            if !st.present || st.controller.generation != generation {
                break;
            }
            st.observation_attempted(address);
        }
        let outcome = match tokio::time::timeout_at(deadline, async {
            match phase {
                PeerPublication::Pending => {
                    connection
                        .object_server()
                        .at(
                            path.as_str(),
                            PeerIface::new(state.clone(), generation, address.0, address.1),
                        )
                        .await?;
                    let iface = connection
                        .object_server()
                        .interface::<_, PeerIface>(path.as_str())
                        .await?;
                    if !iface.get().await.belongs_to(state, generation, address) {
                        return Err(zbus::Error::Failure(
                            "observation path belongs to another owner".into(),
                        ));
                    }
                    Ok(())
                }
                PeerPublication::Retiring => {
                    match connection
                        .object_server()
                        .interface::<_, PeerIface>(path.as_str())
                        .await
                    {
                        Ok(iface) => {
                            if !iface.get().await.belongs_to(state, generation, address) {
                                return Err(zbus::Error::Failure(
                                    "refusing to retire another observation owner".into(),
                                ));
                            }
                            match connection
                                .object_server()
                                .remove::<PeerIface, _>(path.as_str())
                                .await
                            {
                                Ok(_) | Err(zbus::Error::InterfaceNotFound) => Ok(()),
                                Err(error) => Err(error),
                            }
                        }
                        // No instance of our concrete interface exists. Never
                        // delete a foreign interface just for sharing its name.
                        Err(zbus::Error::InterfaceNotFound) => Ok(()),
                        Err(error) => Err(error),
                    }
                }
                PeerPublication::Published => {
                    unreachable!("work excludes published observations")
                }
            }
        })
        .await
        {
            Ok(result) => result,
            Err(_) => Err(zbus::Error::Failure(
                "observation original maintenance deadline elapsed".into(),
            )),
        };
        let success = outcome.is_ok();
        // Never wait beyond the original maintenance budget to finalize an
        // outcome. Unconfirmed work remains charged and is revalidated on the
        // next pass, even if ObjectServer already performed its side effect.
        let Ok(mut st) = state.try_lock() else {
            tracing::warn!(%path,?phase,?outcome,"observation bookkeeping deferred; slot remains charged");
            break;
        };
        if !st.present
            || st.controller.generation != generation
            || st
                .peers
                .get(&address)
                .is_none_or(|d| d.object_path != path || d.publication != phase)
        {
            continue;
        }
        if success {
            if phase == PeerPublication::Pending {
                st.peers.get_mut(&address).unwrap().publication = PeerPublication::Published;
            } else {
                st.peers.remove(&address);
            }
        } else {
            let errors = if phase == PeerPublication::Pending {
                &mut st.observation_publication_errors
            } else {
                &mut st.observation_retirement_errors
            };
            *errors = errors.saturating_add(1);
            // Bounded diagnostic volume for finalized failures.
            if errors.is_power_of_two() {
                tracing::warn!(%path,?phase,count=*errors,error=?outcome.err(),"device observation publication pending; bounded retry");
            }
        }
    }
}

async fn reconcile_native(
    state: &SharedState,
    connection: &zbus::Connection,
    expected: slk_protocol::SleControllerSnapshot,
    minimum_seq: u64,
    snapshot: zbus::fdo::Result<slk_protocol::SleLinkSnapshot>,
) {
    let (
        known,
        barrier,
        revision,
        adapter_path,
        publications,
        retired,
        connection_paths,
        peer_paths,
    ) = {
        let mut st = state.lock().await;
        if !st.present || st.controller.generation != expected.generation {
            return;
        }
        match snapshot {
            Ok(table) => match st.apply_native_links(table, minimum_seq) {
                Ok(()) => {}
                Err(()) => {
                    error!(
                        generation = expected.generation,
                        "invalid or stale canonical link snapshot"
                    );
                }
            },
            Err(error) => {
                st.invalidate_native_connections();
                tracing::warn!(%error, generation=expected.generation, "canonical links unknown; bounded-rate refresh scheduled");
            }
        };
        let (publications, retired) = st.connection_publications();
        let peer_paths = st
            .peers
            .values()
            .map(|entry| entry.object_path.clone())
            .collect::<Vec<_>>();
        let connection_paths = st
            .native_connection_objects
            .values()
            .map(|entry| entry.path.clone())
            .collect::<Vec<_>>();
        (
            st.native_links_known(),
            st.native_link_barrier,
            st.native_link_revision,
            st.object_path.clone(),
            publications,
            retired,
            connection_paths,
            peer_paths,
        )
    };
    for path in retired {
        if let Ok(iface) = connection
            .object_server()
            .interface::<_, crate::connection_object::ConnectionIface>(path.as_str())
            .await
        {
            iface.get().await.stop_ssap().await;
        }
        match connection
            .object_server()
            .remove::<crate::connection_object::ConnectionIface, _>(path.as_str())
            .await
        {
            Ok(_) | Err(zbus::Error::InterfaceNotFound) => {
                state.lock().await.retiring_connection_objects.remove(&path);
            }
            Err(error) => {
                error!(%error, %path, "retired connection object removal failed; will retry")
            }
        }
    }
    for entry in publications {
        let iface = crate::connection_object::ConnectionIface::new(
            state.clone(),
            expected.generation,
            entry.reference,
            state.lock().await.config.ssap.channel_security,
        );
        if let Err(error) = iface.start_ssap_on_publication().await {
            error!(%error,path=%entry.path,"SMTC actor binding failed; no SSAP qualification");
        }
        match connection
            .object_server()
            .at(entry.path.as_str(), iface)
            .await
        {
            Ok(_) => {
                let mut st = state.lock().await;
                if let Some(current) = st
                    .native_connection_objects
                    .get_mut(&entry.reference.lifetime)
                    && current.reference == entry.reference
                {
                    current.published = true;
                }
            }
            Err(error) => {
                error!(%error, path=%entry.path, "typed connection publication failed; refresh will retry")
            }
        }
    }
    maintain_observations(state, connection).await;
    for path in connection_paths {
        crate::adapters::invalidate_connection_properties(
            connection,
            &path,
            &["Connected", "ConnectionKnown"],
        )
        .await;
    }
    for path in peer_paths {
        crate::adapters::invalidate_peer_properties(
            connection,
            &path,
            &["Connected", "ConnectionKnown"],
        )
        .await;
    }
    crate::adapters::invalidate_properties(connection, &adapter_path, &["NativeLinkObservation"])
        .await;
    tracing::info!(
        generation = expected.generation,
        known,
        barrier,
        revision,
        "canonical links reconciled"
    );
}

async fn refresh_native(
    state: &SharedState,
    connection: &zbus::Connection,
    expected: slk_protocol::SleControllerSnapshot,
    minimum_seq: u64,
) {
    let snapshot = crate::connection::snapshot(state).await;
    reconcile_native(state, connection, expected, minimum_seq, snapshot).await;
}

async fn dispatch_native(
    event: slk_native::Result<slk_protocol::SleControllerEvent>,
    state: &SharedState,
    connection: &zbus::Connection,
    expected: slk_protocol::SleControllerSnapshot,
) {
    dispatch_native_with(event, state, connection, expected, || {
        crate::connection::snapshot(state)
    })
    .await;
}

// Query dependency is injectable only by the dedicated offline test caller;
// production always reads the actual canonical kernel ioctl.
async fn dispatch_native_with<
    F: Future<Output = zbus::fdo::Result<slk_protocol::SleLinkSnapshot>>,
>(
    event: slk_native::Result<slk_protocol::SleControllerEvent>,
    state: &SharedState,
    connection: &zbus::Connection,
    expected: slk_protocol::SleControllerSnapshot,
    query: impl FnOnce() -> F,
) {
    let event = match event {
        Ok(event) => event,
        Err(error) => {
            error!(%error, index=expected.dev_index, "native event read failed");
            reconcile_native(
                state,
                connection,
                expected,
                0,
                Err(zbus::fdo::Error::Failed(error.to_string())),
            )
            .await;
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
    let is_link = matches!(event.event_code, 0x15 | 0x1401 | 5 | 0x1405);
    let (refresh, adapter_path) = {
        let mut st = state.lock().await;
        if !st.present {
            return;
        }
        st.events_lost = st.events_lost.saturating_add(event.lost);
        let refresh = event.lost != 0 || is_link && event.seq > st.native_link_barrier;
        if refresh {
            st.invalidate_native_connections();
        }
        (refresh, st.object_path.clone())
    };
    if refresh {
        reconcile_native(state, connection, expected, event.seq, query().await).await;
    }
    if event.lost != 0 {
        crate::adapters::invalidate_properties(connection, &adapter_path, &["EventsLost"]).await;
    }
    if is_link {
        return;
    }
    let mut st = state.lock().await;
    if !st.present {
        return;
    }
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
    let mut st = state.lock().await;
    // Recheck after awaits; a retired registration cannot consume new data.
    if st.present && st.controller.generation == event.generation {
        st.on_native_adv_report(&event, &report);
    }
    drop(st);
    maintain_observations(state, connection).await;
}

#[cfg(test)]
async fn pairing_record(
    state: &SharedState,
    method: &str,
) -> Option<(
    crate::bonding::BondingService,
    slk_protocol::SleAddr,
    crate::bonding::BondingInfo,
)> {
    let st = state.lock().await;
    let mut connected = st.peers.iter().filter(|(_, device)| device.connected);
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
    Some((st.bonding.clone(), addr.1, info))
}

#[cfg(test)]
#[path = "event_loop_tests.rs"]
pub(crate) mod tests;
