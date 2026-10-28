# SPDX-License-Identifier: GPL-2.0-only
"""Shared-oracle literal WRITE deadline fixtures, not SDK or device execution."""
import copy
import errno
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError, reassemble_acb
from ws73_ssap_update_delivery import TOOLS
import ws73_ssap_write_deadline as gate
import ws73_ssap_provider_deadline as shared
from test_ws73_ssap_provider_deadline import combined_summary


def refresh(item):
    lines=item['pending_stdout'].splitlines()
    lines[2]='SdkWriteProviderBound: '+json.dumps(item['bound'])
    approval=json.loads(lines[3].split(': ',1)[1]);approval.update(write=True,value=item['proposed'],data_type=0)
    lines[3]='SdkAuthorizationDecision: '+json.dumps(approval)
    lines[4]='SdkWriteProviderRequest: '+json.dumps(item['callback']['prompt'])
    item['pending_stdout']='\n'.join(lines)+'\n'
    item['late_stdout']=item['pending_stdout']+'SdkWriteProviderReply: '+json.dumps(item['late_reply'])+'\n'+'SdkWriteProviderValue: '+json.dumps(item['application_value'])+'\n'
    item['stdout']=item['late_stdout']+f"SdkOwnedRemoved: api={item['publisher_api']} start={item['start']}\n"
    item['captured_bytes']['stdout']=len(item['stdout'].encode())


