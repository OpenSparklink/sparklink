# SPDX-License-Identifier: GPL-2.0-only
"""Regression for the real missing trace-init failure,using actual shell and
production trace parser on finite synthetic files. No Root/USB/hardware claim.
"""
import json,re,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_ws73_benchmark_timeline as fixtures
from ws73_benchmark_timeline import check_xhci,phase_marker_text,valid_trace_summary
from ws73_capture import CaptureError


def paired_trace(root,*,requested_kb=8192):
    fixtures.modern_trace(root);lines=[]
    from ws73_trace_layout import buffer_kib
    for edge in('start','end'):
        path=root/f'benchmark-xhci-{edge}.json';cfg=json.loads(path.read_text());cfg['requested_buffer_kb']=requested_kb;cfg['buffer_kb']=buffer_kib((root/f'benchmark-xhci-header-{edge}.txt').read_text(),requested_kb,cfg['subbuffer_kb'])[0];path.write_text(json.dumps(cfg))
    def add(t,s):lines.append(f' fixture-1 [000] ..... 0.{t:06d}: '+s)
    c=fixtures.COOKIE;add(1,'tracing_mark_write: SLK_BENCH_BEGIN:'+c)
    for phase,base in enumerate((10,40)):
        for pair in(0,1):add(base+pair,f'tracing_mark_write: SLK_BENCH_PAIR_{pair}_PHASE_BEGIN:{c}:{phase}')
        add(base+5,'xhci_urb_giveback: synthetic bounded fixture')
        for pair in(0,1):add(base+20+pair,f'tracing_mark_write: SLK_BENCH_PAIR_{pair}_PHASE_END:{c}:{phase}')
    add(70,'tracing_mark_write: SLK_BENCH_END:'+c)
    write_rows(root,lines)


def write_rows(root,lines):
    (root/'xhci-trace.log').write_text(f'# tracer: nop\n# entries-in-buffer/entries-written: {len(lines)}/{len(lines)}\n'+'\n'.join(lines)+'\n')
    (root/'xhci-trace-stats.txt').write_text(''.join(f'entries: {n}\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n'for n in(len(lines),0)))


