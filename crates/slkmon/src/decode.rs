use slk_protocol::*;

pub fn print_event(event: &SleDliEvent, timestamp: &str, hexdump: bool) {
    let type_name = event_type_name(event.event_type);
    let data_len = event.data_len as usize;

    println!(
        "[{timestamp}] {type_name} (type={:#04x}) handle={:#06x} status={}",
        event.event_type, event.handle, event.status
    );

    match event.event_type {
        EVT_CONN_COMPLETE => {
            let state = if event.status == 0 {
                "CONNECTED"
            } else {
                "FAILED"
            };
            let addr = format_addr(&event.addr);
            println!("    Peer: {addr}  Result: {state}");
        }
        EVT_DISCONNECTED => {
            let reason = event.data.first().copied().unwrap_or(0);
            println!("    Handle: {:#06x}  Reason: {:#04x}", event.handle, reason);
        }
        EVT_ADV_REPORT => {
            let addr = format_addr(&event.addr);
            let rssi = event.data[0] as i8;
            let disc_level = event.data[1];
            let adv_len = (data_len).saturating_sub(2);
            let adv_data = &event.data[2..2 + adv_len];
            let (entries, _) = slk_protocol::parse_adv_data(adv_data);
            let name = slk_protocol::find_local_name(&entries).unwrap_or_default();
            let uuids = slk_protocol::collect_service_uuids16(&entries);
            println!("    Peer: {addr}  RSSI: {rssi} dBm  Level: {disc_level}  Name: \"{name}\"");
            if !uuids.is_empty() {
                let uuid_str: Vec<String> = uuids.iter().map(|u| format!("{u:#06x}")).collect();
                println!("    Services: {}", uuid_str.join(", "));
            }
        }
        EVT_DATA_RECV => {
            println!(
                "    Data: {} bytes on handle {:#06x}",
                data_len, event.handle
            );
            if data_len > 0 {
                print_data_summary(&event.data[..data_len]);
            }
        }
        EVT_ENCRYPTION_CHANGED => {
            let enabled = event.data.first().copied().unwrap_or(0) != 0;
            println!("    Handle: {:#06x}  Encrypted: {enabled}", event.handle);
        }
        EVT_PAIR_REQUEST => {
            let addr = format_addr(&event.addr);
            let method = event.data.first().copied().unwrap_or(0);
            println!("    Peer: {addr}  Method: {method}");
        }
        EVT_HW_ERROR => {
            let code = event.data.first().copied().unwrap_or(0);
            println!("    Error code: {:#04x}", code);
        }
        _ => {
            if data_len > 0 {
                print_data_summary(&event.data[..data_len]);
            }
        }
    }

    if hexdump && data_len > 0 {
        print_hexdump(&event.data[..data_len]);
    }
}

fn event_type_name(t: u8) -> &'static str {
    match t {
        EVT_CMD_COMPLETE => "CommandComplete",
        EVT_CMD_STATUS => "CommandStatus",
        EVT_ADV_REPORT => "AdvertisementReport",
        EVT_CONN_COMPLETE => "ConnectionComplete",
        EVT_DATA_RECV => "DataReceived",
        EVT_DISCONNECTED => "Disconnected",
        EVT_ENCRYPTION_CHANGED => "EncryptionChanged",
        EVT_PAIR_REQUEST => "PairRequest",
        EVT_HW_ERROR => "HardwareError",
        EVT_BROADCAST_END => "BroadcastEnd",
        EVT_PHY_UPDATE => "PhyUpdate",
        _ => "Unknown",
    }
}

fn format_addr(addr: &[u8; 6]) -> String {
    format!(
        "{:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X}",
        addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
    )
}

fn print_data_summary(data: &[u8]) {
    let preview_len = data.len().min(16);
    let hex: String = data[..preview_len]
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect::<Vec<_>>()
        .join(" ");
    let suffix = if data.len() > 16 { "..." } else { "" };
    println!("    Data preview: {hex}{suffix}");
}

fn print_hexdump(data: &[u8]) {
    for (offset, chunk) in data.chunks(16).enumerate() {
        let addr = offset * 16;
        let hex: String = chunk
            .iter()
            .map(|b| format!("{:02x}", b))
            .collect::<Vec<_>>()
            .join(" ");
        let ascii: String = chunk
            .iter()
            .map(|&b| {
                if b.is_ascii_graphic() || b == b' ' {
                    b as char
                } else {
                    '.'
                }
            })
            .collect();
        println!("    {addr:04x}: {hex:<48} {ascii}");
    }
}
