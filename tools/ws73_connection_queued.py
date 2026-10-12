# SPDX-License-Identifier: GPL-2.0-only
"""Canonical native queued connection File proof; no in-flight/link acceptance."""
import errno

from sparklink.structs import (SleConnectionSubmit, SleConnectionParameters,
    SleConnectionResult, SleControllerSnapshot, SleDiscoveryResult, SleDiscoverySubmit, SleManagementQuery)
from ws73_management_queued import decode, query
from ws73_management_queue_ready_peer import verify_row
from ws73_capture import command_reply


def verify(record, snapshots):
    if (record.get('connection_queue') is not True or record['confirmed_off'] is not True
            or record['ready_peer'] is not True or record['synthetic_support'] is not False):
        raise ValueError('explicit real Ready-peer queued connection gate required')
    cases=record['connection_cases'];activities=record['connection_peer_activities'];releases=record['connection_peer_releases']
    expected=[(i,k) for i in [0,1] for k in ['explicit-release','last-fd-close','dup-last-fd-close']]
    if [(v['index'],v['case']) for v in cases]!=expected or len(activities)!=24 or len(releases)!=6:
        raise ValueError('six real connection file cases and four peer operations each required')
    previous=record['peer_releases'][-1]['wall_ns']
    for n,v in enumerate(cases):
        index=v['index'];peer=1-index;gen=snapshots[index].generation;pgen=snapshots[peer].generation;kind=n%3
        if (v.get('connection_case') is not True or v['case_index']!=n+6 or v['peer_index']!=peer
                or v['generation']!=gen or v['peer_generation']!=pgen
                or not previous<v['start_wall_ns']<v['critical_start_ns']<v['peer_during_wall_ns']<v['critical_end_ns']<v['end_wall_ns']
                or v['critical_end_ns']-v['critical_start_ns']>=50_000_000
                or not 340_000_000<=v['end_wall_ns']-v['start_wall_ns']<=5_000_000_000
                or v['scheduler_restored'] is not True):
            raise ValueError('exact bounded real fd lifecycle/peer identity required')
        expected_input=SleConnectionSubmit(version=2,profile=1,operation=1,generation=gen,request_id=11+kind,timeout_ms=10000,
            parameters=SleConnectionParameters(peer_address=snapshots[peer].address,gt_negotiate=1,frame=1,scan_interval=32,scan_window=32,interval_min=12,interval_max=12,supervision_timeout=508))
        if v['input']!=bytes(expected_input).hex():raise ValueError('full actual typed Create input required')
        queued=SleConnectionResult(version=1,profile=1,state=1,operation=1,generation=gen,request_id=11+kind,dev_index=index)
        if v['queued']!=bytes(queued).hex():raise ValueError('author-only Queued with no Status/outcome/handle required')
        if kind==0:
            cancelled=SleConnectionResult.from_buffer_copy(bytes(queued));cancelled.state=6;cancelled.error=-errno.ECANCELED
            if v['cancelled']!=bytes(cancelled).hex():raise ValueError('retained author must observe exact Cancelled')
        elif v['cancelled'] is not None:
            raise ValueError('closed final File must not fabricate an observable author result')
        if (v['privacy_before_errno']!=errno.ENOENT or v['privacy_after_errno']!=errno.ENOENT
                or v['wrong_token_errno']!=(errno.EPERM if kind==0 else 0)
                or v['writer_fd']<0 or v['duplicate_fd']==v['writer_fd']):
            raise ValueError('author privacy, wrong credential and actual fds required')
        query(v['held'],gen,1);query(v['free'],gen,0)
        if kind==2:
            if v['duplicate_fd']<0 or v['after_first_close_result']!=bytes(queued).hex():raise ValueError('first dup close must preserve same File Queued')
            query(v['after_first_close'],gen,1)
        elif v['duplicate_fd']!=-1 or v['after_first_close_result'] is not None or set(v['after_first_close'])!={'0'}:
            raise ValueError('unexpected duplicate fd/proof')
        for owner,fields in [(index,['snapshot_before','snapshot_after']),(peer,['peer_before','peer_after'])]:
            ready=SleControllerSnapshot.from_buffer_copy(bytes(snapshots[owner]));ready.flags=1
            if any(v[f]!=bytes(ready).hex() for f in fields):raise ValueError('same-generation Ready metadata must remain exact')
        off=bytes(SleDiscoveryResult(version=1,profile=1,generation=gen,dev_index=index,radio_adv=1,radio_scan=1)).hex()
        if v['radio_before']!=off or v['radio_after']!=off:raise ValueError('target actual Off must remain exact')
        held=bytes(SleManagementQuery(version=1,generation=pgen,state=1,mode=1)).hex()
        on=bytes(SleDiscoveryResult(version=1,profile=1,generation=pgen,dev_index=peer,radio_adv=1,radio_scan=2)).hex()
        if (v['peer_writer_fd']<0 or v['peer_lease']<=0
                or any(v['peer_management_'+k]!=held or v['peer_radio_'+k]!=on for k in ['before','during','after'])):
            raise ValueError('independent Ready Managed scanner On must survive whole case')
        group=activities[n*4:n*4+4]
        for phase,(row,op) in enumerate(zip(group,[3,4,3,4])):
            if row.get('connection_peer_activity') is not True or row['case_index']!=n+6 or row['phase']!=phase or row['index']!=peer:
                raise ValueError('exact independent peer activity required')
            verify_row(row,snapshots[peer],2000+(n+6)*4+phase,op)
            if row['start_wall_ns']<=previous:raise ValueError('ordered non-overlapping peer operations required')
            previous=row['end_wall_ns']
        if not group[0]['end_wall_ns']<v['start_wall_ns']<v['end_wall_ns']<group[1]['start_wall_ns']:
            raise ValueError('peer scanner must be On across whole quiet interval')
        release=releases[n]
        if (release.get('connection_peer_release') is not True or release['case_index']!=n+6
                or release['wall_ns']<=previous or release['management']!=bytes(SleManagementQuery(version=1,generation=pgen)).hex()):
            raise ValueError('real peer Free after actual Off required')
        previous=release['wall_ns']


