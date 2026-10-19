# SPDX-License-Identifier: GPL-2.0-only
"""Independent original-format golden evidence;not USB/kernel/RF qualification."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_capture import CaptureError
from ws73_application_client import owned_arguments,application_environment
from ws73_ssap_owned_update import corroborate,valid_summary,STATUS


def fixture(phase=0):
    N=1_000_000_000;B=1_800_000_000_000_000_000;wall=lambda x:B+int(x*N);mono=lambda x:int(x*N)
    owners=[dict(owner=dict(index=n,generation=7+n,path=f'/a{n}',bus=1,device=n+2),object=dict(path=f'/a{n}/link',handle=n+1,lifetime=11))for n in (0,1)]
    s,t=phase,1-phase;api='c'if not phase else'python';data=lambda k,n=32:hashlib.sha256(k.encode()).hexdigest()[:2*n]
    identity=dict(uids=[1000]*4,capabilities={k:'0'for k in ['CapEff','CapPrm','CapAmb','CapInh']})
    row=dict(phase=phase,owners=owners,ssap_owned_update_required=True,ssap_owned_update_status=STATUS,ssap_receipts=[dict(args=['slctl'])])
    i=dict(sender=s,target=t,policy='none',publisher_api=api,secret=data('initial'),service=data('service',16),uuid=data('uuid',16),start=16,end=17,handle=17,start_wall_ns=wall(0),end_wall_ns=wall(7),environment=application_environment(),credentials=copy.deepcopy(identity),exit=0,stderr='',updates=[],value_snapshots=[])
    i['args']=owned_arguments(api,owners[t],i['service'],i['uuid'],i['secret'],'none',read_only=True);row['ssap_owned_updates']=[i]
    i['stdout']=f'SdkOwnedAPI: api={api} client_closed=true\nSsapOwnedService: start=16 end=17 property=17; local registration only\n';pending=[]
    prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    def wire(a,b,pdu,when):
        frame=(b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu).hex()
        for index,direction in [(a,'out'),(b,'in')]:pending.append(dict(index=index,bus=1,device=index+2,handle=index+1,direction=direction,data=frame,wall_ns=wall(when)))
    for n,at in enumerate([1,3]):
        value=data('update'+str(n));receipt=dict(api=api,handle=17,value=value,started_ns=mono(at+.01),returned_ns=mono(at+.02),deadline_ns=mono(at+.01)+5*N)
        snapshot=dict(handle=17,value=value,ordinal=n+1,start_wall_ns=wall(at+.04),end_wall_ns=wall(at+.05))
        call=dict(api=api,position=s,ssap_operation='ssap-read',ssap_path=owners[s]['object']['path'],ssap_handle=17,ssap_expected=value,args=prefix+['ssap',str(s),str(7+s),owners[s]['object']['path'],'ssap-read','17',value],environment=application_environment(),credentials=copy.deepcopy(identity),exit=0,stderr='',start_wall_ns=wall(at+.1),end_wall_ns=wall(at+.2),stdout=json.dumps(dict(stage='ssap_start_barrier',api=api,client_closed=True))+'\n'+f'SsapPeerValue: operation=ssap-read path={owners[s]["object"]["path"]} handle=17 value={value}\n')
        i['updates'].append(dict(value=value,receipt=receipt,snapshot=snapshot,read=call,start_wall_ns=wall(at),end_wall_ns=wall(at+.03),start_monotonic_ns=mono(at),end_monotonic_ns=mono(at+.03)))
        i['value_snapshots'].append(snapshot);i['stdout']+='SdkOwnedReplaced: '+json.dumps(receipt)+'\n'+f'SsapOwnedValue: handle=17 value={value}\n'
        wire(s,t,b'\x08\x03\x11\0\0',at+.11);wire(t,s,b'\x09\x03'+bytes.fromhex(value),at+.15)
    i['forbidden_value']=data('forbidden')
    call=dict(stage='ssap_call',api=api,deadline_ns=mono(10),call_ns=mono(5.01),client_closed=True);error=dict(stage='ssap_error',api=api,errno=5,operation_success=False,deadline_ns=mono(10),returned_ns=mono(5.1))
    i['forbidden_write']=dict(args=prefix+['ssap-error',str(s),str(7+s),owners[s]['object']['path'],'ssap-write','17','5',i['forbidden_value']],environment=application_environment(),exit=0,stderr='',stdout=json.dumps(call)+'\n'+json.dumps(error)+'\n',credentials=copy.deepcopy(identity),start_wall_ns=wall(5),end_wall_ns=wall(5.2),start_monotonic_ns=mono(5),end_monotonic_ns=mono(5.2))
    wire(s,t,b'\x0d\x23\x11\0\0'+bytes.fromhex(i['forbidden_value']),5.02);wire(t,s,b'\x0e\x07\x01\x11\0\x07',5.07)
    i['value_snapshots'].append(dict(handle=17,value=i['updates'][-1]['value'],ordinal=3,start_wall_ns=wall(5.3),end_wall_ns=wall(5.4)))
    i['stdout']+=f'SsapOwnedValue: handle=17 value={i["updates"][-1]["value"]}\nSdkOwnedRemoved: api={api} start=16\n'
    i['quit_wall_ns']=wall(6);i['cleanup']=dict(args=['slctl','--adapter',owners[t]['owner']['path'],'ssap-list'],exit=0,stderr='',stdout='SsapLocalServices: []\n',start_wall_ns=wall(6.1),end_wall_ns=wall(6.2))
    def matched(entry,direction,frame,window):
        found=[p for p in pending if p['index']==entry['owner']['index']and p['direction']==direction and p['data']==frame.hex()and window['start_wall_ns']<=p['wall_ns']<=window['end_wall_ns']]
        if len(found)!=1:raise CaptureError('one original golden TX/opposite RX required')
        pending.remove(found[0]);return found[0]
    return row,matched,pending


class OwnedValueEvidence(unittest.TestCase):
    def test_both_languages_require_real_readbacks_and_unchanged_peer_permissions(self):
        for phase in (0,1):
            row,matched,pending=fixture(phase);proof,credits=corroborate(row,matched)
            self.assertEqual(pending,[]);self.assertEqual(credits,{0:3,1:3});self.assertEqual(proof[0]['peer_validated_reads'],2)

    def test_changed_or_missing_originals_fail_closed(self):
        for kind in ['api','readonly','role','missing-receipt','late','wrong-value','early-peer','missing-peer-compare','peer-write-success','peer-write-value-changed','missing-unregister','foreign-cleanup','RX-missing']:
            row,matched,pending=fixture();i=row['ssap_owned_updates'][0];v=i['updates'][0]
            if kind=='api':i['publisher_api']='python'
            elif kind=='readonly':i['args'][1]='owned'
            elif kind=='role':i['credentials']['capabilities']['CapEff']='1'
            elif kind=='missing-receipt':i['stdout']=i['stdout'].replace('SdkOwnedReplaced:','AbsentReceipt:',1)
            elif kind=='late':v['receipt']['returned_ns']=v['receipt']['deadline_ns']
            elif kind=='wrong-value':v['value']='00'*32
            elif kind=='early-peer':v['read']['start_wall_ns']=v['start_wall_ns']
            elif kind=='missing-peer-compare':v['read']['stdout']=''
            elif kind=='peer-write-success':i['forbidden_write']['stdout']=i['forbidden_write']['stdout'].replace('"operation_success": false','"operation_success": true')
            elif kind=='peer-write-value-changed':i['value_snapshots'][-1]['value']=i['forbidden_value']
            elif kind=='missing-unregister':i['exit']=-9
            elif kind=='foreign-cleanup':i['cleanup']['args'][2]='/other'
            else:pending[:]=[p for p in pending if p['direction']=='out']
            with self.assertRaises((CaptureError,ValueError,KeyError),msg=kind):corroborate(row,matched)

    def test_terminal_is_typed_and_cannot_omit_a_direction_or_usb_leg(self):
        phases=[]
        for n in (0,1):
            row,matched,_=fixture(n);proof,_=corroborate(row,matched);phases.append(dict(phase=n,ssap_owned_updates=proof))
        summary=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=phases);self.assertTrue(valid_summary(summary))
        for kind in ['phase','role','counter','wire','other','result']:
            bad=copy.deepcopy(summary);r=bad['proofs'][1]['ssap_owned_updates'][0]
            if kind=='phase':bad['proofs'][1]['phase']=True
            elif kind=='role':r['sender']=True
            elif kind=='counter':r['replacements']=True
            elif kind=='wire':r['wire'][0]['rx']['data']='00'
            elif kind=='other':bad['proofs'].pop()
            else:bad['status']='SKIP'
            self.assertFalse(valid_summary(bad),kind)
