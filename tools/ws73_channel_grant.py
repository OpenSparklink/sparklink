# SPDX-License-Identifier: GPL-2.0-only
"""Real scratch-VM socket Grant gate, layered on established File cleanup.
IPC carries application commands/receipts, never substitutes for radio RX.
Children close all inherited control fds before dropping to UID1000/caps0.
"""
import ctypes
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


def worker(data, control):
    keep={0,1,2,data.fileno(),control.fileno()}
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
    original=data.fileno();duplicate=data.dup();data.close();data=duplicate
    data.setblocking(True)
    try:fcntl.fcntl(original,fcntl.F_GETFD)
    except OSError as error:
        original_errno=error.errno
        if original_errno!=errno.EBADF:raise
    else:raise ValueError('original application socket still open')
    send(control,dict(stage='ready',pid=os.getpid(),fd=data.fileno(),original=original,original_errno=original_errno,credentials=identity,wall_ns=time.time_ns()))
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
                    if data.send(payload,socket.MSG_NOSIGNAL)!=len(payload):raise ValueError('partial application PDU')
                    arrived=data.recv(249,socket.MSG_TRUNC);validate(arrived,payload,True)
                    sent=payload
                else:
                    arrived=data.recv(249,socket.MSG_TRUNC);validate(arrived,payload,False)
                    sent=bytearray(arrived);sent[28]=1
                    if data.send(sent,socket.MSG_NOSIGNAL)!=len(sent):raise ValueError('partial application reply')
                send(control,dict(stage='business',initiator=command['initiator'],sent=sent.hex(),received=arrived.hex(),start_wall_ns=start,end_wall_ns=time.time_ns()))
            elif kind=='block':
                send(control,dict(stage='armed',pid=os.getpid(),fd=data.fileno(),wall_ns=time.time_ns()))
                start=time.time_ns()
                try:
                    arrived=data.recv(249)
                    raise ValueError('withdrawn blocking RX returned application bytes/EOF: '+arrived.hex())
                except OSError as error:
                    send(control,dict(stage='blocked_denied',errno=error.errno,start_wall_ns=start,end_wall_ns=time.time_ns()))
            elif kind=='deny':
                marker=bytes.fromhex(command['marker']);values={}
                for name,call in [('send',lambda:data.send(marker,socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL)),('recv',lambda:data.recv(249,socket.MSG_DONTWAIT))]:
                    try:call()
                    except OSError as error:values[name]=error.errno
                    else:raise ValueError('old socket operation succeeded after withdrawal')
                poll=select.poll();poll.register(data,select.POLLIN|select.POLLOUT);events=poll.poll(0)
                send(control,dict(stage='denied',errors=values,poll=events[0][1] if events else 0,marker=marker.hex(),wall_ns=time.time_ns()))
            else:raise ValueError('unknown worker command')
    except BaseException as error:
        send(control,dict(error=str(error),error_type=type(error).__name__))
        raise
    finally:data.close()


