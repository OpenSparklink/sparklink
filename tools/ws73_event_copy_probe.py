#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Live ordinary-user VFS copy faults, using real managed scan commands.

No raw DLI commands, device reset, injection or daemon restart. The enclosing
VM lab fixes hardware ownership; this probe cannot certify natural recovery.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from ws73_north_star import Run, daemon_identity, file_record, ordinary_identity, parse_result, stable

CASES = ('zero', 'short', 'bad_address', 'partial_first', 'partial_later',
         'capacity_tail', 'complete_batch')


def verify_cases(cases):
    if [c.get('case') for c in cases] != list(CASES):
        raise ValueError('exact ordered seven live copy cases required')
    for c in cases:
        before, after, final = [c[k] for k in ('before', 'after', 'final')]
        if any(type(c[k]) is not int for k in ('result', 'errno', 'partial_prefix')) or any(type(s.get(k)) is not int for s in (before, after, final) for k in ('pending', 'enqueued', 'dropped', 'delivered')):
            raise ValueError('integer syscall/counter fields required')
        reference, retry = [bytes.fromhex(c[k]) for k in ('reference', 'retry')]
        n = before['pending']
        if not 2 <= n <= 64 or len(reference) != n * 44:
            raise ValueError('complete bounded reference records required')
        committed = 44 if c['case'] in ('partial_later', 'capacity_tail') else len(reference) if c['case'] == 'complete_batch' else 0
        expected_errno = errno.EINVAL if c['case'] == 'short' else errno.EFAULT if c['case'] in ('bad_address', 'partial_first') else 0
        if c['result'] != (-1 if expected_errno else committed) or c['errno'] != expected_errno:
            raise ValueError('copy result/errno differs from whole-record contract')
        if retry != reference[committed:]:
            raise ValueError('fault/retry changed or lost reference bytes')
        if before != {'pending': n, 'enqueued': n, 'dropped': 0, 'delivered': 0} or after != {'pending': n - committed // 44, 'enqueued': n, 'dropped': 0, 'delivered': committed // 44} or final != {'pending': 0, 'enqueued': n, 'dropped': 0, 'delivered': n}:
            raise ValueError('copy fault changed delivery/overflow accounting')
        if c['case'] in ('partial_first', 'partial_later'):
            if not 0 < c['partial_prefix'] <= 22:
                raise ValueError('actual guarded-page partial copy not observed')
        elif c['partial_prefix'] != 0:
            raise ValueError('unexpected partial copy claim')


class EventCopyRun(Run):
    SCOPE = 'live VFS read usercopy with real WS73 managed event producers in VM'
    SUCCESS = 'LIVE_EVENT_COPY_PASS'

    def execute(self):
        child = None
        selector = None
        try:
            if not Path('/scratch-root-uuid').is_file() or 'ws73.event_copy=1' not in Path('/proc/cmdline').read_text().split():
                raise ValueError('opt-in isolated scratch-root VM required')
            identity = ordinary_identity()
            self.pid = daemon_identity(self.args.slkd_pid)
            a, b = [self.ready(p) for p in self.args.ports]
            self.data.update(application_identity=identity, daemon_before=self.pid,
                             bus_before=self.bus_identity(), initial=[a, b], cases=[],
                             kernel_release=os.uname().release, probe=file_record(self.args.probe),
                             sources=[file_record(Path(__file__))], physical_acceptance=False,
                             automatic_fault_recovery_acceptance=False)
            self.save()
            with (self.output / 'probe-stderr.txt').open('xb') as errors:
                child = subprocess.Popen([str(self.args.probe), str(a['index'])],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=errors)
            self.data['probe_pid'] = child.pid
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            pending = b''
            position = 0
            deadline = time.monotonic() + 60
            with (self.output / 'probe.jsonl').open('xb') as transcript:
                while position < len(CASES):
                    if time.monotonic() >= deadline:
                        raise ValueError('live copy probe progress deadline')
                    if not selector.select(0.1):
                        self.alive()
                        continue
                    chunk = os.read(child.stdout.fileno(), 8192)
                    if not chunk:
                        raise ValueError('live copy probe stopped before all cases')
                    transcript.write(chunk); transcript.flush()
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        record = json.loads(line)
                        if 'ready' in record:
                            if record['ready'] != CASES[position] or record['uid'] != identity['uids'][0]:
                                raise ValueError('probe uid/case handshake mismatch')
                            self.check(a); self.check(b)
                            started = self.ctl(a, 'scan', 'on')
                            parse_result(started['stdout'], a, 3)
                            stopped = self.ctl(a, 'scan', 'off')
                            parse_result(stopped['stdout'], a, 4)
                            child.stdin.write(b'events-ready\n'); child.stdin.flush()
                        else:
                            if record.get('case') != CASES[position]:
                                raise ValueError('probe case result out of order')
                            self.data['cases'].append(record); self.save()
                            position += 1
                            deadline = time.monotonic() + 60
                selector.close()
            if pending or child.wait(timeout=5) != 0:
                raise ValueError('live copy probe trailing output/exit failure')
            verify_cases(self.data['cases'])
            self.data['daemon_after'] = daemon_identity(self.args.slkd_pid)
            self.data['bus_after'] = self.bus_identity()
            self.data['final'] = [self.ready(p) for p in self.args.ports]
            if self.data['bus_before'] != self.data['bus_after'] or not all(stable(x, y) for x, y in zip(self.data['initial'], self.data['final'])):
                raise ValueError('copy probe changed daemon or either controller identity')
            self.data['status'] = self.SUCCESS
        except (Exception, KeyboardInterrupt) as error:
            self.data.update(status='FAIL', error=str(error) or type(error).__name__)
        finally:
            if selector is not None:
                selector.close()
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
                for stream in [child.stdin, child.stdout]:
                    stream.close()
                self.data['probe_exit'] = child.returncode
            if self.pid and any(c['args'][-2:] == ['scan', 'on'] and c['exit'] == 0 for c in self.data['commands']):
                try:
                    self.stop(self.ready(self.args.ports[0]), 'scan')
                    self.data['cleanup'] = 'STOP_CONFIRMED'
                except (OSError, ValueError) as error:
                    self.data.update(status='FAIL', cleanup=str(error))
            self.save()
        print(self.data['status'], str(self.output / 'run.json'), flush=True)
        return 0 if self.data['status'] == self.SUCCESS else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--slctl', type=Path, required=True)
    parser.add_argument('--slkd-pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.ports = ['1-1', '1-2']
    raise SystemExit(EventCopyRun(args).execute())
