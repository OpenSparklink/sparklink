//! Single lifetime-scoped SMTC owner: initial ExchangeInfo and bounded base
//! single-value requests. No synthetic replies, security projection, reliable
//! mode, fragmentation or complete service-discovery claim.
use slk_protocol::{
    SleChannelInfo,
    ssap::{
        exchange::{ExchangeInfo, ExchangeKind},
        value::ValuePdu,
    },
};
use std::{
    collections::VecDeque,
    io,
    os::fd::{AsRawFd, OwnedFd},
    time::Duration,
};
use tokio::{
    io::unix::AsyncFd,
    sync::{mpsc, oneshot, watch},
    task::JoinHandle,
    time::Instant,
};

pub(crate) type Incoming = (bool, Vec<u8>);
pub(crate) type UuidValues = (Vec<(u16, bool, u16, Vec<u8>)>, Vec<u8>, Vec<u8>);
pub(crate) type Discovery = (
    Vec<slk_protocol::ssap::discovery::Entry>,
    Vec<(Vec<u8>, Vec<u8>)>,
);
pub(crate) type Info = (
    u16,
    u64,
    u64,
    u16,
    u16,
    u16,
    Vec<u8>,
    Vec<u8>,
    Vec<u8>,
    Vec<u8>,
);
#[derive(Clone, Debug)]
enum Status {
    Starting,
    Negotiated(Info),
    Failed(String),
}
enum Query {
    Info(oneshot::Sender<Result<Info, String>>),
    TransportStatus {
        deadline: Instant,
        reply: oneshot::Sender<Result<slk_protocol::SleSessionTxStatus, String>>,
    },
    Incoming {
        handles: Vec<u16>,
        modes: u8,
        deadline: Instant,
        reply: oneshot::Sender<Result<Incoming, String>>,
    },
    Value {
        bytes: Vec<u8>,
        deadline: Instant,
        minimum: u32,
        reply: oneshot::Sender<Result<Vec<u8>, String>>,
    },
}
type Store = std::sync::Arc<std::sync::Mutex<crate::ssap_database::Database>>;
pub(crate) struct Engine {
    state: watch::Receiver<Status>,
    queries: mpsc::Sender<Query>,
    stop: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<()>>,
}
impl Engine {
    pub(crate) fn start(
        fd: OwnedFd,
        expected: (u16, u64, u64, u16),
        database: Store,
    ) -> io::Result<Self> {
        let fd = AsyncFd::new(fd)?;
        let (state_tx, state) = watch::channel(Status::Starting);
        let (stop, stopped) = oneshot::channel();
        let (queries, incoming) = mpsc::channel(8);
        let task = tokio::spawn(async move {
            if let Err(error) = run(fd, stopped, incoming, expected, &state_tx, database).await {
                state_tx.send_replace(Status::Failed(error.to_string()));
            } else {
                state_tx.send_replace(Status::Failed("SSAP actor stopped".into()));
            }
        });
        Ok(Self {
            state,
            queries,
            stop: Some(stop),
            task: Some(task),
        })
    }
    pub(crate) fn observer(&self) -> Observer {
        Observer {
            state: self.state.clone(),
            queries: self.queries.clone(),
        }
    }
    pub(crate) async fn stop(mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        if let Some(mut task) = self.task.take()
            && tokio::time::timeout(Duration::from_secs(1), &mut task)
                .await
                .is_err()
        {
            task.abort();
            let _ = task.await;
        }
    }
}
pub(crate) struct Observer {
    state: watch::Receiver<Status>,
    queries: mpsc::Sender<Query>,
}
impl Observer {
    async fn request(
        &self,
        bytes: Vec<u8>,
        deadline: Instant,
        minimum: u32,
    ) -> Result<Vec<u8>, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::Value {
                bytes,
                deadline,
                minimum,
                reply,
            })
            .map_err(|_| "SSAP request queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "SSAP discovery original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during discovery".to_string())?
    }
    pub(crate) async fn discover(
        self,
        uuid: Option<Vec<u8>>,
        kind: slk_protocol::ssap::discovery::FindKind,
    ) -> Result<Discovery, String> {
        use slk_protocol::ssap::discovery::{EntryClass, FindKind, FindRequest, decode_page};
        let deadline = Instant::now() + Duration::from_secs(5);
        let info = Observer {
            state: self.state.clone(),
            queries: self.queries.clone(),
        }
        .info()
        .await?;
        let mut entries = Vec::new();
        let mut trace = Vec::new();
        let mut ranges = vec![(kind, 1u16, 65535u16)];
        let hierarchy = uuid.is_none() && kind == FindKind::Primary;
        while let Some((kind, mut start, end)) = ranges.pop() {
            loop {
                if Instant::now() >= deadline || trace.len() >= 96 {
                    return Err("bounded discovery deadline/pages exceeded".into());
                }
                let request = FindRequest {
                    kind,
                    class: EntryClass::Mixed,
                    start,
                    end,
                    uuid: uuid.as_deref(),
                };
                let mut bytes = vec![0; 22];
                let n = request
                    .encode(info.5, &mut bytes)
                    .map_err(|e| format!("find request: {e:?}"))?;
                bytes.truncate(n);
                let raw = self.request(bytes.clone(), deadline, 0).await?;
                trace.push((bytes, raw.clone()));
                if let Ok(ValuePdu::Error {
                    request: op,
                    handle,
                    error,
                }) = ValuePdu::decode(info.5, &raw)
                {
                    if op != request.opcode() {
                        return Err("find error opcode mismatch".into());
                    }
                    if error == 11 && handle == start {
                        break;
                    }
                    return Err(format!("peer find error {error}"));
                }
                let page = decode_page(request, info.5, &raw)
                    .map_err(|e| format!("find response: {e:?}"))?;
                if entries.len() + page.len() > 80 {
                    return Err("remote database entry budget".into());
                }
                let next = if kind == FindKind::Primary {
                    page.last().unwrap().end
                } else {
                    page.last().unwrap().handle
                };
                if hierarchy && kind == FindKind::Primary {
                    for service in &page {
                        if service.members & 2 != 0 {
                            ranges.push((FindKind::Properties, service.handle, service.end));
                        }
                    }
                }
                entries.extend(page);
                if next == 65535 || next >= end {
                    break;
                }
                start = next + 1;
            }
        }
        entries.sort_by_key(|e| e.handle);
        if entries.windows(2).any(|v| v[0].handle == v[1].handle) {
            return Err("duplicate remote handle".into());
        }
        Ok((entries, trace))
    }
    /// One bounded, call-owned receive interest, not a remote CCC subscription.
    pub(crate) async fn incoming(
        self,
        handles: Vec<u16>,
        modes: u8,
        wait: Duration,
    ) -> Result<Incoming, String> {
        let deadline = Instant::now() + wait;
        let _ = Observer {
            state: self.state.clone(),
            queries: self.queries.clone(),
        }
        .info()
        .await?;
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::Incoming {
                handles,
                modes,
                deadline,
                reply,
            })
            .map_err(|_| "SSAP receive queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "SSAP local receive original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during receive".to_string())?
    }
    pub(crate) async fn read_uuid(
        self,
        start: u16,
        end: u16,
        data_type: u8,
        uuid: Vec<u8>,
        minimum: u32,
    ) -> Result<UuidValues, String> {
        let deadline = Instant::now() + Duration::from_secs(5);
        let info = Observer {
            state: self.state.clone(),
            queries: self.queries.clone(),
        }
        .info()
        .await?;
        let request = slk_protocol::ssap::read_uuid::Request {
            start,
            end,
            data_type,
            uuid: &uuid,
        };
        let mut bytes = vec![0; 23];
        let n = request
            .encode(info.5, &mut bytes)
            .map_err(|e| format!("read UUID request: {e:?}"))?;
        bytes.truncate(n);
        let raw = self.request(bytes.clone(), deadline, minimum).await?;
        let entries = slk_protocol::ssap::read_uuid::decode(info.5, &raw)
            .map_err(|e| format!("read UUID response: {e:?}"))?
            .into_iter()
            .map(|item| match item.value {
                Ok(v) => (item.handle, true, 0, v.to_vec()),
                Err(e) => (item.handle, false, e, vec![]),
            })
            .collect();
        Ok((entries, bytes, raw))
    }
    pub(crate) async fn value(
        self,
        handle: u16,
        value: Option<Vec<u8>>,
        minimum: u32,
    ) -> Result<Vec<u8>, String> {
        let deadline = Instant::now() + Duration::from_secs(5);
        let queries = self.queries.clone();
        let info = self.info().await?;
        let mut bytes = vec![0; usize::from(info.5)];
        let pdu = match &value {
            Some(value) => ValuePdu::Write {
                handle,
                data_type: 0,
                value,
                verify: true,
            },
            None => ValuePdu::Read {
                handle,
                data_type: 0,
            },
        };
        let len = pdu
            .encode(info.5, &mut bytes)
            .map_err(|e| format!("value codec: {e:?}"))?;
        bytes.truncate(len);
        let (reply, result) = oneshot::channel();
        queries
            .try_send(Query::Value {
                bytes,
                deadline,
                minimum,
                reply,
            })
            .map_err(|_| "SSAP request queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "SSAP value original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during value operation".to_string())?
    }
    /// Native metadata through the existing owned fd; no SSAP request or new
    /// binding. Cancellation/queueing preserve this original metadata deadline.
    pub(crate) async fn transport_status(
        &self,
        deadline: Instant,
    ) -> Result<slk_protocol::SleSessionTxStatus, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::TransportStatus { deadline, reply })
            .map_err(|_| "transport observation queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "transport observation original deadline".to_string())?
            .map_err(|_| "actor stopped during transport observation".to_string())?
    }
    pub(crate) async fn info(mut self) -> Result<Info, String> {
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let view = self.state.borrow().clone();
                match view {
                    Status::Negotiated(_) => break,
                    Status::Failed(error) => return Err(error),
                    Status::Starting => self
                        .state
                        .changed()
                        .await
                        .map_err(|_| "SSAP actor stopped".to_string())?,
                }
            }
            let (send, reply) = oneshot::channel();
            self.queries
                .try_send(Query::Info(send))
                .map_err(|_| "SSAP query queue unavailable/full".to_string())?;
            reply
                .await
                .map_err(|_| "SSAP actor stopped before authorization".to_string())?
        })
        .await
        .map_err(|_| "SSAP query original deadline".to_string())?
    }
}
impl Drop for Engine {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        // Fallback only; normal object retirement explicitly stops and joins.
        if let Some(task) = &self.task {
            task.abort();
        }
    }
}
#[derive(Clone, Copy)]
enum Purpose {
    Request,
    Response,
    Error,
    Client,
    ValueResponse,
}
struct IncomingWait {
    handles: Vec<u16>,
    modes: u8,
    deadline: Instant,
    reply: oneshot::Sender<Result<Incoming, String>>,
}
/// Actual actor delivery: one complete packet fits the call-owned oneshot slot.
/// ACK success means accepted into this application queue, not app validation.
fn incoming_packet(mtu: u16, raw: &[u8], waiter: &mut Option<IncomingWait>) -> io::Result<Vec<u8>> {
    use slk_protocol::ssap::updates::{Update, ack};
    let packet = Update::decode(mtu, raw)
        .map_err(|e| io::Error::other(format!("invalid/unsupported SSAP update: {e:?}")))?;
    let eligible = waiter.as_ref().is_some_and(|w| {
        !w.reply.is_closed()
            && Instant::now() < w.deadline
            && !packet.event
            && w.modes & if packet.indication { 2 } else { 1 } != 0
            && packet
                .items
                .iter()
                .all(|item| w.handles.contains(&item.handle))
    });
    let accepted = if eligible {
        let w = waiter.take().expect("eligible waiter");
        w.reply.send(Ok((packet.indication, raw.to_vec()))).is_ok()
    } else {
        false
    };
    if !packet.indication {
        return Ok(vec![]);
    }
    let flags = [u8::from(accepted); 64];
    let mut out = vec![0; 2 + packet.items.len()];
    let n = ack(mtu, packet.event, &flags[..packet.items.len()], &mut out)
        .map_err(|_| io::Error::other("SSAP ACK budget"))?;
    out.truncate(n);
    Ok(out)
}
struct ClientRequest {
    minimum: u32,
    epoch: Option<u64>,
    bytes: Vec<u8>,
    deadline: Instant,
    admitted: bool,
    reply: oneshot::Sender<Result<Vec<u8>, String>>,
}
struct Pending {
    bytes: Vec<u8>,
    deadline: Instant,
    purpose: Purpose,
    constraint: Option<slk_protocol::SleSendConstraint>,
}
struct ServerPacket {
    bytes: Vec<u8>,
    deadline: Instant,
    constraint: Option<slk_protocol::SleSendConstraint>,
    mtu: u16,
    level: u32,
    request_id: u64,
}
struct ServerDecision {
    packet: ServerPacket,
    approvals: Vec<crate::ssap_authorization::Approval>,
}
type ServerTask = std::pin::Pin<Box<dyn std::future::Future<Output = ServerDecision> + Send>>;

