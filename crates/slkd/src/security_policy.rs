//! Per-controller consent and call ownership. The kernel's physical Session is
//! the only protocol/crypto engine. No keys or wire packets cross this broker.
use crate::state::{NativeLease, SharedState};
use slk_native::Adapter;
use slk_protocol::{
    SleLinkInfo, SleSecurityNegotiationCancel, SleSecurityNegotiationResult,
    SleSecurityNegotiationSubmit, SleSecurityNumericConfirm,
};
use std::{collections::BTreeMap, sync::Arc, time::Duration};
use tokio::sync::{Mutex, watch};
use zbus::{export::ordered_stream::OrderedStreamExt, zvariant::OwnedObjectPath};

pub(crate) use slk_contract::security::{METHOD, NUMERIC_METHOD};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Method {
    NoMitm,
    Numeric,
}
impl Method {
    fn parse(value: &str) -> zbus::fdo::Result<Self> {
        match value {
            METHOD => Ok(Self::NoMitm),
            NUMERIC_METHOD => Ok(Self::Numeric),
            _ => Err(zbus::fdo::Error::NotSupported(
                "unsupported Agent method; no fallback".into(),
            )),
        }
    }
    fn name(self) -> &'static str {
        match self {
            Self::NoMitm => METHOD,
            Self::Numeric => NUMERIC_METHOD,
        }
    }
    fn flags(self) -> u32 {
        match self {
            Self::NoMitm => 3,
            Self::Numeric => 4,
        }
    }
    fn completed(self, result: &SleSecurityNegotiationResult, confirmed: bool) -> bool {
        result.error == 0
            && result.status == 0
            && match self {
                Self::NoMitm => result.state == 9 && result.flags == 7,
                Self::Numeric => confirmed && result.state == 11 && result.flags == 119,
            }
    }
}
use slk_contract::security::Prompt;

