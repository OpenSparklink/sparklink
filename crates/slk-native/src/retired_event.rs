// Historical U96cafc4 codec/shape; test-only, never a kernel consumer.
use crate::{Error, Event, Result};
use slk_protocol::*;
/// DLI event (ioctl 0x82)
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct SleDliEvent {
    pub event_type: u8,
    pub status: u8,
    pub handle: u16,
    pub opcode: u16,
    pub data_len: u16,
    pub data: [u8; 240],
    pub addr: SleAddr,
    pub _pad: [u8; 2],
}

impl Default for SleDliEvent {
    fn default() -> Self {
        // SAFETY: historical repr(C) contains only integer/byte fields.
        unsafe { core::mem::zeroed() }
    }
}
pub(crate) fn decode_event(raw: SleDliEvent) -> Result<Event> {
    let length = usize::from(raw.data_len);
    if length > raw.data.len() {
        return Err(Error::InvalidParam("event payload exceeds buffer"));
    }
    let minimum = match raw.event_type {
        EVT_ADV_REPORT => 2,
        EVT_ENCRYPTION_CHANGED | EVT_HW_ERROR => 1,
        _ => 0,
    };
    if length < minimum {
        return Err(Error::InvalidParam("truncated event payload"));
    }
    Ok(match raw.event_type {
        EVT_CONN_COMPLETE => Event::ConnectionStateChanged {
            handle: raw.handle,
            state: if raw.status == 0 {
                ConnState::Connected as u8
            } else {
                ConnState::Idle as u8
            },
            peer_addr: raw.addr,
        },
        EVT_DISCONNECTED => Event::ConnectionStateChanged {
            handle: raw.handle,
            state: ConnState::Idle as u8,
            peer_addr: raw.addr,
        },
        EVT_ADV_REPORT => {
            let rssi = raw.data[0] as i8;
            let discovery_level = raw.data[1];
            let adv_data_len = (raw.data_len as usize).saturating_sub(2);
            let adv_data = raw.data[2..2 + adv_data_len].to_vec();
            let (entries, _) = slk_protocol::parse_adv_data(&adv_data);
            let name = slk_protocol::find_local_name(&entries)
                .unwrap_or_default()
                .to_string();
            Event::AdvReport {
                addr: raw.addr,
                rssi,
                discovery_level,
                name,
                adv_data,
            }
        }
        EVT_DATA_RECV => Event::DataReceived {
            handle: raw.handle,
            data: raw.data[..raw.data_len as usize].to_vec(),
        },
        EVT_ENCRYPTION_CHANGED => Event::SecurityChanged {
            state: if raw.data[0] != 0 { 3 } else { 0 },
            method: 0,
            encrypted: raw.data[0] != 0,
        },
        EVT_HW_ERROR => Event::HwError { code: raw.data[0] },
        _ => Event::RawDli(raw),
    })
}
