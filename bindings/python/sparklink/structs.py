"""Current ctypes definitions mirroring sparklink.h and sparklink_native.h.

Layouts are checked against actual Rust types/channel/message_security and kernel declarations.
SleAddr is a raw 6-byte array (typedef uint8_t SleAddr[6] in C).
"""

import ctypes
from enum import IntEnum


class BusType(IntEnum):
    """Provider provenance; Test never denotes qualified physical hardware."""
    Virtual = 0
    Uart = 1
    Spi = 2
    Sdio = 3
    Usb = 4
    Mmio = 5
    Test = 6


# SleAddr: typedef uint8_t SleAddr[6]
SleAddr = ctypes.c_uint8 * 6


# Explicit 8-byte alignment matches the versioned native UAPI. _align_ is
# supported by newer ctypes; NativeAdapter checks it before using these types
# on older 32-bit interpreters. Retired layouts live only in test fixtures.
class SleRegistrationSnapshot(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("generation", ctypes.c_uint64), ("version", ctypes.c_uint32),
        ("state", ctypes.c_uint32), ("profile", ctypes.c_uint32),
        ("phase", ctypes.c_uint32), ("error", ctypes.c_int32),
        ("dev_index", ctypes.c_uint16), ("bus", ctypes.c_uint8),
        ("reserved_byte", ctypes.c_uint8), ("reserved", ctypes.c_uint8 * 8),
    ]


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


