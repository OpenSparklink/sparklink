import copy,hashlib,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_ssap_value import corroborate
from ws73_capture import CaptureError

class ActualValueEvidence(unittest.TestCase):
    def fixture(self,namespace=0):
        owners=[dict(owner=dict(path=f'/adapter{i}'),object=dict(path=f'/adapter{i}/link')) for i in range(2)]
        row=dict(owners=owners,ssap_values=[],ssap_local_registrations=[]);wire=[]
        previous=[bytes([1]*32),bytes([2]*32)]
        for i,o in enumerate(owners):row['ssap_local_registrations'].append(dict(owner=o,start=1,handle=2,registration=dict(exit=0,stdout='SsapLocalService: start=1 end=2 properties=2\n')))
        for n in range(4):
            for sender,target in [(0,1),(1,0)]:
                v=n.to_bytes(4,'little')+hashlib.sha256(bytes([namespace,n,sender])).digest()[:28];before=previous[target];item=dict(sender=sender,target=target,sequence=n,handle=2,value=v.hex(),before=before.hex(),start_wall_ns=len(wire)+1,end_wall_ns=len(wire)+20)
                for name,op,value in [('read_before','ssap-read',before),('write','ssap-write',v),('read_after','ssap-read',v)]:item[name]=dict(exit=0,stdout=f"SsapPeerValue: operation={op} path=/adapter{sender}/link handle=2 value={value.hex()}\n",start_wall_ns=item['start_wall_ns'],end_wall_ns=item['end_wall_ns'])
                item['local_check']=dict(exit=0,stdout=f'SsapLocalValue: handle=2 value={v.hex()}\n');row['ssap_values'].append(item);previous[target]=v
                packets=[(sender,target,b'\x08\x03\x02\0\0'),(target,sender,b'\x09\x03'+before),(sender,target,b'\x0d\x23\x02\0\0'+v),(target,sender,b'\x0e\x03\x02\0\0'+v),(sender,target,b'\x08\x03\x02\0\0'),(target,sender,b'\x09\x03'+v)]
                for a,b,p in packets:
                    frame=b'\x0a\0'+len(p).to_bytes(2,'little')+p
                    wire.extend([(a,'out',frame,item['start_wall_ns']),(b,'in',frame,item['start_wall_ns'])])
        def matched(owner,direction,payload,item):
            key=(owners.index(owner),direction,payload,item['start_wall_ns'])
            if key not in wire:raise CaptureError('missing actual endpoint record')
            wire.remove(key);return dict(data=payload.hex())
        return row,matched,wire
    def test_both_applications_and_48_wire_legs_required(self):
        row,matched,wire=self.fixture();p,credit=corroborate(row,matched);self.assertEqual(len(p),8);self.assertEqual(credit,{0:24,1:24});self.assertEqual(len(wire),0)
    def test_local_validation_reply_and_opposite_rx_are_not_optional(self):
        for name in ['local_check','read_after','write']:
            row,matched,_=self.fixture();row['ssap_values'][0][name]['stdout']='fake success'
            with self.assertRaises(CaptureError):corroborate(row,matched)
        row,matched,wire=self.fixture();wire.pop(1)
        with self.assertRaises(CaptureError):corroborate(row,matched)
    def test_duplicate_direction_or_nonce_rejected(self):
        row,matched,_=self.fixture();row['ssap_values'][1]=copy.deepcopy(row['ssap_values'][0])
        with self.assertRaises(CaptureError):corroborate(row,matched)
        row,matched,_=self.fixture();row['ssap_values'][1]['value']=row['ssap_values'][0]['value']
        with self.assertRaises(CaptureError):corroborate(row,matched)

    def uuid_fixture(self,namespace=0):
        row,matched,wire=self.fixture(namespace);row['ssap_read_uuid_required']=True
        uuid=bytes(range(16));request=b'\x0a\x01\x10\x00\xff\xff\x00'+uuid
        for r in row['ssap_local_registrations']:r['property_uuid']=uuid.hex()
        for item in row['ssap_values']:
            item['property_uuid']=uuid.hex();sender,target=item['sender'],item['target'];stamp=item['start_wall_ns']
            for name,key in [('uuid_read_before','before'),('uuid_read_after','value')]:
                value=bytes.fromhex(item[key]);response=b'\x0b\x03\x02\0'+value
                item[name]=dict(exit=0,stdout=f"SsapUuidValue: path=/adapter{sender}/link handle=2 success=true error=0 value={value.hex()}\nSsapUuidTrace: request={request.hex()} response={response.hex()}\n",start_wall_ns=stamp,end_wall_ns=item['end_wall_ns'])
                for a,b,p in [(sender,target,request),(target,sender,response)]:
                    frame=b'\x0a\0'+len(p).to_bytes(2,'little')+p;wire.extend([(a,'out',frame,stamp),(b,'in',frame,stamp)])
        return row,matched,wire
    def test_uuid_reads_require_both_real_wire_legs_and_original_receipts(self):
        row,matched,wire=self.uuid_fixture();proof,credit=corroborate(row,matched);self.assertEqual(credit,{0:40,1:40});self.assertFalse(wire);self.assertTrue(all(len(p['uuid_wire'])==2 for p in proof))
        for mutation in ['stdout','uuid','wire']:
            row,matched,wire=self.uuid_fixture()
            if mutation=='stdout':row['ssap_values'][0]['uuid_read_after']['stdout']='fake success'
            elif mutation=='uuid':row['ssap_values'][0]['property_uuid']='ff'*16
            else:wire.pop()
            with self.assertRaises(CaptureError):corroborate(row,matched)

    def test_actual_unsupported_receive_interest_is_not_success(self):
        row,matched,wire=self.fixture();row['ssap_update_local_rejection_required']=True;row['unsupported_incoming']=[]
        for a,b in [(0,1),(1,0)]:row['unsupported_incoming'].append(dict(sender=a,target=b,handle=2,receipt=dict(args=['slctl','--adapter',f'/adapter{a}','ssap-observe',f'/adapter{a}/link','2','notify','10'],exit=1,stderr='peer has not advertised requested property update capabilities')))
        proof,credit=corroborate(row,matched);self.assertEqual(len(proof),8);self.assertEqual(credit,{0:24,1:24});self.assertFalse(wire)
        row,matched,_=self.fixture();row['ssap_update_local_rejection_required']=True;row['unsupported_incoming']=[]
        with self.assertRaises(CaptureError):corroborate(row,matched)