class Gate:
    def __init__(self, observers, snapshots, leases, index, record, save):
        self.index=index;self.record=record;self.save=save;self.children=[];self.parents=[]
        self.row=dict(status='STARTING',index=index,owners=[],workers=[],business=[],start_wall_ns=time.time_ns())
        record['channel_grant']=self.row;save();channels=[];pairs=[]
        libc=ctypes.CDLL(None,use_errno=True);libc.bind.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint];libc.bind.restype=ctypes.c_int
        try:
            for n,observer in enumerate(observers):
                table=observer.link_snapshot()
                if table.flags!=1 or table.count!=1:raise ValueError('one actual physical link per controller')
                link=table.links[0];address=Address(family=46,controller=n,version=2,generation=snapshots[n].generation,lifetime=link.lifetime,lease=leases[n],handle=link.handle,local_tcid=31,remote_tcid=31,pi=241,directions=3)
                data=socket.socket(46,socket.SOCK_DGRAM|socket.SOCK_CLOEXEC,0)
                channels.append(data)
                data.setsockopt(socket.SOL_SOCKET,socket.SO_RCVTIMEO,struct.pack('ll',8,0))
                data.setsockopt(socket.SOL_SOCKET,socket.SO_SNDTIMEO,struct.pack('ll',8,0))
                if libc.bind(data.fileno(),ctypes.byref(address),ctypes.sizeof(address)):
                    error=ctypes.get_errno();raise OSError(error,os.strerror(error))
                self.row['owners'].append(dict(index=n,generation=snapshots[n].generation,lifetime=link.lifetime,handle=link.handle,lease=leases[n],address=bytes(address).hex()))
                pairs.append(socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET))
            for n in range(2):
                pid=os.fork()
                if pid==0:
                    try:worker(channels[n],pairs[n][1]);os._exit(0)
                    except BaseException:os._exit(1)
                self.children.append(pid);parent=pairs[n][0];parent.settimeout(12);self.parents.append(parent)
                pairs[n][1].close()
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
        for initiator in [self.index,1-self.index]:
            payload=message();start=time.time_ns()
            for n,parent in enumerate(self.parents):send(parent,dict(kind='business',initiator=n==initiator,payload=payload.hex()))
            receipts=[receive(parent) for parent in self.parents]
            for n,value in enumerate(receipts):
                if value['stage']!='business' or value['initiator']!=(n==initiator):raise ValueError('actual business worker receipt required')
            row=dict(label=label,initiator=initiator,payload=payload.hex(),applications=receipts,start_wall_ns=start,end_wall_ns=time.time_ns());rows.append(row)
            self.row['business'].append(row);self.save()
        return rows

    def arm(self):
        send(self.parents[self.index],dict(kind='block'));value=receive(self.parents[self.index])
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
    if row['status']!='GRANT_GATE_PASS' or row['index']!=i or len(row['owners'])!=2 or len(row['workers'])!=2:raise ValueError('complete Grant gate required')
    for n,owner in enumerate(row['owners']):
        address=Address.from_buffer_copy(bytes.fromhex(owner['address']))
        if (owner['index']!=n or owner['lease']!=outer['leases'][n] or owner['generation']<=0 or owner['lifetime']<=0
                or (address.family,address.controller,address.version,address.flags)!=(46,n,2,0)
                or (address.generation,address.lifetime,address.lease,address.handle)!=(owner['generation'],owner['lifetime'],owner['lease'],owner['handle'])
                or (address.local_tcid,address.remote_tcid,address.pi,address.directions,address.security)!=(31,31,241,3,0) or any(address.reserved)):
            raise ValueError('exact original v2 socket identity/lease required')
    for n,worker_row in enumerate(row['workers']):
        if worker_row['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in worker_row['credentials']['caps'].values()) or worker_row['original']==worker_row['fd'] or worker_row['original_errno']!=errno.EBADF or worker_row['pid']<=0:raise ValueError('actual ordinary duplicated socket required')
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
    expected=['before']*2+(['after_first_control_close']*2 if outer['case']=='dup' else [])
    if [v['label'] for v in row['business']]!=expected:raise ValueError('complete actual business around duplicate control close required')
    nonces=set()
    for value in row['business']:
        payload=bytes.fromhex(value['payload'])
        if payload[8:24] in nonces:raise ValueError('fresh per-business nonce required')
        nonces.add(payload[8:24]);validate(payload,payload,False)
        if len(value['applications'])!=2:raise ValueError('two actual business application receipts required')
        for n,app in enumerate(value['applications']):
            initiator=n==value['initiator'];validate(bytes.fromhex(app['sent']),payload,not initiator);validate(bytes.fromhex(app['received']),payload,initiator)
    return row


def corroborate(row, outer, capture):
    verify(row,outer);sdus=reassemble_acb(capture);legs=[]
    for business in row['business']:
        for n,application in enumerate(business['applications']):
            owner=outer['usb'][n];identity=row['owners'][n]
            for key,direction in [('sent','out'),('received','in')]:
                payload=bytes.fromhex(application[key]);frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                matches=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device']) and p['handle']==identity['handle'] and p['direction']==direction and p['data']==frame.hex() and business['start_wall_ns']<=p['wall_ns']<=business['end_wall_ns']]
                if len(matches)!=1:raise CaptureError('one actual application USB TX/opposite RX per business leg required')
                legs.append(matches[0])
    for key in ['after_withdrawal','after_successor']:
        marker=row[key]['marker']
        if any(marker in p['data'] for p in sdus):raise CaptureError('withdrawn application marker reached wire')
    return dict(status='REAL_BLOCKED_RX_GRANT_USB_CORROBORATED',scope='pre-daemon two real devices/independent Managed Files; ordinary socket dup, witnessed blocked RX, control release/final close/dup, successor old-fd denial; peer radio continuity in outer gate',business_round_trips=len(row['business']),legs=legs,blocked_rx_acceptance=True,daemon_death_acceptance=False,inflight_usb_acceptance=False,natural_recovery_acceptance=False,full_grant_complete=False)
