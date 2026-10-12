# SPDX-License-Identifier: GPL-2.0-only
"""Negative evidence fixtures, never real connection or RF qualification."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError
from ws73_connection_control import corroborate, result


def terminal(owner, operation, handle=0):
    return f"NativeConnectionResult: generation={owner['generation']} request={operation} operation={operation} state=4 errno=0 fault=0 command_status=0 outcome_status=0 handle={handle} flags=7\n"


def fixture():
    owners=[dict(bus=1,device=2,generation=1,address='00:01:09:32:54:CD'),
            dict(bus=1,device=4,generation=2,address='00:01:09:32:54:F9')]
    run=dict(commands=[],connection_control=dict(status='CONNECTION_CONTROL_EVIDENCE_PENDING',phases=[]))
    capture=dict(commands=[],native_events=[])
    for n,(caller,peer) in enumerate([owners,owners[::-1]]):
        phase=dict(caller=caller,peer=peer,peer_address_type=0,end_wall_ns=100+n*100)
        run['connection_control']['phases'].append(phase)
        for operation,opcode,key,event in [(1,0x1401,'connect',0x15),(2,0x1403,'disconnect',5)]:
            start=n*100+operation*10
            phase[key+'_command']=len(run['commands'])
            text=terminal(caller,operation)
            run['commands'].append(dict(stdout=text,exit=0,start_wall_ns=start,end_wall_ns=start+5))
            phase[key]=result(text,caller,operation)
            params=(b'\x00\x00\x00'+bytes.fromhex(peer['address'].replace(':',''))+bytes(18)) if operation==1 else b'\x00\x00\x13'
            identity=dict(bus=caller['bus'],device=caller['device'],wall_ns=start+1)
            capture['commands'].append(identity|dict(opcode=opcode,params=params.hex(),completion=dict(wall_ns=start+2)))
            capture['native_events'].append(identity|dict(event=1,params=(opcode.to_bytes(2,'little')+b'\x01\x00').hex()))
            for owner,remote in [(caller,peer),(peer,caller)]:
                body=b'\x00\x00\x00'+(b'\x00\x00'+bytes.fromhex(remote['address'].replace(':','')) if operation==1 else b'\x13')
                capture['native_events'].append(dict(bus=owner['bus'],device=owner['device'],wall_ns=start+3,event=event,params=body.hex()))
    return run,capture


class ConnectionEvidenceTests(unittest.TestCase):
    def test_both_roles_need_three_evidences_and_both_physical_peers(self):
        run,capture=fixture()
        self.assertEqual(len(corroborate(run,capture)),2)
        for key in ['commands','native_events']:
            bad=copy.deepcopy(capture);bad[key].pop(0)
            with self.subTest(key=key),self.assertRaises(CaptureError):corroborate(run,bad)

    def test_false_or_ambiguous_terminal_is_rejected(self):
        owner=dict(generation=1)
        text=terminal(owner,1)
        for bad in [text+text,text.replace('flags=7','flags=3'),text.replace('errno=0','errno=125'),text.replace('generation=1','generation=2')]:
            with self.subTest(text=bad),self.assertRaises(CaptureError):result(bad,owner,1)

    def test_wrong_raw_peer_status_handle_or_duplicate_is_rejected(self):
        run,capture=fixture()
        for mode in ['peer','status','handle','duplicate']:
            bad=copy.deepcopy(capture)
            event=bad['native_events'][1]
            if mode=='peer':event['params']=event['params'][:-2]+'ff'
            elif mode=='status':bad['native_events'][0]['params']='01140101'
            elif mode=='handle':event['params']='000100'+event['params'][6:]
            else:bad['native_events'].append(copy.deepcopy(event))
            with self.subTest(mode=mode),self.assertRaises(CaptureError):corroborate(run,bad)


if __name__=='__main__':unittest.main()
