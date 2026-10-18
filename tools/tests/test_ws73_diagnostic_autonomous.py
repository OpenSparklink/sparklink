# SPDX-License-Identifier: GPL-2.0-only
"""Passive-expiry fixtures only; frozen live C/USB proof required separately."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from test_ws73_diagnostic_deadline import deadline_fixture
from test_ws73_diagnostic_probe import eviction_fixture
from ws73_diagnostic_probe import verify_records,SleDiagnosticSubmit
from ws73_diagnostic_autonomous import stats_bytes
from ws73_diagnostic_cancel import result


def autonomous_fixture(records=None):
    rows=[r for r in deadline_fixture(records) if 'eviction' not in r]
    held,final=[r for r in rows if 'cancel' in r]
    generation=held['generation'];admit=held['deadline']['samples'][-1]['after_monotonic_ns']+1_000_000
    value=SleDiagnosticSubmit(version=1,generation=generation,request_id=12,timeout_ms=100,opcode=0x0403,action=1)
    raw=bytes(value).hex();value.seq=12
    pending=result(generation,12,0x0403,1);expired=result(generation,12,0x0403,3,-110)
    held['autonomous']={'input':raw,'output':bytes(value).hex(),'initial_result':pending,'result':expired,
        'stats_before':stats_bytes(12,10,2,1),'stats_after':stats_bytes(12,11,1,2),
        'admit_before_monotonic_ns':admit,'admit_after_monotonic_ns':admit+1,
        'quiet_before_monotonic_ns':admit+100,'quiet_after_monotonic_ns':admit+800_000_100,
        'stats_before_monotonic_ns':admit+800_000_110,'stats_after_monotonic_ns':admit+800_000_120,
        'result_before_monotonic_ns':admit+800_000_130,'result_after_monotonic_ns':admit+800_000_140}
    held.update(end_wall_ns=held['end_wall_ns']+800_000_000,quiet_elapsed_ns=950_000_000,
                submitted_after=12,resolved_after=11,timeouts_after=2)
    final.update(start_wall_ns=held['end_wall_ns'],end_wall_ns=held['end_wall_ns']+120_000_000,
                 submitted_before=12,submitted_after=12,resolved_before=11,resolved_after=12,
                 timeouts_before=2,timeouts_after=2,autonomous={'result':expired})
    next(r for r in rows if r.get('hold_phase')=='release_ready')['wall_ns']=held['end_wall_ns']+10
    return eviction_fixture(rows)


def verify(rows):
    verify_records(rows,admission=True,eviction=True,legacy_poll=True,cancellation=True,deadline=True,autonomous=True)


class AutonomousRecords(unittest.TestCase):
    def test_valid_passive_counter_before_result(self):
        rows=autonomous_fixture();verify(rows)
        verify_records(rows[:-2],final=False,admission=True,eviction=True,legacy_poll=True,cancellation=True,deadline=True,autonomous=True)

    def test_mode_and_required_data_cannot_downgrade(self):
        with self.assertRaises(ValueError):verify(deadline_fixture())
        with self.assertRaises(ValueError):verify_records(autonomous_fixture(),admission=True,eviction=True,legacy_poll=True,cancellation=True,deadline=True)
        with self.assertRaises(ValueError):verify_records(autonomous_fixture(),autonomous=True)
        for tag in ['held','released']:
            rows=autonomous_fixture();next(r for r in rows if r.get('cancel')==tag).pop('autonomous')
            with self.assertRaises(ValueError):verify(rows)

    def test_still_pending_or_wrong_counter_snapshot_rejected(self):
        for key,value in [('stats_after',stats_bytes(12,10,2,1)),('stats_before',stats_bytes(12,11,1,2)),
                          ('stats_after',stats_bytes(12,11,1,3)),('stats_after','00'*16)]:
            rows=autonomous_fixture();next(r for r in rows if r.get('cancel')=='held')['autonomous'][key]=value
            with self.subTest(key=key,value=value):
                with self.assertRaises(ValueError):verify(rows)

    def test_short_silence_or_stats_after_result_rejected(self):
        for key,value in [('quiet_after_monotonic_ns',100_500_000_000),('stats_before_monotonic_ns',True),
                          ('stats_after_monotonic_ns',101_000_000_000),('admit_before_monotonic_ns',0)]:
            rows=autonomous_fixture();next(r for r in rows if r.get('cancel')=='held')['autonomous'][key]=value
            with self.assertRaises(ValueError):verify(rows)

    def test_identity_and_exact_retained_result_required(self):
        for tag,key in [('held','input'),('held','output'),('held','initial_result'),('held','result'),('released','result')]:
            rows=autonomous_fixture();next(r for r in rows if r.get('cancel')==tag)['autonomous'][key]='00'*104
            with self.assertRaises(ValueError):verify(rows)

    def test_timeout_once_and_eviction_continuity_required(self):
        for tag,key in [('held','timeouts_after'),('held','resolved_after'),('released','timeouts_after'),('released','submitted_after')]:
            rows=autonomous_fixture();next(r for r in rows if r.get('cancel')==tag)[key]+=1
            with self.assertRaises(ValueError):verify(rows)
