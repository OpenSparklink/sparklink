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
ALL_STATUS='ACTUAL_CONTROLLER_DIRECTORY_LANGUAGE_OBSERVERS_CORROBORATED'
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

def _corroborate(record, control, expected_program, expected_verifier, expected_args):
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
            or row['args']!=expected_args):
        raise ValueError('actual old/new generation, untouched peer and exact SDK command required')
    return dict(status=STATUS,program_sha256=expected_program,verifier_sha256=expected_verifier,observer_uid=1001,event_count=2,
                old_generation=a['generation'],new_generation=new['generation'],peer_generation=b['generation'],
                native_event_acceptance=False,ready_acceptance=False,automatic_recovery=False,**observed)

def corroborate(record, control, expected_program, expected_verifier):
    return _corroborate(record,control,expected_program,expected_verifier,['/bin/slctl','controller-events','3','30000'])

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

def _prepared_file(root,path):
    root=Path(root).resolve(strict=True)
    if not path.startswith('/')or '..'in Path(path).parts:raise ValueError('fixed absolute guest input required')
    actual=root/path.lstrip('/')
    if actual.is_symlink()or not actual.is_file():raise ValueError('regular staged consumer input required')
    actual.resolve(strict=True).relative_to(root)
    return dict(path=path,sha256=hashlib.sha256(actual.read_bytes()).hexdigest())

def _client_shape(value):
    try:
        if set(value)!={'version','c','python','script','library'}or type(value['version'])is not int or value['version']!=1:return False
        names=dict(c='/bin/controller-directory-client',script='/usr/share/sparklink/tools/ws73_controller_directory_client.py',library='/usr/lib/libsparklink.so.0')
        for k in ['c','python','script','library']:
            row=value[k]
            if set(row)!={'path','sha256'}or re.fullmatch('[0-9a-f]{64}',row['sha256'])is None:return False
            if k=='python':
                if re.fullmatch(r'/usr/bin/python3\.[0-9]+',row['path'])is None:return False
            elif row['path']!=names[k]:return False
        return True
    except (TypeError,KeyError):return False

def stage_clients(root,python,compilation):
    if re.fullmatch(r'python3\.[0-9]+',python)is None:raise ValueError('explicit prepared interpreter required')
    value=dict(version=1,c=_prepared_file(root,'/bin/controller-directory-client'),
        python=_prepared_file(root,'/usr/bin/'+python),
        script=_prepared_file(root,'/usr/share/sparklink/tools/ws73_controller_directory_client.py'),
        library=_prepared_file(root,'/usr/lib/libsparklink.so.0'))
    if not _client_shape(value)or value['script']['sha256']!=compilation['script']['sha256']:raise ValueError('prepared actual consumer source differs')
    (Path(root)/'expected-controller-directory-clients.json').write_text(json.dumps(value,indent=2)+'\n')
    return value

def staged_clients(root,files,value):
    if not _client_shape(value):raise ValueError('new language gate requires prepared --controller-directory-clients')
    for k in ['c','python','script','library']:
        row=value[k];actual=_prepared_file(root,row['path'])
        if actual!=row:raise ValueError('staged language input hash differs')
        path=str(Path(root).resolve()/row['path'].lstrip('/'))
        if dict(path=path,sha256=row['sha256'])not in files:raise ValueError('sealed guest input missing')
    p=Path(root)/'expected-controller-directory-clients.json'
    if p.is_symlink()or json.loads(p.read_text())!=value:raise ValueError('sealed expected language inputs differ')
    if dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())not in files:raise ValueError('expected consumer manifest not sealed')
    return value

def consumer_args(language,clients):
    library=clients['library']['path']
    if language=='c':return [clients['c']['path'],library]
    if language=='python':return ['/bin/python3',clients['script']['path'],library]
    raise ValueError('explicit actual consumer language required')

def corroborate_all(record,control,program,verifier,clients):
    if not _client_shape(clients)or set(record['languages'])!={'c','python'}:raise ValueError('both actual language observers required')
    rust=corroborate(record,control,program,verifier);proofs={}
    for language in ['c','python']:
        raw=record['languages'][language]
        proof=_corroborate(raw,control,clients[language]['sha256'],verifier,consumer_args(language,clients))
        if (raw['process']['native_library_loaded']is not False or raw['process']['loaded_library']!=clients['library']
                or not re.fullmatch('[0-9a-f]{64}',raw['process']['maps_sha256'])):raise ValueError('actual mapped application library required,no Native library')
        maps=raw['process']['maps']
        if not isinstance(maps,str)or len(maps.encode())>128*1024 or hashlib.sha256(maps.encode()).hexdigest()!=raw['process']['maps_sha256']:raise ValueError('raw process map evidence required')
        paths={v.split(maxsplit=5)[5]for v in maps.splitlines()if len(v.split(maxsplit=5))==6}
        if clients['library']['path']not in paths or any(Path(v).name.startswith('libslk_native.so')for v in paths):raise ValueError('actual expected SDK map required')
        script=clients['script']if language=='python'else None
        if raw.get('consumer_source')!=script:raise ValueError('actual Python consumer source required')
        if any(proof[k]!=rust[k]for k in ['before','initial_paths','events','old_generation','new_generation','peer_generation']):raise ValueError('language observer identity/cursor differs')
        proof.update(library_sha256=clients['library']['sha256'],script_sha256=script['sha256']if script else None,native_library_loaded=False)
        proofs[language]=proof
    result=dict(rust,status=ALL_STATUS,rust=rust,languages=proofs,prepared_clients=clients)
    if not valid_all_summary(result):raise ValueError('all-language observer proof malformed')
    return result

