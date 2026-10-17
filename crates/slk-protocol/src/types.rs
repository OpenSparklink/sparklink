// SparkLink UAPI type definitions
// Mirror of include/uapi/sparklink/sparklink_ioctl.h and sparklink.h

/// MAC address (6 bytes)
pub type SleAddr = [u8; 6];

// ----- Connection States -----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ConnState {
    Idle = 0,
    Connecting = 1,
    Connected = 2,
    Disconnecting = 3,
}

// ----- Power States -----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum PmState {
    Active = 0,
    Sniff = 1,
    Idle = 2,
    Suspended = 3,
}

// ----- Security States -----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum SecState {
    None = 0,
    Pairing = 1,
    Paired = 2,
    Encrypted = 3,
}

// ----- Pairing Methods -----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum PairMethod {
    None = 0,
    JustWorks = 1,
    Psk = 2,
}

// ----- Discovery Levels (TXS-20001-2025) -----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum DiscoveryLevel {
    Invisible = 0,
    General = 1,
    Priority = 2,
    PairedOnly = 3,
    Designated = 4,
}

// ----- Bus Types -----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum BusType {
    Virtual = 0,
    Uart = 1,
    Spi = 2,
    Sdio = 3,
    Usb = 4,
    Mmio = 5,
    /// Explicit test provider, distinct from physical USB and VirtualBackend.
    Test = 6,
}

// ----- DLI Packet Type Indicators -----

pub const DLI_PKT_COMMAND: u8 = 0xA1;
pub const DLI_PKT_EVENT: u8 = 0xA2;
pub const DLI_PKT_ASYNC_UCAST: u8 = 0xA3;
pub const DLI_PKT_SYNC_UCAST: u8 = 0xA4;
pub const DLI_PKT_ASYNC_MCAST: u8 = 0xA5;

// ----- DLI Event Types (sle_dli_event_to_wire encoding) -----

pub const EVT_CMD_COMPLETE: u8 = 0x01;
pub const EVT_CMD_STATUS: u8 = 0x02;
pub const EVT_ADV_REPORT: u8 = 0x03;
pub const EVT_CONN_COMPLETE: u8 = 0x04;
pub const EVT_DATA_RECV: u8 = 0x05;
pub const EVT_DISCONNECTED: u8 = 0x06;
pub const EVT_ENCRYPTION_CHANGED: u8 = 0x07;
pub const EVT_PAIR_REQUEST: u8 = 0x08;
pub const EVT_HW_ERROR: u8 = 0x09;
pub const EVT_BROADCAST_END: u8 = 0x0A;
pub const EVT_PHY_UPDATE: u8 = 0x0B;

// ----- UAPI Structs (repr(C) for ioctl ABI compatibility) -----

/// Device information (ioctl 0x04)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SciDevInfo {
    pub index: u16,
    pub state: u8,
    pub bus: u8,
    pub addr: SleAddr,
    pub name: [u8; 32],
    pub _reserved: [u8; 24],
}

/// Supported native controller event ABI version.
pub const CONTROLLER_EVENT_VERSION: u32 = 1;
pub const CONTROLLER_EVENT_PAYLOAD_MAX: usize = 288;
pub const CONTROLLER_EVENT_PROFILE_WS73_HCC: u32 = 1;

/// Complete, validated controller parameters from one registration.
/// Sequence and loss counts belong to that registration and reader cursor.
#[derive(Debug, Clone, Copy)]
#[repr(C, align(8))]
pub struct SleControllerEvent {
    pub seq: u64,
    pub generation: u64,
    /// CLOCK_BOOTTIME receipt timestamp, in nanoseconds.
    pub timestamp_ns: u64,
    pub lost: u64,
    pub profile: u32,
    pub dev_index: u16,
    pub event_code: u16,
    pub payload_len: u16,
    pub flags: u16,
    pub _reserved: u32,
    pub payload: [u8; CONTROLLER_EVENT_PAYLOAD_MAX],
}

