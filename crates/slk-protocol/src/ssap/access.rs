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
    /// assertion. Local authorization is not connected, so it cannot pass.
    pub fn check(self, level: u32, write: bool) -> Result<(), u8> {
        let bits = if write { self.0 & 7 } else { (self.0 >> 3) & 7 };
        if bits & 4 != 0 {
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
#[cfg(test)]
mod tests {
    use super::*;
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
}
