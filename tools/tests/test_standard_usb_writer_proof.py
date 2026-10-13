import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_standard_usb_writer_proof import verdict


class WriterProofVerdict(unittest.TestCase):
    def test_complete_property_results_are_required(self):
        report=[{'cProverStatus':'success'},{'result':[{'status':'SUCCESS'}]}]
        self.assertEqual(verdict(0,False,report,'',False),'MODEL_CHECKED_SCOPED')
        for value in [[],[{'cProverStatus':'success'}],[{'result':[{'status':'SUCCESS'}]}]]:
            self.assertEqual(verdict(0,False,value,'',False),'NOT_PROVEN')

    def test_unsupported_timeout_warning_weak_and_failed_are_not_pass(self):
        report=[{'cProverStatus':'success'},{'result':[{'status':'SUCCESS'}]}]
        for code,timeout,stderr,weak in [(0,True,'',False),(0,False,'unsupported construct',False),(0,False,'warning: incomplete',False),(0,False,'',True),(10,False,'',False)]:
            self.assertEqual(verdict(code,timeout,report,stderr,weak),'NOT_PROVEN')
        self.assertEqual(verdict(0,False,report+[{'messageType':'WARNING','messageText':'incomplete'}],'',False),'NOT_PROVEN')
        self.assertEqual(verdict(0,False,[{'cProverStatus':'success'},{'result':[{'status':'UNKNOWN'}]}],'',False),'NOT_PROVEN')
