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
    if sys.argv[1:2] in (['ssap-command'],['ssap-command-reject']):return ssap_command_mode()
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
    if operation not in ('ssap-read','ssap-read-description','ssap-write') or len(sys.argv)!=(9 if writing else 8):raise ValueError('one exact read/short write required')
    error_mode=sys.argv[1]=='ssap-error'
    empty_read=not error_mode and operation=='ssap-read' and sys.argv[7]==''
    if not (empty_read or 1<=len(sys.argv[7])<=4084) or writing and not 1<=len(sys.argv[8])<=4084:raise ValueError('bounded test value required')
    expected_errno=int(sys.argv[7]) if error_mode else None
    if error_mode and not 1<=expected_errno<=4095:raise ValueError('nonzero expected errno required')
    expected=None if error_mode else bytes.fromhex(sys.argv[7]);value=bytes.fromhex(sys.argv[8]) if writing else None
    if not error_mode and not (empty_read or 1<=len(expected)<=2042) or writing and not 1<=len(value)<=2042:raise ValueError('bounded nonempty test value required')
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
            if writing:actual=remote.write(handle,value,deadline_ns=deadline)
            elif operation=='ssap-read-description':actual=remote.read_description(handle,deadline_ns=deadline)
            else:actual=remote.read(handle,deadline_ns=deadline)
        except OSError as error:
            if not error_mode:raise
            print(json.dumps(dict(stage='ssap_error',api='python',errno=error.errno,operation_success=False,deadline_ns=deadline,returned_ns=time.monotonic_ns())),flush=True)
            if error.errno!=expected_errno:raise
            return
        if error_mode:raise AssertionError('negative scenario unexpectedly completed the operation')
        if actual!=expected:raise ValueError('actual peer SSAP result differs from expected random value')
        print(f'SsapPeerValue: operation={operation} path={path} handle={handle} value={actual.hex()}',flush=True)


def ssap_command_mode():
    if len(sys.argv) not in (7,8):raise ValueError('ssap-command index generation path handle value-hex [minimum]')
    reject=sys.argv[1]=='ssap-command-reject'
    index,generation=int(sys.argv[2]),int(sys.argv[3]);path=sys.argv[4];handle=int(sys.argv[5])
    minimum=int(sys.argv[7]) if len(sys.argv)==8 else 0
    if not 1<=handle<=65535 or not 0<=minimum<=2 or not 0<=len(sys.argv[6])<=(4086 if reject else 4084):raise ValueError('bounded command test inputs')
    if reject and (minimum!=0 or not 0<=index<=65535 or not 1<=generation<=2**64-1 or not 1<=len(path)<=256):raise ValueError('exact oversize rejection scope required')
    value=bytes.fromhex(sys.argv[6])
    if (len(value)!=2043 if reject else not 0<=len(value)<=2042):raise ValueError('bounded command test value')
    deadline=time.monotonic_ns()+5_000_000_000
    with Client(deadline_ns=deadline) as client:
        link=client.connection(ControllerId(index,generation),path,deadline_ns=deadline)
    with link:
        barrier=dict(stage='ssap_command_start_barrier',api='python',deadline_ns=deadline,client_closed=True)
        if reject:barrier.update(mode='ssap-command-reject',schema_version=1)
        print(json.dumps(barrier),flush=True)
        wait(0,select.POLLIN,deadline)
        if os.read(0,6)!=b'start\n':raise ValueError('explicit original command start barrier required')
        remote=link.ssap()
        called=time.monotonic_ns()
        if reject and called>=deadline:raise TimeoutError(errno.ETIMEDOUT,'original command rejection deadline')
        try:
            result=remote.write_without_response(handle,value,minimum=minimum,deadline_ns=deadline)
        except OSError as error:
            returned=time.monotonic_ns()
            if not reject or error.errno!=errno.EINVAL:raise
            if not called<returned<deadline:raise TimeoutError(errno.ETIMEDOUT,'command rejection returned outside original deadline') from error
            print('SSAP_COMMAND_REJECTED: '+json.dumps(dict(schema_version=1,mode='ssap-command-reject',api='python',method='WriteSsapCommand',
                index=index,generation=generation,path=path,handle=handle,value=value.hex(),application_bytes=len(value),minimum=minimum,
                sdk_entered=True,errno=error.errno,operation_success=False,peer_delivery_confirmed=False,
                deadline_ns=deadline,call_ns=called,returned_ns=returned)),flush=True)
            return
        returned=time.monotonic_ns()
        if reject:raise AssertionError('oversize SDK command unexpectedly succeeded')
        if result is not None:raise ValueError('command must return software admission without response bytes')
        print('SSAP_COMMAND_ADMITTED: '+json.dumps(dict(api='python',handle=handle,value=value.hex(),minimum=minimum,
            admission_only=True,peer_delivery_confirmed=False,deadline_ns=deadline,call_ns=called,returned_ns=returned)),flush=True)


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


