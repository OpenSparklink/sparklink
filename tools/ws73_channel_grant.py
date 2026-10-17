# SPDX-License-Identifier: GPL-2.0-only
"""Real scratch-VM socket Grant gate, layered on established File cleanup.
IPC carries application commands/receipts, never substitutes for radio RX.
Children close all inherited control fds before dropping to UID1000/caps0.
"""
import ctypes
import array
import errno
import fcntl
import json
import os
from pathlib import Path
import secrets
import select
import signal
import socket
import struct
import time

from ws73_capture import CaptureError, reassemble_acb


class Address(ctypes.Structure):
    _fields_=[('family',ctypes.c_uint16),('controller',ctypes.c_uint16),
              ('version',ctypes.c_uint16),('flags',ctypes.c_uint16),
              ('generation',ctypes.c_uint64),('lifetime',ctypes.c_uint64),('lease',ctypes.c_uint64),
              ('handle',ctypes.c_uint16),('local_tcid',ctypes.c_uint8),('remote_tcid',ctypes.c_uint8),
              ('pi',ctypes.c_uint8),('reserved',ctypes.c_uint8*3),('directions',ctypes.c_uint32),('security',ctypes.c_uint32)]
assert ctypes.sizeof(Address)==48


def message():
    nonce=secrets.token_bytes(16);sequence=secrets.randbits(32)
    return b'SLKGRNT1'+nonce+sequence.to_bytes(4,'little')+b'\0'+bytes(nonce[j%16]^((sequence+j)&255) for j in range(32))


def validate(data, expected, reply):
    value=bytearray(expected);value[28]=int(reply)
    if data!=value or len(data)!=61 or data[:8]!=b'SLKGRNT1':raise ValueError('actual opposite application payload mismatch')
    nonce=data[8:24];sequence=int.from_bytes(data[24:28],'little')
    if any(data[29+j]!=nonce[j%16]^((sequence+j)&255) for j in range(32)):
        raise ValueError('application random payload checksum mismatch')


def send(control, value):
    control.sendall(json.dumps(value).encode())


def receive(control):
    data=control.recv(16384)
    if not data:raise RuntimeError('ordinary worker IPC closed')
    value=json.loads(data)
    if value.get('error'):raise RuntimeError('ordinary worker: '+value['error'])
    return value


def credentials():
    values={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if ':' in line}
    return dict(uids=list(map(int,values['Uid'].split())),caps={key:values[key] for key in ['CapEff','CapPrm','CapAmb']})


def pass_channel(control, data, token):
    payload=json.dumps(dict(stage='channel_fd',token=token)).encode()
    if control.sendmsg([payload],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[data.fileno()]))])!=len(payload):
        raise ValueError('partial channel fd transfer')


