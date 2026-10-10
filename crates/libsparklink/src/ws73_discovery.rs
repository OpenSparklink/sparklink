//! Versioned user-space policy for a basic, nonconnectable frame-1 WS73 beacon.
//! The driver still owns encoding/validation; policy never sends raw DLI.
use crate::{Error, Result};
use slk_protocol::*;

pub const WS73_BASIC_POLICY_VERSION: u32 = 1;

/// T/XS 20001 §6.5 public information inside the SLE access-layer type 255
/// envelope (T/XS 10002 §7.1.4). A full local name avoids inventing a vendor UUID.
pub fn ws73_marker_data(marker: &[u8; 16]) -> Vec<u8> {
    let name = format!(
        "slk-{}",
        marker
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    );
    let mut data = vec![255, (5 + name.len()) as u8, 1, 1, 1, 0x0b, name.len() as u8];
    data.extend_from_slice(name.as_bytes());
    data
}

fn identity(
    snapshot: &SleControllerSnapshot,
    request_id: u64,
    start: bool,
) -> Result<SleDiscoverySubmit> {
    if snapshot.profile != CONTROLLER_EVENT_PROFILE_WS73_HCC
        || snapshot.valid_fields != CONTROLLER_FULL_METADATA
        || snapshot.generation == 0
        || request_id == 0
        || snapshot.address == [0; 6]
    {
        return Err(Error::InvalidParam(
            "basic WS73 policy requires queried native identity and nonzero request id",
        ));
    }
    if !matches!(snapshot.flags, CONTROLLER_READY | CONTROLLER_SETUP)
        || (start && snapshot.flags != CONTROLLER_READY)
    {
        return Err(Error::InvalidParam("native controller is not Ready"));
    }
    Ok(SleDiscoverySubmit {
        version: DISCOVERY_VERSION,
        profile: snapshot.profile,
        generation: snapshot.generation,
        request_id,
        ..Default::default()
    })
}

/// Policy v1: handle 0, nonconnectable/nonqueryable, fixed T, public queried
/// address, 150 ms interval, channels 76/77/78, no power preference (127),
/// primary frame type 1 (encoded 0). No scan response or autonomous termination.
/// Support on actual firmware is proved by its result, never a fallback/echo.
pub fn ws73_basic_advertisement(
    snapshot: &SleControllerSnapshot,
    request_id: u64,
    marker: &[u8; 16],
) -> Result<SleDiscoverySubmit> {
    let mut request = identity(snapshot, request_id, true)?;
    request.operation = DISCOVERY_ADV_START;
    request.advertising = basic_advertiser_config(snapshot);
    let data = ws73_marker_data(marker);
    request.data_len = data.len() as u32;
    request.data[..data.len()].copy_from_slice(&data);
    Ok(request)
}

fn basic_advertiser_config(snapshot: &SleControllerSnapshot) -> SleDiscoveryAdvConfig {
    SleDiscoveryAdvConfig {
        handle: 0,
        mode: 0,
        gt_role: 2,
        interval_min: 1200,
        interval_max: 1200,
        channel_map: 7,
        own_address_type: 0,
        peer_address_type: 0,
        own_address: snapshot.address,
        peer_address: [0; 6],
        filter: 0,
        tx_power: 127,
        primary_frame: 0,
        secondary_frame: 0,
        secondary_phy: 0,
        secondary_pilot: 0,
        secondary_mcs: 0,
        secondary_max_skip: 0,
        sid: 0,
        request_notification: 0,
        max_requests: 0,
        request_rx_duration: 0,
        conn_interval_min: 0,
        conn_interval_max: 0,
        conn_max_latency: 0,
        supervision_timeout: 200,
        min_event_length: 0,
        max_event_length: 0,
    }
}

/// Initialize a fresh handle with explicit policy, then confirm it is OFF.
/// Neither this operation nor its kernel recipe sends an enable command.
pub fn ws73_basic_standby(
    snapshot: &SleControllerSnapshot,
    request_id: u64,
) -> Result<SleDiscoverySubmit> {
    let mut request = identity(snapshot, request_id, false)?;
    request.operation = DISCOVERY_ADV_CONFIGURE_OFF;
    request.advertising = basic_advertiser_config(snapshot);
    Ok(request)
}

/// Passive frame-1 scan, any peer, duplicates retained; interval 200 ms,
/// window 100 ms, both in 125-us slots. Scan frame-1 bitmap is 1, not adv's 0.
pub fn ws73_basic_scan(
    snapshot: &SleControllerSnapshot,
    request_id: u64,
) -> Result<SleDiscoverySubmit> {
    let mut request = identity(snapshot, request_id, true)?;
    request.operation = DISCOVERY_SCAN_START;
    request.scanning = SleDiscoveryScanConfig {
        own_address_type: 0,
        filter: 0,
        frame_types: 1,
        active: 0,
        interval: 1600,
        window: 800,
        filter_duplicates: 0,
    };
    Ok(request)
}

