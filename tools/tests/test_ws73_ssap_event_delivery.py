# SPDX-License-Identifier: GPL-2.0-only
"""Literal two-end receipts and ACB bytes exercise the actual event verifier.

No hardware qualification; subprocess tests below explicitly replace process
I/O only. No successful corroborator or protocol Engine stub.
"""
import copy
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tempfile

from ws73_capture import CaptureError,reassemble_acb
from ws73_application_client import owned_arguments,application_environment
from ws73_ssap_owned import OUTPUT_MAXIMUM
import ws73_ssap_event_delivery as gate


def finish(item,lines):
    item.update(stdout='\n'.join(lines)+'\n',stderr='',exit=0,
        output_collection=dict(method='bounded-child-pipes',maximum_bytes_per_stream=OUTPUT_MAXIMUM,complete=True))
    item['captured_bytes']=dict(stdout=len(item['stdout'].encode()),stderr=0)


def fixture(phase=0):
    owners=[dict(owner=dict(index=i,generation=4,bus=1,device=10+i,path=f'/a{i}'),
            object=dict(generation=4,lifetime=100+phase*2+i,handle=3+i,path=f'/a{i}/peer_0/link_{100+phase*2+i}'))for i in (0,1)]
    row=dict(phase=phase,owners=owners,ssap_receipts=[dict(args=['slctl'])],ssap_owned_required=True,
        ssap_owned=[dict(sender=s,policy=p)for s in (0,1)for p in ('allow','deny')],ssap_event_delivery_required=True,
        ssap_event_delivery_version=1,ssap_event_delivery_status=gate.PENDING,ssap_event_delivery_tools={},ssap_event_delivery_cases=[])
    capture=dict(acb_packets=[],native_events=[])
    caps=dict(uids=[1000]*4,capabilities={k:'0'for k in ('CapEff','CapPrm','CapAmb','CapInh')})
    for s in (0,1):
        t=1-s;api='c'if(phase+s)%2==0 else'python';other='python'if api=='c'else'c'
        seed=lambda label:hashlib.sha256(f'{phase}/{s}/{label}'.encode()).hexdigest()
        base=10**12+phase*10**11+s*10**10;stamp=lambda n:base+n*1_000_000
        item=dict(sender=s,target=t,policy='none',entry_kind='event',event_minimum=0,start=16,handle=17,event_handle=18,end=18,pid=300+s,
            publisher_api=api,environment=application_environment(),credentials=copy.deepcopy(caps),service=seed('service')[:32],uuid=seed('property')[:32],event_uuid=seed('event')[:32],secret=seed('initial'),
            start_wall_ns=stamp(1),bound_wall_ns=stamp(2),end_wall_ns=stamp(1000),cases=[])
        item['args']=owned_arguments(api,owners[t],item['service'],item['uuid'],item['secret'],'none',event_uuid=item['event_uuid'],event_minimum=0)
        binding=dict(version=1,api=api,event=18,reply_property=17,minimum=0);item['event_binding']=binding
        lines=[f'SdkOwnedAPI: api={api} client_closed=true','SsapOwnedService: start=16 end=18 property=17; local registration only','SdkOwnedEventBinding: '+json.dumps(binding)]
        for ordinal,mode in enumerate((1,2)):
            seq=phase*4+s*2+ordinal;b=stamp(10+ordinal*200);at=lambda n:b+n*1_000_000;mono=10**9+seq*10**8
            value=(seq.to_bytes(4,'little')+bytes.fromhex(seed(f'value{mode}'))[4:]).hex()
            reply=((seq|0x80000000).to_bytes(4,'little')+bytes.fromhex(seed(f'reply{mode}'))[4:]).hex()
            pdu=bytes([14+mode,7,18,0,32,0])+bytes.fromhex(value)
            ready=dict(stage='ssap_event_listener_ready',version=1,api=other,event=18,reply_property=17,minimum=0,token=ordinal+1,epoch=41,expires_ns=mono+10_000_000_000,started_ns=mono,returned_ns=mono+10,deadline_ns=mono+5_000_000_000,client_closed=True)
            checked=dict(stage='ssap_event_checked_reply',version=1,api=other,event=18,reply_property=17,minimum=0,sequence=ordinal+1,value=value,reply=reply,started_ns=mono+30,returned_ns=mono+100,deadline_ns=mono+30+5_000_000_000)
            batch=dict(stage='ssap_subscription_batch',api=other,last=ordinal+1,dropped=0,refused=0,state=1,flags=0,reason=0,discarded=0,packets=[dict(sequence=ordinal+1,epoch=41,level=0,indication=mode==2,pdu=pdu.hex())])
            closed=dict(stage='ssap_subscription_released',api=other,flags=1,discarded=0)
            app=dict(api=other,pid=400+s,args=gate.peer_arguments(other,owners[s],18,17),environment=application_environment(),credentials=copy.deepcopy(caps),start_wall_ns=at(1),end_wall_ns=at(90))
            finish(app,[json.dumps(x)for x in (ready,checked,batch,closed)])
            receipt=dict(version=1,api=api,handle=18,minimum=0,stage=mode,pdu=pdu.hex(),ack='110701'if mode==2 else'',started_ns=mono+40,returned_ns=mono+80,deadline_ns=mono+40+5_000_000_000)
            case=dict(mode=mode,sequence=seq,value=value,reply=reply,start_wall_ns=at(0),end_wall_ns=at(99),application=app,ready=ready,checked=checked,
                ready_observed_wall_ns=at(2),check_sent_wall_ns=at(3),check_command=f'check {value} {reply}',checked_observed_wall_ns=at(80),
                send=dict(start_wall_ns=at(4),end_wall_ns=at(75),start_monotonic_ns=mono+39,end_monotonic_ns=mono+81,receipt=receipt),
                after=dict(start_wall_ns=at(91),end_wall_ns=at(92),value=reply,handle=17,ordinal=ordinal+1))
            item['cases'].append(case);lines+=['SdkOwnedEvent: '+json.dumps(receipt),f'SsapOwnedValue: handle=17 value={reply}']
            expected=[(t,s,pdu)]+([(s,t,b'\x11\x07\x01')]if mode==2 else[])+[(s,t,b'\x0d\x23\x11\0\0'+bytes.fromhex(reply)),(t,s,b'\x0e\x03\x11\0\0'+bytes.fromhex(reply))]
            for n,(a,z,payload) in enumerate(expected):
                frame=b'\x0a\0'+len(payload).to_bytes(2,'little')+payload
                for leg,(endpoint,direction)in enumerate(((a,'out'),(z,'in'))):
                    record=len(capture['acb_packets'])+1
                    capture['acb_packets'].append(dict(bus=1,device=10+endpoint,handle=3+endpoint,direction=direction,data=frame.hex(),boundary=0,record=record,wall_ns=at(10+n*4+leg)))
        lines.append(f'SdkOwnedRemoved: api={api} start=16');finish(item,lines)
        item['cleanup']=dict(exit=0,stderr='',stdout='SsapLocalServices: []\n',args=['slctl','--adapter',owners[t]['owner']['path'],'ssap-list'],start_wall_ns=stamp(900),end_wall_ns=stamp(901))
        row['ssap_event_delivery_cases'].append(item)
    packets=reassemble_acb(capture)
    def matched(owner,direction,frame,window):
        key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
        found=[p for p in packets if tuple(p[k]for k in ('bus','device','handle','direction','data'))==key and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1:raise CaptureError('exact original fixture packet required')
        packets.remove(found[0]);return found[0]
    return row,matched,packets


def summary():
    rows=[]
    for phase in (0,1):
        row,matched,packets=fixture(phase);proof,credit=gate.corroborate(row,matched,inventory=copy.deepcopy(packets))
        assert credit=={0:7,1:7}and not packets
        rows.append(dict(phase=phase,owners=row['owners'],ssap_event_deliveries=proof))
    return dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows)


