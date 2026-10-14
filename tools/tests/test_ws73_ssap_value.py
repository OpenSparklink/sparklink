import copy,hashlib,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_ssap_value import corroborate
from ws73_capture import CaptureError

class ActualValueEvidence(unittest.TestCase):
    def fixture(self):
        owners=[dict(owner=dict(path=f'/adapter{i}'),object=dict(path=f'/adapter{i}/link')) for i in range(2)]
        row=dict(owners=owners,ssap_values=[],ssap_local_registrations=[]);wire=[]
        previous=[bytes([1]*32),bytes([2]*32)]
        for i,o in enumerate(owners):row['ssap_local_registrations'].append(dict(owner=o,start=1,handle=2,registration=dict(exit=0,stdout='SsapLocalService: start=1 end=2 properties=2\n')))
        for n in range(4):
            for sender,target in [(0,1),(1,0)]:
                v=n.to_bytes(4,'little')+hashlib.sha256(bytes([n,sender])).digest()[:28];before=previous[target];item=dict(sender=sender,target=target,sequence=n,handle=2,value=v.hex(),before=before.hex(),start_wall_ns=len(wire)+1,end_wall_ns=len(wire)+20)
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
