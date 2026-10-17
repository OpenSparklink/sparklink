"""Fail-closed copied syscall receipts; not a running-kernel proof."""
import copy
from pathlib import Path
import sys
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/'bindings/python')]
from sparklink.structs import SleMessageSecurity,SleSendConstraint
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
