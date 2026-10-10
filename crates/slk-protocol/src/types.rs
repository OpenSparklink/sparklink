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

/// Advertising parameters (ioctl 0x10)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleAdvParams {
    pub dev_index: u16,
    pub interval_ms: u16,
    pub discovery_level: u8,
    pub _reserved: [u8; 11],
}

/// Scan parameters (ioctl 0x12)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleScanParams {
    pub dev_index: u16,
    pub window_ms: u16,
    pub interval_ms: u16,
    pub filter_discovery_level: u8,
    pub _reserved: [u8; 9],
}

/// Scan UUID filter (ioctl 0x23)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleScanFilter {
    pub uuid_count: u8,
    pub _reserved: [u8; 3],
    pub uuids: [u16; 4],
}

/// Inject advertisement (ioctl 0x20)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleInjectAdv {
    pub addr: SleAddr,
    pub rssi: i8,
    pub discovery_level: u8,
    pub name: [u8; 32],
    pub name_len: u8,
    pub _reserved: [u8; 7],
}

/// Inject raw advertisement PDU (ioctl 0x22)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleInjectRawAdv {
    pub rssi: i8,
    pub _pad: u8,
    pub pdu_len: u16,
    pub pdu_data: [u8; 264],
}

/// Extended advertising config (ioctl 0x14)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleExtAdvConfig {
    pub handle: u8,
    pub discovery_level: u8,
    pub sid: u8,
    pub broadcast_type: u8,
    pub primary_phy: u8,
    pub secondary_phy: u8,
    pub tx_power_dbm: i8,
    pub include_tx_power: u8,
    pub interval_ms: u16,
    pub ext_adv_timing: u8,
    pub _reserved: [u8; 5],
}

/// Extended advertising data (ioctl 0x15)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleExtAdvData {
    pub handle: u8,
    pub _pad: u8,
    pub data_len: u16,
    pub data: [u8; 252],
}

/// Extended advertising info (ioctl 0x19)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleExtAdvInfo {
    pub handle: u8,
    pub state: u8,
    pub sid: u8,
    pub primary_phy: u8,
    pub data_len: u16,
    pub ext_adv_timing: u8,
    pub max_adv_events: u8,
    pub tx_count: u64,
    pub events_sent: u32,
    pub _pad: [u8; 4],
}

/// Extended advertising enable params (ioctl 0x1A)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleExtAdvEnableParams {
    pub handle: u8,
    pub max_adv_events: u8,
    pub duration_10ms: u16,
    pub _reserved: [u8; 4],
}

/// Connection parameters (ioctl 0x30)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnectParams {
    pub peer_addr: SleAddr,
    pub gt_role: u8,
    pub bandwidth: u8,
    pub mcs_index: u8,
    pub _pad: u8,
    pub timeout_10ms: u16,
    pub _reserved: [u8; 4],
}

/// Connection info (ioctl 0x32)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnInfo {
    pub tx_bytes: u64,
    pub rx_bytes: u64,
    pub handle: u16,
    pub event_group_period: u16,
    pub supervision_timeout: u16,
    pub tx_pending: u16,
    pub rx_pending: u16,
    pub state: u8,
    pub peer_addr: SleAddr,
    pub local_role: u8,
    pub bandwidth_mhz: u8,
    pub mcs_index: u8,
    pub tx_seq: u8,
    pub rx_seq: u8,
    pub data_mtu: u16,
    pub data_mps: u16,
    pub svc_mtu: u16,
    pub data_mode: u8,
    pub ssap_info_exchanged: u8,
    pub ssap_mtu: u16,
    pub ssap_reliable_mode: u8,
    pub ssap_version_major: u8,
    pub smtc_tx_credits: u16,
    pub smtc_rx_credits: u16,
    pub dudtc_tx_credits: u16,
    pub dudtc_rx_credits: u16,
}

/// Connection data (ioctl 0x33/0x34/0x36)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnData {
    pub handle: u16,
    pub length: u16,
    pub data: [u8; 255],
    pub _reserved: u8,
}

/// Inject connection response (ioctl 0x35)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleInjectConnResp {
    pub handle: u16,
    pub response_type: u8,
    pub bandwidth_mhz: u8,
    pub mcs_index: u8,
    pub _pad: u8,
    pub supervision_timeout: u16,
    pub data_mtu: u16,
    pub data_mps: u16,
}

/// Connection handle list (ioctl 0x38)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnList {
    pub count: u16,
    pub _pad: u16,
    pub handles: [u16; 8],
    pub _reserved: [u8; 4],
}

