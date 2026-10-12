# SPDX-License-Identifier: GPL-2.0-only
"""Negative evidence fixtures, never real connection or RF qualification."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws73_capture import CaptureError, marker_data
from ws73_north_star import parse_match
from ws73_connection_control import corroborate, result


def terminal(owner, operation, handle=0):
    return f"NativeConnectionResult: generation={owner['generation']} request={operation} operation={operation} state=4 errno=0 fault=0 command_status=0 outcome_status=0 handle={handle} flags=7\n"


def fixture():
    owners=[dict(bus=1,device=2,generation=1,address='00:01:09:32:54:CD'),
            dict(bus=1,device=4,generation=2,address='00:01:09:32:54:F9')]
    run=dict(commands=[],connection_control=dict(status='CONNECTION_CONTROL_EVIDENCE_PENDING',phases=[]))
    capture=dict(commands=[],native_events=[],complete=[],reports=[])
    for n,(caller,peer) in enumerate([owners,owners[::-1]]):
        phase=dict(caller=caller,peer=peer,peer_address_type=0,end_wall_ns=100+n*100)
        run['connection_control']['phases'].append(phase)
        phase['advertisement_command']=len(run['commands'])
        run['commands'].append(dict(args=['slctl','advertise','connectable'],exit=0,start_wall_ns=n*100+1,end_wall_ns=n*100+6))
        phase['policy_query_command']=len(run['commands'])
        run['commands'].append(dict(args=['slctl','show'],exit=0,stdout='  Radio policy: version=3 adv_slots=1200..1200 tx_power_dbm=127 scan_slots=1600/800\n'))
        body=bytearray(49);body[1]=1;body[2]=2;body[3:6]=(1200).to_bytes(3,'little');body[6:9]=body[3:6];body[9]=7
        body[12:18]=bytes.fromhex(peer['address'].replace(':',''));body[25]=127;body[33]=1;body[43:45]=(200).to_bytes(2,'little')
        identity=dict(bus=peer['bus'],device=peer['device'])
        capture['commands'].append(identity|dict(wall_ns=n*100+2,record=n*100+1,opcode=0x0c02,params=body.hex(),completion=dict(wall_ns=n*100+3)))
        capture['complete'].append(identity|dict(wall_ns=n*100+4,record=n*100+2,opcode=0x0c02,status=0,value='14'))
        phase['marker']=f'{n+1:032x}'
        phase['scan_command']=len(run['commands'])
        text=f"NativeDiscoveryMatch: generation={caller['generation']} seq=1 address={peer['address']} RSSI=-50 marker={phase['marker']} data={marker_data(phase['marker']).hex()} kernel_boottime_ns=123 elapsed_ms=1 lost=0\n"
        phase['scan_match']=parse_match(text)
        scan_result=f"NativeOperationResult: generation={caller['generation']} request=9 operation=3 state=3 errno=0 status=0x00 opcode=0x1002 step=1/2 power=0 power_valid=0 adv=1 scan=2 profile=1\n"
        run['commands'].append(dict(stdout=text+scan_result,exit=0,start_wall_ns=n*100+6,end_wall_ns=n*100+8))
        capture['reports'].append(dict(bus=caller['bus'],device=caller['device'],wall_ns=n*100+7,address=peer['address'],rssi=-50,data=marker_data(phase['marker']).hex()))
        phase['scan_stop_command']=len(run['commands'])
        stop_result=f"NativeOperationResult: generation={caller['generation']} request=10 operation=4 state=3 errno=0 status=0x00 opcode=0x1002 step=0/1 power=0 power_valid=0 adv=1 scan=1 profile=1\n"
        run['commands'].append(dict(stdout=stop_result,exit=0,start_wall_ns=n*100+8,end_wall_ns=n*100+10))
        identity=dict(bus=caller['bus'],device=caller['device'])
        capture['commands'].append(identity|dict(wall_ns=n*100+8,record=n*100+3,opcode=0x1002,params='0000',completion=dict(wall_ns=n*100+9)))
        capture['complete'].append(identity|dict(wall_ns=n*100+9,record=n*100+4,opcode=0x1002,status=0,value=''))
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

    def test_nonconnectable_announcement_never_qualifies_connection_gate(self):
        run,capture=fixture()
        for offset in [1,33]:
            bad=copy.deepcopy(capture);body=bytearray.fromhex(bad['commands'][0]['params']);body[offset]=0;bad['commands'][0]['params']=body.hex()
            with self.subTest(offset=offset),self.assertRaises(CaptureError):corroborate(run,bad)

    def test_successful_status_without_captured_connectable_air_report_is_rejected(self):
        run,capture=fixture()
        capture['reports'].pop(0)
        with self.assertRaisesRegex(CaptureError,'independently heard'):corroborate(run,capture)

    def test_negotiable_record_requires_its_distinct_actual_wire_posture(self):
        run,capture=fixture();run['connection_control']['advertising_kind']='negotiable-t'
        for phase in run['connection_control']['phases']:
            run['commands'][phase['advertisement_command']]['args'][-1]='negotiable'
        with self.assertRaises(CaptureError):corroborate(run,capture)
        for command in capture['commands']:
            if command['opcode']==0x0c02:
                body=bytearray.fromhex(command['params']);body[1]=3;body[2]=0;body[33]=0;body[34]=1
                body[37:39]=(100).to_bytes(2,'little');body[39:41]=body[37:39];command['params']=body.hex()
        self.assertEqual(len(corroborate(run,capture)),2)


if __name__=='__main__':unittest.main()
