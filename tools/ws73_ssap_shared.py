# SPDX-License-Identifier: GPL-2.0-only
"""Finite shared-owner workload in the existing VM gate,not another Engine.

SDK read/check/writeback and all capture/codec/supervision functions are reused.
Only same-filter/mode sharing is exercised;no fake Native or peer reply exists.
"""
from contextlib import contextmanager,ExitStack
from pathlib import Path
import json,os,secrets,subprocess,time
from ws73_capture import CaptureError
from ws73_application_client import application_environment,process_identity,owned_arguments,authorization_context
from ws73_ssap_owned import publisher,value_snapshot,await_removed
from ws73_ssap_update_delivery import configuration,command_receipt,discover,discovery_wire,sdk_receipt
from ws73_ssap_subscription import checked_update_reply,wait_stage,role

TOOL='/usr/share/sparklink/tools/ws73_ssap_shared.py'

@contextmanager
def reader(run,row,peer,item,api,mode,member):
    prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    args=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(item['handle']),str(mode),'30000']
    label=f'shared-{row["phase"]}-{item["sender"]}-{mode}-{member}';out=run.output/(label+'.stdout');err=run.output/(label+'.stderr')
    begin=time.time_ns()
    app=dict(api=api,args=args,environment=application_environment(),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
    lease=dict(mode=mode,member=member,application=app,start_wall_ns=begin);item['leases'].append(lease);run.save();process=None
    try:
        with out.open('x')as stdout,err.open('x')as stderr:
            process=subprocess.Popen(args,user=1004,group=1004,extra_groups=[],env=dict(os.environ,**application_environment()),stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True)
            app['pid']=process.pid;app['credentials'],app['process_status']=process_identity(process.pid,1004);run.save()
            lease['active']=wait_stage(process,app,'ssap_subscription_active',1,time.monotonic()+6);lease.update(ready_wall_ns=time.time_ns(),ready_ns=time.monotonic_ns());run.save()
            yield process,lease
    finally:
        if process is not None:
            if process.poll()is None:process.kill();process.wait(timeout=2)
            if process.stdin:process.stdin.close()
            app.update(exit=process.returncode,end_wall_ns=time.time_ns(),stdout=out.read_text(),stderr=err.read_text())
        lease['end_wall_ns']=time.time_ns();run.save()


def release(run,process,lease,flags):
    lease.update(release_request_wall_ns=time.time_ns(),release_request_ns=time.monotonic_ns());run.save()
    process.stdin.write('release-observe\n');process.stdin.flush()
    lease['release_started']=wait_stage(process,lease['application'],'ssap_subscription_release_started',1,time.monotonic()+1)
    lease['release']=wait_stage(process,lease['application'],'ssap_subscription_released',1,lease['release_started']['deadline_ns']/1e9)
    lease.update(release_completed_ns=time.monotonic_ns(),release_completed_wall_ns=time.time_ns())
    if lease['release']!=dict(stage='ssap_subscription_released',api=lease['application']['api'],flags=flags,discarded=0):raise CaptureError('actual scoped lease release result required')
    process.stdin.write('quit\n');process.stdin.flush();process.wait(timeout=2)
    if process.returncode:raise CaptureError('actual shared reader exit')
    lease['released_wall_ns']=time.time_ns();run.save()


def execute(run,row):
    from ws73_ssap_subscription import STATUS
    row.update(ssap_subscription=[],ssap_subscription_required=True,ssap_subscription_contract_version=1);run.save()
    for sender in(0,1):
        peer,server=row['owners'][sender],row['owners'][1-sender];api='c'if(row['phase']+sender)%2==0 else'python';other='python'if api=='c'else'c'
        with publisher(run,row,sender,'allow',collection='ssap_subscription',label='shared-subscription',sdk_api=api,updates=True,application_uid=1005)as(owner,item):
            discover(run,peer,item);item.update(leases=[],groups=[]);run.save()
            for mode in(1,2):
                group=dict(mode=mode,start_wall_ns=time.time_ns(),messages=[],lease_indexes=[]);item['groups'].append(group)
                with ExitStack()as resources:
                    a,la=resources.enter_context(reader(run,row,peer,item,other,mode,'a0'));group['lease_indexes'].append(len(item['leases'])-1)
                    group['enabled']=configuration(owner,item,mode,a);run.save()
                    b,lb=resources.enter_context(reader(run,row,peer,item,api,mode,'b'));group['lease_indexes'].append(len(item['leases'])-1)
                    if la['active']['token']==lb['active']['token']or la['active']['epoch']!=lb['active']['epoch']:raise CaptureError('independent token at original epoch required')
                    counts={'a0':0,'b':0,'a1':0}
                    for number in range(7):
                        if number==3:
                            release(run,a,la,3);group['retained_observation']=configuration(owner,item,mode,b);run.save()
                        if number==5:
                            fresh,lf=resources.enter_context(reader(run,row,peer,item,other,mode,'a1'));group['lease_indexes'].append(len(item['leases'])-1)
                            if lf['active']['token']in(la['active']['token'],lb['active']['token'])or lf['active']['epoch']!=lb['active']['epoch']:raise CaptureError('fresh replacement token and unchanged epoch required')
                        peers=[('a0',a,la),('b',b,lb)]if number<3 else[('b',b,lb)]if number<5 else[('a1',fresh,lf),('b',b,lb)]
                        sequence=(row['phase']<<24)|(sender<<20)|(mode<<16)|number;value=(sequence.to_bytes(4,'little')+secrets.token_bytes(28)).hex()
                        case=dict(number=number,value=value,start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns(),recipients=[]);group['messages'].append(case)
                        case['replacement']=command_receipt(owner,item,'replace '+value,'SdkOwnedReplaced');case['before']=value_snapshot(owner,item,value,limit=48);run.save()
                        for position,(member,process,lease)in enumerate(peers):
                            reply=((sequence|0x80000000|((1 if member=='b'else 2 if member=='a1'else 0)<<12)).to_bytes(4,'little')+secrets.token_bytes(28)).hex()
                            received=dict(member=member,reply=reply,start_wall_ns=time.time_ns());case['recipients'].append(received);counts[member]+=1;run.save()
                            callback=(lambda:command_receipt(owner,item,'indicate'if mode==2 else'notify','SdkOwnedUpdate'))if position==0 else None
                            result=checked_update_reply(process,lease['application'],owner,item,value,reply,counts[member],counts[member],limit=48,before_wait=callback,record=received,save=run.save)
                            if 'send'in result:case['send']=result.pop('send')
                            received.update(result,end_wall_ns=time.time_ns());run.save()
                        case.update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns());run.save()
                    release(run,fresh,lf,3);release(run,b,lb,1)
                group['disabled']=configuration(owner,item,0);group['end_wall_ns']=time.time_ns();run.save()
            owner.stdin.write('quit\n');owner.stdin.flush();owner.wait(timeout=2)
            if owner.returncode:raise CaptureError('original shared provider cleanup failed')
            item['cleanup']=await_removed(run,server,item['start']);run.save()
    row['ssap_subscription_status']=STATUS;run.save()