/// Connection MTU params (ioctl 0x39)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnMtuParams {
    pub handle: u16,
    pub mtu: u16,
    pub mps: u16,
    pub _pad: u16,
}

/// AFH channel map (ioctl 0x3A/0x3B)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleAfhMapParams {
    pub handle: u16,
    pub min_channels: u8,
    pub _pad: u8,
    pub map: [u8; 10],
    pub used_count: u8,
    pub _pad2: u8,
}

/// AFH RSSI report (ioctl 0x3C)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleAfhRssiReport {
    pub handle: u16,
    pub channel: u8,
    pub rssi_dbm: i8,
}

/// AFH classify (ioctl 0x3D)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleAfhClassifyParams {
    pub handle: u16,
    pub threshold_dbm: i8,
    pub min_channels: u8,
    pub map_out: [u8; 10],
    pub used_count: u8,
    pub _pad: u8,
}

/// AFH hop info (ioctl 0x3E)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleAfhHopInfo {
    pub handle: u16,
    pub channel: u8,
    pub _pad: u8,
    pub freq_mhz: u16,
    pub event_counter: u16,
}

/// AFH retransmission report (ioctl 0x3F)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleAfhRetxReport {
    pub handle: u16,
    pub channel: u8,
    pub retransmitted: u8,
}

/// PSK params (ioctl 0x40)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePskParams {
    pub psk: [u8; 16],
}

/// Pair params (ioctl 0x41)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePairParams {
    pub method: u8,
    pub _reserved: [u8; 3],
}

/// Security info (ioctl 0x42)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSecInfo {
    pub state: u8,
    pub method: u8,
    pub mode: u8,
    pub enc_enabled: u8,
    pub enc_key_fingerprint: [u8; 4],
    pub _reserved: [u8; 8],
}

/// SM3 hash test (ioctl 0x44)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleHashTest {
    pub in_len: u16,
    pub _pad: u16,
    pub data: [u8; 220],
    pub digest: [u8; 32],
}

/// SM4 block test (ioctl 0x47)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSm4BlockTest {
    pub key: [u8; 16],
    pub input: [u8; 16],
    pub output: [u8; 16],
    pub decrypt: u8,
    pub _pad: [u8; 15],
}

/// HMAC test (ioctl 0x48)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleHmacTest {
    pub key_len: u16,
    pub data_len: u16,
    pub key: [u8; 64],
    pub data: [u8; 160],
    pub digest: [u8; 32],
}

/// OOB data (ioctl 0x4D)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleOobData {
    pub data: [u8; 64],
}

/// Passkey input (ioctl 0x4E)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePasskeyInput {
    pub passkey: u32,
}

/// Password params (ioctl 0x4F)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePasswordParams {
    pub len: u8,
    pub _reserved: [u8; 3],
    pub data: [u8; 32],
}

/// SSAP summary (ioctl 0x51)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapSummary {
    pub service_count: u16,
    pub property_count: u16,
    pub total_entries: u16,
    pub mtu: u16,
    pub notification_count: u16,
    pub _reserved: [u8; 6],
}

/// SSAP read/write (ioctl 0x52/0x53)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapReadWrite {
    pub handle: u16,
    pub length: u16,
    pub data: [u8; 252],
}

/// SSAP service entry
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapServiceEntry {
    pub start_handle: u16,
    pub end_handle: u16,
    pub uuid16: u16,
    pub primary: u8,
    pub _pad: u8,
}

/// SSAP service list (ioctl 0x54)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapServiceList {
    pub count: u8,
    pub _pad: [u8; 3],
    pub services: [SsapServiceEntry; 15],
}

/// SSAP notification (ioctl 0x56/0x5E)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapNotification {
    pub handle: u16,
    pub indication: u8,
    pub length: u8,
    pub data: [u8; 252],
}

/// SSAP add service (ioctl 0x57)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapAddService {
    pub uuid16: u16,
    pub primary: u8,
    pub _pad: u8,
    pub uuid128: [u8; 16],
    pub start_handle: u16,
    pub _reserved: [u8; 6],
}

/// SSAP add property (ioctl 0x58)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapAddProperty {
    pub uuid16: u16,
    pub ops: u8,
    pub value_len: u8,
    pub value: [u8; 248],
    pub handle: u16,
    pub _reserved: [u8; 2],
}

/// SSAP remote command (ioctl 0x5A)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapRemoteCmd {
    pub conn_handle: u16,
    pub _reserved: [u8; 2],
}

/// SSAP remote discover (ioctl 0x5B)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapRemoteDiscover {
    pub conn_handle: u16,
    pub start_handle: u16,
    pub end_handle: u16,
    pub count: u16,
}

