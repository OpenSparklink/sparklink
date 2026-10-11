#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Snapshot native lab build artifacts without installing or booting anything."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


REQUIRED = {'RUST': 'y', 'SPARKLINK': 'y', 'SPARKLINK_DRIVERS': 'y',
            'SPARKLINK_GENL': 'y', 'SPARKLINK_SLE': 'y', 'SPARKLINK_DEBUGFS': 'y',
            'SPARKLINK_WS73_USB': 'm', 'USB': 'y', 'USB_XHCI_PCI': 'y',
            'USB_MON': 'y', 'IKCONFIG': 'y', 'IKCONFIG_PROC': 'y'}
EXPORTS = {'sparklink_native_register', 'sparklink_native_unregister',
           'sparklink_native_health', 'sparklink_native_receive',
           'sparklink_native_event', 'sparklink_native_snoop_rx',
           'sparklink_native_snoop_tx'}


def configuration(text):
    values = dict(re.findall(r'^CONFIG_([A-Z0-9_]+)=(.*)$', text, re.M))
    for name, value in REQUIRED.items():
        if values.get(name, 'n') != value:
            raise ValueError('native lab requires CONFIG_'+name+'='+value)
    if values.get('SPARKLINK_VIRTUAL', 'n') != 'n':
        raise ValueError('native lab must not include the virtual controller')
    return values


def release_name(text):
    release = text.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}', release):
        raise ValueError('unsafe or empty kernel release')
    return release


def elf_header(path, types):
    with path.open('rb') as stream:
        header = stream.read(64)
    if len(header) != 64 or header[:6] != b'\x7fELF\x02\x01':
        raise ValueError(str(path)+': x86_64 little-endian ELF required')
    kind, machine = struct.unpack_from('<HH', header, 16)
    if machine != 62 or kind not in types:
        raise ValueError(str(path)+': wrong ELF architecture/type')


def boot_image(path):
    with path.open('rb') as stream:
        header = stream.read(0x206)
    if len(header) < 0x206 or header[0x1fe:0x200] != b'\x55\xaa' or header[0x202:0x206] != b'HdrS':
        raise ValueError('x86 Linux boot image header required')


def native_exports(text):
    rows = [line.split() for line in text.splitlines() if line.strip()]
    for name in EXPORTS:
        matches = [r for r in rows if len(r) >= 4 and r[1] == name]
        if len(matches) != 1 or matches[0][2:4] != ['vmlinux', 'EXPORT_SYMBOL_GPL']:
            raise ValueError('native built-in GPL export missing/ambiguous: '+name)


def completed_build(record, head, config_hash):
    if record.get('status') != 'BUILD_PASSED' or record.get('build_exit') != 0:
        raise ValueError('completed successful build record required; a live/failed build cannot be accepted')
    if record.get('source_head') != head or record.get('normalized_config_sha256') != config_hash:
        raise ValueError('build preparation record does not match source/config')
    if record.get('source_unchanged') is not True or record.get('config_unchanged') is not True:
        raise ValueError('source/config stability was not established by the build recorder')


def file_record(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return {'path': str(path.resolve()), 'size': path.stat().st_size, 'sha256': digest.hexdigest()}


def collect(args):
    build, source = args.build.resolve(), args.source.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if head != args.source_head or subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True):
        raise ValueError('expected clean kernel source HEAD required')
    config = configuration((build/'.config').read_text())
    release = release_name((build/'include/config/kernel.release').read_text())
    record = json.loads(args.build_record.read_text())
    completed_build(record, head, file_record(build/'.config')['sha256'])
    module = build/'drivers/sparklink/sparklink_ws73_usb.ko'
    elf_header(module, {1}); elf_header(build/'vmlinux', {2, 3})
    boot_image(build/'arch/x86/boot/bzImage')
    embedded = subprocess.check_output([str(source/'scripts/extract-ikconfig'),
                                        str(build/'arch/x86/boot/bzImage')])
    if embedded != (build/'.config').read_bytes():
        raise ValueError('boot image embedded configuration differs from build configuration')
    native_exports((build/'Module.symvers').read_text())
    symbols = (build/'System.map').read_text()
    for name in EXPORTS | {'sparklink_native_health_rust'}:
        if not re.search(r'^\S+ [Tt] '+re.escape(name)+r'$', symbols, re.M):
            raise ValueError('linked native symbol missing: '+name)
    info = {name: subprocess.check_output(['modinfo', '-F', name, str(module)], text=True).strip()
            for name in ['name', 'vermagic', 'license', 'depends', 'signer']}
    if info['name'] != 'sparklink_ws73_usb' or not info['vermagic'] or info['vermagic'].split()[0] != release or info['license'] != 'GPL':
        raise ValueError('WS73 module identity/license/vermagic mismatch')
    ordered = (build/'modules.order').read_text().splitlines()
    # This kernel lists relocatable .o inputs; modfinal produces their .ko files.
    if ordered.count('drivers/sparklink/sparklink_ws73_usb.o') != 1:
        raise ValueError('built module missing/duplicated in modules.order')
    files = ['.config', 'include/config/kernel.release', 'arch/x86/boot/bzImage',
             'System.map', 'Module.symvers', 'modules.order', 'modules.builtin',
             'modules.builtin.modinfo', 'drivers/sparklink/sparklink_ws73_usb.ko']
    inputs = {name: file_record(build/name) for name in files}
    inputs['vmlinux'] = file_record(build/'vmlinux')
    # A complete build and exact artifact identities are prerequisites, not RF,
    # bootability, firmware, board qualification or native recovery acceptance.
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in files:
        target = output/'artifacts'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(build/name, target); target.chmod(0o600)
        if file_record(target)['sha256'] != inputs[name]['sha256']:
            raise ValueError('artifact changed during snapshot: '+name)
    for name, saved in inputs.items():
        if file_record(build/name) != saved:
            raise ValueError('build artifact changed during verification: '+name)
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() != head or subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True):
        raise ValueError('kernel source changed during verification')
    result = {'status': 'NATIVE_BUILD_ARTIFACTS_VERIFIED', 'physical_acceptance': False,
              'native_acceptance': False, 'scope': 'offline native lab artifact check only',
              'source_head': head, 'release': release, 'configuration': config,
              'module_info': info, 'inputs': inputs, 'build_record': file_record(args.build_record),
              'limits': ['No installation, boot entry, initramfs generation, module loading or USB access.',
                         'Snapshot is not a complete boot/install bundle; other modules/dependencies are not staged.',
                         'Source HEAD/config agreement does not independently prove all compiler input provenance.',
                         'Boot, qualified board/firmware and native single/multi-device recovery remain required.']}
    (output/'manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result['status']+': '+release+'; native_acceptance=false')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-head', required=True)
    parser.add_argument('--build-record', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new private snapshot directory')
    collect(parser.parse_args())
