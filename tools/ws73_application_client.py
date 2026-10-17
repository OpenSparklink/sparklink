# SPDX-License-Identifier: GPL-2.0-only
"""One-shot public C/Python application clients; reuse existing VM/capture gates.

No synthetic controller, protocol Engine, load generator or performance claim.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import time
from ws73_capture import CaptureError, reassemble_acb
from ws73_channel_socket import credentials
from ws73_north_star import file_record


def receipts(app, entry):
    try:rows=[json.loads(line) for line in app['stdout'].splitlines()]
    except (ValueError,KeyError) as exc:raise CaptureError('complete original application JSON required') from exc
    if len(rows)!=2 or [r.get('stage') for r in rows]!=['ready','complete'] or any(r.get('api')!=app['api'] for r in rows):raise CaptureError('one actual ready/complete pair per API required')
    ready,complete=rows;owner,obj=entry['owner'],entry['object']
    if set(ready)!={'stage','api','index','generation','lifetime','handle','dup_alive','client_closed'} or (ready['index'],ready['generation'],ready['lifetime'],ready['handle'])!=(owner['index'],owner['generation'],obj['lifetime'],obj['handle']) or ready['dup_alive'] is not True or ready['client_closed'] is not True:raise CaptureError('actual delegated fd identity and lifetime required')
    if set(complete)!={'stage','api','sent','received','last_close_rebind'} or complete['last_close_rebind']!='NotSupported':raise CaptureError('actual final close and rebind refusal required')
    identity=app['credentials']
    if identity['uids']!=[1000]*4 or set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'} or any(int(v,16) for v in identity['capabilities'].values()) or app['exit']!=0 or app['stderr']:raise CaptureError('ordinary successful application with complete stderr required')
    return ready,complete


def execute(run, phase):
    n=len(run.data['connection_control']['phases'])-1
    c=Path('/bin/ws73-application-client-c');python=Path('/usr/share/sparklink/tools/ws73-application-client.py')
    tools=dict(c=file_record(c),python=file_record(python),library=file_record(Path('/usr/lib/libsparklink.so.0')))
    request=n.to_bytes(4,'little')+os.urandom(57);reply=n.to_bytes(4,'little')+os.urandom(57)
    if request==reply:raise CaptureError('independent random application reply required')
    row=dict(phase=n,owners=phase['typed_objects'],request=request.hex(),reply=reply.hex(),tools=tools,applications=[],start_wall_ns=time.time_ns(),status='RUNNING')
    run.data.setdefault('application_clients',[]).append(row);run.save()
    processes=[]
    with ExitStack() as files:
        try:
            for position in [1,0]:
                entry=row['owners'][position];owner=entry['owner'];api=('c' if position==0 else 'python') if n==0 else ('python' if position==0 else 'c')
                args=([str(c)] if api=='c' else ['/bin/python3',str(python)])+[str(owner['index']),str(owner['generation']),entry['object']['path'],str(position),request.hex(),reply.hex()]
                app=dict(api=api,position=position,args=args,start_wall_ns=time.time_ns())
                stdout=run.output/f'app-client-{n}-{api}.stdout';stderr=run.output/f'app-client-{n}-{api}.stderr'
                app['output_files']=[str(stdout),str(stderr)];row['applications'].append(app);run.save()
                proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=files.enter_context(stdout.open('xb')),stderr=files.enter_context(stderr.open('xb')))
                processes.append((proc,app));app['pid']=proc.pid;app['credentials']=credentials(proc.pid)
                status=Path(f'/proc/{proc.pid}/status').read_text()
                fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
                app['credentials']['capabilities']['CapInh']=fields['CapInh'].strip()
                app['credentials']['gids']=list(map(int,fields['Gid'].split()))
                app['credentials']['groups']=list(map(int,fields['Groups'].split()))
                app['process_status']=status;run.save()
                end=time.monotonic()+5
                while True:
                    lines=stdout.read_text().splitlines()
                    if len(lines)==1 and json.loads(lines[0]).get('stage')=='ready':break
                    if proc.poll() is not None or time.monotonic()>=end:raise CaptureError('actual application ready barrier failed')
                    time.sleep(.01)
            row['start_barrier_wall_ns']=time.time_ns();run.save()
            for proc,_ in processes:proc.stdin.write(b'start\n');proc.stdin.flush()
            deadline=time.monotonic()+12
            for proc,app in processes:
                proc.wait(timeout=max(.001,deadline-time.monotonic()))
                app.update(exit=proc.returncode,end_wall_ns=time.time_ns(),stdout=Path(app['output_files'][0]).read_text(),stderr=Path(app['output_files'][1]).read_text());run.save()
                receipts(app,row['owners'][app['position']])
            run.alive()
            for entry in row['owners']:run.check(entry['owner'])
            row.update(status='APPLICATION_CLIENT_EVIDENCE_PENDING',end_wall_ns=time.time_ns());run.save()
        except BaseException as exc:
            row.update(status='FAIL',error=str(exc));raise
        finally:
            for proc,app in processes:
                if proc.poll() is None:proc.kill()
                proc.wait()
                if proc.stdin:proc.stdin.close()
                if 'exit' not in app:app.update(exit=proc.returncode,stdout=Path(app['output_files'][0]).read_text(),stderr=Path(app['output_files'][1]).read_text(),end_wall_ns=time.time_ns())
            row.setdefault('end_wall_ns',time.time_ns());run.save()


def corroborate(run,capture):
    rows=run.get('application_clients')
    if not isinstance(rows,list) or len(rows)!=2:raise CaptureError('both connection roles required for application clients')
    sdus=reassemble_acb(capture);proofs=[];used=set()
    for n,row in enumerate(rows):
        if row['phase']!=n or row['status']!='APPLICATION_CLIENT_EVIDENCE_PENDING' or len(row['owners'])!=2 or len(row['applications'])!=2:raise CaptureError('complete actual application phase required')
        request,reply=bytes.fromhex(row['request']),bytes.fromhex(row['reply'])
        if len(request)!=61 or len(reply)!=61 or request==reply or request[:4]!=n.to_bytes(4,'little') or reply[:4]!=request[:4] or request in used or reply in used:raise CaptureError('fresh sequence and independent full random payloads required')
        used.update([request,reply]);values={}
        for app in row['applications']:
            position=app['position'];expected_api=('c' if position==0 else 'python') if n==0 else ('python' if position==0 else 'c')
            if position in values or app['api']!=expected_api:raise CaptureError('both languages must exchange application roles')
            ready,complete=receipts(app,row['owners'][position]);outgoing,incoming=(reply,request) if position else (request,reply)
            if complete['sent']!=outgoing.hex() or complete['received']!=incoming.hex():raise CaptureError('opposite application must actually validate and reply')
            values[position]=dict(api=app['api'],identity=ready)
        if set(values)!={0,1}:raise CaptureError('independent application ends required')
        legs=[]
        for sender,receiver,payload in [(0,1,request),(1,0,reply)]:
            frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
            leg={}
            for position,direction in [(sender,'out'),(receiver,'in')]:
                entry=row['owners'][position];owner,obj=entry['owner'],entry['object']
                if owner['generation']!=obj['generation'] or not obj['lifetime']:raise CaptureError('current canonical generation/lifetime required')
                matches=[s for s in sdus if (s['bus'],s['device'],s['handle'],s['direction'],s['data'])==(owner['bus'],owner['device'],obj['handle'],direction,frame.hex()) and row['start_wall_ns']<=s['wall_ns']<=row['end_wall_ns']]
                if len(matches)!=1:raise CaptureError('one exact application USB TX/opposite RX required')
                leg[direction]=matches[0]
            legs.append(leg)
        proofs.append(dict(phase=n,applications=values,legs=legs))
    return dict(status='C_PYTHON_BASIC_APPLICATION_USB_AND_PEER_SCOPED_PASS',round_trips=2,proofs=proofs,remaining=['Not deployed group-policy/revocation/fullAPI/recovery orperformance qualification','Other lifecycle combinations and original gates remainrequired'])


def valid_summary(proof):
    """Terminal shape check only; never substitutes for raw corroborate()."""
    try:
        if proof['status']!='C_PYTHON_BASIC_APPLICATION_USB_AND_PEER_SCOPED_PASS' or type(proof['round_trips']) is not int or proof['round_trips']!=2 or len(proof['proofs'])!=2:return False
        frames=set()
        for n,row in enumerate(proof['proofs']):
            if row['phase']!=n or len(row['legs'])!=2:return False
            apps={str(k):v for k,v in row['applications'].items()}
            if set(apps)!={'0','1'} or [apps[str(i)]['api'] for i in [0,1]]!=(['c','python'] if n==0 else ['python','c']):return False
            for app in apps.values():
                identity=app['identity']
                if identity['dup_alive'] is not True or identity['client_closed'] is not True or identity['generation']<=0 or identity['lifetime']<=0:return False
            for leg in row['legs']:
                a,b=leg['out'],leg['in'];raw=bytes.fromhex(a['data'])
                if raw[:5]!=b'\x1f\0\x3e\0\xf1' or len(raw)!=66 or a['data']!=b['data'] or (a['bus'],a['device'])==(b['bus'],b['device']) or a['data'] in frames:return False
                frames.add(a['data'])
        return True
    except (KeyError,TypeError,ValueError):return False
