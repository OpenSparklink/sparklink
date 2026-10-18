# SPDX-License-Identifier: GPL-2.0-only
"""Receive the isolated client's real D-Bus-authorized fd, not radio data.

The VM supervisor must enable SO_PASSCRED before the client sends, check the
original bus owner independently and reap the client before killing slkd.
This primitive alone grants no daemon-death or WS73 qualification.
"""
import array
import fcntl
import json
import os
import socket
import struct


def receive(control, *, token, path, daemon_pid, daemon_owner,
            expected_identity=(1000,1002), expected_family=46):
    payload,ancillary,flags,_=control.recvmsg(16384,socket.CMSG_SPACE(16*array.array('i').itemsize)+socket.CMSG_SPACE(12),socket.MSG_CMSG_CLOEXEC)
    delivered=[];credentials=[];unexpected=False
    try:
        for level,kind,value in ancillary:
            if (level,kind)==(socket.SOL_SOCKET,socket.SCM_RIGHTS):
                fds=array.array('i');fds.frombytes(value[:len(value)//fds.itemsize*fds.itemsize]);delivered.extend(fds)
                if len(value)%fds.itemsize:unexpected=True
            elif (level,kind)==(socket.SOL_SOCKET,socket.SCM_CREDENTIALS) and len(value)==12:
                credentials.append(struct.unpack('3i',value))
            else:unexpected=True
        if unexpected or flags&(socket.MSG_TRUNC|socket.MSG_CTRUNC) or len(delivered)!=1 or len(credentials)!=1:
            raise ValueError('one complete fd and kernel credential record required')
        row=json.loads(payload)
        if not isinstance(row,dict) or set(row)!={'stage','token','path','pid','daemon_pid','daemon_owner','inode','process_status','wall_ns'}:
            raise ValueError('exact daemon fd receipt shape required')
        pid,uid,gid=credentials[0]
        if ((uid,gid)!=expected_identity or row['pid']!=pid or pid<=0
                or row['stage']!='daemon_channel_fd' or row['token']!=token or len(token)!=32
                or row['path']!=path or row['daemon_pid']!=daemon_pid or daemon_pid<=0
                or row['daemon_owner']!=daemon_owner or not daemon_owner.startswith(':')
                or not isinstance(row['wall_ns'],str) or not row['wall_ns'].isdigit() or int(row['wall_ns'])<=0):
            raise ValueError('original ordinary sender and actual daemon grantor required')
        fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in row['process_status'].splitlines() if ':' in line}
        for name,expected in [('Uid',uid),('Gid',gid)]:
            if list(map(int,fields[name].split()))!=[expected]*4:raise ValueError('sender process identity mismatch')
        if any(int(fields[k],16) for k in ['CapEff','CapPrm','CapAmb','CapInh']):raise ValueError('capability-free sender required')
        fd=delivered[0]
        if os.fstat(fd).st_ino!=row['inode'] or not fcntl.fcntl(fd,fcntl.F_GETFD)&fcntl.FD_CLOEXEC:
            raise ValueError('same close-on-exec socket reference required')
        data=socket.socket(expected_family,socket.SOCK_DGRAM,0,fileno=fd)
        delivered.clear()
        try:
            if data.getsockopt(socket.SOL_SOCKET,socket.SO_DOMAIN)!=expected_family or data.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE)!=socket.SOCK_DGRAM:
                raise ValueError('actual native datagram fd required')
        except BaseException:
            data.close();raise
        row['kernel_sender']=dict(pid=pid,uid=uid,gid=gid)
        return data,row
    finally:
        for fd in delivered:os.close(fd)
