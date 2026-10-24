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
from ws73_trace_layout import buffer_kib


def material(path):
    data=path.read_bytes()
    return dict(path=str(path),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))


def selected_clock(text):
    if not text or len(text)>4096 or any(not re.fullmatch(r'(?:\[[a-zA-Z0-9_-]+\]|[a-zA-Z0-9_-]+)',v)for v in text.split()):raise CaptureError('bounded trace clock readback required')
    selected=re.findall(r'\[([a-zA-Z0-9_-]+)\]',text)
    if selected!=['mono']:raise CaptureError('explicit globally comparable mono trace clock required')
    return 'mono'


def phase_marker_text(phase,boundary,cookie,*,pair=None):
    if (type(phase)is not int or phase not in(0,1)or boundary not in('BEGIN','END')
            or not isinstance(cookie,str)or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',cookie)
            or pair is not None and(type(pair)is not int or pair not in(0,1))):raise CaptureError('fixed benchmark phase/pair/cookie required')
    prefix='SLK_BENCH'if pair is None else f'SLK_BENCH_PAIR_{pair}'
    return f'{prefix}_PHASE_{boundary}:{cookie}:{phase}'


def phase_marker(phase,boundary,*,pair=None):
    """Fixed root observer, outside the application's measured hot loop."""
    from ws73_application_role import require_vm
    from ws73_role_snapshot import profile
    require_vm(profile('benchmark')['token'])
    from ws73_socket_benchmark import check_pair_boot
    check_pair_boot(pair,Path('/proc/cmdline').read_text().split())
    if type(phase)is not int or phase not in(0,1)or boundary not in('BEGIN','END'):raise CaptureError('fixed benchmark phase marker required')
    evidence=Path('/evidence');tracing=Path('/sys/kernel/tracing')
    selected_clock((evidence/'benchmark-xhci-clock-start.txt').read_text());selected_clock((tracing/'trace_clock').read_text())
    cfg=json.loads((evidence/'benchmark-xhci-start.json').read_text());cookie=cfg['cookie']
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',cookie)or cfg['enabled']not in('0','1')or cfg['tracing_on']!=cfg['enabled']:raise CaptureError('actual fixed trace phase configuration required')
    enabled=cfg['enabled']=='1'
    if (tracing/'tracing_on').read_text().strip()!=cfg['enabled']or(tracing/'events/xhci-hcd/enable').read_text().strip()!=cfg['enabled']:raise CaptureError('trace phase enable changed')
    text=phase_marker_text(phase,boundary,cookie,pair=pair)
    marker=text if enabled else None
    if marker:(tracing/'trace_marker').write_text(marker+'\n')
    return dict(version=1,mode='on'if enabled else'off',clock='mono',cookie=cookie,marker=marker,**({'parallel_pair':pair}if pair is not None else{}))


def trace_rows(text):
    rows=[]
    for line in text.splitlines():
        if not line.strip()or line.startswith('#'):continue
        match=re.search(r'(\d+)\.(\d{6,9}):\s*(.*)$',line)
        if not match:raise CaptureError('bounded nanosecond trace timestamp required')
        rows.append(dict(ns=int(match[1])*1_000_000_000+int(match[2].ljust(9,'0')),event=match[3],quantum_ns=10**(9-len(match[2]))))
    return rows


def phase_intervals(rows,cookie,*,pair=None):
    prefix=phase_marker_text(0,'BEGIN',cookie,pair=pair).split('_PHASE_')[0]+'_PHASE_'
    markers=[(n,v)for n,v in enumerate(rows)if v['event'].startswith('tracing_mark_write: '+prefix)]
    expected=['tracing_mark_write: '+phase_marker_text(phase,boundary,cookie,pair=pair)for phase in(0,1)for boundary in('BEGIN','END')]
    if [v['event']for _,v in markers]!=expected:raise CaptureError('two ordered original business phase marker pairs required')
    result=[]
    for phase in(0,1):
        (first,a),(last,b)=markers[phase*2:phase*2+2]
        if a['ns']>=b['ns']or not any(v['event'].startswith('xhci_')for v in rows[first+1:last]):raise CaptureError('positive observed work inside each business phase required')
        result.append(dict(phase=phase,begin_ns=a['ns'],end_ns=b['ns']))
    if result[0]['end_ns']>=result[1]['begin_ns']:raise CaptureError('nonoverlapping mono business phases required')
    return result


