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
from ws73_ssap_owned import publisher,value_snapshot,await_removed,observed_process,wait_output
from ws73_ssap_update_delivery import configuration,command_receipt,discover,discovery_wire,sdk_receipt
from ws73_ssap_subscription import checked_update_reply,checked_cached_reply,wait_stage,role,shared_case,stop_reader_process

TOOL='/usr/share/sparklink/tools/ws73_ssap_shared.py'


def workload(kind):
    """Finite orchestration only;packet parsing and SDK I/O stay shared."""
    if kind not in ('release','expiry','owner-exit','pressure'):raise CaptureError('explicit shared workload required')
    return (22,18,20)if kind=='pressure'else(7,3 if kind=='release'else 4,5)


def recipients(kind,number):
    total,withdraw,fresh=workload(kind)
    if type(number)is not int or not 0<=number<total:raise CaptureError('finite original update number required')
    if kind=='pressure'and number<17:return ['b']
    return ['a0','b']if number<(withdraw if kind=='pressure'else 3)else['b']if number<fresh else['a1','b']


def pressure_batch(group,lease,handle):
    """Independent expected queue contents,not a simulated subscription."""
    mode=group['mode']
    packets=[dict(sequence=c['number']+1,epoch=lease['active']['epoch'],level=2,indication=mode==2,
        pdu=(bytes([16 if mode==2 else 15,3])+handle.to_bytes(2,'little')+b'\x20\0'+bytes.fromhex(c['value'])).hex())for c in group['messages'][:16]]
    return dict(stage='ssap_subscription_batch',api=lease['application']['api'],last=17,dropped=int(mode==1),refused=int(mode==2),
        state=1,flags=0,reason=0,discarded=0,packets=packets)

@contextmanager
def reader(run,row,peer,item,api,mode,member):
    duration=2000 if shared_case(row)=='expiry'and member=='a0'else 30000
    prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    args=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(item['handle']),str(mode),str(duration)]
    label=f'shared-{row["phase"]}-{item["sender"]}-{mode}-{member}';out=run.output/(label+'.stdout');err=run.output/(label+'.stderr')
    begin=time.time_ns()
    app=dict(api=api,args=args,environment=application_environment(),start_wall_ns=time.time_ns(),output_files=[str(out),str(err)])
    if shared_case(row)=='pressure':app['ssap_shared_pressure_contract_version']=1
    lease=dict(mode=mode,member=member,application=app,start_wall_ns=begin);item['leases'].append(lease);run.save();process=None
    try:
        with observed_process(args,app,out,err,user=1004,group=1004,extra_groups=[],env=dict(os.environ,**application_environment()),stdin=subprocess.PIPE,text=True)as process:
            app['pid']=process.pid;app['credentials'],app['process_status']=process_identity(process.pid,1004);run.save()
            lease['active']=wait_stage(process,app,'ssap_subscription_active',1,time.monotonic()+6);lease.update(ready_wall_ns=time.time_ns(),ready_ns=time.monotonic_ns());run.save()
            yield process,lease
    finally:
        lease['end_wall_ns']=time.time_ns();run.save()


def release(run,process,lease,flags):
    lease.update(release_request_wall_ns=time.time_ns(),release_request_ns=time.monotonic_ns());run.save()
    process.stdin.write('release-observe\n');process.stdin.flush()
    lease['release_started']=wait_stage(process,lease['application'],'ssap_subscription_release_started',1,time.monotonic()+1)
    lease['release']=wait_stage(process,lease['application'],'ssap_subscription_released',1,lease['release_started']['deadline_ns']/1e9)
    lease.update(release_completed_ns=time.monotonic_ns(),release_completed_wall_ns=time.time_ns())
    if lease['release']!=dict(stage='ssap_subscription_released',api=lease['application']['api'],flags=flags,discarded=0):raise CaptureError('actual scoped lease release result required')
    process.stdin.write('quit\n');process.stdin.flush();wait_output(process,2)
    if process.returncode:raise CaptureError('actual shared reader exit')
    lease['released_wall_ns']=time.time_ns();run.save()


