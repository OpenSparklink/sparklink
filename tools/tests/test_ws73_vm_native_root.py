# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).parents[1]))
from ws73_target import config_required
from ws73_vm_native_root import OPTIONS, enabled, module_plan, stage_discovery_config, check_discovery_config_gate, remove_boot_images, check_runtime_only, stage_runtime_libraries
from ws73_north_star import file_record


class NativeVMProfile(unittest.TestCase):
    def test_runtime_major_names_share_canonical_identity_and_validate_before_copy(self):
        import shutil
        from install_layout import LIBRARIES
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'root';root.mkdir();sources = Path(tmp)/'source';sources.mkdir()
            libraries = []
            for name in LIBRARIES:
                path = sources/name;path.write_bytes(b'\x7fELF-explicit-layout-fixture');libraries.append(path)
            def readelf(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, stdout='(SONAME) ['+LIBRARIES[Path(command[-1]).name]+']', stderr='')
            def copy(source, target, _):
                target.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(source, target)
            with patch('ws73_vm_native_root.subprocess.run', side_effect=readelf):
                rows=stage_runtime_libraries(root,libraries,copy)
            self.assertEqual(len(rows),2)
            for soname in LIBRARIES.values():
                target=root/'usr/lib'/soname;alias=target.with_name(soname.rsplit('.',1)[0])
                self.assertTrue(target.is_file() and not target.is_symlink());self.assertTrue(alias.is_symlink());self.assertEqual(alias.resolve(),target)

    def test_runtime_wrong_second_soname_or_preexisting_alias_is_failure_atomic(self):
        from install_layout import LIBRARIES
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';(root/'usr/lib').mkdir(parents=True);sources=Path(tmp)/'source';sources.mkdir()
            libraries=[]
            for name in LIBRARIES:
                path=sources/name;path.write_bytes(b'\x7fELF-layout-fixture');libraries.append(path)
            calls=[]
            def readelf(command,**kwargs):
                name=Path(command[-1]).name;soname=LIBRARIES[name] if name=='liblibsparklink.so' else 'wrong.so.0'
                return subprocess.CompletedProcess(command,0,stdout='(SONAME) ['+soname+']',stderr='')
            with patch('ws73_vm_native_root.subprocess.run',side_effect=readelf),self.assertRaisesRegex(ValueError,'SONAME'):
                stage_runtime_libraries(root,libraries,lambda *args:calls.append(args))
            self.assertEqual(calls,[]);self.assertEqual(list((root/'usr/lib').iterdir()),[])
            (root/'usr/lib/libsparklink.so').symlink_to('/outside-test-root')
            with patch('ws73_vm_native_root.subprocess.run',side_effect=readelf),self.assertRaisesRegex(ValueError,'preexisting'):
                stage_runtime_libraries(root,libraries,lambda *args:calls.append(args))
            self.assertEqual(calls,[])

    def test_runtime_only_profile_keeps_board_bytes_and_omits_both_boot_search_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ['lib/firmware/sparklink/ws73', 'usr/lib/firmware/sparklink/ws73']:
                p = root / folder
                p.mkdir(parents=True)
                for name in ['ws73.bin', 'wifi_cali.bin', 'btc_cali.bin', 'bsle_custom.bin', 'pm_config.bin']:
                    (p / name).write_bytes(b'explicit-fixture')
            rows = remove_boot_images(root)
            self.assertEqual(len(rows), 6)
            self.assertFalse(any((root / row['path'].lstrip('/')).exists() for row in rows))
            self.assertEqual((root / 'lib/firmware/sparklink/ws73/bsle_custom.bin').read_bytes(), b'explicit-fixture')
            package = dict(native_vm=dict(runtime_only=True))
            check_runtime_only(package, {'port': dict(interfaces=[dict(endpoints=5)])}, ['port'])
            for interfaces in [[], [dict(endpoints=2)], [dict(endpoints=5), dict(endpoints=5)]]:
                with self.subTest(interfaces=interfaces), self.assertRaises(ValueError):
                    check_runtime_only(package, {'port': dict(interfaces=interfaces)}, ['port'])
            with self.assertRaises(ValueError):
                enabled(SimpleNamespace(native_runtime_only=True))

    def test_runtime_only_missing_image_is_failure_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ['lib/firmware/sparklink/ws73', 'usr/lib/firmware/sparklink/ws73']:
                p = root / folder
                p.mkdir(parents=True)
                for name in ['ws73.bin', 'wifi_cali.bin', 'btc_cali.bin']:
                    (p / name).write_bytes(b'fixture')
            (root / 'usr/lib/firmware/sparklink/ws73/btc_cali.bin').unlink()
            with self.assertRaises(ValueError):
                remove_boot_images(root)
            self.assertEqual(len(list(root.rglob('*.bin'))), 5)

    def test_partial_profile_cannot_fall_back_to_builtin_guest(self):
        self.assertFalse(enabled(SimpleNamespace()))
        for name in OPTIONS:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'together'):
                enabled(SimpleNamespace(**{name: Path('/fixture')}))
        self.assertTrue(enabled(SimpleNamespace(**{name: Path('/fixture') for name in OPTIONS})))
        with self.assertRaisesRegex(ValueError, 'complete native VM'):
            enabled(SimpleNamespace(native_discovery_config=Path('/private.conf')))

    def test_module_guest_cannot_use_builtin_driver_or_omit_export_modules(self):
        symbols = ['RUST', 'SPARKLINK', 'SPARKLINK_WS73_USB',
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

    def test_exact_staged_daemon_checks_the_frozen_guest_config(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / 'private.conf'
            config.write_text('[ws73.defaults]\ntx_power_dbm=0\n')
            daemon = base / 'slkd'
            daemon.write_bytes(b'fixture executable')
            manifest = {'inputs': []}
            result = subprocess.CompletedProcess([], 0, 'Ws73DefaultPolicy: version=3 adv_slots=1200..1200 tx_power_dbm=0 scan_slots=1600/800\n', '')
            with patch('ws73_vm_native_root.subprocess.run', return_value=result) as run:
                stage_discovery_config(config, daemon, base / 'root', manifest)
            target = base / 'root/etc/sparklink/main.conf'
            run.assert_called_once_with([str(daemon), '--check-config', '--dump-ws73-policies', '--config', str(target)],
                                        capture_output=True, text=True, timeout=15)
            self.assertEqual(target.read_bytes(), config.read_bytes())
            self.assertEqual(manifest['inputs'], [file_record(config)])
            record = manifest['discovery_config']
            self.assertEqual(record['validator'], file_record(daemon))
            self.assertEqual(record['guest_sha256'], file_record(target)['sha256'])
            self.assertFalse(record['firmware_support_acceptance'])
            self.assertFalse(record['custom_policy_rf_acceptance'])
            self.assertEqual((base / 'root/expected-discovery-config-sha256').read_text().strip(),
                             record['guest_sha256'])

    def test_rejected_or_mutated_config_is_not_published_as_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / 'private.conf'
            config.write_text('valid input')
            daemon = base / 'slkd'
            daemon.write_bytes(b'fixture executable')
            for case in ('reject', 'mutate-source', 'mutate-target', 'timeout'):
                config.write_text('valid input')
                manifest = {'inputs': []}
                def validate(command, **kwargs):
                    if case == 'timeout':
                        raise subprocess.TimeoutExpired(command, 15)
                    if case == 'mutate-source':
                        config.write_text('changed input')
                    if case == 'mutate-target':
                        Path(command[-1]).write_text('changed snapshot')
                    return subprocess.CompletedProcess(command, 1 if case == 'reject' else 0,
                                                       '', 'invalid policy')
                with self.subTest(case=case), patch('ws73_vm_native_root.subprocess.run', side_effect=validate):
                    with self.assertRaises((ValueError, subprocess.TimeoutExpired)):
                        stage_discovery_config(config, daemon, base / 'root', manifest)
                self.assertNotIn('discovery_config', manifest)
                self.assertEqual(manifest['inputs'], [])
            config.write_bytes(bytes(65537))
            with patch('ws73_vm_native_root.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, '64 KiB'):
                    stage_discovery_config(config, daemon, base / 'root', {'inputs': []})
                run.assert_not_called()

    def test_custom_policy_does_not_enter_default_parallel_or_injection_gates(self):
        package = {'discovery_config': {}}
        check_discovery_config_gate({}, SimpleNamespace(command='support'))
        check_discovery_config_gate(package, SimpleNamespace(command='run', qmp_hotplug=True))
        with self.assertRaisesRegex(ValueError, 'frozen policy'):
            check_discovery_config_gate(package, SimpleNamespace(command='run', parallel_pairs=True))
        check_discovery_config_gate({'discovery_config': {}, 'policy_expectation': {'data': {'custom_configuration': True}}}, SimpleNamespace(command='run', parallel_pairs=True))
        for flags in ({'command': 'support'}, {'command': 'run'},

                      {'command': 'run', 'qmp_hotplug': True, 'daemon_cancel_remove': True},
                      {'command': 'run', 'qmp_hotplug': True, 'managed_partial_case': 'dup'}):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'separate QMP or parallel'):
                check_discovery_config_gate(package, SimpleNamespace(**flags))


if __name__ == '__main__':
    unittest.main()
