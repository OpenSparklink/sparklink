use slk_protocol::{SleAddr, SleConnInfo, SleDliEvent};

/// Events received from the kernel SparkLink subsystem
#[derive(Debug)]
pub enum Event {
    /// Connection state changed
    ConnectionStateChanged {
        handle: u16,
        state: u8,
        peer_addr: SleAddr,
    },

    /// Advertisement report received during scanning
    AdvReport {
        addr: SleAddr,
        rssi: i8,
        discovery_level: u8,
        name: String,
    },

    /// Data received on a connection
    DataReceived {
        handle: u16,
        data: Vec<u8>,
    },

    /// Security state changed
    SecurityChanged {
        state: u8,
        method: u8,
        encrypted: bool,
    },

    /// Power state changed
    PowerChanged {
        state: u8,
    },

    /// Hardware error
    HwError {
        code: u8,
    },

    /// Raw DLI event (for unhandled event types)
    RawDli(SleDliEvent),

    /// Connection info update (polled)
    ConnInfoUpdate(SleConnInfo),
}