def take_channel(control, token, family=46):
    """Take exactly one close-on-exec fd; close all delivered fds on rejection."""
    payload,ancillary,flags,_=control.recvmsg(16384,socket.CMSG_SPACE(16*array.array('i').itemsize),socket.MSG_CMSG_CLOEXEC)
    delivered=[]
    try:
        unexpected=False
        for level,kind,value in ancillary:
            if (level,kind)!=(socket.SOL_SOCKET,socket.SCM_RIGHTS):
                unexpected=True;continue
            fds=array.array('i');fds.frombytes(value[:len(value)//fds.itemsize*fds.itemsize]);delivered.extend(fds)
        if unexpected or flags&(socket.MSG_TRUNC|socket.MSG_CTRUNC) or len(delivered)!=1:
            raise ValueError('exactly one complete channel fd required')
        if json.loads(payload)!=dict(stage='channel_fd',token=token):raise ValueError('channel transfer identity mismatch')
        fd=delivered[0]
        if not fcntl.fcntl(fd,fcntl.F_GETFD)&fcntl.FD_CLOEXEC:raise ValueError('transferred fd must be close-on-exec')
        # AF_SPARKLINK does not promise Python's auto-detection getsockname.
        channel=socket.socket(family,socket.SOCK_DGRAM,0,fileno=fd);delivered.clear();return channel
    finally:
        for fd in delivered:os.close(fd)


def intent_receipt(constraint, before, prepared, after):
    return dict(constraint=bytes(constraint).hex(),before_monotonic_ns=before,
                prepared_monotonic_ns=prepared,after_monotonic_ns=after)


def worker(data, control, minimum=0):
    keep={0,1,2,control.fileno()}
    if data is not None:keep.add(data.fileno())
    for name in os.listdir('/proc/self/fd'):
        fd=int(name)
        if fd not in keep:
            try:os.close(fd)
            except OSError as error:
                if error.errno!=errno.EBADF:raise
    if os.geteuid()==0:
        os.setgroups([]);os.setgid(1002);os.setuid(1000)
    identity=credentials()
    if identity['uids']!=[1000]*4 or any(int(v,16) for v in identity['caps'].values()):raise ValueError('ordinary credentials required')
    transfer=None
    if data is None:
        token=secrets.token_hex(16)
        before=dict(stage='awaiting_channel_fd',pid=os.getpid(),credentials=identity,token=token,wall_ns=time.time_ns(),open_fds=[])
        for name in os.listdir('/proc/self/fd'):
            try:target=os.readlink('/proc/self/fd/'+name)
            except FileNotFoundError:continue
            before['open_fds'].append(dict(fd=int(name),target=target))
        if any(v['fd'] not in keep for v in before['open_fds']):raise ValueError('inherited authority fd survived isolation')
        send(control,before);data=take_channel(control,token)
        transfer=dict(before=before,received_wall_ns=time.time_ns(),inode=os.fstat(data.fileno()).st_ino,close_on_exec=True)
    original=data.fileno();duplicate=data.dup();data.close();data=duplicate
    data.setblocking(True)
    try:fcntl.fcntl(original,fcntl.F_GETFD)
    except OSError as error:
        original_errno=error.errno
        if original_errno!=errno.EBADF:raise
    else:raise ValueError('original application socket still open')
    ready=dict(stage='ready',pid=os.getpid(),fd=data.fileno(),original=original,original_errno=original_errno,credentials=identity,wall_ns=time.time_ns())
    if transfer is not None:ready['scm_rights']=transfer
    send(control,ready)
    from sparklink.native import channel_prepare_tx, channel_send_constrained, channel_recv_security
    from sparklink.structs import SleSendConstraint
    last_constraint=None
    def transmit(payload,flags=socket.MSG_NOSIGNAL,receipt=None):
        nonlocal last_constraint
        before=time.monotonic_ns();deadline=before+5_000_000_000
        if receipt is None:
            c=channel_prepare_tx(data.fileno(),minimum,deadline)
        else:
            if receipt.flags!=3 or receipt.security<minimum:
                raise ValueError('original known current reply mechanism required')
            c=SleSendConstraint(version=1,size=48,minimum=receipt.security,
                generation=receipt.generation,lifetime=receipt.lifetime,security_epoch=receipt.security_epoch,
                controller=receipt.controller,handle=receipt.handle,local_tcid=receipt.local_tcid,
                remote_tcid=receipt.remote_tcid,pi=receipt.pi,deadline_monotonic_ns=deadline)
        prepared=time.monotonic_ns()
        if channel_send_constrained(data.fileno(),bytes(payload),c,flags)!=len(payload):
            raise ValueError('partial constrained application admission')
        last_constraint=c
        return intent_receipt(c,before,prepared,time.monotonic_ns())
    def consume():
        payload,context,flags,count=channel_recv_security(data.fileno(),249,socket.MSG_TRUNC)
        if flags or count!=len(payload) or context.flags!=3 or context.security<minimum:
            raise ValueError('complete original scoped RX required')
        return payload,context
    try:
        while True:
            command=receive(control);kind=command['kind']
            if kind=='stop':send(control,dict(stage='stopped'));return
            if kind=='business':
                payload=bytes.fromhex(command['payload']);start=time.time_ns()
                poll=select.poll();poll.register(data,select.POLLOUT)
                events=poll.poll(8000)
                if len(events)!=1 or events[0][1]&(select.POLLERR|select.POLLHUP|select.POLLNVAL) or not events[0][1]&select.POLLOUT:raise ValueError('actual channel Ready required')
                if command['initiator']:
                    intent=transmit(payload)
                    arrived,context=consume();validate(arrived,payload,True)
                    from sparklink.structs import SleSendConstraint
                    requested=SleSendConstraint.from_buffer_copy(bytes.fromhex(intent['constraint']))
                    if context.security_epoch!=requested.security_epoch or context.security<requested.minimum:raise ValueError('reply differs from original TX intent')
                    sent=payload
                else:
                    arrived,context=consume();validate(arrived,payload,False)
                    sent=bytearray(arrived);sent[28]=1
                    intent=transmit(sent,receipt=context)
                send(control,dict(stage='business',initiator=command['initiator'],sent=sent.hex(),received=arrived.hex(),tx_intent=intent,rx_context=bytes(context).hex(),start_wall_ns=start,end_wall_ns=time.time_ns()))
            elif kind=='oneway':
                payload=bytes.fromhex(command['payload']);start=time.time_ns();marker=b'SCPDENY1'+secrets.token_bytes(32)
                if command['initiator']:
                    poll=select.poll();poll.register(data,select.POLLOUT);events=poll.poll(8000)
                    if len(events)!=1 or not events[0][1]&select.POLLOUT or events[0][1]&(select.POLLERR|select.POLLHUP):raise ValueError('TX-only Ready')
                    try:data.recv(249,socket.MSG_DONTWAIT)
                    except OSError as error:denied=error.errno
                    else:raise ValueError('TX-only receive succeeded')
                    intent=transmit(payload)
                    sent=payload.hex();arrived=None
                else:
                    poll=select.poll();poll.register(data,select.POLLOUT)
                    if any(flags&select.POLLOUT for _,flags in poll.poll(0)):raise ValueError('RX-only advertised writable')
                    try:data.send(marker,socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL)
                    except OSError as error:denied=error.errno
                    else:raise ValueError('RX-only send succeeded')
                    arrived,context=consume();validate(arrived,payload,False);arrived=arrived.hex();sent=None
                if denied!=errno.EACCES:raise ValueError('exact forbidden direction EACCES required')
                send(control,dict(stage='oneway',initiator=command['initiator'],sent=sent,received=arrived,direction_errno=denied,denied_marker=marker.hex(),start_wall_ns=start,end_wall_ns=time.time_ns()))
            elif kind=='prime':
                payloads=[bytes.fromhex(v) for v in command['payloads']]
                if len(payloads)!=4 or len(set(payloads))!=4:raise ValueError('four distinct bounded real priming messages required')
                values=[];before=time.time_ns()
                for payload in payloads:
                    validate(payload,payload,False)
                    if command['sender']:
                        transmit(payload)
                        values.append(payload.hex())
                    else:
                        arrived=data.recv(249,socket.MSG_TRUNC);validate(arrived,payload,False);values.append(arrived.hex())
                send(control,dict(stage='primed',sender=command['sender'],values=values,pid=os.getpid(),fd=data.fileno(),start_wall_ns=before,end_wall_ns=time.time_ns()))
            elif kind=='tx_status':
                from sparklink.native import channel_tx_status
                send(control,dict(stage='tx_status',pid=os.getpid(),fd=data.fileno(),value=bytes(channel_tx_status(data.fileno())).hex(),wall_ns=time.time_ns()))
            elif kind=='block':
                prefix=command.get('prefix');admission={}
                if prefix is not None:
                    prefix=bytes.fromhex(prefix)
                    if len(prefix)!=2042 or prefix[:8]!=b'SLKREV01':raise ValueError('bounded random revocation PDU required')
                    admission=dict(admission_before_wall_ns=time.time_ns(),admission_before_monotonic_ns=time.monotonic_ns())
                    admission['tx_intent']=transmit(prefix)
                    admission.update(admission_after_wall_ns=time.time_ns(),admission_after_monotonic_ns=time.monotonic_ns())
                if command.get('sample_before_block'):
                    if prefix is None:raise ValueError('TX observation requires bounded original PDU')
                    from sparklink.native import channel_tx_status
                    time.sleep(.25)
                    admission['pre_block_tx_status']=bytes(channel_tx_status(data.fileno())).hex()
                    admission['pre_block_tx_status_wall_ns']=time.time_ns()
                send(control,dict(stage='armed',pid=os.getpid(),fd=data.fileno(),wall_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),prefix=prefix.hex() if prefix is not None else None,**admission))
                start=time.time_ns();start_mono=time.monotonic_ns()
                try:
                    arrived=data.recv(249)
                    raise ValueError('withdrawn blocking RX returned application bytes/EOF: '+arrived.hex())
                except OSError as error:
                    send(control,dict(stage='blocked_denied',errno=error.errno,start_wall_ns=start,end_wall_ns=time.time_ns(),start_monotonic_ns=start_mono,end_monotonic_ns=time.monotonic_ns()))
            elif kind=='deny':
                marker=bytes.fromhex(command['marker']);values={}
                for name,call in [('send',lambda:data.send(marker,socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL)),('recv',lambda:data.recv(249,socket.MSG_DONTWAIT))]:
                    try:call()
                    except OSError as error:values[name]=error.errno
                    else:raise ValueError('old socket operation succeeded after withdrawal')
                poll=select.poll();poll.register(data,select.POLLIN|select.POLLOUT);events=poll.poll(0)
                if last_constraint is None:raise ValueError('original admitted intent required before withdrawal')
                typed={};calls={}
                for name,call in [('prepare',lambda:channel_prepare_tx(data.fileno(),minimum,time.monotonic_ns()+1_000_000_000)),
                                  ('submit',lambda:channel_send_constrained(data.fileno(),marker,last_constraint,socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL))]:
                    calls[name+'_before_monotonic_ns']=time.monotonic_ns()
                    try:call()
                    except OSError as error:typed[name]=error.errno
                    else:raise ValueError('old constrained operation succeeded after withdrawal')
                    calls[name+'_after_monotonic_ns']=time.monotonic_ns()
                send(control,dict(stage='denied',errors=values,poll=events[0][1] if events else 0,marker=marker.hex(),
                                  tx_intent_denial=dict(errors=typed,calls=calls,constraint=bytes(last_constraint).hex()),wall_ns=time.time_ns()))
            else:raise ValueError('unknown worker command')
    except BaseException as error:
        send(control,dict(error=str(error),error_type=type(error).__name__))
        raise
    finally:data.close()


class Gate:
    def __init__(self, observers, snapshots, leases, index, record, save, directional=False, scm_rights=False, security=0):
        from ws73_protected_grant import requirement
        if security!=requirement(record):raise ValueError('requested protected binding and original prelude must agree')
        self.directional=directional
        self.index=index;self.record=record;self.save=save;self.children=[];self.parents=[]
        self.row=dict(status='STARTING',index=index,owners=[],workers=[],business=[],tx_constraint_required=not directional,start_wall_ns=time.time_ns())
        if directional:self.row.update(directional=True,bind_rejections=[])
        if scm_rights:self.row.update(scm_rights=True,transfers=[])
        record['channel_grant']=self.row;save();channels=[];pairs=[]
        libc=ctypes.CDLL(None,use_errno=True);libc.bind.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint];libc.bind.restype=ctypes.c_int
        try:
            for n,observer in enumerate(observers):
                table=observer.link_snapshot()
                if table.flags!=1 or table.count!=1:raise ValueError('one actual physical link per controller')
                link=table.links[0];address=Address(family=46,controller=n,version=2,generation=snapshots[n].generation,lifetime=link.lifetime,lease=leases[n],handle=link.handle,local_tcid=31,remote_tcid=31,pi=241,directions=(1 if n==index else 2) if directional else 3,security=security)
                data=socket.socket(46,socket.SOCK_DGRAM|socket.SOCK_CLOEXEC,0)
                channels.append(data)
                data.setsockopt(socket.SOL_SOCKET,socket.SO_RCVTIMEO,struct.pack('ll',8,0))
                data.setsockopt(socket.SOL_SOCKET,socket.SO_SNDTIMEO,struct.pack('ll',8,0))
                if directional:
                    for directions,requested_security,expected in [(0,0,errno.EINVAL),(4,0,errno.EINVAL),(3,1,errno.EACCES),(3,2,errno.EACCES),(3,3,errno.EOPNOTSUPP)]:
                        bad=Address.from_buffer_copy(bytes(address));bad.directions=directions;bad.security=requested_security
                        with socket.socket(46,socket.SOCK_DGRAM|socket.SOCK_CLOEXEC,0) as rejected:
                            ret=libc.bind(rejected.fileno(),ctypes.byref(bad),ctypes.sizeof(bad));actual=ctypes.get_errno()
                        if ret!=-1 or actual!=expected:raise ValueError('unsupported/invalid scoped bind did not reject')
                        self.row['bind_rejections'].append(dict(controller=n,input=bytes(bad).hex(),errno=actual,wall_ns=time.time_ns()));save()
                if libc.bind(data.fileno(),ctypes.byref(address),ctypes.sizeof(address)):
                    error=ctypes.get_errno();raise OSError(error,os.strerror(error))
                self.row['owners'].append(dict(index=n,generation=snapshots[n].generation,lifetime=link.lifetime,handle=link.handle,lease=leases[n],address=bytes(address).hex()))
                pairs.append(socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET))
            for n in range(2):
                pid=os.fork()
                if pid==0:
                    try:worker(None if scm_rights else channels[n],pairs[n][1],minimum=security);os._exit(0)
                    except BaseException as error:
                        try:send(pairs[n][1],dict(error=str(error),error_type=type(error).__name__))
                        except OSError:pass
                        os._exit(1)
                self.children.append(pid);parent=pairs[n][0];parent.settimeout(12);self.parents.append(parent)
                pairs[n][1].close()
            if scm_rights:
                for n,parent in enumerate(self.parents):
                    before=receive(parent)
                    if before['stage']!='awaiting_channel_fd' or before['pid']!=self.children[n]:raise ValueError('isolated ordinary transfer receiver required')
                    start=time.time_ns();inode=os.fstat(channels[n].fileno()).st_ino
                    pass_channel(parent,channels[n],before['token'])
                    channels[n].close()
                    self.row['transfers'].append(dict(before=before,inode=inode,start_wall_ns=start,broker_fd_closed_wall_ns=time.time_ns()))
                    save()
            for data in channels:data.close()
            for n,parent in enumerate(self.parents):
                value=receive(parent)
                if value['stage']!='ready' or value['pid']!=self.children[n]:raise ValueError('actual worker startup receipt required')
                self.row['workers'].append(value)
            self.row['status']='WORKERS_READY';save()
        except BaseException:
            for data in channels:data.close()
            self.close();raise

    def exchange(self, label):
        rows=[]
        for initiator in ([self.index] if self.directional else [self.index,1-self.index]):
            payload=message();start=time.time_ns()
            for n,parent in enumerate(self.parents):send(parent,dict(kind='oneway' if self.directional else 'business',initiator=n==initiator,payload=payload.hex()))
            receipts=[receive(parent) for parent in self.parents]
            for n,value in enumerate(receipts):
                if value['stage']!=('oneway' if self.directional else 'business') or value['initiator']!=(n==initiator):raise ValueError('actual business worker receipt required')
            row=dict(label=label,initiator=initiator,payload=payload.hex(),applications=receipts,start_wall_ns=start,end_wall_ns=time.time_ns());rows.append(row)
            self.row['business'].append(row);self.save()
        return rows

    def prime(self):
        from ws73_management_setup import decode
        from sparklink.structs import SleChannelTxStatus
        payloads=[message().hex() for _ in range(4)]
        row=dict(payloads=payloads,start_wall_ns=time.time_ns(),applications=[],source_pool_samples=[])
        self.row['priming']=row;self.save()
        for n,parent in enumerate(self.parents):send(parent,dict(kind='prime',sender=n==self.index,payloads=payloads))
        row['applications']=[receive(parent) for parent in self.parents];self.save()
        deadline=time.monotonic()+.5
        while True:
            send(self.parents[self.index],dict(kind='tx_status'));value=receive(self.parents[self.index]);row['source_pool_samples'].append(value);self.save()
            tx=decode(SleChannelTxStatus,value['value'])
            if (tx.outstanding,tx.connection_debt,tx.flags,tx.queued,tx.busy,tx.active_pdu_bytes,tx.active_pdu_offset)==(4,4,0,0,0,0,0):break
            if time.monotonic()>deadline:raise TimeoutError('actual four unpaid priming credits before long PDU')
            time.sleep(.005)
        row.update(end_wall_ns=time.time_ns(),status='PRIMING_RECEIPTS_RECORDED');self.save()

    def arm(self, sample_before_block=False):
        request=dict(kind='block')
        if sample_before_block:request['sample_before_block']=True
        if 'ws73.channel_revoke_prefix=1' in Path('/proc/cmdline').read_text().split():
            payload=b'SLKREV01'+secrets.token_bytes(2034)
            request['prefix']=payload.hex();self.row['revoke_prefix']=dict(payload=payload.hex(),admission_before_wall_ns=time.time_ns())
        send(self.parents[self.index],request);value=receive(self.parents[self.index])
        if 'revoke_prefix' in self.row:
            if value.get('prefix')!=request['prefix']:raise ValueError('original worker prefix admission required')
            self.row['revoke_prefix']['admission_after_wall_ns']=value.get('admission_after_wall_ns',value['wall_ns'])
        if value['stage']!='armed':raise ValueError('blocking worker arm receipt required')
        samples=[];deadline=time.monotonic()+2
        while len(samples)<2:
            path=Path(f'/proc/{value["pid"]}');raw=(path/'syscall').read_text().split();wchan=(path/'wchan').read_text().strip();state=(path/'stat').read_text().rsplit(')',1)[1].split()[0]
            if raw and raw[0]=='45' and int(raw[1],0)==value['fd'] and state=='S' and wchan in ['__skb_wait_for_more_packets','schedule_timeout']:
                samples.append(dict(syscall=45,fd=value['fd'],state=state,wchan=wchan,wall_ns=time.time_ns()))
            if time.monotonic()>deadline:raise TimeoutError('actual x86_64 recvfrom kernel blocking witness: '+wchan)
            time.sleep(.03)
        self.row['armed']=value;self.row['blocking_witness']=samples;self.row['status']='BLOCKED_IN_KERNEL';self.save()

    def denied(self, label):
        marker=b'GRNTDENY'+secrets.token_bytes(32)
        send(self.parents[self.index],dict(kind='deny',marker=marker.hex()));value=receive(self.parents[self.index])
        if value['stage']!='denied' or value['errors']!={'send':errno.EACCES,'recv':errno.EACCES} or value['poll']&(select.POLLIN|select.POLLOUT) or value['poll']&(select.POLLERR|select.POLLHUP)!=(select.POLLERR|select.POLLHUP):raise ValueError('old authority must be EACCES and ERR/HUP without readable/writable')
        self.row[label]=value;self.save()

    def withdrawn(self):
        if self.directional:
            self.denied('after_withdrawal');return
        value=receive(self.parents[self.index]);self.row['blocked_result']=value;self.save()
        if value['stage']!='blocked_denied' or value['errno']!=errno.EACCES:raise ValueError('actual blocked RX must wake with EACCES')
        self.denied('after_withdrawal')

    def successor(self, observer, generation):
        from sparklink.native import NativeAdapter
        with NativeAdapter(self.index,generation) as writer:
            lease=writer.acquire_management(1)
            if lease<=self.row['owners'][self.index]['lease']:raise ValueError('strict successor token required')
            self.row['successor']=dict(lease=lease,generation=generation,start_wall_ns=time.time_ns());self.save()
            self.denied('after_successor')
            writer.release_management(lease,1)
        if observer.management_status().state!=0:raise ValueError('successor quiet cleanup must settle Free')
        self.row['successor']['end_wall_ns']=time.time_ns();self.row['status']='GRANT_GATE_PASS';self.row['end_wall_ns']=time.time_ns();self.save()

    def close(self):
        for n,parent in enumerate(self.parents):
            try:
                send(parent,dict(kind='stop'));receive(parent)
            except (OSError,RuntimeError):pass
            finally:parent.close()
        for pid in self.children:
            deadline=time.monotonic()+1
            while True:
                actual,status=os.waitpid(pid,os.WNOHANG)
                if actual:
                    if status:raise RuntimeError('ordinary worker failed: '+str(status))
                    break
                if time.monotonic()>deadline:
                    os.kill(pid,signal.SIGKILL);os.waitpid(pid,0);raise TimeoutError('worker termination')
                time.sleep(.01)
        self.children=[];self.parents=[]


