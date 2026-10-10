# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_native_root_smoke import verify_console


class NativeRootEvidence(unittest.TestCase):
    release = '7.0.0-test+'
    uuid = 'de4a8c36-18f7-48a2-a942-93b9b98d4e96'

    def evidence(self):
        return '\n'.join([
            'NATIVE_ROOT_MOUNT: /dev/nvme0n1 btrfs',
            'NATIVE_MODULE_RELEASE: ' + self.release,
            'NATIVE_MODULE_TAINT_BEFORE: 0',
            'NATIVE_MODULE_LOAD: 1', 'NATIVE_MODULE_UNLOAD: 1',
            'NATIVE_MODULE_LOAD: 2', 'NATIVE_MODULE_UNLOAD: 2',
            'NATIVE_MODULE_TAINT_AFTER: 0',
            'NATIVE_MODULE_KERNEL_LOG_BEGIN',
            '[    0.000000] Linux version ' + self.release + ' (test)',
            '[    1.000000] nvme nvme0: pci function 0000:00:01.0',
            '[    2.000000] BTRFS: device fsid ' + self.uuid + ' devid 1 /dev/nvme0n1 (259:0)',
            'NATIVE_MODULE_KERNEL_LOG_END',
            'NATIVE_MODULE_SMOKE: PASS (EMPTY_USB_KVM_ONLY)',
            '[    3.000000] reboot: Power down',
        ])

    def test_poweroff_zero_is_not_success(self):
        for text in ['reboot: Power down', 'Boot has failed.\nreboot: Power down',
                     'NATIVE_MODULE_FAILURE: sysfs\nreboot: Power down']:
            with self.assertRaises(ValueError):
                verify_console(text, self.release, self.uuid, 0)
        verify_console(self.evidence(), self.release, self.uuid, 0)
        with self.assertRaises(ValueError):
            verify_console(self.evidence(), self.release, self.uuid, 1)

    def test_pass_cannot_hide_warning_signature_or_taint(self):
        for bad in ['WARNING: suspected problem', 'module verification failed', 'NATIVE_MODULE_FAILURE: load']:
            with self.assertRaises(ValueError):
                verify_console(self.evidence() + '\n' + bad, self.release, self.uuid, 0)
        with self.assertRaises(ValueError):
            verify_console(self.evidence().replace('TAINT_AFTER: 0', 'TAINT_AFTER: 8192'),
                           self.release, self.uuid, 0)

    def test_wrong_root_or_release_and_truncated_early_log_rejected(self):
        for text in [self.evidence().replace(self.uuid, 'foreign'),
                     self.evidence().replace(self.release, 'other'),
                     self.evidence().replace('0.000000', '0.010000'),
                     self.evidence().replace('/dev/nvme0n1 btrfs', '/dev/vda ext4')]:
            with self.assertRaises(ValueError):
                verify_console(text, self.release, self.uuid, 0)

    def test_load_unload_order_and_uniqueness_required(self):
        for text in [self.evidence().replace('NATIVE_MODULE_LOAD: 1', 'NATIVE_MODULE_LOAD: 2'),
                     self.evidence().replace('NATIVE_MODULE_UNLOAD: 1', 'NATIVE_MODULE_UNLOAD: 2', 1),
                     self.evidence().replace('NATIVE_MODULE_LOAD: 1\nNATIVE_MODULE_UNLOAD: 1',
                                             'NATIVE_MODULE_UNLOAD: 1\nNATIVE_MODULE_LOAD: 1'),
                     self.evidence() + '\nNATIVE_MODULE_LOAD: 1']:
            with self.assertRaises(ValueError):
                verify_console(text, self.release, self.uuid, 0)

    def test_systemd_terminal_reset_does_not_hide_first_root_marker(self):
        prefix = '\x1b[6n\x1b[32766;32766H\x1b[!p\x1b]104\x1b\\\x1b[0m\x1b[1G\x1b[0J'
        verify_console(prefix + self.evidence(), self.release, self.uuid, 0)


if __name__ == '__main__':
    unittest.main()
