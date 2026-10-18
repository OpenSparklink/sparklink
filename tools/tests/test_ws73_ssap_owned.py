"""Evidence verdict fixtures; not a peer, kernel or protocol implementation."""
import hashlib
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_ssap_owned import corroborate
from ws73_ssap_access import value_operations


def fixture():
    owners=[dict(owner=dict(path=f'/a{s}'),object=dict(path=f'/a{s}/link')) for s in (0,1)]
    row=dict(ssap_owned_required=True,owners=owners,security_requirement=0,ssap_receipts=[dict(args=['slctl'])],ssap_owned=[]);wire=[]
    for s in (0,1):
        for policy in ('allow','deny'):
            data=lambda name:hashlib.sha256(f'{s}/{policy}/{name}'.encode()).digest()
            secret,value,uuid,service=data('secret'),data('value'),data('uuid')[:16],data('service')[:16]
            allow=policy=='allow';h=17;local=(value if allow else secret).hex()
            item=dict(sender=s,target=1-s,policy=policy,handle=h,start=16,end=h,secret=secret.hex(),value=value.hex(),uuid=uuid.hex(),service=service.hex(),start_wall_ns=1,end_wall_ns=100,owner_exit_wall_ns=60,exit=-9,owner_exit=-9,stderr='',local_value=local,credentials=dict(uids=[1000]*4,capabilities={'CapEff':'0','CapPrm':'0','CapAmb':'0'}),after_owner_exit=dict(exit=0,stdout='SsapLocalServices: []\n'))
            item['args']=['slctl','--adapter',owners[1-s]['owner']['path'],'ssap-serve',service.hex(),uuid.hex(),'5','36',secret.hex(),policy]
            item['stdout']=f'SsapOwnedValue: handle={h} value={local}\n'+''.join(f'SsapAuthorizationDecision: request={i+1} property={h} write={write} security=0 approved={str(allow).lower()}; local policy only\n' for i,write in enumerate(['false','false','true','false']))
            ops=value_operations(h,uuid,secret,value,0 if allow else 9)+[('removed_read',b'\x08\x03\x11\0\0',b'\x09\x0b\x04\0')]
            for name,request,response in ops:
                c=dict(exit=0,stdout='',stderr='',start_wall_ns=70 if name=='removed_read' else 20,end_wall_ns=71 if name=='removed_read' else 21)
                if name=='uuid_read':c['stdout']=f'SsapUuidTrace: request={request.hex()} response={response.hex()}\n'
                elif not allow or name=='removed_read':c.update(exit=1,stderr=f'peer {"write" if name=="write" else "read"} error {4 if name=="removed_read" else 9}')
                else:c['stdout']=f'SsapPeerValue: operation={"ssap-write" if name=="write" else "ssap-read"} path=/a{s}/link handle={h} value={(secret if name=="read" else value).hex()}\n'
                item[name]=c
                for a,b,pdu in [(s,1-s,request),(1-s,s,response)]:
                    frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                    wire.extend([(a,'out',frame,id(c)),(b,'in',frame,id(c))])
            row['ssap_owned'].append(item)
    def matched(owner,direction,pdu,command):
        key=(owners.index(owner),direction,pdu,id(command))
        if key not in wire:raise CaptureError('missing exact original wire leg')
        wire.remove(key);return dict(data=pdu.hex())
    return row,matched,wire


class OwnedEvidence(unittest.TestCase):
    def test_all_four_cases_consume_every_endpoint_and_account_only_actual_sends(self):
        row,match,wire=fixture();proof,credit=corroborate(row,match)
        self.assertEqual(len(proof),4);self.assertFalse(wire);self.assertEqual(credit,{0:20,1:20})

    def test_missing_or_modified_required_evidence_never_passes(self):
        for kind in ('missing-case','wrong-policy','foreign-owner','capability','uid','missing-decision','repeat-decision','changed-grade','changed-decision','local-value','exit','metadata','owner-order','failed-read','false-denial','payload','missing-wire','late-command','missing-peer'):
            row,match,wire=fixture();i=row['ssap_owned'][0]
            if kind=='missing-case':row['ssap_owned'].pop()
            elif kind=='wrong-policy':i['policy']='deny'
            elif kind=='foreign-owner':i['args'][2]='/other'
            elif kind=='capability':i['credentials']['capabilities']['CapEff']='1'
            elif kind=='uid':i['credentials']['uids']=[0]*4
            elif kind=='missing-decision':i['stdout']=i['stdout'].replace('SsapAuthorizationDecision: request=1','INVALID: request=1')
            elif kind=='repeat-decision':i['stdout']=i['stdout'].replace('request=2','request=1')
            elif kind=='changed-grade':i['stdout']=i['stdout'].replace('security=0','security=2')
            elif kind=='changed-decision':i['stdout']=i['stdout'].replace('approved=true','approved=false')
            elif kind=='local-value':i['local_value']='00'
            elif kind=='exit':i['exit']=0
            elif kind=='metadata':i['after_owner_exit']['stdout']='SsapLocalServices: [[16,17,[],[]]]\n'
            elif kind=='owner-order':i['owner_exit_wall_ns']=99
            elif kind=='failed-read':i['read']['exit']=1
            elif kind=='false-denial':row['ssap_owned'][1]['write']['exit']=0
            elif kind=='payload':i['value']='11'*32
            elif kind=='missing-wire':wire.pop()
            elif kind=='late-command':i['read']['end_wall_ns']=101
            else:wire[:]=[w for w in wire if not(w[0]==1 and w[1]=='in')]
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate(row,match)

    def test_guest_copy_and_hash_inventory_and_opt_in_are_present(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'ws73_target.py').read_text()
        self.assertEqual(source.count("'ws73_ssap_owned.py'"),2)
        self.assertIn('ssap_owned_verification_requested',source)
        self.assertIn('owned SSAP request/evidence mismatch',source)
        self.assertIn('--ssap-owned-verify',(root/'ws73_target_init.sh').read_text())


if __name__=='__main__':unittest.main()
