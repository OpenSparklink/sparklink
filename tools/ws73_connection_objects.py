# SPDX-License-Identifier: GPL-2.0-only
"""Original typed D-Bus object observations, independently checked against USB.

No connection result, physical event, or object absence is synthesized here.
"""
import re
import time
from ws73_capture import CaptureError


def objects(text,owner):
    headers=re.findall(r'^NativeConnectionObjects: generation=(\d+) event_seq=(\d+) revision=(\d+) known=(true|false)$',text,re.M)
    rows=re.findall(r'^NativeConnectionObject: generation=(\d+) lifetime=(\d+) handle=(\d+) role=(\d+) type=(\d+) address=([0-9A-F:]{17}) path=(\S+)$',text,re.M)
    if len(headers)!=1 or len(rows)!=text.count('NativeConnectionObject:') or text.count('NativeConnectionObjects:')!=1:raise CaptureError('one original typed object enumeration required')
    generation,seq,revision=map(int,headers[0][:3])
    if generation!=owner['generation'] or headers[0][3]!='true' or len(rows)>16:raise CaptureError('known exact registration required')
    values=[]
    for row in rows:
        gen,lifetime,handle,role,kind=map(int,row[:5]);address,path=row[5:]
        expected=f"{owner['path']}/peer_t{kind:02x}_{address.replace(':','').lower()}/link_{lifetime:016x}"
        if gen!=generation or not 0<lifetime<=revision or handle>65535 or role>1 or kind>255 or path!=expected:raise CaptureError('immutable canonical object identity required')
        values.append(dict(generation=gen,lifetime=lifetime,handle=handle,role=role,address_type=kind,address=address,path=path))
    if len({v['lifetime'] for v in values})!=len(values) or len({v['handle'] for v in values})!=len(values):raise CaptureError('distinct current handles and lifetimes required')
    return dict(generation=generation,event_seq=seq,revision=revision,known=True),values


def info(text,value):
    expected=f"NativeConnectionInfo: generation={value['generation']} lifetime={value['lifetime']} handle={value['handle']} role={value['role']} type={value['address_type']} address={value['address']} known=true connected=true path={value['path']}\n"
    if text!=expected:raise CaptureError('original GetInfo must match current typed physical identity')


def peer_info(text,value):
    path=value['path'].rsplit('/link_',1)[0]
    expected=f"NativePeerInfo: generation={value['generation']} type={value['address_type']} address={value['address']} known=true connected=true path={path}\nNativePeerConnection: path={value['path']}\n"
    if text!=expected:raise CaptureError('typed peer must reference its exact current lifetime')


def observe(run,owner,remote):
    polls=[];deadline=time.monotonic()+1.5
    while True:
        row=run.ctl(owner,'connection-objects');polls.append(len(run.data['commands'])-1)
        header,values=objects(row['stdout'],owner)
        if len(values)==1:break
        if values or time.monotonic()>deadline:raise CaptureError('one actual published physical object required')
        time.sleep(.01)
    value=values[0]
    if value['address']!=remote['address'] or value['address_type']!=0:raise CaptureError('actual peer/type required')
    row=run.ctl(owner,'connection-info',value['path']);info(row['stdout'],value);connection_command=len(run.data['commands'])-1
    row=run.ctl(owner,'peer-info',value['path'].rsplit('/link_',1)[0]);peer_info(row['stdout'],value)
    return dict(owner=owner,remote=remote,object=value,enumeration_commands=polls,info_command=connection_command,peer_command=len(run.data['commands'])-1)


def reject_old(run,record,scope):
    owner,value=record['owner'],record['object'];polls=[];deadline=time.monotonic()+1.5
    while True:
        row=run.command([str(run.args.slctl),'--adapter',owner['path'],'connection-info',value['path']],3,collection='commands');polls.append(len(run.data['commands'])-1)
        if row['exit']:break
        if time.monotonic()>deadline:raise CaptureError('retired physical object still published')
        time.sleep(.01)
    refusal(row)
    row=run.command([str(run.args.slctl),'--adapter',owner['path'],'disconnect-object',value['path']],3,collection='commands');refusal(row)
    result=dict(owner=owner,object=value,scope=scope,info_commands=polls,disconnect_command=len(run.data['commands'])-1)
    run.save();return result


def refusal(row):
    if not row['exit'] or not re.search(r'org\.freedesktop\.DBus\.Error\.Unknown(Object|Interface|Method)',row['stderr']) or 'NativeDisconnectObject:' in row['stdout'] or 'NativeConnectionResult:' in row['stdout']:
        raise CaptureError('old object must be unavailable without a submitted procedure')


def receipt(text,value,request):
    line=f"NativeDisconnectObject: request={request} generation={value['generation']} lifetime={value['lifetime']} handle={value['handle']} role={value['role']} type={value['address_type']} address={value['address']} path={value['path']}"
    if re.findall(r'^NativeDisconnectObject:.*$',text,re.M)!=[line]:raise CaptureError('original object-targeted Disconnect receipt required')


