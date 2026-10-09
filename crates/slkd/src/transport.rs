//! SparkLink Transport Layer (T/XS 20007-2025)
//!
//! Implements packet encoding/decoding and connection state machines for
//! the SparkLink Basic Service Layer transport protocol.
//!
//! Supports two modes:
//!   - Connectionless (CLTP): unreliable datagram delivery
//!   - Connected (LWCTP): reliable, sequenced delivery with flow control
//!
//! All header fields use big-endian byte order.

/// Protocol version defined in TXS-20007-2025 section 6.2.
const PROTOCOL_VERSION: u8 = 1;

// ---------------------------------------------------------------------------
// Optional field bitmap bits (section 6.4)
// ---------------------------------------------------------------------------

const OPT_PAYLOAD_LEN: u16 = 1 << 0;
const OPT_CHECKSUM: u16 = 1 << 1;
const OPT_TRANSPORT_CTRL: u16 = 1 << 2;
const OPT_RECV_WINDOW: u16 = 1 << 3;

// ---------------------------------------------------------------------------
// Transport control bits (section 6.4.3, low byte)
// ---------------------------------------------------------------------------

/// Start — sender indicates readiness to transmit.
const CTRL_START: u16 = 1 << 0;
/// Start-Ack — receiver confirms start.
const CTRL_START_ACK: u16 = 1 << 1;
/// End — sender indicates transmission complete.
const CTRL_END: u16 = 1 << 2;
/// End-Ack — receiver confirms end.
const CTRL_END_ACK: u16 = 1 << 3;
/// Reset — reset current connection.
const CTRL_RESET: u16 = 1 << 4;

/// Transport control flags parsed from the 2-byte option field.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct TransportControl {
    pub start: bool,
    pub start_ack: bool,
    pub end: bool,
    pub end_ack: bool,
    pub reset: bool,
}

impl TransportControl {
    fn from_bits(bits: u16) -> Self {
        Self {
            start: bits & CTRL_START != 0,
            start_ack: bits & CTRL_START_ACK != 0,
            end: bits & CTRL_END != 0,
            end_ack: bits & CTRL_END_ACK != 0,
            reset: bits & CTRL_RESET != 0,
        }
    }

    fn to_bits(self) -> u16 {
        let mut v = 0u16;
        if self.start {
            v |= CTRL_START;
        }
        if self.start_ack {
            v |= CTRL_START_ACK;
        }
        if self.end {
            v |= CTRL_END;
        }
        if self.end_ack {
            v |= CTRL_END_ACK;
        }
        if self.reset {
            v |= CTRL_RESET;
        }
        v
    }
}

// ---------------------------------------------------------------------------
// Optional fields
// ---------------------------------------------------------------------------

/// Parsed optional fields from a transport packet header.
#[derive(Debug, Clone, Default)]
pub struct OptionalFields {
    pub payload_len: Option<u16>,
    pub checksum: Option<u16>,
    pub transport_ctrl: Option<TransportControl>,
    pub recv_window: Option<u16>,
}

impl OptionalFields {
    fn bitmap(&self) -> u16 {
        let mut b = 0u16;
        if self.payload_len.is_some() {
            b |= OPT_PAYLOAD_LEN;
        }
        if self.checksum.is_some() {
            b |= OPT_CHECKSUM;
        }
        if self.transport_ctrl.is_some() {
            b |= OPT_TRANSPORT_CTRL;
        }
        if self.recv_window.is_some() {
            b |= OPT_RECV_WINDOW;
        }
        b
    }

    /// Encode optional fields into bytes (bitmap + fields + padding).
    /// Returns empty vec if no options are present.
    fn encode(&self) -> Vec<u8> {
        let bm = self.bitmap();
        if bm == 0 {
            return Vec::new();
        }
        let mut buf = Vec::new();
        buf.extend_from_slice(&bm.to_be_bytes());
        if let Some(v) = self.payload_len {
            buf.extend_from_slice(&v.to_be_bytes());
        }
        if let Some(v) = self.checksum {
            buf.extend_from_slice(&v.to_be_bytes());
        }
        if let Some(tc) = self.transport_ctrl {
            buf.extend_from_slice(&tc.to_bits().to_be_bytes());
        }
        if let Some(v) = self.recv_window {
            buf.extend_from_slice(&v.to_be_bytes());
        }
        // Pad to 4-byte alignment
        let total = buf.len();
        let rem = total % 4;
        if rem != 0 {
            buf.resize(total + 4 - rem, 0);
        }
        buf
    }

