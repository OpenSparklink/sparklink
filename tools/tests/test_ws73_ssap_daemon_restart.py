# SPDX-License-Identifier: GPL-2.0-only
"""Recorded-shape negative controls, not daemon/kernel/hardware qualification."""
import copy
import errno
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

import ws73_ssap_daemon_restart as gate
from test_ws73_ssap_write_down import fixture as down_fixture
from test_ws73_ssap_sdk_write_provider import summary as write_summary


def fixture(phase=0):
    row,_,packets=down_fixture(phase);item=row['ssap_write_provider_down_cases'][0]
    prompt=item['callback']['prompt'];base=1_000_000_000_000*(phase+1)
    item['read']['ssap_expected_errno']=errno.ESTALE
    item['read']['args'][-2]=str(errno.ESTALE)
    outputs=[json.loads(s)for s in item['read']['stdout'].splitlines()];outputs[-1]['errno']=errno.ESTALE
    item['read']['stdout']=''.join(json.dumps(s)+'\n'for s in outputs)
    item['armed']=dict(api=prompt['api'],token=prompt['token'],deadline_ns=prompt['deadline_ns'],armed_ns=base+12_100_000)
    item['observations']=[]
    for ordinal,at in [(1,base+13_000_000),(2,base+17_000_000)]:
        upper=prompt['deadline_ns'] if ordinal==1 else item['bind_before_monotonic_ns']+30_000_000_000
        receipt=dict(api=prompt['api'],ordinal=ordinal,token=prompt['token'],deadline_ns=prompt['deadline_ns'],
            observation_deadline_ns=upper,started_ns=at,returned_ns=at+1000,notification_events=1,
            next_result=-errno.ESTALE,authorization_result=-errno.ESTALE,reply_result=-errno.ESTALE,
            info_preserved=True,value_preserved=True,notification_fd_alive=True,local_observation_only=True)
        item['observations'].append(dict(receipt=receipt,lower_ns=at,upper_ns=upper,start_wall_ns=at,end_wall_ns=at+2000))
    item['application_value']['value']=None
    item['stdout']=item['pending_stdout']+'SdkWriteProviderOwnerLossArmed: '+json.dumps(item['armed'])+'\n'
    for o in item['observations']:item['stdout']+='SdkWriteProviderOwnerLoss: '+json.dumps(o['receipt'])+'\n'
    item['stdout']+='SdkWriteProviderValue: '+json.dumps(item['application_value'])+'\n'
    item['stdout']+=f'SdkOwnedRetiredExit: api={prompt["api"]} start={item["start"]}; local release only\n'
    item['captured_bytes']['stdout']=len(item['stdout'].encode())
    record=dict(pending_write_restart=dict(phase=phase,owners=row['owners'],cases=[item],
        status='PENDING_WRITE_DAEMON_RESTART_EVIDENCE_PENDING'),connection_control=dict(phases=[dict(typed_objects=row['owners'])]),
        armed_wall_ns=base+12_200_000,death=dict(reaped_wall_ns=base+12_500_000),successor=dict(wall_ns=base+16_000_000))
    capture=dict(acb_packets=[f for p in packets for f in p['fragments']],native_events=[])
    return record,capture


