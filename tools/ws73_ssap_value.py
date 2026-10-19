"""Actual ordinary-user SSAP operations. Local configuration is not RF proof."""
import re,secrets,time
from contextlib import contextmanager
from ws73_channel_socket import CaptureError


LENGTHS = (32,32,32,32,0,1,248,249,250,251,252,253,254,255,1024,2037)


def execute_read_limits(run,row,command,services):
    from ws73_ssap_discovery import execute as discover
    from ws73_ssap_update_delivery import tool_records
    row['ssap_read_limit_tools']=tool_records();row['ssap_read_limits']=[];run.save()
    for size in (2038,2039,2040,2041,2042):
        group=dict(owners=row['owners'],application_bytes=size,cases=[],start_wall_ns=time.time_ns())
        row['ssap_read_limits'].append(group);run.save()
        with services(size,group) as local:
            discover(run,group,command,local)
            for sender in (0,1):
                source=row['owners'][sender];target=row['owners'][1-sender];prop=local[1-sender]
                item=dict(sender=sender,target=1-sender,handle=prop['discovered_handle'],value=prop['value'].hex(),start_wall_ns=time.time_ns())
                group['cases'].append(item);run.save()
                for name,args in [('read',['ssap-read',source['object']['path'],str(item['handle'])]),
                                  ('uuid_read',['ssap-read-uuid',source['object']['path'],'16','65535',prop['property_uuid']])]:
                    item[name]=run.command([str(run.args.slctl),'--adapter',source['owner']['path'],*args],10,collection='ssap_read_limits');run.save()
                if size<=2040:
                    from ws73_application_client import ssap_command
                    item['sdk_read']=ssap_command(run,row,source,['ssap-read',source['object']['path'],str(item['handle'])],prop['value'],expected_size=size)
                item['local_check']=command(target,['ssap-local-read',str(prop['handle'])],prop['value'])
                item['end_wall_ns']=time.time_ns();run.save()
                for name,limit,error in [('read',2040,'peer read error 16'),('uuid_read',2038,'peer requires unsupported SSAP fragmentation')]:
                    result=item[name]
                    if (result['exit']!=0)!=(size>limit) or size>limit and error not in result['stderr']:raise CaptureError('actual opcode-specific MTU result required')
        group['end_wall_ns']=time.time_ns();run.save()


