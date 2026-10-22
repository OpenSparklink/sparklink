#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify actual RAM firmware upload bytes in a sealed USB capture.

A staged file, warm Ready or matching version is not evidence that these bytes
were loaded. No device operations, firmware rewriting or recovery qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from ws73_capture import CaptureError

IMAGES = [(0x400000, 'ws73.bin'), (0x430000, 'wifi_cali.bin'), (0x440000, 'btc_cali.bin')]


def successful_out(path):
    pending = {}; result = []
    with Path(path).open('rb') as stream:
        h = stream.read(24)
        if len(h) != 24 or h[:4] != b'\xd4\xc3\xb2\xa1' or struct.unpack_from('<I', h, 20)[0] != 220 or struct.unpack_from('<HH',h,4)!=(2,4):
            raise CaptureError('classic little-endian USB mmapped pcap required')
        snaplen = struct.unpack_from('<I', h, 16)[0]
        ordinal = 0
        while header := stream.read(16):
            if len(header) != 16: raise CaptureError('truncated record')
            psec, fraction, size, original = struct.unpack('<IIII', header)
            if not 0<=fraction<1000000 or not 64 <= size <= original or size > snaplen: raise CaptureError('bad captured size')
            p = stream.read(size); ordinal += 1
            if len(p) != size: raise CaptureError('truncated USB data')
            urb, kind, transfer, ep, device, bus, _, flag, sec, usec, status, length, cap = struct.unpack_from('<QBBBBHBBqiiII', p)
            if transfer != 3 or ep != 1 or kind not in b'SCE': continue
            if sec<0 or not 0<=usec<1000000 or abs((sec*1000000000+usec*1000)-(psec*1000000000+fraction*1000))>1000000:
                raise CaptureError('USB/pcap timestamps disagree')
            key = bus, device, urb
            if kind == ord('S'):
                if key in pending or flag or cap != length or size != original or size != 64+cap:
                    raise CaptureError('missing/duplicate/truncated OUT submission')
                pending[key] = dict(bus=bus,device=device,record=ordinal,raw=p[64:],wall_ns=sec*1000000000+usec*1000)
            else:
                if key not in pending: raise CaptureError('completion without submit')
                row = pending.pop(key)
                if status or kind == ord('E') or length != len(row['raw']) or cap or size != 64:
                    raise CaptureError('failed/short OUT cannot prove firmware uploaded')
                row['completion_record'] = ordinal;result.append(row)
    if pending: raise CaptureError('unfinished OUT')
    return sorted(result,key=lambda row:row['record'])


def corroborate(rows, directory):
    chunks=[];command=None
    for row in rows:
        raw=row['raw']
        if raw.startswith(b'FILES '):
            if command is not None: raise CaptureError('missing prior firmware chunk')
            fields=re.fullmatch(rb'FILES 1 0x([0-9a-f]+) 0x([0-9a-f]+) 0x([0-9a-f]+)',raw.strip(b'\0 \r\n'))
            if not fields: raise CaptureError('malformed FILES')
            command=(row,*[int(v,16) for v in fields.groups()])
        elif command is not None:
            cmd,address,length,state=command;command=None
            if (row['bus'],row['device'])!=(cmd['bus'],cmd['device']) or len(raw)!=length:
                raise CaptureError('firmware body differs from command length or device')
            chunks.append(dict(address=address,state=state,raw=raw,command_record=cmd['record'],
                               data_record=row['record'],completion_record=row['completion_record'],bus=row['bus'],device=row['device']))
    if command is not None or not chunks: raise CaptureError('no complete actual upload; warm/staged is not loaded')
    if len({(c['bus'],c['device']) for c in chunks})!=1: raise CaptureError('one boot-device upload per report required')
    result=[];cursor=0
    for base,name in IMAGES:
        image=(Path(directory)/name).read_bytes();expected=image[64:]
        if len(image)<=64 or hashlib.sha256(expected).hexdigest().encode()!=image[:64]:
            raise CaptureError('invalid source image SHA header')
        offset=0;selected=[]
        while offset<len(expected):
            if cursor>=len(chunks): raise CaptureError('missing image chunks')
            c=chunks[cursor];cursor+=1;length=len(c['raw'])
            state=3 if len(expected)<=32768 else 0 if not offset else 2 if offset+length==len(expected) else 1
            if c['address']!=base+offset or not 0<length<=32768 or c['state']!=state:
                raise CaptureError('noncontiguous/oversize/out-of-order firmware chunk')
            if c['raw']!=expected[offset:offset+length]: raise CaptureError('actual USB bytes differ from staged image')
            selected.append({k:v for k,v in c.items() if k!='raw'});offset+=length
        result.append(dict(image=name,load_address=base,bytes=offset,image_sha256=hashlib.sha256(image).hexdigest(),
                           payload_sha256=hashlib.sha256(expected).hexdigest(),chunks=selected))
    if cursor!=len(chunks): raise CaptureError('extra/ambiguous upload')
    return dict(status='ACTUAL_RAM_UPLOAD_BYTES_MATCH',images=result,
                scope='Successful USB boot-mode OUT bytes match supplied images; not firmware execution/air delivery/secure attestation/natural recovery')


