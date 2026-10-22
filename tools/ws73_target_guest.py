#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Guest readiness and explicit synthetic environment support, never RF."""
import json
import errno
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import time

from ws73_capture import command_reply, check_capture_stats, corroborate, corroborate_synthetic, corroborate_passthrough, corroborate_recovery, discovery, read_capture, CaptureError
from ws73_north_star import daemon_identity, healthy_native_runtime, ordinary_identity, registration, file_record

EVIDENCE = Path('/evidence')
TOOLS = Path(__file__).resolve().parent


def application(*command, user='ws73', **kwargs):
    return subprocess.run(['/bin/su',user,'-s','/bin/sh','-c',shlex.join(command)],text=True,**kwargs)


def ready(slot):
    port=f'1-{slot+1}'
    deadline=time.monotonic()+90
    last=None
    pending_observations=[]
    pending_seen=set()
    while time.monotonic()<deadline:
        root=Path('/sys/bus/usb/devices')/port
        interfaces=list(root.glob(port+':*')) if root.exists() else []
        progress={'port':port,'interfaces':[str(p) for p in interfaces]}
        for p in interfaces:
            try:
                state=(p/'native_runtime').read_text().strip()
                progress['native_runtime']=state
                early=re.fullmatch(r'id=-1 generation=\d+ streaming=0 broken=\d+ unsupported=\d+ last_event=[0-9a-fA-F]{4} controller_error=[0-9a-fA-F]+ reserved=1 pending_id=(\d+) pending_generation=(\d+) core_pending_ret=0 core_phase=(\d+) core_error=(-?\d+)',state)
                if early and state not in pending_seen:
                    # Read actual sysfs as the ordinary test user, not a root
                    # projection. Sampling is evidence only, not a Ready gate.
                    command=("import sys,json;from pathlib import Path;sys.path.insert(0,"+repr(str(Path(__file__).resolve().parent))+");from ws73_north_star import ordinary_identity;print(json.dumps({'credentials':ordinary_identity(),'runtime':Path("+repr(str(p/'native_runtime'))+").read_text().strip(),'metadata_valid':Path("+repr(str(p/'metadata_valid'))+").read_text().strip()}))")
                    sampled=application('/bin/python3','-c',command,capture_output=True,timeout=10)
                    if sampled.returncode==0:
                        sample=json.loads(sampled.stdout)
                        sample.update(port=port,time_ns=time.time_ns())
                        pending_observations.append(sample);pending_seen.add(state)
                        (EVIDENCE/f'pending-observations-{slot}.json').write_text(json.dumps(pending_observations,indent=2)+'\n')
                progress['boot_stage']=(p/'boot_stage').read_text().strip()
                progress['boot_error']=int((p/'boot_error').read_text().strip())
                diagnostics=p/'failure_diagnostics'
                if diagnostics.exists():progress['failure_diagnostics']=diagnostics.read_text().strip()
                recovery=p/'warm_recovery'
                if recovery.exists():progress['warm_recovery']=recovery.read_text().strip()
                budget=p/'recovery_budget'
                if budget.exists():progress['recovery_budget']=budget.read_text().strip()
                if progress['boot_stage']=='failed':
                    (EVIDENCE/f'ready-progress-{slot}.json').write_text(json.dumps(progress,indent=2)+'\n')
                    raise ValueError(f'{port}: native bootstrap failed: {progress["boot_error"]}')
                try:m=healthy_native_runtime(state)
                except ValueError:continue
                path=f'/org/sparklink/slk{m[1]}_g{m[2]}'
                result=application('/bin/slctl','--adapter',path,'show',capture_output=True,timeout=10)
                progress.update({'stdout':result.stdout,'stderr':result.stderr,'exit':result.returncode})
                initialization=re.search(r'^  Init error:  (.+)$',result.stdout,re.M)
                if initialization:
                    (EVIDENCE/f'ready-progress-{slot}.json').write_text(json.dumps(progress,indent=2)+'\n')
                    raise ValueError(f'{port}: adapter initialization failed: {initialization[1]}')
                if result.returncode or '  State:       Ready\n' not in result.stdout:continue
                address=re.search(r'^  Address:     ([0-9A-F:]+)$',result.stdout,re.M)
                data={'port':port,'path':path,'index':int(m[1]),'generation':int(m[2]),
                      'bus':int((root/'busnum').read_text()),'device':int((root/'devnum').read_text()),
                      'address':address[1],'view':result.stdout,'native_runtime':state,
                      'controller_information':(p/'controller_information').read_text().strip()}
                models=[t.split('=',1)[1] for t in Path('/proc/cmdline').read_text().split() if t.startswith('ws73.expected_models=')]
                if models:
                    if len(models)!=1 or slot>=len(models[0].split(',')):
                        raise ValueError('one expected board model per physical guest slot required')
                    from ws73_lab_resources import check_hcc
                    data['hcc_chip']=check_hcc((p/'chip_information').read_text().strip(),models[0].split(',')[slot])
                if data['bus']!=1:raise ValueError('capture bus and actual guest WS73 bus differ')
                (EVIDENCE/f'ready-{slot}.json').write_text(json.dumps(data,indent=2)+'\n')
                return
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ENODATA, errno.EAGAIN):raise
        if progress!=last:
            (EVIDENCE/f'ready-progress-{slot}.json').write_text(json.dumps(progress,indent=2)+'\n');last=progress
        time.sleep(0.2)
    raise ValueError(f'{port}: native Ready deadline exceeded')


