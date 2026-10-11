use std::collections::{BTreeMap, HashMap, VecDeque};
use std::sync::Arc;
use tokio::sync::Mutex;

use libsparklink::Adapter;
use slk_protocol::{SleAddr, SleConnectParams, SleScanParams};

use crate::bonding::{BondingService, BondingStore};
use crate::config::DaemonConfig;
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
use crate::profile::ProfileRegistry;
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
use crate::profile_runtime::ProfileService;

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
    pub adv_data: Vec<u8>,
    pub service_uuids: Vec<u16>,
    pub tx_power: Option<i8>,
}

/// Shared adapter state accessible from D-Bus + event loop
pub struct AdapterState {
    pub adapter: Arc<Adapter>,
    pub native_control: Option<Arc<Adapter>>,
    pub radio_advertising: u32,
    pub radio_scanning: u32,
    pub object_path: String,
    pub controller: slk_protocol::SleControllerSnapshot,
    pub present: bool,
    pub initialization_error: String,
    pub native_reports: VecDeque<NativeReport>,
    pub events_lost: u64,
    pub config: DaemonConfig,
    pub powered: bool,
    pub discovering: bool,
    pub devices: HashMap<SleAddr, DeviceEntry>,
    pub name: String,
    pub bonding: BondingService,
    #[cfg(any(test, feature = "experimental-legacy-profiles"))]
    pub profiles: ProfileService,
}

impl AdapterState {
    pub fn new(
        adapter: impl Into<Arc<Adapter>>,
        config: DaemonConfig,
        bonding: BondingStore,
        #[cfg(any(test, feature = "experimental-legacy-profiles"))] profiles: ProfileRegistry,
    ) -> Self {
        let adapter = adapter.into();
        let name = config.general.name.clone();
        Self {
            adapter,
            native_control: None,
            radio_advertising: 0,
            radio_scanning: 0,
            object_path: "/org/sparklink/slk0".into(),
            controller: slk_protocol::SleControllerSnapshot::default(),
            present: true,
            initialization_error: String::new(),
            native_reports: VecDeque::new(),
            events_lost: 0,
            config,
            powered: true,
            discovering: false,
            devices: HashMap::new(),
            name,
            bonding: BondingService::new(bonding),
            #[cfg(any(test, feature = "experimental-legacy-profiles"))]
            profiles: ProfileService::new(profiles),
        }
    }

    /// Start scanning with default parameters
    pub fn start_scan(&mut self) -> libsparklink::Result<()> {
        if self.controller.profile != 0 {
            return Err(libsparklink::Error::InvalidParam(
                "native scan requires an explicit WS73 policy; legacy scan is unsupported",
            ));
        }
        let params = SleScanParams {
            dev_index: self.controller.dev_index,
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
        if self.controller.profile != 0 {
            return Err(libsparklink::Error::InvalidParam(
                "legacy stop scan is unsupported on native WS73",
            ));
        }
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
        if let Some(dev) = self
            .devices
            .values_mut()
            .find(|d| d.conn_handle == Some(handle))
        {
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
        adv_data: Vec<u8>,
    ) -> bool {
        let is_new = !self.devices.contains_key(&addr);
        let object_path = format!(
            "{}/dev_{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
            self.object_path, addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
        );

        // Native discovery payloads are opaque here. Do not interpret them as
        // the legacy advertising codec or invent SSAP/name fields.
        let (entries, _) = if self.controller.profile == 0 {
            slk_protocol::parse_adv_data(&adv_data)
        } else {
            (Vec::new(), Vec::new())
        };
        let service_uuids = slk_protocol::collect_service_uuids16(&entries);
        let tx_power = slk_protocol::find_tx_power(&entries);

        let entry = self.devices.entry(addr).or_insert_with(|| DeviceEntry {
            addr,
            name: String::new(),
            rssi: 0,
            discovery_level: 0,
            connected: false,
            conn_handle: None,
            object_path,
            adv_data: Vec::new(),
            service_uuids: Vec::new(),
            tx_power: None,
        });
        entry.rssi = rssi;
        entry.discovery_level = discovery_level;
        if !name.is_empty() {
            entry.name = name;
        }
        if !adv_data.is_empty() || self.controller.profile != 0 {
            entry.adv_data = adv_data;
            entry.service_uuids = service_uuids;
            entry.tx_power = tx_power;
        }
        is_new
    }

    /// Update connection state from kernel event
    pub fn on_conn_state_changed(&mut self, handle: u16, state: u8, peer_addr: SleAddr) {
        let connected = state == slk_protocol::ConnState::Connected as u8;
        if !connected {
            // Disconnection: look up by handle first (DLI Disconnected may lack addr)
            if let Some(dev) = self
                .devices
                .values_mut()
                .find(|d| d.conn_handle == Some(handle))
            {
                dev.connected = false;
                dev.conn_handle = None;
                return;
            }
        }
        if let Some(dev) = self.devices.get_mut(&peer_addr) {
            dev.connected = connected;
            dev.conn_handle = if connected { Some(handle) } else { None };
        } else if connected {
            let object_path = format!(
                "{}/dev_{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
                self.object_path,
                peer_addr[0],
                peer_addr[1],
                peer_addr[2],
                peer_addr[3],
                peer_addr[4],
                peer_addr[5]
            );
            self.devices.insert(
                peer_addr,
                DeviceEntry {
                    addr: peer_addr,
                    name: String::new(),
                    rssi: 0,
                    discovery_level: 0,
                    connected: true,
                    conn_handle: Some(handle),
                    object_path,
                    adv_data: Vec::new(),
                    service_uuids: Vec::new(),
                    tx_power: None,
                },
            );
        }
    }

    /// Query connection info from the kernel for a given handle.
    pub fn conn_info(&self, handle: u16) -> libsparklink::Result<slk_protocol::SleConnInfo> {
        self.adapter.conn_info(handle)
    }
}

/// Thread-safe shared handle to adapter state
pub type SharedState = Arc<Mutex<AdapterState>>;

/// Exact native report evidence retained independently per registration.
#[derive(Debug, Clone)]
pub struct NativeReport {
    pub sequence: u64,
    pub generation: u64,
    pub received_at_ms: u64,
    pub kernel_boottime_ns: u64,
    pub address: SleAddr,
    pub rssi: i8,
    pub header: Vec<u8>,
    pub data: Vec<u8>,
    pub lost: u64,
}
/// Live paths include the generation so a selected stale D-Bus path cannot
/// silently start addressing a replacement registration.
#[derive(Clone)]
pub struct AdapterRegistration {
    pub adapter: Arc<Adapter>,
    pub generation: u64,
}
pub type AdapterDirectory = Arc<Mutex<BTreeMap<String, AdapterRegistration>>>;

/// Drain experimental callbacks and Bond I/O without holding adapter state.
pub async fn shutdown_services(state: &SharedState) {
    let bonding = state.lock().await.bonding.clone();
    #[cfg(any(test, feature = "experimental-legacy-profiles"))]
    {
        let profiles = state.lock().await.profiles.clone();
        tokio::join!(bonding.shutdown(), profiles.shutdown());
    }
    #[cfg(not(any(test, feature = "experimental-legacy-profiles")))]
    bonding.shutdown().await;
}
