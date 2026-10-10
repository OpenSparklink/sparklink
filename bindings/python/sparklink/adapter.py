"""High-level Adapter wrapper around libsparklink C FFI."""

import ctypes
import ctypes.util
import os
from pathlib import Path

from .structs import (
    SciDevInfo,
    SleConnInfo,
    SleConnectParams,
    SleDliEvent,
    SleDliInfo,
    SlePairParams,
    SlePhyInfo,
    SleScanParams,
    SleSecInfo,
    SsapReadWrite,
    SsapSummary,
)


def _load_lib():
    """Locate and load libsparklink shared library."""
    # 1) Environment override
    env_path = os.environ.get("LIBSPARKLINK_PATH")
    if env_path and os.path.isfile(env_path):
        return ctypes.CDLL(env_path)

    # 2) Look next to this package (development layout)
    pkg_dir = Path(__file__).resolve().parent
    for candidate in [
        pkg_dir / "libsparklink.so",
        pkg_dir.parent.parent.parent / "target" / "release" / "libsparklink.so",
        pkg_dir.parent.parent.parent / "target" / "debug" / "libsparklink.so",
        pkg_dir.parent.parent.parent / "target" / "release" / "liblibsparklink.so",
        pkg_dir.parent.parent.parent / "target" / "debug" / "liblibsparklink.so",
    ]:
        if candidate.is_file():
            return ctypes.CDLL(str(candidate))

    # 3) System library search
    lib_path = ctypes.util.find_library("sparklink")
    if lib_path:
        return ctypes.CDLL(lib_path)

    raise OSError(
        "Cannot find libsparklink.so. Set LIBSPARKLINK_PATH or install the library."
    )


_lib = None


def _get_lib():
    global _lib
    if _lib is not None:
        return _lib
    lib = _load_lib()

    lib.slk_adapter_open.argtypes = [ctypes.c_char_p]
    lib.slk_adapter_open.restype = ctypes.c_void_p
    lib.slk_adapter_free.argtypes = [ctypes.c_void_p]
    lib.slk_adapter_free.restype = None
    lib.slk_device_count.argtypes = [ctypes.c_void_p]
    lib.slk_device_count.restype = ctypes.c_int
    lib.slk_start_scan.argtypes = [ctypes.c_void_p, ctypes.POINTER(SleScanParams)]
    lib.slk_start_scan.restype = ctypes.c_int
    lib.slk_stop_scan.argtypes = [ctypes.c_void_p]
    lib.slk_stop_scan.restype = ctypes.c_int
    lib.slk_connect.argtypes = [ctypes.c_void_p, ctypes.POINTER(SleConnectParams)]
    lib.slk_connect.restype = ctypes.c_int
    lib.slk_disconnect.argtypes = [ctypes.c_void_p, ctypes.c_uint16]
    lib.slk_disconnect.restype = ctypes.c_int
    lib.slk_conn_info.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.POINTER(SleConnInfo)]
    lib.slk_conn_info.restype = ctypes.c_int
    lib.slk_sec_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(SleSecInfo)]
    lib.slk_sec_info.restype = ctypes.c_int
    lib.slk_pair.argtypes = [ctypes.c_void_p, ctypes.POINTER(SlePairParams)]
    lib.slk_pair.restype = ctypes.c_int
    lib.slk_encrypt_on.argtypes = [ctypes.c_void_p]
    lib.slk_encrypt_on.restype = ctypes.c_int
    lib.slk_ssap_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(SsapSummary)]
    lib.slk_ssap_info.restype = ctypes.c_int
    lib.slk_ssap_read.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.POINTER(SsapReadWrite)]
    lib.slk_ssap_read.restype = ctypes.c_int
    lib.slk_ssap_write.argtypes = [ctypes.c_void_p, ctypes.POINTER(SsapReadWrite)]
    lib.slk_ssap_write.restype = ctypes.c_int
    lib.slk_poll_event.argtypes = [ctypes.c_void_p, ctypes.POINTER(SleDliEvent)]
    lib.slk_poll_event.restype = ctypes.c_int
    lib.slk_device_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(SciDevInfo)]
    lib.slk_device_info.restype = ctypes.c_int
    lib.slk_dli_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(SleDliInfo)]
    lib.slk_dli_info.restype = ctypes.c_int
    lib.slk_phy_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(SlePhyInfo)]
    lib.slk_phy_info.restype = ctypes.c_int
    lib.slk_set_role.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
    lib.slk_set_role.restype = ctypes.c_int
    lib.slk_get_role.argtypes = [ctypes.c_void_p]
    lib.slk_get_role.restype = ctypes.c_int

    _lib = lib
    return _lib


