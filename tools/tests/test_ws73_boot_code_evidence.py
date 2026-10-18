# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic negative evidence-parser checks; never hardware qualification."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_boot_code_evidence import corroborate


class BootCodeEvidence(unittest.TestCase):
    def fixture(self, bad=None):
        header = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 220)
        rows = []; tick = 0
        for index in range(2):
            address = 0x154700+4*index
            if bad == 'address' and index == 1: address += 4
            command = f'READM 0x{address:08x} 4 '.encode()
            value = bytes([index+1])*4
            for kind, ep, raw, length, flag in [
                ('S',1,command,len(command),0), ('C',1,b'',len(command),62),
                ('S',129,b'',4,60), ('C',129,value,4,0)]:
                tick += 1; device = 3
                if bad == 'device' and ep == 129: device = 4
                if bad == 'short' and kind == 'C' and ep == 129: raw=raw[:3];length=3
                status = -1 if bad == 'error' and ep == 129 and kind == 'C' else 0
                packet = struct.pack('<QBBBBHBBqiiII', 1,ord(kind),3,ep,device,1,0,flag,10,tick,status,length,len(raw))+bytes(24)+raw
                rows.append(struct.pack('<IIII',10,tick,len(packet),len(packet))+packet)
        if bad == 'missing': rows.pop()
        if bad == 'duplicate': rows += rows[:4]
        if bad == 'order': rows = rows[4:]+rows[:4]
        return header+b''.join(rows)

    def run_case(self, temp, bad=None, dump=None, windows=None):
        root = Path(temp); capture=root/'c.pcap'; data=root/'dump.bin'
        capture.write_bytes(self.fixture(bad)); data.write_bytes(dump if dump is not None else b'\1'*4+b'\2'*4)
        return corroborate(capture,data,windows if windows is not None else [(0x154700,8)])

    def test_exact_read_requests_responses_and_dump(self):
        with tempfile.TemporaryDirectory() as temp:
            r=self.run_case(temp)
            self.assertEqual(r['status'],'ACTUAL_BOOT_READM_CODE_BYTES_MATCH')
            self.assertEqual(r['bytes'],8)
            self.assertEqual([v['receive_completion'] for v in r['words']],[4,8])

    def test_failed_short_wrong_device_missing_or_reordered_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            for bad in ['address','device','short','error','missing','duplicate','order']:
                with self.subTest(bad=bad),self.assertRaises(CaptureError): self.run_case(temp,bad)

    def test_dump_must_equal_actual_usb(self):
        with tempfile.TemporaryDirectory() as temp:
            for dump in [b'',b'\0'*8,b'\1'*4]:
                with self.subTest(dump=dump),self.assertRaises(CaptureError): self.run_case(temp,dump=dump)

    def test_only_bounded_aligned_nonoverlapping_code_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            for windows in [[],[(0x40018000,8)],[(0x154701,8)],[(0x154700,8192)],[(0x154700,4),(0x154700,4)],[(0x154700,0)]]:
                with self.subTest(windows=windows),self.assertRaises(CaptureError): self.run_case(temp,windows=windows)
