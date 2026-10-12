# SPDX-License-Identifier: GPL-2.0-only
"""Explicit signed external-module VM transport probe; never socket acceptance."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

FOLDER = Path('/evidence/acb-transport')
REQUEST = Path('/evidence/application/passthrough-control/acb-request.json')
MODULE = Path('/usr/share/sparklink/tests/ws73_acb_transport_probe.ko')


def stage_module(source, root, manifest):
    from ws73_north_star import file_record
    source = source.resolve(strict=True)
    provenance = source.with_suffix('.build.json')
    build = json.loads(provenance.read_text())
    fields = {name: subprocess.check_output(['modinfo', '-F', name, str(source)], text=True).strip()
              for name in ['name', 'vermagic', 'license', 'signer']}
    if (fields['name'] != 'ws73_acb_transport_probe' or fields['license'] != 'GPL'
            or not fields['signer'] or fields['vermagic'].split()[0] != manifest['native_vm']['release']
            or build['build_exit'] != 0 or build['module_sha256'] != hashlib.sha256(source.read_bytes()).hexdigest()
            or build['kernel_head'] != manifest['native_vm']['kernel_head']
            or build['source_sha256'] != hashlib.sha256(Path(__file__).with_name('lab').joinpath('ws73_acb_transport_probe.c').read_bytes()).hexdigest()):
        raise ValueError('exact signed matching external selftest module and source proof required')
    target = root / str(MODULE).lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(0o444)
    Path(str(target)+'.sha256').write_text(build['module_sha256']+'\n')
    manifest['inputs'].append(file_record(provenance))
    manifest['inputs'].append(file_record(Path(__file__).with_name('lab')/'ws73_acb_transport_probe.c'))
    manifest['acb_probe_module'] = dict(file=file_record(source), build=build, module_info=fields,
                                      explicit_external_test_taint=4096, ordinary_socket_acceptance=False)


def corroborate(run, capture, kernel_log):
    """Require each original random kernel probe frame at both actual USB ends."""
    records = run.get('acb_transport_probe')
    if records is None or len(records) != 2:
        raise ValueError('two actual connected transport-probe phases required')
    frames = re.findall(r'WS73_ACB_PROBE_FRAME: round=(\d+) source=(\d+) bytes=([0-9a-f]+)', kernel_log)
    passed = re.findall(r'WS73_ACB_PROBE_PASS: rounds=(\d+) ordinary_socket=0 negotiation=0', kernel_log)
    if passed != ['4', '4'] or len(frames) != 8:
        raise ValueError('two original four-round module successes and all random frames required')
    from ws73_capture import reassemble_acb
    sdus = reassemble_acb(capture)
    proofs, nonces = [], set()
    for phase, row in enumerate(records):
        supervisor = row['supervisor']
        if (row['phase'] != phase or row['status'] != 'REAL_ACB_TRANSPORT_MODULE_EVIDENCE_PENDING'
                or supervisor['status'] != row['status'] or supervisor['result']['exit']
                or supervisor['result'].get('invocations') != 1 or supervisor['result'].get('syscall') != 'finit_module'
                or supervisor['unload']['exit'] or supervisor['taint'] != 4096):
            raise ValueError('original finite successful selftest and exact external-module taint required')
        references(row['owners'])
        for entry in row['owners']:
            owner, obj = entry['owner'], entry['object']
            completed = [e for e in capture['native_events'] if e['event'] == 9
                         and (e['bus'], e['device']) == (owner['bus'], owner['device'])
                         and supervisor['start_wall_ns'] <= e['wall_ns'] <= supervisor['end_wall_ns']]
            if (any(len(bytes.fromhex(e['params'])) != 3
                    or int.from_bytes(bytes.fromhex(e['params'])[:2], 'little') != obj['handle'] for e in completed)
                    or sum(bytes.fromhex(e['params'])[2] for e in completed) != 4):
                raise ValueError('exact four real completed packets per controller and phase required')
        for index in range(4):
            sequence, side, raw = frames[phase*4+index]
            frame = bytes.fromhex(raw)
            if (int(sequence) != index or int(side) != index % 2 or len(frame) != 62
                    or frame[:2] != b'\x1f\x00' or int.from_bytes(frame[2:4], 'little') != 58
                    or frame[4:13] != b'\xfbSLKACB1!' or int.from_bytes(frame[29:33], 'little') != index
                    or frame[33] != int(side) or frame[13:29] in nonces):
                raise ValueError('fresh exact experimental basic DTAP random frame required')
            nonces.add(frame[13:29])
            a = row['owners'][int(side)]
            b = row['owners'][int(side)^1]
            reply = bytearray(frame); reply[33] |= 0x80
            legs = []
            for sender, receiver, payload in [(a, b, frame), (b, a, reply)]:
                def matching(owner, direction):
                    key = (owner['owner']['bus'], owner['owner']['device'])
                    return [p for p in sdus if (p['bus'], p['device']) == key
                            and p['direction'] == direction and p['handle'] == owner['object']['handle']
                            and p['data'] == payload.hex()
                            and supervisor['start_wall_ns'] <= p['wall_ns'] <= supervisor['end_wall_ns']]
                tx, rx = matching(sender, 'out'), matching(receiver, 'in')
                if len(tx) != 1 or len(rx) != 1:
                    raise ValueError('each exact payload requires one successful USB TX and actual opposite RX')
                count = [e for e in capture['native_events'] if e['event'] == 9
                         and (e['bus'], e['device']) == (tx[0]['bus'], tx[0]['device'])
                         and tx[0]['wall_ns'] <= e['wall_ns'] <= supervisor['end_wall_ns']
                         and len(bytes.fromhex(e['params'])) == 3
                         and int.from_bytes(bytes.fromhex(e['params'])[:2], 'little') == sender['object']['handle']
                         and bytes.fromhex(e['params'])[2] > 0]
                if not count:
                    raise ValueError('actual sending controller NOCP required; USB success is insufficient')
                legs.append(dict(tx=tx[0], rx=rx[0], real_completed_events=count))
            proofs.append(dict(phase=phase, round=index, source=int(side), nonce=frame[13:29].hex(), legs=legs))
    return dict(status='REAL_ACB_TRANSPORT_SELFTEST_USB_CORROBORATED', rounds=8, proofs=proofs,
                ordinary_socket_acceptance=False, channel_negotiation_acceptance=False,
                scope='signed external module plus exact two-endpoint USB/HCC/A3 and real NOCP; not ordinary application or socket qualification')


def finit_once(module, parameters):
    """Exactly one x86_64 guest finit_module; BusyBox fallback retried failed init."""
    if os.uname().machine != 'x86_64':
        raise ValueError('explicit x86_64 VM syscall profile required')
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    with module.open('rb') as stream:
        result = library.syscall(ctypes.c_long(313), ctypes.c_int(stream.fileno()),
                                 ctypes.c_char_p(parameters.encode()), ctypes.c_int(0))
    error = ctypes.get_errno() if result else 0
    return dict(exit=error, syscall='finit_module', invocations=1, stdout='',
                stderr=os.strerror(error) if error else '')


def execute(run, phase):
    row = dict(phase=len(run.data['connection_control']['phases'])-1,
               owners=phase['typed_objects'], status='RUNNING', start_wall_ns=time.time_ns(),
               ordinary_socket_acceptance=False, channel_negotiation_acceptance=False)
    run.data.setdefault('acb_transport_probe', []).append(row)
    run.save()
    temporary = REQUEST.with_suffix('.tmp')
    temporary.write_text(json.dumps(row))
    temporary.replace(REQUEST)
    response = FOLDER / f'phase-{row["phase"]}.json'
    deadline = time.monotonic() + 100
    while not response.exists():
        if time.monotonic() > deadline:
            raise TimeoutError('finite VM ACB transport supervisor deadline')
        time.sleep(.05)
    row['supervisor'] = json.loads(response.read_text())
    row['end_wall_ns'] = time.time_ns()
    row['status'] = row['supervisor']['status']
    run.save()
    if row['status'] != 'REAL_ACB_TRANSPORT_MODULE_EVIDENCE_PENDING':
        raise ValueError('real ACB probe failed: ' + str(row['supervisor'].get('error')))


def references(entries):
    if len(entries) != 2:
        raise ValueError('two original connected object observations required')
    result = []
    for entry in entries:
        owner, obj = entry['owner'], entry['object']
        values = [owner['index'], owner['generation'], obj['lifetime'], obj['handle']]
        if (any(type(x) is not int for x in values) or not 0 <= values[0] <= 65535
                or not 0 < values[1] < 1 << 64 or not 0 < values[2] < 1 << 64
                or not 0 <= values[3] <= 0xfff or obj['generation'] != values[1]):
            raise ValueError('exact nonzero generation/lifetime and supported handle required')
        result.append(values)
    if result[0][0] == result[1][0]:
        raise ValueError('two independent controllers required')
    return result


def observe(entries):
    import sys
    sys.path.insert(0, '/usr/share/sparklink/python')
    from sparklink.native import NativeAdapter
    refs = references(entries)
    records = []
    for entry, ref in zip(entries, refs):
        with NativeAdapter(ref[0], ref[1]) as adapter:
            state = adapter.snapshot()
            links = adapter.link_snapshot()
            management = adapter.management_status()
        if (state.flags != 1 or state.error or links.flags != 1 or links.count != 1
                or management.state != 1 or management.mode != 1 or management.error):
            raise ValueError('independent Ready/Held canonical connected observation required')
        link = links.links[0]
        if (link.lifetime != ref[2] or link.handle != ref[3]
                or link.role != entry['object']['role']
                or link.address_type != entry['object']['address_type']
                or bytes(link.address).hex() != entry['object']['address'].replace(':', '').lower()):
            raise ValueError('kernel table differs from original typed object')
        records.append(dict(controller=bytes(state).hex(), links=bytes(links).hex(),
                            management=bytes(management).hex()))
    return records


def supervise():
    if (os.geteuid() != 0 or 'ws73.acb_probe=1' not in Path('/proc/cmdline').read_text().split()
            or not Path('/scratch-root-uuid').is_file() or not MODULE.is_file()):
        raise ValueError('explicit private VM and frozen signed selftest module required')
    expected = Path(str(MODULE) + '.sha256').read_text().strip()
    if hashlib.sha256(MODULE.read_bytes()).hexdigest() != expected:
        raise ValueError('frozen ACB selftest module changed')
    FOLDER.mkdir(mode=0o755, exist_ok=False)
    for phase in [0, 1]:
        deadline = time.monotonic() + 180
        while True:
            request = json.loads(REQUEST.read_text()) if REQUEST.exists() else None
            if request is not None and request['phase'] == phase:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('finite actual connected ACB request')
            time.sleep(.05)
        row = dict(phase=phase, request=request, status='RUNNING', start_wall_ns=time.time_ns(),
                   ordinary_socket_acceptance=False, module_sha256=expected)
        loaded = False
        try:
            refs = references(request['owners'])
            row['before'] = observe(request['owners'])
            before = int(Path('/proc/sys/kernel/tainted').read_text())
            if before != (0 if phase == 0 else 4096):
                raise ValueError('no unrelated kernel taint allowed before external selftest')
            args = []
            for name, index in [('ids', 0), ('generations', 1), ('lifetimes', 2), ('handles', 3)]:
                args.append(name + '=' + ','.join(str(ref[index]) for ref in refs))
            args.append('rounds=4')
            row['command'] = ['finit_module', str(MODULE), *args]
            row['result'] = finit_once(MODULE, ' '.join(args))
            if row['result']['exit']:
                raise ValueError('real module transport probe returned failure')
            loaded = True
            row['after'] = observe(request['owners'])
            row['taint'] = int(Path('/proc/sys/kernel/tainted').read_text())
            if row['taint'] != 4096:
                raise ValueError('only the explicit external-test-module taint is allowed')
            row['status'] = 'REAL_ACB_TRANSPORT_MODULE_EVIDENCE_PENDING'
        except BaseException as error:
            row.update(status='FAIL', error=str(error), error_type=type(error).__name__)
        finally:
            if loaded:
                removed = subprocess.run(['/bin/rmmod', 'ws73_acb_transport_probe'], capture_output=True, text=True, timeout=10)
                row['unload'] = dict(exit=removed.returncode, stdout=removed.stdout, stderr=removed.stderr)
                if removed.returncode:
                    row.update(status='FAIL', error='selftest module unload failed')
            row['end_wall_ns'] = time.time_ns()
            temporary = FOLDER / f'phase-{phase}.tmp'
            temporary.write_text(json.dumps(row, indent=2) + '\n')
            temporary.replace(FOLDER / f'phase-{phase}.json')
        if row['status'] == 'FAIL':
            raise ValueError(row['error'])


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    supervise()
