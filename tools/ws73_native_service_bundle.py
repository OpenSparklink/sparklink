#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build and stage native daemon/CLI, policy and WS73 file inputs privately.

No installation, group changes, service activation or device I/O. Board files
are checked as files only; this never asserts board, firmware-runtime or RF
qualification. A separate reviewed deployment step must create/enroll the
control group and test the real system bus and service sandbox.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from ws73_firmware import HEADER, MAX_PAYLOAD, NAMES
from ws73_native_build_check import elf_header, release_name
from ws73_native_root_smoke import digest, save

PROGRAMS = ('slkd', 'slctl', 'slkconfig', 'slkmon', 'slkdump')
SOURCE_SCOPE = ('crates', 'data', 'Cargo.toml', 'Cargo.lock')


def firmware_files(directory, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('explicit combined firmware SHA256 required')
    images = {}
    for name in NAMES:
        path = directory / name
        blob = path.read_bytes()
        if not HEADER < len(blob) <= HEADER + MAX_PAYLOAD:
            raise ValueError('firmware image outside bounded size: ' + name)
        if not re.fullmatch(rb'[0-9a-f]{64}', blob[:HEADER]):
            raise ValueError('invalid firmware header: ' + name)
        if hashlib.sha256(blob[HEADER:]).hexdigest().encode() != blob[:HEADER]:
            raise ValueError('firmware payload hash mismatch: ' + name)
        images[name] = blob
    if hashlib.sha256(b''.join(images[name] for name in NAMES)).hexdigest() != expected:
        raise ValueError('three firmware files do not match selected combined blob')
    return images


def source_state(source):
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *SOURCE_SCOPE], cwd=source):
        raise ValueError('compiled Rust and policy source scope must be clean')
    names = subprocess.check_output(['git', 'ls-files', '--', *SOURCE_SCOPE], cwd=source,
                                    text=True).splitlines()
    return head, {name: digest(source / name) for name in names}


