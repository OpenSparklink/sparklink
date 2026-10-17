# SPDX-License-Identifier: GPL-2.0-only
"""Evidence parser fixtures, never real device acceptance."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_channel_socket import application_frames
from ws73_capture import CaptureError


def fixture(rounds=4,message_bytes=61,boundaries=False):
    credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0'))
    apps=[dict(role=role,exit=0,credentials=copy.deepcopy(credentials),stdout=f'NativeChannelOpened: role={role} rounds={rounds}\n') for role in ['initiator','peer']]
    for i in range(rounds):
        nonce=bytes([i+1])*16
        sequence=0x12345678+i*17
        body=b'SLKSOCK1'+nonce+sequence.to_bytes(4,'little')+bytes(1)+bytes(nonce[j%16]^((sequence+j)&255) for j in range(message_bytes-29))
        reply=bytearray(body);reply[28]=1
        apps[0]['stdout']+=f'NativeChannelSent: sequence={i} bytes={body.hex()}\nNativeChannelRoundTrip: sequence={i} elapsed_ms=10 bytes={reply.hex()}\n'
        apps[1]['stdout']+=f'NativeChannelReceived: sequence={i} bytes={body.hex()}\nNativeChannelReply: sequence={i} bytes={reply.hex()}\n'
    for role,app in enumerate(apps):
        if message_bytes!=61:app['stdout']+=f'NativeChannelMessageSize: bytes={message_bytes}\n'
        if boundaries:
            for i,length in enumerate([250,253,254,255]):
                body=b'SLKBOUND'+bytes([role*16+i+1])*(length-8)
                app['stdout']+=f'NativeChannelRejected: length={length} errno=90 bytes={body.hex()}\n'
    return dict(rounds=rounds,message_bytes=message_bytes,boundary_check=boundaries,applications=apps)


class ApplicationProof(unittest.TestCase):
    def test_twenty_bounded_rounds_and_invalid_record_counts(self):
        self.assertEqual(len(application_frames(fixture(20))[0]),20)
        for count in [0,21,-1,True,'20',None]:
            row=fixture();row['rounds']=count
            with self.subTest(count=count),self.assertRaises(CaptureError):application_frames(row)

    def test_maximum_message_and_original_boundary_rejections(self):
        from ws73_channel_socket import rejected_frames
        row=fixture(message_bytes=249,boundaries=True)
        self.assertEqual(len(application_frames(row)[0][0]),249)
        self.assertEqual(len(rejected_frames(row)),8)
        for kind in ['missing','errno','size','unexpected']:
            changed=copy.deepcopy(row)
            if kind=='missing':changed['applications'][0]['stdout']=changed['applications'][0]['stdout'].replace('NativeChannelRejected:','Missing:')
            if kind=='errno':changed['applications'][0]['stdout']=changed['applications'][0]['stdout'].replace('errno=90','errno=11')
            if kind=='size':changed['applications'][0]['stdout']=changed['applications'][0]['stdout'].replace('length=250','length=251')
            if kind=='unexpected':changed['boundary_check']=False
            with self.subTest(kind=kind),self.assertRaises(CaptureError):application_frames(changed)

    def test_required_actual_capabilities_reject_wrong_identity_and_missing_copy(self):
        row=fixture();row['channel_info_required']=True
        row['owners']=[dict(owner=dict(index=3,generation=7),object=dict(lifetime=9,handle=0)),dict(owner=dict(index=4,generation=8),object=dict(lifetime=10,handle=1))]
        for app,entry in zip(row['applications'],row['owners']):
            owner,obj=entry['owner'],entry['object']
            app['stdout']+=f"NativeChannelInfo: index={owner['index']} generation={owner['generation']} lifetime={obj['lifetime']} handle={obj['handle']} local=31 remote=31 pi=241 mtu=249 mps=249 mode=0 directions=3\nNativeChannelInfoCopy: partial=16 retry=1 unchanged=1\n"
        application_frames(row)
        for old,new in [('generation=7','generation=70'),('lifetime=9','lifetime=90'),('pi=241','pi=240'),('mtu=249','mtu=1'),('retry=1','retry=0'),('partial=16','partial=0')]:
            bad=copy.deepcopy(row);bad['applications'][0]['stdout']=bad['applications'][0]['stdout'].replace(old,new)
            with self.subTest(old=old),self.assertRaises(CaptureError):application_frames(bad)

    def test_original_two_application_messages(self):
        sent,replies=application_frames(fixture())
        self.assertEqual(len(sent),4);self.assertEqual(sent[0][28],0);self.assertEqual(replies[0][28],1)

    def test_missing_actual_reply_failed_process_privilege_or_duplicate(self):
        for kind in ['reply','failed','root','cap','duplicate','deadline','payload','wire-sequence']:
            row=fixture();a=row['applications'][0];b=row['applications'][1]
            if kind=='reply':b['stdout']=b['stdout'].replace('NativeChannelReply:','Missing:')
            if kind=='failed':a['exit']=1
            if kind=='root':a['credentials']['uids']=[0]*4
            if kind=='cap':a['credentials']['capabilities']['CapEff']='1'
            if kind=='duplicate':a['stdout']+=a['stdout'].splitlines()[1]+'\n'
            if kind=='deadline':a['stdout']=a['stdout'].replace('elapsed_ms=10','elapsed_ms=10000')
            if kind=='payload':b['stdout']=b['stdout'].replace('bytes=534c4b','bytes=004c4b')
            if kind=='wire-sequence':
                sent,_=application_frames(row);changed=bytearray(sent[1]);changed[24:28]=sent[0][24:28]
                sequence=int.from_bytes(changed[24:28],'little')
                for j in range(32):changed[29+j]=changed[8+j%16]^((sequence+j)&255)
                for app in row['applications']:
                    for reply in [0,1]:
                        old=bytearray(sent[1]);old[28]=reply;changed[28]=reply
                        app['stdout']=app['stdout'].replace(old.hex(),changed.hex())
            with self.subTest(kind=kind),self.assertRaises(CaptureError):application_frames(row)


class TxStatusObservationProof(unittest.TestCase):
    def row(self):
        row=fixture();row['tx_status_required']=True
        row['owners']=[dict(owner=dict(index=0,generation=1,buffers=[254,5,0,0]),object=dict(lifetime=3,handle=0)),dict(owner=dict(index=1,generation=2,buffers=[254,5,0,0]),object=dict(lifetime=4,handle=0))]
        for app in row['applications']:
            n=0 if app['role']=='initiator' else 1
            app['stdout']+=f'NativeTxStatus: stage=ready sequence=0 index={n} generation={n+1} lifetime={n+3} handle=0 maximum=254 capacity=5 outstanding=0 debt=0 peak=1 queued=0 limit=8 busy=0 bytes=0 offset=0 flags=0 blocks=0\n'
        return row
    def test_actual_identity_and_separate_budget_invariants(self):
        from ws73_channel_socket import tx_status_receipts
        row=self.row();self.assertEqual(len(tx_status_receipts(row)),2)
        for old,new in [('capacity=5','capacity=6'),('outstanding=0','outstanding=6'),('queued=0','queued=9'),('generation=1','generation=10'),('flags=0','flags=2'),('NativeTxStatus:','Other:')]:
            changed=copy.deepcopy(row)
            for app in changed['applications']:app['stdout']=app['stdout'].replace(old,new)
            with self.subTest(old=old),self.assertRaises(CaptureError):tx_status_receipts(changed)

    def test_e_u_budgets_remain_separate_and_fail_closed(self):
        from ws73_channel_socket import tx_status_receipts
        row=self.row()
        row['owners'][0]['owner']['buffers']=[1526,6,0,0]
        row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('maximum=254 capacity=5','maximum=1526 capacity=6')
        samples=tx_status_receipts(row)
        self.assertEqual([(v['maximum'],v['capacity']) for v in samples],[(1526,6),(254,5)])
        for bad in [None,[],[True,6,0,0],[0,6,0,0],[2048,6,0,0],[1526,0,0,0],[1526,256,0,0],[254,5,0,0]]:
            changed=copy.deepcopy(row);changed['owners'][0]['owner']['buffers']=bad
            with self.subTest(buffers=bad),self.assertRaises(CaptureError):tx_status_receipts(changed)
        changed=copy.deepcopy(row);changed['applications'][1]['stdout']=changed['applications'][1]['stdout'].replace('maximum=254 capacity=5','maximum=1526 capacity=6')
        with self.assertRaises(CaptureError):tx_status_receipts(changed)


class BurstPressureProof(unittest.TestCase):
    def pressure(self):
        row=fixture(rounds=16,message_bytes=2042)
        row['burst']=True
        source=next(a for a in row['applications'] if a['role']=='initiator')
        source['stdout']+='NativeBurstBlocked: sequence=8 poll_writable=0\nNativeBurstResumed: sequence=8\nNativeBurstPressure: eagain=1 not_writable=1 replies=16\n'
        return row
    def test_pressure_requires_full_original_app_receipts_and_resume(self):
        from ws73_channel_socket import burst_pressure_receipts
        row=self.pressure();self.assertEqual(len(application_frames(row)[0]),16)
        self.assertEqual(burst_pressure_receipts(row)['eagain'],1)
        for kind in ['no_eagain','poll','resume','counts','replies','flag']:
            changed=copy.deepcopy(row);source=next(a for a in changed['applications'] if a['role']=='initiator')
            if kind=='no_eagain':source['stdout']=source['stdout'].replace('NativeBurstBlocked','Wrong')
            if kind=='poll':source['stdout']=source['stdout'].replace('poll_writable=0','poll_writable=1')
            if kind=='resume':source['stdout']=source['stdout'].replace('NativeBurstResumed: sequence=8','NativeBurstResumed: sequence=9')
            if kind=='counts':source['stdout']=source['stdout'].replace('eagain=1','eagain=2')
            if kind=='replies':source['stdout']=source['stdout'].replace('NativeChannelRoundTrip:','LostRoundTrip:')
            if kind=='flag':changed['burst']=False
            with self.subTest(kind=kind),self.assertRaises(CaptureError):application_frames(changed)


class PrefixApplicationProof(unittest.TestCase):
    def prefix(self):
        row=fixture(rounds=1,message_bytes=2042)
        row.update(close_prefix=True,start_wall_ns=1,end_wall_ns=1000)
        source,peer=next(a for a in row['applications'] if a['role']=='initiator'),next(a for a in row['applications'] if a['role']=='peer')
        import re
        payload=re.findall(r'NativeChannelSent: sequence=0 bytes=([0-9a-f]+)',source['stdout'])[0]
        source['end_wall_ns']=30
        source['stdout']=f"NativeChannelLastClose: same_lifetime_reopen=NotSupported\nNativePrefixSent: bytes={payload}\nNativePrefixQueued: bytes={(b'SLKDROP1'+bytes(53)).hex()}\nNativePrefixClosed: start_wall_ns=20 end_wall_ns=21\n"
        return row
    def test_original_peer_validation_and_actual_close_required(self):
        from ws73_channel_socket import prefix_application_frames
        row=self.prefix();sent,replies,close=prefix_application_frames(row)
        self.assertEqual(len(sent[0]),2042);self.assertEqual(replies[0][28],1)
        self.assertEqual(close['start_wall_ns'],20)
        for kind in ['peer','close','source_receipt','credentials']:
            changed=copy.deepcopy(row)
            source=next(a for a in changed['applications'] if a['role']=='initiator');peer=next(a for a in changed['applications'] if a['role']=='peer')
            if kind=='peer':peer['stdout']=peer['stdout'].replace('NativeChannelReceived','Wrong')
            if kind=='close':source['stdout']=source['stdout'].replace('end_wall_ns=21','end_wall_ns=19')
            if kind=='source_receipt':source['stdout']+='NativeChannelRoundTrip: fake\n'
            if kind=='credentials':source['credentials']['uids']=[0]*4
            with self.subTest(kind=kind),self.assertRaises(CaptureError):prefix_application_frames(changed)


class IndependentUSBProof(unittest.TestCase):
    def fixture(self,rounds=4,boundaries=False,message_bytes=61):
        from ws73_channel_socket import application_frames
        phases=[];sdus=[];events=[]
        for n in range(2):
            row=fixture(rounds,message_bytes=message_bytes,boundaries=boundaries);row.update(phase=n,status='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING',start_wall_ns=n*100+1,end_wall_ns=n*100+90)
            owners=[dict(owner=dict(bus=1,device=2+i,index=i,generation=i+1,buffers=[254,5,0,0]),object=dict(generation=i+1,lifetime=1+n*2,handle=0)) for i in range(2)]
            if n:owners.reverse()
            row['owners']=owners
            # Distinct nonce in second phase, regenerate all matching receipts.
            if n:
                for app in row['applications']:
                    for i in range(rounds):
                        old=bytes([i+1])*16;new=bytes([i+127])*16
                        old_sequence=0x12345678+i*17;new_sequence=0xabcdef12+i*17
                        for reply in [0,1]:
                            a=b'SLKSOCK1'+old+old_sequence.to_bytes(4,'little')+bytes([reply])+bytes(old[j%16]^((old_sequence+j)&255) for j in range(message_bytes-29))
                            b=b'SLKSOCK1'+new+new_sequence.to_bytes(4,'little')+bytes([reply])+bytes(new[j%16]^((new_sequence+j)&255) for j in range(message_bytes-29))
                            app['stdout']=app['stdout'].replace(a.hex(),b.hex())
            phases.append(row)
            def leg(sender,receiver,data):
                for entry,direction in [(sender,'out'),(receiver,'in')]:
                    sdus.append(dict(bus=entry['owner']['bus'],device=entry['owner']['device'],direction=direction,handle=0,data=data.hex(),wall_ns=n*100+20))
            sent,replies=application_frames(row)
            for data,reply in zip(sent,replies):
                for sender,receiver,payload in [(owners[0],owners[1],data),(owners[1],owners[0],reply)]:
                    leg(sender,receiver,b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload)
            for sender,receiver in [owners,owners[::-1]]:
                leg(sender,receiver,bytes.fromhex('0200080001010400e2000000'))
                leg(sender,receiver,bytes.fromhex('0200100002010c00e20000000000f900f9000101'))
                events.append(dict(bus=1,device=sender['owner']['device'],event=9,params=(b'\0\0'+bytes([rounds+2])).hex(),wall_ns=n*100+30))
        return dict(channel_socket=phases),dict(native_events=events),sdus

    def test_independent_mtu_mps_current_wire_and_historical_scope(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture()
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            old=corroborate(run,capture)
            self.assertNotIn('independent_mtu_mps',old['proofs'][0])
        for row in run['channel_socket']:
            row.update(dtap_limits_version=1,cmtc_local_capability=dict(mtu=2042,mps=2047),channel_info_required=True,cmtc_identifier=0)
            for app,entry in zip(row['applications'],row['owners']):
                o,obj=entry['owner'],entry['object']
                app['stdout']+=f"NativeChannelInfo: index={o['index']} generation={o['generation']} lifetime={obj['lifetime']} handle=0 local=31 remote=31 pi=241 mtu=2042 mps=2047 mode=0 directions=3\nNativeChannelInfoCopy: partial=16 retry=1 unchanged=1\n"
        for packet in sdus:
            raw=bytearray.fromhex(packet['data'])
            if raw[0]==2:
                raw[5]=0
                if raw[4]==2:raw[14:16]=(2042).to_bytes(2,'little');raw[16:18]=(2047).to_bytes(2,'little')
                packet['data']=raw.hex()
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            result=corroborate(run,capture)
            self.assertTrue(all(p['independent_mtu_mps'] for p in result['proofs']))
        for kind in ['budget','wire','version','advertisement','missing-info']:
            changed,packets=copy.deepcopy(run),copy.deepcopy(sdus)
            row=changed['channel_socket'][0]
            if kind=='budget':row['applications'][0]['stdout']=row['applications'][0]['stdout'].replace('mps=2047','mps=2042')
            elif kind=='wire':
                for packet in packets:
                    raw=bytearray.fromhex(packet['data'])
                    if raw[:6]==bytes.fromhex('020010000200'):raw[16:18]=(2042).to_bytes(2,'little');packet['data']=raw.hex()
            elif kind=='version':row['dtap_limits_version']=True
            elif kind=='advertisement':row['cmtc_local_capability']['mps']=2042
            else:row['channel_info_required']=False
            with self.subTest(kind=kind),patch('ws73_channel_socket.reassemble_acb',return_value=packets),self.assertRaises(CaptureError):corroborate(changed,capture)

    def test_identifier_zero_is_current_and_historical_one_stays_scoped(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture()
        for row in run['channel_socket']:row['cmtc_identifier']=0
        for p in sdus:
            raw=bytearray.fromhex(p['data'])
            if raw[0]==2:raw[5]=0;p['data']=raw.hex()
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            self.assertEqual(corroborate(run,capture)['round_trips'],8)
            for row in run['channel_socket']:row['cmtc_identifier']=1
            with self.assertRaises(CaptureError):corroborate(run,capture)

    def test_long_requires_each_actual_fragment_and_physical_completion_count(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture(message_bytes=2042)
        for packet in sdus:
            raw=bytes.fromhex(packet['data'])
            if packet['direction']=='out' and len(raw)>254:
                parts=[raw[i:i+254] for i in range(0,len(raw),254)]
                packet['fragments']=[dict(data=part.hex(),boundary=1 if i==0 else 3 if i==len(parts)-1 else 2) for i,part in enumerate(parts)]
        for event in capture['native_events']:event['params']='000026' # 4*9 business fragments +2 CMTC
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            self.assertTrue(corroborate(run,capture)['long_pdu_acceptance'])
        for kind in ['missing_fragment','wrong_pb','wrong_nocp','missing_peer']:
            packets,events=copy.deepcopy(sdus),copy.deepcopy(capture)
            if kind=='missing_fragment':packets[0]['fragments']=[]
            if kind=='wrong_pb':packets[0]['fragments'][0]['boundary']=0
            if kind=='wrong_nocp':events['native_events'][0]['params']='000025'
            if kind=='missing_peer':packets.pop(1)
            with self.subTest(kind=kind),patch('ws73_channel_socket.reassemble_acb',return_value=packets),self.assertRaises(CaptureError):corroborate(run,events)

    def test_boundary_rejections_require_no_matching_usb_data(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate,rejected_frames
        run,capture,sdus=self.fixture(boundaries=True)
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            self.assertEqual(corroborate(run,capture)['application_boundary_rejections'],16)
            raw=rejected_frames(run['channel_socket'][0])[0]
            sdus.append(dict(bus=1,device=2,handle=0,direction='out',wall_ns=20,data=raw.hex()))
            with self.assertRaises(CaptureError):corroborate(run,capture)

    def test_real_ssap_receipts_require_both_usb_ends_and_additional_credit(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture()
        for row in run['channel_socket']:
            row['ssap_exchange_required']=True;row['session_start_wall_ns']=row['start_wall_ns'];row['ssap_receipts']=[]
            for owner in row['owners']:
                o,obj=owner['owner'],owner['object'];request='0203f9000102';response='0303f9000102'
                row['ssap_receipts'].append(dict(exit=0,stdout=f"SsapExchangeInfo: index={o['index']} generation={o['generation']} lifetime={obj['lifetime']} handle={obj['handle']} local_mtu=249 negotiated_mtu=249 request={request} peer_reply={response} peer_request={request} response={response}\n"))
                receiver=next(e for e in row['owners'] if e!=owner)['owner']
                for payload in [request,response]:
                    frame='0a000600'+payload
                    sdus.extend([dict(bus=o['bus'],device=o['device'],handle=0,direction='out',wall_ns=row['start_wall_ns']+1,data=frame),dict(bus=receiver['bus'],device=receiver['device'],handle=0,direction='in',wall_ns=row['start_wall_ns']+2,data=frame)])
                event=next(e for e in capture['native_events'] if e['device']==o['device'] and row['start_wall_ns']<=e['wall_ns']<=row['end_wall_ns'])
                event['params']='000008'
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            proof=corroborate(run,capture);self.assertEqual(len(proof['proofs'][0]['ssap_exchange']),2)
            self.assertEqual(len(proof['proofs'][0]['legs']),8)
            self.assertTrue(all('sequence' in leg and leg['tx']['data'].startswith('1f00') for leg in proof['proofs'][0]['legs']))
            bad=copy.deepcopy(run);bad['channel_socket'][0]['ssap_receipts'][0]['stdout']=bad['channel_socket'][0]['ssap_receipts'][0]['stdout'].replace('peer_reply=0303','peer_reply=0302')
            with self.assertRaises(CaptureError):corroborate(bad,capture)
        missing=[p for p in sdus if not (p['data'].startswith('0a') and p['direction']=='in' and p['device']==2)]
        with patch('ws73_channel_socket.reassemble_acb',return_value=missing),self.assertRaises(CaptureError):corroborate(run,capture)

    def test_twenty_rounds_require_twenty_two_real_completions_per_endpoint(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture(20)
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            self.assertEqual(corroborate(run,capture)['round_trips'],40)
            capture['native_events'][0]['params']='000015'
            with self.assertRaises(CaptureError):corroborate(run,capture)

    def test_both_usb_ends_capabilities_and_actual_credit(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        run,capture,sdus=self.fixture()
        with patch('ws73_channel_socket.reassemble_acb',return_value=sdus):
            self.assertEqual(corroborate(run,capture)['round_trips'],8)

    def test_missing_opposite_rx_bad_capability_or_invented_completion(self):
        from unittest.mock import patch
        from ws73_channel_socket import corroborate
        for kind in ['rx','cap','credit','handle','generation']:
            run,capture,sdus=self.fixture()
            if kind=='rx':sdus.pop(1)
            if kind=='cap':sdus[-1]['data']='0200080001010400e2000000'
            if kind=='credit':capture['native_events'][0]['params']='000005'
            if kind=='handle':capture['native_events'][0]['params']='010006'
            if kind=='generation':run['channel_socket'][0]['owners'][0]['object']['generation']=9
            with self.subTest(kind=kind),patch('ws73_channel_socket.reassemble_acb',return_value=sdus),self.assertRaises(CaptureError):
                corroborate(run,capture)


class SealedRealEvidence(unittest.TestCase):
    def test_checked_in_default_socket_case_recomputes_with_limited_scope(self):
        import json
        from ws73_channel_socket import corroborate
        from ws73_capture import corroborate_passthrough, reassemble_acb
        from ws73_connection_control import corroborate as connection
        from ws73_connection_objects import corroborate as objects
        path=Path(__file__).resolve().parents[2]/'docs/evidence/ws73-ordinary-channel-socket-20261013.json'
        evidence=json.loads(path.read_text());case=evidence['cases'][0]
        run=case['raw_control_record'];capture=case['decoded_capture']
        self.assertEqual(corroborate(run,capture),case['independently_derived']['channel'])
        # Preserve the historical captured 0x13 bytes and limited identity;
        # this is not a current management-request or new RF qualification.
        links=connection(run,capture,expected_disconnect_reason=0x13);self.assertEqual(links,case['independently_derived']['connection'])
        self.assertEqual(objects(run,capture,links),case['independently_derived']['objects'])
        self.assertEqual(len(corroborate_passthrough(run,capture)),22)
        self.assertEqual(len(reassemble_acb(capture)),48)
        self.assertEqual(evidence['actual_data_round_trips'],8)
        self.assertEqual(case['expected_taint'],0)
        for field in ['full_goal_complete','long_boundary_credit_exhaustion_acceptance','four_device_data_acceptance',
                      'automatic_hardware_recovery_acceptance','natural_fault_root_cause_closed',
                      'all_close_dup_linkdown_races_acceptance','physical_unplug_acceptance','ssap_acceptance']:
            self.assertIs(evidence[field],False)
        altered=copy.deepcopy(capture)
        packet=next(p for p in altered['acb_packets'] if p['direction']=='out' and p['data'].startswith('1f'))
        packet['data']=packet['data'][:-2]+('00' if packet['data'][-2:]!='00' else '01')
        with self.assertRaises(CaptureError):corroborate(run,altered)

    def test_checked_in_twenty_round_case_recomputes(self):
        import json
        from ws73_channel_socket import corroborate
        from ws73_capture import reassemble_acb
        path=Path(__file__).resolve().parents[2]/'docs/evidence/ws73-ordinary-channel-repeat-20261013.json'
        evidence=json.loads(path.read_text());case=evidence['cases'][0]
        proof=corroborate(case['raw_control_record'],case['decoded_capture'])
        self.assertEqual(proof,case['independently_derived']['channel'])
        self.assertEqual(proof['round_trips'],40)
        self.assertEqual(len(reassemble_acb(case['decoded_capture'])),176)
        self.assertEqual(evidence['real_nocp_packet_count'],88)
        self.assertIs(evidence['full_goal_complete'],False)


class BenchmarkApplicationReports(unittest.TestCase):
    """Synthetic report mutations only, never measured performance or RF."""
    @staticmethod
    def reports():
        reports=[]
        for responder in [False,True]:
            rows=[]
            for i in range(4):
                nonce=bytes([i+1])*16;seq=0x730100+i
                frame=b'SLKSOCK1'+nonce+seq.to_bytes(4,'little')+b'\x01'+bytes(nonce[j%16]^((seq+j)&255) for j in range(32))
                timestamps=[i*100+n for n in range(6)]
                fields=['planned_ns','read_ns','validated_ns','first_syscall_ns','syscall_ns','admitted_ns'] if responder else [
                    'planned_ns','first_syscall_ns','syscall_ns','admitted_ns','read_ns','validated_ns']
                rows.append(dict(zip(fields,timestamps),index=i,send_attempts=1,would_block=0,errno=None,timed_out=False,frame_hex=frame.hex()))
            reports.append(dict(schema_version=1,status='MEASURED_NOT_QUALIFIED',performance_qualified=False,
                workload='ping-pong-one-outstanding',responder=responder,config=dict(count=4,bytes=61),
                clock='process-local-Rust-Instant-relative-nanoseconds',rtt_definition='successful send syscall entry to validated reply, same initiator clock',
                percentile_method='nearest-rank;success-only;p99.9 requires10000 successes',elapsed_ns=400,unmeasured=['fixture-only-no-provenance'],
                channel_identity=dict(controller=int(responder),generation=1,lifetime=1,handle=0,mtu=2042,mps=2047,local_tcid=31,remote_tcid=31,pi=241,mode=0,directions=3),
                attempted=4,admitted=4,validated=4,timed_out=0,unattempted=0,error=None,samples=rows,
                success_only_rtt=None if responder else dict(successful_samples=4,min_ns=3,p50_ns=3,p90_ns=3,p95_ns=3,p99_ns=3,p999_ns=None,max_ns=3)))
        return reports

    def test_matching_reports_do_not_publish_performance_qualification(self):
        from ws73_channel_socket import benchmark_application_reports
        result=benchmark_application_reports(*self.reports())
        self.assertEqual(result['messages'],4);self.assertFalse(result['performance_qualified'])

    def test_missing_stale_inconsistent_or_corrupt_measurements_fail_closed(self):
        from ws73_channel_socket import benchmark_application_reports
        for kind in ['missing-peer','incomplete','qualified','clock','origin','unit-method','empty','count','count-bool',
                     'missing-row','duplicate','payload','nonce','timeout','lost-timeout','errno','order','batch-origin',
                     'elapsed','percentile','small-p999','peer-frame','same-controller','stale-lifetime','attempts','bad-capability',
                     'missing-error','missing-errno','float-percentile','float-peer-config','late-row','late-total']:
            source,peer=self.reports();row=source['samples'][1]
            if kind=='missing-peer':peer=None
            if kind=='incomplete':source['status']='INCOMPLETE'
            if kind=='qualified':source['performance_qualified']=True
            if kind=='clock':peer['clock']='guest-wall-clock-microseconds'
            if kind=='origin':source['rtt_definition']='batch-start'
            if kind=='unit-method':source['percentile_method']='milliseconds'
            if kind=='empty':source['samples']=[]
            if kind=='count':source['admitted']=3
            if kind=='count-bool':source['config']['count']=True
            if kind=='missing-row':peer['samples'].pop()
            if kind=='duplicate':row['index']=0
            if kind=='payload':row['frame_hex']=row['frame_hex'][:-2]+'00'
            if kind=='nonce':row['frame_hex']=source['samples'][0]['frame_hex']
            if kind=='timeout':row['timed_out']=True
            if kind=='lost-timeout':source['timed_out']=1
            if kind=='errno':row['errno']=11
            if kind=='order':row['validated_ns']=row['syscall_ns']-1
            if kind=='batch-origin':row['planned_ns']=0
            if kind=='elapsed':source['elapsed_ns']=1
            if kind=='percentile':source['success_only_rtt']['p99_ns']=99
            if kind=='small-p999':source['success_only_rtt']['p999_ns']=3
            if kind=='peer-frame':peer['samples']=list(reversed(peer['samples']))
            if kind=='same-controller':peer['channel_identity']['controller']=0
            if kind=='stale-lifetime':source['channel_identity']['lifetime']=0
            if kind=='attempts':row['send_attempts']=2
            if kind=='bad-capability':source['channel_identity']['mps']=20
            if kind=='missing-error':source.pop('error')
            if kind=='missing-errno':row.pop('errno')
            if kind=='float-percentile':source['success_only_rtt']['p99_ns']=3.0
            if kind=='float-peer-config':peer['config']['count']=4.0
            if kind=='late-row':row['late']=True
            if kind=='late-total':source['late']=1
            with self.subTest(kind=kind),self.assertRaises(CaptureError):benchmark_application_reports(source,peer)


class SlktestEntryMigration(unittest.TestCase):
    def test_one_current_argument_builder_preserves_role_route_and_exercise(self):
        from ws73_channel_socket import check_arguments
        entry=dict(owner=dict(path='/adapter'),object=dict(path='/adapter/connection'))
        args=check_arguments('/bin/slktest',entry,False,16,2042,'burst',(24576,24577,29441),True)
        self.assertEqual(args,['/bin/slktest','--adapter','/adapter','channel','ping','/adapter/connection','--check','--count','16','--bytes','2042','--exercise','burst','--source-port','24576','--destination-port','24577','--aid','29441','--hold'])
        self.assertEqual(check_arguments('/bin/slktest',entry,True,4,61)[3:5],['channel','peer'])

    def test_protected_check_uses_one_explicit_requirement_without_plain_fallback(self):
        from ws73_channel_socket import check_arguments
        entry=dict(owner=dict(path='/adapter'),object=dict(path='/adapter/connection'))
        for requirement in [1,2]:
            args=check_arguments('/bin/slktest',entry,False,4,61,security=requirement)
            self.assertEqual(args[-2:],['--security',str(requirement)])
            with self.assertRaises(CaptureError):
                check_arguments('/bin/slktest',entry,False,4,61,route=(1,2,3),security=requirement)
        with self.assertRaises(CaptureError):check_arguments('/bin/slktest',entry,False,4,61,security=3)

    def test_metadata_cannot_substitute_management_binary_missing_or_mixed_artifacts(self):
        from ws73_channel_socket import validate_application_tools
        good=dict(path='/usr/libexec/opensparklink/native-lab/0123456789ab/slktest',sha256='a'*64)
        row=dict(channel_socket=[dict(application_tool=good)])
        self.assertEqual(validate_application_tools(row),good)
        for bad in [dict(channel_socket=[{}]),dict(channel_socket=[dict(application_tool=dict(good,path='/bin/slctl'))]),
                    dict(channel_socket=[dict(application_tool=good),dict(application_tool=dict(good,sha256='b'*64))])]:
            with self.assertRaises(CaptureError):validate_application_tools(bad)


class CurrentApplicationArguments(unittest.TestCase):
    def test_new_tool_receipts_require_exact_current_argv(self):
        from ws73_channel_socket import check_arguments
        row=fixture()
        row['application_tool']=dict(path='/bin/slktest',sha256='a'*64)
        row['owners']=[dict(owner=dict(path='/org/sparklink/slk0_g1'),object=dict(path='/link0')),dict(owner=dict(path='/org/sparklink/slk1_g2'),object=dict(path='/link1'))]
        for app in row['applications']:
            peer=app['role']=='peer';entry=row['owners'][int(peer)]
            app['args']=check_arguments('/bin/slktest',entry,peer,4,61)
        application_frames(row)
        for kind in ('oldtool','count','direction','missing'):
            bad=copy.deepcopy(row);args=bad['applications'][0]['args']
            if kind=='oldtool':args[0]='/bin/slctl'
            if kind=='count':args[args.index('--count')+1]='5'
            if kind=='direction':args[4]='peer'
            if kind=='missing':bad['applications'][0].pop('args')
            with self.subTest(kind=kind),self.assertRaises(CaptureError):application_frames(bad)


class MessageSecurityReceipts(unittest.TestCase):
    @staticmethod
    def receipt_fixture():
        from ws73_channel_socket import message_security_receipts
        row=fixture();row.update(message_security_required=True,security_requirement=1,
            owners=[dict(owner=dict(index=1,generation=7),object=dict(lifetime=9,handle=0)),
                    dict(owner=dict(index=2,generation=8),object=dict(lifetime=10,handle=1))])
        for app,entry in zip(row['applications'],row['owners']):
            o,c=entry['owner'],entry['object']
            for n in range(4):
                app['stdout']+=f"NativeMessageSecurity: sequence={n} index={o['index']} generation={o['generation']} lifetime={c['lifetime']} handle={c['handle']} local=31 remote=31 pi=241 security=1 epoch=2 flags=3\n"
            raw=b'SLKCMREJ'+bytes([o['index']])*53
            app['stdout']+=f"NativeControlRejected: errno=95 bytes={raw.hex()}\n"
        return row

    def test_original_scope_mechanism_counts_and_refusals_are_required(self):
        from ws73_channel_socket import message_security_receipts
        row=self.receipt_fixture()
        good,rejected=message_security_receipts(row)
        self.assertEqual((len(good),len(rejected)),(8,2))
        for old,new in [('generation=7','generation=70'),('lifetime=9','lifetime=90'),
            ('flags=3','flags=1'),('flags=3','flags=0'),('epoch=2','epoch=0'),
            ('security=1','security=0'),('security=1','security=3'),('pi=241','pi=242'),
            ('sequence=1','sequence=0'),('errno=95','errno=0'),
            ('NativeMessageSecurity:','Missing:'),('NativeControlRejected:','Missing:')]:
            bad=copy.deepcopy(row);bad['applications'][0]['stdout']=bad['applications'][0]['stdout'].replace(old,new)
            with self.subTest(old=old,new=new),self.assertRaises(CaptureError):message_security_receipts(bad)
        # The old source has no receipt flag and gains no new qualification.
        self.assertEqual(message_security_receipts(fixture()),([],[]))


class SendConstraintReceipts(unittest.TestCase):
    def test_replies_pin_original_context_and_require_all_refusals(self):
        from ws73_channel_socket import send_constraint_receipts
        row=MessageSecurityReceipts.receipt_fixture();row['tx_constraint_required']=True
        peer=row['applications'][1]
        for n in range(4):
            peer['stdout']+=f'NativeConstrainedReply: sequence={n} epoch=2 minimum=1 deadline_ns=123456\n'
            for i,kind in enumerate(['epoch','lifetime','deadline']):
                raw=b'SLKINTRE'+bytes([n*3+i+1])*53
                peer['stdout']+=f'NativeConstraintRejected: sequence={n} kind={kind} errno={110 if kind=="deadline" else 13} bytes={raw.hex()}\n'
        receipts,rejected=send_constraint_receipts(row);self.assertEqual((len(receipts),len(rejected)),(4,12))
        for old,new in [('NativeConstrainedReply: sequence=0 epoch=2','NativeConstrainedReply: sequence=0 epoch=9'),('minimum=1','minimum=0'),('deadline_ns=123456','deadline_ns=0'),('errno=13','errno=0'),('errno=110','errno=11'),('NativeConstrainedReply:','Missing:'),('NativeConstraintRejected:','Missing:'),('kind=lifetime','kind=epoch')]:
            bad=copy.deepcopy(row);bad['applications'][1]['stdout']=bad['applications'][1]['stdout'].replace(old,new)
            with self.subTest(old=old),self.assertRaises(CaptureError):send_constraint_receipts(bad)
        self.assertEqual(send_constraint_receipts(fixture()),([],[]))
