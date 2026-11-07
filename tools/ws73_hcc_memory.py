# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in VM-only root diagnostic. Raw HCC words never become protocol credit.

Reuse the existing finite observer thread and child supervision. An unsupported
or failed read disables later USB queries for that endpoint for this phase.
Later slots retain actual child skip receipts, not invented zero observations.
"""
import errno
import json
from pathlib import Path
import re

from ws73_capture import CaptureError
from ws73_transport_watch import (CAPABILITIES, SPEC, Watch, _validate,
                                  collect_process, ordinary, require_environment)

FIELD = 'hcc_memory_observation'
REQUEST = 'hcc_memory_observation_request'
VERIFIERS = ('ws73_hcc_memory.py',)
RUNTIME = '/bin/python3'
TOKEN = 'ws73.hcc_memory_observation=1'
REQUEST_SPEC = dict(version=1, request_type=161, request=5, value=0, index=0,
                    reply_bytes=4, usb_timeout_ms=250, semantics_verified=0)
PATTERN = re.compile(r'source=SDK_USB_CLASS_5 id=([0-9]+) generation=([0-9]+) '
                     r'raw_le32=([0-9]+) start_ns=([0-9]+) end_ns=([0-9]+) semantics_verified=0\n')

# The argument path is constructed from an original guest owner, never scanned
# or selected by enumeration. No caller-selected register/control request.
READER = '''import json,os,stat,sys,time
path,disabled=sys.argv[1],int(sys.argv[2])
start=time.monotonic_ns()
row=dict(path=path,disabled_errno=disabled,uid=os.geteuid(),start_ns=start)
try:
    row['mode']=stat.S_IMODE(os.stat(path).st_mode)
    if row['mode']!=0o400:raise OSError(1,'root-only diagnostic mode required')
    if disabled:
        row.update(status='SKIPPED_AFTER_ERROR',errno=disabled)
    else:
        with open(path,'rb',buffering=0) as f:data=f.read(1025)
        if len(data)>1024:raise OSError(75,'diagnostic byte budget')
        row.update(status='READ',data=data.decode('ascii'))
except OSError as e:
    row.update(status='ERROR',errno=e.errno)
except (UnicodeError,ValueError) as e:
    row.update(status='INVALID',error=type(e).__name__)
row['end_ns']=time.monotonic_ns()
print(json.dumps(row),flush=True)
sys.exit(0 if row['status'] in ('READ','SKIPPED_AFTER_ERROR') else 1)
'''


def path_for(entry):
    owner = entry['owner']
    if (owner.get('port') not in ('1-1', '1-2')
            or type(owner.get('index')) is not int or not 0 <= owner['index'] < 16
            or type(owner.get('generation')) is not int or not 0 < owner['generation'] < 2**64):
        raise CaptureError('exact original two-leaf guest owner required')
    return f"/sys/bus/usb/devices/{owner['port']}:1.0/hcc_memory_observation"


def command(entry, disabled=0):
    return [RUNTIME, '-c', READER, path_for(entry), str(disabled)]


def root_identity(pid):
    status = Path(f'/proc/{pid}/status').read_text()
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    identity = dict(uids=list(map(int, fields['Uid'].split())),
                    gids=list(map(int, fields['Gid'].split())),
                    groups=list(map(int, fields['Groups'].split())),
                    capabilities={k:fields[k].strip() for k in CAPABILITIES})
    if identity['uids'] != [0]*4 or identity['gids'] != [0]*4 or identity['groups']:
        raise CaptureError('root diagnostic child without inherited supplementary groups required')
    return identity, status


def decoded(receipt, entry, disabled=0, *, uid=0):
    if (receipt['outcome'] != 'EXITED' or receipt['args'] != command(entry, disabled)
            or receipt['stderr'] or receipt.get('identity_error') or receipt.get('reaped') is not True
            or type(receipt.get('pid')) is not int or receipt['pid'] <= 0
            or any(type(receipt.get(k)) is not int for k in ('start_monotonic_ns','end_monotonic_ns',
                    'deadline_monotonic_ns','start_wall_ns','end_wall_ns','exit'))
            or receipt['deadline_monotonic_ns'] != receipt['start_monotonic_ns']+SPEC['query_budget_ns']
            or not receipt['start_monotonic_ns'] <= receipt['end_monotonic_ns']
            or not receipt['start_wall_ns'] <= receipt['end_wall_ns']
            or max(len(receipt[k].encode()) for k in ('stdout','stderr')) > SPEC['stream_limit_bytes']):
        raise CaptureError('exact original diagnostic process receipt required')
    identity = receipt['credentials']
    if (identity['uids'] != [uid]*4 or identity['gids'] != [uid]*4 or identity['groups']
            or set(identity['capabilities']) != CAPABILITIES):
        raise CaptureError('original diagnostic child credentials required')
    if uid != 0 and any(int(v, 16) for v in identity['capabilities'].values()):
        raise CaptureError('ordinary access probe must have no capabilities')
    lines = receipt['stdout'].splitlines()
    if len(lines) != 1:
        raise CaptureError('one complete diagnostic JSON receipt required')
    row = json.loads(lines[0])
    if (row.get('path') != path_for(entry) or type(row.get('mode')) is not int or row['mode'] != 0o400
            or type(row.get('uid')) is not int or row['uid'] != uid
            or type(row.get('disabled_errno')) is not int or row['disabled_errno'] != disabled
            or any(type(row.get(k)) is not int for k in ('start_ns', 'end_ns'))
            or not receipt['start_monotonic_ns'] <= row['start_ns'] <= row['end_ns'] <= receipt['end_monotonic_ns']):
        raise CaptureError('root-only original bounded diagnostic receipt required')
    if disabled:
        if (row.get('status') != 'SKIPPED_AFTER_ERROR' or type(row.get('errno')) is not int or row['errno'] != disabled
                or receipt['exit'] != 0 or 'data' in row):
            raise CaptureError('disabled endpoint cannot issue another diagnostic read')
        return row
    if row.get('status') == 'ERROR':
        if type(row.get('errno')) is not int or not 0 < row['errno'] < 4096 or receipt['exit'] != 1 or 'data' in row:
            raise CaptureError('original diagnostic errno without invented data required')
        return row
    if uid != 0 or row.get('status') != 'READ' or receipt['exit'] != 0 or 'errno' in row:
        raise CaptureError('actual root read or explicit original errno required')
    match = PATTERN.fullmatch(row.get('data', ''))
    if match is None:
        raise CaptureError('exact kernel raw observation line required')
    index, generation, value, start, end = map(int, match.groups())
    if (index != entry['owner']['index'] or generation != entry['owner']['generation']
            or not 0 <= value < 2**32 or not row['start_ns'] <= start <= end <= row['end_ns']):
        raise CaptureError('current controller identity and in-read kernel clocks required')
    row['raw_observation'] = dict(index=index, generation=generation, raw_le32=value,
                                  start_ns=start, end_ns=end, semantics_verified=False)
    return row


def observer(owners, phase):
    require_environment()
    words=Path('/proc/cmdline').read_text().split()
    from ws73_benchmark_ssap import from_boot,observing_hcc
    if words.count(TOKEN) != 1 or not observing_hcc(from_boot(words)):
        raise CaptureError('one explicit HCC diagnostic VM boot token required')
    if len(owners) != 2 or {path_for(v) for v in owners} != {
            f'/sys/bus/usb/devices/1-{i}:1.0/hcc_memory_observation' for i in (1, 2)}:
        raise CaptureError('both distinct original guest leaves required')
    disabled, probes = {}, set()

    def query(entry, stop):
        path = path_for(entry)
        probe = None
        if path not in probes:
            probe = collect_process(command(entry), stop,
                                    credentials=dict(user=1000, group=1000, extra_groups=[], umask=0o077))
            try:
                denied = decoded(probe, entry, uid=1000)
                if denied.get('status') != 'ERROR' or denied['errno'] != errno.EACCES:
                    raise CaptureError('ordinary caller must be denied before any diagnostic USB request')
            except (CaptureError, KeyError, ValueError) as error:
                disabled[path] = errno.EPROTO
                probes.add(path)
                # Preserve the actual failed admission child. Do not issue a
                # privileged read after an invalid access-control prerequisite.
                probe['admission_error'] = str(error)
                return probe
            probes.add(path)
        row = collect_process(command(entry, disabled.get(path, 0)), stop,
                              credentials=dict(user=0, group=0, extra_groups=[], umask=0o077),
                              identity_reader=root_identity)
        if probe is not None:
            row['access_probe'] = probe
        try:
            value = decoded(row, entry, disabled.get(path, 0))
            if value['status'] == 'ERROR':
                disabled[path] = value['errno']
        except (CaptureError, KeyError, ValueError):
            # No automatic retry after malformed, stale, timed-out or killed
            # reads. Keep the original receipt; validation remains fail-closed.
            disabled[path] = errno.EPROTO
        return row

    return Watch(owners, phase, query_fn=query).start()


def validate(row, requested, *, failed=False):
    state = [dict(disabled=0, reads=0, errors=0, skipped=0, probed=False) for _ in (0, 1)]

    def check(receipt, entry, endpoint):
        current = state[endpoint]
        probe = receipt.get('access_probe')
        if not current['probed']:
            if (not isinstance(probe, dict) or probe.get('reaped') is not True
                    or probe['end_monotonic_ns'] > receipt['start_monotonic_ns']):
                raise CaptureError('first read requires separately reaped ordinary access denial')
            value = decoded(probe, entry, uid=1000)
            if value.get('status') != 'ERROR' or value['errno'] != errno.EACCES:
                raise CaptureError('actual ordinary access denial required')
            current['probed'] = True
        elif probe is not None:
            raise CaptureError('access probe cannot be duplicated or reset')
        value = decoded(receipt, entry, current['disabled'])
        if value['status'] == 'READ':
            current['reads'] += 1
            return True
        if value['status'] == 'ERROR':
            current['disabled'] = value['errno']
            current['errors'] += 1
        else:
            current['skipped'] += 1
        return False

    proof = _validate(row, requested, failed=failed, field=FIELD, receipt_check=check,
                      require_success=False)
    if proof is None:
        return None
    if not all(s['probed'] and s['reads']+s['errors'] > 0 for s in state):
        raise CaptureError('both endpoints need actual reads or explicit unsupported/error receipts')
    return dict(status='FAILED_ROLE_HCC_DIAGNOSTICS_ONLY' if failed else 'HCC_DIAGNOSTIC_COLLECTION_ONLY',
                samples=proof['samples'], endpoints=state, semantics_verified=False,
                credit_truth_qualified=False, physical_drain_qualified=False, performance_qualified=False)


def valid_summary(value):
    try:
        if (value['status'] != 'HCC_DIAGNOSTIC_COLLECTION_ONLY'
                or type(value['samples']) is not int or not 2 <= value['samples'] <= SPEC['max_pairs']*2
                or len(value['endpoints']) != 2
                or any(value[k] is not False for k in ('semantics_verified', 'credit_truth_qualified',
                                                      'physical_drain_qualified', 'performance_qualified'))):
            return False
        total = 0
        for state in value['endpoints']:
            if (set(state) != {'disabled','reads','errors','skipped','probed'}
                    or state['probed'] is not True
                    or any(type(state[k]) is not int for k in ('disabled','reads','errors','skipped'))
                    or not 0 <= state['errors'] <= 1 or min(state['reads'],state['skipped']) < 0
                    or state['reads']+state['errors'] < 1
                    or bool(state['errors']) != bool(state['disabled'])
                    or not 0 <= state['disabled'] < 4096
                    or state['skipped'] and not state['disabled']):
                return False
            total += state['reads']+state['errors']+state['skipped']
        return total == value['samples']
    except (KeyError, TypeError):
        return False
