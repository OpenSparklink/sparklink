# SPDX-License-Identifier: GPL-2.0-only
"""Counterfeit transcript tests; no actual device/crypto/identity qualification."""
import errno
import unittest
from test_ws73_encryption import fixture as encryption_fixture
from ws73_security_capabilities import verify, corroborate, Submit, Result, decode
from ws73_security_numeric import OFFER, decision, public_comparison
from ws73_target import run_exit_code


def fixture(mode='numeric-approve'):
    r, c = encryption_fixture(); row = r['security_capabilities']
    r.pop('key_agreement'); r.pop('unauthenticated_encryption')
    r['numeric_comparison'] = mode
    row['ordinary_denial']['confirm_errno']=errno.EPERM
    numeric = row['numeric'] = dict(mode=mode, prompts=[], decisions=[], negatives=[],
        prompt_wall_ns=218, prompt_monotonic_ns=218, terminal_wall_ns=245,
        terminal_monotonic_ns=245 if mode=='numeric-approve' else 5_000_000_161)
    row['observed_monotonic_ns'] = numeric['terminal_monotonic_ns']+1
    for n in (0, 1):
        q = decode(Submit, row['requests'][n]); q.flags=4; row['requests'][n]=bytes(q).hex()
        v = decode(Result, row['results'][n]); v.local_caps[:]=OFFER; v.peer_caps[:]=OFFER
        v.state=3; v.flags=15; v.comparison_code=759201
        numeric['prompts'].append(bytes(v).hex())
        v.comparison_code=0
        v.state, v.flags, v.error = (11,119,0) if mode=='numeric-approve' else ((5,7,-errno.EACCES) if mode=='numeric-reject' and n==0 else (7,7,-errno.ETIMEDOUT))
        row['results'][n]=bytes(v).hex()
        if n==1:
            v.state=1; v.flags=0; v.error=0; v.peer_caps[:]=bytes(10)
            row['t_armed']=bytes(v).hex()
        for kind in ['code','request','reserved','accept','nonowner','terminal_confirm']:
            d=decision(q,759201); want=errno.EPERM; when=219
            if kind=='code': d.comparison_code+=1; want=errno.ESTALE
            elif kind=='request': d.request_id+=1; want=errno.ENOENT
            elif kind=='reserved': d.reserved[0]=1; want=errno.EINVAL
            elif kind=='accept': d.accept=2; want=errno.EINVAL
            elif kind=='terminal_confirm': when=numeric['terminal_monotonic_ns']+1; want=errno.ECANCELED if mode=='numeric-approve' else errno.ETIMEDOUT
            numeric['negatives'].append(dict(index=n,kind=kind,input=bytes(d).hex(),errno=want,before_monotonic_ns=when,after_monotonic_ns=when))
        if mode=='numeric-approve' or mode=='numeric-reject' and n==0:
            when=218 if n==0 else 223
            numeric['decisions'].append(dict(index=n,input=bytes(decision(q,759201,mode=='numeric-approve')).hex(),before_wall_ns=when,after_wall_ns=when,before_monotonic_ns=when,after_monotonic_ns=when))
    c['commands']=[v for v in c['commands'] if v['opcode']!=0x1812 and (mode=='numeric-approve' or v['opcode'] not in (0x1c03,0x1c05))]
    c['complete']=[v for v in c['complete'] if v['opcode']!=0x1812]
    c['native_events']=[v for v in c['native_events'] if v['event']!=0x14 and (mode=='numeric-approve' or v['event'] not in (1,0xe,0x11) or v['wall_ns']>250)]
    order=[0x134,0x135,0x136,0x137,0x13c,0x139]+([0x141,0x142] if mode=='numeric-approve' else [])
    for pos,index in enumerate(order):
        source=0 if index in (0x134,0x136,0x139,0x141) else 1; when=190+5*pos
        data=OFFER if index in (0x134,0x135) else bytes([16,0,2,2,2,2])+bytes(range(1,65)) if index==0x136 else bytes(range(129,193)) if index==0x137 else bytes([9])*16+bytes(range(32,48)) if index==0x13c else bytes(range(16,32)) if index==0x139 else bytes([pos])*16
        body=b'\0\0'+index.to_bytes(2,'little')+bytes([len(data)])+data
        c['commands'].append(dict(**r['usb'][source],opcode=0x1812,params=body.hex(),wall_ns=when,record=300+pos,completion={'record':400+pos}))
        c['complete'].append(dict(**r['usb'][source],opcode=0x1812,status=0,value=body[:4].hex(),wall_ns=when+2,record=500+pos))
        c['native_events'].append(dict(**r['usb'][1-source],event=0x14,params=body.hex(),wall_ns=when+1,record=600+pos))
    return r,c


