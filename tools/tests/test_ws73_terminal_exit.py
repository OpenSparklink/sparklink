# SPDX-License-Identifier: GPL-2.0-only
"""Actual verdict function, terminal-shape fixtures only; no VM/RF acceptance."""
from pathlib import Path
import copy
import ast
import inspect
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_target import run_exit_code


def protected_returns(statements):
    """Source-level finalization guard,not a CFG/liveness or kernel proof."""
    result=[]
    def visit(node):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):return
        if isinstance(node,ast.Return):result.append(node)
        for child in ast.iter_child_nodes(node):visit(child)
    for node in statements:visit(node)
    return result


class TerminalExit(unittest.TestCase):
    def test_actual_run_cannot_return_before_common_sealing_and_finalization(self):
        from ws73_target import _run
        fn=ast.parse(inspect.getsource(_run)).body[0]
        protected=next(n for n in fn.body if isinstance(n,ast.Try) and n.finalbody)
        self.assertEqual(protected_returns([protected]),[])
        tail=fn.body[fn.body.index(protected)+1:]
        self.assertTrue(any(isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='run_exit_code'
                            for statement in tail for n in ast.walk(statement)))
        # A plausible early success under an optional selector must fail this
        # guard even when its finally still saves a manifest. No real VM here.
        bad=copy.deepcopy(protected)
        bad.body.append(ast.If(test=ast.Name(id='runtime_addresses',ctx=ast.Load()),
                               body=[ast.Return(value=ast.Constant(value=0))],orelse=[]))
        self.assertEqual(len(protected_returns([bad])),1)

    def special(self,kind):
        r=dict(status='REAL_EARLY_BOOTSTRAP_FAULT_ISOLATION_PASS'if kind=='early'else'REAL_DAEMON_CHANNEL_DEATH_PASS',
               qemu_exit=0,supervisor_exit=0)
        if kind=='early':
            r['early_bootstrap_fault_requested']=True
            r['early_bootstrap_corroboration']={k:dict(connection=[{'fixture':1}]*2,
                data=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=4,proofs=[{'fixture':1}]*2))for k in ['during_fault','after_retry']}
        else:
            r.update(channel_daemon_crash_requested=True,channel_daemon_index=0,
                channel_daemon_corroboration=dict(status='REAL_DAEMON_CHANNEL_DEATH_USB_CORROBORATED',
                    first_blocked_errno=13,business_round_trips=2,legs=[{'fixture':1}]*8,original_up=[{'fixture':1}]*2,
                    physical_down_before_wake=[],actual_daemon_death=True,successor_does_not_renew_old_fd=True,
                    common_owner_both_leases_withdrawn=True,independent_device_business_isolation=False,
                    physical_acceptance=False,automatic_recovery_acceptance=False,full_grant_complete=False))
        return r

    def test_special_modes_require_same_actual_terminal_receipts(self):
        # Terminal-shape fixtures only. Actual special-mode corroborators and
        # real hardware acceptance remain separate; these are not wire stubs.
        for kind in ['early','death']:
            r=self.special(kind);self.assertEqual(run_exit_code(r),0)
            for key in ['qemu_exit','supervisor_exit']:
                for value in [None,True,0.0,-9,1]:
                    with self.subTest(kind=kind,key=key,value=value):self.assertEqual(run_exit_code(r|{key:value}),1)
                bad=copy.deepcopy(r);bad.pop(key);self.assertEqual(run_exit_code(bad),1)
            self.assertEqual(run_exit_code(r|dict(connection_verify_requested=True)),1)
            self.assertEqual(run_exit_code(r|dict(channel_socket_verification_requested=True)),1)
            self.assertEqual(run_exit_code(r|dict(channel_socket_close_prefix_requested=True)),1)
            for key in ['connection_verify_requested','channel_socket_verification_requested','channel_socket_close_prefix_requested']:
                for value in [0,1,None,'false']:
                    self.assertEqual(run_exit_code(r|{key:value}),1)
            self.assertEqual(run_exit_code(r|dict(early_bootstrap_fault_requested=True,channel_daemon_crash_requested=True)),1)
            bad=copy.deepcopy(r);bad.pop('early_bootstrap_fault_requested'if kind=='early'else'channel_daemon_crash_requested')
            self.assertEqual(run_exit_code(bad),1)

    def test_special_summaries_reject_missing_scope_and_required_business(self):
        r=self.special('early')
        for label in ['during_fault','after_retry']:
            for field,value in [('connection',[]),('data',{}),('data',None)]:
                bad=copy.deepcopy(r);bad['early_bootstrap_corroboration'][label][field]=value
                self.assertEqual(run_exit_code(bad),1)
            for field,value in [('round_trips',True),('round_trips',0),('proofs','xx'),('proofs',[{},{}])]:
                bad=copy.deepcopy(r);bad['early_bootstrap_corroboration'][label]['data'][field]=value
                self.assertEqual(run_exit_code(bad),1)
        r=self.special('death')
        for field,value in [('business_round_trips',0),('legs',[]),('original_up',[]),
                            ('automatic_recovery_acceptance',True),('full_grant_complete',True),
                            ('successor_does_not_renew_old_fd',False),('first_blocked_errno',13.0),
                            ('physical_down_before_wake',[{'fixture':1}])]:
            bad=copy.deepcopy(r);bad['channel_daemon_corroboration'][field]=value
            self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(r);bad['channel_daemon_corroboration']['first_blocked_errno']=116
        self.assertEqual(run_exit_code(bad),1)
        bad['channel_daemon_corroboration']['physical_down_before_wake']=[{'fixture':1}]
        self.assertEqual(run_exit_code(bad),0)

    def test_requested_connection_and_channel_summaries_cannot_be_deleted(self):
        # Terminal-shape fixtures, not reconstructed USB/application evidence.
        r=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,
            connection_verify_requested=True,connection_corroboration=[{'fixture':1}]*2,
            connection_object_corroboration=[{'fixture':1}]*2,
            channel_socket_verification_requested=True,channel_socket_rounds_requested=4,
            channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8))
        self.assertEqual(run_exit_code(r),0)
        for key in ['connection_corroboration','connection_object_corroboration','channel_socket_corroboration']:
            for value in [None,{},[],True,'PASS']:
                with self.subTest(key=key,value=value):self.assertEqual(run_exit_code(r|{key:value}),1)
            bad=copy.deepcopy(r);bad.pop(key);self.assertEqual(run_exit_code(bad),1)
        for key in ['connection_verify_requested','channel_socket_verification_requested']:
            for value in [None,0,1,'true']:
                self.assertEqual(run_exit_code(r|{key:value}),1)
        for value in [True,0,7,9,'8',8.0]:
            bad=copy.deepcopy(r);bad['channel_socket_corroboration']['round_trips']=value
            self.assertEqual(run_exit_code(bad),1)

    def test_prefix_close_requires_post_close_proofs_without_claiming_round_trips(self):
        # Only finalizer shape. The raw oracle independently checks PB order,
        # final-close timing, ordinary credentials and every actual SSAP leg.
        r=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,
            channel_socket_verification_requested=True,channel_socket_close_prefix_requested=True,
            channel_socket_rounds_requested=1,channel_socket_bytes_requested=2042,
            ordinary_prefix_close_acceptance=True,ordinary_channel_socket_acceptance=False,
            channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',
                round_trips=0,prefix_close_phases=2,physical_prefix_delivery_acceptance=True,
                proofs=[dict(phase=n,prefix_close=dict(other_channel_after_close=True),ssap_values=[{'fixture':True}])for n in range(2)]))
        self.assertEqual(run_exit_code(r),0)
        for key,value in [('channel_socket_verification_requested',False),('channel_socket_bytes_requested',61),
                          ('channel_socket_rounds_requested',2),('ordinary_prefix_close_acceptance',False),
                          ('ordinary_channel_socket_acceptance',True)]:
            self.assertEqual(run_exit_code(r|{key:value}),1)
        for key,value in [('round_trips',2),('prefix_close_phases',True),('physical_prefix_delivery_acceptance',False),('proofs',[])]:
            bad=copy.deepcopy(r);bad['channel_socket_corroboration'][key]=value
            self.assertEqual(run_exit_code(bad),1)
        for n in range(2):
            for key,value in [('phase',1-n),('prefix_close',{}),('ssap_values',[])]:
                bad=copy.deepcopy(r);bad['channel_socket_corroboration']['proofs'][n][key]=value
                self.assertEqual(run_exit_code(bad),1)

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