def expire_reader(run,process,lease):
    """Observe the original lease expiry;never issue release to produce it."""
    expires=lease['active']['expires_ns']
    observed=dict(original_expires_ns=expires,wait_started_ns=time.monotonic_ns())
    lease['expiry']=observed;run.save()
    while time.monotonic_ns()<expires:
        time.sleep(min(.01,max(0,(expires-time.monotonic_ns())/1e9)))
    observed.update(read_request_ns=time.monotonic_ns(),read_request_wall_ns=time.time_ns())
    process.stdin.write('poll\n');process.stdin.flush()
    lease['expiry_observation']=wait_stage(process,lease['application'],'ssap_subscription_batch',4,time.monotonic()+5)
    observed.update(observed_ns=time.monotonic_ns(),observed_wall_ns=time.time_ns())
    if lease['expiry_observation']!=dict(stage='ssap_subscription_batch',api=lease['application']['api'],last=4,dropped=0,refused=0,state=3,flags=3,reason=2,discarded=1,packets=[]):
        raise CaptureError('actual original expiry retained sibling and discarded accepted unread data required')
    process.stdin.write('quit\n');process.stdin.flush();wait_output(process,2)
    if process.returncode:raise CaptureError('actual expired reader exit')
    lease['withdrawn_wall_ns']=time.time_ns();run.save()


