"""Actual ordinary-user SSAP operations. Local configuration is not RF proof."""
import re,secrets,time
from ws73_channel_socket import CaptureError


def execute(run,row):
    row['ssap_value_required']=True;row['ssap_values']=[]
    owners=row['owners'];local=[]
    def command(owner,args):
        receipt=run.command([str(run.args.slctl),'--adapter',owner['owner']['path'],*args],10,collection='ssap_values')
        if receipt['exit']:raise CaptureError('actual SSAP application operation failed')
        return receipt
    for owner in owners:
        value=secrets.token_bytes(32)
        service=secrets.token_bytes(16);property_uuid=secrets.token_bytes(16)
        registered=command(owner,['ssap-register',service.hex(),property_uuid.hex(),'5',value.hex()])
        matches=re.findall(r'^SsapLocalService: start=(\d+) end=(\d+) properties=(\d+)$',registered['stdout'],re.M)
        if len(matches)!=1:raise CaptureError('one actual local database registration required')
        start,end,handle=map(int,matches[0]);local.append(dict(owner=owner,start=start,handle=handle,value=value,registration=registered))
    try:
        for sequence in range(4):
            for sender,target in [(0,1),(1,0)]:
                source=owners[sender];destination=owners[target];prop=local[target]
                payload=sequence.to_bytes(4,'little')+secrets.token_bytes(28)
                item=dict(sequence=sequence,sender=sender,target=target,handle=prop['handle'],before=prop['value'].hex(),value=payload.hex(),start_wall_ns=time.time_ns())
                item['read_before']=command(source,['ssap-read',source['object']['path'],str(prop['handle'])])
                item['write']=command(source,['ssap-write',source['object']['path'],str(prop['handle']),payload.hex()])
                item['local_check']=command(destination,['ssap-local-read',str(prop['handle'])])
                item['read_after']=command(source,['ssap-read',source['object']['path'],str(prop['handle'])])
                item['end_wall_ns']=time.time_ns();row['ssap_values'].append(item);run.save()
                def peer_value(record,operation,value):
                    expected=f"SsapPeerValue: operation={operation} path={source['object']['path']} handle={prop['handle']} value={value}"
                    return expected in record['stdout'].splitlines()
                if not peer_value(item['read_before'],'ssap-read',prop['value'].hex()) or not peer_value(item['write'],'ssap-write',payload.hex()) or not peer_value(item['read_after'],'ssap-read',payload.hex()):raise CaptureError('peer SSAP application did not validate random original/updated value')
                if f"SsapLocalValue: handle={prop['handle']} value={payload.hex()}" not in item['local_check']['stdout'].splitlines():raise CaptureError('opposite application local database validation failed')
                prop['value']=payload
    finally:
        row['ssap_local_registrations']=[dict(owner=p['owner'],start=p['start'],handle=p['handle'],registration=p['registration']) for p in local]
        for p in local:command(p['owner'],['ssap-remove',str(p['start'])])
        run.save()


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
        registered=registrations[target];expected_local=f"SsapLocalService: start={registered['start']} end={handle} properties={handle}"
        if registered['registration']['exit'] or registered['registration']['stdout'].splitlines().count(expected_local)!=1:raise CaptureError('original local database registration required')
        for name,op,expected in [('read_before','ssap-read',before),('write','ssap-write',value),('read_after','ssap-read',value)]:
            c=item[name];line=f"SsapPeerValue: operation={op} path={source['object']['path']} handle={handle} value={expected.hex()}"
            if c['exit'] or c['stdout'].splitlines().count(line)!=1:raise CaptureError('original peer application receipt required')
        c=item['local_check'];line=f"SsapLocalValue: handle={handle} value={value.hex()}"
        if c['exit'] or c['stdout'].splitlines().count(line)!=1:raise CaptureError('opposite actual local-value validation required')
        def frame(payload):return bytes([10,0])+len(payload).to_bytes(2,'little')+payload
        read=bytes([8,3])+handle.to_bytes(2,'little')+b'\0';write=bytes([13,35])+handle.to_bytes(2,'little')+b'\0'+value
        wire=[]
        for name,a,b,payload in [('read_before',source,destination,read),('read_before',destination,source,b'\x09\x03'+before),('write',source,destination,write),('write',destination,source,bytes([14,3])+handle.to_bytes(2,'little')+b'\0'+value),('read_after',source,destination,read),('read_after',destination,source,b'\x09\x03'+value)]:
            window=item[name]
            if not item['start_wall_ns']<=window['start_wall_ns']<=window['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('original command interval required')
            wire.append(dict(tx=matched(a,'out',frame(payload),window),rx=matched(b,'in',frame(payload),window)))
            credit[0 if a==owners[0] else 1]+=1
        proof.append(dict(sequence=item['sequence'],sender=sender,target=target,handle=handle,value=item['value'],wire=wire,receipts={k:item[k] for k in ['read_before','write','local_check','read_after']}))
    return proof,credit
