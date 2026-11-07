"""Actual ordinary-user SSAP operations. Local configuration is not RF proof."""
import re,secrets,time
from contextlib import contextmanager
from ws73_channel_socket import CaptureError
from ws73_capture import packet_interval


LENGTHS = (32,32,32,32,0,1,248,249,250,251,252,253,254,255,1024,2037)
FRAGMENT_LENGTHS = LENGTHS + (2038,2039,2040,2041,2042)



# Capability denial and deadline exhaustion are different gates. V1 retained its
# original 10ms request; v2 uses the CLI default budget, never a renewed deadline.
UPDATE_REJECTION_VERSION = 2
UPDATE_REJECTION_WAIT_MS = 5000
UPDATE_REJECTION_REASON = 'peer has not advertised requested property update capabilities'
UPDATE_REJECTION_ERROR = 'error: broker: org.freedesktop.DBus.Error.NotSupported: ' + UPDATE_REJECTION_REASON


def validate_update_rejections(row, *, expected_version=None):
    version = row.get('ssap_update_local_rejection_version', 1)
    if (type(version) is not int or version not in (1, 2)
            or expected_version is not None and version != expected_version):
        raise CaptureError('unsupported local receive evidence version')
    wait = 10 if version == 1 else UPDATE_REJECTION_WAIT_MS
    if version == 2 and (type(row.get('ssap_update_local_rejection_wait_ms')) is not int
                        or row['ssap_update_local_rejection_wait_ms'] != wait):
        raise CaptureError('original capability refusal budget required')
    if version == 1 and 'ssap_update_local_rejection_wait_ms' in row:
        raise CaptureError('legacy evidence cannot inherit a new request budget')
    rows = row.get('unsupported_incoming', [])
    if (row.get('ssap_update_local_rejection_required') is not True or len(rows) != 2
            or any(type(x.get('sender')) is not int or type(x.get('target')) is not int for x in rows)
            or {x['sender'] for x in rows} != {0, 1}):
        raise CaptureError('both actual peer local receive rejections required')
    for item in rows:
        sender, target = item['sender'], item['target']
        receipt = item['receipt']; source = row['owners'][sender]
        expected = ['ssap-receive', source['object']['path'], str(item['handle']), 'notify', str(wait)]
        if (target != 1 - sender or receipt['exit'] == 0 or receipt['args'][-5:] != expected
                or UPDATE_REJECTION_REASON not in receipt['stderr']):
            raise CaptureError('actual unsupported local receive receipt required')
        if version == 2 and (receipt['stderr'].strip() != UPDATE_REJECTION_ERROR
                or receipt['args'][1:] != ['--adapter', source['owner']['path'], *expected]):
            raise CaptureError('exact current owner and typed NotSupported required, not timeout')
    return dict(version=version, wait_ms=wait, receipts=rows)


def execute_update_rejections(run, row, local):
    row.update(ssap_update_local_rejection_required=True,
               ssap_update_local_rejection_version=UPDATE_REJECTION_VERSION,
               ssap_update_local_rejection_wait_ms=UPDATE_REJECTION_WAIT_MS,
               unsupported_incoming=[])
    for sender, target in ((0, 1), (1, 0)):
        source = row['owners'][sender]; prop = local[target]
        args = [str(run.args.slctl), '--adapter', source['owner']['path'], 'ssap-receive',
                source['object']['path'], str(prop['discovered_handle']), 'notify',
                str(UPDATE_REJECTION_WAIT_MS)]
        receipt = run.command(args, 10, collection='ssap_values')
        row['unsupported_incoming'].append(dict(sender=sender, target=target,
                                               handle=prop['discovered_handle'], receipt=receipt))
        run.save()  # Preserve the first failure before leaving; no retry.
        if receipt['exit'] == 0 or receipt['stderr'].strip() != UPDATE_REJECTION_ERROR:
            raise CaptureError('non-notifying actual peer must explicitly reject local receive interest')
    validate_update_rejections(row, expected_version=UPDATE_REJECTION_VERSION)


def physical_packets(packet):
    """Retained complete SMTC packets under one logical SSAP value."""
    packets=packet['ssap_fragments'] if 'ssap_fragments' in packet else [packet]
    if type(packets)is not list or not packets:raise CaptureError('nonempty physical SSAP capture required')
    return packets


