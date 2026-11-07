# SPDX-License-Identifier: GPL-2.0-only
"""Fail-closed result parser only, not SSAP implementation verification."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_formal import classify, ssap_client_configuration


class SsapClientFormalScope(unittest.TestCase):
    def test_actual_config_cannot_drop_a_property_or_change_bounds(self):
        root = Path(__file__).resolve().parents[2] / 'formal/lifecycle'
        raw = (root / 'SSAPClientObligation.cfg').read_text()
        self.assertEqual(len(ssap_client_configuration(raw)['invariants']), 7)
        for text in [raw.replace('SingleTerminal ', ''),
                     raw.replace('PROPERTY EventuallyResolved', ''),
                     raw.replace('Parts = 2', 'Parts = 1'),
                     raw.replace('RequireAll = TRUE', 'RequireAll = FALSE'),
                     raw + '\nHorizon = 8\n', raw.replace('SPECIFICATION Spec', 'SPECIFICATION Init')]:
            with self.assertRaises(ValueError): ssap_client_configuration(text)
        for name, weak in [('SSAPClientPrematureWeak.cfg', 'parts'), ('SSAPClientDrainRenewWeak.cfg', 'drain')]:
            value = (root / name).read_text()
            self.assertEqual(ssap_client_configuration(value, weak=weak)['temporal'], [])
            with self.assertRaises(ValueError): ssap_client_configuration(value)

    def test_positive_requires_completed_safety_liveness_and_nonempty_state_space(self):
        good = ('Finished checking temporal properties in 00s\n'
                'Model checking completed. No error has been found.\n'
                '100 distinct states found, 0 states left on queue.\n')
        self.assertEqual(classify('tlc-ssap-client', 0, good),
                         'MODEL_CHECKED_SCOPED_NOT_IMPLEMENTATION_REFINEMENT')
        for code, text in [(1, good), (0, good.replace('100 distinct', '0 distinct')),
                           (0, good.replace('Finished checking temporal properties', 'Checking temporal properties')),
                           (0, good.replace('Model checking completed. No error has been found.', 'incomplete')),
                           (0, good + 'unsupported feature'), (0, '')]:
            self.assertTrue(classify('tlc-ssap-client', code, text).startswith('NOT_PROVEN'))
        self.assertEqual(classify('tlc-ssap-client', 0, good, True), 'NOT_PROVEN_TIMEOUT')

    def test_weak_controls_require_their_own_exact_counterexample(self):
        for kind, name in [('counterexample-ssap-parts', 'NoPrematureSuccess'),
                           ('counterexample-ssap-drain', 'DrainNotRenewed')]:
            text = f'Invariant {name} is violated.'
            self.assertEqual(classify(kind, 12, text), 'EXPECTED_COUNTEREXAMPLE_WEAK_GUARD')
            for code, output in [(0, text), (1, text), (12, 'Invariant Other is violated.'),
                                 (12, text + '\nunsupported construct')]:
                self.assertTrue(classify(kind, code, output).startswith('NOT_PROVEN'))
            self.assertEqual(classify(kind, 12, text, True), 'NOT_PROVEN_TIMEOUT')
