# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic ftrace verdict negatives, not hardware/worker concurrency proof."""
import copy
import hashlib
import tempfile
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_session_idle import parse,corroborate
from sparklink.structs import SleChannelTxStatus


def fixture():
    row=dict(function='sl_work',clock='global',cookie='a'*32,interval_monotonic_ns=[100,2_000_000_100],stats={f'cpu{i}':'overrun: 0\ncommit overrun: 0\ndropped events: 0\n' for i in range(2)})
    text='# tracer: function\n# entries-in-buffer/entries-written: 4/4   #P:2\n'
    for when,event in [(1,'sl_work <-process_one_work'),(2,'tracing_mark_write: SLK_IDLE_BEGIN:'+'a'*32),(4,'tracing_mark_write: SLK_IDLE_END:'+'a'*32),(5,'sl_work <-process_one_work')]:text+=f' worker-12 [001] .... {when}.000000: {event}\n'
    return row,text


class SessionIdle(unittest.TestCase):
    def test_active_idle_active_requires_real_positive_controls(self):
        row,text=fixture();self.assertEqual(parse(text,row),dict(before=1,idle=0,after=1,events=4))

    def test_polling_is_observed_but_never_event_driven_pass(self):
        row,text=fixture();text=text.replace('4/4','5/5').replace(' worker-12 [001] .... 4.000000:', ' worker-12 [001] .... 3.000000: sl_work <-process_one_work\n worker-12 [001] .... 4.000000:')
        self.assertEqual(parse(text,row,require_idle=False)['idle'],1)
        with self.assertRaisesRegex(ValueError,'executed during'):parse(text,row)

    def test_missing_identity_capture_marker_clock_and_positive_control_fail(self):
        for kind in ['no-before','no-after','missing-marker','cookie','duplicate','truncated','loss','missing-cpu','overrun','missing-stat','duration','filter','clock','malformed']:
            row,text=fixture()
            if kind=='no-before':text=text.replace('1.000000: sl_work','1.000000: other_work')
            elif kind=='no-after':text=text.replace('5.000000: sl_work','5.000000: other_work')
            elif kind=='missing-marker':text=text.replace('SLK_IDLE_END','OTHER_END')
            elif kind=='cookie':row['cookie']='b'*32
            elif kind=='duplicate':text=text.replace('SLK_IDLE_END','SLK_IDLE_BEGIN')
            elif kind=='truncated':text=text.rsplit('\n',2)[0]+'\n'
            elif kind=='loss':text=text.replace('4/4','4/6')
            elif kind=='missing-cpu':row['stats'].pop('cpu1')
            elif kind=='overrun':row['stats']['cpu0']='overrun: 1\ncommit overrun: 0\ndropped events: 0\n'
            elif kind=='missing-stat':row['stats']['cpu0']='overrun: 0\n'
            elif kind=='duration':row['interval_monotonic_ns'][1]=200
            elif kind=='filter':row['function']='other_work'
            elif kind=='clock':row['clock']='local'
            else:text+='unparsed record\n'
            with self.subTest(kind=kind),self.assertRaises(ValueError):parse(text,row)

    def test_complete_raw_trace_and_ordinary_pool_receipts_are_bound(self):
        row,text=fixture();row.update(status='OBSERVED_NOT_PERFORMANCE_QUALIFIED',readbacks=dict(current_tracer='function',set_ftrace_filter='sl_work',trace_clock='local [global]'),trace_sha256=hashlib.sha256(text.encode()).hexdigest(),counts=parse(text,row))
        owners=[dict(generation=i+1,lifetime=1,handle=0) for i in range(2)];workers=[dict(pid=i+80,fd=i+3) for i in range(2)]
        row['pool_before']=[]
        for n,o in enumerate(owners):
            v=SleChannelTxStatus(version=1,size=64,controller=n,handle=0,generation=o['generation'],lifetime=1,packet_maximum=254,capacity=5,queue_limit=8,flags=1)
            row['pool_before'].append(dict(stage='tx_status',value=bytes(v).hex(),**workers[n]))
        r=dict(session_idle=row,channel_grant=dict(owners=owners,workers=workers))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'session-idle';p.mkdir();(p/'trace.txt').write_text(text)
            self.assertEqual(corroborate(r,tmp)['counts']['idle'],0)
            for kind in ['hash','fd','generation','credit','extra-byte','tracer','counts']:
                bad=copy.deepcopy(r);d=bad['session_idle']
                if kind=='hash':d['trace_sha256']='0'*64
                elif kind=='fd':d['pool_before'][0]['fd']+=1
                elif kind=='generation':bad['channel_grant']['owners'][0]['generation']+=1
                elif kind=='credit':
                    v=SleChannelTxStatus.from_buffer_copy(bytes.fromhex(d['pool_before'][0]['value']));v.outstanding=1;d['pool_before'][0]['value']=bytes(v).hex()
                elif kind=='extra-byte':d['pool_before'][0]['value']+='00'
                elif kind=='tracer':d['readbacks']['current_tracer']='nop'
                else:d['counts']['idle']=1
                with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(bad,tmp)
