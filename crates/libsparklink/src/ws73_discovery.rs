//! Versioned discovery policy and an explicit fixed-T connectable advertiser.
//! The driver still owns encoding/validation; policy never sends raw DLI.
use crate::{Error, Result};
use slk_protocol::*;

pub const WS73_DISCOVERY_POLICY_VERSION: u32 = 3;

/// Validated host policy for one registration. Private fields prevent bypassing
/// the SDK's interval/window/power ranges; the driver owns wire encoding and
/// the controller still decides actual support through its Complete result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Ws73DiscoveryPolicy {
    advertising_interval_min: u32,
    advertising_interval_max: u32,
    tx_power: i32,
    scan_interval: u32,
    scan_window: u32,
}

impl Default for Ws73DiscoveryPolicy {
    fn default() -> Self {
        Self {
            advertising_interval_min: 1200,
            advertising_interval_max: 1200,
            tx_power: 127,
            scan_interval: 1600,
            scan_window: 800,
        }
    }
}

impl Ws73DiscoveryPolicy {
    /// Intervals/windows use 125-us slots, power uses dBm; 127 means no
    /// preference. SDK sle_device_discovery.h defines these numeric bounds.
    pub fn new(min: u32, max: u32, power: i32, interval: u32, window: u32) -> Result<Self> {
        if !(0x20..=0xffffff).contains(&min) || !(min..=0xffffff).contains(&max) {
            return Err(Error::InvalidParam(
                "WS73 advertising slots must be 32..16777215 with min <= max",
            ));
        }
        if !(-127..=20).contains(&power) && power != 127 {
            return Err(Error::InvalidParam(
                "WS73 TX power must be -127..20 dBm or 127 (no preference)",
            ));
        }
        if !(4..=0xffff).contains(&interval) || !(4..=interval).contains(&window) {
            return Err(Error::InvalidParam(
                "WS73 scan slots must be 4..65535 with window <= interval",
            ));
        }
        Ok(Self {
            advertising_interval_min: min,
            advertising_interval_max: max,
            tx_power: power,
            scan_interval: interval,
            scan_window: window,
        })
    }

    /// Read-only policy provenance, not a claim that RF or PM is qualified.
    pub fn parameters(self) -> (u32, u32, u32, i32, u32, u32) {
        (
            WS73_DISCOVERY_POLICY_VERSION,
            self.advertising_interval_min,
            self.advertising_interval_max,
            self.tx_power,
            self.scan_interval,
            self.scan_window,
        )
    }
}

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

/// Handle 0, nonconnectable/nonqueryable, fixed T, public queried address,
/// configured interval/power and channels 76/77/78. Defaults retain 150 ms and
/// no power preference (127);
/// primary frame type 1 (encoded 0). No scan response or autonomous termination.
/// Support on actual firmware is proved by its result, never a fallback/echo.
impl Ws73DiscoveryPolicy {
    pub fn advertisement(
        &self,
        snapshot: &SleControllerSnapshot,
        request_id: u64,
        marker: &[u8; 16],
    ) -> Result<SleDiscoverySubmit> {
        let mut request = identity(snapshot, request_id, true)?;
        request.operation = DISCOVERY_ADV_START;
        request.advertising = basic_advertiser_config(snapshot, self);
        let data = ws73_marker_data(marker);
        request.data_len = data.len() as u32;
        request.data[..data.len()].copy_from_slice(&data);
        Ok(request)
    }

    /// Explicit fixed-T, connectable/non-scannable announcement. The default
    /// beacon remains nonconnectable. WS73 mode1 and request posture1/0 are
    /// independent protocol facts; accepting this command does not establish
    /// a link or prove firmware interoperability.
    pub fn connectable_advertisement(
        &self,
        snapshot: &SleControllerSnapshot,
        request_id: u64,
        marker: &[u8; 16],
    ) -> Result<SleDiscoverySubmit> {
        let mut request = self.advertisement(snapshot, request_id, marker)?;
        request.advertising.mode = 1;
        request.advertising.request_notification = 1;
        Ok(request)
    }
}

