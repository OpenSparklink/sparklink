"""Actual Python -> C -> Rust SDK, not a protocol Engine or RF fixture."""
import errno
import os
import time
from sparklink import Client, ControllerId, LocalMethod, MethodAccess

def deadline(): return time.monotonic_ns()+3_000_000_000

def error(code, call):
    try: call()
    except OSError as exc: assert exc.errno==code, (code,exc)
    else: raise AssertionError('unexpected success')

with Client(deadline_ns=deadline()) as client:
    method=LocalMethod(b'\x03\0',MethodAccess(4))
    error(errno.EOPNOTSUPP,lambda: client.register_local_entries(
        ControllerId(2,7),b'\x04\0',[],[method],deadline_ns=deadline()))
    with client.register_local_entries(ControllerId(2,7),b'\x04\0',[],[method],
            authorization='requests',deadline_ns=deadline()) as service:
        assert service.receipt.property_handles==() and service.receipt.method_handles==(17,)
        with service.bind_method_provider(17,deadline_ns=deadline()) as provider:
            error(errno.EOPNOTSUPP,lambda: service.bind_read_provider(17,deadline_ns=deadline()))
            fd=provider.notification_fd()
            print('METHOD_READY',flush=True)
            with service.next_authorization(deadline_ns=deadline()) as approval:
                assert approval.info.data_type==3 and approval.info.write and approval.info.property==17
                assert approval.info.value==b'\x31'*2043
                approval.reply(True)
                error(errno.ESTALE,lambda: approval.reply(True))
            print('AUTH_OK',flush=True)
            for round in range(4):
                with provider.next_request(deadline_ns=deadline()) as request:
                    assert request.info.method==17 and request.info.controller==ControllerId(2,7)
                    assert request.info.connection_lifetime==13 and request.info.security_epoch==41
                    assert request.info.operation==(18 if round==1 else 19)
                    assert request.arguments==b'\x31'*2043
                    if round==2:
                        while time.monotonic_ns()<request.info.deadline_ns:
                            time.sleep(0.001)
                        error(errno.ETIMEDOUT,lambda:request.reply(b''))
                        print('METHOD_EXPIRED',flush=True)
                    elif round==3:
                        service.unregister(deadline_ns=deadline())
                        error(errno.ESHUTDOWN,lambda:request.reply(b''))
                        print('METHOD_REVOKED',flush=True)
                    else:
                        error(errno.EMSGSIZE,lambda:request.reply(b'x'*(request.info.maximum_result_bytes+1)))
                        request.reply(b'\xa6'*request.info.maximum_result_bytes)
                        error(errno.ESTALE,lambda:request.reply(b''))
                        print('METHOD_REPLIED',flush=True)
            os.close(fd)
print('METHOD_COMPLETE',flush=True)
