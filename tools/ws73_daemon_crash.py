# SPDX-License-Identifier: GPL-2.0-only
"""VM supervisor observations of actual SIGKILL/last-File cleanup and successor.

Only the guest init shell sends the signal and reaps its child. This recorder
does not release a lease, stop a radio, reset USB, or construct any DLI reply.
The ordinary application supplies the original active policies. An independent
non-owning kernel fd observes the real cleanup before a new daemon is started.
"""
import ctypes
import fcntl
import json
from pathlib import Path
import re
import time

from ws73_capture import CaptureError, command_reply, marker_data
from ws73_north_star import daemon_identity, file_record, parse_result, stable

STATUS = 'NATIVE_DAEMON_SIGKILL_EVIDENCE_PENDING'
FOLDER = Path('/evidence/daemon-crash')


def observation(owner):
    # Imports are lazy so the independent offline verifier needs no shared lib.
    import sys
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here / ('python' if (here / 'python').is_dir() else 'bindings/python')))
    from sparklink.native import NativeAdapter
    from sparklink.structs import SleDiscoveryResult
    start = time.time_ns()
    with NativeAdapter(owner['index'], owner['generation']) as adapter:
        radio = bytearray(bytes(SleDiscoveryResult(version=1, generation=owner['generation'])))
        number = 0xc0000000 | ctypes.sizeof(SleDiscoveryResult) << 16 | ord('S') << 8 | 0x89
        fcntl.ioctl(adapter.fileno(), number, radio, True)
        state = SleDiscoveryResult.from_buffer_copy(radio)
        snapshot = adapter.snapshot()
        management = adapter.management_status()
        return dict(start_wall_ns=start, index=snapshot.dev_index,
            generation=snapshot.generation, flags=snapshot.flags, profile=snapshot.profile,
            error=snapshot.error, management=dict(state=management.state, mode=management.mode,
                lease=management.lease, flags=management.flags, error=management.error,
                status=management.status, opcode=management.opcode),
            radio=dict(version=state.version, generation=state.generation,
                adv=state.radio_adv, scan=state.radio_scan, error=state.error),
            raw_snapshot=bytes(snapshot).hex(), raw_management=bytes(management).hex(),
            raw_radio=radio.hex(), end_wall_ns=time.time_ns())


def view(row, owner, state, adv, scan):
    from ws73_management_setup import decode
    from sparklink.structs import SleControllerSnapshot, SleManagementQuery, SleDiscoveryResult
    snapshot = decode(SleControllerSnapshot, row['raw_snapshot'])
    management = decode(SleManagementQuery, row['raw_management'])
    radio = decode(SleDiscoveryResult, row['raw_radio'])
    if (snapshot.dev_index != row['index'] or snapshot.generation != row['generation']
            or snapshot.version != 1 or snapshot.flags != row['flags'] or snapshot.profile != row['profile'] or snapshot.error != row['error']
            or management.version != 1 or management.generation != owner['generation'] or management.reserved
            or row['management'] != {k: getattr(management,k) for k in ['state','mode','lease','flags','error','status','opcode']}
            or radio.dev_index != owner['index'] or radio.request_id or radio.flags
            or row['radio'] != dict(version=radio.version,generation=radio.generation,adv=radio.radio_adv,scan=radio.radio_scan,error=radio.error)):
        raise CaptureError('decoded canonical ioctl bytes disagree with observer summary')
    if (row['index'] != owner['index'] or row['generation'] != owner['generation']
            or row['flags'] != 1 or row['profile'] != 1 or row['error']
            or row['management'] != dict(state=state, mode=1 if state == 1 else 0,
                lease=0, flags=0, error=0, status=0, opcode=0)
            or row['radio'] != dict(version=1, generation=owner['generation'], adv=adv, scan=scan, error=0)
            or row['start_wall_ns'] > row['end_wall_ns']):
        raise CaptureError('actual non-owning Held/Free Ready radio observation required')


