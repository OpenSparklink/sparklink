# SPDX-License-Identifier: GPL-2.0-only
import copy
import json
from pathlib import Path
import tempfile
import unittest

from ws73_model_hold import ModelHoldCoordinator, PROPERTIES, corroborate_model_hold
from ws73_diagnostic_hold import write_marker


class Monitor:
    def __init__(self):
        self.state=dict(zip(PROPERTIES,[False,False,0,0,0,0]));self.armable=True
    def execute(self, name, args):
        assert args['path']=='/machine/peripheral/ws73_0'
        key=args['property']
        if name=='qom-get':return self.armable if key=='model-terminal-armable' else self.state[key]
        assert name=='qom-set' and args['value'] is True
        if key==PROPERTIES[0]:self.state[key]=True
        else:
            assert key=='model-terminal-release' and self.state[PROPERTIES[1]]
            self.state[PROPERTIES[1]]=False;self.state[PROPERTIES[3]]+=1
        return {}


def handshake(folder):
    record={};coordinator=ModelHoldCoordinator(folder,record);monitor=Monitor()
    coordinator.folder.mkdir()
    markers=[]
    for i,phase in enumerate(['arm_ready','wait_held','release_ready']):
        marker=dict(hold_phase=phase,wall_ns=i+1);markers.append(marker)
        write_marker(coordinator.folder/f'hold-{phase}.json',marker)
        if phase=='wait_held':monitor.state=dict(zip(PROPERTIES,[False,True,1,0,0,0]))
        coordinator.poll(monitor)
    probe=dict(synthetic_support=True,hold_acknowledgements=record['observations'],markers=markers)
    reply=dict(usb_sha256='a'*64,usb_length=156,record=42)
    stderr=f'WS73_MODEL_TERMINAL_HOLD: serial=1 bytes=156 sha256={"a"*64}\nWS73_MODEL_TERMINAL_RELEASE: serial=1 bytes=156 bounded=0 sha256={"a"*64}\n'
    return record,probe,reply,stderr


class ModelHoldTests(unittest.TestCase):
    def test_exact_model_handshake_and_explicit_nonphysical_proof(self):
        with tempfile.TemporaryDirectory() as d:
            args=handshake(Path(d));proof=corroborate_model_hold(*args)
            self.assertFalse(proof['physical_acceptance'])
            self.assertFalse(proof['actual_host_libusb_hold_acceptance'])
            self.assertEqual(proof['usb_record'],42)

    def test_scope_hash_timer_and_counter_forgery_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=handshake(Path(d))
            for change in ['live','host-method','hash','bounded','counter-bool','missing-marker','duplicate']:
                record,probe,reply,stderr=copy.deepcopy(base)
                if change=='live':probe['synthetic_support']=False
                if change=='host-method':record['method']='QMP_HOLD_ACTUAL_SUCCESSFUL_IN81'
                if change=='hash':reply['usb_sha256']='b'*64
                if change=='bounded':stderr=stderr.replace('bounded=0','bounded=1')
                if change=='counter-bool':record['observations'][1]['state'][PROPERTIES[2]]=True
                if change=='missing-marker':probe['markers'].pop()
                if change=='duplicate':stderr+=stderr.splitlines()[0]+'\n'
                with self.subTest(change=change),self.assertRaises(ValueError):corroborate_model_hold(record,probe,reply,stderr)

    def test_waits_for_idle_and_refuses_expired_or_mistyped_state(self):
        with tempfile.TemporaryDirectory() as d:
            coordinator=ModelHoldCoordinator(Path(d),{});coordinator.folder.mkdir();monitor=Monitor()
            write_marker(coordinator.folder/'hold-arm_ready.json',dict(hold_phase='arm_ready',wall_ns=1))
            monitor.armable=False;coordinator.poll(monitor)
            self.assertEqual(coordinator.phase,'arm_ready')
            self.assertFalse((coordinator.folder/'hold-armed-ack.json').exists())
            monitor.state[PROPERTIES[2]]=True
            with self.assertRaises(ValueError):coordinator.poll(monitor)
