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


def summary():
    rows=[]
    for phase in (0,1):
        row,matched,packets=fixture(phase);items,credit=method.corroborate(row,matched)
        if packets:raise AssertionError('unconsumed fixture wire')
        rows.append(dict(phase=phase,owners=row['owners'],ssap_method_providers=items))
        if credit!={0:8,1:8}:raise AssertionError('actual TXs counted once, not both legs')
    return dict(proofs=rows)


class MethodProviderEvidence(unittest.TestCase):
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
                d=dict(token=ordinal,request=ordinal,index=target['owner']['index'],generation=target['owner']['generation'],lifetime=target['object']['lifetime'],handle=target['object']['handle'],epoch=1,method=17,deadline_ns=now+4_900_000_000)
                active['text'].append(f'SsapMethodProviderPrompt: token=p{d["token"]} request={d["request"]} index={d["index"]} generation={d["generation"]} lifetime={d["lifetime"]} handle={d["handle"]} epoch=1 security=0 local_tcid=10 remote_tcid=10 pi=0 method=17 deadline_ns={d["deadline_ns"]} operation=19 arguments={arguments} maximum_result_bytes=2045; answer \'provide p{d["token"]} HEX\' (\'-\' for empty) or \'provider-error p{d["token"]} AF..FF\'')
                app={};after_start(app,deadline);return app
            def commands(run,row,calls,**kw):
                entry,args,expected=calls[0];return [call(run,row,entry,args,expected,**kw)]
            with tempfile.TemporaryDirectory() as directory:
                run=SimpleNamespace(output=Path(directory),args=SimpleNamespace(slctl='slctl'),save=lambda:None,command=lambda *a,**kw:{})
                with patch('ws73_ssap_owned.publisher',publisher),patch('ws73_ssap_owned.wait_text',wait_text),\
                     patch('ws73_ssap_owned.wait_output',lambda *a:0),patch('ws73_ssap_owned.await_removed',lambda *a:{}),\
                     patch('ws73_ssap_update_delivery.tool_records',lambda:{}),\
                     patch('ws73_application_client.ssap_error_command',call),patch('ws73_application_client.ssap_commands',commands):
                    if corrupt:
                        with self.assertRaises(CaptureError):method.execute(run,row)
                        self.assertEqual(processes[0].stdin.getvalue(),'provider\n')
                    else:
                        method.execute(run,row)
                        self.assertEqual(row['ssap_method_provider_status'],method.PENDING)
                        self.assertEqual(len(calls),6)
                        for p in processes:
                            self.assertIn('provider-error p1 FF\n',p.stdin.getvalue())
                            self.assertIn('provide p2 -\n',p.stdin.getvalue())
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
        method.validate_rows(rows,True)

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