class SparkLinkError(RuntimeError):
    """Raised when a libsparklink C call fails."""


class Adapter:
    """SparkLink adapter handle.

    Usage::

        from sparklink import Adapter

        with Adapter("/dev/sparklink") as adpt:
            info = adpt.device_info()
            print(info.device_name)
    """

    def __init__(self, dev_path="/dev/sparklink"):
        lib = _get_lib()
        path_bytes = dev_path.encode("utf-8") if isinstance(dev_path, str) else dev_path
        self._handle = lib.slk_adapter_open(path_bytes)
        if not self._handle:
            raise SparkLinkError(f"Failed to open adapter: {dev_path}")

    def close(self):
        if self._handle:
            _get_lib().slk_adapter_free(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    def _check(self, ret, msg="operation failed"):
        if ret < 0:
            raise SparkLinkError(msg)
        return ret

    def device_count(self):
        return self._check(_get_lib().slk_device_count(self._handle), "device_count")

    def device_info(self):
        info = SciDevInfo()
        self._check(_get_lib().slk_device_info(self._handle, ctypes.byref(info)), "device_info")
        return info

    def start_scan(self, scan_type=0, phy=0, interval=100, window=50, duration=0):
        params = SleScanParams(
            scan_type=scan_type, phy=phy,
            interval=interval, window=window, duration=duration,
        )
        self._check(_get_lib().slk_start_scan(self._handle, ctypes.byref(params)), "start_scan")

    def stop_scan(self):
        self._check(_get_lib().slk_stop_scan(self._handle), "stop_scan")

    def connect(self, params):
        self._check(_get_lib().slk_connect(self._handle, ctypes.byref(params)), "connect")

    def disconnect(self, handle):
        self._check(_get_lib().slk_disconnect(self._handle, ctypes.c_uint16(handle)), "disconnect")

    def conn_info(self, handle):
        info = SleConnInfo()
        self._check(_get_lib().slk_conn_info(self._handle, ctypes.c_uint16(handle), ctypes.byref(info)), "conn_info")
        return info

    def sec_info(self):
        info = SleSecInfo()
        self._check(_get_lib().slk_sec_info(self._handle, ctypes.byref(info)), "sec_info")
        return info

    def pair(self, method=0):
        params = SlePairParams(method=method)
        self._check(_get_lib().slk_pair(self._handle, ctypes.byref(params)), "pair")

    def encrypt_on(self):
        self._check(_get_lib().slk_encrypt_on(self._handle), "encrypt_on")

    def ssap_info(self):
        info = SsapSummary()
        self._check(_get_lib().slk_ssap_info(self._handle, ctypes.byref(info)), "ssap_info")
        return info

    def ssap_read(self, handle):
        rw = SsapReadWrite()
        self._check(_get_lib().slk_ssap_read(self._handle, ctypes.c_uint16(handle), ctypes.byref(rw)), "ssap_read")
        return bytes(rw.data[: rw.length])

    def ssap_write(self, handle, data):
        rw = SsapReadWrite()
        rw.handle = handle
        rw.length = len(data)
        for i, b in enumerate(data[: min(len(data), 252)]):
            rw.data[i] = b
        self._check(_get_lib().slk_ssap_write(self._handle, ctypes.byref(rw)), "ssap_write")

    def poll_event(self):
        """Poll for a DLI event. Returns SleDliEvent or None."""
        ev = SleDliEvent()
        ret = _get_lib().slk_poll_event(self._handle, ctypes.byref(ev))
        if ret == 1:
            return ev
        if ret == 0:
            return None
        raise SparkLinkError("poll_event failed")

    def dli_info(self):
        info = SleDliInfo()
        self._check(_get_lib().slk_dli_info(self._handle, ctypes.byref(info)), "dli_info")
        return info

    def phy_info(self):
        info = SlePhyInfo()
        self._check(_get_lib().slk_phy_info(self._handle, ctypes.byref(info)), "phy_info")
        return info

    def set_role(self, role):
        self._check(_get_lib().slk_set_role(self._handle, ctypes.c_uint8(role)), "set_role")

    def get_role(self):
        return self._check(_get_lib().slk_get_role(self._handle), "get_role")
