# SPDX-License-Identifier: GPL-2.0-only
"""Native ordinary-application load supervision, using existing slktest/USB gates.

No Host, echo server or controller transition is implemented here. Fixed small
first-baseline workload; application clocks never subtracted across endpoints.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from ws73_capture import CaptureError, reassemble_acb
from ws73_channel_socket import credentials, test_program, validate_application_binary
from ws73_benchmark import load_application_reports, read_report

COUNT, SIZE, WINDOW = 20, 61, 4
PENDING = 'SOCKET_LOAD_APPLICATION_EVIDENCE_PENDING'


def configuration(mode, window=WINDOW):
    if mode not in ('rate','window','duplex') or type(window) is not int or window not in (1,4):
        raise CaptureError('explicit supported Native benchmark mode required')
    return dict(mode=mode,count=COUNT,bytes=SIZE,window=window,
                interval_us=100000 if mode=='rate' else 0)


def arguments(binary, entry, mode, report, window=WINDOW):
    c=configuration(mode if mode!='peer' else 'window',window)
    args=[str(binary),'--adapter',entry['owner']['path'],'channel',mode,entry['object']['path'],
          '--count',str(COUNT),'--bytes',str(SIZE),'--window',str(window),'--report',str(report)]
    if mode=='peer':args+=['--load']
    if mode=='rate':args+=['--interval-us',str(c['interval_us'])]
    return args


def execute(run, phase):
    mode=run.args.channel_benchmark
    window=getattr(run.args,'channel_benchmark_window',WINDOW)
    config=configuration(mode,window)
    row=dict(phase=len(run.data['connection_control']['phases'])-1,owners=phase['typed_objects'],
             config=config,application_tool=test_program(run),start_wall_ns=time.time_ns(),
             status='RUNNING',applications=[],events=[],performance_qualified=False,
             clock='guest wall_ns for observed IO/capture;guest monotonic_ns for supervisory budgets;no cross-application timestamp subtraction')
    run.data.setdefault('socket_benchmark',[]).append(row);run.save()
    processes=[];buffers={};output={};duplicates=set();selector=selectors.DefaultSelector()
    def event(kind,index,**values):
        row['events'].append(dict(kind=kind,application=index,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),**values))
    def wait_marker(kind,seconds):
        deadline=time.monotonic()+seconds;seen=set()
        while len(seen)!=2:
            if time.monotonic()>=deadline:raise CaptureError('original benchmark supervisor '+kind+' deadline')
            for key,_ in selector.select(min(.1,max(0,deadline-time.monotonic()))):
                index=key.data;data=os.read(key.fileobj.fileno(),8192)
                if not data:raise CaptureError('benchmark exited before both '+kind+' markers')
                output[index]+=data;buffers[index]+=data
                if len(output[index])>65536:raise CaptureError('bounded benchmark stdout exceeded')
                while b'\n' in buffers[index]:
                    raw,buffers[index]=buffers[index].split(b'\n',1)
                    text=raw.decode('utf-8',errors='strict')
                    if kind=='armed' and text=='NativeChannelDup: original_closed=1 duplicate_live=1' and index not in duplicates:
                        duplicates.add(index);row['applications'][index]['dup_observed_wall_ns']=time.time_ns();continue
                    if kind=='armed' and index not in duplicates:raise CaptureError('actual existing duplicate-fd setup receipt required')
                    expected_mode=row['applications'][index]['mode'].capitalize()
                    if kind=='armed':expected=f'SocketBenchmarkArmed: mode={expected_mode} count={COUNT} bytes={SIZE} window={window}'
                    else:expected=f'SocketBenchmarkQuiescent: mode={expected_mode} correctness=true'
                    if text!=expected or index in seen:raise CaptureError('unexpected/duplicate benchmark phase output:'+text)
                    event(kind,index,text=text);seen.add(index)
    def release(kind):
        for i,(proc,_) in enumerate(processes):
            before_wall=time.time_ns();before_mono=time.monotonic_ns()
            proc.stdin.write((kind+'\n').encode());proc.stdin.flush()
            event(kind,i,before_wall_ns=before_wall,before_monotonic_ns=before_mono)
    try:
        with ExitStack() as files:
            for i,entry in enumerate(row['owners']):
                appmode=mode if i==0 or mode=='duplex' else 'peer'
                report=run.output/f'benchmark-{row["phase"]}-{i}.json'
                err=run.output/f'benchmark-{row["phase"]}-{i}.stderr'
                app=dict(mode=appmode,args=arguments(row['application_tool']['path'],entry,appmode,report,window),report_path=str(report),stderr_path=str(err),start_wall_ns=time.time_ns())
                row['applications'].append(app)
                proc=subprocess.Popen(app['args'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=files.enter_context(err.open('xb')),bufsize=0)
                processes.append((proc,app));app['pid']=proc.pid;app['credentials']=credentials(proc.pid)
                selector.register(proc.stdout,selectors.EVENT_READ,i);buffers[i]=b'';output[i]=b''
            wait_marker('armed',45)
            # No disk writes between start and both quiescent; bounded IO receipts
            # stay in memory. These are sparse supervision events, not per-packet logs.
            release('start')
            wait_marker('quiescent',620)
            release('finish')
            deadline=time.monotonic()+15
            for i,(proc,app) in enumerate(processes):
                proc.stdin.close();proc.wait(timeout=max(.001,deadline-time.monotonic()))
                tail=proc.stdout.read(65537-len(output[i]));output[i]+=tail
                if len(output[i])>65536:raise CaptureError('benchmark output byte budget')
                app.update(exit=proc.returncode,end_wall_ns=time.time_ns(),stdout=output[i].decode(),stderr=Path(app['stderr_path']).read_text())
                if proc.returncode:raise CaptureError('actual slktest failed:'+app['stderr'])
                report,record=read_report(app['report_path']);app['report']=report;app['report_file']=record
            row['end_wall_ns']=time.time_ns()
            check_supervision(row)
            row['application_check']=load_application_reports(*(a['report'] for a in row['applications']))
            if test_program(run)!=row['application_tool']:raise CaptureError('slktest artifact changed')
            row['status']=PENDING
    except BaseException as error:
        row.update(status='FAIL',error=str(error),error_type=type(error).__name__);raise
    finally:
        for i,(proc,app) in enumerate(processes):
            if proc.poll() is None:
                if not proc.stdin.closed:proc.stdin.close()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            app.setdefault('exit',proc.returncode)
            if 'stdout' not in app:app['stdout']=output.get(i,b'').decode(errors='replace')
            if Path(app['stderr_path']).is_file():app['stderr']=Path(app['stderr_path']).read_text()
            (run.output/f'benchmark-{row["phase"]}-{i}.stdout').write_text(app['stdout'])
        selector.close();row['end_wall_ns']=time.time_ns();run.save()


def check_supervision(row):
    window=row['config']['window']
    configuration(row['config']['mode'],window)
    if row['config']!=configuration(row['config']['mode'],window) or len(row['applications'])!=2:
        raise CaptureError('exact first Native benchmark workload required')
    validate_application_binary(row['application_tool'])
    events=row['events']
    if len(events)!=8:raise CaptureError('complete paired arm/start/quiescent/finish receipts required')
    for clock in ['wall_ns','monotonic_ns']:
        stamps=[e[clock] for e in events]
        if any(type(v) is not int for v in stamps) or stamps!=sorted(stamps):raise CaptureError('same guest supervisor clock order')
    for offset,kind in enumerate(['armed','start','quiescent','finish']):
        chunk=events[offset*2:offset*2+2]
        if {e['application'] for e in chunk}!={0,1} or any(e['kind']!=kind for e in chunk):raise CaptureError('paired barrier order before either release')
    for i,app in enumerate(row['applications']):
        expected=row['config']['mode'] if i==0 or row['config']['mode']=='duplex' else 'peer'
        if app['mode']!=expected or app['args']!=arguments(row['application_tool']['path'],row['owners'][i],expected,app['report_path'],window):raise CaptureError('actual slktest argv/mode mismatch')
        cred=app['credentials']
        if app['exit'] or cred['uids']!=[1000]*4 or any(int(v,16) for v in cred['capabilities'].values()):raise CaptureError('ordinary actual benchmark process required')
        lines=app['stdout'].splitlines()
        expected_lines=['NativeChannelDup: original_closed=1 duplicate_live=1',f'SocketBenchmarkArmed: mode={expected.capitalize()} count={COUNT} bytes={SIZE} window={window}',
                        f'SocketBenchmarkQuiescent: mode={expected.capitalize()} correctness=true',
                        f'SocketBenchmarkLoadObserved: report={app["report_path"]} qualified=false']
        if lines!=expected_lines:raise CaptureError('exact complete successful stdout receipts')
        armed=next(e for e in events if e['application']==i and e['kind']=='armed')
        if not app['start_wall_ns']<=app.get('dup_observed_wall_ns',0)<=armed['wall_ns']:raise CaptureError('original duplicate receipt before arm')
        for kind,line in [('armed',expected_lines[1]),('quiescent',expected_lines[2])]:
            if next(e for e in events if e['application']==i and e['kind']==kind).get('text')!=line:raise CaptureError('IO marker differs from actual stdout')
        for kind,limit,previous in [('start',30,'armed'),('finish',30,'quiescent')]:
            e=next(e for e in events if e['application']==i and e['kind']==kind)
            own=next(e for e in events if e['application']==i and e['kind']==previous)
            if not events[(['armed','start','quiescent','finish'].index(kind)-1)*2+1]['wall_ns']<=e['before_wall_ns']<=e['wall_ns']:raise CaptureError('both endpoints observed before control write')
            if not max(own['monotonic_ns'],events[(['armed','start','quiescent','finish'].index(kind)-1)*2+1]['monotonic_ns'])<=e['before_monotonic_ns']<=e['monotonic_ns']<own['monotonic_ns']+limit*1_000_000_000:raise CaptureError('bounded original supervisory input')
        identity=app['report']['channel_identity'];owner=row['owners'][i]['owner'];obj=row['owners'][i]['object']
        if any(identity[k]!=v for k,v in [('controller',owner['index']),('generation',owner['generation']),('lifetime',obj['lifetime']),('handle',obj['handle'])]):raise CaptureError('report/current registration connection identity')
        cfg=app['report']['config'];expected_cfg=dict(row['config'],mode=expected,interval_us=row['config']['interval_us'] if expected=='rate' else 0)
        if cfg!=expected_cfg:raise CaptureError('actual report workload differs from request')
        if not row['start_wall_ns']<=app['start_wall_ns']<=events[0]['wall_ns']<app['end_wall_ns']<=row['end_wall_ns']:raise CaptureError('original process observation window')


def check_report_files(row, share):
    share=Path(share).resolve(strict=True)
    for i,app in enumerate(row['applications']):
        expected=f"/evidence/application/passthrough-control/benchmark-{row['phase']}-{i}.json"
        if app['report_path']!=expected or app['report_file']['path']!=expected:raise CaptureError('original benchmark report location')
        path=(share/Path(expected).relative_to('/evidence')).resolve(strict=True)
        path.relative_to(share)
        report,record=read_report(path)
        if any(record[k]!=app['report_file'][k] for k in ['sha256','bytes']) or json.dumps(report,sort_keys=True)!=json.dumps(app['report'],sort_keys=True):raise CaptureError('report bytes/hash differ from observed process output')
        for suffix,key in [('stdout','stdout'),('stderr','stderr')]:
            text=path.with_suffix('.'+suffix).read_text()
            if text!=app[key]:raise CaptureError('original benchmark process log differs')


def corroborate(run,capture,share):
    rows=run.get('socket_benchmark')
    if type(rows) is not list or len(rows)!=2:raise CaptureError('both actual connection-role benchmark phases required')
    sdus=reassemble_acb(capture);proofs=[];used=set()
    for n,row in enumerate(rows):
        if row['phase']!=n or row['status']!=PENDING:raise CaptureError('both successful original benchmark phases')
        connection=run['connection_control']['phases'][n]
        if row['owners']!=connection['typed_objects'] or not run['commands'][connection['connect_command']]['end_wall_ns']<=row['start_wall_ns']<=row['end_wall_ns']<=run['commands'][connection['disconnect_command']]['start_wall_ns']:raise CaptureError('benchmark belongs to current physical connection interval')
        check_supervision(row)
        check_report_files(row,share)
        check=load_application_reports(*(app['report'] for app in row['applications']))
        legs=[]
        start=next(e['before_wall_ns'] for e in row['events'] if e['kind']=='start')
        end=max(e['wall_ns'] for e in row['events'] if e['kind']=='quiescent')
        def matched(index,direction,frame):
            entry=row['owners'][index];owner=entry['owner'];obj=entry['object']
            found=[p for p in sdus if (p['bus'],p['device'],p['handle'],p['direction'])==(owner['bus'],owner['device'],obj['handle'],direction) and p['data']==frame.hex() and start<=p['wall_ns']<=end]
            if len(found)!=1:raise CaptureError('one exact opposite USB TX/RX for each benchmark business frame')
            packet=found[0];key=(packet['record'],packet.get('hcc_offset',0),direction,owner['bus'],owner['device'])
            if key in used:raise CaptureError('benchmark evidence reused')
            used.add(key);return packet
        expected=set()
        for index,app in enumerate(row['applications']):
            for original in app['report']['outgoing']:
                request=bytes.fromhex(original['frame_hex']);reply=request[:28]+b'\1'+request[29:]
                for sender,body in [(index,request),(1-index,reply)]:
                    frame=b'\x1f\0'+(len(body)+1).to_bytes(2,'little')+b'\xf1'+body
                    legs.append(dict(tx=matched(sender,'out',frame),rx=matched(1-sender,'in',frame)))
                    expected.add(frame.hex())
        for entry in row['owners']:
            o=entry['owner'];obj=entry['object']
            actual=[p for p in sdus if (p['bus'],p['device'],p['handle'])==(o['bus'],o['device'],obj['handle']) and start<=p['wall_ns']<=end and p['data'].startswith('1f00')]
            if len(actual)!=len(expected) or any(p['data'] not in expected for p in actual):raise CaptureError('all CUTC31 business packets must be attributed once')
        proofs.append(dict(phase=n,owners=row['owners'],application=check,legs=legs,events=row['events']))
    if len({row['config']['window'] for row in rows})!=1:raise CaptureError('same requested window in both physical connection roles required')
    result=dict(status='REAL_WS73_LOAD_USB_AND_APPLICATION_OBSERVED_NOT_PERFORMANCE_QUALIFIED',
                mode=rows[0]['config']['mode'],round_trips=sum(len(a['report']['outgoing']) for row in rows for a in row['applications']),
                proofs=proofs,performance_qualified=False,
                remaining=['repeatstablebaseline/traceoverhead/resources','crossclockmapping/per-layer latency','fullperformance/stress/fairness/recovery qualification'])
    if rows[0]['config']['window']!=WINDOW:result['window']=rows[0]['config']['window']
    return result