    fn decode(data: &[u8]) -> Result<(Self, usize), PacketError> {
        if data.len() < 2 {
            return Err(PacketError::TooShort);
        }
        let bm = u16::from_be_bytes([data[0], data[1]]);
        let mut pos = 2;
        let mut opts = OptionalFields::default();

        if bm & OPT_PAYLOAD_LEN != 0 {
            if pos + 2 > data.len() {
                return Err(PacketError::TooShort);
            }
            opts.payload_len = Some(u16::from_be_bytes([data[pos], data[pos + 1]]));
            pos += 2;
        }
        if bm & OPT_CHECKSUM != 0 {
            if pos + 2 > data.len() {
                return Err(PacketError::TooShort);
            }
            opts.checksum = Some(u16::from_be_bytes([data[pos], data[pos + 1]]));
            pos += 2;
        }
        if bm & OPT_TRANSPORT_CTRL != 0 {
            if pos + 2 > data.len() {
                return Err(PacketError::TooShort);
            }
            let bits = u16::from_be_bytes([data[pos], data[pos + 1]]);
            opts.transport_ctrl = Some(TransportControl::from_bits(bits));
            pos += 2;
        }
        if bm & OPT_RECV_WINDOW != 0 {
            if pos + 2 > data.len() {
                return Err(PacketError::TooShort);
            }
            opts.recv_window = Some(u16::from_be_bytes([data[pos], data[pos + 1]]));
            pos += 2;
        }
        // Skip padding to 4-byte alignment
        let rem = pos % 4;
        if rem != 0 {
            pos += 4 - rem;
        }
        Ok((opts, pos))
    }
}

// ---------------------------------------------------------------------------
// Packet types
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub enum PacketError {
    TooShort,
    BadVersion,
    ChecksumMismatch,
}

/// Connectionless transport packet (CLTP, section 6.2).
#[derive(Debug, Clone)]
pub struct ConnectionlessPacket {
    pub src_port: u16,
    pub dst_port: u16,
    pub options: OptionalFields,
    pub payload: Vec<u8>,
}

impl ConnectionlessPacket {
    pub fn new(src_port: u16, dst_port: u16, payload: Vec<u8>) -> Self {
        Self {
            src_port,
            dst_port,
            options: OptionalFields::default(),
            payload,
        }
    }

    /// Encode the packet into wire format.
    pub fn encode(&self) -> Vec<u8> {
        let opt_bytes = self.options.encode();
        let opt_words = (opt_bytes.len() / 4) as u8;

        let first_byte = (PROTOCOL_VERSION << 5) | (opt_words & 0x1F);
        let mut buf = Vec::with_capacity(5 + opt_bytes.len() + self.payload.len());
        buf.push(first_byte);
        buf.extend_from_slice(&self.src_port.to_be_bytes());
        buf.extend_from_slice(&self.dst_port.to_be_bytes());
        buf.extend_from_slice(&opt_bytes);
        buf.extend_from_slice(&self.payload);
        buf
    }

    /// Decode a connectionless packet from wire bytes.
    pub fn decode(data: &[u8]) -> Result<Self, PacketError> {
        if data.len() < 5 {
            return Err(PacketError::TooShort);
        }
        let version = data[0] >> 5;
        if version != PROTOCOL_VERSION {
            return Err(PacketError::BadVersion);
        }
        let opt_words = (data[0] & 0x1F) as usize;
        let opt_len = opt_words * 4;
        let src_port = u16::from_be_bytes([data[1], data[2]]);
        let dst_port = u16::from_be_bytes([data[3], data[4]]);

        let hdr_end = 5 + opt_len;
        if data.len() < hdr_end {
            return Err(PacketError::TooShort);
        }

        let options = if opt_len > 0 {
            OptionalFields::decode(&data[5..5 + opt_len])?.0
        } else {
            OptionalFields::default()
        };

        let payload = data[hdr_end..].to_vec();
        Ok(Self {
            src_port,
            dst_port,
            options,
            payload,
        })
    }
}

/// Connected transport packet (LWCTP, section 6.3).
#[derive(Debug, Clone)]
pub struct ConnectedPacket {
    pub src_port: u16,
    pub dst_port: u16,
    pub seq_no: u32,
    pub ack_no: u32,
    pub options: OptionalFields,
    pub payload: Vec<u8>,
}

impl ConnectedPacket {
    pub fn new(src_port: u16, dst_port: u16, seq_no: u32, ack_no: u32, payload: Vec<u8>) -> Self {
        Self {
            src_port,
            dst_port,
            seq_no,
            ack_no,
            options: OptionalFields::default(),
            payload,
        }
    }

