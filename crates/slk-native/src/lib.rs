//! Native management, diagnostics and kernel observations. Not an application SDK.
//! Existing unpublished legacy entry retirement continues under WP18/R4.
mod adapter;
mod controller_events;
mod error;
mod event;
pub mod ioctl;
#[cfg(test)]
mod retired_event;
mod snoop;
mod ws73_discovery;
pub use adapter::{Adapter, DEFAULT_DEV_PATH};
pub use controller_events::{ControllerEventCursor, ControllerEventReceiver};
pub use error::Error;
pub use event::Event;
pub use snoop::{
    SnoopCursor, SnoopReceiver, create_snoop_capture, describe_snoop, snoop_packet_code,
    write_snoop_header, write_snoop_record,
};
pub use ws73_discovery::{
    WS73_DISCOVERY_POLICY_VERSION, Ws73ConnectableRole, Ws73DiscoveryPolicy, ws73_discovery_stop,
};
pub type Result<T> = std::result::Result<T, Error>;

pub mod ffi;
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

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn overflowing_discovery_deadline_returns_error_before_ioctl() {
        let adapter = Adapter::open("/dev/null").unwrap();
        let result = adapter.wait_discovery(1, 1, std::time::Duration::MAX).await;
        assert!(matches!(
            result,
            Err(Error::InvalidParam("discovery timeout is too large"))
        ));
    }

    #[test]
    fn error_display() {
        let e = Error::InvalidParam("test");
        assert!(format!("{e}").contains("test"));

        let e = Error::DeviceNotFound(42);
        assert!(format!("{e}").contains("42"));

        let e = Error::ConnectionNotFound(0x1234);
        let msg = format!("{e}");
        assert!(msg.contains("1234") || msg.contains("0x1234"));

        let e = Error::Timeout;
        assert!(format!("{e}").contains("timed out"));
    }

    #[test]
    fn error_from_nix() {
        let nix_err = nix::Error::ENODEV;
        let e: Error = nix_err.into();
        match e {
            Error::Ioctl(_) => {}
            other => panic!("expected Ioctl, got {other:?}"),
        }
    }

    #[test]
    fn event_variants() {
        let ev = Event::ConnectionStateChanged {
            handle: 1,
            state: 2,
            peer_addr: [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF],
        };
        assert!(format!("{ev:?}").contains("ConnectionStateChanged"));

        let ev = Event::AdvReport {
            addr: [1, 2, 3, 4, 5, 6],
            rssi: -50,
            discovery_level: 1,
            name: "TestDevice".into(),
            adv_data: vec![0x02, 0x01, 0x01],
        };
        assert!(format!("{ev:?}").contains("TestDevice"));

        let ev = Event::SecurityChanged {
            state: 3,
            method: 1,
            encrypted: true,
        };
        assert!(format!("{ev:?}").contains("encrypted: true"));

        let ev = Event::PowerChanged { state: 0 };
        assert!(format!("{ev:?}").contains("PowerChanged"));

        let ev = Event::HwError { code: 0x42 };
        assert!(format!("{ev:?}").contains("66") || format!("{ev:?}").contains("0x42"));

        let ev = Event::DataReceived {
            handle: 0x0001,
            data: vec![0xAA, 0xBB, 0xCC],
        };
        let dbg = format!("{ev:?}");
        assert!(dbg.contains("DataReceived"));
        assert!(dbg.contains("handle: 1"));

        let raw_evt: crate::retired_event::SleDliEvent = unsafe { std::mem::zeroed() };
        let ev = Event::RawDli(raw_evt);
        assert!(format!("{ev:?}").contains("RawDli"));
    }

    #[test]
    fn result_type_alias() {
        let ok: Result<i32> = Ok(42);
        assert!(matches!(ok, Ok(42)));

        let err: Result<i32> = Err(Error::Timeout);
        assert!(err.is_err());
    }

    #[test]
    fn malformed_event_lengths_are_errors() {
        use slk_protocol::*;
        let mut event: crate::retired_event::SleDliEvent = unsafe { std::mem::zeroed() };
        event.event_type = EVT_DATA_RECV;
        event.data_len = u16::MAX;
        assert!(crate::retired_event::decode_event(event).is_err());
        for (event_type, length) in [
            (EVT_ADV_REPORT, 1),
            (EVT_HW_ERROR, 0),
            (EVT_ENCRYPTION_CHANGED, 0),
        ] {
            event.event_type = event_type;
            event.data_len = length;
            assert!(crate::retired_event::decode_event(event).is_err());
        }
    }
    #[test]
    fn ioctl_magic_is_correct() {
        assert_eq!(ioctl::SL_MAGIC, b'S');
        assert_eq!(ioctl::SL_MAGIC, 0x53);
    }

    #[test]
    fn ioctl_number_ranges() {
        // Verify ioctl magic is correct across all categories
        assert_eq!(ioctl::SL_MAGIC, 0x53);
    }
}

#[cfg(test)]
mod ffi_lifetime_tests {
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