def check_xhci(share, mode,*,parallel=False):
    share=Path(share)
    if type(parallel)is not bool or parallel and mode!='on':raise CaptureError('explicit paired gate requires original enabled trace')
    if mode not in ('on','off'):raise CaptureError('explicit xHCI comparison mode')
    rows=[json.loads((share/f'benchmark-xhci-{name}.json').read_text()) for name in ['start','end']]
    cookie=rows[0].get('cookie')
    if not isinstance(cookie,str) or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',cookie):raise CaptureError('actual per-boot trace identity')
    # Match the exact kernel's real page payload and DIV_ROUND_UP resize,
    # then the KiB floor in tracing_entries_read; do not accept a tolerance.
    headers=[(share/f'benchmark-xhci-header-{n}.txt').read_text() for n in ['start','end']]
    if headers[0]!=headers[1] or len(headers[0])>4096:raise CaptureError('same original trace page layout before/after')
    subbuffer=rows[0].get('subbuffer_kb')
    requested_kb=8192 if parallel else 1024
    try:actual_kb,payload=buffer_kib(headers[0],requested_kb,subbuffer)
    except ValueError as error:raise CaptureError(str(error)) from error
    expected=dict(enabled='1' if mode=='on' else '0',tracing_on='1' if mode=='on' else '0',tracer='nop',buffer_kb=actual_kb,requested_buffer_kb=requested_kb,subbuffer_kb=subbuffer,cookie=cookie)
    if any(type(v.get(k)) is not int for v in rows for k in ['buffer_kb','requested_buffer_kb','subbuffer_kb']) or rows!=[expected,expected]:raise CaptureError('actual trace start/end configuration differs')
    path=share/'xhci-trace.log';text=path.read_text();stats=(share/'xhci-trace-stats.txt').read_text()
    if len(text)>(32 if parallel else 8)*1024*1024 or 'LOST' in text.upper() or re.findall(r'^# tracer: (.*)$',text,re.M)!=['nop']:raise CaptureError('bounded loss-free nop event trace required')
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
        modern=any((share/f'benchmark-xhci-clock-{name}.txt').exists()for name in('start','end'))
        def phase_event(value):
            if not modern:return False
            if parallel:return bool(re.fullmatch(r'tracing_mark_write: SLK_BENCH_PAIR_[01]_PHASE_(?:BEGIN|END):'+re.escape(cookie)+r':[01]',value))
            return value.startswith('tracing_mark_write: SLK_BENCH_PHASE_')
        if any(not v.startswith('xhci_') and v not in(begin,end)and not phase_event(v)for v in events):raise CaptureError('unexpected event outside requested xHCI observation')
    result=dict(status='XHCI_CONFIGURATION_AND_SEAL_CORROBORATED',mode=mode,entries=len(events),cookie=cookie,
                trace=material(path),requested_buffer_kb=requested_kb,actual_buffer_kb=actual_kb,subbuffer_payload_bytes=payload,scope='Start/end readback and complete finite VM trace;usbmon remains enabled;not all observer overhead or kernel concurrency proof')
    clocks=[share/f'benchmark-xhci-clock-{name}.txt'for name in('start','end')]
    if parallel and not all(p.is_file()for p in clocks):raise CaptureError('paired trace requires original mono clock readbacks')
    if any(p.exists()for p in clocks):
        if not all(p.is_file()and not p.is_symlink()for p in clocks):raise CaptureError('both actual trace clock readbacks required')
        for p in clocks:selected_clock(p.read_text())
        parsed=trace_rows(text);phases=([dict(pair=pair,phases=phase_intervals(parsed,cookie,pair=pair))for pair in(0,1)]if parallel else phase_intervals(parsed,cookie))if mode=='on'else[]
        if mode=='on':
            begin=next(v['ns']for v in parsed if v['event']=='tracing_mark_write: SLK_BENCH_BEGIN:'+cookie)
            end=next(v['ns']for v in parsed if v['event']=='tracing_mark_write: SLK_BENCH_END:'+cookie)
            groups=[p['phases']for p in phases]if parallel else[phases]
            if any(not begin<group[0]['begin_ns']<group[-1]['end_ns']<end for group in groups):raise CaptureError('business phases belong to original boot trace interval')
        result.update(trace_contract_version=2 if parallel else 1,clock='mono',phase_intervals=phases,clock_readbacks=[material(p)for p in clocks])
    return result