    /// Encode the packet into wire format.
    pub fn encode(&self) -> Vec<u8> {
        let opt_bytes = self.options.encode();
        let opt_words = (opt_bytes.len() / 4) as u8;

        let first_byte = (PROTOCOL_VERSION << 5) | (opt_words & 0x1F);
        let mut buf = Vec::with_capacity(13 + opt_bytes.len() + self.payload.len());
        buf.push(first_byte);
        buf.extend_from_slice(&self.src_port.to_be_bytes());
        buf.extend_from_slice(&self.dst_port.to_be_bytes());
        buf.extend_from_slice(&self.seq_no.to_be_bytes());
        buf.extend_from_slice(&self.ack_no.to_be_bytes());
        buf.extend_from_slice(&opt_bytes);
        buf.extend_from_slice(&self.payload);
        buf
    }

    /// Decode a connected packet from wire bytes.
    pub fn decode(data: &[u8]) -> Result<Self, PacketError> {
        if data.len() < 13 {
            return Err(PacketError::TooShort);
        }
        let version = data[0] >> 5;
        if version != PROTOCOL_VERSION {
            return Err(PacketError::BadVersion);
        }
        let opt_words = (data[0] & 0x1F) as usize;
        let opt_len = opt_words * 4;
        let src_port = u16::from_be_bytes([data[1], data[2]]);
        let dst_port = u16::from_be_bytes([data[3], data[4]]);
        let seq_no = u32::from_be_bytes([data[5], data[6], data[7], data[8]]);
        let ack_no = u32::from_be_bytes([data[9], data[10], data[11], data[12]]);

        let hdr_end = 13 + opt_len;
        if data.len() < hdr_end {
            return Err(PacketError::TooShort);
        }

        let options = if opt_len > 0 {
            OptionalFields::decode(&data[13..13 + opt_len])?.0
        } else {
            OptionalFields::default()
        };

        let payload = data[hdr_end..].to_vec();
        Ok(Self {
            src_port,
            dst_port,
            seq_no,
            ack_no,
            options,
            payload,
        })
    }
}

// ---------------------------------------------------------------------------
// Connection state machines (section 7.3.2)
// ---------------------------------------------------------------------------

/// Sender-side connection state (section 7.3.2, figure 11).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SenderState {
    /// 0 — Closed: transmission not started or previous cycle complete.
    Closed,
    /// 1 — WaitStartAck: sent Start, waiting for Start-Ack.
    WaitStartAck,
    /// 2 — Sending: actively transmitting data.
    Sending,
    /// 3 — WaitEndAck: sent End, waiting for End-Ack.
    WaitEndAck,
    /// 4 — Reset: local fault or received Reset from peer.
    Reset,
}

/// Receiver-side connection state (section 7.3.2, figure 12).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReceiverState {
    /// 0 — Closed.
    Closed,
    /// 1 — Receiving: accepted Start, sent Start-Ack, receiving data.
    Receiving,
    /// 2 — EndTransmit: received End, sent End-Ack, cleaning up.
    EndTransmit,
    /// 3 — Reset: local fault or received Reset from peer.
    Reset,
}

/// Events that drive sender state transitions.
#[derive(Debug, Clone, Copy)]
pub enum SenderEvent {
    /// User initiates data transmission.
    StartTransmission,
    /// Received Start-Ack from receiver.
    RecvStartAck,
    /// All data has been sent.
    TransmissionComplete,
    /// Received End-Ack from receiver.
    RecvEndAck,
    /// Local error detected.
    Error,
    /// Received Reset from peer.
    RecvReset,
    /// Reset processing complete.
    ResetComplete,
}

/// Events that drive receiver state transitions.
#[derive(Debug, Clone, Copy)]
pub enum ReceiverEvent {
    /// Received Start from sender.
    RecvStart,
    /// Received End from sender.
    RecvEnd,
    /// Local cleanup after End complete.
    CloseComplete,
    /// Local error detected.
    Error,
    /// Received Reset from peer.
    RecvReset,
    /// Reset processing complete.
    ResetComplete,
}

/// Action requested by the state machine after a transition.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    None,
    SendStart,
    SendStartAck,
    SendEnd,
    SendEndAck,
    SendReset,
}

