# SPDX-License-Identifier: GPL-2.0-only
"""Verifier fixtures are synthetic; they cannot establish live syscall success."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_diagnostic_probe import NEGATIVE, ORDER, QUERIES, SleDiagnosticResult, SleDiagnosticSubmit, SleDliEvent, verify_records
from ws73_target import _run


def fixture():
    records = []
    for seq, (_, opcode, length) in enumerate(QUERIES, 1):
        records.append({'case': 'metadata', 'generation': 7, 'seq': seq, 'opcode': opcode,
                        'start_wall_ns': seq * 100, 'end_wall_ns': seq * 100 + 10,
                        'data': bytes(range(1, length + 1)).hex()})
    records.append({'identity': 'inherited_fd_child', 'uid': 1000, 'euid': 1000, 'cap_eff': 0, 'cap_prm': 0})
    value = SleDiagnosticResult(version=1, generation=7, seq=1, opcode=0x0406, state=2, data_len=6)
    for i in range(6): value.data[i] = i + 1
    raw = bytes(value).hex()
    for name in ORDER[4:]:
        record = {'case': name, 'result': -1, 'errno': 14 if name in ('read_only_output', 'partial_output') else NEGATIVE[name]}
        if name in ('read_only_output', 'partial_output'):
            record.update(reference=raw, retry=raw, partial_prefix=56 if name == 'partial_output' else 0)
        if name == 'retired_fd': records.append({'phase': 'BEFORE_DAEMON_PASS'})
        records.append(record)
    records.append({'phase': 'DIAGNOSTIC_RESULT_LIVE_PASS'})
    return records


def admission_fixture(records=None):
    records = copy.deepcopy(fixture() if records is None else records)
    output = []
    for row in records:
        output.append(row)
        if row.get('case') != 'metadata' or row['seq'] not in (1, 2): continue
        i = row['seq'] - 1; prefix = 36 if i else 0
        value = SleDiagnosticSubmit(version=1, generation=row['generation'], request_id=i+1,
                                    timeout_ms=5000, opcode=row['opcode'], action=1)
        raw = bytes(value); value.seq = row['seq']; final = bytes(value)
        output.append({'admission': 'submit_partial_output' if i else 'submit_read_only_output',
                       'result': -1, 'errno': 14, 'request_id': i+1, 'partial_prefix': prefix,
                       'user_address_mod8': 4 if i else 0,
                       **{k: row[k] for k in ('generation', 'seq', 'opcode', 'start_wall_ns', 'end_wall_ns')},
                       'input': raw.hex(), 'fault_output': (final[:prefix]+raw[prefix:]).hex(),
                       'retry_outputs': [final.hex()]*3,
                       'submitted_before': i, 'submitted_after': i+1, 'resolved_before': i,
                       'resolved_after': i+1, 'pending_before': 0, 'pending_after': 0,
                       'timeouts_before': 0, 'timeouts_after': 0})
    return output


def eviction_fixture(records=None):
    records = copy.deepcopy(admission_fixture() if records is None else records)
    meta = [r for r in records if r.get('case') == 'metadata']
    generation = meta[0]['generation']; fills = []
    legacy = [r for r in records if 'legacy_poll' in r]
    previous = legacy[-1] if legacy else meta[-1]
    baseline = legacy[-1]['submitted_after'] if legacy else 4
    cancellations = [r for r in records if 'cancel' in r]
    if cancellations:
        previous = {'seq': SleDiagnosticSubmit.from_buffer_copy(bytes.fromhex(cancellations[0]['outputs'][-1])).seq,
                    'end_wall_ns': cancellations[-1]['end_wall_ns']}
        baseline = cancellations[-1]['submitted_after']
    for i in range(33):
        value = SleDiagnosticSubmit(version=1, generation=generation, request_id=i+1,
                                    timeout_ms=5000, opcode=0x0406, action=1)
        raw = bytes(value).hex(); value.seq = previous['seq']+i+1
        result = SleDiagnosticResult(version=1, generation=generation, seq=value.seq,
                                     opcode=0x0406, state=2, data_len=6)
        result.data[:6] = bytes.fromhex(meta[0]['data'])
        start = previous['end_wall_ns']+20+i*20
        fills.append({'eviction':'fill', 'generation':generation, 'request_id':i+1,
                      'seq':value.seq, 'opcode':0x0406, 'start_wall_ns':start, 'end_wall_ns':start+10,
                      'data':meta[0]['data'], 'input':raw, 'output':bytes(value).hex(),
                      'result_bytes':bytes(result).hex(), 'submitted_before':baseline+i, 'submitted_after':baseline+i+1,
                      'resolved_before':baseline+i, 'resolved_after':baseline+i+1, 'pending_before':0, 'pending_after':0,
                      'timeouts_before':0, 'timeouts_after':0})
    first, retained = fills[:2]
    query = SleDiagnosticResult(version=1, generation=generation, seq=first['seq'])
    start = fills[-1]['end_wall_ns']+10
    negative = {'eviction':'old_id_and_result_rejected', 'generation':generation, 'request_id':1,
                'seq':first['seq'], 'opcode':0x0406, 'start_wall_ns':start, 'end_wall_ns':start+100_000_010,
                'quiet_observation_ms':100, 'retry_results':[-1]*3, 'retry_errnos':[116]*3,
                'old_input':first['input'], 'retry_outputs':[first['input']]*3,
                'result_query_return':-1, 'result_query_errno':2,
                'result_query_input':bytes(query).hex(), 'result_query_output':bytes(query).hex(),
                'retained_input':retained['input'], 'retained_output':retained['output'],
                'retained_result':retained['result_bytes'], 'submitted_before':baseline+33, 'submitted_after':baseline+33,
                'resolved_before':baseline+33, 'resolved_after':baseline+33, 'pending_before':0, 'pending_after':0,
                'timeouts_before':0, 'timeouts_after':0}
    at = next(i for i,r in enumerate(records) if r.get('case')=='foreign_author_with_lease')+1
    return records[:at]+fills+[negative]+records[at:]


def legacy_poll_fixture(records=None):
    records = copy.deepcopy(admission_fixture() if records is None else records)
    meta = [r for r in records if r.get('case') == 'metadata']
    generation = meta[0]['generation']; rows = []
    event = SleDliEvent(event_type=1, opcode=0x0406, data_len=6)
    event.data[:6] = bytes.fromhex(meta[0]['data']); raw_event = bytes(event)
    for i,name in enumerate(['bad_address','read_only_output','partial_output']):
        prefix = 128 if i==2 else 0
        value = SleDiagnosticSubmit(version=1, generation=generation, request_id=5+i,
                                    timeout_ms=5000, opcode=0x0406, action=1)
        raw = bytes(value).hex(); value.seq = meta[-1]['seq']+i+1
        result = SleDiagnosticResult(version=1, generation=generation, seq=value.seq,
                                     opcode=0x0406, state=2, data_len=6)
        result.data[:6] = bytes.fromhex(meta[0]['data'])
        start = meta[-1]['end_wall_ns']+20+i*20
        rows.append({'legacy_poll':name,'generation':generation,'request_id':5+i,'seq':value.seq,
                     'opcode':0x0406,'start_wall_ns':start,'end_wall_ns':start+10,
                     'result':-1,'errno':14,'partial_prefix':prefix,'drained_before':4 if not i else 0,
                     'final_poll_result':-1,'final_poll_errno':11,'data':meta[0]['data'],
                     'input':raw,'output':bytes(value).hex(),'result_bytes':bytes(result).hex(),
                     'reference':raw_event.hex(),'retry':raw_event.hex(),
                     'fault_output':None if not i else (raw_event[:prefix]+b'\xa5'*(256-prefix)).hex(),
                     'submitted_before':4+i,'submitted_after':5+i,'resolved_before':4+i,
                     'resolved_after':5+i,'pending_before':0,'pending_after':0,'timeouts_before':0,'timeouts_after':0})
    at = next(i for i,r in enumerate(records) if r.get('case')=='missing_sequence')+1
    return eviction_fixture(records[:at]+rows+records[at:])


class DiagnosticEvidenceTests(unittest.TestCase):
    def test_exact_fixture_and_predaemon_phase_are_accepted_only_for_scoped_verifier(self):
        records = fixture(); verify_records(records); verify_records(records[:-2], final=False)

    def test_missing_retirement_or_wrong_errno_cannot_be_accepted(self):
        records = fixture()
        for index in range(len(records)):
            bad = records[:index] + records[index+1:]
            with self.assertRaises(ValueError): verify_records(bad)
        for index, row in enumerate(records):
            if 'errno' in row:
                bad = copy.deepcopy(records); bad[index]['errno'] = 0
                with self.assertRaises(ValueError): verify_records(bad)

    def test_child_capabilities_and_effective_identity_must_be_actual_zero(self):
        for field, value in [('cap_eff', 1), ('cap_prm', 1), ('uid', 0), ('euid', 0), ('cap_eff', False)]:
            records = fixture(); records[4][field] = value
            with self.assertRaises(ValueError): verify_records(records)

    def test_copy_fault_retry_identity_payload_and_partial_boundary_are_checked(self):
        for field in ['generation', 'seq', 'state', 'error', 'data_len', '_pad']:
            records = fixture(); row = next(r for r in records if r.get('case') == 'partial_output')
            value = SleDiagnosticResult.from_buffer_copy(bytes.fromhex(row['reference']))
            setattr(value, field, getattr(value, field) + 1)
            row['reference'] = row['retry'] = bytes(value).hex()
            with self.assertRaises(ValueError): verify_records(records)
        for mutation in ['retry', 'partial_prefix']:
            records = fixture(); row = next(r for r in records if r.get('case') == 'partial_output')
            row[mutation] = '00' if mutation == 'retry' else 0
            with self.assertRaises(ValueError): verify_records(records)

    def test_metadata_identity_opcode_length_and_clock_must_match(self):
        for key, value in [('generation', 8), ('seq', 1), ('opcode', 0x0406), ('data', '00'), ('end_wall_ns', 0)]:
            records = fixture(); records[1][key] = value
            with self.assertRaises(ValueError): verify_records(records)

    def test_current_admission_version_requires_both_actual_copyout_cases(self):
        records = admission_fixture(); verify_records(records, admission=True)
        verify_records(records[:-2], final=False, admission=True)
        with self.assertRaises(ValueError): verify_records(records)
        for name in ('submit_read_only_output', 'submit_partial_output'):
            bad = [r for r in records if r.get('admission') != name]
            with self.assertRaises(ValueError): verify_records(bad, admission=True)

    def test_admission_replay_id_seq_input_and_counters_are_exact(self):
        for field, value in [('request_id', 3), ('seq', 3), ('generation', 8), ('opcode', 0x0404),
                             ('start_wall_ns', 0), ('errno', 0), ('partial_prefix', 32),
                             ('user_address_mod8', 0), ('submitted_after', 3), ('resolved_after', 1),
                             ('pending_after', 1), ('timeouts_after', 1), ('pending_before', False)]:
            records = admission_fixture(); row = next(r for r in records if r.get('admission') == 'submit_partial_output')
            row[field] = value
            with self.assertRaises(ValueError): verify_records(records, admission=True)
        for field in ('input', 'fault_output'):
            records = admission_fixture(); row = next(r for r in records if 'admission' in r); row[field] = '00'
            with self.assertRaises(ValueError): verify_records(records, admission=True)

    def test_observed_submit_prefix_and_same_id_retry_bytes_cannot_be_faked(self):
        for mutation in ('prefix', 'retry', 'input_seq', 'input_timeout'):
            records = admission_fixture(); row = next(r for r in records if r.get('admission') == 'submit_partial_output')
            if mutation == 'prefix': row['fault_output'] = row['input']
            elif mutation == 'retry': row['retry_outputs'][1] = row['input']
            else:
                value = SleDiagnosticSubmit.from_buffer_copy(bytes.fromhex(row['input']))
                if mutation == 'input_seq': value.seq = 1
                else: value.timeout_ms = 4999
                row['input'] = bytes(value).hex()
            with self.assertRaises(ValueError): verify_records(records, admission=True)

    def test_diagnostic_gate_cannot_use_support_or_nonrecovery_host_mode(self):
        for command, recovery in [('support', True), ('run', False)]:
            args = SimpleNamespace(command=command, output=Path('/tmp/never-created-diagnostic-test'),
                                   diagnostic_verify=True, fault_recovery=recovery)
            with patch('ws73_target.ordinary_identity'), self.assertRaisesRegex(ValueError, 'requires real fault-recovery VM mode'):
                _run(args)

    def test_eviction_requires_actual_33_fills_after_foreign_author_check(self):
        records = eviction_fixture()
        verify_records(records, admission=True, eviction=True)
        verify_records(records[:-2], final=False, admission=True, eviction=True)
        for mutation in ('missing', 'foreign_order', 'mode', 'repeat_sequence'):
            bad = copy.deepcopy(records); at = next(i for i,r in enumerate(bad) if 'eviction' in r)
            if mutation=='missing': bad.pop(at)
            elif mutation=='foreign_order': bad[at-1],bad[at] = bad[at],bad[at-1]
            elif mutation=='repeat_sequence': bad[at+1]['seq'] = bad[at]['seq']
            with self.assertRaises(ValueError):
                verify_records(bad, admission=True, eviction=mutation!='mode')

    def test_eviction_rejection_retained_bytes_and_quiet_accounting_are_strict(self):
        for field,value in [('retry_errnos',[2]*3), ('retry_outputs',['00']*3),
                            ('result_query_errno',116), ('result_query_output','00'),
                            ('retained_output','00'), ('retained_result','00'),
                            ('submitted_after',38), ('timeouts_after',1), ('pending_before',False),
                            ('quiet_observation_ms',99), ('end_wall_ns',1)]:
            rows = eviction_fixture(); negative = next(r for r in rows if r.get('eviction')=='old_id_and_result_rejected')
            negative[field] = value
            with self.assertRaises(ValueError): verify_records(rows, admission=True, eviction=True)

    def test_eviction_fill_canonical_bytes_counter_continuity_and_clock_are_checked(self):
        for field,value in [('request_id',3), ('seq',False), ('input','00'), ('output','00'),
                            ('result_bytes','00'), ('data','00'), ('submitted_after',7),
                            ('resolved_before',6), ('start_wall_ns',0)]:
            rows = eviction_fixture(); fills = [r for r in rows if r.get('eviction')=='fill']
            fills[1][field] = value
            with self.assertRaises(ValueError): verify_records(rows, admission=True, eviction=True)

    def test_three_legacy_faults_are_ordered_contiguous_and_required_in_current_mode(self):
        rows = legacy_poll_fixture(); self.assertEqual(len(rows),58)
        verify_records(rows,admission=True,eviction=True,legacy_poll=True)
        verify_records(rows[:-2],final=False,admission=True,eviction=True,legacy_poll=True)
        with self.assertRaises(ValueError): verify_records(rows,admission=True,eviction=True)
        for mutation in ('missing','order','boundary'):
            bad = copy.deepcopy(rows); at = next(i for i,r in enumerate(bad) if 'legacy_poll' in r)
            if mutation=='missing': bad.pop(at)
            elif mutation=='order': bad[at],bad[at+1]=bad[at+1],bad[at]
            else: bad[at-1],bad[at]=bad[at],bad[at-1]
            with self.assertRaises(ValueError): verify_records(bad,admission=True,eviction=True,legacy_poll=True)

    def test_legacy_copy_must_preserve_exact_bytes_padding_and_observed_prefix(self):
        for key,value in [('reference','00'),('retry','00'),('fault_output',None),('partial_prefix',0),
                          ('input','00'),('output','00'),('result_bytes','00')]:
            rows=legacy_poll_fixture(); row=next(r for r in rows if r.get('legacy_poll')=='partial_output');row[key]=value
            with self.assertRaises(ValueError): verify_records(rows,admission=True,eviction=True,legacy_poll=True)
        rows=legacy_poll_fixture(); row=next(r for r in rows if r.get('legacy_poll')=='partial_output')
        row['fault_output']=(b'\xa5'*256).hex()
        with self.assertRaises(ValueError): verify_records(rows,admission=True,eviction=True,legacy_poll=True)

    def test_legacy_actual_errno_identity_once_commit_and_counter_continuity_are_checked(self):
        for key,value in [('errno',0),('result',0),('final_poll_errno',0),('final_poll_result',0),
                          ('request_id',1),('seq',False),('generation',8),('opcode',0x0404),
                          ('start_wall_ns',1),('drained_before',32),('pending_after',1),
                          ('submitted_after',99),('resolved_before',1),('timeouts_after',1)]:
            rows=legacy_poll_fixture(); row=next(r for r in rows if r.get('legacy_poll')=='partial_output');row[key]=value
            with self.assertRaises(ValueError): verify_records(rows,admission=True,eviction=True,legacy_poll=True)
        rows=legacy_poll_fixture(); fill=next(r for r in rows if r.get('eviction')=='fill')
        fill['submitted_before']+=1
        with self.assertRaises(ValueError): verify_records(rows,admission=True,eviction=True,legacy_poll=True)


if __name__ == '__main__': unittest.main()
