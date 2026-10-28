"""Actual installed-language entry against explicit private-bus denials only."""
import errno
import os
import threading
import time
from sparklink import Client, ControllerId, LocalProperty, SsapOperations, SsapAccess

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

def threads_converged(expected, budget_ns=250_000_000):
    # Same exact resource invariant;pthread join is not an atomic procfs scan.
    original=time.monotonic_ns()+budget_ns
    while time.monotonic_ns()<original:
        if len(os.listdir('/proc/self/task'))==expected:return True
        time.sleep(.001)
    return False

before_observer=len(os.listdir('/proc/self/task'))
release_observer=threading.Event()
held_observer=threading.Thread(target=release_observer.wait)
held_observer.start()
try:
    assert not threads_converged(before_observer,20_000_000)  # Actual live task.
finally:
    release_observer.set();held_observer.join()
assert threads_converged(before_observer)

error(errno.ETIMEDOUT, lambda: Client(deadline_ns=1))
threads_before,fds_cold = len(os.listdir('/proc/self/task')),len(os.listdir('/proc/self/fd'))
# Exact pinned Tokio1.51/full process-global signal pair; original cold-zero
# failure and actual C call-stack attribution retained. No per-client allowance.
with Client(deadline_ns=deadline()):
    pass
fds_before = len(os.listdir('/proc/self/fd'))
assert fds_before == fds_cold + 2
assert threads_converged(threads_before)
for _ in range(16):
    with Client(deadline_ns=deadline()):
        pass
    assert len(os.listdir('/proc/self/fd')) == fds_before
    assert threads_converged(threads_before)
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
    description_service=client.register_local_service(ControllerId(2,7),b'\x01\0',
        [LocalProperty(b'\x02\0',SsapOperations(5),SsapAccess(0),b'\x07\x08\x09')],deadline_ns=deadline())
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
with description_service:
    for text in ['描述','é'*122]:
        description_service.set_description(17,text,deadline_ns=deadline())
    error(errno.EINVAL,lambda:description_service.set_description(18,'text',deadline_ns=deadline()))
    error(errno.ETIMEDOUT,lambda:description_service.set_description(17,'text',deadline_ns=1))
    for text in ['', 'x'*245, 'é'*123, 'a\0b']:
        try:description_service.set_description(17,text,deadline_ns=deadline())
        except ValueError:pass
        else:raise AssertionError('invalid description accepted')
    description_service.unregister(deadline_ns=deadline())
    error(errno.EINVAL,lambda:description_service.set_description(17,'text',deadline_ns=deadline()))