class EventEvidence(unittest.TestCase):
    def test_literal_both_roles_directions_modes_and_credit(self):
        self.assertTrue(gate.valid_summary(summary()))
        gate.validate_rows([fixture(0)[0],fixture(1)[0]],True)

    def test_saved_summary_rechecks_raw_evidence(self):
        original=summary()
        for mutation in ('missing-side','wrong-device','wrong-fragment','bad-payload','duplicate','extra-cpcd','no-inventory','truncated-output','no-ready','false-ready','late-ready','late-deadline','wrong-readback','same-reply','queue-loss','bad-close','bad-ack','missing-mode','wrong-version','wrong-lifetime','bad-exit','wrong-role','bool-sequence','sudo','old-artifact-phase','reused-token','changed-epoch','overlapping-cases','early-cleanup'):
            with self.subTest(mutation=mutation):
                value=copy.deepcopy(original);item=value['proofs'][0]['ssap_event_deliveries'][0];case=item['case']['cases'][0];app=case['application']
                if mutation=='missing-side':item['wire'][0].pop('rx')
                elif mutation=='wrong-device':item['wire'][0]['rx']['device']=99
                elif mutation=='wrong-fragment':item['wire'][0]['rx']['fragments'][0]['handle']=99
                elif mutation=='bad-payload':item['wire'][0]['tx']['data']='0a0002000f07'
                elif mutation=='duplicate':item['window_packets'].append(copy.deepcopy(item['window_packets'][0]))
                elif mutation=='extra-cpcd':
                    p=copy.deepcopy(item['window_packets'][0]);p['data']='0a0007000d231100020100';item['window_packets'].append(p)
                elif mutation=='no-inventory':item.pop('window_packets')
                elif mutation=='truncated-output':app['stdout']=app['stdout'][:-20]
                elif mutation=='no-ready':case.pop('ready')
                elif mutation=='false-ready':case['ready']['client_closed']=False
                elif mutation=='late-ready':case['ready_observed_wall_ns']=case['send']['end_wall_ns']+1
                elif mutation=='late-deadline':case['checked']['returned_ns']=case['checked']['deadline_ns']
                elif mutation=='wrong-readback':case['after']['value']='00'
                elif mutation=='same-reply':case['reply']=case['value']
                elif mutation=='queue-loss':app['stdout']=app['stdout'].replace('"dropped": 0','"dropped": 1');app['captured_bytes']['stdout']=len(app['stdout'].encode())
                elif mutation=='bad-close':app['stdout']=app['stdout'].replace('"flags": 1','"flags": 17');app['captured_bytes']['stdout']=len(app['stdout'].encode())
                elif mutation=='bad-ack':case['send']['receipt']['ack']='110701'
                elif mutation=='missing-mode':item['case']['cases'].pop()
                elif mutation=='wrong-version':item['version']=True
                elif mutation=='wrong-lifetime':item['context']['owners'][0]['object']['lifetime']+=1
                elif mutation=='bad-exit':app['exit']=1
                elif mutation=='wrong-role':value['proofs'][0]['phase']=1
                elif mutation=='bool-sequence':case['sequence']=False
                elif mutation=='sudo':app['credentials']['uids']=[0]*4
                elif mutation=='old-artifact-phase':value['proofs'].pop()
                elif mutation=='reused-token':item['case']['cases'][1]['ready']['token']=case['ready']['token']
                elif mutation=='changed-epoch':item['case']['cases'][1]['ready']['epoch']+=1
                elif mutation=='overlapping-cases':item['case']['cases'][1]['start_wall_ns']=case['start_wall_ns']
                elif mutation=='early-cleanup':item['case']['cleanup']['start_wall_ns']=case['start_wall_ns']
                self.assertFalse(gate.valid_summary(value))

    def test_raw_missing_duplicate_or_foreign_packet_rejected(self):
        for change in ('missing','duplicate','foreign','unrelated-owner'):
            row,matched,packets=fixture();inventory=copy.deepcopy(packets)
            if change=='missing':packets.pop()
            elif change=='duplicate':packets.append(copy.deepcopy(packets[-1]))
            elif change=='foreign':packets[-1]['handle']+=1
            else:row['owners'][1]['owner']['device']=row['owners'][0]['owner']['device']
            with self.subTest(change=change),self.assertRaises(CaptureError):gate.corroborate(row,matched,inventory=inventory)

    def test_selector_boot_manifest_and_rows(self):
        a=SimpleNamespace(ssap_event_delivery_verify=True,ssap_owned_verify=True,channel_socket_verify=True,passthrough=True)
        self.assertTrue(gate.requested(a));self.assertTrue(gate.boot_requested([gate.TOKEN,'ws73.ssap_owned=1']))
        for k,v in [('ssap_owned_verify',False),('ssap_method_provider_verify',True),('ssap_event_delivery_verify',1),('channel_socket_rounds',5),('security_agent','numeric-approve')]:
            args=copy.copy(a);setattr(args,k,v)
            with self.subTest(k=k),self.assertRaises(ValueError):gate.requested(args)
        for tokens in ([gate.TOKEN],[gate.TOKEN,gate.TOKEN,'ws73.ssap_owned=1'],['ws73.ssap_event_delivery=0']):
            with self.assertRaises(ValueError):gate.boot_requested(tokens)
        proof=summary();record=dict(ssap_event_delivery_requested=True,ssap_event_delivery_version=1,ssap_event_delivery_acceptance=True,ssap_owned_requested=True,ssap_owned_acceptance=True,ordinary_channel_socket_acceptance=True,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,qemu_args=[gate.TOKEN+' ws73.ssap_owned=1'],channel_socket_corroboration=proof)
        self.assertTrue(gate.valid_manifest(record));self.assertTrue(gate.valid_manifest({}))
        for k,v in [('qemu_exit',True),('qemu_exit',1),('qemu_args',[]),('ssap_event_delivery_version',True),('ssap_event_delivery_acceptance',False),('ssap_owned_acceptance',False),('status','FAILED')]:
            with self.subTest(k=k):self.assertFalse(gate.valid_manifest(dict(record,**{k:v})))
        with self.assertRaises(CaptureError):gate.validate_rows([fixture()[0]],True)
        with self.assertRaises(CaptureError):gate.validate_rows([fixture()[0]],False)

    def test_exact_tool_inputs_and_binding_parameters(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);from ws73_ssap_update_delivery import TOOLS
            for name in (*TOOLS,*gate.EXTRA_TOOLS):
                p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            records=gate.tool_records(root);manifest=[dict(path=str(root/n.lstrip('/')),sha256=v['sha256'])for n,v in records.items()]
            gate.validate_tools(records,root,manifest)
            with self.assertRaises(CaptureError):gate.validate_tools(records,root,manifest[:-1])
            (root/gate.EXTRA_TOOLS[0].lstrip('/')).write_bytes(b'old')
            with self.assertRaises(CaptureError):gate.validate_tools(records,root,manifest)
        row,_,_=fixture();item=row['ssap_event_delivery_cases'][0]
        for bad in [dict(event_minimum=True),dict(event_uuid='00'),dict(policy='allow'),dict(read_provider=True)]:
            options=dict(event_uuid=item['event_uuid'],event_minimum=0,policy='none');options.update(bad);policy=options.pop('policy')
            with self.assertRaises(CaptureError):owned_arguments('c',row['owners'][1],item['service'],item['uuid'],item['secret'],policy,**options)
        with self.assertRaises(CaptureError):gate.peer_arguments('c',row['owners'][0],18,18)

    def test_supervisor_waits_for_exact_ready_and_preserves_failures(self):
        # Only process I/O/state and the wire are fixtures. Exercise the actual
        # supervisor branch, command order, save-on-failure and pending verdict.
        import time
        for failure in (None,'missing-ready','wrong-ready','bad-exit'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory()as tmp:
                original,_,_=fixture();row={k:copy.deepcopy(v)for k,v in original.items()if not k.startswith('ssap_event_delivery_')}
                run=SimpleNamespace(output=Path(tmp),save=lambda:trace.append('save'));trace=[];active={}
                class Input:
                    def __init__(self,kind):self.kind=kind
                    def write(self,text):trace.append((self.kind,text))
                    def flush(self):pass
                def proc(kind):return SimpleNamespace(pid=123,returncode=None,stdin=Input(kind))
                @contextmanager
                def publish(run,row,sender,policy,**kw):
                    self.assertEqual((policy,kw['event_minimum']),('none',0));owner=proc('owner')
                    item=copy.deepcopy(original['ssap_event_delivery_cases'][sender]);item.update(output_files=[str(Path(tmp)/'owner'),str(Path(tmp)/'owner.err')]);row['ssap_event_delivery_cases'].append(item)
                    active.update(sender=sender,owner=owner,item=item);yield owner,item
                @contextmanager
                def observe(args,app,out,err,**kw):
                    child=proc('peer');active.update(app=app,child=child,args=args)
                    try:yield child
                    except BaseException:
                        app['error_fixture_retained']=True;raise
                    finally:app.update(exit=child.returncode,end_wall_ns=time.time_ns())
                def wait(child,out,pattern,deadline,**kw):
                    if 'listener_ready'in pattern:
                        if failure=='missing-ready':raise CaptureError('explicit missing real Ready fixture')
                        now=time.monotonic_ns();ready=dict(stage='ssap_event_listener_ready',version=1,api=active['app']['api'],event=18,reply_property=17,minimum=0,token=1,epoch=41,client_closed=True,started_ns=now,returned_ns=now,deadline_ns=now+5_000_000_000,expires_ns=now+10_000_000_000)
                        if failure=='wrong-ready':ready['event']=19
                        trace.append('ready');return [json.dumps(ready)],''
                    trace.append('checked');return [json.dumps({'stage':'ssap_event_checked_reply'})],''
                def send(owner,item,command,prefix):
                    self.assertTrue(any(isinstance(x,tuple)and x[0]=='peer'and x[1].startswith('check ')for x in trace));self.assertIn('ready',trace)
                    trace.append('send');return dict(start_monotonic_ns=time.monotonic_ns())
                def wait_end(child,timeout):child.returncode=1 if failure=='bad-exit'and child is active.get('child')else 0
                with patch.multiple(gate,publisher=publish,observed_process=observe,wait_text=wait,command_receipt=send,wait_output=wait_end,
                        value_snapshot=lambda *a,**kw:trace.append('readback'),await_removed=lambda *a:{},tool_records=lambda:{}),patch('ws73_channel_socket.credentials',return_value={}):
                    if failure:
                        with self.assertRaises(CaptureError):gate.execute(run,row)
                        self.assertNotIn('ssap_event_delivery_status',row)
                        self.assertTrue(row['ssap_event_delivery_cases'][0]['cases'][0]['application']['error_fixture_retained'])
                        if failure in ('missing-ready','wrong-ready'):self.assertNotIn('send',trace)
                    else:
                        gate.execute(run,row);self.assertEqual(row['ssap_event_delivery_status'],gate.PENDING)
                        self.assertEqual(trace.count('send'),4);self.assertEqual(trace.count('readback'),4)
                        self.assertEqual([x['publisher_api']for x in row['ssap_event_delivery_cases']],['c','python'])

    def test_all_existing_runner_entrypoints_wired(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh','ws73_channel_socket.py'):
            self.assertIn('ssap_event_delivery',(root/name).read_text(),name)
        source=(root/'ws73_target.py').read_text()
        self.assertIn("HERE/'ws73_ssap_event_delivery.py'",source)
        self.assertNotIn("HERE/'ws73_ssap_event_delivery.py','ws73_ssap_event_delivery.py'",source)

if __name__=='__main__':unittest.main()
