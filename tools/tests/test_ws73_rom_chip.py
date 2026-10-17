# SPDX-License-Identifier: GPL-2.0-only
import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_rom_chip import COMMAND, candidate_variant, decode_candidate, rom_observations, runtime_observations, runtime_setup
from ws73_vm_register_reset import Bulk

class RomChipTests(unittest.TestCase):
    def test_all_low_bytes_match_fixed_firmware_logic_without_claiming_validity(self):
        for low in range(256):
            raw=bytes([low,0,0,16]);r=decode_candidate(raw);strap=low&12
            model=0 if strap in (0,12) else 1 if strap==4 else 2
            bus=1 if model==1 else 2 if model==2 and low&48==32 else 0
            self.assertEqual((r['model_id'],r['bus_id']),(model,bus))
            self.assertFalse(r['automatic_selection_permitted']);self.assertEqual(r['access_validity'],'UNPROVED')
            if bus:
                with self.assertRaises(ValueError):candidate_variant(raw)
            else:self.assertEqual(candidate_variant(raw),'e' if model==2 else 'us')
    def test_zero_all_one_short_long_and_wrong_types_never_default_to_u(self):
        for raw in [bytes(4),b'\xff'*4,b'',b'\x08',b'\x08'*3,b'\x08'*5,None,0,bytearray([8,0,0,0])]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):decode_candidate(raw)
    def test_exact_read_only_runtime_encoding_and_command_terminator(self):
        self.assertEqual(runtime_setup(),bytes.fromhex('00000000000000000090000008000040'))
        self.assertEqual(COMMAND,b'READM 0x40019000 4 ')
    def ioctl(self,raw,fail_out=False,fail_in=False):
        def call(fd,request,arg):
            self.assertEqual((fd,request),(71,0xc0185502));b=Bulk.from_buffer_copy(arg);self.assertEqual(b.timeout,2000)
            if b.endpoint==1:
                self.assertEqual(ctypes.string_at(b.data,b.length),COMMAND)
                if fail_out:raise OSError(110,'timeout')
                return b.length
            self.assertEqual((b.endpoint,b.length),(129,512))
            if fail_in:raise OSError(110,'timeout')
            ctypes.memmove(b.data,raw,len(raw));return len(raw)
        return call
    def test_three_real_replies_are_recorded_without_enabling_selection(self):
        rec={}
        with patch('ws73_rom_chip.fcntl.ioctl',side_effect=self.ioctl(bytes([8,0,0,16]))) as io:
            rows=rom_observations(71,rec,lambda:None,'E')
        self.assertEqual(io.call_count,6);self.assertEqual(len(rows),3)
        self.assertTrue(all(r['in_actual']==4 and r['out_actual']==len(COMMAND) and r['before_wall_ns']<=r['after_wall_ns'] and not r['candidate']['automatic_selection_permitted'] for r in rows))
    def test_invalid_reply_mismatch_and_transport_failure_stop_without_retry(self):
        for raw in [b'',b'123',b'12345',b'FAIL\n',bytes(4),b'\xff'*4,bytes([4,0,0,16]),bytes([40,0,0,16]),bytes([0,0,0,16])]:
            rec={}
            with self.subTest(raw=raw),patch('ws73_rom_chip.fcntl.ioctl',side_effect=self.ioctl(raw)) as io,self.assertRaises(ValueError):rom_observations(71,rec,lambda:None,'E')
            self.assertEqual(io.call_count,2);self.assertEqual(len(rec['rom_chip_reads']),1)
        for out,inc in [(True,False),(False,True)]:
            rec={}
            with patch('ws73_rom_chip.fcntl.ioctl',side_effect=self.ioctl(b'1234',out,inc)) as io,self.assertRaises(OSError):rom_observations(71,rec,lambda:None,'E')
            self.assertEqual(io.call_count,1 if out else 2)
    def test_short_command_is_not_retried_or_followed_by_input(self):
        with patch('ws73_rom_chip.fcntl.ioctl',return_value=1) as io,self.assertRaises(ValueError):rom_observations(71,{},lambda:None,'U')
        self.assertEqual(io.call_count,1)
    def test_unstable_rom_observations_fail(self):
        calls=0
        def io(fd,request,arg):
            nonlocal calls
            calls+=1;b=Bulk.from_buffer_copy(arg)
            if b.endpoint==1:return b.length
            ctypes.memmove(b.data,bytes([8,0,0,16+calls]),4);return 4
        with patch('ws73_rom_chip.fcntl.ioctl',side_effect=io),self.assertRaisesRegex(ValueError,'unstable'):rom_observations(71,{},lambda:None,'E')
    def test_runtime_uses_only_fixed_read_endpoint_pair(self):
        calls=[]
        def transfer(ep,data):
            calls.append((ep,data));return bytes([8,0,0,16]) if ep==130 else b''
        self.assertEqual(len(runtime_observations(transfer,'E')),3)
        self.assertEqual(calls,[(2,runtime_setup()),(130,4)]*3)
        with self.assertRaises(ValueError):runtime_observations(transfer,'U')
    def test_missing_mismatched_duplicate_or_mixed_mode_fails_before_device_open(self):
        from ws73_vm_register_reset import run
        base='ws73.register_reset_lab=1 ws73.rom_chip_probe=1 ws73.rom_chip_expected=E'
        for tokens,model,mixed in [(base,'U',False),(base+' ws73.rom_chip_expected=E','E',False),(base.replace('ws73.rom_chip_probe=1',''),'E',False),(base,'S',False),(base,'E',True)]:
            args=SimpleNamespace(rom_chip_expected=model,usb_credit_read_only=mixed)
            def read(path):return tokens if str(path)=='/proc/cmdline' else 'QEMU'
            with self.subTest(tokens=tokens,model=model,mixed=mixed),patch('ws73_vm_register_reset.os.geteuid',return_value=0),patch.object(Path,'read_text',read),patch.object(Path,'is_file',return_value=True),patch('ws73_vm_register_reset.os.open') as opened,self.assertRaises(ValueError):run(args)
            opened.assert_not_called()

if __name__=='__main__':unittest.main()
