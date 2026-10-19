# SPDX-License-Identifier: GPL-2.0-only
"""Finite receiver exit/deadline gates through the sole production SSAP actor.

Actual SDK owner prompts and complete paired USB responses are barriers. A
server configuration observation alone does not prove the peer saw its reply.
No simulated success, extra wire loop or changed production deadline.
"""
from pathlib import Path
from contextlib import contextmanager
import errno
import hashlib
import json
import os
import re
import secrets
import tempfile
import time

from ws73_capture import CaptureError, read_capture
from ws73_application_client import application_environment, authorization_context, owned_arguments
from ws73_ssap_owned import publisher, wait_text, await_removed
from ws73_ssap_update_delivery import configuration, discover, discovery_wire, sdk_receipt
from ws73_daemon_hold import Invocation

STATUS='REAL_RECEIVE_EXIT_DEADLINE_CLEANUP_PENDING_PAIRED_CAPTURE'
CASES=['exit-enable-pending','exit-enabled','original-deadline']
BUSY='SSAP client sequence owned by receive transaction'


@contextmanager
def receiver(run,arguments,label):
    """Reuse the existing live-pipe owner; seal its original prefix and suffix."""
    start=time.monotonic_ns();invocation=Invocation(arguments,'ssap-receive',env=dict(os.environ,**application_environment()))
    invocation.row.update(environment=application_environment(),start_monotonic_ns=start)
    run.data.setdefault('ssap_receive_applications',[]).append(invocation.row);run.save()
    try:
        yield invocation
    except BaseException as error:
        invocation.row.update(collector_error=str(error),collector_error_type=type(error).__name__)
        raise
    finally:
        if invocation.process.poll()is None:invocation.process.kill()
        invocation.finish(timeout=2)
        invocation.row['end_monotonic_ns']=time.monotonic_ns()
        files=[]
        for stream in ['stdout','stderr']:
            path=run.output/f'receive-{label}.{stream}'
            with path.open('xb')as target:target.write(invocation.row[stream].encode())
            files.append(str(path))
        invocation.row['output_files']=files;run.save()


def requested(args,*,passthrough):
    value=getattr(args,'ssap_update_lifecycle_verify',False)
    if type(value)is not bool:raise ValueError('explicit receive lifecycle boolean required')
    if value and (not passthrough or not getattr(args,'ssap_update_delivery_verify',False)
            or getattr(args,'channel_socket_rounds',4)!=4 or getattr(args,'channel_socket_bytes',61)!=61):
        raise ValueError('receive lifecycle requires the same protected real update delivery gate')
    return value


