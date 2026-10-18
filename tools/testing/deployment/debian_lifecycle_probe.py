#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual different-version Debian lifecycle in a marked disposable VM only.

Reuse guest_probe's real system-bus and external SDK consumers. No controller,
USB, protocol fixture or native Grant is created. Input manifests bind both
source archives, actual .deb payloads and matching Python bindings. Passing this
finite pair does not promise arbitrary upgrades, SDK ABI compatibility or Bond
database migration. A host auditor must independently inspect all raw outputs.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from textwrap import dedent
import time
import traceback

PACKAGES = ('sparklink', 'libsparklink0', 'libsparklink-dev')
STAGES = ('install', 'upgrade', 'rollback')
ROLES = ('observer', 'application', 'publisher', 'manager')
SDK_KINDS = ('sparklink', 'sparklink-native')
STAGE_GATES = (
    'apt', 'package-status', 'service-active', 'service-identity', 'config-check',
    *('policy-' + role for role in ROLES), 'python-wheel', 'python-install',
    'external-python',
    *(prefix + kind for kind in SDK_KINDS
      for prefix in ('pkgconfig-', 'compile-', 'external-', 'needed-')),
)
REQUIRED = (
    'apt-update', 'tools', 'version-order', 'source-old', 'source-new',
    'user-observer', 'user-application', 'user-publisher', 'user-manager', 'venv',
    *(stage + '-' + gate for stage in STAGES for gate in STAGE_GATES),
    'remove', 'removed-state', 'journal', 'kernel-log',
)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def actual_scripts(source):
    """Reuse the same committed consumers, including their original assertions."""
    path = source / 'tools/testing/deployment/guest_probe.py'
    strings = [n.value for n in ast.walk(ast.parse(path.read_text()))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    result = {}
    for prefix in ('import dbus,', 'import sparklink,',
                   '#include <sparklink.h>', '#include <sparklink_native.h>'):
        found = [s for s in strings if s.lstrip().startswith(prefix)]
        if len(found) != 1:
            raise ValueError('one actual deployment consumer required: ' + prefix)
        script = dedent(found[0])
        if prefix.startswith('import '):
            compile(script, str(path) + ':' + prefix, 'exec')
        result[prefix] = script
    return result


def complete(gates):
    names = [g['name'] for g in gates]
    return (len(names) == len(set(names)) and set(names) == set(REQUIRED)
            and all(type(g.get('exit')) is int and g['exit'] == 0 for g in gates))


def verify_files(files, root=Path('/')):
    """Compare real installed payload, never the build tree or package database."""
    for name, expected in files.items():
        if not name.startswith('usr/') or '..' in Path(name).parts:
            raise ValueError('only explicit packaged /usr payload permitted')
        path = root / name
        if 'symlink' in expected:
            if not path.is_symlink() or os.readlink(path) != expected['symlink']:
                raise ValueError('installed symlink mismatch: ' + name)
        elif (path.is_symlink() or not path.is_file()
              or digest(path) != expected['sha256']
              or path.stat().st_mode & 0o777 != expected['mode']):
            raise ValueError('installed payload mismatch: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable-guest-only', action='store_true', required=True)
    parser.parse_args()
    marker = Path('/etc/slkr6-disposable-guest')
    if (os.geteuid() != 0 or not marker.is_file()
            or marker.read_text() != 'sparklink-clean-deployment-v1\n'):
        raise SystemExit('dedicated guest marker and guest root required; no action taken')
    if subprocess.check_output(['systemd-detect-virt', '--vm'], text=True).strip() not in ('kvm', 'qemu'):
        raise SystemExit('dedicated QEMU/KVM guest required; no action taken')
    root = Path('/opt/slkr6')
    out = root / 'lifecycle-outputs'
    out.mkdir()  # Do not overwrite any earlier attempt.
    record = dict(schema=1, status='RUNNING_NOT_QUALIFIED', start_ns=time.time_ns(),
                  scope=__doc__, gates=[], stage_snapshots=[], usb_attached=False)

    def save():
        p = out / 'result.tmp'
        p.write_text(json.dumps(record, indent=2) + '\n')
        p.replace(out / 'result.json')

    def check(value, label):
        if not value:
            raise AssertionError(label)

    def run(name, args, timeout=900):
        log = out / (name + '.log')
        check(not log.exists(), 'duplicate gate: ' + name)
        start = time.time_ns()
        with log.open('w') as stream:
            p = subprocess.run(args, env=os.environ | {'DEBIAN_FRONTEND': 'noninteractive'},
                               stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        record['gates'].append(dict(name=name, command=args, exit=p.returncode,
                                   start_ns=start, end_ns=time.time_ns(),
                                   log=log.name, sha256=digest(log)))
        save()
        print('LIFECYCLE_GATE', name, p.returncode, flush=True)
        p.check_returncode()
        return log.read_text()

    def state_snapshot():
        paths = [Path('/etc/sparklink/main.conf'),
                 Path('/etc/sparklink/admin-extra/local.conf'),
                 Path('/var/lib/sparklink/admin-retain')]
        return {str(p): dict(sha256=digest(p), mode=p.stat().st_mode & 0o777,
                            parent_mode=p.parent.stat().st_mode & 0o777) for p in paths}

    try:
        save()
        inputs = json.loads((root / 'lifecycle-inputs.json').read_text())
        check(inputs['schema'] == 1, 'unsupported input schema')
        old, new = inputs['old'], inputs['new']
        check(old['source'] != new['source'] and old['source_archive_sha256'] != new['source_archive_sha256'],
              'distinct actual source archives required')
        check(old['files']['usr/sbin/slkd']['sha256'] != new['files']['usr/sbin/slkd']['sha256'],
              'relabelled daemon cannot qualify different-source upgrade')
        record.update(inputs=inputs, probe_sha256=digest(Path(__file__)),
                      os_release=Path('/etc/os-release').read_text(), kernel=os.uname().release,
                      config_policy='Explicit --force-confold, no general unattended-upgrade claim',
                      sdk_policy='Matching source SDK per stage, no new-SDK/old-runtime compatibility claim')
        run('apt-update', ['apt-get', 'update'])
        run('tools', ['apt-get', 'install', '-y', '--no-install-recommends',
                      'build-essential', 'pkgconf', 'binutils', 'python3-venv',
                      'python3-pip', 'python3-setuptools', 'python3-wheel', 'python3-dbus'])
        run('version-order', ['dpkg', '--compare-versions', old['version'], 'lt', new['version']])
        for label, item in [('old', old), ('new', new)]:
            check(set(item['packages']) == set(PACKAGES), 'exact three-package set required')
            for package in item['packages'].values():
                check(digest(root / package['path']) == package['sha256'], 'package hash mismatch')
            check(digest(root / item['archive']) == item['source_archive_sha256'], 'source hash mismatch')
            source = root / ('lifecycle-source-' + label)
            source.mkdir()
            run('source-' + label, ['tar', '-xf', str(root / item['archive']), '-C', str(source)])
            actual_scripts(source)
        for role, group in zip(ROLES, [None, 'sparklink-apps', 'sparklink-services', 'sparklink']):
            # Install helpers, rather than the harness, create the real role groups.
            # Users start without membership; stage install adds only existing groups.
            run('user-' + role, ['useradd', '--create-home', '--shell', '/bin/sh', 'slkr6-' + role])
        run('venv', ['runuser', '-u', 'slkr6-observer', '--', 'python3', '-m', 'venv', '/home/slkr6-observer/venv'])
        admin_state = None
        prior_owner = prior_pid = None
        for stage, label, item in [('install', 'old', old), ('upgrade', 'new', new), ('rollback', 'old', old)]:
            args = ['apt-get', 'install', '-y', '--no-install-recommends',
                    '-o', 'Dpkg::Options::=--force-confold']
            if stage == 'rollback':
                args.append('--allow-downgrades')
            run(stage + '-apt', args + [str(root / item['packages'][p]['path']) for p in PACKAGES])
            versions = run(stage + '-package-status', ['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Status}\n', *PACKAGES])
            expected = {p: [item['version'], 'install ok installed'] for p in PACKAGES}
            check({v.split('\t')[0]: v.split('\t')[1:] for v in versions.splitlines()} == expected,
                  'actual installed package versions/status mismatch')
            verify_files(item['files'])
            check(run(stage + '-service-active', ['systemctl', 'is-active', 'sparklink']).strip() == 'active', 'service inactive')
            pid = int(subprocess.check_output(['systemctl', 'show', '-p', 'MainPID', '--value', 'sparklink'], text=True))
            check(pid > 1 and digest(Path('/proc') / str(pid) / 'exe') == item['files']['usr/sbin/slkd']['sha256'], 'loaded daemon identity mismatch')
            owner = run(stage + '-service-identity', ['busctl', '--system', 'call', 'org.freedesktop.DBus',
                         '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', 's', 'org.sparklink']).strip()
            check(owner.startswith('s ":') and owner != prior_owner and pid != prior_pid, 'service did not replace owner/process')
            prior_owner, prior_pid = owner, pid
            run(stage + '-config-check', ['/usr/sbin/slkd', '--config', '/etc/sparklink/main.conf', '--check-config'])
            for role, group in zip(ROLES[1:], ['sparklink-apps', 'sparklink-services', 'sparklink']):
                subprocess.run(['usermod', '--append', '--groups', group, 'slkr6-' + role], check=True)
            source = root / ('lifecycle-source-' + label)
            scripts = actual_scripts(source)
            policy = out / (stage + '-policy.py')
            policy.write_text(scripts['import dbus,'])
            for role in ROLES:
                run(stage + '-policy-' + role, ['runuser', '-u', 'slkr6-' + role, '--', 'python3', str(policy), role])
            wheel_dir = out / (stage + '-wheel')
            run(stage + '-python-wheel', ['python3', '-m', 'pip', 'wheel', '--no-cache-dir', '--no-index', '--no-deps',
                '--no-build-isolation', '-w', str(wheel_dir), str(source / 'bindings/python')])
            wheels = list(wheel_dir.glob('*.whl'))
            check(len(wheels) == 1, 'one matching wheel required')
            run(stage + '-python-install', ['runuser', '-u', 'slkr6-observer', '--', '/home/slkr6-observer/venv/bin/pip',
                'install', '--no-index', '--force-reinstall', str(wheels[0])])
            installed_py = Path('/home/slkr6-observer/venv/lib')
            py_matches = list(installed_py.glob('python*/site-packages/sparklink'))
            check(len(py_matches) == 1, 'one installed Python module required')
            for p in (source / 'bindings/python/sparklink').rglob('*.py'):
                check(digest(p) == digest(py_matches[0] / p.relative_to(source / 'bindings/python/sparklink')),
                      'installed Python source mismatch')
            py = out / (stage + '-external.py')
            py.write_text(scripts['import sparklink,'])
            run(stage + '-external-python', ['runuser', '-u', 'slkr6-observer', '--', '/home/slkr6-observer/venv/bin/python', str(py)])
            for kind, header in zip(SDK_KINDS, ['#include <sparklink.h>', '#include <sparklink_native.h>']):
                c = out / (stage + '-' + kind + '.c')
                c.write_text(scripts[header])
                exe = c.with_suffix('')
                flags = shlex.split(run(stage + '-pkgconfig-' + kind, ['pkg-config', '--cflags', '--libs', kind]))
                run(stage + '-compile-' + kind, ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), *flags, '-o', str(exe)])
                run(stage + '-external-' + kind, ['runuser', '-u', 'slkr6-observer', '--', str(exe)])
                needed = run(stage + '-needed-' + kind, ['readelf', '--dynamic', str(exe)])
                check(('libsparklink.so.0' if kind == 'sparklink' else 'libslk_native.so.0') in needed, 'consumer SONAME mismatch')
            if admin_state is None:
                config = Path('/etc/sparklink/main.conf')
                config.write_text(config.read_text() + '\n# R6c administrator-retained setting marker\n')
                config.chmod(0o600)
                config.parent.chmod(0o700)
                extra = config.parent / 'admin-extra/local.conf'
                extra.parent.mkdir(mode=0o700)
                extra.write_text('administrator extra config\n')
                extra.chmod(0o600)
                state = Path('/var/lib/sparklink/admin-retain')
                state.write_text('opaque administrator state, not a trusted Bond\n')
                state.chmod(0o600)
                admin_state = state_snapshot()
            check(state_snapshot() == admin_state, 'administrator config/state/modes changed')
            record['stage_snapshots'].append(dict(stage=stage, source=item['source'], version=item['version'],
                pid=pid, bus_owner=owner, daemon_sha256=digest(Path('/proc') / str(pid) / 'exe'),
                config=admin_state, matching_wheel_sha256=digest(wheels[0]),
                installed_payload_verified=len(item['files'])))
            save()
        run('remove', ['apt-get', 'remove', '-y', *PACKAGES])
        absent = ['usr/sbin/slkd', 'usr/lib/x86_64-linux-gnu/libsparklink.so.0',
                  'usr/lib/x86_64-linux-gnu/libslk_native.so.0', 'usr/include/sparklink.h']
        check(not any((Path('/') / n).exists() or (Path('/') / n).is_symlink() for n in absent), 'packaged files remain')
        check(state_snapshot() == admin_state, 'remove damaged administrator data')
        state = run('removed-state', ['systemctl', 'show', '-p', 'ActiveState', '--value', 'sparklink']).strip()
        check(state in ('inactive', 'failed'), 'removed service still running')
        run('journal', ['journalctl', '--no-pager', '-b', '-u', 'sparklink'])
        run('kernel-log', ['dmesg', '--color=never'])
        check(complete(record['gates']), 'missing/duplicate/failed mandatory gate')
        record['status'] = 'DIFFERENT_VERSION_LIFECYCLE_COMPLETED_INDEPENDENT_AUDIT_PENDING'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error), traceback=traceback.format_exc())
        print(record['traceback'], flush=True)
    finally:
        record['end_ns'] = time.time_ns()
        save()
        os.sync()
        print('LIFECYCLE_FINAL', record['status'], flush=True)
        subprocess.run(['systemctl', 'poweroff'])


if __name__ == '__main__':
    main()
