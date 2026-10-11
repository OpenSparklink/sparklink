#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strict offline USB/HCC/DLI corroboration, never a claim of PHY sniffing.

Layouts: Linux Documentation/usb/usbmon.rst, drivers/usb/mon/mon_bin.c,
libpcap pcap/usb.h and pcap-savefile(5); WS73 driver wire.c/discovery.c.
Only classic pcap LINKTYPE_USB_LINUX_MMAPPED (220) is supported.
"""
import hashlib
from pathlib import Path
import struct
import re


class CaptureError(ValueError):
    pass


def marker_data(marker):
    if len(marker) != 32 or any(c not in '0123456789abcdef' for c in marker):
        raise CaptureError('expected 16-byte lowercase hex marker')
    return bytes([255, 41, 1, 1, 1, 11, 36]) + ('slk-' + marker).encode()


def hcc_receive(data):
    """Validate every aggregate boundary before returning any slot."""
    if not 12 <= len(data) <= 20 * 1024:
        raise CaptureError('invalid USB aggregate size')
    kind, size = struct.unpack_from('<II', data)
    if kind == size == 0:
        if any(data):
            raise CaptureError('nonzero empty aggregate tail')
        return []
    if kind != 2 or size != len(data) or size < 92:
        raise CaptureError('invalid RX aggregate header/length')
    lengths = struct.unpack_from('<24H', data, 12)
    slots, offset, ended = [], 92, False
    for length in lengths:
        if not length:
            ended = True
            continue
        if ended or length < 4 or offset + length > size:
            raise CaptureError('invalid HCC slot boundary')
        tag, queue, payload_length = struct.unpack_from('<BBH', data, offset)
        service = tag >> 4
        if payload_length > length - 4:
            raise CaptureError('HCC payload exceeds slot')
        # SDK SLE RX ignores subtype; real 111 CmdComplete uses a1.
        if (service, queue) == (5, 10) and tag & 15:
            raise CaptureError('nonzero supported-service subtype')
        slots.append((service, queue, offset, data[offset + 4:offset + 4 + payload_length]))
        offset += length
    if offset != size:
        raise CaptureError('unassigned aggregate tail')
    return slots


def discovery(payload):
    if len(payload) < 5 or payload[0] != 0xa2:
        return None
    event, size = struct.unpack_from('<HH', payload, 1)
    if event != 0x180b:
        return None
    if size != len(payload) - 5 or size < 23 or size != 23 + payload[27]:
        raise CaptureError('invalid WS73 discovery event length')
    header = payload[5:28]
    return {'address': ':'.join(f'{b:02X}' for b in header[2:8]),
            'rssi': struct.unpack('b', header[21:22])[0],
            'header': header.hex(), 'data': payload[28:].hex()}


def hcc_command(data):
    """Decode the driver's single-slot TX profile; never search padding."""
    if len(data) < 68 or struct.unpack_from('<I', data)[0] != 0:
        return None  # ROM/control messages have no native command proof.
    if data[64] >> 4 != 10 or data[65] != 8:
        return None  # PM/BSLE profiles have different TX allocation rules.
    _, size, sequence = struct.unpack_from('<III', data)
    payload_size = struct.unpack_from('<H', data, 66)[0]
    if (size != len(data) or data[64] != 0xa0 or payload_size < 5
            or len(data) < 73 or data[68] != 0xa1):
        raise CaptureError('invalid native TX HCC/header')
    opcode, params_size = struct.unpack_from('<HH', data, 69)
    if (not opcode or params_size > 255 or payload_size != 5 + params_size
            or len(data) != 64 + max(64, 9 + params_size)):
        raise CaptureError('invalid native TX command length/opcode')
    return dict(opcode=opcode, params=data[73:73 + params_size].hex(), sequence=sequence)


