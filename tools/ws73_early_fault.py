#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VM-only real missing-custom bootstrap failure and three-device business isolation."""
import argparse
import errno
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from types import SimpleNamespace
from ws73_north_star import Run, daemon_identity, ordinary_identity, registration, stable
from ws73_target_guest import application, ready, EVIDENCE, TOOLS

FIRMWARE=Path('/lib/firmware/sparklink/ws73/bsle_custom.bin')
BACKUP=FIRMWARE.with_name('bsle_custom.bin.early-fault-backup')
DIR=EVIDENCE/'early-bootstrap-fault'


def save(d):
    DIR.mkdir(exist_ok=True)
    (DIR/'run.json').write_text(json.dumps(d,indent=2)+'\n')


def business(args):
    ordinary_identity()
    settings=SimpleNamespace(output=args.output,slctl=Path('/bin/slctl'),slkd_pid=args.slkd_pid,
        artifact=[],ports=args.ports,connection_advertising='negotiable-t',channel_socket_verify=True,
        channel_socket_rounds=2,channel_socket_bytes=61,channel_socket_boundaries=False)
    run=Run(settings)
    try:
        run.begin();owners=[run.ready(port) for port in args.ports];run.data['initial']=owners;run.save()
        # Actual beacon and fresh discovery first; then existing qualified
        # connection/socket engine with random application payload/replies.
        run.phase(*owners,2,'fault-isolation')
        from ws73_connection_control import execute
        execute(run,*owners)
        run.data.update(status='EARLY_FAULT_BUSINESS_EVIDENCE_PENDING',daemon_after=daemon_identity(args.slkd_pid),end_wall_ns=time.time_ns());run.save()
    except BaseException as error:
        run.data.update(status='FAIL',error=str(error),error_type=type(error).__name__);run.save();raise


def ordinary_attributes(interface):
    command=('import sys,json;from pathlib import Path;sys.path.insert(0,'+repr(str(TOOLS))+');from ws73_north_star import ordinary_identity;p=Path('+repr(str(interface))+');print(json.dumps({"credentials":ordinary_identity(),"attributes":{n:(p/n).read_text().strip() for n in ["native_runtime","boot_error","boot_stage","metadata_valid","failure_diagnostics"]}}))')
    result=application('/bin/python3','-c',command,capture_output=True,timeout=10)
    if result.returncode:raise ValueError('ordinary actual sysfs read failed: '+result.stderr)
    data=json.loads(result.stdout);data['wall_ns']=time.time_ns();return data


def ordinary_core_snapshot(index,generation):
    # Uses the installed Python -> actual C cdylib -> Rust -> kernel ioctl.
    # Opens an unbound observation fd; never selects/acquires management.
    command=('import sys,json,os;os.environ["LIBSPARKLINK_PATH"]="/usr/lib/libsparklink.so";sys.path[:0]=['+repr(str(TOOLS))+',"/usr/share/sparklink/python"];from ws73_north_star import ordinary_identity;from sparklink import registration_snapshot;d={"credentials":ordinary_identity()};'
             +'\ntry:\n s=registration_snapshot('+str(index)+','+str(generation)+');d["snapshot"]={n:getattr(s,n) for n in ["version","dev_index","generation","state","profile","bus","phase","error","reserved_byte"]};d["snapshot"]["reserved"]=list(s.reserved)'
             +'\nexcept OSError as e:d["errno"]=e.errno;d["error"]=str(e)\nprint(json.dumps(d))')
    r=application('/bin/python3','-c',command,capture_output=True,timeout=10)
    if r.returncode:raise ValueError('ordinary Core binding query failed: '+r.stderr)
    d=json.loads(r.stdout);d['wall_ns']=time.time_ns();d['command']=r.args;return d


def validate_core_snapshot(sample,index,generation,state):
    if 'snapshot' not in sample:raise ValueError('actual Core binding observation missing: '+str(sample.get('error',sample.get('errno'))))
    c=sample['credentials'];s=sample['snapshot']
    if c['uids']!=[1000]*4 or any(int(c[k],16) for k in ['cap_eff','cap_prm','cap_amb']):raise ValueError('Core query must be ordinary')
    if s != dict(version=1,dev_index=index,generation=generation,state=state,profile=1,bus=4,phase=3 if state==2 else 0,error=-2 if state==2 else 0,reserved_byte=0,reserved=[0]*8):raise ValueError('exact canonical Core registration fields required')