def part_valid(value,phase,sender):
    from ws73_ssap_value import valid_wire
    try:
        api='c'if(phase+sender)%2==0 else'python'
        wanted=dict(sender=sender,target=1-sender,leases=6,updates=14,application_replies=24,decisions=4,shared_contract_version=1,shared_groups=2,shared_joins=4,retained_releases=4,last_disables=2)
        return(all(type(value[k])is type(v)and value[k]==v for k,v in wanted.items())
            and value['publisher']==api and value['peer']==('python'if api=='c'else'c')
            and len(value['wire'])==91 and all(valid_wire(v)for v in value['wire'])
            and all(value.get(k)is None for k in ('renewal_contract_version','pressure_contract_version','owner_loss_contract_version','inflight_release_contract_version')))
    except (KeyError,TypeError,ValueError):return False


def native_security_epochs(row):
    """Bind each side to its actual Native SCM receipt,not the peer's epoch.

    Epochs belong to the local controller/connection security mechanism. Two
    authenticated peers need not allocate equal numbers. The common verifier
    checks each receipt's full controller/generation/lifetime/handle identity.
    This finite gate requires one unchanged authenticated epoch per side.
    """
    from ws73_channel_socket import message_security_receipts
    receipts,_=message_security_receipts(row);epochs=[]
    for position in(0,1):
        role_name='peer'if position else'initiator'
        values=[v for v in receipts if v['role']==role_name]
        distinct={v['epoch']for v in values}
        if len(values)!=row['rounds']or len(distinct)!=1 or any(v['security']!=2 for v in values):
            raise CaptureError('actual stable authenticated Native context per shared endpoint required')
        epochs.append(distinct.pop())
    return epochs