def read_capture(path, targets):
    """Read endpoint-1 IN and pair OUT submission/completion by USB/URB identity.

    Refuse truncation/malformed traffic on a target; ignore unrelated USB data.
    Keep raw file offsets and hashes for independently inspecting each proof.
    Capture content is not authenticated and synthetic fixtures are not RF.
    """
    reports, complete, failures, empty, commands = [], [], [], [], []
    pending = {}
    targets = set(tuple(t) for t in targets)
    with Path(path).open('rb') as stream:
        header = stream.read(24)
        if len(header) != 24:
            raise CaptureError('missing pcap header')
        formats = {b'\xd4\xc3\xb2\xa1': ('<', 1000), b'\xa1\xb2\xc3\xd4': ('>', 1000),
                   b'\x4d\x3c\xb2\xa1': ('<', 1), b'\xa1\xb2\x3c\x4d': ('>', 1)}
        try:
            endian, scale = formats[header[:4]]
        except KeyError as error:
            raise CaptureError('unsupported capture format (classic pcap required)') from error
        major, minor, _, _, snaplen, link = struct.unpack(endian + 'HHiiII', header[4:])
        if (major, minor) != (2, 4) or link != 220 or not 64 <= snaplen <= 16 * 1024 * 1024:
            raise CaptureError('unsupported pcap version/linktype/snaplen')
        ordinal = 0
        while True:
            offset = stream.tell()
            record = stream.read(16)
            if not record:
                break
            if len(record) != 16:
                raise CaptureError('truncated pcap record header')
            sec, fraction, captured, original = struct.unpack(endian + 'IIII', record)
            if captured > snaplen or captured > original or fraction >= 1_000_000_000 // scale:
                raise CaptureError('invalid pcap record lengths/time')
            packet = stream.read(captured)
            if len(packet) != captured or captured < 64:
                raise CaptureError('truncated USB packet/header')
            ordinal += 1
            # libpcap swaps the pseudoheader fields with the file byte order.
            urb, kind, transfer, endpoint, device, bus, _, flag_data, usb_sec, usec, status, length, cap = struct.unpack_from(endian + 'QBBBBHBBqiiII', packet)
            if ((bus, device) not in targets or transfer != 3
                    or not (endpoint == 0x81 and kind == ord('C')
                            or endpoint == 0x01 and kind in map(ord, 'SCE'))):
                continue
            if usb_sec < 0 or not 0 <= usec < 1_000_000:
                raise CaptureError('invalid usbmon timestamp')
            timestamp = usb_sec * 1_000_000_000 + usec * 1000
            if abs(timestamp - (sec * 1_000_000_000 + fraction * scale)) > 1_000_000:
                raise CaptureError('pcap/usbmon clocks disagree')
            identity = {'bus': bus, 'device': device, 'wall_ns': timestamp,
                        'urb': urb, 'record': ordinal, 'file_offset': offset}
            if endpoint == 0x01:
                key = (bus, device, urb)
                if kind == ord('S'):
                    if key in pending:
                        raise CaptureError('duplicate pending OUT URB')
                    if flag_data or cap != length or captured != 64 + cap or original != captured:
                        raise CaptureError('target OUT submission absent or truncated')
                    raw = packet[64:]
                    pending[key] = (identity | {'usb_sha256': hashlib.sha256(raw).hexdigest()},
                                    length, hcc_command(raw))
                    continue
                submitted = pending.pop(key, None)
                if submitted is None:
                    raise CaptureError('OUT completion/error without captured submission')
                start, expected, command = submitted
                if timestamp < start['wall_ns']:
                    raise CaptureError('OUT completion predates submission')
                if status or kind == ord('E'):
                    failures.append(identity | {'status': status, 'endpoint': endpoint})
                    continue
                if length != expected or cap or captured != 64 or original != captured:
                    raise CaptureError('short or data-bearing OUT completion')
                if command is not None:
                    commands.append(start | command | {'completion': identity})
                continue
            if status:
                failures.append(identity | {'status':status, 'endpoint':endpoint})
                continue
            if not length:
                if cap or captured != 64 or original != captured:
                    raise CaptureError('successful empty IN completion contains data or truncation')
                empty.append({'bus':bus, 'device':device, 'wall_ns':timestamp,
                              'urb':urb, 'record':ordinal, 'file_offset':offset})
                continue  # no HCC/DLI report, completion or credit
            if flag_data or cap != length or captured != 64 + cap or original != captured:
                raise CaptureError('target IN payload absent or truncated')
            raw = packet[64:]
            # Each aggregate is validated atomically before interpreting DLI.
            for service, queue, slot, payload in hcc_receive(raw):
                if (service, queue) != (10, 8):
                    continue
                identity = identity | {'hcc_offset': slot, 'usb_sha256': hashlib.sha256(raw).hexdigest(), 'usb_length':len(raw)}
                report = discovery(payload)
                if report is not None:
                    reports.append(identity | report)
                if len(payload) >= 9 and payload[0] == 0xa2 and struct.unpack_from('<H', payload, 1)[0] == 2:
                    size, opcode = struct.unpack_from('<HH', payload, 3)
                    if size != len(payload) - 5:
                        raise CaptureError('malformed Complete length')
                    complete.append(identity | {'opcode': opcode, 'status': payload[8], 'value': payload[9:].hex()})
    if pending:
        raise CaptureError('unfinished OUT submission at capture end')
    return {'reports': reports, 'complete': complete, 'commands': commands, 'failures': failures,
            'empty_bulk_completions':empty, 'packet_count': ordinal}


