"""SparkLink Python bindings via ctypes FFI."""

from sparklink.adapter import Adapter
from sparklink.native import NativeAdapter
from sparklink.ssap import SsapOperations
from sparklink.structs import (
    SleAddr,
    SleConnInfo,
    SleConnectParams,
    SleDliEvent,
    SleDliInfo,
    SlePairParams,
    SlePhyInfo,
    SleScanParams,
    SleSecInfo,
    SciDevInfo,
    SsapReadWrite,
    SsapSummary,
)

__all__ = [
    "Adapter",
    "NativeAdapter",
    "SsapOperations",
    "SleAddr",
    "SleConnInfo",
    "SleConnectParams",
    "SleDliEvent",
    "SleDliInfo",
    "SlePairParams",
    "SlePhyInfo",
    "SleScanParams",
    "SleSecInfo",
    "SciDevInfo",
    "SsapReadWrite",
    "SsapSummary",
]
