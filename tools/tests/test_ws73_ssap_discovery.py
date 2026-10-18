import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_ssap_discovery import corroborate
from ws73_capture import CaptureError

class DiscoveryEvidence(unittest.TestCase):
    def fixture(self):
        owners=[dict(owner=dict(path=f'/adapter{i}'),object=dict(path=f'/adapter{i}/link')) for i in range(2)];row=dict(owners=owners,ssap_local_registrations=[],ssap_discoveries=[]);packets=[]
        for i in range(2):row['ssap_local_registrations'].append(dict(start=16,handle=17,service_uuid=bytes([i+1]*16).hex(),property_uuid=bytes([i+3]*16).hex()))
        for sender,target in [(0,1),(1,0)]:
            s=bytes([target+1]*16);p=bytes([target+3]*16)
            for mode,k in [('hierarchy',1),('service',1),('property',3),('structure',0)]:
                svc=f'SsapRemoteEntry: category=8 handle=16 end=17 uuid={s.hex()} operations=0 descriptors= members=2'
                prop=f'SsapRemoteEntry: category=10 handle=17 end=17 uuid={p.hex()} operations=5 descriptors= members=0'
                primary=b'\x05\x0b\x81\x10\0\x11\0'+s+b'\x02';property_rsp=b'\x05\x0b\x81\x11\0'+p+b'\x05\0\0\0\0'
                if mode=='hierarchy':q=[bytes.fromhex('04110100ffff'),bytes.fromhex('04111200ffff'),bytes.fromhex('041310001100')];rs=[primary,bytes.fromhex('01000412000b'),property_rsp];entries=[svc,prop]
                else:
                    control={'service':17,'property':19,'structure':16}[mode];uuid=p if mode=='property' else s;q=[bytes([6,control,1,0,255,255])+uuid,bytes([6,control,18,0,255,255])+uuid]
                    full=b'\x07\x0b\x10\0\x08'+s+b'\0\x11\0\x0a'+p+b'\x05\0\0\0\0'
                    rs=[bytes([7])+primary[1:] if mode=='service' else bytes([7])+property_rsp[1:] if mode=='property' else full,bytes.fromhex('01000612000b')]
                    entries=[svc] if mode=='service' else [prop] if mode=='property' else [svc.replace('end=17','end=0').replace('members=2','members=0'),prop]
                receipt=dict(exit=0,stdout='\n'.join(entries)+f"\nSsapRemoteDiscovery: path=/adapter{sender}/link kind={k} entries={len(entries)} requests={'|'.join(v.hex() for v in q)} responses={'|'.join(v.hex() for v in rs)}\n",start_wall_ns=len(packets)+1,end_wall_ns=len(packets)+100)
                row['ssap_discoveries'].append(dict(sender=sender,target=target,mode=mode,receipt=receipt))
                for req,rsp in zip(q,rs):
                    for a,b,v in [(sender,target,req),(target,sender,rsp)]:
                        frame=b'\x0a\0'+len(v).to_bytes(2,'little')+v;packets.extend([(a,'out',frame,receipt['start_wall_ns']),(b,'in',frame,receipt['start_wall_ns'])])
        def matched(owner,direction,payload,receipt):
            key=(owners.index(owner),direction,payload,receipt['start_wall_ns'])
            if key not in packets:raise CaptureError('missing opposite packet')
            packets.remove(key);return dict(data=payload.hex())
        return row,matched,packets
    def test_both_schema_directions_and_usb_ends(self):
        row,m,packets=self.fixture();p,c=corroborate(row,m);self.assertEqual(len(p),8);self.assertEqual(c,{0:18,1:18});self.assertEqual(packets,[])
    def test_cannot_substitute_local_handle_cache_or_wrong_uuid(self):
        for old,new in [('handle=17','handle=2'),('members=2','members=0'),('uuid=0101','uuid=0909')]:
            row,m,_=self.fixture();row['ssap_discoveries'][4]['receipt']['stdout']=row['ssap_discoveries'][4]['receipt']['stdout'].replace(old,new)
            with self.assertRaises(CaptureError):corroborate(row,m)
    def test_missing_opposite_rx_and_duplicate_mode_fail(self):
        row,m,p=self.fixture();p.pop(1)
        with self.assertRaises(CaptureError):corroborate(row,m)
        row,m,_=self.fixture();row['ssap_discoveries'][1]=copy.deepcopy(row['ssap_discoveries'][0])
        with self.assertRaises(CaptureError):corroborate(row,m)