/// SSAP remote read/write (ioctl 0x5C/0x5D)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapRemoteReadWrite {
    pub conn_handle: u16,
    pub handle: u16,
    pub length: u16,
    pub _pad: [u8; 2],
    pub data: [u8; 248],
}

/// UUID-based SSAP operation (find-by-uuid, read-by-uuid)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SsapUuidOp {
    pub conn_handle: u16,
    pub uuid16: u16,
    pub uuid128: [u8; 16],
    pub handle: u16,
    pub length: u16,
    pub data: [u8; 232],
}

/// Power management info (ioctl 0x60)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePmInfo {
    pub state: u8,
    pub force_active: u8,
    pub power_pct: u8,
    pub _pad: u8,
    pub current_interval: u16,
    pub supervision_timeout: u16,
    pub latency: u16,
    pub idle_count: u16,
    pub transitions: u32,
    pub active_events: u64,
    pub sniff_events: u64,
    pub idle_events: u64,
    pub _reserved: [u8; 8],
}

/// PM state command (ioctl 0x61)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePmStateCmd {
    pub target_state: u8,
    pub _reserved: [u8; 3],
}

/// PM interval (ioctl 0x62)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePmInterval {
    pub min_interval: u16,
    pub max_interval: u16,
    pub latency: u16,
    pub supervision_timeout: u16,
}

/// Sync CIG config (ioctl 0x66)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSyncCigConfig {
    pub cig_id: u8,
    pub link_count: u8,
    pub adapt_mode: u8,
    pub _pad: u8,
    pub sdu_interval_g2t: u32,
    pub sdu_interval_t2g: u32,
    pub max_sdu_g2t: u16,
    pub max_sdu_t2g: u16,
    pub max_latency_g2t: u16,
    pub max_latency_t2g: u16,
    pub retransmit_g2t: u8,
    pub retransmit_t2g: u8,
    pub handles_out: [u16; 8],
}

/// Sync BIG config (ioctl 0x69)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSyncBigConfig {
    pub big_id: u8,
    pub link_count: u8,
    pub adapt_mode: u8,
    pub _pad: u8,
    pub sdu_interval_g2t: u32,
    pub sdu_interval_t2g: u32,
    pub max_sdu_g2t: u16,
    pub max_sdu_t2g: u16,
    pub max_latency_g2t: u16,
    pub max_latency_t2g: u16,
    pub retransmit_g2t: u8,
    pub retransmit_t2g: u8,
    pub handles_out: [u16; 8],
}

/// Sync create command (ioctl 0x67/0x6A)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSyncCreateCmd {
    pub group_id: u8,
    pub link_count: u8,
    pub _pad: [u8; 2],
    pub acl_handles: [u16; 8],
}

/// Sync datapath command (ioctl 0x6C)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSyncDatapathCmd {
    pub sync_handle: u16,
    pub direction: u8,
    pub path_id: u8,
    pub codec_id: u8,
    pub _pad: [u8; 3],
}

/// Sync link info (ioctl 0x6E)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSyncLinkInfo {
    pub sync_handle: u16,
    pub acl_handle: u16,
    pub group_id: u8,
    pub stream_id: u8,
    pub link_type: u8,
    pub state: u8,
    pub sdu_interval_g2t: u32,
    pub sdu_interval_t2g: u32,
    pub max_sdu_g2t: u16,
    pub max_sdu_t2g: u16,
    pub datapath_configured: u8,
    pub _pad2: [u8; 3],
}

/// Event stats (ioctl 0x71)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleEventStats {
    pub pending: u32,
    pub _pad: u32,
    pub total_enqueued: u64,
    pub total_dropped: u64,
    pub total_delivered: u64,
}

/// DLI controller info (ioctl 0x80)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleDliInfo {
    pub bus: u8,
    pub _pad: [u8; 3],
    pub firmware_version: u32,
    pub features: u64,
    pub max_connections: u8,
    pub max_adv_sets: u8,
    pub transport_modes: u8,
    pub measurement_cap: u8,
    pub max_mtu: u16,
    pub max_mps: u16,
    pub security_cap: u16,
    pub features_ext: u16,
    pub name: [u8; 32],
    pub _reserved: [u8; 4],
}

/// DLI event (ioctl 0x82)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleDliEvent {
    pub event_type: u8,
    pub status: u8,
    pub handle: u16,
    pub opcode: u16,
    pub data_len: u16,
    pub data: [u8; 240],
    pub addr: SleAddr,
    pub _pad: [u8; 2],
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

/// DLI command (ioctl 0x84)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleDliCmd {
    pub opcode: u16,
    pub param_len: u16,
    pub seq: u32,
    pub params: [u8; 240],
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