def bus(row, pid):
    match = re.fullmatch(r'DaemonIdentity: owner=(:\d+\.\d+) pid=(\d+) uid=0\n', row['stdout'])
    if row['exit'] or match is None or int(match[2]) != pid:
        raise CaptureError('bus-authenticated actual daemon identity required')
    return dict(owner=match[1], pid=pid, uid=0)


def record_phase(application, owners, phase, pid, killed_exit=None, folder=FOLDER):
    if 'ws73.daemon_crash=1' not in Path('/proc/cmdline').read_text().split() or not Path('/scratch-root-uuid').is_file():
        raise ValueError('explicit private native VM crash mode required')
    if phase not in ['before', 'free', 'after']:
        raise ValueError('explicit crash supervisor phase required')
    folder.mkdir(exist_ok=True)
    path = folder / 'run.json'
    record = json.loads(path.read_text()) if path.exists() else dict(version=1, status='RUNNING',
        phases=[], slctl=file_record('/bin/slctl'), physical_acceptance=False,
        automatic_recovery_acceptance=False, whole_managed_acceptance=False)
    expected = ['before', 'free', 'after']
    if [p['phase'] for p in record['phases']] != expected[:expected.index(phase)]:
        raise ValueError('ordered single crash supervisor phases required')
    entry = dict(phase=phase, pid=pid, owners=owners, start_wall_ns=time.time_ns(), commands=[])
    record['phases'].append(entry)
    def save(): path.write_text(json.dumps(record, indent=2)+'\n')
    def command(words, refusal=False):
        row = dict(args=words, start_wall_ns=time.time_ns())
        result = application(*words, capture_output=True, timeout=15)
        row.update(stdout=result.stdout, stderr=result.stderr, exit=result.returncode, end_wall_ns=time.time_ns())
        entry['commands'].append(row); save()
        if refusal:
            if (not row['exit'] or 'org.freedesktop.DBus.Error.UnknownObject' not in row['stderr']
                    or 'initializer provenance absent or invalidated' not in row['stderr']
                    or 'NativeOperationResult:' in row['stdout']):
                raise ValueError('successor must not reuse old initializer provenance')
        elif row['exit']: raise ValueError('actual ordinary crash-gate application failed: '+row['stderr'])
        return row
    try:
        if phase == 'free':
            if pid != record['phases'][0]['pid'] or killed_exit != 137 or Path(f'/proc/{pid}').exists():
                raise ValueError('original guest child must be SIGKILL-reaped with status137')
            entry['killed_exit'] = killed_exit
            entry['polls'] = []
            deadline = time.monotonic()+6
            while True:
                rows = [observation(o) for o in owners]
                entry['polls'].append(rows); save()
                try:
                    for o, row in zip(owners, rows): view(row, o, 0, 1, 1)
                    entry['observations'] = rows
                    break
                except CaptureError:
                    if time.monotonic() >= deadline: raise
                    time.sleep(.01)
        else:
            entry['daemon'] = daemon_identity(pid)
            entry['process_status'] = Path(f'/proc/{pid}/status').read_text()
            credentials = application('/bin/cat', '/proc/self/status', capture_output=True, timeout=3)
            if credentials.returncode: raise ValueError('ordinary application credentials unavailable')
            entry['application_status'] = credentials.stdout
            if phase == 'before':
                entry['bus'] = bus(command([record['slctl']['path'], 'daemon']), pid)
                for o, words, op in zip(owners, [('advertise', 'on'), ('scan', 'on')], [1, 3]):
                    parse_result(command([record['slctl']['path'], '--adapter', o['path'], *words])['stdout'], o, op)
                entry['observations'] = [observation(o) for o in owners]
                for o, row, powers in zip(owners, entry['observations'], [(2, 1), (1, 2)]): view(row, o, 1, *powers)
            else:
                if pid == record['phases'][0]['pid']: raise ValueError('new daemon PID required')
                # Ready is published only after actual per-device initializers.
                entry['ready_polls'] = []
                for o in owners:
                    deadline = time.monotonic()+12
                    while True:
                        row = application(record['slctl']['path'], '--adapter', o['path'], 'show', capture_output=True, timeout=3)
                        entry['ready_polls'].append(dict(identity=o,exit=row.returncode,stdout=row.stdout,stderr=row.stderr,wall_ns=time.time_ns())); save()
                        if not row.returncode and '  State:       Ready\n' in row.stdout: break
                        if time.monotonic() >= deadline: raise TimeoutError('successor actual Ready')
                        time.sleep(.02)
                entry['bus'] = bus(command([record['slctl']['path'], 'daemon']), pid)
                entry['observations'] = [observation(o) for o in owners]
                for o, row in zip(owners, entry['observations']): view(row, o, 1, 1, 1)
                for o in owners:
                    for domain in ['advertise', 'scan']:
                        command([record['slctl']['path'], '--adapter', o['path'], domain, 'initialized-off'], refusal=True)
                record['status'] = STATUS
        entry['end_wall_ns'] = time.time_ns(); save()
    except BaseException as error:
        record.update(status='FAIL', error=str(error)); save(); raise


