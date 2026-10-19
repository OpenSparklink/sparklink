#!/usr/bin/env python3
"""Check actual default/all-features Cargo normal-dependency closures, not protocol behavior.

Native Rust consumers have moved to slk-native. The application client and C/Python surfaces use independent libraries.
This gate checks dependencies,not full API or lifecycle qualification.
"""
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={
    'slkd':{'slkd','slk-native','slk-channel','slk-contract','slk-protocol'},
    'libsparklink':{'libsparklink','slk-channel','slk-contract','slk-protocol'},
    'slk-protocol':{'slk-protocol'},
    'slk-channel':{'slk-channel','slk-protocol'},
    'slk-native':{'slk-native','slk-protocol'},
    'slk-contract':{'slk-contract','slk-protocol'},
    'slktest':{'slktest','libsparklink','slk-channel','slk-contract','slk-protocol'},
    'slctl':{'slctl','libsparklink','slk-channel','slk-contract','slk-protocol'},
}


def check_tree(package,output,internal_names):
    rows=output.splitlines()
    if not rows or not re.match(r'^'+re.escape(package)+r' v[0-9]',rows[0]):
        raise ValueError(f'{package}: missing actual root package')
    names=set()
    for row in rows:
        match=re.match(r'^([a-zA-Z0-9_-]+) v[0-9]',row)
        if not match:raise ValueError(f'{package}: unrecognized Cargo tree line: {row!r}')
        names.add(match[1])
    forbidden=(names&internal_names)-ALLOWED[package]
    if forbidden:raise ValueError(f'{package}: forbidden internal normal dependency: {sorted(forbidden)}')
    return sorted(names&internal_names)


def check_native_creators(files):
    """Named source regression guard, not Rust alias/macro or runtime proof.

    Privileged controller sockets/ioctls belong to Native. Ordinary authorized-fd
    operations remain in Channel; D-Bus/daemon policy is not a second creator.
    """
    pattern=r'\b(?:nix::)?libc::(?:socket|bind|connect)\s*\(|\bnix::ioctl_(?:read|write)[a-z_]*\s*!'
    for name,source in files:
        if re.search(pattern,source):raise ValueError(f'{name}: direct Native creator/ioctl outside slk-native')


def check_authorizer_contract(files):
    """Named retirement guard, not a complete Rust/type dependency analysis.

    These tuples describe local D-Bus policy, not SSAP packets or kernel ABI.
    No compatibility re-export may restore their retired protocol-layer home.
    """
    for name,source in files:
        if ('slk-protocol/' in name
                and re.search(r'\bSsapAuthorization(?:Identity|Prompt)\b',source)):
            raise ValueError(f'{name}: D-Bus authorizer contract belongs to slk-contract')
        if re.search(r'slk_protocol\s*::\s*ssap\s*::\s*(?:\{[^}]*\b)?SsapAuthorization(?:Identity|Prompt)\b',source):
            raise ValueError(f'{name}: retired protocol-layer authorizer import')


def main():
    workspace=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['members']
    internal={tomllib.loads((ROOT/path/'Cargo.toml').read_text())['package']['name'] for path in workspace}
    check_native_creators((str(p.relative_to(ROOT)),p.read_text())for directory in ['crates/slkd/src','crates/slk-contract/src']for p in (ROOT/directory).rglob('*.rs'))
    check_authorizer_contract((p.relative_to(ROOT).as_posix(),p.read_text())for p in (ROOT/'crates').rglob('*.rs'))
    for mode in ['default','all-features']:
        for package in ALLOWED:
            # Dev fixtures remain excluded. Optional production features must
            # not introduce a second Host, the application client or test backend.
            command=['cargo','tree','--locked','--color','never','--edges','normal','--prefix','none','-p',package]
            if mode=='all-features':command.append('--all-features')
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            if result.stderr:print(result.stderr,end='',file=sys.stderr)
            result.check_returncode()
            closure=check_tree(package,result.stdout,internal)
            print(f'{package}: {mode} normal internal closure {closure}')
    print('Default/all-features production dependency boundary PASS; not API/RF or complete architecture qualification')



if __name__=='__main__':main()