def wire_interval(packet):
    spans=[packet_interval(p) for p in physical_packets(packet)]
    return min(p[0] for p in spans),max(p[1] for p in spans)


def stream_causal(tx,rx):
    """Check byte-prefix causality across different ACB fragment boundaries.

    Endpoints, original window, PB and record order are checked by
    command_packet/validate_paired_leg before this predicate. RX may overlap TX
    but no received prefix may extend past bytes already captured on TX.
    """
    try:
        sent,received=tx['fragments'],rx['fragments']
        if not sent or not received or tx['data']!=rx['data']:return False
        data=bytes.fromhex(tx['data'])
        if not data:return False
        for parts in (sent,received):
            if any(not bytes.fromhex(p['data'])for p in parts):return False
            if b''.join(bytes.fromhex(p['data'])for p in parts)!=data:return False
            stamps=[packet_interval(p)[0]for p in parts]
            if stamps!=sorted(stamps):return False
        cursor=0;available=0;consumed=0
        for packet in received:
            consumed+=len(bytes.fromhex(packet['data']))
            when=packet_interval(packet)[0]
            while available<consumed:
                if cursor==len(sent) or packet_interval(sent[cursor])[1]>when:return False
                available+=len(bytes.fromhex(sent[cursor]['data']));cursor+=1
        return consumed==available==len(data) and cursor==len(sent)
    except (KeyError,TypeError,ValueError):return False


def physical_sends(packet):
    if 'ssap_fragments' in packet:return sum(physical_sends(p) for p in packet['ssap_fragments'])
    return len(packet.get('fragments',[packet]))


def write_command_contract(row):
    """Explicit evidence contract; old length/update flags never enable commands."""
    if 'ssap_write_command_contract'not in row:return False
    value=row['ssap_write_command_contract']
    if type(value)is not int or value!=1:raise CaptureError('explicit SSAP write command contract1 required')
    return True


def command_pdu(pdu):
    """Finite independent single-property command and confirmation-read shapes."""
    if not isinstance(pdu,bytes)or len(pdu)<2 or pdu[1]!=3:raise CaptureError('complete single-value command/read PDU required')
    if pdu[0]==9:
        if len(pdu)>2044:raise CaptureError('bounded complete confirmation Read value required')
    elif pdu[0]in (8,12):
        if not 5<=len(pdu)<=2047 or pdu[4]!=0 or pdu[2:4]==b'\0\0' or (pdu[0]==8 and len(pdu)!=5):
            raise CaptureError('bounded single-property handle and type0 required')
    else:raise CaptureError('only command12 and confirmation Read8/9 are covered')


def fragment_parts(pdu,*,ssap_write_command_contract=None,ssap_method_result_contract=None):
    command=write_command_contract(dict(ssap_write_command_contract=ssap_write_command_contract))if ssap_write_command_contract is not None else False
    if command:command_pdu(pdu)
    method=ssap_method_result_contract is not None
    if method and (type(ssap_method_result_contract)is not int or ssap_method_result_contract!=1
                   or command or pdu[:2]!=b'\x14\x03'):
        raise CaptureError('explicit independent method result fragmentation contract required')
    supported=(20,)if method else(9,12)if command else(9,11,13,14,15,16)
    if not 2042<len(pdu)<=(2048 if pdu[0] in (15,16) else 2047) or pdu[0]not in supported or pdu[1]&3!=3:raise CaptureError('bounded fragmented logical value/update required')
    begin=(pdu[1]&~3)|(8 if pdu[0]in (12,13) else 0);end=(pdu[1]&~3)|2
    return [bytes([pdu[0]|128,begin,2,0])+pdu[2:2040],bytes([pdu[0]|128,end,2,0])+pdu[2040:]]


