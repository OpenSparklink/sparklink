#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real Managed peer scanning across another controller's held-reply cleanup."""
import time

from sparklink.structs import SleDiscoverySubmit, SleDiscoveryResult, SleControllerSnapshot, SleManagementQuery
from ws73_management_setup import decode


def request(snapshot, identifier, operation):
    from ws73_management_partial import standby
    if operation in (3,5,6):
        value=standby(snapshot,identifier,'advertising' if operation==5 else 'scanning')
        value.operation=operation
        return value
    return SleDiscoverySubmit(version=1,generation=snapshot.generation,request_id=identifier,profile=1,operation=operation)


def ready_bytes(snapshot):
    value=SleControllerSnapshot.from_buffer_copy(bytes(snapshot));value.flags=1
    return bytes(value).hex()


def expected_result(snapshot,identifier,operation,power=0):
    count={3:2,4:1,5:2,6:3}[operation]
    return SleDiscoveryResult(version=1,generation=snapshot.generation,dev_index=snapshot.dev_index,
        request_id=identifier,profile=1,operation=operation,state=3,count=count,step=count-1,
        opcode=0xc05 if operation==5 else 0x1002,radio_adv=1,
        radio_scan=0 if operation==5 else 2 if operation==3 else 1,
        power_valid=1 if operation==5 else 0,selected_power=power)


def verify_row(row,snapshot,identifier,operation):
    if row['input']!=bytes(request(snapshot,identifier,operation)).hex():
        raise ValueError('exact Ready peer policy request required')
    result=decode(SleDiscoveryResult,row['result'])
    power=result.selected_power if operation==5 else 0
    if not -128<=power<=127 or bytes(result)!=bytes(expected_result(snapshot,identifier,operation,power)):
        raise ValueError('actual successful peer policy/radio result required')
    start,end=row['start_wall_ns'],row['end_wall_ns']
    if type(start) is not int or type(end) is not int or not 0<start<=end or end-start>=6_000_000_000:
        raise ValueError('bounded real peer operation interval required')


def verify(record,snapshot):
    peer=record['ready_peer']
    groups=[('bootstrap',[(101,5),(102,6)]),('before',[(201,3),(202,4)]),
            ('during',[(203,3)]),('after',[(204,4),(205,3),(206,4)])]
    previous=0
    for key,operations in groups:
        rows=peer[key]
        if len(rows)!=len(operations):raise ValueError('complete Ready peer phase required')
        for row,(identifier,operation) in zip(rows,operations):
            verify_row(row,snapshot,identifier,operation)
            if row['start_wall_ns']<=previous:raise ValueError('ordered peer phases required')
            previous=row['end_wall_ns']
    if peer['ready_snapshot']!=ready_bytes(snapshot) or record['peer_after']!=peer['ready_snapshot']:
        raise ValueError('same Ready peer registration and complete metadata required')
    management=bytes(SleManagementQuery(version=1,generation=snapshot.generation,state=1,mode=1)).hex()
    if record['peer_management_before']!=management or record['peer_management_after']!=management:
        raise ValueError('peer Managed ownership must survive target cleanup')
    if record['peer_queries']!=[]:raise ValueError('Ready activity cannot borrow Diagnostic query evidence')
    markers=record['markers']
    if peer['before'][-1]['end_wall_ns']>=markers[0]['wall_ns']:
        raise ValueError('peer before activity must finish before target hold arm')
    if not markers[1]['wall_ns']<peer['during'][0]['start_wall_ns']<=peer['during'][0]['end_wall_ns']<record['release_before_wall_ns']:
        raise ValueError('real peer START must complete while target reply is held')
    for key,lower,upper in [('on_before_cancel',peer['during'][0]['end_wall_ns'],record['release_before_wall_ns']),
                            ('on_after_free',record['management_observations'][-1]['wall_ns'],peer['after'][0]['start_wall_ns'])]:
        observation=peer[key]
        if type(observation['wall_ns']) is not int or not lower<observation['wall_ns']<upper:
            raise ValueError('peer On observations must bracket target cancellation and Free')
        if observation['snapshot']!=peer['ready_snapshot'] or observation['management']!=management or observation['result']!=peer['during'][0]['result']:
            raise ValueError('actual same-generation Ready/owner/On must span target cleanup')
    if peer['released_management']!=bytes(SleManagementQuery(version=1,generation=snapshot.generation)).hex():
        raise ValueError('peer lease release only after successful activity and real Off required')


