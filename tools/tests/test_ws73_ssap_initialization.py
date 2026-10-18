"""Test coordinator/parser contracts with fixtures; no WS73/VM qualification."""
import copy
import contextlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_ssap_initialization as init
from ws73_diagnostic_hold import PROPERTIES, write_marker
from ws73_target import run_exit_code


class Monitor:
    """QMP state fixture only, not a successful controller implementation."""
    def __init__(self):
        self.state = [dict(zip(PROPERTIES, [False, False, 0, 0, 0, 0, False, 0])) for _ in range(2)]
        for row in self.state:
            row.update({init.SELECTOR: False, 'test-runtime-in-skip-requested': 0,
                        'test-runtime-in-skip-remaining': 0, 'test-runtime-in-skipped': 0,
                        'test-enumeration-reset-once': False, 'attached': True})
            row.update(dict.fromkeys(['host-reset', 'kernel-driver-detach', 'guest-reset', 'guest-resets-all'], False))
        self.mutations = []

    def execute(self, command, args):
        number = int(args['path'][-1])
        row = self.state[number]
        key = args['property']
        if command == 'qom-get':
            return row[key]
        self.mutations.append((number, key, args['value']))
        if key in [init.SELECTOR, PROPERTIES[0]]:
            row[key] = args['value']
        elif key == 'test-runtime-in-release':
            row.update({PROPERTIES[1]: False, PROPERTIES[3]: 1})
        else:
            raise AssertionError('unexpected mutation')


def fixture():
    phases = []
    commands = []
    for n in range(2):
        owner = dict(index=n, generation=7+n, path=f'/org/sparklink/slk{n}_g{7+n}')
        obj = dict(generation=7+n, lifetime=1, handle=0, role=n, address_type=0,
                   address='01:02:03:04:05:06', path=owner['path']+'/peer_t0_010203040506/link_1')
        selected = 'Selected '+owner['path']+'\n'
        cancel = dict(args=['/bin/slctl', '--adapter', owner['path'], 'cancel-discovery'],
                      exit=0, stderr='', stdout=selected+f"NativePoliciesCancelRequest: generation={owner['generation']}\nNativePoliciesCancelled: generation={owner['generation']}\n",
                      start_wall_ns=20, end_wall_ns=80,
                      credentials=dict(uids=[1000]*4, capabilities=dict.fromkeys(['CapEff','CapPrm','CapAmb','CapInh'], '0')))
        connect_index=len(commands)
        commands.append(dict(start_wall_ns=6,end_wall_ns=7))
        cancel_index=len(commands)
        commands.append(cancel)
        current = dict(args=['/bin/slctl','--adapter',owner['path'],'connection-info',obj['path']], exit=0, stderr='', end_wall_ns=40,
                       stdout=selected+f"NativeConnectionInfo: generation={obj['generation']} lifetime=1 handle=0 role={n} type=0 address={obj['address']} known=true connected=true path={obj['path']}\n")
        failed = dict(args=['/bin/slctl','--adapter',owner['path'],'ssap-info',obj['path']], exit=1,
                      stdout=selected, stderr='Error: org.freedesktop.DBus.Error.Failed: Permission denied (os error 13)\n', end_wall_ns=50)
        def management(state):
            return dict(exit=0,end_wall_ns=30,stdout=f"NativeManagementStatus: generation={owner['generation']} mode={int(state==1)} state={state} flags={int(state==1)} errno=0 status=0x00 opcode=0x0000\n")
        def fd(stage, number, rows, stamp):
            return dict(wall_ns=stamp,sockets=[dict(fd=i,inode=f'socket:[{i}]')for i in rows],
                        request=dict(sequence=n*4+number,phase=n,stage=stage),daemon=dict(pid=42,start_ticks=17),supervisor_uid=0)
        requests=[dict(hold_phase=p,wall_ns=t) for p,t in zip(['arm_ready','wait_held','release_ready'],[2,8,70])]
        acks=[dict(stage=p,request=r,state=dict(zip(PROPERTIES,s))) for p,r,s in zip(['armed','held','released'],requests,
              [[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]])]
        phases.append(dict(caller=owner,target=owner,typed_objects=[dict(owner=owner,object=obj)],connect_command=connect_index,
                           selection=dict(phase=n,slot=n,index=n,generation=7+n,controller_path=owner['path'],role=n),
                           still_connected=current,failed_owner=failed,cancel=cancel,disconnect_command=cancel_index,
                           revocation_polls=[management(2)],management_after=management(1),cancel_pending_before_release=True,
                           hold=dict(markers=requests,acks=acks,ack_receipts=[dict(stage=p,wall_ns=t)for p,t in zip(['armed','held','released'],[5,10,75])]),
                           fds_before=fd('before',0,[1],1),fds_bound=fd('bound',1,[1,2,3],12),
                           fds_withdrawn=fd('withdrawn',2,[1,3],60),fds_after_down=fd('after-down',3,[1],85),end_wall_ns=90))
    return dict(initial=[v['target']for v in phases],daemon_before=dict(pid=42,start_ticks=17),commands=commands,
                ssap_initialization=dict(mode=init.METHOD,status='CMTC_REVOCATION_EVIDENCE_PENDING',phases=phases,
                                         new_engine=False,physical_acceptance=False,automatic_recovery_acceptance=False))


