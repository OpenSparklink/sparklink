# SPDX-License-Identifier: GPL-2.0-only
"""Bounded case/report fixtures only,not Native death, cleanup, Agent or RF proof.

Reuse existing expiry/release fixtures and original production validators. No
successful OS/kernel/SDK/time dependency is stubbed. Actual known guest child
SIGKILL, credentials, retained sibling and wire checks remain separate VM gates.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from test_ws73_parallel_expiry import expiry_metadata,expiry_pairs,expiry_summary
from test_ws73_parallel_subscription import summary_fixture as release_summary
from ws73_capture import CaptureError
from ws73_parallel_data import verify_records,subscription_parallel_proof
from ws73_ssap_subscription import requested,requested_shared_case
from ws73_target import require_subscription_preparation,run_exit_code,validate_business_mode


def owner_metadata():
    r=expiry_metadata();r['ssap_subscription_shared_case']='owner-exit'
    for w in r['workers']:
        w['run']['ssap_subscription_shared_case']='owner-exit'
        w['args'][w['args'].index('--ssap-subscription-shared-case')+1]='owner-exit'
        for row in w['run']['channel_socket']:row['ssap_subscription_shared_case']='owner-exit'
    return r


def owner_pairs():
    pairs=expiry_pairs()
    for pair in pairs:
        root=pair['subscription_supervision'];root.pop('partial_expirations');root.pop('expired_discarded')
        root.update(shared_case='owner-exit',partial_owner_exits=8,unconsumed_published=8,retained_releases=8)
        for row in pair['channel']['proofs']:
            for value in row['ssap_subscription']:
                value.pop('partial_expirations');value.pop('expired_discarded')
                value.update(shared_case='owner-exit',partial_owner_exits=2,unconsumed_published=2,retained_releases=2)
    return pairs


def owner_summary():
    r=expiry_summary();r['ssap_subscription_shared_case']='owner-exit';r['qemu_args']=[v.replace('shared_case=expiry','shared_case=owner-exit')for v in r['qemu_args']]
    proof=r['parallel_corroboration'];pairs=owner_pairs();control=owner_metadata()
    for pair,w in zip(pairs,control['workers'],strict=True):pair['subscription_supervision']['daemon']=copy.deepcopy(w['run']['daemon_before'])
    proof.update(pairs=pairs,parallel_subscription_control=control,shared_subscription=subscription_parallel_proof(pairs,case='owner-exit'))
    return r


class FourOriginalOwnerExit(unittest.TestCase):
    def test_explicit_existing_case_does_not_enable_standalone_or_other_modes(self):
        args=SimpleNamespace(four_device_shared_subscription=True,ssap_subscription_shared_case='owner-exit')
        validate_business_mode(SimpleNamespace(command='run',**vars(args)))
        self.assertEqual(requested_shared_case(args,four_pair=True),'owner-exit')
        self.assertFalse(requested(args,passthrough=False))
        with self.assertRaises(ValueError):requested_shared_case(args)
        for case in (True,None,'unsupported'):
            with self.subTest(case=case),self.assertRaises(ValueError):requested_shared_case(SimpleNamespace(four_device_shared_subscription=True,ssap_subscription_shared_case=case),four_pair=True)

    def test_coordinator_worker_cli_phase_and_original_contract_must_match(self):
        self.assertEqual(len(verify_records(owner_metadata())),4)
        for change in ('version','worker','CLI','phase','expiry','mixed'):
            r=owner_metadata();w=r['workers'][1]
            if change=='version':r['ssap_subscription_shared_lifetime_contract_version']=True
            elif change=='worker':w['run']['ssap_subscription_shared_case']='expiry'
            elif change=='CLI':w['args'][w['args'].index('--ssap-subscription-shared-case')+1]='release'
            elif change=='phase':w['run']['channel_socket'][1]['ssap_subscription_shared_case']='expiry'
            elif change=='expiry':r=expiry_metadata();r['ssap_subscription_shared_case']='owner-exit'
            else:r['update_delivery_mode']=True
            with self.subTest(change=change),self.assertRaises(CaptureError):verify_records(r)

    def test_original_owner_death_counts_and_wire_matrix_cannot_be_release_or_expiry(self):
        p=subscription_parallel_proof(owner_pairs(),case='owner-exit')
        self.assertEqual((p['updates'],p['application_replies'],p['partial_owner_exits'],p['unconsumed_published'],p['retained_releases']),(112,192,16,16,16))
        self.assertNotIn('partial_expirations',p);self.assertNotIn('expired_discarded',p)
        for change in ('expiry-proof','missing-death','no-unread','wrong-retained-count','wrong-root','false-expiry','missing-wire'):
            pairs=owner_pairs();pair=pairs[1];value=pair['channel']['proofs'][0]['ssap_subscription'][0]
            if change=='expiry-proof':pairs=expiry_pairs()
            elif change=='missing-death':value.pop('partial_owner_exits')
            elif change=='no-unread':value['unconsumed_published']=0
            elif change=='wrong-retained-count':pair['subscription_supervision']['retained_releases']=16
            elif change=='wrong-root':pair['subscription_supervision']['shared_case']='expiry'
            elif change=='false-expiry':value['expired_discarded']=2
            else:value['wire'].pop()
            with self.subTest(change=change),self.assertRaises(CaptureError):subscription_parallel_proof(pairs,case='owner-exit')
        with self.assertRaises(CaptureError):subscription_parallel_proof(owner_pairs(),case='expiry')

    def test_verdict_binds_actual_boot_original_case_and_fresh_artifact(self):
        self.assertEqual(run_exit_code(release_summary()),0);self.assertEqual(run_exit_code(expiry_summary()),0);self.assertEqual(run_exit_code(owner_summary()),0)
        for change in ('missing-boot','wrong-boot','duplicate-boot','missing-fresh','bool-fresh','false-death','false-unread','wrong-retained-count','false-expiry','old-expiry-summary','missing-control'):
            r=owner_summary();p=r['parallel_corroboration']
            if change=='missing-boot':r['qemu_args'][0]=r['qemu_args'][0].replace(' ws73.subscription_shared_case=owner-exit','')
            elif change=='wrong-boot':r['qemu_args'][0]=r['qemu_args'][0].replace('shared_case=owner-exit','shared_case=expiry')
            elif change=='duplicate-boot':r['qemu_args'].append('ws73.subscription_shared_case=owner-exit')
            elif change=='missing-fresh':r.pop('four_subscription_lifetime_contract_version')
            elif change=='bool-fresh':r['four_subscription_lifetime_contract_version']=True
            elif change=='false-death':p['shared_subscription']['partial_owner_exits']=15
            elif change=='false-unread':p['shared_subscription']['unconsumed_published']=0
            elif change=='wrong-retained-count':p['shared_subscription']['retained_releases']=32
            elif change=='false-expiry':p['shared_subscription']['expired_discarded']=16
            elif change=='old-expiry-summary':p['shared_subscription']=expiry_summary()['parallel_corroboration']['shared_subscription']
            else:p.pop('parallel_subscription_control')
            with self.subTest(change=change):self.assertEqual(run_exit_code(r),1)

    def test_actual_wire_timing_predicate_rejects_expiry_and_extended_observation(self):
        from ws73_ssap_shared import validate_owner_exit_timing
        # Timestamp/identity inputs to the actual oracle;not an OS death fixture.
        lease=dict(application=dict(pid=17),active=dict(expires_ns=30_000_000_000),withdrawn_wall_ns=130,
            owner_loss=dict(pid=17,signal=9,exit=-9,start_monotonic_ns=100,exit_monotonic_ns=101,
                observation_deadline_ns=5_000_000_100,start_wall_ns=110,exit_wall_ns=120))
        group=dict(messages=[{}, {}, {},dict(end_monotonic_ns=90,end_wall_ns=100),dict(end_monotonic_ns=200)])
        validate_owner_exit_timing(lease,group)
        for change in ('expired','exact-expiry','bool-expiry','wrong-child','not-killed','expiry-substitution','extended-deadline','late-sibling','before-unread','wrong-wall'):
            item=copy.deepcopy(lease);g=copy.deepcopy(group);death=item['owner_loss']
            if change=='expired':item['active']['expires_ns']=100
            elif change=='exact-expiry':item['active']['expires_ns']=101
            elif change=='bool-expiry':item['active']['expires_ns']=True
            elif change=='wrong-child':death['pid']=18
            elif change=='not-killed':death['exit']=0
            elif change=='expiry-substitution':item['expiry']={}
            elif change=='extended-deadline':death['observation_deadline_ns']+=1
            elif change=='late-sibling':g['messages'][4]['end_monotonic_ns']=death['observation_deadline_ns']
            elif change=='before-unread':death['start_monotonic_ns']=89
            else:death['exit_wall_ns']=131
            with self.subTest(change=change),self.assertRaises(CaptureError):validate_owner_exit_timing(item,g)

    def test_stale_lifetime_preparation_is_rejected_before_dependency_access(self):
        with tempfile.TemporaryDirectory()as tmp:
            for v in (None,True,0,2,'1'):
                package=dict(four_subscription_contract_version=1)
                if v is not None:package['four_subscription_lifetime_contract_version']=v
                with self.subTest(v=v),self.assertRaises(ValueError):require_subscription_preparation(package,Path(tmp),case='owner-exit')
