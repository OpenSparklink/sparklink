# SPDX-License-Identifier: GPL-2.0-only
"""Bounded observation/verifier tests, no kernel or physical acceptance."""
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_connection_control import (await_down_properties, corroborate_down_property,
                                    requested_down_failure_observation)
from ws73_capture import CaptureError


class Clock:
    def __init__(self): self.now=0.0
    def monotonic(self): return self.now
    def time_ns(self): return 1_000_000_000+round(self.now*1_000_000_000)
    def sleep(self,seconds): self.now+=seconds


class Run:
    def __init__(self,clock,delays): self.clock=clock;self.delays=delays;self.data={'commands':[]}
    def save(self): pass
    def ctl(self,owner,operation):
        start=self.clock.time_ns();self.clock.now+=.02
        remote='BB:BB:BB:BB:BB:BB' if owner['path']=='/a' else 'AA:AA:AA:AA:AA:AA'
        connected=self.clock.now<self.delays[owner['path']]
        text=f"NativeLinksSnapshot: generation={owner['generation']} event_seq=2 revision=2 flags=1 errno=0\n"
        if connected:text+=f'NativeLink: lifetime=1 handle=0 role=0 type=0 address={remote}\n'
        row={'args':['slctl','--adapter',owner['path'],operation],
             'start_wall_ns':start,'end_wall_ns':self.clock.time_ns(),'exit':0,
             'stdout':text}
        self.data['commands'].append(row);return row


def execute(delays):
    a={'path':'/a','address':'AA:AA:AA:AA:AA:AA','generation':1};b={'path':'/b','address':'BB:BB:BB:BB:BB:BB','generation':2};clock=Clock();run=Run(clock,delays);phase={}
    with patch('ws73_connection_control.time',SimpleNamespace(monotonic=clock.monotonic,time_ns=clock.time_ns,sleep=clock.sleep)):
        await_down_properties(run,phase,a,b)
    return run,phase,a,b