MODES = ('rom-upload', 'runtime-observation')


def requested_mode(args):
    """A test qualification scope, never firmware selection or authorization."""
    mode = getattr(args, 'firmware_evidence', None)
    if mode not in MODES:
        raise ValueError('explicit --firmware-evidence rom-upload|runtime-observation required; staged files are not a loaded-image witness')
    if mode == 'rom-upload':
        allowed = {'qmp_hotplug', 'connection_verify', 'channel_socket_verify', 'channel_socket_boundaries', 'link_measurements'}
        if (not all(getattr(args, key, False) is True for key in ['qmp_hotplug', 'connection_verify', 'channel_socket_verify'])
                or any(type(value) is bool and value and key not in allowed for key, value in vars(args).items())):
            raise ValueError('rom-upload evidence requires a dedicated ordinary two-device connection/socket gate')
    return mode


def guest_instances(kernel_log):
    """USB-core path/instance observations, not device-number ordering.

    Refuse number reuse/ambiguous logs rather than attributing an old capture
    to a later device. No wall-clock/guest-clock differences are calculated.
    """
    if not isinstance(kernel_log, str) or len(kernel_log.encode()) > 16 * 1024 * 1024:
        raise CaptureError('bounded complete kernel USB log required')
    by_key, by_port = {}, {}
    pattern = r'^\[\s*(\d+\.\d+)\] usb (\d+-[\d.]+): new [^\n]{1,120} USB device number (\d+) using \S+'
    for match in re.finditer(pattern, kernel_log, re.M):
        stamp, port, device = match.groups()
        key = int(port.split('-', 1)[0]), int(device)
        if not 1 <= key[0] <= 255 or not 1 <= key[1] <= 127 or key in by_key:
            raise CaptureError('ambiguous/reused USB instance identity')
        entries = by_port.setdefault(port, [])
        # Decimal strings are compared numerically within this one kernel
        # clock; never compare them to pcap wall-clock timestamps.
        from decimal import Decimal
        now = Decimal(stamp)
        if entries and now <= entries[-1]['time']:
            raise CaptureError('USB instance order is not established')
        item = dict(key=key, port=port, time=now,
                    previous=entries[-1]['key'] if entries else None)
        by_key[key] = item
        entries.append(item)
        if len(by_key) > 128:
            raise CaptureError('USB instance observation budget exceeded')
    return by_key


