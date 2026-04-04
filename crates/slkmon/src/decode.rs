use slk_protocol::*;

pub fn print_event(event: &SleDliEvent, timestamp: &str, hexdump: bool) {
    let type_name = event_type_name(event.event_type);
    let data_len = event.data_len as usize;

    println!(
        "[{timestamp}] {type_name} (type={:#04x}) handle={:#06x} status={}",
        event.event_type, event.handle, event.status
    );

    match event.event_type {
        EVT_CONN_STATE => {
            let state = match event.status {
                0 => "IDLE",
                1 => "CONNECTING",
                2 => "CONNECTED",
                3 => "DISCONNECTING",
                _ => "UNKNOWN",
            };
            let addr = format_addr(&event.addr);
            println!("    Peer: {addr}  State: {state}");
        }
        EVT_ADV_REPORT => {
            let addr = format_addr(&event.addr);
            let rssi = event.status as i8;
            let name_end = event.data[..data_len]
                .iter()
                .position(|&b| b == 0)
                .unwrap_or(data_len);
            let name = std::str::from_utf8(&event.data[..name_end]).unwrap_or("<binary>");
            println!("    Peer: {addr}  RSSI: {rssi} dBm  Name: \"{name}\"");
        }
        EVT_DATA_RECV => {
            println!("    Data: {} bytes on handle {:#06x}", data_len, event.handle);
            if data_len > 0 {
                print_data_summary(&event.data[..data_len]);
            }
        }
        EVT_SEC_CHANGED => {
            let sec_state = match event.data.first().copied().unwrap_or(0) {
                0 => "none",
                1 => "pairing",
                2 => "paired",
                3 => "encrypted",
                _ => "unknown",
            };
            let method = match event.data.get(1).copied().unwrap_or(0) {
                0 => "none",
                1 => "just_works",
                2 => "psk",
                _ => "unknown",
            };
            let encrypted = event.data.get(2).copied().unwrap_or(0) != 0;
            println!("    State: {sec_state}  Method: {method}  Encrypted: {encrypted}");
        }
        EVT_PWR_CHANGED => {
            let pwr_state = event.data.first().copied().unwrap_or(0);
            println!("    Power state: {pwr_state}");
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
        EVT_CONN_STATE => "ConnectionStateChanged",
        EVT_ADV_REPORT => "AdvertisementReport",
        EVT_DATA_RECV => "DataReceived",
        EVT_SEC_CHANGED => "SecurityChanged",
        EVT_PWR_CHANGED => "PowerChanged",
        EVT_HW_ERROR => "HardwareError",
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
            .map(|&b| if b.is_ascii_graphic() || b == b' ' { b as char } else { '.' })
            .collect();
        println!("    {addr:04x}: {hex:<48} {ascii}");
    }
}
