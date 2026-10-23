# SPDX-License-Identifier: GPL-2.0-only
"""Production orchestration/verdict functions with explicit metadata/file fixtures.

These inputs are NOT packets or controller successes: no Native/SSAP transport is
stubbed. Actual parser/callback/peer/USB proof and kernel concurrency need VM gates.
"""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ws73_parallel_data import fixture,burst_summary_fixture
from ws73_capture import CaptureError
from ws73_parallel_data import OWNED_SCOPE,verify_records,owned_parallel_proof
from ws73_target import HERE,require_owned_preparation,run_exit_code,validate_business_mode


def owned_fixture():
    r=fixture();r.update(scope=OWNED_SCOPE,owned_ssap_mode=True,parallel_owned_contract_version=1)
    for worker in r['workers']:
        child=worker['run'];child.update(scope=OWNED_SCOPE,owned_ssap_mode=True,parallel_owned_contract_version=1)
        worker['args'].insert(-2,'--owned-ssap')
        for row in child['channel_socket']:row.update(ssap_owned_required=True,ssap_owned=[{}for _ in range(4)])
    return r


def pair_proofs():
    pairs=[]
    for pair in range(2):
        connections=[];phases=[]
        for n in range(2):
            shift=n*1000
            connections.append(dict(steps=[dict(outcomes=[dict(wall_ns=shift+10),dict(wall_ns=shift+11)]),
                dict(outcomes=[dict(wall_ns=shift+900),dict(wall_ns=shift+901)])]))
            cases=[]
            for sender in (0,1):
                for policy in ('allow','deny'):
                    base=shift+100+pair*20+len(cases)*40
                    cases.append(dict(sender=sender,policy=policy,owner_lost=True,
                        wire=[dict(tx=dict(wall_ns=base+j*3),rx=dict(wall_ns=base+j*3+1))for j in range(10)]))
            phases.append(dict(ssap_owned=cases,legs=[{}for _ in range(40)]))
        pairs.append(dict(connections=connections,channel=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=40,proofs=phases)))
    return pairs


def summary_fixture():
    r=burst_summary_fixture();p=r['parallel_corroboration']
    for name in ['long_pdu_acceptance','software_backpressure_acceptance','observed_controller_pool_saturation_and_resumption','controller_credit_correctness_proof','fairness_acceptance']:p.pop(name)
    p.update(status='FOUR_REAL_PARALLEL_OWNED_SSAP_CORROBORATED',round_trips=80,pairs=pair_proofs(),
        parallel_owned_contract_version=1,parallel_owned_control=owned_fixture(),owned_ssap_acceptance=True)
    p['owned_ssap']=owned_parallel_proof(p['pairs'])
    r.update(status='FOUR_DEVICE_PARALLEL_OWNED_SSAP_PASS',four_device_burst_requested=False,
        four_device_owned_requested=True,four_owned_contract_version=1,qemu_args=['ws73.parallel=1 ws73.parallel_business=1 ws73.parallel_owned=1'])
    return r


