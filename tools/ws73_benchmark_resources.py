# SPDX-License-Identifier: GPL-2.0-only
"""Bounded /proc observations of the existing VM benchmark children.

Two checkpoints outside business execution, not a sampling thread, queue/URB
peak monitor, leak proof or per-packet data path. Raw bytes stay in root's
existing closed phase receipt. CPU ticks and memory units remain explicit.
"""
import os
from pathlib import Path
import re
import time

from ws73_capture import CaptureError

VERSION = 1
FIELDS = {'version', 'pid', 'ppid', 'clock_ticks', 'page_bytes', 'begin_mono_ns',
          'end_mono_ns', 'stat', 'identity_stat', 'status', 'fds', 'image'}
MEMORY = ('VmPeak', 'VmSize', 'VmHWM', 'VmRSS', 'RssAnon', 'RssFile', 'RssShmem')


def stat_fields(raw):
    if not isinstance(raw, str) or len(raw) > 8192:
        raise CaptureError('bounded original process stat required')
    head, sep, tail = raw.rpartition(') ')
    if not sep or not re.fullmatch(r'[1-9][0-9]* \([^\n]*', head):
        raise CaptureError('invalid original process stat')
    fields = tail.split()
    if len(fields) < 22 or fields[0] not in ('S', 'R', 'D', 'I'):
        raise CaptureError('live benchmark child required')
    try:
        values = [int(fields[n]) for n in (1, 11, 12, 19)]
    except ValueError as error:
        raise CaptureError('integer process counters required') from error
    if any(not 0 <= v < 2**64 for v in values) or not values[0] or not values[3]:
        raise CaptureError('positive process identity and bounded counters required')
    return dict(pid=int(head.split(' ', 1)[0]), ppid=values[0], user_ticks=values[1],
                system_ticks=values[2], start_ticks=values[3])


def parse(snapshot):
    try:
        if (set(snapshot) != FIELDS or type(snapshot['version']) is not int or snapshot['version'] != VERSION
                or any(type(snapshot[k]) is not int or snapshot[k] <= 0 for k in
                       ('pid', 'ppid', 'clock_ticks', 'page_bytes', 'begin_mono_ns', 'end_mono_ns'))
                or snapshot['clock_ticks'] > 1000000 or snapshot['page_bytes'] > 1024*1024
                or snapshot['begin_mono_ns'] >= snapshot['end_mono_ns']
                or snapshot['end_mono_ns'] - snapshot['begin_mono_ns'] > 5_000_000_000):
            raise CaptureError('bounded process checkpoint contract required')
        first, last = stat_fields(snapshot['stat']), stat_fields(snapshot['identity_stat'])
        if any(first[k] != last[k] for k in ('pid', 'ppid', 'start_ticks')) or any(
                first[k] != snapshot[k] for k in ('pid', 'ppid')) or any(
                last[k] < first[k] for k in ('user_ticks', 'system_ticks')):
            raise CaptureError('same live child throughout checkpoint required')
        raw = snapshot['status']
        if not isinstance(raw, str) or len(raw) > 65536:
            raise CaptureError('bounded original process status required')
        fields = {}
        for line in raw.splitlines():
            key, sep, value = line.partition(':')
            if not sep or key in fields:
                raise CaptureError('complete unique process status fields required')
            fields[key] = value.strip()
        if (fields['Pid'] != str(first['pid']) or fields['Tgid'] != str(first['pid'])
                or fields['PPid'] != str(first['ppid'])
                or any(fields[k].split() != ['1004']*4 for k in ('Uid', 'Gid'))
                or fields['Groups'] or any(int(fields[k], 16) for k in ('CapEff', 'CapPrm', 'CapAmb', 'CapInh'))):
            raise CaptureError('original apps-only process status required')
        memory = {}
        for key in MEMORY:
            match = re.fullmatch(r'(0|[1-9][0-9]*)\s+kB', fields[key])
            if not match or int(match[1]) >= 2**54:
                raise CaptureError('Linux kB (1024 bytes) memory counter required')
            memory[key] = int(match[1])*1024
        if memory['VmHWM'] < memory['VmRSS'] or memory['VmPeak'] < memory['VmSize']:
            raise CaptureError('inconsistent process memory counters')
        fds = snapshot['fds']; image = snapshot['image']
        if (not isinstance(fds, list) or not 1 <= len(fds) <= 4096
                or any(type(v) is not int or not 0 <= v < 2**31 for v in fds)
                or fds != sorted(set(fds)) or set(image) != {'device', 'inode'}
                or any(type(v) is not int or not 0 < v < 2**64 for v in image.values())):
            raise CaptureError('bounded fd names and executable identity required')
        return dict(first, memory_bytes=memory, fd_count=len(fds), clock_ticks=snapshot['clock_ticks'],
                    page_bytes=snapshot['page_bytes'], image=image,
                    begin_mono_ns=snapshot['begin_mono_ns'], end_mono_ns=snapshot['end_mono_ns'])
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise CaptureError('complete process resource checkpoint required') from error


