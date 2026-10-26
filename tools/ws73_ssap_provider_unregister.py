# SPDX-License-Identifier: GPL-2.0-only
"""Pending SDK withdrawal, distinct from owner death and original expiry.

Uses the existing SDK command, peer supervisor, capture and sole daemon Engine.
Local withdrawal receipts alone never qualify real peer/guard delivery.
"""
import copy
import errno
import hashlib
from pathlib import Path
import time

from ws73_capture import CaptureError, packet_interval
from ws73_ssap_sdk_read_provider import need, integer, json_rows, tool_records, _wait_json
from ws73_ssap_provider_owner_exit import (
    CLOCK_CONTRACT, _clock_sample, _clock_bounds, _remaining, _sdk_pending,
    _registration, execute_pending_case, corroborate_peer_guard,
)

PREFIX = 'ssap_provider_unregister'
TOKEN = 'ws73.'+PREFIX+'=1'
VERSION = 1
STATUS = 'SDK_PROVIDER_UNREGISTER_APPLICATION_PAIRED_USB'
PENDING = 'SDK_PROVIDER_UNREGISTER_PENDING_PAIRED_USB'
RECEIPT = {'api','token','property','original_deadline_ns','deadline_ns','started_ns','returned_ns',
           'result','info_preserved','notification_fd_alive','reply_started_ns','reply_returned_ns',
           'reply_result','local_observation_only'}
INCOMPATIBLE = ('ssap_provider_owner_exit_verify','ssap_provider_deadline_verify','ssap_sdk_read_provider_verify')


def requested(args, *, passthrough=None):
    from ws73_ssap_read_provider import requested as baseline
    selected = getattr(args, PREFIX+'_verify', False)
    if type(selected) is not bool: raise ValueError('explicit SDK unregister selector required')
    if selected and (not baseline(args, passthrough=passthrough)
                     or any(getattr(args, key, False) for key in INCOMPATIBLE)):
        raise ValueError('pending unregister requires a dedicated original CLI-v2/Owned gate')
    return selected


