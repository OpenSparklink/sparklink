import copy,hashlib,sys,unittest,json
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

    def test_live_UUID_result_rejects_zero_exit_remote_error_before_cleanup(self):
        # Receipt fixtures only. No Native/peer or successful ioctl substitute.
        from ws73_ssap_value import uuid_result
        row,_,_=self.uuid_fixture();item=row['ssap_values'][0]
        source=row['owners'][item['sender']];uuid=bytes.fromhex(item['property_uuid']);value=bytes.fromhex(item['value'])
        original=item['uuid_read_after'];uuid_result(original,source,2,uuid,value)
        for text in ('SsapUuidValue: path=/adapter0/link handle=16 success=false error=11 value=\n',
                     original['stdout'].splitlines()[0]+'\n',original['stdout']*2):
            with self.subTest(text=text),self.assertRaises(CaptureError):uuid_result(dict(original,stdout=text),source,2,uuid,value)

    def test_actual_unsupported_receive_interest_is_not_success(self):
        row,matched,wire=self.fixture();row['ssap_update_local_rejection_required']=True;row['unsupported_incoming']=[]
        for a,b in [(0,1),(1,0)]:row['unsupported_incoming'].append(dict(sender=a,target=b,handle=2,receipt=dict(args=['slctl','--adapter',f'/adapter{a}','ssap-receive',f'/adapter{a}/link','2','notify','10'],exit=1,stderr='peer has not advertised requested property update capabilities')))
        proof,credit=corroborate(row,matched);self.assertEqual(len(proof),8);self.assertEqual(credit,{0:24,1:24});self.assertFalse(wire)
        row,matched,_=self.fixture();row['ssap_update_local_rejection_required']=True;row['unsupported_incoming']=[]
        with self.assertRaises(CaptureError):corroborate(row,matched)

    def refusal_v2(self, error=None):
        # Invokes the actual gate command path. Explicit receipts are fixtures,
        # not a controller, daemon, SDK, clock or RF qualification.
        from ws73_ssap_value import execute_update_rejections, UPDATE_REJECTION_ERROR
        row, matched, wire = self.fixture(); calls = []; saved = []
        def command(args, timeout, **kwargs):
            calls.append((args, timeout, kwargs))
            return dict(args=args, exit=1, stderr=error or UPDATE_REJECTION_ERROR+'\n')
        run = SimpleNamespace(args=SimpleNamespace(slctl='/usr/bin/slctl'), command=command,
                              save=lambda: saved.append(copy.deepcopy(row)))
        local = [dict(discovered_handle=2), dict(discovered_handle=2)]
        return run, row, local, calls, saved, matched, wire

    def test_current_refusal_command_and_proof_preserve_original_budget(self):
        from ws73_ssap_value import execute_update_rejections, validate_update_rejections
        run, row, local, calls, saved, matched, wire = self.refusal_v2()
        execute_update_rejections(run, row, local)
        self.assertEqual(len(calls), 2); self.assertEqual(len(saved), 2)
        self.assertTrue(all(c[0][-2:] == ['notify', '5000'] and c[1] == 10 for c in calls))
        self.assertEqual(validate_update_rejections(row, expected_version=2)['wait_ms'], 5000)
        proof, credit = corroborate(row, matched)
        self.assertEqual(proof[0]['local_update_rejection']['version'], 2)
        self.assertEqual(credit, {0:24,1:24}); self.assertFalse(wire)

    def test_timeout_remains_failure_saved_once_without_retry(self):
        from ws73_ssap_value import execute_update_rejections
        run, row, local, calls, saved, _, _ = self.refusal_v2('error: channel: Connection timed out (os error 110)\n')
        with self.assertRaisesRegex(CaptureError, 'must explicitly reject'):
            execute_update_rejections(run, row, local)
        self.assertEqual(len(calls), 1); self.assertEqual(len(saved), 1)
        self.assertIn('timed out', saved[0]['unsupported_incoming'][0]['receipt']['stderr'])

    def test_current_refusal_rejects_relabelled_deadlines_wrong_owner_and_error(self):
        from ws73_ssap_value import execute_update_rejections, validate_update_rejections
        run, original, local, *_ = self.refusal_v2(); execute_update_rejections(run, original, local)
        for kind in ('legacy', 'boolean', 'unknown', 'budget', 'command', 'owner', 'timeout', 'mixed_error', 'success', 'duplicate'):
            row = copy.deepcopy(original); receipt = row['unsupported_incoming'][0]['receipt']
            if kind == 'legacy': row.pop('ssap_update_local_rejection_version')
            elif kind == 'boolean': row['ssap_update_local_rejection_version'] = True
            elif kind == 'unknown': row['ssap_update_local_rejection_version'] = 3
            elif kind == 'budget': row['ssap_update_local_rejection_wait_ms'] = 10
            elif kind == 'command': receipt['args'][-1] = '10'
            elif kind == 'owner': receipt['args'][2] = '/other'
            elif kind == 'timeout': receipt['stderr'] = 'error: channel: Connection timed out (os error 110)'
            elif kind == 'mixed_error': receipt['stderr'] += '\nConnection timed out'
            elif kind == 'success': receipt['exit'] = 0
            elif kind == 'duplicate': row['unsupported_incoming'][1] = row['unsupported_incoming'][0]
            with self.subTest(kind=kind), self.assertRaises(CaptureError):
                validate_update_rejections(row, expected_version=2)
        # A historical 10ms record is still v1, never current v2.
        row = copy.deepcopy(original); row.pop('ssap_update_local_rejection_version'); row.pop('ssap_update_local_rejection_wait_ms')
        for item in row['unsupported_incoming']: item['receipt']['args'][-1] = '10'
        self.assertEqual(validate_update_rejections(row)['version'], 1)
        with self.assertRaises(CaptureError): validate_update_rejections(row, expected_version=2)

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