/// Input cursor/version with an output-only event record (ioctl 0x87).
#[derive(Debug, Clone, Copy)]
#[repr(C, align(8))]
pub struct SleControllerEventQuery {
    pub after_seq: u64,
    pub generation: u64,
    pub version: u32,
    pub flags: u32,
    pub event: SleControllerEvent,
}

/// Borrowed WS73 discovery parameters. The raw header preserves address
/// types, direct address, PHY and vendor byte without standard aliases.
#[derive(Debug)]
pub struct Ws73DiscoveryReport<'a> {
    pub header: &'a [u8; 23],
    pub data: &'a [u8],
    pub rssi: i8,
}

impl SleControllerEvent {
    /// Decode exactly one WS73 0x180b report. Fragment/truncation flags in
    /// header[0] are retained; this does not reassemble or invent a level.
    pub fn ws73_discovery(&self) -> Option<Ws73DiscoveryReport<'_>> {
        if self.profile != CONTROLLER_EVENT_PROFILE_WS73_HCC
            || self.event_code != 0x180b
            || self.flags != 0
            || self._reserved != 0
            || self.seq == 0
            || self.generation == 0
        {
            return None;
        }
        let body = self.payload.get(..usize::from(self.payload_len))?;
        let header: &[u8; 23] = body.get(..23)?.try_into().ok()?;
        if body.len() != 23 + usize::from(header[22]) {
            return None;
        }
        Some(Ws73DiscoveryReport {
            header,
            data: &body[23..],
            rssi: header[21] as i8,
        })
    }
}

/// Management stats (ioctl 0x85)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleMgmtStats {
    pub pending: u16,
    pub _pad: u16,
    pub total_submitted: u32,
    pub total_resolved: u32,
    pub total_timeouts: u32,
}

// Version 1 typed discovery ABI. Select a registration before probing/submitting.
// Explicit profile fields/units, opaque data; no implicit board/radio defaults.
pub const DISCOVERY_VERSION: u32 = 1;
pub const DISCOVERY_ADV_START: u32 = 1;
pub const DISCOVERY_ADV_STOP: u32 = 2;
pub const DISCOVERY_SCAN_START: u32 = 3;
pub const DISCOVERY_SCAN_STOP: u32 = 4;
/// Configure explicit advertiser parameters and obtain a successful OFF Complete.
pub const DISCOVERY_ADV_CONFIGURE_OFF: u32 = 5;
/// Passive parameters/ON/OFF probe; only the final OFF Complete establishes off.
pub const DISCOVERY_SCAN_INITIALIZE_OFF: u32 = 6;
pub const DISCOVERY_SCAN_RESPONSE: u32 = 1;
pub const DISCOVERY_FAULT: u32 = 1;
pub const DISCOVERY_RADIO_UNKNOWN: u32 = 0;
pub const DISCOVERY_RADIO_OFF: u32 = 1;
pub const DISCOVERY_RADIO_ON: u32 = 2;
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct SleDiscoveryAdvConfig {
    pub handle: u32,
    pub mode: u32,
    pub gt_role: u32,
    pub interval_min: u32,
    pub interval_max: u32,
    pub channel_map: u32,
    pub own_address_type: u32,
    pub peer_address_type: u32,
    pub own_address: [u8; 6],
    pub peer_address: [u8; 6],
    pub filter: u32,
    pub tx_power: i32,
    pub primary_frame: u32,
    pub secondary_frame: u32,
    pub secondary_phy: u32,
    pub secondary_pilot: u32,
    pub secondary_mcs: u32,
    pub secondary_max_skip: u32,
    pub sid: u32,
    pub request_notification: u32,
    pub max_requests: u32,
    pub request_rx_duration: u32,
    pub conn_interval_min: u32,
    pub conn_interval_max: u32,
    pub conn_max_latency: u32,
    pub supervision_timeout: u32,
    pub min_event_length: u32,
    pub max_event_length: u32,
}
impl Default for SleDiscoveryAdvConfig {
    fn default() -> Self {
        // SAFETY: every field is an integer or byte array; zero is valid.
        unsafe { std::mem::zeroed() }
    }
}
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct SleDiscoveryScanConfig {
    pub own_address_type: u32,
    pub filter: u32,
    pub frame_types: u32,
    pub active: u32,
    pub interval: u32,
    pub window: u32,
    pub filter_duplicates: u32,
}
impl Default for SleDiscoveryScanConfig {
    fn default() -> Self {
        // SAFETY: every field is an integer or byte array; zero is valid.
        unsafe { std::mem::zeroed() }
    }
}
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug)]
pub struct SleDiscoverySubmit {
    pub version: u32,
    pub profile: u32,
    pub operation: u32,
    pub flags: u32,
    pub generation: u64,
    pub request_id: u64,
    pub advertising: SleDiscoveryAdvConfig,
    pub scanning: SleDiscoveryScanConfig,
    pub handle: u32,
    pub duration: u32,
    pub max_events: u32,
    pub data_len: u32,
    pub scan_response_len: u32,
    pub reserved: u32,
    pub data: [u8; 251],
    pub scan_response: [u8; 251],
    pub reserved_tail: [u8; 2],
}
impl Default for SleDiscoverySubmit {
    fn default() -> Self {
        // SAFETY: every field is an integer or byte array; zero is valid.
        unsafe { std::mem::zeroed() }
    }
}
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug)]
pub struct SleDiscoveryResult {
    pub generation: u64,
    pub request_id: u64,
    pub version: u32,
    pub flags: u32,
    pub profile: u32,
    pub operation: u32,
    pub state: u32,
    pub error: i32,
    pub selected_power: i32,
    pub radio_adv: u32,
    pub radio_scan: u32,
    pub dev_index: u16,
    pub opcode: u16,
    pub step: u8,
    pub count: u8,
    pub status: u8,
    pub power_valid: u8,
    pub reserved: [u8; 4],
}
impl Default for SleDiscoveryResult {
    fn default() -> Self {
        // SAFETY: every field is an integer or byte array; zero is valid.
        unsafe { std::mem::zeroed() }
    }
}
impl SleDiscoveryResult {
    /// Queued/pending results are never mistaken for radio completion.
    pub fn is_terminal(&self) -> bool {
        (3..=6).contains(&self.state)
    }
}

