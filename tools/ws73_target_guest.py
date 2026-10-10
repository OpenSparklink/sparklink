#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Guest readiness and explicit synthetic environment support, never RF."""
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import time

from ws73_capture import command_reply, check_capture_stats, corroborate, corroborate_synthetic, discovery, read_capture, CaptureError
from ws73_north_star import daemon_identity, healthy_native_runtime, ordinary_identity, registration

EVIDENCE = Path('/evidence')
TOOLS = Path(__file__).resolve().parent


def application(*command, user='ws73', **kwargs):
    return subprocess.run(['/bin/su',user,'-s','/bin/sh','-c',shlex.join(command)],text=True,**kwargs)


def ready(slot):
    port=f'1-{slot+1}'
    deadline=time.monotonic()+90
    last=None
    while time.monotonic()<deadline:
        root=Path('/sys/bus/usb/devices')/port
        interfaces=list(root.glob(port+':*')) if root.exists() else []
        progress={'port':port,'interfaces':[str(p) for p in interfaces]}
        for p in interfaces:
            try:
                state=(p/'native_runtime').read_text().strip()
                progress['native_runtime']=state
                progress['boot_stage']=(p/'boot_stage').read_text().strip()
                progress['boot_error']=int((p/'boot_error').read_text().strip())
                diagnostics=p/'failure_diagnostics'
                if diagnostics.exists():progress['failure_diagnostics']=diagnostics.read_text().strip()
                recovery=p/'warm_recovery'
                if recovery.exists():progress['warm_recovery']=recovery.read_text().strip()
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
                if data['bus']!=1:raise ValueError('capture bus and actual guest WS73 bus differ')
                (EVIDENCE/f'ready-{slot}.json').write_text(json.dumps(data,indent=2)+'\n')
                return
            except FileNotFoundError:pass
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


if __name__=='__main__':
    action=sys.argv[1]
    if action=='ready':ready(int(sys.argv[2]))
    elif action=='support':support()
    elif action=='verify-support':verify_support()
    elif action=='instructions':instructions()
    elif action=='support-input':support_input()
    elif action=='bindings-writer':bindings(writer=True)
    else:raise SystemExit('unknown guest action')