class ReadLimitEvidence(unittest.TestCase):
    def test_current_terminal_requires_read_limits_while_legacy_is_not_upgraded(self):
        from ws73_ssap_value import corroborate_read_limits
        from ws73_target import run_exit_code
        original,matched,_=ActualValueEvidence().length_fixture();values,_=corroborate(original,matched)
        edges,matched,_=self.fixture();limits,_=corroborate_read_limits(edges,matched)
        gate=values[0]['length_gate'];gate.update(version=2,read_limits=limits)
        proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=[dict(phase=p,ssap_values=copy.deepcopy(values))for p in (0,1)])
        record=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,ordinary_channel_socket_acceptance=True,ssap_value_lengths_requested=True,ssap_value_lengths_acceptance=True,ssap_value_lengths_contract_version=2,qemu_args=['ws73.ssap_value_lengths=1'],channel_socket_corroboration=proof)
        self.assertTrue(valid_length_summary(proof,expected_version=2));self.assertEqual(run_exit_code(record),0)
        for kind in ['missing','partial','wrong-success','legacy']:
            bad=copy.deepcopy(proof);g=bad['proofs'][0]['ssap_values'][0]['length_gate']
            if kind=='missing':g.pop('read_limits')
            elif kind=='partial':g['read_limits'].pop()
            elif kind=='wrong-success':g['read_limits'][-1]['read_success']=True
            else:g.pop('version')
            self.assertFalse(valid_length_summary(bad,expected_version=2));self.assertEqual(run_exit_code(record|dict(channel_socket_corroboration=bad)),1)

    def fixture(self):
        # Reuse the existing independent discovery verdict fixture. This is
        # synthetic evidence for checker tests, not a real peer or kernel.
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        import test_ws73_ssap_discovery as discovery_fixture
        row=dict(owners=None,ssap_read_limits=[],ssap_values=[dict(start_wall_ns=100000)],ssap_receipts=[dict(args=['slctl'])]);packets=[]
        for number,size in enumerate([2038,2039,2040,2041,2042]):
            group,_,wire=discovery_fixture.DiscoveryEvidence().fixture();base=(number+1)*10000
            if row['owners']is None:row['owners']=group['owners']
            group.update(application_bytes=size,cases=[],start_wall_ns=base,end_wall_ns=base+8000)
            for d in group['ssap_discoveries']:
                d['receipt']['start_wall_ns']+=base;d['receipt']['end_wall_ns']+=base
            packets.extend((a,b,p,stamp+base)for a,b,p,stamp in wire)
            for target,r in enumerate(group['ssap_local_registrations']):
                value=(hashlib.sha256(f'{size}/{target}'.encode()).digest()*64)[:size]
                r.update(owner=group['owners'][target],value=value.hex(),registration=dict(exit=0,stdout='SsapLocalService: start=16 end=17 properties=17\n',args=['slctl','--adapter',f'/adapter{target}','ssap-register',r['service_uuid'],r['property_uuid'],'5','0',value.hex()]))
            for sender in (0,1):
                target=1-sender;r=group['ssap_local_registrations'][target];v=bytes.fromhex(r['value']);stamp=base+1000+sender*1000
                item=dict(sender=sender,target=target,handle=17,value=v.hex(),start_wall_ns=stamp,end_wall_ns=stamp+8)
                for name,request,limit in [('read',b'\x08\x03\x11\0\0',2040),('uuid_read',b'\x0a\x01\x10\0\xff\xff\0'+bytes.fromhex(r['property_uuid']),2038)]:
                    response=(b'\x09\x03'+v if name=='read'else b'\x0b\x03\x11\0'+v)if size<=limit else b'\x09\x0b\x10\0'
                    words=['ssap-read',f'/adapter{sender}/link','17']if name=='read'else['ssap-read-uuid',f'/adapter{sender}/link','16','65535',r['property_uuid']]
                    c=dict(exit=0 if size<=limit else 1,stderr='',stdout='',start_wall_ns=stamp+1,end_wall_ns=stamp+2,args=['slctl','--adapter',f'/adapter{sender}',*words])
                    if size<=limit:
                        c['stdout']=(f'SsapPeerValue: operation=ssap-read path=/adapter{sender}/link handle=17 value={v.hex()}\n'if name=='read'else f'SsapUuidValue: path=/adapter{sender}/link handle=17 success=true error=0 value={v.hex()}\nSsapUuidTrace: request={request.hex()} response={response.hex()}\n')
                    else:c['stderr']='peer read error 16'if name=='read'else'peer requires unsupported SSAP fragmentation'
                    item[name]=c
                    for a,b,pdu in [(sender,target,request),(target,sender,response)]:
                        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu;packets.extend([(a,'out',frame,stamp+1),(b,'in',frame,stamp+1)])
                item['local_check']=dict(exit=0,stdout=f'SsapLocalValue: handle=17 value={v.hex()}\n',args=['slctl','--adapter',f'/adapter{target}','ssap-local-read','17'],start_wall_ns=stamp+3,end_wall_ns=stamp+4);group['cases'].append(item)
            row['ssap_read_limits'].append(group)
        def match(owner,direction,payload,command):
            key=(row['owners'].index(owner),direction,payload,command['start_wall_ns'])
            if key not in packets:raise CaptureError('missing original paired limit packet')
            packets.remove(key);return dict(data=payload.hex())
        return row,match,packets

    def test_independent_read_uuid_limits_keep_raw_refusals_and_unchanged_values(self):
        from ws73_ssap_value import corroborate_read_limits
        row,match,packets=self.fixture();proof,credit=corroborate_read_limits(row,match)
        self.assertEqual(len(proof),10);self.assertEqual(sum(v['read_success']for v in proof),6);self.assertEqual(sum(v['uuid_success']for v in proof),2)
        self.assertEqual(credit,{0:110,1:110});self.assertFalse(packets)
        self.assertTrue(all(v['wire'][-1]['rx']['data'].endswith('090b1000') for v in proof if not v['uuid_success']))

    def test_missing_group_bad_handle_wrong_error_payload_and_caller_fail_closed(self):
        from ws73_ssap_value import corroborate_read_limits
        for kind in ['group','handle','error','payload','local','caller','registration','time','peer']:
            row,match,packets=self.fixture();c=row['ssap_read_limits'][-1]['cases'][0]
            if kind=='group':row['ssap_read_limits'].pop()
            elif kind=='handle':c['handle']=18
            elif kind=='error':c['read']['stderr']='peer protocol error 16'
            elif kind=='payload':c['value']='00'*2042
            elif kind=='local':c['local_check']['stdout']='fake successful local check'
            elif kind=='caller':c['read']['args'][3]='ssap-local-read'
            elif kind=='registration':row['ssap_read_limits'][-1]['ssap_local_registrations'][1]['registration']['exit']=1
            elif kind=='time':c['end_wall_ns']=1
            else:packets.pop()
            with self.subTest(kind=kind),self.assertRaises((CaptureError,ValueError)):corroborate_read_limits(row,match)

    def test_actual_sdk_boundary_receipts_are_bounded_and_cannot_replace_the_old_default(self):
        from ws73_application_client import ssap_receipt,application_environment
        from ws73_ssap_value import corroborate_read_limits
        row,_,packets=self.fixture();row.update(phase=0,ssap_language_clients=[])
        for group in row['ssap_read_limits']:
            for i,owner in enumerate(group['owners']):owner['owner'].update(index=i,generation=i+1)
        for group in row['ssap_read_limits']:
            size=group['application_bytes']
            if size>2040:continue
            for item in group['cases']:
                sender=item['sender'];owner=row['owners'][sender];api='c'if sender==0 else'python';path=owner['object']['path'];start=item['start_wall_ns']+5
                args=(['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py'])+['ssap',str(sender),str(sender+1),path,'ssap-read','17',item['value']]
                app=dict(api=api,position=sender,args=args,environment=application_environment(),exit=0,stderr='',stdout=json.dumps(dict(stage='ssap_start_barrier',api=api,client_closed=True))+'\n'+f'SsapPeerValue: operation=ssap-read path={path} handle=17 value={item["value"]}\n',credentials=dict(uids=[1000]*4,capabilities={k:'0'for k in ['CapEff','CapPrm','CapAmb','CapInh']}),ssap_operation='ssap-read',ssap_path=path,ssap_handle=17,ssap_expected=item['value'],start_wall_ns=start,end_wall_ns=start+1)
                item['sdk_read']=app;row['ssap_language_clients'].append(app);item['local_check'].update(start_wall_ns=start+2,end_wall_ns=start+3);item['end_wall_ns']=start+4
                for a,b,pdu in [(sender,1-sender,b'\x08\x03\x11\0\0'),(1-sender,sender,b'\x09\x03'+bytes.fromhex(item['value']))]:
                    frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu;packets.extend([(a,'out',frame,start),(b,'in',frame,start)])
                ssap_receipt(app,owner,expected_size=size)
                with self.assertRaises(CaptureError):ssap_receipt(app,owner)
        def match(owner,direction,payload,command):
            key=(row['owners'].index(owner),direction,payload,command['start_wall_ns'])
            if key not in packets:raise CaptureError('missing actual-format SDK endpoint')
            packets.remove(key);return dict(data=payload.hex())
        proof,credit=corroborate_read_limits(row,match,version=3);self.assertFalse(packets);self.assertEqual(credit,{0:116,1:116});self.assertEqual(sum(v['sdk']is not None for v in proof),6)
        broken=copy.deepcopy(row);broken['ssap_language_clients'].pop()
        with self.assertRaises(CaptureError):corroborate_read_limits(broken,match,version=3)

