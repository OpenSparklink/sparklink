# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual runner admission before launch, not a VM/RF receipt."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_target import validate_channel_death_mode

class Admission(unittest.TestCase):
    def test_native_client_and_separate_mode_required(self):
        package=dict(native_vm={},native_channel_fd_probe={})
        base=dict(command='run',channel_daemon_crash=True,channel_daemon_index=0)
        validate_channel_death_mode(SimpleNamespace(**base),package)
        for key,value in [('command','support'),('qmp_hotplug',True),('new_unknown_test',True),('managed_connected_case','release'),('daemon_hold_case','cancel'),('channel_daemon_index',2)]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_channel_death_mode(SimpleNamespace(**(base|{key:value})),package)
        for missing in ['native_vm','native_channel_fd_probe']:
            with self.subTest(missing=missing),self.assertRaises(ValueError):validate_channel_death_mode(SimpleNamespace(**base),{k:v for k,v in package.items() if k!=missing})