class ParallelOwned(unittest.TestCase):
    def test_original_metadata_contract_preserves_four_owners_and_exact_requests(self):
        self.assertEqual(len(verify_records(owned_fixture())),4)
        for case in ('null','bool','string','worker-version','worker-flag','missing-selector','missing-case','unrequested','burst','wrong-scope'):
            bad=owned_fixture();child=bad['workers'][1]['run']
            if case=='null':bad['parallel_owned_contract_version']=None
            elif case=='bool':bad['parallel_owned_contract_version']=True
            elif case=='string':bad['parallel_owned_contract_version']='1'
            elif case=='worker-version':child['parallel_owned_contract_version']=True
            elif case=='worker-flag':child['owned_ssap_mode']=1
            elif case=='missing-selector':bad['workers'][1]['args'].remove('--owned-ssap')
            elif case=='missing-case':child['channel_socket'][0]['ssap_owned'].pop()
            elif case=='unrequested':child['channel_socket'][0]['ssap_owned_required']=False
            elif case=='burst':bad['burst_mode']=True
            else:bad['scope']='four real WS73 two-pair connected business'
            with self.subTest(case=case),self.assertRaises((CaptureError,ValueError)):verify_records(bad)

    def test_wire_composition_needs_cases_overlap_and_physical_lifetime(self):
        p=owned_parallel_proof(pair_proofs());self.assertEqual(p['request_response_exchanges'],80)
        self.assertFalse(p['fault_isolation_acceptance']);self.assertEqual(p['owner_exit_remote_refusals'],16)
        for case in ('missing-case','missing-wire','no-owner-loss','duplicate-policy','before-Up','after-Down','no-overlap'):
            bad=pair_proofs();items=bad[1]['channel']['proofs'][0]['ssap_owned']
            if case=='missing-case':items.pop()
            elif case=='missing-wire':items[0]['wire'].pop()
            elif case=='no-owner-loss':items[0]['owner_lost']=False
            elif case=='duplicate-policy':items[1]['policy']='allow'
            else:
                shift={'before-Up':-200,'after-Down':1000,'no-overlap':400}[case]
                for item in items:
                    for leg in item['wire']:
                        for direction in ['tx','rx']:leg[direction]['wall_ns']+=shift
            with self.subTest(case=case),self.assertRaises(CaptureError):owned_parallel_proof(bad)

    def test_summary_requires_original_control_exact_boot_and_no_scope_upgrade(self):
        self.assertEqual(run_exit_code(summary_fixture()),0)
        for case in ('missing-control','missing-boot','duplicate-boot','null-version','bool-version','proof-version','worker','missing-wire','forged-count','fault-claim','old-status','missing-request','conflicting-burst','conflicting-disconnect','missing-business'):
            bad=summary_fixture();p=bad['parallel_corroboration']
            if case=='missing-control':p.pop('parallel_owned_control')
            elif case=='missing-boot':bad['qemu_args']=[]
            elif case=='duplicate-boot':bad['qemu_args']*=2
            elif case=='null-version':bad['four_owned_contract_version']=None
            elif case=='bool-version':bad['four_owned_contract_version']=True
            elif case=='proof-version':p['parallel_owned_contract_version']=True
            elif case=='worker':p['parallel_owned_control']['workers'][0]['run']['owned_ssap_mode']=False
            elif case=='missing-wire':p['pairs'][1]['channel']['proofs'][0]['ssap_owned'][0]['wire'].pop()
            elif case=='forged-count':p['owned_ssap']['request_response_exchanges']=81
            elif case=='fault-claim':p['fault_isolation_acceptance']=True
            elif case=='old-status':bad['status']='FOUR_DEVICE_PARALLEL_BUSINESS_PASS'
            elif case=='conflicting-burst':bad['qemu_args'].append('ws73.parallel_burst=1')
            elif case=='conflicting-disconnect':bad['qemu_args'].append('ws73.parallel_disconnect=1')
            elif case=='missing-business':bad['qemu_args']=[v.replace('ws73.parallel_business=1','')for v in bad['qemu_args']]
            else:bad['four_device_owned_requested']=False
            with self.subTest(case=case):self.assertEqual(run_exit_code(bad),1)

    def test_new_selector_is_exclusive_and_old_modes_do_not_enable_it(self):
        validate_business_mode(SimpleNamespace(command='run',four_device_owned=True))
        for other in ('four_device_business','four_device_burst','four_device_disconnect','ssap_owned_verify','qmp_hotplug'):
            with self.subTest(other=other),self.assertRaises(ValueError):
                validate_business_mode(SimpleNamespace(command='run',four_device_owned=True,**{other:True}))
        old=fixture();old['parallel_owned_contract_version']=1
        with self.assertRaises(CaptureError):verify_records(old)

    def test_actual_staged_files_and_executable_init_must_match_new_source(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);tools=root/'root/usr/share/sparklink/tools';tools.mkdir(parents=True)
            for name in ['ws73_parallel_data.py','ws73_ssap_owned.py','ws73_channel_socket.py','ws73_dynamic_channels.py']:(tools/name).write_bytes((HERE/name).read_bytes())
            entry=root/'root/init';entry.write_bytes((HERE/'ws73_target_init.sh').read_bytes());entry.chmod(0o755)
            require_owned_preparation(dict(four_owned_contract_version=1),root)
            for version in (None,True,'1',0):
                with self.subTest(version=version),self.assertRaises(ValueError):require_owned_preparation(dict(four_owned_contract_version=version),root)
            entry.chmod(0o644)
            with self.assertRaises(ValueError):require_owned_preparation(dict(four_owned_contract_version=1),root)
            entry.chmod(0o755);entry.write_bytes(b'#!/bin/sh\nexit 0\n')
            with self.assertRaises(ValueError):require_owned_preparation(dict(four_owned_contract_version=1),root)
            entry.write_bytes((HERE/'ws73_target_init.sh').read_bytes());(tools/'ws73_ssap_owned.py').write_text('# stale\n')
            with self.assertRaises(ValueError):require_owned_preparation(dict(four_owned_contract_version=1),root)