class FragmentWireEvidence(unittest.TestCase):
    """Fixed independent wire vectors/fixture packet lookup, not a real peer."""
    def fixture(self,kind='good'):
        source=dict(owner=0);destination=dict(owner=1)
        body=bytes(range(256))*7+bytes(range(253))
        self.assertEqual(len(body),2045)
        pdu=b'\x0d\x23'+body
        # Actual two-fragment WRITE_REQ headers, including partial vs immediate.
        first=b'\x8d\x28\x02\0'+body[:2038]
        last=b'\x8d\x22\x02\0'+body[2038:]
        if kind=='sequence':first=b'\x8d\x28\x03\0'+body[:2038]
        if kind=='operation':first=b'\x8d\x20\x02\0'+body[:2038]
        packets=[]
        for i,part in enumerate([first,last]):
            frame=b'\x0a\0'+len(part).to_bytes(2,'little')+part
            for owner,direction in [(source,'out'),(destination,'in')]:
                if kind=='missing-tx'and i==1 and direction=='out':continue
                if kind=='missing-rx'and i==1 and direction=='in':continue
                record=(len(packets)+1)*100 if kind!='order'else 0
                pieces=[dict(record=record+n,wall_ns=100,data=frame[p:p+254].hex())for n,p in enumerate(range(0,len(frame),254))]
                packets.append([owner,direction,frame,dict(data=frame.hex(),record=record,wall_ns=100,fragments=pieces)])
        def matched(owner,direction,payload,window):
            for n,(o,d,p,receipt)in enumerate(packets):
                if (o,d,p)==(owner,direction,payload):packets.pop(n);return receipt
            raise CaptureError('missing exact fixed fragment endpoint')
        return dict(ssap_value_lengths_version=4),source,destination,pdu,matched,packets

    def test_two_real_format_ssap_parts_are_distinct_from_nine_dli_fragments(self):
        from ws73_ssap_value import pair_wire,physical_sends
        row,a,b,pdu,matched,remaining=self.fixture();wire=pair_wire(row,matched,a,b,pdu,{})
        self.assertFalse(remaining);self.assertEqual(wire['logical_pdu'],pdu.hex())
        for side in ['tx','rx']:
            self.assertEqual(len(wire[side]['ssap_fragments']),2)
            self.assertEqual(physical_sends(wire[side]),10)
            parts=[bytes.fromhex(p['data'])[4:]for p in wire[side]['ssap_fragments']]
            self.assertEqual([p[:4]for p in parts],[b'\x8d\x28\x02\0',b'\x8d\x22\x02\0'])
            self.assertEqual(b'\x0d\x23'+b''.join(p[4:]for p in parts),pdu)

    def test_missing_endpoint_bad_sequence_operation_and_equal_capture_time_do_not_hide_order(self):
        from ws73_ssap_value import pair_wire
        for kind in ['sequence','operation','missing-tx','missing-rx','order']:
            row,a,b,pdu,matched,_=self.fixture(kind)
            with self.subTest(kind=kind),self.assertRaises(CaptureError):pair_wire(row,matched,a,b,pdu,{})

    def test_old_contract_and_unsupported_logical_size_cannot_claim_new_fragment_delivery(self):
        from ws73_ssap_value import pair_wire
        for version in [1,2,3]:
            row,a,b,pdu,matched,remaining=self.fixture();row['ssap_value_lengths_version']=version
            with self.assertRaises(CaptureError):pair_wire(row,matched,a,b,pdu,{})
            self.assertEqual(len(remaining),4)
        row,a,b,pdu,matched,_=self.fixture()
        with self.assertRaises(CaptureError):pair_wire(row,matched,a,b,pdu+b'\0',{})

    def test_terminal_fragment_shape_refuses_missing_parts_and_corrupted_raw_bytes(self):
        from ws73_ssap_value import pair_wire,valid_wire
        row,a,b,pdu,matched,_=self.fixture();wire=pair_wire(row,matched,a,b,pdu,{})
        self.assertTrue(valid_wire(wire))
        for kind in ['missing','header','logical','DLI','order']:
            bad=copy.deepcopy(wire)
            if kind=='missing':bad['rx']['ssap_fragments'].pop()
            elif kind=='header':bad['tx']['ssap_fragments'][0]['data']='00'
            elif kind=='logical':bad['logical_pdu']='0d23'+'00'*2045
            elif kind=='DLI':bad['rx']['ssap_fragments'][0]['fragments'][0]['data']='00'
            else:bad['rx']['ssap_fragments'][1]['fragments'][0]['record']=0
            with self.subTest(kind=kind):self.assertFalse(valid_wire(bad))
