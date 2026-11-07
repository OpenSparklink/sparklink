# SPDX-License-Identifier: GPL-2.0-only
"""Literal WRITE/SDK fixtures on shared lifecycle orchestration; not hardware."""
import copy
import errno
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ws73_ssap_write_owner_exit as gate
import ws73_ssap_provider_owner_exit as shared
from ws73_capture import CaptureError,reassemble_acb
from ws73_ssap_update_delivery import TOOLS
from test_ws73_ssap_provider_owner_exit import sdk_fixture as read_fixture


def refresh(i):
    lines=i['stdout'].splitlines()
    lines[2]='SdkWriteProviderBound: '+json.dumps(i['bound'])
    approval=json.loads(lines[3].split(': ',1)[1]);approval.update(write=True,value=i['proposed'],data_type=0)
    lines[3]='SdkAuthorizationDecision: '+json.dumps(approval)
    lines[4]='SdkWriteProviderRequest: '+json.dumps(i['callback']['prompt'])
    i['stdout']='\n'.join(lines)+'\n';i['captured_bytes']['stdout']=len(i['stdout'].encode())


def fixture(phase=0,error=175):
    row,matched,packets=read_fixture(phase,error)
    for suffix in ('required','version','cases','guards','tools'):
        row[gate.PREFIX+'_'+suffix]=row.pop(shared.PREFIX+'_'+suffix)
    row[gate.PREFIX+'_version']=1
    for key in list(row):
        if key.startswith('ssap_read_provider'):del row[key]
    row.update(ssap_owned_required=True,ssap_owned=[{}for _ in range(4)])
    row[gate.PREFIX+'_tools']={n:dict(sha256='1'*64,bytes=10)for n in (*TOOLS,*gate.EXTRA_TOOLS)}
    i=row[gate.PREFIX+'_cases'][0];i['operations']=6
    i['sdk_write_provider_contract_version']=i.pop('sdk_read_provider_contract_version')
    i['args']=[v.replace('owned-readonly','owned-writeonly')for v in i['args']]
    i['proposed']=('e1'if phase==0 else'e2')*32
    prompt=i['callback']['prompt'];prompt.pop('maximum_bytes');prompt.update(operation=13,data_type=0,offset=0,value_length=32,verify=True,value=i['proposed'])
    app=i['read'];app['ssap_operation']='ssap-write';app['ssap_proposed']=i['proposed']
    app['args']=[v.replace('ssap-read','ssap-write')for v in app['args']]+[i['proposed']]
    refresh(i)
    h=i['handle'].to_bytes(2,'little')
    sdus=[b'\x0d\x23'+h+b'\0'+bytes.fromhex(i['proposed']),b'\x0e\x07\x01'+h+bytes([error])]
    physical=[]
    for n,p in enumerate(packets):
        for f in p['fragments']:
            v=copy.deepcopy(f)
            if n<4:
                sdu=sdus[n//2];v['data']=(b'\x0a\0'+len(sdu).to_bytes(2,'little')+sdu).hex()
            physical.append(v)
    packets[:]=reassemble_acb(dict(acb_packets=physical,native_events=[]))
    return row,matched,packets


def proof():
    result=dict(proofs=[])
    for phase in (0,1):
        row,match,packets=fixture(phase,(175,4)[phase]);items,credit=gate.corroborate(row,match,packets)
        assert not packets and credit=={0:3,1:3}
        end=items[0]['case']['guard']['end_wall_ns']
        legs=[dict(tx={'wall_ns':end+1000+n*2000},rx={'wall_ns':end+2000+n*2000})for n in range(8)]
        result['proofs'].append(dict(phase=phase,owners=row['owners'],legs=legs,**{gate.PREFIX:items}))
    return result


class WriteOwnerExit(unittest.TestCase):
    def test_literal_both_roles_full_proof(self):
        p=proof();self.assertTrue(gate.valid_summary(p))
        self.assertEqual([r[gate.PREFIX][0]['peer_error']for r in p['proofs']],[175,4])
        self.assertEqual([r[gate.PREFIX][0]['case']['publisher_api']for r in p['proofs']],['python','c'])
        self.assertFalse(shared.valid_summary(p))

    def test_original_write_context_before_owner_loss(self):
        for field in ('value','verify','operation','offset','data_type','value_length','request_id','lifetime','epoch','property','api','token'):
            row,match,packets=fixture();i=row[gate.PREFIX+'_cases'][0];q=i['callback']['prompt']
            q[field]=('00'*32 if field=='value'else False if field=='verify'else'c'if field=='api'else False if field=='token'else q[field]+1)
            refresh(i)
            with self.subTest(field=field),self.assertRaises((CaptureError,KeyError)):gate.corroborate(row,match,packets)
    def test_missing_changed_or_old_peer_evidence(self):
        for change in ('one_phase','one_leg','exit','guard','no_business','early_business','old_lifetime','duplicate','wrong_error','wrong_command','clock'):
            p=copy.deepcopy(proof());item=p['proofs'][0][gate.PREFIX][0]
            if change=='one_phase':p['proofs'].pop()
            elif change=='one_leg':item['wire'].pop()
            elif change=='exit':item['case']['owner_exit']=0
            elif change=='guard':item['case']['guard']['secret']='00'*32
            elif change=='no_business':p['proofs'][0]['legs'].pop()
            elif change=='early_business':p['proofs'][0]['legs'][0]['tx']['wall_ns']=item['case']['kill_before_wall_ns']
            elif change=='old_lifetime':item['context']['owners'][1]['object']['lifetime']+=1
            elif change=='duplicate':item['wire'].append(copy.deepcopy(item['wire'][0]))
            elif change=='wrong_error':item['wire'][1]['rx']['data']='0a000400090baf00'
            elif change=='wrong_command':item['case']['read']['args'][-1]='00'*32
            elif change=='clock':item['case']['clock_after']['realtime_ns']+=100000000
            with self.subTest(change=change):self.assertFalse(gate.valid_summary(p))

    def test_real_callback_required_before_owner_exit(self):
        row,_,_=fixture();i=row[gate.PREFIX+'_cases'][0];i['output_files']=['fixture-only'];process=Mock()
        with patch('ws73_ssap_owned.wait_text',side_effect=CaptureError('no actual callback')):
            with self.assertRaises(CaptureError):shared._owner_exit(Mock(),row,process,i,i['read'],i['callback']['supervisor_deadline_ns'],writing=True)
        process.stdin.write.assert_not_called();process.kill.assert_not_called()

    def test_actual_arrival_kill_and_original_cleanup_deadline(self):
        for phase in (0,1):
            row,_,_=fixture(phase);item=row[gate.PREFIX+'_cases'][0]
            item['output_files']=['/unused/sdk.stdout','/unused/sdk.stderr']
            process=Mock(pid=item['pid'],returncode=-9);process.poll.return_value=None
            observed=item['callback']['observed_monotonic_ns']
            with patch('ws73_ssap_owned.wait_text',return_value=([],item['stdout'])) as arrival, \
                 patch('ws73_ssap_owned.wait_output') as wait, \
                 patch('ws73_ssap_owned.await_removed',return_value=item['cleanup']) as removed, \
                 patch.object(shared.time,'monotonic_ns',return_value=observed), \
                 patch.object(shared.time,'time_ns',return_value=observed):
                shared._owner_exit(SimpleNamespace(save=Mock()),row,process,item,item['read'],item['read']['ssap_supervisor_deadline_ns'],writing=True)
            self.assertEqual(arrival.call_args.args[2],r'^SdkWriteProviderRequest: (.+)$')
            process.kill.assert_called_once_with();process.stdin.write.assert_not_called()
            deadline=item['callback']['exit_deadline_ns']
            wait.assert_called_once_with(process,(deadline-observed)/1e9)
            self.assertEqual(removed.call_args.kwargs,dict(deadline_ns=deadline))

    def test_selector_and_rows_fail_closed(self):
        args=dict(ssap_write_provider_owner_exit_verify=True,passthrough=True,ssap_owned_verify=True,channel_socket_verify=True,channel_socket_rounds=4,channel_socket_bytes=61)
        self.assertTrue(gate.requested(SimpleNamespace(**args)))
        for key,value in [('ssap_sdk_write_provider_verify',True),('ssap_read_provider_verify',True),('ssap_provider_unregister_verify',True),('channel_socket_bytes',62),('ssap_owned_verify',False),('ssap_write_provider_owner_exit_verify',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(SimpleNamespace(**dict(args,**{key:value})))
        tokens=['ws73.ssap_owned=1',gate.TOKEN];self.assertTrue(gate.boot_requested(tokens))
        for bad in [[gate.TOKEN],tokens+[gate.TOKEN],tokens+['ws73.ssap_sdk_write_provider=1'],tokens+['ws73.ssap_provider_unregister=1']]:
            with self.assertRaises(ValueError):gate.boot_requested(bad)
        rows=[fixture(n)[0]for n in(0,1)];gate.validate_rows(rows,True)
        with self.assertRaises(CaptureError):gate.validate_rows(rows,False)
        self.assertFalse(gate.valid_manifest({gate.PREFIX+'_requested':True}))
        self.assertTrue(gate.valid_manifest({}))

    def test_actual_cli_host_rejects_stale_verifier_before_vm(self):
        import tempfile
        from contextlib import redirect_stdout
        import io
        import ws73_target as host
        tools = Path(__file__).resolve().parents[1]
        good = dict(inputs=[host.file_record(p) for p in list(tools.glob('*.py'))+[tools/'ws73_target_init.sh']],
                    application_client_tools=dict(sources=[host.file_record(tools/n) for n in
                        ('testing/application_client/client.c','testing/application_client/client.py')]),
                    ssap_exchange_contract_version=False)
        for stale in (True,False):
            package=copy.deepcopy(good)
            if stale:
                next(r for r in package['inputs'] if Path(r['path']).name=='ws73_ssap_write_owner_exit.py')['sha256']='0'*64
            with self.subTest(stale=stale),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);prepared=root/'prepared';prepared.mkdir();output=root/'output'
                (prepared/'manifest.json').write_text(json.dumps(package))
                argv=['ws73_target.py','run','--prepared',str(prepared),'--output',str(output),
                      '--ports','1-1.1.1','1-1.1.2','--qmp-hotplug','--firmware-evidence','runtime-observation',
                      '--connection-verify','--connection-advertising','negotiable-t','--channel-socket-verify',
                      '--ssap-owned-verify','--ssap-write-provider-owner-exit-verify']
                with patch.object(sys,'argv',argv),patch.object(host,'run',side_effect=lambda a:a):args=host.main()
                with redirect_stdout(io.StringIO()),patch.object(host,'ordinary_identity'), \
                     patch.object(host,'prepared',return_value=package), \
                     patch.object(host,'lab_module',return_value=SimpleNamespace(inventory=lambda:[])), \
                     patch.object(gate,'validate_inputs',wraps=gate.validate_inputs) as check, \
                     patch.object(host.subprocess,'Popen',side_effect=AssertionError('must not launch')) as launch:
                    self.assertEqual(host._run(args),1)
                check.assert_called_once_with(package);launch.assert_not_called()
                record=json.loads((output/'manifest.json').read_text())
                self.assertIn('fresh pending WRITE helper' if stale else 'explicit known SSAP exchange artifact contract required',record['error'])
                self.assertIs(record[gate.PREFIX+'_acceptance'],False);self.assertIs(record['physical_acceptance'],False)
                self.assertNotIn('qemu_args',record)

    def test_actual_boot_parser_from_guest_init(self):
        import re,subprocess,os
        tools=Path(__file__).resolve().parents[1]
        line=next(l for l in (tools/'ws73_target_init.sh').read_text().splitlines()if 'write_owner_exit_arg=$(' in l)
        code=re.search(r"-c '([^']+)'",line).group(1)
        self.assertIn('|| fail sdk-provider-selector',line)
        baseline=['ws73.ssap_owned=1']
        for tokens,expected in [([],''),(baseline,''),(baseline+[gate.TOKEN],'--ssap-write-provider-owner-exit-verify')]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],capture_output=True,text=True,
                                  env=dict(os.environ,PYTHONPATH=str(tools)),timeout=5)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),expected)
        for tokens in [[gate.TOKEN],baseline+[gate.TOKEN,gate.TOKEN],baseline+[gate.TOKEN,'ws73.ssap_provider_owner_exit=1']]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],capture_output=True,text=True,
                                  env=dict(os.environ,PYTHONPATH=str(tools)),timeout=5)
            self.assertNotEqual(result.returncode,0)

    def test_manifest_requires_complete_terminal_and_exact_verifier(self):
        p=proof();r={'status':'PASSTHROUGH_SUPPORT_PASS','qemu_exit':0,'ssap_owned_acceptance':True,
             'ordinary_channel_socket_acceptance':True,'qemu_args':['ws73.ssap_owned=1 '+gate.TOKEN],
             gate.PREFIX+'_requested':True,gate.PREFIX+'_version':1,gate.PREFIX+'_acceptance':True,
             gate.PREFIX+'_verifier':{'path':'/fixture/ws73_ssap_write_owner_exit.py','sha256':'1'*64,'bytes':10},
             'channel_socket_corroboration':p}
        self.assertTrue(gate.valid_manifest(r))
        for k,v in [('qemu_exit',False),('qemu_exit',1),('status','PASS'),('ordinary_channel_socket_acceptance',False),
                    ('ssap_owned_acceptance',False),(gate.PREFIX+'_requested',False),(gate.PREFIX+'_version',True),
                    (gate.PREFIX+'_acceptance',False),('qemu_args',[]),(gate.PREFIX+'_verifier',{'path':'old','sha256':'0'*64,'bytes':10})]:
            bad=copy.deepcopy(r);bad[k]=v
            with self.subTest(k=k,v=v):self.assertFalse(gate.valid_manifest(bad))
