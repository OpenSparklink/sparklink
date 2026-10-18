#!/usr/bin/env python3
"""Independent current C headers versus actual cdylib dynamic exports.

No ABI layout/call, permission, lifetime, build provenance or RF qualification.
Only the currently unversioned flat C surface is supported; new export/version
conventions require an explicit contract change, not silently ignored symbols.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def declarations(text):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    names = re.findall(r'\b(slk_\w+)\s*\(', text)
    if not names or len(names) != len(set(names)):
        raise ValueError('missing or duplicate public C declarations')
    return set(names)


def dynamic_symbols(text):
    names = set()
    for line in text.splitlines():
        fields = line.split()
        if (len(fields) not in (3, 4)
                or not re.fullmatch(r'[A-Za-z_]\w*', fields[0])
                or fields[1] not in ('T', 'W')
                or any(not re.fullmatch(r'[0-9a-fA-F]+', v) for v in fields[2:])):
            raise ValueError('unrecognized defined dynamic symbol: '+repr(line))
        if fields[0] in names:
            raise ValueError('duplicate defined dynamic symbol: '+fields[0])
        names.add(fields[0])
    if not names:
        raise ValueError('empty defined dynamic symbol output')
    return names


def compare(header, output):
    expected, actual = declarations(header), dynamic_symbols(output)
    errors = []
    if expected - actual:
        errors.append('missing exports: '+','.join(sorted(expected - actual)))
    if actual - expected:
        errors.append('undeclared exports: '+','.join(sorted(actual - expected)))
    return errors


def identity(path):
    path = path.resolve(strict=True)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def inspect(library, header):
    before = identity(library)
    head = identity(header)
    command = ['nm', '-D', '--defined-only', '--format=posix', str(library.resolve())]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    if result.stderr:
        raise ValueError('nm diagnostic requires inspection: '+result.stderr)
    errors = compare(header.read_text(), result.stdout)
    if errors:
        raise ValueError('; '.join(errors))
    if identity(library) != before or identity(header) != head:
        raise ValueError('artifact/header changed during check')
    return {'library': before, 'header': head, 'command': command,
            'symbols': sorted(dynamic_symbols(result.stdout))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-library', type=Path, required=True)
    parser.add_argument('--native-library', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise ValueError('refuse to overwrite symbol report')
    rows = [inspect(args.application_library, ROOT/'crates/libsparklink/include/sparklink.h'),
            inspect(args.native_library, ROOT/'crates/slk-native/include/sparklink_native.h')]
    report = {'schema': 1, 'status': 'CURRENT_C_EXPORTS_MATCH_NOT_ABI_OR_RF',
              'scope': __doc__, 'checker': identity(Path(__file__)),
              'nm_version': subprocess.check_output(['nm','--version'], text=True).splitlines()[0],
              'rows': rows}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('Actual application/Native exports match current headers; not ABI/call or device qualification')


if __name__ == '__main__':
    main()
