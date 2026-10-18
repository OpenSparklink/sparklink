//! Strict initial SSAP ExchangeInfo codec (T/XS 20001-2025 §7.4.4.3).
//! No DTAP routing, negotiation success, timers, service database or transport.
//! The channel's actual default MTU is supplied by its caller, never guessed.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExchangeKind {
    Request,
    Response,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExtensionCapabilities {
    pub fragment_sequence: bool,
    /// None means transaction numbers are not supported; Some(0) is invalid.
    pub transaction_capacity: Option<u8>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExchangeInfo {
    pub kind: ExchangeKind,
    pub mtu: Option<u16>,
    /// Major, minor, in that wire order (not a little-endian scalar).
    pub version: Option<[u8; 2]>,
    pub extension: Option<ExtensionCapabilities>,
    pub reliable: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExchangeError {
    InvalidChannelMtu,
    MtuBelowDefault,
    InvalidTransactionCapacity,
    UnsupportedOpcode,
    ReservedControl,
    UnsupportedExtensionLength,
    ReservedExtension,
    Length,
    OutputTooShort,
}

/// Rust-only codec; no C ABI is introduced.
/// cbindgen:ignore
impl ExchangeInfo {
    pub const MAX_ENCODED_LEN: usize = 10;

    pub fn encoded_len(&self, default_mtu: u16) -> Result<usize, ExchangeError> {
        if default_mtu < 2 {
            return Err(ExchangeError::InvalidChannelMtu);
        }
        if self.mtu.is_some_and(|mtu| mtu < default_mtu) {
            return Err(ExchangeError::MtuBelowDefault);
        }
        if self
            .extension
            .is_some_and(|ext| ext.transaction_capacity == Some(0))
        {
            return Err(ExchangeError::InvalidTransactionCapacity);
        }
        let length = 2
            + usize::from(self.mtu.is_some()) * 2
            + usize::from(self.version.is_some()) * 2
            + usize::from(self.extension.is_some()) * 4;
        if length > usize::from(default_mtu) {
            // ExchangeInfo is sent before MTU negotiation completes.
            return Err(ExchangeError::InvalidChannelMtu);
        }
        Ok(length)
    }

    /// Validate all fields and capacity before touching caller-owned output.
    pub fn encode(&self, default_mtu: u16, output: &mut [u8]) -> Result<usize, ExchangeError> {
        let length = self.encoded_len(default_mtu)?;
        if output.len() < length {
            return Err(ExchangeError::OutputTooShort);
        }
        output[0] = match self.kind {
            ExchangeKind::Request => 2,
            ExchangeKind::Response => 3,
        };
        output[1] = u8::from(self.mtu.is_some())
            | (u8::from(self.version.is_some()) << 1)
            | (u8::from(self.extension.is_some()) << 2)
            | (u8::from(self.reliable) << 3);
        let mut offset = 2;
        if let Some(mtu) = self.mtu {
            output[offset..offset + 2].copy_from_slice(&mtu.to_le_bytes());
            offset += 2;
        }
        if let Some(version) = self.version {
            output[offset..offset + 2].copy_from_slice(&version);
            offset += 2;
        }
        if let Some(ext) = self.extension {
            output[offset] = (u8::from(ext.fragment_sequence) << 2)
                | (u8::from(ext.transaction_capacity.is_some()) << 3);
            output[offset + 1] = ext.transaction_capacity.unwrap_or(0);
            output[offset + 2] = 0;
            output[offset + 3] = 0;
        }
        Ok(length)
    }

    /// Exact length, little-endian MTU, conditional fields, no truncation.
    /// Nonzero reserved bits are rejected; the insignificant capacity byte is
    /// ignored when transaction-number support is absent, as specified.
    pub fn decode(default_mtu: u16, input: &[u8]) -> Result<Self, ExchangeError> {
        if input.len() < 2 {
            return Err(ExchangeError::Length);
        }
        let kind = match input[0] {
            2 => ExchangeKind::Request,
            3 => ExchangeKind::Response,
            _ => return Err(ExchangeError::UnsupportedOpcode),
        };
        let control = input[1];
        if control & 0xf0 != 0 {
            return Err(ExchangeError::ReservedControl);
        }
        let length = 2
            + usize::from(control & 1 != 0) * 2
            + usize::from(control & 2 != 0) * 2
            + usize::from(control & 4 != 0) * 4;
        if input.len() != length {
            return Err(ExchangeError::Length);
        }
        let mut offset = 2;
        let mtu = if control & 1 != 0 {
            let value = u16::from_le_bytes([input[offset], input[offset + 1]]);
            offset += 2;
            Some(value)
        } else {
            None
        };
        let version = if control & 2 != 0 {
            let value = [input[offset], input[offset + 1]];
            offset += 2;
            Some(value)
        } else {
            None
        };
        let extension = if control & 4 != 0 {
            let flags = input[offset];
            if flags & 3 != 0 {
                return Err(ExchangeError::UnsupportedExtensionLength);
            }
            if flags & 0xf0 != 0 || input[offset + 2] != 0 || input[offset + 3] != 0 {
                return Err(ExchangeError::ReservedExtension);
            }
            Some(ExtensionCapabilities {
                fragment_sequence: flags & 4 != 0,
                transaction_capacity: if flags & 8 != 0 {
                    Some(input[offset + 1])
                } else {
                    None
                },
            })
        } else {
            None
        };
        let info = Self {
            kind,
            mtu,
            version,
            extension,
            reliable: control & 8 != 0,
        };
        info.encoded_len(default_mtu)?;
        Ok(info)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conditional_fields_all_control_combinations_and_exact_wire() {
        for control in 0..16 {
            let info = ExchangeInfo {
                kind: ExchangeKind::Request,
                mtu: (control & 1 != 0).then_some(254),
                version: (control & 2 != 0).then_some([1, 2]),
                extension: (control & 4 != 0).then_some(ExtensionCapabilities {
                    fragment_sequence: true,
                    transaction_capacity: Some(7),
                }),
                reliable: control & 8 != 0,
            };
            let mut output = [0xa5; 11];
            let size = info.encode(128, &mut output).unwrap();
            assert_eq!(output[0..2], [2, control]);
            assert_eq!(ExchangeInfo::decode(128, &output[..size]), Ok(info));
            assert_eq!(output[size..], vec![0xa5; 11 - size]);
        }
        let expected = [3, 7, 0xfe, 0, 1, 2, 0x0c, 7, 0, 0];
        let info = ExchangeInfo::decode(128, &expected).unwrap();
        let mut output = [0; 10];
        assert_eq!(info.encode(128, &mut output), Ok(10));
        assert_eq!(output, expected);
    }

    #[test]
    fn malformed_or_unsupported_fields_never_negotiate() {
        for raw in [
            &[2][..],
            &[2, 0, 0],
            &[0x82, 0],
            &[2, 0x10],
            &[2, 4, 1, 0, 0, 0],
            &[2, 4, 0x10, 0, 0, 0],
            &[2, 4, 8, 0, 0, 0],
            &[2, 4, 0, 0, 1, 0],
            &[2, 1, 127, 0],
        ] {
            assert!(ExchangeInfo::decode(128, raw).is_err(), "{raw:?}");
        }
        assert_eq!(
            ExchangeInfo::decode(0, &[2, 0]),
            Err(ExchangeError::InvalidChannelMtu)
        );
        let info = ExchangeInfo::decode(128, &[2, 4, 0, 0xff, 0, 0]).unwrap();
        assert_eq!(info.extension.unwrap().transaction_capacity, None);
        let mut output = [0xa5; 6];
        info.encode(128, &mut output).unwrap();
        assert_eq!(output, [2, 4, 0, 0, 0, 0]);
    }

    #[test]
    fn output_failures_preserve_entire_buffer() {
        let mut info = ExchangeInfo::decode(128, &[2, 3, 128, 0, 1, 2]).unwrap();
        for length in 0..6 {
            let mut output = [0xa5; 10];
            assert_eq!(
                info.encode(128, &mut output[..length]),
                Err(ExchangeError::OutputTooShort)
            );
            assert_eq!(output, [0xa5; 10]);
        }
        info.mtu = Some(127);
        let mut output = [0xa5; 10];
        assert_eq!(
            info.encode(128, &mut output),
            Err(ExchangeError::MtuBelowDefault)
        );
        assert_eq!(output, [0xa5; 10]);
    }
}
