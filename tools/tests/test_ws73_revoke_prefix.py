# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic evidence negatives; not hardware or actual callback qualification."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_revoke_prefix import corroborate


def fixture():
    data=b'SLKREV01'+bytes(range(254))*8+bytes(2)
    assert len(data)==2042
    raw=b'\x1f\0\xfb\x07\xf1'+data
    row=dict(index=0,end_wall_ns=10000,owners=[dict(handle=0),dict(handle=0)],armed=dict(prefix=data.hex()),revoke_prefix=dict(payload=data.hex(),admission_before_wall_ns=100,admission_after_wall_ns=200))
    outer=dict(usb=[dict(bus=1,device=2),dict(bus=1,device=3)],release_before_wall_ns=5000,release_after_wall_ns=6000,down=[dict(wall_ns=6500),dict(wall_ns=6600)])
    packets=[dict(bus=1,device=2,direction='out',handle=0,wall_ns=1000+i*500,record=i+1,boundary=1 if i==0 else 2,data=raw[i*254:(i+1)*254].hex(),completion=dict(record=10+i)) for i in range(2)]
    return row,outer,dict(acb_packets=packets,native_events=[])

class RevokePrefix(unittest.TestCase):
    def test_exact_begun_incomplete_prefix_then_withdrawal(self):
        row,outer,cap=fixture();p=corroborate(row,outer,cap)
        self.assertEqual(p['submitted_fragments'],2);self.assertEqual(p['source_application_round_trips'],0)

    def test_late_submit_completed_pdu_interleaving_and_wrong_bytes_fail(self):
        row,outer,cap=fixture()
        for kind in ['late','last','interleave','bytes','foreign','missing']:
            bad=copy.deepcopy(cap)
            if kind=='late':bad['acb_packets'][1]['wall_ns']=6000
            if kind=='last':bad['acb_packets'][1]['boundary']=3
            if kind=='interleave':bad['acb_packets'][1]['boundary']=0
            if kind=='bytes':bad['acb_packets'][1]['data']='00'*254
            if kind=='foreign':bad['acb_packets'][0]['handle']=1
            if kind=='missing':bad['acb_packets'][0]['completion']=None
            with self.subTest(kind=kind),self.assertRaises(CaptureError):corroborate(row,outer,bad)

    def test_send_not_begun_before_release_and_wrong_down_fail(self):
        row,outer,cap=fixture()
        for kind in ['notbegun','down']:
            bad=copy.deepcopy(outer)
            if kind=='notbegun':bad['release_before_wall_ns']=900
            else:bad['down'][0]['wall_ns']=4999
            with self.subTest(kind=kind),self.assertRaises(CaptureError):corroborate(row,bad,cap)
