# SPDX-License-Identifier: GPL-2.0-only
"""Actual default observer/control roles around a separate native RF22 VM.

The root guest supervisor switches only guest identities. The application and
bus clients remain ordinary; neither successful replies nor radio data are made
by this module. Original protocol replies are corroborated after VM exit.
"""
import json
from pathlib import Path
import re
import time

from ws73_capture import CaptureError
from ws73_north_star import file_record, daemon_identity, stable
from ws73_rf_rounds import initializer_recipe

STATUS = 'NATIVE_OBSERVER_POLICY_EVIDENCE_PENDING'
DENIALS = ['own-service','CancelDiscoveryPolicies','StartControllerScan','StopControllerScan',
    'SubmitScanning','SubmitStopScanning','SubmitStopAdvertising','SubmitAdvertising',
    'unique-owner-write','interface-less-write','interface-less-read','Properties.Set',
    'future-method','foreign-interface','RemoteService.Read','DequeueNotification','GetPasskey']
POLICY = [3,1200,1200,127,1600,800]


def record_phase(application, owners, phase, folder=Path('/evidence/observer-policy')):
    if phase not in ['initial','business']: raise ValueError('explicit native role phase required')
    folder.mkdir(exist_ok=True)
    path=folder/'run.json'
    record=json.loads(path.read_text()) if path.exists() else dict(version=1,status='RUNNING',phases=[],
        physical_acceptance=False,automatic_recovery_acceptance=False,whole_authorization_acceptance=False,
        helper=file_record('/bin/bus-policy-probe'),slctl=file_record('/bin/slctl'))
    expected=['initial'] if not record['phases'] else ['initial','business']
    if [p['phase'] for p in record['phases']]+[phase]!=expected:raise ValueError('ordered single role phases required')
    pid=int(__import__('subprocess').check_output(['/bin/pidof','slkd'],text=True))
    entry=dict(phase=phase,owners=owners,commands=[],daemon=daemon_identity(pid),start_wall_ns=time.time_ns())
    record['phases'].append(entry)
    def save():path.write_text(json.dumps(record,indent=2)+'\n')
    def command(role,owner,words):
        row=dict(role=role,identity=owner,args=words,start_wall_ns=time.time_ns())
        result=application(*words,user=role,capture_output=True,timeout=25)
        row.update(stdout=result.stdout,stderr=result.stderr,exit=result.returncode,end_wall_ns=time.time_ns())
        entry['commands'].append(row);save();return row
    try:
        for owner in owners:
            for role,mode in [('observer','observer'),('ws73','control')]:
                row=command(role,owner,['/bin/bus-policy-probe',owner['path'],mode,'native-'+phase])
                if row['exit']:raise ValueError('actual role probe failed: '+row['stderr'])
            for words in [[record['slctl']['path'],'--adapter',owner['path'],'show'],[record['slctl']['path'],'--adapter',owner['path'],'management']]:
                if command('observer',owner,words)['exit']:raise ValueError('actual observer CLI read denied or failed')
            row=command('observer',owner,['/bin/sh','-c','test -r /dev/sparklink || test -w /dev/sparklink || test -r /dev/usbmon1 || test -w /dev/usbmon1'])
            if row['exit']!=1:raise ValueError('default observer obtained direct kernel/capture access')
        entry['end_wall_ns']=time.time_ns()
        if phase=='business':record['status']=STATUS
        save()
    except BaseException as error:
        record.update(status='FAIL',error=str(error));save();raise


def native_reads(row,owner,phase,unique_owner):
    values=[json.loads(v) for v in re.findall(r'^AUTH_NATIVE_READ: (.+)$',row['stdout'],re.M)]
    if len(values)!=2 or [v['destination'] for v in values]!=['org.sparklink',unique_owner]:
        raise CaptureError('named service and actual unique-owner reads required')
    for value in values:
        if (value['phase']!='native-'+phase or value['policy']!=POLICY
                or value['management']!=[owner['generation'],1,1,1,0,0,0]):
            raise CaptureError('actual immutable policy and owned token-redacted management required')
        if len(value['initializers'])!=2 or [v['operation'] for v in value['initializers']]!=[5,6]:
            raise CaptureError('both actual initializer observations required')
        for init in value['initializers']:
            op=init['operation']
            if phase=='initial':
                result=init['result']
                if (len(result)!=14 or result[0]!=owner['generation'] or type(result[1]) is not int or not 0<result[1]<2**64
                        or result[2:9]!=[op,3,0,0,0x0c05 if op==5 else 0x1002,1 if op==5 else 2,2 if op==5 else 3]
                        or type(result[10]) is not bool or result[10]!=(op==5) or result[11:]!=[1,1,1]
                        or type(result[9]) is not int or not -128<=result[9]<=127 or init['history']!=result):
                    raise CaptureError('original successful op5/6 and identical actual history required')
            elif init.get('outcome')!='invalidated' or 'initializer provenance absent or invalidated' not in init.get('reason','') or 'result' in init or 'history' in init:
                raise CaptureError('business-used provenance refusal, not bus denial or cached success, required')
    return values


