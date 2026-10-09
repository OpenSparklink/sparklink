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
