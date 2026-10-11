# SPDX-License-Identifier: GPL-2.0-only
"""Evidence rejection and QMP dependency fixtures; never hardware acceptance."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ws73_daemon_hold import fixture as held_fixture
from ws73_daemon_removal import RemovalCoordinator, RESET_OPTIONS, corroborate, verify_records
from ws73_diagnostic_hold import PROPERTIES, write_marker
from ws73_target import usb_properties


def fixture():
    r, h, c, _ = held_fixture()
    r.update(format_version=1, status='DAEMON_CANCEL_REMOVAL_EVIDENCE_PENDING',
             cancel_pending_before_remove=True, remove_ready_wall_ns=2800,
             remove_ack_observed_wall_ns=3100, readd_ready_wall_ns=4500, readd_ack_observed_wall_ns=4850,
             acknowledgement_observed_wall_ns=[1050, 1250])
    r.pop('case')
    r['markers'] = r['markers'][:2]
    r['hold_acknowledgements'] = r['hold_acknowledgements'][:2]
    r['original_caller']['end_wall_ns'] = 2600
    r['cancel_caller'].update(exit=1, stdout='NativePoliciesCancelRequest: generation=1\n', stderr='No such device (os error 19)')
    r['management_revoking'] = dict(args=['/bin/slctl', '--adapter', r['target']['path'], 'management'], exit=0, stderr='', stdout='NativeManagementStatus: generation=1 mode=0 state=2 flags=0 errno=0 status=0x00 opcode=0x0000\n', start_wall_ns=2650, end_wall_ns=2700)
    r['peer_on_after_remove'] = r.pop('peer_on_after_drain')
    r['retired_selection'] = dict(args=['/bin/slctl', '--adapter', r['target']['path'], 'show'], exit=1, stdout='', stderr='not a live registration', start_wall_ns=4300, end_wall_ns=4400)
    r['retirement_polls'] = [r['retired_selection']]
    r['replacement'] = dict(r['target'], generation=3, path='/org/sparklink/slk0_g3', device=4)
    r['retired_after_readd'] = dict(r['retired_selection'], start_wall_ns=4900, end_wall_ns=5000)
    h.update(method='QMP_REMOVE_ACTUAL_HELD_IN81', observations=r['hold_acknowledgements'],
             before_remove_state=copy.deepcopy(r['hold_acknowledgements'][1]['state']),
             reset_options=dict.fromkeys(RESET_OPTIONS, False), removed_id='ws73_0',
             delete_request_wall_ns=2900, delete_ack_wall_ns=3000, readd_wall_ns=4800,
             readd_properties=usb_properties('1-2.1.4', 0))
    peer = dict(state=dict(zip(PROPERTIES, [False, False, 0, 0, 0, 0, False, 0])), options=dict.fromkeys(RESET_OPTIONS, False) | {'attached': True})
    h.update(peer_before_remove=copy.deepcopy(peer), peer_after_remove=copy.deepcopy(peer))
    c['complete'] = [v for v in c['complete'] if v['device'] != 2]
    c['failures'] = [dict(bus=1, device=2, wall_ns=3150, status=-2, endpoint=0x81, record=77)]
    log = 'WS73_TEST_RUNTIME_HOLD: dev 1:124 bytes=178 host_status=0 holds=1 sha256='+'a'*64+'\nWS73_TEST_RUNTIME_HOLD_DROP: dev 1:124 bytes=178 drops=1 sha256='+'a'*64+'\n'
    return r, h, c, log


class RemovalTests(unittest.TestCase):
    def test_original_cancel_then_real_error_and_peer_success_are_separate(self):
        r, h, c, log = fixture()
        proof = corroborate(r, h, c, log, dict(path='1-2.1.4', bus=1, address=124))
        self.assertEqual(len(proof['peer']), 3)
        self.assertTrue(proof['guest_cancel_removal_support_acceptance'])
        for k in ['whole_managed_acceptance', 'physical_acceptance', 'automatic_fault_recovery_acceptance', 'natural_fault_root_cause_closed']:
            self.assertFalse(proof[k])

    def test_false_success_wrong_generation_clock_affinity_and_peer_disturbance_fail(self):
        for change in ['success', 'fake-confirm', 'wrong-error', 'old-success', 'wrong-generation', 'wrong-affinity', 'not-revoking', 'token', 'no-pending', 'root', 'caps', 'daemon', 'bus', 'peer-generation', 'peer-off', 'peer-error', 'not-retired', 'missing-history', 'wrong-clock', 'timeout']:
            r, h, c, log = fixture()
            if change == 'success': r['cancel_caller']['exit'] = 0
            if change == 'fake-confirm': r['cancel_caller']['stdout'] += 'NativePoliciesCancelled: generation=1\n'
            if change == 'wrong-error': r['cancel_caller']['stderr'] = 'permission denied'
            if change == 'old-success': r['original_caller']['stdout'] = r['original_caller']['stdout'].replace('state=5', 'state=3')
            if change == 'wrong-generation': r['cancel_caller']['generation'] = 2
            if change == 'wrong-affinity': r['pending']['args'][2] = r['peer']['path']
            if change == 'not-revoking': r['management_revoking']['stdout'] = r['management_revoking']['stdout'].replace('state=2', 'state=1')
            if change == 'token': r['management_revoking']['stdout'] += 'lease=1\n'
            if change == 'no-pending': r['cancel_pending_before_remove'] = False
            if change == 'root': r['application_identity']['uids'] = [0]*4
            if change == 'caps': r['application_identity']['cap_eff'] = '1'
            if change == 'daemon': r['daemon_after']['pid'] += 1
            if change == 'bus': r['bus_after']['owner'] = ':1.9'
            if change == 'peer-generation': r['peer_after'] = dict(r['peer_after'], generation=3)
            if change == 'peer-off': r['peer_on_after_remove']['stdout'] = r['peer_on_after_remove']['stdout'].replace('scan=2', 'scan=1')
            if change == 'peer-error': r['peer_stop']['exit'] = 1
            if change == 'not-retired': r['retired_selection']['exit'] = 0
            if change == 'missing-history': r['cancel_polls'] = []
            if change == 'wrong-clock': r['remove_ready_wall_ns'] = 1000
            if change == 'timeout': r['remove_ready_wall_ns'] = r['original_caller']['start_wall_ns']+400_000_000
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_records(r)

    def test_old_delivered_reply_extra_command_missing_drop_and_peer_errors_fail(self):
        for change in ['old-reply', 'extra-start', 'no-retirement', 'peer-failure', 'missing-original', 'missing-drop', 'double-drop', 'wrong-sha', 'wrong-host', 'explicit-release', 'bounded-release', 'wrong-id', 'reset', 'peer-detach', 'wrong-readd', 'early-error', 'deadline']:
            r, h, c, log = fixture()
            if change == 'old-reply': c['complete'].append(dict(c['complete'][0], device=2, wall_ns=3100, opcode=0x1001))
            if change == 'extra-start': c['commands'].append(dict(c['commands'][0], wall_ns=2700, opcode=0x1002))
            if change == 'no-retirement': c['failures'] = []
            if change == 'peer-failure': c['failures'].append(dict(c['failures'][0], device=3))
            if change == 'missing-original': c['commands'] = [v for v in c['commands'] if v['device'] != 2]
            if change == 'missing-drop': log = log.split('WS73_TEST_RUNTIME_HOLD_DROP:')[0]
            if change == 'double-drop': log += log.splitlines()[1]+'\n'
            if change == 'wrong-sha': log = log.replace('drops=1 sha256='+'a'*64, 'drops=1 sha256='+'b'*64)
            if change == 'wrong-host': log = log.replace('dev 1:124', 'dev 1:125')
            if change == 'explicit-release': log += 'WS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:124 bytes=178 bounded=0 releases=1\n'
            if change == 'bounded-release': h['before_remove_state']['test-runtime-in-bounded-releases'] = 1
            if change == 'wrong-id': h['removed_id'] = 'ws73_1'
            if change == 'reset': h['reset_options']['host-reset'] = True
            if change == 'peer-detach': h['peer_after_remove']['options']['attached'] = False
            if change == 'wrong-readd': h['readd_properties']['hostport'] = '2.1.3'
            if change == 'early-error': h['delete_request_wall_ns'] = 3500
            if change == 'deadline': h['delete_request_wall_ns'] += 400_000_000
            with self.subTest(change=change), self.assertRaises(ValueError):
                corroborate(r, h, c, log, dict(path='1-2.1.4', bus=1, address=124))

    def test_clock_offset_does_not_require_equal_host_and_guest_walls(self):
        r, h, c, log = fixture()
        skew = 950_000_000
        for ack in h['observations']: ack['host_wall_ns'] += skew
        for key in ['delete_request_wall_ns', 'delete_ack_wall_ns', 'readd_wall_ns']: h[key] += skew
        p = corroborate(r, h, c, log, dict(path='1-2.1.4', bus=1, address=124))
        self.assertFalse(p['clocks']['raw_wall_clocks_assumed_equal'])
        self.assertGreater(p['clocks']['host_minus_guest_ns'][0], 900_000_000)
        h['delete_ack_wall_ns'] += 1_000_000_000
        with self.assertRaisesRegex(ValueError, 'clock bounds'):
            corroborate(r, h, c, log, dict(path='1-2.1.4', bus=1, address=124))

    def test_removal_coordinator_never_releases_and_only_observes_peer(self):
        from test_ws73_diagnostic_hold import Monitor
        class TwoMonitors(Monitor):
            def execute(self, command, args):
                if args['path'].endswith('ws73_1'):
                    if command != 'qom-get': raise AssertionError('peer must not be mutated')
                    key = args['property']
                    return dict(zip(PROPERTIES, [False, False, 0, 0, 0, 0, False, 0])).get(key, self.options.get(key))
                return super().execute(command, args)
        with tempfile.TemporaryDirectory() as tmp:
            monitor = TwoMonitors()
            host = {}
            gate = RemovalCoordinator(tmp, host)
            gate.folder.mkdir(parents=True)
            write_marker(gate.folder/'hold-arm_ready.json', dict(hold_phase='arm_ready', wall_ns=1))
            gate.poll(monitor)
            monitor.state.update({'test-runtime-in-hold-once': False, 'test-runtime-in-held': True, 'test-runtime-in-holds': 1})
            write_marker(gate.folder/'hold-wait_held.json', dict(hold_phase='wait_held', wall_ns=2))
            gate.poll(monitor)
            self.assertEqual(gate.phase, 'await_remove')
            gate.poll(monitor)
            gate.before_remove(monitor)
            gate.after_remove(monitor)
            gate.after_readd(usb_properties('1-2.1.4', 0))
            self.assertTrue(host['complete'])
            self.assertEqual([s['property'] for s in monitor.sets], ['test-runtime-in-hold-once'])
            self.assertEqual([s['stage'] for s in host['observations']], ['armed', 'held'])

    def test_incompatible_gate_modes_rejected_before_output_creation(self):
        import ws73_target
        for changes in [dict(command='support'), dict(qmp_hotplug=False), dict(fault_recovery=True), dict(daemon_hold_case='cancel-busy'), dict(diagnostic_verify=True), dict(setup_release_verify=True)]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)/'never-created'
                args = dict(command='run', output=output, qmp_hotplug=True, daemon_cancel_remove=True)
                args.update(changes)
                with patch.object(ws73_target, 'ordinary_identity'), self.assertRaisesRegex(ValueError, 'held daemon cancel/removal requires'):
                    ws73_target._run(SimpleNamespace(**args))
                self.assertFalse(output.exists())
