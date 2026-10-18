"""Operations on already-authorized application fds; no Native control lease."""
import ctypes
import errno
import os
from ._library import load_library
from ._validation import _unsigned
from .structs import SleChannelInfo, SleChannelTxStatus, SleSessionTxStatus, SleMessageSecurity, SleSendConstraint

_channel_library=None

def _get_channel_lib():
    global _channel_library
    if _channel_library is not None:
        return _channel_library
    lib=load_library("sparklink", "LIBSPARKLINK_PATH")
    signatures={
        "slk_channel_send_constrained": [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.POINTER(SleSendConstraint)],
        "slk_channel_prepare_tx": [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint64, ctypes.POINTER(SleSendConstraint)],
        "slk_ssap_access_error": [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
        "slk_channel_recv_security": [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.POINTER(SleMessageSecurity), ctypes.POINTER(ctypes.c_int)],
        "slk_channel_info": [ctypes.c_int, ctypes.POINTER(SleChannelInfo)],
        "slk_channel_tx_status": [ctypes.c_int, ctypes.POINTER(SleChannelTxStatus)],
        "slk_session_tx_status": [ctypes.c_int, ctypes.POINTER(SleSessionTxStatus)],
    }
    for name,args in signatures.items():
        fn=getattr(lib,name)
        fn.argtypes=args
        fn.restype=ctypes.c_ssize_t if name in ("slk_channel_recv_security","slk_channel_send_constrained") else ctypes.c_int
    _channel_library=lib
    return lib

def channel_info(fd):
    """Snapshot of a delegated channel fd, not NativeAdapter's control fd.

    Fixed or negotiated dynamic local/remote TCIDs are returned separately.
    Pending dynamic setup returns EAGAIN; metadata is not a peer delivery ACK.
    No lease acquisition, traffic consumption or permission escalation.
    Metadata is coherent at admission; it does not promise future connectivity.
    """
    if type(fd) is not int or not -(1 << 31) <= fd < (1 << 31):
        raise ValueError("channel fd must be a signed 32-bit integer")
    if ctypes.sizeof(SleChannelInfo) != 40 or ctypes.alignment(SleChannelInfo) != 8:
        raise RuntimeError("channel snapshot requires exact 40-byte/8-aligned ABI")
    value = SleChannelInfo()
    result = _get_channel_lib().slk_channel_info(fd, ctypes.byref(value))
    if result < 0:
        raise OSError(-result, "channel capability query")
    return value


def channel_tx_status(fd):
    """No lease or payload; reservations/queue do not mean USB/peer completion."""
    if type(fd) is not int or not -(1 << 31) <= fd < (1 << 31):
        raise ValueError("channel fd must be a signed 32-bit integer")
    if ctypes.sizeof(SleChannelTxStatus) != 64 or ctypes.alignment(SleChannelTxStatus) != 8:
        raise RuntimeError("TX snapshot requires exact64-byte/8-aligned ABI")
    value=SleChannelTxStatus()
    result=_get_channel_lib().slk_channel_tx_status(fd,ctypes.byref(value))
    if result < 0:
        raise OSError(-result,"channel TX observation")
    return value

def session_tx_status(fd):
    """No lease or payload; reservations/queue do not mean USB/peer completion."""
    if type(fd) is not int or not -(1 << 31) <= fd < (1 << 31):
        raise ValueError("channel fd must be a signed 32-bit integer")
    if ctypes.sizeof(SleSessionTxStatus) != 64 or ctypes.alignment(SleSessionTxStatus) != 8:
        raise RuntimeError("TX snapshot requires exact64-byte/8-aligned ABI")
    value=SleSessionTxStatus()
    result=_get_channel_lib().slk_session_tx_status(fd,ctypes.byref(value))
    if result < 0:
        raise OSError(-result,"Session TX observation")
    return value


def channel_recv_security(fd, size, flags=0):
    """Return (copied bytes, receipt facts, msg_flags, syscall count).

    With MSG_TRUNC count may exceed size. Missing/CTRUNC context is an error
    after possible dequeue; no rollback or future send permission is promised.
    fd must stay owned/stable for this synchronous call. Only a real SparkLink
    fd is accepted, never a Unix socket containing fabricated context.
    """
    import socket
    if type(fd) is not int or fd < 0 or fd > 2147483647:
        raise ValueError("fd must be a nonnegative int")
    if type(size) is not int or not 0 <= size <= 2047:
        raise ValueError("bounded receive size 0..2047 required")
    if not isinstance(flags, int) or isinstance(flags, bool) or flags & ~(socket.MSG_DONTWAIT | socket.MSG_PEEK | socket.MSG_TRUNC):
        raise ValueError("unsupported receive flags")
    buffer=(ctypes.c_uint8 * size)()
    context=SleMessageSecurity();actual=ctypes.c_int()
    result=_get_channel_lib().slk_channel_recv_security(fd,buffer,size,flags,ctypes.byref(context),ctypes.byref(actual))
    if result < 0:
        raise OSError(-result,os.strerror(-result))
    return bytes(buffer[:min(result,size)]),context,actual.value,result


def channel_send_constrained(fd, payload, constraint, flags=0):
    """Software admission only, not USB/controller/peer receipt; no plain fallback."""
    import socket
    if type(fd) is not int or not 0 <= fd <= 2147483647:
        raise ValueError("fd must be a nonnegative int")
    if type(payload) is not bytes or len(payload)>2042 or not isinstance(constraint,SleSendConstraint):
        raise ValueError("bounded bytes and typed constraint required")
    if not isinstance(flags,int) or isinstance(flags,bool) or flags & ~(socket.MSG_DONTWAIT | socket.MSG_NOSIGNAL):
        raise ValueError("unsupported send flags")
    buffer=(ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    result=_get_channel_lib().slk_channel_send_constrained(fd,buffer,len(payload),flags,ctypes.byref(constraint))
    if result<0:raise OSError(-result,os.strerror(-result))
    return result


def channel_prepare_tx(fd, minimum, deadline_monotonic_ns):
    """Snapshot a restriction, not authorization; carry it with actual sendmsg."""
    if type(fd) is not int or not 0<=fd<=2147483647 or type(minimum) is not int or not 0<=minimum<=2:
        raise ValueError("valid fd and mechanism0..2 required")
    if type(deadline_monotonic_ns) is not int or not 0<deadline_monotonic_ns<(1<<64):
        raise ValueError("nonzero uint64 original deadline required")
    c=SleSendConstraint();result=_get_channel_lib().slk_channel_prepare_tx(fd,minimum,deadline_monotonic_ns,ctypes.byref(c))
    if result<0:raise OSError(-result,os.strerror(-result))
    return c
