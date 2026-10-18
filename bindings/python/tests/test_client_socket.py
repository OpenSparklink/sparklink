"""Production Python wrapper with explicit C/OS boundary fixtures.

AF_UNIX supplies real fd ownership/I/O only. The socket factory models the
kernel's missing address autodetection. No bus, Grant, AF_SPARKLINK or RF pass.
"""
import ctypes
import errno
import os
import socket
import threading
import unittest
from unittest.mock import patch
from sparklink import Client, ControllerId


class BorrowedBridgeFixture:
    def __init__(self,source):self.source=source;self.delivered=-1;self.closed=0
    def slk_client_open_channel(self,*args):
        self.delivered=os.dup(self.source.fileno())
        args[-1]._obj.value=self.delivered
        return 0
    def slk_client_close(self,handle):self.closed+=1


def client_for(bridge):
    client=Client.__new__(Client)
    client._lock=threading.RLock();client._pid=os.getpid()
    client._handle=ctypes.c_void_p(1);client._lib=bridge
    return client


class PublicClientSocketOwnership(unittest.TestCase):
    def test_opaque_family_does_not_need_getname_and_socket_outlives_client(self):
        real_socket=socket.socket
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.addCleanup(left.close);self.addCleanup(right.close)
        bridge=BorrowedBridgeFixture(left);client=client_for(bridge)
        self.addCleanup(client.close)
        def no_autodetection(family=-1,type=-1,proto=-1,*,fileno=None):
            if (family,type,proto)!=(46,socket.SOCK_DGRAM,0):
                raise OSError(errno.EOPNOTSUPP,'explicitly modeled unavailable getname')
            # Deliberately real Unix fixture; this is not a SparkLink fd.
            return real_socket(socket.AF_UNIX,socket.SOCK_DGRAM,0,fileno=fileno)
        with patch('sparklink.client.socket.socket',side_effect=no_autodetection):
            original=client.open_channel(ControllerId(2,7),'/existing-fixture-path',deadline_ns=1)
        self.assertEqual(original.getsockopt(socket.SOL_SOCKET,socket.SO_DOMAIN),socket.AF_UNIX)
        duplicate=original.dup();self.addCleanup(duplicate.close)
        original.close();client.close()
        self.assertEqual(bridge.closed,1)
        duplicate.send(b'fd still owned');self.assertEqual(right.recv(32),b'fd still owned')
        right.send(b'peer reply');self.assertEqual(duplicate.recv(32),b'peer reply')

    def test_constructor_error_closes_unclaimed_bridge_fd(self):
        left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.addCleanup(left.close);self.addCleanup(right.close)
        bridge=BorrowedBridgeFixture(left);client=client_for(bridge);self.addCleanup(client.close)
        with patch('sparklink.client.socket.socket',side_effect=OSError(errno.EIO,'injected constructor failure')):
            with self.assertRaises(OSError):client.open_channel(ControllerId(2,7),'/fixture',deadline_ns=1)
        with self.assertRaises(OSError) as error:os.fstat(bridge.delivered)
        self.assertEqual(error.exception.errno,errno.EBADF)
