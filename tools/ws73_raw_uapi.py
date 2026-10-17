#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Source-bound retired syscall receipts; independent of RF/business verdicts."""
import argparse
import copy
import hashlib
import inspect
import json
from pathlib import Path
import re

from ws73_channel_socket import verify_retired_uapi_receipt


def verify(record):
    rows = record['channel_socket']
    expected = [(row, owner['owner']) for row in rows for owner in row['owners']]
    receipts = record['retired_uapi_refusals']
    if not expected or len(receipts) != len(expected):
        raise ValueError('each actual connection role/owner needs one retired syscall receipt')
    for receipt, (row, owner) in zip(receipts, expected):
        verify_retired_uapi_receipt(receipt)
        if receipt['args'] != ['/bin/retired-uapi-probe', str(owner['index'])]:
            raise ValueError('retired syscall probe path or selected controller mismatch')
        if type(receipt['pid']) is not int or receipt['pid'] <= 0:
            raise ValueError('actual probe process required')
        times = [row['start_wall_ns'], receipt['start_wall_ns'],
                 receipt['end_wall_ns'], row['end_wall_ns']]
        if any(type(t) is not int or t <= 0 for t in times) or times != sorted(times):
            raise ValueError('retired syscall receipt outside its original connection interval')
    return dict(receipts=len(receipts), commands_per_receipt=101, checks_per_receipt=303)


def verify_binary(prepared, manifest):
    binary = prepared / 'root/bin/retired-uapi-probe'
    entries = [r for r in manifest['guest_files'] if Path(r['path']) == binary]
    if len(entries) != 1:
        raise ValueError('matching prepared probe receipt missing or duplicated')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if entries[0]['sha256'] != digest:
        raise ValueError('actual prepared probe hash mismatch')
    return dict(path='root/bin/retired-uapi-probe', sha256=digest)


def run(args):
    if any(not re.fullmatch('[0-9a-f]{40}', value) for value in [args.kernel, args.userspace]):
        raise ValueError('exact full source commit IDs required')
    args.run = args.run.resolve(strict=True)
    args.prepared = args.prepared.resolve(strict=True)
    manifest_path = args.run / 'manifest.json'
    record_path = args.run / 'guest-output/application/passthrough-control/run.json'
    prepared_path = args.prepared / 'manifest.json'
    run_manifest = json.loads(manifest_path.read_text())
    prepared_manifest = json.loads(prepared_path.read_text())
    if (run_manifest['qemu_exit'] != 0 or run_manifest['native_vm']['kernel_head'] != args.kernel
            or run_manifest['native_vm']['userspace_head'] != args.userspace
            or prepared_manifest['native_vm']['kernel_head'] != args.kernel
            or prepared_manifest['native_vm']['userspace_head'] != args.userspace):
        raise ValueError('run/compiled/prepared source identities disagree')
    record = json.loads(record_path.read_text())
    result = verify(record)
    result['binary'] = verify_binary(args.prepared, prepared_manifest)
    negatives = []
    for kind in ['missing', 'wrong-controller', 'root-uid', 'historical-83', 'short-checks',
                 'failed-exit', 'duplicate-line', 'missing-process', 'outside-interval']:
        changed = copy.deepcopy(record)
        receipt = changed['retired_uapi_refusals'][0]
        if kind == 'missing': changed['retired_uapi_refusals'].pop()
        elif kind == 'wrong-controller': receipt['args'][1] = '15'
        elif kind == 'root-uid': receipt['stdout'] = receipt['stdout'].replace('uid=1000', 'uid=0')
        elif kind == 'historical-83': receipt['stdout'] = receipt['stdout'].replace('cases=101', 'cases=83')
        elif kind == 'short-checks': receipt['stdout'] = receipt['stdout'].replace('checks=303', 'checks=1')
        elif kind == 'failed-exit': receipt['exit'] = 1
        elif kind == 'duplicate-line': receipt['stdout'] *= 2
        elif kind == 'missing-process': receipt['pid'] = 0
        else: receipt['start_wall_ns'] = changed['channel_socket'][0]['end_wall_ns'] + 1
        try:
            verify(changed)
        except (ValueError, KeyError, TypeError) as error:
            negatives.append(dict(kind=kind, result='REJECTED', reason=str(error)))
        else:
            raise ValueError('false pass: ' + kind)
    changed = copy.deepcopy(prepared_manifest)
    next(r for r in changed['guest_files'] if Path(r['path']).name == 'retired-uapi-probe')['sha256'] = '0' * 64
    try:
        verify_binary(args.prepared, changed)
    except ValueError:
        negatives.append(dict(kind='changed-binary-hash', result='REJECTED'))
    else:
        raise ValueError('false pass: changed binary hash')
    result.update(status='RETIRED_SYSCALL_RECEIPTS_SCOPED_PASS', kernel=args.kernel,
                  compiled_userspace=args.userspace, negative_controls=negatives,
                  materials={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in [manifest_path, record_path, prepared_path, Path(__file__),
                                       Path(inspect.getsourcefile(verify_retired_uapi_receipt))]},
                  scope='Actual guest C receipts and prepared binary/source identity; not independent RF evidence, ledger proof, natural recovery or complete architecture.')
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['run', 'prepared', 'output']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--userspace', required=True)
    run(parser.parse_args())
