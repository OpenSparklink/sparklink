"""Actual ordinary-user SSAP operations. Local configuration is not RF proof."""
import re,secrets,time
from contextlib import contextmanager
from ws73_channel_socket import CaptureError


def execute(run,row,*,value_command=None,services=None,local_value_command=None):
    row['ssap_value_required']=True;row['ssap_read_uuid_required']=True;row['ssap_update_local_rejection_required']=True;row['ssap_values']=[]
    owners=row['owners'];local=[]
    def command(owner,args,expected=None):
        if local_value_command is not None and args[0]=='ssap-local-read':
            return local_value_command(owner,args,expected)
        elif value_command is not None and args[0] in ('ssap-read','ssap-write'):
            receipt=value_command(owner,args,expected)
        else:
            receipt=run.command([str(run.args.slctl),'--adapter',owner['owner']['path'],*args],10,collection='ssap_values')
        if receipt['exit']:raise CaptureError('actual SSAP application operation failed')
        return receipt
    @contextmanager
    def manager_services():
        local=[]
        try:
            for owner in owners:
                value=secrets.token_bytes(32)
                service=secrets.token_bytes(16);property_uuid=secrets.token_bytes(16)
                registered=command(owner,['ssap-register',service.hex(),property_uuid.hex(),'5','0',value.hex()])
                matches=re.findall(r'^SsapLocalService: start=(\d+) end=(\d+) properties=(\d+)$',registered['stdout'],re.M)
                if len(matches)!=1:raise CaptureError('one actual local database registration required')
                start,end,handle=map(int,matches[0]);local.append(dict(owner=owner,start=start,handle=handle,value=value,registration=registered,service_uuid=service.hex(),property_uuid=property_uuid.hex()))
            yield local
        finally:
            row['ssap_local_registrations']=[dict(owner=p['owner'],start=p['start'],handle=p['handle'],registration=p['registration'],service_uuid=p['service_uuid'],property_uuid=p['property_uuid']) for p in local]
            for p in local:command(p['owner'],['ssap-remove',str(p['start'])])
            run.save()
    with services(run,row,command) if services is not None else manager_services() as local:
        from ws73_ssap_discovery import execute as discover
        discover(run,row,command,local)
        row['unsupported_incoming']=[]
        for sender,target in [(0,1),(1,0)]:
            source=owners[sender];prop=local[target]
            args=[str(run.args.slctl),'--adapter',source['owner']['path'],'ssap-observe',source['object']['path'],str(prop['discovered_handle']),'notify','10']
            receipt=run.command(args,10,collection='ssap_values');row['unsupported_incoming'].append(dict(sender=sender,target=target,handle=prop['discovered_handle'],receipt=receipt));run.save()
            if receipt['exit']==0 or 'peer has not advertised requested property update capabilities' not in receipt['stderr']:raise CaptureError('non-notifying actual peer must explicitly reject local receive interest')
        for sequence in range(4):
            for sender,target in [(0,1),(1,0)]:
                source=owners[sender];destination=owners[target];prop=local[target]
                payload=sequence.to_bytes(4,'little')+secrets.token_bytes(28)
                item=dict(sequence=sequence,sender=sender,target=target,handle=prop['discovered_handle'],before=prop['value'].hex(),value=payload.hex(),start_wall_ns=time.time_ns())
                item['property_uuid']=prop['property_uuid']
                item['uuid_read_before']=command(source,['ssap-read-uuid',source['object']['path'],'16','65535',prop['property_uuid']])
                item['read_before']=command(source,['ssap-read',source['object']['path'],str(prop['handle'])],prop['value'])
                item['write']=command(source,['ssap-write',source['object']['path'],str(prop['handle']),payload.hex()],payload)
                item['local_check']=command(destination,['ssap-local-read',str(prop['handle'])],payload)
                item['read_after']=command(source,['ssap-read',source['object']['path'],str(prop['handle'])],payload)
                item['uuid_read_after']=command(source,['ssap-read-uuid',source['object']['path'],'16','65535',prop['property_uuid']])
                item['end_wall_ns']=time.time_ns();row['ssap_values'].append(item);run.save()
                def peer_value(record,operation,value):
                    expected=f"SsapPeerValue: operation={operation} path={source['object']['path']} handle={prop['handle']} value={value}"
                    return expected in record['stdout'].splitlines()
                if not peer_value(item['read_before'],'ssap-read',prop['value'].hex()) or not peer_value(item['write'],'ssap-write',payload.hex()) or not peer_value(item['read_after'],'ssap-read',payload.hex()):raise CaptureError('peer SSAP application did not validate random original/updated value')
                if local_value_command is not None:
                    if item['local_check'].get('value')!=payload.hex():raise CaptureError('actual owner SDK value observation required')
                elif f"SsapLocalValue: handle={prop['handle']} value={payload.hex()}" not in item['local_check']['stdout'].splitlines():raise CaptureError('opposite application local database validation failed')
                prop['value']=payload



