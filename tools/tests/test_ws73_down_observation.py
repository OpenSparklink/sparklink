# SPDX-License-Identifier: GPL-2.0-only
"""Bounded observation/verifier tests, no kernel or physical acceptance."""
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_connection_control import await_down_properties, corroborate_down_property
from ws73_capture import CaptureError


class Clock:
    def __init__(self): self.now=0.0
    def monotonic(self): return self.now
    def time_ns(self): return 1_000_000_000+round(self.now*1_000_000_000)
    def sleep(self,seconds): self.now+=seconds


class Run:
    def __init__(self,clock,delays): self.clock=clock;self.delays=delays;self.data={'commands':[]}
    def save(self): pass
    def ctl(self,owner,operation,address):
        start=self.clock.time_ns();self.clock.now+=.02
        row={'args':['slctl','--adapter',owner['path'],operation,address],
             'start_wall_ns':start,'end_wall_ns':self.clock.time_ns(),'exit':0,
             'stdout':f"  Connected: {'false' if self.clock.now>=self.delays[owner['path']] else 'true'}\n"}
        self.data['commands'].append(row);return row


def execute(delays):
    a={'path':'/a','address':'A'};b={'path':'/b','address':'B'};clock=Clock();run=Run(clock,delays);phase={}
    with patch('ws73_connection_control.time',SimpleNamespace(monotonic=clock.monotonic,time_ns=clock.time_ns,sleep=clock.sleep)):
        await_down_properties(run,phase,a,b)
    return run,phase,a,b


class Observation(unittest.TestCase):
    def test_delayed_physical_peer_has_original_bounded_receipt(self):
        run,phase,a,b=execute({'/a':0,'/b':1.11})
        self.assertEqual(phase['down_property_observation']['budget_seconds'],5)
        proof=corroborate_down_property(run.data,phase,b,{'wall_ns':2_110_000_000})
        self.assertGreaterEqual(proof['property_end_wall_ns'],proof['physical_down_wall_ns'])
        self.assertLessEqual(proof['property_end_wall_ns'],proof['deadline_wall_ns'])

    def test_second_owner_does_not_get_refreshed_deadline(self):
        clock=Clock();run=Run(clock,{'/a':4.8,'/b':6});phase={};a={'path':'/a','address':'A'};b={'path':'/b','address':'B'}
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