class SleDiagnosticSubmit(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("version", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("generation", ctypes.c_uint64), ("request_id", ctypes.c_uint64),
        ("timeout_ms", ctypes.c_uint32), ("opcode", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16), ("seq", ctypes.c_uint32),
        ("action", ctypes.c_uint32),
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


class SleConnectionParameters(ctypes.Structure):
    _fields_ = [
        ("filter", ctypes.c_uint32), ("own_address_type", ctypes.c_uint32),
        ("peer_address_type", ctypes.c_uint32), ("peer_address", ctypes.c_uint8 * 6),
        ("reserved", ctypes.c_uint8 * 2), ("gt_negotiate", ctypes.c_uint32),
        ("frame", ctypes.c_uint32), ("scan_interval", ctypes.c_uint32),
        ("scan_window", ctypes.c_uint32), ("interval_min", ctypes.c_uint32),
        ("interval_max", ctypes.c_uint32), ("latency", ctypes.c_uint32),
        ("supervision_timeout", ctypes.c_uint32), ("event_min", ctypes.c_uint32),
        ("event_max", ctypes.c_uint32),
    ]


class SleConnectionSubmit(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("version", ctypes.c_uint32), ("profile", ctypes.c_uint32),
        ("operation", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("generation", ctypes.c_uint64), ("request_id", ctypes.c_uint64),
        ("timeout_ms", ctypes.c_uint32), ("handle", ctypes.c_uint32),
        ("reason", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("parameters", SleConnectionParameters), ("reserved_tail", ctypes.c_uint32),
        ("expected_lifetime", ctypes.c_uint64), ("expected_address", ctypes.c_uint8 * 6),
        ("expected_address_type", ctypes.c_uint8), ("expected_role", ctypes.c_uint8),
    ]


class SleConnectionResult(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("version", ctypes.c_uint32), ("profile", ctypes.c_uint32),
        ("state", ctypes.c_uint32), ("operation", ctypes.c_uint32),
        ("generation", ctypes.c_uint64), ("request_id", ctypes.c_uint64),
        ("error", ctypes.c_int32), ("fault_error", ctypes.c_int32),
        ("command_status", ctypes.c_uint32), ("outcome_status", ctypes.c_uint32),
        ("handle", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("dev_index", ctypes.c_uint16), ("reserved", ctypes.c_uint8 * 6),
    ]


class SleLinkInfo(ctypes.Structure):
    _align_ = 8
    _fields_ = [("lifetime", ctypes.c_uint64), ("handle", ctypes.c_uint16),
        ("role", ctypes.c_uint8), ("address_type", ctypes.c_uint8),
        ("address", ctypes.c_uint8 * 6), ("reserved", ctypes.c_uint8 * 6)]


class SleLinkSnapshot(ctypes.Structure):
    _align_ = 8
    _fields_ = [("generation", ctypes.c_uint64), ("event_seq", ctypes.c_uint64),
        ("revision", ctypes.c_uint64), ("version", ctypes.c_uint32),
        ("profile", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("count", ctypes.c_uint32),
        ("error", ctypes.c_int32), ("dev_index", ctypes.c_uint16), ("reserved", ctypes.c_uint8 * 2),
        ("links", SleLinkInfo * 16)]


class SleChannelInfo(ctypes.Structure):
    _align_ = 8
    _fields_ = [
        ("version", ctypes.c_uint16), ("size", ctypes.c_uint16),
        ("controller", ctypes.c_uint16), ("handle", ctypes.c_uint16),
        ("generation", ctypes.c_uint64), ("lifetime", ctypes.c_uint64),
        ("mtu", ctypes.c_uint16), ("mps", ctypes.c_uint16),
        ("local_tcid", ctypes.c_uint8), ("remote_tcid", ctypes.c_uint8),
        ("pi", ctypes.c_uint8), ("mode", ctypes.c_uint8),
        ("directions", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
    ]


class SleChannelTxStatus(ctypes.Structure):
    _align_ = 8
    _fields_ = [("version", ctypes.c_uint16), ("size", ctypes.c_uint16),
        ("controller", ctypes.c_uint16), ("handle", ctypes.c_uint16),
        ("generation", ctypes.c_uint64), ("lifetime", ctypes.c_uint64),
        ("packet_maximum", ctypes.c_uint16), ("capacity", ctypes.c_uint16),
        ("outstanding", ctypes.c_uint16), ("connection_debt", ctypes.c_uint16),
        ("peak_reserved", ctypes.c_uint16), ("queued", ctypes.c_uint16),
        ("queue_limit", ctypes.c_uint16), ("busy", ctypes.c_uint16),
        ("active_pdu_bytes", ctypes.c_uint32), ("active_pdu_offset", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("pool_exhaustions", ctypes.c_uint64)]


SECURITY_CAPABILITY_ONLY = 1
SECURITY_KEY_AGREEMENT_ONLY = 2
SECURITY_UNAUTHENTICATED_ENCRYPTION = 3
SNOOP_REDACTED = 2


class SleSecurityNegotiationSubmit(ctypes.Structure):
    """Explicit limited exchange approval; no raw relay or trusted security."""
    _align_ = 8
    _fields_ = [("generation",ctypes.c_uint64),("lifetime",ctypes.c_uint64),("request_id",ctypes.c_uint64),("deadline_monotonic_ns",ctypes.c_uint64),
        ("version",ctypes.c_uint32),("profile",ctypes.c_uint32),("action",ctypes.c_uint32),("flags",ctypes.c_uint32),("timeout_ms",ctypes.c_uint32),
        ("handle",ctypes.c_uint16),("role",ctypes.c_uint8),("address_type",ctypes.c_uint8),("address",ctypes.c_uint8*6),("reserved",ctypes.c_uint8*2)]


class SleSecurityNegotiationResult(ctypes.Structure):
    """Local observations only; state4/8 are neither Pair nor Encrypted."""
    _align_ = 8
    _fields_ = [("generation",ctypes.c_uint64),("lifetime",ctypes.c_uint64),("request_id",ctypes.c_uint64),
        ("version",ctypes.c_uint32),("profile",ctypes.c_uint32),("state",ctypes.c_uint32),("error",ctypes.c_int32),("flags",ctypes.c_uint32),
        ("handle",ctypes.c_uint16),("role",ctypes.c_uint8),("status",ctypes.c_uint8),("local_caps",ctypes.c_uint8*10),("peer_caps",ctypes.c_uint8*10),("comparison_code",ctypes.c_uint32)]


class SleSecurityNegotiationCancel(ctypes.Structure):
    """Only original author request withdrawal; physical obligations remain."""
    _align_ = 8
    _fields_ = [("generation", ctypes.c_uint64), ("lifetime", ctypes.c_uint64),
                ("request_id", ctypes.c_uint64), ("version", ctypes.c_uint32),
                ("handle", ctypes.c_uint16), ("reserved", ctypes.c_uint16)]


class SleSessionTxStatus(ctypes.Structure):
    """Unpublished v1 mechanism counts, not a drain/reuse or firmware proof."""
    _align_ = 8
    _fields_ = [("version",ctypes.c_uint16),("size",ctypes.c_uint16),
        ("controller",ctypes.c_uint16),("handle",ctypes.c_uint16),
        ("generation",ctypes.c_uint64),("lifetime",ctypes.c_uint64),
        ("capacity",ctypes.c_uint16),("outstanding",ctypes.c_uint16),
        ("connection_debt",ctypes.c_uint16),("queued",ctypes.c_uint16),
        ("active_pdus",ctypes.c_uint16),("dynamic_open",ctypes.c_uint16),
        ("dynamic_pending",ctypes.c_uint16),("dynamic_retired",ctypes.c_uint16),
        ("dynamic_failed",ctypes.c_uint16),("dynamic_allocated",ctypes.c_uint16),
        ("flags",ctypes.c_uint32),("reserved",ctypes.c_uint64*2)]


class SleSecurityNumericConfirm(ctypes.Structure):
    """Original privileged comparison prompt decision; no key/credential input."""
    _align_ = 8
    _fields_ = [("generation",ctypes.c_uint64),("lifetime",ctypes.c_uint64),("request_id",ctypes.c_uint64),
        ("version",ctypes.c_uint32),("comparison_code",ctypes.c_uint32),("handle",ctypes.c_uint16),
        ("accept",ctypes.c_uint8),("reserved",ctypes.c_uint8*5)]


class SleConnectionSecurity(ctypes.Structure):
    """Current mechanism facts, not historical success, identity, Bond or Grant."""
    _align_ = 8
    _fields_ = [("generation",ctypes.c_uint64),("lifetime",ctypes.c_uint64),
        ("security_epoch",ctypes.c_uint64),("version",ctypes.c_uint32),
        ("profile",ctypes.c_uint32),("level",ctypes.c_uint32),("flags",ctypes.c_uint32),
        ("handle",ctypes.c_uint16),("method",ctypes.c_uint8),("key_size",ctypes.c_uint8),
        ("error",ctypes.c_int32)]


class SleMessageSecurity(ctypes.Structure):
    """40-byte kernel receipt facts; not identity, Bond or future send consent."""
    _align_ = 8
    _fields_ = [("version", ctypes.c_uint16), ("size", ctypes.c_uint16),
        ("security", ctypes.c_uint32), ("generation", ctypes.c_uint64),
        ("lifetime", ctypes.c_uint64), ("security_epoch", ctypes.c_uint64),
        ("controller", ctypes.c_uint16), ("handle", ctypes.c_uint16),
        ("local_tcid", ctypes.c_uint8), ("remote_tcid", ctypes.c_uint8),
        ("pi", ctypes.c_uint8), ("flags", ctypes.c_uint8)]


class SleSendConstraint(ctypes.Structure):
    """48-byte restrictive TX intent; original fd Grant remains mandatory."""
    _align_ = 8
    _fields_ = [("version", ctypes.c_uint16), ("size", ctypes.c_uint16),
        ("minimum", ctypes.c_uint32), ("generation", ctypes.c_uint64),
        ("lifetime", ctypes.c_uint64), ("security_epoch", ctypes.c_uint64),
        ("controller", ctypes.c_uint16), ("handle", ctypes.c_uint16),
        ("local_tcid", ctypes.c_uint8), ("remote_tcid", ctypes.c_uint8),
        ("pi", ctypes.c_uint8), ("reserved", ctypes.c_uint8),
        ("deadline_monotonic_ns", ctypes.c_uint64)]
