"""Pure witness/wire verifier controls with explicit synthetic records.

No daemon, kernel, USB or actual application delivery qualification here.
"""
import json
import unittest
from ws73_capture import CaptureError
from ws73_security_agent import wire,witness
from ws73_security_capabilities import OFFER


def fixture(mode='approve'):
    objects=[]
    for n in range(2):
        objects.append(dict(owner=dict(bus=1,device=n+2),object=dict(path=f'/org/sparklink/slk{n}_g7/peer_t00_01020304050{n}/link_000000000000000d',generation=7,lifetime=13,handle=1,role=n,address_type=0,address=f'01:02:03:04:05:0{n}')))
    phase=dict(typed_objects=objects)
    status='Uid:\t1000\t1000\t1000\t1000\nGid:\t1002\t1002\t1002\t1002\n'+''.join(f'{k}:\t0000000000000000\n' for k in ['CapEff','CapPrm','CapInh','CapAmb'])
    daemon=dict(owner=':1.10',pid=12,uid=0)
    identity=dict(stage='probe_identity',daemon_owner=daemon['owner'],daemon_pid=12,process_status=status,missing_agent_refusals=2,unknown_registration_refusals=2,connections=[v['object']['path'] for v in objects],infos=[[v['object'][k] for k in ['generation','lifetime','handle','role','address_type','address']]+[True,True] for v in objects])
    events=[identity]
    for entry in objects:
        obj=entry['object'];path=obj['path']
        events.append(dict(stage='allocated',path=path,request_id=1,generation=7,lifetime=13,deadline_monotonic_ns=5000000000,timeout_ms=5000,start_wall_ns=11,wall_ns=12,unknown_begin_refused=True))
        events.append(dict(stage='agent_callback',daemon_owner=':1.10',wall_ns=20,prompt=[path,1,7,13,1,obj['role'],0,obj['address'],'sdk111-no-mitm',5000000000]))
        if mode=='caller-exit':events.append(dict(stage='caller_loss_cleanup',path=path,old_request=1,new_request=2,old_result_access_denied=True,fresh_cancelled=True))
        else:events.append(dict(stage='policy_result',path=path,request_id=1,generation=7,lifetime=13,deadline_monotonic_ns=5000000000,phase={'approve':4,'reject':5,'timeout':7,'cancel':6,'agent-exit':10}[mode],error=0 if mode=='approve' else -125,agent_approved=mode=='approve',native_admitted=mode=='approve',kernel_state=9 if mode=='approve' else 0,kernel_error=0,kernel_flags=0,kernel_status=0,cleanup_error=0))
    events.append(dict(stage='probe_complete',wall_ns=99,status='PENDING_INDEPENDENT_USB_AND_BUSINESS_CORROBORATION',authenticated_identity=False,bond=False,physical_recovery_acceptance=False))
    row=dict(mode=mode,status='PENDING_USB_AND_APPLICATION_CORROBORATION',start_wall_ns=10,end_wall_ns=100,events=events,command=dict(exit=0,stdout='\n'.join(json.dumps(v) for v in events)))
    capture=dict(commands=[],complete=[],native_events=[])
    if mode=='approve':
        indices=[0x134,0x135,0x136,0x137,0x138,0x139,0x13a,0x141,0x142]
        for i,index in enumerate(indices):
            n=0 if index in [0x134,0x136,0x139,0x141] else 1
            payload=OFFER if index in [0x134,0x135] else bytes([i+1])*(70 if index==0x136 else 64 if index==0x137 else 16)
            if index==0x136:payload=bytes([16,1,2,2,2,2])+bytes([i+1])*64
            prefix=b'\1\0'+index.to_bytes(2,'little');raw=prefix+bytes([len(payload)])+payload
            capture['commands'].append(dict(bus=1,device=n+2,opcode=0x1812,params=raw.hex(),completion=True,wall_ns=30+i*3,record=i))
            capture['complete'].append(dict(bus=1,device=n+2,opcode=0x1812,status=0,value=prefix.hex(),wall_ns=31+i*3,record=i+50))
            capture['native_events'].append(dict(bus=1,device=(1-n)+2,event=0x14,params=raw.hex(),wall_ns=32+i*3,record=i+100))
        for n,opcode in enumerate([0x1c03,0x1c05]):
            params=b'\1\0'+b'\x07'*16+(b'\1\1\0' if n==0 else b'\1\1')
            capture['commands'].append(dict(bus=1,device=n+2,opcode=opcode,params=params.hex(),completion=True,wall_ns=80+n*3,record=200+n))
            capture['native_events'] += [dict(bus=1,device=n+2,event=1,params=(opcode.to_bytes(2,'little')+b'\1\0').hex(),wall_ns=81+n*3,record=210+n),dict(bus=1,device=n+2,event=0x11,params='00010001',wall_ns=82+n*3,record=220+n)]
        capture['native_events'].append(dict(bus=1,device=3,event=0xe,params='0100',wall_ns=82,record=230))
    return row,phase,daemon,capture


