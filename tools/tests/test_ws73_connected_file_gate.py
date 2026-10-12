# SPDX-License-Identifier: GPL-2.0-only
"""Offline File-gate ABI/authorization checks; no device or RF acceptance."""
import ctypes
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_connected_file_gate import duplicate_result, verify_records, connection
from sparklink.structs import SleConnectionResult, SleControllerSnapshot


class ConnectedFileGate(unittest.TestCase):
    def test_duplicate_result_matches_canonical_kernel_ioctl(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'abi.c';binary=Path(folder)/'abi'
            source.write_text('#include <stdio.h>\n#include <linux/sparklink_ioctl.h>\nint main(void){printf("%lu",(unsigned long)SL_IOCTL_CONNECTION_RESULT);}\n')
            kernel=Path(__file__).resolve().parents[3]/'linux'
            subprocess.run(['cc','-I',str(kernel/'include/uapi'),str(source),'-o',str(binary)],check=True,capture_output=True)
            expected=int(subprocess.check_output([str(binary)]))
            def ioctl(fd,number,raw,mutable):
                self.assertEqual((fd,number,mutable),(123,expected,True))
                value=SleConnectionResult.from_buffer_copy(raw)
                self.assertEqual((value.version,value.generation,value.request_id),(1,7,900))
                value.state=4;raw[:]=bytes(value)
            with patch('ws73_connected_file_gate.fcntl.ioctl',side_effect=ioctl):
                self.assertEqual(duplicate_result(123,7,900).state,4)

    def test_dev_null_does_not_become_success(self):
        fd=os.open('/dev/null',os.O_RDONLY)
        try:
            with self.assertRaises(OSError) as caught:duplicate_result(fd,7,900)
            self.assertEqual(caught.exception.errno,errno.ENOTTY)
        finally:os.close(fd)

    def test_incomplete_synthetic_or_daemon_claim_rejected(self):
        for changes in [{},{'index':True},{'format_version':True},{'daemon_running':True},
                {'physical_acceptance':True},{'automatic_recovery_acceptance':True},{'synthetic_support':True}]:
            r=dict(format_version=1,status='CONNECTED_FILE_PASS',case='release',index=0,daemon_running=False,
                synthetic_support=False,physical_acceptance=False,automatic_recovery_acceptance=False)
            r.update(changes)
            with self.assertRaises((ValueError,KeyError)):verify_records(r)

    def test_real_typed_create_is_not_test_key_or_event_injection(self):
        a=SleControllerSnapshot(generation=7);b=SleControllerSnapshot(generation=8)
        b.address[:]=bytes.fromhex('0001093254f9');request=connection(a,b)
        self.assertEqual((request.version,request.profile,request.operation,request.generation,request.request_id,request.timeout_ms),(1,1,1,7,900,10000))
        self.assertEqual(bytes(request.parameters.peer_address),bytes(b.address))
        self.assertEqual((request.parameters.gt_negotiate,request.parameters.frame),(1,1))
        self.assertEqual(ctypes.sizeof(SleConnectionResult),64)


if __name__=='__main__':unittest.main()
