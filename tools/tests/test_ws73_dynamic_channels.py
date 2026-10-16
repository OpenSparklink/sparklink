"""Synthetic verifier controls; not codec, real USB, kernel or RF qualification."""
import unittest
from unittest.mock import patch
from ws73_capture import CaptureError
import ws73_dynamic_channels as gate
from ws73_target import run_exit_code


def fixture(long_bytes=None):
    run={'dynamic_channels':[],'connection_control':{'phases':[]}};packets=[];clock=100
    def emit(entry,direction,raw):
        nonlocal clock
        clock+=1;o,obj=entry['owner'],entry['object']
        packet=dict(bus=o['bus'],device=o['device'],handle=obj['handle'],direction=direction,data=raw.hex(),wall_ns=clock)
        if len(raw)>254:
            size=254 if direction=='out' else 28;chunks=[raw[n:n+size] for n in range(0,len(raw),size)]
            packet['fragments']=[dict(packet,data=part.hex(),boundary=1 if n==0 else 3 if n==len(chunks)-1 else 2) for n,part in enumerate(chunks)]
        packets.append(packet)
    def pair(a,b,raw):emit(a,'out',raw);emit(b,'in',raw)
    nonce_count=0
    for phase in range(2):
        clock+=1000
        owners=[dict(owner=dict(index=i,generation=7,bus=1,device=5+i,path=f'/adapter{i}'),object=dict(generation=7,lifetime=11+phase,handle=3+i,path=f'/adapter{i}/link{phase}')) for i in range(2)]
        run['connection_control']['phases'].append(dict(typed_objects=owners))
        row=dict(version=2 if long_bytes is not None else 1,long_bytes=long_bytes,phase=phase,owners=owners,start_wall_ns=clock,status='DYNAMIC_CHANNELS_USB_EVIDENCE_PENDING',channels=[],peer_stopped_confirmed=True,peer_stop_wall_ns=clock+1)
        run['dynamic_channels'].append(row)
        row['unbound_refusal']=dict(exit=1,stdout='NativeDynamicStaged: source=24570 destination=24571 aid=29441 passive=false\n')
        pair(*owners,gate.cmtc(gate.request(1,0x80,[24570,24571],0x7301)))
        pair(*owners[::-1],gate.cmtc(bytes([0x11,1,4,0,0x80,0,1,0])))
        def channel(name,source,dest,ports,rounds,identifier,message_bytes=61):
            c=dict(name=name,ports=ports,aid=0x7301,rounds=rounds,message_bytes=message_bytes,owners=owners,applications=[],tx_status_required=True,start_wall_ns=clock)
            row['channels'].append(c)
            mtu=max(249,message_bytes)
            pair(*owners,gate.cmtc(gate.request(identifier,source,ports,0x7301,mtu,mtu+5)))
            pair(*owners[::-1],gate.cmtc(bytes([0x11,identifier,4,0,source,dest,0,0])))
            for n,role in enumerate(['initiator','peer']):
                local,remote=(source,dest) if n==0 else (dest,source);o,obj=owners[n]['owner'],owners[n]['object'];p=ports if n==0 else ports[::-1]
                text=f'NativeDynamicStaged: source={p[0]} destination={p[1]} aid=29441 passive={"false" if n==0 else "true"}\n'
                text+=f'NativeChannelInfo: index={n} generation=7 lifetime={11+phase} handle={3+n} local={local} remote={remote} pi=241 mtu={mtu} mps={mtu+5} mode=0 directions=3\n'
                text+=f'NativeTxStatus: stage=ready sequence=0 index={n} generation=7 lifetime={11+phase} handle={3+n} maximum=254 capacity=5 outstanding=0 debt=0 peak=0 queued=0 limit=8 busy=0 bytes=0 offset=0 flags=0 blocks=0\n'
                text+=f'NativeChannelOpened: role={role} rounds={rounds}\nNativeChannelMessageSize: bytes={message_bytes}\n'
                args=['slctl','--adapter',o['path'],'dynamic-roundtrip' if n==0 else 'dynamic-peer',obj['path'],*map(str,p),'29441',str(rounds),str(message_bytes),'hold']
                c['applications'].append(dict(role=role,args=args,stdout=text,exit=0,credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0'))))
            return c
        def business(c,source,dest):
            nonlocal nonce_count
            for seq in range(c['rounds']):
                nonce_count+=1;raw=bytearray(b'SLKSOCK1'+nonce_count.to_bytes(16,'little')+nonce_count.to_bytes(4,'little')+b'\0'+bytes(c['message_bytes']-29))
                for j in range(c['message_bytes']-29):raw[29+j]=raw[8+j%16]^((nonce_count+j)&255)
                reply=bytearray(raw);reply[28]=1
                a,b=c['applications']
                a['stdout']+=f'NativeChannelSent: sequence={seq} bytes={raw.hex()}\nNativeChannelRoundTrip: sequence={seq} elapsed_ms=1 bytes={reply.hex()}\n'
                b['stdout']+=f'NativeChannelReceived: sequence={seq} bytes={raw.hex()}\nNativeChannelReply: sequence={seq} bytes={reply.hex()}\n'
                for sender,receiver,data,tcid in [(owners[0],owners[1],raw,dest),(owners[1],owners[0],reply,source)]:
                    pair(sender,receiver,bytes([tcid,0])+(len(data)+1).to_bytes(2,'little')+bytes([241])+data)
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
        if long_bytes is not None:
            c=channel('C',0x83,0x82,[24580,24581],4,6,long_bytes)
            row.update(long_peer_stop_wall_ns=clock+1,long_peer_stopped_confirmed=True,long_peer_resume_wall_ns=clock+4,slot_exhaustion=dict(exit=1,stdout='',stderr='native channel bind: No space left on device (os error 28)',start_wall_ns=clock+2,end_wall_ns=clock+3))
            clock+=4;business(c,0x83,0x82);close(c,0x83,0x82,7)
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
    def test_long_variant_and_asymmetric_fragment_shapes(self):
        for size in [250,253,254,255,1024,2042]:
            with self.subTest(size=size):
                run,packets=fixture(size);proof=self.check(run,packets)
                self.assertEqual(proof['round_trips'],56)
                self.assertEqual(proof['long_bytes'],size)
                self.assertEqual(proof['slot_exhaustion_refusals'],2)
                self.assertFalse(proof['tcid_reuse'])
    def test_missing_long_fragments_or_bad_content_fails(self):
        for change in ['absent','boundary','data']:
            run,packets=fixture(2042);packet=next(p for p in packets if len(bytes.fromhex(p['data']))==2047)
            if change=='absent':packet['fragments']=[]
            if change=='boundary':packet['fragments'][0]['boundary']=2
            if change=='data':packet['fragments'][0]['data']='00'
            with self.subTest(change=change),self.assertRaises(CaptureError):self.check(run,packets)
    def test_slot_refusal_before_staging_and_bounded_pause_required(self):
        for change in ['success','wrongerrno','staged','stop','deadline','missingC']:
            run,packets=fixture(2042);row=run['dynamic_channels'][0]
            if change=='success':row['slot_exhaustion']['exit']=0
            if change=='wrongerrno':row['slot_exhaustion']['stderr']='os error 110'
            if change=='staged':row['slot_exhaustion']['stdout']='NativeDynamicStaged:'
            if change=='stop':row['long_peer_stopped_confirmed']=False
            if change=='deadline':row['long_peer_resume_wall_ns']+=5_000_000_000
            if change=='missingC':row['channels'].pop()
            with self.subTest(change=change),self.assertRaises(CaptureError):self.check(run,packets)
    def test_long_manifest_cannot_downgrade_workload_or_drop_gate(self):
        run,packets=fixture(2042);proof=self.check(run,packets)
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,dynamic_channel_verification_requested=True,dynamic_channel_long_bytes_requested=2042,dynamic_channel_acceptance=True,ordinary_channel_socket_acceptance=True,dynamic_channel_corroboration=proof)
        self.assertEqual(run_exit_code(record),0)
        import copy
        for change in ['flag','type','size','channel','business','phase','baseline']:
            r=copy.deepcopy(record)
            if change=='flag':r['dynamic_channel_verification_requested']=False
            if change=='type':r['dynamic_channel_verification_requested']='true'
            if change=='size':r['dynamic_channel_long_bytes_requested']=255
            if change=='channel':r['dynamic_channel_corroboration']['proofs'][0]['channels'].pop()
            if change=='business':r['dynamic_channel_corroboration']['proofs'][0]['channels'][2]['business'].pop()
            if change=='phase':r['dynamic_channel_corroboration']['proofs'][0]['phase']=1
            if change=='baseline':r['ordinary_channel_socket_acceptance']=False
            with self.subTest(change=change):self.assertEqual(run_exit_code(r),1)
    def test_dynamic_request_cannot_pass_with_legacy_status_only(self):
        self.assertEqual(run_exit_code(dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,dynamic_channel_verification_requested=True)),1)


if __name__=='__main__':unittest.main()
