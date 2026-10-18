# SPDX-License-Identifier: GPL-2.0-only
"""Actual Native return across the existing single-leaf QMP removal gate.

No extra detach/recovery framework: the original Run.confirm/host coordinator
does its one removal/re-add. The real bind result is retained by the existing
bounded library. OS fd convergence is not kernel reference/callback/UAF proof.
"""
import copy
import json
from pathlib import Path
import re
import time

from ws73_capture import CaptureError
from ws73_native_return import Client, STAGES, inodes, returned_pair, verify_root_phase

STATUS = 'ACTUAL_USER_NATIVE_RETURN_CONTROLLER_REMOVAL_CORROBORATED'
ROLES = ('initiator', 'acceptor')


def requested(args, *, passthrough=None):
    role = getattr(args, 'native_controller_return', None)
    if role is None:
        return None
    if role not in ROLES or getattr(args, 'native_return_verify', False):
        raise ValueError('separate explicit controller-return role required')
    # Same dedicated ordinary-socket exclusions, not a second acceptance policy.
    from ws73_native_return import requested as original
    proposed = copy.copy(args)
    proposed.native_return_verify = True
    proposed.native_controller_return = None
    original(proposed, passthrough=passthrough)
    return role


class Session:
    def __init__(self, run):
        self.run = run
        self.role = ROLES.index(requested(run.args))
        self.pending = None

    def before_remove(self):
        from ws73_connection_control import connect_phase
        from ws73_connection_objects import info
        from ws73_channel_socket import test_program, check_arguments
        from ws73_daemon_hold import Invocation
        run = self.run
        a, b = run.data['initial']
        caller, peer = (a, b) if not self.role else (b, a)
        selection = dict(phase=2+self.role, controller=a['index'], generation=a['generation'], kind=1)
        phase = dict(caller=caller, peer=peer, target=a, other=b, selection=selection,
                     start_wall_ns=time.time_ns())
        self.record = dict(status='RUNNING', role=ROLES[self.role], phase=phase,
                           physical_acceptance=False, automatic_recovery=False)
        run.data['native_controller_return'] = self.record
        self.client = Client(run, 2+self.role)
        phase['before'] = self.client.request(selection, 'arm')
        connect_phase(run, phase, run.args.connection_advertising)
        selected = next(v for v in phase['typed_objects'] if v['owner'] == a)
        self.remote = next(v for v in phase['typed_objects'] if v['owner'] == b)
        phase['service_ready'] = [run.ctl(v['owner'], 'ssap-info', v['object']['path'])
                                  for v in phase['typed_objects']]
        self.pending = Invocation(check_arguments(test_program(run)['path'], selected, False, 1, 61),
                                  'native-controller-return-user')
        phase['pending_user'] = self.pending.row
        run.data['commands'].append(self.pending.row); run.save()
        phase['bound'] = self.client.request(selection, 'bound')
        held = phase['bound']['held']
        if any(held[k] != selected['object'][k] for k in ('generation', 'lifetime', 'handle')):
            raise CaptureError('actual user bind must belong to the selected physical lifetime')
        phase['physical_while_held'] = run.ctl(a, 'connection-info', selected['object']['path'])
        info(phase['physical_while_held']['stdout'], selected['object'])
        phase['remove_ready_wall_ns'] = time.time_ns(); run.save()

    def removed(self):
        run = self.run; phase = self.record['phase']; target, other = phase['target'], phase['other']
        from ws73_north_star import USB_ROOT
        phase['remove_ack_wall_ns'] = time.time_ns()
        if (USB_ROOT/target['port']).exists():
            raise CaptureError('actual selected guest leaf must be absent after QMP confirmation')
        phase['guest_port_absent'] = dict(port=target['port'], wall_ns=time.time_ns(), absent=True)
        phase['retirement_polls'] = []
        limit = time.monotonic()+.8
        while True:
            row = run.command([str(run.args.slctl), '--adapter', target['path'], 'show'],
                              .5, collection='commands')
            phase['retirement_polls'].append(row); run.save()
            if row['exit'] and 'not a live registration' in row['stderr']:
                phase['old_selection_refused'] = row
                break
            if row['exit'] or time.monotonic() >= limit:
                raise CaptureError('original controller must retire before actual Native return')
            time.sleep(.005)
        phase['other_during_hold'] = run.ctl(other, 'show')
        phase['release'] = self.client.request(phase['selection'], 'release')
        self.pending.finish()
        if not self.pending.row['exit'] or 'retired during native bind' not in self.pending.row['stderr']:
            raise CaptureError('actual user fd cannot escape its retired controller owner')
        run.save()

    def before_readd(self):
        from ws73_connection_control import canonical_link_state, result
        run = self.run; phase = self.record['phase']; other = phase['other']; target = phase['target']
        # Guest USB detach does not cut radio power. Settle the surviving
        # physical peer using its own current connection, never fake two Down
        # events or treat an unknown snapshot as a cleared radio.
        before = run.ctl(other, 'connections'); phase['peer_before_cleanup'] = before
        state = canonical_link_state(before['stdout'], other, target['address'])
        if state is None:
            raise CaptureError('known peer connection state required after guest-only removal')
        if state:
            row = run.command([str(run.args.slctl), '--adapter', other['path'],
                               'disconnect-object', self.remote['object']['path']], 18, collection='commands')
            phase['peer_disconnect'] = row
            parsed = result(row['stdout'], other, 2)
            if row['exit'] or parsed['handle'] != self.remote['object']['handle']:
                raise CaptureError('actual surviving peer cleanup must target the original handle')
        phase['peer_down_polls'] = []
        limit = time.monotonic()+5
        while True:
            row = run.ctl(other, 'connections'); phase['peer_down_polls'].append(row); run.save()
            if canonical_link_state(row['stdout'], other, target['address']) is False:
                phase['peer_down'] = row
                break
            if time.monotonic() >= limit:
                raise CaptureError('original peer Down observation deadline')
            time.sleep(.01)
        run.stop(other, 'advertise')
        phase['drained'] = self.client.request(phase['selection'], 'drained')
        if inodes(phase['drained']) != inodes(phase['before']):
            raise CaptureError('all original Native socket inodes must converge before re-add')
        phase['end_wall_ns'] = time.time_ns(); run.save()

    def replug(self, replacement, other):
        from ws73_north_star import stable, USB_ROOT
        from ws73_ssap_initialization import restore_beacons
        from ws73_lab_resources import check_hcc
        run = self.run; phase = self.record['phase']; old = phase['target']
        if (replacement['generation'] == old['generation'] or replacement['path'] == old['path']
                or not stable(other, phase['other']) or replacement['address'] != old['address']):
            raise CaptureError('new registration and unchanged peer identity required')
        models = [t.split('=', 1)[1] for t in Path('/proc/cmdline').read_text().split()
                  if t.startswith('ws73.expected_models=')]
        if len(models) != 1 or len(models[0].split(',')) != 2:
            raise CaptureError('explicit per-slot model provenance required')
        root = USB_ROOT/replacement['port']
        chip = list(root.glob(replacement['port']+':*/chip_information'))
        if len(chip) != 1:
            raise CaptureError('one actual replacement HCC query attribute required')
        self.record.update(replacement=replacement, hcc=check_hcc(chip[0].read_text().strip(), models[0].split(',')[0]),
                           replacement_observed_wall_ns=time.time_ns())
        restore_beacons(run, dict(caller=replacement, peer=other))
        self.record['status'] = 'NATIVE_CONTROLLER_RETURN_EVIDENCE_PENDING'; run.save()

    def close(self):
        if self.pending and self.pending.process.poll() is None:
            self.pending.finish(kill=True)


