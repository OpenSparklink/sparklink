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
    selected=value['path'].split('/peer_t',1)[0]
    if text not in [expected,f'Selected {selected}\n'+expected]:raise CaptureError('original GetInfo must match current typed physical identity')


def peer_info(text,value):
    path=value['path'].rsplit('/link_',1)[0]
    expected=f"NativePeerInfo: generation={value['generation']} type={value['address_type']} address={value['address']} known=true connected=true path={path}\nNativePeerConnection: path={value['path']}\n"
    selected=value['path'].split('/peer_t',1)[0]
    if text not in [expected,f'Selected {selected}\n'+expected]:raise CaptureError('typed peer must reference its exact current lifetime')


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
    path=value['path'].rsplit('/link_',1)[0]
    row=run.ctl(owner,'peer-info',path);peer_info(row['stdout'],value);peer_command=len(run.data['commands'])-1
    row=run.ctl(owner,'peer-observation',path);peer_observation(row['stdout'],value)
    observation_command=len(run.data['commands'])-1
    row=run.ctl(owner,'peers')
    if f"Peer: path={path} address={value['address']} address_type={value['address_type']} observation_valid=true " not in row['stdout']:
        raise CaptureError('typed SDK Peer listing must contain actual fresh peer identity')
    return dict(owner=owner,remote=remote,object=value,enumeration_commands=polls,info_command=connection_command,
                peer_command=peer_command,observation_command=observation_command,peer_list_command=len(run.data['commands'])-1)


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


def peer_observation(text,value):
    """Independent current CLI contract. No producer parser used as oracle."""
    path=value['path'].rsplit('/link_',1)[0];base=value['path'].split('/peer_t',1)[0]
    if text.startswith(f'Selected {base}\n'):text=text[len(f'Selected {base}\n'):]
    match=re.fullmatch(r'PeerObservation: path=(\S+) generation=(\d+) address_type=(\d+) valid=true rssi=(-?\d+) sequence=(\d+) kernel_boottime_ns=(\d+) lost=0 header=([0-9a-f]+) data=([0-9a-f]*)\n',text)
    if match is None:raise CaptureError('one fresh typed observation with known RSSI and no loss required')
    p,g,k,r,seq,boot,header,data=match.groups();g,k,r,seq,boot=map(int,[g,k,r,seq,boot]);header=bytes.fromhex(header);data=bytes.fromhex(data)
    if (p!=path or g!=value['generation'] or k!=value['address_type'] or k not in [0,1]
            or not seq or not boot or not -128<=r<=126 or len(header)!=23 or header[1]!=k
            or header[2:8]!=bytes.fromhex(value['address'].replace(':','')) or header[22]!=len(data)
            or int.from_bytes(header[21:22],signed=True)!=r):
        raise CaptureError('full typed identity, vendor header, RSSI, length and original position required')
    return dict(path=p,generation=g,address_type=k,rssi=r,sequence=seq,kernel_boottime_ns=boot,params=(header+data).hex())


def corroborate_peer_observations(run,capture):
    """New finite qualification only; never infers it for an older report.

    Original object/wire corroborators remain required independently. This
    checks new actual SDK/CLI calls and raw receiver USB, not RF type1 or timing.
    """
    uid=run['application_identity']
    if not uid['uids'][0] or len(set(uid['uids']))!=1 or any(int(uid[k],16) for k in ['cap_eff','cap_prm','cap_amb']):
        raise CaptureError('actual ordinary-user identity required')
    phases=run['connection_control']['phases']
    if len(phases)!=2:raise CaptureError('both connection roles required')
    proofs=[]
    for phase in phases:
        if len(phase['typed_objects'])!=2:raise CaptureError('both original receivers required')
        expected={(e['bus'],e['device']) for e in [phase['caller'],phase['peer']]}
        if len(expected)!=2 or {(e['owner']['bus'],e['owner']['device']) for e in phase['typed_objects']}!=expected:
            raise CaptureError('distinct original controllers required')
        for entry in phase['typed_objects']:
            value=entry['object'];owner=entry['owner'];row=run['commands'][entry['observation_command']]
            if value['generation']!=owner['generation']:raise CaptureError('original controller generation required')
            path=value['path'].rsplit('/link_',1)[0]
            if row['exit'] or row['args'][-2:]!=['peer-observation',path] or owner['path'] not in row['args']:
                raise CaptureError('actual new Peer SDK command required')
            observed=peer_observation(row['stdout'],value)
            listing=run['commands'][entry['peer_list_command']]
            if (listing['exit'] or listing['args'][-1]!='peers' or owner['path'] not in listing['args']
                    or f"Peer: path={path} address={value['address']} address_type={value['address_type']} observation_valid=true " not in listing['stdout']
                    or not row['start_boottime_ns']<=row['end_boottime_ns']
                    or observed['kernel_boottime_ns']>row['end_boottime_ns']
                    or row['end_wall_ns']>run['commands'][phase['disconnect_command']]['start_wall_ns']):
                raise CaptureError('actual typed listing and original lifetime/time window required')
            matches=[e for e in capture['native_events'] if e['event']==0x180b and (e['bus'],e['device'])==(owner['bus'],owner['device'])
                     and e['params']==observed['params'] and e['wall_ns']<=row['end_wall_ns']]
            if not matches:raise CaptureError('exact original typed advertisement must exist in receiver USB')
            proofs.append(dict(owner=owner,path=path,observation=observed,usb=max(matches,key=lambda e:e['wall_ns'])))
    return proofs