def validate_core_absent(sample):
    c=sample['credentials']
    if c['uids']!=[1000]*4 or any(int(c[k],16) for k in ['cap_eff','cap_prm','cap_amb']):raise ValueError('old Core query must be ordinary')
    if sample.get('errno')!=errno.ENODEV or 'snapshot' in sample:raise ValueError('old Core registration must be absent')


def ordinary_bus_registration(index,generation,user):
    path=f'/org/sparklink/slk{index}_g{generation}'
    command=('import sys,json,subprocess,time,os;sys.path.insert(0,'+repr(str(TOOLS))+');from ws73_north_star import ordinary_identity;d={"credentials":ordinary_identity(),"kernel_access":(os.access("/dev/sparklink",os.R_OK) or os.access("/dev/sparklink",os.W_OK)),"commands":[]};'
             +'\nfor args in [["/bin/slctl","registration",'+repr(path)+'],["/bin/slctl","registrations"]]:\n started=time.time_ns();r=subprocess.run(args,text=True,capture_output=True,timeout=10);d["commands"].append({"args":args,"exit":r.returncode,"stdout":r.stdout,"stderr":r.stderr,"start_wall_ns":started,"end_wall_ns":time.time_ns()})\nprint(json.dumps(d))')
    r=application('/bin/python3','-c',command,user=user,capture_output=True,timeout=25)
    if r.returncode:raise ValueError('actual ordinary D-Bus probe failed: '+r.stderr)
    d=json.loads(r.stdout);d['user']=user;return d


def validate_bus_registration(sample,index,generation,state):
    c=sample['credentials'];uid={'ws73':1000,'observer':1001}[sample['user']]
    if c['uids']!=[uid]*4 or any(int(c[k],16) for k in ['cap_eff','cap_prm','cap_amb']):raise ValueError('actual ordinary bus credentials required')
    if uid==1001 and sample['kernel_access']:raise ValueError('default observer must lack direct kernel access')
    path=f'/org/sparklink/slk{index}_g{generation}';rows=sample['commands'];direct,listing=rows
    if direct['args']!=['/bin/slctl','registration',path] or listing['args']!=['/bin/slctl','registrations']:raise ValueError('actual registration CLI arguments required')
    if state is None:
        if direct['exit']==0 or listing['exit'] or path in listing['stdout']:raise ValueError('old daemon identity must be rejected/absent')
    else:
        expected=f'Registration {path}: index={index} generation={generation} state={state} profile=1 bus=4 phase={3 if state=="Fault" else 0} error={-2 if state=="Fault" else 0}\n'
        if direct['exit'] or listing['exit'] or direct['stdout']!=expected or expected not in listing['stdout']:raise ValueError('actual exact Core-backed D-Bus observation required')


def validate_fault(sample):
    c=sample['credentials'];a=sample['attributes']
    if c['uids'] != [1000]*4 or any(int(c[k],16) for k in ['cap_eff','cap_prm','cap_amb']):raise ValueError('ordinary read credentials required')
    match=re.fullmatch(r'id=-1 generation=\d+ streaming=0 broken=\d+ unsupported=\d+ last_event=[0-9a-fA-F]{4} controller_error=[0-9a-fA-F]+ reserved=1 pending_id=(\d+) pending_generation=(\d+) core_pending_ret=0 core_phase=(\d+) core_error=-2',a['native_runtime'])
    if not match or not 0<=int(match[1])<16 or not int(match[2])>0 or a['metadata_valid']!='0' or a['boot_stage']!='failed' or a['boot_error']!='-2':raise ValueError('actual ENOENT, unqueried Core pending fault and no Runtime required')
    return {'id':int(match[1]),'generation':int(match[2]),'phase':int(match[3])}


