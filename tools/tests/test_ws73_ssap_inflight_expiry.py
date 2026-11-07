# SPDX-License-Identifier: GPL-2.0-only
"""Finite parser/verdict fixtures;no successful kernel/firmware/clock backend."""
import copy
import json
from types import SimpleNamespace
import unittest

from ws73_capture import CaptureError
import ws73_ssap_subscription as gate
import ws73_ssap_sender_deadline as hold
from test_ws73_ssap_inflight_release import fixture as released,terminal_hold
from test_ws73_ssap_update_delivery import matched


def fixture(phase=0,*,closing=False):
    original,_=released(phase);scale=10_000_000
    def transform(value):
        if isinstance(value,dict):return {k:(v*scale if k.endswith('wall_ns')and type(v)is int else transform(v))for k,v in value.items()}
        if isinstance(value,list):return [transform(v)for v in value]
        return value
    row=transform(original);row.update(ssap_subscription_inflight_case='expiry',ssap_subscription_inflight_expiry_contract_version=1)
    for item in row['ssap_subscription']:
        lines=[]
        for line in item['stdout'].splitlines():
            if line.startswith('SdkAuthorizationDecision: '):line='SdkAuthorizationDecision: '+json.dumps(transform(json.loads(line.split(': ',1)[1])))
            lines.append(line)
        item['stdout']='\n'.join(lines)+'\n'
    lease=row['ssap_subscription'][0]['leases'][1];app=lease['application'];case=lease['inflight_release']
    app['args'][-1]='1000';lease['active']['expires_ns']=1_000_001_000
    case['selection']['clock'].update(before_ns=700_000_000,after_ns=700_000_001)
    for k in ('release_started','release_request_wall_ns','release_request_monotonic_ns'):case.pop(k)
    case.update(end_monotonic_ns=1_500_000_000)
    case['expiry']=dict(original_expires_ns=lease['active']['expires_ns'],original_expiry_upper_ns=1_000_001_001,
        threshold_ns=1_050_001_001,start_ns=970_000_000,start_wall_ns=2432*scale,end_ns=1_060_000_000,end_wall_ns=2441*scale,
        read_request_ns=1_400_000_000,read_request_wall_ns=2475*scale)
    batch=dict(stage='ssap_subscription_batch',api=app['api'],last=4,dropped=0,refused=0,
        state=2 if closing else 3,flags=0 if closing else 1,reason=2,discarded=1,packets=[])
    lease['expiry_observation']=batch
    if not closing:lease.pop('release')
    raw=[lease['active']]+[r for c in lease['messages']for r in(c['checked'],c['batch'])]+[batch]+([lease['release']]if closing else[])
    app['stdout']='\n'.join(json.dumps(v)for v in raw)+'\n'
    def match(owner,direction,frame,window):
        packet=matched(owner,direction,frame,window);at=window['start_wall_ns']
        if window is case:at=(2421 if direction=='out'else 2422)*scale if frame[4]==16 else(2423 if direction=='out'else 2460)*scale
        elif window is lease and frame[4:]==b'\x0d\x23\x11\0\x02\0\0':at=2445*scale
        elif window is lease and frame[4:]==b'\x0e\x03\x11\0\x02\0\0':at=(2461 if direction=='out'else 2462)*scale
        return packet|dict(wall_ns=at)
    return row,match