/// Selected registration metadata and Host readiness, independent of RF state.
/// FULL_METADATA marks the queried native five-byte version/80-bit features.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
#[repr(C, align(8))]
pub struct SleControllerSnapshot {
    pub generation: u64,
    pub version: u32,
    pub flags: u32,
    pub profile: u32,
    pub valid_fields: u32,
    pub dev_index: u16,
    pub bus: u8,
    pub command_credits: u8,
    pub acb_length: u16,
    pub icb_length: u16,
    pub acb_count: u8,
    pub icb_count: u8,
    pub version_tuple: [u8; 5],
    pub features: [u8; 10],
    pub address: [u8; 6],
    pub reserved_byte: u8,
    pub error: i32,
    pub reserved: [u8; 4],
}
pub const CONTROLLER_SNAPSHOT_VERSION: u32 = 1;
pub const CONTROLLER_READY: u32 = 1;
pub const CONTROLLER_SETUP: u32 = 2;
pub const CONTROLLER_FAULT: u32 = 4;
pub const CONTROLLER_FULL_METADATA: u32 = 1;

/// Core registration observation, independent of selected fd/Host Ready.
/// Installed is not Ready; phase/error are raw provider diagnostics for pending
/// registrations only. Removal may follow the atomic observation immediately.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
#[repr(C, align(8))]
pub struct SleRegistrationSnapshot {
    pub generation: u64,
    pub version: u32,
    pub state: u32,
    pub profile: u32,
    pub phase: u32,
    pub error: i32,
    pub dev_index: u16,
    pub bus: u8,
    pub reserved_byte: u8,
    pub reserved: [u8; 8],
}
pub const REGISTRATION_VERSION: u32 = 1;
pub const REGISTRATION_PENDING: u32 = 1;
pub const REGISTRATION_FAULT: u32 = 2;
pub const REGISTRATION_INSTALLED: u32 = 3;
pub const REGISTRATION_RETIRING: u32 = 4;
/// Atomic Core observation over D-Bus: generation, version, state, profile,
/// raw pending phase/error, index, bus. Contains no Host Ready or capabilities.
pub type RegistrationSnapshotRecord = (u64, u32, u32, u32, u32, i32, u16, u8);
impl SleRegistrationSnapshot {
    pub fn valid_for(&self, index: u16, generation: u64) -> bool {
        self.version == REGISTRATION_VERSION
            && self.generation != 0
            && (generation == 0 || self.generation == generation)
            && index < 16
            && self.dev_index == index
            && self.bus <= 6
            && self.reserved_byte == 0
            && self.reserved == [0; 8]
            && match self.state {
                REGISTRATION_PENDING => self.error == 0,
                REGISTRATION_FAULT => self.error < 0,
                REGISTRATION_INSTALLED | REGISTRATION_RETIRING => {
                    self.phase == 0 && self.error == 0
                }
                _ => false,
            }
    }
}

