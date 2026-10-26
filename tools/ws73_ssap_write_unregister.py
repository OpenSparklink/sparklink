# SPDX-License-Identifier: GPL-2.0-only
"""WRITE withdrawal uses the original pending-case, SDK and paired-wire gates.

Dedicated ordinary/Owned run; READ evidence remains versioned and unchanged.
The historical item['read'] field holds the actual operation, validated as WRITE.
No callback/RPC result is substituted for the real peer or guard reply.
"""
import hashlib
from pathlib import Path
import re
from ws73_ssap_sdk_read_provider import need, integer
import ws73_ssap_sdk_read_provider as sdk
import ws73_ssap_sdk_write_provider as write
import ws73_ssap_provider_unregister as withdrawal
from ws73_ssap_provider_owner_exit import execute_pending_case

PREFIX='ssap_write_provider_unregister'
TOKEN='ws73.'+PREFIX+'=1'
VERSION=1
STATUS='SDK_WRITE_PROVIDER_UNREGISTER_APPLICATION_PAIRED_USB'
PENDING='SDK_WRITE_PROVIDER_UNREGISTER_PENDING_PAIRED_USB'
EXTRA_TOOLS=sdk.EXTRA_TOOLS+tuple('/usr/share/sparklink/tools/'+name for name in (
    'ws73_ssap_sdk_write_provider.py','ws73_ssap_provider_owner_exit.py',
    'ws73_ssap_provider_unregister.py','ws73_ssap_write_unregister.py'))


def requested(args, *, passthrough=None):
    selected=write.requested(args,passthrough=passthrough,selector=PREFIX)
    need(not selected or not getattr(args,'ssap_sdk_write_provider_verify',False),
         'pending WRITE withdrawal is a dedicated gate, not combined with normal WRITE')
    return selected


def boot_requested(tokens):
    selected=write.boot_requested(tokens,selector=PREFIX)
    need(not selected or not any(t.startswith('ws73.ssap_sdk_write_provider') for t in tokens),
         'dedicated pending WRITE withdrawal boot selector required')
    return selected


def tool_records(root=Path('/')):
    result=sdk.tool_records(root)
    for name in EXTRA_TOOLS[len(sdk.EXTRA_TOOLS):]:
        p=root/name.lstrip('/');result[name]=dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
    return result


def validate_tools(records,root,manifest):
    need(records==tool_records(root),'fresh exact pending WRITE tool identities required')
    sdk.validate_tools({k:v for k,v in records.items() if k not in EXTRA_TOOLS[len(sdk.EXTRA_TOOLS):]},root,manifest)
    for name in EXTRA_TOOLS[len(sdk.EXTRA_TOOLS):]:
        p=(root/name.lstrip('/')).resolve(strict=True);found=[x for x in manifest if Path(x['path']).resolve()==p]
        need(len(found)==1 and found[0]['sha256']==records[name]['sha256'],'pending WRITE helper missing from build manifest')


def validate_inputs(package):
    sdk.validate_inputs(package)
    for name in EXTRA_TOOLS[len(sdk.EXTRA_TOOLS):]:
        p=Path(__file__).resolve().parent/Path(name).name;found=[x for x in package.get('inputs',[])if Path(x['path']).resolve()==p]
        need(len(found)==1 and found[0]['sha256']==hashlib.sha256(p.read_bytes()).hexdigest(),'fresh pending WRITE helper required')


def validate_rows(rows,selected):
    need(type(rows)is list and type(selected)is bool,'explicit pending WRITE rows required')
    for phase,row in enumerate(rows):
        need(type(row.get(PREFIX+'_required',False))is bool and row.get(PREFIX+'_required',False)==selected,'pending WRITE selection mismatch')
        if not selected:
            need(not any(k.startswith(PREFIX+'_')for k in row if k!=PREFIX+'_required'),'unrequested pending WRITE evidence');continue
        need(type(row.get('phase'))is int and row['phase']==phase and row.get('ssap_owned_required')is True
             and len(row.get('ssap_owned',[]))==4 and type(row.get(PREFIX+'_version'))is int and row[PREFIX+'_version']==VERSION
             and len(row.get(PREFIX+'_cases',[]))==len(row.get(PREFIX+'_guards',[]))==1
             and row[PREFIX+'_cases'][0]['guard']==row[PREFIX+'_guards'][0]
             and not any(row.get(k+'_required',False)for k in ('ssap_read_provider','ssap_sdk_read_provider','ssap_sdk_write_provider','ssap_provider_owner_exit','ssap_provider_unregister','ssap_provider_deadline')),
             'one dedicated pending WRITE and original Owned baseline per role required')
    if selected:need(len(rows)==2 and len({(r['owners'][1]['owner']['index'],r['owners'][1]['owner']['generation'])for r in rows})==2,'both physical pending WRITE receivers required')


