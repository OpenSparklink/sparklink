//! SparkLink Advertisement Data TLV Parser and Builder (TXS-20001-2025 section 6.5)
//!
//! Encodes and decodes the device public information TLV structures
//! carried in SLE advertisement data (type 255) or SLB system messages.
//!
//! TLV structure:
//!   [0]   Data type (1 byte)
//!   [1]   Data length L (1 byte)
//!   [2..2+L] Data content (L bytes)
//!
//! Multi-byte values use little-endian byte order per the standard.

use crate::DiscoveryLevel;

/// Advertisement data type identifiers (TXS-20001-2025 table 1).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum AdvDataType {
    DiscoveryLevel = 0x01,
    AccessLayerCapability = 0x02,
    StandardServiceData = 0x03,
    CustomServiceData = 0x04,
    CompleteStdServiceList = 0x05,
    CompleteCustomServiceList = 0x06,
    PartialStdServiceList = 0x07,
    PartialCustomServiceList = 0x08,
    ServiceStructureHash = 0x09,
    ShortenedLocalName = 0x0A,
    CompleteLocalName = 0x0B,
    TxPowerLevel = 0x0C,
    SlbDomainName = 0x0D,
    SlbMacId = 0x0E,
    SleMacId = 0x0F,
    MultiHopNetworkInfo = 0x10,
    ExtendedDataType = 0xFE,
    ManufacturerSpecific = 0xFF,
}

impl AdvDataType {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0x01 => Some(Self::DiscoveryLevel),
            0x02 => Some(Self::AccessLayerCapability),
            0x03 => Some(Self::StandardServiceData),
            0x04 => Some(Self::CustomServiceData),
            0x05 => Some(Self::CompleteStdServiceList),
            0x06 => Some(Self::CompleteCustomServiceList),
            0x07 => Some(Self::PartialStdServiceList),
            0x08 => Some(Self::PartialCustomServiceList),
            0x09 => Some(Self::ServiceStructureHash),
            0x0A => Some(Self::ShortenedLocalName),
            0x0B => Some(Self::CompleteLocalName),
            0x0C => Some(Self::TxPowerLevel),
            0x0D => Some(Self::SlbDomainName),
            0x0E => Some(Self::SlbMacId),
            0x0F => Some(Self::SleMacId),
            0x10 => Some(Self::MultiHopNetworkInfo),
            0xFE => Some(Self::ExtendedDataType),
            0xFF => Some(Self::ManufacturerSpecific),
            _ => None,
        }
    }
}

/// Parse a discovery level byte (bits 0-2) into a `DiscoveryLevel`.
fn parse_discovery_level(v: u8) -> Option<DiscoveryLevel> {
    match v & 0x07 {
        0 => Some(DiscoveryLevel::Invisible),
        1 => Some(DiscoveryLevel::General),
        2 => Some(DiscoveryLevel::Priority),
        3 => Some(DiscoveryLevel::PairedOnly),
        4 => Some(DiscoveryLevel::Designated),
        _ => None,
    }
}

/// Access layer capability bitmap (TXS-20001-2025 table 3).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct AccessLayerCap {
    pub slb: bool,
    pub sle: bool,
}

impl AccessLayerCap {
    pub fn from_byte(b: u8) -> Self {
        Self {
            slb: b & 0x01 != 0,
            sle: b & 0x02 != 0,
        }
    }

    pub fn to_byte(self) -> u8 {
        let mut v = 0u8;
        if self.slb { v |= 0x01; }
        if self.sle { v |= 0x02; }
        v
    }
}

/// Service data: a UUID paired with associated data bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServiceData16 {
    pub uuid: u16,
    pub data: Vec<u8>,
}

/// Service data with 128-bit UUID.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServiceData128 {
    pub uuid: [u8; 16],
    pub data: Vec<u8>,
}

