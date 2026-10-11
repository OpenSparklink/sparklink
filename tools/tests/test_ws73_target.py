# SPDX-License-Identifier: GPL-2.0-only
import json
import errno
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_target import board_files, config_required, opened_usb_node, prepared, usb_host_boundary, usb_properties, HostTimeline, SerialTimeoutSeal, lifecycle_trace, USB_LIFECYCLE_EVENTS
from ws73_north_star import _registration, file_record, healthy_native_runtime, registration, Run
from ws73_target_control import SyntheticControlRun, PassthroughControlRun
from types import SimpleNamespace
import ws73_target_guest as guest


class TargetEnvironment(unittest.TestCase):
    def test_active_deadline_gate_rejects_synthetic_and_release_modes_before_output(self):
        import ws73_target
        for changes in [dict(command='support'),dict(fault_recovery=False),dict(diagnostic_verify=True),
                        dict(diagnostic_cancel_verify=True),dict(diagnostic_deadline_verify=True),dict(diagnostic_autonomous_verify=True)]:
            with self.subTest(changes=changes),tempfile.TemporaryDirectory() as temporary:
                output=Path(temporary)/'never-created'
                fields=dict(command='run',output=output,active_deadline_verify=True,fault_recovery=True)
                fields.update(changes)
                with patch.object(ws73_target,'ordinary_identity'),self.assertRaisesRegex(ValueError,'active retirement requires'):
                    ws73_target._run(SimpleNamespace(**fields))
                self.assertFalse(output.exists())

    def test_timeout_never_confirms_manual_hotplug_or_uses_old_shell_prompt(self):
        initial=b'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0\r\n/ $ \x1b[6n'
        seal=SerialTimeoutSeal(initial)
        self.assertEqual(seal.initial_input,b'\x03')
        self.assertEqual(seal.feed(initial),b'')
        waiting=initial+b'Unplug only WS73 at 1-1, then press Enter: '
        self.assertEqual(seal.feed(waiting),b'')
        self.assertEqual(seal.feed(waiting+b'Reinsert WS73 at 1-1, then press Enter: '),b'')
        self.assertEqual(seal.feed(waiting+b'\r\nFAIL /evidence/application/control/run.json\r\n/ $ \x1b['),b'')
        closed=waiting+b'\r\nFAIL /evidence/application/control/run.json\r\n/ $ \x1b[6n'
        self.assertEqual(seal.feed(closed),b'exit 0\n')
        self.assertEqual(seal.feed(closed),b'')
        self.assertEqual(seal.phase,'EXIT_SENT')

    def test_timeout_does_not_interrupt_root_supervisor_or_unready_guest(self):
        with self.assertRaises(ValueError): SerialTimeoutSeal(b'WS73_TARGET_CAPTURE_READY\n')
        closed=b'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0\nWS73_TARGET_SHELL_CLOSED\n'
        seal=SerialTimeoutSeal(closed)
        self.assertEqual(seal.initial_input,b'')
        self.assertEqual(seal.feed(closed+b'/ $ '),b'')
        self.assertEqual(seal.phase,'CLOSING')
        active=SerialTimeoutSeal(closed.split(b'WS73_TARGET_SHELL_CLOSED')[0])
        self.assertEqual(active.feed(closed+b'/ $ '),b'')

    def test_readiness_retries_only_transient_sysfs_metadata_errors(self):
        for code in (errno.EAGAIN, errno.ENODATA, errno.ENOENT, errno.EIO):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as d:
                root=Path(d); usb=root/'usb'; device=usb/'1-1'; interface=device/'1-1:1.0'
                interface.mkdir(parents=True); evidence=root/'evidence'; evidence.mkdir()
                for name,value in {'native_runtime':'id=0 generation=1 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100',
                                   'boot_stage':'native-runtime-ready','boot_error':'0',
                                   'recovery_budget':'attempts=1 limit=2 cause=-71 result=0',
                                   'controller_information':'queried metadata'}.items():
                    (interface/name).write_text(value+'\n')
                (device/'busnum').write_text('1\n'); (device/'devnum').write_text('7\n')
                result=SimpleNamespace(returncode=0,stdout='  State:       Ready\n  Address:     02:73:00:00:00:01\n',stderr='')
                original=Path.read_text; reads=0
                def read(path,*args,**kwargs):
                    nonlocal reads
                    if path.name=='controller_information':
                        reads+=1
                        if reads==1:raise OSError(code,'metadata invalidated during restore')
                    return original(path,*args,**kwargs)
                def path(value):return usb if value=='/sys/bus/usb/devices' else Path(value)
                with patch.object(guest,'Path',side_effect=path),patch.object(guest,'EVIDENCE',evidence), \
                     patch.object(Path,'read_text',read),patch.object(guest.time,'sleep'), \
                     patch.object(guest,'application',return_value=result):
                    if code==errno.EIO:
                        with self.assertRaises(OSError):guest.ready(0)
                    else:guest.ready(0)
                if code!=errno.EIO:
                    self.assertEqual(json.loads((evidence/'ready-0.json').read_text())['controller_information'],'queried metadata')
                    self.assertEqual(reads,2)

    def test_inventory_timeline_retains_unselected_removal_and_final(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'inventory.jsonl';timeline=HostTimeline(path)
            before={'1-1':{'address':1}, '1-2':{'address':2}}
            after={'1-1':{'address':1}}
            timeline.observe(before,'initial');timeline.observe(before)
            timeline.observe(after);timeline.observe(after);timeline.observe(after,'final')
            records=[json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual([x['sequence'] for x in records],[0,1,2])
            self.assertEqual([x['phase'] for x in records],['initial','poll','final'])
            self.assertEqual(records[0]['devices'],before)
            self.assertEqual(records[1]['devices'],after)
            self.assertTrue(all(x['wall_ns']>0 and x['monotonic_ns']>0 for x in records))

    def test_lifecycle_trace_requires_all_metadata_events(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch('ws73_target.subprocess.check_output',return_value='\n'.join(USB_LIFECYCLE_EVENTS)) as call:
                args=lifecycle_trace(Path('/test/qemu'),root)
            self.assertEqual(call.call_args.args[0],['/test/qemu','-trace','help'])
            self.assertEqual(args,['-msg','timestamp=on','-trace',f'events={root}/usb-lifecycle.events,file={root}/usb-lifecycle.log'])
            self.assertEqual((root/'usb-lifecycle.events').read_text().splitlines(),list(USB_LIFECYCLE_EVENTS))
            with patch('ws73_target.subprocess.check_output',return_value='usb_host_close\n'):
                with self.assertRaisesRegex(ValueError,'events missing'):lifecycle_trace(Path('/test/qemu'),root)

    def test_bootstrap_failure_is_saved_without_waiting_ready_deadline(self):
        for diagnostics in [None, 'phase=10 error=-5 event=000a hardware_error=0']:
            with self.subTest(diagnostics=diagnostics),tempfile.TemporaryDirectory() as d:
                root=Path(d);usb=root/'usb';interface=usb/'1-1/1-1:1.0';interface.mkdir(parents=True)
                evidence=root/'evidence';evidence.mkdir()
                for name,value in {'native_runtime':'id=-1 generation=0 streaming=0 broken=0',
                                   'boot_stage':'failed','boot_error':'-5',
                                   'warm_recovery':'attempts=1 limit=1 cause=-110 result=-5 started_ms=10001'}.items():
                    (interface/name).write_text(value+'\n')
                if diagnostics is not None:(interface/'failure_diagnostics').write_text(diagnostics+'\n')
                def path(value):return usb if value=='/sys/bus/usb/devices' else Path(value)
                with patch.object(guest,'Path',side_effect=path),patch.object(guest,'EVIDENCE',evidence),\
                     patch.object(guest.time,'sleep') as sleep,patch.object(guest,'application') as app:
                    with self.assertRaisesRegex(ValueError,'native bootstrap failed: -5'):guest.ready(0)
                sleep.assert_not_called();app.assert_not_called()
                saved=json.loads((evidence/'ready-progress-0.json').read_text())
                self.assertEqual((saved['boot_stage'],saved['boot_error']),('failed',-5))
                self.assertEqual(saved.get('failure_diagnostics'),diagnostics)
                self.assertEqual(saved['warm_recovery'],'attempts=1 limit=1 cause=-110 result=-5 started_ms=10001')

    def test_initialization_failure_retains_raw_status_without_waiting(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);usb=root/'usb';interface=usb/'1-1/1-1:1.0';interface.mkdir(parents=True)
            evidence=root/'evidence';evidence.mkdir()
            for name,value in {'native_runtime':'id=0 generation=1 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100',
                               'boot_stage':'native-runtime-setup','boot_error':'0',
                               'warm_recovery':'attempts=1 limit=1 cause=-110 result=0 started_ms=10001'}.items():
                (interface/name).write_text(value+'\n')
            def path(value):return usb if value=='/sys/bus/usb/devices' else Path(value)
            error='initialization operation=6 state=4 status=0x0b errno=0'
            result=SimpleNamespace(returncode=0,stdout='  State:       Setup\n  Init error:  '+error+'\n',stderr='')
            with patch.object(guest,'Path',side_effect=path),patch.object(guest,'EVIDENCE',evidence), \
                 patch.object(guest.time,'sleep') as sleep,patch.object(guest,'application',return_value=result):
                with self.assertRaisesRegex(ValueError,'adapter initialization failed'):guest.ready(0)
            sleep.assert_not_called()
            saved=json.loads((evidence/'ready-progress-0.json').read_text())
            self.assertIn(error,saved['stdout'])
            self.assertEqual(saved['exit'],0)

    def test_physical_registration_uses_actual_no_error_sentinel(self):
        # Filesystem fixture only. This is not a hardware/RF acceptance record.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);device=root/'1-2';device.mkdir();interface=root/'1-2:1.0';interface.mkdir()
            driver=root/'drivers/sparklink_ws73_usb';driver.mkdir(parents=True);(interface/'driver').symlink_to(driver)
            for name,value in {'idVendor':'ffff','idProduct':'3733','busnum':'1','devnum':'7','manufacturer':'vendor','product':'WS73'}.items():
                (device/name).write_text(value+'\n')
            native='id=0 generation=5 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100'
            attrs={'metadata_valid':'1','runtime_transport':'1','boot_error':'0','native_runtime':native,
                   'controller_information':'version=0201000120 features=01010101010101010101 address=02:73:00:00:00:01 acb=254/5 icb=0/0 bootstrap_credits=0'}
            for name,value in attrs.items():(interface/name).write_text(value+'\n')
            selected=registration('1-2',root)
            self.assertEqual((selected['path'],selected['features'],selected['bus'],selected['device']),('/org/sparklink/slk0_g5','01'*10,1,7))
            with self.assertRaisesRegex(ValueError,'synthetic WS73 fixture'):_registration('1-2',root,True)
            (device/'manufacturer').write_text('OpenSparklink synthetic test\n')
            (device/'product').write_text('WS73 runtime fixture (NO RF)\n')
            with self.assertRaisesRegex(ValueError,'excluded from physical'):registration('1-2',root)
            self.assertEqual(_registration('1-2',root,True)['path'],'/org/sparklink/slk0_g5')
            (device/'manufacturer').write_text('vendor\n');(device/'product').write_text('WS73\n')
            (interface/'native_runtime').write_text(native.replace('controller_error=100','controller_error=0'))
            with self.assertRaises(ValueError):registration('1-2',root)
    def test_control_orchestrator_scopes_are_distinct_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            physical=Run(SimpleNamespace(output=Path(d)/'physical'))
            synthetic=SyntheticControlRun(SimpleNamespace(output=Path(d)/'synthetic'))
            passthrough=PassthroughControlRun(SimpleNamespace(output=Path(d)/'passthrough'))
            self.assertEqual(physical.data['scope'],'physical')
            self.assertEqual(synthetic.data['scope'],'synthetic WS73 USB control support')
            self.assertNotEqual(physical.SUCCESS,synthetic.SUCCESS)
            self.assertNotEqual(passthrough.SUCCESS,physical.SUCCESS)
            self.assertEqual(passthrough.data['hotplug_method'],'QMP_DEVICE_DEL_ADD')
            self.assertIs(passthrough.data['physical_acceptance'],False)
    def test_live_owned_fd_matches_current_device_not_deleted_handle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fd=root/'10/fd';fd.mkdir(parents=True)
            (fd/'3').symlink_to('/dev/bus/usb/001/003 (deleted)')
            self.assertFalse(opened_usb_node(10,'/dev/bus/usb/001/003',root))
            (fd/'4').symlink_to('/dev/bus/usb/001/004')
            self.assertTrue(opened_usb_node(10,'/dev/bus/usb/001/004',root))
            self.assertFalse(opened_usb_node(11,'/dev/bus/usb/001/004',root))
    def test_native_error_sentinel_is_not_a_controller_status(self):
        base='id=0 generation=1 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error='
        self.assertEqual(healthy_native_runtime(base+'100')[2],'1')
        for status in ['0','01','ff','101']:
            with self.subTest(status=status),self.assertRaises(ValueError):healthy_native_runtime(base+status)
    def test_broken_or_retired_native_runtime_is_not_ready(self):
        good='id=0 generation=1 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100'
        for value in [good.replace('broken=0','broken=1'),good.replace('streaming=1','streaming=0'),good.replace('generation=1','generation=0'),good.replace('id=0','id=16')]:
            with self.subTest(value=value),self.assertRaises(ValueError):healthy_native_runtime(value)
    def test_ports_pin_topology_not_transient_address(self):
        p=usb_properties('1-2.1.3',1)
        self.assertEqual((p['hostbus'],p['hostport'],p['port'],p['guest-reset']),(1,'2.1.3','2',False))
        self.assertNotIn('hostaddr',p)
        self.assertEqual((p['vendorid'],p['productid']),(0xffff,0x3733))
        for name in ['guest-reset','guest-resets-all','kernel-driver-detach','host-reset']:
            self.assertIs(p[name],False)
    def test_unpatched_qemu_cannot_enter_physical_passthrough(self):
        # Introspection fixtures only, not evidence about libusb operations.
        old=SimpleNamespace(returncode=0,stdout='  guest-reset=<bool>\n  hostport=<str>\n',stderr='')
        with patch('ws73_target.subprocess.run',return_value=old) as command:
            proof=usb_host_boundary(Path('/fixture/qemu'))
        self.assertFalse(proof['supported'])
        self.assertEqual(command.call_args.args[0],['/fixture/qemu','-device','usb-host,help'])
    def test_host_boundary_introspection_rejects_missing_or_failed_property_list(self):
        names=['kernel-driver-detach','host-reset','host-retry','guest-reset','guest-resets-all','vendorid','productid','hostbus','hostport']
        text=''.join('  '+n+'=<fixture-type>\n' for n in names)
        for result,expected in [(SimpleNamespace(returncode=0,stdout=text,stderr=''),True),
                                (SimpleNamespace(returncode=1,stdout=text,stderr='error'),False),
                                (SimpleNamespace(returncode=0,stdout=text.replace('  host-retry=<fixture-type>\n',''),stderr=''),False),
                                (SimpleNamespace(returncode=0,stdout=text.replace('  host-reset=<fixture-type>\n',''),stderr=''),False)]:
            with patch('ws73_target.subprocess.run',return_value=result):
                self.assertEqual(usb_host_boundary(Path('/fixture/qemu'))['supported'],expected)
    def test_reject_nonphysical_port_names(self):
        for name in ['usb0','1-0','0-1','1-2:1.0','1-2.0','1-2,hostaddr=3','1-2\n']:
            with self.subTest(name=name),self.assertRaises(ValueError):usb_properties(name,0)
    def test_requires_capture_and_export_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config';p.write_text('CONFIG_RUST=y\nCONFIG_SPARKLINK=y\nCONFIG_SPARKLINK_SLE=y\nCONFIG_SPARKLINK_WS73_USB=y\n')
            with self.assertRaisesRegex(ValueError,'USB_MON'):config_required(p)
    def test_board_inputs_are_explicit_raw_exact_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'bsle_custom.bin').write_bytes(bytes(140));(p/'pm_config.bin').write_bytes(bytes(4))
            self.assertEqual(set(board_files(p)),{'bsle_custom.bin','pm_config.bin'})
            (p/'bsle_custom.bin').write_bytes(bytes(139))
            with self.assertRaises(ValueError):board_files(p)
    def test_prepared_artifact_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);image=p/'bzImage';image.write_bytes(b'original');qemu=p/'qemu';qemu.write_bytes(b'program')
            for name in ['kernel.config','initramfs.cpio.gz']:(p/name).write_bytes(b'original')
            (p/'manifest.json').write_text(json.dumps({'status':'PREPARED','physical_acceptance':False,'artifacts':[file_record(p/name) for name in ['bzImage','kernel.config','initramfs.cpio.gz']],'qemu':file_record(qemu)}))
            image.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'artifact changed'):prepared(p)
    def test_manifest_cannot_validate_different_files_from_launched_guest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);old=p/'old';new=p/'new';old.mkdir();new.mkdir();qemu=p/'qemu';qemu.write_bytes(b'program')
            for name in ['bzImage','kernel.config','initramfs.cpio.gz']:(old/name).write_bytes(b'original')
            (new/'manifest.json').write_text(json.dumps({'status':'PREPARED','physical_acceptance':False,'artifacts':[file_record(old/name) for name in ['bzImage','kernel.config','initramfs.cpio.gz']],'qemu':file_record(qemu)}))
            with self.assertRaisesRegex(ValueError,'path differs'):prepared(new)
    def test_success_label_cannot_claim_physical_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'manifest.json').write_text(json.dumps({'status':'PREPARED','physical_acceptance':True}))
            with self.assertRaises(ValueError):prepared(p)


if __name__=='__main__':unittest.main()
