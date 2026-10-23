# SPDX-License-Identifier: GPL-2.0-only
"""Finite real owner/terminal deadline interleavings, never a wire Engine.

The real slctl callback prompt is the barrier. No sleep is used to guess that
the remote request arrived. The sole actor, original native constraints and
ordinary channel runner remain the production paths.
"""
from pathlib import Path
import errno
import json
import re
import time
from ws73_capture import CaptureError
from ws73_channel_socket import credentials
from ws73_ssap_owned import publisher,wait_text,value_snapshot,await_removed,output_text

PROMPT=(r'^SsapAuthorizationPrompt: token=(\d+) request=(\d+) index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) epoch=(\d+) security=(\d+) property=(\d+) data_type=0 write=(true|false) bytes=(\d+) deadline_ns=(\d+); answer \'yes (\d+)\' or \'no (\d+)\'$')
STATUS='OWNER_LIFECYCLE_USB_CUTC_EVIDENCE_PENDING'


def timeout_arguments(api,source,item):
    if api not in ('c','python'):raise CaptureError('exact public SDK consumer language required')
    prefix=['/bin/ws73-application-client-c'] if api=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    return prefix+['ssap-error',str(source['owner']['index']),str(source['owner']['generation']),source['object']['path'],'ssap-write',str(item['handle']),str(errno.ETIMEDOUT),item['value']]


def timeout_receipt(command,api,source,item):
    """Actual SDK errno plus original timing, never a diagnostic substring."""
    from ws73_application_client import application_environment
    if command['args']!=timeout_arguments(api,source,item) or command.get('environment')!=application_environment() or command['exit']!=0 or command['stderr']:
        raise CaptureError('exact successful negative-scenario SDK process required')
    lines=command['stdout'].splitlines()
    if len(lines)!=2:raise CaptureError('two original SDK call/error receipts required')
    call,result=map(json.loads,lines)
    if (set(call)!={'stage','api','deadline_ns','call_ns','client_closed'} or set(result)!={'stage','api','errno','operation_success','deadline_ns','returned_ns'}
            or call['stage']!='ssap_call' or result['stage']!='ssap_error' or call['api']!=api or result['api']!=api
            or call['client_closed'] is not True or result['operation_success'] is not False or type(result['errno'])is not int or result['errno']!=errno.ETIMEDOUT
            or any(type(v)is not int for v in [call['deadline_ns'],call['call_ns'],result['deadline_ns'],result['returned_ns']]) or result['deadline_ns']!=call['deadline_ns']):
        raise CaptureError('actual ETIMEDOUT without operation success required')
    start,end=command['start_monotonic_ns'],command['end_monotonic_ns'];deadline=call['deadline_ns']
    # SDK sampling only shortens its effective clock/stamp deadline. The public
    # argument is an upper bound;retain the original draft's +/-500ms guard.
    if not (4_500_000_000<=end-start<=5_500_000_000 and start<=call['call_ns']<deadline and call['call_ns']<=result['returned_ns']<=end and deadline-500_000_000<=result['returned_ns']<=deadline+500_000_000 and 0<deadline-call['call_ns']<=5_000_000_000):
        raise CaptureError('unchanged original five-second wait guard and actual local deadline required')
    identity=command['credentials']
    if identity['uids']!=[1000]*4 or set(identity['capabilities'])!={'CapEff','CapPrm','CapAmb','CapInh'} or any(int(v,16)for v in identity['capabilities'].values()):
        raise CaptureError('ordinary cap-zero SDK timeout caller required')
    return dict(api=api,errno=result['errno'],deadline_ns=deadline,call_ns=call['call_ns'],returned_ns=result['returned_ns'],operation_success=False)


def check_prompt(event,target,item):
    p=event['fields'];o,obj=target['owner'],target['object']
    if (len(p)!=14 or not all(v.isascii() and v.isdecimal() for n,v in enumerate(p) if n!=9)
            or tuple(map(int,p[2:6]))!=(o['index'],o['generation'],obj['lifetime'],obj['handle'])
            or int(p[0])<=0 or p[12]!=p[0] or p[13]!=p[0] or int(p[1])<=0 or int(p[6])<=0
            or int(p[7]) not in (0,1,2) or int(p[8])!=item['handle'] or p[9]!='true' or p[10]!='32'
            or not event['monotonic_ns']<int(p[11])<=event['monotonic_ns']+5_000_000_000):
        raise CaptureError('actual original owner prompt identity/value budget/deadline required')
    return dict(token=int(p[0]),request=int(p[1]),epoch=int(p[6]),security=int(p[7]),deadline=int(p[11]))


