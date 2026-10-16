# SPDX-License-Identifier: GPL-2.0-only
"""Real CMTC/dynamic sockets gate; reuse ordinary apps and captured ACB.

No alternate protocol Engine. SIGSTOP only schedules a VM user process; it is
not a device fault, natural recovery, fairness or protocol reliability claim.
"""
from contextlib import ExitStack
from pathlib import Path
import os
import re
import signal
import subprocess
import time
from ws73_capture import CaptureError, reassemble_acb
from ws73_channel_socket import application_frames, credentials


def refresh(app):
    app['stdout'], app['stderr'] = [Path(p).read_text() for p in app['output_files']]


def await_marker(run, tasks, marker, deadline):
    while time.monotonic() < deadline:
        complete = True
        for process, app in tasks:
            refresh(app)
            if marker not in app['stdout']:
                complete = False
                if process.poll() is not None:
                    raise CaptureError('dynamic application exited before '+marker+': '+app['stderr'])
        if complete:
            run.save()
            return
        time.sleep(.005)
    raise CaptureError('dynamic application original observation deadline: '+marker)


def execute(run, phase):
    long_bytes=getattr(run.args,'dynamic_channel_long_bytes',None)
    row = dict(version=2 if long_bytes is not None else 1, phase=len(run.data['connection_control']['phases'])-1,
               owners=phase['typed_objects'], start_wall_ns=time.time_ns(),
               long_bytes=long_bytes, status='RUNNING', channels=[], scheduling='bounded VM peer SIGSTOP; real kernel/firmware remain running')
    run.data.setdefault('dynamic_channels', []).append(row)
    run.save()
    files=ExitStack(); all_tasks=[]; stopped=None
    def start(channel, role, entry):
        ports = channel['ports'] if role=='initiator' else channel['ports'][::-1]
        args=[str(run.args.slctl),'--adapter',entry['owner']['path'],
              'dynamic-roundtrip' if role=='initiator' else 'dynamic-peer', entry['object']['path'],
              *map(str,ports),str(channel['aid']),str(channel['rounds']),str(channel['message_bytes']),'hold']
        app=dict(role=role,args=args,start_wall_ns=time.time_ns())
        channel['applications'].append(app)
        stem=f'dynamic-{row["phase"]}-{channel["name"]}-{role}'
        paths=[run.output/(stem+'.stdout'),run.output/(stem+'.stderr')]
        app['output_files']=list(map(str,paths))
        proc=subprocess.Popen(args,stdin=subprocess.PIPE,
                              stdout=files.enter_context(paths[0].open('xb')),
                              stderr=files.enter_context(paths[1].open('xb')))
        app['pid']=proc.pid; app['credentials']=credentials(proc.pid)
        all_tasks.append((proc,app));run.save();return proc,app
    def new_channel(name,ports,rounds,message_bytes=61):
        channel=dict(name=name,ports=ports,aid=0x7301,rounds=rounds,message_bytes=message_bytes,owners=row['owners'],
                     start_wall_ns=time.time_ns(),applications=[],tx_status_required=True)
        row['channels'].append(channel);return channel
    def close_pair(channel,tasks):
        channel['close_start_wall_ns']=time.time_ns()
        for proc,app in tasks:
            if proc.poll() is not None:raise CaptureError('held dynamic fd exited early')
            proc.stdin.write(b'close\n');proc.stdin.flush();proc.stdin.close()
        for proc,app in tasks:
            proc.wait(timeout=3);refresh(app);app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
            if proc.returncode or app['stdout'].count('NativeDynamicLastClose:')!=1:
                raise CaptureError('real final dynamic fd release failed: '+app['stderr'])
        channel['end_wall_ns']=time.time_ns();run.save()
    try:
        # A real unmatched endpoint refusal also ensures asymmetric TCID
        # allocation without changing a kernel allocator or simulating a peer.
        owner=row['owners'][0]
        row['unbound_refusal']=run.command([str(run.args.slctl),'--adapter',owner['owner']['path'],
            'dynamic-roundtrip',owner['object']['path'],'24570','24571','29441','1','61'],12,collection='dynamic_refusals')
        refusal=row['unbound_refusal']
        if not refusal['exit'] or refusal['stdout'].count('NativeDynamicStaged:')!=1 or 'NativeChannelInfo:' in refusal['stdout'] or 'NativeChannelRoundTrip:' in refusal['stdout']:
            raise CaptureError('unmatched endpoint must be refused after staging; USB evidence still required')
        first=new_channel('A',[24576,24577],4)
        apeer=start(first,'peer',row['owners'][1])
        await_marker(run,[apeer],'NativeDynamicStaged:',time.monotonic()+3)
        ainit=start(first,'initiator',row['owners'][0]);atasks=[apeer,ainit]
        await_marker(run,atasks,'NativeDynamicBusinessDone: rounds=4 held=true',time.monotonic()+45)
        second=new_channel('B',[24578,24579],20)
        bpeer=start(second,'peer',row['owners'][1])
        await_marker(run,[bpeer],'NativeDynamicStaged:',time.monotonic()+3)
        os.kill(bpeer[0].pid,signal.SIGSTOP);stopped=bpeer[0]
        row['peer_stop_wall_ns']=time.time_ns();stop_deadline=time.monotonic()+5
        while '\nState:\tT' not in Path(f'/proc/{stopped.pid}/status').read_text():
            if time.monotonic()>=stop_deadline:raise CaptureError('peer process did not actually stop')
            time.sleep(.001)
        row['peer_stopped_confirmed']=True
        binit=start(second,'initiator',row['owners'][0]);btasks=[bpeer,binit]
        # Kernel negotiates B while its application is paused, then A closes.
        await_marker(run,[binit],'NativeChannelSent:',stop_deadline)
        close_pair(first,atasks)
        time.sleep(.2)  # bounded observation gap, not an assumed wire barrier
        if time.monotonic()>=stop_deadline:raise CaptureError('peer pause exceeded original five-second budget')
        os.kill(stopped.pid,signal.SIGCONT);stopped=None
        row['peer_resume_wall_ns']=time.time_ns();run.save()
        await_marker(run,btasks,'NativeDynamicBusinessDone: rounds=20 held=true',time.monotonic()+205)
        close_pair(second,btasks)
        if long_bytes is not None:
            third=new_channel('C',[24580,24581],4,long_bytes)
            cpeer=start(third,'peer',row['owners'][1])
            await_marker(run,[cpeer],'NativeDynamicStaged:',time.monotonic()+3)
            os.kill(cpeer[0].pid,signal.SIGSTOP);stopped=cpeer[0]
            row['long_peer_stop_wall_ns']=time.time_ns();limit=time.monotonic()+5
            while '\nState:\tT' not in Path(f'/proc/{stopped.pid}/status').read_text():
                if time.monotonic()>=limit:raise CaptureError('long peer did not stop within original budget')
                time.sleep(.001)
            row['long_peer_stopped_confirmed']=True
            cinit=start(third,'initiator',row['owners'][0]);ctasks=[cpeer,cinit]
            await_marker(run,[cinit],'NativeChannelSent:',limit)
            row['slot_exhaustion']=run.command([str(run.args.slctl),'--adapter',owner['owner']['path'],
                'dynamic-roundtrip',owner['object']['path'],'24582','24583','29441','1','61'],3,collection='dynamic_slot_refusals')
            refused=row['slot_exhaustion']
            if refused['exit']==0 or 'os error 28' not in refused['stderr'] or 'NativeDynamicStaged:' in refused['stdout']:
                raise CaptureError('full lifetime slot budget must reject before staging with ENOSPC')
            if time.monotonic()>=limit:raise CaptureError('long peer original pause budget exceeded')
            os.kill(stopped.pid,signal.SIGCONT);stopped=None
            row['long_peer_resume_wall_ns']=time.time_ns();run.save()
            await_marker(run,ctasks,'NativeDynamicBusinessDone: rounds=4 held=true',time.monotonic()+45)
            close_pair(third,ctasks)
        row['smtc_after_close']=[]
        for entry in row['owners']:
            receipt=run.command([str(run.args.slctl),'--adapter',entry['owner']['path'],'ssap-info',entry['object']['path']],10,collection='dynamic_smtc_after_close')
            if receipt['exit']:raise CaptureError('dynamic close affected the fixed SMTC sibling')
            row['smtc_after_close'].append(receipt)
        for channel in row['channels']:application_frames(channel)
        row['status']='DYNAMIC_CHANNELS_USB_EVIDENCE_PENDING'
    except BaseException as error:
        row.update(status='FAIL',error=str(error),error_type=type(error).__name__);raise
    finally:
        if stopped is not None and stopped.poll() is None:os.kill(stopped.pid,signal.SIGCONT)
        for proc,app in all_tasks:
            if proc.poll() is None:proc.kill()
            proc.wait();refresh(app)
            if 'exit' not in app:app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
        files.close();row['end_wall_ns']=time.time_ns();run.save()


