# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic rejection tests for a real gate; never hardware qualification."""
import errno
import unittest

from test_ws73_security_capabilities import fixture as capability_fixture
from ws73_security_capabilities import verify, Submit, Result, decode
from ws73_security_cancel import corroborate, request, Cancel, NEGATIVES


def fixture():
    r,c=capability_fixture();r.update(security_cancel_pending=True,status='SECURITY_CANCEL_PENDING_PASS')
    row=r['security_capabilities'];row.update(status='REAL_PASSIVE_AUTHOR_CANCEL_PASS',t_arm_before_wall_ns=170)
    row.pop('g_start_before_wall_ns')
    for n in [0,1]:
        req=decode(Submit,row['requests'][n]);req.flags=3;row['requests'][n]=bytes(req).hex()
    row['negative']=[v for v in row['negative'] if not (v['index']==0 and v['kind']=='same_lifetime_restart')]
    out=decode(Result,row['t_armed']);out.state=6;out.error=-errno.ECANCELED
    row['results']=[None,bytes(out).hex()]
    row['ordinary_denial']['cancel_errno']=errno.EPERM
    good=request(decode(Submit,row['requests'][1]))
    evidence=dict(input=bytes(good).hex(),returns=[0,0],observations=[bytes(out).hex()]*2,
                  unapproved_errno=errno.ENOENT,before_wall_ns=220,negative=[])
    row['cancel']=evidence
    for kind,want in NEGATIVES.items():
        bad=Cancel.from_buffer_copy(bytes(good))
        if kind=='version':bad.version=0
        elif kind=='reserved':bad.reserved=1
        elif kind=='generation':bad.generation+=1
        elif kind=='lifetime':bad.lifetime+=1
        elif kind=='handle':bad.handle^=1
        elif kind=='request':bad.request_id+=1
        evidence['negative'].append(dict(kind=kind,input=bytes(bad).hex(),errno=want,after=row['t_armed']))
    c['commands']=[v for v in c['commands'] if v['opcode']!=0x1812]
    c['complete']=[v for v in c['complete'] if v['opcode']!=0x1812]
    c['native_events']=[v for v in c['native_events'] if v['event']!=0x14]
    return r,c


class PassiveCancellation(unittest.TestCase):
    def test_original_deadline_expires_before_a_refreshed_post_policy_budget(self):
        r,c=fixture();r.update(security_original_deadline=True,status='SECURITY_ORIGINAL_DEADLINE_PASS')
        row=r['security_capabilities'];row.update(status='REAL_SECURITY_ORIGINAL_DEADLINE_PASS',policy_wait_start_ns=170,policy_wait_end_ns=2_000_000_170,t_arm_before_monotonic_ns=2_000_000_171,observed_monotonic_ns=5_000_000_180)
        out=decode(Result,row['results'][1]);out.state=7;out.error=-errno.ETIMEDOUT
        row['results'][1]=bytes(out).hex();row['cancel'].update(expired_before_cancel=bytes(out).hex(),observations=[bytes(out).hex()]*2)
        retry=next(v for v in row['negative'] if v['kind']=='same_lifetime_restart');fresh=decode(Submit,row['requests'][1]);fresh.request_id=2;fresh.deadline_monotonic_ns=row['observed_monotonic_ns']+5_000_000_000;retry.update(input=bytes(fresh).hex(),before_monotonic_ns=row['observed_monotonic_ns'])
        self.assertEqual(corroborate(r,c)['status'],'REAL_SECURITY_ORIGINAL_DEADLINE_CORROBORATED')
        for kind in ['not_expired','reset_budget','no_policy_wait','cancel_overwrites_timeout','expired_restart_input']:
            with self.subTest(kind=kind):
                import copy
                bad=copy.deepcopy(r);value=bad['security_capabilities']
                if kind=='not_expired':value['observed_monotonic_ns']=4_000_000_000
                elif kind=='reset_budget':
                    request_value=decode(Submit,value['requests'][1]);request_value.deadline_monotonic_ns+=2_000_000_000;value['requests'][1]=bytes(request_value).hex()
                elif kind=='no_policy_wait':value['policy_wait_end_ns']=171
                elif kind=='expired_restart_input':
                    item=next(v for v in value['negative'] if v['kind']=='same_lifetime_restart');item['input']=value['requests'][1]
                else:value['cancel']['expired_before_cancel']=value['t_armed']
                with self.assertRaises(ValueError):verify(bad)

    def test_same_session_local_cancel_with_actual_business_and_later_cleanup(self):
        r,c=fixture();verify(r);proof=corroborate(r,c)
        self.assertEqual(proof['business_round_trips'],4)
        self.assertFalse(proof['in_flight_installation_qualified'])

    def test_request_denial_terminal_and_original_deadline_cannot_be_omitted(self):
        for kind in ['identity','ordinary','nonowner','denial_state','denial_input','repeat','terminal','peer','deadline','lease','lifetime','ready','business','key_agreement']:
            r,c=fixture();row=r['security_capabilities'];e=row['cancel']
            if kind=='identity':v=decode(Cancel,e['input']);v.lifetime+=1;e['input']=bytes(v).hex()
            elif kind=='ordinary':row['ordinary_denial']['cancel_errno']=0
            elif kind=='nonowner':e['negative'][-1]['errno']=0
            elif kind=='denial_state':e['negative'][0]['after']=row['results'][1]
            elif kind=='denial_input':e['negative'][0]['input']=e['input']
            elif kind=='repeat':e['observations'].pop()
            elif kind=='terminal':
                v=decode(Result,row['results'][1]);v.state=9;v.error=0;row['results'][1]=bytes(v).hex();e['observations']=[bytes(v).hex()]*2
            elif kind=='peer':e['unapproved_errno']=0
            elif kind=='deadline':row['observed_monotonic_ns']=row['t_arm_before_monotonic_ns']+5_000_000_000
            elif kind=='lease':row['management_after'][0]=row['management_cleaned'][0]
            elif kind=='lifetime':row['after_links'][0]=row['before_links'][1]
            elif kind=='ready':row['after_ready'][0]=row['before_ready'][1]
            elif kind=='business':r['channel_grant']['business'].pop()
            else:r['key_agreement']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify(r)

    def test_no_security_wire_or_application_log_can_replace_real_traffic(self):
        for kind in ['relay','install','enable','security_rx','install_event','off_event','business','down','scan','missing_business_rx']:
            r,c=fixture()
            if kind in ['relay','install','enable']:
                c['commands'].append(dict(**r['usb'][0],opcode={'relay':0x1812,'install':0x1c03,'enable':0x1c05}[kind],wall_ns=230))
            elif kind in ['security_rx','install_event','off_event']:
                c['native_events'].append(dict(**r['usb'][1],event={'security_rx':0x14,'install_event':0x11,'off_event':0xe}[kind],wall_ns=230))
            elif kind=='business':c['acb_packets'].clear()
            elif kind=='down':c['native_events'].pop(0)
            elif kind=='scan':c['complete'][-1]['status']=1
            else:c['acb_packets'].pop(0)
            with self.subTest(kind=kind),self.assertRaises(ValueError):corroborate(r,c)
