# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial synthetic captures; never real-device qualification."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_discovery_policy_capture import normalized_dump, query_proofs, wire_proofs
from ws73_parallel import corroborate
from test_ws73_parallel import fixture as historical_fixture


def fixture(custom=False):
    parent, capture = historical_fixture()
    owners = [d for w in parent['workers'] for d in w['run']['initial']]
    address = owners[0]['address']
    dump = 'Ws73DefaultPolicy: version=3 adv_slots=1200..1200 tx_power_dbm=127 scan_slots=1600/800\n'
    if custom:
        dump += f'Ws73AdapterPolicy: address={address} version=3 adv_slots=1237..1237 tx_power_dbm=0 scan_slots=1600/800\n'
    data = {'custom_configuration': custom, 'config_sha256': 'a'*64,
            'daemon_dump': dump, 'policies': normalized_dump(dump)}
    info = {'file': {'path': '/fixture/policies.json', 'sha256': 'b'*64, 'size': 1}, 'data': data}
    parent.update(format_version=2, policy_expectation=info)
    for worker in parent['workers']:
        run = worker['run']
        run['policy_expectation'] = copy.deepcopy(info)
        worker['args'][-2:-2] = ['--policy-expectation', info['file']['path']]
        def show(owner, time):
            policy = data['policies']['adapters'].get(owner['address'], data['policies']['defaults'])
            v, lo, hi, power, interval, window = policy
            stdout = (f"Adapter {owner['path']}:\n  State:       Ready\n  Generation:  {owner['generation']}\n"
                      f"  Address:     {owner['address']}\n  Profile:     1\n"
                      f"  Radio policy: version={v} adv_slots={lo}..{hi} tx_power_dbm={power} scan_slots={interval}/{window}\n")
            return {'args': [run['slctl']['path'], '--adapter', owner['path'], 'show'],
                    'exit': 0, 'stdout': stdout, 'start_wall_ns': time, 'end_wall_ns': time+1}
        end = max(c['end_wall_ns'] for c in run['commands'])+10
        run['commands'] = [show(o, 800_000_000+i*10) for i, o in enumerate(run['initial'])] + run['commands'] + [show(o, end+i*10) for i, o in enumerate(run['initial'])]
        for row in run['rounds']:
            row['command_indices'] = [v+2 for v in row['command_indices']]
    by_route = {(d['bus'], d['device']): d for d in owners}
    for c in capture['commands']:
        if (c['bus'], c['device']) not in by_route:
            continue
        owner = by_route[c['bus'], c['device']]
        if c['opcode'] == 0x0c02:
            b = bytearray(49)
            period = 1237 if custom and owner['address'] == address else 1200
            b[2] = 2; b[3:6] = period.to_bytes(3, 'little'); b[6:9] = period.to_bytes(3, 'little')
            b[9] = 7; b[12:18] = bytes.fromhex(owner['address'].replace(':', ''))
            b[25] = 0 if custom and owner['address'] == address else 127
            b[43:45] = (200).to_bytes(2, 'little'); c['params'] = b.hex()
        if c['opcode'] == 0x1001:
            c['params'] = '0000010040062003'
    return parent, capture


class ConfiguredCaptureTests(unittest.TestCase):
    def test_current_default_requires_query_and_full_parameter_proof(self):
        r, c = fixture()
        proof = corroborate(r, c)
        self.assertTrue(proof['default_parallel_gate_acceptance'])
        self.assertFalse(proof['custom_policy_parallel_contrast_acceptance'])
        self.assertFalse(proof['historical_parameter_scope'])
        self.assertEqual(len(proof['policy_readback_proofs']), 8)
        self.assertTrue(proof['configured_parameter_proofs'])

    def test_custom_policy_at_zero_offset_cannot_certify_default(self):
        r, c = fixture(custom=True)
        proof = corroborate(r, c)
        self.assertFalse(proof['default_parallel_gate_acceptance'])
        self.assertTrue(proof['custom_policy_parallel_contrast_acceptance'])
        self.assertFalse(proof['automatic_fault_recovery_acceptance'])

    def test_config_readback_affinity_timing_and_parameter_mutations_rejected(self):
        for case in ['dump', 'worker-config', 'argv', 'missing-show', 'retired', 'wrong-policy', 'late-initial-show', 'early-final-show', 'adv-channel', 'adv-period', 'adv-power', 'scan-window', 'missing-domain', 'failed-complete']:
            r, c = fixture(custom=True)
            run = r['workers'][0]['run']
            if case == 'dump': r['policy_expectation']['data']['daemon_dump'] += 'unknown\n'
            if case == 'worker-config': run['policy_expectation']['data']['config_sha256'] = 'c'*64
            if case == 'argv': r['workers'][0]['args'][-3] = '/wrong/policies'
            if case == 'missing-show': run['commands'][0]['args'][-1] = 'list'
            if case == 'retired': run['commands'][0]['stdout'] = run['commands'][0]['stdout'].replace('Ready', 'Removed')
            if case == 'wrong-policy': run['commands'][0]['stdout'] = run['commands'][0]['stdout'].replace('1237', '1200')
            if case == 'late-initial-show': run['commands'][0]['end_wall_ns'] = 9_000_000_000
            if case == 'early-final-show': run['commands'][-1]['start_wall_ns'] = 1
            if case.startswith('adv-'):
                command = next(v for v in c['commands'] if v['opcode'] == 0x0c02)
                b = bytearray.fromhex(command['params']); b[{'adv-channel':9, 'adv-period':3, 'adv-power':25}[case]] ^= 1; command['params'] = b.hex()
            if case == 'scan-window': next(v for v in c['commands'] if v['opcode'] == 0x1001)['params'] = '0000010040064006'
            if case == 'missing-domain': c['commands'] = [v for v in c['commands'] if v['opcode'] != 0x1001]
            if case == 'failed-complete': next(v for v in c['complete'] if v['opcode'] == 0x0c02)['status'] = 11
            with self.subTest(case=case), self.assertRaises(ValueError): corroborate(r, c)

    def test_normalized_dump_rejects_incomplete_duplicate_and_unknown_output(self):
        default = 'Ws73DefaultPolicy: version=3 adv_slots=1200..1200 tx_power_dbm=127 scan_slots=1600/800\n'
        row = 'Ws73AdapterPolicy: address=02:73:00:00:00:01 version=3 adv_slots=1237..1237 tx_power_dbm=0 scan_slots=1600/800\n'
        for text in ['', default.replace('version=3', 'version=2'), default+row+row, default+'Configuration valid\n']:
            with self.subTest(text=text), self.assertRaises(ValueError): normalized_dump(text)


if __name__ == '__main__':
    unittest.main()