const MAX_RECORDS: usize = 64;
const MAX_AUTHOR_PENDING: usize = 4;
pub(crate) type Shared = Arc<Mutex<Registry>>;
pub(crate) use slk_contract::security::Observation;
#[derive(Clone)]
struct Agent {
    method: Method,
    owner: String,
    path: OwnedObjectPath,
    epoch: u64,
    revoked: watch::Sender<bool>,
}
#[derive(Clone)]
struct Entry {
    owner: String,
    reference: SleLinkInfo,
    agent: Agent,
    observation: Observation,
    cancel: watch::Sender<bool>,
    started: watch::Sender<bool>,
}
#[derive(Default)]
pub(crate) struct Registry {
    retired: bool,
    epoch: u64,
    next_id: u64,
    agent: Option<Agent>,
    entries: BTreeMap<u64, Entry>,
}
fn failed(e: impl std::fmt::Display) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(e.to_string())
}
fn invalid(e: &str) -> zbus::fdo::Error {
    zbus::fdo::Error::InvalidArgs(e.into())
}
pub(crate) fn sender(header: &zbus::message::Header<'_>) -> zbus::fdo::Result<String> {
    header
        .sender()
        .map(ToString::to_string)
        .ok_or_else(|| failed("missing unique caller"))
}
fn monotonic_ns() -> zbus::fdo::Result<u64> {
    let mut time = nix::libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: writable timespec and the explicit same clock as submit v2.
    if unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_MONOTONIC, &mut time) } != 0 {
        return Err(failed(std::io::Error::last_os_error()));
    }
    u64::try_from(time.tv_sec)
        .ok()
        .and_then(|v| v.checked_mul(1_000_000_000))
        .and_then(|v| v.checked_add(time.tv_nsec as u64))
        .ok_or_else(|| failed("clock overflow"))
}
fn native_errno(error: slk_native::Error) -> i32 {
    match error {
        slk_native::Error::Ioctl(e) => -(e as i32),
        slk_native::Error::Timeout => -nix::libc::ETIMEDOUT,
        slk_native::Error::NotSupported(_) => -nix::libc::EOPNOTSUPP,
        _ => -nix::libc::EIO,
    }
}
async fn registry(state: &SharedState) -> Shared {
    state.lock().await.security_policy.clone()
}
impl Registry {
    fn sweep(&mut self, now: u64) {
        for entry in self
            .entries
            .values_mut()
            .filter(|e| e.observation.phase == 1)
        {
            let out = &mut entry.observation;
            if now >= out.deadline_monotonic_ns {
                out.phase = 7;
                out.error = -nix::libc::ETIMEDOUT;
            } else if self
                .agent
                .as_ref()
                .is_none_or(|a| a.epoch != entry.agent.epoch)
            {
                out.phase = 10;
                out.error = -nix::libc::ECANCELED;
            }
        }
    }
    fn owned(
        &self,
        id: u64,
        owner: &str,
        generation: u64,
        reference: SleLinkInfo,
    ) -> zbus::fdo::Result<&Entry> {
        let entry = self.entries.get(&id).ok_or_else(|| {
            zbus::fdo::Error::UnknownObject("security request absent or evicted".into())
        })?;
        if entry.owner != owner
            || entry.observation.generation != generation
            || entry.reference != reference
        {
            return Err(zbus::fdo::Error::AccessDenied(
                "request belongs to another caller/physical connection".into(),
            ));
        }
        Ok(entry)
    }
}
async fn name_exists(bus: &zbus::fdo::DBusProxy<'_>, owner: &str) -> zbus::fdo::Result<bool> {
    bus.name_has_owner(owner.try_into().map_err(failed)?).await
}
pub(crate) async fn register(
    state: &SharedState,
    connection: &zbus::Connection,
    owner: String,
    path: OwnedObjectPath,
    method: &str,
) -> zbus::fdo::Result<u64> {
    {
        let st = state.lock().await;
        if !st.present || st.controller.profile != 1 {
            return Err(zbus::fdo::Error::NotSupported(
                "Agent requires a present Native WS73 controller".into(),
            ));
        }
    }
    let method = Method::parse(method)?;
    if path.as_str() == "/" {
        return Err(invalid("an explicit Agent object path is required"));
    }
    let bus = zbus::fdo::DBusProxy::new(connection)
        .await
        .map_err(failed)?;
    let mut lost = bus
        .receive_name_owner_changed_with_args(&[(0, &owner), (2, "")])
        .await
        .map_err(failed)?;
    if !name_exists(&bus, &owner).await? {
        return Err(failed("Agent caller disappeared"));
    }
    let registry = registry(state).await;
    let agent = {
        let mut guard = registry.lock().await;
        if guard.retired {
            return Err(failed("controller policy retired"));
        }
        if guard.agent.is_some() {
            return Err(failed("controller already has an Agent"));
        }
        guard.epoch = guard
            .epoch
            .checked_add(1)
            .ok_or_else(|| failed("Agent epoch exhausted"))?;
        let (revoked, _) = watch::channel(false);
        let agent = Agent {
            method,
            owner,
            path,
            epoch: guard.epoch,
            revoked,
        };
        guard.agent = Some(agent.clone());
        agent
    };
    let epoch = agent.epoch;
    let mut revoked = agent.revoked.subscribe();
    tokio::spawn(async move {
        tokio::select! {biased; _=lost.next()=>{}, _=revoked.changed()=>{}}
        let mut guard = registry.lock().await;
        if guard.agent.as_ref().is_some_and(|a| a.epoch == agent.epoch) {
            guard.agent.take();
            agent.revoked.send_replace(true);
        }
    });
    Ok(epoch)
}
pub(crate) async fn unregister(
    state: &SharedState,
    owner: &str,
    path: OwnedObjectPath,
    epoch: u64,
) -> zbus::fdo::Result<()> {
    let registry = registry(state).await;
    let mut guard = registry.lock().await;
    let agent = guard
        .agent
        .as_ref()
        .ok_or_else(|| failed("no Agent registered"))?;
    if agent.owner != owner || agent.path != path || agent.epoch != epoch {
        return Err(zbus::fdo::Error::AccessDenied(
            "only original Agent may unregister".into(),
        ));
    }
    let agent = guard.agent.take().ok_or_else(|| failed("Agent absent"))?;
    agent.revoked.send_replace(true);
    Ok(())
}
pub(crate) async fn retire(state: &SharedState) {
    let registry = registry(state).await;
    let mut guard = registry.lock().await;
    guard.retired = true;
    if let Some(agent) = guard.agent.take() {
        agent.revoked.send_replace(true);
    }
    for entry in guard.entries.values() {
        entry.cancel.send_replace(true);
    }
}
struct Native {
    fd: Arc<Adapter>,
    lease: NativeLease,
    token: u64,
    generation: u64,
}
async fn selected(
    state: &SharedState,
    generation: u64,
    reference: SleLinkInfo,
) -> zbus::fdo::Result<Native> {
    let (fd, lease) = {
        let st = state.lock().await;
        if !st.present
            || st.controller.flags != slk_protocol::CONTROLLER_READY
            || st.controller.generation != generation
            || st.controller.profile != 1
            || !st.native_links_known()
            || !st.native_links.as_ref().is_some_and(|v| {
                v.valid_for(generation)
                    && v.profile == 1
                    && v.links[..v.count as usize].contains(&reference)
            })
        {
            return Err(failed("current known WS73 physical connection required"));
        }
        (
            st.native_control
                .clone()
                .ok_or_else(|| failed("native control unavailable"))?,
            st.native_lease
                .clone()
                .ok_or_else(|| failed("management unavailable"))?,
        )
    };
    let token = {
        let guard = lease
            .try_lock()
            .map_err(|_| failed("management handoff busy"))?;
        if !guard.accepting {
            return Err(failed("management unavailable"));
        }
        guard.token.ok_or_else(|| failed("no Managed lease"))?
    };
    Ok(Native {
        fd,
        lease,
        token,
        generation,
    })
}
pub(crate) async fn allocate(
    state: &SharedState,
    connection: &zbus::Connection,
    generation: u64,
    reference: SleLinkInfo,
    owner: &str,
    timeout_ms: u32,
) -> zbus::fdo::Result<u64> {
    if !(1..=5000).contains(&timeout_ms) {
        return Err(invalid("timeout must be1..5000ms"));
    }
    let deadline = monotonic_ns()?
        .checked_add(u64::from(timeout_ms) * 1_000_000)
        .ok_or_else(|| failed("deadline overflow"))?;
    // The original budget includes bus subscriptions, selection and lock waits.
    // No yield occurs between insertion and starting the bounded supervisor.
    let prepare = async {
        let bus = zbus::fdo::DBusProxy::new(connection)
            .await
            .map_err(failed)?;
        let mut lost = bus
            .receive_name_owner_changed_with_args(&[(0, owner), (2, "")])
            .await
            .map_err(failed)?;
        if !name_exists(&bus, owner).await? {
            return Err(failed("request caller disappeared"));
        }
        let _ = selected(state, generation, reference).await?;
        let registry = registry(state).await;
        let mut guard = registry.lock().await;
        let now = monotonic_ns()?;
        guard.sweep(now);
        if now >= deadline {
            return Err(failed("original allocation deadline expired"));
        }
        if guard.retired {
            return Err(failed("controller policy retired"));
        }
        let agent = guard
            .agent
            .clone()
            .ok_or_else(|| zbus::fdo::Error::NotSupported("no explicit security Agent".into()))?;
        if guard
            .entries
            .values()
            .filter(|e| e.owner == owner && e.observation.phase < 4)
            .count()
            >= MAX_AUTHOR_PENDING
            || guard.entries.values().any(|e| {
                e.observation.generation == generation
                    && e.reference.lifetime == reference.lifetime
                    && (e.observation.phase < 4 || e.observation.native_admitted)
            })
        {
            return Err(failed("security request budget or physical lifetime busy"));
        }
        if guard.entries.len() >= MAX_RECORDS {
            let retired = guard
                .entries
                .iter()
                .find(|(_, e)| e.observation.phase >= 4)
                .map(|(id, _)| *id)
                .ok_or_else(|| failed("security request table full"))?;
            guard.entries.remove(&retired);
        }
        guard.next_id = guard
            .next_id
            .checked_add(1)
            .ok_or_else(|| failed("request id exhausted"))?;
        let id = guard.next_id;
        let (cancel, _) = watch::channel(false);
        let (started, _) = watch::channel(false);
        let entry = Entry {
            owner: owner.into(),
            reference,
            agent,
            cancel,
            started,
            observation: Observation {
                request_id: id,
                generation,
                lifetime: reference.lifetime,
                phase: 1,
                error: 0,
                deadline_monotonic_ns: deadline,
                agent_approved: false,
                native_admitted: false,
                kernel_state: 0,
                kernel_error: 0,
                kernel_flags: 0,
                kernel_status: 0,
                cleanup_error: 0,
            },
        };
        guard.entries.insert(id, entry.clone());
        drop(guard);
        tokio::spawn(async move {
            let mut started = entry.started.subscribe();
            let mut cancelled = entry.cancel.subscribe();
            let mut revoked = entry.agent.revoked.subscribe();
            if *started.borrow() {
                return;
            }
            let stop = if *cancelled.borrow() {
                Stop {
                    phase: 6,
                    error: -nix::libc::ECANCELED,
                }
            } else if *revoked.borrow() {
                Stop {
                    phase: 10,
                    error: -nix::libc::ECANCELED,
                }
            } else if let Ok(now) = monotonic_ns() {
                tokio::select! {biased;
                    _=started.changed()=>return,
                    _=lost.next()=>Stop { phase: 9, error: -nix::libc::ECANCELED },
                    _=revoked.changed()=>Stop { phase: 10, error: -nix::libc::ECANCELED },
                    _=cancelled.changed()=>Stop { phase: 6, error: -nix::libc::ECANCELED },
                    _=tokio::time::sleep(Duration::from_nanos(deadline.saturating_sub(now)))=>
                        Stop { phase: 7, error: -nix::libc::ETIMEDOUT },
                }
            } else {
                Stop {
                    phase: 8,
                    error: -nix::libc::EIO,
                }
            };
            let mut guard = registry.lock().await;
            let retired = guard.retired;
            if let Some(current) = guard.entries.get_mut(&id)
                && current.observation.phase == 1
            {
                let out = &mut current.observation;
                out.phase = if retired { 8 } else { stop.phase };
                out.error = if retired {
                    -nix::libc::ENODEV
                } else {
                    stop.error
                };
            }
        });
        Ok(id)
    };
    tokio::time::timeout(
        Duration::from_nanos(deadline.saturating_sub(monotonic_ns()?)),
        prepare,
    )
    .await
    .map_err(|_| failed("original allocation deadline expired"))?
}
pub(crate) async fn observation(
    state: &SharedState,
    owner: &str,
    generation: u64,
    reference: SleLinkInfo,
    id: u64,
) -> zbus::fdo::Result<Observation> {
    let registry = registry(state).await;
    let mut guard = registry.lock().await;
    guard.sweep(monotonic_ns()?);
    Ok(guard
        .owned(id, owner, generation, reference)?
        .observation
        .clone())
}
pub(crate) async fn cancel(
    state: &SharedState,
    owner: &str,
    generation: u64,
    reference: SleLinkInfo,
    id: u64,
) -> zbus::fdo::Result<bool> {
    let registry = registry(state).await;
    let mut guard = registry.lock().await;
    guard.sweep(monotonic_ns()?);
    let entry = guard.owned(id, owner, generation, reference)?;
    if entry.observation.phase >= 4 {
        return Ok(false);
    }
    entry.cancel.send_replace(true);
    if entry.observation.phase == 1 {
        let entry = guard
            .entries
            .get_mut(&id)
            .ok_or_else(|| failed("request absent"))?;
        entry.observation.phase = 6;
        entry.observation.error = -nix::libc::ECANCELED;
    }
    Ok(true) // cancellation requested, not physical cancellation acknowledged
}
pub(crate) async fn begin(
    state: &SharedState,
    connection: &zbus::Connection,
    owner: &str,
    generation: u64,
    reference: SleLinkInfo,
    id: u64,
    method: &str,
) -> zbus::fdo::Result<()> {
    let method = Method::parse(method)?;
    let registry = registry(state).await;
    let entry = {
        let mut guard = registry.lock().await;
        guard.sweep(monotonic_ns()?);
        if guard.retired {
            return Err(failed("controller policy retired"));
        }
        let entry = guard.owned(id, owner, generation, reference)?;
        if entry.agent.method != method {
            return Err(zbus::fdo::Error::NotSupported(
                "method differs from allocated Agent; no fallback".into(),
            ));
        }
        if entry.observation.phase != 1 {
            return Err(failed("request already started or terminal"));
        }
        let entry = guard
            .entries
            .get_mut(&id)
            .ok_or_else(|| failed("request absent"))?;
        entry.observation.phase = 2;
        entry.started.send_replace(true);
        entry.clone()
    };
    let state = state.clone();
    let connection = connection.clone();
    // Task retains the original native submission and cleanup even if this
    // admission RPC's reply disappears. No JoinHandle drop cancels the ioctl.
    tokio::spawn(async move {
        if let Err(error) = supervise(&state, &connection, &registry, entry.clone()).await {
            finish(&registry, id, 8, -nix::libc::EIO).await;
            tracing::warn!(request=id, error=%error,"security policy task failed");
        }
    });
    Ok(())
}
// Used by the actual terminal publication, not a verification-only model.
fn completion_at(now: Option<u64>, deadline: u64) -> (u32, i32) {
    match now {
        Some(now) if now < deadline => (4, 0),
        Some(_) => (7, -nix::libc::ETIMEDOUT),
        None => (8, -nix::libc::EIO),
    }
}
async fn finish(registry: &Shared, id: u64, phase: u32, error: i32) {
    if let Some(entry) = registry.lock().await.entries.get_mut(&id)
        && entry.observation.phase < 4
    {
        let (phase, error) = if phase == 4 && *entry.cancel.borrow() {
            (6, -nix::libc::ECANCELED)
        } else if phase == 4 && *entry.agent.revoked.borrow() {
            (10, -nix::libc::ECANCELED)
        } else if phase == 4 {
            completion_at(monotonic_ns().ok(), entry.observation.deadline_monotonic_ns)
        } else {
            (phase, error)
        };
        entry.observation.phase = phase;
        entry.observation.error = error;
    }
}
#[derive(Clone, Copy)]
struct Stop {
    phase: u32,
    error: i32,
}
/// Both callbacks address the same pinned Agent and full original identity.
/// Numeric confirmation is a separate decision after the kernel's live prompt.
async fn agent_decision(
    connection: &zbus::Connection,
    entry: &Entry,
    args: &Prompt,
    code: Option<u32>,
) -> zbus::Result<bool> {
    let agent = zbus::Proxy::new(
        connection,
        entry.agent.owner.as_str(),
        entry.agent.path.as_str(),
        "org.sparklink.Agent",
    )
    .await?;
    match code {
        None => {
            agent
                .call("AuthorizeReferenceSecurity", &(args.clone(),))
                .await
        }
        Some(code) if entry.agent.method == Method::Numeric && code < 1_000_000 => {
            agent
                .call("ConfirmNumericComparison", &(args.clone(), code))
                .await
        }
        Some(_) => Err(zbus::Error::Failure("invalid numeric prompt/method".into())),
    }
}
async fn supervise(
    state: &SharedState,
    connection: &zbus::Connection,
    registry: &Shared,
    entry: Entry,
) -> zbus::fdo::Result<()> {
    let id = entry.observation.request_id;
    let bus = zbus::fdo::DBusProxy::new(connection)
        .await
        .map_err(failed)?;
    // Both streams exist before owner queries and before invoking the Agent.
    let mut caller_lost = bus
        .receive_name_owner_changed_with_args(&[(0, &entry.owner), (2, "")])
        .await
        .map_err(failed)?;
    let mut agent_lost = bus
        .receive_name_owner_changed_with_args(&[(0, &entry.agent.owner), (2, "")])
        .await
        .map_err(failed)?;
    let mut cancel = entry.cancel.subscribe();
    let mut revoked = entry.agent.revoked.subscribe();
    if !name_exists(&bus, &entry.owner).await? {
        finish(registry, id, 9, -nix::libc::ECANCELED).await;
        return Ok(());
    }
    if !name_exists(&bus, &entry.agent.owner).await? {
        finish(registry, id, 10, -nix::libc::ECANCELED).await;
        return Ok(());
    }
    let remaining = entry
        .observation
        .deadline_monotonic_ns
        .saturating_sub(monotonic_ns()?);
    let expiration = tokio::time::sleep(Duration::from_nanos(remaining));
    tokio::pin!(expiration);
    let stop = async {
        if *cancel.borrow() {
            return Stop {
                phase: 6,
                error: -nix::libc::ECANCELED,
            };
        }
        if *revoked.borrow() {
            return Stop {
                phase: 10,
                error: -nix::libc::ECANCELED,
            };
        }
        tokio::select! {biased;
            _=caller_lost.next()=>Stop {phase:9,error:-nix::libc::ECANCELED},
            _=agent_lost.next()=>Stop {phase:10,error:-nix::libc::ECANCELED},
            _=revoked.changed()=>Stop {phase:10,error:-nix::libc::ECANCELED},
            _=cancel.changed()=>Stop {phase:6,error:-nix::libc::ECANCELED},
            _=&mut expiration=>Stop {phase:7,error:-nix::libc::ETIMEDOUT},
        }
    };
    tokio::pin!(stop);
    let path = {
        let st = state.lock().await;
        crate::connection_object::path(&st.object_path, entry.reference)
    };
    let args = (
        path,
        id,
        entry.observation.generation,
        entry.reference.lifetime,
        entry.reference.handle,
        entry.reference.role,
        entry.reference.address_type,
        crate::dbus_iface::format_addr(&entry.reference.address),
        entry.agent.method.name().to_string(),
        entry.observation.deadline_monotonic_ns,
    );
    let approval = agent_decision(connection, &entry, &args, None);
    let approved = tokio::select! {biased;
        stopped=&mut stop=>{finish(registry,id,stopped.phase,stopped.error).await;return Ok(());},
        result=approval=>result,
    };
    match approved {
        Ok(true) => {}
        Ok(false) => {
            finish(registry, id, 5, -nix::libc::ECANCELED).await;
            return Ok(());
        }
        Err(_) => {
            finish(registry, id, 10, -nix::libc::ECANCELED).await;
            return Ok(());
        }
    }
    {
        let mut guard = registry.lock().await;
        if guard
            .agent
            .as_ref()
            .is_none_or(|a| a.epoch != entry.agent.epoch)
        {
            drop(guard);
            finish(registry, id, 10, -nix::libc::ECANCELED).await;
            return Ok(());
        }
        let current = guard
            .entries
            .get_mut(&id)
            .ok_or_else(|| failed("request absent"))?;
        current.observation.agent_approved = true;
    }
    let native = match selected(state, entry.observation.generation, entry.reference).await {
        Ok(v) => v,
        Err(error) => {
            finish(registry, id, 8, -nix::libc::ESTALE).await;
            return Err(error);
        }
    };
    let request = SleSecurityNegotiationSubmit {
        generation: native.generation,
        lifetime: entry.reference.lifetime,
        request_id: id,
        deadline_monotonic_ns: entry.observation.deadline_monotonic_ns,
        version: 2,
        profile: 1,
        action: if entry.reference.role == 0 { 2 } else { 1 },
        flags: entry.agent.method.flags(),
        timeout_ms: 5000,
        handle: entry.reference.handle,
        role: entry.reference.role,
        address_type: entry.reference.address_type,
        address: entry.reference.address,
        ..Default::default()
    };
    if let Some(current) = registry.lock().await.entries.get_mut(&id) {
        current.observation.phase = 3;
    }
    // Poll already-established loss/cancel/deadline sources BEFORE launching
    // work. A known withdrawal must never cause the submit future to start.
    tokio::select! {biased;
        value=&mut stop=>{finish(registry,id,value.phase,value.error).await;return Ok(());},
        _=std::future::ready(())=>{},
    }
    let authority = match native.lease.clone().try_lock_owned() {
        Ok(guard) if guard.accepting && guard.token == Some(native.token) => guard,
        _ => {
            finish(registry, id, 8, -nix::libc::EACCES).await;
            return Ok(());
        }
    };
    let fd = native.fd.clone();
    // From this point the original bounded kernel admission is in flight.
    // ALWAYS join it before cleanup, including caller/Agent loss. The task
    // keeps this File and its original lease; it never releases the controller.
    let mut submit = tokio::task::spawn_blocking(move || {
        let _authority = authority;
        fd.submit_native_security_negotiation(&request)
            .map_err(native_errno)
    });
    let (submitted, mut stopped) = tokio::select! {biased;
        value=&mut stop=>(submit.await,Some(value)),
        result=&mut submit=>(result,None),
    };
    let submitted = submitted.unwrap_or(Err(-nix::libc::EIO));
    if let Some(current) = registry.lock().await.entries.get_mut(&id) {
        current.observation.native_admitted = submitted.is_ok();
    }
    if let Err(error) = submitted {
        stopped = Some(stopped.unwrap_or(Stop {
            phase: if error == -nix::libc::ETIMEDOUT { 7 } else { 8 },
            error,
        }));
    }
    let mut numeric_confirmed = false;
    if stopped.is_none() {
        loop {
            let fd = native.fd.clone();
            let query = tokio::task::spawn_blocking(move || {
                fd.native_security_negotiation(
                    request.generation,
                    request.lifetime,
                    request.handle,
                    id,
                )
            });
            let result = query
                .await
                .unwrap_or(Err(slk_native::Error::Ioctl(nix::errno::Errno::EIO)));
            match result {
                Ok(result) => {
                    if let Some(current) = registry.lock().await.entries.get_mut(&id) {
                        let out = &mut current.observation;
                        out.kernel_state = result.state;
                        out.kernel_error = result.error;
                        out.kernel_flags = result.flags;
                        out.kernel_status = result.status;
                    }
                    // Join the actual query, then prioritize already-observable
                    // caller/Agent/cancel/deadline loss before any continuation.
                    tokio::select! {biased;
                        value=&mut stop=>{stopped=Some(value);break;},
                        _=std::future::ready(())=>{},
                    }
                    if entry.agent.method == Method::Numeric && result.flags & 8 != 0 {
                        if numeric_confirmed {
                            stopped = Some(Stop {
                                phase: 8,
                                error: -nix::libc::EPROTO,
                            });
                            break;
                        }
                        let decision = tokio::select! {biased;
                            value=&mut stop=>{stopped=Some(value);break;},
                            value=agent_decision(connection,&entry,&args,Some(result.comparison_code))=>value,
                        };
                        let accepted = match decision {
                            Ok(value) => value,
                            Err(_) => {
                                stopped = Some(Stop {
                                    phase: 10,
                                    error: -nix::libc::ECANCELED,
                                });
                                break;
                            }
                        };
                        // The immutable Agent epoch/method and original File,
                        // lease and deadline remain authoritative, not the UI.
                        if registry
                            .lock()
                            .await
                            .agent
                            .as_ref()
                            .is_none_or(|a| a.epoch != entry.agent.epoch)
                        {
                            stopped = Some(Stop {
                                phase: 10,
                                error: -nix::libc::ECANCELED,
                            });
                            break;
                        }
                        tokio::select! {biased;
                            value=&mut stop=>{stopped=Some(value);break;},
                            _=std::future::ready(())=>{},
                        }
                        let authority = match native.lease.clone().try_lock_owned() {
                            Ok(guard) if guard.accepting && guard.token == Some(native.token) => {
                                guard
                            }
                            _ => {
                                stopped = Some(Stop {
                                    phase: 8,
                                    error: -nix::libc::EACCES,
                                });
                                break;
                            }
                        };
                        let confirm = SleSecurityNumericConfirm {
                            generation: request.generation,
                            lifetime: request.lifetime,
                            request_id: id,
                            version: 1,
                            comparison_code: result.comparison_code,
                            handle: request.handle,
                            accept: u8::from(accepted),
                            ..Default::default()
                        };
                        let fd = native.fd.clone();
                        let mut operation = tokio::task::spawn_blocking(move || {
                            let _authority = authority;
                            fd.confirm_native_security_numeric(&confirm)
                                .map_err(native_errno)
                        });
                        // Never abandon a started original File ioctl on stop.
                        let (confirmed, withdrawal) = tokio::select! {biased;
                            value=&mut stop=>(operation.await,Some(value)),
                            value=&mut operation=>(value,None),
                        };
                        let confirmed = confirmed.unwrap_or(Err(-nix::libc::EIO));
                        if let Some(value) = withdrawal {
                            stopped = Some(value);
                            break;
                        }
                        if let Err(error) = confirmed {
                            stopped = Some(Stop {
                                phase: if error == -nix::libc::ETIMEDOUT { 7 } else { 8 },
                                error,
                            });
                            break;
                        }
                        if !accepted {
                            stopped = Some(Stop {
                                phase: 5,
                                error: -nix::libc::ECANCELED,
                            });
                            break;
                        }
                        numeric_confirmed = true; // Local ioctl only, not trust/install.
                        continue;
                    }
                    if entry.agent.method.completed(&result, numeric_confirmed) {
                        finish(registry, id, 4, 0).await;
                        // Prompt the existing service owner only after an
                        // actual terminal native result and a still-successful
                        // original policy request. This does not install keys,
                        // mint a Grant, change its epoch or extend the deadline.
                        let completed = registry
                            .lock()
                            .await
                            .entries
                            .get(&id)
                            .is_some_and(|v| v.observation.phase == 4);
                        if completed {
                            crate::event_loop::start_ssap_after_security(
                                state,
                                connection,
                                native.generation,
                                entry.reference,
                            )
                            .await;
                        }
                        return Ok(());
                    }
                    if matches!(result.state, 4 | 8 | 9 | 11) {
                        stopped = Some(Stop {
                            phase: 8,
                            error: -nix::libc::EPROTO,
                        });
                        break;
                    }
                    if matches!(result.state, 5..=7) {
                        stopped = Some(Stop {
                            phase: if result.state == 7 { 7 } else { 8 },
                            error: result.error,
                        });
                        break;
                    }
                }
                Err(error) => {
                    stopped = Some(Stop {
                        phase: 8,
                        error: native_errno(error),
                    });
                    break;
                }
            }
            tokio::select! {biased;
                value=&mut stop=>{stopped=Some(value);break;},
                _=tokio::time::sleep(Duration::from_millis(5))=>{},
            }
        }
    }
    let cancel_request = SleSecurityNegotiationCancel {
        generation: request.generation,
        lifetime: request.lifetime,
        request_id: id,
        version: 1,
        handle: request.handle,
        reserved: 0,
    };
    let fd = native.fd.clone();
    let cleanup = tokio::task::spawn_blocking(move || {
        let error = fd
            .cancel_native_security_negotiation(&cancel_request)
            .err()
            .map(native_errno)
            .unwrap_or(0);
        let observed = fd.native_security_negotiation(
            request.generation,
            request.lifetime,
            request.handle,
            id,
        );
        (error, observed)
    })
    .await
    .unwrap_or((
        -nix::libc::EIO,
        Err(slk_native::Error::Ioctl(nix::errno::Errno::EIO)),
    ));
    if let Some(current) = registry.lock().await.entries.get_mut(&id) {
        let out = &mut current.observation;
        out.cleanup_error = cleanup.0;
        if let Ok(observed) = cleanup.1 {
            out.kernel_state = observed.state;
            out.kernel_error = observed.error;
            out.kernel_flags = observed.flags;
            out.kernel_status = observed.status;
        }
    }
    let stopped = stopped.unwrap_or(Stop {
        phase: 8,
        error: -nix::libc::EIO,
    });
    finish(registry, id, stopped.phase, stopped.error).await;
    Ok(())
}

#[cfg(test)]
#[path = "security_policy_tests.rs"]
pub(crate) mod tests;
