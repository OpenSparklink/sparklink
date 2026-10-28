# SPDX-License-Identifier: GPL-2.0-only
"""Offline evidence fixtures; not a real kernel, firmware or RF qualification.

Uses the existing recorded-shape receipts, production ACB reassembler and
independently spelled WRITE bytes. No gate encoder builds its expected input.
"""
import copy
import errno
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
import subprocess
import sys

from ws73_application_client import owned_arguments
from ws73_capture import CaptureError, reassemble_acb
from test_ws73_ssap_sdk_read_provider import fixture as read_fixture, matcher
import ws73_ssap_sdk_write_provider as gate


def transcript(item):
    api=item['publisher_api'];h=item['handle']
    lines=[f'SdkOwnedAPI: api={api} client_closed=true',
           f'SsapOwnedService: start={item["start"]} end={h} property={h}; local registration only',
           'SdkWriteProviderBound: '+json.dumps(item['bound'])]
    for s in item['steps']:
        for prefix,value in [('SdkAuthorizationDecision',s['approval']),('SdkWriteProviderRequest',s['callback']['prompt']),
                             ('SdkWriteProviderReply',s['reply']),('SdkWriteProviderValue',s['application_value'])]:
            lines.append(prefix+': '+json.dumps(value))
    lines.append(f'SdkOwnedRemoved: api={api} start={item["start"]}')
    item['stdout']='\n'.join(lines)+'\n';item['captured_bytes']={'stdout':len(item['stdout'].encode()),'stderr':0}


