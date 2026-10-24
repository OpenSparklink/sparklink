#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Four real WS73 radios, two concurrent pairs with actual per-round barriers.

Workers preserve radios On until both real matches have arrived. Qualification
requires independent USB proof of overlapping START/OFF intervals. No hotplug,
reply injection, daemon restart or automatic recovery is performed here.
"""
import argparse
import json
import os
from pathlib import Path
import select
import selectors
import subprocess
import sys
import time

from ws73_north_star import Run, USB_ROOT, daemon_identity, file_record, ordinary_identity, stable, parse_result
from ws73_capture import CaptureError, command_reply, physical_device_descriptors, json_identity
from ws73_rf_rounds import corroborate_rounds, corroborate_stops
from ws73_discovery_policy_capture import checked_expectation, query_proofs, wire_proofs, DEFAULT


PREFIX = 'WS73_PARALLEL_EVENT:'
SCOPE = 'real WS73 parallel pair RF'
SUCCESS = 'PARALLEL_PAIR_RF_EVIDENCE_PENDING'
SEQUENCE = [('ready', 0), *[(phase, n) for n in range(1, 21) for phase in ['start', 'matched']]]


def policy_expectation(path):
    path = path.resolve(strict=True)
    record = file_record(path)
    data = checked_expectation(json.loads(path.read_text()))
    if file_record(path) != record:
        raise ValueError('policy expectation changed while reading')
    return {'file': record, 'data': data}


def start_offset(value):
    value = int(value)
    if not 0 <= value <= 125:
        raise argparse.ArgumentTypeError('diagnostic start offset must be 0..125 ms')
    return value


def distinct_owners(owners):
    """The existing final identity contract, also enforced before RF starts.

    These are controller observations, not authenticated device identities.
    Keep controller/generation as a pair; generations need not be globally unique.
    """
    if len(owners) != 4 or any(len({o[key] for o in owners}) != 4
            for key in ('port', 'path', 'address', 'index')):
        raise CaptureError('four distinct original owner identities required')
    if (len({(o['bus'], o['device']) for o in owners}) != 4
            or len({(o['index'], o['generation']) for o in owners}) != 4):
        raise CaptureError('four independent USB/controller registrations required')
    physical_device_descriptors(owners)


def ready_owners(waits, ports):
    """Bind both live Ready pipes to explicit slots before either is released."""
    if len(waits) != 2 or len(ports) != 4 or len(set(ports)) != 4:
        raise CaptureError('two complete Ready pipes and four explicit slots required')
    owners = []
    for pair, row in enumerate(waits):
        event = row['event']
        entries = event.get('owners', [])
        if (event['pair'] != pair or event['phase'] != 'ready' or event['round'] != 0
                or len(entries) != 2
                or [o['port'] for o in entries] != list(ports[pair*2:pair*2+2])):
            raise CaptureError('Ready observations must match the explicit pair and slots')
        owners.extend(entries)
    distinct_owners(owners)
    return owners


class PairRun(Run):
    SCOPE = SCOPE
    SUCCESS = SUCCESS

    def __init__(self, args):
        super().__init__(args)
        self.barriers_active = False
        self.data['advertise_start_offset_ms'] = args.start_offset_ms
        self.data['policy_expectation'] = policy_expectation(args.policy_expectation)

    def barrier(self, phase, number):
        row = dict(pair=self.args.pair, phase=phase, round=number, wait_wall_ns=time.time_ns())
        if phase == 'ready':
            row['owners'] = self.data['initial']
        self.data.setdefault('barriers', []).append(row)
        self.save()
        print(PREFIX+json.dumps(row, separators=(',', ':')), flush=True)
        if not select.select([sys.stdin], [], [], getattr(self, 'barrier_timeout', 15))[0]:
            raise TimeoutError('bounded parallel peer barrier')
        token = sys.stdin.readline()
        if token == 'parallel-abort\n':
            raise ValueError('parallel peer failed; perform bounded real cleanup')
        if token != f'parallel-{phase}-{number}\n':
            raise ValueError('wrong parallel peer acknowledgement')
        row['ack_wall_ns'] = time.time_ns()
        self.save()

    def ctl(self, identity, *words):
        if self.barriers_active and words == ('advertise', 'on'):
            self.barrier('start', len(self.data['rounds'])+1)
            time.sleep(self.args.start_offset_ms / 1000)
        return super().ctl(identity, *words)

    def stop(self, identity, domain):
        if self.barriers_active and domain == 'advertise':
            self.barrier('matched', len(self.data['rounds'])+1)
        return super().stop(identity, domain)

    def execute(self):
        try:
            self.begin()
            self.data['pair'] = self.args.pair
            a, b = [self.ready(port) for port in self.args.ports]
            self.data['initial'] = [a, b]
            for owner in [a, b]:
                for domain in ['advertise', 'scan']:
                    self.confirm_initialization_off(owner, domain)
            self.barrier('ready', 0)
            self.barriers_active = True
            self.phase(a, b, 20, 'parallel')
            self.barriers_active = False
            self.data['after'] = [self.ready(port) for port in self.args.ports]
            if not all(stable(before, after) for before, after in zip(self.data['initial'], self.data['after'])):
                raise ValueError('parallel RF changed a registration')
            self.alive()
            self.data['daemon_after'] = daemon_identity(self.args.slkd_pid)
            self.data['bus_after'] = self.bus_identity()
            if self.data['bus_before'] != self.data['bus_after']:
                raise ValueError('parallel RF changed authenticated daemon owner')
            for record in [self.data['slctl'], *self.data['sources'], *self.data['artifacts'].values()]:
                if file_record(record['path']) != record:
                    raise ValueError('parallel executable or source changed')
            if policy_expectation(self.args.policy_expectation) != self.data['policy_expectation']:
                raise ValueError('parallel policy expectation changed')
            self.data['status'] = self.SUCCESS
        except (Exception, KeyboardInterrupt) as error:
            self.data.update(status='FAIL', error=str(error) or type(error).__name__)
        finally:
            self.cleanup()
        print(self.data['status'], self.output/'run.json', flush=True)
        return 0 if self.data['status'] == self.SUCCESS else 1

    def cleanup(self):
        self.barriers_active = False
        self.data['cleanup'] = []
        if self.pid is not None:
            for port in self.args.ports:
                if not (USB_ROOT/port).exists():
                    self.data['cleanup'].append(dict(port=port, status='FAILED', error='device absent'))
                    self.data['status'] = 'FAIL'
                    continue
                try:
                    owner = self.read_registration(port)
                    failures = []
                    for domain in ['advertise', 'scan']:
                        try:
                            prefix = [str(self.args.slctl.resolve()), '--adapter', owner['path'], domain]
                            if any(c['args'][:4] == prefix and c['args'][4:5] in [['on'], ['off']]
                                   for c in self.data['commands']):
                                self.require_initialization_invalidated(owner, domain)
                            self.stop(owner, domain)
                        except Exception as error:
                            failures.append(dict(domain=domain, error=str(error)))
                    if failures:
                        self.data['cleanup'].append(dict(port=port, status='FAILED', errors=failures))
                        self.data['status'] = 'FAIL'
                        continue
                    self.data['cleanup'].append(dict(port=port, status='STOP_CONFIRMED'))
                except Exception as error:
                    self.data['cleanup'].append(dict(port=port, status='FAILED', error=str(error)))
                    self.data['status'] = 'FAIL'
        self.save()


class EventReader:
    """Consume live pipes, not mutable worker output files."""
    def __init__(self, processes, rows, timeout_seconds=15):
        self.timeout_seconds = timeout_seconds
        self.watch = selectors.DefaultSelector()
        self.buffers = {n: b'' for n in range(2)}
        self.queue = {n: [] for n in range(2)}
        self.rows = rows
        for n, process in enumerate(processes):
            self.watch.register(process.stdout, selectors.EVENT_READ, (n, 'stdout'))
            self.watch.register(process.stderr, selectors.EVENT_READ, (n, 'stderr'))

    def pump(self, timeout):
        for key, _ in self.watch.select(timeout):
            pair, channel = key.data
            data = os.read(key.fileobj.fileno(), 65536)
            if not data:
                self.watch.unregister(key.fileobj)
                continue
            self.rows[pair][channel] += data.decode(errors='replace')
            if channel == 'stdout':
                self.buffers[pair] += data
                while b'\n' in self.buffers[pair]:
                    line, self.buffers[pair] = self.buffers[pair].split(b'\n', 1)
                    if line.startswith(PREFIX.encode()):
                        self.queue[pair].append(json.loads(line[len(PREFIX):]))

    def waits(self, processes, phase, number):
        deadline = time.monotonic()+self.timeout_seconds
        return [self.wait_one(processes, pair, phase, number, deadline) for pair in range(2)]

    def wait_one(self, processes, pair, phase, number, deadline=None):
        if deadline is None:
            deadline=time.monotonic()+self.timeout_seconds
        while not self.queue[pair]:
            if processes[pair].poll() is not None:
                raise ValueError('parallel worker exited before peer barrier')
            if time.monotonic()>deadline:
                raise TimeoutError('bounded parallel worker event')
            self.pump(.01)
        event=self.queue[pair].pop(0)
        if event['pair']!=pair or event['phase']!=phase or event['round']!=number or 'ack_wall_ns' in event:
            raise ValueError('wrong/duplicate/out-of-order parallel event')
        return dict(event=event,observed_wall_ns=time.time_ns())


def abort_workers(processes, reader, timeout=30):
    """Request real worker cleanup; retain a bounded forced-kill fallback."""
    rows = []
    for process in processes:
        if process.poll() is not None:
            continue
        row = dict(pid=process.pid, requested_wall_ns=time.time_ns(), sent=False, forced_kill=False)
        rows.append(row)
        try:
            process.stdin.write(b'parallel-abort\n')
            process.stdin.flush()
            row['sent'] = True
        except (BrokenPipeError, OSError) as error:
            row['error'] = str(error)
    deadline = time.monotonic()+timeout
    while any(p.poll() is None for p in processes) and time.monotonic() < deadline:
        if reader:
            reader.pump(.01)
        else:
            time.sleep(.01)
    for process in processes:
        if process.poll() is None:
            process.kill()
            next(row for row in rows if row['pid'] == process.pid)['forced_kill'] = True
    return rows


def run_parallel(args):
    if len(args.ports) != 4 or len(set(args.ports)) != 4:
        raise ValueError('four distinct physical guest ports required')
    args.slctl = args.slctl.resolve()
    offset = start_offset(args.second_pair_start_offset_ms)
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = dict(format_version=2, scope='four real WS73 two-pair parallel RF', status='RUNNING',
                  application_identity=ordinary_identity(), stages=[], workers=[],
                  policy_expectation=policy_expectation(args.policy_expectation),
                  second_pair_start_offset_ms=offset,
                  physical_unplug_acceptance=False, automatic_fault_recovery_acceptance=False)
    def save():
        temporary = output/'run.tmp'
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(output/'run.json')
    processes, reader = [], None
    try:
        for pair in range(2):
            argv = [sys.executable, str(Path(__file__).resolve()), 'pair', '--pair', str(pair), '--ports',
                    *args.ports[pair*2:pair*2+2], '--slctl', str(args.slctl), '--slkd-pid', str(args.slkd_pid),
                    '--output', str(output/f'pair-{pair}'),
                    '--policy-expectation', record['policy_expectation']['file']['path'],
                    '--start-offset-ms', str(offset if pair else 0)]
            row = dict(args=argv, start_wall_ns=time.time_ns(), stdout='', stderr='')
            record['workers'].append(row)
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processes.append(process)
            row['pid'] = process.pid
            save()
        reader = EventReader(processes, record['workers'])
        for phase, number in SEQUENCE:
            waits = reader.waits(processes, phase, number)
            if phase == 'ready':
                ready_owners(waits, args.ports)
            stage = dict(phase=phase, round=number, waits=waits, release_wall_ns=time.time_ns())
            record['stages'].append(stage)
            save()
            for process in processes:
                process.stdin.write(f'parallel-{phase}-{number}\n'.encode())
                process.stdin.flush()
            if phase == 'matched':
                print(f'WS73_PARALLEL_MATCHED: round={number} pairs=2', flush=True)
        deadline = time.monotonic()+30
        while any(p.poll() is None for p in processes):
            if time.monotonic() > deadline:
                raise TimeoutError('bounded parallel final stop/reap')
            reader.pump(.01)
        record['status'] = 'PARALLEL_RF_EVIDENCE_PENDING'
    except (Exception, KeyboardInterrupt) as error:
        record.update(status='FAIL', error=str(error) or type(error).__name__)
    finally:
        record['failure_shutdown'] = abort_workers(processes, reader)
        for pair, process in enumerate(processes):
            process.wait()
            record['workers'][pair].update(exit=process.returncode, end_wall_ns=time.time_ns())
        if reader:
            while reader.watch.get_map():
                reader.pump(.01)
            reader.watch.close()
        for pair, process in enumerate(processes):
            # Every worker is reaped before reading any output artifact.
            path = output/f'pair-{pair}/run.json'
            if path.is_file():
                record['workers'][pair].update(run=json.loads(path.read_text()), artifact=file_record(path))
            if process.returncode:
                record['status'] = 'FAIL'
            for pipe in [process.stdin, process.stdout, process.stderr]:
                pipe.close()
        save()
    if record['status'] == 'PARALLEL_RF_EVIDENCE_PENDING':
        try:
            verify_records(record)
        except Exception as error:
            record.update(status='FAIL', error=str(error))
            save()
    print(record['status'], output/'run.json', flush=True)
    return 0 if record['status'] == 'PARALLEL_RF_EVIDENCE_PENDING' else 1


def verify_records(record):
    if (record.get('format_version') not in [1, 2] or record.get('scope') != 'four real WS73 two-pair parallel RF'
            or record.get('status') != 'PARALLEL_RF_EVIDENCE_PENDING' or record.get('physical_unplug_acceptance') is not False
            or record.get('automatic_fault_recovery_acceptance') is not False or len(record['workers']) != 2):
        raise CaptureError('explicit four-device parallel evidence required')
    current = record['format_version'] == 2
    if current:
        checked_expectation(record['policy_expectation']['data'])
    if record.get('failure_shutdown'):
        raise CaptureError('an aborted or forcibly killed worker cannot qualify')
    offset = record.get('second_pair_start_offset_ms')
    if type(offset) is not int or not 0 <= offset <= 125:
        raise CaptureError('explicit bounded diagnostic start offset required')
    app = record['application_identity']
    if app['uids'] != [1000]*4 or any(int(app[k], 16) for k in ['cap_eff', 'cap_prm', 'cap_amb']):
        raise CaptureError('ordinary UID1000 without capabilities required')
    owners, daemon, bus, markers = [], None, None, set()
    if len({w['pid'] for w in record['workers']})!=2 or any(type(w['pid']) is not int or w['pid']<=0 for w in record['workers']):
        raise CaptureError('distinct actual worker processes required')
    for pair, worker in enumerate(record['workers']):
        r = worker['run']
        if worker['exit'] or r['scope'] != SCOPE or r['status'] != SUCCESS or r['pair'] != pair or r['application_identity'] != app:
            raise CaptureError('two actual ordinary reaped successful workers required')
        argv=worker['args']
        if argv[2:7]!=['pair','--pair',str(pair),'--ports',r['initial'][0]['port']] or argv[7]!=r['initial'][1]['port'] or argv[8:12]!=['--slctl',r['slctl']['path'],'--slkd-pid',str(r['daemon_before']['pid'])]:
            raise CaptureError('worker invocation affinity must match selected pair and daemon')
        delay = offset if pair else 0
        if r.get('advertise_start_offset_ms') != delay or argv[-2:] != ['--start-offset-ms', str(delay)]:
            raise CaptureError('worker diagnostic start offset differs from parent')
        if current:
            if (r.get('policy_expectation') != record['policy_expectation']
                    or argv[-4:-2] != ['--policy-expectation', record['policy_expectation']['file']['path']]):
                raise CaptureError('both workers must use the frozen policy expectation')
            query_proofs(r, record['policy_expectation']['data'])
        if len(r['initial']) != 2 or len(r['after']) != 2 or not all(stable(a, b) for a, b in zip(r['initial'], r['after'])):
            raise CaptureError('four registrations stay independently Ready')
        if r['daemon_before'] != r['daemon_after'] or r['bus_before'] != r['bus_after'] or r['bus_before']['pid'] != r['daemon_before']['pid']:
            raise CaptureError('same live authenticated daemon required')
        if pair and (daemon != r['daemon_before'] or bus != r['bus_before']):
            raise CaptureError('both pairs must share the same live daemon')
        daemon, bus = r['daemon_before'], r['bus_before']
        owners.extend(r['initial'])
        if len(r['cleanup']) != 2 or any(v['status'] != 'STOP_CONFIRMED' for v in r['cleanup']):
            raise CaptureError('all actual final stops required')
        if [(v['phase'], v['round']) for v in r['rounds']] != [('parallel', n) for n in range(1, 21)]:
            raise CaptureError('twenty consecutive rounds per pair required')
        for row in r['rounds']:
            if row['marker'] in markers:
                raise CaptureError('random markers reused across pairs')
            markers.add(row['marker'])
    distinct_owners(owners)
    if len({o['generation'] for o in owners}) != 4:
        raise CaptureError('four distinct actual device registrations required')
    if [(s['phase'], s['round']) for s in record['stages']] != SEQUENCE:
        raise CaptureError('all ordered round barriers required')
    for pair, worker in enumerate(record['workers']):
        barriers = worker['run']['barriers']
        delay = offset if pair else 0
        if [(b['phase'], b['round']) for b in barriers] != SEQUENCE:
            raise CaptureError('worker barrier history incomplete')
        for stage, child in zip(record['stages'], barriers):
            wait = stage['waits'][pair]
            event = {k: v for k, v in child.items() if k != 'ack_wall_ns'}
            if wait['event'] != event or child['pair'] != pair or not child['wait_wall_ns'] <= wait['observed_wall_ns'] <= stage['release_wall_ns'] <= child['ack_wall_ns']:
                raise CaptureError('actual live pipe wait/release/ack sequence required')
        for n, row in enumerate(worker['run']['rounds'], 1):
            commands = [worker['run']['commands'][i] for i in row['command_indices']]
            start, matched = barriers[2*n-1:2*n+1]
            if not start['ack_wall_ns'] <= commands[0]['start_wall_ns'] <= commands[1]['end_wall_ns'] <= matched['wait_wall_ns'] <= matched['ack_wall_ns'] <= commands[2]['start_wall_ns']:
                raise CaptureError('both real matches must precede radio OFF')
            if commands[0]['start_wall_ns']-start['ack_wall_ns'] < delay*1_000_000:
                raise CaptureError('actual command predates diagnostic start offset')
    return owners


def corroborate(record, capture):
    owners = verify_records(record)
    expectation = record.get('policy_expectation') if record['format_version'] == 2 else None
    policies = wire_proofs(capture, owners, expectation['data']) if expectation else []
    pairs, used = [], set()
    for worker in record['workers']:
        r = worker['run']
        corroborate_stops(r, capture)
        proofs = corroborate_rounds(r, capture, [('parallel', n) for n in range(1, 21)], {'parallel': r['initial']})
        if len(r['negatives']) != 1 or r['negatives'][0]['phase'] != 'parallel':
            raise CaptureError('actual per-pair TX-off negative control required')
        negative = r['negatives'][0]
        if set(negative['transmitter_addresses']) != {o['address'] for o in r['initial']}:
            raise CaptureError('negative must cover both radios in its pair')
        start, end = negative['window_wall_ns']
        scan_start, scan_end = negative['scan_window_wall_ns']
        stop_start, stop_end = negative['stop_window_wall_ns']
        if not scan_end <= start < end <= stop_start or end-start < 2_000_000_000:
            raise CaptureError('two-second confirmed negative scan required')
        for lo, hi, on in [(scan_start, scan_end, 1), (stop_start, stop_end, 0)]:
            command_reply(capture, negative['rx'], 0x1002, lo, hi, bytes([on, 0]), '')
        if any(v['bus'] == negative['rx']['bus'] and v['device'] == negative['rx']['device'] and start <= v['wall_ns'] <= end and v['address'] in negative['transmitter_addresses'] for v in capture['reports']):
            raise CaptureError('own transmitter observed during TX-off negative')
        metadata = {}
        for owner in r['initial']:
            import struct
            metadata[json_identity(owner)] = [command_reply(capture, owner, opcode, 0, owner['observed_wall_ns'], b'', value)
                for opcode, value in [(0x0404, owner['version']), (0x0402, struct.pack('<HBHB', *owner['buffers']).hex()),
                                      (0x0403, owner['features']), (0x0406, owner['address'].replace(':', '').lower())]]
        for proof, row in zip(proofs, r['rounds']):
            key = (proof['raw']['record'], proof['raw']['hcc_offset'])
            if key in used:
                raise CaptureError('raw report reused across pairs')
            used.add(key)
            proof['registration_queries'] = {side: metadata[json_identity(row[side])] for side in ['tx', 'rx']}
        pairs.append(proofs)
    overlaps = []
    for n, (a, b) in enumerate(zip(*pairs), 1):
        windows = [[max(p['radio_commands'][2]['reply']['wall_ns'], p['radio_commands'][4]['reply']['wall_ns']),
                    min(p['radio_commands'][5]['command']['wall_ns'], p['radio_commands'][6]['command']['wall_ns'])] for p in [a, b]]
        start, end = max(v[0] for v in windows), min(v[1] for v in windows)
        if start >= end:
            raise CaptureError('actual on-air START/OFF intervals did not overlap')
        overlaps.append(dict(round=n, actual_radio_windows=windows, overlap_wall_ns=[start, end]))
    return dict(status='FOUR_REAL_PARALLEL_RF_CORROBORATED', pairs=pairs, overlaps=overlaps,
                actual_pair_start_gaps_ns=[b['radio_commands'][2]['command']['wall_ns']-a['radio_commands'][2]['command']['wall_ns'] for a,b in zip(*pairs)],
                second_pair_start_offset_ms=record['second_pair_start_offset_ms'],
                policy_expectation=expectation,
                configured_parameter_proofs=policies,
                policy_readback_proofs=[p for w in record['workers'] for p in query_proofs(w['run'], expectation['data'])] if expectation else [],
                default_parallel_gate_acceptance=bool(expectation) and not expectation['data']['custom_configuration'] and expectation['data']['policies'] == {'defaults': DEFAULT, 'adapters': {}} and record['second_pair_start_offset_ms'] == 0,
                custom_policy_parallel_contrast_acceptance=bool(expectation) and expectation['data']['custom_configuration'],
                historical_parameter_scope=expectation is None,
                parallel_offset_contrast_acceptance=record['second_pair_start_offset_ms'] != 0,
                whole_concurrency_acceptance=False,
                four_device_two_pair_rf_acceptance=True, physical_unplug_acceptance=False,
                automatic_fault_recovery_acceptance=False, full_goal_complete=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run', 'pair'])
    parser.add_argument('--ports', nargs='+', required=True)
    parser.add_argument('--slctl', type=Path, required=True)
    parser.add_argument('--slkd-pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--policy-expectation', type=Path, required=True,
                        help='immutable expectation produced by the actual staged daemon, not a TOML reimplementation')
    parser.add_argument('--pair', type=int, choices=[0, 1])
    parser.add_argument('--second-pair-start-offset-ms', type=start_offset, default=0,
                        help='explicit diagnostic contrast; default parallel gate remains offset 0')
    parser.add_argument('--start-offset-ms', type=start_offset, default=0)
    args = parser.parse_args()
    if args.mode == 'run':
        if args.pair is not None or args.start_offset_ms: parser.error('pair selector/offset is internal to worker mode')
        return run_parallel(args)
    if args.pair is None or len(args.ports) != 2 or len(set(args.ports)) != 2 or args.second_pair_start_offset_ms:
        parser.error('worker requires explicit pair and two distinct ports')
    args.artifact = ['parallel_control='+str(Path(__file__).resolve()),
                     'policy_verifier='+str(Path(__file__).with_name('ws73_discovery_policy_capture.py').resolve()),
                     'rf_verifier='+str(Path(__file__).with_name('ws73_rf_rounds.py').resolve())]
    return PairRun(args).execute()


if __name__ == '__main__':
    raise SystemExit(main())