class InflightExpiry(unittest.TestCase):
    def test_actual_expired_terminal_or_closing_then_confirmed_cleanup(self):
        for closing in (False,True):
            summary=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',proofs=[])
            for phase in (0,1):
                row,match=fixture(phase,closing=closing);proof,credit=gate.corroborate(row,match)
                self.assertEqual(credit,{0:53,1:53});self.assertEqual([len(v['wire'])for v in proof],[63,43])
                summary['proofs'].append(dict(phase=phase,ssap_subscription=proof))
            self.assertTrue(gate.valid_inflight_summary(summary,case='expiry'))
            self.assertFalse(gate.valid_inflight_summary(summary))
            for mutate in [lambda p:p['proofs'][0]['ssap_subscription'][0].update(inflight_expirations=0),
                           lambda p:p['proofs'][0]['ssap_subscription'][0].pop('inflight_expiry_contract_version'),
                           lambda p:p['proofs'][0]['ssap_subscription'][0].update(inflight_releases=1)]:
                bad=copy.deepcopy(summary);mutate(bad);self.assertFalse(gate.valid_inflight_summary(bad,case='expiry'))

    def test_old_release_cannot_be_renamed_and_real_original_expiry_checks(self):
        for kind in ('old-evidence','wrong-reason','discard','last','packets','flags','manual-release','old-expiry','extended-threshold',
                     'late-cleanup','early-read','wrong-duration','early-disable','late-acceptance','old-token','missing-version'):
            row,match=fixture();lease=row['ssap_subscription'][0]['leases'][1];case=lease['inflight_release'];e=case['expiry']
            if kind=='old-evidence':row,_=released();row.update(ssap_subscription_inflight_case='expiry',ssap_subscription_inflight_expiry_contract_version=1)
            elif kind=='wrong-reason':lease['expiry_observation']['reason']=1
            elif kind=='discard':lease['expiry_observation']['discarded']=0
            elif kind=='last':lease['expiry_observation']['last']=3
            elif kind=='packets':lease['expiry_observation']['packets']=[{}]
            elif kind=='flags':lease['expiry_observation']['flags']=True
            elif kind=='manual-release':case['release_request_wall_ns']=e['start_wall_ns']
            elif kind=='old-expiry':e['original_expires_ns']+=1
            elif kind=='extended-threshold':e['threshold_ns']+=1
            elif kind=='late-cleanup':case['end_monotonic_ns']=lease['active']['expires_ns']+5_000_000_000
            elif kind=='early-read':e['read_request_wall_ns']=case['hold']['markers'][2]['wall_ns']
            elif kind=='wrong-duration':lease['application']['args'][-1]='30000'
            elif kind=='early-disable':case['selection']['clock'].update(before_ns=500_000_000,after_ns=500_000_001)
            elif kind=='late-acceptance':case['selection']['clock'].update(before_ns=900_000_000,after_ns=900_000_001)
            elif kind=='old-token':row['ssap_subscription'][0]['leases'][2]['active']['token']=lease['active']['token']
            else:row.pop('ssap_subscription_inflight_expiry_contract_version')
            with self.subTest(kind=kind),self.assertRaises((CaptureError,KeyError,ValueError)):gate.corroborate(row,match)

    def test_terminal_verdict_requires_exact_expiry_scope_and_original_boot(self):
        from ws73_target import run_exit_code
        pairs=[fixture(p)for p in(0,1)];rows=[v[0]for v in pairs];record,held=terminal_hold(rows)
        record['method']=hold.EXPIRY_METHOD
        for p in record['phases']:p['method']=hold.EXPIRY_METHOD
        held['status']=hold.hold_status('subscription-expiry')
        proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,proofs=[])
        for phase,(row,match)in enumerate(pairs):
            proof['proofs'].append(dict(phase=phase,ssap_subscription=gate.corroborate(row,match)[0],protected_ssap=dict(required=2,controllers=[{},{}]),ssap_values=[{}],ssap_discovery=[{}]))
        supervision=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=10,providers=4,updates=32,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),
            inflight_release_contract_version=1,inflight_case='expiry',inflight_expiry_contract_version=1,inflight_expirations=2,replacement_leases=2,checked_replies=30,discarded_pending=2,snapshot_contract_version=1,snapshot_phases=2,snapshot_files=34,snapshot_bytes=2048)
        m=dict(status='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS',qemu_exit=0,supervisor_exit=0,
            ssap_subscription_requested=True,ssap_subscription_contract_version=1,ssap_subscription_acceptance=True,
            ssap_subscription_inflight_release_requested=True,ssap_subscription_inflight_release_contract_version=1,
            ssap_subscription_inflight_case='expiry',ssap_subscription_inflight_expiry_contract_version=1,
            ssap_subscription_inflight_release_acceptance=False,ssap_subscription_inflight_expiry_acceptance=True,
            ssap_subscription_inflight_hold=record,ssap_subscription_inflight_corroboration=held,
            ssap_subscription_snapshot_contract_version=1,ssap_subscription_supervision=supervision,
            ordinary_channel_socket_acceptance=True,live_ssap_security_requirement=2,live_security_agent_requested='numeric-approve',
            qemu_args=['ws73.ssap_subscription=1 ws73.subscription_snapshot=1 ws73.ssap_subscription_inflight_release=1 ws73.subscription_inflight_case=expiry'],channel_socket_corroboration=proof,
            security_agent_corroboration=dict(status='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS',phases=[dict(mode='numeric-approve',ssap_security_requirement=2)for _ in(0,1)],business_round_trips=8))
        self.assertEqual(run_exit_code(m),0)
        for changed in [dict(ssap_subscription_inflight_case='release'),dict(ssap_subscription_inflight_expiry_contract_version=True),
                dict(ssap_subscription_inflight_expiry_acceptance=False),dict(ssap_subscription_inflight_release_acceptance=True),
                dict(ssap_subscription_inflight_hold={}),dict(ssap_subscription_supervision={}),dict(supervisor_exit=None),
                dict(qemu_args=['ws73.ssap_subscription=1 ws73.subscription_snapshot=1 ws73.ssap_subscription_inflight_release=1'])]:
            with self.subTest(changed=changed):self.assertEqual(run_exit_code(m|changed),1)

    def test_case_boot_selector_and_hold_purpose_are_not_interchangeable(self):
        args=dict(ssap_subscription_verify=True,channel_socket_verify=True,security_agent='numeric-approve',ssap_subscription_inflight_release_verify=True,ssap_subscription_inflight_case='expiry')
        self.assertTrue(gate.requested(SimpleNamespace(**args),passthrough=True))
        for values in [args|{'ssap_subscription_inflight_release_verify':False},args|{'ssap_subscription_inflight_case':None},args|{'ssap_subscription_inflight_case':True},args|{'ssap_subscription_renewal_verify':True}]:
            with self.assertRaises(ValueError):gate.requested(SimpleNamespace(**values),passthrough=True)
        self.assertEqual(gate.boot_inflight_case(['ws73.subscription_inflight_case=expiry'],True),'expiry')
        for tokens,enabled in [(['ws73.subscription_inflight_case=expiry'],False),(['ws73.subscription_inflight_case=expiry']*2,True),(['ws73.subscription_inflight_case=release'],True)]:
            with self.assertRaises(CaptureError):gate.boot_inflight_case(tokens,enabled)
        rows=[fixture(p)[0]for p in (0,1)];record,proof=terminal_hold(rows)
        self.assertFalse(hold.valid_hold_summary(record,proof,purpose='subscription-expiry'))
        record['method']=hold.EXPIRY_METHOD
        for p in record['phases']:p['method']=hold.EXPIRY_METHOD
        proof['status']=hold.hold_status('subscription-expiry')
        self.assertTrue(hold.valid_hold_summary(record,proof,purpose='subscription-expiry'))
        self.assertFalse(hold.valid_hold_summary(record,proof,purpose='subscription-release'))
        supervision=dict(status='ACTUAL_ROOT_SUBSCRIPTION_PHASES_AND_OUTPUTS_CHECKED',version=1,phases=2,reader_UID=1004,provider_UID=1005,readers=10,providers=4,updates=32,daemon=dict(pid=1,start_ticks=1),supervisor=dict(pid=2,start_ticks=2),
            inflight_release_contract_version=1,inflight_case='expiry',inflight_expiry_contract_version=1,inflight_expirations=2,replacement_leases=2,checked_replies=30,discarded_pending=2)
        self.assertTrue(gate.valid_inflight_supervision(supervision,case='expiry'))
        self.assertFalse(gate.valid_inflight_supervision(supervision))


if __name__=='__main__':unittest.main()
