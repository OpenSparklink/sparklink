# SPDX-License-Identifier: GPL-2.0-only
"""Finite disposable-VM role supervisor, not an installed privilege broker.

Reuse the existing SDK one-shot pair and real system-bus probe. Root opens only
fixed evidence paths and drops channels to UID/GID1004,SSAP publishers to1005
and remote value SDK calls to1004. Management discovery/UUID observations stay1000,each with no extra groups.
No protocol bytes, Native lease, Host, fake reply or arbitrary command service.
"""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import re
import signal
import stat
import subprocess
import time
import traceback
from ws73_capture import CaptureError
from ws73_north_star import daemon_identity, file_record

ROOT=Path('/evidence/application-role')
INPUT=Path('/evidence/application/passthrough-control')
SSAP_FIELDS=('ssap_language_required','ssap_language_clients','ssap_registration_kind',
    'ssap_owned_publishers_required','ssap_owned_publishers','ssap_value_required',
    'ssap_read_uuid_required','ssap_update_local_rejection_required','ssap_values',
    'ssap_local_registrations','ssap_discovery_required','ssap_discoveries','unsupported_incoming','role_ssap_commands')
SSAP_PREFLIGHT=['ReadSsapValue','WriteSsapValue','ReceiveSsapUpdate',
                'SubscribeSsapUpdates','ReadSsapUpdates','RenewSsapSubscription','CloseSsapSubscription']
DENIALS=['StopControllerScan','SubmitDisconnect','DiscoverSsap','GetCachedSsap','ReadSsapByUuid',
         'GetSsapInfo','SendOwnedSsapUpdate','GetOwnedSsapConfiguration',
         'AllocateReferenceSecurity','interface-less-GetInfo','unknown-method']


def validate_request(row, phase):
    if set(row)!={'phase','owners','request','reply','tools','applications','start_wall_ns','status'} or row['applications']!=[] or row['status']!='RUNNING':
        raise CaptureError('fixed empty pair request only; no arbitrary work')
    if type(phase)is not int or phase not in (0,1) or type(row.get('phase'))is not int or row['phase']!=phase:
        raise CaptureError('two ordered explicit application phases required')
    for key in ('request','reply'):
        raw=bytes.fromhex(row[key])
        if len(raw)!=61 or raw[:4]!=phase.to_bytes(4,'little'):
            raise CaptureError('original bounded random request/reply required')
    if row['request']==row['reply'] or len(row['owners'])!=2:
        raise CaptureError('independent reply and two owners required')
    for entry in row['owners']:
        owner,obj=entry['owner'],entry['object']
        if (type(owner['index'])is not int or not 0<=owner['index']<16 or
                type(owner['generation'])is not int or not 0<owner['generation']<2**64 or
                not re.fullmatch(r'/org/sparklink/slk'+str(owner['index'])+r'_g'+str(owner['generation'])+r'/peer_t[0-9a-f]{2}_[0-9a-f]{12}/link_[0-9a-f]{16}',obj['path'])):
            raise CaptureError('fixed canonical controller/lifetime input required')
    if len({e['owner']['index']for e in row['owners']})!=2:
        raise CaptureError('two distinct selected controllers required')


def read_json(path, uid, limit=131072):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or
                info.st_mode&0o022 or not 0<info.st_size<=limit):
            raise CaptureError(f'bounded original owner evidence file required: uid={info.st_uid} mode={info.st_mode & 0o777:o} bytes={info.st_size} expected_uid={uid} limit={limit}')
        with os.fdopen(os.dup(fd),'r')as stream:return json.load(stream)
    finally:os.close(fd)


