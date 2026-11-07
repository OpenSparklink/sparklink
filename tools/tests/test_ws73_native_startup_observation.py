# SPDX-License-Identifier: GPL-2.0-only
"""Actual CLI validation/verdict, no USB/Native/concurrency implementation fixture."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import ws73_target as target


class StartupObservation(unittest.TestCase):
    def arguments(self, *extra):
        return target.argument_parser().parse_args([
            'run', '--prepared', '/tmp/prepared', '--output', '/tmp/observed',
            '--ports', '1-2.1.2', '--qmp-hotplug', '--native-startup-observe',
            '--firmware-evidence', 'runtime-observation', '--timeout', '180', *extra])

    def test_one_leaf_and_private_resource_receipts(self):
        args = self.arguments()
        self.assertTrue(target.startup_observation_requested(args))
        args._resource_fds = (10, 11)
        args._resource_vm_inventory = {'fixture': 'read-only host inventory'}
        self.assertTrue(target.startup_observation_requested(args))

    def test_every_other_public_option_is_rejected(self):
        base = self.arguments()
        allowed = {'command', 'prepared', 'output', 'ports', 'timeout', 'qmp_hotplug',
                   'firmware_evidence', 'native_startup_observe'}
        checked = 0
        for key, value in vars(base).items():
            if key in allowed:
                continue
            args = copy.deepcopy(base)
            replacement = not value if type(value) is bool else ('changed-option' if value != 'changed-option' else None)
            setattr(args, key, replacement)
            with self.subTest(option=key), self.assertRaisesRegex(ValueError, 'excludes all other'):
                target.startup_observation_requested(args)
            checked += 1
        self.assertGreater(checked, 80)  # Coverage guard, not a qualification count.

    def test_port_count_mode_firmware_and_original_bound(self):
        for key, values in {
            'ports': [[], ['1-2.1.1', '1-2.1.2']], 'qmp_hotplug': [False],
            'firmware_evidence': ['rom-upload', None], 'command': ['support'],
            'timeout': [0, 119.9, 240.1, float('inf'), float('nan')],
        }.items():
            for value in values:
                args = self.arguments()
                setattr(args, key, value)
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    target.startup_observation_requested(args)
        for value in [120, 240]:
            args = self.arguments(); args.timeout = value
            self.assertTrue(target.startup_observation_requested(args))

    def test_typed_enable_and_ordinary_mode_unchanged(self):
        args = self.arguments(); args.native_startup_observe = 1
        with self.assertRaises(ValueError):
            target.startup_observation_requested(args)
        args.native_startup_observe = False
        self.assertFalse(target.startup_observation_requested(args))

    def test_refusal_precedes_resource_claim(self):
        args = self.arguments('--connection-verify')
        with patch.object(target.resources, 'policy', side_effect=AssertionError('must not claim resources')):
            with self.assertRaisesRegex(ValueError, 'excludes all other'):
                target.run(args)

    def test_observation_cannot_qualify_even_with_forged_terminal_receipt(self):
        for status in ['NATIVE_STARTUP_OBSERVED_NOT_QUALIFIED', 'ENVIRONMENT_FINISHED',
                       'PASSTHROUGH_SUPPORT_PASS', 'REAL_CHANNEL_GRANT_PASS']:
            for enabled in [True, False, None, 'forged']:
                record = dict(status=status, qemu_exit=0, supervisor_exit=0,
                              physical_acceptance=True, native_startup_observation_requested=enabled)
                with self.subTest(status=status, requested=enabled):
                    self.assertEqual(target.run_exit_code(record), 1)
                    self.assertEqual(target.run_exit_code(record, supervisor_pending=True), 1)

    def test_diagnostic_flag_overrides_otherwise_accepted_terminal_shape(self):
        from test_ws73_terminal_exit import TerminalExit
        record = TerminalExit().special('early')
        # Existing independent terminal-shape fixture, not RF or a dependency
        # that always succeeds. The same unflagged record must still pass.
        self.assertEqual(target.run_exit_code(record), 0)
        for enabled in [True, False, None, 'forged']:
            with self.subTest(enabled=enabled):
                self.assertEqual(target.run_exit_code(dict(record,
                    native_startup_observation_requested=enabled)), 1)

    def test_parser_help_and_actual_shell_syntax(self):
        self.assertIn('--native-startup-observe', target.argument_parser()._subparsers._group_actions[0].choices['run'].format_help())
        subprocess.run(['sh', '-n', str(Path(target.__file__).with_name('ws73_target_init.sh'))], check=True)


if __name__ == '__main__':
    unittest.main()
