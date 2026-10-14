#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare/run an isolated WS73 development guest; never install on the host.

Environment readiness is not physical North Star acceptance. The explicit
support command uses synthetic USB and cannot produce physical acceptance.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from types import SimpleNamespace

from ws73_north_star import file_record, ordinary_identity
from ws73_capture import check_capture_stats, read_capture
import ws73_vm_native_root as native_vm

USERSPACE = Path(__file__).resolve().parents[1]
# Local workspaces keep both repositories side by side. CI checks out the
# pinned kernel selftests inside its workspace instead of assuming that layout.
LINUX = Path(os.environ.get('SPARKLINK_KERNEL_SOURCE', USERSPACE.parent / 'linux')).resolve()
HERE = Path(__file__).resolve().parent


def lab_module():
    source = LINUX / 'tools/testing/selftests/sparklink/ws73-lab.py'
    spec = importlib.util.spec_from_file_location('ws73_lab', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kernel_fault(text):
    source=LINUX/'tools/testing/selftests/sparklink/qemu_verdict.py'
    spec=importlib.util.spec_from_file_location('ws73_kernel_verdict',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return bool(module.KERNEL_FAULT.search(text))


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def config_required(path, module_profile=False):
    lines = path.read_text().splitlines()
    for name in ['RUST', 'SPARKLINK', 'SPARKLINK_WS73_USB',
                 'USB_MON', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS', 'VIRTIO_PCI']:
        value = 'm' if module_profile and name in ['SPARKLINK_WS73_USB', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS'] else 'y'
        if f'CONFIG_{name}={value}' not in lines:
            raise ValueError(f'CONFIG_{name}={value} required; do not silently omit capture or evidence export')


def board_files(directory):
    result = {}
    for name, size in [('bsle_custom.bin',140), ('pm_config.bin',4)]:
        source = directory / name
        if len(source.read_bytes()) != size:
            raise ValueError(f'{name}: expected exactly {size} raw bytes')
        result[name] = source
    return result


def copy_elf(source, target, root):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    dependencies = subprocess.check_output(['ldd', str(source)], text=True)
    for name in re.findall(r'(?:=>\s+)?(/[^\s()]+)', dependencies):
        p = Path(name)
        if p.is_file():
            dest = root / name.lstrip('/')
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)


def prepare(args):
    ordinary_identity()
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {'version':1, 'scope':'isolated development environment preparation',
                'physical_acceptance':False, 'status':'PREPARING', 'inputs':[],
                'board_qualification':'NOT_ASSERTED', 'started_at':datetime.now(timezone.utc).isoformat()}
    try:
        module_profile = native_vm.enabled(args)
        config_required(args.kernel_build / '.config', module_profile)
        lab = lab_module()
        images = lab.firmware(args)
        board = board_files(args.runtime_config_dir)
        inputs = [args.kernel_build/'arch/x86/boot/bzImage',args.kernel_build/'.config',
                  args.qemu,args.busybox,args.dbus_daemon,args.tcpdump,args.python,
                  USERSPACE/'data/dbus/sparklink.conf',Path(__file__),HERE/'ws73_target_init.sh',
                  HERE/'ws73_vm_native_root.py',
                  HERE/'ws73_discovery_policy_capture.py',
                  HERE/'ws73_managed_queue_support.py',HERE/'ws73_model_hold.py',
                  HERE/'ws73_channel_daemon_crash.py',HERE/'ws73_daemon_channel_fd.py',HERE/'ws73_target_guest.py',HERE/'ws73_north_star.py',HERE/'ws73_capture.py',HERE/'ws73_rf_rounds.py',HERE/'ws73_parallel.py',
                  HERE/'ws73_target_control.py',HERE/'ws73_connection_control.py',HERE/'ws73_connection_objects.py',HERE/'ws73_link_resync.py',HERE/'ws73_acb_transport_probe.py',HERE/'ws73_channel_socket.py',HERE/'ws73_ssap_value.py',HERE/'ws73_ssap_discovery.py',HERE/'ws73_initialization_lifecycle.py',HERE/'ws73_observer_policy.py',HERE/'ws73_daemon_crash.py',
                  HERE/'ws73_target_recovery.py',HERE/'ws73_early_fault.py',
                  HERE/'ws73_event_copy_probe.py',
                  HERE/'ws73_diagnostic_probe.py',
                  HERE/'ws73_diagnostic_cancel.py',HERE/'ws73_diagnostic_hold.py',HERE/'ws73_diagnostic_deadline.py',HERE/'ws73_diagnostic_autonomous.py',HERE/'ws73_active_deadline.py',HERE/'ws73_management_setup.py',HERE/'ws73_management_queued.py',HERE/'ws73_management_queue_ready_peer.py',HERE/'ws73_connection_queued.py',HERE/'ws73_managed_queue_probe.c',HERE/'ws73_management_partial.py',HERE/'ws73_resource_file_gate.py',HERE/'ws73_connected_file_gate.py',HERE/'ws73_channel_grant.py',HERE/'ws73_management_ready_peer.py',HERE/'ws73_host_later_hold.py',HERE/'ws73_management_eviction.py',HERE/'ws73_daemon_hold.py',HERE/'ws73_daemon_removal.py',HERE/'ws73_vm_register_reset.py',HERE/'ws73_register_reset_init.sh',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_event_copy_test.c',
                  LINUX/'tools/testing/selftests/sparklink/controller_event_copy_test.c',
                  LINUX/'tools/testing/selftests/sparklink/genl_registry_test.c',
                  LINUX/'tools/testing/selftests/sparklink/protocol_state_unsupported_test.c',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_diagnostic_result_test.c',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_setup_release_test.c',
                  LINUX/'tools/testing/selftests/sparklink/ssap_removed_uapi_test.c',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_socket_type_test.c',
                  LINUX/'include/uapi/linux/sparklink_ioctl.h',
                  HERE/'ws73_bindings_probe.c',HERE/'ws73_bindings_probe.py',
                  LINUX/'tools/testing/selftests/sparklink/ws73-lab.py',
                  LINUX/'tools/testing/selftests/sparklink/qemu_verdict.py',
                  LINUX/'tools/testing/selftests/sparklink/daemon_radio_guest.sh',
                  *board.values(),*[args.firmware_dir/name for name in images]]
        if getattr(args, 'acb_probe_module', None) is not None:
            if not module_profile: raise ValueError('ACB selftest module requires native VM profile')
            inputs.append(args.acb_probe_module)
        if getattr(args,'native_channel_fd_probe',None) is not None:
            if not module_profile:raise ValueError('daemon fd client requires native VM profile')
            inputs.append(args.native_channel_fd_probe)
        manifest['inputs'] = [file_record(p) for p in inputs]
        source_files = subprocess.check_output(['git','ls-files','crates','bindings/python/sparklink','Cargo.toml','Cargo.lock'],cwd=USERSPACE,text=True).splitlines()
        source_files += subprocess.check_output(['git','ls-files','--others','--exclude-standard','crates','bindings/python/sparklink'],cwd=USERSPACE,text=True).splitlines()
        manifest['userspace_sources'] = [file_record(USERSPACE/p) for p in sorted(set(source_files))]
        manifest['userspace_head'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=USERSPACE,text=True).strip()
        with (output/'build.log').open('w') as log:
            subprocess.run(['cargo','build','--offline','-p','libsparklink','--lib'],cwd=USERSPACE,
                           stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run(['cargo','build','--offline','-p','slkd','-p','slctl','-p','slkconfig',
                            '-p','slkmon','-p','slkdump','--bins','--examples'],cwd=USERSPACE,
                           stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run(['gcc','-std=c11','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror',
                            '-I'+str(USERSPACE/'crates/libsparklink/include'),str(HERE/'ws73_bindings_probe.c'),
                            '-L'+str(USERSPACE/'target/debug'),'-Wl,-rpath,/usr/lib','-l:liblibsparklink.so',
                            '-o',str(output/'native-bindings-probe')],stdout=log,stderr=subprocess.STDOUT,check=True)
        root = output/'root'
        for name in ['bin','usr/bin','dev','proc','sys','etc','tmp','run','evidence','boot']:
            (root/name).mkdir(parents=True,exist_ok=True)
        (root/'tmp').chmod(0o1777)
        shutil.copy2(args.busybox,root/'bin/busybox')
        for name in ['sh','mount','mdev','sleep','poweroff','dmesg','su','id','grep','awk','insmod','uname',
                     'seq','cat','pidof','chmod','mkdir','chown','kill','sync','setsid']:
            (root/'bin'/name).symlink_to('busybox')
        programs = {'dbus-daemon':args.dbus_daemon,'tcpdump':args.tcpdump}
        probe = output/'event-copy-probe'
        compile_probe = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                         str(LINUX/'tools/testing/selftests/sparklink/sparklink_event_copy_test.c'),'-o',str(probe)]
        subprocess.run(compile_probe, check=True)
        manifest['event_copy_probe_compile'] = compile_probe
        programs['event-copy-probe'] = probe
        current_probe = output/'controller-event-copy-probe'
        current_compile = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                           str(LINUX/'tools/testing/selftests/sparklink/controller_event_copy_test.c'),'-o',str(current_probe)]
        subprocess.run(current_compile, check=True)
        manifest['controller_event_copy_compile'] = current_compile
        programs['controller-event-copy-probe'] = current_probe
        registry_probe = output/'genl-registry-probe'
        registry_compile = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                            str(LINUX/'tools/testing/selftests/sparklink/genl_registry_test.c'),'-o',str(registry_probe)]
        subprocess.run(registry_compile, check=True)
        manifest['genl_registry_compile'] = registry_compile
        programs['genl-registry-probe'] = registry_probe
        legacy_probe = output/'protocol-state-probe'
        legacy_compile = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                          str(LINUX/'tools/testing/selftests/sparklink/protocol_state_unsupported_test.c'),'-o',str(legacy_probe)]
        subprocess.run(legacy_compile,check=True)
        manifest['protocol_state_compile'] = legacy_compile
        programs['protocol-state-probe'] = legacy_probe
        diagnostic_probe = output/'diagnostic-result-probe'
        compile_diagnostic = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                              str(LINUX/'tools/testing/selftests/sparklink/sparklink_diagnostic_result_test.c'),
                              '-o',str(diagnostic_probe)]
        subprocess.run(compile_diagnostic, check=True)
        manifest['diagnostic_probe_compile'] = compile_diagnostic
        programs['diagnostic-result-probe'] = diagnostic_probe
        setup_probe = output/'setup-release-probe'
        compile_setup = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                         str(LINUX/'tools/testing/selftests/sparklink/sparklink_setup_release_test.c'),'-o',str(setup_probe)]
        subprocess.run(compile_setup, check=True)
        manifest['setup_release_probe_compile'] = compile_setup
        programs['setup-release-probe'] = setup_probe
        removed_probe = output/'ssap-removed-uapi-probe'
        compile_removed = [os.environ.get('CC','cc'),'-std=c11','-D_POSIX_C_SOURCE=200809L',
                           '-O2','-Wall','-Wextra','-Werror',
                           str(LINUX/'tools/testing/selftests/sparklink/ssap_removed_uapi_test.c'),
                           '-o',str(removed_probe)]
        subprocess.run(compile_removed, check=True)
        manifest['ssap_removed_uapi_probe_compile'] = compile_removed
        programs['ssap-removed-uapi-probe'] = removed_probe
        type_probe = output/'socket-type-probe'
        compile_type = [os.environ.get('CC','cc'),'-std=c11','-D_POSIX_C_SOURCE=200809L',
                        '-O2','-Wall','-Wextra','-Werror',
                        str(LINUX/'tools/testing/selftests/sparklink/sparklink_socket_type_test.c'),
                        '-o',str(type_probe)]
        subprocess.run(compile_type, check=True)
        manifest['socket_type_probe_compile'] = compile_type
        programs['socket-type-probe'] = type_probe
        queued_probe = output/'managed-queue-probe'
        compile_queued = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                          '-iquote'+str(LINUX/'include/uapi/linux'),str(HERE/'ws73_managed_queue_probe.c'),'-o',str(queued_probe)]
        subprocess.run(compile_queued, check=True)
        manifest['managed_queue_probe_compile'] = compile_queued
        programs['managed-queue-probe'] = queued_probe
        programs.update({name:USERSPACE/'target/debug'/name for name in ['slkd','slctl','slkconfig','slkmon','slkdump']})
        programs['bus-policy-probe'] = USERSPACE/'target/debug/examples/bus_policy_probe'
        programs['native-bindings-probe'] = output/'native-bindings-probe'
        shared_library=USERSPACE/'target/debug/liblibsparklink.so'
        manifest['unstripped_programs'] = [file_record(p) for p in [*programs.values(),shared_library]]
        for name, source in programs.items():
            copy_elf(source,root/'bin'/name,root)
            (root/'bin'/name).chmod(0o755)
            subprocess.run(['strip','--strip-debug',str(root/'bin'/name)],check=True)
        copy_elf(shared_library,root/'usr/lib/liblibsparklink.so',root)
        (root/'usr/lib/libsparklink.so').symlink_to('liblibsparklink.so')
        subprocess.run(['strip','--strip-debug',str(root/'usr/lib/liblibsparklink.so')],check=True)
        shutil.copytree(USERSPACE/'bindings/python/sparklink',root/'usr/share/sparklink/python/sparklink',
                        ignore=shutil.ignore_patterns('__pycache__'))
        python = args.python.resolve()
        copy_elf(python,root/'usr/bin'/python.name,root)
        (root/'bin/python3').symlink_to('/usr/bin/'+python.name)
        stdlib = Path(sysconfig.get_paths()['stdlib'])
        # This interpreter and stdlib must belong to the same running Python.
        if python != Path(sys.executable).resolve():
            raise ValueError('--python must be this interpreter; do not mix stdlib ABIs')
        destination = root/str(stdlib).lstrip('/')
        shutil.copytree(stdlib,destination,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests'))
        for extension in (stdlib/'lib-dynload').glob('*.so'):
            copy_elf(extension,destination/'lib-dynload'/extension.name,root)
        share = root/'usr/share/sparklink/tools';share.mkdir(parents=True)
        for name in ['ws73_north_star.py','ws73_capture.py','ws73_rf_rounds.py','ws73_parallel.py','ws73_discovery_policy_capture.py','ws73_target_guest.py','ws73_target_control.py','ws73_connection_control.py','ws73_connection_objects.py','ws73_link_resync.py','ws73_acb_transport_probe.py','ws73_channel_socket.py','ws73_ssap_value.py','ws73_ssap_discovery.py','ws73_initialization_lifecycle.py','ws73_observer_policy.py','ws73_daemon_crash.py','ws73_target_recovery.py','ws73_early_fault.py','ws73_bindings_probe.py','ws73_event_copy_probe.py','ws73_diagnostic_probe.py','ws73_diagnostic_cancel.py','ws73_diagnostic_hold.py','ws73_diagnostic_deadline.py','ws73_diagnostic_autonomous.py','ws73_active_deadline.py','ws73_management_setup.py','ws73_management_queued.py','ws73_management_queue_ready_peer.py','ws73_connection_queued.py','ws73_management_partial.py','ws73_resource_file_gate.py','ws73_connected_file_gate.py','ws73_channel_grant.py','ws73_channel_daemon_crash.py','ws73_daemon_channel_fd.py','ws73_management_ready_peer.py','ws73_host_later_hold.py','ws73_management_eviction.py','ws73_daemon_hold.py','ws73_daemon_removal.py','ws73_model_hold.py','ws73_vm_register_reset.py']:
            shutil.copy2(HERE/name,share/name)
        shutil.copy2(LINUX/'tools/testing/selftests/sparklink/daemon_radio_guest.sh',root/'bin/test-radio')
        shutil.copy2(HERE/'ws73_register_reset_init.sh',root/'bin/rebootstrap-init');(root/'bin/rebootstrap-init').chmod(0o755)
        shutil.copy2(HERE/'ws73_target_init.sh',root/'init');(root/'init').chmod(0o755)
        shutil.copy2(args.kernel_build/'arch/x86/boot/bzImage',root/'boot/bzImage')
        shutil.copy2(root/'boot/bzImage',output/'bzImage')
        shutil.copy2(args.kernel_build/'.config',output/'kernel.config')
        firmware = root/'lib/firmware/sparklink/ws73';firmware.mkdir(parents=True)
        for name,data in images.items(): (firmware/name).write_bytes(data)
        for name,p in board.items(): shutil.copy2(p,firmware/name)
        (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/sh\nws73:x:1000:1002:application:/tmp:/bin/sh\nobserver:x:1001:1001:observer:/tmp:/bin/sh\ncapture:x:1003:1003:capture:/:/bin/sh\nchannel:x:1004:1004:channel-only:/tmp:/bin/sh\n')
        (root/'etc/group').write_text('root:x:0:\nsparklink:x:1000:ws73\nobserver:x:1001:observer\nws73:x:1002:ws73\ncapture:x:1003:\nsparklink-apps:x:1004:channel\n')
        (root/'etc/shadow').write_text('root:!:0:0:99999:7:::\nws73:!:0:0:99999:7:::\nobserver:!:0:0:99999:7:::\ncapture:!:0:0:99999:7:::\n')
        (root/'etc/shadow').chmod(0o600)
        shutil.copy2(USERSPACE/'data/dbus/sparklink.conf',root/'etc/sparklink.conf')
        (root/'etc/dbus.conf').write_text('''<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>system</type><listen>unix:path=/run/slkbus</listen><auth>EXTERNAL</auth>
<policy context="default"><allow user="*"/><allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy>
<include>/etc/sparklink.conf</include></busconfig>''')
        if module_profile:
            native_vm.stage(args, manifest, root, USERSPACE, copy_elf)
            if getattr(args, 'acb_probe_module', None) is not None:
                from ws73_acb_transport_probe import stage_module
                stage_module(args.acb_probe_module, root, manifest)
        if getattr(args,'native_channel_fd_probe',None) is not None:
            probe=args.native_channel_fd_probe.resolve(strict=True)
            before=file_record(probe);copy_elf(probe,root/'bin/ws73-channel-fd-probe',root)
            (root/'bin/ws73-channel-fd-probe').chmod(0o755)
            if file_record(probe)!=before:raise ValueError('fd client changed during staging')
            manifest['native_channel_fd_probe']=before
        manifest['guest_files'] = [file_record(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()]
        archive = output/'initramfs.cpio.gz'
        if module_profile:
            native_vm.pack(args, manifest, root)
        else:
            with (output/'pack.log').open('wb') as log,archive.open('wb') as packed:
                files = subprocess.Popen(['find','.','-print0'],cwd=root,stdout=subprocess.PIPE)
                cpio = subprocess.Popen(['cpio','--null','-o','--format=newc','--owner=0:0'],cwd=root,
                                        stdin=files.stdout,stdout=subprocess.PIPE,stderr=log);files.stdout.close()
                gzip = subprocess.Popen(['gzip','-n'],stdin=cpio.stdout,stdout=packed,stderr=log);cpio.stdout.close()
                if any([files.wait(),cpio.wait(),gzip.wait()]): raise ValueError('packing failed')
        if any(file_record(r['path']) != r for r in manifest['inputs']+manifest['userspace_sources']):raise ValueError('inputs/sources changed during preparation')
        artifact_names = ['bzImage','kernel.config','initramfs.cpio.gz'] + (['root.btrfs'] if module_profile else [])
        manifest['artifacts'] = [file_record(output/name) for name in artifact_names]
        manifest['qemu'] = file_record(args.qemu)
        manifest['status'] = 'PREPARED'
    except Exception as error:
        manifest['status']='FAIL';manifest['error']=str(error)
    finally:
        manifest['finished_at']=datetime.now(timezone.utc).isoformat();write_json(output/'manifest.json',manifest)
    print(manifest['status'],output/'manifest.json')
    return 0 if manifest['status']=='PREPARED' else 1


def prepared(path):
    m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PREPARED' or m.get('physical_acceptance') is not False:raise ValueError('prepared environment manifest required')
    artifacts=m['artifacts']
    expected = {'bzImage','kernel.config','initramfs.cpio.gz'} | ({'root.btrfs'} if 'native_vm' in m else set())
    if len(artifacts)!=len(expected) or {Path(r['path']).name for r in artifacts}!=expected:raise ValueError('exact kernel/config/initramfs/root artifact set required')
    for record in artifacts:
        if Path(record['path']).resolve()!=(path/Path(record['path']).name).resolve():raise ValueError('prepared artifact path differs from actual QEMU input')
    for record in artifacts+[m['qemu']]:
        if file_record(record['path']) != record:raise ValueError('prepared artifact changed: '+record['path'])
    if 'native_vm' in m:
        for record in m['native_vm']['qemu_data']:
            Path(record['path']).resolve().relative_to((path/'qemu-data').resolve())
            if file_record(record['path']) != record:raise ValueError('prepared QEMU data changed: '+record['path'])
    config_required(path/'kernel.config', 'native_vm' in m)
    return m


def usb_properties(port,index):
    if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*(?:\.[1-9][0-9]*)*',port):raise ValueError('explicit physical USB port required')
    bus,path=port.split('-',1)
    return {'driver':'usb-host','id':f'ws73_{index}','bus':'xhci.0','port':str(index+1),
            'hostbus':int(bus),'hostport':path,'vendorid':0xffff,'productid':0x3733,
            'guest-reset':False,'guest-resets-all':False,
            'kernel-driver-detach':False,'host-reset':False}


def usb_host_boundary(qemu):
    """Introspect properties without creating or opening any host USB device."""
    return lab_module().usb_host_boundary(qemu)


def opened_usb_node(pid,node,proc=Path('/proc')):
    """Read only this owned child's live fds; a lock/PID file is insufficient."""
    try:
        for link in (proc/str(pid)/'fd').iterdir():
            try:
                if os.readlink(link)==node:return True
            except FileNotFoundError:pass
    except FileNotFoundError:pass
    return False


def live_runtime_owner(port, pid, inventory):
    """Bind a test pulse to this child's current port after firmware re-enumeration."""
    matches = [row for row in inventory if row.get('path') == port]
    if len(matches) != 1:
        raise ValueError('one current selected host port required')
    row = matches[0]
    bus = usb_properties(port, 0)['hostbus']
    if (type(row.get('bus')) is not int or row['bus'] != bus
            or type(row.get('address')) is not int or not 1 <= row['address'] <= 127
            or row.get('node') != f"/dev/bus/usb/{bus:03}/{row['address']:03}"
            or row.get('writable') is not True
            or row.get('interfaces') not in [[dict(name=port+':1.0', endpoints=5, driver=driver)] for driver in [None, 'usbfs']]
            or not opened_usb_node(pid, row['node'])):
        raise ValueError('current runtime interface and live child USB fd required')
    return json.loads(json.dumps(row))


def verify_recovery_lifecycle(trace, armed_wall_ns, initial_devices):
    """Only proven initial ROM owners may close before the fault pulse."""
    from decimal import Decimal
    if type(armed_wall_ns) is not int or armed_wall_ns <= 0:
        raise ValueError('exact recovery arm time required')
    boot = {(r['bus'], r['address']) for r in initial_devices
            if r['interfaces'] and all(i['endpoints'] == 2 for i in r['interfaces'])}
    seen = set()
    for line in trace.splitlines():
        if not re.search(r'usb_host_(close|reset|open_failure) dev ', line):
            continue
        match = re.fullmatch(r'\d+@(\d+\.\d+):usb_host_(close|reset|open_failure) dev (\d+):(\d+)(?:,.*)?', line)
        if not match:
            raise ValueError('timestamped USB owner lifecycle action required')
        stamp, action, bus, address = match.groups()
        identity = (int(bus), int(address))
        if (action != 'close' or int(Decimal(stamp)*1_000_000_000) >= armed_wall_ns
                or identity not in boot or identity in seen):
            raise ValueError('protocol recovery unexpectedly closed/reset a USB owner')
        seen.add(identity)
    return sorted(seen)


USB_LIFECYCLE_EVENTS = (
    'usb_port_attach', 'usb_port_detach',
    'usb_host_open_started', 'usb_host_open_success', 'usb_host_open_failure',
    'usb_host_close', 'usb_host_claim_interface', 'usb_host_release_interface',
    'usb_host_req_complete', 'usb_host_req_data', 'usb_host_reset',
    'usb_xhci_slot_address', 'usb_xhci_slot_disable',
    'usb_xhci_ep_stop', 'usb_xhci_ep_reset', 'usb_xhci_ep_state',
    'usb_xhci_ep_set_dequeue', 'usb_xhci_ep_disable',
)


def lifecycle_trace(qemu, output):
    """Metadata-only tracing; no control/data payload or host mutation."""
    available = subprocess.check_output([str(qemu), '-trace', 'help'],
                                        stderr=subprocess.STDOUT, text=True).splitlines()
    missing = set(USB_LIFECYCLE_EVENTS) - set(available)
    if missing:
        raise ValueError('QEMU lifecycle trace events missing: ' + ','.join(sorted(missing)))
    events, log = output/'usb-lifecycle.events', output/'usb-lifecycle.log'
    if any(c in str(events) + str(log) for c in [',', '\n']):
        raise ValueError('QEMU trace paths must not contain option delimiters')
    events.write_text('\n'.join(USB_LIFECYCLE_EVENTS)+'\n')
    return ['-msg', 'timestamp=on', '-trace', f'events={events},file={log}']


class HostTimeline:
    """Persist initial/change/final WS73 inventory with observation timestamps.

    Absence is an observation, not a recovery claim. Include unselected WS73s
    to distinguish an owner-local incident from a hub-wide inventory change.
    """
    def __init__(self, path):
        self.path, self.previous, self.sequence = path, None, 0

    def observe(self, inventory, phase='poll'):
        if inventory == self.previous and phase == 'poll':
            return
        record = dict(sequence=self.sequence, phase=phase, wall_ns=time.time_ns(),
                      monotonic_ns=time.monotonic_ns(), devices=inventory)
        with self.path.open('a') as stream:
            stream.write(json.dumps(record, sort_keys=True)+'\n')
            stream.flush()
        self.previous = inventory
        self.sequence += 1


class SerialTimeoutSeal:
    """Cancel ordinary work, then exit only a newly observed ordinary shell.

    Never send Enter to a physical unplug/reinsert prompt. An interrupt may
    leave cleanup running, so a pre-existing prompt cannot authorize exit.
    """
    def __init__(self, transcript):
        text = transcript.decode(errors='replace')
        if 'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0' not in text:
            raise ValueError('environment timeout before ordinary shell readiness; preserve partial capture')
        self.offset = len(transcript)
        self.phase = 'CLOSING' if 'WS73_TARGET_SHELL_CLOSED' in text or 'WS73_TARGET_FINISHED' in text else 'WAITING_ORDINARY_SHELL'
        self.initial_input = b'' if self.phase == 'CLOSING' else b'\x03'

    def feed(self, transcript):
        suffix = transcript[self.offset:].decode(errors='replace').replace('\r', '')
        if 'WS73_TARGET_SHELL_CLOSED' in suffix or 'WS73_TARGET_FINISHED' in suffix:
            self.phase = 'CLOSING'
        if self.phase == 'WAITING_ORDINARY_SHELL' and re.search(r'(?:^|\n)/ \$ (?:\x1b\[6n)?$', suffix):
            self.phase = 'EXIT_SENT'
            # The cancelled application's status remains in run.json. Return
            # success only from the shell to let the supervisor seal capture;
            # the host still records the original environment timeout as FAIL.
            return b'exit 0\n'
        return b''


def validate_channel_death_mode(args, package):
    incompatible=any(isinstance(v,bool) and v and k!='channel_daemon_crash' for k,v in vars(args).items())
    selectors=any(getattr(args,k,None) for k in ['daemon_hold_case','managed_partial_case','managed_connected_case','managed_connected_reply','managed_real_later_step'])
    if args.command!='run' or 'native_vm' not in package or 'native_channel_fd_probe' not in package or incompatible or selectors or getattr(args,'channel_daemon_index',0) not in [0,1]:
        raise ValueError('dedicated actual daemon-channel death native VM required')


def _run(args):
    ordinary_identity()
    output=args.output.resolve()
    support=args.command=='support'
    passthrough=bool(getattr(args,'qmp_hotplug',False))
    recovery=bool(getattr(args,'fault_recovery',False))
    parallel=bool(getattr(args,'parallel_pairs',False))
    early_fault=bool(getattr(args,'early_bootstrap_fault',False))
    if early_fault and (support or passthrough or recovery or parallel or any(getattr(args,n,False) for n in ['connection_verify','channel_socket_verify','diagnostic_verify','managed_partial_case','managed_connected_case','channel_daemon_crash'])):
        raise ValueError('early bootstrap fault requires separate native three-device VM')
    initializer_lifecycle=bool(getattr(args,'initializer_lifecycle',False))
    observer_policy=bool(getattr(args,'observer_policy',False))
    channel_death=bool(getattr(args,'channel_daemon_crash',False))
    channel_death_index=getattr(args,'channel_daemon_index',0)
    daemon_crash=bool(getattr(args,'daemon_crash',False))
    connection_verify=bool(getattr(args,'connection_verify',False))
    acb_probe=bool(getattr(args,'acb_transport_probe',False))
    channel_socket=bool(getattr(args,'channel_socket_verify',False))
    channel_bytes=getattr(args,'channel_socket_bytes',61)
    channel_boundaries=bool(getattr(args,'channel_socket_boundaries',False))
    if type(channel_bytes) is not int or not 29<=channel_bytes<=249 or ((channel_bytes!=61 or channel_boundaries) and not channel_socket):raise ValueError('message size and boundaries require explicit supported socket gate')
    channel_rounds=getattr(args,'channel_socket_rounds',4)
    if type(channel_rounds) is not int or not 1<=channel_rounds<=20 or (channel_rounds!=4 and not channel_socket):raise ValueError('bounded socket rounds require explicit socket gate')
    link_resync=bool(getattr(args,'daemon_link_resync',False))
    if channel_socket and (not connection_verify or acb_probe or link_resync):raise ValueError('ordinary channel socket requires a separate real connection gate without test module')
    if acb_probe and (not connection_verify or link_resync):raise ValueError('ACB selftest requires separate explicit connection gate')
    if link_resync and not connection_verify:raise ValueError('link resync requires explicit ordinary native connection gate')
    connection_advertising=getattr(args,'connection_advertising','fixed-t')
    if connection_advertising!='fixed-t' and not connection_verify:
        raise ValueError('connection advertising contrast requires connection verification')
    if connection_verify and (args.command!='run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['daemon_crash','observer_policy','initializer_lifecycle','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('connection verification requires separate real QMP-hotplug VM')
    if daemon_crash and (args.command != 'run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['observer_policy','initializer_lifecycle','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('daemon crash requires separate real QMP-hotplug native VM')
    if observer_policy and (args.command != 'run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['daemon_crash','initializer_lifecycle','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('observer policy requires separate real QMP-hotplug native VM')

    if initializer_lifecycle and (args.command != 'run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['daemon_crash','observer_policy','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('initializer lifecycle requires separate real QMP-hotplug native VM')
    if parallel and (support or passthrough or recovery or any(getattr(args,k,False) for k in ['hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify'])):
        raise ValueError('four-device parallel RF requires separate real VM without other gates')
    selected_count=3 if early_fault else 4 if parallel else 2
    parallel_offset=getattr(args,'parallel_start_offset_ms',0)
    if type(parallel_offset) is not int or not 0 <= parallel_offset <= 125 or (parallel_offset and not parallel):
        raise ValueError('bounded parallel start offset requires explicit four-device diagnostic gate')
    event_copy=bool(getattr(args,'event_copy_verify',False))
    diagnostic=bool(getattr(args,'diagnostic_verify',False))
    cancellation=bool(getattr(args,'diagnostic_cancel_verify',False))
    deadline_gate=bool(getattr(args,'diagnostic_deadline_verify',False))
    autonomous_gate=bool(getattr(args,'diagnostic_autonomous_verify',False))
    active_close_gate=bool(getattr(args,'active_close_verify',False))
    active_gate=bool(getattr(args,'active_deadline_verify',False)) or active_close_gate
    if active_close_gate and bool(getattr(args,'active_deadline_verify',False)):
        raise ValueError('select one active deadline or last-file-close gate')
    setup_gate=bool(getattr(args,'setup_release_verify',False))
    daemon_remove=bool(getattr(args,'daemon_cancel_remove',False))
    if daemon_remove and (support or not passthrough or recovery or diagnostic or active_gate or setup_gate or getattr(args,'daemon_hold_case',None) is not None or getattr(args,'managed_partial_case',None) is not None or getattr(args,'managed_queue_verify',False)):
        raise ValueError('held daemon cancel/removal requires separate real QMP-hotplug VM')
    daemon_hold=getattr(args,'daemon_hold_case',None)
    if daemon_hold not in [None,'supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission'] or daemon_hold is not None and (not recovery or support or diagnostic or active_gate or getattr(args,'managed_partial_case',None) is not None or getattr(args,'managed_queue_verify',False)):
        raise ValueError('separate real recovery VM for ordinary daemon held cancellation required')
    connected_case=getattr(args,'managed_connected_case',None)
    connected_index=getattr(args,'managed_connected_index',0)
    connected_reply=getattr(args,'managed_connected_reply',None)
    link_snapshot=bool(getattr(args,'managed_link_snapshot',False))
    peer_binding=bool(getattr(args,'managed_peer_binding',False))
    channel_grant=bool(getattr(args,'managed_channel_grant',False))
    channel_scm_rights=bool(getattr(args,'managed_channel_scm_rights',False))
    if channel_scm_rights and not channel_grant:raise ValueError('fd transfer requires standalone channel Grant')
    channel_directions=bool(getattr(args,'managed_channel_directions',False))
    if channel_directions and not channel_grant:raise ValueError('directional test requires standalone channel Grant')
    if channel_grant and (not connected_case or connected_reply or recovery):raise ValueError('channel Grant requires standalone real established File gate without fault injection')
    if peer_binding and (not connected_case or connected_reply):raise ValueError('peer binding requires separate established File gate')
    if link_snapshot and (not connected_case or connected_reply):raise ValueError('link snapshot requires separate established File gate')
    if connected_reply and not connected_case:raise ValueError('actual connection reply hold requires explicit File gate')
    if connected_case and (support or (not recovery and not channel_grant) or not setup_gate or passthrough or parallel or diagnostic or active_gate
            or any(getattr(args,k,False) for k in ['managed_partial_case','managed_queue_verify','daemon_hold_case','connection_verify'])):
        raise ValueError('connected File gate requires separate real recovery/Setup VM')
    if connected_index and not connected_case:raise ValueError('connected role requires explicit File gate')
    partial_case=getattr(args,'managed_partial_case',None)
    partial_gate=partial_case is not None
    partial_domain=getattr(args,'managed_partial_domain','advertising')
    selected_cleanup=bool(getattr(args,'managed_selected_cleanup',False))
    parameter_cleanup=bool(getattr(args,'managed_scan_parameter_cleanup',False))
    ready_peer=bool(getattr(args,'managed_ready_peer',False))
    real_step=getattr(args,'managed_real_later_step',None)
    real_later=real_step is not None
    resource_recreation=bool(getattr(args,'managed_resource_recreate',False))
    ordinary_eviction=bool(getattr(args,'managed_ordinary_eviction',False))
    if resource_recreation and (not partial_gate or partial_domain!='advertising' or not selected_cleanup or not ready_peer or parameter_cleanup or ordinary_eviction or real_step not in [None,1]):
        raise ValueError('resource recreation requires separate real selected advertising/Ready peer gate; only remove or configure step')
    if ordinary_eviction and (not partial_gate or not selected_cleanup or not ready_peer or real_later or parameter_cleanup!=(partial_domain=='scanning')):
        raise ValueError('ordinary eviction requires first actual partial step and Ready peer; scanning parameter cleanup')
    if real_later and (type(real_step) is not int or real_step not in [1,2] or not partial_gate or not selected_cleanup or not ready_peer or parameter_cleanup or partial_domain=='advertising' and real_step!=1):
        raise ValueError('bounded later real partial step with selected Ready peer required')
    if ready_peer and (not partial_gate or not selected_cleanup or partial_domain=='scanning' and not parameter_cleanup and not real_later or getattr(args,'managed_queue_verify',False)):
        raise ValueError('Ready peer requires separate selected real partial gate')
    if parameter_cleanup and (not selected_cleanup or partial_domain!='scanning'):raise ValueError('scan parameter cleanup requires selected scanning partial gate')
    if selected_cleanup and not partial_gate:raise ValueError('selected-domain cleanup requires explicit real partial gate')
    if partial_case not in (None,'release','close','dup') or partial_domain not in ('advertising','scanning'):
        raise ValueError('explicit supported Managed partial case/domain required')
    if partial_gate and (support or not recovery or not setup_gate or diagnostic or active_gate):
        raise ValueError('Managed partial gate requires separate real recovery/Setup VM without other hold gates')
    queued_gate=bool(getattr(args,'managed_queue_verify',False))
    queue_peer=bool(getattr(args,'managed_queue_ready_peer',False))
    queue_connections=bool(getattr(args,'managed_queue_connections',False))
    if queue_connections and not queue_peer:raise ValueError('native queued connections require confirmed-Off Ready peer gate')
    if queue_peer and (not queued_gate or not getattr(args,'managed_queue_confirmed_off',False) or partial_gate):raise ValueError('Ready queue peer requires separate confirmed-Off real queue gate')
    if getattr(args,'managed_queue_confirmed_off',False) and not queued_gate:raise ValueError('confirmed-Off requires explicit Managed queued gate')
    if queued_gate and (support or not recovery or not setup_gate):
        raise ValueError('Managed queued gate requires real recovery VM and Setup attachment gate')
    if setup_gate and (support or (not recovery and not channel_grant)):
        raise ValueError('Setup release requires explicit real fault-recovery VM mode')
    if active_gate and (support or not recovery or diagnostic or cancellation or deadline_gate or autonomous_gate):
        raise ValueError('active retirement requires separate real fault-recovery VM mode, without explicit-release diagnostic modes')
    if autonomous_gate and (support or not recovery or not diagnostic or not cancellation or not deadline_gate):
        raise ValueError('live autonomous gate requires real diagnostic/cancel/deadline/fault-recovery modes')
    if deadline_gate and (support or not recovery or not diagnostic or not cancellation):
        raise ValueError('live deadline gate requires real diagnostic/cancel/fault-recovery modes')
    if cancellation and (support or not recovery or not diagnostic):
        raise ValueError('live cancellation gate requires diagnostic and real fault-recovery VM modes')
    if event_copy and (support or not recovery):
        raise ValueError('live event copy gate requires real fault-recovery VM mode')
    if diagnostic and (support or not recovery):
        raise ValueError('live diagnostic gate requires real fault-recovery VM mode')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    m={'version':1,'scope':'synthetic environment support' if support else 'physical development environment',
       'physical_acceptance':False,'status':'STARTING','started_at':datetime.now(timezone.utc).isoformat(),
       'synthetic_empty_bulk':bool(getattr(args,'empty_bulk',False)),
       'synthetic_hotplug':bool(getattr(args,'hotplug',False)),
       'synthetic_warm':bool(getattr(args,'warm',False))}
    m['runner_inputs']=[file_record(HERE/name) for name in ('ws73_target.py','ws73_vm_native_root.py')]
    m['early_bootstrap_fault_requested']=early_fault
    if early_fault:m['early_bootstrap_verifier']=file_record(HERE/'ws73_early_fault.py')
    m['four_device_parallel_rf']=parallel
    m['parallel_start_offset_ms']=parallel_offset
    if parallel:
        m['scope']='four real WS73 two-pair RF timing contrast' if parallel_offset else 'four real WS73 two-pair RF'
    if parallel:m['parallel_verifier']=file_record(HERE/'ws73_parallel.py')
    m['qmp_guest_hotplug']=passthrough
    m['connection_verify_requested']=connection_verify
    m['live_daemon_link_resync']=link_resync
    m['acb_transport_selftest_requested']=acb_probe
    m['channel_socket_verification_requested']=channel_socket
    m['channel_socket_rounds_requested']=channel_rounds if channel_socket else None
    m['channel_socket_bytes_requested']=channel_bytes if channel_socket else None
    m['channel_socket_boundaries_requested']=channel_boundaries
    m['ordinary_channel_socket_acceptance']=False
    m['channel_info_verification_requested']=channel_socket
    m['ordinary_channel_info_acceptance']=False
    m['ssap_exchange_info_acceptance']=False
    m['ssap_value_acceptance']=False
    m['ssap_discovery_acceptance']=False
    m['connection_advertising_requested']=connection_advertising if connection_verify else None
    m['channel_daemon_crash_requested']=channel_death
    m['channel_daemon_index']=channel_death_index
    if channel_death:m['channel_daemon_verifier']=file_record(HERE/'ws73_channel_daemon_crash.py')
    m['daemon_crash_requested']=daemon_crash
    if daemon_crash:m['daemon_crash_verifier']=file_record(HERE/'ws73_daemon_crash.py')
    m['observer_policy_requested']=observer_policy
    if observer_policy:m['observer_policy_verifier']=file_record(HERE/'ws73_observer_policy.py')
    m['initializer_lifecycle_requested']=initializer_lifecycle
    if initializer_lifecycle:m['initializer_lifecycle_verifier']=file_record(HERE/'ws73_initialization_lifecycle.py')
    m['artificial_guest_transport_fault']=recovery
    m['live_event_copy_requested']=event_copy
    m['live_diagnostic_requested']=diagnostic
    m['live_diagnostic_deadline_requested']=deadline_gate
    m['live_diagnostic_autonomous_requested']=autonomous_gate
    m['live_active_deadline_requested']=active_gate
    m['live_active_close_requested']=active_close_gate
    m['live_managed_resource_recreation']=resource_recreation
    m['live_managed_partial_case']=partial_case
    m['live_managed_partial_domain']=partial_domain if partial_gate else None
    m['live_managed_real_later_step']=real_step
    m['live_managed_ordinary_eviction']=ordinary_eviction
    m['live_daemon_cancel_removal']=daemon_remove
    if daemon_remove:m['daemon_removal_verifier']=file_record(HERE/'ws73_daemon_removal.py')
    m['live_daemon_hold_case']=daemon_hold
    if daemon_hold:m['daemon_hold_verifier']=file_record(HERE/'ws73_daemon_hold.py')
    if ordinary_eviction:m['managed_eviction_verifier']=file_record(HERE/'ws73_management_eviction.py')
    if real_later:m['managed_real_later_verifier']=file_record(HERE/'ws73_host_later_hold.py')
    m['live_managed_ready_peer']=ready_peer
    if ready_peer:m['managed_ready_peer_verifier']=file_record(HERE/'ws73_management_ready_peer.py')
    m['live_managed_selected_cleanup']=selected_cleanup
    m['live_managed_scan_parameter_cleanup']=parameter_cleanup
    m['live_managed_queue_connections']=queue_connections
    m['live_managed_queue_ready_peer']=queue_peer
    if queue_peer:m['managed_queue_ready_peer_verifier']=file_record(HERE/'ws73_management_queue_ready_peer.py')
    m['live_managed_queue_requested']=queued_gate
    m['live_setup_release_requested']=setup_gate
    m['live_connected_file_case']=connected_case
    m['live_connected_file_index']=connected_index if connected_case else None
    m['live_connected_reply_hold']=connected_reply
    m['live_link_snapshot_gate']=link_snapshot
    m['live_peer_binding_gate']=peer_binding
    m['live_channel_grant_gate']=channel_grant
    m['live_channel_scm_rights_gate']=channel_scm_rights
    m['live_channel_directions_gate']=channel_directions
    if channel_grant:m['channel_grant_verifier']=file_record(HERE/'ws73_channel_grant.py')
    if connected_case:m['connected_file_verifier']=file_record(HERE/'ws73_connected_file_gate.py')
    if queued_gate:
        m['managed_queue_verifier']=file_record(HERE/'ws73_management_queued.py')
    if partial_gate:
        m['managed_partial_verifier']=file_record(HERE/'ws73_management_partial.py')
        if resource_recreation:m['managed_resource_verifier']=file_record(HERE/'ws73_resource_file_gate.py')
    if setup_gate:
        m['setup_release_verifier']=file_record(HERE/'ws73_management_setup.py')
    if active_gate:
        m['active_deadline_verifier']=file_record(HERE/'ws73_active_deadline.py')
    process=monitor=channel=None
    timeline=HostTimeline(output/'host-inventory.jsonl')
    try:
        package=prepared(args.prepared.resolve());m['prepared_manifest']=file_record(args.prepared.resolve()/'manifest.json')
        if early_fault and 'native_vm' not in package:raise ValueError('early bootstrap fault requires signed native VM')
        if channel_death:validate_channel_death_mode(args,package)
        if acb_probe and 'acb_probe_module' not in package:raise ValueError('frozen signed ACB selftest module missing')
        if connection_verify and 'native_vm' not in package:
            raise ValueError('connection gate requires actual signed native VM')
        if daemon_crash and 'native_vm' not in package:
            raise ValueError('daemon crash requires qualified native module VM')
        if observer_policy and 'native_vm' not in package:
            raise ValueError('observer policy requires qualified native module VM')
        if initializer_lifecycle and 'native_vm' not in package:
            raise ValueError('initializer lifecycle requires qualified native module VM')
        native_vm.check_discovery_config_gate(package, args)
        if 'discovery_config' in package:
            m['discovery_config'] = package['discovery_config']
            m['custom_policy_rf_acceptance'] = False
            m['default_policy_acceptance'] = False
        if parallel and 'native_vm' not in package:
            raise ValueError('four-device gate requires qualified scratch-root native VM')
        if parallel and 'policy_expectation' not in package:
            raise ValueError('current four-device gate requires frozen policy expectation')
        if 'policy_expectation' in package:
            m['policy_expectation'] = package['policy_expectation']
        if event_copy:
            raise ValueError('legacy read-copy live gate is retired; canonical ControllerEvent copy gate is separate')
        if event_copy and 'native_vm' not in package:
            raise ValueError('live copy gate requires the qualified scratch-root VM profile')
        if setup_gate and ('setup_release_probe_compile' not in package or 'native_vm' not in package):
            raise ValueError('Setup release requires frozen probe and qualified scratch-root VM')
        if queued_gate and ('managed_queue_probe_compile' not in package or 'native_vm' not in package):
            raise ValueError('Managed queue gate requires frozen probe and scratch-root VM')
        if active_gate and 'native_vm' not in package:
            raise ValueError('active retirement requires qualified scratch-root VM')
        if diagnostic:
            raise ValueError('legacy poll-dependent live diagnostic matrix is retired; current Native queries remain available')
        lab=lab_module();devices={d['path']:d for d in lab.inventory()};m['inventory_before']=devices
        timeline.observe(devices, 'initial')
        if not support:
            m['usb_host_boundary']=usb_host_boundary(package['qemu']['path'])
            if not m['usb_host_boundary']['supported']:
                raise ValueError('QEMU lacks required USB host opt-outs; build the pinned patched QEMU before physical passthrough')
            if len(args.ports)!=selected_count or len(set(args.ports))!=selected_count:raise ValueError('exact distinct physical port count required')
            for index,port in enumerate(args.ports):
                usb_properties(port,index)
                if port not in devices or not devices[port]['writable']:raise ValueError(port+': writable WS73 required; no host permission changes')
                if any(i['driver'] for i in devices[port]['interfaces']):raise ValueError(port+': host driver already owns it; no detach')
        if not os.access('/dev/kvm',os.R_OK|os.W_OK):raise ValueError('KVM access required; nested virtualization is unnecessary')
        share=output/'guest-output';share.mkdir(mode=0o700)
        if any(c in str(share) for c in [',','\n']):raise ValueError('QEMU evidence share path must not contain option delimiters')
        with tempfile.TemporaryDirectory(prefix='ws73-target-') as tmp:
            serial=Path(tmp)/'serial.sock';qmp=Path(tmp)/'qmp.sock'
            command=[package['qemu']['path'],'-machine','q35,accel=kvm','-cpu','host','-m','1024M','-smp',('1' if queued_gate else '2'),
                     '-display','none','-monitor','none','-no-reboot','-nic','none',
                     '-chardev',f'socket,id=console,path={serial},server=on,wait=off','-serial','chardev:console',
                     '-qmp',f'unix:{qmp},server=on,wait=off','-kernel',str(args.prepared.resolve()/'bzImage'),
                     '-initrd',str(args.prepared.resolve()/'initramfs.cpio.gz'),
                     '-append','console=ttyS0 loglevel=5 log_buf_len=4M panic=1 oops=panic'+(' ws73.support=1' if support else '')+
                     (' ws73.passthrough=1' if passthrough else '')+
                     (' ws73.parallel=1' if parallel else '')+
                     (f' ws73.parallel_offset={parallel_offset}' if parallel else '')+
                     (' ws73.daemon_remove=1' if daemon_remove else '')+
                     (' ws73.initializer_lifecycle=1' if initializer_lifecycle else '')+
                     (' ws73.observer_policy=1' if observer_policy else '')+
                     (' ws73.daemon_crash=1' if daemon_crash else '')+
                     (f' ws73.connection_verify=1 ws73.connection_advertising={connection_advertising}' if connection_verify else '')+
                     (' ws73.link_resync=1' if link_resync else '')+
                     (' ws73.acb_probe=1' if acb_probe else '')+
                     (' ws73.channel_boundaries=1' if channel_boundaries else '')+
                     (f' ws73.channel_socket=1 ws73.channel_rounds={channel_rounds} ws73.channel_bytes={channel_bytes}' if channel_socket else '')+
                     (' ws73.recovery=1' if recovery else '')+
                     (' ws73.early_bootstrap_fault=1' if early_fault else '')+
                     (' ws73.event_copy=1' if event_copy else '')+
                     (' ws73.diagnostic=1' if diagnostic else '')+
                     (' ws73.diagnostic_cancel=1' if cancellation else '')+
                     (' ws73.diagnostic_deadline=1' if deadline_gate else '')+
                     (' ws73.diagnostic_autonomous=1' if autonomous_gate else '')+
                     (' ws73.active_deadline=1' if active_gate else '')+
                     (' ws73.active_close=1' if active_close_gate else '')+
                     (' ws73.setup_release=1' if setup_gate else '')+
                     (' ws73.managed_queue=1' if queued_gate else '')+
                     (' ws73.managed_queue_confirmed_off=1' if getattr(args,'managed_queue_confirmed_off',False) else '')+
                     (' ws73.managed_queue_ready_peer=1' if queue_peer else '')+
                     (' ws73.managed_queue_connections=1' if queue_connections else '')+
                     (f' ws73.managed_partial=1 ws73.partial_case={partial_case} ws73.partial_domain={partial_domain}' if partial_gate else '')+
                     (' ws73.managed_recreate=1' if resource_recreation else '')+
                     (f' ws73.connected_case={connected_case} ws73.connected_index={connected_index}' if connected_case else '')+
                     (f' ws73.connected_reply={connected_reply}' if connected_reply else '')+
                     (' ws73.link_snapshot=1' if link_snapshot else '')+
                     (' ws73.peer_binding=1' if peer_binding else '')+
                     (' ws73.channel_daemon_crash=1 ws73.channel_daemon_index='+str(channel_death_index) if channel_death else '')+
                     (' ws73.channel_grant=1' if channel_grant else '')+
                     (' ws73.channel_scm_rights=1' if channel_scm_rights else '')+
                     (' ws73.channel_directions=1' if channel_directions else '')+
                     (' ws73.selected_domain_cleanup=1' if selected_cleanup else '')+
                     (' ws73.scan_parameter_cleanup=1' if parameter_cleanup else '')+
                     (' ws73.managed_ready_peer=1' if ready_peer else '')+
                     (' ws73.ordinary_queue_eviction=1' if ordinary_eviction else '')+
                     (f' ws73.daemon_hold={daemon_hold}' if daemon_hold else '')+
                     (f' ws73.real_later_step=1 ws73.partial_step={real_step}' if real_later else '')+
                     (' ws73.empty_bulk=1' if getattr(args,'empty_bulk',False) else '')+
                     (' ws73.hotplug=1' if getattr(args,'hotplug',False) else ''),
                     '-device','qemu-xhci,id=xhci,p2=8,p3=8',
                     '-fsdev',f'local,id=evidence,path={share},security_model=mapped-xattr',
                     '-device','virtio-9p-pci,fsdev=evidence,mount_tag=evidence']
            if not support:
                command += lifecycle_trace(package['qemu']['path'], output)
                # Keep lifecycle diagnostics in the console even when the
                # guest cannot seal dmesg after an environment timeout.
                index=command.index('-append')+1
                command[index]=command[index].replace('loglevel=5', 'loglevel=6')
            if 'native_vm' in package:
                options, append = native_vm.launch(args.prepared.resolve(), output, package)
                command += options
                command[command.index('-append')+1] += append
                m['native_vm'] = package['native_vm']
            m['qemu_args']=command;write_json(output/'manifest.json',m)
            with (output/'qemu-stderr.log').open('wb') as stderr,(output/'console.log').open('wb') as log:
                process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=stderr)
                deadline=time.monotonic()+args.timeout
                while not serial.exists() or not qmp.exists():
                    if process.poll() is not None or time.monotonic()>deadline:raise ValueError('QEMU socket startup failed')
                    time.sleep(0.05)
                channel=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);channel.connect(str(serial));channel.setblocking(False)
                monitor=lab.Qmp(qmp,output/'qmp.jsonl')
                hold=None
                if connected_reply:
                    from ws73_connected_file_gate import ConnectedHoldCoordinator, ConnectedOutcomeCoordinator
                    kind=ConnectedHoldCoordinator if connected_reply=='status' else ConnectedOutcomeCoordinator
                    hold=kind(share,m.setdefault('connected_file_hold',{}),connected_index)
                if partial_gate:
                    from ws73_management_partial import PartialCoordinator
                    if real_later:
                        from ws73_host_later_hold import LaterHostCoordinator
                        hold=LaterHostCoordinator(share,m.setdefault('managed_partial_hold',{}),real_step)
                    else:hold=PartialCoordinator(share,m.setdefault('managed_partial_hold',{}))
                if daemon_remove:
                    from ws73_daemon_removal import RemovalCoordinator
                    hold=RemovalCoordinator(share,m.setdefault('daemon_removal',{}))
                if daemon_hold:
                    from ws73_daemon_hold import DaemonHoldCoordinator
                    hold=DaemonHoldCoordinator(share,m.setdefault('daemon_hold',{}))
                if active_gate:
                    from ws73_active_deadline import ActiveDeadlineCoordinator
                    hold=ActiveDeadlineCoordinator(share,m.setdefault('active_deadline_hold',{}))
                if cancellation:
                    from ws73_diagnostic_hold import HoldCoordinator
                    hold=HoldCoordinator(share,m.setdefault('diagnostic_hold',{}))
                active=0;addresses={port:devices[port]['address'] for port in getattr(args,'ports',[])};transcript=bytearray();support_input=False;hotplug_phase=0
                watcher=lab.ReattachmentWatcher(addresses,m.setdefault('reattach',[]),owned=opened_usb_node)
                timeout_seal=None
                while process.poll() is None:
                    if time.monotonic()>deadline:
                        if timeout_seal is not None:
                            raise ValueError('environment timeout; graceful capture sealing deadline exceeded')
                        if support or passthrough or recovery or parallel or early_fault:
                            raise ValueError('environment timeout; preserve partial console/capture')
                        timeout_seal=SerialTimeoutSeal(transcript)
                        m['graceful_timeout']={'reason':'ENVIRONMENT_TIMEOUT','state':timeout_seal.phase,
                                               'started_wall_ns':time.time_ns(),'grace_seconds':30,
                                               'automatic_hotplug_confirmation':False}
                        if timeout_seal.initial_input:channel.sendall(timeout_seal.initial_input)
                        deadline=time.monotonic()+30
                        write_json(output/'manifest.json',m)
                    readers=[channel]+([] if support or passthrough or recovery or parallel or early_fault or timeout_seal is not None else [sys.stdin])
                    readable,_,_=select.select(readers,[],[],0.1)
                    if channel in readable:
                        data=channel.recv(65536)
                        if data:
                            log.write(data);log.flush();transcript.extend(data);sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
                    if not support and not passthrough and not recovery and not parallel and not channel_grant and not channel_death and not early_fault and timeout_seal is None and sys.stdin in readable:
                        data=os.read(sys.stdin.fileno(),4096)
                        if data:channel.sendall(data)
                        else:raise ValueError('interactive physical environment requires a terminal; no automatic hotplug confirmation')
                    text=transcript.decode(errors='replace')
                    if hold:
                        if hold.phase == 'arm_ready' and (hold.folder/'hold-arm_ready.json').exists():
                            hold.record['host_identity_at_arm'] = live_runtime_owner(
                                args.ports[connected_index if connected_reply else 0], process.pid, lab.inventory())
                        hold.poll(monitor)
                    if recovery and hotplug_phase==0 and 'WS73_TARGET_RECOVERY_INJECT_READY' in text:
                        host_at_arm = live_runtime_owner(args.ports[0], process.pid, lab.inventory())
                        target={'path':'/machine/peripheral/ws73_0'}
                        if monitor.execute('qom-get',{**target,'property':'test-runtime-in-errors'})!=0:
                            raise ValueError('fresh injection counter required')
                        monitor.execute('qom-set',{**target,'property':'test-runtime-in-error-once','value':True})
                        if monitor.execute('qom-get',{**target,'property':'test-runtime-in-error-once'}) is not True:
                            raise ValueError('one-shot fault pulse did not arm')
                        m['fault_injection']={'method':'QMP_GUEST_TRANSPORT_ERROR_ONCE','guest_slot':0,
                                              'armed_wall_ns':time.time_ns(),'host_identity_at_arm':host_at_arm,'physical_acceptance':False,
                                              'automatic_fault_recovery_acceptance':False}
                        channel.sendall(b'recovery-injected\n');hotplug_phase=1
                    if timeout_seal is not None:
                        action=timeout_seal.feed(transcript)
                        if action:
                            channel.sendall(action)
                            m['graceful_timeout']['exit_sent_wall_ns']=time.time_ns()
                        m['graceful_timeout']['state']=timeout_seal.phase
                    if support and not support_input and 'WS73_TARGET_INPUT_READY' in text:
                        channel.sendall(b'target-ordinary-input\n');support_input=True
                    if (support and getattr(args,'hotplug',False)) or passthrough:
                        prefix='WS73_TARGET_PASSTHROUGH_' if passthrough else 'WS73_TARGET_CONTROL_'
                        acknowledgement='passthrough' if passthrough else 'support'
                        if hotplug_phase==0 and prefix+'REMOVE_READY' in text:
                            if daemon_remove:hold.before_remove(monitor)
                            monitor.execute('device_del',{'id':'ws73_0'});monitor.wait_deleted('ws73_0')
                            if daemon_remove:hold.after_remove(monitor)
                            channel.sendall((acknowledgement+'-remove\n').encode());hotplug_phase=1
                        if hotplug_phase==1 and prefix+'READD_READY' in text:
                            props=dict(driver='usb-ws73-test',id='ws73_0',bus='xhci.0',port='1',
                                       **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                       **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {}),
                                       **{'runtime-idle-scan-stop':True}, **({'runtime-warm':True} if getattr(args,'warm',False) else {}))
                            if passthrough:props=usb_properties(args.ports[0],0)
                            monitor.execute('device_add',props)
                            if daemon_remove:hold.after_readd(props)
                            channel.sendall((acknowledgement+'-readd\n').encode());hotplug_phase=2
                    if early_fault:
                        if hotplug_phase==0 and 'WS73_TARGET_EARLY_FAULT_REMOVE_READY' in text:
                            monitor.execute('device_del',{'id':'ws73_2'});monitor.wait_deleted('ws73_2')
                            channel.sendall(b'early-fault-remove\n');hotplug_phase=1
                        if hotplug_phase==1 and 'WS73_TARGET_EARLY_FAULT_READD_READY' in text:
                            monitor.execute('device_add',usb_properties(args.ports[2],2))
                            channel.sendall(b'early-fault-readd\n');hotplug_phase=2
                    peer_metadata = False
                    if setup_gate and active == 1:
                        from ws73_management_setup import metadata_ready
                        peer_metadata = metadata_ready(share)
                    elif active_gate and active == 1:
                        from ws73_active_deadline import metadata_ready
                        peer_metadata = metadata_ready(share)
                    if active<selected_count and (peer_metadata if (setup_gate or active_gate) and active==1 else ('WS73_TARGET_CAPTURE_READY' if active==0 else f'WS73_TARGET_READY: slot={active-1}') in text):
                        props=(dict(driver='usb-ws73-test',id=f'ws73_{active}',bus='xhci.0',port=str(active+1),
                                    **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                    **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {}),
                                       **{'runtime-idle-scan-stop':True}, **({'runtime-warm':True} if getattr(args,'warm',False) else {})) if support else usb_properties(args.ports[active],active))
                        monitor.execute('device_add',props);active+=1
                    if not support:
                        current={d['path']:d for d in lab.inventory()}
                        timeline.observe(current)
                        for index,port in enumerate(args.ports[:active]):
                            if passthrough and hotplug_phase==1 and index==0:continue
                            if early_fault and hotplug_phase==1 and index==2:continue
                            watcher.poll(index,port,current.get(port),process.pid,monitor)
                # Drain bytes already delivered when QEMU powers down.
                channel.setblocking(True);channel.settimeout(1)
                try:
                    while data:=channel.recv(65536):log.write(data);transcript.extend(data)
                except (TimeoutError,ConnectionResetError):pass
                m['qemu_exit']=process.returncode
                text=transcript.decode(errors='replace').replace('\r','')
                # Generic dracut uses terminal control sequences immediately
                # before switch-root output; they are not part of markers.
                text=re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
                text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
                if process.returncode or 'WS73_TARGET_FAILURE:' in text or 'WS73_TARGET_FINISHED' not in text:raise ValueError('guest environment failed')
                if kernel_fault(text+(share/'kernel.log').read_text()):raise ValueError('kernel fault in environment')
                if 'native_vm' in package:
                    marker = 'WS73_TARGET_NATIVE_VM_ROOT: ' + package['native_vm']['release'] + ' NVMe/Btrfs signed-module'
                    if text.splitlines().count(marker) != 1 or text.splitlines().count('WS73_TARGET_NATIVE_VM_TAINT: '+('4096' if acb_probe else '0')) != 1:
                        raise ValueError('native module VM root/signature proof missing')
                    status = (share/'slkd-process-status.txt').read_text() if not channel_grant else ''
                    if not channel_grant and (not re.search(r'^Name:\s+slkd$', status, re.M)
                            or not re.search(r'^Uid:\s+0\s+0\s+0\s+0$', status, re.M)):
                        raise ValueError('native module VM daemon is not root')
                if early_fault:
                    from ws73_early_fault import corroborate as early_corroborate
                    record=json.loads((share/'early-bootstrap-fault/run.json').read_text())
                    if hotplug_phase!=2 or text.count('WS73_TARGET_EARLY_FAULT_PASS')!=1:raise ValueError('complete controlled target-only fault/remove/readd gate required')
                    identities=[*record['healthy_before'],record['failed_usb'],record['replacement']]
                    packets=check_capture_stats((share/'capture-stats.txt').read_text())
                    capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                    if packets!=capture['packet_count']:raise ValueError('sealed capture count mismatch')
                    if file_record(HERE/'ws73_early_fault.py')!=m['early_bootstrap_verifier']:raise ValueError('early fault verifier changed')
                    m['early_bootstrap_corroboration']=early_corroborate(record,capture,share)
                    m['capture_packets']=packets;m['guest_identities']=identities
                    m['status']='REAL_EARLY_BOOTSTRAP_FAULT_ISOLATION_PASS'
                    print(m['status'],output/'manifest.json')
                    return 0
                if channel_death:
                    from ws73_channel_daemon_crash import corroborate as death_corroborate
                    record=json.loads((share/'channel-daemon-crash/control/run.json').read_text())
                    if text.count('WS73_TARGET_DAEMON_CHANNEL_PASS')!=1 or text.count('WS73_TARGET_DAEMON_CHANNEL_FINISHED')!=1 or record['daemon_channel']['index']!=channel_death_index:raise ValueError('explicit completed daemon fd death gate required')
                    identities=record['initial'];packets=check_capture_stats((share/'capture-stats.txt').read_text())
                    capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                    if packets!=capture['packet_count']:raise ValueError('sealed capture count mismatch')
                    if record['fd_probe']['sha256']!=package['native_channel_fd_probe']['sha256']:raise ValueError('actual fd probe differs from staged client')
                    m['channel_daemon_corroboration']=death_corroborate(record,capture)
                    m['capture_packets']=packets;m['guest_identities']=identities
                    if file_record(HERE/'ws73_channel_daemon_crash.py')!=m['channel_daemon_verifier']:raise ValueError('daemon verifier changed during run')
                    m['status']='REAL_DAEMON_CHANNEL_DEATH_PASS'
                    print(m['status'],output/'manifest.json')
                    return 0
                if support and ('WS73_TARGET_SUPPORT: PASS' not in text or 'WS73_TARGET_INPUT_PASS: uid=1000 caps=0 tty=1' not in text):raise ValueError('synthetic environment support/input proof missing')
                if not support and not passthrough and not recovery and not parallel and not channel_grant and 'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0' not in text:raise ValueError('physical environment readiness missing')
                if passthrough and 'WS73_TARGET_PASSTHROUGH_SUPPORT: PASS' not in text:raise ValueError('QMP passthrough proof missing')
                if recovery and (hotplug_phase!=1 or 'WS73_TARGET_RECOVERY_SUPPORT: PASS' not in text):
                    raise ValueError('artificial transport recovery proof missing')
                if parallel and 'WS73_TARGET_PARALLEL_RF: PASS' not in text:raise ValueError('four-device parallel USB proof missing')
                if channel_grant:
                    from ws73_connected_file_gate import verify_records as verify_connected
                    probe=json.loads((share/'connected-file/run.json').read_text())
                    snapshots=verify_connected(probe)
                    identities=[dict(probe['usb'][n],index=n,generation=value.generation,
                        address=':'.join(f'{v:02X}' for v in value.address),path=f'1-{n+1}') for n,value in enumerate(snapshots)]
                else:
                    identities=[json.loads((share/f'ready-{n}.json').read_text()) for n in range(selected_count)]
                if getattr(args,'hotplug',False) or passthrough:
                    if hotplug_phase!=2:raise ValueError('both synthetic hotplug phases required')
                    pattern=r'^WS73_TARGET_PASSTHROUGH_(REMOVE|READD)_READY$' if passthrough else r'^WS73_TARGET_CONTROL_(REMOVE|READD)_READY$'
                    markers=re.findall(pattern,text,re.M)
                    if markers!=['REMOVE','READD']:raise ValueError('missing/duplicate/out-of-order synthetic control confirmations')
                    control=json.loads((share/('application/passthrough-control/run.json' if passthrough else 'application/support-control/run.json')).read_text())
                    identities=[*control['initial'],control['replacement']]
                    if passthrough and initializer_lifecycle != ('initialization_lifecycle' in control):
                        raise ValueError('initializer lifecycle request and control evidence must agree')
                if recovery:
                    control=json.loads((share/'application/recovery-control/run.json').read_text())
                    identities=[*control['initial'],control['replacement']]
                    injection=(output/'qemu-stderr.log').read_text()
                    markers=re.findall(r'WS73_TEST_RUNTIME_IN_ERROR: dev (\d+):(\d+) ep 81 host_status=0 discarded_bytes=(\d+) injected_count=(\d+)',injection)
                    expected=m['fault_injection']['host_identity_at_arm']
                    if len(markers)!=1 or tuple(map(int,markers[0][:2]))!=(expected['bus'],expected['address']) or int(markers[0][2])<=0 or markers[0][3]!='1':
                        raise ValueError('exact one target-only artificial successful-host-transfer injection required')
                    trace=(output/'usb-lifecycle.log').read_text()
                    m['fault_injection']['initial_rom_closes'] = verify_recovery_lifecycle(
                        trace, m['fault_injection']['armed_wall_ns'], [devices[p] for p in args.ports])
                    m['fault_injection']['consumed_marker']=markers[0]
                if channel_grant:
                    if text.count('WS73_TARGET_CHANNEL_GRANT_FINISHED')!=1:raise ValueError('standalone Grant finish proof missing')
                    control={}
                packets=check_capture_stats((share/'capture-stats.txt').read_text())
                capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                if packets!=capture['packet_count']:raise ValueError('sealed capture packet count mismatch')
                m['capture_packets']=packets;m['guest_identities']=identities
                if parallel:
                    from ws73_parallel import corroborate as corroborate_parallel
                    control=json.loads((share/'application/parallel-control/run.json').read_text())
                    if control['second_pair_start_offset_ms']!=parallel_offset:
                        raise ValueError('guest start offset differs from actual requested diagnostic')
                    expectation = control['policy_expectation']
                    if (expectation['data'] != package['policy_expectation']['data']
                            or expectation['file']['sha256'] != package['policy_expectation']['guest_sha256']):
                        raise ValueError('actual parallel policy expectation differs from frozen preparation')
                    m['parallel_corroboration']=corroborate_parallel(control,capture)
                    m['parallel_control']=file_record(share/'application/parallel-control/run.json')
                if daemon_remove:
                    from ws73_daemon_removal import corroborate as corroborate_removal
                    m['daemon_removal']['corroboration']=corroborate_removal(control['daemon_removal'],hold.record,capture,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                    m['live_daemon_removal']=file_record(share/'application/passthrough-control/run.json')
                if passthrough and connection_verify != ('connection_control' in control):
                    raise ValueError('explicit connection request and guest evidence must agree')
                if connection_verify:
                    from ws73_connection_control import corroborate as connection_corroborate
                    if control['connection_control']['advertising_kind']!=connection_advertising:
                        raise ValueError('guest connection posture differs from explicit parent request')
                    m['connection_corroboration']=connection_corroborate(control,capture)
                    if control['connection_control'].get('connection_objects'):
                        from ws73_connection_objects import corroborate as object_corroborate
                        m['connection_object_corroboration']=object_corroborate(control,capture,m['connection_corroboration'])
                    if link_resync != ('link_resync' in control):raise ValueError('explicit link resync request/evidence mismatch')
                    if link_resync:
                        from ws73_link_resync import corroborate as resync_corroborate
                        m['link_resync_corroboration']=resync_corroborate(control,capture)
                if acb_probe != ('acb_transport_probe' in control):raise ValueError('explicit ACB probe request/evidence mismatch')
                if acb_probe:
                    from ws73_acb_transport_probe import corroborate as acb_corroborate
                    m['acb_transport_selftest_corroboration']=acb_corroborate(control,capture,(share/'kernel.log').read_text())
                    m['expected_external_selftest_taint']=4096
                if channel_socket != ('channel_socket' in control):raise ValueError('explicit socket request/evidence mismatch')
                if channel_socket:
                    from ws73_channel_socket import corroborate as channel_corroborate
                    if any(row.get('message_bytes',61)!=channel_bytes or row.get('boundary_check',False)!=channel_boundaries for row in control['channel_socket']):raise ValueError('socket message size or boundary request differs from actual gate')
                    if any(row['rounds']!=channel_rounds for row in control['channel_socket']):raise ValueError('socket round count differs from explicit request')
                    if not all(row.get('channel_info_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires original capability receipts')
                    m['channel_socket_corroboration']=channel_corroborate(control,capture)
                    m['ordinary_channel_info_acceptance']=True
                    if not all(row.get('ssap_exchange_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires real SMTC ExchangeInfo')
                    m['ssap_exchange_info_acceptance']=True
                    if not all(row.get('ssap_value_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires actual SSAP values')
                    m['ssap_value_acceptance']=True
                    if not all(row.get('ssap_read_uuid_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires actual ReadByUUID values')
                    m['ssap_read_uuid_acceptance']=True
                    if not all(row.get('ssap_update_local_rejection_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires unsupported local update capability refusal')
                    m['ssap_local_update_rejection_acceptance']=True
                    if not all(row.get('ssap_discovery_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires actual SSAP discovery')
                    m['ssap_discovery_acceptance']=True
                    m['ordinary_channel_socket_acceptance']=True
                if daemon_crash != (share/'daemon-crash/run.json').exists():
                    raise ValueError('explicit daemon crash request and evidence must agree')
                if daemon_crash:
                    crash_record=json.loads((share/'daemon-crash/run.json').read_text())
                    old_pid=crash_record['phases'][0]['pid']
                    if re.findall(r'^WS73_TARGET_DAEMON_CRASH_EXIT: pid=(\d+) status=(\d+)$',text,re.M)!=[(str(old_pid),'137')]:
                        raise ValueError('actual guest SIGKILL/reap console evidence required')
                    if re.findall(r'^WS73_TARGET_DAEMON_CRASH_PHASE: (\w+)$',text,re.M)!=['before','free','after']:
                        raise ValueError('ordered actual guest crash phases required')
                    from ws73_daemon_crash import corroborate as crash_corroborate
                    m['daemon_crash_corroboration']=crash_corroborate(json.loads((share/'daemon-crash/run.json').read_text()),control,capture)
                if observer_policy != (share/'observer-policy/run.json').exists():
                    raise ValueError('explicit observer policy request and evidence must agree')
                if observer_policy:
                    from ws73_observer_policy import corroborate as observer_corroborate
                    policy_record=json.loads((share/'observer-policy/run.json').read_text())
                    m['observer_policy_corroboration']=observer_corroborate(policy_record,control,capture)
                if initializer_lifecycle:
                    from ws73_initialization_lifecycle import corroborate_wire as initializer_wire
                    m['initializer_lifecycle_corroboration']=initializer_wire(control,capture)
                if setup_gate:
                    from ws73_management_setup import corroborate as corroborate_setup
                    probe=json.loads((share/'setup-release/run.json').read_text())
                    m['setup_release_corroboration']=corroborate_setup(probe,capture)
                    m['live_setup_release']=file_record(share/'setup-release/run.json')
                if connected_case:
                    from ws73_connected_file_gate import corroborate as connected_corroborate
                    probe=json.loads((share/'connected-file/run.json').read_text())
                    if bool(probe.get('channel_grant',{}).get('directional',False))!=channel_directions:raise ValueError('requested directional Grant gate mismatch')
                    if bool(probe.get('channel_grant',{}).get('scm_rights',False))!=channel_scm_rights:raise ValueError('requested SCM_RIGHTS Grant gate mismatch')
                    if bool(probe.get('channel_grant'))!=channel_grant:raise ValueError('requested real channel Grant gate mismatch')
                    if probe['case']!=connected_case or probe['index']!=connected_index or probe.get('reply_hold')!=connected_reply or bool(probe.get('link_snapshot_gate'))!=link_snapshot or bool(probe.get('peer_binding_gate'))!=peer_binding:raise ValueError('connected File request mismatch')
                    m['connected_file_corroboration']=connected_corroborate(probe,capture,hold.record if connected_reply else None,
                        (output/'qemu-stderr.log').read_text() if connected_reply else None,hold.record['host_identity_at_arm'] if connected_reply else None)
                    m['live_connected_file']=file_record(share/'connected-file/run.json')
                if partial_gate:
                    from ws73_management_partial import corroborate as corroborate_partial
                    if resource_recreation:
                        from ws73_resource_file_gate import corroborate as corroborate_partial
                    probe=json.loads((share/'managed-partial/run.json').read_text())
                    if probe.get('selected_domain_cleanup',False) is not selected_cleanup:raise ValueError('actual selected-domain cleanup must match requested gate')
                    if probe.get('real_later_step',False) is not real_later or probe.get('initialization_step',0)!=(real_step if real_later else 0):raise ValueError('actual later selected step mismatch')
                    if probe.get('ordinary_queue_eviction',False) is not ordinary_eviction:raise ValueError('actual ordinary queue gate mismatch')
                    if probe.get('active_ready_peer',False) is not ready_peer:raise ValueError('actual Ready peer must match requested gate')
                    if probe.get('scan_parameter_cleanup',False) is not parameter_cleanup:raise ValueError('actual scan parameter cleanup must match requested gate')
                    m['managed_partial_hold']['corroboration']=corroborate_partial(probe,hold.record,capture,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                    m['live_managed_partial']=file_record(share/'managed-partial/run.json')
                if daemon_hold:
                    from ws73_daemon_hold import corroborate as corroborate_daemon
                    control=json.loads((share/'application/recovery-control/run.json').read_text())
                    record=control['daemon_hold']
                    if record.get('case')!=daemon_hold:raise ValueError('actual daemon held caller case mismatch')
                    m['daemon_hold']['corroboration']=corroborate_daemon(record,hold.record,capture,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                    m['live_daemon_hold']=file_record(share/'application/recovery-control/run.json')
                if queued_gate:
                    from ws73_management_queued import corroborate as corroborate_queued
                    probe=json.loads((share/'managed-queue/run.json').read_text())
                    if probe.get('ready_peer',False) is not queue_peer:raise ValueError('actual Ready queue peer selector mismatch')
                    if probe.get('connection_queue',False) is not queue_connections:raise ValueError('actual native connection queue request mismatch')
                    m['managed_queue_corroboration']=corroborate_queued(probe,capture)
                    m['live_managed_queue']=file_record(share/'managed-queue/run.json')
                if active_gate:
                    from ws73_active_deadline import corroborate
                    probe=json.loads((share/'active-deadline/run.json').read_text())
                    if ('last_file_close' in probe) != active_close_gate:
                        raise ValueError('actual close evidence must match requested gate')
                    m['active_deadline_hold']['corroboration']=corroborate(
                        probe,hold.record,capture,(output/'qemu-stderr.log').read_text(),
                        (share/'kernel.log').read_text(),identities[0],identities[1],hold.record['host_identity_at_arm'])
                    m['live_active_deadline']=file_record(share/'active-deadline/run.json')
                if event_copy:
                    from ws73_event_copy_probe import verify_cases
                    probe=json.loads((share/'application/event-copy/run.json').read_text())
                    if probe.get('status')!='LIVE_EVENT_COPY_PASS' or probe.get('probe_exit')!=0:
                        raise ValueError('live copy probe failure')
                    verify_cases(probe['cases'])
                    if (probe['daemon_before']!=probe['daemon_after'] or
                            probe['daemon_after']!=control['daemon_before'] or
                            probe['bus_before']!=probe['bus_after'] or
                            probe['bus_after']!=control['bus_before']):
                        raise ValueError('copy and RF gates require the same daemon/bus owner')
                    m['live_event_copy']=file_record(share/'application/event-copy/run.json')
                if diagnostic:
                    from ws73_diagnostic_probe import verify_records
                    probe=json.loads((share/'diagnostic/run.json').read_text())
                    if probe.get('status')!='DIAGNOSTIC_RESULT_LIVE_PASS' or probe.get('probe_exit')!=0:
                        raise ValueError('live diagnostic probe failure')
                    if (probe.get('format_version') != (7 if autonomous_gate else 6 if deadline_gate else 5 if cancellation else 4)
                            or probe.get('cancellation_requested',False) is not cancellation
                            or probe.get('deadline_requested',False) is not deadline_gate
                            or probe.get('autonomous_requested',False) is not autonomous_gate
                            or probe.get('admission_copyout_requested') is not True
                            or probe.get('admission_eviction_requested') is not True
                            or probe.get('legacy_poll_copy_requested') is not True):
                        raise ValueError('current live diagnostic admission gate required')
                    verify_records(probe['records'], admission=True, eviction=True, legacy_poll=True,cancellation=cancellation,deadline=deadline_gate,autonomous=autonomous_gate)
                    if cancellation:
                        if not hold or not hold.record['complete'] or probe.get('host_hold_acknowledgements') != hold.record['observations']:
                            raise ValueError('actual host hold and matching guest acknowledgments required')
                        from ws73_diagnostic_hold import corroborate_host_hold
                        from ws73_capture import corroborate_diagnostic
                        _,cancel_proofs=corroborate_diagnostic(control,capture,probe)
                        m['diagnostic_hold']['corroboration']=corroborate_host_hold(
                            hold.record,probe,cancel_proofs,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                    if len(probe['cli_queries'])!=4:
                        raise ValueError('actual diagnostic CLI query gates missing')
                    m['live_diagnostic']=file_record(share/'diagnostic/run.json')
                m['empty_bulk_completions']=len(capture['empty_bulk_completions'])
                if getattr(args,'empty_bulk',False) and not all(any((e['bus'],e['device'])==(r['bus'],r['device']) for e in capture['empty_bulk_completions']) for r in identities):
                    raise ValueError('successful empty bulk completions missing from either selected USB identity')
                if daemon_remove:
                    # Re-read the final serialized record, not the live coordinator:
                    # later qualification must not erase/mutate earlier evidence.
                    from ws73_daemon_removal import verify_sealed_record
                    verify_sealed_record(control['daemon_removal'],m['daemon_removal'],capture,(output/'qemu-stderr.log').read_text())
                m['status']='REAL_CHANNEL_GRANT_PASS' if channel_grant else ('FOUR_DEVICE_PARALLEL_RF_CONTRAST_PASS' if parallel_offset else 'FOUR_DEVICE_PARALLEL_RF_PASS') if parallel else 'FAULT_RECOVERY_SUPPORT_PASS' if recovery else 'PASSTHROUGH_SUPPORT_PASS' if passthrough else 'SUPPORT_PASS' if support else 'ENVIRONMENT_FINISHED'
                if timeout_seal is not None:
                    m['graceful_timeout']['state']='SEALED'
                    m['status']='FAIL'
                    m['error']='environment timeout; capture sealed; physical control not accepted'
        if parallel and file_record(HERE/'ws73_parallel.py')!=m['parallel_verifier']:
            raise ValueError('parallel verifier changed during run')
        prepared(args.prepared.resolve())
        if queue_peer and file_record(HERE/'ws73_management_queue_ready_peer.py')!=m['managed_queue_ready_peer_verifier']:
            raise ValueError('Ready queue peer verifier changed during run')
        if queued_gate and file_record(HERE/'ws73_management_queued.py')!=m['managed_queue_verifier']:
            raise ValueError('Managed queue verifier changed during run')
        if real_later and file_record(HERE/'ws73_host_later_hold.py')!=m['managed_real_later_verifier']:
            raise ValueError('actual later host verifier changed during run')
        if daemon_remove and file_record(HERE/'ws73_daemon_removal.py')!=m['daemon_removal_verifier']:
            raise ValueError('daemon removal verifier changed during run')
        if daemon_hold and file_record(HERE/'ws73_daemon_hold.py')!=m['daemon_hold_verifier']:
            raise ValueError('daemon held verifier changed during run')
        if daemon_crash and file_record(HERE/'ws73_daemon_crash.py')!=m['daemon_crash_verifier']:
            raise ValueError('daemon crash verifier changed during run')
        if observer_policy and file_record(HERE/'ws73_observer_policy.py')!=m['observer_policy_verifier']:
            raise ValueError('observer policy verifier changed during run')
        if initializer_lifecycle and file_record(HERE/'ws73_initialization_lifecycle.py')!=m['initializer_lifecycle_verifier']:
            raise ValueError('initializer lifecycle verifier changed during run')
        if ordinary_eviction and file_record(HERE/'ws73_management_eviction.py')!=m['managed_eviction_verifier']:
            raise ValueError('ordinary queue verifier changed during run')
        if ready_peer and file_record(HERE/'ws73_management_ready_peer.py')!=m['managed_ready_peer_verifier']:
            raise ValueError('Ready peer verifier changed during run')
        if channel_grant and file_record(HERE/'ws73_channel_grant.py')!=m['channel_grant_verifier']:raise ValueError('channel Grant verifier changed during run')
        if connected_case and file_record(HERE/'ws73_connected_file_gate.py')!=m['connected_file_verifier']:
            raise ValueError('connected File verifier changed during run')
        if resource_recreation and file_record(HERE/'ws73_resource_file_gate.py')!=m['managed_resource_verifier']:
            raise ValueError('resource File verifier changed during run')
        if partial_gate and file_record(HERE/'ws73_management_partial.py')!=m['managed_partial_verifier']:
            raise ValueError('Managed partial verifier changed during run')
        if setup_gate and file_record(HERE/'ws73_management_setup.py')!=m['setup_release_verifier']:
            raise ValueError('Setup release verifier changed during run')
        if active_gate and file_record(HERE/'ws73_active_deadline.py')!=m['active_deadline_verifier']:
            raise ValueError('active deadline host verifier changed during run')
        if file_record(args.prepared.resolve()/'manifest.json')!=m['prepared_manifest']:raise ValueError('prepared manifest changed during run')
    except (Exception,KeyboardInterrupt) as error:
        m['status']='FAIL';m['error']=str(error) or type(error).__name__
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if process is not None:m['qemu_exit']=process.returncode
        if monitor:monitor.close()
        if channel:channel.close()
        m['guest_files']=[file_record(p) for p in sorted((output/'guest-output').rglob('*')) if p.is_file() and not p.is_symlink()] if (output/'guest-output').exists() else []
        m['inventory_after']={d['path']:d for d in lab_module().inventory()}
        timeline.observe(m['inventory_after'], 'final')
        m['host_timeline']=file_record(output/'host-inventory.jsonl')
        m['host_lifecycle_files']=[file_record(output/name) for name in
            ['usb-lifecycle.events', 'usb-lifecycle.log'] if (output/name).is_file()]
        if (output/'root.btrfs').is_file():
            m['vm_disk_after'] = file_record(output/'root.btrfs')
        m['finished_at']=datetime.now(timezone.utc).isoformat();write_json(output/'manifest.json',m)
    print(m['status'],output/'manifest.json')
    return 0 if m['status'] in ['REAL_EARLY_BOOTSTRAP_FAULT_ISOLATION_PASS','REAL_CHANNEL_GRANT_PASS','SUPPORT_PASS','PASSTHROUGH_SUPPORT_PASS','FAULT_RECOVERY_SUPPORT_PASS','FOUR_DEVICE_PARALLEL_RF_PASS','FOUR_DEVICE_PARALLEL_RF_CONTRAST_PASS','ENVIRONMENT_FINISHED'] else 1


def run(args):
    # Share the actual flock inode with the existing firmware lab. A lock file
    # alone is never treated as evidence that another process is live.
    lab=lab_module()
    with lab.lab_lock(SimpleNamespace(action='target-'+args.command,build_dir=args.prepared)):
        return _run(args)


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    pack=commands.add_parser('prepare')
    for name in ['kernel-build','qemu','busybox','dbus-daemon','firmware-dir','runtime-config-dir','output']:
        pack.add_argument('--'+name,type=Path,required=True)
    pack.add_argument('--tcpdump',type=Path,default=Path('/usr/bin/tcpdump'))
    pack.add_argument('--python',type=Path,default=Path(sys.executable))
    for name in native_vm.OPTIONS:
        pack.add_argument('--'+name.replace('_','-'),type=Path,
                          help='optional signed module/NVMe scratch-root VM profile; all three options required')
    pack.add_argument('--native-channel-fd-probe',type=Path,help='explicit isolated real D-Bus fd client binary; native VM only')
    pack.add_argument('--acb-probe-module',type=Path,help='explicit signed external selftest; never ordinary socket qualification')
    pack.add_argument('--native-discovery-config', type=Path,
                      help='freeze a private slkd TOML config in the native VM; checked by staged slkd, no RF qualification')
    for name in ['run','support']:
        cmd=commands.add_parser(name);cmd.add_argument('--prepared',type=Path,required=True);cmd.add_argument('--output',type=Path,required=True)
        cmd.add_argument('--timeout',type=float,default=120 if name=='support' else 1800)
        if name=='run':
            cmd.add_argument('--ports',nargs='+',required=True)
            cmd.add_argument('--parallel-pairs',action='store_true',help='four actual radios, two live pairs; per-round match barrier and raw START/OFF overlap proof, no hotplug or injection')
            cmd.add_argument('--parallel-start-offset-ms',type=int,default=0,help='0..125 ms explicit second-pair timing contrast; never replaces the default parallel gate')
            cmd.add_argument('--early-bootstrap-fault',action='store_true',help='separate native three-real-device missing-custom fault, ordinary Core diagnostics and peer business; controlled QMP retry only')
            cmd.add_argument('--daemon-cancel-remove',action='store_true',help='cancel while actual reply held, remove/re-add only that guest owner; requires --qmp-hotplug; excludes physical/automatic recovery')
            cmd.add_argument('--channel-daemon-crash',action='store_true',help='actual slkd SIGKILL with ordinary retained business fd, successor and no USB reset')
            cmd.add_argument('--channel-daemon-index',type=int,choices=[0,1],default=0)
            cmd.add_argument('--daemon-crash',action='store_true',help='actual active-radio SIGKILL/last-File cleanup and successor before native RF22; separate --qmp-hotplug mode')
            cmd.add_argument('--observer-policy',action='store_true',help='actual default observer/control read and denial roles before/after native RF22; separate --qmp-hotplug mode')
            cmd.add_argument('--initializer-lifecycle',action='store_true',help='real initializer withdrawal, eviction and guest-generation gate; separate native --qmp-hotplug mode')
            cmd.add_argument('--daemon-hold-case',choices=['supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission'],help='ordinary D-Bus callers cancel an original successful held reply with same daemon and active peer')
            cmd.add_argument('--managed-ordinary-eviction',action='store_true',help='two SCHED_OTHER ioctl submitters and terminal result eviction under actual held first reply; separate Ready-peer VM gate')
            cmd.add_argument('--managed-partial-case',choices=['release','close','dup'],help='one actual first-step held-reply cleanup case; requires separate Setup/recovery VM')
            cmd.add_argument('--managed-connected-case',choices=['release','close','dup'],help='actual established-link File cleanup before daemon; separate Setup/recovery VM')
            cmd.add_argument('--managed-link-snapshot',action='store_true',help='actual canonical physical table/lifetime/barrier and VFS read errors; established File gate only')
            cmd.add_argument('--managed-peer-binding',action='store_true',help='actual peer/lifetime mismatch rejection without wire commands; established File gate only')
            cmd.add_argument('--managed-connected-reply',choices=['status','outcome'],help='retain actual original Create Status or outcome frame before File withdrawal')
            cmd.add_argument('--managed-channel-scm-rights',action='store_true',help='ordinary receiver gets real channel via SCM_RIGHTS after inherited authority closes')
            cmd.add_argument('--managed-channel-directions',action='store_true',help='real TX-only/RX-only one-way delivery and opposite-action/protected-bind denial')
            cmd.add_argument('--managed-channel-grant',action='store_true',help='real ordinary blocked socket RX across Managed release/final File/dup and successor; separate established File gate')
            cmd.add_argument('--managed-connected-index',type=int,choices=[0,1],default=0,help='actual Create caller in established-link File gate')
            cmd.add_argument('--managed-resource-recreate',action='store_true',help='actual changed advertising set removal/creation File cancellation; requires selected advertising Ready-peer partial gate')
            cmd.add_argument('--managed-partial-domain',choices=['advertising','scanning'],default='advertising')
            cmd.add_argument('--managed-real-later-step',type=int,choices=[1,2],help='real host later frame selector; requires selected partial and Ready peer; adv only step1')
            cmd.add_argument('--managed-ready-peer',action='store_true',help='real Ready Managed scanning peer across target cancellation/Free')
            cmd.add_argument('--managed-selected-cleanup',action='store_true',help='new real first-step gate: untouched Unknown is not Ready; requires --managed-partial-case')
            cmd.add_argument('--managed-scan-parameter-cleanup',action='store_true',help='new scan first-step gate: Unknown remains Setup; requires selected scanning partial gate')
            cmd.add_argument('--managed-queue-connections',action='store_true',help='native queued Create release/last File/dup and privacy, requires confirmed-Off Ready peer queue gate')
            cmd.add_argument('--managed-queue-ready-peer',action='store_true',help='real independently Ready scanner On across never-selected cancellations')
            cmd.add_argument('--managed-queue-confirmed-off',action='store_true',help='complete initialization before full scanning initializer queue cancellation; requires --managed-queue-verify')
            cmd.add_argument('--managed-queue-verify',action='store_true',help='bounded one-vCPU FIFO real queued-policy cancellation; requires Setup and recovery gates; not ordinary concurrency acceptance')
            cmd.add_argument('--setup-release-verify',action='store_true',help='pre-daemon untouched Setup release/last-fd/dup gate; requires real fault-recovery scratch VM')
            cmd.add_argument('--event-copy-verify',action='store_true',help='opt-in live VFS usercopy gate before real recovery/RF; requires --fault-recovery')
            cmd.add_argument('--active-deadline-verify',action='store_true',help='separate pre-daemon real IN81 timeout/abort gate; requires real fault-recovery and excludes explicit-release diagnostic modes')
            cmd.add_argument('--active-close-verify',action='store_true',help='actual held IN81 original/last dup close and bounded original-deadline retirement; requires separate real fault-recovery VM')
            cmd.add_argument('--diagnostic-verify',action='store_true',help='opt-in live diagnostic owner/CAP/copy/retirement and metadata CLI gate; requires --fault-recovery')
            cmd.add_argument('--diagnostic-autonomous-verify',action='store_true',help='queued expiry already counted before first result after a passive800ms window; requires all diagnostic/cancel/deadline/fault-recovery gates')
            cmd.add_argument('--diagnostic-deadline-verify',action='store_true',help='100ms queued expiry with continuous same-ID retries; requires --diagnostic-cancel-verify and real fault-recovery mode')
            cmd.add_argument('--diagnostic-cancel-verify',action='store_true',help='hold one real IN81 to test active/queued cancel and late reply; requires --diagnostic-verify and --fault-recovery')
            cmd.add_argument('--daemon-link-resync',action='store_true',help='actual VM subscriber pause, real event ring overflow and canonical resync; requires connection verification')
            cmd.add_argument('--channel-socket-bytes',type=int,default=61,help='application message size 29..249 for current basic channel')
            cmd.add_argument('--channel-socket-boundaries',action='store_true',help='require original EMSGSIZE and no USB traffic for oversized messages')
            cmd.add_argument('--channel-socket-rounds',type=int,choices=range(1,21),default=4,help='bounded application rounds per connection role')
            cmd.add_argument('--channel-socket-verify',action='store_true',help='ordinary dual application real channel round trips and CMTC, without test module')
            cmd.add_argument('--acb-transport-probe',action='store_true',help='explicit signed external-module real ACB transport probe; excludes ordinary socket acceptance')
            cmd.add_argument('--connection-verify',action='store_true',help='real typed Connect/Disconnect plus raw outcomes; requires separate --qmp-hotplug VM')
            cmd.add_argument('--connection-advertising',choices=['fixed-t','negotiable-t'],default='fixed-t',help='explicit announcement contrast for --connection-verify')
            modes=cmd.add_mutually_exclusive_group()
            modes.add_argument('--qmp-hotplug',action='store_true',help='real RF with QMP guest-only disconnect/reconnect; never physical unplug or automatic recovery acceptance')
            modes.add_argument('--fault-recovery',action='store_true',help='one opt-in artificial guest bulk IN81 error with real radios; never natural-fault or physical unplug acceptance')
        else:
            cmd.add_argument('--empty-bulk',action='store_true',help='inject successful zero-length bulk IN before synthetic runtime replies; never a physical option')
            cmd.add_argument('--hotplug',action='store_true',help='run the full control orchestrator with explicitly synthetic USB removal/replug; never physical acceptance')
            cmd.add_argument('--warm',action='store_true',help='synthetic one-shot BSP already consumed; require warm restore')
    args=parser.parse_args()
    if not math.isfinite(getattr(args,'timeout',1)) or getattr(args,'timeout',1)<=0:parser.error('timeout must be finite and positive')
    return prepare(args) if args.command=='prepare' else run(args)


if __name__=='__main__':raise SystemExit(main())