def corroborate_read_limits(row,matched,*,version=2):
    from ws73_ssap_discovery import corroborate as discovery
    groups=row.get('ssap_read_limits',[]);credit={0:0,1:0};proof=[];fresh=set();sdk_seen=[]
    if version>=3 and len(row.get('ssap_language_clients',[]))!=6:raise CaptureError('six original bounded SDK read processes required')
    if [g.get('application_bytes')for g in groups]!=[2038,2039,2040,2041,2042]:raise CaptureError('complete actual read/UUID limit groups required')
    for group in groups:
        if group.get('owners')!=row['owners'] or len(group.get('cases',[]))!=2:raise CaptureError('same-lifetime opposite actual read cases required')
        discovered,used=discovery(group,matched)
        for sender in credit:credit[sender]+=used[sender]
        size=group['application_bytes']
        for sender,item in enumerate(group['cases']):
            target=1-sender;source=row['owners'][sender];destination=row['owners'][target]
            registered=group['ssap_local_registrations'][target];h=item['handle'];value=bytes.fromhex(item['value'])
            if item['sender']!=sender or item['target']!=target or registered['handle']!=h or registered['owner']!=destination or registered.get('value')!=item['value'] or len(value)!=size or value in fresh:raise CaptureError('original whole registered value and discovered peer identity required')
            program=row['ssap_receipts'][0]['args'][0];registration=registered['registration']
            if registration['exit'] or registration['stdout'].splitlines().count(f'SsapLocalService: start={registered["start"]} end={h} properties={h}')!=1 or registration['args']!=[program,'--adapter',destination['owner']['path'],'ssap-register',registered['service_uuid'],registered['property_uuid'],'5','0',item['value']]:raise CaptureError('actual initial whole-value registration required')
            fresh.add(value);local=item['local_check']
            if local['exit'] or local['stdout'].splitlines().count(f'SsapLocalValue: handle={h} value={item["value"]}')!=1 or local['args']!=[program,'--adapter',destination['owner']['path'],'ssap-local-read',str(h)]:raise CaptureError('opposite application must observe unchanged complete local value')
            wire=[]
            for name,request,limit in [('read',b'\x08\x03'+h.to_bytes(2,'little')+b'\0',2040),('uuid_read',b'\x0a\x01\x10\0\xff\xff\0'+bytes.fromhex(registered['property_uuid']),2038)]:
                c=item[name];success=size<=limit
                words=['ssap-read',source['object']['path'],str(h)]if name=='read'else['ssap-read-uuid',source['object']['path'],'16','65535',registered['property_uuid']]
                if c['args']!=[program,'--adapter',source['owner']['path'],*words]:raise CaptureError('exact actual opcode-specific read caller required')
                response=(b'\x09\x03'+value if name=='read'else b'\x0b\x03'+h.to_bytes(2,'little')+value)if success else b'\x09\x0b\x10\0'
                if success:
                    expected=(f'SsapPeerValue: operation=ssap-read path={source["object"]["path"]} handle={h} value={item["value"]}'if name=='read'else f'SsapUuidValue: path={source["object"]["path"]} handle={h} success=true error=0 value={item["value"]}')
                    if c['exit'] or c['stdout'].splitlines().count(expected)!=1:raise CaptureError('actual peer complete boundary read required')
                    if name=='uuid_read'and c['stdout'].splitlines().count(f'SsapUuidTrace: request={request.hex()} response={response.hex()}')!=1:raise CaptureError('actual original UUID boundary trace required')
                elif not c['exit'] or ('peer read error 16'if name=='read'else'peer requires unsupported SSAP fragmentation')not in c['stderr']:raise CaptureError('normative READ_RSP unsupported-fragmentation refusal required')
                if not group['start_wall_ns']<=item['start_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=local['start_wall_ns']<=local['end_wall_ns']<=item['end_wall_ns']<=group['end_wall_ns']<=row['ssap_values'][0]['start_wall_ns']:raise CaptureError('original boundary/read/local-check/recovery intervals required')
                for a,b,pdu in [(sender,target,request),(target,sender,response)]:
                    frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                    packet=dict(tx=matched(row['owners'][a],'out',frame,c),rx=matched(row['owners'][b],'in',frame,c));wire.append(packet);credit[a]+=len(packet['tx'].get('fragments',[packet['tx']]))
            sdk=None
            if version>=3 and size<=2040:
                from ws73_application_client import ssap_receipt
                app=item['sdk_read'];ssap_receipt(app,source,expected_size=size)
                if app not in row['ssap_language_clients']or app in sdk_seen:raise CaptureError('SDK read must belong to one actual registered child')
                sdk_seen.append(app)
                expected_api='c'if sender==row['phase']else'python'
                if app['api']!=expected_api or app['ssap_expected']!=item['value'] or not item['start_wall_ns']<=app['start_wall_ns']<=app['end_wall_ns']<=local['start_wall_ns']:raise CaptureError('actual swapped-role SDK complete read required')
                for a,b,pdu in [(sender,target,b'\x08\x03'+h.to_bytes(2,'little')+b'\0'),(target,sender,b'\x09\x03'+value)]:
                    frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu;packet=dict(tx=matched(row['owners'][a],'out',frame,app),rx=matched(row['owners'][b],'in',frame,app));wire.append(packet);credit[a]+=len(packet['tx'].get('fragments',[packet['tx']]))
                sdk=dict(api=app['api'],application=app)
            elif item.get('sdk_read'):raise CaptureError('unrequested SDK read cannot upgrade old contract')
            proof.append(dict(sender=sender,application_bytes=size,read_success=size<=2040,uuid_success=size<=2038,wire=wire,discovery=discovered if sender==0 else None,**(dict(sdk=sdk)if version>=3 else{})))
    if version>=3 and len(sdk_seen)!=6:raise CaptureError('every actual SDK child must be accounted')
    return proof,credit


def lengths_requested(args,*,passthrough):
    value=getattr(args,'ssap_value_lengths_verify',False)
    if type(value)is not bool:raise ValueError('explicit SSAP length gate boolean required')
    if value and (not passthrough or not getattr(args,'channel_socket_verify',False)
            or getattr(args,'channel_socket_rounds',4)!=4 or getattr(args,'channel_socket_bytes',61)!=61
            or getattr(args,'security_agent',None) is not None
            or any(getattr(args,k,False) for k in ['application_client_verify','ssap_owned_verify',
                'ssap_owned_update_verify','ssap_update_delivery_verify','ssap_update_lifecycle_verify',
                'ssap_owner_lifecycle_verify','ssap_requester_lifecycle_verify','ssap_initialization_verify',
                'channel_socket_close_prefix','channel_socket_burst','channel_socket_boundaries',
                'dynamic_channel_verify','channel_fairness_verify'])):
        raise ValueError('SSAP lengths require dedicated ordinary basic socket gate')
    return value


def length_mtu(row):
    receipts=row.get('ssap_receipts',[])
    if len(receipts)!=2:raise CaptureError('both actual SSAP negotiation receipts required')
    pattern=r'^SsapExchangeInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local_mtu=(\d+) negotiated_mtu=(\d+) request=([0-9a-f]+) peer_reply=([0-9a-f]+) peer_request=([0-9a-f]+) response=([0-9a-f]+)$'
    for owner,receipt in zip(row['owners'],receipts,strict=True):
        matches=re.findall(pattern,receipt['stdout'],re.M)
        if receipt['exit'] or len(matches)!=1:raise CaptureError('one actual negotiation result required')
        found=matches[0];identity=tuple(map(int,found[:4]))
        if identity!=(owner['owner']['index'],owner['owner']['generation'],owner['object']['lifetime'],owner['object']['handle']) or tuple(map(int,found[4:6]))!=(2042,2042):
            raise CaptureError('length gate requires exact current lifetime and actual negotiated2042')
    return 2042


def execute(run,row,*,value_command=None,services=None,local_value_command=None):
    row['ssap_value_required']=True;row['ssap_read_uuid_required']=True;row['ssap_update_local_rejection_required']=True;row['ssap_values']=[]
    owners=row['owners'];local=[]
    lengths=bool(getattr(run.args,'ssap_value_lengths_verify',False))
    if lengths:
        if any(v is not None for v in (value_command,services,local_value_command)):raise CaptureError('dedicated real CLI length gate,not an unqualified SDK fixture')
        row['ssap_value_lengths_required']=True;row['ssap_value_lengths_version']=3;row['ssap_length_mtu']=length_mtu(row);row['ssap_length_rejections']=[]
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
    def manager_services(value_bytes=32,record=None):
        record=row if record is None else record
        local=[]
        try:
            for owner in owners:
                value=secrets.token_bytes(value_bytes)
                service=secrets.token_bytes(16);property_uuid=secrets.token_bytes(16)
                registered=command(owner,['ssap-register',service.hex(),property_uuid.hex(),'5','0',value.hex()])
                matches=re.findall(r'^SsapLocalService: start=(\d+) end=(\d+) properties=(\d+)$',registered['stdout'],re.M)
                if len(matches)!=1:raise CaptureError('one actual local database registration required')
                start,end,handle=map(int,matches[0]);local.append(dict(owner=owner,start=start,handle=handle,value=value,registration=registered,service_uuid=service.hex(),property_uuid=property_uuid.hex()))
            yield local
        finally:
            record['ssap_local_registrations']=[dict(owner=p['owner'],start=p['start'],handle=p['handle'],value=p['value'].hex(),registration=p['registration'],service_uuid=p['service_uuid'],property_uuid=p['property_uuid']) for p in local]
            for p in local:command(p['owner'],['ssap-remove',str(p['start'])])
            run.save()
    if lengths:execute_read_limits(run,row,command,manager_services)
    with services(run,row,command) if services is not None else manager_services() as local:
        from ws73_ssap_discovery import execute as discover
        discover(run,row,command,local)
        row['unsupported_incoming']=[]
        for sender,target in [(0,1),(1,0)]:
            source=owners[sender];prop=local[target]
            args=[str(run.args.slctl),'--adapter',source['owner']['path'],'ssap-receive',source['object']['path'],str(prop['discovered_handle']),'notify','10']
            receipt=run.command(args,10,collection='ssap_values');row['unsupported_incoming'].append(dict(sender=sender,target=target,handle=prop['discovered_handle'],receipt=receipt));run.save()
            if receipt['exit']==0 or 'peer has not advertised requested property update capabilities' not in receipt['stderr']:raise CaptureError('non-notifying actual peer must explicitly reject local receive interest')
        if lengths:
            for sender,target in [(0,1),(1,0)]:
                source=owners[sender];prop=local[target]
                for size in (2038,2042,2043):
                    value=secrets.token_bytes(size)
                    words=[str(run.args.slctl),'--adapter',source['owner']['path'],'ssap-write',source['object']['path'],str(prop['handle']),value.hex()]
                    item=dict(sender=sender,target=target,handle=prop['handle'],value=value.hex(),before=prop['value'].hex(),start_wall_ns=time.time_ns())
                    item['rejected']=run.command(words,10,collection='ssap_length_rejections')
                    row['ssap_length_rejections'].append(item);run.save()
                    if not item['rejected']['exit'] or 'value codec: Mtu' not in item['rejected']['stderr']:raise CaptureError('actual complete-PDU oversize refusal required')
                    item['unchanged']=command(source,['ssap-read',source['object']['path'],str(prop['handle'])],prop['value'])
                    item['end_wall_ns']=time.time_ns();run.save()
        for sequence,size in enumerate(LENGTHS if lengths else (32,)*4):
            for sender,target in [(0,1),(1,0)]:
                source=owners[sender];destination=owners[target];prop=local[target]
                payload=(sequence.to_bytes(4,'little')+secrets.token_bytes(size-4)) if size>=4 else secrets.token_bytes(size)
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
    lengths=row.get('ssap_value_lengths_required',False)
    if type(lengths)is not bool:raise CaptureError('explicit recorded length mode required')
    sizes=LENGTHS if lengths else (32,)*4
    if lengths and (length_mtu(row)!=row.get('ssap_length_mtu') or not row.get('ssap_read_uuid_required')):raise CaptureError('actual negotiated MTU/UUID length gate required')
    if len(operations)!=2*len(sizes):raise CaptureError('complete repeated SSAP length/direction matrix required')
    seen=set();nonces=set();proof=[];credit={0:0,1:0};previous_values={}
    def sends(packet):return len(packet.get('fragments',[packet]))
    for item in operations:
        sender,target=item['sender'],item['target'];key=(sender,item['sequence'])
        if sender not in (0,1) or target!=1-sender or key in seen or item['sequence'] not in range(len(sizes)):raise CaptureError('independent repeated SSAP directions required')
        seen.add(key);value=bytes.fromhex(item['value']);before=bytes.fromhex(item['before']);handle=item['handle'];source=owners[sender];destination=owners[target]
        if len(value)>=16:
            if value[4:] in nonces:raise CaptureError('SSAP random nonce reused')
            nonces.add(value[4:])
        size=sizes[item['sequence']]
        previous=32 if item['sequence']==0 else sizes[item['sequence']-1]
        if len(value)!=size or len(before)!=previous or size>=4 and int.from_bytes(value[:4],'little')!=item['sequence']:raise CaptureError('SSAP exact length/random payload/sequence required')
        if target in previous_values and before!=previous_values[target]:raise CaptureError('original written value must persist into the next read')
        previous_values[target]=value
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
            credit[0 if a==owners[0] else 1]+=sends(wire[-1]['tx'])
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
                credit[sender]+=sends(uuid_wire[-1]['request']['tx']);credit[target]+=sends(uuid_wire[-1]['response']['tx'])
        proof.append(dict(sequence=item['sequence'],sender=sender,target=target,handle=handle,value=item['value'],wire=wire,uuid_wire=uuid_wire,receipts={k:item[k] for k in ['read_before','write','local_check','read_after']}))
    if lengths:
        refusals=row.get('ssap_length_rejections',[]);rejected=[]
        if len(refusals)!=6 or [(r['sender'],len(bytes.fromhex(r['value']))) for r in refusals]!=[(s,n)for s in (0,1)for n in (2038,2042,2043)]:raise CaptureError('both actual complete-PDU oversize matrices required')
        for item in refusals:
            s,t=item['sender'],item['target'];h=item['handle'];c=item['rejected'];unchanged=item['unchanged'];before=bytes.fromhex(item['before'])
            initial=next(op['before'] for op in operations if op['sender']==s and op['sequence']==0)
            if item['before']!=initial:raise CaptureError('refusal must preserve the original value seen by the next actual operation')
            if t!=1-s or h!=row['ssap_local_registrations'][t]['handle'] or len(before)!=32 or not c['exit'] or 'value codec: Mtu' not in c['stderr'] or c['args'][-4:]!=['ssap-write',owners[s]['object']['path'],str(h),item['value']]:raise CaptureError('original exact oversize command/refusal required')
            if unchanged['exit'] or unchanged['stdout'].splitlines().count(f"SsapPeerValue: operation=ssap-read path={owners[s]['object']['path']} handle={h} value={item['before']}")!=1:raise CaptureError('peer must actually retain entire original value after refusal')
            if not item['start_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=unchanged['start_wall_ns']<=unchanged['end_wall_ns']<=item['end_wall_ns']<=operations[0]['start_wall_ns']:raise CaptureError('original refusal/read/recovery ordering required')
            legs=[]
            for a,b,pdu in [(s,t,b'\x08\x03'+h.to_bytes(2,'little')+b'\0'),(t,s,b'\x09\x03'+before)]:
                frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                legs.append(dict(tx=matched(owners[a],'out',frame,unchanged),rx=matched(owners[b],'in',frame,unchanged)));credit[a]+=sends(legs[-1]['tx'])
            rejected.append(dict(sender=s,application_bytes=len(bytes.fromhex(item['value'])),wire=legs))
        proof[0]['length_gate']=dict(mtu=2042,lengths=list(LENGTHS),refusals=rejected,scope='Complete-PDU CLI ordinary control-role;not SSAP protocol fragmentation or C/Python length qualification')
        version=row.get('ssap_value_lengths_version',1)
        if type(version)is not int or version not in (1,2,3):raise CaptureError('known explicit length contract version required')
        if version>=2:
            read_limits,read_credit=corroborate_read_limits(row,matched,version=version)
            for sender in credit:credit[sender]+=read_credit[sender]
            proof[0]['length_gate'].update(version=version,read_limits=read_limits)
        elif row.get('ssap_read_limits'):raise CaptureError('read limits cannot claim legacy length qualification')
    elif row.get('ssap_length_rejections') or 'ssap_length_mtu' in row:raise CaptureError('unexpected unrequested SSAP length evidence')
    if row.get('ssap_update_local_rejection_required'):
        rows=row.get('unsupported_incoming',[])
        if len(rows)!=2 or {x['sender'] for x in rows}!={0,1}:raise CaptureError('both actual peer local receive rejections required')
        for item in rows:
            sender,target=item['sender'],item['target'];r=item['receipt'];source=owners[sender]
            expected=['ssap-receive',source['object']['path'],str(item['handle']),'notify','10']
            if target!=1-sender or r['exit']==0 or r['args'][-5:]!=expected or 'peer has not advertised requested property update capabilities' not in r['stderr']:raise CaptureError('actual unsupported local receive receipt required')
    return proof,credit


def valid_length_summary(result,*,expected_version=None):
    try:return _valid_length_summary(result,expected_version)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError):return False


def _valid_length_summary(result,expected_version):
    if not isinstance(result,dict) or result.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED':return False
    rows=result.get('proofs',[])
    if len(rows)!=2:return False
    for phase,row in enumerate(rows):
        if type(row.get('phase'))is not int or row['phase']!=phase:return False
        values=row.get('ssap_values',[])
        if len(values)!=2*len(LENGTHS):return False
        if any(type(v.get(k))is not int for v in values for k in ('sender','sequence')) or {(v.get('sender'),v.get('sequence')) for v in values}!={(s,n)for s in (0,1)for n in range(len(LENGTHS))}:return False
        gate=values[0].get('length_gate',{})
        if gate.get('mtu')!=2042 or gate.get('lengths')!=list(LENGTHS) or len(gate.get('refusals',[]))!=6:return False
        version=gate.get('version',1)
        if type(version)is not int or version not in (1,2,3) or expected_version is not None and version!=expected_version:return False
        if version>=2 and (len(gate.get('read_limits',[]))!=10 or [(v.get('application_bytes'),v.get('sender')) for v in gate['read_limits']]!=[(n,s)for n in (2038,2039,2040,2041,2042)for s in (0,1)] or any(len(v.get('wire',[]))!=(6 if version>=3 and v['application_bytes']<=2040 else 4) for v in gate['read_limits'])):return False
        if version>=2 and any(type(v.get('read_success'))is not bool or v['read_success']!=(v['application_bytes']<=2040) or type(v.get('uuid_success'))is not bool or v['uuid_success']!=(v['application_bytes']<=2038) for v in gate['read_limits']):return False
        if version==1 and gate.get('read_limits'):return False
        if version>=3 and any((v.get('sdk',{}).get('api')!=('c'if v['sender']==phase else'python') if v['read_success']else v.get('sdk')is not None)for v in gate['read_limits']):return False
        if [(v.get('sender'),v.get('application_bytes'))for v in gate['refusals']]!=[(s,n)for s in (0,1)for n in (2038,2042,2043)] or any(len(v.get('wire',[]))!=2 for v in gate['refusals']):return False
        if any(len(bytes.fromhex(v['value']))!=LENGTHS[v['sequence']] or len(v.get('wire',[]))!=6 or len(v.get('uuid_wire',[]))!=2 for v in values):return False
    return True
