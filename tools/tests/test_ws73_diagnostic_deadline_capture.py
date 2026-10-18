# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic wire/record/mode gates; actual VM and USB qualification separate."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from test_ws73_diagnostic_cancel_capture import capture_fixture
from ws73_capture import corroborate_diagnostic,CaptureError
from ws73_diagnostic_hold import corroborate_host_hold
from ws73_target import _run as run_target


class DeadlineCapture(unittest.TestCase):
    def test_requires_actual_pair_order_host_hold_and_zero_queued_traffic(self):
        run,capture,diag,host,log=capture_fixture(deadline=True)
        _,proofs=corroborate_diagnostic(run,capture,diag)
        row=next(p for p in proofs if p['caller']=='C queued deadline')
        self.assertEqual((row['commands'],row['replies'],row['request_id']),(0,0,11))
        self.assertEqual(len(proofs),49)
        self.assertEqual(sum('command' in p and 'reply' in p for p in proofs),46)
        corroborate_host_hold(host,diag,proofs,log,{'bus':1,'address':101})

    def test_downgrade_false_flag_and_missing_data_rejected(self):
        for mutation in ['version','flag','missing','late_result']:
            run,capture,diag,_,_=capture_fixture(deadline=True)
            if mutation=='version':diag['format_version']=5
            elif mutation=='flag':diag['deadline_requested']=False
            elif mutation=='missing':next(r for r in diag['records'] if r.get('cancel')=='held').pop('deadline')
            else:next(r for r in diag['records'] if r.get('cancel')=='released')['deadline']['result']='00'*104
            with self.subTest(mutation=mutation):
                with self.assertRaises((CaptureError,ValueError)):corroborate_diagnostic(run,capture,diag)

    def test_queued_feature_out_reply_or_gap_traffic_rejected(self):
        for mutation in ['out','reply','gap']:
            run,capture,diag,_,_=capture_fixture(deadline=True)
            held,final=[r for r in diag['records'] if 'cancel' in r]
            if mutation=='reply':
                row=copy.deepcopy(capture['complete'][0]);row.update(opcode=0x0403,wall_ns=held['end_wall_ns']-10)
                capture['complete'].append(row)
            else:
                row=copy.deepcopy(capture['commands'][0]);row.update(opcode=0x0403,wall_ns=held['end_wall_ns']-10 if mutation=='out' else final['end_wall_ns']+1)
                capture['commands'].append(row)
            with self.assertRaises(CaptureError):corroborate_diagnostic(run,capture,diag)

    def test_option_cannot_skip_real_hold_or_required_modes(self):
        for command,recovery,diagnostic,cancel in [('support',True,True,True),('run',False,True,True),('run',True,False,True),('run',True,True,False)]:
            args=SimpleNamespace(command=command,output=Path('/unused-deadline-output'),fault_recovery=recovery,
                qmp_hotplug=False,event_copy_verify=False,diagnostic_verify=diagnostic,
                diagnostic_cancel_verify=cancel,diagnostic_deadline_verify=True)
            with self.assertRaisesRegex(ValueError,'live deadline gate'):run_target(args)
