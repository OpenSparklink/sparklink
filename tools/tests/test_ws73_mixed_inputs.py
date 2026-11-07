# SPDX-License-Identifier: GPL-2.0-only
"""Real file provisioner/guard and existing upload decoders with synthetic inputs.

No hardware, firmware execution, Native concurrency, or business qualification.
"""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_lab_resources as resources
import ws73_firmware_profile as profile
from ws73_firmware_upload_evidence import startup_rows, exit_gate, selections_by_port, IMAGES
from ws73_capture import CaptureError
from test_ws73_board_config import board, fixture as board_fixture
from test_ws73_firmware_profile import inputs
from test_ws73_firmware_startup_evidence import fixture as startup_fixture


def prepare_fixture(base):
    data = copy.deepcopy(resources.policy())
    selections = []
    for model, port in [('U', '1-1.1.1'), ('E', '1-2.1.1')]:
        directory = base / model; directory.mkdir()
        firmware = directory / 'firmware'; firmware.mkdir()
        blobs = inputs(model.encode())
        for name in resources.IMAGES:
            (firmware / name).write_bytes(blobs[name])
        data['firmware'][model]['images'] = {name: profile.record(blobs[name]) for name in resources.IMAGES}
        ini = directory / 'source.ini'; ini.write_text(board_fixture())
        candidate = directory / 'board'
        board.export(ini, candidate, 'fixture-not-hardware', 0)
        selections.append(dict(host_port=port, model=model, firmware_dir=str(firmware), board_dir=str(candidate)))
    prepared = base / 'prepared'; root = prepared / 'root'; root.mkdir(parents=True)
    package = resources.prepare_device_inputs(root, selections, data)
    return prepared, selections, package, data


