//! Broker values only, not policy, crypto or a second security Engine.
pub const INTERFACE: &str = "org.sparklink.Security";
pub const METHOD: &str = "sdk111-no-mitm";
pub const NUMERIC_METHOD: &str = "sdk111-numeric-comparison";
pub const REGISTER: &str = "RegisterAgent";
pub const UNREGISTER: &str = "UnregisterAgent";
pub const ALLOCATE: &str = "AllocateReferenceSecurity";
pub const BEGIN: &str = "BeginReferenceSecurity";
pub const RESULT: &str = "GetReferenceSecurityResult";
pub const CANCEL: &str = "CancelReferenceSecurity";
pub type Prompt = (String, u64, u64, u64, u16, u8, u8, String, String, u64);
/// Frozen operation observations, not a live security property or a Bond.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, zvariant::Type)]
pub struct Observation {
    pub request_id: u64,
    pub generation: u64,
    pub lifetime: u64,
    /// 1 allocated,2 Agent,3 native admission/observation,4 completed,
    /// 5 rejected,6 cancelled,7 expired,8 failed,9 caller lost,10 Agent lost.
    pub phase: u32,
    pub error: i32,
    pub deadline_monotonic_ns: u64,
    pub agent_approved: bool,
    /// ioctl acceptance only, neither USB submission nor hardware completion.
    pub native_admitted: bool,
    pub kernel_state: u32,
    pub kernel_error: i32,
    pub kernel_flags: u32,
    pub kernel_status: u8,
    pub cleanup_error: i32,
}