def execute(run,row):
    need(row.get('ssap_owned_required')is True and len(row.get('ssap_owned',[]))==4,'Owned baseline must finish first')
    row.update({PREFIX+'_required':True,PREFIX+'_version':VERSION,PREFIX+'_tools':tool_records(),PREFIX+'_cases':[],PREFIX+'_guards':[]});run.save()
    def action(*args):withdrawal._unregister(*args,writing=True)
    execute_pending_case(run,row,PREFIX,'write-provider-unregister',action,finish=withdrawal._finish,writing=True)
    row[PREFIX+'_status']=PENDING;run.save()


def corroborate(row,matched,packets):
    selected=row.get(PREFIX+'_required',False);need(type(selected)is bool,'explicit pending WRITE selection required')
    if not selected:
        need(not any(k.startswith(PREFIX+'_')for k in row if k!=PREFIX+'_required'),'unrequested pending WRITE evidence');return [],{0:0,1:0}
    need(type(row.get(PREFIX+'_version'))is int and row[PREFIX+'_version']==VERSION
         and len(row.get(PREFIX+'_cases',[]))==len(row.get(PREFIX+'_guards',[]))==1
         and row[PREFIX+'_cases'][0]['guard']==row[PREFIX+'_guards'][0],'one original pending WRITE and guard required')
    result,credit=withdrawal._case(row,row[PREFIX+'_cases'][0],matched,packets,writing=True)
    return [result],credit


def verify_business_after(case,legs):withdrawal.verify_business_after(case,legs)

def valid_summary(proof, *, version=VERSION):
    return type(version)is int and version==VERSION and withdrawal.valid_summary(proof,writing=True)


def valid_manifest(record):
    try:
        selected=record.get(PREFIX+'_requested',False);need(type(selected)is bool,'explicit pending WRITE manifest selector required')
        need(boot_requested([t for arg in record.get('qemu_args',[])for t in arg.split()])==selected,'pending WRITE boot/manifest mismatch')
        proof=record.get('channel_socket_corroboration',{})
        if not selected:return record.get(PREFIX+'_acceptance',False)is False and not any(PREFIX+s in record for s in ('_version','_verifier'))and not any(PREFIX in r for r in proof.get('proofs',[]))
        v=record[PREFIX+'_verifier'];need(type(v)is dict and set(v)=={'path','sha256','bytes'}and type(v['path'])is str and Path(v['path']).name=='ws73_ssap_write_unregister.py'and integer(v['bytes'])and re.fullmatch('[0-9a-f]{64}',v['sha256']),'exact pending WRITE verifier identity required')
        for row in proof.get('proofs',[]):
            for item in row.get(PREFIX,[]):need(item['context'][PREFIX+'_tools'][EXTRA_TOOLS[-1]]=={k:v[k]for k in ('sha256','bytes')},'pending WRITE verifier differs from guest tool')
        return (record.get('status')=='PASSTHROUGH_SUPPORT_PASS'and type(record.get('qemu_exit'))is int and record['qemu_exit']==0
                and record.get('ssap_owned_acceptance')is True and record.get('ordinary_channel_socket_acceptance')is True
                and type(record.get(PREFIX+'_version'))is int and record[PREFIX+'_version']==VERSION
                and record.get(PREFIX+'_acceptance')is True and valid_summary(proof))
    except (KeyError,AttributeError,IndexError,TypeError,ValueError):return False
