//! T/XS 20001-2025 V1.2.0 table 32 operation indicator semantics.
//! This type does not claim a wire Engine or service interoperability.
use core::{fmt, ops::BitOr};

use crate::SsapAddProperty;

/// Validated 32-bit operation permissions, including descriptor permissions.
/// Rust helper only; C uses the canonical kernel SL_SSAP_OP_* API.
/// cbindgen:ignore
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SsapOperations(u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SsapOperationError {
    ReservedBits(u32),
    LegacyWidth(u32),
}

impl fmt::Display for SsapOperationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ReservedBits(bits) => write!(f, "reserved SSAP operation bits: {bits:#010x}"),
            Self::LegacyWidth(bits) => write!(
                f,
                "32-bit SSAP operations do not fit legacy staging: {bits:#010x}"
            ),
        }
    }
}
impl std::error::Error for SsapOperationError {}

/// cbindgen:ignore
impl SsapOperations {
    pub const READ: Self = Self(1 << 0);
    pub const WRITE_NO_RSP: Self = Self(1 << 1);
    pub const WRITE_WITH_RSP: Self = Self(1 << 2);
    pub const NOTIFY: Self = Self(1 << 3);
    pub const INDICATE: Self = Self(1 << 4);
    pub const BROADCAST: Self = Self(1 << 5);
    pub const DESC_WRITABLE: Self = Self(1 << 8);
    pub const CLIENT_CFG_WR: Self = Self(1 << 9);
    pub const SERVER_CFG_WR: Self = Self(1 << 10);
    pub const VALID_MASK: u32 = 0x73f;

    pub const fn from_bits(bits: u32) -> Result<Self, SsapOperationError> {
        if bits & !Self::VALID_MASK != 0 {
            Err(SsapOperationError::ReservedBits(bits & !Self::VALID_MASK))
        } else {
            Ok(Self(bits))
        }
    }
    pub const fn bits(self) -> u32 {
        self.0
    }
    pub const fn contains(self, required: Self) -> bool {
        self.0 & required.0 == required.0
    }
    /// Explicit narrowing for the unpublished, data-value-only staging ioctl.
    pub const fn to_legacy_bits(self) -> Result<u8, SsapOperationError> {
        if self.0 > u8::MAX as u32 {
            Err(SsapOperationError::LegacyWidth(self.0))
        } else {
            Ok(self.0 as u8)
        }
    }
}
impl BitOr for SsapOperations {
    type Output = Self;
    fn bitor(self, rhs: Self) -> Self {
        Self(self.0 | rhs.0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SsapPropertyError {
    Operations(SsapOperationError),
    ValueTooLong(usize),
    NonzeroReserved,
}
impl fmt::Display for SsapPropertyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Operations(error) => error.fmt(f),
            Self::ValueTooLong(length) => {
                write!(f, "legacy SSAP property exceeds 248 bytes: {length}")
            }
            Self::NonzeroReserved => write!(f, "legacy SSAP property reserved fields must be zero"),
        }
    }
}
impl std::error::Error for SsapPropertyError {}
impl From<SsapOperationError> for SsapPropertyError {
    fn from(value: SsapOperationError) -> Self {
        Self::Operations(value)
    }
}
impl SsapAddProperty {
    /// Construct local staging input without truncating permissions or data.
    pub fn for_legacy_staging(
        uuid16: u16,
        ops: SsapOperations,
        value: &[u8],
    ) -> Result<Self, SsapPropertyError> {
        let bits = ops.to_legacy_bits()?;
        if value.len() > 248 {
            return Err(SsapPropertyError::ValueTooLong(value.len()));
        }
        let mut result = Self {
            uuid16,
            ops: bits,
            value_len: value.len() as u8,
            value: [0; 248],
            handle: 0,
            _reserved: [0; 2],
        };
        result.value[..value.len()].copy_from_slice(value);
        Ok(result)
    }
    /// Validate raw caller-owned ABI input before a syscall or state change.
    pub fn validate_legacy_staging(&self) -> Result<(), SsapPropertyError> {
        SsapOperations::from_bits(u32::from(self.ops))?;
        if usize::from(self.value_len) > self.value.len() {
            return Err(SsapPropertyError::ValueTooLong(usize::from(self.value_len)));
        }
        if self._reserved != [0; 2] {
            return Err(SsapPropertyError::NonzeroReserved);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn read_notify_does_not_grant_either_write_permission() {
        let ops = SsapOperations::READ | SsapOperations::NOTIFY;
        assert_eq!(ops.bits(), 9);
        assert!(!ops.contains(SsapOperations::WRITE_WITH_RSP));
        assert!(!ops.contains(SsapOperations::WRITE_NO_RSP));
        assert!(!SsapOperations::WRITE_NO_RSP.contains(SsapOperations::WRITE_WITH_RSP));
        assert!(!SsapOperations::WRITE_WITH_RSP.contains(SsapOperations::WRITE_NO_RSP));
    }
    #[test]
    fn all_reserved_bits_and_combinations_reject() {
        for bit in 0..32 {
            if SsapOperations::VALID_MASK & (1 << bit) == 0 {
                assert!(SsapOperations::from_bits((1 << bit) | 9).is_err());
            }
        }
        assert_eq!(SsapOperations::from_bits(0x73f).unwrap().bits(), 0x73f);
    }
    #[test]
    fn descriptor_permissions_are_not_silently_narrowed() {
        let ops = SsapOperations::READ | SsapOperations::CLIENT_CFG_WR;
        assert_eq!(
            ops.to_legacy_bits(),
            Err(SsapOperationError::LegacyWidth(0x201))
        );
        assert!(SsapAddProperty::for_legacy_staging(1, ops, &[]).is_err());
    }
    #[test]
    fn staging_preserves_complete_value_and_rejects_oversize_or_raw_reserved_fields() {
        let ops = SsapOperations::READ | SsapOperations::NOTIFY;
        let mut prop = SsapAddProperty::for_legacy_staging(1, ops, &[0x5a; 248]).unwrap();
        assert_eq!(prop.ops, 9);
        assert_eq!(prop.value, [0x5a; 248]);
        assert_eq!(prop.value_len, 248);
        assert_eq!(prop.validate_legacy_staging(), Ok(()));
        assert!(SsapAddProperty::for_legacy_staging(1, ops, &[0; 249]).is_err());
        prop._reserved[0] = 1;
        assert_eq!(
            prop.validate_legacy_staging(),
            Err(SsapPropertyError::NonzeroReserved)
        );
        prop._reserved = [0; 2];
        prop.ops = 0x49;
        assert!(prop.validate_legacy_staging().is_err());
        prop.ops = 9;
        prop.value_len = 249;
        assert_eq!(
            prop.validate_legacy_staging(),
            Err(SsapPropertyError::ValueTooLong(249))
        );
    }
}
