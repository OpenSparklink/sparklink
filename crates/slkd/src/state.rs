use std::collections::{BTreeMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

use slk_native::Adapter;
use slk_protocol::SleAddr;

#[cfg(test)]
use crate::bonding::{BondingService, BondingStore};
use crate::config::DaemonConfig;
#[cfg(test)]
use crate::profile::ProfileRegistry;
#[cfg(test)]
use crate::profile_runtime::ProfileService;

pub(crate) const OBSERVATION_MAX_ENTRIES: usize = slk_contract::MAX_PEERS;
pub(crate) const OBSERVATION_MAX_BYTES: usize = 64 * 1024;
pub(crate) const OBSERVATION_TTL: Duration = Duration::from_secs(60);
pub(crate) const OBSERVATION_WORK_BUDGET: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PeerPublication {
    Pending,
    Published,
    Retiring,
}

pub(crate) type PeerKey = (u8, SleAddr);

/// Bounded observation/publication only; connections remain canonical Native facts.
#[derive(Debug, Clone)]
pub(crate) struct PeerEntry {
    pub(crate) advertisement_seen: bool,
    pub(crate) header: Vec<u8>,
    pub(crate) sequence: u64,
    pub(crate) kernel_boottime_ns: u64,
    pub(crate) lost: u64,
    pub(crate) publication: PeerPublication,
    pub(crate) observed_at: Instant,
    #[cfg(test)]
    pub name: String,
    pub rssi: i8,
    pub rssi_known: bool,
    #[cfg(test)]
    pub discovery_level: u8,
    #[cfg(test)]
    pub connected: bool,
    #[cfg(test)]
    pub connection_known: bool,
    #[cfg(test)]
    pub conn_handle: Option<u16>,
    pub object_path: String,
    pub adv_data: Vec<u8>,
    #[cfg(test)]
    pub service_uuids: Vec<u16>,
    #[cfg(test)]
    pub tx_power: Option<i8>,
}

impl PeerEntry {
    pub(crate) fn observation_bytes(&self) -> usize {
        self.adv_data.capacity() + self.header.capacity() + self.object_path.capacity()
    }
    pub(crate) fn observation_valid(&self) -> bool {
        self.publication == PeerPublication::Published
            && self.advertisement_seen
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
    pub(crate) discovery: Arc<crate::discovery::Coordinator>,
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
    /// Physical identity comes only from native_links. Each registration also
    /// owns its one SSAP resource owner before Native creation/publication.
    pub(crate) native_connection_objects: BTreeMap<u64, crate::connection_object::Registration>,
    pub(crate) retiring_connection_objects:
        BTreeMap<String, crate::connection_object::Registration>,
    pub config: DaemonConfig,
    pub(crate) peers: BTreeMap<PeerKey, PeerEntry>,
    pub(crate) observation_drops: u64,
    pub(crate) observation_publication_errors: u64,
    pub(crate) observation_retirement_errors: u64,
    observation_cursor: Option<PeerKey>,
    pub name: String,
    #[cfg(test)]
    pub bonding: BondingService,
    #[cfg(test)]
    pub profiles: ProfileService,
}

impl AdapterState {
    pub fn new(
        adapter: impl Into<Arc<Adapter>>,
        config: DaemonConfig,
        #[cfg(test)] bonding: BondingStore,
        #[cfg(test)] profiles: ProfileRegistry,
    ) -> Self {
        let adapter = adapter.into();
        let name = config.general.name.clone();
        Self {
            discovery: Arc::new(crate::discovery::Coordinator::default()),
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
            retiring_connection_objects: BTreeMap::new(),
            config,
            peers: BTreeMap::new(),
            observation_drops: 0,
            observation_publication_errors: 0,
            observation_retirement_errors: 0,
            observation_cursor: None,
            name,
            #[cfg(test)]
            bonding: BondingService::new(bonding),
            #[cfg(test)]
            profiles: ProfileService::new(profiles),
        }
    }

    fn peer_pinned(&self, key: &PeerKey) -> bool {
        #[cfg(test)]
        if self.controller.profile == 0 {
            return self
                .peers
                .get(key)
                .is_some_and(|p| p.connected && p.connection_known);
        }
        if self.native_links_known() {
            return self.native_links.as_ref().is_some_and(|t| {
                t.links[..t.count as usize]
                    .iter()
                    .any(|l| (l.address_type, l.address) == *key)
            });
        }
        // Unknown cannot authorize retirement of a previously observed link.
        self.native_connection_objects
            .values()
            .any(|v| (v.reference.address_type, v.reference.address) == *key)
    }
    fn peer_proposal(&mut self, key: PeerKey) -> Option<PeerEntry> {
        if key.0 > 1 || self.object_path.len() > 256 {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return None;
        }
        if let Some(v) = self.peers.get(&key) {
            if v.publication == PeerPublication::Retiring {
                self.observation_drops = self.observation_drops.saturating_add(1);
                return None;
            }
            return Some(v.clone());
        }
        Some(PeerEntry {
            publication: PeerPublication::Pending,
            advertisement_seen: false,
            observed_at: Instant::now(),
            object_path: crate::connection_object::peer_path(&self.object_path, key.0, key.1),
            header: Vec::new(),
            adv_data: Vec::new(),
            sequence: 0,
            kernel_boottime_ns: 0,
            lost: 0,
            rssi: 0,
            rssi_known: false,
            #[cfg(test)]
            name: String::new(),
            #[cfg(test)]
            discovery_level: 0,
            #[cfg(test)]
            connected: false,
            #[cfg(test)]
            connection_known: self.controller.profile == 0,
            #[cfg(test)]
            conn_handle: None,
            #[cfg(test)]
            service_uuids: Vec::new(),
            #[cfg(test)]
            tx_power: None,
        })
    }
    fn admit_peer(&mut self, key: PeerKey, entry: PeerEntry) -> bool {
        let old_bytes = self.peers.get(&key).map_or(0, PeerEntry::observation_bytes);
        if (!self.peers.contains_key(&key) && self.peers.len() >= OBSERVATION_MAX_ENTRIES)
            || self.observation_bytes() - old_bytes + entry.observation_bytes()
                > OBSERVATION_MAX_BYTES
        {
            self.observation_drops = self.observation_drops.saturating_add(1);
            let oldest = self
                .peers
                .iter()
                .filter(|(k, p)| {
                    **k != key && p.publication != PeerPublication::Retiring && !self.peer_pinned(k)
                })
                .min_by_key(|(_, p)| p.observed_at)
                .map(|(k, _)| *k);
            if let Some(k) = oldest {
                self.peers.get_mut(&k).unwrap().publication = PeerPublication::Retiring;
            }
            // Budget is retained until actual unpublication, including failures.
            return false;
        }
        let pending = entry.publication == PeerPublication::Pending;
        self.peers.insert(key, entry);
        pending
    }
    pub(crate) fn on_native_adv_report(
        &mut self,
        event: &slk_protocol::SleControllerEvent,
        report: &slk_protocol::Ws73DiscoveryReport<'_>,
    ) {
        let Some(key) = report.peer_identity() else {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return;
        };
        let Some(mut p) = self.peer_proposal(key) else {
            return;
        };
        if p.advertisement_seen && event.seq <= p.sequence {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return;
        }
        p.advertisement_seen = true;
        p.observed_at = Instant::now();
        p.rssi = report.rssi;
        p.rssi_known = report.rssi != 0x7f;
        p.header = report.header.to_vec();
        p.adv_data = report.data.to_vec();
        p.sequence = event.seq;
        p.kernel_boottime_ns = event.timestamp_ns;
        p.lost = event.lost;
        self.expire_observations(Instant::now());
        // Expiry may have begun retirement of this same peer. Do not revive it.
        if self
            .peers
            .get(&key)
            .is_some_and(|p| p.publication == PeerPublication::Retiring)
        {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return;
        }
        self.admit_peer(key, p);
    }
    /// Retained legacy advertisement/callback fixture. No Native wire decoder.
    #[cfg(test)]
    pub fn on_adv_report(
        &mut self,
        addr: SleAddr,
        rssi: i8,
        discovery_level: u8,
        name: String,
        adv_data: Vec<u8>,
    ) -> bool {
        if name.len() > 256 || adv_data.len() > 2048 {
            self.observation_drops = self.observation_drops.saturating_add(1);
            return false;
        }
        self.expire_observations(Instant::now());
        let key = (0, addr);
        let Some(mut p) = self.peer_proposal(key) else {
            return false;
        };
        p.advertisement_seen = true;
        p.observed_at = Instant::now();
        p.rssi = rssi;
        p.rssi_known = rssi != 0x7f;
        p.discovery_level = discovery_level;
        if !name.is_empty() {
            p.name = name.into_boxed_str().into_string();
        }
        if !adv_data.is_empty() || self.controller.profile != 0 {
            let (entries, _) = if self.controller.profile == 0 {
                slk_protocol::parse_adv_data(&adv_data)
            } else {
                (Vec::new(), Vec::new())
            };
            p.service_uuids = slk_protocol::collect_service_uuids16(&entries);
            p.tx_power = slk_protocol::find_tx_power(&entries);
            p.adv_data = adv_data.into_boxed_slice().into_vec();
        }
        self.admit_peer(key, p)
    }
    pub(crate) fn observation_bytes(&self) -> usize {
        self.peers.values().map(PeerEntry::observation_bytes).sum()
    }
    pub(crate) fn expire_observations(&mut self, now: Instant) {
        let expired = self
            .peers
            .iter()
            .filter(|(k, p)| {
                (!p.advertisement_seen
                    || now.saturating_duration_since(p.observed_at) >= OBSERVATION_TTL)
                    && !self.peer_pinned(k)
            })
            .map(|(k, _)| *k)
            .collect::<Vec<_>>();
        for k in expired {
            self.peers.get_mut(&k).unwrap().publication = PeerPublication::Retiring;
        }
    }
    /// Sole EventTask retries both connected-only and advertised Peer objects.
    /// No second publication map, worker or authority for connection state.
    pub(crate) fn observation_work(&mut self) -> Vec<(PeerKey, String, PeerPublication)> {
        if self.native_links_known() {
            let table = self.native_links.expect("known");
            for link in &table.links[..table.count as usize] {
                let key = (link.address_type, link.address);
                if !self.peers.contains_key(&key)
                    && let Some(p) = self.peer_proposal(key)
                {
                    self.admit_peer(key, p);
                }
            }
        }
        self.expire_observations(Instant::now());
        if !self.present {
            return Vec::new();
        }
        let mut work = self
            .peers
            .iter()
            .filter(|(_, p)| p.publication != PeerPublication::Published)
            .map(|(k, p)| (*k, p.object_path.clone(), p.publication))
            .collect::<Vec<_>>();
        work.sort_by_key(|(k, _, _)| (self.observation_cursor.is_some_and(|c| *k <= c), *k));
        work.truncate(OBSERVATION_WORK_BUDGET);
        work
    }
    pub(crate) fn observation_attempted(&mut self, key: PeerKey) {
        self.observation_cursor = Some(key);
    }
    /// Historical callback fixture; Native state comes from lifetime-scoped snapshots.
    #[cfg(test)]
    pub fn on_conn_state_changed(&mut self, handle: u16, state: u8, peer_addr: SleAddr) {
        let connected = state == slk_protocol::ConnState::Connected as u8;
        if !connected {
            // Disconnection: look up by handle first (DLI Disconnected may lack addr)
            if let Some(dev) = self
                .peers
                .values_mut()
                .find(|d| d.conn_handle == Some(handle))
            {
                dev.connected = false;
                dev.connection_known = true;
                dev.conn_handle = None;
                return;
            }
        }
        if let Some(dev) = self.peers.get_mut(&(0, peer_addr)) {
            dev.connected = connected;
            dev.connection_known = true;
            dev.conn_handle = if connected { Some(handle) } else { None };
        } else if connected {
            self.on_adv_report(peer_addr, 0, 0, String::new(), Vec::new());
            if let Some(dev) = self.peers.get_mut(&(0, peer_addr))
                && dev.publication != PeerPublication::Retiring
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
    pub(crate) fn peer_connection(&self, key: &PeerKey) -> (bool, bool) {
        #[cfg(test)]
        if self.controller.profile == 0 {
            return self
                .peers
                .get(key)
                .map(|p| (p.connection_known, p.connected && p.connection_known))
                .unwrap_or((false, false));
        }
        if !self.native_links_known() {
            return (false, false);
        }
        let t = self.native_links.as_ref().expect("known table");
        (
            true,
            t.links[..t.count as usize]
                .iter()
                .any(|l| (l.address_type, l.address) == *key),
        )
    }
    /// Replace the whole observation only if its identity and replay position
    /// cover the triggering event. Return newly discovered publication paths.
    pub fn apply_native_links(
        &mut self,
        table: slk_protocol::SleLinkSnapshot,
        minimum_seq: u64,
    ) -> Result<(), ()> {
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
        // Peer metadata is reconciled by the same bounded observation task.
        Ok(())
    }

    /// Reconcile bounded resource owners/publication from the canonical table.
    /// Unknown retains prior identities without declaring them connected.
    pub(crate) fn connection_publications(
        &mut self,
        context: &SharedState,
    ) -> crate::connection_object::Registrations {
        let mut retired = Vec::new();
        let mut refused = 0;
        if self.native_links_known() {
            let table = self.native_links.expect("known table");
            self.native_connection_objects.retain(|lifetime, entry| {
                let keep = table.links[..table.count as usize]
                    .iter()
                    .any(|link| &link.lifetime == lifetime);
                if !keep {
                    entry.owner.retire();
                    retired.push(entry.clone());
                }
                keep
            });
            self.retiring_connection_objects
                .extend(retired.into_iter().map(|v| (v.path.clone(), v)));
            for link in &table.links[..table.count as usize] {
                if !self.native_connection_objects.contains_key(&link.lifetime)
                    && self.native_connection_objects.len() + self.retiring_connection_objects.len()
                        >= table.links.len()
                {
                    // Unfinished retirement retains its budget; never evict
                    // work or create an untracked owner to admit a new link.
                    refused += 1;
                    continue;
                }
                self.native_connection_objects
                    .entry(link.lifetime)
                    .or_insert_with(|| crate::connection_object::Registration {
                        reference: *link,
                        path: crate::connection_object::path(&self.object_path, *link),
                        published: false,
                        owner: crate::connection_object::ConnectionOwner::new(
                            context,
                            self.controller.generation,
                            *link,
                            self.config.ssap.channel_security,
                        ),
                    });
            }
        }
        crate::connection_object::Registrations {
            pending: self
                .native_connection_objects
                .values()
                .filter(|entry| {
                    self.native_links_known() && !entry.published && !entry.owner.is_retiring()
                })
                .cloned()
                .collect(),
            retired: self.retiring_connection_objects.values().cloned().collect(),
            refused,
        }
    }

    pub(crate) fn connection_publication_pending(&self) -> bool {
        !self.retiring_connection_objects.is_empty()
            || (self.native_links_known()
                && self.native_links.as_ref().is_some_and(|table| {
                    table.links[..table.count as usize]
                        .iter()
                        .any(|link| !self.native_connection_objects.contains_key(&link.lifetime))
                }))
            || self
                .native_connection_objects
                .values()
                .any(|entry| !entry.published)
            || self
                .peers
                .values()
                .any(|p| p.publication != PeerPublication::Published)
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
pub type AdapterDirectory = crate::controller_events::Directory;

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
    #[cfg(test)]
    {
        let profiles = state.lock().await.profiles.clone();
        profiles.shutdown().await;
    }
    #[cfg(test)]
    bonding.shutdown().await;
}
