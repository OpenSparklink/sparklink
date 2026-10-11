# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import ctypes
import errno
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_vm_register_reset import Bulk, Control, Urb, setup_packet, checked_reset_value, route_packet, read_usb_configuration, checked_single_runtime_interface, clear_runtime_route_endpoints, run

class RegisterResetTests(unittest.TestCase):
    descriptor=bytes.fromhex('09023500010100c0010904000005e00202010705810200020007050102000200070583030800010705020200020007058202000200')

    def state_reader(self,fd,request,argument):
        self.assertEqual(fd,77);self.assertEqual(request,0xc0185500)
        c=Control.from_buffer_copy(argument);self.assertEqual(c.kind,0x80)
        self.assertEqual(c.index,0);self.assertEqual(c.timeout,2000)
        raw=b'\x01' if c.request==8 else self.descriptor
        self.assertEqual((c.request,c.value,c.length),(8,0,1) if c.request==8 else (6,512,53))
        ctypes.memmove(c.data,raw,len(raw));return len(raw)

    def test_actual_single_alt_descriptor_without_fake_get_interface(self):
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=self.state_reader) as ioctl:
            rows=read_usb_configuration(77);self.assertEqual(checked_single_runtime_interface(rows),self.descriptor)
        self.assertEqual(ioctl.call_count,2)
        self.assertTrue(all(r['before_wall_ns']<=r['after_wall_ns'] for r in rows))

    def test_clear_halt_is_qualified_bounded_and_never_physical_success(self):
        calls=[];record={}
        def ioctl(fd,request,arg):
            calls.append(request)
            if request==0x80045515:
                self.assertEqual(int.from_bytes(arg,'little'),1 if calls.count(request)==1 else 129)
                return 0
            return self.state_reader(fd,request,arg)
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=ioctl):
            clear_runtime_route_endpoints(77,record,lambda:None)
        self.assertEqual(calls,[0xc0185500,0xc0185500,0x80045515,0x80045515,0xc0185500,0xc0185500])
        self.assertIs(record['physical_clear_halt_confirmed'],False)
        self.assertEqual([r['returned'] for r in record['clear_halt_transfers']],[0,0])

    def test_clear_halt_preserves_error_and_stops_before_next_endpoint(self):
        record={};calls=[]
        def ioctl(fd,request,arg):
            calls.append(request)
            if request==0x80045515:raise OSError(errno.EPIPE,'physical outcome not normalized')
            return self.state_reader(fd,request,arg)
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=ioctl),self.assertRaises(OSError):
            clear_runtime_route_endpoints(77,record,lambda:None)
        self.assertEqual(calls.count(0x80045515),1)
        self.assertEqual(record['clear_halt_transfers'][0]['errno'],errno.EPIPE)
        self.assertNotIn('usb_configuration_after_clear_halt',record)

    def test_clear_halt_cannot_mutate_unqualified_configuration(self):
        calls=[]
        def ioctl(fd,request,arg):
            calls.append(request);raise OSError(errno.EPROTO,'bad configuration')
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=ioctl),self.assertRaises(ValueError):
            clear_runtime_route_endpoints(77,{},lambda:None)
        self.assertNotIn(0x80045515,calls)

    def test_clear_halt_explicit_mode_rejects_missing_route_permission_or_rebind(self):
        for route,rebind,permission in [(False,False,True),(True,False,False),(True,True,True)]:
            def read(p):
                return ('ws73.register_reset_lab=1 ws73.runtime_route_lab=1 ws73.interface_rebind_lab=1'+(' ws73.clear_halt_lab=1' if permission else '')) if str(p)=='/proc/cmdline' else 'QEMU'
            args=SimpleNamespace(guest_clear_halt_before_route=True,runtime_route_before_module=route,guest_set_interface_before_route=rebind)
            with self.subTest(route=route,rebind=rebind,permission=permission),patch('ws73_vm_register_reset.os.geteuid',return_value=0),patch.object(Path,'read_text',read),patch.object(Path,'is_file',return_value=True),patch('ws73_vm_register_reset.os.open') as opened:
                with self.assertRaises(ValueError):run(args)
                opened.assert_not_called()

    def test_unknown_configuration_alternate_or_endpoints_cannot_rebind(self):
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=self.state_reader):rows=read_usb_configuration(77)
        for change in ['short','error','boolean','configuration','extra-interface','alt','duplicate-ep','packet-size']:
            changed=[dict(r) for r in rows];raw=bytearray(self.descriptor)
            if change=='short':changed[1]['returned']=52
            if change=='error':changed[1]['error']='timeout'
            if change=='boolean':changed[0]['returned']=True
            if change=='configuration':changed[0]['data']='00'
            if change=='extra-interface':raw[4]=2
            if change=='alt':raw[12]=1
            if change=='duplicate-ep':raw[48]=1
            if change=='packet-size':raw[22]=8
            changed[1]['data']=raw.hex()
            with self.subTest(change=change),self.assertRaises(ValueError):checked_single_runtime_interface(changed)
        with self.assertRaises(ValueError):checked_single_runtime_interface(rows[:1])

    def test_configuration_error_remains_raw_and_is_not_success(self):
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=OSError(errno.EPIPE,'halted')):
            rows=read_usb_configuration(77)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['errno']==errno.EPIPE and 'data' not in r for r in rows))
        with self.assertRaises(ValueError):checked_single_runtime_interface(rows)

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