def corroborate(record, snapshots, capture):
    verify(record,snapshots);proofs=[]
    start=record['connection_peer_activities'][0]['start_wall_ns'];end=record['connection_peer_releases'][-1]['wall_ns']
    for row in record['connection_peer_activities']:
        op=decode(SleDiscoverySubmit,row['input']).operation
        recipe=[(0x1001,bytes.fromhex('0000010040062003')),(0x1002,b'\1\0')] if op==3 else [(0x1002,b'\0\0')]
        owner=dict(bus=1,device=row['index']+2)
        commands=[c for c in capture['commands'] if (c['bus'],c['device'])==(owner['bus'],owner['device']) and row['start_wall_ns']<=c['wall_ns']<=row['end_wall_ns']]
        if [c['opcode'] for c in commands]!=[x[0] for x in recipe]:raise ValueError('exact peer START/STOP command sequence required')
        for i,(opcode,params) in enumerate(recipe):
            stop=commands[i+1]['wall_ns']-1 if i+1<len(commands) else row['end_wall_ns']
            proofs.append(command_reply(capture,owner,opcode,commands[i]['wall_ns'],stop,params,''))
    for key,part in [('commands','command'),('complete','reply')]:
        actual=[c for c in capture[key] if c['bus']==1 and c['device'] in [2,3] and start<=c['wall_ns']<=end]
        if actual!=sorted([p[part] for p in proofs],key=lambda c:c['wall_ns']):
            raise ValueError('queued connection or unmatched wire traffic forbidden')
    if any(start<=c['wall_ns']<=end for c in capture['failures']):raise ValueError('no USB failures in native queued matrix')
    return dict(scope='six never-selected native Creates; actual File release/last-close/dup and independent scanner; privileged bounded FIFO support',cases=6,
        peer_command_proofs=proofs,author_result_after_final_close_observable=False,
        connected_lifecycle_acceptance=False,inflight_reply_acceptance=False,normal_scheduler_concurrency_acceptance=False,
        automatic_recovery_acceptance=False,whole_managed_acceptance=False)
