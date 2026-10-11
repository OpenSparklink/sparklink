#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit VM-only never-selected Managed queue release/last-file-close gate."""
import argparse
import ctypes
import errno
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / ('python' if (HERE.parent / 'python').is_dir() else 'bindings/python')))
from sparklink.native import NativeAdapter
from sparklink.structs import SleControllerSnapshot, SleDiscoveryResult, SleDiscoverySubmit, SleManagementQuery
from ws73_diagnostic_hold import write_marker


def decode(kind, raw):
    if not isinstance(raw, str) or len(raw) != ctypes.sizeof(kind)*2 or not re.fullmatch('[0-9a-f]+', raw):
        raise ValueError('complete canonical UAPI bytes required')
    return kind.from_buffer_copy(bytes.fromhex(raw))


def setup(raw, index, generation=None):
    s = decode(SleControllerSnapshot, raw)
    if (s.version != 1 or s.flags != 2 or s.profile != 1 or s.valid_fields != 1 or s.error
            or s.dev_index != index or not s.generation or (generation is not None and s.generation != generation)):
        raise ValueError('exact untouched Setup snapshot required')
    return s


def metadata_ready(share):
    path = Path(share)/'setup-release/metadata-0.json'
    if not path.exists():
        return False
    value = json.loads(path.read_text())
    if set(value) != {'slot', 'initial_snapshot'} or type(value['slot']) is not int or value['slot'] != 0:
        raise ValueError('exact Setup metadata marker required')
    setup(value['initial_snapshot'], 0)
    return True


def query(raw, generation, state):
    q = decode(SleManagementQuery, raw)
    if (q.version != 1 or q.generation != generation or q.state != state or q.mode != (1 if state == 1 else 0)
            or any([q.lease, q.flags, q.error, q.status, q.opcode, q.reserved])):
        raise ValueError('independent lease observer state required')


