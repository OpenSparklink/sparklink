# SPDX-License-Identifier: GPL-2.0-only
"""Finite read-only VM benchmark observations; not a Host or credit ledger.

The owned thread never mutates the shared benchmark record. It only publishes
its bounded receipts after stop/join; every CLI child is separately reaped.
"""
import copy
import os
import selectors
import subprocess
import threading
import time

from ws73_capture import CaptureError
from ws73_session_drain import decode

FIELD = 'transport_observation'
SPEC = dict(version=1, pair_period_ns=1_000_000_000, max_pairs=128,
            duration_ns=128_000_000_000, query_budget_ns=1_250_000_000,
            stream_limit_bytes=8192, report_limit_bytes=33_554_432)
VERIFIERS = ('ws73_transport_watch.py', 'ws73_session_drain.py',
             'ws73_session_service.py', 'ws73_trace_layout.py')
RUNTIME = '/bin/slctl'
CAPABILITIES = {'CapEff', 'CapPrm', 'CapAmb', 'CapInh'}


def ordinary(identity):
    return (identity['uids'] == [1000]*4 and identity['gids'] == [1000]*4
            and identity['groups'] == [] and set(identity['capabilities']) == CAPABILITIES
            and all(int(v, 16) == 0 for v in identity['capabilities'].values()))


def collect_process(args, stop, *, credentials=None):
    """Actual OS process/pipe budgets. Tests use local children, not hardware."""
    row = dict(args=args, start_wall_ns=time.time_ns(), start_monotonic_ns=time.monotonic_ns())
    deadline = row['start_monotonic_ns'] + SPEC['query_budget_ns']
    row['deadline_monotonic_ns'] = deadline
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=0, **(credentials or {}))
    row['pid'] = proc.pid
    selector = selectors.DefaultSelector()
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    outcome = 'EXITED'
    try:
        from ws73_application_client import process_identity
        try:
            row['credentials'], status = process_identity(proc.pid, 1000)
            if len(status.encode()) > 16384:
                raise CaptureError('process identity byte budget')
            row['process_status'] = status
        except (OSError, CaptureError) as error:
            row['identity_error'] = str(error)
        for name, pipe in [('stdout', proc.stdout), ('stderr', proc.stderr)]:
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map() or proc.poll() is None:
            if stop.is_set() and proc.poll() is None:
                outcome = 'CANCELLED_OBSERVER_STOP'
                break
            left = (deadline-time.monotonic_ns()) / 1e9
            if left <= 0:
                outcome = 'QUERY_TIMEOUT'
                break
            for key, _ in selector.select(min(.05, left)):
                name = key.data
                try:
                    data = os.read(key.fd, min(4096, SPEC['stream_limit_bytes']+1-len(output[name])))
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output[name].extend(data)
                if len(output[name]) > SPEC['stream_limit_bytes']:
                    outcome = 'OUTPUT_BUDGET'
                    break
            if outcome != 'EXITED':
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=1)
            row['reaped'] = True
        except subprocess.TimeoutExpired:
            row['reaped'] = False
            outcome = 'CHILD_NOT_REAPED'
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
        row.update(exit=proc.returncode, outcome=outcome,
                   end_wall_ns=time.time_ns(), end_monotonic_ns=time.monotonic_ns())
        for name, raw in output.items():
            row[name] = raw.decode(errors='replace')
            if outcome == 'OUTPUT_BUDGET':
                row['output_incomplete'] = True
    return row


def query(entry, stop):
    args = [RUNTIME, '--adapter', entry['owner']['path'], 'transport-status', entry['object']['path']]
    row = collect_process(args, stop, credentials=dict(user=1000, group=1000, extra_groups=[], umask=0o077))
    if row['outcome'] == 'EXITED':
        try:
            identity = row['credentials']
            if not ordinary(identity):
                raise CaptureError('ordinary observation caller credentials required')
            row['values'] = decode(row, entry)
            row['outcome'] = 'SNAPSHOT_OBSERVED'
        except (CaptureError, KeyError) as error:
            row['observation_error'] = str(error)
            row['outcome'] = 'METHOD_OR_IDENTITY_REJECTED'
    return row


def require_environment():
    """Reuse each guard for its own supported role, before any child/thread."""
    from pathlib import Path
    from ws73_application_role import require_vm
    from ws73_session_service import vm_guard, collector_boot, FULL_LOAD_PROFILE
    require_vm('ws73.socket_benchmark_apps=1')
    vm_guard()
    tokens = Path('/proc/cmdline').read_text().split()
    if tokens.count('ws73.session_service=1') != 1 or collector_boot(tokens) != FULL_LOAD_PROFILE:
        raise CaptureError('one explicit full-load-v2 Session observation VM required')