/// Parsed advertisement data entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AdvDataEntry {
    /// 0x01: Discovery level (bits 0-2).
    DiscoveryLevel(DiscoveryLevel),
    /// 0x02: Access layer capability bitmap.
    AccessLayerCap(AccessLayerCap),
    /// 0x03: Standard service data (16-bit UUID + data).
    StandardServiceData(ServiceData16),
    /// 0x04: Custom service data (128-bit UUID + data).
    CustomServiceData(ServiceData128),
    /// 0x05: Complete list of standard 16-bit service UUIDs.
    CompleteStdServiceList(Vec<u16>),
    /// 0x06: Complete list of custom 128-bit service UUIDs.
    CompleteCustomServiceList(Vec<[u8; 16]>),
    /// 0x07: Partial list of standard 16-bit service UUIDs.
    PartialStdServiceList(Vec<u16>),
    /// 0x08: Partial list of custom 128-bit service UUIDs.
    PartialCustomServiceList(Vec<[u8; 16]>),
    /// 0x09: Service structure hash (16 bytes).
    ServiceStructureHash([u8; 16]),
    /// 0x0A: Shortened local name (UTF-8).
    ShortenedLocalName(String),
    /// 0x0B: Complete local name (UTF-8).
    CompleteLocalName(String),
    /// 0x0C: TX power level in dBm (-127 to 127).
    TxPowerLevel(i8),
    /// 0x0D: SLB domain name.
    SlbDomainName(Vec<u8>),
    /// 0x0E: SLB MAC identifier.
    SlbMacId(Vec<u8>),
    /// 0x0F: SLE MAC identifier.
    SleMacId(Vec<u8>),
    /// 0x10: Multi-hop network info.
    MultiHopNetworkInfo(Vec<u8>),
    /// 0xFE: Extended data type.
    ExtendedDataType(Vec<u8>),
    /// 0xFF: Manufacturer specific data.
    ManufacturerSpecific(Vec<u8>),
    /// Unknown or reserved data type.
    Unknown { type_id: u8, data: Vec<u8> },
}

/// Errors returned during TLV parsing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AdvDataError {
    /// Not enough bytes remaining for the declared length.
    Truncated { offset: usize, declared: u8, available: usize },
    /// A fixed-length field has an unexpected size.
    InvalidLength { type_id: u8, expected: usize, got: usize },
    /// UTF-8 decoding failed for a name field.
    InvalidUtf8 { type_id: u8 },
    /// UUID list length is not a multiple of the UUID size.
    UnalignedUuidList { type_id: u8, len: usize, uuid_size: usize },
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

