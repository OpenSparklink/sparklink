# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic syscall/wire verifier fixtures; never hardware qualification."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'bindings/python'))
from sparklink.structs import SleControllerSnapshot, SleManagementQuery, SleDiscoveryResult
from ws73_capture import CaptureError, marker_data, read_capture
from ws73_daemon_crash import STATUS, corroborate, verify_records, record_phase
from test_ws73_north_star import identity, aggregate, pcap, transmit
from test_ws73_initialization_lifecycle import result
import ws73_target


def fixture():
    a,b=identity(1),identity(2);a['index']=0;b['index']=1
    # Keep synthetic paths self-consistent with the chosen actual index fields.
    for o in [a,b]:o['path']=f'/org/sparklink/slk{o["index"]}_g{o["generation"]}'
    owners=[a,b];slctl={'path':'/usr/bin/slctl'};records=[]
    run={'slctl':slctl,'initial':owners,'daemon_before':{'pid':101,'start_ticks':2},
        'bus_before':{'owner':':1.2','pid':101,'uid':0},'rounds':[{'command_indices':[0]}],
        'commands':[{'start_wall_ns':1_000_000_000}]}
    record={'version':1,'status':STATUS,'slctl':slctl,'physical_acceptance':False,
        'automatic_recovery_acceptance':False,'whole_managed_acceptance':False,'phases':[]}
    def observation(o,phase):
        adv=2 if phase=='before' and o==a else 1;scan=2 if phase=='before' and o==b else 1
        state=0 if phase=='free' else 1
        snapshot=SleControllerSnapshot(version=1,dev_index=o['index'],generation=o['generation'],flags=1,profile=1)
        mgmt=SleManagementQuery(version=1,generation=o['generation'],state=state,mode=state)
        radio=SleDiscoveryResult(version=1,dev_index=o['index'],generation=o['generation'],profile=1,radio_adv=adv,radio_scan=scan)
        start={'before':200_000_000,'free':280_000_000,'after':650_000_000}[phase]
        return dict(start_wall_ns=start,end_wall_ns=start+1_000_000,index=o['index'],generation=o['generation'],flags=1,profile=1,error=0,
            management=dict(state=state,mode=state,lease=0,flags=0,error=0,status=0,opcode=0),
            radio=dict(version=1,generation=o['generation'],adv=adv,scan=scan,error=0),
            raw_snapshot=bytes(snapshot).hex(),raw_management=bytes(mgmt).hex(),raw_radio=bytes(radio).hex())
    def command(args,stdout,start,end):return dict(args=args,stdout=stdout,stderr='',exit=0,start_wall_ns=start,end_wall_ns=end)
    for phase,start,end,pid in [('before',100_000_000,220_000_000,100),('free',230_000_000,300_000_000,100),('after',310_000_000,720_000_000,101)]:
        entry=dict(phase=phase,start_wall_ns=start,end_wall_ns=end,pid=pid,owners=owners,
            observations=[observation(o,phase) for o in owners],commands=[]);record['phases'].append(entry)
        if phase=='free':entry.update(killed_exit=137,polls=[entry['observations']]);continue
        owner=':1.1' if phase=='before' else ':1.2'
        entry.update(daemon=dict(pid=pid,start_ticks=1 if phase=='before' else 2),bus=dict(owner=owner,pid=pid,uid=0),
            process_status='Name:\tslkd\nUid:\t0\t0\t0\t0\n',
            application_status='Uid:\t1000\t1000\t1000\t1000\n'+''.join(c+':\t0000000000000000\n' for c in ['CapInh','CapPrm','CapEff','CapAmb']))
        t=110_000_000 if phase=='before' else 660_000_000
        entry['commands'].append(command(['/usr/bin/slctl','daemon'],f'DaemonIdentity: owner={owner} pid={pid} uid=0\n',t,t+1_000_000))
    marker='a'*32
    before,free,after=record['phases']
    before['commands'].append(command(['/usr/bin/slctl','--adapter',a['path'],'advertise','on'],
        f'NativeAdvertisementAccepted: request=3 marker={marker} data={marker_data(marker).hex()}\n'+result(a,1,3),130_000_000,150_000_000))
    before['commands'].append(command(['/usr/bin/slctl','--adapter',b['path'],'scan','on'],result(b,3,3),160_000_000,180_000_000))
    for i in range(4):
        o=owners[i//2];domain,op=('advertise',5) if i%2==0 else ('scan',6);t=670_000_000+i*5_000_000
        row=command(['/usr/bin/slctl','--adapter',o['path'],domain,'initialized-off'],'',t,t+1_000_000);row.update(exit=1,stderr='error: org.freedesktop.DBus.Error.UnknownObject: initializer provenance absent or invalidated\n');after['commands'].append(row)
    def emit(o,t,opcode,params,value=b''):
        transmit(records,o['device'],t,opcode,params)
        payload=b'\xa2\x02\x00'+(4+len(value)).to_bytes(2,'little')+opcode.to_bytes(2,'little')+b'\1\0'+value
        records.append((1,o['device'],t+10_000,aggregate(payload),'C',0x81,0))
    def parameters(o):
        adv=bytearray(49);adv[12:18]=bytes.fromhex(o['address'].replace(':',''))
        scan=bytearray(8);scan[2]=1
        return bytes(adv),bytes(scan)
    adv,_=parameters(a);_,scan=parameters(b)
    for n,(op,p,value) in enumerate([(0xc02,adv,b'\x14'),(0xc03,bytes([0,3,43])+marker_data(marker),b''),(0xc05,b'\1\0\0\0\0',b'')]):emit(a,135_000_000+n*100_000,op,p,value)
    emit(b,165_000_000,0x1001,scan);emit(b,165_100_000,0x1002,b'\1\0')
    emit(a,250_000_000,0xc05,bytes(5));emit(b,260_000_000,0x1002,bytes(2))
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'synthetic.pcap';path.write_bytes(pcap(records));capture=read_capture(path,[(1,o['device']) for o in owners])
    return record,run,capture


class DaemonCrashTests(unittest.TestCase):
    def test_host_recorder_refused_before_creating_output_or_running_application(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ws73_daemon_crash.Path.read_text',return_value='no-private-crash-mode'):
            folder=Path(tmp)/'never'
            with self.assertRaisesRegex(ValueError,'explicit private native VM'):
                record_phase(lambda *a,**k:self.fail('host application invoked'),[],'before',1,folder=folder)
            self.assertFalse(folder.exists())

    def test_complete_synthetic_last_file_cleanup_and_successor(self):
        record,run,capture=fixture();proof=corroborate(record,run,capture)
        self.assertEqual(proof['selected_cleanup_commands'],2);self.assertEqual(proof['successor_initializer_refusals'],4)
        self.assertFalse(proof['held_inflight_acceptance']);self.assertFalse(proof['automatic_recovery_acceptance'])

    def test_rejects_forged_or_unbounded_identity_state_and_observations(self):
        for change in ['pid','bus','generation','status','lease','radio','raw','caps','late','kill','poll','whole','cached-success']:
            record,run,capture=fixture();before,free,after=record['phases']
            if change=='pid':after['pid']=100
            if change=='bus':after['bus']['owner']=':1.1'
            if change=='generation':after['owners']=copy.deepcopy(after['owners']);after['owners'][0]['generation']+=1
            if change=='status':record['status']='PASS'
            if change=='lease':free['observations'][0]['management']['lease']=5
            if change=='radio':free['observations'][0]['radio']['adv']=2
            if change=='raw':free['observations'][0]['raw_radio']='00'
            if change=='caps':after['application_status']=after['application_status'].replace('CapEff:\t0000000000000000','CapEff:\t0000000000000001')
            if change=='late':after['end_wall_ns']=21_000_000_000
            if change=='kill':free['killed_exit']=0
            if change=='poll':free['polls']=[]
            if change=='whole':record['whole_managed_acceptance']=True
            if change=='cached-success':after['commands'][1].update(exit=0,stderr='',stdout=result(record['phases'][0]['owners'][0],5,4))
            with self.subTest(change=change),self.assertRaises(ValueError):verify_records(record,run)

    def test_requires_original_complete_and_no_redundant_cleanup(self):
        for change in ['missing','failed','extra','wrong-data','wrong-stop']:
            record,run,capture=fixture()
            cleanup=next(c for c in capture['commands'] if c['wall_ns']==249_998_000)
            if change=='missing':capture['complete']=[c for c in capture['complete'] if c['wall_ns']!=250_010_000]
            if change=='failed':next(c for c in capture['complete'] if c['wall_ns']==250_010_000)['status']=11
            if change=='extra':capture['commands'].append(copy.deepcopy(cleanup))
            if change=='wrong-data':next(c for c in capture['commands'] if c['opcode']==0xc03)['params']='00'
            if change=='wrong-stop':cleanup['params']='0100000000'
            with self.subTest(change=change),self.assertRaises(CaptureError):corroborate(record,run,capture)

    def test_rejects_mixed_modes_before_output(self):
        for changes in [dict(command='support'),dict(qmp_hotplug=False),dict(fault_recovery=True),dict(parallel_pairs=True),dict(observer_policy=True),dict(initializer_lifecycle=True),dict(daemon_cancel_remove=True),dict(managed_partial_case='release')]:
            with self.subTest(changes=changes),tempfile.TemporaryDirectory() as tmp:
                args=dict(command='run',qmp_hotplug=True,daemon_crash=True,output=Path(tmp)/'never');args.update(changes)
                with patch.object(ws73_target,'ordinary_identity'),self.assertRaisesRegex(ValueError,'daemon crash requires separate'):ws73_target._run(SimpleNamespace(**args))
                self.assertFalse(args['output'].exists())


if __name__=='__main__':unittest.main()
