# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in SDK READ Provider evidence, never a callback/Host/wire Engine.

The original CLI v2 oracle remains mandatory and unchanged. New SDK receipts
prove local binding/acceptance only; the real peer and paired USB prove this
finite empty/value/error exchange. No CLI Result is synthesized from SDK output.
"""
import copy
import errno
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from ws73_capture import CaptureError, packet_interval
from ws73_ssap_read_provider import MODES, _cleanup, _wire
from ws73_ssap_provider_owner_exit import CLOCK_CONTRACT, _clock_sample

PREFIX = 'ssap_sdk_read_provider'
TOKEN = 'ws73.ssap_sdk_read_provider=1'
VERSION = 1
STATUS = 'SDK_READ_PROVIDER_APPLICATION_PAIRED_USB'
PENDING = 'SDK_READ_PROVIDER_PENDING_PAIRED_USB'
COLLECTION = PREFIX+'_cases'
SUMMARY_KEY = PREFIX+'s'
EXTRA_TOOLS = ('/usr/share/sparklink/python/sparklink/service_provider.py',
               '/usr/share/sparklink/tools/ws73_ssap_sdk_read_provider.py')
BOUND = {'api','index','generation','property','started_ns','deadline_ns','returned_ns',
         'result','notification_result','notification_ready','local_binding_only'}
REQUEST = {'api','index','generation','token','request_id','lifetime','handle','epoch','level',
           'deadline_ns','property','maximum_bytes','local_tcid','remote_tcid','pi','observed_ns','observed_wall_ns'}
REPLY = {'api','token','current_token','api_called','status','value','deadline_ns',
         'started_ns','returned_ns','result','local_acceptance_only'}


def need(condition, message):
    if not condition: raise CaptureError(message)


def integer(value, *, zero=False):
    return type(value) is int and (0 if zero else 1) <= value < 2**64


def requested(args, *, passthrough=None):
    from ws73_ssap_read_provider import requested as retained
    selected = getattr(args, PREFIX+'_verify', False)
    if type(selected) is not bool: raise ValueError('explicit SDK Provider selector required')
    if selected and (not retained(args, passthrough=passthrough) or any(getattr(args, k, False)
        for k in ('ssap_provider_owner_exit_verify','ssap_provider_deadline_verify'))):
        raise ValueError('SDK Provider requires dedicated original CLI-v2/Owned ordinary61/4 gate')
    return selected


def boot_requested(tokens):
    from ws73_ssap_read_provider import boot_requested as retained
    if type(tokens) not in (list, tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    found = [t for t in tokens if t == 'ws73.'+PREFIX or t.startswith('ws73.'+PREFIX+'=')]
    if found not in ([], [TOKEN]) or found and (not retained(tokens) or any(
        t.startswith('ws73.ssap_provider_owner_exit') or t.startswith('ws73.ssap_provider_deadline') for t in tokens)):
        raise ValueError('one SDK Provider token with original CLI/Owned dependencies required')
    return bool(found)


def tool_records(root=Path('/')):
    from ws73_ssap_update_delivery import tool_records as retained
    records = retained(root)
    for name in EXTRA_TOOLS:
        path = root/name.lstrip('/')
        records[name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
    return records


def validate_tools(records, root, manifest):
    need(records == tool_records(root), 'fresh SDK Provider apps/library/module required')
    for name, record in records.items():
        actual = (root/name.lstrip('/')).resolve(strict=True)
        found = [p for p in manifest if Path(p['path']).resolve() == actual]
        need(len(found) == 1 and found[0]['sha256'] == record['sha256'], 'SDK Provider tool absent from build manifest')


def validate_inputs(package):
    from ws73_ssap_read_provider import validate_inputs as retained
    retained(package)
    for name in ('ws73_ssap_sdk_read_provider.py','ws73_ssap_provider_owner_exit.py'):
        path = Path(__file__).resolve().parent/name
        found = [p for p in package.get('inputs', []) if Path(p['path']).resolve() == path]
        need(len(found) == 1 and found[0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest(),
             'fresh exact SDK Provider verifier input required: '+name)


def validate_rows(rows, selected):
    from ws73_ssap_read_provider import validate_rows as retained
    need(type(selected) is bool and type(rows) is list, 'explicit SDK Provider rows required')
    if selected: retained(rows, True)
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX+'_required', False)) is bool and row.get(PREFIX+'_required', False) == selected,
             'SDK Provider request/row mismatch')
        if not selected:
            need(not any(k in row for k in (COLLECTION, PREFIX+'_version', PREFIX+'_status', PREFIX+'_tools')),
                 'unrequested SDK Provider evidence')
            continue
        need(type(row.get('phase')) is int and row['phase'] == phase
             and type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
             and row.get('ssap_read_provider_version') == 2 and len(row.get(COLLECTION, [])) == 1
             and row[COLLECTION][0].get('sender') == 0 and type(row.get(PREFIX+'_tools')) is dict,
             'one SDK Owner after original CLI v2 baseline per physical role required')
    if selected:
        need(len(rows) == 2 and len({(r['owners'][1]['owner']['index'],r['owners'][1]['owner']['generation']) for r in rows}) == 2,
             'two physical SDK Provider receivers required')


def json_rows(text, prefix, fields, count):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'duplicate SDK receipt JSON key')
            value[key] = item
        return value
    found = [json.loads(line[len(prefix)+2:], object_pairs_hook=unique)
             for line in text.splitlines() if line.startswith(prefix+': ')]
    need(len(found) == count and sum(l.startswith(prefix+':') for l in text.splitlines()) == count
         and all(type(v) is dict and set(v) == fields for v in found), 'exact '+prefix+' receipt sequence required')
    return found


def _wait_json(process, item, prefix, fields, count, deadline):
    from ws73_ssap_owned import wait_text
    _, text = wait_text(process, Path(item['output_files'][0]), '^'+prefix+r': (.+)$',
                        deadline/1e9, min_count=count, max_count=count)
    return json_rows(text, prefix, fields, count)[-1]


def execute(run, row):
    from ws73_application_client import ssap_commands, ssap_error_command
    from ws73_ssap_owned import publisher, wait_output, await_removed
    need(row.get('ssap_read_provider_required') is True and row.get('ssap_read_provider_version') == 2
         and len(row.get('ssap_read_provider_cases', [])) == 2, 'original CLI v2 baseline must finish first')
    row.update({PREFIX+'_required': True, PREFIX+'_version': VERSION, PREFIX+'_tools': tool_records(), COLLECTION: []})
    api = 'c' if row['phase'] == 0 else 'python'; peer_api = 'python' if api == 'c' else 'c'
    source, target = row['owners']
    with publisher(run, row, 0, 'allow', collection=COLLECTION, label='sdk-read-provider',
                   sdk_api=api, read_only=True, operations=1, read_provider=True) as (process, item):
        value = secrets.token_bytes(32)
        need(value.hex() != item['secret'], 'fresh dynamic SDK Provider value required')
        item.update(bytes=32, dynamic_value=value.hex(), prepared_wall_ns=time.time_ns(), steps=[])
        item['bind_before_monotonic_ns'] = time.monotonic_ns(); item['bind_before_wall_ns'] = time.time_ns()
        process.stdin.write('provider\n'); process.stdin.flush()
        item['bound'] = _wait_json(process, item, 'SdkReadProviderBound', BOUND, 1,
                                  item['bind_before_monotonic_ns']+5_000_000_000)
        item['bound_wall_ns'] = time.time_ns(); run.save()
        for ordinal, mode in enumerate(MODES, 1):
            step = dict(mode=mode, clock_contract=copy.deepcopy(CLOCK_CONTRACT), clock_before=_clock_sample())
            item['steps'].append(step); run.save()
            def provide(app, supervisor):
                step['read'] = app
                d = _wait_json(process, item, 'SdkReadProviderRequest', REQUEST, ordinal, supervisor)
                observed = time.monotonic_ns()
                need(integer(d['deadline_ns']) and observed < d['deadline_ns'] and process.poll() is None,
                     'live original SDK Provider callback required')
                callback = dict(prompt=d, observed_monotonic_ns=observed, observed_wall_ns=time.time_ns(),
                                publisher_pid=process.pid, supervisor_deadline_ns=supervisor)
                step['callback'] = callback
                step['reply_command'] = (f'provider-error p{d["token"]} FF' if mode == MODES[0]
                    else f'provide p{d["token"]} '+('-' if mode == MODES[1] else value.hex()))
                callback.update(reply_before_monotonic_ns=time.monotonic_ns(), reply_before_wall_ns=time.time_ns())
                need(callback['reply_before_monotonic_ns'] < min(d['deadline_ns'],supervisor), 'original reply deadline expired')
                process.stdin.write(step['reply_command']+'\n'); process.stdin.flush()
                callback.update(replied_monotonic_ns=time.monotonic_ns(), replied_wall_ns=time.time_ns())
                step['reply'] = _wait_json(process, item, 'SdkReadProviderReply', REPLY, ordinal,
                                          min(d['deadline_ns'],supervisor))
                run.save()
            args = ['ssap-read', source['object']['path'], str(item['handle'])]
            if mode == MODES[0]:
                step['read'] = ssap_error_command(run,row,source,args,errno.EIO,api=peer_api,after_start=provide)
            else:
                expected = b'' if mode == MODES[1] else value
                step['read'] = ssap_commands(run,row,[(source,args,expected)],api=peer_api,
                                             expected_size=len(expected),after_start=provide)[0]
            step['clock_after'] = _clock_sample(); run.save()
        item['quit_wall_ns'] = time.time_ns(); process.stdin.write('quit\n'); process.stdin.flush()
        wait_output(process, 2); need(process.returncode == 0, 'original SDK Provider explicit cleanup failed')
        item['owner_exit_wall_ns'] = time.time_ns()
        item['cleanup'] = await_removed(run,target,item['start'])
        item['retired_read'] = run.command([str(run.args.slctl),'--adapter',source['owner']['path'],
            'ssap-read',source['object']['path'],str(item['handle']),'0'],10,collection=PREFIX+'_retired')
        run.save()
    row[PREFIX+'_status'] = PENDING; run.save()


def _clocks(step):
    c = step['clock_contract']
    need(c == CLOCK_CONTRACT and type(c['version']) is int and type(c['usbmon_quantization_ns']) is int,
         'explicit same-guest stable-offset/usbmon quantization assumptions required')
    bounds = []
    for name in ('clock_before','clock_after'):
        s = step[name]
        need(type(s) is dict and set(s) == {'monotonic_before_ns','realtime_ns','monotonic_after_ns'}
             and all(integer(v) for v in s.values()) and s['monotonic_before_ns'] <= s['monotonic_after_ns'],
             'original ordered clock bracket required')
        bounds.append((s['realtime_ns']-s['monotonic_after_ns'],s['realtime_ns']-s['monotonic_before_ns']))
    before, after, app = step['clock_before'], step['clock_after'], step['read']
    need(before['realtime_ns'] <= app['start_wall_ns'] <= app['end_wall_ns'] <= after['realtime_ns']
         and before['monotonic_after_ns'] <= step['callback']['observed_monotonic_ns']
         <= step['reply']['returned_ns'] <= after['monotonic_before_ns'], 'clock brackets must contain actual SDK call/answer')
    lower, upper = max(x[0] for x in bounds), min(x[1] for x in bounds)
    need(lower <= upper, 'clock samples contradict stable-offset assumption')
    return lower, upper


def _packet_mono(packet, offset):
    fragments = packet['fragments']
    need(fragments and all(integer(f['wall_ns']) and f['wall_ns']%1000 == 0 for f in fragments),
         'original microsecond usbmon fragment timestamps required')
    return min(f['wall_ns'] for f in fragments)-offset[1], max(f['wall_ns']+999 for f in fragments)-offset[0]


def _case(row, item, matched):
    need(type(row.get('phase')) is int and row['phase'] in (0,1), 'exact original SDK Provider phase required')
    from ws73_application_client import (owned_arguments, application_environment, _ssap_process_receipt,
        ssap_receipt, ssap_error_receipt, authorization_context, AUTHORIZATION_CONTEXT_FIELDS)
    from ws73_ssap_owned import verify_output
    from ws73_ssap_command import _identity
    verify_output(item); _ssap_process_receipt(item,1000)
    from ws73_ssap_update_delivery import TOOLS
    records=row[PREFIX+'_tools']
    need(type(records) is dict and set(records)==set(TOOLS)|set(EXTRA_TOOLS)
         and all(type(v) is dict and set(v)=={'sha256','bytes'} and integer(v['bytes'])
                 and type(v['sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['sha256']) for v in records.values()),
         'bounded exact SDK tools provenance required')
    api = 'c' if row['phase'] == 0 else 'python'; peer_api = 'python' if api == 'c' else 'c'
    source, target = row['owners']; identities = [_identity(x) for x in row['owners']]
    need(type(item['sender']) is int and item['sender'] == 0 and type(item['target']) is int and item['target'] == 1
         and type(item['pid']) is int and item['pid'] > 0 and item['publisher_api'] == api
         and type(item['sdk_read_provider_contract_version']) is int and item['sdk_read_provider_contract_version'] == 1
         and item['operations'] == 1 and type(item['operations']) is int and item['policy'] == 'allow'
         and all(integer(item[k]) for k in ('start','end','handle','bytes'))
         and 0 < item['start'] < item['handle'] == item['end'] < 65536 and item['bytes'] == 32,
         'one original bounded READ-only SDK owner required')
    need(len({(i['index'],i['generation']) for i in identities}) == 2
         and len({(i['bus'],i['device']) for i in identities}) == 2, 'independent original controllers required')
    need(all(type(item[k]) is str and re.fullmatch('[0-9a-f]{32}',item[k]) for k in ('service','uuid'))
         and all(type(item[k]) is str and re.fullmatch('[0-9a-f]{64}',item[k]) for k in ('secret','dynamic_value'))
         and item['dynamic_value'] != item['secret'] and item['environment'] == application_environment()
         and item['args'] == owned_arguments(api,target,item['service'],item['uuid'],item['secret'],'allow',
                                            read_only=True,read_provider=True), 'exact SDK owner argv/environment/fresh value required')
    lines = item['stdout'].splitlines(); h = item['handle']
    registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only'
    bound = json_rows(item['stdout'],'SdkReadProviderBound',BOUND,1)[0]
    requests = json_rows(item['stdout'],'SdkReadProviderRequest',REQUEST,3)
    replies = json_rows(item['stdout'],'SdkReadProviderReply',REPLY,3)
    decision_fields = AUTHORIZATION_CONTEXT_FIELDS|{'allow','decision_ns','decision_wall_ns'}
    decisions = json_rows(item['stdout'],'SdkAuthorizationDecision',decision_fields,3)
    need(len(lines) == 13 and lines[:2] == [f'SdkOwnedAPI: api={api} client_closed=true',registration]
         and lines[2].startswith('SdkReadProviderBound: ')
         and lines[-1] == f'SdkOwnedRemoved: api={api} start={item["start"]}'
         and all([line.split(': ',1)[0] for line in lines[3+i*3:6+i*3]] ==
                 ['SdkAuthorizationDecision','SdkReadProviderRequest','SdkReadProviderReply'] for i in range(3)),
         'only exact SDK registration/bind/approval/request/local-reply/removal transcript allowed')
    need(bound == item['bound'] and all(integer(bound[k],zero=True) for k in ('index','generation','property')) and bound['api'] == api and bound['index'] == identities[1]['index']
         and bound['generation'] == identities[1]['generation'] and bound['property'] == h
         and bound['result'] == bound['notification_result'] == 0 and type(bound['result']) is int
         and type(bound['notification_result']) is int and bound['notification_ready'] is True
         and bound['local_binding_only'] is True
         and all(integer(bound[k]) for k in ('started_ns','deadline_ns','returned_ns'))
         and item['bind_before_monotonic_ns'] <= bound['started_ns'] <= bound['returned_ns'] < bound['deadline_ns']
         and 0 < bound['deadline_ns']-bound['started_ns'] <= 5_000_000_000, 'actual timely bind and notification acquisition required')
    need(type(item['steps']) is list and [x['mode'] for x in item['steps']] == list(MODES), 'ordered error/empty/value SDK sequence required')
    old_calls = [step['read'] for case in row['ssap_read_provider_cases'] for step in case['steps']]
    new_calls = [step['read'] for step in item['steps']]
    need(len(old_calls) == 6 and row['ssap_language_clients'] == old_calls+new_calls
         and len({app['pid'] for app in row['ssap_language_clients']}) == 9, 'exact old six plus new three actual SDK calls required')
    stamps = [item[k] for k in ('start_wall_ns','prepared_wall_ns','bind_before_wall_ns','bound_wall_ns')]
    exchanges = []; limits = []; outcomes = []
    for ordinal, (step,d,r,approval) in enumerate(zip(item['steps'],requests,replies,decisions,strict=True)):
        callback, app = step['callback'], step['read']
        need(all(integer(d[k],zero=True) for k in REQUEST-{'api'}) and d['api'] == api
             and all(d[k] for k in ('token','request_id','lifetime','epoch','deadline_ns','property','observed_ns','observed_wall_ns'))
             and tuple(d[k] for k in ('index','generation','lifetime','handle','property')) ==
                 (identities[1]['index'],identities[1]['generation'],identities[1]['lifetime'],identities[1]['handle'],h)
             and (d['level'],d['local_tcid'],d['remote_tcid'],d['pi'],d['maximum_bytes']) == (0,10,10,0,2042)
             and callback['prompt'] == d and callback['publisher_pid'] == item['pid'], 'original SDK request scope and finite basic MTU required')
        authorization_context({k:approval[k] for k in AUTHORIZATION_CONTEXT_FIELDS},api)
        need(approval['allow'] is True and approval['write'] is False and approval['value'] == ''
             and all(integer(approval[k]) for k in ('decision_ns','decision_wall_ns'))
             and all(approval[k] == d[k] for k in ('index','generation','request_id','lifetime','handle','epoch','level','deadline_ns','property','local_tcid','remote_tcid','pi'))
             and approval['decision_ns'] <= d['observed_ns'] and approval['decision_wall_ns'] <= d['observed_wall_ns'],
             'independent actual local authorization for this value request required')
        if ordinal:
            need(all(d[k] > requests[ordinal-1][k] for k in ('token','request_id'))
                 and all(d[k] == requests[0][k] for k in REQUEST-{'api','token','request_id','deadline_ns','observed_ns','observed_wall_ns'}),
                 'new tokens without changing physical/security scope required')
        value = bytes.fromhex(item['dynamic_value']) if ordinal == 2 else b''; status = 255 if ordinal == 0 else 0
        command = f'provider-error p{d["token"]} FF' if ordinal == 0 else f'provide p{d["token"]} '+(value.hex() if value else '-')
        need(r == step['reply'] and r['api'] == api and r['token'] == r['current_token'] == d['token']
             and r['api_called'] is True and r['status'] == status and type(r['status']) is int
             and r['value'] == value.hex() and r['result'] == 0 and type(r['result']) is int
             and r['deadline_ns'] == d['deadline_ns'] and r['local_acceptance_only'] is True
             and all(integer(r[k]) for k in ('token','current_token','deadline_ns','started_ns','returned_ns'))
             and step['reply_command'] == command, 'one real local SDK reply, not final callback/wire completion, required')
        need(app['api'] == peer_api and app['ssap_operation'] == 'ssap-read' and app['ssap_handle'] == h,
             'opposite actual language peer must read this dynamic property')
        if ordinal == 0:
            sdk = ssap_error_receipt(app,source,expected_errno=errno.EIO)
            origin, upper = sdk['call_ns'], min(sdk['returned_ns'],d['deadline_ns'])
            need(callback['supervisor_deadline_ns'] == app['ssap_supervisor_deadline_ns'], 'original SDK error supervisor required')
        else:
            ssap_receipt(app,source,expected_size=len(value))
            need(app['ssap_expected'] == value.hex(), 'actual peer must check complete dynamic value')
            origin, upper = app['ssap_release_monotonic_ns'], d['deadline_ns']
            need(callback['supervisor_deadline_ns'] == origin+7_000_000_000, 'original SDK positive supervisor required')
        times = [origin,approval['decision_ns'],d['observed_ns'],callback['observed_monotonic_ns'],
                 callback['reply_before_monotonic_ns'],r['started_ns'],r['returned_ns'],d['deadline_ns']]
        need(all(integer(x) for x in times) and times == sorted(times) and r['returned_ns'] < d['deadline_ns']
             and integer(callback['replied_monotonic_ns'])
             and callback['reply_before_monotonic_ns'] <= callback['replied_monotonic_ns'] < d['deadline_ns']
             and d['deadline_ns'] <= callback['supervisor_deadline_ns']
             and 0 < d['deadline_ns']-d['observed_ns'] <= 5_000_000_000, 'original authorization/value deadlines must not renew')
        stamps.extend([app['start_wall_ns'],callback['observed_wall_ns'],callback['reply_before_wall_ns'],
                       callback['replied_wall_ns'],app['end_wall_ns']])
        exchanges.append((app,b'\x09\x0b\xff\0' if ordinal == 0 else b'\x09\x03'+value,callback))
        limits.append((_clocks(step),origin,upper,d['observed_ns'],r['started_ns']))
        outcomes.append(dict(mode=step['mode'],local_status=status,bytes=len(value),peer_api=peer_api,
                             sdk_errno=errno.EIO if ordinal == 0 else 0,peer_validated=ordinal != 0))
    _cleanup(row,item); removed = item['retired_read']
    stamps.extend([item['quit_wall_ns'],item['owner_exit_wall_ns'],item['cleanup']['start_wall_ns'],
                   item['cleanup']['end_wall_ns'],removed['start_wall_ns'],removed['end_wall_ns'],item['end_wall_ns']])
    need(all(integer(x) for x in stamps) and stamps == sorted(stamps), 'original SDK owner/peer/cleanup chronology required')
    exchanges.append((removed,b'\x09\x0b\x04\0',None))
    wire, credit = _wire(row,item,matched,exchanges)
    for i in range(0,len(wire),2):
        request, response = wire[i:i+2]
        need(all(packet_interval(p['tx'])[1] <= packet_interval(p['rx'])[0] for p in (request,response))
             and packet_interval(request['rx'])[1] <= packet_interval(response['tx'])[0], 'two-end causal order required')
        if i < 6:
            offset, origin, upper, observed, answered = limits[i//2]
            need(all(_packet_mono(p,offset)[0] >= origin and _packet_mono(p,offset)[1] < observed for p in request.values()),
                 'actual request must follow this SDK call and precede Provider observation')
            need(all(_packet_mono(p,offset)[0] >= answered and _packet_mono(p,offset)[1] < upper for p in response.values()),
                 'actual response must follow local answer and precede original bounded completion')
    context = copy.deepcopy({k:row[k] for k in ('phase','owners','ssap_receipts','ssap_owned_required','ssap_owned',
        'ssap_read_provider_required','ssap_read_provider_version','ssap_read_provider_cases','ssap_language_clients')})
    return dict(status=STATUS,version=VERSION,sender=0,target=1,provider_api=api,peer_api=peer_api,
                value=item['dynamic_value'],outcomes=outcomes,wire=wire,tools=copy.deepcopy(row[PREFIX+'_tools']),
                context=context,case=copy.deepcopy(item)), credit


def corroborate(row, matched):
    need(type(row.get(PREFIX+'_required',False)) is bool, 'explicit SDK Provider request required')
    if row.get(PREFIX+'_required',False) is not True:
        need(not any(k in row for k in (COLLECTION,PREFIX+'_version',PREFIX+'_tools',PREFIX+'_status')), 'unrequested SDK Provider evidence')
        return [],{0:0,1:0}
    need(row.get('ssap_read_provider_required') is True and row.get('ssap_read_provider_version') == 2
         and type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
         and len(row.get(COLLECTION,[])) == 1, 'one SDK owner after original CLI v2 per role required')
    proof, credit = _case(row,row[COLLECTION][0],matched)
    return [proof],credit


def valid_summary(proof, *, version=VERSION):
    from ws73_ssap_read_provider import valid_summary as retained
    try:
        if type(version) is not int or version != VERSION or not retained(proof,version=2): return False
        receivers=set();values=set()
        for phase,row in enumerate(proof['proofs']):
            items=row[SUMMARY_KEY]
            need(type(row['phase']) is int and row['phase']==phase and len(items)==1, 'two exact SDK Provider phase proofs required')
            item=items[0];context,case=item['context'],item['case']
            need(type(item['version']) is int and item['version']==VERSION
                 and context['phase']==phase and context['owners']==row['owners'] and len(item['wire'])==8
                 and context['ssap_read_provider_cases']==[p['case'] for p in row['ssap_read_providers']], 'retained CLI proof/context must match')
            packets=[copy.deepcopy(leg[side]) for leg in item['wire'] for side in ('tx','rx')]
            def matched(owner,direction,frame,window):
                key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
                found=[p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data'))==key
                       and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
                need(len(found)==1,'one exact retained SDK Provider USB leg required')
                packets.remove(found[0]);return found[0]
            context=copy.deepcopy(context);context[PREFIX+'_tools']=item['tools']
            rebuilt,_=_case(context,case,matched)
            need(not packets and rebuilt==item,'SDK Provider summary must replay exact original evidence')
            receiver=row['owners'][1]['owner'];receivers.add((receiver['index'],receiver['generation']));values.add(item['value'])
        return len(receivers)==len(values)==2
    except (KeyError,AttributeError,IndexError,TypeError,ValueError,StopIteration): return False


def valid_manifest(record):
    from ws73_ssap_read_provider import valid_manifest as retained
    try:
        selected=record.get(PREFIX+'_requested',False)
        if type(selected) is not bool or boot_requested([t for arg in record.get('qemu_args',[]) for t in arg.split()])!=selected: return False
        proof=record.get('channel_socket_corroboration',{})
        if not selected:
            return (record.get(PREFIX+'_acceptance',False) is False
                    and not any(PREFIX+suffix in record for suffix in ('_version','_verifier','_tools'))
                    and not any(SUMMARY_KEY in row for row in proof.get('proofs',[])))
        verifier=record.get(PREFIX+'_verifier',{})
        if (type(verifier) is not dict or set(verifier)!={'path','sha256','bytes'}
                or type(verifier['path']) is not str or Path(verifier['path']).name!='ws73_ssap_sdk_read_provider.py'
                or not integer(verifier['bytes']) or type(verifier['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',verifier['sha256'])): return False
        for row in proof.get('proofs',[]):
            for item in row.get(SUMMARY_KEY,[]):
                if item['tools'][EXTRA_TOOLS[-1]]!={k:verifier[k] for k in ('sha256','bytes')}: return False
        return (type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version']==VERSION
                and record.get(PREFIX+'_acceptance') is True and record.get('ssap_read_provider_version')==2
                and retained(record) and valid_summary(proof,version=record[PREFIX+'_version']))
    except (KeyError,AttributeError,IndexError,TypeError,ValueError): return False