/// Parse a raw advertisement data byte slice into a list of entries.
///
/// Tolerates unknown data types (preserved as `Unknown`).
/// Returns entries parsed so far plus any errors encountered.
pub fn parse_adv_data(data: &[u8]) -> (Vec<AdvDataEntry>, Vec<AdvDataError>) {
    let mut entries = Vec::new();
    let mut errors = Vec::new();
    let mut pos = 0;

    while pos + 2 <= data.len() {
        let type_id = data[pos];
        let length = data[pos + 1] as usize;
        pos += 2;

        if pos + length > data.len() {
            errors.push(AdvDataError::Truncated {
                offset: pos - 2,
                declared: length as u8,
                available: data.len() - pos,
            });
            break;
        }

        let value = &data[pos..pos + length];
        pos += length;

        match type_id {
            0x01 => {
                if length < 1 {
                    errors.push(AdvDataError::InvalidLength {
                        type_id, expected: 1, got: length,
                    });
                    continue;
                }
                if let Some(level) = parse_discovery_level(value[0]) {
                    entries.push(AdvDataEntry::DiscoveryLevel(level));
                }
            }
            0x02 => {
                if length < 1 {
                    errors.push(AdvDataError::InvalidLength {
                        type_id, expected: 1, got: length,
                    });
                    continue;
                }
                entries.push(AdvDataEntry::AccessLayerCap(
                    AccessLayerCap::from_byte(value[0]),
                ));
            }
            0x03 => {
                if length < 2 {
                    errors.push(AdvDataError::InvalidLength {
                        type_id, expected: 2, got: length,
                    });
                    continue;
                }
                let uuid = u16::from_le_bytes([value[0], value[1]]);
                entries.push(AdvDataEntry::StandardServiceData(ServiceData16 {
                    uuid,
                    data: value[2..].to_vec(),
                }));
            }
            0x04 => {
                if length < 16 {
                    errors.push(AdvDataError::InvalidLength {
                        type_id, expected: 16, got: length,
                    });
                    continue;
                }
                let mut uuid = [0u8; 16];
                uuid.copy_from_slice(&value[..16]);
                entries.push(AdvDataEntry::CustomServiceData(ServiceData128 {
                    uuid,
                    data: value[16..].to_vec(),
                }));
            }
            0x05 | 0x07 => {
                if length % 2 != 0 {
                    errors.push(AdvDataError::UnalignedUuidList {
                        type_id, len: length, uuid_size: 2,
                    });
                    continue;
                }
                let uuids: Vec<u16> = value.chunks_exact(2)
                    .map(|c| u16::from_le_bytes([c[0], c[1]]))
                    .collect();
                if type_id == 0x05 {
                    entries.push(AdvDataEntry::CompleteStdServiceList(uuids));
                } else {
                    entries.push(AdvDataEntry::PartialStdServiceList(uuids));
                }
            }
            0x06 | 0x08 => {
                if length % 16 != 0 {
                    errors.push(AdvDataError::UnalignedUuidList {
                        type_id, len: length, uuid_size: 16,
                    });
                    continue;
                }
                let uuids: Vec<[u8; 16]> = value.chunks_exact(16)
                    .map(|c| {
                        let mut u = [0u8; 16];
                        u.copy_from_slice(c);
                        u
                    })
                    .collect();
                if type_id == 0x06 {
                    entries.push(AdvDataEntry::CompleteCustomServiceList(uuids));
                } else {
                    entries.push(AdvDataEntry::PartialCustomServiceList(uuids));
                }
            }
            0x09 => {
                if length != 16 {
                    errors.push(AdvDataError::InvalidLength {
                        type_id, expected: 16, got: length,
                    });
                    continue;
                }
                let mut hash = [0u8; 16];
                hash.copy_from_slice(value);
                entries.push(AdvDataEntry::ServiceStructureHash(hash));
            }
            0x0A | 0x0B => {
                match core::str::from_utf8(value) {
                    Ok(s) => {
                        if type_id == 0x0A {
                            entries.push(AdvDataEntry::ShortenedLocalName(s.to_string()));
                        } else {
                            entries.push(AdvDataEntry::CompleteLocalName(s.to_string()));
                        }
                    }
                    Err(_) => {
                        errors.push(AdvDataError::InvalidUtf8 { type_id });
                    }
                }
            }
            0x0C => {
                if length < 1 {
                    errors.push(AdvDataError::InvalidLength {
                        type_id, expected: 1, got: length,
                    });
                    continue;
                }
                entries.push(AdvDataEntry::TxPowerLevel(value[0] as i8));
            }
            0x0D => entries.push(AdvDataEntry::SlbDomainName(value.to_vec())),
            0x0E => entries.push(AdvDataEntry::SlbMacId(value.to_vec())),
            0x0F => entries.push(AdvDataEntry::SleMacId(value.to_vec())),
            0x10 => entries.push(AdvDataEntry::MultiHopNetworkInfo(value.to_vec())),
            0xFE => entries.push(AdvDataEntry::ExtendedDataType(value.to_vec())),
            0xFF => entries.push(AdvDataEntry::ManufacturerSpecific(value.to_vec())),
            _ => entries.push(AdvDataEntry::Unknown {
                type_id,
                data: value.to_vec(),
            }),
        }
    }

    (entries, errors)
}

// ---------------------------------------------------------------------------
// Building
// ---------------------------------------------------------------------------

