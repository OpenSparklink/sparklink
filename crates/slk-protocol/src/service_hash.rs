//! Service structure hash computation (TXS-20001-2025 section 7.2.6.2).
//!
//! The service structure hash is a 128-bit fingerprint derived from
//! SHA-256 over the concatenation of all service structure entries.
//! It allows clients to detect changes in a server's service database
//! without performing a full service discovery.
//!
//! Hash = SHA-256(M) truncated to the low 128 bits.
//!
//! M is built by iterating entries in ascending handle order and
//! appending: handle (2B LE), category (1B), uuid (2B or 16B LE),
//! operation indicator (4B LE, properties only), and descriptor
//! type list (sorted ascending, 1B each).

use sha2::{Digest, Sha256};

/// Entry category byte values matching TXS-20001-2025 section 7.4.3.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum EntryCategory {
    PrimaryService = 0x00,
    SecondaryService = 0x01,
    Property = 0x02,
    Method = 0x03,
    Event = 0x04,
    ServiceRef = 0x05,
    CustomPrimaryService = 0x08,
    CustomSecondaryService = 0x09,
    CustomProperty = 0x0A,
    CustomMethod = 0x0B,
    CustomEvent = 0x0C,
    CustomServiceRef = 0x0D,
}

impl EntryCategory {
    /// Whether this category carries an operation indicator.
    fn has_ops(self) -> bool {
        matches!(self, Self::Property | Self::CustomProperty)
    }
}

/// UUID representation for service structure entries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SsapUuid {
    Uuid16(u16),
    Uuid128([u8; 16]),
}

/// A single entry in the service structure for hash computation.
///
/// Only the fields relevant to the hash are included.
#[derive(Debug, Clone)]
pub struct HashEntry {
    pub handle: u16,
    pub category: EntryCategory,
    pub uuid: SsapUuid,
    /// Operation indicator (only meaningful for Property categories).
    pub ops: u32,
    /// Descriptor types attached to this entry.
    pub descriptor_types: Vec<u8>,
}

/// Compute the 128-bit service structure hash from a list of entries.
///
/// Entries are sorted by handle internally; the caller does not need
/// to pre-sort them.
pub fn compute_service_hash(entries: &[HashEntry]) -> [u8; 16] {
    let mut sorted: Vec<&HashEntry> = entries.iter().collect();
    sorted.sort_by_key(|e| e.handle);

    let mut hasher = Sha256::new();

    for entry in &sorted {
        // Handle: 2 bytes, little-endian
        hasher.update(entry.handle.to_le_bytes());

        // Category: 1 byte
        hasher.update([entry.category as u8]);

        // UUID: 2 bytes LE or 16 bytes
        match &entry.uuid {
            SsapUuid::Uuid16(v) => hasher.update(v.to_le_bytes()),
            SsapUuid::Uuid128(v) => hasher.update(v),
        }

        // Operation indicator: 4 bytes LE (properties only)
        if entry.category.has_ops() {
            hasher.update(entry.ops.to_le_bytes());
        }

        // Descriptor types: sorted ascending, 1 byte each
        if !entry.descriptor_types.is_empty() {
            let mut dtypes = entry.descriptor_types.clone();
            dtypes.sort();
            hasher.update(&dtypes);
        }
    }

    let digest = hasher.finalize();
    // Truncate to low 128 bits (last 16 bytes of SHA-256)
    let mut result = [0u8; 16];
    result.copy_from_slice(&digest[16..32]);
    result
}

