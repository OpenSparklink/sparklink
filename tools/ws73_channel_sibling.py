# SPDX-License-Identifier: GPL-2.0-only
"""Compose the existing pre-daemon File/Grant gate with a real sibling link.

Same kernel and four physical controllers; the original Gate owns all ordinary
socket workers and its codec. No daemon hook, second Host or generated reply.
This fixture qualifies Native mechanism isolation, not daemon/SDK policy.
"""
import errno
from pathlib import Path
import secrets
import time

from ws73_management_setup import decode, setup
from sparklink.native import NativeAdapter
from sparklink.structs import SleManagementQuery, SleLinkSnapshot
from ws73_capture import CaptureError, discovery, marker_data
from ws73_channel_grant import Gate, business_evidence, checked_controller_ids, validate, verify_intents, verify_owner
from ws73_native_pair import (connection, stop, drain_events, discovery_operation,
    await_events, check_transport, corroborate_discovery, corroborate_transition)
from ws73_resource_file_gate import announcement
from ws73_management_partial import standby
from ws73_diagnostic_hold import write_marker
from ws73_north_star import file_record

TOKEN='ws73.channel_sibling_business=1'
STATUS='ACTUAL_NATIVE_WITHDRAWAL_WITH_SIBLING_BUSINESS_CORROBORATED'
LABELS=('before_hold','while_held','after_withdrawal')
CONTRACT_VERSION=2


def stage_labels(case):
    if case not in ('release','close','dup'):raise ValueError('explicit Native File case required')
    return (LABELS[0],*(['after_first_control_close']if case=='dup'else[]),*LABELS[1:])


def requested(args):
    value=getattr(args,'managed_channel_sibling_business',False)
    if type(value)is not bool:raise ValueError('boolean Native sibling request required')
    if value and (getattr(args,'command',None)!='run'or getattr(args,'managed_connected_case',None)not in ('release','close','dup')
            or type(getattr(args,'managed_connected_index',0))is not int or getattr(args,'managed_connected_index',0)!=0
            or getattr(args,'managed_channel_grant',False)is not True
            or getattr(args,'managed_channel_revoke_prefix',False)is not True or getattr(args,'setup_release_verify',False)is not True
            or any(getattr(args,k,False)for k in ['qmp_hotplug','fault_recovery','managed_channel_queued_discard','session_service_observe','managed_channel_idle_observe','managed_channel_security','managed_channel_scm_rights','managed_channel_directions','managed_channel_link_down','managed_channel_deadline','managed_security_capabilities','managed_link_snapshot','managed_peer_binding','parallel_pairs','four_device_business','four_device_dynamic_benchmark','four_device_disconnect','four_device_burst','four_device_owned','four_device_update_delivery','four_device_shared_subscription','connection_verify'])
            or getattr(args,'managed_connected_reply',None)):
        raise ValueError('sibling business supports dedicated basic release/close/dup index0 prefix only')
    return value


def boot_enabled(words):
    tokens=[w for w in words if w=='ws73.channel_sibling_business'or w.startswith('ws73.channel_sibling_business=')]
    if not tokens:return False
    if tokens!=[TOKEN]:raise ValueError('one explicit Native sibling-business token required')
    cases=[w.split('=',1)[1]for w in words if w.startswith('ws73.connected_case=')]
    if len(cases)!=1 or cases[0]not in ('release','close','dup'):raise ValueError('one explicit Native File case required')
    for word in ['ws73.channel_grant=1','ws73.channel_revoke_prefix=1','ws73.connected_case='+cases[0],'ws73.connected_index=0']:
        key=word.split('=')[0]
        if[w for w in words if w==key or w.startswith(key+'=')]!=[word]:raise ValueError('standalone index0 real-prefix sibling mode required')
    return True


