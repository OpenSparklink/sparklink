#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Shared local main-thread build budget; no device operations or installation.

Wrap a direct kernel make or cargo invocation, not a Makefile that already uses
this wrapper. Legacy/frozen builders are retained; do not run one concurrently.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent


def workspace():
    for parent in HERE.parents:
        if (parent / 'linux/.git').exists() and (parent / 'sparklink/.git').exists():
            return parent
    return HERE.parent


def configuration():
    return json.loads((HERE.parent / 'project/build-resource-policy.json').read_text())


def real_vm_active():
    path = workspace() / '.dev/real-device-vm.lock'
    if not path.exists():
        return False
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def environment(environ=None):
    env = dict(os.environ if environ is None else environ)
    policy = configuration()
    mode = env.get('SPARKLINK_BUILD_WITH_VM', '0')
    if mode not in ('0', '1'):
        raise ValueError('SPARKLINK_BUILD_WITH_VM must be 0 or 1')
    detected_vm = real_vm_active()
    with_vm = mode == '1' or detected_vm
    limit = policy['with_real_device_vm_jobs' if with_vm else 'solo_jobs']
    cpus = len(os.sched_getaffinity(0))
    jobs = int(env.get('SPARKLINK_BUILD_JOBS', min(limit, cpus)))
    if not 1 <= jobs <= min(limit, cpus):
        raise ValueError('explicit build jobs exceed current CPU/VM budget')
    # Both controls refer to the same budget; do not silently ignore an older
    # Cargo setting. Legacy invocations continue outside this new entry point.
    if 'CARGO_BUILD_JOBS' in env and int(env['CARGO_BUILD_JOBS']) != jobs:
        raise ValueError('CARGO_BUILD_JOBS conflicts with SPARKLINK_BUILD_JOBS/policy')
    env['CARGO_BUILD_JOBS'] = str(jobs)
    env['SPARKLINK_BUILD_JOBS'] = str(jobs)
    # This is top-level only. A stale parent jobserver descriptor must not be
    # propagated as a second independent pool. Cargo manages its own children.
    inherited = [k for k in ('MAKEFLAGS', 'MFLAGS', 'CARGO_MAKEFLAGS') if k in env]
    for key in inherited:
        env.pop(key)
    memory = next((line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith('MemAvailable:')), None)
    return env, dict(jobs=jobs, with_real_device_vm=with_vm, detected_shared_vm_lease=detected_vm, logical_cpus=os.cpu_count(),
                     affinity_cpus=cpus, mem_available_kib=int(memory) if memory else None,
                     policy_sha256=hashlib.sha256((HERE.parent / 'project/build-resource-policy.json').read_bytes()).hexdigest(),
                     inherited_top_level_jobserver_cleared=inherited,
                     lock=str(workspace() / '.dev/main-build.lock'))


@contextmanager
def build_lock():
    path = workspace() / '.dev/main-build.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('another coordinated main-thread build owns ' + str(path)) from error
        # Pass this descriptor to the heavy child. Closing the supervisor's
        # copy must not unlock a build still running after supervisor death.
        # Last close releases flock; explicit LOCK_UN would release all copies.
        yield stream.fileno()


@contextmanager
def real_device_vm():
    """Budget handshake, not a USB lease. Multiple device-disjoint VMs may run.

    Refuse launch during an existing coordinated build; never interrupt it.
    Build budget is sampled under the same lock. Child QEMU inherits the shared
    marker so supervisor death cannot prematurely restore the 12-job budget.
    Uncoordinated tools must be checked/arranged separately, not presumed safe.
    """
    path = workspace() / '.dev/real-device-vm.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as marker:
        with build_lock():
            fcntl.flock(marker, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield marker.fileno()


def command_with_jobs(command, jobs):
    if not command or Path(command[0]).name not in ('make', 'gmake', 'cargo'):
        raise ValueError('wrap direct make/cargo only;script callers use build_lock/environment')
    split = command.index('--') if '--' in command else len(command)
    if any(x.startswith('-j') or x == '--jobs' or x.startswith('--jobs=') for x in command[1:split]):
        raise ValueError('job count belongs to shared policy;remove command-specific -j/--jobs')
    if Path(command[0]).name == 'cargo':
        if not any(x in command[1:] for x in ('build', 'check', 'test', 'clippy')):
            raise ValueError('expected a Cargo build/check/test/clippy command')
        flags = ['--jobs', str(jobs)] + ([] if '--locked' in command[:split] else ['--locked'])
        return command[:split] + flags + command[split:]
    return [command[0], '-j' + str(jobs), *command[1:]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-vm', action='store_true')
    parser.add_argument('--record', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    supplied = dict(os.environ)
    if args.with_vm:
        supplied['SPARKLINK_BUILD_WITH_VM'] = '1'
    env, budget = environment(supplied)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    command = command_with_jobs(command, budget['jobs'])
    record = dict(status='BUILD_RUNNING_NOT_QUALIFIED', command=command, budget=budget,
                  start_ns=time.time_ns(), cwd=os.getcwd(), qualification=False,
                  helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  rustup_toolchain=env.get('RUSTUP_TOOLCHAIN'))
    if args.record and args.record.exists():
        raise ValueError('refuse to overwrite build record')
    try:
        with build_lock() as build_fd:
            # A VM may have started after argument parsing; recompute inside
            # the launch handshake, before any compiler or shared-target use.
            env, budget = environment(supplied)
            command = command_with_jobs(args.command[1:] if args.command[:1] == ['--'] else args.command, budget['jobs'])
            record.update(command=command,budget=budget)
            if args.record:
                args.record.write_text(json.dumps(record, indent=2) + '\n')
            print('Build budget: ' + json.dumps(budget), flush=True)
            result = subprocess.run(command, env=env, pass_fds=(build_fd,))
            record.update(status='BUILD_EXITED_NOT_QUALIFIED', exit=result.returncode)
    except BaseException as error:
        record.update(status='FAIL', error=str(error))
        raise
    finally:
        record['end_ns'] = time.time_ns()
        if args.record:
            args.record.write_text(json.dumps(record, indent=2) + '\n')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