/// Encode a list of advertisement data entries into TLV wire format.
pub fn build_adv_data(entries: &[AdvDataEntry]) -> Vec<u8> {
    let mut buf = Vec::new();
    for entry in entries {
        match entry {
            AdvDataEntry::DiscoveryLevel(level) => {
                buf.push(0x01);
                buf.push(1);
                buf.push(*level as u8);
            }
            AdvDataEntry::AccessLayerCap(cap) => {
                buf.push(0x02);
                buf.push(1);
                buf.push(cap.to_byte());
            }
            AdvDataEntry::StandardServiceData(sd) => {
                let len = 2 + sd.data.len();
                buf.push(0x03);
                buf.push(len as u8);
                buf.extend_from_slice(&sd.uuid.to_le_bytes());
                buf.extend_from_slice(&sd.data);
            }
            AdvDataEntry::CustomServiceData(sd) => {
                let len = 16 + sd.data.len();
                buf.push(0x04);
                buf.push(len as u8);
                buf.extend_from_slice(&sd.uuid);
                buf.extend_from_slice(&sd.data);
            }
            AdvDataEntry::CompleteStdServiceList(uuids) => {
                buf.push(0x05);
                buf.push((uuids.len() * 2) as u8);
                for u in uuids { buf.extend_from_slice(&u.to_le_bytes()); }
            }
            AdvDataEntry::CompleteCustomServiceList(uuids) => {
                buf.push(0x06);
                buf.push((uuids.len() * 16) as u8);
                for u in uuids { buf.extend_from_slice(u); }
            }
            AdvDataEntry::PartialStdServiceList(uuids) => {
                buf.push(0x07);
                buf.push((uuids.len() * 2) as u8);
                for u in uuids { buf.extend_from_slice(&u.to_le_bytes()); }
            }
            AdvDataEntry::PartialCustomServiceList(uuids) => {
                buf.push(0x08);
                buf.push((uuids.len() * 16) as u8);
                for u in uuids { buf.extend_from_slice(u); }
            }
            AdvDataEntry::ServiceStructureHash(hash) => {
                buf.push(0x09);
                buf.push(16);
                buf.extend_from_slice(hash);
            }
            AdvDataEntry::ShortenedLocalName(name) => {
                buf.push(0x0A);
                buf.push(name.len() as u8);
                buf.extend_from_slice(name.as_bytes());
            }
            AdvDataEntry::CompleteLocalName(name) => {
                buf.push(0x0B);
                buf.push(name.len() as u8);
                buf.extend_from_slice(name.as_bytes());
            }
            AdvDataEntry::TxPowerLevel(level) => {
                buf.push(0x0C);
                buf.push(1);
                buf.push(*level as u8);
            }
            AdvDataEntry::SlbDomainName(d) => {
                buf.push(0x0D);
                buf.push(d.len() as u8);
                buf.extend_from_slice(d);
            }
            AdvDataEntry::SlbMacId(d) => {
                buf.push(0x0E);
                buf.push(d.len() as u8);
                buf.extend_from_slice(d);
            }
            AdvDataEntry::SleMacId(d) => {
                buf.push(0x0F);
                buf.push(d.len() as u8);
                buf.extend_from_slice(d);
            }
            AdvDataEntry::MultiHopNetworkInfo(d) => {
                buf.push(0x10);
                buf.push(d.len() as u8);
                buf.extend_from_slice(d);
            }
            AdvDataEntry::ExtendedDataType(d) => {
                buf.push(0xFE);
                buf.push(d.len() as u8);
                buf.extend_from_slice(d);
            }
            AdvDataEntry::ManufacturerSpecific(d) => {
                buf.push(0xFF);
                buf.push(d.len() as u8);
                buf.extend_from_slice(d);
            }
            AdvDataEntry::Unknown { type_id, data } => {
                buf.push(*type_id);
                buf.push(data.len() as u8);
                buf.extend_from_slice(data);
            }
        }
    }
    buf
}

// ---------------------------------------------------------------------------
// Convenience lookup helpers
// ---------------------------------------------------------------------------

/// Find the first discovery level in a parsed entry list.
pub fn find_discovery_level(entries: &[AdvDataEntry]) -> Option<DiscoveryLevel> {
    entries.iter().find_map(|e| match e {
        AdvDataEntry::DiscoveryLevel(l) => Some(*l),
        _ => None,
    })
}

/// Find the first complete or shortened local name.
pub fn find_local_name(entries: &[AdvDataEntry]) -> Option<&str> {
    entries.iter().find_map(|e| match e {
        AdvDataEntry::CompleteLocalName(n) | AdvDataEntry::ShortenedLocalName(n) => {
            Some(n.as_str())
        }
        _ => None,
    })
}

/// Find the TX power level.
pub fn find_tx_power(entries: &[AdvDataEntry]) -> Option<i8> {
    entries.iter().find_map(|e| match e {
        AdvDataEntry::TxPowerLevel(p) => Some(*p),
        _ => None,
    })
}

