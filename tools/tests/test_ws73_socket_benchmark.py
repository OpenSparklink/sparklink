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


def fixture(share,mode='window',window=4,count=20,channel=None,size=61,tcid_offset=0,local_tcids=None):
    rows=[];packets=[];record=1
    for phase in range(2):
        reports=reports_fixture(mode,count=count,size=size)
        owners=[dict(owner=dict(index=i,generation=7+i,path=f'/org/sparklink/slk{i}_g{7+i}',bus=1,device=2+i),object=dict(generation=7+i,lifetime=11+i,handle=0,path=f'/link{i}')) for i in range(2)]
        if phase:owners=owners[::-1];reports=reports[::-1] if mode=='duplex' else reports
        # Deliberately map identities to actual fixture ownership for role swap.
        row=dict(phase=phase,owners=owners,config=gate.configuration(mode,window,count=count,size=size),application_tool=dict(path='/bin/slktest',sha256='a'*64),start_wall_ns=phase*2000,status=gate.PENDING,applications=[],events=[],end_wall_ns=phase*2000+1500)
        if channel is not None:row[gate.CHANNEL_FIELD]=copy.deepcopy(channel)
        base=phase*2000
        for kind,offset in [('armed',100),('start',200),('quiescent',1000),('finish',1100)]:
            for i in range(2):
                e=dict(kind=kind,application=i,wall_ns=base+offset+i*10,monotonic_ns=base+offset+i*10)
                if kind in ('start','finish'):e.update(before_wall_ns=e['wall_ns']-1,before_monotonic_ns=e['monotonic_ns']-1)
                row['events'].append(e)
        for i,(r,o) in enumerate(zip(reports,owners)):
            m=mode if i==0 or mode=='duplex' else 'peer';r['config'].update(mode=m,window=window,interval_us=100000 if m=='rate' else 0)
            if m=='rate':
                # Use window mode in synthetic wire fixtures; absolute-rate rows
                # are covered independently and by actual production report replay.
                raise ValueError('use window/duplex fixture')
            r['channel_identity'].update(controller=o['owner']['index'],generation=o['owner']['generation'],lifetime=o['object']['lifetime'])
            if channel is not None:
                r['channel_request']=gate.application_request(row,i)
                r['channel_identity'].update(local_tcid=0x81+i+tcid_offset,remote_tcid=0x82-i+tcid_offset,mtu=max(249,size),mps=max(249,size)+5)
                if local_tcids is not None:r['channel_identity'].update(local_tcid=local_tcids[i],remote_tcid=local_tcids[1-i])
            path=f'/evidence/application/passthrough-control/benchmark-{phase}-{i}.json'
            stdout=f'NativeChannelDup: original_closed=1 duplicate_live=1\nSocketBenchmarkArmed: mode={m.capitalize()} count={count} bytes={size} window={window}\nSocketBenchmarkQuiescent: mode={m.capitalize()} correctness=true\nSocketBenchmarkLoadObserved: report={path} qualified=false\n'
            for e in row['events']:
                if e['application']==i and e['kind'] in ('armed','quiescent'):e['text']=stdout.splitlines()[1 if e['kind']=='armed' else 2]
            app=dict(mode=m,args=gate.arguments('/bin/slktest',o,m,path,window,count=count,size=size),report_path=path,credentials=dict(uids=[1000]*4,capabilities=dict(CapEff='0',CapPrm='0',CapAmb='0')),exit=0,stdout=stdout,stderr='',report=r,dup_observed_wall_ns=base+50,start_wall_ns=base+10,end_wall_ns=base+1400)
            if channel is not None:
                active=i==channel['active_endpoint'];stamp=base+(60 if active else 30)
                row['events'].append(dict(kind='staged',application=i,wall_ns=stamp,monotonic_ns=stamp,text=gate.staged_text(row,i)))
                app['start_wall_ns']=base+(40 if active else 10);app['dup_observed_wall_ns']=base+(50 if active else 20)
                app['stdout']=app['stdout'].replace('\nSocketBenchmarkArmed:', '\n'+gate.staged_text(row,i)+'\nSocketBenchmarkArmed:')
                app['args']=gate.arguments('/bin/slktest',o,m,path,window,count=count,size=size,channel=r['channel_request']);stdout=app['stdout']
            p=share/Path(path).relative_to('/evidence');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r));p.with_suffix('.stdout').write_text(stdout);p.with_suffix('.stderr').write_text('')
            app['report_file']=dict(path=path,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size);row['applications'].append(app)
        row['events'].sort(key=lambda v:v['monotonic_ns'])
        rows.append(row)
        if channel is not None:
            from ws73_dynamic_channels import cmtc,request
            active=channel['active_endpoint'];passive=1-active;req=gate.application_request(row,active)
            a=row['applications'][active]['report']['channel_identity'];b=row['applications'][passive]['report']['channel_identity']
            raw_request=cmtc(request(7,a['local_tcid'],[req['source_port'],req['destination_port']],req['aid'],req['mtu'],req['mps']))
            raw_response=cmtc(bytes([17,7,4,0,a['local_tcid'],b['local_tcid'],0,0]))
            for index,direction,raw,stamp in [(active,'out',raw_request,70),(passive,'in',raw_request,75),(passive,'out',raw_response,80),(active,'in',raw_response,85)]:
                owner=owners[index]['owner'];packets.append(dict(record=record,bus=owner['bus'],device=owner['device'],handle=0,direction=direction,boundary=0,data=raw.hex(),wall_ns=base+stamp));record+=1
        for i,app in enumerate(row['applications']):
            for original in app['report']['outgoing']:
                raw=bytes.fromhex(original['frame_hex'])
                # phase-specific raw evidence offsets, without claiming new nonce provenance.
                for sender,payload in [(i,raw),(1-i,raw[:28]+b'\1'+raw[29:])]:
                    tcid=row['applications'][sender]['report']['channel_identity']['remote_tcid']
                    body=bytes([tcid,0])+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                    for owner,direction in [(owners[sender]['owner'],'out'),(owners[1-sender]['owner'],'in')]:
                        parts=[body[j:j+253]for j in range(0,len(body),253)]
                        stamp=base+(300+20*original['index']+(10 if payload!=raw else 0)if size>253 else 500)
                        for j,part in enumerate(parts):
                            pb=0 if len(parts)==1 else 1 if j==0 else 3 if j==len(parts)-1 else 2
                            packets.append(dict(record=record,bus=owner['bus'],device=owner['device'],handle=0,direction=direction,boundary=pb,data=part.hex(),wall_ns=stamp+j));record+=1
    phases=[];commands=[]
    for n,row in enumerate(rows):
        phases.append(dict(typed_objects=row['owners'],connect_command=len(commands),disconnect_command=len(commands)+1));commands.extend([dict(end_wall_ns=n*2000-1),dict(start_wall_ns=n*2000+1600)])
    return dict(socket_benchmark=rows,connection_control=dict(phases=phases),commands=commands),dict(acb_packets=packets,native_events=[])


