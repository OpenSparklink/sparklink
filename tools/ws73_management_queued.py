#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit VM-only never-selected Managed queue release/last-file-close gate."""
import argparse
import ctypes
import errno
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / ('python' if (HERE.parent / 'python').is_dir() else 'bindings/python')))
from sparklink.native import NativeAdapter
from sparklink.structs import SleControllerSnapshot, SleDiscoveryResult, SleDiscoverySubmit, SleManagementQuery
from ws73_diagnostic_hold import write_marker


def decode(kind, raw):
    if not isinstance(raw, str) or len(raw) != ctypes.sizeof(kind)*2 or not re.fullmatch('[0-9a-f]+', raw):
        raise ValueError('complete canonical UAPI bytes required')
    return kind.from_buffer_copy(bytes.fromhex(raw))


def setup(raw, index, generation=None):
    s = decode(SleControllerSnapshot, raw)
    if (s.version != 1 or s.flags != 2 or s.profile != 1 or s.valid_fields != 1 or s.error
            or s.dev_index != index or not s.generation or (generation is not None and s.generation != generation)):
        raise ValueError('exact untouched Setup snapshot required')
    return s


def metadata_ready(share):
    path = Path(share)/'setup-release/metadata-0.json'
    if not path.exists():
        return False
    value = json.loads(path.read_text())
    if set(value) != {'slot', 'initial_snapshot'} or type(value['slot']) is not int or value['slot'] != 0:
        raise ValueError('exact Setup metadata marker required')
    setup(value['initial_snapshot'], 0)
    return True


def query(raw, generation, state):
    q = decode(SleManagementQuery, raw)
    if (q.version != 1 or q.generation != generation or q.state != state or q.mode != (1 if state == 1 else 0)
            or any([q.lease, q.flags, q.error, q.status, q.opcode, q.reserved])):
        raise ValueError('independent lease observer state required')


