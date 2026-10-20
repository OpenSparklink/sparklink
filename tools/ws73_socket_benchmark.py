# SPDX-License-Identifier: GPL-2.0-only
"""Native ordinary-application load supervision, using existing slktest/USB gates.

No Host, echo server or controller transition is implemented here. Fixed small
first-baseline workload; application clocks never subtracted across endpoints.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import selectors
import subprocess
import stat
import time

from ws73_capture import CaptureError, reassemble_acb
from ws73_channel_socket import credentials, test_program, validate_application_binary
from ws73_benchmark import load_application_reports, read_report

COUNT, SIZE, WINDOW = 20, 61, 4
CONFIG_FIELDS={'mode','count','bytes','window','interval_us'}
PENDING = 'SOCKET_LOAD_APPLICATION_EVIDENCE_PENDING'


from ws73_role_snapshot import profile as snapshot_profile
_ROLE_PROFILE=snapshot_profile('benchmark')
ROLE_TOKEN=_ROLE_PROFILE['token']
ROLE_ROOT=Path(_ROLE_PROFILE['artifact'])
ROLE_RUNTIME=Path(_ROLE_PROFILE['root'])
ROLE_INPUT=Path('/evidence/application/passthrough-control')
ROLE_VERSION=1
RESOURCE_FIELD='benchmark_process_resource_contract_version'
CHANNEL_FIELD='benchmark_channel_request'
ROLE_STATUS='TWO_FINITE_BENCHMARK_PHASES_COMPLETED'
CLOCK='guest wall_ns for observed IO/capture;guest monotonic_ns for supervisory budgets;no cross-application timestamp subtraction'
ROLE_REQUEST_FIELDS={'phase','owners','config','application_tool','start_wall_ns','status','applications','events','performance_qualified','clock','socket_benchmark_role_contract_version','tools'}


def channel_configuration(value):
    """Explicit protocol endpoints, not TCIDs, identity or observed capabilities."""
    if (type(value)is not dict or set(value)!={'version','kind','ports','aid','active_endpoint'}
        or type(value['version'])is not int or value['version']!=1 or value['kind']!='dynamic_basic'
        or type(value['ports'])is not list or len(value['ports'])!=2
        or any(type(v)is not int or not 1<=v<=65535 for v in value['ports'])
        or type(value['aid'])is not int or not 1<=value['aid']<=65535
        or type(value['active_endpoint'])is not int or value['active_endpoint']not in(0,1)):
        raise CaptureError('explicit version1 basic dynamic route required')
    return value


def requested_channel(args):
    dynamic=getattr(args,'channel_benchmark_dynamic',False)
    active=getattr(args,'channel_benchmark_active_endpoint',None)
    if type(dynamic)is not bool or (active is not None and(type(active)is not int or active not in(0,1))):
        raise CaptureError('explicit dynamic benchmark selector/role required')
    if not dynamic:
        if active is not None:raise CaptureError('channel role requires dynamic benchmark')
        return None
    if not getattr(args,'channel_benchmark',None):raise CaptureError('dynamic target requires benchmark mode')
    return channel_configuration(dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=0 if active is None else active))


def row_channel(row):
    return channel_configuration(row[CHANNEL_FIELD])if CHANNEL_FIELD in row else None


def request_fields(row):
    return ROLE_REQUEST_FIELDS|({RESOURCE_FIELD}if RESOURCE_FIELD in row else set())|({CHANNEL_FIELD}if CHANNEL_FIELD in row else set())


def application_request(row,index):
    channel=row_channel(row)
    if channel is None:return None
    mtu=max(249,row['config']['bytes'])
    return dict(version=1,kind='dynamic_basic',source_port=channel['ports'][index],destination_port=channel['ports'][1-index],
                aid=channel['aid'],mtu=mtu,mps=mtu+5,slqi=1,passive=index!=channel['active_endpoint'])


def staged_text(row,index):
    r=application_request(row,index)
    return f"SocketBenchmarkStaged: source={r['source_port']} destination={r['destination_port']} aid={r['aid']} passive={str(r['passive']).lower()}"


def apps_role(row):
    version=row.get('socket_benchmark_role_contract_version')
    if version is not None and(type(version)is not int or version!=ROLE_VERSION):raise CaptureError('explicit benchmark apps-only role contract1 required')
    return version is not None


def role_tool_path(root,name):
    """Resolve only the fixed native-lab executable alias inside the guest root."""
    import re
    root=Path(root).resolve(strict=True);path=root/name.lstrip('/')
    if name=='/bin/slktest':
        if not path.is_symlink():raise CaptureError('fixed native-lab slktest alias required')
        target=path.readlink()
        if not re.fullmatch(r'/usr/libexec/opensparklink/native-lab/[0-9a-f]{12}/slktest',str(target)):raise CaptureError('unexpected slktest alias target')
        path=root/str(target).lstrip('/')
    elif path.is_symlink():raise CaptureError('fixed regular role tool required')
    resolved=path.resolve(strict=True)
    if not resolved.is_relative_to(root)or not resolved.is_file():raise CaptureError('role tool outside sealed guest root')
    return resolved


def role_tools(root=Path('/'),*,dynamic=False):
    import hashlib
    from ws73_role_snapshot import HELPER,SUPERVISOR
    names=('/bin/slktest','/bin/bus-policy-probe',HELPER,SUPERVISOR,'/usr/share/sparklink/tools/ws73_socket_benchmark.py','/usr/share/sparklink/tools/ws73_benchmark.py','/usr/share/sparklink/tools/ws73_benchmark_timeline.py','/usr/share/sparklink/tools/ws73_benchmark_resources.py')
    if dynamic:names+=('/usr/share/sparklink/tools/ws73_dynamic_channels.py',)
    return {n:dict(sha256=hashlib.sha256(role_tool_path(root,n).read_bytes()).hexdigest(),bytes=role_tool_path(root,n).stat().st_size)for n in names}


def validate_role_sources(package,*,dynamic=False):
    from ws73_north_star import file_record
    here=Path(__file__).resolve().parent
    if type(package.get('socket_benchmark_role_contract_version'))is not int or package['socket_benchmark_role_contract_version']!=1:raise ValueError('fresh apps-only benchmark prepared contract1 required')
    if type(package.get('benchmark_trace_contract_version'))is not int or package['benchmark_trace_contract_version']!=1:raise ValueError('fresh explicit monotonic benchmark trace contract1 required')
    if type(package.get(RESOURCE_FIELD)) is not int or package[RESOURCE_FIELD]!=1:raise ValueError('fresh process-resource benchmark contract1 required')
    names=('ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh')
    if dynamic:names+=('ws73_dynamic_channels.py',)
    for name in names:
        matches=[v for v in package['inputs']if Path(v['path']).name==name]
        if len(matches)!=1 or matches[0]['sha256']!=file_record(here/name)['sha256']:raise ValueError('prepared benchmark role/source closure mismatch: '+name)


def validate_role_request(row,phase,*,live=False):
    extra={RESOURCE_FIELD}if RESOURCE_FIELD in row else set()
    if row_channel(row)is not None:extra.add(CHANNEL_FIELD)
    if (live or RESOURCE_FIELD in row)and(type(row.get(RESOURCE_FIELD))is not int or row[RESOURCE_FIELD]!=1):raise CaptureError('new live resource checkpoint contract required')
    if(type(phase)is not int or phase not in(0,1)or type(row.get('phase'))is not int or row['phase']!=phase or not apps_role(row)
        or set(row)!=ROLE_REQUEST_FIELDS|extra
        or row['applications']!=[]or row['events']!=[]or row['status']!='RUNNING'or row['performance_qualified']is not False):raise CaptureError('fixed empty apps-only benchmark request required')
    validate_configuration(row['config']);validate_application_binary(row['application_tool'])
    if row['clock']!=CLOCK or type(row['start_wall_ns'])is not int or row['start_wall_ns']<=0:raise CaptureError('original benchmark clock/start required')
    import re
    if len(row['owners'])!=2:raise CaptureError('two benchmark owners required')
    for entry in row['owners']:
        owner,obj=entry['owner'],entry['object']
        if(type(owner['index'])is not int or not 0<=owner['index']<16 or type(owner['generation'])is not int or not 0<owner['generation']<2**64 or owner['path']!=f"/org/sparklink/slk{owner['index']}_g{owner['generation']}"or obj['generation']!=owner['generation']
            or type(obj['lifetime'])is not int or not 0<obj['lifetime']<2**64 or type(obj['handle'])is not int or not 0<=obj['handle']<=4095
            or not re.fullmatch(r'/org/sparklink/slk'+str(owner['index'])+r'_g'+str(owner['generation'])+r'/peer_t[0-9a-f]{2}_[0-9a-f]{12}/link_'+f"{obj['lifetime']:016x}",obj['path'])):raise CaptureError('canonical original benchmark connection required')
    if len({v['owner']['index']for v in row['owners']})!=2:raise CaptureError('distinct original controllers required')


def execute(run,phase):
    """Control role requests one fixed root-supervised ordinary application pair."""
    from ws73_application_role import read_json
    row=dict(phase=len(run.data['connection_control']['phases'])-1,owners=phase['typed_objects'],config=requested_configuration(run.args),application_tool=test_program(run),start_wall_ns=time.time_ns(),status='RUNNING',applications=[],events=[],performance_qualified=False,clock=CLOCK,socket_benchmark_role_contract_version=ROLE_VERSION,benchmark_process_resource_contract_version=1,tools=role_tools())
    channel=requested_channel(run.args)
    if channel is not None:row[CHANNEL_FIELD]=channel;row['tools']=role_tools(dynamic=True)
    validate_role_request(row,row['phase'],live=True);run.data.setdefault('socket_benchmark',[]).append(row);run.save()
    path=run.output/f'benchmark-role-{row["phase"]}.request.json';temporary=path.with_suffix('.tmp')
    with temporary.open('x')as f:json.dump(row,f)
    temporary.chmod(0o600);os.link(temporary,path);temporary.unlink()
    original={k:row[k]for k in row if k not in ('applications','events','status')}
    response=ROLE_ROOT/f'phase-{row["phase"]}'/'run.json';deadline=time.monotonic()+750
    while not response.is_file():
        if time.monotonic()>=deadline:raise CaptureError('original finite benchmark root-supervisor deadline')
        time.sleep(.01)
    result=read_json(response,0,limit=256*1024*1024)
    if any(result[k]!=v for k,v in original.items())or result.get('status')!=PENDING:raise CaptureError('original apps-only benchmark request failed: '+str(result.get('error')))
    from ws73_application_role import verify_probe
    verify_probe(result);check_supervision(result);row.clear();row.update(result);run.save()


def configuration(mode, window=WINDOW, *, count=COUNT, size=SIZE, interval_us=None):
    if (mode not in ('rate','window','duplex') or type(count) is not int or not 1<=count<=10000
            or type(size) is not int or not 29<=size<=2042
            or type(window) is not int or not 1<=window<=min(count,256)):
        raise CaptureError('explicit bounded Native benchmark workload required')
    interval_us=(100000 if mode=='rate' else 0) if interval_us is None else interval_us
    if type(interval_us) is not int or (mode=='rate' and not (10<=interval_us<=1000000 and interval_us*count<=600000000)) or (mode!='rate' and interval_us!=0):
        raise CaptureError('original bounded absolute-rate plan or zero non-rate interval required')
    return dict(mode=mode,count=count,bytes=size,window=window,interval_us=interval_us)


def requested_configuration(args):
    mode=getattr(args,'channel_benchmark',None)
    values=dict(window=getattr(args,'channel_benchmark_window',WINDOW),count=getattr(args,'channel_benchmark_count',COUNT),size=getattr(args,'channel_benchmark_bytes',SIZE),interval_us=getattr(args,'channel_benchmark_interval_us',None))
    if mode is None:
        if values!=dict(window=WINDOW,count=COUNT,size=SIZE,interval_us=None):
            raise CaptureError('load parameters require explicit benchmark mode')
        return None
    return configuration(mode,**values)


def validate_configuration(config):
    if type(config) is not dict or set(config)!=CONFIG_FIELDS:
        raise CaptureError('exact requested workload fields required')
    valid=configuration(config['mode'],config['window'],count=config['count'],size=config['bytes'],interval_us=config['interval_us'])
    if config!=valid:raise CaptureError('canonical bounded workload required')
    return valid


def record_configuration(record):
    mode=record['socket_benchmark_requested'];window=record.get('socket_benchmark_window_requested',WINDOW)
    if type(window) is not int:raise CaptureError('integer requested window required')
    config=record['socket_benchmark_config_requested'] if 'socket_benchmark_config_requested' in record else configuration(mode,window)
    valid=validate_configuration(config)
    if valid['mode']!=mode or valid['window']!=window:
        raise CaptureError('original mode/window/workload request mismatch')
    return valid


def arguments(binary, entry, mode, report, window=WINDOW, *, count=COUNT, size=SIZE, interval_us=None, channel=None):
    c=configuration(mode if mode!='peer' else 'window',window,count=count,size=size,interval_us=0 if mode=='peer' else interval_us)
    args=[str(binary),'--adapter',entry['owner']['path'],'channel',mode,entry['object']['path'],
          '--count',str(c['count']),'--bytes',str(c['bytes']),'--window',str(window),'--report',str(report)]
    if mode=='peer':args+=['--load']
    if mode=='rate':args+=['--interval-us',str(c['interval_us'])]
    if channel is not None:
        args+=['--source-port',str(channel['source_port']),'--destination-port',str(channel['destination_port']),
               '--aid',str(channel['aid']),'--channel-role','passive'if channel['passive']else'active']
    return args


def execute_supervised(run,row):
    """Only normative live workload:fixed disposable-VM apps-only children."""
    from ws73_application_role import require_vm
    from ws73_application_client import process_identity,application_environment
    from ws73_north_star import file_record
    require_vm(ROLE_TOKEN)
    if not apps_role(row):raise CaptureError('live benchmark requires explicit apps-only contract')
    validate_role_request({k:row[k]for k in request_fields(row)},row['phase'],live=True)
    if row['tools']!=role_tools(dynamic=row_channel(row)is not None)or row['application_tool']!=file_record(Path('/bin/slktest').resolve(strict=True)):
        raise CaptureError('fixed prepared benchmark executables and tools required')
    mode=row['config']['mode'];window=row['config']['window'];config=validate_configuration(row['config'])
    reports=run.output/'reports';reports.mkdir(mode=0o700);os.chown(reports,1004,1004)
    processes=[None,None];row['applications']=[None,None]
    buffers={};output={};duplicates=set();selector=selectors.DefaultSelector()
    channel=row_channel(row);observed={kind:set()for kind in ('staged','armed','quiescent')}
    def event(kind,index,**values):
        row['events'].append(dict(kind=kind,application=index,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),**values))
    def wait_marker(kind,seconds,indices=(0,1)):
        deadline=time.monotonic()+seconds
        while not set(indices)<=observed[kind]:
            if time.monotonic()>=deadline:raise CaptureError('original benchmark supervisor '+kind+' deadline')
            for key,_ in selector.select(min(.1,max(0,deadline-time.monotonic()))):
                index=key.data;data=os.read(key.fileobj.fileno(),8192)
                if not data:raise CaptureError('benchmark exited before both '+kind+' markers')
                output[index]+=data;buffers[index]+=data
                if len(output[index])>65536:raise CaptureError('bounded benchmark stdout exceeded')
                while b'\n' in buffers[index]:
                    raw,buffers[index]=buffers[index].split(b'\n',1)
                    text=raw.decode('utf-8',errors='strict')
                    if text=='NativeChannelDup: original_closed=1 duplicate_live=1' and index not in duplicates:
                        duplicates.add(index);row['applications'][index]['dup_observed_wall_ns']=time.time_ns();continue
                    if index not in duplicates:raise CaptureError('actual existing duplicate-fd setup receipt required')
                    expected_mode=row['applications'][index]['mode'].capitalize()
                    markers={'armed':f"SocketBenchmarkArmed: mode={expected_mode} count={config['count']} bytes={config['bytes']} window={window}",
                             'quiescent':f'SocketBenchmarkQuiescent: mode={expected_mode} correctness=true'}
                    if channel is not None:markers['staged']=staged_text(row,index)
                    matches=[name for name,line in markers.items()if line==text]
                    if len(matches)!=1:raise CaptureError('unexpected benchmark phase output:'+text)
                    actual=matches[0]
                    if(index in observed[actual]or actual=='armed'and channel is not None and index not in observed['staged']
                       or actual=='staged'and index in observed['armed']
                       or actual=='quiescent'and not any(e['kind']=='start'and e['application']==index for e in row['events'])):
                        raise CaptureError('duplicate/out-of-order benchmark phase output:'+text)
                    event(actual,index,text=text);observed[actual].add(index)
    def release(kind):
        for i,(proc,_) in enumerate(processes):
            before_wall=time.time_ns();before_mono=time.monotonic_ns()
            proc.stdin.write((kind+'\n').encode());proc.stdin.flush()
            event(kind,i,before_wall_ns=before_wall,before_monotonic_ns=before_mono)
    try:
        with ExitStack() as files:
            order=(1-channel['active_endpoint'],channel['active_endpoint'])if channel is not None else(0,1)
            for i in order:
                entry=row['owners'][i]
                appmode=mode if i==0 or mode=='duplex' else 'peer'
                report=reports/f'benchmark-{row["phase"]}-{i}.json'
                err=run.output/f'benchmark-{row["phase"]}-{i}.stderr'
                app=dict(mode=appmode,args=arguments(row['application_tool']['path'],entry,appmode,report,window,count=config['count'],size=config['bytes'],interval_us=config['interval_us'],channel=application_request(row,i)),report_path=str(report),stderr_path=str(err),start_wall_ns=time.time_ns())
                row['applications'][i]=app
                proc=subprocess.Popen(app['args'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=files.enter_context(err.open('xb')),bufsize=0,user=1004,group=1004,extra_groups=[],umask=0o077,env=dict(os.environ,**application_environment()))
                processes[i]=(proc,app);app['pid']=proc.pid;app['credentials'],app['process_status']=process_identity(proc.pid,1004);app['environment']=application_environment();app['output_files']=[str(run.output/f'benchmark-{row["phase"]}-{i}.stdout'),str(err)]
                selector.register(proc.stdout,selectors.EVENT_READ,i);buffers[i]=b'';output[i]=b''
                if channel is not None:wait_marker('staged',10,(i,))
            wait_marker('armed',45)
            from ws73_benchmark_resources import collect
            for proc,app in processes:app['process_resources']={'before':collect(proc.pid,row['application_tool']['path'])}
            # No disk writes between start and both quiescent; bounded IO receipts
            # stay in memory. These are sparse supervision events, not per-packet logs.
            from ws73_benchmark_timeline import phase_marker
            row['trace_observation']=phase_marker(row['phase'],'BEGIN')
            release('start')
            wait_marker('quiescent',620)
            end=phase_marker(row['phase'],'END')
            if {k:v for k,v in end.items()if k!='marker'}!={k:v for k,v in row['trace_observation'].items()if k!='marker'}:raise CaptureError('trace configuration changed during business phase')
            row['trace_observation']['end_marker']=end['marker']
            for proc,app in processes:app['process_resources']['after']=collect(proc.pid,row['application_tool']['path'])
            release('finish')
            deadline=time.monotonic()+15
            for i,(proc,app) in enumerate(processes):
                proc.stdin.close();proc.wait(timeout=max(.001,deadline-time.monotonic()))
                tail=proc.stdout.read(65537-len(output[i]));output[i]+=tail
                if len(output[i])>65536:raise CaptureError('benchmark output byte budget')
                app.update(exit=proc.returncode,end_wall_ns=time.time_ns(),stdout=output[i].decode(),stderr=Path(app['stderr_path']).read_text())
                if proc.returncode:raise CaptureError('actual slktest failed:'+app['stderr'])
                report,record=read_report(app['report_path'],expected_uid=1004);app['report']=report;app['report_file']=record
            row['end_wall_ns']=time.time_ns()
            check_supervision(row)
            row['application_check']=load_application_reports(*(a['report'] for a in row['applications']))
            if test_program(run)!=row['application_tool']:raise CaptureError('slktest artifact changed')
            row['status']=PENDING
    except BaseException as error:
        row.update(status='FAIL',error=str(error),error_type=type(error).__name__);raise
    finally:
        for i,pair in enumerate(processes):
            if pair is None:continue
            proc,app=pair
            if proc.poll() is None:
                if not proc.stdin.closed:proc.stdin.close()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            app.setdefault('exit',proc.returncode)
            if 'stdout' not in app:app['stdout']=output.get(i,b'').decode(errors='replace')
            if Path(app['stderr_path']).is_file():app['stderr']=Path(app['stderr_path']).read_text()
            (run.output/f'benchmark-{row["phase"]}-{i}.stdout').write_text(app['stdout'])
        selector.close();row['end_wall_ns']=time.time_ns();run.save()


def check_supervision(row):
    window=row['config']['window']
    config=row['config']
    validate_configuration(config)
    if len(row['applications'])!=2:
        raise CaptureError('exact bounded Native benchmark workload required')
    validate_application_binary(row['application_tool'])
    from ws73_benchmark_resources import observations
    if RESOURCE_FIELD in row and not apps_role(row):raise CaptureError('resource checkpoint requires apps-only role')
    observations(row)
    channel=row_channel(row)
    if channel is not None and not apps_role(row):raise CaptureError('dynamic measurement requires apps-only role')
    all_events=row['events'];events=[e for e in all_events if e['kind']!='staged']
    if channel is None and events!=all_events:raise CaptureError('basic CUTC has no dynamic staging')
    stages=[e for e in all_events if e['kind']=='staged']
    if channel is not None:
        if len(stages)!=2 or {e['application']for e in stages}!={0,1}:raise CaptureError('both exact dynamic staged receipts required')
        passive=1-channel['active_endpoint'];staged=next(e for e in stages if e['application']==passive)
        if staged['wall_ns']>row['applications'][channel['active_endpoint']]['start_wall_ns']:raise CaptureError('passive staged before active process creation required')
    if len(events)!=8:raise CaptureError('complete paired arm/start/quiescent/finish receipts required')
    for clock in ['wall_ns','monotonic_ns']:
        stamps=[e[clock] for e in all_events]
        if any(type(v) is not int for v in stamps) or stamps!=sorted(stamps):raise CaptureError('same guest supervisor clock order')
    for offset,kind in enumerate(['armed','start','quiescent','finish']):
        chunk=events[offset*2:offset*2+2]
        if {e['application'] for e in chunk}!={0,1} or any(e['kind']!=kind for e in chunk):raise CaptureError('paired barrier order before either release')
    for i,app in enumerate(row['applications']):
        expected=row['config']['mode'] if i==0 or row['config']['mode']=='duplex' else 'peer'
        requested=application_request(row,i)
        if app['mode']!=expected or app['args']!=arguments(row['application_tool']['path'],row['owners'][i],expected,app['report_path'],window,count=config['count'],size=config['bytes'],interval_us=config['interval_us'],channel=requested):raise CaptureError('actual slktest argv/mode mismatch')
        if ('channel_request'in app['report'])!=(requested is not None)or requested is not None and app['report']['channel_request']!=requested:
            raise CaptureError('actual report channel request differs from original target')
        cred=app['credentials']
        if apps_role(row):
            from ws73_application_client import application_environment
            if(app['exit']or cred['uids']!=[1004]*4 or cred['gids']!=[1004]*4 or cred['groups']or set(cred['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'}or any(int(v,16)for v in cred['capabilities'].values())or app['environment']!=application_environment()):raise CaptureError('actual apps-only benchmark credentials required')
            file=app['report_file']
            if(set(file)!={'path','sha256','bytes','uid','gid','mode','nlink'}or any(type(file[k])is not int for k in ('bytes','uid','gid','mode','nlink'))or file['uid']!=1004 or file['gid']!=1004 or file['nlink']!=1 or not 0<file['bytes']<=256*1024*1024 or file['mode']&0o022):raise CaptureError('actual closed app-owned report required')
        elif app['exit']or cred['uids']!=[1000]*4 or any(int(v,16)for v in cred['capabilities'].values()):raise CaptureError('historical control-role benchmark process required')
        lines=app['stdout'].splitlines()
        expected_lines=['NativeChannelDup: original_closed=1 duplicate_live=1',f"SocketBenchmarkArmed: mode={expected.capitalize()} count={config['count']} bytes={config['bytes']} window={window}",
                        f'SocketBenchmarkQuiescent: mode={expected.capitalize()} correctness=true',
                        f'SocketBenchmarkLoadObserved: report={app["report_path"]} qualified=false']
        marker_lines=dict(armed=expected_lines[1],quiescent=expected_lines[2])
        if channel is not None:
            marker_lines['staged']=staged_text(row,i);expected_lines.insert(1,marker_lines['staged'])
        if lines!=expected_lines:raise CaptureError('exact complete successful stdout receipts')
        armed=next(e for e in events if e['application']==i and e['kind']=='armed')
        if not app['start_wall_ns']<=app.get('dup_observed_wall_ns',0)<=armed['wall_ns']:raise CaptureError('original duplicate receipt before arm')
        if channel is not None:
            staged=next(e for e in stages if e['application']==i)
            if not app['dup_observed_wall_ns']<=staged['wall_ns']<=armed['wall_ns']or staged['monotonic_ns']>armed['monotonic_ns']:
                raise CaptureError('staged fd preparation must precede its actual Ready')
        for kind,line in marker_lines.items():
            if next(e for e in all_events if e['application']==i and e['kind']==kind).get('text')!=line:raise CaptureError('IO marker differs from actual stdout')
        for kind,limit,previous in [('start',30,'armed'),('finish',30,'quiescent')]:
            e=next(e for e in events if e['application']==i and e['kind']==kind)
            own=next(e for e in events if e['application']==i and e['kind']==previous)
            if not events[(['armed','start','quiescent','finish'].index(kind)-1)*2+1]['wall_ns']<=e['before_wall_ns']<=e['wall_ns']:raise CaptureError('both endpoints observed before control write')
            if not max(own['monotonic_ns'],events[(['armed','start','quiescent','finish'].index(kind)-1)*2+1]['monotonic_ns'])<=e['before_monotonic_ns']<=e['monotonic_ns']<own['monotonic_ns']+limit*1_000_000_000:raise CaptureError('bounded original supervisory input')
        identity=app['report']['channel_identity'];owner=row['owners'][i]['owner'];obj=row['owners'][i]['object']
        if any(identity[k]!=v for k,v in [('controller',owner['index']),('generation',owner['generation']),('lifetime',obj['lifetime']),('handle',obj['handle'])]):raise CaptureError('report/current registration connection identity')
        cfg=app['report']['config'];expected_cfg=dict(row['config'],mode=expected,interval_us=row['config']['interval_us'] if expected=='rate' else 0)
        if cfg!=expected_cfg:raise CaptureError('actual report workload differs from request')
        if not row['start_wall_ns']<=app['start_wall_ns']<=events[0]['wall_ns']<app['end_wall_ns']<=row['end_wall_ns']:raise CaptureError('original process observation window')


def check_report_files(row, share):
    share=Path(share).resolve(strict=True)
    for i,app in enumerate(row['applications']):
        expected=str(ROLE_RUNTIME/f'phase-{row["phase"]}'/'reports'/f'benchmark-{row["phase"]}-{i}.json')if apps_role(row)else f"/evidence/application/passthrough-control/benchmark-{row['phase']}-{i}.json"
        if app['report_path']!=expected or app['report_file']['path']!=expected:raise CaptureError('original benchmark report location')
        exported=ROLE_ROOT/f'phase-{row["phase"]}'/'reports'/Path(expected).name if apps_role(row)else Path(expected)
        path=(share/exported.relative_to('/evidence')).resolve(strict=True)
        path.relative_to(share)
        report,record=read_report(path)
        if any(record[k]!=app['report_file'][k] for k in ['sha256','bytes']) or json.dumps(report,sort_keys=True)!=json.dumps(app['report'],sort_keys=True):raise CaptureError('report bytes/hash differ from observed process output')
        for suffix,key in [('stdout','stdout'),('stderr','stderr')]:
            output=(share/'benchmark-role'/f'phase-{row["phase"]}'/f'benchmark-{row["phase"]}-{i}.{suffix}')if apps_role(row)else path.with_suffix('.'+suffix)
            text=output.read_text()
            if text!=app[key]:raise CaptureError('original benchmark process log differs')


def corroborate(run,capture,share):
    rows=run.get('socket_benchmark')
    if type(rows) is not list or len(rows)!=2:raise CaptureError('both actual connection-role benchmark phases required')
    roles=[apps_role(row)for row in rows]
    if any(roles):
        if not all(roles):raise CaptureError('two matching benchmark role phases required')
        verify_role_artifacts(run,share)
    sdus=reassemble_acb(capture);proofs=[];used=set()
    # Preserve every duplicate candidate; index only replaces repeated full scans.
    indexed={}
    for packet in sdus:
        key=tuple(packet[k] for k in ['bus','device','handle','direction','data'])
        indexed.setdefault(key,[]).append(packet)
    for n,row in enumerate(rows):
        if row['phase']!=n or row['status']!=PENDING:raise CaptureError('both successful original benchmark phases')
        connection=run['connection_control']['phases'][n]
        if row['owners']!=connection['typed_objects'] or not run['commands'][connection['connect_command']]['end_wall_ns']<=row['start_wall_ns']<=row['end_wall_ns']<=run['commands'][connection['disconnect_command']]['start_wall_ns']:raise CaptureError('benchmark belongs to current physical connection interval')
        check_supervision(row)
        check_report_files(row,share)
        check=load_application_reports(*(app['report'] for app in row['applications']))
        legs=[]
        start=next(e['before_wall_ns'] for e in row['events'] if e['kind']=='start')
        end=max(e['wall_ns'] for e in row['events'] if e['kind']=='quiescent')
        def matched(index,direction,frame,*,lower=start,upper=end):
            entry=row['owners'][index];owner=entry['owner'];obj=entry['object']
            found=[p for p in indexed.get((owner['bus'],owner['device'],obj['handle'],direction,frame.hex()),[]) if lower<=p['wall_ns']<=upper]
            if len(found)!=1:raise CaptureError('one exact opposite USB TX/RX for each benchmark business frame')
            packet=found[0];key=(packet['record'],packet.get('hcc_offset',0),direction,owner['bus'],owner['device'])
            if key in used:raise CaptureError('benchmark evidence reused')
            used.add(key);return packet
        channel=row_channel(row);negotiation=None
        if channel is not None:
            from ws73_dynamic_channels import cmtc,request
            active=channel['active_endpoint'];passive=1-active
            a=row['applications'][active]['report']['channel_identity'];b=row['applications'][passive]['report']['channel_identity']
            owner=row['owners'][active]['owner'];obj=row['owners'][active]['object'];requested=application_request(row,active)
            candidates=[p for p in sdus if (p['bus'],p['device'],p['handle'],p['direction'])==(owner['bus'],owner['device'],obj['handle'],'out')
                        and row['start_wall_ns']<=p['wall_ns']<start and len(bytes.fromhex(p['data']))==26
                        and bytes.fromhex(p['data'])[4]==16 and bytes.fromhex(p['data'])[8]==a['local_tcid']]
            if len(candidates)!=1:raise CaptureError('one actual dynamic request before business required')
            identifier=bytes.fromhex(candidates[0]['data'])[5]
            req=cmtc(request(identifier,a['local_tcid'],[requested['source_port'],requested['destination_port']],requested['aid'],requested['mtu'],requested['mps']))
            resp=cmtc(bytes([17,identifier,4,0,a['local_tcid'],b['local_tcid'],0,0]))
            def signal(sender,receiver,raw):return dict(tx=matched(sender,'out',raw,lower=row['start_wall_ns'],upper=start),rx=matched(receiver,'in',raw,lower=row['start_wall_ns'],upper=start))
            negotiation=dict(request=signal(active,passive,req),response=signal(passive,active,resp))
            stamps=[negotiation[k][v]['wall_ns']for k,v in [('request','tx'),('request','rx'),('response','tx'),('response','rx')]]
            if stamps!=sorted(stamps):raise CaptureError('actual dynamic request/response order')
            for key,index in [('tx',passive),('rx',active)]:
                armed=next(e['wall_ns']for e in row['events']if e['kind']=='armed'and e['application']==index)
                if negotiation['response'][key]['wall_ns']>armed:raise CaptureError('actual CMTC response must precede corresponding Ready')
            for p in sdus:
                raw=bytes.fromhex(p['data'])
                if not(row['start_wall_ns']<=p['wall_ns']<=start and raw[:2]==b'\x02\0'and len(raw)>=5 and raw[4]in(16,17)):continue
                for entry in row['owners']:
                    o=entry['owner'];identity=entry['object']
                    if (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],identity['handle']):
                        if (p['record'],p.get('hcc_offset',0),p['direction'],o['bus'],o['device'])not in used:
                            raise CaptureError('unattributed dynamic negotiation before business')
        expected=set()
        for index,app in enumerate(row['applications']):
            for original in app['report']['outgoing']:
                request=bytes.fromhex(original['frame_hex']);reply=request[:28]+b'\1'+request[29:]
                for sender,body in [(index,request),(1-index,reply)]:
                    tcid=row['applications'][sender]['report']['channel_identity']['remote_tcid']
                    frame=bytes([tcid,0])+(len(body)+1).to_bytes(2,'little')+b'\xf1'+body
                    legs.append(dict(tx=matched(sender,'out',frame),rx=matched(1-sender,'in',frame)))
                    expected.add(frame.hex())
        for entry in row['owners']:
            o=entry['owner'];obj=entry['object']
            ids={31}if channel is None else {app['report']['channel_identity'][k]for app in row['applications']for k in ('local_tcid','remote_tcid')}
            actual=[p for p in sdus if (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],obj['handle']) and start<=p['wall_ns']<=end and bytes.fromhex(p['data'])[:1]in[bytes([v])for v in ids]]
            if len(actual)!=len(expected) or any(p['data'] not in expected for p in actual):raise CaptureError('all CUTC31 business packets must be attributed once')
        phase_proof=dict(phase=n,owners=row['owners'],application=check,legs=legs,events=row['events'])
        if negotiation is not None:phase_proof['dynamic_negotiation']=negotiation
        from ws73_benchmark_resources import observations
        resource=observations(row)
        if resource is not None:phase_proof['resource_observations']=resource
        proofs.append(phase_proof)
    if any(RESOURCE_FIELD in row for row in rows):
        if not all(type(row.get(RESOURCE_FIELD))is int and row[RESOURCE_FIELD]==1 for row in rows):raise CaptureError('both resource observation phases required')
    if rows[0]['config']!=rows[1]['config']:raise CaptureError('same requested workload in both physical connection roles required')
    if row_channel(rows[0])!=row_channel(rows[1]):raise CaptureError('same original channel target in both physical roles required')
    result=dict(status='REAL_WS73_LOAD_USB_AND_APPLICATION_OBSERVED_NOT_PERFORMANCE_QUALIFIED',
                mode=rows[0]['config']['mode'],round_trips=sum(len(a['report']['outgoing']) for row in rows for a in row['applications']),
                proofs=proofs,performance_qualified=False,
                remaining=['repeatstablebaseline/traceoverhead/resources','crossclockmapping/per-layer latency','fullperformance/stress/fairness/recovery qualification'])
    if RESOURCE_FIELD in rows[0]:result[RESOURCE_FIELD]=1
    if row_channel(rows[0])is not None:result[CHANNEL_FIELD]=row_channel(rows[0])
    if rows[0]['config']['window']!=WINDOW:result['window']=rows[0]['config']['window']
    if any(rows[0]['config'][k]!=v for k,v in [('count',COUNT),('bytes',SIZE),('interval_us',100000 if rows[0]['config']['mode']=='rate' else 0)]):result['config']=rows[0]['config']
    return result


def verify_role_artifacts(control,evidence):
    """Original root phase bytes/roles,not a substitute for paired data proof."""
    from ws73_application_role import verify_probe
    from ws73_role_snapshot import verify,HELPER
    evidence=Path(evidence);root=evidence/'benchmark-role';finished=json.loads((root/'finished.json').read_text())
    if(set(finished)!={'status','daemon','supervisor','snapshot_contract_version','socket_benchmark_role_contract_version'}or finished['status']!=ROLE_STATUS
        or type(finished['snapshot_contract_version'])is not int or finished['snapshot_contract_version']!=1
        or type(finished['socket_benchmark_role_contract_version'])is not int or finished['socket_benchmark_role_contract_version']!=1
        or finished['daemon']!=control['daemon_before']or control['daemon_before']!=control['daemon_after']or len(control.get('socket_benchmark',[]))!=2):raise CaptureError('complete benchmark root supervisor and unchanged daemon required')
    snapshots=[]
    for phase,row in enumerate(control['socket_benchmark']):
        original=json.loads((root/f'phase-{phase}'/'run.json').read_text())
        if original!=row or not apps_role(row)or row['role_supervisor']!=finished['supervisor']or row['status']!=PENDING:raise CaptureError('original root benchmark phase differs from parent')
        request={k:row[k]for k in request_fields(row)};request.update(status='RUNNING',applications=[],events=[])
        validate_role_request(request,phase)
        verify_probe(row);check_supervision(row);check_report_files(row,evidence)
        snapshots.append(verify(root/f'phase-{phase}',phase=phase,expected_helper=row['tools'][HELPER]['sha256'],kind='benchmark'))
        for app in [row['role_probe'],*row['applications']]:
            if len(app['output_files'])!=2:raise CaptureError('complete original benchmark stdout/stderr paths required')
            for name in app['output_files']:
                relative=Path(name).relative_to('/evidence/benchmark-role/phase-'+str(phase))
                if '..'in relative.parts or relative.suffix not in('.stdout','.stderr'):raise CaptureError('fixed benchmark stream path required')
                if (root/f'phase-{phase}'/relative).read_text()!=app['stdout'if relative.suffix=='.stdout'else'stderr']:raise CaptureError('actual benchmark raw stream differs')
    return dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',version=1,uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=4,report_files=4,phases=2,daemon=finished['daemon'],supervisor=finished['supervisor'],snapshot_files=sum(len(v['files'])for v in snapshots),snapshot_bytes=sum(v['bytes']for v in snapshots),performance_qualified=False,scope='Fixed actual system-bus/apps-only/closed-file supervision,not wire proof/full deployment/stable performance')


def valid_role_supervision(proof):
    try:
        expected=dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',version=1,uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=4,report_files=4,phases=2,performance_qualified=False)
        return(all(type(proof[k])is type(v)and proof[k]==v for k,v in expected.items())
            and all(type(proof[k][f])is int and proof[k][f]>0 for k in('daemon','supervisor')for f in('pid','start_ticks'))
            and type(proof['snapshot_files'])is int and 18<=proof['snapshot_files']<=128
            and type(proof['snapshot_bytes'])is int and 0<proof['snapshot_bytes']<=1024*1024*1024)
    except(KeyError,TypeError):return False


def validate_role_tools(control,root,guest_files):
    for row in control['socket_benchmark']:
        expected=role_tools(root,dynamic=row_channel(row)is not None)
        if not apps_role(row)or row['tools']!=expected:raise CaptureError('exact prepared role tools required')
        for name,record in expected.items():
            actual=role_tool_path(root,name);matches=[v for v in guest_files if Path(v['path']).resolve()==actual]
            if len(matches)!=1 or matches[0]['sha256']!=record['sha256']:raise CaptureError('benchmark actual tool missing from prepared manifest')