def command_packet(packet,frame,window):
    """Validate retained reassembler output, including every physical fragment."""
    start,end=window['start_wall_ns'],window['end_wall_ns']
    if type(start)is not int or type(end)is not int or not 0<start<=end:raise CaptureError('original command observation window required')
    pieces=packet['fragments']
    if not isinstance(pieces,list)or not pieces:raise CaptureError('actual nonempty ACB fragment list required')
    if packet['data']!=frame.hex()or b''.join(bytes.fromhex(p['data'])for p in pieces)!=frame:
        raise CaptureError('actual ordered ACB bytes must equal expected command/read frame')
    boundaries=[p.get('boundary',0)for p in pieces]
    if boundaries!=([0]if len(pieces)==1 else[1]+[2]*(len(pieces)-2)+[3]):
        raise CaptureError('original full or first/middle/last ACB boundaries required')
    order=[(p['record'],p.get('hcc_offset',0))for p in pieces]
    if any(type(v)is not int or v<0 for pair in order for v in pair)or any(a>=b for a,b in zip(order,order[1:])):
        raise CaptureError('strict physical ACB record order required')
    if any(not bytes.fromhex(p['data'])for p in pieces):raise CaptureError('empty physical ACB fragment cannot count as a send')
    first,last=packet_interval(packet)
    if not start<=first<=last<=end:raise CaptureError('all original ACB fragments must lie inside the observation window')


def valid_wire(leg):
    try:
        command=write_command_contract(leg)
        pdu=bytes.fromhex(leg['logical_pdu'])if 'logical_pdu'in leg else None
        if command:
            expected=bytes.fromhex(leg['expected_pdu']);command_pdu(expected)
            if (len(expected)>2042 and pdu!=expected)or (len(expected)<=2042 and pdu is not None):return False
        method=leg.get('ssap_method_result_contract')
        if method is not None and (type(method)is not int or method!=1 or command or pdu is None):return False
        parts=fragment_parts(pdu,ssap_write_command_contract=1 if command else None,
                             ssap_method_result_contract=method)if pdu is not None else None
        for side in ['tx','rx']:
            packets=leg[side]['ssap_fragments']if parts is not None else[leg[side]]
            if parts is not None and len(packets)!=2:return False
            for n,packet in enumerate(packets):
                frame=bytes.fromhex(packet['data'])
                if not frame.startswith(b'\x0a\0')or len(frame)>2046 or int.from_bytes(frame[2:4],'little')!=len(frame)-4:return False
                if parts is not None and frame[4:]!=parts[n]:return False
                if b''.join(bytes.fromhex(p['data'])for p in packet.get('fragments',[packet]))!=frame:return False
                if command:
                    if parts is None and frame[4:]!=expected:return False
                    command_packet(packet,frame,leg['capture_window'])
                elif frame[4:5]in (b'\x0c',b'\x8c'):return False
            if parts is not None:
                end=packets[0].get('fragments',[packets[0]])[-1];start=packets[1].get('fragments',[packets[1]])[0]
                if not(end['record'],end.get('hcc_offset',0))<(start['record'],start.get('hcc_offset',0)):return False
        if parts is None and leg['tx']['data']!=leg['rx']['data']:return False
        return True
    except (KeyError,ValueError,TypeError,IndexError):return False