def verify_records(record, run):
    if (record.get('version') != 1 or record.get('status') != STATUS
            or any(record.get(k) is not False for k in ['physical_acceptance', 'automatic_recovery_acceptance', 'whole_managed_acceptance'])
            or [p['phase'] for p in record['phases']] != ['before', 'free', 'after']
            or record['slctl'] != run['slctl']):
        raise CaptureError('separate completed native SIGKILL gate required')
    before, free, after = record['phases']
    previous = 0
    for entry in record['phases']:
        if len(entry['owners']) != 2 or any(not stable(a,b) for a,b in zip(entry['owners'], run['initial'])):
            raise CaptureError('same physical registrations/generations throughout crash required')
        if not previous < entry['start_wall_ns'] <= entry['end_wall_ns']: raise CaptureError('ordered crash phases required')
        previous = entry['end_wall_ns']
        if len(entry['observations']) != 2: raise CaptureError('two independent observer fds required')
        for i, (o, row) in enumerate(zip(entry['owners'],entry['observations'])):
            view(row, o, 0 if entry['phase']=='free' else 1, 2 if entry['phase']=='before' and i==0 else 1,
                2 if entry['phase']=='before' and i==1 else 1)
            if not entry['start_wall_ns'] <= row['start_wall_ns'] <= row['end_wall_ns'] <= entry['end_wall_ns']:
                raise CaptureError('observation outside actual phase')
    if (before['pid'] == after['pid'] or before['pid'] != free['pid'] or free['killed_exit'] != 137
            or after['daemon'] != run['daemon_before'] or after['bus'] != run['bus_before']
            or before['bus']['owner'] == after['bus']['owner'] or after['end_wall_ns']-before['end_wall_ns'] > 20_000_000_000):
        raise CaptureError('bounded reaped old daemon and authenticated same-generation successor required')
    if free['commands'] or len(before['commands']) != 3 or len(after['commands']) != 5:
        raise CaptureError('exact original active commands and successor provenance refusals required')
    if not free['polls'] or free['polls'][-1] != free['observations'] or free['end_wall_ns']-free['start_wall_ns'] > 7_000_000_000:
        raise CaptureError('bounded actual Free observation polls required')
    for entry in [before, after]:
        if entry['daemon']['pid'] != entry['pid'] or bus(entry['commands'][0], entry['pid']) != entry['bus']:
            raise CaptureError('daemon and bus identities disagree')
        if not re.search(r'^Name:\s+slkd$',entry['process_status'],re.M) or not re.search(r'^Uid:\s+0\s+0\s+0\s+0$',entry['process_status'],re.M):
            raise CaptureError('actual root daemon credentials required')
        if (not re.search(r'^Uid:\s+1000\s+1000\s+1000\s+1000$',entry['application_status'],re.M)
                or any(not re.search(r'^'+cap+r':\s+0+$',entry['application_status'],re.M) for cap in ['CapInh','CapPrm','CapEff','CapAmb'])):
            raise CaptureError('actual ordinary application without capabilities required')
        previous = entry['start_wall_ns']
        for i,row in enumerate(entry['commands']):
            if (row['exit'] != (1 if entry is after and i else 0)
                    or not previous <= row['start_wall_ns'] <= row['end_wall_ns'] <= entry['end_wall_ns']):
                raise CaptureError('actual ordered ordinary application commands required')
            previous = row['end_wall_ns']
    for o, row, words, op in zip(before['owners'],before['commands'][1:],[['advertise','on'],['scan','on']],[1,3]):
        if row['args'] != [record['slctl']['path'],'--adapter',o['path'],*words]: raise CaptureError('original active policy command mismatch')
        parse_result(row['stdout'],o,op)
    for i,row in enumerate(after['commands'][1:]):
        o=after['owners'][i//2];domain,op=('advertise',5) if i%2==0 else ('scan',6)
        if row['args'] != [record['slctl']['path'],'--adapter',o['path'],domain,'initialized-off']: raise CaptureError('successor original initializer read mismatch')
        if ('org.freedesktop.DBus.Error.UnknownObject' not in row['stderr']
                or 'initializer provenance absent or invalidated' not in row['stderr']
                or 'NativeOperationResult:' in row['stdout']):
            raise CaptureError('successor must actually refuse old initializer provenance')
    first=run['commands'][run['rounds'][0]['command_indices'][0]]
    if after['end_wall_ns'] >= first['start_wall_ns']: raise CaptureError('crash gate must finish before ordinary RF22')
    return before, free, after


def corroborate(record, run, capture):
    before, free, after = verify_records(record,run)
    recipes=[]
    for owner,row,opcodes in zip(before['owners'],before['commands'][1:],[[0x0c02,0x0c03,0x0c05],[0x1001,0x1002]]):
        recipe=[]
        for opcode in opcodes:
            params={0x0c05:bytes([1,0,0,0,0]),0x1002:bytes([1,0])}.get(opcode)
            recipe.append(command_reply(capture,owner,opcode,row['start_wall_ns'],row['end_wall_ns'],params,None if opcode==0x0c02 else ''))
        if opcodes[0]==0x0c02:
            accepted=re.findall(r'^NativeAdvertisementAccepted: request=(\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+)$',row['stdout'],re.M)
            if len(accepted)!=1 or int(accepted[0][0])!=parse_result(row['stdout'],owner,1)['request'] or accepted[0][2]!=marker_data(accepted[0][1]).hex() or bytes.fromhex(recipe[1]['command']['params'])!=bytes([0,3,len(marker_data(accepted[0][1]))])+marker_data(accepted[0][1]):
                raise CaptureError('original active advertisement random data must match wire')
        recipes.append(recipe)
    cleanup=[]
    start=before['end_wall_ns'];end=free['end_wall_ns']
    for owner,opcode,params in zip(before['owners'],[0x0c05,0x1002],[b'\0'*5,b'\0\0']):
        traffic=[c for c in capture['commands'] if (c['bus'],c['device'])==(owner['bus'],owner['device']) and start<=c['wall_ns']<=end]
        if len(traffic)!=1 or traffic[0]['opcode']!=opcode: raise CaptureError('last-File close must emit only the required selected STOP')
        cleanup.append(command_reply(capture,owner,opcode,start,end,params,''))
    fresh=[c for c in capture['commands'] if free['end_wall_ns']<=c['wall_ns']<=after['end_wall_ns']]
    if fresh: raise CaptureError('same-generation successor must reuse actual Ready without redundant initialization or STOP')
    return dict(scope='actual active two-device SIGKILL last-File cleanup and same-generation successor before RF22',
        active_recipes=recipes,cleanup_recipes=cleanup,successor_initializer_refusals=4,successor_device_commands=0,
        old_daemon_reaped=True,same_generations=True,new_daemon_and_bus=True,
        selected_cleanup_commands=2,physical_acceptance=False,automatic_recovery_acceptance=False,
        whole_managed_acceptance=False,held_inflight_acceptance=False)
