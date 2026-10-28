# SPDX-License-Identifier: GPL-2.0-only
import ast
import copy
from contextlib import redirect_stdout
import io
import json
import errno
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_target import board_files, config_required, opened_usb_node, prepared, usb_host_boundary, usb_properties, HostTimeline, SerialTimeoutSeal, lifecycle_trace, USB_LIFECYCLE_EVENTS, live_runtime_owner, verify_recovery_lifecycle
from ws73_north_star import _registration, file_record, healthy_native_runtime, registration, Run
from ws73_target_control import SyntheticControlRun, PassthroughControlRun
from types import SimpleNamespace
import ws73_target_guest as guest


class TargetEnvironment(unittest.TestCase):
    def test_dedicated_and_ordinary_hcc_receipts_bind_exact_gate_registration(self):
        from ws73_lab_resources import hcc_profile_checks
        rows=[dict(port=f'1-{n+1}',index=n,generation=n+7,bus=1,device=n+2,address=str(n),
                   hcc_chip=dict(raw=f'source=HCC_GET_CHIP_TYPE model=WS73{model} model_id={0 if model=="U" else 2} bus=USB bus_id=0'),
                   input_profile={'fixture':'input-plan-independent-final-gate'})for n,model in enumerate(['U','E'])]
        ports=['1-1.1.1','1-2.1.1'];models=['U','E']
        checks=hcc_profile_checks(ports,models,rows,rows)
        self.assertEqual([v['model']for v in checks],models)
        self.assertEqual([v['host_port']for v in checks],ports)
        for key in ['port','index','generation','bus','device','address']:
            changed=copy.deepcopy(rows);changed[0][key]='wrong'
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'gate identity'):
                hcc_profile_checks(ports,models,changed,rows)
        with self.assertRaisesRegex(ValueError,'one HCC'):
            hcc_profile_checks(ports,models,rows[:1],rows)
        with self.assertRaisesRegex(ValueError,'model/bus'):
            hcc_profile_checks(ports,['E','E'],rows,rows)
        changed=copy.deepcopy(rows);del changed[0]['input_profile']
        with self.assertRaises(KeyError):hcc_profile_checks(ports,models,changed,rows)

    def test_runtime_owner_uses_live_port_not_pre_upload_address(self):
        row=dict(path='1-2.1.4',bus=1,address=124,node='/dev/bus/usb/001/124',writable=True,
                 interfaces=[dict(name='1-2.1.4:1.0',endpoints=5,driver=None)])
        with patch('ws73_target.opened_usb_node',return_value=True) as owned:
            result=live_runtime_owner('1-2.1.4',99,[row]);owned.assert_called_once_with(99,row['node'])
        self.assertEqual(result,row);result['interfaces'][0]['endpoints']=2;self.assertEqual(row['interfaces'][0]['endpoints'],5)
        claimed=dict(row,interfaces=[dict(name='1-2.1.4:1.0',endpoints=5,driver='usbfs')])
        with patch('ws73_target.opened_usb_node',return_value=True):self.assertEqual(live_runtime_owner('1-2.1.4',99,[claimed]),claimed)
        with patch('ws73_target.opened_usb_node',return_value=False),self.assertRaises(ValueError):live_runtime_owner('1-2.1.4',99,[claimed])
        for changes in [dict(address=True),dict(bus=True),dict(node='/dev/bus/usb/001/123'),dict(writable=False),
                        dict(interfaces=[dict(name='1-2.1.4:1.0',endpoints=2,driver=None)]),
                        dict(interfaces=[dict(name='1-2.1.4:1.0',endpoints=5,driver='other')])]:
            with self.subTest(changes=changes),patch('ws73_target.opened_usb_node',return_value=True),self.assertRaises(ValueError):
                live_runtime_owner('1-2.1.4',99,[dict(row,**changes)])
        for rows in [[],[row,row]]:
            with self.assertRaises(ValueError):live_runtime_owner('1-2.1.4',99,rows)
        with patch('ws73_target.opened_usb_node',return_value=False),self.assertRaises(ValueError):
            live_runtime_owner('1-2.1.4',99,[row])

    def test_recovery_lifecycle_allows_only_original_rom_close_before_arm(self):
        boot=dict(bus=1,address=123,interfaces=[dict(endpoints=2)])
        warm=dict(bus=1,address=124,interfaces=[dict(endpoints=5)])
        self.assertEqual(verify_recovery_lifecycle('42@100.999999:usb_host_close dev 1:123',101_000_000_000,[boot,warm]),[(1,123)])
        for line in ['42@101.000000:usb_host_close dev 1:123',
                     '42@102.000000:usb_host_close dev 1:124',
                     '42@100.000000:usb_host_close dev 1:124',
                     '42@100.000000:usb_host_reset dev 1:123',
                     '42@100.000000:usb_host_open_failure dev 1:123, err -1',
                     'usb_host_close dev 1:123',
                     '42@100.000000:usb_host_close dev 1:123\n42@100.000001:usb_host_close dev 1:123']:
            with self.subTest(line=line),self.assertRaises(ValueError):verify_recovery_lifecycle(line,101_000_000_000,[boot,warm])
        for bad in [True,0,-1]:
            with self.assertRaises(ValueError):verify_recovery_lifecycle('',bad,[boot])

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
    def test_adopted_pending_identity_matches_healthy_runtime(self):
        base='id=0 generation=3 streaming=1 broken=0 unsupported=0 last_event=0000 controller_error=100'
        tail=' reserved=0 pending_id=0 pending_generation=3 core_pending_ret=-2 core_phase=0 core_error=0'
        self.assertEqual(healthy_native_runtime(base+tail)[2],'3')
        for bad in [tail.replace('reserved=0','reserved=1'),tail.replace('pending_id=0','pending_id=1'),tail.replace('pending_generation=3','pending_generation=2'),tail.replace('core_error=0','core_error=-5')]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):healthy_native_runtime(base+bad)
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
            p=Path(d)/'config';p.write_text('CONFIG_RUST=y\nCONFIG_SPARKLINK=y\nCONFIG_SPARKLINK_WS73_USB=y\n')
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


