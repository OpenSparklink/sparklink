# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic verifier fixtures only; actual role/USB/RF qualification is separate."""
import copy
import json
from pathlib import Path
import sys
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_target
from ws73_observer_policy import corroborate,verify_records,STATUS,DENIALS,POLICY
from test_ws73_initialization_lifecycle import fixture as wire_fixture


def fixture():
    run,capture=wire_fixture();run['daemon_before']={'pid':100,'start_ticks':1};run['bus_before']={'owner':':1.0','pid':100,'uid':0}
    record={'version':1,'status':STATUS,'physical_acceptance':False,'automatic_recovery_acceptance':False,'whole_authorization_acceptance':False,
        'slctl':run['slctl'],'helper':{'path':'/bin/bus-policy-probe','sha256':'a'*64},'phases':[]}
    for phase,owners,start in [('initial',run['initial'],800_000_000),('business',[run['replacement'],run['initial'][1]],2_000_000_000)]:
        entry={'phase':phase,'owners':owners,'start_wall_ns':start,'end_wall_ns':start+20_000_000,'commands':[],'daemon':run['daemon_before']};record['phases'].append(entry)
        for owner in owners:
            for offset in range(5):
                role='ws73' if offset==1 else 'observer';args=([record['helper']['path'],owner['path'],'control' if role=='ws73' else 'observer','native-'+phase] if offset<2 else
                    [record['slctl']['path'],'--adapter',owner['path'],'show' if offset==2 else 'management'] if offset<4 else
                    ['/bin/sh','-c','test -r /dev/sparklink || test -w /dev/sparklink || test -r /dev/usbmon1 || test -w /dev/usbmon1'])
                stdout=''
                if offset<2:
                    stdout=f'AUTH_CREDENTIALS: uid={1000 if role=="ws73" else 1001} gid={1002 if role=="ws73" else 1001} caps=0\n'
                    for dest in ['org.sparklink',':1.0']:
                        values=[]
                        for op in [5,6]:
                            value={'operation':op}
                            if phase=='initial':
                                result=[owner['generation'],owner['generation']*10+(1 if op==5 else 2),op,3,0,0,0xc05 if op==5 else 0x1002,1 if op==5 else 2,2 if op==5 else 3,20 if op==5 else 0,op==5,1,1,1]
                                value.update(result=result,history=result)
                            else:value.update(outcome='invalidated',reason='initializer provenance absent or invalidated')
                            values.append(value)
                        stdout+='AUTH_NATIVE_READ: '+json.dumps({'destination':dest,'phase':'native-'+phase,'policy':POLICY,'management':[owner['generation'],1,1,1,0,0,0],'initializers':values})+'\n'
                    stdout+=''.join('AUTH_DENIED: '+d+'\n' for d in (['own-service'] if role=='ws73' else DENIALS))
                elif offset==2:stdout=f'  State:       Ready\n  Generation:  {owner["generation"]}\n  Radio policy: version=3 adv_slots=1200..1200 tx_power_dbm=127 scan_slots=1600/800\n'
                elif offset==3:stdout=f'NativeManagementStatus: generation={owner["generation"]} mode=1 state=1 flags=1 errno=0 status=0x00 opcode=0x0000\n'
                moment=start+len(entry['commands'])*1_000_000
                entry['commands'].append({'role':role,'identity':owner,'args':args,'stdout':stdout,'stderr':'','exit':1 if offset==4 else 0,'start_wall_ns':moment,'end_wall_ns':moment+500_000})
    return record,run,capture


