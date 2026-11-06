"""Real Python/C/Rust SDK; private broker metadata only, not SSAP/RF."""
import errno
import sys
import time
from sparklink import Client,ControllerId,LocalProperty,SsapOperations,SsapAccess
def deadline():return time.monotonic_ns()+3_000_000_000
def refused(call):
    try:call()
    except OSError as e:assert e.errno==errno.EALREADY
    else:raise AssertionError('duplicate callback binding accepted')
client=Client(deadline_ns=deadline())
with client.register_local_service(ControllerId(2,7),b'\x01\0',
        [LocalProperty(b'\x02\0',SsapOperations(5),SsapAccess(0),b'\x07\x08\x09')],deadline_ns=deadline()) as service:
    reader=service.bind_read_provider(17,deadline_ns=deadline()) if sys.argv[1]=='read' else None
    with service.bind_write_provider(17,deadline_ns=deadline()) as writer:
        if reader is None:reader=service.bind_read_provider(17,deadline_ns=deadline())
        refused(lambda:service.bind_read_provider(17,deadline_ns=deadline()))
        refused(lambda:service.bind_write_provider(17,deadline_ns=deadline()))
        client.close()
        value=b'\x51\xa3'
        print('COMPOSITION_READY',flush=True)
        for n in range(4):
            with (reader if n%2==0 else writer).next_request(deadline_ns=deadline()) as request:
                assert request.info.property==17 and request.info.request_id==n+1
                if n%2:
                    assert request.info.operation==13 and request.info.verify
                    value=request.value
                request.reply(value)
            if n==2:
                assert sys.stdin.readline()=='CLOSE_READ\n'
                reader.close()
                print('READ_CLOSED',flush=True)
        assert sys.stdin.readline()=='UNREGISTER\n'
        service.unregister(deadline_ns=deadline())
        try:writer.next_request()
        except OSError as e:assert e.errno==errno.ESHUTDOWN
        else:raise AssertionError('withdrawn WRITE inbox revived')
print('COMPOSITION_COMPLETE',flush=True)