def info(channel, owners):
    values={}
    pattern=r'^NativeChannelInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local=(\d+) remote=(\d+) pi=(\d+) mtu=(\d+) mps=(\d+) mode=(\d+) directions=(\d+)$'
    for app in channel['applications']:
        matches=re.findall(pattern,app['stdout'],re.M)
        if len(matches)!=1 or app['stdout'].count('NativeChannelInfo:')!=1:raise CaptureError('one actual dynamic ChannelInfo required')
        fields=tuple(map(int,matches[0]));entry=owners[0 if app['role']=='initiator' else 1]
        ports=channel['ports'] if app['role']=='initiator' else channel['ports'][::-1]
        staged=rf"^NativeDynamicStaged: source={ports[0]} destination={ports[1]} aid={channel['aid']} passive={'false' if app['role']=='initiator' else 'true'}$"
        done=rf"^NativeDynamicBusinessDone: rounds={channel['rounds']} held=true$"
        closed=rf"^NativeDynamicLastClose: source={ports[0]} destination={ports[1]} aid={channel['aid']}$"
        if any(len(re.findall(pattern,app['stdout'],re.M))!=1 for pattern in [staged,done,closed]):
            raise CaptureError('original staged/business/final-close application receipts required')
        if any(app['stdout'].count(marker)!=1 for marker in ['NativeDynamicStaged:','NativeDynamicBusinessDone:','NativeDynamicLastClose:']):
            raise CaptureError('duplicate or malformed dynamic receipts')
        expected=['--adapter',entry['owner']['path'],'dynamic-roundtrip' if app['role']=='initiator' else 'dynamic-peer',entry['object']['path'],*map(str,ports),str(channel['aid']),str(channel['rounds']),str(channel['message_bytes']),'hold']
        if app['args'][1:]!=expected:raise CaptureError('actual dynamic application arguments/identity mismatch')
        owner,obj=entry['owner'],entry['object']
        if fields[:4]!=(owner['index'],owner['generation'],obj['lifetime'],obj['handle']) or obj['generation']!=owner['generation']:
            raise CaptureError('dynamic immutable controller/generation/lifetime mismatch')
        mtu=max(249,channel['message_bytes'])
        if not all(0x80<=v<=0xdf for v in fields[4:6]) or fields[6:]!=(241,mtu,mtu+5,0,3):
            raise CaptureError('exact negotiated dynamic basic capabilities required')
        values[app['role']]=fields
    if set(values)!={'peer','initiator'} or values['initiator'][4:6]!=values['peer'][5:3:-1] or values['initiator'][4]==values['initiator'][5]:
        raise CaptureError('actual asymmetric cross-matched local/remote TCIDs required')
    return values