def corroborate(run,capture,connection_proofs):
    record=run['connection_control'];proofs=[];previous={}
    if record.get('connection_objects')!='generation-type-lifetime-v1':raise CaptureError('explicit typed object scope required')
    if len(record['phases'])!=2 or len(connection_proofs)!=2:raise CaptureError('both independently proven wire phases required')
    for number,(phase,wire) in enumerate(zip(record['phases'],connection_proofs)):
        rows=phase['typed_objects']
        if len(rows)!=2:raise CaptureError('both current physical object/peer publications required')
        old_objects=dict(previous)
        identities=[(entry['owner']['bus'],entry['owner']['device']) for entry in rows]
        if len(set(identities))!=2 or set(identities)!={(owner['bus'],owner['device']) for owner in [phase['caller'],phase['peer']]}:raise CaptureError('each original owner must publish its own object')
        for entry in rows:
            owner=entry['owner'];value=entry['object'];key=(owner['bus'],owner['device']);command=run['commands'][entry['enumeration_commands'][-1]]
            header,values=objects(command['stdout'],owner)
            if command['exit'] or command['args'][-1]!='connection-objects' or values!=[value]:raise CaptureError('original enumeration mismatch')
            for field,words,check in [('info_command',['connection-info',value['path']],info),('peer_command',['peer-info',value['path'].rsplit('/link_',1)[0]],peer_info)]:
                row=run['commands'][entry[field]]
                if row['exit'] or row['args'][-2:]!=words:raise CaptureError('original typed object/peer command required')
                check(row['stdout'],value)
            events=[e for e in wire['steps'][0]['outcomes'] if (e['bus'],e['device'])==key]
            if len(events)!=1:raise CaptureError('one actual Up per object required')
            event=events[0];body=bytes.fromhex(event['params'])
            if (value['handle']!=int.from_bytes(body[1:3],'little') or value['role']!=body[3] or value['address_type']!=body[4] or bytes.fromhex(value['address'].replace(':',''))!=body[5:11]
                    or header['event_seq']==0 or not event['wall_ns']<=command['start_wall_ns']<=command['end_wall_ns']<=run['commands'][phase['disconnect_command']]['start_wall_ns']):raise CaptureError('object must match original Up before Disconnect')
            if number:
                old=previous[key]
                if value['handle']!=old['handle'] or value['lifetime']<=old['lifetime'] or value['path']==old['path']:raise CaptureError('actual handle reuse must receive a distinct newer lifetime object')
            previous[key]=value
        selected=next(e['object'] for e in rows if e['owner']==phase['caller']);row=run['commands'][phase['disconnect_command']]
        if row['args'][-2:]!=['disconnect-object',selected['path']]:raise CaptureError('normal caller must disconnect through actual object')
        receipt(row['stdout'],selected,phase['disconnect']['request'])
        refusals=phase['stale_object_rejections']
        if len(refusals)!=(2 if number==0 else 4):raise CaptureError('both-owner retired and live-reuse rejection matrix required')
        expected={(entry['object']['generation'],entry['object']['path'],'after-down') for entry in rows}
        if number:expected|={(value['generation'],value['path'],'while-reused-handle-live') for value in old_objects.values()}
        if {(entry['object']['generation'],entry['object']['path'],entry['scope']) for entry in refusals}!=expected:raise CaptureError('distinct original lifetimes and both rejection phases required')
        for entry in refusals:
            owner=entry['owner'];value=entry['object']
            for index,words in [(entry['info_commands'][-1],['connection-info',value['path']]),(entry['disconnect_command'],['disconnect-object',value['path']])]:
                row=run['commands'][index];refusal(row)
                if row['args'][-2:]!=words or owner['path'] not in row['args']:raise CaptureError('same registration old-object target required')
                if any(row['start_wall_ns']<=c['wall_ns']<=row['end_wall_ns'] for c in capture['commands']):raise CaptureError('old object refusal must emit no wire command on either radio')
            start=run['commands'][entry['info_commands'][-1]]['start_wall_ns']
            if entry['scope']=='while-reused-handle-live':
                current=next(e['object'] for e in rows if e['owner']==owner)
                if value!=old_objects[(owner['bus'],owner['device'])] or value['handle']!=current['handle'] or value['lifetime']>=current['lifetime'] or not run['commands'][phase['connect_command']]['end_wall_ns']<=start<=run['commands'][phase['disconnect_command']]['start_wall_ns']:raise CaptureError('old lifetime refusal must occur while same-handle replacement is live')
            elif entry['scope']=='after-down':
                if value not in [e['object'] for e in rows] or start<run['commands'][phase['disconnect_command']]['end_wall_ns']:raise CaptureError('old lifetime must be retired after actual Down')
            else:raise CaptureError('explicit stale object phase required')
        proofs.append(dict(current_objects=rows,stale_refusals=refusals,object_disconnect=run['commands'][phase['disconnect_command']]))
    return proofs