def check_capture_stats(text):
    drops = re.findall(r'^(\d+) packets dropped by kernel$', text, re.M)
    if drops != ['0']:
        raise CaptureError('one complete capture statistic with zero kernel drops required')
    counts = re.findall(r'^(\d+) packets captured$', text, re.M)
    if len(counts) != 1 or int(counts[0]) <= 0:
        raise CaptureError('nonempty stopped capture statistic required')
    interface_drops = re.findall(r'^(\d+) packets dropped by interface$',text,re.M)
    if interface_drops not in ([],['0']):
        raise CaptureError('capture interface drops')
    return int(counts[0])


def corroborate(run, capture):
    """Require exact receiver-side bytes in each successful CLI observation."""
    if run.get('scope') != 'physical' or run.get('status') != 'CONTROL_PASS_EVIDENCE_PENDING':
        raise CaptureError('successful physical control run required; simulations excluded')
    if run.get('hotplug_method', 'PHYSICAL_UNPLUG_REPLUG') != 'PHYSICAL_UNPLUG_REPLUG':
        raise CaptureError('QMP disconnect excluded from physical unplug corroboration')
    # Recheck the recorded descriptor boundary independently of the recorder's
    # class/status label. Renaming a synthetic control record is not hardware.
    physical_descriptors(run)
    return _corroborate_control(run, capture)


def physical_descriptors(run):
    for r in [*run['initial'],run['replacement']]:
        descriptors=r.get('descriptors')
        if not isinstance(descriptors,dict) or set(descriptors)!={'manufacturer','product','serial'}:
            raise CaptureError('complete recorded USB descriptors required')
        for value in descriptors.values():
            if value is not None and not isinstance(value,str):
                raise CaptureError('invalid recorded USB descriptor')
            if value and ('synthetic' in value.lower() or 'fixture' in value.lower()):
                raise CaptureError('synthetic descriptors excluded from physical corroboration')


def corroborate_passthrough(run, capture):
    """Real RF with QMP guest lifecycle, never physical unplug acceptance."""
    if (run.get('scope') != 'real WS73 RF with QMP guest-detach control support'
            or run.get('status') != 'CONTROL_PASSTHROUGH_EVIDENCE_PENDING'
            or run.get('hotplug_method') != 'QMP_DEVICE_DEL_ADD'
            or run.get('physical_acceptance') is not False):
        raise CaptureError('explicit passthrough QMP control run required')
    physical_descriptors(run)
    return _corroborate_control(run, capture)


def corroborate_synthetic(run, capture):
    """Development control evidence only; never physical RX_CORROBORATED."""
    if run.get('scope') != 'synthetic WS73 USB control support' or run.get('status') != 'CONTROL_SUPPORT_EVIDENCE_PENDING':
        raise CaptureError('explicit synthetic control run required')
    for r in [*run['initial'],run['replacement']]:
        if (r['descriptors']['manufacturer'] != 'OpenSparklink synthetic test' or
                r['descriptors']['product'] != 'WS73 runtime fixture (NO RF)'):
            raise CaptureError('synthetic fixture descriptors missing')
    return _corroborate_control(run, capture)


def command_reply(capture, owner, opcode, start, end, params=None, value=None):
    """One submitted-and-completed OUT and one later successful DLI reply.

    IN delivery may race the host OUT-completion callback; both must precede
    the caller's observation end. The reply must follow the submission itself.
    """
    tx = [c for c in capture.get('commands', [])
          if (c['bus'], c['device'], c['opcode']) == (owner['bus'], owner['device'], opcode)
          and start <= c['wall_ns'] <= c['completion']['wall_ns'] <= end]
    if len(tx) != 1:
        raise CaptureError('one successful captured OUT command required')
    command = tx[0]
    if params is not None and command['params'] != params.hex():
        raise CaptureError('captured OUT parameters disagree with operation')
    replies = [c for c in capture['complete']
               if (c['bus'], c['device'], c['opcode'], c['status']) ==
                  (owner['bus'], owner['device'], opcode, 0)
               and command['wall_ns'] <= c['wall_ns'] <= end
               and command['record'] < c['record']]
    if len(replies) != 1:
        raise CaptureError('one successful DLI reply after captured OUT required')
    if value is not None and replies[0]['value'] != value:
        raise CaptureError('captured DLI result disagrees with operation')
    return dict(command=command, reply=replies[0])


def corroborate_recovery(run, capture, diagnostic=None):
    """Real RF after an artificial guest error; never physical/natural-fault acceptance."""
    if (run.get('scope') != 'real WS73 RF with artificial guest transport recovery support'
            or run.get('status') != 'RECOVERY_CONTROL_EVIDENCE_PENDING'
            or run.get('fault_method') != 'QMP_GUEST_TRANSPORT_ERROR_ONCE'
            or run.get('physical_acceptance') is not False
            or run.get('automatic_fault_recovery_acceptance') is not False):
        raise CaptureError('explicit artificial transport recovery run required')
    physical_descriptors(run)
    if not isinstance(run['fault_command']['exit'], int) or not run['fault_command']['exit']:
        raise CaptureError('fault command did not fail')
    old, new = run['initial'][0], run['replacement']
    if (old['bus'], old['device'], old['address']) != (new['bus'], new['device'], new['address']):
        raise CaptureError('protocol recovery changed USB/radio identity')
    metadata_before, queries = {}, []
    if diagnostic is not None:
        metadata_before, queries = corroborate_diagnostic(run, capture, diagnostic)
    proofs = _corroborate_control(run, capture, 'recovery', 'retirement_observed_wall_ns', metadata_before)
    if queries:
        proofs[0]['diagnostic_queries'] = queries
    return proofs


