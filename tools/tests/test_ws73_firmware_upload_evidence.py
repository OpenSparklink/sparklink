# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic parser regressions; never firmware execution or device acceptance."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import struct
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_firmware_upload_evidence import corroborate, IMAGES, successful_out

class UploadEvidence(unittest.TestCase):
    def fixture(self, root):
        rows=[];record=1
        for base,name in IMAGES:
            payload=bytes(range(256))*(130 if name=='ws73.bin' else 2)
            (root/name).write_bytes(hashlib.sha256(payload).hexdigest().encode()+payload)
            for offset in range(0,len(payload),32768):
                part=payload[offset:offset+32768]
                state=3 if len(payload)<=32768 else 0 if offset==0 else 2 if offset+len(part)==len(payload) else 1
                common=dict(bus=1,device=3)
                rows.append(common|dict(record=record,raw=f'FILES 1 0x{base+offset:x} 0x{len(part):x} 0x{state:x} '.encode(),completion_record=record+1))
                rows.append(common|dict(record=record+4,raw=part,completion_record=record+5));record+=8
        return rows

    def test_exact_multichunk_usb_bytes_and_source_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rows=self.fixture(root);p=corroborate(rows,root)
            self.assertEqual(p['status'],'ACTUAL_RAM_UPLOAD_BYTES_MATCH')
            self.assertEqual([len(i['chunks']) for i in p['images']],[2,1,1])

    def test_warm_staged_files_are_not_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root)
            with self.assertRaises(CaptureError):corroborate([],root)

    def test_missing_wrong_bytes_offset_device_and_state_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rows=self.fixture(root)
            for kind in ['missing','bytes','offset','device','state','ambiguous']:
                bad=copy.deepcopy(rows)
                if kind=='missing':bad.pop(1)
                if kind=='bytes':bad[1]['raw']=bytes([1])+bad[1]['raw'][1:]
                if kind=='offset':bad[0]['raw']=bad[0]['raw'].replace(b'400000',b'400004')
                if kind=='device':bad[1]['device']=4
                if kind=='state':bad[0]['raw']=bad[0]['raw'].replace(b'0x0 ',b'0x3 ')
                if kind=='ambiguous':bad.extend(copy.deepcopy(rows))
                with self.subTest(kind=kind),self.assertRaises(CaptureError):corroborate(bad,root)

    def test_invalid_image_header_does_not_gain_wire_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rows=self.fixture(root);p=root/'ws73.bin';b=p.read_bytes();p.write_bytes(b'0'*64+b[64:])
            with self.assertRaises(CaptureError):corroborate(rows,root)


class RawUsbRecords(unittest.TestCase):
    def capture(self, *, bad=None):
        raw=b'FILES 1 0x400000 0x1 0x3 '
        header=struct.pack('<IHHIIII',0xa1b2c3d4,2,3 if bad=='version' else 4,0,0,65535,220)
        packets=[]
        for kind in [ord('S'),ord('C')]:
            body=raw if kind==ord('S') else b''
            status=-1 if bad=='status' and kind==ord('C') else 0
            packet=struct.pack('<QBBBBHBBqiiII',1,kind,3,1,2,1,0,0,10,1234,status,len(raw),len(body))+bytes(24)+body
            if bad=='short' and kind==ord('S'):packet=packet[:-1]
            packets.append(struct.pack('<IIII',10,1234,len(packet),len(packet))+packet)
        return header+b''.join(packets[:1] if bad=='missing' else packets)

    def test_successful_submission_is_paired_and_timed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'capture.pcap';p.write_bytes(self.capture());rows=successful_out(p)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['wall_ns'],10001234000)
            self.assertEqual(rows[0]['completion_record'],2)

    def test_failed_missing_short_or_unknown_version_is_not_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ['status','missing','short','version']:
                p=Path(temp)/'capture.pcap';p.write_bytes(self.capture(bad=kind))
                with self.subTest(kind=kind),self.assertRaises(CaptureError):successful_out(p)