def corroborate_activity_rows(peer,snapshot,capture,owner):
    """Actual peer wire rows only;caller must verify its lifecycle scope."""
    from ws73_capture import command_reply
    proofs=[]
    for phase in ['bootstrap','before','during','after']:
        for row in peer[phase]:
            command=decode(SleDiscoverySubmit,row['input']);result=decode(SleDiscoveryResult,row['result'])
            op=command.operation
            sequence=[(0xc02,None,bytes([result.selected_power & 255]).hex()),(0xc05,b'\0'*5,'')] if op==5 else (
                [(0x1001,bytes.fromhex('0000010040062003'),''),(0x1002,b'\1\0','')]+([(0x1002,b'\0\0','')] if op==6 else []) if op in (3,6) else [(0x1002,b'\0\0','')])
            commands=[v for v in capture['commands'] if (v['bus'],v['device'])==(owner['bus'],owner['device'])
                and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
            if [v['opcode'] for v in commands]!=[v[0] for v in sequence]:
                raise ValueError('exact Ready peer command sequence required')
            previous=row['start_wall_ns']
            for i,(opcode,params,value) in enumerate(sequence):
                limit=commands[i+1]['wall_ns']-1 if i+1<len(commands) else row['end_wall_ns']
                proof=command_reply(capture,owner,opcode,commands[i]['wall_ns'],limit,params,value)
                if proof['reply']['wall_ns']<previous:raise ValueError('ordered actual peer replies required')
                if opcode==0xc02:
                    raw=bytes.fromhex(proof['command']['params'])
                    if len(raw)!=49 or raw[0]!=0 or raw[12:18]!=bytes(snapshot.address):
                        raise ValueError('bootstrap advertising must address the peer controller')
                previous=proof['reply']['wall_ns'];proofs.append(dict(phase=phase,**proof))
    start=peer['bootstrap'][0]['start_wall_ns'];end=peer['after'][-1]['end_wall_ns']
    for key,part in [('commands','command'),('complete','reply')]:
        actual=[v for v in capture[key] if (v['bus'],v['device'])==(owner['bus'],owner['device']) and start<=v['wall_ns']<=end]
        if actual!=[v[part] for v in proofs]:raise ValueError('unmatched peer command/reply or cross-device STOP')
    return proofs


def corroborate(record,snapshot,capture):
    verify(record,snapshot)
    peer=record['ready_peer']
    proofs=corroborate_activity_rows(peer,snapshot,capture,dict(bus=1,device=3))
    return dict(scope='real Ready peer Managed scan On spans target cancellation, original late reply and Free',
        proofs=proofs,on_before_cancel=peer['on_before_cancel'],on_after_free=peer['on_after_free'],
        active_ready_peer_isolation_case_acceptance=True,whole_managed_acceptance=False,
        automatic_fault_recovery_acceptance=False,natural_fault_root_cause_closed=False)


class ReadyPeer:
    def __init__(self,adapter,observer,snapshot,record,save):
        self.adapter=adapter;self.observer=observer;self.snapshot=snapshot;self.record=record;self.save=save
        record['ready_peer']=dict(bootstrap=[],before=[],during=[],after=[])
        self.perform('bootstrap',101,5);self.perform('bootstrap',102,6)
        record['ready_peer']['ready_snapshot']=bytes(observer.snapshot()).hex();save()
        if record['ready_peer']['ready_snapshot']!=ready_bytes(snapshot):raise ValueError('actual peer Ready bootstrap failed')

    def perform(self,phase,identifier,operation):
        command=request(self.snapshot,identifier,operation)
        row=dict(input=bytes(command).hex(),start_wall_ns=time.time_ns())
        self.record['ready_peer'][phase].append(row);self.save()
        self.adapter.submit_discovery(command);deadline=time.monotonic()+6
        while True:
            result=self.observer.discovery_result(identifier)
            if result is not None and result.is_terminal:break
            if time.monotonic()>deadline:raise TimeoutError('actual Ready peer policy completion')
            time.sleep(.002)
        row.update(result=bytes(result).hex(),end_wall_ns=time.time_ns());self.save()
        verify_row(row,self.snapshot,identifier,operation)

    def observe_on(self,key):
        self.record['ready_peer'][key]=dict(wall_ns=time.time_ns(),snapshot=bytes(self.observer.snapshot()).hex(),
            management=bytes(self.observer.management_status()).hex(),result=bytes(self.observer.discovery_result(203)).hex());self.save()

    def phase(self,number):
        if number==1:
            self.perform('before',201,3);self.perform('before',202,4)
        elif number==2:
            self.perform('during',203,3);self.observe_on('on_before_cancel')
        elif number==3:
            self.observe_on('on_after_free')
            self.perform('after',204,4);self.perform('after',205,3);self.perform('after',206,4)
        else:raise ValueError('bounded Ready peer phase')
