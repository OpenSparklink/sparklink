"""Verifier fixtures only; not actual bus-role or RF qualification."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_ssap_service_policy import corroborate,record,STATUS,DENIED,SERVICE_DENIED


def fixture():
    owners=[dict(port=f'1-{n+1}',bus=1,device=n+2,index=n,generation=n+7,path=f'/a{n}',address=f'address{n}',version=1,features=2) for n in (0,1)]
    run=dict(initial=owners,daemon_before={'pid':11},slctl={'path':'/bin/slctl','sha256':'a'*64},connection_control={'phases':[{'start_wall_ns':1000}]})
    r=dict(version=1,status=STATUS,daemon=run['daemon_before'],slctl=run['slctl'],probe={'path':'/bin/probe','sha256':'b'*64},start_wall_ns=1,end_wall_ns=900,cases=[])
    for n,owner in enumerate(owners):
        secret=f'{n+1:02x}'*32;start=16;h=17
        c=dict(stdin={'uid':1005,'gid':1005,'mode':0o600,'fifo':True},owner=owner,exit=0,stderr='',secret=secret,start=start,end=h,handle=h,start_wall_ns=10+n*400,end_wall_ns=390+n*400,credentials={'Uid':['1005']*4,'Gid':['1005']*4,'Groups':[],**{k:['0'] for k in ['CapInh','CapEff','CapPrm','CapAmb']}},args=['/bin/slctl','--adapter',owner['path'],'ssap-serve','11'*16,'22'*16,'5','36',secret,'allow'],stdout=f'SsapOwnedService: start=16 end=17 property=17; local registration only\nSsapOwnedValue: handle=17 value={secret}\n',commands=[])
        for i,(role,mode,uid,gid) in enumerate([('service','service-only',1005,1005),('channel','service-channel',1004,1004),('observer','service-observer',1001,1001)]):
            labels=['own-service']+(['interface-less-own-read']+SERVICE_DENIED*2 if role=='service' else ['RegisterOwnedLocalService']+DENIED*2)
            text=f'AUTH_CREDENTIALS: uid={uid} gid={gid} caps=0\nAUTH_SERVICE_KERNEL_ACCESS: denied\n'
            if role=='service':text+='AUTH_SERVICE_OWNED: start=18 property=19 value=07 removed=true\nAUTH_SERVICE_REPLACED: property=19 values=08,07\nAUTH_OWNED_REPLACE_DEADLINE: expired=true\nAUTH_OWNED_DEADLINE: register/read/remove expired=true\n'
            text+=''.join('AUTH_DENIED: '+label+'\n' for label in labels)+f'AUTH_SERVICE_ROLE: {mode}\n'
            c['commands'].append(dict(role=role,args=['/bin/probe',owner['path'],mode,'16','17'],exit=0,stdout=text,stderr='',start_wall_ns=20+n*400+i*10,end_wall_ns=21+n*400+i*10))
        c['after_quit']=dict(role='ws73',args=['/bin/slctl','--adapter',owner['path'],'ssap-list'],exit=0,stdout='SsapLocalServices: []\n',stderr='',start_wall_ns=100+n*400,end_wall_ns=101+n*400)
        r['cases'].append(c)
    return r,run


class ServicePolicy(unittest.TestCase):
    def test_missing_duplicate_or_wrong_deadline_receipt_fails_closed(self):
        for text in ['', 'AUTH_OWNED_DEADLINE: register/read/remove expired=false\n',
                     'AUTH_OWNED_DEADLINE: register/read/remove expired=true\n' * 2]:
            r,run=fixture()
            c=r['cases'][0]['commands'][0]
            c['stdout']=c['stdout'].replace('AUTH_OWNED_DEADLINE: register/read/remove expired=true\n',text)
            with self.subTest(text=text),self.assertRaises(CaptureError):corroborate(r,run)

    def test_complete_synthetic_fixture_only_validates_verdict(self):
        p=corroborate(*fixture());self.assertEqual(len(p),2);self.assertEqual(sum(v['denials'] for v in p),80)

    def test_missing_wrong_role_scope_and_terminal_evidence_are_rejected(self):
        for kind in ('pipe','missing','uid','group','capability','probe-uid','denial','positive','kernel','registration','value','foreign-cleanup','retained','exit','stderr','daemon','late','phase','duplicate-owner','interval'):
            r,run=fixture();c=r['cases'][0]
            if kind=='pipe':c['stdin']['uid']=0
            elif kind=='missing':r['cases'].pop()
            elif kind=='uid':c['credentials']['Uid']=['0']*4
            elif kind=='group':c['credentials']['Groups']=['1000']
            elif kind=='capability':c['credentials']['CapEff']=['1']
            elif kind=='probe-uid':c['commands'][0]['stdout']=c['commands'][0]['stdout'].replace('uid=1005','uid=0')
            elif kind=='denial':c['commands'][0]['stdout']=c['commands'][0]['stdout'].replace('AUTH_DENIED:','Missing:',1)
            elif kind=='positive':c['commands'][0]['stdout']=c['commands'][0]['stdout'].replace('removed=true','removed=false')
            elif kind=='kernel':c['commands'][0]['stdout']=c['commands'][0]['stdout'].replace('AUTH_SERVICE_KERNEL_ACCESS: denied','')
            elif kind=='registration':c['stdout']=c['stdout'].replace('property=17;','property=18;')
            elif kind=='value':c['stdout']=c['stdout'].replace(c['secret'],'00'*32)
            elif kind=='foreign-cleanup':c['after_quit']['args'][2]='/foreign'
            elif kind=='retained':c['after_quit']['stdout']='SsapLocalServices: [[16,17,[],[]]]\n'
            elif kind=='exit':c['exit']=-9
            elif kind=='stderr':c['commands'][0]['stderr']='unexpected error'
            elif kind=='daemon':r['daemon']={'pid':99}
            elif kind=='late':r['end_wall_ns']=1001
            elif kind=='phase':r['status']='RUNNING'
            elif kind=='duplicate-owner':r['cases'][1]['owner']=copy.deepcopy(r['cases'][0]['owner'])
            else:c['commands'][0]['start_wall_ns']=c['end_wall_ns']+1
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate(r,run)

    def test_non_root_cannot_run_supervisor_or_spawn_anything(self):
        with patch('ws73_ssap_service_policy.os.geteuid',return_value=1000),patch('ws73_ssap_service_policy.subprocess.Popen') as spawned,self.assertRaises(CaptureError):record(None,[],11)
        spawned.assert_not_called()

    def test_actual_guest_copy_and_input_hash_inventory_include_gate(self):
        tools=Path(__file__).resolve().parents[1];s=(tools/'ws73_target.py').read_text()
        self.assertEqual(s.count("'ws73_ssap_service_policy.py'"),4) # input,copy,before/after verifier hash
        self.assertIn('explicit service-role request/evidence mismatch',s)
        self.assertIn('service:x:1005:1005:',s)
        self.assertIn('service-policy "$daemon"',(tools/'ws73_target_init.sh').read_text())

    def test_replacement_and_expired_replacement_are_mandatory(self):
        for text in ['AUTH_SERVICE_REPLACED: property=19 values=08,07\n','AUTH_OWNED_REPLACE_DEADLINE: expired=true\n']:
            r,run=fixture();r['cases'][0]['commands'][0]['stdout']=r['cases'][0]['commands'][0]['stdout'].replace(text,'')
            with self.assertRaises(CaptureError):corroborate(r,run)


if __name__=='__main__':unittest.main()
