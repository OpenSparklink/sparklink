#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Passive, VM-only Session service trace. No packets, credit or Ready generated.

Software admission, atomic USB acceptance, joined return and retirement remain
separate. Full application/USB correctness must pass the existing oracle first.
"""
import argparse
from bisect import bisect_right
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import statistics
import subprocess
import time
from ws73_trace_layout import buffer_kib

EVENTS = {
    'sparklink_session_work': 'ctl gen life epoch service stage attempts bytes stop elapsed_ns planned_delay error'.split(),
    'sparklink_session_queue': 'ctl gen life epoch sequence slot bytes deadline stage'.split(),
    'sparklink_session_tx': 'ctl gen life service sequence slot pb len offset result wait stage'.split(),
}
ROOT = Path('/sys/kernel/tracing')
INSTANCE = ROOT / 'instances/slk_session_service'
FOLDER = Path('/evidence/session-service')
LIMIT = 8 * 1024 * 1024
STATUS = 'OBSERVED_NOT_PERFORMANCE_QUALIFIED'
BUFFER_KIB = 2048 # Measured 1MiB per-CPU overrun retained; bounded diagnostic only.
FULL_LOAD_PROFILE = dict(name='full-load-v2', requested_buffer_kb=8192,
                         text_limit_bytes=32*1024*1024, event_limit=100000, cpu_count=2)
PROFILE_TOKEN = 'ws73.session_service_profile='


def collector_limits(row):
    version=row.get('collector_contract_version');profile=row.get('collector_profile')
    if version is None and profile is None:
        return dict(name='legacy-v1', requested_buffer_kb=BUFFER_KIB,
                    text_limit_bytes=LIMIT, event_limit=None, cpu_count=2)
    if type(version)is not int or version!=2 or profile!=FULL_LOAD_PROFILE:
        raise ValueError('exact explicit bounded Session collector profile required')
    return dict(FULL_LOAD_PROFILE)


def collector_boot(tokens):
    values=[v for v in tokens if v.startswith(PROFILE_TOKEN)]
    if not values:return None
    if values!=[PROFILE_TOKEN+FULL_LOAD_PROFILE['name']]:
        raise ValueError('one supported explicit Session collector boot profile required')
    return dict(FULL_LOAD_PROFILE)


def trace_bytes(path,row):
    """One bounded acquisition, before decoding or hashing untrusted trace text."""
    limit=collector_limits(row)['text_limit_bytes']
    with Path(path).open('rb')as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Session trace text byte budget exceeded')
    return raw


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(row):
    temp = FOLDER / 'run.tmp'
    temp.write_text(json.dumps(row, indent=2) + '\n')
    temp.replace(FOLDER / 'run.json')


def vm_guard():
    if (os.geteuid() != 0 or not Path('/scratch-root-uuid').is_file()
            or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'QEMU'
            or 'ws73.session_service=1' not in Path('/proc/cmdline').read_text().split()):
        raise ValueError('explicit isolated scratch VM only;never configure tracing on host')


def write(name, value):
    (INSTANCE / name).write_text(value + '\n')


def cleanup(row):
    """Only this invocation's freshly created instance;never another tracer."""
    errors = []
    if row['created'] and INSTANCE.exists():
        for path in [INSTANCE/'tracing_on', *[INSTANCE/'events/sparklink'/n/'enable' for n in EVENTS]]:
            if path.exists():
                try:
                    path.write_text('0\n')
                except OSError as error:
                    errors.append(str(error))
        try:
            INSTANCE.rmdir()
        except OSError as error:
            errors.append(str(error))
    row['cleanup_errors'] = errors


def marker(row, kind):
    before = time.monotonic_ns()
    wall = time.time_ns()
    after = time.monotonic_ns()
    mark_before = time.monotonic_ns()
    write('trace_marker', 'SLK_SERVICE_' + kind.upper() + ':' + row['cookie'])
    row['anchors'].append(dict(kind=kind, mono_before=before, wall_ns=wall,
                               mono_after=after, mark_before=mark_before,
                               mark_after=time.monotonic_ns()))


def configure():
    vm_guard()
    profile=collector_boot(Path('/proc/cmdline').read_text().split())
    FOLDER.mkdir(mode=0o700)
    row = dict(status='RUNNING_NOT_QUALIFIED', cookie=secrets.token_hex(16),
               boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               kernel_release=os.uname().release, kernel_version=os.uname().version,
               clock='mono', requested_buffer_kb=BUFFER_KIB, anchors=[], created=False,
               queue_retirement_contract_version=2)
    if profile is not None:
        row.update(collector_contract_version=2,collector_profile=profile,
                   requested_buffer_kb=profile['requested_buffer_kb'])
    save(row)
    try:
        if not (ROOT / 'available_tracers').is_file():
            subprocess.run(['/bin/mount', '-t', 'tracefs', 'tracefs', str(ROOT)], check=True)
        INSTANCE.mkdir()
        row['created'] = True
        write('tracing_on', '0')
        write('current_tracer', 'nop')
        write('trace_clock', 'mono')
        write('buffer_size_kb', str(row['requested_buffer_kb']))
        write('trace', '')
        row['formats'] = {}
        for name in EVENTS:
            event = INSTANCE / 'events/sparklink' / name
            fmt = (event / 'format').read_text()
            if not fmt.startswith('name: ' + name + '\n'):
                raise ValueError('actual named production event format required')
            (FOLDER / (name + '.format')).write_text(fmt)
            row['formats'][name] = digest(FOLDER / (name + '.format'))
            (event / 'enable').write_text('1\n')
        row['readbacks'] = {name: (INSTANCE / name).read_text().strip()
                            for name in ['current_tracer', 'trace_clock', 'buffer_size_kb', 'buffer_subbuf_size_kb']}
        page = (INSTANCE / 'events/header_page').read_text()
        (FOLDER / 'header_page.txt').write_text(page)
        row['header_page'] = page
        row['enabled'] = {name: (INSTANCE / 'events/sparklink' / name / 'enable').read_text().strip()
                          for name in EVENTS}
        if (row['readbacks']['current_tracer'] != 'nop' or '[mono]' not in row['readbacks']['trace_clock']
                or set(row['enabled'].values()) != {'1'}):
            raise ValueError('trace setup readback mismatch')
        write('tracing_on', '1')
        marker(row, 'begin')
        save(row)
    except BaseException as error:
        row.update(status='FAIL', error=str(error))
        cleanup(row)
        save(row)
        raise


