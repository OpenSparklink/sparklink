# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import ctypes
import errno
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_vm_register_reset import Bulk, Control, Urb, setup_packet, checked_reset_value, route_packet, read_usb_configuration, checked_single_runtime_interface, clear_runtime_endpoints, async_register_read, read_credit_control, run

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
            clear_runtime_endpoints(77,record,lambda:None)
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
            clear_runtime_endpoints(77,record,lambda:None)
        self.assertEqual(calls.count(0x80045515),1)
        self.assertEqual(record['clear_halt_transfers'][0]['errno'],errno.EPIPE)
        self.assertNotIn('usb_configuration_after_clear_halt',record)

    def test_clear_halt_cannot_mutate_unqualified_configuration(self):
        calls=[]
        def ioctl(fd,request,arg):
            calls.append(request);raise OSError(errno.EPROTO,'bad configuration')
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=ioctl),self.assertRaises(ValueError):
            clear_runtime_endpoints(77,{},lambda:None)
        self.assertNotIn(0x80045515,calls)

    def test_register_clear_halt_uses_only_fixed_register_endpoints(self):
        endpoints=[];record={}
        def ioctl(fd,request,arg):
            if request==0x80045515:endpoints.append(int.from_bytes(arg,'little'));return 0
            return self.state_reader(fd,request,arg)
        with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=ioctl):
            clear_runtime_endpoints(77,record,lambda:None,register_read=True)
        self.assertEqual(endpoints,[2,130]);self.assertEqual(record['clear_halt_scope'],'register-read EP02/EP82')
        self.assertIs(record['physical_clear_halt_confirmed'],False)
        with self.assertRaises(ValueError):clear_runtime_endpoints(77,{},lambda:None,register_read=1)

    def test_register_clear_halt_refuses_mixed_or_missing_read_only_permission(self):
        for override in [dict(async_read_only=False),dict(runtime_route_before_module=True),dict(guest_usb_reset_before_read=True),dict(sdk_wakeup_before_read=True),dict(guest_clear_halt_before_route=True),dict(permission=False)]:
            args=SimpleNamespace(async_read_only=True,runtime_route_before_module=False,guest_set_interface_before_route=False,guest_usb_reset_before_read=False,sdk_wakeup_before_read=False,guest_clear_halt_before_route=False,guest_clear_halt_before_register_read=True)
            permission=override.get('permission',True)
            for k,v in override.items():setattr(args,k,v)
            def read(p):return ('ws73.register_reset_lab=1 ws73.register_async_read_lab=1 ws73.clear_halt_lab=1'+(' ws73.register_clear_halt_lab=1' if permission else '')) if str(p)=='/proc/cmdline' else 'QEMU'
            with self.subTest(override=override),patch('ws73_vm_register_reset.os.geteuid',return_value=0),patch.object(Path,'read_text',read),patch.object(Path,'is_file',return_value=True),patch('ws73_vm_register_reset.os.open') as opened:
                with self.assertRaises(ValueError):run(args)
                opened.assert_not_called()

    def async_ioctl(self,mode):
        submitted=[];cancelled=set()
        def ioctl(fd,request,arg):
            self.assertEqual(fd,77)
            if request==0x8038550a:
                urb=ctypes.cast(arg,ctypes.POINTER(Urb)).contents;pointer=ctypes.addressof(urb)
                self.assertEqual((urb.endpoint,urb.length),(2,16) if not submitted else (130,4))
                if urb.endpoint==2:self.assertEqual(ctypes.string_at(urb.buffer,urb.length),setup_packet(False))
                submitted.append(pointer);return 0
            if request==0x550b:
                cancelled.add(arg.value);return 0
            self.assertEqual(request,0x4008550d)
            available=[p for p in submitted if mode=='success' or p in cancelled]
            if mode=='close' and cancelled:ctypes.set_errno(errno.EIO);return -1
            if not available:ctypes.set_errno(errno.EAGAIN);return -1
            pointer=available[0];submitted.remove(pointer);urb=ctypes.cast(pointer,ctypes.POINTER(Urb)).contents
            urb.status=-errno.ENOENT if pointer in cancelled else 0;urb.actual=0 if pointer in cancelled else urb.length
            if urb.endpoint==130 and not urb.status:ctypes.memmove(urb.buffer,b'\x01\x02\x03\x04',4)
            ctypes.cast(arg,ctypes.POINTER(ctypes.c_void_p))[0]=pointer;return 0
        return Mock(ioctl=Mock(side_effect=ioctl))

    def test_actual_async_pointer_buffers_success_and_raw_diagnostics(self):
        d={}
        with patch('ws73_vm_register_reset.ctypes.CDLL',return_value=self.async_ioctl('success')):
            value,completed=async_register_read(77,d)
        self.assertEqual(value,b'\x01\x02\x03\x04');self.assertEqual([r['endpoint'] for r in completed],[2,130])
        self.assertEqual(len(d['submitted']),2);self.assertEqual(d['completed'],completed)
        self.assertEqual(d['cancel_requested'],[]);self.assertIs(d['fd_closed_to_join'],False)

    def test_async_timeout_preserves_primary_error_and_joins_both_cancel_replies(self):
        d={};clock=iter(n/10 for n in range(1000))
        with patch('ws73_vm_register_reset.ctypes.CDLL',return_value=self.async_ioctl('timeout')),patch('ws73_vm_register_reset.time.monotonic',side_effect=lambda:next(clock)),patch('ws73_vm_register_reset.time.sleep'),patch('ws73_vm_register_reset.os.close') as close:
            with self.assertRaises(TimeoutError):async_register_read(77,d)
        self.assertEqual(d['original_error']['type'],'TimeoutError');self.assertEqual(d['completed'],[])
        self.assertEqual([r['endpoint'] for r in d['cancel_requested']],[2,130])
        self.assertEqual([(r['status'],r['actual']) for r in d['cancel_reaped']],[(-errno.ENOENT,0),(-errno.ENOENT,0)])
        close.assert_not_called()

    def test_async_reap_failure_closes_owned_fd_and_keeps_original_timeout(self):
        from ws73_vm_register_reset import AsyncFdClosed
        d={};clock=iter(n/10 for n in range(1000))
        with patch('ws73_vm_register_reset.ctypes.CDLL',return_value=self.async_ioctl('close')),patch('ws73_vm_register_reset.time.monotonic',side_effect=lambda:next(clock)),patch('ws73_vm_register_reset.time.sleep'),patch('ws73_vm_register_reset.os.close') as close:
            with self.assertRaises(AsyncFdClosed):async_register_read(77,d)
        self.assertEqual(d['original_error']['type'],'TimeoutError');self.assertEqual(d['cancel_reap_errno'],errno.EIO)
        self.assertIs(d['fd_closed_to_join'],True);close.assert_called_once_with(77)

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

    def test_credit_read_uses_exact_sdk_class_input_and_preserves_zero_or_u32(self):
        for value in [0,1,0xffffffff]:
            record={};saves=[]
            def ioctl(fd,request,arg):
                self.assertEqual((fd,request),(77,0xc0185500))
                c=Control.from_buffer_copy(arg)
                self.assertEqual((c.kind,c.request,c.value,c.index,c.length,c.timeout),(0xa1,5,0,0,4,2000))
                self.assertIn('credit_control',record)
                ctypes.memmove(c.data,value.to_bytes(4,'little'),4);return 4
            with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=ioctl) as call:
                read_credit_control(77,record,lambda:saves.append(True))
            row=record['credit_control'];self.assertEqual(row['raw_credit_u32'],value)
            self.assertEqual(row['data'],value.to_bytes(4,'little').hex())
            self.assertEqual(call.call_count,1);self.assertEqual(len(saves),2)
            self.assertNotIn('status',record);self.assertNotIn('ready',record)

    def test_credit_short_boolean_and_errno_never_become_ready_or_raw_credit(self):
        for result in [0,1,3,5,True,OSError(errno.EPIPE,'raw physical refusal'),OSError(errno.ETIMEDOUT,'raw timeout')]:
            record={}
            with patch('ws73_vm_register_reset.fcntl.ioctl',side_effect=result if isinstance(result,Exception) else None,return_value=result) as call:
                with self.assertRaises((OSError,ValueError)):read_credit_control(77,record,lambda:None)
            row=record['credit_control'];self.assertIn('error',row);self.assertNotIn('raw_credit_u32',row)
            self.assertEqual(call.call_count,1)
            if isinstance(result,OSError):self.assertEqual(row['errno'],result.errno)
            self.assertLessEqual(row['before_wall_ns'],row['after_wall_ns'])

    def test_credit_requires_exact_explicit_boot_and_excludes_all_mutating_modes(self):
        for change in ['missing','duplicate','wrong','bool-string','reset','wake','route','async','rebind','clear','register-clear']:
            args=SimpleNamespace(usb_credit_read_only=True)
            tokens='ws73.register_reset_lab=1 ws73.usb_credit_lab=1'
            if change=='missing':tokens='ws73.register_reset_lab=1'
            if change=='duplicate':tokens+=' ws73.usb_credit_lab=1'
            if change=='wrong':tokens=tokens.replace('usb_credit_lab=1','usb_credit_lab=2')
            if change=='bool-string':args.usb_credit_read_only='1'
            fields={'reset':'guest_usb_reset_before_read','wake':'sdk_wakeup_before_read','route':'runtime_route_before_module','async':'async_read_only','rebind':'guest_set_interface_before_route','clear':'guest_clear_halt_before_route','register-clear':'guest_clear_halt_before_register_read'}
            if change in fields:setattr(args,fields[change],True)
            def read(p):return tokens if str(p)=='/proc/cmdline' else 'QEMU'
            with self.subTest(change=change),patch('ws73_vm_register_reset.os.geteuid',return_value=0),patch.object(Path,'read_text',read),patch.object(Path,'is_file',return_value=True),patch('ws73_vm_register_reset.os.open') as opened:
                with self.assertRaises(ValueError):run(args)
                opened.assert_not_called()