def corroborate(row,matched):
    owners=row['owners'];operations=row.get('ssap_values',[])
    if len(operations)!=8:raise CaptureError('four repeated SSAP operations in both directions required')
    seen=set();nonces=set();proof=[];credit={0:0,1:0}
    for item in operations:
        sender,target=item['sender'],item['target'];key=(sender,item['sequence'])
        if sender not in (0,1) or target!=1-sender or key in seen or item['sequence'] not in range(4):raise CaptureError('independent repeated SSAP directions required')
        seen.add(key);value=bytes.fromhex(item['value']);before=bytes.fromhex(item['before']);handle=item['handle'];source=owners[sender];destination=owners[target]
        if value[4:] in nonces:raise CaptureError('SSAP random nonce reused')
        nonces.add(value[4:])
        if len(value)!=32 or len(before)!=32 or int.from_bytes(value[:4],'little')!=item['sequence']:raise CaptureError('SSAP random payload/sequence required')
        registrations=row.get('ssap_local_registrations',[])
        if len(registrations)!=2 or registrations[target]['owner']!=destination or registrations[target]['handle']!=handle:raise CaptureError('actual target local service identity required')
        registered=registrations[target];owned=row.get('ssap_registration_kind') in ('owned-sdk-v1','owned-sdk-requests-v1')
        expected_local=(f"SsapOwnedService: start={registered['start']} end={handle} property={handle}; local registration only" if owned else f"SsapLocalService: start={registered['start']} end={handle} properties={handle}")
        if registered['registration']['exit'] or registered['registration']['stdout'].splitlines().count(expected_local)!=1:raise CaptureError('original local database registration required')
        for name,op,expected in [('read_before','ssap-read',before),('write','ssap-write',value),('read_after','ssap-read',value)]:
            c=item[name];line=f"SsapPeerValue: operation={op} path={source['object']['path']} handle={handle} value={expected.hex()}"
            if c['exit'] or c['stdout'].splitlines().count(line)!=1:raise CaptureError('original peer application receipt required')
        c=item['local_check']
        if owned:
            publisher=registered['registration'];observations=publisher.get('value_snapshots',[])
            values=re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]*)$',publisher['stdout'],re.M)
            ordinal=c.get('ordinal',0)
            if (c not in observations or not 1<=ordinal<=len(values) or values[ordinal-1]!=(str(handle),value.hex())
                    or c.get('api')!=publisher['api'] or c.get('publisher_pid')!=publisher['pid']
                    or c['handle']!=handle or c['value']!=value.hex()
                    or not item['write']['end_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=item['read_after']['start_wall_ns']):raise CaptureError('actual original owner SDK value snapshot required')
        else:
            line=f"SsapLocalValue: handle={handle} value={value.hex()}"
            if c['exit'] or c['stdout'].splitlines().count(line)!=1:raise CaptureError('opposite actual local-value validation required')
        def frame(payload):return bytes([10,0])+len(payload).to_bytes(2,'little')+payload
        read=bytes([8,3])+handle.to_bytes(2,'little')+b'\0';write=bytes([13,35])+handle.to_bytes(2,'little')+b'\0'+value
        wire=[]
        for name,a,b,payload in [('read_before',source,destination,read),('read_before',destination,source,b'\x09\x03'+before),('write',source,destination,write),('write',destination,source,bytes([14,3])+handle.to_bytes(2,'little')+b'\0'+value),('read_after',source,destination,read),('read_after',destination,source,b'\x09\x03'+value)]:
            window=item[name]
            if not item['start_wall_ns']<=window['start_wall_ns']<=window['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('original command interval required')
            wire.append(dict(tx=matched(a,'out',frame(payload),window),rx=matched(b,'in',frame(payload),window)))
            credit[0 if a==owners[0] else 1]+=1
        uuid_wire=[]
        if row.get('ssap_read_uuid_required'):
            uuid=bytes.fromhex(item['property_uuid'])
            if len(uuid)!=16 or registered['property_uuid']!=item['property_uuid']:raise CaptureError('original target UUID required')
            request=b'\x0a\x01\x10\x00\xff\xff\x00'+uuid
            for name,expected in [('uuid_read_before',before),('uuid_read_after',value)]:
                c=item[name];response=b'\x0b\x03'+handle.to_bytes(2,'little')+expected
                line=f"SsapUuidValue: path={source['object']['path']} handle={handle} success=true error=0 value={expected.hex()}"
                trace=f"SsapUuidTrace: request={request.hex()} response={response.hex()}"
                if c['exit'] or c['stdout'].splitlines().count(line)!=1 or c['stdout'].splitlines().count(trace)!=1:raise CaptureError('original peer UUID value and raw trace required')
                if not item['start_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('UUID request original interval required')
                uuid_wire.append(dict(request=dict(tx=matched(source,'out',frame(request),c),rx=matched(destination,'in',frame(request),c)),response=dict(tx=matched(destination,'out',frame(response),c),rx=matched(source,'in',frame(response),c))))
                credit[sender]+=1;credit[target]+=1
        proof.append(dict(sequence=item['sequence'],sender=sender,target=target,handle=handle,value=item['value'],wire=wire,uuid_wire=uuid_wire,receipts={k:item[k] for k in ['read_before','write','local_check','read_after']}))
    if row.get('ssap_update_local_rejection_required'):
        rows=row.get('unsupported_incoming',[])
        if len(rows)!=2 or {x['sender'] for x in rows}!={0,1}:raise CaptureError('both actual peer local receive rejections required')
        for item in rows:
            sender,target=item['sender'],item['target'];r=item['receipt'];source=owners[sender]
            expected=['ssap-observe',source['object']['path'],str(item['handle']),'notify','10']
            if target!=1-sender or r['exit']==0 or r['args'][-5:]!=expected or 'peer has not advertised requested property update capabilities' not in r['stderr']:raise CaptureError('actual unsupported local receive receipt required')
    return proof,credit
