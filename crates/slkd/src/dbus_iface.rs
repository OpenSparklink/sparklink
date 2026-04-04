use zbus::interface;

use crate::state::SharedState;

/// Root D-Bus object at /org/sparklink
pub struct Root {
    state: SharedState,
}

impl Root {
    pub fn new(state: SharedState) -> Self {
        Self { state }
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
        vec!["/org/sparklink/slk0".into()]
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
        st.start_scan().map_err(|e| {
            zbus::fdo::Error::Failed(format!("scan start failed: {e}"))
        })
    }

    /// Stop device discovery
    async fn stop_discovery(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        st.stop_scan().map_err(|e| {
            zbus::fdo::Error::Failed(format!("scan stop failed: {e}"))
        })
    }

    /// Connect to a device by address string "AA:BB:CC:DD:EE:FF"
    async fn connect_device(&self, address: &str) -> zbus::fdo::Result<()> {
        let addr = parse_addr(address).map_err(|e| {
            zbus::fdo::Error::InvalidArgs(e.to_string())
        })?;
        let mut st = self.state.lock().await;
        st.connect_device(&addr).map_err(|e| {
            zbus::fdo::Error::Failed(format!("connect failed: {e}"))
        })
    }

    /// Disconnect a device by connection handle
    async fn disconnect_device(&self, handle: u16) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        st.disconnect_device(handle).map_err(|e| {
            zbus::fdo::Error::Failed(format!("disconnect failed: {e}"))
        })
    }

    /// List discovered device object paths
    async fn get_devices(&self) -> Vec<String> {
        let st = self.state.lock().await;
        st.devices.values().map(|d| d.object_path.clone()).collect()
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
        st.connect_device(&self.addr).map_err(|e| {
            zbus::fdo::Error::Failed(format!("connect failed: {e}"))
        })
    }

    /// Disconnect from this device
    async fn disconnect(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        let handle = st.devices.get(&self.addr)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| zbus::fdo::Error::Failed("not connected".into()))?;
        st.disconnect_device(handle).map_err(|e| {
            zbus::fdo::Error::Failed(format!("disconnect failed: {e}"))
        })
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
        st.devices.get(&self.addr)
            .map(|d| d.name.clone())
            .unwrap_or_default()
    }

    /// Last seen RSSI
    #[zbus(property)]
    async fn rssi(&self) -> i16 {
        let st = self.state.lock().await;
        st.devices.get(&self.addr)
            .map(|d| d.rssi as i16)
            .unwrap_or(0)
    }

    /// Whether the device is currently connected
    #[zbus(property)]
    async fn connected(&self) -> bool {
        let st = self.state.lock().await;
        st.devices.get(&self.addr)
            .map(|d| d.connected)
            .unwrap_or(false)
    }

    /// Discovery level from advertisement
    #[zbus(property)]
    async fn discovery_level(&self) -> u8 {
        let st = self.state.lock().await;
        st.devices.get(&self.addr)
            .map(|d| d.discovery_level)
            .unwrap_or(0)
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