/// Only the front server obligation is polled, preserving response order.
/// No database/Host lock is held across a policy callback or a wait.
async fn authorize_server(packet: ServerPacket, database: Store) -> ServerDecision {
    let targets = if packet.bytes[0] == 10 {
        slk_protocol::ssap::read_uuid::Request::decode(packet.mtu, &packet.bytes)
            .ok()
            .map(|request| {
                database
                    .lock()
                    .map(|d| d.uuid_targets(request, packet.level))
                    .unwrap_or_default()
            })
            .unwrap_or_default()
    } else {
        ValuePdu::decode(packet.mtu, &packet.bytes)
            .ok()
            .map(|request| {
                database
                    .lock()
                    .map(|d| d.value_targets(request, packet.level))
                    .unwrap_or_default()
            })
            .unwrap_or_default()
    };
    let mut approvals = Vec::new();
    if let Some(c) = packet.constraint {
        let write = packet.bytes[0] == 13;
        let value = match ValuePdu::decode(packet.mtu, &packet.bytes) {
            Ok(ValuePdu::Write { value, .. }) => value.to_vec(),
            _ => vec![],
        };
        for target in targets {
            if Instant::now() >= packet.deadline {
                break;
            }
            let prompt = (
                packet.request_id,
                (
                    c.controller,
                    c.generation,
                    c.lifetime,
                    c.handle,
                    c.security_epoch,
                    packet.level,
                    c.local_tcid,
                    c.remote_tcid,
                    c.pi,
                ),
                target.handle,
                write,
                c.deadline_monotonic_ns,
                value.clone(),
            );
            if target.owner.authorize(prompt, packet.deadline).await {
                approvals.push(crate::ssap_authorization::Approval {
                    handle: target.handle,
                    owner: target.owner,
                });
            }
        }
    }
    ServerDecision { packet, approvals }
}

