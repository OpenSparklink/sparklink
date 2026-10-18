# SPDX-License-Identifier: GPL-2.0-only
"""Report classification only, never implementation proof."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_formal import classify


class RxReportScope(unittest.TestCase):
    def test_requires_strong_and_deliberately_weak_control(self):
        good = 'Observation RxDequeueWithdrawal Never 0 1\nObservation RxDequeueWithdrawalWeak Sometimes 1 1\n'
        self.assertEqual(classify('lkmm-rx', 0, good), 'PROVED_SCOPED_WITH_WEAK_CONTROL')
        for output in [good.splitlines()[0], good.replace('Never', 'Sometimes'),
                       good.replace('Weak Sometimes', 'Weak Never'), good+'unsupported feature']:
            self.assertTrue(classify('lkmm-rx', 0, output).startswith('NOT_PROVEN'))
        self.assertEqual(classify('lkmm-rx', 0, good, True), 'NOT_PROVEN_TIMEOUT')
        self.assertTrue(classify('lkmm-rx', 1, good).startswith('NOT_PROVEN'))


class IngressReportScope(unittest.TestCase):
    def test_retirement_proof_requires_weak_counterexample_and_finished_tool(self):
        good = 'Observation RuntimeRouteRetirement Never 0 1\nObservation RuntimeRouteRetirementWeak Sometimes 1 1\n'
        self.assertEqual(classify('lkmm-ingress', 0, good), 'PROVED_SCOPED_WITH_WEAK_CONTROL')
        for output in [good.splitlines()[0], good.replace('Never', 'Sometimes'),
                       good.replace('Weak Sometimes', 'Weak Never'), good+'unsupported feature']:
            self.assertTrue(classify('lkmm-ingress', 0, output).startswith('NOT_PROVEN'))
        self.assertEqual(classify('lkmm-ingress', 0, good, True), 'NOT_PROVEN_TIMEOUT')
        self.assertTrue(classify('lkmm-ingress', 1, good).startswith('NOT_PROVEN'))
