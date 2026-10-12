# SPDX-License-Identifier: GPL-2.0-only
"""Canonical negative fixtures only; not VFS or real hardware evidence."""
import copy
import errno
import unittest
from test_ws73_management_queue_ready_peer import fixture as original
from ws73_management_queued import verify_records,corroborate
from ws73_management_ready_peer import request,expected_result
from sparklink.structs import (SleConnectionSubmit,SleConnectionParameters,SleConnectionResult,
    SleControllerSnapshot,SleManagementQuery)


def fixture():
    r,w=original();r.update(format_version=5,connection_queue=True,connection_cases=[],connection_peer_activities=[],connection_peer_releases=[])
    base=r['peer_releases'][-1]['wall_ns']+1_000_000_000
    for n,old in enumerate(r['cases']):
        v=copy.deepcopy(old);delta=base+n*1_000_000_000-old['start_wall_ns']
        for k in ['start_wall_ns','end_wall_ns','critical_start_ns','critical_end_ns','peer_during_wall_ns']:v[k]+=delta
        v.update(connection_case=True,case_index=n+6,privacy_before_errno=errno.ENOENT,privacy_after_errno=errno.ENOENT)
        index=v['index'];peer=v['peer_index'];gen=v['generation'];kind=n%3
        ps=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(r['initial_snapshots'][peer]))
        submit=SleConnectionSubmit(version=2,profile=1,operation=1,generation=gen,request_id=11+kind,timeout_ms=10000,
            parameters=SleConnectionParameters(peer_address=ps.address,gt_negotiate=1,frame=1,scan_interval=32,scan_window=32,interval_min=12,interval_max=12,supervision_timeout=508))
        queued=SleConnectionResult(version=1,profile=1,state=1,operation=1,generation=gen,request_id=11+kind,dev_index=index)
        cancelled=SleConnectionResult.from_buffer_copy(bytes(queued));cancelled.state=6;cancelled.error=-errno.ECANCELED
        v.update(input=bytes(submit).hex(),queued=bytes(queued).hex(),cancelled=bytes(cancelled).hex() if kind==0 else None,
            after_first_close_result=bytes(queued).hex() if kind==2 else None)
        r['connection_cases'].append(v)
        for phase,op in enumerate([3,4,3,4]):
            start=v['start_wall_ns']-100_000_000 if phase==0 else v['end_wall_ns']+100_000_000+phase*1000
            row=dict(connection_peer_activity=True,index=peer,case_index=n+6,phase=phase,start_wall_ns=start,end_wall_ns=start+20,
                input=bytes(request(ps,2000+(n+6)*4+phase,op)).hex(),result=bytes(expected_result(ps,2000+(n+6)*4+phase,op)).hex())
            r['connection_peer_activities'].append(row)
            for i,(opcode,params) in enumerate([(0x1001,'0000010040062003'),(0x1002,'0100')] if op==3 else [(0x1002,'0000')]):
                t=start+i*3
                w['commands'].append(dict(bus=1,device=peer+2,opcode=opcode,params=params,wall_ns=t,record=t,completion=dict(wall_ns=t+1)))
                w['complete'].append(dict(bus=1,device=peer+2,opcode=opcode,value='',status=0,wall_ns=t+2,record=t+2))
        r['connection_peer_releases'].append(dict(connection_peer_release=True,case_index=n+6,wall_ns=start+30,management=bytes(SleManagementQuery(version=1,generation=v['peer_generation'])).hex()))
    for key in ['commands','complete']:w[key].sort(key=lambda v:v['wall_ns'])
    return r,w


class NativeConnectionQueueTests(unittest.TestCase):
    def test_retained_and_closed_file_evidence_are_distinct(self):
        r,w=fixture();verify_records(r);p=corroborate(r,w)['connection_queue']
        self.assertEqual(p['cases'],6);self.assertEqual(len(p['peer_command_proofs']),36)
        self.assertFalse(p['author_result_after_final_close_observable'])
        self.assertFalse(p['inflight_reply_acceptance']);self.assertFalse(p['whole_managed_acceptance'])

    def test_author_privacy_dup_lifetime_and_cancelled_state_cannot_be_inferred(self):
        for mode in ['privacy','onwire','status','wrong-peer','fake-closed-result','first-close-cancelled','peer-off','wrong-token']:
            r,w=fixture();v=r['connection_cases'][0]
            if mode=='privacy':v['privacy_after_errno']=0
            elif mode in ['onwire','status']:
                q=SleConnectionResult.from_buffer_copy(bytes.fromhex(v['queued']));setattr(q,'state' if mode=='onwire' else 'flags',2 if mode=='onwire' else 1);v['queued']=bytes(q).hex()
            elif mode=='wrong-peer':v['peer_generation']+=1
            elif mode=='fake-closed-result':r['connection_cases'][1]['cancelled']=v['cancelled']
            elif mode=='first-close-cancelled':r['connection_cases'][2]['after_first_close_result']=v['cancelled']
            elif mode=='peer-off':v['peer_radio_during']=v['radio_before']
            else:v['wrong_token_errno']=0
            with self.subTest(mode=mode),self.assertRaises(ValueError):verify_records(r)

    def test_no_create_disconnect_extra_or_failed_wire_in_entire_extension(self):
        for key in ['commands','complete','failures']:
            r,w=fixture();c=r['connection_cases'][0];w[key].append(dict(bus=1,device=2,opcode=0x1401,wall_ns=c['start_wall_ns']+100,record=c['start_wall_ns']+100,status=0,value='',params='',completion=dict(wall_ns=c['start_wall_ns']+101)))
            with self.subTest(key=key),self.assertRaises(ValueError):corroborate(r,w)


if __name__=='__main__':unittest.main()