/// D-Bus operation record: generation, request id, operation, state, errno,
/// raw status, opcode, step, count, actual selected power, power valid,
/// confirmed adv state, confirmed scan state, profile. This is not a C ABI.
pub type DiscoveryResultRecord = (
    u64,
    u64,
    u32,
    u32,
    i32,
    u8,
    u16,
    u8,
    u8,
    i32,
    bool,
    u32,
    u32,
    u32,
);
impl SleDiscoveryResult {
    pub fn as_record(&self) -> DiscoveryResultRecord {
        (
            self.generation,
            self.request_id,
            self.operation,
            self.state,
            self.error,
            self.status,
            self.opcode,
            self.step,
            self.count,
            self.selected_power,
            self.power_valid != 0,
            self.radio_adv,
            self.radio_scan,
            self.profile,
        )
    }
}

/// seq, generation, kernel CLOCK_BOOTTIME ns, daemon wall ms, address, RSSI,
/// raw header, raw data, lost. Opaque headers never imply PHY reassembly.
pub type TimedDiscoveryReportRecord = (u64, u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64);

pub const MANAGEMENT_VERSION: u32 = 1;
pub const MANAGEMENT_MANAGED: u32 = 1;
pub const MANAGEMENT_DIAGNOSTIC: u32 = 2;
pub const MANAGEMENT_FREE: u32 = 0;
pub const MANAGEMENT_HELD: u32 = 1;
pub const MANAGEMENT_REVOKING: u32 = 2;
pub const MANAGEMENT_FAULTED: u32 = 3;

pub const SNOOP_VERSION: u32 = 1;
pub const SNOOP_PAYLOAD_MAX: usize = 320;
pub const SNOOP_FORMAT_WS73_DLI: u8 = 1;
pub const SNOOP_FORMAT_STANDARD_DLI: u8 = 2;
pub const SNOOP_TRUNCATED: u16 = 1;
pub const SNOOP_REDACTED: u16 = 2;
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug)]
pub struct SleSnoopRecord {
    pub seq: u64,
    pub generation: u64,
    pub timestamp_ns: u64,
    pub lost: u64,
    pub profile: u32,
    pub original_length: u32,
    pub status: i32,
    pub dev_index: u16,
    pub direction: u8,
    pub format: u8,
    pub captured_length: u16,
    pub flags: u16,
    pub reserved: u32,
    pub payload: [u8; SNOOP_PAYLOAD_MAX],
}
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug)]
pub struct SleSnoopQuery {
    pub generation: u64,
    pub after_seq: u64,
    pub version: u32,
    pub flags: u32,
    pub reserved: u64,
    pub record: SleSnoopRecord,
}
pub const SL_IOCTL_SNOOP_GET: u32 = 0xc198538e;
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SleManagementRequest {
    pub generation: u64,
    pub lease: u64,
    pub version: u32,
    pub mode: u32,
    pub flags: u32,
    pub reserved: u32,
}
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SleManagementQuery {
    pub generation: u64,
    pub lease: u64,
    pub version: u32,
    pub mode: u32,
    pub state: u32,
    pub flags: u32,
    pub error: i32,
    pub status: u32,
    pub opcode: u32,
    pub reserved: u32,
}