def registration_counts(stdout):
    pattern=r'^Registration (/org/sparklink/slk(\d+)_g(\d+)): index=(\d+) generation=(\d+) state=(Pending|Fault|Installed|Retiring) profile=(\d+) bus=(\d+) phase=(\d+) error=(-?\d+)$'
    rows=[]
    for line in stdout.splitlines():
        if not line.startswith('Registration '):continue
        m=re.fullmatch(pattern,line)
        if not m or m[2]!=m[4] or m[3]!=m[5] or int(m[3])==0:
            raise ValueError('malformed Core registration row')
        rows.append(dict(path=m[1],index=int(m[4]),generation=int(m[5]),state=m[6]))
    if not rows or len({r['index'] for r in rows})!=len(rows) or any(r['state']=='Retiring' for r in rows):
        raise ValueError('registration inventory empty/duplicate/not settled')
    return dict(Devices=len(rows), **{'Reserved only':sum(r['state'] in ('Pending','Fault') for r in rows),
                                    'Runtimes':sum(r['state']=='Installed' for r in rows)})


def stats(expected):
    # Per-registration samples are not an atomic multi-device snapshot. This
    # controlled gate waits for the exact inventory to stabilize twice.
    deadline=time.monotonic()+10;previous=None
    while time.monotonic()<deadline:
        r=application('/bin/slctl','registrations',capture_output=True,timeout=10)
        if r.returncode:raise ValueError('ordinary registration inventory failed: '+r.stderr)
        fields=registration_counts(r.stdout)
        if fields==expected and previous==r.stdout:
            return dict(fields=fields,stdout=r.stdout,wall_ns=time.time_ns(),
                        source='actual Core-backed D-Bus registrations; stable twice, not atomic aggregate')
        previous=r.stdout;time.sleep(.1)
    raise ValueError('registration inventory did not settle to expected pending/installed counts')


def exchange_record(d,label,ports,pid):
    output=EVIDENCE/'application'/'early-bootstrap-fault'/label
    r=application('/bin/python3',str(Path(__file__).resolve()),'business','--ports',*ports,'--slkd-pid',str(pid),'--output',str(output),capture_output=True,timeout=180)
    d[label]=dict(exit=r.returncode,stdout=r.stdout,stderr=r.stderr,record=str(output/'run.json'),end_wall_ns=time.time_ns());save(d)
    if r.returncode:raise ValueError('ordinary peer business failed: '+r.stderr)


