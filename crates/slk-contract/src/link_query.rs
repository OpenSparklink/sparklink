//! Typed management observations, not application delivery or radio policy.
pub const READ: &str = "ReadLinkMeasurement";
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize, zvariant::Type)]
pub struct Observation {
    pub generation: u64,
    pub lifetime: u64,
    pub handle: u16,
    pub role: u8,
    pub address_type: u8,
    pub address: String,
    pub request_id: u64,
    /// Original daemon/kernel CLOCK_MONOTONIC expiry, not a client clock map.
    pub deadline_monotonic_ns: u64,
    pub kind: u8,
    /// 2 controller success,3 controller/local failure; never synthetic data.
    pub state: u32,
    pub error: i32,
    pub status: u8,
    /// Kernel snapshot:1 current identity,2 value available,4 real status.
    pub flags: u32,
    /// Exact successful reply body, including handle LE16. At most10bytes.
    /// RSSI127 invalid; eight PHY fields retain explicit SDK wire semantics.
    pub data: Vec<u8>,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn observation_has_independently_reviewed_dbus_signature() {
        use zvariant::Type;
        assert_eq!(Observation::SIGNATURE.to_string(), "(ttqyysttyuiyuay)");
    }
}