impl SenderState {
    /// Apply an event and return the new state and required action.
    pub fn next(self, event: SenderEvent) -> (Self, Action) {
        match (self, event) {
            (Self::Closed, SenderEvent::StartTransmission) => {
                (Self::WaitStartAck, Action::SendStart)
            }
            (Self::WaitStartAck, SenderEvent::RecvStartAck) => (Self::Sending, Action::None),
            (Self::Sending, SenderEvent::TransmissionComplete) => {
                (Self::WaitEndAck, Action::SendEnd)
            }
            (Self::WaitEndAck, SenderEvent::RecvEndAck) => (Self::Closed, Action::None),
            // Error/Reset from any active state
            (Self::WaitStartAck | Self::Sending | Self::WaitEndAck, SenderEvent::Error) => {
                (Self::Reset, Action::SendReset)
            }
            (Self::WaitStartAck | Self::Sending | Self::WaitEndAck, SenderEvent::RecvReset) => {
                (Self::Reset, Action::None)
            }
            (Self::Reset, SenderEvent::ResetComplete) => (Self::Closed, Action::None),
            // Stay in current state for unhandled events
            _ => (self, Action::None),
        }
    }
}

impl ReceiverState {
    /// Apply an event and return the new state and required action.
    pub fn next(self, event: ReceiverEvent) -> (Self, Action) {
        match (self, event) {
            (Self::Closed, ReceiverEvent::RecvStart) => (Self::Receiving, Action::SendStartAck),
            (Self::Receiving, ReceiverEvent::RecvEnd) => (Self::EndTransmit, Action::SendEndAck),
            (Self::EndTransmit, ReceiverEvent::CloseComplete) => (Self::Closed, Action::None),
            // Error/Reset from active states
            (Self::Receiving, ReceiverEvent::Error) => (Self::Reset, Action::SendReset),
            (Self::Receiving, ReceiverEvent::RecvReset) => (Self::Reset, Action::None),
            (Self::EndTransmit, ReceiverEvent::Error) => (Self::Reset, Action::SendReset),
            (Self::EndTransmit, ReceiverEvent::RecvReset) => (Self::Reset, Action::None),
            (Self::Reset, ReceiverEvent::ResetComplete) => (Self::Closed, Action::None),
            _ => (self, Action::None),
        }
    }
}

// ---------------------------------------------------------------------------
// Checksum (section 6.4.2)
// ---------------------------------------------------------------------------

