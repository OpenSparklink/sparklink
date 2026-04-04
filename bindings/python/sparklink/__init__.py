"""SparkLink Python bindings via ctypes FFI."""

from sparklink.adapter import Adapter
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
