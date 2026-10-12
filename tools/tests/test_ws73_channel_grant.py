# SPDX-License-Identifier: GPL-2.0-only
"""Receipt rejection and codec support tests, never real Grant qualification."""
import copy
import ctypes
import errno
from pathlib import Path
import select
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_channel_grant import Address, message, validate, verify


def fixture(case='release'):
    owners=[]
    for n in range(2):
        addr=Address(family=46,controller=n,version=2,generation=n+7,lifetime=1,lease=1,handle=0,local_tcid=31,remote_tcid=31,pi=241,directions=3)
        owners.append(dict(index=n,generation=n+7,lifetime=1,lease=1,handle=0,address=bytes(addr).hex()))
    outer=dict(index=0,case=case,leases=[1,1],release_before_wall_ns=100,release_after_wall_ns=110)
    denied=dict(errors={'send':13,'recv':13},poll=select.POLLERR|select.POLLHUP,marker=(b'GRNTDENY'+bytes(32)).hex())
    row=dict(status='GRANT_GATE_PASS',index=0,owners=owners,workers=[dict(credentials=dict(uids=[1000]*4,caps={k:'0' for k in ['CapEff','CapPrm','CapAmb']}),original=n+3,fd=n+9,original_errno=errno.EBADF,pid=123+n) for n in range(2)],
             armed=dict(pid=123,fd=9,wall_ns=50),blocking_witness=[dict(syscall=45,fd=9,state='S',wchan='__skb_wait_for_more_packets',wall_ns=t) for t in [60,90]],
             blocked_result=dict(stage='blocked_denied',errno=13,start_wall_ns=51,end_wall_ns=105),successor=dict(generation=7,lease=2),
             after_withdrawal=copy.deepcopy(denied),after_successor=copy.deepcopy(denied),end_wall_ns=150,business=[])
    for label in ['before']+(['after_first_control_close'] if case=='dup' else []):
        for initiator in range(2):
            payload=message();reply=bytearray(payload);reply[28]=1
            row['business'].append(dict(label=label,initiator=initiator,payload=payload.hex(),applications=[dict(sent=(payload if n==initiator else reply).hex(),received=(reply if n==initiator else payload).hex()) for n in range(2)]))
    return row,outer


class GrantReceipt(unittest.TestCase):
    def test_actual_unpublished_layout_and_random_business_validation(self):
        self.assertEqual(ctypes.sizeof(Address),48)
        self.assertEqual(Address.lease.offset,24)
        a=message();b=message();self.assertNotEqual(a,b);validate(a,a,False)
        reply=bytearray(a);reply[28]=1;validate(reply,a,True)
        reply[-1]^=1
        with self.assertRaises(ValueError):validate(reply,a,True)

    def test_rejects_missing_real_withdrawal_witness_or_ordinary_credentials(self):
        for case in ['release','close','dup']:
            row,outer=fixture(case);verify(row,outer)
            for kind in ['uid','caps','alias','wchan','syscall','fd','order','errno','successor','poll','payload','lease','address','business','timeout']:
                changed=copy.deepcopy(row)
                if kind=='uid':changed['workers'][0]['credentials']['uids']=[0]*4
                elif kind=='caps':changed['workers'][0]['credentials']['caps']['CapEff']='1'
                elif kind=='alias':changed['workers'][0]['original']=changed['workers'][0]['fd']
                elif kind=='wchan':changed['blocking_witness'][0]['wchan']='hrtimer_nanosleep'
                elif kind=='syscall':changed['blocking_witness'][0]['syscall']=35
                elif kind=='fd':changed['blocking_witness'][0]['fd']=8
                elif kind=='order':changed['blocking_witness'][1]['wall_ns']=101
                elif kind=='errno':changed['blocked_result']['errno']=errno.EAGAIN
                elif kind=='successor':changed['successor']['lease']=1
                elif kind=='poll':changed['after_successor']['poll']|=select.POLLOUT
                elif kind=='payload':changed['business'][0]['applications'][0]['received']=message().hex()
                elif kind=='lease':changed['owners'][0]['lease']=2
                elif kind=='address':changed['owners'][0]['address']=bytes(48).hex()
                elif kind=='business':changed['business'].pop()
                elif kind=='timeout':changed['blocked_result']['end_wall_ns']=8_000_000_100
                with self.subTest(case=case,kind=kind),self.assertRaises(ValueError):verify(changed,outer)

class GrantWireProof(unittest.TestCase):
    def test_requires_every_usb_leg_and_rejects_withdrawn_marker(self):
        from unittest.mock import patch
        from ws73_channel_grant import corroborate
        from ws73_capture import CaptureError
        row,outer=fixture();outer['usb']=[dict(bus=1,device=2+n) for n in range(2)]
        sdus=[]
        for b,business in enumerate(row['business']):
            business.update(start_wall_ns=10+b*10,end_wall_ns=19+b*10)
            for n,app in enumerate(business['applications']):
                for key,direction in [('sent','out'),('received','in')]:
                    payload=bytes.fromhex(app[key]);frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                    sdus.append(dict(bus=1,device=n+2,handle=0,direction=direction,data=frame.hex(),wall_ns=15+b*10))
        with patch('ws73_channel_grant.reassemble_acb',return_value=sdus):
            self.assertEqual(corroborate(row,outer,{})['business_round_trips'],2)
        for changed in [sdus[:-1],sdus+[sdus[0]],sdus+[dict(sdus[0],data=row['after_successor']['marker'])]]:
            with patch('ws73_channel_grant.reassemble_acb',return_value=changed),self.assertRaises(CaptureError):
                corroborate(row,outer,{})
