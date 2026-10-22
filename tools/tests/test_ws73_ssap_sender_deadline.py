"""Synthetic evidence/coordination fixtures,not an Engine or RF qualification."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ws73_capture import CaptureError
from ws73_diagnostic_hold import PROPERTIES
import ws73_ssap_sender_deadline as gate
from test_ws73_ssap_update_delivery import fixture as delivery_fixture
from test_ws73_north_star import aggregate,command_payload,pcap


def fixture(phase=0):
    row=delivery_fixture(phase)
    for i,v in enumerate(row['owners']):
        slot=i^phase
        v['owner'].update(port=f'1-{slot+1}',bus=1,device=10+slot)
    item=copy.deepcopy(row['ssap_update_delivery'][0]);item.pop('cases')
    row.update(ssap_sender_deadline_required=True,ssap_sender_deadline_status=gate.STATUS,
               ssap_sender_deadline=[item])
    api=item['publisher_api'];other='python'if api=='c'else'c';peer,server=row['owners']
    item['credentials']['capabilities']={k:'0'for k in ['CapEff','CapPrm','CapAmb','CapInh']}
    w=10**15;h=item['handle'];value=item['secret'];reply='ee'*32
    s=dict(version=1,phase=phase,property=h,value=value,start_wall_ns=w+200_000_000,
        clock=dict(before_ns=1_000_000_000,wall_ns=w+200_000_000,after_ns=1_000_000_100),
        controllers=[dict(bus=v['owner']['bus'],device=v['owner']['device'],index=v['owner']['index'],
            generation=v['owner']['generation'],lifetime=v['object']['lifetime'],handle=v['object']['handle'],port=v['owner']['port'])for v in row['owners']])
    send=dict(start_wall_ns=w+230_000_000,end_wall_ns=w+1_250_000_000,
        start_monotonic_ns=1_030_000_000,end_monotonic_ns=2_050_000_000,
        receipt=dict(api=api,handle=h,result=-110,started_ns=1_040_000_000,
                     deadline_ns=2_040_000_000,returned_ns=2_041_000_000))
    def configured(mode,start,end):
        return dict(start_wall_ns=w+start,end_wall_ns=w+end,receipt=dict(api=api,handle=h,modes=mode))
    markers=[];acks=[];receipts=[]
    for i,(phase_name,ack_name,start,end,state)in enumerate([
        ('arm_ready','armed',210_000_000,220_000_000,[True,False,0,0,0,0,False,0]),
        ('wait_held','held',1_260_000_000,1_270_000_000,[False,True,1,0,0,0,False,0]),
        ('release_ready','released',1_300_000_000,1_310_000_000,[False,False,1,1,0,0,False,0])]):
        m=dict(hold_phase=phase_name,wall_ns=w+start);markers.append(m)
        acks.append(dict(stage=ack_name,request=m,state=dict(zip(PROPERTIES,state)),host_wall_ns=100+i))
        receipts.append(dict(stage=ack_name,wall_ns=w+end))
    prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    output=[dict(stage='ssap_update_wait',api=other,handle=h,mode=2,client_closed=True),
        dict(stage='ssap_update_checked_reply',api=other,handle=h,mode=2,
             pdu=gate.update_frame(s)[4:].hex(),value=value,reply=reply)]
    case=dict(start_wall_ns=w,end_wall_ns=w+1_500_000_000,value=value,reply=reply,mode=2,selection=s,send=send,
        enabled=[configured(2,100_000_000,110_000_000)],
        owner_while_held=[configured(2,1_280_000_000,1_290_000_000)],
        disabled=[configured(0,1_410_000_000,1_420_000_000)],after=dict(value=reply),
        hold=dict(markers=markers,acks=acks,ack_receipts=receipts),
        application=dict(args=prefix+['update-peer',str(peer['owner']['index']),'7',peer['object']['path'],str(h),'2',value,reply],
            exit=0,stderr='',environment=item['environment'],credentials=item['credentials'],
            end_wall_ns=w+1_400_000_000,stdout=''.join(json.dumps(v)+'\n'for v in output)))
    item.update(case=case,end_wall_ns=w+2_000_000_000,cleanup=dict(exit=0,stdout='SsapLocalServices: []\n'))
    lines=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start=16 end=17 property=17; local registration only']
    for token,mode in enumerate([2,0],1):
        d=dict(api=api,index=server['owner']['index'],generation=7,token=token,request_id=token,
            lifetime=server['object']['lifetime'],handle=server['object']['handle'],epoch=41,level=2,
            deadline_ns=5_000_000_000,property=h,data_type=2,write=True,value=bytes([mode,0]).hex(),
            local_tcid=10,remote_tcid=10,pi=0,allow=True,decision_ns=4_000_000_000,decision_wall_ns=w)
        lines.append('SdkAuthorizationDecision: '+json.dumps(d))
    lines+=['SdkOwnedUpdateDeadline: '+json.dumps(send['receipt']),f'SsapOwnedValue: handle={h} value={reply}',
            f'SdkOwnedRemoved: api={api} start=16']
    item['stdout']='\n'.join(lines)+'\n'
    serial=0
    def matched(owner,direction,frame,window):
        nonlocal serial
        index=row['owners'].index(owner);op=frame[4];serial+=1
        if window is not case:at=3 if window is item['full_discovery']else 6
        elif op==16:at=300_000_000 if direction=='out'else 310_000_000
        elif op==17:at=320_000_000 if direction=='out'else 1_320_000_000
        else:at=100_000_000
        return dict(record=serial,data=frame.hex(),wall_ns=w+at if window is case else at,
                    direction=direction,controller=owner['owner']['index'],handle=owner['object']['handle'],boundary=0)
    return row,matched


def retired_fixture(phase=0):
    """Metadata/packet fixtures only;fixed new Error4 bytes are independent.

    Reuse the existing discovery/indication setup. New matching looks up a
    bounded packet collection and rejects missing/wrong packets;it does not
    return success for arbitrary production requests.
    """
    row,normal=fixture(phase)
    old,_=gate.corroborate(row,normal)
    packets=[dict(p)for leg in old[0]['wire'][:16]for p in [leg['tx'],leg['rx']]]
    owners=row['owners'];item=row[gate.FIELD][0];case=item['case'];api=item['publisher_api'];other='python'if api=='c'else'c'
    w=10**15;h=item['handle'];peer=owners[0]
    row['ssap_sender_lifecycle_case']='owner-after-deadline'
    item['exit']=-9
    item['stdout']='\n'.join(line for line in item['stdout'].splitlines()if
        not line.startswith(('SdkOwnedRemoved:','SsapOwnedValue:'))and
        not(line.startswith('SdkAuthorizationDecision:')and json.loads(line.split(': ',1)[1])['value']=='0000'))+'\n'
    case.pop('disabled');case.pop('after')
    case.update(owner_exit=-9,owner_exit_wall_ns=w+1_295_000_000)
    item['cleanup']=dict(exit=0,stdout='SsapLocalServices: []\n',start_wall_ns=w+1_296_000_000,end_wall_ns=w+1_299_000_000)
    case['owner_removal']=item['cleanup']
    prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    app=case['application'];app.update(args=prefix+['update-retired',str(peer['owner']['index']),'7',peer['object']['path'],str(h),'2','5','5000'],start_monotonic_ns=990_000_000,end_monotonic_ns=2_400_000_000)
    app['stdout']=''.join(json.dumps(v)+'\n'for v in [
        dict(stage='ssap_update_wait',api=other,handle=h,mode=2,deadline_ns=6_000_000_000,client_closed=True,started_ns=1_000_000_000,budget_ms=5000),
        dict(stage='ssap_update_error',api=other,handle=h,mode=2,errno=5,deadline_ns=6_000_000_000,returned_ns=2_390_000_000)])
    case['retired_write']=dict(args=prefix+['ssap-error',str(peer['owner']['index']),'7',peer['object']['path'],'ssap-write',str(h),'5',case['reply']],
        environment=item['environment'],credentials=copy.deepcopy(item['credentials']),exit=0,stderr='',
        start_wall_ns=w+1_420_000_000,end_wall_ns=w+1_460_000_000,start_monotonic_ns=2_410_000_000,end_monotonic_ns=2_460_000_000,
        stdout=''.join(json.dumps(v)+'\n'for v in [dict(stage='ssap_call',api=other,deadline_ns=7_420_000_000,call_ns=2_420_000_000,client_closed=True),
            dict(stage='ssap_error',api=other,errno=5,operation_success=False,deadline_ns=7_420_000_000,returned_ns=2_440_000_000)]))
    hb=h.to_bytes(2,'little')
    for source,target,pdu,tx,rx in [(0,1,b'\x0d\x23'+hb+b'\x02\0\0',330_000_000,1_331_000_000),
            (1,0,b'\x0e\x07\x01'+hb+b'\x04',1_340_000_000,1_341_000_000),
            (0,1,b'\x0d\x23'+hb+b'\0'+bytes.fromhex(case['reply']),1_430_000_000,1_431_000_000),
            (1,0,b'\x0e\x07\x01'+hb+b'\x04',1_440_000_000,1_441_000_000)]:
        for index,direction,at in [(source,'out',tx),(target,'in',rx)]:
            packets.append(dict(controller=owners[index]['owner']['index'],direction=direction,handle=owners[index]['object']['handle'],boundary=0,
                record=100+len(packets),data=(b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu).hex(),wall_ns=w+at))
    def matched(owner,direction,payload,window):
        found=[p for p in packets if p['controller']==owner['owner']['index']and p['direction']==direction
            and p['data']==payload.hex()and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1:raise CaptureError('one exact fixture packet required')
        return found[0]
    return row,matched,packets


class SenderDeadline(unittest.TestCase):
    def test_actual_guest_selector_function_needs_only_shell_builtins_and_rejects_bad_cases(self):
        source=(Path(__file__).resolve().parents[1]/'ws73_target_init.sh').read_text()
        function=re.search(r'^sender_case_argument\(\) \{\n.*?^\}',source,re.M|re.S)
        self.assertIsNotNone(function)
        program=function[0]+'\nsender_case_argument "$@"\n'
        for args,wanted in [([],''),(['ws73.ssap_sender_deadline=1'],''),
                (['ws73.ssap_sender_deadline=1','ws73.ssap_sender_case=owner-after-deadline'],'owner-after-deadline'),
                (['ws73.ssap_sender_deadline=1','ws73.ssap_sender_case=deadline'],'deadline')]:
            result=subprocess.run(['/bin/sh','-c',program,'selector',*args],env=dict(os.environ,PATH='/__missing__'),capture_output=True,text=True,timeout=2)
            self.assertEqual((result.returncode,result.stdout,result.stderr),(0,wanted,''))
        for args in [['ws73.ssap_sender_case=owner-after-deadline'],['ws73.ssap_sender_deadline=1','ws73.ssap_sender_case='],
                ['ws73.ssap_sender_deadline=1','ws73.ssap_sender_case=bad'],
                ['ws73.ssap_sender_deadline=1','ws73.ssap_sender_case=deadline','ws73.ssap_sender_case=owner-after-deadline'],
                ['ws73.ssap_sender_deadline=1','ws73.ssap_sender_deadline=1']]:
            result=subprocess.run(['/bin/sh','-c',program,'selector',*args],env=dict(os.environ,PATH='/__missing__'),capture_output=True,text=True,timeout=2)
            self.assertNotEqual(result.returncode,0,args)

    def test_owner_after_author_deadline_requires_actual_refusals_not_application_delivery(self):
        rows=[]
        for phase in (0,1):
            row,matched,_=retired_fixture(phase);proof,credit=gate.corroborate(row,matched)
            self.assertEqual(sum(credit.values()),20);self.assertEqual(proof[0]['application_replies'],0)
            self.assertEqual(proof[0]['retired_write_refusals'],1)
            rows.append(dict(phase=phase,ssap_sender_deadline=proof))
        p=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)
        self.assertTrue(gate.valid_summary(p))
        rows[1]['ssap_sender_deadline'][0].pop('lifecycle_case')
        self.assertFalse(gate.valid_summary(p))

    def test_owner_case_rejects_missing_wrong_or_premature_wire_refusal(self):
        for mode in ['missing','wrong-error','before-owner-exit']:
            row,matched,packets=retired_fixture();h=row[gate.FIELD][0]['handle'];raw=b'\x0a\0\x06\0\x0e\x07\x01'+h.to_bytes(2,'little')+b'\x04'
            packet=next(p for p in packets if p['data']==raw.hex())
            if mode=='missing':packets.remove(packet)
            elif mode=='wrong-error':packet['data']=raw[:-1].hex()+'09'
            else:packet['wall_ns']=10**15+1_294_000_000
            with self.subTest(mode=mode),self.assertRaises(CaptureError):gate.corroborate(row,matched)

    def test_new_gate_write_refusal_bytes_use_actual_production_codec(self):
        row,matched,_=retired_fixture();proof,_=gate.corroborate(row,matched)
        raw=bytes.fromhex(proof[0]['wire'][-1]['rx']['data'])[4:]
        codec=Path(__file__).resolve().parents[2]/'crates/slk-protocol/src/ssap/value.rs'
        h=row[gate.FIELD][0]['handle']
        # Include the actual Rust parser,not a test decoder. The packet comes
        # from this gate's real oracle path,so shared wrong fixture bytes do
        # not pass just because both sides of a matcher repeat the mistake.
        source=('#[path='+json.dumps(str(codec))+']\npub mod value;\n#[test]\n'
            'fn gate_refusal_vector(){assert_eq!(value::ValuePdu::decode(2048,&'+str(list(raw))+'),'
            'Ok(value::ValuePdu::WriteError{handle:'+str(h)+',error:4}));'
            'assert!(value::ValuePdu::decode(2048,&[14,11,4,0]).is_err());}\n')
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'vector.rs';out=Path(directory)/'vector';p.write_text(source)
            try:
                compile=subprocess.run(['rustc','--edition=2024','--test','-Dwarnings',str(p),'-o',str(out)],capture_output=True,text=True,timeout=30)
            except subprocess.TimeoutExpired as error:
                self.fail(f'actual production codec compile exceeded the original {error.timeout}s limit; '
                          f'command={error.cmd!r}; stdout_tail={(error.stdout or b"")[-4096:]!r}; '
                          f'stderr_tail={(error.stderr or b"")[-4096:]!r}')
            self.assertEqual(compile.returncode,0,compile.stdout+compile.stderr)
            run=subprocess.run([str(out)],capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_production_codec_compile_timeout_remains_failure_with_diagnostics(self):
        # Tool failure reporting fixture only. The real compiler/vector test
        # above remains mandatory with its original deadline and assertions.
        error=subprocess.TimeoutExpired(['rustc','fixture-command'],30,
                                        output=b'fixture-compiler-output',stderr=b'fixture-compiler-error')
        with patch('subprocess.run',side_effect=error):
            with self.assertRaisesRegex(self.failureException,
                    'original 30s limit.*fixture-compiler-output.*fixture-compiler-error'):
                self.test_new_gate_write_refusal_bytes_use_actual_production_codec()

    def test_owner_case_rejects_fabricated_success_late_removal_wrong_error_and_new_authority(self):
        for mutate in [lambda i:i['case'].update(owner_exit=0),
                lambda i:i['case']['owner_removal'].update(end_wall_ns=10**15+1_310_000_000),
                lambda i:i['case']['application'].update(stdout=i['case']['application']['stdout'].replace('"errno": 5','"errno": 110')),
                lambda i:i['case']['retired_write'].update(stdout=i['case']['retired_write']['stdout'].replace('false','true')),
                lambda i:i['case']['retired_write']['credentials']['capabilities'].update(CapEff='1'),
                lambda i:i.update(stdout=i['stdout']+'SdkOwnedRemoved: api=c start=16\n'),
                lambda i:i['case'].update(disabled=[]),lambda i:i['case']['retired_write'].update(exit=1)]:
            row,matched,_=retired_fixture();mutate(row[gate.FIELD][0])
            with self.assertRaises((CaptureError,KeyError)):gate.corroborate(row,matched)

    def test_lifecycle_selector_boot_and_prepared_input_cannot_fall_back(self):
        args=SimpleNamespace(ssap_sender_deadline_verify=True,ssap_sender_lifecycle_case='owner-after-deadline')
        self.assertEqual(gate.lifecycle_case(args),'owner-after-deadline')
        self.assertEqual(gate.boot_case(['ws73.ssap_sender_case=owner-after-deadline'],True),'owner-after-deadline')
        for tokens,enabled in [(['ws73.ssap_sender_case=owner-after-deadline'],False),
                (['ws73.ssap_sender_case=bogus'],True),(['ws73.ssap_sender_case=deadline']*2,True)]:
            with self.assertRaises(CaptureError):gate.boot_case(tokens,enabled)
        args.ssap_sender_deadline_verify=False
        with self.assertRaises(ValueError):gate.lifecycle_case(args)
        from ws73_target import file_record,HERE
        names=['ws73_ssap_sender_deadline.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh',
               'testing/application_client/client.c','testing/application_client/client.py']
        pkg=dict(inputs=[file_record(HERE/name)for name in names if not name.startswith('testing/')],
            application_client_tools=dict(sources=[file_record(HERE/name)for name in names if name.startswith('testing/')]))
        gate.validate_inputs(pkg)
        with self.assertRaises(ValueError):gate.validate_inputs(pkg,subscription=True)
        both=copy.deepcopy(pkg)
        both['inputs'] += [file_record(HERE/n)for n in ('ws73_ssap_subscription.py','ws73_application_role.py')]
        gate.validate_inputs(both,subscription=True)
        both['inputs'][-1]['sha256']='0'*64
        with self.assertRaises(ValueError):gate.validate_inputs(both,subscription=True)
        for name in names:
            broken=copy.deepcopy(pkg);records=broken['application_client_tools']['sources']if name.startswith('testing/')else broken['inputs']
            next(v for v in records if v['path'].endswith(name))['sha256']='0'*64
            with self.assertRaises(ValueError):gate.validate_inputs(broken)
        wrong=copy.deepcopy(pkg);wrong['inputs']+=wrong.pop('application_client_tools')['sources']
        with self.assertRaises(ValueError):gate.validate_inputs(wrong)

    def test_original_deadline_and_opposite_application_fixture_account_twenty_wire_legs(self):
        proof=[]
        for phase in (0,1):
            row,matched=fixture(phase);p,c=gate.corroborate(row,matched)
            self.assertEqual(sum(c.values()),20);self.assertEqual(p[0]['application_replies'],1)
            proof.append(dict(phase=phase,ssap_sender_deadline=p))
        self.assertTrue(gate.valid_summary(dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=proof)))

    def test_wrong_errno_success_renewed_deadline_early_or_excessively_late_terminal_never_pass(self):
        row,_=fixture();r=row[gate.FIELD][0]['case']['send']
        for changes in [dict(result=0),dict(result=-5),dict(result=False),dict(api='c-stub'),dict(handle=18),
                        dict(deadline_ns=3_040_000_000),dict(returned_ns=2_039_999_999),dict(returned_ns=3_040_000_000)]:
            bad=copy.deepcopy(r);bad['receipt'].update(changes)
            with self.assertRaises(CaptureError):gate.check_deadline(bad,'c',17)

    def test_missing_app_wrong_payload_or_early_release_never_pass(self):
        for mutate in [lambda i:i['case']['application'].update(stdout=''),
            lambda i:i['case'].update(reply='ff'*32),lambda i:i.update(stderr='failure'),
            lambda i:i['case']['hold']['markers'][2].update(wall_ns=10**15+1_200_000_000),
            lambda i:i['case']['owner_while_held'][0]['receipt'].update(modes=0),
            lambda i:i['credentials']['capabilities'].pop('CapInh'),
            lambda i:i.update(stdout=i['stdout']+'SdkOwnedUpdate: {}\n'),
            lambda i:i['case']['selection']['controllers'][1].update(lifetime=99)]:
            row,matched=fixture();mutate(row[gate.FIELD][0])
            with self.assertRaises((CaptureError,KeyError,AssertionError)):gate.corroborate(row,matched)

    def test_wrong_old_clock_or_early_ack_rx_are_not_a_deadline_barrier(self):
        for shift in [1_000_000_000,-1_000_000_000]:
            row,matched=fixture();row[gate.FIELD][0]['case']['selection']['clock']['wall_ns']+=shift
            with self.assertRaises(CaptureError):gate.corroborate(row,matched)

    def test_selected_guest_port_never_infers_hardware_slot_from_native_index(self):
        row,_=fixture(1);s=row[gate.FIELD][0]['case']['selection']
        self.assertEqual(s['controllers'][1]['index'],1);self.assertEqual(gate.check_selection(s,1),0)
        for key,value in [('phase',False),('property',0),('value','00'),('start_wall_ns',0),('controllers',[])]:
            bad=copy.deepcopy(s);bad[key]=value
            with self.assertRaises(CaptureError):gate.check_selection(bad,1)
        for port in ['1-3','1-4','1-1.1.3','1-2.1.4']:
            bad=copy.deepcopy(s);bad['controllers'][1]['port']=port
            with self.assertRaises(CaptureError):gate.check_selection(bad,1)

    def test_real_parser_live_prefix_requires_indication_tx_peer_rx_and_ack_tx_without_provider_ack(self):
        row,_=fixture();s=row[gate.FIELD][0]['case']['selection'];s['start_wall_ns']=10**15
        source,target=s['controllers'][1],s['controllers'][0];frame=gate.update_frame(s);ack=b'\x0a\0\x03\0\x11\x03\x01'
        def out(owner,data,at):
            raw=bytearray(command_payload(owner['handle'],data));raw[68]=0xa3
            return [(owner['bus'],owner['device'],at,raw,'S',1,-115),(owner['bus'],owner['device'],at+1000,raw,'C',1,0)]
        def incoming(owner,data,at):return(owner['bus'],owner['device'],at,aggregate(b'\xa3'+struct.pack('<HH',owner['handle'],len(data))+data),'C',0x81,0)
        records=out(source,frame,10**15+1000)+[incoming(target,frame,10**15+3000)]+out(target,ack,10**15+4000)
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'capture.pcap'
            for count in [1,2,3]:
                path.write_bytes(pcap(records[:count]));self.assertIsNone(gate.live_witness(folder,path,s,[]))
            path.write_bytes(pcap(records));observations=[];witness=gate.live_witness(folder,path,s,observations)
            self.assertEqual(witness['ack_tx']['direction'],'out');self.assertEqual(len(observations),1)
            path.write_bytes(pcap(records+[incoming(source,ack,10**15+8000)]))
            with self.assertRaises(CaptureError):gate.live_witness(folder,path,s,[])
            with self.assertRaises(CaptureError):gate.live_witness(folder,path,s,[{}]*64)

    def test_live_witness_requires_complete_reassembly_of_pb_split_short_indication(self):
        row,_=fixture();s=row[gate.FIELD][0]['case']['selection'];s['start_wall_ns']=10**15
        source,target=s['controllers'][1],s['controllers'][0];frame=gate.update_frame(s)
        def out(owner,data,at):
            raw=bytearray(command_payload(owner['handle'],data));raw[68]=0xa3
            return [(owner['bus'],owner['device'],at,raw,'S',1,-115),(owner['bus'],owner['device'],at+1000,raw,'C',1,0)]
        def incoming(part,boundary,at):
            data=aggregate(b'\xa3'+struct.pack('<HH',target['handle']|(boundary<<12),len(part))+part)
            return(target['bus'],target['device'],at,data,'C',0x81,0)
        records=out(source,frame,10**15+1000)+[incoming(frame[:21],1,10**15+3000)]
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'capture.pcap';path.write_bytes(pcap(records))
            self.assertIsNone(gate.live_witness(folder,path,s,[]))
            path.write_bytes(pcap(records+[incoming(frame[21:],3,10**15+4000)]+out(target,b'\x0a\0\x03\0\x11\x03\x01',10**15+5000)))
            result=gate.live_witness(folder,path,s,[]);self.assertIsNotNone(result)
            self.assertEqual([v['boundary']for v in result['indication_rx']['fragments']],[1,3])

    def test_existing_capture_prefix_hash_or_required_complete_observation_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'capture.pcap';raw=b'a'*24;path.write_bytes(raw)
            phases=[dict(live_observations=[dict(bytes=24,sha256=hashlib.sha256(raw).hexdigest())])for _ in (0,1)]
            for p in phases:p['live_witness']=dict(observations=p['live_observations'])
            gate.validate_prefixes(dict(phases=phases),path)
            phases[1]['live_observations'][0]['sha256']='0'*64
            with self.assertRaises(CaptureError):gate.validate_prefixes(dict(phases=phases),path)

    def test_explicit_dedicated_gate_and_actual_qemu_pin_required(self):
        args=SimpleNamespace(ssap_sender_deadline_verify=True,ssap_update_delivery_verify=True)
        self.assertTrue(gate.requested(args,passthrough=True))
        for changes in [dict(ssap_update_delivery_verify=False),dict(channel_socket_rounds=20),
                        dict(ssap_update_lifecycle_verify=True),dict(ssap_sender_deadline_verify=1)]:
            with self.assertRaises(ValueError):gate.requested(SimpleNamespace(**(vars(args)|changes)),passthrough=True)
        with self.assertRaises(ValueError):gate.requested(args,passthrough=False)
        with tempfile.NamedTemporaryFile()as q:
            with self.assertRaises(ValueError):gate.validate_qemu(q.name)

    def test_same_coordinator_waits_for_real_decoded_peer_ack_before_hold_acknowledgment(self):
        # Counted QMP fixture,not actual QEMU/USB acceptance. The live witness
        # itself was exercised through the actual decoder above.
        from test_ws73_diagnostic_hold import Monitor
        from ws73_diagnostic_hold import write_marker
        row,_=fixture();value=row[gate.FIELD][0]['case']['selection'];calls=[]
        class Routed:
            def __init__(self):self.monitors={0:Monitor(),1:Monitor()}
            def execute(self,command,args):
                slot=int(args['path'].rsplit('_',1)[1]);calls.append((slot,command,args['property']))
                return self.monitors[slot].execute(command,args|dict(path='/machine/peripheral/ws73_0'))
        with tempfile.TemporaryDirectory()as folder,patch.object(gate,'validate_qemu'):
            root=Path(folder);record={};c=gate.Coordinator(root,root,record,'fixture');m=Routed()
            selected=c.root/'phase-0';selected.mkdir(parents=True)
            write_marker(selected/'selection.json',value);write_marker(selected/'hold-arm_ready.json',dict(hold_phase='arm_ready',wall_ns=1))
            c.poll(m,lambda slot:dict(bus=1,address=100+slot))
            self.assertEqual(c.child.path,'/machine/peripheral/ws73_1')
            with patch.object(gate,'live_witness',side_effect=AssertionError('must not burn scan budget before request marker')):
                c.poll(m,lambda slot:None)
            m.monitors[1].state.update({'test-runtime-in-hold-once':False,'test-runtime-in-held':True,'test-runtime-in-holds':1})
            write_marker(selected/'hold-wait_held.json',dict(hold_phase='wait_held',wall_ns=2))
            with patch.object(gate,'live_witness',return_value=None):c.poll(m,lambda slot:None)
            self.assertFalse((selected/'hold-held-ack.json').exists())
            with patch.object(gate,'live_witness',return_value={'fixture':'verified separately'}):c.poll(m,lambda slot:None)
            self.assertTrue((selected/'hold-held-ack.json').exists())
            write_marker(selected/'hold-release_ready.json',dict(hold_phase='release_ready',wall_ns=3))
            c.poll(m,lambda slot:None);self.assertFalse(record['complete']);self.assertEqual(c.used,[1])
            self.assertEqual(set(v[0]for v in calls),{1})

    def test_terminal_gate_requires_both_original_hold_and_capture_witnesses(self):
        phases=[];proofs=[]
        for phase in (0,1):
            row,_=fixture(phase);case=row[gate.FIELD][0]['case'];s=case['selection'];slot=gate.check_selection(s,phase)
            observations=[dict(bytes=24,sha256='a'*64)]
            phases.append(dict(method=gate.METHOD,slot=slot,selection=s,selection_sha256=hashlib.sha256((json.dumps(s)+'\n').encode()).hexdigest(),
                complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=case['hold']['acks'],
                live_observations=observations,live_witness=dict(observations=observations,indication_tx={'fixture':1},indication_rx={'fixture':2},ack_tx={'fixture':3})))
            proofs.append(dict(phase=phase,slot=slot,held_kind='NOCP',host_hold=dict(status='ACTUAL_HOST_HOLD_CORROBORATED',
                host_transfer_sha256='b'*64,host_transfer_bytes=128,delivered_usb_record=20,
                physical_acceptance=False,automatic_fault_recovery_acceptance=False)))
        record=dict(method=gate.METHOD,qemu_sha256=gate.SEQUENCE_QEMU_SHA256,complete=True,
            physical_acceptance=False,automatic_fault_recovery_acceptance=False,phases=phases)
        proof=dict(status='TWO_ORIGINAL_AUTHOR_DEADLINE_LATE_ACK_HOLDS_CORROBORATED',phases=proofs)
        self.assertTrue(gate.valid_hold_summary(record,proof))
        for mutate in [lambda r:r['phases'].pop(),lambda r:r.update(complete=False),
            lambda r:r.update(qemu_sha256='0'*64),lambda r:r['phases'][0]['live_witness'].pop('ack_tx'),
            lambda r:r['phases'][0]['live_observations'][0].pop('sha256'),
            lambda r:r['phases'][1]['selection']['controllers'][1].update(generation=99),
            lambda r:r['phases'][0]['observations'][2]['state'].update({'test-runtime-in-bounded-releases':1})]:
            bad=copy.deepcopy(record);mutate(bad);self.assertFalse(gate.valid_hold_summary(bad,proof))
        self.assertFalse(gate.valid_hold_summary(record,dict(status=proof['status'],phases=[])))
