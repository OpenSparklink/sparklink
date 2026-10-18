# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic transcript/shape rejection controls; not hardware qualification."""
import copy
import unittest
from ws73_protected_grant import requirement,corroborate
from ws73_management_setup import decode
from sparklink.structs import SleConnectionSecurity,SleSecurityNegotiationSubmit as Submit
from test_ws73_encryption import fixture as encryption_fixture
from test_ws73_security_numeric import fixture as numeric_fixture


def fixture(level=1):
    outer,capture=(encryption_fixture if level==1 else numeric_fixture)()
    context=dict(index=outer['index'],protected_requirement=level,status='ACTUAL_POSITIVE_MECHANISM_OBSERVED',
        before_wall_ns=159,after_wall_ns=251,end_wall_ns=252,security_capabilities=outer.pop('security_capabilities'),before=[],after=[])
    if level==1:
        context['key_agreement']=outer.pop('key_agreement');context['unauthenticated_encryption']=outer.pop('unauthenticated_encryption')
    else:context['numeric_comparison']=outer.pop('numeric_comparison')
    for n,raw in enumerate(context['security_capabilities']['requests']):
        req=decode(Submit,raw)
        for key,observed in [('before',0),('after',level)]:
            value=SleConnectionSecurity(generation=req.generation,lifetime=req.lifetime,handle=req.handle,
                security_epoch=1 if not observed else (2 if n==outer['index'] else 3),version=1,profile=1,
                level=observed,flags=0 if not observed else 13 if level==1 else 15,
                method=0 if not observed else 3 if level==1 else 4,key_size=16 if observed else 0)
            context[key].append(bytes(value).hex())
    outer.update(channel_security_requirement=level,protected_security=context)
    for b in outer['channel_grant']['business']:b['start_wall_ns']=270
    return outer,capture


class ProtectedPrelude(unittest.TestCase):
    def test_explicit_typed_preludes_reuse_the_existing_wire_checker(self):
        for level in (1,2):
            r,c=fixture(level);self.assertEqual(requirement(r),level)
            p=corroborate(r,c);self.assertEqual(p['requirement'],level)
            self.assertEqual(len(p['wire']['installations']),2)
            self.assertEqual(p['wire']['status'],'REAL_POSITIVE_EXCHANGE_ONLY_CORROBORATED')

    def test_incomplete_old_or_downgraded_mechanism_cannot_authorize_the_gate(self):
        for level in (1,2):
            base,_=fixture(level)
            for kind in ['missing','plain','unsupported','false-level','status','foreign-index','level','flags','epoch','identity','deadline','terminal','nonowner','early-business']:
                r=copy.deepcopy(base);ctx=r['protected_security'];row=ctx['security_capabilities']
                if kind=='missing':r.pop('protected_security')
                elif kind=='plain':r['channel_security_requirement']=0
                elif kind=='unsupported':r['channel_security_requirement']=3
                elif kind=='false-level':r['channel_security_requirement']=True
                elif kind=='status':ctx['status']='POLICY_YES'
                elif kind=='foreign-index':ctx['index']=1-ctx['index']
                elif kind in ['level','flags','epoch','identity']:
                    v=decode(SleConnectionSecurity,ctx['after'][0])
                    if kind=='level':v.level=0
                    elif kind=='flags':v.flags=0
                    elif kind=='epoch':v.security_epoch=1
                    else:v.lifetime+=1
                    ctx['after'][0]=bytes(v).hex()
                elif kind=='deadline':row['observed_monotonic_ns']=5_000_000_999
                elif kind=='terminal':row['results'][0]='00'*len(bytes.fromhex(row['results'][0]))
                elif kind=='nonowner':row['negative'][0]['errno']=0
                else:r['channel_grant']['business'][0]['start_wall_ns']=1
                with self.subTest(level=level,kind=kind),self.assertRaises((ValueError,KeyError)):
                    if kind=='early-business':corroborate(r,{})
                    else:requirement(r)

    def test_local_success_without_peer_receipts_install_or_cipher_is_not_qualified(self):
        for level in (1,2):
            for kind in ['peer-rx','complete','install','cipher','payload']:
                r,c=fixture(level)
                if kind=='peer-rx':c['native_events']=[v for v in c['native_events'] if v['event']!=0x14]
                elif kind=='complete':c['complete']=[v for v in c['complete'] if v['opcode']!=0x1812]
                elif kind=='install':c['commands']=[v for v in c['commands'] if v['opcode']!=0x1c05]
                elif kind=='cipher':c['native_events']=[v for v in c['native_events'] if v['event']!=0x11]
                else:
                    v=next(v for v in c['native_events'] if v['event']==0x14);v['params']=v['params'][:-2]+'ff'
                with self.subTest(level=level,kind=kind),self.assertRaises(ValueError):corroborate(r,c)

    def test_supervisor_requires_the_requested_grade_and_complete_proof(self):
        from ws73_target import run_exit_code
        for level in (1,2):
            base=dict(supervisor_exit=0,status='REAL_CHANNEL_GRANT_PASS',qemu_exit=0,live_channel_security_required=level,
                connected_file_corroboration=dict(protected_security=dict(requirement=level,
                    status='ACTUAL_PROTECTED_PRELUDE_AND_LIFECYCLE_SCOPE',
                    wire=dict(status='REAL_POSITIVE_EXCHANGE_ONLY_CORROBORATED'))))
            self.assertEqual(run_exit_code(base),0)
            for kind in ['missing-request','plain','missing-proof','wrong-grade','false-grade','wire','qemu','type']:
                r=copy.deepcopy(base);p=r['connected_file_corroboration']['protected_security']
                if kind=='missing-request':r.pop('live_channel_security_required')
                elif kind=='plain':r['live_channel_security_required']=0
                elif kind=='missing-proof':r['connected_file_corroboration'].pop('protected_security')
                elif kind=='wrong-grade':p['requirement']=3-level
                elif kind=='false-grade':p['requirement']=True
                elif kind=='wire':p['wire']='PASS'
                elif kind=='qemu':r['qemu_exit']=1
                else:r['connected_file_corroboration']=None
                with self.subTest(level=level,kind=kind):self.assertEqual(run_exit_code(r),1)

    def test_original_all_command_guard_only_counts_exact_verified_records(self):
        from ws73_protected_grant import command_records
        r,c=fixture(1);p=corroborate(r,c)
        commands=command_records(p,c)
        self.assertEqual(len(commands),11)
        self.assertNotIn(0x1403,[v['opcode'] for v in commands])
        for kind in ['missing','duplicate','changed-relay','bad-id']:
            proof,cap=copy.deepcopy(p),copy.deepcopy(c)
            if kind=='missing':cap['commands'].remove(next(v for v in cap['commands'] if v['opcode']==0x1c03))
            elif kind=='duplicate':cap['commands'].append(copy.deepcopy(commands[0]))
            elif kind=='changed-relay':proof['wire']['controllers'][0]['relays'][0]['command']['params']='00'
            else:proof['wire']['installations'][0]['command_record']=-1
            with self.subTest(kind=kind),self.assertRaises(ValueError):command_records(proof,cap)

    def test_plain_legacy_has_no_implicit_positive_prelude(self):
        self.assertEqual(requirement({}),0)
        with self.assertRaises(ValueError):requirement(dict(protected_security={}))

if __name__=='__main__':unittest.main()