def startup_rows(outgoing, incoming, kernel_log, ports, selection, observations, directory):
    """Compose existing upload/model oracles for every observed Runtime.

    The caller binds the log/pcap to one sealed VM and fixed guest-slot mapping.
    HCC is a firmware report; neither this mapping nor an upload attests what
    code executes. A later warm enumeration does not inherit an earlier upload.
    """
    from ws73_model_evidence import corroborate_rows as model_reply
    if (not ports or len(ports) > 4 or len(set(ports)) != len(ports)
            or selection.get('model') not in ('E', 'U')
            or selection.get('sdk') != '1.10.110'
            or set(selection.get('images', {})) != {name for _, name in IMAGES}):
        raise CaptureError('explicit homogeneous SDK110 inputs and distinct ports required')
    guest_to_host = {f'1-{slot + 1}': host for slot, host in enumerate(ports)}
    instances = guest_instances(kernel_log)
    rom_ports = set()
    for row in observations:
        if (row.get('port') in ports and row.get('declared_model') == selection['model']
                and len(row.get('interfaces', [])) == 1
                and row['interfaces'][0].get('endpoints') == 2):
            rom_ports.add(row['port'])
    boots = {}
    for key in {(r['bus'], r['device']) for r in outgoing if r['raw'].startswith(b'FILES ')}:
        instance = instances.get(key)
        if instance is None or instance['port'] not in guest_to_host:
            raise CaptureError('upload USB identity lacks selected guest topology')
        host = guest_to_host[instance['port']]
        if host not in rom_ports:
            raise CaptureError('no guarded two-endpoint ROM observation for upload port')
        rows = [r for r in outgoing if (r['bus'], r['device']) == key]
        selected_directory = directory[host] if isinstance(directory, dict) else directory
        proof = corroborate(rows, selected_directory)
        for image in proof['images']:
            expected = selection['images'][image['image']]
            if (image['image_sha256'] != expected['sha256']
                    or image['bytes'] + 64 != expected['bytes']):
                raise CaptureError('actual upload differs from explicit staged model inputs')
        end = max(c['completion_record'] for i in proof['images'] for c in i['chunks'])
        quits = [r for r in rows if r['raw'] == b'QUIT ' and r['record'] > end]
        if len(quits) != 1:
            raise CaptureError('one successful QUIT after exact image inputs required')
        boots[key] = dict(proof=proof, quit_completion=quits[0]['completion_record'])
    keys = {(r['bus'], r['device']) for r in outgoing
            if len(r['raw']) >= 70 and r['raw'][64:66] == b'\x19\x09'
            and r['raw'][68:70] == b'\x10\x00'}
    runtimes, consumed = [], set()
    for key in sorted(keys):
        instance = instances.get(key)
        if instance is None or instance['port'] not in guest_to_host:
            raise CaptureError('Runtime USB identity lacks selected guest topology')
        host = guest_to_host[instance['port']]
        same = lambda r: (r['bus'], r['device']) == key
        model = model_reply([r for r in outgoing if same(r)], [r for r in incoming if same(r)])
        if model['observation']['model'] != 'WS73' + selection['model']:
            raise CaptureError('actual HCC model differs from explicit image model')
        row = dict(host_port=host, guest_port=instance['port'], bus=key[0], device=key[1],
                   hcc=model['observation'], result='MISSING',
                   origin='RUNTIME_WITHOUT_THIS_ENUMERATION_UPLOAD')
        prior = instance['previous']
        if prior in boots:
            boot = boots[prior]
            if boot['quit_completion'] >= model['observation']['request_record']:
                raise CaptureError('upload/QUIT must precede this Runtime HCC request')
            row.update(result='PASS', origin='ACTUAL_ROM_INPUT_UPLOAD_OBSERVED',
                       rom_bus=prior[0], rom_device=prior[1], **boot)
            consumed.add(prior)
        runtimes.append(row)
    covered = {r['host_port'] for r in runtimes}
    unmatched = [dict(bus=k[0], device=k[1], guest_port=instances[k]['port']) for k in sorted(set(boots) - consumed)]
    result = 'PASS' if covered == set(ports) and runtimes and not unmatched and all(r['result'] == 'PASS' for r in runtimes) else 'MISSING'
    return dict(version=1, result=result, selected_ports=list(ports), staged=selection,
                runtimes=runtimes, ports_without_runtime=sorted(set(ports) - covered),
                unmatched_uploads=unmatched,
                cold_power_verified=False, executing_firmware_attested=False,
                scope='Exact successful ROM input uploads before each observed HCC/DLI Runtime only; no warm inheritance, cold-power or executing-firmware attestation')


