#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Four real controllers, two live physical pairs and actual app replies.

Reuses connection/socket/USB proofs. Barriers coordinate test workers, never
fabricate controller events or data. Positive fixed-channel and controlled pair-Disconnect slices only;
no transport-fault, dynamic-channel, protected SSAP or natural-recovery claim.
"""
import argparse
import hashlib
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
ISOLATION_SCOPE = 'four real WS73 controlled pair disconnect with surviving business'
BURST_SCOPE = 'four real WS73 two-pair 2042-byte burst and observed budgets'
OWNED_SCOPE = 'four real WS73 two-pair owned SSAP approvals and owner loss'
DELIVERY_SCOPE = 'four real WS73 two-pair protected update delivery'
SUBSCRIPTION_SCOPE = 'four real WS73 two-pair protected shared subscriptions'
PENDING = 'PARALLEL_BUSINESS_EVIDENCE_PENDING'
SUCCESS = 'CONNECTED_PAIR_BUSINESS_EVIDENCE_PENDING'
SEQUENCE = [('ready', 0), *[(kind, n) for n in range(2)
                           for kind in ['linked', 'business-ready', 'business-done', 'down']]]
from ws73_discovery_policy_capture import checked_expectation, expected_policy, FIELDS

BARRIER_SECONDS = 45  # bounded test synchronization, not a refreshed protocol deadline


def stage_specs(isolation,progress=False):
    if progress and not isolation:raise ValueError('progress contract is Disconnect-only')
    stages=[('ready',0,(0,1))]
    for n in range(2):
        stages.extend([('linked',n,(0,1)),('business-ready',n,(0,1))])
        if progress:stages.append(('business-progress',n,(1-n,)))
        stages.extend([('business-done',n,(n,)),('business-done',n,(1-n,))]
                      if isolation else [('business-done',n,(0,1))])
        stages.append(('down',n,(0,1)))
    return stages


def subscription_case(record):
    """Reuse the original typed shared-case contract, without enabling new cases."""
    from ws73_ssap_subscription import shared_case
    enabled=record.get('shared_subscription_mode',False)
    if type(enabled)is not bool:raise CaptureError('typed subscription mode required')
    case=shared_case(dict(record,ssap_subscription_shared_required=enabled,ssap_subscription_shared_contract_version=record.get('parallel_subscription_contract_version')if enabled else None))
    if case not in ('release','expiry','owner-exit'):raise CaptureError('separate four-pair shared case not implemented')
    return case


def rounds_for(isolation,pair,phase,burst=False):
    return 16 if burst else 4 if isolation and pair==phase else 20


class BusinessPair(PairRun):
    SCOPE = SCOPE
    SUCCESS = SUCCESS
    barrier_timeout = BARRIER_SECONDS

    def __init__(self,args):
        self.isolation=bool(getattr(args,'disconnect_isolation',False))
        self.burst=bool(getattr(args,'burst',False))
        self.owned=bool(getattr(args,'owned_ssap',False))
        self.delivery=bool(getattr(args,'update_delivery',False))
        self.subscription=bool(getattr(args,'shared_subscription',False))
        if sum((self.isolation,self.burst,self.owned,self.delivery,self.subscription))>1:raise ValueError('separate explicit four-device scopes required')
        if self.isolation:self.SCOPE=ISOLATION_SCOPE
        if self.burst:self.SCOPE=BURST_SCOPE
        if self.owned:self.SCOPE=OWNED_SCOPE
        if self.delivery:self.SCOPE=DELIVERY_SCOPE
        if self.subscription:self.SCOPE=SUBSCRIPTION_SCOPE
        super().__init__(args)
        self.data['disconnect_isolation']=self.isolation
        self.data['burst_mode']=self.burst
        if self.delivery:self.data.update(update_delivery_mode=True,parallel_delivery_contract_version=1)
        if self.subscription:self.data.update(shared_subscription_mode=True,parallel_subscription_contract_version=1)
        if self.subscription and getattr(args,'ssap_subscription_shared_case','release')!='release':
            self.data.update(ssap_subscription_shared_case=args.ssap_subscription_shared_case,ssap_subscription_shared_lifetime_contract_version=1)
        subscription_case(self.data)
        if self.owned:
            self.data['owned_ssap_mode']=True
            self.data['parallel_owned_contract_version']=1
        if self.isolation:
            self.data['disconnect_progress_contract_version']=1
            self.channel_application_progress=self._application_progress

    # Share bounded pipe coordination and cleanup, not the RF-only start/match hooks.
    def ctl(self, identity, *words):
        return Run.ctl(self, identity, *words)

    def stop(self, identity, domain):
        return Run.stop(self, identity, domain)

    def connection_barrier(self, kind, phase):
        self.barrier(kind, len(self.data['connection_control']['phases'])-1)

    def channel_barrier(self, row):
        row['rounds']=rounds_for(self.isolation,self.args.pair,row['phase'],self.burst)
        self.barrier('business-ready', row['phase'])

    def channel_completion(self,phase,finish):
        # Keep the one typed Disconnect implementation in connection_control.
        return finish if self.isolation else None

    def _application_progress(self,row):
        # A hint wakes the test coordinator;actual USB/app oracles still decide.
        # Blocking this supervisor on its pipe does not pause the applications.
        if self.args.pair==row['phase'] or 'business_progress_hint'in row:return
        apps=[a for a in row['applications']if a['role']=='initiator']
        if not apps:return
        app=apps[0]
        with Path(app['output_files'][0]).open('rb')as stream:prefix=stream.read(128*1024+1)
        if len(prefix)>128*1024:raise CaptureError('bounded application progress stdout exceeded')
        values=re.findall(rb'^NativeChannelRoundTrip: sequence=(\d+) elapsed_ms=\d+ bytes=[0-9a-f]+\n',prefix,re.M)
        sequences=[int(v)for v in values]
        if sequences!=list(range(len(sequences))):raise CaptureError('invalid original progress sequence')
        if len(sequences)<2:return
        row['business_progress_hint']=dict(version=1,minimum_replies=2,sequences=sequences,
            pid=app['pid'],prefix_bytes=len(prefix),prefix_sha256=hashlib.sha256(prefix).hexdigest(),observed_wall_ns=time.time_ns())
        self.save();self.barrier('business-progress',row['phase'])

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
    isolation=bool(getattr(args,'disconnect_isolation',False))
    burst=bool(getattr(args,'burst',False))
    owned=bool(getattr(args,'owned_ssap',False))
    delivery=bool(getattr(args,'update_delivery',False))
    subscription=bool(getattr(args,'shared_subscription',False))
    if sum((isolation,burst,owned,delivery,subscription))>1:raise ValueError('separate explicit four-device scopes required')
    record=dict(format_version=1,scope=SUBSCRIPTION_SCOPE if subscription else DELIVERY_SCOPE if delivery else OWNED_SCOPE if owned else BURST_SCOPE if burst else ISOLATION_SCOPE if isolation else SCOPE,disconnect_isolation=isolation,burst_mode=burst,status='RUNNING',application_identity=ordinary_identity(),
                workers=[],stages=[],policy_expectation=policy_expectation(args.policy_expectation),
                barrier_budget_seconds=BARRIER_SECONDS,physical_unplug_acceptance=False,
                automatic_fault_recovery_acceptance=False,fault_isolation_acceptance=False)
    if isolation:record['disconnect_progress_contract_version']=1
    if owned:record.update(owned_ssap_mode=True,parallel_owned_contract_version=1)
    if delivery:record.update(update_delivery_mode=True,parallel_delivery_contract_version=1)
    if subscription:record.update(shared_subscription_mode=True,parallel_subscription_contract_version=1)
    if subscription and args.ssap_subscription_shared_case!='release':
        record.update(ssap_subscription_shared_case=args.ssap_subscription_shared_case,ssap_subscription_shared_lifetime_contract_version=1)
    case=subscription_case(record)
    def save():
        temp=output/'run.tmp';temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(output/'run.json')
    processes=[];reader=None;save()
    try:
        for pair in range(2):
            argv=[sys.executable,str(Path(__file__).resolve()),'pair','--pair',str(pair),'--ports',
                  *args.ports[pair*2:pair*2+2],'--slctl',str(args.slctl),'--slkd-pid',str(args.slkd_pid),
                  '--output',str(output/f'pair-{pair}'),*(['--disconnect-isolation'] if isolation else []),*(['--burst'] if burst else []),*(['--owned-ssap']if owned else []),*(['--update-delivery']if delivery else []),*(['--shared-subscription']if subscription else []),*(['--ssap-subscription-shared-case',case]if case!='release'else []),
                  '--policy-expectation',str(args.policy_expectation)]
            row=dict(args=argv,start_wall_ns=time.time_ns(),stdout='',stderr='');record['workers'].append(row)
            p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            processes.append(p);row['pid']=p.pid;save()
        reader=EventReader(processes,record['workers'],timeout_seconds=BARRIER_SECONDS)
        held_down={}
        for kind,number,participants in stage_specs(isolation,progress=isolation):
            waits=[held_down.pop((number,pair)) if (kind=='down' and (number,pair) in held_down)
                   else reader.wait_one(processes,pair,kind,number) for pair in participants]
            stage=dict(phase=kind,round=number,waits=waits,release_wall_ns=time.time_ns());record['stages'].append(stage);save()
            for pair in participants:
                p=processes[pair];p.stdin.write(f'parallel-{kind}-{number}\n'.encode());p.stdin.flush()
            print(f'WS73_PARALLEL_BUSINESS_STAGE: {kind} role_phase={number} pairs={participants}',flush=True)
            if isolation and kind=='business-done' and participants==(number,):
                # Let only this pair issue actual Disconnect. Hold its Down ack
                # until the other pair finishes real business and its own Down.
                held_down[number,number]=reader.wait_one(processes,number,'down',number)
        if held_down:raise CaptureError('unreleased Down barrier')
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
            if any(reader.queue.values()):
                if record.get('status')=='FAIL':
                    record.setdefault('cleanup_errors',[]).append('extra barrier events')
                else:record.update(status='FAIL',error='extra barrier events')
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
    isolation=record.get('disconnect_isolation',False)
    burst=record.get('burst_mode',False)
    owned=record.get('owned_ssap_mode',False)
    delivery=record.get('update_delivery_mode',False)
    subscription=record.get('shared_subscription_mode',False)
    case=subscription_case(record)
    from ws73_ssap_subscription import shared_case
    if any(type(v)is not bool for v in(isolation,burst,owned,delivery,subscription))or sum((isolation,burst,owned,delivery,subscription))>1:raise CaptureError('explicit exclusive scope booleans required')
    version=record.get('disconnect_progress_contract_version')
    if 'disconnect_progress_contract_version'in record and (type(version)is not int or version!=1 or not isolation):raise CaptureError('explicit supported Disconnect progress contract required')
    progress=version==1
    if owned:
        if type(record.get('parallel_owned_contract_version'))is not int or record['parallel_owned_contract_version']!=1:raise CaptureError('explicit Owned SSAP contract required')
    elif 'parallel_owned_contract_version'in record:raise CaptureError('Owned contract without Owned request')
    if delivery:
        if type(record.get('parallel_delivery_contract_version'))is not int or record['parallel_delivery_contract_version']!=1:raise CaptureError('explicit protected delivery contract required')
    elif 'parallel_delivery_contract_version'in record:raise CaptureError('unrequested protected delivery contract')
    if subscription:
        if type(record.get('parallel_subscription_contract_version'))is not int or record['parallel_subscription_contract_version']!=1:raise CaptureError('explicit shared subscription contract required')
    elif 'parallel_subscription_contract_version'in record:raise CaptureError('unrequested shared subscription contract')
    scope=SUBSCRIPTION_SCOPE if subscription else DELIVERY_SCOPE if delivery else OWNED_SCOPE if owned else BURST_SCOPE if burst else ISOLATION_SCOPE if isolation else SCOPE
    if (record.get('format_version')!=1 or record.get('scope')!=scope or record.get('status')!=PENDING
            or record.get('barrier_budget_seconds')!=BARRIER_SECONDS or len(record.get('workers',[]))!=2
            or record.get('failure_shutdown') or record.get('cleanup_errors') or any(record.get(k) is not False for k in
                ['physical_unplug_acceptance','automatic_fault_recovery_acceptance','fault_isolation_acceptance'])):
        raise CaptureError('complete explicit positive business slice required')
    checked_expectation(record['policy_expectation']['data'])
    app=record['application_identity']
    if app['uids']!=[1000]*4 or any(int(app[k],16) for k in ['cap_eff','cap_prm','cap_amb']):
        raise CaptureError('actual ordinary coordinator required')
    owners=[];daemon=None;bus=None;pids=set()
    specs=stage_specs(isolation,progress)
    if [(s['phase'],s['round']) for s in record['stages']]!=[(kind,n) for kind,n,_ in specs]:
        raise CaptureError('all ordered live connection/business barriers required')
    observations={}
    for stage,(_,_,participants) in zip(record['stages'],specs):
        if len(stage['waits'])!=len(participants):raise CaptureError('exact participating live pipes required')
        for pair,seen in zip(participants,stage['waits']):
            event=seen['event'];key=(pair,event['phase'],event['round'])
            if event['pair']!=pair or (event['phase'],event['round'])!=(stage['phase'],stage['round']) or key in observations:raise CaptureError('unique original live barrier required')
            observations[key]=(stage,seen)
    if isolation:
        for n in range(2):
            victim_done=observations[n,'business-done',n][0]
            survivor_done=observations[1-n,'business-done',n][0]
            down=observations[n,'down',n][1]
            if not victim_done['release_wall_ns']<=down['observed_wall_ns']<=survivor_done['release_wall_ns']:
                raise CaptureError('victim actual Down must precede survivor disconnect admission')
            if progress and observations[1-n,'business-progress',n][0]['release_wall_ns']>victim_done['release_wall_ns']:
                raise CaptureError('survivor progress must release before victim Disconnect admission')
    for pair,w in enumerate(record['workers']):
        r=w['run']
        if subscription_case(r)!=case:raise CaptureError('original worker shared case mismatch')
        if w['exit'] or r['status']!=SUCCESS or r['scope']!=scope or r.get('disconnect_isolation',False)!=isolation or r.get('burst_mode',False)!=burst or r.get('owned_ssap_mode',False)is not owned or r.get('update_delivery_mode',False)is not delivery or r.get('shared_subscription_mode',False)is not subscription or r['pair']!=pair or r['application_identity']!=app:
            raise CaptureError('actual successful ordinary pair workers required')
        if (r.get('disconnect_progress_contract_version')!=version
                or ('disconnect_progress_contract_version'in r and type(r['disconnect_progress_contract_version'])is not int)):
            raise CaptureError('worker progress contract mismatch')
        if owned:
            if type(r.get('parallel_owned_contract_version'))is not int or r['parallel_owned_contract_version']!=1:raise CaptureError('worker Owned contract mismatch')
        elif 'parallel_owned_contract_version'in r:raise CaptureError('unrequested worker Owned contract')
        if delivery:
            if type(r.get('parallel_delivery_contract_version'))is not int or r['parallel_delivery_contract_version']!=1:raise CaptureError('worker protected delivery contract mismatch')
        elif 'parallel_delivery_contract_version'in r:raise CaptureError('unrequested worker delivery contract')
        if subscription:
            if type(r.get('parallel_subscription_contract_version'))is not int or r['parallel_subscription_contract_version']!=1:raise CaptureError('worker subscription contract mismatch')
        elif 'parallel_subscription_contract_version'in r:raise CaptureError('unrequested worker subscription contract')
        if delivery or subscription:
            if len(r.get('security_agent',[]))!=2 or any(v.get('mode')!='numeric-approve'or v.get('ssap_security_requirement')!=2 for v in r['security_agent']):raise CaptureError('actual numeric protected2 Agent request required')
        elif r.get('security_agent'):raise CaptureError('unrequested security mode')
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
        if argv.count('--update-delivery')!=int(delivery):raise CaptureError('explicit worker protected delivery selector required')
        if argv.count('--shared-subscription')!=int(subscription):raise CaptureError('explicit worker shared subscription selector required')
        if argv.count('--ssap-subscription-shared-case')!=int(case!='release')or case!='release'and argv[argv.index('--ssap-subscription-shared-case')+1]!=case:raise CaptureError('explicit original worker shared case required')
        if argv.count('--owned-ssap')!=int(owned):raise CaptureError('explicit worker Owned selector required')
        if argv.count('--burst')!=int(burst):raise CaptureError('explicit worker burst selector required')
        if argv.count('--disconnect-isolation')!=int(isolation):raise CaptureError('explicit worker disconnect selector required')
        if argv[2:12]!=expected or argv[-2:]!=['--policy-expectation',record['policy_expectation']['file']['path']]:
            raise CaptureError('original CLI/port/daemon worker affinity required')
        if r['policy_expectation']!=record['policy_expectation']:raise CaptureError('same frozen policy required')
        if (len(r['cleanup'])!=2 or any(v['status']!='STOP_CONFIRMED' for v in r['cleanup'])
                or len(r['connection_cleanup'])!=2 or any(v['status']!='NO_CURRENT_QUERIED_LINKS' for v in r['connection_cleanup'])):
            raise CaptureError('all four actual owned cleanups required')
        if len(r.get('channel_socket',[]))!=2 or any(x['rounds']!=rounds_for(isolation,pair,n,burst) or x['message_bytes']!=(2042 if burst else 61) or x.get('close_prefix') or x.get('burst',False)!=burst or x.get('boundary_check') for n,x in enumerate(r['channel_socket'])):
            raise CaptureError('exact requested role/message-size/burst slice required')
        if any(x.get('ssap_owned_required',False)is not owned or (owned and len(x.get('ssap_owned',[]))!=4)for x in r['channel_socket']):raise CaptureError('exact original Owned production cases required')
        if any(x.get('ssap_update_delivery_required',False)is not delivery or (delivery and (x.get('security_requirement')!=2 or x.get('ssap_security_requirement')!=2 or x.get('ssap_update_delivery_version')!=2))for x in r['channel_socket']):raise CaptureError('original protected2 updatev2 matrix required')
        for x in r['channel_socket']:
            if x.get('ssap_subscription_required',False)is not subscription:raise CaptureError('explicit subscription request required')
            if subscription and(x.get('ssap_subscription_shared_required')is not True or shared_case(x)!=case or type(x.get('parallel_pair'))is not int or x['parallel_pair']!=pair or x.get('security_requirement')!=2 or x.get('ssap_security_requirement')!=2):raise CaptureError('original protected shared case matrix and pair required')
        sequence=[('ready',0)]
        for n in range(2):
            sequence.extend([('linked',n),('business-ready',n)])
            if progress and pair!=n:sequence.append(('business-progress',n))
            sequence.extend([('business-done',n),('down',n)])
        if [(s['phase'],s['round']) for s in r['barriers']]!=sequence:raise CaptureError('worker barrier history mismatch')
        for index,entry in enumerate(r['barriers']):
            stage,seen=observations[pair,entry['phase'],entry['round']];live=seen['event']
            if entry['phase']=='ready' and entry.get('owners')!=r['initial']:
                raise CaptureError('Ready barrier must name its original pair')
            if (live!={k:v for k,v in entry.items() if k!='ack_wall_ns'} or live['pair']!=pair
                    or not live['wait_wall_ns']<=seen['observed_wall_ns']<=stage['release_wall_ns']<=entry['ack_wall_ns']
                    or entry['ack_wall_ns']-live['wait_wall_ns']>BARRIER_SECONDS*1_000_000_000):
                raise CaptureError('live pipe/parent release/worker acknowledgement cause mismatch')
        if progress:verify_progress_contract(r,observations,pair)
        owners.extend(r['initial'])
    for key in ['port','path','address','index']:
        if len({o[key] for o in owners})!=4:raise CaptureError('four distinct original owner identities required')
    if len({(o['bus'],o['device']) for o in owners})!=4 or len({(o['index'],o['generation']) for o in owners})!=4:
        raise CaptureError('four independent USB/controller registrations required')
    physical_device_descriptors(owners)
    return owners


def verify_progress_contract(run,observations,pair):
    for n,row in enumerate(run['channel_socket']):
        if row.get('post_application_disconnect')is not True:raise CaptureError('actual application-completion Disconnect required')
        from ws73_channel_socket import validate_passive_controller_stages
        validate_passive_controller_stages(run,row,run['connection_control']['phases'][n])
        if pair==n:
            if 'business_progress_hint'in row:raise CaptureError('victim cannot claim survivor progress')
            continue
        hint=row.get('business_progress_hint',{});apps=[a for a in row['applications']if a['role']=='initiator']
        if len(apps)!=1:raise CaptureError('one original progress application required')
        app=apps[0];prefix_bytes=hint.get('prefix_bytes');sequences=hint.get('sequences')
        if (type(hint.get('version'))is not int or hint['version']!=1
                or hint.get('minimum_replies')!=2 or hint.get('pid')!=app['pid']
                or type(prefix_bytes)is not int or not 0<prefix_bytes<=128*1024
                or not isinstance(sequences,list)or not 2<=len(sequences)<=20
                or any(type(v)is not int for v in sequences)or sequences!=list(range(len(sequences)))):
            raise CaptureError('bounded original survivor progress hint required')
        prefix=app['stdout'].encode()[:prefix_bytes]
        values=[int(v)for v in re.findall(rb'^NativeChannelRoundTrip: sequence=(\d+) elapsed_ms=\d+ bytes=[0-9a-f]+\n',prefix,re.M)]
        event=observations[pair,'business-progress',n][1]['event']
        if (len(prefix)!=prefix_bytes or hashlib.sha256(prefix).hexdigest()!=hint.get('prefix_sha256')or values!=sequences
                or not app['start_wall_ns']<=hint['observed_wall_ns']<=event['wait_wall_ns']<=app['end_wall_ns']):
            raise CaptureError('progress hint differs from original application stdout/timeline')


def pair_capture(capture, owners):
    keys={(o['bus'],o['device']) for o in owners}
    return {k:([r for r in v if (r['bus'],r['device']) in keys] if isinstance(v,list) else v)
            for k,v in capture.items()}


def overlap_window(windows):
    if len(windows)!=2 or any(len(w)!=2 or w[0]>=w[1] for w in windows):raise CaptureError('two real business windows required')
    start,end=max(w[0] for w in windows),min(w[1] for w in windows)
    if start>=end:raise CaptureError('actual business USB intervals did not overlap')
    return [start,end]


def corroborate(record,capture,*,evidence=None):
    from ws73_connection_control import corroborate as connection_proof
    from ws73_connection_objects import corroborate as object_proof
    from ws73_channel_socket import corroborate as channel_proof,application_frames
    from ws73_rf_rounds import corroborate_stops
    owners=verify_records(record);pairs=[];nonces=set();sequences=set()
    isolation=record.get('disconnect_isolation',False);burst=record.get('burst_mode',False);owned=record.get('owned_ssap_mode',False);delivery=record.get('update_delivery_mode',False)
    subscription=record.get('shared_subscription_mode',False)
    if subscription and evidence is None:raise CaptureError('original root subscription artifacts required')
    for w in record['workers']:
        r=w['run'];subset=pair_capture(capture,r['initial'])
        conn=connection_proof(r,subset);objects=object_proof(r,subset,conn);channel=channel_proof(r,subset)
        if channel['round_trips']!=(32 if burst else 24 if isolation else 40):raise CaptureError('all actual peer replies per pair required')
        if burst and (channel.get('long_pdu_acceptance') is not True or channel.get('software_backpressure_acceptance') is not True):
            raise CaptureError('actual long-fragment and finite-queue pressure proofs required')
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
        entry=dict(connections=conn,objects=objects,channel=channel,metadata=metadata,policy_readbacks=policy_rows)
        if delivery or subscription:
            from ws73_security_agent import corroborate as security_proof
            entry['security']=security_proof(r,subset)
        if subscription:
            from ws73_ssap_subscription import verify_supervisor_artifacts
            from ws73_ssap_shared import configuration_wire
            entry['subscription_supervision']=verify_supervisor_artifacts(r,evidence,pair=r['pair'])
            entry['subscription_configuration']=configuration_wire(r,subset)
        if burst:
            from ws73_credit_observation import observe_phase
            entry['budget_observations']=[observe_phase(row,subset) for row in r['channel_socket']]
        pairs.append(entry)
    overlaps=[]
    for n in range(2):
        windows=[];lifetimes=[]
        for number,pair in enumerate(pairs):
            legs=pair['channel']['proofs'][n]['legs']
            if len(legs)!=2*rounds_for(isolation,number,n,burst):raise CaptureError('exact bidirectional business message pairs required')
            window=[min(v['tx']['wall_ns'] for v in legs),max(v['rx']['wall_ns'] for v in legs)]
            up=pair['connections'][n]['steps'][0]['outcomes'];down=pair['connections'][n]['steps'][1]['outcomes']
            if max(v['wall_ns'] for v in up)>window[0] or min(v['wall_ns'] for v in down)<window[1]:
                raise CaptureError('business must fall within actual physical Up/Down')
            windows.append(window);lifetimes.append([max(v['wall_ns'] for v in up),min(v['wall_ns'] for v in down)])
        overlap=overlap_window(windows)
        if overlap[0]<max(v[0] for v in lifetimes) or overlap[1]>min(v[1] for v in lifetimes):raise CaptureError('both physical connections must coexist during real business')
        overlaps.append(dict(role_phase=n,business_windows=windows,overlap_wall_ns=overlap))
    return dict(status='FOUR_REAL_PARALLEL_SHARED_SUBSCRIPTION_CORROBORATED'if subscription else 'FOUR_REAL_PARALLEL_UPDATE_DELIVERY_CORROBORATED'if delivery else 'FOUR_REAL_PARALLEL_OWNED_SSAP_CORROBORATED'if owned else 'FOUR_REAL_PARALLEL_BURST_CORROBORATED' if burst else 'FOUR_REAL_DISCONNECT_ISOLATION_CORROBORATED' if isolation else 'FOUR_REAL_PARALLEL_BUSINESS_CORROBORATED',pairs=pairs,overlaps=overlaps,
                **(dict(parallel_subscription_contract_version=1,parallel_subscription_control=record,shared_subscription=subscription_parallel_proof(pairs,case=subscription_case(record)),shared_subscription_acceptance=True)if subscription else{}),
                **(dict(parallel_delivery_contract_version=1,parallel_delivery_control=record,update_delivery=delivery_parallel_proof(pairs),update_delivery_acceptance=True)if delivery else{}),
                **(dict(parallel_owned_contract_version=1,parallel_owned_control=record,owned_ssap=owned_parallel_proof(pairs),owned_ssap_acceptance=True)if owned else{}),
                **(dict(disconnect_progress_contract_version=1)if record.get('disconnect_progress_contract_version')==1 else{}),
                **(dict(disconnect_progress_control=record)if record.get('disconnect_progress_contract_version')==1 else{}),
                **(dict(disconnect_proofs=disconnect_proofs(pairs),controlled_disconnect_isolation_acceptance=True) if isolation else {}),
                **(dict(long_pdu_acceptance=True,software_backpressure_acceptance=True,observed_controller_pool_saturation_and_resumption=True,controller_credit_correctness_proof=False,fairness_acceptance=False) if burst else {}),
                controller_count=len(owners),round_trips=64 if burst else 48 if isolation else 80,ordinary_uid=1000,
                fixed_basic_channel_business_acceptance=True,fault_isolation_acceptance=False,
                dynamic_channel_acceptance=False,automatic_fault_recovery_acceptance=False,
                protected_ssap_acceptance=delivery or subscription,full_goal_complete=False)


def protected_pair_security(pair):
    """Same original numeric/install/Grant witnesses for each protected scope."""
    security=pair.get('security',{})
    if (security.get('status')!='REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS'
            or security.get('business_round_trips')!=40 or security.get('current_security_snapshots')!=8
            or len(security.get('phases',[]))!=2):raise CaptureError('actual per-pair numeric and security proof required')
    for n,phase in enumerate(security['phases']):
        if (phase.get('mode')!='numeric-approve'or phase.get('application_phase')!=n
                or phase.get('application_security_requirement')!=2 or phase.get('ssap_security_requirement')!=2
                or phase.get('current_security_snapshots')!=4 or phase.get('protected_grant_refusals')!=4
                or not phase.get('wire')):raise CaptureError('protected2 must include original wire,Grant and current Session witnesses')


def protected_wire_overlaps(pairs,key):
    """Compose already validated business packets with their physical lifetimes."""
    if key not in ('ssap_update_delivery','ssap_subscription'):raise CaptureError('fixed protected proof key required')
    def times(packet):
        children=packet.get('ssap_fragments')or packet.get('fragments')
        if children:return [t for child in children for t in times(child)]
        stamp=packet.get('wall_ns')
        if type(stamp)is not int or stamp<=0:raise CaptureError('actual fragment timestamps required')
        return [stamp]
    overlaps=[]
    for n in range(2):
        windows=[];lifetimes=[]
        for pair in pairs:
            legs=[leg for item in pair['channel']['proofs'][n][key]for leg in item['wire']]
            window=[min(t for leg in legs for t in times(leg['tx'])),max(t for leg in legs for t in times(leg['rx']))]
            steps=pair['connections'][n]['steps'];lifetime=[max(e['wall_ns']for e in steps[0]['outcomes']),min(e['wall_ns']for e in steps[1]['outcomes'])]
            if not lifetime[0]<=window[0]<window[1]<=lifetime[1]:raise CaptureError('updates must remain in original physical lifetime')
            windows.append(window);lifetimes.append(lifetime)
        overlap=overlap_window(windows)
        if not max(v[0]for v in lifetimes)<=overlap[0]<overlap[1]<=min(v[1]for v in lifetimes):raise CaptureError('both physical links must coexist during actual updates')
        overlaps.append(dict(role_phase=n,wire_windows=windows,overlap_wall_ns=overlap))
    return overlaps


def delivery_parallel_proof(pairs):
    """Compose existing numeric/security and full update-v2 wire contracts."""
    from ws73_ssap_update_delivery import valid_summary,LENGTHS
    if len(pairs)!=2:raise CaptureError('two protected update pair proofs required')
    for pair in pairs:
        if not valid_summary(pair['channel'],expected_version=2):raise CaptureError('full existing protected update-v2 matrix required')
        protected_pair_security(pair)
    return dict(version=1,update_contract_version=2,security_requirement=2,lengths=list(LENGTHS),
                updates=64,application_replies=64,notifications=32,indications=32,approval_decisions=128,
                numeric_agent_phases=4,overlaps=protected_wire_overlaps(pairs,'ssap_update_delivery'),service_only_deployment=False,
                fault_isolation_acceptance=False,rf_cipher_attested=False,
                scope='Original numeric/install/Grant and update-v2 oracles;actual receiver validation/reply. UID1000control-role,not Bond/full authentication/fairness/recovery or RF cipher attestation')


def subscription_parallel_proof(pairs,*,case='release'):
    """Original full shared case matrix, per-pair root roles and wire oracle."""
    from ws73_ssap_subscription import valid_shared_summary,valid_shared_supervision,valid_snapshot_supervision
    from ws73_ssap_shared import valid_configuration_summary
    if type(case)is not str or case not in ('release','expiry','owner-exit'):raise CaptureError('explicit supported four-pair shared case required')
    if len(pairs)!=2:raise CaptureError('two original shared subscription pairs required')
    supervisors=set();daemon=None
    for number,pair in enumerate(pairs):
        if not valid_shared_summary(pair['channel'],case=case,expected_round_trips=40):raise CaptureError('full shared case matrix and original40socket replies required')
        protected_pair_security(pair)
        root=pair.get('subscription_supervision',{})
        if (not valid_shared_supervision(root,case=case)or not valid_snapshot_supervision(root)
                or type(root.get('parallel_pair'))is not int or root['parallel_pair']!=number
                or not valid_configuration_summary(pair.get('subscription_configuration',{}))):raise CaptureError('original closed root roles and physical configuration required')
        identity=(root['supervisor']['pid'],root['supervisor']['start_ticks'])
        if identity in supervisors or daemon is not None and daemon!=root['daemon']:raise CaptureError('two independent finite supervisors and same daemon required')
        supervisors.add(identity);daemon=root['daemon']
    return dict(version=1,shared_contract_version=1,shared_case=case,security_requirement=2,
                **(dict(shared_lifetime_contract_version=1,partial_expirations=16,expired_discarded=16)if case=='expiry'else dict(shared_lifetime_contract_version=1,partial_owner_exits=16,unconsumed_published=16)if case=='owner-exit'else{}),
                updates=112,application_replies=192,shared_joins=32,retained_releases=16 if case=='owner-exit'else 32,last_disables=16,
                readers=48,providers=8,reader_UID=1004,provider_UID=1005,numeric_agent_phases=4,
                overlaps=protected_wire_overlaps(pairs,'ssap_subscription'),
                whole_application_deployment=False,fault_isolation_acceptance=False,rf_cipher_attested=False,
                scope='Original protected shared-'+case+',actual role probes/closed snapshots/configuration writes/receiver checks. Socket coordinator UID1000;not Bond/full authentication,fairness,recovery or RF cipher attestation')


def owned_parallel_proof(pairs):
    """Compose the existing Owned wire proofs, not another SSAP decoder.

    Both pairs must really perform transactions in overlapping intervals while
    both physical connections are Up. This does not prove that another pair
    made progress at every owner-death instant or establish fault isolation.
    """
    if len(pairs)!=2:raise CaptureError('two original Owned pair proofs required')
    phases=[]
    for n in range(2):
        windows=[];lifetimes=[]
        for pair in pairs:
            cases=pair['channel']['proofs'][n].get('ssap_owned',[])
            if (len(cases)!=4 or {(c['sender'],c['policy'])for c in cases}
                    !={(s,p)for s in (0,1)for p in ('allow','deny')}
                    or any(c.get('owner_lost')is not True or len(c.get('wire',[]))!=10 for c in cases)):
                raise CaptureError('all original Owned approval/denial/owner-loss wire cases required')
            legs=[w for c in cases for w in c['wire']]
            window=[min(w['tx']['wall_ns']for w in legs),max(w['rx']['wall_ns']for w in legs)]
            steps=pair['connections'][n]['steps']
            lifetime=[max(e['wall_ns']for e in steps[0]['outcomes']),min(e['wall_ns']for e in steps[1]['outcomes'])]
            if not lifetime[0]<=window[0]<window[1]<=lifetime[1]:
                raise CaptureError('Owned wire must belong to its physical connection lifetime')
            windows.append(window);lifetimes.append(lifetime)
        overlap=overlap_window(windows)
        if not max(v[0]for v in lifetimes)<=overlap[0]<overlap[1]<=min(v[1]for v in lifetimes):
            raise CaptureError('both physical links must coexist during Owned wire overlap')
        phases.append(dict(role_phase=n,wire_windows=windows,overlap_wall_ns=overlap))
    return dict(version=1,policy_cases=16,request_response_exchanges=80,
                approved_policy_cases=8,denied_policy_cases=8,owner_exit_remote_refusals=16,
                overlaps=phases,service_only_deployment=False,fault_isolation_acceptance=False,
                scope='Existing Owned Engine/caller and independent wire proofs;uid1000/caps0 control-role,not crypto identity,Bond or full lifecycle/fault isolation')


def disconnect_proofs(pairs):
    """Check actual USB timing; a coordinated schedule alone never qualifies.

    No pauses or reply synthesis. Both existing application processes span
    the other pair's Down. Full replies must occur on both sides of it.
    """
    if len(pairs)!=2:raise CaptureError('two original pair proofs required')
    proofs=[]
    for n in range(2):
        victim=pairs[n]['connections'][n]['steps'][1]
        submitted=victim['command']['wall_ns']
        events=victim['outcomes']
        if len(events)!=2 or len({(e['bus'],e['device']) for e in events})!=2:
            raise CaptureError('both actual victim Down endpoints required')
        down=max(e['wall_ns'] for e in events)
        if submitted>=min(e['wall_ns'] for e in events):raise CaptureError('actual Disconnect must precede both Down')
        legs=pairs[1-n]['channel']['proofs'][n]['legs']
        if len(legs)!=40:raise CaptureError('twenty actual surviving replies required')
        windows=[]
        for seq in range(20):
            parts=[v for v in legs if v['sequence']==seq]
            if len(parts)!=2:raise CaptureError('request and reply USB legs per surviving sequence required')
            windows.append([min(v['tx']['wall_ns'] for v in parts),max(v['rx']['wall_ns'] for v in parts)])
        before=[i for i,w in enumerate(windows) if w[1]<submitted]
        after=[i for i,w in enumerate(windows) if w[0]>down]
        if len(before)<2 or len(after)<4:raise CaptureError('survivor requires >=2 full replies before Disconnect and >=4 after both Down')
        proofs.append(dict(role_phase=n,victim_pair=n,survivor_pair=1-n,
            disconnect=victim['command'],victim_down=events,before_sequences=before,
            after_down_sequences=after,survivor_round_trip_windows=windows,
            scope='controlled physical Disconnect/Down with continuous same-session app replies; not transport fault or natural recovery'))
    return proofs


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['run','pair'])
    parser.add_argument('--ports',nargs='+',required=True);parser.add_argument('--slctl',type=Path,required=True)
    parser.add_argument('--slkd-pid',type=int,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--policy-expectation',type=Path,required=True);parser.add_argument('--pair',type=int,choices=[0,1])
    parser.add_argument('--disconnect-isolation',action='store_true',help='alternate which physical pair disconnects while the other continues20 real replies; not natural fault recovery')
    parser.add_argument('--shared-subscription',action='store_true',help='full shared-release matrix in bothpairs;actual readers1004/providers1005,closed root snapshots and original80socketreplies')
    parser.add_argument('--update-delivery',action='store_true',help='existing numeric protected2 and full updatev2 notification/indication/appreply matrix in bothpairs')
    parser.add_argument('--owned-ssap',action='store_true',help='existing Owned SSAP caller/Engine in both physical pairs;actual approvals,denials,owner loss and wire overlap')
    parser.add_argument('--burst',action='store_true',help='16 real2042-byte replies perpair perrole; actual queue pressure and scoped pool/NOCP observations')
    parser.add_argument('--ssap-subscription-shared-case',choices=['release','expiry','owner-exit'],default='release',help='existing explicit release,original lease expiry or actual guest reader exit;separate full matrices')
    args=parser.parse_args()
    if sum((args.burst,args.disconnect_isolation,args.owned_ssap,args.update_delivery,args.shared_subscription))>1:parser.error('select one explicit scope')
    if args.ssap_subscription_shared_case!='release'and not args.shared_subscription:parser.error('shared lifetime case requires its dedicated mode')
    if args.mode=='run':
        if args.pair is not None:parser.error('pair selector internal only')
        return run_parallel(args)
    if args.pair is None or len(args.ports)!=2 or len(set(args.ports))!=2:parser.error('worker requires explicit pair and two ports')
    args.artifact=[name+'='+str(Path(__file__).with_name(name+'.py').resolve()) for name in
                   ['ws73_credit_observation','ws73_parallel_data','ws73_connection_control','ws73_connection_objects','ws73_channel_socket','ws73_ssap_value','ws73_ssap_discovery']]
    args.start_offset_ms=0;args.channel_socket_verify=True;args.channel_socket_rounds=20
    args.channel_socket_bytes=2042 if args.burst else 61
    args.channel_socket_burst=args.burst;args.connection_advertising='negotiable-t'
    args.security_agent='numeric-approve'if args.update_delivery or args.shared_subscription else None
    args.ssap_subscription_verify=args.shared_subscription;args.ssap_subscription_shared_verify=args.shared_subscription
    args.ssap_update_delivery_verify=args.update_delivery
    if args.update_delivery or args.shared_subscription:
        args.artifact.extend(name+'='+str(Path(__file__).with_name(name+'.py').resolve())for name in ['ws73_security_agent','ws73_ssap_update_delivery'])
        args.artifact.append('security_agent_probe=/bin/ws73-security-agent-probe')
    if args.shared_subscription:
        args.artifact.extend(name+'='+str(Path(__file__).with_name(name+'.py').resolve())for name in ['ws73_ssap_subscription','ws73_ssap_shared','ws73_role_snapshot','ws73_application_role'])
    args.ssap_owned_verify=args.owned_ssap
    if args.owned_ssap:args.artifact.append('ws73_ssap_owned='+str(Path(__file__).with_name('ws73_ssap_owned.py').resolve()))
    return BusinessPair(args).execute()


if __name__=='__main__':raise SystemExit(main())