def prompt(owner,item,server,value):
    rows,_=wait_text(owner,Path(item['output_files'][0]),r'^SdkAuthorizationRequest: (.+)$',
        time.monotonic()+3,min_count=len(item.setdefault('prompts',[]))+1)
    if len(rows)!=len(item['prompts'])+1:raise CaptureError('one original typed prompt at a time required')
    context=json.loads(rows[-1]);authorization_context(context,item['publisher_api'],level=2,data_type=2)
    expected=[server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],item['handle']]
    if ([context[k]for k in ['index','generation','lifetime','handle','property']]!=expected
            or context['value']!=bytes([value,0]).hex() or not context['write']
            or time.monotonic_ns()>=context['deadline_ns']):raise CaptureError('actual current typed configuration prompt required')
    event=dict(context=context,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
    item['prompts'].append(event);return event


def approve(owner,item,event):
    context=event['context'];at=time.monotonic_ns()
    if at>=context['deadline_ns']:raise CaptureError('never approve an expired original context')
    answer=dict(input_wall_ns=time.time_ns(),input_monotonic_ns=at)
    owner.stdin.write(f'yes {context["token"]}\n');owner.stdin.flush()
    rows,_=wait_text(owner,Path(item['output_files'][0]),r'^SdkAuthorizationReply: (.+)$',
        min(time.monotonic()+2,context['deadline_ns']/1e9),min_count=len(item.setdefault('answers',[]))+1)
    if len(rows)!=len(item['answers'])+1:raise CaptureError('one actual SDK reply per original context required')
    answer['receipt']=json.loads(rows[-1]);item['answers'].append(answer);return answer


def barrier_request(row,item,case,mode,remaining_ms):
    phase=row['phase'];sequence=phase*6+CASES.index(case['kind'])*2+int(mode==0)
    owners=[dict(bus=v['owner']['bus'],device=v['owner']['device'],index=v['owner']['index'],generation=v['owner']['generation'],lifetime=v['object']['lifetime'],handle=v['object']['handle'])for v in row['owners']]
    return dict(version=1,sequence=sequence,phase=phase,mode=mode,property=item['handle'],controllers=owners,
        start_wall_ns=case['start_wall_ns'],deadline_wall_ns=time.time_ns()+remaining_ms*1_000_000,remaining_ms=remaining_ms)


def check_request(request,sequence):
    if (set(request)!={'version','sequence','phase','mode','property','controllers','start_wall_ns','deadline_wall_ns','remaining_ms'}
            or any(type(request[k])is not int for k in request if k!='controllers')
            or request['version']!=1 or request['sequence']!=sequence or not 0<=sequence<12
            or request['phase']!=sequence//6 or request['mode']!=(0 if sequence%2 else 1+sequence//6)
            or not 1<=request['property']<=65535 or not 1<=request['remaining_ms']<=2000
            or not 0<request['start_wall_ns']<request['deadline_wall_ns']):raise CaptureError('invalid bounded capture barrier request')
    owners=request['controllers']
    if not isinstance(owners,list)or len(owners)!=2:raise CaptureError('two original controllers required')
    for entry in owners:
        if (not isinstance(entry,dict)or set(entry)!={'bus','device','index','generation','lifetime','handle'}
                or any(type(v)is not int or v<0 for v in entry.values())
                or not 0<entry['bus']<=255 or not 0<entry['device']<=127 or entry['index']>65535
                or not 0<entry['generation']<2**64 or not 0<entry['lifetime']<2**64 or entry['handle']>4095):raise CaptureError('invalid original controller identity')
    if (owners[0]['bus'],owners[0]['device'])==(owners[1]['bus'],owners[1]['device'])or owners[0]['index']==owners[1]['index']:raise CaptureError('distinct controllers required')


def capture_once(output,capture,request,observations):
    """One bounded Host-side prefix decode; never make raw capture app-readable."""
    if len(observations)>=64:raise CaptureError('live capture observation budget exceeded')
    with Path(capture).open('rb')as source:raw=source.read(16*1024*1024+1)
    if len(raw)>16*1024*1024:raise CaptureError('live capture barrier byte budget exceeded')
    observation=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());observations.append(observation)
    owners=request['controllers'];s=request['phase'];t=1-s;mode=request['mode'];h=request['property']
    with tempfile.NamedTemporaryFile(dir=output,prefix='capture-prefix-')as snapshot:
        snapshot.write(raw);snapshot.flush()
        try:decoded=read_capture(snapshot.name,[(v['bus'],v['device'])for v in owners])
        except CaptureError as error:
            if str(error)not in ['truncated pcap record header','truncated USB packet/header','unfinished OUT submission at capture end']:raise
            observation['partial']=str(error);return None
    pdu=b'\x0e\x03'+h.to_bytes(2,'little')+bytes([2,mode,0]);frame=(b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu).hex();legs=[]
    for index,direction in [(t,'out'),(s,'in')]:
        entry=owners[index]
        found=[p for p in decoded['acb_packets']if (p['bus'],p['device'],p['handle'],p['direction'],p.get('boundary',0),p['data'])==
            (entry['bus'],entry['device'],entry['handle'],direction,0,frame)
            and request['start_wall_ns']<=p['wall_ns']<=request['deadline_wall_ns']]
        if len(found)>1:raise CaptureError('ambiguous repeated configuration response at live barrier')
        legs.extend(found)
    if len(legs)==2:return dict(mode=mode,observations=observations,tx=legs[0],rx=legs[1],host_observed_monotonic_ns=time.monotonic_ns())
    return None


