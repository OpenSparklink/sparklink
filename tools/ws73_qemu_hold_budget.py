#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create a separate, pinned eight-second QEMU test hold fixture source.

Default two-second fixture is unchanged. This only delays an actual successful
IN81 transfer; the existing explicit release/abort and all reset/detach guards
remain byte-for-byte. It is not firmware, a reply generator or recovery.
"""
import argparse
import hashlib
from pathlib import Path

BASE_SHA256='4443a20194d4b2584cd234306c43deedb5a3f77d396c44f79370054e495955ed'
HOLD_MS=8000


def transform(original):
    if hashlib.sha256(original).hexdigest()!=BASE_SHA256:
        raise ValueError('exact pinned complete guarded QEMU host source required')
    text=original.decode()
    replacements=[
        ('    uint64_t                         test_runtime_holds;',
         '    uint64_t                         test_runtime_hold_ms;\n    uint64_t                         test_runtime_holds;'),
        ('timer_mod(s->test_runtime_hold_timer,\n                  qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 2000);',
         'timer_mod(s->test_runtime_hold_timer,\n                  qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + s->test_runtime_hold_ms);'),
        ('    object_property_add_bool(obj, "test-runtime-in-hold-once",',
         '    s->test_runtime_hold_ms = 8000;\n    object_property_add_uint64_ptr(obj, "test-runtime-in-hold-ms",\n                                  &s->test_runtime_hold_ms, OBJ_PROP_FLAG_READ);\n    object_property_add_bool(obj, "test-runtime-in-hold-once",'),
    ]
    for before,after in replacements:
        if text.count(before)!=1:raise ValueError('exact bounded-hold source location required')
        text=text.replace(before,after,1)
    return text.encode()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();data=transform(a.source.read_bytes())
    # Exclusive output, never mutate the existing source/binary/prepared image.
    with a.output.open('xb') as f:f.write(data)
    print('TEST_ONLY_BOUNDED_HOLD_SOURCE',HOLD_MS,hashlib.sha256(data).hexdigest())


if __name__=='__main__':main()
