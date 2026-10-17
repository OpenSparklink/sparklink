#!/usr/bin/env python3
"""Check actual default Cargo normal-dependency closures, not protocol behavior.

Native Rust consumers have moved to slk-native. The C/Python facade still
uses Native pending WP18/R3c; this is not the finished application SDK split.
"""
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={
    'slkd':{'slkd','slk-native','slk-channel','slk-protocol'},
    'libsparklink':{'libsparklink','slk-native','slk-channel','slk-protocol'},
    'slk-protocol':{'slk-protocol'},
    'slk-channel':{'slk-channel','slk-protocol'},
    'slk-native':{'slk-native','slk-protocol'},
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


def main():
    workspace=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['members']
    internal={tomllib.loads((ROOT/path/'Cargo.toml').read_text())['package']['name'] for path in workspace}
    for package in ALLOWED:
        # Keep actual default features enabled. Dev dependencies are excluded;
        # an optional test backend accidentally enabled by default must fail.
        command=['cargo','tree','--locked','--color','never','--edges','normal','--prefix','none','-p',package]
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        if result.stderr:print(result.stderr,end='',file=sys.stderr)
        result.check_returncode()
        closure=check_tree(package,result.stdout,internal)
        print(f'{package}: default normal internal closure {closure}')
    print('Default production dependency boundary PASS; not API/RF or complete architecture qualification')


if __name__=='__main__':main()
