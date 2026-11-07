# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic decoded-event fixtures; no device, timing or RF qualification."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ws73_connection_control import fixture
from ws73_capture import CaptureError
from ws73_connection_control import observe_down_timing


def timing_fixture():
    run, capture = fixture()
    run['status'] = 'SYNTHETIC_FIXTURE_NOT_QUALIFICATION'
    run['initial'] = copy.deepcopy([run['connection_control']['phases'][0][k] for k in ['caller', 'peer']])
    capture['rx_capture_span'] = dict(version=1, selected_records=20,
        earliest=dict(wall_ns=0), latest=dict(wall_ns=300),
        targets=[[o['bus'], o['device']] for o in run['initial']])
    for n, phase in enumerate(run['connection_control']['phases']):
        phase['start_wall_ns'] = n*100+1
        phase['down_property_observation'] = dict(version=2, budget_seconds=5,
            start_wall_ns=n*100+26, receipts=[])
        for event in capture['native_events']:
            if event['event'] == 0x15 and event['wall_ns'] == n*100+13 and event['device'] == phase['peer']['device']:
                data = bytearray.fromhex(event['params']); data[3] = 1; event['params'] = data.hex()
    return run, capture


class DownTimingTests(unittest.TestCase):
    def test_both_roles_observed_without_gate_or_mutation(self):
        run, capture = timing_fixture(); before = copy.deepcopy((run, capture))
        result = observe_down_timing(run, capture)
        self.assertFalse(result['gate_awarded'])
        self.assertEqual(len(result['phases']), 2)
        self.assertEqual((run, capture), before)
        for phase in result['phases']:
            self.assertFalse(phase['gate_awarded'])
            self.assertEqual({e['link_role'] for e in phase['ends']}, {0, 1})
            self.assertEqual([e['from_usb_disconnect_ns'] for e in phase['ends']], [2, 2])

    def test_original_failure_and_late_raw_down_never_become_gate_success(self):
        run, capture = timing_fixture(); run['connection_control']['phases'] = run['connection_control']['phases'][:1]
        run['status'] = 'FAIL'; run['error'] = 'original shared budget failure'
        capture['native_events'] = [e for e in capture['native_events'] if e['wall_ns'] < 100]
        peer = capture['native_events'][-1]; peer['wall_ns'] = 5_000_000_027
        peer['params'] = '00000007'; capture['rx_capture_span']['latest']['wall_ns'] = peer['wall_ns']
        result = observe_down_timing(run, capture)
        self.assertEqual(result['original_run_status'], 'FAIL')
        self.assertEqual(result['original_error'], run['error'])
        end = result['phases'][0]['ends'][1]
        self.assertEqual(end['reason'], 7)
        self.assertEqual(end['down'], peer)  # Include the final capture timestamp.
        self.assertFalse(end['raw_down_no_later_than_original_deadline'])
        self.assertFalse(result['gate_awarded'])

    def test_missing_down_or_wrong_handle_is_only_bounded_absence(self):
        for wrong_handle in (False, True):
            run, capture = timing_fixture()
            e = next(e for e in capture['native_events'] if e['event'] == 5)
            if wrong_handle: e['params'] = '00010013'
            else: capture['native_events'].remove(e)
            result = observe_down_timing(run, capture)
            end = result['phases'][0]['ends'][0]
            self.assertEqual(end['observation'], 'NOT_OBSERVED_IN_CAPTURE_INTERVAL')
            self.assertIsNone(end['down']); self.assertIsNone(end['raw_down_no_later_than_original_deadline'])

    def test_no_original_disconnect_is_explicitly_not_executed(self):
        run, capture = timing_fixture(); del run['connection_control']['phases'][0]['disconnect_command']
        result = observe_down_timing(run, capture)
        self.assertEqual(result['phases'][0]['observation'], 'NO_ORIGINAL_DISCONNECT')
        self.assertFalse(result['phases'][0]['gate_awarded'])

    def test_corrupt_or_ambiguous_identity_interval_and_events_are_rejected(self):
        for case in ['span', 'target', 'generation', 'peer', 'same-role', 'status', 'completion',
                     'duplicate-down', 'new-up', 'short-down', 'bad-down', 'wrong-target', 'window', 'order']:
            run, capture = timing_fixture(); phase = run['connection_control']['phases'][0]
            down = next(e for e in capture['native_events'] if e['event'] == 5)
            if case == 'span': del capture['rx_capture_span']
            elif case == 'target': capture['rx_capture_span']['targets'].pop()
            elif case == 'generation': phase['caller']['generation'] = 77
            elif case == 'peer': capture['native_events'][1]['params'] = '0000000000'+'ff'*6
            elif case == 'same-role': capture['native_events'][2]['params'] = capture['native_events'][2]['params'][:6]+'00'+capture['native_events'][2]['params'][8:]
            elif case == 'status': capture['native_events'][3]['params'] = '03140101'
            elif case == 'completion': capture['commands'][-1]['completion']['wall_ns'] = 999
            elif case == 'duplicate-down': capture['native_events'].append(copy.deepcopy(down))
            elif case == 'new-up':
                event = copy.deepcopy(capture['native_events'][1]); event['wall_ns'] = 27; capture['native_events'].append(event)
            elif case == 'short-down': down['params'] = '0000'
            elif case == 'bad-down': down['params'] = '01000007'
            elif case == 'wrong-target': next(c for c in capture['commands'] if c['opcode'] == 0x1403)['params'] = '010010'
            elif case == 'window': phase['down_property_observation']['budget_seconds'] = 6
            elif case == 'order': run['commands'][phase['disconnect_command']]['start_wall_ns'] = 1
            with self.subTest(case=case), self.assertRaises(CaptureError):
                observe_down_timing(run, capture)


if __name__ == '__main__':
    unittest.main()
