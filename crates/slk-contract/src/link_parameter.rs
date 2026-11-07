//! Explicit management command acknowledgment, never an effective link MTU.
pub const SET_PAYLOAD_PREFERENCE: &str = "SetLinkPayloadPreference";

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize, zvariant::Type)]
pub struct Acknowledgment {
    pub generation: u64,
    pub lifetime: u64,
    pub handle: u16,
    pub role: u8,
    pub address_type: u8,
    pub address: String,
    pub request_id: u64,
    pub deadline_monotonic_ns: u64,
    /// Original requested argument. Not an observed or negotiated result.
    pub requested_octets: u16,
    /// 2=real controller command success,3=controller/local failure.
    pub state: u32,
    pub error: i32,
    pub status: u8,
    /// 1=current identity,4=real status. No value-available bit for this command.
    pub flags: u32,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn acknowledgment_has_independent_signature_and_no_effective_value() {
        use zvariant::Type;
        assert_eq!(Acknowledgment::SIGNATURE.to_string(), "(ttqyysttquiyu)");
    }
}
