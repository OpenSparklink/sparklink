# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_management_setup import metadata_ready, verify_records, corroborate, save_record
from ws73_diagnostic_hold import write_marker
from sparklink.structs import SleControllerSnapshot, SleDiscoveryResult, SleManagementQuery


def fixture():
    snapshots = [bytes(SleControllerSnapshot(version=1, generation=i+1, dev_index=i, flags=2,
                                            profile=1, valid_fields=1)).hex() for i in [0, 1]]
    record = {'format_version': 1, 'status': 'UNTOUCHED_SETUP_RELEASE_LIVE_PASS', 'probe_exit': 0,
              'daemon_running': False, 'physical_acceptance': False, 'automatic_fault_recovery_acceptance': False,
              'initial_snapshots': snapshots, 'cases': []}
    for i in [0, 1]:
        for kind in ['explicit-release', 'last-fd-close', 'dup-last-fd-close']:
            held = bytes(SleManagementQuery(version=1, generation=i+1, mode=1, state=1)).hex()
            free = bytes(SleManagementQuery(version=1, generation=i+1)).hex()
            radio = bytes(SleDiscoveryResult(version=1, generation=i+1)).hex()
            start = 1_000_000_000+len(record['cases'])*1_000_000_000
            record['cases'].append({'case': kind, 'index': i, 'generation': i+1, 'peer_index': 1-i,
                                    'peer_generation': 2-i, 'start_wall_ns': start, 'end_wall_ns': start+400_000_000,
                                    'writer_fd': 5, 'duplicate_fd': 6 if kind == 'dup-last-fd-close' else -1,
                                    'wrong_token_errno': errno.EPERM if kind == 'explicit-release' else 0,
                                    'snapshot_before': snapshots[i], 'snapshot_after': snapshots[i],
                                    'peer_before': snapshots[1-i], 'peer_after': snapshots[1-i],
                                    'radio_before': radio, 'radio_after': radio, 'held': held, 'free': free,
                                    'after_first_close': held if kind == 'dup-last-fd-close' else '0'*len(held)})
    return record


