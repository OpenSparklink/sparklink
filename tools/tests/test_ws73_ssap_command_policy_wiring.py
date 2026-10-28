# SPDX-License-Identifier: GPL-2.0-only
"""Actual selector entry points and static staging/dispatch wiring.

Only the host identity check is replaced in the pre-output refusal test. No
controller, daemon, socket peer, build, firmware or VM operation is executed.
Static source checks identify missing callers; they grant no runtime coverage.
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

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from ws73_capture import CaptureError
from ws73_channel_socket import reject_unattributed_ssap


def function(name, filename):
    return next(n for n in ast.parse((TOOLS / filename).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def calls(node, name):
    return sorted((n for n in ast.walk(node) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == name), key=lambda n: n.lineno)


class CommandPolicyWiring(unittest.TestCase):
    def test_real_host_and_guest_cli_expose_explicit_opt_in(self):
        for argv in ([sys.executable, str(TOOLS / 'ws73_target.py'), 'run', '--help'],
                     [sys.executable, str(TOOLS / 'ws73_target_control.py'), '--help']):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--ssap-write-command-policy-verify', result.stdout)
            self.assertIn('--ssap-write-command-verify', result.stdout)
        result = subprocess.run([sys.executable, str(TOOLS / 'ws73_target_control.py'),
            '--slctl', '/bin/slctl', '--slkd-pid', '1', '--output', '/unused',
            '--passthrough', '--connection-verify', '--channel-socket-verify',
            '--ssap-write-command-policy-verify'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertRegex(result.stderr.lower(), 'command.*policy|policy.*command')

    def test_actual_host_refuses_missing_base_before_output_or_launch(self):
        import ws73_target
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'must-not-exist'
            args = SimpleNamespace(command='run', output=output, qmp_hotplug=True,
                connection_verify=True, channel_socket_verify=True,
                ssap_write_command_policy_verify=True, ssap_write_command_verify=False)
            with patch.object(ws73_target, 'ordinary_identity'), \
                 patch.object(ws73_target.subprocess, 'Popen', side_effect=AssertionError('no process launch')), \
                 self.assertRaisesRegex(ValueError, '(?i)command.*policy|policy.*command'):
                ws73_target._run(args)
            self.assertFalse(output.exists())

    def test_init_executes_the_same_strict_boot_parser(self):
        source = (TOOLS / 'ws73_target_init.sh').read_text()
        line = next(line for line in source.splitlines() if 'command_policy_arg=$(' in line)
        code = re.search(r"-c '([^']+)'", line).group(1)
        self.assertIn('from ws73_ssap_command_policy import boot_requested', code)
        self.assertIn('|| fail command-policy-selector', line)
        base = 'ws73.ssap_write_command=1'
        selected = 'ws73.ssap_command_policy=1'
        env = dict(os.environ, PYTHONPATH=str(TOOLS))
        for tokens, expected in (([], ''), ([base], ''), ([base, selected], '--ssap-write-command-policy-verify')):
            with self.subTest(tokens=tokens):
                result = subprocess.run([sys.executable, '-c', code, *tokens], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
        for tokens in ([selected], [base, selected, selected], [base, 'ws73.ssap_command_policy'],
                       [base, 'ws73.ssap_command_policy=0'], [base, 'ws73.ssap_command_policy=2'],
                       [base, 'ws73.ssap_command_policy=']):
            with self.subTest(tokens=tokens):
                result = subprocess.run([sys.executable, '-c', code, *tokens], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_existing_positive_dispatch_precedes_policy_and_ordinary_business(self):
        execute = function('execute', 'ws73_channel_socket.py')
        base, policy = calls(execute, 'command_execute'), calls(execute, 'command_policy_execute')
        self.assertEqual(len(base), 1)
        self.assertEqual(len(policy), 1)
        self.assertLess(base[0].lineno, policy[0].lineno)
        ordinary = calls(execute, 'run_applications')
        self.assertTrue(any(n.lineno > policy[0].lineno for n in ordinary))
        corroborate = function('corroborate', 'ws73_channel_socket.py')
        base = calls(corroborate, 'command_corroborate')
        policy = calls(corroborate, 'command_policy_corroborate')
        self.assertEqual(len(base), 1)
        self.assertEqual(len(policy), 1)
        self.assertLess(base[0].lineno, policy[0].lineno)
        self.assertEqual([ast.unparse(arg) for arg in policy[0].args], ['row', 'value_matched', 'sdus'])

    def test_fresh_and_retained_carriers_stage_policy_and_all_consumers_validate(self):
        name = 'ws73_ssap_command_policy.py'
        for function_name in ('prepare_from_carrier', 'prepare_locked'):
            node = function(function_name, 'ws73_target.py')
            matches = [n for n in ast.walk(node) if isinstance(n, ast.Constant) and n.value == name]
            self.assertEqual(len(matches), 1 if function_name == 'prepare_from_carrier' else 2)
        host = function('_run', 'ws73_target.py')
        for expected in ('command_policy_requested', 'command_policy_inputs', 'command_policy_rows', 'command_policy_summary'):
            self.assertEqual(len(calls(host, expected)), 1, expected)
        self.assertEqual(len(calls(function('run_exit_code', 'ws73_target.py'), 'valid_command_policy_manifest')), 1)
        self.assertEqual(len(calls(function('verify_passthrough', 'ws73_target_guest.py'), 'policy_rows')), 1)

    def test_extra_command_error_or_write_reply_remains_rejected(self):
        row = dict(start_wall_ns=10, end_wall_ns=20, ssap_write_command_contract=1,
                   ssap_command_policy_required=True, ssap_command_policy_contract=1)
        for opcode in (1, 12, 14, 0x81, 0x8c, 0x8e):
            with self.subTest(opcode=opcode), self.assertRaises(CaptureError):
                reject_unattributed_ssap(row, [dict(data=f'0a000200{opcode:02x}03', wall_ns=15)])


if __name__ == '__main__':
    unittest.main()
