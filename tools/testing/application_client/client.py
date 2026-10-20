# SPDX-License-Identifier: GPL-2.0-only
"""One-shot external consumer of the public application SDK, no Host/codec."""
import errno
import json
import os
import select
import socket
import struct
import sys
import time
from sparklink import Client, ControllerId, channel_info, channel_recv_security


def wait(fd, event, deadline):
    poll=select.poll();poll.register(fd,event)
    while True:
        left=deadline-time.monotonic_ns()
        if left<=0:raise TimeoutError(errno.ETIMEDOUT,"original application deadline")
        ready=poll.poll((left+999999)//1000000)
        if not ready:raise TimeoutError(errno.ETIMEDOUT,"original application deadline")
        if ready[0][1]&(select.POLLHUP|select.POLLERR|select.POLLNVAL):raise ConnectionError("channel terminal")
        if ready[0][1]&event:return


def main():
    if sys.argv[1:2]==['subscription']:return subscription_mode()
    if sys.argv[1:2] in (['owned'],['owned-readonly'],['owned-updates']):return owned_mode()
    if sys.argv[1:2] in (['update-peer'],['update-error'],['update-retired']):return update_peer_mode()
    if sys.argv[1:2] == ['discovery']:return discovery_mode()
    if sys.argv[1:2] in (['ssap'], ['ssap-error']):return ssap_mode()
    if len(sys.argv)!=7:raise ValueError("index generation connection role request reply required")
    index,generation=int(sys.argv[1]),int(sys.argv[2]);path=sys.argv[3];role=int(sys.argv[4])
    request,reply=bytes.fromhex(sys.argv[5]),bytes.fromhex(sys.argv[6])
    if role not in (0,1) or not 1<=len(request)<=2042 or len(reply)!=len(request) or request==reply:raise ValueError("bounded independent request/reply required")
    identity=ControllerId(index,generation);deadline=time.monotonic_ns()+5_000_000_000
    with Client(deadline_ns=deadline) as client:
        if client.controllers(deadline_ns=deadline).count(identity)!=1:raise ValueError("selected registration missing")
        original=client.open_channel(identity,path,deadline_ns=deadline)
        try:data=original.dup()
        finally:original.close()
    # Client is now closed; only this duplicate holds the channel binding.
    with data:
        data.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack("ii",1,2))
        while True:
            try:info=channel_info(data.fileno());break
            except OSError as exc:
                if exc.errno!=errno.EAGAIN:raise
                wait(data.fileno(),select.POLLOUT,deadline)
        if (info.controller,info.generation,info.directions,info.local_tcid,info.remote_tcid,info.pi,info.mode)!=(index,generation,3,31,31,241,0) or info.mtu<len(request):raise ValueError("actual channel identity/mode/size")
        print(json.dumps(dict(stage="ready",api="python",index=index,generation=generation,lifetime=info.lifetime,handle=info.handle,dup_alive=True,client_closed=True)),flush=True)
        wait(0,select.POLLIN,deadline)
        if os.read(0,6)!=b"start\n":raise ValueError("explicit original start barrier required")
        outgoing,expected=(reply,request) if role else (request,reply)
        if not role:
            wait(data.fileno(),select.POLLOUT,deadline)
            if data.send(outgoing,socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL)!=len(outgoing):raise ValueError("incomplete admission")
        wait(data.fileno(),select.POLLIN,deadline)
        actual,receipt,flags,count=channel_recv_security(data.fileno(),2042,socket.MSG_DONTWAIT)
        if actual!=expected or count!=len(expected) or flags&(socket.MSG_TRUNC|socket.MSG_CTRUNC):raise ValueError("peer application payload mismatch")
        if (receipt.controller,receipt.generation,receipt.lifetime,receipt.handle,receipt.local_tcid,receipt.remote_tcid,receipt.pi)!=(info.controller,info.generation,info.lifetime,info.handle,31,31,241):raise ValueError("actual RX lifetime differs from delegated fd")
        if role:
            wait(data.fileno(),select.POLLOUT,deadline)
            if data.send(outgoing,socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL)!=len(outgoing):raise ValueError("incomplete admission")
    with Client(deadline_ns=deadline) as client:
        try:unexpected=client.open_channel(identity,path,deadline_ns=deadline)
        except OSError as exc:
            if exc.errno!=errno.EOPNOTSUPP:raise
        else:unexpected.close();raise AssertionError("same-lifetime rebind without protocol barrier")
    print(json.dumps(dict(stage="complete",api="python",sent=outgoing.hex(),received=actual.hex(),last_close_rebind="NotSupported")),flush=True)


