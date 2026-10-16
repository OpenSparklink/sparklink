# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic supervision/capture negatives, never actual Native acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_ws73_benchmark import fixture as reports_fixture
import ws73_socket_benchmark as gate
from ws73_capture import CaptureError
from ws73_target import run_exit_code


def fixture(share,mode='window'):
    rows=[];packets=[];record=1
    for phase in range(2):
        reports=reports_fixture(mode,count=20)
        owners=[dict(owner=dict(index=i,generation=7+i,path=f'/org/sparklink/slk{i}_g{7+i}',bus=1,device=2+i),object=dict(generation=7+i,lifetime=11+i,handle=0,path=f'/link{i}')) for i in range(2)]
        if phase:owners=owners[::-1];reports=reports[::-1] if mode=='duplex' else reports
        # Deliberately map identities to actual fixture ownership for role swap.
        row=dict(phase=phase,owners=owners,config=gate.configuration(mode),application_tool=dict(path='/bin/slktest',sha256='a'*64),start_wall_ns=phase*2000,status=gate.PENDING,applications=[],events=[],end_wall_ns=phase*2000+1500)
        base=phase*2000
        for kind,offset in [('armed',100),('start',200),('quiescent',1000),('finish',1100)]:
            for i in range(2):
                e=dict(kind=kind,application=i,wall_ns=base+offset+i*10,monotonic_ns=base+offset+i*10)
                if kind in ('start','finish'):e.update(before_wall_ns=e['wall_ns']-1,before_monotonic_ns=e['monotonic_ns']-1)
                row['events'].append(e)
        for i,(r,o) in enumerate(zip(reports,owners)):
            m=mode if i==0 or mode=='duplex' else 'peer';r['config'].update(mode=m,window=4,interval_us=100000 if m=='rate' else 0)
            if m=='rate':
                # Use window mode in synthetic wire fixtures; absolute-rate rows
                # are covered independently and by actual production report replay.
                raise ValueError('use window/duplex fixture')
            r['channel_identity'].update(controller=o['owner']['index'],generation=o['owner']['generation'],lifetime=o['object']['lifetime'])
            path=f'/evidence/application/passthrough-control/benchmark-{phase}-{i}.json'
            stdout=f'NativeChannelDup: original_closed=1 duplicate_live=1\nSocketBenchmarkArmed: mode={m.capitalize()} count=20 bytes=61 window=4\nSocketBenchmarkQuiescent: mode={m.capitalize()} correctness=true\nSocketBenchmarkLoadObserved: report={path} qualified=false\n'
            for e in row['events']:
                if e['application']==i and e['kind'] in ('armed','quiescent'):e['text']=stdout.splitlines()[1 if e['kind']=='armed' else 2]
            app=dict(mode=m,args=gate.arguments('/bin/slktest',o,m,path),report_path=path,credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0')),exit=0,stdout=stdout,stderr='',report=r,dup_observed_wall_ns=base+50,start_wall_ns=base+10,end_wall_ns=base+1400)
            p=share/Path(path).relative_to('/evidence');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r));p.with_suffix('.stdout').write_text(stdout);p.with_suffix('.stderr').write_text('')
            app['report_file']=dict(path=path,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size);row['applications'].append(app)
        rows.append(row)
        for i,app in enumerate(row['applications']):
            for original in app['report']['outgoing']:
                raw=bytes.fromhex(original['frame_hex'])
                # phase-specific raw evidence offsets, without claiming new nonce provenance.
                for sender,payload in [(i,raw),(1-i,raw[:28]+b'\1'+raw[29:])]:
                    body=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                    for owner,direction in [(owners[sender]['owner'],'out'),(owners[1-sender]['owner'],'in')]:
                        packets.append(dict(record=record,bus=owner['bus'],device=owner['device'],handle=0,direction=direction,boundary=0,data=body.hex(),wall_ns=base+500));record+=1
    phases=[];commands=[]
    for n,row in enumerate(rows):
        phases.append(dict(typed_objects=row['owners'],connect_command=len(commands),disconnect_command=len(commands)+1));commands.extend([dict(end_wall_ns=n*2000-1),dict(start_wall_ns=n*2000+1600)])
    return dict(socket_benchmark=rows,connection_control=dict(phases=phases),commands=commands),dict(acb_packets=packets,native_events=[])


class NativeBenchmarkEvidence(unittest.TestCase):
    def test_synthetic_wire_and_supervisor_pair_are_independently_checked(self):
        for mode,count in [('window',40),('duplex',80)]:
            with tempfile.TemporaryDirectory() as directory:
                run,capture=fixture(Path(directory),mode)
                proof=gate.corroborate(run,capture,directory)
                self.assertEqual(proof['round_trips'],count)
                self.assertIs(proof['performance_qualified'],False)
                record=dict(status='PASSTHROUGH_SUPPORT_PASS',socket_benchmark_requested=mode,socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,qemu_exit=0)
                self.assertEqual(run_exit_code(record),0)
                record['socket_benchmark_corroboration']['round_trips']-=1
                self.assertEqual(run_exit_code(record),1)

    def test_missing_receipt_payload_capture_identity_and_raw_material_fail_closed(self):
        for kind in ['early-start','missingfinish','duplicate','eventtext','credentials','exit','args','identity','rowpayload','capturemissing','captureduplicate','extra','missingreport','hash','rawstdout','mode','stalephase']:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);run,capture=fixture(root);r=run['socket_benchmark'][0];a=r['applications'][0]
                if kind=='early-start':r['events'][2]['before_wall_ns']=0
                if kind=='missingfinish':r['events'].pop()
                if kind=='duplicate':r['events'][1]['application']=0
                if kind=='eventtext':r['events'][0]['text']='wrong'
                if kind=='credentials':a['credentials']['uids']=[0]*4
                if kind=='exit':a['exit']=1
                if kind=='args':a['args'][0]='/bin/slctl'
                if kind=='identity':a['report']['channel_identity']['lifetime']+=1
                if kind=='rowpayload':a['report']['outgoing'][0]['frame_hex']='00'*61
                if kind=='capturemissing':capture['acb_packets'].pop(0)
                if kind=='captureduplicate':capture['acb_packets'].append(copy.deepcopy(capture['acb_packets'][0]))
                if kind=='extra':
                    p=copy.deepcopy(capture['acb_packets'][0]);p['record']=9999;p['data']=p['data'][:-2]+'ff';capture['acb_packets'].append(p)
                path=root/'application/passthrough-control/benchmark-0-0.json'
                if kind=='missingreport':path.unlink()
                if kind=='hash':a['report_file']['sha256']='0'*64
                if kind=='rawstdout':path.with_suffix('.stdout').write_text('truncated')
                if kind=='mode':r['config']['mode']='duplex'
                if kind=='stalephase':r['phase']=1
                with self.subTest(kind=kind),self.assertRaises((CaptureError,OSError,ValueError)):gate.corroborate(run,capture,root)

    def test_request_without_corroboration_and_performance_upgrades_are_rejected(self):
        for mode in ['window','rate','duplex']:
            self.assertEqual(run_exit_code(dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,socket_benchmark_requested=mode)),1)
