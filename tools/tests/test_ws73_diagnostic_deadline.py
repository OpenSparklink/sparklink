# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic metadata/time/wire mutations only; no real deadline qualification."""
import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from test_ws73_diagnostic_cancel import cancellation_fixture
from test_ws73_diagnostic_probe import eviction_fixture
from ws73_diagnostic_probe import verify_records,SleDiagnosticSubmit
from ws73_diagnostic_cancel import result


def deadline_fixture(records=None):
    rows=[r for r in cancellation_fixture(records) if 'eviction' not in r]
    held,final=[r for r in rows if 'cancel' in r]
    generation=held['generation'];admit=100_000_000_000
    value=SleDiagnosticSubmit(version=1,generation=generation,request_id=11,
                              timeout_ms=100,opcode=0x0403,action=1)
    raw=bytes(value).hex();value.seq=SleDiagnosticSubmit.from_buffer_copy(bytes.fromhex(held['outputs'][-1])).seq+1
    output=bytes(value).hex();pending=result(generation,value.seq,0x0403,1)
    expired=result(generation,value.seq,0x0403,3,-110)
    samples=[{'before_monotonic_ns':admit+i*1_000_000+10,
              'after_monotonic_ns':admit+i*1_000_000+20,'retry':output,
              'result':pending if i<100 else expired} for i in range(150)]
    held['deadline']={'input':raw,'output':output,'initial_result':pending,
                      'admit_before_monotonic_ns':admit,'admit_after_monotonic_ns':admit+1,'samples':samples}
    held['end_wall_ns']+=100_000_000;held['quiet_elapsed_ns']=150_000_000;held['observations']=150
    held.update(submitted_after=11,resolved_after=10,timeouts_after=1)
    final.update(start_wall_ns=held['end_wall_ns'],end_wall_ns=held['end_wall_ns']+120_000_000,
                 submitted_before=11,submitted_after=11,resolved_before=10,resolved_after=11,
                 timeouts_before=1,timeouts_after=1,deadline={'result':expired})
    next(r for r in rows if r.get('hold_phase')=='release_ready')['wall_ns']=held['end_wall_ns']+10
    return eviction_fixture(rows)


def verify(rows):
    verify_records(rows,admission=True,eviction=True,legacy_poll=True,cancellation=True,deadline=True)


class DeadlineRecords(unittest.TestCase):
    def test_valid_record_fixture_and_predaemon_subset(self):
        rows=deadline_fixture();verify(rows)
        verify_records(rows[:-2],final=False,admission=True,eviction=True,legacy_poll=True,cancellation=True,deadline=True)

    def test_missing_new_mode_or_required_data_rejected(self):
        with self.assertRaises(ValueError):verify(cancellation_fixture())
        with self.assertRaises(ValueError):verify_records(deadline_fixture(),admission=True,eviction=True,legacy_poll=True,cancellation=True)
        with self.assertRaises(ValueError):verify_records(deadline_fixture(),deadline=True)
        for tag in ['held','released']:
            rows=deadline_fixture();next(r for r in rows if r.get('cancel')==tag).pop('deadline')
            with self.assertRaises(ValueError):verify(rows)

    def test_wrong_original_identity_or_output_seq_is_rejected(self):
        for key,field in [('input','request_id'),('input','timeout_ms'),('output','seq'),('output','generation')]:
            rows=deadline_fixture();row=next(r for r in rows if r.get('cancel')=='held')['deadline']
            value=SleDiagnosticSubmit.from_buffer_copy(bytes.fromhex(row[key]));setattr(value,field,getattr(value,field)+1);row[key]=bytes(value).hex()
            with self.subTest(key=key,field=field):
                with self.assertRaises(ValueError):verify(rows)

    def test_never_expires_early_expires_or_revival_rejected(self):
        for mutation in ['never','early','revive','wrong_error','renew']:
            rows=deadline_fixture();r=next(r for r in rows if r.get('cancel')=='held')['deadline'];samples=r['samples']
            if mutation=='never':
                for s in samples:s['result']=r['initial_result']
            elif mutation=='early':samples[10]['result']=samples[-1]['result']
            elif mutation=='revive':samples[110]['result']=r['initial_result']
            elif mutation=='wrong_error':samples[-1]['result']='00'*104
            else:samples[-1]['retry']=r['input']
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):verify(rows)

    def test_clock_types_gaps_and_bounds_rejected(self):
        for key,value in [('before_monotonic_ns',True),('after_monotonic_ns',0),('before_monotonic_ns',100_080_000_000)]:
            rows=deadline_fixture();next(r for r in rows if r.get('cancel')=='held')['deadline']['samples'][10][key]=value
            with self.assertRaises(ValueError):verify(rows)
        rows=deadline_fixture();next(r for r in rows if r.get('cancel')=='held')['deadline']['samples']=[]
        with self.assertRaises(ValueError):verify(rows)

    def test_counter_timeout_once_and_late_retention_required(self):
        for tag,key in [('held','timeouts_after'),('held','submitted_after'),('released','timeouts_after'),('released','resolved_after')]:
            rows=deadline_fixture();next(r for r in rows if r.get('cancel')==tag)[key]+=1
            with self.assertRaises(ValueError):verify(rows)
        rows=deadline_fixture();next(r for r in rows if r.get('cancel')=='released')['deadline']['result']='00'*104
        with self.assertRaises(ValueError):verify(rows)
