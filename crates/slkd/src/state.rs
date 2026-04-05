use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;

use libsparklink::Adapter;
use slk_protocol::{SleAddr, SleConnectParams, SleScanParams};

use crate::bonding::BondingStore;
use crate::config::DaemonConfig;
use crate::profile::ProfileRegistry;

/// Discovered device info maintained by the daemon
#[derive(Debug, Clone)]
pub struct DeviceEntry {
    pub addr: SleAddr,
    pub name: String,
    pub rssi: i8,
    pub discovery_level: u8,
    pub connected: bool,
    pub conn_handle: Option<u16>,
    pub object_path: String,
}

/// Shared adapter state accessible from D-Bus + event loop
pub struct AdapterState {
    pub adapter: Adapter,
    pub config: DaemonConfig,
    pub powered: bool,
    pub discovering: bool,
    pub devices: HashMap<SleAddr, DeviceEntry>,
    pub name: String,
    pub bonding: BondingStore,
    pub profiles: ProfileRegistry,
}

impl AdapterState {
    pub fn new(adapter: Adapter, config: DaemonConfig, bonding: BondingStore, profiles: ProfileRegistry) -> Self {
        let name = config.general.name.clone();
        Self {
            adapter,
            config,
            powered: true,
            discovering: false,
            devices: HashMap::new(),
            name,
            bonding,
            profiles,
        }
    }

    /// Start scanning with default parameters
    pub fn start_scan(&mut self) -> libsparklink::Result<()> {
        let params = SleScanParams {
            dev_index: 0,
            window_ms: 100,
            interval_ms: 200,
            filter_discovery_level: self.config.general.discovery_level,
            _reserved: [0; 9],
        };
        self.adapter.start_scan(&params)?;
        self.discovering = true;
        Ok(())
    }

    /// Stop scanning
    pub fn stop_scan(&mut self) -> libsparklink::Result<()> {
        self.adapter.stop_scan()?;
        self.discovering = false;
        Ok(())
    }

    /// Initiate connection to a peer by address
    pub fn connect_device(&mut self, addr: &SleAddr) -> libsparklink::Result<()> {
        let params = SleConnectParams {
            peer_addr: *addr,
            gt_role: 0,
            bandwidth: 0,
            mcs_index: 0,
            _pad: 0,
            timeout_10ms: 100,
            _reserved: [0; 4],
        };
        self.adapter.connect(&params)?;
        Ok(())
    }

    /// Disconnect a device by connection handle
    pub fn disconnect_device(&mut self, handle: u16) -> libsparklink::Result<()> {
        self.adapter.disconnect(handle)?;
        if let Some(dev) = self.devices.values_mut().find(|d| d.conn_handle == Some(handle)) {
            dev.connected = false;
            dev.conn_handle = None;
        }
        Ok(())
    }

    /// Record a discovered device from an advertisement report
    pub fn on_adv_report(
        &mut self,
        addr: SleAddr,
        rssi: i8,
        discovery_level: u8,
        name: String,
    ) -> bool {
        let is_new = !self.devices.contains_key(&addr);
        let object_path = format!(
            "/org/sparklink/slk0/dev_{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
            addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
        );
        let entry = self.devices.entry(addr).or_insert_with(|| DeviceEntry {
            addr,
            name: String::new(),
            rssi: 0,
            discovery_level: 0,
            connected: false,
            conn_handle: None,
            object_path,
        });
        entry.rssi = rssi;
        entry.discovery_level = discovery_level;
        if !name.is_empty() {
            entry.name = name;
        }
        is_new
    }

    /// Update connection state from kernel event
    pub fn on_conn_state_changed(&mut self, handle: u16, state: u8, peer_addr: SleAddr) {
        let connected = state == slk_protocol::ConnState::Connected as u8;
        if let Some(dev) = self.devices.get_mut(&peer_addr) {
            dev.connected = connected;
            dev.conn_handle = if connected { Some(handle) } else { None };
        } else if connected {
            let object_path = format!(
                "/org/sparklink/slk0/dev_{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
                peer_addr[0], peer_addr[1], peer_addr[2],
                peer_addr[3], peer_addr[4], peer_addr[5]
            );
            self.devices.insert(peer_addr, DeviceEntry {
                addr: peer_addr,
                name: String::new(),
                rssi: 0,
                discovery_level: 0,
                connected: true,
                conn_handle: Some(handle),
                object_path,
            });
        }
    }
}

/// Thread-safe shared handle to adapter state
pub type SharedState = Arc<Mutex<AdapterState>>;
