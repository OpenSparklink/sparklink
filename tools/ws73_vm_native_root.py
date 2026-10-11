#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private VM root profile; never install files or services on the host.

Reuse a verified scratch-root boot and signed modules. This extends the target
guest, not the native-host acceptance matrix or a systemd sandbox qualification.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from ws73_native_root_smoke import digest
from ws73_native_service_bundle import PROGRAMS, source_state
from ws73_north_star import file_record

OPTIONS = ('native_module_tree', 'native_boot_smoke', 'native_service_bundle')


def enabled(args):
    supplied = [getattr(args, name, None) is not None for name in OPTIONS]
    if any(supplied) and not all(supplied):
        raise ValueError('native VM profile requires module tree, boot smoke and service bundle together')
    return all(supplied)


def module_plan(tree):
    """Read the staged dependency closure; never run modprobe on the host."""
    tree = tree.resolve(strict=True)
    release = tree.name
    if tree.parent.name != 'modules' or tree.parent.parent.name != 'lib':
        raise ValueError('module tree must be a staged lib/modules/<release>')
    paths = []
    for name in ('9p', '9pnet_virtio', 'sparklink_ws73_usb'):
        output = subprocess.check_output(['modprobe', '--show-depends', '-d', str(tree.parents[2]),
                                         '-S', release, name], text=True)
        for line in output.splitlines():
            words = line.split()
            if len(words) != 2 or words[0] != 'insmod':
                raise ValueError('unexpected module dependency instruction: ' + line)
            path = Path(words[1]).resolve(strict=True)
            path.relative_to(tree)
            if path not in paths:
                paths.append(path)
    if not paths or paths[-1].name != 'sparklink_ws73_usb.ko':
        raise ValueError('signed uncompressed WS73 module must be last in dependency closure')
    for path in paths:
        fields = {field: subprocess.check_output(['modinfo', '-F', field, str(path)],
                                                 text=True).strip()
                  for field in ('vermagic', 'signer')}
        if fields['vermagic'].split()[0] != release or not fields['signer']:
            raise ValueError('unsigned or mismatched staged module: ' + str(path))
    return release, paths


def checked_copy(source, target):
    before = digest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if digest(source) != before or digest(target) != before:
        raise ValueError('VM input changed while copying: ' + str(source))


