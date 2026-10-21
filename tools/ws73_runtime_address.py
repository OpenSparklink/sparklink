#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit VM-only volatile address gate through the existing Native CLI.

No libusb, firmware writes, address allocation or alternate protocol engine.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from ws73_capture import CaptureError, command_reply, json_identity
from ws73_lab_resources import observe_guest_hcc
from ws73_north_star import file_record, registration


def parse_addresses(values):
    if len(values) != 2 or any(not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', v) for v in values):
        raise ValueError('exactly two explicit six-byte addresses required')
    result = [v.upper() for v in values]
    if len(set(result)) != 2 or any(v in ('00:00:00:00:00:00', 'FF:FF:FF:FF:FF:FF') for v in result):
        raise ValueError('different nonzero Native metadata addresses required')
    return result


def requested(args):
    values = getattr(args, 'runtime_addresses', None)
    if values is None:
        return None
    values = parse_addresses(values)
    ports = list(args.ports)
    # Slot order is explicit input, not device selection. Keep exactly the two
    # assigned E leaves; addresses follow that order through QMP and readback.
    if (args.command != 'run' or len(ports) != 2 or set(ports) != {'1-2.1.1', '1-2.1.2'}
            or not getattr(args, 'qmp_hotplug', False) or not getattr(args, 'channel_socket_verify', False)
            or not getattr(args, 'connection_verify', False)):
        raise ValueError('volatile E gate requires the explicit assigned E pair and ordinary connection/socket VM')
    return values


def boot_addresses(words):
    values = [w.split('=', 1)[1] for w in words if w.startswith('ws73.runtime_addresses=')]
    if not values:
        return None
    if len(values) != 1 or words.count('ws73.expected_models=E,E') != 1:
        raise ValueError('one explicit E/E volatile address configuration required')
    return parse_addresses(values[0].split(','))


def decode_query(row, owner):
    pattern = (rf'NativeDiagnosticQuery: index={owner["index"]} generation={owner["generation"]} '
               r'opcode=0x0406 admission_seq=([1-9][0-9]*) status=0x00 data=([0-9a-f]{12})\n')
    match = re.fullmatch(pattern, row['stdout'])
    expected=['/bin/slkconfig','--adapter',str(owner['index']),'--generation',str(owner['generation']),'query','mac']
    if row.get('args')!=expected or row['exit'] or row['stderr'] or not match:
        raise ValueError('actual successful typed Native 0406 query receipt required')
    return match[2]


def configure():
    if os.getuid() != 0 or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU':
        raise ValueError('explicit root-only isolated QEMU gate required')
    addresses = boot_addresses(Path('/proc/cmdline').read_text().split())
    if addresses is None:
        raise ValueError('volatile addresses not explicitly requested')
    out = Path('/evidence/runtime-address');out.mkdir(exist_ok=False)
    path = out/'run.json'
    result = dict(version=1, status='RUNNING_NOT_QUALIFIED', addresses=addresses,
                  runtime_only=True, official_identity=False, commands=[], owners=[], originals=[], setters=[],
                  sources=[file_record(Path(__file__)), file_record('/bin/slkconfig')], uid=os.getuid())
    def save(): path.write_text(json.dumps(result, indent=2)+'\n')
    def call(owner, *operation):
        command = ['/bin/slkconfig', '--adapter', str(owner['index']), '--generation', str(owner['generation']), *operation]
        row = dict(args=command, start_wall_ns=time.time_ns(), start_monotonic_ns=time.monotonic_ns())
        result['commands'].append(row);save()
        try:
            p = subprocess.run(command, text=True, capture_output=True, timeout=12)
            row.update(exit=p.returncode, stdout=p.stdout, stderr=p.stderr)
        finally:
            row.update(end_wall_ns=time.time_ns(), end_monotonic_ns=time.monotonic_ns());save()
        if p.returncode: raise ValueError('Native command rejected; original error retained')
        return len(result['commands'])-1, row
    try:
        for slot in range(2):
            deadline = time.monotonic()+90
            while True:
                try:
                    owner = registration(f'1-{slot+1}')
                    observed = observe_guest_hcc(owner, 'E')
                    break
                except (OSError, ValueError):
                    if time.monotonic() >= deadline: raise
                    time.sleep(.2)
            result['owners'].append(observed);save()
            # The existing runner waits on this explicit setup observation to
            # attach the second leaf. This is neither daemon Ready nor a grant.
            print(f'WS73_TARGET_ADDRESS_SETUP: slot={slot}', flush=True)
        for owner in result['owners']:
            idx, row = call(owner, 'query', 'mac')
            result['originals'].append(dict(query=idx, address=decode_query(row, owner)));save()
        if any(v.replace(':', '').lower() in [x['address'] for x in result['originals']] for v in addresses):
            raise ValueError('requested address conflicts with observed original pair')
        for slot, owner in enumerate(result['owners']):
            peer = result['owners'][1-slot]
            before_idx, before_row = call(peer, 'query', 'mac')
            before = decode_query(before_row, peer)
            idx, row = call(owner, 'runtime-address', addresses[slot])
            after_idx, after_row = call(peer, 'query', 'mac')
            if decode_query(after_row, peer) != before:
                raise ValueError('changing one controller changed the peer address')
            current = registration(owner['port'])
            if any(current[k] != owner[k] for k in ('index','generation','bus','device')) or current['address'] != addresses[slot]:
                raise ValueError('Runtime/sysfs identity disagrees with configured readback')
            result['setters'].append(dict(slot=slot, command=idx, peer_before=before_idx, peer_after=after_idx,
                                           configured=current));save()
        result['status'] = 'REAL_READBACK_PENDING_CAPTURE_AUDIT'
    except BaseException as error:
        result.update(status='FAIL', error=type(error).__name__+': '+str(error));raise
    finally: save()


def corroborate(record, capture, addresses):
    addresses = parse_addresses(addresses)
    if (record.get('version') != 1 or record.get('status') != 'REAL_READBACK_PENDING_CAPTURE_AUDIT'
            or record.get('addresses') != addresses or record.get('runtime_only') is not True
            or record.get('official_identity') is not False or record.get('uid') != 0
            or len(record.get('owners', [])) != 2 or len(record.get('setters', [])) != 2
            or len(record.get('originals', [])) != 2):
        raise CaptureError('complete limited volatile address gate required')
    proofs = {}
    commands = record['commands']
    for slot, (owner, original, setter) in enumerate(zip(record['owners'], record['originals'], record['setters'])):
        if setter['slot'] != slot or owner['port'] != f'1-{slot+1}' or owner['hcc_chip']['model'] != 'E' or owner['hcc_chip']['bus'] != 'USB':
            raise CaptureError('explicit slot and actual E/USB observation required')
        def query(index, wanted=None, target=owner):
            row = commands[index]
            value = decode_query(row, target)
            if wanted is not None and value != wanted: raise CaptureError('query differs from expected observed value')
            return command_reply(capture, target, 0x0406, row['start_wall_ns'], row['end_wall_ns'], b'', value)
        old = query(original['query'], original['address'])
        row = commands[setter['command']]
        prefix = f'index={owner["index"]} generation={owner["generation"]}'
        old_lines = re.findall(rf'^NativeRuntimeAddressOriginal: {prefix} opcode=0x0406 admission_seq=([1-9][0-9]*) data=([0-9a-f]{{12}})$', row['stdout'], re.M)
        set_lines = re.findall(rf'^NativeRuntimeAddressSetComplete: {prefix} opcode=0x0405 admission_seq=([1-9][0-9]*) status=0x00$', row['stdout'], re.M)
        final = re.findall(rf'^NativeRuntimeAddressVerified: {prefix} setter_seq=([1-9][0-9]*) readback_seq=([1-9][0-9]*) original=([0-9a-f]{{12}}) readback=([0-9a-f]{{12}}) runtime_only=true official_identity=false$', row['stdout'], re.M)
        expected = addresses[slot].replace(':', '').lower()
        expected_args=['/bin/slkconfig','--adapter',str(owner['index']),'--generation',str(owner['generation']),'runtime-address',addresses[slot]]
        if row.get('args')!=expected_args or row['exit'] or row['stderr'] or len(old_lines) != 1 or len(set_lines) != 1 or len(final) != 1 or old_lines[0][1] != original['address'] or final[0][2:] != (original['address'], expected) or final[0][0] != set_lines[0][0] or not int(old_lines[0][0]) < int(final[0][0]) < int(final[0][1]):
            raise CaptureError('real original/setter/readback correlated receipts required')
        set_proof = command_reply(capture, owner, 0x0405, row['start_wall_ns'], row['end_wall_ns'], bytes.fromhex(expected), '')
        queries = [q for q in capture['commands'] if (q['bus'],q['device'],q['opcode']) == (owner['bus'],owner['device'],0x0406) and row['start_wall_ns'] <= q['wall_ns'] <= row['end_wall_ns']]
        if len(queries) != 2: raise CaptureError('one original and one later controller readback required')
        set_start = set_proof['command']['wall_ns']
        first = command_reply(capture, owner, 0x0406, row['start_wall_ns'], set_start-1, b'', original['address'])
        verified = command_reply(capture, owner, 0x0406, set_proof['reply']['wall_ns']+1, row['end_wall_ns'], b'', expected)
        if verified['reply']['wall_ns']-set_start >= 5_000_000_000: raise CaptureError('original setter deadline exceeded')
        peer = record['owners'][1-slot]
        pre = query(setter['peer_before'], target=peer)
        post = query(setter['peer_after'], pre['reply']['value'], target=peer)
        if not old['reply']['wall_ns'] < pre['command']['wall_ns'] < first['command']['wall_ns'] < post['command']['wall_ns']:
            raise CaptureError('original/peer/setting timeline mismatch')
        current = setter['configured']
        if any(current[k] != owner[k] for k in ('index','generation','bus','device','port')) or current['address'] != addresses[slot]:
            raise CaptureError('current Runtime observation differs from real readback')
        proofs[json_identity(current)] = dict(original=old, before_set=first, setter=set_proof, readback=verified,
                                              peer_before=pre, peer_after=post, scope='temporary volatile configuration only')
    return proofs


if __name__ == '__main__':
    configure()
