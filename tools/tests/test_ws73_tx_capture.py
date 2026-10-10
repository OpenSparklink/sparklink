# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic byte/interleaving fixtures only; never physical or RF evidence."""
import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import test_ws73_north_star as fixtures
from test_ws73_north_star import aggregate, command_payload, fixture, identity, pcap
from ws73_capture import CaptureError, command_reply, corroborate, hcc_command


class TransmitCaptureTests(unittest.TestCase):
    read = fixtures.CaptureTests.read

    def setUp(self):
        self.payload = command_payload(0x0406, b'\x00')
        self.pair = [(1,2,1000,self.payload,'S',1,-115),
                     (1,2,3000,self.payload,'C',1,0)]

    def test_successful_out_has_submission_and_completion_offsets(self):
        tx = self.read(pcap(self.pair))['commands'][0]
        self.assertEqual((tx['opcode'],tx['params'],tx['sequence']),(0x0406,'00',1))
        self.assertEqual((tx['record'],tx['completion']['record']),(1,2))
        self.assertLess(tx['file_offset'],tx['completion']['file_offset'])

    def test_in_reply_can_arrive_before_out_callback(self):
        reply=aggregate(b'\xa2\x02\x00\x0a\x00\x06\x04\x01\x00'+bytes.fromhex('027300000001'))
        records=[self.pair[0],(1,2,2000,reply,'C',0x81,0),self.pair[1]]
        step=command_reply(self.read(pcap(records)),identity(1),0x0406,0,4000,b'\x00','027300000001')
        self.assertLess(step['reply']['wall_ns'],step['command']['completion']['wall_ns'])

    def test_urb_reuse_after_completion_is_legal(self):
        records=self.pair+[(1,2,4000,self.payload,'S',1,-115),(1,2,5000,self.payload,'C',1,0)]
        self.assertEqual(len(self.read(pcap(records))['commands']),2)

    def test_no_padding_search_for_command(self):
        payload=bytearray(self.payload);payload[100:105]=b'\xa1\x03\x0c\x00\x00'
        self.assertEqual(hcc_command(payload)['opcode'],0x0406)
        payload[64]=0x50;payload[65]=10
        self.assertIsNone(hcc_command(payload))

    def test_bad_native_tx_schema_is_rejected(self):
        for offset,value in [(4,1),(64,0xa1),(66,1),(68,0xa2),(70,0),(71,255)]:
            # The opcode-zero case must clear both bytes.
            payload=bytearray(self.payload);payload[offset]=value
            if offset==70:payload[69]=0
            with self.subTest(offset=offset),self.assertRaises(CaptureError):hcc_command(payload)

    def test_missing_duplicate_and_unfinished_submission_rejected(self):
        for records in [[self.pair[1]], [self.pair[0],self.pair[0],self.pair[1]], [self.pair[0]]]:
            with self.subTest(records=len(records)),self.assertRaises(CaptureError):self.read(pcap(records))

    def test_completion_cannot_follow_different_usb_identity(self):
        records=[self.pair[0],(1,3,3000,self.payload,'C',1,0)]
        with self.assertRaisesRegex(CaptureError,'without captured submission'):self.read(pcap(records))

    def test_completion_cannot_follow_different_urb(self):
        blob=bytearray(pcap(self.pair));second=24+16+64+len(self.payload)
        struct.pack_into('<Q',blob,second+16,124)
        with self.assertRaisesRegex(CaptureError,'without captured submission'):self.read(blob)

    def test_failed_completion_and_submit_error_never_make_tx_proof(self):
        for kind in ['C','E']:
            records=[self.pair[0],(1,2,3000,self.payload,kind,1,-32)]
            result=self.read(pcap(records))
            self.assertFalse(result['commands'])
            self.assertEqual((result['failures'][0]['status'],result['failures'][0]['endpoint']),(-32,1))

    def test_short_completion_is_not_success(self):
        records=[self.pair[0],(1,2,3000,self.payload[:-1],'C',1,0)]
        with self.assertRaisesRegex(CaptureError,'short or data-bearing'):self.read(pcap(records))

    def test_submission_data_flag_and_truncation_rejected(self):
        for mode in ['flag','length']:
            blob=bytearray(pcap(self.pair))
            if mode=='flag':blob[24+16+15]=ord('>')
            else:struct.pack_into('<I',blob,24+16+32,len(self.payload)+1)
            with self.subTest(mode=mode),self.assertRaises(CaptureError):self.read(blob)

    def test_complete_only_ready_evidence_is_rejected(self):
        run,records=fixture();capture=self.read(pcap(records))
        capture['commands']=[c for c in capture['commands'] if c['opcode'] not in [0x0402,0x0403,0x0404,0x0406]]
        with self.assertRaisesRegex(CaptureError,'captured OUT'):corroborate(run,capture)

    def test_marker_changed_in_tx_is_rejected_despite_matching_rx(self):
        run,records=fixture();capture=self.read(pcap(records))
        command=next(c for c in capture['commands'] if c['opcode']==0x0c03)
        command['params']=command['params'][:-2]+'ff'
        with self.assertRaisesRegex(CaptureError,'parameters disagree'):corroborate(run,capture)

    def test_enable_and_address_read_parameters_are_checked(self):
        run,records=fixture();good=self.read(pcap(records))
        for opcode in [0x0c05,0x1002,0x0406]:
            capture=copy.deepcopy(good)
            command=next(c for c in capture['commands'] if c['opcode']==opcode)
            command['params']='ff'+command['params'][2:]
            with self.subTest(opcode=opcode),self.assertRaisesRegex(CaptureError,'parameters disagree'):
                corroborate(run,capture)

    def test_reply_before_tx_and_duplicate_tx_rejected(self):
        run,records=fixture();good=self.read(pcap(records))
        for mode in ['early-reply','duplicate-tx']:
            capture=copy.deepcopy(good)
            command=next(c for c in capture['commands'] if c['opcode']==0x0c03)
            if mode=='duplicate-tx':capture['commands'].append(copy.deepcopy(command))
            else:
                reply=next(c for c in capture['complete'] if c['opcode']==0x0c03)
                reply['wall_ns']=command['wall_ns']-1000
            with self.subTest(mode=mode),self.assertRaises(CaptureError):corroborate(run,capture)

    def test_selected_power_and_recipe_order_are_checked(self):
        run,records=fixture();good=self.read(pcap(records))
        for mode in ['power','order']:
            capture=copy.deepcopy(good)
            if mode=='power':next(c for c in capture['complete'] if c['opcode']==0x0c02)['value']='f9'
            else:
                command=next(c for c in capture['commands'] if c['opcode']==0x0c03)
                command['wall_ns']-=20_000
            with self.subTest(mode=mode),self.assertRaises(CaptureError):corroborate(run,capture)

    def test_survivor_stdout_without_raw_control_is_not_proof(self):
        run,records=fixture();capture=self.read(pcap(records))
        scan=run['survivor_control']['scan_request']
        capture['commands']=[c for c in capture['commands']
                             if not scan['start_wall_ns']<=c['wall_ns']<=scan['end_wall_ns']]
        with self.assertRaisesRegex(CaptureError,'captured OUT'):corroborate(run,capture)


if __name__=='__main__':
    unittest.main()
