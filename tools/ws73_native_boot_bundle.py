#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare a private native lab boot payload and an explicit deployment plan.

Does not install, activate a boot entry, alter the default or reboot. Firmware,
board calibration and daemon deployment require separate qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import uuid

from ws73_native_build_check import release_name
from ws73_native_root_smoke import digest, save, verify_console

METADATA = {'modules.order', 'modules.alias', 'modules.alias.bin', 'modules.builtin',
            'modules.builtin.alias.bin', 'modules.builtin.bin', 'modules.builtin.modinfo',
            'modules.dep', 'modules.dep.bin', 'modules.devname', 'modules.softdep',
            'modules.symbols', 'modules.symbols.bin', 'modules.weakdep'}


def staged_modules(directory):
    order = (directory / 'modules.order').read_text().splitlines()
    if not order or len(order) != len(set(order)):
        raise ValueError('empty or duplicate staged module order')
    for item in order:
        path = PurePosixPath(item)
        if (path.is_absolute() or '..' in path.parts or not item.startswith('kernel/')
                or not item.endswith('.ko')):
            raise ValueError('unsafe staged module pathname: ' + item)
    files = []
    for source in sorted(directory.rglob('*')):
        relative = source.relative_to(directory)
        if source.is_symlink():
            if relative == Path('build'):
                continue  # Build-tree pointer is deliberately excluded.
            raise ValueError('unexpected staged symlink: ' + str(relative))
        if source.is_file():
            if (str(relative) not in METADATA
                    and not (str(relative).startswith('kernel/') and str(relative).endswith('.ko'))):
                raise ValueError('unexpected staged file: ' + str(relative))
            if not re.fullmatch(r'[A-Za-z0-9_./+\-]+', str(relative)):
                raise ValueError('unsafe staged filename: ' + str(relative))
            files.append(relative)
        elif not source.is_dir():
            raise ValueError('unexpected staged special file: ' + str(relative))
    actual = {str(item) for item in files if str(item).endswith('.ko')}
    if actual != set(order):
        raise ValueError('staged modules do not exactly match modules.order')
    for name in ('modules.dep', 'modules.dep.bin', 'modules.alias', 'modules.alias.bin',
                 'modules.builtin', 'modules.builtin.modinfo'):
        if Path(name) not in files or (directory / name).stat().st_size == 0:
            raise ValueError('missing staged module metadata: ' + name)
    return files, len(order)


def boot_options(root_uuid, rootflags):
    parsed = uuid.UUID(root_uuid)
    if str(parsed) != root_uuid:
        raise ValueError('canonical root filesystem UUID required')
    if not re.fullmatch(r'subvol=[A-Za-z0-9_./-]+', rootflags):
        raise ValueError('explicit Btrfs subvolume rootflags required')
    if '..' in PurePosixPath(rootflags.split('=', 1)[1]).parts:
        raise ValueError('unsafe Btrfs subvolume')
    return ('root=UUID=' + root_uuid + ' ro rootfstype=btrfs rootflags=' + rootflags
            + ' rd.driver.blacklist=sparklink_ws73_usb modprobe.blacklist=sparklink_ws73_usb')


def check_smoke(smoke_directory, build, kernel, initramfs, module):
    proof = json.loads((smoke_directory / 'manifest.json').read_text())
    if proof.get('status') != 'PASS_ISOLATED_NATIVE_ROOT_SMOKE':
        raise ValueError('successful isolated root smoke required')
    if proof.get('release') != build['release'] or proof.get('source_head') != build['source_head']:
        raise ValueError('root smoke release/source mismatch')
    for name, path in [('kernel', kernel), ('initramfs', initramfs), ('module', module)]:
        if proof['inputs'][name]['sha256'] != digest(path):
            raise ValueError('root smoke tested a different ' + name)
    console = smoke_directory / 'console.log'
    if digest(console) != proof['console_sha256']:
        raise ValueError('root smoke console changed')
    verify_console(console.read_text(errors='replace'), build['release'], proof['uuid'],
                   proof['qemu_exit'])
    return proof


