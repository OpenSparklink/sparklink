use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

use slk_native::Adapter;
use slk_protocol::{SleAddr, SleConnectParams, SleScanParams};

#[cfg(test)]
use crate::bonding::{BondingService, BondingStore};
use crate::config::DaemonConfig;
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
use crate::profile::ProfileRegistry;
#[cfg(any(test, feature = "experimental-legacy-profiles"))]
use crate::profile_runtime::ProfileService;

pub(crate) const OBSERVATION_MAX_ENTRIES: usize = 128;
pub(crate) const OBSERVATION_MAX_BYTES: usize = 64 * 1024;
pub(crate) const OBSERVATION_TTL: Duration = Duration::from_secs(60);
pub(crate) const OBSERVATION_WORK_BUDGET: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DevicePublication {
    Pending,
    Published,
    Retiring,
}

/// Discovered device info maintained by the daemon
#[derive(Debug, Clone)]
pub struct DeviceEntry {
    pub(crate) publication: DevicePublication,
    pub(crate) observed_at: Instant,
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

impl DeviceEntry {
    pub(crate) fn observation_bytes(&self) -> usize {
        self.name.capacity()
            + self.adv_data.capacity()
            + self.service_uuids.capacity() * std::mem::size_of::<u16>()
            + self.object_path.capacity()
    }
    pub(crate) fn observation_valid(&self) -> bool {
        self.publication == DevicePublication::Published
            && self.rssi_known
            && self.observed_at.elapsed() < OBSERVATION_TTL
    }
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
    pub(crate) security_policy: crate::security_policy::Shared,
    pub(crate) ssap_database: Arc<std::sync::Mutex<crate::ssap_database::Database>>,
    pub(crate) ssap_owner_slots: Arc<tokio::sync::Semaphore>,
    pub adapter: Arc<Adapter>,
    pub native_control: Option<Arc<Adapter>>,
    pub(crate) native_lease: Option<NativeLease>,
    pub(crate) native_discovery_policy: Option<slk_native::Ws73DiscoveryPolicy>,
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
    pub discovering: bool,
    pub devices: HashMap<SleAddr, DeviceEntry>,
    pub(crate) observation_drops: u64,
    pub(crate) observation_publication_errors: u64,
    pub(crate) observation_retirement_errors: u64,
    observation_cursor: Option<SleAddr>,
    pub name: String,
    #[cfg(test)]
    pub bonding: BondingService,
    #[cfg(any(test, feature = "experimental-legacy-profiles"))]
    pub profiles: ProfileService,
}

impl AdapterState {
    pub fn new(
        adapter: impl Into<Arc<Adapter>>,
        config: DaemonConfig,
        #[cfg(test)] bonding: BondingStore,
        #[cfg(any(test, feature = "experimental-legacy-profiles"))] profiles: ProfileRegistry,
    ) -> Self {
        let adapter = adapter.into();
        let name = config.general.name.clone();
        Self {
            security_policy: Arc::new(Mutex::new(crate::security_policy::Registry::default())),
            adapter,
            ssap_database: Arc::new(std::sync::Mutex::new(
                crate::ssap_database::Database::default(),
            )),
            ssap_owner_slots: Arc::new(tokio::sync::Semaphore::new(16)),
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
            discovering: false,
            devices: HashMap::new(),
            observation_drops: 0,
            observation_publication_errors: 0,
            observation_retirement_errors: 0,
            observation_cursor: None,
            name,
            #[cfg(test)]
            bonding: BondingService::new(bonding),
            #[cfg(any(test, feature = "experimental-legacy-profiles"))]
            profiles: ProfileService::new(profiles),
        }
    }