def verify_guest(run):
    from ws73_connection_objects import info
    from ws73_north_star import stable
    value = run['native_controller_return']; p = value['phase']; role = ROLES.index(value['role'])
    if (value['status'] != 'NATIVE_CONTROLLER_RETURN_EVIDENCE_PENDING'
            or value['physical_acceptance'] is not False or value['automatic_recovery'] is not False
            or p['target'] != run['initial'][0] or p['other'] != run['initial'][1]
            or p['selection'] != dict(phase=2+role, controller=p['target']['index'], generation=p['target']['generation'], kind=1)):
        raise CaptureError('one explicit original-controller/user-return slice required')
    target, other = p['target'], p['other']; selected = next(v for v in p['typed_objects'] if v['owner'] == target)
    if selected['object']['role'] != role:
        raise CaptureError('requested actual connection role required')
    info(p['physical_while_held']['stdout'], selected['object'])
    held, returned = p['bound']['held'], p['release']['returned']; returned_pair(held, returned)
    if (any(held[k] != selected['object'][k] for k in ('generation', 'lifetime', 'handle'))
            or any(held[k] != p['selection'][k] for k in ('phase','kind','controller','generation'))):
        raise CaptureError('same actual Native bound lifetime required')
    baseline = None
    for i, stage in enumerate(STAGES):
        row = p[{'arm':'before','bound':'bound','release':'release','drained':'drained'}[stage]]
        request = row['request']
        if (request['sequence'] != (2+role)*4+i or request['phase'] != 2+role
                or request['stage'] != stage or request['selection'] != p['selection']
                or row['supervisor_uid'] != 0 or row['daemon']['pid'] != held['pid']
                or not request['wall_ns'] <= row['start_wall_ns'] <= row['end_wall_ns']):
            raise CaptureError('ordered original VM-root return receipts required')
        if baseline is None: baseline = row
        if row['daemon'] != baseline['daemon'] or row['fixture'] != baseline['fixture']:
            raise CaptureError('same original daemon/library required')
    before, bound, drained = map(inodes, (p['before'], p['bound'], p['drained']))
    if (not before <= bound or len(bound-before) != 3 or p['bound']['held_inode'] not in bound-before
            or drained != before):
        raise CaptureError('actual user/service fd ownership and convergence required')
    old = p['old_selection_refused']; ready = p['other_during_hold']; pending = p['pending_user']
    if (not held['start_wall_ns'] <= p['physical_while_held']['start_wall_ns']
            <= p['physical_while_held']['end_wall_ns'] <= p['remove_ready_wall_ns']
            <= p['remove_ack_wall_ns'] <= p['guest_port_absent']['wall_ns']
            <= old['start_wall_ns'] <= old['end_wall_ns'] <= ready['start_wall_ns']
            <= ready['end_wall_ns'] <= p['release']['release_wall_ns'] <= returned['end_wall_ns']
            <= pending['end_wall_ns'] <= p['drained']['end_wall_ns'] <= p['end_wall_ns']
            <= value['replacement_observed_wall_ns']):
        raise CaptureError('controller retirement must precede original Native return and re-add')
    if (p['guest_port_absent'] != dict(port=target['port'], wall_ns=p['guest_port_absent']['wall_ns'], absent=True)
            or type(old['exit']) is not int or old['exit'] <= 0 or 'not a live registration' not in old['stderr']
            or ready['exit'] or '  State:       Ready\n' not in ready['stdout']
            or f"  Generation:  {other['generation']}\n" not in ready['stdout']
            or type(pending['exit']) is not int or pending['exit'] <= 0
            or 'retired during native bind' not in pending['stderr']
            or pending['start_wall_ns'] > held['start_wall_ns']):
        raise CaptureError('old selection/user return refusal and independent Ready required')
    replacement = value['replacement']
    if (not stable(replacement, run['replacement']) or replacement['generation'] == target['generation']
            or replacement['path'] == target['path'] or run['daemon_before'] != run['daemon_after']
            or run['bus_before'] != run['bus_after']
            or run['connection_control']['owners'] != [replacement, other]
            or min(v['start_wall_ns'] for v in run['channel_socket']) < value['replacement_observed_wall_ns']):
        raise CaptureError('same daemon and new-registration ordinary socket preservation required')
    return p