def require_preparation(package,path):
    if type(package.get('channel_sibling_business_contract_version'))is not int or package['channel_sibling_business_contract_version']!=CONTRACT_VERSION:
        raise ValueError('sibling business requires fresh explicit preparation contract2')
    here=Path(__file__).resolve().parent
    for name in ['ws73_channel_sibling.py','ws73_native_pair.py','ws73_channel_grant.py','ws73_connected_file_gate.py','ws73_channel_prefix_hold.py']:
        if file_record(path/'root/usr/share/sparklink/tools'/name)['sha256']!=file_record(here/name)['sha256']:raise ValueError('sibling preparation/source mismatch: '+name)
    if file_record(here/'ws73_target.py') not in package.get('inputs',[]):
        raise ValueError('sibling preparation requires the exact host runner input')
    entry=path/'root/init'
    if entry.is_symlink()or not entry.is_file()or not entry.stat().st_mode&0o111 or file_record(entry)['sha256']!=file_record(here/'ws73_target_init.sh')['sha256']:
        raise ValueError('sibling business requires current executable VM init')


class Sibling:
    def __init__(self,outer,save,folder):
        self.save=save;self.outer=outer;self.folder=Path(folder)/'sibling';self.folder.mkdir()
        self.handles=[];self.gate=None;self.closed=False
        self.row=dict(version=CONTRACT_VERSION,case=outer['case'],status='STARTING',controller_ids=[2,3],index=0,initial_snapshots=[],usb=[],events=[[],[]],discovery=[],leases=[],hcc_observations=[])
        outer['sibling_business']=self.row;save()
        self.observers=[];self.snapshots=[];self.writers=[]
        try:
            models=[w.split('=',1)[1].split(',')for w in Path('/proc/cmdline').read_text().split()if w.startswith('ws73.expected_models=')]
            if len(models)!=1 or len(models[0])!=4:raise ValueError('four explicit per-leaf models required')
            from ws73_lab_resources import observe_guest_hcc
            for index in(2,3):
                write_marker(self.folder/f'attach-{index}.json',dict(controller=index,guest_port=f'1-{index+1}'))
                deadline=time.monotonic()+90 # same Setup metadata budget as original fixture
                while True:
                    observer=None
                    try:
                        observer=NativeAdapter(index);snapshot=observer.snapshot();setup(bytes(snapshot).hex(),index);break
                    except BaseException as error:
                        if observer is not None:observer.close()
                        if not isinstance(error,OSError)or error.errno not in(errno.ENODEV,errno.EAGAIN):raise
                    if time.monotonic()>deadline:raise TimeoutError('independent sibling Setup metadata')
                    time.sleep(.01)
                self.handles.append(observer);self.observers.append(observer);self.snapshots.append(snapshot)
                root=Path(f'/sys/bus/usb/devices/1-{index+1}');usb=dict(bus=int((root/'busnum').read_text()),device=int((root/'devnum').read_text()))
                self.row['initial_snapshots'].append(bytes(snapshot).hex());self.row['usb'].append(usb)
                self.row['hcc_observations'].append(observe_guest_hcc(dict(usb,port=f'1-{index+1}',index=index,generation=snapshot.generation,address=':'.join(f'{v:02X}'for v in snapshot.address)),models[0][index]));save()
            if bytes(self.snapshots[0].address)==bytes(self.snapshots[1].address):raise ValueError('sibling RF requires distinct actual configured addresses')
            for index,snapshot in zip((2,3),self.snapshots):
                writer=NativeAdapter(index,snapshot.generation);self.handles.append(writer);self.writers.append(writer);self.row['leases'].append(writer.acquire_management(1));save()
            for n,snapshot in enumerate(self.snapshots):
                for identifier,domain in[(101,'advertising'),(102,'scanning')]:self.discover(n,standby(snapshot,identifier,domain))
            self.row['marker']=secrets.token_hex(16);ad=announcement(self.snapshots[1],self.row['marker']);ad.request_id=103;self.discover(1,ad)
            scan=standby(self.snapshots[0],103,'scanning');scan.operation=3;self.row['scan_start_wall_ns']=time.time_ns();self.discover(0,scan)
            deadline=time.monotonic()+10
            while True:
                self.drain();matches=[]
                for event in self.row['events'][0]:
                    if event['event']==0x180b and event['wall_ns']>=self.row['scan_start_wall_ns']:
                        body=bytes.fromhex(event['params']);value=discovery(b'\xa2\x0b\x18'+len(body).to_bytes(2,'little')+body)
                        if value and value['data']==marker_data(self.row['marker']).hex():matches.append(value)
                if matches:break
                if time.monotonic()>deadline:raise TimeoutError('fresh sibling random advertisement')
                time.sleep(.002)
            self.row['scan_match']=matches[0];self.row['scan_end_wall_ns']=time.time_ns();self.discover(0,stop(self.snapshots[0],104,4))
            request=connection(self.snapshots[0],self.snapshots[1]);self.row['connection_input']=bytes(request).hex();self.row['connect_before_wall_ns']=time.time_ns();self.writers[0].submit_connection(request)
            deadline=time.monotonic()+12
            while True:
                result=self.writers[0].connection_result(self.snapshots[0].generation,900);self.drain()
                if result is not None and result.state>=4:break
                if time.monotonic()>deadline:raise TimeoutError('actual sibling Create')
                time.sleep(.002)
            if result.state!=4:raise ValueError('actual sibling Create failed')
            self.row['connected']=bytes(result).hex();self.row['up']=await_events(self.row,self.drain,'sibling Up',[0x15,0x1401]);self.row['connect_after_wall_ns']=time.time_ns()
            self.row['management_before']=[bytes(a.management_status()).hex()for a in self.writers]
            self.row['links_before']=[bytes(a.link_snapshot()).hex()for a in self.observers]
            self.gate=Gate(self.observers,self.snapshots,self.row['leases'],0,self.row,save)
            self.exchange('before_hold');self.row['status']='SIBLING_LINK_LIVE';save()
        except BaseException:
            self.close();raise

    def drain(self):drain_events(self.observers,self.row)
    def discover(self,n,request):discovery_operation(self.writers,self.observers,self.row,self.save,self.drain,n,request)
    def exchange(self,label):
        if label not in stage_labels(self.row['case']):raise ValueError('explicit bounded sibling stage required')
        self.gate.exchange(label);self.save()

    def finish(self):
        self.row['management_after']=[bytes(a.management_status()).hex()for a in self.writers]
        self.row['links_after']=[bytes(a.link_snapshot()).hex()for a in self.observers]
        if self.row['management_before']!=self.row['management_after']or self.row['links_before']!=self.row['links_after']:raise ValueError('sibling authority and connection changed during other-controller withdrawal')
        self.gate.close();self.gate=None;self.row['cleanup']=[]
        for n,writer in enumerate(self.writers):
            entry=dict(controller=2+n,start_wall_ns=time.time_ns());self.row['cleanup'].append(entry);self.save()
            if n==0:self.row['release_before_wall_ns']=entry['start_wall_ns']
            writer.release_management(self.row['leases'][n],1)
            if n==0:self.row['release_after_wall_ns']=time.time_ns()
            deadline=time.monotonic()+20
            while True:
                result=writer.management_status()
                if result.state==0:break
                if result.state!=2:raise ValueError('sibling cleanup did not converge through Revoking')
                if time.monotonic()>deadline:raise TimeoutError('sibling actual Managed cleanup')
                self.drain();time.sleep(.002)
            entry.update(result=bytes(result).hex(),end_wall_ns=time.time_ns());self.save()
        self.row['down']=await_events(self.row,self.drain,'sibling Down',[5,0x1405])
        self.row.update(status='SIBLING_NATIVE_BUSINESS_CONTINUITY_PASS',end_wall_ns=time.time_ns());self.save();self.close()

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if self.gate:self.gate.close();self.gate=None
        finally:
            for handle in reversed(self.handles):handle.close()


