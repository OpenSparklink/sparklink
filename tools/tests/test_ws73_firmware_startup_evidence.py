# SPDX-License-Identifier: GPL-2.0-only
"""Actual startup evidence composition with explicit synthetic USB/log fixtures.

No controller/Host substitute. Hardware replays are recorded separately.
"""
import copy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_firmware_upload_evidence import startup_rows, exit_gate, requested_mode, IMAGES
from ws73_target import run_exit_code
import test_ws73_firmware_upload_evidence as upload_fixture
from test_ws73_model_evidence import fixture as model_fixture


def fixture(root):
    uploads = upload_fixture.UploadEvidence.fixture(None, root)
    outgoing, incoming = model_fixture()
    for row in outgoing:
        row['record'] += 100
        row['completion_record'] += 100
    incoming[0]['submit_record'] += 100
    incoming[0]['record'] += 100
    uploads.append(dict(bus=1, device=3, record=60, completion_record=61, raw=b'QUIT '))
    images = {name: dict(sha256=hashlib.sha256((root/name).read_bytes()).hexdigest(),
                         bytes=(root/name).stat().st_size) for _, name in IMAGES}
    selection = dict(model='E', sdk='1.10.110', variant='e', images=images)
    log = ('[ 1.000000] usb 1-1: new full-speed USB device number 3 using xhci_hcd\n'
           '[ 3.000000] usb 1-1: new high-speed USB device number 4 using xhci_hcd\n')
    observations = [dict(port='1-2.1.1', declared_model='E', interfaces=[dict(endpoints=2)])]
    return dict(outgoing=uploads+outgoing, incoming=incoming, kernel_log=log,
                ports=['1-2.1.1'], selection=selection, observations=observations, directory=root)


def record(proof):
    return dict(firmware_evidence_contract_version=1, firmware_evidence_mode='rom-upload', firmware_evidence=proof,
                physical_resource_allocation=dict(selected_ports=proof['selected_ports'], firmware=proof['staged']))


