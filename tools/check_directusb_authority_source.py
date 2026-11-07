#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual standalone build.rs source-pin controls, including native C; no USB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from build_resources import build_lock, environment

INPUTS = {
    'authority': ('net/sparklink/sle_grant.rs', 65536, 'production authority'),
    'wire-codec': ('drivers/sparklink/ws73/wire.c', 65536, 'production wire codec'),
    'wire-header': ('drivers/sparklink/ws73/wire.h', 16384, 'production wire header'),
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(kernel, output):
    kernel = kernel.resolve(strict=True)
    source = Path(__file__).resolve().parent / 'lab/ws73_directusb_rom/build.rs'
    original = {key: kernel / value[0] for key, value in INPUTS.items()}
    def identities():
        return dict(checker=digest(Path(__file__)), build_script=digest(source),
                    production_inputs={key: digest(path) for key, path in original.items()})
    before = identities()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING_NOT_QUALIFIED', source_sha256=before,
                  scope='Actual build-script source pin and native C compilation;temporary paths/files,not USB/Host/formal qualification',
                  started_ns=time.time_ns(), cases=[])
    try:
        executable = output / 'actual-build-script'
        command = ['rustc', '+1.96.1', '--edition=2024', str(source), '-o', str(executable)]
        with build_lock() as fd:
            env, budget = environment(dict(os.environ, SPARKLINK_BUILD_WITH_VM='1'))
            with (output / 'compile.log').open('x') as log:
                subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, pass_fds=(fd,), check=True)
            report.update(compile_command=command, resource_budget=budget, executable_sha256=digest(executable))
            cases = [('exact', None, None), ('missing-selection', None, None)]
            cases += [(key + '-' + mutation, key, mutation) for key in INPUTS
                      for mutation in ['wrong-content', 'oversized-content', 'escaping-symlink', 'missing-file']]
            for name, key, mutation in cases:
                folder = output / name
                folder.mkdir()
                generated = folder / 'out'
                generated.mkdir()
                selected = dict(env, OUT_DIR=str(generated), CARGO_CFG_TARGET_OS='linux',
                                HOST='x86_64-unknown-linux-gnu', TARGET='x86_64-unknown-linux-gnu')
                selected.pop('SPARKLINK_KERNEL_SOURCE', None)
                if name == 'exact':
                    selected['SPARKLINK_KERNEL_SOURCE'] = str(kernel)
                elif name != 'missing-selection':
                    root = folder / 'kernel'
                    for k, (relative, _, _) in INPUTS.items():
                        target = root / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(original[k], target)
                    target = root / INPUTS[key][0]
                    if mutation == 'wrong-content':
                        target.write_bytes(original[key].read_bytes() + b'\n// changed input\n')
                    elif mutation == 'oversized-content':
                        target.write_bytes(b'x' * (INPUTS[key][1] + 1))
                    else:
                        target.unlink()
                        if mutation == 'escaping-symlink':
                            target.symlink_to(original[key])
                    selected['SPARKLINK_KERNEL_SOURCE'] = str(root)
                result = subprocess.run([str(executable)], env=selected, pass_fds=(fd,), capture_output=True, text=True, timeout=20)
                (folder / 'stdout.log').write_text(result.stdout)
                (folder / 'stderr.log').write_text(result.stderr)
                module = generated / 'production_authority.rs'
                if name == 'exact':
                    if result.returncode or result.stderr or not module.is_file():
                        raise ValueError('actual production source must compile its snapshots')
                    snapshot = generated / 'production_lease_source.rs'
                    expected = '#[path = ' + json.dumps(str(snapshot), ensure_ascii=False) + '] mod production_lease;\n'
                    if module.read_text() != expected:
                        raise ValueError('module does not reference exact owned production snapshot')
                    for key2, copy in [('authority', snapshot), ('wire-codec', generated / 'wire.c'), ('wire-header', generated / 'wire.h')]:
                        if copy.read_bytes() != original[key2].read_bytes():
                            raise ValueError('compiled input snapshot mismatch: ' + key2)
                    if not (generated / 'ws73_wire.o').stat().st_size or not (generated / 'libws73_wire.a').stat().st_size:
                        raise ValueError('native C artifacts absent')
                else:
                    reason = 'explicit SPARKLINK_KERNEL_SOURCE' if name == 'missing-selection' else {
                        'wrong-content': INPUTS[key][2] + ' pin mismatch',
                        'oversized-content': INPUTS[key][2] + ' source exceeds build input budget',
                        'escaping-symlink': INPUTS[key][2] + ' source escapes selected kernel root',
                        'missing-file': 'selected production source',
                    }[mutation]
                    if result.returncode == 0 or reason not in result.stderr or any(generated.iterdir()):
                        raise ValueError('invalid input not rejected before all code generation: ' + name)
                report['cases'].append(dict(case=name, exit=result.returncode, expected_contract_observed=True))
        if before != identities():
            raise ValueError('executed source changed during checks')
        report['status'] = 'SOURCE_PIN_GUARDS_AND_NATIVE_C_BUILD_ONLY_PASS'
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