def coordinate(pid):
    if 'ws73.early_bootstrap_fault=1' not in Path('/proc/cmdline').read_text().split():raise ValueError('explicit VM command line required')
    d=dict(status='RUNNING',controlled_missing_firmware=True,natural_recovery_acceptance=False,started_wall_ns=time.time_ns(),daemon_before=daemon_identity(pid));save(d)
    restored=False
    try:
        ready(0);print('WS73_TARGET_READY: slot=0',flush=True)
        ready(1)
        d['healthy_before']=[registration(p) for p in ['1-1','1-2']]
        if BACKUP.exists() or not FIRMWARE.is_file():raise ValueError('exact single guest fixture file required')
        d['firmware_sha256']=hashlib.sha256(FIRMWARE.read_bytes()).hexdigest()
        FIRMWARE.rename(BACKUP);d['removed_wall_ns']=time.time_ns();save(d)
        # Third physical owner is attached only after the fixture is absent.
        print('WS73_TARGET_READY: slot=1',flush=True)
        deadline=time.monotonic()+45;last=None
        while time.monotonic()<deadline:
            paths=list(Path('/sys/bus/usb/devices/1-3').glob('1-3:*'))
            for p in paths:
                try:
                    if (p/'boot_stage').read_text().strip()!='failed':continue
                    sample=ordinary_attributes(p);identity=validate_fault(sample);last=(p,sample,identity);break
                except OSError:continue
            if last:break
            time.sleep(.1)
        if last is None:raise ValueError('target failed-init observation deadline; no simulated success')
        interface,sample,fault=last;d.update(failed=sample,fault_identity=fault,failed_usb=dict(bus=int(Path('/sys/bus/usb/devices/1-3/busnum').read_text()),device=int(Path('/sys/bus/usb/devices/1-3/devnum').read_text())))
        d['core_fault']=ordinary_core_snapshot(fault['id'],fault['generation']);validate_core_snapshot(d['core_fault'],fault['id'],fault['generation'],2)
        # Daemon publication is asynchronous, but the original bound is finite.
        deadline=time.monotonic()+10
        while True:
            bus=[ordinary_bus_registration(fault['id'],fault['generation'],u) for u in ['ws73','observer']]
            try:
                for row in bus:validate_bus_registration(row,fault['id'],fault['generation'],'Fault')
                d['bus_fault']=bus;break
            except ValueError:
                if time.monotonic()>deadline:d['bus_fault']=bus;save(d);raise
                time.sleep(.1)
        cli=application('/bin/slkconfig','--adapter',str(fault['id']),'--generation',str(fault['generation']),'registration',capture_output=True,timeout=10)
        d['core_fault_cli']=dict(exit=cli.returncode,stdout=cli.stdout,stderr=cli.stderr)
        expected=f'Registration: index={fault["id"]} generation={fault["generation"]} state=2 profile=1 bus=4 phase=3 error=-2\n'
        if cli.returncode or cli.stdout!=expected:raise ValueError('ordinary CLI must expose exact real Core fault')
        d['failed_selection']=application('/bin/slctl','--adapter',f'/org/sparklink/slk{fault["id"]}_g{fault["generation"]}','show',capture_output=True,timeout=10).__dict__
        # CompletedProcess contains only serializable command/exit/streams.
        if d['failed_selection']['returncode']==0:raise ValueError('failed pending identity selectable as Ready')
        d['stats_failed']=stats({'Devices':3,'Reserved only':1,'Runtimes':2})
        if d['stats_failed']['fields']!={'Devices':3,'Reserved only':1,'Runtimes':2}:raise ValueError('exact two Runtime plus one pending fault expected')
        save(d);exchange_record(d,'during_fault',['1-1','1-2'],pid)
        d['failed_after_business']=ordinary_attributes(interface)
        if validate_fault(d['failed_after_business'])!=fault:raise ValueError('fault generation changed during peer business')
        BACKUP.rename(FIRMWARE);restored=True;d['restored_wall_ns']=time.time_ns()
        if hashlib.sha256(FIRMWARE.read_bytes()).hexdigest()!=d['firmware_sha256']:raise ValueError('original firmware fixture must be restored exactly')
        save(d);print('WS73_TARGET_EARLY_FAULT_REMOVE_READY',flush=True)
        if input().strip()!='early-fault-remove':raise ValueError('explicit guest-only removal acknowledgement required')
        deadline=time.monotonic()+15
        while Path('/sys/bus/usb/devices/1-3').exists():
            if time.monotonic()>deadline:raise ValueError('target guest removal deadline')
            time.sleep(.05)
        d['stats_after_remove']=stats({'Devices':2,'Reserved only':0,'Runtimes':2})
        if d['stats_after_remove']['fields']!={'Devices':2,'Reserved only':0,'Runtimes':2}:raise ValueError('pending cancellation must converge without clearing peers')
        d['core_cancelled']=ordinary_core_snapshot(fault['id'],fault['generation']);validate_core_absent(d['core_cancelled'])
        d['bus_cancelled']=[ordinary_bus_registration(fault['id'],fault['generation'],u) for u in ['ws73','observer']]
        for row in d['bus_cancelled']:validate_bus_registration(row,fault['id'],fault['generation'],None)
        save(d);print('WS73_TARGET_EARLY_FAULT_READD_READY',flush=True)
        if input().strip()!='early-fault-readd':raise ValueError('explicit guest-only readd acknowledgement required')
        ready(2);new=registration('1-3');d['replacement']=new
        if new['generation']<=fault['generation']:raise ValueError('retry requires a new generation')
        d['core_replacement']=ordinary_core_snapshot(new['index'],new['generation']);validate_core_snapshot(d['core_replacement'],new['index'],new['generation'],3)
        d['core_stale']=ordinary_core_snapshot(fault['id'],fault['generation'])
        validate_core_absent(d['core_stale'])
        d['bus_replacement']=[ordinary_bus_registration(new['index'],new['generation'],u) for u in ['ws73','observer']]
        for row in d['bus_replacement']:validate_bus_registration(row,new['index'],new['generation'],'Installed')
        d['bus_stale']=[ordinary_bus_registration(fault['id'],fault['generation'],u) for u in ['ws73','observer']]
        for row in d['bus_stale']:validate_bus_registration(row,fault['id'],fault['generation'],None)
        d['healthy_after']=[registration(p) for p in ['1-1','1-2']]
        if any(not stable(a,b) for a,b in zip(d['healthy_before'],d['healthy_after'])):raise ValueError('peer identity changed during fault/retry')
        exchange_record(d,'after_retry',['1-1','1-3'],pid)
        d.update(daemon_after=daemon_identity(pid),status='REAL_EARLY_BOOTSTRAP_FAULT_EVIDENCE_PENDING',finished_wall_ns=time.time_ns())
        if d['daemon_after']!=d['daemon_before']:raise ValueError('slkd restart invalidates gate')
        save(d);print('WS73_TARGET_EARLY_FAULT_PASS',flush=True)
    except BaseException as error:
        d.update(status='FAIL',error=str(error),error_type=type(error).__name__);save(d);raise
    finally:
        if not restored and BACKUP.exists() and not FIRMWARE.exists():BACKUP.rename(FIRMWARE)


