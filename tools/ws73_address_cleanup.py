# SPDX-License-Identifier: GPL-2.0-only
"""Read-only eligibility for the existing volatile-address maintenance path.

No VM, native setter, retry or recovery verdict is implemented here. Callers
must separately freeze the execution closure, wait their own VM, and recheck
the live resource policy/leases before any maintenance operation. A fresh VM
is not evidence that firmware obligations have drained.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from ws73_capture import check_capture_stats, command_reply, read_capture
from ws73_runtime_address import check_originals, decode_query, originals_document, parse_addresses


def require(condition, message):
    if not condition:
        raise ValueError(message)


def material(path):
    """Hash an existing regular file; never follow a leaf symlink or rewrite it."""
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'regular cleanup evidence required')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        size = stream.tell()
    return dict(path=str(path.resolve()), sha256=digest, bytes=size)


def terminal_setters(record, capture, addresses):
    """Account for every attempted and observed 0405 without using setters[].

    Complete/readback and peer-before/after evidence can survive a later CLI
    or supervisor failure. Such evidence does not turn that failure into PASS.
    Unknown/unfinished attempts are deliberately outside the admitted slice.
    The USB-to-readback bound is not the original software-admission deadline.
    """
    addresses = parse_addresses(addresses)
    require(record.get('addresses') == addresses, 'explicit selected address pair required')
    require(record.get('status') in ('FAIL', 'RUNNING_NOT_QUALIFIED',
                                    'REAL_READBACK_PENDING_CAPTURE_AUDIT'), 'known setup progress state required')
    originals_document(record)  # Actual shared typed-query and owner checks.
    owners, rows = record['owners'], record['commands']
    require(len({(v['bus'], v['device']) for v in owners}) == 2, 'distinct USB registrations required')
    require(len({v['index'] for v in owners}) == 2, 'distinct controller indices required')
    require(2 <= len(rows) <= 8, 'bounded original setup command sequence required')
    require(capture.get('failures') == [], 'USB failures leave physical obligations unproved')
    identities = {(v['bus'], v['device']) for v in owners}
    require(all((v['bus'], v['device']) in identities for v in capture['commands']),
            'foreign USB command in setup evidence')
    require(not any(0x0c00 <= v['opcode'] <= 0x1405 for v in capture['commands']),
            'address cleanup evidence must precede advertising and connection activity')
    originals = []
    for slot, owner in enumerate(owners):
        row = rows[slot]
        value = decode_query(row, owner)
        originals.append(command_reply(capture, owner, 0x0406,
                         row['start_wall_ns'], row['end_wall_ns'], b'', value))
    attempts = []
    previous_end = None
    for index, row in enumerate(rows):
        start, end = row['start_wall_ns'], row['end_wall_ns']
        require(type(start) is int and type(end) is int and start < end,
                'complete subprocess interval required')
        require(previous_end is None or previous_end <= start, 'sequential command intervals required')
        previous_end = end
        require(row.get('timed_out') is not True and row.get('physical_outcome') != 'unknown'
                and type(row.get('exit')) is int, 'unknown or unfinished subprocess requires retained obligations')
        candidates = [(slot, operation) for slot, owner in enumerate(owners)
                      for operation in ('query', 'runtime-address')
                      if row.get('args') == ['/bin/slkconfig', '--adapter', str(owner['index']),
                         '--generation', str(owner['generation']), operation,
                         'mac' if operation == 'query' else addresses[slot]]]
        require(len(candidates) == 1, 'exact original typed command and owner required')
        slot, operation = candidates[0]
        if operation == 'runtime-address':
            attempts.append((index, slot))
    wire_setters = [v for v in capture['commands'] if v['opcode'] == 0x0405]
    wire_completes = [v for v in capture['complete'] if v['opcode'] == 0x0405]
    require(len(attempts) == len(wire_setters) <= 2, 'every attempted and outgoing setter must be accounted for')
    require(len(wire_completes) == len(wire_setters)
            and all(v['status'] == 0 for v in wire_completes), 'no failed, duplicate or unaccounted setter Complete')
    require(len({slot for _, slot in attempts}) == len(attempts), 'no repeated setter in a registration')
    require(len({v['record'] for v in wire_setters}) == len(wire_setters), 'unique physical setter records required')
    proofs, matched = [], set()
    for index, slot in attempts:
        # Production configure performs peer query, setter (with internal
        # original/query readback), then peer query. Its summary append can fail
        # afterwards; the raw commands still retain this complete transaction.
        require(index >= 3 and index + 1 < len(rows), 'both peer observations required')
        row, owner, peer = rows[index], owners[slot], owners[1-slot]
        start, end = row['start_wall_ns'], row['end_wall_ns']
        temporary = addresses[slot].replace(':', '').lower()
        setter = command_reply(capture, owner, 0x0405, start, end, bytes.fromhex(temporary), '')
        original = command_reply(capture, owner, 0x0406, start,
                                 setter['command']['wall_ns']-1, b'', record['originals'][slot]['address'])
        readback = command_reply(capture, owner, 0x0406,
                                setter['reply']['wall_ns']+1, end, b'', temporary)
        queries = [v for v in capture['commands']
                   if (v['bus'], v['device'], v['opcode']) == (owner['bus'], owner['device'], 0x0406)
                   and start <= v['wall_ns'] <= end]
        require(len(queries) == 2, 'one original query and one readback per setter required')
        require(readback['reply']['wall_ns']-setter['command']['wall_ns'] < 5_000_000_000,
                'observed USB-to-readback evidence interval exceeded')
        before, after = rows[index-1], rows[index+1]
        peer_value = decode_query(before, peer)
        require(decode_query(after, peer) == peer_value, 'peer address changed or peer query incomplete')
        pre = command_reply(capture, peer, 0x0406, before['start_wall_ns'], before['end_wall_ns'], b'', peer_value)
        post = command_reply(capture, peer, 0x0406, after['start_wall_ns'], after['end_wall_ns'], b'', peer_value)
        require(max(v['reply']['wall_ns'] for v in originals) < pre['command']['wall_ns']
                < original['command']['wall_ns'] < setter['command']['wall_ns']
                < readback['reply']['wall_ns'] < post['command']['wall_ns'],
                'saved originals, setter and unchanged peer timeline required')
        matched.add(setter['command']['record'])
        proofs.append(dict(slot=slot, original=original, setter=setter, readback=readback,
                           peer_before=pre, peer_after=post, cli_exit=row['exit']))
    require(matched == {v['record'] for v in wire_setters}, 'unaccounted physical setter')
    return dict(original_queries=originals, terminal_setters=proofs,
                classification='NO_SETTER_OBSERVED' if not proofs else 'ALL_OBSERVED_SETTERS_COMPLETE_AND_READ_BACK',
                original_request_deadline_qualified=False, firmware_drain_proved=False,
                restoration_confirmed=False)


def inspect_setup(share, *, addresses, bindings, expected_sources):
    """Inspect preserved failed/successful setup without awarding recovery.

    bindings is the caller's previously pinned ordered guest/physical mapping,
    containing host_port, guest_port and serial_sha256 for each leaf. It is not
    a substitute for rechecking the current policy and live USB ownership.
    The original progress and originals journal are never changed. Missing or
    truncated progress remains ineligible even when the journal survives.
    """
    require(isinstance(bindings, list) and len(bindings) == 2, 'two ordered leaf bindings required')
    require(all(isinstance(v, dict) and set(v) == {'host_port', 'guest_port', 'serial_sha256'}
                and isinstance(v['host_port'], str) and v['host_port']
                and v['guest_port'] == f'1-{slot+1}'
                and isinstance(v['serial_sha256'], str) and re.fullmatch('[0-9a-f]{64}', v['serial_sha256'])
                for slot, v in enumerate(bindings)), 'explicit physical and guest binding fields required')
    require(len({v['host_port'] for v in bindings}) == 2
            and len({v['serial_sha256'] for v in bindings}) == 2, 'distinct pinned physical leaves required')
    require(isinstance(expected_sources, list) and len(expected_sources) == 2,
            'pinned helper and actual Native CLI sources required')
    share = Path(share)
    out = share/'runtime-address'
    paths = [out/'run.json', out/'originals.json', share/'ws73.pcap', share/'capture-stats.txt']
    pins = [material(path) for path in paths]
    record = json.loads(paths[0].read_text())
    require(record.get('version') == 1 and record.get('sources') == expected_sources,
            'setup helper/CLI identity differs from frozen inputs')
    journal = check_originals(out, record)
    for owner, binding in zip(record['owners'], bindings):
        serial = owner.get('descriptors', {}).get('serial')
        require(isinstance(serial, str) and bool(serial) and owner['port'] == binding['guest_port']
                and hashlib.sha256(serial.encode()).hexdigest() == binding['serial_sha256'],
                'saved guest descriptor does not match pinned physical leaf')
    capture = read_capture(paths[2], [(v['bus'], v['device']) for v in record['owners']])
    require(capture['packet_count'] == check_capture_stats(paths[3].read_text()), 'complete zero-drop capture required')
    proof = terminal_setters(record, capture, addresses)
    require([material(path) for path in paths] == pins and check_originals(out, record) == journal,
            'cleanup inputs changed during validation')
    return dict(version=1, status='ORIGINALS_VALIDATED_CLEANUP_ELIGIBLE_NOT_RESTORED',
                original_setup_status=record['status'], bindings=bindings,
                temporary=[v.replace(':', '').lower() for v in parse_addresses(addresses)],
                originals=[v['address'] for v in record['originals']], journal=journal,
                sources=expected_sources, materials=pins, proof=proof,
                owned_vm_exit_and_live_ownership_required=True, current_policy_recheck_required=True,
                new_vm_is_not_firmware_drain=True, natural_recovery_qualified=False)
