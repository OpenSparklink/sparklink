"""Opaque local policy requests over the sole Rust authorizer guard."""
import ctypes
from dataclasses import dataclass
import errno
import os
import threading
from .client import ControllerId, _ControllerId, _result


class _Info(ctypes.Structure):
    _fields_ = [('controller', _ControllerId), ('token', ctypes.c_uint64),
                ('request_id', ctypes.c_uint64), ('connection_lifetime', ctypes.c_uint64),
                ('security_epoch', ctypes.c_uint64), ('deadline_ns', ctypes.c_uint64),
                ('security_level', ctypes.c_uint32), ('connection_handle', ctypes.c_uint16),
                ('property', ctypes.c_uint16), ('value_length', ctypes.c_uint16),
                ('write', ctypes.c_uint8), ('local_tcid', ctypes.c_uint8),
                ('remote_tcid', ctypes.c_uint8), ('pi', ctypes.c_uint8),
                ('data_type', ctypes.c_uint8), ('reserved', ctypes.c_uint8 * 1), ('value', ctypes.c_uint8 * 2043),
                ('tail', ctypes.c_uint8 * 5)]


@dataclass(frozen=True)
class AuthorizationInfo:
    controller: ControllerId
    token: int
    request_id: int
    connection_lifetime: int
    connection_handle: int
    security_epoch: int
    security_level: int
    deadline_ns: int
    property: int
    write: bool
    value: bytes
    local_tcid: int
    remote_tcid: int
    pi: int
    data_type: int


def _configure(lib):
    methods = {
        'slk_authorization_request_info': [ctypes.c_void_p, ctypes.POINTER(_Info)],
        'slk_authorization_request_reply': [ctypes.c_void_p, ctypes.c_uint32],
        'slk_authorization_request_free': [ctypes.c_void_p],
    }
    for name, args in methods.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = None if name.endswith('_free') else ctypes.c_int


class AuthorizationRequest:
    """Create via LocalService.next_authorization;release every delivered view.

    No Client/service reference is retained. Service close/withdrawal/owner loss
    invalidates decisions even while this original snapshot remains readable.
    reply is local decision admission,not daemon commit or physical completion.
    A dropped unanswered request denies it;capacity awaits callback drain too.
    """
    def __init__(self):
        raise TypeError('create through LocalService.next_authorization')

    @classmethod
    def _from_view(cls, lib, handle, receipt):
        if not handle.value:
            raise OSError(errno.EPROTO, 'missing authorization request')
        _configure(lib)
        self = object.__new__(cls)
        self._lib, self._handle = lib, handle
        self._pid, self._lock = os.getpid(), threading.RLock()
        try:
            raw = _Info()
            _result(lib.slk_authorization_request_info(handle, ctypes.byref(raw)))
            controller = ControllerId(raw.controller.index, raw.controller.generation)
            if (controller != receipt.controller or any(raw.controller.reserved)
                    or any(raw.reserved) or any(raw.tail) or raw.write not in (0, 1) or raw.data_type not in (0, 2, 3)
                    or raw.data_type == 2 and (raw.write != 1 or raw.security_level != 2
                        or raw.value_length != 2 or raw.value[1] != 0 or raw.value[0] & ~3)
                    or not raw.token or not raw.request_id or not raw.connection_lifetime
                    or not raw.security_epoch or not raw.deadline_ns or raw.security_level > 2
                    or raw.property not in (receipt.method_handles if raw.data_type == 3 else receipt.property_handles)
                    or raw.data_type == 3 and raw.write != 1
                    or raw.value_length > (2043 if raw.data_type == 3 else 2042)
                    or any(raw.value[raw.value_length:])
                    or (raw.local_tcid, raw.remote_tcid, raw.pi) != (10, 10, 0)
                    or not raw.write and raw.value_length):
                raise OSError(errno.EPROTO, 'invalid authorization context ABI')
            self._info = AuthorizationInfo(controller, raw.token, raw.request_id,
                raw.connection_lifetime, raw.connection_handle, raw.security_epoch,
                raw.security_level, raw.deadline_ns, raw.property, bool(raw.write),
                bytes(raw.value[:raw.value_length]), raw.local_tcid, raw.remote_tcid, raw.pi, raw.data_type)
            return self
        except BaseException:
            self.close()
            raise

    @property
    def info(self):
        return self._info

    def _live(self):
        if self._pid != os.getpid():
            raise RuntimeError('authorization objects cannot be used after fork')
        if not self._handle.value:
            raise RuntimeError('authorization request closed')

    def reply(self, allow):
        if type(allow) is not bool:
            raise TypeError('explicit boolean decision required')
        self._live()
        with self._lock:
            self._live()
            _result(self._lib.slk_authorization_request_reply(self._handle, int(allow)))

    def close(self):
        if self._pid != os.getpid():
            raise RuntimeError('authorization objects cannot be used after fork')
        with self._lock:
            if self._handle.value:
                self._lib.slk_authorization_request_free(self._handle)
                self._handle = ctypes.c_void_p()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if getattr(self, '_handle', None) and getattr(self, '_pid', None) == os.getpid():
            self.close()