def identities():
    a,b=[json.loads((EVIDENCE/f'ready-{n}.json').read_text()) for n in range(2)]
    if a['index']==b['index'] or a['generation']==b['generation'] or a['address']==b['address']:raise ValueError('independent identities required')
    return a,b


def instructions():
    a,b=identities()
    for r in [a,b]:
        actual=registration(r['port'])
        if actual['path']!=r['path']:raise ValueError('physical mapping changed')
    pid=int(subprocess.check_output(['/bin/pidof','slkd'],text=True))
    print('WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0',flush=True)
    print('Ordinary uid1000 shell; capture started BEFORE USB attachment. Exit the shell after testing to seal capture.',flush=True)
    print(shlex.join(['/bin/python3',str(TOOLS/'ws73_north_star.py'),'run','--ports',a['port'],b['port'],
                      '--slctl','/bin/slctl','--slkd-pid',str(pid),'--output','/evidence/application/control',
                      *[x for label,p in [('kernel_image','/boot/bzImage'),('firmware','/lib/firmware/sparklink/ws73/ws73.bin'),
                                        ('wifi_calibration','/lib/firmware/sparklink/ws73/wifi_cali.bin'),('btc_calibration','/lib/firmware/sparklink/ws73/btc_cali.bin'),
                                        ('bsle_custom','/lib/firmware/sparklink/ws73/bsle_custom.bin'),('pm_config','/lib/firmware/sparklink/ws73/pm_config.bin')]
                        for x in ['--artifact',label+'='+p]]]),flush=True)


