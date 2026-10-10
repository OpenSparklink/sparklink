#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in VM diagnostic owner/CAP/usercopy/retirement gate with real metadata.

Runs before slkd, releasing Diagnostic before Managed starts. An old fd stays
open through the enclosing artificial recovery, without holding a lease.
"""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / ('python' if (HERE.parent / 'python').is_dir() else 'bindings/python')))
from sparklink.structs import SleDiagnosticResult, SleDiagnosticSubmit
from ws73_north_star import file_record

NEGATIVE = {'inherited_fd_cap0': errno.EPERM, 'version': errno.EOPNOTSUPP,
            'flags': errno.EINVAL, 'reserved': errno.EINVAL, 'zero_seq': errno.EINVAL,
            'zero_generation': errno.EINVAL, 'wrong_generation': errno.ENODEV,
            'missing_sequence': errno.ENOENT, 'foreign_author_with_lease': errno.EPERM,
            'retired_fd': errno.ENODEV}
ORDER = ['metadata'] * 4 + ['inherited_fd_cap0', 'read_only_output', 'partial_output',
         'version', 'flags', 'reserved', 'zero_seq', 'zero_generation',
         'wrong_generation', 'missing_sequence', 'foreign_author_with_lease', 'retired_fd']
QUERIES = [('mac', 0x0406, 6), ('features', 0x0403, 10), ('version', 0x0404, 5), ('buffers', 0x0402, 6)]


def verify_records(records, final=True, admission=False):
    tags = ('case', 'identity', 'phase', 'admission') if admission else ('case', 'identity', 'phase')
    if any(sum(k in r for k in tags) != 1 for r in records):
        raise ValueError('unknown or ambiguous diagnostic record')
    cases = [r for r in records if 'case' in r]
    if [r['case'] for r in cases] != (ORDER if final else ORDER[:-1]):
        raise ValueError('exact ordered diagnostic syscall cases required')
    metadata = cases[:4]
    generation = metadata[0]['generation']
    if type(generation) is not int or generation <= 0 or len({r['seq'] for r in metadata}) != 4:
        raise ValueError('one exact registration and distinct admissions required')
    for r, (_, opcode, length) in zip(metadata, QUERIES):
        if (r['generation'] != generation or type(r['seq']) is not int or r['seq'] <= 0
                or r['opcode'] != opcode or len(bytes.fromhex(r['data'])) != length
                or type(r['start_wall_ns']) is not int or r['start_wall_ns'] <= 0
                or type(r['end_wall_ns']) is not int or r['end_wall_ns'] <= r['start_wall_ns']):
            raise ValueError('metadata identity/opcode/length/clock mismatch')
    for r in cases[4:]:
        expected = errno.EFAULT if r['case'] in ('read_only_output', 'partial_output') else NEGATIVE[r['case']]
        if type(r['result']) is not int or r['result'] != -1 or type(r['errno']) is not int or r['errno'] != expected:
            raise ValueError('diagnostic syscall errno mismatch')
        if r['case'] in ('read_only_output', 'partial_output'):
            raw = bytes.fromhex(r['reference'])
            if len(raw) != ctypes.sizeof(SleDiagnosticResult) or r['retry'] != r['reference']:
                raise ValueError('failed copy consumed or changed result')
            value = SleDiagnosticResult.from_buffer_copy(raw)
            if (value.version != 1 or value.flags or value.generation != generation
                    or value.seq != metadata[0]['seq'] or value.opcode != 0x0406
                    or value.state != 2 or value.error or value.status or value.data_len != 6
                    or value._pad or any(value._reserved)
                    or bytes(value.data[:6]).hex() != metadata[0]['data'] or any(value.data[6:])):
                raise ValueError('retry does not match exact successful metadata result')
            prefix = 56 if r['case'] == 'partial_output' else 0
            if type(r['partial_prefix']) is not int or r['partial_prefix'] != prefix:
                raise ValueError('actual copy boundary mismatch')
    if admission: verify_admissions(records)
    child = [r for r in records if r.get('identity') == 'inherited_fd_child']
    if child != [{'identity': 'inherited_fd_child', 'uid': 1000, 'euid': 1000, 'cap_eff': 0, 'cap_prm': 0}] or any(type(r[k]) is not int for r in child for k in ('uid', 'euid', 'cap_eff', 'cap_prm')):
        raise ValueError('actual inherited fd child identity/capabilities required')
    phases = [r['phase'] for r in records if 'phase' in r]
    if phases != (['BEFORE_DAEMON_PASS', 'DIAGNOSTIC_RESULT_LIVE_PASS'] if final else ['BEFORE_DAEMON_PASS']):
        raise ValueError('diagnostic phase/retirement completion missing')


def verify_admissions(records):
    """Two actual copyout failures, exact retry identity/bytes and counters.

    The capture verifier separately requires a single completed OUT/reply over
    each entire failure/retry interval. Records alone are not wire evidence.
    """
    rows = [r for r in records if 'admission' in r]
    metadata = [r for r in records if r.get('case') == 'metadata']
    if [r['admission'] for r in rows] != ['submit_read_only_output', 'submit_partial_output']:
        raise ValueError('both ordered actual admission copyout cases required')
    for i, (r, meta) in enumerate(zip(rows, metadata)):
        prefix = 36 if i else 0
        if (type(r['result']) is not int or r['result'] != -1
                or type(r['errno']) is not int or r['errno'] != errno.EFAULT
                or type(r['partial_prefix']) is not int or r['partial_prefix'] != prefix
                or type(r['user_address_mod8']) is not int or r['user_address_mod8'] != (4 if i else 0)
                or type(r['request_id']) is not int or r['request_id'] != i + 1):
            raise ValueError('actual admission copyout errno/identity/boundary required')
        for field in ('generation', 'seq', 'opcode', 'start_wall_ns', 'end_wall_ns'):
            if type(r[field]) is not int or r[field] != meta[field]:
                raise ValueError('admission interval/sequence differs from metadata proof')
        raw = bytes.fromhex(r['input'])
        if len(raw) != ctypes.sizeof(SleDiagnosticSubmit):
            raise ValueError('exact canonical admission input bytes required')
        value = SleDiagnosticSubmit.from_buffer_copy(raw)
        if (value.version != 1 or value.flags or value.generation != meta['generation']
                or value.request_id != r['request_id'] or value.timeout_ms != 5000
                or value.opcode != meta['opcode'] or value.reserved or value.seq or value.action != 1):
            raise ValueError('admission input fields mismatch')
        value.seq = meta['seq']; expected = bytes(value).hex()
        if r['retry_outputs'] != [expected] * 3:
            raise ValueError('same caller-known ID retry changed admission')
        observed = bytes.fromhex(r['fault_output'])
        if len(observed) != len(raw) or observed != bytes(value)[:prefix] + raw[prefix:]:
            raise ValueError('copyout failure bytes do not show the actual expected prefix')
        for field in ('submitted_before', 'submitted_after', 'resolved_before', 'resolved_after',
                      'pending_before', 'pending_after', 'timeouts_before', 'timeouts_after'):
            if type(r[field]) is not int or not 0 <= r[field] < 1 << 32:
                raise ValueError('actual bounded counters required')
        if (r['submitted_after'] != r['submitted_before'] + 1
                or r['resolved_after'] != r['resolved_before'] + 1
                or r['pending_before'] or r['pending_after']
                or r['timeouts_before'] != r['timeouts_after']):
            raise ValueError('replay changed admission/resolution/timeout accounting')


def run(args):
    if (os.getuid() != 0 or os.geteuid() != 0 or not Path('/scratch-root-uuid').is_file()
            or 'ws73.diagnostic=1' not in Path('/proc/cmdline').read_text().split()):
        raise ValueError('privileged opt-in scratch-root VM required')
    output = args.output.resolve(); output.mkdir(mode=0o700)
    record = {'format_version': 2, 'admission_copyout_requested': True, 'status': 'STARTING', 'scope': 'live real WS73 diagnostic syscall gate in isolated VM',
              'physical_acceptance': False, 'automatic_fault_recovery_acceptance': False,
              'probe': file_record(args.probe), 'sources': [file_record(Path(__file__))],
              'index': args.index, 'records': [], 'cli_queries': [], 'uid': os.getuid(), 'euid': os.geteuid()}
    child = None
    def save(): (output / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
    try:
        save()
        with (output / 'probe-stderr.txt').open('xb') as error, (output / 'probe.jsonl').open('xb') as transcript:
            child = subprocess.Popen([str(args.probe), str(args.index)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=error)
            selector = selectors.DefaultSelector(); selector.register(child.stdout, selectors.EVENT_READ)
            pending = b''; deadline = time.monotonic() + 120; acknowledged = False
            while True:
                if time.monotonic() >= deadline: raise ValueError('diagnostic probe deadline')
                if not acknowledged and (output / 'before-daemon.json').is_file() and args.retired_marker.is_file():
                    child.stdin.write(b'retired\n'); child.stdin.flush(); acknowledged = True
                for key, _ in selector.select(0.1):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj); continue
                    transcript.write(data); transcript.flush(); pending += data
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1); item = json.loads(line)
                        record['records'].append(item); save()
                        if item.get('phase') == 'BEFORE_DAEMON_PASS':
                            verify_records(record['records'], final=False, admission=True)
                            for name, opcode, _ in QUERIES:
                                generation = record['records'][0]['generation']
                                command = [str(args.slkconfig), '--adapter', str(args.index), '--generation', str(generation), 'query', name]
                                start = time.time_ns(); completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
                                row = {'args': command, 'exit': completed.returncode, 'stdout': completed.stdout,
                                       'stderr': completed.stderr, 'start_wall_ns': start, 'end_wall_ns': time.time_ns()}
                                matches = re.findall(r'^NativeDiagnosticQuery: index=(\d+) generation=(\d+) opcode=0x([0-9a-f]+) admission_seq=(\d+) status=0x00 data=([0-9a-f]+)$', completed.stdout, re.M)
                                expected = next(r['data'] for r in record['records'] if r.get('opcode') == opcode)
                                if completed.returncode or len(matches) != 1 or matches[0][:3] != (str(args.index), str(generation), f'{opcode:04x}') or int(matches[0][3]) <= 0 or matches[0][4] != expected:
                                    raise ValueError('actual slkconfig metadata query mismatch')
                                record['cli_queries'].append(row); save()
                            record['status'] = 'BEFORE_DAEMON_PASS'; save()
                            (output / 'before-daemon.json').write_text(json.dumps({'status': record['status']}) + '\n')
                            deadline = time.monotonic() + 180
                if child.poll() is not None and not selector.get_map(): break
            selector.close()
            record['probe_exit'] = child.wait(timeout=5)
            if record['probe_exit'] or pending or not acknowledged: raise ValueError('probe exit or retirement handshake')
        verify_records(record['records'], admission=True)
        record['status'] = 'DIAGNOSTIC_RESULT_LIVE_PASS'; save()
    except BaseException as error:
        record.update(status='FAIL', error=str(error)); save(); raise
    finally:
        if child is not None and child.poll() is None:
            child.kill(); child.wait(timeout=5)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe', required=True, type=Path); p.add_argument('--slkconfig', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path); p.add_argument('--index', type=int, default=0)
    p.add_argument('--retired-marker', type=Path, default=Path('/run/diagnostic-retired'))
    run(p.parse_args())
