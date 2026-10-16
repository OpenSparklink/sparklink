# SPDX-License-Identifier: GPL-2.0-only
"""Real partial-PDU physical Disconnect, with both Managed leases still held.

Reuse the established File gate and ordinary Grant workers. Never synthesize
events or call this a Managed withdrawal, deadline, reuse or recovery proof.
"""
import errno
import secrets
import select
import time

from ws73_channel_grant import send, receive, validate, business_evidence, Address
from ws73_capture import CaptureError
from ws73_management_setup import decode, setup, query
from sparklink.structs import SleConnectionSubmit, SleConnectionResult, SleLinkSnapshot, SleControllerSnapshot


def exercise(r, save, grant, observers, writers, snapshots, leases, discover, outcomes, standby, stop, bound_disconnect):
    i=r['index'];p=1-i
    row=dict(status='STARTING',management_before=[bytes(a.management_status()).hex() for a in observers],
             links_before=[bytes(a.link_snapshot()).hex() for a in observers],
             ready_before=[bytes(a.snapshot()).hex() for a in observers])
    r['data_link_down']=row;save()
    # Historical helper field revoke_prefix describes admission only here.
    # The explicit Disconnect below does NOT revoke either Managed epoch.
    from ws73_channel_prefix_hold import PrefixBarrier
    barrier=PrefixBarrier(r,save);barrier.arm(grant)
    link=decode(SleLinkSnapshot,row['links_before'][i]).links[0]
    request=bound_disconnect(snapshots[i],link,950)
    row.update(input=bytes(request).hex(),submit_before_wall_ns=time.time_ns());save()
    writers[i].submit_connection(request);row['submit_after_wall_ns']=time.time_ns();save()
    barrier.release()
    row['down']=outcomes('down',[5,0x1405])
    deadline=time.monotonic()+2
    while True:
        result=writers[i].connection_result(snapshots[i].generation,950)
        if result is not None and result.state>=4:break
        if time.monotonic()>deadline:raise ValueError('actual Disconnect terminal result required')
        time.sleep(.002)
    row['result']=bytes(result).hex();row['blocked_result']=receive(grant.parents[i])
    marker=b'DOWNDENY'+secrets.token_bytes(32)
    send(grant.parents[i],dict(kind='deny',marker=marker.hex()))
    row['old_fd']=receive(grant.parents[i]);row['checks_after_wall_ns']=time.time_ns()
    row['links_after']=[bytes(a.link_snapshot()).hex() for a in observers]
    row['management_after']=[bytes(a.management_status()).hex() for a in observers]
    row['ready_after']=[bytes(a.snapshot()).hex() for a in observers];save()
    # Physical link loss affects its peer, but cannot remove the peer's lease
    # or its independent controller-level scan capability.
    for identifier,operation in [(104,2),(105,3),(106,4)]:
        req=standby(snapshots[p],identifier,'scanning') if operation==3 else stop(snapshots[p],identifier,operation)
        req.operation=operation;discover(p,req)
    row['scan_checked_wall_ns']=time.time_ns()
    for n in [i,p]:writers[n].release_management(leases[n],1)
    row['management_cleaned']=[bytes(a.management_status()).hex() for a in observers]
    row.update(status='ACTUAL_LINK_DOWN_PASS',end_wall_ns=time.time_ns())
    r.update(status='DATA_LINK_DOWN_PASS',end_wall_ns=row['end_wall_ns']);verify(r);save()
    print('WS73_TARGET_DATA_LINK_DOWN_PASS',flush=True)


