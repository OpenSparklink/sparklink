# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic checker counterexamples; not actual crypto/USB/RF qualification."""
import json
import unittest
from test_ws73_key_agreement import fixture as candidate_fixture
from ws73_key_agreement import corroborate
from ws73_security_capabilities import Submit,Result,decode


def fixture():
    r,c=candidate_fixture();r['unauthenticated_encryption']=True;row=r['security_capabilities']
    for n in [0,1]:
        req=decode(Submit,row['requests'][n]);req.flags=3;row['requests'][n]=bytes(req).hex()
        res=decode(Result,row['results'][n]);res.state=9;row['results'][n]=bytes(res).hex()
        op=0x1c03 if n==0 else 0x1c05;when=235 if n==0 else 238
        params=b'\0\0'+bytes([0x5a])*16+(b'\x01\x01\0' if n==0 else b'\x01\x01')
        c['commands'].append(dict(**r['usb'][n],opcode=op,params=params.hex(),wall_ns=when,record=1000+n,completion={'record':1010+n}))
        c['native_events'].append(dict(**r['usb'][n],event=1,params=(op.to_bytes(2,'little')+b'\x01\0').hex(),wall_ns=when+1,record=1020+n))
        c['native_events'].append(dict(**r['usb'][n],event=0x11,params='00000001',wall_ns=240+n,record=1030+n))
    c['native_events'].append(dict(**r['usb'][1],event=0xe,params='0000',wall_ns=237,record=1040))
    return r,c


class EncryptionEvidence(unittest.TestCase):
    def test_distinct_install_accept_event_business_and_no_key_in_report(self):
        r,c=fixture();proof=corroborate(r,c)
        self.assertEqual(proof['status'],'REAL_UNAUTHENTICATED_LINK_ENCRYPTION_CORROBORATED')
        self.assertEqual([v['parameter_length'] for v in proof['installations']],[21,20])
        self.assertNotIn('5a'*16,json.dumps(proof));self.assertEqual(proof['business_round_trips'],4)

    def test_missing_wrong_late_or_local_success_cannot_upgrade_qualification(self):
        for kind in ['state8','mode2','missing','duplicate','role','length','algorithm','zero','different','accept','event','failed','early_event','request','early_request','early_g','early_t','business']:
            r,c=fixture();row=r['security_capabilities'];tx=[v for v in c['commands'] if v['opcode'] in [0x1c03,0x1c05]];events=[v for v in c['native_events'] if v['event']==0x11]
            if kind=='state8':v=decode(Result,row['results'][0]);v.state=8;row['results'][0]=bytes(v).hex()
            elif kind=='mode2':v=decode(Submit,row['requests'][0]);v.flags=2;row['requests'][0]=bytes(v).hex()
            elif kind=='missing':c['commands'].remove(tx[1])
            elif kind=='duplicate':c['commands'].append(tx[1].copy())
            elif kind=='role':tx[1]['opcode']=0x1c03
            elif kind in ['length','algorithm','zero','different']:
                raw=bytearray.fromhex(tx[1]['params'])
                if kind=='length':raw.pop()
                elif kind=='algorithm':raw[19]=2
                elif kind=='zero':raw[2:18]=bytes(16)
                else:raw[2]^=1
                tx[1]['params']=raw.hex()
            elif kind=='accept':c['native_events']=[v for v in c['native_events'] if v['record']!=1020]
            elif kind=='event':c['native_events'].remove(events[0])
            elif kind=='failed':events[0]['params']='01000001'
            elif kind=='early_event':events[0]['wall_ns']=231
            elif kind=='request':c['native_events']=[v for v in c['native_events'] if v['event']!=0xe]
            elif kind=='early_request':next(v for v in c['native_events'] if v['event']==0xe)['wall_ns']=234
            elif kind=='early_g':tx[0]['wall_ns']=229
            elif kind=='early_t':next(v for v in c['complete'] if v['opcode']==0x1812 and v['value']=='00004201')['wall_ns']=239
            else:next(v for v in r['channel_grant']['business'] if v['label']=='after_capabilities')['start_wall_ns']=239
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c)
