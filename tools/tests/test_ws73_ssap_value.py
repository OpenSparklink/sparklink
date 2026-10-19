import copy,hashlib,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_ssap_value import corroborate, LENGTHS, lengths_requested, valid_length_summary
from ws73_capture import CaptureError

class ActualValueEvidence(unittest.TestCase):
    def fixture(self,namespace=0,lengths=False):
        owners=[dict(owner=dict(path=f'/adapter{i}'),object=dict(path=f'/adapter{i}/link')) for i in range(2)]
        row=dict(owners=owners,ssap_values=[],ssap_local_registrations=[]);wire=[]
        previous=[bytes([1]*32),bytes([2]*32)]
        for i,o in enumerate(owners):row['ssap_local_registrations'].append(dict(owner=o,start=1,handle=2,registration=dict(exit=0,stdout='SsapLocalService: start=1 end=2 properties=2\n')))
        for n,size in enumerate(LENGTHS if lengths else (32,)*4):
            for sender,target in [(0,1),(1,0)]:
                v=(n.to_bytes(4,'little')+(hashlib.sha256(bytes([namespace,n,sender])).digest()*64)[:size-4]) if size>=4 else bytes([sender+1])*size;before=previous[target];item=dict(sender=sender,target=target,sequence=n,handle=2,value=v.hex(),before=before.hex(),start_wall_ns=len(wire)+1,end_wall_ns=len(wire)+20)
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

    def uuid_fixture(self,namespace=0,lengths=False):
        row,matched,wire=self.fixture(namespace,lengths);row['ssap_read_uuid_required']=True
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
        for a,b in [(0,1),(1,0)]:row['unsupported_incoming'].append(dict(sender=a,target=b,handle=2,receipt=dict(args=['slctl','--adapter',f'/adapter{a}','ssap-receive',f'/adapter{a}/link','2','notify','10'],exit=1,stderr='peer has not advertised requested property update capabilities')))
        proof,credit=corroborate(row,matched);self.assertEqual(len(proof),8);self.assertEqual(credit,{0:24,1:24});self.assertFalse(wire)
        row,matched,_=self.fixture();row['ssap_update_local_rejection_required']=True;row['unsupported_incoming']=[]
        with self.assertRaises(CaptureError):corroborate(row,matched)

    def length_fixture(self):
        """Verifier fixture only; no claim to execute a real peer or decoder."""
        row,matched,wire=self.uuid_fixture(lengths=True)
        row.update(ssap_value_lengths_required=True,ssap_length_mtu=2042,ssap_receipts=[],ssap_length_rejections=[])
        for i,owner in enumerate(row['owners']):
            owner['owner'].update(index=i,generation=i+1);owner['object'].update(lifetime=7,handle=0)
            row['ssap_receipts'].append(dict(exit=0,stdout=f'SsapExchangeInfo: index={i} generation={i+1} lifetime=7 handle=0 local_mtu=2042 negotiated_mtu=2042 request=0203fa070102 peer_reply=0303fa070102 peer_request=0203fa070102 response=0303fa070102\n'))
        # Shift positive windows after all original refusal/unchanged reads.
        for item in row['ssap_values']:
            item['start_wall_ns']+=1000;item['end_wall_ns']+=1000
            for name in ['read_before','write','read_after','uuid_read_before','uuid_read_after']:
                item[name]['start_wall_ns']+=1000;item[name]['end_wall_ns']+=1000
        wire[:]=[(a,d,p,stamp+1000)for a,d,p,stamp in wire]
        for sender in (0,1):
            for size in (2038,2042,2043):
                before=bytes([2-sender])*32;stamp=-10-len(row['ssap_length_rejections'])*10
                item=dict(sender=sender,target=1-sender,handle=2,value=(b'\xaa'*size).hex(),before=before.hex(),start_wall_ns=stamp,
                    rejected=dict(exit=1,stderr='value codec: Mtu',args=['slctl','ssap-write',f'/adapter{sender}/link','2',(b'\xaa'*size).hex()],start_wall_ns=stamp,end_wall_ns=stamp+1),
                    unchanged=dict(exit=0,stdout=f'SsapPeerValue: operation=ssap-read path=/adapter{sender}/link handle=2 value={before.hex()}\n',start_wall_ns=stamp+2,end_wall_ns=stamp+3),end_wall_ns=stamp+4)
                for a,b,pdu in [(sender,1-sender,b'\x08\x03\x02\0\0'),(1-sender,sender,b'\x09\x03'+before)]:
                    packet=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
                    wire.extend([(a,'out',packet,stamp+2),(b,'in',packet,stamp+2)])
                row['ssap_length_rejections'].append(item)
        return row,matched,wire

    def test_length_mode_keeps_baseline_and_full_actual_wire_obligations(self):
        row,matched,wire=self.length_fixture();proof,credit=corroborate(row,matched)
        self.assertEqual(len(proof),32);self.assertEqual(credit,{0:166,1:166});self.assertFalse(wire)
        self.assertEqual(proof[0]['length_gate']['lengths'],list(LENGTHS))
        result=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=[dict(phase=0,ssap_values=proof),dict(phase=1,ssap_values=copy.deepcopy(proof))])
        self.assertTrue(valid_length_summary(result))
        for kind in ['missing-case','mtu','refusals','wire','payload']:
            bad=copy.deepcopy(result);v=bad['proofs'][0]['ssap_values']
            if kind=='missing-case':v.pop()
            elif kind=='mtu':v[0]['length_gate']['mtu']=249
            elif kind=='refusals':v[0]['length_gate']['refusals'].pop()
            elif kind=='wire':v[-1]['wire'].pop()
            else:v[-1]['value']='00'
            self.assertFalse(valid_length_summary(bad),kind)

    def test_actual_terminal_path_rejects_missing_boot_refusal_and_supervisor(self):
        from ws73_target import run_exit_code
        row,match,_=self.length_fixture();values,_=corroborate(row,match)
        proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=[dict(phase=p,ssap_values=copy.deepcopy(values))for p in (0,1)])
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,ordinary_channel_socket_acceptance=True,
            ssap_value_lengths_requested=True,ssap_value_lengths_acceptance=True,qemu_args=['ws73.ssap_value_lengths=1'],channel_socket_corroboration=proof)
        self.assertEqual(run_exit_code(record),0)
        for change in [dict(supervisor_exit=1),dict(qemu_exit=1),dict(qemu_args=[]),dict(ssap_value_lengths_requested=False),dict(ssap_value_lengths_acceptance=False)]:
            self.assertEqual(run_exit_code(record|change),1)
        for mutate in [lambda p:p['proofs'][1].update(phase=0),lambda p:p['proofs'][0]['ssap_values'][0]['length_gate']['refusals'].pop(),lambda p:p['proofs'][1]['ssap_values'].pop()]:
            bad=copy.deepcopy(proof);mutate(bad);self.assertEqual(run_exit_code(record|dict(channel_socket_corroboration=bad)),1)

    def test_length_refusal_state_identity_and_opposite_capture_are_required(self):
        for kind in ['missing','error','success','payload','read','window','generation','negotiation','state-chain','one-end']:
            row,matched,wire=self.length_fixture();r=row['ssap_length_rejections'][0]
            if kind=='missing':row['ssap_length_rejections'].pop()
            elif kind=='error':r['rejected']['stderr']='timeout'
            elif kind=='success':r['rejected']['exit']=0
            elif kind=='payload':r['rejected']['args'][-1]='00'
            elif kind=='read':r['unchanged']['stdout']='fake local success'
            elif kind=='window':r['end_wall_ns']=99999
            elif kind=='generation':row['owners'][0]['owner']['generation']=3
            elif kind=='negotiation':row['ssap_receipts'][0]['stdout']=row['ssap_receipts'][0]['stdout'].replace('negotiated_mtu=2042','negotiated_mtu=2041')
            elif kind=='state-chain':row['ssap_values'][2]['before']='00'*32
            else:wire.pop()
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate(row,matched)

    def test_long_wire_credit_counts_real_fragments_not_sdu_count(self):
        row,matched,wire=self.length_fixture()
        def fragmented(owner,direction,payload,item):
            packet=matched(owner,direction,payload,item)
            if len(payload)>249:packet['fragments']=[dict(record=i)for i in range(3)]
            return packet
        _,credit=corroborate(row,fragmented)
        self.assertFalse(wire);self.assertGreater(credit[0],166);self.assertEqual(credit[0],credit[1])

    def test_length_gate_opt_in_and_existing_guest_callers(self):
        args=SimpleNamespace(ssap_value_lengths_verify=True,channel_socket_verify=True)
        self.assertTrue(lengths_requested(args,passthrough=True))
        for flag in ['security_agent','ssap_owned_verify','ssap_update_delivery_verify','application_client_verify','channel_socket_close_prefix','channel_socket_boundaries']:
            bad=copy.copy(args);setattr(bad,flag,'numeric-approve'if flag=='security_agent'else True)
            with self.assertRaises(ValueError):lengths_requested(bad,passthrough=True)
        with self.assertRaises(ValueError):lengths_requested(args,passthrough=False)
        root=Path(__file__).resolve().parents[1]
        for name in ['ws73_target.py','ws73_target_control.py','ws73_target_init.sh']:
            self.assertIn('--ssap-value-lengths-verify',(root/name).read_text())
