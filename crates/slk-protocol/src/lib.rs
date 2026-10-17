//! ```compile_fail
//! use slk_protocol::{SlePairParams, SleSecInfo};
//! ```
//! ```compile_fail
//! use slk_protocol::{SleDliCmd, SleConnData, SleScanParams};
//! ```
//! Shared ABI, values, codecs and pure validation. Device/ioctl operations live
//! in Native or Channel, never in this crate.
//! ```compile_fail
//! use slk_protocol::ioctl;
//! ```
pub mod advdata;
pub mod channel;
pub mod message_security;
pub use channel::{SleChannelInfo, SleChannelTxStatus, SleSessionTxStatus};
pub use message_security::{SleMessageSecurity, SleSendConstraint};
mod genl;
pub mod service_hash;
pub mod ssap;
#[cfg(test)]
mod retired_types;
#[cfg(test)]
mod tests;
mod types;

pub use advdata::*;
pub use genl::*;
pub use types::*;

pub use ssap::*;
