"""Fail-closed copied syscall receipts; not a running-kernel proof."""
import copy
from pathlib import Path
import sys
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/'bindings/python')]
from sparklink.structs import SleMessageSecurity,SleSendConstraint,SleChannelInfo
from ws73_channel_grant import verify_intents,intent_receipt
from test_ws73_channel_grant import fixture

class OriginalIntentLifecycle(unittest.TestCase):
    def fixture(self):
        row,outer=fixture('dup');row['tx_constraint_required']=True
        def constraint(n,t):
            o=row['owners'][n]
            return SleSendConstraint(version=1,size=48,generation=o['generation'],lifetime=o['lifetime'],controller=n,handle=o['handle'],security_epoch=21+n,local_tcid=31,remote_tcid=31,pi=241,deadline_monotonic_ns=t+5_000_000_000)
        for b in row['business']:
            for n,a in enumerate(b['applications']):
                c=constraint(n,100)
                a['tx_intent']=intent_receipt(c,100,101,102)
                a['rx_context']=bytes(SleMessageSecurity(version=1,size=40,generation=c.generation,lifetime=c.lifetime,security_epoch=c.security_epoch,controller=n,handle=c.handle,local_tcid=31,remote_tcid=31,pi=241,flags=3)).hex()
        row['revoke_prefix']=dict(payload='fake fixture is not wire proof')
        c=constraint(0,1010);row['armed'].update(tx_intent=intent_receipt(c,1010,1020,1030),admission_before_monotonic_ns=1000,admission_after_monotonic_ns=1100)
        for key in ['after_withdrawal','after_successor']:row[key]['tx_intent_denial']=dict(errors=dict(prepare=13,submit=13),constraint=bytes(c).hex(),calls=dict(prepare_before_monotonic_ns=2000,prepare_after_monotonic_ns=2001,submit_before_monotonic_ns=2002,submit_after_monotonic_ns=2003))
        return row,outer
    def test_original_constraint_and_receiver_context_both_required(self):
        row,outer=self.fixture();p=verify_intents(row,outer)
        self.assertEqual(p['business_sends'],8);self.assertEqual(p['late_refusals'],4);self.assertTrue(p['prefix_admission'])
    def test_bad_context_epoch_lifetime_deadline_or_missing_refusal_fails(self):
        for kind in ['epoch','scope','deadline','renewal','early','unknown','old','minimum','missing','prepare-success','submit-success','cached','prefix-window']:
            r,o=self.fixture();a=r['business'][0]['applications'][0]
            if kind in ['epoch','scope','deadline','renewal','minimum']:
                c=SleSendConstraint.from_buffer_copy(bytes.fromhex(a['tx_intent']['constraint']))
                if kind=='epoch':c.security_epoch+=1
                elif kind=='scope':c.lifetime+=1
                elif kind=='deadline':c.deadline_monotonic_ns=0
                elif kind=='renewal':c.deadline_monotonic_ns+=1
                else:c.minimum=3
                a['tx_intent']['constraint']=bytes(c).hex()
            elif kind=='early':a['tx_intent']['after_monotonic_ns']=0
            elif kind in ['unknown','old']:
                m=SleMessageSecurity.from_buffer_copy(bytes.fromhex(a['rx_context']));m.flags=0 if kind=='unknown' else 1;a['rx_context']=bytes(m).hex()
            elif kind=='missing':r['after_successor'].pop('tx_intent_denial')
            elif kind in ['prepare-success','submit-success']:r['after_withdrawal']['tx_intent_denial']['errors'][kind.split('-')[0]]=0
            elif kind=='cached':r['after_withdrawal']['tx_intent_denial']['constraint']='00'*48
            else:r['armed']['admission_before_monotonic_ns']=1040
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):verify_intents(r,o)
    def test_new_basic_request_epoch_does_not_rewrite_cached_original_intent(self):
        r,o=self.fixture();a=r['business'][1]['applications'][0]
        c=SleSendConstraint.from_buffer_copy(bytes.fromhex(a['tx_intent']['constraint']));c.security_epoch+=10
        m=SleMessageSecurity.from_buffer_copy(bytes.fromhex(a['rx_context']));m.security_epoch=c.security_epoch
        a['tx_intent']['constraint']=bytes(c).hex();a['rx_context']=bytes(m).hex()
        verify_intents(r,o)

    def test_expired_intent_and_inactive_session_have_distinct_exact_errors(self):
        import errno
        r,o=self.fixture();value=copy.deepcopy(r['after_withdrawal']);value['errors']=dict(send=errno.ENOTCONN,recv=errno.ENOTCONN)
        value['tx_intent_denial']['errors']=dict(prepare=errno.ENOTCONN,submit=errno.ETIMEDOUT)
        c=SleSendConstraint.from_buffer_copy(bytes.fromhex(value['tx_intent_denial']['constraint']))
        value['tx_intent_denial']['calls']={k:c.deadline_monotonic_ns+j+1 for j,k in enumerate(value['tx_intent_denial']['calls'])}
        o['data_deadline']=dict(old_fd_before_release=value,old_fd_after_release=copy.deepcopy(value))
        verify_intents(r,o)
        for kind in ['notexpired','wrongphase','success','missing-clock']:
            rr,oo=copy.deepcopy(r),copy.deepcopy(o);d=oo['data_deadline']['old_fd_before_release']['tx_intent_denial']
            if kind=='notexpired':d['calls']['submit_before_monotonic_ns']=1
            elif kind=='wrongphase':d['errors']['submit']=errno.ENOTCONN
            elif kind=='success':d['errors']['submit']=0
            else:d.pop('calls')
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):verify_intents(rr,oo)

    def test_target_loads_the_record_before_enforcing_typed_scope(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'ws73_target.py').read_text())
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='connected_case' and any(isinstance(x,ast.ImportFrom) and x.module=='ws73_connected_file_gate' for x in n.body))
        load=next(i for i,x in enumerate(branch.body) if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='probe' for t in x.targets))
        guard=next(i for i,x in enumerate(branch.body) if isinstance(x,ast.If) and any(isinstance(v,ast.Constant) and v.value=='tx_constraint_required' for v in ast.walk(x.test)))
        self.assertLess(load,guard)

    def phase2(self):
        import errno
        r,o=self.fixture();r['intent_phase_contract_version']=2
        c=SleSendConstraint.from_buffer_copy(bytes.fromhex(r['armed']['tx_intent']['constraint']))
        c.deadline_monotonic_ns=6_000_000_000
        r['armed'].update(tx_intent=intent_receipt(c,1_000_000_000,1_000_000_001,1_000_000_002),
            admission_before_monotonic_ns=999_999_999,admission_after_monotonic_ns=1_000_000_003)
        r['revoke_prefix']['admission_before_wall_ns']=1_000_000_000
        live=SleSendConstraint.from_buffer_copy(bytes(c));live.deadline_monotonic_ns=100_000_100
        fresh=SleSendConstraint.from_buffer_copy(bytes(c));fresh.deadline_monotonic_ns=5_100_000_200
        info=SleChannelInfo(version=1,size=40,controller=c.controller,handle=c.handle,
            generation=c.generation,lifetime=c.lifetime,mtu=2042,mps=2047,local_tcid=31,remote_tcid=31,pi=241,directions=3)
        r['expired_live_intent']=dict(stage='expired_live_intent',errno=errno.ETIMEDOUT,
            pid=r['workers'][0]['pid'],fd=r['workers'][0]['fd'],marker=(b'INTENTEX'+b'x'*32).hex(),
            info_before=bytes(info).hex(),info_after=bytes(info).hex(),constraint=bytes(live).hex(),fresh_constraint=bytes(fresh).hex(),
            before_monotonic_ns=100,prepared_monotonic_ns=101,submit_before_monotonic_ns=100_000_100,
            submit_after_monotonic_ns=100_000_101,fresh_before_monotonic_ns=100_000_200,fresh_after_monotonic_ns=100_000_201,
            start_wall_ns=10,end_wall_ns=20,boot_id='11111111-2222-3333-4444-555555555555')
        d=copy.deepcopy(r['after_withdrawal']);d['errors']=dict(send=errno.ENOTCONN,recv=errno.ENOTCONN)
        d['tx_intent_denial']=dict(errors=dict(prepare=errno.ENOTCONN,submit=errno.ENOTCONN),constraint=bytes(c).hex(),
            calls=dict(prepare_before_monotonic_ns=6_000_000_001,prepare_after_monotonic_ns=6_000_000_002,
                submit_before_monotonic_ns=6_000_000_003,submit_after_monotonic_ns=6_000_000_004))
        o['data_deadline']=dict(old_fd_before_release=d,old_fd_after_release=copy.deepcopy(d))
        return r,o

    def test_phase2_requires_both_live_timeout_and_retired_binding_denial(self):
        from ws73_channel_grant import business_evidence
        r,o=self.phase2();p=verify_intents(r,o)
        self.assertEqual((p['intent_phase_contract_version'],p['expired_intent_refusals'],p['retired_binding_refusals']),(2,1,2))
        for kind in ['missing','version','early','renewed','success','wrong-live-errno','wrong-retired-errno','identity','changed-info','mps-below-header','oversized-mtu','oversized-mps','fresh-epoch','late-probe','boot','worker','bad-marker','USB']:
            rr,oo=copy.deepcopy((r,o));v=rr['expired_live_intent']
            if kind=='missing':rr.pop('expired_live_intent')
            elif kind=='version':rr['intent_phase_contract_version']=True
            elif kind=='early':v['submit_before_monotonic_ns']-=1
            elif kind=='renewed':v['before_monotonic_ns']+=1
            elif kind=='success':v['errno']=0
            elif kind=='wrong-live-errno':v['errno']=107
            elif kind=='wrong-retired-errno':oo['data_deadline']['old_fd_before_release']['tx_intent_denial']['errors']['submit']=110
            elif kind=='identity':
                c=SleSendConstraint.from_buffer_copy(bytes.fromhex(v['constraint']));c.lifetime+=1;v['constraint']=bytes(c).hex()
            elif kind=='changed-info':v['info_after']='00'*40
            elif kind in ['mps-below-header','oversized-mtu','oversized-mps']:
                info=SleChannelInfo.from_buffer_copy(bytes.fromhex(v['info_before']))
                if kind=='mps-below-header':info.mps=info.mtu+4
                elif kind=='oversized-mtu':info.mtu=2043
                else:info.mps=2048
                v['info_before']=v['info_after']=bytes(info).hex()
            elif kind=='fresh-epoch':
                c=SleSendConstraint.from_buffer_copy(bytes.fromhex(v['fresh_constraint']));c.security_epoch+=1;v['fresh_constraint']=bytes(c).hex()
            elif kind=='late-probe':v['fresh_after_monotonic_ns']=1_000_000_000
            elif kind=='boot':rr['queue_boot_id']='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
            elif kind=='worker':v['fd']+=1
            elif kind=='bad-marker':v['marker']='00'*40
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                if kind=='USB':business_evidence(rr,oo,dict(acb_packets=[dict(data=v['marker'])]))
                else:verify_intents(rr,oo)

    def test_phase2_summary_cannot_drop_either_phase_or_boot_identity(self):
        from ws73_target import run_exit_code
        good=dict(status='REAL_CHANNEL_ORIGINAL_DEADLINE_PREFIX_PASS',qemu_exit=0,supervisor_exit=0,
            intent_phase_contract_version=2,live_channel_deadline_requested=True,qemu_args=['ws73.intent_phase=2'],
            connected_file_corroboration=dict(tx_constraints=dict(intent_phase_contract_version=2,expired_intent_refusals=1,retired_binding_refusals=2)))
        self.assertEqual(run_exit_code(good),0)
        for kind in ['missing-version','missing-boot','bool-version','not-deadline','missing-proof','live','retired','wrong-proof-version']:
            bad=copy.deepcopy(good);p=bad['connected_file_corroboration']['tx_constraints']
            if kind=='missing-version':bad.pop('intent_phase_contract_version')
            elif kind=='missing-boot':bad['qemu_args']=[]
            elif kind=='bool-version':bad['intent_phase_contract_version']=True
            elif kind=='not-deadline':bad['live_channel_deadline_requested']=False
            elif kind=='missing-proof':p.clear()
            elif kind=='live':p['expired_intent_refusals']=0
            elif kind=='retired':p['retired_binding_refusals']=1
            else:p['intent_phase_contract_version']=1
            with self.subTest(kind=kind):self.assertEqual(run_exit_code(bad),1)
