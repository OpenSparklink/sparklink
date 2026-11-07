# SPDX-License-Identifier: GPL-2.0-only
"""Real CLI/boot refusal and static caller checks for the deadline opt-in.

No build, controller, daemon or VM is started. The host refusal replaces only
the host identity read and makes process launch an explicit test failure.
Static staging checks cannot establish runtime or hardware qualification.
"""
import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ws73_capture import CaptureError
from ws73_channel_socket import reject_unattributed_ssap
from test_ws73_ssap_command_policy_wiring import function,calls


class CommandDeadlineWiring(unittest.TestCase):
    def test_real_host_guest_clis_expose_all_three_distinct_opt_ins(self):
        for argv in ([sys.executable,str(TOOLS/'ws73_target.py'),'run','--help'],
                     [sys.executable,str(TOOLS/'ws73_target_control.py'),'--help']):
            result=subprocess.run(argv,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            for flag in ('--ssap-write-command-verify','--ssap-write-command-policy-verify',
                         '--ssap-write-command-deadline-verify'):
                self.assertIn(flag,result.stdout)
        for extra in ([],['--ssap-write-command-verify']):
            result=subprocess.run([sys.executable,str(TOOLS/'ws73_target_control.py'),
                '--slctl','/bin/slctl','--slkd-pid','1','--output','/unused',
                '--passthrough','--connection-verify','--channel-socket-verify',
                '--ssap-write-command-deadline-verify',*extra],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertRegex(result.stderr.lower(),'deadline.*policy|policy.*deadline')

    def test_host_rejects_missing_dependency_before_output_or_launch(self):
        import ws73_target
        for base,policy in ((False,False),(True,False),(False,True)):
            with tempfile.TemporaryDirectory() as directory:
                output=Path(directory)/'must-not-exist'
                args=SimpleNamespace(command='run',output=output,qmp_hotplug=True,
                    connection_verify=True,channel_socket_verify=True,
                    ssap_write_command_deadline_verify=True,
                    ssap_write_command_policy_verify=policy,ssap_write_command_verify=base)
                with patch.object(ws73_target,'ordinary_identity'),\
                     patch.object(ws73_target.subprocess,'Popen',side_effect=AssertionError('must not launch')),\
                     self.assertRaisesRegex(ValueError,'(?i)command.*(policy|deadline)|(policy|deadline).*command'):
                    ws73_target._run(args)
                self.assertFalse(output.exists())

    def test_init_uses_exact_existing_parser_and_refuses_ambiguous_tokens(self):
        source=(TOOLS/'ws73_target_init.sh').read_text()
        line=next(line for line in source.splitlines() if 'command_deadline_arg=$(' in line)
        code=re.search(r"-c '([^']+)'",line).group(1)
        self.assertIn('from ws73_ssap_command_deadline import boot_requested',code)
        self.assertIn('|| fail command-deadline-selector',line)
        base=['ws73.ssap_write_command=1','ws73.ssap_command_policy=1']
        token='ws73.ssap_command_deadline=1'
        env=dict(os.environ,PYTHONPATH=str(TOOLS))
        for tokens,expected in (([],''),(base,''),(base+[token],'--ssap-write-command-deadline-verify')):
            result=subprocess.run([sys.executable,'-c',code,*tokens],env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),expected)
        for tokens in ([token],[base[0],token],[base[1],token],base+[token,token],
                       base+['ws73.ssap_command_deadline'],base+['ws73.ssap_command_deadline='],
                       base+['ws73.ssap_command_deadline=0'],base+['ws73.ssap_command_deadline=2']):
            with self.subTest(tokens=tokens):
                result=subprocess.run([sys.executable,'-c',code,*tokens],env=env,capture_output=True,text=True,timeout=5)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')

    def test_dispatch_retains_positive_policy_then_terminal_business_callback(self):
        execute=function('execute','ws73_channel_socket.py')
        previous=0
        for name in ('command_execute','command_policy_execute','command_deadline_execute'):
            found=calls(execute,name);self.assertEqual(len(found),1,name)
            self.assertGreater(found[0].lineno,previous);previous=found[0].lineno
        call=calls(execute,'command_deadline_execute')[0]
        self.assertIsInstance(call.args[2],ast.Lambda)
        self.assertEqual(ast.unparse(call.args[2]),'lambda deadline: run_applications(run, row, processes, files, deadline)')
        # The ordinary fallback must exclude this branch, preventing a second
        # independent run from concealing failure of the post-terminal one.
        ordinary=[node for node in ast.walk(execute) if isinstance(node,ast.If)
                  and any(calls(child,'run_applications') for child in node.body)]
        self.assertTrue(any('ssap_write_command_deadline_verify' in ast.unparse(n.test) for n in ordinary))
        corroborate=function('corroborate','ws73_channel_socket.py')
        names=('command_corroborate','command_policy_corroborate','command_deadline_corroborate','command_deadline_business')
        found=[calls(corroborate,name) for name in names]
        self.assertTrue(all(len(x)==1 for x in found))
        self.assertEqual([x[0].lineno for x in found],sorted(x[0].lineno for x in found))
        self.assertEqual([ast.unparse(x) for x in found[2][0].args],['row','value_matched','sdus'])
        self.assertEqual([ast.unparse(x) for x in found[3][0].args],['row',"row['ssap_command_deadline_case']",'legs'])

    def test_staging_and_all_consumers_keep_deadline_verifier(self):
        name='ws73_ssap_command_deadline.py'
        for function_name in ('prepare_from_carrier','prepare_locked'):
            node=function(function_name,'ws73_target.py')
            found=[n for n in ast.walk(node) if isinstance(n,ast.Constant) and n.value==name]
            self.assertEqual(len(found),1 if function_name=='prepare_from_carrier' else 2)
        host=function('_run','ws73_target.py')
        for name in ('command_deadline_requested','command_deadline_inputs','command_deadline_rows','command_deadline_summary'):
            self.assertEqual(len(calls(host,name)),1,name)
        self.assertEqual(len(calls(function('run_exit_code','ws73_target.py'),'valid_command_deadline_manifest')),1)
        guest=function('verify_passthrough','ws73_target_guest.py')
        self.assertEqual(len(calls(guest,'deadline_boot')),1)
        self.assertEqual(len(calls(guest,'deadline_rows')),1)

    def test_deadline_opt_in_does_not_accept_unclaimed_response_or_late_sdu(self):
        row=dict(start_wall_ns=10,end_wall_ns=20,ssap_write_command_contract=1,
            ssap_command_policy_required=True,ssap_command_policy_contract=1,
            ssap_command_deadline_required=True,ssap_command_deadline_contract=1)
        for opcode in (1,12,14,0x81,0x8c,0x8e):
            with self.subTest(opcode=opcode),self.assertRaises(CaptureError):
                reject_unattributed_ssap(row,[dict(data=f'0a000200{opcode:02x}03',wall_ns=15)])


if __name__=='__main__':
    unittest.main()
