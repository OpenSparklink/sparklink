# SPDX-License-Identifier: GPL-2.0-only
"""Scratch-VM actual slkd death with retained ordinary business fds.
Init alone kills/reaps its daemon and launches the successor. Both controllers
share that daemon, so both leases must withdraw; no independent-owner claim.
"""
import argparse
import copy
import errno
import json
import os
from pathlib import Path
import secrets
import select
import shlex
import socket
import struct
import subprocess
import sys
import time
from ws73_channel_grant import Gate, worker, send, receive, pass_channel, validate
from ws73_daemon_channel_fd import receive as receive_fd
from ws73_north_star import Run, daemon_identity, file_record
from ws73_connection_control import execute, result
from ws73_capture import CaptureError, reassemble_acb
FOLDER=Path('/evidence/channel-daemon-crash')


def wait_file(path, seconds=45):
    deadline=time.monotonic()+seconds
    while not path.exists():
        if time.monotonic()>deadline:raise TimeoutError('finite phase wait: '+str(path))
        time.sleep(.02)
    return json.loads(path.read_text())


class ControlRun(Run):
    def command(self, command, timeout, **kwargs):
        if kwargs.get('child_credentials') is not None:
            return super().command(command, timeout, **kwargs)
        wrapped=['/bin/su','ws73','-s','/bin/sh','-c','exec '+shlex.join(command)]
        row=super().command(wrapped,timeout,**kwargs)
        row['execution_args']=row['args'];row['args']=command;self.save();return row

    def connected_gate(self, phase):
        gate=object.__new__(Gate)
        gate.directional=False;gate.index=self.args.index;gate.record=self.data;gate.save=self.save
        gate.children=[];gate.parents=[]
        entries=sorted(phase['typed_objects'],key=lambda v:v['owner']['index'])
        gate.row=dict(status='STARTING',index=gate.index,owners=entries,workers=[],transfers=[],business=[])
        self.data['daemon_channel']=gate.row;self.save()
        try:
            for n,entry in enumerate(entries):
                ipc=FOLDER/f'fd-{n}.sock'
                with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver:
                    receiver.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
                    receiver.bind(str(ipc));ipc.chmod(0o666);receiver.settimeout(12)
                    token=secrets.token_hex(16)
                    command=['/bin/su','ws73','-s','/bin/sh','-c','exec '+shlex.join(['/bin/ws73-channel-fd-probe',entry['object']['path'],str(ipc),token])]
                    with (FOLDER/f'probe-{n}.stdout').open('xb') as out,(FOLDER/f'probe-{n}.stderr').open('xb') as err:
                        proc=subprocess.Popen(command,stdout=out,stderr=err,close_fds=True)
                        try:
                            data,receipt=receive_fd(receiver,token=token,path=entry['object']['path'],daemon_pid=self.args.slkd_pid,daemon_owner=self.data['bus_before']['owner'])
                            proc.wait(timeout=12)
                            if proc.returncode:raise ValueError('actual D-Bus fd client failed')
                        finally:
                            if proc.poll() is None:proc.kill();proc.wait()
                ipc.unlink()
                with data:
                    data.setsockopt(socket.SOL_SOCKET,socket.SO_RCVTIMEO,struct.pack('ll',8,0))
                    parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
                    pid=os.fork()
                    if pid==0:
                        try:worker(None,child);os._exit(0)
                        except BaseException as error:
                            try:send(child,dict(error=str(error),error_type=type(error).__name__))
                            except OSError:pass
                            os._exit(1)
                    child.close();parent.settimeout(12);gate.parents.append(parent);gate.children.append(pid)
                    before=receive(parent)
                    if before['stage']!='awaiting_channel_fd' or before['pid']!=pid:raise ValueError('isolated worker required')
                    pass_channel(parent,data,before['token'])
                ready=receive(parent)
                if ready['stage']!='ready' or ready['scm_rights']['inode']!=receipt['inode']:raise ValueError('same actual daemon channel fd required')
                gate.row['workers'].append(ready)
                gate.row['transfers'].append(dict(client=receipt,client_exit=proc.returncode,client_reaped_wall_ns=time.time_ns(),before=before,broker_closed=True,controller=entry['owner']['index']))
                self.save()
            gate.exchange('before')
            from ws73_ssap_daemon_restart import pending_write
            def die(deadline):
                gate.arm()
                if time.monotonic_ns() >= deadline:raise TimeoutError('original WRITE deadline before death arm')
                self.data['armed_wall_ns']=time.time_ns();self.save()
                (FOLDER/'armed.json').write_text(json.dumps(dict(pid=self.args.slkd_pid,wall_ns=self.data['armed_wall_ns']))+'\n')
                death=wait_file(FOLDER/'death.json',max(0,(deadline-time.monotonic_ns())/1e9))
                if time.monotonic_ns() >= deadline or death['pid']!=self.args.slkd_pid or death['status']!=137 or Path(f'/proc/{death["pid"]}').exists():raise ValueError('original daemon must be killed/reaped within WRITE deadline')
                self.data['death']=death;self.save()
            with pending_write(self, phase, die) as observe_successor:
                death=self.data['death']
                from sparklink.native import NativeAdapter
                deadline=time.monotonic()+7;observations=[]
                while True:
                    rows=[]
                    for entry in entries:
                        o=entry['owner']
                        with NativeAdapter(o['index'],o['generation']) as observer:
                            snapshot=observer.snapshot();management=observer.management_status();links=observer.link_snapshot()
                            rows.append(dict(index=o['index'],generation=snapshot.generation,flags=snapshot.flags,error=snapshot.error,snapshot=bytes(snapshot).hex(),management=bytes(management).hex(),links=bytes(links).hex(),state=management.state,management_flags=management.flags,link_flags=links.flags,link_count=links.count,wall_ns=time.time_ns()))
                    observations.append(rows);self.data['cleanup_observations']=observations;self.save()
                    if all(v['flags']==1 and not v['error'] and v['state']==0 and not v['management_flags'] and v['link_flags']==1 and not v['link_count'] for v in rows):break
                    if time.monotonic()>deadline:raise TimeoutError('daemon-owned cleanup did not become Free')
                    time.sleep(.02)
                blocked=receive(gate.parents[gate.index]);gate.row['blocked_result']=blocked;self.save()
                if blocked['stage']!='blocked_denied' or blocked['errno'] not in [errno.EACCES,errno.ESTALE]:raise ValueError('actual withdrawal or ended physical lifetime required')
                gate.denied('after_withdrawal')
                other=1-gate.index;send(gate.parents[other],dict(kind='deny',marker=(b'GRNTDENY'+secrets.token_bytes(32)).hex()))
                gate.row['other_after_death']=receive(gate.parents[other]);self.save()
                (FOLDER/'free.json').write_text(json.dumps(dict(pid=death['pid'],wall_ns=time.time_ns()))+'\n')
                successor=wait_file(FOLDER/'successor.json',90)
                self.args.slkd_pid=successor['pid'];self.pid=daemon_identity(self.args.slkd_pid)
                self.data['successor']=successor;self.data['daemon_after']=self.pid;self.data['bus_after']=self.bus_identity()
                self.data['after_ready']=[self.ready(o['owner']['port']) for o in entries];self.save()
                gate.denied('after_successor')
                send(gate.parents[other],dict(kind='deny',marker=(b'GRNTDENY'+secrets.token_bytes(32)).hex()))
                gate.row['other_after_successor']=receive(gate.parents[other]);self.save()
                observe_successor()
            self.successor_business(phase)
            gate.row.update(status='DAEMON_CHANNEL_GATE_PASS',end_wall_ns=time.time_ns());self.save()
        finally:gate.close()

    def successor_business(self, old_phase):
        args=copy.copy(self.args)
        args.output=FOLDER/'successor-business'
        args.channel_daemon_crash=False;args.channel_socket_verify=True
        args.ssap_owned_verify=True;args.ssap_sdk_write_provider_verify=True
        successor=ControlRun(args)
        successor.pid=self.pid
        successor.data.update(daemon_before=self.pid,slctl=file_record('/bin/slctl'))
        successor.data['initial']=self.data['after_ready']
        def barrier(stage, phase):
            if stage!='linked':return
            from ws73_connection_objects import reject_old
            phase['predecessor_object_rejections']=[reject_old(successor,x,'daemon-predecessor') for x in old_phase['typed_objects']]
        successor.connection_barrier=barrier
        self.data['successor_business']=successor.data
        try:execute(successor,*self.data['after_ready'])
        finally:self.save()


