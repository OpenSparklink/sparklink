# SPDX-License-Identifier: GPL-2.0-only
"""Actual owner update -> SDK peer read,through the sole production Engine.

Local commit is never a notification/ACK/peer-delivery receipt. The independent
opposite USB read response and peer application's comparison are mandatory.
"""
from pathlib import Path
import json
import re
import secrets
import time
from ws73_capture import CaptureError
from ws73_ssap_owned import publisher,wait_text,value_snapshot,await_removed
from ws73_application_client import ssap_command,ssap_receipt,owned_arguments,application_environment,process_identity

STATUS='SDK_OWNED_REPLACEMENT_PAIRED_EVIDENCE_PENDING'


def execute(run,row):
    row['ssap_owned_update_required']=True;row['ssap_owned_updates']=[];run.save()
    s=row['phase']%2;source,target=row['owners'][s],row['owners'][1-s];api='c'if row['phase']==0 else'python'
    with publisher(run,row,s,'none',collection='ssap_owned_updates',label='local-replace',sdk_api=api,read_only=True)as(proc,item):
        item['updates']=[]
        for n in range(2):
            value=secrets.token_hex(32);entry=dict(value=value,start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns())
            item['updates'].append(entry);proc.stdin.write('replace '+value+'\n');proc.stdin.flush()
            matches,_=wait_text(proc,Path(item['output_files'][0]),r'^SdkOwnedReplaced: (.+)$',time.monotonic()+2,min_count=n+1)
            if len(matches)!=n+1:raise CaptureError('one actual local commit receipt per original update')
            entry['receipt']=json.loads(matches[-1]);entry.update(end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns());run.save()
            entry['snapshot']=value_snapshot(proc,item,value);run.save()
            entry['read']=ssap_command(run,row,source,['ssap-read',source['object']['path'],str(item['handle'])],bytes.fromhex(value),api=api)
        value=item['updates'][-1]['value'];item['forbidden_value']=secrets.token_hex(32)
        prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
        def observed(process,record):record['credentials'],record['process_status']=process_identity(process.pid)
        item['forbidden_write']=run.command(prefix+['ssap-error',str(source['owner']['index']),str(source['owner']['generation']),source['object']['path'],'ssap-write',str(item['handle']),'5',item['forbidden_value']],10,collection='ssap_owned_update_commands',environment=application_environment(),on_started=observed)
        value_snapshot(proc,item,value)
        if item['forbidden_write']['exit'] or item['forbidden_write']['stderr']:raise CaptureError('actual read-only peer write must fail with SDK EIO')
        item['quit_wall_ns']=time.time_ns();proc.stdin.write('quit\n');proc.stdin.flush();proc.wait(timeout=2)
        if proc.returncode!=0:raise CaptureError('original owner unregister must finish normally')
        item['cleanup']=await_removed(run,target,item['start']);run.save()
    row['ssap_owned_update_status']=STATUS;run.save()


