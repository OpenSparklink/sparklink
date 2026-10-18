# SPDX-License-Identifier: GPL-2.0-only
"""Explicit VM-only real event-ring overflow; no fabricated events or replies.

A guest supervisor briefly pauses the actual daemon, while real advertising and
scanning continue in the kernel. Non-owning ioctl observations bound the pause.
This is a controlled subscriber overflow, not natural hardware recovery.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import time

from ws73_capture import CaptureError, marker_data

FOLDER=Path('/evidence/link-resync')
REQUEST=Path('/evidence/application/passthrough-control/resync-request.json')
MIN_EVENTS=40


def status(text):
    rows=re.findall(r'^  Native links: event_seq=(\d+) revision=(\d+) known=(true|false) lost=(\d+)$',text,re.M)
    if len(rows)!=1:raise CaptureError('one original daemon observation required')
    seq,revision,known,lost=rows[0]
    return dict(event_seq=int(seq),revision=int(revision),known=known=='true',lost=int(lost))


def execute(run,caller,peer,phase):
    before=run.ctl(caller,'show');before_status=status(before['stdout'])
    if not before_status['known']:raise CaptureError('known initial daemon observation required')
    row=dict(phase=phase,caller=caller,peer=peer,marker=run.data['connection_control']['phases'][phase]['marker'],
        before_command=len(run.data['commands'])-1,after_commands=[],status='RUNNING',start_wall_ns=time.time_ns())
    run.data.setdefault('link_resync',[]).append(row);run.save()
    request=dict(phase=phase,caller=caller,peer=peer)
    tmp=REQUEST.with_suffix('.tmp');tmp.write_text(json.dumps(request));tmp.replace(REQUEST)
    response=FOLDER/f'phase-{phase}.json';deadline=time.monotonic()+100
    while not response.exists():
        if time.monotonic()>deadline:raise TimeoutError('finite actual VM subscriber overflow supervisor')
        time.sleep(.05)
    supervisor=json.loads(response.read_text());row['supervisor']=supervisor;run.save()
    if supervisor['status']!='REAL_RING_OVERFLOW_RESUMED':raise CaptureError('real overflow supervisor failed: '+str(supervisor.get('error')))
    minimum=supervisor['observations'][-1]['links']['event_seq']
    deadline=time.monotonic()+3
    while True:
        after=run.ctl(caller,'show');row['after_commands'].append(len(run.data['commands'])-1);run.save()
        value=status(after['stdout'])
        if value['known'] and value['event_seq']>=minimum and value['lost']>before_status['lost']:break
        if time.monotonic()>deadline:raise CaptureError('actual loss must recover Known at the snapshot barrier without daemon restart')
        time.sleep(.02)
    row.update(status='REAL_RING_RESYNC_EVIDENCE_PENDING',end_wall_ns=time.time_ns());run.save()
    run.check(caller);run.check(peer)


def observe(owner):
    import sys
    here=Path(__file__).resolve().parent.parent
    sys.path.insert(0,str(here/('python' if (here/'python').is_dir() else 'bindings/python')))
    from sparklink.native import NativeAdapter
    start=time.time_ns()
    with NativeAdapter(owner['index'],owner['generation']) as adapter:
        controller=adapter.snapshot();table=adapter.link_snapshot();management=adapter.management_status()
    if (controller.address[:]!=list(bytes.fromhex(owner['address'].replace(':','')))
            or controller.flags!=1 or controller.error or table.flags!=1 or table.count
            or management.state!=1 or management.mode!=1 or management.error):
        raise ValueError('same Ready/Held non-owning actual empty physical table required')
    return dict(start_wall_ns=start,end_wall_ns=time.time_ns(),raw_controller=bytes(controller).hex(),
        raw_links=bytes(table).hex(),raw_management=bytes(management).hex(),
        links=dict(event_seq=table.event_seq,revision=table.revision,generation=table.generation))


def supervise(pid):
    if (os.geteuid()!=0 or 'ws73.link_resync=1' not in Path('/proc/cmdline').read_text().split()
            or not Path('/scratch-root-uuid').is_file() or Path(f'/proc/{pid}/comm').read_text().strip()!='slkd'):
        raise ValueError('explicit private native VM supervisor and actual daemon required')
    FOLDER.mkdir(mode=0o755,exist_ok=False)
    for phase in [0,1]:
        deadline=time.monotonic()+180
        while True:
            request=json.loads(REQUEST.read_text()) if REQUEST.exists() else None
            if request is not None and request['phase']==phase:break
            if time.monotonic()>deadline:raise TimeoutError('finite ordered subscriber request')
            time.sleep(.05)
        row=dict(phase=phase,pid=pid,request=request,status='RUNNING',observations=[],start_wall_ns=time.time_ns());paused=False
        try:
            row['before_status']=Path(f'/proc/{pid}/status').read_text()
            row['before']=observe(request['caller']);row['peer_before']=observe(request['peer'])
            row['stop_wall_ns']=time.time_ns();os.kill(pid,signal.SIGSTOP);paused=True
            deadline=time.monotonic()+2
            while True:
                text=Path(f'/proc/{pid}/status').read_text()
                if re.search(r'^State:\s+T ',text,re.M):break
                if time.monotonic()>deadline:raise TimeoutError('actual stopped guest daemon')
                time.sleep(.005)
            row['stopped_status']=text;row['stopped_wall_ns']=time.time_ns();deadline=time.monotonic()+90
            row['observations'].append(observe(request['caller']))
            initial_seq=row['observations'][0]['links']['event_seq']
            while True:
                value=observe(request['caller']);row['observations'].append(value)
                if value['links']['event_seq']-initial_seq>=MIN_EVENTS:break
                if time.monotonic()>deadline:raise TimeoutError('real radio did not advance event ring beyond capacity')
                time.sleep(.1)
            row['peer_stopped']=observe(request['peer'])
            row['continue_wall_ns']=time.time_ns();os.kill(pid,signal.SIGCONT);paused=False
            row['after_status']=Path(f'/proc/{pid}/status').read_text()
            row.update(status='REAL_RING_OVERFLOW_RESUMED',end_wall_ns=time.time_ns())
        except BaseException as error:
            row.update(status='FAIL',error=str(error),error_type=type(error).__name__,end_wall_ns=time.time_ns())
            raise
        finally:
            if paused:os.kill(pid,signal.SIGCONT)
            tmp=FOLDER/f'phase-{phase}.tmp';tmp.write_text(json.dumps(row,indent=2)+'\n');tmp.chmod(0o644);tmp.replace(FOLDER/f'phase-{phase}.json')


def corroborate(run,capture):
    from ws73_management_setup import decode
    from sparklink.structs import SleLinkSnapshot,SleControllerSnapshot,SleManagementQuery
    rows=run['link_resync']
    if len(rows)!=2:raise CaptureError('both real overflow roles required')
    proofs=[]
    for phase,row in enumerate(rows):
        supervisor=row['supervisor'];caller=row['caller'];peer=row['peer']
        if row['phase']!=phase or row['status']!='REAL_RING_RESYNC_EVIDENCE_PENDING' or supervisor['phase']!=phase or supervisor['status']!='REAL_RING_OVERFLOW_RESUMED':raise CaptureError('original ordered successful observations required')
        if supervisor['pid']!=run['daemon_before']['pid'] or supervisor['request']!=dict(phase=phase,caller=caller,peer=peer):raise CaptureError('same actual daemon/owners required')
        if not re.search(r'^State:\s+T ',supervisor['stopped_status'],re.M):raise CaptureError('actual stopped subscriber proof required')
        observations=[supervisor['before'],*supervisor['observations']]
        if not observations or not supervisor['stop_wall_ns']<=supervisor['stopped_wall_ns']<supervisor['continue_wall_ns']<supervisor['end_wall_ns']:raise CaptureError('bounded original signal timeline required')
        for owner,entries in [(caller,observations),(peer,[supervisor['peer_before'],supervisor['peer_stopped']])]:
            revision=None;previous=0
            for entry in entries:
                table=decode(SleLinkSnapshot,entry['raw_links']);controller=decode(SleControllerSnapshot,entry['raw_controller']);management=decode(SleManagementQuery,entry['raw_management'])
                canonical=SleLinkSnapshot(version=1,profile=1,generation=owner['generation'],dev_index=owner['index'],flags=1,event_seq=table.event_seq,revision=table.revision)
                if (table.flags!=1 or table.count or table.generation!=owner['generation'] or table.dev_index!=owner['index'] or table.event_seq<previous
                        or bytes(table)!=bytes(canonical)
                        or controller.flags!=1 or controller.error or controller.generation!=owner['generation'] or bytes(controller.address)!=bytes.fromhex(owner['address'].replace(':',''))
                        or management.state!=1 or management.mode!=1 or management.lease or management.error
                        or entry['links']!=dict(event_seq=table.event_seq,revision=table.revision,generation=table.generation)):
                    raise CaptureError('actual non-owning Ready/Held/known empty table bytes required')
                if revision is not None and table.revision!=revision:raise CaptureError('overflow must not alter physical links')
                revision=table.revision;previous=table.event_seq
        initial=supervisor['observations'][0]['links']['event_seq'];terminal=observations[-1]['links']['event_seq']
        if terminal-initial<MIN_EVENTS:raise CaptureError('actual ring advance beyond 32-event capacity required')
        before=run['commands'][row['before_command']];after=run['commands'][row['after_commands'][-1]]
        a,b=status(before['stdout']),status(after['stdout'])
        if before['exit'] or after['exit'] or before['args'][-1]!='show' or after['args'][-1]!='show' or not a['known'] or not b['known'] or b['event_seq']<terminal or b['lost']<=a['lost'] or b['revision']!=observations[-1]['links']['revision']:raise CaptureError('actual lost counter and canonical Known restoration required')
        start,end=supervisor['stopped_wall_ns'],supervisor['continue_wall_ns']
        heard=[e for e in capture['reports'] if (e['bus'],e['device'])==(caller['bus'],caller['device']) and start<=e['wall_ns']<=end and e['address']==peer['address'] and e['data']==marker_data(row['marker']).hex()]
        if len(heard)<MIN_EVENTS:raise CaptureError('independent real radio reports must exceed ring capacity during pause')
        if len({(e['record'],e['hcc_offset']) for e in heard})!=len(heard):raise CaptureError('distinct original captured radio reports required')
        if any(start<=c['wall_ns']<=end for c in capture['commands']):raise CaptureError('no target/peer reset or wire command allowed during pause')
        proofs.append(dict(phase=phase,actual_reports=heard,initial_event_seq=initial,terminal_event_seq=terminal,lost_delta=b['lost']-a['lost'],barrier=b['event_seq'],revision=b['revision']))
    return proofs


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--slkd-pid',type=int,required=True)
    supervise(parser.parse_args().slkd_pid)
