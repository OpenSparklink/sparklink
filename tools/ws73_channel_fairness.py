# SPDX-License-Identifier: GPL-2.0-only
"""Concurrent short/long application progress, not a full fairness proof.

Reuse actual dynamic sockets, application loops and the original capture parser.
The barrier schedules only VM users; it cannot grant credit or manufacture RX.
"""
from contextlib import ExitStack
import subprocess
import time

from ws73_capture import CaptureError, reassemble_acb
from ws73_channel_socket import (application_frames, burst_pressure_receipts,
                                 check_arguments, credentials, test_program)
from ws73_dynamic_channels import ApplicationOutput, await_marker, cmtc, info, request


def execute(run, phase):
    row=dict(version=1,phase=len(run.data['connection_control']['phases'])-1,
             owners=phase['typed_objects'],start_wall_ns=time.time_ns(),status='RUNNING',
             application_tool=test_program(run),channels=[],starts=[])
    run.data.setdefault('channel_fairness',[]).append(row);run.save()
    reader=ApplicationOutput(maximum=256*1024);files=ExitStack();tasks=[];failed=False
    try:
        row['unbound_refusal']=run.command(check_arguments(row['application_tool']['path'],row['owners'][0],False,1,61,route=(24570,24571,29441)),12,collection='fairness_refusals')
        if row['unbound_refusal']['exit']==0:raise CaptureError('actual unmatched endpoint refusal required')
        for name,ports,rounds,size in [('S',[24576,24577],20,61),('L',[24578,24579],16,2042)]:
            channel=dict(name=name,phase=row['phase'],ports=ports,aid=29441,rounds=rounds,message_bytes=size,
                         burst=name=='L',start_barrier=True,tx_status_required=True,
                         application_tool=row['application_tool'],owners=row['owners'],
                         start_wall_ns=time.time_ns(),applications=[])
            row['channels'].append(channel)
            for role,index in [('peer',1),('initiator',0)]:
                route=ports[::-1] if role=='peer' else ports
                argv=check_arguments(row['application_tool']['path'],row['owners'][index],index==1,rounds,size,
                                     'burst' if name=='L' and index==0 else 'regular',(*route,29441),True,True)
                app=dict(role=role,args=argv,start_wall_ns=time.time_ns());channel['applications'].append(app)
                paths=[run.output/f'fairness-{row["phase"]}-{name}-{role}.{stream}' for stream in ['stdout','stderr']]
                app['output_files']=list(map(str,paths));sinks=[files.enter_context(p.open('xb')) for p in paths]
                proc=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                tasks.append((proc,app));reader.add(proc,app,sinks);app['pid']=proc.pid;app['credentials']=credentials(proc.pid);run.save()
                await_marker(run,[(proc,app)],'NativeDynamicStaged:',time.monotonic()+3,reader)
        await_marker(run,tasks,'NativeDynamicArmed:',time.monotonic()+15,reader)
        row['armed_wall_ns']=time.time_ns()
        row['armed']=[dict(pid=a['pid'],stdout=a['stdout'],stderr=a['stderr']) for _,a in tasks]
        for snapshot in row['armed']:
            if snapshot['stdout'].count('NativeDynamicArmed:')!=1 or 'NativeChannelOpened:' in snapshot['stdout']:
                raise CaptureError('every endpoint must be armed without business before release')
        for proc,app in tasks:
            start=dict(pid=app['pid'],before_wall_ns=time.time_ns());row['starts'].append(start)
            proc.stdin.write(b'start\n');proc.stdin.flush();start['after_wall_ns']=time.time_ns();run.save()
        for channel in row['channels']:
            selected=[(p,a) for p,a in tasks if a in channel['applications']]
            await_marker(run,selected,f'NativeDynamicBusinessDone: rounds={channel["rounds"]} held=true',time.monotonic()+205,reader)
        for channel in row['channels']:
            channel['close_start_wall_ns']=time.time_ns()
            for proc,app in tasks:
                if app not in channel['applications']:continue
                if proc.poll() is not None:raise CaptureError('held reference exited before explicit close')
                proc.stdin.write(b'close\n');proc.stdin.flush();proc.stdin.close()
            for proc,app in tasks:
                if app not in channel['applications']:continue
                proc.wait(timeout=3);reader.final(app);app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
                if proc.returncode:raise CaptureError('concurrent actual application failed:'+app['stderr'])
            channel['end_wall_ns']=time.time_ns();application_frames(channel);run.save()
        row['status']='CONCURRENT_CHANNELS_USB_EVIDENCE_PENDING'
    except BaseException as error:
        failed=True;row.update(status='FAIL',error=str(error),error_type=type(error).__name__);raise
    finally:
        errors=[]
        for proc,app in tasks:
            if proc.poll() is None:proc.kill()
            proc.wait()
            if proc.stdin is not None and not proc.stdin.closed:proc.stdin.close()
            try:reader.final(app)
            except BaseException as e:errors.append(str(e))
            if 'exit' not in app:app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
        reader.close();files.close();row['cleanup_errors']=errors;row['end_wall_ns']=time.time_ns()
        if errors and not failed:row.update(status='FAIL',error=';'.join(errors))
        run.save()
        if errors and not failed:raise CaptureError('concurrent output cleanup failed')


