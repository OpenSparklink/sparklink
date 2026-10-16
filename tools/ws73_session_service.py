#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Passive, VM-only Session service trace. No packets, credit or Ready generated.

Software admission, atomic USB acceptance, joined return and retirement remain
separate. Full application/USB correctness must pass the existing oracle first.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
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
    FOLDER.mkdir(mode=0o700)
    row = dict(status='RUNNING_NOT_QUALIFIED', cookie=secrets.token_hex(16),
               boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               kernel_release=os.uname().release, kernel_version=os.uname().version,
               clock='mono', requested_buffer_kb=1024, anchors=[], created=False)
    save(row)
    try:
        if not (ROOT / 'available_tracers').is_file():
            subprocess.run(['/bin/mount', '-t', 'tracefs', 'tracefs', str(ROOT)], check=True)
        INSTANCE.mkdir()
        row['created'] = True
        write('tracing_on', '0')
        write('current_tracer', 'nop')
        write('trace_clock', 'mono')
        write('buffer_size_kb', '1024')
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
        text = (INSTANCE / 'trace').read_text()
        (FOLDER / 'trace.txt').write_text(text)
        row['trace_sha256'] = digest(FOLDER / 'trace.txt')
        row['stats'] = {}
        for p in sorted((INSTANCE / 'per_cpu').glob('cpu*/stats')):
            raw = p.read_text()
            (FOLDER / (p.parent.name + '-stats.txt')).write_text(raw)
            row['stats'][p.parent.name] = raw
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
    if (len(text) > LIMIT or row['status'] != STATUS or row['clock'] != 'mono'
            or not re.fullmatch('[0-9a-f]{32}', row['cookie'])
            or re.findall(r'^# tracer: (.*)$', text, re.M) != ['nop']
            or 'LOST' in text.upper() or row['instance_removed'] is not True):
        raise ValueError('complete bounded same-clock trace required')
    read = row['readbacks']
    if read['current_tracer'] != 'nop' or '[mono]' not in read['trace_clock']:
        raise ValueError('original trace configuration required')
    expected_kib, _ = buffer_kib(row['header_page'], row['requested_buffer_kb'],
                               int(read['buffer_subbuf_size_kb']))
    if (type(row['requested_buffer_kb']) is not int or row['requested_buffer_kb'] != 1024
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
                or not 0 < v['life'] < 2**64 or v['stage'] not in (0, 1, 2)):
            raise ValueError('invalid trace identity/stage')
        if any(value < 0 or value >= 2**64 for k, value in v.items()
               if k not in ('slot', 'result', 'error')):
            raise ValueError('invalid unsigned trace field')
        v.update(event=m[3].removeprefix('sparklink_session_'), mono_ns=t)
        rows.append(v)
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
    return dict(rows=rows, quantum_ns=quantum, offset_ns=[low, high],
                interval_ns=[markers[0][1], markers[1][1]])


def summary(parsed):
    return dict(events=len(parsed['rows']), quantum_ns=parsed['quantum_ns'],
                offset_ns=parsed['offset_ns'], interval_ns=parsed['interval_ns'])


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


def join(parsed, owners, capture):
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
    complete = partial = 0
    for key, stages in queues.items():
        if set(stages) != {0, 1, 2}:
            raise ValueError('unaccounted software admission/dequeue/operation retirement')
        a, dequeues, c = stages[0], stages[1], stages[2]
        b = dequeues[0]
        snapshots = [a, *dequeues, c]
        if (any(len({v[field] for v in snapshots}) != 1 for field in ['epoch','bytes','deadline'])
                or a['epoch'] != epochs.get(key[:3]) or a['mono_ns'] > b['mono_ns']+q
                or b['mono_ns'] > c['mono_ns']+q):
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
        if any(not b['mono_ns']-q <= steps[0]['mono_ns'] <= c['mono_ns']+q for steps in op_attempts):
            raise ValueError('attempt outside dequeued operation lifetime')
        successful = [steps[1] for kt, steps in attempts.items()
                      if kt[:3] == key[:3] and kt[4:6] == (key[4], key[3]) and steps[1]['result'] == 0]
        successful.sort(key=lambda v:v['offset'])
        offset = 0
        for v in successful:
            expected_pb = (1 if v['len'] < a['bytes'] else 0) if offset == 0 else (3 if offset+v['len'] == a['bytes'] else 2)
            if (v['offset'] != offset or v['pb'] != expected_pb or offset+v['len'] > a['bytes']
                    or not b['mono_ns']-q <= v['mono_ns'] <= c['mono_ns']+q):
                raise ValueError('PB/offset/retirement continuity mismatch')
            offset += v['len']
        complete += offset == a['bytes']
        partial += offset != a['bytes']
    # Every accepted packet, including fixed CMTC, must have the corresponding
    # real USB submit, in the serialized physical order and within clock bounds.
    usb_total = 0
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
            if (packet['boundary'] != a['pb'] or len(bytes.fromhex(packet['data'])) != a['len']
                    or not a['mono_ns']+low-2*q <= packet['wall_ns'] <= commit['mono_ns']+high+2*q):
                raise ValueError('actual USB submit/Native interval mismatch')
            usb_total += 1
    return dict(status='REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED',
                **summary(parsed), services=len(works), attempts=len(attempts),
                accepted_usb_packets=usb_total, operations=len(queues),
                complete_transport_operations=complete, partial_retired_operations=partial,
                credit_waits=sum(v[1]['result']==-11 and v[1]['wait']==1 for v in attempts.values()),
                uncertain_acceptances=sum(2 in v and v[2]['result']==0 and v[1]['result']!=0 for v in attempts.values()),
                scope='Default-off C4 Session observations plus original USB submits;no credit truth,callback drain,peer delivery,RF,performance or concurrency proof;dynamic CMTC consent excluded')


def corroborate(record, capture, share):
    folder = Path(share) / 'session-service'
    row = json.loads((folder/'run.json').read_text())
    if (folder/'header_page.txt').read_text() != row['header_page']:
        raise ValueError('original kernel trace page layout changed')
    if row['trace_sha256'] != digest(folder/'trace.txt'):
        raise ValueError('trace bytes changed')
    for name in EVENTS:
        if row['formats'][name] != digest(folder/(name+'.format')):
            raise ValueError('original kernel event format changed')
    for cpu, raw in row['stats'].items():
        if (folder/(cpu+'-stats.txt')).read_text() != raw:
            raise ValueError('original CPU statistics changed')
    parsed = parse((folder/'trace.txt').read_text(), row)
    if summary(parsed) != row['observed']:
        raise ValueError('captured trace summary mismatch')
    return join(parsed, identities(record), capture)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'finish', 'abort'])
    args = p.parse_args()
    if args.action == 'start':
        configure()
    else:
        finish(args.action == 'abort')