def verify(r):
    if r.get('status')!='DATA_LINK_DOWN_PASS' or r.get('case')!='release' or r.get('index') not in [0,1] or r.get('daemon_running') is not False or r.get('synthetic_support') is not False:
        raise ValueError('explicit pre-daemon real direct-Down gate required')
    row=r['data_link_down'];g=r['channel_grant'];i=r['index']
    snapshots=[setup(raw,n) for n,raw in enumerate(r['initial_snapshots'])]
    if len(snapshots)!=2 or row['status']!='ACTUAL_LINK_DOWN_PASS' or len(row['down'])!=2 or any(e['event'] not in [5,0x1405] for e in row['down']):raise ValueError('two original controllers and physical Down events required')
    for n in [0,1]:
        for key in ['management_before','management_after']:query(row[key][n],snapshots[n].generation,1)
        if row['management_after'][n]!=row['management_before'][n]:raise ValueError('Disconnect must retain both original Managed leases')
        query(row['management_cleaned'][n],snapshots[n].generation,0)
        before=decode(SleLinkSnapshot,row['links_before'][n]);after=decode(SleLinkSnapshot,row['links_after'][n])
        if before.flags!=1 or before.count!=1 or after.flags!=1 or after.count or before.generation!=snapshots[n].generation or after.generation!=before.generation:
            raise ValueError('original known physical lifetime must disappear on both ends')
        owner=g['owners'][n];address=Address.from_buffer_copy(bytes.fromhex(owner['address']))
        if (owner['generation'],owner['lifetime'],owner['handle'],owner['lease'])!=(before.generation,before.links[0].lifetime,before.links[0].handle,r['leases'][n]):raise ValueError('exact original binding lifetime/lease required')
        if (address.generation,address.lifetime,address.lease,address.handle,address.directions,address.security)!=(owner['generation'],owner['lifetime'],owner['lease'],owner['handle'],3,0):raise ValueError('original bidirectional unprotected binding required')
        if (address.family,address.controller,address.version,address.flags,address.local_tcid,address.remote_tcid,address.pi)!=(46,n,2,0,31,31,241) or any(address.reserved):raise ValueError('exact original unpublished channel address required')
        worker=g['workers'][n]
        if worker['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in worker['credentials']['caps'].values()) or worker['original_errno']!=errno.EBADF:raise ValueError('actual ordinary duplicate fd required')
        for key in ['ready_before','ready_after']:
            ready=decode(SleControllerSnapshot,row[key][n])
            if ready.flags!=1 or ready.generation!=snapshots[n].generation:raise ValueError('same registered Ready controller required')
    request=decode(SleConnectionSubmit,row['input']);old=decode(SleLinkSnapshot,row['links_before'][i]).links[0]
    if (request.version,request.operation,request.generation,request.request_id,request.handle,request.reason,request.expected_lifetime)!=(2,2,snapshots[i].generation,950,old.handle,0x13,old.lifetime) or bytes(request.expected_address)!=bytes(old.address) or request.expected_role!=old.role or request.expected_address_type!=old.address_type:raise ValueError('exact bound Disconnect input required')
    result=decode(SleConnectionResult,row['result'])
    if (result.version,result.profile,result.state,result.operation,result.generation,result.request_id,result.handle,result.flags,result.dev_index)!=(1,1,4,2,snapshots[i].generation,950,old.handle,7,i) or any([result.error,result.fault_error,result.command_status,result.outcome_status,*result.reserved]):raise ValueError('actual successful Disconnect result required')
    armed=g['armed'];witness=g['blocking_witness'];blocked=row['blocked_result']
    if armed['pid']!=g['workers'][i]['pid'] or armed['fd']!=g['workers'][i]['fd'] or len(witness)!=2 or any(v['syscall']!=45 or v['fd']!=armed['fd'] or v['state']!='S' or v['wchan'] not in ['__skb_wait_for_more_packets','schedule_timeout'] for v in witness) or not armed['wall_ns']<witness[0]['wall_ns']<witness[1]['wall_ns']<row['submit_before_wall_ns']<=row['submit_after_wall_ns']:
        raise ValueError('actual blocked syscall must precede Disconnect')
    # Runtime lifetime validation returns ESTALE; a waiter may observe the
    # Session stop's ENOTCONN first. This race does not permit an old send.
    if blocked['stage']!='blocked_denied' or blocked['errno'] not in [errno.ESTALE,errno.ENOTCONN] or not row['submit_before_wall_ns']<=blocked['end_wall_ns']<=row['checks_after_wall_ns'] or blocked['end_wall_ns']-blocked['start_wall_ns']>=8_000_000_000:
        raise ValueError('finite physical-Down blocked RX error required')
    if row['old_fd']['errors']!={'send':errno.ESTALE,'recv':errno.ESTALE} or row['old_fd']['poll']!=select.POLLERR|select.POLLHUP:raise ValueError('old lifetime must stay stale with ERR/HUP while leases held')
    if len(g['business'])!=2:raise ValueError('two actual pre-Down round trips required')
    for b in g['business']:
        payload=bytes.fromhex(b['payload'])
        for n,app in enumerate(b['applications']):
            validate(bytes.fromhex(app['sent']),payload,n!=b['initiator']);validate(bytes.fromhex(app['received']),payload,n==b['initiator'])
    return row


def corroborate(r,capture):
    row=verify(r);g=r['channel_grant'];i=r['index'];sdus,legs=business_evidence(g,r,capture)
    owner=g['owners'][i];same=lambda v,n: (v['bus'],v['device'])==(r['usb'][n]['bus'],r['usb'][n]['device'])
    commands=[c for c in capture['commands'] if same(c,i) and c['opcode']==0x1403 and row['submit_before_wall_ns']<=c['wall_ns']<=row['checks_after_wall_ns']]
    if len(commands)!=1 or commands[0]['params']!=(owner['handle'].to_bytes(2,'little')+b'\x13').hex() or not commands[0].get('completion'):raise CaptureError('one actual exact Disconnect USB submission required')
    statuses=[e for e in capture['native_events'] if same(e,i) and e['event']==1 and bytes.fromhex(e['params'])[:2]==b'\x03\x14' and commands[0]['wall_ns']<=e['wall_ns']<=row['checks_after_wall_ns']]
    if len(statuses)!=1 or bytes.fromhex(statuses[0]['params'])[3:]!=b'\0':raise CaptureError('one actual successful Disconnect Status required')
    for n,event in enumerate(row['down']):
        matches=[e for e in capture['native_events'] if same(e,n) and e['event']==event['event'] and e['params']==event['params'] and row['submit_before_wall_ns']<=e['wall_ns']<=row['checks_after_wall_ns']]
        body=bytes.fromhex(event['params'])
        if len(matches)!=1 or not matches[0]['wall_ns']<=event['wall_ns']<=row['checks_after_wall_ns'] or event['generation']!=g['owners'][n]['generation'] or event['lost'] or len(body)!=4 or body[0] or int.from_bytes(body[1:3],'little')!=g['owners'][n]['handle']:raise CaptureError('both actual physical Down events required')
    payload=bytes.fromhex(g['revoke_prefix']['payload']);expected=b'\x1f\0\xfb\x07\xf1'+payload
    if len(payload)!=2042 or payload[:8]!=b'SLKREV01' or g['armed'].get('prefix')!=payload.hex():raise CaptureError('original admitted random2042-byte payload required')
    packets=[p for p in capture['acb_packets'] if same(p,i) and p['direction']=='out' and p['handle']==owner['handle'] and g['revoke_prefix']['admission_before_wall_ns']<=p['wall_ns']<=r['end_wall_ns']]
    data=b''
    for n,p in enumerate(packets):
        if p.get('boundary')!=(1 if n==0 else 2) or not p.get('completion') or p['wall_ns']>=row['down'][i]['wall_ns']:raise CaptureError('only an incomplete prefix before observed Down may submit')
        data+=bytes.fromhex(p['data'])
    if not packets or not expected.startswith(data) or not 0<len(data)<len(expected):raise CaptureError('actual original incomplete PDU prefix required')
    if any(row['old_fd']['marker'] in p['data'] for p in sdus):raise CaptureError('stale fd canary reached USB')
    # Scan control after Down: actual successful START/OFF, not a local flag.
    for enabled in [True,False]:
        params=bytes([enabled,0]).hex();n=1-i
        sent=[c for c in capture['commands'] if same(c,n) and c['opcode']==0x1002 and c['params']==params and row['checks_after_wall_ns']<=c['wall_ns']<=row['scan_checked_wall_ns']]
        if len(sent)!=1 or not sent[0].get('completion'):raise CaptureError('actual peer scan on/off required')
        upper=min([c['wall_ns']-1 for c in capture['commands'] if same(c,n) and c['wall_ns']>sent[0]['wall_ns']]+[row['scan_checked_wall_ns']])
        replies=[v for v in capture['complete'] if same(v,n) and v['opcode']==0x1002 and sent[0]['wall_ns']<=v['wall_ns']<=upper]
        if len(replies)!=1 or replies[0]['status']!=0:raise CaptureError('one actual peer successful scan Complete before next command required')
    return dict(status='REAL_BEGUN_LINK_DOWN_CORROBORATED',submitted_fragments=len(packets),submitted_bytes=len(data),
                business_round_trips_before_down=2,partial_pdu_application_round_trips=0,business_legs=legs,
                actual_disconnect=commands[0],actual_down=row['down'],both_leases_preserved=True,
                original_deadline_qualified=False,handle_reuse_qualified=False,natural_recovery_qualified=False,
                scope='Direct physical Disconnect while leases held; source old lifetime rejection and peer Ready/scan, not another independent business link or exact timestamp of kernel submit barrier')
