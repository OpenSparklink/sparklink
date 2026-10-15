#!/usr/bin/env python3
"""Static check of published Python snippets, without importing/opening devices.

Checks syntax and direct Adapter/NativeAdapter calls against production AST.
It does not execute examples or establish ABI, permission or device qualification.
"""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def check_python_examples(text, root=ROOT):
    methods = {}
    for source in ('adapter.py', 'native.py'):
        tree = ast.parse((root / 'bindings/python/sparklink' / source).read_text())
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods[node.name] = {x.name for x in node.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}
    blocks = re.findall(r'^```python\n(.*?)^```', text, re.M | re.S)
    errors = []
    if not blocks:
        return ['missing required Python usage example']
    for i, block in enumerate(blocks, 1):
        try:
            tree = ast.parse(block)
        except SyntaxError as exc:
            errors.append(f'example {i}: {exc}')
            continue
        bindings = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
                call = node.context_expr
                if isinstance(call.func, ast.Name) and call.func.id in methods and isinstance(node.optional_vars, ast.Name):
                    bindings[node.optional_vars.id] = call.func.id
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                if node.value.func.id in methods:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            bindings[target.id] = node.value.func.id
        seen = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                owner = bindings.get(node.func.value.id)
                if owner:
                    seen = True
                    if node.func.attr not in methods[owner]:
                        errors.append(f'example {i}: {owner}.{node.func.attr} is absent from production source')
        if not seen:
            errors.append(f'example {i}: no checked production binding call')
    return errors


def main():
    errors = check_python_examples((ROOT / 'bindings/python/README.md').read_text())
    if errors:
        print('\n'.join(errors))
        return 1
    print('Python documentation example static contract PASS (no execution/device qualification)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
