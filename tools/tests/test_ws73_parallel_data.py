# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic metadata/clock negatives; actual coordination uses existing pipe tests.

Fixtures test only the new verifier contract, never actual kernel/USB delivery.
The actual app/USB proof functions remain the existing independently tested path.
"""
import copy
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ws73_parallel import fixture as rf_fixture
from ws73_capture import CaptureError
from ws73_parallel import EventReader, PREFIX
from ws73_north_star import Run
from ws73_parallel_data import (BusinessPair, BARRIER_SECONDS, PENDING, SUCCESS,
    SCOPE, SEQUENCE, ISOLATION_SCOPE, BURST_SCOPE, stage_specs, rounds_for, disconnect_proofs, overlap_window, pair_capture, verify_records)
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


def disconnect_fixture():
    r=fixture();r.update(scope=ISOLATION_SCOPE,disconnect_isolation=True,stages=[])
    held={};clock=100
    for pair,w in enumerate(r['workers']):
        child=w['run'];child.update(scope=ISOLATION_SCOPE,disconnect_isolation=True,barriers=[])
        for n,row in enumerate(child['channel_socket']):row['rounds']=rounds_for(True,pair,n)
        w['args'].insert(-2,'--disconnect-isolation')
    def observe(pair,kind,phase):
        nonlocal clock
        clock+=1;event=dict(pair=pair,phase=kind,round=phase,wait_wall_ns=clock)
        if kind=='ready':event['owners']=r['workers'][pair]['run']['initial']
        r['workers'][pair]['run']['barriers'].append(event)
        clock+=1;return dict(event=copy.deepcopy(event),observed_wall_ns=clock)
    for kind,n,pairs in stage_specs(True):
        waits=[held.pop(n) if kind=='down' and pair==n else observe(pair,kind,n) for pair in pairs]
        clock+=1;r['stages'].append(dict(phase=kind,round=n,waits=waits,release_wall_ns=clock))
        for pair in pairs:
            child=r['workers'][pair]['run'];child['barriers'][-1]['ack_wall_ns']=clock+1
        clock+=1
        if kind=='business-done' and pairs==(n,):held[n]=observe(n,'down',n)
    return r


def capture_disconnect_fixture():
    pairs=[dict(connections=[],channel=dict(proofs=[])) for _ in range(2)]
    for pair in range(2):
        for n in range(2):
            shift=1000*n
            pairs[pair]['connections'].append(dict(steps=[{},dict(command=dict(wall_ns=shift+70),
                outcomes=[dict(bus=1,device=pair*2+dev,wall_ns=shift+80+dev) for dev in [2,3]])]))
            legs=[]
            for seq in range(20):
                for direction in range(2):
                    t=shift+10+seq*20+direction*2
                    legs.append(dict(sequence=seq,tx=dict(wall_ns=t),rx=dict(wall_ns=t+1)))
            pairs[pair]['channel']['proofs'].append(dict(legs=legs))
    return pairs


def burst_fixture():
    r=fixture();r.update(scope=BURST_SCOPE,burst_mode=True)
    for w in r['workers']:
        child=w['run'];child.update(scope=BURST_SCOPE,burst_mode=True)
        w['args'].insert(-2,'--burst')
        for row in child['channel_socket']:row.update(rounds=16,message_bytes=2042,burst=True)
    return r


def burst_summary_fixture():
    r=burst_fixture();pairs=[]
    for w in r['workers']:
        owners=[dict(owner=o,object=dict(lifetime=1,handle=0)) for o in w['run']['initial']]
        endpoints=[dict(controller=e['owner']['index'],generation=e['owner']['generation'],lifetime=1,handle=0,
            capacity=e['owner']['buffers'][1],wire_peak=e['owner']['buffers'][1],usb_submissions=206,nocp_packets=206,
            wire_final_debt=0,full_nocp_resume_intervals=[dict(full_record=5,nocp_record=6,resumed_submit_record=7)]) for e in owners]
        pairs.append(dict(connections=[{},{}],channel=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',
            round_trips=32,long_pdu_acceptance=True,software_backpressure_acceptance=True,credit_exhaustion_acceptance=False,
            proofs=[dict(owners=owners,legs=[{}]*32) for _ in range(2)]),budget_observations=[dict(phase=n,source_pool_refusals_delta=3,endpoints=copy.deepcopy(endpoints)) for n in range(2)]))
    proof=dict(status='FOUR_REAL_PARALLEL_BURST_CORROBORATED',controller_count=4,round_trips=64,ordinary_uid=1000,
        fixed_basic_channel_business_acceptance=True,long_pdu_acceptance=True,software_backpressure_acceptance=True,
        observed_controller_pool_saturation_and_resumption=True,controller_credit_correctness_proof=False,fairness_acceptance=False,
        fault_isolation_acceptance=False,dynamic_channel_acceptance=False,automatic_fault_recovery_acceptance=False,
        protected_ssap_acceptance=False,full_goal_complete=False,pairs=pairs,
        overlaps=[dict(role_phase=n,overlap_wall_ns=[1,2]) for n in range(2)])
    return dict(supervisor_exit=0,status='FOUR_DEVICE_PARALLEL_BURST_PASS',four_device_burst_requested=True,
        four_device_parallel_business=True,four_device_parallel_rf=False,qemu_exit=0,parallel_corroboration=proof)


class BurstEvidenceTests(unittest.TestCase):
    def test_explicit_two_pair_2042_burst_metadata(self):
        self.assertEqual(len(verify_records(burst_fixture())),4)
        validate_business_mode(SimpleNamespace(command='run',four_device_burst=True))
        for key in ['four_device_business','four_device_disconnect']:
            with self.assertRaises(ValueError):validate_business_mode(SimpleNamespace(command='run',four_device_burst=True,**{key:True}))
        for change in ['wrong-scope','worker-mode','worker-flag','small-size','wrong-rounds','not-burst','mixed-down']:
            r=burst_fixture();child=r['workers'][1]['run']
            if change=='wrong-scope':r['scope']=SCOPE
            if change=='worker-mode':child['burst_mode']=False
            if change=='worker-flag':r['workers'][0]['args'].remove('--burst')
            if change=='small-size':child['channel_socket'][0]['message_bytes']=61
            if change=='wrong-rounds':child['channel_socket'][0]['rounds']=20
            if change=='not-burst':child['channel_socket'][0]['burst']=False
            if change=='mixed-down':r['disconnect_isolation']=True
            with self.subTest(change=change),self.assertRaises((CaptureError,ValueError)):
                verify_records(r)

    def test_summary_requires_long_pressure_actual_budgets_and_no_broad_proof(self):
        self.assertEqual(run_exit_code(burst_summary_fixture()),0)
        for change in ['request','status','long','software','no-observation','no-refusal','source-owner','no-nocp','no-resume','debt','inherited-peak','proof','fairness','wrong-count','missing-pair']:
            r=burst_summary_fixture();p=r['parallel_corroboration'];pair=p['pairs'][1];obs=pair['budget_observations'][0];end=obs['endpoints'][0]
            if change=='request':r['four_device_burst_requested']=False
            if change=='status':r['status']='FOUR_DEVICE_PARALLEL_BUSINESS_PASS'
            if change=='long':pair['channel']['long_pdu_acceptance']=False
            if change=='software':p['software_backpressure_acceptance']=False
            if change=='no-observation':pair.pop('budget_observations')
            if change=='no-refusal':obs['source_pool_refusals_delta']=0
            if change=='source-owner':end['generation']+=100
            if change=='no-nocp':end['nocp_packets']-=1
            if change=='no-resume':end['full_nocp_resume_intervals']=[]
            if change=='debt':end['wire_final_debt']=1
            if change=='inherited-peak':end['wire_peak']-=1
            if change=='proof':p['controller_credit_correctness_proof']=True
            if change=='fairness':p['fairness_acceptance']=True
            if change=='wrong-count':p['round_trips']=80
            if change=='missing-pair':p['pairs'].pop()
            with self.subTest(change=change):self.assertEqual(run_exit_code(r),1)


class DisconnectEvidenceTests(unittest.TestCase):
    def test_ordered_alternating_disconnect_records(self):
        r=disconnect_fixture();self.assertEqual(len(verify_records(r)),4)
        self.assertEqual([[x['rounds'] for x in w['run']['channel_socket']] for w in r['workers']],[[4,20],[20,4]])
        self.assertEqual(len(r['stages']),11)

    def test_wrong_scope_participant_release_or_victim_budget_rejected(self):
        for change in ['scope','no-worker-flag','wrong-worker-flag','no-victim-down','early-survivor-release','wrong-victim','few-survivor','missing-wait','wrong-participant']:
            r=disconnect_fixture()
            if change=='scope':r['scope']=SCOPE
            if change=='no-worker-flag':r['workers'][1]['args'].remove('--disconnect-isolation')
            if change=='wrong-worker-flag':r['workers'][1]['run']['disconnect_isolation']=False
            if change=='no-victim-down':r['workers'][0]['run']['barriers'].pop(4)
            if change=='early-survivor-release':r['stages'][4]['release_wall_ns']=1
            if change=='wrong-victim':r['workers'][0]['run']['channel_socket'][0]['rounds']=20
            if change=='few-survivor':r['workers'][1]['run']['channel_socket'][0]['rounds']=4
            if change=='missing-wait':r['stages'][4]['waits']=[]
            if change=='wrong-participant':r['stages'][3]['waits'][0]['event']['pair']=1
            with self.subTest(change=change),self.assertRaises((CaptureError,ValueError,KeyError)):
                verify_records(r)

    def test_actual_pipes_select_victim_down_before_releasing_other_pair(self):
        processes=[];reader=None;rows=[]
        try:
            for pair in range(2):
                program=f"import json,sys,time; print({PREFIX!r}+json.dumps(dict(pair={pair},phase='business-done',round=0,wait_wall_ns=time.time_ns())),flush=True); assert sys.stdin.readline()=='done\\n'; print({PREFIX!r}+json.dumps(dict(pair={pair},phase='down',round=0,wait_wall_ns=time.time_ns())),flush=True); assert sys.stdin.readline()=='down\\n'"
                processes.append(subprocess.Popen([sys.executable,'-c',program],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
                rows.append(dict(stdout='',stderr=''))
            reader=EventReader(processes,rows,timeout_seconds=2)
            reader.wait_one(processes,0,'business-done',0)
            processes[0].stdin.write(b'done\n');processes[0].stdin.flush()
            first=reader.wait_one(processes,0,'down',0)
            second=reader.wait_one(processes,1,'business-done',0)
            self.assertLessEqual(first['observed_wall_ns'],second['observed_wall_ns'])
            processes[1].stdin.write(b'done\n');processes[1].stdin.flush()
            reader.wait_one(processes,1,'down',0)
            for p in processes:p.stdin.write(b'down\n');p.stdin.flush()
            for p in processes:p.wait(timeout=3);self.assertEqual(p.returncode,0)
        finally:
            for p in processes:
                if p.poll() is None:p.kill()
                p.wait()
                for stream in [p.stdin,p.stdout,p.stderr]:stream.close()
            if reader:reader.watch.close()

    def test_actual_down_needs_completed_replies_on_both_sides(self):
        p=capture_disconnect_fixture();proof=disconnect_proofs(p)
        self.assertEqual([x['victim_pair'] for x in proof],[0,1])
        self.assertEqual([x['survivor_pair'] for x in proof],[1,0])
        self.assertTrue(all(len(x['before_sequences'])>=2 and len(x['after_down_sequences'])>=4 for x in proof))
        for change in ['no-down','same-down-end','down-before-submit','survivor-finishes-before-down','survivor-starts-after-disconnect','missing-reply','duplicate-sequence']:
            p=capture_disconnect_fixture();step=p[0]['connections'][0]['steps'][1];legs=p[1]['channel']['proofs'][0]['legs']
            if change=='no-down':step['outcomes'].pop()
            if change=='same-down-end':step['outcomes'][1]['device']=step['outcomes'][0]['device']
            if change=='down-before-submit':step['command']['wall_ns']=100
            if change=='survivor-finishes-before-down':step['outcomes'][1]['wall_ns']=10000
            if change=='survivor-starts-after-disconnect':step['command']['wall_ns']=1
            if change=='missing-reply':legs.pop()
            if change=='duplicate-sequence':legs[-1]['sequence']=0
            with self.subTest(change=change),self.assertRaises(CaptureError):disconnect_proofs(p)

    def test_dedicated_mode_and_summary_require_disconnect_proof(self):
        validate_business_mode(SimpleNamespace(command='run',four_device_disconnect=True))
        with self.assertRaises(ValueError):validate_business_mode(SimpleNamespace(command='run',four_device_disconnect=True,four_device_business=True))
        proof=dict(status='FOUR_REAL_DISCONNECT_ISOLATION_CORROBORATED',controller_count=4,round_trips=48,
            ordinary_uid=1000,fixed_basic_channel_business_acceptance=True,
            fault_isolation_acceptance=False,dynamic_channel_acceptance=False,automatic_fault_recovery_acceptance=False,
            protected_ssap_acceptance=False,full_goal_complete=False,controlled_disconnect_isolation_acceptance=True,
            disconnect_proofs=[dict(role_phase=n,victim_pair=n,survivor_pair=1-n,before_sequences=[0,1],after_down_sequences=[16,17,18,19]) for n in range(2)],
            overlaps=[dict(role_phase=n,overlap_wall_ns=[1,2]) for n in range(2)],
            pairs=[dict(connections=[{},{}],channel=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=24,
                proofs=[dict(legs=[{}]*(8 if n==pair else 40)) for n in range(2)])) for pair in range(2)])
        r=dict(supervisor_exit=0,status='FOUR_DEVICE_DISCONNECT_ISOLATION_PASS',four_device_disconnect_requested=True,
            four_device_parallel_business=True,four_device_parallel_rf=False,qemu_exit=0,parallel_corroboration=proof)
        self.assertEqual(run_exit_code(r),0)
        for change in ['flag','proof','post-count','wrong-victim','status','count']:
            bad=copy.deepcopy(r);p=bad['parallel_corroboration']
            if change=='flag':bad['four_device_disconnect_requested']=False
            if change=='proof':p.pop('disconnect_proofs')
            if change=='post-count':p['disconnect_proofs'][1]['after_down_sequences']=[19]
            if change=='wrong-victim':p['disconnect_proofs'][1]['victim_pair']=0
            if change=='status':bad['status']='FOUR_DEVICE_PARALLEL_BUSINESS_PASS'
            if change=='count':p['round_trips']=80
            with self.subTest(change=change):self.assertEqual(run_exit_code(bad),1)


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
        record=dict(supervisor_exit=0,status='FOUR_DEVICE_PARALLEL_BUSINESS_PASS',four_device_parallel_business=True,
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
