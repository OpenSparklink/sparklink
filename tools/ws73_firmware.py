# SPDX-License-Identifier: GPL-2.0-only
"""Validate a cat-combined SDK blob and export unchanged SDK image files.

The file-format facts are documented in libws73-usb/blobs/README. This is an
independent Python implementation; it performs no device I/O.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

NAMES = ('ws73.bin', 'wifi_cali.bin', 'btc_cali.bin')
HEADER = 64
MAX_PAYLOAD = 204736


def split_combined(blob):
    if not 3 * (HEADER + 1) <= len(blob) <= 3 * (HEADER + MAX_PAYLOAD):
        raise ValueError('combined blob size outside three-image bounds')
    result = {}
    offset = 0
    for name in NAMES:
        header = blob[offset:offset + HEADER]
        if not re.fullmatch(rb'[0-9a-f]{64}', header):
            raise ValueError(f'{name}: invalid lowercase SHA-256 header')
        start = offset + HEADER
        digest = hashlib.sha256()
        end = None
        for position in range(start, min(len(blob), start + MAX_PAYLOAD)):
            digest.update(blob[position:position + 1])
            if digest.hexdigest().encode() == header:
                end = position + 1
                break
        if end is None:
            raise ValueError(f'{name}: no bounded nonempty payload matches header')
        result[name] = blob[offset:end]
        offset = end
    if offset != len(blob):
        raise ValueError('trailing data after three verified images')
    return result


def export_combined(source, output, expected_sha256):
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('expected SHA-256 must be 64 lowercase hex characters')
    if source.stat().st_size > 3 * (HEADER + MAX_PAYLOAD):
        raise ValueError('combined blob too large')
    blob = source.read_bytes()
    actual = hashlib.sha256(blob).hexdigest()
    if actual != expected_sha256:
        raise ValueError('combined blob SHA-256 differs from explicit expected hash')
    images = split_combined(blob)  # Validate every image before creating output.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    records = {}
    for name, image in images.items():
        (output / name).write_bytes(image)
        records[name] = dict(size=len(image), file_sha256=hashlib.sha256(image).hexdigest(),
                             payload_sha256=image[:HEADER].decode())
    receipt = dict(scope='file validation only; no hardware or board qualification',
                   source=str(source.resolve()), combined_sha256=actual, images=records)
    (output / 'firmware-source.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--combined', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_combined(args.combined, args.output, args.sha256), indent=2))


if __name__ == '__main__':
    main()
