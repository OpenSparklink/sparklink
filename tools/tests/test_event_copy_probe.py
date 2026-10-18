# SPDX-License-Identifier: GPL-2.0-only
import copy
import errno
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_event_copy_probe import CASES, verify_cases


def sample():
    # Verifier-only synthetic transcript, never live VFS or RF evidence.
    records = []
    raw = bytes(range(88))
    for name in CASES:
        committed = 44 if name in ('partial_later', 'capacity_tail') else 88 if name == 'complete_batch' else 0
        error = errno.EINVAL if name == 'short' else errno.EFAULT if name in ('bad_address', 'partial_first') else 0
        records.append({'case': name, 'result': -1 if error else committed, 'errno': error,
                        'partial_prefix': 22 if name in ('partial_first', 'partial_later') else 0,
                        'before': {'pending': 2, 'enqueued': 2, 'dropped': 0, 'delivered': 0},
                        'after': {'pending': 2 - committed // 44, 'enqueued': 2, 'dropped': 0, 'delivered': committed // 44},
                        'final': {'pending': 0, 'enqueued': 2, 'dropped': 0, 'delivered': 2},
                        'reference': raw.hex(), 'retry': raw[committed:].hex()})
    return records


class EventCopyVerifier(unittest.TestCase):
    def test_exact_case_sequence_and_duplicate_rejection(self):
        verify_cases(sample())
        for bad in [sample()[:-1], list(reversed(sample())), sample() + [sample()[0]]]:
            with self.assertRaises(ValueError):
                verify_cases(bad)

    def test_fault_cannot_be_success_eof_or_partial_return(self):
        for index in [2, 3, 4]:
            for value in [0, 22, 66]:
                bad = sample(); bad[index]['result'] = value
                with self.assertRaises(ValueError):
                    verify_cases(bad)

    def test_consumption_drop_or_retained_byte_change_rejects(self):
        for key in ['pending', 'enqueued', 'dropped', 'delivered']:
            bad = sample(); bad[3]['after'][key] += 1
            with self.assertRaises(ValueError):
                verify_cases(bad)
        bad = sample(); bad[3]['retry'] = 'ff' + bad[3]['retry'][2:]
        with self.assertRaises(ValueError):
            verify_cases(bad)

    def test_non_record_reference_and_missing_actual_partial_reject(self):
        for key, value in [('reference', '01'), ('partial_prefix', 0), ('partial_prefix', 23)]:
            bad = copy.deepcopy(sample()); bad[3][key] = value
            with self.assertRaises(ValueError):
                verify_cases(bad)

    def test_boolean_and_float_are_not_syscall_or_counter_values(self):
        for key, value in [('result', False), ('errno', 0.0), ('partial_prefix', True)]:
            bad = sample(); bad[0][key] = value
            with self.assertRaises(ValueError):
                verify_cases(bad)
        bad = sample(); bad[0]['after']['pending'] = 2.0
        with self.assertRaises(ValueError):
            verify_cases(bad)