def corroborate_diagnostic(run, capture, diagnostic):
    """Separate bootstrap from explicit query/fault/quiet windows; never choose an arbitrary
    same-opcode reply in a broad registration window. Every query must have one
    completed OUT and one exact successful reply in its own observed interval.
    """
    from ws73_diagnostic_probe import QUERIES, verify_records
    if (diagnostic.get('status') != 'DIAGNOSTIC_RESULT_LIVE_PASS' or diagnostic.get('probe_exit') != 0
            or diagnostic.get('scope') != 'live real WS73 diagnostic syscall gate in isolated VM'
            or diagnostic.get('uid') != 0 or diagnostic.get('euid') != 0
            or diagnostic.get('physical_acceptance') is not False
            or diagnostic.get('automatic_fault_recovery_acceptance') is not False):
        raise CaptureError('scoped successful diagnostic syscall run required')
    version = diagnostic.get('format_version', 1)
    if (type(version) is not int or version not in (1, 2, 3, 4, 5, 6)
            or (version >= 2 and diagnostic.get('admission_copyout_requested') is not True)
            or (version == 1 and diagnostic.get('admission_copyout_requested') not in (None, False))
            or (version >= 3 and diagnostic.get('admission_eviction_requested') is not True)
            or (version < 3 and diagnostic.get('admission_eviction_requested') not in (None, False))
            or (version >= 4 and diagnostic.get('legacy_poll_copy_requested') is not True)
            or (version < 4 and diagnostic.get('legacy_poll_copy_requested') not in (None, False))
            or (version >= 5 and diagnostic.get('cancellation_requested') is not True)
            or (version < 5 and diagnostic.get('cancellation_requested') not in (None,False))
            or (version == 6 and diagnostic.get('deadline_requested') is not True)
            or (version < 6 and diagnostic.get('deadline_requested') not in (None,False))):
        raise CaptureError('explicit diagnostic admission evidence version required')
    try:
        verify_records(diagnostic['records'], admission=version >= 2, eviction=version >= 3,
                       legacy_poll=version >= 4,cancellation=version >= 5,deadline=version == 6)
    except (ValueError, KeyError, TypeError) as error:
        raise CaptureError('invalid diagnostic syscall records') from error
    owner = run['initial'][0]
    def window(key, first, last):
        return [r for r in capture[key] if r['bus']==owner['bus'] and r['device']==owner['device']
                and first <= r['wall_ns'] <= last]
    rows = [r for r in diagnostic['records'] if r.get('case') == 'metadata']
    if diagnostic['index'] != owner['index'] or any(r['generation'] != owner['generation'] for r in rows):
        raise CaptureError('diagnostic controller instance differs from initial registration')
    expected = {0x0406: owner['address'].replace(':', '').lower(), 0x0403: owner['features'],
                0x0404: owner['version'], 0x0402: struct.pack('<HBHB', *owner['buffers']).hex()}
    proofs = []
    previous = 0
    for row in rows:
        if row['data'] != expected[row['opcode']] or not previous <= row['start_wall_ns'] < row['end_wall_ns'] < owner['observed_wall_ns']:
            raise CaptureError('diagnostic data/time differs from registration')
        proof = command_reply(capture, owner, row['opcode'], row['start_wall_ns'], row['end_wall_ns'], b'', row['data'])
        item = {'caller': 'C syscall', 'local_admission_seq': row['seq'], **proof}
        admissions = [r for r in diagnostic['records'] if r.get('admission') and r['seq'] == row['seq']]
        if admissions:
            item['admission_copyout'] = admissions[0]
        proofs.append(item)
        previous = row['end_wall_ns']
    if version >= 4:
        legacy = [r for r in diagnostic['records'] if 'legacy_poll' in r]
        legacy_proofs = []
        for row in legacy:
            if not previous <= row['start_wall_ns'] < row['end_wall_ns'] < owner['observed_wall_ns']:
                raise CaptureError('legacy poll seed/fault interval differs from registration/time')
            proof = command_reply(capture, owner, 0x0406, row['start_wall_ns'], row['end_wall_ns'], b'', expected[0x0406])
            legacy_proofs.append({'caller':'C legacy poll fault', 'local_admission_seq':row['seq'],
                                  'legacy_poll_copy':row, **proof})
            previous = row['end_wall_ns']
        if (window('commands', legacy[0]['start_wall_ns'], previous) != [p['command'] for p in legacy_proofs]
                or window('complete', legacy[0]['start_wall_ns'], previous) != [p['reply'] for p in legacy_proofs]):
            raise CaptureError('legacy poll seed/fault/retry phase contains extra commands or replies')
        proofs.extend(legacy_proofs)
    if version >= 5:
        held, final = [r for r in diagnostic['records'] if 'cancel' in r]
        if not previous <= held['start_wall_ns'] < final['end_wall_ns'] < owner['observed_wall_ns']:
            raise CaptureError('cancellation phase differs from registration/time')
        early=window('commands',held['start_wall_ns'],held['end_wall_ns'])
        later=window('commands',held['end_wall_ns'],final['end_wall_ns'])
        replies=window('complete',held['end_wall_ns'],final['end_wall_ns'])
        if (len(early)!=1 or len(later)!=1 or len(replies)!=2
                or window('complete',held['start_wall_ns'],held['end_wall_ns'])
                or any(c['opcode']!=0x0406 or c['params'] or
                       not c['wall_ns'] <= c['completion']['wall_ns'] <= final['end_wall_ns'] for c in early+later)
                or any(r['opcode']!=0x0406 or r['status'] or r['value']!=expected[0x0406] for r in replies)
                or not early[0]['record'] < replies[0]['record'] < later[0]['record'] < replies[1]['record']
                or not early[0]['wall_ns'] <= replies[0]['wall_ns'] <= later[0]['wall_ns'] <= replies[1]['wall_ns']
                or window('commands',held['start_wall_ns'],final['end_wall_ns'])!=early+later
                or window('complete',held['start_wall_ns'],final['end_wall_ns'])!=replies):
            raise CaptureError('held slot, queued cancellation or late reply wire isolation failed')
        fresh=command_reply(capture,owner,0x0406,later[0]['wall_ns'],final['end_wall_ns'],b'',expected[0x0406])
        proofs.extend([{'caller':'C held active cancel','command':early[0],'reply':replies[0],
                        'cancellation':held},
                       {'caller':'C fresh after held cancel',**fresh,'cancellation':final},
                       {'caller':'C queued cancel','commands':0,'replies':0,'request_id':10}])
        if version == 6:
            proofs.append({'caller':'C queued deadline','commands':0,'replies':0,'request_id':11,
                           'evidence':held['deadline'],'retained_result':final['deadline']})
        previous=final['end_wall_ns']
    if version >= 3:
        eviction_rows = [r for r in diagnostic['records'] if 'eviction' in r]
        start = eviction_rows[0]['start_wall_ns']
        if version >= 5 and (window('commands', previous, start) or window('complete', previous, start)):
            raise CaptureError('held/expired queue sent traffic in the release-to-eviction gap')
        end = eviction_rows[-2]['end_wall_ns']
        if not previous <= start < end < owner['observed_wall_ns']:
            raise CaptureError('eviction phase differs from diagnostic registration/time')
        fill_proofs = []
        for row in eviction_rows[:-1]:
            proof = command_reply(capture, owner, 0x0406, row['start_wall_ns'], row['end_wall_ns'], b'', expected[0x0406])
            fill_proofs.append({'caller':'C eviction fill', 'request_id':row['request_id'],
                                'local_admission_seq':row['seq'], **proof})
        # The enclosing interval includes inter-query gaps, too. No extra
        # opcode or repeated OUT/reply may hide outside a single fill's window.
        if (window('commands', start, end) != [p['command'] for p in fill_proofs]
                or window('complete', start, end) != [p['reply'] for p in fill_proofs]):
            raise CaptureError('eviction fill phase contains extra or unordered commands/replies')
        rejection = eviction_rows[-1]
        if (not end <= rejection['start_wall_ns'] < rejection['end_wall_ns'] < owner['observed_wall_ns']
                or window('commands', rejection['start_wall_ns'], rejection['end_wall_ns'])
                or window('complete', rejection['start_wall_ns'], rejection['end_wall_ns'])):
            raise CaptureError('evicted-ID/retained-ID quiet observation sent a command or consumed a reply')
        proofs.extend(fill_proofs)
        proofs.append({'caller':'C eviction rejection', 'commands':0, 'replies':0, 'evidence':rejection})
        previous = rejection['end_wall_ns']
    cli = diagnostic['cli_queries']
    if len(cli) != 4:
        raise CaptureError('four actual diagnostic CLI queries required')
    for row, (name, opcode, _) in zip(cli, QUERIES):
        matches = re.findall(r'^NativeDiagnosticQuery: index=(\d+) generation=(\d+) opcode=0x([0-9a-f]+) admission_seq=(\d+) status=0x00 data=([0-9a-f]+)$', row['stdout'], re.M)
        if (row['exit'] != 0 or len(matches) != 1 or matches[0][:3] != (str(owner['index']), str(owner['generation']), f'{opcode:04x}')
                or int(matches[0][3]) <= 0 or matches[0][4] != expected[opcode]
                or row['args'][1:] != ['--adapter', str(owner['index']), '--generation', str(owner['generation']), 'query', name]
                or not previous <= row['start_wall_ns'] < row['end_wall_ns'] < owner['observed_wall_ns']):
            raise CaptureError('diagnostic CLI identity/data/time/command mismatch')
        proof = command_reply(capture, owner, opcode, row['start_wall_ns'], row['end_wall_ns'], b'', expected[opcode])
        proofs.append({'caller': 'slkconfig', 'local_admission_seq': int(matches[0][3]), **proof})
        previous = row['end_wall_ns']
    return {json_identity(owner): rows[0]['start_wall_ns']}, proofs


