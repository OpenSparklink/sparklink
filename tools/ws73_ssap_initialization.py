# SPDX-License-Identifier: GPL-2.0-only
"""Real CMTC-pending lease withdrawal; sole production initializer/Engine.

The test retains an original IN81 aggregate, not a fabricated protocol result.
FD inode observations are daemon-fd convergence, not kernel reference/UAF proof.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time

from ws73_capture import CaptureError
from ws73_channel_prefix_hold import PrefixBarrier
from ws73_daemon_hold import Invocation, management_observed
from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker, corroborate_host_hold

QEMU_SHA256 = '1622d935beca86ed20d6413e569c4e8ff676c7d262ec768b5e8d1191067cd832'
METHOD = 'REAL_CMTC_PENDING_MANAGED_WITHDRAWAL'
SELECTOR = 'test-runtime-cmtc-capability'
RESPONSE = '0200100002000c00e20000000000fa07ff070101'


def requested(args):
    enabled = bool(getattr(args, 'ssap_initialization_verify', False))
    if enabled and (not getattr(args, 'passthrough', False) or not getattr(args, 'connection_verify', False)
            or not getattr(args, 'channel_socket_verify', False)
            or getattr(args, 'channel_socket_bytes', 61) != 61 or getattr(args, 'channel_socket_rounds', 4) != 4
            or any(getattr(args, key, False) for key in ['ssap_owner_lifecycle_verify', 'ssap_requester_lifecycle_verify',
                'ssap_owned_verify', 'security_agent', 'channel_socket_burst', 'channel_socket_close_prefix',
                'channel_socket_boundaries', 'dynamic_channel_verify', 'channel_fairness_verify',
                'application_client_verify', 'channel_benchmark', 'daemon_link_resync'])):
        raise ValueError('SSAP initialization requires separate real connection and ordinary basic socket preservation')
    return enabled


def validate_qemu(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != QEMU_SHA256:
        raise ValueError('exact reviewed bounded2s CMTC-selector QEMU required')


class SelectedHold(HoldCoordinator):
    def snapshot(self, monitor):
        for name, expected in [(SELECTOR, True), ('test-runtime-in-skip-requested', 0),
                               ('test-runtime-in-skip-remaining', 0), ('test-runtime-in-skipped', 0),
                               ('test-enumeration-reset-once', False)]:
            value = monitor.execute('qom-get', {'path': self.path, 'property': name})
            if type(value) is not type(expected) or value != expected:
                raise ValueError('exact CMTC-only selector without reset/skip required')
        return super().snapshot(monitor)


class Coordinator:
    def __init__(self, share, record, qemu):
        validate_qemu(qemu)
        self.root = Path(share)/'application/passthrough-control/ssap-initialization'
        self.record = record
        record.update(method=METHOD, qemu_sha256=QEMU_SHA256, hold_budget_ms=2000,
                      phases=[], complete=False, physical_acceptance=False,
                      automatic_fault_recovery_acceptance=False)
        self.child = None
        self.used = []

    def poll(self, monitor, owner):
        if self.record['complete']:
            return
        number = len(self.used)
        if self.child is None:
            folder = self.root/f'phase-{number}'
            path = folder/'selection.json'
            if not path.exists() or not (folder/'hold-arm_ready.json').exists():
                return
            selection = json.loads(path.read_text())
            index = selection.get('index')
            slot = selection.get('slot')
            if (set(selection) != {'phase', 'slot', 'index', 'generation', 'controller_path', 'role'}
                    or type(selection['phase']) is not int or selection['phase'] != number
                    or type(selection['role']) is not int or selection['role'] != number or type(index) is not int
                    or not 0 <= index < 16 or type(slot) is not int or slot != number or slot in self.used
                    or type(selection['generation']) is not int or selection['generation'] < 1
                    or selection['controller_path'] != f"/org/sparklink/slk{index}_g{selection['generation']}"):
                raise ValueError('fresh exact two-role controller selection required')
            child = SelectedHold(folder, {})
            child.folder = folder
            child.path = f'/machine/peripheral/ws73_{slot}'
            if monitor.execute('qom-get', {'path': child.path, 'property': SELECTOR}) is not False:
                raise ValueError('fresh disabled CMTC selector required')
            identity = owner(slot)
            monitor.execute('qom-set', {'path': child.path, 'property': SELECTOR, 'value': True})
            child.record.update(selection=selection, host_identity_at_arm=identity)
            self.record['phases'].append(child.record)
            self.child = child
        self.child.poll(monitor)
        if self.child.phase == 'done':
            self.used.append(self.child.record['selection']['slot'])
            self.child = None
            self.record['complete'] = len(self.used) == 2


def sockets(pid):
    values = []
    for fd in (Path('/proc')/str(pid)/'fd').iterdir():
        try:
            link = os.readlink(fd)
        except FileNotFoundError:
            continue
        if link.startswith('socket:['):
            values.append(dict(fd=int(fd.name), inode=link))
    return dict(wall_ns=time.time_ns(), sockets=sorted(values, key=lambda v: v['fd']))


def inodes(value):
    rows = value['sockets']
    if (not isinstance(rows, list) or len(rows) > 128
            or any(set(v) != {'fd', 'inode'} or type(v['fd']) is not int or v['fd'] < 0
                   or not re.fullmatch(r'socket:\[\d+\]', v['inode']) for v in rows)
            or len({v['fd'] for v in rows}) != len(rows)):
        raise CaptureError('bounded actual socket-inode observations required')
    return {v['inode'] for v in rows}


class FdClient:
    """Request read-only VM-root evidence; never ask the daemon to expose fds."""
    def __init__(self, run):
        self.run = run
        self.sequence = 0
        self.folder = run.output/'ssap-initialization-fd-requests'
        self.folder.mkdir(exist_ok=False)

    def snapshot(self, phase, stage):
        request = dict(sequence=self.sequence, phase=phase, stage=stage, wall_ns=time.time_ns())
        write_marker(self.folder/f'{self.sequence}.json', request)
        path = Path('/evidence/ssap-initialization-fds')/f'{self.sequence}.json'
        limit = time.monotonic()+2
        while not path.exists():
            self.run.alive()
            if time.monotonic() >= limit:
                raise TimeoutError('original read-only fd supervisor request')
            time.sleep(.005)
        value = json.loads(path.read_text())
        if (value['request'] != request or value['daemon']['pid'] != self.run.args.slkd_pid
                or value['supervisor_uid'] != 0):
            raise CaptureError('original fixed-daemon VM-root fd receipt required')
        inodes(value)
        self.sequence += 1
        return value


def observe_fds(root, pid):
    """Eight fixed-stage snapshots, VM root only; no fd duplicate/ioctl/USB I/O."""
    from ws73_north_star import daemon_identity
    if os.geteuid() != 0:
        raise ValueError('read-only VM root supervisor required')
    root = Path(root)
    output = root/'ssap-initialization-fds'
    output.mkdir(mode=0o755, exist_ok=False)
    source = root/'application/passthrough-control/ssap-initialization-fd-requests'
    original = daemon_identity(pid)
    deadline = time.monotonic()+120
    for number in range(8):
        path = source/f'{number}.json'
        while not path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('bounded eight-stage fd supervisor')
            if daemon_identity(pid) != original:
                raise ValueError('original daemon changed before fd snapshot')
            time.sleep(.005)
        request = json.loads(path.read_text())
        if (set(request) != {'sequence', 'phase', 'stage', 'wall_ns'}
                or type(request['sequence']) is not int or type(request['phase']) is not int
                or request['sequence'] != number or request['phase'] != number//4
                or request['stage'] != ['before', 'bound', 'withdrawn', 'after-down'][number % 4]
                or type(request['wall_ns']) is not int or request['wall_ns'] <= 0):
            raise ValueError('fixed original per-phase fd request order required')
        if daemon_identity(pid) != original:
            raise ValueError('daemon changed during fd observation')
        value = sockets(pid) | dict(request=request, daemon=original, supervisor_uid=os.geteuid())
        inodes(value)
        write_marker(output/f'{number}.json', value)
    print('WS73_SSAP_INIT_FDS_FINISHED', flush=True)


def execute(run, a, b):
    from ws73_connection_control import connect_phase, observe_phase_down
    from ws73_connection_objects import info
    from ws73_channel_socket import credentials
    record = dict(status='RUNNING', mode=METHOD, phases=[], new_engine=False,
                  physical_acceptance=False, automatic_recovery_acceptance=False)
    run.data['ssap_initialization'] = record
    previous = []
    fd_observer = FdClient(run)
    for n, target in enumerate((a, b)):
        # Cover withdrawal on initiating slot0 and accepting slot1. The
        # ordinary preservation gate subsequently exchanges both radio roles.
        caller, peer = a, b
        other = b if n == 0 else a
        phase = dict(caller=caller, peer=peer, target=target, other=other, start_wall_ns=time.time_ns())
        record['phases'].append(phase)
        # Establish the same real advertisement, discovery, Create and typed
        # publication as the ordinary gate; only the CMTC hold is additional.
        phase['fds_before'] = fd_observer.snapshot(n, 'before')
        parent = run.output/'ssap-initialization'
        parent.mkdir(exist_ok=True)
        hold = PrefixBarrier(phase, run.save, parent/f'phase-{n}', field='hold')
        selection = dict(phase=n, slot=n, index=target['index'], generation=target['generation'],
                         controller_path=target['path'], role=n)
        phase['selection'] = selection
        write_marker(hold.folder/'selection.json', selection)
        # Arm before Create so the real first capability response cannot race
        # ahead of a post-publication observer.
        hold.stage('arm_ready', 'armed')
        connect_phase(run, phase, run.args.connection_advertising, previous, n)
        selected = next(v['object'] for v in phase['typed_objects'] if v['owner'] == target)
        if selected['role'] != n:
            raise CaptureError('actual initiating/accepting target role must match original selection')
        hold.stage('wait_held', 'held')
        phase['fds_bound'] = fd_observer.snapshot(n, 'bound')
        if (not inodes(phase['fds_before']) <= inodes(phase['fds_bound'])
                or len(inodes(phase['fds_bound']) - inodes(phase['fds_before'])) != 2):
            raise CaptureError('two actual daemon socket additions after both eager SMTC binds required')
        pending = Invocation([str(run.args.slctl), '--adapter', target['path'], 'cancel-discovery'], 'cancel')
        phase['cancel'] = pending.row
        phase['cancel']['credentials'] = credentials(pending.process.pid)
        phase['disconnect_command'] = len(run.data['commands'])
        run.data['commands'].append(pending.row)
        run.save()
        try:
            if pending.identifier() != target['generation']:
                raise CaptureError('original controller cancellation marker required')
            phase['revocation_polls'] = []
            limit = time.monotonic()+1
            while True:
                row = run.ctl(target, 'management')
                phase['revocation_polls'].append(row)
                state = management_observed(row, target, None)
                if state == 2:
                    break
                if state != 1 or time.monotonic() >= limit:
                    raise CaptureError('actual kernel Revoking before original USB release required')
            phase['still_connected'] = run.ctl(target, 'connection-info', selected['path'])
            if phase['still_connected']['exit'] or phase['still_connected']['stderr']:
                raise CaptureError('successful current physical-link observation before release required')
            info(phase['still_connected']['stdout'], selected)
            phase['failed_owner'] = run.ctl(target, 'ssap-info', selected['path'])
            owner_failure(phase['failed_owner'], target, selected)
            phase['fds_withdrawn'] = fd_observer.snapshot(n, 'withdrawn')
            before, bound, withdrawn = map(inodes, [phase['fds_before'], phase['fds_bound'], phase['fds_withdrawn']])
            if not before <= withdrawn <= bound or not (bound-before)-withdrawn:
                raise CaptureError('original socket must converge while its real capability reply remains held')
            phase['other_during_revoke'] = run.ctl(other, 'show')
            if (phase['other_during_revoke']['exit'] or '  State:       Ready\n' not in phase['other_during_revoke']['stdout']
                    or f"  Generation:  {other['generation']}\n" not in phase['other_during_revoke']['stdout']):
                raise CaptureError('unheld peer controller must retain independent Ready generation')
            phase['cancel_pending_before_release'] = pending.process.poll() is None
            if not phase['cancel_pending_before_release']:
                raise CaptureError('withdrawal must retain actual cleanup obligation before USB release')
            hold.release()
            pending.finish()
            cancellation(pending.row, target)
        finally:
            if pending.process.poll() is None:
                pending.finish(kill=True)
            run.save()
        observe_phase_down(run, phase)
        phase['fds_after_down'] = fd_observer.snapshot(n, 'after-down')
        if phase['fds_after_down']['sockets'] != phase['fds_before']['sockets']:
            raise CaptureError('all added daemon socket inodes must retire after actual two-end Down')
        phase['management_after'] = run.ctl(target, 'management')
        management_observed(phase['management_after'], target, 1)
        phase['end_wall_ns'] = time.time_ns()
        previous = phase['typed_objects']
        run.save()
    record['status'] = 'CMTC_REVOCATION_EVIDENCE_PENDING'
    verify_guest(run.data)
    run.save()


def owner_failure(row, owner, reference):
    # Runtime session admission rejects the revoked epoch with EACCES (sle_sessions::session_limits).
    # A timeout, absent object or successful cached negotiation cannot substitute.
    if (not isinstance(row.get('exit'), int) or row['exit'] <= 0
            or row['args'][-2:] != ['ssap-info', reference['path']]
            or row['stdout'] != f"Selected {owner['path']}\n"
            or 'org.freedesktop.DBus.Error.Failed' not in row['stderr']
            or row['stderr'].count('Permission denied (os error 13)') != 1):
        raise CaptureError('actual current owner EACCES before capability release required')


def cancellation(row, owner):
    lines = [f"Selected {owner['path']}",
             f"NativePoliciesCancelRequest: generation={owner['generation']}",
             f"NativePoliciesCancelled: generation={owner['generation']}"]
    if (row.get('exit') != 0 or row.get('stderr') or row.get('stdout', '').splitlines() != lines
            or row['args'][-1:] != ['cancel-discovery']):
        raise CaptureError('actual completed per-controller Managed cleanup/reacquisition required')


def verify_guest(run):
    from ws73_connection_objects import info
    record = run['ssap_initialization']
    if (record.get('mode') != METHOD or record.get('status') != 'CMTC_REVOCATION_EVIDENCE_PENDING'
            or len(record.get('phases', [])) != 2 or record.get('new_engine') is not False
            or record.get('physical_acceptance') is not False or record.get('automatic_recovery_acceptance') is not False):
        raise CaptureError('both bounded actual CMTC role phases required')
    used = set()
    for n, phase in enumerate(record['phases']):
        caller = phase['target']
        if (type(caller['index']) is not int or not 0 <= caller['index'] < 16
                or type(caller['generation']) is not int or caller['generation'] < 1):
            raise CaptureError('actual typed original controller identity required')
        used.add(n)
        if caller != run['initial'][n]:
            raise CaptureError('explicit original guest port/physical slot binding required')
        if phase['selection'] != dict(phase=n, slot=n, index=caller['index'], generation=caller['generation'], controller_path=caller['path'], role=n):
            raise CaptureError('original role/registration selection required')
        reference = next(v['object'] for v in phase['typed_objects'] if v['owner'] == caller)
        if reference['role'] != n:
            raise CaptureError('revoked endpoints must cover actual initiating/accepting roles')
        if phase['still_connected']['exit'] or phase['still_connected']['stderr']:
            raise CaptureError('actual successful pre-release physical-link observation required')
        info(phase['still_connected']['stdout'], reference)
        owner_failure(phase['failed_owner'], caller, reference)
        cancellation(phase['cancel'], caller)
        if run['commands'][phase['disconnect_command']] != phase['cancel'] or phase.get('cancel_pending_before_release') is not True:
            raise CaptureError('original pending author and completed cleanup record required')
        management_observed(phase['revocation_polls'][-1], caller, 2)
        management_observed(phase['management_after'], caller, 1)
        marker = phase['hold']
        if len(marker['markers']) != 3 or len(marker['acks']) != 3 or len(marker['ack_receipts']) != 3:
            raise CaptureError('complete causal hold receipts required')
        states = [[True,False,0,0,0,0,False,0], [False,True,1,0,0,0,False,0], [False,False,1,1,0,0,False,0]]
        for j, (name, stage) in enumerate(zip(['arm_ready','wait_held','release_ready'], ['armed','held','released'])):
            request, ack, receipt = marker['markers'][j], marker['acks'][j], marker['ack_receipts'][j]
            state = dict(zip(PROPERTIES,states[j]))
            if (request.get('hold_phase') != name or ack.get('stage') != stage or ack.get('request') != request
                    or ack.get('state') != state or any(type(ack['state'][key]) is not type(value) for key,value in state.items())
                    or receipt.get('stage') != stage or not request['wall_ns'] <= receipt['wall_ns']):
                raise CaptureError('exact typed original hold/release receipts without expiry/drop required')
        created = run['commands'][phase['connect_command']]
        if not (phase['fds_before']['wall_ns'] <= marker['markers'][0]['wall_ns']
                <= marker['ack_receipts'][0]['wall_ns'] < created['start_wall_ns']
                <= created['end_wall_ns'] <= marker['ack_receipts'][1]['wall_ns']
                <= phase['fds_bound']['wall_ns']):
            raise CaptureError('original arm precedes Create; published/bound fd snapshot follows actual hold required')
        times = [marker['ack_receipts'][1]['wall_ns'], phase['cancel']['start_wall_ns'],
                 phase['revocation_polls'][-1]['end_wall_ns'], phase['still_connected']['end_wall_ns'],
                 phase['failed_owner']['end_wall_ns'], phase['fds_withdrawn']['wall_ns'],
                 marker['markers'][2]['wall_ns'], phase['cancel']['end_wall_ns'], phase['end_wall_ns']]
        if times != sorted(times):
            raise CaptureError('held < kernel revoke < old owner failure/fd drop < release < actual cleanup required')
        before, bound, withdrawn, after = map(inodes, [phase['fds_before'], phase['fds_bound'], phase['fds_withdrawn'], phase['fds_after_down']])
        if (not before <= withdrawn <= bound or len(bound-before) != 2 or not (bound-before)-withdrawn or after != before
                or phase['fds_after_down']['sockets'] != phase['fds_before']['sockets']):
            raise CaptureError('finite actual daemon socket convergence required')
        credentials = phase['cancel']['credentials']
        if (credentials['uids'] != [1000]*4 or set(credentials['capabilities']) != {'CapEff', 'CapPrm', 'CapAmb', 'CapInh'}
                or any(int(v, 16) for v in credentials['capabilities'].values())):
            raise CaptureError('ordinary cap-zero cancellation caller required')
        for number, stage in enumerate(['before', 'bound', 'withdrawn', 'after-down']):
            value = phase[['fds_before', 'fds_bound', 'fds_withdrawn', 'fds_after_down'][number]]
            if (value['supervisor_uid'] != 0 or value['daemon'] != phase['fds_before']['daemon']
                    or value['daemon'] != run['daemon_before']
                    or value['request']['sequence'] != n*4+number or value['request']['stage'] != stage
                    or value['request']['phase'] != n):
                raise CaptureError('fixed original VM-root observer and eight exact stages required')
    if used != {0, 1}:
        raise CaptureError('distinct revoked controllers in initiating/accepting roles required')


def verify_fd_supervisor(run, root):
    verify_guest(run)
    root = Path(root)
    if (root/'ssap-initialization-fds.log').read_text().splitlines() != ['WS73_SSAP_INIT_FDS_FINISHED']:
        raise CaptureError('completed read-only VM fd supervisor required')
    expected = [phase[key] for phase in run['ssap_initialization']['phases']
                for key in ['fds_before', 'fds_bound', 'fds_withdrawn', 'fds_after_down']]
    for n, value in enumerate(expected):
        if json.loads((root/'ssap-initialization-fds'/f'{n}.json').read_text()) != value:
            raise CaptureError('original root supervisor snapshot differs from caller evidence')


def corroborate_guest(run, capture):
    from ws73_connection_control import corroborate_wire_operation, result, link_reference
    verify_guest(run)
    proofs = []
    for phase in run['ssap_initialization']['phases']:
        handles = {}
        reference = phase['reference']
        connect = run['commands'][phase['connect_command']]
        if connect['exit'] or result(connect['stdout'], phase['caller'], 1) != phase['connect']:
            raise CaptureError('original actual Create author terminal required')
        links = run['commands'][phase['links_command']]
        if links['exit'] or link_reference(links['stdout'], phase['caller'], phase['peer'], phase['connect']['handle']) != reference:
            raise CaptureError('original canonical connection reference required')
        create = corroborate_wire_operation(run, phase, capture, 1, connect, reference['handle'], handles, reference)
        target_reference = next(v['object'] for v in phase['typed_objects'] if v['owner'] == phase['target'])
        target_up = next(v for v in create['outcomes'] if (v['bus'],v['device']) == (phase['target']['bus'],phase['target']['device']))
        if bytes.fromhex(target_up['params'])[3] != target_reference['role']:
            raise CaptureError('actual raw physical role must match withdrawn owner reference')
        directed = dict(phase, caller=phase['target'], peer=phase['other'])
        cleanup = corroborate_wire_operation(run, directed, capture, 2, phase['cancel'], target_reference['handle'], handles, target_reference, reason=0x10)
        caller = phase['target']
        same = lambda e: (e['bus'], e['device']) == (caller['bus'], caller['device'])
        withdrawal = phase['revocation_polls'][-1]['end_wall_ns']
        release = phase['hold']['markers'][2]['wall_ns']
        held = [e for e in capture['acb_packets'] if same(e) and e['direction'] == 'in' and e['data'] == RESPONSE
                and release <= e['wall_ns'] <= phase['end_wall_ns']]
        if len(held) != 1 or held[0]['handle'] != target_reference['handle'] or held[0]['boundary'] != 0:
            raise CaptureError('one original capability response after revoke/failure/release required')
        if any(same(e) and e['direction'] == 'out' and withdrawal <= e['wall_ns'] <= phase['end_wall_ns'] for e in capture['acb_packets']):
            raise CaptureError('revoked controller must not newly submit ACB after reported withdrawal')
        if cleanup['outcomes'][0]['wall_ns'] < held[0]['wall_ns']:
            raise CaptureError('target physical Down cannot precede its retained original RX transfer')
        peer_down = cleanup['outcomes'][1]
        if not phase['cancel']['start_wall_ns'] <= peer_down['wall_ns'] < release:
            raise CaptureError('unheld peer must process its real Down while target RX remains retained')
        proofs.append(dict(selection=phase['selection'], create=create, cleanup=cleanup, late_capability=held[0],
                           peer_rx_progress_during_hold=peer_down))
    return dict(status='REAL_CMTC_REVOKE_LATE_REPLY_DAEMON_FD_CONVERGENCE', proofs=proofs,
                kernel_reference_or_uaf_proof=False, native_bind_inflight_proof=False,
                initializer_task_join_proof=False, connection_object_removal_proof=False,
                natural_recovery_acceptance=False)


def corroborate(run, capture, record, stderr):
    proof = corroborate_guest(run, capture)
    if (record.get('method') != METHOD or record.get('qemu_sha256') != QEMU_SHA256
            or record.get('complete') is not True or len(record.get('phases', [])) != 2
            or record.get('hold_budget_ms') != 2000):
        raise CaptureError('exact two-phase pinned bounded2s host fixture required')
    holds = re.findall(r'WS73_TEST_RUNTIME_HOLD:.*', stderr)
    releases = re.findall(r'WS73_TEST_RUNTIME_HOLD_RELEASE:.*', stderr)
    if len(holds) != 2 or len(releases) != 2 or 'WS73_TEST_RUNTIME_HOLD_DROP:' in stderr or 'WS73_TEST_RUNTIME_IN_ERROR:' in stderr:
        raise CaptureError('two original explicit releases with no error/drop required')
    for host, guest, wire, held, released in zip(record['phases'], run['ssap_initialization']['phases'], proof['proofs'], holds, releases, strict=True):
        if host['selection'] != guest['selection']:
            raise CaptureError('host/guest original selection mismatch')
        wire['host_hold'] = corroborate_host_hold(host, dict(records=guest['hold']['markers'], host_hold_acknowledgements=guest['hold']['acks']),
            [], held+'\n'+released+'\n', host['host_identity_at_arm'], held_reply=wire['late_capability'])
    return proof


def valid_summary(value):
    return (value.get('status') == 'REAL_CMTC_REVOKE_LATE_REPLY_DAEMON_FD_CONVERGENCE'
            and len(value.get('proofs', [])) == 2
            and {v.get('selection', {}).get('slot') for v in value['proofs']} == {0, 1}
            and {v.get('selection', {}).get('role') for v in value['proofs']} == {0, 1}
            and all(v.get('host_hold', {}).get('status') == 'ACTUAL_HOST_HOLD_CORROBORATED' for v in value['proofs'])
            and all(v.get('late_capability', {}).get('data') == RESPONSE
                    and v.get('peer_rx_progress_during_hold') in v.get('cleanup', {}).get('outcomes', []) for v in value['proofs'])
            and value.get('kernel_reference_or_uaf_proof') is False
            and value.get('native_bind_inflight_proof') is False
            and value.get('initializer_task_join_proof') is False
            and value.get('connection_object_removal_proof') is False
            and value.get('natural_recovery_acceptance') is False)
