"""Validated T/XS 20001-2025 V1.2.0 table32 operations, not a wire Engine."""
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class SsapOperations:
    bits: int
    VALID_MASK: ClassVar[int] = 0x73F
    READ: ClassVar['SsapOperations']
    WRITE_NO_RSP: ClassVar['SsapOperations']
    WRITE_WITH_RSP: ClassVar['SsapOperations']
    NOTIFY: ClassVar['SsapOperations']
    INDICATE: ClassVar['SsapOperations']
    BROADCAST: ClassVar['SsapOperations']
    DESC_WRITABLE: ClassVar['SsapOperations']
    CLIENT_CFG_WR: ClassVar['SsapOperations']
    SERVER_CFG_WR: ClassVar['SsapOperations']

    def __post_init__(self):
        if type(self.bits) is not int:
            raise TypeError('SSAP operations must be an integer, excluding bool')
        if self.bits < 0 or self.bits > 0xFFFFFFFF or self.bits & ~self.VALID_MASK:
            raise ValueError('reserved or out-of-range SSAP operation bits')

    def __or__(self, other):
        if not isinstance(other, SsapOperations):
            return NotImplemented
        return SsapOperations(self.bits | other.bits)

    def contains(self, required):
        if not isinstance(required, SsapOperations):
            raise TypeError('required SSAP operations must be validated')
        return self.bits & required.bits == required.bits

    def to_legacy_bits(self):
        """Narrow to local-staging byte; descriptor rights cannot be discarded."""
        if self.bits > 0xFF:
            raise ValueError('32-bit SSAP permissions do not fit legacy staging')
        return self.bits


SsapOperations.READ = SsapOperations(1 << 0)
SsapOperations.WRITE_NO_RSP = SsapOperations(1 << 1)
SsapOperations.WRITE_WITH_RSP = SsapOperations(1 << 2)
SsapOperations.NOTIFY = SsapOperations(1 << 3)
SsapOperations.INDICATE = SsapOperations(1 << 4)
SsapOperations.BROADCAST = SsapOperations(1 << 5)
SsapOperations.DESC_WRITABLE = SsapOperations(1 << 8)
SsapOperations.CLIENT_CFG_WR = SsapOperations(1 << 9)
SsapOperations.SERVER_CFG_WR = SsapOperations(1 << 10)


@dataclass(frozen=True)
class SsapAccess:
    """Value security requirements, not operation indicators or a Grant."""
    bits: int
    WRITE_ENCRYPTED: ClassVar[int] = 1
    WRITE_AUTHENTICATED: ClassVar[int] = 2
    WRITE_AUTHORIZED: ClassVar[int] = 4
    READ_ENCRYPTED: ClassVar[int] = 8
    READ_AUTHENTICATED: ClassVar[int] = 16
    READ_AUTHORIZED: ClassVar[int] = 32
    VALID_MASK: ClassVar[int] = 63

    def __post_init__(self):
        if type(self.bits) is not int or not 0<=self.bits<=self.VALID_MASK:
            raise ValueError('invalid or reserved SSAP access bits')

    def error(self, level, write=False):
        """Pure production requirement check; never observes/mints authority."""
        if type(level) is not int or not 0<=level<=2 or type(write) is not bool:
            raise ValueError('bounded mechanism and bool direction required')
        from .channel import _get_channel_lib
        result=_get_channel_lib().slk_ssap_access_error(self.bits,level,int(write))
        if result<0:raise ValueError('invalid access context')
        return result
