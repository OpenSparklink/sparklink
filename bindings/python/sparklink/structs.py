"""ctypes definitions mirroring the cbindgen-generated sparklink.h.

All layouts match the Rust repr(C) structs in slk-protocol/types.rs.
SleAddr is a raw 6-byte array (typedef uint8_t SleAddr[6] in C).
"""

import ctypes

# SleAddr: typedef uint8_t SleAddr[6]
SleAddr = ctypes.c_uint8 * 6


# Explicit 8-byte alignment matches the versioned native UAPI. _align_ is
# supported by newer ctypes; NativeAdapter checks it before using these types
# on older 32-bit interpreters. Legacy types remain usable independently.
class SleControllerSnapshot(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("generation", ctypes.c_uint64), ("version", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("profile", ctypes.c_uint32),
        ("valid_fields", ctypes.c_uint32), ("dev_index", ctypes.c_uint16),
        ("bus", ctypes.c_uint8), ("command_credits", ctypes.c_uint8),
        ("acb_length", ctypes.c_uint16), ("icb_length", ctypes.c_uint16),
        ("acb_count", ctypes.c_uint8), ("icb_count", ctypes.c_uint8),
        ("version_tuple", ctypes.c_uint8 * 5), ("features", ctypes.c_uint8 * 10),
        ("address", SleAddr), ("reserved_byte", ctypes.c_uint8),
        ("error", ctypes.c_int32), ("reserved", ctypes.c_uint8 * 4),
    ]


class SleManagementQuery(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("generation", ctypes.c_uint64), ("lease", ctypes.c_uint64),
        ("version", ctypes.c_uint32), ("mode", ctypes.c_uint32),
        ("state", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("error", ctypes.c_int32), ("status", ctypes.c_uint32),
        ("opcode", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
    ]


class SleControllerEvent(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("seq", ctypes.c_uint64), ("generation", ctypes.c_uint64),
        ("timestamp_ns", ctypes.c_uint64), ("lost", ctypes.c_uint64),
        ("profile", ctypes.c_uint32), ("dev_index", ctypes.c_uint16),
        ("event_code", ctypes.c_uint16), ("payload_len", ctypes.c_uint16),
        ("flags", ctypes.c_uint16), ("_reserved", ctypes.c_uint32),
        ("payload", ctypes.c_uint8 * 288),
    ]


class SleControllerEventQuery(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("after_seq", ctypes.c_uint64), ("generation", ctypes.c_uint64),
        ("version", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("event", SleControllerEvent),
    ]


class SleSnoopRecord(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("seq", ctypes.c_uint64), ("generation", ctypes.c_uint64),
        ("timestamp_ns", ctypes.c_uint64), ("lost", ctypes.c_uint64),
        ("profile", ctypes.c_uint32), ("original_length", ctypes.c_uint32),
        ("status", ctypes.c_int32), ("dev_index", ctypes.c_uint16),
        ("direction", ctypes.c_uint8), ("format", ctypes.c_uint8),
        ("captured_length", ctypes.c_uint16), ("flags", ctypes.c_uint16),
        ("reserved", ctypes.c_uint32), ("payload", ctypes.c_uint8 * 320),
    ]


class SleSnoopQuery(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("generation", ctypes.c_uint64), ("after_seq", ctypes.c_uint64),
        ("version", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("reserved", ctypes.c_uint64), ("record", SleSnoopRecord),
    ]


class SleDiagnosticResult(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("version", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("generation", ctypes.c_uint64), ("seq", ctypes.c_uint32),
        ("state", ctypes.c_uint32), ("error", ctypes.c_int32),
        ("opcode", ctypes.c_uint16), ("status", ctypes.c_uint8),
        ("_pad", ctypes.c_uint8), ("data_len", ctypes.c_uint16),
        ("_reserved", ctypes.c_uint8 * 6), ("data", ctypes.c_uint8 * 64),
    ]


class SleDiscoveryAdvConfig(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32), ("mode", ctypes.c_uint32),
        ("gt_role", ctypes.c_uint32), ("interval_min", ctypes.c_uint32),
        ("interval_max", ctypes.c_uint32), ("channel_map", ctypes.c_uint32),
        ("own_address_type", ctypes.c_uint32), ("peer_address_type", ctypes.c_uint32),
        ("own_address", SleAddr), ("peer_address", SleAddr),
        ("filter", ctypes.c_uint32), ("tx_power", ctypes.c_int32),
        ("primary_frame", ctypes.c_uint32), ("secondary_frame", ctypes.c_uint32),
        ("secondary_phy", ctypes.c_uint32), ("secondary_pilot", ctypes.c_uint32),
        ("secondary_mcs", ctypes.c_uint32), ("secondary_max_skip", ctypes.c_uint32),
        ("sid", ctypes.c_uint32), ("request_notification", ctypes.c_uint32),
        ("max_requests", ctypes.c_uint32), ("request_rx_duration", ctypes.c_uint32),
        ("conn_interval_min", ctypes.c_uint32), ("conn_interval_max", ctypes.c_uint32),
        ("conn_max_latency", ctypes.c_uint32), ("supervision_timeout", ctypes.c_uint32),
        ("min_event_length", ctypes.c_uint32), ("max_event_length", ctypes.c_uint32),
    ]


class SleDiscoveryScanConfig(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "own_address_type", "filter", "frame_types", "active",
        "interval", "window", "filter_duplicates",
    )]


class SleDiscoverySubmit(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("version", ctypes.c_uint32), ("profile", ctypes.c_uint32),
        ("operation", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("generation", ctypes.c_uint64), ("request_id", ctypes.c_uint64),
        ("advertising", SleDiscoveryAdvConfig), ("scanning", SleDiscoveryScanConfig),
        ("handle", ctypes.c_uint32), ("duration", ctypes.c_uint32),
        ("max_events", ctypes.c_uint32), ("data_len", ctypes.c_uint32),
        ("scan_response_len", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("data", ctypes.c_uint8 * 251), ("scan_response", ctypes.c_uint8 * 251),
        ("reserved_tail", ctypes.c_uint8 * 2),
    ]


class SleDiscoveryResult(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("generation", ctypes.c_uint64), ("request_id", ctypes.c_uint64),
        ("version", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("profile", ctypes.c_uint32), ("operation", ctypes.c_uint32),
        ("state", ctypes.c_uint32), ("error", ctypes.c_int32),
        ("selected_power", ctypes.c_int32), ("radio_adv", ctypes.c_uint32),
        ("radio_scan", ctypes.c_uint32), ("dev_index", ctypes.c_uint16),
        ("opcode", ctypes.c_uint16), ("step", ctypes.c_uint8),
        ("count", ctypes.c_uint8), ("status", ctypes.c_uint8),
        ("power_valid", ctypes.c_uint8), ("reserved", ctypes.c_uint8 * 4),
    ]

    @property
    def is_terminal(self):
        return 3 <= self.state <= 6


class SleScanParams(ctypes.Structure):
    _fields_ = [
        ("dev_index", ctypes.c_uint16),
        ("window_ms", ctypes.c_uint16),
        ("interval_ms", ctypes.c_uint16),
        ("filter_discovery_level", ctypes.c_uint8),
        ("_reserved", ctypes.c_uint8 * 9),
    ]


class SleConnectParams(ctypes.Structure):
    _fields_ = [
        ("peer_addr", SleAddr),
        ("gt_role", ctypes.c_uint8),
        ("bandwidth", ctypes.c_uint8),
        ("mcs_index", ctypes.c_uint8),
        ("_pad", ctypes.c_uint8),
        ("timeout_10ms", ctypes.c_uint16),
        ("_reserved", ctypes.c_uint8 * 4),
    ]


class SleConnInfo(ctypes.Structure):
    _fields_ = [
        ("tx_bytes", ctypes.c_uint64),
        ("rx_bytes", ctypes.c_uint64),
        ("handle", ctypes.c_uint16),
        ("event_group_period", ctypes.c_uint16),
        ("supervision_timeout", ctypes.c_uint16),
        ("tx_pending", ctypes.c_uint16),
        ("rx_pending", ctypes.c_uint16),
        ("state", ctypes.c_uint8),
        ("peer_addr", SleAddr),
        ("local_role", ctypes.c_uint8),
        ("bandwidth_mhz", ctypes.c_uint8),
        ("mcs_index", ctypes.c_uint8),
        ("tx_seq", ctypes.c_uint8),
        ("rx_seq", ctypes.c_uint8),
        ("data_mtu", ctypes.c_uint16),
        ("data_mps", ctypes.c_uint16),
        ("svc_mtu", ctypes.c_uint16),
        ("data_mode", ctypes.c_uint8),
        ("ssap_info_exchanged", ctypes.c_uint8),
        ("ssap_mtu", ctypes.c_uint16),
        ("ssap_reliable_mode", ctypes.c_uint8),
        ("ssap_version_major", ctypes.c_uint8),
        ("smtc_tx_credits", ctypes.c_uint16),
        ("smtc_rx_credits", ctypes.c_uint16),
        ("dudtc_tx_credits", ctypes.c_uint16),
        ("dudtc_rx_credits", ctypes.c_uint16),
    ]


class SleSecInfo(ctypes.Structure):
    _fields_ = [
        ("state", ctypes.c_uint8),
        ("method", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),
        ("enc_enabled", ctypes.c_uint8),
        ("enc_key_fingerprint", ctypes.c_uint8 * 4),
        ("_reserved", ctypes.c_uint8 * 8),
    ]


class SlePairParams(ctypes.Structure):
    _fields_ = [
        ("method", ctypes.c_uint8),
        ("_reserved", ctypes.c_uint8 * 3),
    ]


class SsapSummary(ctypes.Structure):
    _fields_ = [
        ("service_count", ctypes.c_uint16),
        ("property_count", ctypes.c_uint16),
        ("total_entries", ctypes.c_uint16),
        ("mtu", ctypes.c_uint16),
        ("notification_count", ctypes.c_uint16),
        ("_reserved", ctypes.c_uint8 * 6),
    ]


class SsapReadWrite(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * 252),
    ]


class SleDliEvent(ctypes.Structure):
    _fields_ = [
        ("event_type", ctypes.c_uint8),
        ("status", ctypes.c_uint8),
        ("handle", ctypes.c_uint16),
        ("opcode", ctypes.c_uint16),
        ("data_len", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * 240),
        ("addr", SleAddr),
        ("_pad", ctypes.c_uint8 * 2),
    ]


class SciDevInfo(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint16),
        ("state", ctypes.c_uint8),
        ("bus", ctypes.c_uint8),
        ("addr", SleAddr),
        ("name", ctypes.c_uint8 * 32),
        ("_reserved", ctypes.c_uint8 * 24),
    ]

    @property
    def device_name(self):
        raw = bytes(self.name)
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


class SleDliInfo(ctypes.Structure):
    _fields_ = [
        ("bus", ctypes.c_uint8),
        ("_pad", ctypes.c_uint8 * 3),
        ("firmware_version", ctypes.c_uint32),
        ("features", ctypes.c_uint64),
        ("max_connections", ctypes.c_uint8),
        ("max_adv_sets", ctypes.c_uint8),
        ("transport_modes", ctypes.c_uint8),
        ("measurement_cap", ctypes.c_uint8),
        ("max_mtu", ctypes.c_uint16),
        ("max_mps", ctypes.c_uint16),
        ("security_cap", ctypes.c_uint16),
        ("features_ext", ctypes.c_uint16),
        ("name", ctypes.c_uint8 * 32),
        ("_reserved", ctypes.c_uint8 * 4),
    ]


class SlePhyInfo(ctypes.Structure):
    _fields_ = [
        ("mcs_index", ctypes.c_uint8),
        ("bandwidth_mhz", ctypes.c_uint8),
        ("pilot_density", ctypes.c_uint8),
        ("tx_power_dbm", ctypes.c_int8),
        ("mimo_mode", ctypes.c_uint8),
        ("num_tx_ant", ctypes.c_uint8),
        ("num_rx_ant", ctypes.c_uint8),
        ("ofdm", ctypes.c_uint8),
        ("data_rate_kbps", ctypes.c_uint32),
        ("hop_channel", ctypes.c_uint8),
        ("hop_increment", ctypes.c_uint8),
        ("hop_used_channels", ctypes.c_uint8),
        ("_pad", ctypes.c_uint8),
        ("modulation", ctypes.c_uint8),
        ("code_rate_num", ctypes.c_uint8),
        ("code_rate_den", ctypes.c_uint8),
        ("_reserved", ctypes.c_uint8 * 5),
    ]


class SleDiscoveryTiming(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("generation", ctypes.c_uint64), ("request_id", ctypes.c_uint64),
        ("completed_boottime_ns", ctypes.c_uint64), ("version", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("operation", ctypes.c_uint32),
        ("state", ctypes.c_uint32), ("dev_index", ctypes.c_uint16),
        ("opcode", ctypes.c_uint16), ("status", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 3),
    ]