def prompt(process,item,target,ordinal):
    fields,_=wait_text(process,Path(item['output_files'][0]),PROMPT,time.monotonic()+2,min_count=ordinal)
    if len(fields)!=ordinal:raise CaptureError('one new actual owner prompt per original request')
    event=dict(fields=list(fields[-1]),wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
    check_prompt(event,target,item);item.setdefault('prompt_events',[]).append(event);return event


def execute(run,row):
    row['ssap_owner_lifecycle_required']=True;row['ssap_owner_lifecycle']=[];run.save()
    sender=row['phase']%2;source,target=row['owners'][sender],row['owners'][1-sender];level=row.get('security_requirement',0)
    mode=getattr(run.args,'ssap_owner_publisher','cli')
    if mode not in ('cli','sdk'):raise CaptureError('explicit lifecycle publisher mode required')
    api=('c' if row['phase']==0 else 'python') if mode=='sdk' else None
    row['ssap_owner_publisher']=mode
    def owner_publisher(*args,**kwargs):return publisher(*args,**kwargs,sdk_api=api)
    def command(words,on_started=None):
        return run.command([str(run.args.slctl),'--adapter',source['owner']['path'],*words],10,collection='ssap_owner_lifecycle_commands',on_started=on_started)
    def show_other(item):
        c=run.command([str(run.args.slctl),'--adapter',source['owner']['path'],'show'],2,collection='ssap_owner_lifecycle_observations')
        if c['exit'] or '  State:       Ready\n' not in c['stdout'] or f'  Generation:  {source["owner"]["generation"]}\n' not in c['stdout']:raise CaptureError('peer management blocked or changed during actual approval')
        item.setdefault('peer_during_prompt',[]).append(c);run.save()
    with owner_publisher(run,row,sender,'allow',collection='ssap_owner_lifecycle',label='guard') as (guard,g):
        g['case']='guard'
        with owner_publisher(run,row,sender,'ask',collection='ssap_owner_lifecycle',label='exit-pending') as (owner,i):
            i['case']='owner-exit'
            def exit_barrier(process,record):
                record['credentials']=credentials(process.pid)
                event=prompt(owner,i,target,1);i['barrier_command_start']=record['start_monotonic_ns'];run.save();show_other(i)
                owner.kill();i['owner_exit']=owner.wait(timeout=2);i['owner_exit_wall_ns']=time.time_ns()
                i['after_owner_exit']=await_removed(run,target,i['start']);run.save()
            i['write']=command(['ssap-write',source['object']['path'],str(i['handle']),i['value'],str(level)],exit_barrier)
            errors=re.findall(r'peer write error (\d+)',i['write']['stderr'])
            if not i['write']['exit'] or len(errors)!=1 or int(errors[0]) not in (4,9):raise CaptureError('inflight original request must return actual removed/denied error')
            i['peer_error']=int(errors[0]);i['removed_read']=command(['ssap-read',source['object']['path'],str(i['handle']),str(level)])
            if not i['removed_read']['exit'] or 'peer read error 4' not in i['removed_read']['stderr']:raise CaptureError('old owner handle must refuse after completed cleanup')
            i['guard_read']=command(['ssap-read',source['object']['path'],str(g['handle']),str(level)])
            if i['guard_read']['exit'] or f'value={g["secret"]}' not in i['guard_read']['stdout']:raise CaptureError('another actual owner must continue remote delivery')
            i.update(guard_handle=g['handle'],guard_value=g['secret']);run.save()
        # A deliberately expired physical obligation can retire this Engine.
        # Finish the live-scope gate first;do not reset its original deadline.
        if mode=='sdk':
            with owner_publisher(run,row,sender,'ask',collection='ssap_owner_lifecycle',label='close-pending') as (owner,i):
                i['case']='close-pending'
                def close_barrier(process,record):
                    record['credentials']=credentials(process.pid)
                    event=prompt(owner,i,target,1);show_other(i)
                    i['close_input']=dict(wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
                    owner.stdin.write('close\n');owner.stdin.flush()
                    matches,_=wait_text(owner,Path(i['output_files'][0]),r'^SdkServiceClosed: (.+)$',time.monotonic()+2)
                    if len(matches)!=1:raise CaptureError('one original service-close receipt required')
                    i['close_receipt']=json.loads(matches[0]);i['process_alive_after_close']=owner.poll() is None
                    i['after_scope_close']=await_removed(run,target,i['start'])
                    if owner.poll() is not None:raise CaptureError('scope cleanup must happen while publisher is alive')
                    run.save()
                i['write']=command(['ssap-write',source['object']['path'],str(i['handle']),i['value'],str(level)],close_barrier)
                errors=re.findall(r'peer write error (\d+)',i['write']['stderr'])
                if not i['write']['exit'] or len(errors)!=1 or int(errors[0]) not in (4,9):raise CaptureError('closed original scope must refuse actual pending peer write')
                i['peer_error']=int(errors[0]);i['removed_read']=command(['ssap-read',source['object']['path'],str(i['handle']),str(level)])
                if not i['removed_read']['exit'] or 'peer read error 4' not in i['removed_read']['stderr']:raise CaptureError('closed scope handle must stay retired')
                i['guard_read']=command(['ssap-read',source['object']['path'],str(g['handle']),str(level)])
                if i['guard_read']['exit'] or f'value={g["secret"]}' not in i['guard_read']['stdout']:raise CaptureError('independent actual service must survive last view close')
                i.update(guard_handle=g['handle'],guard_value=g['secret'])
                owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2);i['closed_exit']=owner.returncode
                if owner.returncode!=0:raise CaptureError('closed publisher must exit normally after cleanup')
                run.save()
        with owner_publisher(run,row,sender,'ask',collection='ssap_owner_lifecycle',label='original-deadline') as (owner,i):
            i['case']='original-deadline'
            def deny_barrier(process,record):
                record['credentials']=credentials(process.pid)
                event=prompt(owner,i,target,1);check=check_prompt(event,target,i);show_other(i)
                i['denial_input']=dict(token=check['token'],wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
                owner.stdin.write(f'no {check["token"]}\n');owner.stdin.flush();run.save()
            i['denied_write']=command(['ssap-write',source['object']['path'],str(i['handle']),i['value'],str(level)],deny_barrier)
            if not i['denied_write']['exit'] or 'peer write error 9' not in i['denied_write']['stderr']:raise CaptureError('explicit current-token denial must cross real SMTC')
            value_snapshot(owner,i,i['secret']);run.save()
            def stale_barrier(process,record):
                from ws73_application_client import process_identity
                record['credentials'],record['process_status']=process_identity(process.pid)
                event=prompt(owner,i,target,2);first=check_prompt(i['prompt_events'][0],target,i);second=check_prompt(event,target,i)
                if second['token']<=first['token']:raise CaptureError('publisher prompt token reused')
                i['stale_input']=dict(token=first['token'],wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
                owner.stdin.write(f'yes {first["token"]}\n');owner.stdin.flush();value_snapshot(owner,i,i['secret']);show_other(i)
                if process.poll() is not None:raise CaptureError('stale token ended current original request early')
                run.save()
            from ws73_application_client import application_environment
            api='c' if row['phase']==0 else 'python'
            i['timeout_api']=api
            i['timed_write']=run.command(timeout_arguments(api,source,i),10,collection='ssap_owner_lifecycle_commands',on_started=stale_barrier,environment=application_environment())
            c=i['timed_write'];elapsed=c['end_monotonic_ns']-c['start_monotonic_ns']
            i['timeout_receipt']=timeout_receipt(c,api,source,i)
            deadline=check_prompt(i['prompt_events'][1],target,i)['deadline'];remaining=(deadline-time.monotonic_ns())/1e9+.1
            if remaining>1.5:raise CaptureError('source failed too early for original owner deadline')
            if remaining>0:time.sleep(remaining)
            token=int(i['prompt_events'][1]['fields'][0]);i['late_input']=dict(token=token,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
            owner.stdin.write(f'yes {token}\n');owner.stdin.flush();value_snapshot(owner,i,i['secret']);run.save()
            if 'approved=true' in output_text(owner,Path(i['output_files'][0])):raise CaptureError('old/late prompt decision granted authorization')
        value_snapshot(guard,g,g['secret']);g['other_owner_after_failed_request']=True;run.save()
    row['ssap_owner_lifecycle_status']=STATUS;run.save()


def sdk_prompt_contexts(item):
    from ws73_application_client import authorization_context
    rows=[json.loads(v) for v in re.findall(r'^SdkAuthorizationRequest: (.+)$',item['stdout'],re.M)]
    events=item.get('prompt_events',[])
    if len(rows)!=len(events):raise CaptureError('one actual SDK context per prompt required')
    for context,event in zip(rows,events,strict=True):
        authorization_context(context,item['publisher_api']);f=event['fields']
        if ([context[k] for k in ['token','request_id','index','generation','lifetime','handle','epoch','level','property']]
                !=[int(v)for v in f[:9]] or context['write']is not True
                or context['value']!=item['value'] or context['deadline_ns']!=int(f[11])):
            raise CaptureError('SDK opaque original context/proposal differs from actual barrier')
    return rows


def sdk_replies(item):
    rows=[json.loads(v) for v in re.findall(r'^SdkAuthorizationReply: (.+)$',item['stdout'],re.M)]
    fields={'api','token','current_token','allow','api_called','result','returned_ns'}
    for v in rows:
        if (not isinstance(v,dict) or set(v)!=fields or v['api']!=item['publisher_api']
                or type(v['allow'])is not bool or type(v['api_called'])is not bool
                or any(type(v[k])is not int for k in ['token','current_token','result','returned_ns'])
                or not 0<v['token']<2**64 or not 0<v['current_token']<2**64 or v['returned_ns']<=0):
            raise CaptureError('actual typed SDK policy reply receipt required')
    return rows


def corroborate(row,matched,sdus):
    if not row.get('ssap_owner_lifecycle_required'):return [],{0:0,1:0}
    items=row.get('ssap_owner_lifecycle',[]);owners=row['owners'];s=row['phase']%2;t=1-s
    mode=row.get('ssap_owner_publisher','cli')
    if mode not in ('cli','sdk'):raise CaptureError('original lifecycle publisher selector required')
    expected=['guard','owner-exit']+(['close-pending'] if mode=='sdk' else [])+['original-deadline']
    if row.get('ssap_owner_lifecycle_status')!=STATUS or [v.get('case')for v in items]!=expected:raise CaptureError('all finite completed original owner interleavings required')
    g,ex=items[:2];expired=items[-1];closed=items[2] if mode=='sdk' else None;credit={0:0,1:0};proof=[]
    def exchange(item,name,request,response=None,window=None):
        command=item[name];window=window or command
        if not item['start_wall_ns']<=command['start_wall_ns']<=command['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('original lifecycle command interval required')
        operation='ssap-write' if request[0]==13 else 'ssap-read'
        args=[row['ssap_receipts'][0]['args'][0],'--adapter',owners[s]['owner']['path'],operation,owners[s]['object']['path'],str(int.from_bytes(request[2:4],'little'))]
        if request[0]==13:args.append(request[5:].hex())
        args.append(str(row.get('security_requirement',0)))
        if name=='timed_write':
            api='c'if row['phase']==0 else'python'
            if item.get('timeout_api')!=api or item.get('timeout_receipt')!=timeout_receipt(command,api,owners[s],item):raise CaptureError('actual original SDK timeout result required')
        elif command['args']!=args:raise CaptureError('original selected source/lifetime/value/minimum command required')
        result=[]
        for a,b,pdu in [(s,t,request)]+([] if response is None else [(t,s,response)]):
            frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
            result.append(dict(tx=matched(owners[a],'out',frame,window),rx=matched(owners[b],'in',frame,window)));credit[a]+=1
        return result
    def write(item):return b'\x0d\x23'+item['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(item['value'])
    def denied(h,error):return b'\x0e\x07\x01'+h.to_bytes(2,'little')+bytes([error])
    def read(h):return b'\x08\x03'+h.to_bytes(2,'little')+b'\0'
    fresh=set()
    for item in items:
        expected_exit=0 if item.get('case')=='close-pending' else -9
        if item['sender']!=s or item['target']!=t or item['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in item['credentials']['capabilities'].values()) or item['exit']!=expected_exit or item['stderr']:raise CaptureError('ordinary live publisher and actual final close required')
        if mode=='sdk':
            from ws73_application_client import application_environment,owned_arguments
            api='c'if row['phase']==0 else'python'
            args=owned_arguments(api,owners[t],item['service'],item['uuid'],item['secret'],item['policy'])
            if item.get('publisher_api')!=api or item.get('environment')!=application_environment() or item['stdout'].splitlines()[0]!=f'SdkOwnedAPI: api={api} client_closed=true':raise CaptureError('original SDK caller/parent-close/environment required')
        else:
            args=[row['ssap_receipts'][0]['args'][0],'--adapter',owners[t]['owner']['path'],'ssap-serve',item['service'],item['uuid'],'5','36',item['secret'],item['policy']]
            if 'publisher_api'in item:raise CaptureError('SDK cannot be relabeled as historical CLI')
        if item['args']!=args:raise CaptureError('original lifecycle owner command required')
        registration=f'SsapOwnedService: start={item["start"]} end={item["end"]} property={item["handle"]}; local registration only'
        if not item['start']<=item['handle']<=item['end'] or item['stdout'].splitlines().count(registration)!=1:raise CaptureError('one original local owner registration required')
        for key,size in [('secret',32),('value',32),('uuid',16),('service',16)]:
            value=bytes.fromhex(item[key])
            if len(value)!=size or value in fresh:raise CaptureError('fresh original lifecycle values/identifiers required')
            fresh.add(value)
        for c in item.get('peer_during_prompt',[]):
            if c['exit'] or c['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',owners[s]['owner']['path'],'show'] or '  State:       Ready\n' not in c['stdout']:raise CaptureError('original peer management response during pending callback required')
    for item,count in [(ex,1),(expired,2)]+([(closed,1)] if closed else []):
        events=item.get('prompt_events',[])
        if item['policy']!='ask' or len(events)!=count or len(item.get('peer_during_prompt',[]))!=count or 'approved=true' in item['stdout']:raise CaptureError('original ask prompts/refusals only required')
        observed=re.findall(PROMPT,item['stdout'],re.M)
        if observed!=[tuple(v['fields']) for v in events]:raise CaptureError('sealed prompt transcript differs from observed original barrier')
        for event in events:
            p=check_prompt(event,owners[t],item)
            if p['security']!=row.get('security_requirement',0):raise CaptureError('original receipt mechanism differs from selected gate')
    if ex['peer_error'] not in (4,9) or ex['owner_exit']!=-9 or not ex['prompt_events'][0]['wall_ns']<ex['owner_exit_wall_ns']<ex['removed_read']['start_wall_ns']:raise CaptureError('actual prompt then owner exit and old-handle refusal required')
    cleanup=ex['after_owner_exit'];lists=re.findall(r'^SsapLocalServices: (.+)$',cleanup['stdout'],re.M)
    if (cleanup['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',owners[t]['owner']['path'],'ssap-list'] or cleanup['exit'] or cleanup['stderr'] or len(lists)!=1
            or any(v[0]==ex['start']for v in json.loads(lists[0])) or not ex['owner_exit_wall_ns']<=cleanup['start_wall_ns']<=cleanup['end_wall_ns']<=ex['removed_read']['start_wall_ns']):raise CaptureError('original same-controller owner cleanup before retired read required')
    for name,error in [('write',ex['peer_error']),('removed_read',4)]:
        if not ex[name]['exit'] or f'peer {"write" if name=="write" else "read"} error {error}' not in ex[name]['stderr']:raise CaptureError('actual removed original request protocol refusal required')
    if g['policy']!='allow':raise CaptureError('independent allowed owner required')
    guard_line=f'SsapPeerValue: operation=ssap-read path={owners[s]["object"]["path"]} handle={g["handle"]} value={g["secret"]}'
    if ex['guard_handle']!=g['handle'] or ex['guard_value']!=g['secret'] or ex['guard_read']['exit'] or guard_line not in ex['guard_read']['stdout'].splitlines():raise CaptureError('independent live owner must continue real remote value delivery')
    legs=exchange(ex,'write',write(ex),denied(ex['handle'],ex['peer_error']))+exchange(ex,'removed_read',read(ex['handle']),b'\x09\x0b\x04\0')+exchange(ex,'guard_read',read(g['handle']),b'\x09\x03'+bytes.fromhex(g['secret']))
    if not expired['denied_write']['exit'] or 'peer write error 9' not in expired['denied_write']['stderr']:raise CaptureError('current local token must actually deny on wire')
    legs+=exchange(expired,'denied_write',write(expired),denied(expired['handle'],9))
    first,second=[check_prompt(v,owners[t],expired) for v in expired['prompt_events']]
    for command in [ex['write'],expired['denied_write'],expired['timed_write']]:
        if command['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in command['credentials']['capabilities'].values()):raise CaptureError('actual ordinary requesting process required')
    epochs=[int(v['fields'][6]) for item in [ex,expired] for v in item['prompt_events']]
    if len(set(epochs))!=1:raise CaptureError('unexpected original security epoch change within this basic gate')
    if second['token']<=first['token'] or expired['denial_input']['token']!=first['token'] or expired['stale_input']['token']!=first['token'] or expired['late_input']['token']!=second['token'] or not expired['stale_input']['monotonic_ns']<second['deadline']<expired['late_input']['monotonic_ns']:raise CaptureError('unique original tokens with stale-before/late-after-deadline inputs required')
    if mode=='sdk':
        if not closed['end_wall_ns']<=expired['start_wall_ns']:raise CaptureError('live scope close must finish before deliberate terminal obligation expiry')
        for item in [ex,expired,closed]:sdk_prompt_contexts(item)
        replies=sdk_replies(expired)
        expected_replies=[(first['token'],first['token'],False,True,0),(first['token'],second['token'],True,False,-errno.ESTALE),(second['token'],second['token'],True,True,-errno.ETIMEDOUT)]
        if len(replies)!=3:raise CaptureError('all current/stale/late SDK decisions required')
        for reply,wanted,field in zip(replies,expected_replies,['denial_input','stale_input','late_input'],strict=True):
            if tuple(reply[k]for k in ['token','current_token','allow','api_called','result'])!=wanted or not expired[field]['monotonic_ns']<=reply['returned_ns']:raise CaptureError('actual SDK decision result/source or original timing differs')
    c=expired['timed_write'];elapsed=c['end_monotonic_ns']-c['start_monotonic_ns']
    api='c'if row['phase']==0 else'python'
    if expired.get('timeout_api')!=api or expired.get('timeout_receipt')!=timeout_receipt(c,api,owners[s],expired):raise CaptureError('unchanged original five-second actual SDK timeout required')
    snapshots=expired.get('value_snapshots',[])
    if len(snapshots)!=3 or [v['ordinal'] for v in snapshots]!=[1,2,3] or any(v['value']!=expired['secret'] or v['handle']!=expired['handle'] for v in snapshots) or not expired['stale_input']['monotonic_ns']<=snapshots[1]['start_monotonic_ns']<=snapshots[1]['end_monotonic_ns']<second['deadline'] or not expired['late_input']['monotonic_ns']<=snapshots[2]['start_monotonic_ns']<=snapshots[2]['end_monotonic_ns']:raise CaptureError('actual same-owner unchanged DB checks before and after original expiry required')
    observed=re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$',expired['stdout'],re.M)
    if observed!=[(str(expired['handle']),expired['secret'])]*3:raise CaptureError('same owner sealed value transcript required')
    # A denial may already be physically owed when the requesting app times
    # out. Attribute it, never discard that obligation or accept a success.
    window=dict(start_wall_ns=c['start_wall_ns'],end_wall_ns=snapshots[-1]['end_wall_ns'])
    legs+=exchange(expired,'timed_write',write(expired))
    pdu=denied(expired['handle'],9);frame=(b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu).hex()
    seen=any(p['data']==frame and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns'] for p in sdus)
    if seen:
        legs.append(dict(tx=matched(owners[t],'out',bytes.fromhex(frame),window),rx=matched(owners[s],'in',bytes.fromhex(frame),window)));credit[t]+=1
    elif 'peer write error 9' in c['stderr']:raise CaptureError('reported deadline denial requires actual opposite USB response')
    if not g.get('other_owner_after_failed_request') or len(g.get('value_snapshots',[]))!=1 or g['value_snapshots'][0]['value']!=g['secret'] or f'SsapOwnedValue: handle={g["handle"]} value={g["secret"]}' not in g['stdout'].splitlines():raise CaptureError('independent owner must survive another original request expiry')
    if closed:
        records=[json.loads(v)for v in re.findall(r'^SdkServiceClosed: (.+)$',closed['stdout'],re.M)]
        context=check_prompt(closed['prompt_events'][0],owners[t],closed)
        if (len(records)!=1 or records[0]!=closed.get('close_receipt')
                or set(records[0])!={'api','token','info_preserved','notification_fd_alive','reply_result','closed_ns'}
                or records[0]['api']!=closed['publisher_api'] or type(records[0]['token'])is not int or records[0]['token']!=context['token']
                or records[0]['info_preserved']is not True or records[0]['notification_fd_alive']is not True
                or type(records[0]['reply_result'])is not int or records[0]['reply_result']!=-errno.ESTALE
                or type(records[0]['closed_ns'])is not int or not closed['close_input']['monotonic_ns']<=records[0]['closed_ns']<context['deadline']
                or closed.get('process_alive_after_close')is not True or closed.get('closed_exit')!=0):raise CaptureError('actual last-view close with retained request/fd and live process required')
        cleanup=closed['after_scope_close'];lists=re.findall(r'^SsapLocalServices: (.+)$',cleanup['stdout'],re.M)
        if (cleanup['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',owners[t]['owner']['path'],'ssap-list'] or cleanup['exit'] or cleanup['stderr'] or len(lists)!=1 or any(v[0]==closed['start']for v in json.loads(lists[0]))
                or not closed['close_input']['wall_ns']<=cleanup['start_wall_ns']<=cleanup['end_wall_ns']<=closed['removed_read']['start_wall_ns']):raise CaptureError('scope cleanup while publisher alive before old-handle read required')
        if (closed['peer_error']not in (4,9) or closed['write']['exit']==0 or f'peer write error {closed["peer_error"]}' not in closed['write']['stderr']
                or closed['removed_read']['exit']==0 or 'peer read error 4'not in closed['removed_read']['stderr']
                or closed['guard_handle']!=g['handle'] or closed['guard_value']!=g['secret'] or closed['guard_read']['exit'] or guard_line not in closed['guard_read']['stdout'].splitlines()
                or closed['stdout'].splitlines().count(f'SdkOwnedClosedExit: api={closed["publisher_api"]} start={closed["start"]}')!=1
                or 'SdkOwnedRemoved:'in closed['stdout']):raise CaptureError('actual closed-scope refusal/independent guard delivery/normal process exit required')
        if g['value_snapshots'][0]['start_wall_ns']<closed['guard_read']['end_wall_ns']:raise CaptureError('independent owner snapshot must follow last-scope close and peer delivery')
        legs+=exchange(closed,'write',write(closed),denied(closed['handle'],closed['peer_error']))+exchange(closed,'removed_read',read(closed['handle']),b'\x09\x0b\x04\0')+exchange(closed,'guard_read',read(g['handle']),b'\x09\x03'+bytes.fromhex(g['secret']))
    proof.append(dict(sender=s,target=t,wire=legs,owner_exit_peer_error=ex['peer_error'],deadline_elapsed_ns=elapsed,timeout=expired['timeout_receipt'],late_denial_physical_obligation=seen,stale_token_rejected=True,late_token_rejected=True,scope='Actual callbacks and unchanged opposite DB;CUTC corroborated separately. Not concurrent peer-business,cross-lifetime human replay,controller retirement,full cancellation or security/Bond proof'))
    if closed:proof[0].update(publisher_api=closed['publisher_api'],closed_scope=closed['close_receipt'],closed_scope_peer_error=closed['peer_error'],closed_scope_process_alive=True,sdk_reply_results=[v['result']for v in sdk_replies(expired)],scope='Actual SDK C/Python callbacks,original5s,owner exit andlastviewclose;not socketfd/Grant/fullcleanup/concurrentbusiness/deployment proof')
    return proof,credit


def valid_summary(proof,publisher='cli'):
    """Fail-closed terminal shape only;full corroboration still requires originals."""
    if publisher not in ('cli','sdk') or not isinstance(proof,dict) or proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED':return False
    phases=proof.get('proofs')
    if not isinstance(phases,list) or len(phases)!=2:return False
    for phase,row in enumerate(phases):
        if not isinstance(row,dict):return False
        rows=row.get('ssap_owner_lifecycle',[])
        if type(row.get('phase'))is not int or row['phase']!=phase or not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):return False
        p=rows[0];timeout=p.get('timeout',{})
        if not isinstance(timeout,dict):return False
        if (any(type(p.get(k))is not int for k in ['sender','target','owner_exit_peer_error']) or p['sender']!=phase or p['target']!=1-phase or p['owner_exit_peer_error']not in(4,9)
                or p.get('stale_token_rejected')is not True or p.get('late_token_rejected')is not True
                or type(p.get('late_denial_physical_obligation'))is not bool
                or type(p.get('deadline_elapsed_ns'))is not int or not 4_500_000_000<=p['deadline_elapsed_ns']<=5_500_000_000
                or not isinstance(p.get('wire'),list) or len(p['wire'])!=(15 if publisher=='sdk' else 9)+int(p['late_denial_physical_obligation'])
                or timeout.get('api')!=('c'if phase==0 else'python') or type(timeout.get('errno'))is not int or timeout['errno']!=errno.ETIMEDOUT or timeout.get('operation_success')is not False
                or any(type(timeout.get(k))is not int for k in ['deadline_ns','call_ns','returned_ns'])
                or not timeout['call_ns']<timeout['deadline_ns'] or not timeout['call_ns']<=timeout['returned_ns'] or not timeout['deadline_ns']-500_000_000<=timeout['returned_ns']<=timeout['deadline_ns']+500_000_000):return False
        if publisher=='sdk':
            close=p.get('closed_scope',{});results=p.get('sdk_reply_results')
            if (not isinstance(close,dict) or not isinstance(results,list) or any(type(v)is not int for v in results)
                    or p.get('publisher_api')!=('c'if phase==0 else'python') or results!=[0,-errno.ESTALE,-errno.ETIMEDOUT]
                    or p.get('closed_scope_process_alive')is not True or type(p.get('closed_scope_peer_error'))is not int or p['closed_scope_peer_error']not in (4,9)
                    or close.get('api')!=p['publisher_api'] or close.get('info_preserved')is not True or close.get('notification_fd_alive')is not True
                    or type(close.get('token'))is not int or close['token']<=0 or type(close.get('closed_ns'))is not int or close['closed_ns']<=0
                    or type(close.get('reply_result'))is not int or close['reply_result']!=-errno.ESTALE):return False
        elif any(k in p for k in ['publisher_api','closed_scope','sdk_reply_results']):return False
        for leg in p['wire']:
            if not isinstance(leg,dict)or set(leg)!={'tx','rx'}:return False
            tx,rx=leg['tx'],leg['rx']
            if (any(not isinstance(v,dict) or any(type(v.get(k))is not int for k in ['bus','device','handle','wall_ns'])for v in (tx,rx))
                    or tx.get('direction')!='out' or rx.get('direction')!='in'
                    or (tx['bus'],tx['device'])==(rx['bus'],rx['device'])
                    or not isinstance(tx.get('data'),str)or not re.fullmatch(r'(?:[0-9a-f]{2}){4,}',tx['data'])or tx['data']!=rx.get('data')):return False
    return True