def ssap_mode():
    if len(sys.argv) not in (8,9):raise ValueError('ssap index generation path operation handle expected [value]')
    index,generation=int(sys.argv[2]),int(sys.argv[3]);path,operation=sys.argv[4:6];handle=int(sys.argv[6])
    writing=operation=='ssap-write'
    if operation not in ('ssap-read','ssap-write') or len(sys.argv)!=(9 if writing else 8):raise ValueError('one exact read/short write required')
    error_mode=sys.argv[1]=='ssap-error'
    if not 1<=len(sys.argv[7])<=4084 or writing and not 1<=len(sys.argv[8])<=4084:raise ValueError('bounded test value required')
    expected_errno=int(sys.argv[7]) if error_mode else None
    if error_mode and not 1<=expected_errno<=4095:raise ValueError('nonzero expected errno required')
    expected=None if error_mode else bytes.fromhex(sys.argv[7]);value=bytes.fromhex(sys.argv[8]) if writing else None
    if not error_mode and not 1<=len(expected)<=2042 or writing and not 1<=len(value)<=2042:raise ValueError('bounded nonempty test value required')
    deadline=time.monotonic_ns()+5_000_000_000
    with Client(deadline_ns=deadline) as client:
        link=client.connection(ControllerId(index,generation),path,deadline_ns=deadline)
    with link:
        if error_mode:
            # The actual remote owner prompt is the controlled arrival barrier.
            print(json.dumps(dict(stage='ssap_call',api='python',deadline_ns=deadline,call_ns=time.monotonic_ns(),client_closed=True)),flush=True)
        else:
            print(json.dumps(dict(stage='ssap_start_barrier',api='python',client_closed=True)),flush=True)
            wait(0,select.POLLIN,deadline)
            if os.read(0,6)!=b'start\n':raise ValueError('explicit original start barrier required')
        remote=link.ssap()
        try:
            actual=remote.write(handle,value,deadline_ns=deadline) if writing else remote.read(handle,deadline_ns=deadline)
        except OSError as error:
            if not error_mode:raise
            print(json.dumps(dict(stage='ssap_error',api='python',errno=error.errno,operation_success=False,deadline_ns=deadline,returned_ns=time.monotonic_ns())),flush=True)
            if error.errno!=expected_errno:raise
            return
        if error_mode:raise AssertionError('negative scenario unexpectedly completed the operation')
        if actual!=expected:raise ValueError('actual peer SSAP result differs from expected random value')
        print(f'SsapPeerValue: operation={operation} path={path} handle={handle} value={actual.hex()}',flush=True)


def discovery_mode():
    if len(sys.argv)!=7:raise ValueError('discovery index generation prefix count address-hex')
    index,generation=int(sys.argv[2]),int(sys.argv[3]);prefix=bytes.fromhex(sys.argv[4]);wanted=int(sys.argv[5]);address=bytes.fromhex(sys.argv[6])
    if not 1<=len(prefix)<=64 or not 1<=wanted<=1024 or len(address)!=6:raise ValueError('bounded discovery test inputs')
    deadline=time.monotonic_ns()+20_000_000_000;identity=ControllerId(index,generation)
    with Client(deadline_ns=deadline) as client:lease=client.discover(identity,prefix=prefix,deadline_ns=deadline)
    with lease:
        path=f'/org/sparklink/slk{index}_g{generation}'
        print('Selected '+path,flush=True)
        print(f'DiscoverySession: id={lease.session_id} path={path} state=active source=broker',flush=True)
        received=0
        while received<wanted:
            batch=lease.read(deadline_ns=deadline)
            for r in batch.reports:
                if r.address!=address:continue
                if r.rssi is None:raise ValueError('known RSSI needed by this physical gate')
                print(f'DiscoveryReport: session={lease.session_id} generation={generation} sequence={r.sequence} address_type={r.address_type} address={r.address.hex()} rssi={r.rssi} data={r.data.hex()}',flush=True)
                received+=1
                if received==wanted:break
        stopped=lease.release(deadline_ns=deadline)
        print(f'DiscoveryReleased: session={lease.session_id} last_physical_stop_confirmed={str(stopped).lower()}',flush=True)


