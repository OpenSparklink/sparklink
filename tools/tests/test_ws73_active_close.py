# SPDX-License-Identifier: GPL-2.0-only
import copy
import ctypes
import errno
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_active_deadline import verify_records, verify_last_file_close
from sparklink.structs import SleManagementQuery
from test_ws73_active_deadline import fixture
import ws73_target


def close_fixture():
    record=fixture()
    held=SleManagementQuery(version=1,generation=1,state=1,mode=2)
    revoke=SleManagementQuery(version=1,generation=1,state=2)
    record['quiet_before_monotonic_ns']=1_160_000_000
    record['last_file_close']={
        'original_fd':3,'duplicate_fd':5,'lease':2,
        'original_fd_errno':errno.EBADF,'duplicate_fd_errno':errno.EBADF,
        'before_management':bytes(held).hex(),'first_management':bytes(held).hex(),'last_management':bytes(revoke).hex(),
        'first_before_wall_ns':220,'first_after_wall_ns':230,'last_before_wall_ns':240,'last_after_wall_ns':250,
        'first_before_monotonic_ns':1_050_000_000,'first_after_monotonic_ns':1_051_000_000,
        'last_before_monotonic_ns':1_151_000_000,'last_after_monotonic_ns':1_152_000_000,
    }
    return record


class ActiveCloseTests(unittest.TestCase):
    def test_complete_record_validation_is_not_hardware_qualification(self):
        verify_records(close_fixture())
        verify_last_file_close(close_fixture())
        verify_records(fixture())  # previous deadline records remain inspectable

    def test_first_reference_cannot_revoke_and_last_cannot_be_free_or_held(self):
        for field,state in [('before_management',0),('first_management',2),('last_management',0),('last_management',1),('last_management',3)]:
            changed=close_fixture();value=SleManagementQuery.from_buffer_copy(bytes.fromhex(changed['last_file_close'][field]));value.state=state
            changed['last_file_close'][field]=bytes(value).hex()
            with self.subTest(field=field,state=state),self.assertRaises(ValueError):verify_records(changed)

    def test_observer_has_no_owner_token_flags_or_fabricated_fault(self):
        for key in ['generation','lease','version','mode','flags','error','status','opcode','reserved']:
            changed=close_fixture();value=SleManagementQuery.from_buffer_copy(bytes.fromhex(changed['last_file_close']['first_management']));setattr(value,key,getattr(value,key)+1)
            changed['last_file_close']['first_management']=bytes(value).hex()
            with self.subTest(key=key),self.assertRaises(ValueError):verify_records(changed)

    def test_exact_descriptor_errno_and_typed_identity_required(self):
        for field,value in [('original_fd',True),('duplicate_fd',3),('lease',0),('lease',True),('original_fd_errno',0),('duplicate_fd_errno',True)]:
            changed=close_fixture();changed['last_file_close'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):verify_records(changed)
        changed=close_fixture();changed['last_file_close']['unknown']=1
        with self.assertRaises(ValueError):verify_records(changed)

    def test_close_clocks_precede_original_timeout_and_keep_alias_for_100ms(self):
        for field,value in [('first_before_wall_ns',200),('last_after_wall_ns',301),('last_before_monotonic_ns',1_052_000_000),('last_after_monotonic_ns',1_410_000_000),('first_before_monotonic_ns',1_000_000_000),('first_after_wall_ns',True)]:
            changed=close_fixture();changed['last_file_close'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):verify_records(changed)

    def test_close_gate_rejects_synthetic_or_combined_retirement(self):
        for extra in [{'support':True,'fault_recovery':True},{'fault_recovery':False},{'fault_recovery':True,'active_deadline_verify':True},{'fault_recovery':True,'diagnostic_verify':True}]:
            with tempfile.TemporaryDirectory() as tmp:
                mode='support' if extra.get('support') else 'run'
                args=SimpleNamespace(command=mode,output=Path(tmp)/'evidence',active_close_verify=True,**extra)
                with patch.object(ws73_target,'ordinary_identity'),self.subTest(extra=extra),self.assertRaises(ValueError):ws73_target._run(args)
                self.assertFalse(args.output.exists())


if __name__=='__main__':unittest.main()