class CaptureCoordinator:
    """Narrow evidence-only responder on the existing Host monitor loop.

    No USB access,protocol mutation or privilege grant. The guest can request
    only twelve fixed type2 response observations,not paths or arbitrary data.
    Host and guest monotonic clocks are never compared or subtracted.
    """
    def __init__(self,share,output,record):
        self.share=Path(share);self.root=self.share/'application/passthrough-control/receive-response-barriers'
        self.output=Path(output);self.record=record;self.active=None
        record.update(status='WAITING_FOR_ORIGINAL_CAPTURE_REQUESTS',events=[],complete=False)

    def poll(self):
        if self.record['complete']or self.record['status']=='FAIL':return
        sequence=len(self.record['events'])if self.active is None else self.active['sequence']
        path=self.root/f'request-{sequence:02}.json';reply=self.root/f'reply-{sequence:02}.json'
        if not path.exists():return
        if (path.is_symlink()or self.root.is_symlink()or not path.resolve().is_relative_to(self.share.resolve())):
            self.record.update(status='FAIL',error='capture request path escaped fixed evidence root');return
        from ws73_diagnostic_hold import write_marker
        try:
            with path.open('rb')as stream:raw=stream.read(4097)
            if len(raw)>4096:raise CaptureError('capture request byte budget')
            digest=hashlib.sha256(raw).hexdigest()
            if self.active is None:
                request=json.loads(raw);check_request(request,sequence)
                if raw!=(json.dumps(request)+'\n').encode():raise CaptureError('noncanonical capture request identity')
                self.active=dict(sequence=sequence,request=request,request_sha256=digest,observations=[],status='WAITING',host_deadline_ns=time.monotonic_ns()+request['remaining_ms']*1_000_000)
                self.record['events'].append(self.active)
            entry=self.active
            if digest!=entry['request_sha256']:raise CaptureError('capture request changed while pending')
            if time.monotonic_ns()>=entry['host_deadline_ns']:raise CaptureError('original capture observation deadline')
            result=capture_once(self.output,self.share/'ws73.pcap',entry['request'],entry['observations'])
            if result is None:return
            if time.monotonic_ns()>=entry['host_deadline_ns']:raise CaptureError('original capture observation deadline')
            result.update(sequence=sequence,request_sha256=digest)
            entry.update(status='CAPTURED',result=result)
            write_marker(reply,dict(status='CAPTURED',sequence=sequence,request_sha256=digest,result=result))
            self.active=None
            if len(self.record['events'])==12:self.record.update(status='TWELVE_ORIGINAL_CAPTURE_RESPONSES_OBSERVED',complete=True)
        except (CaptureError,ValueError,TypeError,KeyError,OSError)as error:
            self.record.update(status='FAIL',error=str(error))
            if not reply.exists():write_marker(reply,dict(status='FAIL',error='capture evidence rejected'))


def response_barrier(run,row,item,case,mode,deadline):
    from ws73_diagnostic_hold import write_marker
    remaining_ms=int((deadline-time.monotonic())*1000)
    request=barrier_request(row,item,case,mode,remaining_ms);check_request(request,request['sequence'])
    root=run.output/'receive-response-barriers';root.mkdir(exist_ok=True)
    path=root/f'request-{request["sequence"]:02}.json';reply=root/f'reply-{request["sequence"]:02}.json'
    write_marker(path,request);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    for _ in range(512):
        if time.monotonic()>=deadline:break
        if reply.exists():
            with reply.open('rb')as stream:raw=stream.read(128*1024+1)
            if len(raw)>128*1024:raise CaptureError('capture responder result byte budget')
            result=json.loads(raw)
            if (result.get('status')!='CAPTURED'or result.get('sequence')!=request['sequence']or result.get('request_sha256')!=digest):raise CaptureError('capture observer failure/stale response')
            value=result['result']
            if value.get('sequence')!=request['sequence']or value.get('request_sha256')!=digest:raise CaptureError('capture response identity mismatch')
            if time.monotonic()>=deadline:break
            return dict(value,observed_wall_ns=time.time_ns(),observed_monotonic_ns=time.monotonic_ns(),private_capture_readable=os.access('/evidence/ws73.pcap',os.R_OK))
        time.sleep(.005)
    raise CaptureError('actual paired configuration response observer deadline/budget')


