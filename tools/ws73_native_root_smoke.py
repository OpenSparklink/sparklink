#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Boot a supplied native initramfs against a private Btrfs/NVMe scratch root.

Never attaches host disks, USB devices or a network. Requires accessible KVM,
mkfs.btrfs, readelf, modinfo, a static busybox and a verified native build.
This is a boot-path check, not native-host, firmware or RF acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from ws73_native_build_check import boot_image, elf_header, release_name


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, record):
    path.write_text(json.dumps(record, indent=2) + '\n')


def verify_console(console, release, root_uuid, exit_code):
    """Require boot/root/module evidence together; poweroff alone can be failure."""
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', console)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).replace('\r', '')
    if exit_code != 0:
        raise ValueError('QEMU did not exit successfully')
    if re.search(r'NATIVE_MODULE_FAILURE|Kernel panic|Oops:|BUG:|WARNING:|'
                 r'module verification failed|Boot has failed|Unable to mount root', text):
        raise ValueError('boot/module failure or kernel warning in console')
    markers = [
        'NATIVE_ROOT_MOUNT: /dev/nvme0n1 btrfs',
        'NATIVE_MODULE_RELEASE: ' + release,
        'NATIVE_MODULE_TAINT_BEFORE: 0',
        'NATIVE_MODULE_LOAD: 1', 'NATIVE_MODULE_UNLOAD: 1',
        'NATIVE_MODULE_LOAD: 2', 'NATIVE_MODULE_UNLOAD: 2',
        'NATIVE_MODULE_TAINT_AFTER: 0',
        'NATIVE_MODULE_KERNEL_LOG_BEGIN', 'NATIVE_MODULE_KERNEL_LOG_END',
        'NATIVE_MODULE_SMOKE: PASS (EMPTY_USB_KVM_ONLY)',
    ]
    position = -1
    for marker in markers:
        if text.splitlines().count(marker) != 1:
            raise ValueError('missing or duplicated marker: ' + marker)
        current = text.index(marker)
        if current <= position:
            raise ValueError('out-of-order marker: ' + marker)
        position = current
    kernel_log = text.split('NATIVE_MODULE_KERNEL_LOG_BEGIN\n', 1)[1].split(
        '\nNATIVE_MODULE_KERNEL_LOG_END', 1)[0]
    if not re.search(r'\[\s*0\.000000\] Linux version ' + re.escape(release) + r'\s', kernel_log):
        raise ValueError('complete early kernel log missing')
    if not re.search(r'BTRFS: device fsid ' + re.escape(root_uuid) + r' .* /dev/nvme0n1', kernel_log):
        raise ValueError('expected scratch filesystem UUID not observed')
    if 'nvme nvme0: pci function' not in kernel_log or 'reboot: Power down' not in text:
        raise ValueError('NVMe probe or normal poweroff missing')