/// Final successful matched Complete receipt (CLOCK_BOOTTIME ns).
/// Pending, failed/cancelled/faulted without success have timestamp zero.
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug, Default)]
pub struct SleDiscoveryTiming {
    pub generation: u64,
    pub request_id: u64,
    pub completed_boottime_ns: u64,
    pub version: u32,
    pub flags: u32,
    pub operation: u32,
    pub state: u32,
    pub dev_index: u16,
    pub opcode: u16,
    pub status: u8,
    pub reserved: [u8; 3],
}

/// Owner-private non-destructive diagnostic result (ioctl 0xd0).
#[derive(Debug, Clone, Copy)]
#[repr(C, align(8))]
pub struct SleDiagnosticResult {
    pub version: u32,
    pub flags: u32,
    pub generation: u64,
    pub seq: u32,
    pub state: u32,
    pub error: i32,
    pub opcode: u16,
    pub status: u8,
    pub _pad: u8,
    pub data_len: u16,
    pub _reserved: [u8; 6],
    pub data: [u8; 64],
}
impl Default for SleDiagnosticResult {
    fn default() -> Self {
        // SAFETY: fixed integers/byte arrays; zero is valid for every field.
        unsafe { core::mem::zeroed() }
    }
}

/// Caller-keyed Native metadata admission or cancellation (ioctl 0xd1).
/// Repeat the same request ID/fields after EFAULT; never invent a fresh ID.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
#[repr(C, align(8))]
pub struct SleDiagnosticSubmit {
    pub version: u32,
    pub flags: u32,
    pub generation: u64,
    pub request_id: u64,
    pub timeout_ms: u32,
    pub opcode: u16,
    pub reserved: u16,
    pub seq: u32,
    pub action: u32,
}

/// Native connection parameters use the explicit controller profile dialect.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct SleConnectionParameters {
    pub filter: u32,
    pub own_address_type: u32,
    pub peer_address_type: u32,
    pub peer_address: [u8; 6],
    pub reserved: [u8; 2],
    pub gt_negotiate: u32,
    pub frame: u32,
    pub scan_interval: u32,
    pub scan_window: u32,
    pub interval_min: u32,
    pub interval_max: u32,
    pub latency: u32,
    pub supervision_timeout: u32,
    pub event_min: u32,
    pub event_max: u32,
}
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug, Default)]
pub struct SleConnectionSubmit {
    pub version: u32,
    pub profile: u32,
    pub operation: u32,
    pub flags: u32,
    pub generation: u64,
    pub request_id: u64,
    pub timeout_ms: u32,
    pub handle: u32,
    pub reason: u32,
    pub reserved: u32,
    pub parameters: SleConnectionParameters,
    pub reserved_tail: u32,
    pub expected_lifetime: u64,
    pub expected_address: SleAddr,
    pub expected_address_type: u8,
    pub expected_role: u8,
}
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug, Default)]
pub struct SleConnectionResult {
    pub version: u32,
    pub profile: u32,
    pub state: u32,
    pub operation: u32,
    pub generation: u64,
    pub request_id: u64,
    pub error: i32,
    pub fault_error: i32,
    pub command_status: u32,
    pub outcome_status: u32,
    pub handle: u32,
    pub flags: u32,
    pub dev_index: u16,
    pub reserved: [u8; 6],
}