def concurrent_progress(short, long):
    """Captured PDU-boundary progress in both directions, not latency promises."""
    observations=[]
    for role in ['initiator','peer']:
        large=[v for v in long if v['role']==role];small=[v for v in short if v['role']==role]
        if len(large)!=16 or len(small)!=20:raise CaptureError('complete short20/long16 per direction required')
        first=min(v['tx']['fragments'][0]['wall_ns'] for v in large)
        last=max(v['tx']['wall_ns'] for v in large)
        between=[v for v in small if first<v['tx']['wall_ns']<last]
        if not between:raise CaptureError('no actual short PDU progress during long TX stream')
        observations.append(dict(role=role,long_tx_window_ns=[first,last],short_pdus_between=len(between),
                                 short_sequences=[v['sequence'] for v in between]))
    return observations


def corroborate(run,capture):
    rows=run.get('channel_fairness',[])
    if len(rows)!=2:raise CaptureError('both actual physical roles required')
    packets=reassemble_acb(capture);proofs=[];nonces=set();sequences=set()
    for phase,row in enumerate(rows):
        if type(row.get('version')) is not int or row.get('version')!=1 or row.get('phase')!=phase or row.get('status')!='CONCURRENT_CHANNELS_USB_EVIDENCE_PENDING' or row.get('cleanup_errors')!=[]:
            raise CaptureError('exact complete concurrent gate receipt required')
        owners=row['owners'];used=set();physical=run['connection_control']['phases'][phase]
        if owners!=physical['typed_objects'] or len(owners)!=2:raise CaptureError('canonical physical Session identities required')
        if [c['name'] for c in row['channels']]!=['S','L']:raise CaptureError('exact two distinct short/long channels required')
        apps=[a for c in row['channels'] for a in c['applications']]
        pids=[a['pid'] for a in apps]
        if len(set(pids))!=4 or any(type(v) is not int or v<=0 for v in pids):raise CaptureError('four distinct actual application processes required')
        armed={v['pid']:v for v in row['armed']};starts={v['pid']:v for v in row['starts']}
        if set(armed)!=set(pids) or len(row['armed'])!=4 or set(starts)!=set(pids) or len(row['starts'])!=4:raise CaptureError('complete per-endpoint barrier receipts required')
        for channel in row['channels']:
            if channel.get('tx_status_required') is not True or channel.get('start_barrier') is not True:raise CaptureError('explicit barrier required')
            for app in channel['applications']:
                a=armed[app['pid']];st=starts[app['pid']];tag=f'NativeDynamicArmed: count={channel["rounds"]} bytes={channel["message_bytes"]}'
                if (a['stderr'] or not app['stdout'].startswith(a['stdout']) or a['stdout'].count(tag)!=1
                        or 'NativeChannelOpened:' in a['stdout'] or not row['armed_wall_ns']<=st['before_wall_ns']<=st['after_wall_ns']<=app['end_wall_ns']):
                    raise CaptureError('actual negotiated-before-start barrier order mismatch')
        def belongs(p,owner):
            o,obj=owner['owner'],owner['object']
            return (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],obj['handle']) and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns']
        def matched(owner,direction,raw):
            candidates=[(i,p) for i,p in enumerate(packets) if belongs(p,owner) and p['direction']==direction and p['data']==raw.hex()]
            if len(candidates)!=1:raise CaptureError('unique exact concurrent USB leg required')
            i,p=candidates[0]
            if i in used:raise CaptureError('USB obligation reused')
            used.add(i);return p
        def pair(a,b,raw):return dict(tx=matched(a,'out',raw),rx=matched(b,'in',raw))
        def connected(source,destination,ports,result,mtu=249,mps=254):
            reqs=[p for p in packets if belongs(p,owners[0]) and p['direction']=='out' and len(bytes.fromhex(p['data']))==26 and bytes.fromhex(p['data'])[4]==16 and bytes.fromhex(p['data'])[8]==source]
            if len(reqs)!=1:raise CaptureError('one actual dynamic request required')
            ident=bytes.fromhex(reqs[0]['data'])[5]
            return dict(request=pair(*owners,cmtc(request(ident,source,ports,29441,mtu,mps))),response=pair(*owners[::-1],cmtc(bytes([17,ident,4,0,source,destination,result,0]))))
        refused=row['unbound_refusal']
        if not refused['exit'] or 'NativeChannelInfo:' in refused['stdout'] or 'NativeChannelRoundTrip:' in refused['stdout']:raise CaptureError('actual refused asymmetric endpoint required')
        rejected=connected(128,0,[24570,24571],1)
        channels=[];ids=[]
        for channel,name,ports,count,size in zip(row['channels'],['S','L'],[[24576,24577],[24578,24579]],[20,16],[61,2042]):
            if (channel['name']!=name or channel['ports']!=ports or channel['aid']!=29441 or channel['rounds']!=count or channel['message_bytes']!=size or channel['burst']!=(name=='L') or channel['owners']!=owners):
                raise CaptureError('exact bounded concurrent workload required')
            fields=info(channel,owners);sent,replies=application_frames(channel)
            if name=='L':burst_pressure_receipts(channel)
            conn=connected(fields['initiator'][4],fields['peer'][4],ports,0,fields['initiator'][7],fields['initiator'][8]);legs=[]
            if conn['response']['rx']['wall_ns']>=min(st['before_wall_ns'] for st in starts.values()):raise CaptureError('all channels must be negotiated before any start')
            for seq,(data,reply) in enumerate(zip(sent,replies)):
                if data[8:24] in nonces or data[24:28] in sequences:raise CaptureError('random identity reused')
                nonces.add(data[8:24]);sequences.add(data[24:28])
                for role,a,b,raw in [('initiator',owners[0],owners[1],data),('peer',owners[1],owners[0],reply)]:
                    framed=bytes([fields[role][5],0])+(len(raw)+1).to_bytes(2,'little')+b'\xf1'+raw
                    leg=pair(a,b,framed);pid=next(v['pid'] for v in channel['applications'] if v['role']==role)
                    if leg['tx']['fragments'][0]['wall_ns']<starts[pid]['before_wall_ns'] or leg['rx']['wall_ns']>channel['end_wall_ns']:raise CaptureError('business outside released channel lifetime')
                    for direction in ['tx','rx']:
                        pieces=leg[direction]['fragments'];pb=[v.get('boundary',0) for v in pieces]
                        if pb!=([0] if len(pieces)==1 else [1]+[2]*(len(pieces)-2)+[3]) or any(not 1<=len(bytes.fromhex(v['data']))<=254 for v in pieces):raise CaptureError('bounded contiguous actual PB required')
                    legs.append(dict(sequence=seq,role=role,**leg))
            closes=[]
            for n,owner in enumerate(owners):
                role='initiator' if n==0 else 'peer';local,remote=fields[role][4:6]
                reqs=[p for p in packets if belongs(p,owner) and p['direction']=='out' and len(bytes.fromhex(p['data']))==10 and bytes.fromhex(p['data'])[4]==18 and bytes.fromhex(p['data'])[8:]==bytes([local,remote])]
                if len(reqs)>1:raise CaptureError('duplicate close outside bounded gate')
                for p in reqs:
                    raw=bytes.fromhex(p['data'])
                    if p['wall_ns']<channel['close_start_wall_ns']:raise CaptureError('close before final application release')
                    closes.append(dict(request=pair(owner,owners[1-n],raw),response=pair(owners[1-n],owner,cmtc(bytes([19,raw[5],3,0,local,remote,0])))))
            if not closes:raise CaptureError('real close exchange required')
            ids.append(fields);channels.append(dict(name=name,info=fields,connect=conn,business=legs,close=closes))
        if any(ids[0][role][4]==ids[1][role][4] for role in ['initiator','peer']):raise CaptureError('distinct per-channel TCIDs required')
        tcids={fields[role][4] for fields in ids for role in ['initiator','peer']}
        for i,p in enumerate(packets):
            if any(belongs(p,o) for o in owners):
                raw=bytes.fromhex(p['data'])
                if (raw[:2]==b'\x02\0' and len(raw)>=5 and raw[4] in (16,17,18,19) or raw and raw[0] in tcids) and i not in used:raise CaptureError('unattributed concurrent CMTC or data')
        proofs.append(dict(phase=phase,refused=rejected,channels=channels,progress=concurrent_progress(channels[0]['business'],channels[1]['business'])))
    return dict(status='REAL_CONCURRENT_SHORT_LONG_PDU_PROGRESS_SCOPED_PASS',round_trips=72,proofs=proofs,
                full_fairness_acceptance=False,performance_qualified=False,natural_recovery=False,
                scope='Bothphysicalroles,short20/long16x2042 perrole,allfournegotiatedbeforestart,actualpeerreply/twoUSB/PB andshortprogressduringlongTX;notalladmittedqueue/fairnessbounds,observercost,concurrency orNOCPproof')