def corroborate(row,matched):
    owners=row['owners'];proof=[];credit={0:0,1:0};unique=set();epochs=native_security_epochs(row)
    if len(row.get('ssap_subscription',[]))!=2:raise CaptureError('two original shared providers required')
    for sender,item in enumerate(row['ssap_subscription']):
        s,t=sender,1-sender;peer,server=owners[s],owners[t];api='c'if(row['phase']+s)%2==0 else'python';other='python'if api=='c'else'c';h=item['handle'];legs=[];snapshots=[];tokens=set();pidset=set();commands={'SdkOwnedReplaced':[],'SdkOwnedUpdate':[],'SdkOwnedConfiguration':[]}
        if(item['sender']!=s or item['target']!=t or item['publisher_api']!=api or item['policy']!='allow'
            or item['args']!=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'allow',update_connection=server['object']['path'])
            or item['environment']!=application_environment()or type(item['exit'])is not int or item['exit']!=0 or item['stderr']
            or not 16<=item['start']<h<=item['end']<=65535 or len(item['leases'])!=6 or len(item['groups'])!=2):raise CaptureError('original service-only shared provider required')
        role(item['credentials'],1005)
        lines=item['stdout'].splitlines()
        if lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only']or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={item["start"]}']:raise CaptureError('complete shared provider stream required')
        def exchange(a,b,pdu,window):
            from ws73_ssap_value import pair_wire,physical_sends
            leg=pair_wire(row,matched,owners[a],owners[b],pdu,window);legs.append(leg);credit[a]+=physical_sends(leg['tx']);return leg
        discovery_wire(item,peer,exchange)
        for mode,group in zip((1,2),item['groups'],strict=True):
            indexes=list(range((mode-1)*3,mode*3));leases=item['leases'][indexes[0]:indexes[-1]+1];by_member=dict(zip(('a0','b','a1'),leases,strict=True));expected={k:[]for k in by_member};counts={k:0 for k in by_member}
            if type(group['mode'])is not int or group['mode']!=mode or group['lease_indexes']!=indexes or len(group['messages'])!=7:raise CaptureError('complete finite shared group matrix required')
            for member,lease in by_member.items():
                app=lease['application'];reader_api=api if member=='b'else other;role(app['credentials'],1004)
                prefix=['/bin/ws73-application-client-c']if reader_api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
                if (lease['member']!=member or type(lease['mode'])is not int or lease['mode']!=mode or app['api']!=reader_api or app['environment']!=application_environment()
                    or app['args']!=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode),'30000']
                    or type(app['exit'])is not int or app['exit']!=0 or app['stderr']or type(app['pid'])is not int or app['pid']<=0 or app['pid']in pidset
                    or not group['start_wall_ns']<=lease['start_wall_ns']<=app['start_wall_ns']<=app['end_wall_ns']<=lease['end_wall_ns']<=group['end_wall_ns']<=item['end_wall_ns']):raise CaptureError('actual separate ordinary SDK reader process required')
                pidset.add(app['pid']);active=lease['active'];expected[member].append(active)
                if (set(active)!={'stage','api','token','epoch','expires_ns','started_ns','deadline_ns','returned_ns','client_closed'}
                    or active['stage']!='ssap_subscription_active'or active['api']!=reader_api or active['client_closed']is not True
                    or any(type(active[k])is not int or active[k]<=0 for k in ('token','epoch','expires_ns','started_ns','deadline_ns','returned_ns'))
                    or active['epoch']!=epochs[s]or active['token']in tokens or active['deadline_ns']-active['started_ns']!=5_000_000_000
                    or not active['started_ns']<=active['returned_ns']<active['deadline_ns'] or lease['ready_ns']<active['returned_ns']
                    or not active['started_ns']+30_000_000_000<=active['expires_ns']<=active['deadline_ns']+30_000_000_000):raise CaptureError('distinct original shared token/lease/deadline required')
                tokens.add(active['token'])
            if len({v['active']['epoch']for v in leases})!=1:raise CaptureError('same original security epoch required')
            if not(by_member['a0']['released_wall_ns']<=group['messages'][3]['start_wall_ns']<=group['messages'][4]['end_wall_ns']<=by_member['a1']['application']['start_wall_ns']):raise CaptureError('partial release,continued sibling business then fresh replacement required')
            if not(by_member['a0']['ready_wall_ns']<=by_member['b']['application']['start_wall_ns']<=by_member['b']['ready_wall_ns']<=group['messages'][0]['start_wall_ns']
                and by_member['a1']['ready_wall_ns']<=group['messages'][5]['start_wall_ns']):raise CaptureError('both actual acquisitions before publication and fresh acquisition before replacement data required')
            for number,case in enumerate(group['messages']):
                wanted=['a0','b']if number<3 else['b']if number<5 else['a1','b'];sequence=(row['phase']<<24)|(s<<20)|(mode<<16)|number;value=bytes.fromhex(case['value'])
                if type(case['number'])is not int or case['number']!=number or [r['member']for r in case['recipients']]!=wanted or len(value)!=32 or value in unique or value[:4]!=sequence.to_bytes(4,'little'):raise CaptureError('finite original random update and recipient order required')
                unique.add(value);pdu=bytes([16 if mode==2 else 15,3])+h.to_bytes(2,'little')+b'\x20\0'+value
                sent=sdk_receipt(case['send'],api,h,{'stage','pdu','ack'});replacement=sdk_receipt(case['replacement'],api,h,{'value'})
                if sent['stage']!=(2 if mode==2 else 1)or sent['pdu']!=pdu.hex()or sent['ack']!=('110301'if mode==2 else'')or replacement['value']!=case['value']or case['before']['value']!=case['value']:raise CaptureError('actual SDK shared update and owner snapshot required')
                commands['SdkOwnedReplaced'].append(case['replacement']['receipt']);commands['SdkOwnedUpdate'].append(case['send']['receipt']);snapshots.append((str(h),case['value']))
                data=exchange(t,s,pdu,case)
                if mode==2:exchange(s,t,b'\x11\x03\x01',case['send'])
                for received in case['recipients']:
                    member=received['member'];lease=by_member[member];counts[member]+=1;reader_api=lease['application']['api'];reply=bytes.fromhex(received['reply']);prefix=sequence|0x80000000|((1 if member=='b'else 2 if member=='a1'else 0)<<12)
                    if len(reply)!=32 or reply in unique or reply[:4]!=prefix.to_bytes(4,'little'):raise CaptureError('independent recipient sequence/random business reply required')
                    unique.add(reply);n=counts[member]
                    checked=dict(stage='ssap_subscription_checked_reply',api=reader_api,sequence=n,value=case['value'],reply=received['reply'])
                    batch=dict(stage='ssap_subscription_batch',api=reader_api,last=n,dropped=0,refused=0,state=1,flags=0,reason=0,discarded=0,packets=[dict(sequence=n,epoch=lease['active']['epoch'],level=2,indication=mode==2,pdu=pdu.hex())])
                    if received['checked']!=checked or received['batch']!=batch or received['after']['value']!=received['reply']:raise CaptureError('actual independent application comparison/batch/writeback required')
                    expected[member].extend((checked,batch));snapshots.append((str(h),received['reply']))
                    request=exchange(s,t,b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+reply,received);response=exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+reply,received)
                    if not(case['start_wall_ns']<=received['start_wall_ns']<=request['tx']['wall_ns']<=response['rx']['wall_ns']<=received['end_wall_ns']<=case['end_wall_ns']):raise CaptureError('original per-recipient writeback window required')
                if not(group['start_wall_ns']<=case['start_wall_ns']<=case['send']['start_wall_ns']<=case['send']['end_wall_ns']<=case['end_wall_ns']<=group['end_wall_ns']):raise CaptureError('original shared update window required')
            for member,lease in by_member.items():
                started=lease['release_started'];flags=1 if member=='b'else 3;reader_api=lease['application']['api']
                if (set(started)!={'stage','api','started_ns','deadline_ns'}or started['stage']!='ssap_subscription_release_started'or started['api']!=reader_api
                    or any(type(started[k])is not int for k in ('started_ns','deadline_ns'))or started['deadline_ns']-started['started_ns']!=5_000_000_000
                    or not lease['release_request_ns']<=started['started_ns']<=lease['release_completed_ns']<started['deadline_ns']
                    or any(type(lease['release'][k])is not int for k in ('flags','discarded'))or lease['release']!=dict(stage='ssap_subscription_released',api=reader_api,flags=flags,discarded=0)):raise CaptureError('actual original scoped cleanup receipt required')
                expected[member].extend((started,lease['release']))
                if [json.loads(v)for v in lease['application']['stdout'].splitlines()]!=expected[member]:raise CaptureError('complete exact independent reader stream required')
            if not by_member['a1']['released_wall_ns']<=by_member['b']['release_request_wall_ns']:raise CaptureError('last reference cleanup order required')
            for key,wanted in [('enabled',mode),('retained_observation',mode),('disabled',0)]:
                records=group[key]
                if not 1<=len(records)<=12:raise CaptureError('finite actual shared configuration observation required')
                receipts=[sdk_receipt(v,api,h,{'modes'})for v in records]
                if receipts[-1]['modes']!=wanted:raise CaptureError('actual shared configuration outcome required')
                if key=='retained_observation'and not by_member['a0']['released_wall_ns']<=records[0]['start_wall_ns']<=records[-1]['end_wall_ns']<=group['messages'][3]['start_wall_ns']:raise CaptureError('actual retained observation between partial release and continued business required')
                commands['SdkOwnedConfiguration'].extend(v['receipt']for v in records)
            for request,response in [(b'\x08\x03'+h.to_bytes(2,'little')+b'\x02',b'\x09\x03\0\0'),(b'\x0d\x23'+h.to_bytes(2,'little')+bytes([2,mode,0]),b'\x0e\x03'+h.to_bytes(2,'little')+bytes([2,mode,0])),(b'\x0d\x23'+h.to_bytes(2,'little')+b'\x02\0\0',b'\x0e\x03'+h.to_bytes(2,'little')+b'\x02\0\0')]:
                window=dict(start_wall_ns=by_member['b']['release_request_wall_ns'],end_wall_ns=by_member['b']['release_completed_wall_ns'])if request[:2]==b'\x0d\x23'and request[-2:]==b'\0\0'else group
                exchange(s,t,request,window);exchange(t,s,response,window)
        import re
        for prefix,receipts in commands.items():
            if [json.loads(v)for v in re.findall('^'+prefix+r': (.+)$',item['stdout'],re.M)]!=receipts:raise CaptureError('actual shared provider transcript differs from receipts')
        if re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]+)$',item['stdout'],re.M)!=snapshots:raise CaptureError('actual shared provider snapshots differ')
        decisions=[json.loads(v)for v in re.findall(r'^SdkAuthorizationDecision: (.+)$',item['stdout'],re.M)]
        wanted=('0100','0000','0200','0000')
        if len(decisions)!=len(wanted):raise CaptureError('only original enable/finaldisable approvals required')
        for decision,value in zip(decisions,wanted,strict=True):
            authorization_context({k:v for k,v in decision.items()if k not in {'allow','decision_ns','decision_wall_ns'}},api,level=2,data_type=2)
            if (decision['index'],decision['generation'],decision['lifetime'],decision['handle'],decision['property'])!=(server['owner']['index'],server['owner']['generation'],server['object']['lifetime'],server['object']['handle'],h) or decision['value']!=value or decision['allow']is not True or decision['epoch']!=epochs[t]or decision['decision_ns']>=decision['deadline_ns']or not item['start_wall_ns']<=decision['decision_wall_ns']<=item['end_wall_ns']:raise CaptureError('actual bound shared configuration approval required')
        part=dict(sender=s,target=t,publisher=api,peer=other,leases=6,updates=14,application_replies=24,decisions=4,shared_contract_version=1,shared_groups=2,shared_joins=4,retained_releases=4,last_disables=2,wire=legs)
        if not part_valid(part,row['phase'],s):raise CaptureError('exact complete shared paired-wire matrix required')
        proof.append(part)
    return proof,credit


