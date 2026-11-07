# SPDX-License-Identifier: GPL-2.0-only
"""Literal paired-packet/SDK fixtures for the actual runner, not hardware proof."""
import copy
import errno
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError
import ws73_ssap_provider_unregister as gate
from test_ws73_ssap_provider_owner_exit import sdk_fixture


def fixture(phase=0, peer_error=175):
    row,matched,packets = sdk_fixture(phase,peer_error)
    old = 'ssap_provider_owner_exit'
    for suffix in ('required','version','cases','guards','tools'):
        row[gate.PREFIX+'_'+suffix] = row.pop(old+'_'+suffix)
    row[gate.PREFIX+'_version'] = 1
    i = row[gate.PREFIX+'_cases'][0];base = i['start_wall_ns']-2_000_000
    cb = i['callback'];cb['unregister_deadline_ns'] = cb.pop('exit_deadline_ns')
    i['pending_stdout'] = i['stdout']
    i['unregister_before_monotonic_ns'] = i.pop('kill_before_monotonic_ns')
    i['unregister_before_wall_ns'] = i.pop('kill_before_wall_ns')
    for k in ('kill_returned_wall_ns','kill_returned_monotonic_ns','owner_exit','owner_exit_monotonic_ns'):
        del i[k]
    r = dict(api=i['publisher_api'],token=1,property=i['handle'],original_deadline_ns=cb['prompt']['deadline_ns'],
             deadline_ns=cb['prompt']['deadline_ns'],started_ns=base+13_100_000,returned_ns=base+13_200_000,
             result=0,info_preserved=True,notification_fd_alive=True,reply_started_ns=base+13_250_000,
             reply_returned_ns=base+13_300_000,reply_result=-errno.ESHUTDOWN,local_observation_only=True)
    i.update(unregistered=r,unregister_observed_monotonic_ns=base+13_400_000,
             unregister_observed_wall_ns=base+13_400_000,provider_alive_after_guard_wall_ns=base+51_100_000,
             quit_wall_ns=base+52_000_000,owner_exit_wall_ns=base+53_000_000,exit=0)
    i['withdrawn_stdout'] = i['pending_stdout']+'SdkReadProviderUnregistered: '+json.dumps(r)+'\n'
    i['stdout'] = i['withdrawn_stdout']+f"SdkOwnedClosedExit: api={r['api']} start={i['start']}\n"
    i['captured_bytes']['stdout'] = len(i['stdout'].encode())
    return row,matched,packets


def proof():
    result = {'proofs':[]}
    for phase in (0,1):
        row,matched,packets = fixture(phase,(175,4)[phase]);p,c = gate.corroborate(row,matched,packets)
        assert not packets and c == {0:3,1:3}
        # Timestamp-only fixtures test the extra ordering predicate, not ordinary payload decoding.
        end=p[0]['case']['guard']['end_wall_ns']
        legs=[dict(tx={'wall_ns':end+1000+n*2000},rx={'wall_ns':end+2000+n*2000}) for n in range(8)]
        result['proofs'].append(dict(phase=phase,owners=row['owners'],legs=legs,**{gate.PREFIX:p}))
    return result


