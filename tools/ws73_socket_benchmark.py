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
import ws73_benchmark_ssap as ssap_gate

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
    if type(value)is dict and type(value.get('version'))is int and value['version']in(2,3):
        close=value['version']==3
        if (set(value)!={'version','kind','channels'}or value['kind']!=('dynamic_basic_parallel_close'if close else'dynamic_basic_parallel')
            or type(value['channels'])is not list or len(value['channels'])!=2):
            raise CaptureError('explicit version2 two-channel profile required')
        for group in value['channels']:
            if (type(group)is not dict or set(group)!={'name','route','config'}or type(group.get('route'))is not dict
                or type(group['route'].get('version'))is not int or group['route']['version']!=1):
                raise CaptureError('explicit named channel/config/route required')
            channel_configuration(group['route']);validate_configuration(group['config'])
        active=value['channels'][0]['route']['active_endpoint']
        if value!=parallel_channel(active,close_short=close):raise CaptureError('canonical finite short/long profile required')
        return value
    if (type(value)is not dict or set(value)!={'version','kind','ports','aid','active_endpoint'}
        or type(value['version'])is not int or value['version']!=1 or value['kind']!='dynamic_basic'
        or type(value['ports'])is not list or len(value['ports'])!=2
        or any(type(v)is not int or not 1<=v<=65535 for v in value['ports'])
        or type(value['aid'])is not int or not 1<=value['aid']<=65535
        or type(value['active_endpoint'])is not int or value['active_endpoint']not in(0,1)):
        raise CaptureError('explicit version1 basic dynamic route required')
    return value


def parallel_channel(active=0,*,close_short=False):
    if type(active)is not int or active not in(0,1):raise CaptureError('explicit parallel negotiation role required')
    if type(close_short)is not bool:raise CaptureError('explicit short-close profile required')
    groups=[]
    for name,ports,count,size,window in [('short',[24576,24577],20,61,4),('long',[24578,24579],64 if close_short else 16,2042,8)]:
        route=dict(version=1,kind='dynamic_basic',ports=ports,aid=29441,active_endpoint=active)
        groups.append(dict(name=name,route=route,config=configuration('window',window,count=count,size=size)))
    return dict(version=3 if close_short else 2,kind='dynamic_basic_parallel_close'if close_short else'dynamic_basic_parallel',channels=groups)


def is_parallel(channel):
    return channel is not None and channel.get('version')in(2,3)


def closes_short(channel):
    return channel is not None and channel.get('version')==3


def supervision_version(channel):
    return 3 if closes_short(channel)else 2 if is_parallel(channel)else 1


def parallel_replies(channel):
    channel_configuration(channel)
    if not is_parallel(channel):raise CaptureError('parallel profile required')
    return 2*sum(g['config']['count']for g in channel['channels'])


def requested_channel(args):
    dynamic=getattr(args,'channel_benchmark_dynamic',False)
    parallel=getattr(args,'channel_benchmark_parallel',False)
    close=getattr(args,'channel_benchmark_close_short',False)
    active=getattr(args,'channel_benchmark_active_endpoint',None)
    if type(dynamic)is not bool or type(parallel)is not bool or type(close)is not bool or close and not parallel or (active is not None and(type(active)is not int or active not in(0,1))):
        raise CaptureError('explicit dynamic benchmark selector/role required')
    if parallel:
        if dynamic or requested_configuration(args)!=configuration('window'):
            raise CaptureError('parallel target requires separate default short window workload')
        return channel_configuration(parallel_channel(0 if active is None else active,close_short=close))
    if not dynamic:
        if active is not None:raise CaptureError('channel role requires dynamic benchmark')
        return None
    if not getattr(args,'channel_benchmark',None):raise CaptureError('dynamic target requires benchmark mode')
    return channel_configuration(dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=0 if active is None else active))


def row_channel(row):
    return channel_configuration(row[CHANNEL_FIELD])if CHANNEL_FIELD in row else None


def channel_boot(channel):
    if channel is None:return []
    channel_configuration(channel)
    parallel=is_parallel(channel)
    active=channel['channels'][0]['route']['active_endpoint']if parallel else channel['active_endpoint']
    return ['ws73.benchmark_parallel=1'if parallel else'ws73.benchmark_dynamic=1',f'ws73.benchmark_active={active}']+(['ws73.benchmark_close=short']if closes_short(channel)else[])


def channel_from_boot(words,config):
    prefixes=('ws73.benchmark_dynamic=','ws73.benchmark_parallel=','ws73.benchmark_active=','ws73.benchmark_close=')
    selected=[w for w in words if w.startswith(prefixes)]
    if not selected:return None
    for profile in(1,2,3):
        for active in(0,1):
            candidate=parallel_channel(active,close_short=profile==3)if profile>1 else dict(version=1,kind='dynamic_basic',ports=[24576,24577],aid=29441,active_endpoint=active)
            if selected==channel_boot(candidate):
                if profile>1 and config!=configuration('window'):raise CaptureError('parallel boot requires exact short workload')
                return candidate
    raise CaptureError('one exact original channel boot profile required')


def request_fields(row):
    return ROLE_REQUEST_FIELDS|({RESOURCE_FIELD}if RESOURCE_FIELD in row else set())|({CHANNEL_FIELD}if CHANNEL_FIELD in row else set())|({ssap_gate.FIELD}if ssap_gate.FIELD in row else set())


