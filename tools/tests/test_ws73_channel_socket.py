# SPDX-License-Identifier: GPL-2.0-only
"""Evidence parser fixtures, never real device acceptance."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_channel_socket import application_frames
from ws73_capture import CaptureError


def fixture():
    credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0'))
    apps=[dict(role=role,exit=0,credentials=copy.deepcopy(credentials),stdout=f'NativeChannelOpened: role={role} rounds=4\n') for role in ['initiator','peer']]
    for i in range(4):
        nonce=bytes([i+1])*16
        body=b'SLKSOCK1'+nonce+i.to_bytes(4,'little')+bytes(1)+bytes(nonce[j%16]^((i+j)&255) for j in range(32))
        reply=bytearray(body);reply[28]=1
        apps[0]['stdout']+=f'NativeChannelSent: sequence={i} bytes={body.hex()}\nNativeChannelRoundTrip: sequence={i} elapsed_ms=10 bytes={reply.hex()}\n'
        apps[1]['stdout']+=f'NativeChannelReceived: sequence={i} bytes={body.hex()}\nNativeChannelReply: sequence={i} bytes={reply.hex()}\n'
    return dict(rounds=4,applications=apps)


class ApplicationProof(unittest.TestCase):
    def test_original_two_application_messages(self):
        sent,replies=application_frames(fixture())
        self.assertEqual(len(sent),4);self.assertEqual(sent[0][28],0);self.assertEqual(replies[0][28],1)

    def test_missing_actual_reply_failed_process_privilege_or_duplicate(self):
        for kind in ['reply','failed','root','cap','duplicate','deadline','payload']:
            row=fixture();a=row['applications'][0];b=row['applications'][1]
            if kind=='reply':b['stdout']=b['stdout'].replace('NativeChannelReply:','Missing:')
            if kind=='failed':a['exit']=1
            if kind=='root':a['credentials']['uids']=[0]*4
            if kind=='cap':a['credentials']['capabilities']['CapEff']='1'
            if kind=='duplicate':a['stdout']+=a['stdout'].splitlines()[1]+'\n'
            if kind=='deadline':a['stdout']=a['stdout'].replace('elapsed_ms=10','elapsed_ms=10000')
            if kind=='payload':b['stdout']=b['stdout'].replace('bytes=534c4b','bytes=004c4b')
            with self.subTest(kind=kind),self.assertRaises(CaptureError):application_frames(row)


class IndependentUSBProof(unittest.TestCase):
    def fixture(self):
        from ws73_channel_socket import application_frames
        phases=[];sdus=[];events=[]
        for n in range(2):
            row=fixture();row.update(phase=n,status='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING',start_wall_ns=n*100+1,end_wall_ns=n*100+90)
            owners=[dict(owner=dict(bus=1,device=2+i,index=i,generation=i+1),object=dict(generation=i+1,lifetime=1+n*2,handle=0)) for i in range(2)]
            if n:owners.reverse()
            row['owners']=owners
            # Distinct nonce in second phase, regenerate all matching receipts.
            if n:
                for app in row['applications']:
                    for i in range(4):
                        old=bytes([i+1])*16;new=bytes([i+11])*16
                        for reply in [0,1]:
                            a=b'SLKSOCK1'+old+i.to_bytes(4,'little')+bytes([reply])+bytes(old[j%16]^((i+j)&255) for j in range(32))
                            b=b'SLKSOCK1'+new+i.to_bytes(4,'little')+bytes([reply])+bytes(new[j%16]^((i+j)&255) for j in range(32))
                            app['stdout']=app['stdout'].replace(a.hex(),b.hex())
            phases.append(row)
            def leg(sender,receiver,data):
                for entry,direction in [(sender,'out'),(receiver,'in')]:
                    sdus.append(dict(bus=entry['owner']['bus'],device=entry['owner']['device'],direction=direction,handle=0,data=data.hex(),wall_ns=n*100+20))
            sent,replies=application_frames(row)
            for data,reply in zip(sent,replies):
                for sender,receiver,payload in [(owners[0],owners[1],data),(owners[1],owners[0],reply)]:
                    leg(sender,receiver,b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload)
            for sender,receiver in [owners,owners[::-1]]:
                leg(sender,receiver,bytes.fromhex('0200080001010400e2000000'))
                leg(sender,receiver,bytes.fromhex('0200100002010c00e20000000000f900f9000101'))
                events.append(dict(bus=1,device=sender['owner']['device'],event=9,params='000006',wall_ns=n*100+30))
        return dict(channel_socket=phases),dict(native_events=events),sdus

    def test_both_usb_ends_capabilities_and_actual_credit(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture()
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            self.assertEqual(corroborate(run,capture)['round_trips'],8)

    def test_missing_opposite_rx_bad_capability_or_invented_completion(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        for kind in ['rx','cap','credit','handle','generation']:
            run,capture,sdus=self.fixture()
            if kind=='rx':sdus.pop(1)
            if kind=='cap':sdus[-1]['data']='0200080001010400e2000000'
            if kind=='credit':capture['native_events'][0]['params']='000005'
            if kind=='handle':capture['native_events'][0]['params']='010006'
            if kind=='generation':run['channel_socket'][0]['owners'][0]['object']['generation']=9
            with self.subTest(kind=kind),patch('ws73_channel_socket.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):
                corroborate(run,capture)
