# SPDX-License-Identifier: GPL-2.0-only
"""Finite VM apps-only discovery gate, using the actual SDK/slctl and USB oracle.

The existing ordinary controller runner drives the advertiser. This root-only
test supervisor can launch only two fixed UID1004 slctl readers, never a Host,
arbitrary command, Native operation or installed privilege service. A positive
run covers explicit release only, not TTL/owner-loss/management cancellation.
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

ROOT = Path('/evidence/discovery-role')
INPUT = Path('/evidence/application/passthrough-control')
SESSION = re.compile(r'DiscoverySession: id=([1-9][0-9]*) path=(/org/sparklink/slk[0-9]+_g[1-9][0-9]*) state=active source=broker')
REPORT = re.compile(r'DiscoveryReport: session=([1-9][0-9]*) generation=([1-9][0-9]*) sequence=([1-9][0-9]*) address_type=([0-9]+) address=([0-9a-f]{12}) rssi=(-?[0-9]+) data=([0-9a-f]+)')
RELEASE = re.compile(r'DiscoveryReleased: session=([1-9][0-9]*) last_physical_stop_confirmed=(false|true)')


def requested(args):
    if not getattr(args,'application_discovery_verify',False):return False
    allowed = {'passthrough','qmp_hotplug','connection_verify','application_discovery_verify',
               'channel_socket_verify','channel_socket_boundaries'}
    if (not (getattr(args,'passthrough',False) or getattr(args,'qmp_hotplug',False)) or
            not getattr(args,'connection_verify',False) or len(getattr(args,'ports',[])) != 2 or
            any(type(v) is bool and v and k not in allowed for k,v in vars(args).items()) or
            any(getattr(args,k,None) for k in ['security_agent','native_controller_return','channel_benchmark',
                'managed_partial_case','managed_connected_case','managed_connected_reply','managed_real_later_step','daemon_hold_case']) or
            getattr(args,'connection_advertising','fixed-t') != 'fixed-t'):
        raise CaptureError('discovery explicit release requires separate two-device real connection/preservation VM')
    return True


def validate_request(row, phase):
    if (set(row) != {'phase', 'scanner', 'advertiser', 'markers', 'tool', 'status'} or
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
    if (set(row['tool']) != {'path', 'sha256'} or row['tool']['path'] != '/bin/slctl' or
            not re.fullmatch('[0-9a-f]{64}', row['tool']['sha256'])):
        raise CaptureError('fixed slctl artifact only; no arbitrary command')


def reader_args(row, number):
    prefix = marker_data(row['markers'][0])[:-16].hex()
    return ['/bin/slctl', '--adapter', row['scanner']['path'], 'discover', prefix,
            str(1 if number == 0 else 8), '20000', '-128']


def receipt(row, number):
    """Parse actual output independently of SDK codec and shared D-Bus types."""
    app = row['readers'][number]
    identity = app['credentials']
    if (app['args'] != reader_args(row, number) or app['exit'] != 0 or app['stderr'] or
            identity['uids'] != [1004]*4 or identity['gids'] != [1004]*4 or identity['groups'] or
            set(identity['capabilities']) != {'CapEff','CapPrm','CapAmb','CapInh'} or
            any(int(v,16) for v in identity['capabilities'].values()) or app['native_fds']):
        raise CaptureError('successful cap-zero apps-only actual SDK reader required')
    lines = app['stdout'].splitlines()
    session = SESSION.fullmatch(lines[0]) if lines else None
    release = RELEASE.fullmatch(lines[-1]) if lines else None
    count = 1 if number == 0 else 8
    if (not session or not release or session[2] != row['scanner']['path'] or
            session[1] != release[1] or release[2] != ('false' if number == 0 else 'true') or
            len(lines) != count + 2):
        raise CaptureError('original active identity/count and explicit release receipt required')
    reports = []
    for line in lines[1:-1]:
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
    return dict(session=int(session[1]), reports=reports)


def write_record(path, row):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(row,indent=2)+'\n')
    temporary.chmod(0o644)
    temporary.replace(path)


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
                    row['first_released'] = wait_for(folder/'first-released.json',run,12);run.save()
                else:
                    row['supervision'] = wait_for(folder/'run.json',run,20)
                    if row['supervision']['status'] != 'EXPLICIT_RELEASE_OUTPUTS_CHECKED':
                        raise CaptureError('actual discovery readers failed')
                run.stop(advertiser,'advertise')
            run.check(scanner);run.check(advertiser)
            row.update(status='APPLICATION_DISCOVERY_EVIDENCE_PENDING',end_wall_ns=time.time_ns());run.save()
        except BaseException as error:
            row.update(status='FAIL',error=str(error),end_wall_ns=time.time_ns());run.save();raise


def supervise(daemon_pid):
    require_vm('ws73.application_discovery=1')
    daemon = daemon_identity(daemon_pid)
    ROOT.mkdir(mode=0o755,exist_ok=False)
    def interrupted(*_): raise InterruptedError('discovery supervisor stopped')
    signal.signal(signal.SIGTERM,interrupted)
    request_deadline = time.monotonic()+180  # Test environment budget, not a protocol deadline.
    for phase in (0,1):
        request = INPUT/f'discovery-role-{phase}.request.json'
        while not request.is_file():
            if daemon_identity(daemon_pid) != daemon or time.monotonic() >= request_deadline:
                raise CaptureError('original daemon/request supervision deadline')
            time.sleep(.01)
        source = read_json(request,1000);validate_request(source,phase)
        if source['tool'] != file_record('/bin/slctl'): raise CaptureError('original actual SDK binary changed')
        folder = ROOT/f'phase-{phase}';folder.mkdir(mode=0o755)
        row = dict(source,daemon=daemon,readers=[None,None],status='RUNNING',start_wall_ns=time.time_ns(),
                   request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),verifier=file_record(__file__))
        children = []
        with ExitStack() as files:
            try:
                for number in (1,0):
                    out,err = folder/f'{number}.stdout',folder/f'{number}.stderr'
                    app = dict(args=reader_args(source,number),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
                    row['readers'][number] = app
                    process = subprocess.Popen(app['args'],user=1004,group=1004,extra_groups=[],stdin=subprocess.DEVNULL,
                                               stdout=files.enter_context(out.open('xb')),stderr=files.enter_context(err.open('xb')))
                    children.append((number,process,app,out,err));app['pid']=process.pid
                    app['credentials'],app['process_status'] = process_identity(process.pid,1004)
                    app['native_fds'] = [os.readlink(fd) for fd in Path(f'/proc/{process.pid}/fd').iterdir()
                                         if fd.exists() and os.readlink(fd) == '/dev/sparklink']
                    deadline = time.monotonic()+6
                    while True:
                        lines = out.read_text().splitlines()
                        if lines and SESSION.fullmatch(lines[0]):break
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise CaptureError('actual SDK AcquireDiscovery readiness failed')
                        time.sleep(.01)
                    app['active_wall_ns'] = time.time_ns()
                    if daemon_identity(daemon_pid) != daemon:raise CaptureError('original daemon changed')
                    write_record(folder/'progress.json',row)
                ready = dict(phase=phase,scanner=source['scanner']['path'],active_wall_ns=time.time_ns(),
                             sessions=[SESSION.fullmatch(Path(app['output_files'][0]).read_text().splitlines()[0])[1] for app in row['readers']])
                if len(set(ready['sessions'])) != 2:raise CaptureError('distinct caller sessions required')
                row['ready'] = ready;write_record(folder/'ready.json',ready)
                for number in (0,1):
                    _,process,app,out,err = next(c for c in children if c[0] == number)
                    process.wait(timeout=27)
                    app.update(exit=process.returncode,stdout=out.read_text(),stderr=err.read_text(),end_wall_ns=time.time_ns())
                    receipt(row,number)
                    if number == 0:
                        survivor = next(c[1] for c in children if c[0] == 1)
                        if survivor.poll() is not None:raise CaptureError('survivor ended before isolated release barrier')
                        row['first_released'] = dict(phase=phase,first_end_wall_ns=app['end_wall_ns'],survivor_alive=True,observed_wall_ns=time.time_ns())
                        write_record(folder/'first-released.json',row['first_released'])
                if daemon_identity(daemon_pid) != daemon:raise CaptureError('original daemon changed')
                row.update(status='EXPLICIT_RELEASE_OUTPUTS_CHECKED',end_wall_ns=time.time_ns())
            except BaseException as error:
                row.update(status='FAIL',error=str(error),error_traceback=traceback.format_exc());raise
            finally:
                for _,process,app,out,err in children:
                    if process.poll() is None:process.kill()
                    process.wait()
                    if 'exit' not in app:app.update(exit=process.returncode,stdout=out.read_text(),stderr=err.read_text(),end_wall_ns=time.time_ns())
                write_record(folder/'run.json',row)
    write_record(ROOT/'finished.json',dict(status='TWO_EXPLICIT_RELEASE_PHASES_COMPLETED',daemon=daemon))


def corroborate(run,capture):
    rows = run.get('application_discovery',[])
    if len(rows) != 2:raise CaptureError('both ordered scanner roles required')
    if len({m for item in rows for m in item['request']['markers']}) != 4:
        raise CaptureError('original random markers must not repeat across phases')
    proofs = []
    for phase,item in enumerate(rows):
        row = item['supervision'];validate_request(item['request'],phase)
        if (item['status'] != 'APPLICATION_DISCOVERY_EVIDENCE_PENDING' or
                row['status'] != 'EXPLICIT_RELEASE_OUTPUTS_CHECKED' or
                any(row[k] != item['request'][k] for k in item['request'] if k != 'status') or
                row['tool'] != run['slctl'] or
                row['ready'] != item['barrier'] or row['first_released'] != item['first_released']):
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
        start = min(a['start_wall_ns'] for a in row['readers']);end = max(a['end_wall_ns'] for a in row['readers'])
        if (not start <= row['ready']['active_wall_ns'] <= first['start_wall_ns'] <= first['end_wall_ns'] <= second['start_wall_ns'] < second['end_wall_ns'] <= end or
                not first['start_wall_ns'] <= row['first_released']['first_end_wall_ns'] <= row['first_released']['observed_wall_ns'] <= second['start_wall_ns']):
            raise CaptureError('original active/release/new-marker ordering required')
        if (row['readers'][0]['end_wall_ns'] - first['start_wall_ns'] >= 10_000_000_000 or
                row['readers'][1]['end_wall_ns'] - second['start_wall_ns'] >= 10_000_000_000):
            raise CaptureError('selected marker must be observed/released within original ten seconds')
        commands = [c for c in capture['commands'] if (c['bus'],c['device']) == (scanner['bus'],scanner['device']) and start <= c['wall_ns'] <= end and c['opcode'] in (0x1001,0x1002)]
        if [(c['opcode'],c['params'] if c['opcode']==0x1002 else None) for c in commands] != [(0x1001,None),(0x1002,'0100'),(0x1002,'0000')]:
            raise CaptureError('one actual START recipe and only last-caller STOP required')
        radio = []
        for i,command in enumerate(commands):
            if command['opcode']==0x1001 and (len(bytes.fromhex(command['params']))!=8 or bytes.fromhex(command['params'])[2]!=1):
                raise CaptureError('actual validated WS73 frame-1 scan parameters required')
            bound = commands[i+1]['wall_ns']-1 if i+1<len(commands) else end
            radio.append(command_reply(capture,scanner,command['opcode'],command['wall_ns'],bound,bytes.fromhex(command['params']),''))
        if not radio[1]['reply']['wall_ns'] <= row['ready']['active_wall_ns'] or radio[-1]['command']['wall_ns'] <= row['first_released']['observed_wall_ns']:
            raise CaptureError('START before active and STOP after isolated first release required')
        raw = []
        for number,app in enumerate(parsed):
            used = set()  # Shared fanout across callers, distinct RX within each caller.
            for report in app['reports']:
                matches = [r for r in capture['reports'] if (r['bus'],r['device']) == (scanner['bus'],scanner['device']) and
                           radio[1]['reply']['wall_ns'] <= r['wall_ns'] <= row['readers'][number]['end_wall_ns'] and
                           r['address'] == advertiser['address'] and r['data'] == report['data'] and r['rssi'] == report['rssi'] and
                           (r['record'],r['hcc_offset']) not in used and
                           (report['data'] != marker_data(row['markers'][1]).hex() or second['start_wall_ns'] <= r['wall_ns'])]
                if not matches:raise CaptureError('each SDK report needs selected raw receiver USB/HCC/DLI evidence')
                used.add((matches[0]['record'],matches[0]['hcc_offset']))
                raw.append(matches[0])
        if any(start<=f['wall_ns']<=end and (f['bus'],f['device']) in [(o['bus'],o['device']) for o in [scanner,advertiser]] for f in capture['failures']):
            raise CaptureError('failed target USB transfer within accepted discovery interval')
        proofs.append(dict(phase=phase,scanner=scanner,advertiser=advertiser,radio=radio,reports=raw))
    return dict(status='EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED',phases=proofs,
                limits='Explicit release positive slice only; no TTL/owner-loss/manager-stop/partial-init/system-wide privilege or natural recovery qualification.')


def verify_supervisor_artifacts(run,evidence,expected_tool):
    """Reopen the original root-side files, not merely their copied JSON values."""
    evidence = Path(evidence)
    finished = json.loads((evidence/'discovery-role/finished.json').read_text())
    if finished != dict(status='TWO_EXPLICIT_RELEASE_PHASES_COMPLETED',daemon=run['daemon_before']):
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
        for name,key in [('ready','barrier'),('first-released','first_released')]:
            if json.loads((folder/(name+'.json')).read_text()) != item[key]:
                raise CaptureError('original supervisor barrier changed')
        for number,app in enumerate(row['readers']):
            for suffix in ['stdout','stderr']:
                if app[suffix] != (folder/f'{number}.{suffix}').read_text():
                    raise CaptureError('actual original SDK stdout/stderr required')
    return dict(status='ORIGINAL_DISCOVERY_ROLE_FILES_CHECKED',uid=1004,phases=2)


def valid_summary(proof):
    try:
        return (proof['status']=='EXPLICIT_RELEASE_TWO_ROLE_USB_CORROBORATED' and
                len(proof['phases'])==2 and [p['phase'] for p in proof['phases']]==[0,1] and
                all(len(p['radio'])==3 and len(p['reports'])==9 for p in proof['phases']) and
                proof['phases'][0]['scanner']==proof['phases'][1]['advertiser'] and
                proof['phases'][0]['advertiser']==proof['phases'][1]['scanner'])
    except (KeyError,TypeError):return False


if __name__ == '__main__':
    import sys
    if len(sys.argv)!=2:raise SystemExit('usage: ws73_application_discovery.py ACTUAL_DAEMON_PID')
    supervise(int(sys.argv[1]))