/// Collect all standard 16-bit service UUIDs from complete and partial lists.
pub fn collect_service_uuids16(entries: &[AdvDataEntry]) -> Vec<u16> {
    let mut uuids = Vec::new();
    for e in entries {
        match e {
            AdvDataEntry::CompleteStdServiceList(u)
            | AdvDataEntry::PartialStdServiceList(u) => {
                uuids.extend_from_slice(u);
            }
            _ => {}
        }
    }
    uuids
}

/// Check whether any entry advertises a specific 16-bit service UUID.
pub fn has_service_uuid16(entries: &[AdvDataEntry], target: u16) -> bool {
    for e in entries {
        match e {
            AdvDataEntry::CompleteStdServiceList(u)
            | AdvDataEntry::PartialStdServiceList(u) => {
                if u.contains(&target) { return true; }
            }
            AdvDataEntry::StandardServiceData(sd) if sd.uuid == target => {
                return true;
            }
            _ => {}
        }
    }
    false
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_discovery_level() {
        let data = [0x01, 0x01, 0x02]; // type=0x01, len=1, value=2 (Priority)
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0], AdvDataEntry::DiscoveryLevel(crate::DiscoveryLevel::Priority));
    }

    #[test]
    fn parse_access_layer_cap() {
        let data = [0x02, 0x01, 0x02]; // SLE only
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        let cap = match &entries[0] {
            AdvDataEntry::AccessLayerCap(c) => *c,
            _ => panic!("wrong type"),
        };
        assert!(!cap.slb);
        assert!(cap.sle);
    }

    #[test]
    fn parse_tx_power() {
        let data = [0x0C, 0x01, 0xF0]; // -16 dBm (0xF0 as i8 = -16)
        let (entries, _) = parse_adv_data(&data);
        assert_eq!(entries[0], AdvDataEntry::TxPowerLevel(-16));
    }

    #[test]
    fn parse_local_name() {
        let name = "SparkLink-KB";
        let mut data = vec![0x0B, name.len() as u8];
        data.extend_from_slice(name.as_bytes());
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(entries[0], AdvDataEntry::CompleteLocalName("SparkLink-KB".into()));
    }

    #[test]
    fn parse_std_service_list() {
        // Two 16-bit UUIDs: 0x060B (HID), 0x180F (Battery)
        let data = [0x05, 0x04, 0x0B, 0x06, 0x0F, 0x18];
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(
            entries[0],
            AdvDataEntry::CompleteStdServiceList(vec![0x060B, 0x180F])
        );
    }

    #[test]
    fn parse_std_service_data() {
        // UUID 0x060B with 2 bytes of data
        let data = [0x03, 0x04, 0x0B, 0x06, 0x01, 0x02];
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(entries[0], AdvDataEntry::StandardServiceData(ServiceData16 {
            uuid: 0x060B,
            data: vec![0x01, 0x02],
        }));
    }

    #[test]
    fn parse_service_structure_hash() {
        let mut data = vec![0x09, 0x10];
        let hash = [0xAAu8; 16];
        data.extend_from_slice(&hash);
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(entries[0], AdvDataEntry::ServiceStructureHash(hash));
    }

    #[test]
    fn parse_custom_service_list() {
        let uuid1 = [1u8; 16];
        let uuid2 = [2u8; 16];
        let mut data = vec![0x06, 32];
        data.extend_from_slice(&uuid1);
        data.extend_from_slice(&uuid2);
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(
            entries[0],
            AdvDataEntry::CompleteCustomServiceList(vec![uuid1, uuid2])
        );
    }

    #[test]
    fn parse_manufacturer_specific() {
        let data = [0xFF, 0x03, 0x01, 0x02, 0x03];
        let (entries, _) = parse_adv_data(&data);
        assert_eq!(entries[0], AdvDataEntry::ManufacturerSpecific(vec![1, 2, 3]));
    }

    #[test]
    fn parse_multiple_entries() {
        let data = [
            0x01, 0x01, 0x01, // discovery level = General
            0x02, 0x01, 0x03, // access cap = SLB + SLE
            0x0C, 0x01, 0x04, // tx power = 4 dBm
            0x0B, 0x04, b'T', b'e', b's', b't', // name = "Test"
        ];
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(entries.len(), 4);
        assert_eq!(
            find_discovery_level(&entries),
            Some(crate::DiscoveryLevel::General)
        );
        assert_eq!(find_local_name(&entries), Some("Test"));
        assert_eq!(find_tx_power(&entries), Some(4));
    }

    #[test]
    fn roundtrip_all_types() {
        let entries = vec![
            AdvDataEntry::DiscoveryLevel(crate::DiscoveryLevel::Priority),
            AdvDataEntry::AccessLayerCap(AccessLayerCap { slb: false, sle: true }),
            AdvDataEntry::StandardServiceData(ServiceData16 {
                uuid: 0x060B,
                data: vec![0x01],
            }),
            AdvDataEntry::CompleteStdServiceList(vec![0x060B, 0x180F]),
            AdvDataEntry::ShortenedLocalName("SLK".into()),
            AdvDataEntry::CompleteLocalName("SparkLink".into()),
            AdvDataEntry::TxPowerLevel(-10),
            AdvDataEntry::ServiceStructureHash([0xBB; 16]),
            AdvDataEntry::ManufacturerSpecific(vec![0xDE, 0xAD]),
        ];
        let wire = build_adv_data(&entries);
        let (parsed, errors) = parse_adv_data(&wire);
        assert!(errors.is_empty());
        assert_eq!(parsed, entries);
    }

    #[test]
    fn truncated_data_error() {
        let data = [0x01, 0x05, 0x01]; // declares 5 bytes but only 1 available
        let (entries, errors) = parse_adv_data(&data);
        assert!(entries.is_empty());
        assert_eq!(errors.len(), 1);
        assert!(matches!(errors[0], AdvDataError::Truncated { .. }));
    }

    #[test]
    fn invalid_length_error() {
        let data = [0x09, 0x02, 0x00, 0x00]; // hash needs 16 bytes, got 2
        let (entries, errors) = parse_adv_data(&data);
        assert!(entries.is_empty());
        assert_eq!(errors.len(), 1);
        assert!(matches!(errors[0], AdvDataError::InvalidLength { type_id: 0x09, .. }));
    }

    #[test]
    fn unaligned_uuid_list_error() {
        let data = [0x05, 0x03, 0x01, 0x02, 0x03]; // 3 bytes, not multiple of 2
        let (entries, errors) = parse_adv_data(&data);
        assert!(entries.is_empty());
        assert_eq!(errors.len(), 1);
        assert!(matches!(errors[0], AdvDataError::UnalignedUuidList { .. }));
    }

    #[test]
    fn unknown_type_preserved() {
        let data = [0x42, 0x02, 0xAA, 0xBB];
        let (entries, errors) = parse_adv_data(&data);
        assert!(errors.is_empty());
        assert_eq!(entries[0], AdvDataEntry::Unknown {
            type_id: 0x42,
            data: vec![0xAA, 0xBB],
        });
    }

    #[test]
    fn has_service_uuid_lookup() {
        let entries = vec![
            AdvDataEntry::CompleteStdServiceList(vec![0x060B, 0x180F]),
        ];
        assert!(has_service_uuid16(&entries, 0x060B));
        assert!(!has_service_uuid16(&entries, 0x1234));
    }

    #[test]
    fn collect_uuids_from_mixed() {
        let entries = vec![
            AdvDataEntry::CompleteStdServiceList(vec![0x060B]),
            AdvDataEntry::PartialStdServiceList(vec![0x180F, 0x1800]),
        ];
        let uuids = collect_service_uuids16(&entries);
        assert_eq!(uuids, vec![0x060B, 0x180F, 0x1800]);
    }

    #[test]
    fn empty_data() {
        let (entries, errors) = parse_adv_data(&[]);
        assert!(entries.is_empty());
        assert!(errors.is_empty());
    }

    #[test]
    fn adv_data_type_roundtrip() {
        for v in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                   0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10,
                   0xFE, 0xFF] {
            let t = AdvDataType::from_u8(v).unwrap();
            assert_eq!(t as u8, v);
        }
        // Reserved values return None
        assert!(AdvDataType::from_u8(0x20).is_none());
        assert!(AdvDataType::from_u8(0x00).is_none());
    }
}