def verify(outer):
    row=outer['sibling_business'];g=row['channel_grant']
    labels=stage_labels(outer['case'])
    if row.get('version')!=CONTRACT_VERSION or type(row['version'])is not int or row.get('case')!=outer['case']or row['status']!='SIBLING_NATIVE_BUSINESS_CONTINUITY_PASS'or checked_controller_ids(row['controller_ids'])!=[2,3]:raise CaptureError('complete actual sibling Native pair required')
    if len(g['owners'])!=2 or len(g['workers'])!=2 or len(g['business'])!=2*len(labels):raise CaptureError('complete two-endpoint sibling matrix required')
    if type(outer['index'])is not int or outer['index']!=0 or outer.get('daemon_running')is not False or 'prefix_hold'not in outer:raise CaptureError('dedicated pre-daemon index0 prefix gate required')
    if row['management_before']!=row['management_after']or row['links_before']!=row['links_after']:raise CaptureError('same sibling files/links must remain live through withdrawal')
    if len(row['initial_snapshots'])!=2 or len(row['hcc_observations'])!=2 or len(row['cleanup'])!=2:raise CaptureError('complete sibling identity/HCC/cleanup matrix required')
    for n,index in enumerate((2,3)):
        s=setup(row['initial_snapshots'][n],index);owner=g['owners'][n]
        verify_owner(owner,index,row['leases'][n],3,0)
        if (owner['index'],owner['generation'],owner['lease'])!=(index,s.generation,row['leases'][n]):raise CaptureError('original selected sibling identity and authority required')
        status=decode(SleManagementQuery,row['management_before'][n]);table=decode(SleLinkSnapshot,row['links_before'][n])
        if (status.state,status.flags,status.mode,status.generation,status.lease)!=(1,1,1,s.generation,row['leases'][n])or (table.version,table.generation,table.dev_index,table.profile,table.flags,table.count)!=(1,s.generation,index,1,1,1):raise CaptureError('same original Managed File and physical link required')
        link=table.links[0]
        if (owner['lifetime'],owner['handle'])!=(link.lifetime,link.handle):raise CaptureError('original sibling connection lifetime required')
        hcc=row['hcc_observations'][n]
        if any(hcc[k]!=v for k,v in dict(row['usb'][n],index=index,generation=s.generation,port=f'1-{index+1}',address=':'.join(f'{v:02X}'for v in s.address)).items()):raise CaptureError('sibling HCC identity belongs to original leaf')
        cleanup=row['cleanup'][n];free=decode(SleManagementQuery,cleanup['result'])
        if cleanup['controller']!=index or free.state!=0 or free.generation!=s.generation or not row['channel_grant']['business'][-1]['end_wall_ns']<cleanup['start_wall_ns']<=cleanup['end_wall_ns']:raise CaptureError('sibling cleanup follows actual final business')
    if[g['owners'][n]['index']for n in range(2)]!=[2,3]or g.get('controller_ids')!=[2,3]or [x['label']for x in g['business']]!=[label for label in labels for _ in range(2)]:raise CaptureError('all original bidirectional sibling stages required')
    if g.get('tx_constraint_required')is not True:raise CaptureError('actual constrained sibling sends required')
    verify_intents(g,row)
    stages={label:g['business'][2*i:2*i+2]for i,label in enumerate(labels)}
    before,held,after=[stages[label]for label in LABELS]
    samples=outer['channel_grant']['blocking_witness'];release=outer['release_before_wall_ns'];released=outer['release_after_wall_ns']
    if not(before[-1]['end_wall_ns']<samples[0]['wall_ns']and samples[-1]['wall_ns']<held[0]['start_wall_ns']and held[-1]['end_wall_ns']<release<=released<after[0]['start_wall_ns']):raise CaptureError('actual sibling business must straddle the controlled withdrawal')
    if outer['case']=='dup':
        first=stages['after_first_control_close']
        if not(before[-1]['end_wall_ns']<outer['first_close_wall_ns']<=outer['first_close_quiet_end_ns']<first[0]['start_wall_ns']<=first[-1]['end_wall_ns']<samples[0]['wall_ns']):
            raise CaptureError('actual sibling replies after first dup close must precede the final-close barrier')
    nonces=set();previous=0
    for business in g['business']:
        if not previous<business['start_wall_ns']<business['end_wall_ns']:raise CaptureError('ordered finite sibling business required')
        previous=business['end_wall_ns']
        if len(business['applications'])!=2:raise CaptureError('two actual sibling application receipts required')
        payload=bytes.fromhex(business['payload']);validate(payload,payload,False)
        if payload[8:24]in nonces:raise CaptureError('fresh sibling nonce per request required')
        nonces.add(payload[8:24])
        for n,app in enumerate(business['applications']):
            initiator=n==business['initiator'];validate(bytes.fromhex(app['sent']),payload,not initiator);validate(bytes.fromhex(app['received']),payload,initiator)
    for worker in g['workers']:
        if worker['credentials']['uids']!=[1000]*4 or any(int(v,16)for v in worker['credentials']['caps'].values()):raise CaptureError('ordinary sibling application without capabilities required')
    return row


