# SPDX-License-Identifier: GPL-2.0-only
"""Supervisor boundary fixtures only; no role switch, daemon or device run."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_application_role import read_json,supervise,validate_request
from ws73_capture import CaptureError


def request():
    return dict(status='RUNNING',start_wall_ns=1,tools={},applications=[],phase=0,request='00000000'+'12'*57,reply='00000000'+'34'*57,
                owners=[dict(owner=dict(index=i,generation=i+1),object=dict(path=f'/org/sparklink/slk{i}_g{i+1}/peer_t00_01020304050{i}/link_0000000000000001'))for i in (0,1)])


class SupervisorBoundary(unittest.TestCase):
    def test_bounded_canonical_input_and_no_arbitrary_command(self):
        value=request();validate_request(value,0)
        for kind in ['phase','length','echo','owner','path','generation']:
            bad=copy.deepcopy(value)
            if kind=='phase':bad['phase']=2
            elif kind=='length':bad['request']+='00'
            elif kind=='echo':bad['reply']=bad['request']
            elif kind=='owner':bad['owners'][1]['owner']['index']=0
            elif kind=='path':bad['owners'][0]['object']['path']='/bin/sh'
            elif kind=='generation':bad['owners'][0]['owner']['generation']=0
            with self.subTest(kind=kind),self.assertRaises(CaptureError):validate_request(bad,0)

    def test_file_owner_budget_regular_mode_and_no_symlink(self):
        with tempfile.TemporaryDirectory()as temporary:
            path=Path(temporary)/'record';path.write_text(json.dumps(request()));path.chmod(0o600)
            self.assertEqual(read_json(path,os.getuid()),request())
            with self.assertRaises(CaptureError):read_json(path,os.getuid()+1)
            with self.assertRaises(CaptureError):read_json(path,os.getuid(),limit=1)
            path.chmod(0o622)
            with self.assertRaises(CaptureError):read_json(path,os.getuid())
            link=Path(temporary)/'alias';link.symlink_to(path)
            with self.assertRaises(OSError):read_json(link,os.getuid())

    def test_no_host_or_ordinary_launcher(self):
        with patch('ws73_application_role.os.geteuid',return_value=1000),self.assertRaises(CaptureError):supervise(1)