pub const LINK_SNAPSHOT_KNOWN: u32 = 1;
pub const LINK_SNAPSHOT_MAX: usize = 16;
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SleLinkInfo {
    pub lifetime: u64,
    pub handle: u16,
    pub role: u8,
    pub address_type: u8,
    pub address: SleAddr,
    pub reserved: [u8; 6],
}
#[repr(C, align(8))]
#[derive(Clone, Copy, Debug, Default)]
pub struct SleLinkSnapshot {
    pub generation: u64,
    pub event_seq: u64,
    pub revision: u64,
    pub version: u32,
    pub profile: u32,
    pub flags: u32,
    pub count: u32,
    pub error: i32,
    pub dev_index: u16,
    pub reserved: [u8; 2],
    pub links: [SleLinkInfo; LINK_SNAPSHOT_MAX],
}
impl SleLinkSnapshot {
    /// Validate a complete bounded reply before publishing any peer state.
    /// Unknown has an error and an empty *representation*, not an empty link set.
    pub fn valid_for(&self, generation: u64) -> bool {
        if self.version != 1
            || generation == 0
            || self.generation != generation
            || self.profile == 0
            || self.reserved != [0; 2]
            || self.count as usize > LINK_SNAPSHOT_MAX
        {
            return false;
        }
        if self.flags == 0 {
            return self.error < 0
                && self.count == 0
                && self.links.iter().all(|v| *v == SleLinkInfo::default());
        }
        if self.flags != LINK_SNAPSHOT_KNOWN || self.error != 0 {
            return false;
        }
        let count = self.count as usize;
        for (i, link) in self.links[..count].iter().enumerate() {
            if link.lifetime == 0
                || link.lifetime > self.revision
                || link.role > 1
                || link.address == [0; 6]
                || link.address == [255; 6]
                || link.reserved != [0; 6]
                || self.links[..i]
                    .iter()
                    .any(|old| old.handle == link.handle || old.lifetime == link.lifetime)
            {
                return false;
            }
        }
        self.links[count..]
            .iter()
            .all(|v| *v == SleLinkInfo::default())
    }
}

impl Default for SleControllerEvent {
    fn default() -> Self {
        // SAFETY: repr(C) integers and byte arrays accept zero. seq/generation
        // zero is an invalid observation; decoders reject it until populated.
        unsafe { std::mem::zeroed() }
    }
}

/// WS73 physical facts; command acceptance and author results are separate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ws73LinkOutcome {
    Connected {
        status: u8,
        handle: u16,
        role: u8,
        address_type: u8,
        address: SleAddr,
    },
    Disconnected {
        status: u8,
        handle: u16,
        reason: u8,
    },
}
impl SleControllerEvent {
    pub fn ws73_link_outcome(&self) -> Option<Ws73LinkOutcome> {
        if self.profile != CONTROLLER_EVENT_PROFILE_WS73_HCC
            || self.flags != 0
            || self._reserved != 0
            || self.seq == 0
            || self.generation == 0
        {
            return None;
        }
        let body = self.payload.get(..usize::from(self.payload_len))?;
        match self.event_code {
            0x15 | 0x1401 if body.len() >= 11 => {
                let address: SleAddr = body[5..11].try_into().ok()?;
                if body[0] == 0 && (body[3] > 1 || address == [0; 6] || address == [255; 6]) {
                    return None;
                }
                Some(Ws73LinkOutcome::Connected {
                    status: body[0],
                    handle: u16::from_le_bytes([body[1], body[2]]),
                    role: body[3],
                    address_type: body[4],
                    address,
                })
            }
            5 | 0x1405 if body.len() >= 4 => Some(Ws73LinkOutcome::Disconnected {
                status: body[0],
                handle: u16::from_le_bytes([body[1], body[2]]),
                reason: body[3],
            }),
            _ => None,
        }
    }
}

