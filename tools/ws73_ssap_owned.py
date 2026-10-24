# SPDX-License-Identifier: GPL-2.0-only
"""Ordinary foreground owner policy through the sole real SSAP Engine.

No synthetic peer, controller or security result. The publisher is an actual
slctl process on the guest system bus, with the same uid1000/no-capabilities
scope as this runner. A service-only group deployment is a separate gate.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import re
import json
import os
import secrets
import subprocess
import time
import traceback
from ws73_capture import CaptureError
from ws73_channel_socket import credentials

OUTPUT_MAXIMUM=2*1024*1024


@contextmanager
def observed_process(args,item,out,err,**options):
    """Reuse bounded child pipes; persisted files are evidence sinks,not IPC.

    This byte bound covers existing 128-observation long-value fixtures;it
    changes no protocol budget,request count,deadline or application payload.
    """
    from ws73_dynamic_channels import ApplicationOutput
    process=None;primary=None
    item['output_files']=[str(out),str(err)]
    with ExitStack()as files:
        reader=ApplicationOutput(OUTPUT_MAXIMUM);files.callback(reader.close)
        try:
            sinks=[files.enter_context(p.open('xb'))for p in (out,err)]
            process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**options)
            process.ws73_observed_output=(reader,item,(out,err))
            reader.add(process,item,sinks)
            item['output_collection']['complete']=False
            yield process
        except BaseException as error:
            primary=error
            raise
        finally:
            if process is not None:
                try:
                    if process.poll()is None:process.kill()
                    process.wait(timeout=2)
                    reader.final(item)
                    item['output_collection']['complete']=True
                except BaseException as error:
                    item.setdefault('output_cleanup_errors',[]).append(dict(error=str(error),
                        error_type=type(error).__name__,errno=getattr(error,'errno',None),traceback=traceback.format_exc()))
                    if primary is None:raise
                finally:
                    item.update(exit=process.returncode,end_wall_ns=time.time_ns())
                    if process.stdin:process.stdin.close()


def output_text(process,path):
    """Only an explicitly observed real child supplies a live transcript."""
    state=getattr(process,'ws73_observed_output',None)
    if not isinstance(state,tuple)or len(state)!=3:raise CaptureError('explicit bounded child output required;no live file fallback')
    reader,item,paths=state
    if Path(path)not in paths:raise CaptureError('output path differs from original child')
    reader.drain()
    return item['stdout'if Path(path)==paths[0]else'stderr']


def wait_output(process,timeout):
    """Drain the same child pipes while waiting within one original budget."""
    deadline=time.monotonic()+timeout
    while True:
        state=getattr(process,'ws73_observed_output',None)
        if not isinstance(state,tuple)or len(state)!=3:raise CaptureError('observed child required')
        state[0].drain()
        result=process.poll()
        if result is not None:return result
        if time.monotonic()>=deadline:raise subprocess.TimeoutExpired(process.args,timeout)
        time.sleep(.005)


def verify_output(item):
    record=item.get('output_collection',{})
    if (record.get('method')!='bounded-child-pipes'or type(record.get('maximum_bytes_per_stream'))is not int
            or record['maximum_bytes_per_stream']!=OUTPUT_MAXIMUM or record.get('complete')is not True
            or item.get('output_collection_error')or item.get('output_collection_followup_errors')or item.get('output_cleanup_errors')):
        raise CaptureError('complete original bounded pipe output required')
    for name in ('stdout','stderr'):
        size=item.get('captured_bytes',{}).get(name)
        if type(size)is not int or not 0<=size<=OUTPUT_MAXIMUM or size!=len(item[name].encode('utf-8')):
            raise CaptureError('complete exact output byte accounting required')


def wait_text(process, path, pattern, deadline, min_count=1, *, max_count=16, count_budget=80):
    if type(count_budget)is not int or count_budget not in (80,128)or not 1<=max_count<=count_budget or not 1<=min_count<=max_count:raise CaptureError('bounded output observation count required')
    while True:
        text=output_text(process,path)
        matches=re.findall(pattern,text,re.M)
        if len(matches)>=min_count:return matches,text
        if process.poll() is not None or time.monotonic()>=deadline:
            raise CaptureError('owned service stopped or original observation deadline: '+text)
        time.sleep(.01)


@contextmanager
def publisher(run,row,sender,policy,*,collection='ssap_owned',label=None,sdk_api=None,read_only=False,updates=False,application_uid=1000,operations=5):
    if type(operations)is not int or operations not in (3,5) or (operations!=5 and sdk_api is not None):
        raise CaptureError('explicit CLI READ/WRITE_COMMAND or original publisher operations required')
    if application_uid not in (1000,1005):raise CaptureError('fixed publisher test role required')
    if application_uid==1005:
        from ws73_application_role import require_vm
        require_vm('ws73.ssap_subscription=1')
        if sdk_api not in ('c','python'):raise CaptureError('service-only publisher requires existing SDK consumer')
    source,target=row['owners'][sender],row['owners'][1-sender]
    secret=secrets.token_hex(32);value=secrets.token_hex(32);uuid=secrets.token_hex(16);service=secrets.token_hex(16)
    prefix=run.output/f'ssap-owned-{row["phase"]}-{sender}-{label or policy}'
    out=Path(str(prefix)+'.stdout');err=Path(str(prefix)+'.stderr')
    args=[str(run.args.slctl),'--adapter',target['owner']['path'],'ssap-serve',service,uuid,str(operations),'36',secret,policy]
    environment=None
    if sdk_api is not None:
        from ws73_application_client import application_environment,owned_arguments
        args=owned_arguments(sdk_api,target,service,uuid,secret,policy,read_only=read_only,
            update_connection=target['object']['path'] if updates else None)
        environment=application_environment()
    item=dict(sender=sender,target=1-sender,policy=policy,secret=secret,value=value,uuid=uuid,service=service,args=args,start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
    if operations!=5:item['operations']=operations
    if sdk_api is not None:item.update(publisher_api=sdk_api,environment=environment)
    row.setdefault(collection,[]).append(item);run.save();process=None
    try:
        with observed_process(args,item,out,err,env=dict(os.environ,**environment)if environment else None,stdin=subprocess.PIPE,text=True,**({'user':1005,'group':1005,'extra_groups':[]}if application_uid==1005 else {}))as process:
            if application_uid==1005:
                from ws73_application_client import process_identity
                item['credentials'],item['process_status']=process_identity(process.pid,1005)
            else:item['credentials']=credentials(process.pid)
            item.update(pid=process.pid);run.save()
            matches,_=wait_text(process,out,r'^SsapOwnedService: start=(\d+) end=(\d+) property=(\d+); local registration only$',time.monotonic()+5)
            if len(matches)!=1:raise CaptureError('one actual owned registration required')
            if sdk_api is not None and output_text(process,out).splitlines()[0]!=f'SdkOwnedAPI: api={sdk_api} client_closed=true':
                raise CaptureError('actual SDK original caller and parent-close barrier required')
            start,end,handle=map(int,matches[0]);item.update(start=start,end=end,handle=handle);run.save()
            yield process,item
    finally:
        item['end_wall_ns']=time.time_ns();run.save()


def value_snapshot(process,item,expected,*,limit=16):
    version=item.get('ssap_shared_pressure_contract_version')
    if version is not None and(type(version)is not int or version!=1):raise CaptureError('explicit shared-pressure value observation contract required')
    budget=128 if version is not None else 80
    # Reject a caller/profile mismatch before sending the actual command.
    if type(limit)is not int or not 1<=limit<=budget:raise CaptureError('bounded value observation count required')
    path=Path(item['output_files'][0]);pattern=r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$'
    count=len(re.findall(pattern,output_text(process,path),re.M));observation=dict(start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns())
    if count>=limit:raise CaptureError('value observation count exhausted before command')
    process.stdin.write('value\n');process.stdin.flush()
    values,_=wait_text(process,path,pattern,time.monotonic()+2,min_count=count+1,max_count=limit,count_budget=budget)
    if len(values)!=count+1 or values[-1]!=(str(item['handle']),expected):raise CaptureError('original owner application value snapshot differs')
    observation.update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns(),handle=item['handle'],value=expected,ordinal=count+1)
    item.setdefault('value_snapshots',[]).append(observation);return observation


def await_removed(run,target,start):
    deadline=time.monotonic()+2
    while True:
        c=run.command([str(run.args.slctl),'--adapter',target['owner']['path'],'ssap-list'],max(.001,deadline-time.monotonic()),collection='ssap_owned_cleanup')
        if time.monotonic()>deadline:raise CaptureError('original owner cleanup observation deadline')
        if c['exit']:raise CaptureError('local metadata cleanup query failed')
        lists=re.findall(r'^SsapLocalServices: (.+)$',c['stdout'],re.M)
        if len(lists)!=1:raise CaptureError('one actual local metadata list required')
        if not any(v[0]==start for v in json.loads(lists[0])):return c
        if time.monotonic()>=deadline:raise CaptureError('service survived its unique owner')
        time.sleep(.01)


def execute(run,row):
    row['ssap_owned_required']=True;row['ssap_owned']=[];run.save()
    for sender in (0,1):
        source,target=row['owners'][sender],row['owners'][1-sender]
        for policy in ('allow','deny'):
            with publisher(run,row,sender,policy) as (process,item):
                h=item['handle'];level=row.get('security_requirement',0)
                def command(words):return run.command([str(run.args.slctl),'--adapter',source['owner']['path'],*words],10,collection='ssap_owned')
                item['read']=command(['ssap-read',source['object']['path'],str(h),str(level)])
                item['uuid_read']=command(['ssap-read-uuid',source['object']['path'],'16','65535',item['uuid'],str(level)])
                item['write']=command(['ssap-write',source['object']['path'],str(h),item['value'],str(level)])
                item['read_after']=command(['ssap-read',source['object']['path'],str(h),str(level)])
                for name in ('read','write','read_after'):
                    c=item[name]
                    if policy=='allow' and c['exit']:raise CaptureError('actual owned approval failed')
                    if policy=='deny' and (not c['exit'] or f'peer {"write" if name=="write" else "read"} error 9' not in c['stderr']):raise CaptureError('actual owner refusal required')
                if item['uuid_read']['exit']:raise CaptureError('actual owned UUID transaction failed')
                expected=item['value'] if policy=='allow' else item['secret']
                value_snapshot(process,item,expected);item['local_value']=expected
                process.kill();item['owner_exit']=process.wait(timeout=2);item['owner_exit_wall_ns']=time.time_ns()
                item['after_owner_exit']=await_removed(run,target,item['start'])
                item['removed_read']=command(['ssap-read',source['object']['path'],str(h),str(level)])
                if not item['removed_read']['exit'] or 'peer read error 4' not in item['removed_read']['stderr']:raise CaptureError('retired owner handle must fail over real SMTC')


def corroborate(row,matched):
    if not row.get('ssap_owned_required'):return [],{0:0,1:0}
    items=row.get('ssap_owned',[]);owners=row['owners'];proof=[];credit={0:0,1:0};fresh=set()
    if len(items)!=4 or {(i['sender'],i['policy']) for i in items}!={(s,p) for s in (0,1) for p in ('allow','deny')}:
        raise CaptureError('both directions and actual allow/deny owned policies required')
    from ws73_ssap_access import value_operations
    for item in items:
        s,t=item['sender'],item['target'];h=item['handle'];secret=bytes.fromhex(item['secret']);value=bytes.fromhex(item['value']);uuid=bytes.fromhex(item['uuid']);allow=item['policy']=='allow'
        for raw in (secret,value,uuid,bytes.fromhex(item['service'])):
            if len(raw) not in (16,32) or raw in fresh:raise CaptureError('fresh owned transaction identifiers and payloads required')
            fresh.add(raw)
        expected=owners[t]['owner']['path']
        if t!=1-s or item['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',expected,'ssap-serve',item['service'],item['uuid'],'5','36',item['secret'],item['policy']]:raise CaptureError('original owned service arguments required')
        if item['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in item['credentials']['capabilities'].values()):raise CaptureError('ordinary owner without capabilities required')
        if item['exit']!=-9 or item['owner_exit']!=-9 or item['stderr']:raise CaptureError('actual abrupt service owner loss required')
        if item['local_value']!=(value if allow else secret).hex() or f'SsapOwnedValue: handle={h} value={item["local_value"]}' not in item['stdout'].splitlines():raise CaptureError('actual owner-side value verification required')
        decisions=re.findall(r'^SsapAuthorizationDecision: request=(\d+) property=(\d+) data_type=0 write=(true|false) security=(\d+) approved=(true|false); local policy only$',item['stdout'],re.M)
        if len(decisions)!=4 or [d[2] for d in decisions]!=['false','false','true','false'] or any(int(d[1])!=h or int(d[3])!=row.get('security_requirement',0) or d[4]!=str(allow).lower() for d in decisions) or len({d[0] for d in decisions})!=4:raise CaptureError('four original per-request owner decisions required')
        wire=[]
        ops=value_operations(h,uuid,secret,value,0 if allow else 9)+[('removed_read',b'\x08\x03'+h.to_bytes(2,'little')+b'\x00',b'\x09\x0b\x04\x00')]
        for name,request,response in ops:
            c=item[name]
            if not item['start_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('original owned operation interval required')
            if name=='uuid_read':
                if c['exit'] or f'SsapUuidTrace: request={request.hex()} response={response.hex()}' not in c['stdout'].splitlines():raise CaptureError('actual owned UUID result required')
            elif not allow or name=='removed_read':
                error=4 if name=='removed_read' else 9
                if not c['exit'] or f'peer {"write" if name=="write" else "read"} error {error}' not in c['stderr']:raise CaptureError('actual owned wire refusal required')
            else:
                v=secret if name=='read' else value;operation='ssap-write' if name=='write' else 'ssap-read'
                if c['exit'] or f'SsapPeerValue: operation={operation} path={owners[s]["object"]["path"]} handle={h} value={v.hex()}' not in c['stdout'].splitlines():raise CaptureError('peer must validate owned response')
            for a,b,pdu in [(s,t,request),(t,s,response)]:
                frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                wire.append(dict(tx=matched(owners[a],'out',frame,c),rx=matched(owners[b],'in',frame,c)));credit[a]+=1
        metadata=item['after_owner_exit']
        lists=re.findall(r'^SsapLocalServices: (.+)$',metadata['stdout'],re.M)
        if metadata['exit'] or len(lists)!=1 or any(v[0]==item['start'] for v in json.loads(lists[0])):raise CaptureError('actual removed registration metadata required')
        if not item['write']['end_wall_ns']<item['owner_exit_wall_ns']<item['removed_read']['start_wall_ns']:raise CaptureError('owner loss must precede actual remote refusal')
        proof.append(dict(sender=s,policy=item['policy'],wire=wire,owner_lost=True,scope='uid1000 guest system bus;not service-only deployment,crypto identity,Bond or full cancellation matrix'))
    return proof,credit