class MixedInputs(unittest.TestCase):
    def test_actual_five_file_closure_and_leaf_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared, selections, package, data = prepare_fixture(Path(tmp))
            ports = [s['host_port'] for s in selections]
            firmware = resources.check_firmware(package, ports, prepared, data)
            board_proof = resources.check_board_configuration(package, ports, prepared, data)
            self.assertEqual([r['model'] for r in firmware['entries']], ['U', 'E'])
            self.assertEqual([r['guest_route'] for r in firmware['entries']], ['1', '2'])
            self.assertEqual(set(package['firmware_profiles']['entries']), {'1', '2'})
            self.assertEqual(selections_by_port(firmware, ports),
                             {e['host_port']: e['firmware'] for e in package['device_inputs']['entries']})
            record = dict(board_configuration_contract_version=2, physical_resource_allocation=dict(
                selected_ports=ports, firmware=firmware, board_configuration=board_proof))
            self.assertTrue(resources.board_configuration_exit_gate(record))
            for route, model in [('1', 'U'), ('2', 'E')]:
                directory = prepared / 'root/lib/firmware' / package['firmware_profiles']['entries'][route]['directory']
                self.assertEqual((directory / 'profile.bin').read_bytes()[8], profile.MODELS[model])
                self.assertEqual({p.name for p in directory.iterdir()}, {*profile.FILES, 'profile.bin'})

    def test_wrong_alias_model_order_route_and_contract_refuse_before_attach(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared, selections, package, data = prepare_fixture(Path(tmp))
            ports = [s['host_port'] for s in selections]
            for case in ('alias-firmware', 'alias-board', 'missing-version', 'bool-version', 'reordered',
                         'wrong-model', 'duplicate-port', 'wrong-route', 'wrong-SDK', 'wrong-board-model'):
                bad = copy.deepcopy(package)
                entries = bad['device_inputs']['entries']
                if case == 'alias-firmware': bad['explicit_firmware'] = entries[0]['firmware']
                elif case == 'alias-board': bad['board_configuration'] = entries[0]['board_configuration']
                elif case == 'missing-version': bad.pop('device_input_contract_version')
                elif case == 'bool-version': bad['device_input_contract_version'] = True
                elif case == 'reordered': entries.reverse()
                elif case == 'wrong-model': entries[1]['model'] = 'U'
                elif case == 'duplicate-port': entries[1]['host_port'] = ports[0]
                elif case == 'wrong-route': entries[1]['guest_route'] = '1'
                elif case == 'wrong-SDK': entries[1]['firmware']['images']['ws73.bin']['sha256'] = '0'*64
                else: entries[1]['board_configuration']['selected_model'] = 'U'
                for check in (resources.check_firmware, resources.check_board_configuration):
                    with self.subTest(case=case, check=check.__name__), self.assertRaises(ValueError):
                        check(bad, ports, prepared, data)
            for wrong_ports in (list(reversed(ports)), ports[:1], ['1-1.1.1', '1-2.1.3']):
                with self.assertRaises(ValueError): resources.check_firmware(package, wrong_ports, prepared, data)

    def test_each_actual_file_and_board_source_is_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared, selections, package, data = prepare_fixture(Path(tmp))
            ports = [s['host_port'] for s in selections]
            first = prepared / 'root/lib/firmware' / package['firmware_profiles']['entries']['1']['directory']
            second = prepared / 'root/lib/firmware' / package['firmware_profiles']['entries']['2']['directory']
            untouched = {p.name: p.read_bytes() for p in first.iterdir()}
            for name in (*profile.FILES, 'profile.bin'):
                path = second / name; before = path.read_bytes(); path.write_bytes(bytes([before[0]^1])+before[1:])
                try:
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        resources.check_firmware(package, ports, prepared, data)
                finally: path.write_bytes(before)
            self.assertEqual(untouched, {p.name: p.read_bytes() for p in first.iterdir()})
            source = Path(selections[1]['board_dir']).parent / 'source.ini'
            source.write_text(source.read_text()+'\n# changed\n')
            with self.assertRaises(ValueError): resources.check_board_configuration(package, ports, prepared, data)

    def test_invalid_last_input_publishes_no_partial_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); _, selections, _, data = prepare_fixture(base)
            other = base / 'other'; other.mkdir()
            (Path(selections[1]['firmware_dir'])/'btc_cali.bin').write_bytes(b'not-the-declared-file')
            with self.assertRaises(ValueError): resources.prepare_device_inputs(other, selections, data)
            self.assertEqual(list(other.iterdir()), [])

    def test_global_loader_files_are_never_a_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); _, selections, _, data = prepare_fixture(base)
            other = base / 'other'; path = other / profile.BASE / 'ws73.bin'
            path.parent.mkdir(parents=True); path.write_bytes(b'old-global')
            with self.assertRaises(ValueError): resources.prepare_device_inputs(other, selections, data)
            self.assertFalse((other / profile.PLAN).exists())

    def test_board_v2_cannot_downgrade_or_cross_leaf_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared, selections, package, data = prepare_fixture(Path(tmp)); ports=[s['host_port'] for s in selections]
            firmware=resources.check_firmware(package,ports,prepared,data)
            proof=resources.check_board_configuration(package,ports,prepared,data)
            original=dict(board_configuration_contract_version=2,physical_resource_allocation=dict(
                selected_ports=ports,firmware=firmware,board_configuration=proof))
            for case in ('reordered','wrong-model','missing-proof','bool-version','missing-contract-and-proof'):
                bad=copy.deepcopy(original);allocation=bad['physical_resource_allocation']
                if case=='reordered':allocation['board_configuration']['entries'].reverse()
                elif case=='wrong-model':allocation['board_configuration']['entries'][1]['configuration']['selected_model']='U'
                elif case=='missing-proof':allocation.pop('board_configuration')
                elif case=='bool-version':bad['board_configuration_contract_version']=True
                else:bad.pop('board_configuration_contract_version');allocation.pop('board_configuration')
                with self.subTest(case=case):self.assertFalse(resources.board_configuration_exit_gate(bad))