class PairedTrace(unittest.TestCase):
    def test_actual_init_shell_selects_parallel_and_all_trace_sites_use_it(self):
        text=(Path(__file__).resolve().parents[1]/'ws73_target_init.sh').read_text();function=re.search(r'^benchmark_trace_requested\(\) \{.*?^\}',text,re.M|re.S).group()
        def run(body,words):return subprocess.run(['sh','-c',body+'\nbenchmark_trace_requested "$@"','fixture',*words],capture_output=True,text=True).returncode
        for word in ['ws73.parallel_benchmark=1','ws73.benchmark_mode=rate','ws73.benchmark_mode=window','ws73.benchmark_mode=duplex']:
            self.assertEqual(run(function,[word]),0)
        self.assertEqual(run(function.replace('|ws73.parallel_benchmark=1',''),['ws73.parallel_benchmark=1']),1)
        for words in [[],['ws73.parallel_benchmark=0'],['ws73.parallel_benchmark'],['ws73.parallel_subscription=1'],['ws73.benchmark_mode=invalid']]:self.assertEqual(run(function,words),1)
        self.assertEqual(text.count('[ "$benchmark_trace" = 1 ]'),4)
        self.assertNotIn("grep -q 'ws73.benchmark_mode=' /proc/cmdline",text)
        buffer_function=re.search(r'^benchmark_trace_buffer_kb\(\) \{.*?^\}',text,re.M|re.S).group()
        for words,expected in [([], '1024'),(['ws73.benchmark_mode=window'],'1024'),(['ws73.parallel_benchmark=1'],'8192'),(['ws73.parallel_benchmark_case=close-short'],'1024'),(['ws73.parallel_benchmark=1','ws73.parallel_benchmark_case=close-short'],'16384'),(['ws73.parallel_benchmark_case=close-short','ws73.parallel_benchmark=1'],'16384')]:
            p=subprocess.run(['sh','-c',buffer_function+'\nbenchmark_trace_buffer_kb "$@"','fixture',*words],capture_output=True,text=True);self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,expected)
        subprocess.run(['sh','-n',str(Path(__file__).resolve().parents[1]/'ws73_target_init.sh')],check=True)

    def test_measured_close_workload_budget_is_exact_bounded_and_still_zero_loss(self):
        from ws73_trace_layout import buffer_kib
        for kb in (8192,16384):
            with tempfile.TemporaryDirectory()as tmp:
                root=Path(tmp);paired_trace(root,requested_kb=kb)
                if kb==8192:
                    with self.assertRaises(CaptureError):check_xhci(root,'on',parallel=True,close_short=True)
                    continue
                proof=check_xhci(root,'on',parallel=True,close_short=True)
                with self.assertRaises(ValueError):buffer_kib((root/'benchmark-xhci-header-start.txt').read_text(),16385,4)
                self.assertTrue(valid_trace_summary(proof,'on',parallel=True,close_short=True))
                self.assertFalse(valid_trace_summary(proof,'on',parallel=True))
                with self.assertRaises(CaptureError):check_xhci(root,'on',parallel=True)
                bad=dict(proof,trace=dict(bytes=64*1024*1024+1));self.assertFalse(valid_trace_summary(bad,'on',parallel=True,close_short=True))
                (root/'xhci-trace-stats.txt').write_text((root/'xhci-trace-stats.txt').read_text().replace('overrun: 0','overrun: 1',1))
                with self.assertRaises(CaptureError):check_xhci(root,'on',parallel=True,close_short=True)

    def test_fixed_phase_markers_keep_legacy_and_pair_identity_separate(self):
        c=fixtures.COOKIE
        self.assertEqual(phase_marker_text(0,'BEGIN',c),f'SLK_BENCH_PHASE_BEGIN:{c}:0')
        for pair in(0,1):self.assertEqual(phase_marker_text(1,'END',c,pair=pair),f'SLK_BENCH_PAIR_{pair}_PHASE_END:{c}:1')
        for pair in(True,-1,2,'0'):
            with self.assertRaises(CaptureError):phase_marker_text(0,'BEGIN',c,pair=pair)
        for phase,boundary,cookie in [(True,'BEGIN',c),(0,'start',c),(0,'END','wrong')]:
            with self.assertRaises(CaptureError):phase_marker_text(phase,boundary,cookie)

    def test_both_pairs_require_original_clocks_markers_complete_trace_and_no_downgrade(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);paired_trace(root);proof=check_xhci(root,'on',parallel=True);self.assertTrue(valid_trace_summary(proof,'on',parallel=True));self.assertFalse(valid_trace_summary(proof,'on'))
            with self.assertRaises(CaptureError):check_xhci(root,'on')
            with self.assertRaises(CaptureError):check_xhci(root,'off',parallel=True)
        for mutation in ['missing-clock','duplicate','missing-pair','unknown-pair','wrong-cookie','phase-order','drop','truncated','legacy-marker','old-buffer']:
            with tempfile.TemporaryDirectory()as tmp:
                root=Path(tmp);paired_trace(root);path=root/'xhci-trace.log';lines=[s for s in path.read_text().splitlines()if s and not s.startswith('#')]
                if mutation=='missing-clock':(root/'benchmark-xhci-clock-start.txt').unlink()
                elif mutation=='duplicate':lines.insert(2,lines[1]);write_rows(root,lines)
                elif mutation=='missing-pair':write_rows(root,[s for s in lines if 'PAIR_1_'not in s])
                elif mutation=='unknown-pair':write_rows(root,[s.replace('PAIR_1_','PAIR_2_')for s in lines])
                elif mutation=='wrong-cookie':write_rows(root,[s.replace(fixtures.COOKIE,'ffffffff-89ab-cdef-0123-456789abcdef')if'PAIR_1_'in s else s for s in lines])
                elif mutation=='phase-order':write_rows(root,[s.replace(':0',':1')if'PAIR_1_'in s else s for s in lines])
                elif mutation=='drop':(root/'xhci-trace-stats.txt').write_text((root/'xhci-trace-stats.txt').read_text().replace('overrun: 0','overrun: 1',1))
                elif mutation=='truncated':path.write_text('\n'.join(path.read_text().splitlines()[:-1])+'\n')
                elif mutation=='old-buffer':
                    cfg=root/'benchmark-xhci-start.json';value=json.loads(cfg.read_text());value['requested_buffer_kb']=1024;cfg.write_text(json.dumps(value))
                else:write_rows(root,[s.replace('SLK_BENCH_PAIR_1_PHASE','SLK_BENCH_PHASE')for s in lines])
                with self.subTest(mutation=mutation),self.assertRaises(CaptureError):check_xhci(root,'on',parallel=True)


if __name__=='__main__':unittest.main()
