# SPDX-License-Identifier: GPL-2.0-only
"""Explicit synthetic initializer fixtures, never hardware/RF acceptance."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_capture import CaptureError, read_capture
from ws73_north_star import parse_result
from ws73_rf_rounds import corroborate_stops
from test_ws73_north_star import aggregate, identity, pcap, transmit


def fixture(operation):
    owner = identity(1)
    adv = operation == 5
    domain = 'advertise' if adv else 'scan'
    sequence = [(0x0c02, bytes(49), b'\xfe'), (0x0c05, bytes(5), b'')] if adv else [
        (0x1001, bytes(8), b''), (0x1002, b'\1\0', b''), (0x1002, b'\0\0', b'')]
    records = []
    for n, (opcode, params, value) in enumerate(sequence):
        moment = 500_000_000 + n*1_000_000
        transmit(records, owner['device'], moment, opcode, params)
        complete = b'\xa2\x02\x00' + (4+len(value)).to_bytes(2, 'little') + opcode.to_bytes(2, 'little') + b'\1\0' + value
        records.append((1, owner['device'], moment, aggregate(complete), 'C', 0x81, 0))
    output = (f'NativeOperationResult: generation=1 request=41 operation={operation} state=3 errno=0 status=0x00 '
              f'opcode=0x{sequence[-1][0]:04x} step={len(sequence)-1}/{len(sequence)} '
              f'power={-2 if adv else 0} power_valid={int(adv)} adv=1 scan=1 profile=1\n')
    run = {'slctl': {'path': '/usr/bin/slctl'}, 'commands': [{
        'args': ['/usr/bin/slctl', '--adapter', owner['path'], domain, 'initialized-off'],
        'exit': 0, 'stdout': output, 'start_wall_ns': 1_000_000_000, 'end_wall_ns': 1_001_000_000}],
        'initialization_off_confirmations': [{'identity': owner, 'domain': domain,
            'query_command': 0, 'request': 41, 'operation': operation}]}
    return run, records


class InitializationOffTests(unittest.TestCase):
    def capture(self, records):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'synthetic.pcap'
            path.write_bytes(pcap(records))
            return read_capture(path, {(1, identity(1)['device'])})

    def test_real_operation_shape_is_kept_and_independent_domain_can_be_on(self):
        for operation in [5, 6]:
            run, records = fixture(operation)
            proof = corroborate_stops(run, self.capture(records))
            self.assertEqual(proof[0]['operation'], operation)
            self.assertFalse(proof[0]['new_stop_submission'])
            self.assertEqual(len(proof[0]['initializer_wire_recipe']), 2 if operation == 5 else 3)
            output = run['commands'][0]['stdout'].replace(('scan' if operation == 5 else 'adv')+'=1',
                                                        ('scan' if operation == 5 else 'adv')+'=2')
            self.assertEqual(parse_result(output, identity(1), operation)['request'], 41)
            with self.assertRaises(ValueError):
                parse_result(output, identity(1), 2 if operation == 5 else 4)

    def test_no_success_from_missing_wire_later_business_or_mutated_result(self):
        for operation in [5, 6]:
            run, records = fixture(operation)
            capture = self.capture(records)
            for changed in [run['commands'][0]['stdout'].replace('status=0x00', 'status=0x0b'),
                            run['commands'][0]['stdout'].replace('generation=1', 'generation=2'),
                            run['commands'][0]['stdout'].replace('state=3', 'state=2'),
                            run['commands'][0]['stdout'].replace('scan=1', 'scan=0'),
                            run['commands'][0]['stdout'].replace(f'operation={operation}', 'operation=4')]:
                bad = copy.deepcopy(run); bad['commands'][0]['stdout'] = changed
                with self.assertRaises((ValueError, CaptureError)): corroborate_stops(bad, capture)
            for field in ['commands', 'complete']:
                bad = copy.deepcopy(capture); bad[field] = bad[field][:-1]
                with self.assertRaises(CaptureError): corroborate_stops(run, bad)
            bad = copy.deepcopy(run)
            earlier = copy.deepcopy(bad['commands'][0]); earlier['args'][-1] = 'on'
            bad['commands'].insert(0, earlier); bad['initialization_off_confirmations'][0]['query_command'] = 1
            with self.assertRaises(CaptureError): corroborate_stops(bad, capture)
            bad = copy.deepcopy(capture); bad['commands'].append(copy.deepcopy(bad['commands'][-1]))
            with self.assertRaises(CaptureError): corroborate_stops(run, bad)
            bad = copy.deepcopy(run); bad['initialization_off_confirmations'][0]['request'] = 42
            with self.assertRaises(CaptureError): corroborate_stops(bad, capture)

    def test_expected_negative_requires_business_history_and_no_success_result(self):
        run, _ = fixture(5)
        row = copy.deepcopy(run['commands'][0]); row.update(exit=1, stdout='', stderr='initializer provenance absent or invalidated')
        run['commands'] = [dict(row, args=row['args'][:-1]+['on']), row]
        run.pop('initialization_off_confirmations')
        run['initialization_off_rejections'] = [{'identity': identity(1), 'domain': 'advertise', 'query_command': 1}]
        self.assertEqual(corroborate_stops(run, {}), [])
        for field, value in [('exit', 0), ('stdout', 'NativeOperationResult: fake'), ('stderr', 'unknown failure')]:
            bad = copy.deepcopy(run); bad['commands'][1][field] = value
            with self.assertRaises(CaptureError): corroborate_stops(bad, {})
        bad = copy.deepcopy(run); bad['commands'][0]['args'][-1] = 'reports'
        with self.assertRaises(CaptureError): corroborate_stops(bad, {})


if __name__ == '__main__':
    unittest.main()
