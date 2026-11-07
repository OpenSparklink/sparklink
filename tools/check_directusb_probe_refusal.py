#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual probe binaries without arguments; never select/open USB."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

SCOPES = {'rom': 'VM_ROM_READ_ONLY_NOT_HOST_OR_RECOVERY',
          'control': 'VM_RUNTIME_EP0_READ_ONLY_NOT_HOST_OR_RECOVERY',
          'receive': 'VM_RUNTIME_BULK_IN_ONLY_NOT_HOST_OR_RECOVERY'}


def validate(result, kind):
    if (type(result.returncode) is not int or result.returncode != 1
            or result.stderr or len(result.stdout.encode()) > 65536):
        raise ValueError('exact refusal exit/complete bounded output required')
    value = json.loads(result.stdout)
    if (not isinstance(value, dict) or type(value.get('schema')) is not int
            or value['schema'] != 1 or value.get('status') != 'REFUSED_OR_FAILED'
            or value.get('scope') != SCOPES[kind]
            or not isinstance(value.get('error'), str) or not value['error'].startswith('usage: ')
            or any(k in value for k in ['bus', 'guest_port', 'reply', 'control',
                                      'raw_memory_backpressure_word_le', 'receive',
                                      'endpoint_pending_after', 'interface_release'])):
        raise ValueError('no-argument refusal must precede device selection')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--receive', type=Path, required=True)
    args = parser.parse_args()
    for kind, binary in [('rom', args.rom), ('control', args.control), ('receive', args.receive)]:
        before = hashlib.sha256(binary.read_bytes()).hexdigest()
        result = subprocess.run([str(binary.resolve(strict=True))], capture_output=True,
                                text=True, timeout=5, check=False)
        validate(result, kind)
        if hashlib.sha256(binary.read_bytes()).hexdigest() != before:
            raise ValueError('executed binary changed')
        print(kind, 'ACTUAL_NO_ARGUMENT_REFUSAL_ONLY', before)


if __name__ == '__main__':
    main()
