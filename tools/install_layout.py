#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Render the installed runtime layout; no service/group/device activation.

DESTDIR is a staging root, never embedded into service or pkg-config paths.
The existing distribution service files remain templates for the private lab too.
"""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import tomllib

from build_resources import workspace, configuration

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ('slkd', 'slkconfig', 'slctl', 'slktest', 'slkmon', 'slkdump')
LIBRARIES = {'liblibsparklink.so': 'libsparklink.so.0', 'libslk_native.so': 'libslk_native.so.0'}


def runtime_path(value):
    # Do not silently misrender systemd specifiers, environment expansions,
    # activation quoting or pkg-config variables. Staging roots may have spaces.
    if (not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./+\-]*', value)
            or value.startswith('//') or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts):
        raise ValueError('runtime path must be canonical absolute ASCII without service/pc metacharacters: ' + str(value))
    return value


def version(source_root=ROOT):
    value = tomllib.loads((source_root / 'Cargo.toml').read_text())['workspace']['package']['version']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('packaging needs an explicit supported workspace version')
    return value


def check_artifacts(directory):
    for name in (*PROGRAMS, *LIBRARIES):
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('regular actual ELF build artifact required: ' + str(path))
    for name, expected in LIBRARIES.items():
        result = subprocess.run(['readelf', '--dynamic', '--wide', str(directory / name)],
                                capture_output=True, text=True, check=True)
        if result.stderr:
            raise ValueError('readelf diagnostic: ' + result.stderr)
        names = re.findall(r'\(SONAME\).*?\[([^\]]+)\]', result.stdout)
        if names != [expected]:
            raise ValueError(f'{name}: expected SONAME {expected}, observed {names}')


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('source template changed; review runtime rendering: ' + before)
    return text.replace(before, after)


def render(sbindir, libdir, includedir, sysconfdir, statedir, prefix, source_root=ROOT):
    for value in [sbindir, libdir, includedir, sysconfdir, statedir, prefix]:
        runtime_path(value)
    command = sbindir + '/slkd --config ' + sysconfdir + '/sparklink/main.conf'
    unit = replace_once((source_root / 'data/systemd/sparklink.service').read_text(),
                        'ExecStart=/usr/sbin/slkd\n', 'ExecStart=' + command + '\n')
    unit = replace_once(unit, 'ReadWritePaths=/var/lib/sparklink\n', 'ReadWritePaths=' + statedir + '\n')
    if statedir != '/var/lib/sparklink':
        # This is an install-created, root-owned reserved directory, not a
        # configurable Bond database. Do not make a second /var/lib directory.
        unit = replace_once(unit, 'StateDirectory=sparklink\n', '')
        unit = replace_once(unit, 'StateDirectoryMode=0700\n', '')
    activation = replace_once((source_root / 'data/dbus/org.sparklink.service').read_text(),
                              'Exec=/usr/sbin/slkd\n', 'Exec=' + command + '\n')
    pcs = {}
    for name in ['sparklink', 'sparklink-native']:
        text = (source_root / f'data/pkgconfig/{name}.pc').read_text()
        for key, value in [('prefix', prefix), ('libdir', libdir), ('includedir', includedir)]:
            text, n = re.subn(r'^' + key + r'=.*$', lambda _: key + '=' + value, text, flags=re.M)
            if n != 1:
                raise ValueError('missing/duplicate pkg-config layout field: ' + key)
        text, n = re.subn(r'^Version: .*$', 'Version: ' + version(source_root), text, flags=re.M)
        if n != 1:
            raise ValueError('missing/duplicate pkg-config version')
        pcs[name + '.pc'] = text
    return {'sparklink.service': unit, 'org.sparklink.service': activation, **pcs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    query = parser.add_mutually_exclusive_group()
    query.add_argument('--print-target', action='store_true')
    query.add_argument('--print-version', action='store_true')
    parser.add_argument('--check-artifacts', type=Path)
    parser.add_argument('--output', type=Path)
    for name in ['prefix', 'sbindir', 'libdir', 'includedir', 'sysconfdir', 'statedir']:
        parser.add_argument('--' + name)
    args = parser.parse_args()
    if args.print_target:
        print(workspace() / configuration()['cargo_native_development_target'])
        return
    if args.print_version:
        print(version())
        return
    if args.check_artifacts:
        check_artifacts(args.check_artifacts)
        return
    if args.output is None or any(getattr(args, key) is None for key in ['prefix', 'sbindir', 'libdir', 'includedir', 'sysconfdir', 'statedir']):
        parser.error('output and complete runtime layout required')
    files = render(args.sbindir, args.libdir, args.includedir, args.sysconfdir, args.statedir, args.prefix)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.output / name
        if path.is_symlink():
            raise ValueError('refuse generated output symlink: ' + str(path))
        path.write_text(text)
        path.chmod(0o644)


if __name__ == '__main__':
    main()