fn basic_advertiser_config(
    snapshot: &SleControllerSnapshot,
    policy: &Ws73DiscoveryPolicy,
) -> SleDiscoveryAdvConfig {
    SleDiscoveryAdvConfig {
        handle: 0,
        mode: 0,
        gt_role: 2,
        interval_min: policy.advertising_interval_min,
        interval_max: policy.advertising_interval_max,
        channel_map: 7,
        own_address_type: 0,
        peer_address_type: 0,
        own_address: snapshot.address,
        peer_address: [0; 6],
        filter: 0,
        tx_power: policy.tx_power,
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
impl Ws73DiscoveryPolicy {
    pub fn standby(
        &self,
        snapshot: &SleControllerSnapshot,
        request_id: u64,
    ) -> Result<SleDiscoverySubmit> {
        let mut request = identity(snapshot, request_id, false)?;
        request.operation = DISCOVERY_ADV_CONFIGURE_OFF;
        request.advertising = basic_advertiser_config(snapshot, self);
        Ok(request)
    }

    /// Passive frame-1 scan, any peer, duplicates retained; configured interval
    /// and window in 125-us slots (defaults 200/100 ms). Scan frame-1 bitmap is 1, not adv's 0.
    pub fn scan(
        &self,
        snapshot: &SleControllerSnapshot,
        request_id: u64,
    ) -> Result<SleDiscoverySubmit> {
        let mut request = identity(snapshot, request_id, true)?;
        request.operation = DISCOVERY_SCAN_START;
        request.scanning = basic_scanner_config(self);
        Ok(request)
    }
}

fn basic_scanner_config(policy: &Ws73DiscoveryPolicy) -> SleDiscoveryScanConfig {
    SleDiscoveryScanConfig {
        own_address_type: 0,
        filter: 0,
        frame_types: 1,
        active: 0,
        interval: policy.scan_interval,
        window: policy.scan_window,
        filter_duplicates: 0,
    }
}

/// Probe a passive scanner ON then OFF, requiring both successful Completes.
/// This briefly enables reception; it never sends active scan requests.
impl Ws73DiscoveryPolicy {
    pub fn scan_standby(
        &self,
        snapshot: &SleControllerSnapshot,
        request_id: u64,
    ) -> Result<SleDiscoverySubmit> {
        let mut request = identity(snapshot, request_id, false)?;
        request.operation = DISCOVERY_SCAN_INITIALIZE_OFF;
        request.scanning = basic_scanner_config(self);
        Ok(request)
    }
}

/// Stops can establish initial off while Setup, but cannot clear a Host fault.
pub fn ws73_discovery_stop(
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
    #[test]
    fn explicit_connectable_policy_keeps_default_beacon_and_identity_guards() {
        let policy = Ws73DiscoveryPolicy::new(1237, 1301, -20, 1703, 997).unwrap();
        let identity = snapshot();
        let beacon = policy.advertisement(&identity, 11, &[0xab; 16]).unwrap();
        let mut connection = policy
            .connectable_advertisement(&identity, 11, &[0xab; 16])
            .unwrap();
        assert_eq!(
            (
                beacon.advertising.mode,
                beacon.advertising.request_notification
            ),
            (0, 0)
        );
        assert_eq!(
            (
                connection.advertising.mode,
                connection.advertising.gt_role,
                connection.advertising.request_notification,
                connection.advertising.max_requests
            ),
            (1, 2, 1, 0)
        );
        assert_eq!(connection.data, beacon.data);
        assert_eq!(connection.generation, beacon.generation);
        // Compare every named field without reading C padding.
        connection.advertising.mode = 0;
        connection.advertising.request_notification = 0;
        assert_eq!(format!("{:?}", connection), format!("{:?}", beacon));
        for invalid in [
            SleControllerSnapshot {
                flags: CONTROLLER_SETUP,
                ..identity
            },
            SleControllerSnapshot {
                generation: 0,
                ..identity
            },
            SleControllerSnapshot {
                profile: 0,
                ..identity
            },
        ] {
            assert!(
                policy
                    .connectable_advertisement(&invalid, 11, &[0; 16])
                    .is_err()
            );
        }
        assert!(
            policy
                .connectable_advertisement(&identity, 0, &[0; 16])
                .is_err()
        );
        assert_eq!(policy.standby(&identity, 12).unwrap().advertising.mode, 0);
    }
    #[test]
    fn numeric_policy_bounds_fail_before_constructing_requests() {
        for (min, max, power, interval, window) in [
            (0, 1200, 127, 1600, 800),
            (31, 1200, 127, 1600, 800),
            (1200, 1199, 127, 1600, 800),
            (32, 0x1000000, 127, 1600, 800),
            (1200, 1200, -128, 1600, 800),
            (1200, 1200, 21, 1600, 800),
            (1200, 1200, 126, 1600, 800),
            (1200, 1200, 127, 3, 3),
            (1200, 1200, 127, 1600, 3),
            (1200, 1200, 127, 1600, 1601),
            (1200, 1200, 127, 65536, 800),
        ] {
            assert!(Ws73DiscoveryPolicy::new(min, max, power, interval, window).is_err());
        }
        for (min, max, power, interval, window) in [
            (32, 32, -127, 4, 4),
            (0xffffff, 0xffffff, 20, 65535, 65535),
            (1200, 1600, 0, 1600, 800),
            (1200, 1200, 127, 1600, 800),
        ] {
            assert!(Ws73DiscoveryPolicy::new(min, max, power, interval, window).is_ok());
        }
    }
    #[test]
    fn setup_and_start_share_the_selected_policy_and_keep_identity_scoped() {
        let a = Ws73DiscoveryPolicy::new(1237, 1301, -20, 1703, 997).unwrap();
        let b = Ws73DiscoveryPolicy::default();
        let ready = snapshot();
        let setup = SleControllerSnapshot {
            flags: CONTROLLER_SETUP,
            ..ready
        };
        let off = a.standby(&setup, 11).unwrap();
        let on = a.advertisement(&ready, 12, &[0xab; 16]).unwrap();
        assert_eq!(off.advertising.interval_min, on.advertising.interval_min);
        assert_eq!(
            (
                on.advertising.interval_min,
                on.advertising.interval_max,
                on.advertising.tx_power
            ),
            (1237, 1301, -20)
        );
        assert_eq!(
            (
                off.generation,
                on.generation,
                off.advertising.own_address,
                on.advertising.own_address
            ),
            (
                ready.generation,
                ready.generation,
                ready.address,
                ready.address
            )
        );
        let off_scan = a.scan_standby(&setup, 13).unwrap();
        let on_scan = a.scan(&ready, 14).unwrap();
        assert_eq!(
            (off_scan.scanning.interval, off_scan.scanning.window),
            (on_scan.scanning.interval, on_scan.scanning.window)
        );
        assert_eq!(
            (on_scan.scanning.interval, on_scan.scanning.window),
            (1703, 997)
        );
        assert_eq!(b.parameters(), (3, 1200, 1200, 127, 1600, 800));
        assert!(a.advertisement(&setup, 15, &[0; 16]).is_err());
        assert!(a.scan(&setup, 16).is_err());
    }
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
        let request = Ws73DiscoveryPolicy::default().standby(&setup, 10).unwrap();
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
            Ws73DiscoveryPolicy::default()
                .standby(
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
    fn scan_standby_uses_setup_without_enable_and_rejects_faults() {
        let setup = SleControllerSnapshot {
            flags: CONTROLLER_SETUP,
            ..snapshot()
        };
        let req = Ws73DiscoveryPolicy::default()
            .scan_standby(&setup, 12)
            .unwrap();
        assert_eq!(req.operation, DISCOVERY_SCAN_INITIALIZE_OFF);
        assert_eq!(
            (
                req.scanning.frame_types,
                req.scanning.active,
                req.scanning.interval,
                req.scanning.window
            ),
            (1, 0, 1600, 800)
        );
        assert_eq!(
            (
                req.data_len,
                req.flags,
                req.handle,
                req.duration,
                req.max_events
            ),
            (0, 0, 0, 0, 0)
        );
        assert_eq!(
            (
                req.advertising.interval_min,
                req.advertising.interval_max,
                req.advertising.channel_map
            ),
            (0, 0, 0)
        );
        for flags in [CONTROLLER_FAULT, 0] {
            assert!(
                Ws73DiscoveryPolicy::default()
                    .scan_standby(&SleControllerSnapshot { flags, ..setup }, 13)
                    .is_err()
            );
        }
        assert!(
            Ws73DiscoveryPolicy::default()
                .scan_standby(&setup, 0)
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
        let req = Ws73DiscoveryPolicy::default()
            .advertisement(&snapshot(), 7, &[0; 16])
            .unwrap();
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
        let scan = Ws73DiscoveryPolicy::default().scan(&snapshot(), 8).unwrap();
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
            assert!(Ws73DiscoveryPolicy::default().scan(&s, 1).is_err());
            assert!(
                Ws73DiscoveryPolicy::default()
                    .advertisement(&s, 1, &[0; 16])
                    .is_err()
            );
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
            assert!(Ws73DiscoveryPolicy::default().scan(&s, 1).is_err());
        }
        assert!(Ws73DiscoveryPolicy::default().scan(&snapshot(), 0).is_err());
        let setup = SleControllerSnapshot {
            flags: CONTROLLER_SETUP,
            ..snapshot()
        };
        assert!(ws73_discovery_stop(&setup, 1, DISCOVERY_ADV_STOP).is_ok());
        assert!(ws73_discovery_stop(&setup, 1, DISCOVERY_SCAN_START).is_err());
        for flags in [CONTROLLER_FAULT, 0, 5] {
            let invalid = SleControllerSnapshot {
                flags,
                ..snapshot()
            };
            assert!(ws73_discovery_stop(&invalid, 1, DISCOVERY_ADV_STOP).is_err());
        }
    }
}