def identities(outer):
    row=verify(outer)
    return[dict(row['usb'][n],index=index,generation=setup(raw,index).generation,
        address=':'.join(f'{v:02X}'for v in setup(raw,index).address),path=f'1-{index+1}')
        for n,(raw,index)in enumerate(zip(row['initial_snapshots'],(2,3),strict=True))]


def corroborate(outer,capture):
    row=verify(outer);g=row['channel_grant'];sdus,legs=business_evidence(g,row,capture)
    # This pair is attached after the victim fixture has already started.
    # Its qualification window starts after both actual Setup/HCC observations,
    # at the first policy operation; bootstrap cancellations are not promoted
    # to a clean initialization or natural recovery qualification.
    start=row['discovery'][0]['start_wall_ns']
    if max(h['observed_wall_ns']for h in row['hcc_observations'])>=start:
        raise CaptureError('sibling policy window must follow both actual Setup/HCC observations')
    check_transport(row,capture,start,row['end_wall_ns'])
    snapshots=[setup(raw,index)for raw,index in zip(row['initial_snapshots'],(2,3),strict=True)]
    radio,heard=corroborate_discovery(row,capture,snapshots)
    links=[corroborate_transition(row,capture,snapshots,1,0x1401,row['connect_before_wall_ns'],row['connect_after_wall_ns'],'up'),corroborate_transition(row,capture,snapshots,2,0x1403,row['release_before_wall_ns'],row['end_wall_ns'],'down')]
    owners=[dict(row['usb'][n],controller=owner['index'],generation=owner['generation'],lifetime=owner['lifetime'],handle=owner['handle'])for n,owner in enumerate(g['owners'])]
    business=[{k:v[k]for k in ['label','initiator','payload','start_wall_ns','end_wall_ns']}for v in g['business']]
    result=dict(version=CONTRACT_VERSION,case=outer['case'],status=STATUS,controllers=[2,3],owners=owners,business=business,round_trips=len(business),after_first_close_round_trips=2 if outer['case']=='dup'else 0,while_held_round_trips=2,after_withdrawal_round_trips=2,application_UID=1000,daemon_policy_qualified=False,credit_truth=False,full_drain=False,natural_recovery=False,legs=legs,management_unchanged=True,links_unchanged=True,discovery=radio,heard=heard,links=links)
    return result


