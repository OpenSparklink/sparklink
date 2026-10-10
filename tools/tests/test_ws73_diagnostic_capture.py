# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic query-window fixtures; no syscall or hardware acceptance."""
import copy
import struct
import unittest

from test_ws73_diagnostic_probe import fixture, admission_fixture
from ws73_capture import CaptureError, command_reply, corroborate_diagnostic, json_identity
from ws73_diagnostic_probe import QUERIES


def inputs():
    owner = {'port': '1-1', 'index': 0, 'generation': 7, 'bus': 1, 'device': 2, 'observed_wall_ns': 10000,
             'address': '01:02:03:04:05:06', 'features': '0102030405060708090a',
             'version': '0102030405', 'buffers': [513, 2, 514, 3]}
    values = {0x0406: '010203040506', 0x0403: owner['features'], 0x0404: owner['version'],
              0x0402: struct.pack('<HBHB', *owner['buffers']).hex()}
    diagnostic = {'status': 'DIAGNOSTIC_RESULT_LIVE_PASS', 'probe_exit': 0,
                  'scope': 'live real WS73 diagnostic syscall gate in isolated VM',
                  'index': 0, 'uid': 0, 'euid': 0, 'physical_acceptance': False,
                  'automatic_fault_recovery_acceptance': False, 'records': fixture(), 'cli_queries': []}
    capture = {'commands': [], 'complete': []}
    def add(opcode, start):
        ordinal = len(capture['commands']) * 2
        capture['commands'].append({'bus': 1, 'device': 2, 'opcode': opcode, 'wall_ns': start+1,
                                    'record': ordinal, 'params': '', 'completion': {'wall_ns': start+2}})
        capture['complete'].append({'bus': 1, 'device': 2, 'opcode': opcode, 'wall_ns': start+3,
                                    'record': ordinal+1, 'status': 0, 'value': values[opcode]})
    for i, (_, opcode, _) in enumerate(QUERIES): add(opcode, (i+1)*10)
    for row in diagnostic['records'][:4]:
        row['data'] = values[row['opcode']]; add(row['opcode'], row['start_wall_ns'])
    for i, (name, opcode, _) in enumerate(QUERIES, 5):
        start = (i-4)*1000
        diagnostic['cli_queries'].append({'args': ['/bin/slkconfig', '--adapter', '0', '--generation', '7', 'query', name],
                                         'exit': 0, 'start_wall_ns': start, 'end_wall_ns': start+20,
                                         'stdout': f'NativeDiagnosticQuery: index=0 generation=7 opcode=0x{opcode:04x} admission_seq={i} status=0x00 data={values[opcode]}\n'})
        add(opcode, start)
    return {'initial': [owner]}, capture, diagnostic


class DiagnosticCaptureTests(unittest.TestCase):
    def test_bootstrap_boundary_and_eight_queries_remain_individually_unique(self):
        run, capture, diagnostic = inputs(); owner = run['initial'][0]
        with self.assertRaises(CaptureError): command_reply(capture, owner, 0x0404, 0, 10000)
        boundary, proofs = corroborate_diagnostic(run, capture, diagnostic)
        self.assertEqual(boundary, {json_identity(owner): 100})
        self.assertEqual(len(proofs), 8)
        for _, opcode, _ in QUERIES: command_reply(capture, owner, opcode, 0, boundary[json_identity(owner)])

    def test_submission_fault_and_retries_share_one_exact_wire_interval(self):
        run, capture, diagnostic = inputs()
        diagnostic.update(format_version=2, admission_copyout_requested=True,
                          records=admission_fixture(diagnostic['records']))
        _, proofs = corroborate_diagnostic(run, capture, diagnostic)
        self.assertEqual([p['admission_copyout']['request_id'] for p in proofs[:2]], [1, 2])
        for mutation in ('duplicate_out', 'missing_fault_record', 'missing_mode', 'downgrade', 'boolean_version'):
            d = copy.deepcopy(diagnostic); c = copy.deepcopy(capture)
            if mutation == 'duplicate_out': c['commands'].append(copy.deepcopy(c['commands'][4]))
            elif mutation == 'missing_fault_record': d['records'] = [r for r in d['records'] if r.get('admission') != 'submit_read_only_output']
            elif mutation == 'missing_mode': d.pop('admission_copyout_requested')
            elif mutation == 'downgrade': d['format_version'] = 1
            else: d['format_version'] = True
            with self.assertRaises(CaptureError): corroborate_diagnostic(run, c, d)

    def test_unknown_failed_unprivileged_or_wrong_registration_run_rejects(self):
        run, capture, diagnostic = inputs()
        for key, value in [('status', 'FAIL'), ('probe_exit', 1), ('scope', 'synthetic'), ('uid', 1000),
                           ('euid', 1000), ('index', 1), ('physical_acceptance', True)]:
            bad = copy.deepcopy(diagnostic); bad[key] = value
            with self.assertRaises(CaptureError): corroborate_diagnostic(run, capture, bad)

    def test_wrong_data_clock_cli_or_ambiguous_wire_reply_rejects(self):
        run, capture, diagnostic = inputs()
        for field, value in [('exit', 1), ('stdout', ''), ('start_wall_ns', 0), ('end_wall_ns', 20000),
                             ('args', ['/bin/slkconfig', 'query', 'version'])]:
            bad = copy.deepcopy(diagnostic); bad['cli_queries'][0][field] = value
            with self.assertRaises(CaptureError): corroborate_diagnostic(run, capture, bad)
        for mutation in ['command', 'reply', 'data']:
            bad = copy.deepcopy(capture)
            if mutation == 'command': bad['commands'].append(bad['commands'][4])
            elif mutation == 'reply': bad['complete'].append(bad['complete'][4])
            else: bad['complete'][4]['value'] = '00'
            with self.assertRaises(CaptureError): corroborate_diagnostic(run, bad, diagnostic)


if __name__ == '__main__': unittest.main()