fn server_response(
    packet: &ServerPacket,
    database: &Store,
    approvals: &[crate::ssap_authorization::Approval],
) -> io::Result<Vec<u8>> {
    let raw = &packet.bytes;
    let negotiated = packet.mtu;
    if raw[0] == 10 {
        return match slk_protocol::ssap::read_uuid::Request::decode(negotiated, raw) {
            Ok(request) => {
                let database = database
                    .lock()
                    .map_err(|_| io::Error::other("database poisoned"))?;
                if approvals.is_empty() {
                    database.read_uuid(request, negotiated, packet.level)
                } else {
                    database.read_uuid_authorized(request, negotiated, packet.level, approvals)
                }
                .map_err(io::Error::other)
            }
            Err(_) => {
                let mut out = vec![0; 6];
                ValuePdu::Error {
                    request: 10,
                    handle: 0,
                    error: 1,
                }
                .encode(negotiated, &mut out)
                .map_err(|_| io::Error::other("read UUID error codec"))?;
                Ok(out)
            }
        };
    }
    if matches!(raw[0], 4 | 6) {
        return match slk_protocol::ssap::discovery::FindRequest::decode(negotiated, raw) {
            Ok(request) => database
                .lock()
                .map_err(|_| io::Error::other("database poisoned"))?
                .find(request, negotiated)
                .map_err(io::Error::other),
            Err(error) => {
                let mut out = vec![0; 6];
                let handle = if matches!(error, slk_protocol::ssap::discovery::FindError::Handle)
                    && raw.len() >= 4
                {
                    u16::from_le_bytes([raw[2], raw[3]])
                } else {
                    0
                };
                ValuePdu::Error {
                    request: raw[0],
                    handle,
                    error: match error {
                        slk_protocol::ssap::discovery::FindError::Handle => 4,
                        slk_protocol::ssap::discovery::FindError::Unsupported => 2,
                        _ => 1,
                    },
                }
                .encode(negotiated, &mut out)
                .map_err(|_| io::Error::other("find error codec"))?;
                Ok(out)
            }
        };
    }
    match ValuePdu::decode(negotiated, raw) {
        Ok(request) => {
            let mut database = database
                .lock()
                .map_err(|_| io::Error::other("database poisoned"))?;
            if approvals.is_empty() {
                database.answer(request, negotiated, packet.level)
            } else {
                database.answer_authorized(request, negotiated, packet.level, approvals)
            }
            .map_err(io::Error::other)
        }
        Err(e) => {
            let mut out = vec![0; 6];
            ValuePdu::Error {
                request: raw[0],
                handle: 0,
                error: if raw.get(1).is_some_and(|v| v & 3 != 3) {
                    16
                } else if matches!(e, slk_protocol::ssap::value::ValueError::Unsupported) {
                    2
                } else {
                    1
                },
            }
            .encode(negotiated, &mut out)
            .map_err(|_| io::Error::other("error response exceeds MTU"))?;
            Ok(out)
        }
    }
}
fn complete_server(wire: &Wire, decision: ServerDecision, database: &Store) -> io::Result<Pending> {
    if Instant::now() >= decision.packet.deadline {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "original SSAP authorization deadline",
        ));
    }
    if let Some(original) = decision.packet.constraint {
        // A recheck is an admission snapshot, not an atomic transaction across
        // kernel security state and the userspace database. Later revocation
        // can stop the original response; it cannot roll back a prior write.
        let now = wire
            .prepare(original.minimum, decision.packet.deadline)?
            .ok_or_else(|| io::Error::other("missing native authorization recheck"))?;
        if (
            now.controller,
            now.generation,
            now.lifetime,
            now.handle,
            now.security_epoch,
            now.local_tcid,
            now.remote_tcid,
            now.pi,
        ) != (
            original.controller,
            original.generation,
            original.lifetime,
            original.handle,
            original.security_epoch,
            original.local_tcid,
            original.remote_tcid,
            original.pi,
        ) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "SSAP original authorization context changed",
            ));
        }
    }
    let response = server_response(&decision.packet, database, &decision.approvals)?;
    Ok(Pending {
        bytes: response,
        deadline: decision.packet.deadline,
        purpose: Purpose::ValueResponse,
        constraint: decision.packet.constraint,
    })
}

