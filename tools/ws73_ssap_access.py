"""Actual per-attribute policy and active-intent gates, not a second Engine."""
import re
import secrets
import time
from ws73_capture import CaptureError


def execute(run,row):
    row['ssap_access_required']=True
    row['ssap_access']=[]
    owners=row['owners'];level=row.get('security_requirement',0)
    def command(owner,args):
        return run.command([str(run.args.slctl),'--adapter',owner['owner']['path'],*args],10,collection='ssap_access')
    for sender in [0,1]:
        source,target=owners[sender],owners[1-sender]
        before=command(target,['ssap-list'])
        refusals=[]
        for access in [4,32,64]:
            c=command(target,['ssap-register',secrets.token_hex(16),secrets.token_hex(16),'5',str(access),secrets.token_hex(32)])
            if c['exit']==0 or ('NotSupported' if access!=64 else 'InvalidArgs') not in c['stderr']:
                raise CaptureError('unsupported authorization/reserved policy must refuse')
            refusals.append(dict(access=access,command=c))
        after=command(target,['ssap-list'])
        if before['exit'] or after['exit'] or before['stdout']!=after['stdout']:raise CaptureError('failed registration mutated service metadata')
        for access in [0,9,18]:
            secret=secrets.token_bytes(32);payload=secrets.token_bytes(32);uuid=secrets.token_bytes(16);service=secrets.token_bytes(16)
            registration=command(target,['ssap-register',service.hex(),uuid.hex(),'5',str(access),secret.hex()])
            match=re.findall(r'^SsapLocalService: start=(\d+) end=(\d+) properties=(\d+)$',registration['stdout'],re.M)
            if registration['exit'] or len(match)!=1:raise CaptureError('actual access registration required')
            start,end,handle=map(int,match[0]);error=8 if access==18 and level<2 else 10 if access==9 and level<1 else 0
            item=dict(sender=sender,target=1-sender,level=level,access=access,start=start,handle=handle,secret=secret.hex(),value=payload.hex(),uuid=uuid.hex(),service=service.hex(),registration=registration,error=error,start_wall_ns=time.time_ns())
            row['ssap_access'].append(item);run.save()
            try:
                item['read']=command(source,['ssap-read',source['object']['path'],str(handle),str(level)])
                item['uuid_read']=command(source,['ssap-read-uuid',source['object']['path'],'16','65535',uuid.hex(),str(level)])
                item['write']=command(source,['ssap-write',source['object']['path'],str(handle),payload.hex(),str(level)])
                item['local_check']=command(target,['ssap-local-read',str(handle)])
                item['read_after']=command(source,['ssap-read',source['object']['path'],str(handle),str(level)])
                if error:
                    if any(item[name]['exit']==0 or f'peer {"write" if name=="write" else "read"} error {error}' not in item[name]['stderr'] for name in ['read','write','read_after']):raise CaptureError('insufficient original receipt must return actual protocol denial')
                    if f'success=false error={error} value=' not in item['uuid_read']['stdout']:raise CaptureError('UUID read must preserve access error entry')
                elif any(item[name]['exit'] for name in ['read','uuid_read','write','read_after']):raise CaptureError('qualified attribute request failed')
                expected=secret if error else payload
                if item['local_check']['exit'] or f'SsapLocalValue: handle={handle} value={expected.hex()}' not in item['local_check']['stdout']:raise CaptureError('denied mutation or accepted write not reflected in opposite local DB')
                if access==0:
                    local_reject=[]
                    for minimum in ([level+1,3] if level<2 else [3]):
                        value=secrets.token_bytes(32)
                        c=command(source,['ssap-write',source['object']['path'],str(handle),value.hex(),str(minimum)])
                        if c['exit']==0 or ('SSAP send intent refused' if minimum<3 else 'minimum0..2') not in c['stderr']:raise CaptureError('active minimum must refuse without raw fallback')
                        local_reject.append(dict(minimum=minimum,value=value.hex(),command=c))
                    item['local_rejections']=local_reject
                    check=command(target,['ssap-local-read',str(handle)]);item['after_local_rejection']=check
                    if check['exit'] or f'SsapLocalValue: handle={handle} value={payload.hex()}' not in check['stdout']:raise CaptureError('rejected active intent changed opposite DB')
            finally:
                item['end_wall_ns']=time.time_ns();item['removal']=command(target,['ssap-remove',str(start)]);run.save()
            if item['removal']['exit']:raise CaptureError('real local cleanup failed')
        row.setdefault('ssap_access_registration_refusals',[]).append(dict(sender=sender,before=before,after=after,refusals=refusals))
        run.save()