def pair_wire(row,matched,source,destination,pdu,window):
    # Independent fixed two-fragment byte expectations for the2042-wire/2047-
    # logical qualification. This is evidence reconstruction, not a Host/Engine.
    enabled=write_command_contract(row)
    if pdu[:1]==b'\x8c':raise CaptureError('expected complete logical command, not a raw extended fragment')
    if pdu[:1]==b'\x0c'and not enabled:raise CaptureError('Write Command needs its own explicit evidence contract')
    command=enabled and pdu[:1]in (b'\x08',b'\x09',b'\x0c')
    extra={}
    if command:
        command_pdu(pdu)
        extra=dict(ssap_write_command_contract=1,expected_pdu=pdu.hex(),
                   capture_window={k:window[k]for k in ('start_wall_ns','end_wall_ns')})
    if len(pdu)<=2042:
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        result=dict(tx=matched(source,'out',frame,window),rx=matched(destination,'in',frame,window),**extra)
        if command and not valid_wire(result):raise CaptureError('complete paired command/read capture evidence required')
        return result
    versioned_value=row.get('ssap_value_lengths_version',1)==4 and pdu[0] in (9,11,13,14)
    versioned_provider=type(row.get('ssap_sdk_write_provider_version')) is int and row['ssap_sdk_write_provider_version']==2 and pdu[0] in (13,14)
    versioned_update=row.get('ssap_update_delivery_version',1)==2 and pdu[0] in (9,11,13,14,15,16)
    versioned_method=type(row.get('ssap_method_provider_version')) is int and row['ssap_method_provider_version']==4 and pdu[:2]==b'\x14\x03'
    limit=2048 if pdu[0] in (15,16) else 2047
    if not(versioned_value or versioned_update or versioned_provider or versioned_method or command) or not 2042<len(pdu)<=limit or pdu[1]&3!=3:raise CaptureError('bounded actual negotiated sequence fragment contract required')
    if versioned_method:extra['ssap_method_result_contract']=1
    parts=fragment_parts(pdu,ssap_write_command_contract=1 if command else None,ssap_method_result_contract=1 if versioned_method else None)
    result=dict(tx=dict(ssap_fragments=[]),rx=dict(ssap_fragments=[]),logical_pdu=pdu.hex(),**extra)
    for part in parts:
        frame=b'\x0a\0'+len(part).to_bytes(2,'little')+part
        for key,owner,direction in [('tx',source,'out'),('rx',destination,'in')]:result[key]['ssap_fragments'].append(matched(owner,direction,frame,window))
    for key in ['tx','rx']:
        a,b=result[key]['ssap_fragments']
        end=a.get('fragments',[a])[-1];start=b.get('fragments',[b])[0]
        if not(end['record'],end.get('hcc_offset',0))<(start['record'],start.get('hcc_offset',0)):raise CaptureError('first/last SSAP fragment record order required')
    if command and not valid_wire(result):raise CaptureError('complete paired fragmented command/read evidence required')
    return result


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
                if size<=2042:
                    from ws73_application_client import ssap_command
                    item['sdk_read']=ssap_command(run,row,source,['ssap-read',source['object']['path'],str(item['handle'])],prop['value'],expected_size=size)
                item['local_check']=command(target,['ssap-local-read',str(prop['handle'])],prop['value'])
                item['end_wall_ns']=time.time_ns();run.save()
                for name,limit,error in [('read',2040,'peer read error 16'),('uuid_read',2038,'peer requires unsupported SSAP fragmentation')]:
                    result=item[name]
                    if result['exit']:raise CaptureError('actual negotiated full-value read/UUID delivery required')
        group['end_wall_ns']=time.time_ns();run.save()


def corroborate_read_limits(row,matched,*,version=2):
    from ws73_ssap_discovery import corroborate as discovery
    groups=row.get('ssap_read_limits',[]);credit={0:0,1:0};proof=[];fresh=set();sdk_seen=[]
    if version>=3 and len(row.get('ssap_language_clients',[]))!=(10 if version>=4 else 6):raise CaptureError('all original bounded SDK read processes required')
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
                c=item[name];success=version>=4 or size<=limit
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
                    packet=pair_wire(row,matched,row['owners'][a],row['owners'][b],pdu,c);wire.append(packet);credit[a]+=physical_sends(packet['tx'])
            sdk=None
            if version>=3 and (version>=4 or size<=2040):
                from ws73_application_client import ssap_receipt
                app=item['sdk_read'];ssap_receipt(app,source,expected_size=size)
                if app not in row['ssap_language_clients']or app in sdk_seen:raise CaptureError('SDK read must belong to one actual registered child')
                sdk_seen.append(app)
                expected_api='c'if sender==row['phase']else'python'
                if app['api']!=expected_api or app['ssap_expected']!=item['value'] or not item['start_wall_ns']<=app['start_wall_ns']<=app['end_wall_ns']<=local['start_wall_ns']:raise CaptureError('actual swapped-role SDK complete read required')
                for a,b,pdu in [(sender,target,b'\x08\x03'+h.to_bytes(2,'little')+b'\0'),(target,sender,b'\x09\x03'+value)]:
                    frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu;packet=pair_wire(row,matched,row['owners'][a],row['owners'][b],pdu,app);wire.append(packet);credit[a]+=physical_sends(packet['tx'])
                sdk=dict(api=app['api'],application=app)
            elif item.get('sdk_read'):raise CaptureError('unrequested SDK read cannot upgrade old contract')
            proof.append(dict(sender=sender,application_bytes=size,read_success=version>=4 or size<=2040,uuid_success=version>=4 or size<=2038,wire=wire,discovery=discovered if sender==0 else None,**(dict(sdk=sdk)if version>=3 else{})))
    if version>=3 and len(sdk_seen)!=(10 if version>=4 else 6):raise CaptureError('every actual SDK child must be accounted')
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


