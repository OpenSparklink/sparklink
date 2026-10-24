# SPDX-License-Identifier: GPL-2.0-only
"""Original pressure metadata composition, not Native or real queue qualification.

Reuse existing release fixtures and actual validators. Opaque wire/security rows
only test the report contract; no successful SDK, kernel or peer is stubbed.
Actual independent reader outputs, queue contents, refusals and application
replies still require the full existing controlled VM/capture gate.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from test_ws73_parallel_subscription import metadata_fixture, pairs_fixture, summary_fixture
from ws73_capture import CaptureError
from ws73_parallel_data import subscription_parallel_proof, verify_records
from ws73_ssap_subscription import requested, requested_shared_case
from ws73_target import require_subscription_preparation, run_exit_code, validate_business_mode


def pressure_metadata():
    record = metadata_fixture()
    for row in [record, *[w['run'] for w in record['workers']]]:
        row.update(ssap_subscription_shared_case='pressure', ssap_subscription_shared_pressure_contract_version=1)
    for worker in record['workers']:
        worker['args'][-2:-2] = ['--ssap-subscription-shared-case', 'pressure']
        for phase in worker['run']['channel_socket']:
            phase.update(ssap_subscription_shared_case='pressure', ssap_subscription_shared_contract_version=1,
                         ssap_subscription_shared_pressure_contract_version=1)
    return record


def pressure_pairs():
    pairs = pairs_fixture()
    for pair in pairs:
        pair['subscription_supervision'].update(shared_case='pressure', shared_pressure_contract_version=1,
            updates=176, checked_replies=328, slow_notification_drops=4, slow_indication_refusals=4,
            healthy_losses=0, ordered_drains=8, resumed=8, healthy_replies=176)
        for row in pair['channel']['proofs']:
            for value in row['ssap_subscription']:
                wire = value['wire']
                value.update(shared_case='pressure', shared_pressure_contract_version=1, updates=44,
                    application_replies=82, slow_notification_drops=1, slow_indication_refusals=1,
                    healthy_losses=0, ordered_drains=2, resumed=2, healthy_replies=44)
                # Finite opaque rows for the real summary validator, not parser input.
                value['wire'] = [copy.deepcopy(wire[n % len(wire)]) for n in range(252)]
    return pairs


def pressure_summary():
    record = summary_fixture()
    record.update(ssap_subscription_shared_case='pressure', ssap_subscription_shared_pressure_contract_version=1,
                  four_subscription_pressure_contract_version=1)
    record['qemu_args'][0] += ' ws73.subscription_shared_case=pressure'
    pairs, control = pressure_pairs(), pressure_metadata()
    for pair, worker in zip(pairs, control['workers'], strict=True):
        pair['subscription_supervision']['daemon'] = copy.deepcopy(worker['run']['daemon_before'])
    record['parallel_corroboration'].update(pairs=pairs, parallel_subscription_control=control,
                                         shared_subscription=subscription_parallel_proof(pairs, case='pressure'))
    return record


class FourOriginalSharedPressure(unittest.TestCase):
    def test_explicit_four_case_does_not_enable_standalone_or_other_scopes(self):
        args = SimpleNamespace(command='run', four_device_shared_subscription=True,
                               ssap_subscription_shared_case='pressure')
        validate_business_mode(args)
        self.assertEqual(requested_shared_case(args, four_pair=True), 'pressure')
        self.assertFalse(requested(args, passthrough=False))
        with self.assertRaises(ValueError):
            requested_shared_case(args)
        self.assertEqual(requested_shared_case(SimpleNamespace(ssap_subscription_shared_verify=True,
                          ssap_subscription_shared_case='pressure')), 'pressure')

    def test_original_coordinator_worker_cli_and_phase_are_same_typed_case(self):
        self.assertEqual(len(verify_records(pressure_metadata())), 4)
        for change in ('version', 'lifetime', 'worker', 'worker-version', 'cli', 'phase', 'phase-version', 'mode'):
            record = pressure_metadata(); worker = record['workers'][0]; phase = worker['run']['channel_socket'][1]
            if change == 'version': record['ssap_subscription_shared_pressure_contract_version'] = True
            elif change == 'lifetime': record['ssap_subscription_shared_lifetime_contract_version'] = 1
            elif change == 'worker': worker['run']['ssap_subscription_shared_case'] = 'owner-exit'
            elif change == 'worker-version': worker['run'].pop('ssap_subscription_shared_pressure_contract_version')
            elif change == 'cli': worker['args'][worker['args'].index('--ssap-subscription-shared-case') + 1] = 'release'
            elif change == 'phase': phase['ssap_subscription_shared_case'] = 'release'
            elif change == 'phase-version': phase['ssap_subscription_shared_pressure_contract_version'] = False
            else: record['shared_subscription_mode'] = False
            with self.subTest(change=change), self.assertRaises(CaptureError):
                verify_records(record)

    def test_full_original_queue_contracts_cannot_be_reduced_or_relabelled(self):
        proof = subscription_parallel_proof(pressure_pairs(), case='pressure')
        self.assertEqual((proof['updates'], proof['application_replies'], proof['healthy_replies']), (352, 656, 352))
        self.assertEqual((proof['slow_notification_drops'], proof['slow_indication_refusals'], proof['healthy_losses']), (8, 8, 0))
        self.assertEqual((proof['ordered_drains'], proof['resumed'], proof['retained_releases'], proof['last_disables']), (16, 16, 32, 16))
        self.assertNotIn('shared_lifetime_contract_version', proof)
        for change in ('release', 'missing-refusal', 'healthy-loss', 'reduced-updates', 'missing-wire', 'bool-drop', 'root-loss', 'root-drain', 'lifetime'):
            pairs = pressure_pairs(); item = pairs[1]['channel']['proofs'][0]['ssap_subscription'][0]
            if change == 'release': pairs = pairs_fixture()
            elif change == 'missing-refusal': item.pop('slow_indication_refusals')
            elif change == 'healthy-loss': item['healthy_losses'] = 1
            elif change == 'reduced-updates': item['updates'] = 14
            elif change == 'missing-wire': item['wire'].pop()
            elif change == 'bool-drop': item['slow_notification_drops'] = True
            elif change == 'root-loss': pairs[1]['subscription_supervision']['healthy_losses'] = 1
            elif change == 'root-drain': pairs[1]['subscription_supervision']['ordered_drains'] = 7
            else: pairs[1]['subscription_supervision']['shared_lifetime_contract_version'] = 1
            with self.subTest(change=change), self.assertRaises(CaptureError):
                subscription_parallel_proof(pairs, case='pressure')
        with self.assertRaises(CaptureError):
            subscription_parallel_proof(pressure_pairs())

    def test_summary_requires_pressure_specific_fresh_preparation_and_boot(self):
        self.assertEqual(run_exit_code(pressure_summary()), 0)
        for change in ('no-boot', 'duplicate-boot', 'wrong-boot', 'no-fresh', 'bool-fresh', 'lifetime-fresh', 'lifetime-extra', 'missing-count', 'false-count', 'fake-fault', 'release-proof', 'no-control'):
            record = pressure_summary(); proof = record['parallel_corroboration']
            if change == 'no-boot': record['qemu_args'][0] = record['qemu_args'][0].replace(' ws73.subscription_shared_case=pressure', '')
            elif change == 'duplicate-boot': record['qemu_args'].append('ws73.subscription_shared_case=pressure')
            elif change == 'wrong-boot': record['qemu_args'][0] = record['qemu_args'][0].replace('shared_case=pressure', 'shared_case=owner-exit')
            elif change == 'no-fresh': record.pop('four_subscription_pressure_contract_version')
            elif change == 'bool-fresh': record['four_subscription_pressure_contract_version'] = True
            elif change == 'lifetime-fresh': record['four_subscription_lifetime_contract_version'] = record.pop('four_subscription_pressure_contract_version')
            elif change == 'lifetime-extra': record['four_subscription_lifetime_contract_version'] = 1
            elif change == 'missing-count': proof['shared_subscription'].pop('slow_notification_drops')
            elif change == 'false-count': proof['shared_subscription']['healthy_replies'] = 351
            elif change == 'fake-fault': proof['shared_subscription']['fault_isolation_acceptance'] = True
            elif change == 'release-proof': proof['shared_subscription'] = summary_fixture()['parallel_corroboration']['shared_subscription']
            else: proof.pop('parallel_subscription_control')
            with self.subTest(change=change):
                self.assertEqual(run_exit_code(record), 1)

    def test_old_lifetime_preparation_does_not_authorize_pressure(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in (None, True, 0, 2, '1'):
                package = dict(four_subscription_contract_version=1, four_subscription_lifetime_contract_version=1)
                if version is not None:
                    package['four_subscription_pressure_contract_version'] = version
                with self.subTest(version=version), self.assertRaises(ValueError):
                    require_subscription_preparation(package, Path(tmp), case='pressure')
