# SPDX-License-Identifier: GPL-2.0-only
"""Finite method gate over the existing publisher, SDK supervisor and USB proof.

No Host/codec/receive loop. Execution is pending until both USB legs and the
actual independent application result have been corroborated. Short requests
only; command, long-result and lifetime matrices remain separate gates.
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

VERSION = 1
TOKEN = 'ws73.ssap_method_provider=1'
STATUS = 'METHOD_PROVIDER_APPLICATION_PAIRED_USB'
PENDING = 'METHOD_PROVIDER_PENDING_PAIRED_USB'
MODES = ('application-error-ff', 'empty', 'value32')
PROMPT = (r'^SsapMethodProviderPrompt: token=p(?P<token>[1-9]\d*) request=(?P<request>[1-9]\d*) '
          r'index=(?P<index>\d+) generation=(?P<generation>[1-9]\d*) lifetime=(?P<lifetime>[1-9]\d*) '
          r'handle=(?P<handle>\d+) epoch=(?P<epoch>[1-9]\d*) security=(?P<security>\d+) '
          r'local_tcid=(?P<local_tcid>\d+) remote_tcid=(?P<remote_tcid>\d+) pi=(?P<pi>\d+) '
          r'method=(?P<method>[1-9]\d*) deadline_ns=(?P<deadline_ns>[1-9]\d*) operation=(?P<operation>\d+) '
          r'arguments=(?P<arguments>[0-9a-f]*) maximum_result_bytes=(?P<maximum_result_bytes>\d+); '
          r"answer 'provide p(?P=token) HEX' \('-' for empty\) or 'provider-error p(?P=token) AF\.\.FF'$")


def requested(args, *, passthrough=None):
    selected = getattr(args, 'ssap_method_provider_verify', False)
    if type(selected) is not bool: raise ValueError('explicit method selector boolean required')
    if not selected: return False
    if any(value for name, value in vars(args).items() if name.startswith('ssap_') and name.endswith('_verify')
           and name not in ('ssap_method_provider_verify', 'ssap_owned_verify')):
        raise ValueError('method gate requires its own unchanged Owned baseline')
    # Share the existing finite baseline constraints, without enabling READ.
    from ws73_ssap_read_provider import requested as baseline
    shadow = copy.copy(args); shadow.ssap_read_provider_verify = True
    baseline(shadow, passthrough=passthrough)
    return True


def boot_requested(tokens):
    if type(tokens) not in (list, tuple) or any(type(t) is not str for t in tokens):
        raise ValueError('original tokenized boot arguments required')
    selected = [t for t in tokens if t == 'ws73.ssap_method_provider' or t.startswith('ws73.ssap_method_provider=')]
    if selected not in ([], [TOKEN]) or selected and tokens.count('ws73.ssap_owned=1') != 1:
        raise ValueError('one method selector and Owned dependency required')
    return bool(selected)


def validate_inputs(package):
    from ws73_ssap_read_provider import validate_inputs as baseline
    baseline(package)
    path = Path(__file__).resolve()
    records = [r for r in package.get('inputs', []) if Path(r['path']).resolve() == path]
    if len(records) != 1 or records[0]['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise CaptureError('fresh exact method scenario/verifier required')


def validate_rows(rows, selected):
    if type(selected) is not bool or type(rows) is not list or selected and len(rows) != 2:
        raise CaptureError('explicit method selector and two original phases required')
    for phase, row in enumerate(rows):
        actual = row.get('ssap_method_provider_required', False)
        if type(actual) is not bool or actual != selected: raise CaptureError('method selector/evidence mismatch')
        if not selected:
            if any(k.startswith('ssap_method_provider_') for k in row if k != 'ssap_method_provider_required'):
                raise CaptureError('unrequested method evidence')
            continue
        if (type(row.get('phase')) is not int or row['phase'] != phase
                or type(row.get('ssap_method_provider_version')) is not int or row['ssap_method_provider_version'] != VERSION
                or row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4
                or {(i['sender'], i['policy']) for i in row['ssap_owned']} != {(s,p) for s in (0,1) for p in ('allow','deny')}
                or type(row.get('ssap_method_provider_tools')) is not dict
                or len(row.get('ssap_method_provider_cases', [])) != 2
                or {i['sender'] for i in row['ssap_method_provider_cases']} != {0,1}):
            raise CaptureError('complete original baseline, version and two method directions required')


def prompts(text, count):
    found = list(re.finditer(PROMPT, text, re.M))
    if type(count) is not int or count not in (1,2,3) or len(found) != count or sum(l.startswith('SsapMethodProviderPrompt:') for l in text.splitlines()) != count:
        raise CaptureError('exact original method callback sequence required')
    result = []
    for match in found:
        data = {k: (v if k == 'arguments' else int(v)) for k,v in match.groupdict().items()}
        if (any(not 0 <= v < 2**64 for k,v in data.items() if k != 'arguments')
                or len(data['arguments']) != 64 or not 32 <= data['maximum_result_bytes'] <= 2045
                or (data['local_tcid'],data['remote_tcid'],data['pi'],data['security'],data['operation']) != (10,10,0,0,19)):
            raise CaptureError('bounded basic-SMTC method request context required')
        result.append(data)
    return result


def execute(run, row):
    from ws73_application_client import ssap_commands, ssap_error_command
    from ws73_ssap_owned import publisher, wait_text, wait_output, await_removed
    from ws73_ssap_update_delivery import tool_records
    if row.get('ssap_owned_required') is not True or len(row.get('ssap_owned', [])) != 4:
        raise CaptureError('original Owned baseline must precede method scenario')
    row.update(ssap_method_provider_required=True, ssap_method_provider_version=VERSION,
               ssap_method_provider_tools=tool_records(), ssap_method_provider_cases=[])
    run.save()
    for sender in (0,1):
        source,target = row['owners'][sender],row['owners'][1-sender]
        with publisher(run,row,sender,'allow',method_access=4,collection='ssap_method_provider_cases',label='method-provider') as (process,item):
            item.update(result=secrets.token_hex(32), prepared_wall_ns=time.time_ns(), steps=[])
            process.stdin.write('provider\n'); process.stdin.flush()
            found,_ = wait_text(process,Path(item['output_files'][0]),
                r'^SsapMethodProviderBound: handle=(\d+); independent application result, no rebind or fallback$',time.monotonic()+5,max_count=1)
            if found != [str(item['handle'])]: raise CaptureError('same owner must bind one actual method')
            item['bound_wall_ns'] = time.time_ns(); run.save()
            api = 'c' if (row['phase']+sender)%2 == 0 else 'python'
            for ordinal,mode in enumerate(MODES,1):
                # First eight random bytes identify this request; remaining
                # bytes are payload. The application sees and verifies all32.
                arguments = secrets.token_hex(32)
                if arguments == item['result'] or any(s['arguments'] == arguments for s in item['steps']):
                    raise CaptureError('fresh independent method nonce/payload required')
                step = dict(mode=mode,arguments=arguments);item['steps'].append(step);run.save()
                def provide(app,deadline):
                    step['request'] = app; run.save()
                    _,text = wait_text(process,Path(item['output_files'][0]),PROMPT,min(deadline/1e9,time.monotonic()+5),min_count=ordinal,max_count=ordinal)
                    observed = time.monotonic_ns();d = prompts(text,ordinal)[-1]
                    if ((d['index'],d['generation'],d['lifetime'],d['handle'],d['method']) !=
                            (target['owner']['index'],target['owner']['generation'],target['object']['lifetime'],target['object']['handle'],item['handle'])
                            or d['arguments'] != arguments or not observed < d['deadline_ns'] <= min(deadline,observed+5_000_000_000)
                            or ordinal>1 and any(d[k] <= item['steps'][-2]['callback']['prompt'][k] for k in ('token','request'))):
                        raise CaptureError('actual method callback identity/arguments/original deadline required')
                    step['callback'] = dict(prompt=d,publisher_pid=process.pid,observed_wall_ns=time.time_ns(),observed_monotonic_ns=observed,supervisor_deadline_ns=deadline)
                    step['reply_command'] = f'provider-error p{d["token"]} FF' if mode==MODES[0] else f'provide p{d["token"]} '+('-' if mode==MODES[1] else item['result'])
                    run.save();step['callback'].update(reply_before_wall_ns=time.time_ns(),reply_before_monotonic_ns=time.monotonic_ns())
                    process.stdin.write(step['reply_command']+'\n');process.stdin.flush()
                    step['callback'].update(replied_wall_ns=time.time_ns(),replied_monotonic_ns=time.monotonic_ns())
                    if step['callback']['replied_monotonic_ns'] >= d['deadline_ns']:raise CaptureError('original method deadline expired')
                    run.save()
                args=['ssap-call-method',source['object']['path'],str(item['handle']),arguments]
                if mode==MODES[0]:step['request']=ssap_error_command(run,row,source,args,errno.EIO,api=api,after_start=provide)
                else:
                    expected=b'' if mode==MODES[1] else bytes.fromhex(item['result'])
                    step['request']=ssap_commands(run,row,[(source,args,expected)],api=api,expected_size=len(expected),after_start=provide)[0]
                run.save()
            item['quit_wall_ns']=time.time_ns();process.stdin.write('quit\n');process.stdin.flush();wait_output(process,2)
            if process.returncode!=0:raise CaptureError('method owner cleanup failed')
            item['owner_exit_wall_ns']=time.time_ns();item['cleanup']=await_removed(run,target,item['start'])
            item['retired_request']=run.command([str(run.args.slctl),'--adapter',source['owner']['path'],'ssap-call-method',source['object']['path'],str(item['handle']),item['steps'][0]['arguments'],'0'],10,collection='ssap_method_providers')
            run.save()
    row['ssap_method_provider_status']=PENDING;run.save()


def _case(row,item,matched):
    from ws73_application_client import ssap_receipt,ssap_error_receipt
    from ws73_ssap_command import _identity
    from ws73_ssap_owned import verify_output
    from ws73_ssap_read_provider import _wire
    verify_output(item)
    identities=[_identity(o) for o in row['owners']]
    if (len(identities)!=2 or len({(i['index'],i['generation']) for i in identities})!=2
            or len({(i['bus'],i['device']) for i in identities})!=2
            or any(type(item[k]) is not int for k in ('sender','target','handle','start','end','pid','method_access'))
            or item['sender'] not in (0,1) or item['target']!=1-item['sender']
            or not 0<item['start']<item['handle']==item['end']<65535 or item['pid']<=0
            or item['entry_kind']!='method' or item['method_access']!=4 or item['policy']!='allow'
            or any(not re.fullmatch('[0-9a-f]{32}',item[k]) for k in ('service','uuid'))
            or not re.fullmatch('[0-9a-f]{64}',item['result'])
            or type(item['steps']) is not list or [s['mode'] for s in item['steps']]!=list(MODES)
            or len({s['arguments'] for s in item['steps']})!=3):
        raise CaptureError('original independent method owners and bounded sequence required')
    s,t,h=item['sender'],item['target'],item['handle'];source,target=row['owners'][s],row['owners'][t]
    if (item['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',target['owner']['path'],'ssap-serve-method',item['service'],item['uuid'],'4','allow']
            or type(item['exit']) is not int or item['exit']!=0 or item['stderr']
            or item['credentials']['uids']!=[1000]*4
            or set(item['credentials']['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'}
            or any(int(v,16) for v in item['credentials']['capabilities'].values())):
        raise CaptureError('original cap-zero method owner and exact command required')
    data=prompts(item['stdout'],3);lines=item['stdout'].splitlines()
    registration=f'SsapOwnedMethod: start={item["start"]} end={item["end"]} method={h}; local registration only'
    bound=f'SsapMethodProviderBound: handle={h}; independent application result, no rebind or fallback'
    for prefix,count in [('SsapOwnedMethod:',1),('SsapMethodProviderBound:',1),('SsapAuthorizationDecision:',3),('SsapMethodProviderResult:',3),('SsapMethodProviderInput:',0)]:
        if sum(l.startswith(prefix) for l in lines)!=count:raise CaptureError('complete method owner transcript required')
    if lines.count(registration)!=1 or lines.count(bound)!=1:raise CaptureError('same registered method and binding required')
    order=[lines.index(registration),lines.index(bound)];stamps=[item['start_wall_ns'],item['prepared_wall_ns'],item['bound_wall_ns']]
    requests=[];exchanges=[]
    for ordinal,(step,d) in enumerate(zip(item['steps'],data,strict=True)):
        callback,app=step['callback'],step['request'];expected=b'' if ordinal<2 else bytes.fromhex(item['result']);status=255 if ordinal==0 else 0
        answer=f'provider-error p{d["token"]} FF' if ordinal==0 else f'provide p{d["token"]} '+('-' if ordinal==1 else item['result'])
        if (callback['prompt']!=d or type(callback['publisher_pid']) is not int or callback['publisher_pid']!=item['pid']
                or any(type(v) is not int for k,v in callback['prompt'].items() if k!='arguments')
                or (d['index'],d['generation'],d['lifetime'],d['handle'],d['method']) != (identities[t]['index'],identities[t]['generation'],identities[t]['lifetime'],identities[t]['handle'],h)
                or d['arguments']!=step['arguments'] or d['arguments']==item['result'] or step['reply_command']!=answer
                or ordinal>0 and any(d[k]<=data[ordinal-1][k] for k in ('token','request'))
                or ordinal>0 and any(d[k]!=data[0][k] for k in ('index','generation','lifetime','handle','epoch','security','method','maximum_result_bytes'))):
            raise CaptureError('actual same-lifetime method callback and independent parameters required')
        decision=f'SsapAuthorizationDecision: request={d["request"]} property={h} data_type=3 write=true security=0 approved=true; local policy only'
        result=f'SsapMethodProviderResult: request={d["request"]} method={h} status={status} bytes={len(expected)}; application response only'
        prompt_line=[l for l in lines if l.startswith(f'SsapMethodProviderPrompt: token=p{d["token"]} ')]
        if lines.count(decision)!=1 or lines.count(result)!=1 or len(prompt_line)!=1:raise CaptureError('separate actual method approval/callback/result required')
        order.extend([lines.index(decision),lines.index(prompt_line[0]),lines.index(result)])
        if (app['api']!=('c' if (row['phase']+s)%2==0 else 'python') or app['ssap_operation']!='ssap-call-method'
                or app['ssap_handle']!=h or app['ssap_arguments']!=step['arguments']):raise CaptureError('exact original SDK method requester required')
        if ordinal==0:
            ssap_error_receipt(app,source,expected_errno=errno.EIO);origin=app['start_monotonic_ns']
            if callback['supervisor_deadline_ns']!=app['ssap_supervisor_deadline_ns']:raise CaptureError('original error supervisor deadline required')
        else:
            ssap_receipt(app,source,expected_size=len(expected));origin=app['ssap_release_monotonic_ns']
            if app['ssap_expected']!=expected.hex():raise CaptureError('actual SDK must compare independent complete result')
        times=[origin,callback['observed_monotonic_ns'],callback['reply_before_monotonic_ns'],callback['replied_monotonic_ns'],d['deadline_ns'],callback['supervisor_deadline_ns']]
        if any(type(v) is not int or v<=0 for v in times) or times!=sorted(times) or times[3]>=times[4] or not 0<times[4]-times[1]<=5_000_000_000 or times[-1]!=origin+7_000_000_000:
            raise CaptureError('original method and supervisor deadlines required')
        stamps.append(app['start_wall_ns'])
        if ordinal:stamps.append(app['ssap_released_wall_ns'])
        stamps.extend([callback['observed_wall_ns'],callback['reply_before_wall_ns'],callback['replied_wall_ns'],app['end_wall_ns']])
        requests.append(b'\x13\x03'+h.to_bytes(2,'little')+bytes.fromhex(step['arguments']))
        response=b'\x01\0\x13'+h.to_bytes(2,'little')+b'\xff' if ordinal==0 else b'\x14\x03'+expected
        exchanges.append((app,response,callback))
    cleanup,removed=item['cleanup'],item['retired_request'];lists=re.findall(r'^SsapLocalServices: (.+)$',cleanup['stdout'],re.M)
    if (type(cleanup['exit']) is not int or cleanup['exit']!=0 or cleanup['stderr'] or len(lists)!=1 or any(v[0]==item['start'] for v in json.loads(lists[0]))
            or cleanup['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',target['owner']['path'],'ssap-list']
            or removed['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',source['owner']['path'],'ssap-call-method',source['object']['path'],str(h),item['steps'][0]['arguments'],'0']
            or type(removed['exit']) is not int or removed['exit']==0 or 'peer method protocol error 4' not in removed['stderr']):
        raise CaptureError('owner withdrawal and real retired method refusal required')
    stamps.extend([item['quit_wall_ns'],item['owner_exit_wall_ns'],cleanup['start_wall_ns'],cleanup['end_wall_ns'],removed['start_wall_ns'],removed['end_wall_ns'],item['end_wall_ns']])
    if order!=sorted(order) or len(set(order))!=len(order) or any(type(v)is not int or v<=0 for v in stamps) or stamps!=sorted(stamps):raise CaptureError('original method chronology required')
    requests.append(requests[0]);exchanges.append((removed,b'\x01\0\x13'+h.to_bytes(2,'little')+b'\x04',None))
    wire,credit=_wire(row,item,matched,exchanges,requests=requests)
    for n in range(0,len(wire),2):
        req,rsp=wire[n:n+2]
        if any(packet_interval(p['tx'])[1]>packet_interval(p['rx'])[0] for p in (req,rsp)) or packet_interval(req['rx'])[1]>packet_interval(rsp['tx'])[0]:raise CaptureError('paired method request/response causal order required')
    return dict(status=STATUS,version=VERSION,sender=s,target=t,result=item['result'],wire=wire,
                context=copy.deepcopy(dict(phase=row['phase'],owners=row['owners'],ssap_receipts=row['ssap_receipts'])),case=copy.deepcopy(item)),credit


def corroborate(row,matched):
    if row.get('ssap_method_provider_required',False) is not True:
        if any(k.startswith('ssap_method_provider_') for k in row if k!='ssap_method_provider_required'):raise CaptureError('unrequested method evidence')
        return [],{0:0,1:0}
    if (row.get('ssap_owned_required') is not True or len(row.get('ssap_owned',[]))!=4
            or {(i['sender'],i['policy']) for i in row['ssap_owned']}!={(s,p) for s in (0,1) for p in ('allow','deny')}
            or type(row.get('ssap_method_provider_version')) is not int or row['ssap_method_provider_version']!=VERSION
            or len(row.get('ssap_method_provider_cases',[]))!=2 or {i['sender'] for i in row['ssap_method_provider_cases']}!={0,1}):raise CaptureError('original baseline and two method directions required')
    proof=[];credit={0:0,1:0}
    for case in row['ssap_method_provider_cases']:
        item,used=_case(row,case,matched);proof.append(item)
        for k in credit:credit[k]+=used[k]
    if len({p['result'] for p in proof})!=2:raise CaptureError('independent method results required')
    return proof,credit


def valid_summary(proof):
    try:
        rows=proof['proofs'];values=set();arguments=set()
        if type(rows)is not list or len(rows)!=2:return False
        for phase,row in enumerate(rows):
            items=row['ssap_method_providers']
            if type(row['phase'])is not int or row['phase']!=phase or len(items)!=2 or {i['sender'] for i in items}!={0,1}:return False
            for item in items:
                context,case=item['context'],item['case']
                if type(item['version'])is not int or item['version']!=VERSION or context['phase']!=phase or context['owners']!=row['owners'] or item['result'] in values or len(item['wire'])!=8:return False
                values.add(item['result'])
                for step in case['steps']:
                    if step['arguments'] in arguments:return False
                    arguments.add(step['arguments'])
                packets=[copy.deepcopy(leg[side]) for leg in item['wire'] for side in ('tx','rx')]
                def matched(owner,direction,frame,window):
                    key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
                    found=[p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data'))==key and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
                    if len(found)!=1:raise CaptureError('one retained paired method packet required')
                    packets.remove(found[0]);return found[0]
                rebuilt,_=_case(context,case,matched)
                if packets or json.dumps(rebuilt,sort_keys=True)!=json.dumps(item,sort_keys=True):return False
        return True
    except (KeyError,AttributeError,IndexError,TypeError,ValueError):return False


def valid_manifest(record):
    try:
        selected=record.get('ssap_method_provider_requested',False)
        if type(selected)is not bool or boot_requested([t for arg in record.get('qemu_args',[]) for t in arg.split()])!=selected:return False
        proof=record.get('channel_socket_corroboration',{})
        if not selected:return record.get('ssap_method_provider_acceptance',False)is False and 'ssap_method_provider_version' not in record and not any('ssap_method_providers' in r for r in proof.get('proofs',[]))
        return (type(record.get('ssap_method_provider_version'))is int and record['ssap_method_provider_version']==VERSION
                and record.get('ssap_method_provider_acceptance')is True and record.get('ssap_owned_requested')is True
                and record.get('ssap_owned_acceptance')is True and record.get('ordinary_channel_socket_acceptance')is True
                and record.get('status')=='PASSTHROUGH_SUPPORT_PASS'
                and type(record.get('qemu_exit'))is int and record['qemu_exit']==0 and valid_summary(proof))
    except (KeyError,AttributeError,IndexError,TypeError,ValueError):return False