def parallel_fixture(share,active=0,*,cross_namespace=False,close_short=False):
    """Two explicit fixture pairs merged into one four-app observation.

    This tests production metadata/capture checks, not a successful kernel,
    socket, USB or firmware dependency.
    """
    channel=gate.parallel_channel(active,close_short=close_short);runs=[];captures=[]
    for g,target in enumerate(channel['channels']):
        directory=share/target['name'];directory.mkdir(parents=True)
        c=target['config'];run,capture=fixture(directory,window=c['window'],count=c['count'],size=c['bytes'],channel=target['route'],tcid_offset=2*g,local_tcids=((0x81,0x83)if g==0 else(0x83,0x81))if cross_namespace else None)
        runs.append(run);captures.append(capture)
    run=runs[0]
    for phase,row in enumerate(run['socket_benchmark']):
        other=runs[1]['socket_benchmark'][phase]
        row[gate.CHANNEL_FIELD]=copy.deepcopy(channel)
        row['applications']+=other['applications']
        row['events']+=[dict(e,application=e['application']+2)for e in other['events']]
        row['events'].sort(key=lambda e:(e['wall_ns'],e['application']))
        for index,app in enumerate(row['applications']):
            app['pid']=100+4*phase+index
            old=app['report_path'];new=f'/evidence/application/passthrough-control/benchmark-{phase}-{index}.json'
            app['report_path']=new;app['report_file']['path']=new
            app['args']=[new if v==old else v for v in app['args']];app['stdout']=app['stdout'].replace(old,new)
            path=share/Path(new).relative_to('/evidence');path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(app['report']));path.with_suffix('.stdout').write_text(app['stdout']);path.with_suffix('.stderr').write_text('')
            app['report_file'].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
    packets=[p for c in captures for p in c['acb_packets']]
    packets.sort(key=lambda p:p['wall_ns'])
    for record,p in enumerate(packets,1):p['record']=record
    if close_short:
        from ws73_dynamic_channels import cmtc
        for phase,row in enumerate(run['socket_benchmark']):
            oldbase=phase*2000;base=phase*20000;delta=base-oldbase
            for packet in packets:
                if oldbase<=packet['wall_ns']<oldbase+2000:packet['wall_ns']+=delta
            row['start_wall_ns']+=delta;row['end_wall_ns']=base+9000
            for app in row['applications']:
                app['start_wall_ns']+=delta;app['dup_observed_wall_ns']+=delta
            for event in row['events']:
                for key in ['wall_ns','monotonic_ns','before_wall_ns','before_monotonic_ns']:
                    if key in event:event[key]+=delta
                if event['application']>=2 and event['kind']in('quiescent','finish'):
                    for key in ['wall_ns','monotonic_ns','before_wall_ns','before_monotonic_ns']:
                        if key in event:event[key]+=7000
            row['events'].sort(key=lambda e:(e['wall_ns'],e['application']))
            for i,app in enumerate(row['applications']):app['end_wall_ns']=base+(1400+i*10 if i<2 else 8500+i*10)
            row['closed_short']=[dict(application=i,pid=row['applications'][i]['pid'],exit=0,reaped_wall_ns=row['applications'][i]['end_wall_ns'])for i in(0,1)]
            for g in range(2):
                a,b=row['applications'][2*g:2*g+2];identity=a['report']['channel_identity'];local,remote=identity['local_tcid'],identity['remote_tcid'];ident=11+g
                request=cmtc(bytes([18,ident,2,0,local,remote]));response=cmtc(bytes([19,ident,3,0,local,remote,0]))
                for endpoint,direction,raw,offset in [(0,'out',request,0),(1,'in',request,1),(1,'out',response,9),(0,'in',response,9)]:
                    owner=row['owners'][endpoint]['owner'];packets.append(dict(record=0,bus=owner['bus'],device=owner['device'],handle=0,direction=direction,boundary=0,data=raw.hex(),wall_ns=base+(1210 if g==0 else 8200)+offset))
            run['commands'][2*phase]['end_wall_ns']=base-1;run['commands'][2*phase+1]['start_wall_ns']=base+9500
        packets.sort(key=lambda p:p['wall_ns'])
        for record,packet in enumerate(packets,1):packet['record']=record
    return run,dict(acb_packets=packets,native_events=[])


