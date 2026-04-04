"""C structure definitions mirroring sparklink.h."""

import ctypes


class SleAddr(ctypes.Structure):
    _fields_ = [
        ("type_", ctypes.c_uint8),
        ("addr", ctypes.c_uint8 * 8),
    ]

    def __repr__(self):
        octets = ":".join(f"{b:02x}" for b in self.addr[:6])
        return f"SleAddr(type={self.type_}, addr={octets})"


class SleScanParams(ctypes.Structure):
    _fields_ = [
        ("scan_type", ctypes.c_uint8),
        ("phy", ctypes.c_uint8),
        ("interval", ctypes.c_uint16),
        ("window", ctypes.c_uint16),
        ("duration", ctypes.c_uint16),
        ("_reserved", ctypes.c_uint8 * 8),
    ]


class SleConnectParams(ctypes.Structure):
    _fields_ = [
        ("peer", SleAddr),
        ("_pad", ctypes.c_uint8 * 1),
        ("interval_min", ctypes.c_uint16),
        ("interval_max", ctypes.c_uint16),
        ("latency", ctypes.c_uint16),
        ("timeout", ctypes.c_uint16),
        ("_reserved", ctypes.c_uint8 * 8),
    ]


class SleConnInfo(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint16),
        ("state", ctypes.c_uint8),
        ("role", ctypes.c_uint8),
        ("peer", SleAddr),
        ("_pad", ctypes.c_uint8 * 1),
        ("interval", ctypes.c_uint16),
        ("latency", ctypes.c_uint16),
        ("timeout", ctypes.c_uint16),
        ("mtu", ctypes.c_uint16),
        ("rssi", ctypes.c_int8),
        ("tx_phy", ctypes.c_uint8),
        ("rx_phy", ctypes.c_uint8),
        ("_reserved", ctypes.c_uint8 * 8),
    ]


class SleSecInfo(ctypes.Structure):
    _fields_ = [
        ("level", ctypes.c_uint8),
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
        ("security_cap", ctypes.c_uint8),
        ("features_ext", ctypes.c_uint8),
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