def verify_records(record):
    synthetic = record.get('synthetic_support', False)
    confirmed=record.get('confirmed_off',False)
    ready_peer=record.get('ready_peer',False)
    if type(ready_peer) is not bool or ready_peer and (confirmed is not True or synthetic is not False):raise ValueError('Ready peer requires real confirmed-Off queued gate')
    if type(confirmed) is not bool:raise ValueError('exact confirmed-Off scope required')
    if type(synthetic) is not bool:
        raise ValueError('exact synthetic evidence scope required')
    prefix='QUEUED_CONFIRMED_OFF_INITIALIZE_RELEASE' if confirmed else 'QUEUED_UNKNOWN_SETUP_RELEASE'
    expected_status=prefix+('_SYNTHETIC_SUPPORT_PASS' if synthetic else '_LIVE_PASS')
    if (type(record.get('format_version')) is not int or record.get('format_version') != (4 if ready_peer else 3 if confirmed else 2)
            or record.get('status') != expected_status
            or type(record.get('probe_exit')) is not int or record.get('probe_exit') != 0 or record.get('daemon_running') is not False
            or record.get('physical_acceptance') is not False or record.get('automatic_fault_recovery_acceptance') is not False):
        raise ValueError('limited Setup lease gate format required')
    snapshots = record['initial_snapshots']
    if len(snapshots) != 2:
        raise ValueError('two independent Setup registrations required')
    identities = [setup(raw, index) for index, raw in enumerate(snapshots)]
    if identities[0].generation == identities[1].generation:
        raise ValueError('independent generations required')
    expected_snapshots=list(snapshots)
    bootstrap=record.get('bootstrap',[])
    if confirmed:
        if len(bootstrap)!=2:raise ValueError('two original complete bootstrap records required')
        from ws73_management_partial import standby
        last=0
        for index,row in enumerate(bootstrap):
            snapshot=identities[index];generation=snapshot.generation
            if row.get('bootstrap') is not True or type(row['index']) is not int or row['index']!=index:
                raise ValueError('exact bootstrap identities required')
            if (row['advertising_input']!=bytes(standby(snapshot,1000,'advertising')).hex()
                    or row['scanning_input']!=bytes(standby(snapshot,1001,'scanning')).hex()):
                raise ValueError('actual complete typed initialization inputs required')
            adv=decode(SleDiscoveryResult,row['advertising_result'])
            if not -128<=adv.selected_power<=127:raise ValueError('actual bootstrap power required')
            expected=SleDiscoveryResult(version=1,generation=generation,request_id=1000,profile=1,dev_index=index,operation=5,state=3,count=2,step=1,opcode=0xc05,radio_adv=1,power_valid=1,selected_power=adv.selected_power)
            if bytes(adv)!=bytes(expected):raise ValueError('advertising bootstrap must complete successfully')
            expected=SleDiscoveryResult(version=1,generation=generation,request_id=1001,profile=1,dev_index=index,operation=6,state=3,count=3,step=2,opcode=0x1002,radio_adv=1,radio_scan=1)
            if row['scanning_result']!=bytes(expected).hex():raise ValueError('complete scan parameter/START/STOP bootstrap required')
            ready=SleControllerSnapshot.from_buffer_copy(bytes(snapshot));ready.flags=1
            expected_snapshots[index]=bytes(ready).hex()
            if row['ready_snapshot']!=expected_snapshots[index]:raise ValueError('exact same-generation Ready metadata required')
            expected=SleDiscoveryResult(version=1,generation=generation,profile=1,dev_index=index,radio_adv=1,radio_scan=1)
            if row['radio']!=bytes(expected).hex():raise ValueError('both actually confirmed Off required')
            if (type(row['start_wall_ns']) is not int or type(row['end_wall_ns']) is not int
                    or not last<row['start_wall_ns']<row['end_wall_ns'] or row['end_wall_ns']-row['start_wall_ns']>2_000_000_000):
                raise ValueError('bounded ordered bootstrap required')
            last=row['end_wall_ns']
    elif bootstrap:raise ValueError('untouched Setup cannot carry initialized bootstrap')
    cases = record['cases']
    expected = [(i, kind) for i in [0, 1] for kind in ['explicit-release', 'last-fd-close', 'dup-last-fd-close']]
    if [(v['index'], v['case']) for v in cases] != expected:
        raise ValueError('both roles and all three real file cases required')
    previous = bootstrap[-1]['end_wall_ns'] if confirmed else 0
    for case_number, v in enumerate(cases):
        if not all(type(v[k]) is int for k in ['index', 'generation', 'peer_index', 'peer_generation', 'wrong_token_errno']):
            raise ValueError('exact integer identity and error fields required')
        index = v['index']; peer = 1-index; generation = identities[index].generation
        if (v['peer_index'] != peer or v['generation'] != generation or v['peer_generation'] != identities[peer].generation
                or type(v['start_wall_ns']) is not int or type(v['end_wall_ns']) is not int
                or not previous < v['start_wall_ns'] < v['end_wall_ns']
                or not 340_000_000 <= v['end_wall_ns']-v['start_wall_ns'] <= 5_000_000_000):
            raise ValueError('ordered bounded real release intervals required')
        previous = v['end_wall_ns']
        if (v['scheduler_restored'] is not True or type(v['critical_start_ns']) is not int
                or type(v['critical_end_ns']) is not int
                or not v['start_wall_ns'] <= v['critical_start_ns'] < v['critical_end_ns'] <= v['end_wall_ns']
                or v['critical_end_ns']-v['critical_start_ns'] >= 50_000_000):
            raise ValueError('bounded FIFO section and restored normal scheduling required')
        if len(v['queued']) != 2 or len(v['cancelled']) != 2:
            raise ValueError('both actual typed policy domains required')
        for domain in range(2):
            for key, state, error in [('queued', 1, 0), ('cancelled', 5, -errno.ECANCELED)]:
                result = decode(SleDiscoveryResult, v[key][domain])
                expected = SleDiscoveryResult(version=1, generation=generation,
                    request_id=(case_number%3)*2+1+domain,
                    profile=1, operation=(5, 6 if confirmed else 4)[domain], count=(2, 3 if confirmed else 1)[domain],
                    radio_adv=int(confirmed),radio_scan=int(confirmed),
                    dev_index=index, state=state, error=error)
                if bytes(result) != bytes(expected):
                    raise ValueError('full Queued to Cancelled UAPI with no selected opcode/step required')
        rejected = v['scan_initialize_rejections']
        if len(rejected) != (0 if confirmed else 2):
            raise ValueError('Unknown and pending-advertising scan admission guards required')
        for n, row in enumerate(rejected):
            expected = SleDiscoverySubmit(version=1, generation=generation, profile=1,
                                          request_id=(n+1)*100+case_number%3, operation=6)
            expected.scanning.frame_types = 1
            expected.scanning.interval = 1600
            expected.scanning.window = 800
            if (bytes(decode(SleDiscoverySubmit, row['input'])) != bytes(expected)
                    or type(row['submit_errno']) is not int or row['submit_errno'] != errno.EBUSY
                    or type(row['result_errno']) is not int or row['result_errno'] != errno.ENOENT):
                raise ValueError('rejected scan initialization must remain unadmitted, without a result')
        for a, b, raw in [('snapshot_before', 'snapshot_after', expected_snapshots[index]), ('peer_before', 'peer_after', expected_snapshots[peer])]:
            if v[a] != v[b] or v[a] != raw:
                raise ValueError('full Setup metadata and survivor must remain unchanged')
        if v['radio_before'] != v['radio_after']:
            raise ValueError('radio state changed during no-policy lease')
        radio = decode(SleDiscoveryResult, v['radio_after'])
        if confirmed and v['radio_after']!=bytes(SleDiscoveryResult(version=1,generation=generation,profile=1,dev_index=index,radio_adv=1,radio_scan=1)).hex():raise ValueError('complete confirmed-Off radio UAPI required')
        if radio.version != 1 or radio.generation != generation or radio.radio_adv!=int(confirmed) or radio.radio_scan!=int(confirmed) or radio.error:
            raise ValueError('lease release must preserve Unknown and not invent Off')
        query(v['held'], generation, 1); query(v['free'], generation, 0)
        if type(v['writer_fd']) is not int or v['writer_fd'] < 0 or type(v['duplicate_fd']) is not int:
            raise ValueError('actual file descriptors required')
        if v['case'] == 'dup-last-fd-close':
            if v['duplicate_fd'] < 0 or v['duplicate_fd'] == v['writer_fd']:
                raise ValueError('distinct dup reference required')
            query(v['after_first_close'], generation, 1)
        elif v['duplicate_fd'] != -1 or set(v['after_first_close']) != {'0'}:
            raise ValueError('unexpected duplicate reference')
        if v['wrong_token_errno'] != (errno.EPERM if v['case'] == 'explicit-release' else 0):
            raise ValueError('wrong token must remain rejected')
    if ready_peer:
        from ws73_management_queue_ready_peer import verify as verify_ready_peer
        verify_ready_peer(record,identities)
    return identities