def owned_exit_error():
    error=sys.exc_info()[1]
    if error is None:return 0
    return -error.errno if isinstance(error,OSError) and error.errno else -errno.EIO


def owned_lifecycle(stage,receipt,created,end,error=0,token=0,request_id=0,call_started=0,call_returned=0):
    # Same-guest observations only,not server TTL/commit/remote cleanup.
    print('SdkOwnedLifecycle: '+json.dumps(dict(version=1,api='python',stage=stage,pid=os.getpid(),
        index=receipt.controller.index,generation=receipt.controller.generation,start=receipt.start,
        property=receipt.handles[0],created_ns=created,deadline_ns=end,sampled_ns=time.monotonic_ns(),
        wall_ns=time.time_ns(),error=error,token=token,request_id=request_id,
        call_started_ns=call_started,call_returned_ns=call_returned)),flush=True)


def owned_provider_info(info):
    return dict(api='python',index=info.controller.index,generation=info.controller.generation,
        token=info.token,request_id=info.request_id,lifetime=info.connection_lifetime,
        handle=info.connection_handle,epoch=info.security_epoch,level=info.security_level,
        deadline_ns=info.deadline_ns,property=info.property,maximum_bytes=info.maximum_bytes,
        local_tcid=info.local_tcid,remote_tcid=info.remote_tcid,pi=info.pi,
        observed_ns=time.monotonic_ns(),observed_wall_ns=time.time_ns())


