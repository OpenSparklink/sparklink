"""Tests for sparklink Python bindings — struct ABI compatibility.

Sizes must match Rust repr(C) structs verified in slk-protocol tests.
"""

import ctypes
import unittest

from sparklink.structs import (
    SciDevInfo,
    SleAddr,
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


class TestStructSizes(unittest.TestCase):
    """Verify ctypes struct sizes match Rust repr(C) layout."""

    def test_sle_addr(self):
        self.assertEqual(ctypes.sizeof(SleAddr), 6)

    def test_sle_scan_params(self):
        self.assertEqual(ctypes.sizeof(SleScanParams), 16)

    def test_sle_connect_params(self):
        self.assertEqual(ctypes.sizeof(SleConnectParams), 16)

    def test_sle_conn_info(self):
        self.assertEqual(ctypes.sizeof(SleConnInfo), 64)

    def test_sle_sec_info(self):
        self.assertEqual(ctypes.sizeof(SleSecInfo), 16)

    def test_sle_pair_params(self):
        self.assertEqual(ctypes.sizeof(SlePairParams), 4)

    def test_ssap_summary(self):
        self.assertEqual(ctypes.sizeof(SsapSummary), 16)

    def test_ssap_read_write(self):
        self.assertEqual(ctypes.sizeof(SsapReadWrite), 256)

    def test_sle_dli_event(self):
        self.assertEqual(ctypes.sizeof(SleDliEvent), 256)

    def test_sci_dev_info(self):
        self.assertEqual(ctypes.sizeof(SciDevInfo), 66)

    def test_sle_dli_info(self):
        self.assertEqual(ctypes.sizeof(SleDliInfo), 64)

    def test_sle_phy_info(self):
        self.assertEqual(ctypes.sizeof(SlePhyInfo), 24)


class TestSleAddr(unittest.TestCase):
    def test_is_array_type(self):
        addr = SleAddr()
        self.assertEqual(len(addr), 6)
        for i in range(6):
            self.assertEqual(addr[i], 0)

    def test_assign(self):
        addr = SleAddr(0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF)
        self.assertEqual(addr[0], 0xAA)
        self.assertEqual(addr[5], 0xFF)


class TestSciDevInfo(unittest.TestCase):
    def test_device_name(self):
        info = SciDevInfo()
        test_name = b"TestNode"
        for i, b in enumerate(test_name):
            info.name[i] = b
        self.assertEqual(info.device_name, "TestNode")

    def test_device_name_empty(self):
        info = SciDevInfo()
        self.assertEqual(info.device_name, "")


class TestSsapReadWrite(unittest.TestCase):
    def test_data_capacity(self):
        rw = SsapReadWrite()
        self.assertEqual(len(rw.data), 252)

    def test_write_read(self):
        rw = SsapReadWrite()
        rw.handle = 0x42
        rw.length = 3
        rw.data[0] = 0xDE
        rw.data[1] = 0xAD
        rw.data[2] = 0xBE
        self.assertEqual(rw.handle, 0x42)
        self.assertEqual(rw.length, 3)
        self.assertEqual(bytes(rw.data[:3]), b"\xDE\xAD\xBE")


class TestSleConnInfo(unittest.TestCase):
    def test_field_access(self):
        info = SleConnInfo()
        info.tx_bytes = 1000
        info.handle = 0x42
        info.state = 2
        self.assertEqual(info.tx_bytes, 1000)
        self.assertEqual(info.handle, 0x42)
        self.assertEqual(info.state, 2)


if __name__ == "__main__":
    unittest.main()