def verify_records(record):
    synthetic = record.get('synthetic_support', False)
    if type(synthetic) is not bool:
        raise ValueError('exact synthetic evidence scope required')
    expected_status = ('QUEUED_UNKNOWN_SETUP_RELEASE_SYNTHETIC_SUPPORT_PASS' if synthetic
                       else 'QUEUED_UNKNOWN_SETUP_RELEASE_LIVE_PASS')
    if (type(record.get('format_version')) is not int or record.get('format_version') != 2
            or record.get('status') != expected_status
            or type(record.get('probe_exit')) is not int or record.get('probe_exit') != 0 or record.get('daemon_running') is not False
            or record.get('physical_acceptance') is not False or record.get('automatic_fault_recovery_acceptance') is not False):
        raise ValueError('limited Setup lease gate format required')
    snapshots = record['initial_snapshots']
    if len(snapshots) != 2:
        raise ValueError('two independent Setup registrations required')
    identities = [setup(raw, index) for index, raw in enumerate(snapshots)]
    if identities[0].generation == identities[1].generation:
        raise ValueError('independent generations required')
    cases = record['cases']
    expected = [(i, kind) for i in [0, 1] for kind in ['explicit-release', 'last-fd-close', 'dup-last-fd-close']]
    if [(v['index'], v['case']) for v in cases] != expected:
        raise ValueError('both roles and all three real file cases required')
    previous = 0
    for case_number, v in enumerate(cases):
        if not all(type(v[k]) is int for k in ['index', 'generation', 'peer_index', 'peer_generation', 'wrong_token_errno']):
            raise ValueError('exact integer identity and error fields required')
        index = v['index']; peer = 1-index; generation = identities[index].generation
        if (v['peer_index'] != peer or v['generation'] != generation or v['peer_generation'] != identities[peer].generation
                or type(v['start_wall_ns']) is not int or type(v['end_wall_ns']) is not int
                or not previous < v['start_wall_ns'] < v['end_wall_ns']
                or not 340_000_000 <= v['end_wall_ns']-v['start_wall_ns'] <= 5_000_000_000):
            raise ValueError('ordered bounded real release intervals required')
        previous = v['end_wall_ns']
        if (v['scheduler_restored'] is not True or type(v['critical_start_ns']) is not int
                or type(v['critical_end_ns']) is not int
                or not v['start_wall_ns'] <= v['critical_start_ns'] < v['critical_end_ns'] <= v['end_wall_ns']
                or v['critical_end_ns']-v['critical_start_ns'] >= 50_000_000):
            raise ValueError('bounded FIFO section and restored normal scheduling required')
        if len(v['queued']) != 2 or len(v['cancelled']) != 2:
            raise ValueError('both actual typed policy domains required')
        for domain in range(2):
            for key, state, error in [('queued', 1, 0), ('cancelled', 5, -errno.ECANCELED)]:
                result = decode(SleDiscoveryResult, v[key][domain])
                expected = SleDiscoveryResult(version=1, generation=generation,
                    request_id=(case_number%3)*2+1+domain,
                    profile=1, operation=(5, 4)[domain], count=(2, 1)[domain],
                    dev_index=index, state=state, error=error)
                if bytes(result) != bytes(expected):
                    raise ValueError('full Queued to Cancelled UAPI with no selected opcode/step required')
        rejected = v['scan_initialize_rejections']
        if len(rejected) != 2:
            raise ValueError('Unknown and pending-advertising scan admission guards required')
        for n, row in enumerate(rejected):
            expected = SleDiscoverySubmit(version=1, generation=generation, profile=1,
                                          request_id=(n+1)*100+case_number%3, operation=6)
            expected.scanning.frame_types = 1
            expected.scanning.interval = 1600
            expected.scanning.window = 800
            if (bytes(decode(SleDiscoverySubmit, row['input'])) != bytes(expected)
                    or type(row['submit_errno']) is not int or row['submit_errno'] != errno.EBUSY
                    or type(row['result_errno']) is not int or row['result_errno'] != errno.ENOENT):
                raise ValueError('rejected scan initialization must remain unadmitted, without a result')
        for a, b, raw in [('snapshot_before', 'snapshot_after', snapshots[index]), ('peer_before', 'peer_after', snapshots[peer])]:
            if v[a] != v[b] or v[a] != raw:
                raise ValueError('full Setup metadata and survivor must remain unchanged')
        if v['radio_before'] != v['radio_after']:
            raise ValueError('radio state changed during no-policy lease')
        radio = decode(SleDiscoveryResult, v['radio_after'])
        if radio.version != 1 or radio.generation != generation or radio.radio_adv or radio.radio_scan or radio.error:
            raise ValueError('lease release must preserve Unknown and not invent Off')
        query(v['held'], generation, 1); query(v['free'], generation, 0)
        if type(v['writer_fd']) is not int or v['writer_fd'] < 0 or type(v['duplicate_fd']) is not int:
            raise ValueError('actual file descriptors required')
        if v['case'] == 'dup-last-fd-close':
            if v['duplicate_fd'] < 0 or v['duplicate_fd'] == v['writer_fd']:
                raise ValueError('distinct dup reference required')
            query(v['after_first_close'], generation, 1)
        elif v['duplicate_fd'] != -1 or set(v['after_first_close']) != {'0'}:
            raise ValueError('unexpected duplicate reference')
        if v['wrong_token_errno'] != (errno.EPERM if v['case'] == 'explicit-release' else 0):
            raise ValueError('wrong token must remain rejected')
    return identities


def corroborate(record, capture):
    verify_records(record)
    start = record['cases'][0]['start_wall_ns']; end = record['cases'][-1]['end_wall_ns']
    # Include gaps and both registrations, not just each release syscall.
    traffic = [v for kind in ['commands', 'complete', 'failures'] for v in capture[kind]
               if start <= v['wall_ns'] <= end]
    if traffic:
        raise ValueError('untouched release emitted controller command/reply traffic')
    return {'scope': 'six actual queued two-domain cancellations; one vCPU and privileged bounded FIFO support; whole interval and both devices' ,
            'cases': 6, 'commands': 0, 'completions': 0, 'failures': 0,
            'start_wall_ns': start, 'end_wall_ns': end,
            'synthetic_support': record.get('synthetic_support', False),
            'managed_preselection_live_acceptance': False,
            'managed_unknown_setup_preselection_live_acceptance': not record.get('synthetic_support', False),
            'managed_preselection_synthetic_support_acceptance': record.get('synthetic_support', False),
            'active_ready_peer_isolation_acceptance': False,
            'normal_scheduler_concurrency_acceptance': False, 'setup_preserved': True, 'peer_snapshot_preserved': True,
            'partial_initialization_cleanup_acceptance': False, 'held_transport_fd_close_acceptance': False,
            'automatic_fault_recovery_acceptance': False}


