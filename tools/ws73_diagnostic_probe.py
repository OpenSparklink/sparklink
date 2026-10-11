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
from sparklink.structs import SleDiagnosticResult, SleDiagnosticSubmit, SleDliEvent
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


def verify_records(records, final=True, admission=False, eviction=False, legacy_poll=False, cancellation=False, deadline=False, autonomous=False):
    if autonomous and not deadline:raise ValueError('autonomous evidence requires original deadline gate')
    if not autonomous and any('autonomous' in r for r in records):raise ValueError('autonomous evidence cannot downgrade')
    if deadline and not cancellation:
        raise ValueError('deadline evidence requires real cancellation/hold gate')
    if not deadline and any('deadline' in r for r in records):
        raise ValueError('deadline evidence cannot downgrade')
    if eviction and not admission:
        raise ValueError('eviction evidence requires preceding admission gate')
    if legacy_poll and not eviction:
        raise ValueError('legacy poll evidence requires admission and eviction gates')
    if cancellation and not legacy_poll:
        raise ValueError('cancellation evidence requires preceding legacy and admission gates')
    tags = (('case', 'identity', 'phase') + (('admission',) if admission else ())
            + (('eviction',) if eviction else ()) + (('legacy_poll',) if legacy_poll else ())
            + (('cancel','hold_phase') if cancellation else ()))
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
    if legacy_poll: verify_legacy_poll(records, cancellation=cancellation)
    if cancellation:
        from ws73_diagnostic_cancel import verify_cancellations
        verify_cancellations(records, deadline=deadline,autonomous=autonomous)
    if eviction: verify_evictions(records)
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


def verify_legacy_poll(records, cancellation=False):
    """Canonical real-seed event copy/commit evidence; wire checked separately.

    A Native ring test does not qualify controller.poll_event backend fallback.
    """
    rows = [r for r in records if 'legacy_poll' in r]
    if [r['legacy_poll'] for r in rows] != ['bad_address', 'read_only_output', 'partial_output']:
        raise ValueError('three ordered actual legacy poll copy faults required')
    boundary = next(i for i, r in enumerate(records) if r.get('case') == 'missing_sequence')
    if ([i for i, r in enumerate(records) if 'legacy_poll' in r] != list(range(boundary+1, boundary+4))
            or (records[boundary+4].get('hold_phase') != 'arm_ready' if cancellation
                else records[boundary+4].get('case') != 'foreign_author_with_lease')):
        raise ValueError('legacy faults must precede author release/foreign-fd gate')
    metadata = [r for r in records if r.get('case') == 'metadata']
    generation = metadata[0]['generation']
    previous_seq, previous_end = metadata[-1]['seq'], metadata[-1]['end_wall_ns']
    expected = SleDliEvent(event_type=1, opcode=0x0406, data_len=6)
    expected.data[:6] = bytes.fromhex(metadata[0]['data'])
    canonical_event = bytes(expected)
    if len(canonical_event) != 256:
        raise ValueError('canonical legacy event ABI must remain256 bytes')
    previous_counts = None
    for i, row in enumerate(rows):
        prefix = 128 if i == 2 else 0
        for field in ('generation', 'request_id', 'seq', 'opcode', 'start_wall_ns', 'end_wall_ns',
                      'result', 'errno', 'partial_prefix', 'drained_before', 'final_poll_result', 'final_poll_errno'):
            if type(row[field]) is not int:
                raise ValueError('exact typed legacy fault identity/boundary/results required')
        if (row['generation'] != generation or row['request_id'] != 5+i or row['opcode'] != 0x0406
                or not previous_seq < row['seq'] < 1 << 32
                or not previous_end <= row['start_wall_ns'] < row['end_wall_ns']
                or row['result'] != -1 or row['errno'] != errno.EFAULT
                or row['partial_prefix'] != prefix or not 0 <= row['drained_before'] <= 31
                or i and row['drained_before'] != 0
                or row['final_poll_result'] != -1 or row['final_poll_errno'] != errno.EAGAIN
                or row['data'] != metadata[0]['data']):
            raise ValueError('legacy fault identity/clock/EFAULT/once-consumed EAGAIN mismatch')
        submit = SleDiagnosticSubmit(version=1, generation=generation, request_id=5+i,
                                     timeout_ms=5000, opcode=0x0406, action=1)
        if row['input'] != bytes(submit).hex():
            raise ValueError('legacy seed canonical input mismatch')
        submit.seq = row['seq']
        result = SleDiagnosticResult(version=1, generation=generation, seq=row['seq'],
                                     opcode=0x0406, state=2, data_len=6)
        result.data[:6] = bytes.fromhex(row['data'])
        if row['output'] != bytes(submit).hex() or row['result_bytes'] != bytes(result).hex():
            raise ValueError('legacy seed must have actual exact successful metadata result')
        if row['reference'] != canonical_event.hex() or row['retry'] != row['reference']:
            raise ValueError('legacy retry lost or changed canonical event bytes')
        fault = None if not i else (canonical_event[:prefix] + b'\xa5'*(256-prefix)).hex()
        if row['fault_output'] != fault:
            raise ValueError('legacy fault must show actual prefix and inaccessible unchanged suffix')
        before, after = [], []
        for counter in ('submitted', 'resolved', 'pending', 'timeouts'):
            for suffix, values in [('before', before), ('after', after)]:
                value = row[f'{counter}_{suffix}']
                if type(value) is not int or not 0 <= value < 1 << 32:
                    raise ValueError('actual legacy poll counters required')
                values.append(value)
        if (after[:2] != [v+1 for v in before[:2]] or before[2] or after[2]
                or before[3] != after[3] or previous_counts is not None and before != previous_counts):
            raise ValueError('legacy poll must seed once without changing command accounting on retry')
        previous_counts, previous_seq, previous_end = after, row['seq'], row['end_wall_ns']
    fill = next(r for r in records if r.get('eviction') == 'fill')
    if (fill['seq'] <= previous_seq or fill['start_wall_ns'] < previous_end
            or not cancellation and any(fill[f'{k}_before'] != rows[-1][f'{k}_after']
                   for k in ('submitted', 'resolved', 'pending', 'timeouts'))):
        raise ValueError('legacy poll/eviction sequence, clock or accounting continuity mismatch')


