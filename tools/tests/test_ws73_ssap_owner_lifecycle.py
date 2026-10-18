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
        i['stdout']+=f"SsapAuthorizationPrompt: token={token} request={request} index={t} generation={owners[t]['owner']['generation']} lifetime=11 handle={t+1} epoch=9 security=0 property={i['handle']} write=true bytes=32 deadline_ns={fields[11]}; answer 'yes {token}' or 'no {token}'\n"
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


class LifecycleReceipts(unittest.TestCase):
    def test_finalizer_computes_supervisor_result_before_it_is_published(self):
        d=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
               ssap_owner_lifecycle_requested=True,ssap_owner_lifecycle_acceptance=True,
               ordinary_channel_socket_acceptance=True,channel_socket_corroboration=summary())
        # This is the actual _run finalizer's input state. It writes the
        # supervisor result only after calling this production verdict function.
        self.assertEqual(run_exit_code(d),0)
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