def bindings(writer=False):
    """Actual C/Python library calls, only in the explicit synthetic guest."""
    if 'ws73.support=1' not in Path('/proc/cmdline').read_text().split():
        raise ValueError('binding probe is synthetic support only')
    control=EVIDENCE/'application/support-control/run.json'
    if control.exists():
        run=json.loads(control.read_text());selected=[run['replacement'],run['initial'][1]]
    else:selected=list(identities())
    mode='writer' if writer else 'observe'
    results=[]
    for r in selected:
        for name,program in [('c',['/bin/native-bindings-probe']),('python',['/bin/python3',str(TOOLS/'ws73_bindings_probe.py')])]:
            for who in (['root'] if writer else ['root','ws73']):
                p=application(*program,mode,str(r['index']),str(r['generation']),user=who,capture_output=True,timeout=10)
                results.append({'language':name,'user':who,'index':r['index'],'generation':r['generation'],
                                'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
                if p.returncode:raise ValueError('actual binding probe failed: '+str(results[-1]))
                if writer:
                    lines=re.findall(r'^WS73_NATIVE_BINDING_RESULT: (.+)$',p.stdout,re.M)
                    if len(lines)!=1:raise ValueError('binding writer result missing')
                    results[-1]['result']=json.loads(lines[0])
                    if name=='c':
                        scans=re.findall(r'^WS73_NATIVE_BINDING_SCAN_READY: (.+)$',p.stdout,re.M)
                        releases=re.findall(r'^WS73_NATIVE_BINDING_RELEASE: (.+)$',p.stdout,re.M)
                        if len(scans)!=2 or len(releases)!=1:raise ValueError('binding scan/revoke precondition missing')
                        results[-1]['scan_setup']=[json.loads(x) for x in scans]
                        results[-1]['release_scan']=json.loads(releases[0])

    (EVIDENCE/('bindings-'+mode+'.json')).write_text(json.dumps({'scope':'synthetic C/Python kernel binding support',
        'physical_acceptance':False,'mode':mode,'results':results},indent=2)+'\n')


def support():
    a,b=identities();pid=int(subprocess.check_output(['/bin/pidof','slkd'],text=True))
    before=daemon_identity(pid)
    result=application('/bin/python3','-c',
                       'from pathlib import Path;import os,json;print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"groups":os.getgroups(),"status":Path("/proc/self/status").read_text()}))',
                       capture_output=True,check=True)
    credentials=json.loads(result.stdout)
    if credentials['uid']!=1000 or credentials['gid']!=1002 or 1000 not in credentials['groups']:raise ValueError('ordinary control identity')
    fields=dict(line.split(':',1) for line in credentials['status'].splitlines() if ':' in line)
    if any(int(fields[k],16) for k in ['CapEff','CapPrm','CapAmb']):raise ValueError('ordinary app retained capabilities')
    collector=dict(line.split(':',1) for line in (EVIDENCE/'capture-process-status.txt').read_text().splitlines() if ':' in line)
    if list(map(int,collector['Uid'].split()))!=[1003]*4 or any(int(collector[k],16) for k in ['CapEff','CapPrm','CapAmb']):raise ValueError('capture process did not drop privileges')
    if application('/bin/sh','-c','test -w /bin/slkd || test -w /lib/firmware/sparklink/ws73/ws73.bin').returncode==0:raise ValueError('ordinary app can overwrite privileged code/firmware')
    if application('/bin/sh','-c','test -r /dev/usbmon1 || test -w /dev/usbmon1').returncode==0:raise ValueError('ordinary app has raw USB capture permission')
    for who,mode in [('observer','observer'),('ws73','control')]:
        with (EVIDENCE/f'policy-{mode}.log').open('w') as log:
            application('/bin/bus-policy-probe',a['path'],mode,user=who,stdout=log,stderr=subprocess.STDOUT,check=True)
    rejected=application('/bin/python3',str(TOOLS/'ws73_north_star.py'),'run','--ports',a['port'],b['port'],
                         '--slctl','/bin/slctl','--slkd-pid',str(pid),'--output','/evidence/application/rejected',capture_output=True)
    rejection=json.loads((EVIDENCE/'application/rejected/run.json').read_text())
    if rejected.returncode!=1 or rejection['status']!='FAIL' or 'synthetic USB model excluded' not in rejection.get('error',''):raise ValueError('physical acceptance admitted fixture')
    watchers=[];stale_watchers=[]
    for name in ['slkmon','slkdump']:
        log=(EVIDENCE/(name+'.log')).open('w')
        p=subprocess.Popen(['/bin/'+name,'--adapter',str(b['index']),'--generation',str(b['generation']),
                            '--count','32','--write',str(EVIDENCE/(name+'.snoop'))],stdout=log,stderr=subprocess.STDOUT)
        watchers.append((p,log))
    try:
        hotplug='ws73.hotplug=1' in Path('/proc/cmdline').read_text().split()
        if hotplug:
            for name,program in [('c',['/bin/native-bindings-probe']),('python',['/bin/python3',str(TOOLS/'ws73_bindings_probe.py')])]:
                for mode in ['stale-event','stale-trace']:
                    log=(EVIDENCE/f'bindings-{name}-{mode}.log').open('w')
                    p=subprocess.Popen([*program,mode,str(a['index']),str(a['generation'])],stdout=log,stderr=subprocess.STDOUT)
                    stale_watchers.append((p,log))
        deadline=time.monotonic()+10
        while any(not (EVIDENCE/(name+'.snoop')).exists() or (EVIDENCE/(name+'.snoop')).stat().st_size<16 for name in ['slkmon','slkdump']):
            if time.monotonic()>deadline or any(p.poll() is not None for p,_ in watchers):raise ValueError('snoop startup')
            time.sleep(0.05)
        if hotplug:
            command=['/bin/python3',str(TOOLS/'ws73_target_control.py'),'--slctl','/bin/slctl','--slkd-pid',str(pid),
                     '--output','/evidence/application/support-control']
            process=subprocess.Popen(['/bin/busybox','setsid','-c','/bin/su','ws73','-s','/bin/sh','-c',shlex.join(command)],
                                     text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            with (EVIDENCE/'support-control.log').open('w') as log:
                for line in process.stdout:
                    log.write(line);log.flush();print(line,end='',flush=True)
            if process.wait():raise ValueError('synthetic full control orchestrator failed')
        else:
            script=EVIDENCE/'support-radio.sh'
            script.write_text('#!/bin/sh\nctl() { /bin/slctl "$@"; }\nfail() { echo "TARGET_RADIO_FAILURE: $*"; exit 1; }\n. /bin/test-radio\n'+
                              'radio_rounds 20 '+shlex.quote(a['path'])+' '+shlex.quote(b['path'])+' target-support\n')
            with (EVIDENCE/'support-radio.log').open('w') as log:
                application('/bin/sh',str(script),stdout=log,stderr=subprocess.STDOUT,timeout=60,check=True)
        for p,_ in watchers:
            if p.wait(timeout=10):raise ValueError('native snoop tool failure')
        for p,_ in stale_watchers:
            if p.wait(timeout=10):raise ValueError('C/Python retired binding failure')
    finally:
        for p,log in watchers+stale_watchers:
            if p.poll() is None:p.terminate();p.wait(timeout=5)
            log.close()
    # Controller events are spontaneous RX, not setup command completions.
    # Require actual discovery traffic before comparing independent readers.
    bindings()
    if before!=daemon_identity(pid):raise ValueError('daemon replaced during support radio')
    (EVIDENCE/'support.json').write_text(json.dumps({'scope':'synthetic environment support','physical_acceptance':False,
        'credentials':credentials,'daemon':before,'identities':[a,b],'fixture_rejected':True},indent=2)+'\n')


def verify_support():
    a,b=identities();stats=check_capture_stats((EVIDENCE/'capture-stats.txt').read_text())
    hotplug='ws73.hotplug=1' in Path('/proc/cmdline').read_text().split()
    control=json.loads((EVIDENCE/'application/support-control/run.json').read_text()) if hotplug else None
    ids=[*control['initial'],control['replacement']] if hotplug else [a,b]
    capture=read_capture(EVIDENCE/'ws73.pcap',[(r['bus'],r['device']) for r in ids])
    if stats!=capture['packet_count']:raise ValueError('sealed pcap/statistics count mismatch')
    if hotplug:
        for language in ['c','python']:
            for mode in ['event','trace']:
                text=(EVIDENCE/f'bindings-{language}-stale-{mode}.log').read_text()
                expected=f'WS73_NATIVE_{language.upper()}_STALE: PASS mode={mode} index={control["initial"][0]["index"]} old={control["initial"][0]["generation"]} new={control["replacement"]["generation"]} poll=ERR|HUP'
                if text.count(expected)!=1:raise ValueError('retired C/Python binding proof missing')
    for mode,expected in [('observe',8),('writer',4)]:
        proof=json.loads((EVIDENCE/('bindings-'+mode+'.json')).read_text())
        if proof['physical_acceptance'] is not False or proof['mode']!=mode or len(proof['results'])!=expected:
            raise ValueError('actual C/Python binding proof missing')
        for entry in proof['results']:
            uid=1000 if entry['user']=='ws73' else 0
            if entry['exit']!=0 or f'WS73_NATIVE_{entry["language"].upper()}_BINDINGS: PASS mode={mode} uid={uid} ' not in entry['stdout']:
                raise ValueError('binding process/credential result failed')
            if mode=='writer':
                result=entry['result'];r=next(x for x in ids if (x['index'],x['generation'])==(entry['index'],entry['generation']))
                if (result['generation'],result['state'],result['status'],result['error'],result['operation'])!=(r['generation'],3,0,0,4 if entry['language']=='c' else 2):
                    raise ValueError('binding result disagrees with selected generation')
                if not any((x['bus'],x['device'],x['opcode'],x['status'])==(r['bus'],r['device'],result['opcode'],0)
                           and result['started_wall_ns']<=x['wall_ns']<=result['finished_wall_ns'] for x in capture['complete']):
                    raise ValueError('binding writer lacks captured exact-generation Complete')
                if entry['language']=='c':
                    for scan in entry['scan_setup']:
                        if scan['generation']!=r['generation']:raise ValueError('binding scan owner changed')
                        for opcode,params in [(0x1001,bytes.fromhex('0000010040062003')),(0x1002,b'\x01\x00')]:
                            command_reply(capture,r,opcode,scan['started_wall_ns'],scan['finished_wall_ns'],params,'')
                    release=entry['release_scan']
                    if release['generation']!=r['generation'] or not release['ready']:raise ValueError('binding release lost owner/Ready')
                    start,end=release['started_wall_ns'],release['finished_wall_ns']
                    command_reply(capture,r,0x1002,start,end,b'\x00\x00','')
                    if any((c['bus'],c['device'],c['opcode'])==(r['bus'],r['device'],0x0c05) and start<=c['wall_ns']<=end for c in capture['commands']):
                        raise ValueError('binding release resent already-confirmed advertising OFF')

    empty_bulk='ws73.empty_bulk=1' in Path('/proc/cmdline').read_text().split()
    if empty_bulk and not all(any((e['bus'],e['device'])==(r['bus'],r['device']) for e in capture['empty_bulk_completions']) for r in ids):
        raise ValueError('both selected controllers must have captured successful empty bulk completions')
    if hotplug:
        proofs=corroborate_synthetic(control,capture)
        try:corroborate(control,capture)
        except CaptureError:pass
        else:raise ValueError('physical corroborator admitted synthetic control')
        renamed=dict(control,scope='physical',status='CONTROL_PASS_EVIDENCE_PENDING')
        # Verify the independent descriptor boundary after testing the QMP
        # method boundary. Neither renaming scope nor removing that label
        # can promote synthetic bytes to a physical unplug receipt.
        try:corroborate(renamed,capture)
        except CaptureError as error:
            if 'QMP disconnect excluded' not in str(error):raise
        else:raise ValueError('QMP method promoted to physical unplug')
        renamed.pop('hotplug_method',None)
        try:corroborate(renamed,capture)
        except CaptureError as error:
            if 'synthetic descriptors excluded' not in str(error):raise
        else:raise ValueError('renaming synthetic control labels admitted physical corroboration')
        (EVIDENCE/'support-control-proofs.json').write_text(json.dumps({'scope':'synthetic USB control corroboration; never physical acceptance',
            'physical_acceptance':False,'physical_scope_rejected':True,'renamed_record_rejected':True,'proofs':proofs},indent=2)+'\n')
        matches=[(str(r['match']['generation']),r['match']['address'],str(r['match']['rssi']),r['marker'],r['match']['data']) for r in control['rounds']]
    else:
        radio=(EVIDENCE/'support-radio.log').read_text()
        matches=re.findall(r'^NativeDiscoveryMatch: generation=(\d+) seq=\d+ address=([0-9A-F:]+) RSSI=(-?\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+) ',radio,re.M)
    count=22 if hotplug else 20
    if len(matches)!=count or len({m[3] for m in matches})!=count:raise ValueError('independent ordinary-user matches required')
    for g,addr,rssi,marker,data in matches:
        rx=next(r for r in ids if r['generation']==int(g))
        if not any((r['bus'],r['device'],r['address'],r['rssi'],r['data'])==(rx['bus'],rx['device'],addr,int(rssi),data) for r in capture['reports']):raise ValueError('actual USB capture disagrees with ordinary app')
    mon=(EVIDENCE/'slkmon.snoop').read_bytes();dump=(EVIDENCE/'slkdump.snoop').read_bytes()
    if mon!=dump or mon[:16]!=b'SLKSNP01'+struct.pack('<II',1,320) or len(mon)!=16+32*376:raise ValueError('independent snoop byte equality')
    record=struct.Struct('<QQQQIIiHBBHHI320s');reports=[]
    for n in range(32):
        seq,g,t,lost,profile,original,status,index,direction,fmt,length,flags,reserved,payload=record.unpack_from(mon,16+n*376)
        if (seq!=n+1 or g!=b['generation'] or index!=b['index'] or not t or lost or profile!=1 or
            status or fmt!=1 or flags or reserved or not 5<=length<=320 or original!=length or any(payload[length:]) or
            direction not in [1,2] or payload[0]!=(0xa2 if direction==1 else 0xa1) or int.from_bytes(payload[3:5],'little')!=length-5):raise ValueError('snoop metadata/framing')
        if direction==1:
            parsed=discovery(payload[:length])
            if parsed is not None:reports.append(parsed)
    if not reports:raise ValueError('raw DLI report missing')
    for r in reports:
        if not any((r['address'],r['rssi'],r['data'])==(addr,int(rssi),data) for g,addr,rssi,marker,data in matches if int(g)==b['generation']):raise ValueError('snoop/app report mismatch')
    result={'scope':'synthetic environment support; never firmware/RF acceptance','physical_acceptance':False,
            'packet_count':stats,'raw_reports':len(capture['reports']),'matches':count,'snoop_records':32,'snoop_identical':True,
            'synthetic_empty_bulk':empty_bulk,'empty_bulk_completions':len(capture['empty_bulk_completions']),
            'synthetic_hotplug':hotplug}
    (EVIDENCE/'support-capture.json').write_text(json.dumps(result,indent=2)+'\n')
    print('WS73_TARGET_SUPPORT: PASS',flush=True)


def support_input():
    ordinary_identity()
    if not sys.stdin.isatty():raise ValueError('ordinary console input is not a tty')
    print('WS73_TARGET_INPUT_READY',flush=True)
    if input()!='target-ordinary-input':raise ValueError('ordinary serial input mismatch')
    print('WS73_TARGET_INPUT_PASS: uid=1000 caps=0 tty=1',flush=True)


def verify_parallel():
    business='ws73.parallel_business=1' in Path('/proc/cmdline').read_text().split()
    if business:
        from ws73_parallel_data import corroborate
    else:
        from ws73_parallel import corroborate
    name='parallel-business' if business else 'parallel-control'
    run=json.loads((EVIDENCE/f'application/{name}/run.json').read_text())
    if business and run.get('disconnect_isolation',False)!=('ws73.parallel_disconnect=1' in Path('/proc/cmdline').read_text().split()):
        raise ValueError('guest disconnect scope disagrees with explicit boot request')
    if business and run.get('burst_mode',False)!=('ws73.parallel_burst=1' in Path('/proc/cmdline').read_text().split()):
        raise ValueError('guest burst scope disagrees with explicit boot request')
    owners=[o for w in run['workers'] for o in w['run']['initial']]
    capture=read_capture(EVIDENCE/'ws73.pcap',[(o['bus'],o['device']) for o in owners])
    count=check_capture_stats((EVIDENCE/'capture-stats.txt').read_text())
    if capture['packet_count']!=count:raise ValueError('parallel sealed capture count mismatch')
    proof=corroborate(run,capture)
    (EVIDENCE/f'{name}-proofs.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('WS73_TARGET_PARALLEL_BUSINESS: PASS' if business else 'WS73_TARGET_PARALLEL_RF: PASS',flush=True)


def verify_passthrough():
    run=json.loads((EVIDENCE/'application/passthrough-control/run.json').read_text())
    identities=[*run['initial'],run['replacement']]
    capture=read_capture(EVIDENCE/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
    packets=check_capture_stats((EVIDENCE/'capture-stats.txt').read_text())
    if packets!=capture['packet_count']:raise ValueError('passthrough capture packet count mismatch')
    from ws73_runtime_address import boot_addresses
    addresses=boot_addresses(Path('/proc/cmdline').read_text().split())
    address_record=json.loads((EVIDENCE/'runtime-address/run.json').read_text()) if addresses else None
    proofs=corroborate_passthrough(run,capture,address_record,addresses)
    if ('ws73.link_resync=1' in Path('/proc/cmdline').read_text().split()) != ('link_resync' in run):
        raise ValueError('explicit subscriber resync request/evidence mismatch')
    if 'link_resync' in run:
        from ws73_link_resync import corroborate as resync_corroborate
        resync_corroborate(run,capture)
    if ('ws73.acb_probe=1' in Path('/proc/cmdline').read_text().split()) != ('acb_transport_probe' in run):
        raise ValueError('explicit ACB transport probe/evidence mismatch')
    if 'acb_transport_probe' in run:
        from ws73_acb_transport_probe import corroborate as acb_corroborate
        acb_corroborate(run,capture,(EVIDENCE/'kernel.log').read_text())
    requested_connection = 'ws73.connection_verify=1' in Path('/proc/cmdline').read_text().split()
    requested_discovery = 'ws73.application_discovery=1' in Path('/proc/cmdline').read_text().split()
    if requested_discovery != ('application_discovery' in run):raise ValueError('explicit application discovery request/evidence mismatch')
    if requested_discovery:
        from ws73_application_discovery import corroborate as discovery_corroborate,verify_supervisor_artifacts,boot_case,case as discovery_case
        variant=boot_case(Path('/proc/cmdline').read_text().split())
        if any(discovery_case(row['request'])!=variant for row in run['application_discovery']):
            raise ValueError('original boot discovery termination differs from actual request')
        proofs.append({'discovery_supervision':verify_supervisor_artifacts(run,EVIDENCE,file_record(TOOLS/'ws73_application_discovery.py'))})
        proofs.append({'application_discovery':discovery_corroborate(run,capture)})
    requested_clients = 'ws73.application_clients=1' in Path('/proc/cmdline').read_text().split()
    if requested_clients != ('application_clients' in run):raise ValueError('explicit application client request/evidence mismatch')
    if requested_clients:
        from ws73_application_client import corroborate as client_corroborate
        from ws73_application_role import verify_supervisor_artifacts
        proofs.append({'application_role_supervision':verify_supervisor_artifacts(run,EVIDENCE)})
        proofs.append({'application_clients':client_corroborate(run,capture)})
    if requested_connection != ('connection_control' in run):
        raise ValueError('explicit connection request and evidence must agree')
    native_requested='ws73.native_return=1' in Path('/proc/cmdline').read_text().split()
    if native_requested != ('native_return' in run):raise ValueError('Native return request/evidence mismatch')
    if native_requested:
        from ws73_native_return import verify_root, corroborate as native_corroborate
        verify_root(run,EVIDENCE)
        proofs.append({'native_return':native_corroborate(run,capture)})
    controller_roles=[v.split('=',1)[1] for v in Path('/proc/cmdline').read_text().split()
                      if v.startswith('ws73.native_controller_return=')]
    if bool(controller_roles) != ('native_controller_return' in run):raise ValueError('controller return request/evidence mismatch')
    if controller_roles:
        from ws73_native_controller_return import corroborate as controller_corroborate
        if native_requested or controller_roles != [run['native_controller_return']['role']]:raise ValueError('one exclusive controller return role required')
        proofs.append({'native_controller_return':controller_corroborate(run,capture,EVIDENCE,Path('/expected-native-return-sha256').read_text().strip())})
    initialization_requested='ws73.ssap_initialization=1' in Path('/proc/cmdline').read_text().split()
    if initialization_requested != ('ssap_initialization' in run):raise ValueError('initialization request/evidence mismatch')
    if initialization_requested:
        from ws73_ssap_initialization import corroborate_guest, verify_fd_supervisor, profile
        stages=[v.split('=',1)[1] for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.ssap_initialization_stage=')]
        if len(stages)>1 or run['ssap_initialization'].get('stage','cmtc')!=profile(stages[0] if stages else 'cmtc')['stage']:
            raise ValueError('actual VM command line and guest initialization stage differ')
        verify_fd_supervisor(run,EVIDENCE)
        proofs.append({'ssap_initialization':corroborate_guest(run,capture)})
    requester_requested='ws73.ssap_requester_lifecycle=1' in Path('/proc/cmdline').read_text().split()
    if any(bool(row.get('ssap_requester_lifecycle_required',False))!=requester_requested for row in run.get('channel_socket',[])) or(requester_requested and not run.get('channel_socket')):raise ValueError('requester lifecycle request/evidence mismatch')
    subscription_requested='ws73.ssap_subscription=1' in Path('/proc/cmdline').read_text().split()
    if any(bool(row.get('ssap_subscription_required',False))!=subscription_requested for row in run.get('channel_socket',[]))or subscription_requested and not run.get('channel_socket'):raise ValueError('subscription request/evidence mismatch')
    renewal_requested='ws73.ssap_subscription_renewal=1'in Path('/proc/cmdline').read_text().split()
    from ws73_ssap_subscription import renewal_required
    if renewal_requested and not subscription_requested or any(renewal_required(row)!=renewal_requested for row in run.get('channel_socket',[])):raise ValueError('renewal boot/request/evidence mismatch')
    pressure_requested='ws73.ssap_subscription_pressure=1'in Path('/proc/cmdline').read_text().split()
    from ws73_ssap_subscription import pressure_required
    if pressure_requested and not subscription_requested or any(pressure_required(row)!=pressure_requested for row in run.get('channel_socket',[])):raise ValueError('pressure boot/request/evidence mismatch')
    loss_requested='ws73.ssap_subscription_owner_loss=1'in Path('/proc/cmdline').read_text().split()
    from ws73_ssap_subscription import owner_loss_required
    if loss_requested and not subscription_requested or any(owner_loss_required(row)!=loss_requested for row in run.get('channel_socket',[])):raise ValueError('owner-loss boot/request/evidence mismatch')
    inflight_requested='ws73.ssap_subscription_inflight_release=1'in Path('/proc/cmdline').read_text().split()
    from ws73_ssap_subscription import inflight_required
    if inflight_requested and not subscription_requested or any(inflight_required(row)!=inflight_requested for row in run.get('channel_socket',[])):raise ValueError('in-flight release boot/request/evidence mismatch')
    from ws73_ssap_subscription import boot_inflight_case,inflight_case
    requested_case=boot_inflight_case(Path('/proc/cmdline').read_text().split(),inflight_requested)
    if any(inflight_case(row)!=requested_case for row in run.get('channel_socket',[])):raise ValueError('in-flight original case boot/evidence mismatch')
    from ws73_ssap_subscription import shared_boot,shared_required,boot_shared_case,shared_case
    shared_requested=shared_boot(Path('/proc/cmdline').read_text().split())
    if shared_requested and not subscription_requested or any(shared_required(row)!=shared_requested for row in run.get('channel_socket',[])):raise ValueError('shared owner boot/request/evidence mismatch')
    requested_shared_case=boot_shared_case(Path('/proc/cmdline').read_text().split(),shared_requested)
    if any(shared_case(row)!=requested_shared_case for row in run.get('channel_socket',[])):raise ValueError('shared lifetime boot/evidence mismatch')
    from ws73_role_snapshot import TOKEN,requested as snapshot_requested
    snapshot_boot=Path('/proc/cmdline').read_text().split().count(TOKEN)
    if snapshot_boot>1 or snapshot_boot and not subscription_requested or any(snapshot_requested(row)!=bool(snapshot_boot)for row in run.get('channel_socket',[])):raise ValueError('snapshot boot/request/evidence mismatch')
    delivery_requested='ws73.ssap_update_delivery=1' in Path('/proc/cmdline').read_text().split()
    if any(bool(row.get('ssap_update_delivery_required',False))!=delivery_requested for row in run.get('channel_socket',[])) or (delivery_requested and not run.get('channel_socket')):raise ValueError('update delivery request/evidence mismatch')
    lifecycle_requested='ws73.ssap_owner_lifecycle=1' in Path('/proc/cmdline').read_text().split()
    if any(bool(row.get('ssap_owner_lifecycle_required',False))!=lifecycle_requested for row in run.get('channel_socket',[])) or (lifecycle_requested and not run.get('channel_socket')):raise ValueError('owner lifecycle request/evidence mismatch')
    owned_requested='ws73.ssap_owned=1' in Path('/proc/cmdline').read_text().split()
    if any(bool(row.get('ssap_owned_required',False))!=owned_requested for row in run.get('channel_socket',[])) or (owned_requested and not run.get('channel_socket')):
        raise ValueError('explicit owned SSAP request and evidence must agree')
    if requested_connection:
        from ws73_connection_control import corroborate as connection_corroborate
        connections=connection_corroborate(run,capture)
        proofs.append({'connection_control':connections})
        if run['connection_control'].get('connection_objects'):
            from ws73_connection_objects import corroborate as object_corroborate
            object_corroborate(run,capture,connections)
        from ws73_link_measurement import TOKEN,corroborate as measurement_corroborate
        tokens=Path('/proc/cmdline').read_text().split()
        requested_measurements=tokens.count(TOKEN)
        if requested_measurements>1 or bool(requested_measurements)!=run.get('link_measurements_requested',False):
            raise ValueError('link observation boot/request mismatch')
        measured=measurement_corroborate(run,capture,bool(requested_measurements))
        if measured is not None:proofs.append({'link_measurements':measured})
    benchmark_modes=[w.split('=',1)[1] for w in Path('/proc/cmdline').read_text().split() if w.startswith('ws73.benchmark_mode=')]
    if bool(benchmark_modes)!=('socket_benchmark' in run) or len(benchmark_modes)>1:raise ValueError('benchmark request/evidence mismatch')
    dynamic_boot=[w for w in Path('/proc/cmdline').read_text().split()if w.startswith(('ws73.benchmark_dynamic=','ws73.benchmark_parallel=','ws73.benchmark_active=','ws73.benchmark_close='))]
    if dynamic_boot and not benchmark_modes:raise ValueError('dynamic benchmark boot target without benchmark')
    benchmark_role=[v for v in Path('/proc/cmdline').read_text().split()if v.startswith('ws73.socket_benchmark_apps=')]
    if benchmark_role and(benchmark_role!=['ws73.socket_benchmark_apps=1']or not benchmark_modes):raise ValueError('benchmark apps-only boot scope mismatch')
    from ws73_benchmark_ssap import from_boot as service_boot,selected as selected_service,workload as service_workload
    service=service_boot(Path('/proc/cmdline').read_text().split())
    if service is not None and not benchmark_modes:raise ValueError('concurrent SSAP requires the benchmark root scope')
    if benchmark_modes:
        from ws73_socket_benchmark import corroborate as benchmark_corroborate,apps_role
        if bool(benchmark_role)!=all(apps_role(row)for row in run['socket_benchmark']):raise ValueError('benchmark role/boot/evidence mismatch')
        from ws73_socket_benchmark import configuration
        fields={}
        words=Path('/proc/cmdline').read_text().split()
        for field in ['window','count','bytes','interval_us']:
            values=[w.split('=',1)[1] for w in words if w.startswith('ws73.benchmark_'+field+'=')]
            if len(values)!=1 or not values[0].isascii() or not values[0].isdecimal():raise ValueError('one explicit numeric benchmark '+field+' required')
            fields[field]=int(values[0])
        config=configuration(benchmark_modes[0],fields['window'],count=fields['count'],size=fields['bytes'],interval_us=fields['interval_us'])
        if any(row['config']!=config for row in run['socket_benchmark']):raise ValueError('requested exact workload differs')
        from ws73_socket_benchmark import channel_from_boot,row_channel
        channel=channel_from_boot(words,config)
        if any(row_channel(row)!=channel for row in run['socket_benchmark']):raise ValueError('requested channel target differs from actual benchmark')
        if any(selected_service(row)!=service for row in run['socket_benchmark']):raise ValueError('requested concurrent SSAP differs from actual benchmark')
        if service is not None:service_workload(config,channel)
        proofs.append({'socket_benchmark':benchmark_corroborate(run,capture,EVIDENCE)})
    if 'daemon_removal' in run:
        from ws73_daemon_removal import corroborate_wire
        proofs.append({'daemon_cancel_removal':corroborate_wire(run['daemon_removal'],capture)})
    requested = 'ws73.initializer_lifecycle=1' in Path('/proc/cmdline').read_text().split()
    if requested != ('initialization_lifecycle' in run):
        raise ValueError('explicit initializer lifecycle request and evidence must agree')
    if requested:
        from ws73_initialization_lifecycle import corroborate_wire
        proofs.append({'initializer_lifecycle':corroborate_wire(run,capture)})
    requested_crash = 'ws73.daemon_crash=1' in Path('/proc/cmdline').read_text().split()
    if requested_crash != (EVIDENCE/'daemon-crash/run.json').exists():
        raise ValueError('explicit daemon crash request and evidence must agree')
    if requested_crash:
        from ws73_daemon_crash import corroborate as crash_corroborate
        proofs.append({'daemon_crash':crash_corroborate(json.loads((EVIDENCE/'daemon-crash/run.json').read_text()),run,capture)})
    service_requested='ws73.ssap_service_policy=1' in Path('/proc/cmdline').read_text().split()
    if service_requested!=(EVIDENCE/'service-policy/run.json').exists():raise ValueError('explicit service-role request/evidence mismatch')
    if service_requested:
        from ws73_ssap_service_policy import corroborate as service_corroborate
        proofs.append({'ssap_service_policy':service_corroborate(json.loads((EVIDENCE/'service-policy/run.json').read_text()),run)})
    requested_observer = 'ws73.observer_policy=1' in Path('/proc/cmdline').read_text().split()
    if requested_observer != (EVIDENCE/'observer-policy/run.json').exists():
        raise ValueError('explicit observer policy request and evidence must agree')
    if requested_observer:
        from ws73_observer_policy import corroborate as observer_corroborate
        proofs.append({'observer_policy':observer_corroborate(json.loads((EVIDENCE/'observer-policy/run.json').read_text()),run,capture)})
    (EVIDENCE/'passthrough-control-proofs.json').write_text(json.dumps({
        'scope':'real WS73 RF with QMP guest-detach control support',
        'physical_acceptance':False,'packet_count':packets,'proofs':proofs},indent=2)+'\n')
    print('WS73_TARGET_PASSTHROUGH_SUPPORT: PASS',flush=True)


if __name__=='__main__':
    action=sys.argv[1]
    if action=='ssap-init-fds':
        from ws73_ssap_initialization import observe_fds
        observe_fds(EVIDENCE,int(sys.argv[2]))
        raise SystemExit(0)
    if action=='daemon-crash':
        from ws73_daemon_crash import record_phase
        record_phase(application,[registration('1-1'),registration('1-2')],sys.argv[2],int(sys.argv[3]),int(sys.argv[4]) if len(sys.argv)>4 else None)
        print('WS73_TARGET_DAEMON_CRASH_PHASE: '+sys.argv[2],flush=True)
        raise SystemExit(0)
    if action=='service-policy':
        from ws73_ssap_service_policy import record
        record(application,[registration('1-1'),registration('1-2')],int(sys.argv[2]))
        print('WS73_TARGET_SERVICE_POLICY: local role evidence pending',flush=True)
        raise SystemExit(0)
    if action=='observer-policy':
        from ws73_observer_policy import record_phase
        phase=sys.argv[2]
        record_phase(application,[registration('1-1'),registration('1-2')],phase)
        print('WS73_TARGET_OBSERVER_POLICY_PHASE: '+phase,flush=True)
        raise SystemExit(0)
    if action=='verify-recovery':
        run=json.loads((EVIDENCE/'application/recovery-control/run.json').read_text())
        capture=read_capture(EVIDENCE/'ws73.pcap',[(r['bus'],r['device']) for r in [*run['initial'],run['replacement']]])
        packets=check_capture_stats((EVIDENCE/'capture-stats.txt').read_text())
        if packets!=capture['packet_count']:raise ValueError('recovery capture count mismatch')
        diagnostic_path=EVIDENCE/'diagnostic/run.json'
        diagnostic=json.loads(diagnostic_path.read_text()) if 'ws73.diagnostic=1' in Path('/proc/cmdline').read_text().split() else None
        active=json.loads((EVIDENCE/'active-deadline/run.json').read_text()) if 'ws73.active_deadline=1' in Path('/proc/cmdline').read_text().split() else None
        if 'ws73.setup_release=1' in Path('/proc/cmdline').read_text().split():
            from ws73_management_setup import corroborate as corroborate_setup
            setup_proof=corroborate_setup(json.loads((EVIDENCE/'setup-release/run.json').read_text()),capture)
            (EVIDENCE/'setup-release/capture-proof.json').write_text(json.dumps(setup_proof,indent=2)+'\n')
        partial=json.loads((EVIDENCE/'managed-partial/run.json').read_text()) if 'ws73.managed_partial=1' in Path('/proc/cmdline').read_text().split() else None
        connected=json.loads((EVIDENCE/'connected-file/run.json').read_text()) if any(v.startswith('ws73.connected_case=') for v in Path('/proc/cmdline').read_text().split()) else None
        proofs=corroborate_recovery(run,capture,diagnostic,active,partial,connected)
        (EVIDENCE/'recovery-control-proofs.json').write_text(json.dumps({'scope':run['scope'],'physical_acceptance':False,'packet_count':packets,'proofs':proofs},indent=2)+'\n')
        print('WS73_TARGET_RECOVERY_SUPPORT: PASS',flush=True)
        raise SystemExit(0)
    if action=='ready':ready(int(sys.argv[2]))
    elif action=='support':support()
    elif action=='verify-support':verify_support()
    elif action=='verify-passthrough':verify_passthrough()
    elif action=='verify-parallel':verify_parallel()
    elif action=='instructions':instructions()
    elif action=='support-input':support_input()
    elif action=='bindings-writer':bindings(writer=True)
    else:raise SystemExit('unknown guest action')
