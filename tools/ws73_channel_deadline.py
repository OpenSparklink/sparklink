# SPDX-License-Identifier: GPL-2.0-only
"""VM-only original PDU deadline with a bounded hold of real IN81 bytes.

Reuses actual ordinary workers, Session/data ledger/tickets and QMP hold.
No synthetic packets, timers refreshed by the test, credit refunds or recovery.
"""
import errno
import json
from pathlib import Path
import secrets
import select
import time
from ws73_channel_grant import send,receive,validate,business_evidence,Address
from ws73_diagnostic_hold import HoldCoordinator,PROPERTIES,write_marker
from ws73_management_setup import decode,setup,query
from ws73_capture import CaptureError
from sparklink.structs import SleLinkSnapshot,SleControllerSnapshot,SleChannelTxStatus,SleConnectionResult,SleConnectionSubmit


class DeadlineCoordinator(HoldCoordinator):
    def __init__(self,share,record,index):
        super().__init__(share,record)
        self.folder=Path(share)/'channel-deadline';self.path='/machine/peripheral/ws73_'+str(index)
        self.record.update(method='BOUNDED8S_HOLD_REAL_IN81_FOR_ORIGINAL5S_PDU_DEADLINE',index=index)

    def poll(self,monitor):
        if self.phase=='arm_ready' and (self.folder/'hold-arm_ready.json').exists():
            budget=monitor.execute('qom-get',{'path':self.path,'property':'test-runtime-in-hold-ms'})
            if type(budget) is not int or budget!=8000:raise ValueError('separate bounded8s test fixture required, default2s is insufficient')
            self.record['hold_budget_ms']=budget
        super().poll(monitor)


def exercise(r,save,grant,observers,writers,snapshots,leases,discover,outcomes,standby,stop,bound_disconnect):
    i=r['index'];p=1-i;folder=Path('/evidence/channel-deadline');folder.mkdir(exist_ok=False)
    row=dict(status='STARTING',markers=[],acks=[],ack_receipts=[],management_before=[bytes(a.management_status()).hex() for a in observers],links_before=[bytes(a.link_snapshot()).hex() for a in observers],ready_before=[bytes(a.snapshot()).hex() for a in observers])
    r['data_deadline']=row;save()
    def stage(phase,ack):
        marker=dict(hold_phase=phase,wall_ns=time.time_ns());write_marker(folder/f'hold-{phase}.json',marker);row['markers'].append(marker);save();limit=time.monotonic()+3
        path=folder/f'hold-{ack}-ack.json'
        while not path.exists():
            if time.monotonic()>limit:raise TimeoutError('real IN81 hold acknowledgment '+ack)
            time.sleep(.005)
        value=json.loads(path.read_text());row['acks'].append(value);row['ack_receipts'].append(dict(stage=ack,wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns()));save()
    # Distinguish live expired intent from the binding retired by PDU timeout.
    # The original held-PDU absolute5s deadline starts only after this probe.
    grant.expired_intent()
    # Allow previous real business completions to drain before arming once.
    time.sleep(.15);row['geometry']=grant.prefix_geometry();save();stage('arm_ready','armed')
    count=row['geometry']['plan']['prime_count']
    if count:
        row['primed']=True;grant.prime(count);stage('wait_held','held')
    grant.arm(sample_before_block=True)
    if not count:stage('wait_held','held')
    row['blocked_result']=receive(grant.parents[i]);row['timeout_observed_wall_ns']=time.time_ns();save()
    marker=b'DEADLINE'+secrets.token_bytes(32);send(grant.parents[i],dict(kind='deny',marker=marker.hex()));row['old_fd_before_release']=receive(grant.parents[i]);save()
    row['management_at_timeout']=[bytes(a.management_status()).hex() for a in observers]
    row['links_at_timeout']=[bytes(a.link_snapshot()).hex() for a in observers]
    row['ready_at_timeout']=[bytes(a.snapshot()).hex() for a in observers];save()
    stage('release_ready','released');time.sleep(.15)
    send(grant.parents[i],dict(kind='deny',marker=marker.hex()));row['old_fd_after_release']=receive(grant.parents[i]);row['post_release_checked_wall_ns']=time.time_ns();save()
    # Physical link was not a fabricated timeout. End it explicitly for cleanup.
    link=decode(SleLinkSnapshot,row['links_at_timeout'][i]).links[0]
    req=bound_disconnect(snapshots[i],link,950);row['cleanup_disconnect_input']=bytes(req).hex();row['cleanup_before_wall_ns']=time.time_ns();writers[i].submit_connection(req)
    row['down']=outcomes('down',[5,0x1405]);row['cleanup_after_wall_ns']=time.time_ns()
    limit=time.monotonic()+2
    while True:
        result=writers[i].connection_result(snapshots[i].generation,950)
        if result is not None and result.state>=4:break
        if time.monotonic()>limit:raise TimeoutError('terminal real cleanup Disconnect result')
        time.sleep(.002)
    row['cleanup_result']=bytes(result).hex()
    row['links_after']=[bytes(a.link_snapshot()).hex() for a in observers];row['ready_after']=[bytes(a.snapshot()).hex() for a in observers]
    for identifier,op in [(104,2),(105,3),(106,4)]:
        request=standby(snapshots[p],identifier,'scanning') if op==3 else stop(snapshots[p],identifier,op);request.operation=op;discover(p,request)
    row['scan_checked_wall_ns']=time.time_ns()
    for n in [i,p]:writers[n].release_management(leases[n],1)
    row['management_cleaned']=[bytes(a.management_status()).hex() for a in observers];row['status']='ACTUAL_ORIGINAL_DEADLINE_PASS';r.update(status='DATA_DEADLINE_PASS',end_wall_ns=time.time_ns())
    try:verify(r)
    except Exception:
        row['status']='VALIDATION_FAILED';r['status']='FAIL';save();raise
    save();print('WS73_TARGET_DATA_DEADLINE_PASS',flush=True)


