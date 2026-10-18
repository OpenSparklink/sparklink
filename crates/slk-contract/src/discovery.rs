//! Caller-owned discovery observations, not controller management or Native Ready.
use serde::{Deserialize, Serialize};
use zvariant::Type;

pub const VERSION: u16 = 1;
pub const ACQUIRE: &str = "AcquireDiscovery";
pub const RELEASE: &str = "ReleaseDiscovery";
pub const REPORTS: &str = "ReadDiscovery";
pub const CAPACITY: usize = 32;
pub const MAX_SESSIONS: usize = 16;
pub const MAX_PER_CALLER: usize = 2;
pub const MAX_PREFIX: usize = 64;
pub const MAX_DATA: usize = 255;
pub const MAX_HEADER: usize = 32;
pub const MAX_DURATION_MS: u32 = 60_000;

#[derive(Clone, Debug, Serialize, Deserialize, Type)]
pub struct Report {
    pub sequence: u64,
    pub kernel_boottime_ns: u64,
    pub address_type: u8,
    pub address: Vec<u8>,
    pub rssi: i16,
    pub rssi_known: bool,
    pub header: Vec<u8>,
    pub data: Vec<u8>,
}

#[derive(Debug, Serialize, Deserialize, Type)]
pub struct Batch {
    pub version: u16,
    pub session: u64,
    pub generation: u64,
    /// Saturating counters, not a promise of lossless observation.
    pub dropped: u64,
    pub kernel_lost: u64,
    pub reports: Vec<Report>,
}

pub fn valid_filter(prefix: &[u8], minimum_rssi: i16, duration_ms: u32) -> bool {
    prefix.len() <= MAX_PREFIX
        && (-128..=20).contains(&minimum_rssi)
        && (250..=MAX_DURATION_MS).contains(&duration_ms)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_bus_shapes_and_filter_limits() {
        assert_eq!(Report::SIGNATURE.to_string(), "(ttyaynbayay)");
        assert_eq!(Batch::SIGNATURE.to_string(), "(qtttta(ttyaynbayay))");
        assert!(valid_filter(&[0; 64], -128, 250));
        assert!(valid_filter(&[], 20, 60_000));
        for (len, rssi, duration) in [
            (65, -128, 250),
            (0, -129, 1000),
            (0, 21, 1000),
            (0, 0, 249),
            (0, 0, 60_001),
        ] {
            assert!(!valid_filter(&vec![0; len], rssi, duration));
        }
    }
}