def save_record(folder, record):
    """Progress is replaceable; peer-attachment handshake markers are one-shot."""
    temporary = Path(folder)/'run.tmp'
    temporary.write_text(json.dumps(record, indent=2)+'\n')
    temporary.replace(Path(folder)/'run.json')


def run(args):
    synthetic = bool(getattr(args, 'synthetic_support', False))
    cmdline = Path('/proc/cmdline').read_text().split()
    if synthetic != ('ws73.managed_queue_support=1' in cmdline):
        raise ValueError('explicit matching synthetic boot and collector required')
    if synthetic and (Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU'
                      or not Path('/scratch-root-uuid').is_file()):
        raise ValueError('synthetic support requires dedicated QEMU scratch VM')
    if 'ws73.managed_queue=1' not in Path('/proc/cmdline').read_text().split() or subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode == 0:
        raise ValueError('explicit VM mode before daemon startup required')
    folder = args.output; folder.mkdir(parents=True, exist_ok=False)
    record = {'format_version': 2, 'status': 'RUNNING', 'daemon_running': False,
              'synthetic_support': synthetic,
              'physical_acceptance': False, 'automatic_fault_recovery_acceptance': False,
              'initial_snapshots': [], 'cases': []}
    def save():
        save_record(folder, record)
    adapters = []
    try:
        for index in [0, 1]:
            deadline = time.monotonic()+90
            while True:
                adapter = None
                try:
                    adapter = NativeAdapter(index); snapshot = adapter.snapshot()
                    setup(bytes(snapshot).hex(), index)
                    break
                except OSError as error:
                    if error.errno not in (errno.ENODEV, errno.EAGAIN):
                        raise
                    if adapter is not None:
                        adapter.close()
                if time.monotonic() > deadline:
                    raise TimeoutError('independent Setup metadata availability')
                time.sleep(0.01)
            adapters.append(adapter); record['initial_snapshots'].append(bytes(snapshot).hex()); save()
            if index == 0:
                write_marker(folder/'metadata-0.json', {'slot': 0, 'initial_snapshot': bytes(snapshot).hex()})
        command = [str(args.probe), *[str(a.generation) for a in adapters]]
        with (folder/'probe.jsonl').open('w') as out, (folder/'probe-stderr.txt').open('w') as err:
            p = subprocess.run(command, stdout=out, stderr=err, timeout=15)
        record['probe_exit'] = p.returncode
        record['cases'] = [json.loads(line) for line in (folder/'probe.jsonl').read_text().splitlines()]
        if p.returncode:
            raise ValueError('real release/last-file-close probe failed')
        record['status'] = ('QUEUED_UNKNOWN_SETUP_RELEASE_SYNTHETIC_SUPPORT_PASS' if synthetic
                            else 'QUEUED_UNKNOWN_SETUP_RELEASE_LIVE_PASS')
        verify_records(record); save()
        print('WS73_TARGET_MANAGED_QUEUE_SYNTHETIC_SUPPORT_PASS' if synthetic
              else 'WS73_TARGET_MANAGED_QUEUE_PASS', flush=True)
    except BaseException as error:
        record['status'] = 'FAIL'; record['error'] = str(error); save(); raise
    finally:
        for adapter in adapters:
            adapter.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, default=Path('/bin/managed-queue-probe'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--synthetic-support', action='store_true',
                        help='dedicated simulated USB VM; never live hardware acceptance')
    run(parser.parse_args())
