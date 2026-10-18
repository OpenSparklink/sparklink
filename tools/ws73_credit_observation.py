#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only burst credit evidence, distinct from software queue pressure.

Wire outstanding is observed USB submissions minus NOCP counts, not a proof of
firmware truth. Input captures are unauthenticated; application/identity checks
come from the existing actual ordinary-channel corroborator.
"""
import argparse
import hashlib
import json
from pathlib import Path
from ws73_capture import CaptureError, read_capture
from ws73_channel_socket import corroborate, tx_status_receipts


def observe_phase(row, capture):
    if not row.get('burst') or not row.get('tx_status_required'):
        raise CaptureError('actual burst with required budget snapshots needed')
    values = tx_status_receipts(row)
    samples = [v for v in values if v['role'] == 'initiator']
    ready = [v for v in samples if v['stage'] == 'ready']
    replied = [v for v in samples if v['stage'] == 'replied']
    if len(ready) != 1 or len(replied) != 1:
        raise CaptureError('one initial and final actual source budget required')
    before, after = ready[0], replied[0]
    if before['outstanding'] or after['outstanding'] or after['debt'] or after['queued'] or after['busy']:
        raise CaptureError('initial/final source budget must be drained')
    if after['blocks'] <= before['blocks'] or not any(
        v['stage'] == 'blocked' and v['outstanding'] == v['debt'] == v['capacity']
        and v['blocks'] > before['blocks'] for v in samples
    ):
        raise CaptureError('new actual pool refusal while full required; inherited peak insufficient')
    endpoints = []
    for entry in row['owners']:
        owner, obj = entry['owner'], entry['object']
        key = owner['bus'], owner['device']
        capacity = owner['buffers'][1]
        start, end = row['session_start_wall_ns'], row['end_wall_ns']
        events = []
        for p in capture['acb_packets']:
            if p['direction'] == 'out' and (p['bus'], p['device']) == key and start <= p['wall_ns'] <= end:
                if p['handle'] != obj['handle'] or not p.get('completion'):
                    raise CaptureError('foreign handle or missing USB completion')
                events.append((p['wall_ns'], p['record'], 1, 'submit'))
        for p in capture['native_events']:
            if p['event'] == 9 and (p['bus'], p['device']) == key and start <= p['wall_ns'] <= end:
                raw = bytes.fromhex(p['params'])
                if len(raw) != 3 or int.from_bytes(raw[:2], 'little') != obj['handle'] or not raw[2]:
                    raise CaptureError('malformed/foreign/zero NOCP')
                events.append((p['wall_ns'], p['record'], -raw[2], 'nocp'))
        debt = peak = submits = returns = resumed = full_points = 0
        full_record = release_record = None
        intervals = []
        for wall, record, delta, kind in sorted(events):
            if kind == 'submit':
                submits += 1
                if release_record is not None:
                    resumed += 1
                    intervals.append(dict(full_record=full_record, nocp_record=release_record,
                                          resumed_submit_record=record))
                    full_record = release_record = None
            else:
                returns -= delta
                if debt == capacity and full_record is not None:
                    release_record = record
            debt += delta
            if not 0 <= debt <= capacity:
                raise CaptureError('wire debt exceeds capacity or completion invents credit')
            peak = max(peak, debt)
            if debt == capacity:
                full_points += 1
                full_record = record
        if not events or debt or peak != capacity or not resumed:
            raise CaptureError('real pool full, NOCP and later submission with final drain required')
        endpoints.append(dict(controller=owner['index'], generation=owner['generation'],
                              lifetime=obj['lifetime'], handle=obj['handle'], capacity=capacity,
                              usb_submissions=submits, nocp_packets=returns, wire_peak=peak,
                              wire_final_debt=debt, full_points=full_points,
                              full_nocp_resume_intervals=intervals))
    return dict(phase=row['phase'], source_pool_refusals_delta=after['blocks']-before['blocks'],
                source_full_samples=sum(v['outstanding']==v['capacity'] for v in samples), endpoints=endpoints)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-folder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; sealed evidence must not be overwritten")
    root = args.run_folder
    manifest_file = root/'manifest.json'
    run_file = root/'guest-output/application/passthrough-control/run.json'
    pcap = root/'guest-output/ws73.pcap'
    manifest = json.loads(manifest_file.read_text())
    run = json.loads(run_file.read_text())
    if manifest['status'] != 'PASSTHROUGH_SUPPORT_PASS' or manifest['qemu_exit']:
        raise CaptureError('successful original VM evidence required')
    targets = {(e['owner']['bus'], e['owner']['device']) for row in run['channel_socket'] for e in row['owners']}
    capture = read_capture(pcap, targets)
    proof = corroborate(run, capture)  # real app payloads/UID/roles and both USB ends
    if proof['round_trips'] != 32 or not proof.get('software_backpressure_acceptance'):
        raise CaptureError('both real16-message application burst phases required')
    phases = [observe_phase(row, capture) for row in run['channel_socket']]
    result = dict(status='REAL_BURST_POOL_DEPLETION_AND_NOCP_RESUMPTION_SCOPED_PASS',
                  source=manifest['native_vm'], phases=phases, application_round_trips=32,
                  assumptions=['PCAP USB submission/NOCP observed ordering; original link interval starts drained',
                               'NOCP accuracy is firmware/hardware trust, not proven by a matching count',
                               'No duplicate/late NOCP or handle-reuse barrier qualified',
                               'USB completion is not credit return; only NOCP changes reconstructed debt'],
                  inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [manifest_file,run_file,pcap]},
                  scope='Two real controllers, exchanged roles, fixed channels and SDK111 profile. Supplemental evidence; original manifest remains unchanged.',
                  natural_recovery_qualified=False, whole_credit_proof=False)
    # Source has private deployment paths: publish only accurate source identities.
    result['source']={k:v for k,v in result['source'].items() if k in ['kernel_head','userspace_head']}
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'])


if __name__ == '__main__':
    main()
