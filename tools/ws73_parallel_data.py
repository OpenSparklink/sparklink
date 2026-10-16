#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Four real controllers, two live physical pairs and actual app replies.

Reuses connection/socket/USB proofs. Barriers coordinate test workers, never
fabricate controller events or data. Positive fixed-channel slice only; no
fault-isolation, dynamic-channel, protected SSAP or natural-recovery claim.
"""
import argparse
import json
import re
from pathlib import Path
import struct
import subprocess
import sys
import time

from ws73_capture import CaptureError, command_reply, physical_device_descriptors
from ws73_north_star import Run, daemon_identity, file_record, ordinary_identity, stable
from ws73_parallel import PairRun, EventReader, abort_workers, policy_expectation

SCOPE = 'four real WS73 two-pair connected business'
PENDING = 'PARALLEL_BUSINESS_EVIDENCE_PENDING'
SUCCESS = 'CONNECTED_PAIR_BUSINESS_EVIDENCE_PENDING'
SEQUENCE = [('ready', 0), *[(kind, n) for n in range(2)
                           for kind in ['linked', 'business-ready', 'business-done', 'down']]]
from ws73_discovery_policy_capture import checked_expectation, expected_policy, FIELDS

BARRIER_SECONDS = 45  # bounded test synchronization, not a refreshed protocol deadline


class BusinessPair(PairRun):
    SCOPE = SCOPE
    SUCCESS = SUCCESS
    barrier_timeout = BARRIER_SECONDS

    # Share bounded pipe coordination and cleanup, not the RF-only start/match hooks.
    def ctl(self, identity, *words):
        return Run.ctl(self, identity, *words)

    def stop(self, identity, domain):
        return Run.stop(self, identity, domain)

    def connection_barrier(self, kind, phase):
        self.barrier(kind, len(self.data['connection_control']['phases'])-1)

    def channel_barrier(self, row):
        self.barrier('business-ready', row['phase'])

    def execute(self):
        try:
            self.begin()
            self.data['pair'] = self.args.pair
            self.data['barrier_budget_seconds'] = BARRIER_SECONDS
            owners = [self.ready(port) for port in self.args.ports]
            self.data['initial'] = owners
            for owner in owners:
                for domain in ['advertise', 'scan']:
                    self.confirm_initialization_off(owner, domain)
            self.barrier('ready', 0)
            self.barriers_active = True
            from ws73_connection_control import execute
            execute(self, *owners)
            self.barriers_active = False
            self.data['after'] = [self.ready(port) for port in self.args.ports]
            if not all(stable(a,b) for a,b in zip(owners,self.data['after'])):
                raise CaptureError('business changed a registration')
            self.alive()
            self.data['daemon_after'] = daemon_identity(self.args.slkd_pid)
            self.data['bus_after'] = self.bus_identity()
            if self.data['bus_before'] != self.data['bus_after']:
                raise CaptureError('business changed original authenticated daemon')
            for record in [self.data['slctl'],*self.data['sources'],*self.data['artifacts'].values()]:
                if file_record(record['path']) != record: raise CaptureError('executable/source changed')
            if policy_expectation(self.args.policy_expectation) != self.data['policy_expectation']:
                raise CaptureError('frozen policy changed')
            self.data['status'] = self.SUCCESS
        except (Exception, KeyboardInterrupt) as error:
            self.data.update(status='FAIL',error=str(error) or type(error).__name__)
        finally:
            self.barriers_active = False
            self.cleanup_connections()
            self.cleanup()  # existing explicit radio stop/initializer checks
        print(self.data['status'],self.output/'run.json',flush=True)
        return 0 if self.data['status']==self.SUCCESS else 1

    def cleanup_connections(self):
        """Inspect only our two controllers; never reset/release another pair.

        Failure here is a failed run, not a Free/recovery declaration. Late or
        uncertain physical obligations cannot become successful test cleanup.
        """
        from ws73_connection_objects import objects
        rows = self.data.setdefault('connection_cleanup',[])
        for owner in self.data.get('initial',[]):
            row = dict(owner=owner,status='CHECKING'); rows.append(row); self.save()
            try:
                query=self.ctl(owner,'connection-objects');row['query']=len(self.data['commands'])-1
                _, links=objects(query['stdout'],owner)
                for link in links:
                    if link['address'] not in {v['address'] for v in self.data['initial'] if v!=owner}:
                        raise CaptureError('refuse cleanup of an unowned physical peer')
                    result=self.command([str(self.args.slctl),'--adapter',owner['path'],
                                         'disconnect-object',link['path']],18,collection='commands')
                    row.setdefault('disconnect_commands',[]).append(len(self.data['commands'])-1)
                    if result['exit']:raise CaptureError('actual own-lifetime disconnect failed')
                final=self.ctl(owner,'connection-objects');row['final_query']=len(self.data['commands'])-1
                if objects(final['stdout'],owner)[1]:raise CaptureError('own physical links remain')
                row['status']='NO_CURRENT_QUERIED_LINKS'
            except Exception as error:
                row.update(status='FAILED',error=str(error));self.data['status']='FAIL'
            self.save()


def run_parallel(args):
    if len(args.ports)!=4 or len(set(args.ports))!=4:raise ValueError('four distinct guest USB ports required')
    args.slctl=args.slctl.resolve()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False,mode=0o700)
    record=dict(format_version=1,scope=SCOPE,status='RUNNING',application_identity=ordinary_identity(),
                workers=[],stages=[],policy_expectation=policy_expectation(args.policy_expectation),
                barrier_budget_seconds=BARRIER_SECONDS,physical_unplug_acceptance=False,
                automatic_fault_recovery_acceptance=False,fault_isolation_acceptance=False)
    def save():
        temp=output/'run.tmp';temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(output/'run.json')
    processes=[];reader=None;save()
    try:
        for pair in range(2):
            argv=[sys.executable,str(Path(__file__).resolve()),'pair','--pair',str(pair),'--ports',
                  *args.ports[pair*2:pair*2+2],'--slctl',str(args.slctl),'--slkd-pid',str(args.slkd_pid),
                  '--output',str(output/f'pair-{pair}'),'--policy-expectation',str(args.policy_expectation)]
            row=dict(args=argv,start_wall_ns=time.time_ns(),stdout='',stderr='');record['workers'].append(row)
            p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            processes.append(p);row['pid']=p.pid;save()
        reader=EventReader(processes,record['workers'],timeout_seconds=BARRIER_SECONDS)
        for kind,number in SEQUENCE:
            waits=reader.waits(processes,kind,number)
            stage=dict(phase=kind,round=number,waits=waits,release_wall_ns=time.time_ns());record['stages'].append(stage);save()
            for p in processes:p.stdin.write(f'parallel-{kind}-{number}\n'.encode());p.stdin.flush()
            print(f'WS73_PARALLEL_BUSINESS_STAGE: {kind} role_phase={number}',flush=True)
        deadline=time.monotonic()+45
        while any(p.poll() is None for p in processes):
            if time.monotonic()>deadline:raise TimeoutError('bounded business final cleanup/reap')
            reader.pump(.01)
        record['status']=PENDING
    except (Exception,KeyboardInterrupt) as error:
        record.update(status='FAIL',error=str(error) or type(error).__name__)
    finally:
        record['failure_shutdown']=abort_workers(processes,reader)
        for n,p in enumerate(processes):
            p.wait();record['workers'][n].update(exit=p.returncode,end_wall_ns=time.time_ns())
        if reader:
            while reader.watch.get_map():reader.pump(.01)
            reader.watch.close()
            if any(reader.queue.values()):record.update(status='FAIL',error='extra barrier events')
        for n,p in enumerate(processes):
            path=output/f'pair-{n}/run.json'
            if path.is_file():record['workers'][n].update(run=json.loads(path.read_text()),artifact=file_record(path))
            if p.returncode:record['status']='FAIL'
            for pipe in [p.stdin,p.stdout,p.stderr]:pipe.close()
        save()
    if record['status']==PENDING:
        try:verify_records(record)
        except Exception as error:record.update(status='FAIL',error=str(error));save()
    print(record['status'],output/'run.json',flush=True)
    return 0 if record['status']==PENDING else 1


def verify_records(record):
    if (record.get('format_version')!=1 or record.get('scope')!=SCOPE or record.get('status')!=PENDING
            or record.get('barrier_budget_seconds')!=BARRIER_SECONDS or len(record.get('workers',[]))!=2
            or record.get('failure_shutdown') or any(record.get(k) is not False for k in
                ['physical_unplug_acceptance','automatic_fault_recovery_acceptance','fault_isolation_acceptance'])):
        raise CaptureError('complete explicit positive business slice required')
    checked_expectation(record['policy_expectation']['data'])
    app=record['application_identity']
    if app['uids']!=[1000]*4 or any(int(app[k],16) for k in ['cap_eff','cap_prm','cap_amb']):
        raise CaptureError('actual ordinary coordinator required')
    owners=[];daemon=None;bus=None;pids=set()
    if [(s['phase'],s['round']) for s in record['stages']]!=SEQUENCE:
        raise CaptureError('all ordered live connection/business barriers required')
    for pair,w in enumerate(record['workers']):
        r=w['run']
        if w['exit'] or r['status']!=SUCCESS or r['scope']!=SCOPE or r['pair']!=pair or r['application_identity']!=app:
            raise CaptureError('actual successful ordinary pair workers required')
        if type(w['pid']) is not int or w['pid']<=0 or w['pid'] in pids:raise CaptureError('distinct worker PID required')
        pids.add(w['pid'])
        if r['barrier_budget_seconds']!=BARRIER_SECONDS or len(r['initial'])!=2 or len(r['after'])!=2 or not all(stable(a,b) for a,b in zip(r['initial'],r['after'])):
            raise CaptureError('each original registration stays Ready')
        if r['daemon_before']!=r['daemon_after'] or r['bus_before']!=r['bus_after'] or r['bus_before']['pid']!=r['daemon_before']['pid']:
            raise CaptureError('unchanged actual daemon and bus owner required')
        if pair and (daemon!=r['daemon_before'] or bus!=r['bus_before']):raise CaptureError('one shared slkd required')
        daemon,bus=r['daemon_before'],r['bus_before']
        argv=w['args'];expected=['pair','--pair',str(pair),'--ports',*[v['port'] for v in r['initial']],
                    '--slctl',r['slctl']['path'],'--slkd-pid',str(daemon['pid'])]
        if argv[2:12]!=expected or argv[-2:]!=['--policy-expectation',record['policy_expectation']['file']['path']]:
            raise CaptureError('original CLI/port/daemon worker affinity required')
        if r['policy_expectation']!=record['policy_expectation']:raise CaptureError('same frozen policy required')
        if (len(r['cleanup'])!=2 or any(v['status']!='STOP_CONFIRMED' for v in r['cleanup'])
                or len(r['connection_cleanup'])!=2 or any(v['status']!='NO_CURRENT_QUERIED_LINKS' for v in r['connection_cleanup'])):
            raise CaptureError('all four actual owned cleanups required')
        if len(r.get('channel_socket',[]))!=2 or any(x['rounds']!=20 or x['message_bytes']!=61 or x.get('close_prefix') or x.get('burst') or x.get('boundary_check') for x in r['channel_socket']):
            raise CaptureError('exact two-role20-message61-byte slice required')
        if [(s['phase'],s['round']) for s in r['barriers']]!=SEQUENCE:raise CaptureError('worker barrier history mismatch')
        for index,entry in enumerate(r['barriers']):
            stage=record['stages'][index];seen=stage['waits'][pair];live=seen['event']
            if entry['phase']=='ready' and entry.get('owners')!=r['initial']:
                raise CaptureError('Ready barrier must name its original pair')
            if (live!={k:v for k,v in entry.items() if k!='ack_wall_ns'} or live['pair']!=pair
                    or not live['wait_wall_ns']<=seen['observed_wall_ns']<=stage['release_wall_ns']<=entry['ack_wall_ns']
                    or entry['ack_wall_ns']-live['wait_wall_ns']>BARRIER_SECONDS*1_000_000_000):
                raise CaptureError('live pipe/parent release/worker acknowledgement cause mismatch')
        owners.extend(r['initial'])
    for key in ['port','path','address','index']:
        if len({o[key] for o in owners})!=4:raise CaptureError('four distinct original owner identities required')
    if len({(o['bus'],o['device']) for o in owners})!=4 or len({(o['index'],o['generation']) for o in owners})!=4:
        raise CaptureError('four independent USB/controller registrations required')
    physical_device_descriptors(owners)
    return owners


def pair_capture(capture, owners):
    keys={(o['bus'],o['device']) for o in owners}
    return {k:([r for r in v if (r['bus'],r['device']) in keys] if isinstance(v,list) else v)
            for k,v in capture.items()}


def overlap_window(windows):
    if len(windows)!=2 or any(len(w)!=2 or w[0]>=w[1] for w in windows):raise CaptureError('two real business windows required')
    start,end=max(w[0] for w in windows),min(w[1] for w in windows)
    if start>=end:raise CaptureError('actual business USB intervals did not overlap')
    return [start,end]


def corroborate(record,capture):
    from ws73_connection_control import corroborate as connection_proof
    from ws73_connection_objects import corroborate as object_proof
    from ws73_channel_socket import corroborate as channel_proof,application_frames
    from ws73_rf_rounds import corroborate_stops
    owners=verify_records(record);pairs=[];nonces=set();sequences=set()
    for w in record['workers']:
        r=w['run'];subset=pair_capture(capture,r['initial'])
        conn=connection_proof(r,subset);objects=object_proof(r,subset,conn);channel=channel_proof(r,subset)
        if channel['round_trips']!=40:raise CaptureError('forty actual peer replies per pair required')
        corroborate_stops(r,subset)
        for row in r['channel_socket']:
            sent,_=application_frames(row)
            for raw in sent:
                nonce=raw[8:24];sequence=int.from_bytes(raw[24:28],'little')
                if nonce in nonces or sequence in sequences:raise CaptureError('fresh original payload identity across all pairs required')
                nonces.add(nonce);sequences.add(sequence)
        policy_rows=[]
        for command in r['commands']:
            if command['args'][-1:]!=['show']:continue
            matches=[o for o in r['initial'] if command['args']==[r['slctl']['path'],'--adapter',o['path'],'show']]
            values=re.findall('^  Radio policy: '+FIELDS+'$',command['stdout'],re.M)
            if len(matches)!=1 or command['exit'] or len(values)!=1 or list(map(int,values[0]))!=expected_policy(record['policy_expectation']['data'],matches[0]['address']):
                raise CaptureError('actual policy readback must match original staged configuration')
            policy_rows.append(command)
        if len(policy_rows)!=6:raise CaptureError('before/after Ready plus two connection policy readbacks required')
        for owner in r['initial']:
            _,_,_,_,interval,window=expected_policy(record['policy_expectation']['data'],owner['address'])
            scans=[c for c in subset['commands'] if (c['bus'],c['device'])==(owner['bus'],owner['device']) and c['opcode']==0x1001]
            expected=(b'\0\0\1\0'+interval.to_bytes(2,'little')+window.to_bytes(2,'little')).hex()
            if not scans or any(c['params']!=expected for c in scans):raise CaptureError('actual scan parameters differ from frozen policy')
        metadata=[]
        for owner in r['initial']:
            metadata.append([command_reply(subset,owner,op,0,owner['observed_wall_ns'],b'',value)
                for op,value in [(0x404,owner['version']),(0x402,struct.pack('<HBHB',*owner['buffers']).hex()),
                                 (0x403,owner['features']),(0x406,owner['address'].replace(':','').lower())]])
        pairs.append(dict(connections=conn,objects=objects,channel=channel,metadata=metadata,policy_readbacks=policy_rows))
    overlaps=[]
    for n in range(2):
        windows=[];lifetimes=[]
        for pair in pairs:
            legs=pair['channel']['proofs'][n]['legs']
            if len(legs)!=40:raise CaptureError('twenty bidirectional business message pairs required')
            window=[min(v['tx']['wall_ns'] for v in legs),max(v['rx']['wall_ns'] for v in legs)]
            up=pair['connections'][n]['steps'][0]['outcomes'];down=pair['connections'][n]['steps'][1]['outcomes']
            if max(v['wall_ns'] for v in up)>window[0] or min(v['wall_ns'] for v in down)<window[1]:
                raise CaptureError('business must fall within actual physical Up/Down')
            windows.append(window);lifetimes.append([max(v['wall_ns'] for v in up),min(v['wall_ns'] for v in down)])
        overlap=overlap_window(windows)
        if overlap[0]<max(v[0] for v in lifetimes) or overlap[1]>min(v[1] for v in lifetimes):raise CaptureError('both physical connections must coexist during real business')
        overlaps.append(dict(role_phase=n,business_windows=windows,overlap_wall_ns=overlap))
    return dict(status='FOUR_REAL_PARALLEL_BUSINESS_CORROBORATED',pairs=pairs,overlaps=overlaps,
                controller_count=len(owners),round_trips=80,ordinary_uid=1000,
                fixed_basic_channel_business_acceptance=True,fault_isolation_acceptance=False,
                dynamic_channel_acceptance=False,automatic_fault_recovery_acceptance=False,
                protected_ssap_acceptance=False,full_goal_complete=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['run','pair'])
    parser.add_argument('--ports',nargs='+',required=True);parser.add_argument('--slctl',type=Path,required=True)
    parser.add_argument('--slkd-pid',type=int,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--policy-expectation',type=Path,required=True);parser.add_argument('--pair',type=int,choices=[0,1])
    args=parser.parse_args()
    if args.mode=='run':
        if args.pair is not None:parser.error('pair selector internal only')
        return run_parallel(args)
    if args.pair is None or len(args.ports)!=2 or len(set(args.ports))!=2:parser.error('worker requires explicit pair and two ports')
    args.artifact=[name+'='+str(Path(__file__).with_name(name+'.py').resolve()) for name in
                   ['ws73_parallel_data','ws73_connection_control','ws73_connection_objects','ws73_channel_socket','ws73_ssap_value','ws73_ssap_discovery']]
    args.start_offset_ms=0;args.channel_socket_verify=True;args.channel_socket_rounds=20
    args.channel_socket_bytes=61;args.connection_advertising='negotiable-t'
    return BusinessPair(args).execute()


if __name__=='__main__':raise SystemExit(main())
