#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only guest usbmon completion-to-resubmission observations.

Uses the existing strict capture parser and actual paired Native benchmark
windows. Not driver callback CPU time, RF latency or a performance verdict.
No device operations, kernel changes or protocol implementation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from ws73_capture import CaptureError, check_capture_stats, read_capture
from ws73_socket_benchmark import corroborate


def distribution(values):
    if not values:
        raise CaptureError('nonempty RX gap sample required')
    ordered = sorted(values)
    def percentile(p):
        return ordered[math.ceil(len(ordered) * p) - 1]
    return dict(samples=len(values), min_ns=ordered[0], p50_ns=percentile(.5),
                p95_ns=percentile(.95), p99_ns=percentile(.99), max_ns=ordered[-1])


def observe(events, owner, start, end):
    """Check single-URB ownership in this interval; retain edge censoring.

    Pre-window events establish the submission already outstanding at start.
    A completion belongs to exactly its captured submission; its next device
    event must be a resubmission of that same URB. No cross-device pairing.
    """
    if type(start) is not int or type(end) is not int or start >= end:
        raise CaptureError('finite nonempty observation window required')
    selected = [e for e in events if (e['bus'], e['device']) == (owner['bus'], owner['device'])]
    if any(a['wall_ns'] > b['wall_ns'] or a['record'] >= b['record']
           for a, b in zip(selected, selected[1:])):
        raise CaptureError('ordered same-device usbmon clock/records required')
    pending = {}
    rows = []
    ids = set()
    peak = 0
    censored = 0
    for i, e in enumerate(selected):
        t, urb, kind = e['wall_ns'], e['urb'], e['kind']
        if t > end:
            break
        inside = start <= t <= end
        if kind == 'S':
            if inside and urb in pending:
                raise CaptureError('duplicate pending RX URB')
            pending[urb] = e
        elif kind in ('C', 'E'):
            submitted = pending.pop(urb, None)
            if inside:
                if kind != 'C' or e['status']:
                    raise CaptureError('RX error inside measurement window')
                if submitted is None or submitted['wall_ns'] > t or not 0 <= e['length'] <= submitted['length']:
                    raise CaptureError('RX completion missing/mismatching original submission')
                if pending:
                    raise CaptureError('more than one RX URB active at completion')
                ids.add(urb)
                following = selected[i + 1] if i + 1 < len(selected) else None
                if following is None or following['wall_ns'] > end:
                    censored += 1
                    continue
                if following['kind'] != 'S' or following['urb'] != urb:
                    raise CaptureError('next RX event is not same-URB resubmission')
                rows.append(dict(completion_record=e['record'], submission_record=following['record'],
                                 completion_offset=e['file_offset'], submission_offset=following['file_offset'],
                                 completion_wall_ns=t, submission_wall_ns=following['wall_ns'],
                                 gap_ns=following['wall_ns'] - t, bytes=e['length']))
        else:
            raise CaptureError('unknown RX event')
        if inside:
            peak = max(peak, len(pending))
            if peak > 1:
                raise CaptureError('observed multiple outstanding RX URBs')
    if len(ids) != 1 or peak != 1:
        raise CaptureError('one active bulk RX URB identity required in selected window')
    return dict(owner=owner, start_wall_ns=start, end_wall_ns=end,
                gap=distribution([r['gap_ns'] for r in rows]), rows=rows,
                sum_gap_ns=sum(r['gap_ns'] for r in rows),
                window_fraction_without_submitted_rx=sum(r['gap_ns'] for r in rows) / (end - start),
                fraction_scope='Completed paired gaps only; edge-censored intervals are excluded, not assumed zero.',
                completed_bytes=sum(r['bytes'] for r in rows),
                peak_observed_outstanding=peak, right_censored_completions=censored,
                urb_identity_sha256=hashlib.sha256(str(next(iter(ids))).encode()).hexdigest())