def length_mtu(row,*,require_sequence=False):
    receipts=row.get('ssap_receipts',[])
    if len(receipts)!=2:raise CaptureError('both actual SSAP negotiation receipts required')
    pattern=r'^SsapExchangeInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local_mtu=(\d+) negotiated_mtu=(\d+) request=([0-9a-f]+) peer_reply=([0-9a-f]+) peer_request=([0-9a-f]+) response=([0-9a-f]+)$'
    for owner,receipt in zip(row['owners'],receipts,strict=True):
        matches=re.findall(pattern,receipt['stdout'],re.M)
        if receipt['exit'] or len(matches)!=1:raise CaptureError('one actual negotiation result required')
        found=matches[0];identity=tuple(map(int,found[:4]))
        if identity!=(owner['owner']['index'],owner['owner']['generation'],owner['object']['lifetime'],owner['object']['handle']) or tuple(map(int,found[4:6]))!=(2042,2042):
            raise CaptureError('length gate requires exact current lifetime and actual negotiated2042')
        if require_sequence and (type(row.get('ssap_exchange_contract'))is not int or row['ssap_exchange_contract']!=2
                or tuple(found[6:])!=('0207fa07010204000000','0307fa07010204000000','0207fa07010204000000','0307fa07010204000000')):
            raise CaptureError('actual current two-way sequence negotiation required')
    return 2042


def uuid_result(receipt,source,handle,uuid,expected):
    """CLI exit zero is not a successful remote UUID read."""
    request=b'\x0a\x01\x10\x00\xff\xff\x00'+uuid
    response=b'\x0b\x03'+handle.to_bytes(2,'little')+expected
    line=f"SsapUuidValue: path={source['object']['path']} handle={handle} success=true error=0 value={expected.hex()}"
    trace=f"SsapUuidTrace: request={request.hex()} response={response.hex()}"
    if (receipt['exit']or receipt['stdout'].splitlines().count(line)!=1
        or receipt['stdout'].splitlines().count(trace)!=1):raise CaptureError('original peer UUID value and raw trace required')
    return request,response