class NumericWitness(unittest.TestCase):
    def test_all_three_modes_reuse_full_wire_business_and_cleanup_checker(self):
        for mode in ('numeric-approve','numeric-reject','numeric-late'):
            r,c=fixture(mode); verify(r); proof=corroborate(r,c)
            self.assertEqual(proof['status'],'REAL_NUMERIC_COMPARISON_MECHANISM_CORROBORATED')
            self.assertEqual(proof['numeric']['code'],759201)
            self.assertEqual(len(proof['business_legs']),16)
            self.assertEqual(len(proof['installations']),2 if mode=='numeric-approve' else 0)
            manifest=dict(supervisor_exit=0,status='REAL_NUMERIC_COMPARISON_MECHANISM_PASS',live_security_numeric_requested=mode,connected_file_corroboration=proof,qemu_exit=0)
            self.assertEqual(run_exit_code(manifest),0)
            for key in ('connected_file_corroboration','live_security_numeric_requested','qemu_exit'):
                bad=manifest.copy();bad.pop(key);self.assertEqual(run_exit_code(bad),1)

    def test_reject_bad_public_widths(self):
        with self.assertRaises(ValueError):public_comparison(bytes(63),bytes(64),bytes(16),bytes(16))

    def test_missing_or_duplicate_negative_is_an_explicit_validation_failure(self):
        for index in range(12):
            r,c=fixture();r['security_capabilities']['numeric']['negatives'].pop(index)
            with self.subTest(index=index),self.assertRaises(ValueError):verify(r)
        r,c=fixture();n=r['security_capabilities']['numeric']['negatives'];n[5]=n[4].copy()
        with self.assertRaises(ValueError):verify(r)

    def test_dropped_or_fabricated_stage_never_passes(self):
        for kind in ('code','decision','late','identity','offer','native9','early_proof','public_transcript','missing_peer','install','business','negative','ordinary_confirm'):
            r,c=fixture();row=r['security_capabilities'];n=row['numeric']
            if kind in ('code','identity','offer'):
                v=decode(Result,n['prompts'][1])
                if kind=='code':v.comparison_code+=1
                elif kind=='identity':v.lifetime+=1
                else:v.local_caps[2]=0
                n['prompts'][1]=bytes(v).hex()
            elif kind=='decision':n['decisions'].pop()
            elif kind=='late':n['decisions'][0]['after_monotonic_ns']=5_000_000_160
            elif kind=='native9':v=decode(Result,row['results'][0]);v.state=9;row['results'][0]=bytes(v).hex()
            elif kind=='early_proof':n['decisions'][0]['before_wall_ns']=221;n['decisions'][0]['after_wall_ns']=221
            elif kind=='public_transcript':
                # Change both actual TX and opposite RX identically: equality
                # alone still cannot replace independent comparison checking.
                for group in ('commands','native_events'):
                    v=next(v for v in c[group] if v.get('opcode')==0x1812 and v['params'][4:8]=='3901' or v.get('event')==0x14 and v['params'][4:8]=='3901')
                    v['params']=v['params'][:-2]+'ff'
            elif kind=='missing_peer':c['native_events']=[v for v in c['native_events'] if v.get('record')!=607]
            elif kind=='install':c['commands']=[v for v in c['commands'] if v['opcode']!=0x1c05]
            elif kind=='business':c['acb_packets'].pop()
            elif kind=='ordinary_confirm':row['ordinary_denial']['confirm_errno']=0
            else:n['negatives'][0]['errno']=0
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c)
