# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_vm_register_reset import Bulk, Control, Urb, setup_packet, checked_reset_value, route_packet, run

class RegisterResetTests(unittest.TestCase):
    def test_runtime_route_is_exact_bsle_control_without_register_write(self):
        self.assertEqual(route_packet(0,1,10).hex(),'030000000000000000000000010000000a00000000000000000000000000000000000000')
        self.assertEqual(route_packet(1,0,0).hex(),'030000000000000001000000000000000000000000000000000000000000000000000000')
        for args in [(True,1,10),(-1,1,10),(2**32,1,10),(0,1,9),(0,0,10)]:
            with self.subTest(args=args),self.assertRaises(ValueError):route_packet(*args)

    def test_protocol_setup_packets_and_usbfs_width(self):
        self.assertEqual(setup_packet(False).hex(),'000000000000000018f1000008000040')
        self.assertEqual(setup_packet(True).hex(),'000000000000000018f1000009000040')
        self.assertEqual(ctypes.sizeof(Bulk),24)
        self.assertEqual(ctypes.sizeof(Control),24)
        self.assertEqual(Bulk.data.offset,16)
        self.assertEqual(Control.data.offset,16)
        self.assertEqual(ctypes.sizeof(Urb),56)
        self.assertEqual(Urb.buffer.offset,16)
        self.assertEqual(Urb.context.offset,48)

    def test_read_failure_never_generates_reset_write(self):
        for raw in [None,b'',b'\x00'*3,b'\x00'*5,bytearray(4),b'\xff'*4,b'\x10\x00\x00\x00']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):checked_reset_value(raw)
        self.assertEqual(checked_reset_value(b'\x01\x02\x03\x04'),0x04030211)

    def test_outside_privileged_vm_cannot_open_usb_or_write_registers(self):
        with patch('ws73_vm_register_reset.os.geteuid',return_value=1000),patch('ws73_vm_register_reset.os.open') as opened:
            with self.assertRaises(ValueError):run(SimpleNamespace(output=Path('/invalid')))
            opened.assert_not_called()
