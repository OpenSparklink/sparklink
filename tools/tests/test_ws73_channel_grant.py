# SPDX-License-Identifier: GPL-2.0-only
"""Receipt rejection and codec support tests, never real Grant qualification."""
import copy
import ctypes
import errno
import array
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_channel_grant import Address, message, validate, verify, pass_channel, take_channel
from ws73_channel_grant import controller_ids, checked_controller_ids


class SelectedControllerIdentity(unittest.TestCase):
    def test_selected_ids_are_not_pair_local_indices_or_enumeration_order(self):
        for ids in ([0,1],[2,3],[3,2],[15,0]):
            self.assertEqual(controller_ids([SimpleNamespace(dev_index=n)for n in ids]),ids)
        for ids in ([0,0],[2,True],[2,16],[-1,3],[2],(2,3)):
            with self.subTest(ids=ids),self.assertRaises(ValueError):checked_controller_ids(ids)

    def test_existing_receipt_checks_require_actual_declared_pair_identity(self):
        row,outer=fixture();outer['controller_ids']=[2,3];row['controller_ids']=[2,3]
        for n,owner in enumerate(row['owners']):
            address=Address.from_buffer_copy(bytes.fromhex(owner['address']));address.controller=2+n
            owner.update(index=2+n,address=bytes(address).hex())
        verify(row,outer)
        for mutation in ('outer-missing','row-missing','pair-local','duplicate','bool'):
            bad=copy.deepcopy(row);context=copy.deepcopy(outer)
            if mutation=='outer-missing':context.pop('controller_ids')
            elif mutation=='row-missing':bad.pop('controller_ids')
            elif mutation=='pair-local':bad['owners'][0]['index']=0
            elif mutation=='duplicate':context['controller_ids']=[2,2]
            else:bad['controller_ids']=[True,3]
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify(bad,context)


class FdTransfer(unittest.TestCase):
    """Actual local Unix fd passing; no Sparklink/WS73 qualification claim."""
    def test_exact_fd_is_close_on_exec_and_outlives_sender_reference(self):
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as data:
            inode=os.fstat(data.fileno()).st_ino
            a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            with a,b:
                pass_channel(a,data,'test-token')
                data.close()
                with take_channel(b,'test-token',socket.AF_UNIX) as received:
                    self.assertEqual(os.fstat(received.fileno()).st_ino,inode)
                    self.assertTrue(fcntl.fcntl(received,fcntl.F_GETFD)&fcntl.FD_CLOEXEC)

    def test_rejected_transfer_closes_delivered_fds(self):
        a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        with a,b,socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as data:
            before=set(os.listdir('/proc/self/fd'))
            for count,payload in [(0,dict(stage='channel_fd',token='right')),(2,dict(stage='channel_fd',token='right')),(32,dict(stage='channel_fd',token='right')),(1,dict(stage='channel_fd',token='wrong')),(1,dict(stage='wrong',token='right')),(1,'malformed-json'),(1,'x'*17000)]:
                ancillary=[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[data.fileno()]*count))] if count else []
                a.sendmsg([(payload if isinstance(payload,str) else json.dumps(payload)).encode()],ancillary)
                with self.subTest(count=count,payload=payload),self.assertRaises((ValueError,json.JSONDecodeError)):
                    take_channel(b,'right',socket.AF_UNIX)
                self.assertEqual(set(os.listdir('/proc/self/fd')),before)


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
    def test_transfer_receipt_requires_isolated_ordinary_receiver_and_fd_identity(self):
        row,outer=fixture();row.update(scm_rights=True,transfers=[])
        for n,worker in enumerate(row['workers']):
            before=dict(stage='awaiting_channel_fd',pid=worker['pid'],credentials=worker['credentials'],token='a'*32,wall_ns=1,open_fds=[dict(fd=10,target='socket:[1]')])
            row['transfers'].append(dict(before=before,inode=n+100,start_wall_ns=2,broker_fd_closed_wall_ns=3))
            worker.update(wall_ns=5,scm_rights=dict(before=before,inode=n+100,received_wall_ns=4,close_on_exec=True))
        verify(row,outer)
        for kind in ['inode','order','inherited','cloexec','pid','credentials']:
            changed=copy.deepcopy(row);transfer=changed['workers'][0]['scm_rights']
            if kind=='inode':transfer['inode']=999
            elif kind=='order':transfer['received_wall_ns']=1
            elif kind=='inherited':transfer['before']['open_fds'].append(dict(fd=11,target='socket:[2]'))
            elif kind=='cloexec':transfer['close_on_exec']=False
            elif kind=='pid':transfer['before']['pid']=999
            elif kind=='credentials':transfer['before']['credentials']=dict(uids=[0]*4,caps={})
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(changed,outer)

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

class DirectionalGrantProof(unittest.TestCase):
    def test_directional_scope_requires_opposite_action_and_bind_denial(self):
        from unittest.mock import patch
        from ws73_channel_grant import corroborate
        from ws73_capture import CaptureError
        row,outer=fixture();row['directional']=True
        for key in ['armed','blocking_witness','blocked_result']:row.pop(key)
        row['bind_rejections']=[]
        for n,owner in enumerate(row['owners']):
            address=Address.from_buffer_copy(bytes.fromhex(owner['address']));address.directions=1 if n==0 else 2;owner['address']=bytes(address).hex()
            for directions,security,error in [(0,0,22),(4,0,22),(3,1,13),(3,2,13),(3,3,95)]:
                bad=Address.from_buffer_copy(bytes(address));bad.directions=directions;bad.security=security
                row['bind_rejections'].append(dict(controller=n,input=bytes(bad).hex(),errno=error))
        row['business']=row['business'][:1];business=row['business'][0];business.update(start_wall_ns=10,end_wall_ns=19)
        payload=business['payload'];business['applications']=[dict(stage='oneway',initiator=n==0,sent=payload if n==0 else None,received=payload if n==1 else None,direction_errno=13,denied_marker=(b'SCPDENY1'+bytes([n])*32).hex()) for n in range(2)]
        outer['usb']=[dict(bus=1,device=2+n) for n in range(2)]
        frame=(b'\x1f\0'+(62).to_bytes(2,'little')+b'\xf1'+bytes.fromhex(payload)).hex()
        sdus=[dict(bus=1,device=2+n,handle=0,direction='out' if n==0 else 'in',data=frame,wall_ns=15) for n in range(2)]
        verify(row,outer)
        with patch('ws73_channel_grant.reassemble_acb',return_value=sdus):
            proof=corroborate(row,outer,{});self.assertEqual(proof['one_way_deliveries'],1);self.assertEqual(proof['business_round_trips'],0);self.assertFalse(proof['blocked_rx_acceptance'])
        for kind in ['direction','denied','bind','missing','marker']:
            changed=copy.deepcopy(row);packets=copy.deepcopy(sdus)
            if kind=='direction':address=Address.from_buffer_copy(bytes.fromhex(changed['owners'][0]['address']));address.directions=3;changed['owners'][0]['address']=bytes(address).hex()
            elif kind=='denied':changed['business'][0]['applications'][1]['direction_errno']=11
            elif kind=='bind':changed['bind_rejections'][0]['errno']=95
            elif kind=='missing':packets.pop()
            else:packets.append(dict(sdus[0],data=business['applications'][1]['denied_marker']))
            with self.subTest(kind=kind),patch('ws73_channel_grant.reassemble_acb',return_value=packets),self.assertRaises((ValueError,CaptureError)):corroborate(changed,outer,{})
