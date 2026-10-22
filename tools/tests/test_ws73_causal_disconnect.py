# SPDX-License-Identifier: GPL-2.0-only
"""Test orchestration with explicit metadata/command fixtures and real child waits.

No controller,Native ioctl,USB or protocol delivery is simulated as qualification.
Fixture command text tests parser/order/error behavior only;physical success still
requires the original independent app/USB oracle in the VM.
"""
import copy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_channel_socket import passive_controller_checks,validate_passive_controller_stages,wait_application
from ws73_connection_control import disconnect_phase
from ws73_parallel_data import BusinessPair,stage_specs,verify_progress_contract,verify_records
from test_ws73_parallel_data import disconnect_fixture
from ws73_target import run_exit_code


class ProbeFixture:
    """Scripted observer receipts,not a Native backend;unknown commands fail."""
    def __init__(self,root):
        self.args=SimpleNamespace(slctl=root/'slctl');self.data=dict(commands=[]);self.count=1
        self.owners=[dict(path='/org/sparklink/slk0_g1',index=0,generation=1),
                     dict(path='/org/sparklink/slk1_g2',index=1,generation=2)]
        for name in ('controller-event-copy-probe','retired-uapi-probe','genl-registry-probe'):(root/name).touch()
    def save(self):pass
    def command(self,args,timeout,collection):
        if args[-1]=='events':
            o=next(o for o in self.owners if o['path']==args[-2]);text=f'ControllerEventPosition: index={o["index"]} generation={o["generation"]} sequence=3\n'
        elif args[-1]=='stats':
            o=next(o for o in self.owners if o['path']==args[-2]);text=f'ControllerLinkSummary: index={o["index"]} generation={o["generation"]} revision=2 event_sequence=3 connections={self.count}\n'
        elif Path(args[0]).name=='retired-uapi-probe':
            text='RETIRED_UAPI_ENOTTY_PASS: uid=1000 cases=103 unchanged=103 checks=309 invalid_user_address=1 mixed_stats=ENOTTY\n'
        elif Path(args[0]).name=='controller-event-copy-probe':
            text=f'CONTROLLER_EVENT_COPY_PASS: uid=1000 index={args[1]} generation={args[2]} partial=4 retry=4 peer_replay=4 readiness_preserved=4 removed_read=1 removed_stats=2\n'
        elif Path(args[0]).name=='genl-registry-probe':
            text='GENL_REGISTRY_PASS: uid=1000 count=4 version=2 retired=31 extra_attr=1 no_multicast=1 count_preserved=1\n'
        else:raise AssertionError('unexpected fixture command')
        row=dict(args=args,stdout=text,stderr='',exit=0,start_wall_ns=time.time_ns(),end_wall_ns=time.time_ns())
        self.data.setdefault(collection,[]).append(row);return row


def passive_fixture(root):
    run=ProbeFixture(root);row=dict(start_wall_ns=time.time_ns(),owners=[dict(owner=o)for o in run.owners])
    run.data['slctl']=dict(path=str(run.args.slctl))
    original=copy.deepcopy(row['owners']);passive_controller_checks(run,row,1,'before-applications')
    now=time.time_ns();row['applications']=[dict(role=r,start_wall_ns=now,end_wall_ns=now+1)for r in ('peer','initiator')]
    phase=dict(disconnect_command=0);stamp=time.time_ns()
    run.data['commands'].append(dict(start_wall_ns=stamp,end_wall_ns=stamp))
    phase['down_property_observation']=dict(end_wall_ns=stamp+1);phase['disconnect_completed_wall_ns']=stamp+2
    run.count=0;passive_controller_checks(run,row,0,'after-applications-and-down')
    row['end_wall_ns']=time.time_ns()
    assert row['owners']==original
    return run,row,phase