def configuration_wire(control,capture):
    from ws73_capture import reassemble_acb
    packets=reassemble_acb(capture);groups=[]
    for row in control['channel_socket']:
        for item in row['ssap_subscription']:
            peer=row['owners'][item['sender']];identity=peer['owner'];h=item['handle']
            for group in item['groups']:
                out=[p for p in packets if(p['bus'],p['device'],p['handle'],p['direction'])==(identity['bus'],identity['device'],peer['object']['handle'],'out')and group['start_wall_ns']<=p['wall_ns']<=group['end_wall_ns']and bytes.fromhex(p['data'])[4:9]==b'\x0d\x23'+h.to_bytes(2,'little')+b'\x02']
                wanted=[(b'\x0a\0\x07\0\x0d\x23'+h.to_bytes(2,'little')+bytes([2,group['mode'],0])).hex(),(b'\x0a\0\x07\0\x0d\x23'+h.to_bytes(2,'little')+b'\x02\0\0').hex()]
                if [p['data']for p in out]!=wanted:raise CaptureError('one real enable and only finalreference disable,without other configuration writes required')
                groups.append(dict(phase=row['phase'],sender=item['sender'],mode=group['mode'],writes=out))
    if len(groups)!=8:raise CaptureError('both shared directions/modes/roles required')
    return dict(status='EXACT_SHARED_REMOTE_CONFIGURATION_WRITES',groups=groups,enables=8,last_disables=8)