def stage(args):
    source = Path(args.source).resolve(strict=True)
    kernel_manifest = Path(args.kernel_manifest).resolve(strict=True)
    kernel = json.loads(kernel_manifest.read_text())
    if kernel.get('status') != 'NATIVE_BUILD_ARTIFACTS_VERIFIED':
        raise ValueError('verified native kernel artifact manifest required')
    release = release_name(kernel['release'])
    head, source_hashes = source_state(source)
    firmware = Path(args.firmware_dir).resolve(strict=True)
    images = firmware_files(firmware, args.combined_sha256)
    runtime = Path(args.runtime_config_dir).resolve(strict=True)
    board = {}
    for name, size in [('bsle_custom.bin', 140), ('pm_config.bin', 4)]:
        blob = (runtime / name).read_bytes()
        if len(blob) != size:
            raise ValueError('runtime config wrong raw size: ' + name)
        board[name] = blob
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700)
    tool_inputs = {str(Path(__file__).with_name(name)): digest(Path(__file__).with_name(name))
                   for name in ('ws73_native_service_bundle.py', 'ws73_firmware.py',
                                'ws73_native_build_check.py', 'ws73_native_root_smoke.py')}
    record = {'status': 'BUILDING', 'scope': 'private native service and firmware file staging only',
              'userspace_head': head, 'kernel_head': kernel['source_head'], 'kernel_release': release,
              'kernel_manifest_sha256': digest(kernel_manifest),
              'source_scope': list(SOURCE_SCOPE), 'source_hashes': source_hashes,
              'combined_firmware_sha256': args.combined_sha256,
              'board_qualification': 'NOT_ASSERTED', 'firmware_runtime_qualification': 'NOT_ASSERTED',
              'host_installation': False, 'native_acceptance': False, 'physical_acceptance': False,
              'tool_inputs': tool_inputs,
              'files': {}, 'runtime_dependencies': {}}
    manifest = output / 'manifest.json'
    save(manifest, record)
    try:
        build = output / 'build'
        command = ['cargo', 'build', '--offline', '--locked', '--release', '--workspace']
        record.update(build_command=command, target_directory=str(build),
                      rustc=subprocess.check_output(['rustc', '--version'], text=True).strip(),
                      cargo=subprocess.check_output(['cargo', '--version'], text=True).strip())
        save(manifest, record)
        environment = dict(os.environ, CARGO_TARGET_DIR=str(build))
        with (output / 'build.log').open('xb') as log:
            result = subprocess.run(command, cwd=source, env=environment,
                                    stdout=log, stderr=subprocess.STDOUT)
        record['build_exit'] = result.returncode
        if result.returncode != 0 or source_state(source) != (head, source_hashes):
            raise ValueError('build failed or compiled/policy source changed')
        payload = output / 'payload'
        payload.mkdir()
        prefix = Path('usr/libexec/opensparklink/native-lab') / head[:12]

        def write(relative, blob):
            destination = payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(blob)
            destination.chmod(0o644)
            record['files'][str(relative)] = {'sha256': digest(destination), 'size': len(blob), 'mode': '0644'}

        def copy(path, relative, executable=False):
            before = digest(path)
            blob = path.read_bytes()
            write(relative, blob)
            if digest(path) != before or record['files'][str(relative)]['sha256'] != before:
                raise ValueError('source changed during file staging: ' + str(path))
            if executable:
                (payload / relative).chmod(0o755)
            record['files'][str(relative)]['mode'] = '0755' if executable else '0644'

        for name in PROGRAMS:
            binary = build / 'release' / name
            elf_header(binary, {2, 3})
            copy(binary, prefix / name, executable=True)
            dependencies = subprocess.check_output(['ldd', str(binary)], text=True)
            if 'not found' in dependencies:
                raise ValueError('runtime dependency missing: ' + name)
            records = {}
            for filename in re.findall(r'(?:=>\s+)?(/[^\s()]+)', dependencies):
                library = Path(filename)
                if library.is_file():
                    records[filename] = digest(library)
            if not records:
                raise ValueError('no native dynamic dependency record: ' + name)
            record['runtime_dependencies'][name] = records
        metadata = json.loads(subprocess.check_output(
            ['cargo', 'metadata', '--offline', '--locked', '--no-deps', '--format-version', '1'],
            cwd=source, text=True))
        package = next(item for item in metadata['packages'] if item['name'] == 'libsparklink')
        target = next(item for item in package['targets'] if 'cdylib' in item['crate_types'])
        library = build / 'release' / ('lib' + target['name'] + '.so')
        elf_header(library, {3})
        copy(library, prefix / library.name)
        record['shared_library'] = '/' + str(prefix / library.name)
        # Dependencies are recorded, not copied over distribution libraries.
        env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS='unix:path=/tmp/ws73-staging-no-bus.sock',
                   DBUS_SESSION_BUS_ADDRESS='unix:path=/tmp/ws73-staging-no-session-bus.sock')
        queries = {}
        for name, arguments in [('slkd', ['--help']), ('slctl', ['--help']),
                                ('slctl-version', ['--version'])]:
            binary = build / 'release' / name.split('-')[0]
            result = subprocess.run([str(binary), *arguments], env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise ValueError('offline executable query failed: ' + name)
            queries[name] = {'arguments': arguments, 'stdout': result.stdout, 'exit': result.returncode}
        record['offline_queries'] = queries
        for name, blob in images.items():
            write(Path('usr/lib/firmware/sparklink/ws73') / name, blob)
        for name, blob in board.items():
            write(Path('usr/lib/firmware/sparklink/ws73') / name, blob)
        copy(source / 'data/config/main.conf', Path('etc/sparklink/main.conf'))
        copy(source / 'data/dbus/sparklink.conf', Path('etc/dbus-1/system.d/sparklink-native-lab.conf'))
        copy(source / 'data/udev/99-sparklink.rules', Path('etc/udev/rules.d/99-sparklink-native-lab.rules'))
        unit = (source / 'data/systemd/sparklink.service').read_text()
        if unit.count('ExecStart=/usr/sbin/slkd\n') != 1:
            raise ValueError('unexpected source service ExecStart')
        unit = unit.replace('ExecStart=/usr/sbin/slkd\n', 'ExecStart=/' + str(prefix / 'slkd') + '\n')
        write(Path('etc/systemd/system/opensparklink-native-lab.service'), unit.encode())
        activation = ('[D-BUS Service]\nName=org.sparklink\nExec=/' + str(prefix / 'slkd')
                      + '\nUser=root\nSystemdService=opensparklink-native-lab.service\n')
        write(Path('usr/share/dbus-1/system-services/org.sparklink.service'), activation.encode())
        write(Path('usr/lib/sysusers.d/opensparklink-native-lab.conf'), b'g sparklink -\n')
        plan = {'kernel_release': release, 'binary_prefix': '/' + str(prefix),
                'service': 'opensparklink-native-lab.service', 'dbus_name': 'org.sparklink',
                'control_group': 'sparklink', 'default_activation': 'not activated',
                'required': ['refuse overwrite and conflicting existing org.sparklink service/policy',
                             'review board/calibration qualification before loading WS73',
                             'create the control group with administrator/sysusers step',
                             'explicit administrator enrollment of ordinary control user',
                             'reload udev/system D-Bus/systemd and verify actual permissions',
                             'verify actual service startup/sandbox and group/observer policy',
                             'verify per-device Ready, ordinary CLI, RF and recovery matrix'],
                'rollback': ['stop lab service and confirm native OFF cleanup',
                             'remove only unchanged recorded lab files; retain daemon state',
                             'restore/verify prior D-Bus and udev service configuration'],
                'retain_distribution_libraries': True, 'reboot': False}
        save(output / 'deployment-plan.json', plan)
        if any(digest(Path(path)) != expected for path, expected in tool_inputs.items()):
            raise ValueError('staging tool inputs changed during execution')
        record.update(status='PRIVATE_NATIVE_SERVICE_FILES_STAGED', binary_prefix='/' + str(prefix),
                      deployment_plan_sha256=digest(output / 'deployment-plan.json'),
                      tool_sha256=digest(Path(__file__)),
                      source_scope_unchanged=source_state(source) == (head, source_hashes))
        if not record['source_scope_unchanged']:
            raise ValueError('source changed during staging')
    except (Exception, KeyboardInterrupt) as error:
        record.update(status='FAIL', error=str(error))
        save(manifest, record)
        raise
    save(manifest, record)
    print(json.dumps({'status': record['status'], 'files': len(record['files']),
                      'manifest': str(manifest), 'board_qualification': 'NOT_ASSERTED',
                      'host_installation': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'kernel-manifest', 'firmware-dir', 'runtime-config-dir',
                 'combined-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    stage(parser.parse_args())


if __name__ == '__main__':
    main()
