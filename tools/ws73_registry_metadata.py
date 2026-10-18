#!/usr/bin/env python3
"""Actual Native C count and slkconfig entry in disposable VM; not business RF."""
from pathlib import Path
import re
import time
from ws73_capture import CaptureError
from ws73_north_star import file_record

STATUS='ACTUAL_CORE_REGISTRY_METADATA_SCOPED_PASS'


def corroborate(run):
    record=run['registry_metadata']
    if record['version']!=1 or record['status']!=STATUS or len(record['cases'])!=2:
        raise CaptureError('two complete metadata cases required')
    owners=record['owners']
    if len(owners)!=2 or len({o['index'] for o in owners})!=2:
        raise CaptureError('two independent registrations required')
    if any(type(o['index']) is not int or not 0<=o['index']<16 or type(o['generation']) is not int or o['generation']<=0 for o in owners):
        raise CaptureError('valid registration identities required')
    expected=sum(1<<o['index'] for o in owners)
    parent=run['connection_control']
    if owners!=parent['owners'] or parent['status']!='CONNECTION_CONTROL_EVIDENCE_PENDING' or record['start_wall_ns']<parent['end_wall_ns']:
        raise CaptureError('same completed physical role-exchange owners required')
    if len(run['registry_metadata_commands'])!=4:raise CaptureError('all four original commands required')
    for artifact in ['probe','cli']:
        value=record[artifact]
        if value!=run['artifacts']['registry_'+artifact]:raise CaptureError('metadata artifact differs from original run identity')
        if not re.fullmatch('[0-9a-f]{64}',value['sha256']) or not Path(value['path']).is_absolute():
            raise CaptureError('actual artifact identity required')
    previous=record['start_wall_ns']
    for index,(owner,case) in enumerate(zip(owners,record['cases'])):
        if case['owner']!=owner:raise CaptureError('metadata owner mismatch')
        c,cli=case['c'],case['cli'];idx,gen=owner['index'],owner['generation']
        if [c,cli]!=run['registry_metadata_commands'][2*index:2*index+2]:raise CaptureError('original command receipts required')
        for command in [c,cli]:
            if command['exit'] or not previous<=command['start_wall_ns']<=command['end_wall_ns']<=record['end_wall_ns']:
                raise CaptureError('completed command within original metadata interval required')
            previous=command['end_wall_ns']
        if c['args']!=[record['probe']['path'],'metadata',str(idx),str(gen)]:raise CaptureError('original C entry required')
        fields=re.fullmatch(r'CoreRegistryMetadata: index=(\d+) generation=(\d+) mask=(\d+) count=(\d+) flags=(\d+)\nWS73_NATIVE_C_BINDINGS: PASS mode=metadata uid=(\d+) index=(\d+) generation=(\d+)\n',c['stdout'])
        if fields is None or tuple(map(int,fields.groups()))!=(idx,gen,expected,2,1,1000,idx,gen):
            raise CaptureError('actual ordinary Native observer C bitmap/count/identity required')
        if cli['args']!=[record['cli']['path'],'--adapter',str(idx),'--generation',str(gen),'connections']:
            raise CaptureError('actual slkconfig connections entry required')
        fields=re.fullmatch(r'NativeLinks: index=(\d+) generation=(\d+) revision=(\d+) sequence=(\d+) count=0\n',cli['stdout'])
        if fields is None or tuple(map(int,fields.groups()[:2]))!=(idx,gen) or min(map(int,fields.groups()[2:]))<=0:
            raise CaptureError('confirmed empty physical table after actual disconnect required')
    return {'status':STATUS,'registrations':2,'allocated':2,'physical_links':0,
            'scope':'Core registry/actual C and CLI metadata only;not C/Python business data,attestation,atomic cross-query or recovery'}


def execute(run,a,b):
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip()!='QEMU' or not Path('/scratch-root-uuid').is_file():
        raise CaptureError('disposable QEMU Native VM only')
    record={'version':1,'status':'RUNNING','start_wall_ns':time.time_ns(),
            'owners':[a,b],'probe':file_record('/bin/native-bindings-probe'),
            'cli':file_record('/bin/slkconfig'),'cases':[]}
    run.data['registry_metadata']=record;run.save()
    try:
        for owner in [a,b]:
            run.check(owner)
            row={'owner':owner};record['cases'].append(row);run.save()
            row['c']=run.command([record['probe']['path'],'metadata',str(owner['index']),str(owner['generation'])],3,collection='registry_metadata_commands')
            row['cli']=run.command([record['cli']['path'],'--adapter',str(owner['index']),'--generation',str(owner['generation']),'connections'],3,collection='registry_metadata_commands')
            run.save()
        record['end_wall_ns']=time.time_ns();record['status']=STATUS
        corroborate(run.data)
    except BaseException:
        record['status']='FAIL';raise
    finally:
        record['end_wall_ns']=time.time_ns();run.save()