def _corroborate_control(run, capture, replacement_phase='replug', boundary_field='unplug_observed_wall_ns', metadata_before=None):
    # Verify supporting records rather than trusting the success label alone.
    from ws73_north_star import parse_result, parse_match, parse_scan_window, parse_scan_complete, parse_scan_observed, stable
    identity = run['application_identity']
    if (not identity['uids'][0] or len(identity['uids']) != 4 or len(set(identity['uids'])) != 1
            or any(int(identity[k], 16) for k in ['cap_eff','cap_prm','cap_amb'])):
        raise CaptureError('ordinary application identity required')
    before, after = run['daemon_before'], run['daemon_after']
    if before != after or before['pid'] <= 0 or before['start_ticks'] <= 0:
        raise CaptureError('same live slkd process not proved')
    if run['bus_before'] != run['bus_after'] or run['bus_before']['pid'] != before['pid']:
        raise CaptureError('same bus-authenticated daemon owner not proved')
    initial = run['initial']
    if len(initial) != 2 or not stable(initial[1], run['survivor_control']['identity']):
        raise CaptureError('survivor changed during removal')
    parse_result(run['survivor_control']['scan_request']['stdout'], initial[1], 3)
    stale = run['stale_selection']
    if not isinstance(stale['exit'], int) or not stale['exit'] or 'not a live registration' not in stale['stderr']:
        raise CaptureError('retired selection rejection missing')
    replacement = run['replacement']
    if (replacement['port'] != initial[0]['port'] or replacement['generation'] == initial[0]['generation']
            or replacement['path'] == initial[0]['path']):
        raise CaptureError('replacement generation not proved')
    if len(run['cleanup']) != 2 or any(c['status'] != 'STOP_CONFIRMED' for c in run['cleanup']):
        raise CaptureError('final stops not confirmed')
    for confirmation in run.get('stop_confirmations', []):
        owner = confirmation['identity']
        domain = confirmation['domain']
        if domain not in ['advertise', 'scan']:
            raise CaptureError('unknown OFF confirmation domain')
        op, opcode, params = (2, 0x0c05, b'\0'*5) if domain == 'advertise' else (4, 0x1002, b'\0'*2)
        source, query = [run['commands'][confirmation[k]] for k in ['source_command', 'query_command']]
        prefix = [run['slctl']['path'], '--adapter', owner['path']]
        result = parse_result(source['stdout'], owner, op)
        observed = parse_result(query['stdout'], owner, op)
        if (source['exit'] or query['exit'] or source['args'] != prefix+[domain, 'off']
                or query['args'] != prefix+['result', str(result['request'])]
                or observed['request'] != result['request']
                or source['end_wall_ns'] > query['start_wall_ns']):
            raise CaptureError('OFF confirmation differs from retained successful stop')
        if any(c['args'][:4] == prefix+[domain] and c['args'][4:5] in [['on'], ['off']]
               for c in run['commands'][confirmation['source_command']+1:confirmation['query_command']]):
            raise CaptureError('radio operation intervened before OFF confirmation')
        command_reply(capture, owner, opcode, source['start_wall_ns'], source['end_wall_ns'], params, '')
    rounds = run['rounds']
    if [(r['phase'], r['round']) for r in rounds] != [('initial', i) for i in range(1, 21)] + [(replacement_phase, 1), (replacement_phase, 2)]:
        raise CaptureError('20 consecutive alternating rounds plus separate replug proof required')
    if len({r['marker'] for r in rounds}) != 22:
        raise CaptureError('markers reused')
    proofs, used = [], set()
    for i, r in enumerate(rounds):
        tx, rx, match = r['tx'], r['rx'], r['match']
        if tx['port'] == rx['port'] or tx['address'] == rx['address']:
            raise CaptureError('distinct physical devices required')
        if i and rounds[i-1]['phase'] == r['phase'] and (tx != rounds[i-1]['rx'] or rx != rounds[i-1]['tx']):
            raise CaptureError('roles did not alternate')
        expected_pair = initial if r['phase'] == 'initial' else [replacement,initial[1]]
        if {json_identity(tx),json_identity(rx)} != {json_identity(d) for d in expected_pair}:
            raise CaptureError('round uses unrelated physical registrations')
        commands = [run['commands'][j] for j in r['command_indices']]
        radio = []
        if len(commands) != 4:
            raise CaptureError('complete control command references required')
        if any(a['end_monotonic_ns'] > b['start_monotonic_ns'] or a['end_wall_ns'] > b['start_wall_ns'] for a,b in zip(commands,commands[1:])):
            raise CaptureError('radio command windows overlap or are out of order')
        for c, op, owner, words in zip(commands, [1,3,2,4], [tx,rx,tx,rx],
                [['advertise','on'],['scan','on',r['marker'],tx['address']],['advertise','off'],['scan','off']]):
            if c['args'] != [run['slctl']['path'],'--adapter',owner['path'],*words] or c['exit'] != 0:
                raise CaptureError('control command evidence mismatch')
            parse_result(c['stdout'], owner, op)
            opcodes = {1:[0x0c02,0x0c03,0x0c05],3:[0x1001,0x1002],2:[0x0c05],4:[0x1002]}[op]
            recipe = []
            for opcode in opcodes:
                expected = {0x0c03: bytes([0,3,len(marker_data(r['marker']))])+marker_data(r['marker']),
                            0x0c05: bytes([int(op == 1),0,0,0,0]),
                            0x1002: bytes([int(op == 3),0])}.get(opcode)
                step = command_reply(capture, owner, opcode, c['start_wall_ns'], c['end_wall_ns'],
                                     expected, None if opcode == 0x0c02 else '')
                params = bytes.fromhex(step['command']['params'])
                if opcode == 0x0c02 and (len(params) != 49 or params[0] != 0
                        or params[12:18] != bytes.fromhex(owner['address'].replace(':',''))):
                    raise CaptureError('captured advertisement parameters use wrong handle/address')
                if opcode == 0x1001 and (len(params) != 8 or params[2] != 1):
                    raise CaptureError('captured scan parameters use unsupported frame')
                if recipe and recipe[-1]['reply']['wall_ns'] > step['command']['wall_ns']:
                    raise CaptureError('recipe sent next step before previous Complete')
                recipe.append(step)
            radio.extend(recipe)
        accepted = re.findall(r'^NativeAdvertisementAccepted: request=(\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+)$',commands[0]['stdout'],re.M)
        adv_result = parse_result(commands[0]['stdout'],tx,1)
        if radio[0]['reply']['value'] != struct.pack('b', adv_result['selected_power']).hex():
            raise CaptureError('selected power disagrees with raw parameter Complete')
        if (len(accepted) != 1 or int(accepted[0][0]) != adv_result['request']
                or accepted[0][1] != r['marker'] or accepted[0][2] != marker_data(r['marker']).hex()
                or match['marker'] != r['marker']):
            raise CaptureError('admission/marker/result correlation mismatch')
        if parse_match(commands[1]['stdout']) != match:
            raise CaptureError('fresh match disagrees with raw slctl output')
        scan_result = parse_result(commands[1]['stdout'], rx, 3)
        scan_boottime = parse_scan_window(commands[1]['stdout'], rx, scan_result['request'])
        if match['kernel_boottime_ns'] < scan_boottime:
            raise CaptureError('kernel RX predates this scan invocation')
        completed = parse_scan_complete(commands[1]['stdout'], rx, scan_result['request'])
        start_mono, end_mono = commands[1]['start_monotonic_ns'], commands[1]['end_monotonic_ns']
        command=commands[1]
        if not command['start_boottime_ns'] <= scan_boottime <= completed <= command['end_boottime_ns']:
            raise CaptureError('Scan Complete clock outside command observation window')
        observed=parse_scan_observed(commands[1]['stdout'],rx,scan_result['request'])
        if not completed<=match['kernel_boottime_ns']<=observed<=command['end_boottime_ns']:
            raise CaptureError('RX or observation outside correlated boottime interval')
        if match['elapsed_ms']!=(observed-completed)//1_000_000:
            raise CaptureError('elapsed time disagrees with correlated clocks')
        if match['kernel_boottime_ns'] < completed:
            raise CaptureError('kernel RX predates successful Scan Complete')
        if r['scan_window_wall_ns'] != [command['start_wall_ns'],command['end_wall_ns']]:
            raise CaptureError('capture interval disagrees with command timestamps')
        start, end = r['scan_window_wall_ns']
        if (end < start or end_mono < start_mono or match['elapsed_ms'] >= 10000
                or abs((end-start)-(end_mono-start_mono)) > 250_000_000):
            raise CaptureError('inconsistent command clocks or discovery timeout')
        completions=[c for c in capture['complete'] if (c['bus'],c['device'],c['opcode'],c['status']) ==
            (rx['bus'],rx['device'],0x1002,0) and start<=c['wall_ns']<=end]
        if len(completions)!=1 :
            raise CaptureError('one raw successful Scan Complete with post-completion deadline required')
        if (match['generation'] != rx['generation'] or match['address'] != tx['address']
                or match['lost'] or match['seq'] <= r['watermark'] or match['kernel_boottime_ns'] <= 0
                or match['data'] != marker_data(r['marker']).hex()):
            raise CaptureError('invalid fresh selected CLI observation')
        if any(f['bus'] == d['bus'] and f['device'] == d['device'] and start <= f['wall_ns'] <= end
               for f in capture['failures'] for d in [tx,rx]):
            raise CaptureError('failed target URB during accepted discovery')
        rows = [p for p in capture['reports'] if p['bus'] == rx['bus'] and p['device'] == rx['device']
                and completions[0]['wall_ns'] <= p['wall_ns'] <= end and p['wall_ns']-completions[0]['wall_ns'] < 10_000_000_000 and p['address'] == tx['address']
                and p['header'] == r['header'] and p['data'] == match['data'] and p['rssi'] == match['rssi']]
        if not rows:
            raise CaptureError(f"missing full receiver USB/HCC/DLI proof for {r['phase']} round {r['round']}")
        proof = rows[0]
        key = (proof['record'], proof['hcc_offset'])
        if key in used:
            raise CaptureError('raw report reused')
        used.add(key)
        proofs.append({'phase': r['phase'], 'round': r['round'], 'marker': r['marker'],
                       'receiver': rx, 'raw': proof, 'radio_commands': radio})
    if [n['phase'] for n in run['negatives']] != ['initial', replacement_phase]:
        raise CaptureError('both negative controls required')
    for n in run['negatives']:
        start, end = n['window_wall_ns']
        if end - start < 2_000_000_000 or end <= start:
            raise CaptureError('negative observation too short')
        rx = n['rx']
        scan_start, scan_end = n['scan_window_wall_ns']
        stop_start, stop_end = n['stop_window_wall_ns']
        if not scan_end <= start < end <= stop_start:
            raise CaptureError('negative interval not enclosed by confirmed scan/stop')
        negative = [command_reply(capture, rx, 0x1002, lower, upper, bytes([enable,0]), '')
                    for lower,upper,enable in [(scan_start,scan_end,1),(stop_start,stop_end,0)]]
        next(p for p in reversed(proofs) if p['phase'] == n['phase'])['negative_scan_commands'] = negative
        if any(p['bus'] == rx['bus'] and p['device'] == rx['device'] and start <= p['wall_ns'] <= end
               and p['address'] in n['transmitter_addresses'] for p in capture['reports']):
            raise CaptureError('test transmitter reported during TX-off negative control')
    # Capture must include the actual metadata queries, not only radio reports.
    identities = {json_identity(r[side]): r[side] for r in rounds for side in ['tx', 'rx']}
    metadata = {}
    for identity in identities.values():
        metadata[json_identity(identity)] = [command_reply(capture, identity, opcode,
            run[boundary_field] if identity == replacement else 0,
            (metadata_before or {}).get(json_identity(identity), identity['observed_wall_ns']), b'', value)
            for opcode,value in [(0x0404, identity['version']),
                                 (0x0402, struct.pack('<HBHB', *identity['buffers']).hex()),
                                 (0x0403, identity['features']),
                                 (0x0406, identity['address'].replace(':', '').lower())]]
    for proof, r in zip(proofs, rounds):
        proof['registration_queries'] = {side: metadata[json_identity(r[side])] for side in ['tx','rx']}
    survivor = run['survivor_control']['scan_request']
    if not run[boundary_field] <= survivor['start_wall_ns'] <= survivor['end_wall_ns'] <= replacement['observed_wall_ns']:
        raise CaptureError('survivor control not between unplug and replacement Ready')
    steps = [command_reply(capture, initial[1], opcode, survivor['start_wall_ns'], survivor['end_wall_ns'],
                           b'\x01\x00' if opcode == 0x1002 else None, '')
             for opcode in [0x1001,0x1002]]
    if steps[0]['reply']['wall_ns'] > steps[1]['command']['wall_ns']:
        raise CaptureError('survivor scan recipe sent before parameter Complete')
    next(p for p in reversed(proofs) if p['phase'] == 'initial')['survivor_scan_commands'] = steps
    return proofs


def json_identity(identity):
    return (identity['port'], identity['generation'])
