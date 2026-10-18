# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_target_recovery import RecoveryRun


def identity(index):
    return {key: index for key in ['port', 'bus', 'device', 'index', 'generation', 'path', 'address', 'version', 'features']}


def sample(reset=False, exhausted=False):
    return {'recovery_budget': f'attempts={0 if reset else 2} limit=2 uploads=0 upload_limit=3 cause={0 if reset else -110} result=0 exhausted={int(exhausted)} deadline_ms={0 if reset else 120000} stable_since_ms=1000'}


class StableBudgetObservation(unittest.TestCase):
    def run_object(self, samples):
        run = object.__new__(RecoveryRun); run.data = {}; run.alive = Mock(); run.save = Mock()
        a, b = identity(0), identity(1)
        run.ready = Mock(side_effect=lambda port: [a, b][port])
        run.diagnostics = Mock(side_effect=samples)
        return run, a, b

    def test_second_fault_waits_for_actual_reset_without_policy_mutation(self):
        run, a, b = self.run_object([sample(), sample(), sample(reset=True)])
        with patch('ws73_target_recovery.time.sleep') as sleep:
            run.wait_stable_budget(a, b)
        self.assertEqual(run.diagnostics.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        record = run.data['recovery_budget_rearm']
        self.assertEqual(len(record['samples']), 3)
        self.assertEqual(record['target'], a); self.assertEqual(record['peer'], b)
        self.assertGreaterEqual(record['end_monotonic_ns'], record['start_monotonic_ns'])

    def test_exhaustion_bad_budget_or_changed_peer_never_proceeds(self):
        for mutation in ['exhausted', 'malformed', 'peer']:
            run, a, b = self.run_object([sample(exhausted=True) if mutation == 'exhausted' else
                                         {'recovery_budget': 'attempts=0'} if mutation == 'malformed' else sample()])
            if mutation == 'peer':run.ready = Mock(side_effect=[a, identity(2)])
            with self.subTest(mutation=mutation), patch('ws73_target_recovery.time.sleep') as sleep, self.assertRaises(ValueError):
                run.wait_stable_budget(a, b)
            sleep.assert_not_called()
            self.assertNotIn('end_monotonic_ns', run.data['recovery_budget_rearm'])


if __name__ == '__main__':unittest.main()
