# SPDX-License-Identifier: GPL-2.0-only
"""Proof-runner/config negative fixtures,not an implementation/hardware proof."""
from pathlib import Path
import unittest
from run_formal import classify,ssap_shared_configuration

class SharedFormalScope(unittest.TestCase):
    def test_exact_declared_properties_and_bounds(self):
        root=Path(__file__).resolve().parents[2]/'formal/lifecycle'
        raw=(root/'SSAPSharedOwnership.cfg').read_text()
        self.assertEqual(len(ssap_shared_configuration(raw)['invariants']),7)
        self.assertEqual(ssap_shared_configuration(raw)['temporal'],['EventuallyTerminal'])
        for bad in [raw.replace('Tokens = 3','Tokens = 1'),raw.replace('Capacity = 2','Capacity = 1'),raw.replace('CleanupBudget = 2','CleanupBudget = 3'),raw.replace(' NoSiblingClear',''),raw.replace('PROPERTY EventuallyTerminal',''),raw.replace('WeakClose = FALSE','WeakClose = TRUE'),raw+'\nTokens = 3\n']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):ssap_shared_configuration(bad)
        weak=(root/'SSAPSharedOwnershipWeak.cfg').read_text();self.assertEqual(ssap_shared_configuration(weak,weak=True)['temporal'],[])
        with self.assertRaises(ValueError):ssap_shared_configuration(weak)
    def test_new_selector_cannot_hide_a_second_requested_matrix(self):
        from run_formal import run
        import tempfile
        with tempfile.TemporaryDirectory()as tmp:
            output=Path(tmp)/'must-not-exist'
            with self.assertRaises(ValueError):run(output,False,5,ssap_client_only=True,ssap_shared_only=True)
            self.assertFalse(output.exists())

    def test_strict_result_and_actual_negative_trace_required(self):
        success='Model checking completed. No error has been found.\nFinished checking temporal properties\n57 distinct states found'
        self.assertEqual(classify('tlc-ssap-shared',0,success),'MODEL_CHECKED_SCOPED_NOT_IMPLEMENTATION_REFINEMENT')
        for code,text,timed_out in [(0,success,True),(0,success+'\nError: truncated',False),(0,success+' unsupported feature',False),(0,success.replace('57 distinct states found','0 distinct states found'),False),(0,success.replace('Finished checking temporal properties',''),False),(1,success,False)]:
            self.assertTrue(classify('tlc-ssap-shared',code,text,timed_out).startswith('NOT_PROVEN'))
        negative='Error: Invariant NoSiblingClear is violated.\nState 1: <Initial predicate>\nState 2: <Close>'
        self.assertEqual(classify('counterexample-ssap-shared',12,negative),'EXPECTED_COUNTEREXAMPLE_WEAK_GUARD')
        for code,text in [(0,negative),(12,negative.replace('NoSiblingClear','DebtPreserved')),(12,'Invariant NoSiblingClear is violated.')]:
            self.assertTrue(classify('counterexample-ssap-shared',code,text).startswith('NOT_PROVEN'))

if __name__=='__main__':unittest.main()
