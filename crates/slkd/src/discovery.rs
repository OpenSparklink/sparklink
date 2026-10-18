//! One scanner policy owner per controller. No Host, codec or protocol credit.
//! The Native management guard serializes actual submissions and handoff;
//! this registry owns only caller leases, filtering and bounded observations.
use crate::state::{NativeLease, SharedState};
#[path = "discovery_fence.rs"]
mod fence;
use slk_channel::deadline::Deadline;
use slk_contract::discovery as wire;
use std::{
    collections::{BTreeMap, VecDeque},
    sync::{
        Arc, Mutex, Weak,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
use tokio::sync::{Notify, OwnedSemaphorePermit, Semaphore, oneshot, watch};
use zbus::export::ordered_stream::OrderedStreamExt;
#[cfg(test)]
#[path = "discovery_tests.rs"]
mod tests;

fn failed(e: impl std::fmt::Display) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(e.to_string())
}
fn absent() -> zbus::fdo::Error {
    zbus::fdo::Error::UnknownObject("discovery session absent, expired or revoked".into())
}
fn busy() -> zbus::fdo::Error {
    failed("physical scanner policy busy; no controller ownership granted")
}
pub(crate) fn deadline(value: slk_contract::Deadline) -> zbus::fdo::Result<Deadline> {
    Deadline::from_stamp(slk_contract::deadline_stamp(value))
        .and_then(|d| d.capped(Duration::from_secs(5)))
        .map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Idle,
    Manager,
    Starting,
    Running,
    Stopping,
    Fault,
}

struct Entry {
    owner: Arc<Owner>,
    prefix: Vec<u8>,
    minimum_rssi: i16,
    expires: Instant,
    opening: Instant,
    queue: VecDeque<wire::Report>,
    dropped: u64,
    kernel_lost: u64,
    reading: bool,
    after_sequence: u64,
}
struct Registry {
    fence: fence::Fence,
    next: u64,
    phase: Phase,
    scope: Option<(u64, u64)>, // generation, original Native credential; never public
    stop: Option<(u64, u64, u64)>, // manager generation, credential, request id
    cleanup: Option<Instant>,
    settled: Option<(u64, bool)>,
    entries: BTreeMap<u64, Entry>,
}
impl Default for Registry {
    fn default() -> Self {
        Self {
            fence: fence::Fence::default(),
            next: 0,
            phase: Phase::Idle,
            scope: None,
            stop: None,
            cleanup: None,
            settled: None,
            entries: BTreeMap::new(),
        }
    }
}
impl Registry {
    fn advance(&mut self) -> zbus::fdo::Result<()> {
        if self.fence.advance().is_err() {
            self.phase = Phase::Fault;
            self.entries.clear();
            return Err(failed("scanner epoch retired or exhausted"));
        }
        Ok(())
    }
    fn remove(&mut self, id: u64, until: Instant) {
        if self.entries.remove(&id).is_none() {
            return;
        }
        if self.entries.is_empty() && matches!(self.phase, Phase::Starting | Phase::Running) {
            self.cleanup = Some(self.cleanup.map_or(until, |old| old.min(until)));
            if self.phase == Phase::Running {
                self.phase = Phase::Stopping;
            }
        }
    }
    fn expire(&mut self, now: Instant) {
        let ids = self
            .entries
            .iter()
            .filter_map(|(id, e)| {
                (!e.owner.current() || e.expires <= now).then_some((*id, e.expires.min(now)))
            })
            .collect::<Vec<_>>();
        for (id, at) in ids {
            self.remove(id, at + Duration::from_secs(5));
        }
    }
    fn invalidate(&mut self, retired: bool) {
        self.entries.clear();
        self.phase = Phase::Fault;
        self.scope = None;
        self.stop = None;
        self.cleanup = None;
        let _ = self.advance();
        if retired {
            self.fence.retire();
        }
    }
}

pub(crate) struct Coordinator {
    store: Mutex<Registry>,
    changed: Notify,
    slots: Arc<Semaphore>,
    reads: Arc<Semaphore>,
    callers: Mutex<BTreeMap<String, usize>>,
}
impl Default for Coordinator {
    fn default() -> Self {
        Self {
            store: Mutex::new(Registry::default()),
            changed: Notify::new(),
            slots: Arc::new(Semaphore::new(wire::MAX_SESSIONS)),
            reads: Arc::new(Semaphore::new(wire::MAX_SESSIONS)),
            callers: Mutex::new(BTreeMap::new()),
        }
    }
}
impl Coordinator {
    fn owner_slot(self: &Arc<Self>, name: &str) -> zbus::fdo::Result<CallerSlot> {
        let mut callers = self.callers.lock().expect("scanner caller budget");
        if callers.get(name).copied().unwrap_or(0) >= wire::MAX_PER_CALLER {
            return Err(busy());
        }
        let slot = self.slots.clone().try_acquire_owned().map_err(|_| busy())?;
        *callers.entry(name.to_owned()).or_default() += 1;
        Ok(CallerSlot {
            service: Arc::downgrade(self),
            name: name.to_owned(),
            _global: slot,
        })
    }
    /// Called with the actual Native management guard, before command admission.
    pub(crate) fn manager(
        &self,
        generation: u64,
        token: u64,
        id: u64,
        operation: u32,
    ) -> zbus::fdo::Result<()> {
        if !matches!(operation, 3 | 4 | 6) {
            return Ok(());
        }
        let mut st = self.store.lock().expect("scanner registry");
        if st.fence.retired() {
            return Err(absent());
        }
        if operation != 4 && matches!(st.phase, Phase::Starting | Phase::Running | Phase::Stopping)
        {
            return Err(busy());
        }
        // Only an explicit manager STOP may supersede application sessions.
        // Last application release never takes this path or revokes connections.
        st.advance()?;
        st.entries.clear();
        st.phase = Phase::Manager;
        st.scope = Some((generation, token));
        st.cleanup = None;
        st.stop = (operation == 4).then_some((generation, token, id));
        self.changed.notify_waiters();
        Ok(())
    }
    pub(crate) fn observe_manager(&self, token: u64, result: slk_protocol::SleDiscoveryResult) {
        let mut st = self.store.lock().expect("scanner registry");
        if st.phase == Phase::Manager
            && st.stop == Some((result.generation, token, result.request_id))
            && valid_receipt(&result, result.generation, result.request_id, false)
        {
            st.phase = Phase::Idle;
            st.stop = None;
            st.scope = None;
            self.changed.notify_waiters();
        }
    }
    pub(crate) fn invalidate(&self, retired: bool) {
        self.store
            .lock()
            .expect("scanner registry")
            .invalidate(retired);
        if retired {
            self.slots.close();
        }
        self.changed.notify_waiters();
    }
    /// Only after actual Managed relinquish/drain and reacquisition succeeded.
    pub(crate) fn credential_replaced(&self) {
        let mut st = self.store.lock().expect("scanner registry");
        if !st.fence.retired() {
            st.phase = Phase::Idle;
        }
        self.changed.notify_waiters();
    }
    pub(crate) fn report(
        &self,
        event: &slk_protocol::SleControllerEvent,
        report: &slk_protocol::Ws73DiscoveryReport<'_>,
    ) {
        let Some((address_type, address)) = report.peer_identity() else {
            return;
        };
        if report.header.len() > wire::MAX_HEADER || report.data.len() > wire::MAX_DATA {
            return;
        }
        let mut st = self.store.lock().expect("scanner registry");
        st.expire(Instant::now());
        if st.fence.retired()
            || st.phase != Phase::Running
            || st.scope.is_none_or(|s| s.0 != event.generation)
        {
            return;
        }
        for e in st.entries.values_mut() {
            if event.seq <= e.after_sequence {
                continue;
            }
            e.after_sequence = event.seq;
            if !report.data.starts_with(&e.prefix)
                || e.minimum_rssi != -128
                    && (report.rssi == 0x7f || i16::from(report.rssi) < e.minimum_rssi)
            {
                continue;
            }
            if e.queue.len() == wire::CAPACITY {
                e.queue.pop_front();
                e.dropped = e.dropped.saturating_add(1);
            }
            e.queue.push_back(wire::Report {
                sequence: event.seq,
                kernel_boottime_ns: event.timestamp_ns,
                address_type,
                address: address.to_vec(),
                rssi: i16::from(report.rssi),
                rssi_known: report.rssi != 0x7f,
                header: report.header.to_vec(),
                data: report.data.to_vec(),
            });
        }
        self.changed.notify_waiters();
    }
    pub(crate) fn lost(&self, count: u64) {
        if count == 0 {
            return;
        }
        for e in self
            .store
            .lock()
            .expect("scanner registry")
            .entries
            .values_mut()
        {
            e.kernel_lost = e.kernel_lost.saturating_add(count);
        }
        self.changed.notify_waiters();
    }
}

/// A watch is not a physical worker. Weak references prevent a bus/object cycle.
struct Owner {
    name: String,
    active: AtomicBool,
    task: Mutex<Option<tokio::task::JoinHandle<()>>>,
    _slot: Arc<CallerSlot>,
}
struct CallerSlot {
    service: Weak<Coordinator>,
    name: String,
    _global: OwnedSemaphorePermit,
}
impl Drop for CallerSlot {
    fn drop(&mut self) {
        if let Some(service) = self.service.upgrade() {
            let mut callers = service.callers.lock().expect("scanner caller budget");
            if let Some(count) = callers.get_mut(&self.name) {
                *count -= 1;
                if *count == 0 {
                    callers.remove(&self.name);
                }
            }
        }
    }
}
struct OwnerExit {
    owner: Weak<Owner>,
    service: Weak<Coordinator>,
    _slot: Arc<CallerSlot>,
}
impl Drop for OwnerExit {
    fn drop(&mut self) {
        if let Some(owner) = self.owner.upgrade() {
            owner.active.store(false, Ordering::Release);
        }
        if let Some(service) = self.service.upgrade() {
            service.changed.notify_waiters();
        }
    }
}
impl Owner {
    fn current(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }
    async fn pin(
        bus: zbus::Connection,
        name: String,
        service: &Arc<Coordinator>,
        slot: CallerSlot,
        until: Instant,
    ) -> zbus::fdo::Result<Arc<Self>> {
        let owner = Arc::new(Self {
            name: name.clone(),
            active: AtomicBool::new(true),
            task: Mutex::new(None),
            _slot: Arc::new(slot),
        });
        let weak = Arc::downgrade(&owner);
        let registry = Arc::downgrade(service);
        let task_slot = owner._slot.clone();
        let (send, ready) = oneshot::channel();
        let task = tokio::spawn(async move {
            let _exit = OwnerExit {
                owner: weak.clone(),
                service: registry.clone(),
                _slot: task_slot,
            };
            let install = async {
                let bus = zbus::fdo::DBusProxy::new(&bus).await.map_err(failed)?;
                let changes = bus
                    .receive_name_owner_changed_with_args(&[(0, &name), (2, "")])
                    .await
                    .map_err(failed)?;
                if !bus
                    .name_has_owner(name.as_str().try_into().map_err(failed)?)
                    .await
                    .map_err(failed)?
                {
                    return Err(absent());
                }
                Ok(changes)
            };
            match tokio::time::timeout_at(until.into(), install).await {
                Ok(Ok(mut changes)) => {
                    if send.send(Ok(())).is_err() {
                        return;
                    }
                    let _ = changes.next().await;
                    if let Some(owner) = weak.upgrade() {
                        owner.active.store(false, Ordering::Release);
                    }
                    if let Some(registry) = registry.upgrade() {
                        registry.changed.notify_waiters();
                    }
                }
                Ok(Err(error)) => {
                    let _ = send.send(Err(error));
                }
                Err(_) => {
                    let _ = send.send(Err(failed(
                        "original discovery deadline expired during owner subscription",
                    )));
                }
            }
        });
        *owner.task.lock().expect("discovery owner task") = Some(task);
        ready.await.map_err(failed)??;
        if !owner.current() {
            return Err(absent());
        }
        Ok(owner)
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        if let Ok(task) = self.task.get_mut()
            && let Some(task) = task.take()
        {
            task.abort();
        }
    }
}

async fn selected(state: &SharedState) -> zbus::fdo::Result<(Arc<Coordinator>, NativeLease, u64)> {
    let st = state.lock().await;
    if !st.present {
        return Err(absent());
    }
    if st.controller.profile != 1 {
        return Err(zbus::fdo::Error::NotSupported(
            "application scanner requires Native WS73".into(),
        ));
    }
    Ok((
        st.discovery.clone(),
        st.native_lease.clone().ok_or_else(busy)?,
        st.controller.generation,
    ))
}

pub(crate) async fn acquire(
    state: &SharedState,
    bus: zbus::Connection,
    name: String,
    prefix: Vec<u8>,
    minimum_rssi: i16,
    duration_ms: u32,
    until: Deadline,
) -> zbus::fdo::Result<u64> {
    if !wire::valid_filter(&prefix, minimum_rssi, duration_ms) {
        return Err(zbus::fdo::Error::InvalidArgs(
            "bounded prefix/RSSI/duration required".into(),
        ));
    }
    until.remaining().map_err(failed)?;
    let (service, lease, generation) = selected(state).await?;
    let slot = service.owner_slot(&name)?;
    let owner = Owner::pin(bus, name, &service, slot, until.instant()).await?;
    let authority = lease.try_lock_owned().map_err(|_| busy())?;
    let token = authority
        .token
        .filter(|_| authority.accepting)
        .ok_or_else(busy)?;
    let fd = {
        let st = state.lock().await;
        if !st.present {
            return Err(absent());
        }
        st.native_control.clone().ok_or_else(absent)?
    };
    let (authority, after_sequence, radio_scan) = tokio::task::spawn_blocking(move || {
        let snapshot = fd.controller_snapshot(generation).map_err(failed)?;
        if snapshot.flags != slk_protocol::CONTROLLER_READY || snapshot.error != 0 {
            return Err(busy());
        }
        let position = fd.native_link_snapshot(generation).map_err(failed)?;
        let radio = fd.discovery_snapshot().map_err(failed)?;
        if radio.generation != generation {
            return Err(absent());
        }
        Ok((authority, position.event_seq, radio.radio_scan))
    })
    .await
    .map_err(failed)??;
    until.remaining().map_err(failed)?;
    let (id, epoch) = {
        let mut st = service.store.lock().expect("scanner registry");
        st.expire(Instant::now());
        if st.fence.retired() || !owner.current() {
            return Err(absent());
        }
        if st.entries.len() >= wire::MAX_SESSIONS
            || st
                .entries
                .values()
                .filter(|e| e.owner.name == owner.name)
                .count()
                >= wire::MAX_PER_CALLER
        {
            return Err(busy());
        }
        let id = st
            .next
            .checked_add(1)
            .ok_or_else(|| failed("discovery identity exhausted"))?;
        match st.phase {
            Phase::Idle if radio_scan == 1 => {
                st.advance()?;
                st.phase = Phase::Starting;
                st.scope = Some((generation, token));
                st.cleanup = None;
            }
            Phase::Running if st.scope == Some((generation, token)) && radio_scan == 2 => {}
            _ => return Err(busy()),
        }
        st.next = id;
        st.entries.insert(
            id,
            Entry {
                owner,
                prefix,
                minimum_rssi,
                expires: Instant::now() + Duration::from_millis(duration_ms.into()),
                opening: until.instant(),
                queue: VecDeque::new(),
                dropped: 0,
                kernel_lost: 0,
                reading: false,
                after_sequence,
            },
        );
        (id, st.fence.current())
    };
    drop(authority);
    let mut reservation = Reservation {
        service: Arc::downgrade(&service),
        id,
        armed: true,
    };
    service.changed.notify_waiters();
    let work = async {
        loop {
            let changed = service.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            {
                let mut st = service.store.lock().expect("scanner registry");
                st.expire(Instant::now());
                if !st.fence.accepts(epoch) || !st.entries.contains_key(&id) {
                    return Err(absent());
                }
                if st.phase == Phase::Running {
                    return Ok(id);
                }
                if st.phase == Phase::Fault {
                    return Err(failed(
                        "physical scanner start failed; manager cleanup required",
                    ));
                }
            }
            changed.await;
        }
    };
    match tokio::time::timeout_at(until.instant().into(), work).await {
        Ok(Ok(id)) => {
            until.remaining().map_err(failed)?;
            reservation.armed = false;
            Ok(id)
        }
        outcome => {
            service
                .store
                .lock()
                .expect("scanner registry")
                .remove(id, Instant::now() + Duration::from_secs(5));
            service.changed.notify_waiters();
            match outcome {
                Ok(Err(e)) => Err(e),
                _ => Err(zbus::fdo::Error::Timeout(
                    "original discovery start deadline expired".into(),
                )),
            }
        }
    }
}

/// Cancelling the server future does not leave a queued author behind. The
/// controller worker still owns any physical obligation already begun.
struct Reservation {
    service: Weak<Coordinator>,
    id: u64,
    armed: bool,
}
impl Drop for Reservation {
    fn drop(&mut self) {
        if self.armed
            && let Some(service) = self.service.upgrade()
        {
            service
                .store
                .lock()
                .expect("scanner registry")
                .remove(self.id, Instant::now() + Duration::from_secs(5));
            service.changed.notify_waiters();
        }
    }
}
struct Reader {
    service: Weak<Coordinator>,
    id: u64,
    _slot: OwnedSemaphorePermit,
}
impl Drop for Reader {
    fn drop(&mut self) {
        if let Some(service) = self.service.upgrade()
            && let Some(e) = service
                .store
                .lock()
                .expect("scanner registry")
                .entries
                .get_mut(&self.id)
        {
            e.reading = false;
        }
    }
}

pub(crate) async fn release(
    state: &SharedState,
    name: &str,
    id: u64,
    until: Deadline,
) -> zbus::fdo::Result<bool> {
    until.remaining().map_err(failed)?;
    let (service, _, _) = selected(state).await?;
    let epoch = {
        let mut st = service.store.lock().expect("scanner registry");
        let entry = st
            .entries
            .get(&id)
            .filter(|e| e.owner.current() && e.owner.name == name)
            .ok_or_else(absent)?;
        if entry.expires <= Instant::now() {
            return Err(absent());
        }
        let epoch = st.fence.current();
        st.remove(id, until.instant());
        service.changed.notify_waiters();
        if !st.entries.is_empty() {
            return Ok(false);
        }
        epoch
    };
    tokio::time::timeout_at(until.instant().into(), async {
        loop {
            let changed = service.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            {
                let st = service.store.lock().expect("scanner registry");
                if st.settled == Some((epoch, true)) {
                    return Ok(true);
                }
                if st.settled == Some((epoch, false))
                    || st.fence.retired()
                    || !st.fence.accepts(epoch)
                {
                    return Err(failed(
                        "scanner cleanup failed or superseded; no Off receipt",
                    ));
                }
            }
            changed.await;
        }
    })
    .await
    .map_err(|_| {
        zbus::fdo::Error::Timeout(
            "original discovery release deadline expired; cleanup not confirmed".into(),
        )
    })?
}

pub(crate) async fn reports(
    state: &SharedState,
    name: &str,
    id: u64,
    wait: bool,
    until: Deadline,
) -> zbus::fdo::Result<wire::Batch> {
    let (service, _, generation) = selected(state).await?;
    let slot = service
        .reads
        .clone()
        .try_acquire_owned()
        .map_err(|_| busy())?;
    {
        let mut st = service.store.lock().expect("scanner registry");
        let e = st
            .entries
            .get_mut(&id)
            .filter(|e| e.owner.current() && e.owner.name == name)
            .ok_or_else(absent)?;
        if e.reading {
            return Err(busy());
        }
        e.reading = true;
    }
    let _reader = Reader {
        service: Arc::downgrade(&service),
        id,
        _slot: slot,
    };
    tokio::time::timeout_at(until.instant().into(), async {
        loop {
            let changed = service.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            {
                let mut st = service.store.lock().expect("scanner registry");
                st.expire(Instant::now());
                until.remaining().map_err(failed)?;
                if st.fence.retired()
                    || st.phase != Phase::Running
                    || st.scope.is_none_or(|s| s.0 != generation)
                {
                    return Err(absent());
                }
                let e = st
                    .entries
                    .get_mut(&id)
                    .filter(|e| e.owner.current() && e.owner.name == name)
                    .ok_or_else(absent)?;
                if !wait || !e.queue.is_empty() || e.dropped != 0 || e.kernel_lost != 0 {
                    return Ok(wire::Batch {
                        version: wire::VERSION,
                        session: id,
                        generation,
                        dropped: e.dropped,
                        kernel_lost: e.kernel_lost,
                        reports: e.queue.drain(..).collect(),
                    });
                }
            }
            changed.await;
        }
    })
    .await
    .map_err(|_| {
        zbus::fdo::Error::Timeout("original discovery observation deadline expired".into())
    })?
}

fn valid_receipt(
    r: &slk_protocol::SleDiscoveryResult,
    generation: u64,
    id: u64,
    enable: bool,
) -> bool {
    generation != 0
        && id != 0
        && r.version == slk_protocol::DISCOVERY_VERSION
        && r.flags == 0
        && r.reserved == [0; 4]
        && r.profile == 1
        && r.generation == generation
        && r.request_id == id
        && r.operation == if enable { 3 } else { 4 }
        && r.state == 3
        && r.error == 0
        && r.status == 0
        && r.opcode == 0x1002
        && r.count == if enable { 2 } else { 1 }
        && r.step.checked_add(1) == Some(r.count)
        && r.radio_scan == if enable { 2 } else { 1 }
}
pub(crate) fn validate_receipt(
    r: &slk_protocol::SleDiscoveryResult,
    generation: u64,
    id: u64,
    enable: bool,
) -> zbus::fdo::Result<()> {
    if valid_receipt(r, generation, id, enable) {
        Ok(())
    } else {
        Err(failed(format!(
            "scanner receipt mismatch/failure request={} operation={} state={} errno={} opcode=0x{:04x} status=0x{:02x}",
            r.request_id, r.operation, r.state, r.error, r.opcode, r.status
        )))
    }
}

pub(crate) fn start_worker(
    state: &SharedState,
    mut cancelled: watch::Receiver<bool>,
) -> tokio::task::JoinHandle<()> {
    let weak = Arc::downgrade(state);
    tokio::spawn(async move {
        let Some(state) = weak.upgrade() else {
            return;
        };
        let service = state.lock().await.discovery.clone();
        let _exit = WorkerExit(service.clone());
        drop(state);
        loop {
            let changed = service.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if *cancelled.borrow() || cancelled.has_changed().is_err() {
                service.invalidate(true);
                return;
            }
            let action = {
                let mut st = service.store.lock().expect("scanner registry");
                st.expire(Instant::now());
                if st.fence.retired() {
                    return;
                }
                match st.phase {
                    Phase::Starting => Some((
                        st.fence.current(),
                        true,
                        st.scope,
                        st.entries.values().map(|e| e.opening).min().or(st.cleanup),
                    )),
                    Phase::Stopping => Some((st.fence.current(), false, st.scope, st.cleanup)),
                    _ => None,
                }
            };
            if let Some((epoch, enable, scope, until)) = action {
                let outcome = match (scope, until) {
                    (Some(scope), Some(until)) => {
                        physical(&weak, &service, epoch, scope, enable, until).await
                    }
                    _ => Err(absent()),
                };
                let mut st = service.store.lock().expect("scanner registry");
                if st.fence.accepts(epoch) {
                    match (enable, outcome) {
                        (true, Ok(())) => {
                            st.phase = if st.entries.is_empty() {
                                Phase::Stopping
                            } else {
                                Phase::Running
                            };
                        }
                        (false, Ok(())) => {
                            st.phase = Phase::Idle;
                            st.scope = None;
                            st.settled = Some((epoch, true));
                        }
                        (_, Err(error)) => {
                            tracing::warn!(epoch, %error, "application scanner policy failed");
                            st.phase = Phase::Fault;
                            st.entries.clear();
                            st.settled = Some((epoch, false));
                        }
                    }
                    service.changed.notify_waiters();
                }
                continue;
            }
            let expires = service
                .store
                .lock()
                .expect("scanner registry")
                .entries
                .values()
                .map(|e| e.expires)
                .min();
            tokio::select! {
                _ = cancelled.changed() => {},
                _ = &mut changed => {},
                _ = async { if let Some(at) = expires { tokio::time::sleep_until(at.into()).await } else { std::future::pending().await } } => {},
            }
        }
    })
}
struct WorkerExit(Arc<Coordinator>);
impl Drop for WorkerExit {
    fn drop(&mut self) {
        self.0.invalidate(true);
    }
}

async fn physical(
    state: &Weak<tokio::sync::Mutex<crate::state::AdapterState>>,
    service: &Coordinator,
    epoch: u64,
    scope: (u64, u64),
    enable: bool,
    until: Instant,
) -> zbus::fdo::Result<()> {
    let state = state.upgrade().ok_or_else(absent)?;
    let (_, lease, generation) = selected(&state).await?;
    let authority = tokio::time::timeout_at(until.into(), lease.lock_owned())
        .await
        .map_err(|_| failed("original scanner deadline while waiting for Native authority"))?;
    if generation != scope.0 || authority.token != Some(scope.1) || !authority.accepting {
        return Err(absent());
    }
    {
        let mut st = service.store.lock().expect("scanner registry");
        st.expire(Instant::now());
        if !st.fence.accepts(epoch)
            || st.fence.retired()
            || st.scope != Some(scope)
            || st.phase
                != if enable {
                    Phase::Starting
                } else {
                    Phase::Stopping
                }
        {
            return Err(absent());
        }
        if enable && st.entries.is_empty() {
            return Err(absent());
        }
    }
    crate::radio::session_operation(&state, authority, enable, until).await
}
