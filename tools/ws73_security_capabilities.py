# SPDX-License-Identifier: GPL-2.0-only
"""Real bounded capability/candidate agreement via the sole physical Session.

No raw packets, protocol engine, key material, trusted result or injected RX.
This probe is not approved pairing, encryption or a peer application ACK.
"""
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import time
from ws73_channel_grant import credentials,business_evidence,validate
from ws73_management_setup import setup,decode,query
from ws73_capture import CaptureError
from sparklink.structs import SleSecurityNegotiationSubmit as Submit,SleSecurityNegotiationResult as Result,SleLinkSnapshot,SleControllerSnapshot,SleConnectionResult

OFFER=bytes([3,0,0,16,0,2,2,2,2,0])
SUBMIT=(1<<30)|(ctypes.sizeof(Submit)<<16)|(ord('S')<<8)|0xd2
RESULT=(3<<30)|(ctypes.sizeof(Result)<<16)|(ord('S')<<8)|0xd3


def request(snapshot,link,agreement=False):
    value=Submit(version=1,profile=1,flags=2 if agreement else 1,action=2 if link.role==0 else 1,timeout_ms=5000,generation=snapshot.generation,lifetime=link.lifetime,request_id=1,handle=link.handle,role=link.role,address_type=link.address_type)
    value.address[:]=link.address;return value


def denied(fd,command,value):
    try:fcntl.ioctl(fd,command,bytearray(bytes(value)),True)
    except OSError as e:return e.errno
    raise ValueError('unauthorized/invalid limited security request succeeded')


def ordinary_denial(writer,req):
    rd,wr=os.pipe2(os.O_CLOEXEC);pid=os.fork()
    if pid==0:
        try:
            keep={0,1,2,wr,writer.fileno()}
            for name in os.listdir('/proc/self/fd'):
                if int(name) not in keep:
                    try:os.close(int(name))
                    except OSError as e:
                        if e.errno!=errno.EBADF:raise
            os.setgroups([]);os.setgid(1002);os.setuid(1000)
            out=dict(credentials=credentials(),submit_errno=denied(writer.fileno(),SUBMIT,req),result_errno=denied(writer.fileno(),RESULT,Result(version=1,generation=req.generation,lifetime=req.lifetime,handle=req.handle,request_id=1)))
            os.write(wr,json.dumps(out).encode());os._exit(0)
        except BaseException:os._exit(1)
    os.close(wr);reaped=False
    try:
        if not select.select([rd],[],[],2)[0]:os.kill(pid,signal.SIGKILL);raise TimeoutError('ordinary inherited Managed fd denial')
        data=os.read(rd,8192);_,status=os.waitpid(pid,0);reaped=True
        if status!=0:raise ValueError('ordinary denial child failed')
        return json.loads(data)
    finally:
        os.close(rd)
        if not reaped:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            os.waitpid(pid,0)