class InitializationGate(unittest.TestCase):
    def test_expected_error_uses_actual_nonzero_child_without_success_wrapper(self):
        import os
        from ws73_north_star import Run, daemon_identity
        # Real collector/subprocess; the executable supplies only diagnostic
        # text, not a controller or protocol success. No VM qualification.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            program = root/'slctl'
            program.write_text('#!/bin/sh\nprintf "Selected %s\\n" "$2"\n'
                'printf "error: broker: org.freedesktop.DBus.Error.Failed: Permission denied (os error 13)\\n" >&2\nexit 1\n')
            program.chmod(0o700)
            run = Run(SimpleNamespace(output=root/'run', slctl=program, slkd_pid=os.getpid()))
            run.pid = daemon_identity(os.getpid())
            owner = dict(path='/org/sparklink/slk0_g1')
            reference = dict(path=owner['path']+'/peer_t00_010203040506/link_1')
            row = init.observe_owner_failure(run, owner, reference)
            self.assertIs(run.data['commands'][0], row)
            self.assertEqual(row['exit'], 1)
            self.assertGreaterEqual(row['end_wall_ns'], row['start_wall_ns'])
            for key, value in [('exit', 0), ('exit', True), ('stderr', 'original deadline')]:
                bad = dict(row, **{key: value})
                with self.assertRaises(ValueError):init.owner_failure(bad, owner, reference)

    def test_selection_release_uses_same_original_hold_two_targets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(init, 'validate_qemu'):
            record = {}
            c = init.Coordinator(tmp, record, 'fixture')
            m = Monitor()
            for n in range(2):
                folder = c.root/f'phase-{n}'
                folder.mkdir(parents=True)
                write_marker(folder/'selection.json', dict(phase=n,slot=n,index=n+5,generation=7+n,controller_path=f'/org/sparklink/slk{n+5}_g{7+n}',role=n))
                write_marker(folder/'hold-arm_ready.json', dict(hold_phase='arm_ready',wall_ns=1))
                c.poll(m,lambda i:dict(bus=1,address=i+2))
                write_marker(folder/'hold-wait_held.json', dict(hold_phase='wait_held',wall_ns=2))
                c.poll(m,lambda i:None)
                self.assertFalse((folder/'hold-held-ack.json').exists())
                m.state[n].update({PROPERTIES[0]:False,PROPERTIES[1]:True,PROPERTIES[2]:1})
                c.poll(m,lambda i:None)
                write_marker(folder/'hold-release_ready.json', dict(hold_phase='release_ready',wall_ns=3))
                c.poll(m,lambda i:None)
            self.assertTrue(record['complete'])
            self.assertEqual(m.mutations, [(n,k,True)for n in range(2)for k in [init.SELECTOR,PROPERTIES[0],'test-runtime-in-release']])

    def test_dirty_selector_or_expiry_does_not_become_success(self):
        for key,value in [(init.SELECTOR,True),('test-runtime-in-skip-requested',1),('test-enumeration-reset-once',True),(PROPERTIES[4],1)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory()as tmp,patch.object(init,'validate_qemu'):
                c=init.Coordinator(tmp,{},'fixture');m=Monitor();m.state[0][key]=value
                p=c.root/'phase-0';p.mkdir(parents=True)
                write_marker(p/'selection.json',dict(phase=0,slot=0,index=0,generation=7,controller_path='/org/sparklink/slk0_g7',role=0))
                write_marker(p/'hold-arm_ready.json',dict(hold_phase='arm_ready',wall_ns=1))
                with self.assertRaises(ValueError):c.poll(m,lambda i:dict(bus=1,address=2))
                self.assertFalse(m.state[0][PROPERTIES[0]])
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'qemu';p.write_bytes(b'wrong fixture')
            with self.assertRaises(ValueError):init.validate_qemu(p)

    def test_actual_record_contract_rejects_false_owner_and_cleanup(self):
        good=fixture();init.verify_guest(good)
        changes=[lambda d:d['ssap_initialization']['phases'].pop(),
                 lambda d:d['ssap_initialization']['phases'][0].update(cancel_pending_before_release=False),
                 lambda d:d['ssap_initialization']['phases'][0]['failed_owner'].update(exit=0),
                 lambda d:d['ssap_initialization']['phases'][0]['failed_owner'].update(stderr='transport original deadline'),
                 lambda d:d['ssap_initialization']['phases'][0]['still_connected'].update(exit=1),
                 lambda d:d['ssap_initialization']['phases'][0]['fds_after_down'].update(sockets=[dict(fd=2,inode='socket:[2]')]),
                 lambda d:d['ssap_initialization']['phases'][0]['fds_withdrawn'].update(wall_ns=75),
                 lambda d:d['ssap_initialization']['phases'][0]['cancel']['credentials'].update(capabilities={}),
                 lambda d:d['ssap_initialization']['phases'][0]['fds_bound']['daemon'].update(pid=99),
                 lambda d:d['ssap_initialization']['phases'][0]['fds_bound']['request'].update(stage='before')]
        for change in changes:
            bad=copy.deepcopy(good);change(bad)
            with self.assertRaises((ValueError,KeyError,StopIteration)):init.verify_guest(bad)

    def test_missing_bounded_proof_fails_outer_verdict(self):
        # Use a complete unrelated fixture as a starting point; its old PASS
        # must not satisfy this new requested gate.
        r=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0)
        self.assertEqual(run_exit_code(r),0)
        r.update(ssap_initialization_requested=True,ssap_initialization_acceptance=True)
        self.assertEqual(run_exit_code(r),1)

    def test_real_local_socket_inode_snapshot_and_strict_bounds(self):
        import os
        a,b=socket.socketpair()
        try:
            value=init.sockets(os.getpid())
            self.assertTrue({f'socket:[{os.fstat(s.fileno()).st_ino}]'for s in [a,b]}<=init.inodes(value))
        finally:a.close();b.close()
        for bad in [[dict(fd=-1,inode='socket:[2]')],[dict(fd=1,inode='file')],
                    [dict(fd=1,inode='socket:[2]')]*2]:
            with self.assertRaises(ValueError):init.inodes(dict(sockets=bad))

    def test_entry_requires_existing_separate_socket_preservation(self):
        args=SimpleNamespace(ssap_initialization_verify=True,passthrough=True,connection_verify=True,channel_socket_verify=True)
        self.assertTrue(init.requested(args))
        for key,value in [('passthrough',False),('connection_verify',False),('channel_socket_verify',False),
                          ('ssap_owner_lifecycle_verify',True),('security_agent','approve'),('channel_socket_boundaries',True)]:
            bad=copy.copy(args);setattr(bad,key,value)
            with self.assertRaises(ValueError):init.requested(bad)

    def test_fixed_daemon_observer_eight_real_local_snapshots_and_bad_order(self):
        import os
        # The root identity is a fixture, while /proc and the socket pair are
        # real local OS resources. This does not claim actual root VM policy.
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);requests=root/'application/passthrough-control/ssap-initialization-fd-requests'
            requests.mkdir(parents=True)
            for n in range(8):
                write_marker(requests/f'{n}.json',dict(sequence=n,phase=n//4,
                    stage=['before','bound','withdrawn','after-down'][n%4],wall_ns=n+1))
            out=io.StringIO()
            with patch.object(init.os,'geteuid',return_value=0),contextlib.redirect_stdout(out):init.observe_fds(root,os.getpid())
            self.assertEqual(out.getvalue(),'WS73_SSAP_INIT_FDS_FINISHED\n')
            values=[json.loads((root/'ssap-initialization-fds'/f'{n}.json').read_text())for n in range(8)]
            self.assertEqual([v['request']['sequence']for v in values],list(range(8)))
            self.assertTrue(all(v['daemon']['pid']==os.getpid()for v in values))
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);requests=root/'application/passthrough-control/ssap-initialization-fd-requests';requests.mkdir(parents=True)
            write_marker(requests/'0.json',dict(sequence=0,phase=0,stage='withdrawn',wall_ns=1))
            with patch.object(init.os,'geteuid',return_value=0),self.assertRaises(ValueError):init.observe_fds(root,os.getpid())
        with patch.object(init.os,'geteuid',return_value=1000),self.assertRaises(ValueError):init.observe_fds('/does-not-exist',os.getpid())

    def test_host_and_guest_explicit_physical_modes_share_one_validator(self):
        host=SimpleNamespace(ssap_initialization_verify=True,qmp_hotplug=True,connection_verify=True,channel_socket_verify=True)
        self.assertTrue(init.requested(host,passthrough=host.qmp_hotplug))
        with self.assertRaises(ValueError):init.requested(host,passthrough=False)
        # The shared validator does not infer another entry point's CLI name.
        with self.assertRaises(ValueError):init.requested(host)
        guest=SimpleNamespace(ssap_initialization_verify=True,passthrough=True,connection_verify=True,channel_socket_verify=True)
        self.assertTrue(init.requested(guest))

    def test_actual_init_shell_line_forwards_only_explicit_mode(self):
        import os
        source=(Path(__file__).resolve().parents[1]/'ws73_target_init.sh').read_text()
        line=next(s.strip()for s in source.splitlines()if 'connection_arg="$connection_arg --ssap-initialization-verify"'in s)
        with tempfile.TemporaryDirectory()as tmp:
            cmdline=Path(tmp)/'cmdline'
            for content,wanted in [('ws73.ssap_initialization=1',' --ssap-initialization-verify'),
                                   ('ws73.ssap_initialization=2',''),('unrelated=1','')]:
                cmdline.write_text(content+'\n')
                program='connection_arg=""; '+line.replace('/proc/cmdline','"$test_cmdline"')+'; printf \'%s\' "$connection_arg"'
                result=subprocess.run(['sh','-c',program],env=os.environ|{'test_cmdline':str(cmdline)},capture_output=True,text=True)
                self.assertEqual((result.returncode,result.stdout,result.stderr),(0,wanted,''))