def mixed_startup(root):
    first=root/'E';second=root/'U';first.mkdir();second.mkdir()
    e=startup_fixture(first);u=startup_fixture(second)
    # Distinct synthetic U payloads exercise both byte and per-model binding.
    for _, name in IMAGES:
        path=second/name;payload=bytes(v^1 for v in path.read_bytes()[64:])
        path.write_bytes(hashlib.sha256(payload).hexdigest().encode()+payload)
    for row in u['outgoing']:
        if not row['raw'].startswith((b'FILES ', b'QUIT ')) and row['record']<100:
            row['raw']=bytes(v^1 for v in row['raw'])
        row['device']+=2;row['record']+=200;row['completion_record']+=200
    for row in u['incoming']:
        row['device']+=2;row['record']+=200;row['submit_record']+=200;row['raw'][108]=0
    u['selection'].update(model='U',variant='us',images={n:profile.record((second/n).read_bytes())for n in resources.IMAGES})
    ports=['1-2.1.1','1-1.1.1']
    selection=dict(version=2,entries=[dict(host_port=port,guest_route=str(i),**value)
                                    for i,(port,value)in enumerate(zip(ports,[e['selection'],u['selection']]),1)])
    return dict(outgoing=e['outgoing']+u['outgoing'],incoming=e['incoming']+u['incoming'],
        kernel_log=e['kernel_log']+'[ 4.000000] usb 1-2: new full-speed USB device number 5 using xhci_hcd\n[ 6.000000] usb 1-2: new high-speed USB device number 6 using xhci_hcd\n',
        ports=ports,selection=selection,observations=e['observations']+[dict(port=ports[1],declared_model='U',interfaces=[dict(endpoints=2)])],
        directory={ports[0]:first,ports[1]:second})


class MixedStartup(unittest.TestCase):
    def test_two_independent_image_uploads_and_HCC_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=mixed_startup(Path(tmp));proof=startup_rows(**data)
            self.assertEqual((proof['version'],proof['result']),(2,'PASS'))
            self.assertEqual([r['hcc']['model']for r in proof['runtimes']],['WS73E','WS73U'])
            receipt=dict(firmware_evidence_contract_version=2,firmware_evidence_mode='rom-upload',firmware_evidence=proof,
                         physical_resource_allocation=dict(selected_ports=data['ports'],firmware=data['selection']))
            self.assertTrue(exit_gate(receipt))
            for case in ('global-alias','reordered','model','image','version'):
                bad=copy.deepcopy(data)
                if case=='global-alias':bad['selection']['model']='E'
                elif case=='reordered':bad['selection']['entries'].reverse()
                elif case=='model':bad['selection']['entries'][1].update(model='E',variant='e')
                elif case=='image':bad['selection']['entries'][1]['images']=bad['selection']['entries'][0]['images']
                else:bad['selection']['version']=True
                with self.subTest(case=case),self.assertRaises(CaptureError):startup_rows(**bad)
            for case in ('downgrade','remove-staged','wrong-ports'):
                bad=copy.deepcopy(receipt)
                if case=='downgrade':bad['firmware_evidence_contract_version']=1
                elif case=='remove-staged':bad['firmware_evidence'].pop('staged')
                else:bad['physical_resource_allocation']['selected_ports'].reverse()
                with self.subTest(case=case):self.assertFalse(exit_gate(bad))

    def test_warm_result_remains_missing_and_has_no_unvalidated_v2_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=mixed_startup(Path(tmp))
            # Retain the Runtime HCC query AND first DLI; omit only ROM instances.
            data['outgoing']=[r for r in data['outgoing']if r['device']in(4,6)]
            proof=startup_rows(**data);self.assertEqual(proof['result'],'MISSING')
            receipt=dict(firmware_evidence_contract_version=2,firmware_evidence_mode='runtime-observation',firmware_evidence=proof,
                         physical_resource_allocation=dict(selected_ports=data['ports'],firmware=data['selection']))
            self.assertTrue(exit_gate(receipt))
            for case in ('remove-allocation','remove-staged','alter-ports','bool-version'):
                bad=copy.deepcopy(receipt)
                if case=='remove-allocation':bad.pop('physical_resource_allocation')
                elif case=='remove-staged':bad['firmware_evidence'].pop('staged')
                elif case=='alter-ports':bad['firmware_evidence']['selected_ports'].reverse()
                else:bad['firmware_evidence_contract_version']=True
                with self.subTest(case=case):self.assertFalse(exit_gate(bad))


if __name__=='__main__':unittest.main()
