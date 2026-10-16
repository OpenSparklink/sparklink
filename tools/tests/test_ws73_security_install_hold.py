"""Synthetic coordinator/witness negative controls; never real USB qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ws73_diagnostic_hold import PROPERTIES, write_marker
from ws73_security_install_hold import InstallCoordinator, SELECTORS, QEMU_SHA256
from ws73_security_agent import witness,wire
from ws73_target import run_exit_code
from test_ws73_security_agent import fixture


class Monitor:
    def __init__(self):
        self.devices=[dict(zip(PROPERTIES,[False,False,0,0,0,0,False,0])) for _ in range(2)]
        for state in self.devices:
            state.update(dict.fromkeys(SELECTORS,0));state.update(attached=True)
            state.update(dict.fromkeys(['host-reset','kernel-driver-detach','guest-reset','guest-resets-all','test-enumeration-reset-once'],False))
        self.mutations=[]
    def execute(self,command,args):
        i=int(args['path'][-1]);key=args['property'];state=self.devices[i]
        if command=='qom-get':return state[key]
        self.mutations.append((i,key,args['value']))
        if key=='test-runtime-install-g':state[SELECTORS[0]]=0x1c03
        elif key==PROPERTIES[0]:state[key]=True
        elif key=='test-runtime-in-release':state.update({PROPERTIES[1]:False,PROPERTIES[3]:1})
        else:raise AssertionError('unexpected physical mutation')


def install_fixture():
    row,phase,daemon,cap=fixture();row['mode']='install-cancel'
    selected=phase['typed_objects'][0]['object']['path']
    result=next(e for e in row['events'] if e['stage']=='policy_result' and e['path']==selected)
    result.update(phase=6,kernel_state=6,error=-125,kernel_error=-125,kernel_flags=7)
    raw=[result[k] for k in ['request_id','generation','lifetime','phase','error','deadline_monotonic_ns','agent_approved','native_admitted','kernel_state','kernel_error','kernel_flags','kernel_status','cleanup_error']]
    before=raw.copy();before[3]=3;before[4]=0;before[8]=3;before[9]=0
    row['events']+= [dict(stage='install_barrier',request={},ack={}),dict(stage='install_barrier',request={},ack={}),dict(stage='install_before_cancel',path=selected,raw=before,wall_ns=80),dict(stage='install_cancelled',path=selected,raw=raw,wall_ns=81),dict(stage='install_terminal_stable',path=selected,raw=raw.copy(),wall_ns=95)]
    row['command']['stdout']='\n'.join(json.dumps(e) for e in row['events'])
    return row,phase,daemon,cap


class InstallationHoldTests(unittest.TestCase):
    def test_both_phases_reuse_generic_hold_without_touching_peer(self):
        with tempfile.TemporaryDirectory() as tmp,patch('ws73_security_install_hold.validate_qemu'):
            record={};gate=InstallCoordinator(tmp,record,'not-a-real-qemu');m=Monitor()
            for n in range(2):
                folder=Path(tmp)/'security-install-hold'/f'phase-{n}';folder.mkdir(parents=True)
                write_marker(folder/'selection.json',dict(phase=n,index=n,opcode=0x1c03,generation=7,lifetime=n+1,handle=0,path=f'/original/{n}'))
                write_marker(folder/'hold-arm_ready.json',dict(hold_phase='arm_ready',wall_ns=1))
                gate.poll(m,lambda i:dict(bus=1,address=i+2));self.assertEqual(m.devices[n][SELECTORS[0]],0x1c03)
                write_marker(folder/'hold-wait_held.json',dict(hold_phase='wait_held',wall_ns=2))
                gate.poll(m,lambda i:None);self.assertFalse((folder/'hold-held-ack.json').exists())
                m.devices[n].update({PROPERTIES[0]:False,PROPERTIES[1]:True,PROPERTIES[2]:1})
                gate.poll(m,lambda i:None)
                write_marker(folder/'hold-release_ready.json',dict(hold_phase='release_ready',wall_ns=3));gate.poll(m,lambda i:None)
            self.assertTrue(record['complete']);self.assertEqual(record['qemu_sha256'],QEMU_SHA256)
            self.assertEqual(m.mutations,[(n,key,True) for n in range(2) for key in ['test-runtime-install-g',PROPERTIES[0],'test-runtime-in-release']])

    def test_actual_guest_init_fragment_forwards_every_mode_or_fails(self):
        import os
        import subprocess
        from ws73_security_agent import MODES
        text=(Path(__file__).parents[1]/'ws73_target_init.sh').read_text()
        start=text.index('        for word in $(cat /proc/cmdline); do')
        end=text.index('\n        done',start)+len('\n        done')
        fragment=text[start:end].replace('$(cat /proc/cmdline)','$(printf \'%s\\n\' "$test_cmdline")')
        command='fail() { exit 99; }; connection_arg=""; '+fragment+'; printf \'%s\' "$connection_arg"'
        for mode in [*MODES,'unknown','']:
            result=subprocess.run(['sh','-c',command],env=os.environ|dict(test_cmdline='unrelated=1 ws73.security_agent='+mode),capture_output=True,text=True)
            if mode in MODES:
                self.assertEqual(result.returncode,0,mode);self.assertEqual(result.stdout,' --security-agent='+mode)
            else:self.assertEqual(result.returncode,99,mode)

    def test_bad_qemu_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'qemu';p.write_bytes(b'wrong')
            with self.assertRaises(ValueError):InstallCoordinator(tmp,{},p)

    def test_dirty_selector_does_not_arm_hold(self):
        for key,value in [(SELECTORS[0],0x1c05),(SELECTORS[1],1),(PROPERTIES[2],1),('test-enumeration-reset-once',True)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp,patch('ws73_security_install_hold.validate_qemu'):
                record={};gate=InstallCoordinator(tmp,record,'fixture');m=Monitor();m.devices[0][key]=value
                folder=Path(tmp)/'security-install-hold/phase-0';folder.mkdir(parents=True)
                write_marker(folder/'selection.json',dict(phase=0,index=0,opcode=0x1c03,generation=7,lifetime=1,handle=0,path='/original/0'))
                write_marker(folder/'hold-arm_ready.json',dict(hold_phase='arm_ready',wall_ns=1))
                with self.assertRaises(ValueError):gate.poll(m,lambda i:dict(bus=1,address=2))
                self.assertFalse(m.devices[0][PROPERTIES[0]])

    def test_new_witness_keeps_pre_admission_negatives_distinct(self):
        row,phase,daemon,cap=install_fixture();witness(row,phase,daemon);wire(row,phase,cap)
        for stage,field,value in [('install_before_cancel','raw',[1,7,13,2,0,5000000000,True,False,0,0,0,0,0]),('install_cancelled','path','/wrong'),('install_terminal_stable','raw',[1,7,13,4,0,5000000000,True,True,9,0,7,0,0])]:
            bad=copy.deepcopy(row);next(e for e in bad['events'] if e['stage']==stage)[field]=value
            bad['command']['stdout']='\n'.join(json.dumps(e) for e in bad['events'])
            with self.assertRaises(ValueError):witness(bad,phase,daemon)
        bad=copy.deepcopy(row);bad['mode']='cancel'
        with self.assertRaises(ValueError):witness(bad,phase,daemon)

    def test_new_exit_verdict_requires_its_two_actual_hold_proofs(self):
        record=dict(status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',live_security_agent_requested='install-cancel',security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=[dict(mode='install-cancel')]*2,business_round_trips=8),channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8),ordinary_channel_socket_acceptance=True,qemu_exit=0)
        self.assertEqual(run_exit_code(record),1)
        record['security_install_hold']=dict(complete=True,qemu_sha256=QEMU_SHA256,corroboration=dict(status='TWO_ROLE_ACTUAL_INSTALL_WITHDRAWAL_LATE_REPLY_SCOPED_PASS',phases=[{},{}]))
        self.assertEqual(run_exit_code(record),0)
        for key in ['complete','qemu_sha256','corroboration']:
            wrong=copy.deepcopy(record);del wrong['security_install_hold'][key];self.assertEqual(run_exit_code(wrong),1)


def complete_hold_fixture():
    from ws73_security_install_hold import METHOD
    from ws73_diagnostic_hold import PROPERTIES
    rows=[];phases=[];hosts=[];cap=dict(commands=[],complete=[],native_events=[]);log=''
    for n in range(2):
        row,phase,daemon,c=install_fixture()
        if n:
            import re
            def swap(value):
                if isinstance(value,str):return re.sub(r'slk([01])_g',lambda m:'slk'+str(1-int(m[1]))+'_g',value)
                if isinstance(value,list):return [swap(v) for v in value]
                if isinstance(value,dict):return {k:swap(v) for k,v in value.items()}
                return value
            row=swap(row);phase=swap(phase)
            for entry in phase['typed_objects']:entry['owner']['device']=5-entry['owner']['device']
            for packet in c['commands']+c['complete']+c['native_events']:packet['device']=5-packet['device']
        for i,entry in enumerate(phase['typed_objects']):
            entry['owner']['index']=i if not n else 1-i
        owner=phase['typed_objects'][0]['owner'];obj=phase['typed_objects'][0]['object'];selection=dict(phase=n,index=owner['index'],opcode=0x1c03,**{k:obj[k] for k in ['generation','lifetime','handle','path']})
        markers=[dict(hold_phase=p,wall_ns=t) for p,t in zip(['arm_ready','wait_held','release_ready'],[11,75,82])]
        acks=[dict(stage=p,host_wall_ns=1000+i,request=markers[i],state=dict(zip(PROPERTIES,v))) for i,(p,v) in enumerate(zip(['armed','held','released'],[[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]]))]
        row['install_hold']=dict(selection=selection,arm_receipt_wall_ns=12,markers=markers,acks=acks)
        for e in row['events']:
            if e['stage']=='allocated':e.update(start_wall_ns=21,wall_ns=22)
            if e['stage']=='agent_callback':e['wall_ns']=25
        for e,ack in zip([e for e in row['events'] if e['stage']=='install_barrier'],acks[1:]):e.update(request=ack['request'],ack=ack)
        row['command']['stdout']='\n'.join(json.dumps(e) for e in row['events'])
        host=dict(method='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81',selection=selection,complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,observations=acks,host_identity_at_arm=dict(bus=1,address=20+n))
        for event in c['native_events']:
            if event['device']==owner['device'] and event['event']==1 and event['params']=='031c0100':event.update(wall_ns=85,usb_sha256=str(n+1)*64,usb_length=105)
        for command in c['commands']:
            if command['opcode']==0x1c03:command['completion']=dict(wall_ns=61)
        if n:
            def later(value):
                if isinstance(value,list):return [later(v) for v in value]
                if isinstance(value,dict):return {k:(v+1000 if 'wall_ns' in k and type(v) is int else later(v)) for k,v in value.items()}
                return value
            row=later(row);phase=later(phase);host=later(host)
            for k in c:c[k]=later(c[k])
            row['command']['stdout']='\n'.join(json.dumps(e) for e in row['events'])
        for k in cap:cap[k]+=c[k]
        rows.append(row);phases.append(phase);hosts.append(host)
        log+=f'WS73_TEST_RUNTIME_HOLD: dev 1:{20+n} bytes=105 host_status=0 holds=1 sha256={str(n+1)*64}\nWS73_TEST_RUNTIME_HOLD_RELEASE: dev 1:{20+n} bytes=105 bounded=0 releases=1\n'
    host=dict(method=METHOD,qemu_sha256=QEMU_SHA256,complete=True,physical_acceptance=False,automatic_fault_recovery_acceptance=False,phases=hosts)
    control=dict(security_agent=rows,connection_control=dict(phases=phases))
    return host,control,cap,log


class FullHoldOracleTests(unittest.TestCase):
    def test_exact_synthetic_two_role_gate_and_negative_controls(self):
        from ws73_security_install_hold import corroborate
        host,control,cap,log=complete_hold_fixture();self.assertEqual(corroborate(host,control,cap,log)['status'],'TWO_ROLE_ACTUAL_INSTALL_WITHDRAWAL_LATE_REPLY_SCOPED_PASS')
        for kind in ['missing-accept','wrong-hash','accept-before-cancel','accept-after-finalread','new-submit-after-cancel','bounded-release','missing-hold','drop','wrong-owner','stale-lifetime','late-arm']:
            h,c,p,l=copy.deepcopy((host,control,cap,log));a=next(e for e in p['native_events'] if e['event']==1 and e['params']=='031c0100')
            if kind=='missing-accept':p['native_events'].remove(a)
            elif kind=='wrong-hash':a['usb_sha256']='f'*64
            elif kind=='accept-before-cancel':a['wall_ns']=79
            elif kind=='accept-after-finalread':a['wall_ns']=96
            elif kind=='new-submit-after-cancel':p['commands'].append(dict(bus=1,device=2,opcode=0x1812,wall_ns=90))
            elif kind=='bounded-release':l=l.replace('bounded=0','bounded=1',1)
            elif kind=='missing-hold':l=l.split('\n',1)[1]
            elif kind=='drop':l+='WS73_TEST_RUNTIME_HOLD_DROP: unexpected\n'
            elif kind=='wrong-owner':h['phases'][0]['host_identity_at_arm']['address']=99
            elif kind=='stale-lifetime':h['phases'][0]['selection']=dict(h['phases'][0]['selection'],lifetime=99)
            elif kind=='late-arm':c['security_agent'][0]['install_hold']['arm_receipt_wall_ns']=22
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(h,c,p,l)