def verify_evictions(records):
    """Actual second-fd retention boundary; wire and quiet window checked apart."""
    rows = [r for r in records if 'eviction' in r]
    if [r['eviction'] for r in rows] != ['fill'] * 33 + ['old_id_and_result_rejected']:
        raise ValueError('33 actual fills and one ordered eviction rejection interval required')
    foreign = next(i for i, r in enumerate(records) if r.get('case') == 'foreign_author_with_lease')
    if [i for i, r in enumerate(records) if 'eviction' in r] != list(range(foreign+1, foreign+35)):
        raise ValueError('foreign author refusal must precede contiguous second-fd eviction gate')
    metadata = [r for r in records if r.get('case') == 'metadata']
    generation = metadata[0]['generation']
    previous_seq, previous_end = metadata[-1]['seq'], metadata[-1]['end_wall_ns']
    counters = ('submitted', 'resolved', 'pending', 'timeouts')
    previous_counts = None
    for i, row in enumerate(rows):
        for field in ('generation', 'request_id', 'seq', 'opcode', 'start_wall_ns', 'end_wall_ns'):
            if type(row[field]) is not int:
                raise ValueError('exact typed eviction identity and interval required')
        if (row['generation'] != generation or row['opcode'] != 0x0406
                or not previous_end <= row['start_wall_ns'] < row['end_wall_ns']):
            raise ValueError('eviction registration/opcode/ordered clock mismatch')
        before, after = [], []
        for counter in counters:
            for suffix, values in [('before', before), ('after', after)]:
                value = row[f'{counter}_{suffix}']
                if type(value) is not int or not 0 <= value < 1 << 32:
                    raise ValueError('actual eviction bounded counters required')
                values.append(value)
        if (before[2] or after[2] or before[3] != after[3]
                or previous_counts is not None and before != previous_counts):
            raise ValueError('eviction quiet accounting/continuity mismatch')
        if i < 33:
            if (row['request_id'] != i+1 or not previous_seq < row['seq'] < 1 << 32
                    or after[:2] != [v+1 for v in before[:2]] or row['data'] != metadata[0]['data']):
                raise ValueError('eviction fill must admit and complete exactly once')
            value = SleDiagnosticSubmit(version=1, generation=generation, request_id=i+1,
                                        timeout_ms=5000, opcode=0x0406, action=1)
            if row['input'] != bytes(value).hex():
                raise ValueError('eviction canonical submission input mismatch')
            value.seq = row['seq']
            result = SleDiagnosticResult(version=1, generation=generation, seq=row['seq'],
                                         opcode=0x0406, state=2, data_len=6)
            result.data[:6] = bytes.fromhex(row['data'])
            if row['output'] != bytes(value).hex() or row['result_bytes'] != bytes(result).hex():
                raise ValueError('eviction complete admission/result bytes mismatch')
            previous_seq = row['seq']
        else:
            first, retained = rows[:2]
            old_query = SleDiagnosticResult(version=1, generation=generation, seq=first['seq'])
            if (row['request_id'] != 1 or row['seq'] != first['seq'] or before != after
                    or row['retry_results'] != [-1]*3 or row['retry_errnos'] != [errno.ESTALE]*3
                    or type(row['result_query_return']) is not int or row['result_query_return'] != -1
                    or type(row['result_query_errno']) is not int or row['result_query_errno'] != errno.ENOENT
                    or row['old_input'] != first['input'] or row['retry_outputs'] != [first['input']]*3
                    or row['result_query_input'] != bytes(old_query).hex()
                    or row['result_query_output'] != row['result_query_input']
                    or row['retained_input'] != retained['input'] or row['retained_output'] != retained['output']
                    or row['retained_result'] != retained['result_bytes']
                    or type(row['quiet_observation_ms']) is not int or row['quiet_observation_ms'] != 100
                    or row['end_wall_ns'] - row['start_wall_ns'] < 100_000_000):
                raise ValueError('old-ID/sequence must reject unchanged, retained ID2 retries and quiet counters must remain')
        previous_counts, previous_end = after, row['end_wall_ns']