/// Compute the ones-complement checksum over the given data.
///
/// The checksum field in the header should be zeroed before computation.
/// If the data length is odd, a zero padding byte is appended internally.
pub fn compute_checksum(data: &[u8]) -> u16 {
    let mut sum: u32 = 0;
    let mut i = 0;
    while i + 1 < data.len() {
        sum += u16::from_be_bytes([data[i], data[i + 1]]) as u32;
        i += 2;
    }
    if i < data.len() {
        sum += (data[i] as u32) << 8;
    }
    while sum >> 16 != 0 {
        sum = (sum & 0xFFFF) + (sum >> 16);
    }
    !(sum as u16)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connectionless_roundtrip() {
        let pkt = ConnectionlessPacket::new(0x1000, 0x2000, vec![0x01, 0x02, 0x03]);
        let wire = pkt.encode();
        let decoded = ConnectionlessPacket::decode(&wire).unwrap();
        assert_eq!(decoded.src_port, 0x1000);
        assert_eq!(decoded.dst_port, 0x2000);
        assert_eq!(decoded.payload, vec![0x01, 0x02, 0x03]);
    }

    #[test]
    fn connected_roundtrip() {
        let pkt = ConnectedPacket::new(100, 200, 1, 0, vec![0xAA, 0xBB]);
        let wire = pkt.encode();
        let decoded = ConnectedPacket::decode(&wire).unwrap();
        assert_eq!(decoded.src_port, 100);
        assert_eq!(decoded.dst_port, 200);
        assert_eq!(decoded.seq_no, 1);
        assert_eq!(decoded.ack_no, 0);
        assert_eq!(decoded.payload, vec![0xAA, 0xBB]);
    }

    #[test]
    fn connected_with_options() {
        let mut pkt = ConnectedPacket::new(1, 2, 100, 0, vec![0x42]);
        pkt.options.payload_len = Some(1);
        pkt.options.transport_ctrl = Some(TransportControl {
            start: true,
            ..Default::default()
        });
        let wire = pkt.encode();
        let decoded = ConnectedPacket::decode(&wire).unwrap();
        assert_eq!(decoded.options.payload_len, Some(1));
        assert!(decoded.options.transport_ctrl.unwrap().start);
        assert!(!decoded.options.transport_ctrl.unwrap().end);
        assert_eq!(decoded.payload, vec![0x42]);
    }

    #[test]
    fn version_check() {
        let mut wire = ConnectionlessPacket::new(0, 0, vec![]).encode();
        wire[0] = 0b010_00000; // version 2
        assert!(matches!(
            ConnectionlessPacket::decode(&wire),
            Err(PacketError::BadVersion)
        ));
    }

    #[test]
    fn checksum_rfc_style() {
        let data = [0x00, 0x01, 0x00, 0x02];
        let cs = compute_checksum(&data);
        // Verify: sum of words + checksum should fold to 0xFFFF
        let verify: u32 = 0x0001u32 + 0x0002u32 + cs as u32;
        assert_eq!(verify & 0xFFFF, 0xFFFF);
    }

    #[test]
    fn checksum_odd_length() {
        let data = [0x01, 0x02, 0x03];
        let cs = compute_checksum(&data);
        // Verify: 0x0102 + 0x0300 + cs should fold to 0xFFFF
        let mut sum = 0x0102u32 + 0x0300u32 + cs as u32;
        while sum >> 16 != 0 {
            sum = (sum & 0xFFFF) + (sum >> 16);
        }
        assert_eq!(sum as u16, 0xFFFF);
    }

    #[test]
    fn sender_state_lifecycle() {
        let mut s = SenderState::Closed;
        let (ns, act) = s.next(SenderEvent::StartTransmission);
        s = ns;
        assert_eq!(s, SenderState::WaitStartAck);
        assert_eq!(act, Action::SendStart);

        let (ns, _) = s.next(SenderEvent::RecvStartAck);
        s = ns;
        assert_eq!(s, SenderState::Sending);

        let (ns, act) = s.next(SenderEvent::TransmissionComplete);
        s = ns;
        assert_eq!(s, SenderState::WaitEndAck);
        assert_eq!(act, Action::SendEnd);

        let (ns, _) = s.next(SenderEvent::RecvEndAck);
        s = ns;
        assert_eq!(s, SenderState::Closed);
    }

    #[test]
    fn receiver_state_lifecycle() {
        let mut s = ReceiverState::Closed;
        let (ns, act) = s.next(ReceiverEvent::RecvStart);
        s = ns;
        assert_eq!(s, ReceiverState::Receiving);
        assert_eq!(act, Action::SendStartAck);

        let (ns, act) = s.next(ReceiverEvent::RecvEnd);
        s = ns;
        assert_eq!(s, ReceiverState::EndTransmit);
        assert_eq!(act, Action::SendEndAck);

        let (ns, _) = s.next(ReceiverEvent::CloseComplete);
        s = ns;
        assert_eq!(s, ReceiverState::Closed);
    }

    #[test]
    fn sender_error_triggers_reset() {
        let s = SenderState::Sending;
        let (ns, act) = s.next(SenderEvent::Error);
        assert_eq!(ns, SenderState::Reset);
        assert_eq!(act, Action::SendReset);

        let (ns, _) = ns.next(SenderEvent::ResetComplete);
        assert_eq!(ns, SenderState::Closed);
    }

    #[test]
    fn receiver_reset_from_peer() {
        let s = ReceiverState::Receiving;
        let (ns, act) = s.next(ReceiverEvent::RecvReset);
        assert_eq!(ns, ReceiverState::Reset);
        assert_eq!(act, Action::None);

        let (ns, _) = ns.next(ReceiverEvent::ResetComplete);
        assert_eq!(ns, ReceiverState::Closed);
    }

    #[test]
    fn transport_control_roundtrip() {
        let tc = TransportControl {
            start: true,
            start_ack: false,
            end: true,
            end_ack: false,
            reset: false,
        };
        let bits = tc.to_bits();
        assert_eq!(bits, 0x05); // bit 0 + bit 2
        let decoded = TransportControl::from_bits(bits);
        assert_eq!(decoded, tc);
    }

    #[test]
    fn connectionless_no_options() {
        let pkt = ConnectionlessPacket::new(0x0001, 0x0002, vec![]);
        let wire = pkt.encode();
        // header: 1 byte (version|opt_words) + 2 src + 2 dst = 5 bytes
        assert_eq!(wire.len(), 5);
        assert_eq!(wire[0] >> 5, PROTOCOL_VERSION);
        assert_eq!(wire[0] & 0x1F, 0); // no options
    }

    #[test]
    fn connected_header_size() {
        let pkt = ConnectedPacket::new(0, 0, 1, 0, vec![]);
        let wire = pkt.encode();
        // 1 + 2 + 2 + 4 + 4 = 13 bytes minimum
        assert_eq!(wire.len(), 13);
    }
}
