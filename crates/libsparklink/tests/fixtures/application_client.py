"""Actual installed-language entry against explicit private-bus denials only."""
import errno
import os
import threading
import time
from sparklink import Client, ControllerId

PATH = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b"
def deadline():
    return time.monotonic_ns() + 3_000_000_000
def error(code, call):
    try:
        call()
    except OSError as exc:
        assert exc.errno == code, (exc, code)
    else:
        raise AssertionError("operation incorrectly succeeded")

error(errno.ETIMEDOUT, lambda: Client(deadline_ns=1))
with Client(deadline_ns=deadline()) as client:
    assert client.controllers(deadline_ns=deadline()) == (ControllerId(2, 7), ControllerId(3, 9))
    error(errno.ESTALE, lambda: client.open_channel(ControllerId(2, 8), PATH, deadline_ns=deadline()))
    error(errno.EACCES, lambda: client.open_channel(ControllerId(2, 7), PATH, deadline_ns=deadline()))
    error(errno.EAFNOSUPPORT, lambda: client.open_channel(ControllerId(2, 7), PATH, minimum=2, deadline_ns=deadline()))
    error(errno.ETIMEDOUT, lambda: client.controllers(deadline_ns=1))
    for fields in [(True, 7), (2, 0), (-1, 7), (2, 1 << 64)]:
        try:
            ControllerId(*fields)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid controller accepted")
    # Parent mutex held by a different thread: fork checks must precede locks.
    locked, release = threading.Event(), threading.Event()
    def hold():
        with client._lock:
            locked.set()
            assert release.wait(5)
    holder = threading.Thread(target=hold)
    holder.start()
    assert locked.wait(3)
    child = os.fork()
    if child == 0:
        for call in (client.close, client.__enter__, lambda: client.controllers(deadline_ns=deadline()),
                     lambda: client.open_channel(ControllerId(2, 7), PATH, deadline_ns=deadline())):
            try:
                call()
            except RuntimeError:
                continue
            os._exit(91)
        os._exit(0)
    try:
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        release.set()
        holder.join(3)
        assert not holder.is_alive()
client.close()
try:
    client.controllers(deadline_ns=deadline())
except ValueError:
    pass
else:
    raise AssertionError("closed client revived")
print("CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS")
