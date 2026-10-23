# SPDX-License-Identifier: GPL-2.0-only
"""Finite selector/schema and synthetic capture fixtures,not Native/RF proof."""
import copy,json,struct,tempfile,unittest
import subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
from ws73_capture import CaptureError,read_capture
import ws73_ssap_subscription as base
import ws73_ssap_shared as shared
from test_ws73_north_star import pcap,command_payload


def wire_fixture(extra=None):
    control=dict(channel_socket=[]);records=[];start=10**15
    for phase in(0,1):
        row=dict(phase=phase,owners=[dict(owner=dict(bus=1,device=10+s),object=dict(handle=12))for s in(0,1)],ssap_subscription=[]);control['channel_socket'].append(row)
        for sender in(0,1):
            item=dict(sender=sender,handle=17,groups=[]);row['ssap_subscription'].append(item)
            for mode in(1,2):
                at=start+phase*1_000_000+sender*100_000+mode*10_000;group=dict(mode=mode,start_wall_ns=at,end_wall_ns=at+9999);item['groups'].append(group)
                values=[(mode,1000),(0,5000)]
                if extra=='duplicate'and(phase,sender,mode)==(0,0,1):values.insert(1,(mode,3000))
                if extra=='other-mode'and(phase,sender,mode)==(0,0,1):values.insert(1,(3,3000))
                if extra=='missing'and(phase,sender,mode)==(0,0,1):values.pop()
                for value,offset in values:
                    data=b'\x0a\0\x07\0\x0d\x23\x11\0'+bytes([2,value,0]);payload=bytearray(command_payload(12,data));payload[68]=0xa3
                    records.extend([(1,10+sender,at+offset,payload,'S',1,-115),(1,10+sender,at+offset+1000,payload,'C',1,0)])
    return control,pcap(records)


