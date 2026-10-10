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
    for name in ['RUST', 'SPARKLINK', 'SPARKLINK_SLE', 'SPARKLINK_WS73_USB',
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
                  HERE/'ws73_target_guest.py',HERE/'ws73_north_star.py',HERE/'ws73_capture.py',
                  HERE/'ws73_target_control.py',
                  HERE/'ws73_target_recovery.py',
                  HERE/'ws73_event_copy_probe.py',
                  HERE/'ws73_diagnostic_probe.py',
                  HERE/'ws73_diagnostic_cancel.py',HERE/'ws73_diagnostic_hold.py',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_event_copy_test.c',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_diagnostic_result_test.c',
                  LINUX/'include/uapi/linux/sparklink_ioctl.h',
                  HERE/'ws73_bindings_probe.c',HERE/'ws73_bindings_probe.py',
                  LINUX/'tools/testing/selftests/sparklink/ws73-lab.py',
                  LINUX/'tools/testing/selftests/sparklink/qemu_verdict.py',
                  LINUX/'tools/testing/selftests/sparklink/daemon_radio_guest.sh',
                  *board.values(),*[args.firmware_dir/name for name in images]]
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
        diagnostic_probe = output/'diagnostic-result-probe'
        compile_diagnostic = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                              str(LINUX/'tools/testing/selftests/sparklink/sparklink_diagnostic_result_test.c'),
                              '-o',str(diagnostic_probe)]
        subprocess.run(compile_diagnostic, check=True)
        manifest['diagnostic_probe_compile'] = compile_diagnostic
        programs['diagnostic-result-probe'] = diagnostic_probe
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
        for name in ['ws73_north_star.py','ws73_capture.py','ws73_target_guest.py','ws73_target_control.py','ws73_target_recovery.py','ws73_bindings_probe.py','ws73_event_copy_probe.py','ws73_diagnostic_probe.py','ws73_diagnostic_cancel.py','ws73_diagnostic_hold.py']:
            shutil.copy2(HERE/name,share/name)
        shutil.copy2(LINUX/'tools/testing/selftests/sparklink/daemon_radio_guest.sh',root/'bin/test-radio')
        shutil.copy2(HERE/'ws73_target_init.sh',root/'init');(root/'init').chmod(0o755)
        shutil.copy2(args.kernel_build/'arch/x86/boot/bzImage',root/'boot/bzImage')
        shutil.copy2(root/'boot/bzImage',output/'bzImage')
        shutil.copy2(args.kernel_build/'.config',output/'kernel.config')
        firmware = root/'lib/firmware/sparklink/ws73';firmware.mkdir(parents=True)
        for name,data in images.items(): (firmware/name).write_bytes(data)
        for name,p in board.items(): shutil.copy2(p,firmware/name)
        (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/sh\nws73:x:1000:1002:application:/tmp:/bin/sh\nobserver:x:1001:1001:observer:/tmp:/bin/sh\ncapture:x:1003:1003:capture:/:/bin/sh\n')
        (root/'etc/group').write_text('root:x:0:\nsparklink:x:1000:ws73\nobserver:x:1001:observer\nws73:x:1002:ws73\ncapture:x:1003:\n')
        (root/'etc/shadow').write_text('root:!:0:0:99999:7:::\nws73:!:0:0:99999:7:::\nobserver:!:0:0:99999:7:::\ncapture:!:0:0:99999:7:::\n')
        (root/'etc/shadow').chmod(0o600)
        shutil.copy2(USERSPACE/'data/dbus/sparklink.conf',root/'etc/sparklink.conf')
        (root/'etc/dbus.conf').write_text('''<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>system</type><listen>unix:path=/run/slkbus</listen><auth>EXTERNAL</auth>
<policy context="default"><allow user="*"/><allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy>
<include>/etc/sparklink.conf</include></busconfig>''')
        if module_profile:
            native_vm.stage(args, manifest, root, USERSPACE, copy_elf)
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


def _run(args):
    ordinary_identity()
    output=args.output.resolve()
    support=args.command=='support'
    passthrough=bool(getattr(args,'qmp_hotplug',False))
    recovery=bool(getattr(args,'fault_recovery',False))
    event_copy=bool(getattr(args,'event_copy_verify',False))
    diagnostic=bool(getattr(args,'diagnostic_verify',False))
    cancellation=bool(getattr(args,'diagnostic_cancel_verify',False))
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
    m['qmp_guest_hotplug']=passthrough
    m['artificial_guest_transport_fault']=recovery
    m['live_event_copy_requested']=event_copy
    m['live_diagnostic_requested']=diagnostic
    process=monitor=channel=None
    timeline=HostTimeline(output/'host-inventory.jsonl')
    try:
        package=prepared(args.prepared.resolve());m['prepared_manifest']=file_record(args.prepared.resolve()/'manifest.json')
        if event_copy and 'event_copy_probe_compile' not in package:
            raise ValueError('prepared VM does not contain the frozen live copy probe')
        if event_copy and 'native_vm' not in package:
            raise ValueError('live copy gate requires the qualified scratch-root VM profile')
        if diagnostic and ('diagnostic_probe_compile' not in package or 'native_vm' not in package):
            raise ValueError('live diagnostic gate requires frozen probe and qualified scratch-root VM')
        lab=lab_module();devices={d['path']:d for d in lab.inventory()};m['inventory_before']=devices
        timeline.observe(devices, 'initial')
        if not support:
            m['usb_host_boundary']=usb_host_boundary(package['qemu']['path'])
            if not m['usb_host_boundary']['supported']:
                raise ValueError('QEMU lacks required USB host opt-outs; build the pinned patched QEMU before physical passthrough')
            if len(set(args.ports))!=2:raise ValueError('two distinct physical ports required')
            for index,port in enumerate(args.ports):
                usb_properties(port,index)
                if port not in devices or not devices[port]['writable']:raise ValueError(port+': writable WS73 required; no host permission changes')
                if any(i['driver'] for i in devices[port]['interfaces']):raise ValueError(port+': host driver already owns it; no detach')
        if not os.access('/dev/kvm',os.R_OK|os.W_OK):raise ValueError('KVM access required; nested virtualization is unnecessary')
        share=output/'guest-output';share.mkdir(mode=0o700)
        if any(c in str(share) for c in [',','\n']):raise ValueError('QEMU evidence share path must not contain option delimiters')
        with tempfile.TemporaryDirectory(prefix='ws73-target-') as tmp:
            serial=Path(tmp)/'serial.sock';qmp=Path(tmp)/'qmp.sock'
            command=[package['qemu']['path'],'-machine','q35,accel=kvm','-cpu','host','-m','1024M','-smp','2',
                     '-display','none','-monitor','none','-no-reboot','-nic','none',
                     '-chardev',f'socket,id=console,path={serial},server=on,wait=off','-serial','chardev:console',
                     '-qmp',f'unix:{qmp},server=on,wait=off','-kernel',str(args.prepared.resolve()/'bzImage'),
                     '-initrd',str(args.prepared.resolve()/'initramfs.cpio.gz'),
                     '-append','console=ttyS0 loglevel=5 log_buf_len=4M panic=1 oops=panic'+(' ws73.support=1' if support else '')+
                     (' ws73.passthrough=1' if passthrough else '')+
                     (' ws73.recovery=1' if recovery else '')+
                     (' ws73.event_copy=1' if event_copy else '')+
                     (' ws73.diagnostic=1' if diagnostic else '')+
                     (' ws73.diagnostic_cancel=1' if cancellation else '')+
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
                        if support or passthrough or recovery:
                            raise ValueError('environment timeout; preserve partial console/capture')
                        timeout_seal=SerialTimeoutSeal(transcript)
                        m['graceful_timeout']={'reason':'ENVIRONMENT_TIMEOUT','state':timeout_seal.phase,
                                               'started_wall_ns':time.time_ns(),'grace_seconds':30,
                                               'automatic_hotplug_confirmation':False}
                        if timeout_seal.initial_input:channel.sendall(timeout_seal.initial_input)
                        deadline=time.monotonic()+30
                        write_json(output/'manifest.json',m)
                    readers=[channel]+([] if support or passthrough or recovery or timeout_seal is not None else [sys.stdin])
                    readable,_,_=select.select(readers,[],[],0.1)
                    if channel in readable:
                        data=channel.recv(65536)
                        if data:
                            log.write(data);log.flush();transcript.extend(data);sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
                    if not support and not passthrough and not recovery and timeout_seal is None and sys.stdin in readable:
                        data=os.read(sys.stdin.fileno(),4096)
                        if data:channel.sendall(data)
                        else:raise ValueError('interactive physical environment requires a terminal; no automatic hotplug confirmation')
                    text=transcript.decode(errors='replace')
                    if hold:
                        hold.poll(monitor)
                    if recovery and hotplug_phase==0 and 'WS73_TARGET_RECOVERY_INJECT_READY' in text:
                        target={'path':'/machine/peripheral/ws73_0'}
                        if monitor.execute('qom-get',{**target,'property':'test-runtime-in-errors'})!=0:
                            raise ValueError('fresh injection counter required')
                        monitor.execute('qom-set',{**target,'property':'test-runtime-in-error-once','value':True})
                        if monitor.execute('qom-get',{**target,'property':'test-runtime-in-error-once'}) is not True:
                            raise ValueError('one-shot fault pulse did not arm')
                        m['fault_injection']={'method':'QMP_GUEST_TRANSPORT_ERROR_ONCE','guest_slot':0,
                                              'armed_wall_ns':time.time_ns(),'physical_acceptance':False,
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
                            monitor.execute('device_del',{'id':'ws73_0'});monitor.wait_deleted('ws73_0')
                            channel.sendall((acknowledgement+'-remove\n').encode());hotplug_phase=1
                        if hotplug_phase==1 and prefix+'READD_READY' in text:
                            props=dict(driver='usb-ws73-test',id='ws73_0',bus='xhci.0',port='1',
                                       **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                       **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {}),
                                       **{'runtime-idle-scan-stop':True}, **({'runtime-warm':True} if getattr(args,'warm',False) else {}))
                            if passthrough:props=usb_properties(args.ports[0],0)
                            monitor.execute('device_add',props);channel.sendall((acknowledgement+'-readd\n').encode());hotplug_phase=2
                    if active<2 and ('WS73_TARGET_CAPTURE_READY' if active==0 else 'WS73_TARGET_READY: slot=0') in text:
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
                    if text.splitlines().count(marker) != 1 or text.splitlines().count('WS73_TARGET_NATIVE_VM_TAINT: 0') != 1:
                        raise ValueError('native module VM root/signature proof missing')
                    status = (share/'slkd-process-status.txt').read_text()
                    if (not re.search(r'^Name:\s+slkd$', status, re.M)
                            or not re.search(r'^Uid:\s+0\s+0\s+0\s+0$', status, re.M)):
                        raise ValueError('native module VM daemon is not root')
                if support and ('WS73_TARGET_SUPPORT: PASS' not in text or 'WS73_TARGET_INPUT_PASS: uid=1000 caps=0 tty=1' not in text):raise ValueError('synthetic environment support/input proof missing')
                if not support and not passthrough and not recovery and 'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0' not in text:raise ValueError('physical environment readiness missing')
                if passthrough and 'WS73_TARGET_PASSTHROUGH_SUPPORT: PASS' not in text:raise ValueError('QMP passthrough proof missing')
                if recovery and (hotplug_phase!=1 or 'WS73_TARGET_RECOVERY_SUPPORT: PASS' not in text):
                    raise ValueError('artificial transport recovery proof missing')
                identities=[json.loads((share/f'ready-{n}.json').read_text()) for n in range(2)]
                if getattr(args,'hotplug',False) or passthrough:
                    if hotplug_phase!=2:raise ValueError('both synthetic hotplug phases required')
                    pattern=r'^WS73_TARGET_PASSTHROUGH_(REMOVE|READD)_READY$' if passthrough else r'^WS73_TARGET_CONTROL_(REMOVE|READD)_READY$'
                    markers=re.findall(pattern,text,re.M)
                    if markers!=['REMOVE','READD']:raise ValueError('missing/duplicate/out-of-order synthetic control confirmations')
                    control=json.loads((share/('application/passthrough-control/run.json' if passthrough else 'application/support-control/run.json')).read_text())
                    identities=[*control['initial'],control['replacement']]
                if recovery:
                    control=json.loads((share/'application/recovery-control/run.json').read_text())
                    identities=[*control['initial'],control['replacement']]
                    injection=(output/'qemu-stderr.log').read_text()
                    markers=re.findall(r'WS73_TEST_RUNTIME_IN_ERROR: dev (\d+):(\d+) ep 81 host_status=0 discarded_bytes=(\d+) injected_count=(\d+)',injection)
                    expected=devices[args.ports[0]]
                    if len(markers)!=1 or tuple(map(int,markers[0][:2]))!=(expected['bus'],expected['address']) or int(markers[0][2])<=0 or markers[0][3]!='1':
                        raise ValueError('exact one target-only artificial successful-host-transfer injection required')
                    trace=(output/'usb-lifecycle.log').read_text()
                    if re.search(r'usb_host_(close|reset|open_failure) dev ',trace):
                        raise ValueError('protocol recovery unexpectedly closed/reset a USB owner')
                    m['fault_injection']['consumed_marker']=markers[0]
                packets=check_capture_stats((share/'capture-stats.txt').read_text())
                capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                if packets!=capture['packet_count']:raise ValueError('sealed capture packet count mismatch')
                m['capture_packets']=packets;m['guest_identities']=identities
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
                    if (probe.get('format_version') != (5 if cancellation else 4)
                            or probe.get('cancellation_requested',False) is not cancellation
                            or probe.get('admission_copyout_requested') is not True
                            or probe.get('admission_eviction_requested') is not True
                            or probe.get('legacy_poll_copy_requested') is not True):
                        raise ValueError('current live diagnostic admission gate required')
                    verify_records(probe['records'], admission=True, eviction=True, legacy_poll=True,cancellation=cancellation)
                    if cancellation:
                        if not hold or not hold.record['complete'] or probe.get('host_hold_acknowledgements') != hold.record['observations']:
                            raise ValueError('actual host hold and matching guest acknowledgments required')
                        from ws73_diagnostic_hold import corroborate_host_hold
                        from ws73_capture import corroborate_diagnostic
                        _,cancel_proofs=corroborate_diagnostic(control,capture,probe)
                        m['diagnostic_hold']['corroboration']=corroborate_host_hold(
                            hold.record,probe,cancel_proofs,(output/'qemu-stderr.log').read_text(),devices[args.ports[0]])
                    if len(probe['cli_queries'])!=4:
                        raise ValueError('actual diagnostic CLI query gates missing')
                    m['live_diagnostic']=file_record(share/'diagnostic/run.json')
                m['empty_bulk_completions']=len(capture['empty_bulk_completions'])
                if getattr(args,'empty_bulk',False) and not all(any((e['bus'],e['device'])==(r['bus'],r['device']) for e in capture['empty_bulk_completions']) for r in identities):
                    raise ValueError('successful empty bulk completions missing from either selected USB identity')
                m['status']='FAULT_RECOVERY_SUPPORT_PASS' if recovery else 'PASSTHROUGH_SUPPORT_PASS' if passthrough else 'SUPPORT_PASS' if support else 'ENVIRONMENT_FINISHED'
                if timeout_seal is not None:
                    m['graceful_timeout']['state']='SEALED'
                    m['status']='FAIL'
                    m['error']='environment timeout; capture sealed; physical control not accepted'
        prepared(args.prepared.resolve())
        if file_record(args.prepared.resolve()/'manifest.json')!=m['prepared_manifest']:raise ValueError('prepared manifest changed during run')
    except (Exception,KeyboardInterrupt) as error:
        m['status']='FAIL';m['error']=str(error) or type(error).__name__
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
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
    return 0 if m['status'] in ['SUPPORT_PASS','PASSTHROUGH_SUPPORT_PASS','FAULT_RECOVERY_SUPPORT_PASS','ENVIRONMENT_FINISHED'] else 1


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
    for name in ['run','support']:
        cmd=commands.add_parser(name);cmd.add_argument('--prepared',type=Path,required=True);cmd.add_argument('--output',type=Path,required=True)
        cmd.add_argument('--timeout',type=float,default=120 if name=='support' else 1800)
        if name=='run':
            cmd.add_argument('--ports',nargs=2,required=True)
            cmd.add_argument('--event-copy-verify',action='store_true',help='opt-in live VFS usercopy gate before real recovery/RF; requires --fault-recovery')
            cmd.add_argument('--diagnostic-verify',action='store_true',help='opt-in live diagnostic owner/CAP/copy/retirement and metadata CLI gate; requires --fault-recovery')
            cmd.add_argument('--diagnostic-cancel-verify',action='store_true',help='hold one real IN81 to test active/queued cancel and late reply; requires --diagnostic-verify and --fault-recovery')
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
