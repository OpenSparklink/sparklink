# SPDX-License-Identifier: GPL-2.0-only
"""Finite original-case/report fixtures, not Native expiry, Agent or RF proof.

Reuse the existing shared/release fixtures and actual parser/verdict functions.
No successful kernel, SDK, time, allocator or wire dependency is stubbed.
Real deadline/queue/identity and sibling delivery remain mandatory VM gates.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from test_ws73_parallel_subscription import metadata_fixture as release_metadata,pairs_fixture as release_pairs,summary_fixture as release_summary
from ws73_capture import CaptureError
from ws73_parallel_data import verify_records,subscription_case,subscription_parallel_proof
from ws73_ssap_subscription import requested,requested_shared_case
from ws73_target import require_subscription_preparation,run_exit_code,validate_business_mode


def expiry_metadata():
    record=release_metadata()
    for row in [record,*[w['run']for w in record['workers']]]:
        row.update(ssap_subscription_shared_case='expiry',ssap_subscription_shared_lifetime_contract_version=1)
    for worker in record['workers']:
        worker['args'][-2:-2]=['--ssap-subscription-shared-case','expiry']
        for phase in worker['run']['channel_socket']:phase.update(ssap_subscription_shared_case='expiry',ssap_subscription_shared_contract_version=1,ssap_subscription_shared_lifetime_contract_version=1)
    return record


def expiry_pairs():
    pairs=release_pairs()
    for pair in pairs:
        pair['subscription_supervision'].update(shared_case='expiry',shared_lifetime_contract_version=1,partial_expirations=8,expired_discarded=8)
        for row in pair['channel']['proofs']:
            for value in row['ssap_subscription']:value.update(shared_case='expiry',shared_lifetime_contract_version=1,partial_expirations=2,expired_discarded=2)
    return pairs


def expiry_summary():
    record=release_summary();record.update(ssap_subscription_shared_case='expiry',ssap_subscription_shared_lifetime_contract_version=1,four_subscription_lifetime_contract_version=1)
    record['qemu_args'][0]+=' ws73.subscription_shared_case=expiry'
    proof=record['parallel_corroboration'];pairs=expiry_pairs();control=expiry_metadata()
    for pair,worker in zip(pairs,control['workers'],strict=True):pair['subscription_supervision']['daemon']=copy.deepcopy(worker['run']['daemon_before'])
    proof.update(pairs=pairs,parallel_subscription_control=control,shared_subscription=subscription_parallel_proof(pairs,case='expiry'))
    return record


class FourOriginalExpiry(unittest.TestCase):
    def test_existing_selector_requires_dedicated_explicit_four_context(self):
        args=SimpleNamespace(four_device_shared_subscription=True,ssap_subscription_shared_case='expiry')
        validate_business_mode(SimpleNamespace(command='run',**vars(args)))
        self.assertEqual(requested_shared_case(args,four_pair=True),'expiry')
        self.assertFalse(requested(args,passthrough=False)) # Does not enable a standalone gate.
        with self.assertRaises(ValueError):requested_shared_case(args)
        for case in (True,None,'unknown'):
            with self.subTest(case=case),self.assertRaises(ValueError):requested_shared_case(SimpleNamespace(four_device_shared_subscription=True,ssap_subscription_shared_case=case),four_pair=True)
        # Existing separate two-device cases are not removed or upgraded.
        self.assertEqual(requested_shared_case(SimpleNamespace(ssap_subscription_shared_verify=True,ssap_subscription_shared_case='owner-exit')),'owner-exit')

    def test_original_record_worker_cli_and_phase_must_name_same_case(self):
        self.assertEqual(len(verify_records(expiry_metadata())),4)
        for change in ('coordinator-version','worker-case','worker-version','missing-flag','wrong-flag','phase-case','phase-version','wrong-mode','wrong-coordinator-case'):
            record=expiry_metadata();worker=record['workers'][1];phase=worker['run']['channel_socket'][0]
            if change=='coordinator-version':record['ssap_subscription_shared_lifetime_contract_version']=True
            elif change=='worker-case':worker['run']['ssap_subscription_shared_case']='release'
            elif change=='worker-version':worker['run'].pop('ssap_subscription_shared_lifetime_contract_version')
            elif change=='missing-flag':worker['args'].remove('--ssap-subscription-shared-case')
            elif change=='wrong-flag':worker['args'][worker['args'].index('--ssap-subscription-shared-case')+1]='release'
            elif change=='phase-case':phase['ssap_subscription_shared_case']='release'
            elif change=='phase-version':phase['ssap_subscription_shared_lifetime_contract_version']=True
            elif change=='wrong-mode':record['shared_subscription_mode']=False
            else:record['ssap_subscription_shared_case']='owner-exit'
            with self.subTest(change=change),self.assertRaises(CaptureError):verify_records(record)

    def test_full_existing_expiry_and_sibling_contracts_are_not_release_evidence(self):
        proof=subscription_parallel_proof(expiry_pairs(),case='expiry')
        self.assertEqual((proof['updates'],proof['application_replies'],proof['partial_expirations'],proof['expired_discarded']),(112,192,16,16))
        for change in ('release-proof','missing-expiry','no-discard','wrong-root-case','wrong-root-expirations','bool-version','missing-wire'):
            pairs=expiry_pairs();pair=pairs[1]
            if change=='release-proof':pairs=release_pairs()
            elif change=='missing-expiry':pair['channel']['proofs'][0]['ssap_subscription'][0].pop('partial_expirations')
            elif change=='no-discard':pair['channel']['proofs'][0]['ssap_subscription'][0]['expired_discarded']=0
            elif change=='wrong-root-case':pair['subscription_supervision']['shared_case']='release'
            elif change=='wrong-root-expirations':pair['subscription_supervision']['partial_expirations']=7
            elif change=='bool-version':pair['subscription_supervision']['shared_lifetime_contract_version']=True
            else:pair['channel']['proofs'][1]['ssap_subscription'][0]['wire'].pop()
            with self.subTest(change=change),self.assertRaises(CaptureError):subscription_parallel_proof(pairs,case='expiry')
        with self.assertRaises(CaptureError):subscription_parallel_proof(expiry_pairs())
        for case in ('owner-exit','pressure',True):
            with self.assertRaises(CaptureError):subscription_parallel_proof(expiry_pairs(),case=case)

    def test_summary_requires_original_case_boot_fresh_preparation_and_witnesses(self):
        self.assertEqual(run_exit_code(release_summary()),0)
        self.assertEqual(run_exit_code(expiry_summary()),0)
        for change in ('missing-boot','duplicate-boot','wrong-boot','missing-fresh-contract','bool-fresh-contract','global-case','no-global-version','fake-discard','old-release-summary','missing-control'):
            record=expiry_summary();proof=record['parallel_corroboration']
            if change=='missing-boot':record['qemu_args'][0]=record['qemu_args'][0].replace(' ws73.subscription_shared_case=expiry','')
            elif change=='duplicate-boot':record['qemu_args'].append('ws73.subscription_shared_case=expiry')
            elif change=='wrong-boot':record['qemu_args'][0]=record['qemu_args'][0].replace('shared_case=expiry','shared_case=owner-exit')
            elif change=='missing-fresh-contract':record.pop('four_subscription_lifetime_contract_version')
            elif change=='bool-fresh-contract':record['four_subscription_lifetime_contract_version']=True
            elif change=='global-case':record['ssap_subscription_shared_case']='release'
            elif change=='no-global-version':record.pop('ssap_subscription_shared_lifetime_contract_version')
            elif change=='fake-discard':proof['shared_subscription']['expired_discarded']=15
            elif change=='old-release-summary':proof['shared_subscription']=release_summary()['parallel_corroboration']['shared_subscription']
            else:proof.pop('parallel_subscription_control')
            with self.subTest(change=change):self.assertEqual(run_exit_code(record),1)

    def test_old_or_invalid_preparation_cannot_enable_expiry_before_file_access(self):
        with tempfile.TemporaryDirectory()as tmp:
            for version in (None,True,0,2,'1'):
                package=dict(four_subscription_contract_version=1)
                if version is not None:package['four_subscription_lifetime_contract_version']=version
                with self.subTest(version=version),self.assertRaises(ValueError):require_subscription_preparation(package,Path(tmp),case='expiry')
