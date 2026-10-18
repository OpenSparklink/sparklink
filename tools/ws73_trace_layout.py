# SPDX-License-Identifier: GPL-2.0-only
"""Exact tracefs KiB readback from the captured kernel subbuffer layout."""
import re


def buffer_kib(header, requested_kib, subbuffer_kib):
    if (len(header) > 4096 or type(requested_kib) is not int
            or not 0 < requested_kib <= 8192 or type(subbuffer_kib) is not int
            or subbuffer_kib not in (4, 8, 16, 32, 64)):
        raise ValueError('actual bounded trace subbuffer layout')
    fields = re.findall(r'field: char data;\s*offset:(\d+);\s*size:(\d+);', header)
    if len(fields) != 1:
        raise ValueError('one exact kernel trace page data field required')
    offset, payload = map(int, fields[0])
    if not 0 < offset <= 128 or payload + offset != subbuffer_kib * 1024:
        raise ValueError('trace header/data/subbuffer sizes disagree')
    pages = max(2, (requested_kib * 1024 + payload - 1) // payload)
    return pages * payload // 1024, payload
