# SPDX-License-Identifier: GPL-2.0-only
"""Actual verdict function, terminal-shape fixtures only; no VM/RF acceptance."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_target import run_exit_code


class TerminalExit(unittest.TestCase):
    def test_completed_shape_requires_two_integer_zero_exit_receipts(self):
        for status in ['SUPPORT_PASS','PASSTHROUGH_SUPPORT_PASS','ENVIRONMENT_FINISHED']:
            record=dict(status=status,qemu_exit=0,supervisor_exit=0)
            self.assertEqual(run_exit_code(record),0)
            for key in ['qemu_exit','supervisor_exit']:
                bad=dict(record);bad.pop(key)
                with self.subTest(status=status,missing=key):self.assertEqual(run_exit_code(bad),1)
                for value in [1,-9,None,False,True,0.0,'0']:
                    with self.subTest(status=status,key=key,value=value):
                        self.assertEqual(run_exit_code(record|{key:value}),1)

    def test_only_explicit_internal_pending_phase_may_compute_unwritten_supervisor(self):
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0)
        self.assertEqual(run_exit_code(record),1)
        self.assertEqual(run_exit_code(record,supervisor_pending=True),0)
        self.assertEqual(run_exit_code(record|dict(supervisor_pending=True)),1)
        for value in [None,1,'true']:
            self.assertEqual(run_exit_code(record,supervisor_pending=value),1)
        for value in [1,-9,False,None,'0']:
            self.assertEqual(run_exit_code(record|dict(supervisor_exit=value),supervisor_pending=True),1)

    def test_internal_pending_phase_still_requires_actual_qemu_exit_and_success(self):
        self.assertEqual(run_exit_code(dict(status='SUPPORT_PASS'),supervisor_pending=True),1)
        self.assertEqual(run_exit_code(dict(supervisor_exit=0,status='FAIL',qemu_exit=0),supervisor_pending=True),1)


if __name__=='__main__':unittest.main()