class FirmwareStartupEvidence(unittest.TestCase):
    def test_exact_inputs_quit_same_path_new_runtime_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = startup_rows(**fixture(Path(tmp)))
            self.assertEqual(proof['result'], 'PASS')
            self.assertTrue(exit_gate(record(proof)))
            self.assertEqual((proof['runtimes'][0]['rom_device'], proof['runtimes'][0]['device']), (3, 4))
            self.assertIs(proof['cold_power_verified'], False)
            self.assertIs(proof['executing_firmware_attested'], False)

    def test_staged_only_is_missing_and_strict_rejects_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            data['outgoing'] = [r for r in data['outgoing'] if r['device'] == 4]
            proof = startup_rows(**data)
            self.assertEqual(proof['result'], 'MISSING')
            current = record(proof)
            self.assertFalse(exit_gate(current))
            current['firmware_evidence_mode'] = 'runtime-observation'
            self.assertTrue(exit_gate(current))

    def test_later_warm_runtime_does_not_inherit_same_port_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            outgoing, incoming = model_fixture()
            for row in outgoing:
                row['device'] = 5; row['record'] += 200; row['completion_record'] += 200
            incoming[0].update(device=5, submit_record=212, record=213)
            data['outgoing'] += outgoing; data['incoming'] += incoming
            data['kernel_log'] += '[ 5.000000] usb 1-1: new high-speed USB device number 5 using xhci_hcd\n'
            proof = startup_rows(**data)
            self.assertEqual([r['result'] for r in proof['runtimes']], ['PASS', 'MISSING'])
            self.assertFalse(exit_gate(record(proof)))

    def test_missing_second_controller_cannot_be_covered_by_one_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp)); data['ports'].append('1-2.1.2')
            proof = startup_rows(**data)
            self.assertEqual(proof['ports_without_runtime'], ['1-2.1.2'])
            self.assertFalse(exit_gate(record(proof)))

    def test_later_upload_without_runtime_cannot_hide_behind_old_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = fixture(root)
            rows = upload_fixture.UploadEvidence.fixture(None, root)
            for row in rows:
                row.update(device=6, record=row['record']+200, completion_record=row['completion_record']+200)
            rows.append(dict(bus=1, device=6, record=260, completion_record=261, raw=b'QUIT '))
            data['outgoing'] += rows
            data['kernel_log'] += '[ 5.000000] usb 1-1: new full-speed USB device number 6 using xhci_hcd\n'
            proof = startup_rows(**data)
            self.assertEqual(proof['runtimes'][0]['result'], 'PASS')
            self.assertEqual(proof['unmatched_uploads'], [dict(bus=1, device=6, guest_port='1-1')])
            self.assertEqual(proof['result'], 'MISSING')
            self.assertFalse(exit_gate(record(proof)))

    def test_incomplete_or_ambiguous_chain_never_gains_upload_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = fixture(Path(tmp))
            for case in ['no-quit', 'duplicate-quit', 'late-quit', 'wrong-guest-path', 'reused-number',
                         'wrong-model', 'wrong-hash', 'no-ROM-observation', 'wrong-bytes', 'wrong-previous-instance']:
                data = copy.deepcopy(original)
                if case == 'no-quit': data['outgoing'].pop(8)
                elif case == 'duplicate-quit': data['outgoing'].insert(8, copy.deepcopy(data['outgoing'][8]))
                elif case == 'late-quit': data['outgoing'][8].update(record=115, completion_record=116)
                elif case == 'wrong-guest-path': data['kernel_log'] = data['kernel_log'].replace('1-1: new high', '1-2: new high')
                elif case == 'reused-number': data['kernel_log'] += data['kernel_log']
                elif case == 'wrong-model': data['incoming'][0]['raw'][108] = 0
                elif case == 'wrong-hash': data['selection']['images']['ws73.bin']['sha256'] = '0'*64
                elif case == 'no-ROM-observation': data['observations'][0]['interfaces'][0]['endpoints'] = 5
                elif case == 'wrong-bytes': data['outgoing'][1]['raw'] = b'wrong'
                else:
                    data['kernel_log'] = data['kernel_log'].replace('[ 3.000000]',
                        '[ 2.000000] usb 1-1: new full-speed USB device number 6 using xhci_hcd\n[ 3.000000]')
                with self.subTest(case=case):
                    try:
                        proof = startup_rows(**data)
                    except CaptureError:
                        continue
                    self.assertNotEqual(proof['result'], 'PASS')

    def test_exit_gate_rejects_forged_positive_or_cold_attestation_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = record(startup_rows(**fixture(Path(tmp))))
            for case in ['missing', 'empty', 'duplicate', 'wrong-ports', 'wrong-image', 'no-images',
                         'wrong-model-selection', 'cold', 'attestation', 'bad-version', 'bad-row']:
                data = copy.deepcopy(original)
                if case == 'missing': data.pop('firmware_evidence')
                elif case == 'empty': data['firmware_evidence']['runtimes'] = []
                elif case == 'duplicate': data['firmware_evidence']['runtimes'] *= 2
                elif case == 'wrong-ports': data['physical_resource_allocation']['selected_ports'] = ['1-2.1.2']
                elif case == 'wrong-image': data['firmware_evidence']['runtimes'][0]['proof']['images'][0]['image_sha256'] = '0'*64
                elif case == 'no-images': data['firmware_evidence']['runtimes'][0]['proof']['images'] = []
                elif case == 'wrong-model-selection': data['firmware_evidence']['staged']['model'] = 'U'
                elif case == 'cold': data['firmware_evidence']['cold_power_verified'] = True
                elif case == 'attestation': data['firmware_evidence']['executing_firmware_attested'] = True
                elif case == 'bad-version': data['firmware_evidence']['version'] = True
                else: data['firmware_evidence']['runtimes'] = [3]
                with self.subTest(case=case): self.assertFalse(exit_gate(data))

    def test_mode_is_explicit_before_any_artifact_or_USB_lookup(self):
        target = Path(__file__).resolve().parents[1]/'ws73_target.py'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'must-not-exist'
            result = subprocess.run([sys.executable, str(target), 'run', '--ports', '1-1.1.1', '1-1.1.2',
                                     '--prepared', str(Path(tmp)/'absent'), '--output', str(output)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('explicit --firmware-evidence', result.stderr)
            self.assertFalse(output.exists())
        for mode in ['rom-upload', 'runtime-observation']:
            args = SimpleNamespace(firmware_evidence=mode, qmp_hotplug=True, connection_verify=True, channel_socket_verify=True)
            self.assertEqual(requested_mode(args), mode)
        args.early_bootstrap_fault = True; args.firmware_evidence = 'rom-upload'
        with self.assertRaises(ValueError): requested_mode(args)

    def test_terminal_verdict_cannot_hide_missing_required_upload(self):
        historical = dict(status='ENVIRONMENT_FINISHED', qemu_exit=0, supervisor_exit=0)
        self.assertEqual(run_exit_code(historical), 0)
        current = dict(historical, firmware_evidence_contract_version=1, firmware_evidence_mode='rom-upload',
                       firmware_evidence=dict(version=1, result='MISSING', cold_power_verified=False, executing_firmware_attested=False))
        self.assertEqual(run_exit_code(current), 1)
        current['firmware_evidence_mode'] = 'runtime-observation'
        self.assertEqual(run_exit_code(current), 0)

    def test_external_expected_scope_rejects_deleted_or_downgraded_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = record(startup_rows(**fixture(Path(tmp))))
            self.assertTrue(exit_gate(original, 'rom-upload'))
            for deleted in [('firmware_evidence_mode',), ('firmware_evidence_contract_version',),
                            ('firmware_evidence_mode', 'firmware_evidence_contract_version')]:
                bad = copy.deepcopy(original)
                for key in deleted: bad.pop(key)
                self.assertFalse(exit_gate(bad, 'rom-upload'))
            bad = copy.deepcopy(original); bad['firmware_evidence_mode'] = 'runtime-observation'
            self.assertFalse(exit_gate(bad, 'rom-upload'))
            bad = copy.deepcopy(original); bad['firmware_evidence_contract_version'] = True
            self.assertFalse(exit_gate(bad, 'rom-upload'))