def channel_groups(row):
    channel=row_channel(row)
    if is_parallel(channel):
        if row['config']!=channel['channels'][0]['config']:raise CaptureError('primary workload differs from parallel target')
        return channel['channels']
    return [dict(name='single',route=channel,config=row['config'])]


def application_count(row):
    return 4 if is_parallel(row_channel(row))else 2


def application_config(row,index):
    if type(index)is not int or not 0<=index<application_count(row):raise CaptureError('bounded original application index required')
    return channel_groups(row)[index//2]['config']


def application_mode(row,index):
    mode=application_config(row,index)['mode']
    return mode if index%2==0 or mode=='duplex'else'peer'


def application_owner(row,index):
    application_config(row,index)
    return row['owners'][index%2]


def release_order(row):
    return [2,3,0,1]if application_count(row)==4 else[0,1]


def application_request(row,index):
    config=application_config(row,index);channel=channel_groups(row)[index//2]['route'];endpoint=index%2
    if channel is None:return None
    mtu=max(249,config['bytes'])
    return dict(version=1,kind='dynamic_basic',source_port=channel['ports'][endpoint],destination_port=channel['ports'][1-endpoint],
                aid=channel['aid'],mtu=mtu,mps=mtu+5,slqi=1,passive=endpoint!=channel['active_endpoint'])


def application_checks(row):
    checks=[load_application_reports(*(a['report']for a in row['applications'][2*i:2*i+2]))for i in range(len(channel_groups(row)))]
    return checks if is_parallel(row_channel(row))else checks[0]


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


def role_tools(root=Path('/'),*,dynamic=False,parallel=False,ssap=False):
    import hashlib
    from ws73_role_snapshot import HELPER,SUPERVISOR
    names=('/bin/slktest','/bin/bus-policy-probe',HELPER,SUPERVISOR,'/usr/share/sparklink/tools/ws73_socket_benchmark.py','/usr/share/sparklink/tools/ws73_benchmark.py','/usr/share/sparklink/tools/ws73_benchmark_timeline.py','/usr/share/sparklink/tools/ws73_benchmark_resources.py')
    if dynamic:names+=('/usr/share/sparklink/tools/ws73_dynamic_channels.py',)
    if parallel:names+=('/usr/share/sparklink/tools/ws73_channel_fairness.py',)
    if ssap:names+=tuple('/usr/share/sparklink/tools/'+n for n in ssap_gate.VERIFIERS)+ssap_gate.RUNTIME
    return {n:dict(sha256=hashlib.sha256(role_tool_path(root,n).read_bytes()).hexdigest(),bytes=role_tool_path(root,n).stat().st_size)for n in names}


def request_tools(row,root=Path('/')):
    """Same typed source profile for producer, root admission and replay."""
    channel=row_channel(row)
    return role_tools(root,dynamic=channel is not None,parallel=is_parallel(channel),ssap=ssap_gate.selected(row)is not None)


def validate_role_sources(package,*,dynamic=False,parallel=False,ssap=False):
    from ws73_north_star import file_record
    here=Path(__file__).resolve().parent
    if type(package.get('socket_benchmark_role_contract_version'))is not int or package['socket_benchmark_role_contract_version']!=1:raise ValueError('fresh apps-only benchmark prepared contract1 required')
    if type(package.get('benchmark_trace_contract_version'))is not int or package['benchmark_trace_contract_version']!=1:raise ValueError('fresh explicit monotonic benchmark trace contract1 required')
    if type(package.get(RESOURCE_FIELD)) is not int or package[RESOURCE_FIELD]!=1:raise ValueError('fresh process-resource benchmark contract1 required')
    names=('ws73_benchmark_resources.py','ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_role_snapshot.py','ws73_application_role.py','ws73_target.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh')
    if dynamic:names+=('ws73_dynamic_channels.py',)
    if parallel:names+=('ws73_channel_fairness.py',)
    if ssap:
        if type(package.get('benchmark_ssap_contract_version'))is not int or package['benchmark_ssap_contract_version']!=2:raise ValueError('fresh concurrent SSAP prepared contract2 required')
        from ws73_application_client import validate_consumer_sources
        validate_consumer_sources(package)
        names+=ssap_gate.VERIFIERS
    for name in names:
        matches=[v for v in package['inputs']if Path(v['path']).name==name]
        if len(matches)!=1 or matches[0]['sha256']!=file_record(here/name)['sha256']:raise ValueError('prepared benchmark role/source closure mismatch: '+name)


def validate_role_request(row,phase,*,live=False):
    extra={RESOURCE_FIELD}if RESOURCE_FIELD in row else set()
    if row_channel(row)is not None:extra.add(CHANNEL_FIELD)
    if ssap_gate.selected(row)is not None:
        extra.add(ssap_gate.FIELD);ssap_gate.workload(row['config'],row_channel(row))
    if (live or RESOURCE_FIELD in row)and(type(row.get(RESOURCE_FIELD))is not int or row[RESOURCE_FIELD]!=1):raise CaptureError('new live resource checkpoint contract required')
    if(type(phase)is not int or phase not in(0,1)or type(row.get('phase'))is not int or row['phase']!=phase or not apps_role(row)
        or set(row)!=ROLE_REQUEST_FIELDS|extra
        or row['applications']!=[]or row['events']!=[]or row['status']!='RUNNING'or row['performance_qualified']is not False):raise CaptureError('fixed empty apps-only benchmark request required')
    validate_configuration(row['config']);validate_application_binary(row['application_tool'])
    channel_groups(row)
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
    if channel is not None:row[CHANNEL_FIELD]=channel
    service=ssap_gate.requested(run.args)
    if service is not None:row[ssap_gate.FIELD]=service
    row['tools']=request_tools(row)
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
    if ssap_gate.from_boot(Path('/proc/cmdline').read_text().split())!=ssap_gate.selected(row):raise CaptureError('concurrent SSAP boot/request mismatch')
    if not apps_role(row):raise CaptureError('live benchmark requires explicit apps-only contract')
    validate_role_request({k:row[k]for k in request_fields(row)},row['phase'],live=True)
    if row['tools']!=request_tools(row)or row['application_tool']!=file_record(Path('/bin/slktest').resolve(strict=True)):
        raise CaptureError('fixed prepared benchmark executables and tools required')
    validate_configuration(row['config']);count=application_count(row);indices=tuple(range(count))
    reports=run.output/'reports';reports.mkdir(mode=0o700);os.chown(reports,1004,1004)
    processes=[None]*count;row['applications']=[None]*count
    buffers={};output={};duplicates=set();selector=selectors.DefaultSelector()
    channel=row_channel(row);observed={kind:set()for kind in ('staged','armed','quiescent')}
    def event(kind,index,**values):
        row['events'].append(dict(kind=kind,application=index,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),**values))
    def wait_marker(kind,seconds,selected=indices,*,original_deadline=None):
        deadline=time.monotonic()+seconds
        if original_deadline is not None:deadline=min(deadline,original_deadline)
        while not set(selected)<=observed[kind]:
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
                    config=application_config(row,index);window=config['window']
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
    def release(kind,selected=indices):
        for i in release_order(row):
            if i not in selected:continue
            proc,_=processes[i]
            before_wall=time.time_ns();before_mono=time.monotonic_ns()
            proc.stdin.write((kind+'\n').encode());proc.stdin.flush()
            event(kind,i,before_wall_ns=before_wall,before_monotonic_ns=before_mono)
    def collect_ends(selected,deadline):
        for i in selected:
            proc,app=processes[i]
            proc.stdin.close();proc.wait(timeout=max(.001,deadline-time.monotonic()))
            selector.unregister(proc.stdout)
            tail=proc.stdout.read(65537-len(output[i]));output[i]+=tail
            if len(output[i])>65536:raise CaptureError('benchmark output byte budget')
            app.update(exit=proc.returncode,end_wall_ns=time.time_ns(),stdout=output[i].decode(),stderr=Path(app['stderr_path']).read_text())
            if proc.returncode:raise CaptureError('actual slktest failed:'+app['stderr'])
            report,record=read_report(app['report_path'],expected_uid=1004);app['report']=report;app['report_file']=record
    try:
        with ExitStack() as files:
            order=[i for passive in(True,False)for i in indices if application_request(row,i)['passive']==passive]if channel is not None else list(indices)
            for i in order:
                entry=application_owner(row,i);config=application_config(row,i);window=config['window']
                appmode=application_mode(row,i)
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
            # Plain load keeps sparse IO receipts in memory until quiescent.
            # The explicit SSAP correctness profile records actual SDK work
            # during load and cannot be called a low-perturbation measurement.
            from ws73_benchmark_timeline import phase_marker
            row['trace_observation']=phase_marker(row['phase'],'BEGIN')
            release('start')
            business_deadline=time.monotonic()+620
            if ssap_gate.selected(row)is not None:ssap_gate.execute(run,row)
            if closes_short(channel):
                wait_marker('quiescent',620,(0,1),original_deadline=business_deadline)
                if observed['quiescent']&{2,3}:raise CaptureError('long applications already quiescent before short close')
                for i in(0,1):
                    proc,app=processes[i];app['process_resources']['after']=collect(proc.pid,row['application_tool']['path'])
                release('finish',(0,1))
                collect_ends((0,1),time.monotonic()+15)
                row['closed_short']=[dict(application=i,pid=row['applications'][i]['pid'],exit=row['applications'][i]['exit'],reaped_wall_ns=row['applications'][i]['end_wall_ns'])for i in(0,1)]
            wait_marker('quiescent',620,original_deadline=business_deadline)
            end=phase_marker(row['phase'],'END')
            if {k:v for k,v in end.items()if k!='marker'}!={k:v for k,v in row['trace_observation'].items()if k!='marker'}:raise CaptureError('trace configuration changed during business phase')
            row['trace_observation']['end_marker']=end['marker']
            remaining=(2,3)if closes_short(channel)else indices
            for i in remaining:
                proc,app=processes[i];app['process_resources']['after']=collect(proc.pid,row['application_tool']['path'])
            release('finish',remaining)
            deadline=time.monotonic()+15
            collect_ends(remaining,deadline)
            row['end_wall_ns']=time.time_ns()
            check_supervision(row)
            row['application_check']=application_checks(row)
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
    config=row['config']
    validate_configuration(config)
    count=application_count(row);indices=set(range(count))
    if len(row['applications'])!=count:
        raise CaptureError('exact bounded Native benchmark workload required')
    validate_application_binary(row['application_tool'])
    from ws73_benchmark_resources import observations
    if RESOURCE_FIELD in row and not apps_role(row):raise CaptureError('resource checkpoint requires apps-only role')
    observations(row)
    channel=row_channel(row)
    if ssap_gate.selected(row)is not None:
        ssap_gate.workload(config,channel);ssap_gate.streams(row)
        start=max(e['wall_ns']for e in row['events']if e['kind']=='start')
        finish=min(e['before_wall_ns']for e in row['events']if e['kind']=='finish')
        if not start<=row[ssap_gate.SOURCE]['start_wall_ns']<=row[ssap_gate.SOURCE]['end_wall_ns']<=finish:raise CaptureError('actual SDK source between original start/finish barriers required')
        if any(app['report']['channel_identity'][k]==10 for app in row['applications']for k in ('local_tcid','remote_tcid')):raise CaptureError('application channel and SSAP SMTC must be distinct')
    else:ssap_gate.streams(row)
    if channel is not None and not apps_role(row):raise CaptureError('dynamic measurement requires apps-only role')
    all_events=row['events'];events=[e for e in all_events if e['kind']!='staged']
    if channel is None and events!=all_events:raise CaptureError('basic CUTC has no dynamic staging')
    stages=[e for e in all_events if e['kind']=='staged']
    if channel is not None:
        if len(stages)!=count or {e['application']for e in stages}!=indices:raise CaptureError('all exact dynamic staged receipts required')
        for group_index,group in enumerate(channel_groups(row)):
            active=2*group_index+group['route']['active_endpoint'];passive=2*group_index+1-group['route']['active_endpoint']
            staged=next(e for e in stages if e['application']==passive)
            if staged['wall_ns']>row['applications'][active]['start_wall_ns']:raise CaptureError('passive staged before active process creation required')
    if len(events)!=4*count or any(type(e.get('application'))is not int for e in all_events):raise CaptureError('complete typed arm/start/quiescent/finish receipts required')
    if count==4:
        pids=[a.get('pid')for a in row['applications']]
        if len(set(pids))!=4 or any(type(p)is not int or p<=0 for p in pids):raise CaptureError('four distinct actual child processes required')
        for endpoint in(0,1):
            infos=[row['applications'][2*g+endpoint]['report']['channel_identity']for g in range(2)]
            if any(len({i[k]for i in infos})!=2 for k in ('local_tcid','remote_tcid')):raise CaptureError('distinct per-channel actual TCIDs required')
    for clock in ['wall_ns','monotonic_ns']:
        stamps=[e[clock] for e in all_events]
        if any(type(v) is not int for v in stamps) or stamps!=sorted(stamps):raise CaptureError('same guest supervisor clock order')
    close=closes_short(channel)
    for offset,kind in enumerate(['armed','start']if close else['armed','start','quiescent','finish']):
        chunk=events[offset*count:offset*count+count]
        if {e['application'] for e in chunk}!=indices or any(e['kind']!=kind for e in chunk):raise CaptureError('global barrier order before any release')
    if close:
        for i in indices:
            if [e['kind']for e in events if e['application']==i]!=['armed','start','quiescent','finish']:
                raise CaptureError('each endpoint must quiesce before its own final release')
        closed=row.get('closed_short')
        if (type(closed)is not list or len(closed)!=2
            or any(type(v)is not dict or set(v)!={'application','pid','exit','reaped_wall_ns'}for v in closed)):
            raise CaptureError('both actual short processes must be reaped')
        for i,item in enumerate(closed):
            app=row['applications'][i]
            finished=next(e for e in events if e['application']==i and e['kind']=='finish')
            if (any(type(item[k])is not int for k in item)or item['application']!=i or item['pid']!=app['pid']or item['exit']!=0
                or item['reaped_wall_ns']!=app['end_wall_ns']or not finished['wall_ns']<=item['reaped_wall_ns']
                <min(e['wall_ns']for e in events if e['application']in(2,3)and e['kind']=='quiescent')):
                raise CaptureError('short final release must precede continuing long application completion')
    elif 'closed_short'in row:raise CaptureError('early close cannot change the original global finish contract')
    for i,app in enumerate(row['applications']):
        config=application_config(row,i);window=config['window'];expected=application_mode(row,i)
        requested=application_request(row,i)
        if app['mode']!=expected or app['args']!=arguments(row['application_tool']['path'],application_owner(row,i),expected,app['report_path'],window,count=config['count'],size=config['bytes'],interval_us=config['interval_us'],channel=requested):raise CaptureError('actual slktest argv/mode mismatch')
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
            preceding=(max((v for v in events if v['kind']=='quiescent'and v['application']//2==i//2),key=lambda v:v['wall_ns'])
                       if close and kind=='finish'else events[(['armed','start','quiescent','finish'].index(kind)-1)*count+count-1])
            if not preceding['wall_ns']<=e['before_wall_ns']<=e['wall_ns']:raise CaptureError('all endpoints observed before control write')
            if not max(own['monotonic_ns'],preceding['monotonic_ns'])<=e['before_monotonic_ns']<=e['monotonic_ns']<own['monotonic_ns']+limit*1_000_000_000:raise CaptureError('bounded original supervisory input')
        identity=app['report']['channel_identity'];entry=application_owner(row,i);owner=entry['owner'];obj=entry['object']
        if any(identity[k]!=v for k,v in [('controller',owner['index']),('generation',owner['generation']),('lifetime',obj['lifetime']),('handle',obj['handle'])]):raise CaptureError('report/current registration connection identity')
        cfg=app['report']['config'];expected_cfg=dict(config,mode=expected,interval_us=config['interval_us'] if expected=='rate' else 0)
        if cfg!=expected_cfg:raise CaptureError('actual report workload differs from request')
        armed=next(e['wall_ns']for e in events if e['kind']=='armed'and e['application']==i)if count==4 else events[0]['wall_ns']
        if not row['start_wall_ns']<=app['start_wall_ns']<=armed<app['end_wall_ns']<=row['end_wall_ns']:raise CaptureError('original process observation window')


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
    if type(rows)is list and any(apps_role(row)for row in rows):
        verify_role_artifacts(run,share)
    proof=_match_payloads(run,capture,share)
    return dict(status='REAL_WS73_LOAD_USB_AND_APPLICATION_OBSERVED_NOT_PERFORMANCE_QUALIFIED',**proof)


def diagnose_closed_payloads(run,capture,share):
    """Closed app/USB component only;never complete controller acceptance.

    No daemon-after fact is invented when the control runner fails. Reuse the
    same closed phase and payload matchers, but issue no full role/proof status.
    The normal corroborate entry still requires original daemon completion.
    """
    facts=_closed_role_facts(run,share)
    proof=_match_payloads(run,capture,share)
    return dict(status='DIAGNOSTIC_CLOSED_PAYLOAD_COMPONENT_ONLY',
                control_completion='NOT_VALIDATED_BY_THIS_DIAGNOSTIC',
                overall_run_acceptance=False,closed_role_facts=facts,**proof)


def _match_payloads(run,capture,share):
    rows=run.get('socket_benchmark')
    if type(rows) is not list or len(rows)!=2:raise CaptureError('both actual connection-role benchmark phases required')
    roles=[apps_role(row)for row in rows]
    if any(roles):
        if not all(roles):raise CaptureError('two matching benchmark role phases required')
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
        groups=[]
        start=next(e['before_wall_ns'] for e in row['events'] if e['kind']=='start')
        end=max(e['wall_ns'] for e in row['events'] if e['kind']=='quiescent')
        def matched(index,direction,frame,*,lower=start,upper=end):
            entry=row['owners'][index];owner=entry['owner'];obj=entry['object']
            found=[p for p in indexed.get((owner['bus'],owner['device'],obj['handle'],direction,frame.hex()),[]) if lower<=p['wall_ns']<=upper]
            if len(found)!=1:raise CaptureError('one exact opposite USB TX/RX for each benchmark business frame')
            packet=found[0];key=(packet['record'],packet.get('hcc_offset',0),direction,owner['bus'],owner['device'])
            if key in used:raise CaptureError('benchmark evidence reused')
            used.add(key);return packet
        channel=row_channel(row)
        for group_index,group in enumerate(channel_groups(row)):
            base=2*group_index;apps=row['applications'][base:base+2];route=group['route']
            check=load_application_reports(*(app['report']for app in apps));legs=[];negotiation=None
            if route is not None:
                negotiation=match_negotiation(row,apps,route,base,sdus,start,matched)
            expected=set()
            for index,app in enumerate(apps):
                for original in app['report']['outgoing']:
                    request=bytes.fromhex(original['frame_hex']);reply=request[:28]+b'\1'+request[29:]
                    for sender,body in [(index,request),(1-index,reply)]:
                        tcid=apps[sender]['report']['channel_identity']['remote_tcid']
                        frame=bytes([tcid,0])+(len(body)+1).to_bytes(2,'little')+b'\xf1'+body
                        legs.append(dict(tx=matched(sender,'out',frame),rx=matched(1-sender,'in',frame)))
                        expected.add(frame.hex())
            for endpoint,entry in enumerate(row['owners']):
                o=entry['owner'];obj=entry['object']
                ids={31}if route is None else {app['report']['channel_identity'][k]for app in apps for k in ('local_tcid','remote_tcid')}
                actual=[p for p in sdus if (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],obj['handle']) and start<=p['wall_ns']<=end and bytes.fromhex(p['data'])[:1]in[bytes([v])for v in ids]]
                if is_parallel(channel):
                    identity=apps[endpoint]['report']['channel_identity']
                    actual=[p for p in actual if bytes.fromhex(p['data'])[0]==identity['remote_tcid'if p['direction']=='out'else'local_tcid']]
                if len(actual)!=len(expected) or any(p['data'] not in expected for p in actual):raise CaptureError('all selected-channel business packets must be attributed once')
            result=dict(name=group['name'],config=group['config'],application=check,legs=legs)
            if is_parallel(channel)and group['name']=='long'and any(len(leg[k]['fragments'])<2 for leg in legs for k in('tx','rx')):
                raise CaptureError('actual PB-fragmented long messages required on both USB legs')
            if negotiation is not None:result['dynamic_negotiation']=negotiation
            if closes_short(channel)and group['name']=='short':result['close']=match_channel_close(row,apps,base,sdus,matched)
            groups.append(result)
        if channel is not None:
            # All channels must be matched before rejecting unowned signaling.
            # A shared CMTC queue is never consumed independently by each app.
            for p in sdus:
                raw=bytes.fromhex(p['data'])
                if not(row['start_wall_ns']<=p['wall_ns']<=start and raw[:2]==b'\x02\0'and len(raw)>=5 and raw[4]in(16,17)):continue
                for entry in row['owners']:
                    o=entry['owner'];identity=entry['object']
                    if (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],identity['handle']):
                        if (p['record'],p.get('hcc_offset',0),p['direction'],o['bus'],o['device'])not in used:
                            raise CaptureError('unattributed dynamic negotiation before business')
        phase_proof=dict(phase=n,owners=row['owners'],legs=[leg for group in groups for leg in group['legs']],events=row['events'])
        if is_parallel(channel):
            phase_proof.update(channels=groups,concurrent_progress=load_progress(groups))
            if closes_short(channel):
                phase_proof['closed_short']=row['closed_short']
                phase_proof['close_continuity']=close_continuity(groups,row['closed_short'])
        else:
            phase_proof['application']=groups[0]['application']
            if 'dynamic_negotiation'in groups[0]:phase_proof['dynamic_negotiation']=groups[0]['dynamic_negotiation']
        from ws73_benchmark_resources import observations
        resource=observations(row)
        if resource is not None:phase_proof['resource_observations']=resource
        proofs.append(phase_proof)
    if any(RESOURCE_FIELD in row for row in rows):
        if not all(type(row.get(RESOURCE_FIELD))is int and row[RESOURCE_FIELD]==1 for row in rows):raise CaptureError('both resource observation phases required')
    if rows[0]['config']!=rows[1]['config']:raise CaptureError('same requested workload in both physical connection roles required')
    if row_channel(rows[0])!=row_channel(rows[1]):raise CaptureError('same original channel target in both physical roles required')
    if ssap_gate.selected(rows[0])!=ssap_gate.selected(rows[1]):raise CaptureError('same original concurrent SSAP profile in both roles required')
    service=ssap_gate.corroborate(rows,capture,proofs)if ssap_gate.selected(rows[0])is not None else None
    result=dict(mode=rows[0]['config']['mode'],round_trips=sum(len(a['report']['outgoing']) for row in rows for a in row['applications']),
                proofs=proofs,performance_qualified=False,
                remaining=['repeatstablebaseline/traceoverhead/resources','crossclockmapping/per-layer latency','fullperformance/stress/fairness/recovery qualification'])
    if RESOURCE_FIELD in rows[0]:result[RESOURCE_FIELD]=1
    if row_channel(rows[0])is not None:result[CHANNEL_FIELD]=row_channel(rows[0])
    if service is not None:result.update({ssap_gate.FIELD:ssap_gate.selected(rows[0]),'ssap':service})
    if is_parallel(row_channel(rows[0])):result['full_fairness_acceptance']=False
    if closes_short(row_channel(rows[0])):result['channel_close_isolation_acceptance']=True
    if rows[0]['config']['window']!=WINDOW:result['window']=rows[0]['config']['window']
    if any(rows[0]['config'][k]!=v for k,v in [('count',COUNT),('bytes',SIZE),('interval_us',100000 if rows[0]['config']['mode']=='rate' else 0)]):result['config']=rows[0]['config']
    return result


def match_negotiation(row,apps,channel,base,sdus,start,matched):
    """Same CMTC matcher for each pair; the caller owns unique capture use."""
    from ws73_dynamic_channels import cmtc,request
    active=channel['active_endpoint'];passive=1-active
    a=apps[active]['report']['channel_identity'];b=apps[passive]['report']['channel_identity']
    owner=row['owners'][active]['owner'];obj=row['owners'][active]['object'];requested=application_request(row,base+active)
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
        armed=next(e['wall_ns']for e in row['events']if e['kind']=='armed'and e['application']==base+index)
        if negotiation['response'][key]['wall_ns']>armed:raise CaptureError('actual CMTC response must precede corresponding Ready')
    return negotiation


def load_progress(groups):
    """Read-only view for the existing captured short/long progress oracle."""
    from ws73_channel_fairness import concurrent_progress
    streams=[]
    for group in groups:
        streams.append([dict(leg,role='initiator'if i%2==0 else'peer',sequence=i//2)for i,leg in enumerate(group['legs'])])
    return concurrent_progress(*streams,short_count=groups[0]['config']['count'],long_count=groups[1]['config']['count'])


def match_channel_close(row,apps,base,sdus,matched):
    """Actual CMTC exchange for the final app release, same capture ownership."""
    from ws73_dynamic_channels import cmtc
    closes=[]
    for endpoint,app in enumerate(apps):
        o=row['owners'][endpoint]['owner'];obj=row['owners'][endpoint]['object'];identity=app['report']['channel_identity']
        local,remote=identity['local_tcid'],identity['remote_tcid']
        first=next(e['before_wall_ns']for e in row['events']if e['application']==base+endpoint and e['kind']=='finish')
        reqs=[p for p in sdus if(p['bus'],p['device'],p['handle'],p['direction'])==(o['bus'],o['device'],obj['handle'],'out')
              and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns']and len(bytes.fromhex(p['data']))==10
              and bytes.fromhex(p['data'])[:2]==b'\x02\0'and bytes.fromhex(p['data'])[4]==18 and bytes.fromhex(p['data'])[8:]==bytes([local,remote])]
        if len(reqs)>1:raise CaptureError('duplicate close outside this bounded profile')
        for packet in reqs:
            raw=bytes.fromhex(packet['data']);identifier=raw[5]
            if packet['wall_ns']<first:raise CaptureError('channel close precedes its actual final release')
            def signal(sender,receiver,value):
                return dict(tx=matched(sender,'out',value,lower=first,upper=row['end_wall_ns']),rx=matched(receiver,'in',value,lower=first,upper=row['end_wall_ns']))
            result=dict(request=signal(endpoint,1-endpoint,raw),response=signal(1-endpoint,endpoint,cmtc(bytes([19,identifier,3,0,local,remote,0]))))
            stamps=[result[k][v]['wall_ns']for k,v in [('request','tx'),('request','rx'),('response','tx'),('response','rx')]]
            if stamps!=sorted(stamps):raise CaptureError('actual close request/response order required')
            closes.append(result)
    if not closes:raise CaptureError('actual final channel close exchange missing')
    return closes


def close_continuity(groups,closed):
    """Peer-validated new request/reply after wire close AND short process exit.

    This is a finite capture/closed-report observation, not a callback drain,
    NOCP truth, safe reuse, reliable mode or latency proof.
    """
    if len(groups)!=2 or type(closed)is not list or len(closed)!=2:raise CaptureError('two channels and closed short processes required')
    if any(type(v)is not dict or set(v)!={'application','pid','exit','reaped_wall_ns'}for v in closed):raise CaptureError('original short close receipt shape required')
    for i,v in enumerate(closed):
        if any(type(n)is not int for n in v.values())or v['application']!=i or v['pid']<=0 or v['exit']!=0 or v['reaped_wall_ns']<=0:raise CaptureError('original successful short exits required')
    short,long=groups;closes=short['close']
    if type(closes)is not list or not 1<=len(closes)<=2:raise CaptureError('bounded short close exchange required')
    first=min(c['request']['tx']['wall_ns']for c in closes)
    last=max(c['response']['rx']['wall_ns']for c in closes)
    barrier=max(last,max(v['reaped_wall_ns']for v in closed))
    before=[];after=[]
    if len(long['legs'])%2:raise CaptureError('complete long request/reply pairs required')
    for i in range(0,len(long['legs']),2):
        pair=long['legs'][i:i+2]
        if all(leg[k]['wall_ns']<first for leg in pair for k in('tx','rx')):before.append(i//2)
        if all(leg[k]['fragments'][0]['wall_ns']>barrier for leg in pair for k in('tx','rx')):after.append(i//2)
    if not before or not after:raise CaptureError('actual long peer replies required before and after short wire close and final process exit')
    return dict(status='SHORT_CHANNEL_CLOSED_LONG_PEER_REPLIES_CONTINUE',wire_close_ns=[first,last],after_barrier_wall_ns=barrier,
                before_reply_sequences=before,after_reply_sequences=after,callback_drain_proved=False,nocp_accuracy_proved=False,safe_reuse=False)


def valid_parallel_summary(proof,channel,config,supervision):
    """Closed summary shape; paired raw evidence is checked by corroborate."""
    try:
        if not is_parallel(channel)or channel_configuration(channel)!=row_channel(proof)or config!=configuration('window'):return False
        if not valid_role_supervision(supervision)or row_channel(supervision)!=channel:return False
        if proof.get('full_fairness_acceptance')is not False or type(proof.get('round_trips'))is not int or proof['round_trips']!=parallel_replies(channel):return False
        close=closes_short(channel)
        if proof.get('channel_close_isolation_acceptance',False)is not close:return False
        phases=proof['proofs']
        if type(phases)is not list or len(phases)!=2:return False
        for n,phase in enumerate(phases):
            groups=phase['channels']
            if type(phase['phase'])is not int or phase['phase']!=n or type(groups)is not list or len(groups)!=2 or 'application'in phase or 'dynamic_negotiation'in phase:return False
            for g,(group,target)in enumerate(zip(groups,channel['channels'])):
                c=target['config'];app=group['application'];signal=group['dynamic_negotiation']
                validate_configuration(group['config'])
                if group['name']!=target['name']or group['config']!=c or type(group['legs'])is not list or len(group['legs'])!=2*c['count']:return False
                if g==1 and any(len(leg[k]['fragments'])<2 for leg in group['legs']for k in('tx','rx')):return False
                if (app.get('status')!='LOAD_APPLICATION_REPORTS_CONSISTENT_NOT_QUALIFIED'or app.get('performance_qualified')is not False
                    or app.get('fixture')is not False or app.get('messages')!=[c['count'],0]):return False
                expected=[application_request(dict(config=config,benchmark_channel_request=channel),2*g+i)for i in(0,1)]
                if app.get('channel_requests')!=expected or set(signal)!={'request','response'}or any(set(signal[k])!={'tx','rx'}for k in signal):return False
            if phase['legs']!=[leg for group in groups for leg in group['legs']]:return False
            if phase['concurrent_progress']!=load_progress(groups):return False
            if close:
                if phase['close_continuity']!=close_continuity(groups,phase['closed_short']):return False
            elif 'close_continuity'in phase or 'closed_short'in phase:return False
        return True
    except(KeyError,TypeError,ValueError,AttributeError):return False



def verify_role_artifacts(control,evidence):
    """Complete original control/daemon scope,not a partial diagnostic."""
    facts=_closed_role_facts(control,evidence)
    if control['daemon_after']!=facts['daemon']:
        raise CaptureError('complete benchmark unchanged daemon required')
    return dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',**facts,
                scope='Fixed actual system-bus/apps-only/closed-file supervision,not wire proof/full deployment/stable performance')


def _closed_role_facts(control,evidence):
    """Original root phase bytes/roles,not a substitute for paired data proof."""
    from ws73_application_role import verify_probe
    from ws73_role_snapshot import verify,HELPER
    evidence=Path(evidence);root=evidence/'benchmark-role';finished=json.loads((root/'finished.json').read_text())
    if(set(finished)!={'status','daemon','supervisor','snapshot_contract_version','socket_benchmark_role_contract_version'}or finished['status']!=ROLE_STATUS
        or type(finished['snapshot_contract_version'])is not int or finished['snapshot_contract_version']!=1
        or type(finished['socket_benchmark_role_contract_version'])is not int or finished['socket_benchmark_role_contract_version']!=1
        or finished['daemon']!=control['daemon_before']or len(control.get('socket_benchmark',[]))!=2):raise CaptureError('closed benchmark root phases and recorded daemon required')
    snapshots=[];channels=[row_channel(row)for row in control['socket_benchmark']]
    if channels[0]!=channels[1]:raise CaptureError('one original channel profile for both closed phases required')
    for phase,row in enumerate(control['socket_benchmark']):
        original=json.loads((root/f'phase-{phase}'/'run.json').read_text())
        if original!=row or not apps_role(row)or row['role_supervisor']!=finished['supervisor']or row['status']!=PENDING:raise CaptureError('original root benchmark phase differs from parent')
        request={k:row[k]for k in request_fields(row)};request.update(status='RUNNING',applications=[],events=[])
        validate_role_request(request,phase)
        verify_probe(row);check_supervision(row);check_report_files(row,evidence)
        snapshots.append(verify(root/f'phase-{phase}',phase=phase,expected_helper=row['tools'][HELPER]['sha256'],kind='benchmark'))
        for app in [row['role_probe'],*row['applications'],*ssap_gate.streams(row)]:
            if len(app['output_files'])!=2:raise CaptureError('complete original benchmark stdout/stderr paths required')
            for name in app['output_files']:
                relative=Path(name).relative_to('/evidence/benchmark-role/phase-'+str(phase))
                if '..'in relative.parts or relative.suffix not in('.stdout','.stderr'):raise CaptureError('fixed benchmark stream path required')
                if (root/f'phase-{phase}'/relative).read_text()!=app['stdout'if relative.suffix=='.stdout'else'stderr']:raise CaptureError('actual benchmark raw stream differs')
    parallel=is_parallel(channels[0]);count=8 if parallel else 4
    result=dict(version=supervision_version(channels[0]),uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=count,report_files=count,phases=2,daemon=finished['daemon'],supervisor=finished['supervisor'],snapshot_files=sum(len(v['files'])for v in snapshots),snapshot_bytes=sum(v['bytes']for v in snapshots),performance_qualified=False)
    if parallel:result[CHANNEL_FIELD]=channels[0]
    service=ssap_gate.selected(control['socket_benchmark'][0])
    if any(ssap_gate.selected(row)!=service for row in control['socket_benchmark']):raise CaptureError('same actual closed service profile required')
    if service is not None:result.update({ssap_gate.FIELD:service,'ssap_client_processes':48,'ssap_provider_processes':4})
    return result


def valid_role_supervision(proof):
    try:
        channel=row_channel(proof);parallel=is_parallel(channel);count=8 if parallel else 4
        service=ssap_gate.selected(proof)
        if service is not None and any(type(proof.get(k))is not int or proof[k]!=v for k,v in dict(ssap_client_processes=48,ssap_provider_processes=4).items()):return False
        if service is None and any(k in proof for k in ('ssap_client_processes','ssap_provider_processes')):return False
        if channel is not None and not parallel:return False
        expected=dict(status='ACTUAL_ROOT_BENCHMARK_APPS_ONLY_PHASES_CHECKED',version=supervision_version(channel),uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=count,report_files=count,phases=2,performance_qualified=False)
        return(all(type(proof[k])is type(v)and proof[k]==v for k,v in expected.items())
            and all(type(proof[k][f])is int and proof[k][f]>0 for k in('daemon','supervisor')for f in('pid','start_ticks'))
            and type(proof['snapshot_files'])is int and (30 if parallel else 18)<=proof['snapshot_files']<=128
            and type(proof['snapshot_bytes'])is int and 0<proof['snapshot_bytes']<=1024*1024*1024)
    except(KeyError,TypeError,ValueError):return False


def validate_role_tools(control,root,guest_files):
    for row in control['socket_benchmark']:
        expected=request_tools(row,root)
        if not apps_role(row)or row['tools']!=expected:raise CaptureError('exact prepared role tools required')
        for name,record in expected.items():
            actual=role_tool_path(root,name);matches=[v for v in guest_files if Path(v['path']).resolve()==actual]
            if len(matches)!=1 or matches[0]['sha256']!=record['sha256']:raise CaptureError('benchmark actual tool missing from prepared manifest')
