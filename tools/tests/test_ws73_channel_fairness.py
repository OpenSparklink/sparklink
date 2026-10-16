# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic receipts and USB bytes only;not Native or fairness qualification."""
import copy
import unittest
from types import SimpleNamespace
from pathlib import Path
import tempfile
from unittest.mock import patch
from ws73_channel_fairness import corroborate, concurrent_progress
from ws73_channel_socket import check_arguments
from ws73_dynamic_channels import cmtc,request
from ws73_capture import CaptureError
from ws73_target import run_exit_code


def fixture():
    run=dict(connection_control=dict(phases=[]),channel_fairness=[])
    capture=dict(acb_packets=[],native_events=[]);clock=1000;serial=0;nonce=0
    def emit(owner,direction,raw):
        nonlocal clock,serial
        chunks=[raw[i:i+254] for i in range(0,len(raw),254)]
        for n,chunk in enumerate(chunks):
            clock+=1;serial+=1
            capture['acb_packets'].append(dict(record=serial,bus=owner['owner']['bus'],device=owner['owner']['device'],handle=owner['object']['handle'],direction=direction,data=chunk.hex(),wall_ns=clock,boundary=0 if len(chunks)==1 else 1 if n==0 else 3 if n==len(chunks)-1 else 2))
    def pair(a,b,raw):emit(a,'out',raw);emit(b,'in',raw)
    for phase in range(2):
        owners=[dict(owner=dict(index=i,generation=7,path=f'/org/sparklink/slk{i}_g7',bus=1,device=5+i),object=dict(generation=7,lifetime=11+phase,handle=3+i,path=f'/link{i}_{phase}')) for i in range(2)]
        run['connection_control']['phases'].append(dict(typed_objects=owners));clock+=100
        tool=dict(path='/bin/slktest',sha256='a'*64)
        row=dict(version=1,phase=phase,status='CONCURRENT_CHANNELS_USB_EVIDENCE_PENDING',owners=owners,start_wall_ns=clock,channels=[],starts=[],armed=[],cleanup_errors=[],unbound_refusal=dict(exit=1,stdout='NativeDynamicStaged:\n'))
        run['channel_fairness'].append(row)
        pair(*owners,cmtc(request(1,128,[24570,24571],29441)))
        pair(*owners[::-1],cmtc(bytes([17,1,4,0,128,0,1,0])))
        for k,(name,ports,count,size) in enumerate([('S',[24576,24577],20,61),('L',[24578,24579],16,2042)]):
            source,dest=129+k,128+k;mtu=max(249,size)
            pair(*owners,cmtc(request(2+k,source,ports,29441,mtu,mtu+5)));pair(*owners[::-1],cmtc(bytes([17,2+k,4,0,source,dest,0,0])))
            c=dict(name=name,ports=ports,aid=29441,rounds=count,message_bytes=size,burst=name=='L',start_barrier=True,tx_status_required=True,application_tool=tool,owners=owners,applications=[])
            row['channels'].append(c)
            for i,role in enumerate(['initiator','peer']):
                p=ports if i==0 else ports[::-1];local,remote=(source,dest) if i==0 else (dest,source);pid=100+phase*4+k*2+i
                text=f'NativeDynamicStaged: source={p[0]} destination={p[1]} aid=29441 passive={str(i==1).lower()}\n'
                text+=f'NativeChannelInfo: index={i} generation=7 lifetime={11+phase} handle={3+i} local={local} remote={remote} pi=241 mtu={mtu} mps={mtu+5} mode=0 directions=3\n'
                text+=f'NativeTxStatus: stage=ready sequence=0 index={i} generation=7 lifetime={11+phase} handle={3+i} maximum=254 capacity=5 outstanding=0 debt=0 peak=0 queued=0 limit=8 busy=0 bytes=0 offset=0 flags=0 blocks=0\n'
                text+=f'NativeDynamicArmed: count={count} bytes={size}\n'
                row['armed'].append(dict(pid=pid,stdout=text,stderr=''))
                c['applications'].append(dict(pid=pid,role=role,args=check_arguments(tool['path'],owners[i],i==1,count,size,'burst' if name=='L' and i==0 else 'regular',(*p,29441),True,True),stdout=text+f'NativeChannelOpened: role={role} rounds={count}\nNativeChannelMessageSize: bytes={size}\n',stderr='',exit=0,credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0'))))
        row['armed_wall_ns']=clock+1
        for p in row['armed']:row['starts'].append(dict(pid=p['pid'],before_wall_ns=clock+2,after_wall_ns=clock+3))
        clock+=10
        def message(c,n):
            nonlocal nonce
            nonce+=1;size=c['message_bytes'];raw=bytearray(b'SLKSOCK1'+nonce.to_bytes(16,'little')+nonce.to_bytes(4,'little')+b'\0'+bytes(size-29))
            for j in range(size-29):raw[29+j]=raw[8+j%16]^((nonce+j)&255)
            reply=bytearray(raw);reply[28]=1;a,b=c['applications'];source,dest=(129,128) if c['name']=='S' else (130,129)
            a['stdout']+=f'NativeChannelSent: sequence={n} bytes={raw.hex()}\nNativeChannelRoundTrip: sequence={n} elapsed_ms=1 bytes={reply.hex()}\n'
            b['stdout']+=f'NativeChannelReceived: sequence={n} bytes={raw.hex()}\nNativeChannelReply: sequence={n} bytes={reply.hex()}\n'
            pair(*owners,bytes([dest,0])+(size+1).to_bytes(2,'little')+b'\xf1'+raw)
            pair(*owners[::-1],bytes([source,0])+(size+1).to_bytes(2,'little')+b'\xf1'+reply)
        short,long=row['channels']
        for n in range(16):message(long,n);message(short,n)
        for n in range(16,20):message(short,n)
        long['applications'][0]['stdout']+='NativeBurstBlocked: sequence=8 poll_writable=0\nNativeBurstResumed: sequence=8\nNativeBurstPressure: eagain=1 not_writable=1 replies=16\n'
        for k,c in enumerate(row['channels']):
            c['close_start_wall_ns']=clock
            source,dest=129+k,128+k;ident=4+k
            pair(*owners,cmtc(bytes([18,ident,2,0,source,dest])));pair(*owners[::-1],cmtc(bytes([19,ident,3,0,source,dest,0])))
            c['end_wall_ns']=clock
            for a in c['applications']:
                p=c['ports'] if a['role']=='initiator' else c['ports'][::-1]
                a['stdout']+=f'NativeDynamicBusinessDone: rounds={c["rounds"]} held=true\nNativeDynamicLastClose: source={p[0]} destination={p[1]} aid=29441\n';a['end_wall_ns']=clock
        row['end_wall_ns']=clock
    return run,capture


class ConcurrentGate(unittest.TestCase):
    def test_full_receipts_and_raw_pb_fixture(self):
        run,capture=fixture();proof=corroborate(run,capture)
        self.assertEqual(proof['round_trips'],72);self.assertFalse(proof['full_fairness_acceptance'])
        self.assertFalse(proof['performance_qualified']);self.assertEqual(len(proof['proofs']),2)
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,channel_fairness_requested=True,channel_fairness_acceptance=True,channel_fairness_corroboration=proof)
        self.assertEqual(run_exit_code(record),0)
        for change in [dict(status='FAIL'),dict(qemu_exit=1),dict(channel_fairness_requested=False),dict(channel_fairness_acceptance=False)]:self.assertEqual(run_exit_code(record|change),1)

    def test_identity_start_ownership_payload_and_capture_negatives(self):
        for kind in ['missing-arm','early-start','business-before-start','wrong-pid','old-lifetime','route','wrong-pattern','missing-usb','pb','extra-usb','missing-close','no-pressure','failed-app','no-overlap','missing-tx-status','wrong-version']:
            run,capture=fixture();row=run['channel_fairness'][0];app=row['channels'][0]['applications'][0]
            if kind=='missing-arm':row['armed'].pop()
            elif kind=='early-start':row['starts'][0]['before_wall_ns']=row['armed_wall_ns']-1
            elif kind=='business-before-start':row['armed'][0]['stdout']+='NativeChannelOpened: role=initiator rounds=20\n'
            elif kind=='wrong-pid':app['pid']=row['channels'][1]['applications'][0]['pid']
            elif kind=='old-lifetime':app['stdout']=app['stdout'].replace('lifetime=11','lifetime=999')
            elif kind=='route':app['args'].remove('--start-barrier')
            elif kind=='wrong-pattern':app['stdout']=app['stdout'].replace('534c4b534f434b31','0000000000000000',1)
            elif kind=='missing-usb':capture['acb_packets'].pop(6)
            elif kind=='pb':next(v for v in capture['acb_packets'] if v['boundary']==2)['boundary']=0
            elif kind=='extra-usb':capture['acb_packets'].append(dict(capture['acb_packets'][5],record=99999))
            elif kind=='missing-close':capture['acb_packets']=[v for v in capture['acb_packets'] if not(v['data'].startswith('0200') and len(v['data'])==20 and bytes.fromhex(v['data'])[4]==18)]
            elif kind=='no-pressure':row['channels'][1]['applications'][0]['stdout']=row['channels'][1]['applications'][0]['stdout'].replace('poll_writable=0','poll_writable=1')
            elif kind=='failed-app':app['exit']=1
            elif kind=='missing-tx-status':row['channels'][0]['tx_status_required']=False
            elif kind=='wrong-version':row['version']=True
            else:
                for p in capture['acb_packets']:
                    raw=bytes.fromhex(p['data'])
                    if len(raw)==66:p['wall_ns']=row['end_wall_ns']-1
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate(run,capture)

    def test_unsupported_combination_rejected_before_device_access(self):
        import ws73_target
        for change in [dict(),dict(dynamic_channel_verify=True,channel_socket_verify=True,connection_verify=True,qmp_hotplug=True)]:
            with tempfile.TemporaryDirectory() as d:
                args=SimpleNamespace(**(dict(command='run',output=Path(d)/'absent',channel_fairness_verify=True)|change))
                with patch.object(ws73_target,'ordinary_identity'),patch.object(ws73_target,'prepared') as prepare,self.assertRaisesRegex(ValueError,'concurrent channel gate'):
                    ws73_target._run(args)
                prepare.assert_not_called();self.assertFalse(args.output.exists())
