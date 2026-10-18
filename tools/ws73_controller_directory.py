#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VM-only ordinary observer of actual SDK directory events, not Native events.

Reuse the existing process/pipe recorder and original hotplug/socket gate.
Root owns the witness; no messages, Ready or physical completion are generated.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import time

from ws73_daemon_hold import Invocation
from ws73_north_star import daemon_identity, file_record

STATUS='ACTUAL_CONTROLLER_DIRECTORY_OBSERVER_CORROBORATED'
SNAPSHOT=rb'^ControllerDirectorySnapshot: cursor=(\d+) controllers=([^\n]*)\n'
PATH=r'/org/sparklink/slk(0|[1-9][0-9]*)_g([1-9][0-9]*)'

def staged_program(root, guest_files):
    # /bin/slctl is an absolute guest alias. Never resolve it in the host root.
    from ws73_security_cli import validate_binary
    root=Path(root).resolve(strict=True)
    target=os.readlink(root/'bin/slctl')
    candidate=root/target.lstrip('/')
    candidate.resolve(strict=True).relative_to(root)
    if candidate.is_symlink()or not candidate.is_file():raise ValueError('regular staged CLI required')
    binary=dict(path=target,sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
    validate_binary(binary,root,guest_files)
    return binary

def paths(text):
    values=[] if not text else text.split('|')
    if len(values)>16 or len(set(values))!=len(values):raise ValueError('bounded distinct directory snapshot required')
    for value in values:
        m=re.fullmatch(PATH,value)
        if not m or int(m[1])>65535 or int(m[2])>=2**64:raise ValueError('canonical directory identity required')
    return values

def parse(text):
    lines=text.splitlines()
    if len(lines)!=3 or not text.endswith('\n'):raise ValueError('one snapshot and exactly two complete changes required')
    initial=re.fullmatch(r'ControllerDirectorySnapshot: cursor=(\d+) controllers=(.*)',lines[0])
    if not initial:raise ValueError('original SDK snapshot required')
    before=int(initial[1]);initial_paths=paths(initial[2]);events=[]
    for n,line in enumerate(lines[1:],1):
        m=re.fullmatch(r'ControllerDirectoryEvent: sequence=(\d+) action=(withdrawn|published) path=('+PATH+r')',line)
        if not m or int(m[1])!=before+n or int(m[1])>=2**64:raise ValueError('contiguous original directory changes required')
        paths(m[3]);events.append(dict(sequence=int(m[1]),action=m[2],path=m[3]))
    if [v['action']for v in events]!=['withdrawn','published']:raise ValueError('withdrawal then new publication required')
    return dict(before=before,initial_paths=initial_paths,events=events)

def requested(args, *, passthrough=None):
    enabled=getattr(args,'controller_directory_events',False)
    if type(enabled)is not bool:raise ValueError('boolean directory observer request required')
    if enabled:
        real=getattr(args,'qmp_hotplug',False)if passthrough is None else passthrough
        if real is not True or getattr(args,'native_controller_return',None)not in ('initiator','acceptor'):
            raise ValueError('directory observer requires existing real user-controller return gate')
    return enabled

def corroborate(record, control, expected_program, expected_verifier):
    row=record['invocation'];proc=record['process'];observed=parse(row['stdout'])
    if record['source']['sha256']!=expected_verifier:raise ValueError('actual prepared guest verifier source required')
    if record['status']!='COMPLETE_NOT_QUALIFIED' or type(row['exit'])is not int or row['exit']!=0 or row['stderr']:
        raise ValueError('actual observer must exit normally without errors')
    if (record['program']['sha256']!=expected_program or proc['program_sha256']!=expected_program
            or type(row['pid'])is not int or row['pid']<=1 or proc['pid']!=row['pid']
            or proc['uids']!=[1001]*4 or proc['gids']!=[1001]*4 or proc['groups']!=[]
            or proc['caps']!={'CapEff':0,'CapPrm':0,'CapAmb':0} or proc['native_fds']):
        raise ValueError('actual default observer image/credentials and no Native fd required')
    if record['daemon_before']!=control['daemon_before'] or record['daemon_after']!=control['daemon_after']:
        raise ValueError('same real daemon required')
    a,b=control['initial'];new=control['replacement']
    if (set(observed['initial_paths'])!={a['path'],b['path']}
            or observed['events'][0]['path']!=a['path'] or observed['events'][1]['path']!=new['path']
            or new['index']!=a['index']or new['generation']<=a['generation']
            or row['args']!=['/bin/slctl','controller-events','3','30000']):
        raise ValueError('actual old/new generation, untouched peer and exact SDK command required')
    return dict(status=STATUS,program_sha256=expected_program,verifier_sha256=expected_verifier,observer_uid=1001,event_count=2,
                old_generation=a['generation'],new_generation=new['generation'],peer_generation=b['generation'],
                native_event_acceptance=False,ready_acceptance=False,automatic_recovery=False,**observed)

def valid_summary(value):
    try:
        if not (isinstance(value,dict)and value.get('status')==STATUS and value.get('observer_uid')==1001
                and type(value.get('event_count'))is int and value['event_count']==2
                and all(type(value.get(k))is int and value[k]>0 for k in ['old_generation','new_generation','peer_generation'])
                and value['new_generation']>value['old_generation']
                and value.get('native_event_acceptance')is False and value.get('ready_acceptance')is False
                and value.get('automatic_recovery')is False
                and all(isinstance(value.get(k),str)and re.fullmatch('[0-9a-f]{64}',value[k])is not None for k in ['program_sha256','verifier_sha256'])):
            return False
        text=f"ControllerDirectorySnapshot: cursor={value['before']} controllers={'|'.join(value['initial_paths'])}\n"
        text+=''.join(f"ControllerDirectoryEvent: sequence={e['sequence']} action={e['action']} path={e['path']}\n"for e in value['events'])
        parsed=parse(text);old,new=[e['path']for e in parsed['events']]
        a=re.fullmatch(PATH,old);b=re.fullmatch(PATH,new)
        return (len(parsed['initial_paths'])==2 and old in parsed['initial_paths']
                and a[1]==b[1]and int(a[2])==value['old_generation']and int(b[2])==value['new_generation']
                and any(p!=old and int(re.fullmatch(PATH,p)[2])==value['peer_generation']for p in parsed['initial_paths']))
    except (ValueError,KeyError,TypeError,IndexError):return False

def supervise(daemon):
    if (os.geteuid()!=0 or Path('/proc/cmdline').read_text().split().count('ws73.controller_directory_events=1')!=1
            or 'opensparklink-native-lab'not in os.uname().release):
        raise ValueError('explicit disposable Native VM root required; no process started')
    folder=Path('/evidence/controller-directory');folder.mkdir(mode=0o700)
    path=folder/'result.json';p=None
    record=dict(status='RUNNING_NOT_QUALIFIED',program=file_record('/bin/slctl'),
                source=file_record(__file__),start_wall_ns=time.time_ns(),daemon_before=daemon_identity(daemon))
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(record,indent=2)+'\n');tmp.replace(path)
    try:
        save();user=pwd.getpwnam('observer')
        if (user.pw_uid,user.pw_gid)!=(1001,1001):raise ValueError('fixed isolated observer role required')
        p=Invocation(['/bin/slctl','controller-events','3','30000'],'controller-directory',credentials=(1001,1001))
        record['invocation']=p.row;save()
        p.until(SNAPSHOT,timeout=5,limit=16384,label='actual directory snapshot')
        status={k:v.split()for line in Path(f'/proc/{p.process.pid}/status').read_text().splitlines()if ':'in line for k,v in [line.split(':',1)]}
        fds=[os.readlink(f)for f in Path(f'/proc/{p.process.pid}/fd').iterdir()]
        record['process']=dict(pid=p.process.pid,uids=list(map(int,status['Uid'])),gids=list(map(int,status['Gid'])),
            groups=list(map(int,status['Groups'])),caps={k:int(status[k][0],16)for k in ['CapEff','CapPrm','CapAmb']},
            native_fds=[f for f in fds if f in ['/dev/sparklink','/dev/usbmon1']],
            program_sha256=hashlib.sha256(Path(f'/proc/{p.process.pid}/exe').read_bytes()).hexdigest())
        save();(folder/'ready').write_text('ACTUAL_OBSERVER_SNAPSHOT\n')
        row=p.finish(timeout=95)
        if type(row['exit'])is not int or row['exit']!=0 or row['stderr']or len(row['stdout'])>16384:raise ValueError('actual directory observer failed')
        parse(row['stdout']);record['daemon_after']=daemon_identity(daemon);record['status']='COMPLETE_NOT_QUALIFIED';save()
    except BaseException as error:
        record.update(status='FAIL',error=repr(error))
        if p is not None and 'exit'not in p.row:
            try:p.finish(kill=p.process.poll()is None)
            except BaseException as cleanup:record['cleanup_error']=repr(cleanup)
        raise
    finally:
        record['end_wall_ns']=time.time_ns();save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--daemon-pid',type=int,required=True)
    supervise(parser.parse_args().daemon_pid)
