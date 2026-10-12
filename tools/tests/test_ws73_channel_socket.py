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