// Native always checks actual kernel receipt facts. Local fixtures are explicit
// test-only transports, never a production fallback or fabricated security.
struct Wire {
    fd: AsyncFd<OwnedFd>,
    #[cfg(test)]
    fixture: bool,
}
impl Wire {
    fn native(fd: AsyncFd<OwnedFd>) -> Self {
        Self {
            fd,
            #[cfg(test)]
            fixture: false,
        }
    }
    #[cfg(test)]
    fn fixture(fd: AsyncFd<OwnedFd>) -> Self {
        Self { fd, fixture: true }
    }
    fn receive(
        &self,
        fd: &OwnedFd,
        bytes: &mut [u8],
        cap: SleChannelInfo,
    ) -> io::Result<(usize, Option<slk_protocol::SleMessageSecurity>)> {
        #[cfg(test)]
        if self.fixture {
            return receive_fixture(fd, bytes).map(|n| (n, None));
        }
        let (size, m, flags) = slk_channel::security::recv(
            fd.as_raw_fd(),
            bytes,
            nix::libc::MSG_DONTWAIT | nix::libc::MSG_TRUNC,
        )?;
        if size > bytes.len()
            || flags & nix::libc::MSG_TRUNC != 0
            || (
                m.controller,
                m.generation,
                m.lifetime,
                m.handle,
                m.local_tcid,
                m.remote_tcid,
                m.pi,
            ) != (
                cap.controller,
                cap.generation,
                cap.lifetime,
                cap.handle,
                cap.local_tcid,
                cap.remote_tcid,
                cap.pi,
            )
        {
            return Err(io::Error::other(
                "SSAP truncated or foreign receipt context",
            ));
        }
        if m.flags != 3 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "unknown/stale SSAP receipt mechanism",
            ));
        }
        Ok((size, Some(m)))
    }
    fn prepare(
        &self,
        minimum: u32,
        deadline: Instant,
    ) -> io::Result<Option<slk_protocol::SleSendConstraint>> {
        #[cfg(test)]
        if self.fixture {
            if minimum != 0 {
                return Err(io::Error::from_raw_os_error(nix::libc::EOPNOTSUPP));
            }
            return Ok(None);
        }
        slk_channel::security::prepare(
            self.fd.get_ref().as_raw_fd(),
            minimum,
            monotonic_deadline(deadline)?,
        )
        .map(Some)
    }
    fn send(&self, fd: &OwnedFd, packet: &Pending) -> io::Result<()> {
        #[cfg(test)]
        if self.fixture {
            return send(fd, &packet.bytes);
        }
        if let Some(c) = packet.constraint {
            let count = slk_channel::security::send(
                fd.as_raw_fd(),
                &packet.bytes,
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
                &c,
            )?;
            if count != packet.bytes.len() {
                return Err(io::Error::other("partial SSAP constrained admission"));
            }
            Ok(())
        } else {
            Err(io::Error::other("missing Native SSAP TX intent"))
        }
    }
}
fn monotonic_deadline(deadline: Instant) -> io::Result<u64> {
    slk_channel::security::deadline_at(deadline.into_std())
}
fn encode(kind: ExchangeKind, mtu: u16) -> io::Result<Vec<u8>> {
    let info = ExchangeInfo {
        kind,
        mtu: Some(mtu),
        version: Some([1, 2]),
        extension: None,
        reliable: false,
    };
    let mut bytes = [0; 10];
    let size = info
        .encode(mtu, &mut bytes)
        .map_err(|_| io::Error::other("invalid actual SMTC MTU"))?;
    Ok(bytes[..size].to_vec())
}
#[cfg(test)]
fn send(fd: &OwnedFd, bytes: &[u8]) -> io::Result<()> {
    let count = unsafe {
        nix::libc::send(
            fd.as_raw_fd(),
            bytes.as_ptr().cast(),
            bytes.len(),
            nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
        )
    };
    if count < 0 {
        return Err(io::Error::last_os_error());
    }
    if count != bytes.len() as isize {
        return Err(io::Error::other("partial SSAP datagram admission"));
    }
    Ok(()) // Software admission, never controller completion or peer receipt.
}
#[cfg(test)]
fn receive_fixture(fd: &OwnedFd, bytes: &mut [u8]) -> io::Result<usize> {
    let count = unsafe {
        nix::libc::recv(
            fd.as_raw_fd(),
            bytes.as_mut_ptr().cast(),
            bytes.len(),
            nix::libc::MSG_DONTWAIT | nix::libc::MSG_TRUNC,
        )
    };
    if count < 0 {
        return Err(io::Error::last_os_error());
    }
    if count as usize > bytes.len() {
        return Err(io::Error::other("oversized SSAP PDU"));
    }
    Ok(count as usize)
}
async fn run(
    fd: AsyncFd<OwnedFd>,
    mut stopped: oneshot::Receiver<()>,
    incoming: mpsc::Receiver<Query>,
    expected: (u16, u64, u64, u16),
    state: &watch::Sender<Status>,
    database: Store,
) -> io::Result<()> {
    let original_deadline = Instant::now() + Duration::from_secs(5);
    let capabilities = loop {
        tokio::select! {
            _ = &mut stopped => return Ok(()),
            _ = tokio::time::sleep_until(original_deadline) => return Err(io::Error::new(io::ErrorKind::TimedOut, "SMTC capability deadline")),
            ready = fd.writable() => {
                let mut ready = ready?;
                match ready.try_io(|fd| slk_channel::query(fd.get_ref().as_raw_fd())) {
                    Ok(info) => break info?, Err(_) => continue,
                }
            }
        }
    };
    if (
        capabilities.controller,
        capabilities.generation,
        capabilities.lifetime,
        capabilities.handle,
    ) != expected
    {
        return Err(io::Error::other(
            "SMTC controller/generation/lifetime mismatch",
        ));
    }
    if (
        capabilities.local_tcid,
        capabilities.remote_tcid,
        capabilities.pi,
        capabilities.directions,
    ) != (10, 10, 0, 3)
    {
        return Err(io::Error::other("SMTC binding identity mismatch"));
    }
    exchange_loop(
        Wire::native(fd),
        capabilities,
        original_deadline,
        &mut stopped,
        incoming,
        state,
        database,
    )
    .await
}
async fn exchange_loop(
    wire: Wire,
    capabilities: SleChannelInfo,
    original_deadline: Instant,
    stopped: &mut oneshot::Receiver<()>,
    mut incoming: mpsc::Receiver<Query>,
    state: &watch::Sender<Status>,
    database: Store,
) -> io::Result<()> {
    let request = encode(ExchangeKind::Request, capabilities.mtu)?;
    let response = encode(ExchangeKind::Response, capabilities.mtu)?;
    let mut pending = VecDeque::from([Pending {
        bytes: request.clone(),
        deadline: original_deadline,
        purpose: Purpose::Request,
        constraint: wire.prepare(0, original_deadline)?,
    }]);
    let mut request_admitted = false;
    let mut initial_done = false;
    let mut peer_reply: Option<(ExchangeInfo, Vec<u8>)> = None;
    let mut peer_request = Vec::new();
    let mut response_admitted = Vec::new();
    let mut client: Option<ClientRequest> = None;
    let mut incoming_wait: Option<IncomingWait> = None;
    let mut buffer = [0; 2042];
    let mut server_queue: VecDeque<ServerPacket> = VecDeque::new();
    let mut server: Option<(Instant, ServerTask)> = None;
    let mut next_server_id = 0u64;
    loop {
        if server.is_none()
            && let Some(packet) = server_queue.pop_front()
        {
            server = Some((
                packet.deadline,
                Box::pin(authorize_server(packet, database.clone())),
            ));
        }
        let server_load = server_queue.len() + usize::from(server.is_some());
        if incoming_wait
            .as_ref()
            .is_some_and(|w| w.reply.is_closed() || Instant::now() >= w.deadline)
            && let Some(w) = incoming_wait.take()
        {
            let _ = w
                .reply
                .send(Err("SSAP incoming cancelled/original deadline".into()));
        }
        let response_owed = pending
            .iter()
            .any(|p| matches!(p.purpose, Purpose::Response));
        if request_admitted
            && !response_owed
            && let Some((peer, raw)) = peer_reply.as_ref()
        {
            let mtu = capabilities.mtu.min(peer.mtu.unwrap_or(capabilities.mtu));
            let result = (
                capabilities.controller,
                capabilities.generation,
                capabilities.lifetime,
                capabilities.handle,
                capabilities.mtu,
                mtu,
                request.clone(),
                raw.clone(),
                peer_request.clone(),
                response_admitted.clone(),
            );
            state.send_replace(Status::Negotiated(result));
            initial_done = true;
        } else {
            state.send_replace(Status::Starting);
        }
        let debt_deadline = pending
            .iter()
            .map(|p| p.deadline)
            .chain(client.as_ref().map(|v| v.deadline))
            .chain(server.as_ref().map(|v| v.0))
            .chain(server_queue.iter().map(|v| v.deadline))
            .chain(
                incoming_wait
                    .as_ref()
                    .map(|w| w.deadline.min(Instant::now() + Duration::from_secs(1))),
            )
            .min();
        let tick = debt_deadline.unwrap_or_else(|| Instant::now() + Duration::from_secs(1));
        let deadline = if initial_done {
            tick
        } else {
            tick.min(original_deadline)
        };
        tokio::select! {
            _ = &mut *stopped => return Ok(()),
            _ = tokio::time::sleep_until(deadline) => {
                if (!initial_done && Instant::now() >= original_deadline) || pending.iter().any(|p| Instant::now() >= p.deadline) || client.as_ref().is_some_and(|v|Instant::now()>=v.deadline) || server.as_ref().is_some_and(|v|Instant::now()>=v.0) || server_queue.iter().any(|v|Instant::now()>=v.deadline) {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "original SSAP obligation deadline"));
                }
                slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
            }
            query = incoming.recv() => {
                let Some(query)=query else { return Ok(()); };
                if let Query::Incoming{handles,modes,deadline,reply}=query {
                    if reply.is_closed(){continue;}
                    if incoming_wait.is_some() || !initial_done || Instant::now()>=deadline || handles.is_empty() || handles.len()>32 || modes==0 || modes&!3!=0 || handles.contains(&0) || handles.iter().enumerate().any(|(i,h)|handles[..i].contains(h)) {let _=reply.send(Err("SSAP local receive busy/not-ready/invalid/expired".into()));continue;}
                    slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                    incoming_wait=Some(IncomingWait{handles,modes,deadline,reply});continue;
                }
                if let Query::Value{bytes,deadline,minimum,reply}=query {
                    if client.is_some() || pending.len()+server_load>=8 || !initial_done || Instant::now()>=deadline {let _=reply.send(Err("SSAP busy/not-ready/expired".into()));continue;}
                    slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                    if bytes.len()>usize::from(capabilities.mtu) {let _=reply.send(Err("SSAP request exceeds channel".into()));continue;}
                    if reply.is_closed(){continue;}
                    let constraint=match wire.prepare(minimum,deadline) {Ok(c)=>c,Err(e)=>{let _=reply.send(Err(format!("SSAP send intent refused: {e}")));continue;}};
                    let epoch=constraint.map(|c|c.security_epoch);
                    pending.push_back(Pending{bytes:bytes.clone(),deadline,purpose:Purpose::Client,constraint});client=Some(ClientRequest{bytes,deadline,minimum,epoch,admitted:false,reply});continue;
                }
                if let Query::TransportStatus{deadline,reply}=query {
                    if reply.is_closed() {continue;}
                    let result=if Instant::now()>=deadline {
                        Err("transport observation original deadline".into())
                    } else {
                        slk_channel::query_session_tx_status(wire.fd.get_ref().as_raw_fd())
                            .map_err(|error|error.to_string()).and_then(|current| {
                                if (current.controller,current.generation,current.lifetime,current.handle)
                                    != (capabilities.controller,capabilities.generation,capabilities.lifetime,capabilities.handle) {
                                    Err("transport observation lifetime changed".into())
                                } else {Ok(current)}
                            })
                    };
                    let _=reply.send(result);continue;
                }
                let Query::Info(reply)=query else {unreachable!()};
                let result=match state.borrow().clone() {
                    Status::Negotiated(info) => slk_channel::query(wire.fd.get_ref().as_raw_fd()).map_err(|e|e.to_string()).and_then(|current| {
                        if current != capabilities { Err("SMTC capability/lifetime changed".into()) } else { Ok(info) }
                    }),
                    Status::Starting => Err("SSAP response obligation pending".into()),
                    Status::Failed(error) => Err(error),
                };
                let _=reply.send(result);
            }
            decision = async { server.as_mut().expect("guarded server obligation").1.as_mut().await }, if server.is_some() => {
                server.take();
                pending.push_back(complete_server(&wire,decision,&database)?);
            }
            ready = wire.fd.writable(), if !pending.is_empty() => {
                let mut ready = ready?;
                let packet = pending.front().expect("guarded queue");
                if Instant::now() >= packet.deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "expired SSAP submit")); }
                if let Ok(result) = ready.try_io(|fd| wire.send(fd.get_ref(), packet)) {
                    result?;
                    let packet = pending.pop_front().expect("guarded queue");
                    match packet.purpose {
                        Purpose::Request => request_admitted = true,
                        Purpose::Response => response_admitted = packet.bytes,
                        Purpose::Error | Purpose::ValueResponse => {},
                        Purpose::Client => {if let Some(client)=&mut client {client.admitted=true;}}
                    }
                }
            }
            ready = wire.fd.readable() => {
                let mut ready = ready?;
                if let Ok(result) = ready.try_io(|fd| wire.receive(fd.get_ref(), &mut buffer, capabilities)) {
                    let (size, receipt) = result?;
                    let reply_deadline = if initial_done { Instant::now()+Duration::from_secs(5) } else { original_deadline };
                    let constraint = receipt.map(|m| slk_protocol::SleSendConstraint::from_receipt(m,m.security,
                        monotonic_deadline(reply_deadline)?)).transpose()?;
                    if size == 0 || size > usize::from(capabilities.mtu) { return Err(io::Error::other("invalid SSAP PDU length")); }
                    let raw = &buffer[..size];
                    if !initial_done && Instant::now() >= original_deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "late SSAP reply")); }
                    if matches!(raw[0],15|16) {
                        if raw[0]==16 && pending.len()+server_load>=8{return Err(io::Error::other("SSAP ACK queue full"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                        let ack=incoming_packet(negotiated,raw,&mut incoming_wait)?;
                        if !ack.is_empty(){pending.push_back(Pending{bytes:ack,deadline:Instant::now()+Duration::from_secs(5),purpose:Purpose::ValueResponse,constraint});}
                    } else if matches!(raw[0],4|6|8|10|13) {
                        if !initial_done {return Err(io::Error::other("SSAP value/discovery before ExchangeInfo completion"));}
                        if pending.len()+server_load>=8 {return Err(io::Error::other("SSAP response obligation queue full"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                        next_server_id=next_server_id.checked_add(1).ok_or_else(||io::Error::other("SSAP original request namespace exhausted"))?;
                        server_queue.push_back(ServerPacket {bytes:raw.to_vec(),deadline:reply_deadline,constraint,mtu:negotiated,level:receipt.map_or(0,|m|m.security),request_id:next_server_id});
                    } else if matches!(raw[0],1|5|7|9|11|14) {
                        let Some(ClientRequest{bytes:request,deadline,minimum,epoch,admitted,reply})=client.take() else {return Err(io::Error::other("unsolicited SSAP value reply"));};
                        if let Some(epoch)=epoch {
                            let m=receipt.ok_or_else(||io::Error::other("missing reply receipt"))?;
                            if m.security_epoch!=epoch || m.security<minimum{return Err(io::Error::other("SSAP reply differs from original request security intent"));}
                        }
                        if !admitted || Instant::now()>=deadline {return Err(io::Error::other("SSAP reply before submit or after original deadline"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        if request[0]==10 {
                            let r=slk_protocol::ssap::read_uuid::Request::decode(negotiated,&request).map_err(|_|io::Error::other("invalid local UUID request"))?;
                            if let Ok(ValuePdu::ReadError(16))=ValuePdu::decode(negotiated,raw){let _=reply.send(Err("peer requires unsupported SSAP fragmentation".into()));continue;}
                            if let Ok(ValuePdu::Error{request:10,error,..})=ValuePdu::decode(negotiated,raw){let _=reply.send(Err(format!("peer read UUID protocol error {error}")));continue;}
                            let entries=slk_protocol::ssap::read_uuid::decode(negotiated,raw).map_err(|_|io::Error::other("invalid read UUID response"))?;
                            if entries.iter().any(|i|i.handle<r.start || i.handle>r.end) {return Err(io::Error::other("read UUID response outside requested range"));}
                            let _=reply.send(Ok(raw.to_vec()));continue;
                        }
                        if matches!(request[0],4|6) {
                            let request=slk_protocol::ssap::discovery::FindRequest::decode(negotiated,&request).map_err(|_|io::Error::other("invalid local find request"))?;
                            if raw[0]==1 {match ValuePdu::decode(negotiated,raw) {Ok(ValuePdu::Error{request:op,..}) if op==request.opcode()=>{},_=>return Err(io::Error::other("invalid find error response"))}}
                            else {slk_protocol::ssap::discovery::decode_page(request,negotiated,raw).map_err(|_|io::Error::other("invalid find response"))?;}
                            let _=reply.send(Ok(raw.to_vec()));continue;
                        }
                        let parsed=ValuePdu::decode(negotiated,raw).map_err(|_|io::Error::other("invalid value response"))?;
                        let result=match (ValuePdu::decode(capabilities.mtu,&request).map_err(|_|io::Error::other("invalid local request"))?,parsed) {
                            (ValuePdu::Read{..},ValuePdu::ReadValue(value))=>Ok(value.to_vec()),
                            (ValuePdu::Read{..},ValuePdu::ReadError(error))=>Err(format!("peer read error {error}")),
                            (ValuePdu::Write{handle,data_type,value,verify:true},ValuePdu::WrittenValue{handle:h,data_type:t,value:v}) if (handle,data_type,value)==(h,t,v)=>Ok(v.to_vec()),
                            (ValuePdu::Write{handle,..},ValuePdu::WriteError{handle:h,error}) if handle==h=>Err(format!("peer write error {error}")),
                            (ValuePdu::Read{..},ValuePdu::Error{request:8,error,..})|(ValuePdu::Write{..},ValuePdu::Error{request:13,error,..})=>Err(format!("peer protocol error {error}")),
                            _=>return Err(io::Error::other("SSAP response does not match original operation")),
                        };let _=reply.send(result);
                    } else if raw[0] == 2 || raw[0] == 3 {
                        let info = match ExchangeInfo::decode(capabilities.mtu,raw) {
                            Ok(info)=>info,
                            Err(_) if raw[0]==2 => {
                                if pending.len()>=8 {return Err(io::Error::other("SSAP invalid-PDU response queue full"));}
                                pending.push_back(Pending {bytes:vec![1,0,2,0,0,1],purpose:Purpose::Error,constraint,deadline:Instant::now()+Duration::from_secs(5)});
                                continue;
                            }
                            Err(_)=>return Err(io::Error::other("invalid ExchangeInfo response")),
                        };
                        if info.kind == ExchangeKind::Response {
                            if !request_admitted || peer_reply.is_some() { return Err(io::Error::other("unsolicited/duplicate ExchangeInfo response")); }
                            if !peer_request.is_empty() && ExchangeInfo::decode(capabilities.mtu,&peer_request).map_err(|_|io::Error::other("invalid peer request"))?.mtu != info.mtu { return Err(io::Error::other("peer dual-role MTU mismatch")); }
                            peer_reply = Some((info, raw.to_vec()));
                        } else {
                            if response_owed || pending.len() >= 8 { return Err(io::Error::other("SSAP response queue full")); }
                            if let Some((peer,_)) = &peer_reply && peer.mtu != info.mtu { return Err(io::Error::other("peer dual-role MTU mismatch")); }
                            peer_request = raw.to_vec();
                            pending.push_back(Pending { bytes: response.clone(), purpose: Purpose::Response,constraint,
                                deadline: if initial_done { Instant::now() + Duration::from_secs(5) } else { original_deadline } });
                        }
                    } else if matches!(raw[0] & 0x7f, 4 | 6 | 8 | 10 | 13 | 19) {
                        if pending.len() >= 8 { return Err(io::Error::other("SSAP error queue full")); }
                        // T/XS20001 table50: complete ErrorRsp including RFU MCC.
                        pending.push_back(Pending { bytes: vec![1,0,raw[0],0,0,2], purpose: Purpose::Error,constraint,
                            deadline: Instant::now() + Duration::from_secs(5) });
                    } else if matches!(raw[0], 12 | 18) {
                        // Unsupported commands/notifications carry no response obligation.
                    } else { return Err(io::Error::other("unsupported or unmatched SSAP response")); }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn transport_pair() -> (OwnedFd, OwnedFd) {
        let (a, b) = std::os::unix::net::UnixDatagram::pair().unwrap();
        a.set_nonblocking(true).unwrap();
        b.set_nonblocking(true).unwrap();
        (a.into(), b.into())
    }
    fn fixture_capabilities(controller: u16) -> SleChannelInfo {
        SleChannelInfo {
            version: 1,
            size: 40,
            controller,
            generation: 1,
            lifetime: 1,
            mtu: 249,
            mps: 249,
            local_tcid: 10,
            remote_tcid: 10,
            directions: 3,
            ..Default::default()
        }
    }
    async fn negotiated(mut state: watch::Receiver<Status>) -> Info {
        tokio::time::timeout(Duration::from_secs(1), async {
            loop {
                let view = state.borrow().clone();
                if let Status::Negotiated(info) = view {
                    return info;
                }
                state.changed().await.unwrap();
            }
        })
        .await
        .unwrap()
    }
    #[tokio::test]
    async fn native_wire_never_accepts_local_fixture_as_security_context() {
        let (a, b) = transport_pair();
        send(&b, b"fixture-only").unwrap();
        let native = Wire::native(AsyncFd::new(a).unwrap());
        let mut bytes = [0u8; 64];
        assert_eq!(
            native
                .receive(native.fd.get_ref(), &mut bytes, fixture_capabilities(0))
                .unwrap_err()
                .raw_os_error(),
            Some(nix::libc::EAFNOSUPPORT)
        );
        let fixture = Wire::fixture(native.fd);
        let (count, context) = fixture
            .receive(fixture.fd.get_ref(), &mut bytes, fixture_capabilities(0))
            .unwrap();
        assert_eq!(&bytes[..count], b"fixture-only");
        assert!(context.is_none());
    }
    #[tokio::test]
    async fn actual_transport_algorithm_exchanges_both_roles_without_native_fallback() {
        // Explicit AF_UNIX dependencies: tests the production message loop,
        // not kernel binding, metadata, controller completion or radio.
        let (a, b) = transport_pair();
        let (s0, r0) = watch::channel(Status::Starting);
        let (s1, r1) = watch::channel(Status::Starting);
        let (stop0, mut done0) = oneshot::channel();
        let (stop1, mut done1) = oneshot::channel();
        let (q0, in0) = mpsc::channel(8);
        let (_q1, in1) = mpsc::channel(8);
        let state0 = r0.clone();
        let deadline = Instant::now() + Duration::from_secs(1);
        let task0 = tokio::spawn(async move {
            exchange_loop(
                Wire::fixture(AsyncFd::new(a).unwrap()),
                fixture_capabilities(0),
                deadline,
                &mut done0,
                in0,
                &s0,
                std::sync::Arc::new(std::sync::Mutex::new(
                    crate::ssap_database::Database::default(),
                )),
            )
            .await
        });
        let task1 = tokio::spawn(async move {
            exchange_loop(
                Wire::fixture(AsyncFd::new(b).unwrap()),
                fixture_capabilities(1),
                deadline,
                &mut done1,
                in1,
                &s1,
                std::sync::Arc::new(std::sync::Mutex::new(
                    crate::ssap_database::Database::default(),
                )),
            )
            .await
        });
        for info in [negotiated(r0).await, negotiated(r1).await] {
            assert_eq!(info.4, 249);
            assert_eq!(info.5, 249);
            assert_eq!(info.6, [2, 3, 249, 0, 1, 2]);
            assert_eq!(info.7, [3, 3, 249, 0, 1, 2]);
            assert_eq!(info.8, [2, 3, 249, 0, 1, 2]);
            assert_eq!(info.9, [3, 3, 249, 0, 1, 2]);
        }
        let observer = Observer {
            state: state0,
            queries: q0,
        };
        assert!(
            observer
                .transport_status(Instant::now() + Duration::from_secs(1))
                .await
                .unwrap_err()
                .contains("25")
        );
        assert!(observer.info().await.unwrap_err().contains("25")); // AF_UNIX is not Native.
        stop0.send(()).unwrap();
        stop1.send(()).unwrap();
        task0.await.unwrap().unwrap();
        task1.await.unwrap().unwrap();
    }
    #[test]
    fn actual_incoming_queue_rejects_closed_unknown_event_and_expired_waits() {
        fn wait(
            handles: Vec<u16>,
            modes: u8,
        ) -> (
            Option<IncomingWait>,
            oneshot::Receiver<Result<Incoming, String>>,
        ) {
            let (reply, rx) = oneshot::channel();
            (
                Some(IncomingWait {
                    handles,
                    modes,
                    deadline: Instant::now() + Duration::from_secs(1),
                    reply,
                }),
                rx,
            )
        }
        let indication = [16, 3, 17, 0, 2, 0, 7, 8];
        let notification = [15, 3, 17, 0, 2, 0, 7, 8];
        let (mut w, mut rx) = wait(vec![17], 2);
        assert_eq!(
            incoming_packet(249, &indication, &mut w).unwrap(),
            [17, 3, 1]
        );
        assert_eq!(rx.try_recv().unwrap().unwrap(), (true, indication.to_vec()));
        assert!(w.is_none());
        let (mut w, rx) = wait(vec![17], 2);
        drop(rx);
        assert_eq!(
            incoming_packet(249, &indication, &mut w).unwrap(),
            [17, 3, 0]
        );
        let (mut w, _rx) = wait(vec![18], 2);
        assert_eq!(
            incoming_packet(249, &indication, &mut w).unwrap(),
            [17, 3, 0]
        );
        assert!(w.is_some());
        let (mut w, _rx) = wait(vec![17], 1);
        assert_eq!(
            incoming_packet(249, &indication, &mut w).unwrap(),
            [17, 3, 0]
        );
        assert!(w.is_some());
        w.as_mut().unwrap().deadline = Instant::now() - Duration::from_millis(1);
        assert!(
            incoming_packet(249, &notification, &mut w)
                .unwrap()
                .is_empty()
        );
        assert!(w.is_some());
        let (mut w, mut rx) = wait(vec![17], 1);
        assert!(
            incoming_packet(249, &notification, &mut w)
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            rx.try_recv().unwrap().unwrap(),
            (false, notification.to_vec())
        );
        let (mut w, _rx) = wait(vec![17], 2);
        let mut event = indication;
        event[1] = 7;
        assert_eq!(incoming_packet(249, &event, &mut w).unwrap(), [17, 7, 0]);
        assert!(w.is_some());
        let (mut w, _rx) = wait(vec![17], 2);
        assert!(incoming_packet(249, &indication[..7], &mut w).is_err());
        assert!(w.is_some());
        assert_eq!(
            incoming_packet(249, &indication, &mut None).unwrap(),
            [17, 3, 0]
        );
    }
    #[tokio::test]
    async fn absent_peer_response_hits_original_deadline_and_joins() {
        let (a, _peer) = transport_pair();
        let (tx, _rx) = watch::channel(Status::Starting);
        let (_stop, mut done) = oneshot::channel();
        let (_queries, incoming) = mpsc::channel(8);
        let error = exchange_loop(
            Wire::fixture(AsyncFd::new(a).unwrap()),
            fixture_capabilities(0),
            Instant::now() + Duration::from_millis(30),
            &mut done,
            incoming,
            &tx,
            std::sync::Arc::new(std::sync::Mutex::new(
                crate::ssap_database::Database::default(),
            )),
        )
        .await
        .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    }
}

#[cfg(test)]
#[path = "ssap_authorization_tests.rs"]
mod authorization_tests;