def corroborate(record, capture):
    snapshots=verify_records(record)
    ready_peer=record.get('ready_peer',False)
    start = record['cases'][0]['start_wall_ns']; end = record['cases'][-1]['end_wall_ns']
    # Include gaps and both registrations, not just each release syscall.
    traffic = [v for kind in ['commands', 'complete', 'failures'] for v in capture[kind]
               if start <= v['wall_ns'] <= end]
    if ready_peer:
        traffic=[v for v in traffic if any(row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns'] for row in record['cases'])]
    if traffic:
        raise ValueError('untouched release emitted controller command/reply traffic')
    bootstrap=[]
    if record.get('confirmed_off',False):
        for row in record['bootstrap']:
            index=row['index']
            if not ready_peer and any(v['bus']==1 and v['device']==index+2 and row['end_wall_ns']<=v['wall_ns']<=end for kind in ['commands','complete','failures'] for v in capture[kind]):raise ValueError('no mutation after original confirmed-Off bootstrap permitted')
            snapshot=decode(SleControllerSnapshot,record['initial_snapshots'][index]);commands=[v for v in capture['commands'] if v['bus']==1 and v['device']==index+2 and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
            if [v['opcode'] for v in commands]!=[0xc02,0xc05,0x1001,0x1002,0x1002]:raise ValueError('complete captured bootstrap wire order required')
            adv=bytes.fromhex(commands[0]['params'])
            if len(adv)!=49 or adv[0]!=0 or adv[12:18]!=bytes(snapshot.address) or [v['params'] for v in commands[1:]]!=['0000000000','0000010040062003','0100','0000']:raise ValueError('qualified original bootstrap parameters required')
            original_replies=[]
            for n,command in enumerate(commands):
                stop=commands[n+1]['wall_ns'] if n+1<len(commands) else row['end_wall_ns']
                replies=[v for v in capture['complete'] if (v['bus'],v['device'],v['opcode'])==(command['bus'],command['device'],command['opcode']) and command['completion']['wall_ns']<=v['wall_ns']<stop]
                if len(replies)!=1 or replies[0]['status']!=0:raise ValueError('original successful bootstrap Complete required')
                value=bytes([decode(SleDiscoveryResult,row['advertising_result']).selected_power&255]).hex() if command['opcode']==0xc02 else ''
                if replies[0]['value']!=value:raise ValueError('bootstrap reply/power mismatch')
                original_replies.append(replies[0]);bootstrap.append(dict(command=command,reply=replies[0]))
            all_replies=[v for v in capture['complete'] if v['bus']==1 and v['device']==index+2 and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns']]
            if original_replies!=all_replies or any(v['bus']==1 and v['device']==index+2 and row['start_wall_ns']<=v['wall_ns']<=row['end_wall_ns'] for v in capture['failures']):raise ValueError('no extra or failed bootstrap reply permitted')
    peer_proof=None
    if ready_peer:
        from ws73_management_queue_ready_peer import corroborate as corroborate_ready_peer
        peer_proof=corroborate_ready_peer(record,snapshots,capture,bootstrap)
    return {'ready_peer_activity':peer_proof,'bootstrap':bootstrap,'confirmed_off':record.get('confirmed_off',False),'scope': 'six actual queued two-domain cancellations; one vCPU and privileged bounded FIFO support; whole interval and both devices' ,
            'cases': 6, 'commands': 0, 'completions': 0, 'failures': 0,
            'start_wall_ns': start, 'end_wall_ns': end,
            'synthetic_support': record.get('synthetic_support', False),
            'managed_preselection_live_acceptance': False,
            'managed_unknown_setup_preselection_live_acceptance': not record.get('synthetic_support', False) and not record.get('confirmed_off',False),
            'managed_preselection_synthetic_support_acceptance': record.get('synthetic_support', False),
            'active_ready_peer_isolation_acceptance': peer_proof is not None,
            'normal_scheduler_concurrency_acceptance': False, 'setup_preserved': not record.get('confirmed_off',False),'confirmed_off_preserved':record.get('confirmed_off',False), 'peer_snapshot_preserved': True,
            'partial_initialization_cleanup_acceptance': False, 'held_transport_fd_close_acceptance': False,
            'automatic_fault_recovery_acceptance': False}


def save_record(folder, record):
    """Progress is replaceable; peer-attachment handshake markers are one-shot."""
    temporary = Path(folder)/'run.tmp'
    temporary.write_text(json.dumps(record, indent=2)+'\n')
    temporary.replace(Path(folder)/'run.json')


def run(args):
    synthetic = bool(getattr(args, 'synthetic_support', False))
    confirmed=bool(getattr(args,'confirmed_off',False))
    ready_peer=bool(getattr(args,'ready_peer',False))
    cmdline = Path('/proc/cmdline').read_text().split()
    if ready_peer!=('ws73.managed_queue_ready_peer=1' in cmdline) or ready_peer and (not confirmed or synthetic):raise ValueError('matching real confirmed-Off Ready peer boot mode required')
    if confirmed!=('ws73.managed_queue_confirmed_off=1' in cmdline):raise ValueError('explicit matching confirmed-Off boot mode required')
    if synthetic != ('ws73.managed_queue_support=1' in cmdline):
        raise ValueError('explicit matching synthetic boot and collector required')
    if synthetic and (Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU'
                      or not Path('/scratch-root-uuid').is_file()):
        raise ValueError('synthetic support requires dedicated QEMU scratch VM')
    if 'ws73.managed_queue=1' not in Path('/proc/cmdline').read_text().split() or subprocess.run(['/bin/pidof','slkd'],capture_output=True).returncode == 0:
        raise ValueError('explicit VM mode before daemon startup required')
    folder = args.output; folder.mkdir(parents=True, exist_ok=False)
    record = {'format_version': 4 if ready_peer else 3 if confirmed else 2,'confirmed_off':confirmed,'bootstrap':[], 'status': 'RUNNING', 'daemon_running': False,
              'synthetic_support': synthetic,
              'physical_acceptance': False, 'automatic_fault_recovery_acceptance': False,
              'initial_snapshots': [], 'cases': []}
    if ready_peer:record.update(ready_peer=True,peer_activities=[],peer_releases=[])
    def save():
        save_record(folder, record)
    adapters = []
    try:
        for index in [0, 1]:
            deadline = time.monotonic()+90
            while True:
                adapter = None
                try:
                    adapter = NativeAdapter(index); snapshot = adapter.snapshot()
                    setup(bytes(snapshot).hex(), index)
                    break
                except OSError as error:
                    if error.errno not in (errno.ENODEV, errno.EAGAIN):
                        raise
                    if adapter is not None:
                        adapter.close()
                if time.monotonic() > deadline:
                    raise TimeoutError('independent Setup metadata availability')
                time.sleep(0.01)
            adapters.append(adapter); record['initial_snapshots'].append(bytes(snapshot).hex()); save()
            if index == 0:
                write_marker(folder/'metadata-0.json', {'slot': 0, 'initial_snapshot': bytes(snapshot).hex()})
        command = [str(args.probe), *[str(a.generation) for a in adapters]]
        if confirmed:command.append('--confirmed-off')
        if ready_peer:command.append('--ready-peer')
        with (folder/'probe.jsonl').open('w') as out, (folder/'probe-stderr.txt').open('w') as err:
            p = subprocess.run(command, stdout=out, stderr=err, timeout=15)
        record['probe_exit'] = p.returncode
        lines=[json.loads(line) for line in (folder/'probe.jsonl').read_text().splitlines()]
        record['bootstrap']=[v for v in lines if v.get('bootstrap') is True]
        record['cases']=[v for v in lines if not any(v.get(k) is True for k in ['bootstrap','peer_activity','peer_release'])]
        if ready_peer:
            record['peer_activities']=[v for v in lines if v.get('peer_activity') is True]
            record['peer_releases']=[v for v in lines if v.get('peer_release') is True]
        if p.returncode:
            raise ValueError('real release/last-file-close probe failed')
        record['status']=('QUEUED_CONFIRMED_OFF_INITIALIZE_RELEASE' if confirmed else 'QUEUED_UNKNOWN_SETUP_RELEASE')+('_SYNTHETIC_SUPPORT_PASS' if synthetic else '_LIVE_PASS')
        verify_records(record); save()
        print('WS73_TARGET_MANAGED_QUEUE_SYNTHETIC_SUPPORT_PASS' if synthetic
              else 'WS73_TARGET_MANAGED_QUEUE_PASS', flush=True)
    except BaseException as error:
        record['status'] = 'FAIL'; record['error'] = str(error); save(); raise
    finally:
        for adapter in adapters:
            adapter.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, default=Path('/bin/managed-queue-probe'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ready-peer',action='store_true',help='real Ready Managed scanner On across every queued cancellation')
    parser.add_argument('--confirmed-off',action='store_true',help='actual complete bootstraps before full scan initializer queue cancellation')
    parser.add_argument('--synthetic-support', action='store_true',
                        help='dedicated simulated USB VM; never live hardware acceptance')
    run(parser.parse_args())
