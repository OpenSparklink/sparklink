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

from ws73_capture import check_capture_stats, discovery, read_capture
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
                try:m=healthy_native_runtime(state)
                except ValueError:continue
                path=f'/org/sparklink/slk{m[1]}_g{m[2]}'
                result=application('/bin/slctl','--adapter',path,'show',capture_output=True,timeout=10)
                progress.update({'stdout':result.stdout,'stderr':result.stderr,'exit':result.returncode})
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
    watchers=[]
    for name in ['slkmon','slkdump']:
        log=(EVIDENCE/(name+'.log')).open('w')
        p=subprocess.Popen(['/bin/'+name,'--adapter',str(b['index']),'--generation',str(b['generation']),
                            '--count','32','--write',str(EVIDENCE/(name+'.snoop'))],stdout=log,stderr=subprocess.STDOUT)
        watchers.append((p,log))
    try:
        deadline=time.monotonic()+10
        while any(not (EVIDENCE/(name+'.snoop')).exists() or (EVIDENCE/(name+'.snoop')).stat().st_size<16 for name in ['slkmon','slkdump']):
            if time.monotonic()>deadline or any(p.poll() is not None for p,_ in watchers):raise ValueError('snoop startup')
            time.sleep(0.05)
        script=EVIDENCE/'support-radio.sh'
        script.write_text('#!/bin/sh\nctl() { /bin/slctl "$@"; }\nfail() { echo "TARGET_RADIO_FAILURE: $*"; exit 1; }\n. /bin/test-radio\n'+
                          'radio_rounds 20 '+shlex.quote(a['path'])+' '+shlex.quote(b['path'])+' target-support\n')
        with (EVIDENCE/'support-radio.log').open('w') as log:
            application('/bin/sh',str(script),stdout=log,stderr=subprocess.STDOUT,timeout=60,check=True)
        for p,_ in watchers:
            if p.wait(timeout=10):raise ValueError('native snoop tool failure')
    finally:
        for p,log in watchers:
            if p.poll() is None:p.terminate();p.wait(timeout=5)
            log.close()
    if before!=daemon_identity(pid):raise ValueError('daemon replaced during support radio')
    (EVIDENCE/'support.json').write_text(json.dumps({'scope':'synthetic environment support','physical_acceptance':False,
        'credentials':credentials,'daemon':before,'identities':[a,b],'fixture_rejected':True},indent=2)+'\n')


def verify_support():
    a,b=identities();stats=check_capture_stats((EVIDENCE/'capture-stats.txt').read_text())
    capture=read_capture(EVIDENCE/'ws73.pcap',[(r['bus'],r['device']) for r in [a,b]])
    if stats!=capture['packet_count']:raise ValueError('sealed pcap/statistics count mismatch')
    radio=(EVIDENCE/'support-radio.log').read_text()
    matches=re.findall(r'^NativeDiscoveryMatch: generation=(\d+) seq=\d+ address=([0-9A-F:]+) RSSI=(-?\d+) marker=([0-9a-f]{32}) data=([0-9a-f]+) ',radio,re.M)
    if len(matches)!=20 or len({m[3] for m in matches})!=20:raise ValueError('20 independent ordinary-user matches required')
    for g,addr,rssi,marker,data in matches:
        rx=next(r for r in [a,b] if r['generation']==int(g))
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
            'packet_count':stats,'raw_reports':len(capture['reports']),'matches':20,'snoop_records':32,'snoop_identical':True}
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
    else:raise SystemExit('unknown guest action')
