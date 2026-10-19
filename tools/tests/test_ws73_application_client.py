# SPDX-License-Identifier: GPL-2.0-only
"""Verifier fixtures only, no controller/device or qualification produced."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_application_client import corroborate, valid_summary, application_environment
from ws73_capture import CaptureError
from ws73_target import run_exit_code
import ws73_target as target
import test_ws73_ssap_value as value_cases


def sdk_ssap_fixture(row,sdus):
    """Adapt existing explicit SSAP golden fixture to SDK process receipts.

    No successful verifier stub: the production capture and SSAP corroborators
    consume every actual-format request/reply and both endpoint fixture records.
    """
    n=row['phase'];base,_,wire=value_cases.ActualValueEvidence().uuid_fixture(n)
    owners=row['owners']
    for i,item in enumerate(base['ssap_local_registrations']):item['owner']=owners[i]
    row.update({k:v for k,v in base.items() if k!='owners'})
    row['ssap_language_required']=True;row['ssap_language_clients']=[]
    row.update(ssap_registration_kind='owned-sdk-requests-v1',ssap_owned_publishers_required=True,ssap_owned_publishers=[])
    for position,registered in enumerate(row['ssap_local_registrations']):
        registered['service_uuid']=(bytes([160+n,position+1])*8).hex()
        api='c' if position==n else 'python';owner=owners[position];handle=registered['handle'];begin=registered['start']
        app=dict(api=api,position=position,pid=200+position,credentials=dict(uids=[1005]*4,gids=[1005]*4,groups=[],capabilities={k:'0' for k in ['CapEff','CapPrm','CapAmb','CapInh']}),environment=application_environment(),start_wall_ns=n*10000+900,end_wall_ns=n*10000+2000,exit=0,stderr='',value_snapshots=[])
        app['args']=(['/bin/ws73-application-client-c'] if api=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py'])+['owned',str(owner['owner']['index']),str(owner['owner']['generation']),registered['service_uuid'],registered['property_uuid'],'ab'*32,'allow']
        app['stdout']=f'SdkOwnedAPI: api={api} client_closed=true\nSsapOwnedService: start={begin} end={handle} property={handle}; local registration only\n'
        registered['registration']=app;row['ssap_owned_publishers'].append(app)
    normal_count=8*12
    for i,item in enumerate(row['ssap_values']):
        start=n*10000+1000+i*100;item.update(start_wall_ns=start,end_wall_ns=start+60)
        for name,offset in [('uuid_read_before',1),('read_before',10),('write',20),('read_after',30),('uuid_read_after',40)]:
            item[name].update(start_wall_ns=start+offset,end_wall_ns=start+offset+5)
        for name,key,operation in [('read_before','before','ssap-read'),('write','value','ssap-write'),('read_after','value','ssap-read')]:
            position=item['sender'];entry=owners[position];api='c'if position==n else 'python';app=item[name]
            arguments=(['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py'])+['ssap',str(entry['owner']['index']),str(entry['owner']['generation']),entry['object']['path'],operation,str(item['handle']),item[key]]
            if operation=='ssap-write':arguments.append(item['value'])
            barrier=json.dumps(dict(stage='ssap_start_barrier',api=api,client_closed=True))
            app.update(position=position,api=api,args=arguments,environment=application_environment(),ssap_operation=operation,ssap_path=entry['object']['path'],ssap_handle=item['handle'],ssap_expected=item[key],stdout=barrier+'\n'+app['stdout'],stderr='',credentials=dict(uids=[1000]*4,capabilities={k:'0'for k in ['CapEff','CapPrm','CapAmb','CapInh']}))
            row['ssap_language_clients'].append(app)
        publisher=row['ssap_owned_publishers'][item['target']];ordinal=len(publisher['value_snapshots'])+1
        observation=dict(api=publisher['api'],publisher_pid=publisher['pid'],handle=item['handle'],value=item['value'],ordinal=ordinal,start_wall_ns=start+26,end_wall_ns=start+28)
        item['local_check']=observation;publisher['value_snapshots'].append(observation)
        for j,name in enumerate(['uuid_read_before','read_before','write','read_after','uuid_read_after']):
            obj=row['owners'][item['target']]['object'];owner=row['owners'][item['target']]['owner']
            token=(ordinal-1)*5+j+1
            decision=dict(api=publisher['api'],index=owner['index'],generation=owner['generation'],
                token=token,request_id=token+10,lifetime=obj['lifetime'],handle=obj['handle'],
                epoch=1,level=0,deadline_ns=10_000_000_000,property=item['handle'],data_type=0,write=name=='write',
                value=item['value'] if name=='write' else '',local_tcid=10,remote_tcid=10,pi=0,
                allow=True,decision_ns=9_000_000_000+token,decision_wall_ns=item[name]['start_wall_ns']+2)
            publisher['stdout']+='SdkAuthorizationDecision: '+json.dumps(decision)+'\n'
            if name=='write':publisher['stdout']+=f"SsapOwnedValue: handle={item['handle']} value={item['value']}\n"
        normal=wire[i*12:(i+1)*12];uuid=wire[normal_count+i*8:normal_count+(i+1)*8]
        for part,offset in [(normal[:4],10),(normal[4:8],20),(normal[8:12],30),(uuid[:4],1),(uuid[4:8],40)]:
            for position,direction,payload,_ in part:
                entry=owners[position];owner,obj=entry['owner'],entry['object']
                sdus.append(dict(bus=owner['bus'],device=owner['device'],handle=obj['handle'],direction=direction,data=payload.hex(),wall_ns=start+offset+1))
    for publisher in row['ssap_owned_publishers']:
        publisher['stdout']+=f"SdkOwnedRemoved: api={publisher['api']} start={publisher['start'] if 'start' in publisher else row['ssap_local_registrations'][publisher['position']]['start']}\n"



def fixture():
    rows=[];sdus=[]
    for n in range(2):
        owners=[dict(owner=dict(index=i,generation=10+i,bus=1,device=2+i,path=f'/adapter{i}'),object=dict(generation=10+i,lifetime=n+1,handle=i+3,path=f'/adapter{i}/link')) for i in range(2)]
        request=n.to_bytes(4,'little')+bytes([10+n])*57;reply=n.to_bytes(4,'little')+bytes([20+n])*57
        apps=[]
        for i in [0,1]:
            api=(['c','python'] if n==0 else ['python','c'])[i];owner,obj=owners[i]['owner'],owners[i]['object']
            ready=dict(stage='ready',api=api,index=i,generation=owner['generation'],lifetime=obj['lifetime'],handle=obj['handle'],dup_alive=True,client_closed=True)
            sent,received=(reply,request) if i else (request,reply)
            complete=dict(stage='complete',api=api,sent=sent.hex(),received=received.hex(),last_close_rebind='NotSupported')
            apps.append(dict(position=i,api=api,environment=application_environment(),stdout=json.dumps(ready)+'\n'+json.dumps(complete)+'\n',stderr='',exit=0,credentials=dict(uids=[1004]*4,gids=[1004]*4,groups=[],capabilities={k:'0' for k in ['CapEff','CapPrm','CapAmb','CapInh']})))
        row=dict(phase=n,owners=owners,request=request.hex(),reply=reply.hex(),applications=apps,start_wall_ns=100+n*10000,end_wall_ns=9999+n*10000,status='APPLICATION_CLIENT_EVIDENCE_PENDING')
        from ws73_application_role import DENIALS
        lines=['AUTH_CREDENTIALS: uid=1004 gid=1004 caps=0','AUTH_CHANNEL_KERNEL_ACCESS: denied','AUTH_DENIED: own-service']
        for destination in ['named','unique']:
            lines+=['AUTH_CHANNEL_IDENTITY: '+destination]+['AUTH_DENIED: '+m for m in DENIALS]
        lines+=['AUTH_CHANNEL_ROLE: sparklink-apps-only']
        row.update(channel_role='sparklink-apps-only',role_probe=dict(args=['/bin/bus-policy-probe',owners[0]['object']['path'],'application-channel'],credentials=copy.deepcopy(apps[0]['credentials']),exit=0,stderr='',stdout='\n'.join(lines)+'\n',start_wall_ns=110+n*10000,end_wall_ns=120+n*10000))
        rows.append(row)
        for source,target,payload in [(0,1,request),(1,0,reply)]:
            frame=(b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload).hex()
            for i,direction in [(source,'out'),(target,'in')]:
                sdus.append(dict(bus=1,device=2+i,handle=3+i,direction=direction,data=frame,wall_ns=150+n*10000))
        sdk_ssap_fixture(row,sdus)
    return dict(application_clients=rows),sdus


class ApplicationClientEvidence(unittest.TestCase):
    def test_policy_decisions_must_match_original_lifetime_proposal_and_window(self):
        cases=['missing','duplicate','deny','lifetime','generation','index-bool','handle','epoch',
               'property','data-type','untyped','late','wrong-value','write','wall','token','request','unknown','malformed','old-mode']
        for case in cases:
            run,sdus=fixture();row=run['application_clients'][0];app=row['ssap_owned_publishers'][0]
            lines=app['stdout'].splitlines();positions=[i for i,line in enumerate(lines) if line.startswith('SdkAuthorizationDecision: ')]
            at=positions[2];data=json.loads(lines[at].removeprefix('SdkAuthorizationDecision: '))
            if case=='missing':lines.pop(at)
            elif case=='duplicate':lines.insert(at,lines[at])
            elif case=='deny':data['allow']=False
            elif case=='lifetime':data['lifetime']+=1
            elif case=='generation':data['generation']+=1
            elif case=='index-bool':data['index']=False
            elif case=='handle':data['handle']+=1
            elif case=='epoch':data['epoch']=0
            elif case=='property':data['property']+=1
            elif case=='data-type':data['data_type']=2
            elif case=='untyped':data.pop('data_type')
            elif case=='late':data['decision_ns']=data['deadline_ns']
            elif case=='wrong-value':data['value']='00'*32
            elif case=='write':data['write']=False
            elif case=='wall':data['decision_wall_ns']=1
            elif case=='token':data['token']=1
            elif case=='request':data['request_id']=1
            elif case=='unknown':data['extra']='ignored'
            elif case=='old-mode':row['ssap_registration_kind']='owned-sdk-v1'
            if case not in ['missing','duplicate']:
                lines[at]='SdkAuthorizationDecision: '+('{' if case=='malformed' else json.dumps(data))
            app['stdout']='\n'.join(lines)+'\n'
            with self.subTest(case=case),patch('ws73_application_client.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):corroborate(run,{})

    def test_owned_publishers_cannot_be_replaced_by_manager_or_fake_cleanup(self):
        for kind in ['manager','missing','role','caps','failed','parent-open','missing-remove','snapshot','wrong-api','unknown-cleanup']:
            run,sdus=fixture();row=run['application_clients'][0];app=row['ssap_owned_publishers'][0]
            if kind=='manager':row['ssap_registration_kind']='manager'
            elif kind=='missing':row['ssap_owned_publishers'].pop()
            elif kind=='role':app['credentials']['uids']=[1000]*4
            elif kind=='caps':app['credentials']['capabilities']['CapEff']='1'
            elif kind=='failed':app['exit']=1
            elif kind=='parent-open':app['stdout']=app['stdout'].replace('client_closed=true','client_closed=false')
            elif kind=='missing-remove':app['stdout']=app['stdout'].replace('SdkOwnedRemoved:','Missing:')
            elif kind=='snapshot':app['value_snapshots'][0]['value']='00'*32
            elif kind=='wrong-api':app['api']='python'
            elif kind=='unknown-cleanup':row['owned_publisher_cleanup_errors']=['timeout']
            with self.subTest(kind=kind),patch('ws73_application_client.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):corroborate(run,{})

    def test_private_image_has_explicit_sdk_path_without_host_native_fallback(self):
        env=application_environment(Path('/private-image'))
        self.assertEqual(env['PYTHONPATH'],'/private-image/usr/share/sparklink/python:/private-image/usr/share/sparklink/tools')
        self.assertEqual(env['LIBSPARKLINK_PATH'],'/private-image/usr/lib/libsparklink.so.0')
        self.assertNotIn('LIBSLK_NATIVE_PATH',env)

    def test_actual_runner_preflight_reaches_verified_profile_before_guest_or_usb(self):
        # Only external identity, prepared-package verification and host inventory
        # are fixtures. Execute the real CLI parser/preflight/final verdict.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=root/'prepared';prepared.mkdir();(prepared/'manifest.json').write_text('{}')
            output=root/'run'
            argv=['ws73_target.py','run','--prepared',str(prepared),'--output',str(output),'--ports','1-1.1.1','1-1.1.2','--firmware-evidence','runtime-observation','--qmp-hotplug','--connection-verify','--connection-advertising','negotiable-t','--application-client-verify']
            with patch.object(sys,'argv',argv),patch('ws73_target.run',target._run),patch('ws73_target.ordinary_identity'),patch('ws73_target.prepared',return_value={}),patch('ws73_target.lab_module',return_value=SimpleNamespace(inventory=lambda:[])),patch('ws73_target.subprocess.Popen') as guest:
                self.assertEqual(target.main(),1)
                guest.assert_not_called()
            result=json.loads((output/'manifest.json').read_text())
            self.assertEqual(result['error'],'application clients require the verified native VM profile')
            self.assertEqual(result['status'],'FAIL')

    def test_explicit_fixture_positive_and_full_terminal_shape(self):
        run,sdus=fixture()
        with patch('ws73_application_client.reassemble_acb',return_value=sdus):proof=corroborate(run,{})
        self.assertTrue(valid_summary(proof))
        supervision=dict(status='ACTUAL_GUEST_APPS_ONLY_PAIRS_AND_POLICY_OUTPUTS_CHECKED',uid=1004,gid=1004,extra_groups=[],role_probes=2,application_processes=4,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2))
        record=dict(supervisor_exit=0,application_role_supervision=supervision,application_client_verification_requested=True,application_client_acceptance=True,application_client_corroboration=proof,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0)
        self.assertEqual(run_exit_code(record),0)
        for key in ['application_client_verification_requested','application_client_acceptance','application_client_corroboration','application_role_supervision']:
            bad=copy.deepcopy(record);bad.pop(key)
            with self.subTest(key=key):self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(record);bad['application_client_corroboration']['proofs'][0]['legs'].pop();self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(record);bad['qemu_exit']=1;self.assertEqual(run_exit_code(bad),1)
        bad=copy.deepcopy(record);bad['application_client_corroboration'].pop('ssap');self.assertEqual(run_exit_code(bad),1)

    def test_missing_changed_duplicate_and_wrong_lifetime_rejected(self):
        def mutate(name,run,sdus):
            if name=='missing-peer':sdus.pop(3)
            elif name=='changed-payload':sdus[0]['data']='00'
            elif name=='duplicate-capture':sdus.append(sdus[0])
            elif name=='stale-handle':sdus[0]['handle']=99
            elif name=='truncated-app':run['application_clients'][0]['applications'][0]['stdout']='{}\n'
            elif name=='wrong-lifetime':
                app=run['application_clients'][0]['applications'][0];parts=app['stdout'].splitlines();ready=json.loads(parts[0]);ready['lifetime']=99;app['stdout']=json.dumps(ready)+'\n'+parts[1]+'\n'
            elif name=='root':run['application_clients'][0]['applications'][0]['credentials']['uids']=[0]*4
            elif name=='inherited-cap':run['application_clients'][0]['applications'][0]['credentials']['capabilities']['CapInh']='1'
            elif name=='diagnostic':run['application_clients'][0]['applications'][0]['stderr']='unexpected warning'
            elif name=='missing-phase':run['application_clients'].pop()
            elif name=='failure':run['application_clients'][0]['applications'][0]['exit']=1
            elif name=='echo':run['application_clients'][0]['reply']=run['application_clients'][0]['request']
        for name in ['missing-peer','changed-payload','duplicate-capture','stale-handle','truncated-app','wrong-lifetime','root','inherited-cap','diagnostic','missing-phase','failure','echo']:
            run,sdus=fixture();mutate(name,run,sdus)
            with self.subTest(name=name),patch('ws73_application_client.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):corroborate(run,{})

    def test_ssap_clients_wire_and_original_result_are_mandatory(self):
        for case in ['missing-required','missing-call','wrong-api','wrong-output','wrong-args','root','late-window','missing-wire']:
            run,sdus=fixture();row=run['application_clients'][0];app=row['ssap_values'][0]['read_before']
            if case=='missing-required':row.pop('ssap_language_required')
            elif case=='missing-call':row['ssap_language_clients'].pop()
            elif case=='wrong-api':app['api']='python'
            elif case=='wrong-output':app['stdout']=app['stdout'].replace(app['ssap_expected'],'00'*32)
            elif case=='wrong-args':app['args'][0]='/bin/slctl'
            elif case=='root':app['credentials']['uids']=[0]*4
            elif case=='late-window':app['start_wall_ns']=app['end_wall_ns']+1
            elif case=='missing-wire':sdus.pop(4)
            with self.subTest(case=case),patch('ws73_application_client.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):corroborate(run,{})

    def test_role_evidence_cannot_be_replaced_by_management_or_partial_success(self):
        from ws73_application_role import verify_probe
        for kind in ['missing','manager','group','cap','denial','raw','path','exit','stderr','interval']:
            run,_=fixture();row=run['application_clients'][0];probe=row['role_probe']
            if kind=='missing':row.pop('role_probe')
            elif kind=='manager':probe['credentials']['uids']=[1000]*4
            elif kind=='group':probe['credentials']['groups']=[1000]
            elif kind=='cap':probe['credentials']['capabilities']['CapInh']='1'
            elif kind=='denial':probe['stdout']=probe['stdout'].replace('AUTH_DENIED: ReadSsapValue\n','')
            elif kind=='raw':probe['stdout']=probe['stdout'].replace('KERNEL_ACCESS: denied','KERNEL_ACCESS: allowed')
            elif kind=='path':probe['args'][1]='/old/lifetime'
            elif kind=='exit':probe['exit']=1
            elif kind=='stderr':probe['stderr']='warning'
            elif kind=='interval':probe['end_wall_ns']=1
            with self.subTest(kind=kind),self.assertRaises(CaptureError):verify_probe(row)
