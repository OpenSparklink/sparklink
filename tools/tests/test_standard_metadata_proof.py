import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_standard_metadata_proof import verdict


class StandardMetadataProofVerdict(unittest.TestCase):
    def test_complete_success_has_narrow_qualification(self):
        self.assertEqual(verdict(0, True, [{'status': 'SUCCESS'}], [], False, False), 'MODEL_CHECKED_SCOPED')

    def test_timeout_unsupported_unexpanded_and_failed_never_pass(self):
        success = [{'status': 'SUCCESS'}]
        for args in [(0, True, success, [], True, False),
                     (0, True, success, ['unsupported construct'], False, False),
                     (0, False, success, [], False, False),
                     (0, True, [], [], False, False),
                     (0, True, [{'status': 'UNKNOWN'}], [], False, False),
                     (10, True, success, [], False, False),
                     (0, True, [{'status': 'FAILURE'}], [], False, False)]:
            with self.subTest(args=args):
                self.assertEqual(verdict(*args), 'NOT_PROVEN')

    def test_deliberately_weak_source_never_receives_production_pass(self):
        self.assertEqual(verdict(0, True, [{'status': 'SUCCESS'}], [], False, True), 'NOT_PROVEN')
