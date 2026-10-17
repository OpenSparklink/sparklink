"""Formal verdict parser must reject partial, empty or diagnostic-only success."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify_ssap_access import inspect,PROPERTIES
class VerificationVerdict(unittest.TestCase):
    def good(self):
        return '\n'.join(PROPERTIES)+'\n- Status: SUCCESS\nVERIFICATION:- SUCCESSFUL\n1 successfully verified harnesses, 0 failures, 1 total\n'
    def test_complete_synthetic_output_only_checks_parser_not_production_proof(self):
        self.assertEqual(inspect(self.good(),0)['status'],'BOUNDED_PREDICATE_PASS')
    def test_diagnostics_unsupported_and_missing_inventory_never_upgrade(self):
        for body,code in [(self.good()+'warning: unstable feature\n',0),(self.good()+'unsupported operation\n',0),(self.good().replace(PROPERTIES[0],''),0),(self.good().replace('VERIFICATION:- SUCCESSFUL',''),0),(self.good()+'- Status: FAILURE\n',0),(self.good(),1),('',0)]:
            with self.subTest(body=body,code=code):self.assertEqual(inspect(body,code)['status'],'NOT_PROVEN')