def rx_resubmits(share,run,trace):
    """Observe HCD endpoints, not a callback timer or hardware-ready timestamp.

    xHCI giveback precedes USB-core callback dispatch; enqueue is before the
    HCD lock/queue and can still fail. Neither event embeds Runtime generation.
    Connection identity is an annotation from the independently checked gate.
    """
    if trace.get('trace_contract_version')!=1 or trace.get('clock')!='mono':raise CaptureError('RX interval requires explicit trace clock/phase contract')
    if trace['mode']=='off':
        for row in run['socket_benchmark']:
            if row.get('trace_observation')!=dict(version=1,mode='off',clock='mono',cookie=trace['cookie'],marker=None,end_marker=None):raise CaptureError('actual root trace-off witness required')
        return dict(status='NOT_OBSERVED_TRACE_OFF',endpoints=[])
    raw=(Path(share)/'xhci-trace.log').read_bytes()
    if len(raw)!=trace['trace']['bytes']or hashlib.sha256(raw).hexdigest()!=trace['trace']['sha256']:raise CaptureError('RX trace changed after verification')
    rows=trace_rows(raw.decode());results=[]
    pattern=re.compile(r'xhci_urb_(enqueue|giveback|dequeue): (\d+-\d+(?:\.\d+)*) ep(\d+)in-bulk: urb ([0-9a-f]{16}) pipe (\d+) slot (\d+) length (\d+)/(\d+) sgs \d+/\d+ stream \d+ flags [0-9a-f]{8}')
    for phase,bounds in zip(run['socket_benchmark'],trace['phase_intervals'],strict=True):
        witness=phase.get('trace_observation',{});n=phase['phase']
        if (bounds['phase']!=n or witness!=dict(version=1,mode='on',clock='mono',cookie=trace['cookie'],marker=f'SLK_BENCH_PHASE_BEGIN:{trace["cookie"]}:{n}',end_marker=f'SLK_BENCH_PHASE_END:{trace["cookie"]}:{n}')):raise CaptureError('actual root business trace witness required')
        for entry in phase['owners']:
            owner,obj=entry['owner'],entry['object'];port=owner['port'];events=[]
            for row in rows:
                if not bounds['begin_ns']<row['ns']<bounds['end_ns']:continue
                if row['event'].startswith(('xhci_urb_enqueue: '+port+' ','xhci_urb_giveback: '+port+' ','xhci_urb_dequeue: '+port+' '))and'in-bulk:'in row['event']:
                    match=pattern.fullmatch(row['event'])
                    if not match:raise CaptureError('exact recorded xHCI bulk IN format required')
                    operation,_,ep,urb,pipe,slot,actual,length=match.groups();actual,length=int(actual),int(length)
                    if length!=20480 or not 0<=actual<=length or(operation=='enqueue'and actual!=0):raise CaptureError('current native single RX buffer observation required')
                    events.append(row|dict(operation=operation,ep=ep,urb=urb,pipe=pipe,slot=slot,actual=actual))
            if not events or len({tuple(v[k]for k in('ep','urb','pipe','slot'))for v in events})!=1:raise CaptureError('one observed Runtime RX URB per endpoint and phase required')
            times=[v['ns']for v in events]
            if times!=sorted(times):raise CaptureError('RX event order disagrees with mono clock')
            inflight=False;last=None;left=0;left_enqueue=0;givebacks=0;submissions=0;empty=0;samples=[]
            for i,event in enumerate(events):
                if event['operation']=='dequeue':raise CaptureError('RX cancellation inside measured phase; interval not qualified')
                if event['operation']=='giveback':
                    if not inflight:
                        if i!=0:raise CaptureError('RX completion without observed submission')
                        left+=1
                    if last is not None:raise CaptureError('duplicate RX completion before resubmit')
                    givebacks+=1;empty+=event['actual']==0;last=event;inflight=False
                else:
                    if inflight:raise CaptureError('overlapping RX submissions; single-URB observation invalid')
                    submissions+=1
                    if i==0:left_enqueue+=1
                    if last is not None:
                        samples.append(dict(giveback_ns=last['ns'],resubmit_entry_ns=event['ns'],interval_ns=event['ns']-last['ns'],actual_bytes=last['actual'],timestamp_quantum_ns=max(event['quantum_ns'],last['quantum_ns'])))
                        last=None
                    inflight=True
            if not samples:raise CaptureError('RX giveback/resubmit samples missing')
            if submissions!=len(samples)+left_enqueue or givebacks!=len(samples)+int(last is not None):raise CaptureError('every observed RX event must be accounted or censored')
            results.append(dict(phase=n,identity=dict(port=port,controller=owner['index'],generation=owner['generation'],lifetime=obj['lifetime'],handle=obj['handle']),urb=events[0]['urb'],endpoint=int(events[0]['ep']),enqueue_entries=submissions,givebacks=givebacks,empty_givebacks=empty,left_censored_enqueue_entries=left_enqueue,left_censored_completions=left,right_censored_submission=int(inflight),right_censored_completion=int(last is not None),samples=samples,distribution=distribution([v['interval_ns']for v in samples])))
    if len(results)!=4:raise CaptureError('both endpoints in both business phases required')
    return dict(status='HCD_RX_GIVEBACK_TO_RESUBMIT_ENTRY_OBSERVED',clock='mono',endpoints=results,scope='Only same-boot established-business phases, single observed RX URB/endpoint; boundary censoring explicit. Includes USB-core dispatch/callback and submit preparation before HCD queue. Not callback-only cost, full no-URB hardware window, generation/ref/drain proof, RF delay or bottleneck/optimization evidence.')


