# SPDX-License-Identifier: GPL-2.0-only
"""Finite VM apps-only discovery gate, using the actual SDK/slctl and USB oracle.

The existing ordinary controller runner drives the advertiser. This root-only
test supervisor can launch only two fixed UID1004 slctl readers, never a Host,
arbitrary command, Native operation or installed privilege service. A positive
run selects explicit release or caller process loss. TTL/management cancellation
remain separate gates. Killing a reader is a controlled owner-loss test, never
natural device recovery or evidence that all process/fd lifetimes are qualified.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import traceback

from ws73_application_client import process_identity
from ws73_application_role import read_json, require_vm
from ws73_capture import CaptureError, command_reply, marker_data
from ws73_north_star import daemon_identity, file_record, parse_result
from ws73_daemon_hold import Invocation

ROOT = Path('/evidence/discovery-role')
INPUT = Path('/evidence/application/passthrough-control')
SESSION = re.compile(r'DiscoverySession: id=([1-9][0-9]*) path=(/org/sparklink/slk[0-9]+_g[1-9][0-9]*) state=active source=broker')
REPORT = re.compile(r'DiscoveryReport: session=([1-9][0-9]*) generation=([1-9][0-9]*) sequence=([1-9][0-9]*) address_type=([0-9]+) address=([0-9a-f]{12}) rssi=(-?[0-9]+) data=([0-9a-f]+)')
RELEASE = re.compile(r'DiscoveryReleased: session=([1-9][0-9]*) last_physical_stop_confirmed=(false|true)')
LEASE = re.compile(r'DiscoveryLease: session=([1-9][0-9]*) caller=(:[0-9]+\.[0-9]+) owner=(:[0-9]+\.[0-9]+) lease_ms=(4000|12000) before_wall_ns=([1-9][0-9]*) active_wall_ns=([1-9][0-9]*)')
EXPIRED = re.compile(r'DiscoveryExpired: session=([1-9][0-9]*) caller_present=true owner_same=true read_error=org\.freedesktop\.DBus\.Error\.UnknownObject observed_wall_ns=([1-9][0-9]*)')
LEASE_EXIT = re.compile(r'DiscoveryLeaseExit: session=([1-9][0-9]*) caller_present=true owner_same=true close_error=org\.freedesktop\.DBus\.Error\.UnknownObject')
CASES = ('release', 'owner-loss', 'ttl', 'sdk-release')


def case(row):
    value = row.get('termination', 'release')
    if value not in CASES:raise CaptureError('explicit supported discovery termination required')
    return value


def departure_key(row):
    return {'release':'first_released','sdk-release':'first_released','owner-loss':'first_lost','ttl':'first_expired'}[case(row)]


def output_status(row):
    if case(row)=='ttl':return 'TTL_OUTPUTS_CHECKED_EVIDENCE_PENDING'
    return 'OWNER_LOSS_OUTPUTS_CHECKED_EVIDENCE_PENDING' if case(row) == 'owner-loss' else 'EXPLICIT_RELEASE_OUTPUTS_CHECKED'


def finished_status(row):
    if case(row)=='ttl':return 'TWO_TTL_PHASES_COMPLETED'
    return 'TWO_OWNER_LOSS_PHASES_COMPLETED' if case(row) == 'owner-loss' else 'TWO_EXPLICIT_RELEASE_PHASES_COMPLETED'


def boot_case(tokens):
    values=[t for t in tokens if t.startswith('ws73.application_discovery_case=')]
    if not values:return 'release'
    if len(values)!=1 or values[0].split('=',1)[1] not in ('owner-loss','ttl','sdk-release') or 'ws73.application_discovery=1' not in tokens:
        raise CaptureError('one explicit lifecycle boot selection requires discovery gate')
    return values[0].split('=',1)[1]


def supervision_summary(variant):
    if variant not in CASES:raise CaptureError('unknown discovery supervision case')
    result=dict(status='ORIGINAL_DISCOVERY_ROLE_FILES_CHECKED',uid=1004,phases=2)
    if variant!='release':result['termination']=variant
    return result


def requested(args):
    variant=getattr(args,'application_discovery_case','release')
    if variant not in CASES:raise CaptureError('unknown discovery termination')
    if not getattr(args,'application_discovery_verify',False):
        if variant != 'release':raise CaptureError('lifecycle case requires explicit application discovery gate')
        return False
    allowed = {'passthrough','qmp_hotplug','connection_verify','application_discovery_verify',
               'channel_socket_verify','channel_socket_boundaries'}
    if (not (getattr(args,'passthrough',False) or getattr(args,'qmp_hotplug',False)) or
            not getattr(args,'connection_verify',False) or len(getattr(args,'ports',[])) != 2 or
            any(type(v) is bool and v and k not in allowed for k,v in vars(args).items()) or
            any(getattr(args,k,None) for k in ['security_agent','native_controller_return','channel_benchmark',
                'managed_partial_case','managed_connected_case','managed_connected_reply','managed_real_later_step','daemon_hold_case']) or
            getattr(args,'connection_advertising',None) != 'negotiable-t'):
        # SDK110's source-bound connection/business baseline is negotiable-T.
        # Fixed-T is a separate unqualified contrast, never an implicit fallback.
        raise CaptureError('shared discovery requires explicit negotiable-t in a separate two-device real connection/preservation VM')
    return True


def validate_tool(tool,root=None,guest_files=None):
    if (set(tool) != {'path','sha256'} or
            not re.fullmatch(r'/bin/slctl|/usr/libexec/opensparklink/native-lab/[0-9a-f]{12}/slctl',tool['path']) or
            not re.fullmatch('[0-9a-f]{64}',tool['sha256'])):
        raise CaptureError('fixed actual slctl artifact only; no arbitrary command')
    if root is not None:
        root=Path(root).resolve(strict=True)
        if (root/'bin/slctl').is_symlink():
            # Reuse the qualified directory gate's absolute guest-alias
            # mapping; resolving /bin's absolute link in the host is wrong.
            from ws73_controller_directory import staged_program
            if staged_program(root,guest_files)!=tool:
                raise CaptureError('actual slctl differs from sealed prepared image')
        else:
            from ws73_security_cli import validate_binary
            if tool['path']!='/bin/slctl':raise CaptureError('slctl alias differs from actual executed bundle binary')
            validate_binary(tool,root,guest_files)


def validate_request(row, phase):
    expected = {'phase', 'scanner', 'advertiser', 'markers', 'tool', 'status'}
    if 'termination' in row:expected.add('termination')
    if case(row)=='ttl':expected.add('probe');validate_probe(row.get('probe',{}))
    if case(row)=='sdk-release':expected.add('clients');validate_sdk_clients(row.get('clients',{}))
    case(row)
    if (set(row) != expected or
            type(phase) is not int or phase not in (0, 1) or row['phase'] != phase or
            type(row['phase']) is not int or row['status'] != 'REQUESTED'):
        raise CaptureError('two ordered fixed discovery requests only')
    for owner in [row['scanner'], row['advertiser']]:
        if (type(owner.get('index')) is not int or not 0 <= owner['index'] < 16 or
                type(owner.get('generation')) is not int or not 0 < owner['generation'] < 2**64 or
                owner.get('path') != f"/org/sparklink/slk{owner['index']}_g{owner['generation']}" or
                not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', owner.get('address', ''))):
            raise CaptureError('original canonical controller identity required')
    if (row['scanner']['index'] == row['advertiser']['index'] or
            row['scanner']['address'] == row['advertiser']['address']):
        raise CaptureError('distinct selected controllers required')
    markers = row['markers']
    if (not isinstance(markers, list) or len(markers) != 2 or
            any(not isinstance(m, str) or not re.fullmatch('[0-9a-f]{32}', m) for m in markers) or
            markers[0] == markers[1] or markers[0][:16] != markers[1][:16]):
        raise CaptureError('independent marker suffixes with one original random prefix required')
    validate_tool(row['tool'])


SDK_CLIENT_PATHS = dict(c='/bin/ws73-application-client-c',python='/usr/share/sparklink/tools/ws73-application-client.py',library='/usr/lib/libsparklink.so.0')


def validate_sdk_clients(tools,root=None,guest_files=None):
    if not isinstance(tools,dict) or set(tools)!=set(SDK_CLIENT_PATHS):raise CaptureError('fixed public C/Python client and library records required')
    for name,path in SDK_CLIENT_PATHS.items():
        tool=tools[name]
        if (set(tool)!={'path','sha256'} or tool['path']!=path or not re.fullmatch('[0-9a-f]{64}',tool['sha256'])):
            raise CaptureError('fixed actual SDK client/library only;no arbitrary command')
        if root is not None:
            actual=Path(root)/path.lstrip('/')
            if actual.is_symlink() or not actual.is_file() or file_record(actual)['sha256']!=tool['sha256'] or file_record(actual) not in guest_files:
                raise CaptureError('executed discovery SDK input differs from sealed prepared image')
            if name!='python' and actual.read_bytes()[:4]!=b'\x7fELF':raise CaptureError('actual SDK ELF required')


def reader_args(row, number):
    prefix = marker_data(row['markers'][0])[:-16].hex()
    if case(row)=='sdk-release':
        prefix_args=[SDK_CLIENT_PATHS['c']] if number==0 else ['/bin/python3',SDK_CLIENT_PATHS['python']]
        return prefix_args+['discovery',str(row['scanner']['index']),str(row['scanner']['generation']),prefix,str(1 if number==0 else 8),row['advertiser']['address'].replace(':','').lower()]
    if case(row)=='ttl':
        return ['/bin/discovery-lifetime-probe',row['scanner']['path'],prefix,str(4000 if number==0 else 12000),row['advertiser']['address']]
    return ['/bin/slctl', '--adapter', row['scanner']['path'], 'discover', prefix,
            str(1024 if case(row) == 'owner-loss' else (1 if number == 0 else 8)), '20000', '-128']


def validate_probe(tool,root=None,guest_files=None):
    if (set(tool)!={'path','sha256'} or tool['path']!='/bin/discovery-lifetime-probe' or
            not isinstance(tool['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',tool['sha256'])):
        raise CaptureError('fixed actual SDK lifetime example only')
    if root is not None:
        root=Path(root).resolve(strict=True);path=root/tool['path'].lstrip('/')
        if path.is_symlink() or not path.is_file() or path.read_bytes()[:4]!=b'\x7fELF' or file_record(path)['sha256']!=tool['sha256'] or not any(f==file_record(path) for f in guest_files):
            raise CaptureError('actual lifetime probe differs from sealed VM')


def ttl_output(row,number,*,final=True):
    """Literal SDK consumer output only; no protocol or lease implementation."""
    app=row['readers'][number];text=app['stdout'];lines=text.splitlines()
    session=active_session(text,row['scanner']['path'])
    lease=LEASE.fullmatch(lines[2]) if len(lines)>2 else None
    expiry_rows=[(i,m) for i,line in enumerate(lines) if (m:=EXPIRED.fullmatch(line))]
    if not session or not lease or lease[1]!=session[1] or int(lease[4])!=(4000 if number==0 else 12000) or len(expiry_rows)!=1:
        raise CaptureError('original bounded lease identity and one UnknownObject expiry required')
    index,expired=expiry_rows[0]
    if (expired[1]!=session[1] or not app['start_wall_ns']<=int(lease[5])<=int(lease[6])<=app['active_wall_ns'] or
            not int(lease[5])+int(lease[4])*1_000_000<=int(expired[2])<=int(lease[6])+int(lease[4])*1_000_000+5_000_000_000 or
            not 1<=index-3<=1024):
        raise CaptureError('expiry must fit original admission bounds with actual prior reports')
    if final:
        footer=LEASE_EXIT.fullmatch(lines[-1]) if lines else None
        if not footer or footer[1]!=session[1] or len(lines)!=index+2 or not text.endswith('\n'):
            raise CaptureError('stale close must occur only after explicit finish;normal final output required')
        if (app.get('termination') is not None or
                not int(expired[2])<=app['expiry_observed_wall_ns']<app['finish_requested_wall_ns']<=app['end_wall_ns']):
            raise CaptureError('caller must survive expiry until supervised finish;no signal/early exit')
    elif len(lines)!=index+1 or not text.endswith('\n'):
        raise CaptureError('original complete expiry line and still-held caller required')
    return dict(session=int(session[1]),caller=lease[2],owner=lease[3],duration_ms=int(lease[4]),
                before_wall_ns=int(lease[5]),active_wall_ns=int(lease[6]),expired_wall_ns=int(expired[2]),
                report_lines=lines[3:index])


def active_session(text,path):
    # slctl --adapter prints its actual selection before the command result.
    lines=text.splitlines()
    if text and not text.endswith('\n'):lines=lines[:-1]
    if not lines:return None
    if lines[0]!='Selected '+path:raise CaptureError('actual CLI selection must match the original controller')
    if len(lines)<2:return None
    match=SESSION.fullmatch(lines[1])
    if match and match[2]!=path:raise CaptureError('active session selected another controller')
    return match


def receipt(row, number):
    """Parse actual output independently of SDK codec and shared D-Bus types."""
    app = row['readers'][number]
    if case(row)=='sdk-release':
        from ws73_application_client import application_environment
        if app.get('environment')!=application_environment():raise CaptureError('explicit SDK environment required')
    identity = app['credentials']
    lost = case(row) == 'owner-loss'
    if (app['args'] != reader_args(row, number) or app['exit'] != (-signal.SIGKILL if lost else 0) or app['stderr'] or not app['stdout'].endswith('\n') or
            identity['uids'] != [1004]*4 or identity['gids'] != [1004]*4 or identity['groups'] or
            set(identity['capabilities']) != {'CapEff','CapPrm','CapAmb','CapInh'} or
            any(int(v,16) for v in identity['capabilities'].values()) or app['native_fds']):
        raise CaptureError('successful cap-zero apps-only actual SDK reader required')
    lines = app['stdout'].splitlines()
    session = active_session(app['stdout'],row['scanner']['path'])
    release = RELEASE.fullmatch(lines[-1]) if lines else None
    count = 1 if number == 0 else 8
    ttl=None
    if case(row)=='ttl':
        ttl=ttl_output(row,number)
        report_lines=ttl['report_lines']
        if len(report_lines)<count:raise CaptureError('actual minimum peer reports required before TTL')
    elif lost:
        termination=app.get('termination',{})
        if (not session or release or not count <= len(lines)-2 <= 1024 or
                termination.get('signal') != signal.SIGKILL or termination.get('pid') != app['pid'] or
                termination.get('reason') != 'TEST_OWNED_CALLER_LOSS' or
                not app['active_wall_ns'] < termination.get('sent_wall_ns',0) <= app['end_wall_ns'] or
                not app['start_monotonic_ns'] < termination.get('sent_monotonic_ns',0) < app['start_monotonic_ns']+20_000_000_000):
            raise CaptureError('actual owned caller SIGKILL and observed peer data required; no explicit release')
        report_lines=lines[2:]
    elif (not session or not release or session[2] != row['scanner']['path'] or
            session[1] != release[1] or release[2] != ('false' if number == 0 else 'true') or len(lines) != count + 3):
        raise CaptureError('original active identity/count and explicit release receipt required')
    else:report_lines=lines[2:-1]
    reports = []
    for line in report_lines:
        match = REPORT.fullmatch(line)
        if (not match or match[1] != session[1] or int(match[2]) != row['scanner']['generation'] or
                int(match[4]) != 0 or match[5] != row['advertiser']['address'].replace(':','').lower() or
                not -128 <= int(match[6]) <= 20 or
                match[7] not in [marker_data(m).hex() for m in row['markers']]):
            raise CaptureError('exact peer random bytes/address/type/known RSSI required')
        reports.append(dict(sequence=int(match[3]), address=match[5], rssi=int(match[6]), data=match[7]))
    if any(a['sequence'] >= b['sequence'] for a,b in zip(reports,reports[1:])):
        raise CaptureError('actual SDK reports must have strictly increasing Native sequences')
    if reports[0]['data'] != marker_data(row['markers'][0]).hex():
        raise CaptureError('both callers must hear original first marker')
    if number == 1 and not any(r['data'] == marker_data(row['markers'][1]).hex() for r in reports):
        raise CaptureError('survivor must receive the new marker after other caller released')
    result=dict(session=int(session[1]), reports=reports)
    if ttl is not None:result['ttl']={k:v for k,v in ttl.items() if k!='report_lines'}
    return result


def write_record(path, row):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(row,indent=2)+'\n')
    temporary.chmod(0o644)
    temporary.replace(path)


def finish_reader(caller,app,out,err,*,kill=False,timeout=3):
    """Spool complete pipe output only after collection; never poll live 9p files."""
    try:
        caller.finish(kill=kill,timeout=timeout)
    finally:
        if 'exit' in caller.row:
            app.update({k:caller.row[k] for k in ['exit','stdout','stderr','end_wall_ns']})
            for path,key in [(out,'stdout'),(err,'stderr')]:
                temporary=path.with_suffix(path.suffix+'.tmp')
                temporary.write_text(app[key]);temporary.replace(path)


def wait_for(path, run, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        run.alive()
        if path.is_file():
            return read_json(path, 0)
        failure = path.parent/'run.json'
        if failure.is_file():
            raise CaptureError('discovery supervisor ended before required barrier: '+str(read_json(failure,0).get('error')))
        time.sleep(.01)
    raise CaptureError('original discovery test barrier deadline; preserve partial outputs')


def execute(run, a, b):
    for phase,(scanner,advertiser) in enumerate([(a,b),(b,a)]):
        run.check(scanner);run.check(advertiser)
        prefix = os.urandom(8).hex()
        markers = [prefix+os.urandom(8).hex() for _ in range(2)]
        request = dict(phase=phase,scanner=scanner,advertiser=advertiser,markers=markers,
                       tool=file_record(run.args.slctl),status='REQUESTED')
        if getattr(run.args,'application_discovery_case','release') != 'release':
            request['termination']=run.args.application_discovery_case
        if case(request)=='ttl':request['probe']=file_record('/bin/discovery-lifetime-probe')
        if case(request)=='sdk-release':request['clients']={name:file_record(path) for name,path in SDK_CLIENT_PATHS.items()}
        validate_request(request,phase)
        row = dict(request=request,status='RUNNING',start_wall_ns=time.time_ns(),advertisements=[])
        run.data.setdefault('application_discovery',[]).append(row);run.save()
        target = run.output/f'discovery-role-{phase}.request.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(request)+'\n');temporary.chmod(0o600)
        os.link(temporary,target);temporary.unlink()
        folder = ROOT/f'phase-{phase}'
        try:
            row['barrier'] = wait_for(folder/'ready.json',run,12);run.save()
            for index,marker in enumerate(markers):
                started = run.ctl(advertiser,'advertise','on',marker)
                parsed = parse_result(started['stdout'],advertiser,1,allow_recreate=True)
                if f"NativeAdvertisementAccepted: request={parsed['request']} marker={marker} data={marker_data(marker).hex()}" not in started['stdout'].splitlines():
                    raise CaptureError('original explicit random advertisement admission required')
                row['advertisements'].append(len(run.data['commands'])-1);run.save()
                if index == 0:
                    key=departure_key(request)
                    row[key] = wait_for(folder/(key.replace('_','-')+'.json'),run,12);run.save()
                else:
                    row['supervision'] = wait_for(folder/'run.json',run,20)
                    if row['supervision']['status'] != output_status(request):
                        raise CaptureError('actual discovery readers failed')
                run.stop(advertiser,'advertise')
            run.check(scanner);run.check(advertiser)
            row.update(status='APPLICATION_DISCOVERY_EVIDENCE_PENDING',end_wall_ns=time.time_ns());run.save()
        except BaseException as error:
            row.update(status='FAIL',error=str(error),end_wall_ns=time.time_ns());run.save();raise


def supervise(daemon_pid):
    require_vm('ws73.application_discovery=1')
    boot=boot_case(Path('/proc/cmdline').read_text().split())
    daemon = daemon_identity(daemon_pid)
    ROOT.mkdir(mode=0o755,exist_ok=False)
    def interrupted(*_): raise InterruptedError('discovery supervisor stopped')
    signal.signal(signal.SIGTERM,interrupted)
    request_deadline = time.monotonic()+180  # Test environment budget, not a protocol deadline.
    original_case = None
    for phase in (0,1):
        request = INPUT/f'discovery-role-{phase}.request.json'
        while not request.is_file():
            if daemon_identity(daemon_pid) != daemon or time.monotonic() >= request_deadline:
                raise CaptureError('original daemon/request supervision deadline')
            time.sleep(.01)
        source = read_json(request,1000);validate_request(source,phase)
        if original_case is None:original_case=case(source)
        if case(source)!=original_case or case(source)!=boot:raise CaptureError('one explicit boot termination case for both scanner roles')
        if source['tool'] != file_record('/bin/slctl'): raise CaptureError('original actual SDK binary changed')
        if case(source)=='sdk-release' and source['clients']!={name:file_record(path) for name,path in SDK_CLIENT_PATHS.items()}:raise CaptureError('original public SDK client inputs changed')
        if case(source)=='ttl' and source['probe']!=file_record('/bin/discovery-lifetime-probe'):
            raise CaptureError('original actual lifetime probe changed')
        folder = ROOT/f'phase-{phase}';folder.mkdir(mode=0o755)
        row = dict(source,daemon=daemon,readers=[None,None],status='RUNNING',start_wall_ns=time.time_ns(),
                   request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),verifier=file_record(__file__))
        children = []
        callers = {}
        with ExitStack() as files:
            try:
                for number in (1,0):
                    out,err = folder/f'{number}.stdout',folder/f'{number}.stderr'
                    app = dict(args=reader_args(source,number),start_wall_ns=time.time_ns(),
                               start_monotonic_ns=time.monotonic_ns(),output_files=[str(out),str(err)])
                    row['readers'][number] = app
                    options={}
                    if case(source)=='sdk-release':
                        from ws73_application_client import application_environment
                        app['environment']=application_environment();options['env']=dict(os.environ,**app['environment'])
                    caller=Invocation(app['args'],'discovery',credentials=(1004,1004),stdin=subprocess.PIPE if case(source)=='ttl' else subprocess.DEVNULL,**options)
                    callers[number]=caller;process=caller.process
                    for stream in [process.stdout,process.stderr,process.stdin]:
                        if stream is not None:files.callback(stream.close)
                    children.append((number,process,app,out,err));app['pid']=process.pid
                    app['credentials'],app['process_status'] = process_identity(process.pid,1004)
                    app['native_fds'] = [os.readlink(fd) for fd in Path(f'/proc/{process.pid}/fd').iterdir()
                                         if fd.exists() and os.readlink(fd) == '/dev/sparklink']
                    caller.until(rb'^DiscoverySession: [^\n]*\n',timeout=6,limit=4*1024*1024,label='actual SDK active session')
                    if not active_session(caller.prefix.decode(),source['scanner']['path']) or process.poll() is not None:
                        raise CaptureError('actual SDK AcquireDiscovery readiness failed')
                    app['active_wall_ns'] = time.time_ns()
                    if daemon_identity(daemon_pid) != daemon:raise CaptureError('original daemon changed')
                    write_record(folder/'progress.json',row)
                ready = dict(phase=phase,scanner=source['scanner']['path'],active_wall_ns=time.time_ns(),
                             sessions=[active_session(callers[n].prefix.decode(),source['scanner']['path'])[1] for n in (0,1)])
                if len(set(ready['sessions'])) != 2:raise CaptureError('distinct caller sessions required')
                row['ready'] = ready;write_record(folder/'ready.json',ready)
                for number in (0,1):
                    _,process,app,out,err = next(c for c in children if c[0] == number)
                    caller=callers[number]
                    if case(source)=='ttl':
                        caller.until(rb'^DiscoveryExpired: [^\n]*\n',timeout=15,limit=4*1024*1024,label='actual original TTL expiry')
                        text=caller.prefix.decode()
                        if process.poll() is not None:raise CaptureError('TTL must be observed while original caller remains alive')
                        app['stdout']=text;app['expiry_observed_wall_ns']=time.time_ns()
                        ttl_output(row,number,final=False)
                        if number==0:
                            survivor=next(c[1] for c in children if c[0]==1)
                            if survivor.poll() is not None:raise CaptureError('TTL survivor ended')
                            key=departure_key(source)
                            row[key]=dict(phase=phase,first_expired_wall_ns=app['expiry_observed_wall_ns'],
                                first_alive=True,survivor_alive=True,observed_wall_ns=time.time_ns())
                            write_record(folder/(key.replace('_','-')+'.json'),row[key])
                        continue
                    if case(source) == 'owner-loss':
                        # Only wait for actual complete CLI report lines. This
                        # is a scheduling barrier, never the acceptance oracle:
                        # receipt + independent raw capture check every report.
                        def heard(prefix):
                            text=prefix.decode();lines=text.splitlines()
                            if not text.endswith('\n'):lines=lines[:-1]
                            seen=[m for line in lines[2:] if (m:=REPORT.fullmatch(line))]
                            if daemon_identity(daemon_pid)!=daemon:raise CaptureError('original daemon changed')
                            return (len(seen)>=(1 if number==0 else 8) and
                                    (number==0 or any(m[7]==marker_data(source['markers'][1]).hex() for m in seen)))
                        caller.pump_until(heard,timeout=12,limit=4*1024*1024,label='actual selected peer reports')
                        if process.poll() is not None:raise CaptureError('owned caller ended before deliberate loss')
                        app['termination']=dict(reason='TEST_OWNED_CALLER_LOSS',signal=signal.SIGKILL,pid=process.pid,
                                                sent_wall_ns=time.time_ns(),sent_monotonic_ns=time.monotonic_ns())
                        process.kill()  # Popen child only; no externally supplied pid.
                    finish_reader(caller,app,out,err,timeout=3 if case(source)=='owner-loss' else 27)
                    receipt(row,number)
                    if number == 0:
                        survivor = next(c[1] for c in children if c[0] == 1)
                        if survivor.poll() is not None:raise CaptureError('survivor ended before isolated release barrier')
                        key=departure_key(source)
                        row[key] = dict(phase=phase,first_end_wall_ns=app['end_wall_ns'],survivor_alive=True,observed_wall_ns=time.time_ns())
                        write_record(folder/(key.replace('_','-')+'.json'),row[key])
                if case(source)=='ttl':
                    until=time.monotonic_ns()+5_000_000_000
                    while (remaining:=until-time.monotonic_ns())>0:
                        if any(p.poll() is not None for _,p,_,_,_ in children):raise CaptureError('TTL callers must survive physical cleanup collection')
                        if daemon_identity(daemon_pid)!=daemon:raise CaptureError('original daemon changed')
                        time.sleep(min(.01,remaining/1e9))
                    last=ttl_output(row,1,final=False)
                    row['cleanup_window']=dict(start_wall_ns=row['readers'][1]['expiry_observed_wall_ns'],
                        deadline_wall_ns=last['active_wall_ns']+last['duration_ms']*1_000_000+5_000_000_000,
                        end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns(),budget_ns=5_000_000_000,
                        callers_alive=True)
                    for number,process,app,out,err in children:
                        if process.poll() is not None:raise CaptureError('TTL caller exited before finish permission')
                        app['finish_requested_wall_ns']=time.time_ns()
                        process.stdin.write(b'finish\n');process.stdin.flush();process.stdin.close()
                        process.stdin=None  # communicate must not flush an already closed pipe.
                        finish_reader(callers[number],app,out,err)
                        receipt(row,number)
                if case(source) == 'owner-loss':
                    last=row['readers'][1]['termination']
                    until=last['sent_monotonic_ns']+5_000_000_000
                    # Collection window only: no manager STOP, ioctl or fake
                    # cleanup receipt. Missing/late physical STOP fails capture.
                    while (remaining:=until-time.monotonic_ns())>0:
                        if daemon_identity(daemon_pid)!=daemon:raise CaptureError('original daemon changed')
                        time.sleep(min(.01,remaining/1e9))
                    row['cleanup_window']=dict(start_wall_ns=last['sent_wall_ns'],
                        deadline_wall_ns=last['sent_wall_ns']+5_000_000_000,end_wall_ns=time.time_ns(),
                        end_monotonic_ns=time.monotonic_ns(),budget_ns=5_000_000_000)
                if daemon_identity(daemon_pid) != daemon:raise CaptureError('original daemon changed')
                row.update(status=output_status(source),end_wall_ns=time.time_ns())
            except BaseException as error:
                row.update(status='FAIL',error=str(error),error_traceback=traceback.format_exc());raise
            finally:
                for number,process,app,out,err in children:
                    if 'exit' not in app:
                        finish_reader(callers[number],app,out,err,kill=process.poll() is None)
                write_record(folder/'run.json',row)
    write_record(ROOT/'finished.json',dict(status=finished_status(source),daemon=daemon))


def corroborate(run,capture):
    rows = run.get('application_discovery',[])
    if len(rows) != 2:raise CaptureError('both ordered scanner roles required')
    if len({m for item in rows for m in item['request']['markers']}) != 4:
        raise CaptureError('original random markers must not repeat across phases')
    if len({case(item['request']) for item in rows}) != 1:raise CaptureError('both scanner roles require the same original termination case')
    proofs = []
    for phase,item in enumerate(rows):
        row = item['supervision'];validate_request(item['request'],phase)
        if (item['status'] != 'APPLICATION_DISCOVERY_EVIDENCE_PENDING' or
                row['status'] != output_status(row) or
                case(row) != case(item['request']) or
                any(row[k] != item['request'][k] for k in item['request'] if k != 'status') or
                row['tool'] != run['slctl'] or
                row['ready'] != item['barrier'] or row[departure_key(row)] != item[departure_key(row)]):
            raise CaptureError('exact original discovery request/barriers and actual tool required')
        parsed = [receipt(row,n) for n in (0,1)]
        if parsed[0]['session'] == parsed[1]['session']:raise CaptureError('caller ids collided')
        if row['ready']['sessions'] != [str(p['session']) for p in parsed]:
            raise CaptureError('original active barrier session ids differ from actual receipts')
        scanner,advertiser = row['scanner'],row['advertiser']
        expected_pair = run['initial'] if phase == 0 else list(reversed(run['initial']))
        if [scanner,advertiser] != expected_pair:raise CaptureError('original scanner roles must swap')
        first,second = [run['commands'][i] for i in item['advertisements']]
        for command,marker in zip([first,second],row['markers']):
            if (command['args'] != [run['slctl']['path'],'--adapter',advertiser['path'],'advertise','on',marker] or command['exit']):
                raise CaptureError('exact actual marker advertisement command required')
            parse_result(command['stdout'],advertiser,1,allow_recreate=True)
            command_reply(capture,advertiser,0x0c03,command['start_wall_ns'],command['end_wall_ns'],
                          bytes([0,3,len(marker_data(marker))])+marker_data(marker),'')
        first_departure=row[departure_key(row)]
        ttl_case=case(row)=='ttl'
        first_at=row['readers'][0]['expiry_observed_wall_ns'] if ttl_case else row['readers'][0]['end_wall_ns']
        if (first_departure.get('phase')!=phase or first_departure.get('survivor_alive') is not True or
                first_departure.get('first_expired_wall_ns' if ttl_case else 'first_end_wall_ns')!=first_at or
                not first_departure['observed_wall_ns']<row['readers'][1]['end_wall_ns']):
            raise CaptureError('actual first-caller departure and live survivor barrier required')
        if ttl_case and (first_departure.get('first_alive') is not True or
                parsed[0]['ttl']['caller']==parsed[1]['ttl']['caller'] or
                any(p['ttl']['owner']!=run['bus_before']['owner'] for p in parsed)):
            raise CaptureError('two distinct original live callers and same actual daemon owner required')
        start = min(a['start_wall_ns'] for a in row['readers']);end = max(a['end_wall_ns'] for a in row['readers'])
        if (not start <= row['ready']['active_wall_ns'] <= first['start_wall_ns'] <= first['end_wall_ns'] <= second['start_wall_ns'] < second['end_wall_ns'] <= end or
                not first['start_wall_ns'] <= first_at <= first_departure['observed_wall_ns'] <= second['start_wall_ns']):
            raise CaptureError('original active/release/new-marker ordering required')
        observation=[p['ttl']['expired_wall_ns'] for p in parsed] if ttl_case else [a['end_wall_ns'] for a in row['readers']]
        if (observation[0] - first['start_wall_ns'] >= 10_000_000_000 or
                observation[1] - second['start_wall_ns'] >= 10_000_000_000):
            raise CaptureError('selected marker must be observed/released within original ten seconds')
        if case(row)=='owner-loss':
            window=row.get('cleanup_window',{});last=row['readers'][1]['termination']
            if (window.get('budget_ns')!=5_000_000_000 or window.get('start_wall_ns')!=last['sent_wall_ns'] or
                    window.get('deadline_wall_ns')!=last['sent_wall_ns']+5_000_000_000 or
                    window.get('end_wall_ns',0)<max(end,window['deadline_wall_ns']) or
                    window.get('end_monotonic_ns',0)<last['sent_monotonic_ns']+5_000_000_000):
                raise CaptureError('original five-second last-owner cleanup collection window required')
            end=window['end_wall_ns']
        elif ttl_case:
            window=row.get('cleanup_window',{});last=parsed[1]['ttl']
            if (window.get('budget_ns')!=5_000_000_000 or window.get('callers_alive') is not True or
                    window.get('start_wall_ns')!=row['readers'][1]['expiry_observed_wall_ns'] or
                    window.get('deadline_wall_ns')!=last['active_wall_ns']+last['duration_ms']*1_000_000+5_000_000_000 or
                    window.get('end_wall_ns',0)<window['start_wall_ns']+5_000_000_000 or
                    any(a['finish_requested_wall_ns']<window['end_wall_ns'] for a in row['readers'])):
                raise CaptureError('both callers must remain alive through original TTL cleanup collection')
        commands = [c for c in capture['commands'] if (c['bus'],c['device']) == (scanner['bus'],scanner['device']) and start <= c['wall_ns'] <= end and c['opcode'] in (0x1001,0x1002)]
        if [(c['opcode'],c['params'] if c['opcode']==0x1002 else None) for c in commands] != [(0x1001,None),(0x1002,'0100'),(0x1002,'0000')]:
            raise CaptureError('one actual START recipe and only last-caller STOP required')
        radio = []
        for i,command in enumerate(commands):
            if command['opcode']==0x1001 and (len(bytes.fromhex(command['params']))!=8 or bytes.fromhex(command['params'])[2]!=1):
                raise CaptureError('actual validated WS73 frame-1 scan parameters required')
            bound = commands[i+1]['wall_ns']-1 if i+1<len(commands) else (window['deadline_wall_ns'] if case(row) in ('owner-loss','ttl') else end)
            radio.append(command_reply(capture,scanner,command['opcode'],command['wall_ns'],bound,bytes.fromhex(command['params']),''))
        if not radio[1]['reply']['wall_ns'] <= row['ready']['active_wall_ns'] or radio[-1]['command']['wall_ns'] <= first_departure['observed_wall_ns']:
            raise CaptureError('START before active and STOP after isolated first release required')
        if case(row)=='owner-loss' and radio[-1]['command']['wall_ns']<last['sent_wall_ns']:
            raise CaptureError('automatic STOP must follow last caller loss; no premature or manager STOP')
        if case(row)=='owner-loss' and radio[-1]['reply']['wall_ns']>=min(a['start_wall_ns'] for a in row['readers'])+20_000_000_000:
            # Acquire admission is after child creation. Completing STOP before
            # this lower bound rules out either original lease expiring first.
            raise CaptureError('TTL-ambiguous STOP cannot qualify caller-loss cleanup')
        if ttl_case and (radio[-1]['command']['wall_ns']<last['before_wall_ns']+last['duration_ms']*1_000_000 or
                radio[-1]['reply']['wall_ns']>=min(a['finish_requested_wall_ns'] for a in row['readers'])):
            raise CaptureError('STOP must follow last original TTL and complete before any close/exit permission')
        raw = []
        for number,app in enumerate(parsed):
            used = set()  # Shared fanout across callers, distinct RX within each caller.
            cutoff=observation[number] if ttl_case else row['readers'][number]['end_wall_ns']
            for report in app['reports']:
                matches = [r for r in capture['reports'] if (r['bus'],r['device']) == (scanner['bus'],scanner['device']) and
                           radio[1]['reply']['wall_ns'] <= r['wall_ns'] <= cutoff and
                           r['address'] == advertiser['address'] and r['data'] == report['data'] and r['rssi'] == report['rssi'] and
                           (r['record'],r['hcc_offset']) not in used and
                           (report['data'] != marker_data(row['markers'][1]).hex() or second['start_wall_ns'] <= r['wall_ns'])]
                if not matches:raise CaptureError('each SDK report needs selected raw receiver USB/HCC/DLI evidence')
                used.add((matches[0]['record'],matches[0]['hcc_offset']))
                raw.append(matches[0])
        if any(start<=f['wall_ns']<=end and (f['bus'],f['device']) in [(o['bus'],o['device']) for o in [scanner,advertiser]] for f in capture['failures']):
            raise CaptureError('failed target USB transfer within accepted discovery interval')
        proofs.append(dict(phase=phase,scanner=scanner,advertiser=advertiser,radio=radio,reports=raw))
    if case(rows[0]['request'])=='ttl':
        if any(item['request']['probe']!=rows[0]['request']['probe'] for item in rows):raise CaptureError('same actual probe in both scanner roles required')
        return dict(status='TTL_TWO_ROLE_USB_CORROBORATED',termination='ttl',probe=rows[0]['request']['probe'],phases=proofs,
                    limits='Two distinct live caller leases4/12seconds,firstTTL survivor/newmarker,last automaticSTOP before close/exit. NotmanagerSTOP/partialinit/deadlineinterleavings/fullpermissions/peerbusinessisolation or naturalrecovery.')
    if case(rows[0]['request'])=='owner-loss':
        return dict(status='OWNER_LOSS_TWO_ROLE_USB_CORROBORATED',termination='owner-loss',phases=proofs,
                    limits='Deliberate SIGKILL of two owned apps-only readers;survivor new-marker and last-loss actualSTOP within original5s only. NoTTL/manager-stop/partial-init/system-wide privilege/peer business isolation or natural recovery qualification.')
    if case(rows[0]['request'])=='sdk-release':
        clients=rows[0]['request']['clients']
        if any(item['request']['clients']!=clients for item in rows):raise CaptureError('same actual C/Python SDK artifacts required in both roles')
        return dict(status='SDK_EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED',termination='sdk-release',clients=clients,phases=proofs,
                    limits='C/Python explicit-release positive slice only,UID1004/caps0 and actual USB reports/STOP;not TTL/callerloss/managerSTOP/fullpermissions/peerbusinessisolation or natural recovery.')
    return dict(status='EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED',phases=proofs,
                limits='Explicit release positive slice only; no TTL/owner-loss/manager-stop/partial-init/system-wide privilege or natural recovery qualification.')


def verify_supervisor_artifacts(run,evidence,expected_tool):
    """Reopen the original root-side files, not merely their copied JSON values."""
    evidence = Path(evidence)
    finished = json.loads((evidence/'discovery-role/finished.json').read_text())
    if finished != dict(status=finished_status(run['application_discovery'][0]['request']),daemon=run['daemon_before']):
        raise CaptureError('original supervisor completion/daemon identity required')
    for phase,item in enumerate(run['application_discovery']):
        folder = evidence/'discovery-role'/f'phase-{phase}'
        row = item['supervision']
        request = evidence/'application/passthrough-control'/f'discovery-role-{phase}.request.json'
        if (json.loads((folder/'run.json').read_text()) != row or
                json.loads(request.read_text()) != item['request'] or
                hashlib.sha256(request.read_bytes()).hexdigest() != row['request_sha256'] or
                row['verifier'] != expected_tool):
            raise CaptureError('original source-bound discovery request/supervision files required')
        departure=departure_key(row)
        for name,key in [('ready','barrier'),(departure.replace('_','-'),departure)]:
            if json.loads((folder/(name+'.json')).read_text()) != item[key]:
                raise CaptureError('original supervisor barrier changed')
        for number,app in enumerate(row['readers']):
            for suffix in ['stdout','stderr']:
                if app[suffix] != (folder/f'{number}.{suffix}').read_text():
                    raise CaptureError('actual original SDK stdout/stderr required')
    return supervision_summary(case(run['application_discovery'][0]['request']))


def valid_summary(proof):
    try:
        lost=case(proof)=='owner-loss'
        ttl=case(proof)=='ttl'
        if ttl:validate_probe(proof.get('probe',{}))
        sdk=case(proof)=='sdk-release'
        if sdk:validate_sdk_clients(proof.get('clients',{}))
        return (proof['status']==('SDK_EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED' if sdk else 'TTL_TWO_ROLE_USB_CORROBORATED' if ttl else ('OWNER_LOSS_TWO_ROLE_USB_CORROBORATED' if lost else 'EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED')) and
                len(proof['phases'])==2 and [p['phase'] for p in proof['phases']]==[0,1] and
                all(len(p['radio'])==3 and (9<=len(p['reports'])<=2048 if lost or ttl else len(p['reports'])==9) for p in proof['phases']) and
                proof['phases'][0]['scanner']==proof['phases'][1]['advertiser'] and
                proof['phases'][0]['advertiser']==proof['phases'][1]['scanner'])
    except (KeyError,TypeError,CaptureError):return False


if __name__ == '__main__':
    import sys
    if len(sys.argv)!=2:raise SystemExit('usage: ws73_application_discovery.py ACTUAL_DAEMON_PID')
    supervise(int(sys.argv[1]))