def validate_coordination(rows,record):
    if not valid_observer_summary(record):raise CaptureError('all original Host capture observations required')
    barriers=[case[key]for row in rows for item in row['ssap_receive_lifecycle']for case in item['cases']for key in ['enable_wire_barrier','disable_wire_barrier']]
    if len(barriers)!=12:raise CaptureError('twelve original guest barriers required')
    for sequence,(guest,host)in enumerate(zip(barriers,record['events'],strict=True)):
        check_request(host['request'],sequence)
        if (host.get('status')!='CAPTURED'or host.get('sequence')!=sequence or guest.get('sequence')!=sequence
                or type(guest.get('private_capture_readable'))is not bool
                or guest.get('request_sha256')!=host['request_sha256']
                or {k:v for k,v in guest.items()if k not in ['observed_wall_ns','observed_monotonic_ns','private_capture_readable']}!=host['result']):raise CaptureError('guest barrier differs from actual Host observation')


def valid_observer_summary(record):
    if (not isinstance(record,dict)or record.get('complete')is not True
            or record.get('status')!='TWELVE_ORIGINAL_CAPTURE_RESPONSES_OBSERVED'
            or not isinstance(record.get('events'),list)or len(record['events'])!=12):return False
    try:
        for sequence,event in enumerate(record['events']):
            check_request(event['request'],sequence)
            digest=hashlib.sha256((json.dumps(event['request'])+'\n').encode()).hexdigest();result=event['result']
            if (event['status']!='CAPTURED'or type(event['sequence'])is not int or event['sequence']!=sequence
                    or event['request_sha256']!=digest or result.get('request_sha256')!=digest
                    or type(result.get('sequence'))is not int or result['sequence']!=sequence
                    or type(result.get('mode'))is not int or result.get('mode')!=event['request']['mode']
                    or not isinstance(result.get('observations'),list)or not 1<=len(result['observations'])<=64
                    or any(not isinstance(result.get(k),dict)or not result[k]for k in ['tx','rx'])
                    or type(result.get('host_observed_monotonic_ns'))is not int):return False
    except (CaptureError,ValueError,TypeError,KeyError,AttributeError):return False
    return True


