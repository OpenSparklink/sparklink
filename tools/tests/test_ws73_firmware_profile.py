# SPDX-License-Identifier: GPL-2.0-only
"""Actual file provisioner/encoder with fixture bytes;not firmware or USB proof."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_firmware_profile as profile


def inputs(tag=b'fixture'):
    result = {}
    for name in profile.NAMES:
        payload = tag + name.encode()
        result[name] = hashlib.sha256(payload).hexdigest().encode() + payload
    result.update({'bsle_custom.bin': b'c' * 140, 'pm_config.bin': b'\x01\x00\x00\x00'})
    return result


def prepare(root, entries=None):
    return profile.stage(root, entries or {'1': ('U', inputs()), '2': ('E', inputs(b'E'))})


class FirmwareProfile(unittest.TestCase):
    def test_golden_wire_layout_and_full_file_hashes(self):
        files = {n: profile.record(v) for n, v in inputs().items()}
        raw = profile.encode('E', files)
        self.assertEqual(len(raw), 172)
        self.assertEqual(raw[:12], b'WS73P001\x02\x00\x00\x00')
        self.assertEqual(raw[12:44], hashlib.sha256(inputs()['ws73.bin']).digest())
        self.assertEqual(raw[-32:], hashlib.sha256(inputs()['pm_config.bin']).digest())
        self.assertEqual(profile.encode('U', files)[8], 0)
        for model in ['S', 'E/UART', '', None]:
            with self.assertRaises(ValueError):
                profile.encode(model, files)
        for name in profile.FILES:
            for changes in [{'sha256': '0'*64}, {'sha256': 'F'*64}, {'bytes': True}, {'bytes': 0}]:
                bad = copy.deepcopy(files);bad[name].update(changes)
                with self.assertRaises(ValueError):
                    profile.encode('E', bad)

    def test_paths_use_explicit_controller_and_usb2_route(self):
        self.assertEqual(str(profile.directory('0000:c5:00.3', '2.1.1')),
                         'sparklink/ws73/by-path/0000:c5:00.3-usb2-2.1.1')
        for controller, route in [('a/b','1'), ('x'*64,'1'), ('','1'), ('pci','01'),
                                  ('pci','1..2'), ('pci','256'), ('pci','1.0'), ('pci','1.'),
                                  ('pci','../1'), ('pci','255.255.255.255.1')]:
            with self.subTest(controller=controller, route=route), self.assertRaises(ValueError):
                profile.directory(controller, route)

    def test_distinct_models_and_each_input_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);plan = prepare(root)
            self.assertEqual(profile.verify(root, plan), plan)
            first = root/'lib/firmware'/plan['entries']['1']['directory']/'profile.bin'
            second = root/'lib/firmware'/plan['entries']['2']['directory']/'profile.bin'
            self.assertNotEqual(first.read_bytes(), second.read_bytes())
            before = first.read_bytes();second.write_bytes(before)
            with self.assertRaises(ValueError):
                profile.verify(root, plan)
            self.assertEqual(first.read_bytes(), before)

    def test_validation_precedes_filesystem_publication(self):
        for name in profile.FILES:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp);bad = inputs();bad[name] += b'wrong'
                with self.assertRaises(ValueError):
                    prepare(root, {'1': ('U', inputs()), '2': ('E', bad)})
                self.assertEqual(list(root.iterdir()), [])

    def test_write_failure_does_not_publish_partial_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(Path, 'write_bytes', side_effect=OSError('injected full disk')):
                with self.assertRaises(OSError):
                    prepare(root)
            self.assertFalse((root/profile.PLAN).exists())
            self.assertFalse(any(root.rglob('profile.bin')))
            self.assertFalse(any(root.rglob('.profile-*')))

    def test_refuses_overwrite_symlink_and_changed_exported_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);plan = prepare(root)
            with self.assertRaises(ValueError):
                prepare(root)
            path = root/'lib/firmware'/plan['entries']['1']['directory']/'pm_config.bin'
            original = path.read_bytes();other = root/'other';other.write_bytes(original)
            path.unlink();path.symlink_to(other)
            with self.assertRaises(ValueError):
                profile.verify(root, plan)
            path.unlink();path.write_bytes(original)
            changed = copy.deepcopy(plan);changed['entries']['1']['model'] = 'E'
            (root/profile.PLAN).write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                profile.verify(root, plan)

    def test_runtime_only_strips_only_images_and_cannot_prove_cold_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);plan = prepare(root);paths = profile.boot_paths(root, plan)
            self.assertEqual(len(paths), 6)
            for p in paths:
                p.unlink()
            self.assertEqual(profile.verify(root, plan, boot=False), plan)
            with self.assertRaises(ValueError):
                profile.verify(root, plan)
            for entry in plan['entries'].values():
                base = root/'lib/firmware'/entry['directory']
                self.assertEqual((base/'bsle_custom.bin').stat().st_size, 140)
                self.assertEqual((base/'pm_config.bin').stat().st_size, 4)

    def test_driver_observation_does_not_turn_selection_into_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);plan = prepare(root);entry = plan['entries']['2']
            raw = f"source=os-input directory={entry['directory']} expected_model=WS73E bus=USB filesystem_checked=18 execution_attested=0"
            observed = profile.observed(raw, plan, '2', 'E')
            self.assertFalse(observed['execution_attested'])
            for bad in [raw.replace('WS73E','WS73U'),raw.replace('18','1f'),raw.replace('attested=0','attested=1')]:
                with self.assertRaises(ValueError):
                    profile.observed(bad, plan, '2', 'E')
            cmd = root/'cmd';cmd.write_text('ws73.firmware_profiles=1')
            with self.assertRaises(ValueError):
                profile.guest_observation(root, 'E', '2', root/'absent', cmd)
            (root/'firmware_profile').write_text(raw)
            self.assertEqual(profile.guest_observation(root, 'E', '2', root/profile.PLAN, cmd), observed)

    def test_bundle_inputs_must_match_before_global_paths_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);blobs = inputs()
            for name, blob in blobs.items():
                path = root/profile.BASE/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(blob)
                path = root/profile.INPUTS/'E'/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(blob)
            service = dict(firmware_input_contract_version=1, firmware_inputs=dict(model='E',
                           directory=str(profile.INPUTS/'E'),files=profile.validate_blobs(blobs)))
            bad = copy.deepcopy(service);bad['firmware_inputs']['model'] = 'U'
            with self.assertRaises(ValueError):
                profile.provision(root, 'E', bad)
            self.assertTrue((root/profile.BASE/'ws73.bin').exists())
            plan = profile.provision(root, 'E', service)
            self.assertEqual(len(plan['entries']), 4)
            self.assertFalse((root/profile.BASE/'ws73.bin').exists())
            self.assertFalse((root/profile.INPUTS/'E'/'ws73.bin').exists())
            profile.verify(root, plan)

    def test_saved_verdict_requires_exact_profile_and_hcc_per_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = prepare(Path(tmp));checks=[]
            for i, model in [(1,'U'), (2,'E')]:
                entry=plan['entries'][str(i)]
                raw=f"source=os-input directory={entry['directory']} expected_model=WS73{model} bus=USB filesystem_checked=18 execution_attested=0"
                checks.append(dict(host_port=f'host-{i}',guest_port=f'1-{i}',model=model,bus='USB',
                                   input_profile=profile.observed(raw,plan,str(i),model)))
            result=dict(firmware_input_contract_version=1,physical_resource_allocation=dict(
                input_profiles=plan,selected_ports=['host-1','host-2'],hcc_checks=checks),
                qemu_args=['-device',profile.QEMU_DEVICE,'-append','ws73.firmware_profiles=1'])
            self.assertTrue(profile.exit_gate(result))
            for key in ['qemu_args','physical_resource_allocation']:
                bad=copy.deepcopy(result);del bad[key];self.assertFalse(profile.exit_gate(bad))
            bad=copy.deepcopy(result);del bad['physical_resource_allocation']['hcc_checks'][0]['input_profile']
            self.assertFalse(profile.exit_gate(bad))
            bad=copy.deepcopy(result);bad['physical_resource_allocation']['hcc_checks'][0]['input_profile']=checks[1]['input_profile']
            self.assertFalse(profile.exit_gate(bad))
            bad=copy.deepcopy(result);bad['qemu_args'][0]='-name'
            self.assertFalse(profile.exit_gate(bad))
            bad=copy.deepcopy(result);bad['qemu_args'][2]='-name'
            self.assertFalse(profile.exit_gate(bad))
            bad=copy.deepcopy(result);bad['firmware_input_contract_version']=True
            self.assertFalse(profile.exit_gate(bad))
            self.assertTrue(profile.exit_gate({}))  # historical decoder only


if __name__ == '__main__':
    unittest.main()