#[cfg(test)]
mod ws73_link_tests {
    use super::*;
    fn event(code: u16, body: &[u8]) -> SleControllerEvent {
        let mut e = SleControllerEvent {
            profile: 1,
            generation: 7,
            seq: 1,
            event_code: code,
            payload_len: body.len() as u16,
            ..Default::default()
        };
        e.payload[..body.len()].copy_from_slice(body);
        e
    }
    #[test]
    fn exact_profile_aliases_handle_bounds_and_original_extensions() {
        for code in [0x15, 0x1401] {
            for handle in [0, 65535u16] {
                let mut body = vec![
                    0,
                    handle as u8,
                    (handle >> 8) as u8,
                    1,
                    255,
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                ];
                body.extend_from_slice(&[7; 12]);
                let e = event(code, &body);
                let original = e.payload;
                assert_eq!(
                    e.ws73_link_outcome(),
                    Some(Ws73LinkOutcome::Connected {
                        status: 0,
                        handle,
                        role: 1,
                        address_type: 255,
                        address: [1, 2, 3, 4, 5, 6]
                    })
                );
                assert_eq!(e.payload, original);
            }
        }
        for code in [5, 0x1405] {
            assert_eq!(
                event(code, &[0, 0, 0, 0x13]).ws73_link_outcome(),
                Some(Ws73LinkOutcome::Disconnected {
                    status: 0,
                    handle: 0,
                    reason: 0x13
                })
            );
        }
    }
    #[test]
    fn malformed_identity_and_success_are_rejected_failure_is_not_fake_disconnect() {
        for n in 0..11 {
            assert!(event(0x15, &vec![0; n]).ws73_link_outcome().is_none());
        }
        let body = [0, 7, 0, 0, 0, 1, 1, 1, 1, 1, 1];
        let mut e = event(0x15, &body);
        e.profile = 0;
        assert!(e.ws73_link_outcome().is_none());
        e.profile = 1;
        e.flags = 1;
        assert!(e.ws73_link_outcome().is_none());
        e.flags = 0;
        e.payload[3] = 2;
        assert!(e.ws73_link_outcome().is_none());
        assert_eq!(
            event(5, &[1, 7, 0, 0x13]).ws73_link_outcome(),
            Some(Ws73LinkOutcome::Disconnected {
                status: 1,
                handle: 7,
                reason: 0x13
            })
        );
    }
}

#[cfg(test)]
mod link_snapshot_tests {
    use super::*;
    #[test]
    fn malformed_or_unknown_table_never_becomes_empty_known_state() {
        let mut s = SleLinkSnapshot {
            version: 1,
            generation: 7,
            profile: 1,
            flags: LINK_SNAPSHOT_KNOWN,
            ..Default::default()
        };
        assert!(s.valid_for(7));
        assert!(!s.valid_for(8));
        s.flags = 0;
        assert!(!s.valid_for(7));
        s.error = -117;
        assert!(s.valid_for(7));
        s.count = 1;
        assert!(!s.valid_for(7));
        s.count = 0;
        s.links[15].lifetime = 1;
        assert!(!s.valid_for(7));
    }
    #[test]
    fn complete_lifetime_and_identity_checked_before_any_peer_publication() {
        let mut s = SleLinkSnapshot {
            version: 1,
            generation: 7,
            profile: 1,
            flags: LINK_SNAPSHOT_KNOWN,
            revision: 3,
            count: 1,
            ..Default::default()
        };
        s.links[0] = SleLinkInfo {
            lifetime: 3,
            handle: 0,
            role: 1,
            address_type: 0,
            address: [1; 6],
            reserved: [0; 6],
        };
        assert!(s.valid_for(7));
        for bad in [
            SleLinkInfo {
                lifetime: 0,
                ..s.links[0]
            },
            SleLinkInfo {
                lifetime: 4,
                ..s.links[0]
            },
            SleLinkInfo {
                role: 2,
                ..s.links[0]
            },
            SleLinkInfo {
                address: [0; 6],
                ..s.links[0]
            },
            SleLinkInfo {
                reserved: [1; 6],
                ..s.links[0]
            },
        ] {
            let mut t = s;
            t.links[0] = bad;
            assert!(!t.valid_for(7));
        }
        s.count = 2;
        s.links[1] = s.links[0];
        assert!(!s.valid_for(7));
        s.links[1].handle = 1;
        s.links[1].lifetime = 2;
        assert!(s.valid_for(7));
        s.links[15].lifetime = 1;
        assert!(!s.valid_for(7));
    }
}