class Restart(unittest.TestCase):
    def test_original_both_sdk_receipts_and_real_reassembler(self):
        for phase in (0,1):
            record,capture=fixture(phase)
            proof=gate.corroborate(record,capture)
            self.assertEqual(len(proof['request_legs']),2)
            data=write_summary();data.update(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8)
            whole=dict(daemon_restart_version=2,pending_write=proof,successor_data=data,
                successor_connections=[{'physical':'fixture'}]*2,successor_objects=[{'typed':'fixture'}]*2)
            self.assertTrue(gate.summary_valid(whole))
            broken=copy.deepcopy(whole);broken['pending_write']['acb_packets'].pop()
            self.assertFalse(gate.summary_valid(broken))
            broken=copy.deepcopy(whole);del broken['successor_data']['proofs'][0]['ssap_sdk_write_providers']
            self.assertFalse(gate.summary_valid(broken))

    def test_receipt_identity_deadline_and_wire_negative_controls(self):
        for mutation in ('missing_rx','duplicate','payload','lifetime','deadline','success','no_wake','fd_dead',
                         'before_reap','before_successor','value','transcript','early_arm','no_requester'):
            r,c=fixture();i=r['pending_write_restart']['cases'][0]
            with self.subTest(mutation=mutation):
                if mutation=='missing_rx':c['acb_packets'].pop()
                elif mutation=='duplicate':c['acb_packets'].append(copy.deepcopy(c['acb_packets'][0]))
                elif mutation=='payload':c['acb_packets'][1]['data']='0a00010000'
                elif mutation=='lifetime':i['callback']['prompt']['lifetime']+=1
                elif mutation=='deadline':i['observations'][0]['upper_ns']=1
                elif mutation=='success':i['observations'][0]['receipt']['reply_result']=0
                elif mutation=='no_wake':i['observations'][0]['receipt']['notification_events']=0
                elif mutation=='fd_dead':i['observations'][1]['receipt']['notification_fd_alive']=False
                elif mutation=='before_reap':r['death']['reaped_wall_ns']=i['observations'][0]['start_wall_ns']+1
                elif mutation=='before_successor':r['successor']['wall_ns']=i['observations'][1]['start_wall_ns']+1
                elif mutation=='value':i['application_value']['value']=i['proposed']
                elif mutation=='transcript':i['stdout']+='unexpected success\n'
                elif mutation=='early_arm':r['armed_wall_ns']=1
                elif mutation=='no_requester':i['read']['exit']=1
                with self.assertRaises((ValueError,KeyError)):gate.corroborate(r,c)

    def test_retained_old_success_rejected(self):
        r,c=fixture();i=r['pending_write_restart']['cases'][0]
        reply=b'\x0e\x03'+i['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(i['proposed'])
        p=copy.deepcopy(c['acb_packets'][1]);p.update(direction='out',record=3,wall_ns=r['death']['reaped_wall_ns'],
            data=(b'\x0a\0'+len(reply).to_bytes(2,'little')+reply).hex());c['acb_packets'].append(p)
        with self.assertRaises(ValueError):gate.corroborate(r,c)

    def test_plain_su_and_explicit_sdk_credentials_do_not_double_drop(self):
        from ws73_channel_daemon_crash import ControlRun
        obj=object.__new__(ControlRun);obj.save=lambda:None
        with patch('ws73_north_star.Run.command',return_value={})as call:
            credentials=dict(user=1000,group=1000,extra_groups=[])
            obj.command(['/bin/example'],1,collection='commands',child_credentials=credentials)
            self.assertEqual(call.call_args.args,(['/bin/example'],1))
            self.assertEqual(call.call_args.kwargs['child_credentials'],credentials)

    def test_root_supervised_slktest_drops_privileges(self):
        from ws73_channel_socket import run_applications
        record,_=fixture();row=dict(applications=[],owners=record['pending_write_restart']['owners'],
            boundary_check=False,close_prefix=False,burst=False,application_tool=dict(path='/bin/slktest'),
            rounds=4,message_bytes=61,security_requirement=0,message_security_required=True,phase=0)
        class Files:
            def enter_context(self, stream):stream.close();return None
        import tempfile
        with tempfile.TemporaryDirectory()as tmp:
            run=SimpleNamespace(output=Path(tmp),save=lambda:None)
            with patch('ws73_channel_socket.os.geteuid',return_value=0),patch('ws73_channel_socket.subprocess.Popen',side_effect=RuntimeError('stop before process'))as launch:
                with self.assertRaisesRegex(RuntimeError,'stop before process'):run_applications(run,row,[],Files())
                self.assertEqual({k:launch.call_args.kwargs[k]for k in ('user','group','extra_groups')},dict(user=1000,group=1000,extra_groups=[]))

if __name__=='__main__':unittest.main()
