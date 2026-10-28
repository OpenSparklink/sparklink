# SPDX-License-Identifier: GPL-2.0-only
"""Finite independent SDK JSON/USB fixtures, not daemon or hardware qualification.

Actual old CLI verifier, SDK receipt parsers and ACB reassembler are exercised;
no success stub replaces a validator. Global Owned/CUTC verification remains in
the existing channel runner and is not claimed by this isolated fixture.
"""
import copy
import errno
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ws73_application_client import application_environment, owned_arguments
from ws73_capture import CaptureError, reassemble_acb
from ws73_ssap_owned import OUTPUT_MAXIMUM
from ws73_ssap_update_delivery import TOOLS
from test_ws73_ssap_read_provider import fixture_v2
from test_ws73_ssap_provider_owner_exit import swap_fixture_hardware
import ws73_ssap_read_provider as old
import ws73_ssap_sdk_read_provider as gate


def matcher(packets):
    def match(owner, direction, frame, window):
        key=(owner['owner']['bus'],owner['owner']['device'],owner['object']['handle'],direction,frame.hex())
        found=[p for p in packets if tuple(p[k] for k in ('bus','device','handle','direction','data'))==key
               and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1: raise CaptureError('one exact independent SDK fixture leg required')
        packets.remove(found[0]); return found[0]
    return match


def transcript(item):
    api=item['publisher_api'];h=item['handle']
    lines=[f'SdkOwnedAPI: api={api} client_closed=true',
           f'SsapOwnedService: start={item["start"]} end={item["end"]} property={h}; local registration only',
           'SdkReadProviderBound: '+json.dumps(item['bound'])]
    for step in item['steps']:
        lines.extend(prefix+': '+json.dumps(value) for prefix,value in (
            ('SdkAuthorizationDecision',step['approval']),
            ('SdkReadProviderRequest',step['callback']['prompt']),('SdkReadProviderReply',step['reply'])))
    lines.append(f'SdkOwnedRemoved: api={api} start={item["start"]}')
    item['stdout']='\n'.join(lines)+'\n'
    item['captured_bytes']=dict(stdout=len(item['stdout'].encode()),stderr=0)


def fixture(phase=0):
    row,_,old_packets=fixture_v2(phase)
    if phase==1:
        row=swap_fixture_hardware(row);old_packets=swap_fixture_hardware(old_packets)
    source,target=row['owners'];api=('c','python')[phase];peer_api=('python','c')[phase]
    for n,app in enumerate(s['read'] for c in row['ssap_read_provider_cases'] for s in c['steps']):
        app['pid']=1000+phase*100+n
    row['ssap_language_clients']=[s['read'] for c in row['ssap_read_provider_cases'] for s in c['steps']]
    row.update({gate.PREFIX+'_required':True,gate.PREFIX+'_version':1,gate.PREFIX+'_status':gate.PENDING,
                gate.PREFIX+'_tools':{p:dict(sha256=hashlib.sha256(p.encode()).hexdigest(),bytes=100)
                                      for p in list(TOOLS)+list(gate.EXTRA_TOOLS)}})
    base=1_000_000_000_000*(phase+1);stamp=lambda n:base+n*1_000_000
    seed=lambda name:hashlib.sha256(f'sdk/{phase}/{name}'.encode()).hexdigest()
    creds=dict(uids=[1000]*4,capabilities={k:'0' for k in ('CapEff','CapPrm','CapAmb','CapInh')})
    h=33;path=source['object']['path']
    item=dict(sender=0,target=1,publisher_api=api,sdk_read_provider_contract_version=1,operations=1,policy='allow',
        pid=2000+phase,start=32,end=h,handle=h,bytes=32,secret=seed('secret'),dynamic_value=seed('dynamic'),
        service=seed('service')[:32],uuid=seed('property')[:32],environment=application_environment(),
        credentials=creds,exit=0,stderr='',start_wall_ns=stamp(1),prepared_wall_ns=stamp(2),
        bind_before_wall_ns=stamp(3),bind_before_monotonic_ns=stamp(3),bound_wall_ns=stamp(6),steps=[],
        quit_wall_ns=stamp(230),owner_exit_wall_ns=stamp(231),end_wall_ns=stamp(250),
        output_collection=dict(method='bounded-child-pipes',maximum_bytes_per_stream=OUTPUT_MAXIMUM,complete=True))
    item['args']=owned_arguments(api,target,item['service'],item['uuid'],item['secret'],'allow',read_only=True,read_provider=True)
    item['bound']=dict(api=api,index=target['owner']['index'],generation=target['owner']['generation'],property=h,
        started_ns=stamp(4),deadline_ns=stamp(4)+5_000_000_000,returned_ns=stamp(5),result=0,
        notification_result=0,notification_ready=True,local_binding_only=True)
    capture=dict(acb_packets=[],native_events=[])
    exchanges=[]
    for ordinal,mode in enumerate(('application-error-ff','empty','value32')):
        start=stamp(10+ordinal*100);value=item['dynamic_value'] if ordinal==2 else ''
        prefix=['/bin/ws73-application-client-c'] if peer_api=='c' else ['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
        app=dict(api=peer_api,pid=3000+phase*100+ordinal,exit=0,stderr='',credentials=copy.deepcopy(creds),
            environment=application_environment(),ssap_operation='ssap-read',ssap_path=path,ssap_handle=h,
            start_wall_ns=start,end_wall_ns=start+10_000_000)
        if ordinal==0:
            app.update(args=prefix+['ssap-error',str(source['owner']['index']),str(source['owner']['generation']),path,'ssap-read',str(h),'5'],
                ssap_expected_errno=errno.EIO,start_monotonic_ns=start,end_monotonic_ns=start+10_000_000,
                ssap_error_deadline_ns=start+5_000_000_000,ssap_supervisor_deadline_ns=start+7_000_000_000)
            call=dict(stage='ssap_call',api=peer_api,client_closed=True,call_ns=start+1_000_000,deadline_ns=app['ssap_error_deadline_ns'])
            result=dict(stage='ssap_error',api=peer_api,errno=5,operation_success=False,deadline_ns=call['deadline_ns'],returned_ns=start+9_000_000)
            app['stdout']=json.dumps(call)+'\n'+json.dumps(result)+'\n'
        else:
            app.update(args=prefix+['ssap',str(source['owner']['index']),str(source['owner']['generation']),path,'ssap-read',str(h),value],
                       ssap_expected=value,ssap_release_monotonic_ns=start+1_000_000,ssap_released_wall_ns=start+1_000_000)
            app['stdout']=json.dumps(dict(stage='ssap_start_barrier',api=peer_api,client_closed=True))+'\n'+f'SsapPeerValue: operation=ssap-read path={path} handle={h} value={value}\n'
        d=dict(api=api,index=target['owner']['index'],generation=target['owner']['generation'],token=ordinal+1,request_id=ordinal+100,
            lifetime=target['object']['lifetime'],handle=target['object']['handle'],epoch=41,level=0,
            deadline_ns=start+4_900_000_000,property=h,maximum_bytes=2042,local_tcid=10,remote_tcid=10,pi=0,
            observed_ns=start+2_000_000,observed_wall_ns=start+2_000_000)
        approval={k:v for k,v in d.items() if k not in ('maximum_bytes','observed_ns','observed_wall_ns')}
        approval.update(data_type=0,write=False,value='',allow=True,decision_ns=start+1_800_000,decision_wall_ns=start+1_800_000)
        reply=dict(api=api,token=d['token'],current_token=d['token'],api_called=True,status=255 if ordinal==0 else 0,
            value=value,deadline_ns=d['deadline_ns'],started_ns=start+3_100_000,returned_ns=start+3_200_000,
            result=0,local_acceptance_only=True)
        callback=dict(prompt=d,publisher_pid=item['pid'],observed_monotonic_ns=start+2_100_000,observed_wall_ns=start+2_100_000,
            reply_before_monotonic_ns=start+3_000_000,reply_before_wall_ns=start+3_000_000,replied_monotonic_ns=start+4_000_000,
            replied_wall_ns=start+4_000_000,supervisor_deadline_ns=start+7_000_000_000+(1_000_000 if ordinal else 0))
        clock=lambda t:dict(monotonic_before_ns=t,realtime_ns=t+50,monotonic_after_ns=t+100)
        step=dict(mode=mode,read=app,callback=callback,reply=reply,approval=approval,
            reply_command=f'provider-error p{d["token"]} FF' if not ordinal else f'provide p{d["token"]} '+(value or '-'),
            clock_contract=copy.deepcopy(gate.CLOCK_CONTRACT),clock_before=clock(start-1000),clock_after=clock(start+11_000_000))
        item['steps'].append(step);row['ssap_language_clients'].append(app)
        exchanges.append((app,b'\x09\x0b\xff\0' if not ordinal else b'\x09\x03'+bytes.fromhex(value)))
    item['cleanup']=dict(args=['slctl','--adapter',target['owner']['path'],'ssap-list'],exit=0,stderr='',stdout='SsapLocalServices: []\n',
                         start_wall_ns=stamp(232),end_wall_ns=stamp(233))
    item['retired_read']=dict(args=['slctl','--adapter',source['owner']['path'],'ssap-read',path,str(h),'0'],
        exit=1,stderr='peer read error 4',stdout='',start_wall_ns=stamp(240),end_wall_ns=stamp(249))
    exchanges.append((item['retired_read'],b'\x09\x0b\x04\0'))
    transcript(item);row[gate.COLLECTION]=[item]
    for window,response in exchanges:
        for sender,target_no,pdu in [(0,1,b'\x08\x03\x21\0\0'),(1,0,response)]:
            frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
            for endpoint,direction in [(sender,'out'),(target_no,'in')]:
                owner=row['owners'][endpoint]
                at=window['start_wall_ns']+(1_200_000 if sender==0 else 5_000_000)+(100_000 if direction=='in' else 0)
                # Actual captures can have a one-fragment TX and two-fragment RX.
                # Exercise the production reassembler; RX never doubles TX credit.
                parts=[(1,frame[:29]),(3,frame[29:])] if direction=='in' and len(frame)==38 else [(0,frame)]
                for part,(boundary,payload) in enumerate(parts):
                    capture['acb_packets'].append(dict(bus=owner['owner']['bus'],device=owner['owner']['device'],handle=owner['object']['handle'],
                        direction=direction,data=payload.hex(),boundary=boundary,record=len(capture['acb_packets'])+1,wall_ns=at+part*1000))
    packets=reassemble_acb(capture)
    return row,matcher(packets),packets,old_packets


def summary():
    rows=[]
    for phase in (0,1):
        row,matched,packets,old_packets=fixture(phase)
        cli,_=old.corroborate(row,matcher(old_packets))
        sdk,credit=gate.corroborate(row,matched)
        assert not packets and not old_packets and credit=={0:4,1:4}
        rows.append(dict(phase=phase,owners=row['owners'],ssap_read_providers=cli,**{gate.SUMMARY_KEY:sdk}))
    return dict(proofs=rows)


def manifest():
    proof=summary();module=proof['proofs'][0][gate.SUMMARY_KEY][0]['tools'][gate.EXTRA_TOOLS[-1]]
    return dict(ssap_sdk_read_provider_requested=True,ssap_sdk_read_provider_version=1,ssap_sdk_read_provider_acceptance=True,
        ssap_sdk_read_provider_verifier=dict(path='/fixture/tools/ws73_ssap_sdk_read_provider.py',**module),
        ssap_read_provider_requested=True,ssap_read_provider_version=2,ssap_read_provider_acceptance=True,
        ssap_owned_acceptance=True,ordinary_channel_socket_acceptance=True,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
        qemu_args=[gate.TOKEN+' ws73.ssap_read_provider=1 ws73.ssap_owned=1'],channel_socket_corroboration=proof)


class SdkProviderEvidence(unittest.TestCase):
    def test_both_language_roles_paired_wire_and_original_baseline(self):
        proof=summary();self.assertTrue(gate.valid_summary(proof,version=1));self.assertTrue(gate.valid_manifest(manifest()))
        self.assertEqual([(p[gate.SUMMARY_KEY][0]['provider_api'],p[gate.SUMMARY_KEY][0]['peer_api']) for p in proof['proofs']],
                         [('c','python'),('python','c')])
        self.assertTrue(gate.valid_manifest({}))
        for version in (0,2,True,'1',None):self.assertFalse(gate.valid_summary(proof,version=version))

    def test_selector_and_rows_require_cli_baseline_and_distinct_receivers(self):
        args=dict(ssap_sdk_read_provider_verify=True,ssap_read_provider_verify=True,ssap_owned_verify=True,
                  passthrough=True,channel_socket_verify=True,channel_socket_rounds=4,channel_socket_bytes=61)
        self.assertTrue(gate.requested(SimpleNamespace(**args)))
        for key,value in [('ssap_read_provider_verify',False),('ssap_provider_owner_exit_verify',True),
                          ('ssap_provider_deadline_verify',True),('ssap_sdk_read_provider_verify',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(SimpleNamespace(**dict(args,**{key:value})))
        rows=[fixture(p)[0] for p in (0,1)];gate.validate_rows(rows,True)
        rows[1]['owners']=copy.deepcopy(rows[0]['owners'])
        with self.assertRaises(CaptureError):gate.validate_rows(rows,True)
        for tokens in ([gate.TOKEN],[gate.TOKEN,gate.TOKEN],['ws73.ssap_sdk_read_provider=0']):
            with self.assertRaises(ValueError):gate.boot_requested(tokens)

    def test_missing_duplicate_corrupt_or_late_usb_is_rejected(self):
        for mutation in ('missing-tx','missing-rx','duplicate','payload','before-call','after-return','non-usbmon-time'):
            row,match,packets,_=fixture();item=row[gate.COLLECTION][0];app=item['steps'][0]['read']
            if mutation=='missing-tx':packets.pop(0)
            elif mutation=='missing-rx':packets.pop(1)
            elif mutation=='duplicate':packets.append(copy.deepcopy(packets[0]))
            elif mutation=='payload':packets[2]['data']=packets[2]['data'][:-4]+'af00'
            else:
                chosen=packets[:2] if mutation=='before-call' else packets[2:4]
                at=app['start_wall_ns']+100_000 if mutation=='before-call' else app['end_wall_ns']-2000
                for n,p in enumerate(chosen):
                    p['wall_ns']=at+n*1000+(1 if mutation=='non-usbmon-time' else 0)
                    for f in p['fragments']:f['wall_ns']=p['wall_ns']
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,match)

    def test_local_receipt_cannot_substitute_for_peer_or_authorization(self):
        for mutation in ('peer-value','peer-language','notification','token','lifetime','approval','renew','result','maximum','duplicate-key','fake-cli','inventory'):
            row,match,_,_=fixture();item=row[gate.COLLECTION][0];step=item['steps'][1]
            if mutation=='peer-value':step['read']['stdout']=step['read']['stdout'].replace('value=\n','value=ff\n')
            elif mutation=='peer-language':step['read']['api']='c'
            elif mutation=='notification':item['bound']['notification_result']=-5
            elif mutation=='token':step['reply']['current_token']+=1
            elif mutation=='lifetime':step['callback']['prompt']['lifetime']+=1
            elif mutation=='approval':step['approval']['allow']=False
            elif mutation=='renew':step['reply']['deadline_ns']+=1
            elif mutation=='result':step['reply']['result']=-errno.ESTALE
            elif mutation=='maximum':step['callback']['prompt']['maximum_bytes']=True
            elif mutation=='inventory':row['ssap_language_clients'].pop()
            transcript(item)
            if mutation=='duplicate-key':item['stdout']=item['stdout'].replace('"notification_ready": true','"notification_ready": false, "notification_ready": true')
            if mutation=='fake-cli':item['stdout']+='SsapReadProviderResult: request=1 property=33 status=0 bytes=0; application response only\n'
            item['captured_bytes']['stdout']=len(item['stdout'].encode())
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):gate.corroborate(row,match)

    def test_summary_requires_retained_cli_and_exact_new_proof(self):
        for mutation in ('missing-cli','cli-wire','missing-sdk','sdk-wire','version','context','context-phase-bool','tool'):
            proof=summary();row=proof['proofs'][0];item=row[gate.SUMMARY_KEY][0]
            if mutation=='missing-cli':del row['ssap_read_providers']
            elif mutation=='cli-wire':row['ssap_read_providers'][0]['wire'].pop()
            elif mutation=='missing-sdk':del row[gate.SUMMARY_KEY]
            elif mutation=='sdk-wire':item['wire'].pop()
            elif mutation=='version':item['version']=True
            elif mutation=='context':item['context']['ssap_read_provider_cases'][0]['policy']='deny'
            elif mutation=='context-phase-bool':proof['proofs'][1][gate.SUMMARY_KEY][0]['context']['phase']=True
            else:del item['tools'][gate.EXTRA_TOOLS[0]]
            with self.subTest(mutation=mutation):self.assertFalse(gate.valid_summary(proof))

    def test_clock_or_original_deadline_uncertainty_is_not_delivery(self):
        for mutation in ('missing','inverted','incompatible','bool-version','renewed','quantization-overlap'):
            row,match,packets,_=fixture();item=row[gate.COLLECTION][0];step=item['steps'][0]
            if mutation=='missing':del step['clock_before']
            elif mutation=='inverted':step['clock_before']['monotonic_after_ns']=1
            elif mutation=='incompatible':step['clock_after']['realtime_ns']+=1_000_000
            elif mutation=='bool-version':step['clock_contract']['version']=True
            elif mutation=='renewed':step['callback']['prompt']['deadline_ns']+=10_000_000_000;transcript(item)
            else:
                packet=packets[3];packet['wall_ns']=step['read']['start_wall_ns']+9_000_000-1000
                for f in packet['fragments']:f['wall_ns']=packet['wall_ns']
            with self.subTest(mutation=mutation),self.assertRaises((CaptureError,KeyError)):
                gate.corroborate(row,match)

    def test_manifest_pins_and_no_request_residual_fail_closed(self):
        good=manifest()
        for mutation in ('missing-verifier','bad-hash','bad-bytes','extra-key','wrong-path','false-request','missing-owned','missing-ordinary'):
            bad=copy.deepcopy(good)
            if mutation=='missing-verifier':del bad[gate.PREFIX+'_verifier']
            elif mutation=='bad-hash':bad[gate.PREFIX+'_verifier']['sha256']='f'*64
            elif mutation=='bad-bytes':bad[gate.PREFIX+'_verifier']['bytes']+=1
            elif mutation=='extra-key':bad[gate.PREFIX+'_verifier']['untrusted']=True
            elif mutation=='wrong-path':bad[gate.PREFIX+'_verifier']['path']='/other.py'
            elif mutation=='false-request':bad[gate.PREFIX+'_requested']=False
            elif mutation=='missing-owned':bad['ssap_owned_acceptance']=False
            else:bad['ordinary_channel_socket_acceptance']=False
            with self.subTest(mutation=mutation):self.assertFalse(gate.valid_manifest(bad))
        for key,value in ((gate.PREFIX+'_verifier',good[gate.PREFIX+'_verifier']),(gate.PREFIX+'_version',1),
                          ('channel_socket_corroboration',good['channel_socket_corroboration'])):
            with self.subTest(residual=key):self.assertFalse(gate.valid_manifest({key:value}))


if __name__=='__main__':unittest.main()