def analyze(directory):
    root = Path(directory).resolve(strict=True)
    share = root / 'guest-output'
    run = json.loads((share / 'application/passthrough-control/run.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['status'] != 'PASSTHROUGH_SUPPORT_PASS' or manifest['qemu_exit'] != 0:
        raise CaptureError('terminal successful original Native run required')
    targets = {(o['owner']['bus'], o['owner']['device']) for row in run['socket_benchmark'] for o in row['owners']}
    path = share / 'ws73.pcap'
    capture = read_capture(path, targets, observe_rx=True)
    if check_capture_stats((share / 'capture-stats.txt').read_text()) != capture['packet_count']:
        raise CaptureError('capture count mismatch')
    proof = corroborate(run, capture, share)
    if proof != manifest['socket_benchmark_corroboration']:
        raise CaptureError('independent replay differs from original Native proof')
    windows = []
    for row in run['socket_benchmark']:
        start = min(e['before_wall_ns'] for e in row['events'] if e['kind'] == 'start')
        end = max(e['wall_ns'] for e in row['events'] if e['kind'] == 'quiescent')
        windows.extend(dict(phase=row['phase'], **observe(capture['rx_urbs'], o['owner'], start, end)) for o in row['owners'])
    return dict(schema_version=1, status='OBSERVED_NOT_PERFORMANCE_QUALIFIED',
                run=root.name, mode=proof['mode'], round_trips=proof['round_trips'],
                pcap_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), windows=windows,
                clock='guest usbmon wall clock;1us timestamp quantization;same-device subtraction only',
                scope=['Completion-to-resubmission gap includes callback, USB core and VM scheduling.',
                       'Only original successful paired Native benchmark intervals;zero capture drops required.',
                       'No callback CPU attribution, RF latency, saturation or multi-URB benefit proof.',
                       'No driver/order/generation/buffer/stop-drain change;original source and failure evidence retained.'])


def diagnose_failed(directory, phase):
    """Observe the whole captured failed load phase, not a passing benchmark.

    This entry never calls or relaxes successful qualification. The separate
    failure export validator checks the same original file/size/hash bounds.
    A caller cannot supply a shorter, more convenient time window.
    """
    from ws73_role_snapshot import HELPER, verify_failed
    from ws73_socket_benchmark import request_fields, validate_role_request, application_count
    if type(phase)is not int or phase not in (0,1):
        raise CaptureError('one explicit failed phase0 or1 required')
    root=Path(directory).resolve(strict=True);share=root/'guest-output'
    manifest_path=root/'manifest.json';control_path=share/'application/passthrough-control/run.json'
    manifest=json.loads(manifest_path.read_text());control=json.loads(control_path.read_text())
    if manifest['status']!='FAIL' or manifest['qemu_exit']!=0 or control['status']!='FAIL':
        raise CaptureError('terminal original failed VM/control required; never relabel a PASS')
    parents=[r for r in control['socket_benchmark']if r['phase']==phase]
    if len(parents)!=1:raise CaptureError('one original failed benchmark request required')
    parent=parents[0];path=share/'benchmark-role'/('phase-'+str(phase))
    request_path=control_path.parent/f'benchmark-role-{phase}.request.json'
    request=json.loads(request_path.read_text())
    validate_role_request(request,phase,live=True)
    exported=verify_failed(path,phase=phase,expected_helper=request['tools'][HELPER]['sha256'],kind='benchmark')
    row=json.loads((path/'run.json').read_text())
    stable=request_fields(request)-{'status','applications','events'}
    if (row['status']!='FAIL' or type(row['phase'])is not int or row['phase']!=phase
        or any({k:r[k]for k in stable}!={k:request[k]for k in stable}for r in (row,parent))):
        raise CaptureError('failed local phase must match its original request and owners')
    starts=[e for e in row['events']if e['kind']=='start']
    expected=set(range(len(row['applications'])))
    if (len(expected)!=application_count(request)or len(starts)!=len(expected)
        or any(type(e['application'])is not int for e in starts)or {e['application']for e in starts}!=expected
        or any(type(e['before_wall_ns'])is not int or e['before_wall_ns']<=0 for e in starts)):
        raise CaptureError('all actual application start barriers required')
    start=min(e['before_wall_ns']for e in starts);end=row['end_wall_ns']
    targets={(o['owner']['bus'],o['owner']['device'])for o in row['owners']}
    if len(targets)!=2:raise CaptureError('two distinct original USB owners required')
    pcap=share/'ws73.pcap';stats=share/'capture-stats.txt';capture=read_capture(pcap,targets,observe_rx=True)
    if check_capture_stats(stats.read_text())!=capture['packet_count']:raise CaptureError('capture count mismatch')
    for bus,device in targets:
        stamps=[e['wall_ns']for e in capture['rx_urbs']if(e['bus'],e['device'])==(bus,device)]
        if not stamps or min(stamps)>start or max(stamps)<end:
            raise CaptureError('both original USB owner timelines must cover the complete failed phase')
    windows=[observe(capture['rx_urbs'],o['owner'],start,end)for o in row['owners']]
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(schema_version=1,status='OBSERVED_FAILED_RUN_NOT_QUALIFIED',original_result='FAIL',
                original_phase=phase,original_error=row['error'],original_gate_qualified=False,
                window_rule='All application starts through original failed phase end; no caller clipping.',
                manifest_sha256=digest(manifest_path),control_sha256=digest(control_path),
                request_sha256=digest(request_path),
                snapshot_sha256=digest(path/'snapshot.json'),snapshot_files=len(exported['files']),
                snapshot_success=False,pcap_sha256=digest(pcap),capture_stats_sha256=digest(stats),
                packet_count=capture['packet_count'],windows=windows,
                clock='same-guest usbmon wall clock;1us timestamp quantization;same-device subtraction only',
                scope=['Read-only original failed-run diagnostics; no new VM or hardware qualification.',
                       'Original failures, protocol deadlines and missing application/cleanup gates remain unchanged.',
                       'Completion-to-resubmission includes callback, USB core and VM scheduling, not callback CPU alone.',
                       'No isolated RF latency, stable performance, saturation or multi-URB benefit proof.',
                       'No driver/order/generation/buffer/stop-drain change or claim.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--failed-phase',type=int,choices=[0,1],
                        help='separate closed failed-load diagnostic; never successful benchmark qualification')
    args = parser.parse_args()
    print(json.dumps(analyze(args.run)if args.failed_phase is None else diagnose_failed(args.run,args.failed_phase),indent=2))


if __name__ == '__main__':
    main()
