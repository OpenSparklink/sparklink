# SPDX-License-Identifier: GPL-2.0-only
"""One-shot public C/Python application clients; reuse existing VM/capture gates.

No synthetic controller, protocol Engine, load generator or performance claim.
"""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import subprocess
import time
from ws73_capture import CaptureError, reassemble_acb
from ws73_north_star import file_record


def application_environment(root=Path('/')):
    """Explicit private-image SDK location, also used by staged import checks."""
    root=Path(root).resolve()
    return dict(PYTHONPATH=os.pathsep.join(str(root/p) for p in ['usr/share/sparklink/python','usr/share/sparklink/tools']),LIBSPARKLINK_PATH=str(root/'usr/lib/libsparklink.so.0'))


def validate_consumer_sources(package):
    """Same compiled C/interpreted Python input binding for finite SDK gates."""
    import hashlib
    here=Path(__file__).resolve().parent
    for name in ('testing/application_client/client.c','testing/application_client/client.py'):
        path=here/name;records=package.get('application_client_tools',{}).get('sources',[])
        matches=[v for v in records if Path(v['path']).resolve()==path.resolve()]
        if len(matches)!=1 or matches[0]['sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('fresh exact application consumer source required: '+name)


def process_identity(pid, uid=1000):
    status=Path(f'/proc/{pid}/status').read_text()
    fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
    identity=dict(uids=list(map(int,fields['Uid'].split())),
                  capabilities={k:fields[k].strip() for k in ['CapEff','CapPrm','CapAmb','CapInh']})
    if uid not in (1000,1004,1005) or identity['uids']!=[uid]*4 or any(int(v,16) for v in identity['capabilities'].values()):
        raise CaptureError('exact cap-zero test role required')
    identity['gids']=list(map(int,fields['Gid'].split()))
    identity['groups']=list(map(int,fields['Groups'].split()))
    if uid in (1004,1005) and (identity['gids']!=[uid]*4 or identity['groups']):
        raise CaptureError('application-only child inherited authority groups')
    return identity,status


def ssap_receipt(app,entry,*,expected_size=32,expected_uid=1000):
    if app['environment']!=application_environment():
        raise CaptureError('original staged SSAP SDK environment required')
    if type(app['exit'])is not int or app['exit']!=0:
        raise CaptureError('actual SSAP consumer process failed; inspect retained exit and stderr')
    if type(app['stderr'])is not str or app['stderr']:
        raise CaptureError('actual SSAP consumer stderr rejected; inspect original receipt')
    identity=app['credentials']
    if expected_uid not in (1000,1004) or identity['uids']!=[expected_uid]*4 or set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'} or any(int(v,16) for v in identity['capabilities'].values()):
        raise CaptureError('ordinary cap-zero SSAP application required')
    if expected_uid==1004 and (identity.get('gids')!=[1004]*4 or identity.get('groups')!=[]):
        raise CaptureError('SSAP application-only child inherited authority groups')
    lines=app['stdout'].splitlines()
    if len(lines)!=2 or json.loads(lines[0])!=dict(stage='ssap_start_barrier',api=app['api'],client_closed=True):
        raise CaptureError('original retained-caller start barrier required')
    operation,path,handle,expected=app['ssap_operation'],app['ssap_path'],app['ssap_handle'],app['ssap_expected']
    if operation not in ('ssap-read','ssap-read-description','ssap-write') or path!=entry['object']['path'] or not 1<=handle<=65535 or type(expected_size)is not int or not 1<=expected_size<=2042 or len(bytes.fromhex(expected))!=expected_size:
        raise CaptureError('original exact SSAP caller identity and bounded value required')
    if lines[1]!=f'SsapPeerValue: operation={operation} path={path} handle={handle} value={expected}':
        raise CaptureError('actual SDK must validate the complete peer result')
    prefix=['/bin/ws73-application-client-c'] if app['api']=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    args=prefix+['ssap',str(entry['owner']['index']),str(entry['owner']['generation']),path,operation,str(handle),expected]
    if operation=='ssap-write':args.append(expected)
    if app['api']not in ('c','python') or app['args']!=args:
        raise CaptureError('exact actual SSAP executable and arguments required')


def ssap_command(run,row,entry,args,expected,*,api=None,expected_size=32,application_uid=1000):
    return ssap_commands(run,row,[(entry,args,expected)],api=api,expected_size=expected_size,application_uid=application_uid)[0]


def ssap_commands(run,row,calls,*,api=None,expected_size=32,application_uid=1000,batch=None):
    """One finite supervisor for the existing actual SDK children,not a wire loop.

    All children reach their real retained-caller barrier before any release.
    Paired waits share one original deadline; neither child renews the other.
    """
    if type(calls)is not list or len(calls)not in (1,2):raise CaptureError('one or two bounded SDK calls required')
    paired=len(calls)==2
    if paired:
        from ws73_application_role import require_vm
        require_vm('ws73.socket_benchmark_apps=1')
        if (application_uid!=1004 or api is not None or type(batch)is not tuple or len(batch)!=2
            or type(batch[0])is not int or batch[0]not in range(4)or batch[1]not in ('read_before','write','read_after')
            or {row['owners'].index(c[0])for c in calls}!={0,1}
            or len({(c[0]['owner']['index'],c[0]['owner']['generation'])for c in calls})!=2
            or any(c[1][0]!=('ssap-write'if batch[1]=='write'else'ssap-read')for c in calls)):
            raise CaptureError('explicit ordinary opposite-controller SSAP step required')
    elif batch is not None:raise CaptureError('single SDK call cannot claim duplex')
    plans=[ssap_call(run,row,entry,args,expected,api=api,expected_size=expected_size,application_uid=application_uid)for entry,args,expected in calls]
    items=row.setdefault('ssap_language_clients',[]);number=len(items)
    group=None
    if paired:
        group=dict(version=1,index=len(row.setdefault('ssap_sdk_batches',[])),sequence=batch[0],step=batch[1],
                   applications=list(range(number,number+2)),start_wall_ns=time.time_ns(),status='RUNNING',supervisor_seconds=7)
        row['ssap_sdk_batches'].append(group)
    processes=[];result=[]
    with ExitStack()as files:
        try:
            ready_deadline=None
            for entry,command,language,environment,args,expected in plans:
                ordinal=len(items);stdout=run.output/f'app-ssap-{row["phase"]}-{ordinal}-{language}.stdout';stderr=run.output/f'app-ssap-{row["phase"]}-{ordinal}-{language}.stderr'
                app=dict(api=language,args=command,position=row['owners'].index(entry),environment=environment,ssap_operation=args[0],ssap_path=args[1],ssap_handle=int(args[2]),ssap_expected=expected.hex(),start_wall_ns=time.time_ns(),output_files=[str(stdout),str(stderr)])
                if group is not None:app['ssap_batch_index']=group['index']
                items.append(app);result.append(app);run.data.setdefault('ssap_values',[]).append(app);run.save()
                proc=subprocess.Popen(command,env=dict(os.environ,**environment),stdin=subprocess.PIPE,
                    stdout=files.enter_context(stdout.open('xb')),stderr=files.enter_context(stderr.open('xb')),
                    **({'user':application_uid,'group':application_uid,'extra_groups':[]}if os.geteuid()==0 else{}))
                processes.append((proc,app,stdout,stderr,entry));app['pid']=proc.pid;app['credentials'],app['process_status']=process_identity(proc.pid,application_uid);run.save()
                if ready_deadline is None:ready_deadline=time.monotonic()+5
            for proc,app,stdout,stderr,entry in processes:
                while True:
                    lines=stdout.read_text().splitlines()
                    if len(lines)==1 and json.loads(lines[0])==dict(stage='ssap_start_barrier',api=app['api'],client_closed=True):break
                    if proc.poll()is not None or time.monotonic()>=ready_deadline:raise CaptureError('actual SDK SSAP original start barrier failed')
                    time.sleep(.01)
                app['start_barrier_wall_ns']=time.time_ns();run.save()
            deadline=None
            for proc,app,stdout,stderr,entry in processes:
                before=time.monotonic_ns()
                if deadline is None:deadline=before+7_000_000_000
                app['ssap_release_before_wall_ns']=time.time_ns();app['ssap_release_monotonic_ns']=before
                proc.stdin.write(b'start\n');proc.stdin.flush();app['ssap_released_wall_ns']=time.time_ns()
            if group is not None:group.update(released_wall_ns=time.time_ns(),wait_deadline_monotonic_ns=deadline)
            run.save()
            for proc,app,stdout,stderr,entry in processes:
                proc.wait(timeout=max(.001,(deadline-time.monotonic_ns())/1e9))
                app.update(exit=proc.returncode,end_wall_ns=time.time_ns(),stdout=stdout.read_text(),stderr=stderr.read_text());run.save()
                ssap_receipt(app,entry,expected_size=expected_size,expected_uid=application_uid)
            if group is not None:group['status']='SDK_CALLS_COMPLETE'
        finally:
            for proc,app,stdout,stderr,entry in processes:
                if proc.poll()is None:proc.kill()
                proc.wait();proc.stdin.close()
                app.setdefault('exit',proc.returncode);app.setdefault('end_wall_ns',time.time_ns());app['stdout']=stdout.read_text();app['stderr']=stderr.read_text()
            if group is not None:
                if group['status']!='SDK_CALLS_COMPLETE':group['status']='FAIL'
                group.update(end_wall_ns=time.time_ns(),completed_monotonic_ns=time.monotonic_ns())
            run.save()
    return result


def ssap_call(run,row,entry,args,expected,*,api,expected_size,application_uid):
    """Same fixed executable and full-value contract for single and paired calls."""
    if type(expected_size)is not int or not 1<=expected_size<=2042 or not isinstance(expected,bytes) or len(expected)!=expected_size:raise CaptureError('original bounded expected SSAP value required')
    if application_uid not in (1000,1004):raise CaptureError('explicit SSAP test role required')
    if application_uid==1004 and os.geteuid()!=0:raise CaptureError('apps-only SSAP requires existing VM root role supervisor')
    if (type(args)is not list or not args or args[0]not in ('ssap-read','ssap-read-description','ssap-write')
        or len(args)!=(4 if args[0]=='ssap-write'else 3)or args[1]!=entry['object']['path']
        or not 1<=int(args[2])<=65535 or args[0]=='ssap-write'and args[3]!=expected.hex()):
        raise CaptureError('exact same-lifetime SDK value call required')
    position=row['owners'].index(entry)
    if api is None:api='c' if position==row['phase'] else 'python'
    if api not in ('c','python'):raise CaptureError('explicit SDK consumer required')
    command=(['/bin/ws73-application-client-c'] if api=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py'])+['ssap',str(entry['owner']['index']),str(entry['owner']['generation']),args[1],args[0],args[2],expected.hex()]
    if args[0]=='ssap-write':command.append(args[3])
    return entry,command,api,application_environment(),args,expected


def receipts(app, entry):
    if app.get('environment')!=application_environment():raise CaptureError('exact staged SDK environment required')
    try:rows=[json.loads(line) for line in app['stdout'].splitlines()]
    except (ValueError,KeyError) as exc:raise CaptureError('complete original application JSON required') from exc
    if len(rows)!=2 or [r.get('stage') for r in rows]!=['ready','complete'] or any(r.get('api')!=app['api'] for r in rows):raise CaptureError('one actual ready/complete pair per API required')
    ready,complete=rows;owner,obj=entry['owner'],entry['object']
    if set(ready)!={'stage','api','index','generation','lifetime','handle','dup_alive','client_closed'} or (ready['index'],ready['generation'],ready['lifetime'],ready['handle'])!=(owner['index'],owner['generation'],obj['lifetime'],obj['handle']) or ready['dup_alive'] is not True or ready['client_closed'] is not True:raise CaptureError('actual delegated fd identity and lifetime required')
    if set(complete)!={'stage','api','sent','received','last_close_rebind'} or complete['last_close_rebind']!='NotSupported':raise CaptureError('actual final close and rebind refusal required')
    identity=app['credentials']
    if identity['uids']!=[1004]*4 or identity['gids']!=[1004]*4 or identity['groups'] or set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'} or any(int(v,16) for v in identity['capabilities'].values()) or app['exit']!=0 or app['stderr']:raise CaptureError('ordinary successful application with complete stderr required')
    return ready,complete


def channel_pair(run, row):
    """Same one-shot orchestration, executed only by the disposable root supervisor."""
    from ws73_application_role import require_vm
    require_vm()
    n=row['phase'];request=bytes.fromhex(row['request']);reply=bytes.fromhex(row['reply'])
    c=Path('/bin/ws73-application-client-c');python=Path('/usr/share/sparklink/tools/ws73-application-client.py')
    processes=[]
    with ExitStack() as files:
        try:
            for position in [1,0]:
                entry=row['owners'][position];owner=entry['owner'];api=('c' if position==0 else 'python') if n==0 else ('python' if position==0 else 'c')
                args=([str(c)] if api=='c' else ['/bin/python3',str(python)])+[str(owner['index']),str(owner['generation']),entry['object']['path'],str(position),request.hex(),reply.hex()]
                environment=application_environment()
                app=dict(api=api,position=position,args=args,environment=environment,start_wall_ns=time.time_ns())
                stdout=run.output/f'app-client-{n}-{api}.stdout';stderr=run.output/f'app-client-{n}-{api}.stderr'
                app['output_files']=[str(stdout),str(stderr)];row['applications'].append(app);run.save()
                proc=subprocess.Popen(args,user=1004,group=1004,extra_groups=[],env=dict(os.environ,**environment),stdin=subprocess.PIPE,stdout=files.enter_context(stdout.open('xb')),stderr=files.enter_context(stderr.open('xb')))
                processes.append((proc,app));app['pid']=proc.pid
                app['credentials'],app['process_status']=process_identity(proc.pid,1004);run.save()
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
            row.update(pair_status='CHANNEL_PAIR_EVIDENCE_PENDING');run.save()
        except BaseException as exc:
            row.update(status='FAIL',error=str(exc));raise
        finally:
            for proc,app in processes:
                if proc.poll() is None:proc.kill()
                proc.wait()
                if proc.stdin:proc.stdin.close()
                if 'exit' not in app:app.update(exit=proc.returncode,stdout=Path(app['output_files'][0]).read_text(),stderr=Path(app['output_files'][1]).read_text(),end_wall_ns=time.time_ns())
            row.setdefault('end_wall_ns',time.time_ns());run.save()


def owned_arguments(api,owner,service,uuid,initial,policy,*,read_only=False,update_connection=None):
    if api not in ('c','python') or policy not in ('none','allow','deny','ask') or type(read_only)is not bool or (read_only and policy!='none'):
        raise CaptureError('explicit SDK language and application policy required')
    prefix=['/bin/ws73-application-client-c'] if api=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    if update_connection is not None:
        if read_only or policy=='none' or update_connection!=owner['object']['path']:
            raise CaptureError('explicit original owned-update connection and policy required')
        return prefix+['owned-updates',str(owner['owner']['index']),str(owner['owner']['generation']),service,uuid,initial,policy,update_connection]
    return prefix+['owned-readonly'if read_only else'owned',str(owner['owner']['index']),str(owner['owner']['generation']),service,uuid,initial]+([]if policy=='none'else[policy])


@contextmanager
def owned_services(run,row,live,*,vm_token='ws73.application_clients=1'):
    """Real SDK publishers,not manager staging. Existing value loop is reused."""
    from ws73_application_role import require_vm
    from ws73_ssap_owned import wait_text
    import secrets,sys
    if vm_token not in ('ws73.application_clients=1','ws73.socket_benchmark_apps=1'):raise CaptureError('fixed Owned VM role required')
    require_vm(vm_token);row['ssap_registration_kind']='owned-sdk-requests-v1';row['ssap_owned_publishers_required']=True
    local=[];processes=[]
    with ExitStack() as files:
        try:
            for position,owner in enumerate(row['owners']):
                api='c' if position==row['phase'] else 'python';value=secrets.token_bytes(32);service=secrets.token_hex(16);uuid=secrets.token_hex(16)
                args=owned_arguments(api,owner,service,uuid,value.hex(),'allow')
                prefix=run.output/f"owned-sdk-{row['phase']}-{api}";out=Path(str(prefix)+'.stdout');err=Path(str(prefix)+'.stderr')
                app=dict(api=api,position=position,args=args,environment=application_environment(),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
                row.setdefault('ssap_owned_publishers',[]).append(app);run.save()
                process=subprocess.Popen(args,env=dict(os.environ,**app['environment']),user=1005,group=1005,extra_groups=[],stdin=subprocess.PIPE,stdout=files.enter_context(out.open('x')),stderr=files.enter_context(err.open('x')),text=True)
                processes.append((process,app));app['pid']=process.pid;app['credentials'],app['process_status']=process_identity(process.pid,1005)
                matches,text=wait_text(process,out,r'^SsapOwnedService: start=(\d+) end=(\d+) property=(\d+); local registration only$',time.monotonic()+5)
                if len(matches)!=1 or text.splitlines()[0]!=f'SdkOwnedAPI: api={api} client_closed=true':raise CaptureError('actual original SDK owner and Client-close barrier required')
                start,end,handle=map(int,matches[0]);app.update(start=start,end=end,handle=handle);live[owner['owner']['path']]=(process,app)
                if vm_token=='ws73.socket_benchmark_apps=1':
                    from ws73_ssap_update_delivery import command_receipt
                    row['publisher_lifecycle_observation_version']=1
                    app['lifecycle_observation']=command_receipt(process,app,'lifecycle','SdkOwnedLifecycle')
                    publisher_lifecycle_trace(app,owner,terminal=False,stdout=out.read_text())
                local.append(dict(owner=owner,start=start,handle=handle,value=value,registration=app,service_uuid=service,property_uuid=uuid));run.save()
            yield local
        finally:
            active_error=sys.exc_info()[0] is not None;errors=[]
            for process,app in processes:
                try:
                    if process.poll() is None:process.stdin.write('quit\n');process.stdin.flush()
                    process.wait(timeout=5)
                except (OSError,subprocess.TimeoutExpired) as e:errors.append(str(e))
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=2)
                    if process.stdin:process.stdin.close()
                    app.update(exit=process.returncode,end_wall_ns=time.time_ns(),stdout=Path(app['output_files'][0]).read_text(),stderr=Path(app['output_files'][1]).read_text())
                    if app['exit'] or app['stderr'] or app['stdout'].splitlines().count(f"SdkOwnedRemoved: api={app['api']} start={app.get('start')}")!=1:errors.append('actual SDK owner unregister acknowledgement missing')
            row['ssap_local_registrations']=[dict(owner=p['owner'],start=p['start'],handle=p['handle'],registration=p['registration'],service_uuid=p['service_uuid'],property_uuid=p['property_uuid']) for p in local]
            if errors:row['owned_publisher_cleanup_errors']=errors
            run.save();live.clear()
            if errors and not active_error:raise CaptureError(';'.join(errors))


def owned_value_snapshot(run,live,owner,args,expected):
    from ws73_ssap_owned import value_snapshot
    process,app=live[owner['owner']['path']]
    if args!=['ssap-local-read',str(app['handle'])] or expected is None:raise CaptureError('original local SDK observation target required')
    observation=value_snapshot(process,app,expected.hex());observation.update(api=app['api'],publisher_pid=app['pid']);run.save();return observation


def ssap_phase(run,row,*,application_uid=1000,vm_token='ws73.application_clients=1',duplex=False):
    from ws73_ssap_value import execute as ssap_execute
    if type(duplex)is not bool or duplex and(vm_token!='ws73.socket_benchmark_apps=1'or application_uid!=1004):raise CaptureError('explicit ordinary benchmark duplex role required')
    row['ssap_language_required']=True
    if duplex:row['ssap_sdk_duplex_required']=True
    run.save()
    live={}
    ssap_execute(run,row,value_command=lambda entry,args,expected:ssap_command(run,row,entry,args,expected,application_uid=application_uid),
        services=lambda _run,_row,_command:owned_services(_run,_row,live,vm_token=vm_token),
        local_value_command=lambda owner,args,expected:owned_value_snapshot(run,live,owner,args,expected),
        value_commands=(lambda calls,sequence,step:ssap_commands(run,row,calls,application_uid=application_uid,batch=(sequence,step)))if duplex else None)

def execute(run, phase):
    n=len(run.data['connection_control']['phases'])-1
    c=Path('/bin/ws73-application-client-c');python=Path('/usr/share/sparklink/tools/ws73-application-client.py')
    tools=dict(c=file_record(c),python=file_record(python),library=file_record(Path('/usr/lib/libsparklink.so.0')))
    request=n.to_bytes(4,'little')+os.urandom(57);reply=n.to_bytes(4,'little')+os.urandom(57)
    if request==reply:raise CaptureError('independent random application reply required')
    row=dict(phase=n,owners=phase['typed_objects'],request=request.hex(),reply=reply.hex(),tools=tools,applications=[],start_wall_ns=time.time_ns(),status='RUNNING')
    run.data.setdefault('application_clients',[]).append(row);run.save()
    from ws73_application_role import request_pair
    try:
        request_pair(run,row)
        run.alive()
        for entry in row['owners']:run.check(entry['owner'])
        run.alive()
        for entry in row['owners']:run.check(entry['owner'])
        row.update(status='APPLICATION_CLIENT_EVIDENCE_PENDING',end_wall_ns=time.time_ns());run.save()
    except BaseException as exc:
        row.update(status='FAIL',error=str(exc),end_wall_ns=time.time_ns());run.save();raise


AUTHORIZATION_CONTEXT_FIELDS={'api','index','generation','token','request_id','lifetime','handle',
    'epoch','level','deadline_ns','property','data_type','write','value','local_tcid','remote_tcid','pi'}


def authorization_context(context,api,*,level=0,data_type=0):
    """Basic-CUTC local observation only,not a Native grant/security fact."""
    if (level,data_type) not in [(0,0),(2,2)]:raise CaptureError('unsupported explicit authorization evidence scope')
    if (not isinstance(context,dict) or set(context)!=AUTHORIZATION_CONTEXT_FIELDS or context['api']!=api
            or type(context['write']) is not bool or not isinstance(context['value'],str)
            or any(type(context[k]) is not int or not 0<=context[k]<2**64
                   for k in AUTHORIZATION_CONTEXT_FIELDS-{'api','write','value'})
            or not all(context[k] for k in ['generation','token','request_id','lifetime','epoch','deadline_ns','property'])
            or context['index']>65535 or context['handle']>65535 or context['property']>65535
            or (context['local_tcid'],context['remote_tcid'],context['pi'],context['level'],context['data_type'])!=(10,10,0,level,data_type)):
        raise CaptureError('complete original basic SDK authorization context required')
    try:value=bytes.fromhex(context['value'])
    except ValueError as error:raise CaptureError('exact proposed authorization bytes required') from error
    if value.hex()!=context['value'] or len(value)>2042 or not context['write'] and value:
        raise CaptureError('bounded canonical proposed bytes,empty for reads,required')
    if data_type==2 and (not context['write'] or len(value)!=2 or value[1]!=0 or value[0]&~3):
        raise CaptureError('exact authenticated two-byte client configuration required')
    return context


def authorization_decisions(app):
    """Original frontend output;not Native authorization or peer delivery."""
    try:
        rows=[json.loads(line.removeprefix('SdkAuthorizationDecision: '))
              for line in app['stdout'].splitlines() if line.startswith('SdkAuthorizationDecision: ')]
    except (ValueError,TypeError) as error:raise CaptureError('original approval JSON required') from error
    fields={'api','index','generation','token','request_id','lifetime','handle','epoch','level',
            'deadline_ns','property','data_type','write','value','local_tcid','remote_tcid','pi','allow',
            'decision_ns','decision_wall_ns'}
    for d in rows:
        if isinstance(d,dict):authorization_context({k:v for k,v in d.items() if k in AUTHORIZATION_CONTEXT_FIELDS},app['api'])
        if (not isinstance(d,dict) or set(d)!=fields or d['api']!=app['api']
                or type(d['write']) is not bool or d['allow'] is not True
                or any(type(d[k]) is not int or not 0<=d[k]<2**64
                       for k in fields-{'api','write','value','allow'})
                or not all(d[k] for k in ['generation','token','request_id','lifetime','epoch','deadline_ns','property','decision_ns','decision_wall_ns'])
                or not 0<d['deadline_ns']-d['decision_ns']<=5_000_000_000
                or (d['local_tcid'],d['remote_tcid'],d['pi'],d['level'])!=(10,10,0,0)
                or not isinstance(d['value'],str)):
            raise CaptureError('complete original basic approval context and deadline required')
    if (len(rows)!=20 or any(a['token']>=b['token'] or a['request_id']>=b['request_id']
                             for a,b in zip(rows,rows[1:]))):
        raise CaptureError('twenty distinct ordered decisions per actual publisher required')
    return rows


def publisher_lifecycle_trace(app,owner,*,terminal=True,stdout=None):
    """Original test-client timer/call/cleanup samples;not serverTTL or commit.

    Partial failed runs can retain this structural diagnostic. The existing
    full workload still requires actual successful calls,wire and finalization.
    """
    from ws73_link_measurement import unique_object
    text=app.get('stdout','')if stdout is None else stdout
    lines=[v[len('SdkOwnedLifecycle: '):]for v in text.splitlines()if v.startswith('SdkOwnedLifecycle: ')]
    if 'lifecycle_observation'not in app:
        if lines:raise CaptureError('unrequested publisher lifecycle samples')
        return None
    if not 1<=len(lines)<=35 or any(len(line.encode())>2048 for line in lines):raise CaptureError('bounded original publisher lifecycle samples required')
    rows=[json.loads(line,object_pairs_hook=unique_object)for line in lines]
    fields={'version','api','stage','pid','index','generation','start','property','created_ns','deadline_ns',
            'sampled_ns','wall_ns','error','token','request_id','call_started_ns','call_returned_ns'}
    identity=owner['owner']
    previous=0;budget=None
    for row in rows:
        if (type(row)is not dict or set(row)!=fields or any(type(row[k])is not int for k in fields-{'api','stage'})
            or row['version']!=1 or row['api']!=app['api']
            or not 0<row['pid']<2**31 or not 0<=row['index']<=65535 or not row['generation']
            or not 0<row['start']<row['property']<=65535
            or (row['pid'],row['index'],row['generation'],row['start'],row['property'])!=(app['pid'],identity['index'],identity['generation'],app['start'],app['handle'])
            or not -4095<=row['error']<=0 or any(not 0<=row[k]<2**64 for k in fields-{'api','stage','error'})
            or not 0<row['created_ns']<row['deadline_ns'] or row['deadline_ns']-row['created_ns']!=30_000_000_000
            or not row['created_ns']<=row['sampled_ns'] or not row['wall_ns'] or row['sampled_ns']<previous):
            raise CaptureError('exact original publisher identity,30second loop budget and clock samples required')
        current=(row['created_ns'],row['deadline_ns'])
        if budget is not None and current!=budget:raise CaptureError('publisher budget renewed or replaced')
        budget=current;previous=row['sampled_ns']
        if row['stage']=='approval_return':
            if (not row['token'] or not row['request_id']
                or not row['created_ns']<=row['call_started_ns']<=row['call_returned_ns']<=row['sampled_ns']):
                raise CaptureError('actual approval API return samples required')
        elif row['stage']not in ('observed','cleanup_begin','cleanup_end') or any(row[k]for k in ('token','request_id','call_started_ns','call_returned_ns')):
            raise CaptureError('bounded original lifecycle stage required')
    observation=app['lifecycle_observation'];first=rows[0]
    if (first['stage']!='observed' or first['error'] or first!=observation['receipt']
        or not observation['start_monotonic_ns']<=first['sampled_ns']<=observation['end_monotonic_ns']
        or first['sampled_ns']>=first['deadline_ns']):raise CaptureError('original live observation command/receipt required')
    if terminal:
        if len(rows)<3 or [r['stage']for r in rows[-2:]]!=['cleanup_begin','cleanup_end'] or any(r['stage']!='approval_return'for r in rows[1:-2]):
            raise CaptureError('complete original frontend cleanup begin/end required;not remote drain proof')
    elif len(rows)!=1:raise CaptureError('one initial observation before workload required')
    return rows


def verify_owned_publishers(row):
    """Terminal source/role/stream contract;not an independent USB decoder."""
    import re
    if row.get('ssap_registration_kind')!='owned-sdk-requests-v1' or row.get('ssap_owned_publishers_required')is not True or row.get('owned_publisher_cleanup_errors'):raise CaptureError('current SDK gate requires actual approving Owned publishers and cleanup')
    publishers=row.get('ssap_owned_publishers',[]);registrations=row.get('ssap_local_registrations',[])
    if len(publishers)!=2 or len(registrations)!=2:raise CaptureError('two opposite actual Owned SDK publishers required')
    for position,(app,registered) in enumerate(zip(publishers,registrations,strict=True)):
        owner=row['owners'][position];api='c' if position==row['phase'] else 'python';credentials=app['credentials']
        if (registered['owner']!=owner or registered['registration']!=app or app['api']!=api or app['position']!=position or app['exit'] or app['stderr']
                or app['environment']!=application_environment() or credentials['uids']!=[1005]*4 or credentials['gids']!=[1005]*4 or credentials['groups']
                or set(credentials['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'} or any(int(v,16) for v in credentials['capabilities'].values())):raise CaptureError('actual successful service-only cap-zero publisher required')
        expected=(['/bin/ws73-application-client-c'] if api=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py'])+['owned',str(owner['owner']['index']),str(owner['owner']['generation']),registered['service_uuid'],registered['property_uuid']]
        if app['args'][:-2]!=expected or app['args'][-1]!='allow' or len(bytes.fromhex(app['args'][-2]))!=32 or not row['start_wall_ns']<=app['start_wall_ns']<=app['end_wall_ns']<=row['end_wall_ns']:raise CaptureError('actual explicit-policy SDK publisher arguments/interval required')
        lifecycle=publisher_lifecycle_trace(app,owner)
        requested=row.get('publisher_lifecycle_observation_version')
        if requested is not None and (type(requested)is not int or requested!=1):raise CaptureError('exact explicit publisher lifecycle version required')
        if (requested==1)!=(lifecycle is not None):raise CaptureError('publisher lifecycle request/receipt mismatch')
        if lifecycle is not None and any(r['error'] or r['stage']=='approval_return'and r['call_started_ns']>=r['deadline_ns']for r in lifecycle):
            raise CaptureError('publisher failure or admission after original loop budget')
        decisions=authorization_decisions(app)
        if lifecycle is not None:
            calls=lifecycle[1:-2]
            if len(calls)!=len(decisions)or any((c['token'],c['request_id'],c['call_started_ns'])!=(d['token'],d['request_id'],d['decision_ns'])for c,d in zip(calls,decisions)):
                raise CaptureError('actual approval API return must match every original decision')
        expected_calls=[(item,name) for item in row.get('ssap_values',[]) if item['target']==position
                        for name in ['uuid_read_before','read_before','write','read_after','uuid_read_after']]
        if len(expected_calls)!=20:raise CaptureError('complete actual authorization operation coverage required')
        for d,(item,name) in zip(decisions,expected_calls,strict=True):
            obj=owner['object'];identity=owner['owner'];window=item[name]
            if ((d['index'],d['generation'],d['lifetime'],d['handle'],d['property'])
                    !=(identity['index'],identity['generation'],obj['lifetime'],obj['handle'],registered['handle'])
                    or d['write']!=(name=='write') or d['value']!=(item['value'] if name=='write' else '')
                    or not window['start_wall_ns']<=d['decision_wall_ns']<=window['end_wall_ns']):
                raise CaptureError('decision must match actual operation,proposal and original receiver lifetime/window')
        lines=[line for line in app['stdout'].splitlines() if not line.startswith(('SdkAuthorizationDecision: ','SdkOwnedLifecycle: '))]
        start,handle=registered['start'],registered['handle']
        if lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={start} end={handle} property={handle}; local registration only'] or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={start}'] or len(lines)!=7:raise CaptureError('actual retained caller/register/four values/unregister stream required')
        observations=app.get('value_snapshots',[])
        if len(observations)!=4 or [o['ordinal'] for o in observations]!=[1,2,3,4]:raise CaptureError('all four original owner value observations required')
        if any(not re.fullmatch(r'SsapOwnedValue: handle=\d+ value=[0-9a-f]{64}',line) for line in lines[2:-1]):raise CaptureError('bounded original publisher values required')
    return publishers


def duplex_evidence(apps,values,batches,owners,phase):
    """Actual paired SDK/USB obligations,not merely overlapping processes."""
    from ws73_capture import packet_interval
    if len(apps)!=24 or len(values)!=8 or type(batches)is not list or len(batches)!=12:
        raise CaptureError('complete duplex SDK value matrix required')
    fields={'version','index','sequence','step','applications','start_wall_ns','status','supervisor_seconds',
            'released_wall_ns','wait_deadline_monotonic_ns','end_wall_ns','completed_monotonic_ns'}
    results=[]
    for n,batch in enumerate(batches):
        sequence,step=n//3,('read_before','write','read_after')[n%3]
        if (type(batch)is not dict or set(batch)!=fields or batch['status']!='SDK_CALLS_COMPLETE'
            or any(type(batch[k])is not int for k in fields-{'status','step','applications'})
            or(batch['version'],batch['index'],batch['sequence'],batch['step'],batch['supervisor_seconds'])!=(1,n,sequence,step,7)
            or batch['applications']!=[2*n,2*n+1]):raise CaptureError('one exact original paired SDK step required')
        pair=apps[2*n:2*n+2];packets=[]
        if {a['position']for a in pair}!={0,1}:raise CaptureError('opposite original SDK senders required')
        for app in pair:
            sender=app['position'];ssap_receipt(app,owners[sender],expected_uid=1004)
            if (type(app.get('ssap_batch_index'))is not int or app['ssap_batch_index']!=n
                or app['api']!=('c'if sender==phase else'python')):raise CaptureError('actual swapped-language duplex child required')
            found=[v for v in values if(v['sequence'],v['sender'])==(sequence,sender)]
            if len(found)!=1 or found[0]['receipts'][step]!=app:raise CaptureError('each actual SDK child belongs to its original value step')
            index={'read_before':0,'write':2,'read_after':4}[step];wire=found[0]['wire'];request,response=wire[index:index+2]
            if any(bytes.fromhex(leg['tx']['data'])[:2]!=b'\x0a\0'for leg in(request,response)):
                raise CaptureError('duplex proof requires real SSAP SMTC packets')
            packets.append((packet_interval(request['tx'])[1],packet_interval(response['rx'])[1]))
            times=[app[k]for k in ('start_wall_ns','start_barrier_wall_ns','ssap_release_before_wall_ns','ssap_released_wall_ns','end_wall_ns')]
            if (any(type(t)is not int or t<=0 for t in times)or times!=sorted(times)
                or not batch['start_wall_ns']<=times[0]<=times[-1]<=batch['end_wall_ns']):raise CaptureError('original SDK child start/release/end interval required')
        if (max(a['start_barrier_wall_ns']for a in pair)>min(a['ssap_release_before_wall_ns']for a in pair)
            or max(a['ssap_released_wall_ns']for a in pair)>batch['released_wall_ns']
            or batch['released_wall_ns']>min(a['end_wall_ns']for a in pair)
            or any(type(a.get('ssap_release_monotonic_ns'))is not int for a in pair)
            or batch['wait_deadline_monotonic_ns']!=min(a['ssap_release_monotonic_ns']for a in pair)+7_000_000_000
            or batch['completed_monotonic_ns']>batch['wait_deadline_monotonic_ns']):
            raise CaptureError('all actual SDK barriers before release and one original paired deadline required')
        start=max(p[0]for p in packets);end=min(p[1]for p in packets)
        if not start<end:raise CaptureError('both actual SSAP requests must overlap before the first response RX')
        results.append(dict(sequence=sequence,step=step,applications=batch['applications'],
                            pending_overlap_start_wall_ns=start,pending_overlap_end_wall_ns=end))
    return dict(version=1,source_batches=batches,proofs=results,performance_qualified=False)


def corroborate_ssap(rows,capture):
    if len(rows)!=2 or any(row.get('phase')!=n for n,row in enumerate(rows)):raise CaptureError('two original ordered SSAP phases required')
    from ws73_ssap_value import corroborate as value_corroborate
    sdus=reassemble_acb(capture);proofs=[];payloads=set()
    for n,row in enumerate(rows):
        if row.get('ssap_language_required')is not True:raise CaptureError('current gate requires actual SDK SSAP consumers')
        publishers=verify_owned_publishers(row)
        apps=row.get('ssap_language_clients',[])
        if len(apps)!=24:raise CaptureError('both directions/four repeated read-write-read SDK calls required')
        used=[]
        for item in row.get('ssap_values',[]):
            for name in ('read_before','write','read_after'):
                app=item[name];position=item['sender'];entry=row['owners'][position]
                expected_api='c' if position==n else 'python'
                if app not in apps or app in used or app['position']!=position or app['api']!=expected_api:
                    raise CaptureError('actual independent SDK calls and swapped API roles required')
                ssap_receipt(app,entry,expected_uid=1004);used.append(app)
        if len(used)!=24:raise CaptureError('every SSAP application must belong to one actual operation')
        def matched(entry,direction,payload,item):
            owner,obj=entry['owner'],entry['object']
            found=[s for s in sdus if (s['bus'],s['device'],s['handle'],s['direction'],s['data'])==(owner['bus'],owner['device'],obj['handle'],direction,payload.hex()) and item['start_wall_ns']<=s['wall_ns']<=item['end_wall_ns']]
            if len(found)!=1:raise CaptureError('one actual SDK SSAP TX/opposite USB RX in its original interval required')
            return found[0]
        values,_=value_corroborate(row,matched)
        for value in values:
            if value['value']in payloads:raise CaptureError('fresh SSAP payloads required across connection roles')
            payloads.add(value['value'])
        part=dict(phase=n,applications=apps,values=values,publishers=publishers,authorization_requests=40)
        if 'ssap_sdk_duplex_required'in row:
            if row['ssap_sdk_duplex_required']is not True:raise CaptureError('typed explicit duplex evidence required')
            part['duplex']=duplex_evidence(apps,values,row['ssap_sdk_batches'],row['owners'],n)
        elif row.get('ssap_sdk_batches')or any('ssap_batch_index'in a for a in apps):raise CaptureError('unrequested duplex cannot relabel sequential evidence')
        proofs.append(part)
    return dict(status='C_PYTHON_SSAP_VALUE_USB_CORROBORATED',operations=16,api_calls=48,authorization_requests=80,proofs=proofs)


def corroborate(run,capture):
    rows=run.get('application_clients')
    if not isinstance(rows,list) or len(rows)!=2:raise CaptureError('both connection roles required for application clients')
    sdus=reassemble_acb(capture);proofs=[];used=set()
    for n,row in enumerate(rows):
        from ws73_application_role import verify_probe
        verify_probe(row)
        if row['phase']!=n or row['status']!='APPLICATION_CLIENT_EVIDENCE_PENDING' or len(row['owners'])!=2 or len(row['applications'])!=2:raise CaptureError('complete actual application phase required')
        request,reply=bytes.fromhex(row['request']),bytes.fromhex(row['reply'])
        if len(request)!=61 or len(reply)!=61 or request==reply or request[:4]!=n.to_bytes(4,'little') or reply[:4]!=request[:4] or request in used or reply in used:raise CaptureError('fresh sequence and independent full random payloads required')
        used.update([request,reply]);values={}
        for app in row['applications']:
            position=app['position'];expected_api=('c' if position==0 else 'python') if n==0 else ('python' if position==0 else 'c')
            if position in values or app['api']!=expected_api:raise CaptureError('both languages must exchange application roles')
            ready,complete=receipts(app,row['owners'][position]);outgoing,incoming=(reply,request) if position else (request,reply)
            if complete['sent']!=outgoing.hex() or complete['received']!=incoming.hex():raise CaptureError('opposite application must actually validate and reply')
            values[position]=dict(api=app['api'],identity=ready,credentials=app['credentials'])
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
        proofs.append(dict(phase=n,applications=values,legs=legs,role_probe=row['role_probe'],channel_role=row['channel_role'],application_role_contract_version=row['application_role_contract_version']))
    ssap=corroborate_ssap(rows,capture)
    return dict(status='C_PYTHON_APPS_ONLY_CHANNEL_AND_OWNED_SSAP_USB_SCOPED_PASS',application_role_contract_version=2,round_trips=2,proofs=proofs,ssap=ssap,remaining=['Not deployed group-policy/revocation/fullAPI/recovery orperformance qualification','Other lifecycle combinations and original gates remainrequired'])


def valid_summary(proof):
    """Terminal shape check only; never substitutes for raw corroborate()."""
    try:
        if type(proof.get('application_role_contract_version'))is not int or proof['application_role_contract_version']!=2 or proof['status']!='C_PYTHON_APPS_ONLY_CHANNEL_AND_OWNED_SSAP_USB_SCOPED_PASS' or type(proof['round_trips']) is not int or proof['round_trips']!=2 or len(proof['proofs'])!=2:return False
        ssap=proof['ssap']
        if ssap['status']!='C_PYTHON_SSAP_VALUE_USB_CORROBORATED' or ssap['operations']!=16 or ssap['api_calls']!=48 or ssap.get('authorization_requests')!=80 or len(ssap['proofs'])!=2:return False
        for n,row in enumerate(ssap['proofs']):
            if row['phase']!=n or len(row['values'])!=8 or len(row['applications'])!=24:return False
            if len(row.get('publishers',[]))!=2 or row.get('authorization_requests')!=40:return False
            for i,publisher in enumerate(row['publishers']):
                if publisher['api']!=('c' if i==n else 'python') or publisher['exit'] or publisher['stderr'] or publisher['credentials']['uids']!=[1005]*4 or len(publisher.get('value_snapshots',[]))!=4:return False
                authorization_decisions(publisher)
            for app in row['applications']:
                if (app['credentials']['uids']!=[1004]*4 or app['credentials'].get('gids')!=[1004]*4
                        or app['credentials'].get('groups')!=[] or set(app['credentials']['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'}
                        or any(int(v,16)for v in app['credentials']['capabilities'].values())):return False
                if app['position']not in (0,1) or app['api']!=('c' if app['position']==n else 'python') or app['exit'] or app['stderr']:return False
            for value in row['values']:
                if len(value['wire'])!=6 or len(value['uuid_wire'])!=2:return False
                legs=list(value['wire'])
                for item in value['uuid_wire']:legs.extend([item['request'],item['response']])
                for leg in legs:
                    a,b=leg['tx'],leg['rx'];raw=bytes.fromhex(a['data'])
                    if raw[:2]!=b'\x0a\0' or len(raw)<6 or int.from_bytes(raw[2:4],'little')!=len(raw)-4 or a['data']!=b['data'] or (a['bus'],a['device'])==(b['bus'],b['device']):return False
        frames=set()
        for n,row in enumerate(proof['proofs']):
            from ws73_application_role import verify_probe
            verify_probe(row)
            if row['phase']!=n or len(row['legs'])!=2:return False
            apps={str(k):v for k,v in row['applications'].items()}
            if set(apps)!={'0','1'} or [apps[str(i)]['api'] for i in [0,1]]!=(['c','python'] if n==0 else ['python','c']):return False
            for app in apps.values():
                identity=app['identity']
                credential=app['credentials']
                if credential['uids']!=[1004]*4 or credential['gids']!=[1004]*4 or credential['groups'] or any(int(v,16) for v in credential['capabilities'].values()):return False
                if identity['dup_alive'] is not True or identity['client_closed'] is not True or identity['generation']<=0 or identity['lifetime']<=0:return False
            for leg in row['legs']:
                a,b=leg['out'],leg['in'];raw=bytes.fromhex(a['data'])
                if raw[:5]!=b'\x1f\0\x3e\0\xf1' or len(raw)!=66 or a['data']!=b['data'] or (a['bus'],a['device'])==(b['bus'],b['device']) or a['data'] in frames:return False
                frames.add(a['data'])
        return True
    except (KeyError,TypeError,ValueError):return False
