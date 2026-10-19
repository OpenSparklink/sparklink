"""Finite supervisor/verdict fixtures. Not a peer, kernel or radio qualification."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ws73_capture import CaptureError
from ws73_application_client import application_environment, owned_arguments
import ws73_ssap_receive_lifecycle as gate
from ws73_ssap_update_delivery import discovery_wire
from test_ws73_ssap_update_delivery import fixture as delivery_fixture, matched as delivery_matched


def fixture(phase=0):
    row=delivery_fixture(phase);s=phase;t=1-s;peer,server=row['owners'][s],row['owners'][t]
    for index,v in enumerate(row['owners']):v['owner'].update(bus=1,device=10+index)
    item=copy.deepcopy(row['ssap_update_delivery'][s]);api='c'if s==0 else'python';other='python'if s==0 else'c';mode=1+s;h=item['handle']
    item.update(policy='ask',publisher_api=api,cases=[],prompts=[],answers=[],end_wall_ns=10**15+16_000_000_000)
    item['args']=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'ask',update_connection=server['object']['path'])
    caps={k:'00000000'for k in ['CapEff','CapPrm','CapAmb','CapInh']}
    item['credentials']=dict(uids=[1000]*4,capabilities=caps)
    row.update(rounds=4,ssap_receive_lifecycle_required=True,ssap_receive_lifecycle_status=gate.STATUS,ssap_receive_lifecycle=[item],applications=[])
    packets={};serial=0
    def put(index,direction,pdu,window,wall):
        nonlocal serial
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        key=(index,direction,frame.hex(),window['start_wall_ns']);serial+=1
        packets[key]=dict(record=serial,wall_ns=wall,data=frame.hex(),direction=direction,handle=row['owners'][index]['object']['handle'],boundary=0,controller=index)
        return packets[key]
    def matcher(owner,direction,frame,window):
        key=(owner['owner']['index'],direction,frame.hex(),window['start_wall_ns'])
        if key not in packets:raise CaptureError('missing original paired leg')
        value=packets[key];return dict(value,fragments=[value])
    def pair(a,b,pdu,window,wall):
        return dict(tx=put(a,'out',pdu,window,wall),rx=put(b,'in',pdu,window,min(wall+1_000_000,window['end_wall_ns'])))
    discovery_wire(item,peer,lambda a,b,pdu,window:pair(a,b,pdu,window,window['start_wall_ns']))
    lines=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']
    def config(w,m,value):
        return dict(start_wall_ns=w,end_wall_ns=w+1_000_000,start_monotonic_ns=m,end_monotonic_ns=m+1_000_000,
            receipt=dict(api=api,handle=h,modes=value,started_ns=m+1,deadline_ns=m+5_000_000_001,returned_ns=m+2))
    for i,kind in enumerate(gate.CASES):
        w=10**15+i*5_000_000_000;m=10**12+i*5_000_000_000;early=kind=='exit-enable-pending';timeout=kind=='original-deadline'
        end_offset=2_010_000_000 if timeout else 30_000_000 if early else 80_000_000
        case=dict(kind=kind,mode=mode,start_wall_ns=w,end_wall_ns=w+end_offset+100_000_000,
            exit_wall_ns=w+end_offset,exit_monotonic_ns=m+end_offset,process_exit=0 if timeout else-9)
        budget=2000 if timeout else 5000
        call=dict(stage='ssap_update_wait',api=other,handle=h,mode=mode,client_closed=True,started_ns=m+10_000_000,budget_ms=budget,deadline_ns=m+10_000_000+budget*1_000_000)
        if timeout:
            case.update(exit_monotonic_ns=call['deadline_ns']+1_000_000,exit_wall_ns=w+2_011_000_000,end_wall_ns=w+2_111_000_000)
            end_offset=2_011_000_000
        cleanup_base=end_offset+100_000_000 if early else end_offset
        case['end_wall_ns']=w+cleanup_base+100_000_000
        case['call']=call;anchor=call['deadline_ns']if timeout else case['exit_monotonic_ns'];case['cleanup_observation_deadline_ns']=anchor+5_000_000_000
        prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
        args=prefix+['update-error'if timeout else'update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode)]+(['110','2000']if timeout else['11'*32,'22'*32])
        output=[call]
        if timeout:output.append(dict(stage='ssap_update_error',api=other,handle=h,mode=mode,errno=110,deadline_ns=call['deadline_ns'],returned_ns=case['exit_monotonic_ns']))
        case['application']=dict(args=args,exit=0 if timeout else-9,stderr='',stdout='\n'.join(map(json.dumps,output))+'\n',environment=application_environment(),credentials=dict(uids=[1000]*4,capabilities=caps),start_wall_ns=w+10_000_000,end_wall_ns=w+cleanup_base+90_000_000)
        for key,value,prompt_offset,answer_offset in [('enable',mode,20_000_000,80_000_000 if early else 40_000_000),('disable',0,cleanup_base+20_000_000,cleanup_base+30_000_000)]:
            token=i*2+(1 if key=='enable'else 2)
            context=dict(api=api,index=server['owner']['index'],generation=server['owner']['generation'],token=token,request_id=token,lifetime=server['object']['lifetime'],handle=server['object']['handle'],epoch=41,level=2,deadline_ns=m+prompt_offset+5_000_000_000,property=h,data_type=2,write=True,value=bytes([value,0]).hex(),local_tcid=10,remote_tcid=10,pi=0)
            event=dict(context=context,wall_ns=w+prompt_offset,monotonic_ns=m+prompt_offset)
            answer=dict(input_wall_ns=w+answer_offset,input_monotonic_ns=m+answer_offset,receipt=dict(api=api,token=token,current_token=token,allow=True,api_called=True,result=0,returned_ns=m+answer_offset+1))
            case[key+'_prompt']=event;case[key+'_answer']=answer;item['prompts'].append(event);item['answers'].append(answer)
            lines+=['SdkAuthorizationRequest: '+json.dumps(context),'SdkAuthorizationReply: '+json.dumps(answer['receipt'])]
            request=b'\x0d\x23'+h.to_bytes(2,'little')+bytes([2,value,0]);response=b'\x0e\x03'+h.to_bytes(2,'little')+bytes([2,value,0])
            pair(s,t,request,case,w+prompt_offset-1_000_000)
            result=pair(t,s,response,case,w+answer_offset+10_000_000)
            case[key+'_wire_barrier']=dict(mode=value,observations=[dict(bytes=24,sha256=hashlib.sha256(b'x'*24).hexdigest())],**result,observed_wall_ns=w+answer_offset+15_000_000,observed_monotonic_ns=m+answer_offset+15_000_000)
        enabled_offset=110_000_000 if early else 65_000_000
        case['enabled']=[config(w+enabled_offset,m+enabled_offset,mode)]
        case['disabled']=[config(w+cleanup_base+55_000_000,m+cleanup_base+55_000_000,0)]
        pair(s,t,b'\x08\x03'+h.to_bytes(2,'little')+b'\x02',case,w+15_000_000)
        pair(t,s,b'\x09\x03\0\0',case,w+17_000_000)
        expected_read=[item['discovery']['args'][0],'--adapter',peer['owner']['path'],'ssap-read',peer['object']['path'],str(h),'2']
        if early:
            case['pending_configuration']=[config(w+25_000_000,m+25_000_000,0)]
            case['busy_read']=dict(args=expected_read,exit=1,stderr=gate.BUSY,stdout='',start_wall_ns=w+35_000_000,end_wall_ns=w+40_000_000)
            case['business_window']=dict(start_wall_ns=w+45_000_000,end_wall_ns=w+75_000_000)
            row['applications']=[dict(exit=0,start_wall_ns=w+50_000_000,end_wall_ns=w+70_000_000)for _ in (0,1)]
        for observation in case.get('pending_configuration',[])+case['enabled']+case['disabled']:lines.append('SdkOwnedConfiguration: '+json.dumps(observation['receipt']))
        last=dict(args=expected_read,exit=0,stderr='',stdout=f'Selected {peer["owner"]["path"]}\nSsapPeerValue: operation=ssap-read path={peer["object"]["path"]} handle={h} value={item["secret"]}\n',start_wall_ns=w+cleanup_base+70_000_000,end_wall_ns=w+cleanup_base+80_000_000)
        case['new_read_attempts']=[last]
        pair(s,t,b'\x08\x03'+h.to_bytes(2,'little')+b'\0',last,last['start_wall_ns']+1)
        pair(t,s,b'\x09\x03'+bytes.fromhex(item['secret']),last,last['start_wall_ns']+2_000_000)
        item['cases'].append(case)
    item['stdout']='\n'.join(lines+[f'SdkOwnedRemoved: api={api} start={item["start"]}'])+'\n'
    return row,matcher,packets


class ReceiveLifecycle(unittest.TestCase):
    def test_actual_pipe_prefix_and_suffix_are_retained_without_file_callback_assumptions(self):
        with tempfile.TemporaryDirectory()as directory:
            run=SimpleNamespace(output=Path(directory),data={},save=lambda:None)
            command=[sys.executable,'-c','import time;print("original-call",flush=True);time.sleep(.05);print("original-terminal",flush=True)']
            with gate.receiver(run,command,'pipe-fixture')as invocation:
                self.assertNotIn('output_files',invocation.row)
                self.assertEqual(invocation.until(rb'^original-call$',timeout=1,limit=4096),b'original-call')
                invocation.process.wait(timeout=1)
            row=invocation.row
            self.assertEqual(row['stdout'],'original-call\noriginal-terminal\n');self.assertEqual(row['exit'],0)
            self.assertEqual(Path(row['output_files'][0]).read_bytes(),row['stdout'].encode())
            self.assertEqual(Path(row['output_files'][1]).read_bytes(),b'')
            self.assertIs(run.data['ssap_receive_applications'][0],row)

    def test_failed_actual_pipe_barrier_retains_child_output_and_error(self):
        with tempfile.TemporaryDirectory()as directory:
            run=SimpleNamespace(output=Path(directory),data={},save=lambda:None)
            with self.assertRaises(ValueError):
                with gate.receiver(run,[sys.executable,'-c','print("wrong-call",flush=True)'],'failed-pipe-fixture')as invocation:
                    invocation.until(rb'^required-call$',timeout=1,limit=4096)
            row=run.data['ssap_receive_applications'][0]
            self.assertIn('before',row['collector_error']);self.assertEqual(row['stdout'],'wrong-call\n')
            self.assertEqual(Path(row['output_files'][0]).read_bytes(),b'wrong-call\n')

    def test_live_barrier_uses_real_decoder_and_waits_only_for_incomplete_tail(self):
        from test_ws73_north_star import aggregate,command_payload,pcap
        import struct
        row,_,_=fixture();item=row['ssap_receive_lifecycle'][0];case=item['cases'][0]
        frame=b'\x0a\0\x07\0\x0e\x03\x11\0\x02\x01\0'
        outgoing=bytearray(command_payload(row['owners'][1]['object']['handle'],frame));outgoing[68]=0xa3
        incoming=aggregate(b'\xa3'+struct.pack('<HH',row['owners'][0]['object']['handle'],len(frame))+frame)
        at=case['start_wall_ns']+100_000_000
        records=[(1,11,at,outgoing,'S',1,-115),(1,11,at+1000,outgoing,'C',1,0),(1,10,at+2000,incoming,'C',0x81,0)]
        partial,complete=pcap(records[:1]),pcap(records)
        class Prefix:
            def __init__(self):self.count=0
            def open(self,_):
                self.count+=1;return io.BytesIO(partial if self.count==1 else complete)
        source=Prefix()
        with tempfile.TemporaryDirectory()as directory,patch.object(gate,'Path',side_effect=lambda value:source if str(value)=='/evidence/ws73.pcap'else Path(value)):
            result=gate.response_barrier(SimpleNamespace(output=Path(directory)),row,item,case,1,time.monotonic()+1)
        self.assertEqual(result['observations'][0]['partial'],'unfinished OUT submission at capture end')
        self.assertEqual(result['observations'][-1]['sha256'],hashlib.sha256(complete).hexdigest())
        self.assertEqual((result['tx']['device'],result['rx']['device']),(11,10))

    def test_live_barrier_never_uses_wrong_peer_handle_mode_or_malformed_capture(self):
        from test_ws73_north_star import aggregate,command_payload,pcap
        import struct
        row,_,_=fixture();item=row['ssap_receive_lifecycle'][0];case=item['cases'][0]
        at=case['start_wall_ns']+100_000_000
        for kind in ['missing-peer','wrong-handle','wrong-mode','invalid-header']:
            frame=b'\x0a\0\x07\0\x0e\x03\x11\0\x02'+bytes([2 if kind=='wrong-mode'else 1,0])
            outgoing=bytearray(command_payload(3,frame));outgoing[68]=0xa3
            incoming=aggregate(b'\xa3'+struct.pack('<HH',4 if kind=='wrong-handle'else 2,len(frame))+frame)
            records=[(1,11,at,outgoing,'S',1,-115),(1,11,at+1000,outgoing,'C',1,0)]
            if kind!='missing-peer':records.append((1,10,at+2000,incoming,'C',0x81,0))
            raw=b'invalid pcap header'.ljust(24,b'x')if kind=='invalid-header'else pcap(records)
            source=SimpleNamespace(open=lambda _:io.BytesIO(raw))
            with self.subTest(kind=kind),tempfile.TemporaryDirectory()as directory,patch.object(gate.time,'sleep',return_value=None),patch.object(gate,'Path',side_effect=lambda value:source if str(value)=='/evidence/ws73.pcap'else Path(value)):
                with self.assertRaises(CaptureError):gate.response_barrier(SimpleNamespace(output=Path(directory)),row,item,case,1,time.monotonic()+1)

    def test_actual_guard_requires_explicit_dedicated_protected_parent_gate(self):
        self.assertFalse(gate.requested(SimpleNamespace(),passthrough=False))
        args=SimpleNamespace(ssap_update_lifecycle_verify=True,ssap_update_delivery_verify=True)
        self.assertTrue(gate.requested(args,passthrough=True))
        for change,physical in [({'ssap_update_delivery_verify':False},True),({},False),({'ssap_update_lifecycle_verify':'yes'},True),({'channel_socket_rounds':8},True),({'channel_socket_bytes':2042},True)]:
            with self.assertRaises(ValueError):gate.requested(SimpleNamespace(**(vars(args)|change)),passthrough=physical)

    def test_finite_fixture_accounts_every_case_on_both_connection_roles(self):
        rows=[]
        for phase in (0,1):
            row,matcher,_=fixture(phase);proof,credit=gate.corroborate(row,matcher,[])
            self.assertEqual(credit,{0:17,1:17});self.assertEqual(len(proof[0]['wire']),34)
            rows.append(dict(phase=phase,ssap_receive_lifecycle=proof))
        self.assertTrue(gate.valid_summary(dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)))

    def test_missing_identity_original_deadline_exit_cleanup_or_business_never_pass(self):
        controls={
            'wrong-type':lambda r:r['ssap_receive_lifecycle'][0]['prompts'][0]['context'].update(data_type=0),
            'different-epoch':lambda r:r['ssap_receive_lifecycle'][0]['prompts'][2]['context'].update(epoch=42),
            'missing-owner-stream':lambda r:r['ssap_receive_lifecycle'][0].update(stdout=''),
            'root':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0]['application']['credentials'].update(uids=[0]*4),
            'missing-capabilities':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0]['application']['credentials'].update(capabilities={}),
            'caller-survives':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0]['application'].update(exit=0),
            'deadline-renewed':lambda r:r['ssap_receive_lifecycle'][0]['cases'][2]['call'].update(deadline_ns=10**18),
            'cleanup-renewed':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0].update(cleanup_observation_deadline_ns=10**18),
            'no-disable':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0].update(disabled=[]),
            'wrong-mode':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0].update(mode=3),
            'no-peer-value':lambda r:r['ssap_receive_lifecycle'][0]['cases'][0]['new_read_attempts'][0].update(stdout=''),
            'no-held-business':lambda r:r.update(applications=[]),
            'raw-reply-not-observed':lambda r:r['ssap_receive_lifecycle'][0]['cases'][1]['enable_wire_barrier'].update(rx={}),
            'poll-before-receive':lambda r:r['ssap_receive_lifecycle'][0]['cases'][1]['enable_wire_barrier'].update(observed_wall_ns=1),
        }
        for name,mutate in controls.items():
            with self.subTest(name=name):
                row,matcher,_=fixture();mutate(row)
                with self.assertRaises((CaptureError,KeyError,ValueError)):gate.corroborate(row,matcher,[])

    def test_missing_either_raw_leg_or_software_busy_reaching_wire_never_pass(self):
        row,matcher,packets=fixture()
        case=row['ssap_receive_lifecycle'][0]['cases'][0]
        raw=case['disable_wire_barrier']['rx'];key=next(k for k,p in packets.items()if p==raw);del packets[key]
        with self.assertRaises(CaptureError):gate.corroborate(row,matcher,[])
        row,matcher,_=fixture();case=row['ssap_receive_lifecycle'][0]['cases'][0];h=17
        extra=dict(data=(b'\x0a\0\x05\0\x08\x03'+h.to_bytes(2,'little')+b'\0').hex(),wall_ns=case['busy_read']['start_wall_ns'])
        with self.assertRaises(CaptureError):gate.corroborate(row,matcher,[extra])

    def test_live_prefix_hashes_must_reconstruct_from_sealed_original(self):
        rows=[fixture(phase)[0]for phase in (0,1)]
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'capture.pcap';path.write_bytes(b'x'*24)
            gate.validate_prefixes(rows,path)
            for mutate in [lambda r:r.pop(),lambda r:r[0]['ssap_receive_lifecycle'][0]['cases'][0]['enable_wire_barrier']['observations'][0].update(sha256='0'*64),lambda r:r[0]['ssap_receive_lifecycle'][0]['cases'][0]['enable_wire_barrier']['observations'][0].update(partial='truncated')]:
                bad=copy.deepcopy(rows);mutate(bad)
                with self.assertRaises(CaptureError):gate.validate_prefixes(bad,path)
            path.write_bytes(b'wrong original capture')
            with self.assertRaises(CaptureError):gate.validate_prefixes(rows,path)

    def test_summary_and_terminal_require_both_roles_all_cases_and_matching_boot_request(self):
        from ws73_target import run_exit_code
        from ws73_ssap_update_delivery import corroborate as delivery
        rows=[]
        for phase in (0,1):
            row,matcher,_=fixture(phase);receive,_=gate.corroborate(row,matcher,[]);updates,_=delivery(delivery_fixture(phase),delivery_matched)
            rows.append(dict(phase=phase,ssap_receive_lifecycle=receive,ssap_update_delivery=updates,
                protected_ssap=dict(required=2,controllers=[{'fixture':0},{'fixture':1}]),
                ssap_values=[{'fixture':'validated by separate production gate tests'}],
                ssap_discovery=[{'fixture':'validated by separate production gate tests'}]))
        proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows,round_trips=8)
        record=dict(status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',qemu_exit=0,supervisor_exit=0,live_security_agent_requested='numeric-approve',live_ssap_security_requirement=2,ordinary_channel_socket_acceptance=True,ssap_update_delivery_requested=True,ssap_update_delivery_acceptance=True,ssap_receive_lifecycle_requested=True,ssap_receive_lifecycle_acceptance=True,qemu_args=['ws73.ssap_update_delivery=1 ws73.ssap_receive_lifecycle=1'],channel_socket_corroboration=proof,security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=[dict(mode='numeric-approve',ssap_security_requirement=2)for _ in (0,1)],business_round_trips=8))
        self.assertEqual(run_exit_code(record),0)
        for changes in [dict(ssap_receive_lifecycle_acceptance=False),dict(ssap_update_delivery_requested=False),dict(ssap_receive_lifecycle_requested=False),dict(qemu_args=['ws73.ssap_update_delivery=1']),dict(supervisor_exit=1)]:
            self.assertEqual(run_exit_code(record|changes),1)
        for mutate in [lambda p:p['proofs'].pop(),lambda p:p['proofs'][0]['ssap_receive_lifecycle'][0].update(receiver_exits=True),lambda p:p['proofs'][0]['ssap_receive_lifecycle'][0]['wire'].pop(),lambda p:p['proofs'][1]['ssap_receive_lifecycle'][0].update(cases=gate.CASES[:-1])]:
            bad=copy.deepcopy(proof);mutate(bad);self.assertFalse(gate.valid_summary(bad))