def fixture(phase=0,version=1):
    row,_,_,_=read_fixture(phase);item=row['ssap_sdk_read_provider_cases'][0]
    records=row['ssap_sdk_read_provider_tools']
    for key in list(row):
        if key.startswith(('ssap_sdk_read_provider','ssap_read_provider')):del row[key]
    records[gate.EXTRA_TOOLS[-1]]=dict(sha256=hashlib.sha256(gate.EXTRA_TOOLS[-1].encode()).hexdigest(),bytes=100)
    row.update({gate.PREFIX+'_required':True,gate.PREFIX+'_version':version,gate.PREFIX+'_tools':records,gate.COLLECTION:[item]})
    if version in (2,3):
        row['ssap_exchange_contract']=2
        row['ssap_receipts']=[copy.deepcopy(row['ssap_receipts'][0]) for _ in row['owners']]
        for owner,receipt in zip(row['owners'],row['ssap_receipts']):
            receipt.update(exit=0,stdout=f"SsapExchangeInfo: index={owner['owner']['index']} generation={owner['owner']['generation']} lifetime={owner['object']['lifetime']} handle={owner['object']['handle']} local_mtu=2042 negotiated_mtu=2042 request=0207fa07010204000000 peer_reply=0307fa07010204000000 peer_request=0207fa07010204000000 response=0307fa07010204000000\n")
    del item['sdk_read_provider_contract_version'];item.update(sdk_write_provider_contract_version=1,operations=6)
    source,target=row['owners'];api=item['publisher_api'];h=item['handle'];path=source['object']['path']
    item['args']=owned_arguments(api,target,item['service'],item['uuid'],item['secret'],'allow',write_provider=True)
    wire=[]
    for n,s in enumerate(item['steps']):
        app=s.pop('read');s['call']=app;s['mode']=gate.scenarios(version)[n][0]
        value=hashlib.shake_256(f'write/{phase}/{n}'.encode()).hexdigest(gate.scenarios(version)[n][1]);s['value']=value
        app['ssap_operation']='ssap-write'
        prefix=app['args'][:1] if app['api']=='c'else app['args'][:2]
        base=prefix+['ssap-error'if n==0 else'ssap',str(source['owner']['index']),str(source['owner']['generation']),path,'ssap-write',str(h)]
        if n==0:
            app['args']=base+['5',value];app['ssap_proposed']=value
        else:
            app['args']=base+[value,value];app['ssap_expected']=value
            app['stdout']=json.dumps(dict(stage='ssap_start_barrier',api=app['api'],client_closed=True))+'\n'+f'SsapPeerValue: operation=ssap-write path={path} handle={h} value={value}\n'
        d=s['callback']['prompt'];del d['maximum_bytes'];d.update(operation=13,data_type=0,offset=0,value_length=len(value)//2,verify=True,value=value)
        s['approval'].update(write=True,value=value)
        s['reply'].update(value=''if n==0 else value,matched_value=True,accepted_value=None if n==0 else value)
        s['reply_command']=f'provider-error p{d["token"]} FF'if n==0 else f'provide p{d["token"]} {value}'
        s['application_value']=dict(api=api,property=h,value=None if n==0 else value,application_memory_only=True)
        after=s['clock_after']['monotonic_after_ns'];s.update(value_before_ns=after+1000,value_after_ns=after+2000,
            value_before_wall_ns=after+1000,value_after_wall_ns=after+2000)
        request=b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+bytes.fromhex(value)
        response=b'\x0e\x07\x01'+h.to_bytes(2,'little')+b'\xff'if n==0 else b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+bytes.fromhex(value)
        if version==3 and n<2:
            from ws73_ssap_command import command_arguments
            start=app['start_wall_ns'];app.update(start_monotonic_ns=start,barrier_wall_ns=start+1000,
                barrier_monotonic_ns=start+1000,release_wall_ns=start+2000,release_monotonic_ns=start+2000,
                end_wall_ns=start+1_500_000,end_monotonic_ns=start+1_500_000,exit=0,stderr='')
            app['args']=command_arguments(app['api'],source,h,value)
            end=start+5_000_000_000
            app['stdout']=json.dumps(dict(stage='ssap_command_start_barrier',api=app['api'],deadline_ns=end,client_closed=True))+'\nSSAP_COMMAND_ADMITTED: '+json.dumps(dict(api=app['api'],handle=h,value=value,minimum=0,admission_only=True,peer_delivery_confirmed=False,deadline_ns=end,call_ns=start+3000,returned_ns=start+1_400_000))+'\n'
            from test_ws73_ssap_command import output
            output(app)
            d.update(operation=12,verify=False);s['reply']['value']='';s['command']=app
            s['callback']['supervisor_deadline_ns']=app['release_monotonic_ns']+7_000_000_000
            request=b'\x0c\x03'+h.to_bytes(2,'little')+b'\0'+bytes.fromhex(value);response=None
            window=dict(start_wall_ns=start,end_wall_ns=s['value_after_wall_ns'])
        else:window=app
        wire.append((window,request,response))
    row['ssap_language_clients']=[s['call']for s in item['steps']if version!=3 or not s['mode'].startswith('command-')]
    wire.append((item['retired_read'],b'\x08\x03'+h.to_bytes(2,'little')+b'\0',b'\x09\x0b\x04\0'))
    transcript(item);capture=dict(acb_packets=[],native_events=[])
    for window,request,response in wire:
        for sender,target_no,pdu in ([(0,1,request)] if response is None else [(0,1,request),(1,0,response)]):
            from ws73_ssap_value import fragment_parts
            fragments=fragment_parts(pdu)if len(pdu)>2042 else[pdu]
            for sequence,fragment in enumerate(fragments):
                frame=b'\x0a\0'+len(fragment).to_bytes(2,'little')+fragment
                for endpoint,direction in [(sender,'out'),(target_no,'in')]:
                    owner=row['owners'][endpoint];at=window['start_wall_ns']+(1_200_000 if sender==0 else 5_000_000)+(100_000 if direction=='in'else 0)+sequence*20000
                    chunk=223 if direction=='out'else 191
                    if version==1:parts=[(1,frame[:29]),(3,frame[29:])]if direction=='in'and len(frame)>29 else[(0,frame)]
                    else:
                        payloads=[frame[i:i+chunk]for i in range(0,len(frame),chunk)]
                        parts=[(0 if len(payloads)==1 else 1 if i==0 else 3 if i==len(payloads)-1 else 2,p)for i,p in enumerate(payloads)]
                    for part,(boundary,payload)in enumerate(parts):
                        capture['acb_packets'].append(dict(bus=owner['owner']['bus'],device=owner['owner']['device'],handle=owner['object']['handle'],
                            direction=direction,data=payload.hex(),boundary=boundary,record=len(capture['acb_packets'])+1,wall_ns=at+part*1000))
    packets=reassemble_acb(capture)
    return row,matcher(packets),packets


def summary():
    rows=[]
    for phase in (0,1):
        row,match,packets=fixture(phase);proof,credit=gate.corroborate(row,match)
        assert not packets and credit=={0:4,1:4}
        rows.append(dict(phase=phase,owners=row['owners'],**{gate.SUMMARY_KEY:proof}))
    return dict(proofs=rows)


def manifest():
    proof=summary();module=proof['proofs'][0][gate.SUMMARY_KEY][0]['tools'][gate.EXTRA_TOOLS[-1]]
    return {gate.PREFIX+'_requested':True,gate.PREFIX+'_version':1,gate.PREFIX+'_acceptance':True,
        gate.PREFIX+'_verifier':dict(path='/fixture/tools/ws73_ssap_sdk_write_provider.py',**module),
        'ssap_owned_acceptance':True,'ordinary_channel_socket_acceptance':True,'status':'PASSTHROUGH_SUPPORT_PASS','qemu_exit':0,
        'qemu_args':[gate.TOKEN+' ws73.ssap_owned=1'],'channel_socket_corroboration':proof}


class WriteEvidence(unittest.TestCase):
    def test_both_roles_and_split_rx_do_not_double_tx_credit(self):
        proof=summary();self.assertTrue(gate.valid_summary(proof));self.assertTrue(gate.valid_manifest(manifest()))
        self.assertEqual([(p[gate.SUMMARY_KEY][0]['provider_api'],p[gate.SUMMARY_KEY][0]['peer_api'])for p in proof['proofs']],[('c','python'),('python','c')])
        self.assertTrue(gate.valid_manifest({}))

    def test_explicit_selector_and_original_baseline(self):
        args=dict(ssap_sdk_write_provider_verify=True,connection_advertising='negotiable-t',passthrough=True,ssap_owned_verify=True,channel_socket_verify=True,channel_socket_rounds=4,channel_socket_bytes=61)
        self.assertTrue(gate.requested(SimpleNamespace(**args)))
        for key,value in [('connection_advertising',None),('connection_advertising','fixed-t'),('ssap_sdk_write_provider_verify',1),('ssap_owned_verify',False),('passthrough',False),('ssap_read_provider_verify',True),('ssap_provider_unregister_verify',True),('channel_socket_bytes',62),('ssap_value_lengths_verify',True)]:
            with self.subTest(key=key),self.assertRaises(CaptureError):gate.requested(SimpleNamespace(**dict(args,**{key:value})))
        for tokens in ([gate.TOKEN],[gate.TOKEN,gate.TOKEN,'ws73.ssap_owned=1'],['ws73.ssap_sdk_write_provider=0'],[gate.TOKEN,'ws73.ssap_owned=1','ws73.ssap_read_provider=1']):
            with self.assertRaises(CaptureError):gate.boot_requested(tokens)
        gate.validate_rows([fixture(p)[0]for p in(0,1)],True)
        rows=[fixture(p)[0]for p in(0,1)];rows[1]['owners']=copy.deepcopy(rows[0]['owners'])
        with self.assertRaises(CaptureError):gate.validate_rows(rows,True)
        with self.assertRaises(CaptureError):gate.validate_rows([fixture()[0]],False)

    def test_bad_context_reply_and_application_value(self):
        changes=[('prompt',k,v)for k,v in [('lifetime',99),('epoch',42),('handle',99),('local_tcid',11),('operation',8),('verify',False),('value','aa'),('value_length',31),('deadline_ns',1)]]
        changes += [('reply',k,v)for k,v in [('result',-1),('accepted_value','aa'),('matched_value',False),('api_called',False),('value','aa'),('current_token',99)]]
        changes += [('approval','write',False),('application_value','value','aa')]
        for part,key,value in changes:
            with self.subTest(part=part,key=key):
                row,match,_=fixture();item=row[gate.COLLECTION][0];step=item['steps'][0]
                obj=step['callback']['prompt']if part=='prompt'else step[part];obj[key]=value;transcript(item)
                with self.assertRaises(CaptureError):gate.corroborate(row,match)

    def test_capture_missing_duplicate_payload_and_time(self):
        for change in ('missing-tx','missing-rx','duplicate','payload','wrong-endpoint','before-call','late-response','wrong-clock'):
            with self.subTest(change=change):
                row,match,packets=fixture();step=row[gate.COLLECTION][0]['steps'][0]
                if change=='missing-tx':packets.pop(0)
                elif change=='missing-rx':packets.pop(1)
                elif change=='duplicate':packets.append(copy.deepcopy(packets[0]))
                elif change=='payload':packets[2]['data']=packets[2]['data'][:-2]+'af'
                elif change=='wrong-endpoint':packets[0]['fragments'][0]['device']+=1
                else:
                    ps=packets[:2]if change=='before-call'else packets[2:4]
                    at=step['call']['start_wall_ns'] if change=='before-call'else step['call']['end_wall_ns']-1000
                    for p in ps:
                        p['wall_ns']=at+(1 if change=='wrong-clock'else 0)
                        for f in p['fragments']:f['wall_ns']=p['wall_ns']
                with self.assertRaises(CaptureError):gate.corroborate(row,match)

    def test_incomplete_or_forged_summary_is_not_qualification(self):
        for field,value in [(gate.PREFIX+'_requested',1),(gate.PREFIX+'_acceptance',False),(gate.PREFIX+'_version',True),('ssap_owned_acceptance',False),('ordinary_channel_socket_acceptance',False),('qemu_args',[]),('qemu_exit',True),('qemu_exit',1),('status','SKIP')]:
            r=manifest();r[field]=value;self.assertFalse(gate.valid_manifest(r),field)
        for change in ('missing-role','same-role','missing-leg','hash','value','duplicate-json','truncated-output','bad-exit'):
            r=manifest();proof=r['channel_socket_corroboration'];case=proof['proofs'][0][gate.SUMMARY_KEY][0]
            if change=='missing-role':proof['proofs'].pop()
            elif change=='same-role':proof['proofs'][1]=copy.deepcopy(proof['proofs'][0])
            elif change=='missing-leg':case['wire'].pop()
            elif change=='hash':r[gate.PREFIX+'_verifier']['sha256']='0'*64
            elif change=='value':case['case']['steps'][1]['value']='00'*31
            elif change=='duplicate-json':case['case']['stdout']=case['case']['stdout'].replace('"operation": 13','"operation": 8, "operation": 13')
            elif change=='truncated-output':case['case']['output_collection']['complete']=False
            elif change=='bad-exit':case['case']['exit']=1
            self.assertFalse(gate.valid_manifest(r),change)

    def test_exact_tools_and_input_dependency_closure(self):
        from ws73_ssap_update_delivery import TOOLS
        here=Path(gate.__file__).resolve().parent
        def file_record(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        inputs=[file_record(p)for p in here.iterdir()if p.is_file()]
        package=dict(inputs=inputs,application_client_tools=dict(sources=[file_record(here/'testing/application_client'/name)for name in ('client.c','client.py')]))
        gate.validate_inputs(package)
        for name in ('ws73_ssap_sdk_write_provider.py','ws73_ssap_read_provider.py','ws73_ssap_sdk_read_provider.py','ws73_target_control.py','ws73_target_init.sh','ws73_ssap_initialization.py'):
            bad=copy.deepcopy(package);bad['inputs']=[x for x in bad['inputs']if Path(x['path']).name!=name]
            with self.subTest(missing=name),self.assertRaises(ValueError):gate.validate_inputs(bad)
        bad=copy.deepcopy(package);bad['application_client_tools']['sources'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):gate.validate_inputs(bad)
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);manifest=[]
            for name in set(TOOLS)|set(gate.EXTRA_TOOLS):
                p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode());manifest.append(file_record(p))
            records=gate.tool_records(root);gate.validate_tools(records,root,manifest)
            for name in gate.EXTRA_TOOLS:
                bad=copy.deepcopy(records);bad[name]['sha256']='0'*64
                with self.subTest(stale=name),self.assertRaises(CaptureError):gate.validate_tools(bad,root,manifest)
            with self.assertRaises(CaptureError):gate.validate_tools(records,root,manifest[:-1])

    def test_actual_host_and_guest_cli_expose_opt_in(self):
        here=Path(gate.__file__).resolve().parent
        for tool,args in [('ws73_target.py',['run','--help']),('ws73_target_control.py',['--help'])]:
            result=subprocess.run([sys.executable,str(here/tool),*args],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('--ssap-sdk-write-provider-verify',result.stdout)
        # Static consumer wiring only. Actual VM execution remains its own gate.
        for tool,symbols in [('ws73_target.py',['sdk_write_provider_requested','sdk_write_provider_rows','sdk_write_provider_tools','valid_sdk_write_provider_manifest']),
                             ('ws73_target_guest.py',['sdk_write_provider_boot','sdk_write_provider_rows']),
                             ('ws73_target_init.sh',['--ssap-sdk-write-provider-verify','ws73_ssap_sdk_write_provider']),
                             ('ws73_channel_socket.py',['sdk_write_provider_execute','sdk_write_provider_corroborate','ssap_sdk_write_providers'])]:
            text=(here/tool).read_text()
            for symbol in symbols:self.assertIn(symbol,text)

    def test_exchanges_require_explicit_matching_request_count(self):
        from ws73_ssap_read_provider import _wire
        row,match,_=fixture()
        with self.assertRaises(CaptureError):_wire(row,row[gate.COLLECTION][0],match,[(None,None,None)],requests=[])




class WriteLengthsEvidence(unittest.TestCase):
    def test_actual_sdk_long_value_receipts_and_two_fragment_capture_replay(self):
        phases=[]
        for phase in (0,1):
            row,match,packets=fixture(phase,2)
            proof,credit=gate.corroborate(row,match)
            self.assertFalse(packets)
            self.assertEqual(credit,{0:23,1:23})
            self.assertEqual([v['application_bytes']for v in proof[0]['outcomes']],[32,2037,2042])
            self.assertEqual([len(gate.physical_packets(leg['tx']))for leg in proof[0]['wire']],[1,1,1,1,2,2,1,1])
            phases.append(dict(phase=phase,owners=row['owners'],**{gate.SUMMARY_KEY:proof}))
        result=dict(proofs=phases)
        self.assertTrue(gate.valid_summary(result,version=2))
        self.assertFalse(gate.valid_summary(result,version=1))
        record=manifest();record['channel_socket_corroboration']=result;record[gate.PREFIX+'_version']=2
        self.assertTrue(gate.valid_manifest(record))
        record[gate.PREFIX+'_version']=1;self.assertFalse(gate.valid_manifest(record))
        gate.validate_rows([fixture(p,2)[0]for p in (0,1)],True)
        old=summary();self.assertFalse(gate.valid_summary(old,version=2))

    def test_long_value_capture_receipt_and_negotiation_negative_controls(self):
        for change in ('missing-last','wrong-sequence','wrong-operation','wrong-order','wrong-endpoint',
                       'wrong-lifetime','late-request','early-response','different-accepted',
                       'different-peer-value','missing-capability','wrong-mtu','short-value'):
            with self.subTest(change=change):
                row,match,packets=fixture(0,2);item=row[gate.COLLECTION][0];step=item['steps'][2]
                long=[p for p in packets if bytes.fromhex(p['data'])[4:5]in(b'\x8d',b'\x8e')]
                if change=='missing-last':packets.remove(long[-1])
                elif change=='wrong-sequence':long[0]['data']=long[0]['data'][:12]+'0300'+long[0]['data'][16:]
                elif change=='wrong-operation':long[0]['data']=long[0]['data'][:10]+'20'+long[0]['data'][12:]
                elif change=='wrong-order':long[2]['fragments'][0]['record']=1
                elif change=='wrong-endpoint':long[0]['fragments'][0]['device']+=1
                elif change=='wrong-lifetime':step['callback']['prompt']['lifetime']+=1;transcript(item)
                elif change=='late-request':
                    for f in long[2]['fragments']:f['wall_ns']=step['callback']['prompt']['observed_wall_ns']+1000
                elif change=='early-response':
                    for f in long[4]['fragments']:f['wall_ns']=step['callback']['reply_before_wall_ns']-1000
                elif change=='different-accepted':step['application_value']['value']='00';transcript(item)
                elif change=='different-peer-value':step['call']['ssap_expected']='00'
                elif change=='missing-capability':row['ssap_receipts'][0]['stdout']=row['ssap_receipts'][0]['stdout'].replace('010204000000','010200000000')
                elif change=='wrong-mtu':row['ssap_receipts'][0]['stdout']=row['ssap_receipts'][0]['stdout'].replace('negotiated_mtu=2042','negotiated_mtu=2041')
                else:step['value']=step['value'][:-2]
                with self.assertRaises((CaptureError,KeyError)):gate.corroborate(row,match)

    def test_valid_ssap_fragment_pipeline_is_not_mistaken_for_time_reversal(self):
        row,match,packets=fixture(0,2)
        # Independently captured first RX may precede the second TX. Keep each
        # physical packet causal and the complete request before app callback.
        for packet in packets:
            if bytes.fromhex(packet['data'])[4:6]in(b'\x8d\x22',b'\x8e\x02'):
                packet['wall_ns']+=200_000
                for fragment in packet['fragments']:fragment['wall_ns']+=200_000
        proof,_=gate.corroborate(row,match)
        self.assertFalse(packets)
        for leg in proof[0]['wire'][4:6]:
            tx,rx=leg['tx']['ssap_fragments'],leg['rx']['ssap_fragments']
            self.assertLess(gate.interval(rx[0])[1],gate.interval(tx[1])[0])

    def test_acb_byte_prefix_pipeline_accepts_overlap_but_rejects_unsent_bytes(self):
        from ws73_ssap_value import stream_causal
        def packet(parts,times):
            return dict(data=b''.join(parts).hex(),fragments=[dict(data=p.hex(),wall_ns=t)for p,t in zip(parts,times)])
        tx=packet([b'abcd',b'efgh',b'ijkl'],[1000,3000,5000])
        rx=packet([b'ab',b'cd',b'efghij',b'kl'],[2000,2500,6000,7000])
        self.assertTrue(stream_causal(tx,rx))
        for change in ('unsent-middle','unsent-tail','wrong-bytes','missing-tail','backward-clock','empty'):
            with self.subTest(change=change):
                bad=copy.deepcopy(rx)
                if change=='unsent-middle':bad['fragments'][2]['wall_ns']=4000
                elif change=='unsent-tail':bad['fragments'][-1]['wall_ns']=4500
                elif change=='wrong-bytes':bad['fragments'][0]['data']='ffff'
                elif change=='missing-tail':bad['fragments'].pop()
                elif change=='backward-clock':bad['fragments'][1]['wall_ns']=1500
                else:bad['fragments'][0]['data']=''
                self.assertFalse(stream_causal(tx,bad))

    def test_invalid_versions_cannot_enable_long_capture_or_upgrade_old_proof(self):
        for version in (True,0,4,None,'2'):
            with self.assertRaises(CaptureError):gate.scenarios(version)
            self.assertFalse(gate.valid_summary(summary(),version=version))


class WriteSetup(unittest.TestCase):
    def test_stopped_beacon_setup_precedes_connection_and_failures_stop_the_gate(self):
        # Coordinator dependencies are explicit fixtures; this checks ordering,
        # not controller Complete, real connection or RF delivery.
        from unittest.mock import patch
        from ws73_target_control import ConnectionControlRun,PassthroughControlRun
        for failed in (False,True):
            run=object.__new__(ConnectionControlRun)
            run.args=SimpleNamespace(ssap_sdk_write_provider_verify=True)
            run.native_controller_return=None;run.data={};run.save=lambda:None
            a,b={'index':0},{'index':1};seen=[]
            def setup(r,phase):
                self.assertIs(r,run);self.assertEqual(phase,dict(caller=a,peer=b))
                seen.append('setup')
                if failed:raise CaptureError('setup failed')
            with patch('ws73_ssap_initialization.restore_beacons',side_effect=setup), \
                 patch('ws73_connection_control.execute',side_effect=lambda *a:seen.append('connect')), \
                 patch('ws73_registry_metadata.execute',side_effect=lambda *a:seen.append('metadata')), \
                 patch.object(PassthroughControlRun,'phase',side_effect=lambda *a:seen.append('baseline')):
                if failed:
                    with self.assertRaisesRegex(CaptureError,'setup failed'):run.phase(a,b,4,'initial')
                else:run.phase(a,b,4,'initial')
            self.assertEqual(seen,['setup']if failed else['setup','connect','metadata','baseline'])


if __name__=='__main__':unittest.main()


class CommandProviderEvidence(unittest.TestCase):
    def test_command_error_acceptance_and_verified_followup_both_languages(self):
        proofs=[]
        for phase in (0,1):
            row,match,packets=fixture(phase,3)
            gate.audit_command_responses(row,copy.deepcopy(packets))
            proof,credit=gate.corroborate(row,match)
            self.assertFalse(packets)
            self.assertEqual(credit,{0:4,1:2})
            self.assertEqual([x['sdk_errno']for x in proof[0]['outcomes']],[0,0,0])
            self.assertFalse(proof[0]['outcomes'][0]['application_accepted'])
            self.assertTrue(proof[0]['outcomes'][1]['application_accepted'])
            proofs.append(dict(phase=phase,owners=row['owners'],**{gate.SUMMARY_KEY:proof}))
        self.assertTrue(gate.valid_summary(dict(proofs=proofs),version=3))
        self.assertFalse(gate.valid_summary(dict(proofs=proofs),version=2))

    def test_command_does_not_invent_peer_ack_or_application_success(self):
        for part,key,value in [('prompt','operation',13),('prompt','verify',True),
            ('reply','value','aa'),('reply','accepted_value','aa'),('application_value','value','aa')]:
            row,match,_=fixture(0,3);item=row[gate.COLLECTION][0];s=item['steps'][1]
            target=s['callback']['prompt']if part=='prompt'else s[part];target[key]=value
            transcript(item)
            with self.subTest(part=part,key=key),self.assertRaises(CaptureError):gate.corroborate(row,match)

    def test_spurious_success_error_or_late_response_is_rejected(self):
        for opcode in (14,5,0x8e):
            row,_,packets=fixture(0,3);item=row[gate.COLLECTION][0]
            packet=copy.deepcopy(packets[1]);packet['data']='0a000400'+bytes([opcode,3,0,0]).hex()
            packet['wall_ns']=item['steps'][1]['callback']['replied_wall_ns']+1000
            with self.subTest(opcode=opcode),self.assertRaises(CaptureError):gate.audit_command_responses(row,packets+[packet])
