# SPDX-License-Identifier: GPL-2.0-only
"""VM selector/capture wiring; no controller, kernel or firmware execution."""
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_channel_socket import reject_unattributed_ssap


class CommandWiring(unittest.TestCase):
    def test_residual_command_and_unsolicited_response_cannot_escape_new_contract(self):
        row = dict(start_wall_ns=10, end_wall_ns=30, ssap_write_command_contract=1)
        for opcode in (1, 12, 14, 0x81, 0x8c, 0x8e):
            packet = dict(data=(b'\x0a\0\x02\0' + bytes([opcode, 0])).hex(), wall_ns=20)
            with self.assertRaises(CaptureError, msg=hex(opcode)):
                reject_unattributed_ssap(row, [packet])
        # Historical captures do not acquire a new contract by loading this tool.
        old = dict(start_wall_ns=10, end_wall_ns=30)
        for opcode in (1, 12, 0x8c):
            reject_unattributed_ssap(old, [dict(data=f'0a000200{opcode:02x}00', wall_ns=20)])
        for version in (True, 0, 2, '1', None):
            with self.assertRaises(CaptureError):
                reject_unattributed_ssap(dict(row, ssap_write_command_contract=version), [])

    def test_actual_host_and_guest_parser_expose_the_same_selector(self):
        root = Path(__file__).resolve().parents[1]
        for command in ([sys.executable, str(root/'ws73_target.py'), 'run', '--help'],
                        [sys.executable, str(root/'ws73_target_control.py'), '--help']):
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--ssap-write-command-verify', result.stdout)
        result = subprocess.run([sys.executable, str(root/'ws73_target_control.py'),
                                 '--slctl', '/bin/slctl', '--slkd-pid', '1', '--output', '/unused',
                                 '--ssap-write-command-verify'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Write Command requires', result.stderr)


if __name__ == '__main__':
    unittest.main()