def cmtc(payload):
    return b'\x02\0'+len(payload).to_bytes(2,'little')+payload


def request(identifier,source,ports,aid,mtu=249,mps=254):
    # Independent public-format expectation, not the production C encoder.
    return bytes([0x10,identifier,18,0,source,10,1,0])+mtu.to_bytes(2,'little')+mps.to_bytes(2,'little')+bytes([1,1,1,0])+ports[1].to_bytes(2,'little')+ports[0].to_bytes(2,'little')+aid.to_bytes(2,'little')


def corroborate(run,capture):
    rows=run.get('dynamic_channels')
    if not isinstance(rows,list) or len(rows)!=2:raise CaptureError('both real connection roles require dynamic evidence')
    packets=reassemble_acb(capture);proofs=[];nonces=set();sequences=set()
    versions={row.get('version') for row in rows}
    if len(versions)!=1 or versions not in [{1},{2}]:raise CaptureError('one exact dynamic gate version required')
    extended=versions=={2}
    if extended and (any(type(row.get('long_bytes')) is not int or row['long_bytes'] not in [249,250,253,254,255,1024,2042] for row in rows) or rows[0]['long_bytes']!=rows[1]['long_bytes']):raise CaptureError('exact bounded dynamic long workload required')
    for number,row in enumerate(rows):
        if row.get('version')!=(2 if extended else 1) or row.get('phase')!=number or row.get('status')!='DYNAMIC_CHANNELS_USB_EVIDENCE_PENDING' or [c['name'] for c in row['channels']]!=(['A','B','C'] if extended else ['A','B']):
            raise CaptureError('original dynamic phase/schema/terminal evidence required')
        owners=row['owners'];used=set()
        if owners!=run['connection_control']['phases'][number]['typed_objects']:raise CaptureError('dynamic owners differ from canonical physical phase')
        if len(owners)!=2 or owners[0]['owner']['index']==owners[1]['owner']['index']:raise CaptureError('two independent controllers required')
        def belongs(p,entry):
            o,obj=entry['owner'],entry['object']
            return (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],obj['handle']) and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns']
        def matched(entry,direction,raw):
            candidates=[(n,p) for n,p in enumerate(packets) if belongs(p,entry) and p['direction']==direction and p['data']==raw.hex()]
            if len(candidates)!=1:raise CaptureError('one exact dynamic USB leg required')
            n,p=candidates[0]
            if n in used:raise CaptureError('dynamic USB leg reused across obligations')
            used.add(n);return p
        def pair(sender,receiver,raw):return dict(tx=matched(sender,'out',raw),rx=matched(receiver,'in',raw))
        def create(source,ports,destination,result,mtu=249,mps=254):
            reqs=[p for p in packets if belongs(p,owners[0]) and p['direction']=='out' and len(bytes.fromhex(p['data']))==26 and bytes.fromhex(p['data'])[4]==0x10 and bytes.fromhex(p['data'])[8]==source]
            if len(reqs)!=1:raise CaptureError('one original ConnectReq per allocated local TCID required')
            identifier=bytes.fromhex(reqs[0]['data'])[5]
            req=cmtc(request(identifier,source,ports,0x7301,mtu,mps))
            rsp=cmtc(bytes([0x11,identifier,4,0,source,destination,result,0]))
            return dict(identifier=identifier,request=pair(owners[0],owners[1],req),response=pair(owners[1],owners[0],rsp))
        refusal=row['unbound_refusal']
        if not refusal['exit'] or 'NativeChannelInfo:' in refusal['stdout'] or 'NativeChannelRoundTrip:' in refusal['stdout']:
            raise CaptureError('real refused endpoint must not become a channel')
        rejected=create(0x80,[24570,24571],0,1)
        channels=[]
        for channel in row['channels']:
            if channel.get('tx_status_required') is not True or channel.get('message_bytes')!=(row['long_bytes'] if channel['name']=='C' else 61):raise CaptureError('current dynamic budget/message evidence required')
            if channel['rounds']!=(20 if channel['name']=='B' else 4):raise CaptureError('exact two-channel workload required')
            fields=info(channel,owners);sent,replies=application_frames(channel)
            for raw in sent:
                if raw[8:24] in nonces or raw[24:28] in sequences:raise CaptureError('nonce or random wire sequence reused across channels/roles')
                nonces.add(raw[8:24]);sequences.add(raw[24:28])
            connected=create(fields['initiator'][4],channel['ports'],fields['peer'][4],0,fields['initiator'][7],fields['initiator'][8])
            legs=[]
            for sequence,(data,reply) in enumerate(zip(sent,replies)):
                for role,source,dest,raw in [('initiator',owners[0],owners[1],data),('peer',owners[1],owners[0],reply)]:
                    frame=bytes([fields[role][5],0])+ (len(raw)+1).to_bytes(2,'little')+bytes([241])+raw
                    if len(frame)>fields[role][8]:raise CaptureError('complete dynamic PDU exceeds negotiated MPS')
                    leg=pair(source,dest,frame)
                    if channel['name']=='C':
                        for direction in ['tx','rx']:
                            pieces=leg[direction].get('fragments',[])
                            if b''.join(bytes.fromhex(p['data']) for p in pieces)!=frame:raise CaptureError('dynamic long fragment bytes disagree with the exact application PDU')
                            boundaries=[p.get('boundary',0) for p in pieces]
                            expected=[0] if len(pieces)==1 else [1]+[2]*(len(pieces)-2)+[3]
                            if not pieces or boundaries!=expected or any(not 1<=len(bytes.fromhex(p['data']))<=254 for p in pieces):
                                raise CaptureError('dynamic PDU requires bounded actual PB framing on both ends')
                            if direction=='tx' and (len(pieces)>1)!=(len(frame)>254):
                                raise CaptureError('dynamic 254-byte controller boundary requires exact unfragmented/fragmented TX posture')
                    if leg['tx']['wall_ns']<connected['response']['tx']['wall_ns'] or leg['rx']['wall_ns']>channel['end_wall_ns']:
                        raise CaptureError('business outside negotiated channel lifetime')
                    legs.append(dict(sequence=sequence,role=role,**leg))
            closes=[]
            for n,sender in enumerate(owners):
                receiver=owners[1-n];role='initiator' if n==0 else 'peer'
                local,remote=fields[role][4:6]
                reqs=[p for p in packets if belongs(p,sender) and p['direction']=='out' and len(bytes.fromhex(p['data']))==10 and bytes.fromhex(p['data'])[4]==0x12 and bytes.fromhex(p['data'])[8:]==bytes([local,remote])]
                if len(reqs)>1:raise CaptureError('duplicate close requests exceed this explicit profile')
                for p in reqs:
                    raw=bytes.fromhex(p['data']);identifier=raw[5]
                    if p['wall_ns']<channel['close_start_wall_ns']:raise CaptureError('channel closed before final application release')
                    closes.append(dict(request=pair(sender,receiver,raw),response=pair(receiver,sender,cmtc(bytes([0x13,identifier,3,0,local,remote,0])))))
            if not closes:raise CaptureError('real dynamic close exchange missing')
            channels.append(dict(name=channel['name'],info=fields,connect=connected,business=legs,close=closes))
        a,b=channels[:2]
        close_end=max(c['response']['rx']['wall_ns'] for c in a['close'])
        if row.get('peer_stopped_confirmed') is not True:raise CaptureError('actual stopped VM process receipt missing')
        if not row['peer_stop_wall_ns']<row['peer_resume_wall_ns'] or row['peer_resume_wall_ns']-row['peer_stop_wall_ns']>=5_000_000_000:
            raise CaptureError('bounded original VM peer scheduling receipt required')
        if b['connect']['response']['tx']['wall_ns']>=min(c['request']['tx']['wall_ns'] for c in a['close']):
            raise CaptureError('B must be negotiated while A still exists')
        if not any(leg['sequence']>0 and leg['tx']['wall_ns']>close_end for leg in b['business']):
            raise CaptureError('actual B business after A close response required')
        if any(len({c['info'][role][4] for c in channels})!=len(channels) for role in ['initiator','peer']):raise CaptureError('channel TCID tombstone reused')
        dynamic={i for i,p in enumerate(packets) if any(belongs(p,o) for o in owners) and len(bytes.fromhex(p['data']))>=5 and bytes.fromhex(p['data'])[:2]==b'\x02\0' and bytes.fromhex(p['data'])[4] in [0x10,0x11,0x12,0x13]}
        if not dynamic.issubset(used):raise CaptureError('unattributed dynamic CMTC frame')
        dynamic_ids={value['info'][role][4] for value in channels for role in ['initiator','peer']}
        if any(i not in used and any(belongs(p,o) for o in owners) and bytes.fromhex(p['data'])[0] in dynamic_ids for i,p in enumerate(packets)):
            raise CaptureError('unattributed dynamic business frame')
        if len(row.get('smtc_after_close',[]))!=2 or any(r['exit'] for r in row['smtc_after_close']):raise CaptureError('fixed SMTC post-close observations missing')
        if extended:
            refused=row.get('slot_exhaustion',{})
            if not refused.get('exit') or 'os error 28' not in refused.get('stderr','') or 'NativeDynamicStaged:' in refused.get('stdout',''):raise CaptureError('original ENOSPC before staging required')
            if row.get('long_peer_stopped_confirmed') is not True or not row['long_peer_stop_wall_ns']<refused['start_wall_ns']<=refused['end_wall_ns']<row['long_peer_resume_wall_ns'] or row['long_peer_resume_wall_ns']-row['long_peer_stop_wall_ns']>=5_000_000_000:raise CaptureError('original bounded long-peer scheduling and resource refusal required')
            if not any(leg['sequence']>0 and leg['tx']['wall_ns']>refused['end_wall_ns'] for leg in channels[2]['business']):raise CaptureError('actual dynamic long business after slot refusal required')
        proofs.append(dict(phase=number,refused=rejected,channels=channels,close_isolation=True))
    if extended:
        return dict(status='DYNAMIC_BASIC_CHANNEL_LONG_AND_SLOT_BOUND_SCOPED_PASS',round_trips=56,long_bytes=rows[0]['long_bytes'],slot_exhaustion_refusals=2,proofs=proofs,scope=('Prior dual dynamic behavior plus C long PDU/actual two-end PB fragments and ENOSPC before staging;Cactual app replies after refusal,both physical roles;no safe TCID reuse/fullcredit/concurrency or natural recovery claim' if rows[0]['long_bytes']>249 else 'Prior dual dynamic behavior plus C249byteSDU/254bytePDU at controller boundary,actual unfragmentedTX/validpeerRX and ENOSPC before staging;Cactual app replies after refusal,bothphysicalroles;no safeTCIDreuse/fullcredit/concurrency/naturalrecovery'),reliable_mode=False,tcid_reuse=False,natural_recovery=False,full_multichannel_matrix=False)
    return dict(status='DYNAMIC_BASIC_TWO_CHANNEL_USB_AND_APPLICATION_SCOPED_PASS',round_trips=48,proofs=proofs,
                scope='Two real controllers, both physical connection roles, actual CMTC, asymmetric TCIDs, per-channel random app replies, A close/B progress; bounded VM app scheduling only',
                reliable_mode=False,tcid_reuse=False,natural_recovery=False,full_multichannel_matrix=False)
