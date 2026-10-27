# SPDX-License-Identifier: GPL-2.0-only
"""Literal packet/receipt fixtures exercise the actual method corroborator.

No hardware or successful verifier stub. Existing READ timing/identity fixture
is reused, but method wire bytes and signatures are independently specified.
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
import time

from ws73_capture import CaptureError
import ws73_ssap_method_provider as method
from test_ws73_ssap_read_provider import fixture_v2


def fixture(phase=0):
    row,_,packets=fixture_v2(phase)
    for k in list(row):
        if k.startswith('ssap_read_provider_'):row[k.replace('ssap_read_provider_','ssap_method_provider_')]=row.pop(k)
    row['ssap_method_provider_version']=1
    for item in row['ssap_method_provider_cases']:
        h=item['handle'];item.update(entry_kind='method',method_access=4,result=item.pop('dynamic_value'))
        item.pop('operations');item.pop('bytes')
        item['args']=['slctl','--adapter',row['owners'][item['target']]['owner']['path'],'ssap-serve-method',item['service'],item['uuid'],'4','allow']
        lines=[f'SsapOwnedMethod: start={item["start"]} end={item["end"]} method={h}; local registration only',
               f'SsapMethodProviderBound: handle={h}; independent application result, no rebind or fallback']
        windows=[]
        for ordinal,step in enumerate(item['steps']):
            arguments=hashlib.sha256(f'{phase}/{item["sender"]}/{ordinal}/arguments'.encode()).hexdigest()
            step['arguments']=arguments;app=step.pop('read');step['request']=app
            app['ssap_operation']='ssap-call-method';app['ssap_arguments']=arguments
            app['args']=['ssap-call-method' if a=='ssap-read' else a for a in app['args']]+[arguments]
            if ordinal==0:app['ssap_proposed']=arguments
            else:app['stdout']=app['stdout'].replace('operation=ssap-read','operation=ssap-call-method')
            d=step['callback']['prompt'];d['method']=d.pop('property');d.pop('maximum_bytes')
            d.update(arguments=arguments,operation=19,maximum_result_bytes=2045)
            lines.append(f'SsapAuthorizationDecision: request={d["request"]} property={h} data_type=3 write=true security=0 approved=true; local policy only')
            lines.append(f'SsapMethodProviderPrompt: token=p{d["token"]} request={d["request"]} index={d["index"]} generation={d["generation"]} lifetime={d["lifetime"]} handle={d["handle"]} epoch={d["epoch"]} security=0 local_tcid=10 remote_tcid=10 pi=0 method={h} deadline_ns={d["deadline_ns"]} operation=19 arguments={arguments} maximum_result_bytes=2045; answer \'provide p{d["token"]} HEX\' (\'-\' for empty) or \'provider-error p{d["token"]} AF..FF\'')
            value=b'' if ordinal<2 else bytes.fromhex(item['result'])
            lines.append(f'SsapMethodProviderResult: request={d["request"]} method={h} status={255 if ordinal==0 else 0} bytes={len(value)}; application response only')
            request=b'\x13\x03'+h.to_bytes(2,'little')+bytes.fromhex(arguments)
            response=b'\x01\0\x13'+h.to_bytes(2,'little')+b'\xff' if ordinal==0 else b'\x14\x03'+value
            windows.append((app,request,response))
        removed=item.pop('retired_read');item['retired_request']=removed
        removed['args']=['slctl','--adapter',row['owners'][item['sender']]['owner']['path'],'ssap-call-method',row['owners'][item['sender']]['object']['path'],str(h),item['steps'][0]['arguments'],'0']
        removed['stderr']='peer method protocol error 4'
        windows.append((removed,windows[0][1],b'\x01\0\x13'+h.to_bytes(2,'little')+b'\x04'))
        item['stdout']='\n'.join(lines)+'\n';item['captured_bytes']['stdout']=len(item['stdout'].encode())
        for window,request,response in windows:
            for p in packets:
                if not window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']:continue
                original=bytes.fromhex(p['data'])[4:]
                pdu=request if original[:2]==b'\x08\x03' else response
                data=(b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu).hex()
                p['data']=data
                for f in p['fragments']:f['data']=data
    def matched(owner,direction,frame,window):
        key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
        found=[p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data'))==key and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1:raise CaptureError('one exact independent fixture packet required')
        packets.remove(found[0]);return found[0]
    return row,matched,packets


def fixture_v2_command(phase=0):
    from ws73_ssap_command import command_arguments
    from ws73_application_client import application_environment
    from test_ws73_ssap_command import credentials, output
    row,matched,packets=fixture(phase)
    row['ssap_method_provider_version']=2
    row['start_wall_ns']=min(i['start_wall_ns'] for i in row['ssap_method_provider_cases'])
    row['end_wall_ns']=max(i['end_wall_ns'] for i in row['ssap_method_provider_cases'])
    record=max(p['record'] for p in packets)+1
    for item in row['ssap_method_provider_cases']:
        source,target=row['owners'][item['sender']],row['owners'][item['target']]
        previous=item['steps'][-1];base=previous['request']['end_wall_ns']+1_000_000
        for ordinal,mode in enumerate(('command-error-ff','command-accepted'),3):
            start=base+(ordinal-3)*3_000_000;api='c' if (phase+item['sender'])%2==0 else 'python'
            arguments=hashlib.sha256(f'{phase}/{item["sender"]}/{ordinal}/command'.encode()).hexdigest()
            d=copy.deepcopy(previous['callback']['prompt'])
            d.update(token=ordinal+1,request=previous['callback']['prompt']['request']+ordinal-2,
                     deadline_ns=start+4_900_000_000,operation=18,maximum_result_bytes=0,arguments=arguments)
            typed=dict(mode='ssap-method-command',schema_version=1,method='CallSsapMethodCommand')
            barrier=dict(stage='ssap_command_start_barrier',api=api,client_closed=True,deadline_ns=start+5_000_000_000,**typed)
            receipt=dict(api=api,handle=item['handle'],value=arguments,minimum=0,admission_only=True,
                         peer_delivery_confirmed=False,deadline_ns=barrier['deadline_ns'],call_ns=start+20_000,returned_ns=start+90_000,**typed)
            app=dict(api=api,args=command_arguments(api,source,item['handle'],arguments,mode='ssap-method-command'),
                     environment=application_environment(),credentials=credentials(),exit=0,stderr='',
                     stdout=json.dumps(barrier)+'\nSSAP_COMMAND_ADMITTED: '+json.dumps(receipt)+'\n',
                     start_wall_ns=start,end_wall_ns=start+100_000,barrier_wall_ns=start+1,release_wall_ns=start+2,
                     start_monotonic_ns=start,barrier_monotonic_ns=start+1,release_monotonic_ns=start+2)
            output(app)
            callback=dict(prompt=d,publisher_pid=item['pid'],observed_wall_ns=start+200_000,observed_monotonic_ns=start+200_000,
                          reply_before_wall_ns=start+300_000,reply_before_monotonic_ns=start+300_000,
                          replied_wall_ns=start+310_000,replied_monotonic_ns=start+310_000,supervisor_deadline_ns=start+7_000_000_000)
            answer=f'provider-error p{d["token"]} FF' if ordinal==3 else f'provide p{d["token"]} -'
            item['steps'].append(dict(mode=mode,arguments=arguments,request=app,callback=callback,reply_command=answer,
                api=api,handle=item['handle'],value=arguments,sequence=phase*4+item['sender']*2+ordinal-3,
                processed_wall_ns=start+400_000,processed_monotonic_ns=start+400_000))
            item['stdout']+=f'SsapAuthorizationDecision: request={d["request"]} property={item["handle"]} data_type=3 write=true security=0 approved=true; local policy only\n'
            item['stdout']+=f'SsapMethodProviderPrompt: token=p{d["token"]} request={d["request"]} index={d["index"]} generation={d["generation"]} lifetime={d["lifetime"]} handle={d["handle"]} epoch={d["epoch"]} security=0 local_tcid=10 remote_tcid=10 pi=0 method={item["handle"]} deadline_ns={d["deadline_ns"]} operation=18 arguments={arguments} maximum_result_bytes=0; answer \'provide p{d["token"]} HEX\' (\'-\' for empty) or \'provider-error p{d["token"]} AF..FF\'\n'
            item['stdout']+=f'SsapMethodProviderResult: request={d["request"]} method={item["handle"]} status={255 if ordinal==3 else 0} bytes=0; application response only\n'
            pdu=b'\x12\x03'+item['handle'].to_bytes(2,'little')+bytes.fromhex(arguments)
            raw=(b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu).hex()
            for owner,direction,stamp in [(source,'out',start+40_000),(target,'in',start+50_000)]:
                packet=dict(bus=owner['owner']['bus'],device=owner['owner']['device'],handle=owner['object']['handle'],
                            direction=direction,data=raw,boundary=0,record=record,wall_ns=stamp)
                record+=1;packet['fragments']=[copy.deepcopy(packet)];packets.append(packet)
        output(item)
    return row,matched,packets


def summary(version=1):
    rows=[]
    for phase in (0,1):
        row,matched,packets=(fixture if version==1 else fixture_v2_command)(phase)
        items,credit=method.corroborate(row,matched,inventory=copy.deepcopy(packets))
        if packets:raise AssertionError('unconsumed fixture wire')
        rows.append(dict(phase=phase,owners=row['owners'],ssap_method_providers=items))
        if credit!={0:8 if version==1 else 10,1:8 if version==1 else 10}:raise AssertionError('actual TXs counted once, not both legs')
    return dict(proofs=rows)


class MethodProviderEvidence(unittest.TestCase):
    def test_v2_commands_keep_v1_request_gate_and_count_only_actual_transmits(self):
        proof=summary(2)
        self.assertTrue(method.valid_summary(proof,version=2))
        self.assertFalse(method.valid_summary(proof,version=1))
        self.assertFalse(method.valid_summary(proof,version=True))
        self.assertTrue(method.valid_summary(summary(),version=1))
        self.assertFalse(method.valid_summary(summary(),version=2))
        for phase in (0,1):
            row,_,_=fixture_v2_command(phase)
            rows=[fixture_v2_command(p)[0] for p in (0,1)]
            method.validate_rows(rows,True)
            for item in row['ssap_method_provider_cases']:
                self.assertEqual(len(item['steps']),5)
                self.assertEqual([s['callback']['prompt']['operation'] for s in item['steps']],[19,19,19,18,18])

    def test_v2_needs_raw_inventory_not_just_successful_positive_pairs(self):
        row,matched,_=fixture_v2_command()
        with self.assertRaises(CaptureError):method.corroborate(row,matched)
        for opcode in (18,19,20,1):
            row,matched,packets=fixture_v2_command()
            item=row['ssap_method_provider_cases'][0];step=item['steps'][3]
            p=copy.deepcopy(packets[0]);p['wall_ns']=step['processed_wall_ns']+1
            p['record']=5000;p['data']='0a000600'+bytes([opcode,0,18,17,0,255]).hex()
            p['fragments']=[{k:v for k,v in p.items() if k!='fragments'}];packets.append(p)
            with self.subTest(opcode=opcode),self.assertRaises(CaptureError):
                method.corroborate(row,matched,inventory=copy.deepcopy(packets))

    def test_v2_context_effect_receipt_and_original_deadline_fail_closed(self):
        for mutation in ('request-opcode','nonempty-result','missing-result','admission-as-delivery','late-processing','old-token','wrong-arguments','no-command','wrong-rpc'):
            row,matched,packets=fixture_v2_command();item=row['ssap_method_provider_cases'][0];step=item['steps'][3]
            if mutation=='request-opcode':item['stdout']=item['stdout'].replace('operation=18','operation=19',1)
            elif mutation=='nonempty-result':
                key=f'SsapMethodProviderResult: request={step["callback"]["prompt"]["request"]} method={item["handle"]} status=255 bytes='
                item['stdout']=item['stdout'].replace(key+'0;',key+'1;',1)
            elif mutation=='missing-result':
                line=f'SsapMethodProviderResult: request={step["callback"]["prompt"]["request"]} '
                item['stdout']='\n'.join(l for l in item['stdout'].splitlines() if not l.startswith(line))+'\n'
            elif mutation=='admission-as-delivery':step['request']['stdout']=step['request']['stdout'].replace('"peer_delivery_confirmed": false','"peer_delivery_confirmed": true')
            elif mutation=='late-processing':step['processed_monotonic_ns']=step['callback']['prompt']['deadline_ns']
            elif mutation=='old-token':step['callback']['prompt']['token']=1
            elif mutation=='wrong-arguments':step['arguments']='00'*32
            elif mutation=='no-command':item['steps'].pop()
            else:step['request']['args'][step['request']['args'].index('ssap-method-command')]='ssap-command'
            from test_ws73_ssap_command import output
            output(item);output(step['request'])
            with self.subTest(mutation=mutation),self.assertRaises((CaptureError,KeyError,ValueError)):
                method.corroborate(row,matched,inventory=copy.deepcopy(packets))

    def test_v2_saved_inventory_and_version_cannot_be_missing_or_upgraded(self):
        original=summary(2)
        for mutation in ('missing','extra','wrong-packet','wrong-version','mixed-version'):
            proof=copy.deepcopy(original);item=proof['proofs'][0]['ssap_method_providers'][0]
            if mutation=='missing':item.pop('command_window_packets')
            elif mutation=='extra':item['command_window_packets'].append(copy.deepcopy(item['command_window_packets'][0]))
            elif mutation=='wrong-packet':item['command_window_packets'][0]['data']='00'
            elif mutation=='wrong-version':item['context']['ssap_method_provider_version']=1
            else:proof['proofs'][1]=summary()['proofs'][1]
            with self.subTest(mutation=mutation):self.assertFalse(method.valid_summary(proof))
        record=dict(ssap_method_provider_requested=True,ssap_method_provider_version=2,
            ssap_method_provider_acceptance=True,ssap_owned_requested=True,ssap_owned_acceptance=True,
            ordinary_channel_socket_acceptance=True,status='PASSTHROUGH_SUPPORT_PASS',
            qemu_args=[method.TOKEN+' ws73.ssap_owned=1'],qemu_exit=0,channel_socket_corroboration=original)
        self.assertTrue(method.valid_manifest(record))
        record['channel_socket_corroboration']=summary()
        self.assertFalse(method.valid_manifest(record))

    def test_extra_method_packets_are_rejected_after_evidence_consumption(self):
        from ws73_channel_socket import reject_unattributed_ssap
        row,_,packets=fixture_v2_command()
        for opcode in (1,18,19,20,18|128):
            p=copy.deepcopy(packets[0]);p['data']='0a000200'+bytes([opcode,3]).hex()
            with self.subTest(opcode=opcode),self.assertRaises(CaptureError):reject_unattributed_ssap(row,[p])

    def test_executor_checks_actual_callback_arguments_before_answering(self):
        # Only process/SDK I/O is a fixture here. The production executor and
        # prompt/context/deadline checks run; no fixture return is a verdict.
        for corrupt in (False,True):
            template,_,_=fixture();row={k:copy.deepcopy(v) for k,v in template.items() if not k.startswith('ssap_method_provider_')}
            processes=[];active={};calls=[]
            @contextmanager
            def publisher(run,row,sender,policy,**kw):
                self.assertEqual(kw['method_access'],4)
                proc=SimpleNamespace(pid=200+sender,stdin=io.StringIO(),returncode=0)
                item=dict(sender=sender,target=1-sender,handle=17,start=16,end=17,pid=proc.pid,output_files=['out','err'])
                row['ssap_method_provider_cases'].append(item);active.update(proc=proc,item=item,text=[])
                processes.append(proc);yield proc,item
            def wait_text(proc,path,pattern,deadline,**kw):
                if pattern!=method.PROMPT:return ['17'],''
                return [],'\n'.join(active['text'])+'\n'
            def call(run,row,entry,args,expected,*,api,after_start,**kw):
                calls.append(args);item=active['item'];target=row['owners'][item['target']];ordinal=len(item['steps'])
                now=time.monotonic_ns();deadline=now+7_000_000_000
                arguments='00'*32 if corrupt else args[3]
                operation=19 if ordinal<=3 else 18
                maximum=2045 if ordinal<=3 else 0
                d=dict(token=ordinal,request=ordinal,index=target['owner']['index'],generation=target['owner']['generation'],lifetime=target['object']['lifetime'],handle=target['object']['handle'],epoch=1,method=17,deadline_ns=now+4_900_000_000)
                active['text'].append(f'SsapMethodProviderPrompt: token=p{d["token"]} request={d["request"]} index={d["index"]} generation={d["generation"]} lifetime={d["lifetime"]} handle={d["handle"]} epoch=1 security=0 local_tcid=10 remote_tcid=10 pi=0 method=17 deadline_ns={d["deadline_ns"]} operation={operation} arguments={arguments} maximum_result_bytes={maximum}; answer \'provide p{d["token"]} HEX\' (\'-\' for empty) or \'provider-error p{d["token"]} AF..FF\'')
                app={};after_start(app,deadline);return app
            def command(run,row,case,entry,**kw):
                self.assertEqual(kw,dict(mode='ssap-method-command',label='method-command'))
                case['command']=call(run,row,entry,['ssap-method-command',entry['object']['path'],str(case['handle']),case['value']],None,
                    api=case['api'],after_start=lambda app,deadline:app.update(start_monotonic_ns=deadline-7_000_000_000))
            def commands(run,row,calls,**kw):
                entry,args,expected=calls[0];return [call(run,row,entry,args,expected,**kw)]
            with tempfile.TemporaryDirectory() as directory:
                run=SimpleNamespace(output=Path(directory),args=SimpleNamespace(slctl='slctl'),save=lambda:None,command=lambda *a,**kw:{})
                with patch('ws73_ssap_owned.publisher',publisher),patch('ws73_ssap_owned.wait_text',wait_text),\
                     patch('ws73_ssap_owned.wait_output',lambda *a:0),patch('ws73_ssap_owned.await_removed',lambda *a:{}),\
                     patch('ws73_ssap_update_delivery.tool_records',lambda:{}),\
                     patch('ws73_ssap_command.execute_command',command),patch('ws73_application_client.ssap_error_command',call),patch('ws73_application_client.ssap_commands',commands):
                    if corrupt:
                        with self.assertRaises(CaptureError):method.execute(run,row)
                        self.assertEqual(processes[0].stdin.getvalue(),'provider\n')
                    else:
                        method.execute(run,row)
                        self.assertEqual(row['ssap_method_provider_status'],method.PENDING)
                        self.assertEqual(len(calls),10)
                        for p in processes:
                            self.assertIn('provider-error p1 FF\n',p.stdin.getvalue())
                            self.assertIn('provide p2 -\n',p.stdin.getvalue())
                            self.assertIn('provider-error p4 FF\n',p.stdin.getvalue())
                            self.assertIn('provide p5 -\n',p.stdin.getvalue())
                            self.assertTrue(p.stdin.getvalue().endswith('quit\n'))

    def test_full_two_role_two_direction_original_wire_and_independent_result(self):
        proof=summary();self.assertTrue(method.valid_summary(proof))
        self.assertTrue(method.valid_manifest(dict(ssap_method_provider_requested=True,ssap_method_provider_version=1,
            ssap_method_provider_acceptance=True,ssap_owned_requested=True,ssap_owned_acceptance=True,
            ordinary_channel_socket_acceptance=True,status='PASSTHROUGH_SUPPORT_PASS',qemu_args=[method.TOKEN+' ws73.ssap_owned=1'],qemu_exit=0,channel_socket_corroboration=proof)))
        for phase in (0,1):
            row,_,_=fixture(phase)
            if phase==0:rows=[row]
            else:rows.append(row)
        method.validate_rows(rows,True,version=1)

    def test_actual_case_rejects_forged_identity_parameters_result_and_deadlines(self):
        changes={
            'wrong-args':lambda i:i['steps'][2].update(arguments='00'*32),
            'echo':lambda i:i.update(result=i['steps'][2]['arguments']),
            'wrong-input-token':lambda i:i['steps'][2].update(reply_command='provide p999 '+i['result']),
            'wrong-sdk':lambda i:i['steps'][2]['request'].update(ssap_arguments='00'*32),
            'wrong-sdk-result':lambda i:i['steps'][2]['request'].update(ssap_expected='00'*32),
            'missing-step':lambda i:i['steps'].pop(),
            'reused-args':lambda i:i['steps'][1].update(arguments=i['steps'][0]['arguments']),
            'wrong-lifetime':lambda i:i['steps'][0]['callback']['prompt'].update(lifetime=999),
            'late':lambda i:i['steps'][2]['callback'].update(replied_monotonic_ns=i['steps'][2]['callback']['prompt']['deadline_ns']),
            'renewed-supervisor':lambda i:i['steps'][2]['callback'].update(supervisor_deadline_ns=i['steps'][2]['callback']['supervisor_deadline_ns']+1),
            'wrong-pid':lambda i:i['steps'][0]['callback'].update(publisher_pid=888),
            'privileged':lambda i:i['credentials'].update(uids=[0]*4),
            'failed-owner':lambda i:i.update(exit=1),
            'incomplete-output':lambda i:i['output_collection'].update(complete=False),
            'old-registration':lambda i:i.update(entry_kind='property'),
            'wrong-grant':lambda i:i.update(method_access=0),
            'withdraw-failed':lambda i:i['cleanup'].update(stdout='SsapLocalServices: [[16,17]]\n'),
            'retired-success':lambda i:i['retired_request'].update(exit=0),
        }
        for name,change in changes.items():
            row,matched,_=fixture();change(row['ssap_method_provider_cases'][0])
            with self.subTest(name=name),self.assertRaises((CaptureError,KeyError,ValueError)):
                method.corroborate(row,matched)

    def test_missing_corrupt_cross_device_late_and_duplicate_usb_cannot_pass(self):
        for mutation in ('missing','duplicate','payload','endpoint','fragment-endpoint','late','response-before-answer'):
            row,matched,packets=fixture()
            if mutation=='missing':packets.pop(1)
            elif mutation=='duplicate':packets.append(copy.deepcopy(packets[0]))
            elif mutation=='payload':packets[1]['data']='00'+packets[1]['data'][2:]
            elif mutation=='endpoint':packets[1]['device']=999
            elif mutation=='fragment-endpoint':packets[1]['fragments'][0]['device']=999
            elif mutation=='late':packets[1]['wall_ns']=1
            else:
                packet=packets[2];stamp=row['ssap_method_provider_cases'][0]['steps'][0]['callback']['reply_before_wall_ns']-1
                packet['wall_ns']=stamp;packet['fragments'][0]['wall_ns']=stamp
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):method.corroborate(row,matched)

    def test_saved_summary_rebuilds_case_and_every_packet(self):
        original=summary()
        for kind in ('missing-rx','old-context','wrong-proof','missing-phase','bool-version','missing-wire','capture-drop'):
            proof=copy.deepcopy(original);item=proof['proofs'][0]['ssap_method_providers'][0]
            if kind=='missing-rx':item['wire'][0].pop('rx')
            elif kind=='old-context':item['context']['owners'][0]['object']['lifetime']+=1
            elif kind=='wrong-proof':item['result']='00'*32
            elif kind=='missing-phase':proof['proofs'].pop()
            elif kind=='bool-version':item['version']=True
            elif kind=='missing-wire':item['wire'].pop()
            else:item['case']['captured_bytes']['stdout']-=1
            with self.subTest(kind=kind):self.assertFalse(method.valid_summary(proof))

    def test_selectors_and_manifest_refuse_missing_unrequested_or_partial_cases(self):
        args=SimpleNamespace(ssap_method_provider_verify=True,ssap_owned_verify=True,channel_socket_verify=True,passthrough=True)
        self.assertTrue(method.requested(args));self.assertTrue(method.boot_requested([method.TOKEN,'ws73.ssap_owned=1']))
        for key,value in [('ssap_owned_verify',False),('ssap_read_provider_verify',True),('channel_socket_rounds',5),('ssap_method_provider_verify',1)]:
            bad=copy.copy(args);setattr(bad,key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):method.requested(bad)
        for tokens in ([method.TOKEN],[method.TOKEN,method.TOKEN,'ws73.ssap_owned=1'],['ws73.ssap_method_provider=0']):
            with self.assertRaises(ValueError):method.boot_requested(tokens)
        rows=[fixture(phase)[0] for phase in (0,1)]
        with self.assertRaises(CaptureError):method.validate_rows(rows,False)
        with self.assertRaises(CaptureError):method.validate_rows(rows[:1],True)
        self.assertFalse(method.valid_manifest(dict(ssap_method_provider_requested=True)))
        self.assertFalse(method.valid_manifest(dict(channel_socket_corroboration=summary())))

    def test_manifest_requires_original_boot_baseline_and_complete_vm_exit(self):
        original=dict(ssap_method_provider_requested=True,ssap_method_provider_version=1,ssap_method_provider_acceptance=True,
            ssap_owned_requested=True,ssap_owned_acceptance=True,ordinary_channel_socket_acceptance=True,
            status='PASSTHROUGH_SUPPORT_PASS',qemu_args=[method.TOKEN+' ws73.ssap_owned=1'],qemu_exit=0,channel_socket_corroboration=summary())
        for key,value in [('qemu_args',[]),('qemu_exit',True),('qemu_exit',1),('status','FAIL'),('ssap_owned_acceptance',False),('ordinary_channel_socket_acceptance',False),('ssap_method_provider_acceptance',False),('ssap_method_provider_version',True),('ssap_method_provider_requested',False)]:
            bad=copy.deepcopy(original);bad[key]=value
            with self.subTest(key=key,value=value):self.assertFalse(method.valid_manifest(bad))

    def test_source_identity_includes_new_module_and_existing_consumers(self):
        here=Path(__file__).parents[1]
        names=('ws73_ssap_read_provider.py','ws73_ssap_owned.py','ws73_application_client.py','ws73_ssap_value.py',
               'ws73_ssap_command.py','ws73_ssap_update_delivery.py','ws73_channel_socket.py','ws73_target_control.py',
               'ws73_target_guest.py','ws73_target_init.sh','ws73_ssap_method_provider.py')
        record=lambda p:dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        package=dict(inputs=[record(here/n) for n in names],application_client_tools=dict(sources=[record(here/'testing/application_client'/n) for n in ('client.c','client.py')]))
        method.validate_inputs(package)
        for mode in ('missing','hash','duplicate','old-consumer'):
            bad=copy.deepcopy(package)
            if mode=='missing':bad['inputs'].pop()
            elif mode=='hash':bad['inputs'][-1]['sha256']='0'*64
            elif mode=='duplicate':bad['inputs'].append(bad['inputs'][-1])
            else:bad['application_client_tools']['sources'][0]['sha256']='0'*64
            with self.subTest(mode=mode),self.assertRaises((CaptureError,ValueError)):method.validate_inputs(bad)


if __name__=='__main__':unittest.main()