class AgentEvidenceTests(unittest.TestCase):
    def test_exact_explicit_synthetic_witness_is_not_hardware_qualification(self):
        row,phase,daemon,capture=fixture()
        witness(row,phase,daemon)
        proof=wire(row,phase,capture)
        self.assertEqual(proof['opposite_receipts'],9)
        self.assertTrue(all(v['key_redacted'] for v in proof['installations']))
        self.assertNotIn('07070707',json.dumps(proof))

    def test_missing_peer_rx_cannot_pass_from_completes(self):
        row,phase,_,capture=fixture();capture['native_events']=[v for v in capture['native_events'] if not (v['device']==3 and v['event']==0x14)]
        with self.assertRaises(CaptureError):wire(row,phase,capture)

    def test_changed_peer_payload_is_rejected(self):
        row,phase,_,capture=fixture();event=next(v for v in capture['native_events'] if v['event']==0x14);event['params']=event['params'][:-2]+'fe'
        with self.assertRaises(CaptureError):wire(row,phase,capture)

    def test_install_acceptance_does_not_replace_0011(self):
        row,phase,_,capture=fixture();capture['native_events']=[v for v in capture['native_events'] if v['event']!=0x11]
        with self.assertRaises(CaptureError):wire(row,phase,capture)

    def test_two_install_keys_must_match_but_never_enter_proof(self):
        row,phase,_,capture=fixture();cmd=capture['commands'][-1];cmd['params']=cmd['params'][:4]+'08'+cmd['params'][6:]
        with self.assertRaises(CaptureError):wire(row,phase,capture)

    def test_sealed_transcript_cannot_be_mutated(self):
        row,phase,daemon,_=fixture();row['events'][1]['request_id']=2
        with self.assertRaises(CaptureError):witness(row,phase,daemon)

    def test_daemon_identity_and_privilege_mismatch(self):
        row,phase,daemon,_=fixture();daemon['pid']=99
        with self.assertRaises(CaptureError):witness(row,phase,daemon)

    def test_each_pre_admission_negative_mode_must_have_no_security_wire(self):
        for mode in ['reject','timeout','cancel','agent-exit','caller-exit']:
            with self.subTest(mode=mode):
                row,phase,daemon,capture=fixture(mode);witness(row,phase,daemon);wire(row,phase,capture)
                capture['commands'].append(dict(bus=1,device=2,opcode=0x1812,wall_ns=50))
                with self.assertRaises(CaptureError):wire(row,phase,capture)

    def test_missing_stage_and_unknown_terminal_not_pass(self):
        for change in ['missing','phase']:
            row,phase,daemon,_=fixture()
            if change=='missing':row['events'].pop(1)
            else:next(v for v in row['events'] if v['stage']=='policy_result')['phase']=8
            row['command']['stdout']='\n'.join(json.dumps(v) for v in row['events'])
            with self.assertRaises(CaptureError):witness(row,phase,daemon)


if __name__=='__main__':unittest.main()
