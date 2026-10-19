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
    if sys.argv[1:2] in (['owned'],['owned-readonly']):return owned_mode()
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
    if len(sys.argv) not in (7,8):raise ValueError('owned index generation service property initial-hex [allow|deny|ask]')
    policy=sys.argv[7] if len(sys.argv)==8 else None
    if policy not in (None,'allow','deny','ask'):raise ValueError('explicit application test policy required')
    index,generation=int(sys.argv[2]),int(sys.argv[3])
    service,uuid,value=(bytes.fromhex(v) for v in sys.argv[4:7])
    identity=ControllerId(index,generation)
    original=time.monotonic_ns()+5_000_000_000
    with Client(deadline_ns=original) as client:
        view=client.register_local_service(identity,service,
            [LocalProperty(uuid,SsapOperations(1 if sys.argv[1]=='owned-readonly' else 5),SsapAccess(36 if policy else 0),value)],
            deadline_ns=original,authorization='requests' if policy else 'none')
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


if __name__=="__main__":main()
