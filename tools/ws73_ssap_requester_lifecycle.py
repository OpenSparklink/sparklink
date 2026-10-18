# SPDX-License-Identifier: GPL-2.0-only
"""Actual requester death/old reply drain, using the sole existing SSAP path.

The real owner prompt and terminated process are the barriers. Software busy
does not establish that every internal cancellation task has already run. The
gate proves the observed old-slot obligation and independently completed new
request, never rollback, credit refund or a universal reuse barrier.
"""
from pathlib import Path
import json
import re
import time

from ws73_capture import CaptureError
from ws73_ssap_owned import publisher, value_snapshot, wait_text
from ws73_ssap_owner_lifecycle import check_prompt, prompt, timeout_arguments
from ws73_application_client import application_environment, process_identity

STATUS = 'REQUESTER_EXIT_OLD_REPLY_AND_HELD_BUSINESS_EVIDENCE_PENDING'
BUSY = 'SSAP busy/not-ready/expired'


def killed_receipt(command, api, source, item):
    if (command['args'] != timeout_arguments(api, source, item)
            or command.get('environment') != application_environment()
            or command['exit'] != -9 or command['stderr']):
        raise CaptureError('actual killed public SDK requester required')
    lines = command['stdout'].splitlines()
    if len(lines) != 1:
        raise CaptureError('dead requester must have call receipt and no terminal success/error')
    call = json.loads(lines[0])
    if (set(call) != {'stage','api','deadline_ns','call_ns','client_closed'}
            or call['stage'] != 'ssap_call' or call['api'] != api or call['client_closed'] is not True
            or any(type(call[k]) is not int for k in ['deadline_ns','call_ns'])
            or not 0 < call['deadline_ns']-call['call_ns'] <= 5_000_000_000):
        raise CaptureError('actual immutable SDK call deadline required')
    identity = command['credentials']
    if (identity['uids'] != [1000]*4
            or set(identity['capabilities']) != {'CapEff','CapPrm','CapAmb','CapInh'}
            or any(int(v,16) for v in identity['capabilities'].values())):
        raise CaptureError('ordinary cap-zero actual requester required')
    return call


def read_reply(command,source,guard,program):
    """Current real CLI selects the adapter before printing the peer value."""
    args=[program,'--adapter',source['owner']['path'],'ssap-read',source['object']['path'],str(guard['handle']),'0']
    expected=[f'Selected {source["owner"]["path"]}',
        f'SsapPeerValue: operation=ssap-read path={source["object"]["path"]} handle={guard["handle"]} value={guard["secret"]}']
    if command['args']!=args or command['exit'] or command['stderr'] or command['stdout'].splitlines()!=expected:
        raise CaptureError('exact CLI selected identity and independently validated other-owner value required')


