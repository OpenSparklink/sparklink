# SPDX-License-Identifier: GPL-2.0-only
"""Actual host guard with filesystem/fd/QMP fixtures; no real USB operation."""
import copy
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_lab_resources as resource
import build_resources as build
import ws73_firmware_profile as profile
from test_ws73_firmware_profile import inputs as profile_inputs
from ws73_target import usb_properties


class AllocatedResources(unittest.TestCase):
    def test_execution_state_has_one_current_topology_authority(self):
        data = resource.policy()
        state = {'hardware_resource_allocation': {
            'policy': 'project/lab-resource-policy.json', 'owner': data['owner'],
            'allowed_U': ['1-1.1.1', '1-1.1.2'],
            'allowed_E': ['1-2.1.1', '1-2.1.2'],
            'forbidden': data['forbidden_ports'],
            'runtime_directory': data['run_root'], 'source_worktree': data['worktree'],
        }, 'hardware_constraint': {
            'operational_scope_ref': 'hardware_resource_allocation.policy',
            'historical_topology_revision': {'models': {'1-2.1.2': 'U'}},
        }}
        self.assertEqual(resource.execution_state_errors(state, data), [])
        for key, value in [('allowed_U', ['1-2.1.2']), ('allowed_E', ['1-1.1.1']),
                           ('forbidden', []), ('source_worktree', 'sparklink'),
                           ('runtime_directory', '.dev/shared'), ('owner', 'other-thread')]:
            bad = copy.deepcopy(state)
            bad['hardware_resource_allocation'][key] = value
            self.assertTrue(resource.execution_state_errors(bad, data), key)
        for key in ['current_operational_scope', 'topology_revision']:
            bad = copy.deepcopy(state)
            bad['hardware_constraint'][key] = 'historical map must not be operational'
            self.assertTrue(resource.execution_state_errors(bad, data), key)
        for bad in [{}, dict(state, hardware_constraint={}),
                    dict(state, hardware_constraint=None),
                    dict(state, hardware_resource_allocation=None)]:
            self.assertTrue(resource.execution_state_errors(bad, data))

    def test_actual_cli_rejects_unallocated_port_before_artifact_or_usb_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'must-not-exist'
            program=Path(__file__).resolve().parents[1]/'ws73_target.py'
            for port in resource.policy()['forbidden_ports']+['1-1.1','1-2.1']:
                result=subprocess.run([sys.executable,str(program),'run','--ports',port,
                    '--prepared',str(Path(tmp)/'nonexistent-artifact'),'--output',str(out)],
                    text=True,capture_output=True,timeout=10)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('outside this thread whitelist',result.stderr)
                self.assertFalse(out.exists())

    def test_explicit_subset_no_old_ports_hubs_enumeration_or_fallback(self):
        data = resource.policy()
        self.assertEqual(resource.selected(['1-1.1.1', '1-1.1.2']), ['U', 'U'])
        self.assertEqual(resource.selected(['1-2.1.1', '1-2.1.2']), ['E', 'E'])
        for ports in [[], ['1-1.1.1'] * 2, ['1-1.1'], ['1-2.1'], ['1-9'],
                      *[[p] for p in data['forbidden_ports']]]:
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                resource.selected(ports)

    def test_snapshot_rechecks_stable_identity_not_device_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sysfs = base / 'sysfs'; sysfs.mkdir()
            pci = base / '0000:c5:00.3'; pci.mkdir()
            hub = pci / '1-1.1'; hub.mkdir()
            device = hub / '1-1.1.1'; device.mkdir()
            (sysfs / hub.name).symlink_to(hub)
            (sysfs / device.name).symlink_to(device)
            for p, values in [(hub, dict(idVendor='05e3', idProduct='0610')),
                              (device, dict(idVendor='ffff', idProduct='3733', serial='fixture-only', busnum='1', devnum='16'))]:
                for k,v in values.items(): (p/k).write_text(v)
            interface = device / '1-1.1.1:1.0'; interface.mkdir()
            (interface / 'bNumEndpoints').write_text('02')
            data=copy.deepcopy(resource.policy())
            data['ports'][device.name]['serial_sha256']=hashlib.sha256(b'fixture-only').hexdigest()
            self.assertEqual(resource.snapshot(device.name,data,sysfs)['device'],16)
            (device/'devnum').write_text('97')
            self.assertEqual(resource.snapshot(device.name,data,sysfs)['device'],97)
            for p, value, original in [(device/'serial','replacement','fixture-only'),
                                       (hub/'idProduct','9999','0610'),(device/'idVendor','0000','ffff'),
                                       (interface/'bNumEndpoints','03','02')]:
                p.write_text(value)
                with self.assertRaises(ValueError): resource.snapshot(device.name,data,sysfs)
                p.write_text(original)
            data['controller']='0000:ff:00.0'
            with self.assertRaises(ValueError):resource.snapshot(device.name,data,sysfs)
            with self.assertRaises(ValueError):resource.snapshot('1-1.1.2',resource.policy(),sysfs)

    def test_actual_firmware_set_and_mixed_or_old_provenance_fail_closed(self):
        data=copy.deepcopy(resource.policy())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            expected=data['firmware']['U']
            blobs=profile_inputs();(root/'root').mkdir()
            for name in resource.IMAGES:
                raw=blobs[name]
                expected['images'][name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
            plan=profile.stage(root/'root',{'1':('U',blobs),'2':('U',blobs)})
            firmware_dir=root/'root/lib/firmware'/plan['entries']['1']['directory']
            explicit=resource.explicit_firmware('U',firmware_dir,data)
            package={'explicit_firmware':explicit,'firmware_input_contract_version':1,'firmware_profiles':plan}
            self.assertEqual(resource.check_firmware(package,['1-1.1.1','1-1.1.2'],root,data),explicit)
            for ports, bad in [(['1-1.1.1','1-2.1.1'],package),(['1-1.1.1'],{}),
                               (['1-1.1.1'],dict(package,native_vm={'runtime_only':True})),
                               (['1-2.1.2'],package)]:
                with self.assertRaises(ValueError):resource.check_firmware(bad,ports,root,data)
            old=root/'root/usr/lib/firmware/sparklink/ws73/btc_cali.bin'
            old.parent.mkdir(parents=True);old.write_bytes(blobs['btc_cali.bin'])
            with self.assertRaises(ValueError):resource.check_firmware(package,['1-1.1.1'],root,data)
            old.unlink()
            # A corrupt unselected closure must not poison a different device.
            second=root/'root/lib/firmware'/plan['entries']['2']['directory']/'btc_cali.bin'
            second.write_bytes(b'wrong calibration')
            self.assertEqual(resource.check_firmware(package,['1-1.1.1'],root,data),explicit)
            with self.assertRaises(ValueError):resource.check_firmware(package,['1-1.1.1','1-1.1.2'],root,data)
            (firmware_dir/'wifi_cali.bin').write_bytes(b'wrong variant')
            with self.assertRaises(ValueError):resource.explicit_firmware('U',firmware_dir,data)
            with self.assertRaises(ValueError):resource.explicit_firmware(None,firmware_dir,data)

    def test_occupancy_refuses_driver_and_actual_open_fd(self):
        row=dict(port='1-1.1.1',bus=1,device=16,interfaces=[{'driver':None}])
        with tempfile.TemporaryDirectory() as tmp:
            proc=Path(tmp)
            resource.check_available(row,proc)
            fd=proc/'42/fd';fd.mkdir(parents=True)
            (fd/'7').symlink_to('/dev/bus/usb/001/016')
            with self.assertRaises(ValueError):resource.check_available(row,proc)
            (fd/'7').unlink()
            row['interfaces'][0]['driver']='usbfs'
            with self.assertRaises(ValueError):resource.check_available(row,proc)

    def test_live_vm_assignment_uses_topology_and_allows_other_thread(self):
        def xml(source):
            return '<domain><devices><hostdev type="usb"><source>'+source+'</source></hostdev></devices></domain>'
        leaf = '<vendor id="0xffff"/><product id="0x3733"/><address bus="1" device="16"/>'
        with tempfile.TemporaryDirectory() as tmp:
            sysfs = Path(tmp)
            for port, number in [('1-1.1.1',16),('1-1.1.3',17)]:
                d=sysfs/port;d.mkdir()
                (d/'busnum').write_text('1');(d/'devnum').write_text(str(number))
            with self.assertRaisesRegex(ValueError,'allocated leaf'):
                resource.check_vm_xml(xml(leaf),['1-1.1.1'],sysfs=sysfs)
            other=xml(leaf.replace('device="16"','device="17"'))
            self.assertEqual(resource.check_vm_xml(other,['1-1.1.1'],sysfs=sysfs)[0]['port'],'1-1.1.3')
            # The former number no longer proves identity after reenumeration.
            (sysfs/'1-1.1.1/devnum').write_text('99')
            with self.assertRaisesRegex(ValueError,'unresolved live WS73'):
                resource.check_vm_xml(xml(leaf),['1-1.1.1'],sysfs=sysfs)
            with self.assertRaisesRegex(ValueError,'allocated leaf'):
                resource.check_vm_xml(xml(leaf.replace('device="16"','device="99"')),['1-1.1.1'],sysfs=sysfs)

    def test_vm_hub_controller_and_ambiguous_selector_require_coordination(self):
        def xml(kind,source):
            return '<domain><devices><hostdev type="'+kind+'"><source>'+source+'</source></hostdev></devices></domain>'
        for source in ['<address bus="1" port="1.1"/>',
                       '<address bus="1" port="1.1.1"/>',
                       '<vendor id="0xffff"/><product id="0x3733"/>', '']:
            with self.subTest(source=source),self.assertRaises(ValueError):
                resource.check_vm_xml(xml('usb',source),['1-1.1.1'])
        pci='<address domain="0x0000" bus="0xc5" slot="0x00" function="0x3"/>'
        with self.assertRaisesRegex(ValueError,'shared USB controller'):
            resource.check_vm_xml(xml('pci',pci),['1-2.1.1'])
        # Other PCI and explicitly other-thread ports do not stop our task.
        self.assertEqual(resource.check_vm_xml(xml('pci',pci.replace('0xc5','0xc6')),['1-2.1.1'])[0]['controller'],'0000:c6:00.3')
        self.assertEqual(resource.check_vm_xml(xml('usb','<address bus="1" port="2.1.4"/>'),['1-2.1.1'])[0]['port'],'1-2.1.4')
        with self.assertRaises(ValueError):resource.check_vm_xml('<domain/>',['1-2.1.4'])

    def test_live_inventory_only_reads_and_preserves_xml_identity(self):
        raw='<domain><devices><hostdev type="usb"><source><vendor id="0x1234"/><product id="0x0001"/></source></hostdev></devices></domain>'
        with patch.object(resource.subprocess,'run',side_effect=[
            subprocess.CompletedProcess([],0,'peer-vm\n\n',''),subprocess.CompletedProcess([],0,raw,'')]) as query:
            report=resource.check_live_vms(['1-1.1.1'])
        self.assertEqual(query.call_count,2)
        self.assertEqual(query.call_args_list[0].args[0],['virsh','-c','qemu:///system','list','--name'])
        self.assertEqual(query.call_args_list[1].args[0][-3:],['dumpxml','--','peer-vm'])
        self.assertEqual(report['live_vms'][0]['xml_sha256'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertIn('NOT_HARDWARE_QUALIFICATION',report['status'])
        for call in query.call_args_list:
            self.assertGreater(call.kwargs['timeout'],0);self.assertLessEqual(call.kwargs['timeout'],5)

    def test_unobservable_corrupt_overbudget_or_timed_out_vm_inventory_refuses(self):
        for failure in [FileNotFoundError('virsh'),subprocess.CalledProcessError(1,['virsh']),
                        subprocess.TimeoutExpired(['virsh'],5)]:
            with patch.object(resource.subprocess,'run',side_effect=failure),self.assertRaisesRegex(ValueError,'unavailable'):
                resource.check_live_vms(['1-1.1.1'])
        for names in ['\n'.join(str(i) for i in range(65)),'duplicate\nduplicate','x'*(1024*1024+1)]:
            with patch.object(resource.subprocess,'run',return_value=subprocess.CompletedProcess([],0,names,'')),self.assertRaises(ValueError):
                resource.check_live_vms(['1-1.1.1'])
        for raw in ['<domain', '<unrelated/>', '<domain/>', '<domain><devices><hostdev type="pci"/></devices></domain>',
                    '<domain><devices><hostdev type="usb"><source><address bus="x" device="y"/></source></hostdev></devices></domain>']:
            with patch.object(resource.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,'test-vm',''),subprocess.CompletedProcess([],0,raw,'')]),self.assertRaises(ValueError):
                resource.check_live_vms(['1-1.1.1'])
        with patch.object(resource.subprocess,'run') as query,self.assertRaises(ValueError):
            resource.check_live_vms(['1-1.1.4'])
        query.assert_not_called()

    def test_actual_runner_checks_all_owned_leaves_before_qemu_and_releases_lease(self):
        import ws73_target as target
        with tempfile.TemporaryDirectory() as tmp,patch.object(resource,'workspace',return_value=Path(tmp)),\
             patch.object(target,'build_workspace',return_value=Path(tmp)),\
             patch.object(resource,'check_paths'),patch.object(target,'lab_module'),\
             patch.object(target,'_run',return_value=17) as run,\
             patch.object(build,'real_device_vm',return_value=nullcontext(42)) as marker,\
             patch.object(resource,'check_live_vms',side_effect=ValueError('peer VM conflict')) as inventory:
            args=SimpleNamespace(command='run',ports=['1-1.1.1'],output=Path(tmp)/'run',prepared=Path(tmp)/'prepared',firmware_evidence='runtime-observation')
            with self.assertRaisesRegex(ValueError,'peer VM conflict'):target.run(args)
            inventory.assert_called_once_with(list(resource.policy()['ports']),resource.policy())
            run.assert_not_called();marker.assert_not_called()
            # A failed preflight cannot retain the real file lease or budget.
            with resource.port_leases(args.ports):pass
            inventory.side_effect=None;inventory.return_value={'status':'fixture-only'}
            self.assertEqual(target.run(args),17)
            self.assertEqual(args._resource_vm_inventory,{'status':'fixture-only'})
            self.assertIn(42,args._resource_fds)
            run.assert_called_once_with(args)

    def test_every_monitor_attach_including_reenumeration_is_rechecked(self):
        # QMP dispatch fixture only, not a successful firmware/board/USB gate.
        with patch.object(resource,'check_firmware',return_value={}),\
             patch.object(resource,'check_board_configuration',return_value={}) as board,\
             patch.object(resource.PhysicalBoundary,'check') as check:
            boundary=resource.PhysicalBoundary(['1-1.1.1'],{},Path('/fixture'))
            actual=Mock();monitor=boundary.monitor(actual);args=usb_properties('1-1.1.1',0)
            monitor.execute('device_add',args);monitor.execute('device_del',{'id':'ws73_0'});monitor.execute('device_add',args)
            self.assertEqual(check.call_count,3)
            self.assertEqual(board.call_count,3)  # Constructor plus every attach.
            for bad in [usb_properties('1-1.1.3',0),dict(args,**{'host-reset':True}),
                        dict(args,driver='vfio-pci'),dict(args,hostport='1.1'),dict(args,hostaddr=16)]:
                with self.assertRaises(ValueError):monitor.execute('device_add',bad)
            with self.assertRaises(ValueError):monitor.execute('device_del',{'id':'ws73_1'})
            self.assertEqual(actual.execute.call_count,3)

    def test_board_inputs_actual_export_and_prepared_root_fail_closed(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('board_fixtures',Path(__file__).with_name('test_ws73_board_config.py'))
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ini=root/'source.ini';ini.write_text(fixtures.fixture())
            candidate=root/'candidate';fixtures.board.export(ini,candidate,'not-a-hardware-claim',0)
            proof=resource.board_configuration(candidate,'E')
            package=dict(board_configuration_contract_version=1,board_configuration=proof)
            prepared=root/'prepared'
            destination=prepared/'root';destination.mkdir(parents=True)
            blobs=profile_inputs()
            for name in proof['images']:blobs[name]=(candidate/name).read_bytes()
            plan=profile.stage(destination,{'1':('E',blobs),'2':('E',blobs)})
            package.update(firmware_input_contract_version=1,firmware_profiles=plan)
            self.assertEqual(resource.check_board_configuration(package,['1-2.1.1','1-2.1.2'],prepared),proof)
            for ports in [['1-1.1.1'],['1-1.1.1','1-2.1.1']]:
                with self.assertRaises(ValueError):resource.check_board_configuration(package,ports,prepared)
            for version in [None,True,2]:
                with self.assertRaises(ValueError):resource.check_board_configuration(dict(package,board_configuration_contract_version=version),['1-2.1.1'],prepared)
            receipt=dict(board_configuration_contract_version=1,physical_resource_allocation=dict(firmware=dict(model='E'),board_configuration=proof))
            self.assertTrue(resource.board_configuration_exit_gate(receipt))
            import ws73_target as target
            # Test the real finalizer, without inventing successful hardware evidence.
            for bad in [dict(receipt,board_configuration_contract_version=True),
                        dict(receipt,physical_resource_allocation=dict(firmware=dict(model='U'),board_configuration=proof))]:
                self.assertFalse(resource.board_configuration_exit_gate(bad))
                self.assertEqual(target.run_exit_code(bad),1)
            payload=destination/'lib/firmware'/plan['entries']['1']['directory']/'pm_config.bin'
            payload.write_bytes(b'bad!')
            with self.assertRaises(ValueError):resource.check_board_configuration(package,['1-2.1.1'],prepared)
            payload.unlink();payload.symlink_to(candidate/'pm_config.bin')
            with self.assertRaises(ValueError):resource.check_board_configuration(package,['1-2.1.1'],prepared)
            ini.write_text(fixtures.fixture()+'\n# stale\n')
            with self.assertRaises(ValueError):resource.board_configuration(candidate,'E')

    def test_real_port_lock_process_and_independent_leaf(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(resource,'workspace',return_value=Path(tmp)):
            p=Path(tmp)/'.dev/ws73-port-leases/1-1.1.1.lock'
            script='import fcntl,sys\nf=open(sys.argv[1],"a+")\ntry:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:sys.exit(17)\n'
            with resource.port_leases(['1-1.1.1']) as fds:
                self.assertEqual(len(fds),1)
                self.assertEqual(subprocess.run([sys.executable,'-c',script,str(p)]).returncode,17)
                with resource.port_leases(['1-1.1.2']):pass
            self.assertEqual(subprocess.run([sys.executable,'-c',script,str(p)]).returncode,0)

    def test_independent_paths_and_worktree_no_old_prepared_root(self):
        data=copy.deepcopy(resource.policy())
        # Exercise the path contract in any checkout; only actual physical
        # execution uses the thread's fixed worktree from the shipped policy.
        data['worktree']=Path(resource.__file__).resolve().parents[1].relative_to(resource.workspace()).as_posix()
        root=resource.workspace()/data['run_root']
        resource.check_paths(root/'run1',root/'prepared1',data)
        for value in [Path('/tmp/old'),root/'../escaped',root/'../../sparklink']:
            with self.assertRaises(ValueError):resource.check_paths(value,root/'prepared1',data)

    def test_hcc_is_independent_from_declared_placement_vidpid_and_ready(self):
        for model,number in [('U',0),('E',2)]:
            raw=f'source=HCC_GET_CHIP_TYPE model=WS73{model} model_id={number} bus=USB bus_id=0'
            self.assertEqual(resource.check_hcc(raw,model)['model'],model)
            for bad in [raw.replace('USB','UART'),raw.replace('bus_id=0','bus_id=2'), 'ffff:3733', '', 'Ready']:
                with self.assertRaises(ValueError):resource.check_hcc(bad,model)
            with self.assertRaises(ValueError):resource.check_hcc(raw,'E' if model=='U' else 'U')

    def test_standalone_hcc_binds_registration_and_rejects_change_or_missing_metadata(self):
        # Real metadata reader/checker; registration is a visible fixture here,
        # not actual kernel concurrency, firmware provenance or RF acceptance.
        identity=dict(port='1-1',index=0,generation=7,bus=1,device=2,address='00:01:09:32:54:CD')
        current=dict(identity,path='/org/sparklink/slk0_g7',version='00'*5,features='00'*10)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);interface=root/'1-1/1-1:1.0';interface.mkdir(parents=True)
            chip=interface/'chip_information'
            chip.write_text('source=HCC_GET_CHIP_TYPE model=WS73U model_id=0 bus=USB bus_id=0\n')
            with patch('ws73_north_star.registration',return_value=current):
                observed=resource.observe_guest_hcc(identity,'U',root)
                self.assertEqual(observed['generation'],7)
                self.assertEqual(observed['hcc_chip']['model'],'U')
                for key,value in [('generation',8),('device',3),('index',1),('address','00:01:09:32:54:F9')]:
                    with self.assertRaises(ValueError):resource.observe_guest_hcc(dict(identity,**{key:value}),'U',root)
                with self.assertRaises(ValueError):resource.observe_guest_hcc(identity,'E',root)
                chip.unlink()
                with self.assertRaises(FileNotFoundError):resource.observe_guest_hcc(identity,'U',root)
            chip.write_text('source=HCC_GET_CHIP_TYPE model=WS73U model_id=0 bus=USB bus_id=0')
            with patch('ws73_north_star.registration',side_effect=[current,dict(current,generation=8)]):
                with self.assertRaises(ValueError):resource.observe_guest_hcc(identity,'U',root)


if __name__=='__main__':unittest.main()
