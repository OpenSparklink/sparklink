# SPDX-License-Identifier: GPL-2.0-only
"""Independent golden receipts/PDUs; fixtures are not native kernel or RF tests."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_ssap_requester_lifecycle import STATUS,corroborate,killed_receipt,valid_summary,read_reply
from ws73_application_client import application_environment
from ws73_target import _run,run_exit_code


def fixture(phase=0):
    N=1_000_000_000;W=1_800_000_000_000_000_000
    wall=lambda n:W+int(n*N)
    owners=[dict(owner=dict(index=n,generation=n+11,path=f'/a{n}',bus=1,device=n+2),
        object=dict(lifetime=9,handle=n+1,path=f'/a{n}/connection'))for n in (0,1)]
    s,t=phase,1-phase;api='c'if s==0 else'python'
    row=dict(phase=phase,owners=owners,rounds=4,ssap_receipts=[{'args':['/bin/slctl']}],
        ssap_requester_lifecycle_required=True,ssap_requester_lifecycle_status=STATUS)
    def item(case,policy,h):
        data=lambda name:hashlib.sha256((case+name).encode()).hexdigest()
        i=dict(case=case,sender=s,target=t,policy=policy,handle=h,start=h-1,end=h,
            secret=data('secret'),value=data('value'),uuid=data('uuid')[:32],service=data('service')[:32],
            credentials={'uids':[1000]*4,'capabilities':{'CapEff':'0','CapPrm':'0','CapAmb':'0'}},
            exit=-9,stderr='',start_wall_ns=wall(.1),end_wall_ns=wall(3))
        i['args']=['/bin/slctl','--adapter',owners[t]['owner']['path'],'ssap-serve',i['service'],i['uuid'],'5','36',i['secret'],policy]
        i['stdout']=f'SsapOwnedService: start={h-1} end={h} property={h}; local registration only\n'
        return i
    g=item('guard','allow',17);i=item('requester-exit','ask',19);i['api']=api
    row['ssap_requester_lifecycle']=[g,i]
    def command(start,end):return dict(start_wall_ns=wall(start),end_wall_ns=wall(end))
    prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    call=dict(stage='ssap_call',api=api,call_ns=int(1.1*N),deadline_ns=6*N,client_closed=True)
    c=dict(args=prefix+['ssap-error',str(s),str(s+11),owners[s]['object']['path'],'ssap-write','19','110',i['value']],
        environment=application_environment(),exit=-9,stderr='',stdout=json.dumps(call)+'\n',
        credentials={'uids':[1000]*4,'capabilities':{k:'0'for k in ['CapEff','CapPrm','CapAmb','CapInh']}},
        start_monotonic_ns=N,end_monotonic_ns=int(2.6*N),**command(1,2.6))
    i.update(killed_write=c,call_receipt=call,requester_exit=-9,requester_exit_wall_ns=wall(1.3),
        requester_exit_monotonic_ns=int(1.3*N),business_window=dict(start_wall_ns=wall(1.6),end_wall_ns=wall(2),start_monotonic_ns=int(1.6*N),end_monotonic_ns=2*N),
        approval=dict(token=1,wall_ns=wall(2.1),monotonic_ns=int(2.1*N)))
    fields=['1','7',str(t),str(t+11),'9',str(t+1),'4','0','19','true','32',str(int(6.2*N)),'1','1']
    i['prompt_events']=[dict(fields=fields,wall_ns=wall(1.2),monotonic_ns=int(1.2*N))]
    i['stdout']+=f"SsapAuthorizationPrompt: token=1 request=7 index={t} generation={t+11} lifetime=9 handle={t+1} epoch=4 security=0 property=19 write=true bytes=32 deadline_ns={int(6.2*N)}; answer 'yes 1' or 'no 1'\n"
    i['stdout']+='SsapAuthorizationDecision: request=7 property=19 write=true security=0 approved=true; local policy only\n'
    args=['/bin/slctl','--adapter',owners[s]['owner']['path'],'ssap-read',owners[s]['object']['path'],'17','0']
    i['busy_read']=dict(args=args,exit=1,stdout='',stderr='SSAP busy/not-ready/expired',**command(1.4,1.5))
    i['next_read_attempts']=[dict(args=args,exit=0,stderr='',stdout=f'Selected {owners[s]["owner"]["path"]}\nSsapPeerValue: operation=ssap-read path={owners[s]["object"]["path"]} handle=17 value={g["secret"]}\n',**command(2.2,2.4))]
    row['applications']=[dict(exit=0,**command(1.61,1.9)),dict(exit=0,**command(1.62,1.91))]
    def snapshot(item,n,at,value):
        item.setdefault('value_snapshots',[]).append(dict(ordinal=n,handle=item['handle'],value=value,**command(at,at+.01)))
        item['stdout']+=f'SsapOwnedValue: handle={item["handle"]} value={value}\n'
    snapshot(i,1,1.55,i['secret']);snapshot(i,2,2.5,i['value']);snapshot(g,1,2.52,g['secret'])
    sdus=[]
    def packet(a,b,pdu,at):
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        for k,d,delta in [(a,'out',0),(b,'in',.001)]:
            sdus.append(dict(bus=1,device=k+2,handle=k+1,direction=d,data=frame.hex(),wall_ns=wall(at+delta)))
    # Independent expected bytes: verified write, original written value,
    # new read of another owner, and its independently validated reply.
    packet(s,t,b'\x0d\x23\x13\0\0'+bytes.fromhex(i['value']),1.15)
    packet(t,s,b'\x0e\x03\x13\0\0'+bytes.fromhex(i['value']),2.12)
    packet(s,t,b'\x08\x03\x11\0\0',2.22)
    packet(t,s,b'\x09\x03'+bytes.fromhex(g['secret']),2.25)
    return row,sdus


def check(row,sdus):
    left=copy.deepcopy(sdus)
    def matched(owner,direction,raw,window):
        matches=[p for p in left if p['device']==owner['owner']['device']and p['direction']==direction
            and p['data']==raw.hex()and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(matches)!=1:raise CaptureError('one exact independently supplied wire leg required')
        left.remove(matches[0]);return matches[0]
    result,credit=corroborate(row,matched,left)
    if left:raise CaptureError('unattributed golden packets')
    return result,credit


class RequesterLifecycle(unittest.TestCase):
    def test_actual_cli_selection_line_is_required_and_cannot_hide_wrong_identity_or_payload(self):
        row,_=fixture();g,i=row['ssap_requester_lifecycle'];source=row['owners'][0];c=i['next_read_attempts'][-1]
        read_reply(c,source,g,'/bin/slctl')
        for output in [c['stdout'].split('\n',1)[1],c['stdout'].replace('Selected /a0','Selected /other'),
                       c['stdout'].replace(g['secret'],'00'*32),c['stdout']+'extra\n',c['stdout']+c['stdout']]:
            wrong=dict(c,stdout=output)
            with self.assertRaises(CaptureError):read_reply(wrong,source,g,'/bin/slctl')

    def test_both_roles_use_actual_validator_with_independent_wire_bytes(self):
        phases=[]
        for phase in (0,1):
            row,sdus=fixture(phase);proof,credit=check(row,sdus)
            self.assertEqual(credit,{0:2,1:2});self.assertEqual(proof[0]['api'],'c'if phase==0 else'python')
            phases.append(dict(phase=phase,ssap_requester_lifecycle=proof))
        summary=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=phases)
        self.assertTrue(valid_summary(summary))
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,ssap_requester_lifecycle_requested=True,
            ssap_requester_lifecycle_acceptance=True,ordinary_channel_socket_acceptance=True,channel_socket_corroboration=summary)
        self.assertEqual(run_exit_code(record),0)
        for mutate in [lambda d:d.update(ssap_requester_lifecycle_requested=False),lambda d:d.update(ssap_requester_lifecycle_acceptance=False),
                       lambda d:d.update(supervisor_exit=1),lambda d:d.update(ssap_owner_lifecycle_requested=True),
                       lambda d:d['channel_socket_corroboration'].update(round_trips=9),lambda d:d['channel_socket_corroboration']['proofs'].pop()]:
            wrong=copy.deepcopy(record);mutate(wrong);self.assertEqual(run_exit_code(wrong),1)

    def test_requester_died_before_policy_release_and_no_terminal_success_can_be_forged(self):
        for phase in (0,1):
            row,_=fixture(phase);item=row['ssap_requester_lifecycle'][1];c=item['killed_write']
            self.assertEqual(killed_receipt(c,item['api'],row['owners'][phase],item),item['call_receipt'])
            for mutate in [lambda d:d.update(exit=0),lambda d:d.update(stdout=d['stdout']+'{}\n'),
                           lambda d:d['environment'].update(LIBSPARKLINK_PATH='/old/lib.so'),
                           lambda d:d['credentials'].update(uids=[0]*4),lambda d:d.update(stderr='lost output'),
                           lambda d:d['args'].__setitem__(-1,'00')]:
                wrong=copy.deepcopy(c);mutate(wrong)
                with self.assertRaises(CaptureError):killed_receipt(wrong,item['api'],row['owners'][phase],item)

    def test_temporal_identity_and_value_negative_controls(self):
        row,sdus=fixture()
        def item(d):return d['ssap_requester_lifecycle'][1]
        mutations=[lambda d:d['ssap_requester_lifecycle'].pop(),lambda d:item(d).update(requester_exit=0),
            lambda d:item(d)['approval'].update(token=2),lambda d:item(d)['approval'].update(monotonic_ns=6_100_000_000),
            lambda d:item(d)['prompt_events'][0]['fields'].__setitem__(4,'10'),
            lambda d:item(d)['busy_read'].update(exit=0),lambda d:item(d)['busy_read']['args'].__setitem__(4,'/old-lifetime'),
            lambda d:item(d)['value_snapshots'][0].update(value=item(d)['value']),
            lambda d:item(d)['value_snapshots'][1].update(value=item(d)['secret']),
            lambda d:item(d)['business_window'].update(end_monotonic_ns=7_000_000_000),
            lambda d:d['applications'].pop(),lambda d:d['applications'][0].update(end_wall_ns=1_800_000_003_000_000_000),
            lambda d:item(d)['next_read_attempts'][-1].update(stdout='fake success'),
            lambda d:item(d).update(stdout=item(d)['stdout'].replace('approved=true','approved=false'))]
        for n,mutate in enumerate(mutations):
            wrong=copy.deepcopy(row);mutate(wrong)
            with self.subTest(n=n),self.assertRaises((CaptureError,KeyError)):check(wrong,sdus)

    def test_missing_duplicate_corrupt_early_reply_and_busy_wire_are_rejected(self):
        row,sdus=fixture()
        cases=[sdus[:-1],sdus+[copy.deepcopy(sdus[-1])]]
        wrong=copy.deepcopy(sdus);wrong[2]['wall_ns']-=1_000_000_000;cases.append(wrong)
        wrong=copy.deepcopy(sdus);wrong[3]['data']=wrong[3]['data'][:-2]+'ff';cases.append(wrong)
        wrong=copy.deepcopy(sdus)
        for p in wrong:
            if p['data'].startswith('0a0005000803'):p['wall_ns']=1_800_000_001_450_000_000
        cases.append(wrong)
        for wrong in cases:
            with self.assertRaises(CaptureError):check(row,wrong)

    def test_requester_gate_refuses_other_modes_before_any_artifact_or_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra in [{},{'qmp_hotplug':True},{'qmp_hotplug':True,'channel_socket_verify':True,'ssap_owner_lifecycle_verify':True}]:
                args=SimpleNamespace(command='run',output=Path(tmp)/'unused',ssap_requester_lifecycle_verify=True,**extra)
                with self.assertRaisesRegex(ValueError,'requester lifecycle requires separate'):_run(args)
                self.assertFalse(args.output.exists())


if __name__=='__main__':unittest.main()