def owned_provider_command(line):
    # Application input only; the public request still checks its original scope.
    text=line.decode('ascii')
    if not text.endswith('\n') or text.count('\n')!=1:
        raise ValueError('one provider command line required')
    parts=text[:-1].split(' ')
    if len(parts)!=3 or not all(parts) or parts[0] not in ('provide','provider-error'):
        raise ValueError('exact provider command required')
    word=parts[1]
    if not word.startswith('p') or not word[1:].isdecimal() or not 1<=int(word[1:])<2**64:
        raise ValueError('nonzero unsigned provider token required')
    if parts[0]=='provider-error':
        if len(parts[2])!=2 or any(c not in '0123456789abcdefABCDEF' for c in parts[2]):
            raise ValueError('two-digit application error required')
        status=int(parts[2],16)
        if not 0xAF<=status<=0xFF:raise ValueError('application error must be AF..FF')
        value=b''
    else:
        status=0
        if parts[2]=='-':value=b''
        else:
            if len(parts[2])%2 or any(c not in '0123456789abcdefABCDEF' for c in parts[2]):
                raise ValueError('exact hexadecimal provider value required')
            value=bytes.fromhex(parts[2])
    return int(word[1:]),status,value


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
    observing=False;created=end=0
    try:
        with view:
            receipt=view.receipt
            if len(receipt.handles)!=1:raise ValueError('one owned property required')
            handle=receipt.handles[0]
            print('SdkOwnedAPI: api=python client_closed=true',flush=True)
            print(f'SsapOwnedService: start={receipt.start} end={receipt.end} property={handle}; local registration only',flush=True)
            created=time.monotonic_ns();end=created+30_000_000_000
            fd=view.authorization_fd() if policy else None
            line=bytearray();poller=select.poll();poller.register(0,select.POLLIN)
            if fd is not None:poller.register(fd,select.POLLIN)
            pending=None;closed=False
            provider=None;provider_fd=None;provider_pending=None
            provider_attempted=False;provider_polling=False
            def stop_provider():
                nonlocal provider,provider_fd,provider_pending,provider_polling
                # Stop admission before releasing the request or notification fd.
                if provider is not None:provider.close();provider=None
                if provider_pending is not None:provider_pending.close();provider_pending=None
                if provider_fd is not None:
                    if provider_polling:poller.unregister(provider_fd);provider_polling=False
                    os.close(provider_fd);provider_fd=None
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
                                call_error=0
                                try:pending.reply(policy=='allow')
                                except BaseException:
                                    call_error=owned_exit_error();raise
                                finally:
                                    if observing:
                                        returned=time.monotonic_ns()
                                        owned_lifecycle('approval_return',receipt,created,end,call_error,
                                            info.token,info.request_id,decision,returned)
                                    pending.close();pending=None
                                print('SdkAuthorizationDecision: '+json.dumps(dict(owned_info(info),allow=policy=='allow',decision_ns=decision,decision_wall_ns=wall)),flush=True)
                    if provider is not None and not closed and provider_pending is None:
                        if time.monotonic_ns()>=end:raise TimeoutError(errno.ETIMEDOUT,'original publisher deadline')
                        try:provider_pending=provider.next_request()
                        except OSError as error:
                            if error.errno!=errno.EAGAIN:raise
                        else:
                            # A stopped notification stays readable; while this view
                            # is held, only stdin can decide/release it. Avoid spin.
                            if provider_polling:poller.unregister(provider_fd);provider_polling=False
                            print('SdkReadProviderRequest: '+json.dumps(owned_provider_info(provider_pending.info)),flush=True)
                    left=end-time.monotonic_ns()
                    if left<=0:raise TimeoutError(errno.ETIMEDOUT,'original publisher deadline')
                    ready=dict(poller.poll((left+999999)//1000000))
                    if fd is not None and not closed and ready.get(fd,0)&(select.POLLERR|select.POLLHUP|select.POLLNVAL):
                        raise OSError(errno.EIO,'approval notification failed')
                    if provider_polling and ready.get(provider_fd,0)&(select.POLLERR|select.POLLHUP|select.POLLNVAL):
                        raise OSError(errno.EIO,'provider notification failed')
                    if not ready.get(0,0)&select.POLLIN:
                        if ready.get(0,0)&(select.POLLERR|select.POLLHUP|select.POLLNVAL):raise BrokenPipeError('publisher input closed')
                        continue
                    byte=os.read(0,1)
                    if not byte:raise BrokenPipeError('publisher input closed')
                    line+=byte
                    if byte!=b'\n':
                        if len(line)>=4095:raise ValueError('bounded owned command required')
                        continue
                    if line==b'lifecycle\n':
                        if updates or policy!='allow' or closed or observing:raise ValueError('one live plain allow publisher observation required')
                        if time.monotonic_ns()>=end:raise TimeoutError(errno.ETIMEDOUT,'original publisher deadline')
                        observing=True;owned_lifecycle('observed',receipt,created,end)
                    elif sys.argv[1]=='owned-readonly' and line==b'provider\n':
                        if closed or provider_attempted:raise ValueError('one live original provider bind attempt required')
                        provider_attempted=True
                        started=time.monotonic_ns();deadline=min(started+5_000_000_000,end)
                        if started>=end:raise TimeoutError(errno.ETIMEDOUT,'original publisher deadline')
                        result=0;notification_result=None;notification_ready=False;failure=None
                        try:provider=view.bind_read_provider(handle,deadline_ns=deadline)
                        except BaseException as error:
                            result=owned_exit_error();failure=error
                        finally:returned=time.monotonic_ns()
                        if failure is None:
                            try:
                                provider_fd=provider.notification_fd();notification_result=0
                                poller.register(provider_fd,select.POLLIN);provider_polling=True
                                notification_ready=True
                            except BaseException as error:
                                if notification_result is None:notification_result=owned_exit_error()
                                failure=error
                        print('SdkReadProviderBound: '+json.dumps(dict(api='python',index=index,generation=generation,
                            property=handle,started_ns=started,deadline_ns=deadline,returned_ns=returned,result=result,
                            notification_result=notification_result,notification_ready=notification_ready,
                            local_binding_only=True)),flush=True)
                        if failure is not None:raise failure
                    elif sys.argv[1]=='owned-readonly' and (line.startswith(b'provide ') or line.startswith(b'provider-error ')):
                        if closed or provider is None or not provider_attempted:
                            raise OSError(errno.ESHUTDOWN,'live original provider required')
                        token,status,provided=owned_provider_command(line)
                        info=provider_pending.info if provider_pending is not None else None
                        current=info.token if info is not None else 0
                        called=provider_pending is not None and token==current
                        started=time.monotonic_ns();result=-errno.ESTALE;failure=None
                        if started>=end:raise TimeoutError(errno.ETIMEDOUT,'original publisher deadline')
                        if called:
                            try:provider_pending.reply(provided,status=status);result=0
                            except BaseException as error:
                                result=owned_exit_error();failure=error
                        returned=time.monotonic_ns()
                        print('SdkReadProviderReply: '+json.dumps(dict(api='python',token=token,current_token=current,
                            api_called=called,status=status,value=provided.hex(),deadline_ns=info.deadline_ns if info else 0,
                            started_ns=started,returned_ns=returned,result=result,local_acceptance_only=True)),flush=True)
                        if failure is not None and (not isinstance(failure,OSError) or failure.errno not in
                                (errno.EINVAL,errno.EMSGSIZE,errno.ESTALE,errno.ETIMEDOUT,errno.ESHUTDOWN)):
                            raise failure
                        if called and result in (0,-errno.ESTALE,-errno.ETIMEDOUT,-errno.ESHUTDOWN):
                            provider_pending.close();provider_pending=None
                            if not closed:
                                poller.register(provider_fd,select.POLLIN);provider_polling=True
                    elif line==b'value\n':
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
                        if provider_polling:poller.unregister(provider_fd);provider_polling=False
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
                        stop_provider()
                        if closed:
                            print(f'SdkOwnedClosedExit: api=python start={receipt.start}',flush=True)
                        else:
                            cleanup_deadline=time.monotonic_ns()+5_000_000_000
                            if provider_attempted:cleanup_deadline=min(cleanup_deadline,end)
                            view.unregister(deadline_ns=cleanup_deadline)
                            print(f'SdkOwnedRemoved: api=python start={receipt.start}',flush=True)
                        return
                    else:raise ValueError('bounded owned command required')
                    line.clear()
            finally:
                if observing:owned_lifecycle('cleanup_begin',receipt,created,end,owned_exit_error())
                stop_provider()
                if pending:pending.close()
                if fd is not None:os.close(fd)
                if link is not None:link.close()
    finally:
        if observing:owned_lifecycle('cleanup_end',receipt,created,end,owned_exit_error())


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
            if args in (['release'],['release-observe']):
                if position!=len(cache):raise OSError(errno.EBUSY,'unchecked cached batch')
                close_started=time.monotonic_ns();close_deadline=close_started+5_000_000_000
                if args==['release-observe']:
                    print(json.dumps(dict(stage='ssap_subscription_release_started',api='python',
                        started_ns=close_started,deadline_ns=close_deadline)),flush=True)
                batch=sub.release(deadline_ns=close_deadline);released=True
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
            if batch.info.state==3 and (batch.flags & 1)==1:released=True
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
