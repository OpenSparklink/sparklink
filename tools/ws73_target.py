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

USERSPACE = Path(__file__).resolve().parents[1]
LINUX = USERSPACE.parent / 'linux'
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


def config_required(path):
    lines = path.read_text().splitlines()
    for name in ['RUST', 'SPARKLINK', 'SPARKLINK_SLE', 'SPARKLINK_WS73_USB',
                 'USB_MON', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS', 'VIRTIO_PCI']:
        if f'CONFIG_{name}=y' not in lines:
            raise ValueError(f'CONFIG_{name}=y required; do not silently omit capture or evidence export')


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
        config_required(args.kernel_build / '.config')
        lab = lab_module()
        images = lab.firmware(args)
        board = board_files(args.runtime_config_dir)
        inputs = [args.kernel_build/'arch/x86/boot/bzImage',args.kernel_build/'.config',
                  args.qemu,args.busybox,args.dbus_daemon,args.tcpdump,args.python,
                  USERSPACE/'data/dbus/sparklink.conf',Path(__file__),HERE/'ws73_target_init.sh',
                  HERE/'ws73_target_guest.py',HERE/'ws73_north_star.py',HERE/'ws73_capture.py',
                  HERE/'ws73_target_control.py',
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
        for name in ['sh','mount','mdev','sleep','poweroff','dmesg','su','id','grep','awk',
                     'seq','cat','pidof','chmod','mkdir','chown','kill','sync','setsid']:
            (root/'bin'/name).symlink_to('busybox')
        programs = {'dbus-daemon':args.dbus_daemon,'tcpdump':args.tcpdump}
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
        for name in ['ws73_north_star.py','ws73_capture.py','ws73_target_guest.py','ws73_target_control.py','ws73_bindings_probe.py']:
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
        manifest['guest_files'] = [file_record(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()]
        archive = output/'initramfs.cpio.gz'
        with (output/'pack.log').open('wb') as log,archive.open('wb') as packed:
            files = subprocess.Popen(['find','.','-print0'],cwd=root,stdout=subprocess.PIPE)
            cpio = subprocess.Popen(['cpio','--null','-o','--format=newc','--owner=0:0'],cwd=root,
                                    stdin=files.stdout,stdout=subprocess.PIPE,stderr=log);files.stdout.close()
            gzip = subprocess.Popen(['gzip','-n'],stdin=cpio.stdout,stdout=packed,stderr=log);cpio.stdout.close()
            if any([files.wait(),cpio.wait(),gzip.wait()]): raise ValueError('packing failed')
        if any(file_record(r['path']) != r for r in manifest['inputs']+manifest['userspace_sources']):raise ValueError('inputs/sources changed during preparation')
        manifest['artifacts'] = [file_record(output/name) for name in ['bzImage','kernel.config','initramfs.cpio.gz']]
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
    if len(artifacts)!=3 or {Path(r['path']).name for r in artifacts}!={'bzImage','kernel.config','initramfs.cpio.gz'}:raise ValueError('exact kernel/config/initramfs artifact set required')
    for record in artifacts:
        if Path(record['path']).resolve()!=(path/Path(record['path']).name).resolve():raise ValueError('prepared artifact path differs from actual QEMU input')
    for record in artifacts+[m['qemu']]:
        if file_record(record['path']) != record:raise ValueError('prepared artifact changed: '+record['path'])
    config_required(path/'kernel.config')
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


def _run(args):
    ordinary_identity()
    output=args.output.resolve();output.mkdir(mode=0o700,parents=True,exist_ok=False)
    support=args.command=='support'
    m={'version':1,'scope':'synthetic environment support' if support else 'physical development environment',
       'physical_acceptance':False,'status':'STARTING','started_at':datetime.now(timezone.utc).isoformat(),
       'synthetic_empty_bulk':bool(getattr(args,'empty_bulk',False)),
       'synthetic_hotplug':bool(getattr(args,'hotplug',False))}
    process=monitor=channel=None
    try:
        package=prepared(args.prepared.resolve());m['prepared_manifest']=file_record(args.prepared.resolve()/'manifest.json')
        lab=lab_module();devices={d['path']:d for d in lab.inventory()};m['inventory_before']=devices
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
                     (' ws73.empty_bulk=1' if getattr(args,'empty_bulk',False) else '')+
                     (' ws73.hotplug=1' if getattr(args,'hotplug',False) else ''),
                     '-device','qemu-xhci,id=xhci,p2=8,p3=8',
                     '-fsdev',f'local,id=evidence,path={share},security_model=mapped-xattr',
                     '-device','virtio-9p-pci,fsdev=evidence,mount_tag=evidence']
            m['qemu_args']=command;write_json(output/'manifest.json',m)
            with (output/'qemu-stderr.log').open('wb') as stderr,(output/'console.log').open('wb') as log:
                process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=stderr)
                deadline=time.monotonic()+args.timeout
                while not serial.exists() or not qmp.exists():
                    if process.poll() is not None or time.monotonic()>deadline:raise ValueError('QEMU socket startup failed')
                    time.sleep(0.05)
                channel=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);channel.connect(str(serial));channel.setblocking(False)
                monitor=lab.Qmp(qmp,output/'qmp.jsonl')
                active=0;addresses={port:devices[port]['address'] for port in getattr(args,'ports',[])};transcript=bytearray();support_input=False;hotplug_phase=0
                watcher=lab.ReattachmentWatcher(addresses,m.setdefault('reattach',[]),owned=opened_usb_node)
                while process.poll() is None:
                    if time.monotonic()>deadline:raise ValueError('environment timeout; preserve partial console/capture')
                    readers=[channel]+([] if support else [sys.stdin])
                    readable,_,_=select.select(readers,[],[],0.1)
                    if channel in readable:
                        data=channel.recv(65536)
                        if data:
                            log.write(data);log.flush();transcript.extend(data);sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
                    if not support and sys.stdin in readable:
                        data=os.read(sys.stdin.fileno(),4096)
                        if data:channel.sendall(data)
                        else:raise ValueError('interactive physical environment requires a terminal; no automatic hotplug confirmation')
                    text=transcript.decode(errors='replace')
                    if support and not support_input and 'WS73_TARGET_INPUT_READY' in text:
                        channel.sendall(b'target-ordinary-input\n');support_input=True
                    if support and getattr(args,'hotplug',False):
                        if hotplug_phase==0 and 'WS73_TARGET_CONTROL_REMOVE_READY' in text:
                            monitor.execute('device_del',{'id':'ws73_0'});monitor.wait_deleted('ws73_0')
                            channel.sendall(b'support-remove\n');hotplug_phase=1
                        if hotplug_phase==1 and 'WS73_TARGET_CONTROL_READD_READY' in text:
                            props=dict(driver='usb-ws73-test',id='ws73_0',bus='xhci.0',port='1',
                                       **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                       **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {}))
                            monitor.execute('device_add',props);channel.sendall(b'support-readd\n');hotplug_phase=2
                    if active<2 and ('WS73_TARGET_CAPTURE_READY' if active==0 else 'WS73_TARGET_READY: slot=0') in text:
                        props=(dict(driver='usb-ws73-test',id=f'ws73_{active}',bus='xhci.0',port=str(active+1),
                                    **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                    **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {})) if support else usb_properties(args.ports[active],active))
                        monitor.execute('device_add',props);active+=1
                    if not support:
                        current={d['path']:d for d in lab.inventory()}
                        for index,port in enumerate(args.ports[:active]):
                            watcher.poll(index,port,current.get(port),process.pid,monitor)
                # Drain bytes already delivered when QEMU powers down.
                channel.setblocking(True);channel.settimeout(1)
                try:
                    while data:=channel.recv(65536):log.write(data);transcript.extend(data)
                except (TimeoutError,ConnectionResetError):pass
                m['qemu_exit']=process.returncode
                text=transcript.decode(errors='replace').replace('\r','')
                if process.returncode or 'WS73_TARGET_FAILURE:' in text or 'WS73_TARGET_FINISHED' not in text:raise ValueError('guest environment failed')
                if kernel_fault(text+(share/'kernel.log').read_text()):raise ValueError('kernel fault in environment')
                if support and ('WS73_TARGET_SUPPORT: PASS' not in text or 'WS73_TARGET_INPUT_PASS: uid=1000 caps=0 tty=1' not in text):raise ValueError('synthetic environment support/input proof missing')
                if not support and 'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0' not in text:raise ValueError('physical environment readiness missing')
                identities=[json.loads((share/f'ready-{n}.json').read_text()) for n in range(2)]
                if getattr(args,'hotplug',False):
                    if hotplug_phase!=2:raise ValueError('both synthetic hotplug phases required')
                    markers=re.findall(r'^WS73_TARGET_CONTROL_(REMOVE|READD)_READY$',text,re.M)
                    if markers!=['REMOVE','READD']:raise ValueError('missing/duplicate/out-of-order synthetic control confirmations')
                    control=json.loads((share/'application/support-control/run.json').read_text())
                    identities=[*control['initial'],control['replacement']]
                packets=check_capture_stats((share/'capture-stats.txt').read_text())
                capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                if packets!=capture['packet_count']:raise ValueError('sealed capture packet count mismatch')
                m['capture_packets']=packets;m['guest_identities']=identities
                m['empty_bulk_completions']=len(capture['empty_bulk_completions'])
                if getattr(args,'empty_bulk',False) and not all(any((e['bus'],e['device'])==(r['bus'],r['device']) for e in capture['empty_bulk_completions']) for r in identities):
                    raise ValueError('successful empty bulk completions missing from either selected USB identity')
                m['status']='SUPPORT_PASS' if support else 'ENVIRONMENT_FINISHED'
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
        m['finished_at']=datetime.now(timezone.utc).isoformat();write_json(output/'manifest.json',m)
    print(m['status'],output/'manifest.json')
    return 0 if m['status'] in ['SUPPORT_PASS','ENVIRONMENT_FINISHED'] else 1


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
    for name in ['run','support']:
        cmd=commands.add_parser(name);cmd.add_argument('--prepared',type=Path,required=True);cmd.add_argument('--output',type=Path,required=True)
        cmd.add_argument('--timeout',type=float,default=120 if name=='support' else 1800)
        if name=='run':cmd.add_argument('--ports',nargs=2,required=True)
        else:
            cmd.add_argument('--empty-bulk',action='store_true',help='inject successful zero-length bulk IN before synthetic runtime replies; never a physical option')
            cmd.add_argument('--hotplug',action='store_true',help='run the full control orchestrator with explicitly synthetic USB removal/replug; never physical acceptance')
    args=parser.parse_args()
    if not math.isfinite(getattr(args,'timeout',1)) or getattr(args,'timeout',1)<=0:parser.error('timeout must be finite and positive')
    return prepare(args) if args.command=='prepare' else run(args)


if __name__=='__main__':raise SystemExit(main())
