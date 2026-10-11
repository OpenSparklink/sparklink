# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import ctypes
import errno
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_vm_register_reset import Bulk, Control, Urb, setup_packet, checked_reset_value, route_packet, read_usb_states, checked_interface_zero, run

class RegisterResetTests(unittest.TestCase):
    def state_reader(self,fd,request,argument):
        self.assertEqual(fd,77);self.assertEqual(request,0xc0185500)
        c=Control.from_buffer_copy(argument);self.assertEqual(c.value,0)
        self.assertEqual(c.timeout,2000)
        raw=b'\x01' if c.request==8 else bytes(c.length)
        ctypes.memmove(c.data,raw,len(raw));return len(raw)

    def test_fixed_readonly_configuration_interface_endpoint_state(self):
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=self.state_reader) as ioctl:
            rows=read_usb_states(77);checked_interface_zero(rows)
        self.assertEqual([(r['kind'],r['request'],r['index'],r['length']) for r in rows],
            [(0x80,8,0,1),(0x81,10,0,1),*[(0x82,0,ep,2) for ep in [1,2,129,130,131]]])
        self.assertEqual(ioctl.call_count,7)
        self.assertTrue(all(r['before_wall_ns']<=r['after_wall_ns'] for r in rows))

    def test_unknown_interface_or_configuration_cannot_rebind(self):
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=self.state_reader):rows=read_usb_states(77)
        for field,value in [('data','00'),('returned',0),('error','timeout')]:
            changed=[dict(r) for r in rows];changed[0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):checked_interface_zero(changed)
        with self.assertRaises(ValueError):checked_interface_zero(rows[:2])

    def test_usb_state_error_remains_raw_and_is_not_success(self):
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=OSError(errno.EPIPE,'halted')):
            rows=read_usb_states(77)
        self.assertEqual(len(rows),7);self.assertTrue(all(r['errno']==errno.EPIPE and 'data' not in r for r in rows))
        with self.assertRaises(ValueError):checked_interface_zero(rows)

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
