# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic record rejection tests, not crypto/RF qualification."""
import unittest
from test_ws73_security_capabilities import fixture as capability_fixture
from ws73_security_capabilities import Submit,Result,decode
from ws73_key_agreement import corroborate


def fixture():
    r,c=capability_fixture();r['key_agreement']=True;row=r['security_capabilities']
    for n in [0,1]:
        req=decode(Submit,row['requests'][n]);req.flags=2;row['requests'][n]=bytes(req).hex()
        result=decode(Result,row['results'][n]);result.state=8;row['results'][n]=bytes(result).hex()
    c['commands']=[v for v in c['commands'] if v['opcode']!=0x1812]
    c['complete']=[v for v in c['complete'] if v['opcode']!=0x1812]
    c['native_events']=[v for v in c['native_events'] if v['event']!=0x14]
    order=[0x134,0x135,0x136,0x137,0x138,0x139,0x13a,0x141,0x142]
    for position,index in enumerate(order):
        source=0 if index in [0x134,0x136,0x139,0x141] else 1;target=1-source;when=190+5*position
        payload=bytes([3,0,0,16,0,2,2,2,2,0]) if index in [0x134,0x135] else bytes([16,1,2,2,2,2])+bytes(range(1,65)) if index==0x136 else bytes(range(129,193)) if index==0x137 else bytes([position])*16
        body=b'\0\0'+index.to_bytes(2,'little')+bytes([len(payload)])+payload
        c['commands'].append(dict(**r['usb'][source],opcode=0x1812,params=body.hex(),wall_ns=when,record=300+position,completion={'record':400+position}))
        c['complete'].append(dict(**r['usb'][source],opcode=0x1812,status=0,value=body[:4].hex(),wall_ns=when+2,record=500+position))
        c['native_events'].append(dict(**r['usb'][target],event=0x14,params=body.hex(),wall_ns=when+1,record=600+position))
    return r,c


class KeyAgreementEvidence(unittest.TestCase):
    def test_nine_real_pdu_proof_scope_and_same_session_business(self):
        r,c=fixture();p=corroborate(r,c)
        self.assertEqual([len(v['relays']) for v in p['controllers']],[4,5]);self.assertEqual(p['business_round_trips'],4)

    def test_no_local_success_complete_or_caps_upgrade_to_candidate_proof(self):
        for kind in ['state4','flag1','missing_rx','wrong_proof','missing_complete','bad_complete','bad_echo','duplicate','early_confirm','encryption','business']:
            r,c=fixture();row=r['security_capabilities']
            if kind=='state4':v=decode(Result,row['results'][0]);v.state=4;row['results'][0]=bytes(v).hex()
            elif kind=='flag1':v=decode(Submit,row['requests'][0]);v.flags=1;row['requests'][0]=bytes(v).hex()
            elif kind=='missing_rx':c['native_events'].pop()
            elif kind=='wrong_proof':c['native_events'][-1]['params']=c['native_events'][-1]['params'][:-2]+'ff'
            elif kind=='missing_complete':c['complete'].pop()
            elif kind=='bad_complete':c['complete'][-1]['status']=1
            elif kind=='bad_echo':c['complete'][-1]['value']='00004101'
            elif kind=='duplicate':c['commands'].append(c['commands'][-1].copy())
            elif kind=='early_confirm':next(v for v in c['complete'] if v['opcode']==0x1812 and v['value']=='00003701')['wall_ns']=220
            elif kind=='encryption':c['native_events'].append(dict(**r['usb'][0],event=0x11,params='',wall_ns=240))
            else:c['acb_packets'].pop()
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c)
