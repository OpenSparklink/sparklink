# SPDX-License-Identifier: GPL-2.0-only
"""Filesystem safety tests with tiny synthetic payloads; not boot evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import ws73_native_deploy as deploy
from ws73_native_boot_bundle import boot_options, staged_modules
from ws73_native_root_smoke import digest, save


class NativeDeployment(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.bundle, self.root = base / 'bundle', base / 'root'
        self.bundle.mkdir(); self.root.mkdir()
        self.release = '7.0.0-opensparklink-native-lab-test+'
        self.uuid = '4d528bcc-0c26-4bfe-9253-5077505180fe'
        self.module_unit = 'usr/lib/modules/' + self.release
        payload = self.bundle / 'payload'
        names = ['boot/vmlinuz-' + self.release, 'boot/initramfs-' + self.release + '.img',
                 'boot/config-' + self.release, 'boot/System.map-' + self.release,
                 self.module_unit + '/kernel/drivers/sparklink/sparklink_ws73_usb.ko',
                 self.module_unit + '/modules.order']
        files = {}
        for name in names:
            path = payload / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic filesystem test: ' + name)
            files[name] = {'sha256': digest(path), 'size': path.stat().st_size}
        entry_name = 'opensparklink-native-' + self.release + '.conf'
        entry = self.bundle / entry_name
        entry.write_text('title OpenSparkLink native lab (controlled WS73 load)\nversion '
                         + self.release + '\nlinux /vmlinuz-' + self.release
                         + '\ninitrd /initramfs-' + self.release + '.img\noptions '
                         + boot_options(self.uuid, 'subvol=root') + '\n')
        self.entry_unit = 'boot/loader/entries/' + entry_name
        save(self.bundle / 'deployment-plan.json', {'synthetic': True})
        (self.bundle / 'SHA256SUMS').write_text('synthetic filesystem test\n')
        self.record = {'status': 'PRIVATE_NATIVE_BOOT_PAYLOAD_VERIFIED', 'release': self.release,
                       'files': files, 'root_uuid': self.uuid, 'rootflags': 'subvol=root',
                       'candidate_entry': {'path': entry_name, 'destination': self.entry_unit,
                                           'sha256': digest(entry)},
                       'deployment_plan_sha256': digest(self.bundle / 'deployment-plan.json'),
                       'checksums_sha256': digest(self.bundle / 'SHA256SUMS')}
        save(self.bundle / 'manifest.json', self.record)
        for name in ['usr/lib/modules', 'boot/loader/entries', 'boot/grub2', 'var/lib']:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.originals = {'boot/vmlinuz-original': b'distribution kernel',
                          'boot/loader/entries/original.conf': b'distribution entry',
                          'boot/grub2/grubenv': b'saved_entry=original'}
        for name, data in self.originals.items():
            (self.root / name).write_bytes(data)

    def assert_originals(self):
        for name, data in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_install_rollback_repeat_preserves_distribution_and_history(self):
        state = deploy.install(self.bundle, self.root)
        self.assertEqual(state['status'], 'INSTALLED')
        self.assertFalse(state['host_installation'])
        self.assertTrue((self.root / self.entry_unit).is_file())
        self.assert_originals()
        self.assertEqual(deploy.rollback(self.bundle, self.root)['status'], 'ROLLED_BACK')
        self.assertFalse((self.root / self.module_unit).exists())
        self.assertFalse((self.root / self.entry_unit).exists())
        deploy.rollback(self.bundle, self.root)
        deploy.install(self.bundle, self.root)
        self.assertEqual(len(list((self.root / 'var/lib/opensparklink/native-lab').glob('*.completed-*.json'))), 1)
        deploy.rollback(self.bundle, self.root)
        self.assert_originals()

    def test_existing_release_is_never_overwritten(self):
        foreign = self.root / ('boot/vmlinuz-' + self.release)
        foreign.write_bytes(b'foreign')
        with self.assertRaises(ValueError): deploy.install(self.bundle, self.root)
        self.assertEqual(foreign.read_bytes(), b'foreign')
        self.assertFalse((self.root / self.module_unit).exists())
        self.assert_originals()

    def test_symlink_parent_and_traversal_are_rejected(self):
        parent = self.root / 'usr/lib/modules'; parent.rmdir()
        outside = Path(self.temporary.name) / 'outside'; outside.mkdir()
        parent.symlink_to(outside)
        with self.assertRaises(ValueError): deploy.install(self.bundle, self.root)
        self.assertEqual(list(outside.iterdir()), [])
        with self.assertRaises(ValueError): deploy.safe_path(self.root, '../outside')

    def test_corrupt_payload_cannot_be_installed(self):
        (self.bundle / 'payload' / ('boot/vmlinuz-' + self.release)).write_text('changed')
        with self.assertRaises(ValueError): deploy.install(self.bundle, self.root)
        self.assertFalse((self.root / self.module_unit).exists())
        self.assert_originals()

    def test_rollback_refuses_unknown_module_before_removing_entry(self):
        deploy.install(self.bundle, self.root)
        foreign = self.root / self.module_unit / 'foreign-data'; foreign.write_text('keep')
        with self.assertRaises(ValueError): deploy.rollback(self.bundle, self.root)
        self.assertEqual(foreign.read_text(), 'keep')
        self.assertTrue((self.root / self.entry_unit).exists())
        self.assert_originals()

    def test_rollback_refuses_changed_entry_before_removing_modules(self):
        deploy.install(self.bundle, self.root)
        (self.root / self.entry_unit).write_text('modified entry')
        with self.assertRaises(ValueError): deploy.rollback(self.bundle, self.root)
        self.assertTrue((self.root / self.module_unit).exists())
        self.assert_originals()

    def test_mid_install_failure_rolls_back_only_published_units(self):
        original = deploy.publish; calls = []
        def interrupted(source, destination):
            calls.append(destination)
            if len(calls) == 3: raise OSError('injected disk failure')
            original(source, destination)
        with patch.object(deploy, 'publish', side_effect=interrupted):
            with self.assertRaises(OSError): deploy.install(self.bundle, self.root)
        self.assertFalse((self.root / self.module_unit).exists())
        self.assertFalse((self.root / self.entry_unit).exists())
        self.assert_originals()
        journal = self.root / 'var/lib/opensparklink/native-lab' / (self.release + '.json')
        self.assertEqual(json.loads(journal.read_text())['status'], 'INSTALL_FAILED_ROLLED_BACK')

    def test_destination_race_does_not_overwrite_or_delete_foreign_file(self):
        original = deploy.publish; calls = []
        def race(source, destination):
            calls.append(destination)
            if len(calls) == 2: destination.write_bytes(b'foreign concurrent install')
            original(source, destination)
        with patch.object(deploy, 'publish', side_effect=race):
            with self.assertRaises(FileExistsError): deploy.install(self.bundle, self.root)
        self.assertEqual(calls[1].read_bytes(), b'foreign concurrent install')
        self.assertFalse((self.root / self.module_unit).exists())
        self.assert_originals()


class BundleInputs(unittest.TestCase):
    def test_root_options_cannot_inject_another_boot_command(self):
        for root_uuid, flags in [('../outside', 'subvol=root'),
                                 ('4d528bcc-0c26-4bfe-9253-5077505180fe', 'subvol=root\ninit=/bin/sh'),
                                 ('4d528bcc-0c26-4bfe-9253-5077505180fe', 'subvol=../root')]:
            with self.assertRaises(ValueError): boot_options(root_uuid, flags)

    def test_staging_rejects_extra_keys_missing_modules_and_unexpected_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'kernel').mkdir(); (root / 'kernel/test.ko').write_bytes(b'test')
            (root / 'modules.order').write_text('kernel/test.ko\n')
            for name in ['modules.dep', 'modules.dep.bin', 'modules.alias', 'modules.alias.bin',
                         'modules.builtin', 'modules.builtin.modinfo']:
                (root / name).write_bytes(b'test')
            (root / 'build').symlink_to('/unrelated/build')
            files, count = staged_modules(root)
            self.assertEqual(count, 1); self.assertNotIn(Path('build'), files)
            key = root / 'private.pem'; key.write_bytes(b'private test key')
            with self.assertRaises(ValueError): staged_modules(root)
            key.unlink()
            (root / 'modules.alias').unlink(); (root / 'modules.alias').symlink_to(root / 'modules.dep')
            with self.assertRaises(ValueError): staged_modules(root)
            (root / 'modules.alias').unlink(); (root / 'modules.alias').write_bytes(b'test')
            (root / 'kernel/test.ko').unlink()
            with self.assertRaises(ValueError): staged_modules(root)


if __name__ == '__main__':
    unittest.main()