def corroborate(run, capture, root, expected=None):
    from ws73_connection_control import corroborate_wire_operation, corroborate_wire_status, canonical_link_state
    p = verify_guest(run); verify_root_phase(p, root, expected)
    handles = {(v['owner']['bus'],v['owner']['device']):v['object']['handle'] for v in p['typed_objects']}
    create = corroborate_wire_operation(run, p, capture, 1, run['commands'][p['connect_command']],
                                       p['connect']['handle'], handles)
    other = p['other']; body_handle = handles[(other['bus'],other['device'])]
    downs = [v for v in capture['native_events'] if v['event'] in (5, 0x1405)
             and (v['bus'],v['device']) == (other['bus'],other['device'])
             and p['bound']['held']['start_wall_ns'] <= v['wall_ns'] <= p['peer_down']['end_wall_ns']]
    if (len(downs) != 1 or len(bytes.fromhex(downs[0]['params'])) < 4
            or bytes.fromhex(downs[0]['params'])[0]
            or int.from_bytes(bytes.fromhex(downs[0]['params'])[1:3], 'little') != body_handle
            or canonical_link_state(p['peer_down']['stdout'], other, p['target']['address']) is not False):
        raise CaptureError('actual surviving peer Down must settle its original handle')
    cleanup = None
    if 'peer_disconnect' in p:
        command, status = corroborate_wire_status(capture, other, 0x1403, p['peer_disconnect'])
        if command['params'] != (body_handle.to_bytes(2,'little')+b'\x10').hex():
            raise CaptureError('surviving peer cleanup requires the exact current handle/reason')
        cleanup = dict(command=command, status=status)
    return dict(status=STATUS, role=run['native_controller_return']['role'], slices=1,
                held=p['bound']['held'], returned=p['release']['returned'], create=create, peer_down=downs[0], peer_cleanup=cleanup,
                fixture_sha256=p['before']['fixture']['sha256'], actual_guest_controller_removal=True,
                replacement_generation=run['replacement']['generation'], hcc=run['native_controller_return']['hcc'],
                same_daemon=True, socket_inode_convergence=True, kernel_reference_or_uaf_proof=False,
                physical_acceptance=False, automatic_recovery=False)


def valid_summary(v):
    try:
        if (not isinstance(v, dict) or v.get('status') != STATUS or v.get('role') not in ROLES
                or type(v.get('slices')) is not int or v['slices'] != 1
                or any(v.get(k) is not True for k in ('actual_guest_controller_removal','same_daemon','socket_inode_convergence'))
                or any(v.get(k) is not False for k in ('kernel_reference_or_uaf_proof','physical_acceptance','automatic_recovery'))
                or not isinstance(v.get('fixture_sha256'), str) or not re.fullmatch('[0-9a-f]{64}',v['fixture_sha256'])
                or type(v.get('replacement_generation')) is not int or v['replacement_generation'] <= v['held']['generation']
                or v['held']['phase'] != 2+ROLES.index(v['role']) or v['held']['kind'] != 1
                or not all(v.get('create',{}).get(k) for k in ('command','status','outcomes'))
                or len(v['create']['outcomes']) != 2 or not v.get('peer_down')
                or v.get('hcc',{}).get('source') != 'HCC_GET_CHIP_TYPE' or v['hcc'].get('bus') != 'USB'):
            return False
        returned_pair(v['held'],v['returned'])
        return True
    except (ValueError, CaptureError, KeyError, TypeError):
        return False
