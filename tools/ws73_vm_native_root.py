#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private VM root profile; never install files or services on the host.

Reuse a verified scratch-root boot and signed modules. This extends the target
guest, not the native-host acceptance matrix or a systemd sandbox qualification.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from ws73_native_root_smoke import digest
from ws73_native_service_bundle import PROGRAMS, source_state
from ws73_north_star import file_record
from ws73_discovery_policy_capture import normalized_dump
from install_layout import LIBRARIES

OPTIONS = ('native_module_tree', 'native_boot_smoke', 'native_service_bundle')


def stage_runtime_libraries(root, libraries, copy_elf):
    """Private fresh VM root only; same actual ABI-major libraries as installation.

    Existing explicit-path probes keep linker aliases to that one runtime copy.
    Validate both SONAMEs/destinations before changing either alias.
    """
    root = root.resolve(strict=True)
    if root == Path('/'):
        raise ValueError('private VM staging root required')
    sources = {path.name: path for path in libraries}
    if len(sources) != len(libraries) or set(sources) != set(LIBRARIES):
        raise ValueError('both current application/Native runtime libraries required')
    directory = root / 'usr/lib'
    directory.resolve().relative_to(root)
    plans = []
    for name, soname in LIBRARIES.items():
        source = sources[name]
        if source.is_symlink() or source.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('actual regular runtime ELF required')
        result = subprocess.run(['readelf', '--dynamic', '--wide', str(source)],
                                capture_output=True, text=True, check=True)
        if result.stderr or re.findall(r'\(SONAME\).*?\[([^\]]+)\]', result.stdout) != [soname]:
            raise ValueError('runtime SONAME mismatch: ' + name)
        target = directory / soname
        alias = directory / soname.rsplit('.', 1)[0]
        if target.exists() or target.is_symlink() or alias.is_symlink() or (alias.exists() and not alias.is_file()):
            raise ValueError('unexpected preexisting VM runtime destination')
        plans.append((source, target, alias, digest(source)))
    for source, target, _, expected in plans:
        copy_elf(source, target, root)
        if digest(target) != expected or digest(source) != expected:
            raise ValueError('runtime changed during VM staging')
    for _, target, alias, _ in plans:
        alias.unlink(missing_ok=True)
        alias.symlink_to(target.name)
    return [file_record(target) for _, target, _, _ in plans]


def enabled(args):
    supplied = [getattr(args, name, None) is not None for name in OPTIONS]
    if any(supplied) and not all(supplied):
        raise ValueError('native VM profile requires module tree, boot smoke and service bundle together')
    if getattr(args, 'native_discovery_config', None) is not None and not all(supplied):
        raise ValueError('discovery config requires the complete native VM profile')
    if getattr(args, 'native_runtime_only', False) and not all(supplied):
        raise ValueError('runtime-only requires the complete native VM profile')
    return all(supplied)


def remove_boot_images(root):
    """Mixed-board adoption must fail on ROM, never download a wrong variant."""
    removed = []
    for directory in ['lib/firmware/sparklink/ws73', 'usr/lib/firmware/sparklink/ws73']:
        for name in ['ws73.bin', 'wifi_cali.bin', 'btc_cali.bin']:
            path = root / directory / name
            if not path.is_file() or path.is_symlink():
                raise ValueError('exact regular staged boot image required: ' + str(path))
            removed.append(dict(path='/' + str(path.relative_to(root)), sha256=digest(path)))
    # Validate the entire set before removing anything. Board inputs remain.
    for row in removed:
        (root / row['path'].lstrip('/')).unlink()
    return removed


def check_runtime_only(package, devices, ports):
    if not package.get('native_vm', {}).get('runtime_only', False):
        return
    for port in ports:
        interfaces = devices.get(port, {}).get('interfaces', [])
        if len(interfaces) != 1 or interfaces[0].get('endpoints') != 5:
            raise ValueError('runtime-only refuses ROM or unknown descriptor mode: ' + port)


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


