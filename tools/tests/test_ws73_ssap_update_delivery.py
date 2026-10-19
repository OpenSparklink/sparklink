"""Finite report/control fixtures,not a Host,Native security or RF qualification."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from ws73_capture import CaptureError
import ws73_ssap_update_delivery as gate
from ws73_application_client import application_environment,owned_arguments

def fixture(phase=0):
    owners=[dict(owner=dict(index=i,generation=7,path=f'/org/sparklink/slk{i}_g7'),
        object=dict(lifetime=11+i,handle=2+i,path=f'/org/sparklink/slk{i}_g7/peer_t00_010203040506/link_000000000000000b'))for i in(0,1)]
    row=dict(phase=phase,owners=owners,security_requirement=2,message_security_required=True,
        ssap_update_delivery_required=True,ssap_update_delivery_status=gate.STATUS,ssap_update_delivery=[])
    seq=0
    def random(n):
        nonlocal seq
        seq+=1;return bytes([seq]*n).hex()
    def observation(api,h,**data):
        return dict(start_wall_ns=150,end_wall_ns=151,start_monotonic_ns=1000,end_monotonic_ns=1010,
            receipt=dict(api=api,handle=h,started_ns=1001,returned_ns=1002,deadline_ns=5000001001,**data))
    for s in(0,1):
        t=1-s;peer,server=owners[s],owners[t];api='c'if(phase+s)%2==0 else'python';other='python'if api=='c'else'c'
        item=dict(sender=s,target=t,start=16,end=17,handle=17,policy='allow',publisher_api=api,
            service=random(16),uuid=random(16),secret=random(32),start_wall_ns=1,end_wall_ns=400,
            exit=0,stderr='',credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0')),
            environment=application_environment(),cases=[])
        item['args']=owned_arguments(api,server,item['service'],item['uuid'],item['secret'],'allow',update_connection=server['object']['path'])
        h=17;end=(h+1).to_bytes(2,'little');uuid=bytes.fromhex(item['uuid'])
        q=[b'\x06\x13\x01\0\xff\xff'+uuid,b'\x06\x13'+end+b'\xff\xff'+uuid]
        r=[b'\x07\x0b\x81'+h.to_bytes(2,'little')+uuid+(541).to_bytes(4,'little')+b'\x01\x02',b'\x01\0\x06'+end+b'\x0b']
        item['discovery']=dict(exit=0,stderr='',args=['slctl','--adapter',peer['owner']['path'],'ssap-discover',peer['object']['path'],'property',item['uuid']],
            start_wall_ns=5,end_wall_ns=8,stdout=f'SsapRemoteDiscovery: path={peer["object"]["path"]} kind=3 entries=1 requests={"|".join(v.hex()for v in q)} responses={"|".join(v.hex()for v in r)}\n')
        fq=[b'\x04\x11\x01\0\xff\xff',b'\x04\x11'+end+b'\xff\xff',b'\x04\x13\x10\0\x11\0']
        fr=[b'\x05\x0b\x81\x10\0\x11\0'+bytes.fromhex(item['service'])+b'\x02',b'\x01\0\x04'+end+b'\x0b',
            b'\x05\x0b\x81\x11\0'+uuid+(541).to_bytes(4,'little')+b'\x01\x02']
        item['full_discovery']=dict(exit=0,stderr='',args=['slctl','--adapter',peer['owner']['path'],'ssap-discover',peer['object']['path']],
            start_wall_ns=2,end_wall_ns=4,stdout=f'SsapRemoteDiscovery: path={peer["object"]["path"]} kind=1 entries=2 requests={"|".join(v.hex()for v in fq)} responses={"|".join(v.hex()for v in fr)}\n')
        lines=[f'SdkOwnedAPI: api={api} client_closed=true','SsapOwnedService: start=16 end=17 property=17; local registration only']
        for mode in(1,2):
            value,reply=random(32),random(32);pdu=(bytes([16 if mode==2 else 15,3,17,0,32,0])+bytes.fromhex(value)).hex()
            case=dict(mode=mode,value=value,reply=reply,start_wall_ns=100,end_wall_ns=300,
                replacement=observation(api,h,value=value),before=dict(handle=h,value=value),after=dict(handle=h,value=reply),
                enabled=[observation(api,h,modes=mode)],disabled=[observation(api,h,modes=0)],
                send=observation(api,h,stage=2 if mode==2 else 1,pdu=pdu,ack='110301'if mode==2 else''))
            prefix=['/bin/ws73-application-client-c']if other=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
            case['application']=dict(api=other,args=prefix+['update-peer',str(peer['owner']['index']),'7',peer['object']['path'],'17',str(mode),value,reply],
                exit=0,stderr='',environment=application_environment(),credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0')),
                start_wall_ns=130,end_wall_ns=250,stdout=json.dumps(dict(stage='ssap_update_wait',api=other,handle=h,mode=mode,deadline_ns=10**12,client_closed=True))+'\n'+
                    json.dumps(dict(stage='ssap_update_checked_reply',api=other,handle=h,mode=mode,pdu=pdu,value=value,reply=reply))+'\n')
            item['cases'].append(case)
            lines+=['SdkOwnedReplaced: '+json.dumps(case['replacement']['receipt']),f'SsapOwnedValue: handle=17 value={value}']
            for configured in(mode,0):
                d=dict(api=api,index=server['owner']['index'],generation=7,token=1+len(lines),request_id=1+len(lines),lifetime=server['object']['lifetime'],handle=server['object']['handle'],
                    epoch=41,level=2,deadline_ns=5000000,property=h,data_type=2,write=True,value=bytes([configured,0]).hex(),local_tcid=10,remote_tcid=10,pi=0,
                    allow=True,decision_ns=4000000,decision_wall_ns=200)
                lines.append('SdkAuthorizationDecision: '+json.dumps(d))
            lines+=['SdkOwnedConfiguration: '+json.dumps(case['enabled'][0]['receipt']),
                'SdkOwnedUpdate: '+json.dumps(case['send']['receipt']),'SdkOwnedConfiguration: '+json.dumps(case['disabled'][0]['receipt']),
                f'SsapOwnedValue: handle=17 value={reply}']
        lines.append(f'SdkOwnedRemoved: api={api} start=16');item['stdout']='\n'.join(lines)+'\n';row['ssap_update_delivery'].append(item)
    return row

def matched(owner,direction,payload,window):return dict(data=payload.hex(),direction=direction,controller=owner['owner']['index'])

class UpdateDelivery(unittest.TestCase):
    def test_terminal_contract_requires_numeric_security_success_not_plain_passthrough(self):
        # Explicit report-shape fixtures,not successful Native dependencies.
        from ws73_target import run_exit_code
        rows=[]
        for phase in(0,1):
            rows.append(dict(phase=phase,ssap_update_delivery=gate.corroborate(fixture(phase),matched)[0],
                protected_ssap=dict(required=2,controllers=[{'fixture':0},{'fixture':1}]),
                ssap_values=[{'fixture':'checked-elsewhere'}],ssap_discovery=[{'fixture':'checked-elsewhere'}]))
        record=dict(status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',qemu_exit=0,supervisor_exit=0,
            ssap_update_delivery_requested=True,ssap_update_delivery_acceptance=True,
            ordinary_channel_socket_acceptance=True,live_ssap_security_requirement=2,
            live_security_agent_requested='numeric-approve',qemu_args=['ws73.ssap_update_delivery=1'],
            channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=rows,round_trips=8),
            security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',
                phases=[dict(mode='numeric-approve',ssap_security_requirement=2)for _ in(0,1)],business_round_trips=8))
        self.assertEqual(run_exit_code(record),0)
        for changes in [dict(status='PASSTHROUGH_SUPPORT_PASS'),dict(status='FAIL'),dict(qemu_exit=1),
                dict(supervisor_exit=1),dict(live_ssap_security_requirement=1),
                dict(live_security_agent_requested='approve'),dict(ssap_update_delivery_acceptance=False),
                dict(ordinary_channel_socket_acceptance=False),dict(qemu_args=[]),dict(security_agent_corroboration={})]:
            with self.subTest(changes=changes):self.assertEqual(run_exit_code(record|changes),1)
        record['channel_socket_corroboration']['proofs'][0]['ssap_update_delivery'].pop()
        self.assertEqual(run_exit_code(record),1)

    def test_finite_fixture_replays_both_directions_and_stages(self):
        summaries=[]
        for phase in(0,1):
            proof,credit=gate.corroborate(fixture(phase),matched)
            self.assertEqual([len(p['wire'])for p in proof],[29,29]);self.assertEqual(credit,{0:29,1:29})
            summaries.append(dict(phase=phase,ssap_update_delivery=proof))
        self.assertTrue(gate.valid_summary(dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=summaries)))
        summaries[0]['ssap_update_delivery'][0]['wire'][0]['rx']={}
        self.assertFalse(gate.valid_summary(dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=summaries)))

    def test_missing_or_wrong_delivery_approval_cpcd_role_and_stream_never_pass(self):
        controls=['missing-peer','false-peer-result','wrong-value','wrong-ack','wrong-stage','not-disabled','not-authenticated','foreign-owner','wrong-type','missing-decision','raw-stream-mismatch','bad-discovery','wrong-role','missing-kind','missing-hierarchy','wrong-hierarchy','late-hierarchy']
        for control in controls:
            row=fixture();item=row['ssap_update_delivery'][0];case=item['cases'][0]
            if control=='missing-peer':case['application']['stdout']=''
            elif control=='false-peer-result':case['application']['exit']=1
            elif control=='wrong-value':case['value']='ff'*32
            elif control=='wrong-ack':case['send']['receipt']['ack']='110300'
            elif control=='wrong-stage':case['send']['receipt']['stage']=2
            elif control=='not-disabled':case['disabled'][0]['receipt']['modes']=1
            elif control=='not-authenticated':item['stdout']=item['stdout'].replace('"level": 2','"level": 1')
            elif control=='foreign-owner':item['stdout']=item['stdout'].replace('"lifetime": 12','"lifetime": 13')
            elif control=='wrong-type':item['stdout']=item['stdout'].replace('"data_type": 2','"data_type": 0')
            elif control=='missing-decision':item['stdout']='\n'.join(l for l in item['stdout'].splitlines()if not l.startswith('SdkAuthorizationDecision:'))+'\n'
            elif control=='raw-stream-mismatch':item['stdout']=item['stdout'].replace('SsapOwnedValue:','LostValue:')
            elif control=='bad-discovery':item['discovery']['stdout']=''
            elif control=='wrong-role':case['application']['credentials']['uids']=[0]*4
            elif control=='missing-hierarchy':item.pop('full_discovery')
            elif control=='wrong-hierarchy':item['full_discovery']['stdout']=item['full_discovery']['stdout'].replace('kind=1','kind=3')
            elif control=='late-hierarchy':item['full_discovery']['end_wall_ns']=9
            else:item['cases'].pop()
            with self.subTest(control=control),self.assertRaises((CaptureError,KeyError,ValueError)):gate.corroborate(row,matched)

    def test_one_sided_update_capture_is_not_business_delivery(self):
        def missing(owner,direction,payload,window):
            if direction=='in'and payload[4:5]in[b'\x0f',b'\x10']:raise CaptureError('explicit missing RX fixture')
            return matched(owner,direction,payload,window)
        with self.assertRaisesRegex(CaptureError,'missing RX'):gate.corroborate(fixture(),missing)

    def test_explicit_protected_gate_only_no_implicit_selection(self):
        args=SimpleNamespace(ssap_update_delivery_verify=True,channel_socket_verify=True,security_agent='numeric-approve')
        self.assertTrue(gate.requested(args,passthrough=True))
        for changed in ['security_agent','channel_socket_verify','ssap_owned_verify']:
            bad=copy.copy(args);setattr(bad,changed,'approve'if changed=='security_agent'else False if changed=='channel_socket_verify'else True)
            with self.assertRaises(ValueError):gate.requested(bad,passthrough=True)
        with self.assertRaises(ValueError):gate.requested(args,passthrough=False)

    def test_summary_rejects_malformed_types_and_incomplete_or_forged_counts(self):
        proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=[
            dict(phase=p,ssap_update_delivery=gate.corroborate(fixture(p),matched)[0])for p in(0,1)])
        self.assertTrue(gate.valid_summary(proof))
        for key in ['sender','target','updates','application_replies','decisions']:
            for bad in [True,False,1.0,2.0,'2',None]:
                changed=copy.deepcopy(proof);changed['proofs'][0]['ssap_update_delivery'][0][key]=bad
                with self.subTest(key=key,bad=bad):self.assertFalse(gate.valid_summary(changed))
        for bad in [None,[],{'proofs':None},{'status':'ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED','proofs':[None,None]}]:
            self.assertFalse(gate.valid_summary(bad))
        for bad in [None,True,'capture',{},dict(tx={'data':'01'},rx=[]),dict(tx={},rx={'data':'01'})]:
            changed=copy.deepcopy(proof);changed['proofs'][0]['ssap_update_delivery'][0]['wire'][0]=bad
            self.assertFalse(gate.valid_summary(changed))

    def test_executed_tools_must_match_both_sealed_files_and_manifest(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);manifest=[]
            for name in gate.TOOLS:
                path=root/name.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
                manifest.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            records=gate.tool_records(root)
            gate.validate_tools(records,root,manifest)
            for bad in [manifest[:-1],manifest+[manifest[0]],list(reversed(manifest[:-1]))]:
                with self.assertRaises(CaptureError):gate.validate_tools(records,root,bad)
            changed=copy.deepcopy(manifest);changed[0]['sha256']='0'*64
            with self.assertRaises(CaptureError):gate.validate_tools(records,root,changed)
            (root/gate.TOOLS[0].lstrip('/')).write_bytes(b'old or substituted binary')
            with self.assertRaises(CaptureError):gate.validate_tools(records,root,manifest)