    /// Start scanning with default parameters
    pub fn start_scan(&mut self) -> slk_native::Result<()> {
        if self.controller.profile != 0 {
            return Err(slk_native::Error::InvalidParam(
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
    pub fn stop_scan(&mut self) -> slk_native::Result<()> {
        if self.controller.profile != 0 {
            return Err(slk_native::Error::InvalidParam(
                "legacy stop scan is unsupported on native WS73",
            ));
        }
        self.adapter.stop_scan()?;
        self.discovering = false;
        Ok(())
    }

    /// Initiate connection to a peer by address
    pub fn connect_device(&mut self, addr: &SleAddr) -> slk_native::Result<()> {
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
    pub fn disconnect_device(&mut self, handle: u16) -> slk_native::Result<()> {
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
        if name.len() > 256 || adv_data.len() > 2048 || self.object_path.len() > 256 {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return false;
        }
        let now = Instant::now();
        self.expire_observations(now);
        if self
            .devices
            .get(&addr)
            .is_some_and(|d| d.publication == DevicePublication::Retiring)
        {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return false;
        }
        // Build one bounded proposal before mutating any existing observation.
        // Tight buffers prevent spare caller capacity bypassing the byte budget.
        let name = name.into_boxed_str().into_string();
        let adv_data = adv_data.into_boxed_slice().into_vec();
        let object_path = format!(
            "{}/dev_{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
            self.object_path, addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
        );
        let mut entry = self.devices.get(&addr).cloned().unwrap_or(DeviceEntry {
            publication: DevicePublication::Pending,
            observed_at: now,
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
        entry.observed_at = now;
        if !name.is_empty() {
            entry.name = name;
        }
        if !adv_data.is_empty() || self.controller.profile != 0 {
            // Native payloads remain opaque; this is not an SSAP/wire decoder.
            let (entries, _) = if self.controller.profile == 0 {
                slk_protocol::parse_adv_data(&adv_data)
            } else {
                (Vec::new(), Vec::new())
            };
            entry.service_uuids = slk_protocol::collect_service_uuids16(&entries)
                .into_boxed_slice()
                .into_vec();
            entry.tx_power = slk_protocol::find_tx_power(&entries);
            entry.adv_data = adv_data;
        }
        let old_bytes = self
            .devices
            .get(&addr)
            .map_or(0, DeviceEntry::observation_bytes);
        if (!self.devices.contains_key(&addr) && self.devices.len() >= OBSERVATION_MAX_ENTRIES)
            || self.observation_bytes() - old_bytes + entry.observation_bytes()
                > OBSERVATION_MAX_BYTES
        {
            self.observation_drops = self.observation_drops.saturating_add(1);
            // Keep the old entry until actual unpublication. Never allocate a
            // replacement while its D-Bus object still consumes the old slot.
            let oldest = self
                .devices
                .iter()
                .filter(|(a, d)| {
                    **a != addr
                        && d.publication != DevicePublication::Retiring
                        && !self.device_connection(a).1
                })
                .min_by_key(|(_, d)| d.observed_at)
                .map(|(a, _)| *a);
            if let Some(oldest) = oldest {
                self.devices.get_mut(&oldest).unwrap().publication = DevicePublication::Retiring;
            }
            return false;
        }
        let pending = entry.publication == DevicePublication::Pending;
        self.devices.insert(addr, entry);
        pending
    }

    pub(crate) fn observation_bytes(&self) -> usize {
        self.devices
            .values()
            .map(DeviceEntry::observation_bytes)
            .sum()
    }
    pub(crate) fn expire_observations(&mut self, now: Instant) {
        let expired = self
            .devices
            .iter()
            .filter(|(address, d)| {
                now.saturating_duration_since(d.observed_at) >= OBSERVATION_TTL
                    && !self.device_connection(address).1
            })
            .map(|(address, _)| *address)
            .collect::<Vec<_>>();
        for address in expired {
            self.devices.get_mut(&address).unwrap().publication = DevicePublication::Retiring;
        }
    }
    /// The sole registration EventTask performs this work. Failed work remains
    /// charged to the same bounded slot; a rotating cursor prevents starvation.
    pub(crate) fn observation_work(&mut self) -> Vec<(SleAddr, String, DevicePublication)> {
        self.expire_observations(Instant::now());
        if !self.present {
            return Vec::new();
        }
        let mut work = self
            .devices
            .iter()
            .filter(|(_, d)| d.publication != DevicePublication::Published)
            .map(|(a, d)| (*a, d.object_path.clone(), d.publication))
            .collect::<Vec<_>>();
        work.sort_by_key(|(a, _, _)| {
            (
                self.observation_cursor.is_some_and(|cursor| *a <= cursor),
                *a,
            )
        });
        work.truncate(OBSERVATION_WORK_BUDGET);
        work
    }
    pub(crate) fn observation_attempted(&mut self, address: SleAddr) {
        self.observation_cursor = Some(address);
    }

    /// Historical callback fixture; Native state comes from lifetime-scoped snapshots.
    #[cfg(any(test, feature = "experimental-legacy-profiles"))]
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
            self.on_adv_report(peer_addr, 0, 0, String::new(), Vec::new());
            if let Some(dev) = self.devices.get_mut(&peer_addr)
                && dev.publication != DevicePublication::Retiring
            {
                dev.connected = true;
                dev.connection_known = true;
                dev.conn_handle = Some(handle);
                dev.rssi_known = false;
            }
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
    pub fn conn_info(&self, handle: u16) -> slk_native::Result<slk_protocol::SleConnInfo> {
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

/// Published registration topology only. State/availability comes from Core
/// on every read; this unselected fd has no management lease or radio resources.
#[derive(Clone)]
pub struct RegistrationObserver {
    pub adapter: Arc<Adapter>,
    pub index: u16,
    pub generation: u64,
}
pub type RegistrationDirectory = Arc<Mutex<BTreeMap<String, RegistrationObserver>>>;

/// Drain production owners and experimental callbacks without holding adapter state.
/// Historical metadata I/O exists only in unit-test builds.
pub async fn shutdown_services(state: &SharedState) {
    crate::security_policy::retire(state).await;
    let database = state.lock().await.ssap_database.clone();
    let owners = match database.lock() {
        Ok(mut database) => database.retire(),
        Err(_) => {
            tracing::error!("SSAP database poisoned at retirement; clean retirement unverified");
            Vec::new()
        }
    };
    for owner in owners {
        owner.shutdown().await;
    }
    #[cfg(test)]
    let bonding = state.lock().await.bonding.clone();
    #[cfg(any(test, feature = "experimental-legacy-profiles"))]
    {
        let profiles = state.lock().await.profiles.clone();
        profiles.shutdown().await;
    }
    #[cfg(test)]
    bonding.shutdown().await;
}