def audit_rejections(row,sdus):
    if not row.get('ssap_access_required'):return
    for item in row.get('ssap_access',[]):
        values=[r['value'] for r in item.get('local_rejections',[])]
        # Secret value must never be returned on either USB leg for denied reads.
        if item['error']:values.append(item['secret'])
        for value in values:
            if any(value in p['data'] and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns'] for p in sdus):raise CaptureError('denied secret or locally refused write leaked to USB')


def corroborate(row,matched):
    if not row.get('ssap_access_required'):return [],{0:0,1:0}
    items=row.get('ssap_access',[]);owners=row['owners'];proof=[];credit={0:0,1:0};seen=set()
    if len(items)!=6 or {(i['sender'],i['access']) for i in items}!={(s,a) for s in [0,1] for a in [0,9,18]}:raise CaptureError('both directions and all independent attribute policies required')
    refusal=row.get('ssap_access_registration_refusals',[])
    if len(refusal)!=2 or {v['sender'] for v in refusal}!={0,1}:raise CaptureError('both actual registration refusal sets required')
    for r in refusal:
        if r['before']['exit'] or r['after']['exit'] or r['before']['stdout']!=r['after']['stdout']:raise CaptureError('registration refusal changed actual DB list')
        if [v['access'] for v in r['refusals']]!=[4,32,64] or any(v['command']['exit']==0 or ('NotSupported' if v['access']!=64 else 'InvalidArgs') not in v['command']['stderr'] for v in r['refusals']):raise CaptureError('authorization/reserved registration cannot stage silently')
    def frame(p):return b'\x0a\x00'+len(p).to_bytes(2,'little')+p
    for i in items:
        s,t=i['sender'],i['target'];level=row.get('security_requirement',0);access=i['access'];h=i['handle'];secret=bytes.fromhex(i['secret']);value=bytes.fromhex(i['value']);uuid=bytes.fromhex(i['uuid'])
        if any(v in seen for v in [secret,value,uuid]) or len(secret)!=32 or len(value)!=32 or len(uuid)!=16:raise CaptureError('fresh bounded original attribute payloads required')
        seen.update([secret,value,uuid]);e=8 if access==18 and level<2 else 10 if access==9 and level<1 else 0
        if i['error']!=e or i['level']!=level or t!=1-s:raise CaptureError('expected policy must match original mode and direction')
        reg=i['registration'];expected=[str(access),secret.hex()]
        if reg['exit'] or reg['args'][-2:]!=expected or f'SsapLocalService: start={i["start"]} end={h} properties={h}' not in reg['stdout'].splitlines():raise CaptureError('original security registration arguments required')
        read=b'\x08\x03'+h.to_bytes(2,'little')+b'\x00';write=b'\x0d\x23'+h.to_bytes(2,'little')+b'\x00'+value
        uuid_req=b'\x0a\x01\x10\x00\xff\xff\x00'+uuid
        operations=[('read',read,b'\x09\x0b'+e.to_bytes(2,'little') if e else b'\x09\x03'+secret),
          ('uuid_read',uuid_req,b'\x0b\x0b'+h.to_bytes(2,'little')+e.to_bytes(2,'little') if e else b'\x0b\x03'+h.to_bytes(2,'little')+secret),
          ('write',write,b'\x0e\x07\x01'+h.to_bytes(2,'little')+bytes([e]) if e else b'\x0e\x03'+h.to_bytes(2,'little')+b'\x00'+value),
          ('read_after',read,b'\x09\x0b'+e.to_bytes(2,'little') if e else b'\x09\x03'+value)]
        wire=[]
        for name,request,response in operations:
            c=i[name]
            if not i['start_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=i['end_wall_ns']:raise CaptureError('original attribute command interval required')
            if name=='uuid_read':
                if c['exit'] or f'SsapUuidTrace: request={request.hex()} response={response.hex()}' not in c['stdout'].splitlines():raise CaptureError('actual UUID denial/success raw trace required')
            elif e:
                if c['exit']==0 or f'peer {"write" if name=="write" else "read"} error {e}' not in c['stderr']:raise CaptureError('actual protocol refusal required')
            else:
                expected_value=secret if name=='read' else value
                op='ssap-write' if name=='write' else 'ssap-read'
                if c['exit'] or f'SsapPeerValue: operation={op} path={owners[s]["object"]["path"]} handle={h} value={expected_value.hex()}' not in c['stdout'].splitlines():raise CaptureError('actual peer value validation required')
            for a,b,pdu in [(s,t,request),(t,s,response)]:
                wire.append(dict(tx=matched(owners[a],'out',frame(pdu),c),rx=matched(owners[b],'in',frame(pdu),c)));credit[a]+=1
        local=secret if e else value
        if i['local_check']['exit'] or f'SsapLocalValue: handle={h} value={local.hex()}' not in i['local_check']['stdout'].splitlines():raise CaptureError('opposite DB mutation/isolation check required')
        if access==0:
            rejects=i.get('local_rejections',[]);expected=[level+1,3] if level<2 else [3]
            if [r['minimum'] for r in rejects]!=expected or any(r['command']['exit']==0 or ('SSAP send intent refused' if r['minimum']<3 else 'minimum0..2') not in r['command']['stderr'] for r in rejects):raise CaptureError('active intent minimum rejection required')
            c=i['after_local_rejection']
            if c['exit'] or f'SsapLocalValue: handle={h} value={value.hex()}' not in c['stdout'].splitlines():raise CaptureError('locally refused request changed peer DB')
        if i['removal']['exit']:raise CaptureError('local attribute cleanup failed')
        proof.append(dict(sender=s,target=t,access=access,error=e,wire=wire,peer_value_unchanged=bool(e)))
    return proof,credit
