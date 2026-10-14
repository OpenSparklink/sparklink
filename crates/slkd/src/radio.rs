//! Typed discovery controls scoped to one live registration. No business lock
//! is held across a device ioctl or a wait. IDs come from callers so admission
//! can be recovered after a disconnected D-Bus request.
use crate::state::{InitializationOff, SharedState};
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
    build: impl FnOnce(
        SleControllerSnapshot,
        libsparklink::Ws73DiscoveryPolicy,
    ) -> libsparklink::Result<SleDiscoverySubmit>
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
    // Do not queue an RPC behind withdrawal and silently admit it under a
    // successor credential. The caller can explicitly retry after handoff.
    let authority = lease
        .try_lock_owned()
        .map_err(|_| failed("device management admission or handoff busy"))?;
    if !authority.accepting || authority.token.is_none() || !state.lock().await.present {
        return Err(failed("management unavailable or registration removed"));
    }
    let policy = state.lock().await.native_discovery_policy.ok_or_else(|| {
        zbus::fdo::Error::NotSupported("registration discovery policy unavailable".into())
    })?;
    tokio::task::spawn_blocking(move || {
        // Keep this guard in the blocking task even if its RPC is abandoned.
        // Cancellation/removal cannot hand off authority underneath an ioctl.
        let mut authority = authority;
        let snapshot = fd.controller_snapshot(generation)?;
        let request = build(snapshot, policy)?;
        // Conservative even when admission fails: never reuse initialization
        // provenance after attempting a later policy in the same domain.
        let domain = usize::from(matches!(request.operation, 3 | 4 | 6));
        authority.initialized_off[domain] = None;
        fd.submit_discovery(&request)?;
        Ok::<_, libsparklink::Error>(request.data[..request.data_len as usize].to_vec())
    })
    .await
    .map_err(failed)?
    .map_err(failed)
}

/// Withdraw this controller lease, including connection and discovery cleanup. This
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
            authority.initialized_off = [None; 2];
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
    role: Option<libsparklink::Ws73ConnectableRole>,
) -> zbus::fdo::Result<Vec<u8>> {
    let marker: [u8; 16] = marker
        .try_into()
        .map_err(|_| zbus::fdo::Error::InvalidArgs("marker must be exactly 16 bytes".into()))?;
    submit(state, move |snapshot, policy| {
        if let Some(role) = role {
            policy.connectable_advertisement(&snapshot, id, &marker, role)
        } else {
            policy.advertisement(&snapshot, id, &marker)
        }
    })
    .await
}
pub(crate) async fn scan(state: &SharedState, id: u64) -> zbus::fdo::Result<()> {
    submit(state, move |snapshot, policy| policy.scan(&snapshot, id)).await?;
    Ok(())
}
pub(crate) async fn stop(state: &SharedState, id: u64, op: u32) -> zbus::fdo::Result<()> {
    submit(state, move |snapshot, _policy| {
        libsparklink::ws73_discovery_stop(&snapshot, id, op)
    })
    .await?;
    Ok(())
}