def exercise(r,save,grant,observers,writers,snapshots,leases,outcomes,bound_disconnect,discover,standby,stop):
    i=r['index'];p=1-i
    row=dict(status='STARTING',before_links=[bytes(a.link_snapshot()).hex() for a in observers],before_ready=[bytes(a.snapshot()).hex() for a in observers],management_before=[bytes(a.management_status()).hex() for a in observers],negative=[],start_wall_ns=time.time_ns())
    r['security_capabilities']=row;save();links=[decode(SleLinkSnapshot,v).links[0] for v in row['before_links']]
    if links[i].role!=0 or links[p].role!=1:raise ValueError('actual G Create and T response roles required')
    agreement=r.get('key_agreement',False);wanted=8 if agreement else 4
    requests=[request(s,l,agreement) for s,l in zip(snapshots,links)]
    row['requests']=[bytes(v).hex() for v in requests];row['ordinary_denial']=ordinary_denial(writers[i],requests[i]);save()
    for n in [i,p]:
        good=requests[n]
        for kind,want in [('generation',errno.ENODEV),('lifetime',errno.ESTALE),('address',errno.ESTALE),('role',errno.ESTALE),('profile',errno.EOPNOTSUPP),('flags',errno.EINVAL),('reserved',errno.EINVAL)]:
            bad=Submit.from_buffer_copy(bytes(good))
            if kind=='generation':bad.generation+=1
            elif kind=='lifetime':bad.lifetime+=1
            elif kind=='address':bad.address[5]^=1
            elif kind=='role':bad.role^=1;bad.action=2 if bad.role==0 else 1
            elif kind=='profile':bad.profile=0
            elif kind=='flags':bad.flags=0
            else:bad.reserved[0]=1
            actual=denied(writers[n].fileno(),SUBMIT,bad)
            row['negative'].append(dict(index=n,kind=kind,input=bytes(bad).hex(),errno=actual));save()
            if actual!=want:raise ValueError('exact kernel limited-security negative errno '+kind)
        for command,value in [(SUBMIT,good),(RESULT,Result(version=1,generation=good.generation,lifetime=good.lifetime,handle=good.handle,request_id=1))]:
            actual=denied(observers[n].fileno(),command,value);row['negative'].append(dict(index=n,kind='nonowner_submit' if command==SUBMIT else 'nonowner_result',errno=actual));save()
            if actual!=errno.EPERM:raise ValueError('same-controller admin observer is not the Managed author')
    row['t_arm_before_wall_ns']=time.time_ns();row['t_arm_before_monotonic_ns']=time.monotonic_ns();writers[p].submit_security_negotiation(requests[p]);row['t_armed']=bytes(writers[p].security_negotiation(links[p].lifetime,links[p].handle,1)).hex();save()
    row['g_start_before_wall_ns']=time.time_ns();writers[i].submit_security_negotiation(requests[i]);deadline=time.monotonic()+5
    while True:
        values=[a.security_negotiation(l.lifetime,l.handle,1) for a,l in zip(writers,links)]
        row['results']=[bytes(v).hex() for v in values];save()
        if all(v.state==wanted for v in values):break
        if any(v.state in [5,6,7] for v in values) or time.monotonic()>deadline:raise ValueError('actual limited security negotiation did not finish: '+str([(v.state,v.error,v.flags) for v in values]))
        time.sleep(.005)
    row['observed_wall_ns']=time.time_ns();row['observed_monotonic_ns']=time.monotonic_ns()
    for n in [i,p]:
        again=Submit.from_buffer_copy(bytes(requests[n]));again.request_id=2
        row['negative'].append(dict(index=n,kind='same_lifetime_restart',errno=denied(writers[n].fileno(),SUBMIT,again)))
        if row['negative'][-1]['errno']!=errno.EBUSY:raise ValueError('same-life security restart lacks a proven barrier')
    grant.exchange('after_capabilities');row['after_links']=[bytes(a.link_snapshot()).hex() for a in observers];row['after_ready']=[bytes(a.snapshot()).hex() for a in observers];row['management_after']=[bytes(a.management_status()).hex() for a in observers];save()
    cleanup=bound_disconnect(snapshots[i],links[i],950);row['cleanup_input']=bytes(cleanup).hex();row['cleanup_before_wall_ns']=time.time_ns();writers[i].submit_connection(cleanup);row['down']=outcomes('down',[5,0x1405]);row['cleanup_after_wall_ns']=time.time_ns()
    deadline=time.monotonic()+2
    while True:
        result=writers[i].connection_result(snapshots[i].generation,950)
        if result is not None and result.state>=4:break
        if time.monotonic()>deadline:raise TimeoutError('real terminal capability probe cleanup')
        time.sleep(.002)
    row['cleanup_result']=bytes(result).hex()
    for identifier,op in [(104,2),(105,3),(106,4)]:
        req=standby(snapshots[p],identifier,'scanning') if op==3 else stop(snapshots[p],identifier,op);req.operation=op;discover(p,req)
    row['scan_checked_wall_ns']=time.time_ns()
    for n in [i,p]:writers[n].release_management(leases[n],1)
    row['management_cleaned']=[bytes(a.management_status()).hex() for a in observers];row['end_wall_ns']=time.time_ns();row['status']='REAL_LIMITED_CAPABILITIES_PASS';r.update(status='SECURITY_CAPABILITIES_PASS',end_wall_ns=row['end_wall_ns']);verify(r);save();print('WS73_TARGET_SECURITY_CAPABILITIES_PASS',flush=True)