def owned_info(info):
    return dict(api='python',index=info.controller.index,generation=info.controller.generation,
        token=info.token,request_id=info.request_id,lifetime=info.connection_lifetime,
        handle=info.connection_handle,epoch=info.security_epoch,level=info.security_level,
        deadline_ns=info.deadline_ns,property=info.property,data_type=info.data_type,write=info.write,
        value=info.value.hex(),local_tcid=info.local_tcid,remote_tcid=info.remote_tcid,pi=info.pi)


def owned_mode():
    from sparklink import LocalProperty, SsapOperations, SsapAccess
    updates=sys.argv[1]=='owned-updates'
    if len(sys.argv) not in ((9,) if updates else (7,8)):raise ValueError('owned index generation service property initial-hex [allow|deny|ask] [update-connection]')
    policy=sys.argv[7] if len(sys.argv)>=8 else None
    if policy not in (None,'allow','deny','ask'):raise ValueError('explicit application test policy required')
    index,generation=int(sys.argv[2]),int(sys.argv[3])
    service,uuid,value=(bytes.fromhex(v) for v in sys.argv[4:7])
    identity=ControllerId(index,generation)
    original=time.monotonic_ns()+5_000_000_000
    link=None
    with Client(deadline_ns=original) as client:
        view=client.register_local_service(identity,service,
            [LocalProperty(uuid,SsapOperations(541 if updates else 1 if sys.argv[1]=='owned-readonly' else 5),SsapAccess(36 if policy and not updates else 0),value)],
            deadline_ns=original,authorization='requests' if policy else 'none')
        if updates:link=client.connection(identity,sys.argv[8],deadline_ns=original)
    with view:
        receipt=view.receipt
        if len(receipt.handles)!=1:raise ValueError('one owned property required')
        handle=receipt.handles[0]
        print('SdkOwnedAPI: api=python client_closed=true',flush=True)
        print(f'SsapOwnedService: start={receipt.start} end={receipt.end} property={handle}; local registration only',flush=True)
        end=time.monotonic_ns()+30_000_000_000
        fd=view.authorization_fd() if policy else None
        line=bytearray();poller=select.poll();poller.register(0,select.POLLIN)
        if fd is not None:poller.register(fd,select.POLLIN)
        pending=None;closed=False
        try:
            while True:
                if policy and not closed and pending is None:
                    try:pending=view.next_authorization()
                    except OSError as error:
                        if error.errno!=errno.EAGAIN:raise
                    else:
                        info=pending.info
                        if policy=='ask':
                            print('SdkAuthorizationRequest: '+json.dumps(owned_info(info)),flush=True)
                            print(f"SsapAuthorizationPrompt: token={info.token} request={info.request_id} index={index} generation={generation} lifetime={info.connection_lifetime} handle={info.connection_handle} epoch={info.security_epoch} security={info.security_level} property={info.property} data_type={info.data_type} write={str(info.write).lower()} bytes={len(info.value)} deadline_ns={info.deadline_ns}; answer 'yes {info.token}' or 'no {info.token}'",flush=True)
                        else:
                            decision,wall=time.monotonic_ns(),time.time_ns()
                            try:pending.reply(policy=='allow')
                            finally:pending.close();pending=None
                            print('SdkAuthorizationDecision: '+json.dumps(dict(owned_info(info),allow=policy=='allow',decision_ns=decision,decision_wall_ns=wall)),flush=True)
                left=end-time.monotonic_ns()
                if left<=0:raise TimeoutError(errno.ETIMEDOUT,'original publisher deadline')
                ready=dict(poller.poll((left+999999)//1000000))
                if fd is not None and not closed and ready.get(fd,0)&(select.POLLERR|select.POLLHUP|select.POLLNVAL):
                    raise OSError(errno.EIO,'approval notification failed')
                if not ready.get(0,0)&select.POLLIN:
                    if ready.get(0,0)&(select.POLLERR|select.POLLHUP|select.POLLNVAL):raise BrokenPipeError('publisher input closed')
                    continue
                byte=os.read(0,1)
                if not byte:raise BrokenPipeError('publisher input closed')
                line+=byte
                if byte!=b'\n':
                    if len(line)>=4095:raise ValueError('bounded owned command required')
                    continue
                if line==b'value\n':
                    actual=view.read_local(handle,deadline_ns=time.monotonic_ns()+5_000_000_000)
                    print(f'SsapOwnedValue: handle={handle} value={actual.hex()}',flush=True)
                elif line.startswith(b'replace '):
                    value=bytes.fromhex(line[8:-1].decode('ascii'))
                    started=time.monotonic_ns();deadline=started+5_000_000_000
                    view.replace_local(handle,value,deadline_ns=deadline)
                    print('SdkOwnedReplaced: '+json.dumps(dict(api='python',handle=handle,value=value.hex(),
                        started_ns=started,deadline_ns=deadline,returned_ns=time.monotonic_ns())),flush=True)
                elif updates and line==b'configuration\n':
                    started=time.monotonic_ns();deadline=started+5_000_000_000
                    modes=link.ssap().owned_configuration(handle,deadline_ns=deadline)
                    print('SdkOwnedConfiguration: '+json.dumps(dict(api='python',handle=handle,modes=modes,
                        started_ns=started,deadline_ns=deadline,returned_ns=time.monotonic_ns())),flush=True)
                elif updates and line in (b'notify\n',b'indicate\n',b'indicate-deadline\n',b'indicate-observe\n'):
                    short_deadline=line==b'indicate-deadline\n';observe=short_deadline or line==b'indicate-observe\n'
                    started=time.monotonic_ns();deadline=started+(1_000_000_000 if short_deadline else 5_000_000_000)
                    try:
                        result=link.ssap().send_owned_update(handle,deadline_ns=deadline,indication=line!=b'notify\n')
                    except OSError as error:
                        if not observe:raise
                        observed=-error.errno
                    else:observed=0
                    if observe:
                        # A result observation,not a success verdict. Wrong
                        # errors and unexpected success remain gate failures.
                        print(('SdkOwnedUpdateDeadline: 'if short_deadline else'SdkOwnedUpdateObserved: ')+json.dumps(dict(api='python',handle=handle,result=observed,
                            started_ns=started,deadline_ns=deadline,returned_ns=time.monotonic_ns())),flush=True)
                        line.clear();continue
                    print('SdkOwnedUpdate: '+json.dumps(dict(api='python',handle=handle,stage=result.stage,
                        pdu=result.pdu.hex(),ack=result.acknowledgement.hex(),
                        started_ns=started,deadline_ns=deadline,returned_ns=time.monotonic_ns())),flush=True)
                elif policy=='ask' and (line.startswith(b'yes ') or line.startswith(b'no ')):
                    parts=line.decode('ascii').split()
                    if len(parts)!=2 or not parts[1].isascii() or not parts[1].isdecimal() or not 0<=int(parts[1])<2**64:raise ValueError('exact unsigned token required')
                    token=int(parts[1]);current=pending.info.token if pending else 0
                    called=pending is not None and token==current
                    result=-errno.ESTALE
                    if called:
                        try:pending.reply(parts[0]=='yes');result=0
                        except OSError as error:
                            if error.errno not in (errno.ESTALE,errno.ETIMEDOUT,errno.ESHUTDOWN):raise
                            result=-error.errno
                        finally:pending.close();pending=None
                    print('SdkAuthorizationReply: '+json.dumps(dict(api='python',token=token,current_token=current,allow=parts[0]=='yes',api_called=called,result=result,returned_ns=time.monotonic_ns())),flush=True)
                elif policy=='ask' and line==b'close\n':
                    if closed or pending is None:raise ValueError('live service with actual pending request required')
                    snapshot=pending.info;view.close();closed=True;poller.unregister(fd)
                    try:pending.reply(True)
                    except OSError as error:
                        if error.errno!=errno.ESTALE:raise
                        result=-error.errno
                    else:raise AssertionError('closed original scope accepted policy')
                    print('SdkServiceClosed: '+json.dumps(dict(api='python',token=snapshot.token,
                        info_preserved=pending.info==snapshot,notification_fd_alive=os.fstat(fd) is not None,
                        reply_result=result,closed_ns=time.monotonic_ns())),flush=True)
                    pending.close();pending=None
                elif line==b'quit\n':
                    if closed:
                        print(f'SdkOwnedClosedExit: api=python start={receipt.start}',flush=True)
                    else:
                        view.unregister(deadline_ns=time.monotonic_ns()+5_000_000_000)
                        print(f'SdkOwnedRemoved: api=python start={receipt.start}',flush=True)
                    return
                else:raise ValueError('bounded owned command required')
                line.clear()
        finally:
            if pending:pending.close()
            if fd is not None:os.close(fd)
            if link is not None:link.close()


def checked_update_write(link,handle,mode,pdu,expected,reply):
    exact=bytes([16 if mode==2 else 15,3])+handle.to_bytes(2,'little')+len(expected).to_bytes(2,'little')+expected
    if pdu!=exact:raise ValueError('actual peer complete random update mismatch')
    actual=link.ssap().write(handle,reply,minimum=2,deadline_ns=time.monotonic_ns()+5_000_000_000)
    if actual!=reply:raise ValueError('actual business reply result mismatch')


def update_peer_mode():
    if len(sys.argv)!=9:raise ValueError('update-peer index generation connection handle mode expected reply')
    index,generation=int(sys.argv[2]),int(sys.argv[3]);path=sys.argv[4]
    handle,mode=int(sys.argv[5]),int(sys.argv[6]);retired=sys.argv[1]=='update-retired'
    negative=sys.argv[1] in ('update-error','update-retired')
    expected,reply=(b'',b'') if negative else map(bytes.fromhex,sys.argv[7:9])
    budget_ms=int(sys.argv[8]) if negative else 5000
    expected_error=errno.EIO if retired else errno.ETIMEDOUT
    if negative and (int(sys.argv[7])!=expected_error or not 50<=budget_ms<=5000
                     or (retired and (mode!=2 or budget_ms!=5000))):
        raise ValueError('bounded explicit receive-error case required;retirement requires EIO,indication,5000ms')
    if mode not in (1,2) or not 1<=handle<=65535 or len(expected)>2042 or len(reply)>2042 or (not negative and expected==reply):
        raise ValueError('bounded independent update/reply required')
    started=time.monotonic_ns();original=started+budget_ms*1_000_000
    with Client(deadline_ns=original) as client:link=client.connection(ControllerId(index,generation),path,deadline_ns=original)
    with link:
        call=dict(stage='ssap_update_wait',api='python',handle=handle,mode=mode,
            deadline_ns=original,client_closed=True)
        call.update(started_ns=started,budget_ms=budget_ms)
        print(json.dumps(call),flush=True)
        try:received=link.ssap().receive_update(handle,deadline_ns=original,modes=mode)
        except OSError as error:
            if not negative or error.errno!=expected_error:raise
            print(json.dumps(dict(stage='ssap_update_error',api='python',handle=handle,mode=mode,
                errno=error.errno,deadline_ns=original,returned_ns=time.monotonic_ns())),flush=True)
            return
        if negative:raise ValueError('receive unexpectedly succeeded instead of required original error')
        if received.stage!=3 or received.acknowledgement:
            raise ValueError('actual peer complete random update mismatch')
        checked_update_write(link,handle,mode,received.pdu,expected,reply)
        print(json.dumps(dict(stage='ssap_update_checked_reply',api='python',handle=handle,mode=mode,
            pdu=received.pdu.hex(),value=expected.hex(),reply=reply.hex())),flush=True)


def subscription_mode():
    if len(sys.argv)!=8:raise ValueError('subscription index generation connection handle modes lease_ms')
    index,generation=int(sys.argv[2]),int(sys.argv[3]);path=sys.argv[4]
    handle,modes,duration_ms=map(int,sys.argv[5:8])
    with Client(deadline_ns=time.monotonic_ns()+5_000_000_000) as client:
        link=client.connection(ControllerId(index,generation),path,deadline_ns=time.monotonic_ns()+5_000_000_000)
    started=time.monotonic_ns();creation_deadline=started+5_000_000_000
    with link,link.ssap().subscribe([handle],modes=modes,duration_ms=duration_ms,
            deadline_ns=creation_deadline) as sub:
        info=sub.info();released=False;cache=();position=0
        print(json.dumps(dict(stage='ssap_subscription_active',api='python',token=info.token,
                              epoch=info.security_epoch,expires_ns=info.expires_ns,started_ns=started,
                              deadline_ns=creation_deadline,returned_ns=time.monotonic_ns(),client_closed=True)),flush=True)
        while True:
            line=sys.stdin.readline(16384)
            if not line:
                if position!=len(cache):raise OSError(errno.EBUSY,'unchecked cached batch')
                break
            if len(line)>16383 or not line.endswith('\n'):raise ValueError('bounded complete input line required')
            args=line.split()
            if args==['quit']:
                if position!=len(cache):raise OSError(errno.EBUSY,'unchecked cached batch')
                break
            if args==['parent-close']:
                link.close()
                print(json.dumps(dict(stage='ssap_subscription_parent_closed',api='python')),flush=True)
                continue
            if len(args)==2 and args[0]=='renew':
                renewal_started=time.monotonic_ns();renewal_deadline=renewal_started+5_000_000_000
                info=sub.renew(int(args[1]),deadline_ns=renewal_deadline)
                print(json.dumps(dict(stage='ssap_subscription_renewed',api='python',token=info.token,
                    epoch=info.security_epoch,expires_ns=info.expires_ns,started_ns=renewal_started,
                    deadline_ns=renewal_deadline,returned_ns=time.monotonic_ns())),flush=True)
                continue
            if args==['release']:
                if position!=len(cache):raise OSError(errno.EBUSY,'unchecked cached batch')
                batch=sub.release(deadline_ns=time.monotonic_ns()+5_000_000_000);released=True
                print(json.dumps(dict(stage='ssap_subscription_released',api='python',flags=batch.flags,
                                      discarded=batch.discarded_on_close)),flush=True)
                continue
            from_cache=len(args)==3 and args[0]=='check-cached';check=from_cache or len(args)==3 and args[0]=='check'
            if not check and args not in (['read'],['poll'],['drain']):raise ValueError('unknown subscription operation')
            if check:
                expected,reply=map(bytes.fromhex,args[1:])
                if not 1<=len(expected)<=2042 or not 1<=len(reply)<=2042 or expected==reply:
                    raise ValueError('independent bounded update/reply required')
                link._live()
            if from_cache:
                if position>=len(cache):raise OSError(errno.ENODATA,'no cached update')
            else:
                if position!=len(cache):raise OSError(errno.EBUSY,'unchecked cached batch')
                batch=sub.read(wait=args!=['poll'],deadline_ns=time.monotonic_ns()+5_000_000_000)
                if args==['drain']:
                    if not 1<=len(batch.packets)<=16:raise ValueError('bounded nonempty batch required')
                    cache=batch.packets;position=0
            if check:
                if not from_cache and len(batch.packets)!=1:raise ValueError('exact single complete update required')
                packet=cache[position]if from_cache else batch.packets[0]
                checked_update_write(link,handle,2 if packet.indication else 1,packet.pdu,expected,reply)
                print(json.dumps(dict(stage='ssap_subscription_checked_reply',api='python',
                    sequence=packet.sequence,value=expected.hex(),reply=reply.hex())),flush=True)
                if from_cache:
                    position+=1
                    continue
            if batch.info.state==3 and batch.flags==1:released=True
            print(json.dumps(dict(stage='ssap_subscription_batch',api='python',last=batch.last_sequence,
                dropped=batch.dropped_notifications,refused=batch.refused_indications,state=batch.info.state,
                flags=batch.flags,reason=batch.reason,discarded=batch.discarded_on_close,
                packets=[dict(sequence=p.sequence,epoch=p.security_epoch,level=p.security_level,indication=p.indication,
                              pdu=p.pdu.hex()) for p in batch.packets])),flush=True)
        if not released:
            batch=sub.release(deadline_ns=time.monotonic_ns()+5_000_000_000)
            print(json.dumps(dict(stage='ssap_subscription_released',api='python',flags=batch.flags,
                                  discarded=batch.discarded_on_close)),flush=True)


if __name__=="__main__":main()