def valid_trace_summary(proof,mode,*,parallel=False):
    try:
        if(type(parallel)is not bool or parallel and mode!='on'or mode not in('on','off')or proof['mode']!=mode or proof['status']!='XHCI_CONFIGURATION_AND_SEAL_CORROBORATED'or type(proof['trace_contract_version'])is not int or proof['trace_contract_version']!=(2 if parallel else 1)or proof['clock']!='mono'):return False
        phases=proof['phase_intervals']
        if parallel:
            if proof.get('requested_buffer_kb')!=8192 or type(proof.get('trace',{}).get('bytes'))is not int or not 0<proof['trace']['bytes']<=32*1024*1024:return False
            if type(phases)is not list or len(phases)!=2 or any(type(p)is not dict or set(p)!={'pair','phases'}or type(p['pair'])is not int or p['pair']!=i for i,p in enumerate(phases)):return False
            groups=[p['phases']for p in phases]
            if not all(valid_phase_bounds(group)for group in groups):return False
            return max(g[0]['end_ns']for g in groups)<min(g[1]['begin_ns']for g in groups)
        return phases==[]if mode=='off'else(len(phases)==2 and all(type(p[k])is int for p in phases for k in('phase','begin_ns','end_ns'))and[ph['phase']for ph in phases]==[0,1]and 0<phases[0]['begin_ns']<phases[0]['end_ns']<phases[1]['begin_ns']<phases[1]['end_ns'])
    except(KeyError,TypeError,IndexError):return False


def valid_phase_bounds(phases):
    return (type(phases)is list and len(phases)==2 and all(type(p[k])is int for p in phases for k in('phase','begin_ns','end_ns'))
            and[p['phase']for p in phases]==[0,1]and 0<phases[0]['begin_ns']<phases[0]['end_ns']<phases[1]['begin_ns']<phases[1]['end_ns'])


def verify_paired_trace(control,trace):
    """Bind each original Root witness to its own sealed mono trace markers."""
    if not valid_trace_summary(trace,'on',parallel=True):raise CaptureError('complete paired enabled mono trace required')
    for number,worker in enumerate(control['workers']):
        rows=worker['run']['socket_benchmark']
        if len(rows)!=2:raise CaptureError('two original Root trace witnesses per pair required')
        for phase,row in enumerate(rows):
            expected=dict(version=1,mode='on',clock='mono',cookie=trace['cookie'],parallel_pair=number,
                marker=phase_marker_text(phase,'BEGIN',trace['cookie'],pair=number),end_marker=phase_marker_text(phase,'END',trace['cookie'],pair=number))
            if row.get('trace_observation')!=expected:raise CaptureError('Root trace witness differs from original paired trace')


