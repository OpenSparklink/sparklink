mod adapter;
mod error;
mod event;
pub mod ffi;
mod receiver;

pub use adapter::{Adapter, DEFAULT_DEV_PATH};
pub use error::Error;
pub use event::Event;
pub use receiver::EventReceiver;
mod controller_events;
pub use controller_events::{ControllerEventCursor, ControllerEventReceiver};
pub use slk_protocol as protocol;

pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests {
    use super::*;
    use std::ptr;

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

        let raw_evt: slk_protocol::SleDliEvent = unsafe { std::mem::zeroed() };
        let ev = Event::RawDli(raw_evt);
        assert!(format!("{ev:?}").contains("RawDli"));
    }

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
    fn result_type_alias() {
        let ok: Result<i32> = Ok(42);
        assert!(matches!(ok, Ok(42)));

        let err: Result<i32> = Err(Error::Timeout);
        assert!(err.is_err());
    }

    #[test]
    fn synchronous_control_and_ffi_open_without_tokio() {
        use std::os::fd::AsRawFd;
        let adapter = Adapter::open("/dev/null").expect("synchronous open requires no reactor");
        assert!(adapter.as_fd().as_raw_fd() >= 0);
        assert!(matches!(adapter.device_count(), Err(Error::Ioctl(_))));
        assert!(matches!(
            adapter.into_event_receiver(),
            Err(Error::InvalidParam(_))
        ));
        let path = b"/dev/null\0";
        let handle = unsafe { ffi::slk_adapter_open(path.as_ptr().cast()) };
        assert!(!handle.is_null());
        assert_eq!(unsafe { ffi::slk_device_count(handle) }, -1);
        unsafe { ffi::slk_adapter_free(handle) };
    }

    #[test]
    fn malformed_event_lengths_are_errors() {
        use slk_protocol::*;
        let mut event: SleDliEvent = unsafe { std::mem::zeroed() };
        event.event_type = EVT_DATA_RECV;
        event.data_len = u16::MAX;
        assert!(adapter::decode_event(event).is_err());
        for (event_type, length) in [
            (EVT_ADV_REPORT, 1),
            (EVT_HW_ERROR, 0),
            (EVT_ENCRYPTION_CHANGED, 0),
        ] {
            event.event_type = event_type;
            event.data_len = length;
            assert!(adapter::decode_event(event).is_err());
        }
    }
}
mod ws73_discovery;
pub use ws73_discovery::{
    WS73_BASIC_POLICY_VERSION, ws73_basic_advertisement, ws73_basic_scan, ws73_basic_stop,
    ws73_marker_data,
};
