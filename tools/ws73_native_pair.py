# SPDX-License-Identifier: GPL-2.0-only
"""Shared Native test-pair operations and original independent USB oracles.

The two-controller File gate and its explicit sibling composition use the same
functions. No Host state, synthetic controller or application I/O loop lives here.
"""
import struct
import time
from ws73_management_setup import decode
from sparklink.structs import (SleConnectionSubmit, SleConnectionParameters,
    SleDiscoverySubmit, SleDiscoveryResult, SleConnectionResult)
from ws73_capture import CaptureError, marker_data, command_reply


def connection(snapshot, peer):
    return SleConnectionSubmit(version=2, profile=1, operation=1,
        generation=snapshot.generation, request_id=900, timeout_ms=10000,
        parameters=SleConnectionParameters(peer_address=peer.address,
            gt_negotiate=1, frame=1, scan_interval=32, scan_window=32,
            interval_min=12, interval_max=12, supervision_timeout=508))

def stop(snapshot, identifier, operation):
    if operation not in [2,4]:raise ValueError('typed radio stop only')
    return SleDiscoverySubmit(version=1,profile=1,generation=snapshot.generation,request_id=identifier,operation=operation)

def drain_events(observers,record):
    for n,a in enumerate(observers):
        while (event:=a.poll_event())is not None:
            record['events'][n].append(dict(event=event.event_code,params=bytes(event.payload[:event.payload_len]).hex(),
                generation=event.generation,seq=event.seq,lost=event.lost,wall_ns=time.time_ns()))

def discovery_operation(writers,observers,record,save,drain,n,request):
    ids=record.get('controller_ids',[0,1])
    row=dict(index=ids[n],input=bytes(request).hex(),start_wall_ns=time.time_ns());record['discovery'].append(row);save()
    writers[n].submit_discovery(request);deadline=time.monotonic()+8
    while True:
        value=observers[n].discovery_result(request.request_id);drain()
        if value is not None and value.is_terminal:break
        if time.monotonic()>deadline:raise TimeoutError('real discovery')
        time.sleep(.002)
    row.update(result=bytes(value).hex(),end_wall_ns=time.time_ns());save()
    if value.state!=3 or value.error or value.status:raise ValueError('real discovery failed')

def await_events(record,drain,key,codes,index=None):
    deadline=time.monotonic()+8
    while True:
        drain();values=[[e for e in events if e['event']in codes]for events in record['events']]
        if index is not None and len(values[index])==1:return values[index][0]
        if index is None and all(len(v)==1 for v in values):return[v[0]for v in values]
        if time.monotonic()>deadline:raise TimeoutError('both actual '+key+' events')
        time.sleep(.002)

def check_transport(record,capture,start,end):
    """The same complete USB failure rule, scoped to this explicit pair/window.

    A four-controller capture also contains another pair's initialization.
    Its pre-policy receive cancellations remain evidence, not this pair's
    business transport outcome. Every selected in-window failure still fails.
    """
    selected={(v['bus'],v['device'])for v in record['usb']}
    if any((e['bus'],e['device'])in selected and start<=e['wall_ns']<=end
           for e in capture['failures']):
        raise CaptureError('USB transport failure inside selected Native pair gate')

