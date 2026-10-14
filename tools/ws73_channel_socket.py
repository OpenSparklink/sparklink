# SPDX-License-Identifier: GPL-2.0-only
"""Two ordinary applications; independent two-end USB/CMTC/NOCP proof."""
from contextlib import ExitStack
from pathlib import Path
import re
import subprocess
import time
from ws73_capture import CaptureError, reassemble_acb


def credentials(pid):
    fields = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    value = dict(uids=list(map(int, fields['Uid'].split())),
                 capabilities={k: fields[k].strip() for k in ['CapEff', 'CapPrm', 'CapAmb']})
    if value['uids'] != [1000]*4 or any(int(v,16) for v in value['capabilities'].values()):
        raise CaptureError('each socket application must be uid1000 without capabilities')
    return value


def execute(run, phase):
    row = dict(phase=len(run.data['connection_control']['phases'])-1, owners=phase['typed_objects'],
               rounds=getattr(run.args,'channel_socket_rounds',4), message_bytes=getattr(run.args,'channel_socket_bytes',61),
               boundary_check=getattr(run.args,'channel_socket_boundaries',False), channel_info_required=True, ssap_exchange_required=True, session_start_wall_ns=phase['start_wall_ns'], ssap_receipts=[], status='RUNNING', start_wall_ns=time.time_ns(), applications=[])
    run.data.setdefault('channel_socket', []).append(row); run.save()
    processes=[];files=ExitStack()
    try:
        for entry in row['owners']:
            receipt=run.command([str(run.args.slctl),'--adapter',entry['owner']['path'],'ssap-info',entry['object']['path']],10,collection='ssap_exchange')
            if receipt['exit']: raise CaptureError('actual SMTC ExchangeInfo failed')
            row['ssap_receipts'].append(receipt);run.save()
        from ws73_ssap_value import execute as ssap_value_execute
        ssap_value_execute(run,row)
        # Both binds must occur during the same live connection. Never synthesize RX.
        for role, entry in [('peer', row['owners'][1]), ('initiator', row['owners'][0])]:
            args=[str(run.args.slctl),'--adapter',entry['owner']['path'],
                  'channel-peer' if role=='peer' else 'channel-roundtrip',entry['object']['path'],str(row['rounds'])]
            if row['message_bytes']!=61 or row['boundary_check']:args.append(str(row['message_bytes']))
            if row['boundary_check']:args.append('boundaries')
            app=dict(role=role,args=args,start_wall_ns=time.time_ns())
            row['applications'].append(app);run.save()
            stdout=run.output/f'channel-{row["phase"]}-{role}.stdout'
            stderr=run.output/f'channel-{row["phase"]}-{role}.stderr'
            app['output_files']=[str(stdout),str(stderr)]
            proc=subprocess.Popen(args,stdout=files.enter_context(stdout.open('xb')),stderr=files.enter_context(stderr.open('xb')))
            processes.append((proc,app));app['pid']=proc.pid
            app['credentials']=credentials(proc.pid);run.save()
        deadline=time.monotonic()+row['rounds']*10+5
        for proc,app in processes:
            proc.wait(timeout=max(.001,deadline-time.monotonic()))
            app['stdout'],app['stderr']=[Path(p).read_text() for p in app['output_files']]
            app.update(exit=proc.returncode,end_wall_ns=time.time_ns());run.save()
            if proc.returncode:raise CaptureError('actual socket application failed: '+app['stderr'])
        for app in row['applications']:
            if app['stdout'].count('NativeChannelDup: original_closed=1 duplicate_live=1') != 1 or app['stdout'].count('NativeChannelLastClose: same_lifetime_reopen=NotSupported') != 1:
                raise CaptureError('actual duplicate/last-close/reopen rejection receipts required')
        row['session_binding_lifecycle'] = 'DUP_ALIVE_LAST_CLOSE_REBIND_UNSUPPORTED'
        application_frames(row)
        # Passive VFS checks use current full records; old read/stats never
        # re-enter the producer. Older packages have no such test artifact and
        # retain their original qualification, not a new copy-gate receipt.
        probe = Path(run.args.slctl).parent/'controller-event-copy-probe'
        if not probe.is_file() and Path('/scratch-root-uuid').is_file():
            probe = Path('/bin/controller-event-copy-probe')
        if probe.is_file():
            for entry in row['owners']:
                owner = entry['owner']
                position = run.command([str(run.args.slctl),'--adapter',owner['path'],'events'],
                                       10, collection='controller_event_positions')
                expected = rf'^ControllerEventPosition: index={owner["index"]} generation={owner["generation"]} sequence=(\d+)$'
                if position['exit'] or len(re.findall(expected,position['stdout'],re.M)) != 1:
                    raise CaptureError('actual canonical event-position interface failed')
                legacy_probe = Path(run.args.slctl).parent/'protocol-state-probe'
                if not legacy_probe.is_file() and Path('/scratch-root-uuid').is_file():
                    legacy_probe = Path('/bin/protocol-state-probe')
                if legacy_probe.is_file():
                    refused = run.command([str(legacy_probe),str(owner['index'])],10,collection='protocol_state_refusals')
                    expected_refusal = 'PROTOCOL_STATE_REFUSAL_PASS: uid=1000 cases=83 unchanged=83 mixed_stats=ENOTTY'
                    if refused['exit'] or refused['stdout'].strip()!=expected_refusal:
                        raise CaptureError('actual retired protocol-state rejection failed')
                summary = run.command([str(run.args.slctl),'--adapter',owner['path'],'stats'],
                                      10,collection='controller_link_summaries')
                pattern = rf'^ControllerLinkSummary: index={owner["index"]} generation={owner["generation"]} revision=([1-9]\d*) event_sequence=([1-9]\d*) connections=1$'
                if summary['exit'] or len(re.findall(pattern,summary['stdout'],re.M)) != 1:
                    raise CaptureError('actual validated physical link summary failed')
                receipt = run.command([str(probe),str(owner['index']),str(owner['generation'])],
                                      10, collection='controller_event_copy')
                expected = f'CONTROLLER_EVENT_COPY_PASS: uid=1000 index={owner["index"]} generation={owner["generation"]} partial=4 retry=4 peer_replay=4 readiness_preserved=4 removed_read=1 removed_stats=2'
                if receipt['exit'] or receipt['stdout'].strip() != expected:
                    raise CaptureError('actual ControllerEvent copy/alias/replay gate failed')
        registry_probe = Path(run.args.slctl).parent/'genl-registry-probe'
        if not registry_probe.is_file() and Path('/scratch-root-uuid').is_file():
            registry_probe = Path('/bin/genl-registry-probe')
        if registry_probe.is_file():
            receipt = run.command([str(registry_probe)],10,collection='genl_registry')
            expected = r'^GENL_REGISTRY_PASS: uid=1000 count=\d+ version=2 retired=31 extra_attr=1 no_multicast=1 count_preserved=1$'
            if receipt['exit'] or not re.fullmatch(expected,receipt['stdout'].strip()):
                raise CaptureError('actual registry-only netlink/retired mutation gate failed')
        row['status']='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING'
    except BaseException as error:
        row.update(status='FAIL',error=str(error),error_type=type(error).__name__);raise
    finally:
        for proc,app in processes:
            if proc.poll() is None:proc.kill()
            if 'exit' not in app:
                proc.wait()
                app['stdout'],app['stderr']=[Path(p).read_text() for p in app['output_files']];app.update(exit=proc.returncode,end_wall_ns=time.time_ns())
        files.close()
        row['end_wall_ns']=time.time_ns();run.save()