def boot_requested(tokens):
    from ws73_ssap_read_provider import boot_requested as baseline
    if type(tokens) not in (list,tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original boot tokens required')
    found = [t for t in tokens if t == 'ws73.'+PREFIX or t.startswith('ws73.'+PREFIX+'=')]
    if found not in ([],[TOKEN]) or found and (not baseline(tokens) or any(
            t.startswith('ws73.'+key.removesuffix('_verify')) for key in INCOMPATIBLE for t in tokens)):
        raise ValueError('one exact unregister selector and original baseline required')
    return bool(found)


def validate_inputs(package):
    from ws73_ssap_provider_owner_exit import validate_inputs as baseline
    baseline(package)
    path = Path(__file__).resolve()
    found = [p for p in package.get('inputs',[]) if Path(p['path']).resolve() == path]
    need(len(found) == 1 and found[0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest(),
         'fresh exact unregister verifier required')


def validate_rows(rows, selected):
    from ws73_ssap_read_provider import validate_rows as baseline
    need(type(rows) is list and type(selected) is bool, 'explicit unregister rows required')
    if selected: baseline(rows, True)
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX+'_required',False)) is bool and row.get(PREFIX+'_required',False) == selected,
             'unregister selection mismatch')
        if not selected:
            need(not any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'), 'unrequested unregister evidence')
            continue
        need(type(row.get('phase')) is int and row['phase'] == phase
             and type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
             and len(row.get(PREFIX+'_cases',[])) == len(row.get(PREFIX+'_guards',[])) == 1
             and row[PREFIX+'_cases'][0]['guard'] == row[PREFIX+'_guards'][0]
             and row.get('ssap_read_provider_version') == 2
             and not any(row.get(k.removesuffix('_verify')+'_required',False) for k in INCOMPATIBLE),
             'one pending SDK unregister per original role required')
    if selected:
        need(len(rows) == 2 and len({(r['owners'][1]['owner']['index'],r['owners'][1]['owner']['generation']) for r in rows}) == 2,
             'both physical Provider receivers required')


def withdrawal_receipt(row, item, text):
    """Validate original SDK output, never synthesize a successful RPC receipt."""
    lines = text.splitlines()
    need(len(lines) == 6 and lines[5].startswith('SdkReadProviderUnregistered: '), 'exact pending then withdrawn transcript required')
    request = _sdk_pending(row, item, '\n'.join(lines[:5])+'\n')
    result = json_rows(text, 'SdkReadProviderUnregistered', RECEIPT, 1)[0]
    need(result['api'] == request['api'] and result['token'] == request['token']
         and result['property'] == request['property'] and result['original_deadline_ns'] == request['deadline_ns'],
         'withdrawal must belong to the original SDK request')
    need(all(integer(result[k]) for k in ('token','property','original_deadline_ns','deadline_ns','started_ns',
                 'returned_ns','reply_started_ns','reply_returned_ns'))
         and type(result['result']) is int and result['result'] == 0
         and type(result['reply_result']) is int and result['reply_result'] == -errno.ESHUTDOWN
         and all(result[k] is True for k in ('info_preserved','notification_fd_alive','local_observation_only')),
         'actual successful unregister, retained views and ESHUTDOWN required')
    need(request['observed_ns'] <= item['unregister_before_monotonic_ns'] <= result['started_ns']
         <= result['returned_ns'] <= result['reply_started_ns'] <= result['reply_returned_ns']
         < result['deadline_ns'] <= request['deadline_ns']
         and result['reply_returned_ns'] < item['callback']['unregister_deadline_ns'],
         'withdrawal and old reply must finish within all original deadlines')
    return request, result


def _unregister(run, row, process, item, app, supervisor_deadline_ns):
    from ws73_ssap_owned import wait_text, await_removed
    item['read'] = app; run.save()
    _, text = wait_text(process, Path(item['output_files'][0]), r'^SdkReadProviderRequest: (.+)$',
        min(app['ssap_error_deadline_ns'], supervisor_deadline_ns)/1e9, max_count=1)
    data = _sdk_pending(row, item, text); observed = time.monotonic_ns()
    need(process.poll() is None and data['observed_ns'] <= observed < data['deadline_ns'] <= observed+5_000_000_000,
         'live pending SDK request before withdrawal required')
    deadline = min(data['deadline_ns'], app['ssap_error_deadline_ns'], supervisor_deadline_ns)
    item['callback'] = dict(prompt=data, observed_monotonic_ns=observed, observed_wall_ns=time.time_ns(),
        publisher_pid=process.pid, supervisor_deadline_ns=supervisor_deadline_ns, unregister_deadline_ns=deadline)
    item['pending_stdout'] = text
    item['clock_contract'] = copy.deepcopy(CLOCK_CONTRACT); item['clock_before'] = _clock_sample()
    item.update(unregister_before_wall_ns=time.time_ns(), unregister_before_monotonic_ns=time.monotonic_ns())
    run.save(); _remaining(deadline)
    process.stdin.write('provider-unregister\n'); process.stdin.flush()
    receipt = _wait_json(process, item, 'SdkReadProviderUnregistered', RECEIPT, 1, deadline)
    item['withdrawn_stdout'] = Path(item['output_files'][0]).read_text()
    _, checked = withdrawal_receipt(row, item, item['withdrawn_stdout'])
    need(checked == receipt and process.poll() is None, 'withdrawn Provider process must stay alive')
    item['unregistered'] = receipt
    item.update(unregister_observed_monotonic_ns=time.monotonic_ns(), unregister_observed_wall_ns=time.time_ns())
    _remaining(deadline); run.save()
    item['cleanup'] = await_removed(run, row['owners'][1], item['start'], deadline_ns=deadline)
    item['cleanup_completed_monotonic_ns'] = time.monotonic_ns()
    _remaining(deadline); run.save()


def _finish(run, row, process, item):
    from ws73_ssap_owned import wait_output
    need(process.poll() is None, 'Provider must survive peer refusal, retired read and independent guard')
    item.update(provider_alive_after_guard_wall_ns=time.time_ns(), quit_wall_ns=time.time_ns())
    run.save(); process.stdin.write('quit\n'); process.stdin.flush(); wait_output(process, 2)
    need(process.returncode == 0, 'withdrawn SDK process must exit normally after guard delivery')
    item['owner_exit_wall_ns'] = time.time_ns(); run.save()


def execute(run, row):
    need(row.get('ssap_read_provider_version') == 2 and len(row.get('ssap_read_provider_cases',[])) == 2,
         'original CLI Provider baseline must finish before SDK withdrawal')
    row.update({PREFIX+'_required':True, PREFIX+'_version':VERSION, PREFIX+'_tools':tool_records(),
                PREFIX+'_cases':[], PREFIX+'_guards':[]}); run.save()
    execute_pending_case(run, row, PREFIX, 'provider-unregister', _unregister, finish=_finish)
    row[PREFIX+'_status'] = PENDING; run.save()


def _case(row, item, matched, packets):
    from ws73_application_client import ssap_error_receipt
    from ws73_ssap_update_delivery import TOOLS
    from ws73_ssap_sdk_read_provider import EXTRA_TOOLS
    from ws73_ssap_command import _identity
    import re
    records = row[PREFIX+'_tools']
    need(type(records) is dict and set(records) == set(TOOLS)|set(EXTRA_TOOLS)
         and all(type(v) is dict and set(v) == {'sha256','bytes'} and integer(v['bytes'])
                 and type(v['sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['sha256']) for v in records.values()),
         'original SDK tool identities required')
    _registration(row,item,sdk=True)
    data, result = withdrawal_receipt(row,item,item['withdrawn_stdout'])
    need(item['unregistered'] == result and item['pending_stdout'] == '\n'.join(item['withdrawn_stdout'].splitlines()[:5])+'\n'
         and item['stdout'] == item['withdrawn_stdout']+f"SdkOwnedClosedExit: api={data['api']} start={item['start']}\n"
         and type(item['exit']) is int and item['exit'] == 0
         and not any(k in item for k in ('kill_before_wall_ns','owner_exit_monotonic_ns','reply_command','steps')),
         'original successful withdrawal followed only by normal process exit required')
    ids = [_identity(o) for o in row['owners']]
    need(len({(i['index'],i['generation']) for i in ids}) == len({(i['bus'],i['device']) for i in ids}) == 2,
         'two physical original controller identities required')
    cb, app, guard = item['callback'],item['read'],item['guard'];source = row['owners'][0]
    need(cb['prompt'] == data and cb['publisher_pid'] == item['pid']
         and all(guard[k] != item[k] for k in ('pid','handle','service','uuid','secret'))
         and data['observed_ns'] <= cb['observed_monotonic_ns']
         and data['observed_wall_ns'] <= cb['observed_wall_ns'], 'distinct live guard and original SDK pending identity required')
    receipt = ssap_error_receipt(app,source,expected_errno=errno.EIO)
    deadline = min(data['deadline_ns'],receipt['deadline_ns'],app['ssap_supervisor_deadline_ns'])
    need(cb['supervisor_deadline_ns'] == app['ssap_supervisor_deadline_ns'] and cb['unregister_deadline_ns'] == deadline
         and app['api'] == ('c','python')[row['phase']] and app['ssap_operation'] == 'ssap-read'
         and app['ssap_handle'] == item['handle'], 'original peer operation and deadlines required')
    times = [app['start_monotonic_ns'],receipt['call_ns'],cb['observed_monotonic_ns'],item['unregister_before_monotonic_ns'],
             result['started_ns'],result['returned_ns'],result['reply_started_ns'],result['reply_returned_ns'],
             item['unregister_observed_monotonic_ns'],item['cleanup_completed_monotonic_ns']]
    need(all(integer(t) for t in times) and times == sorted(times) and times[-1] < deadline
         and item['unregister_before_monotonic_ns'] <= receipt['returned_ns'] < deadline,
         'withdrawal, cleanup and actual peer return within original deadlines required')
    stamps = [guard['start_wall_ns'],guard['registered_wall_ns'],item['start_wall_ns'],item['bound_wall_ns'],app['start_wall_ns'],
              cb['observed_wall_ns'],item['unregister_before_wall_ns'],item['unregister_observed_wall_ns'],
              item['cleanup']['start_wall_ns'],item['cleanup']['end_wall_ns'],app['end_wall_ns'],
              item['retired_read']['start_wall_ns'],item['retired_read']['end_wall_ns'],guard['read']['start_wall_ns'],
              guard['read']['end_wall_ns'],guard['alive_after_read_wall_ns'],item['provider_alive_after_guard_wall_ns'],
              item['quit_wall_ns'],item['owner_exit_wall_ns'],item['end_wall_ns'],guard['quit_wall_ns'],
              guard['owner_exit_wall_ns'],guard['cleanup']['start_wall_ns'],guard['cleanup']['end_wall_ns'],guard['end_wall_ns']]
    need(all(integer(t) for t in stamps) and stamps == sorted(stamps), 'original withdrawal/peer/guard/normal-exit chronology required')
    offset,_ = _clock_bounds(item,action='unregister')
    response,wire,credit = corroborate_peer_guard(row,item,matched,packets,receipt,deadline,offset,item['unregister_before_wall_ns'])
    context = {k:copy.deepcopy(row[k]) for k in ('phase','owners','ssap_receipts',PREFIX+'_tools')}
    return dict(status=STATUS,version=VERSION,sender=0,target=1,api=app['api'],sdk_errno=receipt['errno'],
                peer_error=response[2],wire=wire,context=context,case=copy.deepcopy(item)),credit


def corroborate(row, matched, packets):
    if row.get(PREFIX+'_required',False) is not True:
        need(not any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'), 'unrequested unregister evidence')
        return [],{0:0,1:0}
    need(type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
         and row.get('ssap_read_provider_version') == 2
         and len(row.get(PREFIX+'_cases',[])) == len(row.get(PREFIX+'_guards',[])) == 1
         and row[PREFIX+'_cases'][0]['guard'] == row[PREFIX+'_guards'][0], 'one original pending withdrawal and guard required')
    proof,credit = _case(row,row[PREFIX+'_cases'][0],matched,packets)
    return [proof],credit


def verify_business_after(case, legs):
    """Additional ordering gate; outer channel oracle validates payload and peers."""
    need(type(legs) is list and len(legs) == 8, 'four original ordinary request/reply rounds required')
    barrier = case['guard']['end_wall_ns']
    need(all(packet_interval(leg[side])[0] > barrier for leg in legs for side in ('tx','rx')),
         'ordinary business must occur after withdrawn Provider and guard cleanup')


def valid_summary(proof):
    try:
        rows = proof['proofs'];need(type(rows) is list and len(rows) == 2,'both original phases required')
        receivers = set()
        for phase,row in enumerate(rows):
            need(type(row['phase']) is int and row['phase'] == phase and len(row[PREFIX]) == 1,'original two phase proof required')
            item = row[PREFIX][0];context,case = item['context'],item['case']
            need(type(item['version']) is int and item['version'] == VERSION and context['phase'] == phase
                 and context['owners'] == row['owners'] and len(item['wire']) == 6,'original unregister context required')
            owner = row['owners'][1]['owner'];receivers.add((owner['index'],owner['generation']))
            packets = [copy.deepcopy(leg[side]) for leg in item['wire'] for side in ('tx','rx')]
            def matched(owner,direction,frame,window):
                key = (owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
                found = [p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data')) == key
                         and window['start_wall_ns'] <= p['wall_ns'] <= window['end_wall_ns']]
                need(len(found) == 1,'one retained paired USB leg required');packets.remove(found[0]);return found[0]
            verify_business_after(case,row['legs'])
            rebuilt,_ = _case(context,case,matched,packets)
            need(not packets and rebuilt == item,'entire proof must reconstruct from original evidence')
        return len(receivers) == 2
    except (KeyError,AttributeError,TypeError,ValueError):
        return False


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested',False)
        if type(selected) is not bool or boot_requested([t for arg in record.get('qemu_args',[]) for t in arg.split()]) != selected:
            return False
        proof = record.get('channel_socket_corroboration',{})
        if not selected:
            return record.get(PREFIX+'_acceptance',False) is False and PREFIX+'_version' not in record and not any(PREFIX in r for r in proof.get('proofs',[]))
        from ws73_ssap_read_provider import valid_manifest as baseline
        return (type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version'] == VERSION
                and record.get(PREFIX+'_acceptance') is True and record.get('ssap_read_provider_version') == 2
                and baseline(record) and valid_summary(proof))
    except (KeyError,AttributeError,TypeError,ValueError):
        return False