def corroborate(row,matched):
    if row.get('ssap_owned_update_required',False)is False:return [],{0:0,1:0}
    if row.get('ssap_owned_update_required')is not True:raise CaptureError('typed explicit owner update required')
    items=row.get('ssap_owned_updates',[]);owners=row['owners'];credit={0:0,1:0};proof=[]
    if row.get('ssap_owned_update_status')!=STATUS or len(items)!=1:raise CaptureError('complete owned update gate required')
    i=items[0];s=row['phase']%2;t=1-s;source,target=owners[s],owners[t];api='c'if row['phase']==0 else'python'
    if (i.get('publisher_api')!=api or i.get('policy')!='none' or i.get('sender')!=s or i.get('target')!=t
            or i['args']!=owned_arguments(api,target,i['service'],i['uuid'],i['secret'],'none',read_only=True)
            or i.get('environment')!=application_environment() or i.get('exit')!=0 or i.get('stderr')):raise CaptureError('actual read-only SDK owner and normal unregister required')
    if i['credentials']['uids']!=[1000]*4 or any(int(v,16)for v in i['credentials']['capabilities'].values()):raise CaptureError('ordinary cap-zero SDK owner required')
    if not i['start']<i['handle']<=i['end'] or any(len(bytes.fromhex(i[k]))!=n for k,n in [('secret',32),('service',16),('uuid',16)]):raise CaptureError('original bounded owned registration and initial value required')
    updates=i.get('updates',[]);lines=i['stdout'].splitlines()
    if len(updates)!=2 or lines[:2]!=[f'SdkOwnedAPI: api={api} client_closed=true',f'SsapOwnedService: start={i["start"]} end={i["end"]} property={i["handle"]}; local registration only'] or lines[-1:]!=[f'SdkOwnedRemoved: api={api} start={i["start"]}'] or len(lines)!=8:raise CaptureError('complete original two update/three value/unregister stream required')
    receipts=[json.loads(v)for v in re.findall(r'^SdkOwnedReplaced: (.+)$',i['stdout'],re.M)]
    if receipts!=[v['receipt']for v in updates]:raise CaptureError('sealed update receipts differ from observations')
    fresh={i['secret']};legs=[];previous=i['start_wall_ns']
    def exchange(a,b,pdu,window):
        frame=b'\x0a\0'+len(pdu).to_bytes(2,'little')+pdu
        legs.append(dict(tx=matched(owners[a],'out',frame,window),rx=matched(owners[b],'in',frame,window)));credit[a]+=1
    for v in updates:
        r=v['receipt'];value=v['value'];call=v['read'];snapshot=v['snapshot']
        if set(r)!={'api','handle','value','started_ns','deadline_ns','returned_ns'} or r['api']!=api or r['handle']!=i['handle'] or r['value']!=value or any(type(r[k])is not int for k in ['handle','started_ns','deadline_ns','returned_ns']):raise CaptureError('typed original API commit receipt required')
        if not v['start_monotonic_ns']<=r['started_ns']<=r['returned_ns']<=v['end_monotonic_ns'] or not r['returned_ns']<r['deadline_ns'] or r['deadline_ns']-r['started_ns']!=5_000_000_000:raise CaptureError('original five-second replacement deadline required')
        if not previous<=v['start_wall_ns']<=v['end_wall_ns']<=snapshot['start_wall_ns']<=snapshot['end_wall_ns']<=call['start_wall_ns']<=call['end_wall_ns']<=i['end_wall_ns']:raise CaptureError('commit then independent local snapshot and actual remote read required')
        if len(bytes.fromhex(value))!=32 or value in fresh or snapshot['handle']!=i['handle'] or snapshot['value']!=value:raise CaptureError('fresh exact random update and local observation required')
        fresh.add(value);ssap_receipt(call,source)
        if call['api']!=api or call['ssap_operation']!='ssap-read' or call['ssap_handle']!=i['handle'] or call['ssap_expected']!=value:raise CaptureError('peer application must actually validate the new complete value')
        exchange(s,t,b'\x08\x03'+i['handle'].to_bytes(2,'little')+b'\0',call);exchange(t,s,b'\x09\x03'+bytes.fromhex(value),call);previous=call['end_wall_ns']
    denied=i['forbidden_write'];prefix=['/bin/ws73-application-client-c']if api=='c'else['/bin/python3','/usr/share/sparklink/tools/ws73-application-client.py']
    if denied['args']!=prefix+['ssap-error',str(source['owner']['index']),str(source['owner']['generation']),source['object']['path'],'ssap-write',str(i['handle']),'5',i['forbidden_value']] or denied['exit']or denied['stderr']or denied.get('environment')!=application_environment():raise CaptureError('actual unchanged read-only peer permission rejection required')
    ds=[json.loads(x)for x in denied['stdout'].splitlines()]
    if len(ds)!=2 or ds[0]['stage']!='ssap_call' or ds[0]['api']!=api or ds[0]['client_closed']is not True or ds[1]['stage']!='ssap_error' or ds[1]['api']!=api or ds[1]['errno']!=5 or ds[1]['operation_success']is not False:raise CaptureError('actual SDK error without fabricated operation success required')
    identity=denied['credentials']
    if identity['uids']!=[1000]*4 or any(int(v,16)for v in identity['capabilities'].values()):raise CaptureError('ordinary denied SDK caller required')
    if set(ds[0])!={'stage','api','deadline_ns','call_ns','client_closed'} or set(ds[1])!={'stage','api','errno','operation_success','deadline_ns','returned_ns'} or ds[0]['deadline_ns']!=ds[1]['deadline_ns'] or not denied['start_monotonic_ns']<=ds[0]['call_ns']<=ds[1]['returned_ns']<=denied['end_monotonic_ns'] or not ds[1]['returned_ns']<ds[0]['deadline_ns'] or not 0<ds[0]['deadline_ns']-ds[0]['call_ns']<=5_000_000_000:raise CaptureError('original actual non-timeout SDK error timing required')
    if len(bytes.fromhex(i['forbidden_value']))!=32 or i['forbidden_value']in fresh:raise CaptureError('independent forbidden write payload required')
    if not previous<=denied['start_wall_ns']<=denied['end_wall_ns']<=i['quit_wall_ns']<=i['cleanup']['start_wall_ns']<=i['cleanup']['end_wall_ns']<=i['end_wall_ns']:raise CaptureError('original denial/owner-unregister/cleanup ordering required')
    exchange(s,t,b'\x0d\x23'+i['handle'].to_bytes(2,'little')+b'\0'+bytes.fromhex(i['forbidden_value']),denied);exchange(t,s,b'\x0e\x07\x01'+i['handle'].to_bytes(2,'little')+b'\x07',denied)
    snapshots=i.get('value_snapshots',[])
    if len(snapshots)!=3 or snapshots[-1]['value']!=updates[-1]['value'] or not denied['end_wall_ns']<=snapshots[-1]['start_wall_ns']<=snapshots[-1]['end_wall_ns']<=i['quit_wall_ns']:raise CaptureError('failed peer write must leave the actual owner value unchanged')
    if re.findall(r'^SsapOwnedValue: handle=(\d+) value=([0-9a-f]+)$',i['stdout'],re.M)!=[(str(i['handle']),v)for v in [updates[0]['value'],updates[1]['value'],updates[1]['value']]]:raise CaptureError('original owner value stream required')
    clean=i['cleanup'];lists=re.findall(r'^SsapLocalServices: (.+)$',clean['stdout'],re.M)
    if clean['args']!=[row['ssap_receipts'][0]['args'][0],'--adapter',target['owner']['path'],'ssap-list'] or clean['exit']or clean['stderr']or len(lists)!=1 or any(v[0]==i['start']for v in json.loads(lists[0])):raise CaptureError('independent original service removal required')
    proof.append(dict(api=api,sender=s,target=t,replacements=2,peer_validated_reads=2,read_only_peer_write_error=7,normal_unregister=True,wire=legs,scope='ActualUID1000control-role SDK owner update/peer read;not notification/provider/CCC/service-onlyRF orfullpermissions/lifecycle'))
    return proof,credit


