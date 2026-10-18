"""Historical raw DLI projection shape for archived evidence verifiers only.

Not a bindings API and never submitted to the current kernel.
"""
import ctypes


class SleDliEvent(ctypes.Structure):
    _fields_ = [("event_type", ctypes.c_uint8), ("status", ctypes.c_uint8),
                ("handle", ctypes.c_uint16), ("opcode", ctypes.c_uint16),
                ("data_len", ctypes.c_uint16), ("data", ctypes.c_uint8 * 240),
                ("addr", ctypes.c_uint8 * 6), ("_pad", ctypes.c_uint8 * 2)]