def finish(aborted=False):
    vm_guard()
    row = json.loads((FOLDER / 'run.json').read_text())
    if row['status'] != 'RUNNING_NOT_QUALIFIED' or row['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise ValueError('same live capture,not another boot or previously sealed trace')
    try:
        marker(row, 'end')
        write('tracing_on', '0')
        row['stats'] = {}
        for p in sorted((INSTANCE / 'per_cpu').glob('cpu*/stats')):
            raw = p.read_text()
            (FOLDER / (p.parent.name + '-stats.txt')).write_text(raw)
            row['stats'][p.parent.name] = raw
        try:raw=trace_bytes(INSTANCE/'trace',row)
        except ValueError:
            row['trace_budget_exceeded']=True
            raise
        text=raw.decode('utf-8')
        (FOLDER/'trace.txt').write_bytes(raw)
        row['trace_sha256']=hashlib.sha256(raw).hexdigest()
        for name in EVENTS:
            (INSTANCE / 'events/sparklink' / name / 'enable').write_text('0\n')
        row['disabled'] = {name: (INSTANCE / 'events/sparklink' / name / 'enable').read_text().strip()
                           for name in EVENTS}
        if set(row['disabled'].values()) != {'0'}:
            raise ValueError('trace events not disabled')
        INSTANCE.rmdir()
        row.update(instance_removed=True, status='ABORTED_NOT_QUALIFIED' if aborted else STATUS)
        if not aborted:
            parsed = parse(text, row)
            row['observed'] = summary(parsed)
        save(row)
    except BaseException as error:
        row.update(status='FAIL', error=str(error))
        cleanup(row)
        save(row)
        raise


def timestamp(seconds, fraction):
    if len(fraction) not in (6, 9):
        raise ValueError('explicit microsecond/nanosecond trace resolution required')
    return int(seconds) * 10**9 + int(fraction) * 10**(9-len(fraction))


def parse(text, row):
    """Successful observation entry; aborted traces remain ineligible."""
    return _parse(text, row, STATUS)


def parse_aborted(text, row):
    """Same structural checks, solely for an explicitly aborted diagnostic.

    This does not manufacture a completed application/transport observation.
    The separate failed-run consumer must still associate every original trace
    and USB submission. Unobserved retirement stays unknown; the qualified
    join still rejects it. No rows are clipped out to make a successful gate.
    """
    return _parse(text, row, 'ABORTED_NOT_QUALIFIED')


def _parse(text, row, expected_status):
    limits=collector_limits(row)
    version = row.get('queue_retirement_contract_version', 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError('explicit supported queue retirement observation contract required')
    if (len(text.encode('utf-8')) > limits['text_limit_bytes']
            or type(row.get('trace_budget_exceeded',False))is not bool or row.get('trace_budget_exceeded',False)
            or row['status'] != expected_status or row['clock'] != 'mono'
            or not re.fullmatch('[0-9a-f]{32}', row['cookie'])
            or re.findall(r'^# tracer: (.*)$', text, re.M) != ['nop']
            or 'LOST' in text.upper() or row['instance_removed'] is not True):
        raise ValueError('complete bounded same-clock trace required')
    read = row['readbacks']
    if read['current_tracer'] != 'nop' or '[mono]' not in read['trace_clock']:
        raise ValueError('original trace configuration required')
    expected_kib, _ = buffer_kib(row['header_page'], row['requested_buffer_kb'],
                               int(read['buffer_subbuf_size_kb']))
    if (type(row['requested_buffer_kb']) is not int or row['requested_buffer_kb'] != limits['requested_buffer_kb']
            or str(expected_kib) != read['buffer_size_kb']):
        raise ValueError('bounded configured trace buffer required')
    if row['enabled'] != dict.fromkeys(EVENTS, '1') or row['disabled'] != dict.fromkeys(EVENTS, '0'):
        raise ValueError('explicit event enable/disable required')
    if set(row['stats']) != {'cpu0', 'cpu1'}:
        raise ValueError('both configured VM CPUs required')
    entries = 0
    for raw in row['stats'].values():
        pairs = re.findall(r'^([^:\n]+):\s*(\d+)\s*$', raw, re.M)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError('duplicate per-CPU statistics')
        if any(fields.get(k) != '0' for k in ['overrun', 'commit overrun', 'dropped events']):
            raise ValueError('missing/nonzero trace loss counters')
        if 'entries' not in fields:
            raise ValueError('original per-CPU entry counts required')
        entries += int(fields['entries'])
    if limits['event_limit']is not None and entries>limits['event_limit']+2:
        raise ValueError('bounded Session event budget exceeded')
    header = re.findall(r'#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)', text)
    if len(header) != 1 or header[0][0] != header[0][1] or int(header[0][0]) != entries:
        raise ValueError('complete trace entry accounting required')
    rows, markers = [], []
    quantum = 1
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        m = re.search(r'(\d+)\.(\d+):\s*(\w+):\s*(.*)$', line)
        if not m:
            raise ValueError('unparsed trace row')
        t = timestamp(m[1], m[2])
        quantum = max(quantum, 10**(9-len(m[2])))
        if m[3] == 'tracing_mark_write':
            markers.append((m[4], t))
            continue
        if m[3] not in EVENTS:
            raise ValueError('unexpected event')
        fields = m[4].split()
        pairs = [v.split('=') for v in fields]
        if (any(len(p) != 2 or not re.fullmatch('-?(?:0|[1-9][0-9]*)', p[1]) for p in pairs)
                or [p[0] for p in pairs] != EVENTS[m[3]]):
            raise ValueError('exact typed trace schema required')
        v = {k: int(value) for k, value in pairs}
        if (not 0 <= v['ctl'] <= 65535 or not 0 < v['gen'] < 2**64
                or not 0 < v['life'] < 2**64
                or v['stage'] not in (0, 1, 2, 3)
                or v['stage'] == 3 and (version != 2 or m[3] != 'sparklink_session_queue')):
            raise ValueError('invalid trace identity/stage')
        if any(value < 0 or value >= 2**64 for k, value in v.items()
               if k not in ('slot', 'result', 'error')):
            raise ValueError('invalid unsigned trace field')
        v.update(event=m[3].removeprefix('sparklink_session_'), mono_ns=t)
        rows.append(v)
        if limits['event_limit']is not None and len(rows)>limits['event_limit']:
            raise ValueError('bounded Session event budget exceeded')
    expected = [('SLK_SERVICE_BEGIN:' + row['cookie']), ('SLK_SERVICE_END:' + row['cookie'])]
    if ([v[0] for v in markers] != expected or len(rows) < 2
            or int(header[0][0]) != len(rows) + 2 or markers[0][1] >= markers[1][1]):
        raise ValueError('nonempty original interval and exact marker closure required')
    anchors = row['anchors']
    if len(anchors) != 2 or [v['kind'] for v in anchors] != ['begin', 'end']:
        raise ValueError('both clock anchors required')
    for (_, t), a in zip(markers, anchors):
        if (any(type(a[k]) is not int for k in ['mono_before', 'mono_after', 'wall_ns', 'mark_before', 'mark_after'])
                or not 0 <= a['mono_before'] <= a['mono_after'] <= a['mark_before'] <= a['mark_after']
                or not a['mark_before']-quantum <= t <= a['mark_after']+quantum):
            raise ValueError('clock/marker bracket mismatch')
    if any(not markers[0][1]-quantum <= v['mono_ns'] <= markers[1][1]+quantum for v in rows):
        raise ValueError('event outside sealed interval')
    low = max(a['wall_ns']-a['mono_after'] for a in anchors)
    high = min(a['wall_ns']-a['mono_before'] for a in anchors)
    if low > high:
        raise ValueError('no common realtime/monotonic offset;cannot join USB clocks')
    result=dict(rows=rows, quantum_ns=quantum, offset_ns=[low, high],
                interval_ns=[markers[0][1], markers[1][1]])
    if row.get('collector_contract_version')==2:result['collector_profile']=dict(limits)
    return result


def summary(parsed):
    result=dict(events=len(parsed['rows']), quantum_ns=parsed['quantum_ns'],
                offset_ns=parsed['offset_ns'], interval_ns=parsed['interval_ns'])
    if 'collector_profile'in parsed:result.update(collector_contract_version=2,collector_profile=parsed['collector_profile'])
    return result


def identities(record):
    owners = {}
    if 'channel_socket' in record or 'socket_benchmark' in record:
        for phase in record.get('channel_socket',record.get('socket_benchmark',[])):
            for item in phase['owners']:
                o, obj = item['owner'], item['object']
                key = (o['index'], o['generation'], obj['lifetime'])
                value = dict(bus=o['bus'], device=o['device'], handle=obj['handle'], epoch=None)
                if key in owners and owners[key] != value:
                    raise ValueError('conflicting connection identity')
                owners[key] = value
    elif 'channel_grant' in record:
        for o, usb in zip(record['channel_grant']['owners'], record['usb']):
            owners[o['index'], o['generation'], o['lifetime']] = dict(
                bus=usb['bus'], device=usb['device'], handle=o['handle'], epoch=o['lease'])
    if not owners:
        raise ValueError('actual ordinary channel owner receipts required')
    return owners


def _associate(parsed, owners, capture):
    """Validate all observed rows/USB; expose unclosed software observations.

    The qualified join below still rejects every unclosed operation. The
    failed-run diagnostic retains them, with unknown retirement, rather than
    deleting their rows or inferring that a purge/drain was observed.
    """
    works, queues, attempts = {}, {}, {}
    q = parsed['quantum_ns']
    for key, owner in owners.items():
        if (len(key) != 3 or any(type(v) is not int for v in key)
                or any(type(owner[k]) is not int for k in ['bus', 'device', 'handle'])
                or owner['epoch'] is not None and type(owner['epoch']) is not int):
            raise ValueError('typed original physical owner identity required')
    for v in parsed['rows']:
        ident = (v['ctl'], v['gen'], v['life'])
        if ident not in owners:
            raise ValueError('unowned generation/lifetime in trace')
        if 'epoch' in v and (not v['epoch'] or owners[ident]['epoch'] not in (None, v['epoch'])):
            raise ValueError('wrong immutable Managed epoch')
        if v['event'] == 'work':
            if v['stage'] not in (0, 1) or not v['service']:
                raise ValueError('invalid service stage')
            group, key = works, (*ident, v['service'])
        elif v['event'] == 'queue':
            if not 0 <= v['slot'] < 6 or not 0 < v['bytes'] <= 2047:
                raise ValueError('invalid admitted PDU')
            group, key = queues, (*ident, v['sequence'], v['slot'])
        else:
            if (not -1 <= v['slot'] < 6 or v['pb'] not in range(4)
                    or not 0 < v['len'] <= 2047 or not 0 <= v['offset'] < 2047
                    or not -4095 <= v['result'] <= 0 or v['wait'] not in (0, 1, 2)):
                raise ValueError('invalid submit metadata')
            group, key = attempts, (*ident, v['service'], v['slot'], v['sequence'], v['offset'])
        stages = group.setdefault(key, {})
        if v['event'] == 'queue' and v['stage'] == 1:
            # Production may requeue an unstarted PDU after EAGAIN. Keep each
            # dequeue and prove that its preceding try accepted no USB packet.
            stages.setdefault(1, []).append(v)
            continue
        if v['stage'] in stages:
            raise ValueError('duplicate/ambiguous trace stage or sequence wrap')
        stages[v['stage']] = v
    if not works or not queues or not attempts:
        raise ValueError('actual work,admission and Native submit observations required')
    epochs = {}
    for key, stages in works.items():
        if set(stages) != {0, 1}:
            raise ValueError('worker crossed capture boundary or missing end')
        a, b = stages[0], stages[1]
        if (a['mono_ns'] > b['mono_ns']+q or a['epoch'] != b['epoch']
                or a['attempts'] or a['bytes'] or a['stop'] or a['elapsed_ns'] or a['error']
                or b['attempts'] > 8 or b['bytes'] > 4096 or b['stop'] not in range(4)
                or not -4095 <= b['error'] <= 0):
            raise ValueError('invalid bounded service accounting')
        if b['stop'] == 1 and b['attempts'] != 8 or b['stop'] == 3 and b['elapsed_ns'] < 2_000_000:
            raise ValueError('service stop reason contradicts actual budget')
        if key[:3] in epochs and epochs[key[:3]] != a['epoch']:
            raise ValueError('Session epoch changed')
        epochs[key[:3]] = a['epoch']
    accepted, data_steps = defaultdict(list), defaultdict(list)
    for key, stages in attempts.items():
        if not {0, 1} <= set(stages) or not set(stages) <= {0, 1, 2}:
            raise ValueError('incomplete Native attempt')
        a, b = stages[0], stages[1]
        common = ['ctl','gen','life','service','slot','sequence','offset','pb','len']
        if any(a[k] != b[k] for k in common) or a['result'] != -115 or a['wait'] != 0:
            raise ValueError('Native begin/result identity mismatch')
        wk = (*key[:3], a['service'])
        if wk not in works:
            raise ValueError('attempt without originating service')
        w0, w1 = works[wk][0], works[wk][1]
        if not w0['mono_ns']-q <= a['mono_ns'] <= b['mono_ns']+q <= w1['mono_ns']+2*q:
            raise ValueError('attempt outside service')
        commit = stages.get(2)
        if b['result'] == 0 and (commit is None or commit['result'] != 0):
            raise ValueError('joined success lacks actual atomic acceptance')
        if commit:
            if (any(a[k] != commit[k] for k in common)
                    or not a['mono_ns']-q <= commit['mono_ns'] <= b['mono_ns']+q
                    or commit['wait'] != 0):
                raise ValueError('actual atomic consent identity/order mismatch')
            if commit['result'] == 0:
                accepted[key[:3]].append((a, commit, b))
        if a['slot'] >= 0:
            data_steps[wk].append(a)
            kq = (*key[:3], a['sequence'], a['slot'])
            if kq not in queues:
                raise ValueError('data attempt without admission/dequeue')
        elif a['offset'] or a['pb']:
            raise ValueError('unfragmented control namespace required')
    for key, stages in works.items():
        steps = data_steps[key]
        if stages[1]['attempts'] != len(steps) or stages[1]['bytes'] != sum(v['len'] for v in steps):
            raise ValueError('service attempted packet/byte accounting mismatch')
    complete = partial = discarded = 0
    unclosed = []
    for key, stages in queues.items():
        if set(stages) not in ({0}, {0, 1}, {0, 1, 2}, {0, 3}, {0, 1, 3}):
            raise ValueError('unaccounted software admission/dequeue/operation retirement')
        a, dequeues, c = stages[0], stages.get(1, []), stages.get(2, stages.get(3))
        b = dequeues[0] if dequeues else None
        snapshots = [a, *dequeues, *([c] if c else [])]
        if (any(len({v[field] for v in snapshots}) != 1 for field in ['epoch','bytes','deadline'])
                or a['epoch'] != epochs.get(key[:3])
                or b and a['mono_ns'] > b['mono_ns']+q
                or c and a['mono_ns'] > c['mono_ns']+q
                or c and b and b['mono_ns'] > c['mono_ns']+q):
            raise ValueError('operation identity/original deadline changed')
        op_attempts = [steps for kt, steps in attempts.items()
                       if kt[:3] == key[:3] and kt[4:6] == (key[4], key[3])]
        op_attempts.sort(key=lambda steps: steps[0]['mono_ns'])
        for previous, current in zip(dequeues, dequeues[1:]):
            tries = [steps for steps in op_attempts
                     if previous['mono_ns']-q <= steps[0]['mono_ns'] < current['mono_ns']-q]
            if (current['mono_ns'] <= previous['mono_ns'] or len(tries) != 1
                    or tries[0][0]['offset'] != 0 or tries[0][1]['result'] != -11
                    or 2 in tries[0] and tries[0][2]['result'] == 0
                    or tries[0][1]['mono_ns'] > current['mono_ns']+q):
                raise ValueError('repeated dequeue without definite unstarted EAGAIN')
        end = c['mono_ns'] if c else parsed['interval_ns'][1]
        if op_attempts and (b is None or any(not b['mono_ns']-q <= steps[0]['mono_ns'] <= end+q for steps in op_attempts)):
            raise ValueError('attempt outside dequeued operation lifetime')
        if 3 in stages:
            if (len(op_attempts) != len(dequeues)
                    or any(v[0]['offset'] != 0 or v[1]['result'] != -11
                           or 2 in v and v[2]['result'] == 0 for v in op_attempts)):
                raise ValueError('queued discard must have no accepted prefix and only definite unstarted EAGAIN')
            discarded += 1
        successful = [steps[1] for kt, steps in attempts.items()
                      if kt[:3] == key[:3] and kt[4:6] == (key[4], key[3]) and steps[1]['result'] == 0]
        successful.sort(key=lambda v:v['offset'])
        offset = 0
        for v in successful:
            expected_pb = (1 if v['len'] < a['bytes'] else 0) if offset == 0 else (3 if offset+v['len'] == a['bytes'] else 2)
            if (v['offset'] != offset or v['pb'] != expected_pb or offset+v['len'] > a['bytes']
                    or b is None or not b['mono_ns']-q <= v['mono_ns'] <= end+q):
                raise ValueError('PB/offset/retirement continuity mismatch')
            offset += v['len']
        complete += offset == a['bytes']
        partial += offset != a['bytes']
        if c is None:
            unclosed.append(dict(controller=key[0], generation=key[1], lifetime=key[2],
                                 slot=key[4], admission_sequence=key[3],
                                 observed_stages=sorted(stages), dtap_bytes=a['bytes'],
                                 accepted_prefix_bytes=offset,
                                 reason='Retirement not observed; capture boundary or untraced purge, not proof of live allocation or drain.'))
    # Every accepted packet, including fixed CMTC, must have the corresponding
    # real USB submit, in the serialized physical order and within clock bounds.
    usb_total = 0
    dynamic_control = False
    for ident, owner in owners.items():
        calls = sorted(accepted[ident], key=lambda item:item[0]['mono_ns'])
        if not calls:
            raise ValueError('no actual acceptance for an original endpoint')
        active, offset = None, 0
        for a, _, _ in calls:
            operation = (a['slot'], a['sequence'])
            if active is not None:
                if operation != active or a['offset'] != offset or a['pb'] not in (2, 3):
                    raise ValueError('interleaved or discontinuous physical PB stream')
                offset += a['len']
                if a['pb'] == 3:
                    active = None
            elif a['pb'] not in (0, 1) or a['offset']:
                raise ValueError('physical PB continuation without start')
            elif a['pb'] == 1:
                active, offset = operation, a['len']
        all_intervals = []
        for other, oo in owners.items():
            if oo['bus'] == owner['bus'] and oo['device'] == owner['device'] and oo['handle'] == owner['handle']:
                all_intervals.extend((other, *v) for v in accepted[other])
        all_intervals.sort(key=lambda item:item[1]['mono_ns'])
        if len({v[1]['mono_ns'] for v in all_intervals}) != len(all_intervals):
            raise ValueError('ambiguous timestamp resolution for serialized submits')
        if ident != all_intervals[0][0]:
            continue  # Same physical handle across the two recorded lifetimes.
        packets = [v for v in capture['acb_packets'] if v['direction']=='out'
                   and (v['bus'],v['device'],v['handle'])==(owner['bus'],owner['device'],owner['handle'])]
        if len(packets) != len(all_intervals):
            raise ValueError('trace/USB accepted packet counts disagree')
        low, high = parsed['offset_ns']
        for packet, (_, a, commit, b) in zip(packets, all_intervals):
            wire = bytes.fromhex(packet['data'])
            if (packet['boundary'] != a['pb'] or len(wire) != a['len']
                    or not a['mono_ns']+low-2*q <= packet['wall_ns'] <= commit['mono_ns']+high+2*q):
                raise ValueError('actual USB submit/Native interval mismatch')
            # Scope annotation only, after exact count/order/consent matching.
            # CMTC protocol correctness remains the existing application gate.
            if packet['boundary'] == 0 and len(wire) >= 5 and wire[:2] == b'\x02\0' and wire[4] in (16, 17):
                dynamic_control = True
            usb_total += 1
    proof = dict(status='REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED',
                **summary(parsed), services=len(works), attempts=len(attempts),
                accepted_usb_packets=usb_total, operations=len(queues),
                complete_transport_operations=complete, partial_retired_operations=partial,
                credit_waits=sum(v[1]['result']==-11 and v[1]['wait']==1 for v in attempts.values()),
                uncertain_acceptances=sum(2 in v and v[2]['result']==0 and v[1]['result']!=0 for v in attempts.values()),
                scope=('Default-off Session observations include dynamic CMTC envelopes in the exact accepted USB/trace join on recorded identities;not CMTC negotiation success,credit truth,callback drain,peer delivery,RF,performance or concurrency proof' if dynamic_control else
                       'Default-off C4 Session observations plus original USB submits;no credit truth,callback drain,peer delivery,RF,performance or concurrency proof;dynamic CMTC consent excluded'))
    if discarded:
        proof['queued_discarded_operations'] = discarded
    return proof, unclosed


def join(parsed, owners, capture):
    proof, unclosed = _associate(parsed, owners, capture)
    if unclosed:
        raise ValueError('unaccounted software admission/dequeue/operation retirement')
    return proof


def _read_trace(folder):
    """Shared original-file validation, without choosing a qualification mode."""
    folder = Path(folder)
    row = json.loads((folder/'run.json').read_text())
    if (folder/'header_page.txt').read_text() != row['header_page']:
        raise ValueError('original kernel trace page layout changed')
    raw_trace=trace_bytes(folder/'trace.txt',row)
    if row['trace_sha256'] != hashlib.sha256(raw_trace).hexdigest():
        raise ValueError('trace bytes changed')
    for name in EVENTS:
        if row['formats'][name] != digest(folder/(name+'.format')):
            raise ValueError('original kernel event format changed')
    for cpu, raw in row['stats'].items():
        if (folder/(cpu+'-stats.txt')).read_text() != raw:
            raise ValueError('original CPU statistics changed')
    return raw_trace.decode('utf-8'), row


def corroborate(record, capture, share):
    text, row = _read_trace(Path(share) / 'session-service')
    parsed = parse(text, row)
    if summary(parsed) != row['observed']:
        raise ValueError('captured trace summary mismatch')
    proof = join(parsed, identities(record), capture)
    if 'collector_profile'in parsed:proof.update(collector_contract_version=2,collector_profile=parsed['collector_profile'])
    if record.get('channel_grant', {}).get('queued_discard_contract_version') is not None:
        if record['channel_grant'].get('queue_boot_id') != row.get('boot_id'):
            raise ValueError('queued syscall and trace must belong to the same actual boot')
        proof['queued_discard_lifecycle'] = queued_lifecycle(record, parsed, capture)
    return proof


def queued_lifecycle(record, parsed, capture):
    """Join actual syscall windows to production queue retirement and USB.

    The original File/Grant/held-prefix oracle must pass independently. This
    observes local queued retirement, never credit refunds or reference drain.
    """
    from ws73_channel_grant import queued_admissions, verify_intents
    row = record['channel_grant']
    queued = queued_admissions(row)
    if len(queued) != 2:
        raise ValueError('explicit two-admission queued lifecycle required')
    verify_intents(row, record)
    proof = join(parsed, identities(record), capture)
    if proof.get('queued_discarded_operations') != 2:
        raise ValueError('exactly two local queued retirements and no sibling discard required')
    timings = _operation_timings(parsed, identities(record), capture, proof)
    i = record['index']; owner = row['owners'][i]; quantum = parsed['quantum_ns']
    operations = timings['operations']
    owned = [v for v in operations if (v['controller'], v['generation'], v['lifetime'])
             == (i, owner['generation'], owner['lifetime'])]
    admissions = []
    for entry in queued:
        found = [v for v in owned if entry['before_monotonic_ns']-quantum
                 <= v['admission_ns'] <= entry['after_monotonic_ns']+quantum]
        if len(found) != 1:
            raise ValueError('unique actual queue admission in original syscall window required')
        v = found[0]
        if (v.get('retirement_kind') != 'queued_discard_no_physical_prefix'
                or v['dtap_bytes'] != 2047 or v['epoch'] != owner['lease']
                or v['accepted_fragments'] or v['accepted_usb_records']
                or v['retirement_ns'] < v['admission_ns']-quantum):
            raise ValueError('queued original identity must retire without physical prefix')
        admissions.append(dict(sequence=v['admission_sequence'], payload_sha256=hashlib.sha256(bytes.fromhex(entry['payload'])).hexdigest(),
                               admission_ns=v['admission_ns'], retirement_ns=v['retirement_ns']))
    if len({v['sequence'] for v in admissions}) != 2:
        raise ValueError('each queued application admission retires once')
    armed = row['armed']
    begun = [v for v in owned if armed['admission_before_monotonic_ns']-quantum
             <= v['admission_ns'] <= armed['admission_after_monotonic_ns']+quantum]
    if (len(begun) != 1 or begun[0].get('retirement_kind') is not None
            or begun[0]['dtap_bytes'] != 2047 or begun[0]['epoch'] != owner['lease']
            or not begun[0]['accepted_fragments'] or not begun[0]['accepted_usb_records']
            or not 0 < sum(v['length'] for v in begun[0]['calls'] if v['acceptance_ns'] is not None) < 2047):
        raise ValueError('original begun Session PDU must remain a separate observed operation')
    mode = 'deadline' if 'data_deadline' in record else 'down' if 'data_link_down' in record else record['case']
    return dict(status='REAL_QUEUED_DISCARD_LIFECYCLE_CORROBORATED', mode=mode,
                controller=i, generation=owner['generation'], lifetime=owner['lifetime'], epoch=owner['lease'],
                queued_discarded_operations=2, queued_accepted_usb_packets=0, sibling_discarded_operations=0,
                admissions=admissions, begun_sequence=begun[0]['admission_sequence'],
                begun_accepted_usb_records=begun[0]['accepted_usb_records'],
                scope='Two ordinary constrained queue admissions and local retirement;original begun-PDU/File/Grant/USB oracle separately required. Not new business delivery,credit refund,NOCP truth,reuse,callback/reference drain or recovery.')


def valid_queued_summary(proof):
    if not isinstance(proof, dict):
        return False
    rows = proof.get('admissions', [])
    return (proof.get('status') == 'REAL_QUEUED_DISCARD_LIFECYCLE_CORROBORATED'
            and proof.get('mode') in ('release', 'close', 'dup', 'down', 'deadline')
            and type(proof.get('controller')) is int and proof['controller'] in (0, 1)
            and all(type(proof.get(k)) is int and proof[k] > 0 for k in ('generation', 'lifetime', 'epoch', 'begun_sequence'))
            and type(proof.get('queued_discarded_operations')) is int and proof['queued_discarded_operations'] == 2
            and type(proof.get('queued_accepted_usb_packets')) is int and proof['queued_accepted_usb_packets'] == 0
            and type(proof.get('sibling_discarded_operations')) is int and proof['sibling_discarded_operations'] == 0
            and isinstance(rows, list) and len(rows) == 2
            and all(isinstance(v, dict) and type(v.get('sequence')) is int and v['sequence'] > 0
                    and isinstance(v.get('payload_sha256'), str) and re.fullmatch('[0-9a-f]{64}', v['payload_sha256'])
                    and type(v.get('admission_ns')) is int and v['admission_ns'] > 0
                    and type(v.get('retirement_ns')) is int and v['retirement_ns'] >= v['admission_ns'] for v in rows)
            and len({v['sequence'] for v in rows}) == 2
            and len({v['payload_sha256'] for v in rows}) == 2
            and proof['begun_sequence'] not in {v['sequence'] for v in rows}
            and isinstance(proof.get('begun_accepted_usb_records'), list) and bool(proof['begun_accepted_usb_records'])
            and all(type(n) is int and n > 0 for n in proof['begun_accepted_usb_records']))


def operation_timings(parsed, owners, capture):
    """Read-only timings after the existing full trace/USB join, not new credit truth.

    Admission IDs are debug observations, not application message sequence IDs.
    Inter-attempt gaps include scheduling/other work; a reported credit wait does
    not establish when the controller freed a buffer. No timestamps cross clocks.
    """
    proof = join(parsed, owners, capture)
    return _operation_timings(parsed, owners, capture, proof)


def failed_operation_timings(parsed, owners, capture):
    """All observed transport rows must agree; unknown ends stay explicit.

    This cannot replace the strict join or a successful application gate.
    Every software admission remains in the output, including censored ones.
    """
    proof, unclosed = _associate(parsed, owners, capture)
    return dict(unclosed_software_operations=unclosed,
                **_operation_timings(parsed, owners, capture, proof))


def _operation_timings(parsed, owners, capture, proof):
    quantum = parsed['quantum_ns']

    def interval(first, last):
        delta = last - first
        if delta < -quantum:
            raise ValueError('operation timing reversed beyond trace resolution')
        return dict(observed_ns=delta, lower_ns=max(0, delta-quantum),
                    upper_ns=delta+quantum)

    queues, attempts, services = defaultdict(list), defaultdict(dict), {}
    all_attempts = defaultdict(dict)
    for v in parsed['rows']:
        ident = (v['ctl'], v['gen'], v['life'])
        if v['event'] == 'queue':
            queues[(*ident, v['slot'], v['sequence'])].append(v)
        elif v['event'] == 'tx' and v['slot'] >= 0:
            attempts[(*ident, v['slot'], v['sequence'])].setdefault(
                (v['service'], v['offset']), {})[v['stage']] = v
        elif v['event'] == 'work' and v['stage'] == 1:
            services[(*ident, v['service'])] = v
        if v['event'] == 'tx':
            all_attempts[(*ident, v['slot'], v['sequence'], v['service'], v['offset'])][v['stage']] = v
    # Reuse the exact order already validated by join(), including control
    # packets and handle reuse across lifetimes. No payload decoder is added.
    physical = defaultdict(list)
    for key, stages in all_attempts.items():
        if 2 in stages and stages[2]['result'] == 0:
            owner = owners[key[:3]]
            physical[owner['bus'], owner['device'], owner['handle']].append((key[:5], stages))
    records = defaultdict(list)
    for physical_key, values in physical.items():
        values.sort(key=lambda v: v[1][0]['mono_ns'])
        packets = [v for v in capture['acb_packets'] if v['direction'] == 'out'
                   and (v['bus'], v['device'], v['handle']) == physical_key]
        for (key, _), packet in zip(values, packets):
            records[key].append(packet['record'])
    rows = []
    for key, stages in sorted(queues.items()):
        admitted = next(v for v in stages if v['stage'] == 0)
        retired = next((v for v in stages if v['stage'] in (2, 3)), None)
        dequeues = sorted((v['mono_ns'] for v in stages if v['stage'] == 1))
        tries = sorted(attempts[key].values(), key=lambda s: s[0]['mono_ns'])
        accepted = [s for s in tries if 2 in s and s[2]['result'] == 0]
        waits = [s for s in tries if s[1]['result'] == -11 and s[1]['wait'] == 1]
        service_ids = sorted({s[0]['service'] for s in tries})
        gaps = []
        for previous, current in zip(tries, tries[1:]):
            gaps.append(dict(after_service=previous[0]['service'],
                             before_service=current[0]['service'],
                             previous_result=previous[1]['result'],
                             previous_wait=previous[1]['wait'],
                             duration=interval(previous[1]['mono_ns'], current[0]['mono_ns'])))
        row = dict(controller=key[0], generation=key[1], lifetime=key[2],
                   epoch=admitted['epoch'], slot=key[3], admission_sequence=key[4],
                   dtap_bytes=admitted['bytes'], deadline_jiffies=admitted['deadline'],
                   admission_ns=admitted['mono_ns'], dequeue_ns=dequeues,
                   retirement_ns=retired['mono_ns'] if retired else None, attempts=len(tries),
                   accepted_fragments=len(accepted), reported_credit_waits=len(waits),
                   accepted_usb_records=records[key],
                   uncertain_acceptances=sum(s[1]['result'] != 0 for s in accepted),
                   admission_to_dequeue=interval(admitted['mono_ns'], dequeues[0]) if dequeues else None,
                   admission_to_retirement=interval(admitted['mono_ns'], retired['mono_ns']) if retired else None,
                   admission_to_first_attempt=None, admission_to_first_acceptance=None,
                   accepted_fragment_span=None, inter_attempt_gaps=gaps,
                   calls=[dict(service=s[0]['service'], offset=s[0]['offset'],
                               length=s[0]['len'], pb=s[0]['pb'], result=s[1]['result'],
                               wait=s[1]['wait'], begin_ns=s[0]['mono_ns'],
                               return_ns=s[1]['mono_ns'],
                               acceptance_ns=s[2]['mono_ns'] if s in accepted else None,
                               duration=interval(s[0]['mono_ns'], s[1]['mono_ns']))
                          for s in tries],
                   services=[dict(sequence=n, stop=services[(*key[:3], n)]['stop'],
                                  attempts=services[(*key[:3], n)]['attempts'],
                                  bytes=services[(*key[:3], n)]['bytes'],
                                  elapsed_ns=services[(*key[:3], n)]['elapsed_ns'],
                                  planned_delay_jiffies=services[(*key[:3], n)]['planned_delay'])
                             for n in service_ids])
        if tries:
            row['admission_to_first_attempt'] = interval(admitted['mono_ns'], tries[0][0]['mono_ns'])
        if accepted:
            row['admission_to_first_acceptance'] = interval(admitted['mono_ns'], accepted[0][2]['mono_ns'])
            row['accepted_fragment_span'] = interval(accepted[0][2]['mono_ns'], accepted[-1][2]['mono_ns'])
        if retired and retired['stage'] == 3:
            row['retirement_kind'] = 'queued_discard_no_physical_prefix'
        rows.append(row)
    control_waits = sum(v['event'] == 'tx' and v['slot'] == -1 and v['stage'] == 1
                        and v['result'] == -11 and v['wait'] == 1 for v in parsed['rows'])
    if (len(rows) != proof['operations']
            or sum(v['reported_credit_waits'] for v in rows) + control_waits != proof['credit_waits']):
        raise ValueError('operation observation accounting mismatch')
    return dict(version=1, clock='mono', quantum_ns=quantum, operations=rows,
                control_reported_credit_waits=control_waits,
                scope='Trace admission IDs,not application IDs;DTAP bytes include its header. '
                      'Retirement is local operation retirement,not delivery. Atomic acceptance '
                      'is not controller completion. Reported credit waits and gaps do not '
                      'prove credit correctness or isolate credit,USB,firmware,radio or scheduling delay.')


def bind_business(timings, rows):
    """Associate already verified business legs through exact original USB records."""
    by_first_record = {}
    for operation in timings['operations']:
        operation['business'] = None
        records = operation['accepted_usb_records']
        if records:
            if records[0] in by_first_record:
                raise ValueError('ambiguous operation USB record')
            by_first_record[records[0]] = operation
    for row in rows:
        for direction, packet in [('request', row['records'][0]), ('reply', row['records'][2])]:
            operation = by_first_record.get(packet['fragment_records'][0])
            if (operation is None or operation['business'] is not None
                    or operation['accepted_usb_records'] != packet['fragment_records']):
                raise ValueError('business leg and Session operation fragments differ')
            operation['business'] = dict(phase=row['phase'], source=row['source'],
                                         sequence=row['sequence'], direction=direction,
                                         request_frame_sha256=row['frame_sha256'])


def nocp_candidates(parsed, owners, capture, timings):
    """Observed wire/worker timing candidates, never credit attribution.

    Call after the existing complete or censored trace/USB join. NOCP carries
    only handle/count. An observation window cannot establish its generation,
    lifetime, accuracy, uniqueness or which ticket it completed.
    """
    def stats(values):
        return dict(count=len(values), min_ns=min(values) if values else None,
                    median_ns=statistics.median(values) if values else None,
                    max_ns=max(values) if values else None)

    lo, hi = parsed['offset_ns']
    quantum = parsed['quantum_ns']
    windows, services = {}, {}
    for row in parsed['rows']:
        key = row['ctl'], row['gen'], row['life']
        begin, end = windows.get(key, (row['mono_ns'], row['mono_ns']))
        windows[key] = min(begin, row['mono_ns']), max(end, row['mono_ns'])
        if row['event'] == 'work' and row['stage'] == 0:
            services[(*key, row['service'])] = row['mono_ns']
    indices, wire = {}, []
    for key, (begin, end) in sorted(windows.items()):
        owner = owners[key]
        events = []
        for event in capture['native_events']:
            if (event['event'] != 9
                    or (event['bus'], event['device']) != (owner['bus'], owner['device'])
                    or not begin+lo-quantum <= event['wall_ns'] <= end+hi+quantum):
                continue
            data = bytes.fromhex(event['params'])
            if len(data) != 3:
                raise ValueError('SDK110 single-handle NOCP format required for timing observation')
            if int.from_bytes(data[:2], 'little') != owner['handle']:
                continue
            events.append(dict(wall_ns=event['wall_ns'], record=event['record'],
                               hcc_offset=event.get('hcc_offset', 0), count=data[2]))
        events.sort(key=lambda v: (v['wall_ns'], v['record'], v['hcc_offset']))
        indices[key] = [v['wall_ns'] for v in events], events
        wire.append(dict(controller=key[0], generation=key[1], observed_lifetime=key[2],
                         wire_has_generation=False, wire_has_lifetime=False,
                         events=len(events), reported_count_sum=sum(v['count'] for v in events),
                         count_distribution={str(n): sum(v['count'] == n for v in events)
                                             for n in sorted({v['count'] for v in events})},
                         interarrival=stats([b['wall_ns']-a['wall_ns']
                                             for a, b in zip(events, events[1:])]),
                         source_window_mono_ns=[begin, end]))
    episodes, unmatched = [], []
    for operation in timings['operations']:
        key = operation['controller'], operation['generation'], operation['lifetime']
        stamps, events = indices[key]
        last_wait = {}
        for call in operation['calls']:
            if call['result'] == -11 and call['wait'] == 1:
                last_wait[call['offset']] = call
            if call['acceptance_ns'] is None or call['offset'] not in last_wait:
                continue
            wait = last_wait[call['offset']]
            index = bisect_right(stamps, call['acceptance_ns']+hi+quantum)-1
            identity = dict(controller=key[0], generation=key[1], observed_lifetime=key[2],
                            admission_sequence=operation['admission_sequence'],
                            slot=operation['slot'], offset=call['offset'])
            if index < 0:
                unmatched.append(identity | dict(reason='no_preceding_candidate_in_observed_window'))
                continue
            event = events[index]
            lower, upper = event['wall_ns']-hi-quantum, event['wall_ns']-lo+quantum
            worker = services[(*key, call['service'])]
            relation = ('after_last_refusal' if lower >= wait['return_ns'] else
                        'overlaps_last_refusal' if upper >= wait['return_ns'] else
                        'before_last_refusal')
            episodes.append(identity | dict(service=call['service'], wire_candidate=event,
                wire_relation=relation, worker_start_ns=worker,
                last_refusal_return_ns=wait['return_ns'], acceptance_ns=call['acceptance_ns'],
                wire_to_worker_lower_ns=worker-upper, wire_to_worker_upper_ns=worker-lower,
                wire_to_acceptance_lower_ns=call['acceptance_ns']-upper,
                wire_to_acceptance_upper_ns=call['acceptance_ns']-lower,
                worker_to_acceptance_ns=call['acceptance_ns']-worker,
                refusal_to_acceptance_ns=call['acceptance_ns']-wait['return_ns']))
    metrics = {name: stats([v[name] for v in episodes]) for name in (
        'wire_to_worker_lower_ns', 'wire_to_worker_upper_ns',
        'wire_to_acceptance_lower_ns', 'wire_to_acceptance_upper_ns',
        'worker_to_acceptance_ns', 'refusal_to_acceptance_ns')}
    return dict(version=1, status='WIRE_NOCP_TIMING_CANDIDATES_NOT_CAUSAL_OR_CREDIT_PROOF',
                quantum_ns=quantum, wire=wire, episodes=episodes, unmatched=unmatched,
                metrics=metrics,
                scope='Latest preceding same-handle wire event within observed Session window; '
                      'not authenticated generation/lifetime or a ticket completion mapping. '
                      'No credit ledger simulation, exact Runtime notification timestamp/cause, '
                      'NOCP truth/duplicate/late/reuse-barrier proof, isolated RF delay or '
                      'performance qualification. Bounds use captured wall/mono anchors; '
                      'negative bounds remain visible for an already running/coalesced worker.')


def analyze_benchmark(directory):
    """Replay the original paired application oracle before retrospective timings."""
    from ws73_benchmark_timeline import analyze, material
    from ws73_capture import read_capture
    root = Path(directory).resolve(strict=True)
    timeline = analyze(root)  # Full original app/USB/capture/role/source oracle.
    manifest = json.loads((root/'manifest.json').read_text())
    if (manifest.get('session_service_observation_requested') is not True
            or manifest.get('session_service_acceptance') is not True):
        raise ValueError('original successful Session observation required')
    share = root/'guest-output'
    record = json.loads((share/'application/passthrough-control/run.json').read_text())
    owners = identities(record)
    capture = read_capture(share/'ws73.pcap', {(v['bus'], v['device']) for v in owners.values()})
    proof = corroborate(record, capture, share)
    if proof != manifest['session_service_observation']:
        raise ValueError('original Session observation replay mismatch')
    folder = share/'session-service'
    parsed = parse((folder/'trace.txt').read_text(), json.loads((folder/'run.json').read_text()))
    timings = operation_timings(parsed, owners, capture)
    bind_business(timings, timeline['rows'])
    return dict(status='SESSION_TIMINGS_OBSERVED_NOT_PERFORMANCE_QUALIFIED',
                source_manifest=material(root/'manifest.json'),
                trace=material(folder/'trace.txt'), trace_receipt=material(folder/'run.json'),
                original_round_trips=timeline['round_trips'], service_observation=proof,
                nocp_observation=nocp_candidates(parsed, owners, capture, timings),
                **timings)


def _check_kernel_strings(trace, control):
    # The collector records uname.version; the control receipt records the
    # whole /proc/version line. Compare the actual formats, not unlike strings.
    # These observations do not attest the executing image; artifact identity
    # remains the separately hashed kernel/preparation/source mapping.
    if (trace['kernel_release'] != control['kernel_release']
            or not re.fullmatch(re.escape('Linux version '+trace['kernel_release'])
                                + r' \([^\n]+\) '+re.escape(trace['kernel_version'])+r'\n?',
                                control['kernel_version'])):
        raise ValueError('original trace/control kernel identity differs')


def analyze_failed_benchmark(directory, phase, *, pending_rx_tail=False, application_progress=False, host_usb=False):
    """Censored transport observations from an unchanged failed application gate.

    Reuse the strict failed-phase/export/capture validator. No success receipt
    is synthesized, no window is shortened, and the original failure remains
    required. All observed trace/USB submissions must agree; unknown software
    retirement is explicitly retained and cannot qualify a full trace join.
    """
    from ws73_rx_gap import diagnose_failed
    from ws73_benchmark_timeline import material
    from ws73_capture import read_capture
    if type(host_usb) is not bool or host_usb and not application_progress:
        raise ValueError('host USB analysis requires explicit failed application progress')
    root = Path(directory).resolve(strict=True)
    failure = diagnose_failed(root, phase, pending_rx_tail=pending_rx_tail)
    manifest = json.loads((root/'manifest.json').read_text())
    if (manifest.get('session_service_observation_requested') is not True
            or manifest.get('session_service_acceptance') is not False):
        raise ValueError('failed original Session observation required')
    share = root/'guest-output'
    record = json.loads((share/'application/passthrough-control/run.json').read_text())
    text, row = _read_trace(share/'session-service')
    _check_kernel_strings(row, record)
    parsed = parse_aborted(text, row)
    owners = identities(record)
    capture = read_capture(share/'ws73.pcap', {(v['bus'], v['device']) for v in owners.values()},
                           observe_rx=host_usb, observe_bulk=host_usb)
    timings = failed_operation_timings(parsed, owners, capture)
    result = dict(status='FAILED_GATE_TRANSPORT_TIMINGS_NOT_QUALIFIED',
                original_gate_qualified=False, original_result='FAIL',
                failure={k: v for k, v in failure.items() if k != 'windows'},
                source_manifest=material(root/'manifest.json'),
                trace=material(share/'session-service/trace.txt'),
                trace_receipt=material(share/'session-service/run.json'),
                trace_observation=summary(parsed),
                nocp_observation=nocp_candidates(parsed, owners, capture, timings),
                **timings)
    if type(application_progress)is not bool:
        raise ValueError('explicit offline application-progress selector required')
    if application_progress:
        from ws73_benchmark_progress import application_prefixes, read_failed_reports, transport_prefixes, observed_link_window
        from ws73_rx_gap import failed_phase_inputs
        _,_,_,request,row,exported=failed_phase_inputs(root,phase)
        if len(row['applications'])!=2 or row.get('benchmark_channel_request',{}).get('version')!=1:
            raise ValueError('original two-application dynamic window slice required')
        reports,report_files=read_failed_reports(share/'benchmark-role'/f'phase-{phase}',phase,exported)
        application=application_prefixes(reports,request['config'])
        anchor=min(e['before_wall_ns'] for e in row['events'] if e['kind']=='start')
        scoped,windows=observed_link_window(capture,row['owners'],anchor)
        transport=transport_prefixes(scoped,reports,application,row['owners'])
        if host_usb:
            from ws73_host_usb import observe_failed
            result['host_usb_observation'] = observe_failed(root,manifest,row,reports,application,capture,timings,parsed)
        application.pop('catalog') # Only hashes/indices/counts in this diagnostic summary.
        result['failed_application_progress']=dict(application=application,transport=transport,
            reports=report_files,observed_link_windows=windows,original_gate_qualified=False,
            scope='Original failed socket-fault window/peer slice only. Independent report/frame/prefix association;no clock subtraction,credit truth,firmware cause or successful application gate. Other failure shapes refused.')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'finish', 'abort', 'analyze-benchmark', 'analyze-failed-benchmark'])
    p.add_argument('directory', nargs='?', type=Path)
    p.add_argument('--failed-phase', type=int, choices=[0, 1])
    p.add_argument('--pending-rx-tail', action='store_true',help='explicit offline failed-capture v2;not normal success')
    p.add_argument('--application-progress', action='store_true',help='explicit offline original failed window/peer reports and retired prefixes;never a passing benchmark')
    p.add_argument('--host-usb', action='store_true',help='opt-in failed business/host-length candidates;not a clock mapping or delivery qualification')
    args = p.parse_args()
    if args.action.startswith('analyze-') != (args.directory is not None):
        p.error('only analysis actions require a captured VM run directory')
    if args.pending_rx_tail and args.action != 'analyze-failed-benchmark':
        p.error('pending RX tail only applies to original failed observations')
    if args.application_progress and args.action!='analyze-failed-benchmark':
        p.error('application progress only applies to original failed observations')
    if args.host_usb and (args.action!='analyze-failed-benchmark' or not args.application_progress):
        p.error('host USB observations require failed application progress')
    if (args.action == 'analyze-failed-benchmark') != (args.failed_phase is not None):
        p.error('only analyze-failed-benchmark requires an explicit failed phase')
    if args.action == 'analyze-benchmark':
        print(json.dumps(analyze_benchmark(args.directory), indent=2))
    elif args.action == 'analyze-failed-benchmark':
        print(json.dumps(analyze_failed_benchmark(args.directory, args.failed_phase, pending_rx_tail=args.pending_rx_tail,application_progress=args.application_progress,host_usb=args.host_usb), indent=2))
    elif args.action == 'start':
        configure()
    else:
        finish(args.action == 'abort')
