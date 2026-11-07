# SPDX-License-Identifier: GPL-2.0-only
"""Actual verdict parser; terminal fixtures,not USB or transport qualification."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
from check_directusb_probe_refusal import SCOPES, validate


class ProbeRefusal(unittest.TestCase):
    def result(self, kind, **changes):
        value = dict(schema=1, status='REFUSED_OR_FAILED', scope=SCOPES[kind], error='usage: explicit guest port')
        value.update(changes)
        return subprocess.CompletedProcess([], 1, json.dumps(value), '')

    def test_all_actual_refusal_shapes(self):
        for kind in SCOPES:
            self.assertEqual(validate(self.result(kind), kind)['scope'], SCOPES[kind])

    def test_success_skip_partial_wrong_scope_and_selection_are_rejected(self):
        for kind in SCOPES:
            for changes in [dict(schema=True), dict(status='PASS'), dict(status='SKIP'),
                            dict(scope=SCOPES['control' if kind == 'rom' else 'rom']),
                            dict(error='device already opened'), dict(error=None),
                            *[{key: 0} for key in ['bus', 'guest_port', 'reply', 'control', 'raw_memory_backpressure_word_le', 'receive', 'endpoint_pending_after', 'interface_release']]]:
                with self.subTest(kind=kind, changes=changes), self.assertRaises(ValueError):
                    validate(self.result(kind, **changes), kind)
            for code, output, error in [(0, self.result(kind).stdout, ''), (-9, '', ''),
                                        (1, '{', ''), (1, self.result(kind).stdout, 'truncated'),
                                        (1, 'x' * 65537, '')]:
                with self.subTest(code=code), self.assertRaises((ValueError, json.JSONDecodeError)):
                    validate(subprocess.CompletedProcess([], code, output, error), kind)


if __name__ == '__main__':
    unittest.main()
