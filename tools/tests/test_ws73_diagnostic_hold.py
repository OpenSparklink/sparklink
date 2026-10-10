# SPDX-License-Identifier: GPL-2.0-only
"""Counted QMP mocks only; not actual QEMU scheduling or USB acceptance."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_diagnostic_hold import HoldCoordinator, PROPERTIES, write_marker


class Monitor:
    def __init__(self):
        self.state=dict(zip(PROPERTIES,[False,False,0,0,0,0,False,0]))
        self.options=dict.fromkeys(['host-reset','guest-reset','guest-resets-all','kernel-driver-detach'],False)
        self.options['attached']=True
        self.sets=[]

    def execute(self,command,args):
        assert args['path']=='/machine/peripheral/ws73_0'
        key=args['property']
        if command=='qom-get':return self.state[key] if key in self.state else self.options[key]
        self.sets.append(args)
        if key=='test-runtime-in-hold-once':self.state[key]=args['value']
        elif key=='test-runtime-in-release':
            self.state['test-runtime-in-held']=False;self.state['test-runtime-in-releases']+=1
        else:raise AssertionError('unexpected QMP mutation')


class HoldCoordinatorTests(unittest.TestCase):
    def test_markers_are_complete_before_publish_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'marker.json';value={'hold_phase':'arm_ready','wall_ns':1}
            write_marker(path,value)
            self.assertEqual(json.loads(path.read_text()),value)
            self.assertFalse(path.with_name(path.name+'.tmp').exists())
            with self.assertRaises(ValueError):write_marker(path,{'wall_ns':2})
            self.assertEqual(json.loads(path.read_text()),value)

    def marker(self,hold,phase):
        hold.folder.mkdir(exist_ok=True)
        (hold.folder/f'hold-{phase}.json').write_text(json.dumps({'hold_phase':phase,'wall_ns':1}))

    def held(self,monitor):
        monitor.state.update({'test-runtime-in-hold-once':False,'test-runtime-in-held':True,'test-runtime-in-holds':1})

    def test_handshake_waits_for_actual_hold_and_only_releases_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            record={};hold=HoldCoordinator(tmp,record);monitor=Monitor()
            hold.poll(monitor);self.assertFalse(monitor.sets)
            self.marker(hold,'arm_ready');hold.poll(monitor)
            self.marker(hold,'wait_held');hold.poll(monitor)
            self.assertEqual(hold.phase,'wait_held');self.assertFalse((hold.folder/'hold-held-ack.json').exists())
            self.held(monitor);hold.poll(monitor)
            self.marker(hold,'release_ready');hold.poll(monitor);hold.poll(monitor)
            self.assertTrue(record['complete']);self.assertEqual(len(monitor.sets),2)
            self.assertEqual([r['stage'] for r in record['observations']],['armed','held','released'])
            self.assertFalse(record['physical_acceptance'])

    def test_missing_owner_reset_options_and_dirty_counters_fail_before_arming(self):
        for key,value in [('attached',False),('host-reset',True),('kernel-driver-detach',True),
                          ('guest-reset',True),('guest-resets-all',True),('test-runtime-in-errors',1),
                          ('test-runtime-in-holds',True)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp:
                hold=HoldCoordinator(tmp,{});monitor=Monitor();self.marker(hold,'arm_ready')
                (monitor.state if key in monitor.state else monitor.options)[key]=value
                with self.assertRaises(ValueError):hold.poll(monitor)
                self.assertFalse(monitor.sets)

    def test_bounded_release_drop_or_old_hold_cannot_be_acknowledged(self):
        for key,value in [('test-runtime-in-releases',1),('test-runtime-in-bounded-releases',1),
                          ('test-runtime-in-hold-drops',1),('test-runtime-in-holds',2)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp:
                hold=HoldCoordinator(tmp,{});monitor=Monitor();self.marker(hold,'arm_ready');hold.poll(monitor)
                self.marker(hold,'wait_held');self.held(monitor);monitor.state[key]=value
                with self.assertRaises(ValueError):hold.poll(monitor)
                self.assertFalse((hold.folder/'hold-held-ack.json').exists())

    def test_expired_hold_is_never_treated_as_explicit_release_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            hold=HoldCoordinator(tmp,{});monitor=Monitor();self.marker(hold,'arm_ready');hold.poll(monitor)
            self.marker(hold,'wait_held');self.held(monitor);hold.poll(monitor)
            monitor.state.update({'test-runtime-in-held':False,'test-runtime-in-releases':1,'test-runtime-in-bounded-releases':1})
            self.marker(hold,'release_ready')
            with self.assertRaises(ValueError):hold.poll(monitor)
            self.assertEqual(len(monitor.sets),1);self.assertFalse(hold.record['complete'])
