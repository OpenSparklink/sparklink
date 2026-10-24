//! T/XS 20001-2025 tables 50, 69/72 and 75/76/77. Base, single-value,
//! complete logical-PDU codec; no extended control or multi-item promise.
//! The caller supplies a bounded normalized-PDU budget. Per-datagram MTU and
//! negotiated fragment headers are enforced by fragments::Plan, outside this
//! codec; ValueError::Mtu means this supplied budget would be exceeded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValueError {
    Length,
    Mtu,
    Unsupported,
    Reserved,
    Output,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValuePdu<'a> {
    Read {
        handle: u16,
        data_type: u8,
    },
    ReadValue(&'a [u8]),
    ReadError(u16),
    Write {
        handle: u16,
        data_type: u8,
        value: &'a [u8],
        verify: bool,
    },
    /// Single property-value command. It has no normal or error wire reply.
    WriteCommand {
        handle: u16,
        data_type: u8,
        value: &'a [u8],
    },
    Written,
    WrittenValue {
        handle: u16,
        data_type: u8,
        value: &'a [u8],
    },
    WriteError {
        handle: u16,
        error: u8,
    },
    Error {
        request: u8,
        handle: u16,
        error: u8,
    },
}
/// cbindgen:ignore
impl<'a> ValuePdu<'a> {
    pub fn decode(budget: u16, raw: &'a [u8]) -> Result<Self, ValueError> {
        if budget < 2 || raw.len() > usize::from(budget) {
            return Err(ValueError::Mtu);
        }
        if raw.len() < 2 {
            return Err(ValueError::Length);
        }
        let handle = || u16::from_le_bytes([raw[2], raw[3]]);
        match (raw[0], raw[1]) {
            (8, 3) if raw.len() == 5 => Ok(Self::Read {
                handle: handle(),
                data_type: raw[4],
            }),
            (8, 3) => Err(if raw.len() > 5 && (raw.len() - 2).is_multiple_of(3) {
                ValueError::Unsupported
            } else {
                ValueError::Length
            }),
            (9, 3) => Ok(Self::ReadValue(&raw[2..])),
            (9, 11) if raw.len() == 4 && handle() & 0x8000 == 0 => Ok(Self::ReadError(handle())),
            (12, 3) if raw.len() < 5 => Err(ValueError::Length),
            (12, 3) if raw[4] == 0 => Ok(Self::WriteCommand {
                handle: handle(),
                data_type: 0,
                value: &raw[5..],
            }),
            (12, 3) => Err(ValueError::Unsupported),
            (13, 3 | 35) if raw.len() >= 5 => Ok(Self::Write {
                handle: handle(),
                data_type: raw[4],
                value: &raw[5..],
                verify: raw[1] == 35,
            }),
            (14, 3) if raw.len() == 2 => Ok(Self::Written),
            (14, 3) if raw.len() >= 5 => Ok(Self::WrittenValue {
                handle: handle(),
                data_type: raw[4],
                value: &raw[5..],
            }),
            (14, 7) if raw.len() == 6 && raw[2] == 1 => Ok(Self::WriteError {
                handle: u16::from_le_bytes([raw[3], raw[4]]),
                error: raw[5],
            }),
            (1, 0) if raw.len() == 6 => Ok(Self::Error {
                request: raw[2],
                handle: u16::from_le_bytes([raw[3], raw[4]]),
                error: raw[5],
            }),
            (8, control) if control & 0xfc != 0 => Err(ValueError::Reserved),
            (9, control) if control & 0xf0 != 0 => Err(ValueError::Reserved),
            (12, control) if control & 0xe0 != 0 => Err(ValueError::Reserved),
            (13, control) if control & 0xc0 != 0 => Err(ValueError::Reserved),
            (14, control) if control & 0xf0 != 0 => Err(ValueError::Reserved),
            (8 | 9 | 12 | 13 | 14, control) if control & 3 != 3 => Err(ValueError::Unsupported),
            (8 | 9 | 12 | 13 | 14, _) => Err(ValueError::Unsupported),
            (1, 0) => Err(ValueError::Length),
            (1, _) => Err(ValueError::Reserved),
            _ => Err(ValueError::Unsupported),
        }
    }
    pub fn encode(&self, budget: u16, output: &mut [u8]) -> Result<usize, ValueError> {
        let len = match self {
            Self::Read { .. } => 5,
            Self::ReadValue(v) => 2usize.checked_add(v.len()).ok_or(ValueError::Mtu)?,
            Self::ReadError(e) if e & 0x8000 == 0 => 4,
            Self::ReadError(_) => return Err(ValueError::Reserved),
            Self::WriteCommand { data_type, .. } if *data_type != 0 => {
                return Err(ValueError::Unsupported);
            }
            Self::Write { value, .. }
            | Self::WriteCommand { value, .. }
            | Self::WrittenValue { value, .. } => {
                5usize.checked_add(value.len()).ok_or(ValueError::Mtu)?
            }
            Self::Written => 2,
            Self::WriteError { .. } | Self::Error { .. } => 6,
        };
        if budget < 2 || len > usize::from(budget) {
            return Err(ValueError::Mtu);
        }
        if output.len() < len {
            return Err(ValueError::Output);
        }
        match self {
            Self::Read { handle, data_type } => {
                output[..2].copy_from_slice(&[8, 3]);
                output[2..4].copy_from_slice(&handle.to_le_bytes());
                output[4] = *data_type;
            }
            Self::ReadValue(v) => {
                output[..2].copy_from_slice(&[9, 3]);
                output[2..len].copy_from_slice(v);
            }
            Self::ReadError(e) => {
                output[..2].copy_from_slice(&[9, 11]);
                output[2..4].copy_from_slice(&e.to_le_bytes());
            }
            Self::Write {
                handle,
                data_type,
                value,
                verify,
            } => {
                output[..2].copy_from_slice(&[13, 3 | if *verify { 32 } else { 0 }]);
                output[2..4].copy_from_slice(&handle.to_le_bytes());
                output[4] = *data_type;
                output[5..len].copy_from_slice(value);
            }
            Self::WriteCommand {
                handle,
                data_type,
                value,
            } => {
                output[..2].copy_from_slice(&[12, 3]);
                output[2..4].copy_from_slice(&handle.to_le_bytes());
                output[4] = *data_type;
                output[5..len].copy_from_slice(value);
            }
            Self::Written => {
                output[..2].copy_from_slice(&[14, 3]);
            }
            Self::WrittenValue {
                handle,
                data_type,
                value,
            } => {
                output[..2].copy_from_slice(&[14, 3]);
                output[2..4].copy_from_slice(&handle.to_le_bytes());
                output[4] = *data_type;
                output[5..len].copy_from_slice(value);
            }
            Self::WriteError { handle, error } => {
                output[..3].copy_from_slice(&[14, 7, 1]);
                output[3..5].copy_from_slice(&handle.to_le_bytes());
                output[5] = *error;
            }
            Self::Error {
                request,
                handle,
                error,
            } => {
                output[..3].copy_from_slice(&[1, 0, *request]);
                output[3..5].copy_from_slice(&handle.to_le_bytes());
                output[5] = *error;
            }
        }
        Ok(len)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn standard_vectors_and_atomic_refusal() {
        let vectors: &[&[u8]] = &[
            &[8, 3, 0x34, 0x12, 0],
            &[9, 3, 1, 2],
            &[9, 11, 6, 0],
            &[12, 3, 0x34, 0x12, 0, 4, 5],
            &[12, 3, 0x34, 0x12, 0],
            &[13, 35, 2, 0, 0, 4, 5],
            &[14, 3],
            &[14, 3, 2, 0, 0, 4, 5],
            &[14, 7, 1, 2, 0, 7],
            &[1, 0, 8, 0, 0, 2],
        ];
        for raw in vectors {
            let p = ValuePdu::decode(249, raw).unwrap();
            let mut out = [0xa5; 256];
            let size = p.encode(249, &mut out).unwrap();
            assert_eq!(&out[..size], *raw);
            assert!(out[size..].iter().all(|v| *v == 0xa5));
            let mut short = [0xa5; 1];
            assert_eq!(p.encode(249, &mut short), Err(ValueError::Output));
            assert_eq!(short, [0xa5]);
        }
    }
    #[test]
    fn write_command_is_single_property_only_and_refusals_are_atomic() {
        for raw in [
            &[12, 3][..],
            &[12, 3, 1, 0][..],
            &[12, 3, 1, 0, 2][..],
            &[12, 7, 1, 0, 0][..],
            &[12, 11, 1, 0, 0][..],
            &[12, 19, 1, 0, 0][..],
            &[12, 35, 1, 0, 0][..],
        ] {
            assert!(ValuePdu::decode(249, raw).is_err(), "{raw:?}");
        }
        for data_type in [1, 2, 255] {
            let mut out = [0xa5; 16];
            let command = ValuePdu::WriteCommand {
                handle: 1,
                data_type,
                value: &[3],
            };
            assert_eq!(command.encode(249, &mut out), Err(ValueError::Unsupported));
            assert_eq!(out, [0xa5; 16]);
        }
        let value = vec![0x5a; 2042];
        let command = ValuePdu::WriteCommand {
            handle: 1,
            data_type: 0,
            value: &value,
        };
        let mut out = vec![0xa5; 2048];
        assert_eq!(command.encode(2046, &mut out), Err(ValueError::Mtu));
        assert!(out.iter().all(|b| *b == 0xa5));
        assert_eq!(command.encode(2047, &mut out), Ok(2047));
        assert_eq!(ValuePdu::decode(2047, &out[..2047]), Ok(command));
        assert_eq!(out[2047], 0xa5);
    }
    #[test]
    fn exhaustive_short_input_and_control_boundaries() {
        for op in 0..=255 {
            for control in 0..=255 {
                for len in 0..=7 {
                    let mut raw = [0; 7];
                    raw[0] = op;
                    raw[1] = control;
                    if let Ok(p) = ValuePdu::decode(7, &raw[..len]) {
                        let mut out = [0xa5; 7];
                        let n = p.encode(7, &mut out).unwrap();
                        assert_eq!(&out[..n], &raw[..len]);
                    }
                }
            }
        }
        assert_eq!(
            ValuePdu::decode(249, &[8, 3, 1, 0, 0, 2, 0, 0]),
            Err(ValueError::Unsupported)
        );
        assert_eq!(
            ValuePdu::decode(249, &[8, 0, 1, 0, 0]),
            Err(ValueError::Unsupported)
        );
        let p = ValuePdu::Write {
            handle: 1,
            data_type: 0,
            value: &[3; 245],
            verify: false,
        };
        let mut out = [0xa5; 260];
        assert_eq!(p.encode(249, &mut out), Err(ValueError::Mtu));
        assert_eq!(out, [0xa5; 260]);
    }
}