class ProviderDeadlineRunnerWiring(unittest.TestCase):
    """CLI/source/boot integration only; no daemon, VM or controller starts.

    Artifact observations are fixtures in the pre-launch refusal test. They do
    not manufacture a successful VM, wire reply, timeout or qualification.
    """
    tools = Path(__file__).resolve().parents[1]
    dependencies = ('--ssap-owned-verify', '--ssap-read-provider-verify',
                    '--ssap-provider-owner-exit-verify')

    def test_actual_host_and_control_help_expose_explicit_deadline(self):
        for command in ([sys.executable, str(self.tools/'ws73_target.py'), 'run', '--help'],
                        [sys.executable, str(self.tools/'ws73_target_control.py'), '--help']):
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            for flag in (*self.dependencies, '--ssap-provider-deadline-verify'):
                self.assertIn(flag, result.stdout)

    def test_actual_control_refuses_missing_baseline_before_execution(self):
        import ws73_target_control as control
        argv = ['ws73_target_control.py', '--slctl', '/bin/slctl', '--slkd-pid', '1',
                '--output', '/unused', '--passthrough', '--connection-verify',
                '--channel-socket-verify', '--ssap-provider-deadline-verify',
                *self.dependencies]
        for missing in self.dependencies:
            with self.subTest(missing=missing), patch.object(sys, 'argv', [v for v in argv if v != missing]), \
                 patch.object(control, 'ConnectionControlRun', side_effect=AssertionError('must not execute')) as launch, \
                 patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as failure:
                control.main()
            self.assertEqual(failure.exception.code, 2)
            launch.assert_not_called()

    def test_actual_host_refuses_missing_owner_exit_before_output(self):
        import ws73_target as host
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'must-not-exist'
            args = SimpleNamespace(command='run', output=output, qmp_hotplug=True,
                connection_verify=True, channel_socket_verify=True, channel_socket_rounds=4,
                channel_socket_bytes=61, ssap_owned_verify=True, ssap_read_provider_verify=True,
                ssap_provider_owner_exit_verify=False, ssap_provider_deadline_verify=True)
            with patch.object(host, 'ordinary_identity'), \
                 patch.object(host.subprocess, 'Popen', side_effect=AssertionError('must not launch')) as launch, \
                 self.assertRaisesRegex(ValueError, '(?i)(provider|owner|deadline)'):
                host._run(args)
            launch.assert_not_called()
            self.assertFalse(output.exists())

    def test_init_runs_real_boot_parser_for_exact_dependency_tokens(self):
        source = (self.tools/'ws73_target_init.sh').read_text()
        line = next(line for line in source.splitlines() if 'provider_deadline_arg=$(' in line)
        code = re.search(r"-c '([^']+)'", line).group(1)
        self.assertIn('from ws73_ssap_provider_deadline import boot_requested', code)
        self.assertIn('|| fail provider-deadline-selector', line)
        baseline = ['ws73.ssap_owned=1', 'ws73.ssap_read_provider=1', 'ws73.ssap_provider_owner_exit=1']
        token = 'ws73.ssap_provider_deadline=1'
        environment = dict(os.environ, PYTHONPATH=str(self.tools))
        for tokens, expected in (([], ''), (baseline, ''),
                                 (baseline+[token], '--ssap-provider-deadline-verify')):
            result = subprocess.run([sys.executable, '-c', code, *tokens], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)
        bad = [[token], baseline[:-1]+[token], baseline+[token, token],
               baseline+['ws73.ssap_provider_deadline'], baseline+['ws73.ssap_provider_deadline='],
               baseline+['ws73.ssap_provider_deadline=0'], baseline+['ws73.ssap_provider_deadline=2']]
        for tokens in bad:
            with self.subTest(tokens=tokens):
                result = subprocess.run([sys.executable, '-c', code, *tokens], env=environment,
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_current_source_staging_and_verdict_have_every_deadline_call(self):
        # Static integration coverage complements the actual parser/refusal
        # cases; it is not runtime or hardware evidence.
        from test_ws73_ssap_command_policy_wiring import function, calls
        filename = 'ws73_ssap_provider_deadline.py'
        for function_name, count in (('prepare_from_carrier', 1), ('prepare_locked', 2)):
            node = function(function_name, 'ws73_target.py')
            literals = [n for n in ast.walk(node) if isinstance(n, ast.Constant) and n.value == filename]
            self.assertEqual(len(literals), count)
        host = function('_run', 'ws73_target.py')
        for name in ('provider_deadline_requested', 'provider_deadline_inputs',
                     'provider_deadline_rows', 'provider_deadline_summary'):
            self.assertEqual(len(calls(host, name)), 1, name)
        self.assertEqual(len(calls(function('run_exit_code', 'ws73_target.py'),
                                   'valid_provider_deadline_manifest')), 1)
        guest = function('verify_passthrough', 'ws73_target_guest.py')
        for name in ('provider_deadline_boot', 'provider_deadline_rows'):
            self.assertEqual(len(calls(guest, name)), 1, name)
        body = ast.unparse(host)
        for field in ('ssap_provider_deadline_requested', 'ssap_provider_deadline_acceptance',
                      'ssap_provider_deadline_version', 'ssap_provider_deadline_verifier',
                      'ssap_provider_deadline_tools'):
            self.assertIn(field, body)
        self.assertIn('ws73.ssap_provider_deadline=1', body)

    def test_actual_host_checks_deadline_source_before_any_vm_launch(self):
        import ws73_target as host
        import ws73_ssap_provider_deadline as gate
        names = list(self.tools.glob('*.py'))+[self.tools/'ws73_target_init.sh']
        original = dict(inputs=[file_record(p) for p in names],
            application_client_tools=dict(sources=[file_record(self.tools/name) for name in
                ('testing/application_client/client.c', 'testing/application_client/client.py')]),
            ssap_exchange_contract_version=False)
        sources = ('ws73_ssap_provider_deadline.py', 'ws73_ssap_command_deadline.py',
                   'ws73_ssap_command_policy.py')
        cases = [(name, fault) for name in sources for fault in ('missing', 'stale')]
        for name, fault in [*cases, (None, 'unchanged')]:
            package = copy.deepcopy(original)
            if fault == 'missing':
                package['inputs'] = [item for item in package['inputs']
                                     if Path(item['path']).name != name]
            elif fault == 'stale':
                next(item for item in package['inputs'] if Path(item['path']).name ==
                     name)['sha256'] = '0'*64
            with self.subTest(source=name, fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); prepared = root/'prepared'; prepared.mkdir()
                (prepared/'manifest.json').write_text(json.dumps(package)); output = root/'output'
                argv = ['ws73_target.py', 'run', '--prepared', str(prepared), '--output', str(output),
                        '--ports', '1-1.1.1', '1-1.1.2', '--qmp-hotplug',
                        '--firmware-evidence', 'runtime-observation', '--connection-verify',
                        '--connection-advertising', 'negotiable-t', '--channel-socket-verify',
                        *self.dependencies, '--ssap-provider-deadline-verify']
                with patch.object(sys, 'argv', argv), patch.object(host, 'run', side_effect=lambda args: args):
                    args = host.main()
                with redirect_stdout(io.StringIO()), patch.object(host, 'ordinary_identity'), \
                     patch.object(host, 'prepared', return_value=package), \
                     patch.object(host, 'lab_module', return_value=SimpleNamespace(inventory=lambda: [])), \
                     patch.object(gate, 'validate_inputs', wraps=gate.validate_inputs) as checked, \
                     patch.object(host.subprocess, 'Popen', side_effect=AssertionError('must not launch')) as launch:
                    self.assertEqual(host._run(args), 1)
                checked.assert_called_once_with(package); launch.assert_not_called()
                record = json.loads((output/'manifest.json').read_text())
                if fault == 'unchanged':
                    self.assertIn('explicit known SSAP exchange artifact contract required', record['error'])
                else:
                    self.assertRegex(record['error'], '(?i)provider.*deadline|deadline.*provider')
                    self.assertIn(name, record['error'])
                self.assertIs(record['ssap_provider_deadline_requested'], True)
                # The live runner now requires SDK v2; historical CLI v1 remains reader-only.
                self.assertEqual(record['ssap_provider_deadline_version'], 2)
                self.assertEqual(record['ssap_provider_deadline_verifier'], file_record(self.tools/'ws73_ssap_provider_deadline.py'))
                self.assertIs(record['ssap_provider_deadline_acceptance'], False)
                self.assertIs(record['physical_acceptance'], False)
                self.assertNotIn('qemu_args', record)


if __name__=='__main__':unittest.main()