def execute(run,row,business):
    if row.get('security_requirement')!=2:raise CaptureError('actual mechanism2 required')
    row.update(ssap_receive_lifecycle_required=True,ssap_receive_lifecycle=[]);run.save()
    s=row['phase']%2;peer,server=row['owners'][s],row['owners'][1-s]
    api='c'if s==0 else'python';other='python'if api=='c'else'c';mode=1+s
    with publisher(run,row,s,'ask',collection='ssap_receive_lifecycle',label='receive-lifecycle',sdk_api=api,updates=True)as(owner,item):
        discover(run,peer,item);item['cases']=[];run.save()
        for kind in CASES:
            case=dict(kind=kind,mode=mode,start_wall_ns=time.time_ns());item['cases'].append(case);run.save()
            prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
            arguments=prefix+['update-error'if kind=='original-deadline'else'update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(item['handle']),str(mode)]
            if kind=='original-deadline':arguments += [str(errno.ETIMEDOUT),'2000']
            else:arguments += [secrets.token_hex(32),secrets.token_hex(32)]
            def read():return run.command([str(run.args.slctl),'--adapter',peer['owner']['path'],'ssap-read',peer['object']['path'],str(item['handle']),'2'],2,collection='ssap_receive_observations')
            def barrier(process,record):
                from ws73_channel_socket import credentials
                record['credentials']=credentials(process.pid);case['application']=record;run.save()
                raw=invocation.until(rb'^(\{[^\n]*"stage"\s*:\s*"ssap_update_wait"[^\n]*\})\n',timeout=3,limit=4096,label='original SDK receive call')
                call=json.loads(raw);case['call']=call
                enabled=prompt(owner,item,server,mode);case['enable_prompt']=enabled;run.save()
                if kind=='exit-enable-pending':
                    case['pending_configuration']=configuration(owner,item,0,process)
                    process.kill();case['process_exit']=process.wait(timeout=2)
                    case.update(exit_wall_ns=time.time_ns(),exit_monotonic_ns=time.monotonic_ns());run.save()
                    case['busy_read']=read()
                    if not case['busy_read']['exit']or BUSY not in case['busy_read']['stderr']:raise CaptureError('old receive transaction lost before real enable response')
                    case['business_window']=dict(start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns());run.save()
                    business(min(enabled['context']['deadline_ns'],call['deadline_ns'])/1e9-.1)
                    case['business_window'].update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns());run.save()
                case['enable_answer']=approve(owner,item,enabled);run.save()
                case['enable_wire_barrier']=response_barrier(run,row,item,case,mode,min(time.monotonic()+2,call['deadline_ns']/1e9))
                case['enabled']=configuration(owner,item,mode)
                if kind!='exit-enable-pending':
                    if kind=='exit-enabled':process.kill()
                    case['process_exit']=process.wait(timeout=max(.001,call['deadline_ns']/1e9-time.monotonic()+1))
                    case.update(exit_wall_ns=time.time_ns(),exit_monotonic_ns=time.monotonic_ns());run.save()
                anchor=call['deadline_ns']if kind=='original-deadline'else case['exit_monotonic_ns']
                case['cleanup_observation_deadline_ns']=anchor+5_000_000_000
                disabled=prompt(owner,item,server,0);case['disable_prompt']=disabled
                case['disable_answer']=approve(owner,item,disabled);run.save()
                case['disable_wire_barrier']=response_barrier(run,row,item,case,0,min(time.monotonic()+2,(anchor+5_000_000_000)/1e9))
                case['disabled']=configuration(owner,item,0)
                case['new_read_attempts']=[]
                for _ in range(16):
                    if time.monotonic_ns()>=anchor+5_000_000_000:raise CaptureError('fixed cleanup observation deadline')
                    command=read();case['new_read_attempts'].append(command);run.save()
                    if not command['exit']:
                        if f'value={item["secret"]}'not in command['stdout']:raise CaptureError('new same-actor peer value differs')
                        break
                    if BUSY not in command['stderr']:raise CaptureError('same SSAP actor did not remain usable after cleanup')
                    time.sleep(.01)
                else:raise CaptureError('finite same-actor cleanup convergence budget')
            with receiver(run,arguments,f'{row["phase"]}-{kind}')as invocation:
                case['application']=invocation.row;run.save()
                barrier(invocation.process,invocation.row)
            case['end_wall_ns']=time.time_ns();run.save()
        owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2)
        if owner.returncode:raise CaptureError('original publisher unregister failed')
        item['cleanup']=await_removed(run,server,item['start']);run.save()
    row['ssap_receive_lifecycle_status']=STATUS;run.save()


def ordinary(record):
    ids=record.get('credentials',{});caps=ids.get('capabilities',{})
    if (ids.get('uids')!=[1000]*4 or set(caps)!={'CapEff','CapPrm','CapAmb','CapInh'}
            or any(int(v,16)for v in caps.values())):raise CaptureError('actual cap-zero ordinary application required')


def validate_prefixes(rows,path):
    """Reconstruct every live barrier prefix from the original sealed capture."""
    with Path(path).open('rb')as source:raw=source.read(64*1024*1024+1)
    if len(raw)>64*1024*1024:raise CaptureError('sealed capture prefix replay byte budget')
    if len(rows)!=2:raise CaptureError('both original connection roles required for prefix replay')
    for row in rows:
        if row.get('ssap_receive_lifecycle_required')is not True:raise CaptureError('missing receive lifecycle request')
        items=row.get('ssap_receive_lifecycle',[])
        if len(items)!=1 or len(items[0].get('cases',[]))!=3:raise CaptureError('missing original capture barrier cases')
        for case in items[0]['cases']:
            for key in ['enable_wire_barrier','disable_wire_barrier']:
                observations=case[key]['observations']
                if not 1<=len(observations)<=64:raise CaptureError('bounded live capture observations required')
                if 'partial'in observations[-1]:raise CaptureError('a partial capture cannot establish a barrier')
                for observation in observations:
                    size=observation['bytes']
                    if (type(size)is not int or not 24<=size<=min(len(raw),16*1024*1024)
                            or hashlib.sha256(raw[:size]).hexdigest()!=observation['sha256']):raise CaptureError('live capture prefix identity differs from sealed original')