/// Stops can establish initial off while Setup, but cannot clear a Host fault.
pub fn ws73_basic_stop(
    snapshot: &SleControllerSnapshot,
    request_id: u64,
    operation: u32,
) -> Result<SleDiscoverySubmit> {
    if !matches!(operation, DISCOVERY_ADV_STOP | DISCOVERY_SCAN_STOP) {
        return Err(Error::InvalidParam("invalid discovery stop operation"));
    }
    let mut request = identity(snapshot, request_id, false)?;
    request.operation = operation;
    Ok(request)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn snapshot() -> SleControllerSnapshot {
        SleControllerSnapshot {
            generation: 9,
            flags: CONTROLLER_READY,
            profile: 1,
            valid_fields: 1,
            address: [2, 0x73, 0, 0, 0, 1],
            ..Default::default()
        }
    }
    #[test]
    fn standby_uses_queried_setup_identity_without_payload_or_enable() {
        let setup = SleControllerSnapshot {
            flags: CONTROLLER_SETUP,
            ..snapshot()
        };
        let request = ws73_basic_standby(&setup, 10).unwrap();
        assert_eq!(request.operation, DISCOVERY_ADV_CONFIGURE_OFF);
        assert_eq!(request.advertising.own_address, setup.address);
        assert_eq!(request.advertising.interval_min, 1200);
        assert_eq!(request.advertising.tx_power, 127);
        assert_eq!(
            (
                request.flags,
                request.data_len,
                request.duration,
                request.max_events
            ),
            (0, 0, 0, 0)
        );
        assert!(
            request
                .data
                .iter()
                .chain(&request.scan_response)
                .all(|b| *b == 0)
        );
        assert!(
            ws73_basic_standby(
                &SleControllerSnapshot {
                    flags: CONTROLLER_FAULT,
                    ..setup
                },
                11
            )
            .is_err()
        );
    }
    #[test]
    fn marker_has_access_envelope_and_public_information_not_ble_tlv() {
        let marker = [0xab; 16];
        let data = ws73_marker_data(&marker);
        assert_eq!(&data[..7], &[255, 41, 1, 1, 1, 11, 36]);
        assert_eq!(&data[7..], b"slk-abababababababababababababababab");
        assert_eq!(data.len(), 43);
    }
    #[test]
    fn policy_identity_units_and_omitted_response_are_explicit() {
        let req = ws73_basic_advertisement(&snapshot(), 7, &[0; 16]).unwrap();
        assert_eq!(
            (req.generation, req.profile, req.request_id, req.operation),
            (9, 1, 7, 1)
        );
        assert_eq!(
            (req.advertising.primary_frame, req.advertising.gt_role),
            (0, 2)
        );
        assert_eq!(
            (req.advertising.interval_min, req.advertising.tx_power),
            (1200, 127)
        );
        assert_eq!(
            (
                req.flags,
                req.scan_response_len,
                req.duration,
                req.max_events
            ),
            (0, 0, 0, 0)
        );
        assert_eq!(req.advertising.own_address, snapshot().address);
        assert!(
            req.data[43..]
                .iter()
                .chain(&req.scan_response)
                .all(|b| *b == 0)
        );
        let scan = ws73_basic_scan(&snapshot(), 8).unwrap();
        assert_eq!(
            (
                scan.scanning.frame_types,
                scan.scanning.active,
                scan.scanning.interval,
                scan.scanning.window
            ),
            (1, 0, 1600, 800)
        );
    }
    #[test]
    fn setup_fault_projection_and_invalid_identity_cannot_start() {
        for flags in [CONTROLLER_SETUP, CONTROLLER_FAULT, 0, 5] {
            let s = SleControllerSnapshot {
                flags,
                ..snapshot()
            };
            assert!(ws73_basic_scan(&s, 1).is_err());
            assert!(ws73_basic_advertisement(&s, 1, &[0; 16]).is_err());
        }
        for s in [
            SleControllerSnapshot {
                profile: 0,
                ..snapshot()
            },
            SleControllerSnapshot {
                valid_fields: 0,
                ..snapshot()
            },
            SleControllerSnapshot {
                generation: 0,
                ..snapshot()
            },
            SleControllerSnapshot {
                address: [0; 6],
                ..snapshot()
            },
        ] {
            assert!(ws73_basic_scan(&s, 1).is_err());
        }
        assert!(ws73_basic_scan(&snapshot(), 0).is_err());
        let setup = SleControllerSnapshot {
            flags: CONTROLLER_SETUP,
            ..snapshot()
        };
        assert!(ws73_basic_stop(&setup, 1, DISCOVERY_ADV_STOP).is_ok());
        assert!(ws73_basic_stop(&setup, 1, DISCOVERY_SCAN_START).is_err());
        for flags in [CONTROLLER_FAULT, 0, 5] {
            let invalid = SleControllerSnapshot {
                flags,
                ..snapshot()
            };
            assert!(ws73_basic_stop(&invalid, 1, DISCOVERY_ADV_STOP).is_err());
        }
    }
}