class SetupReleaseTests(unittest.TestCase):
    def test_progress_replacement_persists_second_metadata_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); record = {'status': 'RUNNING', 'initial_snapshots': ['first']}
            save_record(folder, record)
            record['initial_snapshots'].append('second'); save_record(folder, record)
            self.assertEqual(json.loads((folder/'run.json').read_text()), record)
            record['status'] = 'FAIL'; record['error'] = 'actual probe failure'; save_record(folder, record)
            self.assertEqual(json.loads((folder/'run.json').read_text()), record)
            self.assertFalse((folder/'run.tmp').exists())

    def test_record_replacement_does_not_relax_one_shot_attachment_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'metadata-0.json'; value = {'slot': 0, 'initial_snapshot': fixture()['initial_snapshots'][0]}
            write_marker(path, value)
            with self.assertRaises(ValueError): write_marker(path, value)
            self.assertEqual(json.loads(path.read_text()), value)

    def test_complete_fixture_validates_bytes_only_not_hardware(self):
        identities = verify_records(fixture())
        self.assertEqual([s.flags for s in identities], [2, 2])
        proof = corroborate(fixture(), {k: [] for k in ['commands', 'complete', 'failures']})
        self.assertFalse(proof['partial_initialization_cleanup_acceptance'])
        self.assertFalse(proof['held_transport_fd_close_acceptance'])
        self.assertFalse(proof['automatic_fault_recovery_acceptance'])

    def test_all_modes_and_both_registration_roles_are_required(self):
        for change in ['missing', 'reordered', 'duplicate', 'wrong-peer', 'wrong-generation']:
            record = fixture()
            if change == 'missing': record['cases'].pop()
            if change == 'reordered': record['cases'].reverse()
            if change == 'duplicate': record['cases'][1] = copy.deepcopy(record['cases'][0])
            if change == 'wrong-peer': record['cases'][0]['peer_index'] = 0
            if change == 'wrong-generation': record['cases'][0]['generation'] = 3
            with self.subTest(change=change), self.assertRaises(ValueError): verify_records(record)

    def test_fake_ready_off_or_changed_survivor_is_rejected(self):
        for key, field, value in [('snapshot_after', 'flags', 1), ('snapshot_after', 'generation', 4),
                                  ('peer_after', 'error', -5), ('peer_after', 'dev_index', 0)]:
            record = fixture(); row = record['cases'][0]
            s = SleControllerSnapshot.from_buffer_copy(bytes.fromhex(row[key])); setattr(s, field, value)
            row[key] = bytes(s).hex()
            with self.subTest(key=key, field=field), self.assertRaises(ValueError): verify_records(record)
        record = fixture(); row = record['cases'][0]
        radio = SleDiscoveryResult.from_buffer_copy(bytes.fromhex(row['radio_after'])); radio.radio_adv = 1
        row['radio_before'] = row['radio_after'] = bytes(radio).hex()
        with self.assertRaises(ValueError): verify_records(record)

    def test_dup_must_hold_until_last_reference_close_and_hide_token(self):
        for field, value in [('state', 0), ('lease', 1), ('flags', 1), ('error', -5), ('status', 30)]:
            record = fixture(); row = record['cases'][2]
            q = SleManagementQuery.from_buffer_copy(bytes.fromhex(row['after_first_close'])); setattr(q, field, value)
            row['after_first_close'] = bytes(q).hex()
            with self.subTest(field=field), self.assertRaises(ValueError): verify_records(record)

    def test_short_or_overlapping_quiet_intervals_are_rejected(self):
        for change in ['short', 'overlap', 'unordered', 'unbounded']:
            record = fixture(); row = record['cases'][1]
            if change == 'short': row['end_wall_ns'] = row['start_wall_ns']+1
            if change == 'overlap': row['start_wall_ns'] = record['cases'][0]['end_wall_ns']
            if change == 'unordered': row['end_wall_ns'] = row['start_wall_ns']-1
            if change == 'unbounded': row['end_wall_ns'] = row['start_wall_ns']+10_000_000_000
            with self.subTest(change=change), self.assertRaises(ValueError): verify_records(record)

    def test_boolean_identity_and_success_downgrade_are_rejected(self):
        for field in ['index', 'generation', 'peer_index', 'peer_generation', 'wrong_token_errno']:
            record = fixture(); record['cases'][0][field] = bool(record['cases'][0][field])
            with self.subTest(field=field), self.assertRaises(ValueError): verify_records(record)
        for field, value in [('format_version', True), ('probe_exit', False), ('daemon_running', True),
                             ('automatic_fault_recovery_acceptance', True), ('physical_acceptance', True)]:
            record = fixture(); record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): verify_records(record)

    def test_wire_traffic_in_case_or_between_cases_fails(self):
        for key in ['commands', 'complete', 'failures']:
            for wall in [1_000_000_000, 1_200_000_000, 1_600_000_000, 6_400_000_000]:
                capture = {k: [] for k in ['commands', 'complete', 'failures']}; capture[key] = [{'wall_ns': wall}]
                with self.subTest(key=key, wall=wall), self.assertRaises(ValueError): corroborate(fixture(), capture)

    def test_peer_attachment_requires_atomic_setup_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp); self.assertFalse(metadata_ready(share)); folder = share/'setup-release'; folder.mkdir()
            marker = folder/'metadata-0.json'; raw = fixture()['initial_snapshots'][0]
            marker.write_text(json.dumps({'slot': 0, 'initial_snapshot': raw})); self.assertTrue(metadata_ready(share))
            for field, value in [('flags', 1), ('flags', 4), ('profile', 0), ('dev_index', 1), ('generation', 0)]:
                s = SleControllerSnapshot.from_buffer_copy(bytes.fromhex(raw)); setattr(s, field, value)
                marker.write_text(json.dumps({'slot': 0, 'initial_snapshot': bytes(s).hex()}))
                with self.subTest(field=field), self.assertRaises(ValueError): metadata_ready(share)
