# SPDX-License-Identifier: GPL-2.0-only
"""Finite synthetic receipt/capture fixtures;not kernel or firmware proof."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_link_payload import MODE, acknowledgment, corroborate_entry, corroborate, exit_gate


def fixture(index=0):
    controller = index % 2 if index < 2 else 1-index % 2
    owner = dict(path=f'/org/sparklink/slk{controller}_g{11+controller}',bus=1,device=2+controller,
                 generation=11+controller,buffers=[1526,6,0,0])
    link = dict(generation=owner['generation'],lifetime=41+index//2*2,handle=0x1234,
                role=index%2,address_type=0,address='01:02:03:04:05:06',path=owner['path']+'/link')
    value = {k:v for k,v in link.items() if k != 'path'}
    value.update(request_id=index+1,deadline_monotonic_ns=5000,requested_octets=1526,
                 state=2,error=0,status=0,flags=5)
    clock=index*1000+100
    row=dict(args=['/bin/slctl','--adapter',owner['path'],'link-payload-preference',link['path'],'1526','5000'],
             start_wall_ns=clock,end_wall_ns=clock+50,exit=0,stderr='',
             stdout='NativeLinkPayloadAcknowledgment: '+json.dumps(value)+'\n')
    record=dict(version=1,mode=MODE,status='REAL_ACK_PENDING_RAW_AUDIT',command=row,acknowledgment=value)
    entry=dict(owner=owner,object=link,link_payload_preference=record)
    wire=dict(bus=1,device=owner['device'],opcode=0x1804)
    capture=dict(commands=[dict(wire,record=index*10+1,wall_ns=clock+10,params='3412f605',completion=dict(wall_ns=clock+11))],
                 complete=[dict(wire,record=index*10+2,wall_ns=clock+12,status=0,value='')])
    return entry,capture


def complete_run():
    run=dict(link_payload_preference_requested=MODE,link_payload_commands=[],link_payload_attempts=[],
             application_identity=dict(uids=[1000]*4,cap_eff='0',cap_prm='0',cap_amb='0'),
             connection_control=dict(phases=[dict(typed_objects=[]),dict(typed_objects=[])]))
    capture=dict(commands=[],complete=[])
    for index in range(4):
        entry,part=fixture(index)
        run['connection_control']['phases'][index//2]['typed_objects'].append(entry)
        run['link_payload_commands'].append(entry['link_payload_preference']['command'])
        run['link_payload_attempts'].append(dict(owner=entry['owner'],object=entry['object'],record=entry['link_payload_preference']))
        for key in capture:capture[key].extend(part[key])
    return run,capture


class PayloadPreferenceTests(unittest.TestCase):
    def test_original_receipt_and_actual_raw_command_shape_agree(self):
        entry,capture=fixture();p=corroborate_entry(entry,capture)
        self.assertEqual(p['real_DLI']['command']['params'],'3412f605')
        self.assertEqual(p['real_DLI']['reply']['value'],'')
        self.assertNotIn('effective_octets',p['scope'])

    def test_identity_argument_status_and_original_receipt_cannot_be_replaced(self):
        entry,_=fixture();source=entry['link_payload_preference']['command']
        for field,value in [('generation',12),('lifetime',42),('handle',7),('role',1),('address_type',1),
                            ('requested_octets',254),('request_id',0),('deadline_monotonic_ns',0),
                            ('flags',7),('flags',True),('state',1),('status',1),('error',-110),
                            ('effective_octets',1526)]:
            row=copy.deepcopy(source);receipt=dict(entry['link_payload_preference']['acknowledgment']);receipt[field]=value
            row['stdout']='NativeLinkPayloadAcknowledgment: '+json.dumps(receipt)+'\n'
            with self.subTest(field=field),self.assertRaises(ValueError):acknowledgment(row,entry)

    def test_missing_wrong_argument_wrong_controller_and_late_complete_refused(self):
        for case in range(6):
            entry,capture=fixture()
            if case==0:capture['complete']=[]
            elif case==1:capture['commands'][0]['params']='3412fe00'
            elif case==2:capture['complete'][0]['device']=7
            elif case==3:capture['complete'][0]['wall_ns']=1000
            elif case==4:capture['complete'][0]['value']='3412'
            else:capture['complete'][0]['status']=1
            with self.subTest(case=case),self.assertRaises(ValueError):corroborate_entry(entry,capture)

    def test_four_real_acknowledgment_scope_is_separate_from_effect_and_business(self):
        run,capture=complete_run();proof=corroborate(run,capture,MODE)
        parent=dict(link_payload_preference_requested=MODE,link_payload_preference_acceptance=True,
                    link_payload_preference_corroboration=proof)
        self.assertTrue(exit_gate(parent));self.assertEqual(len(proof['proofs']),4)
        self.assertNotIn('application_delivery',proof)
        for case in range(6):
            bad=copy.deepcopy(parent)
            if case==0:bad['link_payload_preference_corroboration']['proofs'].pop()
            elif case==1:bad['link_payload_preference_corroboration']['proofs']=[{}]*4
            elif case==2:bad['link_payload_preference_corroboration']['proofs'][0]['scope']['requested_octets']=254
            elif case==3:bad['link_payload_preference_corroboration']['proofs'][3]=copy.deepcopy(bad['link_payload_preference_corroboration']['proofs'][0])
            elif case==4:bad['link_payload_preference_acceptance']=False
            else:bad['link_payload_preference_corroboration']['proofs'][0]['real_DLI']['reply']['value']='3412'
            self.assertFalse(exit_gate(bad),case)

    def test_unrequested_and_partial_scopes_never_gain_acceptance(self):
        self.assertIsNone(corroborate({},dict(commands=[],complete=[]),None));self.assertTrue(exit_gate({}))
        run,capture=complete_run()
        with self.assertRaises(ValueError):corroborate(run,capture,None)
        run['connection_control']['phases'].pop()
        with self.assertRaises(ValueError):corroborate(run,capture,MODE)
        self.assertFalse(exit_gate(dict(link_payload_preference_requested=MODE)))
        self.assertFalse(exit_gate(dict(link_payload_preference_acceptance=True)))


if __name__=='__main__':unittest.main()
