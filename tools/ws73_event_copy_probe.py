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
        raise ValueError('legacy read-copy live matrix is retired; use the passive current ControllerEvent copy probe')

if __name__ == '__main__':
    raise SystemExit('NotSupported: legacy read-copy live matrix is retired; use the current ControllerEvent copy probe')
