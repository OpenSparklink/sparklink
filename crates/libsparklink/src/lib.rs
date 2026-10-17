//! Transitional C/SDK facade: Native Rust production consumers have moved to
//! slk-native. These management reexports remain only until the next C/Python
//! caller migration, not the target application SDK contract.
pub mod ffi;
pub use slk_native::{
    Adapter, ControllerEventCursor, ControllerEventReceiver, DEFAULT_DEV_PATH, Error, Event,
    Result, SnoopCursor, SnoopReceiver, Ws73ConnectableRole, Ws73DiscoveryPolicy,
    create_snoop_capture, describe_snoop, snoop_packet_code, write_snoop_header,
    write_snoop_record, ws73_discovery_stop,
};
pub use slk_protocol as protocol;
/// C header array bound, checked against the canonical protocol declaration.
pub const CONTROLLER_EVENT_PAYLOAD_MAX: usize = 288;
/// C header array bound, checked against the canonical protocol declaration.
pub const SNOOP_PAYLOAD_MAX: usize = 320;
/// C header constants, checked against the canonical protocol declaration.
pub const LINK_SNAPSHOT_MAX: usize = 16;
pub const LINK_SNAPSHOT_KNOWN: u32 = 1;
pub const SNOOP_REDACTED: u16 = 2;
pub const SECURITY_CAPABILITY_ONLY: u32 = 1;
pub const SECURITY_KEY_AGREEMENT_ONLY: u32 = 2;
pub const SECURITY_UNAUTHENTICATED_ENCRYPTION: u32 = 3;
const _: () = assert!(CONTROLLER_EVENT_PAYLOAD_MAX == slk_protocol::CONTROLLER_EVENT_PAYLOAD_MAX);
const _: () = assert!(SNOOP_PAYLOAD_MAX == slk_protocol::SNOOP_PAYLOAD_MAX);
const _: () = assert!(LINK_SNAPSHOT_MAX == slk_protocol::LINK_SNAPSHOT_MAX);
const _: () = assert!(LINK_SNAPSHOT_KNOWN == slk_protocol::LINK_SNAPSHOT_KNOWN);
const _: () = assert!(SECURITY_CAPABILITY_ONLY == slk_protocol::SECURITY_CAPABILITY_ONLY);
const _: () = assert!(SECURITY_KEY_AGREEMENT_ONLY == slk_protocol::SECURITY_KEY_AGREEMENT_ONLY);
const _: () = assert!(
    SECURITY_UNAUTHENTICATED_ENCRYPTION == slk_protocol::SECURITY_UNAUTHENTICATED_ENCRYPTION
);
const _: () = assert!(SNOOP_REDACTED == slk_protocol::SNOOP_REDACTED);

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

// Transitional Native C header constant, checked against the owner.
pub const WS73_DISCOVERY_POLICY_VERSION: u32 = 3;
const _: () = assert!(WS73_DISCOVERY_POLICY_VERSION == slk_native::WS73_DISCOVERY_POLICY_VERSION);

#[cfg(test)]
mod tests {
    use super::*;
    use std::ptr;
    #[test]
    fn ffi_null_safety() {
        let result = unsafe { ffi::slk_adapter_open(ptr::null()) };
        assert!(result.is_null());

        unsafe { ffi::slk_adapter_free(ptr::null_mut()) };

        let count = unsafe { ffi::slk_device_count(ptr::null()) };
        assert_eq!(count, -1);

        let ret = unsafe { ffi::slk_stop_scan(ptr::null()) };
        assert_eq!(ret, -1);

        let ret = unsafe { ffi::slk_encrypt_on(ptr::null()) };
        assert_eq!(ret, -1);

        let ret = unsafe { ffi::slk_get_role(ptr::null()) };
        assert_eq!(ret, -1);
    }

    #[test]
    fn ffi_open_nonexistent_device() {
        let path = b"/dev/sparklink_nonexistent_test\0";
        let result = unsafe { ffi::slk_adapter_open(path.as_ptr() as *const _) };
        assert!(result.is_null());
    }

    #[test]
    fn synchronous_control_and_ffi_open_without_tokio() {
        use std::os::fd::AsRawFd;
        let adapter = Adapter::open("/dev/null").expect("synchronous open requires no reactor");
        assert!(adapter.as_fd().as_raw_fd() >= 0);
        assert!(matches!(adapter.device_count(), Err(Error::Ioctl(_))));
        assert!(matches!(
            adapter.into_controller_event_receiver(),
            Err(Error::InvalidParam(_))
        ));
        let path = b"/dev/null\0";
        let handle = unsafe { ffi::slk_adapter_open(path.as_ptr().cast()) };
        assert!(!handle.is_null());
        assert_eq!(unsafe { ffi::slk_device_count(handle) }, -1);
        unsafe { ffi::slk_adapter_free(handle) };
    }
}
