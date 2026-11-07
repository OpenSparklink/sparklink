#!/usr/bin/env python3
"""Minimal retired-entry guard; actual ELF/D-Bus/CLI tests remain independent.

Checks declared production source surfaces, not macro expansion, runtime behavior,
all exported APIs, memory safety, authority or a proof of architectural refinement.
"""
from pathlib import Path
import ast
import json
import re

ROOT = Path(__file__).resolve().parents[1]
RAW_STRING = re.compile(r'(?:br|r)(#{0,255})"')
CHARACTER = re.compile(r"'(?:\\.|[^'\\\n])'")


def argument_match_ranges(text):
    """Exclude positional argument selectors from the root command surface.

    This is a limited source guard, not a Rust AST or interface proof. Mask
    strings/comments before balancing braces; malformed input fails closed.
    Root labels and the existing dangling-label negative controls stay checked.
    """
    code=list(text);i=0
    while i<len(text):
        start=i
        if text.startswith('//',i):
            end=text.find('\n',i);i=len(text) if end<0 else end
        elif text.startswith('/*',i):
            depth=1;i+=2
            while depth and i<len(text):
                if text.startswith('/*',i):depth+=1;i+=2
                elif text.startswith('*/',i):depth-=1;i+=2
                else:i+=1
            if depth:raise ValueError('unterminated Rust comment')
        else:
            raw=RAW_STRING.match(text,i)
            if raw:
                end=text.find('"'+raw[1],raw.end())
                if end<0:raise ValueError('unterminated raw Rust string')
                i=end+1+len(raw[1])
            elif text[i]=='"':
                i+=1
                while i<len(text) and text[i]!='"':
                    i+=2 if text[i]=='\\' else 1
                if i>=len(text):raise ValueError('unterminated Rust string')
                i+=1
            elif (character:=CHARACTER.match(text,i)):
                i=character.end()
            else:i+=1;continue
        code[start:i]=['\n' if c=='\n' else ' ' for c in text[start:i]]
    masked=''.join(code);ranges=[]
    for match in re.finditer(r'\bmatch\s+args\s*\[\s*[1-9][0-9]*\s*\]\s*\{',masked):
        depth=1;i=match.end()
        while depth and i<len(masked):
            if masked[i]=='{':depth+=1
            elif masked[i]=='}':depth-=1
            i+=1
        if depth:raise ValueError('unbalanced argument match')
        ranges.append((match.start(),i))
    return ranges


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
    if 'impl AdapterIface {' not in text:
        errors.append('missing Adapter interface boundary')
    if 'DeviceIface' in text or 'org.sparklink.Device' in text:
        errors.append('retired address-only Device interface')
    retired=set(policy['adapter_methods']) | set(policy['device_methods'])
    for name in set(re.findall(r'^\s*async fn (\w+)',text,re.M)) & retired:
        errors.append(f'retired adapter/device method: {name}')
    reject('python_types','bindings/python/sparklink/structs.py',r'^class (\w+)\(')
    path='crates/slctl/src/commands.rs'
    if path not in files:errors.append('missing current source: '+path)
    else:
        try:ranges=argument_match_ranges(files[path])
        except ValueError as error:errors.append('invalid slctl command surface: '+str(error))
        else:
            for match in re.finditer(r'"([a-z][a-z-]*)"\s*(?:if[^\n]*?)?=>',files[path]):
                if match[1] in policy['slctl_commands'] and not any(start<=match.start()<end for start,end in ranges):
                    errors.append(f'retired slctl_commands: {path}:{match[1]}')
    for name in policy['slkconfig_variants']:
        text = files.get('crates/slkconfig/src/main.rs','')
        if 'enum Command {' not in text:
            errors.append('missing actual slkconfig Command enum')
            break
        command = text.split('enum Command {',1)[1].split('\n}',1)[0]
        if re.search(r'^\s*'+re.escape(name)+r'\b',command,re.M):
            errors.append('retired slkconfig variant: '+name)
    for path,commands in policy.get('retired_tool_commands',{}).items():
        text=files.get(path)
        if text is None:
            errors.append('missing current tool source: '+path);continue
        try:tree=ast.parse(text)
        except SyntaxError:
            errors.append('invalid current tool source: '+path);continue
        for call in ast.walk(tree):
            if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute):continue
            words=[]
            if call.func.attr=='ctl' and len(call.args)>=2:words=[call.args[1]]
            elif call.func.attr=='command' and call.args and isinstance(call.args[0],(ast.List,ast.Tuple)):words=call.args[0].elts
            for word in words:
                if isinstance(word,ast.Constant) and word.value in commands:
                    errors.append(f'retired live tool command: {path}:{word.value}')
    for path in policy['absent_files']:
        if path in files:
            errors.append('retired production module: '+path)
    return errors


def main():
    policy=json.loads((ROOT/'project/retired-interface-contract.json').read_text())
    paths=['crates/slk-native/src/adapter.rs','crates/slk-native/src/ioctl.rs',
           'crates/slk-native/include/sparklink_native.h','crates/slkd/src/controller.rs',
           'crates/slkd/src/dbus_iface.rs','bindings/python/sparklink/structs.py',
           'crates/slctl/src/commands.rs','crates/slkconfig/src/main.rs',*policy.get('retired_tool_commands',{}),*policy['absent_files']]
    files={path:(ROOT/path).read_text() for path in paths if (ROOT/path).is_file()}
    errors=check(policy,files)
    if errors:raise SystemExit('\n'.join(errors))
    print('Retired entry source guard PASS; not full ABI/runtime/architecture qualification')


if __name__=='__main__':main()
