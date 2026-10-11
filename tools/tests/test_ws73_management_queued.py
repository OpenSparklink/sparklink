# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import unittest
from test_ws73_management_setup import fixture as setup_fixture
from ws73_management_queued import verify_records, corroborate
from sparklink.structs import SleDiscoveryResult


def fixture():
    record = setup_fixture()
    record['status'] = 'QUEUED_MANAGED_RELEASE_LIVE_PASS'
    for n, row in enumerate(record['cases']):
        row.update(critical_start_ns=row['start_wall_ns']+1,
                   critical_end_ns=row['start_wall_ns']+1_000_000, scheduler_restored=True)
        for key, state, error in [('queued', 1, 0), ('cancelled', 5, -errno.ECANCELED)]:
            row[key] = [bytes(SleDiscoveryResult(version=1, generation=row['generation'],
                request_id=(n%3)*2+1+i, profile=1, operation=5+i, count=2+i,
                dev_index=row['index'], state=state, error=error)).hex() for i in [0, 1]]
    return record


class QueuedTests(unittest.TestCase):
    def test_full_canonical_two_domain_six_cases(self):
        record = fixture()
        verify_records(record)
        proof = corroborate(record, {k: [] for k in ['commands', 'complete', 'failures']})
        self.assertTrue(proof['managed_preselection_live_acceptance'])
        self.assertFalse(proof['normal_scheduler_concurrency_acceptance'])
        self.assertFalse(proof['partial_initialization_cleanup_acceptance'])
        self.assertFalse(proof['active_ready_peer_isolation_acceptance'])
        self.assertFalse(proof['managed_preselection_synthetic_support_acceptance'])

    def test_synthetic_scope_cannot_claim_live_acceptance(self):
        record = fixture()
        record['synthetic_support'] = True
        record['status'] = 'QUEUED_MANAGED_RELEASE_SYNTHETIC_SUPPORT_PASS'
        proof = corroborate(record, {k: [] for k in ['commands', 'complete', 'failures']})
        self.assertFalse(proof['managed_preselection_live_acceptance'])
        self.assertTrue(proof['managed_preselection_synthetic_support_acceptance'])
        self.assertFalse(proof['active_ready_peer_isolation_acceptance'])

    def test_scope_status_mismatch_and_non_boolean_rejected(self):
        for synthetic, status in [(True, 'QUEUED_MANAGED_RELEASE_LIVE_PASS'),
                                  (False, 'QUEUED_MANAGED_RELEASE_SYNTHETIC_SUPPORT_PASS'),
                                  (1, 'QUEUED_MANAGED_RELEASE_LIVE_PASS')]:
            record = fixture(); record.update(synthetic_support=synthetic, status=status)
            with self.subTest(synthetic=synthetic, status=status), self.assertRaises(ValueError):
                verify_records(record)

    def test_selected_or_fabricated_result_rejected(self):
        for key in ['queued', 'cancelled']:
            for field, value in [('state', 3), ('opcode', 0xc02), ('step', 1), ('error', 0 if key == 'cancelled' else -125),
                                 ('radio_adv', 1), ('radio_scan', 1), ('power_valid', 1), ('status', 30),
                                 ('request_id', 99), ('generation', 999), ('reserved', (1, 0, 0, 0))]:
                record = fixture()
                result = SleDiscoveryResult.from_buffer_copy(bytes.fromhex(record['cases'][0][key][0]))
                if field == 'reserved': result.reserved[:] = value
                else: setattr(result, field, value)
                record['cases'][0][key][0] = bytes(result).hex()
                with self.subTest(key=key, field=field), self.assertRaises(ValueError): verify_records(record)

    def test_unbounded_or_unrestored_scheduler_rejected(self):
        for field, value in [('scheduler_restored', False), ('scheduler_restored', 1),
                             ('critical_end_ns', 1_050_000_001), ('critical_start_ns', True)]:
            record = fixture(); record['cases'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): verify_records(record)

    def test_traffic_on_either_device_in_gaps_rejected(self):
        for key in ['commands', 'complete', 'failures']:
            capture = {k: [] for k in ['commands', 'complete', 'failures']}
            capture[key] = [{'wall_ns': 1_600_000_000, 'bus': 1, 'device': 3}]
            with self.subTest(key=key), self.assertRaises(ValueError): corroborate(fixture(), capture)

    def test_peer_mutation_and_missing_domain_rejected(self):
        for change in ['peer', 'domain']:
            record = fixture()
            if change == 'peer': record['cases'][0]['peer_after'] = record['initial_snapshots'][0]
            else: record['cases'][0]['cancelled'].pop()
            with self.subTest(change=change), self.assertRaises(ValueError): verify_records(record)
