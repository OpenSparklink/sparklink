# SPDX-License-Identifier: GPL-2.0-only
"""Literal paired USB/SDK fixtures and real CLI parser, NOT hardware qualification."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ws73_ssap_write_down as gate
from ws73_capture import CaptureError
from ws73_ssap_update_delivery import TOOLS
from test_ws73_ssap_write_owner_exit import fixture as prior_fixture


def fixture(phase=0):
    row, matched, packets = prior_fixture(phase)
    old = 'ssap_write_provider_owner_exit'
    for suffix in ('required','version','cases','tools'):
        row[gate.PREFIX+'_'+suffix] = row.pop(old+'_'+suffix)
    del row[old+'_guards']
    row[gate.PREFIX+'_tools'] = {n:dict(sha256='1'*64, bytes=10) for n in (*TOOLS,*gate.EXTRA_TOOLS)}
    row.update(post_application_disconnect=True)
    row[gate.PREFIX+'_status'] = gate.PENDING
    item = row[gate.PREFIX+'_cases'][0]
    item['pending_stdout'] = item['stdout']
    item['down_before_wall_ns'] = item['kill_before_wall_ns']
    item['down_before_monotonic_ns'] = item['kill_before_monotonic_ns']
    for key in list(item):
        if key.startswith('kill_') or key in ('guard','retired_read'): del item[key]
    item.update(exit=0, down_command=0, down_completed_wall_ns=1_000_015_000_000,
                provider_alive_after_down_wall_ns=1_000_016_000_000,
                quit_wall_ns=1_000_021_000_000, owner_exit_wall_ns=1_000_022_000_000)
    item['cleanup'].update(start_wall_ns=1_000_023_000_000,end_wall_ns=1_000_024_000_000)
    for key in ('down_completed_wall_ns','provider_alive_after_down_wall_ns','quit_wall_ns','owner_exit_wall_ns'):
        item[key] += phase*1_000_000_000_000
    for key in ('start_wall_ns','end_wall_ns'):item['cleanup'][key] += phase*1_000_000_000_000
    item['stdout'] += f'SdkOwnedRemoved: api={item["publisher_api"]} start={item["start"]}\n'
    item['captured_bytes']['stdout'] = len(item['stdout'].encode())
    packets[:] = packets[:2]  # only the literal WRITE TX/RX, no response
    return row, matched, packets


def proof():
    result = dict(proofs=[])
    for phase in (0,1):
        row, matched, packets = fixture(phase)
        items, credit = gate.corroborate(row, matched, packets)
        assert not packets and credit == {0:1,1:0}
        result['proofs'].append(dict(phase=phase,owners=row['owners'],**{gate.PREFIX:items}))
    return result


class WriteDown(unittest.TestCase):
    def test_both_sdk_roles_and_single_paired_request(self):
        self.assertTrue(gate.valid_summary(proof()))

    def test_required_physical_and_application_evidence(self):
        for mutation in ('phase','packet','duplicate','payload','lifetime','deadline','timeout','early_result','reply','killed','cleanup','prompt'):
            p=proof();i=p['proofs'][0][gate.PREFIX][0];case=i['case']
            if mutation=='phase':p['proofs'].pop()
            elif mutation=='packet':del i['wire'][0]['rx']
            elif mutation=='duplicate':i['wire'].append(copy.deepcopy(i['wire'][0]))
            elif mutation=='payload':i['wire'][0]['rx']['data']='0a000400090baf00'
            elif mutation=='lifetime':i['context']['owners'][1]['object']['lifetime']+=1
            elif mutation=='deadline':case['callback']['exit_deadline_ns']+=1
            elif mutation=='timeout':case['read']['stdout']=case['read']['stdout'].replace('"errno": 5','"errno": 110')
            elif mutation=='early_result':case['down_before_monotonic_ns']=case['callback']['exit_deadline_ns']
            elif mutation=='reply':case['reply_command']='provide p1 00'
            elif mutation=='killed':case['exit']=-9
            elif mutation=='cleanup':case['cleanup']['stdout']='SsapLocalServices: [[16]]\n'
            elif mutation=='prompt':case['pending_stdout']=case['pending_stdout'].replace('"verify": true','"verify": false')
            with self.subTest(mutation=mutation):self.assertFalse(gate.valid_summary(p))

    def test_same_down_command_is_required(self):
        row,_,_=fixture();i=row[gate.PREFIX+'_cases'][0]
        row['applications']=[dict(end_wall_ns=i['read']['start_wall_ns']-1)]
        phase=dict(typed_objects=row['owners'],disconnect_command=0,
                   disconnect_completed_wall_ns=i['down_completed_wall_ns'],
                   down_property_observation={'end_wall_ns':i['down_completed_wall_ns']})
        run=dict(channel_socket=[row],connection_control={'phases':[phase]},
                 commands=[dict(start_wall_ns=i['down_before_wall_ns']+1,end_wall_ns=i['down_completed_wall_ns']-1)])
        gate.validate_phases(run)
        for key in ('down_command','down_completed_wall_ns'):
            changed=copy.deepcopy(run);changed['channel_socket'][0][gate.PREFIX+'_cases'][0][key]+=1
            with self.subTest(key=key),self.assertRaises((CaptureError,IndexError)):gate.validate_phases(changed)
        run['commands'][0]['start_wall_ns']=i['callback']['observed_wall_ns']-1
        with self.assertRaises(CaptureError):gate.validate_phases(run)

    def test_dedicated_selection_and_exact_boot(self):
        args=SimpleNamespace(passthrough=True,ssap_owned_verify=True,channel_socket_verify=True,
                             ssap_write_provider_down_verify=True)
        self.assertTrue(gate.requested(args))
        for name in ('ssap_sdk_write_provider_verify','ssap_write_provider_owner_exit_verify','channel_benchmark','channel_socket_burst'):
            setattr(args,name,True)
            with self.subTest(name=name),self.assertRaises(CaptureError):gate.requested(args)
            setattr(args,name,False)
        self.assertTrue(gate.boot_requested(['ws73.ssap_owned=1','ws73.ssap_write_provider_down=1']))
        for tokens in (['ws73.ssap_write_provider_down=1'],['ws73.ssap_owned=1','ws73.ssap_write_provider_down=0'],
                       ['ws73.ssap_owned=1','ws73.ssap_write_provider_down=1','ws73.ssap_write_provider_owner_exit=1']):
            with self.assertRaises(CaptureError):gate.boot_requested(tokens)

    def test_manifest_requires_actual_original_two_end_down(self):
        p=proof();connections=[]
        for row in p['proofs']:
            item=row[gate.PREFIX][0];owners=row['owners'];case=item['case']
            command=dict(opcode=0x1403,direction='out',bus=owners[0]['owner']['bus'],
                         device=owners[0]['owner']['device'],wall_ns=case['down_before_wall_ns']+1,
                         params=(owners[0]['object']['handle'].to_bytes(2,'little')+b'\x10').hex())
            events=[dict(bus=o['owner']['bus'],device=o['owner']['device'],event=0x1405,
                         params=(b'\0'+o['object']['handle'].to_bytes(2,'little')+b'\x10').hex(),
                         wall_ns=case['down_completed_wall_ns']-1) for o in owners]
            connections.append(dict(caller=owners[0]['owner'],peer=owners[1]['owner'],steps=[{},dict(command=command,outcomes=events)]))
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,ssap_owned_acceptance=True,
                    ordinary_channel_socket_acceptance=True,channel_socket_corroboration=p,
                    connection_corroboration=connections,qemu_args=['ws73.ssap_owned=1 ws73.ssap_write_provider_down=1'],
                    **{gate.PREFIX+'_requested':True,gate.PREFIX+'_acceptance':True,gate.PREFIX+'_version':1,
                       gate.PREFIX+'_verifier':dict(path='ws73_ssap_write_down.py',sha256='1'*64,bytes=10)})
        self.assertTrue(gate.valid_manifest(record))
        for change in ('missing','wrong_handle','early','wrong_owner','wrong_command','one_role','tool','exit'):
            r=copy.deepcopy(record);step=r['connection_corroboration'][0]['steps'][1]
            if change=='missing':step['outcomes'].pop()
            elif change=='wrong_handle':step['outcomes'][1]['params']='00ffff10'
            elif change=='early':step['outcomes'][0]['wall_ns']=step['command']['wall_ns']-1
            elif change=='wrong_owner':step['outcomes'][0]['device']+=100
            elif change=='wrong_command':step['command']['params']='ffff10'
            elif change=='one_role':r['connection_corroboration'].pop()
            elif change=='tool':r[gate.PREFIX+'_verifier']['sha256']='2'*64
            elif change=='exit':r['qemu_exit']=1
            with self.subTest(change=change):self.assertFalse(gate.valid_manifest(r))

    def test_no_accidental_completion_callback(self):
        from ws73_target_control import ConnectionControlRun
        run=ConnectionControlRun.__new__(ConnectionControlRun)
        run.args=SimpleNamespace(ssap_write_provider_down_verify=False)
        self.assertIsNone(run.channel_completion({},lambda:None))
        run.args.ssap_write_provider_down_verify=True
        run.data={'channel_socket':[]}
        with self.assertRaises(ValueError):run.channel_completion({'typed_objects':[]},lambda:None)()
        row={'owners':[{'original':'identity'}]};run.data['channel_socket']=[row]
        phase={'typed_objects':row['owners']};finish=lambda:None
        with patch.object(gate,'execute') as execute:
            run.channel_completion(phase,finish)()
            execute.assert_called_once_with(run,row,phase,finish)

    def test_actual_host_parser_and_guest_boot_command(self):
        import os, re, subprocess, sys
        import ws73_target as host
        tools=Path(__file__).resolve().parents[1]
        argv=['ws73_target.py','run','--prepared','/fixture/prepared','--output','/fixture/output',
              '--ports','1-1.1.1','1-1.1.2','--qmp-hotplug','--connection-verify',
              '--channel-socket-verify','--ssap-owned-verify','--ssap-write-provider-down-verify']
        with patch.object(sys,'argv',argv),patch.object(host,'run',side_effect=lambda a:a):args=host.main()
        self.assertTrue(gate.requested(args,passthrough=True))
        line=next(l for l in (tools/'ws73_target_init.sh').read_text().splitlines() if 'write_down_arg=$(' in l)
        code=re.search(r"-c '([^']+)'",line).group(1)
        self.assertIn('|| fail sdk-provider-selector',line)
        for tokens,ok in [([],True),(['ws73.ssap_owned=1','ws73.ssap_write_provider_down=1'],True),
                          (['ws73.ssap_write_provider_down=1'],False),
                          (['ws73.ssap_owned=1','ws73.ssap_write_provider_down=0'],False)]:
            result=subprocess.run([sys.executable,'-c',code,*tokens],env=dict(os.environ,PYTHONPATH=str(tools)),
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode==0,ok,result.stderr)
            if ok and tokens:self.assertEqual(result.stdout.strip(),'--ssap-write-provider-down-verify')
        package=dict(inputs=[host.file_record(p) for p in list(tools.glob('*.py'))+[tools/'ws73_target_init.sh']],
                     application_client_tools=dict(sources=[host.file_record(tools/n) for n in
                         ('testing/application_client/client.c','testing/application_client/client.py')]))
        gate.validate_inputs(package)
        next(r for r in package['inputs'] if Path(r['path']).name=='ws73_ssap_write_down.py')['sha256']='0'*64
        with self.assertRaises(CaptureError):gate.validate_inputs(package)

    def test_unrequested_or_partial_manifest_never_passes(self):
        self.assertTrue(gate.valid_manifest({}))
        self.assertFalse(gate.valid_manifest({gate.PREFIX+'_acceptance':True}))
        self.assertFalse(gate.valid_manifest({gate.PREFIX+'_requested':True,'qemu_args':['ws73.ssap_owned=1 ws73.ssap_write_provider_down=1']}))
        row,_,_=fixture()
        with self.assertRaises(CaptureError):gate.validate_rows([row],False)
        with self.assertRaises(CaptureError):gate.validate_rows([row],True)

if __name__ == '__main__': unittest.main()