def execute(run, row, business):
    row['ssap_requester_lifecycle_required'] = True
    row['ssap_requester_lifecycle'] = []
    sender = row['phase'] % 2
    source, target = row['owners'][sender], row['owners'][1-sender]
    api = 'c' if sender == 0 else 'python'
    with publisher(run,row,sender,'allow',collection='ssap_requester_lifecycle',label='requester-guard') as (guard,g):
        g['case'] = 'guard'
        with publisher(run,row,sender,'ask',collection='ssap_requester_lifecycle',label='requester-exit') as (owner,i):
            i.update(case='requester-exit',api=api)
            def read_guard():
                return run.command([str(run.args.slctl),'--adapter',source['owner']['path'],
                    'ssap-read',source['object']['path'],str(g['handle']),'0'],
                    max(.001,min(2,observation_deadline-time.monotonic())),collection='ssap_requester_commands')
            def barrier(process, record):
                nonlocal observation_deadline
                i['killed_write']=record  # Retain the call even if its barrier fails.
                record['credentials'],record['process_status'] = process_identity(process.pid)
                event = prompt(owner,i,target,1)
                checked = check_prompt(event,target,i)
                if process.poll() is not None:
                    raise CaptureError('requester returned before actual owner barrier')
                process.kill()
                i['requester_exit'] = process.wait(timeout=2)
                i['requester_exit_wall_ns'] = time.time_ns()
                i['requester_exit_monotonic_ns'] = time.monotonic_ns()
                observation_deadline = time.monotonic()+2
                i['busy_read'] = read_guard()
                if not i['busy_read']['exit'] or BUSY not in i['busy_read']['stderr']:
                    raise CaptureError('old admitted request slot must remain busy after requester death')
                value_snapshot(owner,i,i['secret'])
                i['business_window'] = dict(start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns())
                run.save()
                # Conservatively stay inside the same SDK five seconds too;
                # no new business/collector budget may extend the held call.
                business(min(checked['deadline']/1e9,(record['start_monotonic_ns']+4_500_000_000)/1e9))
                i['business_window'].update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns())
                if time.monotonic_ns() >= checked['deadline']:
                    raise CaptureError('business did not complete inside original peer prompt deadline')
                i['approval'] = dict(token=checked['token'],wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
                owner.stdin.write(f'yes {checked["token"]}\n');owner.stdin.flush()
                pattern = rf'^SsapAuthorizationDecision: request={checked["request"]} property={i["handle"]} write=true security=0 approved=true; local policy only$'
                wait_text(owner,Path(i['output_files'][0]),pattern,min(time.monotonic()+2,checked['deadline']/1e9))
                observation_deadline = min(time.monotonic()+2,checked['deadline']/1e9)
                i['next_read_attempts'] = []
                for _ in range(16):
                    if time.monotonic() >= observation_deadline:
                        raise CaptureError('old physical reply/new request observation deadline')
                    read = read_guard();i['next_read_attempts'].append(read);run.save()
                    if not read['exit']:
                        read_reply(read,source,g,str(run.args.slctl))
                        break
                    if BUSY not in read['stderr']:
                        raise CaptureError('new requester failed after old physical reply')
                    time.sleep(.01)
                else:
                    raise CaptureError('finite new-request retry budget exhausted')
                value_snapshot(owner,i,i['value'])
                value_snapshot(guard,g,g['secret'])
                run.save()
            observation_deadline = 0
            i['killed_write'] = run.command(timeout_arguments(api,source,i),10,
                collection='ssap_requester_commands',on_started=barrier,environment=application_environment())
            i['call_receipt'] = killed_receipt(i['killed_write'],api,source,i)
    row['ssap_requester_lifecycle_status'] = STATUS
    run.save()


def corroborate(row, matched, sdus):
    if not row.get('ssap_requester_lifecycle_required'):
        return [],{0:0,1:0}
    items = row.get('ssap_requester_lifecycle',[])
    if (row.get('ssap_requester_lifecycle_status') != STATUS or len(items) != 2
            or [v.get('case') for v in items] != ['guard','requester-exit']):
        raise CaptureError('completed requester exit and independent guard required')
    g,i = items
    s,t = row['phase']%2,1-row['phase']%2
    source,target = row['owners'][s],row['owners'][t]
    api = 'c' if s == 0 else 'python'
    fresh = set()
    for item,policy in [(g,'allow'),(i,'ask')]:
        expected = [row['ssap_receipts'][0]['args'][0],'--adapter',target['owner']['path'],
                    'ssap-serve',item['service'],item['uuid'],'5','36',item['secret'],policy]
        if (item['args'] != expected or item['policy'] != policy or item['sender'] != s or item['target'] != t
                or item['credentials']['uids'] != [1000]*4 or any(int(v,16) for v in item['credentials']['capabilities'].values())
                or item['exit'] != -9 or item['stderr']
                or not item['start'] <= item['handle'] <= item['end']):
            raise CaptureError('original independent ordinary live owner required')
        registration = f'SsapOwnedService: start={item["start"]} end={item["end"]} property={item["handle"]}; local registration only'
        if item['stdout'].splitlines().count(registration) != 1:
            raise CaptureError('actual owned registration receipt required')
        for k,n in [('secret',32),('value',32),('uuid',16),('service',16)]:
            raw=bytes.fromhex(item[k])
            if len(raw)!=n or raw in fresh:raise CaptureError('fresh requester case identity/value required')
            fresh.add(raw)
    c=i['killed_write'];call=killed_receipt(c,api,source,i)
    if i['api'] != api or i['call_receipt'] != call or i['requester_exit'] != -9:
        raise CaptureError('original actual killed requester call receipt required')
    events=i.get('prompt_events',[])
    if len(events)!=1:raise CaptureError('one actual old-request prompt required')
    e=events[0];p=check_prompt(e,target,i);window=i['business_window'];a=i['approval']
    if (a['token']!=p['token'] or not c['start_monotonic_ns']<=call['call_ns']<=e['monotonic_ns']<i['requester_exit_monotonic_ns']
            <=window['start_monotonic_ns']<=window['end_monotonic_ns']<a['monotonic_ns']<min(p['deadline'],call['deadline_ns'])
            or not c['start_wall_ns']<=e['wall_ns']<i['requester_exit_wall_ns']<=window['start_wall_ns']<=window['end_wall_ns']<a['wall_ns']):
        raise CaptureError('actual prompt,requester exit,business,approval inside original deadlines required')
    from ws73_ssap_owner_lifecycle import PROMPT
    if re.findall(PROMPT,i['stdout'],re.M)!=[tuple(e['fields'])]:
        raise CaptureError('sealed original prompt transcript differs')
    decision=rf'^SsapAuthorizationDecision: request={p["request"]} property={i["handle"]} write=true security=0 approved=true; local policy only$'
    if len(re.findall(decision,i['stdout'],re.M))!=1:
        raise CaptureError('exact original policy approval required;not peer or app success')
    attempts=i.get('next_read_attempts',[])
    if not 1<=len(attempts)<=16:raise CaptureError('bounded new-request attempts required')
    read_args=[row['ssap_receipts'][0]['args'][0],'--adapter',source['owner']['path'],
               'ssap-read',source['object']['path'],str(g['handle']),'0']
    failed=[i['busy_read'],*attempts[:-1]]
    frame=(b'\x0a\0\x05\0\x08\x03'+g['handle'].to_bytes(2,'little')+b'\0').hex()
    for command in [*failed,attempts[-1]]:
        if command['args']!=read_args or not c['start_wall_ns']<=command['start_wall_ns']<=command['end_wall_ns']<=c['end_wall_ns']:
            raise CaptureError('actual same-lifetime new read command interval required')
    for command in failed:
        if not command['exit'] or BUSY not in command['stderr']:
            raise CaptureError('all unadmitted attempts must preserve actual busy refusal')
        if any(d['data']==frame and command['start_wall_ns']<=d['wall_ns']<=command['end_wall_ns'] for d in sdus):
            raise CaptureError('busy software request reached physical wire')
    if not i['requester_exit_wall_ns']<=i['busy_read']['start_wall_ns']<=i['busy_read']['end_wall_ns']<window['start_wall_ns']:
        raise CaptureError('busy old obligation must be observed after actual process death andbefore business')
    last=attempts[-1]
    read_reply(last,source,g,row['ssap_receipts'][0]['args'][0])
    if last['start_wall_ns']<a['wall_ns']:
        raise CaptureError('independent new-request peer value validation required')
    snapshots=i.get('value_snapshots',[])
    if (len(snapshots)!=2 or [x['value'] for x in snapshots]!=[i['secret'],i['value']]
            or any(x['handle']!=i['handle'] or x['ordinal']!=n for n,x in enumerate(snapshots,1))
            or not snapshots[0]['end_wall_ns']<=window['start_wall_ns'] or snapshots[1]['start_wall_ns']<last['end_wall_ns']):
        raise CaptureError('actual unchanged-before,committed-after owner value observations required')
    for item,values in [(i,[i['secret'],i['value']]),(g,[g['secret']])]:
        if re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$',item['stdout'],re.M)!=[(str(item['handle']),v) for v in values]:
            raise CaptureError('owner-side sealed application snapshots required')
    apps=row.get('applications',[])
    if len(apps)!=2 or any(v['exit'] or not window['start_wall_ns']<=v['start_wall_ns']<=v['end_wall_ns']<=window['end_wall_ns'] for v in apps):
        raise CaptureError('both existing business applications must finish while old prompt remains held')
    wire=[];credit={0:0,1:0}
    def leg(sender,receiver,pdu,interval):
        raw=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        value=dict(tx=matched(row['owners'][sender],'out',raw,interval),rx=matched(row['owners'][receiver],'in',raw,interval))
        wire.append(value);credit[sender]+=1;return value
    request=leg(s,t,b'\x0d\x23'+i['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(i['value']),c)
    old=leg(t,s,b'\x0e\x03'+i['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(i['value']),c)
    if request['rx']['wall_ns']>e['wall_ns'] or old['tx']['wall_ns']<a['wall_ns'] or old['rx']['wall_ns']<i['requester_exit_wall_ns']:
        raise CaptureError('original reply must actually cross both USB ends after requester death andpolicy release')
    new_request=leg(s,t,b'\x08\x03'+g['handle'].to_bytes(2,'little')+b'\0',last)
    leg(t,s,b'\x09\x03'+bytes.fromhex(g['secret']),last)
    if new_request['tx']['wall_ns']<old['rx']['wall_ns']:
        raise CaptureError('new request submitted before old response drained')
    return [dict(sender=s,target=t,api=api,requester_exit=-9,busy_without_wire=True,
                 late_original_reply_drained=True,peer_value_committed=True,business_while_prompt_held=row['rounds'],wire=wire,
                 scope='Finite requester process death/old physical response/new independent read;not rollback,precise cancellation linearization,NOCPtruth,reuse,security or recovery proof')],credit


def valid_summary(proof):
    if not isinstance(proof,dict) or proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED':return False
    phases=proof.get('proofs')
    if not isinstance(phases,list) or len(phases)!=2:return False
    total=0
    for phase,row in enumerate(phases):
        if not isinstance(row,dict) or type(row.get('phase'))is not int or row['phase']!=phase:return False
        items=row.get('ssap_requester_lifecycle')
        if not isinstance(items,list) or len(items)!=1 or not isinstance(items[0],dict):return False
        item=items[0]
        if (type(item.get('sender'))is not int or item['sender']!=phase or type(item.get('target'))is not int or item['target']!=1-phase
                or item.get('api')!=('c'if phase==0 else'python') or type(item.get('requester_exit'))is not int or item['requester_exit']!=-9
                or any(item.get(k)is not True for k in ['busy_without_wire','late_original_reply_drained','peer_value_committed'])
                or type(item.get('business_while_prompt_held'))is not int or not 1<=item['business_while_prompt_held']<=20
                or not isinstance(item.get('wire'),list) or len(item['wire'])!=4):return False
        total+=item['business_while_prompt_held']
        for leg in item['wire']:
            if not isinstance(leg,dict)or set(leg)!={'tx','rx'}:return False
            tx,rx=leg['tx'],leg['rx']
            if any(not isinstance(v,dict)or any(type(v.get(k))is not int for k in ['bus','device','handle','wall_ns'])for v in [tx,rx]):return False
            if tx.get('direction')!='out' or rx.get('direction')!='in' or (tx['bus'],tx['device'])==(rx['bus'],rx['device'])or not isinstance(tx.get('data'),str)or not re.fullmatch(r'(?:[0-9a-f]{2}){4,}',tx['data'])or tx['data']!=rx.get('data'):return False
    return type(proof.get('round_trips'))is int and proof['round_trips']==total
