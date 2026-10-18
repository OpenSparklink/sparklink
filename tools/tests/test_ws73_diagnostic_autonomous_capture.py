# SPDX-License-Identifier: GPL-2.0-only
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from test_ws73_diagnostic_cancel_capture import capture_fixture
from ws73_capture import corroborate_diagnostic,CaptureError
from ws73_diagnostic_hold import corroborate_host_hold
from ws73_target import _run


class AutonomousCapture(unittest.TestCase):
    def test_full_old_gates_actual_hold_and_two_zero_wire_expirations(self):
        run,capture,diag,host,log=capture_fixture(autonomous=True)
        _,proofs=corroborate_diagnostic(run,capture,diag)
        row=next(p for p in proofs if p['caller']=='C autonomous queued expiry')
        self.assertEqual((row['commands'],row['replies'],row['request_id']),(0,0,12))
        self.assertEqual(len(proofs),50)
        self.assertEqual(sum('command' in p and 'reply' in p for p in proofs),46)
        corroborate_host_hold(host,diag,proofs,log,{'bus':1,'address':101})

    def test_version_flag_and_missing_record_fail(self):
        for mutation in ['version','flag','missing','late']:
            run,capture,diag,_,_=capture_fixture(autonomous=True)
            if mutation=='version':diag['format_version']=6
            elif mutation=='flag':diag['autonomous_requested']=False
            elif mutation=='missing':next(r for r in diag['records'] if r.get('cancel')=='held').pop('autonomous')
            else:next(r for r in diag['records'] if r.get('cancel')=='released')['autonomous']['result']='00'*104
            with self.assertRaises((ValueError,CaptureError)):corroborate_diagnostic(run,capture,diag)

    def test_features_during_silence_or_release_gap_rejected(self):
        for key in ['commands','complete']:
            for gap in [False,True]:
                run,capture,diag,_,_=capture_fixture(autonomous=True)
                held,final=[r for r in diag['records'] if 'cancel' in r]
                extra=copy.deepcopy(capture[key][0]);extra.update(opcode=0x0403,wall_ns=final['end_wall_ns']+1 if gap else held['end_wall_ns']-10)
                capture[key].append(extra)
                with self.assertRaises(CaptureError):corroborate_diagnostic(run,capture,diag)

    def test_required_modes_cannot_skip_original_deadline_or_real_hold(self):
        for command,recovery,diagnostic,cancel,deadline in [('support',True,True,True,True),('run',False,True,True,True),('run',True,False,True,True),('run',True,True,False,True),('run',True,True,True,False)]:
            args=SimpleNamespace(command=command,output=Path('/unused-autonomous-output'),fault_recovery=recovery,
                qmp_hotplug=False,event_copy_verify=False,diagnostic_verify=diagnostic,
                diagnostic_cancel_verify=cancel,diagnostic_deadline_verify=deadline,diagnostic_autonomous_verify=True)
            with self.assertRaisesRegex(ValueError,'live autonomous gate'):_run(args)