def execute(run,row,*,value_command=None,services=None,local_value_command=None,value_commands=None):
    row['ssap_value_required']=True;row['ssap_read_uuid_required']=True;row['ssap_update_local_rejection_required']=True;row['ssap_values']=[]
    owners=row['owners'];local=[]
    lengths=bool(getattr(run.args,'ssap_value_lengths_verify',False))
    if value_commands is not None:
        if (not callable(value_commands)or value_command is None or services is None or local_value_command is None
            or lengths or row.get('ssap_sdk_duplex_required')is not True):raise CaptureError('explicit actual SDK duplex callbacks required')
    elif row.get('ssap_sdk_duplex_required'):raise CaptureError('duplex cannot fall back to sequential callers')
    if lengths:
        if any(v is not None for v in (value_command,services,local_value_command)):raise CaptureError('dedicated real CLI length gate,not an unqualified SDK fixture')
        row['ssap_value_lengths_required']=True;row['ssap_value_lengths_version']=4;row['ssap_length_mtu']=length_mtu(row);row['ssap_length_rejections']=[]
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
        execute_update_rejections(run,row,local)
        if lengths:
            for sender,target in [(0,1),(1,0)]:
                source=owners[sender];prop=local[target]
                for size in (2043,2048,2050):
                    value=secrets.token_bytes(size)
                    words=[str(run.args.slctl),'--adapter',source['owner']['path'],'ssap-write',source['object']['path'],str(prop['handle']),value.hex()]
                    item=dict(sender=sender,target=target,handle=prop['handle'],value=value.hex(),before=prop['value'].hex(),start_wall_ns=time.time_ns())
                    item['rejected']=run.command(words,10,collection='ssap_length_rejections')
                    row['ssap_length_rejections'].append(item);run.save()
                    if not item['rejected']['exit'] or 'value codec: Mtu' not in item['rejected']['stderr']:raise CaptureError('actual complete-PDU oversize refusal required')
                    item['unchanged']=command(source,['ssap-read',source['object']['path'],str(prop['handle'])],prop['value'])
                    item['end_wall_ns']=time.time_ns();run.save()
        for sequence,size in enumerate(FRAGMENT_LENGTHS if lengths else (32,)*4):
            for senders in ((0,1),)if value_commands is not None else((0,),(1,)):
                work=[]
                for sender in senders:
                    target=1-sender;source=owners[sender];destination=owners[target];prop=local[target]
                    payload=(sequence.to_bytes(4,'little')+secrets.token_bytes(size-4))if size>=4 else secrets.token_bytes(size)
                    item=dict(sequence=sequence,sender=sender,target=target,handle=prop['discovered_handle'],before=prop['value'].hex(),value=payload.hex(),start_wall_ns=time.time_ns(),property_uuid=prop['property_uuid'])
                    item['uuid_read_before']=command(source,['ssap-read-uuid',source['object']['path'],'16','65535',prop['property_uuid']])
                    uuid_result(item['uuid_read_before'],source,prop['handle'],bytes.fromhex(prop['property_uuid']),prop['value'])
                    work.append((source,destination,prop,payload,item))
                def values(step,writing=False):
                    calls=[]
                    for source,destination,prop,payload,item in work:
                        expected=prop['value']if step=='read_before'else payload
                        words=['ssap-write'if writing else'ssap-read',source['object']['path'],str(prop['handle'])]
                        if writing:words.append(payload.hex())
                        calls.append((source,words,expected))
                    receipts=(value_commands(calls,sequence,step)if value_commands is not None
                              else[command(owner,words,expected)for owner,words,expected in calls])
                    if len(receipts)!=len(work)or any(r['exit']for r in receipts):raise CaptureError('every actual SDK value result required')
                    for transaction,receipt in zip(work,receipts,strict=True):transaction[-1][step]=receipt
                values('read_before');values('write',True)
                for source,destination,prop,payload,item in work:item['local_check']=command(destination,['ssap-local-read',str(prop['handle'])],payload)
                values('read_after')
                for source,destination,prop,payload,item in work:
                    item['uuid_read_after']=command(source,['ssap-read-uuid',source['object']['path'],'16','65535',prop['property_uuid']])
                    uuid_result(item['uuid_read_after'],source,prop['handle'],bytes.fromhex(prop['property_uuid']),payload)
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
    version=row.get('ssap_value_lengths_version',1)
    matrix=FRAGMENT_LENGTHS if version>=4 else LENGTHS
    sizes=matrix if lengths else (32,)*4
    if lengths and (length_mtu(row)!=row.get('ssap_length_mtu') or not row.get('ssap_read_uuid_required')):raise CaptureError('actual negotiated MTU/UUID length gate required')
    if len(operations)!=2*len(sizes):raise CaptureError('complete repeated SSAP length/direction matrix required')
    seen=set();nonces=set();proof=[];credit={0:0,1:0};previous_values={}
    sends=physical_sends
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
            wire.append(pair_wire(row,matched,a,b,payload,window))
            credit[0 if a==owners[0] else 1]+=sends(wire[-1]['tx'])
        uuid_wire=[]
        if row.get('ssap_read_uuid_required'):
            uuid=bytes.fromhex(item['property_uuid'])
            if len(uuid)!=16 or registered['property_uuid']!=item['property_uuid']:raise CaptureError('original target UUID required')
            request=b'\x0a\x01\x10\x00\xff\xff\x00'+uuid
            for name,expected in [('uuid_read_before',before),('uuid_read_after',value)]:
                c=item[name];actual_request,response=uuid_result(c,source,handle,uuid,expected)
                if actual_request!=request:raise CaptureError('original target UUID request required')
                if not item['start_wall_ns']<=c['start_wall_ns']<=c['end_wall_ns']<=item['end_wall_ns']:raise CaptureError('UUID request original interval required')
                uuid_wire.append(dict(request=pair_wire(row,matched,source,destination,request,c),response=pair_wire(row,matched,destination,source,response,c)))
                credit[sender]+=sends(uuid_wire[-1]['request']['tx']);credit[target]+=sends(uuid_wire[-1]['response']['tx'])
        proof.append(dict(sequence=item['sequence'],sender=sender,target=target,handle=handle,value=item['value'],wire=wire,uuid_wire=uuid_wire,receipts={k:item[k] for k in ['read_before','write','local_check','read_after']}))
    if lengths:
        refusals=row.get('ssap_length_rejections',[]);rejected=[]
        if len(refusals)!=6 or [(r['sender'],len(bytes.fromhex(r['value']))) for r in refusals]!=[(s,n)for s in (0,1)for n in ((2043,2048,2050)if version>=4 else(2038,2042,2043))]:raise CaptureError('both actual bounded oversize matrices required')
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
        proof[0]['length_gate']=dict(mtu=2042,lengths=list(matrix),refusals=rejected,scope=('Bounded negotiated sequence read/write/UUID and public maximum reads;not full SSAP fragmentation/multitransaction/update qualification'if version>=4 else'Complete-PDU CLI ordinary control-role;not SSAP protocol fragmentation or C/Python length qualification'))
        version=row.get('ssap_value_lengths_version',1)
        if type(version)is not int or version not in (1,2,3,4):raise CaptureError('known explicit length contract version required')
        if version>=2:
            read_limits,read_credit=corroborate_read_limits(row,matched,version=version)
            for sender in credit:credit[sender]+=read_credit[sender]
            proof[0]['length_gate'].update(version=version,read_limits=read_limits)
        elif row.get('ssap_read_limits'):raise CaptureError('read limits cannot claim legacy length qualification')
    elif row.get('ssap_length_rejections') or 'ssap_length_mtu' in row:raise CaptureError('unexpected unrequested SSAP length evidence')
    if row.get('ssap_update_local_rejection_required'):
        rejection = validate_update_rejections(row)
        if rejection['version'] == 2:
            proof[0]['local_update_rejection'] = rejection
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
        gate=values[0].get('length_gate',{})if values else{}
        version=gate.get('version',1);matrix=FRAGMENT_LENGTHS if version==4 else LENGTHS
        if len(values)!=2*len(matrix):return False
        if any(type(v.get(k))is not int for v in values for k in ('sender','sequence')) or {(v.get('sender'),v.get('sequence')) for v in values}!={(s,n)for s in (0,1)for n in range(len(matrix))}:return False
        gate=values[0].get('length_gate',{})
        if gate.get('mtu')!=2042 or gate.get('lengths')!=list(matrix) or len(gate.get('refusals',[]))!=6:return False
        version=gate.get('version',1)
        if type(version)is not int or version not in (1,2,3,4) or expected_version is not None and version!=expected_version:return False
        if version>=2 and (len(gate.get('read_limits',[]))!=10 or [(v.get('application_bytes'),v.get('sender')) for v in gate['read_limits']]!=[(n,s)for n in (2038,2039,2040,2041,2042)for s in (0,1)] or any(len(v.get('wire',[]))!=(6 if version>=3 and(version>=4 or v['application_bytes']<=2040)else 4) for v in gate['read_limits'])):return False
        if version>=2 and any(type(v.get('read_success'))is not bool or v['read_success']!=(version>=4 or v['application_bytes']<=2040) or type(v.get('uuid_success'))is not bool or v['uuid_success']!=(version>=4 or v['application_bytes']<=2038) for v in gate['read_limits']):return False
        if version>=4:
            legs=[leg for v in values for leg in v['wire']]+[leg for v in values for pair in v['uuid_wire']for leg in pair.values()]+[leg for v in gate['read_limits']for leg in v['wire']]
            if not all(valid_wire(leg)for leg in legs)or not any('logical_pdu'in leg for leg in legs):return False
            if any((len(bytes.fromhex(v['value']))+5>2042)!=('logical_pdu'in v['wire'][2])for v in values):return False
        if version==1 and gate.get('read_limits'):return False
        if version>=3 and any((v.get('sdk',{}).get('api')!=('c'if v['sender']==phase else'python') if v['read_success']else v.get('sdk')is not None)for v in gate['read_limits']):return False
        if [(v.get('sender'),v.get('application_bytes'))for v in gate['refusals']]!=[(s,n)for s in (0,1)for n in ((2043,2048,2050)if version>=4 else(2038,2042,2043))] or any(len(v.get('wire',[]))!=2 for v in gate['refusals']):return False
        if any(len(bytes.fromhex(v['value']))!=matrix[v['sequence']] or len(v.get('wire',[]))!=6 or len(v.get('uuid_wire',[]))!=2 for v in values):return False
    return True
