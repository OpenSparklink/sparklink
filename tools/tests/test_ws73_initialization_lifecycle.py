# SPDX-License-Identifier: GPL-2.0-only
"""Explicit synthetic lifecycle/byte fixtures; never real device evidence."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_capture import CaptureError,marker_data,read_capture
from ws73_initialization_lifecycle import SCOPE,STATUS,EVICTION_CYCLES,verify_records,corroborate_wire
from test_ws73_north_star import identity,aggregate,pcap,transmit
import ws73_target


def result(owner, operation, request):
    shape={1:(0x0c05,2,3,1,2,1),2:(0x0c05,0,1,0,1,1),3:(0x1002,1,2,0,1,2),4:(0x1002,0,1,0,1,1),5:(0x0c05,1,2,1,1,1),6:(0x1002,2,3,0,1,1)}[operation]
    opcode,step,count,power,adv,scan=shape
    return (f'NativeOperationResult: generation={owner["generation"]} request={request} operation={operation} state=3 errno=0 status=0x00 '
            f'opcode=0x{opcode:04x} step={step}/{count} power={20 if power else 0} power_valid={power} adv={adv} scan={scan} profile=1\n')


def fixture():
    a,b,new=identity(1),identity(2),identity(3)
    run={'slctl':{'path':'/usr/bin/slctl'},'initial':[a,b],'replacement':new,'commands':[],
         'initialization_off_confirmations':[],'rounds':[]}
    records=[]

    def emit(owner, moment, opcode, params, value=b''):
        transmit(records,owner['device'],moment,opcode,params)
        complete=b'\xa2\x02\x00'+(4+len(value)).to_bytes(2,'little')+opcode.to_bytes(2,'little')+b'\1\0'+value
        records.append((1,owner['device'],moment,aggregate(complete),'C',0x81,0))

    def wire(owner, moment, operation, marker=None):
        adv=bytearray(49);adv[12:18]=bytes.fromhex(owner['address'].replace(':',''))
        steps={5:[(0x0c02,bytes(adv),b'\x14'),(0x0c05,bytes(5),b'')],
               6:[(0x1001,bytes(8),b''),(0x1002,b'\1\0',b''),(0x1002,b'\0\0',b'')],
               3:[(0x1001,bytes(8),b''),(0x1002,b'\1\0',b'')],4:[(0x1002,b'\0\0',b'')],
               2:[(0x0c05,bytes(5),b'')]}
        if operation==1:steps[1]=[(0x0c02,bytes(adv),b'\x14'),(0x0c03,bytes([0,3,43])+marker_data(marker),b''),(0x0c05,b'\1\0\0\0\0',b'')]
        for n,(opcode,params,value) in enumerate(steps[operation]):emit(owner,moment+n*10_000,opcode,params,value)

    for o in [a,b,new]:
        wire(o,500_000_000,5);wire(o,510_000_000,6)

    def command(owner, words, output='', error=None, operation=None, request=None, marker=None):
        index=len(run['commands']);start=1_000_000_000+index*1_000_000;end=start+500_000
        if operation:
            output=result(owner,operation,request)
            if operation==1:output=f'NativeAdvertisementAccepted: request={request} marker={marker} data={marker_data(marker).hex()}\n'+output
            wire(owner,start+100_000,operation,marker)
        run['commands'].append({'args':['/usr/bin/slctl','--adapter',owner['path'],*words],
            'exit':1 if error else 0,'stdout':output,'stderr':error or '',
            'start_wall_ns':start,'end_wall_ns':end,'start_monotonic_ns':start,'end_monotonic_ns':end})
        return index

    def initial(owner, operation, request):
        domain='advertise' if operation==5 else 'scan'
        index=command(owner,[domain,'initialized-off'],result(owner,operation,request))
        run['initialization_off_confirmations'].append({'identity':owner,'domain':domain,'operation':operation,'request':request,'query_command':index})
        return index

    def status(owner):
        return f'NativeManagementStatus: generation={owner["generation"]} mode=1 state=1 flags=1 errno=0 status=0x00 opcode=0x0000\n'

    before={'target':a,'peer':b,'initial_queries':[initial(a,5,11),initial(a,6,12),initial(b,5,21),initial(b,6,22)]}
    before['peer_scan_on']=command(b,['scan','on'],operation=3,request=30)
    before['management_before']=command(a,['management'],status(a))
    before['cancel']=command(a,['cancel-discovery'],f'NativePoliciesCancelRequest: generation=1\nNativePoliciesCancelled: generation=1\n')
    before['invalidated_queries']=[command(a,[domain,'initialized-off'],error='initializer provenance absent or invalidated') for domain in ['advertise','scan']]
    before['historical_queries']=[command(a,['result',str(request)],result(a,op,request)) for op,request in [(5,11),(6,12)]]
    before['management_after']=command(a,['management'],status(a))
    before['peer_still_on']=command(b,['result','30'],result(b,3,30))
    before['peer_untouched_advertising']=initial(b,5,21)
    before['peer_stop']=command(b,['scan','off'],operation=4,request=31)
    before['peer_after']=b
    run['rounds'].append({'phase':'initial','command_indices':[len(run['commands'])]})
    command(a,['fixture-only-rf-phase-marker'])
    after={'target':new,'peer':b}
    after['retired_queries']=[command(a,[domain,'initialized-off'],error='not a live registration') for domain in ['advertise','scan']]
    after['initial_queries']=[initial(new,5,41),initial(new,6,42)]
    after['peer_scan_on']=command(b,['scan','on'],operation=3,request=43)
    after['eviction_commands']=[]
    for n in range(EVICTION_CYCLES*2):
        op=2 if n%2 else 1
        after['eviction_commands'].append(command(new,['advertise','off' if n%2 else 'on'],operation=op,request=100+n,marker=f'{n+1:032x}'))
    after['evicted_initializer_query']=command(new,['scan','initialized-off'],error='initializer result absent or evicted')
    after['evicted_general_query']=command(new,['result','42'],error='operation absent or evicted')
    after['current_off_query']=command(new,['result','163'],result(new,2,163))
    after['peer_still_on']=command(b,['result','43'],result(b,3,43))
    after['peer_stop']=command(b,['scan','off'],operation=4,request=44)
    after['peer_after']=b
    run['rounds'].append({'phase':'replug','command_indices':[len(run['commands'])]})
    command(new,['fixture-only-rf-phase-marker'])
    run['initialization_lifecycle']={'version':1,'scope':SCOPE,'status':STATUS,'eviction_cycles':EVICTION_CYCLES,
        'physical_acceptance':False,'automatic_recovery_acceptance':False,'private_file_close_dup_acceptance':False,
        'withdrawal':before,'replacement_eviction':after}
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'synthetic.pcap';path.write_bytes(pcap(records));capture=read_capture(path,{(1,o['device']) for o in [a,b,new]})
    return run,capture


class LifecycleTests(unittest.TestCase):
    def test_separate_real_mode_refuses_mixed_gates_before_output(self):
        for changes in [dict(command='support'),dict(qmp_hotplug=False),dict(fault_recovery=True),
                        dict(parallel_pairs=True),dict(daemon_cancel_remove=True),dict(diagnostic_cancel_verify=True),
                        dict(managed_partial_case='release'),dict(daemon_hold_case='cancel-busy')]:
            with self.subTest(changes=changes),tempfile.TemporaryDirectory() as tmp:
                args=dict(command='run',qmp_hotplug=True,initializer_lifecycle=True,output=Path(tmp)/'never')
                args.update(changes)
                with patch.object(ws73_target,'ordinary_identity'),self.assertRaisesRegex(ValueError,'initializer lifecycle requires separate'):
                    ws73_target._run(SimpleNamespace(**args))
                self.assertFalse(args['output'].exists())

    def test_synthetic_fixture_checks_all_wire_without_claiming_rf_or_private_fd(self):
        run,capture=fixture();proof=corroborate_wire(run,capture)
        self.assertEqual(len(proof['real_eviction_business_operations']),64)
        self.assertFalse(proof['private_file_close_dup_acceptance'])
        self.assertFalse(proof['physical_acceptance'])

    def test_stale_history_eviction_and_peer_mutations_are_rejected(self):
        run,_=fixture();r=run['initialization_lifecycle'];b=r['withdrawal'];a=r['replacement_eviction']
        mutations=[lambda x:x['initialization_lifecycle'].update(private_file_close_dup_acceptance=True),
            lambda x:x['initialization_lifecycle']['replacement_eviction'].update(target=x['initial'][0]),
            lambda x:x['initialization_lifecycle']['replacement_eviction']['eviction_commands'].pop(),
            lambda x:x['commands'][b['historical_queries'][0]].update(stdout=result(identity(1),2,11)),
            lambda x:x['commands'][b['management_after']].update(stdout=x['commands'][b['management_after']]['stdout'].replace('flags=1','flags=0')),
            lambda x:x['commands'][b['cancel']].update(stdout='NativePoliciesCancelled: generation=2\n'),
            lambda x:x['commands'][a['evicted_initializer_query']].update(stderr='initializer provenance absent or invalidated'),
            lambda x:x['commands'][a['evicted_general_query']].update(exit=0,stdout=result(identity(3),6,42)),
            lambda x:x['commands'][a['peer_still_on']].update(stdout=result(identity(2),4,43)),
            lambda x:x['commands'][a['eviction_commands'][0]].update(stdout=x['commands'][a['eviction_commands'][0]]['stdout'].replace('status=0x00','status=0x0b')),
            lambda x:x['commands'][a['retired_queries'][0]].update(exit=0),
            lambda x:x['commands'][a['peer_scan_on']].update(args=['/usr/bin/slctl','--adapter',identity(3)['path'],'scan','on'])]
        for change in mutations:
            bad=copy.deepcopy(run);change(bad)
            with self.assertRaises((ValueError,CaptureError)):verify_records(bad)

    def test_missing_business_complete_redundant_handoff_and_peer_control_rejected(self):
        run,capture=fixture();r=run['initialization_lifecycle']
        bad=copy.deepcopy(capture);bad['complete']=bad['complete'][:-1]
        with self.assertRaises(CaptureError):corroborate_wire(run,bad)
        for section,owner,key in [('withdrawal',r['withdrawal']['target'],'cancel'),
                                  ('replacement_eviction',r['replacement_eviction']['peer'],'evicted_initializer_query')]:
            bad=copy.deepcopy(capture);row=copy.deepcopy(bad['commands'][0]);row.update(bus=owner['bus'],device=owner['device'],opcode=0x1002,
                wall_ns=run['commands'][r[section][key]]['start_wall_ns']);bad['commands'].append(row)
            with self.assertRaises(CaptureError):corroborate_wire(run,bad)


if __name__=='__main__':unittest.main()
