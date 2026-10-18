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
threads_before,fds_cold = len(os.listdir('/proc/self/task')),len(os.listdir('/proc/self/fd'))
# Exact pinned Tokio1.51/full process-global signal pair; original cold-zero
# failure and actual C call-stack attribution retained. No per-client allowance.
with Client(deadline_ns=deadline()):
    pass
fds_before = len(os.listdir('/proc/self/fd'))
assert fds_before == fds_cold + 2
assert len(os.listdir('/proc/self/task')) == threads_before
for _ in range(16):
    with Client(deadline_ns=deadline()):
        pass
    assert len(os.listdir('/proc/self/fd')) == fds_before
    assert len(os.listdir('/proc/self/task')) == threads_before
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
    observer = client.controller_events(deadline_ns=deadline())
    snapshot = observer.next(deadline_ns=deadline(),peek=True)
    assert snapshot.kind == 'snapshot' and snapshot.sequence == 0
    assert snapshot.controllers == (ControllerId(2,7),ControllerId(3,9))
    assert observer.next(deadline_ns=deadline()) == snapshot
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
    error(errno.ETIMEDOUT, lambda: client.connection(ControllerId(2, 7), PATH, deadline_ns=1))
    error(errno.ESTALE, lambda: client.connection(ControllerId(2, 8), PATH, deadline_ns=deadline()))
    connection = client.connection(ControllerId(2, 7), PATH, deadline_ns=deadline())
client.close()
for kind, sequence in [('published',1),('withdrawn',2)]:
    event = observer.next(deadline_ns=deadline())
    assert (event.kind,event.sequence,event.controllers) == (kind,sequence,(ControllerId(2,7),))
observer.close()
print("CURRENT_CONTROLLER_DIRECTORY_LANGUAGE_FIXTURE_PASS_NOT_RF")
try:
    client.controllers(deadline_ns=deadline())
except ValueError:
    pass
else:
    raise AssertionError("closed client revived")
# Closing the root does not end the retained original caller. These are finite
# private-bus fixture replies, never protocol or WS73 delivery qualification.
with connection:
    ssap = connection.ssap()
    assert ssap.read(17,minimum=2,deadline_ns=deadline()) == b"\x34\x78"
    assert ssap.write(17,b"\x56\x12",minimum=1,deadline_ns=deadline()) == b"\x90"
    assert ssap.write(17,b"",deadline_ns=deadline()) == b"\x91"
    error(errno.EINVAL, lambda: ssap.write(17,b"\x56\x12",deadline_ns=deadline()))
    error(errno.EMSGSIZE, lambda: ssap.write(17,b"x"*65536,deadline_ns=deadline()))
    error(errno.ETIMEDOUT, lambda: ssap.read(17,minimum=2,deadline_ns=1))
    error(errno.ETIMEDOUT, lambda: ssap.read(20,deadline_ns=time.monotonic_ns()+50_000_000))
    error(errno.ESTALE, lambda: ssap.read(19,deadline_ns=deadline()))
    error(errno.ESTALE, lambda: ssap.read(17,minimum=2,deadline_ns=deadline()))
try:
    ssap.read(17,minimum=2,deadline_ns=deadline())
except ValueError:
    pass
else:
    raise AssertionError("closed connection view revived")
assert len(os.listdir('/proc/self/task')) == threads_before
assert len(os.listdir('/proc/self/fd')) == fds_before
print("CURRENT_APPLICATION_CONNECTION_SSAP_FIXTURE_PASS_NOT_RF")
print("CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS")
