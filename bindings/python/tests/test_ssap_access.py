"""Actual production Rust predicate through C ABI and Python, not receipt truth."""
import errno
import unittest
from sparklink import SsapAccess
from sparklink.native import _get_native_lib

class AccessContract(unittest.TestCase):
    def test_six_reference_api_bits_are_separate_from_operation_bits(self):
        self.assertEqual([SsapAccess.WRITE_ENCRYPTED,SsapAccess.WRITE_AUTHENTICATED,SsapAccess.WRITE_AUTHORIZED,SsapAccess.READ_ENCRYPTED,SsapAccess.READ_AUTHENTICATED,SsapAccess.READ_AUTHORIZED],[1,2,4,8,16,32])
    def test_exhaustive_api_mask_level_direction_through_actual_shared_library(self):
        lib=_get_native_lib()
        for bits in range(256):
            for level in range(4):
                for write in range(3):
                    wanted=(bits&7) if write else ((bits>>3)&7)
                    expected=-errno.EINVAL if bits>63 or level>2 or write>1 else 9 if wanted&4 else 8 if wanted&2 and level<2 else 10 if wanted&1 and level<1 else 0
                    self.assertEqual(lib.slk_ssap_access_error(bits,level,write),expected,(bits,level,write))
                    if bits<64 and level<3 and write<2:self.assertEqual(SsapAccess(bits).error(level,bool(write)),expected)
    def test_python_invalid_inputs_do_not_narrow_or_accept_bool(self):
        for value in [-1,64,1<<32,True,'1',1.5]:
            with self.assertRaises(ValueError):SsapAccess(value)
        for level,write in [(True,False),(3,False),(0,1),(-1,False)]:
            with self.assertRaises(ValueError):SsapAccess(0).error(level,write)