def fixture(phase=0):
    old=combined_summary(2)['proofs'][phase]
    data=old[shared.PREFIX][0];row=copy.deepcopy(data['context']);item=copy.deepcopy(data['case'])
    for key in list(row):
        if key.startswith(('ssap_read_provider','ssap_provider_owner_exit',shared.PREFIX)):del row[key]
    row.update(ssap_owned_required=True,ssap_owned=[dict(end_wall_ns=item['start_wall_ns']-1000)for _ in range(4)],
               ssap_language_clients=[item['read']],**{gate.PREFIX+'_required':True,gate.PREFIX+'_version':1,
               gate.PREFIX+'_cases':[item],gate.PREFIX+'_tools':{n:dict(sha256='1'*64,bytes=10)for n in (*TOOLS,*gate.EXTRA_TOOLS)}})
    item['status']=gate.PENDING;item['operations']=6;item['proposed']=item['late_value']
    item['sdk_write_provider_contract_version']=item.pop('sdk_read_provider_contract_version')
    item['args']=[s.replace('owned-readonly','owned-writeonly') for s in item['args']]
    request=item['callback']['prompt'];request.pop('maximum_bytes');request.update(operation=13,data_type=0,offset=0,value_length=32,verify=True,value=item['proposed'])
    app=item['read'];app['ssap_operation']='ssap-write';app['ssap_proposed']=item['proposed']
    app['args']=[s.replace('ssap-read','ssap-write') for s in app['args']]+[item['proposed']]
    item['late_reply'].update(matched_value=True,accepted_value=None)
    item['application_value']=dict(api=item['publisher_api'],property=item['handle'],value=None,application_memory_only=True)
    refresh(item)
    pdu=b'\x0d\x23'+item['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(item['proposed'])
    frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
    physical=[]
    for p in data['window_packets']:
        for f in p['fragments']:
            f=copy.deepcopy(f);f['data']=frame.hex();physical.append(f)
    packets=reassemble_acb(dict(acb_packets=physical,native_events=[]))
    def matched(owner,direction,frame,window):
        key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
        found=[p for p in packets if tuple(p[k]for k in ('bus','device','handle','direction','data'))==key
               and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1:raise CaptureError('one exact fixture request leg required')
        packets.remove(found[0]);return found[0]
    return row,item,matched,packets,old['legs']


def proof():
    result=dict(proofs=[])
    for phase in (0,1):
        row,item,match,packets,legs=fixture(phase);data,credit=gate.corroborate(row,match,packets)
        assert not packets and credit=={0:1,1:0}
        gate.verify_business_evidence(row,data,legs)
        result['proofs'].append(dict(phase=phase,owners=row['owners'],legs=legs,**{gate.PREFIX:data}))
    return result


class WriteDeadline(unittest.TestCase):
    def test_both_roles_full_business_proof(self):
        p=proof();self.assertTrue(gate.valid_summary(p));self.assertFalse(shared.valid_summary(p,version=1))
        self.assertEqual([r[gate.PREFIX][0]['case']['publisher_api']for r in p['proofs']],['python','c'])

    def test_valid_late_call_not_parser_error_or_false_effect(self):
        for key,value in [('result',0),('result',-errno.ESHUTDOWN),('api_called',False),
                          ('matched_value',False),('accepted_value','00'*32),('deadline_ns',1),('value','00'*32)]:
            row,item,match,packets,_=fixture();item['late_reply'][key]=value;refresh(item)
            with self.subTest(key=key,value=value),self.assertRaises(CaptureError):gate.corroborate(row,match,packets)
        row,item,match,packets,_=fixture();item['application_value']['value']=item['proposed'];refresh(item)
        with self.assertRaises(CaptureError):gate.corroborate(row,match,packets)

    def test_identity_deadline_payload_and_operation(self):
        for key in ('operation','data_type','offset','value_length','lifetime','epoch','property','token','request_id','deadline_ns'):
            row,item,match,packets,_=fixture();item['callback']['prompt'][key]+=1;refresh(item)
            with self.subTest(key=key),self.assertRaises(CaptureError):gate.corroborate(row,match,packets)
        for key,value in [('verify',False),('value','00'*32)]:
            row,item,match,packets,_=fixture();item['callback']['prompt'][key]=value;refresh(item)
            with self.subTest(key=key),self.assertRaises(CaptureError):gate.corroborate(row,match,packets)

    def test_full_proof_fails_on_missing_changed_or_promoted_evidence(self):
        p=proof()
        for mode in ('phase','capture','duplicate','late_payload','application','old_lifetime','clock','recovery','drain','business','response','deadline'):
            bad=copy.deepcopy(p);r=bad['proofs'][0];v=r[gate.PREFIX][0];case=v['case']
            if mode=='phase':bad['proofs'].pop()
            elif mode=='capture':v['window_packets'].pop()
            elif mode=='duplicate':v['window_packets'].append(copy.deepcopy(v['window_packets'][0]))
            elif mode=='late_payload':case['late_value']='00'*32
            elif mode=='application':case['application_value']['value']=case['proposed']
            elif mode=='old_lifetime':v['context']['owners'][1]['object']['lifetime']+=1
            elif mode=='clock':case['clock_after']['realtime_ns']+=1000000
            elif mode=='recovery':v['same_actor_recovery']=True
            elif mode=='drain':case['requester_outcome']['physical_drain_proven']=True
            elif mode=='business':r['legs'].pop()
            elif mode=='response':v['window_packets'][0]['data']='0a0006000e0701110000'
            elif mode=='deadline':case['terminal_observation_deadline_ns']+=1
            with self.subTest(mode=mode):self.assertFalse(gate.valid_summary(bad))

    def test_selectors_rows_and_manifest(self):
        args=dict(ssap_write_provider_deadline_verify=True,passthrough=True,ssap_owned_verify=True,
                  channel_socket_verify=True,channel_socket_rounds=4,channel_socket_bytes=61)
        self.assertTrue(gate.requested(SimpleNamespace(**args)))
        for key,value in [('ssap_write_provider_unregister_verify',True),('ssap_sdk_write_provider_verify',True),
                          ('ssap_provider_deadline_verify',True),('ssap_owned_verify',False),('ssap_write_provider_deadline_verify',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(SimpleNamespace(**dict(args,**{key:value})))
        tokens=['ws73.ssap_owned=1',gate.TOKEN];self.assertTrue(gate.boot_requested(tokens))
        for bad in [[gate.TOKEN],tokens+[gate.TOKEN],tokens+['ws73.ssap_write_provider_unregister=1']]:
            with self.assertRaises(ValueError):gate.boot_requested(bad)
        rows=[fixture(n)[0]for n in (0,1)];gate.validate_rows(rows,True)
        with self.assertRaises(CaptureError):gate.validate_rows(rows,False)
        r=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,ssap_owned_acceptance=True,
               ordinary_channel_socket_acceptance=True,qemu_args=[' '.join(tokens)],channel_socket_corroboration=proof(),
               **{gate.PREFIX+'_requested':True,gate.PREFIX+'_version':1,gate.PREFIX+'_acceptance':True,
                  gate.PREFIX+'_verifier':dict(path='/fixture/ws73_ssap_write_deadline.py',sha256='1'*64,bytes=10)})
        self.assertTrue(gate.valid_manifest(r));self.assertTrue(gate.valid_manifest({}))
        for key,value in [('qemu_exit',False),('qemu_exit',1),('status','PASS'),('ssap_owned_acceptance',False),
                          ('ordinary_channel_socket_acceptance',False),(gate.PREFIX+'_version',True),
                          (gate.PREFIX+'_requested',False),('qemu_args',[])]:
            with self.subTest(key=key):self.assertFalse(gate.valid_manifest(dict(r,**{key:value})))
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
                next(r for r in package['inputs'] if Path(r['path']).name=='ws73_ssap_write_deadline.py')['sha256']='0'*64
            with self.subTest(stale=stale),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);prepared=root/'prepared';prepared.mkdir();output=root/'output'
                (prepared/'manifest.json').write_text(json.dumps(package))
                argv=['ws73_target.py','run','--prepared',str(prepared),'--output',str(output),
                      '--ports','1-1.1.1','1-1.1.2','--qmp-hotplug','--firmware-evidence','runtime-observation',
                      '--connection-verify','--connection-advertising','negotiable-t','--channel-socket-verify',
                      '--ssap-owned-verify','--ssap-write-provider-deadline-verify']
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
        line=next(l for l in (tools/'ws73_target_init.sh').read_text().splitlines()if 'write_deadline_arg=$(' in l)
        code=re.search(r"-c '([^']+)'",line).group(1)
        self.assertIn('|| fail sdk-provider-selector',line)
        baseline=['ws73.ssap_owned=1']
        for tokens,expected in [([],''),(baseline,''),(baseline+[gate.TOKEN],'--ssap-write-provider-deadline-verify')]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],capture_output=True,text=True,
                                  env=dict(os.environ,PYTHONPATH=str(tools)),timeout=5)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),expected)
        for tokens in [[gate.TOKEN],baseline+[gate.TOKEN,gate.TOKEN],baseline+[gate.TOKEN,'ws73.ssap_provider_owner_exit=1']]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],capture_output=True,text=True,
                                  env=dict(os.environ,PYTHONPATH=str(tools)),timeout=5)
            self.assertNotEqual(result.returncode,0)

