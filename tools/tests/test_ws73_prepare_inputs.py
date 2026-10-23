# SPDX-License-Identifier: GPL-2.0-only
"""Actual prepare/CLI/file guards with explicit synthetic carrier/packer fixtures.

No kernel, ELF execution, USB, firmware execution or compiled identity attestation.
The successful pack fixture is paired with failure/mutation cases; real mkfs and
boot are separate VM gates. No Native ioctl or protocol dependency is mocked.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_target as target
import ws73_lab_resources as resources
from ws73_north_star import file_record
from test_ws73_mixed_inputs import prepare_fixture


def fixture(base):
    source, selections, package, allocation = prepare_fixture(base)
    root = source / 'root'
    (root / 'init').write_text('#!/bin/sh\nexit 0\n'); (root / 'init').chmod(0o755)
    tools = root / 'usr/share/sparklink/tools'; tools.mkdir(parents=True)
    (tools / 'ws73_firmware_profile.py').write_text('# retained old carrier helper\n')
    for name, relative in target.native_vm.STAGED_PYTHON_CLIENTS.items():
        (tools / name).write_bytes((target.HERE / relative).read_bytes())
    (root / 'bin').mkdir(); (root / 'bin/busybox').write_bytes(b'fixture-not-an-ELF')
    (root / 'bin/sh').symlink_to('busybox')
    for name in ('bzImage', 'initramfs.cpio.gz', 'root.btrfs'):
        (source / name).write_bytes(b'explicit-synthetic-artifact-' + name.encode())
    (source / 'kernel.config').write_text('\n'.join('CONFIG_' + n + '=' + ('m' if n in [
        'SPARKLINK_WS73_USB', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS'] else 'y')
        for n in ['RUST', 'SPARKLINK', 'SPARKLINK_WS73_USB', 'USB_MON', 'NET_9P',
                  'NET_9P_VIRTIO', '9P_FS', 'VIRTIO_PCI']) + '\n')
    data = source / 'qemu-data'; data.mkdir(); (data / 'bios.bin').write_bytes(b'fixture-BIOS')
    qemu = base / 'qemu'; qemu.write_bytes(b'fixture-QEMU-never-executed')
    rust = base / 'compiled-source.rs'; rust.write_text('// fixture never compiled\n')
    package.update(status='PREPARED', physical_acceptance=False,
        native_vm=dict(root_uuid='fixture-root', userspace_head='2'*40, kernel_head='3'*40,
                       qemu_data=[file_record(data / 'bios.bin')]),
        compiled_userspace_identity='1'*40, userspace_head='2'*40,
        userspace_sources=[file_record(rust)], qemu=file_record(qemu),
        guest_files=[file_record(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()],
        artifacts=[file_record(source / n) for n in ['bzImage', 'kernel.config', 'initramfs.cpio.gz', 'root.btrfs']])
    (source / 'manifest.json').write_text(json.dumps(package))
    plan = base / 'devices.json'; plan.write_text(json.dumps(dict(version=1, entries=selections)))
    args = SimpleNamespace(from_prepared=source, device_inputs=plan, output=base / 'new')
    return source, selections, package, allocation, args


def pack_fixture(args, manifest, root):
    (args.output / 'root.btrfs').write_bytes(b'fixture-packer-no-kernel-or-mkfs')


class PrepareInputs(unittest.TestCase):
    def run_prepare(self, args, allocation, pack=pack_fixture):
        with patch.object(resources, 'policy', return_value=allocation), \
             patch.object(target, 'ordinary_identity'), \
             patch.object(target.native_vm, 'pack', side_effect=pack), \
             contextlib.redirect_stdout(io.StringIO()):
            return target.prepare_from_carrier(args)

    def test_shared_provisioner_preserves_frozen_artifacts_and_stages_current_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, selections, old, allocation, args = fixture(Path(tmp))
            before = target.carrier_root_files(source / 'root', old['guest_files'])
            self.assertEqual(self.run_prepare(args, allocation), 0)
            new = target.prepared(args.output)
            self.assertEqual(new['compiled_userspace_identity'], '1'*40)
            self.assertFalse(new['new_production_compilation'])
            self.assertEqual(new['native_vm']['parent_carrier_userspace_head'], '2'*40)
            self.assertNotIn('explicit_firmware', new); self.assertNotIn('board_configuration', new)
            self.assertEqual(new['device_inputs'], old['device_inputs'])
            self.assertEqual(target.carrier_root_files(source / 'root', old['guest_files']), before)
            for name in ('bzImage', 'kernel.config', 'initramfs.cpio.gz'):
                self.assertEqual((source / name).read_bytes(), (args.output / name).read_bytes())
            self.assertEqual((args.output / 'root/usr/share/sparklink/tools/ws73_firmware_profile.py').read_bytes(),
                             (target.HERE / 'ws73_firmware_profile.py').read_bytes())
            self.assertEqual((args.output / 'root/init').read_bytes(),
                             (target.HERE / 'ws73_target_init.sh').read_bytes())
            self.assertEqual((args.output / 'root/init').stat().st_mode & 0o777, 0o755)
            self.assertIn(file_record(target.HERE / 'ws73_target_init.sh'), new['inputs'])
            ports = [s['host_port'] for s in selections]
            self.assertEqual(resources.check_firmware(new, ports, args.output, allocation)['version'], 2)
            self.assertEqual(resources.check_board_configuration(new, ports, args.output, allocation)['version'], 2)
            self.assertEqual((args.output / 'root/bin/sh').readlink(), Path('busybox'))

    def test_global_and_additional_staging_options_are_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, allocation, args = fixture(Path(tmp))
            for field in ('board_model', 'firmware_dir', 'kernel_build', 'tcpdump', 'python', 'native_service_bundle',
                          'native_channel_fd_probe', 'controller_directory_clients',
                          'native_runtime_only'):
                bad = copy.copy(args); setattr(bad, field, 'U')
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'refuses'):
                    self.run_prepare(bad, allocation)
                self.assertFalse(args.output.exists())

    def test_retained_config_rejection_uses_real_process_and_does_not_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, _, package, allocation, args = fixture(Path(tmp))
            root = source / 'root'
            relative = 'usr/libexec/opensparklink/native-lab/000000000001/slkd'
            binary = root / relative; binary.parent.mkdir(parents=True)
            # Explicit rejecting executable, never a successful daemon/Native stub.
            shutil.copy2('/bin/false', binary)
            (root / 'bin/slkd').symlink_to('/' + relative)
            package['guest_files'] = [file_record(p) for p in sorted(root.rglob('*'))
                                      if p.is_file() and not p.is_symlink()]
            (source / 'manifest.json').write_text(json.dumps(package))
            before = target.carrier_root_files(root, package['guest_files'])
            config = Path(tmp) / 'explicit.conf'; config.write_text('[ssap]\nchannel_security = 2\n')
            args.native_discovery_config = config
            def forbidden_pack(*unused):
                self.fail('rejected config must never reach formatter')
            self.assertEqual(self.run_prepare(args, allocation, forbidden_pack), 1)
            failed = json.loads((args.output / 'manifest.json').read_text())
            self.assertEqual(failed['status'], 'FAIL')
            self.assertIn('staged slkd rejected', failed['error'])
            self.assertFalse((args.output / 'root.btrfs').exists())
            self.assertEqual(target.carrier_root_files(root, package['guest_files']), before)

    def test_wrong_plan_or_missing_plan_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, allocation, args = fixture(Path(tmp))
            original = json.loads(args.device_inputs.read_text())
            cases = [dict(original, version=True), dict(original, unexpected=True), dict(version=1, entries={})]
            bad = copy.deepcopy(original); bad['entries'][1]['host_port'] = '1-2.1.3'; cases.append(bad)
            bad = copy.deepcopy(original); bad['entries'][1]['model'] = 'U'; cases.append(bad)
            for value in cases:
                args.device_inputs.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                    self.run_prepare(args, allocation)
                self.assertFalse(args.output.exists())
            args.device_inputs = None
            with self.assertRaises(ValueError): self.run_prepare(args, allocation)

    def test_stale_unlisted_or_symlink_carrier_file_refuses_before_output(self):
        for case in ('changed', 'extra', 'symlink', 'qemu-extra', 'no-compiled-identity', 'runtime-only'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                source, _, package, allocation, args = fixture(Path(tmp))
                path = source / 'root/init'
                if case == 'changed': path.write_text('changed\n')
                elif case == 'extra': (source / 'root/unlisted').write_text('extra')
                elif case == 'symlink': path.unlink(); path.symlink_to('/etc/passwd')
                elif case == 'qemu-extra': (source / 'qemu-data/extra').write_bytes(b'unlisted')
                else:
                    if case == 'runtime-only': package['native_vm']['runtime_only'] = True
                    else: package.pop('compiled_userspace_identity')
                    (source / 'manifest.json').write_text(json.dumps(package))
                with self.assertRaises(ValueError): self.run_prepare(args, allocation)
                self.assertFalse(args.output.exists())

    def test_pack_failure_and_mutations_never_leave_prepared_verdict(self):
        for case in ('pack-error', 'carrier-change', 'plan-change', 'firmware-change', 'staged-root-change'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                source, selections, _, allocation, args = fixture(Path(tmp))
                def pack(a, m, r):
                    if case == 'pack-error': raise OSError('fixture formatter failure')
                    pack_fixture(a, m, r)
                    if case == 'carrier-change': (source / 'root/init').write_text('changed')
                    elif case == 'plan-change': args.device_inputs.write_text('{}')
                    elif case == 'staged-root-change': (r / 'init').write_text('changed')
                    else: (Path(selections[1]['firmware_dir']) / 'ws73.bin').write_bytes(b'changed')
                self.assertEqual(self.run_prepare(args, allocation, pack), 1)
                failed = json.loads((args.output / 'manifest.json').read_text())
                self.assertEqual(failed['status'], 'FAIL')
                with self.assertRaises(ValueError): target.prepared(args.output)

    def test_unknown_or_changed_external_consumer_refuses_instead_of_using_verifier(self):
        for name in ('private-helper.py', 'ws73-application-client.py'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                source, _, package, allocation, args = fixture(Path(tmp))
                (source / 'root/usr/share/sparklink/tools' / name).write_text('# changed client\n')
                package['guest_files'] = [file_record(p) for p in sorted((source / 'root').rglob('*'))
                                         if p.is_file() and not p.is_symlink()]
                (source / 'manifest.json').write_text(json.dumps(package))
                self.assertEqual(self.run_prepare(args, allocation), 1)
                failed = json.loads((args.output / 'manifest.json').read_text())
                self.assertEqual(failed['status'], 'FAIL')

    def test_cli_routes_prepare_and_rejects_retired_flag(self):
        with patch.object(sys, 'argv', ['ws73_target.py', 'prepare', '--from-prepared', '/carrier',
                                     '--device-inputs', '/explicit.json', '--output', '/new']), \
             patch.object(target, 'prepare', return_value=7) as run:
            self.assertEqual(target.main(), 7)
            self.assertEqual(run.call_args.args[0].from_prepared, Path('/carrier'))
        with patch.object(sys, 'argv', ['ws73_target.py', 'prepare', '--output', '/new', '--native-runtime-only']), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            target.main()
        self.assertEqual(error.exception.code, 2)