def stage(args, manifest, root, source, copy_elf):
    smoke_path = args.native_boot_smoke.resolve(strict=True)
    smoke = json.loads(smoke_path.read_text())
    if smoke.get('status') != 'PASS_ISOLATED_NATIVE_ROOT_SMOKE':
        raise ValueError('successful isolated scratch-root boot proof required')
    release, modules = module_plan(args.native_module_tree)
    if release != smoke['release']:
        raise ValueError('VM module tree and boot proof release differ')
    kernel = args.kernel_build / 'arch/x86/boot/bzImage'
    if digest(kernel) != smoke['inputs']['kernel']['sha256']:
        raise ValueError('VM kernel differs from scratch-root boot proof')
    if digest(modules[-1]) != smoke['inputs']['module']['sha256']:
        raise ValueError('WS73 module differs from signed scratch-root boot proof')
    kernel_manifest_path = Path(smoke['inputs']['kernel_manifest']['path'])
    if digest(kernel_manifest_path) != smoke['inputs']['kernel_manifest']['sha256']:
        raise ValueError('scratch-root kernel manifest changed')
    kernel_manifest = json.loads(kernel_manifest_path.read_text())
    if digest(args.kernel_build / '.config') != kernel_manifest['inputs']['.config']['sha256']:
        raise ValueError('VM config differs from verified kernel build')
    if digest(args.qemu) != smoke['inputs']['qemu']['sha256']:
        raise ValueError('VM QEMU differs from scratch-root boot proof')
    initramfs = Path(smoke['inputs']['initramfs']['path'])
    if digest(initramfs) != smoke['inputs']['initramfs']['sha256']:
        raise ValueError('scratch-root boot initramfs changed')
    service_path = args.native_service_bundle.resolve(strict=True)
    service = json.loads((service_path / 'manifest.json').read_text())
    if (service.get('status') != 'PRIVATE_NATIVE_SERVICE_FILES_STAGED'
            or service['kernel_release'] != release or service['kernel_head'] != smoke['source_head']):
        raise ValueError('verified matching service bundle required')
    if source_state(source)[1] != service['source_hashes']:
        raise ValueError('compiled/policy sources differ from service bundle')
    if not re.fullmatch(r'/usr/libexec/opensparklink/native-lab/[0-9a-f]{12}', service['binary_prefix']):
        raise ValueError('invalid versioned executable prefix')
    if service['shared_library'] != service['binary_prefix'] + '/liblibsparklink.so':
        raise ValueError('unexpected shared library pathname')
    for relative, record in service['files'].items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('invalid service payload pathname')
        original = service_path / 'payload' / path
        original.resolve(strict=True).relative_to((service_path / 'payload').resolve())
        if (original.is_symlink() or digest(original) != record['sha256']
                or original.stat().st_size != record['size']
                or original.stat().st_mode & 0o7777 != int(record['mode'], 8)):
            raise ValueError('service payload changed: ' + relative)
        checked_copy(original, root / path)
    prefix = Path(service['binary_prefix'].lstrip('/'))
    for name in PROGRAMS:
        # Copy the exact release executable and its current ELF dependencies.
        copy_elf(service_path / 'payload' / prefix / name, root / prefix / name, root)
        (root / 'bin' / name).unlink()
        (root / 'bin' / name).symlink_to('/' + str(prefix / name))
    library = service_path / 'payload' / service['shared_library'].lstrip('/')
    copy_elf(library, root / 'usr/lib/liblibsparklink.so', root)
    for name in ('ws73.bin', 'wifi_cali.bin', 'btc_cali.bin', 'bsle_custom.bin', 'pm_config.bin'):
        if digest(root / 'lib/firmware/sparklink/ws73' / name) != digest(
                root / 'usr/lib/firmware/sparklink/ws73' / name):
            raise ValueError('target firmware differs from service bundle: ' + name)
    instructions = []
    inputs = []
    for module in modules:
        relative = module.relative_to(args.native_module_tree.resolve())
        target = root / 'lib/modules' / release / relative
        checked_copy(module, target)
        inputs.append({'path': str(module), 'sha256': digest(module)})
        instructions.append('insmod /lib/modules/' + release + '/' + str(relative))
    # Mount dependencies load before evidence export; WS73 loads after capture.
    (root / 'native-evidence-modules.sh').write_text('\n'.join(
        line + " || fail 'native evidence module'" for line in instructions[:-1]) + '\n')
    (root / 'native-ws73-module.sh').write_text(instructions[-1] + " || fail 'signed WS73 module'\n")
    (root / 'expected-release').write_text(release + '\n')
    (root / 'etc/os-release').write_text('ID=sparklink-vm\nNAME="SparkLink isolated module VM"\n')
    root_uuid = str(uuid.uuid4())
    (root / 'scratch-root-uuid').write_text(root_uuid + '\n')
    checked_copy(initramfs, args.output / 'initramfs.cpio.gz')
    qemu_data = []
    for name, record in smoke['inputs'].items():
        if not name.startswith('qemu-data/'):
            continue
        relative = Path(name)
        if '..' in relative.parts:
            raise ValueError('invalid QEMU data pathname')
        original = Path(record['path'])
        if digest(original) != record['sha256']:
            raise ValueError('scratch-root QEMU data changed: ' + name)
        target = args.output / relative
        checked_copy(original, target)
        qemu_data.append(file_record(target))
    if not qemu_data:
        raise ValueError('explicit verified QEMU data snapshot required')
    manifest['native_vm'] = {'release': release, 'root_uuid': root_uuid,
                             'qemu_data': qemu_data,
                             'modules': inputs, 'service_manifest_sha256': digest(service_path / 'manifest.json'),
                             'boot_smoke_manifest_sha256': digest(smoke_path),
                             'userspace_head': service['userspace_head'],
                             'host_installation': False, 'native_host_acceptance': False,
                             'systemd_sandbox_acceptance': False, 'board_qualification': 'NOT_ASSERTED'}


def pack(args, manifest, root):
    disk = args.output / 'root.btrfs'
    with disk.open('xb') as stream:
        stream.truncate(1024 * 1024 * 1024)
    command = ['mkfs.btrfs', '-U', manifest['native_vm']['root_uuid'], '--rootdir', str(root), str(disk)]
    with (args.output / 'pack.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)


def launch(prepared, output, package):
    """Only copy the sealed private disk. Each VM gets independent writable state."""
    disk = output / 'root.btrfs'
    checked_copy(prepared / 'root.btrfs', disk)
    append = (' root=UUID=' + package['native_vm']['root_uuid']
              + ' rootfstype=btrfs rw init=/init rd.plymouth=0 plymouth.enable=0 '
              'rd.shell=0 rd.retry=30 rd.timeout=45')
    return ['-L', str(prepared / 'qemu-data'),
            '-drive', 'file=' + str(disk) + ',if=none,id=scratch,format=raw',
            '-device', 'nvme,drive=scratch,serial=SLK_VM_ROOT_ONLY'], append
