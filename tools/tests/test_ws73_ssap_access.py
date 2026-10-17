"""Evidence verdict fixtures, never a controller or SSAP Engine implementation."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_ssap_access import corroborate,audit_rejections
from ws73_capture import CaptureError

class AttributeEvidence(unittest.TestCase):
    def fixture(self,level=0):
        owners=[dict(owner=dict(path=f'/a{n}'),object=dict(path=f'/a{n}/link')) for n in range(2)]
        row=dict(ssap_access_required=True,security_requirement=level,owners=owners,start_wall_ns=1,end_wall_ns=100,ssap_access=[],ssap_access_registration_refusals=[]);wire=[]
        for s in [0,1]:
            row['ssap_access_registration_refusals'].append(dict(sender=s,before=dict(exit=0,stdout='original DB'),after=dict(exit=0,stdout='original DB'),refusals=[dict(access=a,command=dict(exit=1,stderr='InvalidArgs' if a==64 else 'NotSupported')) for a in [4,32,64]]))
            for a in [0,9,18]:
                data=lambda label:hashlib.sha256(f'{s}/{a}/{label}'.encode()).digest()
                secret,value,uuid=data('secret'),data('value'),data('uuid')[:16]
                e=8 if a==18 and level<2 else 10 if a==9 and level<1 else 0
                i=dict(sender=s,target=1-s,access=a,level=level,start=1,handle=2,secret=secret.hex(),value=value.hex(),uuid=uuid.hex(),error=e,start_wall_ns=10,end_wall_ns=90,registration=dict(exit=0,args=['slctl','ssap-register','service',uuid.hex(),'5',str(a),secret.hex()],stdout='SsapLocalService: start=1 end=2 properties=2\n'),removal=dict(exit=0))
                req=b'\x08\x03\x02\0\0';u=b'\x0a\x01\x10\0\xff\xff\0'+uuid;w=b'\x0d\x23\x02\0\0'+value
                for n,rspreq,rsp in [('read',req,b'\x09\x0b'+bytes([e,0]) if e else b'\x09\x03'+secret),('uuid_read',u,b'\x0b\x0b\x02\0'+bytes([e,0]) if e else b'\x0b\x03\x02\0'+secret),('write',w,b'\x0e\x07\x01\x02\0'+bytes([e]) if e else b'\x0e\x03\x02\0\0'+value),('read_after',req,b'\x09\x0b'+bytes([e,0]) if e else b'\x09\x03'+value)]:
                    c=dict(exit=0,start_wall_ns=11+len(wire),end_wall_ns=12+len(wire),stdout='',stderr='')
                    if n=='uuid_read':c['stdout']=f'SsapUuidTrace: request={rspreq.hex()} response={rsp.hex()}\n'
                    elif e:c.update(exit=1,stderr=f'peer {"write" if n=="write" else "read"} error {e}')
                    else:c['stdout']=f'SsapPeerValue: operation={"ssap-write" if n=="write" else "ssap-read"} path=/a{s}/link handle=2 value={(secret if n=="read" else value).hex()}\n'
                    # Per-command intervals cannot be inferred from a shared batch start.
                    c.update(start_wall_ns=20,end_wall_ns=21);i[n]=c
                    for sender,receiver,p in [(s,1-s,rspreq),(1-s,s,rsp)]:
                        frame=b'\x0a\0'+len(p).to_bytes(2,'little')+p
                        wire.extend([(sender,'out',frame,id(c)),(receiver,'in',frame,id(c))])
                i['local_check']=dict(exit=0,stdout=f'SsapLocalValue: handle=2 value={(secret if e else value).hex()}\n')
                if a==0:
                    i['local_rejections']=[dict(minimum=m,value=data(str(m)).hex(),command=dict(exit=1,stderr='minimum0..2' if m==3 else 'SSAP send intent refused')) for m in ([level+1,3] if level<2 else [3])]
                    i['after_local_rejection']=dict(exit=0,stdout=f'SsapLocalValue: handle=2 value={value.hex()}\n')
                row['ssap_access'].append(i)
        def matched(owner,direction,payload,c):
            k=(owners.index(owner),direction,payload,id(c))
            if k not in wire:raise CaptureError('missing exact USB endpoint')
            wire.remove(k);return dict(data=payload.hex())
        return row,matched,wire
    def test_guest_copy_and_hashed_input_inventories_include_the_actual_gate(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'ws73_target.py').read_text())
        prepare=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_locked')
        mentions=[n for n in ast.walk(prepare) if isinstance(n,ast.Constant) and n.value=='ws73_ssap_access.py']
        self.assertEqual(len(mentions),2,'both hashed input and actual guest copy required')

    def test_three_grades_two_directions_exact_endpoint_and_debt_inventory(self):
        for level in range(3):
            r,m,w=self.fixture(level);p,c=corroborate(r,m)
            self.assertEqual(len(p),6);self.assertEqual(c,{0:24,1:24});self.assertEqual(w,[])
            self.assertEqual(sum(v['peer_value_unchanged'] for v in p),[4,2,0][level])
    def test_missing_or_corrupted_required_receipt_is_never_pass(self):
        for kind in ['policy','registration','reply','local','missing','min','cleanup','interval','direction','duplicate','endpoint']:
            r,m,w=self.fixture();i=r['ssap_access'][0]
            if kind=='policy':i['access']=18
            elif kind=='registration':i['registration']['args'][-2]='18'
            elif kind=='reply':i['read']['stdout']='fake Complete'
            elif kind=='local':i['local_check']['stdout']='fake local success'
            elif kind=='missing':r['ssap_access'].pop()
            elif kind=='min':i['local_rejections'].pop()
            elif kind=='cleanup':i['removal']['exit']=1
            elif kind=='interval':i['write']['start_wall_ns']=0
            elif kind=='direction':i['target']=i['sender']
            elif kind=='duplicate':r['ssap_access'][1]['value']=i['value']
            else:w.pop()
            with self.subTest(kind=kind),self.assertRaises(CaptureError):corroborate(r,m)
    def test_refused_write_and_denied_secret_cannot_appear_on_usb(self):
        r,_,_=self.fixture();audit_rejections(r,[])
        for payload in [r['ssap_access'][0]['local_rejections'][0]['value'],r['ssap_access'][1]['secret']]:
            with self.assertRaises(CaptureError):audit_rejections(r,[dict(data='0a00'+payload,wall_ns=30)])
        # A denied WRITE request may reach the peer; the immutable DB check is separate.
        audit_rejections(r,[dict(data=r['ssap_access'][1]['value'],wall_ns=30)])