def verify(r):
    from ws73_protected_grant import requirement
    security=requirement(r)
    if r.get('format_version')!=1 or r.get('status')!='DATA_DEADLINE_PASS' or r.get('case')!='release' or r.get('index') not in [0,1] or r.get('daemon_running') is not False or r.get('synthetic_support') is not False:raise ValueError('separate real original-deadline gate required')
    d=r['data_deadline'];g=r['channel_grant'];i=r['index'];snapshots=[setup(raw,n) for n,raw in enumerate(r['initial_snapshots'])]
    if len(snapshots)!=2 or d['status']!='ACTUAL_ORIGINAL_DEADLINE_PASS':raise ValueError('exact two original controllers required')
    for n in [0,1]:
        for key in ['management_before','management_at_timeout']:
            query(d[key][n],snapshots[n].generation,1)
        if d['management_at_timeout'][n]!=d['management_before'][n]:raise ValueError('original lease must remain held through timeout')
        query(d['management_cleaned'][n],snapshots[n].generation,0)
        before=decode(SleLinkSnapshot,d['links_before'][n]);during=decode(SleLinkSnapshot,d['links_at_timeout'][n]);after=decode(SleLinkSnapshot,d['links_after'][n])
        if before.flags!=1 or before.count!=1 or bytes(during)!=bytes(before) or after.flags!=1 or after.count or after.generation!=before.generation or before.generation!=snapshots[n].generation:raise ValueError('timeout does not fabricate physical Down; real cleanup must follow')
        owner=g['owners'][n];a=Address.from_buffer_copy(bytes.fromhex(owner['address']));link=before.links[0]
        if (a.family,a.controller,a.version,a.flags,a.generation,a.lifetime,a.lease,a.handle,a.local_tcid,a.remote_tcid,a.pi,a.directions,a.security)!=(46,n,2,0,before.generation,link.lifetime,r['leases'][n],link.handle,31,31,241,3,security) or any(a.reserved):raise ValueError('exact current bidirectional ordinary binding required')
        if (owner['generation'],owner['lifetime'],owner['handle'],owner['lease'])!=(a.generation,a.lifetime,a.handle,a.lease):raise ValueError('exact original owner required')
        worker=g['workers'][n]
        if worker['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in worker['credentials']['caps'].values()) or worker['original_errno']!=errno.EBADF:raise ValueError('actual ordinary duplicate fd required')
        for key in ['ready_before','ready_at_timeout','ready_after']:
            ready=decode(SleControllerSnapshot,d[key][n])
            if ready.flags!=1 or ready.generation!=a.generation:raise ValueError('same registered Ready controller required')
    armed=g['armed'];samples=g['blocking_witness'];result=d['blocked_result'];owner=g['owners'][i]
    from ws73_channel_prefix_hold import full_pool,verify_priming
    full_pool(r,'data_deadline')
    if d.get('primed',False):verify_priming(r,'data_deadline')
    if armed['pid']!=g['workers'][i]['pid'] or armed['fd']!=g['workers'][i]['fd'] or len(samples)!=2 or any(v['syscall']!=45 or v['fd']!=armed['fd'] or v['state']!='S' or v['wchan'] not in ['__skb_wait_for_more_packets','schedule_timeout'] for v in samples) or not armed['pre_block_tx_status_wall_ns']<=armed['wall_ns']<samples[0]['wall_ns']<samples[1]['wall_ns']<result['end_wall_ns']:raise ValueError('actual blocked RX after real full-pool observation required')
    if result['stage']!='blocked_denied' or result['errno']!=errno.ETIMEDOUT:raise ValueError('original timeout, not EAGAIN/revoke/Down/EOF required')
    lower=result['end_monotonic_ns']-armed['admission_after_monotonic_ns'];upper=result['end_monotonic_ns']-armed['admission_before_monotonic_ns']
    if not 4_900_000_000<=lower<=upper<=5_500_000_000 or result['start_monotonic_ns']<armed['admission_after_monotonic_ns']:raise ValueError('finite original5s admission deadline required, not 8s recv timeout or refreshed retry deadline')
    for key in ['old_fd_before_release','old_fd_after_release']:
        if d[key]['errors']!={'send':errno.ENOTCONN,'recv':errno.ENOTCONN} or d[key]['poll']!=select.POLLERR|select.POLLHUP:raise ValueError('failed Session must reject old fd before and after real delayed reply')
    if len(d['acks'])!=3 or len(d['markers'])!=3 or len(d['ack_receipts'])!=3 or [v['stage'] for v in d['acks']]!=['armed','held','released']:raise ValueError('real hold/release handshake required')
    for j,a in enumerate(d['acks']):
        expected=dict(zip(PROPERTIES,[[True,False,0,0,0,0,False,0],[False,True,1,0,0,0,False,0],[False,False,1,1,0,0,False,0]][j]))
        receipt=d['ack_receipts'][j]
        if a['request']!=d['markers'][j] or a['state']!=expected or receipt['stage']!=a['stage'] or receipt['wall_ns']<a['request']['wall_ns']:raise ValueError('exact real hold states and guest receipts, no bounded release/drop/error required')
    # Host and guest wall clocks have independent offsets. Use the guest's
    # actual ack-file receipt to connect causal stages; never compare clocks.
    receipts=d['ack_receipts']
    held_order=(receipts[1]['wall_ns']<armed['admission_before_wall_ns'] if d.get('primed',False)
                else armed['admission_after_wall_ns']<d['markers'][1]['wall_ns']<=receipts[1]['wall_ns'])
    if not (receipts[0]['wall_ns']<=armed['admission_before_wall_ns']<=armed['admission_after_wall_ns']<result['end_wall_ns']<=d['timeout_observed_wall_ns']<d['markers'][2]['wall_ns']<=receipts[2]['wall_ns']<d['post_release_checked_wall_ns']<d['cleanup_before_wall_ns'] and held_order and receipts[1]['wall_ns']<result['end_wall_ns']) or not receipts[0]['monotonic_ns']<receipts[1]['monotonic_ns']<receipts[2]['monotonic_ns']:raise ValueError('guest receipts must show original timeout while real reply held')
    if not d['acks'][0]['host_wall_ns']<d['acks'][1]['host_wall_ns']<d['acks'][2]['host_wall_ns']:raise ValueError('host observations must be ordered on their own clock')
    request=decode(SleConnectionSubmit,d['cleanup_disconnect_input']);link=decode(SleLinkSnapshot,d['links_at_timeout'][i]).links[0]
    if (request.version,request.operation,request.generation,request.request_id,request.handle,request.reason,request.expected_lifetime)!=(2,2,owner['generation'],950,owner['handle'],0x13,owner['lifetime']) or bytes(request.expected_address)!=bytes(link.address) or request.expected_role!=link.role or request.expected_address_type!=link.address_type:raise ValueError('exact lifetime-bound cleanup input required')
    cleanup=decode(SleConnectionResult,d['cleanup_result'])
    if (cleanup.state,cleanup.operation,cleanup.generation,cleanup.request_id,cleanup.handle,cleanup.flags)!=(4,2,owner['generation'],950,owner['handle'],7) or any([cleanup.error,cleanup.fault_error,cleanup.command_status,cleanup.outcome_status]):raise ValueError('actual terminal cleanup Disconnect required')
    if len(d['down'])!=2 or any(v['event'] not in [5,0x1405] for v in d['down']):raise ValueError('two actual cleanup Down events required')
    if len(g['business'])!=2:raise ValueError('two actual pre-hold business round trips required')
    for b in g['business']:
        payload=bytes.fromhex(b['payload'])
        for n,app in enumerate(b['applications']):validate(bytes.fromhex(app['sent']),payload,n!=b['initiator']);validate(bytes.fromhex(app['received']),payload,n==b['initiator'])
    return d


def corroborate(r,capture,hold,stderr,expected):
    d=verify(r);g=r['channel_grant'];i=r['index'];owner=g['owners'][i]
    from ws73_channel_prefix_hold import geometry,corroborate_geometry,corroborate_priming
    plan=geometry(r,'data_deadline')
    if not hold or not hold.get('complete') or hold.get('hold_budget_ms')!=8000 or hold['observations']!=d['acks'] or hold['index']!=i:raise CaptureError('sealed real bounded8s coordinator required')
    sdus,legs=business_evidence(g,r,capture);same=lambda v,n:(v['bus'],v['device'])==(r['usb'][n]['bus'],r['usb'][n]['device'])
    start=g['revoke_prefix']['admission_before_wall_ns'];end=d['cleanup_before_wall_ns'];payload=bytes.fromhex(g['revoke_prefix']['payload']);wire=b'\x1f\0\xfb\x07\xf1'+payload
    if len(payload)!=2042 or payload[:8]!=b'SLKREV01' or g['armed']['prefix']!=payload.hex():raise CaptureError('original random admitted2042byte PDU required')
    packets=[v for v in capture['acb_packets'] if same(v,i) and v['direction']=='out' and v['handle']==owner['handle'] and start<=v['wall_ns']<=end];data=b''
    for n,p in enumerate(packets):
        if p['boundary']!=(1 if n==0 else 2) or not p.get('completion') or p['wall_ns']>=g['armed']['pre_block_tx_status_wall_ns'] or len(bytes.fromhex(p['data']))!=plan['packet_maximum']:raise CaptureError('only original prefix before full-pool snapshot may submit, never after timeout/release')
        data+=bytes.fromhex(p['data'])
    if len(packets)!=plan['fragments'] or len(data)!=plan['offset'] or not wire.startswith(data):raise CaptureError('exact actual original incomplete prefix required')
    if d.get('primed',False):corroborate_priming(r,capture,'data_deadline')
    nocp=[v for v in capture['native_events'] if same(v,i) and v['event']==9 and start<=v['wall_ns']<=end]
    if not nocp or any(v['wall_ns']<=d['markers'][2]['wall_ns'] for v in nocp):raise CaptureError('NOCP must be withheld until explicit post-timeout real reply release')
    counts=[]
    for e in nocp:
        body=bytes.fromhex(e['params'])
        if len(body)!=3 or int.from_bytes(body[:2],'little')!=owner['handle'] or not body[2]:raise CaptureError('exact original handle nonzero NOCP required')
        counts.append(body[2])
    if sum(counts)!=plan['capacity']:raise CaptureError('exact full-pool delayed controller completions required, not an assumed refund')
    from ws73_diagnostic_hold import corroborate_host_hold
    hold_proof=corroborate_host_hold(hold,dict(records=d['markers'],host_hold_acknowledgements=d['acks']),[],stderr,expected,held_reply=nocp[0],expected_method='BOUNDED8S_HOLD_REAL_IN81_FOR_ORIGINAL5S_PDU_DEADLINE')
    for n,e in enumerate(d['down']):
        matches=[v for v in capture['native_events'] if same(v,n) and v['event']==e['event'] and v['params']==e['params'] and d['cleanup_before_wall_ns']<=v['wall_ns']<=d['cleanup_after_wall_ns']]
        body=bytes.fromhex(e['params'])
        if len(matches)!=1 or e['generation']!=g['owners'][n]['generation'] or e['lost'] or len(body)!=4 or body[0] or int.from_bytes(body[1:3],'little')!=g['owners'][n]['handle']:raise CaptureError('both real physical cleanup Down events required')
    control(capture,r['usb'][i],0x1403,owner['handle'].to_bytes(2,'little')+b'\x13',d['cleanup_before_wall_ns'],d['cleanup_after_wall_ns'],status=True)
    for enabled in [True,False]:control(capture,r['usb'][1-i],0x1002,bytes([enabled,0]),d['cleanup_after_wall_ns'],d['scan_checked_wall_ns'])
    if any(d['old_fd_after_release']['marker'] in p['data'] for p in sdus):raise CaptureError('failed oldfd marker reached USB')
    return dict(status='REAL_ORIGINAL5S_BEGUN_DEADLINE_CORROBORATED',submitted_fragments=plan['fragments'],submitted_bytes=plan['offset'],prefix_geometry=corroborate_geometry(r,capture,'data_deadline'),business_round_trips_before_hold=2,partial_pdu_application_round_trips=0,elapsed_monotonic_ns=d['blocked_result']['end_monotonic_ns']-g['armed']['admission_after_monotonic_ns'],actual_full_pool_snapshot=g['armed']['pre_block_tx_status'],delayed_nocp_records=[v['record'] for v in nocp],business_legs=legs,host_hold=hold_proof,scope='Bounded delay of real successful USB IN, not natural recovery, full debt/reuse proof or another independent peer business link')


def control(capture,usb,opcode,params,start,end,*,status=False):
    same=lambda v:(v['bus'],v['device'])==(usb['bus'],usb['device'])
    commands=[v for v in capture['commands'] if same(v) and v['opcode']==opcode and v['params']==params.hex() and start<=v['wall_ns']<=end]
    if len(commands)!=1 or not commands[0].get('completion'):raise CaptureError('one exact real control USB command required')
    command=commands[0];upper=min([v['wall_ns']-1 for v in capture['commands'] if same(v) and v['wall_ns']>command['wall_ns']]+[end])
    if status:
        replies=[v for v in capture['native_events'] if same(v) and v['event']==1 and bytes.fromhex(v['params'])[:2]==opcode.to_bytes(2,'little') and command['wall_ns']<=v['wall_ns']<=upper]
        if len(replies)!=1 or bytes.fromhex(replies[0]['params'])[3:]!=b'\0':raise CaptureError('one actual successful Status required')
    else:
        replies=[v for v in capture['complete'] if same(v) and v['opcode']==opcode and command['wall_ns']<=v['wall_ns']<=upper]
        if len(replies)!=1 or replies[0]['status']!=0:raise CaptureError('one actual successful Complete required')
    return dict(command=command,reply=replies[0])
