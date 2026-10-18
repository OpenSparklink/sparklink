# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic query-window fixtures; no syscall or hardware acceptance."""
import copy
import struct
import unittest

from test_ws73_diagnostic_probe import fixture, admission_fixture, eviction_fixture, legacy_poll_fixture
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


def eviction_inputs(legacy=False):
    run, capture, diagnostic = inputs()
    diagnostic.update(format_version=4 if legacy else 3, admission_copyout_requested=True, admission_eviction_requested=True,
                      records=(legacy_poll_fixture if legacy else eviction_fixture)(admission_fixture(diagnostic['records'])))
    if legacy: diagnostic['legacy_poll_copy_requested']=True
    eviction = [r for r in diagnostic['records'] if 'eviction' in r]
    for row in [r for r in diagnostic['records'] if 'legacy_poll' in r]+eviction[:-1]:
        start = row['start_wall_ns']
        capture['commands'].append({'bus':1, 'device':2, 'opcode':0x0406, 'wall_ns':start+1,
                                    'params':'', 'completion':{'wall_ns':start+2}})
        capture['complete'].append({'bus':1, 'device':2, 'opcode':0x0406, 'wall_ns':start+3,
                                    'status':0, 'value':row['data']})
    for i,row in enumerate(diagnostic['cli_queries']):
        start = eviction[-1]['end_wall_ns']+1000*(i+1)
        row.update(start_wall_ns=start, end_wall_ns=start+20)
        command, reply = capture['commands'][8+i], capture['complete'][8+i]
        command['wall_ns']=start+1; command['completion']['wall_ns']=start+2; reply['wall_ns']=start+3
    run['initial'][0]['observed_wall_ns']=diagnostic['cli_queries'][-1]['end_wall_ns']+1000
    for name in ('commands','complete'): capture[name].sort(key=lambda r:r['wall_ns'])
    for i,row in enumerate(sorted(capture['commands']+capture['complete'],key=lambda r:r['wall_ns'])): row['record']=i
    return run,capture,diagnostic


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

    def test_eviction_has_33_single_wire_fills_and_one_quiet_rejection_interval(self):
        run,capture,diagnostic = eviction_inputs()
        _,proofs = corroborate_diagnostic(run,capture,diagnostic)
        self.assertEqual(len(proofs),42)
        self.assertEqual([p['request_id'] for p in proofs[4:37]],list(range(1,34)))
        self.assertEqual(proofs[37]['commands'],0)
        self.assertEqual(proofs[37]['replies'],0)
        self.assertEqual([p['caller'] for p in proofs[38:]],['slkconfig']*4)

    def test_extra_commands_in_fill_gaps_or_quiet_rejection_cannot_hide(self):
        run,capture,diagnostic = eviction_inputs()
        rows = [r for r in diagnostic['records'] if 'eviction' in r]
        for mutation in ('fill_duplicate','fill_gap','quiet_out','quiet_reply','missing_reply','mode','downgrade'):
            c,d = copy.deepcopy(capture),copy.deepcopy(diagnostic)
            if mutation in ('mode','downgrade'):
                if mutation=='mode': d.pop('admission_eviction_requested')
                else: d['format_version']=2
            elif mutation=='missing_reply': c['complete']=[r for r in c['complete'] if r['wall_ns']!=rows[0]['start_wall_ns']+3]
            elif mutation=='quiet_reply':
                reply = copy.deepcopy(c['complete'][0]); reply.update(opcode=0x0404,wall_ns=rows[-1]['start_wall_ns']+1)
                c['complete'].append(reply)
            else:
                tx = copy.deepcopy(next(r for r in c['commands'] if r['wall_ns']==rows[0]['start_wall_ns']+1))
                if mutation=='fill_gap': tx['wall_ns']=rows[0]['end_wall_ns']+1
                elif mutation=='quiet_out': tx['wall_ns']=rows[-1]['start_wall_ns']+1
                c['commands'].append(tx)
            with self.assertRaises(CaptureError): corroborate_diagnostic(run,c,d)

    def test_eviction_quiet_window_is_specific_to_one_controller(self):
        run,capture,diagnostic = eviction_inputs()
        negative = next(r for r in diagnostic['records'] if r.get('eviction')=='old_id_and_result_rejected')
        for name in ('commands','complete'):
            row = copy.deepcopy(capture[name][0]); row.update(device=3,wall_ns=negative['start_wall_ns']+1,opcode=0x0406)
            capture[name].append(row)
        _,proofs = corroborate_diagnostic(run,capture,diagnostic)
        self.assertEqual(proofs[37]['commands'],0)

    def test_legacy_poll_faults_each_have_one_real_seed_before_eviction(self):
        run,capture,diagnostic=eviction_inputs(legacy=True)
        _,proofs=corroborate_diagnostic(run,capture,diagnostic)
        self.assertEqual(len(proofs),45)
        self.assertEqual([p['legacy_poll_copy']['legacy_poll'] for p in proofs[4:7]],
                         ['bad_address','read_only_output','partial_output'])
        self.assertEqual([p['request_id'] for p in proofs[7:40]],list(range(1,34)))
        self.assertEqual(proofs[40]['commands'],0)

    def test_legacy_poll_cannot_omit_faults_mode_or_duplicate_seeds_even_in_gaps(self):
        run,capture,diagnostic=eviction_inputs(legacy=True)
        rows=[r for r in diagnostic['records'] if 'legacy_poll' in r]
        for mutation in ('mode','downgrade','missing','duplicate','gap','wrong_reply','registration'):
            c,d=copy.deepcopy(capture),copy.deepcopy(diagnostic)
            if mutation=='mode':d.pop('legacy_poll_copy_requested')
            elif mutation=='downgrade':d['format_version']=3
            elif mutation=='missing':d['records']=[r for r in d['records'] if r.get('legacy_poll')!='bad_address']
            elif mutation=='registration':d['records'][next(i for i,r in enumerate(d['records']) if 'legacy_poll' in r)]['generation']=8
            elif mutation=='wrong_reply':
                next(r for r in c['complete'] if r['wall_ns']==rows[0]['start_wall_ns']+3)['value']='00'
            else:
                tx=copy.deepcopy(next(r for r in c['commands'] if r['wall_ns']==rows[0]['start_wall_ns']+1))
                if mutation=='gap':tx['wall_ns']=rows[0]['end_wall_ns']+1
                c['commands'].append(tx)
            with self.assertRaises(CaptureError):corroborate_diagnostic(run,c,d)


if __name__ == '__main__': unittest.main()