class NativeBenchmarkEvidence(unittest.TestCase):
    def test_synthetic_wire_and_supervisor_pair_are_independently_checked(self):
        for mode,count in [('window',40),('duplex',80)]:
            with tempfile.TemporaryDirectory() as directory:
                run,capture=fixture(Path(directory),mode)
                proof=gate.corroborate(run,capture,directory)
                self.assertEqual(proof['round_trips'],count)
                self.assertIs(proof['performance_qualified'],False)
                record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',socket_benchmark_requested=mode,socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,qemu_exit=0)
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

    def test_single_outstanding_window_uses_same_codec_and_original_argv(self):
        for window in [1,4]:
            with tempfile.TemporaryDirectory() as directory:
                run,capture=fixture(Path(directory),window=window)
                proof=gate.corroborate(run,capture,directory)
                self.assertEqual(proof.get('window',4),window)
                record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',socket_benchmark_requested='window',socket_benchmark_window_requested=window,socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,qemu_exit=0)
                self.assertEqual(run_exit_code(record),0)
                record['socket_benchmark_window_requested']=4 if window==1 else 1
                self.assertEqual(run_exit_code(record),1)
                run['socket_benchmark'][0]['applications'][0]['args'][-3]='999'
                with self.assertRaises(CaptureError):gate.corroborate(run,capture,directory)
        for invalid in [True,0,21,256,'1',1.0]:
            with self.subTest(window=invalid),self.assertRaises(CaptureError):gate.configuration('window',invalid)

    def test_variable_workload_uses_actual_two_end_reports_and_requested_verdict(self):
        for mode in ['window','duplex']:
            with tempfile.TemporaryDirectory() as directory:
                run,capture=fixture(Path(directory),mode,window=3,count=7)
                proof=gate.corroborate(run,capture,directory)
                record=dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',socket_benchmark_requested=mode,socket_benchmark_window_requested=3,socket_benchmark_config_requested=gate.configuration(mode,3,count=7),socket_benchmark_acceptance=True,socket_benchmark_corroboration=proof,performance_qualified=False,qemu_exit=0)
                self.assertEqual(proof['config'],record['socket_benchmark_config_requested'])
                self.assertEqual(run_exit_code(record),0)
                proof['config']=proof['config'].copy()
                original=record['socket_benchmark_config_requested'].copy()
                for change in [dict(window=True),dict(count=7.0),dict(bytes=True),dict(interval_us=False)]:
                    proof['config']=dict(original,**change)
                    with self.subTest(proof=change):self.assertEqual(run_exit_code(record),1)
                proof['config']=original.copy()
                record['socket_benchmark_config_requested']['count']=8
                self.assertEqual(run_exit_code(record),1)
                record['socket_benchmark_config_requested']['count']=7
                record.pop('socket_benchmark_config_requested')
                self.assertEqual(run_exit_code(record),1)
                run['socket_benchmark'][1]['config']['count']=8
                with self.assertRaises((CaptureError,ValueError)):gate.corroborate(run,capture,directory)

    def test_typed_budgets_and_same_existing_slktest_argv(self):
        from argparse import Namespace
        cfg=gate.configuration('rate',64,count=1000,size=2042,interval_us=10000)
        self.assertEqual(cfg,dict(mode='rate',window=64,count=1000,bytes=2042,interval_us=10000))
        self.assertEqual(gate.record_configuration(dict(socket_benchmark_requested='rate',socket_benchmark_window_requested=64,socket_benchmark_config_requested=cfg)),cfg)
        e=dict(owner=dict(path='/adapter'),object=dict(path='/connection'))
        args=gate.arguments('/bin/slktest',e,'rate','/evidence/report',64,count=1000,size=2042,interval_us=10000)
        self.assertEqual(args[-2:],['--interval-us','10000']);self.assertIn('2042',args)
        args=gate.arguments('/bin/slktest',e,'peer','/evidence/report',64,count=1000,size=2042,interval_us=10000)
        self.assertEqual(args[-1],'--load');self.assertNotIn('--interval-us',args)
        for change in [dict(count=True),dict(count=0),dict(count=10001),dict(size=28),dict(size=2043),dict(window=True),dict(window=257),dict(window=1001),dict(interval_us=9),dict(interval_us=1000000)]:
            values=dict(window=64,count=1000,size=61,interval_us=10000);values.update(change)
            with self.subTest(change=change),self.assertRaises(CaptureError):gate.configuration('rate',**values)
        with self.assertRaises(CaptureError):gate.configuration('window',interval_us=1)
        with self.assertRaises(CaptureError):gate.requested_configuration(Namespace(channel_benchmark=None,channel_benchmark_count=128))
        self.assertIsNone(gate.requested_configuration(Namespace()))

    def test_request_without_corroboration_and_performance_upgrades_are_rejected(self):
        for mode in ['window','rate','duplex']:
            self.assertEqual(run_exit_code(dict(supervisor_exit=0,status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,socket_benchmark_requested=mode)),1)
