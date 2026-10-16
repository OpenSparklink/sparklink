# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic metadata/clock negatives; actual coordination uses existing pipe tests.

Fixtures test only the new verifier contract, never actual kernel/USB delivery.
The actual app/USB proof functions remain the existing independently tested path.
"""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ws73_parallel import fixture as rf_fixture
from ws73_capture import CaptureError
from ws73_north_star import Run
from ws73_parallel_data import (BusinessPair, BARRIER_SECONDS, PENDING, SUCCESS,
    SCOPE, SEQUENCE, overlap_window, pair_capture, verify_records)
from ws73_target import run_exit_code, validate_business_mode


def fixture():
    record,_=rf_fixture()
    policy=dict(file=dict(path='/fixture/policy.json',sha256='0'*64),data=dict(custom_configuration=False,config_sha256='0'*64,
        daemon_dump='Ws73DefaultPolicy: version=3 adv_slots=1200..1200 tx_power_dbm=127 scan_slots=1600/800',
        policies=dict(defaults=[3,1200,1200,127,1600,800],adapters={})))
    record.update(scope=SCOPE,status=PENDING,barrier_budget_seconds=BARRIER_SECONDS,
        policy_expectation=policy,fault_isolation_acceptance=False,stages=[])
    for pair,w in enumerate(record['workers']):
        r=w['run'];r.update(scope=SCOPE,status=SUCCESS,barrier_budget_seconds=BARRIER_SECONDS,
            policy_expectation=copy.deepcopy(policy),barriers=[],
            channel_socket=[dict(rounds=20,message_bytes=61) for _ in range(2)],
            connection_cleanup=[dict(status='NO_CURRENT_QUERIED_LINKS') for _ in range(2)])
        w['args']=['/bin/python3','/fixture/ws73_parallel_data.py','pair','--pair',str(pair),
            '--ports',*[o['port'] for o in r['initial']],'--slctl',r['slctl']['path'],
            '--slkd-pid',str(r['daemon_before']['pid']),'--output',f'/fixture/pair-{pair}',
            '--policy-expectation',policy['file']['path']]
    for n,(kind,role) in enumerate(SEQUENCE):
        waits=[]
        for pair,w in enumerate(record['workers']):
            event=dict(pair=pair,phase=kind,round=role,wait_wall_ns=100+n*10+pair)
            if kind=='ready':event['owners']=w['run']['initial']
            waits.append(dict(event=copy.deepcopy(event),observed_wall_ns=event['wait_wall_ns']+1))
            w['run']['barriers'].append(event|dict(ack_wall_ns=105+n*10))
        record['stages'].append(dict(phase=kind,round=role,waits=waits,release_wall_ns=104+n*10))
    return record


class BusinessEvidenceTests(unittest.TestCase):
    def test_explicit_fixed_positive_slice_metadata(self):
        self.assertEqual(len(verify_records(fixture())),4)

    def test_missing_failed_cross_owner_and_false_scope_never_pass(self):
        for change in ['failure','synthetic','root','caps','samepid','samecontroller','sameusb',
                'daemon','argv','policy','cleanup','connection-cleanup','rounds','bytes','boundary',
                'missing-stage','child-stage','future-ack','wrong-live','late','aborted','recovery']:
            r=fixture();a,b=[w['run'] for w in r['workers']]
            if change=='failure':r['workers'][1]['exit']=1
            if change=='synthetic':b['initial'][0]['descriptors']['product']='synthetic fixture'
            if change=='root':r['application_identity']['uids']=[0]*4
            if change=='caps':r['application_identity']['cap_eff']='1'
            if change=='samepid':r['workers'][1]['pid']=r['workers'][0]['pid']
            if change=='samecontroller':b['initial'][0]['index']=a['initial'][0]['index']
            if change=='sameusb':b['initial'][0]['device']=a['initial'][0]['device']
            if change=='daemon':b['bus_before']['owner']=':1.99'
            if change=='argv':r['workers'][1]['args'][6]='1-1'
            if change=='policy':b['policy_expectation']['file']['sha256']='1'*64
            if change=='cleanup':b['cleanup'].pop()
            if change=='connection-cleanup':b['connection_cleanup'][0]['status']='FAILED'
            if change=='rounds':b['channel_socket'][0]['rounds']=19
            if change=='bytes':b['channel_socket'][0]['message_bytes']=2042
            if change=='boundary':b['channel_socket'][0]['boundary_check']=True
            if change=='missing-stage':r['stages'].pop()
            if change=='child-stage':b['barriers'].pop()
            if change=='future-ack':b['barriers'][1]['ack_wall_ns']=1
            if change=='wrong-live':r['stages'][1]['waits'][1]['event']['pair']=0
            if change=='late':b['barriers'][1]['ack_wall_ns']+=46_000_000_000
            if change=='aborted':r['failure_shutdown']=[dict(pid=10)]
            if change=='recovery':r['automatic_fault_recovery_acceptance']=True
            with self.subTest(change=change),self.assertRaises((CaptureError,ValueError)):
                verify_records(r)

    def test_exact_capture_partition_keeps_records_and_excludes_other_pair(self):
        capture=dict(packet_count=99,acb_packets=[dict(bus=1,device=2,record=9),dict(bus=1,device=3,record=10)],
            native_events=[dict(bus=1,device=4,record=11)],complete=[])
        expected=dict(packet_count=99,acb_packets=[dict(bus=1,device=2,record=9)],native_events=[],complete=[])
        self.assertEqual(pair_capture(capture,[dict(bus=1,device=2)]),expected)
        self.assertEqual(capture['acb_packets'][1]['record'],10)
        with self.assertRaises(KeyError):pair_capture(dict(acb_packets=[dict(record=9)]),[dict(bus=1,device=2)])

    def test_real_intervals_must_overlap_not_merely_two_live_workers(self):
        self.assertEqual(overlap_window([[10,20],[15,25]]),[15,20])
        for windows in [[],[[10,20]],[[10,20],[20,30]],[[10,20],[21,30]],[[10,10],[1,30]]]:
            with self.subTest(windows=windows),self.assertRaises(CaptureError):overlap_window(windows)

    def test_business_does_not_enter_rf_start_or_match_barriers(self):
        run=BusinessPair.__new__(BusinessPair);owner=dict(path='/fixture')
        with patch.object(Run,'ctl',return_value='real-base-call') as ctl,patch.object(Run,'stop',return_value='real-base-stop') as stop,patch.object(run,'barrier',side_effect=AssertionError('RF hook')):
            self.assertEqual(run.ctl(owner,'advertise','on'),'real-base-call')
            self.assertEqual(run.stop(owner,'advertise'),'real-base-stop')
            ctl.assert_called_once_with(run,owner,'advertise','on');stop.assert_called_once_with(run,owner,'advertise')

    def test_new_mode_rejects_mixed_gates(self):
        validate_business_mode(SimpleNamespace(command='run',four_device_business=True))
        for key,value in [('parallel_pairs',True),('qmp_hotplug',True),('connection_verify',True),
                ('parallel_start_offset_ms',37),('security_agent','approve'),('managed_partial_case','release'),
                ('channel_socket_bytes',2042),('channel_socket_rounds',20),('connection_advertising','negotiable-t')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_business_mode(SimpleNamespace(command='run',four_device_business=True,**{key:value}))

    def test_status_string_without_complete_proof_is_failure(self):
        proof=dict(status='FOUR_REAL_PARALLEL_BUSINESS_CORROBORATED',controller_count=4,
            round_trips=80,ordinary_uid=1000,fixed_basic_channel_business_acceptance=True,
            pairs=[dict(connections=[{},{}],channel=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=40,proofs=[dict(legs=[{}]*40) for _ in range(2)])) for _ in range(2)],overlaps=[dict(role_phase=n,overlap_wall_ns=[1,2]) for n in range(2)],
            fault_isolation_acceptance=False,dynamic_channel_acceptance=False,
            automatic_fault_recovery_acceptance=False,protected_ssap_acceptance=False,full_goal_complete=False)
        record=dict(status='FOUR_DEVICE_PARALLEL_BUSINESS_PASS',four_device_parallel_business=True,
            four_device_parallel_rf=False,qemu_exit=0,parallel_corroboration=proof)
        self.assertEqual(run_exit_code(record),0)
        for key in record:
            wrong=copy.deepcopy(record);wrong.pop(key)
            with self.subTest(missing=key):self.assertEqual(run_exit_code(wrong),1)
        for key in proof:
            wrong=copy.deepcopy(record);wrong['parallel_corroboration'].pop(key)
            with self.subTest(proof_missing=key):self.assertEqual(run_exit_code(wrong),1)
        wrong=copy.deepcopy(record);wrong['parallel_corroboration']['pairs'][1]['channel']['proofs'].pop()
        self.assertEqual(run_exit_code(wrong),1)
        wrong=copy.deepcopy(record);wrong['parallel_corroboration']['overlaps'][1]['overlap_wall_ns']=[20,10]
        self.assertEqual(run_exit_code(wrong),1)


if __name__=='__main__':unittest.main()