class Unregister(unittest.TestCase):
    def test_original_sdk_roles_and_all_six_paired_legs(self):
        p = proof();self.assertTrue(gate.valid_summary(p))
        for n,row in enumerate(p['proofs']):
            self.assertEqual(row[gate.PREFIX][0]['case']['publisher_api'],('python','c')[n])
            self.assertEqual(row[gate.PREFIX][0]['case']['exit'],0)

    def test_no_receipt_or_owner_death_substitution(self):
        for mutation in ('kill','reply_success','bad_token','no_fd','changed_info','rpc_failure','late_reply','deadline_renewal',
                         'old_lifetime','wrong_api','duplicate_receipt','extra_answer','wrong_tools','early_exit','missing_capture'):
            row,match,packets = fixture();i=row[gate.PREFIX+'_cases'][0];r=i['unregistered']
            if mutation=='kill':i['exit']=-9
            elif mutation=='reply_success':r['reply_result']=0
            elif mutation=='bad_token':r['token']+=1
            elif mutation=='no_fd':r['notification_fd_alive']=False
            elif mutation=='changed_info':r['info_preserved']=False
            elif mutation=='rpc_failure':r['result']=-errno.EIO
            elif mutation=='late_reply':r['reply_returned_ns']=r['deadline_ns']
            elif mutation=='deadline_renewal':r['deadline_ns']+=1
            elif mutation=='old_lifetime':row['owners'][1]['object']['lifetime']+=1
            elif mutation=='wrong_api':r['api']='rust'
            elif mutation=='wrong_tools':row[gate.PREFIX+'_tools'].pop(next(iter(row[gate.PREFIX+'_tools'])))
            elif mutation=='early_exit':i['owner_exit_wall_ns']=i['read']['start_wall_ns']
            elif mutation=='missing_capture':packets.pop()
            i['withdrawn_stdout']=i['pending_stdout']+'SdkReadProviderUnregistered: '+json.dumps(r)+'\n'
            if mutation=='duplicate_receipt':i['withdrawn_stdout']+=i['withdrawn_stdout'].splitlines()[-1]+'\n'
            if mutation=='extra_answer':i['withdrawn_stdout']+='SdkReadProviderReply: {}\n'
            i['stdout']=i['withdrawn_stdout']+f"SdkOwnedClosedExit: api={r['api']} start={i['start']}\n"
            i['captured_bytes']['stdout']=len(i['stdout'].encode())
            with self.subTest(mutation=mutation),self.assertRaises((CaptureError,KeyError,ValueError)):
                gate.corroborate(row,match,packets)

    def test_summary_negative_controls(self):
        original=proof()
        for change in ('one_phase','one_leg','false_result','changed_guard','wrong_action','same_controller','late_wire','missing_business','early_business'):
            p=copy.deepcopy(original);i=p['proofs'][0][gate.PREFIX][0]
            if change=='one_phase':p['proofs'].pop()
            elif change=='one_leg':i['wire'].pop()
            elif change=='false_result':i['case']['unregistered']['result']=-1
            elif change=='changed_guard':i['case']['guard']['secret']='00'*32
            elif change=='wrong_action':i['case']['kill_before_wall_ns']=1
            elif change=='same_controller':p['proofs'][1]['owners']=p['proofs'][0]['owners']
            elif change=='missing_business':p['proofs'][0]['legs'].pop()
            elif change=='early_business':p['proofs'][0]['legs'][0]['tx']['wall_ns']=i['case']['unregister_before_wall_ns']
            elif change=='late_wire':i['wire'][1]['rx']['wall_ns']=i['case']['callback']['unregister_deadline_ns']+1
            with self.subTest(change=change):self.assertFalse(gate.valid_summary(p))

    def test_selector_no_combining_lifecycle_actions(self):
        good=dict(ssap_provider_unregister_verify=True,ssap_read_provider_verify=True,ssap_owned_verify=True,
                  channel_socket_verify=True,passthrough=True,channel_socket_rounds=4,channel_socket_bytes=61)
        self.assertTrue(gate.requested(SimpleNamespace(**good)))
        for key,value in [('ssap_provider_unregister_verify',1),('ssap_owned_verify',False),
                          ('ssap_read_provider_verify',False),('passthrough',False),('channel_socket_bytes',62),
                          *[(k,True) for k in gate.INCOMPATIBLE]]:
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(SimpleNamespace(**dict(good,**{key:value})))
        tokens=['ws73.ssap_owned=1','ws73.ssap_read_provider=1',gate.TOKEN]
        self.assertTrue(gate.boot_requested(tokens))
        for bad in [tokens+[gate.TOKEN],tokens[:-2]+[gate.TOKEN],[gate.TOKEN],tokens+['ws73.ssap_provider_owner_exit=1'],
                    ['ws73.ssap_provider_unregister=0'],[True]]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):gate.boot_requested(bad)
        self.assertFalse(gate.valid_manifest(dict(ssap_provider_unregister_requested=True)))

    def test_rows_require_both_physical_receivers_and_baseline(self):
        rows=[fixture(n)[0]for n in (0,1)];gate.validate_rows(rows,True)
        for key,value in [('ssap_provider_unregister_version',True),('phase',True),
                          ('ssap_read_provider_version',1),('ssap_provider_owner_exit_required',True)]:
            bad=copy.deepcopy(rows);bad[0][key]=value
            with self.subTest(key=key),self.assertRaises(CaptureError):gate.validate_rows(bad,True)
        with self.assertRaises(CaptureError):gate.validate_rows(rows,False)

    def test_after_start_does_not_send_unregister_until_actual_pending(self):
        row,_,_=fixture();i=row[gate.PREFIX+'_cases'][0];i['output_files']=['fixture-only'];process=Mock();run=Mock()
        with patch('ws73_ssap_owned.wait_text',side_effect=CaptureError('missing actual request')):
            with self.assertRaises(CaptureError):gate._unregister(run,row,process,i,i['read'],i['callback']['supervisor_deadline_ns'])
        process.stdin.write.assert_not_called()
        process.kill.assert_not_called()

    def test_late_or_dead_owner_cannot_be_withdrawn(self):
        for dead in (True,False):
            row,_,_=fixture();i=row[gate.PREFIX+'_cases'][0];i['output_files']=['fixture-only'];process=Mock();process.poll.return_value=0 if dead else None
            now=i['callback']['prompt']['deadline_ns']+1 if not dead else i['callback']['observed_monotonic_ns']
            with patch('ws73_ssap_owned.wait_text',return_value=(None,i['pending_stdout'])),patch.object(gate.time,'monotonic_ns',return_value=now):
                with self.assertRaises(CaptureError):gate._unregister(Mock(),row,process,i,i['read'],i['callback']['supervisor_deadline_ns'])
            process.stdin.write.assert_not_called();process.kill.assert_not_called()

    def test_finish_rejects_owner_death_instead_of_normal_quit(self):
        process=Mock();process.poll.return_value=-9
        with self.assertRaises(CaptureError):gate._finish(Mock(),{},process,{})
        process.stdin.write.assert_not_called()


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
                next(r for r in package['inputs'] if Path(r['path']).name=='ws73_ssap_provider_unregister.py')['sha256']='0'*64
            with self.subTest(stale=stale),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);prepared=root/'prepared';prepared.mkdir();output=root/'output'
                (prepared/'manifest.json').write_text(json.dumps(package))
                argv=['ws73_target.py','run','--prepared',str(prepared),'--output',str(output),
                      '--ports','1-1.1.1','1-1.1.2','--qmp-hotplug','--firmware-evidence','runtime-observation',
                      '--connection-verify','--connection-advertising','negotiable-t','--channel-socket-verify',
                      '--ssap-owned-verify','--ssap-read-provider-verify','--ssap-provider-unregister-verify']
                with patch.object(sys,'argv',argv),patch.object(host,'run',side_effect=lambda a:a):args=host.main()
                with redirect_stdout(io.StringIO()),patch.object(host,'ordinary_identity'), \
                     patch.object(host,'prepared',return_value=package), \
                     patch.object(host,'lab_module',return_value=SimpleNamespace(inventory=lambda:[])), \
                     patch.object(gate,'validate_inputs',wraps=gate.validate_inputs) as check, \
                     patch.object(host.subprocess,'Popen',side_effect=AssertionError('must not launch')) as launch:
                    self.assertEqual(host._run(args),1)
                check.assert_called_once_with(package);launch.assert_not_called()
                record=json.loads((output/'manifest.json').read_text())
                self.assertIn('fresh exact unregister verifier' if stale else 'explicit known SSAP exchange artifact contract required',record['error'])
                self.assertIs(record[gate.PREFIX+'_acceptance'],False);self.assertIs(record['physical_acceptance'],False)
                self.assertNotIn('qemu_args',record)

    def test_actual_boot_parser_from_guest_init(self):
        import re,subprocess,os
        tools=Path(__file__).resolve().parents[1]
        line=next(l for l in (tools/'ws73_target_init.sh').read_text().splitlines()if 'provider_unregister_arg=$(' in l)
        code=re.search(r"-c '([^']+)'",line).group(1)
        self.assertIn('|| fail provider-unregister-selector',line)
        baseline=['ws73.ssap_owned=1','ws73.ssap_read_provider=1']
        for tokens,expected in [([],''),(baseline,''),(baseline+[gate.TOKEN],'--ssap-provider-unregister-verify')]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],capture_output=True,text=True,
                                  env=dict(os.environ,PYTHONPATH=str(tools)),timeout=5)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),expected)
        for tokens in [[gate.TOKEN],baseline+[gate.TOKEN,gate.TOKEN],baseline+[gate.TOKEN,'ws73.ssap_provider_owner_exit=1']]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],capture_output=True,text=True,
                                  env=dict(os.environ,PYTHONPATH=str(tools)),timeout=5)
            self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