def run(args):
    if os.geteuid()!=0 or not Path('/scratch-root-uuid').is_file() or Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU' or 'ws73.channel_daemon_crash=1' not in Path('/proc/cmdline').read_text().split():raise ValueError('explicit private VM only')
    sys.path.insert(0,'/usr/share/sparklink/python')
    FOLDER.mkdir(exist_ok=False)
    args.output=FOLDER/'control';args.slctl=Path('/bin/slctl');args.artifact=[];args.connection_advertising='negotiable-t';args.channel_daemon_crash=True
    control=ControlRun(args)
    control.data.update(daemon_restart_version=2,scope='actual common slkd owner death with ordinary retained business fds',daemon_before=daemon_identity(args.slkd_pid),slctl=file_record('/bin/slctl'),fd_probe=file_record('/bin/ws73-channel-fd-probe'),automatic_recovery_acceptance=False,physical_acceptance=False,independent_owner_isolation=False)
    control.pid=control.data['daemon_before'];control.data['bus_before']=control.bus_identity()
    try:
        owners=[control.ready(f'1-{n+1}') for n in range(2)];control.data['initial']=owners
        caller=next(v for v in owners if v['index']==args.index);peer=next(v for v in owners if v['index']!=args.index)
        execute(control,caller,peer)
        control.data.update(status='REAL_DAEMON_CHANNEL_DEATH_EVIDENCE_PENDING',end_wall_ns=time.time_ns());control.save()
        verify(control.data);print('WS73_TARGET_DAEMON_CHANNEL_PASS',flush=True)
    except BaseException as error:
        control.data.update(status='FAIL',error=str(error));control.save();raise


