# SPDX-License-Identifier: GPL-2.0-only
"""Finite receipt/terminal fixtures;not a controller,USB or RF qualification."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_capture import CaptureError
from ws73_application_client import application_environment
from ws73_ssap_owner_lifecycle import timeout_arguments,timeout_receipt,valid_summary,corroborate,STATUS
from ws73_target import run_exit_code


def fixture(api='c'):
    source={'owner':{'index':2,'generation':7},'object':{'path':'/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b'}}
    item={'handle':17,'value':'34'*32}
    call={'stage':'ssap_call','api':api,'deadline_ns':6_000_000_000,'call_ns':1_100_000_000,'client_closed':True}
    result={'stage':'ssap_error','api':api,'errno':110,'operation_success':False,'deadline_ns':6_000_000_000,'returned_ns':6_010_000_000}
    command={'args':timeout_arguments(api,source,item),'environment':application_environment(),'exit':0,'stderr':'','stdout':json.dumps(call)+'\n'+json.dumps(result)+'\n','start_monotonic_ns':1_000_000_000,'end_monotonic_ns':6_020_000_000,'credentials':{'uids':[1000]*4,'capabilities':{k:'0'for k in ['CapEff','CapPrm','CapAmb','CapInh']}}}
    return source,item,command,call,result


def summary():
    phases=[]
    for n in(0,1):
        source,item,command,_,_=fixture('c'if n==0 else'python')
        wire=[dict(tx=dict(bus=1,device=2,handle=1,wall_ns=100+j,data='0a0002000803',direction='out'),rx=dict(bus=1,device=3,handle=2,wall_ns=101+j,data='0a0002000803',direction='in'))for j in range(9)]
        p=dict(sender=n,target=1-n,owner_exit_peer_error=9,stale_token_rejected=True,late_token_rejected=True,late_denial_physical_obligation=False,deadline_elapsed_ns=5_020_000_000,wire=wire,timeout=timeout_receipt(command,'c'if n==0 else'python',source,item))
        phases.append(dict(phase=n,ssap_owner_lifecycle=[p]))
    return {'status':'ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED','proofs':phases}


def wire_fixture(phase=0,late=True):
    """Independent golden request/error records,never a successful wire stub."""
    N=1_000_000_000;W=1_800_000_000_000_000_000
    wall=lambda n:W+int(n*N)
    owners=[dict(owner=dict(index=n,generation=n+7,path=f'/a{n}'),object=dict(lifetime=11,handle=n+1,path=f'/a{n}/link'))for n in(0,1)]
    s,t=phase,1-phase;row=dict(phase=phase,owners=owners,security_requirement=0,ssap_receipts=[{'args':['slctl']}],ssap_owner_lifecycle_required=True,ssap_owner_lifecycle_status=STATUS)
    def item(case,policy,h,start,end):
        data=lambda k:hashlib.sha256((case+k).encode()).hexdigest()
        v=dict(case=case,policy=policy,sender=s,target=t,handle=h,start=h-1,end=h,secret=data('secret'),value=data('value'),uuid=data('uuid')[:32],service=data('service')[:32],start_wall_ns=wall(start),end_wall_ns=wall(end),exit=-9,stderr='',credentials={'uids':[1000]*4,'capabilities':{'CapEff':'0','CapPrm':'0','CapAmb':'0'}})
        v['args']=['slctl','--adapter',owners[t]['owner']['path'],'ssap-serve',v['service'],v['uuid'],'5','36',v['secret'],policy]
        v['stdout']=f'SsapOwnedService: start={h-1} end={h} property={h}; local registration only\n';return v
    g=item('guard','allow',17,1,16);ex=item('owner-exit','ask',19,2,4);e=item('original-deadline','ask',21,5,14);row['ssap_owner_lifecycle']=[g,ex,e]
    def event(i,token,request,at):
        fields=[str(token),str(request),str(t),str(owners[t]['owner']['generation']),'11',str(t+1),'9','0',str(i['handle']),'true','32',str(int((at+5)*N)),str(token),str(token)]
        v=dict(fields=fields,wall_ns=wall(at),monotonic_ns=int(at*N));i.setdefault('prompt_events',[]).append(v)
        i['stdout']+=f"SsapAuthorizationPrompt: token={token} request={request} index={t} generation={owners[t]['owner']['generation']} lifetime=11 handle={t+1} epoch=9 security=0 property={i['handle']} data_type=0 write=true bytes=32 deadline_ns={fields[11]}; answer 'yes {token}' or 'no {token}'\n"
        i.setdefault('peer_during_prompt',[]).append(dict(args=['slctl','--adapter',owners[s]['owner']['path'],'show'],exit=0,stdout='  State:       Ready\n',stderr=''))
    event(ex,1,7,2.1);event(e,1,8,5.2);event(e,2,9,6.2)
    ex.update(peer_error=9,owner_exit=-9,owner_exit_wall_ns=wall(2.4))
    ex['after_owner_exit']=dict(args=['slctl','--adapter',owners[t]['owner']['path'],'ssap-list'],exit=0,stdout='SsapLocalServices: []\n',stderr='',start_wall_ns=wall(2.5),end_wall_ns=wall(2.55))
    def command(op,h,at,end,value=None,error=None):
        args=['slctl','--adapter',owners[s]['owner']['path'],op,owners[s]['object']['path'],str(h)]
        if op=='ssap-write':args.append(value)
        args.append('0')
        return dict(args=args,exit=1 if error else 0,stdout=''if error else f'SsapPeerValue: operation={op} path={owners[s]["object"]["path"]} handle={h} value={value}\n',stderr=f'peer {"write"if op=="ssap-write"else"read"} error {error}'if error else'',start_wall_ns=wall(at),end_wall_ns=wall(end),credentials={'uids':[1000]*4,'capabilities':{'CapEff':'0'}})
    ex['write']=command('ssap-write',19,2.05,2.58,ex['value'],9);ex['removed_read']=command('ssap-read',19,2.6,2.7,error=4);ex['guard_read']=command('ssap-read',17,2.8,2.9,g['secret']);ex.update(guard_handle=17,guard_value=g['secret'])
    e['denied_write']=command('ssap-write',21,5.1,5.4,e['value'],9)
    source,_item,c,call,result=fixture('c'if phase==0 else'python');api=call['api'];c['args']=timeout_arguments(api,owners[s],e);c['start_monotonic_ns']=6*N;c['end_monotonic_ns']=int(11.05*N);c.update(start_wall_ns=wall(6),end_wall_ns=wall(11.05));call.update(call_ns=int(6.1*N),deadline_ns=11*N);result.update(deadline_ns=11*N,returned_ns=int(11.01*N));c['stdout']=json.dumps(call)+'\n'+json.dumps(result)+'\n';e.update(timed_write=c,timeout_api=api,timeout_receipt=timeout_receipt(c,api,owners[s],e))
    e.update(denial_input=dict(token=1,monotonic_ns=int(5.3*N)),stale_input=dict(token=1,monotonic_ns=int(6.3*N)),late_input=dict(token=2,monotonic_ns=int(11.3*N)))
    def snapshot(i,n,at):
        v=dict(ordinal=n,handle=i['handle'],value=i['secret'],start_monotonic_ns=int(at*N),end_monotonic_ns=int((at+.01)*N),start_wall_ns=wall(at),end_wall_ns=wall(at+.01));i.setdefault('value_snapshots',[]).append(v);i['stdout']+=f'SsapOwnedValue: handle={i["handle"]} value={i["secret"]}\n'
    for n,at in enumerate([5.5,6.4,11.31],1):snapshot(e,n,at)
    snapshot(g,1,12);g['other_owner_after_failed_request']=True
    sdus=[]
    def wire(a,b,pdu,at):
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        for n,d in[(a,'out'),(b,'in')]:sdus.append(dict(index=n,direction=d,data=frame.hex(),wall_ns=wall(at)))
    # Independent little-endian golden SSAP PDUs,not production encoder calls.
    wire(s,t,b'\x0d\x23\x13\0\0'+bytes.fromhex(ex['value']),2.2);wire(t,s,b'\x0e\x07\x01\x13\0\x09',2.3)
    wire(s,t,b'\x08\x03\x13\0\0',2.62);wire(t,s,b'\x09\x0b\x04\0',2.65)
    wire(s,t,b'\x08\x03\x11\0\0',2.82);wire(t,s,b'\x09\x03'+bytes.fromhex(g['secret']),2.85)
    wire(s,t,b'\x0d\x23\x15\0\0'+bytes.fromhex(e['value']),5.25);wire(t,s,b'\x0e\x07\x01\x15\0\x09',5.35)
    wire(s,t,b'\x0d\x23\x15\0\0'+bytes.fromhex(e['value']),6.25)
    if late:wire(t,s,b'\x0e\x07\x01\x15\0\x09',11.22)
    remaining=list(sdus)
    def matched(owner,direction,payload,window):
        matches=[p for p in remaining if p['index']==owners.index(owner)and p['direction']==direction and p['data']==payload.hex()and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(matches)!=1:raise CaptureError('one exact golden original leg required')
        remaining.remove(matches[0]);return matches[0]
    return row,matched,sdus,remaining


def sdk_wire_fixture(phase=0,late=True):
    row,matched,sdus,remaining=wire_fixture(phase,late)
    row['ssap_owner_publisher']='sdk';s,t=phase,1-phase;api='c'if phase==0 else'python'
    owners=row['owners'];g,ex,e=row['ssap_owner_lifecycle'];N=1_000_000_000;W=1_800_000_000_000_000_000
    wall=lambda n:W+int(n*N)
    closed=copy.deepcopy(ex)
    for key in ['peer_error','owner_exit','owner_exit_wall_ns','after_owner_exit','write','removed_read','guard_read','guard_handle','guard_value']:closed.pop(key,None)
    closed.update(case='close-pending',start=22,end=23,handle=23,start_wall_ns=wall(12.5),end_wall_ns=wall(15),exit=0,closed_exit=0,process_alive_after_close=True)
    for key,size in [('secret',32),('value',32),('uuid',16),('service',16)]:closed[key]=hashlib.sha256(('close-'+key).encode()).hexdigest()[:2*size]
    fields=['1','10',str(t),str(owners[t]['owner']['generation']),'11',str(t+1),'9','0','23','true','32',str(int(17.7*N)),'1','1']
    closed['prompt_events']=[dict(fields=fields,wall_ns=wall(12.7),monotonic_ns=int(12.7*N))]
    closed['stdout']=f"SsapOwnedService: start=22 end=23 property=23; local registration only\nSsapAuthorizationPrompt: token=1 request=10 index={t} generation={owners[t]['owner']['generation']} lifetime=11 handle={t+1} epoch=9 security=0 property=23 data_type=0 write=true bytes=32 deadline_ns={fields[11]}; answer 'yes 1' or 'no 1'\n"
    closed['peer_during_prompt']=[copy.deepcopy(ex['peer_during_prompt'][0])]
    closed['close_input']=dict(wall_ns=wall(12.8),monotonic_ns=int(12.8*N))
    closed['close_receipt']=dict(api=api,token=1,info_preserved=True,notification_fd_alive=True,reply_result=-116,closed_ns=int(12.9*N))
    closed['after_scope_close']=dict(args=['slctl','--adapter',owners[t]['owner']['path'],'ssap-list'],exit=0,stdout='SsapLocalServices: []\n',stderr='',start_wall_ns=wall(13),end_wall_ns=wall(13.05))
    closed.update(peer_error=9,guard_handle=g['handle'],guard_value=g['secret'])
    for name,template,h,start,end,error,value in [('write',ex['write'],23,12.6,13.1,9,closed['value']),('removed_read',ex['removed_read'],23,13.2,13.3,4,None),('guard_read',ex['guard_read'],17,13.4,13.5,None,g['secret'])]:
        c=copy.deepcopy(template);c.update(start_wall_ns=wall(start),end_wall_ns=wall(end));c['args'][5]=str(h)
        if name=='write':c['args'][6]=value
        c.update(exit=1 if error else 0,stdout=''if error else f'SsapPeerValue: operation=ssap-read path={owners[s]["object"]["path"]} handle=17 value={value}\n',stderr=f'peer {"write"if name=="write"else"read"} error {error}'if error else'')
        closed[name]=c
    closed['stdout']+='SdkServiceClosed: '+json.dumps(closed['close_receipt'])+'\n'+f'SdkOwnedClosedExit: api={api} start=22\n'
    g['value_snapshots'][0].update(start_wall_ns=wall(15.2),end_wall_ns=wall(15.21),start_monotonic_ns=int(15.2*N),end_monotonic_ns=int(15.21*N))
    row['ssap_owner_lifecycle'].append(closed)
    from ws73_application_client import owned_arguments
    for item in row['ssap_owner_lifecycle']:
        item.update(publisher_api=api,environment=application_environment(),args=owned_arguments(api,owners[t],item['service'],item['uuid'],item['secret'],item['policy']))
        item['stdout']=f'SdkOwnedAPI: api={api} client_closed=true\n'+item['stdout']
        for event in item.get('prompt_events',[]):
            f=event['fields'];context=dict(api=api,index=int(f[2]),generation=int(f[3]),token=int(f[0]),request_id=int(f[1]),lifetime=int(f[4]),handle=int(f[5]),epoch=int(f[6]),level=int(f[7]),deadline_ns=int(f[11]),property=int(f[8]),data_type=0,write=True,value=item['value'],local_tcid=10,remote_tcid=10,pi=0)
            item['stdout']+='SdkAuthorizationRequest: '+json.dumps(context)+'\n'
    for token,current,allow,called,result,key in [(1,1,False,True,0,'denial_input'),(1,2,True,False,-116,'stale_input'),(2,2,True,True,-110,'late_input')]:
        e['stdout']+='SdkAuthorizationReply: '+json.dumps(dict(api=api,token=token,current_token=current,allow=allow,api_called=called,result=result,returned_ns=e[key]['monotonic_ns']+1_000_000))+'\n'
    def wire(a,b,pdu,at):
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        for index,d in [(a,'out'),(b,'in')]:
            item=dict(index=index,direction=d,data=frame.hex(),wall_ns=wall(at));sdus.append(item);remaining.append(item)
    wire(s,t,b'\x0d\x23\x17\0\0'+bytes.fromhex(closed['value']),12.72);wire(t,s,b'\x0e\x07\x01\x17\0\x09',12.95)
    wire(s,t,b'\x08\x03\x17\0\0',13.22);wire(t,s,b'\x09\x0b\x04\0',13.25)
    wire(s,t,b'\x08\x03\x11\0\0',13.42);wire(t,s,b'\x09\x03'+bytes.fromhex(g['secret']),13.45)
    # Match the production sequence:live close is completed before deliberate
    # terminal obligation expiry. Preserve the original CLI deadline fixture.
    def earlier(value):
        if isinstance(value,dict):
            for key,entry in value.items():
                if key.endswith('_wall_ns'):value[key]=entry-int(8.5*N)
                elif key.endswith('_monotonic_ns') or key in ('monotonic_ns','wall_ns','closed_ns'):value[key]=entry-int(8.5*N)
                else:earlier(entry)
        elif isinstance(value,list):
            for entry in value:earlier(entry)
    old=closed['prompt_events'][0]['fields'][11];earlier(closed)
    closed['end_wall_ns']=wall(5)
    closed['prompt_events'][0]['fields'][11]=str(int(old)-int(8.5*N))
    closed['stdout']=closed['stdout'].replace(old,closed['prompt_events'][0]['fields'][11])
    # Context/deadline and close JSON must reflect the original shifted times.
    lines=[]
    for line in closed['stdout'].splitlines():
        if line.startswith('SdkServiceClosed: '):line='SdkServiceClosed: '+json.dumps(closed['close_receipt'])
        lines.append(line)
    closed['stdout']='\n'.join(lines)+'\n'
    for entry in sdus[-12:]:entry['wall_ns']-=int(8.5*N)
    row['ssap_owner_lifecycle']=[g,ex,closed,e]
    return row,matched,sdus,remaining


class LifecycleReceipts(unittest.TestCase):
    def test_untyped_or_descriptor_prompt_cannot_qualify_a_property_scenario(self):
        for replacement in ['', ' data_type=2', ' data_type=255']:
            row,matched,sdus,_=sdk_wire_fixture()
            row['ssap_owner_lifecycle'][1]['stdout']=row['ssap_owner_lifecycle'][1]['stdout'].replace(' data_type=0',replacement)
            with self.subTest(replacement=replacement),self.assertRaises(CaptureError):
                corroborate(row,matched,sdus)

    def test_sdk_variant_reuses_actual_wire_oracle_and_requires_all_close_cases(self):
        for phase in (0,1):
            for late in (False,True):
                row,matched,sdus,remaining=sdk_wire_fixture(phase,late)
                proof,_=corroborate(row,matched,sdus)
                self.assertEqual(proof[0]['publisher_api'],'c'if phase==0 else'python')
                self.assertEqual(proof[0]['sdk_reply_results'],[0,-116,-110])
                self.assertEqual(len(proof[0]['wire']),15+int(late));self.assertEqual(remaining,[])

    def test_sdk_proposals_actual_replies_and_live_close_cannot_be_omitted(self):
        for kind in ['order','mode','api','environment','args','header','missing-close','early-exit','snapshot','fd','accepted','time','cleanup','guard','removed','request','proposal','fake-api','stale-current','late-result']:
            row,matched,sdus,_=sdk_wire_fixture();g,ex,c,e=row['ssap_owner_lifecycle']
            if kind=='order':c['end_wall_ns']=e['start_wall_ns']+1
            elif kind=='mode':row['ssap_owner_publisher']='cli'
            elif kind=='api':c['publisher_api']='python'
            elif kind=='environment':c['environment']['LIBSPARKLINK_PATH']='/unrelated'
            elif kind=='args':c['args'][-1]='allow'
            elif kind=='header':c['stdout']=c['stdout'].replace('client_closed=true','client_closed=false')
            elif kind=='missing-close':del row['ssap_owner_lifecycle'][2]
            elif kind=='early-exit':c['process_alive_after_close']=False
            elif kind in ['snapshot','fd','accepted','time']:
                data=c['close_receipt'];old=json.dumps(data)
                if kind=='snapshot':data['info_preserved']=False
                elif kind=='fd':data['notification_fd_alive']=False
                elif kind=='accepted':data['reply_result']=0
                else:data['closed_ns']=1
                c['stdout']=c['stdout'].replace(old,json.dumps(data))
            elif kind=='cleanup':c['after_scope_close']['stdout']='SsapLocalServices: [[22]]\n'
            elif kind=='guard':c['guard_read']['stdout']='unverified'
            elif kind=='removed':c['removed_read']['exit']=0
            elif kind in ['request','proposal']:
                prefix='SdkAuthorizationRequest: ';line=next(v for v in c['stdout'].splitlines() if v.startswith(prefix));data=json.loads(line[len(prefix):]);data['request_id'if kind=='request'else'value']=0 if kind=='request'else'00'*32;c['stdout']=c['stdout'].replace(line,prefix+json.dumps(data))
            else:
                prefix='SdkAuthorizationReply: ';lines=[v for v in e['stdout'].splitlines() if v.startswith(prefix)];line=lines[1 if kind!='late-result'else 2];data=json.loads(line[len(prefix):])
                if kind=='fake-api':data['api_called']=True
                elif kind=='stale-current':data['current_token']=1
                else:data['result']=0
                e['stdout']=e['stdout'].replace(line,prefix+json.dumps(data))
            with self.subTest(kind=kind),self.assertRaises(CaptureError):corroborate(row,matched,sdus)

    def test_sdk_terminal_is_explicit_typed_and_does_not_relabel_cli(self):
        proof=summary()
        for n,phase in enumerate(proof['proofs']):
            p=phase['ssap_owner_lifecycle'][0];p['wire']+=copy.deepcopy(p['wire'][:6])
            p.update(publisher_api='c'if n==0 else'python',closed_scope_peer_error=9,closed_scope_process_alive=True,sdk_reply_results=[0,-116,-110],closed_scope=dict(api='c'if n==0 else'python',token=1,info_preserved=True,notification_fd_alive=True,reply_result=-116,closed_ns=2))
        self.assertFalse(valid_summary(proof));self.assertTrue(valid_summary(proof,publisher='sdk'))
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,ssap_owner_lifecycle_requested=True,ssap_owner_publisher_requested='sdk',ssap_owner_lifecycle_acceptance=True,ordinary_channel_socket_acceptance=True,channel_socket_corroboration=proof)
        self.assertEqual(run_exit_code(record),0)
        for kind in ['mode','missing-mode','type','closed','fd','alive','result','request']:
            bad=copy.deepcopy(record);p=bad['channel_socket_corroboration']['proofs'][0]['ssap_owner_lifecycle'][0]
            if kind=='mode':bad['ssap_owner_publisher_requested']='cli'
            elif kind=='missing-mode':bad.pop('ssap_owner_publisher_requested')
            elif kind=='type':p['sdk_reply_results'][0]=False
            elif kind=='closed':p['closed_scope']=[]
            elif kind=='fd':p['closed_scope']['notification_fd_alive']=False
            elif kind=='alive':p['closed_scope_process_alive']=False
            elif kind=='result':p['closed_scope']['reply_result']=0
            else:bad['ssap_owner_lifecycle_requested']=False
            with self.subTest(kind=kind):self.assertEqual(run_exit_code(bad),1)

    def test_finalizer_computes_supervisor_result_before_it_is_published(self):
        d=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
               ssap_owner_lifecycle_requested=True,ssap_owner_lifecycle_acceptance=True,
               ordinary_channel_socket_acceptance=True,channel_socket_corroboration=summary())
        # This is the actual _run finalizer's input state. It writes the
        # supervisor result only after calling this production verdict function.
        self.assertEqual(run_exit_code(d),1)  # saved record lacks final receipt
        self.assertEqual(run_exit_code(d,supervisor_pending=True),0)
        d['supervisor_exit']=0
        self.assertEqual(run_exit_code(d),0)
        for invalid in(1,None,False):
            d['supervisor_exit']=invalid
            self.assertEqual(run_exit_code(d),1)

    def test_conservative_clock_sampling_keeps_original_elapsed_guard(self):
        # Actual SDK Clock->Instant->stamp samples conservatively. Its effective
        # deadline may be shorter than the public argument;not a new budget.
        source,item,c,call,result=fixture()
        result['returned_ns']=result['deadline_ns']-100_000
        c['stdout']=json.dumps(call)+'\n'+json.dumps(result)+'\n'
        self.assertEqual(timeout_receipt(c,'c',source,item)['errno'],110)

    def test_two_languages_require_actual_errno_and_original_timing(self):
        for api in('c','python'):
            source,item,command,_,_=fixture(api)
            self.assertEqual(timeout_receipt(command,api,source,item)['errno'],110)

    def test_wrong_scope_missing_output_or_early_error_never_becomes_timeout_gate(self):
        for kind in('args','env','exit','stderr','missing','extra','success','errno','bool-errno','deadline','clock-type','early','late','call','queue','root','capability','wrong-api'):
            source,item,c,call,result=fixture()
            if kind=='args':c['args'][-1]='00'*32
            elif kind=='env':c['environment']['LIBSPARKLINK_PATH']='/old/lib.so'
            elif kind=='exit':c['exit']=1
            elif kind=='stderr':c['stderr']='unexpected failure'
            elif kind=='missing':result.pop('errno')
            elif kind=='extra':result['invented_success']=True
            elif kind=='success':result['operation_success']=True
            elif kind=='errno':result['errno']=5
            elif kind=='bool-errno':result['errno']=True
            elif kind=='deadline':result['deadline_ns']+=1
            elif kind=='clock-type':call['call_ns']=True
            elif kind=='early':result['returned_ns']=1_200_000_000;c['end_monotonic_ns']=1_300_000_000
            elif kind=='late':result['returned_ns']+=1_000_000_000;c['end_monotonic_ns']+=1_000_000_000
            elif kind=='call':call['call_ns']=call['deadline_ns']
            elif kind=='queue':c['start_monotonic_ns']=0
            elif kind=='root':c['credentials']['uids']=[0]*4
            elif kind=='capability':c['credentials']['capabilities']['CapEff']='1'
            else:result['api']='python'
            c['stdout']=json.dumps(call)+'\n'+json.dumps(result)+'\n'
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):
                timeout_receipt(c,'c',source,item)
        source,item,c,_,_=fixture();c['stdout']=''
        with self.assertRaises(CaptureError):timeout_receipt(c,'c',source,item)

    def test_terminal_requires_both_roles_and_all_actual_modes(self):
        p=summary();self.assertTrue(valid_summary(p))
        base={'status':'PASSTHROUGH_SUPPORT_PASS','qemu_exit':0,'supervisor_exit':0,'ssap_owner_lifecycle_requested':True,'ssap_owner_lifecycle_acceptance':True,'ordinary_channel_socket_acceptance':True,'channel_socket_corroboration':p}
        self.assertEqual(run_exit_code(base),0) # Shape fixture,not RF verdict.
        for kind in('request','missing-accept','process','missing-phase','empty','wire','stale','late','duration','api','errno','success','missing-time','optional-denial'):
            d=copy.deepcopy(base);v=d['channel_socket_corroboration']['proofs'][0]['ssap_owner_lifecycle'][0]
            if kind=='request':d['ssap_owner_lifecycle_requested']=False
            elif kind=='missing-accept':d.pop('ssap_owner_lifecycle_acceptance')
            elif kind=='process':d['supervisor_exit']=1
            elif kind=='missing-phase':d['channel_socket_corroboration']['proofs'].pop()
            elif kind=='empty':d['channel_socket_corroboration']['proofs'][0]['ssap_owner_lifecycle']=[]
            elif kind=='wire':v['wire'].pop()
            elif kind=='stale':v['stale_token_rejected']=False
            elif kind=='late':v['late_token_rejected']=False
            elif kind=='duration':v['deadline_elapsed_ns']=100
            elif kind=='api':v['timeout']['api']='python'
            elif kind=='errno':v['timeout']['errno']=5
            elif kind=='success':v['timeout']['operation_success']=True
            elif kind=='missing-time':v['timeout'].pop('deadline_ns')
            else:v['late_denial_physical_obligation']=True
            with self.subTest(kind=kind):self.assertNotEqual(run_exit_code(d),0)


class LifecycleWireEvidence(unittest.TestCase):
    def test_all_original_cases_consume_both_ends_in_either_role(self):
        for phase in(0,1):
            for late in(False,True):
                row,matched,sdus,left=wire_fixture(phase,late);proof,credit=corroborate(row,matched,sdus)
                self.assertFalse(left);self.assertEqual(len(proof),1);self.assertEqual(credit,{phase:5,1-phase:4+int(late)})

    def test_missing_or_modified_originals_never_pass(self):
        for kind in('case','registration','root','positive','prompt','stale','late','epoch','changed-db','cleanup','foreign-cleanup','owner-exit','late-read','payload','missing-peer','deadline','early-error','api','guard','wire'):
            row,matched,sdus,left=wire_fixture();g,ex,e=row['ssap_owner_lifecycle']
            if kind=='case':row['ssap_owner_lifecycle'].pop()
            elif kind=='registration':ex['stdout']=ex['stdout'].replace('SsapOwnedService:','INVALID:')
            elif kind=='root':e['credentials']['uids']=[0]*4
            elif kind=='positive':e['stdout']+='approved=true'
            elif kind=='prompt':e['prompt_events'][1]['fields'][8]='99'
            elif kind=='stale':e['stale_input']['token']=2
            elif kind=='late':e['late_input']['monotonic_ns']=1
            elif kind=='epoch':ex['prompt_events'][0]['fields'][6]='2'
            elif kind=='changed-db':e['value_snapshots'][2]['value']='00'*32
            elif kind=='cleanup':ex['after_owner_exit']['stdout']='SsapLocalServices: [[18,19]]\n'
            elif kind=='foreign-cleanup':ex['after_owner_exit']['args'][2]='/other'
            elif kind=='owner-exit':ex['owner_exit']=0
            elif kind=='late-read':ex['guard_read']['end_wall_ns']=ex['end_wall_ns']+1
            elif kind=='payload':e['value']='00'*32
            elif kind=='missing-peer':left[:]=[p for p in left if p['direction']!='in']
            elif kind=='deadline':e['timed_write']['end_monotonic_ns']+=1_000_000_000
            elif kind=='early-error':e['timed_write']['end_monotonic_ns']=e['timed_write']['start_monotonic_ns']+100
            elif kind=='api':e['timeout_api']='python'
            elif kind=='guard':g['other_owner_after_failed_request']=False
            else:left.pop()
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate(row,matched,sdus)


if __name__=='__main__':unittest.main()
