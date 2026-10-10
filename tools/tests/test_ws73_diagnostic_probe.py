# SPDX-License-Identifier: GPL-2.0-only
"""Verifier fixtures are synthetic; they cannot establish live syscall success."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_diagnostic_probe import NEGATIVE, ORDER, QUERIES, SleDiagnosticResult, verify_records
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

    def test_diagnostic_gate_cannot_use_support_or_nonrecovery_host_mode(self):
        for command, recovery in [('support', True), ('run', False)]:
            args = SimpleNamespace(command=command, output=Path('/tmp/never-created-diagnostic-test'),
                                   diagnostic_verify=True, fault_recovery=recovery)
            with patch('ws73_target.ordinary_identity'), self.assertRaisesRegex(ValueError, 'requires real fault-recovery VM mode'):
                _run(args)


if __name__ == '__main__': unittest.main()