def verify(r):
    if r.get('format_version')!=1 or r.get('status')!='SECURITY_CAPABILITIES_PASS' or r.get('case')!='release' or r.get('index') not in [0,1] or r.get('daemon_running') is not False or r.get('synthetic_support') is not False:raise ValueError('separate real limited capability gate required')
    row=r['security_capabilities'];i=r['index'];g=r['channel_grant'];agreement=r.get('key_agreement',False);snapshots=[setup(v,n) for n,v in enumerate(r['initial_snapshots'])]
    if row['status']!='REAL_LIMITED_CAPABILITIES_PASS' or len(snapshots)!=2:raise ValueError('two actual controllers required')
    for n in [0,1]:
        before=decode(SleLinkSnapshot,row['before_links'][n]);after=decode(SleLinkSnapshot,row['after_links'][n])
        if before.flags!=1 or before.count!=1 or bytes(before)!=bytes(after) or before.generation!=snapshots[n].generation:raise ValueError('same physical lifetime must survive limited exchange')
        link=before.links[0];req=decode(Submit,row['requests'][n]);owner=g['owners'][n]
        if (req.version,req.profile,req.flags,req.timeout_ms,req.request_id,req.generation,req.lifetime,req.handle,req.role,req.action,req.address_type)!=(1,1,2 if agreement else 1,5000,1,before.generation,link.lifetime,link.handle,0 if n==i else 1,2 if n==i else 1,link.address_type) or bytes(req.address)!=bytes(link.address) or any(req.reserved):raise ValueError('exact approved physical reference required')
        if (owner['generation'],owner['lifetime'],owner['handle'],owner['lease'])!=(req.generation,req.lifetime,req.handle,r['leases'][n]):raise ValueError('business must use same original Session/lease')
        result=decode(Result,row['results'][n])
        if (result.version,result.profile,result.generation,result.lifetime,result.handle,result.request_id,result.role,result.state,result.error,result.status,result.flags)!=(1,1,req.generation,req.lifetime,req.handle,1,req.role,8 if agreement else 4,0,0,7) or bytes(result.local_caps)!=OFFER or bytes(result.peer_caps)!=OFFER or any(result.reserved):raise ValueError('real local Complete and peer capability bytes required, never trusted state')
        for key in ['before_ready','after_ready']:
            ready=decode(SleControllerSnapshot,row[key][n])
            if ready.flags!=1 or ready.generation!=req.generation:raise ValueError('original registration Ready must remain')
        if row['management_before'][n]!=row['management_after'][n]:raise ValueError('limited exchange must retain original author')
        query(row['management_after'][n],req.generation,1);query(row['management_cleaned'][n],req.generation,0)
        expected={'generation':errno.ENODEV,'lifetime':errno.ESTALE,'address':errno.ESTALE,'role':errno.ESTALE,'profile':errno.EOPNOTSUPP,'flags':errno.EINVAL,'reserved':errno.EINVAL,'nonowner_submit':errno.EPERM,'nonowner_result':errno.EPERM,'same_lifetime_restart':errno.EBUSY}
        negatives=[v for v in row['negative'] if v['index']==n]
        if len(negatives)!=len(expected) or {v['kind']:v['errno'] for v in negatives}!=expected:raise ValueError('complete exact kernel authority/reference/restart denials required')
        worker=g['workers'][n]
        if worker['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in worker['credentials']['caps'].values()) or worker['original_errno']!=errno.EBADF:raise ValueError('ordinary business application required')
    armed=decode(Result,row['t_armed']);t_req=decode(Submit,row['requests'][1-i])
    if (armed.version,armed.profile,armed.generation,armed.lifetime,armed.handle,armed.request_id,armed.role,armed.state,armed.status,armed.flags,armed.error)!=(1,1,t_req.generation,t_req.lifetime,t_req.handle,1,1,1,0,0,0) or any(armed.peer_caps) or any(armed.reserved) or bytes(armed.local_caps)!=OFFER:raise ValueError('T approval alone cannot invent RX/TX/Complete')
    if not 0<row['observed_monotonic_ns']-row['t_arm_before_monotonic_ns']<5_000_000_000:raise ValueError('original limited deadline required')
    denial=row['ordinary_denial']
    if denial['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in denial['credentials']['caps'].values()) or (denial['submit_errno'],denial['result_errno'])!=(errno.EPERM,errno.EPERM):raise ValueError('ordinary inherited Managed fd must not approve or observe protected procedure')
    if [b['label'] for b in g['business']]!=['before','before','after_capabilities','after_capabilities']:raise ValueError('four real before/after business round trips required')
    for b in g['business']:
        for n,app in enumerate(b['applications']):
            validate(bytes.fromhex(app['sent']),bytes.fromhex(b['payload']),n!=b['initiator']);validate(bytes.fromhex(app['received']),bytes.fromhex(b['payload']),n==b['initiator'])
    if len(row['down'])!=2 or any(e['event'] not in [5,0x1405] for e in row['down']):raise ValueError('both actual cleanup Down events required')
    cleanup=decode(SleConnectionResult,row['cleanup_result']);owner=g['owners'][i]
    if (cleanup.version,cleanup.profile,cleanup.state,cleanup.operation,cleanup.generation,cleanup.request_id,cleanup.handle,cleanup.flags)!=(1,1,4,2,owner['generation'],950,owner['handle'],7) or any([cleanup.error,cleanup.fault_error,cleanup.command_status,cleanup.outcome_status,*cleanup.reserved]):raise ValueError('real successful physical cleanup required')
    return row


def corroborate(r,capture):
    if r.get('key_agreement',False):
        from ws73_key_agreement import corroborate as agreement_corroborate
        return agreement_corroborate(r,capture)
    row=verify(r);g=r['channel_grant'];i=r['index'];sdus,legs=business_evidence(g,r,capture);proof=[]
    for n in [0,1]:
        owner=g['owners'][n];same=lambda v:(v['bus'],v['device'])==(r['usb'][n]['bus'],r['usb'][n]['device']);tx_index=0x134 if n==i else 0x135;rx_index=0x135 if n==i else 0x134
        body=lambda index:owner['handle'].to_bytes(2,'little')+index.to_bytes(2,'little')+bytes([10])+OFFER
        commands=[v for v in capture['commands'] if same(v) and v['opcode']==0x1812 and row['start_wall_ns']<=v['wall_ns']<=row['cleanup_before_wall_ns']]
        if len(commands)!=1 or commands[0]['params']!=body(tx_index).hex() or not commands[0].get('completion') or commands[0]['wall_ns']<row['g_start_before_wall_ns']:raise CaptureError('one exact real approved relay USB submission per controller required')
        replies=[v for v in capture['complete'] if same(v) and v['opcode']==0x1812 and commands[0]['wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
        if len(replies)!=1 or replies[0]['status'] or replies[0]['value']!=(owner['handle'].to_bytes(2,'little')+tx_index.to_bytes(2,'little')).hex():raise CaptureError('actual current handle/index Complete required')
        incoming=[v for v in capture['native_events'] if same(v) and v['event']==0x14 and row['g_start_before_wall_ns']<=v['wall_ns']<=row['observed_wall_ns']]
        if len(incoming)!=1 or incoming[0]['params']!=body(rx_index).hex():raise CaptureError('opposite real received 0014 bytes required, local Complete insufficient')
        if any(v['event'] in [0x11,0xe] and same(v) and row['start_wall_ns']<=v['wall_ns']<=row['cleanup_before_wall_ns'] for v in capture['native_events']):raise CaptureError('limited exchange must not install/enable encryption')
        if any(v['opcode'] in [0x1c03,0x1c05] and same(v) and row['start_wall_ns']<=v['wall_ns']<=row['cleanup_before_wall_ns'] for v in capture['commands']):raise CaptureError('capability-only evidence must contain no key install command')
        proof.append(dict(command=commands[0],complete=replies[0],peer_rx=incoming[0]))
        event=row['down'][n];matches=[v for v in capture['native_events'] if same(v) and v['event']==event['event'] and v['params']==event['params'] and row['cleanup_before_wall_ns']<=v['wall_ns']<=row['cleanup_after_wall_ns']]
        raw=bytes.fromhex(event['params'])
        if len(matches)!=1 or event['generation']!=owner['generation'] or event['lost'] or len(raw)!=4 or raw[0] or int.from_bytes(raw[1:3],'little')!=owner['handle']:raise CaptureError('actual current-lifetime cleanup Down required')
    if not proof[i]['command']['wall_ns']<=proof[1-i]['peer_rx']['wall_ns']<=proof[1-i]['command']['wall_ns']<=proof[i]['peer_rx']['wall_ns']:raise CaptureError('actual134/135 cross-device causal order required')
    from ws73_channel_deadline import control
    control(capture,r['usb'][i],0x1403,g['owners'][i]['handle'].to_bytes(2,'little')+b'\x13',row['cleanup_before_wall_ns'],row['cleanup_after_wall_ns'],status=True)
    for enabled in [True,False]:control(capture,r['usb'][1-i],0x1002,bytes([enabled,0]),row['cleanup_after_wall_ns'],row['scan_checked_wall_ns'])
    return dict(status='REAL_APPROVED_LIMITED134_135_CORROBORATED',controllers=proof,business_legs=legs,business_round_trips=4,scope='Explicit admin capability-only approval, actual stock transport/peer RX and same-Session ordinary before/after business; NOT Agent/pairing/authentication/key install/encryption/Bond/standard interoperability or natural recovery')
