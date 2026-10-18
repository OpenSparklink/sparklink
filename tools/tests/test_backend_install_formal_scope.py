import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_formal import classify


class BackendInstallFormalScope(unittest.TestCase):
    def test_weak_control_requires_exact_invariant_and_terminal_code(self):
        text = 'Error: Invariant LiveMetadataCurrent is violated.'
        self.assertEqual(classify('counterexample-install', 12, text), 'EXPECTED_COUNTEREXAMPLE_WEAK_GUARD')
        for code, output in [(0, text), (1, text), (12, 'Invariant Other is violated.'), (12, '')]:
            self.assertTrue(classify('counterexample-install', code, output).startswith('NOT_PROVEN'))

    def test_timeout_and_unsupported_cannot_pass_weak_control(self):
        text = 'Invariant LiveMetadataCurrent is violated.'
        self.assertEqual(classify('counterexample-install', 12, text, True), 'NOT_PROVEN_TIMEOUT')
        self.assertEqual(classify('counterexample-install', 12, 'unsupported feature\n'+text), 'NOT_PROVEN_UNSUPPORTED')

    def test_positive_model_needs_terminal_completion(self):
        self.assertEqual(classify('tlc', 0, 'Model checking completed. No error has been found.'), 'MODEL_CHECKED_SCOPED')
        self.assertTrue(classify('tlc', 0, 'Starting model checking').startswith('NOT_PROVEN'))
