# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic verifier fixtures: never syscall, USB or RF acceptance."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from test_ws73_diagnostic_probe import legacy_poll_fixture, eviction_fixture
from ws73_diagnostic_probe import verify_records, SleDiagnosticSubmit, SleDiagnosticResult
from ws73_diagnostic_cancel import result


def cancellation_fixture(records=None):
    records=[r for r in legacy_poll_fixture(records) if 'eviction' not in r]
    legacy=[r for r in records if 'legacy_poll' in r][-1]
    generation=legacy['generation'];first=legacy['seq']+1;start=legacy['end_wall_ns']+100
    inputs=[];outputs=[];cancel=[]
    for i,opcode in enumerate([0x0406,0x0406,0x0403]):
        value=SleDiagnosticSubmit(version=1,generation=generation,request_id=8+i,
                                  timeout_ms=5000,opcode=opcode,action=1)
        inputs.append(bytes(value).hex());value.seq=first+i;outputs.append(bytes(value).hex())
        if i!=1:
            value.action=2;cancel.append(bytes(value).hex())
    snapshots=[result(generation,first,0x0406,3,-125),result(generation,first+1,0x0406,1),
               result(generation,first+2,0x0403,3,-125)]
    held={'cancel':'held','generation':generation,'start_wall_ns':start,'end_wall_ns':start+60_000_000,
          'quiet_elapsed_ns':50_000_000,'observations':40,'inputs':inputs,'outputs':outputs,
          'cancel_outputs':cancel,'results':snapshots,'submitted_before':7,'resolved_before':7,
          'pending_before':0,'timeouts_before':0,'submitted_after':10,'resolved_after':9,
          'pending_after':1,'timeouts_after':0}
    final=copy.deepcopy(held);final.update(cancel='released',start_wall_ns=held['end_wall_ns'],
                                        end_wall_ns=held['end_wall_ns']+120_000_000,
                                        submitted_before=10,resolved_before=9,pending_before=1,
                                        resolved_after=10,pending_after=0)
    final['results'][1]=result(generation,first+1,0x0406,2,data=bytes.fromhex(legacy['data']))
    block=[{'hold_phase':'arm_ready','wall_ns':start-10},
           {'hold_phase':'wait_held','wall_ns':start+10},held,
           {'hold_phase':'release_ready','wall_ns':held['end_wall_ns']+10},final]
    at=records.index(legacy)+1
    return eviction_fixture(records[:at]+block+records[at:])


def verify(records):
    verify_records(records,admission=True,eviction=True,legacy_poll=True,cancellation=True)


class CancelRecordTests(unittest.TestCase):
    def test_valid_fixture_is_only_a_record_verifier_gate(self):
        records=cancellation_fixture();verify(records);verify_records(records[:-2],final=False,
            admission=True,eviction=True,legacy_poll=True,cancellation=True)

    def test_missing_or_extra_phase_or_cancel_cannot_pass(self):
        records=cancellation_fixture()
        for i,row in enumerate(records):
            if 'hold_phase' in row or 'cancel' in row:
                with self.subTest(i=i):
                    with self.assertRaises(ValueError):verify(records[:i]+records[i+1:])
                    with self.assertRaises(ValueError):verify(records+[copy.deepcopy(row)])

    def test_old_format_cannot_accept_new_records_or_skip_prerequisites(self):
        with self.assertRaises(ValueError):verify_records(cancellation_fixture(),admission=True,eviction=True,legacy_poll=True)
        with self.assertRaises(ValueError):verify_records(cancellation_fixture(),cancellation=True)

    def test_wrong_admission_identity_or_cancel_action_is_rejected(self):
        for key,index,field in [('inputs',0,'request_id'),('outputs',1,'seq'),('outputs',2,'opcode'),
                                ('cancel_outputs',0,'action'),('cancel_outputs',1,'timeout_ms')]:
            records=cancellation_fixture();held=next(r for r in records if r.get('cancel')=='held')
            value=SleDiagnosticSubmit.from_buffer_copy(bytes.fromhex(held[key][index]));setattr(value,field,getattr(value,field)+1)
            held[key][index]=bytes(value).hex()
            with self.subTest(key=key,index=index,field=field):
                with self.assertRaises(ValueError):verify(records)

    def test_result_revival_wrong_owner_and_payload_cannot_pass(self):
        for tag,index,field in [('held',1,'state'),('held',0,'error'),('released',0,'state'),
                                ('released',1,'seq'),('released',2,'generation'),('released',1,'_pad')]:
            records=cancellation_fixture();row=next(r for r in records if r.get('cancel')==tag)
            value=SleDiagnosticResult.from_buffer_copy(bytes.fromhex(row['results'][index]));setattr(value,field,getattr(value,field)+1)
            row['results'][index]=bytes(value).hex()
            with self.subTest(tag=tag,index=index,field=field):
                with self.assertRaises(ValueError):verify(records)

    def test_counter_replay_early_reply_timeout_and_clock_drift_are_rejected(self):
        for tag,key in [('held','submitted_after'),('held','resolved_after'),('held','pending_after'),
                        ('released','timeouts_after'),('released','start_wall_ns')]:
            records=cancellation_fixture();row=next(r for r in records if r.get('cancel')==tag);row[key]+=1
            with self.subTest(tag=tag,key=key):
                with self.assertRaises(ValueError):verify(records)
        for key,value in [('observations',False),('quiet_elapsed_ns',0),('generation',True)]:
            records=cancellation_fixture();next(r for r in records if r.get('cancel')=='held')[key]=value
            with self.assertRaises(ValueError):verify(records)
