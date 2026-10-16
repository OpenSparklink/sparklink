#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only per-message USB intervals from existing dual-end benchmark proofs.

Same-guest usbmon wall-clock intervals and application-local monotonic intervals
are separate. No RF isolation, clock subtraction, NOCP delivery or performance
qualification. New trace controls operate only inside the existing isolated VM.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from ws73_benchmark import distribution
from ws73_capture import CaptureError, check_capture_stats, read_capture
from ws73_socket_benchmark import corroborate


def material(path):
    data=path.read_bytes()
    return dict(path=str(path),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))


def check_xhci(share, mode):
    share=Path(share)
    if mode not in ('on','off'):raise CaptureError('explicit xHCI comparison mode')
    rows=[json.loads((share/f'benchmark-xhci-{name}.json').read_text()) for name in ['start','end']]
    cookie=rows[0].get('cookie')
    if not isinstance(cookie,str) or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',cookie):raise CaptureError('actual per-boot trace identity')
    expected=dict(enabled='1' if mode=='on' else '0',tracing_on='1' if mode=='on' else '0',tracer='nop',buffer_kb=1024,cookie=cookie)
    if any(type(v.get('buffer_kb')) is not int for v in rows) or rows!=[expected,expected]:raise CaptureError('actual trace start/end configuration differs')
    path=share/'xhci-trace.log';text=path.read_text();stats=(share/'xhci-trace-stats.txt').read_text()
    if len(text)>8*1024*1024 or 'LOST' in text.upper() or re.findall(r'^# tracer: (.*)$',text,re.M)!=['nop']:raise CaptureError('bounded loss-free nop event trace required')
    header=re.findall(r'#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)',text)
    if len(header)!=1 or header[0][0]!=header[0][1]:raise CaptureError('complete trace buffer required')
    for key in ['overrun','commit overrun','dropped events']:
        if re.findall(r'^'+key+r':\s*(\d+)\s*$',stats,re.M)!=['0','0']:raise CaptureError('both CPU trace loss statistics required')
    entries=re.findall(r'^entries:\s*(\d+)\s*$',stats,re.M)
    if len(entries)!=2 or sum(map(int,entries))!=int(header[0][0]):raise CaptureError('trace/CPU entry counts disagree')
    events=[]
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):continue
        match=re.search(r'\d+\.\d+:\s*(.*)$',line)
        if not match:raise CaptureError('unparsed xHCI trace row')
        events.append(match[1])
    if len(events)!=int(header[0][0]):raise CaptureError('truncated trace rows')
    if mode=='off':
        if events:raise CaptureError('disabled trace contains events')
    else:
        begin='tracing_mark_write: SLK_BENCH_BEGIN:'+cookie;end='tracing_mark_write: SLK_BENCH_END:'+cookie
        if events.count(begin)!=1 or events.count(end)!=1 or events.index(begin)>=events.index(end):raise CaptureError('original ordered trace interval markers required')
        if not any(v.startswith('xhci_') for v in events[events.index(begin)+1:events.index(end)]):raise CaptureError('actual xHCI positive work required')
        if any(not v.startswith('xhci_') and v not in (begin,end) for v in events):raise CaptureError('unexpected event outside requested xHCI observation')
    return dict(status='XHCI_CONFIGURATION_AND_SEAL_CORROBORATED',mode=mode,entries=len(events),cookie=cookie,
                trace=material(path),scope='Start/end readback and complete finite VM trace;usbmon remains enabled;not all observer overhead or kernel concurrency proof')


