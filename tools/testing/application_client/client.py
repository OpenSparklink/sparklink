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


if __name__=="__main__":main()