with connection:
    ssap = connection.ssap()
    from sparklink import SsapDiscovery, SsapEntry
    from sparklink.ssap_discovery import _Entry
    import ctypes
    assert ctypes.sizeof(_Entry)==284 and _Entry.uuid.offset==12
    discovered = ssap.discover(b'\x01\x02',kind=4,deadline_ns=deadline())
    assert discovered == SsapDiscovery((SsapEntry(3,17,17,b'\x01\x02',0,b'\x80',0),),
        ((b'\x06\x14\x01\x00\xff\xff\x01\x02',b'\x07\x0b\x01\x11\x00\x01\x02\x00\x00\x00\x00\x01\x80'),))
    error(errno.ESTALE,lambda:ssap.discover(b'\x03\x04',kind=4,deadline_ns=deadline()))
    error(errno.EOPNOTSUPP,lambda:ssap.discover(b'\x05\x06',kind=4,deadline_ns=deadline()))
    error(errno.ETIMEDOUT,lambda:ssap.discover(b'\x07\x08',kind=4,deadline_ns=deadline()))
    error(errno.ETIMEDOUT,lambda:ssap.discover(b'\x01\x02',kind=4,deadline_ns=1))
    for invalid_uuid,invalid_kind in [(b'1',4),(b'12',2),(b'12',True),(b'x'*17,4)]:
        try:ssap.discover(invalid_uuid,kind=invalid_kind,deadline_ns=deadline())
        except ValueError:pass
        else:raise AssertionError('invalid discovery input accepted')
    held,release=threading.Event(),threading.Event()
    def hold_discovery_lock():
        with connection._lock:
            held.set();release.wait(3)
    holder=threading.Thread(target=hold_discovery_lock);holder.start();assert held.wait(2)
    try:
        error(errno.ETIMEDOUT,lambda:ssap.discover(b'\x01\x02',kind=4,
            deadline_ns=time.monotonic_ns()+50_000_000))
        assert not release.is_set()
    finally:
        release.set();holder.join(2);assert not holder.is_alive()
    assert ssap.read(17,minimum=2,deadline_ns=deadline()) == b"\x34\x78"
    assert ssap.read_description(17,minimum=2,deadline_ns=deadline()) == '描述'.encode('utf8')
    error(errno.EOPNOTSUPP,lambda:ssap.read_description(18,deadline_ns=deadline()))
    error(errno.ETIMEDOUT,lambda:ssap.read_description(17,deadline_ns=1))
    assert ssap.write(17,b"\x56\x12",minimum=1,deadline_ns=deadline()) == b"\x90"
    assert ssap.write(17,b"",deadline_ns=deadline()) == b"\x91"
    error(errno.EINVAL, lambda: ssap.write(17,b"\x56\x12",deadline_ns=deadline()))
    error(errno.EMSGSIZE, lambda: ssap.write(17,b"x"*65536,deadline_ns=deadline()))
    assert ssap.call_method(17,b"\x56\x12",minimum=1,deadline_ns=deadline())==b"\x90\x78\x34"
    assert ssap.call_method_without_response(17,b"\x56\x12",minimum=1,deadline_ns=deadline()) is None
    error(errno.EOPNOTSUPP,lambda:ssap.call_method(18,b"",deadline_ns=deadline()))
    error(errno.EMSGSIZE,lambda:ssap.call_method(17,b"x"*2044,deadline_ns=deadline()))
    error(errno.EMSGSIZE,lambda:ssap.call_method_without_response(17,b"x"*2044,deadline_ns=deadline()))
    error(errno.ETIMEDOUT,lambda:ssap.call_method_without_response(17,b"",deadline_ns=1))
    assert ssap.write_without_response(17,b"\x56\x12",minimum=1,deadline_ns=deadline()) is None
    assert ssap.write_without_response(17,b"",deadline_ns=deadline()) is None
    error(errno.EINVAL, lambda: ssap.write_without_response(17,b"\x56\x12",deadline_ns=deadline()))
    error(errno.ETIMEDOUT, lambda: ssap.write_without_response(21,b"\x56\x12",deadline_ns=deadline()))
    # Explicit daemon fixture rejection, not an SDK limit, negotiated MTU or RF test.
    error(errno.EINVAL, lambda: ssap.write_without_response(17,b"\xa5"*2043,deadline_ns=deadline()))
    error(errno.EMSGSIZE, lambda: ssap.write_without_response(17,b"x"*65536,deadline_ns=deadline()))
    error(errno.ETIMEDOUT, lambda: ssap.write_without_response(17,b"",deadline_ns=1))
    error(errno.ETIMEDOUT, lambda: ssap.read(17,minimum=2,deadline_ns=1))
    error(errno.ETIMEDOUT, lambda: ssap.read(20,deadline_ns=time.monotonic_ns()+50_000_000))
    error(errno.ESTALE, lambda: ssap.read(19,deadline_ns=deadline()))
    error(errno.ESTALE, lambda: ssap.read(17,minimum=2,deadline_ns=deadline()))
    error(errno.ESTALE, lambda: ssap.write_without_response(17,b"",deadline_ns=deadline()))
    error(errno.ESTALE,lambda:ssap.read_description(17,deadline_ns=deadline()))
try:
    ssap.read(17,minimum=2,deadline_ns=deadline())
except ValueError:
    pass
else:
    raise AssertionError("closed connection view revived")
assert discovered.entries[0].handle==17 # immutable observation survives close
assert len(os.listdir('/proc/self/fd')) == fds_before
assert threads_converged(threads_before)
print("CURRENT_APPLICATION_CONNECTION_SSAP_FIXTURE_PASS_NOT_RF")
print("CURRENT_APPLICATION_CLIENT_NEGATIVE_BUS_PASS")