def verify(record):
    if record['status']!='REAL_DAEMON_CHANNEL_DEATH_EVIDENCE_PENDING' or record['automatic_recovery_acceptance'] or record['physical_acceptance'] or record['independent_owner_isolation']:raise CaptureError('common owner death scope required')
    g=record['daemon_channel'];i=g['index']
    if g['status']!='DAEMON_CHANNEL_GATE_PASS' or len(g['workers'])!=2 or len(g['transfers'])!=2 or len(g['business'])!=2:raise CaptureError('complete retained fd gate required')
    if record['bus_before']['pid']!=record['death']['pid'] or record['death']['status']!=137 or record['bus_after']['pid']!=record['successor']['pid'] or record['bus_before']['owner']==record['bus_after']['owner'] or record['death']['pid']==record['successor']['pid']:raise CaptureError('distinct reaped daemon successor required')
    armed=g['armed'];samples=g['blocking_witness'];blocked=g['blocked_result']
    if armed['pid']!=g['workers'][i]['pid'] or armed['fd']!=g['workers'][i]['fd'] or len(samples)!=2 or not armed['wall_ns']<samples[0]['wall_ns']<samples[1]['wall_ns']<record['armed_wall_ns']<=record['death']['before_wall_ns']:raise CaptureError('blocked application must precede SIGKILL')
    if any(v['syscall']!=45 or v['fd']!=armed['fd'] or v['state']!='S' or v['wchan'] not in ['__skb_wait_for_more_packets','schedule_timeout'] for v in samples) or blocked['errno'] not in [errno.EACCES,errno.ESTALE] or blocked['end_wall_ns']<record['death']['before_wall_ns'] or blocked['end_wall_ns']-blocked['start_wall_ns']>=8_000_000_000:raise CaptureError('finite actual EACCES wake required')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bindings/python'))
    from sparklink.structs import SleControllerSnapshot, SleManagementQuery, SleLinkSnapshot
    rows=record['cleanup_observations'][-1]
    if len(rows)!=2:raise CaptureError('two actual cleanup observers required')
    for n,row in enumerate(rows):
        owner=g['owners'][n]['owner']
        snapshot=SleControllerSnapshot.from_buffer_copy(bytes.fromhex(row['snapshot']))
        management=SleManagementQuery.from_buffer_copy(bytes.fromhex(row['management']))
        links=SleLinkSnapshot.from_buffer_copy(bytes.fromhex(row['links']))
        if (snapshot.version!=1 or management.version!=1 or links.version!=1 or snapshot.generation!=owner['generation'] or snapshot.dev_index!=owner['index'] or snapshot.flags!=1 or snapshot.profile!=1 or snapshot.error or management.generation!=owner['generation'] or any(getattr(management,k) for k in ['lease','mode','state','flags','error','status','opcode','reserved']) or links.generation!=owner['generation'] or links.dev_index!=owner['index'] or links.flags!=1 or links.count or links.error or row['wall_ns']<record['death']['reaped_wall_ns'] or row['wall_ns']>record['successor']['wall_ns']):raise CaptureError('canonical Ready/Free/empty physical table before successor required')
    for n,(w,t) in enumerate(zip(g['workers'],g['transfers'])):
        c=t['client'];before=t['before']
        if c['daemon_pid']!=record['death']['pid'] or c['daemon_owner']!=record['bus_before']['owner'] or c['path']!=g['owners'][n]['object']['path'] or c['kernel_sender']!=dict(pid=c['pid'],uid=1000,gid=1002) or t['client_exit'] or not t['broker_closed'] or w['scm_rights']['inode']!=c['inode'] or w['scm_rights']['before']!=before or before['pid']!=w['pid'] or w['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in w['credentials']['caps'].values()) or w['original_errno']!=errno.EBADF or w['original']==w['fd']:raise CaptureError('reaped real D-Bus ordinary fd delegation required')
    for key in ['after_withdrawal','after_successor','other_after_death','other_after_successor']:
        v=g[key]
        if v['stage']!='denied' or v['errors']!={'send':errno.EACCES,'recv':errno.EACCES} or v['poll']!=select.POLLERR|select.POLLHUP:raise CaptureError('both old grants must stay revoked')
    for old,new in zip(g['owners'],record['after_ready']):
        o=old['owner']
        if any(o[k]!=new[k] for k in ['index','generation','address','port','bus','device']):raise CaptureError('replacement must not reset registration')
    if {b['initiator'] for b in g['business']}!={0,1} or len({b['payload'][16:48] for b in g['business']})!=2:raise CaptureError('both directions and fresh nonces required')
    for b in g['business']:
        if b['label']!='before' or b['end_wall_ns']>record['armed_wall_ns']:raise CaptureError('business must finish before death')
        for n,a in enumerate(b['applications']):
            validate(bytes.fromhex(a['sent']),bytes.fromhex(b['payload']),n!=b['initiator']);validate(bytes.fromhex(a['received']),bytes.fromhex(b['payload']),n==b['initiator'])
    version=record.get('daemon_restart_version',1)
    if type(version)is not int or version not in (1,2):raise CaptureError('supported daemon gate version required')
    if version==2:
        from ws73_ssap_daemon_restart import verify as write_verify
        write_verify(record)
        fresh=record['successor_business']
        if fresh['connection_control']['status']!='CONNECTION_CONTROL_EVIDENCE_PENDING' or len(fresh['channel_socket'])!=2:raise CaptureError('two real fresh connection business phases required')
        old={x['object']['path'] for x in g['owners']}
        for phase in fresh['connection_control']['phases']:
            if len(phase.get('predecessor_object_rejections',[]))!=2 or old & {x['object']['path']for x in phase['typed_objects']}:raise CaptureError('old lifetime must not revive on successor')
            from ws73_connection_objects import refusal
            for old_entry, rejection in zip(record['connection_control']['phases'][0]['typed_objects'],phase['predecessor_object_rejections']):
                if rejection['object']!=old_entry['object'] or rejection['owner']!=old_entry['owner'] or not rejection['info_commands']:raise CaptureError('same predecessor object refusal required')
                for command in rejection['info_commands']+[rejection['disconnect_command']]:
                    receipt=fresh['commands'][command];refusal(receipt)
                    if receipt['args'][-1]!=old_entry['object']['path'] or receipt['start_wall_ns']<record['successor']['wall_ns']:raise CaptureError('actual successor refusal of old object required')
    return record


def corroborate(record,capture):
    verify(record);g=record['daemon_channel'];sdus=reassemble_acb(capture);legs=[]
    for b in g['business']:
        for n,app in enumerate(b['applications']):
            entry=g['owners'][n];o=entry['owner'];handle=entry['object']['handle']
            for key,direction in [('sent','out'),('received','in')]:
                data=bytes.fromhex(app[key]);frame=b'\x1f\0'+(len(data)+1).to_bytes(2,'little')+b'\xf1'+data
                matches=[p for p in sdus if (p['bus'],p['device'],p['handle'],p['direction'],p['data'])==(o['bus'],o['device'],handle,direction,frame.hex()) and b['start_wall_ns']<=p['wall_ns']<=b['end_wall_ns']]
                if len(matches)!=1:raise CaptureError('one opposite USB TX/RX leg required')
                legs.append(matches[0])
    for key in ['after_withdrawal','after_successor','other_after_death','other_after_successor']:
        if any(g[key]['marker'] in p['data'] for p in sdus):raise CaptureError('revoked payload reached USB')
    phase=record['connection_control']['phases'][0];command=record['commands'][phase['connect_command']];terminal=result(command['stdout'],phase['caller'],1)
    if terminal!=phase['connect'] or command['exit']:raise CaptureError('original Create terminal required')
    up=[]
    for entry in g['owners']:
        o=entry['owner'];v=entry['object'];events=[e for e in capture['native_events'] if e['event'] in [0x15,0x1401] and (e['bus'],e['device'])==(o['bus'],o['device']) and command['start_wall_ns']<=e['wall_ns']<=record['armed_wall_ns']]
        if len(events)!=1:raise CaptureError('one original physical Up per controller required')
        body=bytes.fromhex(events[0]['params'])
        if len(body)<11 or body[0] or (int.from_bytes(body[1:3],'little'),body[3],body[4],body[5:11].hex())!=(v['handle'],v['role'],v['address_type'],v['address'].replace(':','').lower()):raise CaptureError('actual Up must match retained fd object')
        up.extend(events)
    down=[]
    if g['blocked_result']['errno']==errno.ESTALE:
        owner=g['owners'][g['index']]['owner'];handle=g['owners'][g['index']]['object']['handle']
        down=[e for e in capture['native_events'] if e['event'] in [5,0x1405] and (e['bus'],e['device'])==(owner['bus'],owner['device']) and record['death']['before_wall_ns']<=e['wall_ns']<=g['blocked_result']['end_wall_ns'] and len(bytes.fromhex(e['params']))>=4 and bytes.fromhex(e['params'])[0]==0 and int.from_bytes(bytes.fromhex(e['params'])[1:3],'little')==handle]
        if len(down)!=1:raise CaptureError('ESTALE wake requires actual matching physical Down before wake')
    proof=dict(status='REAL_DAEMON_CHANNEL_DEATH_USB_CORROBORATED',first_blocked_errno=g['blocked_result']['errno'],physical_down_before_wake=down,business_round_trips=2,legs=legs,original_up=up,actual_daemon_death=True,successor_does_not_renew_old_fd=True,common_owner_both_leases_withdrawn=True,independent_device_business_isolation=False,physical_acceptance=False,automatic_recovery_acceptance=False,full_grant_complete=False)
    if record.get('daemon_restart_version',1)==2:
        from ws73_ssap_daemon_restart import corroborate as write_corroborate
        from ws73_connection_control import corroborate as connection_corroborate
        from ws73_connection_objects import corroborate as objects_corroborate
        from ws73_channel_socket import corroborate as channel_corroborate
        fresh=record['successor_business']
        links=connection_corroborate(fresh,capture)
        proof.update(daemon_restart_version=2,pending_write=write_corroborate(record,capture),
            successor_connections=links,successor_objects=objects_corroborate(fresh,capture,links),
            successor_data=channel_corroborate(fresh,capture))
    return proof



if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--slkd-pid',type=int,required=True);p.add_argument('--index',type=int,choices=[0,1],default=0);run(p.parse_args())
