use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
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
    pub rssi_known: bool,
    pub discovery_level: u8,
    pub connected: bool,
    pub connection_known: bool,
    pub conn_handle: Option<u16>,
    pub object_path: String,
    pub adv_data: Vec<u8>,
    pub service_uuids: Vec<u16>,
    pub tx_power: Option<i8>,
}

/// One shared credential and admission gate for RPCs, bootstrap and removal.
pub(crate) struct NativeManagement {
    pub token: Option<u64>,
    pub accepting: bool,
    pub connection_id: u64,
    /// Correlation only, never cached radio success. A business admission or
    /// lease withdrawal invalidates its domain before touching the kernel.
    pub initialized_off: [Option<InitializationOff>; 2],
}
#[derive(Clone, Copy, Debug)]
pub(crate) struct InitializationOff {
    pub generation: u64,
    pub token: u64,
    pub request_id: u64,
    pub operation: u32,
}
pub(crate) type NativeLease = Arc<Mutex<NativeManagement>>;

/// Shared adapter state accessible from D-Bus + event loop.
pub struct AdapterState {
    pub adapter: Arc<Adapter>,
    pub native_control: Option<Arc<Adapter>>,
    pub(crate) native_lease: Option<NativeLease>,
    pub(crate) native_discovery_policy: Option<libsparklink::Ws73DiscoveryPolicy>,
    pub radio_advertising: u32,
    pub radio_scanning: u32,
    pub object_path: String,
    pub controller: slk_protocol::SleControllerSnapshot,
    pub present: bool,
    pub initialization_error: String,
    pub native_reports: VecDeque<NativeReport>,
    pub events_lost: u64,
    pub native_links: Option<slk_protocol::SleLinkSnapshot>,
    pub native_link_barrier: u64,
    pub native_link_revision: u64,
    /// D-Bus publication metadata only. Physical state remains native_links.
    pub(crate) native_connection_objects: BTreeMap<u64, crate::connection_object::Registration>,
    pub(crate) retiring_connection_objects: BTreeSet<String>,
    pub(crate) native_peer_objects:
        BTreeMap<(u8, SleAddr), crate::connection_object::PeerRegistration>,
    pub(crate) retiring_peer_objects: BTreeSet<String>,
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
            native_lease: None,
            native_discovery_policy: None,
            radio_advertising: 0,
            radio_scanning: 0,
            object_path: "/org/sparklink/slk0".into(),
            controller: slk_protocol::SleControllerSnapshot::default(),
            present: true,
            initialization_error: String::new(),
            native_reports: VecDeque::new(),
            events_lost: 0,
            native_links: None,
            native_link_barrier: 0,
            native_link_revision: 0,
            native_connection_objects: BTreeMap::new(),
            retiring_connection_objects: BTreeSet::new(),
            native_peer_objects: BTreeMap::new(),
            retiring_peer_objects: BTreeSet::new(),
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
            rssi_known: true,
            discovery_level: 0,
            connected: false,
            connection_known: self.controller.profile == 0,
            conn_handle: None,
            object_path,
            adv_data: Vec::new(),
            service_uuids: Vec::new(),
            tx_power: None,
        });
        entry.rssi = rssi;
        entry.rssi_known = true;
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
                dev.connection_known = true;
                dev.conn_handle = None;
                return;
            }
        }
        if let Some(dev) = self.devices.get_mut(&peer_addr) {
            dev.connected = connected;
            dev.connection_known = true;
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
                    rssi_known: false,
                    discovery_level: 0,
                    connected: true,
                    connection_known: true,
                    conn_handle: Some(handle),
                    object_path,
                    adv_data: Vec::new(),
                    service_uuids: Vec::new(),
                    tx_power: None,
                },
            );
        }
    }

    /// Native physical state is an exact canonical snapshot, never an event delta
    /// or an author result. The replay barrier survives failed refreshes.
    pub fn invalidate_native_connections(&mut self) {
        self.native_links = None;
    }
    pub fn native_links_known(&self) -> bool {
        self.present
            && self
                .native_links
                .as_ref()
                .is_some_and(|table| table.flags == slk_protocol::LINK_SNAPSHOT_KNOWN)
    }
    /// Address-only discovery objects are aliases, not a typed connection
    /// identity. Multiple current lifetimes/types at that address are Unknown.
    pub fn device_connection(&self, address: &SleAddr) -> (bool, bool) {
        if self.controller.profile == 0 {
            return self
                .devices
                .get(address)
                .map(|d| (d.connection_known, d.connected && d.connection_known))
                .unwrap_or((false, false));
        }
        if !self.native_links_known() {
            return (false, false);
        }
        let table = self.native_links.as_ref().expect("known table");
        let count = table.links[..table.count as usize]
            .iter()
            .filter(|link| &link.address == address)
            .count();
        if count > 1 {
            (false, false)
        } else {
            (true, count == 1)
        }
    }
    /// Replace the whole observation only if its identity and replay position
    /// cover the triggering event. Return newly discovered publication paths.
    pub fn apply_native_links(
        &mut self,
        table: slk_protocol::SleLinkSnapshot,
        minimum_seq: u64,
    ) -> Result<Vec<(SleAddr, String)>, ()> {
        if !self.present
            || self.controller.profile != 1
            || !table.valid_for(self.controller.generation)
            || table.profile != self.controller.profile
            || table.dev_index != self.controller.dev_index
            || table.event_seq < minimum_seq.max(self.native_link_barrier)
            || table.revision < self.native_link_revision
            || table.links[..table.count.min(16) as usize]
                .iter()
                .any(|link| {
                    self.native_connection_objects
                        .get(&link.lifetime)
                        .is_some_and(|old| old.reference != *link)
                })
        {
            self.invalidate_native_connections();
            return Err(());
        }
        self.native_link_barrier = table.event_seq;
        self.native_link_revision = table.revision;
        self.native_links = Some(table);
        let mut new = Vec::new();
        if table.flags == slk_protocol::LINK_SNAPSHOT_KNOWN {
            for link in &table.links[..table.count as usize] {
                if !self.devices.contains_key(&link.address)
                    && self.on_adv_report(link.address, 0, 0, String::new(), Vec::new())
                {
                    let device = self.devices.get_mut(&link.address).expect("new peer");
                    device.rssi_known = false;
                    new.push((link.address, device.object_path.clone()));
                }
            }
        }
        Ok(new)
    }

    /// Reconcile bounded publication metadata from the canonical table.
    /// Unknown retains prior identities without declaring them connected.
    pub(crate) fn connection_publications(
        &mut self,
    ) -> (Vec<crate::connection_object::Registration>, Vec<String>) {
        let mut retired = Vec::new();
        if self.native_links_known() {
            let table = self.native_links.expect("known table");
            self.native_connection_objects.retain(|lifetime, entry| {
                let keep = table.links[..table.count as usize]
                    .iter()
                    .any(|link| &link.lifetime == lifetime);
                if !keep {
                    retired.push(entry.path.clone());
                }
                keep
            });
            for link in &table.links[..table.count as usize] {
                self.native_connection_objects
                    .entry(link.lifetime)
                    .or_insert_with(|| crate::connection_object::Registration {
                        reference: *link,
                        path: crate::connection_object::path(&self.object_path, *link),
                        published: false,
                    });
            }
        }
        self.retiring_connection_objects.extend(retired);
        (
            self.native_connection_objects
                .values()
                .filter(|entry| !entry.published)
                .cloned()
                .collect(),
            self.retiring_connection_objects.iter().cloned().collect(),
        )
    }

    pub(crate) fn connection_publication_pending(&self) -> bool {
        !self.retiring_connection_objects.is_empty()
            || self
                .native_connection_objects
                .values()
                .any(|entry| !entry.published)
            || !self.retiring_peer_objects.is_empty()
            || self
                .native_peer_objects
                .values()
                .any(|entry| !entry.published)
    }
    pub(crate) fn peer_publications(
        &mut self,
    ) -> (Vec<crate::connection_object::PeerRegistration>, Vec<String>) {
        if self.native_links_known() {
            let table = self.native_links.expect("known table");
            self.native_peer_objects.retain(|key, entry| {
                let keep = table.links[..table.count as usize]
                    .iter()
                    .any(|link| (link.address_type, link.address) == *key);
                if !keep {
                    self.retiring_peer_objects.insert(entry.path.clone());
                }
                keep
            });
            for link in &table.links[..table.count as usize] {
                self.native_peer_objects
                    .entry((link.address_type, link.address))
                    .or_insert_with(|| crate::connection_object::PeerRegistration {
                        address_type: link.address_type,
                        address: link.address,
                        path: crate::connection_object::peer_path(
                            &self.object_path,
                            link.address_type,
                            link.address,
                        ),
                        published: false,
                    });
            }
        }
        (
            self.native_peer_objects
                .values()
                .filter(|entry| !entry.published)
                .cloned()
                .collect(),
            self.retiring_peer_objects.iter().cloned().collect(),
        )
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
