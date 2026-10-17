//! Application SDK. Control requests use the pinned daemon broker; business
//! traffic uses already-authorized Channel fds. No Native management dependency.
mod client;
pub mod controller;
pub mod ffi;
pub mod peer;
pub mod ssap;
pub use client::{ApplicationConnection, ApplicationError, Client};
pub use slk_channel::Channel;
/// Local SSAP API access requirements, separate from operation indicators.
pub const SSAP_ACCESS_WRITE_ENCRYPTED: u32 = 1;
const _: () =
    assert!(SSAP_ACCESS_WRITE_ENCRYPTED == slk_protocol::ssap::access::SSAP_ACCESS_WRITE_ENCRYPTED);
pub const SSAP_ACCESS_WRITE_AUTHENTICATED: u32 = 2;
const _: () = assert!(
    SSAP_ACCESS_WRITE_AUTHENTICATED == slk_protocol::ssap::access::SSAP_ACCESS_WRITE_AUTHENTICATED
);
pub const SSAP_ACCESS_WRITE_AUTHORIZED: u32 = 4;
const _: () = assert!(
    SSAP_ACCESS_WRITE_AUTHORIZED == slk_protocol::ssap::access::SSAP_ACCESS_WRITE_AUTHORIZED
);
pub const SSAP_ACCESS_READ_ENCRYPTED: u32 = 8;
const _: () =
    assert!(SSAP_ACCESS_READ_ENCRYPTED == slk_protocol::ssap::access::SSAP_ACCESS_READ_ENCRYPTED);
pub const SSAP_ACCESS_READ_AUTHENTICATED: u32 = 16;
const _: () = assert!(
    SSAP_ACCESS_READ_AUTHENTICATED == slk_protocol::ssap::access::SSAP_ACCESS_READ_AUTHENTICATED
);
pub const SSAP_ACCESS_READ_AUTHORIZED: u32 = 32;
const _: () =
    assert!(SSAP_ACCESS_READ_AUTHORIZED == slk_protocol::ssap::access::SSAP_ACCESS_READ_AUTHORIZED);
pub const SSAP_ACCESS_VALID_MASK: u32 = 63;
const _: () = assert!(SSAP_ACCESS_VALID_MASK == slk_protocol::ssap::access::SSAP_ACCESS_VALID_MASK);
