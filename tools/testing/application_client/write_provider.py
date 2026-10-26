"""Actual Python SDK consumer; finite private-bus callback fixture, no wire Engine."""
import errno
import sys
import time
from sparklink import Client, ControllerId, LocalProperty, SsapOperations, SsapAccess

end=time.monotonic_ns()+2_000_000_000
client=Client(deadline_ns=end)
service=client.register_local_service(ControllerId(2,7),b'\x01\x00',
    [LocalProperty(b'\x02\x00',SsapOperations(6),SsapAccess(0),b'\x07\x08\x09')],deadline_ns=end)
provider=service.bind_write_provider(17,deadline_ns=end)
client.close()
print('READY',flush=True)
try:
    for n in range(1,5):
        with provider.next_request(deadline_ns=time.monotonic_ns()+3_000_000_000) as request:
            i=request.info
            assert (i.request_id,i.property,i.controller,i.connection_lifetime,i.security_epoch,i.offset,i.data_type)==(n,17,ControllerId(2,7),13,41,0,0)
            print(f'VALUE {n} {request.value.hex()}',flush=True)
            try: request.reply(b'',status=7)
            except ValueError: pass
            else: raise AssertionError('invalid application status accepted')
            if n==4:
                while (left:=i.deadline_ns-time.monotonic_ns())>0:
                    time.sleep(left/1_000_000_000)
            if n<3: stored=request.value
            try:
                request.reply(stored if i.verify and n<3 else b'',status=0xaf if n==3 else 0)
                result=0
            except OSError as error: result=-error.errno
            assert result==(-errno.ETIMEDOUT if n==4 else 0)
            print(f'RESULT {n} {result}',flush=True)
            # Original owner stays live until actual callback-receipt barrier.
            assert sys.stdin.readline()=='CONTINUE\n'
finally:
    provider.close()
    service.close()
print('DONE',flush=True)
