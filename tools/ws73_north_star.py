#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Ordinary-user physical WS73 control run and separate raw RX corroboration.

Never installs firmware, restarts slkd, changes USB ownership, or invokes sudo.
A complete control run is evidence-pending until the separate capture is checked.
Even RX corroboration does not certify board configuration or PHY sniffing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from ws73_capture import CaptureError, corroborate, marker_data, read_capture

USB_ROOT = Path('/sys/bus/usb/devices')


def file_record(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def ordinary_identity():
    lines = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    uids = list(map(int, lines['Uid'].split()))
    if not uids[0] or len(set(uids)) != 1 or any(int(lines[k].strip(), 16) for k in ['CapEff','CapPrm','CapAmb']):
        raise ValueError('run as an ordinary user with matching real/effective IDs and no effective capabilities')
    return {'uids': uids, 'cap_eff': lines['CapEff'].strip(), 'cap_prm': lines['CapPrm'].strip(), 'cap_amb': lines['CapAmb'].strip(), 'groups': os.getgroups()}


def daemon_identity(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    rest = text.rsplit(')', 1)[1].split()
    if rest[0] in ('Z', 'X'):
        raise ValueError('slkd process is not alive')
    return {'pid': pid, 'start_ticks': int(rest[19])}


def healthy_native_runtime(value):
    # usb.c initializes 0x100 to mean no controller error byte was observed.
    # An actual 0x000a event (even with byte 0) faults the transport; never
    # invent a successful error event or accept one as healthy.
    m = re.fullmatch(r'id=(\d+) generation=(\d+) streaming=1 broken=0 unsupported=(\d+) last_event=([0-9a-fA-F]{4}) controller_error=100', value)
    if m is None or not 0 <= int(m[1]) < 16 or not 0 < int(m[2]) < 1 << 64:
        raise ValueError('healthy native runtime with no controller error event required')
    return m


def _registration(port, root, synthetic):
    if not re.fullmatch(r'\d+-\d+(?:\.\d+)*', port):
        raise ValueError('explicit physical USB port required')
    device = root / port
    def text(name): return (device / name).read_text().strip()
    if text('idVendor').lower() != 'ffff' or text('idProduct').lower() != '3733':
        raise ValueError('port is not a WS73 USB device')
    descriptors = {name: text(name) if (device / name).exists() else None for name in ['manufacturer', 'product', 'serial']}
    fixture = any(value and ('synthetic' in value.lower() or 'fixture' in value.lower()) for value in descriptors.values())
    if fixture and not synthetic:
        raise ValueError('synthetic USB model excluded from physical acceptance')
    if synthetic and not (descriptors['manufacturer'] == 'OpenSparklink synthetic test' and descriptors['product'] == 'WS73 runtime fixture (NO RF)'):
        raise ValueError('explicit synthetic WS73 fixture descriptors required')
    interfaces = [p for p in root.glob(port + ':*') if (p / 'driver').is_symlink() and (p / 'driver').resolve().name == 'sparklink_ws73_usb']
    if len(interfaces) != 1:
        raise ValueError('exactly one bound native WS73 interface required')
    interface = interfaces[0]
    attrs = {name: (interface / name).read_text().strip() for name in ['metadata_valid', 'runtime_transport', 'boot_error', 'native_runtime', 'controller_information']}
    if attrs['metadata_valid'] != '1' or attrs['runtime_transport'] != '1' or attrs['boot_error'] != '0':
        raise ValueError('native metadata/transport initialization incomplete')
    runtime = healthy_native_runtime(attrs['native_runtime'])
    info = re.fullmatch(r'version=([0-9a-fA-F]{10}) features=([0-9a-fA-F]{20}) address=([0-9a-fA-F:]{17}) acb=(\d+)/(\d+) icb=(\d+)/(\d+) bootstrap_credits=(\d+)', attrs['controller_information'])
    if runtime is None or int(runtime[2]) == 0 or info is None or info[3] == '00:00:00:00:00:00':
        raise ValueError('native registration/queried identity invalid')
    return {'port': port, 'sysfs_path': str(device.resolve()), 'bus': int(text('busnum')),
            'device': int(text('devnum')), 'index': int(runtime[1]), 'generation': int(runtime[2]),
            'path': f'/org/sparklink/slk{runtime[1]}_g{runtime[2]}', 'address': info[3].upper(),
            'version': info[1].lower(), 'features': info[2].lower(),
            'buffers': [int(info[i]) for i in range(4, 8)], 'attributes': attrs,
            'descriptors': descriptors, 'observed_wall_ns': time.time_ns()}


def registration(port, root=USB_ROOT):
    return _registration(port, root, False)


def stable(a, b):
    # Acquisition time is evidence, not part of device identity.
    return all(a[k] == b[k] for k in ['port', 'bus', 'device', 'index', 'generation', 'path', 'address', 'version', 'features'])


def parse_result(output, identity, operation):
    pattern = (r'^NativeOperationResult: generation=(\d+) request=(\d+) operation=(\d+) state=(\d+) errno=(-?\d+) status=0x([0-9a-f]{2}) '
               r'opcode=0x([0-9a-f]{4}) step=(\d+)/(\d+) power=(-?\d+) power_valid=(\d+) adv=(\d+) scan=(\d+) profile=(\d+)$')
    rows = re.findall(pattern, output, re.M)
    if len(rows) != 1 or output.count('NativeOperationResult:') != 1:
        raise ValueError('one exact typed terminal result required')
    r = rows[0]
    expected = {1: ('0c05', 2, 3, 2, 1), 2: ('0c05', 0, 1, 1, 1),
                3: ('1002', 1, 2, 1, 2), 4: ('1002', 0, 1, 1, 1)}[operation]
    if (int(r[0]) != identity['generation'] or int(r[1]) == 0 or int(r[2]) != operation
            or r[3:6] != ('3', '0', '00') or r[13] != '1'
            or (r[6], int(r[7]), int(r[8]), int(r[11]), int(r[12])) != expected
            or int(r[10]) != int(operation == 1)):
        raise ValueError('unsuccessful or wrong-generation native transaction')
    return {'request': int(r[1]), 'generation': int(r[0]), 'operation': operation,
            'selected_power': int(r[9]), 'power_valid': bool(int(r[10]))}


def reports(output, identity):
    rows = []
    for line in output.splitlines():
        if line.startswith('Selected '):
            continue
        m = re.fullmatch(r'seq=(\d+) generation=(\d+) time_ms=(\d+) address=([0-9A-F:]+) RSSI=(-?\d+) header=([0-9a-f]+) data=([0-9a-f]*) lost=(\d+)', line)
        if m is None:
            raise ValueError('malformed report history')
        header = bytes.fromhex(m[6])
        data = bytes.fromhex(m[7])
        if (len(header) != 23 or header[22] != len(data) or int(m[2]) != identity['generation']
                or ':'.join(f'{b:02X}' for b in header[2:8]) != m[4]
                or int.from_bytes(header[21:22], signed=True) != int(m[5])):
            raise ValueError('invalid report identity/header/length')
        rows.append({'seq': int(m[1]), 'generation': int(m[2]), 'address': m[4], 'rssi': int(m[5]),
                     'header': m[6], 'data': m[7], 'lost': int(m[8])})
    return rows


def parse_match(output):
    matches = re.findall(r'^NativeDiscoveryMatch: generation=(\d+) seq=(\d+) address=([0-9A-F:]+) RSSI=(-?\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+) kernel_boottime_ns=(\d+) elapsed_ms=(\d+) lost=(\d+)$', output, re.M)
    if len(matches) != 1 or output.count('NativeDiscoveryMatch:') != 1:
        raise ValueError('one exact fresh discovery match required')
    r = matches[0]
    return dict(zip(['generation','seq','address','rssi','marker','data','kernel_boottime_ns','elapsed_ms','lost'],
                    [int(r[0]),int(r[1]),r[2],int(r[3]),r[4],r[5],int(r[6]),int(r[7]),int(r[8])]))


def parse_scan_window(output, identity, request):
    rows = re.findall(r'^NativeScanWindow: generation=(\d+) request=(\d+) start_boottime_ns=(\d+)$', output, re.M)
    if (len(rows) != 1 or output.count('NativeScanWindow:') != 1
            or int(rows[0][0]) != identity['generation'] or int(rows[0][1]) != request
            or int(rows[0][2]) <= 0):
        raise ValueError('one correlated positive kernel-clock scan window required')
    return int(rows[0][2])


def parse_scan_complete(output, identity, request):
    rows=re.findall(r'^NativeScanComplete: generation=(\d+) request=(\d+) completed_boottime_ns=(\d+)$',output,re.M)
    if (len(rows)!=1 or output.count('NativeScanComplete:')!=1
            or int(rows[0][0])!=identity['generation'] or int(rows[0][1])!=request
            or int(rows[0][2])<parse_scan_window(output,identity,request)):
        raise ValueError('one correlated final Scan Complete clock required')
    return int(rows[0][2])


def parse_scan_observed(output, identity, request):
    rows=re.findall(r'^NativeScanObserved: generation=(\d+) request=(\d+) observed_boottime_ns=(\d+)$',output,re.M)
    if (len(rows)!=1 or output.count('NativeScanObserved:')!=1
            or int(rows[0][0])!=identity['generation'] or int(rows[0][1])!=request):
        raise ValueError('one correlated scan observation clock required')
    completed=parse_scan_complete(output,identity,request)
    observed=int(rows[0][2])
    if not 0<=observed-completed<10_000_000_000:
        raise ValueError('scan observation outside ten seconds after Complete')
    return observed


class Run:
    SCOPE = 'physical'
    SUCCESS = 'CONTROL_PASS_EVIDENCE_PENDING'

    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.output.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.data = {'format_version': 1, 'scope': self.SCOPE, 'status': 'RUNNING', 'rounds': [], 'negatives': [], 'commands': []}
        self.pid = None
        self.save()

    def save(self):
        self.output.joinpath('run.json').write_text(json.dumps(self.data, indent=2) + '\n')

    def read_registration(self, port):
        return registration(port)

    def confirm(self, message):
        input(message)

    def alive(self):
        if daemon_identity(self.args.slkd_pid) != self.pid:
            raise ValueError('slkd exited/restarted or PID reused')

    def bus_identity(self):
        command = [str(self.args.slctl.resolve()), 'daemon']
        result = subprocess.run(command, text=True, capture_output=True, timeout=10)
        self.data.setdefault('bus_observations',[]).append({'args':command,'stdout':result.stdout,'stderr':result.stderr,'exit':result.returncode,'observed_wall_ns':time.time_ns()})
        self.save()
        match = re.fullmatch(r'DaemonIdentity: owner=(:[0-9]+\.[0-9]+) pid=(\d+) uid=(\d+)\n', result.stdout)
        if result.returncode or match is None or int(match[2]) != self.args.slkd_pid:
            raise ValueError('provided PID disagrees with bus-authenticated slkd owner')
        return {'owner':match[1], 'pid':int(match[2]), 'uid':int(match[3])}

    def ctl(self, identity, *words):
        self.alive()
        command = [str(self.args.slctl.resolve()), '--adapter', identity['path'], *words]
        record = {'args': command, 'start_wall_ns': time.time_ns(), 'start_monotonic_ns': time.monotonic_ns(), 'start_boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME)}
        self.data['commands'].append(record)
        self.save()
        try:
            p = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30 if words[:2] == ('scan','on') else 15)
            record.update({'stdout': p.stdout, 'stderr': p.stderr, 'exit': p.returncode})
        except subprocess.TimeoutExpired as error:
            record.update({'stdout': error.stdout.decode(errors='replace') if isinstance(error.stdout,bytes) else (error.stdout or ''), 'stderr': error.stderr.decode(errors='replace') if isinstance(error.stderr,bytes) else (error.stderr or ''), 'exit': 'timeout'})
            raise ValueError('slctl timed out; admitted operation may still exist') from error
        finally:
            record.update({'end_wall_ns': time.time_ns(), 'end_monotonic_ns': time.monotonic_ns(), 'end_boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME)})
            self.save()
        self.alive()
        if p.returncode:
            raise ValueError(f'slctl failed; preserve command {len(self.data["commands"])}')
        return record

    def ready(self, port):
        identity = self.read_registration(port)
        output = self.ctl(identity, 'show')['stdout']
        expected = f"Adapter {identity['path']}:\n  State:       Ready\n  Generation:  {identity['generation']}\n  Address:     {identity['address']}\n  Profile:     1"
        if expected not in output:
            raise ValueError('slctl Ready identity disagrees with physical native registration')
        return identity

    def check(self, identity):
        if not stable(identity, self.read_registration(identity['port'])):
            raise ValueError('physical mapping/registration changed during a round')
        self.alive()

    def stop(self, identity, domain):
        r = self.ctl(identity, domain, 'off')
        parse_result(r['stdout'], identity, 2 if domain == 'advertise' else 4)

    def phase(self, a, b, count, phase):
        tx, rx = a, b
        for n in range(1, count+1):
            self.check(tx); self.check(rx)
            before = reports(self.ctl(rx, 'reports')['stdout'], rx)
            watermark = max((r['seq'] for r in before), default=0)
            adv = self.ctl(tx, 'advertise', 'on')
            adv_index = len(self.data['commands'])-1
            result = parse_result(adv['stdout'], tx, 1)
            accepted = re.findall(r'^NativeAdvertisementAccepted: request=(\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+)$', adv['stdout'], re.M)
            if len(accepted) != 1 or int(accepted[0][0]) != result['request'] or accepted[0][2] != marker_data(accepted[0][1]).hex():
                raise ValueError('advertisement admission/data/result correlation invalid')
            marker = accepted[0][1]
            if marker in [r['marker'] for r in self.data['rounds']]:
                raise ValueError('random marker reused')
            scan = self.ctl(rx, 'scan', 'on', marker, tx['address'])
            scan_index = len(self.data['commands'])-1
            scan_result = parse_result(scan['stdout'], rx, 3)
            scan_boottime = parse_scan_complete(scan['stdout'], rx, scan_result['request'])
            observed = parse_scan_observed(scan['stdout'], rx, scan_result['request'])
            match = parse_match(scan['stdout'])
            if (match['generation'] != rx['generation'] or match['seq'] <= watermark or match['marker'] != marker
                    or match['address'] != tx['address'] or match['data'] != marker_data(marker).hex()
                    or match['lost'] or match['kernel_boottime_ns'] < scan_boottime or match['elapsed_ms'] >= 10000
                    or not scan_boottime<=match['kernel_boottime_ns']<=observed<=scan['end_boottime_ns']
                    or match['elapsed_ms']!=(observed-scan_boottime)//1_000_000):
                raise ValueError('fresh marker/address/data/timing/loss invalid')
            after = reports(self.ctl(rx, 'reports')['stdout'], rx)
            exact = [r for r in after if all(r[k] == match[k] for k in ['seq', 'generation', 'address', 'rssi', 'data', 'lost'])]
            if len(exact) != 1:
                raise ValueError('matched report missing full native header')
            self.stop(tx, 'advertise'); self.stop(rx, 'scan')
            self.check(tx); self.check(rx)
            self.data['rounds'].append({'phase': phase, 'round': n, 'tx': tx, 'rx': rx, 'marker': marker,
                                        'watermark': watermark, 'match': match, 'header': exact[0]['header'],
                                        'command_indices': [adv_index, scan_index, len(self.data['commands'])-2, len(self.data['commands'])-1],
                                        'scan_window_wall_ns': [scan['start_wall_ns'], scan['end_wall_ns']]})
            self.save()
            print(f"{phase} round {n}: {tx['port']} -> {rx['port']} marker={marker} RSSI={match['rssi']} elapsed_ms={match['elapsed_ms']}", flush=True)
            tx, rx = rx, tx
        self.negative(a, b, phase)

    def negative(self, tx, rx, phase):
        time.sleep(0.25)
        baseline = max((r['seq'] for r in reports(self.ctl(rx, 'reports')['stdout'], rx)), default=0)
        scan = self.ctl(rx, 'scan', 'on'); parse_result(scan['stdout'], rx, 3)
        start = time.time_ns(); started = time.monotonic_ns()
        time.sleep(2)
        after = self.ctl(rx, 'reports')
        if any(r['seq'] > baseline and r['address'] in [tx['address'], rx['address']] for r in reports(after['stdout'], rx)):
            raise ValueError('new test transmitter report with both advertisements stopped')
        elapsed = time.monotonic_ns() - started
        if elapsed < 2_000_000_000:
            raise ValueError('negative interval too short')
        self.stop(rx, 'scan'); stop = self.data['commands'][-1]; self.check(tx); self.check(rx)
        self.data['negatives'].append({'phase': phase, 'rx': rx, 'transmitter_addresses': [tx['address'], rx['address']],
                                      'window_wall_ns': [start, after['end_wall_ns']], 'elapsed_monotonic_ns': elapsed,
                                      'scan_window_wall_ns': [scan['start_wall_ns'],scan['end_wall_ns']],
                                      'stop_window_wall_ns': [stop['start_wall_ns'],stop['end_wall_ns']]})
        self.save()

    def wait_port(self, port, present):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            self.alive()
            if not present and not (USB_ROOT / port).exists():
                return None
            if present:
                try: return self.ready(port)
                except (OSError, ValueError): pass
            time.sleep(0.25)
        raise ValueError('physical hotplug/Ready deadline exceeded')

    def execute(self):
        try:
            self.data['application_identity'] = ordinary_identity()
            self.args.slctl = self.args.slctl.resolve()
            mode = self.args.slctl.stat().st_mode
            if not stat.S_ISREG(mode) or mode & (stat.S_ISUID | stat.S_ISGID) or 'security.capability' in os.listxattr(self.args.slctl):
                raise ValueError('ordinary slctl executable required, without setid/file capabilities')
            self.data['slctl'] = file_record(self.args.slctl)
            self.data['kernel_release'] = os.uname().release
            self.data['kernel_version'] = Path('/proc/version').read_text()
            self.data['repositories'] = {}
            for repo in [Path(__file__).resolve().parents[1],Path(__file__).resolve().parents[2]/'linux']:
                if not (repo/'.git').exists(): continue
                head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
                diff = subprocess.check_output(['git','diff','HEAD'],cwd=repo)
                self.data['repositories'][str(repo)] = {'head':head,'dirty_diff_sha256':hashlib.sha256(diff).hexdigest()}
                (self.output/(repo.name+'-dirty.diff')).write_bytes(diff)
            self.data['sources'] = [file_record(Path(__file__)), file_record(Path(__file__).with_name('ws73_capture.py'))]
            self.data['artifacts'] = {}
            for item in self.args.artifact:
                label, path = item.split('=', 1)
                if not label or label in self.data['artifacts']:
                    raise ValueError('unique labeled artifact paths required')
                self.data['artifacts'][label] = file_record(path)
            self.pid = daemon_identity(self.args.slkd_pid)
            self.data['daemon_before'] = self.pid
            self.data['bus_before'] = self.bus_identity()
            a, b = [self.ready(port) for port in self.args.ports]
            if a['address'] == b['address'] or (a['bus'],a['device']) == (b['bus'],b['device']):
                raise ValueError('distinct physical queried identities required')
            self.data['initial'] = [a,b]
            self.phase(a,b,20,'initial')
            self.confirm(f"Unplug only WS73 at {a['port']}, then press Enter: ")
            self.wait_port(a['port'], False)
            self.data['unplug_observed_wall_ns'] = time.time_ns()
            survivor = self.ready(b['port'])
            if not stable(b,survivor): raise ValueError('unplug changed survivor identity')
            scan = self.ctl(b,'scan','on'); parse_result(scan['stdout'],b,3)
            self.stop(b,'scan')
            stale = [str(self.args.slctl.resolve()), '--adapter', a['path'], 'show']
            p = subprocess.run(stale, text=True, capture_output=True, timeout=15)
            self.data['stale_selection'] = {'args':stale,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
            if not p.returncode or 'not a live registration' not in p.stderr:
                raise ValueError('stale selection was not rejected')
            self.data['survivor_control'] = {'identity':survivor, 'scan_request':scan}
            self.confirm(f"Reinsert WS73 at {a['port']}, then press Enter: ")
            new = self.wait_port(a['port'], True)
            if new['generation'] == a['generation'] or new['path'] == a['path']:
                raise ValueError('replug reused retired registration')
            if not stable(b,self.ready(b['port'])): raise ValueError('replug changed survivor')
            self.phase(new,b,2,'replug')
            self.data['replacement'] = new
            self.alive()
            self.data['daemon_after'] = daemon_identity(self.args.slkd_pid)
            self.data['bus_after'] = self.bus_identity()
            if self.data['bus_after'] != self.data['bus_before']:
                raise ValueError('slkd bus owner changed during hotplug')
            for record in [self.data['slctl'], *self.data['sources'], *self.data['artifacts'].values()]:
                if file_record(record['path']) != record:
                    raise ValueError('executable/source/provenance artifact changed during run')
            self.data['status'] = self.SUCCESS
        except (Exception, KeyboardInterrupt) as error:
            self.data['status'] = 'FAIL'
            self.data['error'] = str(error) or type(error).__name__
        finally:
            self.data['cleanup'] = []
            if self.pid is not None:
                for port in self.args.ports:
                    if not (USB_ROOT / port).exists(): continue
                    try:
                        identity = self.read_registration(port)
                        self.stop(identity,'advertise'); self.stop(identity,'scan')
                        self.data['cleanup'].append({'port':port,'status':'STOP_CONFIRMED'})
                    except Exception as error:
                        self.data['cleanup'].append({'port':port,'status':'FAILED','error':str(error)})
                        self.data['status'] = 'FAIL'
            self.save()
        print(self.data['status'], str(self.output / 'run.json'), flush=True)
        return 0 if self.data['status'] == self.SUCCESS else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='physical control gate; manual single-device unplug/replug')
    run.add_argument('--ports', nargs=2, required=True)
    run.add_argument('--slctl', type=Path, required=True)
    run.add_argument('--slkd-pid', type=int, required=True)
    run.add_argument('--artifact', action='append', default=[], help='label=/absolute/file for firmware/calibration/kernel provenance')
    run.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify', help='offline full receiver USB/HCC/DLI corroboration; no board/PHY certification')
    verify.add_argument('--run', type=Path, required=True)
    verify.add_argument('--pcap', type=Path, required=True)
    verify.add_argument('--capture-stats', type=Path, required=True, help='sealed tcpdump stderr including zero kernel drops')
    verify.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.command == 'run':
        if args.ports[0] == args.ports[1]: p.error('two distinct USB ports required')
        return Run(args).execute()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'format_version':1, 'scope':'USB/HCC/DLI RX corroboration, not board qualification or PHY sniffing', 'status':'FAIL'}
    try:
        result['run'] = file_record(args.run); result['pcap'] = file_record(args.pcap)
        result['capture_stats'] = file_record(args.capture_stats)
        from ws73_capture import check_capture_stats
        captured_packets = check_capture_stats(args.capture_stats.read_text())
        run = json.loads(args.run.read_text())
        targets = {(r[s]['bus'], r[s]['device']) for r in run['rounds'] for s in ['tx','rx']}
        capture = read_capture(args.pcap, targets)
        if capture['packet_count'] != captured_packets:
            raise CaptureError('pcap record count disagrees with sealed capture statistics')
        result['capture_packet_count'] = captured_packets
        result['proofs'] = corroborate(run, capture)
        if file_record(args.run) != result['run'] or file_record(args.pcap) != result['pcap'] or file_record(args.capture_stats) != result['capture_stats']:
            raise CaptureError('run/capture changed during verification')
        result['status'] = 'RX_CORROBORATED'
    except Exception as error:
        result['error'] = str(error)
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result['status'], args.output / 'verification.json')
    return 0 if result['status']=='RX_CORROBORATED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
