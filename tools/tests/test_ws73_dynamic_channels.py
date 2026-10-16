"""Synthetic verifier controls; not codec, real USB, kernel or RF qualification."""
import unittest
from unittest.mock import patch
from ws73_capture import CaptureError
import ws73_dynamic_channels as gate
from ws73_target import run_exit_code


def fixture():
    run={'dynamic_channels':[],'connection_control':{'phases':[]}};packets=[];clock=100
    def emit(entry,direction,raw):
        nonlocal clock
        clock+=1;o,obj=entry['owner'],entry['object']
        packets.append(dict(bus=o['bus'],device=o['device'],handle=obj['handle'],direction=direction,data=raw.hex(),wall_ns=clock))
    def pair(a,b,raw):emit(a,'out',raw);emit(b,'in',raw)
    nonce_count=0
    for phase in range(2):
        clock+=1000
        owners=[dict(owner=dict(index=i,generation=7,bus=1,device=5+i,path=f'/adapter{i}'),object=dict(generation=7,lifetime=11+phase,handle=3+i,path=f'/adapter{i}/link{phase}')) for i in range(2)]
        run['connection_control']['phases'].append(dict(typed_objects=owners))
        row=dict(version=1,phase=phase,owners=owners,start_wall_ns=clock,status='DYNAMIC_CHANNELS_USB_EVIDENCE_PENDING',channels=[],peer_stopped_confirmed=True,peer_stop_wall_ns=clock+1)
        run['dynamic_channels'].append(row)
        row['unbound_refusal']=dict(exit=1,stdout='NativeDynamicStaged: source=24570 destination=24571 aid=29441 passive=false\n')
        pair(*owners,gate.cmtc(gate.request(1,0x80,[24570,24571],0x7301)))
        pair(*owners[::-1],gate.cmtc(bytes([0x11,1,4,0,0x80,0,1,0])))
        def channel(name,source,dest,ports,rounds,identifier):
            c=dict(name=name,ports=ports,aid=0x7301,rounds=rounds,message_bytes=61,owners=owners,applications=[],tx_status_required=True,start_wall_ns=clock)
            row['channels'].append(c)
            pair(*owners,gate.cmtc(gate.request(identifier,source,ports,0x7301)))
            pair(*owners[::-1],gate.cmtc(bytes([0x11,identifier,4,0,source,dest,0,0])))
            for n,role in enumerate(['initiator','peer']):
                local,remote=(source,dest) if n==0 else (dest,source);o,obj=owners[n]['owner'],owners[n]['object'];p=ports if n==0 else ports[::-1]
                text=f'NativeDynamicStaged: source={p[0]} destination={p[1]} aid=29441 passive={"false" if n==0 else "true"}\n'
                text+=f'NativeChannelInfo: index={n} generation=7 lifetime={11+phase} handle={3+n} local={local} remote={remote} pi=241 mtu=249 mps=254 mode=0 directions=3\n'
                text+=f'NativeTxStatus: stage=ready sequence=0 index={n} generation=7 lifetime={11+phase} handle={3+n} maximum=254 capacity=5 outstanding=0 debt=0 peak=0 queued=0 limit=8 busy=0 bytes=0 offset=0 flags=0 blocks=0\n'
                text+=f'NativeChannelOpened: role={role} rounds={rounds}\nNativeChannelMessageSize: bytes=61\n'
                args=['slctl','--adapter',o['path'],'dynamic-roundtrip' if n==0 else 'dynamic-peer',obj['path'],*map(str,p),'29441',str(rounds),'61','hold']
                c['applications'].append(dict(role=role,args=args,stdout=text,exit=0,credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0'))))
            return c
        def business(c,source,dest):
            nonlocal nonce_count
            for seq in range(c['rounds']):
                nonce_count+=1;raw=bytearray(b'SLKSOCK1'+nonce_count.to_bytes(16,'little')+nonce_count.to_bytes(4,'little')+b'\0'+bytes(32))
                for j in range(32):raw[29+j]=raw[8+j%16]^((nonce_count+j)&255)
                reply=bytearray(raw);reply[28]=1
                a,b=c['applications']
                a['stdout']+=f'NativeChannelSent: sequence={seq} bytes={raw.hex()}\nNativeChannelRoundTrip: sequence={seq} elapsed_ms=1 bytes={reply.hex()}\n'
                b['stdout']+=f'NativeChannelReceived: sequence={seq} bytes={raw.hex()}\nNativeChannelReply: sequence={seq} bytes={reply.hex()}\n'
                for sender,receiver,data,tcid in [(owners[0],owners[1],raw,dest),(owners[1],owners[0],reply,source)]:
                    pair(sender,receiver,bytes([tcid,0,62,0,241])+data)
        def close(c,source,dest,identifier):
            c['close_start_wall_ns']=clock
            pair(*owners,gate.cmtc(bytes([0x12,identifier,2,0,source,dest])))
            pair(*owners[::-1],gate.cmtc(bytes([0x13,identifier,3,0,source,dest,0])))
            for n,a in enumerate(c['applications']):
                ports=c['ports'] if n==0 else c['ports'][::-1]
                a['stdout']+=f'NativeDynamicBusinessDone: rounds={c["rounds"]} held=true\nNativeDynamicLastClose: source={ports[0]} destination={ports[1]} aid=29441\n'
            c['end_wall_ns']=clock
        a=channel('A',0x81,0x80,[24576,24577],4,2);business(a,0x81,0x80)
        b=channel('B',0x82,0x81,[24578,24579],20,3)
        close(a,0x81,0x80,4);row['peer_resume_wall_ns']=clock
        business(b,0x82,0x81);close(b,0x82,0x81,5)
        row['smtc_after_close']=[dict(exit=0),dict(exit=0)];row['end_wall_ns']=clock
    return run,packets


class DynamicVerifier(unittest.TestCase):
    def check(self,run,packets):
        with patch.object(gate,'reassemble_acb',return_value=packets):return gate.corroborate(run,{})
    def test_complete_synthetic_shape_only(self):
        run,packets=fixture();p=self.check(run,packets)
        self.assertEqual(p['round_trips'],48)
        self.assertFalse(p['full_multichannel_matrix'])
        self.assertFalse(p['natural_recovery'])
    def test_missing_or_duplicate_usb_leg(self):
        run,packets=fixture()
        for p in [packets[1:],packets+[packets[0]],packets[:-1]]:
            with self.assertRaises(CaptureError):self.check(run,p)
    def test_payload_or_cmtc_identifier_replacement(self):
        for number in [0,2,8]:
            run,packets=fixture();raw=bytearray.fromhex(packets[number]['data']);raw[-1]^=1;packets[number]['data']=raw.hex()
            with self.assertRaises(CaptureError):self.check(run,packets)
    def test_missing_final_close_or_peer_business(self):
        for marker in ['NativeDynamicLastClose:','NativeChannelReceived:','NativeChannelRoundTrip:']:
            run,packets=fixture();app=run['dynamic_channels'][0]['channels'][0]['applications'][0 if marker=='NativeChannelRoundTrip:' else 1]
            app['stdout']='\n'.join(v for v in app['stdout'].splitlines() if not v.startswith(marker))
            with self.assertRaises(CaptureError):self.check(run,packets)
    def test_wrong_generation_args_caps_or_pending_status(self):
        for change in ['generation','args','caps','status','stopped','phase','exit']:
            run,packets=fixture();row=run['dynamic_channels'][0];app=row['channels'][0]['applications'][0]
            if change=='generation':app['stdout']=app['stdout'].replace('generation=7','generation=6')
            if change=='args':app['args'][4]='/stale/link'
            if change=='caps':app['credentials']['capabilities']['CapEff']='1'
            if change=='status':row['status']='RUNNING'
            if change=='stopped':row['peer_stopped_confirmed']=False
            if change=='phase':row['phase']=1
            if change=='exit':app['exit']=1
            with self.subTest(change=change),self.assertRaises(CaptureError):self.check(run,packets)
    def test_dynamic_request_cannot_pass_with_legacy_status_only(self):
        self.assertEqual(run_exit_code(dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,dynamic_channel_verification_requested=True)),1)


if __name__=='__main__':unittest.main()