def execute(run,row):
    from ws73_ssap_subscription import STATUS
    kind=shared_case(row);pressure=kind=='pressure';total,withdraw,fresh_at=workload(kind)
    row.update(ssap_subscription=[],ssap_subscription_required=True,ssap_subscription_contract_version=1,ssap_subscription_output_contract_version=1);run.save()
    for sender in(0,1):
        peer,server=row['owners'][sender],row['owners'][1-sender];api='c'if(row['phase']+sender)%2==0 else'python';other='python'if api=='c'else'c'
        with publisher(run,row,sender,'allow',collection='ssap_subscription',label='shared-subscription',sdk_api=api,updates=True,application_uid=1005)as(owner,item):
            if pressure:item['ssap_shared_pressure_contract_version']=1
            discover(run,peer,item);item.update(leases=[],groups=[]);run.save()
            for mode in(1,2):
                group=dict(mode=mode,start_wall_ns=time.time_ns(),messages=[],lease_indexes=[]);item['groups'].append(group)
                with ExitStack()as resources:
                    a,la=resources.enter_context(reader(run,row,peer,item,other,mode,'a0'));group['lease_indexes'].append(len(item['leases'])-1)
                    group['enabled']=configuration(owner,item,mode,a);run.save()
                    b,lb=resources.enter_context(reader(run,row,peer,item,api,mode,'b'));group['lease_indexes'].append(len(item['leases'])-1)
                    if la['active']['token']==lb['active']['token']or la['active']['epoch']!=lb['active']['epoch']:raise CaptureError('independent token at original epoch required')
                    counts={'a0':0,'b':0,'a1':0}
                    def receive(case,member,process,lease,records,*,callback=None,cached=False):
                        number=case['number'];sequence=(row['phase']<<24)|(sender<<20)|(mode<<16)|number
                        reply=((sequence|0x80000000|((1 if member=='b'else 2 if member=='a1'else 0)<<12)).to_bytes(4,'little')+secrets.token_bytes(28)).hex()
                        received=dict(member=member,reply=reply,start_wall_ns=time.time_ns());counts[member]+=1
                        if cached:received['number']=number
                        records.append(received);run.save()
                        if cached:
                            checked_cached_reply(process,lease['application'],owner,item,case['value'],reply,counts[member],limit=128,record=received,save=run.save)
                        else:
                            result=checked_update_reply(process,lease['application'],owner,item,case['value'],reply,counts[member],
                                2 if pressure and member=='a0'else counts[member],limit=128 if pressure else 48,before_wait=callback,record=received,save=run.save)
                            if 'send'in result:case['send']=result.pop('send')
                        received['end_wall_ns']=time.time_ns();return received
                    for number in range(total):
                        if number==withdraw and kind in ('release','pressure'):
                            release(run,a,la,3);group['retained_observation']=configuration(owner,item,mode,b);run.save()
                        if number==withdraw and kind in ('expiry','owner-exit'):
                            if time.monotonic_ns()>=la['active']['expires_ns']:raise CaptureError('unread publication must finish before original expiry')
                            if kind=='expiry':expire_reader(run,a,la)
                            else:
                                stop_reader_process(run,la,a);la['withdrawn_wall_ns']=time.time_ns();run.save()
                            group['retained_observation']=configuration(owner,item,mode,b);run.save()
                        if number==fresh_at:
                            fresh,lf=resources.enter_context(reader(run,row,peer,item,other,mode,'a1'));group['lease_indexes'].append(len(item['leases'])-1)
                            if lf['active']['token']in(la['active']['token'],lb['active']['token'])or lf['active']['epoch']!=lb['active']['epoch']:raise CaptureError('fresh replacement token and unchanged epoch required')
                        if pressure and number==17:
                            drain=dict(start_wall_ns=time.time_ns(),recipients=[]);group['drain']=drain;run.save()
                            a.stdin.write('drain\n');a.stdin.flush()
                            drain['batch']=wait_stage(a,la['application'],'ssap_subscription_batch',1,time.monotonic()+6)
                            if drain['batch']!=pressure_batch(group,la,item['handle']):raise CaptureError('slow queue ordered first16/overflow counters required')
                            for filled in group['messages'][:16]:
                                receive(filled,'a0',a,la,drain['recipients'],cached=True);run.save()
                            drain['end_wall_ns']=time.time_ns();run.save()
                        members=dict(a0=(a,la),b=(b,lb))
                        if number>=fresh_at:members['a1']=(fresh,lf)
                        peers=[(member,*members[member])for member in recipients(kind,number)]
                        sequence=(row['phase']<<24)|(sender<<20)|(mode<<16)|number;value=(sequence.to_bytes(4,'little')+secrets.token_bytes(28)).hex()
                        case=dict(number=number,value=value,start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns(),recipients=[]);group['messages'].append(case)
                        case['replacement']=command_receipt(owner,item,'replace '+value,'SdkOwnedReplaced',limit=64 if pressure else 32);case['before']=value_snapshot(owner,item,value,limit=128 if pressure else 48);run.save()
                        for position,(member,process,lease)in enumerate(peers):
                            callback=(lambda:command_receipt(owner,item,'indicate'if mode==2 else'notify','SdkOwnedUpdate',limit=64 if pressure else 32))if position==0 else None
                            receive(case,member,process,lease,case['recipients'],callback=callback);run.save()
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
        kind=value.get('shared_case','release');version=value.get('shared_lifetime_contract_version');pressure=value.get('shared_pressure_contract_version')
        if (type(kind)is not str or kind not in ('release','expiry','owner-exit','pressure')
            or kind in ('release','pressure')and version is not None
            or kind in ('expiry','owner-exit')and(type(version)is not int or version!=1)
            or kind=='pressure'and(type(pressure)is not int or pressure!=1)
            or kind!='pressure'and pressure is not None):return False
        if kind=='release'and any(value.get(k)is not None for k in ('partial_expirations','expired_discarded','partial_owner_exits','unconsumed_published')):return False
        if kind=='expiry'and any(value.get(k)is not None for k in ('partial_owner_exits','unconsumed_published')):return False
        if kind=='owner-exit'and any(value.get(k)is not None for k in ('partial_expirations','expired_discarded')):return False
        wanted=dict(sender=sender,target=1-sender,leases=6,updates=44 if kind=='pressure'else 14,application_replies=82 if kind=='pressure'else 24,decisions=4,shared_contract_version=1,shared_groups=2,shared_joins=4,retained_releases=2 if kind=='owner-exit'else 4,last_disables=2)
        if kind=='expiry':wanted.update(partial_expirations=2,expired_discarded=2)
        if kind=='owner-exit':wanted.update(partial_owner_exits=2,unconsumed_published=2)
        if kind=='pressure':wanted.update(slow_notification_drops=1,slow_indication_refusals=1,healthy_losses=0,ordered_drains=2,resumed=2,healthy_replies=44)
        if kind=='pressure'and any(value.get(k)is not None for k in ('partial_expirations','expired_discarded','partial_owner_exits','unconsumed_published')):return False
        if kind!='pressure'and any(value.get(k)is not None for k in ('slow_notification_drops','slow_indication_refusals','healthy_losses','ordered_drains','resumed','healthy_replies')):return False
        return(all(type(value[k])is type(v)and value[k]==v for k,v in wanted.items())
            and value['publisher']==api and value['peer']==('python'if api=='c'else'c')
            and len(value['wire'])==(252 if kind=='pressure'else 91)and all(valid_wire(v)for v in value['wire'])
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


def validate_owner_exit_timing(lease,group):
    """Original child/sibling window;caller also verifies roles,transcripts,wire.

    An exit after the original lease expiry cannot establish owner-loss cause.
    This is the actual wire-verifier predicate,not a second lifetime model.
    """
    death=lease['owner_loss'];case=group['messages'][3];expires=lease['active']['expires_ns']
    fields=('pid','signal','exit','start_monotonic_ns','exit_monotonic_ns','observation_deadline_ns','start_wall_ns','exit_wall_ns')
    if ('expiry'in lease or 'expiry_observation'in lease or any(type(death.get(k))is not int for k in fields)
        or type(expires)is not int or expires<=0
        or death['pid']!=lease['application']['pid']or death['signal']!=9 or death['exit']!=-9
        or death['observation_deadline_ns']-death['start_monotonic_ns']!=5_000_000_000
        or not case['end_monotonic_ns']<=death['start_monotonic_ns']<=death['exit_monotonic_ns']<death['observation_deadline_ns']
        or death['exit_monotonic_ns']>=expires
        or not case['end_wall_ns']<=death['start_wall_ns']<=death['exit_wall_ns']<=lease['withdrawn_wall_ns']
        or group['messages'][4]['end_monotonic_ns']>=death['observation_deadline_ns']):
        raise CaptureError('actual child exit before original lease expiry and bounded continuing sibling business required')


def corroborate(row,matched):
    owners=row['owners'];proof=[];credit={0:0,1:0};unique=set();epochs=native_security_epochs(row);kind=shared_case(row)
    pressure=kind=='pressure';total,withdraw,fresh_at=workload(kind)
    if len(row.get('ssap_subscription',[]))!=2:raise CaptureError('two original shared providers required')
    for sender,item in enumerate(row['ssap_subscription']):
        s,t=sender,1-sender;peer,server=owners[s],owners[t];api='c'if(row['phase']+s)%2==0 else'python';other='python'if api=='c'else'c';h=item['handle'];legs=[];snapshots=[];tokens=set();pidset=set();commands={'SdkOwnedReplaced':[],'SdkOwnedUpdate':[],'SdkOwnedConfiguration':[]}
        if(item['sender']!=s or item['target']!=t or item['publisher_api']!=api or item['policy']!='allow'
            or (type(item.get('ssap_shared_pressure_contract_version'))is not int or item['ssap_shared_pressure_contract_version']!=1 if pressure else item.get('ssap_shared_pressure_contract_version')is not None)
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
            if (type(group['mode'])is not int or group['mode']!=mode or group['lease_indexes']!=indexes or len(group['messages'])!=total
                or pressure and 'drain'not in group or not pressure and 'drain'in group):raise CaptureError('complete finite shared group matrix required')
            for member,lease in by_member.items():
                app=lease['application'];reader_api=api if member=='b'else other;role(app['credentials'],1004)
                prefix=['/bin/ws73-application-client-c']if reader_api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
                duration=2000 if kind=='expiry'and member=='a0'else 30000
                expected_exit=-9 if kind=='owner-exit'and member=='a0'else 0
                if (lease['member']!=member or type(lease['mode'])is not int or lease['mode']!=mode or app['api']!=reader_api or app['environment']!=application_environment()
                    or (type(app.get('ssap_shared_pressure_contract_version'))is not int or app['ssap_shared_pressure_contract_version']!=1 if pressure else app.get('ssap_shared_pressure_contract_version')is not None)
                    or app['args']!=prefix+['subscription',str(peer['owner']['index']),str(peer['owner']['generation']),peer['object']['path'],str(h),str(mode),str(duration)]
                    or type(app['exit'])is not int or app['exit']!=expected_exit or app['stderr']or type(app['pid'])is not int or app['pid']<=0 or app['pid']in pidset
                    or not group['start_wall_ns']<=lease['start_wall_ns']<=app['start_wall_ns']<=app['end_wall_ns']<=lease['end_wall_ns']<=group['end_wall_ns']<=item['end_wall_ns']):raise CaptureError('actual separate ordinary SDK reader process required')
                pidset.add(app['pid']);active=lease['active'];expected[member].append(active)
                if (set(active)!={'stage','api','token','epoch','expires_ns','started_ns','deadline_ns','returned_ns','client_closed'}
                    or active['stage']!='ssap_subscription_active'or active['api']!=reader_api or active['client_closed']is not True
                    or any(type(active[k])is not int or active[k]<=0 for k in ('token','epoch','expires_ns','started_ns','deadline_ns','returned_ns'))
                    or active['epoch']!=epochs[s]or active['token']in tokens or active['deadline_ns']-active['started_ns']!=5_000_000_000
                    or not active['started_ns']<=active['returned_ns']<active['deadline_ns'] or lease['ready_ns']<active['returned_ns']
                    or not active['started_ns']+duration*1_000_000<=active['expires_ns']<=active['deadline_ns']+duration*1_000_000):raise CaptureError('distinct original shared token/lease/deadline required')
                tokens.add(active['token'])
            if len({v['active']['epoch']for v in leases})!=1:raise CaptureError('same original security epoch required')
            withdrawn=by_member['a0']['released_wall_ns']if kind in ('release','pressure')else by_member['a0']['withdrawn_wall_ns']
            first_after=withdraw
            if not(withdrawn<=group['messages'][first_after]['start_wall_ns']<=group['messages'][fresh_at-1]['end_wall_ns']<=by_member['a1']['application']['start_wall_ns']):raise CaptureError('partial withdrawal,continued sibling business then fresh replacement required')
            if not(by_member['a0']['ready_wall_ns']<=by_member['b']['application']['start_wall_ns']<=by_member['b']['ready_wall_ns']<=group['messages'][0]['start_wall_ns']
                and by_member['a1']['ready_wall_ns']<=group['messages'][fresh_at]['start_wall_ns']):raise CaptureError('both actual acquisitions before publication and fresh acquisition before replacement data required')
            def verify_reply(received,case,window,*,cached=False):
                member=received['member'];lease=by_member[member];counts[member]+=1;reader_api=lease['application']['api'];reply=bytes.fromhex(received['reply'])
                number=case['number'];sequence=(row['phase']<<24)|(s<<20)|(mode<<16)|number;prefix=sequence|0x80000000|((1 if member=='b'else 2 if member=='a1'else 0)<<12)
                if len(reply)!=32 or reply in unique or reply[:4]!=prefix.to_bytes(4,'little'):raise CaptureError('independent recipient sequence/random business reply required')
                unique.add(reply);n=number+1 if pressure and member=='a0'else counts[member]
                pdu=bytes([16 if mode==2 else 15,3])+h.to_bytes(2,'little')+b'\x20\0'+bytes.fromhex(case['value'])
                checked=dict(stage='ssap_subscription_checked_reply',api=reader_api,sequence=n,value=case['value'],reply=received['reply'])
                if received['checked']!=checked or received['after']['value']!=received['reply']:raise CaptureError('actual independent application comparison/writeback required')
                expected[member].append(checked)
                if cached:
                    if member!='a0'or type(received['number'])is not int or received['number']!=number or 'batch'in received:raise CaptureError('actual ordered cached check,not a second read required')
                else:
                    batch=dict(stage='ssap_subscription_batch',api=reader_api,last=n,dropped=int(pressure and member=='a0'and mode==1),refused=int(pressure and member=='a0'and mode==2),state=1,flags=0,reason=0,discarded=0,packets=[dict(sequence=n,epoch=lease['active']['epoch'],level=2,indication=mode==2,pdu=pdu.hex())])
                    if received['batch']!=batch:raise CaptureError('actual independent receive batch/loss counters required')
                    expected[member].append(batch)
                snapshots.append((str(h),received['reply']))
                request=exchange(s,t,b'\x0d\x23'+h.to_bytes(2,'little')+b'\0'+reply,received);response=exchange(t,s,b'\x0e\x03'+h.to_bytes(2,'little')+b'\0'+reply,received)
                if not(window['start_wall_ns']<=received['start_wall_ns']<=request['tx']['wall_ns']<=response['rx']['wall_ns']<=received['end_wall_ns']<=window['end_wall_ns']):raise CaptureError('original per-recipient writeback window required')
            for number,case in enumerate(group['messages']):
                if pressure and number==17:
                    drain=group['drain'];slow=by_member['a0']
                    if (drain['batch']!=pressure_batch(group,slow,h)or len(drain['recipients'])!=16
                        or not group['messages'][16]['end_wall_ns']<=drain['start_wall_ns']<=drain['end_wall_ns']<=case['start_wall_ns']):raise CaptureError('actual bounded full slow queue then ordered drain before resume required')
                    expected['a0'].append(drain['batch'])
                    for filled,received in zip(group['messages'][:16],drain['recipients'],strict=True):verify_reply(received,filled,drain,cached=True)
                wanted=recipients(kind,number);sequence=(row['phase']<<24)|(s<<20)|(mode<<16)|number;value=bytes.fromhex(case['value'])
                if type(case['number'])is not int or case['number']!=number or [r['member']for r in case['recipients']]!=wanted or len(value)!=32 or value in unique or value[:4]!=sequence.to_bytes(4,'little'):raise CaptureError('finite original random update and recipient order required')
                unique.add(value);pdu=bytes([16 if mode==2 else 15,3])+h.to_bytes(2,'little')+b'\x20\0'+value
                sent=sdk_receipt(case['send'],api,h,{'stage','pdu','ack'});replacement=sdk_receipt(case['replacement'],api,h,{'value'})
                if sent['stage']!=(2 if mode==2 else 1)or sent['pdu']!=pdu.hex()or sent['ack']!=('110301'if mode==2 else'')or replacement['value']!=case['value']or case['before']['value']!=case['value']:raise CaptureError('actual SDK shared update and owner snapshot required')
                commands['SdkOwnedReplaced'].append(case['replacement']['receipt']);commands['SdkOwnedUpdate'].append(case['send']['receipt']);snapshots.append((str(h),case['value']))
                data=exchange(t,s,pdu,case)
                if mode==2:exchange(s,t,b'\x11\x03\x01',case['send'])
                for received in case['recipients']:verify_reply(received,case,case)
                if not(group['start_wall_ns']<=case['start_wall_ns']<=case['send']['start_wall_ns']<=case['send']['end_wall_ns']<=case['end_wall_ns']<=group['end_wall_ns']):raise CaptureError('original shared update window required')
            for member,lease in by_member.items():
                reader_api=lease['application']['api']
                if member=='a0'and kind not in ('release','pressure'):
                    if any(k in lease for k in ('release','release_started','release_request_ns','release_request_wall_ns','released_wall_ns')):raise CaptureError('manual release cannot substitute shared lifetime withdrawal')
                    case=group['messages'][3]
                    if kind=='expiry':
                        observed=lease['expiry'];expires=lease['active']['expires_ns'];terminal=dict(stage='ssap_subscription_batch',api=reader_api,last=4,dropped=0,refused=0,state=3,flags=3,reason=2,discarded=1,packets=[])
                        if (set(observed)!={'original_expires_ns','wait_started_ns','read_request_ns','read_request_wall_ns','observed_ns','observed_wall_ns'}
                            or observed['original_expires_ns']!=expires or not case['end_monotonic_ns']<=observed['wait_started_ns']<expires<=observed['read_request_ns']<=observed['observed_ns']<observed['read_request_ns']+5_000_000_000
                            or not case['end_wall_ns']<=observed['read_request_wall_ns']<=observed['observed_wall_ns']<=withdrawn
                            or lease['expiry_observation']!=terminal or 'owner_loss'in lease):raise CaptureError('actual original expiry/retained terminal/accepted unread discard required')
                        expected[member].append(terminal)
                    else:
                        validate_owner_exit_timing(lease,group)
                else:
                    if any(k in lease for k in ('expiry','owner_loss','expiry_observation')):raise CaptureError('unexpected lifetime observation on surviving owner')
                    started=lease['release_started'];flags=1 if member=='b'else 3
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
                if key=='retained_observation'and not withdrawn<=records[0]['start_wall_ns']<=records[-1]['end_wall_ns']<=group['messages'][first_after]['start_wall_ns']:raise CaptureError('actual retained observation between partial release and continued business required')
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
        part=dict(sender=s,target=t,publisher=api,peer=other,leases=6,updates=44 if pressure else 14,application_replies=82 if pressure else 24,decisions=4,shared_contract_version=1,shared_groups=2,shared_joins=4,retained_releases=2 if kind=='owner-exit'else 4,last_disables=2,wire=legs)
        if pressure:part.update(shared_case=kind,shared_pressure_contract_version=1,slow_notification_drops=1,slow_indication_refusals=1,healthy_losses=0,ordered_drains=2,resumed=2,healthy_replies=44)
        elif kind!='release':part.update(shared_case=kind,shared_lifetime_contract_version=1,**({'partial_expirations':2,'expired_discarded':2}if kind=='expiry'else{'partial_owner_exits':2,'unconsumed_published':2}))
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
