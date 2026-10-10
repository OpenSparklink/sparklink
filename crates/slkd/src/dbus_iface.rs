use std::collections::HashMap;
use zbus::interface;
use zbus::zvariant::Value;

use crate::state::{AdapterDirectory, SharedState};

/// Root D-Bus object at /org/sparklink
pub struct Root {
    adapters: AdapterDirectory,
}

impl Root {
    pub fn new(adapters: AdapterDirectory) -> Self {
        Self { adapters }
    }
}

#[interface(name = "org.sparklink.Manager")]
impl Root {
    /// Get the daemon version
    fn version(&self) -> &str {
        env!("CARGO_PKG_VERSION")
    }

    /// List available adapter object paths
    async fn list_adapters(&self) -> Vec<String> {
        self.adapters.lock().await.keys().cloned().collect()
    }
}

/// Adapter D-Bus object at /org/sparklink/slk0
pub struct AdapterIface {
    state: SharedState,
}

impl AdapterIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.Adapter")]
impl AdapterIface {
    /// Start device discovery (scanning)
    async fn start_discovery(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        st.start_scan()
            .map_err(|e| zbus::fdo::Error::Failed(format!("scan start failed: {e}")))
    }

    /// Stop device discovery
    async fn stop_discovery(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        st.stop_scan()
            .map_err(|e| zbus::fdo::Error::Failed(format!("scan stop failed: {e}")))
    }

    /// Connect to a device by address string "AA:BB:CC:DD:EE:FF"
    async fn connect_device(&self, address: &str) -> zbus::fdo::Result<()> {
        let addr = parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        let mut st = self.state.lock().await;
        st.connect_device(&addr)
            .map_err(|e| zbus::fdo::Error::Failed(format!("connect failed: {e}")))
    }

    /// Disconnect a device by connection handle
    async fn disconnect_device(&self, handle: u16) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        st.disconnect_device(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("disconnect failed: {e}")))
    }

    /// List discovered devices as (addr_hex, name, rssi, connected) tuples
    async fn get_devices(&self) -> Vec<(String, String, i16, bool)> {
        let st = self.state.lock().await;
        st.devices
            .values()
            .map(|d| {
                let addr_hex = d
                    .addr
                    .iter()
                    .map(|b| format!("{b:02X}"))
                    .collect::<Vec<_>>()
                    .join(":");
                (addr_hex, d.name.clone(), d.rssi as i16, d.connected)
            })
            .collect()
    }

    /// Exact received WS73 reports: sequence, generation, timestamp_ms,
    /// address, RSSI, complete header, data and explicit lost-record count.
    async fn get_reports(&self) -> Vec<(u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64)> {
        self.state
            .lock()
            .await
            .native_reports
            .iter()
            .map(|r| {
                (
                    r.sequence,
                    r.generation,
                    r.received_at_ms,
                    format_addr(&r.address),
                    i16::from(r.rssi),
                    r.header.clone(),
                    r.data.clone(),
                    r.lost,
                )
            })
            .collect()
    }

    #[zbus(property)]
    async fn ready(&self) -> bool {
        let st = self.state.lock().await;
        st.present && st.controller.flags == slk_protocol::CONTROLLER_READY
    }
    #[zbus(property)]
    async fn controller_state(&self) -> String {
        let st = self.state.lock().await;
        if !st.present {
            "Removed"
        } else {
            match st.controller.flags {
                slk_protocol::CONTROLLER_READY => "Ready",
                slk_protocol::CONTROLLER_FAULT => "Fault",
                _ => "Setup",
            }
        }
        .into()
    }
    #[zbus(property)]
    async fn generation(&self) -> u64 {
        self.state.lock().await.controller.generation
    }
    #[zbus(property)]
    async fn profile(&self) -> u32 {
        self.state.lock().await.controller.profile
    }
    #[zbus(property)]
    async fn address(&self) -> String {
        format_addr(&self.state.lock().await.controller.address)
    }
    #[zbus(property)]
    async fn controller_version(&self) -> Vec<u8> {
        self.state.lock().await.controller.version_tuple.to_vec()
    }
    #[zbus(property)]
    async fn features(&self) -> Vec<u8> {
        self.state.lock().await.controller.features.to_vec()
    }
    #[zbus(property)]
    async fn metadata_valid_fields(&self) -> u32 {
        self.state.lock().await.controller.valid_fields
    }
    #[zbus(property)]
    async fn command_credits(&self) -> u8 {
        self.state.lock().await.controller.command_credits
    }
    #[zbus(property)]
    async fn controller_error(&self) -> i32 {
        self.state.lock().await.controller.error
    }
    #[zbus(property)]
    async fn initialization_error(&self) -> String {
        self.state.lock().await.initialization_error.clone()
    }
    #[zbus(property)]
    async fn events_lost(&self) -> u64 {
        self.state.lock().await.events_lost
    }

    /// Adapter power state
    #[zbus(property)]
    async fn powered(&self) -> bool {
        self.state.lock().await.powered
    }

    #[zbus(property)]
    async fn set_powered(&self, value: bool) {
        self.state.lock().await.powered = value;
    }

    /// Whether discovery is active
    #[zbus(property)]
    async fn discovering(&self) -> bool {
        self.state.lock().await.discovering
    }

    /// Adapter name
    #[zbus(property)]
    async fn name(&self) -> String {
        self.state.lock().await.name.clone()
    }
}

