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
                       'Only paired Native low-load benchmark intervals;zero capture drops required.',
                       'No callback CPU attribution, RF latency, saturation or multi-URB benefit proof.',
                       'No driver/order/generation/buffer/stop-drain change;original source and failure evidence retained.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.run), indent=2))


if __name__ == '__main__':
    main()
