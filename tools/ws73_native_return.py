# SPDX-License-Identifier: GPL-2.0-only
"""Controlled real Native bind-return/Connection retirement, VM only.

The test library calls SYS_bind first; it never supplies an fd or wire result.
Reuse the original connection, socket, capture and daemon identity facilities.
Socket-inode convergence is not a kernel-reference/callback/UAF proof.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import time

from ws73_capture import CaptureError
from ws73_diagnostic_hold import write_marker
from ws73_ssap_initialization import sockets, inodes

CONTROL = Path('/run/ws73-native-return')
SELECTION = struct.Struct('<8sIIQII')
OBSERVATION = struct.Struct('<8sIIIiIIQQQQQQII')
OBSERVATION_KEYS = ['phase', 'pid', 'tid', 'fd', 'controller', 'handle', 'generation', 'lifetime',
                    'start_mono_ns', 'start_wall_ns', 'end_mono_ns', 'end_wall_ns', 'outcome', 'kind']
STAGES = ('arm', 'bound', 'release', 'drained')
STATUS = 'ACTUAL_NATIVE_RETURN_CONNECTION_RETIREMENT_CORROBORATED'


def requested(args, *, passthrough=None):
    enabled = getattr(args, 'native_return_verify', False)
    if type(enabled) is not bool:
        raise ValueError('boolean Native-return request required')
    real = getattr(args, 'passthrough', False) if passthrough is None else passthrough
    if enabled and (getattr(args, 'native_controller_return', None) is not None
            or real is not True or not getattr(args, 'connection_verify', False)
            or not getattr(args, 'channel_socket_verify', False)
            or getattr(args, 'channel_socket_bytes', 61) != 61
            or getattr(args, 'channel_socket_rounds', 4) != 4
            or any(getattr(args, k, False) for k in [
                'ssap_initialization_verify', 'ssap_owner_lifecycle_verify',
                'ssap_requester_lifecycle_verify', 'ssap_owned_verify', 'security_agent',
                'channel_socket_burst', 'channel_socket_close_prefix', 'channel_socket_boundaries',
                'dynamic_channel_verify', 'channel_fairness_verify', 'application_client_verify',
                'channel_benchmark', 'daemon_link_resync'])):
        raise ValueError('Native return requires dedicated real ordinary basic socket preservation')
    return enabled


def fixture_phases(tokens=None):
    """One explicit VM scope; historical four-Connection evidence stays distinct."""
    tokens = Path('/proc/cmdline').read_text().split() if tokens is None else tokens
    native = tokens.count('ws73.native_return=1')
    controller = [v.split('=', 1)[1] for v in tokens if v.startswith('ws73.native_controller_return=')]
    if native == 1 and not controller:
        return tuple(range(4))
    if not native and len(controller) == 1 and controller[0] in ('initiator', 'acceptor'):
        return (2 + ('initiator', 'acceptor').index(controller[0]),)
    raise ValueError('one explicit Native return VM scope required')


def decode(raw):
    if len(raw) != OBSERVATION.size:
        raise ValueError('complete fixed Native observation required')
    magic, *values = OBSERVATION.unpack(raw)
    row = dict(zip(OBSERVATION_KEYS, values, strict=True))
    if (magic != b'SLKRET1\0' or row['phase'] not in range(4)
            or row['kind'] != row['phase']//2 or row['controller'] not in range(16)
            or row['handle'] not in range(65536) or row['pid'] <= 0 or row['tid'] <= 0
            or row['fd'] < 0 or not row['generation'] or not row['lifetime']
            or not row['start_mono_ns'] or not row['start_wall_ns']
            or row['outcome'] not in (0, 1, 2)):
        raise ValueError('invalid Native observation identity')
    if row['outcome'] == 0:
        if row['end_mono_ns'] or row['end_wall_ns']:
            raise ValueError('held observation cannot contain a return')
    elif not (row['start_mono_ns'] < row['end_mono_ns']
              and row['start_wall_ns'] <= row['end_wall_ns']):
        raise ValueError('ordered actual return timestamps required')
    return row


def returned_pair(held, returned):
    for row in (held, returned):
        if (not isinstance(row, dict) or set(row) != set(OBSERVATION_KEYS)
                or any(type(v) is not int for v in row.values())):
            raise CaptureError('typed complete original Native observations required')
        decode(OBSERVATION.pack(b'SLKRET1\0', *(row[k] for k in OBSERVATION_KEYS)))
    if (held['outcome'] != 0 or returned['outcome'] != 1
            or not 0 < returned['end_mono_ns']-held['start_mono_ns'] < 2_000_000_000
            or any(returned[k] != held[k] for k in held if k not in ('outcome', 'end_mono_ns', 'end_wall_ns'))):
        raise CaptureError('original successful bind must return by explicit release within the finite hold')


def wait_record(path, alive, deadline):
    while True:
        alive()
        if path.exists():
            raw = path.read_bytes()
            if len(raw) == OBSERVATION.size:
                return decode(raw)
            if len(raw) > OBSERVATION.size:
                raise ValueError('oversized Native record')
        if time.monotonic() >= deadline:
            raise TimeoutError('bounded real Native fixture observation')
        time.sleep(.001)


def setup():
    import platform
    if os.geteuid() or '-opensparklink-native-lab+' not in platform.release():
        raise ValueError('explicit native test VM root required')
    fixture_phases()
    CONTROL.mkdir(mode=0o700, exist_ok=False)


def supervise(root, pid):
    from ws73_north_star import daemon_identity
    if os.geteuid() != 0 or stat.S_IMODE(CONTROL.stat().st_mode) != 0o700:
        raise ValueError('fixed VM-root control directory required')
    original = daemon_identity(pid)
    root = Path(root)
    output = root/'native-return-root'
    output.mkdir(mode=0o755, exist_ok=False)
    library = Path('/usr/lib/sparklink/native-return-fixture.so')
    fixture = dict(path=str(library), sha256=hashlib.sha256(library.read_bytes()).hexdigest())
    if str(library) not in (Path('/proc')/str(pid)/'maps').read_text():
        raise ValueError('actual original daemon must load the pinned test-only library')
    source = root/'application/passthrough-control/native-return-requests'
    deadline = time.monotonic()+180
    def alive():
        if time.monotonic() >= deadline or daemon_identity(pid) != original:
            raise ValueError('original daemon/finite Native supervisor required')
    phases = fixture_phases()
    for phase in phases:
        held = None
        for stage in STAGES:
            number = phase*4+STAGES.index(stage)
            path = source/f'{number}.json'
            while not path.exists():
                alive()
                # Keep actual C bytes even if the foreground caller fails
                # before requesting the next receipt. /run is volatile.
                for suffix in ('held', 'returned'):
                    native = CONTROL/f'{phase}-{suffix}'
                    if native.exists():
                        raw = native.read_bytes()
                        if len(raw) == OBSERVATION.size:
                            decode(raw)
                            preserved = output/f'{phase}-{suffix}.bin'
                            if preserved.exists() and preserved.read_bytes() != raw:
                                raise ValueError('original C observation changed')
                            if not preserved.exists():
                                preserved.write_bytes(raw)
                time.sleep(.002)
            descriptor = os.open(path, os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as stream:
                attributes = os.fstat(stream.fileno())
                if not stat.S_ISREG(attributes.st_mode) or attributes.st_uid != 1000 or attributes.st_size > 4096:
                    raise ValueError('bounded ordinary-user regular request required')
                request = json.loads(stream.read(4097))
            if (set(request) != {'sequence', 'phase', 'stage', 'selection', 'wall_ns'}
                    or type(request['sequence']) is not int or request['sequence'] != number
                    or type(request['phase']) is not int or request['phase'] != phase
                    or request['stage'] != stage or type(request['wall_ns']) is not int):
                raise ValueError('fixed original Native request sequence required')
            selection = request['selection']
            if (set(selection) != {'controller', 'generation', 'phase', 'kind'}
                    or any(type(x) is not int for x in selection.values())
                    or selection['phase'] != phase or selection['kind'] != phase//2
                    or selection['controller'] not in range(16) or selection['generation'] < 1):
                raise ValueError('original selected controller/generation/kind required')
            alive()
            row = dict(request=request, daemon=original, fixture=fixture, supervisor_uid=os.geteuid(),
                       start_wall_ns=time.time_ns())
            if stage == 'arm':
                raw = SELECTION.pack(b'SLKSEL1\0', phase, selection['controller'], selection['generation'], phase//2, 0)
                fd = os.open(CONTROL/'selection', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                (output/f'{phase}-selection.bin').write_bytes(raw)
            elif stage == 'bound':
                held = wait_record(CONTROL/f'{phase}-held', alive, time.monotonic()+2)
                if (held['pid'] != pid or any(held[k] != selection[k] for k in selection)
                        or held['outcome'] != 0 or (CONTROL/f'{phase}-returned').exists()):
                    raise ValueError('actual successful selected bind must still be held')
                row['held'] = held
                (output/f'{phase}-held.bin').write_bytes((CONTROL/f'{phase}-held').read_bytes())
                row['held_inode'] = os.readlink(Path('/proc')/str(pid)/'fd'/str(held['fd']))
            elif stage == 'release':
                if held is None or (CONTROL/f'{phase}-returned').exists():
                    raise ValueError('release must precede finite fixture expiry')
                row['release_wall_ns'] = time.time_ns()
                fd = os.open(CONTROL/f'{phase}-release', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
                os.close(fd)
                returned = wait_record(CONTROL/f'{phase}-returned', alive, time.monotonic()+1)
                if (returned['outcome'] != 1 or any(returned[k] != held[k] for k in held if k not in
                        ('outcome', 'end_mono_ns', 'end_wall_ns'))):
                    raise ValueError('real return must follow explicit release, never expiry')
                row['returned'] = returned
                (output/f'{phase}-returned.bin').write_bytes((CONTROL/f'{phase}-returned').read_bytes())
            else:
                (CONTROL/'selection').unlink()
                if len(phases) == 1:
                    # After real device removal, the peer's actual Down and
                    # controller retirement may still be draining. Observe,
                    # never close a daemon fd or invent a successful drain.
                    row['drain_observations'] = []
                    limit = time.monotonic()+2
                    while True:
                        observation = sockets(pid)
                        row['drain_observations'].append(observation)
                        if inodes(observation) == inodes(baseline):
                            break
                        alive()
                        if time.monotonic() >= limit:
                            raise TimeoutError('controller Native socket convergence')
                        time.sleep(.01)
            row.update(sockets(pid), end_wall_ns=time.time_ns())
            if stage == 'arm':
                baseline = row
            inodes(row)
            write_marker(output/f'{number}.json', row)
    print('WS73_NATIVE_RETURN_SUPERVISOR_FINISHED', flush=True)


class Client:
    def __init__(self, run, start_phase=0):
        if type(start_phase) is not int or start_phase not in range(4):
            raise ValueError('fixed Native selection phase required')
        self.run, self.sequence = run, start_phase*4
        self.folder = run.output/'native-return-requests'
        self.folder.mkdir(exist_ok=False)

    def request(self, selection, stage):
        request = dict(sequence=self.sequence, phase=selection['phase'], stage=stage,
                       selection=selection, wall_ns=time.time_ns())
        write_marker(self.folder/f'{self.sequence}.json', request)
        output = Path('/evidence/native-return-root')/f'{self.sequence}.json'
        limit = time.monotonic()+3
        while not output.exists():
            self.run.alive()
            if time.monotonic() >= limit:
                raise TimeoutError('bounded Native-return root receipt')
            time.sleep(.002)
        value = json.loads(output.read_text())
        if value.get('request') != request or value.get('supervisor_uid') != 0:
            raise CaptureError('original VM-root Native receipt required')
        inodes(value); self.sequence += 1
        return value


def execute(run, a, b):
    from ws73_connection_control import connect_phase, result, await_down_properties, observe_phase_down
    from ws73_connection_objects import info
    from ws73_channel_socket import test_program, check_arguments
    from ws73_daemon_hold import Invocation
    from ws73_ssap_initialization import restore_beacons
    client = Client(run)
    record = dict(status='RUNNING', phases=[], new_engine=False, physical_acceptance=False,
                  automatic_recovery_acceptance=False)
    run.data['native_return'] = record
    previous = []
    for n in range(4):
        target, other = (a, b) if n % 2 == 0 else (b, a)
        selection = dict(phase=n, controller=target['index'], generation=target['generation'], kind=n//2)
        phase = dict(caller=a, peer=b, target=target, other=other, selection=selection,
                     start_wall_ns=time.time_ns())
        record['phases'].append(phase); run.save()
        phase['before'] = client.request(selection, 'arm')
        connect_phase(run, phase, run.args.connection_advertising, previous, n)
        selected = next(v for v in phase['typed_objects'] if v['owner'] == target)
        remote = next(v for v in phase['typed_objects'] if v['owner'] == other)
        pending = None
        try:
            if n >= 2:
                phase['service_ready'] = [run.ctl(v['owner'], 'ssap-info', v['object']['path'])
                                          for v in phase['typed_objects']]
                argv = check_arguments(test_program(run)['path'], selected, False, 1, 61)
                pending = Invocation(argv, 'native-return-user')
                phase['pending_user'] = pending.row
                run.data['commands'].append(pending.row); run.save()
            phase['bound'] = client.request(selection, 'bound')
            held = phase['bound']['held']
            if any(held[k] != selected['object'][k] for k in ('generation', 'lifetime', 'handle')):
                raise CaptureError('real bind must belong to the original physical object')
            phase['physical_while_held'] = run.ctl(target, 'connection-info', selected['object']['path'])
            info(phase['physical_while_held']['stdout'], selected['object'])
            phase['disconnect_command'] = len(run.data['commands'])
            row = run.command([str(run.args.slctl), '--adapter', other['path'],
                               'disconnect-object', remote['object']['path']], 18, collection='commands')
            phase['disconnect'] = result(row['stdout'], other, 2)
            if row['exit'] or phase['disconnect']['handle'] != remote['object']['handle']:
                raise CaptureError('actual unheld peer must disconnect the exact physical lifetime')
            await_down_properties(run, phase, a, b)
            phase['down_while_held'] = copy.deepcopy(phase['down_property_observation'])
            phase['physical_down_held'] = run.ctl(target, 'connection-info', selected['object']['path'])
            value = selected['object']
            expected = (f"NativeConnectionInfo: generation={value['generation']} lifetime={value['lifetime']} "
                        f"handle={value['handle']} role={value['role']} type={value['address_type']} "
                        f"address={value['address']} known=true connected=false path={value['path']}\n")
            if phase['physical_down_held']['stdout'] != f"Selected {target['path']}\n"+expected:
                raise CaptureError('retiring physical view must remain observable until actual Native return')
            argv = check_arguments(test_program(run)['path'], selected, False, 1, 61)
            denied = run.command(argv, 3, collection='commands')
            phase['retired_admission'] = denied
            if not denied['exit'] or 'immutable identity unavailable or changed: connection unknown/down' not in denied['stderr']:
                raise CaptureError('public SDK must reject a known Down lifetime before requesting a new fd')
            phase['other_during_hold'] = run.ctl(other, 'show')
            phase['release'] = client.request(selection, 'release')
            if pending:
                pending.finish()
                if not pending.row['exit'] or 'retired during native bind' not in pending.row['stderr']:
                    raise CaptureError('held actual user fd must be rejected after physical retirement')
            observe_phase_down(run, phase)
            phase['drained'] = client.request(selection, 'drained')
            if phase['drained']['sockets'] != phase['before']['sockets']:
                raise CaptureError('all actual Native sockets must converge after return and parent cleanup')
            restore_beacons(run, phase)
            previous = phase['typed_objects']
            phase['end_wall_ns'] = time.time_ns(); run.save()
        finally:
            if pending and pending.process.poll() is None:
                pending.finish(kill=True)
            run.save()
    record['status'] = 'NATIVE_RETURN_EVIDENCE_PENDING'; run.save()


def verify_guest(run):
    from ws73_connection_objects import info
    record = run['native_return']
    phases = record['phases']
    if (record['status'] != 'NATIVE_RETURN_EVIDENCE_PENDING' or len(phases) != 4
            or any(record.get(k) is not False for k in
                   ('new_engine', 'physical_acceptance', 'automatic_recovery_acceptance'))):
        raise CaptureError('four finite actual Native-return slices required')
    original = None
    for n, phase in enumerate(phases):
        selection = phase['selection']
        if (selection != dict(phase=n, controller=phase['target']['index'],
                              generation=phase['target']['generation'], kind=n//2)
                or phase['target'] != run['initial'][n % 2]
                or phase['other'] != run['initial'][1-n % 2]):
            raise CaptureError('fixed role/kind and original controller selection required')
        entry = next(v for v in phase['typed_objects'] if v['owner'] == phase['target'])
        reference = entry['object']
        if reference['role'] != n % 2:
            raise CaptureError('actual initiating and accepting roles required')
        held = phase['bound']['held']
        returned = phase['release']['returned']
        returned_pair(held, returned)
        if (held['phase'] != n or held['kind'] != n//2 or held['outcome'] != 0
                or held['controller'] != selection['controller']
                or any(held[k] != reference[k] for k in ('generation', 'lifetime', 'handle'))
                or returned['outcome'] != 1 or not 0 < returned['end_mono_ns']-held['start_mono_ns'] < 2_000_000_000
                or any(returned[k] != held[k] for k in held if k not in ('outcome', 'end_mono_ns', 'end_wall_ns'))):
            raise CaptureError('same actual successful Native bind must return only on explicit release')
        for i, stage in enumerate(STAGES):
            row = phase[{'arm':'before', 'bound':'bound', 'release':'release', 'drained':'drained'}[stage]]
            request = row['request']
            if (request['sequence'] != n*4+i or request['phase'] != n or request['stage'] != stage
                    or request['selection'] != selection or row['supervisor_uid'] != 0
                    or not request['wall_ns'] <= row['start_wall_ns'] <= row['end_wall_ns']):
                raise CaptureError('ordered original VM-root receipts required')
            if original is None:
                original = row['daemon']
            if row['daemon'] != original:
                raise CaptureError('same actual daemon must survive every Native-return slice')
            if (row['fixture'] != phases[0]['before']['fixture']
                    or row['fixture']['path'] != '/usr/lib/sparklink/native-return-fixture.so'
                    or not re.fullmatch('[0-9a-f]{64}', row['fixture']['sha256'])):
                raise CaptureError('same pinned library must observe every real Native call')
        before, bound, drained = map(inodes, (phase['before'], phase['bound'], phase['drained']))
        if (not before <= bound or len(bound-before) != (2 if n < 2 else 3)
                or phase['bound']['held_inode'] not in bound-before or drained != before
                or phase['drained']['sockets'] != phase['before']['sockets']):
            raise CaptureError('actual original Native fd ownership and post-return convergence required')
        info(phase['physical_while_held']['stdout'], reference)
        down = phase['physical_down_held']
        if (down['exit'] or 'known=true connected=false' not in down['stdout']
                or not held['start_wall_ns'] <= phase['physical_while_held']['start_wall_ns']
                <= phase['physical_while_held']['end_wall_ns'] <= phase['down_while_held']['start_wall_ns']
                <= down['start_wall_ns'] <= down['end_wall_ns']
                <= phase['retired_admission']['start_wall_ns'] <= phase['retired_admission']['end_wall_ns']
                <= phase['release']['release_wall_ns'] <= returned['end_wall_ns']):
            raise CaptureError('physical publication and Down/refusal must precede actual return')
        denied = phase['retired_admission']
        from ws73_channel_socket import check_arguments
        if (denied['exit'] <= 0 or 'immutable identity unavailable or changed: connection unknown/down' not in denied['stderr']
                or denied['args'] != check_arguments(run['slktest']['path'], entry, False, 1, 61)):
            raise CaptureError('actual public SDK Down refusal required')
        ready = phase['other_during_hold']
        if (ready['exit'] or '  State:       Ready\n' not in ready['stdout']
                or f"  Generation:  {phase['other']['generation']}\n" not in ready['stdout']
                or ready['end_wall_ns'] > phase['release']['release_wall_ns']):
            raise CaptureError('independent other controller must retain original Ready while held')
        if n >= 2:
            pending = phase['pending_user']
            if (pending['exit'] <= 0 or 'retired during native bind' not in pending['stderr']
                    or pending['start_wall_ns'] > held['start_wall_ns']
                    or pending['end_wall_ns'] < returned['end_wall_ns']):
                raise CaptureError('actual pending user creation cannot receive a retired fd')
        elif 'pending_user' in phase:
            raise CaptureError('service slice cannot be relabelled as application creation')
    return phases


def verify_root(run, root, expected=None):
    phases = verify_guest(run)
    for phase in phases:
        verify_root_phase(phase, root, expected)


def verify_root_phase(phase, root, expected=None):
    root = Path(root)/'native-return-root'
    s = phase['selection']; n = s['phase']
    for i, stage in enumerate(STAGES):
        saved = json.loads((root/f'{n*4+i}.json').read_text())
        if saved != phase[{'arm':'before', 'bound':'bound', 'release':'release', 'drained':'drained'}[stage]]:
            raise CaptureError('root receipt changed/missing in original private artifact')
        if expected is not None and saved['fixture']['sha256'] != expected:
            raise CaptureError('actual loaded Native fixture differs from prepared artifact')
    if (decode((root/f'{n}-held.bin').read_bytes()) != phase['bound']['held']
            or decode((root/f'{n}-returned.bin').read_bytes()) != phase['release']['returned']):
        raise CaptureError('original C observation bytes must match decoded root receipts')
    selected = SELECTION.unpack((root/f'{n}-selection.bin').read_bytes())
    if selected != (b'SLKSEL1\0', n, s['controller'], s['generation'], n//2, 0):
        raise CaptureError('original fixed C selector bytes required')


def corroborate(run, capture):
    from ws73_connection_control import corroborate_wire_operation
    phases = verify_guest(run)
    proofs = []
    for phase in phases:
        handles = {(v['owner']['bus'], v['owner']['device']): v['object']['handle'] for v in phase['typed_objects']}
        create = corroborate_wire_operation(run, phase, capture, 1, run['commands'][phase['connect_command']],
                                           phase['connect']['handle'], handles)
        selected = next(v['object'] for v in phase['typed_objects'] if v['owner'] == phase['other'])
        swapped = dict(phase, caller=phase['other'], peer=phase['target'])
        disconnect = corroborate_wire_operation(run, swapped, capture, 2,
            run['commands'][phase['disconnect_command']], selected['handle'], handles, selected)
        # Check the earlier, still-held Down receipts against the same raw
        # physical outcomes, not only the post-return ordinary cleanup query.
        from ws73_connection_control import corroborate_down_property
        early = dict(phase, down_property_observation=phase['down_while_held'])
        for event in disconnect['outcomes']:
            owner = next(v for v in (phase['caller'], phase['peer'])
                         if (v['bus'], v['device']) == (event['bus'], event['device']))
            corroborate_down_property(run, early, owner, event)
        proofs.append(dict(phase=phase['selection']['phase'], kind=phase['selection']['kind'],
                           role=phase['selection']['phase'] % 2, create=create, disconnect=disconnect,
                           held=phase['bound']['held'], returned=phase['release']['returned']))
    return dict(status=STATUS, slices=4, service_slices=2, user_slices=2, proofs=proofs,
                fixture_sha256=phases[0]['before']['fixture']['sha256'],
                kernel_reference_or_uaf_proof=False, dynamic_creator=False,
                actual_controller_removal=False, broker_new_admission_probe=False,
                physical_acceptance=False, automatic_recovery=False)


def valid_summary(value):
    if not isinstance(value, dict):
        return False
    proofs = value.get('proofs')
    if not isinstance(proofs, list) or len(proofs) != 4 or any(not isinstance(p, dict) for p in proofs):
        return False
    valid = (value.get('status') == STATUS and type(value.get('slices')) is int and value['slices'] == 4
            and isinstance(value.get('fixture_sha256'), str) and re.fullmatch('[0-9a-f]{64}',value['fixture_sha256'])
            and all(type(value.get(k)) is int and value[k] == 2 for k in ('service_slices', 'user_slices'))
            and all(all(type(p.get(k)) is int for k in ('phase', 'kind', 'role'))
                    and p['phase'] == n and p['kind'] == n//2 and p['role'] == n%2
                    for n, p in enumerate(proofs))
            and all(value.get(k) is False for k in ('kernel_reference_or_uaf_proof', 'dynamic_creator',
                'actual_controller_removal', 'broker_new_admission_probe', 'physical_acceptance', 'automatic_recovery')))
    if not valid:
        return False
    try:
        for phase in value['proofs']:
            returned_pair(phase['held'], phase['returned'])
            for key in ('create', 'disconnect'):
                if (not phase[key]['command'] or not phase[key]['status']
                        or len(phase[key]['outcomes']) != 2):
                    return False
    except (ValueError, KeyError, TypeError, struct.error, CaptureError):
        return False
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('setup')
    observe = commands.add_parser('supervise')
    observe.add_argument('root', type=Path)
    observe.add_argument('pid', type=int)
    args = parser.parse_args()
    if args.command == 'setup':
        setup()
    else:
        supervise(args.root, args.pid)