def collect(pid, executable):
    from ws73_application_role import require_vm
    from ws73_application_client import process_identity
    require_vm('ws73.socket_benchmark_apps=1')
    if type(pid) is not int or pid <= 0:
        raise CaptureError('owned benchmark child pid required')
    begin = time.monotonic_ns(); root = Path('/proc') / str(pid)
    def read(name, limit):
        with (root/name).open() as f: raw = f.read(limit+1)
        if len(raw) > limit: raise CaptureError('process observation byte budget')
        return raw
    identity, status = process_identity(pid, 1004)
    first = read('stat', 8192)
    fds = []
    with os.scandir(root/'fd') as entries:
        for item in entries:
            if not item.name.isdecimal() or len(fds) >= 4096:
                raise CaptureError('process fd observation budget')
            fds.append(int(item.name))
    actual, expected = (root/'exe').stat(), Path(executable).stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise CaptureError('child executable differs from prepared slktest')
    last = read('stat', 8192)
    if process_identity(pid, 1004)[0] != identity:
        raise CaptureError('child credentials changed during observation')
    snapshot = dict(version=VERSION, pid=pid, ppid=os.getpid(), clock_ticks=os.sysconf('SC_CLK_TCK'),
                    page_bytes=os.sysconf('SC_PAGE_SIZE'), begin_mono_ns=begin, end_mono_ns=time.monotonic_ns(),
                    stat=first, identity_stat=last, status=status, fds=sorted(fds),
                    image=dict(device=actual.st_dev, inode=actual.st_ino))
    parse(snapshot)
    return snapshot


def observations(row):
    version = row.get('benchmark_process_resource_contract_version')
    if version is None:
        if any('process_resources' in app for app in row['applications']):
            raise CaptureError('resource observations require explicit version')
        return None  # Historical decoder only, never new live acceptance.
    if type(version) is not int or version != VERSION or len(row['applications']) != 2:
        raise CaptureError('two process checkpoint pairs required')
    events = row['events']; result = []
    for app in row['applications']:
        pair = app.get('process_resources', {})
        if set(pair) != {'before', 'after'}: raise CaptureError('complete process checkpoint pair required')
        before, after = parse(pair['before']), parse(pair['after'])
        if (any(before[k] != after[k] for k in ('pid', 'ppid', 'start_ticks', 'clock_ticks', 'page_bytes', 'image'))
                or before['pid'] != app['pid']
                or before['ppid'] != row['role_supervisor']['pid']
                or not max(e['monotonic_ns'] for e in events if e['kind']=='armed') <= before['begin_mono_ns']
                or not before['end_mono_ns'] <= min(e['before_monotonic_ns'] for e in events if e['kind']=='start')
                or not max(e['monotonic_ns'] for e in events if e['kind']=='quiescent') <= after['begin_mono_ns']
                or not after['end_mono_ns'] <= min(e['before_monotonic_ns'] for e in events if e['kind']=='finish')
                or any(after[k] < before[k] for k in ('user_ticks', 'system_ticks'))
                or any(after['memory_bytes'][k] < before['memory_bytes'][k] for k in ('VmHWM', 'VmPeak'))):
            raise CaptureError('same original child and resource checkpoints outside business required')
        result.append(dict(pid=before['pid'], start_ticks=before['start_ticks'],
                           user_ticks_delta=after['user_ticks']-before['user_ticks'],
                           system_ticks_delta=after['system_ticks']-before['system_ticks'],
                           clock_ticks_per_second=before['clock_ticks'],
                           before=before, after=after))
    return result


def valid_summary(proof):
    """Shape/arithmetic of a receipt; raw /proc identity is replayed separately."""
    try:
        if (type(proof['benchmark_process_resource_contract_version']) is not int
                or proof['benchmark_process_resource_contract_version'] != VERSION
                or len(proof['proofs']) != 2):
            return False
        for phase, row in enumerate(proof['proofs']):
            samples = row['resource_observations']
            if row['phase'] != phase or len(samples) != 2 or len({s['pid'] for s in samples}) != 2:
                return False
            for item in samples:
                if (set(item) != {'pid', 'start_ticks', 'user_ticks_delta', 'system_ticks_delta',
                                  'clock_ticks_per_second', 'before', 'after'}
                        or any(type(item[k]) is not int for k in ('pid', 'start_ticks',
                               'user_ticks_delta', 'system_ticks_delta', 'clock_ticks_per_second'))):
                    return False
                before, after = item['before'], item['after']
                for point in (before, after):
                    if (any(type(point[k]) is not int or point[k] <= 0 for k in
                            ('pid', 'ppid', 'start_ticks', 'clock_ticks', 'page_bytes', 'fd_count', 'begin_mono_ns', 'end_mono_ns'))
                            or point['fd_count'] > 4096 or point['clock_ticks'] > 1000000
                            or point['page_bytes'] > 1024*1024
                            or any(type(point[k]) is not int or not 0 <= point[k] < 2**64
                                   for k in ('user_ticks', 'system_ticks'))
                            or not 0 < point['end_mono_ns'] - point['begin_mono_ns'] <= 5_000_000_000
                            or set(point['memory_bytes']) != set(MEMORY)
                            or any(type(v) is not int or not 0 <= v < 2**64 or v % 1024 for v in point['memory_bytes'].values())):
                        return False
                if (any(before[k] != after[k] for k in ('pid', 'ppid', 'start_ticks', 'clock_ticks', 'page_bytes', 'image'))
                        or item['pid'] != before['pid'] or item['start_ticks'] != before['start_ticks']
                        or item['clock_ticks_per_second'] != before['clock_ticks']
                        or not before['end_mono_ns'] < after['begin_mono_ns']):
                    return False
                for key in ('user_ticks', 'system_ticks'):
                    delta = item[key + '_delta']
                    if type(delta) is not int or delta != after[key] - before[key] or delta < 0:
                        return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
