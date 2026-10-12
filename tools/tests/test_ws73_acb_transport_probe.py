# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic parser/refusal vectors; not hardware or socket proof."""
import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError, acb, hcc_acb, hcc_command
from ws73_acb_transport_probe import references, corroborate
import test_ws73_north_star as fixtures
from test_ws73_north_star import aggregate, command_payload, pcap


class AcbProbeTests(unittest.TestCase):
    read = fixtures.CaptureTests.read

    def wire(self):
        data = bytearray(command_payload(0xabc, b'abc'))
        data[68] = 0xa3
        return data

    def test_nonzero_handle_and_data_do_not_become_command_receipt(self):
        wire = self.wire()
        self.assertIsNone(hcc_command(wire))
        self.assertEqual(hcc_acb(wire), dict(handle=0xabc, data='616263'))
        capture = self.read(pcap([(1,2,1000,wire,'S',1,-115),
                                  (1,2,2000,aggregate(wire[68:76]),'C',0x81,0),
                                  (1,2,3000,wire,'C',1,0)]))
        self.assertEqual([p['direction'] for p in capture['acb_packets']], ['in', 'out'])
        self.assertFalse(capture['commands'])

    def test_exact_lengths_flags_padding_and_no_successful_write_proof(self):
        for offset in [4, 66, 71, 100]:
            wire = self.wire(); wire[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(CaptureError):
                hcc_acb(wire)
        wire = self.wire(); wire[70] |= 0x10
        with self.assertRaises(CaptureError): hcc_acb(wire)
        self.assertIsNone(acb(b'\xa2\x09\x00'))
        with self.assertRaises(CaptureError): acb(b'\xa3\x00')
        wire = self.wire()
        capture = self.read(pcap([(1,2,1000,wire,'S',1,-115),(1,2,3000,wire,'E',1,-5)]))
        self.assertFalse(capture['acb_packets'])
        with self.assertRaises(CaptureError): self.read(pcap([(1,2,1000,wire,'S',1,-115)]))

    def entries(self):
        return [dict(owner=dict(index=i,generation=7+i),
                     object=dict(generation=7+i,lifetime=1,handle=0)) for i in range(2)]

    def test_cross_controller_and_lifetime_parameters_are_explicit(self):
        self.assertEqual(references(self.entries()), [[0,7,1,0],[1,8,1,0]])
        for field, value in [('index',True),('generation',0)]:
            entries = self.entries(); entries[0]['owner'][field] = value
            with self.assertRaises(ValueError): references(entries)
        for field, value in [('lifetime',0),('handle',0x1000),('generation',8)]:
            entries = self.entries(); entries[0]['object'][field] = value
            with self.assertRaises(ValueError): references(entries)
        entries = self.entries(); entries[1]['owner']['index'] = 0
        with self.assertRaises(ValueError): references(entries)

    def test_logs_or_no_module_probe_cannot_prove_transport(self):
        with self.assertRaises(ValueError): corroborate({}, {}, '')
        rows = [dict(phase=i,status='REAL_ACB_TRANSPORT_MODULE_EVIDENCE_PENDING') for i in range(2)]
        with self.assertRaises(ValueError): corroborate(dict(acb_transport_probe=rows), {}, '')

    def proof_fixture(self):
        run = dict(acb_transport_probe=[])
        capture = dict(acb_packets=[], native_events=[])
        log = ''
        for phase in range(2):
            owners = self.entries()
            for i, entry in enumerate(owners): entry['owner'].update(bus=1,device=i+2)
            start, end = phase*1000, (phase+1)*1000
            supervisor = dict(status='REAL_ACB_TRANSPORT_MODULE_EVIDENCE_PENDING', result=dict(exit=0),
                              unload=dict(exit=0), taint=4096,start_wall_ns=start,end_wall_ns=end)
            run['acb_transport_probe'].append(dict(phase=phase,status=supervisor['status'],owners=owners,supervisor=supervisor))
            for index in range(4):
                frame=bytearray(62);frame[:5]=b'\x1f\x00\x3a\x00\xfb';frame[5:13]=b'SLKACB1!'
                frame[13:29]=bytes([phase*4+index+1])*16;frame[29:33]=index.to_bytes(4,'little');frame[33]=index%2
                log+=f'WS73_ACB_PROBE_FRAME: round={index} source={index%2} bytes={frame.hex()}\n'
                source=index%2;peer=source^1;reply=bytearray(frame);reply[33]|=0x80
                for sender,receiver,data in [(source,peer,frame),(peer,source,reply)]:
                    capture['acb_packets'] += [dict(bus=1,device=sender+2,direction='out',handle=0,data=data.hex(),wall_ns=start+index*10+1,completion=dict(wall_ns=start+index*10+3)),
                                               dict(bus=1,device=receiver+2,direction='in',handle=0,data=data.hex(),wall_ns=start+index*10+2)]
                    capture['native_events'].append(dict(event=9,bus=1,device=sender+2,params='000001',wall_ns=start+index*10+4))
            log+='WS73_ACB_PROBE_PASS: rounds=4 ordinary_socket=0 negotiation=0\n'
        return run,capture,log

    def test_exact_two_endpoint_bytes_and_nocp_are_required(self):
        run,capture,log=self.proof_fixture()
        proof=corroborate(run,capture,log)
        self.assertEqual(proof['rounds'],8)
        self.assertFalse(proof['ordinary_socket_acceptance'])
        for kind in ['opposite_rx','nocp','extra_count','foreign_handle','wrong_taint']:
            r,c=copy.deepcopy(run),copy.deepcopy(capture)
            if kind=='opposite_rx': c['acb_packets']=[p for p in c['acb_packets'] if p['direction']=='out']
            if kind=='nocp': c['native_events']=[]
            if kind=='extra_count': c['native_events'][0]['params']='000002'
            if kind=='foreign_handle': c['acb_packets'][0]['handle']=1
            if kind=='wrong_taint': r['acb_transport_probe'][0]['supervisor']['taint']=0
            with self.subTest(kind=kind),self.assertRaises(ValueError): corroborate(r,c,log)


if __name__ == '__main__':
    unittest.main()