def corroborate(record,capture,guest_root=None):
    from ws73_connection_control import corroborate as connection_proof
    from ws73_channel_socket import corroborate as channel_proof
    if record['status']!='REAL_EARLY_BOOTSTRAP_FAULT_EVIDENCE_PENDING' or record['daemon_before']!=record['daemon_after']:raise ValueError('completed unchanged daemon gate required')
    fault=validate_fault(record['failed'])
    validate_core_snapshot(record['core_fault'],fault['id'],fault['generation'],2)
    new=record['replacement'];validate_core_snapshot(record['core_replacement'],new['index'],new['generation'],3)
    validate_core_absent(record['core_cancelled']);validate_core_absent(record['core_stale'])
    for label,index,generation,state in [('bus_fault',fault['id'],fault['generation'],'Fault'),('bus_cancelled',fault['id'],fault['generation'],None),('bus_replacement',new['index'],new['generation'],'Installed'),('bus_stale',fault['id'],fault['generation'],None)]:
        rows=record[label]
        if [r['user'] for r in rows]!=['ws73','observer']:raise ValueError('both default observer and control application bus receipts required')
        for row in rows:validate_bus_registration(row,index,generation,state)
    cli=record['core_fault_cli']
    if cli['exit'] or cli['stdout']!=f'Registration: index={fault["id"]} generation={fault["generation"]} state=2 profile=1 bus=4 phase=3 error=-2\n':raise ValueError('actual CLI fault observation required')
    if validate_fault(record['failed_after_business'])!=fault or record['fault_identity']!=fault:raise ValueError('same failed Core identity across actual peer business required')
    if record['failed_selection']['returncode']==0:raise ValueError('failed identity must be refused')
    if record['stats_failed']['fields']!={'Devices':3,'Reserved only':1,'Runtimes':2} or record['stats_after_remove']['fields']!={'Devices':2,'Reserved only':0,'Runtimes':2}:raise ValueError('exact failure and joined cancellation counts required')
    if record['replacement']['generation']<=fault['generation'] or record['replacement']['index']!=fault['id']:raise ValueError('reused slot must have a newer generation')
    if any(not stable(a,b) for a,b in zip(record['healthy_before'],record['healthy_after'])):raise ValueError('peer registration changed')
    if not record['removed_wall_ns']<record['failed']['wall_ns']<=record['failed_after_business']['wall_ns']<record['restored_wall_ns']:raise ValueError('original missing-file interval must cover actual fault and peer data')
    results={}
    for label in ['during_fault','after_retry']:
        path=Path(record[label]['record']);path=guest_root/path.relative_to('/evidence') if guest_root is not None else path
        run=json.loads(path.read_text())
        if run['status']!='EARLY_FAULT_BUSINESS_EVIDENCE_PENDING':raise ValueError('completed original peer application receipts required')
        results[label]=dict(connection=connection_proof(run,capture),data=channel_proof(run,capture))
        if results[label]['data']['round_trips']!=4:raise ValueError('two roles each two real round trips required')
        if label=='during_fault':
            for row in run['channel_socket']:
                for app in row['applications']:
                    if not record['failed']['wall_ns']<=app['start_wall_ns']<=app['end_wall_ns']<=record['failed_after_business']['wall_ns']:raise ValueError('actual business must occur while failed target remains pending')
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['coordinate','business']);p.add_argument('--slkd-pid',type=int,required=True);p.add_argument('--ports',nargs=2);p.add_argument('--output',type=Path);a=p.parse_args()
    if a.mode=='coordinate':coordinate(a.slkd_pid)
    else:business(a)