/// Verify that a received hash matches the computed hash for a
/// set of entries.
pub fn verify_service_hash(entries: &[HashEntry], expected: &[u8; 16]) -> bool {
    &compute_service_hash(entries) == expected
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_entries() {
        let hash = compute_service_hash(&[]);
        // SHA-256 of empty input, low 16 bytes
        let sha256_empty = Sha256::digest([]);
        let mut expected = [0u8; 16];
        expected.copy_from_slice(&sha256_empty[16..32]);
        assert_eq!(hash, expected);
    }

    #[test]
    fn single_primary_service() {
        let entries = vec![HashEntry {
            handle: 0x0001,
            category: EntryCategory::PrimaryService,
            uuid: SsapUuid::Uuid16(0x060B),
            ops: 0,
            descriptor_types: vec![],
        }];
        let hash = compute_service_hash(&entries);
        // Manually compute expected: SHA-256([0x01, 0x00, 0x00, 0x0B, 0x06]) low 16
        let mut hasher = Sha256::new();
        hasher.update([0x01, 0x00]); // handle 0x0001 LE
        hasher.update([0x00]); // category PrimaryService
        hasher.update([0x0B, 0x06]); // uuid 0x060B LE
        let digest = hasher.finalize();
        let mut expected = [0u8; 16];
        expected.copy_from_slice(&digest[16..32]);
        assert_eq!(hash, expected);
    }

    #[test]
    fn property_with_ops_and_descriptors() {
        let entries = vec![HashEntry {
            handle: 0x0010,
            category: EntryCategory::Property,
            uuid: SsapUuid::Uuid16(0x1039),
            ops: 0x01,                                // READ
            descriptor_types: vec![0x04, 0x02, 0x01], // unsorted
        }];
        let hash = compute_service_hash(&entries);

        let mut hasher = Sha256::new();
        hasher.update([0x10, 0x00]); // handle
        hasher.update([0x02]); // category Property
        hasher.update([0x39, 0x10]); // uuid LE
        hasher.update([0x01, 0x00, 0x00, 0x00]); // ops LE
        hasher.update([0x01, 0x02, 0x04]); // descriptor types sorted
        let digest = hasher.finalize();
        let mut expected = [0u8; 16];
        expected.copy_from_slice(&digest[16..32]);
        assert_eq!(hash, expected);
    }

    #[test]
    fn ordering_by_handle() {
        let e1 = HashEntry {
            handle: 0x0020,
            category: EntryCategory::Property,
            uuid: SsapUuid::Uuid16(0x103A),
            ops: 0x01,
            descriptor_types: vec![],
        };
        let e2 = HashEntry {
            handle: 0x0001,
            category: EntryCategory::PrimaryService,
            uuid: SsapUuid::Uuid16(0x060B),
            ops: 0,
            descriptor_types: vec![],
        };
        // Reversed order — should be sorted internally
        let hash_reversed = compute_service_hash(&[e1.clone(), e2.clone()]);
        let hash_sorted = compute_service_hash(&[e2, e1]);
        assert_eq!(hash_reversed, hash_sorted);
    }

    #[test]
    fn uuid128_entry() {
        let uuid = [
            0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E,
            0x0F, 0x10,
        ];
        let entries = vec![HashEntry {
            handle: 0x0030,
            category: EntryCategory::CustomProperty,
            uuid: SsapUuid::Uuid128(uuid),
            ops: 0x07,
            descriptor_types: vec![],
        }];
        let hash = compute_service_hash(&entries);

        let mut hasher = Sha256::new();
        hasher.update([0x30, 0x00]);
        hasher.update([0x0A]); // CustomProperty
        hasher.update(uuid);
        hasher.update([0x07, 0x00, 0x00, 0x00]); // ops LE
        let digest = hasher.finalize();
        let mut expected = [0u8; 16];
        expected.copy_from_slice(&digest[16..32]);
        assert_eq!(hash, expected);
    }

    #[test]
    fn verify_matches() {
        let entries = vec![HashEntry {
            handle: 0x0001,
            category: EntryCategory::PrimaryService,
            uuid: SsapUuid::Uuid16(0x060B),
            ops: 0,
            descriptor_types: vec![],
        }];
        let hash = compute_service_hash(&entries);
        assert!(verify_service_hash(&entries, &hash));

        let wrong = [0xFFu8; 16];
        assert!(!verify_service_hash(&entries, &wrong));
    }

    #[test]
    fn method_no_ops() {
        // Method entries don't have ops — verify ops are NOT included
        let entries = vec![HashEntry {
            handle: 0x0050,
            category: EntryCategory::Method,
            uuid: SsapUuid::Uuid16(0x2001),
            ops: 0xFF, // should be ignored
            descriptor_types: vec![],
        }];
        let hash = compute_service_hash(&entries);

        let mut hasher = Sha256::new();
        hasher.update([0x50, 0x00]);
        hasher.update([0x03]); // Method
        hasher.update([0x01, 0x20]); // uuid LE
        // No ops for Method
        let digest = hasher.finalize();
        let mut expected = [0u8; 16];
        expected.copy_from_slice(&digest[16..32]);
        assert_eq!(hash, expected);
    }

    #[test]
    fn full_service_structure() {
        // Simulate a realistic service: primary service + 2 properties + 1 event
        let entries = vec![
            HashEntry {
                handle: 0x0001,
                category: EntryCategory::PrimaryService,
                uuid: SsapUuid::Uuid16(0x060B), // HID service
                ops: 0,
                descriptor_types: vec![],
            },
            HashEntry {
                handle: 0x0010,
                category: EntryCategory::Property,
                uuid: SsapUuid::Uuid16(0x1039),     // TypeFormat
                ops: 0x01,                          // READ
                descriptor_types: vec![0x02, 0x04], // ClientConfig, PropertyFormat
            },
            HashEntry {
                handle: 0x0011,
                category: EntryCategory::Property,
                uuid: SsapUuid::Uuid16(0x103C), // InputReport
                ops: 0x09,                      // READ | NOTIFY
                descriptor_types: vec![0x02],   // ClientConfig
            },
            HashEntry {
                handle: 0x0020,
                category: EntryCategory::Event,
                uuid: SsapUuid::Uuid16(0x2000),
                ops: 0,
                descriptor_types: vec![],
            },
        ];
        let hash1 = compute_service_hash(&entries);
        let hash2 = compute_service_hash(&entries);
        assert_eq!(hash1, hash2); // deterministic

        // Changing a property ops changes the hash
        let mut modified = entries.clone();
        modified[1].ops = 0x03; // READ | WRITE_NO_RSP
        let hash3 = compute_service_hash(&modified);
        assert_ne!(hash1, hash3);
    }
}