/// Subsystem stats (ioctl 0x86)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSubsysStats {
    pub dev_count: u16,
    pub proto_count: u8,
    pub binding_count: u8,
    pub active_connections: u16,
    pub mgmt_pending: u16,
    pub total_conn_created: u32,
    pub total_conn_completed: u32,
    pub total_mgmt_submitted: u32,
    pub total_mgmt_timeouts: u32,
    pub power_state: u8,
    pub _pad: [u8; 3],
    pub power_transitions: u32,
    pub crc_errors: u32,
}

/// PHY info (ioctl 0x90)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePhyInfo {
    pub mcs_index: u8,
    pub bandwidth_mhz: u8,
    pub pilot_density: u8,
    pub tx_power_dbm: i8,
    pub mimo_mode: u8,
    pub num_tx_ant: u8,
    pub num_rx_ant: u8,
    pub ofdm: u8,
    pub data_rate_kbps: u32,
    pub hop_channel: u8,
    pub hop_increment: u8,
    pub hop_used_channels: u8,
    pub _pad: u8,
    pub modulation: u8,
    pub code_rate_num: u8,
    pub code_rate_den: u8,
    pub _reserved: [u8; 5],
}

/// PHY MCS command (ioctl 0x91)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePhyMcsCmd {
    pub mcs_index: u8,
    pub _reserved: [u8; 3],
}

/// PHY TX power command (ioctl 0x92)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePhyTxPowerCmd {
    pub tx_power_dbm: i8,
    pub _reserved: [u8; 3],
}

/// PHY MCS select (ioctl 0x93)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePhyMcsSelect {
    pub min_kbps: u32,
    pub effective_kbps: u32,
    pub sinr_db_x10: i16,
    pub bandwidth_mhz: u8,
    pub selected_mcs: u8,
}

/// PHY hop info (ioctl 0x94)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePhyHopInfo {
    pub channel: u8,
    pub _pad: u8,
    pub freq_mhz: u16,
    pub event_counter: u16,
    pub _reserved: [u8; 2],
}

/// PHY bandwidth command (ioctl 0x95)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SlePhyBwCmd {
    pub bandwidth_mhz: u8,
    pub _reserved: [u8; 3],
}

/// SINR thresholds (ioctl 0x96/0x97)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleSinrThresholds {
    pub thresholds: [i16; 13],
    pub _pad: [u8; 2],
}

/// Connection peer capability (ioctl 0x98/0x99)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnPeerCap {
    pub handle: u16,
    pub features: [u8; 10],
    pub features_valid: u8,
    pub version: u8,
    pub manufacturer: u16,
    pub subversion: u16,
    pub version_valid: u8,
    pub _reserved: [u8; 3],
}

/// Connection parameter update (ioctl 0x9A)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnParamUpdate {
    pub handle: u16,
    pub interval_min: u16,
    pub interval_max: u16,
    pub latency: u16,
    pub supervision_timeout: u16,
    pub _reserved: [u8; 2],
}

/// Connection PHY update (ioctl 0x9B)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleConnPhyUpdate {
    pub handle: u16,
    pub mcs_index: u8,
    pub bandwidth_mhz: u8,
}

/// RAL add params (ioctl 0xB0)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleRalAddParams {
    pub resolve_algo: u8,
    pub peer_id_type: u8,
    pub peer_irkid: u8,
    pub local_irkid: u8,
    pub peer_id: SleAddr,
    pub _reserved: [u8; 2],
    pub peer_irk: [u8; 16],
    pub local_irk: [u8; 16],
}

/// RAL remove params (ioctl 0xB1)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleRalRemoveParams {
    pub peer_id_type: u8,
    pub _reserved: u8,
    pub peer_id: SleAddr,
}

/// RAL query params (ioctl 0xB4/0xB5)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleRalQueryParams {
    pub id_type: u8,
    pub _reserved: u8,
    pub id: SleAddr,
    pub rpa: SleAddr,
    pub _pad: [u8; 2],
}

/// Measurement capability (ioctl 0xC0)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleMeasCap {
    pub meas_types: u8,
    pub max_instances: u8,
    pub antenna_count: u8,
    pub _reserved: u8,
}

/// Measurement link parameter (ioctl 0xC1)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleMeasLinkParam {
    pub handle: u16,
    pub meas_type: u8,
    pub config_index: u8,
    pub interval: u16,
    pub duration: u16,
}

/// Measurement action (ioctl 0xC2)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleMeasAction {
    pub handle: u16,
    pub action: u8,
    pub config_index: u8,
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
pub const SNOOP_TRUNCATED: u16 = 1;
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