def _verify_probe(row):
    probe=row['role_probe'];identity=probe['credentials']
    if (type(row.get('application_role_contract_version'))is not int or row['application_role_contract_version']!=2 or row.get('channel_role')!='sparklink-apps-only' or probe['exit'] or probe['stderr'] or
            identity['uids']!=[1004]*4 or identity['gids']!=[1004]*4 or identity['groups'] or
            set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'} or
            any(int(v,16)for v in identity['capabilities'].values())):
        raise CaptureError('actual application-only system-bus role required')
    path=probe['args'][1]
    if 'owners'in row and path!=row['owners'][0]['object']['path']:
        raise CaptureError('probe must target original live Connection')
    if probe['args']!=['/bin/bus-policy-probe',path,'application-channel']:
        raise CaptureError('exact disposable role probe required')
    lines=probe['stdout'].splitlines()
    expected=['AUTH_CREDENTIALS: uid=1004 gid=1004 caps=0','AUTH_CHANNEL_KERNEL_ACCESS: denied','AUTH_DENIED: own-service']
    for destination in ('named','unique'):
        expected+=['AUTH_CHANNEL_IDENTITY: '+destination]
        expected+=['AUTH_DENIED: '+name for name in DENIALS[:2]]
        expected+=['AUTH_SSAP_PREFLIGHT: '+name for name in SSAP_PREFLIGHT]
        expected+=['AUTH_DENIED: '+name for name in DENIALS[2:]]
    expected+=['AUTH_CHANNEL_ROLE: sparklink-apps-only']
    if lines!=expected:raise CaptureError('all original role observations and denials required')
    if not probe['start_wall_ns']<=probe['end_wall_ns']:
        raise CaptureError('original probe interval required')


def verify_probe(row):
    try:_verify_probe(row)
    except (KeyError,TypeError,ValueError,IndexError) as error:
        raise CaptureError('complete original application role probe required') from error


def request_pair(run,row):
    validate_request(row,row['phase'])
    request=run.output/f'app-channel-role-{row["phase"]}.request.json'
    temporary=request.with_suffix('.tmp')
    with temporary.open('x')as stream:json.dump(row,stream)
    temporary.chmod(0o600)
    os.link(temporary,request);temporary.unlink()
    observed=request.stat()
    row['role_request_file']=dict(uid=observed.st_uid,gid=observed.st_gid,mode=observed.st_mode & 0o777,bytes=observed.st_size);run.save()
    # The root helper cannot accept arbitrary programs or privileged operations.
    # This timeout only supervises the test; SDK children keep original5s.
    response=ROOT/f'phase-{row["phase"]}'/'run.json';end=time.monotonic()+35
    while not response.is_file():
        if time.monotonic()>=end:raise CaptureError('role supervisor original wait deadline')
        time.sleep(.01)
    result=read_json(response,0,limit=512*1024)
    for key in ('phase','owners','request','reply','tools','start_wall_ns'):
        if result[key]!=row[key]:raise CaptureError('role helper changed original operation identity')
    if result.get('pair_status')!='CHANNEL_PAIR_EVIDENCE_PENDING':
        raise CaptureError('actual application-only pair failed: '+str(result.get('error')))
    verify_probe(result)
    if result.get('ssap_gate_status')!='OWNED_SDK_VALUE_EVIDENCE_PENDING':raise CaptureError('actual root-supervised Owned SDK phase missing')
    for key in SSAP_FIELDS:
        if key not in result:raise CaptureError('missing root-supervised SDK field: '+key)
    for key in ('applications','start_barrier_wall_ns','role_probe','channel_role','application_role_contract_version','role_supervisor',*SSAP_FIELDS):
        row[key]=result[key]
    run.save()


def verify_supervisor_artifacts(control,evidence):
    """Check original root-supervised outputs, separate from USB corroboration."""
    evidence=Path(evidence);root=evidence/'application-role'
    finished=json.loads((root/'finished.json').read_text())
    if (finished.get('status')!='TWO_FINITE_ROLE_PAIRS_COMPLETED' or
            finished['daemon']!=control['daemon_before'] or control['daemon_before']!=control['daemon_after']):
        raise CaptureError('actual root role supervisor and original daemon required')
    for phase,row in enumerate(control['application_clients']):
        original=json.loads((root/f'phase-{phase}'/'run.json').read_text())
        verify_probe(original)
        for key in ('phase','owners','request','reply','tools','applications','role_probe','channel_role','application_role_contract_version','role_supervisor','start_barrier_wall_ns',*SSAP_FIELDS):
            if row[key]!=original[key]:raise CaptureError('root-supervised phase differs from control record')
        if original.get('pair_status')!='CHANNEL_PAIR_EVIDENCE_PENDING' or original['role_supervisor']!=finished['supervisor']:
            raise CaptureError('completed original role phase required')
        for app in [*original['applications'],original['role_probe'],*original['ssap_owned_publishers'],*original['ssap_language_clients']]:
            for filename in app['output_files']:
                path=evidence/Path(filename).relative_to('/evidence')
                if path.read_text()!=app['stdout'if path.suffix=='.stdout'else'stderr']:
                    raise CaptureError('original actual role process output differs')
    if len(control['application_clients'])!=2:raise CaptureError('two original role phases required')
    return dict(status='ACTUAL_GUEST_APPS_ONLY_PAIRS_AND_POLICY_OUTPUTS_CHECKED',contract_version=2,ssap_client_uid=1004,uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=4,daemon=finished['daemon'],supervisor=finished['supervisor'],scope='Finite actual system-bus role and SDK one-shot gate;not full deployment/revocation/deadline or per-application authorization')