def corroborate(row,matched,sdus):
    if not row.get('ssap_receive_lifecycle_required',False):return [],{0:0,1:0}
    items=row.get('ssap_receive_lifecycle',[])
    if row.get('ssap_receive_lifecycle_status')!=STATUS or len(items)!=1 or row.get('security_requirement')!=2:raise CaptureError('complete protected receive lifecycle required')
    item=items[0];s=row['phase']%2;t=1-s;peer,server=row['owners'][s],row['owners'][t];api='c'if s==0 else'python';other='python'if api=='c'else'c';h=item['handle'];mode=1+s
    ordinary(item)
    if (item['sender']!=s or item['target']!=t or item['publisher_api']!=api or item['policy']!='ask' or item['exit']!=0 or item['stderr']
            or item.get('environment')!=application_environment()or item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'ask',update_connection=server['object']['path'])
            or [c.get('kind')for c in item['cases']]!=CASES):raise CaptureError('actual original typed SDK owner and three ordered cases required')
    lines=item['stdout'].splitlines()
    if lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={item["start"]}']:raise CaptureError('complete actual provider stream required')
    prompts=[json.loads(v)for v in re.findall(r'^SdkAuthorizationRequest: (.+)$',item['stdout'],re.M)]
    answers=[json.loads(v)for v in re.findall(r'^SdkAuthorizationReply: (.+)$',item['stdout'],re.M)]
    if prompts!=[v['context']for v in item['prompts']]or answers!=[v['receipt']for v in item['answers']]or len(prompts)!=6 or len(answers)!=6:raise CaptureError('six original typed enable/disable contexts/replies required')
    configuration_rows=[json.loads(v)for v in re.findall(r'^SdkOwnedConfiguration: (.+)$',item['stdout'],re.M)]
    expected_configurations=[v['receipt']for case in item['cases']for v in case.get('pending_configuration',[])+case['enabled']+case['disabled']]
    if configuration_rows!=expected_configurations:raise CaptureError('raw provider configuration receipts differ from observations')
    if len({v['token']for v in prompts})!=6 or len({v['request_id']for v in prompts})!=6 or len({v['epoch']for v in prompts})!=1:raise CaptureError('no context reuse or epoch substitution')
    legs=[];credit={0:0,1:0}
    def exchange(a,b,pdu,window):
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        leg=dict(tx=matched(row['owners'][a],'out',frame,window),rx=matched(row['owners'][b],'in',frame,window));legs.append(leg);credit[a]+=1;return leg
    discovery_wire(item,peer,exchange)
    for ordinal,case in enumerate(item['cases']):
        kind=case['kind'];app=case['application'];call=case['call'];ordinary(app)
        if (type(case['mode'])is not int or case['mode']!=mode or type(app['exit'])is not int or type(case['process_exit'])is not int
                or app['environment']!=application_environment()or app['stderr']):raise CaptureError('actual ordinary receiver and selected mode required')
        output=[json.loads(v)for v in app['stdout'].splitlines()]
        if not output or output[0]!=call or call.get('stage')!='ssap_update_wait'or call.get('api')!=other or call.get('handle')!=h or call.get('mode')!=mode or call.get('client_closed')is not True:raise CaptureError('original public receiver call required')
        if (set(call)!={'stage','api','handle','mode','deadline_ns','client_closed','started_ns','budget_ms'}
                or any(type(call[k])is not int or call[k]<=0 for k in ['handle','mode','deadline_ns','started_ns','budget_ms'])
                or call['budget_ms']!=(2000 if kind=='original-deadline'else 5000)
                or call['deadline_ns']-call['started_ns']!=call['budget_ms']*1_000_000):raise CaptureError('immutable original receive timing required')
        prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
        expected=prefix+['update-error'if kind=='original-deadline'else'update-peer',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode)]
        if app['args'][:-2]!=expected:raise CaptureError('exact actual receiver arguments required')
        if kind=='original-deadline':
            if (app['args'][-2:]!=['110','2000']or app['exit']!=0 or case['process_exit']!=0 or len(output)!=2
                    or call.get('budget_ms')!=2000 or call['deadline_ns']-call.get('started_ns',0)!=2_000_000_000):raise CaptureError('actual immutable receive deadline required')
            terminal=output[1]
            if (set(terminal)!={'stage','api','handle','mode','errno','deadline_ns','returned_ns'}or terminal!={**terminal,'stage':'ssap_update_error','api':other,'handle':h,'mode':mode,'errno':errno.ETIMEDOUT,'deadline_ns':call['deadline_ns']}
                    or not call['deadline_ns']<=terminal['returned_ns']<=case['exit_monotonic_ns']):raise CaptureError('actual SDK ETIMEDOUT at original deadline required')
            anchor=call['deadline_ns']
        else:
            if app['exit']!=-9 or case['process_exit']!=-9 or len(output)!=1 or not all(len(bytes.fromhex(v))==32 for v in app['args'][-2:])or app['args'][-1]==app['args'][-2]:raise CaptureError('actual receiver death with no success required')
            anchor=case['exit_monotonic_ns']
        if (case['cleanup_observation_deadline_ns']!=anchor+5_000_000_000 or not case['start_wall_ns']<=app['start_wall_ns']<=case['exit_wall_ns']<=app['end_wall_ns']<=case['end_wall_ns']<=item['end_wall_ns']):raise CaptureError('original process and bounded cleanup intervals required')
        for j,key in enumerate(['enable','disable']):
            event=case[key+'_prompt'];answer=case[key+'_answer'];context=event['context'];value=mode if j==0 else 0
            authorization_context(context,api,level=2,data_type=2)
            if context!=prompts[ordinal*2+j]or answer['receipt']!=answers[ordinal*2+j]or [context[k]for k in ['index','generation','lifetime','handle','property']]!=[server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],h]or context['value']!=bytes([value,0]).hex():raise CaptureError('original owner/lifetime/type2 proposal must match raw response')
            result=answer['receipt']
            if (type(result.get('result'))is not int or result.get('allow')is not True or result.get('api_called')is not True
                    or result!={'api':api,'token':context['token'],'current_token':context['token'],'allow':True,'api_called':True,'result':0,'returned_ns':result.get('returned_ns')}
                    or not event['monotonic_ns']<=answer['input_monotonic_ns']<=result['returned_ns']<context['deadline_ns']):raise CaptureError('actual current SDK approval before original deadline required')
        for key,wanted in [('enabled',mode),('disabled',0)]:
            values=[sdk_receipt(v,api,h,{'modes'})for v in case[key]]
            if not values or any(type(v['modes'])is not int or not 0<=v['modes']<=3 for v in values)or values[-1]['modes']!=wanted:raise CaptureError('actual bounded server configuration state required')
        if case['disabled'][-1]['end_monotonic_ns']>anchor+5_000_000_000:raise CaptureError('cleanup result exceeded fixed observation bound')
        exchange(s,t,b'\x08\x03'+h.to_bytes(2,'little')+b'\x02',case);exchange(t,s,b'\x09\x03\0\0',case)
        enable=b'\x0d\x23'+h.to_bytes(2,'little')+bytes([2,mode,0]);disable=b'\x0d\x23'+h.to_bytes(2,'little')+b'\x02\0\0'
        replies={}
        for key,request,value in [('enable',enable,mode),('disable',disable,0)]:
            exchange(s,t,request,case);reply=exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+bytes([2,value,0]),case);replies[key]=reply
            barrier=case[key+'_wire_barrier']
            if (barrier['mode']!=value or not barrier['observations']or len(barrier['observations'])>64
                    or any(barrier[k]!={a:b for a,b in reply[k].items()if a!='fragments'}for k in ['tx','rx'])or not case[key+'_answer']['input_wall_ns']<=reply['tx']['wall_ns']<=reply['rx']['wall_ns']<=barrier['observed_wall_ns']):raise CaptureError('actual paired USB reply must establish the live barrier')
        if kind=='exit-enable-pending':
            window=case['business_window'];busy=case['busy_read']
            if not busy['exit']or BUSY not in busy['stderr']or not case['exit_wall_ns']<=busy['start_wall_ns']<=busy['end_wall_ns']<=window['start_wall_ns']<=window['end_wall_ns']<=case['enable_answer']['input_wall_ns']<=replies['enable']['rx']['wall_ns']:raise CaptureError('old physical obligation and held business interval required')
            apps=row['applications']
            if len(apps)!=2 or any(v['exit']or not window['start_wall_ns']<=v['start_wall_ns']<=v['end_wall_ns']<=window['end_wall_ns']for v in apps):raise CaptureError('both ordinary business apps must finish while approval is held')
            pending=[sdk_receipt(v,api,h,{'modes'})for v in case['pending_configuration']]
            if not pending or any(type(v['modes'])is not int or v['modes']!=0 for v in pending):raise CaptureError('pre-approval configuration must remain disabled')
        elif not replies['enable']['rx']['wall_ns']<=case['enable_wire_barrier']['observed_wall_ns']<=case['exit_wall_ns']:raise CaptureError('enabled-case exit must follow actual peer USB receive,not a sleep')
        attempts=case['new_read_attempts']
        if not 1<=len(attempts)<=16:raise CaptureError('finite same-actor request attempts required')
        expected_read=[item['discovery']['args'][0],'--adapter',peer['owner']['path'],'ssap-read',peer['object']['path'],str(h),'2']
        for refused in ([case['busy_read']]if kind=='exit-enable-pending'else[])+attempts[:-1]:
            if refused['args']!=expected_read or not refused['exit']or BUSY not in refused['stderr']:raise CaptureError('only actual unadmitted sequence-busy attempts allowed')
            frame=(b'\x0a\0\x05\0\x08\x03'+h.to_bytes(2,'little')+b'\0').hex()
            if any(p['data']==frame and refused['start_wall_ns']<=p['wall_ns']<=refused['end_wall_ns']for p in sdus):raise CaptureError('busy request reached the wire')
        last=attempts[-1]
        expected_output=[f'Selected {peer["owner"]["path"]}',f'SsapPeerValue: operation=ssap-read path={peer["object"]["path"]} handle={h} value={item["secret"]}']
        if last['args']!=expected_read or last['exit']or last['stderr']or last['stdout'].splitlines()!=expected_output:raise CaptureError('same original actor must actually read peer value after cleanup')
        new=exchange(s,t,b'\x08\x03'+h.to_bytes(2,'little')+b'\0',last);exchange(t,s,b'\x09\x03'+bytes.fromhex(item['secret']),last)
        if new['tx']['wall_ns']<replies['disable']['rx']['wall_ns']:raise CaptureError('new wire request preceded confirmed disable response')
    return [dict(sender=s,target=t,publisher=api,peer=other,cases=CASES,confirmed_cleanups=3,
        receiver_exits=2,original_timeouts=1,business_while_prompt_held=row['rounds'],wire=legs,
        scope='Finite actual process exit/deadline,paired disable and same-actor reuse;not universal cancel linearization,fd/Grant/Down/epoch/reuse/ACK/NOCP proof,permissions or recovery qualification')],credit


def valid_summary(proof):
    if not isinstance(proof,dict)or proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED':return False
    rows=proof.get('proofs')
    if not isinstance(rows,list)or len(rows)!=2:return False
    for phase,row in enumerate(rows):
        if not isinstance(row,dict)or type(row.get('phase'))is not int or row.get('phase')!=phase:return False
        items=row.get('ssap_receive_lifecycle')
        if not isinstance(items,list)or len(items)!=1 or not isinstance(items[0],dict):return False
        item=items[0]
        expected=dict(sender=phase,target=1-phase,publisher='c'if phase==0 else'python',peer='python'if phase==0 else'c',cases=CASES,confirmed_cleanups=3,receiver_exits=2,original_timeouts=1,business_while_prompt_held=4)
        if any(type(item.get(k))is not type(v)or item[k]!=v for k,v in expected.items()):return False
        legs=item.get('wire')
        if not isinstance(legs,list)or len(legs)!=34 or any(not isinstance(v,dict)or set(v)!={'tx','rx'}or any(not isinstance(v[k],dict)or not v[k]for k in ['tx','rx'])for v in legs):return False
    return True
