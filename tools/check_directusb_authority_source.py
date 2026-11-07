#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual standalone build.rs on explicit source-pin inputs; no USB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from build_resources import build_lock, environment


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(kernel, output):
    kernel = kernel.resolve(strict=True)
    original = kernel / 'net/sparklink/sle_grant.rs'
    source = Path(__file__).resolve().parent / 'lab/ws73_directusb_rom/build.rs'
    identities = {'checker': digest(Path(__file__)), 'build_script': digest(source),
                  'production_authority': digest(original)}
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING_NOT_QUALIFIED', 'source_sha256': identities,
              'scope': 'Actual build-script source-pin guard;temporary file/path fixtures,not USB or protocol/formal qualification',
              'started_ns': time.time_ns(), 'cases': []}
    try:
        executable = output / 'actual-build-script'
        command = ['rustc', '+1.96.1', '--edition=2024', str(source), '-o', str(executable)]
        with build_lock() as fd:
            env, budget = environment(dict(os.environ, SPARKLINK_BUILD_WITH_VM='1'))
            with (output / 'compile.log').open('x') as log:
                subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                               pass_fds=(fd,), check=True)
        report.update(compile_command=command, resource_budget=budget, executable_sha256=digest(executable))
        for name in ['exact', 'missing-selection', 'wrong-content', 'oversized-content', 'escaping-symlink']:
            folder = output / name
            folder.mkdir()
            generated = folder / 'out'
            generated.mkdir()
            env = dict(os.environ, OUT_DIR=str(generated))
            env.pop('SPARKLINK_KERNEL_SOURCE', None)
            if name == 'exact':
                env['SPARKLINK_KERNEL_SOURCE'] = str(kernel)
            elif name != 'missing-selection':
                root = folder / 'kernel'
                target = root / 'net/sparklink/sle_grant.rs'
                target.parent.mkdir(parents=True)
                if name == 'wrong-content':
                    target.write_bytes(original.read_bytes() + b'\n// changed input\n')
                elif name == 'oversized-content':
                    target.write_bytes(b'x' * 65537)
                else:
                    target.symlink_to(original)
                env['SPARKLINK_KERNEL_SOURCE'] = str(root)
            result = subprocess.run([str(executable)], env=env, capture_output=True, text=True, timeout=10)
            (folder / 'stdout.log').write_text(result.stdout)
            (folder / 'stderr.log').write_text(result.stderr)
            module = generated / 'production_authority.rs'
            if name == 'exact':
                if result.returncode or result.stderr or not module.is_file():
                    raise ValueError('actual production source must generate its module reference')
                snapshot = generated / 'production_lease_source.rs'
                if snapshot.read_bytes() != original.read_bytes():
                    raise ValueError('compiled snapshot differs from pinned production bytes')
                expected = '#[path = ' + json.dumps(str(snapshot), ensure_ascii=False) + '] mod production_lease;\n'
                if module.read_text() != expected:
                    raise ValueError('generated reference differs from selected exact production source')
            else:
                reason = {'missing-selection': 'explicit SPARKLINK_KERNEL_SOURCE',
                          'wrong-content': 'production authority pin mismatch',
                          'oversized-content': 'production authority source exceeds build input budget',
                          'escaping-symlink': 'authority source escapes selected kernel root'}[name]
                if result.returncode == 0 or reason not in result.stderr or module.exists():
                    raise ValueError('invalid source input was not rejected before module generation: ' + name)
            report['cases'].append({'case': name, 'exit': result.returncode,
                                    'expected_contract_observed': True})
        if identities != {'checker': digest(Path(__file__)), 'build_script': digest(source),
                          'production_authority': digest(original)}:
            raise ValueError('executed source changed during checks')
        report['status'] = 'SOURCE_PIN_GUARDS_ONLY_PASS'
    except BaseException as error:
        report.update(status='FAIL_RETAINED_NOT_QUALIFIED', error=repr(error))
        raise
    finally:
        report['finished_ns'] = time.time_ns()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(check(args.kernel_source, args.output.resolve())['status'])


if __name__ == '__main__':
    main()
