# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic fixtures for recovery evidence boundaries, never real RF evidence."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import test_ws73_north_star as fixtures
from ws73_capture import CaptureError, corroborate, corroborate_recovery


def recovery_fixture():
    run, records = fixtures.fixture()
    old, new = run['initial'][0], run['replacement']
    new_address, old_address = new['address'], old['address']
    new_device, old_device = new['device'], old['device']

    def convert(value):
        if isinstance(value, dict):
            result = {key: convert(item) for key, item in value.items()}
            if value.get('generation') == new['generation'] and 'device' in value:
                result['device'] = old_device
            return result
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, str):
            return value.replace(new_address, old_address).replace(
                new_address.replace(':', '').lower(), old_address.replace(':', '').lower())
        return value

    run = convert(run)
    run.update(scope='real WS73 RF with artificial guest transport recovery support',
               status='RECOVERY_CONTROL_EVIDENCE_PENDING', physical_acceptance=False,
               automatic_fault_recovery_acceptance=False,
               fault_method='QMP_GUEST_TRANSPORT_ERROR_ONCE', fault_command={'exit': 1})
    run['retirement_observed_wall_ns'] = run.pop('unplug_observed_wall_ns')
    for entry in run['rounds'] + run['negatives']:
        if entry['phase'] == 'replug':
            entry['phase'] = 'recovery'
    wire_old, wire_new = [bytes.fromhex(address.replace(':', ''))
                          for address in [old_address, new_address]]
    records = [(bus, old_device if device == new_device else device, timestamp,
                payload.replace(wire_new, wire_old), kind, endpoint, status)
               for bus, device, timestamp, payload, kind, endpoint, status in records]
    return run, records


class RecoveryCaptureTests(unittest.TestCase):
    read = fixtures.CaptureTests.read

    def setUp(self):
        self.run, records = recovery_fixture()
        self.capture = self.read(fixtures.pcap(records))

    def test_full_fixture_uses_same_usb_identity_and_fresh_queries(self):
        proof = corroborate_recovery(self.run, self.capture)
        self.assertEqual(len(proof), 22)
        self.assertEqual(proof[-1]['phase'], 'recovery')

    def test_support_cannot_be_counted_as_physical_acceptance(self):
        with self.assertRaises(CaptureError):
            corroborate(self.run, self.capture)
        for key, value in [('physical_acceptance', True),
                           ('automatic_fault_recovery_acceptance', True),
                           ('scope', 'physical'), ('fault_method', 'manual replug')]:
            run = copy.deepcopy(self.run)
            run[key] = value
            with self.subTest(key=key), self.assertRaises(CaptureError):
                corroborate_recovery(run, self.capture)

    def test_fault_must_fail_and_cannot_reenumerate(self):
        for exit_code in [0, None, 'timeout']:
            run = copy.deepcopy(self.run)
            run['fault_command']['exit'] = exit_code
            with self.subTest(exit=exit_code), self.assertRaises(CaptureError):
                corroborate_recovery(run, self.capture)
        for key in ['bus', 'device', 'address']:
            run = copy.deepcopy(self.run)
            run['replacement'][key] = 99 if key != 'address' else '02:00:00:00:00:99'
            with self.subTest(key=key), self.assertRaises(CaptureError):
                corroborate_recovery(run, self.capture)

    def test_old_phase_and_pre_retirement_metadata_do_not_qualify(self):
        run = copy.deepcopy(self.run)
        run['rounds'][-1]['phase'] = 'replug'
        with self.assertRaises(CaptureError):
            corroborate_recovery(run, self.capture)
        capture = copy.deepcopy(self.capture)
        for entry in capture['commands']:
            if entry['opcode'] == 0x0406 and entry['wall_ns'] > 8_000_000_000:
                entry['wall_ns'] = 500_000_000
        with self.assertRaises(CaptureError):
            corroborate_recovery(self.run, capture)


if __name__ == '__main__':
    unittest.main()
