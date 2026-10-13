"""SparkLink Python bindings via ctypes FFI."""

from sparklink.adapter import Adapter
from sparklink.native import NativeAdapter, registration_snapshot
from sparklink.ssap import SsapOperations
from sparklink.structs import (
    BusType,
    SleAddr,
    SleConnInfo,
    SleConnectParams,
    SleDliInfo,
    SlePairParams,
    SlePhyInfo,
    SleScanParams,
    SleSecInfo,
    SciDevInfo,
)

__all__ = [
    "Adapter",
    "NativeAdapter",
    "registration_snapshot",
    "SsapOperations",
    "BusType",
    "SleAddr",
    "SleConnInfo",
    "SleConnectParams",
    "SleDliInfo",
    "SlePairParams",
    "SlePhyInfo",
    "SleScanParams",
    "SleSecInfo",
    "SciDevInfo",
]
