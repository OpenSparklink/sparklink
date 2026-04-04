mod adapter;
mod error;
mod event;
pub mod ffi;

pub use adapter::Adapter;
pub use error::Error;
pub use event::Event;
pub use slk_protocol as protocol;

pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests {
    use super::*;
    use std::ptr;

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
        assert_eq!(ok.unwrap(), 42);

        let err: Result<i32> = Err(Error::Timeout);
        assert!(err.is_err());
    }
}