def verify_records(record,run):
    if (record.get('version')!=1 or record.get('status')!=STATUS
            or any(record.get(k) is not False for k in ['physical_acceptance','automatic_recovery_acceptance','whole_authorization_acceptance'])
            or [p['phase'] for p in record['phases']]!=['initial','business']):
        raise CaptureError('separate completed real Native observer role gate required')
    if record['slctl']!=run['slctl']:raise CaptureError('same actually executed slctl required')
    previous=0;initial_ids={}
    for entry,expected in zip(record['phases'],[run['initial'],[run['replacement'],run['initial'][1]]]):
        if (len(entry['owners'])!=2 or any(not stable(a,b) for a,b in zip(entry['owners'],expected)) or entry['daemon']!=run['daemon_before']
                or not previous<entry['start_wall_ns']<=entry['end_wall_ns'] or len(entry['commands'])!=10):
            raise CaptureError('same live daemon and exact selected role registrations required')
        previous=entry['start_wall_ns']
        for index,row in enumerate(entry['commands']):
            owner=entry['owners'][index//5];offset=index%5
            role='ws73' if offset==1 else 'observer'
            args=([record['helper']['path'],owner['path'],'control' if role=='ws73' else 'observer','native-'+entry['phase']] if offset<2 else
                  [record['slctl']['path'],'--adapter',owner['path'],'show' if offset==2 else 'management'] if offset<4 else
                  ['/bin/sh','-c','test -r /dev/sparklink || test -w /dev/sparklink || test -r /dev/usbmon1 || test -w /dev/usbmon1'])
            if (row['role']!=role or row['identity']!=owner or row['args']!=args or row['exit']!=(1 if offset==4 else 0)
                    or not previous<=row['start_wall_ns']<=row['end_wall_ns']<=entry['end_wall_ns']):
                raise CaptureError('exact role, ordered actual command and result required')
            previous=row['end_wall_ns']
            if offset<2:
                expected_credentials=f'AUTH_CREDENTIALS: uid={1000 if role=="ws73" else 1001} gid={1002 if role=="ws73" else 1001} caps=0'
                if re.findall(r'^AUTH_CREDENTIALS: .+$',row['stdout'],re.M)!=[expected_credentials]:raise CaptureError('actual ordinary role credentials required')
                if re.findall(r'^AUTH_DENIED: (.+)$',row['stdout'],re.M)!=(['own-service'] if role=='ws73' else DENIALS):raise CaptureError('all exact bus refusals including cancellation and service ownership required')
                reads=native_reads(row,owner,entry['phase'],run['bus_before']['owner'])
                if entry['phase']=='initial':
                    ids=[v['result'][1] for v in reads[0]['initializers']]
                    key=owner['path']
                    if key in initial_ids and initial_ids[key]!=ids:raise CaptureError('observer/control initializer IDs differ')
                    initial_ids[key]=ids
                    if [v['result'] for v in reads[0]['initializers']]!=[v['result'] for v in reads[1]['initializers']]:raise CaptureError('unique-owner observation differs')
            elif offset==2:
                if '  State:       Ready\n' not in row['stdout'] or f'  Generation:  {owner["generation"]}\n' not in row['stdout'] or '  Radio policy: version=3 adv_slots=1200..1200 tx_power_dbm=127 scan_slots=1600/800\n' not in row['stdout']:
                    raise CaptureError('default observer show must finish with actual Ready policy')
            elif offset==3:
                expected_line=f'NativeManagementStatus: generation={owner["generation"]} mode=1 state=1 flags=1 errno=0 status=0x00 opcode=0x0000'
                if re.findall(r'^NativeManagementStatus: .+$',row['stdout'],re.M)!=[expected_line] or 'lease=' in row['stdout']:raise CaptureError('observer management must be actual and token-redacted')
        previous=entry['end_wall_ns']
    if (record['phases'][0]['end_wall_ns']>=run['commands'][min(run['rounds'][0]['command_indices'])]['start_wall_ns']
            or record['phases'][1]['start_wall_ns']<=run['commands'][max(run['rounds'][-1]['command_indices'])]['end_wall_ns']):
        raise CaptureError('role phases must bracket the entire real RF gate')
    return record


def corroborate(record,run,capture):
    verify_records(record,run);proofs=[]
    for entry in record['phases']:
        for owner in entry['owners']:
            if any((c['bus'],c['device'])==(owner['bus'],owner['device']) and entry['start_wall_ns']<=c['wall_ns']<=entry['end_wall_ns'] for c in capture['commands']):
                raise CaptureError('observer or denied bus calls caused device commands')
        if entry['phase']=='initial':
            for row in entry['commands']:
                if row['args'][0]!=record['helper']['path']:continue
                for read in native_reads(row,row['identity'],'initial',run['bus_before']['owner']):
                    for init in read['initializers']:
                        proofs.append({'identity':row['identity'],'role':row['role'],'destination':read['destination'],'operation':init['operation'],'request':init['result'][1],
                            'initializer_wire_recipe':initializer_recipe(capture,row['identity'],init['operation'],row,init['result'][9]),'new_stop_submission':False})
    if len(proofs)!=16:raise CaptureError('all 16 role/destination original initializer observations required')
    return {'status':'REAL_DEFAULT_OBSERVER_NATIVE_POLICY_CORROBORATED','initializer_observations':proofs,
            'observer_bus_denials':68,'control_service_ownership_denials':4,'role_phases':2,'role_window_device_commands':0,
            'whole_authorization_acceptance':False,'physical_acceptance':False,'automatic_recovery_acceptance':False}