def rejected_frames(row):
    result=[]
    for app in row['applications']:
        values=re.findall(r'^NativeChannelRejected: length=(\d+) errno=(\d+) bytes=([0-9a-f]+)$',app['stdout'],re.M)
        if row.get('boundary_check',False):
            if [int(v[0]) for v in values]!=[250,253,254,255] or len(values)!=app['stdout'].count('NativeChannelRejected:'):
                raise CaptureError('all original length boundary rejection receipts required')
            for length,error,raw in values:
                data=bytes.fromhex(raw)
                if int(error)!=90 or len(data)!=int(length) or data[:8]!=b'SLKBOUND':raise CaptureError('exact x86_64 EMSGSIZE and original rejected bytes required')
                result.append(data)
        elif values or 'NativeChannelRejected:' in app['stdout']:
            raise CaptureError('boundary receipts without explicit requested boundary check')
    if len({v.hex() for v in result})!=len(result):raise CaptureError('fresh rejected boundary payloads required')
    return result


def channel_info_receipts(row):
    if not row.get('channel_info_required', False):
        return []  # Historical records never gain this qualification.
    owners = row['owners']; result = []
    for app in row['applications']:
        entry = owners[0 if app['role'] == 'initiator' else 1]
        expected = (entry['owner']['index'], entry['owner']['generation'],
                    entry['object']['lifetime'], entry['object']['handle'], 31, 31, 241)
        values = re.findall(r'^NativeChannelInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local=(\d+) remote=(\d+) pi=(\d+) mtu=(\d+) mps=(\d+) mode=(\d+) directions=(\d+)$', app['stdout'], re.M)
        copies = re.findall(r'^NativeChannelInfoCopy: partial=(\d+) retry=1 unchanged=1$',app['stdout'],re.M)
        if len(values) != 1 or len(copies) != 1 or not 1 <= int(copies[0]) <= 16:
            raise CaptureError('original channel capability and guarded copy receipts required')
        fields = tuple(map(int, values[0]))
        if fields[:7] != expected or fields[-2:] != (0, 3) or min(fields[7:9]) < row.get('message_bytes',61):
            raise CaptureError('channel capabilities disagree with original owner/lifetime/mode/budget')
        result.append(dict(role=app['role'], fields=fields, partial_copy_bytes=int(copies[0])))
    return result


