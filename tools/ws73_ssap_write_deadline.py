# SPDX-License-Identifier: GPL-2.0-only
"""Typed WRITE adapter for the shared original-deadline scenario and oracle.

One original request, bounded absence of a reply, real SDK late-answer refusal
and independent ordinary business. Not reliable delivery or actor recovery.
"""
from pathlib import Path
import re
import ws73_ssap_provider_deadline as shared
import ws73_ssap_write_unregister as tools
import ws73_ssap_sdk_write_provider as write
from ws73_ssap_sdk_read_provider import need, integer

PREFIX = 'ssap_write_provider_deadline'
TOKEN = 'ws73.'+PREFIX+'=1'
VERSION = 1
PENDING = 'SDK_WRITE_PROVIDER_ORIGINAL_DEADLINE_PENDING_PAIRED_USB'
EXTRA_TOOLS = tools.EXTRA_TOOLS+tuple('/usr/share/sparklink/tools/'+name for name in (
    'ws73_ssap_provider_deadline.py', 'ws73_ssap_command_deadline.py',
    'ws73_ssap_command_policy.py', 'ws73_ssap_write_deadline.py'))


def requested(args, *, passthrough=None):
    return write.requested(args, passthrough=passthrough, selector=PREFIX)


def boot_requested(tokens):
    return write.boot_requested(tokens, selector=PREFIX)


def tool_records(root=Path('/')):
    return tools.tool_records(root, extra_tools=EXTRA_TOOLS)


def validate_tools(records, root, manifest):
    return tools.validate_tools(records, root, manifest, extra_tools=EXTRA_TOOLS)


def validate_inputs(package):
    return tools.validate_inputs(package, extra_tools=EXTRA_TOOLS)


def validate_rows(rows, selected):
    need(type(rows) is list and type(selected) is bool, 'explicit WRITE deadline selection required')
    for phase, row in enumerate(rows):
        need(type(row.get(PREFIX+'_required',False)) is bool
             and row.get(PREFIX+'_required',False) == selected, 'WRITE deadline selection mismatch')
        if not selected:
            need(not any(k.startswith(PREFIX+'_') for k in row if k != PREFIX+'_required'),
                 'unrequested WRITE deadline evidence')
            continue
        need(type(row['phase']) is int and row['phase'] == phase
             and row.get('ssap_owned_required') is True and len(row.get('ssap_owned',[])) == 4
             and type(row.get(PREFIX+'_version')) is int and row[PREFIX+'_version'] == VERSION
             and len(row.get(PREFIX+'_cases',[])) == 1
             and not any(row.get(k+'_required',False) for k in (
                 'ssap_read_provider','ssap_sdk_read_provider','ssap_sdk_write_provider',
                 'ssap_write_provider_unregister','ssap_provider_owner_exit',
                 'ssap_provider_unregister','ssap_provider_deadline')),
             'one last WRITE deadline case after original Owned baseline required')
    if selected:
        need(len(rows) == 2 and len({(r['owners'][1]['owner']['index'],r['owners'][1]['owner']['generation'])
             for r in rows}) == 2, 'both original physical WRITE receivers required')


def execute(run, row, business):
    return shared.execute(run, row, business, writing=True)


def corroborate(row, matched, packets):
    return shared.corroborate(row, matched, packets, writing=True)


def verify_business_evidence(row, proof, legs):
    return shared.verify_business_evidence(row, proof, legs)


def valid_summary(proof, *, version=VERSION):
    return type(version) is int and version == VERSION and shared.valid_summary(proof, version=version, writing=True)


def valid_manifest(record):
    try:
        selected = record.get(PREFIX+'_requested',False)
        need(type(selected) is bool and boot_requested([t for arg in record.get('qemu_args',[]) for t in arg.split()]) == selected,
             'WRITE deadline boot/manifest mismatch')
        proof = record.get('channel_socket_corroboration',{})
        if not selected:
            return (record.get(PREFIX+'_acceptance',False) is False
                    and not any(PREFIX+s in record for s in ('_version','_verifier'))
                    and not any(PREFIX in r for r in proof.get('proofs',[])))
        v = record[PREFIX+'_verifier']
        need(type(v) is dict and set(v) == {'path','sha256','bytes'} and Path(v['path']).name == 'ws73_ssap_write_deadline.py'
             and integer(v['bytes']) and re.fullmatch('[0-9a-f]{64}',v['sha256']), 'exact WRITE deadline verifier required')
        for row in proof.get('proofs',[]):
            for item in row.get(PREFIX,[]):
                need(item['context'][PREFIX+'_tools'][EXTRA_TOOLS[-1]] == {k:v[k] for k in ('sha256','bytes')},
                     'WRITE deadline guest and host verifier differ')
        return (record.get('status') == 'PASSTHROUGH_SUPPORT_PASS' and type(record.get('qemu_exit')) is int
                and record['qemu_exit'] == 0 and record.get('ssap_owned_acceptance') is True
                and record.get('ordinary_channel_socket_acceptance') is True
                and type(record.get(PREFIX+'_version')) is int and record[PREFIX+'_version'] == VERSION
                and record.get(PREFIX+'_acceptance') is True and valid_summary(proof))
    except (KeyError, AttributeError, TypeError, ValueError, IndexError):
        return False