def corroborate_discovery(r,capture,snapshots):
    i=r['index']
    def belongs(row,n,start,end):
        usb=r['usb'][n]
        return(row['bus'],row['device'])==(usb['bus'],usb['device'])and start<=row['wall_ns']<=end
    proofs=[]
    for row in r['discovery']:
        n=r.get('controller_ids',[0,1]).index(row['index']); value=decode(SleDiscoveryResult,row['result']); request=decode(SleDiscoverySubmit,row['input'])
        recipes={1:[0xc08,0xc02,0xc03,0xc05],2:[0xc05],3:[0x1001,0x1002],4:[0x1002],5:[0xc02,0xc05],6:[0x1001,0x1002,0x1002]}
        commands=[c for c in capture['commands'] if belongs(c,n,row['start_wall_ns'],row['end_wall_ns'])]
        if [c['opcode'] for c in commands]!=recipes[request.operation] or value.state!=3 or value.error or value.status:
            raise CaptureError('exact original successful discovery recipe required')
        for j,c in enumerate(commands):
            upper=commands[j+1]['wall_ns']-1 if j+1<len(commands) else row['end_wall_ns']
            params=(bytes(1) if c['opcode']==0xc08 else bytes([int(request.operation==1),0,0,0,0]) if c['opcode']==0xc05
                else bytes([0,3,len(marker_data(r['marker']))])+marker_data(r['marker']) if c['opcode']==0xc03
                else bytes([int(request.operation==3 or request.operation==6 and j==1),0]) if c['opcode']==0x1002
                else bytes.fromhex('0000010040062003') if c['opcode']==0x1001 else None)
            if c['opcode']==0xc02:
                params=bytearray(49);params[2]=2;params[3:6]=(1200).to_bytes(3,'little');params[6:9]=params[3:6]
                params[9]=7;params[12:18]=bytes(snapshots[n].address);params[25]=127;params[43]=200
                if request.operation==1:
                    params[1]=3;params[2]=0;params[34]=1;params[37:39]=(100).to_bytes(2,'little');params[39:41]=params[37:39]
                params=bytes(params)
            proofs.append(command_reply(capture,r['usb'][n],c['opcode'],c['wall_ns'],upper,params,
                bytes([value.selected_power&255]).hex() if c['opcode']==0xc02 else ''))
    heard=[e for e in capture['reports'] if belongs(e,i,r['scan_start_wall_ns'],r['scan_end_wall_ns'])
        and all(e[k]==r['scan_match'][k] for k in ['address','data','rssi'])]
    if not heard:raise CaptureError('independent actual random marker RX required')
    return proofs,heard

def corroborate_transition(r,capture,snapshots,operation,opcode,start,end,key,*,expected_cleanup_reason=0x10):
    if (operation,opcode,key)not in[(1,0x1401,'up'),(2,0x1403,'down')]:raise CaptureError('explicit physical transition required')
    if expected_cleanup_reason not in(0x10,0x13):raise CaptureError('explicit SLE cleanup reason required')
    i=r['index'];p=1-i
    def belongs(row,n,start,end):
        usb=r['usb'][n]
        return(row['bus'],row['device'])==(usb['bus'],usb['device'])and start<=row['wall_ns']<=end
    commands=[c for c in capture['commands'] if belongs(c,i,start,end) and c['opcode']==opcode]
    # Connected revocation has no radio obligations on this target.
    if len(commands)!=1 or commands[0]['opcode']!=opcode:raise CaptureError('exact actual Create/cleanup Disconnect required')
    command=commands[0]
    status=[e for e in capture['native_events'] if belongs(e,i,start,end) and e['event']==1
        and len(bytes.fromhex(e['params']))==4 and bytes.fromhex(e['params'])[:2]==opcode.to_bytes(2,'little')
        and bytes.fromhex(e['params'])[3]==0]
    if len(status)!=1 or command['completion']['wall_ns']>end:raise CaptureError('real OUT and successful Status required')
    body=bytes.fromhex(command['params'])
    expected_create=bytes(3)+bytes(snapshots[p].address)+bytes([1,1])+struct.pack('<8H',32,32,12,12,0,508,0,0)
    if operation==1 and body!=expected_create:
        raise CaptureError('Create must target actual peer')
    handle=int.from_bytes(bytes.fromhex(r['up'][i]['params'])[1:3],'little')
    if not r.get('reply_hold') and handle!=decode(SleConnectionResult,r['connected']).handle:
        raise CaptureError('author result must match actual physical handle')
    if operation==2 and body!=handle.to_bytes(2,'little')+bytes([expected_cleanup_reason]):raise CaptureError('exact cleanup handle/reason required')
    outcomes=[]
    for n in [i,p]:
        receipt=r[key][n]
        events=[e for e in capture['native_events'] if belongs(e,n,start,end)
            and e['event']==receipt['event'] and e['params']==receipt['params']]
        if len(events)!=1:raise CaptureError('one independent exact physical outcome on each device required')
        outcomes.append(events[0])
    return dict(command=command,status=status[0],outcomes=outcomes)
