# SPDX-License-Identifier: GPL-2.0-only
"""Pure synthetic trace/interval negatives; never hardware qualification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from ws73_benchmark_timeline import check_xhci,intervals,rx_resubmits,selected_clock,valid_trace_summary
from ws73_capture import CaptureError
from ws73_socket_benchmark import corroborate
from test_ws73_socket_benchmark import fixture
COOKIE='01234567-89ab-cdef-0123-456789abcdef'


def modern_trace(root,mode='on'):
    """Synthetic observation records, no actual callback/USB/Native fixture."""
    trace_fixture(root,mode);run=dict(socket_benchmark=[]);lines=[]
    def append(t,event):lines.append(f'  fixture-1 [000] ..... 0.{t:06d}: '+event)
    if mode=='on':append(1,'tracing_mark_write: SLK_BENCH_BEGIN:'+COOKIE)
    for phase,base in enumerate((10,40)):
        row=dict(phase=phase,owners=[],trace_observation=dict(version=1,mode=mode,clock='mono',cookie=COOKIE,marker=f'SLK_BENCH_PHASE_BEGIN:{COOKIE}:{phase}'if mode=='on'else None,end_marker=f'SLK_BENCH_PHASE_END:{COOKIE}:{phase}'if mode=='on'else None));run['socket_benchmark'].append(row)
        if mode=='on':append(base,f'tracing_mark_write: SLK_BENCH_PHASE_BEGIN:{COOKIE}:{phase}')
        events=[]
        for index in(0,1):
            row['owners'].append(dict(owner=dict(port=f'1-{index+1}',index=index,generation=index+5),object=dict(lifetime=phase+10,handle=0)))
            for offset,operation,actual in[(2,'giveback',156),(4,'enqueue',0),(6,'giveback',0),(8,'enqueue',0)]:
                events.append((base+offset+index,f'xhci_urb_{operation}: 1-{index+1} ep1in-bulk: urb {index+1:016x} pipe 3225453184 slot {index+1} length {actual}/20480 sgs 0/0 stream 0 flags 00010200'))
        if mode=='on':
            for t,event in sorted(events):append(t,event)
            append(base+20,f'tracing_mark_write: SLK_BENCH_PHASE_END:{COOKIE}:{phase}')
    if mode=='on':append(70,'tracing_mark_write: SLK_BENCH_END:'+COOKIE)
    (root/'xhci-trace.log').write_text('# tracer: nop\n# entries-in-buffer/entries-written: '+str(len(lines))+'/'+str(len(lines))+'\n'+'\n'.join(lines)+'\n')
    (root/'xhci-trace-stats.txt').write_text(''.join(f'entries: {n}\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n'for n in(len(lines),0)))
    for end in('start','end'):(root/f'benchmark-xhci-clock-{end}.txt').write_text('local global counter uptime perf [mono] mono_raw boot tai x86-tsc\n')
    return run


def reseal_trace_fixture(root,text):
    rows=[v for v in text.splitlines()if v.strip()and not v.startswith('#')]
    (root/'xhci-trace.log').write_text('# tracer: nop\n# entries-in-buffer/entries-written: '+str(len(rows))+'/'+str(len(rows))+'\n'+'\n'.join(rows)+'\n')
    (root/'xhci-trace-stats.txt').write_text(''.join(f'entries: {n}\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n'for n in(len(rows),0)))
    return check_xhci(root,'on')


def trace_fixture(root,mode='on'):
    value=dict(enabled='1' if mode=='on' else '0',tracing_on='1' if mode=='on' else '0',tracer='nop',buffer_kb=1027,requested_buffer_kb=1024,subbuffer_kb=4,cookie=COOKIE)
    for name in ['start','end']:
        (root/f'benchmark-xhci-{name}.json').write_text(json.dumps(value))
        (root/f'benchmark-xhci-header-{name}.txt').write_text('field: char data; offset:16; size:4080; signed:1;\n')
    lines=[] if mode=='off' else [f'0.000001: tracing_mark_write: SLK_BENCH_BEGIN:{COOKIE}','0.000002: xhci_urb_giveback: synthetic',f'0.000003: tracing_mark_write: SLK_BENCH_END:{COOKIE}']
    (root/'xhci-trace.log').write_text('# tracer: nop\n# entries-in-buffer/entries-written: '+str(len(lines))+'/'+str(len(lines))+'\n'+'\n'.join(lines)+'\n')
    (root/'xhci-trace-stats.txt').write_text(''.join('entries: '+str(n)+'\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n' for n in [len(lines),0]))


class TimelineEvidence(unittest.TestCase):
    def test_linux_arch_clock_enumeration_does_not_change_required_selection(self):
        clocks='local global counter uptime perf [mono] mono_raw boot tai x86-tsc\n'
        self.assertEqual(selected_clock(clocks),'mono')
        with self.assertRaises(CaptureError):selected_clock(clocks.replace('[mono]','mono').replace('x86-tsc','[x86-tsc]'))

    def test_explicit_clock_phase_and_single_rx_intervals_keep_boundary_censoring(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);run=modern_trace(root);trace=check_xhci(root,'on');self.assertTrue(valid_trace_summary(trace,'on'))
            proof=rx_resubmits(root,run,trace);self.assertEqual(len(proof['endpoints']),4)
            for ep in proof['endpoints']:
                self.assertEqual(ep['left_censored_completions'],1);self.assertEqual(ep['right_censored_submission'],1);self.assertEqual(ep['right_censored_completion'],0)
                self.assertEqual(ep['givebacks'],2);self.assertEqual(ep['empty_givebacks'],1)
                self.assertEqual([s['interval_ns']for s in ep['samples']],[2000,2000]);self.assertEqual(ep['distribution']['p999_ns'],None)
            run=modern_trace(root,'off');trace=check_xhci(root,'off');self.assertTrue(valid_trace_summary(trace,'off'))
            self.assertEqual(rx_resubmits(root,run,trace),dict(status='NOT_OBSERVED_TRACE_OFF',endpoints=[]))

    def test_trace_clock_missing_wrong_and_unbounded_are_not_measurements(self):
        for value in('','[local] mono','[mono] [mono_raw]','[mono] local]','[mono]'+'a'*4096):
            with self.subTest(value=value[:30]),self.assertRaises(CaptureError):selected_clock(value)
        for name in('missing-start','missing-end','wrong-end','duplicate-phase','old-cookie','reversed-time','missing-work','missing-marker'):
            with tempfile.TemporaryDirectory()as d:
                root=Path(d);modern_trace(root);p=root/'xhci-trace.log';text=p.read_text()
                if name.startswith('missing-')and name.split('-',1)[1]in('start','end'):(root/f'benchmark-xhci-clock-{name.split("-",1)[1]}.txt').unlink()
                elif name=='wrong-end':(root/'benchmark-xhci-clock-end.txt').write_text('[local] mono')
                elif name=='duplicate-phase':text=text.replace('SLK_BENCH_PHASE_BEGIN:'+COOKIE+':1','SLK_BENCH_PHASE_BEGIN:'+COOKIE+':0')
                elif name=='old-cookie':text=text.replace('SLK_BENCH_PHASE_END:'+COOKIE+':1','SLK_BENCH_PHASE_END:'+'f'*36+':1')
                elif name=='reversed-time':text=text.replace('0.000030:','0.000009:')
                elif name=='missing-work':text=text.replace('xhci_urb_','tracing_mark_write: bad_')
                elif name=='missing-marker':text=text.replace('SLK_BENCH_PHASE_BEGIN:','UNRECOGNIZED:')
                p.write_text(text)
                with self.subTest(name=name),self.assertRaises((CaptureError,FileNotFoundError)):check_xhci(root,'on')

    def test_initial_enqueue_is_explicitly_censored_and_all_events_accounted(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);run=modern_trace(root);trace=check_xhci(root,'on');p=root/'xhci-trace.log'
            # Prefix was before the observation interval; do not invent its
            # completion timestamp or turn an enqueue into a measured gap.
            text=p.read_text();line=next(v for v in text.splitlines()if '0.000012: xhci_urb_giveback: 1-1'in v)
            first=line.replace('0.000012:','0.000011:').replace('xhci_urb_giveback:','xhci_urb_enqueue:').replace('length 156/20480','length 0/20480')
            trace=reseal_trace_fixture(root,text.replace(line,first+'\n'+line))
            ep=rx_resubmits(root,run,trace)['endpoints'][0]
            self.assertEqual(ep['left_censored_enqueue_entries'],1);self.assertEqual(ep['left_censored_completions'],0)
            self.assertEqual(ep['enqueue_entries'],len(ep['samples'])+1)
            self.assertEqual(ep['givebacks'],len(ep['samples'])+ep['right_censored_completion'])

    def test_single_rx_parser_rejects_overlap_cancel_pointer_and_clock_races(self):
        for name in('overlap','cancel','pointer','length','out-of-order','duplicate-completion','missing-endpoint','wrong-root-marker'):
            with tempfile.TemporaryDirectory()as d:
                root=Path(d);run=modern_trace(root);trace=check_xhci(root,'on');p=root/'xhci-trace.log';text=p.read_text()
                if name=='overlap':text=text.replace('0.000016: xhci_urb_giveback:','0.000016: xhci_urb_enqueue:')
                elif name=='cancel':text=text.replace('0.000016: xhci_urb_giveback:','0.000016: xhci_urb_dequeue:')
                elif name=='pointer':text=text.replace('0.000016: xhci_urb_giveback: 1-1 ep1in-bulk: urb 0000000000000001','0.000016: xhci_urb_giveback: 1-1 ep1in-bulk: urb 0000000000000009')
                elif name=='length':text=text.replace('/20480','/20479')
                elif name=='out-of-order':text=text.replace('0.000016:','0.000013:')
                elif name=='duplicate-completion':text=text.replace('0.000014: xhci_urb_enqueue:','0.000014: xhci_urb_giveback:')
                elif name=='missing-endpoint':text='\n'.join(line for line in text.splitlines()if '1-2 ep1in-bulk'not in line)+'\n'
                else:run['socket_benchmark'][0]['trace_observation']['cookie']='f'*36
                trace=reseal_trace_fixture(root,text)
                with self.subTest(name=name),self.assertRaises(CaptureError):rx_resubmits(root,run,trace)

    def test_rx_trace_bytes_cannot_change_after_original_verification(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);run=modern_trace(root);trace=check_xhci(root,'on');p=root/'xhci-trace.log';p.write_text(p.read_text().replace('length 156/20480','length 157/20480',1))
            with self.assertRaisesRegex(CaptureError,'changed after verification'):rx_resubmits(root,run,trace)

    def test_new_trace_terminal_guard_rejects_missing_or_old_clock(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);modern_trace(root);trace=check_xhci(root,'on')
            for update in [dict(clock='local'),dict(trace_contract_version=True),dict(phase_intervals=[]),dict(mode='off')]:
                self.assertFalse(valid_trace_summary(trace|update,'on'))

    def test_modern_trace_cannot_be_relabelled_as_legacy_terminal_evidence(self):
        from ws73_target import run_exit_code
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);run,capture=fixture(root);proof=corroborate(run,capture,root)
            record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',socket_benchmark_requested='window',socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,qemu_exit=0)
            self.assertEqual(run_exit_code(record),0) # Historical metadata fixture only.
            modern_trace(root);record['socket_benchmark_xhci_observation']=check_xhci(root,'on');record['socket_benchmark_xhci_requested']='on'
            self.assertEqual(run_exit_code(record),1) # Missing contract must not fall back.
            record['benchmark_trace_contract_version']=1
            self.assertEqual(run_exit_code(record),1) # New contract cannot use legacy role.
    def test_on_off_actual_readback_and_trace_integrity(self):
        for mode in ['on','off']:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);trace_fixture(root,mode);r=check_xhci(root,mode)
                self.assertEqual(r['entries'],3 if mode=='on' else 0)
                self.assertEqual(r['mode'],mode)

    def test_actual_page_payload_roundup_not_requested_kib_or_tolerance(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);trace_fixture(root);r=check_xhci(root,'on')
            self.assertEqual((r['requested_buffer_kb'],r['actual_buffer_kb'],r['subbuffer_payload_bytes']),(1024,1027,4080))
            for wrong in [1024,1026,1028,True,1027.0]:
                for name in ['start','end']:
                    p=root/f'benchmark-xhci-{name}.json';v=json.loads(p.read_text());v['buffer_kb']=wrong;p.write_text(json.dumps(v))
                with self.subTest(buffer=wrong),self.assertRaises(CaptureError):check_xhci(root,'on')
            for field in ['requested_buffer_kb','subbuffer_kb']:
                for name in ['start','end']:
                    trace_fixture(root);p=root/f'benchmark-xhci-{name}.json';v=json.loads(p.read_text());v[field]=float(v[field]);p.write_text(json.dumps(v))
                    with self.subTest(field=field,endpoint=name),self.assertRaises(CaptureError):check_xhci(root,'on')
            trace_fixture(root)
            (root/'benchmark-xhci-header-end.txt').write_text('field: char data; offset:16; size:4096; signed:1;\n')
            with self.assertRaises(CaptureError):check_xhci(root,'on')

    def test_trace_configuration_identity_drop_and_marker_negatives(self):
        for kind in ['oldcookie','enabled','tracing','buffer','bufferfloat','tracer','header','loss','missingcpu','count','truncate','marker','no-work','unexpected','off-has-events']:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);trace_fixture(root);start=root/'benchmark-xhci-start.json';cfg=json.loads(start.read_text());trace=root/'xhci-trace.log';stats=root/'xhci-trace-stats.txt'
                if kind=='oldcookie':cfg['cookie']='ffffffff-ffff-ffff-ffff-ffffffffffff'
                if kind=='enabled':cfg['enabled']='0'
                if kind=='tracing':cfg['tracing_on']='0'
                if kind=='buffer':cfg['buffer_kb']=2048
                if kind=='bufferfloat':cfg['buffer_kb']=1027.0
                if kind=='tracer':cfg['tracer']='function'
                start.write_text(json.dumps(cfg))
                if kind=='header':trace.write_text(trace.read_text().replace('3/3','2/3'))
                if kind=='loss':stats.write_text(stats.read_text().replace('overrun: 0','overrun: 1',1))
                if kind=='missingcpu':stats.write_text(stats.read_text().split('entries: 0')[0])
                if kind=='count':stats.write_text(stats.read_text().replace('entries: 3','entries: 2'))
                if kind=='truncate':trace.write_text(trace.read_text().replace('0.000002: xhci_urb_giveback: synthetic\n',''))
                if kind=='marker':trace.write_text(trace.read_text().replace('SLK_BENCH_END','SLK_BENCH_BEGIN'))
                if kind=='no-work':trace.write_text(trace.read_text().replace('xhci_urb_giveback','tracing_mark_write'))
                if kind=='unexpected':trace.write_text(trace.read_text().replace('xhci_urb_giveback','sched_switch'))
                with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):check_xhci(root,'off' if kind=='off-has-events' else 'on')

    def paired(self,root):
        run,capture=fixture(root,window=1);proof=corroborate(run,capture,root)
        for phase in proof['proofs']:
            for n,leg in enumerate(phase['legs']):
                base=phase['phase']*2000+500+(n//2)*10+(n%2)*4
                leg['tx']['wall_ns']=base;leg['tx']['completion']=dict(wall_ns=base+3)
                leg['tx']['fragments'][0]['wall_ns']=base;leg['tx']['fragments'][0]['completion']=dict(wall_ns=base+3)
                leg['rx']['wall_ns']=base+2;leg['rx']['fragments'][0]['wall_ns']=base+2
        return run,proof

    def test_separate_clock_domains_and_out_completion_race(self):
        with tempfile.TemporaryDirectory() as d:
            run,proof=self.paired(Path(d));rows=intervals(run,proof)
            self.assertEqual(len(rows),40)
            for row in rows:
                self.assertEqual(row['usb_wall_ns']['usb_round_trip'],6)
                self.assertEqual(row['usb_wall_ns']['request_out_complete'],3)
                self.assertEqual(row['application_monotonic_ns']['rtt'],30)
                self.assertEqual(row['usb_wall_ns']['peer_in_to_reply_out'],2)

    def test_sdk111_three_fragment_rx_short_message_preserves_first_last(self):
        with tempfile.TemporaryDirectory() as d:
            run,proof=self.paired(Path(d))
            for phase in proof['proofs']:
                for leg in phase['legs']:
                    rx=leg['rx'];raw=bytes.fromhex(rx['data']);self.assertEqual(len(raw),66)
                    parts=[];offset=0
                    for n,size in enumerate([28,28,10]):
                        part={k:v for k,v in rx.items() if k!='fragments'}
                        part.update(boundary=n+1,data=raw[offset:offset+size].hex(),record=10000+4*rx['record']+n,wall_ns=rx['wall_ns']-2+n)
                        offset+=size;parts.append(part)
                    rx['boundary']=3;rx['fragments']=parts
            for row in intervals(run,proof):
                self.assertEqual(row['usb_wall_ns']['peer_rx_assembly_span'],2)
                self.assertEqual(row['usb_wall_ns']['source_rx_assembly_span'],2)
                self.assertEqual([v['fragments'] for v in row['records']],[1,3,1,3])

    def test_fragment_wrong_order_or_missing_legs_rejected(self):
        for kind in ['fragments','backwards','out-completion','missing','extra']:
            with tempfile.TemporaryDirectory() as d:
                run,proof=self.paired(Path(d));leg=proof['proofs'][0]['legs'][0]
                if kind=='fragments':leg['tx']['fragments'].append(copy.deepcopy(leg['tx']['fragments'][0]))
                if kind=='backwards':leg['rx']['wall_ns']=leg['tx']['wall_ns']-1
                if kind=='out-completion':leg['tx']['completion']['wall_ns']=leg['tx']['wall_ns']-1
                if kind=='missing':proof['proofs'][0]['legs'].pop()
                if kind=='extra':proof['proofs'][0]['legs'].append(copy.deepcopy(leg))
                with self.subTest(kind=kind),self.assertRaises((CaptureError,StopIteration)):intervals(run,proof)

    def test_fragmented_tx_uses_first_submit_all_completions_and_last_peer_rx(self):
        with tempfile.TemporaryDirectory() as d:
            run,proof=self.paired(Path(d))
            for phase in proof['proofs']:
                for leg in phase['legs']:
                    tx=leg['tx'];base=tx['wall_ns'];parts=[]
                    for n in range(3):
                        part={k:v for k,v in tx.items()if k!='fragments'}
                        part.update(boundary=n+1,wall_ns=base+n-2,completion=dict(wall_ns=base+n+1))
                        parts.append(part)
                    tx.update(boundary=3,fragments=parts)
            rows=intervals(run,proof)
            for row in rows:
                self.assertEqual(row['usb_wall_ns']['usb_round_trip'],8)
                self.assertEqual(row['usb_wall_ns']['request_out_complete'],5)
                self.assertEqual(row['fragmented_tx_wall_ns']['request_submission_span'],2)
                self.assertEqual([p['fragments']for p in row['records']],[3,1,3,1])
            for kind in ('pb','completion','identity','order'):
                bad=copy.deepcopy(proof);tx=bad['proofs'][0]['legs'][0]['tx']
                if kind=='pb':tx['fragments'][1]['boundary']=0
                elif kind=='completion':tx['fragments'][0]['completion']['wall_ns']=tx['fragments'][0]['wall_ns']-1
                elif kind=='identity':tx['fragments'][1]['handle']+=1
                else:tx['fragments'].reverse()
                with self.subTest(kind=kind),self.assertRaises(CaptureError):intervals(run,bad)
