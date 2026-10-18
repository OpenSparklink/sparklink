# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic negative evidence-parser checks, never physical qualification."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_credit_observation import observe_phase


def fixture():
    owners = [dict(owner=dict(index=i,generation=i+1,bus=1,device=i+2,buffers=[254,5,0,0]),
                   object=dict(lifetime=3,handle=0)) for i in range(2)]
    apps=[]
    for i, role in enumerate(['initiator','peer']):
        text=''
        stages=[('ready',0,0,0,0,0),('blocked',11,5,5,8,1),('replied',16,0,5,0,3)] if i==0 else [('ready',0,0,0,0,0)]
        for stage,seq,debt,peak,queued,blocks in stages:
            text+=f'NativeTxStatus: stage={stage} sequence={seq} index={i} generation={i+1} lifetime=3 handle=0 maximum=254 capacity=5 outstanding={debt} debt={debt} peak={peak} queued={queued} limit=8 busy=0 bytes=0 offset=0 flags=0 blocks={blocks}\n'
        apps.append(dict(role=role,stdout=text))
    row=dict(phase=0,owners=owners,applications=apps,burst=True,tx_status_required=True,session_start_wall_ns=0,end_wall_ns=100)
    cap=dict(acb_packets=[],native_events=[])
    for device in [2,3]:
        for record in [1,2,3,4,5,7]:
            cap['acb_packets'].append(dict(bus=1,device=device,handle=0,wall_ns=record,record=record,direction='out',completion=dict(wall_ns=record+1)))
        for record,count in [(6,5),(8,1)]:
            cap['native_events'].append(dict(bus=1,device=device,wall_ns=record,record=record,event=9,params='0000'+f'{count:02x}'))
    return row,cap


class CreditObservation(unittest.TestCase):
    def test_full_then_actual_nocp_then_resume_and_drain(self):
        row,cap=fixture();proof=observe_phase(row,cap)
        self.assertEqual(proof['source_pool_refusals_delta'],3)
        for e in proof['endpoints']:
            self.assertEqual((e['wire_peak'],e['wire_final_debt'],e['usb_submissions'],e['nocp_packets']),(5,0,6,6))
            self.assertEqual(e['full_nocp_resume_intervals'],[dict(full_record=5,nocp_record=6,resumed_submit_record=7)])

    def test_missing_or_extra_completion_cannot_pass(self):
        row,cap=fixture()
        for kind in ['missing','extra','zero','foreign']:
            bad=copy.deepcopy(cap)
            if kind=='missing':bad['native_events'].pop(0)
            if kind=='extra':bad['native_events'][0]['params']='000006'
            if kind=='zero':bad['native_events'][0]['params']='000000'
            if kind=='foreign':bad['native_events'][0]['params']='010005'
            with self.subTest(kind=kind),self.assertRaises(CaptureError):observe_phase(row,bad)

    def test_usb_completion_does_not_refund_budget(self):
        row,cap=fixture();cap['native_events'][0]['wall_ns']=9
        with self.assertRaises(CaptureError):observe_phase(row,cap)

    def test_inherited_peak_without_new_refusal_is_insufficient(self):
        row,cap=fixture();row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('blocks=1','blocks=0').replace('blocks=3','blocks=0')
        with self.assertRaises(CaptureError):observe_phase(row,cap)

    def test_historical_record_and_wrong_identity_are_rejected(self):
        row,cap=fixture()
        for kind in ['historical','identity']:
            bad=copy.deepcopy(row)
            if kind=='historical':bad['tx_status_required']=False
            else:bad['applications'][0]['stdout']=bad['applications'][0]['stdout'].replace('lifetime=3','lifetime=4')
            with self.subTest(kind=kind),self.assertRaises(CaptureError):observe_phase(bad,cap)

    def test_foreign_handle_and_missing_successful_usb_are_rejected(self):
        row,cap=fixture()
        for kind in ['foreign','missing']:
            bad=copy.deepcopy(cap)
            if kind=='foreign':bad['acb_packets'][0]['handle']=1
            else:bad['acb_packets'][0]['completion']=None
            with self.subTest(kind=kind),self.assertRaises(CaptureError):observe_phase(row,bad)
