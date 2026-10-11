# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_target import config_required
from ws73_vm_native_root import OPTIONS, enabled, module_plan


class NativeVMProfile(unittest.TestCase):
    def test_partial_profile_cannot_fall_back_to_builtin_guest(self):
        self.assertFalse(enabled(SimpleNamespace()))
        for name in OPTIONS:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'together'):
                enabled(SimpleNamespace(**{name: Path('/fixture')}))
        self.assertTrue(enabled(SimpleNamespace(**{name: Path('/fixture') for name in OPTIONS})))

    def test_module_guest_cannot_use_builtin_driver_or_omit_export_modules(self):
        symbols = ['RUST', 'SPARKLINK', 'SPARKLINK_SLE', 'SPARKLINK_WS73_USB',
                   'USB_MON', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS', 'VIRTIO_PCI']
        modules = ['SPARKLINK_WS73_USB', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS']
        lines = [f"CONFIG_{name}={'m' if name in modules else 'y'}" for name in symbols]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config'
            config.write_text('\n'.join(lines))
            config_required(config, True)
            with self.assertRaisesRegex(ValueError, 'WS73_USB=y'):
                config_required(config)
            for name in modules:
                config.write_text('\n'.join(line.replace(f'{name}=m', f'{name}=y') for line in lines))
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, f'{name}=m'):
                    config_required(config, True)

    def test_only_private_staged_module_tree_is_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'staged lib/modules'):
                module_plan(Path(directory))


if __name__ == '__main__':
    unittest.main()