class Observation(unittest.TestCase):
    def test_old_missing_or_duplicate_guest_inputs_are_rejected(self):
        import ws73_target as target
        rows=[target.file_record(target.HERE/name) for name in [
            'ws73_connection_control.py','ws73_target_control.py','ws73_target_init.sh']]
        target.validate_down_failure_inputs({'inputs':rows})
        for selected in [[],rows[:-1],rows+[rows[0]],
                         [dict(r,sha256='0'*64)if i==0 else r for i,r in enumerate(rows)]]:
            with self.subTest(rows=len(selected)),self.assertRaises(ValueError):
                target.validate_down_failure_inputs({'inputs':selected})

    def test_passive_capture_is_explicit_bounded_and_separate_from_other_gates(self):
        args=SimpleNamespace(connection_down_failure_observe_seconds=6,passthrough=True,
                             connection_verify=True,channel_socket_verify=True)
        self.assertEqual(requested_down_failure_observation(args),6)
        self.assertEqual(requested_down_failure_observation(SimpleNamespace()),0)
        for key,value in [('connection_down_failure_observe_seconds',True),
                          ('connection_down_failure_observe_seconds',7),
                          ('passthrough',False),('channel_socket_verify',False),
                          ('ssap_initialization_verify',True),('security_agent','approve')]:
            with self.subTest(key=key,value=value):
                bad=SimpleNamespace(**vars(args));setattr(bad,key,value)
                with self.assertRaises(ValueError):requested_down_failure_observation(bad)

    def test_passive_window_keeps_original_failure_and_issues_no_control_command(self):
        clock=Clock();run=Run(clock,{'/a':0,'/b':6});phase={}
        run.args=SimpleNamespace(connection_down_failure_observe_seconds=6)
        a={'path':'/a','address':'AA:AA:AA:AA:AA:AA','generation':1}
        b={'path':'/b','address':'BB:BB:BB:BB:BB:BB','generation':2}
        windows=[]
        def sleep(seconds):
            if seconds==6:
                self.assertEqual(run.data['status'],'FAIL')
                windows.append(len(run.data['commands']))
            clock.sleep(seconds)
        with patch('ws73_connection_control.time',SimpleNamespace(
                monotonic=clock.monotonic,time_ns=clock.time_ns,sleep=sleep)):
            with self.assertRaisesRegex(CaptureError,'shared budget'):
                await_down_properties(run,phase,a,b)
        observation=phase['down_property_observation'];row=observation['passive_failure_capture']
        self.assertEqual(observation['budget_seconds'],5)
        self.assertEqual(len(observation['receipts']),1)
        self.assertEqual(row['status'],'FINISHED_ORIGINAL_GATE_FAIL')
        self.assertEqual(row['command_count_before'],row['command_count_after'])
        self.assertEqual(windows,[len(run.data['commands'])])
        self.assertEqual(row['end_monotonic_ns']-row['start_monotonic_ns'],6_000_000_000)
        with self.assertRaises(CaptureError):
            corroborate_down_property(run.data,phase,b,{'wall_ns':7_000_000_000})

    def test_interrupting_passive_window_is_not_a_completed_observation(self):
        clock=Clock();run=Run(clock,{'/a':0,'/b':6});phase={}
        run.args=SimpleNamespace(connection_down_failure_observe_seconds=6)
        a={'path':'/a','address':'AA:AA:AA:AA:AA:AA','generation':1}
        b={'path':'/b','address':'BB:BB:BB:BB:BB:BB','generation':2}
        def sleep(seconds):
            if seconds==6:raise KeyboardInterrupt()
            clock.sleep(seconds)
        with patch('ws73_connection_control.time',SimpleNamespace(
                monotonic=clock.monotonic,time_ns=clock.time_ns,sleep=sleep)):
            with self.assertRaises(KeyboardInterrupt):await_down_properties(run,phase,a,b)
        self.assertEqual(run.data['status'],'FAIL')
        self.assertEqual(phase['down_property_observation']['passive_failure_capture']['status'],
                         'INTERRUPTED_ORIGINAL_GATE_FAIL')

    def test_delayed_physical_peer_has_original_bounded_receipt(self):
        run,phase,a,b=execute({'/a':0,'/b':1.11})
        self.assertEqual(phase['down_property_observation']['budget_seconds'],5)
        proof=corroborate_down_property(run.data,phase,b,{'wall_ns':2_110_000_000})
        self.assertGreaterEqual(proof['property_end_wall_ns'],proof['physical_down_wall_ns'])
        self.assertLessEqual(proof['property_end_wall_ns'],proof['deadline_wall_ns'])

    def test_second_owner_does_not_get_refreshed_deadline(self):
        clock=Clock();run=Run(clock,{'/a':4.8,'/b':6});phase={};a={'path':'/a','address':'AA:AA:AA:AA:AA:AA','generation':1};b={'path':'/b','address':'BB:BB:BB:BB:BB:BB','generation':2}
        with patch('ws73_connection_control.time',SimpleNamespace(monotonic=clock.monotonic,time_ns=clock.time_ns,sleep=clock.sleep)):
            with self.assertRaises(CaptureError): await_down_properties(run,phase,a,b)
        self.assertEqual(len(phase['down_property_observation']['receipts']),1)
        self.assertLess(clock.now,5.1)

    def test_verifier_rejects_early_false_expiry_missing_or_wrong_owner(self):
        run,phase,a,b=execute({'/a':0,'/b':1.11})
        with self.assertRaises(CaptureError):corroborate_down_property(run.data,phase,b,{'wall_ns':9_000_000_000})
        bad=copy.deepcopy(phase);bad['down_property_observation']['end_wall_ns']=6_000_000_001
        with self.assertRaises(CaptureError):corroborate_down_property(run.data,bad,b,{'wall_ns':2_110_000_000})
        bad=copy.deepcopy(phase);bad['down_property_observation']['receipts'].pop()
        with self.assertRaises(CaptureError):corroborate_down_property(run.data,bad,b,{'wall_ns':2_110_000_000})
        bad=copy.deepcopy(run.data);bad['commands'][-1]['args'][2]='/wrong'
        with self.assertRaises(CaptureError):corroborate_down_property(bad,phase,b,{'wall_ns':2_110_000_000})

    def test_historical_device_receipt_remains_a_separate_read_only_decoder(self):
        run,phase,a,b=execute({'/a':0,'/b':0})
        phase['down_property_observation']['version']=1
        phase['down_property_observation'].pop('source')
        for receipt in phase['down_property_observation']['receipts']:
            row=run.data['commands'][receipt['command']]
            row['args']=['slctl','--adapter',receipt['owner']['path'],'info',receipt['remote_address']]
            row['stdout']='  Connected: false\n'
        self.assertIsNotNone(corroborate_down_property(run.data,phase,b,{'wall_ns':1_000_000_000}))
