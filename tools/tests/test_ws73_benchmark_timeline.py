# SPDX-License-Identifier: GPL-2.0-only
"""Pure synthetic trace/interval negatives; never hardware qualification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from ws73_benchmark_timeline import check_xhci,intervals
from ws73_capture import CaptureError
from ws73_socket_benchmark import corroborate
from test_ws73_socket_benchmark import fixture
COOKIE='01234567-89ab-cdef-0123-456789abcdef'


def trace_fixture(root,mode='on'):
    value=dict(enabled='1' if mode=='on' else '0',tracing_on='1' if mode=='on' else '0',tracer='nop',buffer_kb=1027,requested_buffer_kb=1024,subbuffer_kb=4,cookie=COOKIE)
    for name in ['start','end']:
        (root/f'benchmark-xhci-{name}.json').write_text(json.dumps(value))
        (root/f'benchmark-xhci-header-{name}.txt').write_text('field: char data; offset:16; size:4080; signed:1;\n')
    lines=[] if mode=='off' else [f'0.000001: tracing_mark_write: SLK_BENCH_BEGIN:{COOKIE}','0.000002: xhci_urb_giveback: synthetic',f'0.000003: tracing_mark_write: SLK_BENCH_END:{COOKIE}']
    (root/'xhci-trace.log').write_text('# tracer: nop\n# entries-in-buffer/entries-written: '+str(len(lines))+'/'+str(len(lines))+'\n'+'\n'.join(lines)+'\n')
    (root/'xhci-trace-stats.txt').write_text(''.join('entries: '+str(n)+'\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n' for n in [len(lines),0]))


class TimelineEvidence(unittest.TestCase):
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
