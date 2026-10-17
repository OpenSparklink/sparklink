#!/usr/bin/env python3
"""Minimal retired-entry guard; actual ELF/D-Bus/CLI tests remain independent.

Checks declared production source surfaces, not macro expansion, runtime behavior,
all exported APIs, memory safety, authority or a proof of architectural refinement.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def check(policy, files):
    if policy.get('schema') != 1:
        raise ValueError('unsupported retired interface contract')
    errors = []
    def reject(key, path, pattern):
        text = files.get(path)
        if text is None:
            errors.append(f'missing current source: {path}')
            return
        names = set(re.findall(pattern, text, re.M))
        for name in sorted(names & set(policy[key])):
            errors.append(f'retired {key}: {path}:{name}')
    reject('native_methods','crates/slk-native/src/adapter.rs',r'^\s*pub\s+(?:async\s+)?fn\s+(\w+)')
    reject('native_ioctl_wrappers','crates/slk-native/src/ioctl.rs',r'nix::\w+!\(\s*(sl_\w+)')
    reject('native_c_symbols','crates/slk-native/include/sparklink_native.h',r'\b(slk_\w+)\s*\(')
    reject('controller_methods','crates/slkd/src/controller.rs',r'^\s*async fn (\w+)')
    text = files.get('crates/slkd/src/dbus_iface.rs','')
    if 'impl DeviceIface {' not in text:
        errors.append('missing Device interface boundary')
    else:
        adapter, device = text.split('impl DeviceIface {',1)
        for key, part in [('adapter_methods',adapter),('device_methods',device)]:
            for name in set(re.findall(r'^\s*async fn (\w+)',part,re.M)) & set(policy[key]):
                errors.append(f'retired {key}: {name}')
    reject('python_types','bindings/python/sparklink/structs.py',r'^class (\w+)\(')
    reject('slctl_commands','crates/slctl/src/commands.rs',r'"([a-z][a-z-]*)"\s*=>')
    for name in policy['slkconfig_variants']:
        text = files.get('crates/slkconfig/src/main.rs','')
        if 'enum Command {' not in text:
            errors.append('missing actual slkconfig Command enum')
            break
        command = text.split('enum Command {',1)[1].split('\n}',1)[0]
        if re.search(r'^\s*'+re.escape(name)+r'\b',command,re.M):
            errors.append('retired slkconfig variant: '+name)
    for path in policy['absent_files']:
        if path in files:
            errors.append('retired production module: '+path)
    return errors


def main():
    policy=json.loads((ROOT/'project/retired-interface-contract.json').read_text())
    paths=['crates/slk-native/src/adapter.rs','crates/slk-native/src/ioctl.rs',
           'crates/slk-native/include/sparklink_native.h','crates/slkd/src/controller.rs',
           'crates/slkd/src/dbus_iface.rs','bindings/python/sparklink/structs.py',
           'crates/slctl/src/commands.rs','crates/slkconfig/src/main.rs',*policy['absent_files']]
    files={path:(ROOT/path).read_text() for path in paths if (ROOT/path).is_file()}
    errors=check(policy,files)
    if errors:raise SystemExit('\n'.join(errors))
    print('Retired entry source guard PASS; not full ABI/runtime/architecture qualification')


if __name__=='__main__':main()
