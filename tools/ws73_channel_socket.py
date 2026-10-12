# SPDX-License-Identifier: GPL-2.0-only
"""Two ordinary applications; independent two-end USB/CMTC/NOCP proof."""
from pathlib import Path
import re
import subprocess
import time
from ws73_capture import CaptureError, reassemble_acb


def credentials(pid):
    fields = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    value = dict(uids=list(map(int, fields['Uid'].split())),
                 capabilities={k: fields[k].strip() for k in ['CapEff', 'CapPrm', 'CapAmb']})
    if value['uids'] != [1000]*4 or any(int(v,16) for v in value['capabilities'].values()):
        raise CaptureError('each socket application must be uid1000 without capabilities')
    return value


def execute(run, phase):
    row = dict(phase=len(run.data['connection_control']['phases'])-1, owners=phase['typed_objects'],
               rounds=4, status='RUNNING', start_wall_ns=time.time_ns(), applications=[])
    run.data.setdefault('channel_socket', []).append(row); run.save()
    processes=[]
    try:
        # Both binds must occur during the same live connection. Never synthesize RX.
        for role, entry in [('peer', row['owners'][1]), ('initiator', row['owners'][0])]:
            args=[str(run.args.slctl),'--adapter',entry['owner']['path'],
                  'channel-peer' if role=='peer' else 'channel-roundtrip',entry['object']['path'],str(row['rounds'])]
            app=dict(role=role,args=args,start_wall_ns=time.time_ns())
            row['applications'].append(app);run.save()
            proc=subprocess.Popen(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            processes.append((proc,app));app['pid']=proc.pid
            app['credentials']=credentials(proc.pid);run.save()
        deadline=time.monotonic()+45
        for proc,app in processes:
            app['stdout'],app['stderr']=proc.communicate(timeout=max(.001,deadline-time.monotonic()))
            app.update(exit=proc.returncode,end_wall_ns=time.time_ns());run.save()
            if proc.returncode:raise CaptureError('actual socket application failed: '+app['stderr'])
        application_frames(row)
        row['status']='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING'
    except BaseException as error:
        row.update(status='FAIL',error=str(error),error_type=type(error).__name__);raise
    finally:
        for proc,app in processes:
            if proc.poll() is None:proc.kill()
            if 'exit' not in app:
                app['stdout'],app['stderr']=proc.communicate();app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
        row['end_wall_ns']=time.time_ns();run.save()


def application_frames(row):
    apps={a['role']:a for a in row['applications']}
    if set(apps)!={'peer','initiator'} or len(row['applications'])!=2 or row['rounds']!=4:
        raise CaptureError('two original application processes and four rounds required')
    for role,a in apps.items():
        if a['exit'] or a['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in a['credentials']['capabilities'].values()):
            raise CaptureError('successful ordinary applications required')
        if re.findall(r'^NativeChannelOpened: role=(\w+) rounds=(\d+)$',a['stdout'],re.M)!=[(role,'4')]:
            raise CaptureError('one original socket opening per application required')
    def rows(role,marker,elapsed=False):
        pattern=rf'^{marker}: sequence=(\d+) '+(r'elapsed_ms=(\d+) ' if elapsed else '')+r'bytes=([0-9a-f]+)$'
        values=re.findall(pattern,apps[role]['stdout'],re.M)
        if len(values)!=4 or apps[role]['stdout'].count(marker+':')!=4:raise CaptureError('all original application receipts required')
        if [int(v[0]) for v in values]!=list(range(4)):raise CaptureError('ordered unique sequence required')
        if elapsed and any(int(v[1])>=10000 for v in values):raise CaptureError('ten second round trip deadline')
        return [bytes.fromhex(v[-1]) for v in values]
    sent=rows('initiator','NativeChannelSent');received=rows('peer','NativeChannelReceived')
    reply=rows('peer','NativeChannelReply');returned=rows('initiator','NativeChannelRoundTrip',True)
    nonces=set()
    for i,data in enumerate(sent):
        if len(data)!=61 or data[:8]!=b'SLKSOCK1' or data[24:28]!=i.to_bytes(4,'little') or data[28]!=0:
            raise CaptureError('exact random application protocol required')
        if data[8:24] in nonces:raise CaptureError('fresh nonce per round required')
        nonces.add(data[8:24])
        if any(data[29+j] != data[8+j%16]^((i+j)&255) for j in range(32)):raise CaptureError('application payload mismatch')
        expected=bytearray(data);expected[28]=1
        if received[i]!=data or reply[i]!=expected or returned[i]!=expected:
            raise CaptureError('actual peer validation and exact reply required')
    return sent,reply


def corroborate(run,capture):
    rows=run.get('channel_socket')
    if rows is None or len(rows)!=2:raise CaptureError('two connection direction phases required')
    sdus=reassemble_acb(capture);proofs=[];all_nonces=set()
    for n,row in enumerate(rows):
        if row['phase']!=n or row['status']!='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING':raise CaptureError('original successful socket phase required')
        sent,replies=application_frames(row)
        owners=row['owners']
        if len(owners)!=2 or owners[0]['owner']['index']==owners[1]['owner']['index']:raise CaptureError('independent controller identities required')
        def matched(entry,direction,payload):
            owner,obj=entry['owner'],entry['object']
            if owner['generation']!=obj['generation'] or not obj['lifetime']:raise CaptureError('canonical generation/lifetime required')
            found=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device'])
                   and p['handle']==obj['handle'] and p['direction']==direction and p['data']==payload.hex()
                   and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns']]
            if len(found)!=1:raise CaptureError('one exact USB TX/opposite RX per message required')
            return found[0]
        legs=[]
        for sequence,(data,reply) in enumerate(zip(sent,replies)):
            if data[8:24] in all_nonces:raise CaptureError('random nonce reused across direction phases')
            all_nonces.add(data[8:24])
            for sender,receiver,payload in [(owners[0],owners[1],data),(owners[1],owners[0],reply)]:
                frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                legs.append(dict(sequence=sequence,tx=matched(sender,'out',frame),rx=matched(receiver,'in',frame)))
        # Each endpoint sends one capability request, one response, four business PDUs.
        capabilities=[]
        for sender,receiver in [owners,owners[::-1]]:
            query=bytes.fromhex('0200080001010400e2000000')
            response=bytes.fromhex('0200100002010c00e20000000000f900f9000101')
            capabilities.append(dict(request_tx=matched(sender,'out',query),request_rx=matched(receiver,'in',query),
                                     response_tx=matched(sender,'out',response),response_rx=matched(receiver,'in',response)))
            owner,obj=sender['owner'],sender['object']
            completed=[e for e in capture['native_events'] if e['event']==9 and (e['bus'],e['device'])==(owner['bus'],owner['device'])
                       and row['start_wall_ns']<=e['wall_ns']<=row['end_wall_ns']]
            if any(len(bytes.fromhex(e['params']))!=3 or int.from_bytes(bytes.fromhex(e['params'])[:2],'little')!=obj['handle'] for e in completed):raise CaptureError('exact actual completion handle required')
            if sum(bytes.fromhex(e['params'])[2] for e in completed)!=6:raise CaptureError('six actual completed packets per controller required')
        proofs.append(dict(phase=n,owners=owners,capabilities=capabilities,legs=legs))
    return dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=proofs,
                scope='uid1000/caps0 two applications; CMTC/basic CUTC31 PI241; 61-byte peer-validated payload; both USB/HCC/A3 ends and NOCP',
                long_pdu_acceptance=False,credit_exhaustion_acceptance=False,four_device_acceptance=False)