class CausalDisconnect(unittest.TestCase):
    def test_all_original_passive_checks_retained_at_connected_and_down_states(self):
        with tempfile.TemporaryDirectory()as tmp:
            run,row,phase=passive_fixture(Path(tmp))
            validate_passive_controller_stages(run.data,row,phase)
            self.assertEqual([s['expected_connections']for s in row['passive_controller_checks']],[1,0])
            for key in ('controller_event_positions','retired_uapi_refusals','controller_link_summaries','controller_event_copy'):
                self.assertEqual(len(run.data[key]),4)
            self.assertEqual(len(run.data['genl_registry']),2)

    def test_missing_wrong_state_owner_or_reordered_passive_receipts_fail(self):
        with tempfile.TemporaryDirectory()as tmp:
            run,row,phase=passive_fixture(Path(tmp))
            for case in ('missing-stage','before-app-order','after-down-order','missing-copy','wrong-link-state','wrong-owner','wrong-registry','failed-copy'):
                data=copy.deepcopy(run.data);r=copy.deepcopy(row);p=copy.deepcopy(phase)
                if case=='missing-stage':r['passive_controller_checks'].pop()
                elif case=='before-app-order':r['passive_controller_checks'][0]['end_wall_ns']=r['applications'][0]['start_wall_ns']+10
                elif case=='after-down-order':p['disconnect_completed_wall_ns']=r['passive_controller_checks'][1]['start_wall_ns']+10
                elif case=='missing-copy':data['controller_event_copy'].pop()
                elif case=='wrong-link-state':data['controller_link_summaries'][-1]['stdout']=data['controller_link_summaries'][-1]['stdout'].replace('connections=0','connections=1')
                elif case=='wrong-owner':data['controller_event_positions'][-1]['args'][-2]='/org/sparklink/slk15_g99'
                elif case=='wrong-registry':data['genl_registry'][-1]['stdout']=data['genl_registry'][-1]['stdout'].replace('count=4','count=2')
                else:data['controller_event_copy'][-1]['exit']=1
                with self.subTest(case=case),self.assertRaises((CaptureError,KeyError,ValueError)):
                    validate_passive_controller_stages(data,r,p)

    def test_passive_probe_failure_is_not_converted_to_success(self):
        with tempfile.TemporaryDirectory()as tmp:
            run=ProbeFixture(Path(tmp));run.count=0
            row=dict(owners=[dict(owner=o)for o in run.owners])
            with self.assertRaises(CaptureError):passive_controller_checks(run,row,1,'before-applications')
            self.assertNotIn('end_wall_ns',row['passive_controller_checks'][0])

    def test_real_owned_child_observation_does_not_refresh_original_deadline(self):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(.06)'])
        observed=[]
        try:
            wait_application(child,time.monotonic()+2,lambda:observed.append(time.monotonic()))
            self.assertEqual(child.returncode,0);self.assertGreaterEqual(len(observed),2)
        finally:
            if child.poll()is None:child.kill()
            child.wait()
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                wait_application(child,time.monotonic()+.01,lambda:time.sleep(.03))
        finally:
            if child.poll()is None:child.kill()
            child.wait()

    def test_progress_notification_is_bounded_once_and_never_waits_for_app_exit(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'stdout';pair=object.__new__(BusinessPair);pair.args=SimpleNamespace(pair=1)
            pair.save=lambda:None;events=[];pair.barrier=lambda kind,n:events.append((kind,n))
            row=dict(phase=0,applications=[dict(role='initiator',pid=123,output_files=[str(path)])])
            path.write_bytes(b'NativeChannelRoundTrip: sequence=0 elapsed_ms=1 bytes=00\n')
            pair._application_progress(row);self.assertFalse(events)
            prefix=path.read_bytes()+b'NativeChannelRoundTrip: sequence=1 elapsed_ms=1 bytes=01\n';path.write_bytes(prefix)
            pair._application_progress(row);pair._application_progress(row)
            self.assertEqual(events,[('business-progress',0)])
            self.assertEqual(row['business_progress_hint']['prefix_sha256'],hashlib.sha256(prefix).hexdigest())
            row.pop('business_progress_hint');path.write_bytes(b'x'*(128*1024+1))
            with self.assertRaises(CaptureError):pair._application_progress(row)
            path.write_bytes(b'NativeChannelRoundTrip: sequence=1 elapsed_ms=1 bytes=01\n')
            with self.assertRaises(CaptureError):pair._application_progress(row)

    def test_progress_stage_precedes_victim_release_without_changing_workload(self):
        specs=stage_specs(True,True)
        for n in range(2):
            self.assertLess(specs.index(('business-progress',n,(1-n,))),specs.index(('business-done',n,(n,))))
        with self.assertRaises(ValueError):stage_specs(False,True)

    def test_disconnect_failure_or_repeat_never_resubmits_same_phase(self):
        for case in ('ok','observation-failure','wrong-handle','command-failure'):
            calls=[]
            run=SimpleNamespace(args=SimpleNamespace(slctl='/bin/slctl'),data=dict(commands=[]),save=lambda:None)
            def command(args,timeout,collection):
                calls.append(args);row=dict(exit=int(case=='command-failure'),stdout='NativeConnectionResult: generation=1 request=2 operation=2 state=4 errno=0 fault=0 command_status=0 outcome_status=0 handle='+('8'if case=='wrong-handle'else'7')+' flags=7\n')
                run.data['commands'].append(row);return row
            run.command=command;phase=dict(caller=dict(path='/org/sparklink/slk0_g1',generation=1),connect=dict(handle=7))
            with self.subTest(case=case),patch('ws73_connection_control.observe_phase_down',side_effect=RuntimeError('fixture Down failure')if case=='observation-failure'else None):
                if case=='ok':disconnect_phase(run,phase,dict(path='/fixture/connection'))
                else:
                    with self.assertRaises((CaptureError,RuntimeError)):disconnect_phase(run,phase,dict(path='/fixture/connection'))
                with self.assertRaises(CaptureError):disconnect_phase(run,phase,dict(path='/fixture/connection'))
                self.assertEqual(len(calls),1)

    def test_new_summary_tag_without_original_progress_control_is_not_pass(self):
        # Not a complete positive fixture;missing evidence must never be upgraded.
        record=dict(supervisor_exit=0,status='FOUR_DEVICE_DISCONNECT_ISOLATION_PASS',
                    four_disconnect_progress_contract_version=1,parallel_corroboration=dict(disconnect_progress_contract_version=1))
        self.assertEqual(run_exit_code(record),1)

    def test_declared_null_boolean_and_unknown_contracts_are_not_legacy(self):
        for version in (None,True,False,0,2,'1'):
            r=disconnect_fixture();r['disconnect_progress_contract_version']=version
            with self.subTest(version=version),self.assertRaisesRegex(CaptureError,'supported Disconnect progress'):
                verify_records(r)

    def test_original_progress_prefix_validates_integer_version_and_sequences(self):
        with tempfile.TemporaryDirectory()as tmp:
            fixture,row,phase=passive_fixture(Path(tmp));row['post_application_disconnect']=True
            app=next(a for a in row['applications']if a['role']=='initiator')
            prefix='NativeChannelRoundTrip: sequence=0 elapsed_ms=1 bytes=00\nNativeChannelRoundTrip: sequence=1 elapsed_ms=1 bytes=01\n'
            app.update(pid=55,stdout=prefix)
            row['business_progress_hint']=dict(version=1,minimum_replies=2,pid=55,sequences=[0,1],prefix_bytes=len(prefix),
                prefix_sha256=hashlib.sha256(prefix.encode()).hexdigest(),observed_wall_ns=app['start_wall_ns'])
            other=copy.deepcopy(row);other.pop('business_progress_hint')
            run=dict(fixture.data,channel_socket=[row,other],connection_control=dict(phases=[phase,phase]))
            observations={(1,'business-progress',0):(None,dict(event=dict(wait_wall_ns=app['start_wall_ns'])))}
            verify_progress_contract(run,observations,1)
            for case in ('bool-version','bool-sequences','wrong-prefix','wrong-pid'):
                bad=copy.deepcopy(run);hint=bad['channel_socket'][0]['business_progress_hint']
                if case=='bool-version':hint['version']=True
                elif case=='bool-sequences':hint['sequences']=[False,True]
                elif case=='wrong-prefix':hint['prefix_sha256']='0'*64
                else:hint['pid']=56
                with self.subTest(case=case),self.assertRaises(CaptureError):verify_progress_contract(bad,observations,1)