def intervals(run, proof):
    """Derive intervals only after original full application/capture corroboration.

    OUT completion may follow the opposite IN; it is not an air timestamp or a
    credit return. Parts retained here are indices/hashes, not copied payloads.
    """
    rows=[]
    for phase,verified in zip(run['socket_benchmark'],proof['proofs']):
        legs=iter(verified['legs'])
        for index,app in enumerate(phase['applications']):
            for original in app['report']['outgoing']:
                request,reply=next(legs),next(legs)
                packets=[request['tx'],request['rx'],reply['tx'],reply['rx']]
                if any(not p.get('fragments') for p in packets) or any(len(p['fragments'])!=1 or p.get('boundary')!=0 for p in [request['tx'],reply['tx']]):raise CaptureError('timeline requires short single-OUT PDU and complete independently reassembled RX')
                a,b,c,d=[p['wall_ns'] for p in packets]
                ca=request['tx']['completion']['wall_ns'];cc=reply['tx']['completion']['wall_ns']
                first_b=request['rx']['fragments'][0]['wall_ns'];first_d=reply['rx']['fragments'][0]['wall_ns']
                if not a<=first_b<=b<=c<=first_d<=d or ca<a or cc<c:raise CaptureError('USB causal interval/OUT completion order invalid')
                timings=dict(request_out_complete=ca-a,request_out_to_peer_in=b-a,peer_in_to_reply_out=c-b,reply_out_complete=cc-c,reply_out_to_source_in=d-c,usb_round_trip=d-a,request_out_to_peer_first_in=first_b-a,peer_rx_assembly_span=b-first_b,reply_out_to_source_first_in=first_d-c,source_rx_assembly_span=d-first_d)
                if timings['usb_round_trip']!=sum(timings[k] for k in ['request_out_to_peer_in','peer_in_to_reply_out','reply_out_to_source_in']):raise CaptureError('USB timeline interval sum')
                rows.append(dict(phase=phase['phase'],source=index,sequence=original['index'],frame_sha256=hashlib.sha256(bytes.fromhex(original['frame_hex'])).hexdigest(),
                    application_monotonic_ns=dict(rtt=original['validated_ns']-original['syscall_ns'],syscall_admission=original['admitted_ns']-original['syscall_ns'],planned_dispatch=original['dispatch_ns']-original['planned_ns']),usb_wall_ns=timings,
                    records=[dict(record=p['record'],bus=p['bus'],device=p['device'],handle=p['handle'],direction=p['direction'],wall_ns=p['wall_ns'],fragments=len(p['fragments']),fragment_records=[f['record'] for f in p['fragments']]) for p in packets]))
        if next(legs,None) is not None:raise CaptureError('unattributed business legs in timeline')
    if len(rows)!=proof['round_trips'] or not rows:raise CaptureError('one timeline for every successful actual application request')
    return rows


def analyze(directory):
    root=Path(directory).resolve(strict=True);share=root/'guest-output'
    manifest=json.loads((root/'manifest.json').read_text());run=json.loads((share/'application/passthrough-control/run.json').read_text())
    if manifest['status']!='PASSTHROUGH_SUPPORT_PASS' or manifest['qemu_exit']!=0:raise CaptureError('complete successful original VM required;failed attempts remain separate')
    capture=read_capture(share/'ws73.pcap',{(o['owner']['bus'],o['owner']['device']) for r in run['socket_benchmark'] for o in r['owners']})
    if capture['packet_count']!=check_capture_stats((share/'capture-stats.txt').read_text()):raise CaptureError('complete capture count')
    proof=corroborate(run,capture,share)
    if json.dumps(proof,sort_keys=True)!=json.dumps(manifest['socket_benchmark_corroboration'],sort_keys=True):raise CaptureError('actual original proof replay mismatch')
    rows=intervals(run,proof);trace=None
    if 'socket_benchmark_xhci_requested' in manifest:
        trace=check_xhci(share,manifest['socket_benchmark_xhci_requested'])
        if trace!=manifest['socket_benchmark_xhci_observation']:raise CaptureError('original trace observation mismatch')
    return dict(schema_version=1,status='INTERVALS_OBSERVED_NOT_PERFORMANCE_QUALIFIED',round_trips=len(rows),mode=proof['mode'],window=run['socket_benchmark'][0]['config']['window'],xhci=trace,
                source_manifest=material(root/'manifest.json'),capture=material(share/'ws73.pcap'),rows=rows,
                usb_wall_distributions={k:distribution([r['usb_wall_ns'][k] for r in rows]) for k in rows[0]['usb_wall_ns']},
                application_monotonic_distributions={k:distribution([r['application_monotonic_ns'][k] for r in rows]) for k in rows[0]['application_monotonic_ns']},
                nocp=[dict(record=v['record'],bus=v['bus'],device=v['device'],wall_ns=v['wall_ns'],params=v['params']) for v in capture['native_events'] if v['event']==9],
                scope=['Same-guest usbmon wall clock,1usquantization;OUT-completion separate andallowed afterpeerIN. RX assembly may contain multiple SDK111 fragments even forshort application payload;first andcompleteRX times separate.',
                       'Application-local monotonic intervals kept separate;no cross-domain subtraction,RTT/2 or precise one-way RF claim.',
                       'OUT-to-oppositeIN includes USB,firmware,radio andVM;peer turnaround includes receive/kernel/application/send combined.',
                       'NOCP handle/count timeline separate,not assigned as per-message acknowledgement or delivery.',
                       'Successful original paired lowload workload only;failed runs refused,not silently included or upgraded;allattempt ledger remains required.',
                       'No Session/credit/Ticket/Grant/URB changes;no stable threshold,resourcepeak orcompleteperformance qualification.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    print(json.dumps(analyze(args.run),indent=2))


if __name__=='__main__':main()
