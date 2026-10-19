//! T/XS 20001-2025 table 40: one two-byte client configuration per property.
//! The codec is not subscription ownership or evidence of authenticated access.
use super::{SsapOperations, access::SsapAccess, value::ValueError};

pub const DATA_TYPE: u8 = 2;
pub const WRITE_ACCESS: SsapAccess = SsapAccess::client_configuration();

pub fn modes(operations: SsapOperations) -> u8 {
    ((operations.bits() >> 3) & 3) as u8
}
/// Supported owned-server subset. Notification capability always has exactly
/// one implicit CPCD and a connected owner policy; no manager staging shortcut.
pub fn supported_owned(operations: SsapOperations, has_authorizer: bool) -> bool {
    let bits = operations.bits();
    bits & !(5 | 8 | 16 | 512) == 0
        && (modes(operations) != 0) == operations.contains(SsapOperations::CLIENT_CFG_WR)
        && (modes(operations) == 0 || has_authorizer)
}

pub fn decode(value: &[u8], supported: u8) -> Result<u8, ValueError> {
    let bytes: [u8; 2] = value.try_into().map_err(|_| ValueError::Length)?;
    let bits = u16::from_le_bytes(bytes);
    if supported == 0 || supported & !3 != 0 {
        return Err(ValueError::Unsupported);
    }
    if bits & !3 != 0 || bits & !u16::from(supported) != 0 {
        return Err(ValueError::Reserved);
    }
    Ok(bits as u8)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_two_byte_little_endian_reserved_and_capability_checks() {
        for supported in 1..=3 {
            for bits in 0..=u16::MAX {
                let result = decode(&bits.to_le_bytes(), supported);
                assert_eq!(result.is_ok(), bits & !u16::from(supported) == 0);
                if let Ok(value) = result {
                    assert_eq!(u16::from(value), bits);
                }
            }
        }
        for raw in [&[][..], &[1][..], &[1, 0, 0][..]] {
            assert_eq!(decode(raw, 3), Err(ValueError::Length));
        }
        for supported in [0, 4, 255] {
            assert_eq!(decode(&[0, 0], supported), Err(ValueError::Unsupported));
        }
    }
    #[test]
    fn configuration_write_uses_existing_authentication_and_authorization_semantics() {
        assert_eq!(WRITE_ACCESS.bits(), 6);
        for level in 0..=3 {
            for approved in [false, true] {
                assert_eq!(
                    WRITE_ACCESS
                        .check_authorization_result(level, true, approved)
                        .is_ok(),
                    level == 2 && approved
                );
            }
            assert_eq!(WRITE_ACCESS.check(level, false).is_ok(), level <= 2);
        }
    }
}
