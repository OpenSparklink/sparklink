# SPDX-License-Identifier: GPL-2.0-only
"""Disposable VM system-bus roles for the existing Owned SSAP API.

Only the guest supervisor changes uid. No native kernel/device operation or
wire result is implemented here. Role acceptance is separate from RF delivery.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time
from ws73_capture import CaptureError
from ws73_north_star import file_record,daemon_identity,stable
from ws73_ssap_owned import wait_text,observed_process

STATUS='ACTUAL_GUEST_SERVICE_ROLE_EVIDENCE_PENDING'
DENIED=['foreign-owned-read','global-value-read','foreign-owned-replace','foreign-owned-remove']
SERVICE_DENIED=DENIED+['RemoveLocalService','RegisterLocalService','StopControllerScan','interface-less-owned-read','OpenChannel']


def credentials(pid):
    fields=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    result={k:fields[k].split() for k in ['Uid','Gid','Groups','CapInh','CapEff','CapPrm','CapAmb']}
    if (result['Uid']!=['1005']*4 or result['Gid']!=['1005']*4 or result['Groups'] or
            any(int(result[k][0],16) for k in ['CapInh','CapEff','CapPrm','CapAmb'])):
        raise CaptureError('service-only process must have uid/gid1005, no extra groups or capabilities')
    return result


def record(application,owners,daemon_pid,folder=Path('/evidence/service-policy')):
    if (os.geteuid()!=0 or 'ws73.ssap_service_policy=1' not in Path('/proc/cmdline').read_text().split()
            or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU' or not Path('/scratch-root-uuid').is_file()):
        raise CaptureError('explicit disposable QEMU guest service-role gate required')
    folder.mkdir(exist_ok=False);path=folder/'run.json'
    result=dict(version=1,status='RUNNING',daemon=daemon_identity(daemon_pid),slctl=file_record('/bin/slctl'),probe=file_record('/bin/bus-policy-probe'),cases=[],start_wall_ns=time.time_ns(),scope='Actual guest system bus roles/local Owned API only;not wire delivery,full authorization or host installation')
    def save():path.write_text(json.dumps(result,indent=2)+'\n')
    save()
    def command(role,args):
        entry=dict(role=role,args=args,start_wall_ns=time.time_ns())
        p=application(*args,user=role,capture_output=True,timeout=12)
        entry.update(exit=p.returncode,stdout=p.stdout,stderr=p.stderr,end_wall_ns=time.time_ns());return entry
    try:
        for n,owner in enumerate(owners):
            secret=secrets.token_hex(32);service=secrets.token_hex(16);uuid=secrets.token_hex(16)
            args=[result['slctl']['path'],'--adapter',owner['path'],'ssap-serve',service,uuid,'5','36',secret,'allow']
            out=folder/f'{n}.stdout';err=folder/f'{n}.stderr';entry=dict(owner=owner,args=args,secret=secret,start_wall_ns=time.time_ns(),commands=[]);result['cases'].append(entry);save()
            process=None
            try:
                with ExitStack() as files:
                    # The CLI deliberately reopens stdin for an independent
                    # O_NONBLOCK description. A root-owned inherited pipe is
                    # not reopenable after setuid, despite its inherited fd.
                    readfd,writefd=os.pipe2(os.O_CLOEXEC)
                    files.callback(os.close,readfd)
                    writer=files.enter_context(os.fdopen(writefd,'wb',buffering=0))
                    os.fchown(readfd,1005,1005);os.fchmod(readfd,0o600)
                    pipe=os.fstat(readfd)
                    entry['stdin']={'uid':pipe.st_uid,'gid':pipe.st_gid,'mode':stat.S_IMODE(pipe.st_mode),'fifo':stat.S_ISFIFO(pipe.st_mode)}
                    process=files.enter_context(observed_process(args,entry,out,err,text=True,stdin=readfd,user=1005,group=1005,extra_groups=[]))
                    entry.update(pid=process.pid,credentials=credentials(process.pid));save()
                    matches,_=wait_text(process,out,r'^SsapOwnedService: start=(\d+) end=(\d+) property=(\d+); local registration only$',time.monotonic()+5)
                    if len(matches)!=1:raise CaptureError('one actual service-only owner registration required')
                    start,end,handle=map(int,matches[0]);entry.update(start=start,end=end,handle=handle);save()
                    for role,mode in [('service','service-only'),('channel','service-channel'),('observer','service-observer')]:
                        c=command(role,[result['probe']['path'],owner['path'],mode,str(start),str(handle)]);entry['commands'].append(c);save()
                        if c['exit']:raise CaptureError('actual service-role bus probe failed: '+c['stderr'])
                    writer.write(b'value\n')
                    observed,_=wait_text(process,out,r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$',time.monotonic()+2)
                    if observed!=[(str(handle),secret)]:raise CaptureError('foreign participants modified original owner value')
                    writer.write(b'quit\n');entry['exit']=process.wait(timeout=3)
                    if entry['exit']:raise CaptureError('service-only owner could not unregister')
                    c=command('ws73',[result['slctl']['path'],'--adapter',owner['path'],'ssap-list']);entry['after_quit']=c
                    rows=re.findall(r'^SsapLocalServices: (.+)$',c['stdout'],re.M)
                    if c['exit'] or len(rows)!=1 or any(v[0]==start for v in json.loads(rows[0])):raise CaptureError('service-only final unregister left metadata')
            finally:
                if process:
                    entry['exit']=process.returncode
                entry['end_wall_ns']=time.time_ns();save()
        result.update(status=STATUS,end_wall_ns=time.time_ns());save()
    except BaseException as error:result.update(status='FAIL',error=str(error),end_wall_ns=time.time_ns());save();raise


def corroborate(record,run):
    if record.get('version')!=1 or record.get('status')!=STATUS or len(record.get('cases',[]))!=2 or record['daemon']!=run['daemon_before'] or record['slctl']!=run['slctl']:
        raise CaptureError('complete real guest service roles and same daemon/binary required')
    if not record['start_wall_ns']<=record['end_wall_ns']<run['connection_control']['phases'][0]['start_wall_ns']:raise CaptureError('service-role gate must finish before real connection phase')
    proof=[];fresh=set()
    for entry in record['cases']:
        if entry.get('stdin')!={'uid':1005,'gid':1005,'mode':0o600,'fifo':True}:raise CaptureError('actual service-owned pollable input pipe required')
    for case,owner in zip(record['cases'],run['initial'],strict=True):
        if not stable(case['owner'],owner) or case['exit']!=0 or case['stderr']:raise CaptureError('same actual registration and successful original owner required')
        if not record['start_wall_ns']<=case['start_wall_ns']<=case['end_wall_ns']<=record['end_wall_ns']:raise CaptureError('original service-role case interval required')
        if not re.fullmatch(r'[a-f0-9]{64}',case['secret']) or case['secret'] in fresh:raise CaptureError('fresh actual owner value required')
        fresh.add(case['secret'])
        if re.findall(r'^SsapOwnedService: start=(\d+) end=(\d+) property=(\d+); local registration only$',case['stdout'],re.M)!=[(str(case['start']),str(case['end']),str(case['handle']))]:raise CaptureError('exact original owner registration required')
        if case['credentials']['Uid']!=['1005']*4 or case['credentials']['Gid']!=['1005']*4 or case['credentials']['Groups'] or any(int(case['credentials'][k][0],16) for k in ['CapInh','CapEff','CapPrm','CapAmb']):raise CaptureError('exact service-only process credentials required')
        if case['args'][:4]!=[record['slctl']['path'],'--adapter',owner['path'],'ssap-serve'] or case['args'][-4:]!=['5','36',case['secret'],'allow']:raise CaptureError('original foreground service-only command required')
        if f'SsapOwnedValue: handle={case["handle"]} value={case["secret"]}' not in case['stdout'].splitlines():raise CaptureError('original owner must read unchanged real value')
        if len(case['commands'])!=3:raise CaptureError('all three role commands required')
        previous=case['start_wall_ns'];denials=0
        for c,(role,mode,uid,gid) in zip(case['commands'],[('service','service-only',1005,1005),('channel','service-channel',1004,1004),('observer','service-observer',1001,1001)],strict=True):
            if c['role']!=role or c['args']!=[record['probe']['path'],owner['path'],mode,str(case['start']),str(case['handle'])] or c['exit'] or c['stderr'] or not previous<=c['start_wall_ns']<=c['end_wall_ns']<=case['end_wall_ns']:raise CaptureError('original ordered role command/result required')
            if re.findall(r'^AUTH_CREDENTIALS: .+$',c['stdout'],re.M)!=[f'AUTH_CREDENTIALS: uid={uid} gid={gid} caps=0']:raise CaptureError('actual bus client credentials required')
            if re.findall(r'^AUTH_SERVICE_KERNEL_ACCESS: (.+)$',c['stdout'],re.M)!=['denied']:raise CaptureError('actual existing kernel device access refusals required')
            expected=['own-service']+(['interface-less-own-read']+SERVICE_DENIED*2 if role=='service' else ['RegisterOwnedLocalService']+DENIED*2)
            actual=re.findall(r'^AUTH_DENIED: (.+)$',c['stdout'],re.M)
            if actual!=expected or re.findall(r'^AUTH_SERVICE_ROLE: (.+)$',c['stdout'],re.M)!=[mode]:raise CaptureError('all exact named/unique-owner bus denials required')
            positives=re.findall(r'^AUTH_SERVICE_OWNED: start=(\d+) property=(\d+) value=07 removed=true$',c['stdout'],re.M)
            if (role=='service' and (len(positives)!=1 or int(positives[0][1])<=int(positives[0][0]))) or (role!='service' and positives):raise CaptureError('only actual service role may register/read/remove its own value')
            replaced=re.findall(r'^AUTH_SERVICE_REPLACED: property=(\d+) values=08,07$',c['stdout'],re.M)
            expired_replace=re.findall(r'^AUTH_OWNED_REPLACE_DEADLINE: expired=true$',c['stdout'],re.M)
            if (role=='service' and (len(replaced)!=1 or replaced[0]!=positives[0][1] or len(expired_replace)!=1)) or (role!='service' and (replaced or expired_replace)):raise CaptureError('actual own replacement/readback and expired replacement refusal required')
            deadlines=re.findall(r'^AUTH_OWNED_DEADLINE: (.+)$',c['stdout'],re.M)
            if deadlines != (['register/read/remove expired=true'] if role=='service' else []):raise CaptureError('actual expired Owned register/read/remove refusals required')
            denials+=len(actual);previous=c['end_wall_ns']
        c=case['after_quit'];rows=re.findall(r'^SsapLocalServices: (.+)$',c['stdout'],re.M)
        if c['args']!=[record['slctl']['path'],'--adapter',owner['path'],'ssap-list'] or not previous<=c['start_wall_ns']<=c['end_wall_ns']<=case['end_wall_ns']:raise CaptureError('same controller actual final metadata query required')
        if c['role']!='ws73' or c['exit'] or c['stderr'] or len(rows)!=1 or any(v[0]==case['start'] for v in json.loads(rows[0])):raise CaptureError('actual owner final unregister required')
        proof.append(dict(owner=owner,denials=denials,expired_owned_requests=4,local_replacements=2,service_uid=1005,scope='Actual system-bus local ownership/role policy and expired request rejection;not application RF delivery or full multi-application lifecycle'))
    return proof