def application_frames(row):
    rounds=row['rounds'];message_bytes=row.get('message_bytes',61)
    if type(message_bytes) is not int or not 29<=message_bytes<=249:raise CaptureError('supported basic channel message size required')
    if type(rounds) is not int or not 1<=rounds<=20:raise CaptureError('finite original round count required')
    apps={a['role']:a for a in row['applications']}
    if set(apps)!={'peer','initiator'} or len(row['applications'])!=2:
        raise CaptureError('two original application processes and bounded rounds required')
    for role,a in apps.items():
        if a['exit'] or a['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in a['credentials']['capabilities'].values()):
            raise CaptureError('successful ordinary applications required')
        if re.findall(r'^NativeChannelOpened: role=(\w+) rounds=(\d+)$',a['stdout'],re.M)!=[(role,str(rounds))]:
            raise CaptureError('one original socket opening per application required')
        declared=re.findall(r'^NativeChannelMessageSize: bytes=(\d+)$',a['stdout'],re.M)
        if declared and declared!=[str(message_bytes)] or (message_bytes!=61 and not declared):raise CaptureError('original application message size must match request')
    rejected_frames(row)
    channel_info_receipts(row)
    def rows(role,marker,elapsed=False):
        pattern=rf'^{marker}: sequence=(\d+) '+(r'elapsed_ms=(\d+) ' if elapsed else '')+r'bytes=([0-9a-f]+)$'
        values=re.findall(pattern,apps[role]['stdout'],re.M)
        if len(values)!=rounds or apps[role]['stdout'].count(marker+':')!=rounds:raise CaptureError('all original application receipts required')
        if [int(v[0]) for v in values]!=list(range(rounds)):raise CaptureError('ordered unique sequence required')
        if elapsed and any(int(v[1])>=10000 for v in values):raise CaptureError('ten second round trip deadline')
        return [bytes.fromhex(v[-1]) for v in values]
    sent=rows('initiator','NativeChannelSent');received=rows('peer','NativeChannelReceived')
    reply=rows('peer','NativeChannelReply');returned=rows('initiator','NativeChannelRoundTrip',True)
    nonces=set();wire_sequences=set()
    for i,data in enumerate(sent):
        if len(data)!=message_bytes or data[:8]!=b'SLKSOCK1' or data[28]!=0:
            raise CaptureError('exact random application protocol required')
        if data[8:24] in nonces:raise CaptureError('fresh nonce per round required')
        nonces.add(data[8:24])
        wire_sequence=int.from_bytes(data[24:28],'little')
        if wire_sequence in wire_sequences:raise CaptureError('fresh random wire sequence required')
        wire_sequences.add(wire_sequence)
        if any(data[29+j] != data[8+j%16]^((wire_sequence+j)&255) for j in range(message_bytes-29)):raise CaptureError('application payload mismatch')
        expected=bytearray(data);expected[28]=1
        if received[i]!=data or reply[i]!=expected or returned[i]!=expected:
            raise CaptureError('actual peer validation and exact reply required')
    return sent,reply


def corroborate(run,capture):
    rows=run.get('channel_socket')
    if rows is None or len(rows)!=2:raise CaptureError('two connection direction phases required')
    sdus=reassemble_acb(capture);proofs=[];all_nonces=set();all_sequences=set()
    for n,row in enumerate(rows):
        if row['phase']!=n or row['status']!='ORDINARY_CHANNEL_SOCKET_EVIDENCE_PENDING':raise CaptureError('original successful socket phase required')
        sent,replies=application_frames(row)
        rejected=rejected_frames(row)
        for raw in rejected:
            if any(raw.hex() in p['data'] and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns'] for p in sdus):raise CaptureError('rejected message reached USB data path')
        owners=row['owners']
        if len(owners)!=2 or owners[0]['owner']['index']==owners[1]['owner']['index']:raise CaptureError('independent controller identities required')
        def matched(entry,direction,payload,session=False):
            owner,obj=entry['owner'],entry['object']
            if owner['generation']!=obj['generation'] or not obj['lifetime']:raise CaptureError('canonical generation/lifetime required')
            found=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device'])
                   and p['handle']==obj['handle'] and p['direction']==direction and p['data']==payload.hex()
                   and (row.get('session_start_wall_ns',row['start_wall_ns']) if session else row['start_wall_ns'])<=p['wall_ns']<=row['end_wall_ns']]
            if len(found)!=1:raise CaptureError('one exact USB TX/opposite RX per message required')
            return found[0]
        ssap_values=[];ssap_credit={0:0,1:0}
        if row.get('ssap_value_required',False):
            from ws73_ssap_value import corroborate as ssap_value_corroborate
            def value_matched(entry,direction,payload,item):
                owner,obj=entry['owner'],entry['object']
                found=[p for p in sdus if (p['bus'],p['device'])==(owner['bus'],owner['device']) and p['handle']==obj['handle'] and p['direction']==direction and p['data']==payload.hex() and item['start_wall_ns']<=p['wall_ns']<=item['end_wall_ns']]
                if len(found)!=1:raise CaptureError('one exact SSAP value USB leg in original command interval required')
                result=found.pop(0);sdus.remove(result);return result
            ssap_values,ssap_credit=ssap_value_corroborate(row,value_matched)
            ssap_discovery=[]
            if row.get('ssap_discovery_required',False):
                from ws73_ssap_discovery import corroborate as discovery_corroborate
                ssap_discovery,discovery_credit=discovery_corroborate(row,value_matched)
                for key in ssap_credit:ssap_credit[key]+=discovery_credit[key]
            if any(p['data'].startswith('0a00') and len(p['data'])>=10 and int(p['data'][8:10],16) in ((1,4,5,6,7,8,9,13,14) if row.get('ssap_discovery_required',False) else (8,9,13,14)) and row['start_wall_ns']<=p['wall_ns']<=row['end_wall_ns'] for p in sdus):raise CaptureError('extra/unattributed SSAP value USB packet')
        legs=[]
        for sequence,(data,reply) in enumerate(zip(sent,replies)):
            if data[8:24] in all_nonces:raise CaptureError('random nonce reused across direction phases')
            all_nonces.add(data[8:24])
            wire_sequence=int.from_bytes(data[24:28],'little')
            if wire_sequence in all_sequences:raise CaptureError('wire sequence reused across direction phases')
            all_sequences.add(wire_sequence)
            for sender,receiver,payload in [(owners[0],owners[1],data),(owners[1],owners[0],reply)]:
                frame=b'\x1f\0'+(len(payload)+1).to_bytes(2,'little')+b'\xf1'+payload
                legs.append(dict(sequence=sequence,tx=matched(sender,'out',frame),rx=matched(receiver,'in',frame)))
        # Each endpoint sends one capability request, one response, the recorded number of business PDUs.
        capabilities=[]
        for sender,receiver in [owners,owners[::-1]]:
            query=bytes.fromhex('0200080001010400e2000000')
            response=bytes.fromhex('0200100002010c00e20000000000f900f9000101')
            capabilities.append(dict(request_tx=matched(sender,'out',query,session=row.get('ssap_exchange_required',False)),request_rx=matched(receiver,'in',query,session=row.get('ssap_exchange_required',False)),
                                     response_tx=matched(sender,'out',response,session=row.get('ssap_exchange_required',False)),response_rx=matched(receiver,'in',response,session=row.get('ssap_exchange_required',False))))
            owner,obj=sender['owner'],sender['object']
            completed=[e for e in capture['native_events'] if e['event']==9 and (e['bus'],e['device'])==(owner['bus'],owner['device'])
                       and row.get('session_start_wall_ns',row['start_wall_ns'])<=e['wall_ns']<=row['end_wall_ns']]
            if any(len(bytes.fromhex(e['params']))!=3 or int.from_bytes(bytes.fromhex(e['params'])[:2],'little')!=obj['handle'] for e in completed):raise CaptureError('exact actual completion handle required')
            if sum(bytes.fromhex(e['params'])[2] for e in completed)!=row['rounds']+(4 if row.get('ssap_exchange_required',False) else 2)+ssap_credit[owners.index(sender)]:raise CaptureError('exact actual completed packet count per controller required')
        ssap=[]
        if row.get('ssap_exchange_required',False):
            if len(row.get('ssap_receipts',[]))!=2:raise CaptureError('both original daemon SSAP receipts required')
            for source,owner in zip(row['ssap_receipts'],owners):
                pattern=r'^SsapExchangeInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) local_mtu=(\d+) negotiated_mtu=(\d+) request=([0-9a-f]+) peer_reply=([0-9a-f]+) peer_request=([0-9a-f]+) response=([0-9a-f]+)$'
                fields=re.findall(pattern,source['stdout'],re.M)
                if source['exit'] or len(fields)!=1:raise CaptureError('one original successful SSAP observation required')
                value=fields[0];o=owner['owner'];obj=owner['object']
                if tuple(map(int,value[:4]))!=(o['index'],o['generation'],obj['lifetime'],obj['handle']):raise CaptureError('SSAP owner/lifetime mismatch')
                mtu=int(value[4]);negotiated=int(value[5]);req,rsp,peer_req,response=map(bytes.fromhex,value[6:])
                expected_req=bytes([2,3])+mtu.to_bytes(2,'little')+bytes([1,2]);expected_rsp=bytes([3,3])+mtu.to_bytes(2,'little')+bytes([1,2])
                if (req,rsp,peer_req,response)!=(expected_req,expected_rsp,expected_req,expected_rsp) or negotiated!=mtu:raise CaptureError('exact real basic ExchangeInfo required')
                receiver=next(e for e in owners if e!=owner)
                ssap_legs=[]
                for payload in [req,response]:
                    frame=bytes([10,0])+len(payload).to_bytes(2,'little')+payload
                    ssap_legs.append(dict(tx=matched(owner,'out',frame,True),rx=matched(receiver,'in',frame,True)))
                ssap.append(dict(receipt=source,wire=ssap_legs))
        entry = dict(phase=n,owners=owners,capabilities=capabilities,legs=legs)
        if row.get("channel_info_required",False): entry["channel_info"] = channel_info_receipts(row)
        if row.get("ssap_exchange_required",False): entry["ssap_exchange"] = ssap
        if row.get("ssap_value_required",False): entry["ssap_values"] = ssap_values
        if row.get("ssap_update_local_rejection_required",False): entry["ssap_local_update_rejection"] = row["unsupported_incoming"]
        if row.get("ssap_discovery_required",False): entry["ssap_discovery"] = ssap_discovery
        proofs.append(entry)
    proof=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=sum(row['rounds'] for row in rows),proofs=proofs,
                scope=f"uid1000/caps0 two applications; CMTC/basic CUTC31 PI241; {rows[0].get('message_bytes',61)}-byte peer-validated payload; both USB/HCC/A3 ends and NOCP",
                long_pdu_acceptance=False,credit_exhaustion_acceptance=False,four_device_acceptance=False)
    if any(row.get('boundary_check',False) for row in rows):
        proof['application_boundary_rejections']=sum(len(rejected_frames(row)) for row in rows)
        proof['application_message_bytes']=rows[0].get('message_bytes',61)
        proof['dtap_pdu_bytes']=proof['application_message_bytes']+5
    return proof