#[cfg(test)]
mod registration_tests {
    use super::*;
    #[test]
    fn core_observation_requires_exact_identity_and_consistent_diagnostics() {
        let mut s = SleRegistrationSnapshot {
            version: REGISTRATION_VERSION,
            generation: 7,
            dev_index: 2,
            state: REGISTRATION_PENDING,
            bus: 4,
            ..Default::default()
        };
        assert!(s.valid_for(2, 0));
        assert!(s.valid_for(2, 7));
        assert!(!s.valid_for(2, 8));
        assert!(!s.valid_for(3, 7));
        assert!(!s.valid_for(16, 7));
        s.state = REGISTRATION_FAULT;
        assert!(!s.valid_for(2, 7));
        s.error = -2;
        s.phase = 3;
        assert!(s.valid_for(2, 7));
        for state in [REGISTRATION_INSTALLED, REGISTRATION_RETIRING] {
            s.phase = 3;
            s.error = -2;
            s.state = state;
            assert!(!s.valid_for(2, 7));
            s.phase = 0;
            s.error = 0;
            assert!(s.valid_for(2, 7));
            s.reserved_byte = 1;
            assert!(!s.valid_for(2, 7));
            s.reserved_byte = 0;
        }
        s.generation = 0;
        assert!(!s.valid_for(2, 0));
    }
}

/// Experimental capability/candidate-proof observation; no raw RX/TX or trusted result.
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default)]
pub struct SleSecurityNegotiationSubmit {
    pub generation: u64,
    pub lifetime: u64,
    pub request_id: u64,
    /// Original CLOCK_MONOTONIC deadline, set before policy/Agent waiting.
    pub deadline_monotonic_ns: u64,
    pub version: u32,
    pub profile: u32,
    pub action: u32,
    pub flags: u32,
    pub timeout_ms: u32,
    pub handle: u16,
    pub role: u8,
    pub address_type: u8,
    pub address: [u8; 6],
    pub reserved: [u8; 2],
}

/// Local observations only: state4/state8/state9 do not prove identity, trust or peer application ACK.
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default)]
pub struct SleSecurityNegotiationResult {
    pub generation: u64,
    pub lifetime: u64,
    pub request_id: u64,
    pub version: u32,
    pub profile: u32,
    pub state: u32,
    pub error: i32,
    pub flags: u32,
    pub handle: u16,
    pub role: u8,
    pub status: u8,
    pub local_caps: [u8; 10],
    pub peer_caps: [u8; 10],
    pub comparison_code: u32,
}

/// Explicit opt-in to the limited exchange; never a trusted-security flag.
pub const SECURITY_CAPABILITY_ONLY: u32 = 1;
/// Unauthenticated candidate agreement only, no Agent/install/encryption/Bond.
pub const SECURITY_KEY_AGREEMENT_ONLY: u32 = 2;
pub const SECURITY_UNAUTHENTICATED_ENCRYPTION: u32 = 3;

/// Withdraw one original Managed File request; not controller release or wire cancellation.
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default)]
pub struct SleSecurityNegotiationCancel {
    pub generation: u64,
    pub lifetime: u64,
    pub request_id: u64,
    pub version: u32,
    pub handle: u16,
    pub reserved: u16,
}
const _: () = assert!(core::mem::size_of::<SleSecurityNegotiationCancel>() == 32);

/// One decision on the original numeric prompt; no credential or raw proof.
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default)]
pub struct SleSecurityNumericConfirm {
    pub generation: u64,
    pub lifetime: u64,
    pub request_id: u64,
    pub version: u32,
    pub comparison_code: u32,
    pub handle: u16,
    pub accept: u8,
    pub reserved: [u8; 5],
}
pub const SECURITY_NUMERIC_COMPARISON: u32 = 4;
const _: () = assert!(core::mem::size_of::<SleSecurityNumericConfirm>() == 40);

/// Current physical Session mechanism facts, not historical operation success,
/// application authorization, named identity or Bond. Epoch advances at native
/// ingress before ordinary queueing; snapshot alone cannot authorize later TX.
#[repr(C, align(8))]
#[derive(Debug, Clone, Copy, Default)]
pub struct SleConnectionSecurity {
    pub generation: u64,
    pub lifetime: u64,
    pub security_epoch: u64,
    pub version: u32,
    pub profile: u32,
    pub level: u32,
    pub flags: u32,
    pub handle: u16,
    pub method: u8,
    pub key_size: u8,
    pub error: i32,
}
const _: () = assert!(core::mem::size_of::<SleConnectionSecurity>() == 48);