def valid_configuration_summary(proof):
    try:
        if proof['status']!='EXACT_SHARED_REMOTE_CONFIGURATION_WRITES'or any(type(proof[k])is not int or proof[k]!=8 for k in('enables','last_disables'))or len(proof['groups'])!=8:return False
        for group,(phase,sender,mode)in zip(proof['groups'],[(p,s,m)for p in(0,1)for s in(0,1)for m in(1,2)],strict=True):
            if any(type(group[k])is not int or group[k]!=v for k,v in dict(phase=phase,sender=sender,mode=mode).items())or len(group['writes'])!=2:return False
            a,b=group['writes'];raw=bytes.fromhex(a['data']);off=bytes.fromhex(b['data'])
            if len(raw)!=11 or raw[:6]!=b'\x0a\0\x07\0\x0d\x23'or raw[6:8]==b'\0\0'or raw[8:]!=bytes([2,mode,0])or off!=raw[:9]+b'\0\0':return False
            if any(type(a[k])is not int or a[k]<=0 for k in('bus','device','record','wall_ns'))or any(type(b[k])is not int or b[k]<=0 for k in('bus','device','record','wall_ns')):return False
            if a['direction']!='out'or b['direction']!='out'or(a['bus'],a['device'],a['handle'])!=(b['bus'],b['device'],b['handle'])or not a['record']<b['record']or not a['wall_ns']<=b['wall_ns']:return False
        return True
    except(KeyError,TypeError,ValueError):return False