class Watch:
    def __init__(self, owners, phase):
        self.owners = copy.deepcopy(owners)
        self.stop_event = threading.Event()
        self.armed = threading.Event()
        self.thread = threading.Thread(target=self._run, name='ws73-transport-watch', daemon=False)
        self.report = dict(version=1, spec=dict(SPEC), phase=phase, samples=[], missed_pairs=[],
                           status='STARTING_NOT_QUALIFIED', performance_qualified=False)
        self.closed = False

    def start(self):
        require_environment()
        self.thread.start()
        if not self.armed.wait(1):
            self.close()
            raise CaptureError('transport observer did not arm within original supervisor budget')
        return self

    def _run(self):
        try:
            start = time.monotonic_ns()
            self.report.update(start_monotonic_ns=start, start_wall_ns=time.time_ns(),
                               status='RUNNING_NOT_QUALIFIED')
            self.armed.set()
            pair = 0
            while pair < SPEC['max_pairs'] and not self.stop_event.is_set():
                planned = start + pair*SPEC['pair_period_ns']
                if self.stop_event.wait(max(0, (planned-time.monotonic_ns())/1e9)):
                    break
                now = time.monotonic_ns()
                due = (now-start)//SPEC['pair_period_ns']
                if due > pair:
                    self.report['missed_pairs'].append(dict(first=pair, stop=min(due, SPEC['max_pairs'])))
                    pair = due
                    if pair >= SPEC['max_pairs']:
                        break
                    planned = start + pair*SPEC['pair_period_ns']
                for endpoint, entry in enumerate(self.owners):
                    if self.stop_event.is_set():
                        break
                    if time.monotonic_ns()+SPEC['query_budget_ns'] > start+SPEC['duration_ns']:
                        self.report['status'] = 'OBSERVATION_BUDGET_REACHED'
                        return
                    receipt = query(entry, self.stop_event)
                    self.report['samples'].append(dict(pair=pair, endpoint=endpoint,
                                                       planned_monotonic_ns=planned, receipt=receipt))
                    if not receipt['reaped']:
                        raise CaptureError('unreaped observer query; no further child admission')
                pair += 1
            self.report['status'] = ('STOPPED_JOIN_PENDING' if self.stop_event.is_set()
                                     else 'OBSERVATION_BUDGET_REACHED')
        except BaseException as error:
            self.report.update(status='OBSERVER_ERROR', error=type(error).__name__+': '+str(error))
        finally:
            self.report.update(end_wall_ns=time.time_ns(), end_monotonic_ns=time.monotonic_ns())
            self.armed.set()

    def close(self):
        if self.closed:
            return self.report
        self.closed = True
        self.report_stop_wall_ns = time.time_ns()
        self.report_stop_monotonic_ns = time.monotonic_ns()
        self.stop_event.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            # Do not read a concurrently mutable report or claim drain.
            raise CaptureError('transport observer join timeout; VM gate cannot pass')
        self.report.update(stop_wall_ns=self.report_stop_wall_ns,
                           stop_monotonic_ns=self.report_stop_monotonic_ns, thread_joined=True)
        due = min(SPEC['max_pairs'], max(0, (self.report_stop_monotonic_ns
                  - self.report['start_monotonic_ns'])//SPEC['pair_period_ns']+1))
        observed = {sample['pair'] for sample in self.report['samples']}
        self.report['unattempted_pairs'] = sorted(set(range(due))-observed)
        if self.report['status'] == 'STOPPED_JOIN_PENDING':
            self.report['status'] = 'BOUNDED_READONLY_OBSERVATION_COMPLETE'
        return self.report


def _validate(row, requested, *, failed):
    """Collection integrity only; failures/missing snapshots are not zero data."""
    if failed:
        if row.get('status') != 'FAIL' or not isinstance(row.get('error'), str) or not row['error']:
            raise CaptureError('original failed role with actual error required')
    elif requested and row.get('status') == 'FAIL':
        raise CaptureError('failed role is not a successful observation qualification')
    report = row.get(FIELD)
    if not requested:
        if report is not None:
            raise CaptureError('unrequested transport observation')
        return None
    if (not isinstance(report, dict) or report.get('version') != 1
            or type(report['version']) is not int or report.get('spec') != SPEC
            or any(type(report['spec'][k]) is not int for k in SPEC)
            or type(report.get('phase')) is not int or report.get('phase') != row['phase'] or report.get('thread_joined') is not True
            or report.get('status') != 'BOUNDED_READONLY_OBSERVATION_COMPLETE'
            or report.get('performance_qualified') is not False
            or not 1 <= len(report['samples']) <= SPEC['max_pairs']*2):
        raise CaptureError('complete bounded requested transport observer required')
    import json
    if len(json.dumps(report).encode()) > SPEC['report_limit_bytes']:
        raise CaptureError('transport report byte budget')
    if any(type(report[k])is not int for k in ('start_wall_ns','start_monotonic_ns',
            'stop_wall_ns','stop_monotonic_ns','end_wall_ns','end_monotonic_ns')):
        raise CaptureError('integer original observation clocks required')
    if not (row['start_wall_ns'] <= report['start_wall_ns'] <= report['stop_wall_ns']
            <= report['end_wall_ns'] <= row['end_wall_ns']):
        raise CaptureError('observer must stay within the original role phase')
    starts = [e['before_wall_ns'] for e in row['events'] if e['kind'] == 'start']
    ends = [e['wall_ns'] for e in row['events'] if e['kind'] == 'quiescent']
    if not starts or report['start_wall_ns'] > min(starts):
        raise CaptureError('observer must cover original application start barriers')
    if not failed and (not ends or report['stop_wall_ns'] < max(ends)):
        raise CaptureError('observer must cover the original quiescent barriers')
    seen, successful = set(), [0, 0]
    previous = (-1, -1)
    previous_end = report['start_monotonic_ns']
    for sample in report['samples']:
        pair, endpoint = sample['pair'], sample['endpoint']
        if (type(pair) is not int or not 0 <= pair < SPEC['max_pairs']
                or type(endpoint) is not int or endpoint not in (0, 1)
                or (pair, endpoint) in seen or (pair, endpoint) <= previous):
            raise CaptureError('unique bounded original observation slot required')
        seen.add((pair, endpoint))
        previous = pair, endpoint
        receipt = sample['receipt']
        entry = row['owners'][endpoint]
        if (any(type(receipt[k])is not int for k in ('start_wall_ns','start_monotonic_ns',
                'end_wall_ns','end_monotonic_ns','deadline_monotonic_ns','exit'))
                or type(sample['planned_monotonic_ns'])is not int):
            raise CaptureError('integer original query clocks/exit required')
        if (sample['planned_monotonic_ns'] != report['start_monotonic_ns']+pair*SPEC['pair_period_ns']
                or not sample['planned_monotonic_ns'] <= receipt['start_monotonic_ns']
                or receipt['start_monotonic_ns'] < previous_end
                or not receipt['start_monotonic_ns'] <= receipt['end_monotonic_ns'] <= report['end_monotonic_ns']
                or not report['start_wall_ns'] <= receipt['start_wall_ns'] <= receipt['end_wall_ns'] <= report['end_wall_ns']
                or receipt['args'] != [RUNTIME, '--adapter', entry['owner']['path'], 'transport-status', entry['object']['path']]
                or type(receipt['pid']) is not int or receipt['pid'] <= 0
                or receipt['deadline_monotonic_ns'] != receipt['start_monotonic_ns']+SPEC['query_budget_ns']
                or receipt['reaped'] is not True
                or receipt['outcome'] not in ('SNAPSHOT_OBSERVED', 'METHOD_OR_IDENTITY_REJECTED',
                                              'CANCELLED_OBSERVER_STOP', 'QUERY_TIMEOUT')
                or max(len(receipt[k].encode()) for k in ('stdout', 'stderr')) > SPEC['stream_limit_bytes']):
            raise CaptureError('original bounded/reaped query receipt required')
        previous_end = receipt['end_monotonic_ns']
        if receipt['outcome'] == 'SNAPSHOT_OBSERVED':
            if (not isinstance(receipt.get('values'),dict)
                    or any(type(v)is not int for v in receipt['values'].values())
                    or decode(receipt, row['owners'][endpoint]) != receipt['values']):
                raise CaptureError('actual production snapshot must match receipt')
            identity = receipt['credentials']
            if not ordinary(identity):
                raise CaptureError('ordinary actual snapshot observer credentials required')
            successful[endpoint] += 1
        elif 'values' in receipt:
            raise CaptureError('failed observation must not manufacture snapshot values')
    if not all(successful):
        raise CaptureError('each actual endpoint needs an observed snapshot; missing is not zero')
    skipped = set()
    for gap in report['missed_pairs']:
        first, stop = gap['first'], gap['stop']
        if type(first) is not int or type(stop) is not int or not 0 <= first < stop <= SPEC['max_pairs']:
            raise CaptureError('bounded missed original observation slots required')
        for pair in range(first, stop):
            if pair in skipped:
                raise CaptureError('duplicate missed observation slot')
            skipped.add(pair)
    observed = {pair for pair, _ in seen}
    due = min(SPEC['max_pairs'], max(0, (report['stop_monotonic_ns']
              - report['start_monotonic_ns'])//SPEC['pair_period_ns']+1))
    unattempted = set(range(due))-observed
    if (type(report.get('unattempted_pairs'))is not list or any(type(v)is not int for v in report['unattempted_pairs'])
            or report['unattempted_pairs'] != sorted(unattempted)
            or not observed <= set(range(due))
            or not set(range(max(observed)+1))-observed <= skipped <= unattempted):
        raise CaptureError('missed cadence slots cannot disappear or be fabricated')
    if any((pair, 0) not in seen or (pair, 1) not in seen for pair in observed-{max(observed)}):
        raise CaptureError('only final stop may leave a partial observation pair')
    return dict(status=('FAILED_ROLE_READONLY_TRANSPORT_OBSERVATIONS_NOT_QUALIFIED' if failed
                        else 'BOUNDED_READONLY_TRANSPORT_COLLECTION_ONLY'), samples=len(seen),
                successes=successful, failures=len(seen)-sum(successful),
                credit_truth_qualified=False, physical_drain_qualified=False,
                performance_qualified=False)


def valid_summary(value):
    try:
        successes=value['successes']
        return (value['status']=='BOUNDED_READONLY_TRANSPORT_COLLECTION_ONLY'
                and type(value['samples'])is int and 2<=value['samples']<=SPEC['max_pairs']*2
                and type(successes)is list and len(successes)==2
                and all(type(v)is int and v>0 for v in successes)
                and type(value['failures'])is int and value['failures']>=0
                and sum(successes)+value['failures']==value['samples']
                and all(value[k]is False for k in ('credit_truth_qualified','physical_drain_qualified','performance_qualified')))
    except(KeyError,TypeError):return False


def validate(row, requested):
    """Normal collection check; never accepts a failed role as qualified."""
    return _validate(row, requested, failed=False)


def diagnose_failed(directory, phase):
    """Separate original failed snapshot; no clipping, RX or whole-run PASS."""
    import hashlib
    from ws73_rx_gap import failed_phase_inputs
    from ws73_benchmark_ssap import FIELD as SERVICE, selected, observing, from_boot
    root, manifest, control, request, row, exported = failed_phase_inputs(directory, phase)
    service = selected(request)
    if (not observing(service) or selected(row) != service or manifest.get(SERVICE) != service
            or from_boot(manifest['qemu_args'][manifest['qemu_args'].index('-append')+1].split()) != service):
        raise CaptureError('original explicit observed request/boot/manifest required')
    from ws73_socket_benchmark import application_count
    starts = [e for e in row['events'] if e['kind'] == 'start']
    if (len(starts) != application_count(request)
            or any(type(e['application']) is not int for e in starts)
            or {e['application'] for e in starts} != set(range(application_count(request)))):
        raise CaptureError('all original actual application start barriers required')
    proof = _validate(row, True, failed=True)
    share = root/'guest-output'
    paths = [root/'manifest.json', share/'application/passthrough-control/run.json',
             share/'application/passthrough-control'/f'benchmark-role-{phase}.request.json',
             share/'benchmark-role'/f'phase-{phase}'/'snapshot.json',
             share/'benchmark-role'/f'phase-{phase}'/'run.json']
    return dict(schema_version=1, status='OBSERVED_FAILED_RUN_NOT_QUALIFIED',
                original_result='FAIL', original_phase=phase, original_error=row['error'],
                original_gate_qualified=False, observation=proof, snapshot_success=False,
                snapshot_files=len(exported['files']),
                material_sha256={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                scope=['Original complete failed-role observation export only; no caller clipping.',
                       'No RX-capture coverage, credit truth, drain, performance or whole-run qualification.',
                       'All missing/failed queries retained, not zero-filled; actual snapshot is not NOCP attribution.'])


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--failed-phase', type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose_failed(args.run, args.failed_phase), indent=2))
