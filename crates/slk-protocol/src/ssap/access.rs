//! SSAP value access requirements, separate from table32 operation indicators.
//! T/XS20001 access-permission section/table51; six-bit API encoding matches fixed NearLink
//! Host NapiPermission. This pure check never mints local authorization or Bond.
pub const SSAP_ACCESS_WRITE_ENCRYPTED: u32 = 0x01;
pub const SSAP_ACCESS_WRITE_AUTHENTICATED: u32 = 0x02;
pub const SSAP_ACCESS_WRITE_AUTHORIZED: u32 = 0x04;
pub const SSAP_ACCESS_READ_ENCRYPTED: u32 = 0x08;
pub const SSAP_ACCESS_READ_AUTHENTICATED: u32 = 0x10;
pub const SSAP_ACCESS_READ_AUTHORIZED: u32 = 0x20;
pub const SSAP_ACCESS_VALID_MASK: u32 = 0x3f;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SsapAccess(u32);
impl SsapAccess {
    /// Descriptor policy is independent of the property's value permissions.
    pub const fn client_configuration() -> Self {
        Self(SSAP_ACCESS_WRITE_AUTHENTICATED | SSAP_ACCESS_WRITE_AUTHORIZED)
    }
    pub fn from_bits(bits: u32) -> Result<Self, &'static str> {
        if bits & !SSAP_ACCESS_VALID_MASK != 0 {
            Err("reserved SSAP access bits")
        } else {
            Ok(Self(bits))
        }
    }
    pub fn bits(self) -> u32 {
        self.0
    }
    pub fn needs_local_authorization(self) -> bool {
        self.0 & (SSAP_ACCESS_WRITE_AUTHORIZED | SSAP_ACCESS_READ_AUTHORIZED) != 0
    }
    /// level is a verified original receipt observation, never an application
    /// assertion. No local authorization is supplied by this default helper.
    pub fn check(self, level: u32, write: bool) -> Result<(), u8> {
        self.check_authorization_result(level, write, false)
    }
    /// Pure predicate, not an authority or an application approval API.
    /// The server must validate the original owner/registration/request before
    /// supplying a local decision. Authentication/encryption remain required.
    pub fn check_authorization_result(
        self,
        level: u32,
        write: bool,
        authorized: bool,
    ) -> Result<(), u8> {
        let bits = if write { self.0 & 7 } else { (self.0 >> 3) & 7 };
        if bits & 4 != 0 && !authorized {
            Err(9)
        } else if level > 2 || (bits & 2 != 0 && level < 2) {
            Err(8)
        } else if bits & 1 != 0 && level < 1 {
            Err(10)
        } else {
            Ok(())
        }
    }
}
/// Invocation requirements, not a property's read/write operation bits.
/// Reuses the verified encryption/authentication/authorization predicate; a
/// method's declared requirements must cover every effect implemented by it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MethodAccess(SsapAccess);
impl MethodAccess {
    pub fn from_bits(bits: u32) -> Result<Self, &'static str> {
        if bits & !7 != 0 {
            return Err("reserved method access bits");
        }
        SsapAccess::from_bits(bits).map(Self)
    }
    pub fn bits(self) -> u32 {
        self.0.bits()
    }
    pub fn needs_local_authorization(self) -> bool {
        self.0.needs_local_authorization()
    }
    pub fn check(self, level: u32, authorized: bool) -> Result<(), u8> {
        self.0.check_authorization_result(level, true, authorized)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn method_requirements_reuse_permission_semantics_and_reject_read_bits() {
        for bits in 0..=255 {
            let parsed = MethodAccess::from_bits(bits);
            if bits > 7 {
                assert!(parsed.is_err());
                continue;
            }
            let method = parsed.unwrap();
            assert_eq!(method.bits(), bits);
            for level in 0..=3 {
                for approved in [false, true] {
                    assert_eq!(
                        method.check(level, approved),
                        SsapAccess::from_bits(bits)
                            .unwrap()
                            .check_authorization_result(level, true, approved)
                    );
                }
            }
        }
    }
    #[test]
    fn independent_read_write_requirements_and_fail_closed_authorization() {
        for bits in 0..=255 {
            let parsed = SsapAccess::from_bits(bits);
            if bits > 63 {
                assert!(parsed.is_err());
                continue;
            }
            let p = parsed.unwrap();
            assert_eq!(p.bits(), bits);
            for write in [false, true] {
                for level in 0..=3 {
                    let required = if write { bits & 7 } else { (bits >> 3) & 7 };
                    let expected = if required & 4 != 0 {
                        Err(9)
                    } else if level > 2 || required & 2 != 0 && level < 2 {
                        Err(8)
                    } else if required & 1 != 0 && level < 1 {
                        Err(10)
                    } else {
                        Ok(())
                    };
                    assert_eq!(p.check(level, write), expected);
                }
            }
        }
        assert!(SsapAccess::from_bits(1 << 31).is_err());
    }
    #[test]
    fn approval_only_discharges_the_selected_directions_authorization_bit() {
        for bits in 0..=63 {
            let policy = SsapAccess::from_bits(bits).unwrap();
            for write in [false, true] {
                for level in 0..=3 {
                    let direction = if write { 4 } else { 32 };
                    assert_eq!(
                        policy.check_authorization_result(level, write, true),
                        SsapAccess::from_bits(bits & !direction)
                            .unwrap()
                            .check(level, write)
                    );
                    assert_eq!(
                        policy.check_authorization_result(level, write, false),
                        policy.check(level, write)
                    );
                }
            }
        }
    }
}
