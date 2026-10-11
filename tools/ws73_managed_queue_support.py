#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual kernel fd/Queued cancellation on two simulated USB controllers.

Dedicated scratch VM, no host USB, network or host disks. This cannot qualify
real radios, active Ready peer isolation, partial cleanup or automatic recovery.
"""
import argparse
import json
import math
from pathlib import Path
import select
import socket
import subprocess
import time
from types import SimpleNamespace

from ws73_capture import check_capture_stats, read_capture
from ws73_management_queued import corroborate, setup
from ws73_north_star import file_record
from ws73_target import kernel_fault, lab_module, prepared
import ws73_vm_native_root as native_vm


def properties(slot, partial=False, reject_idle=False):
    if type(slot) is not int or slot not in (0, 1):
        raise ValueError('exact synthetic slot required')
    if type(partial) is not bool or type(reject_idle) is not bool or reject_idle and not partial:
        raise ValueError('exact model-only partial/reject controls required')
    return dict(driver='usb-ws73-test', id=f'ws73_{slot}', bus='xhci.0',
                port=str(slot+1), **{'runtime-discovery': True,
                'runtime-policy': True, 'runtime-fresh-advertiser': True,
                'runtime-sle-subtypes': True, 'runtime-medium': 1,
                'runtime-idle-scan-stop': reject_idle if partial else True})


def verify_transport(rows, partial=False, reject_idle=False):
    """Refuse host USB, resets, extra objects or unsuccessful QMP commands."""
    sent = [r['message'] for r in rows if r['direction'] == 'tx']
    attachments=[m for m in sent if m['execute'] not in ('qom-get','qom-set')]
    if [m['execute'] for m in attachments] != ['qmp_capabilities', 'device_add', 'device_add']:
        raise ValueError('only two synthetic device attachments permitted')
    if [m.get('arguments') for m in attachments[1:]] != [properties(0,partial,reject_idle), properties(1,partial,reject_idle)]:
        raise ValueError('exact synthetic transport properties required')
    for message in sent:
        if message['execute'] in ('qom-get','qom-set'):
            from ws73_model_hold import PROPERTIES
            args=message.get('arguments',{})
            if not partial or args.get('path')!='/machine/peripheral/ws73_0':
                raise ValueError('model-only target QOM scope required')
            if message['execute']=='qom-get':
                if set(args)!={'path','property'} or args['property'] not in PROPERTIES+['model-terminal-armable']:
                    raise ValueError('exact model observation property required')
            elif (set(args)!={'path','property','value'} or args['property'] not in ['model-terminal-hold-once','model-terminal-release'] or args['value'] is not True):
                raise ValueError('only model arm/release pulses allowed')
        replies = [r['message'] for r in rows if r['direction'] == 'rx'
                   and r['message'].get('id') == message['id']]
        if len(replies) != 1 or 'return' not in replies[0] or 'error' in replies[0]:
            raise ValueError('successful QMP command readback required')
        if message['execute']!='qom-get' and replies[0]['return']!={}:
            raise ValueError('exact mutation/capability acknowledgment required')
        if message['execute']=='qom-get':
            kind=bool if args['property'] in PROPERTIES[:2]+['model-terminal-armable'] else int
            value=replies[0]['return']
            if type(value) is not kind or kind is int and not 0<=value<1<<64:
                raise ValueError('typed bounded model property reply required')


def run(args):
    if not math.isfinite(args.timeout) or not 15 <= args.timeout <= 300:
        raise ValueError('bounded support VM timeout required')
    lab = lab_module()
    partial=args.partial_case is not None
    if args.idle_scan_stop_reject and not partial or not partial and args.partial_domain!='advertising':
        raise ValueError('partial controls require explicit partial case')
    success='PASS_MANAGED_PARTIAL_SYNTHETIC_KERNEL_FD_SUPPORT' if partial else 'PASS_MANAGED_QUEUE_SYNTHETIC_KERNEL_FD_SUPPORT'
    mode='MANAGED_PARTIAL' if partial else 'MANAGED_QUEUE'
    output = args.output.resolve()
    if any(c in str(p) for p in [output, args.prepared.resolve()] for c in [',', '\n', '\r']):
        raise ValueError('QEMU paths cannot contain option delimiters')
    record = dict(status='STARTING', scope='simulated USB, actual kernel fd contracts only',
                  physical_acceptance=False, managed_preselection_live_acceptance=False,
                  managed_partial_initialization_live_acceptance=False,
                  active_ready_peer_isolation_acceptance=False,
                  automatic_fault_recovery_acceptance=False, natural_fault_root_cause_closed=False,
                  started_wall_ns=time.time_ns())
    record.update(partial_case=args.partial_case,partial_domain=args.partial_domain if partial else None,
                  model_idle_stop_reject=args.idle_scan_stop_reject)
    process = monitor = channel = None
    def save():
        (output/'manifest.json').write_text(json.dumps(record, indent=2)+'\n')
    with lab.lab_lock(SimpleNamespace(action='managed-queue-synthetic-support', build_dir=args.prepared)):
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        share = output/'guest-output'; share.mkdir(mode=0o700)
        try:
            package = prepared(args.prepared.resolve())
            if 'native_vm' not in package or 'managed_queue_probe_compile' not in package:
                raise ValueError('qualified signed scratch-root VM and frozen C fd probe required')
            record['prepared_manifest'] = file_record(args.prepared/'manifest.json')
            record['runner_inputs'] = [file_record(Path(__file__)),
                                      file_record(Path(__file__).with_name('ws73_management_queued.py'))]
            serial = output/'serial.sock'; qmp = output/'qmp.sock'
            options, append = native_vm.launch(args.prepared.resolve(), output, package)
            boot=(f'ws73.managed_partial=1 ws73.managed_partial_support=1 ws73.partial_case={args.partial_case} ws73.partial_domain={args.partial_domain}'
                  if partial else 'ws73.managed_queue=1 ws73.managed_queue_support=1')
            command = [package['qemu']['path'], '-machine', 'q35,accel=kvm', '-cpu', 'host',
                       '-m', '1024M', '-smp', '1', '-display', 'none', '-monitor', 'none',
                       '-no-reboot', '-nic', 'none', '-kernel', str(args.prepared/'bzImage'),
                       '-initrd', str(args.prepared/'initramfs.cpio.gz'),
                       '-chardev', f'socket,id=console,path={serial},server=on,wait=off',
                       '-serial', 'chardev:console', '-qmp', f'unix:{qmp},server=on,wait=off',
                       '-device', 'qemu-xhci,id=xhci,p2=8,p3=8',
                       '-fsdev', f'local,id=evidence,path={share},security_model=mapped-xattr',
                       '-device', 'virtio-9p-pci,fsdev=evidence,mount_tag=evidence',
                       '-append', 'console=ttyS0 loglevel=6 panic=1 oops=panic '
                       +boot+append, *options]
            record['qemu_args'] = command; save()
            with (output/'console.log').open('xb') as log, (output/'qemu-stderr.log').open('xb') as err:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
                deadline = time.monotonic()+args.timeout
                while not serial.exists() or not qmp.exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise TimeoutError('support VM socket startup')
                    time.sleep(.05)
                channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                channel.connect(str(serial)); channel.setblocking(False)
                monitor = lab.Qmp(qmp, output/'qmp.jsonl')
                hold=None
                if partial:
                    from ws73_model_hold import ModelHoldCoordinator
                    hold=ModelHoldCoordinator(share,record.setdefault('model_hold',{}))
                transcript = bytearray(); attached = 0
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('bounded support VM execution')
                    if select.select([channel], [], [], .1)[0]:
                        data = channel.recv(65536)
                        if data: log.write(data); log.flush(); transcript.extend(data)
                    marker = share/('managed-partial' if partial else 'managed-queue')/'metadata-0.json'
                    if attached == 0 and b'WS73_TARGET_CAPTURE_READY' in transcript:
                        monitor.execute('device_add', properties(0,partial,args.idle_scan_stop_reject)); attached = 1
                    elif attached == 1 and marker.exists():
                        value = json.loads(marker.read_text())
                        if set(value) != {'slot', 'initial_snapshot'} or type(value['slot']) is not int or value['slot'] != 0:
                            raise ValueError('exact initial Setup marker required')
                        setup(value['initial_snapshot'], 0)
                        monitor.execute('device_add', properties(1,partial,args.idle_scan_stop_reject)); attached = 2
                    if hold and attached==2:hold.poll(monitor)
                channel.setblocking(True); channel.settimeout(1)
                try:
                    while data := channel.recv(65536): log.write(data); transcript.extend(data)
                except (TimeoutError, ConnectionResetError):
                    pass
            text = transcript.decode(errors='replace')
            if process.returncode or 'WS73_TARGET_FAILURE:' in text or kernel_fault(text+(share/'kernel.log').read_text()):
                raise ValueError('support VM failed; preserve evidence')
            for marker in [f'WS73_TARGET_{mode}_SUPPORT_FINISHED', f'WS73_TARGET_{mode}_SUPPORT_TAINT: 0']:
                if text.replace('\r', '').splitlines().count(marker) != 1:
                    raise ValueError('complete synthetic support marker required')
            verify_transport([json.loads(l) for l in (output/'qmp.jsonl').read_text().splitlines()],partial,args.idle_scan_stop_reject)
            probe = json.loads((share/('managed-partial' if partial else 'managed-queue')/'run.json').read_text())
            if probe.get('synthetic_support') is not True:
                raise ValueError('collector must label simulated evidence explicitly')
            capture = read_capture(share/'ws73.pcap', [(1, n) for n in range(1, 128)])
            record['capture_packets'] = check_capture_stats((share/'capture-stats.txt').read_text())
            if record['capture_packets'] != capture['packet_count']:
                raise ValueError('sealed USB capture count mismatch')
            if partial:
                from ws73_management_partial import corroborate as corroborate_partial
                record['corroboration']=corroborate_partial(probe,hold.record,capture,(output/'qemu-stderr.log').read_text(),{})
            else:record['corroboration'] = corroborate(probe, capture)
            prepared(args.prepared.resolve())
            if record['runner_inputs'] != [file_record(Path(__file__)), file_record(Path(__file__).with_name('ws73_management_queued.py'))]:
                raise ValueError('runner or verifier changed during support VM')
            record['status'] = success
        except BaseException as error:
            record.update(status='FAIL', error=str(error))
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            if monitor: monitor.close()
            if channel: channel.close()
            record['qemu_exit'] = None if process is None else process.returncode
            record['guest_files'] = [file_record(p) for p in sorted(share.rglob('*')) if p.is_file() and not p.is_symlink()]
            record['finished_wall_ns'] = time.time_ns(); save()
    print(record['status'], output/'manifest.json')
    return int(record['status'] != success)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--partial-case',choices=['release','close','dup'])
    parser.add_argument('--partial-domain',choices=['advertising','scanning'],default='advertising')
    parser.add_argument('--idle-scan-stop-reject',action='store_true',help='model negative branch: preserve raw idle STOP refusal; expected VM failure, never a real pass')
    raise SystemExit(run(parser.parse_args()))
