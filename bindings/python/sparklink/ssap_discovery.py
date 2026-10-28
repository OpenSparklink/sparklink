"""Immutable delivery of one Rust SDK result; no protocol codec or remote cache."""
import ctypes
import errno
import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SsapEntry:
    category: int
    handle: int
    end: int
    uuid: bytes
    operations: int
    descriptors: bytes
    members: int


@dataclass(frozen=True)
class SsapDiscovery:
    """Historical observation, not current availability, authorization or delivery."""
    entries: tuple[SsapEntry, ...]
    trace: tuple[tuple[bytes, bytes], ...]


class _Entry(ctypes.Structure):
    _fields_ = [('operations', ctypes.c_uint32), ('handle', ctypes.c_uint16),
                ('end', ctypes.c_uint16), ('category', ctypes.c_uint8),
                ('members', ctypes.c_uint8), ('uuid_length', ctypes.c_uint8),
                ('descriptor_length', ctypes.c_uint8), ('uuid', ctypes.c_uint8 * 16),
                ('descriptors', ctypes.c_uint8 * 255), ('reserved', ctypes.c_uint8 * 1)]


def _functions(lib):
    pointer = ctypes.c_void_p
    size = ctypes.c_size_t
    signatures = {
        'slk_connection_ssap_discover': [pointer, pointer, size, ctypes.c_uint8,
                                        ctypes.c_uint64, ctypes.POINTER(pointer)],
        'slk_ssap_discovery_counts': [pointer, ctypes.POINTER(size), ctypes.POINTER(size)],
        'slk_ssap_discovery_entry': [pointer, size, ctypes.POINTER(_Entry)],
        'slk_ssap_discovery_trace': [pointer, size, ctypes.c_uint8, pointer, size,
                                    ctypes.POINTER(size)],
    }
    for name, args in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, ctypes.c_int
    lib.slk_ssap_discovery_free.argtypes = [pointer]
    lib.slk_ssap_discovery_free.restype = None


def discover(connection, uuid, kind, deadline_ns):
    from .client import _deadline, _result
    if type(kind) is not int or kind not in (0, 1, 3, 4):
        raise ValueError('SSAP discovery kind must be 0,1,3,4')
    if not isinstance(uuid, (bytes, bytearray, memoryview)):
        raise TypeError('UUID must be bytes-like')
    if (uuid.nbytes if isinstance(uuid, memoryview) else len(uuid)) not in (0, 2, 16):
        raise ValueError('UUID must be empty,2 or16 bytes in wire order')
    uuid = bytes(uuid)
    original = _deadline(deadline_ns)
    now = time.monotonic_ns()
    if original > now + 30_000_000_000:
        raise OSError(errno.EINVAL, 'deadline exceeds local 30 second limit')
    original = min(original, now + 5_000_000_000)
    connection._live()
    _functions(connection._lib)
    result = ctypes.c_void_p()
    data = (ctypes.c_uint8 * len(uuid)).from_buffer_copy(uuid)
    remaining = original - time.monotonic_ns()
    if remaining <= 0 or not connection._lock.acquire(timeout=remaining / 1e9):
        raise OSError(errno.ETIMEDOUT, os.strerror(errno.ETIMEDOUT))
    try:
        connection._live()
        _result(connection._lib.slk_connection_ssap_discover(connection._handle, data,
            len(uuid), kind, original, ctypes.byref(result)))
    finally:
        connection._lock.release()
    # No live connection/executor is consulted after this single request.
    lib = connection._lib
    try:
        count, pages = ctypes.c_size_t(), ctypes.c_size_t()
        _result(lib.slk_ssap_discovery_counts(result, ctypes.byref(count), ctypes.byref(pages)))
        if count.value > 80 or not 1 <= pages.value <= 96:
            raise OSError(errno.EPROTO, 'invalid discovery ABI counts')
        entries, trace = [], []
        for index in range(count.value):
            entry = _Entry()
            _result(lib.slk_ssap_discovery_entry(result, index, ctypes.byref(entry)))
            if (entry.uuid_length not in (2, 16) or any(entry.reserved)
                    or any(entry.uuid[entry.uuid_length:])
                    or any(entry.descriptors[entry.descriptor_length:])):
                raise OSError(errno.EPROTO, 'invalid discovery ABI entry')
            entries.append(SsapEntry(entry.category, entry.handle, entry.end,
                bytes(entry.uuid[:entry.uuid_length]), entry.operations,
                bytes(entry.descriptors[:entry.descriptor_length]), entry.members))
        for index in range(pages.value):
            pair = []
            for response in (0, 1):
                data = (ctypes.c_uint8 * 2048)()
                size = ctypes.c_size_t()
                _result(lib.slk_ssap_discovery_trace(result, index, response, data,
                    len(data), ctypes.byref(size)))
                if not 1 <= size.value <= (22 if response == 0 else 2048):
                    raise OSError(errno.EPROTO, 'invalid discovery ABI trace')
                pair.append(bytes(data[:size.value]))
            trace.append(tuple(pair))
        return SsapDiscovery(tuple(entries), tuple(trace))
    finally:
        lib.slk_ssap_discovery_free(result)