def verify(row, outer):
    i=outer['index']
    from ws73_protected_grant import requirement
    security=requirement(outer)
    if row['status']!='GRANT_GATE_PASS' or row['index']!=i or len(row['owners'])!=2 or len(row['workers'])!=2:raise ValueError('complete Grant gate required')
    for n,owner in enumerate(row['owners']):
        address=Address.from_buffer_copy(bytes.fromhex(owner['address']))
        if (owner['index']!=n or owner['lease']!=outer['leases'][n] or owner['generation']<=0 or owner['lifetime']<=0
                or (address.family,address.controller,address.version,address.flags)!=(46,n,2,0)
                or (address.generation,address.lifetime,address.lease,address.handle)!=(owner['generation'],owner['lifetime'],owner['lease'],owner['handle'])
                or (address.local_tcid,address.remote_tcid,address.pi,address.directions,address.security)!=(31,31,241,(1 if n==i else 2) if row.get('directional',False) else 3,security) or any(address.reserved)):
            raise ValueError('exact original v2 socket identity/lease required')
    for n,worker_row in enumerate(row['workers']):
        if worker_row['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in worker_row['credentials']['caps'].values()) or worker_row['original']==worker_row['fd'] or worker_row['original_errno']!=errno.EBADF or worker_row['pid']<=0:raise ValueError('actual ordinary duplicated socket required')
        if row.get('scm_rights',False):
            transfer=row['transfers'][n];received=worker_row['scm_rights'];before=transfer['before']
            if received['before']!=before or before['pid']!=worker_row['pid'] or before['credentials']!=worker_row['credentials'] or received['inode']!=transfer['inode'] or not received['close_on_exec'] or not before['wall_ns']<transfer['start_wall_ns']<=transfer['broker_fd_closed_wall_ns'] or received['received_wall_ns']<transfer['start_wall_ns'] or received['received_wall_ns']>worker_row['wall_ns']:raise ValueError('actual SCM_RIGHTS lineage required')
            if len(before['token'])!=32 or any(v['fd'] not in [0,1,2] and not v['target'].startswith('socket:[') for v in before['open_fds']) or len([v for v in before['open_fds'] if v['fd']>2])!=1:raise ValueError('only IPC fd may survive before transfer')
    if not row.get('directional',False):
        samples=row['blocking_witness'];armed=row['armed'];result=row['blocked_result']
        if armed['pid']!=row['workers'][i]['pid'] or armed['fd']!=row['workers'][i]['fd']:raise ValueError('original ordinary worker must be the blocked process')
        if len(samples)!=2 or any(v['syscall']!=45 or v['fd']!=armed['fd'] or v['state']!='S' or v['wchan'] not in ['__skb_wait_for_more_packets','schedule_timeout'] for v in samples):raise ValueError('two actual blocked syscall witnesses required')
        if not armed['wall_ns']<samples[0]['wall_ns']<samples[1]['wall_ns']<outer['release_before_wall_ns']<=outer['release_after_wall_ns']<row['end_wall_ns']:raise ValueError('blocked before original authority withdrawal required')
        if result['stage']!='blocked_denied' or result['errno']!=errno.EACCES or result['end_wall_ns']<outer['release_before_wall_ns'] or result['end_wall_ns']-result['start_wall_ns']>=8_000_000_000:raise ValueError('actual finite blocked RX withdrawal error required')
    successor=row['successor']
    if successor['generation']!=row['owners'][i]['generation'] or successor['lease']<=row['owners'][i]['lease']:raise ValueError('same registration strictly new lease required')
    for key in ['after_withdrawal','after_successor']:
        value=row[key]
        if value['errors']!={'send':errno.EACCES,'recv':errno.EACCES} or value['poll']!=select.POLLERR|select.POLLHUP or not bytes.fromhex(value['marker']).startswith(b'GRNTDENY'):raise ValueError('actual old-fd denial required')
    multiplier=1 if row.get('directional',False) else 2
    expected=['before']*multiplier+(['after_first_control_close']*multiplier if outer['case']=='dup' else [])
    if [v['label'] for v in row['business']]!=expected:raise ValueError('complete actual business around duplicate control close required')
    nonces=set()
    for value in row['business']:
        payload=bytes.fromhex(value['payload'])
        if payload[8:24] in nonces:raise ValueError('fresh per-business nonce required')
        nonces.add(payload[8:24]);validate(payload,payload,False)
        if len(value['applications'])!=2:raise ValueError('two actual business application receipts required')
        for n,app in enumerate(value['applications']):
            initiator=n==value['initiator']
            if row.get('directional',False):
                if app['stage']!='oneway' or app['direction_errno']!=errno.EACCES or (app['sent'] is None)!= (not initiator) or (app['received'] is None)!=initiator:raise ValueError('actual one-way and denied opposite direction required')
                validate(bytes.fromhex(app['sent'] if initiator else app['received']),payload,False)
                continue
            validate(bytes.fromhex(app['sent']),payload,not initiator);validate(bytes.fromhex(app['received']),payload,initiator)
    return row


def verify_intents(row, outer):
    """Current real fd calls; not a proof of kernel locks, credit or firmware truth."""
    from sparklink.structs import SleSendConstraint, SleMessageSecurity, SleConnectionSecurity
    from ws73_management_setup import decode
    from ws73_protected_grant import requirement
    floor=requirement(outer);count=0
    def scope(v,owner):
        return (v.controller,v.generation,v.lifetime,v.handle,v.local_tcid,v.remote_tcid,v.pi)==(owner['index'],owner['generation'],owner['lifetime'],owner['handle'],31,31,241)
    def intent(record,owner):
        c=decode(SleSendConstraint,record['constraint'])
        if c.version!=1 or c.size!=48 or c.reserved or not scope(c,owner) or not c.security_epoch or not floor<=c.minimum<=2:raise ValueError('exact original scoped restrictive TX required')
        before,prepared,after=[record[k] for k in ['before_monotonic_ns','prepared_monotonic_ns','after_monotonic_ns']]
        if not 0<before<=prepared<=after<c.deadline_monotonic_ns or c.deadline_monotonic_ns!=before+5_000_000_000:raise ValueError('one original absolute5s intent before admission required')
        # A new basic-Grant request may observe a newer epoch; this does not
        # renew the cached original intent or an epoch-bound protected Grant.
        if floor:
            observed=decode(SleConnectionSecurity,outer['protected_security']['after'][owner['index']])
            if c.security_epoch!=observed.security_epoch:raise ValueError('intent must match actual installed native epoch')
        return c
    for b in row['business']:
        for n,a in enumerate(b['applications']):
            c=intent(a['tx_intent'],row['owners'][n]);m=decode(SleMessageSecurity,a['rx_context'])
            if m.version!=1 or m.size!=40 or m.flags!=3 or not scope(m,row['owners'][n]) or m.security_epoch!=c.security_epoch or not c.minimum<=m.security<=2:raise ValueError('actual original RX scope/epoch/grade required')
            if c.minimum!=(floor if b['initiator']==n else m.security):raise ValueError('initiator minimum and original reply observation required')
            count+=1
    armed=row.get('armed',{});prefix=armed.get('tx_intent')
    if 'revoke_prefix' in row:
        if prefix is None:raise ValueError('actual long PDU admission must carry TX intent')
        c=intent(prefix,row['owners'][outer['index']])
        if c.minimum!=floor or not armed['admission_before_monotonic_ns']<=prefix['before_monotonic_ns']<=prefix['after_monotonic_ns']<=armed['admission_after_monotonic_ns']:raise ValueError('prefix cannot refresh original admission deadline')
        original=prefix['constraint']
    else:original=None
    if 'data_deadline' in outer:receipts=[outer['data_deadline'][k] for k in ['old_fd_before_release','old_fd_after_release']]
    elif 'data_link_down' in outer:receipts=[outer['data_link_down']['old_fd']]
    else:receipts=[row[k] for k in ['after_withdrawal','after_successor'] if k in row]
    for a in receipts:
        d=a['tx_intent_denial']
        calls=d['calls'];pb,pa,sb,sa=[calls[k+'_monotonic_ns'] for k in ['prepare_before','prepare_after','submit_before','submit_after']]
        if not 0<pb<=pa<=sb<=sa:raise ValueError('same-clock before/after actual denial syscalls required')
        raw=a['errors']['send']
        if raw not in [errno.EACCES,errno.ESTALE,errno.ENOTCONN]:raise ValueError('original raw denial contract required')
        expected=raw
        if 'data_deadline' in outer:
            cached=decode(SleSendConstraint,d['constraint'])
            # Actual production sl_prepare_tx rejects inactive Session first;
            # sl_tx_access checks the expired constraint before later sl_admit.
            if raw!=errno.ENOTCONN or sb<cached.deadline_monotonic_ns:raise ValueError('original Session timeout before cached expired-intent retry required')
            expected=errno.ETIMEDOUT
        if d['errors']!={'prepare':raw,'submit':expected}:raise ValueError('fresh prepare and unchanged cached intent need their exact phase-specific errors')
        if original is not None and d['constraint']!=original:raise ValueError('withdrawal retry must use the original admitted intent unchanged')
    return dict(status='ORIGINAL_TX_INTENT_LIFECYCLE_RECEIPTS_CORROBORATED',business_sends=count,prefix_admission=bool(prefix),late_refusals=len(receipts)*2,expired_intent_refusals=len(receipts) if 'data_deadline' in outer else 0,
                scope='Actual ordinary fd prepare/send/recv plus existing USB/hold/Down or deadline oracle;local syscall records are not carried on USB,no actual kernel concurrency/credit-reuse/ref-drain proof')


def business_evidence(row, outer, capture):
    """Shared actual application TX/opposite RX evidence, independent of closure."""
    if row.get('tx_constraint_required'):verify_intents(row,outer)
    sdus=reassemble_acb(capture);legs=[]
    for business in row['business']:
        for n,application in enumerate(business['applications']):
            owner=outer['usb'][n];identity=row['owners'][n]
            for key,direction in [('sent','out'),('received','in')]:
                if application[key] is None:continue
                payload=bytes.fromhex(application[key]);frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                matches=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device']) and p['handle']==identity['handle'] and p['direction']==direction and p['data']==frame.hex() and business['start_wall_ns']<=p['wall_ns']<=business['end_wall_ns']]
                if len(matches)!=1:raise CaptureError('one actual application USB TX/opposite RX per business leg required')
                legs.append(matches[0])
    return sdus,legs


def corroborate(row, outer, capture):
    verify(row,outer);sdus,legs=business_evidence(row,outer,capture)
    for key in ['after_withdrawal','after_successor']:
        marker=row[key]['marker']
        if any(marker in p['data'] for p in sdus):raise CaptureError('withdrawn application marker reached wire')
    if row.get('directional',False):
        for business in row['business']:
            for application in business['applications']:
                if any(application['denied_marker'] in p['data'] for p in sdus):raise CaptureError('forbidden direction marker reached wire')
        if len(row['bind_rejections'])!=10:raise CaptureError('all invalid/protected bind requests required')
        for n in range(2):
            values=row['bind_rejections'][n*5:n*5+5]
            if [(Address.from_buffer_copy(bytes.fromhex(v['input'])).directions,Address.from_buffer_copy(bytes.fromhex(v['input'])).security,v['errno']) for v in values]!=[(0,0,22),(4,0,22),(3,1,13),(3,2,13),(3,3,95)]:raise CaptureError('exact invalid/protected request errors')
    proof=dict(status='REAL_DIRECTIONAL_GRANT_USB_CORROBORATED' if row.get('directional',False) else 'REAL_BLOCKED_RX_GRANT_USB_CORROBORATED' ,scope='pre-daemon two real devices/independent Managed Files; ordinary socket dup, witnessed blocked RX, control release/final close/dup, successor old-fd denial; peer radio continuity in outer gate',business_round_trips=0 if row.get('directional',False) else len(row['business']),legs=legs,blocked_rx_acceptance=not row.get('directional',False),daemon_death_acceptance=False,inflight_usb_acceptance=False,natural_recovery_acceptance=False,full_grant_complete=False)

    if row.get('directional',False):
        proof['one_way_deliveries']=len(row['business'])
        proof['scope']='pre-daemon two real devices/independent Managed Files; UID1000/caps0 TX-only to RX-only actual one-way validation, forbidden direction EACCES, protected/invalid bind rejection, revoked/successor stale-fd denial; no business round-trip or blocked RX claim'
    if row.get('scm_rights',False):proof['scm_rights_acceptance']=True
    if row.get('revoke_prefix'):
        from ws73_revoke_prefix import corroborate as prefix_corroborate
        proof['begun_revoke']=prefix_corroborate(row,outer,capture)
    return proof
