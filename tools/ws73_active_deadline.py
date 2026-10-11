#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VM-only real IN81 active-deadline/retirement gate, before daemon startup.

This is separate from the accepted explicit-release diagnostic gate. It never
injects a reply or requests a host reset, USB detach or physical replug.
"""
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
from sparklink.structs import SleControllerSnapshot, SleDiagnosticResult, SleDiagnosticSubmit
from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker


class ActiveDeadlineCoordinator(HoldCoordinator):
    """Arm once, observe the real transfer, then observe cancellation only."""
    def __init__(self, share, record):
        super().__init__(share, record)
        self.folder = Path(share) / 'active-deadline'
        self.record['method'] = 'QMP_HOLD_ACTUAL_IN81_UNTIL_NATIVE_RETIREMENT'
        self.abort_deadline = None

    def poll(self, monitor):
        if self.phase != 'abort_ready':
            super().poll(monitor)
            if self.phase == 'release_ready':
                self.phase = 'abort_ready'
            return
        marker = self.folder / 'hold-abort_ready.json'
        if not marker.exists():
            return
        request = json.loads(marker.read_text())
        if (set(request) != {'hold_phase', 'wall_ns'} or request['hold_phase'] != self.phase
                or type(request['wall_ns']) is not int or request['wall_ns'] <= 0):
            raise ValueError('exact active abort observation marker required')
        if self.abort_deadline is None:
            self.abort_deadline = time.monotonic() + 3
        held = dict(zip(PROPERTIES, [False, True, 1, 0, 0, 0, False, 0]))
        aborted = dict(zip(PROPERTIES, [False, False, 1, 0, 0, 1, False, 0]))
        state = self.snapshot(monitor)
        if state == held and time.monotonic() < self.abort_deadline:
            return
        if state != aborted or monitor.execute('qom-get', {'path': self.path, 'property': 'attached'}) is not True:
            raise ValueError('exact one held-transfer abort without release/reset/detach required')
        response = {'stage': 'aborted', 'host_wall_ns': time.time_ns(), 'request': request, 'state': state}
        self.record['observations'].append(response)
        write_marker(self.folder / 'hold-aborted-ack.json', response)
        self.phase = 'done'
        self.record['complete'] = True


def _decode(kind, raw):
    if not isinstance(raw, str) or len(raw) != ctypes.sizeof(kind) * 2 or not re.fullmatch('[0-9a-f]+', raw):
        raise ValueError('canonical complete ABI bytes required')
    return kind.from_buffer_copy(bytes.fromhex(raw))


def metadata_ready(share):
    """A redirected guest stdout cannot be used to attach the second device."""
    path = Path(share) / 'active-deadline/metadata-0.json'
    if not path.exists():
        return False
    value = json.loads(path.read_text())
    if set(value) != {'slot', 'initial_snapshot'} or type(value['slot']) is not int or value['slot'] != 0:
        raise ValueError('exact initial target metadata marker required')
    snapshot = _decode(SleControllerSnapshot, value['initial_snapshot'])
    if (snapshot.version != 1 or snapshot.dev_index != 0 or not snapshot.generation
            or snapshot.flags != 2 or snapshot.profile != 1 or snapshot.valid_fields != 1):
        raise ValueError('actual target Setup metadata required before peer attachment')
    return True


def verify_records(record):
    if (record.get('format_version') != 1 or type(record['format_version']) is not int
            or record.get('status') != 'ACTIVE_DEADLINE_PRE_DAEMON_PASS'
            or record.get('physical_acceptance') is not False
            or record.get('automatic_fault_recovery_acceptance') is not False
            or record.get('daemon_running_during_hold') is not False):
        raise ValueError('limited pre-daemon active retirement format required')
    if (record.get('initializer_method') != 'EXISTING_SLKD_MANAGED_STANDBY'
            or type(record.get('initializer_pid')) is not int or not 1 < record['initializer_pid'] < 1 << 32
            or type(record.get('initializer_exit')) is not int or record['initializer_exit'] != 0):
        raise ValueError('existing initializer daemon must exit before the held gate')
    target = _decode(SleControllerSnapshot, record['target_snapshot'])
    peers = [_decode(SleControllerSnapshot, v) for v in record['peer_snapshots']]
    if (target.version != 1 or target.flags != 1 or target.profile != 1 or target.valid_fields != 1 or target.dev_index != 0
            or not target.generation or len(peers) != 2 or bytes(peers[0]) != bytes(peers[1])
            or peers[0].dev_index != 1 or peers[0].flags != 1 or peers[0].profile != 1 or peers[0].valid_fields != 1
            or not peers[0].generation or target.generation == peers[0].generation):
        raise ValueError('independent initial target and unchanged peer metadata required')
    initializations = record['initializations']
    if len(initializations) != 2:
        raise ValueError('both real initialization stop barriers required')
    for initialization, snapshot in zip(initializations, [target, peers[0]]):
        initial = _decode(SleControllerSnapshot, initialization['initial_snapshot'])
        ready = _decode(SleControllerSnapshot, initialization['ready_snapshot'])
        if (initial.flags != 2 or initial.generation != snapshot.generation or initial.dev_index != snapshot.dev_index
                or bytes(ready) != bytes(snapshot) or type(initialization['start_wall_ns']) is not int
                or type(initialization['end_wall_ns']) is not int
                or not 0 < initialization['start_wall_ns'] < initialization['end_wall_ns'] < record['markers'][0]['wall_ns']):
            raise ValueError('real Setup to Ready initialization before arming required')
    command = _decode(SleDiagnosticSubmit, record['input'])
    expected = SleDiagnosticSubmit(version=1, generation=target.generation, request_id=1,
                                   timeout_ms=500, opcode=0x0406, action=1)
    if bytes(command) != bytes(expected):
        raise ValueError('exact original active MAC admission required')
    output = _decode(SleDiagnosticSubmit, record['output'])
    if not output.seq:
        raise ValueError('actual nonzero admission sequence required')
    expected.seq = output.seq
    if bytes(output) != bytes(expected):
        raise ValueError('admission changed request identity')
    pending = _decode(SleDiagnosticResult, record['initial_result'])
    expected_pending = SleDiagnosticResult(version=1, generation=target.generation,
                                          seq=output.seq, state=1, opcode=0x0406)
    if bytes(pending) != bytes(expected_pending):
        raise ValueError('actual exact Pending result before passive wait required')
    clocks = [record[k] for k in ['submit_before_monotonic_ns', 'submit_after_monotonic_ns',
                                  'quiet_before_monotonic_ns', 'quiet_after_monotonic_ns']]
    if any(type(v) is not int or v <= 0 for v in clocks) or clocks != sorted(clocks):
        raise ValueError('ordered actual monotonic clocks required')
    if clocks[2] - clocks[0] >= 400_000_000 or not 50_000_000 <= clocks[3] - clocks[2] < 2_000_000_000:
        raise ValueError('hold must precede original deadline and passive abort must precede guard')
    acknowledgments = record['host_hold_acknowledgements']
    markers = record['markers']
    receipts = record['guest_ack_receipts']
    if len(acknowledgments) != 3 or len(markers) != 3 or len(receipts) != 3 or [v.get('stage') for v in acknowledgments] != ['armed', 'held', 'aborted']:
        raise ValueError('one causal armed/held/aborted handshake required')
    previous_host = previous_guest = previous_monotonic = 0
    for i, (row, marker, receipt) in enumerate(zip(acknowledgments, markers, receipts)):
        values = [i == 0, i == 1, int(i > 0), 0, 0, int(i == 2), False, 0]
        if (row['request'] != marker or set(marker) != {'hold_phase', 'wall_ns'}
                or marker['hold_phase'] != ['arm_ready', 'wait_held', 'abort_ready'][i]
                or type(marker['wall_ns']) is not int or marker['wall_ns'] <= previous_guest
                or type(row['host_wall_ns']) is not int or row['host_wall_ns'] <= previous_host
                or set(receipt) != {'stage','wall_ns','monotonic_ns'} or receipt['stage'] != row['stage']
                or type(receipt['wall_ns']) is not int or receipt['wall_ns'] < marker['wall_ns']
                or type(receipt['monotonic_ns']) is not int or receipt['monotonic_ns'] <= previous_monotonic
                or row['state'] != dict(zip(PROPERTIES, values))
                or any(type(row['state'][key]) is not type(value) for key, value in zip(PROPERTIES, values))):
            raise ValueError('exact non-releasing QMP readbacks and causal markers required')
        previous_host = row['host_wall_ns']; previous_guest = receipt['wall_ns']; previous_monotonic = receipt['monotonic_ns']
    if len(markers) != 3 or record['retired_result_errno'] != errno.ENODEV or type(record['retired_result_errno']) is not int:
        raise ValueError('retired selected result must reject ENODEV')
    if record['retired_submit_errno'] != errno.ENODEV or type(record['retired_submit_errno']) is not int:
        raise ValueError('retired selected retry must reject ENODEV')
    if (type(record['submit_before_wall_ns']) is not int or type(record['submit_after_wall_ns']) is not int
            or not receipts[0]['wall_ns'] <= record['submit_before_wall_ns']
            <= record['submit_after_wall_ns'] <= markers[1]['wall_ns'] <= receipts[1]['wall_ns']
            or not receipts[0]['monotonic_ns'] <= clocks[0] <= clocks[1] <= receipts[1]['monotonic_ns']
            <= clocks[2] <= receipts[2]['monotonic_ns'] <= clocks[3]):
        raise ValueError('held successful host transfer must follow admission')
    queries = record['peer_queries']
    if len(queries) != 2:
        raise ValueError('peer queries before and after target retirement required')
    for i, query in enumerate(queries):
        result = _decode(SleDiagnosticResult, query['result'])
        request = _decode(SleDiagnosticSubmit, query['output'])
        canonical = SleDiagnosticSubmit(version=1, generation=peers[0].generation, request_id=i+1,
                                        timeout_ms=5000, opcode=0x0406, seq=request.seq, action=1)
        complete = SleDiagnosticResult(version=1, generation=peers[0].generation, seq=request.seq,
                                       state=2, opcode=0x0406, data_len=6)
        complete.data[:6] = peers[0].address
        if (not request.seq or bytes(request) != bytes(canonical) or bytes(result) != bytes(complete)
                or type(query['start_wall_ns']) is not int or type(query['end_wall_ns']) is not int
                or not 0 < query['start_wall_ns'] < query['end_wall_ns']):
            raise ValueError('actual peer MAC query identity/result/interval required')
    if queries[0]['end_wall_ns'] >= markers[0]['wall_ns'] or queries[1]['start_wall_ns'] <= receipts[-1]['wall_ns']:
        raise ValueError('peer queries must bracket held retirement')


def corroborate(record, host, capture, stderr, kernel_log, owner, peer, host_owner):
    verify_records(record)
    if (host.get('complete') is not True or host.get('method') != 'QMP_HOLD_ACTUAL_IN81_UNTIL_NATIVE_RETIREMENT'
            or host.get('observations') != record['host_hold_acknowledgements']):
        raise ValueError('matching actual host retirement readbacks required')
    held = re.findall(r'WS73_TEST_RUNTIME_HOLD: dev (\d+):(\d+) bytes=(\d+) host_status=0 holds=(\d+) sha256=([0-9a-f]{64})', stderr)
    if (len(held) != 1 or tuple(map(int, held[0][:2])) != (host_owner['bus'], host_owner['address'])
            or held[0][2:4] != ('178', '1') or 'WS73_TEST_RUNTIME_HOLD_RELEASE:' in stderr):
        raise ValueError('one real target-only MAC transfer held and never released required')
    target_snapshot = _decode(SleControllerSnapshot, record['target_snapshot'])
    peer_snapshot = _decode(SleControllerSnapshot, record['peer_snapshots'][0])
    if (owner['index'] != 0 or owner['generation'] <= target_snapshot.generation
            or peer['index'] != 1 or peer['generation'] != peer_snapshot.generation):
        raise ValueError('new target and surviving peer registrations required before daemon RF')
    start = record['submit_before_wall_ns']; end = record['guest_ack_receipts'][-1]['wall_ns']
    commands = [c for c in capture['commands'] if (c['bus'], c['device'], c['opcode']) ==
                (owner['bus'], owner['device'], 0x0406) and start <= c['wall_ns'] <= c['completion']['wall_ns'] <= end]
    if len(commands) != 1 or commands[0]['params'] != '':
        raise ValueError('one accepted actual held MAC command required')
    if any(c.get('usb_sha256') == held[0][4] for c in capture['complete'] + capture['reports']):
        raise ValueError('aborted original host payload was delivered to guest')
    if any(c['opcode'] == 0x0406 and (c['bus'],c['device']) == (owner['bus'],owner['device'])
           and commands[0]['wall_ns'] <= c['wall_ns'] <= end for c in capture['complete']):
        raise ValueError('held target replied before retirement acknowledgment')
    def log_times(pattern):
        from decimal import Decimal
        return [int(Decimal(v)*1_000_000_000) for v in re.findall(pattern, kernel_log, re.M)]
    timeouts = log_times(r'^\[\s*(\d+\.\d+)\].*sle0 USB command Host timed out\s*$')
    retirements = log_times(r'^\[\s*(\d+\.\d+)\].*sparklink_ws73_usb 1-1:1\.0: native RX stopped: -110\s*$')
    # Correlate this gate, not an unrelated later fault in the RF regression.
    first = record['submit_before_monotonic_ns']; last = record['quiet_after_monotonic_ns']
    timeouts = [v for v in timeouts if first+450_000_000 <= v <= last]
    if len(timeouts) != 1 or sum(timeouts[0] <= v <= last for v in retirements) != 1:
        raise ValueError('causal target Host timeout and native retirement during passive wait required')
    from ws73_capture import command_reply
    initialization_proofs = []
    for identity,row in zip([owner,peer],record['initializations']):
        proofs = []
        for opcode,params in [(0x0c02,None),(0x0c05,'0000000000'),(0x1001,'0000010040062003'),(0x1002,'0100'),(0x1002,'0000')]:
            candidates = [c for c in capture['commands'] if (c['bus'],c['device'],c['opcode']) ==
                          (identity['bus'],identity['device'],opcode) and row['start_wall_ns'] <= c['wall_ns'] <= row['end_wall_ns']
                          and (params is None or c['params']==params)]
            if len(candidates)!=1: raise ValueError('one real canonical initializer recipe step required')
            command=candidates[0]
            following=[c['wall_ns'] for c in capture['commands'] if (c['bus'],c['device'],c['opcode']) ==
                       (identity['bus'],identity['device'],opcode) and command['wall_ns'] < c['wall_ns'] <= row['end_wall_ns']]
            end=min(following)-1 if following else row['end_wall_ns']
            filtered=dict(capture,commands=[command])
            proofs.append(command_reply(filtered,identity,opcode,command['wall_ns'],end,
                                        None if params is None else bytes.fromhex(params)))
        initialization_proofs.append(proofs)
    peer_proofs = [command_reply(capture, peer, 0x0406, q['start_wall_ns'], q['end_wall_ns'], b'',
                                bytes(_decode(SleControllerSnapshot, record['peer_snapshots'][0]).address).hex())
                   for q in record['peer_queries']]
    return {'status': 'ACTIVE_USB_TIMEOUT_RETIREMENT_CORROBORATED_PRE_DAEMON',
            'host_transfer_sha256': held[0][4], 'host_transfer_bytes': 178,
            'host_usb_identity': {'bus': host_owner['bus'], 'address': host_owner['address']},
            'held_command': commands[0], 'peer_queries': peer_proofs,
            'initialization_stops': initialization_proofs,
            'host_timeout_monotonic_ns': timeouts[0],
            'exact_deadline_latency_bound_qualified': False,
            'daemon_continuity_during_hold_qualified': False,
            'natural_fault_root_cause_closed': False, 'physical_acceptance': False}


def run(args):
    if 'ws73.active_deadline=1' not in Path('/proc/cmdline').read_text().split() or __import__('os').geteuid() != 0:
        raise ValueError('explicit root VM active deadline mode required')
    folder = args.output
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = {'format_version': 1, 'status': 'STARTING', 'physical_acceptance': False,
              'automatic_fault_recovery_acceptance': False, 'daemon_running_during_hold': False,
              'host_hold_acknowledgements': [], 'guest_ack_receipts': [], 'markers': [], 'peer_queries': [], 'peer_snapshots': [], 'initializations': []}
    def save():
        temporary = folder / 'run.tmp'; temporary.write_text(json.dumps(record, indent=2)+'\n'); temporary.replace(folder/'run.json')
    def marker(phase, ack):
        value = {'hold_phase': phase, 'wall_ns': time.time_ns()}; record['markers'].append(value)
        write_marker(folder/f'hold-{phase}.json', value)
        deadline = time.monotonic()+6
        while not (folder/f'hold-{ack}-ack.json').exists():
            if time.monotonic() > deadline: raise TimeoutError('actual host acknowledgment timeout')
            time.sleep(0.005)
        response = json.loads((folder/f'hold-{ack}-ack.json').read_text())
        if response['stage'] != ack or response['request'] != value: raise ValueError('mismatched host acknowledgment')
        record['guest_ack_receipts'].append({'stage':ack,'wall_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns()})
        record['host_hold_acknowledgements'].append(response); save()
    adapters = []
    initializer = None
    try:
        for index in [0, 1]:
            deadline = time.monotonic()+90
            while True:
                adapter = None
                ready = False
                try:
                    adapter = NativeAdapter(index); snapshot = adapter.snapshot()
                    if snapshot.valid_fields == 1 and snapshot.profile == 1 and snapshot.flags != 4:
                        record['initializations'].append({'initial_snapshot':bytes(snapshot).hex()})
                        ready = True
                        break
                except OSError as error:
                    if error.errno not in (errno.ENODEV, errno.EAGAIN): raise
                finally:
                    if adapter is not None and not ready: adapter.close()
                if time.monotonic() > deadline: raise TimeoutError('independent metadata availability')
                time.sleep(0.01)
            adapters.append(adapter)
            if index == 0:
                save()
                write_marker(folder / 'metadata-0.json', {'slot': 0, 'initial_snapshot': bytes(snapshot).hex()})
                print('WS73_TARGET_ACTIVE_METADATA: slot=0', flush=True)
        for row in record['initializations']: row['start_wall_ns']=time.time_ns()
        with (folder/'initializer.log').open('wb') as log:
            initializer=subprocess.Popen(['/bin/slkd','--storage','/tmp/active-init-bonds','-n'],stdout=log,stderr=subprocess.STDOUT)
            record.update(initializer_method='EXISTING_SLKD_MANAGED_STANDBY',initializer_pid=initializer.pid);save()
            deadline=time.monotonic()+20
            while not all(adapter.snapshot().flags==1 for adapter in adapters):
                if initializer.poll() is not None or time.monotonic()>deadline: raise TimeoutError('existing slkd did not initialize both actual Ready controllers')
                time.sleep(0.01)
            initializer.terminate();record['initializer_exit']=initializer.wait(timeout=10)
        for adapter,row in zip(adapters,record['initializations']):
            deadline=time.monotonic()+6
            while adapter.management_status().state!=0:
                if time.monotonic()>deadline: raise TimeoutError('initializer did not relinquish Managed ownership')
                time.sleep(0.01)
            row.update(ready_snapshot=bytes(adapter.snapshot()).hex(),end_wall_ns=time.time_ns())
        record['target_snapshot']=record['initializations'][0]['ready_snapshot']
        record['peer_snapshots'].append(record['initializations'][1]['ready_snapshot'])
        target, peer = adapters
        leases = [a.acquire_management(2) for a in adapters]
        def query_peer(request_id):
            command = SleDiagnosticSubmit(version=1, generation=peer.generation, request_id=request_id,
                                          timeout_ms=5000, opcode=0x0406, action=1)
            start = time.time_ns(); peer.submit_diagnostic(command); deadline = time.monotonic()+6
            while True:
                result = peer.diagnostic_result(command.seq)
                if result is not None and result.state != 1: break
                if time.monotonic() > deadline: raise TimeoutError('real peer MAC query')
                time.sleep(0.005)
            record['peer_queries'].append({'output': bytes(command).hex(), 'result': bytes(result).hex(),
                                          'start_wall_ns': start, 'end_wall_ns': time.time_ns()}); save()
        query_peer(1)
        marker('arm_ready', 'armed')
        command = SleDiagnosticSubmit(version=1, generation=target.generation, request_id=1,
                                      timeout_ms=500, opcode=0x0406, action=1)
        record['input'] = bytes(command).hex(); record['submit_before_wall_ns'] = time.time_ns()
        record['submit_before_monotonic_ns'] = time.monotonic_ns()
        target.submit_diagnostic(command)
        record['submit_after_monotonic_ns'] = time.monotonic_ns(); record['submit_after_wall_ns'] = time.time_ns()
        record['output'] = bytes(command).hex()
        record['initial_result'] = bytes(target.diagnostic_result(command.seq)).hex()
        marker('wait_held', 'held')
        record['quiet_before_monotonic_ns'] = time.monotonic_ns()
        marker('abort_ready', 'aborted')  # passive filesystem/QMP wait: no ioctl can expire the author
        record['quiet_after_monotonic_ns'] = time.monotonic_ns()
        for key, operation in [('retired_result_errno', lambda: target.diagnostic_result(command.seq)),
                               ('retired_submit_errno', lambda: target.submit_diagnostic(command))]:
            try: operation()
            except OSError as error: record[key] = error.errno
            else: raise ValueError('retired selected fd accepted request')
        record['peer_snapshots'].append(bytes(peer.snapshot()).hex()); query_peer(2)
        peer.release_management(leases[1], 2)
        deadline = time.monotonic()+6
        while peer.management_status().state != 0:
            if time.monotonic() > deadline: raise TimeoutError('peer lease did not settle Free')
            time.sleep(0.01)
        record['status'] = 'ACTIVE_DEADLINE_PRE_DAEMON_PASS'; verify_records(record); save()
    except BaseException as error:
        record.update(status='FAIL', error=str(error)); save(); raise
    finally:
        if initializer is not None and initializer.poll() is None:
            initializer.terminate()
            try: initializer.wait(timeout=5)
            except subprocess.TimeoutExpired: initializer.kill();initializer.wait(timeout=5)
        for adapter in reversed(adapters): adapter.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