/// D-Bus object representing a discovered device
pub struct DeviceIface {
    state: SharedState,
    addr: slk_protocol::SleAddr,
}

impl DeviceIface {
    pub fn new(state: SharedState, addr: slk_protocol::SleAddr) -> Self {
        Self { state, addr }
    }
}

#[interface(name = "org.sparklink.Device")]
impl DeviceIface {
    /// Connect to this device
    async fn connect(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        st.connect_device(&self.addr)
            .map_err(|e| zbus::fdo::Error::Failed(format!("connect failed: {e}")))
    }

    /// Disconnect from this device
    async fn disconnect(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        let handle = st
            .devices
            .get(&self.addr)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| zbus::fdo::Error::Failed("not connected".into()))?;
        st.disconnect_device(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("disconnect failed: {e}")))
    }

    /// Device MAC address "AA:BB:CC:DD:EE:FF"
    #[zbus(property)]
    async fn address(&self) -> String {
        format_addr(&self.addr)
    }

    /// Device name from advertisement
    #[zbus(property)]
    async fn name(&self) -> String {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.name.clone())
            .unwrap_or_default()
    }

    /// Last seen RSSI
    #[zbus(property)]
    async fn rssi(&self) -> i16 {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.rssi as i16)
            .unwrap_or(0)
    }

    /// Whether the device is currently connected
    #[zbus(property)]
    async fn connected(&self) -> bool {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.connected)
            .unwrap_or(false)
    }

    /// Discovery level from advertisement
    #[zbus(property)]
    async fn discovery_level(&self) -> u8 {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.discovery_level)
            .unwrap_or(0)
    }

    /// Raw advertisement data bytes
    async fn get_adv_data(&self) -> Vec<u8> {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.adv_data.clone())
            .unwrap_or_default()
    }

    /// Parsed 16-bit service UUIDs from advertisement TLV data
    #[zbus(property)]
    async fn service_uuids(&self) -> Vec<u16> {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.service_uuids.clone())
            .unwrap_or_default()
    }

    /// TX power level from advertisement (dBm), -128 if absent
    #[zbus(property)]
    async fn tx_power(&self) -> i16 {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .and_then(|d| d.tx_power)
            .map(|p| p as i16)
            .unwrap_or(-128)
    }

    /// Query connection info as a property dict.
    ///
    /// Returns key-value pairs: handle, state, data_mtu, data_mps,
    /// data_mode, ssap_mtu, ssap_reliable_mode, smtc_tx_credits,
    /// smtc_rx_credits, dudtc_tx_credits, dudtc_rx_credits,
    /// tx_bytes, rx_bytes.
    async fn get_connection_info(&self) -> zbus::fdo::Result<HashMap<String, Value<'static>>> {
        let st = self.state.lock().await;
        let handle = st
            .devices
            .get(&self.addr)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| zbus::fdo::Error::Failed("not connected".into()))?;
        let info = st
            .conn_info(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("conn_info failed: {e}")))?;
        let mut m = HashMap::new();
        m.insert("handle".into(), Value::from(info.handle));
        m.insert("state".into(), Value::from(info.state));
        m.insert("data_mtu".into(), Value::from(info.data_mtu));
        m.insert("data_mps".into(), Value::from(info.data_mps));
        m.insert("data_mode".into(), Value::from(info.data_mode));
        m.insert("svc_mtu".into(), Value::from(info.svc_mtu));
        m.insert("ssap_mtu".into(), Value::from(info.ssap_mtu));
        m.insert(
            "ssap_reliable_mode".into(),
            Value::from(info.ssap_reliable_mode),
        );
        m.insert(
            "ssap_version_major".into(),
            Value::from(info.ssap_version_major),
        );
        m.insert("smtc_tx_credits".into(), Value::from(info.smtc_tx_credits));
        m.insert("smtc_rx_credits".into(), Value::from(info.smtc_rx_credits));
        m.insert(
            "dudtc_tx_credits".into(),
            Value::from(info.dudtc_tx_credits),
        );
        m.insert(
            "dudtc_rx_credits".into(),
            Value::from(info.dudtc_rx_credits),
        );
        m.insert("tx_bytes".into(), Value::from(info.tx_bytes));
        m.insert("rx_bytes".into(), Value::from(info.rx_bytes));
        m.insert("bandwidth_mhz".into(), Value::from(info.bandwidth_mhz));
        m.insert("mcs_index".into(), Value::from(info.mcs_index));
        m.insert(
            "supervision_timeout".into(),
            Value::from(info.supervision_timeout),
        );
        Ok(m)
    }
}

fn parse_addr(s: &str) -> Result<slk_protocol::SleAddr, &'static str> {
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 6 {
        return Err("address must be AA:BB:CC:DD:EE:FF");
    }
    let mut addr = [0u8; 6];
    for (i, part) in parts.iter().enumerate() {
        addr[i] = u8::from_str_radix(part, 16).map_err(|_| "invalid hex byte")?;
    }
    Ok(addr)
}

pub(crate) fn format_addr(addr: &slk_protocol::SleAddr) -> String {
    format!(
        "{:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X}",
        addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
    )
}
