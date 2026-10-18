#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual Ready Managed scanner around never-selected queue cancellation."""
from ws73_management_ready_peer import verify_row
from ws73_management_setup import decode
from sparklink.structs import SleManagementQuery,SleDiscoveryResult,SleDiscoverySubmit


def verify(record,snapshots):
    activities=record['peer_activities'];releases=record['peer_releases']
    if len(activities)!=24 or len(releases)!=6:raise ValueError('four actual peer operations and one release per case required')
    previous=record['bootstrap'][-1]['end_wall_ns']
    for number,case in enumerate(record['cases']):
        index=case['peer_index'];snapshot=snapshots[index];generation=snapshot.generation
        group=activities[number*4:number*4+4]
        for phase,(row,op) in enumerate(zip(group,[3,4,3,4])):
            if row.get('peer_activity') is not True or type(row['index']) is not int or row['index']!=index or type(row['case_index']) is not int or row['case_index']!=number or type(row['phase']) is not int or row['phase']!=phase:
                raise ValueError('exact peer phase/role required')
            verify_row(row,snapshot,2000+number*4+phase,op)
            if row['start_wall_ns']<=previous:raise ValueError('complete ordered real peer activity required')
            previous=row['end_wall_ns']
        if not group[0]['end_wall_ns']<case['start_wall_ns']<case['end_wall_ns']<group[1]['start_wall_ns']:
            raise ValueError('peer must stay On across complete quiet queue interval')
        if type(case['peer_during_wall_ns']) is not int or not case['critical_start_ns']<case['peer_during_wall_ns']<case['critical_end_ns']:
            raise ValueError('peer owner/On observed inside queued critical section required')
        if type(case['peer_writer_fd']) is not int or case['peer_writer_fd']<0 or type(case['peer_lease']) is not int or case['peer_lease']<=0:
            raise ValueError('actual independent peer descriptor/lease required')
        held=bytes(SleManagementQuery(version=1,generation=generation,state=1,mode=1)).hex()
        radio=bytes(SleDiscoveryResult(version=1,generation=generation,dev_index=index,profile=1,radio_adv=1,radio_scan=2)).hex()
        for phase in ['before','during','after']:
            if case['peer_management_'+phase]!=held or case['peer_radio_'+phase]!=radio:
                raise ValueError('complete same-generation Managed peer current On across cancellation required')
        release=releases[number]
        if release.get('peer_release') is not True or type(release['case_index']) is not int or release['case_index']!=number or type(release['wall_ns']) is not int or release['wall_ns']<=previous or release['management']!=bytes(SleManagementQuery(version=1,generation=generation)).hex():
            raise ValueError('exact peer Free only after successful real Off required')
        previous=release['wall_ns']


def corroborate(record,snapshots,capture,bootstrap):
    verify(record,snapshots)
    from ws73_capture import command_reply
    proofs=[]
    for row in record['peer_activities']:
        operation=decode(SleDiscoverySubmit,row['input']).operation
        recipe=[(0x1001,bytes.fromhex('0000010040062003')),(0x1002,b'\1\0')] if operation==3 else [(0x1002,b'\0\0')]
        owner=dict(bus=1,device=row['index']+2)
        commands=[v for v in capture['commands'] if (v['bus'],v['device'])==(owner['bus'],owner['device']) and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
        if [v['opcode'] for v in commands]!=[v[0] for v in recipe]:raise ValueError('exact real peer START/STOP wire sequence required')
        for i,(opcode,params) in enumerate(recipe):
            end=commands[i+1]['wall_ns']-1 if i+1<len(commands) else row['end_wall_ns']
            proofs.append(dict(case_index=row['case_index'],phase=row['phase'],**command_reply(capture,owner,opcode,commands[i]['wall_ns'],end,params,'')))
    start=record['bootstrap'][0]['start_wall_ns'];end=record['peer_releases'][-1]['wall_ns']
    allowed=bootstrap+proofs
    for key,part in [('commands','command'),('complete','reply')]:
        actual=[v for v in capture[key] if v['bus']==1 and v['device'] in [2,3] and start<=v['wall_ns']<=end]
        expected=sorted([v[part] for v in allowed],key=lambda v:v['wall_ns'])
        if actual!=expected:raise ValueError('unmatched command/reply outside recorded queue peer phases')
    if any(start<=v['wall_ns']<=end for v in capture['failures']):raise ValueError('transport failure inside queue/peer matrix')
    return dict(scope='six never-selected two-domain cancellations with independently Ready Managed scanner On',
        commands=proofs,quiet_intervals=[dict(start_wall_ns=v['start_wall_ns'],end_wall_ns=v['end_wall_ns']) for v in record['cases']],
        active_ready_peer_queue_isolation_acceptance=True,normal_scheduler_concurrency_acceptance=False,
        whole_managed_acceptance=False,automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)