def run(args):
    paths = {name: Path(getattr(args, name)).resolve(strict=True)
             for name in ('kernel_manifest', 'kernel', 'initramfs', 'module', 'busybox', 'qemu')}
    qemu_data = Path(args.qemu_data).resolve(strict=True)
    if not qemu_data.is_dir():
        raise ValueError('QEMU data must be a directory')
    manifest = json.loads(paths['kernel_manifest'].read_text())
    if manifest.get('status') != 'NATIVE_BUILD_ARTIFACTS_VERIFIED':
        raise ValueError('native build manifest is not verified')
    release = release_name(manifest['release'])
    if digest(paths['kernel']) != manifest['inputs']['arch/x86/boot/bzImage']['sha256']:
        raise ValueError('kernel does not match verified build')
    boot_image(paths['kernel'])
    elf_header(paths['module'], {1})
    module_info = {}
    for field in ('name', 'vermagic', 'signer', 'sig_hashalgo', 'depends'):
        module_info[field] = subprocess.check_output(
            ['modinfo', '-F', field, str(paths['module'])], text=True).strip()
    if (module_info['name'] != 'sparklink_ws73_usb'
            or module_info['vermagic'].split()[0] != release
            or not module_info['signer'] or module_info['depends']):
        raise ValueError('requires matching signed WS73 module with no dependencies')
    busybox_headers = subprocess.check_output(['readelf', '-l', str(paths['busybox'])], text=True)
    elf_header(paths['busybox'], {2, 3})
    if 'INTERP' in busybox_headers or 'Requesting program interpreter' in busybox_headers:
        raise ValueError('busybox must be static')
    output = Path(args.output).resolve()
    if ',' in str(output):
        raise ValueError('QEMU drive pathname cannot contain commas')
    output.mkdir(mode=0o700)  # Never reuse a disk, transcript or result directory.
    record = {'status': 'PREPARING', 'native_acceptance': False, 'physical_acceptance': False,
              'scope': 'isolated KVM native initramfs/Btrfs/NVMe and empty USB module check',
              'release': release, 'source_head': manifest['source_head'],
              'module_info': module_info, 'inputs': {}}
    result_path = output / 'manifest.json'
    save(result_path, record)
    try:
        inputs = output / 'inputs'
        inputs.mkdir()
        for name, source in paths.items():
            before = digest(source)
            destination = inputs / name
            shutil.copy2(source, destination)
            if digest(destination) != before or digest(source) != before:
                raise ValueError('input changed during snapshot: ' + name)
            record['inputs'][name] = {'source': str(source), 'path': str(destination), 'sha256': before}
            paths[name] = destination
        data_snapshot = inputs / 'qemu-data'
        data_snapshot.mkdir()
        # QEMU's default data lookup is relative to its executable. Make this
        # dependency explicit when moving the binary into the private snapshot.
        for source in sorted(qemu_data.rglob('*')):
            if not source.is_file():
                continue
            relative = source.relative_to(qemu_data)
            destination = data_snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            before = digest(source)
            shutil.copy2(source, destination)
            if digest(destination) != before or digest(source) != before:
                raise ValueError('QEMU data changed during snapshot: ' + str(relative))
            record['inputs']['qemu-data/' + str(relative)] = {
                'source': str(source), 'path': str(destination), 'sha256': before}
        helper = Path(__file__).with_name('ws73_native_module_init.sh')
        root = output / 'root'
        for directory in ('bin', 'sbin', 'etc', 'usr', 'proc', 'sys', 'dev', 'run'):
            (root / directory).mkdir(parents=True)
        shutil.copy2(paths['busybox'], root / 'bin/busybox')
        for applet in ('sh', 'cat', 'dmesg', 'insmod', 'rmmod', 'mount', 'sync', 'uname', 'poweroff'):
            (root / 'bin' / applet).symlink_to('busybox')
        helper_before = digest(helper)
        shutil.copy2(helper, root / 'sbin/init')
        (root / 'sbin/init').chmod(0o755)
        record['helper_sha256'] = digest(root / 'sbin/init')
        if record['helper_sha256'] != helper_before or digest(helper) != helper_before:
            raise ValueError('module init helper changed during snapshot')
        shutil.copy2(paths['module'], root / 'sparklink_ws73_usb.ko')
        (root / 'expected-release').write_text(release + '\n')
        (root / 'etc/os-release').write_text('ID=sparklink-smoke\nNAME="SparkLink isolated smoke root"\n')
        root_uuid = str(uuid.uuid4())
        (root / 'scratch-root-uuid').write_text(root_uuid + '\n')
        disk = output / 'root.btrfs'
        with disk.open('xb') as stream:
            stream.truncate(512 * 1024 * 1024)
        command = ['mkfs.btrfs', '-U', root_uuid, '--rootdir', str(root), str(disk)]
        record.update(uuid=root_uuid, mkfs_command=command)
        with (output / 'mkfs.log').open('xb') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        record['disk_before_sha256'] = digest(disk)
        command = [str(paths['qemu']), '-L', str(data_snapshot), '-machine', 'q35,accel=kvm', '-cpu', 'host',
                   '-m', '2048M', '-smp', '2', '-nodefaults', '-display', 'none',
                   '-monitor', 'none', '-serial', 'stdio', '-no-reboot', '-nic', 'none',
                   '-kernel', str(paths['kernel']), '-initrd', str(paths['initramfs']),
                   '-drive', 'file=' + str(disk) + ',if=none,id=scratch,format=raw',
                   '-device', 'nvme,drive=scratch,serial=SLK_SCRATCH_ONLY',
                   '-append', 'root=UUID=' + root_uuid + ' rootfstype=btrfs rw init=/sbin/init '
                   'console=ttyS0 loglevel=6 log_buf_len=4M panic=1 oops=panic '
                   'rd.plymouth=0 plymouth.enable=0 rd.shell=0 rd.retry=30 rd.timeout=45']
        record.update(status='RUNNING', qemu_command=command, timeout_seconds=args.timeout)
        save(result_path, record)
        with (output / 'console.log').open('xb') as log:
            process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, timeout=args.timeout)
        record['qemu_exit'] = process.returncode
        record['disk_after_sha256'] = digest(disk)
        record['console_sha256'] = digest(output / 'console.log')
        for name, info in record['inputs'].items():
            if digest(info['path']) != info['sha256']:
                raise ValueError('snapshotted input changed: ' + name)
        verify_console((output / 'console.log').read_text(errors='replace'), release, root_uuid,
                       process.returncode)
        record['status'] = 'PASS_ISOLATED_NATIVE_ROOT_SMOKE'
    except (Exception, KeyboardInterrupt) as error:
        record.update(status='FAIL', error=str(error))
        if (output / 'console.log').is_file():
            record['console_sha256'] = digest(output / 'console.log')
        if (output / 'root.btrfs').is_file():
            record['disk_after_sha256'] = digest(output / 'root.btrfs')
        save(result_path, record)
        raise
    save(result_path, record)
    print(json.dumps({'status': record['status'], 'manifest': str(result_path),
                      'native_acceptance': False, 'physical_acceptance': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('kernel-manifest', 'kernel', 'initramfs', 'module', 'busybox', 'qemu', 'qemu-data', 'output'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--timeout', type=int, default=150)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 600:
        parser.error('timeout must be 30..600 seconds')
    run(args)


if __name__ == '__main__':
    main()
