#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install/rollback a verified lab payload in an explicit root (never reboot).

Real-host operations require root and a readable grubby default. Test roots do
not qualify a real boot manager. Existing releases and entries are never replaced.
"""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from ws73_native_boot_bundle import METADATA, boot_options
from ws73_native_build_check import release_name
from ws73_native_root_smoke import digest


def safe_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('unsafe deployment path')
    result = root
    for part in path.parts:
        result = result / part
        if result.is_symlink():
            raise ValueError('symlink in deployment path: ' + str(result))
    return result


def regular_tree(root):
    files = {}
    directories = set()
    for item in root.rglob('*'):
        if item.is_symlink():
            raise ValueError('symlink in installed/payload tree')
        relative = item.relative_to(root).as_posix()
        if item.is_file():
            files[relative] = {'sha256': digest(item), 'size': item.stat().st_size}
        elif item.is_dir():
            directories.add(relative)
        else:
            raise ValueError('special file in installed/payload tree')
    allowed = set()
    for name in files:
        allowed.update(parent.as_posix() for parent in Path(name).parents if parent != Path('.'))
    if directories != allowed:
        raise ValueError('unexpected empty directory in installed/payload tree')
    return files


def bundle_info(bundle):
    manifest = bundle / 'manifest.json'
    record = json.loads(manifest.read_text())
    if record.get('status') != 'PRIVATE_NATIVE_BOOT_PAYLOAD_VERIFIED':
        raise ValueError('verified private boot payload required')
    release = release_name(record['release'])
    if 'opensparklink-native-lab' not in release:
        raise ValueError('lab release required')
    module_prefix = 'usr/lib/modules/' + release + '/'
    boot_files = {'boot/vmlinuz-' + release, 'boot/initramfs-' + release + '.img',
                  'boot/config-' + release, 'boot/System.map-' + release}
    expected = record['files']
    if not boot_files.issubset(expected):
        raise ValueError('incomplete lab boot payload')
    for name in expected:
        safe_path(bundle / 'payload', name)
        if name in boot_files:
            continue
        if not name.startswith(module_prefix):
            raise ValueError('payload contains unrelated destination')
        relative = name[len(module_prefix):]
        if relative not in METADATA and not (relative.startswith('kernel/') and relative.endswith('.ko')):
            raise ValueError('payload contains unrelated module file')
    if regular_tree(bundle / 'payload') != expected:
        raise ValueError('payload files changed or unknown files present')
    for filename, key in [('deployment-plan.json', 'deployment_plan_sha256'),
                          ('SHA256SUMS', 'checksums_sha256')]:
        if digest(safe_path(bundle, filename)) != record[key]:
            raise ValueError('bundle plan/checksums changed')
    entry = record['candidate_entry']
    entry_name = 'opensparklink-native-' + release + '.conf'
    if entry['path'] != entry_name or entry['destination'] != 'boot/loader/entries/' + entry_name:
        raise ValueError('unexpected BLS candidate path')
    candidate = safe_path(bundle, entry_name)
    if digest(candidate) != entry['sha256']:
        raise ValueError('BLS candidate changed')
    options = boot_options(record['root_uuid'], record['rootflags'])
    wanted = ('title OpenSparkLink native lab (controlled WS73 load)\nversion ' + release
              + '\nlinux /vmlinuz-' + release + '\ninitrd /initramfs-' + release
              + '.img\noptions ' + options + '\n')
    if candidate.read_text() != wanted:
        raise ValueError('BLS candidate references unexpected image/options')
    units = [module_prefix[:-1]] + sorted(boot_files) + [entry['destination']]
    return record, units, digest(manifest)


def default_kernel(root):
    if root != Path('/'):
        return None  # Only filesystem lifecycle is tested with a scratch root.
    if os.geteuid() != 0:
        raise PermissionError('real-host deployment requires sudo/root')
    value = subprocess.check_output(['grubby', '--default-kernel'], text=True).strip()
    if not value.startswith('/boot/vmlinuz-') or '\n' in value:
        raise ValueError('readable distribution default kernel required')
    return value


def journal_path(root, release):
    parent = safe_path(root, 'var/lib/opensparklink/native-lab')
    parent.mkdir(parents=True, exist_ok=True)
    return safe_path(root, 'var/lib/opensparklink/native-lab/' + release + '.json')


def write_journal(path, value, initial=False):
    if initial:
        with path.open('x') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.journal-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(source, destination):
    """Copy beside final path, then atomically publish without replacing it."""
    if not destination.parent.is_dir():
        raise ValueError('deployment parent must exist: ' + str(destination.parent))
    staging = Path(tempfile.mkdtemp(prefix='.opensparklink-stage-', dir=destination.parent))
    temporary = staging / 'unit'
    try:
        if source.is_dir():
            shutil.copytree(source, temporary, copy_function=shutil.copyfile)
            for item in temporary.rglob('*'):
                item.chmod(0o755 if item.is_dir() else 0o644)
            temporary.chmod(0o755)
        else:
            shutil.copyfile(source, temporary)
            temporary.chmod(0o644)
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temporary), -100, os.fsencode(destination), 1) != 0:
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise FileExistsError('deployment destination already exists: ' + str(destination))
            raise OSError(code, os.strerror(code))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def unit_matches(root, bundle, record, unit):
    destination = safe_path(root, unit)
    if unit == record['candidate_entry']['destination']:
        return destination.is_file() and digest(destination) == record['candidate_entry']['sha256']
    if unit.startswith('boot/'):
        return destination.is_file() and {'sha256': digest(destination), 'size': destination.stat().st_size} == record['files'][unit]
    if not destination.is_dir():
        return False
    prefix = unit + '/'
    expected = {key[len(prefix):]: value for key, value in record['files'].items() if key.startswith(prefix)}
    return regular_tree(destination) == expected


def remove_units(root, bundle, record, units):
    # Validate every unit before deleting any. Never recursively delete a tree
    # containing an unknown file, a changed binary, or an unexpected symlink.
    present = [unit for unit in units if safe_path(root, unit).exists()]
    for unit in present:
        if not unit_matches(root, bundle, record, unit):
            raise ValueError('installed content changed; removal refused: ' + unit)
    for unit in reversed(present):
        destination = safe_path(root, unit)
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()


def install(bundle, root):
    record, units, bundle_hash = bundle_info(bundle)
    before = default_kernel(root)
    if root == Path('/') and os.uname().release == record['release']:
        raise ValueError('cannot install over the currently running lab release')
    for unit in units:
        destination = safe_path(root, unit)
        if destination.exists() or not destination.parent.is_dir():
            raise ValueError('destination collision or missing parent: ' + unit)
    path = journal_path(root, record['release'])
    if path.exists():
        old = json.loads(path.read_text())
        if (old.get('status') not in ('ROLLED_BACK', 'INSTALL_FAILED_ROLLED_BACK')
                or old.get('bundle_sha256') != bundle_hash or old.get('root') != str(root)):
            raise ValueError('existing installation journal must be resolved first')
        path.rename(path.with_name(path.stem + '.completed-' + str(uuid.uuid4()) + '.json'))
    state = {'status': 'INSTALLING', 'root': str(root), 'release': record['release'],
             'bundle_sha256': bundle_hash, 'default_before': before, 'planned_units': units,
             'completed_units': [], 'host_installation': root == Path('/'),
             'native_acceptance': False, 'physical_acceptance': False}
    write_journal(path, state, initial=True)
    try:
        for unit in units:
            source = (bundle / record['candidate_entry']['path']
                      if unit == record['candidate_entry']['destination'] else bundle / 'payload' / unit)
            publish(source, safe_path(root, unit))
            state['completed_units'].append(unit)
            write_journal(path, state)
            if not unit_matches(root, bundle, record, unit):
                raise ValueError('published content does not match bundle: ' + unit)
        after = default_kernel(root)
        if after != before:
            raise ValueError('default kernel changed after publishing candidate')
        state.update(status='INSTALLED', default_after=after)
    except (Exception, KeyboardInterrupt) as error:
        state.update(status='INSTALL_FAILED', error=str(error))
        try:
            remove_units(root, bundle, record, state['completed_units'])
            if default_kernel(root) != before:
                raise ValueError('boot-manager default not restored after removing failed install')
            state['status'] = 'INSTALL_FAILED_ROLLED_BACK'
        except Exception as cleanup_error:
            state['cleanup_error'] = str(cleanup_error)
        write_journal(path, state)
        raise
    write_journal(path, state)
    return state


def rollback(bundle, root):
    record, units, bundle_hash = bundle_info(bundle)
    path = safe_path(root, 'var/lib/opensparklink/native-lab/' + record['release'] + '.json')
    state = json.loads(path.read_text())
    if (state.get('root') != str(root) or state.get('release') != record['release']
            or state.get('bundle_sha256') != bundle_hash or state.get('planned_units') != units):
        raise ValueError('installation journal does not match bundle/root')
    if state.get('status') not in ('INSTALLED', 'INSTALLING', 'INSTALL_FAILED', 'ROLLED_BACK'):
        raise ValueError('journal is not a rollback candidate')
    if root == Path('/') and os.uname().release == record['release']:
        raise ValueError('boot retained distribution kernel before removing lab release')
    if default_kernel(root) != state['default_before']:
        raise ValueError('boot-manager default changed; restore retained distribution default first')
    remove_units(root, bundle, record, units)
    state['status'] = 'ROLLED_BACK'
    write_journal(path, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'install', 'rollback'])
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--target-root', required=True)
    args = parser.parse_args()
    bundle = Path(args.bundle).resolve(strict=True)
    root = Path(args.target_root).resolve(strict=True)
    if args.operation == 'check':
        record, units, _ = bundle_info(bundle)
        print(json.dumps({'status': 'BUNDLE_VERIFIED', 'release': record['release'], 'units': units}))
    else:
        state = install(bundle, root) if args.operation == 'install' else rollback(bundle, root)
        print(json.dumps({'status': state['status'], 'root': str(root),
                          'host_installation': state['host_installation'], 'native_acceptance': False}))


if __name__ == '__main__':
    main()