class SharedGate(unittest.TestCase):
    def test_slow_reader_workload_preserves_old_unread_lifetime_step(self):
        for kind in ('release','expiry','owner-exit'):
            self.assertEqual([shared.recipients(kind,n)for n in range(7)],[['a0','b']]*3+[['b']]*2+[['a1','b']]*2)
        self.assertEqual(shared.workload('pressure'),(22,18,20))
        members=[shared.recipients('pressure',n)for n in range(22)]
        self.assertEqual(members,[['b']]*17+[['a0','b']]+[['b']]*2+[['a1','b']]*2)
        # 25 live checks plus16 cached checks;the overflow is never delivered.
        self.assertEqual(sum(map(len,members))+16,41)
        for number in (-1,22,True):
            with self.assertRaises(CaptureError):shared.recipients('pressure',number)

    def test_shared_pressure_selector_is_distinct_from_single_and_lifetime(self):
        args=SimpleNamespace(ssap_subscription_verify=True,ssap_subscription_shared_verify=True,channel_socket_verify=True,security_agent='numeric-approve',ssap_subscription_shared_case='pressure')
        self.assertTrue(base.requested(args,passthrough=True))
        row=dict(ssap_subscription_shared_required=True,ssap_subscription_shared_contract_version=1,ssap_subscription_shared_case='pressure',ssap_subscription_shared_pressure_contract_version=1)
        self.assertEqual(base.shared_case(row),'pressure')
        self.assertEqual(base.boot_shared_case(['ws73.subscription_shared_case=pressure'],True),'pressure')
        for update in [dict(ssap_subscription_shared_pressure_contract_version=None),dict(ssap_subscription_shared_pressure_contract_version=True),dict(ssap_subscription_shared_lifetime_contract_version=1),dict(ssap_subscription_shared_required=False),dict(ssap_subscription_shared_case='release')]:
            with self.subTest(update=update),self.assertRaises(CaptureError):base.shared_case(row|update)
        with self.assertRaises(CaptureError):base.boot_shared_case(['ws73.subscription_shared_case=pressure'],False)
        with self.assertRaises(CaptureError):base.boot_shared_case(['ws73.subscription_shared_case=pressure']*2,True)

    def test_slow_queue_oracle_keeps_first16_hole_and_per_owner_counters(self):
        lease=dict(active=dict(epoch=13),application=dict(api='c'))
        group=dict(mode=2,messages=[dict(number=n,value=n.to_bytes(4,'little').hex()+'ab'*28)for n in range(17)])
        batch=shared.pressure_batch(group,lease,19)
        self.assertEqual((batch['last'],batch['dropped'],batch['refused']),(17,0,1))
        self.assertEqual([p['sequence']for p in batch['packets']],list(range(1,17)))
        self.assertEqual(bytes.fromhex(batch['packets'][-1]['pdu']),b'\x10\x03\x13\0\x20\0'+(15).to_bytes(4,'little')+b'\xab'*28)
        self.assertTrue(all(p['epoch']==13 and p['level']==2 and p['indication']is True for p in batch['packets']))
        notify=shared.pressure_batch(group|dict(mode=1),lease,19)
        self.assertEqual((notify['last'],notify['dropped'],notify['refused']),(17,1,0))

    def test_explicit_pressure_transcript_budget_does_not_widen_old_profiles(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'reader.stdout';path.write_text('{}\n'*47)
            app=dict(output_files=[str(path)])
            with self.assertRaises(CaptureError):base.parse_app_rows(path.read_text(),app)
            self.assertEqual(len(base.parse_app_rows(path.read_text(),app|dict(ssap_shared_pressure_contract_version=1))),47)
            with self.assertRaises(CaptureError):base.parse_app_rows(path.read_text(),app|dict(ssap_shared_pressure_contract_version=True))
            path.write_text('{}\n'*65)
            with self.assertRaises(CaptureError):base.parse_app_rows(path.read_text(),app|dict(ssap_shared_pressure_contract_version=1))

    def test_value_observer_budget_fails_before_command_and_is_profile_scoped(self):
        from ws73_ssap_owned import value_snapshot,wait_text,observed_process,output_text
        # Real child text/observer fixture only,no protocol or Native stub.
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'provider.stdout';err=path.with_suffix('.stderr');item=dict(handle=19)
            program="import sys;sys.stdout.write('SsapOwnedValue: handle=19 value=ab\\n'*80);sys.stdout.flush();assert input()=='value';print('value',file=sys.stderr,flush=True);print('SsapOwnedValue: handle=19 value=cd',flush=True);assert input()=='quit'"
            with observed_process([sys.executable,'-c',program],item,path,err,stdin=subprocess.PIPE,text=True)as process:
                wait_text(process,path,r'^SsapOwnedValue: (.+)$',time.monotonic()+2,min_count=80,max_count=80)
                with self.assertRaises(CaptureError):value_snapshot(process,item,'cd',limit=128)
                with self.assertRaises(CaptureError):value_snapshot(process,item,'cd',limit=80)
                with self.assertRaises(CaptureError):value_snapshot(process,item|dict(ssap_shared_pressure_contract_version=True),'cd',limit=128)
                self.assertEqual(output_text(process,err),'')
                observed=value_snapshot(process,item|dict(ssap_shared_pressure_contract_version=1),'cd',limit=128)
                self.assertEqual(observed['ordinal'],81)
                self.assertEqual(wait_text(process,err,'^value$',time.monotonic()+2)[0],['value'])
                with self.assertRaises(CaptureError):wait_text(process,path,'.',0,max_count=81)
                with self.assertRaises(CaptureError):wait_text(process,path,'.',0,max_count=129,count_budget=128)
                with self.assertRaises(CaptureError):wait_text(process,path,'.',0,count_budget=True)
                process.stdin.write('quit\n');process.stdin.flush();process.wait(timeout=2)

    def test_shared_pressure_summary_never_upgrades_other_cases(self):
        # Synthetic summary/packet-shape fixture only;no successful Native stub.
        leg=dict(tx=dict(data='0a00010001'),rx=dict(data='0a00010001'))
        part=dict(sender=0,target=1,publisher='c',peer='python',leases=6,updates=44,application_replies=82,decisions=4,shared_contract_version=1,shared_groups=2,shared_joins=4,retained_releases=4,last_disables=2,wire=[copy.deepcopy(leg)for _ in range(252)],shared_case='pressure',shared_pressure_contract_version=1,slow_notification_drops=1,slow_indication_refusals=1,healthy_losses=0,ordered_drains=2,resumed=2,healthy_replies=44)
        self.assertTrue(shared.part_valid(part,0,0))
        for update in [dict(updates=14),dict(application_replies=24),dict(healthy_losses=1),dict(slow_indication_refusals=0),dict(shared_pressure_contract_version=True),dict(shared_lifetime_contract_version=1),dict(partial_expirations=2),dict(wire=part['wire'][:-1]),dict(shared_case='release')]:
            with self.subTest(update=update):self.assertFalse(shared.part_valid(part|update,0,0))
        proof=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=24,providers=4,updates=176,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),shared_contract_version=1,shared_groups=8,shared_joins=16,checked_replies=328,retained_releases=16,last_disables=8,shared_case='pressure',shared_pressure_contract_version=1,slow_notification_drops=4,slow_indication_refusals=4,healthy_losses=0,ordered_drains=8,resumed=8,healthy_replies=176)
        self.assertTrue(base.valid_shared_supervision(proof,case='pressure'));self.assertFalse(base.valid_shared_supervision(proof))
        for update in [dict(updates=56),dict(checked_replies=96),dict(healthy_losses=1),dict(healthy_replies=175),dict(shared_pressure_contract_version=None),dict(shared_pressure_contract_version=True),dict(shared_lifetime_contract_version=1),dict(pressure_contract_version=1),dict(shared_case='release')]:
            with self.subTest(update=update):self.assertFalse(base.valid_shared_supervision(proof|update,case='pressure'))

    def test_actual_native_receipts_keep_endpoint_epochs_independent(self):
        # Fixture exercises the production receipt parser;no Native ioctl stub.
        owners=[dict(owner=dict(index=n,generation=n+1),object=dict(lifetime=9,handle=0))for n in(0,1)]
        row=dict(rounds=1,message_security_required=True,security_requirement=2,owners=owners,applications=[])
        for n,epoch in enumerate((2,3)):
            out=f'NativeMessageSecurity: sequence=0 index={n} generation={n+1} lifetime=9 handle=0 local=31 remote=31 pi=241 security=2 epoch={epoch} flags=3\n'
            out+='NativeControlRejected: errno=95 bytes='+(b'SLKCMREJ'+bytes(53)).hex()+'\n'
            row['applications'].append(dict(role='peer'if n else'initiator',stdout=out))
        self.assertEqual(shared.native_security_epochs(row),[2,3])
        for old,new in [('generation=2','generation=1'),('lifetime=9','lifetime=8'),('security=2','security=1'),('epoch=3','epoch=0'),('flags=3','flags=1')]:
            bad=copy.deepcopy(row);bad['applications'][1]['stdout']=bad['applications'][1]['stdout'].replace(old,new)
            with self.subTest(new=new),self.assertRaises(CaptureError):shared.native_security_epochs(bad)
        bad=copy.deepcopy(row);bad['message_security_required']=False
        with self.assertRaises(CaptureError):shared.native_security_epochs(bad)

    def test_selector_scope_is_typed_dedicated_and_preserves_baseline(self):
        args=dict(ssap_subscription_verify=True,ssap_subscription_shared_verify=True,channel_socket_verify=True,security_agent='numeric-approve')
        self.assertTrue(base.requested(SimpleNamespace(**args),passthrough=True))
        for update in [dict(ssap_subscription_shared_verify=1),dict(ssap_subscription_shared_verify=None),dict(ssap_subscription_verify=False),dict(channel_socket_verify=False),dict(channel_socket_bytes=2042),dict(channel_socket_rounds=8),dict(security_agent='approve'),*[dict.fromkeys([k],True)for k in('ssap_subscription_inflight_release_verify','ssap_subscription_pressure_verify','ssap_subscription_owner_loss_verify','ssap_subscription_renewal_verify')]]:
            with self.subTest(update=update),self.assertRaises(ValueError):base.requested(SimpleNamespace(**(args|update)),passthrough=True)
        with self.assertRaises(ValueError):base.requested(SimpleNamespace(**args),passthrough=False)
        self.assertTrue(base.shared_required(dict(ssap_subscription_shared_required=True,ssap_subscription_shared_contract_version=1)))
        for row in [dict(ssap_subscription_shared_required=1),dict(ssap_subscription_shared_required=True),dict(ssap_subscription_shared_required=True,ssap_subscription_shared_contract_version=True),dict(ssap_subscription_shared_contract_version=1)]:
            with self.assertRaises(CaptureError):base.shared_required(row)
        self.assertTrue(base.shared_boot(['ws73.ssap_subscription_shared=1']))
        for tokens in [['ws73.ssap_subscription_shared=1']*2,['ws73.ssap_subscription_shared=0'],['ws73.ssap_subscription_shared=true']]:
            with self.assertRaises(CaptureError):base.shared_boot(tokens)

    def test_shared_lifetime_selector_boot_and_supervision_do_not_relabel_release(self):
        for case in ('expiry','owner-exit'):
            args=SimpleNamespace(ssap_subscription_verify=True,ssap_subscription_shared_verify=True,channel_socket_verify=True,security_agent='numeric-approve',ssap_subscription_shared_case=case)
            self.assertTrue(base.requested(args,passthrough=True));self.assertEqual(base.requested_shared_case(args),case)
            row=dict(ssap_subscription_shared_required=True,ssap_subscription_shared_contract_version=1,ssap_subscription_shared_case=case,ssap_subscription_shared_lifetime_contract_version=1)
            self.assertEqual(base.shared_case(row),case)
            for update in [dict(ssap_subscription_shared_required=False),dict(ssap_subscription_shared_lifetime_contract_version=True),dict(ssap_subscription_shared_lifetime_contract_version=2),dict(ssap_subscription_shared_case='release')]:
                with self.subTest(update=update),self.assertRaises(CaptureError):base.shared_case(row|update)
            for enabled,tokens in [(False,['ws73.subscription_shared_case='+case]),(True,['ws73.subscription_shared_case='+case]*2),(True,['ws73.subscription_shared_case=release']),(True,['ws73.subscription_shared_case=bad'])]:
                with self.assertRaises(CaptureError):base.boot_shared_case(tokens,enabled)
            self.assertEqual(base.boot_shared_case(['ws73.subscription_shared_case='+case],True),case)
            old=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=24,providers=4,updates=56,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),shared_contract_version=1,shared_groups=8,shared_joins=16,checked_replies=96,retained_releases=16,last_disables=8)
            self.assertFalse(base.valid_shared_supervision(old,case=case))
            current=old|dict(shared_case=case,shared_lifetime_contract_version=1)
            if case=='expiry':current.update(partial_expirations=8,expired_discarded=8)
            else:current.update(partial_owner_exits=8,unconsumed_published=8,retained_releases=8)
            self.assertTrue(base.valid_shared_supervision(current,case=case));self.assertFalse(base.valid_shared_supervision(current))
            for key in ['shared_lifetime_contract_version','partial_expirations'if case=='expiry'else'partial_owner_exits']:
                bad=current.copy();bad.pop(key);self.assertFalse(base.valid_shared_supervision(bad,case=case))
            self.assertFalse(base.valid_shared_supervision(current|{'expired_discarded':8},case=case))if case=='owner-exit'else self.assertFalse(base.valid_shared_supervision(current|{'partial_owner_exits':8},case=case))
        for case in (True,None,'bad'):
            with self.assertRaises(ValueError):base.requested_shared_case(SimpleNamespace(ssap_subscription_shared_case=case,ssap_subscription_shared_verify=True))
        with self.assertRaises(ValueError):base.requested_shared_case(SimpleNamespace(ssap_subscription_shared_case='expiry'))
        with self.assertRaises(CaptureError):base.shared_case(dict(ssap_subscription_shared_lifetime_contract_version=1))

    def test_actual_parser_rejects_extra_missing_duplicate_configuration_writes(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'capture.pcap'
            for extra in(None,'duplicate','other-mode','missing'):
                control,raw=wire_fixture(extra);path.write_bytes(raw);capture=read_capture(path,[(1,10),(1,11)])
                if extra is None:
                    proof=shared.configuration_wire(control,capture);self.assertTrue(shared.valid_configuration_summary(proof))
                    for change in ('phase','bool-mode','count','missing','raw'):
                        bad=copy.deepcopy(proof)
                        if change=='phase':bad['groups'][0]['phase']=1
                        elif change=='bool-mode':bad['groups'][0]['mode']=True
                        elif change=='count':bad['enables']=7
                        elif change=='missing':bad['groups'][0]['writes'].pop()
                        else:bad['groups'][0]['writes'][1]['data']='00'
                        self.assertFalse(shared.valid_configuration_summary(bad),change)
                else:
                    with self.subTest(extra=extra),self.assertRaises(CaptureError):shared.configuration_wire(control,capture)

    def test_shared_supervision_cannot_relabel_single_lease_evidence(self):
        proof=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=24,providers=4,updates=56,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),shared_contract_version=1,shared_groups=8,shared_joins=16,checked_replies=96,retained_releases=16,last_disables=8)
        self.assertTrue(base.valid_shared_supervision(proof))
        for update in [dict(readers=8),dict(updates=24),dict(shared_contract_version=True),dict(shared_groups=7),dict(checked_replies=56),dict(last_disables=24),dict(retained_releases=0),dict(inflight_release_contract_version=1)]:
            with self.subTest(update=update):self.assertFalse(base.valid_shared_supervision(proof|update))

    def test_new_guest_source_is_required_before_any_usb_execution(self):
        from ws73_target import file_record,HERE
        from ws73_ssap_sender_deadline import validate_inputs
        names=['ws73_ssap_sender_deadline.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh','ws73_ssap_subscription.py','ws73_application_role.py']
        package=dict(inputs=[file_record(HERE/n)for n in names],application_client_tools=dict(sources=[file_record(HERE/n)for n in('testing/application_client/client.c','testing/application_client/client.py')]))
        validate_inputs(package,subscription=True)
        with self.assertRaises(ValueError):validate_inputs(package,subscription=True,shared=True)
        package['inputs'].append(file_record(HERE/'ws73_ssap_shared.py'))
        with self.assertRaises(ValueError):validate_inputs(package,subscription=True,shared=True)
        package['inputs'].append(file_record(HERE/'ws73_ssap_owned.py'));validate_inputs(package,subscription=True,shared=True)
        package['inputs'][-1]['sha256']='0'*64
        with self.assertRaises(ValueError):validate_inputs(package,subscription=True,shared=True)

if __name__=='__main__':unittest.main()
