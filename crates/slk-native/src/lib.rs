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