pub(crate) async fn discovery_policy(
    state: &SharedState,
) -> zbus::fdo::Result<(u32, u32, u32, i32, u32, u32)> {
    let st = state.lock().await;
    if !st.present {
        return Err(failed("registration removed"));
    }
    if st.controller.profile != slk_protocol::CONTROLLER_EVENT_PROFILE_WS73_HCC
        || st.native_control.is_none()
    {
        return Err(zbus::fdo::Error::NotSupported(
            "WS73 discovery policy unavailable".into(),
        ));
    }
    st.native_discovery_policy
        .map(|p| p.parameters())
        .ok_or_else(|| zbus::fdo::Error::NotSupported("WS73 discovery policy unavailable".into()))
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

/// Read the actual initializer's result only while its registration, credential
/// and untouched business domain still match. Never submit OFF, recreate an
/// evicted result, or project op5/6 as a new op2/4 successful command.
pub(crate) async fn initialization_off(
    state: &SharedState,
    operation: u32,
) -> zbus::fdo::Result<DiscoveryResultRecord> {
    let domain = match operation {
        slk_protocol::DISCOVERY_ADV_CONFIGURE_OFF => 0,
        slk_protocol::DISCOVERY_SCAN_INITIALIZE_OFF => 1,
        _ => {
            return Err(zbus::fdo::Error::InvalidArgs(
                "initializer operation must be 5 or 6".into(),
            ));
        }
    };
    let (fd, generation) = selected(state).await?;
    let lease = state
        .lock()
        .await
        .native_lease
        .clone()
        .ok_or_else(|| failed("management unavailable"))?;
    let authority = lease
        .try_lock_owned()
        .map_err(|_| failed("device management admission or handoff busy"))?;
    let reference = authority.initialized_off[domain]
        .filter(|r| {
            authority.accepting
                && authority.token == Some(r.token)
                && r.generation == generation
                && r.operation == operation
                && r.request_id != 0
        })
        .ok_or_else(|| {
            zbus::fdo::Error::UnknownObject("initializer provenance absent or invalidated".into())
        })?;
    if !state.lock().await.present {
        return Err(failed("registration removed"));
    }
    let result = tokio::task::spawn_blocking(move || {
        // Keep the guard through all observations, even if the RPC disappears.
        let _authority = authority;
        let snapshot = fd.controller_snapshot(generation).map_err(failed)?;
        let before = fd.management_status(generation).map_err(failed)?;
        let result = fd
            .discovery_result(generation, reference.request_id)
            .map_err(failed)?
            .ok_or_else(|| {
                zbus::fdo::Error::UnknownObject("initializer result absent or evicted".into())
            })?;
        validate_initialization_off(reference, snapshot, before, result).map_err(failed)?;
        let after = fd.management_status(generation).map_err(failed)?;
        validate_initialization_off(reference, snapshot, after, result).map_err(failed)?;
        Ok::<_, zbus::fdo::Error>(result.as_record())
    })
    .await
    .map_err(failed)??;
    if !state.lock().await.present {
        return Err(failed("registration removed during initializer query"));
    }
    Ok(result)
}

fn validate_initialization_off(
    reference: InitializationOff,
    snapshot: SleControllerSnapshot,
    management: slk_protocol::SleManagementQuery,
    result: slk_protocol::SleDiscoveryResult,
) -> Result<(), &'static str> {
    let (opcode, step, count, power_valid, own, other) = match reference.operation {
        slk_protocol::DISCOVERY_ADV_CONFIGURE_OFF => {
            (0x0c05, 1, 2, 1, result.radio_adv, result.radio_scan)
        }
        slk_protocol::DISCOVERY_SCAN_INITIALIZE_OFF => {
            (0x1002, 2, 3, 0, result.radio_scan, result.radio_adv)
        }
        _ => return Err("unsupported initializer provenance"),
    };
    if reference.generation == 0
        || reference.token == 0
        || reference.request_id == 0
        || snapshot.generation != reference.generation
        || snapshot.profile != 1
        || snapshot.flags != slk_protocol::CONTROLLER_READY
        || snapshot.error != 0
        || management.generation != reference.generation
        || management.lease != reference.token
        || management.mode != slk_protocol::MANAGEMENT_MANAGED
        || management.state != slk_protocol::MANAGEMENT_HELD
        || management.flags != 1
        || management.error != 0
        || result.version != slk_protocol::DISCOVERY_VERSION
        || result.flags != 0
        || result.generation != reference.generation
        || result.request_id != reference.request_id
        || result.dev_index != snapshot.dev_index
        || result.profile != 1
        || result.operation != reference.operation
        || result.state != 3
        || result.error != 0
        || result.status != 0
        || result.opcode != opcode
        || result.step != step
        || result.count != count
        || result.power_valid != power_valid
        || own != 1
        || !matches!(other, 1 | 2)
    {
        return Err(
            "initializer OFF is not confirmed for the current registration and management authority",
        );
    }
    Ok(())
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
/// Explicit controller-management scan methods wait for success;
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
            connection_id: 0,
            initialized_off: [None; 2],
        })));
        Arc::new(Mutex::new(state))
    }

    #[test]
    fn initializer_proof_rejects_stale_authority_fault_and_wrong_domain() {
        // Explicit synthetic integer fixtures exercise rejection predicates;
        // they never stand in for a kernel ioctl or a real Complete.
        for operation in [5, 6] {
            let reference = InitializationOff {
                generation: 23,
                token: 7,
                request_id: 41,
                operation,
            };
            let snapshot = SleControllerSnapshot {
                generation: 23,
                dev_index: 2,
                profile: 1,
                flags: 1,
                ..Default::default()
            };
            let management = slk_protocol::SleManagementQuery {
                generation: 23,
                lease: 7,
                version: 1,
                flags: 1,
                mode: 1,
                state: 1,
                ..Default::default()
            };
            let result = slk_protocol::SleDiscoveryResult {
                generation: 23,
                request_id: 41,
                operation,
                version: 1,
                profile: 1,
                state: 3,
                dev_index: 2,
                radio_adv: 1,
                radio_scan: 1,
                opcode: if operation == 5 { 0x0c05 } else { 0x1002 },
                step: if operation == 5 { 1 } else { 2 },
                count: if operation == 5 { 2 } else { 3 },
                power_valid: u8::from(operation == 5),
                selected_power: if operation == 5 { 20 } else { 0 },
                ..Default::default()
            };
            assert!(validate_initialization_off(reference, snapshot, management, result).is_ok());
            let mut other_on = result;
            if operation == 5 {
                other_on.radio_scan = 2;
            } else {
                other_on.radio_adv = 2;
            }
            assert!(validate_initialization_off(reference, snapshot, management, other_on).is_ok());
            for invalid in [
                slk_protocol::SleDiscoveryResult {
                    generation: 24,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    request_id: 42,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    operation: if operation == 5 { 2 } else { 4 },
                    ..result
                },
                slk_protocol::SleDiscoveryResult { flags: 1, ..result },
                slk_protocol::SleDiscoveryResult { state: 2, ..result },
                slk_protocol::SleDiscoveryResult {
                    state: 4,
                    status: 0x0b,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    error: -125,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    status: 0x0b,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    dev_index: 3,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    opcode: 0x0404,
                    ..result
                },
                slk_protocol::SleDiscoveryResult { step: 0, ..result },
                slk_protocol::SleDiscoveryResult { count: 1, ..result },
                slk_protocol::SleDiscoveryResult {
                    power_valid: u8::from(operation != 5),
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    radio_adv: 0,
                    ..result
                },
                slk_protocol::SleDiscoveryResult {
                    radio_scan: 3,
                    ..result
                },
            ] {
                assert!(
                    validate_initialization_off(reference, snapshot, management, invalid).is_err(),
                    "{invalid:?}"
                );
            }
            let mut own_on = result;
            if operation == 5 {
                own_on.radio_adv = 2;
            } else {
                own_on.radio_scan = 2;
            }
            assert!(validate_initialization_off(reference, snapshot, management, own_on).is_err());
            for invalid in [
                slk_protocol::SleManagementQuery {
                    generation: 24,
                    ..management
                },
                slk_protocol::SleManagementQuery {
                    lease: 8,
                    ..management
                },
                slk_protocol::SleManagementQuery {
                    lease: 0,
                    ..management
                },
                slk_protocol::SleManagementQuery {
                    state: 2,
                    ..management
                },
                slk_protocol::SleManagementQuery {
                    mode: 2,
                    ..management
                },
                slk_protocol::SleManagementQuery {
                    flags: 0,
                    ..management
                },
                slk_protocol::SleManagementQuery {
                    error: -110,
                    ..management
                },
            ] {
                assert!(validate_initialization_off(reference, snapshot, invalid, result).is_err());
            }
            for invalid in [
                SleControllerSnapshot {
                    generation: 24,
                    ..snapshot
                },
                SleControllerSnapshot {
                    profile: 0,
                    ..snapshot
                },
                SleControllerSnapshot {
                    flags: 2,
                    ..snapshot
                },
                SleControllerSnapshot {
                    error: -110,
                    ..snapshot
                },
            ] {
                assert!(
                    validate_initialization_off(reference, invalid, management, result).is_err()
                );
            }
        }
    }

    #[tokio::test]
    async fn initializer_query_never_falls_back_or_blocks_a_peer() {
        let first = selected_null();
        let peer = selected_null();
        assert!(matches!(
            initialization_off(&first, 2).await,
            Err(zbus::fdo::Error::InvalidArgs(_))
        ));
        assert!(matches!(
            initialization_off(&first, 5).await,
            Err(zbus::fdo::Error::UnknownObject(_))
        ));
        first.lock().await.controller.generation = 23;
        let lease = first.lock().await.native_lease.clone().unwrap();
        let mut guard = lease.lock().await;
        guard.initialized_off[0] = Some(InitializationOff {
            generation: 23,
            token: 7,
            request_id: 41,
            operation: 5,
        });
        let busy = tokio::time::timeout(Duration::from_millis(100), initialization_off(&first, 5))
            .await
            .unwrap();
        assert!(busy.err().unwrap().to_string().contains("busy"));
        assert!(matches!(
            initialization_off(&peer, 5).await,
            Err(zbus::fdo::Error::UnknownObject(_))
        ));
        guard.token = Some(8);
        drop(guard);
        assert!(matches!(
            initialization_off(&first, 5).await,
            Err(zbus::fdo::Error::UnknownObject(_))
        ));
        lease.lock().await.token = Some(7);
        assert!(
            initialization_off(&first, 5)
                .await
                .err()
                .unwrap()
                .to_string()
                .contains("ENOTTY")
        );
        assert!(matches!(
            initialization_off(&first, 6).await,
            Err(zbus::fdo::Error::UnknownObject(_))
        ));
        lease.lock().await.accepting = false;
        assert!(matches!(
            initialization_off(&first, 5).await,
            Err(zbus::fdo::Error::UnknownObject(_))
        ));
        first.lock().await.present = false;
        assert!(
            initialization_off(&first, 5)
                .await
                .err()
                .unwrap()
                .to_string()
                .contains("registration removed")
        );
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
    async fn policy_query_has_no_fallback_and_is_registration_scoped() {
        let first = selected_null();
        let peer = selected_null();
        assert!(matches!(
            discovery_policy(&first).await,
            Err(zbus::fdo::Error::NotSupported(_))
        ));
        let configured =
            libsparklink::Ws73DiscoveryPolicy::new(1237, 1301, -20, 1703, 997).unwrap();
        first.lock().await.controller.profile = slk_protocol::CONTROLLER_EVENT_PROFILE_WS73_HCC;
        peer.lock().await.controller.profile = slk_protocol::CONTROLLER_EVENT_PROFILE_WS73_HCC;
        first.lock().await.native_discovery_policy = Some(configured);
        peer.lock().await.native_discovery_policy =
            Some(libsparklink::Ws73DiscoveryPolicy::default());
        assert_eq!(
            discovery_policy(&first).await.unwrap(),
            configured.parameters()
        );
        assert_eq!(
            discovery_policy(&peer).await.unwrap(),
            (3, 1200, 1200, 127, 1600, 800)
        );
        first.lock().await.present = false;
        assert!(
            discovery_policy(&first)
                .await
                .unwrap_err()
                .to_string()
                .contains("registration removed")
        );
        assert_eq!(
            discovery_policy(&peer).await.unwrap(),
            (3, 1200, 1200, 127, 1600, 800)
        );
    }

    #[tokio::test]
    async fn busy_business_admission_never_waits_for_successor_authority() {
        let first = selected_null();
        let peer = selected_null();
        first.lock().await.native_discovery_policy =
            Some(libsparklink::Ws73DiscoveryPolicy::default());
        peer.lock().await.native_discovery_policy =
            Some(libsparklink::Ws73DiscoveryPolicy::default());
        let lease = first.lock().await.native_lease.clone().unwrap();
        let mut guard = lease.lock().await;
        for operation in 1..=4 {
            let result = tokio::time::timeout(
                Duration::from_millis(100),
                submit(&first, move |_, _| {
                    panic!("busy operation {operation} reached request construction")
                }),
            )
            .await
            .expect("busy admission must not wait behind authority handoff");
            assert!(result.unwrap_err().to_string().contains("busy"));
        }
        // A different device reaches its actual ioctl, independently. No
        // synthetic successful snapshot or radio state is supplied here.
        let error = tokio::time::timeout(Duration::from_millis(100), scan(&peer, 41))
            .await
            .unwrap()
            .unwrap_err()
            .to_string();
        assert!(error.contains("ENOTTY"), "{error}");
        guard.token = Some(8);
        drop(guard);
        let error = scan(&first, 42).await.unwrap_err().to_string();
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
