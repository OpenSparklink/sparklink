# SPDX-License-Identifier: GPL-2.0-only
"""Independent config/wire observation fixtures; no daemon, USB or RF test."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_connection_control import explicit_connection_policy, configured_create_body, observe_connection_policy
from test_ws73_connection_control import fixture

CONFIG = '''[ws73.connection]
filter=0
own_address_type=0
gt_negotiate=1
frame=1
scan_interval=32
scan_window=32
interval_min=12
interval_max=12
latency=0
supervision_timeout=508
event_min=0
event_max=0
timeout_ms=10000
'''


def observation():
    run, capture = fixture()
    for phase in run['connection_control']['phases']:
        command = run['commands'][phase['connect_command']]
        phase['links_command'] = len(run['commands'])
        caller, peer = phase['caller'], phase['peer']
        run['commands'].append(dict(args=['slctl', 'connections'], exit=0,
            start_wall_ns=command['end_wall_ns'], end_wall_ns=command['end_wall_ns']+1,
            stdout=f"NativeLinksSnapshot: generation={caller['generation']} event_seq=2 revision=1 flags=1 errno=0\n"
                   f"NativeLink: lifetime=1 handle=0 role=0 type=0 address={peer['address']}\n"))
    for command in capture['commands']:
        if command['opcode'] == 0x1401:
            # Fixed dialect vector, not the encoder under test.
            command['params'] = command['params'][:18]+'0101200020000c000c000000fc0100000000'
    for event in capture['native_events']:
        if event['event'] == 0x15:
            body = bytearray.fromhex(event['params'])
            phase = next(p for p in run['connection_control']['phases']
                         if run['commands'][p['connect_command']]['start_wall_ns'] < event['wall_ns']
                         < run['commands'][p['connect_command']]['end_wall_ns'])
            body[3] = int(event['device'] == phase['peer']['device'])
            event['params'] = body.hex()+'00'*12+'0c000000fc0100'
            event['record'] = event['wall_ns']
    return run, capture


class ExplicitPolicy(unittest.TestCase):
    def test_no_defaults_coercion_or_unknown_fields(self):
        self.assertEqual(explicit_connection_policy(CONFIG)['interval_min'], 12)
        for text in [CONFIG.replace('frame=1\n', ''), CONFIG+'unknown=0\n',
                     CONFIG.replace('frame=1', 'frame=true'), CONFIG.replace('frame=1', 'frame=256'),
                     CONFIG.replace('interval_min=12', 'interval_min=13'),
                     CONFIG.replace('timeout_ms=10000', 'timeout_ms=0'),
                     CONFIG.replace('scan_interval=32', 'scan_interval=65536')]:
            with self.subTest(text=text), self.assertRaises(CaptureError):
                explicit_connection_policy(text)

    def test_reference_vector_both_real_roles_and_raw_units_only(self):
        policy = explicit_connection_policy(CONFIG)
        self.assertEqual(configured_create_body(policy, 0, '01:02:03:04:05:06').hex(),
                         '0000000102030405060101200020000c000c000000fc0100000000')
        run, capture = observation()
        proof = observe_connection_policy(run, capture, policy)
        self.assertEqual([p['outcomes'][0]['raw_interval'] for p in proof['phases']], [12, 12])
        self.assertFalse(proof['performance_qualified'])

    def test_whole_requested_body_not_just_peer_or_captured_echo(self):
        run, capture = observation()
        for offset in (0, 1, 9, 10, 11, 13, 15, 17, 19, 21, 23, 25):
            changed = copy.deepcopy(capture)
            command = next(v for v in changed['commands'] if v['opcode'] == 0x1401)
            data = bytearray.fromhex(command['params']); data[offset] ^= 1
            command['params'] = data.hex()
            with self.subTest(offset=offset), self.assertRaises(CaptureError):
                observe_connection_policy(run, changed, explicit_connection_policy(CONFIG))

    def test_outcome_shape_effective_range_agreement_roles_and_missing_end(self):
        run, capture = observation()
        for case in ('short', 'extra', 'interval', 'latency', 'supervision', 'role', 'missing'):
            changed = copy.deepcopy(capture)
            event = [v for v in changed['native_events'] if v['event'] == 0x15][1]
            data = bytearray.fromhex(event['params'])
            if case == 'short': data.pop()
            elif case == 'extra': data.append(0)
            elif case == 'missing': changed['native_events'].remove(event)
            else: data[{'interval': 23, 'latency': 25, 'supervision': 27, 'role': 3}[case]] ^= 1
            event['params'] = data.hex()
            with self.subTest(case=case), self.assertRaises(CaptureError):
                observe_connection_policy(run, changed, explicit_connection_policy(CONFIG))
