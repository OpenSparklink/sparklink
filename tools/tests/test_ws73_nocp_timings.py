# SPDX-License-Identifier: GPL-2.0-only
"""Post-join timestamp fixtures, not CreditLedger/kernel/hardware validation."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_session_service import nocp_candidates


def fixture():
    key = dict(ctl=0, gen=2, life=3)
    parsed = dict(offset_ns=[1000, 1010], quantum_ns=1, rows=[
        key | dict(event='queue', mono_ns=10),
        key | dict(event='work', mono_ns=80, service=2, stage=0),
        key | dict(event='work', mono_ns=100, service=2, stage=1)])
    owners = {(0, 2, 3): dict(bus=1, device=2, handle=7)}
    capture = dict(native_events=[dict(event=9, bus=1, device=2, params='070001',
                                      record=4, wall_ns=1070)])
    timings = dict(operations=[dict(controller=0, generation=2, lifetime=3, slot=1,
        admission_sequence=5, calls=[
            dict(result=-11, wait=1, offset=0, return_ns=40, acceptance_ns=None),
            dict(result=0, wait=0, offset=0, return_ns=95, acceptance_ns=90, service=2)])])
    return parsed, owners, capture, timings


class CandidateTimes(unittest.TestCase):
    def test_clock_bounds_and_not_causal_contract(self):
        result = nocp_candidates(*fixture())
        self.assertEqual(len(result['episodes']), 1)
        row = result['episodes'][0]
        self.assertEqual((row['wire_to_worker_lower_ns'], row['wire_to_worker_upper_ns']), (9, 21))
        self.assertEqual((row['wire_to_acceptance_lower_ns'], row['wire_to_acceptance_upper_ns']), (19, 31))
        self.assertEqual(row['wire_relation'], 'after_last_refusal')
        self.assertFalse(result['wire'][0]['wire_has_lifetime'])
        self.assertIn('NOT_CAUSAL_OR_CREDIT_PROOF', result['status'])

    def test_missing_different_usb_handle_or_outside_window_not_substituted(self):
        for case in ('missing', 'usb', 'handle', 'before', 'after'):
            args = list(copy.deepcopy(fixture())); events = args[2]['native_events']
            if case == 'missing': events.clear()
            elif case == 'usb': events[0]['device'] = 3
            elif case == 'handle': events[0]['params'] = '080001'
            elif case == 'before': events[0]['wall_ns'] = 1000
            else: events[0]['wall_ns'] = 1200
            with self.subTest(case=case):
                result = nocp_candidates(*args)
                self.assertEqual(result['episodes'], [])
                self.assertEqual(len(result['unmatched']), 1)
                self.assertIsNone(result['metrics']['wire_to_worker_lower_ns']['median_ns'])

    def test_already_running_worker_negative_bounds_not_clamped(self):
        args = list(fixture()); args[0]['rows'][1]['mono_ns'] = 50
        result = nocp_candidates(*args)
        self.assertEqual(result['episodes'][0]['wire_to_worker_upper_ns'], -9)

    def test_zero_and_duplicate_reported_counts_not_simulated_or_deduplicated(self):
        args = list(fixture()); event = args[2]['native_events'][0]; event['params'] = '070000'
        args[2]['native_events'].append(copy.deepcopy(event))
        result = nocp_candidates(*args)
        self.assertEqual(result['wire'][0]['events'], 2)
        self.assertEqual(result['wire'][0]['reported_count_sum'], 0)
        self.assertEqual(len(result['episodes']), 1)

    def test_truncated_vendor_event_and_command_wait_not_mislabeled_data_credit(self):
        args = list(fixture()); args[2]['native_events'][0]['params'] = '0700'
        with self.assertRaisesRegex(ValueError, 'NOCP format'):
            nocp_candidates(*args)
        args = list(fixture()); args[3]['operations'][0]['calls'][0]['wait'] = 2
        self.assertEqual(nocp_candidates(*args)['episodes'], [])