def valid_supervision(proof):
    """Terminal shape only. Raw root files and process output are checked above."""
    try:
        return (proof['status']=='ACTUAL_GUEST_APPS_ONLY_PAIRS_AND_POLICY_OUTPUTS_CHECKED' and
                type(proof['contract_version'])is int and proof['contract_version']==2 and proof['ssap_client_uid']==1004 and
                proof['uid']==1004 and proof['gid']==1004 and proof['extra_groups']==[] and
                proof['role_probes']==2 and proof['application_processes']==4 and
                all(type(proof[k]['pid'])is int and proof[k]['pid']>0 and
                    type(proof[k]['start_ticks'])is int and proof[k]['start_ticks']>0
                    for k in ['daemon','supervisor']))
    except (KeyError,TypeError):return False


def require_vm(token='ws73.application_clients=1'):
    if (token not in ('ws73.application_clients=1', 'ws73.application_discovery=1', 'ws73.ssap_subscription=1') or
            os.geteuid()!=0 or token not in Path('/proc/cmdline').read_text().split()or
            Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU'or not Path('/scratch-root-uuid').is_file()):
        raise CaptureError('explicit disposable QEMU SDK role gate required')


def supervise(daemon_pid,*,mode='values'):
    """New subscription artifacts keep all hot files off the9p export."""
    from ws73_role_snapshot import TOKEN,local_root
    if mode=='subscription'and TOKEN in Path('/proc/cmdline').read_text().split():
        require_vm('ws73.ssap_subscription=1')
        def interrupted(*_):raise InterruptedError('role supervisor stopped')
        signal.signal(signal.SIGTERM,interrupted)
        with local_root()as local:
            finished=_supervise(daemon_pid,mode=mode,snapshot_root=local)
        # A failed export/unmount or abnormal exit must not leave a completed
        # root marker. The parent init also requires this process's actual exit.
        from ws73_ssap_subscription import ROOT as root
        (root/'finished.json').write_text(json.dumps(finished)+'\n')
        (root/'finished.json').chmod(0o644)
        return
    return _supervise(daemon_pid,mode=mode)


def _supervise(daemon_pid,*,mode='values',snapshot_root=None):
    if mode not in ('values','subscription'):raise CaptureError('fixed role supervision mode required')
    subscription=mode=='subscription'
    require_vm('ws73.ssap_subscription=1'if subscription else'ws73.application_clients=1')
    from ws73_ssap_subscription import ROOT as subscription_root,validate_request as subscription_request,execute_supervised
    root=subscription_root if subscription else ROOT
    from ws73_application_client import channel_pair,process_identity
    root.mkdir(exist_ok=False);root.chmod(0o755)
    supervisor=daemon_identity(os.getpid());daemon=daemon_identity(daemon_pid)
    def interrupted(*_):raise InterruptedError('role supervisor stopped')
    signal.signal(signal.SIGTERM,interrupted)
    end=time.monotonic()+(180 if subscription else 120)
    for phase in (0,1):
        request=INPUT/(f'subscription-role-{phase}.request.json'if subscription else f'app-channel-role-{phase}.request.json')
        while True:
            if daemon_identity(daemon_pid)!=daemon:raise CaptureError('original daemon changed')
            if request.is_file():
                try:row=read_json(request,1000);break
                except json.JSONDecodeError:pass # Writer has not finished original bounded JSON.
            if time.monotonic()>=end:raise CaptureError('finite role request deadline')
            time.sleep(.01)
        (subscription_request if subscription else validate_request)(row,phase)
        if subscription:
            from ws73_role_snapshot import requested as snapshot_requested
            if snapshot_requested(row)!=(snapshot_root is not None):raise CaptureError('snapshot boot/request mismatch')
        folder=(snapshot_root or root)/f'phase-{phase}';folder.mkdir(mode=0o755)
        row.update(channel_role='sparklink-apps-only',application_role_contract_version=2,role_supervisor=supervisor)
        def save():
            target=folder/'progress.json';temporary=folder/'progress.tmp'
            temporary.write_text(json.dumps(row,indent=2)+'\n');temporary.chmod(0o644);temporary.replace(target)
        context=SimpleNamespace(output=folder,save=save)
        try:
            from ws73_ssap_subscription import tool_records
            from ws73_ssap_subscription import inflight_required
            expected_tools=tool_records(snapshot=snapshot_root is not None,inflight=inflight_required(row))if subscription else{key:file_record(path)for key,path in [('c','/bin/ws73-application-client-c'),('python','/usr/share/sparklink/tools/ws73-application-client.py'),('library','/usr/lib/libsparklink.so.0')]}
            if row['tools']!=expected_tools:
                raise CaptureError('exact actual SDK artifacts required')
            probe=dict(args=['/bin/bus-policy-probe',row['owners'][0]['object']['path'],'application-channel'],start_wall_ns=time.time_ns())
            row['role_probe']=probe;save();out=folder/'probe.stdout';err=folder/'probe.stderr'
            with out.open('xb')as stdout,err.open('xb')as stderr:
                process=subprocess.Popen(probe['args'],user=1004,group=1004,extra_groups=[],stdout=stdout,stderr=stderr)
                try:
                    probe['pid']=process.pid;probe['credentials'],probe['process_status']=process_identity(process.pid,1004);save()
                    process.wait(timeout=10)
                finally:
                    if process.poll()is None:process.kill()
                    process.wait()
                    probe.update(exit=process.returncode,stdout=out.read_text(),stderr=err.read_text(),end_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
            verify_probe(row)
            if not subscription:channel_pair(context,row)
            from ws73_north_star import Run
            from ws73_application_client import ssap_phase
            context.args=SimpleNamespace(slctl=Path('/bin/slctl'));context.data={}
            row['role_ssap_commands']=context.data.setdefault('ssap_values',[])
            def observed(process,record):
                record['credentials'],record['process_status']=process_identity(process.pid,1000)
            context.command=lambda args,timeout,**kwargs:Run.command(context,args,timeout,
                child_credentials={'user':1000,'group':1000,'extra_groups':[]},on_started=observed,**kwargs)
            if subscription:execute_supervised(context,row)
            else:ssap_phase(context,row,application_uid=1004)
            row.update(ssap_gate_status='OWNED_SDK_VALUE_EVIDENCE_PENDING'if not subscription else'CONTINUOUS_SUBSCRIPTION_PENDING_USB',end_wall_ns=time.time_ns())
            if daemon_identity(daemon_pid)!=daemon:raise CaptureError('original daemon changed during pair')
        except BaseException as error:
            row.update(pair_status='FAIL',error=str(error),error_traceback=traceback.format_exc());raise
        finally:
            if snapshot_root:
                from ws73_role_snapshot import remap_outputs,publish
                remap_outputs(row,folder,root/f'phase-{phase}')
            save();(folder/'progress.json').replace(folder/'run.json')
            if snapshot_root:publish(folder,root/f'phase-{phase}',phase=phase,success='error'not in row)
    finished=root/'finished.json'
    value=dict(status='TWO_FINITE_SUBSCRIPTION_PHASES_COMPLETED'if subscription else'TWO_FINITE_ROLE_PAIRS_COMPLETED',daemon=daemon,supervisor=supervisor)
    if snapshot_root:
        value['snapshot_contract_version']=1
        return value
    finished.write_text(json.dumps(value)+'\n');finished.chmod(0o644)


if __name__=='__main__':
    import sys
    if len(sys.argv)not in (2,3)or len(sys.argv)==3 and sys.argv[2]!='subscription':raise SystemExit('usage: ws73_application_role.py ACTUAL_DAEMON_PID [subscription]')
    supervise(int(sys.argv[1]),mode='subscription'if len(sys.argv)==3 else'values')