def valid_all_summary(value):
    try:
        if value.get('status')!=ALL_STATUS or not _client_shape(value['prepared_clients'])or set(value['languages'])!={'c','python'}:return False
        rust=value['rust'];clients=value['prepared_clients']
        if not valid_summary(rust)or any(value[k]!=v for k,v in rust.items()if k!='status'):return False
        for language,proof in value['languages'].items():
            if not valid_summary(proof)or proof['program_sha256']!=clients[language]['sha256']or proof['verifier_sha256']!=rust['verifier_sha256']:return False
            if proof['library_sha256']!=clients['library']['sha256']or proof['native_library_loaded']is not False:return False
            if proof['script_sha256']!=(clients['script']['sha256']if language=='python'else None):return False
            if any(proof[k]!=rust[k]for k in ['before','initial_paths','events','old_generation','new_generation','peer_generation']):return False
        return True
    except (ValueError,KeyError,TypeError):return False

def process_observation(process,library=None):
    status={k:v.split()for line in Path(f'/proc/{process.pid}/status').read_text().splitlines()if ':'in line for k,v in [line.split(':',1)]}
    fds=[]
    for fd in Path(f'/proc/{process.pid}/fd').iterdir():
        try:fds.append(os.readlink(fd))
        except FileNotFoundError:pass  # An ephemeral deadline/proc fd closed; permission errors still fail.
    result=dict(pid=process.pid,uids=list(map(int,status['Uid'])),gids=list(map(int,status['Gid'])),groups=list(map(int,status['Groups'])),
        caps={k:int(status[k][0],16)for k in ['CapEff','CapPrm','CapAmb']},native_fds=[f for f in fds if f in ['/dev/sparklink','/dev/usbmon1']],
        program_sha256=hashlib.sha256(Path(f'/proc/{process.pid}/exe').read_bytes()).hexdigest())
    if library:
        with Path(f'/proc/{process.pid}/maps').open('rb')as f:blob=f.read(128*1024+1)
        if len(blob)>128*1024:raise ValueError('bounded process map evidence exceeded')
        maps=blob.decode();paths={row.split(maxsplit=5)[5]for row in maps.splitlines()if len(row.split(maxsplit=5))==6}
        actual=str(Path(library['path']).resolve(strict=True))
        if actual!=library['path']or actual not in paths:raise ValueError('actual expected SDK library not mapped')
        result.update(maps=maps,maps_sha256=hashlib.sha256(maps.encode()).hexdigest(),loaded_library=file_record(actual),
            native_library_loaded=any(Path(p).name.startswith('libslk_native.so')for p in paths))
    return result

def supervise(daemon):
    if (os.geteuid()!=0 or Path('/proc/cmdline').read_text().split().count('ws73.controller_directory_events=1')!=1
            or 'opensparklink-native-lab'not in os.uname().release):
        raise ValueError('explicit disposable Native VM root required; no process started')
    clients=json.loads(Path('/expected-controller-directory-clients.json').read_text())
    if not _client_shape(clients):raise ValueError('explicit actual language inputs required')
    folder=Path('/evidence/controller-directory');folder.mkdir(mode=0o700)
    path=folder/'result.json';children=[]
    record=dict(status='RUNNING_NOT_QUALIFIED',program=file_record('/bin/slctl'),source=file_record(__file__),
        start_wall_ns=time.time_ns(),daemon_before=daemon_identity(daemon),languages={})
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(record,indent=2)+'\n');tmp.replace(path)
    try:
        save();user=pwd.getpwnam('observer')
        if (user.pw_uid,user.pw_gid)!=(1001,1001):raise ValueError('fixed isolated observer role required')
        for language in ['rust','c','python']:
            args=['/bin/slctl','controller-events','3','30000']if language=='rust'else consumer_args(language,clients)
            raw=record if language=='rust'else dict(status='RUNNING_NOT_QUALIFIED',program=file_record(args[0]),source=record['source'],daemon_before=record['daemon_before'])
            if language!='rust':
                raw['program']=dict(clients[language])
                raw['consumer_source']=clients['script']if language=='python'else None
                record['languages'][language]=raw
            p=Invocation(args,'controller-directory-'+language,credentials=(1001,1001));children.append((p,raw))
            raw['invocation']=p.row;save();p.until(SNAPSHOT,timeout=5,limit=16384,label='actual '+language+' directory snapshot')
            raw['process']=process_observation(p.process,None if language=='rust'else clients['library']);save()
        (folder/'ready').write_text('ACTUAL_ALL_OBSERVERS_SNAPSHOT\n')
        for p,raw in children:
            row=p.finish(timeout=95)
            if type(row['exit'])is not int or row['exit']!=0 or row['stderr']or len(row['stdout'])>16384:raise ValueError('actual directory language observer failed')
            parse(row['stdout']);raw['daemon_after']=daemon_identity(daemon)
            if raw is not record:raw['status']='COMPLETE_NOT_QUALIFIED'
            save()
        record['daemon_after']=daemon_identity(daemon);record['status']='COMPLETE_NOT_QUALIFIED';save()
    except BaseException as error:
        record.update(status='FAIL',error=repr(error))
        for p,raw in children:
            if 'exit'not in p.row:
                try:p.finish(kill=p.process.poll()is None)
                except BaseException as cleanup:raw['cleanup_error']=repr(cleanup)
        raise
    finally:
        record['end_wall_ns']=time.time_ns();save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--daemon-pid',type=int,required=True)
    supervise(parser.parse_args().daemon_pid)