def prepare(args):
    artifacts = Path(args.artifacts).resolve(strict=True)
    build = json.loads((artifacts / 'manifest.json').read_text())
    if build.get('status') != 'NATIVE_BUILD_ARTIFACTS_VERIFIED':
        raise ValueError('verified native build artifact snapshot required')
    release = release_name(build['release'])
    if 'opensparklink-native-lab' not in release:
        raise ValueError('independently named native lab release required')
    staged = Path(args.module_root).resolve(strict=True)
    if staged.name != release:
        raise ValueError('module staging directory release mismatch')
    files, module_count = staged_modules(staged)
    kernel = artifacts / 'artifacts/arch/x86/boot/bzImage'
    for name in ('arch/x86/boot/bzImage', '.config', 'System.map', 'modules.order',
                 'modules.builtin', 'modules.builtin.modinfo'):
        if digest(artifacts / 'artifacts' / name) != build['inputs'][name]['sha256']:
            raise ValueError('artifact snapshot changed: ' + name)
    for name in ('modules.builtin', 'modules.builtin.modinfo'):
        if digest(staged / name) != build['inputs'][name]['sha256']:
            raise ValueError('module staging belongs to a different build: ' + name)
    expected = ['kernel/' + item[:-2] + '.ko'
                for item in (artifacts / 'artifacts/modules.order').read_text().splitlines()
                if item.endswith('.o')]
    if expected != (staged / 'modules.order').read_text().splitlines():
        raise ValueError('staged module order differs from verified full build')
    initramfs = Path(args.initramfs).resolve(strict=True)
    module = staged / 'kernel/drivers/sparklink/sparklink_ws73_usb.ko'
    smoke_directory = Path(args.smoke).resolve(strict=True)
    proof = check_smoke(smoke_directory, build, kernel, initramfs, module)
    options = boot_options(args.root_uuid, args.rootflags)
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700)
    record = {'status': 'PREPARING', 'release': release, 'source_head': build['source_head'],
              'native_acceptance': False, 'physical_acceptance': False, 'host_installation': False,
              'scope': 'offline lab boot payload; deployment and hardware acceptance pending',
              'module_count': module_count, 'root_uuid': args.root_uuid, 'rootflags': args.rootflags,
              'root_smoke_console_sha256': proof['console_sha256'], 'files': {},
              'excluded': ['staged build symlink', 'firmware/calibration/keys', 'daemon and policies'],
              'default_boot_selection': 'unchanged; candidate entry is not activated'}
    manifest = output / 'manifest.json'
    save(manifest, record)
    try:
        cache = subprocess.check_output(['lsinitrd', '-f', 'etc/ld.so.cache', str(initramfs)])
        if not cache.startswith(b'glibc-ld.so.cache1.1'):
            raise ValueError('valid initramfs glibc loader cache required')
        evidence = output / 'evidence'
        evidence.mkdir()
        (evidence / 'ld.so.cache').write_bytes(cache)
        cache_list = subprocess.check_output(['/usr/sbin/ldconfig', '-p', '-C',
                                              str(evidence / 'ld.so.cache')], text=True)
        if 'libc.so.6' not in cache_list or 'ld-linux-x86-64.so.2' not in cache_list:
            raise ValueError('initramfs loader cache missing libc or loader')
        (evidence / 'ldconfig-cache.txt').write_text(cache_list)
        shutil.copy2(smoke_directory / 'manifest.json', evidence / 'root-smoke.json')
        shutil.copy2(smoke_directory / 'console.log', evidence / 'root-smoke-console.log')
        payload = output / 'payload'
        payload.mkdir()

        def copy(source, relative):
            destination = payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            before = digest(source)
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
            if digest(destination) != before or digest(source) != before:
                raise ValueError('source changed during payload snapshot: ' + str(source))
            record['files'][str(relative)] = {'sha256': before, 'size': destination.stat().st_size}

        for source, destination in [
                (kernel, 'boot/vmlinuz-' + release),
                (initramfs, 'boot/initramfs-' + release + '.img'),
                (artifacts / 'artifacts/.config', 'boot/config-' + release),
                (artifacts / 'artifacts/System.map', 'boot/System.map-' + release)]:
            copy(source, Path(destination))
        module_destination = Path('usr/lib/modules') / release
        for relative in files:
            copy(staged / relative, module_destination / relative)
        entry_name = 'opensparklink-native-' + release + '.conf'
        entry = output / entry_name
        entry.write_text('title OpenSparkLink native lab (controlled WS73 load)\nversion '
                         + release + '\nlinux /vmlinuz-' + release + '\ninitrd /initramfs-'
                         + release + '.img\noptions ' + options + '\n')
        record['candidate_entry'] = {'path': entry_name, 'sha256': digest(entry),
                                     'destination': 'boot/loader/entries/' + entry_name}
        units = [module_destination.as_posix()] + [p for p in record['files'] if p.startswith('boot/')]
        plan = {'schema': 1, 'release': release, 'install_units': units,
                'candidate_entry': record['candidate_entry'], 'root_options': options,
                'conditions': ['all destination units absent, no overwrite of existing releases',
                               'privileged deployment and boot-manager default inspection',
                               'retain and verify the current distribution boot entry',
                               'copy modules/kernel first; publish candidate entry last',
                               'record default before and after; never change saved boot selection'],
                'rollback': ['boot the retained distribution kernel first',
                             'verify running release differs from this lab release',
                             'remove only matching recorded candidate entry and install units',
                             'reject removal if installed contents changed or unknown files exist'],
                'not_installed': record['excluded'], 'automatic_reboot': False}
        save(output / 'deployment-plan.json', plan)
        (output / 'SHA256SUMS').write_text(''.join(
            info['sha256'] + '  payload/' + name + '\n' for name, info in sorted(record['files'].items())))
        record.update(status='PRIVATE_NATIVE_BOOT_PAYLOAD_VERIFIED',
                      deployment_plan_sha256=digest(output / 'deployment-plan.json'),
                      checksums_sha256=digest(output / 'SHA256SUMS'),
                      initramfs_cache_sha256=hashlib.sha256(cache).hexdigest())
    except (Exception, KeyboardInterrupt) as error:
        record.update(status='FAIL', error=str(error))
        save(manifest, record)
        raise
    save(manifest, record)
    print(json.dumps({'status': record['status'], 'module_count': module_count,
                      'manifest': str(manifest), 'host_installation': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('artifacts', 'module-root', 'initramfs', 'smoke', 'root-uuid', 'rootflags', 'output'):
        parser.add_argument('--' + name, required=True)
    prepare(parser.parse_args())


if __name__ == '__main__':
    main()
