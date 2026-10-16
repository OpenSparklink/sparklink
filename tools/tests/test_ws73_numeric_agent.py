# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic evidence controls; not actual Agent/kernel/crypto/RF qualification."""
import json,unittest
from test_ws73_security_agent import fixture as old_fixture
from ws73_security_agent import witness,wire
from ws73_capture import CaptureError

def fixture(mode='numeric-approve'):
    r,p,d,c=old_fixture();r['mode']=mode
    events=r['events'];cb=[]
    for e in events:
        if e['stage']=='agent_callback':e['prompt'][8]='sdk111-numeric-comparison';cb.append(e)
        if e['stage']=='policy_result':
            e.update(wall_ns=90,phase=4 if mode=='numeric-approve' else 5 if mode=='numeric-reject' else 7,error=0 if mode=='numeric-approve' else -125 if mode=='numeric-reject' else -110,kernel_state=11 if mode=='numeric-approve' else 5 if mode=='numeric-reject' else 7,kernel_flags=119 if mode=='numeric-approve' else 7,kernel_error=0 if mode=='numeric-approve' else -13 if mode=='numeric-reject' else -110)
    for n,e in enumerate(cb):
        events.append(dict(stage='numeric_callback',prompt=e['prompt'].copy(),code=759201,wall_ns=49+n,daemon_owner=d['owner']))
        events.append(dict(stage='numeric_decision',prompt=e['prompt'].copy(),code=759201,wall_ns=55+n,monotonic_ns=5000000001 if mode=='numeric-late' else 4000000000,accepted=mode!='numeric-reject',reply_delivered=True))
    r['command']['stdout']='\n'.join(json.dumps(e) for e in events)
    c['commands']=[v for v in c['commands'] if v['opcode']!=0x1812 and (mode=='numeric-approve' or v['opcode'] not in [0x1c03,0x1c05])];c['complete']=[];c['native_events']=[v for v in c['native_events'] if v['event']!=0x14 and mode=='numeric-approve']
    order=[0x134,0x135,0x136,0x137,0x13c,0x139]+([0x141,0x142] if mode=='numeric-approve' else [])
    for i,index in enumerate(order):
        n=0 if index in [0x134,0x136,0x139,0x141] else 1;when=30+3*i if i<6 else 61+3*(i-6)
        data=bytes([1,0,4,16,0,2,2,2,2,0]) if index in [0x134,0x135] else bytes([16,0,2,2,2,2])+bytes(range(1,65)) if index==0x136 else bytes(range(129,193)) if index==0x137 else bytes([3])*16+bytes(range(32,48)) if index==0x13c else bytes(range(16,32)) if index==0x139 else bytes([i])*16
        raw=b'\1\0'+index.to_bytes(2,'little')+bytes([len(data)])+data
        c['commands'].append(dict(bus=1,device=n+2,opcode=0x1812,params=raw.hex(),completion=True,wall_ns=when,record=i))
        c['complete'].append(dict(bus=1,device=n+2,opcode=0x1812,status=0,value=raw[:4].hex(),wall_ns=when+1,record=50+i))
        c['native_events'].append(dict(bus=1,device=3-n,event=0x14,params=raw.hex(),wall_ns=when+2,record=100+i))
    return r,p,d,c

class NumericAgentEvidence(unittest.TestCase):
    def test_three_modes_preserve_native_and_business_distinction(self):
        for mode in ['numeric-approve','numeric-reject','numeric-late']:
            r,p,d,c=fixture(mode);witness(r,p,d);proof=wire(r,p,c)
            self.assertEqual(proof['opposite_receipts'],8 if mode=='numeric-approve' else 6)
            self.assertEqual(len(proof['installations']),2 if mode=='numeric-approve' else 0)

    def test_missing_or_wrong_numeric_decisions_never_pass(self):
        for kind in ['missing','code','method','identity','oldowner','deadline','policyyes','native9','preproof']:
            r,p,d,c=fixture();ns=[e for e in r['events'] if e['stage']=='numeric_decision'];n=ns[0]
            if kind=='missing':r['events'].remove(n)
            elif kind=='code':n['code']+=1
            elif kind=='method':n['prompt'][8]='sdk111-no-mitm'
            elif kind=='identity':n['prompt'][3]+=1
            elif kind=='oldowner':next(e for e in r['events'] if e['stage']=='numeric_callback')['daemon_owner']=':1.99'
            elif kind=='deadline':n['monotonic_ns']=5000000001
            elif kind=='policyyes':next(e for e in r['events'] if e['stage']=='policy_result')['native_admitted']=False
            elif kind=='native9':next(e for e in r['events'] if e['stage']=='policy_result')['kernel_state']=9
            else:n['wall_ns']=62
            r['command']['stdout']='\n'.join(json.dumps(e) for e in r['events'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):witness(r,p,d);wire(r,p,c)

    def test_rejected_or_late_callback_cannot_install(self):
        for mode in ['numeric-reject','numeric-late']:
            r,p,d,c=fixture(mode);c['commands'].append(dict(bus=1,device=2,opcode=0x1c03,wall_ns=80))
            with self.assertRaises(CaptureError):wire(r,p,c)