def valid_summary(proof):
    try:
        labels=stage_labels(proof['case']);count=2*len(labels)
        expected=dict(version=CONTRACT_VERSION,status=STATUS,controllers=[2,3],round_trips=count,after_first_close_round_trips=2 if proof['case']=='dup'else 0,while_held_round_trips=2,after_withdrawal_round_trips=2,application_UID=1000,daemon_policy_qualified=False,credit_truth=False,full_drain=False,natural_recovery=False,management_unchanged=True,links_unchanged=True)
        if not(all(type(proof.get(k))is type(v)and proof[k]==v for k,v in expected.items())and type(proof['legs'])is list and len(proof['legs'])==4*count
            and len(proof['heard'])>=1 and len(proof['links'])==2 and len(proof['discovery'])>0):return False
        owners=proof['owners'];business=proof['business']
        if type(owners)is not list or len(owners)!=2 or[owner['controller']for owner in owners]!=[2,3]or type(business)is not list or len(business)!=count:return False
        if len({(o['bus'],o['device'])for o in owners})!=2:return False
        previous=0
        for i,row in enumerate(business):
            if row['label']!=labels[i//2]or type(row['initiator'])is not int or row['initiator']!=i%2:return False
            if not previous<row['start_wall_ns']<row['end_wall_ns']:return False
            previous=row['end_wall_ns']
            payload=bytes.fromhex(row['payload']);validate(payload,payload,False)
            for j,leg in enumerate(proof['legs'][4*i:4*i+4]):
                n=j//2;owner=owners[n];out=j%2==0;reply=(n!=row['initiator'])if out else(n==row['initiator'])
                value=bytearray(payload);value[28]=int(reply);wire=b'\x1f\0\x3e\0\xf1'+value
                if ((leg['bus'],leg['device'],leg['handle'],leg['direction'])!=(owner['bus'],owner['device'],owner['handle'],'out'if out else'in')or leg['data']!=wire.hex()or not row['start_wall_ns']<=leg['wall_ns']<=row['end_wall_ns']):return False
        return True
    except(CaptureError,ValueError,KeyError,TypeError,IndexError):return False