def valid_summary(proof):
    if not isinstance(proof,dict)or proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED':return False
    phases=proof.get('proofs',[])
    if not isinstance(phases,list)or len(phases)!=2:return False
    for n,p in enumerate(phases):
        if not isinstance(p,dict):return False
        rows=p.get('ssap_owned_updates',[])
        if type(p.get('phase'))is not int or p['phase']!=n or not isinstance(rows,list)or len(rows)!=1 or not isinstance(rows[0],dict):return False
        r=rows[0]
        if any(type(r.get(k))is not int for k in ['sender','target','replacements','peer_validated_reads','read_only_peer_write_error']):return False
        if r.get('api')!=('c'if n==0 else'python')or r.get('sender')!=n or r.get('target')!=1-n or r.get('replacements')!=2 or r.get('peer_validated_reads')!=2 or r.get('read_only_peer_write_error')!=7 or r.get('normal_unregister')is not True or not isinstance(r.get('wire'),list)or len(r['wire'])!=6:return False
        for leg in r['wire']:
            if not isinstance(leg,dict)or set(leg)!={'tx','rx'}:return False
            tx,rx=leg['tx'],leg['rx']
            if any(not isinstance(v,dict)or any(type(v.get(k))is not int for k in ['bus','device','handle','wall_ns'])for v in [tx,rx]):return False
            if tx.get('direction')!='out'or rx.get('direction')!='in'or (tx['bus'],tx['device'])==(rx['bus'],rx['device'])or not isinstance(tx.get('data'),str)or not re.fullmatch(r'(?:[0-9a-f]{2}){6,}',tx['data'])or tx['data']!=rx.get('data'):return False
    return True