def packet_times(packet):
    """Inspect the existing reassembly proof, not another fragment decoder."""
    parts=packet.get('fragments')
    if not isinstance(parts,list)or not parts:raise CaptureError('complete independently reassembled fragment proof required')
    expected=[0]if len(parts)==1 else[1]+[2]*(len(parts)-2)+[3]
    if (any(type(p.get('boundary',0))is not int for p in parts)
        or [p.get('boundary',0)for p in parts]!=expected
        or any(any(p[k]!=packet[k]for k in('bus','device','handle','direction'))for p in parts)
        or any(type(p['wall_ns'])is not int for p in parts)
        or [p['wall_ns']for p in parts]!=sorted(p['wall_ns']for p in parts)
        or packet['wall_ns']!=parts[-1]['wall_ns']):raise CaptureError('ordered original fragment timestamps and identity required')
    first,last=parts[0]['wall_ns'],parts[-1]['wall_ns']
    complete=None
    if packet['direction']=='out':
        completions=[p['completion']['wall_ns']for p in parts]
        if any(type(v)is not int or v<p['wall_ns']for p,v in zip(parts,completions)):raise CaptureError('every original OUT fragment completion required')
        complete=max(completions)
        if len(parts)==1 and packet['completion']['wall_ns']!=complete:raise CaptureError('original OUT completion differs from fragment')
    return first,last,complete


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
                points=[packet_times(p)for p in packets]
                a,last_a,ca=points[0];first_b,b,_=points[1];c,last_c,cc=points[2];first_d,d,_=points[3]
                if not a<=first_b<=b<=c<=first_d<=d or last_a>b or last_c>d:raise CaptureError('USB causal interval/OUT completion order invalid')
                timings=dict(request_out_complete=ca-a,request_out_to_peer_in=b-a,peer_in_to_reply_out=c-b,reply_out_complete=cc-c,reply_out_to_source_in=d-c,usb_round_trip=d-a,request_out_to_peer_first_in=first_b-a,peer_rx_assembly_span=b-first_b,reply_out_to_source_first_in=first_d-c,source_rx_assembly_span=d-first_d)
                if timings['usb_round_trip']!=sum(timings[k] for k in ['request_out_to_peer_in','peer_in_to_reply_out','reply_out_to_source_in']):raise CaptureError('USB timeline interval sum')
                rows.append(dict(phase=phase['phase'],source=index,sequence=original['index'],frame_sha256=hashlib.sha256(bytes.fromhex(original['frame_hex'])).hexdigest(),
                    application_monotonic_ns=dict(rtt=original['validated_ns']-original['syscall_ns'],syscall_admission=original['admitted_ns']-original['syscall_ns'],planned_dispatch=original['dispatch_ns']-original['planned_ns']),usb_wall_ns=timings,
                    records=[dict(record=p['record'],bus=p['bus'],device=p['device'],handle=p['handle'],direction=p['direction'],wall_ns=p['wall_ns'],fragments=len(p['fragments']),fragment_records=[f['record'] for f in p['fragments']]) for p in packets]))
                if len(request['tx']['fragments'])>1 or len(reply['tx']['fragments'])>1:
                    rows[-1]['fragmented_tx_wall_ns']=dict(request_submission_span=last_a-a,reply_submission_span=last_c-c,
                        request_last_out_to_peer_complete_in=b-last_a,reply_last_out_to_source_complete_in=d-last_c)
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
    result=dict(schema_version=1,status='INTERVALS_OBSERVED_NOT_PERFORMANCE_QUALIFIED',round_trips=len(rows),mode=proof['mode'],window=run['socket_benchmark'][0]['config']['window'],xhci=trace,
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
    if 'benchmark_process_resource_contract_version'in proof:
        from ws73_benchmark_resources import valid_summary
        if not valid_summary(proof):raise CaptureError('complete process-resource proof required')
        result['process_resource_observations']=[dict(phase=p['phase'],applications=p['resource_observations'])for p in proof['proofs']]
        result['scope'].append('Process CPU tick deltas bracket the armed/quiescent checkpoints;memory high-water marks include process preparation through the observed checkpoint. fd counts are checkpoint counts,not peaks;not whole VM/controller/URB/queue or resource leak qualification.')
    if trace and trace.get('trace_contract_version')==1:
        if not valid_trace_summary(trace,manifest['socket_benchmark_xhci_requested']):raise CaptureError('fresh trace summary contract required')
        result['rx_resubmit_observation']=rx_resubmits(share,run,trace)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    print(json.dumps(analyze(args.run),indent=2))


if __name__=='__main__':main()