def observe_run(share, prepared, ports, package, allocation):
    from ws73_boot_code_evidence import successful_in
    from ws73_capture import check_capture_stats, read_capture
    import ws73_firmware_profile as profile
    capture = Path(share) / 'ws73.pcap'
    log = Path(share) / 'kernel.log'
    packets = check_capture_stats((Path(share) / 'capture-stats.txt').read_text())
    plan = package['firmware_profiles']
    profile.verify(Path(prepared) / 'root', plan, [str(i+1) for i in range(len(ports))])
    directories = {host: Path(prepared) / 'root/lib/firmware' / plan['entries'][str(i+1)]['directory']
                   for i, host in enumerate(ports)}
    evidence = startup_rows(successful_out(capture), successful_in(capture), log.read_text(),
                            ports, package['explicit_firmware'], allocation['observations'],
                            directories)
    identities = [(r['bus'], r['device']) for r in evidence['runtimes']]
    if not identities or read_capture(capture, identities)['packet_count'] != packets:
        raise CaptureError('complete Runtime capture and matching zero-drop statistics required')
    evidence['capture_sha256'] = hashlib.sha256(capture.read_bytes()).hexdigest()
    evidence['kernel_log_sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
    return evidence


def exit_gate(record, expected_mode=None):
    """Absent fields are historical, not retroactive firmware qualification."""
    if expected_mode is not None and (expected_mode not in MODES or record.get('firmware_evidence_mode') != expected_mode):
        return False
    if ('firmware_evidence_mode' not in record and 'firmware_evidence_contract_version' not in record
            and expected_mode is None):
        return True
    if type(record.get('firmware_evidence_contract_version')) is not int or record['firmware_evidence_contract_version'] != 1:
        return False
    mode = record.get('firmware_evidence_mode')
    proof = record.get('firmware_evidence')
    if (mode not in MODES or not isinstance(proof, dict)
            or type(proof.get('version')) is not int or proof['version'] != 1):
        return False
    if (proof.get('result') not in ('PASS', 'MISSING', 'UNPROVED')
            or proof.get('cold_power_verified') is not False
            or proof.get('executing_firmware_attested') is not False):
        return False
    if proof['result'] != 'PASS':
        return mode == 'runtime-observation'
    allocation = record.get('physical_resource_allocation')
    if not isinstance(allocation, dict):
        return False
    ports = allocation.get('selected_ports')
    rows = proof.get('runtimes')
    if not (proof.get('result') == 'PASS' and isinstance(ports, list) and bool(ports)
            and all(isinstance(p, str) for p in ports) and len(set(ports)) == len(ports)
            and proof.get('selected_ports') == ports and proof.get('unmatched_uploads') == []
            and isinstance(rows, list) and bool(rows)
            and all(isinstance(r, dict) and isinstance(r.get('host_port'), str) for r in rows)
            and {r.get('host_port') for r in rows} == set(ports)
            and all(r.get('result') == 'PASS' and r.get('origin') == 'ACTUAL_ROM_INPUT_UPLOAD_OBSERVED'
                    and isinstance(r.get('proof'), dict)
                    and r['proof'].get('status') == 'ACTUAL_RAM_UPLOAD_BYTES_MATCH' for r in rows)):
        return False
    selection = allocation.get('firmware')
    if (proof.get('staged') != selection or not isinstance(selection, dict)
            or selection.get('model') not in ('E', 'U') or selection.get('sdk') != '1.10.110'
            or selection.get('variant') != ('e' if selection['model'] == 'E' else 'us')
            or not isinstance(selection.get('images'), dict)):
        return False
    seen = set()
    for row in rows:
        key = row.get('bus'), row.get('device')
        if any(type(v) is not int or v <= 0 for v in key) or key in seen:
            return False
        seen.add(key)
        if row.get('guest_port') != f'1-{ports.index(row["host_port"]) + 1}':
            return False
        hcc = row.get('hcc')
        if (not isinstance(hcc, dict) or hcc.get('model') != 'WS73' + selection['model']
                or hcc.get('bus') != 'USB' or hcc.get('bus_id') != 0
                or (hcc.get('bus_number'), hcc.get('device')) != key):
            return False
        order = [row.get('quit_completion')] + [hcc.get(k) for k in
                 ['request_record', 'request_completion', 'response_submit', 'response_record', 'first_dli_record']]
        if any(type(v) is not int or v <= 0 for v in order) or any(a >= b for a, b in zip(order, order[1:])):
            return False
        images = row['proof'].get('images')
        if not isinstance(images, list) or len(images) != 3:
            return False
        for image, (address, name) in zip(images, IMAGES):
            if (not isinstance(image, dict) or image.get('image') != name
                    or image.get('load_address') != address
                    or image.get('image_sha256') != selection.get('images', {}).get(name, {}).get('sha256')
                    or type(image.get('bytes')) is not int
                    or image['bytes'] + 64 != selection.get('images', {}).get(name, {}).get('bytes')):
                return False
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--firmware-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('output exists; preserve sealed evidence')
    result=corroborate(successful_out(a.capture),a.firmware_dir)
    result['capture_sha256']=hashlib.sha256(a.capture.read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])


if __name__=='__main__':main()
