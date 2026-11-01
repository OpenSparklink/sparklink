#!/usr/bin/env python3
"""Stage checksum-pinned upstream production code plus narrow no-USB tests.

No download, build, device enumeration, claim or submission. The caller uses
the existing shared build wrapper and the archive's Cargo.lock. This is an
upstream dependency audit, not a SparkLink implementation/VM qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

VERSION = '0.2.9'
CHECKSUM = '1de8b6d15f559f50760dad6c1b56fde4041f99dc96a08e55c2b41f44c7417ad9'
MODULE = 'src/transfer/internal.rs'


def prepare(archive, output):
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != CHECKSUM:
        raise ValueError('nusb archive checksum mismatch; no source staged')
    if output.exists():
        raise ValueError('audit output already exists; preserve previous evidence')
    fixture = Path(__file__).parent / 'tests/fixtures/nusb_transfer_lifecycle.rs'
    tests = fixture.read_bytes()
    with tarfile.open(archive) as source:
        members = source.getmembers()
        prefix = f'nusb-{VERSION}/'
        for member in members:
            path = Path(member.name)
            if not member.name.startswith(prefix) or '..' in path.parts or not member.isfile():
                raise ValueError('unexpected archive member')
        output.mkdir(parents=True)
        source.extractall(output, members=members, filter='data')
    root = output / f'nusb-{VERSION}'
    production = root / MODULE
    original = production.read_bytes()
    production.write_bytes(original + b'\n' + tests)
    record = {
        'version': VERSION, 'archive_sha256': CHECKSUM,
        'upstream_git': '5dfee4c1f82a1fdf019c3b5935ee4cd887908093',
        'production_module': MODULE,
        'original_sha256': hashlib.sha256(original).hexdigest(),
        'test_sha256': hashlib.sha256(tests).hexdigest(),
        'instrumented_sha256': hashlib.sha256(production.read_bytes()).hexdigest(),
        'cargo_lock_sha256': hashlib.sha256((root / 'Cargo.lock').read_bytes()).hexdigest(),
        'status': 'PREPARED_NOT_EXECUTED',
        'scope': 'actual upstream transfer ownership; manual exactly-once completion, no OS/USB',
    }
    (output / 'preparation.json').write_text(json.dumps(record, indent=2) + '\n')
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.archive, args.output))
