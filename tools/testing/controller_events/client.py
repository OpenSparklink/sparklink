#!/usr/bin/env python3
"""Actual Python public SDK observer for the disposable VM, never a bus fixture."""
import os
import sys
import time
if len(sys.argv) != 2:
    raise SystemExit('explicit prepared SDK library required')
os.environ['LIBSPARKLINK_PATH'] = sys.argv[1]
sys.path.insert(0, '/usr/share/sparklink/python')
from sparklink import Client

def deadline():
    return time.monotonic_ns() + 30_000_000_000

client = Client(deadline_ns=deadline())
stream = client.controller_events(deadline_ns=deadline())
client.close()  # The derived view must retain the same actual caller.
with stream:
    for n in range(3):
        value = stream.next(deadline_ns=deadline())
        if n == 0:
            if value.kind != 'snapshot':
                raise ValueError('actual initial snapshot required')
            paths = '|'.join(f'/org/sparklink/slk{v.index}_g{v.generation}' for v in value.controllers)
            print(f'ControllerDirectorySnapshot: cursor={value.sequence} controllers={paths}', flush=True)
        else:
            if value.kind not in ('published','withdrawn') or len(value.controllers) != 1:
                raise ValueError('actual directory change required')
            v = value.controllers[0]
            print(f'ControllerDirectoryEvent: sequence={value.sequence} action={value.kind} path=/org/sparklink/slk{v.index}_g{v.generation}', flush=True)