def run(args):
    if (os.getuid() != 0 or os.geteuid() != 0 or not Path('/scratch-root-uuid').is_file()
            or 'ws73.diagnostic=1' not in Path('/proc/cmdline').read_text().split()):
        raise ValueError('privileged opt-in scratch-root VM required')
    output = args.output.resolve(); output.mkdir(mode=0o700)
    cancellation = 'ws73.diagnostic_cancel=1' in Path('/proc/cmdline').read_text().split()
    deadline_test = 'ws73.diagnostic_deadline=1' in Path('/proc/cmdline').read_text().split()
    autonomous_test = 'ws73.diagnostic_autonomous=1' in Path('/proc/cmdline').read_text().split()
    if autonomous_test and not deadline_test:raise ValueError('autonomous requires original deadline mode')
    if deadline_test and not cancellation:raise ValueError('deadline requires cancellation hold mode')
    record = {'format_version': 7 if autonomous_test else 6 if deadline_test else 5 if cancellation else 4,
              'deadline_requested':deadline_test,'autonomous_requested':autonomous_test,
              'cancellation_requested':cancellation, 'host_hold_acknowledgements':[],
              'admission_copyout_requested': True, 'admission_eviction_requested': True,
              'legacy_poll_copy_requested': True, 'status': 'STARTING', 'scope': 'live real WS73 diagnostic syscall gate in isolated VM',
              'physical_acceptance': False, 'automatic_fault_recovery_acceptance': False,
              'probe': file_record(args.probe), 'sources': [file_record(Path(__file__))],
              'index': args.index, 'records': [], 'cli_queries': [], 'uid': os.getuid(), 'euid': os.geteuid()}
    child = None
    def save(): (output / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
    try:
        save()
        with (output / 'probe-stderr.txt').open('xb') as error, (output / 'probe.jsonl').open('xb') as transcript:
            child = subprocess.Popen([str(args.probe), str(args.index)]+(['autonomous'] if autonomous_test else ['deadline'] if deadline_test else ['cancel'] if cancellation else []), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=error)
            selector = selectors.DefaultSelector(); selector.register(child.stdout, selectors.EVENT_READ)
            pending = b''; deadline = time.monotonic() + 120; acknowledged = False; hold_pending=None
            while True:
                if time.monotonic() >= deadline: raise ValueError('diagnostic probe deadline')
                if not acknowledged and (output / 'before-daemon.json').is_file() and args.retired_marker.is_file():
                    child.stdin.write(b'retired\n'); child.stdin.flush(); acknowledged = True
                if hold_pending is not None:
                    ack={'arm_ready':'armed','wait_held':'held','release_ready':'released'}[hold_pending]
                    path=output/f'hold-{ack}-ack.json'
                    if path.exists():
                        response=json.loads(path.read_text())
                        if response.get('stage') != ack or response.get('request') != record['records'][-1]:
                            raise ValueError('hold acknowledgment does not match pending phase')
                        record['host_hold_acknowledgements'].append(response);save()
                        child.stdin.write((ack+'\n').encode());child.stdin.flush();hold_pending=None
                for key, _ in selector.select(0.1):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj); continue
                    transcript.write(data); transcript.flush(); pending += data
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1); item = json.loads(line)
                        record['records'].append(item); save()
                        if 'hold_phase' in item:
                            if not cancellation or hold_pending is not None or item['hold_phase'] not in ('arm_ready','wait_held','release_ready'):
                                raise ValueError('unexpected/duplicate hold coordination phase')
                            hold_pending=item['hold_phase']
                            from ws73_diagnostic_hold import write_marker
                            write_marker(output/f'hold-{hold_pending}.json',item)
                        if item.get('phase') == 'BEFORE_DAEMON_PASS':
                            verify_records(record['records'], final=False, admission=True, eviction=True, legacy_poll=True,cancellation=cancellation,deadline=deadline_test,autonomous=autonomous_test)
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
        verify_records(record['records'], admission=True, eviction=True, legacy_poll=True,cancellation=cancellation,deadline=deadline_test,autonomous=autonomous_test)
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
