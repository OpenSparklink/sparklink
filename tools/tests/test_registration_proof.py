import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_registration_proof import verdict


class RegistrationProofVerdict(unittest.TestCase):
    def test_incomplete_unsupported_timeout_and_bad_control_are_not_proved(self):
        success='VERIFICATION:- SUCCESSFUL\n0 failures, 1 total'
        self.assertEqual(verdict(0,success,False,False),'PROVED_SCOPED')
        for code,log,timeout in [(0,success,True),(0,success+' unsupported construct',False),(0,'building',False),(1,success,False)]:
            self.assertTrue(verdict(code,log,timeout,False).startswith('NOT_PROVEN'))
        self.assertEqual(verdict(0,success,False,True),'NOT_PROVEN_WEAK_CONTROL_UNEXPECTED_PASS')

    def test_only_expected_single_failed_generation_property_is_control_witness(self):
        log='VERIFICATION:- FAILED\n ** 1 of 83 failed\nFailed Checks: assertion failed: generation == 0 || s.generation == generation\n0 successfully verified harnesses, 1 failures, 1 total'
        self.assertEqual(verdict(1,log,False,True),'EXPECTED_COUNTEREXAMPLE_WEAK_VALIDATOR')
        for output in [log.replace('1 of','2 of'),log.replace('generation == 0','wrong property'),log+' unsupported feature']:
            self.assertTrue(verdict(1,output,False,True).startswith('NOT_PROVEN'))