def freeze_policy_expectation(daemon, target, root, manifest, custom, command=None, result=None):
    before = digest(target)
    if result is None:
        command = [str(daemon), '--check-config', '--dump-ws73-policies', '--config', str(target)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode or digest(target) != before:
        raise ValueError('staged daemon policy expectation rejected or changed')
    data = {'custom_configuration': custom, 'config_sha256': before,
            'daemon_dump': result.stdout, 'policies': normalized_dump(result.stdout)}
    path = root / 'expected-discovery-policies.json'
    path.write_text(json.dumps(data, indent=2) + '\n')
    path.chmod(0o444)
    manifest['policy_expectation'] = {'data': data, 'guest_sha256': digest(path),
                                      'validator': file_record(daemon), 'validation_command': command,
                                      'validation_exit': result.returncode}
    (root / 'expected-discovery-config-sha256').write_text(before + '\n')


def stage_discovery_config(source, daemon, root, manifest):
    """Freeze a private VM config and check it with the exact staged daemon.

    No Python policy parser or firmware-support claim. The source is retained
    in preparation inputs so a concurrent edit fails the final freeze check.
    """
    source = source.resolve(strict=True)
    if not source.is_file() or source.stat().st_size > 65536:
        raise ValueError('discovery config must be a regular file of at most 64 KiB')
    record = file_record(source)
    target = root / 'etc/sparklink/main.conf'
    checked_copy(source, target)
    if digest(target) != record['sha256']:
        raise ValueError('discovery config changed before validation')
    command = [str(daemon), '--check-config', '--dump-ws73-policies', '--config', str(target)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('staged slkd rejected discovery config: ' + result.stderr[-4096:])
    if file_record(source) != record or digest(target) != record['sha256']:
        raise ValueError('discovery config changed during validation')
    freeze_policy_expectation(daemon, target, root, manifest, True, command, result)
    manifest['inputs'].append(record)
    manifest['discovery_config'] = {
        'source': record, 'guest_path': '/etc/sparklink/main.conf',
        'guest_sha256': digest(target), 'validator': file_record(daemon),
        'validation_command': command, 'validation_exit': result.returncode,
        'validation_stdout': result.stdout, 'validation_stderr': result.stderr,
        'firmware_support_acceptance': False, 'custom_policy_rf_acceptance': False,
        'host_installation': False,
    }
    (root / 'expected-discovery-config-sha256').write_text(record['sha256'] + '\n')


def check_discovery_config_gate(package, args):
    """Custom policy first uses the separate two-radio guest lifecycle gate.

    Existing Managed injections and default four-radio acceptance must not
    silently inherit a custom configuration before their verifiers migrate.
    """
    if 'discovery_config' not in package:
        return
    if (args.command != 'run'
            or not (getattr(args, 'qmp_hotplug', False) or getattr(args, 'parallel_pairs', False))
            or any(getattr(args, flag, False) for flag in (
                'fault_recovery', 'daemon_cancel_remove', 'initializer_lifecycle', 'observer_policy', 'daemon_crash',
                'event_copy_verify', 'diagnostic_verify', 'active_deadline_verify',
                'active_close_verify', 'setup_release_verify', 'managed_queue_verify',
                'managed_partial_case', 'daemon_hold_case'))):
        raise ValueError('custom discovery config requires separate QMP or parallel RF gate')
    if getattr(args, 'parallel_pairs', False) and not package.get('policy_expectation', {}).get('data', {}).get('custom_configuration'):
        raise ValueError('custom parallel gate requires frozen policy expectation')


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
    if (service['shared_library'] != service['binary_prefix'] + '/liblibsparklink.so'
            or service['native_shared_library'] != service['binary_prefix'] + '/libslk_native.so'):
        raise ValueError('unexpected application/Native shared library pathname')
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
    native_library = service_path / 'payload' / service['native_shared_library'].lstrip('/')
    manifest['native_runtime_libraries'] = stage_runtime_libraries(
        root, [library, native_library], copy_elf)
    # Small external SDK consumers, isolated from daemon/default production.
    fixtures = source / 'tools/testing/application_client'
    c_probe = root / 'bin/ws73-application-client-c'
    compiled_probe = root.parent / 'application-client-c'
    compiler = Path(shutil.which(os.environ.get('CC', 'cc'))).resolve(strict=True)
    command = [str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-I' + str(source / 'crates/libsparklink/include'),
               str(fixtures / 'client.c'), str(library), '-Wl,-rpath,/usr/lib',
               '-o', str(compiled_probe)]
    subprocess.run(command, check=True)
    copy_elf(compiled_probe, c_probe, root)
    python_probe = root / 'usr/share/sparklink/tools/ws73-application-client.py'
    checked_copy(fixtures / 'client.py', python_probe)
    checked_copy(source / 'tools/ws73_application_client.py',
                 root / 'usr/share/sparklink/tools/ws73_application_client.py')
    checked_copy(source / 'tools/ws73_application_role.py',
                 root / 'usr/share/sparklink/tools/ws73_application_role.py')
    manifest['application_client_tools'] = dict(
        sources=[file_record(fixtures / name) for name in ('client.c', 'client.py')],
        verifier=file_record(source / 'tools/ws73_application_client.py'),
        role_supervisor=file_record(source / 'tools/ws73_application_role.py'),
        c_compile=command, compiler=file_record(compiler),
        compiler_version=subprocess.check_output([str(compiler), '--version'],text=True),
        c=file_record(c_probe), python=file_record(python_probe))
    custom_config = getattr(args, 'native_discovery_config', None)
    if custom_config is not None:
        stage_discovery_config(custom_config, service_path / 'payload' / prefix / 'slkd', root, manifest)
    else:
        freeze_policy_expectation(service_path / 'payload' / prefix / 'slkd',
                                  root / 'etc/sparklink/main.conf', root, manifest, False)
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
                             'kernel_head': smoke['source_head'],
                             'qemu_data': qemu_data,
                             'modules': inputs, 'service_manifest_sha256': digest(service_path / 'manifest.json'),
                             'boot_smoke_manifest_sha256': digest(smoke_path),
                             'userspace_head': service['userspace_head'],
                             'host_installation': False, 'native_host_acceptance': False,
                             'systemd_sandbox_acceptance': False, 'board_qualification': 'NOT_ASSERTED'}
    if getattr(args, 'native_runtime_only', False):
        manifest['native_vm'].update(runtime_only=True, removed_boot_images=remove_boot_images(root))


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
