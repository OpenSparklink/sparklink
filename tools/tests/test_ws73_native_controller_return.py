# SPDX-License-Identifier: GPL-2.0-only
"""Mode/receipt/verdict fixtures only; no kernel, daemon or USB qualification."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_native_controller_return as gate
from ws73_native_return import fixture_phases, OBSERVATION, decode
from ws73_target import run_exit_code
from ws73_target_control import ConnectionControlRun, PassthroughControlRun


class ControllerReturn(unittest.TestCase):
    def test_scope_cannot_relabel_original_connection_gate(self):
        self.assertEqual(fixture_phases(['ws73.native_return=1']), (0,1,2,3))
        for role, phase in [('initiator',2),('acceptor',3)]:
            self.assertEqual(fixture_phases(['ws73.native_controller_return='+role]), (phase,))
        for tokens in [[],['ws73.native_return=1']*2,['ws73.native_controller_return=no'],
                       ['ws73.native_controller_return=initiator']*2,
                       ['ws73.native_return=1','ws73.native_controller_return=initiator'],
                       ['ws73.native_controller_return=initiator','ws73.native_controller_return=acceptor']]:
            with self.subTest(tokens=tokens),self.assertRaises(ValueError):fixture_phases(tokens)

    def test_requested_roles_share_existing_dedicated_gate_constraints(self):
        args=SimpleNamespace(native_controller_return='initiator',passthrough=True,
            connection_verify=True,channel_socket_verify=True,channel_socket_bytes=61,channel_socket_rounds=4)
        self.assertEqual(gate.requested(args),'initiator')
        for key,value in [('native_controller_return',True),('native_controller_return','other'),
                          ('native_return_verify',True),('passthrough',False),
                          ('connection_verify',False),('channel_socket_bytes',250),
                          ('channel_socket_rounds',3),('dynamic_channel_verify',True),
                          ('security_agent','approve'),('ssap_initialization_verify',True)]:
            bad=copy.copy(args);setattr(bad,key,value)
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):gate.requested(bad)
        self.assertIsNone(gate.requested(SimpleNamespace()))

    def test_existing_remove_confirm_is_the_only_host_action_path(self):
        events=[];session=Mock()
        for name in ('before_remove','removed','before_readd'):
            getattr(session,name).side_effect=lambda name=name:events.append(name)
        run=SimpleNamespace(native_controller_return=session,confirmations=0)
        def actual(self,message):
            events.append('original-confirm-'+str(self.confirmations));self.confirmations+=1
        with patch.object(PassthroughControlRun,'confirm',actual):
            # Method uses super(), so exercise its actual class instance
            # without constructing a VM run or substituting any Host Engine.
            instance=object.__new__(ConnectionControlRun)
            instance.native_controller_return=run.native_controller_return
            instance.confirmations=0
            instance.confirm('remove');instance.confirm('readd')
        self.assertEqual(events,['before_remove','original-confirm-0','removed','before_readd','original-confirm-1'])

    def test_controller_boot_and_result_are_required_by_terminal_verdict(self):
        for role in ['initiator','acceptor']:
            row=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,
                qemu_args=['-append','ws73.native_controller_return='+role],
                native_controller_return_requested=role,native_controller_return_acceptance=True)
            self.assertEqual(run_exit_code(row),1)
            for key,value in [('supervisor_exit',False),('qemu_exit',False),
                              ('native_controller_return_requested',None),('native_controller_return_requested',True),
                              ('qemu_args',[]),('native_return_requested',True)]:
                bad=dict(row);bad[key]=value;self.assertEqual(run_exit_code(bad),1)

    def test_only_direct_owner_retiring_error_releases_the_barrier(self):
        prefix='Error: GDBus.Error:org.freedesktop.DBus.Error.Failed: '
        def row(message):return dict(exit=1,stdout='',stderr=prefix+message+'\n')
        self.assertEqual(gate.owner_probe_state(row('connection owner retiring')),'retiring')
        for message in ['management handoff busy','connection Native creation busy','connection lifetime is not current']:
            self.assertEqual(gate.owner_probe_state(row(message)),'not-yet-observed')
        for value in [row('registration removed'),row('connection owner retired during native bind'),
                      dict(exit=0,stdout='(handle 0,)\n',stderr=''),dict(exit=False,stdout='',stderr=''),
                      dict(exit='timeout',stdout='',stderr=''),
                      dict(exit=1,stdout='',stderr='Error: GDBus.Error:org.freedesktop.DBus.Error.UnknownObject: gone\n')]:
            with self.subTest(value=value),self.assertRaises(gate.CaptureError):gate.owner_probe_state(value)

    def test_ordinary_business_runs_on_replacement_in_this_mode(self):
        events=[];instance=object.__new__(ConnectionControlRun)
        instance.args=SimpleNamespace(native_return_verify=False,ssap_initialization_verify=False)
        instance.native_controller_return=Mock()
        instance.native_controller_return.replug.side_effect=lambda a,b:events.append(('replacement',a,b))
        with patch.object(PassthroughControlRun,'phase',side_effect=lambda a,b,n,label:events.append(('radio',label))), \
             patch('ws73_connection_control.execute',side_effect=lambda run,a,b:events.append(('business',a,b))), \
             patch('ws73_registry_metadata.execute',side_effect=lambda run,a,b:events.append(('registry',a,b))):
            instance.phase('old','other',20,'initial')
            instance.phase('new','other',2,'replug')
        self.assertEqual(events,[('radio','initial'),('replacement','new','other'),
                                 ('business','new','other'),('registry','new','other'),('radio','replug')])

    def test_summary_requires_original_identity_bounded_return_and_no_overclaim(self):
        held=decode(OBSERVATION.pack(b'SLKRET1\0',2,10,11,7,1,2,3,4,100,200,0,0,0,1))
        value=dict(status=gate.STATUS,role='initiator',slices=1,held=held,
            returned=dict(held,outcome=1,end_mono_ns=150,end_wall_ns=250),
            create=dict(command={'fixture':True},status={'fixture':True},outcomes=[{'fixture':True}]*2),
            peer_down={'fixture':True},fixture_sha256='a'*64,replacement_generation=9,
            actual_owner_retirement_refusal=dict(exit=1,stdout='',stderr='Error: GDBus.Error:org.freedesktop.DBus.Error.Failed: connection owner retiring\n'),
            owner_probe_binary=dict(sha256='b'*64),
            hcc=dict(source='HCC_GET_CHIP_TYPE',model='U',bus='USB'),
            actual_guest_controller_removal=True,same_daemon=True,socket_inode_convergence=True,
            kernel_reference_or_uaf_proof=False,physical_acceptance=False,automatic_recovery=False)
        self.assertTrue(gate.valid_summary(value))
        mutations=[lambda p:p.update(role='acceptor'),lambda p:p.update(slices=True),
                   lambda p:p.update(held=None),lambda p:p.update(fixture_sha256='old'),
                   lambda p:p.update(replacement_generation=3),lambda p:p.update(same_daemon=False),
                   lambda p:p.update(automatic_recovery=True),lambda p:p.update(physical_acceptance=True),
                   lambda p:p.update(kernel_reference_or_uaf_proof=True),
                   lambda p:p['returned'].update(outcome=2),lambda p:p['returned'].update(lifetime=99),
                   lambda p:p['held'].update(fd=True),lambda p:p['create'].update(outcomes=[]),
                   lambda p:p.pop('peer_down'),lambda p:p['hcc'].update(bus='UART'),
                   lambda p:p.pop('actual_owner_retirement_refusal'),
                   lambda p:p['actual_owner_retirement_refusal'].update(stderr='error: immutable identity unavailable or changed: registration removed\n'),
                   lambda p:p['owner_probe_binary'].update(sha256='old')]
        for n,mutate in enumerate(mutations):
            bad=copy.deepcopy(value);mutate(bad)
            with self.subTest(n=n):self.assertFalse(gate.valid_summary(bad))


if __name__=='__main__':unittest.main()