class ObserverPolicyTests(unittest.TestCase):
    def test_separate_native_role_gate_refuses_mixed_modes_before_output(self):
        for changes in [dict(command='support'),dict(qmp_hotplug=False),dict(fault_recovery=True),dict(parallel_pairs=True),dict(initializer_lifecycle=True),dict(daemon_cancel_remove=True),dict(diagnostic_cancel_verify=True),dict(managed_partial_case='release'),dict(daemon_hold_case='cancel-admission')]:
            with self.subTest(changes=changes),tempfile.TemporaryDirectory() as tmp:
                args=dict(command='run',qmp_hotplug=True,observer_policy=True,output=Path(tmp)/'never');args.update(changes)
                with patch.object(ws73_target,'ordinary_identity'),self.assertRaisesRegex(ValueError,'observer policy requires separate'):
                    ws73_target._run(SimpleNamespace(**args))
                self.assertFalse(args['output'].exists())

    def test_explicit_readonly_allowlist_keeps_writes_and_interface_less_closed(self):
        root=ET.parse(Path(__file__).resolve().parents[2]/'data/dbus/sparklink.conf').getroot()
        default=next(p for p in root.findall('policy') if p.get('context')=='default')
        allows=[a.attrib for a in default.findall('allow')]
        for method in ['GetDiscoveryPolicy','GetManagementStatus','GetInitializationOff']:
            self.assertIn({'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Adapter','send_member':method},allows)
        for method in ['SubmitScanning','SubmitAdvertising','SubmitStopScanning','SubmitStopAdvertising','CancelDiscoveryPolicies','FutureControl']:
            self.assertFalse(any(a.get('send_member')==method for a in allows))
        self.assertFalse(any(a.get('send_type')=='method_call' and 'send_interface' not in a for a in allows))
        self.assertIn({'send_destination':'org.sparklink'},[a.attrib for a in default.findall('deny')])

    def test_application_group_has_scoped_discovery_not_controller_or_service_ownership(self):
        root=ET.parse(Path(__file__).resolve().parents[2]/'data/dbus/sparklink.conf').getroot()
        app=root.find("policy[@group='sparklink-apps']")
        self.assertIsNotNone(app)
        rules=[a.attrib for a in app.findall('allow')]
        self.assertEqual(rules,[
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Adapter','send_member':'AcquireDiscovery'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Adapter','send_member':'ReadDiscovery'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Adapter','send_member':'ReleaseDiscovery'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'GetInfo'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'OpenChannel'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'OpenChannelScoped'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'PrepareDynamicChannel'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'ReadSsapValue'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'ReadSsapDescription'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'WriteSsapValue'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'WriteSsapCommand'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'ReceiveSsapUpdate'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'SubscribeSsapUpdates'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'ReadSsapUpdates'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'RenewSsapSubscription'},
            {'send_destination':'org.sparklink','send_type':'method_call','send_interface':'org.sparklink.Connection','send_member':'CloseSsapSubscription'},
        ])
        self.assertFalse(any('own' in r for r in rules))
        # Contract change: bounded SSAP client calls join owned discovery/channel use.
        # This does not grant controller management or foreign Owned mutation.
        # A controller scan/stop/cancel, connection teardown or future method
        # remains management authority; do not replace this with a broad allow.
        adapter_members={r['send_member']for r in rules if r.get('send_interface')=='org.sparklink.Adapter'}
        self.assertEqual(adapter_members,{'AcquireDiscovery','ReadDiscovery','ReleaseDiscovery'})
        for method in ['StartControllerScan','StopControllerScan','SubmitScanning','SubmitStopScanning','CancelDiscoveryPolicies','FutureControl']:
            self.assertNotIn(method,adapter_members)
        default=root.find("policy[@context='default']")
        self.assertFalse(any(a.get('send_interface')=='org.sparklink.Connection' and a.get('send_member')=='GetInfo' for a in default.findall('allow')))
        self.assertEqual({a['send_interface']for a in rules},{'org.sparklink.Connection','org.sparklink.Adapter'})
        source=(Path(__file__).resolve().parents[2]/'crates/slkd/src/dbus_iface.rs').read_text()
        self.assertIn('async fn start_controller_scan',source)
        self.assertIn('async fn stop_controller_scan',source)
        self.assertNotIn('async fn start_discovery',source)
        self.assertNotIn('async fn stop_discovery',source)

    def test_description_read_and_owner_mutation_keep_distinct_groups(self):
        # XML role contract only,not actual system-bus/kernel authorization.
        root=ET.parse(Path(__file__).resolve().parents[2]/'data/dbus/sparklink.conf').getroot()
        def members(group):
            return {(r.get('send_interface'),r.get('send_member'))
                    for r in root.find(f"policy[@group='{group}']").findall('allow')}
        read=('org.sparklink.Connection','ReadSsapDescription')
        set_owned=('org.sparklink.ServiceManager','SetOwnedLocalDescription')
        self.assertIn(read,members('sparklink-apps'))
        self.assertNotIn(set_owned,members('sparklink-apps'))
        self.assertIn(set_owned,members('sparklink-services'))
        self.assertNotIn(read,members('sparklink-services'))
        default=root.find("policy[@context='default']")
        self.assertFalse(any((r.get('send_interface'),r.get('send_member'))in(read,set_owned)
                             for r in default.findall('allow')))

    def test_synthetic_complete_role_fixture_requires_actual_original_wire(self):
        record,run,capture=fixture();p=corroborate(record,run,capture)
        self.assertEqual(len(p['initializer_observations']),16);self.assertEqual(p['observer_bus_denials'],68)
        self.assertFalse(p['whole_authorization_acceptance'])

    def test_role_scope_credentials_alias_denial_history_and_raw_access_rejected(self):
        for change in ['role','caps','denial','cancel-allowed','raw-access','stale','daemon','policy','token','alias','fake-history','cached-after','early-post','whole-scope']:
            record,run,capture=fixture();row=record['phases'][0]['commands'][0]
            if change=='role':row['role']='ws73'
            if change=='caps':row['stdout']=row['stdout'].replace('caps=0','caps=1')
            if change=='denial':row['stdout']=row['stdout'].replace('AUTH_DENIED: own-service\n','')
            if change=='cancel-allowed':row['stdout']=row['stdout'].replace('AUTH_DENIED: CancelDiscoveryPolicies\n','')
            if change=='raw-access':record['phases'][0]['commands'][4]['exit']=0
            if change=='stale':record['phases'][1]['owners']=[run['initial'][0],run['initial'][1]]
            if change=='daemon':record['phases'][1]['daemon']={'pid':101,'start_ticks':1}
            if change=='policy':row['stdout']=row['stdout'].replace('"policy": [3, 1200','"policy": [3, 1201')
            if change=='token':row['stdout']=row['stdout'].replace('"management": [1, 1, 1, 1, 0, 0, 0]','"management": [1, 1, 1, 1, 0, 0, 0, 7]')
            if change=='alias':row['stdout']=row['stdout'].replace('"destination": ":1.0"','"destination": ":1.9"')
            if change=='fake-history':row['stdout']=row['stdout'].replace('"history": [1, 11, 5','"history": [1, 11, 2')
            if change=='cached-after':record['phases'][1]['commands'][0]['stdout']=row['stdout']
            if change=='early-post':record['phases'][1]['start_wall_ns']=1
            if change=='whole-scope':record['whole_authorization_acceptance']=True
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):verify_records(record,run)

    def test_missing_complete_extra_role_wire_or_wrong_selected_power_rejected(self):
        for change in ['missing','extra','power']:
            record,run,capture=fixture()
            if change=='missing':capture['complete'].pop(0)
            if change=='extra':capture['commands'].append(dict(capture['commands'][0],wall_ns=801_000_000))
            if change=='power':
                for row in record['phases'][0]['commands']:
                    row['stdout']=row['stdout'].replace(', 20, true',', 19, true')
            with self.subTest(change=change),self.assertRaises(ValueError):corroborate(record,run,capture)
