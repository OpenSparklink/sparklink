//! Single lifetime-scoped SMTC owner: initial ExchangeInfo and bounded
//! single-value requests. No synthetic replies, security projection, reliable
//! mode or complete service-discovery claim. Value fragments are bounded and
//! require negotiated sequence support; a partial-stream error retires the actor.
use slk_protocol::{
    SleChannelInfo,
    ssap::{
        exchange::{ExchangeInfo, ExchangeKind, ExtensionCapabilities},
        fragments,
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

pub(crate) use slk_contract::ssap::Incoming;
pub(crate) use slk_contract::ssap::UuidValues;
pub(crate) type Discovery = (
    Vec<slk_protocol::ssap::discovery::Entry>,
    Vec<(Vec<u8>, Vec<u8>)>,
);
pub(crate) use slk_contract::ssap::ExchangeInfo as Info;
#[derive(Clone, Debug)]
enum Status {
    Starting,
    Negotiated(Info),
    Failed(String),
}
enum Query {
    Subscribe {
        owner: crate::ssap_subscription::CallerLease,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        deadline: Instant,
        reply: oneshot::Sender<Result<slk_contract::ssap::subscription::Info, String>>,
    },
    SubscriptionRead {
        caller: String,
        token: u64,
        wait: bool,
        deadline: Instant,
        reply: oneshot::Sender<Result<slk_contract::ssap::subscription::Batch, String>>,
    },
    SubscriptionRenew {
        caller: String,
        token: u64,
        duration_ms: u32,
        deadline: Instant,
        reply: oneshot::Sender<Result<slk_contract::ssap::subscription::Info, String>>,
    },
    SubscriptionClose {
        caller: String,
        token: u64,
        deadline: Instant,
        reply: oneshot::Sender<Result<slk_contract::ssap::subscription::Batch, String>>,
    },
    Update {
        caller: String,
        handle: u16,
        indication: bool,
        deadline: Instant,
        reply: oneshot::Sender<Result<slk_contract::ssap::UpdateReceipt, String>>,
    },
    Configuration {
        caller: String,
        handle: u16,
        deadline: Instant,
        reply: oneshot::Sender<Result<u8, String>>,
    },
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
        reply: oneshot::Sender<Result<Vec<u8>, ClientFailure>>,
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
    #[cfg(test)]
    pub(crate) fn task_fixture(task: JoinHandle<()>) -> Self {
        // A controlled real task/OS-fd join, not a successful wire backend.
        let (_, state) = watch::channel(Status::Starting);
        let (queries, _) = mpsc::channel(8);
        Self {
            state,
            queries,
            stop: None,
            task: Some(task),
        }
    }

    pub(crate) fn start(
        fd: OwnedFd,
        expected: (u16, u64, u64, u16),
        database: Store,
        original_deadline: Instant,
    ) -> io::Result<Self> {
        if Instant::now() >= original_deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "SSAP initialization original deadline",
            ));
        }
        let fd = AsyncFd::new(fd)?;
        let (state_tx, state) = watch::channel(Status::Starting);
        let (stop, stopped) = oneshot::channel();
        let (queries, incoming) = mpsc::channel(8);
        let task = tokio::spawn(async move {
            if let Err(error) = run(
                fd,
                stopped,
                incoming,
                expected,
                &state_tx,
                database,
                original_deadline,
            )
            .await
            {
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
    pub(crate) async fn stop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        if let Some(task) = self.task.as_mut()
            && tokio::time::timeout(Duration::from_secs(1), &mut *task)
                .await
                .is_err()
        {
            task.abort();
            let _ = task.await;
        }
        // Keep the handle in its owner across every suspension above. A
        // cancelled stop waiter leaves the same task available for joining.
        self.task = None;
    }
}
pub(crate) struct Observer {
    state: watch::Receiver<Status>,
    queries: mpsc::Sender<Query>,
}
impl Observer {
    pub(crate) async fn subscribe(
        &self,
        owner: crate::ssap_subscription::CallerLease,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        deadline: Instant,
    ) -> Result<slk_contract::ssap::subscription::Info, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::Subscribe {
                owner,
                handles,
                modes,
                duration_ms,
                deadline,
                reply,
            })
            .map_err(|_| "subscription command queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "subscription original creation deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during subscription".to_string())?
    }
    pub(crate) async fn subscription_read(
        &self,
        caller: String,
        token: u64,
        wait: bool,
        deadline: Instant,
    ) -> Result<slk_contract::ssap::subscription::Batch, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::SubscriptionRead {
                caller,
                token,
                wait,
                deadline,
                reply,
            })
            .map_err(|_| "subscription read command queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "subscription read original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during subscription read".to_string())?
    }
    pub(crate) async fn subscription_renew(
        &self,
        caller: String,
        token: u64,
        duration_ms: u32,
        deadline: Instant,
    ) -> Result<slk_contract::ssap::subscription::Info, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::SubscriptionRenew {
                caller,
                token,
                duration_ms,
                deadline,
                reply,
            })
            .map_err(|_| "subscription renewal command queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "subscription renewal original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during subscription renewal".to_string())?
    }
    pub(crate) async fn subscription_close(
        &self,
        caller: String,
        token: u64,
        deadline: Instant,
    ) -> Result<slk_contract::ssap::subscription::Batch, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::SubscriptionClose {
                caller,
                token,
                deadline,
                reply,
            })
            .map_err(|_| "subscription close command queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "subscription close original deadline;cleanup may continue".to_string())?
            .map_err(|_| "SSAP actor stopped during subscription close".to_string())?
    }
    pub(crate) async fn update(
        &self,
        caller: String,
        handle: u16,
        indication: bool,
        deadline: Instant,
    ) -> Result<slk_contract::ssap::UpdateReceipt, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::Update {
                caller,
                handle,
                indication,
                deadline,
                reply,
            })
            .map_err(|_| "SSAP update queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "SSAP update original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during update".to_string())?
    }
    pub(crate) async fn configuration(
        &self,
        caller: String,
        handle: u16,
        deadline: Instant,
    ) -> Result<u8, String> {
        let (reply, result) = oneshot::channel();
        self.queries
            .try_send(Query::Configuration {
                caller,
                handle,
                deadline,
                reply,
            })
            .map_err(|_| "SSAP configuration observation queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "SSAP configuration observation original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during observation".to_string())?
    }
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
            .map_err(|error| error.to_string())
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
    /// One bounded receive transaction: baseline, enable, receive, disable.
    pub(crate) async fn incoming(
        self,
        handles: Vec<u16>,
        modes: u8,
        deadline: Instant,
    ) -> Result<Incoming, String> {
        let _ = tokio::time::timeout_at(
            deadline,
            Observer {
                state: self.state.clone(),
                queries: self.queries.clone(),
            }
            .info(),
        )
        .await
        .map_err(|_| "SSAP receive original deadline".to_string())??;
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
            .encode(value_budget(&info), &mut bytes)
            .map_err(|e| format!("read UUID request: {e:?}"))?;
        bytes.truncate(n);
        let raw = self.request(bytes.clone(), deadline, minimum).await?;
        let entries = slk_protocol::ssap::read_uuid::decode(value_budget(&info), &raw)
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
        deadline: Instant,
    ) -> Result<Vec<u8>, String> {
        if Instant::now() >= deadline {
            return Err("SSAP value original deadline".into());
        }
        let queries = self.queries.clone();
        let info = tokio::time::timeout_at(deadline, self.info())
            .await
            .map_err(|_| "SSAP value original deadline".to_string())??;
        let mut bytes = vec![0; usize::from(value_budget(&info))];
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
            .encode(value_budget(&info), &mut bytes)
            .map_err(|e| format!("value codec: {e:?}"))?;
        bytes.truncate(len);
        if Instant::now() >= deadline {
            return Err("SSAP value original deadline".into());
        }
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
            .map_err(|error| error.to_string())
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
    Update,
}
struct UpdateRequest {
    submitted_all: bool,
    handle: u16,
    owner: std::sync::Arc<crate::ssap_authorization::Owner>,
    mode: u8,
    epoch: u64,
    deadline: Instant,
    drain: Option<Instant>,
    pdu: Vec<u8>,
    reply: Option<oneshot::Sender<Result<slk_contract::ssap::UpdateReceipt, String>>>,
}
impl UpdateRequest {
    fn needs_withdrawal_watch(&self) -> bool {
        self.reply.is_some() || !self.submitted_all
    }
    async fn withdrawn(&mut self) {
        let Some(reply) = self.reply.as_mut() else {
            // The author is gone, but an unfinished stream still has an
            // owner. Its later revocation must wake the same actor too.
            return self.owner.withdrawn().await;
        };
        tokio::select! {
            _ = self.owner.withdrawn() => {},
            _ = reply.closed() => {},
        }
    }
    fn admit_part(&mut self, now: Instant, last: bool) {
        self.drain.get_or_insert(now + Duration::from_secs(5));
        self.submitted_all = last;
    }
    fn obligation_deadline(&self) -> Instant {
        self.drain.map_or(self.deadline, |drain| {
            if self.reply.as_ref().is_some_and(|r| !r.is_closed()) {
                drain.min(self.deadline)
            } else {
                drain
            }
        })
    }
}
fn retire_update_wait(
    update: &mut Option<UpdateRequest>,
    pending: &mut VecDeque<Pending>,
    now: Instant,
) {
    let Some(current) = update.as_mut() else {
        return;
    };
    if current.owner.current()
        && now < current.deadline
        && current.reply.as_ref().is_some_and(|r| !r.is_closed())
    {
        return;
    }
    if let Some(reply) = current.reply.take() {
        let _ = reply.send(Err(
            "SSAP update owner/caller retired or original deadline".into()
        ));
    }
    if current.drain.is_none() {
        pending.retain(|p| !matches!(p.purpose, Purpose::Update));
        *update = None;
    }
}
fn retire_update_event(
    update: &mut Option<UpdateRequest>,
    pending: &mut VecDeque<Pending>,
    now: Instant,
) -> io::Result<()> {
    retire_update_wait(update, pending, now);
    if update
        .as_ref()
        .is_some_and(|v| !v.owner.current() && v.drain.is_some() && !v.submitted_all)
    {
        return Err(io::Error::other(
            "partial update owner withdrawn;retire SSAP actor",
        ));
    }
    Ok(())
}
pub(super) enum IncomingDelivery {
    Once(oneshot::Sender<Result<Incoming, String>>),
    Stream(crate::ssap_subscription::Sink),
}
impl From<oneshot::Sender<Result<Incoming, String>>> for IncomingDelivery {
    fn from(value: oneshot::Sender<Result<Incoming, String>>) -> Self {
        Self::Once(value)
    }
}
impl IncomingDelivery {
    fn is_closed(&self) -> bool {
        match self {
            Self::Once(reply) => reply.is_closed(),
            Self::Stream(sink) => {
                !*sink.alive.borrow() || sink.queue.lock().map_or(true, |q| q.is_closing())
            }
        }
    }
    pub(super) fn send(
        self,
        value: Result<Incoming, String>,
    ) -> Result<(), Result<Incoming, String>> {
        match self {
            Self::Once(reply) => reply.send(value),
            Self::Stream(_) => Err(value),
        }
    }
}
pub(super) struct IncomingWait {
    pub(super) handles: Vec<u16>,
    pub(super) modes: u8,
    pub(super) deadline: Instant,
    pub(super) reply: IncomingDelivery,
}
/// Actual actor delivery: one complete packet fits the call-owned oneshot slot.
/// ACK success means accepted into this application queue, not app validation.
fn incoming_packet(
    mtu: u16,
    logical_budget: u16,
    raw: &[u8],
    receipt: Option<slk_protocol::SleMessageSecurity>,
    waiter: &mut Option<IncomingWait>,
) -> io::Result<Vec<u8>> {
    use slk_protocol::ssap::updates::{Update, ack};
    let packet = Update::decode(logical_budget, raw)
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
        if let IncomingDelivery::Stream(sink) = &waiter.as_ref().expect("eligible waiter").reply {
            sink.offer((packet.indication, raw.to_vec()), receipt, Instant::now())
                .map_err(io::Error::other)?
        } else {
            let w = waiter.take().expect("eligible waiter");
            w.reply.send(Ok((packet.indication, raw.to_vec()))).is_ok()
        }
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
/// Retain a correlated peer result until its owning transaction handles it.
/// A diagnostic string,even one resembling a peer error,is not this evidence.
/// This classification grants no identity,security,credit or native authority.
#[derive(Debug, PartialEq, Eq)]
pub(super) enum ClientFailure {
    Message(String),
    WriteError { handle: u16, error: u8 },
}
impl std::fmt::Display for ClientFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Message(message) => f.write_str(message),
            Self::WriteError { error, .. } => write!(f, "peer write error {error}"),
        }
    }
}
impl From<String> for ClientFailure {
    fn from(value: String) -> Self {
        Self::Message(value)
    }
}
impl From<&str> for ClientFailure {
    fn from(value: &str) -> Self {
        Self::Message(value.into())
    }
}

fn client_value_response(
    budget: u16,
    request: &[u8],
    raw: &[u8],
) -> io::Result<Result<Vec<u8>, ClientFailure>> {
    let request =
        ValuePdu::decode(budget, request).map_err(|_| io::Error::other("invalid local request"))?;
    let parsed =
        ValuePdu::decode(budget, raw).map_err(|_| io::Error::other("invalid value response"))?;
    Ok(match (request, parsed) {
        (ValuePdu::Read { .. }, ValuePdu::ReadValue(value)) => Ok(value.to_vec()),
        (ValuePdu::Read { .. }, ValuePdu::ReadError(error)) => {
            Err(format!("peer read error {error}").into())
        }
        (
            ValuePdu::Write {
                handle,
                data_type,
                value,
                verify: true,
            },
            ValuePdu::WrittenValue {
                handle: h,
                data_type: t,
                value: v,
            },
        ) if (handle, data_type, value) == (h, t, v) => Ok(v.to_vec()),
        (ValuePdu::Write { handle, .. }, ValuePdu::WriteError { handle: h, error })
            if handle == h =>
        {
            Err(ClientFailure::WriteError { handle, error })
        }
        (
            ValuePdu::Read { .. },
            ValuePdu::Error {
                request: 8, error, ..
            },
        )
        | (
            ValuePdu::Write { .. },
            ValuePdu::Error {
                request: 13, error, ..
            },
        ) => Err(format!("peer protocol error {error}").into()),
        _ => {
            return Err(io::Error::other(
                "SSAP response does not match original operation",
            ));
        }
    })
}

struct ClientRequest {
    minimum: u32,
    epoch: Option<u64>,
    bytes: Vec<u8>,
    deadline: Instant,
    admitted: bool,
    submitted_all: bool,
    // Starts once at software admission, when physical submission is possible.
    // This is a drain bound, never a renewed author/admission/TX deadline.
    cleanup_deadline: Option<Instant>,
    reply: Option<oneshot::Sender<Result<Vec<u8>, ClientFailure>>>,
}
impl ClientRequest {
    /// A response cannot discharge a partially admitted stream or a stale
    /// physical obligation. Native validates receipt lifetime before this
    /// actor-level check; this does not authenticate a caller-provided receipt.
    fn validate_reply(
        &self,
        receipt: Option<slk_protocol::SleMessageSecurity>,
        now: Instant,
    ) -> io::Result<()> {
        if let Some(epoch) = self.epoch {
            let m = receipt.ok_or_else(|| io::Error::other("missing reply receipt"))?;
            if m.security_epoch != epoch || m.security < self.minimum {
                return Err(io::Error::other(
                    "SSAP reply differs from original request security intent",
                ));
            }
        }
        if !self.admitted || !self.submitted_all || self.cleanup_deadline.is_none_or(|at| now >= at)
        {
            return Err(io::Error::other(
                "SSAP reply before admission or after physical drain deadline",
            ));
        }
        Ok(())
    }
    fn admit_part(&mut self, now: Instant, last: bool) {
        if !self.admitted {
            self.admitted = true;
            self.cleanup_deadline = Some(now + Duration::from_secs(5));
        }
        self.submitted_all = last;
    }
    fn obligation_deadline(&self) -> Instant {
        if self.admitted {
            let physical = self
                .cleanup_deadline
                .expect("admitted request owns drain deadline");
            if self.reply.as_ref().is_some_and(|r| !r.is_closed()) {
                physical.min(self.deadline)
            } else {
                physical
            }
        } else {
            self.deadline
        }
    }
}
fn finish_client(
    reply: Option<oneshot::Sender<Result<Vec<u8>, ClientFailure>>>,
    result: Result<Vec<u8>, ClientFailure>,
) {
    if let Some(reply) = reply {
        let _ = reply.send(result);
    }
}
/// Only this actor mutates its pending queue. Unsubmitted work can be removed;
/// admitted work retains its frozen request/security identity until a matching
/// reply or bounded wire retirement. No refund or successful late result.
fn retire_client_wait(
    client: &mut Option<ClientRequest>,
    pending: &mut VecDeque<Pending>,
    now: Instant,
) {
    let Some(current) = client.as_mut() else {
        return;
    };
    if now < current.deadline && current.reply.as_ref().is_some_and(|r| !r.is_closed()) {
        return;
    }
    if current.admitted {
        finish_client(
            current.reply.take(),
            Err("SSAP caller cancelled/original deadline".into()),
        );
    } else {
        let current = client.take().expect("current request");
        pending.retain(|p| !matches!(p.purpose, Purpose::Client));
        finish_client(
            current.reply,
            Err("SSAP caller cancelled/original deadline before admission".into()),
        );
    }
}
struct Pending {
    sent: usize,
    bytes: Vec<u8>,
    deadline: Instant,
    purpose: Purpose,
    constraint: Option<slk_protocol::SleSendConstraint>,
}
struct ClientAdmission<'a> {
    wire: &'a Wire,
    client: &'a mut Option<ClientRequest>,
    pending: &'a mut VecDeque<Pending>,
    response_load: usize,
    ready: bool,
    mtu: u16,
}
impl ClientAdmission<'_> {
    fn begin(
        self,
        bytes: Vec<u8>,
        deadline: Instant,
        minimum: u32,
        reply: oneshot::Sender<Result<Vec<u8>, ClientFailure>>,
    ) -> bool {
        let Self {
            wire,
            client,
            pending,
            response_load: load,
            ready,
            mtu,
        } = self;
        if reply.is_closed() {
            return false;
        }
        if client.is_some()
            || pending.len() + load >= 8
            || !ready
            || Instant::now() >= deadline
            || bytes.len() > usize::from(mtu)
        {
            let _ = reply.send(Err("SSAP busy/not-ready/expired/oversize".into()));
            return false;
        }
        let prepared = slk_channel::query(wire.fd.get_ref().as_raw_fd())
            .and_then(|_| wire.prepare(minimum, deadline));
        let constraint = match prepared {
            Ok(c) => c,
            Err(e) => {
                let _ = reply.send(Err(format!("SSAP send intent refused: {e}").into()));
                return false;
            }
        };
        let epoch = constraint.map(|c| c.security_epoch);
        pending.push_back(Pending {
            sent: 0,
            bytes: bytes.clone(),
            deadline,
            purpose: Purpose::Client,
            constraint,
        });
        *client = Some(ClientRequest {
            bytes,
            deadline,
            minimum,
            epoch,
            admitted: false,
            submitted_all: false,
            cleanup_deadline: None,
            reply: Some(reply),
        });
        true
    }
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
                target.data_type,
            );
            if target.owner.authorize(prompt, packet.deadline).await {
                approvals.push(crate::ssap_authorization::Approval {
                    handle: target.handle,
                    data_type: target.data_type,
                    write,
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
    configurations: &mut crate::ssap_engine_config::ClientConfigurations,
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
            if matches!(
                request,
                ValuePdu::Read { data_type: 2, .. } | ValuePdu::Write { data_type: 2, .. }
            ) {
                return database
                    .answer_configuration(
                        request,
                        negotiated,
                        packet.level,
                        packet.constraint.map(|c| c.security_epoch),
                        approvals,
                        configurations,
                    )
                    .map_err(io::Error::other);
            }
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
fn complete_server(
    wire: &Wire,
    decision: ServerDecision,
    database: &Store,
    configurations: &mut crate::ssap_engine_config::ClientConfigurations,
) -> io::Result<Pending> {
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
    let response = server_response(
        &decision.packet,
        database,
        &decision.approvals,
        configurations,
    )?;
    Ok(Pending {
        sent: 0,
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
    fn send(&self, fd: &OwnedFd, packet: &Pending, bytes: &[u8]) -> io::Result<()> {
        #[cfg(test)]
        if self.fixture {
            return send(fd, bytes);
        }
        if let Some(c) = packet.constraint {
            let count = slk_channel::security::send(
                fd.as_raw_fd(),
                bytes,
                nix::libc::MSG_DONTWAIT | nix::libc::MSG_NOSIGNAL,
                &c,
            )?;
            if count != bytes.len() {
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
fn sequenced(info: &ExchangeInfo) -> bool {
    info.extension.is_some_and(|e| e.fragment_sequence)
}
fn accepts_extended(info: &ExchangeInfo, control: u8) -> bool {
    info.extension
        .is_some_and(|e| control & 3 == 3 || e.fragment_sequence)
}
fn value_budget(info: &Info) -> u16 {
    if ExchangeInfo::decode(info.4, &info.7).is_ok_and(|p| sequenced(&p)) {
        fragments::LOGICAL_MTU
    } else {
        info.5
    }
}
fn encode(kind: ExchangeKind, mtu: u16) -> io::Result<Vec<u8>> {
    let info = ExchangeInfo {
        kind,
        mtu: Some(mtu),
        version: Some([1, 2]),
        extension: Some(ExtensionCapabilities {
            fragment_sequence: true,
            transaction_capacity: None,
        }),
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
    original_deadline: Instant,
) -> io::Result<()> {
    if Instant::now() >= original_deadline {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "SSAP initialization original deadline",
        ));
    }
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
        sent: 0,
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
    let mut assemblies: [fragments::Reassembly<Option<slk_protocol::SleMessageSecurity>, Instant>;
        3] = std::array::from_fn(|_| fragments::Reassembly::default());
    let mut server_queue: VecDeque<ServerPacket> = VecDeque::new();
    let mut server: Option<(Instant, ServerTask)> = None;
    let mut next_server_id = 0u64;
    let mut configurations = crate::ssap_engine_config::ClientConfigurations::default();
    let mut update: Option<UpdateRequest> = None;
    let mut receive: Option<crate::ssap_receive_transaction::ReceiveTransaction> = None;
    let mut last_subscription: Option<crate::ssap_subscription::Closed> = None;
    let mut next_subscription = 1u64;
    loop {
        retire_client_wait(&mut client, &mut pending, Instant::now());
        retire_update_wait(&mut update, &mut pending, Instant::now());
        if let Some(current) = receive.as_mut() {
            current
                .maintain(&mut incoming_wait, Instant::now())
                .map_err(io::Error::other)?;
            retire_client_wait(&mut client, &mut pending, Instant::now());
            if current.finished() && client.is_none() {
                if let Some(closed) = receive.take().expect("finished transaction").finish() {
                    last_subscription = Some(closed);
                }
            } else if client.is_none()
                && let Some((handle, value, deadline)) = current.next(&mut incoming_wait)
            {
                let mtu = capabilities.mtu.min(
                    peer_reply
                        .as_ref()
                        .and_then(|(p, _)| p.mtu)
                        .unwrap_or(capabilities.mtu),
                );
                let packet = match &value {
                    Some(value) => ValuePdu::Write {
                        handle,
                        data_type: 2,
                        value,
                        verify: true,
                    },
                    None => ValuePdu::Read {
                        handle,
                        data_type: 2,
                    },
                };
                let mut raw = vec![0; usize::from(mtu)];
                let n = packet
                    .encode(mtu, &mut raw)
                    .map_err(|e| io::Error::other(format!("configuration request codec: {e:?}")))?;
                raw.truncate(n);
                let (reply, result) = oneshot::channel();
                let load = server_queue.len() + usize::from(server.is_some());
                let admitted = ClientAdmission {
                    wire: &wire,
                    client: &mut client,
                    pending: &mut pending,
                    response_load: load,
                    ready: initial_done,
                    mtu,
                }
                .begin(raw, deadline, 2, reply);
                if admitted
                    && let Some(expected) = current.expected_epoch()
                    && client.as_ref().and_then(|c| c.epoch) != Some(expected)
                {
                    return Err(io::Error::other(
                        "subscription original security changed before configuration admission",
                    ));
                }
                current.submitted(handle, result, admitted);
            }
        }
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
            .chain(assemblies.iter().filter_map(|a| a.deadline()))
            .chain(client.as_ref().map(ClientRequest::obligation_deadline))
            .chain(update.as_ref().map(UpdateRequest::obligation_deadline))
            .chain(receive.as_ref().map(|r| r.wake_deadline()))
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
            _ = async { update.as_mut().expect("guarded update wait").withdrawn().await },
                if update.as_ref().is_some_and(UpdateRequest::needs_withdrawal_watch) => {
                retire_update_event(&mut update, &mut pending, Instant::now())?;
                // A withdrawn author does not erase admitted work or its
                // original drain. All-admitted work without an author no
                // longer watches; an unfinished stream keeps its owner watch.
            }
            _ = tokio::time::sleep_until(deadline) => {
                retire_client_wait(&mut client, &mut pending, Instant::now());
                retire_update_wait(&mut update, &mut pending, Instant::now());
                if assemblies.iter().any(|a|a.deadline().is_some_and(|d|Instant::now()>=d)) {return Err(io::Error::new(io::ErrorKind::TimedOut,"original SSAP fragment deadline"));}
                if update.as_ref().is_some_and(|v| Instant::now() >= v.obligation_deadline()) {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "original SSAP indication obligation deadline"));
                }
                if (!initial_done && Instant::now() >= original_deadline) || pending.iter().any(|p| Instant::now() >= p.deadline) || client.as_ref().is_some_and(|v|Instant::now()>=v.obligation_deadline()) || server.as_ref().is_some_and(|v|Instant::now()>=v.0) || server_queue.iter().any(|v|Instant::now()>=v.deadline) {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "original SSAP obligation deadline"));
                }
                slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
            }
            query = incoming.recv() => {
                let Some(query)=query else { return Ok(()); };
                if let Query::Subscribe {owner,handles,modes,duration_ms,deadline,reply}=query {
                    if reply.is_closed(){continue;}
                    let prepared=(||{
                        if !initial_done || receive.is_some() || client.is_some() || incoming_wait.is_some()
                            || Instant::now()>=deadline || !owner.current()
                            || !slk_contract::ssap::subscription::valid_request(&handles,modes,duration_ms){
                            return Err("subscription busy/not-ready/expired/invalid".to_string());
                        }
                        let context=wire.prepare(2,deadline).map_err(|e|e.to_string())?.ok_or("Native subscription context required")?;
                        let token=next_subscription;
                        next_subscription=next_subscription.checked_add(1).ok_or("subscription namespace exhausted")?;
                        let expires=Instant::now()+Duration::from_millis(u64::from(duration_ms));
                        let info=slk_contract::ssap::subscription::Info{version:1,controller:capabilities.controller,
                            generation:capabilities.generation,lifetime:capabilities.lifetime,handle:capabilities.handle,
                            security_epoch:context.security_epoch,token,expires_ns:monotonic_deadline(expires).map_err(|e|e.to_string())?,
                            handles:handles.clone(),modes,state:slk_contract::ssap::subscription::STARTING,
                            capacity:slk_contract::ssap::subscription::CAPACITY as u16};
                        Ok((info,expires))
                    })();
                    match prepared {
                        Err(error)=>{let _=reply.send(Err(error));},
                        Ok((info,expires))=>receive=Some(crate::ssap_receive_transaction::ReceiveTransaction::new_stream(
                            handles,modes,deadline,owner,info,expires,reply)),
                    }
                    continue;
                }
                if let Query::SubscriptionRead{caller,token,wait,deadline,reply}=query {
                    if reply.is_closed(){continue;}
                    if let Some(current)=receive.as_mut().filter(|r|r.matches(&caller,token)) {
                        let valid=(||{
                            if Instant::now()>=deadline{return Err("subscription read original deadline".to_string());}
                            let context=wire.prepare(2,deadline).map_err(|e|e.to_string())?.ok_or("Native context required")?;
                            if current.expected_epoch()!=Some(context.security_epoch){return Err("subscription original security changed".into());}
                            Ok(())
                        })();
                        match valid { Ok(())=>current.read(wait,deadline,reply),Err(error)=>{let _=reply.send(Err(error));} }
                    } else if let Some(last)=last_subscription.as_ref().filter(|r|r.owner==caller&&r.token==token) {
                        let _=reply.send(last.result.clone());
                    } else {let _=reply.send(Err("subscription owner/token unavailable".into()));}
                    continue;
                }
                if let Query::SubscriptionRenew{caller,token,duration_ms,deadline,reply}=query {
                    if reply.is_closed(){continue;}
                    let result=(||{
                        if Instant::now()>=deadline{return Err("subscription renewal original deadline".to_string());}
                        let current=receive.as_mut().filter(|r|r.matches(&caller,token)).ok_or("subscription owner/token unavailable")?;
                        let context=wire.prepare(2,deadline).map_err(|e|e.to_string())?.ok_or("Native context required")?;
                        if current.expected_epoch()!=Some(context.security_epoch){return Err("subscription original security changed".into());}
                        current.renew(duration_ms)
                    })();
                    let _=reply.send(result);continue;
                }
                if let Query::SubscriptionClose{caller,token,deadline,reply}=query {
                    if reply.is_closed(){continue;}
                    if Instant::now()>=deadline {let _=reply.send(Err("subscription close original deadline".into()));continue;}
                    if let Some(current)=receive.as_mut().filter(|r|r.matches(&caller,token)){current.close(reply);}
                    else if let Some(last)=last_subscription.as_ref().filter(|r|r.owner==caller&&r.token==token){let _=reply.send(last.result.clone());}
                    else {let _=reply.send(Err("subscription owner/token unavailable".into()));}
                    continue;
                }
                if let Query::Configuration { caller, handle, deadline, reply } = query {
                    if reply.is_closed() {continue;}
                    let result = (|| {
                        if !initial_done || Instant::now() >= deadline {return Err("configuration observation not-ready/expired".to_string());}
                        let context=wire.prepare(2,deadline).map_err(|e|e.to_string())?.ok_or("native security context required")?;
                        let db=database.lock().map_err(|_|"database poisoned")?;
                        let (owner,_)=db.owned_update(handle,&caller)?;
                        Ok(configurations.get(handle,&owner,context.security_epoch))
                    })();
                    let _=reply.send(result);continue;
                }
                if let Query::Update { caller, handle, indication, deadline, reply } = query {
                    if reply.is_closed() {continue;}
                    if update.is_some() || pending.len()+server_load>=8 || !initial_done || Instant::now()>=deadline {
                        let _=reply.send(Err("SSAP update busy/not-ready/expired".into()));continue;
                    }
                    let prepared = (|| {
                        let context=wire.prepare(2,deadline).map_err(|e|e.to_string())?.ok_or("native security context required")?;
                        let db=database.lock().map_err(|_|"database poisoned")?;
                        let (owner,value)=db.owned_update(handle,&caller)?;
                        let mode=if indication {2} else {1};
                        if configurations.get(handle,&owner,context.security_epoch)&mode==0 {return Err("peer client configuration does not enable requested mode".to_string());}
                        let mtu=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        let packet=slk_protocol::ssap::updates::Update { indication,event:false,
                            items:vec![slk_protocol::ssap::updates::Item{handle,value:&value}] };
                        let budget=if peer_reply.as_ref().is_some_and(|(p,_)|sequenced(p)) {fragments::MAX_LOGICAL_MTU}else{mtu};
                        let mut raw=vec![0;usize::from(budget)];
                        let size=packet.encode(budget,&mut raw).map_err(|e|format!("update exceeds negotiated logical budget: {e:?}"))?;
                        raw.truncate(size);Ok((owner,mode,context,raw))
                    })();
                    match prepared {
                        Err(error)=>{let _=reply.send(Err(error));},
                        Ok((owner,mode,context,raw))=> {
                            pending.push_back(Pending{sent: 0,bytes:raw.clone(),deadline,purpose:Purpose::Update,constraint:Some(context)});
                            update=Some(UpdateRequest{submitted_all:false,handle,owner,mode,epoch:context.security_epoch,deadline,drain:None,pdu:raw,reply:Some(reply)});
                        }
                    }
                    continue;
                }
                if let Query::Incoming{handles,modes,deadline,reply}=query {
                    if reply.is_closed(){continue;}
                    if receive.is_some() || client.is_some() || incoming_wait.is_some() || !initial_done || Instant::now()>=deadline || handles.is_empty() || handles.len()>32 || modes==0 || modes&!3!=0 || handles.contains(&0) || handles.iter().enumerate().any(|(i,h)|handles[..i].contains(h)) {let _=reply.send(Err("SSAP receive busy/not-ready/invalid/expired".into()));continue;}
                    slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                    receive=Some(crate::ssap_receive_transaction::ReceiveTransaction::new(handles,modes,deadline,reply));continue;
                }
                if let Query::Value{bytes,deadline,minimum,reply}=query {
                    if receive.as_ref().is_some_and(|r|r.owns_client_sequence()) {let _=reply.send(Err("SSAP client sequence owned by receive transaction".into()));continue;}
                    ClientAdmission {wire:&wire,client:&mut client,pending:&mut pending,response_load:server_load,ready:initial_done,mtu:if peer_reply.as_ref().is_some_and(|(p,_)|sequenced(p)){fragments::LOGICAL_MTU}else{capabilities.mtu}}
                        .begin(bytes,deadline,minimum,reply);continue;
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
            event = async {receive.as_mut().expect("guarded receive transaction").event().await}, if receive.is_some() => {
                receive.as_mut().expect("current receive transaction").apply(event).map_err(io::Error::other)?;
            }
            decision = async { server.as_mut().expect("guarded server obligation").1.as_mut().await }, if server.is_some() => {
                server.take();
                pending.push_back(complete_server(&wire,decision,&database,&mut configurations)?);
            }
            ready = wire.fd.writable(), if !pending.is_empty() => {
                let mut ready = ready?;
                retire_client_wait(&mut client, &mut pending, Instant::now());
                retire_update_wait(&mut update, &mut pending, Instant::now());
                let Some(packet) = pending.front() else { continue; };
                if Instant::now() >= packet.deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "expired SSAP submit")); }
                let is_update=matches!(packet.purpose,Purpose::Update);
                let sequence=match packet.purpose {
                    Purpose::Client|Purpose::Update=>peer_reply.as_ref().is_some_and(|(p,_)|sequenced(p)),
                    Purpose::ValueResponse=>ExchangeInfo::decode(capabilities.mtu,&peer_request).is_ok_and(|p|sequenced(&p)),
                    _=>false,
                };
                let mtu=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                let plan=fragments::Plan::new(&packet.bytes,mtu,sequence).map_err(|e|io::Error::other(format!("SSAP fragment plan: {e:?}")))?;
                let mut fragment=vec![0;usize::from(mtu)];
                let count=plan.count();let size=plan.encode(packet.sent,&mut fragment).map_err(|e|io::Error::other(format!("SSAP fragment encode: {e:?}")))?;
                fragment.truncate(size);
                let outcome = if is_update {
                    // Same DB mutex as removal. This nonblocking syscall admits
                    // one immutable value snapshot; no lock crosses an await.
                    let db=database.lock().map_err(|_|io::Error::other("database poisoned"))?;
                    let current=update.as_ref().ok_or_else(||io::Error::other("missing update obligation"))?;
                    if !current.owner.current() || configurations.get(current.handle,&current.owner,current.epoch)&current.mode==0 {
                        if current.drain.is_some() {return Err(io::Error::other("partial update owner/configuration withdrawn;retire SSAP actor"));}
                        drop(db);
                        if let Some(mut current)=update.take() && let Some(reply)=current.reply.take() {let _=reply.send(Err("update owner/configuration withdrawn before admission".into()));}
                        pending.pop_front();continue;
                    }
                    ready.try_io(|fd| wire.send(fd.get_ref(), packet, &fragment))
                } else {ready.try_io(|fd| wire.send(fd.get_ref(), packet, &fragment))};
                if let Ok(result) = outcome {
                    result?;
                    let packet=pending.front_mut().expect("guarded queue");
                    if matches!(packet.purpose,Purpose::Client) && let Some(client)=&mut client {
                        client.admit_part(Instant::now(),packet.sent+1==count);
                    }
                    if is_update {
                        update.as_mut().ok_or_else(||io::Error::other("missing update admission"))?
                            .admit_part(Instant::now(),packet.sent+1==count);
                    }
                    packet.sent+=1;
                    if packet.sent<count {continue;}
                    let packet = pending.pop_front().expect("guarded queue");
                    match packet.purpose {
                        Purpose::Request => request_admitted = true,
                        Purpose::Response => response_admitted = packet.bytes,
                        Purpose::Error | Purpose::ValueResponse => {},
                        Purpose::Client => {},
                        Purpose::Update => {
                            let current=update.as_mut().ok_or_else(||io::Error::other("missing admitted update"))?;
                            if current.mode!=2 {
                                let mut current=update.take().expect("admitted notification");
                                if let Some(reply)=current.reply.take() {let _=reply.send(Ok(slk_contract::ssap::UpdateReceipt {stage:1,pdu:current.pdu,acknowledgement:vec![]}));}
                                // No SSAP reply is owed. Native still retains
                                // physical TX/credit obligations independently.
                            }
                        }
                    }
                }
            }
            ready = wire.fd.readable() => {
                let mut ready = ready?;
                if let Ok(result) = ready.try_io(|fd| wire.receive(fd.get_ref(), &mut buffer, capabilities)) {
                    let (size, mut receipt) = result?;
                    let mut reply_deadline = if initial_done { Instant::now()+Duration::from_secs(5) } else { original_deadline };

                    if size == 0 || size > usize::from(capabilities.mtu) { return Err(io::Error::other("invalid SSAP PDU length")); }
                    let wire_raw = &buffer[..size];
                    let assembled;
                    let raw = if fragments::needs_reassembly(wire_raw) {
                        if !initial_done {return Err(io::Error::other("SSAP fragments before negotiation"));}
                        let lane=fragments::lane(wire_raw[0]).expect("supported fragment lane");
                        let enabled=if lane==0 {ExchangeInfo::decode(capabilities.mtu,&peer_request).is_ok_and(|p|accepts_extended(&p,wire_raw[1]))}
                            else {peer_reply.as_ref().is_some_and(|(p,_)|accepts_extended(p,wire_raw[1]))};
                        if lane==1 && let Some(c)=&client {reply_deadline=reply_deadline.min(c.obligation_deadline());}
                        if lane==2 && let Some(w)=&incoming_wait {reply_deadline=reply_deadline.min(w.deadline);}
                        let complete=assemblies[lane].receive(wire_raw,capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu)),enabled,receipt,Instant::now(),reply_deadline)
                            .map_err(|e|io::Error::other(format!("SSAP fragment stream retired: {e:?}")))?;
                        let Some(complete)=complete else {continue;};
                        receipt=complete.context;reply_deadline=complete.deadline;assembled=complete.bytes;&assembled[..]
                    } else {
                        if fragments::lane(wire_raw[0]).is_some_and(|lane|assemblies[lane].deadline().is_some()) {return Err(io::Error::other("complete SSAP value interleaves unfinished fragment lane"));}
                        wire_raw
                    };
                    let constraint=receipt.map(|m|slk_protocol::SleSendConstraint::from_receipt(m,m.security,monotonic_deadline(reply_deadline)?)).transpose()?;
                    if !initial_done && Instant::now() >= original_deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "late SSAP reply")); }
                    if matches!(raw[0],15|16) {
                        if raw[0]==16 && pending.len()+server_load>=8{return Err(io::Error::other("SSAP ACK queue full"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                        if let Some(current)=receive.as_mut() {
                            current.maintain(&mut incoming_wait,Instant::now()).map_err(io::Error::other)?;
                        }
                        let budget=if peer_reply.as_ref().is_some_and(|(p,_)|sequenced(p)){fragments::MAX_LOGICAL_MTU}else{negotiated};
                        let ack=incoming_packet(negotiated,budget,raw,receipt,&mut incoming_wait)?;
                        if !ack.is_empty(){pending.push_back(Pending{sent: 0,bytes:ack,deadline:reply_deadline,purpose:Purpose::ValueResponse,constraint});}
                    } else if raw[0]==17 {
                        let Some(mut current)=update.take() else {return Err(io::Error::other("unsolicited indication ACK"));};
                        if current.mode!=2 || !current.submitted_all || current.drain.is_none_or(|d|Instant::now()>=d) {
                            return Err(io::Error::other("indication ACK before admission or after drain deadline"));
                        }
                        let m=receipt.ok_or_else(||io::Error::other("missing ACK security receipt"))?;
                        if m.security_epoch!=current.epoch || m.security<2 {return Err(io::Error::other("indication ACK original security changed"));}
                        let flags=slk_protocol::ssap::updates::decode_ack(capabilities.mtu,raw,false,1)
                            .map_err(|e|io::Error::other(format!("invalid indication ACK: {e:?}")))?;
                        if let Some(reply)=current.reply.take().filter(|r| !r.is_closed() && current.owner.current() && Instant::now()<current.deadline) {
                            let result=if flags==[1] {Ok(slk_contract::ssap::UpdateReceipt{stage:2,pdu:current.pdu,acknowledgement:raw.to_vec()})}
                                else {Err("peer indication receive queue refused update".into())};
                            let _=reply.send(result);
                        }
                    } else if matches!(raw[0],4|6|8|10|13) {
                        if !initial_done {return Err(io::Error::other("SSAP value/discovery before ExchangeInfo completion"));}
                        if pending.len()+server_load>=8 {return Err(io::Error::other("SSAP response obligation queue full"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        slk_channel::query(wire.fd.get_ref().as_raw_fd())?;
                        next_server_id=next_server_id.checked_add(1).ok_or_else(||io::Error::other("SSAP original request namespace exhausted"))?;
                        server_queue.push_back(ServerPacket {bytes:raw.to_vec(),deadline:reply_deadline,constraint,mtu:if matches!(raw[0],8|10|13) && ExchangeInfo::decode(capabilities.mtu,&peer_request).is_ok_and(|p|sequenced(&p)){fragments::LOGICAL_MTU}else{negotiated},level:receipt.map_or(0,|m|m.security),request_id:next_server_id});
                    } else if matches!(raw[0],1|5|7|9|11|14) {
                        let Some(current)=client.take() else {return Err(io::Error::other("unsolicited SSAP value reply"));};
                        current.validate_reply(receipt,Instant::now())?;
                        let ClientRequest{bytes:request,deadline,reply,..}=current;
                        let reply=reply.filter(|r| !r.is_closed() && Instant::now()<deadline);
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        if request[0]==10 {
                            let r=slk_protocol::ssap::read_uuid::Request::decode(negotiated,&request).map_err(|_|io::Error::other("invalid local UUID request"))?;
                            if let Ok(ValuePdu::ReadError(16))=ValuePdu::decode(negotiated,raw){finish_client(reply,Err("peer requires unsupported SSAP fragmentation".into()));continue;}
                            if let Ok(ValuePdu::Error{request:10,error,..})=ValuePdu::decode(negotiated,raw){finish_client(reply,Err(format!("peer read UUID protocol error {error}").into()));continue;}
                            let entries=slk_protocol::ssap::read_uuid::decode(if peer_reply.as_ref().is_some_and(|(p,_)|sequenced(p)){fragments::LOGICAL_MTU}else{negotiated},raw).map_err(|_|io::Error::other("invalid read UUID response"))?;
                            if entries.iter().any(|i|i.handle<r.start || i.handle>r.end) {return Err(io::Error::other("read UUID response outside requested range"));}
                            finish_client(reply,Ok(raw.to_vec()));continue;
                        }
                        if matches!(request[0],4|6) {
                            let request=slk_protocol::ssap::discovery::FindRequest::decode(negotiated,&request).map_err(|_|io::Error::other("invalid local find request"))?;
                            if raw[0]==1 {match ValuePdu::decode(negotiated,raw) {Ok(ValuePdu::Error{request:op,..}) if op==request.opcode()=>{},_=>return Err(io::Error::other("invalid find error response"))}}
                            else {slk_protocol::ssap::discovery::decode_page(request,negotiated,raw).map_err(|_|io::Error::other("invalid find response"))?;}
                            finish_client(reply,Ok(raw.to_vec()));continue;
                        }
                        let value_budget=if peer_reply.as_ref().is_some_and(|(p,_)|sequenced(p)){fragments::LOGICAL_MTU}else{negotiated};
                        // Admission,lifetime andsecurity checks above still
                        // precede classification;never parse diagnostics.
                        finish_client(reply,client_value_response(value_budget,&request,raw)?);
                    } else if raw[0] == 2 || raw[0] == 3 {
                        let info = match ExchangeInfo::decode(capabilities.mtu,raw) {
                            Ok(info)=>info,
                            Err(_) if raw[0]==2 => {
                                if pending.len()>=8 {return Err(io::Error::other("SSAP invalid-PDU response queue full"));}
                                pending.push_back(Pending {sent: 0,bytes:vec![1,0,2,0,0,1],purpose:Purpose::Error,constraint,deadline:Instant::now()+Duration::from_secs(5)});
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
                            pending.push_back(Pending {sent: 0, bytes: response.clone(), purpose: Purpose::Response,constraint,
                                deadline: if initial_done { Instant::now() + Duration::from_secs(5) } else { original_deadline } });
                        }
                    } else if matches!(raw[0] & 0x7f, 4 | 6 | 8 | 10 | 13 | 19) {
                        if pending.len() >= 8 { return Err(io::Error::other("SSAP error queue full")); }
                        // T/XS20001 table50: complete ErrorRsp including RFU MCC.
                        pending.push_back(Pending {sent: 0, bytes: vec![1,0,raw[0],0,0,2], purpose: Purpose::Error,constraint,
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
    #[test]
    fn expired_initializer_cannot_register_a_reactor_or_start_wire_work() {
        let (fd, _peer) = transport_pair();
        let result = Engine::start(
            fd,
            (0, 1, 1, 0),
            std::sync::Arc::new(std::sync::Mutex::new(
                crate::ssap_database::Database::default(),
            )),
            Instant::now(),
        );
        assert!(matches!(result,Err(error)if error.kind()==io::ErrorKind::TimedOut));
        // No Tokio runtime: moving the check past AsyncFd::new would panic.
    }
    #[test]
    fn actual_client_retirement_removes_only_definite_unsubmitted_work() {
        let now = Instant::now();
        for close in [false, true] {
            let (tx, mut rx) = oneshot::channel();
            let mut client = Some(ClientRequest {
                minimum: 0,
                epoch: None,
                bytes: vec![8, 0, 17, 0],
                deadline: now + Duration::from_secs(1),
                admitted: false,
                submitted_all: false,
                cleanup_deadline: None,
                reply: Some(tx),
            });
            let mut pending = VecDeque::from([
                Pending {
                    sent: 0,
                    bytes: vec![1],
                    deadline: now + Duration::from_secs(2),
                    purpose: Purpose::Response,
                    constraint: None,
                },
                Pending {
                    sent: 0,
                    bytes: vec![8, 0, 17, 0],
                    deadline: now + Duration::from_secs(1),
                    purpose: Purpose::Client,
                    constraint: None,
                },
            ]);
            if close {
                rx.close();
            }
            retire_client_wait(
                &mut client,
                &mut pending,
                if close {
                    now
                } else {
                    now + Duration::from_secs(1)
                },
            );
            assert!(client.is_none());
            assert_eq!(pending.len(), 1);
            assert!(matches!(pending[0].purpose, Purpose::Response));
            assert_eq!(pending[0].bytes, [1]);
            if !close {
                assert!(
                    rx.try_recv()
                        .unwrap()
                        .unwrap_err()
                        .to_string()
                        .contains("before admission")
                );
            }
        }
    }
    #[test]
    fn actual_admitted_retirement_preserves_physical_identity_and_never_renews_author() {
        let now = Instant::now();
        let original = now + Duration::from_secs(1);
        let drain = now + Duration::from_secs(5);
        let (tx, mut rx) = oneshot::channel();
        let mut client = Some(ClientRequest {
            minimum: 2,
            epoch: Some(37),
            bytes: vec![8, 0, 17, 0],
            deadline: original,
            admitted: true,
            submitted_all: true,
            cleanup_deadline: Some(drain),
            reply: Some(tx),
        });
        let mut pending = VecDeque::new();
        retire_client_wait(&mut client, &mut pending, original);
        assert!(
            rx.try_recv()
                .unwrap()
                .unwrap_err()
                .to_string()
                .contains("original deadline")
        );
        let c = client.as_ref().unwrap();
        assert!(c.admitted && c.reply.is_none());
        assert_eq!((c.minimum, c.epoch), (2, Some(37)));
        assert_eq!(c.bytes, [8, 0, 17, 0]);
        assert_eq!(c.deadline, original);
        assert_eq!(c.obligation_deadline(), drain);
        retire_client_wait(
            &mut client,
            &mut pending,
            original + Duration::from_millis(1),
        );
        let mut c = client.take().unwrap();
        finish_client(c.reply.take(), Ok(vec![99]));
        assert_eq!(rx.try_recv(), Err(oneshot::error::TryRecvError::Closed));
        assert!(pending.is_empty());
    }
    #[test]
    fn typed_write_rejection_requires_original_handle_operation_and_layout() {
        let request = [13, 35, 17, 0, 2, 0, 0];
        let result = client_value_response(249, &request, &[14, 7, 1, 17, 0, 4]).unwrap();
        assert_eq!(
            result,
            Err(ClientFailure::WriteError {
                handle: 17,
                error: 4
            })
        );
        assert_eq!(result.unwrap_err().to_string(), "peer write error 4");
        for raw in [&[14, 7, 1, 18, 0, 4][..], &[14, 11, 4, 0], &[9, 11, 4, 0]] {
            assert!(client_value_response(249, &request, raw).is_err());
        }
        assert!(matches!(
            client_value_response(249, &request, &[1, 0, 13, 17, 0, 4]).unwrap(),
            Err(ClientFailure::Message(_))
        ));
        assert_eq!(
            client_value_response(249, &request, &[14, 3, 17, 0, 2, 0, 0]).unwrap(),
            Ok(vec![0, 0])
        );
    }
    #[test]
    fn extended_complete_and_sequence_capabilities_remain_distinct() {
        let mut p = ExchangeInfo {
            kind: ExchangeKind::Response,
            mtu: Some(2042),
            version: Some([1, 2]),
            extension: None,
            reliable: false,
        };
        assert!(!accepts_extended(&p, 3));
        assert!(!accepts_extended(&p, 0));
        p.extension = Some(ExtensionCapabilities {
            fragment_sequence: false,
            transaction_capacity: None,
        });
        assert!(accepts_extended(&p, 3));
        assert!(!accepts_extended(&p, 0));
        p.extension.as_mut().unwrap().fragment_sequence = true;
        for c in 0..4 {
            assert!(accepts_extended(&p, c));
        }
    }
    #[test]
    fn actual_fragment_admissions_start_one_drain_and_keep_author_deadline() {
        let now = Instant::now();
        let deadline = now + Duration::from_secs(1);
        let (tx, _rx) = oneshot::channel();
        let mut c = ClientRequest {
            minimum: 0,
            epoch: None,
            bytes: vec![13, 35, 17, 0, 0],
            deadline,
            admitted: false,
            submitted_all: false,
            cleanup_deadline: None,
            reply: Some(tx),
        };
        c.admit_part(now, false);
        let first = c.cleanup_deadline;
        assert!(c.admitted);
        assert!(!c.submitted_all);
        assert_eq!(first, Some(now + Duration::from_secs(5)));
        c.admit_part(now + Duration::from_millis(900), true);
        assert!(c.submitted_all);
        assert_eq!(c.cleanup_deadline, first);
        assert_eq!(c.deadline, deadline);
        let mut client = Some(c);
        let mut pending = VecDeque::new();
        retire_client_wait(&mut client, &mut pending, deadline);
        let c = client.unwrap();
        assert!(c.reply.is_none());
        assert_eq!(c.cleanup_deadline, first);
        assert_eq!(c.obligation_deadline(), first.unwrap());
    }
    #[tokio::test]
    async fn actual_partial_client_backpressure_preserves_cancelled_stream_and_reply_guard() {
        // Actual production codec/Plan/Wire::send/request transitions with
        // explicit AF_UNIX dependencies. This starts AFTER Native admission;
        // it does not bypass ClientAdmission's real ioctl or invent security.
        let (fd, peer) = transport_pair();
        let small = 1024i32;
        assert_eq!(
            unsafe {
                nix::libc::setsockopt(
                    fd.as_raw_fd(),
                    nix::libc::SOL_SOCKET,
                    nix::libc::SO_SNDBUF,
                    (&small as *const i32).cast(),
                    std::mem::size_of_val(&small) as nix::libc::socklen_t,
                )
            },
            0
        );
        let wire = Wire::fixture(AsyncFd::new(fd).unwrap());
        let first = Instant::now();
        let deadline = first + Duration::from_secs(1);
        let value = vec![0xa7; 2042];
        let mut raw = vec![0; usize::from(fragments::LOGICAL_MTU)];
        let size = ValuePdu::Write {
            handle: 17,
            data_type: 0,
            value: &value,
            verify: true,
        }
        .encode(fragments::LOGICAL_MTU, &mut raw)
        .unwrap();
        raw.truncate(size);
        let plan = fragments::Plan::new(&raw, 249, true).unwrap();
        assert!(plan.count() > 1);
        let (reply, author) = oneshot::channel();
        let mut current = ClientRequest {
            minimum: 0,
            epoch: None,
            bytes: raw.clone(),
            deadline,
            admitted: false,
            submitted_all: false,
            cleanup_deadline: None,
            reply: Some(reply),
        };
        let mut packet = Pending {
            sent: 0,
            bytes: raw.clone(),
            deadline,
            purpose: Purpose::Client,
            constraint: None,
        };
        let mut frames = Vec::new();
        while packet.sent < plan.count() {
            let mut part = vec![0; 249];
            let n = plan.encode(packet.sent, &mut part).unwrap();
            part.truncate(n);
            match wire.send(wire.fd.get_ref(), &packet, &part) {
                Ok(()) => {
                    packet.sent += 1;
                    current.admit_part(
                        first + Duration::from_millis(packet.sent as u64),
                        packet.sent == plan.count(),
                    );
                    frames.push(part);
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(error) => panic!("actual fixture send failed: {error}"),
            }
        }
        assert!(
            packet.sent > 0 && packet.sent < plan.count(),
            "actual partial software admission required"
        );
        assert!(current.admitted && !current.submitted_all);
        let first_drain = current.cleanup_deadline.unwrap();
        assert_eq!(
            first_drain,
            first + Duration::from_millis(1) + Duration::from_secs(5)
        );
        assert!(
            current
                .validate_reply(None, first + Duration::from_millis(100))
                .is_err()
        );
        drop(author);
        let original = current.bytes.clone();
        let mut client = Some(current);
        let mut pending = VecDeque::from([packet]);
        retire_client_wait(
            &mut client,
            &mut pending,
            first + Duration::from_millis(100),
        );
        let current = client.as_mut().unwrap();
        assert!(current.reply.is_none() && current.admitted && !current.submitted_all);
        assert_eq!(current.bytes, original);
        assert_eq!(current.cleanup_deadline, Some(first_drain));
        assert_eq!(current.obligation_deadline(), first_drain);
        assert_eq!(pending.front().unwrap().deadline, deadline);
        // Drain only the genuine socket records. No generated peer response,
        // credit, completion or successful author result is substituted.
        let mut observed = Vec::new();
        for _ in 0..frames.len() {
            let mut received = [0; 249];
            let size = receive_fixture(&peer, &mut received).unwrap();
            observed.push(received[..size].to_vec());
        }
        assert_eq!(observed, frames);
        assert_eq!(
            receive_fixture(&peer, &mut [0; 249]).unwrap_err().kind(),
            io::ErrorKind::WouldBlock
        );
        while pending.front().unwrap().sent < plan.count() {
            let packet = pending.front_mut().unwrap();
            let mut part = vec![0; 249];
            let n = plan.encode(packet.sent, &mut part).unwrap();
            part.truncate(n);
            wire.send(wire.fd.get_ref(), packet, &part).unwrap();
            packet.sent += 1;
            current.admit_part(
                first + Duration::from_millis(200),
                packet.sent == plan.count(),
            );
            let mut received = [0; 249];
            let size = receive_fixture(&peer, &mut received).unwrap();
            assert_eq!(&received[..size], part);
        }
        assert!(current.submitted_all && current.reply.is_none());
        assert_eq!(current.cleanup_deadline, Some(first_drain));
        assert_eq!(current.deadline, deadline);
        // A valid late reply could drain this complete stream; it cannot
        // revive the cancelled author. The boundary itself stays exclusive.
        current
            .validate_reply(None, first_drain - Duration::from_nanos(1))
            .unwrap();
        assert!(current.validate_reply(None, first_drain).is_err());
    }
    #[test]
    fn actual_reply_guard_keeps_admission_drain_and_security_independent() {
        let now = Instant::now();
        let (reply, _author) = oneshot::channel();
        let mut request = ClientRequest {
            minimum: 2,
            epoch: Some(37),
            bytes: vec![8, 3, 17, 0],
            deadline: now + Duration::from_secs(1),
            admitted: false,
            submitted_all: false,
            cleanup_deadline: None,
            reply: Some(reply),
        };
        let valid = slk_protocol::SleMessageSecurity {
            security: 2,
            security_epoch: 37,
            ..Default::default()
        };
        assert!(request.validate_reply(Some(valid), now).is_err());
        request.admit_part(now, false);
        assert!(request.validate_reply(Some(valid), now).is_err());
        request.admit_part(now + Duration::from_millis(1), true);
        assert!(
            request
                .validate_reply(None, now)
                .unwrap_err()
                .to_string()
                .contains("missing reply receipt")
        );
        for wrong in [
            slk_protocol::SleMessageSecurity {
                security_epoch: 38,
                ..valid
            },
            slk_protocol::SleMessageSecurity {
                security: 1,
                ..valid
            },
        ] {
            assert!(
                request
                    .validate_reply(Some(wrong), now)
                    .unwrap_err()
                    .to_string()
                    .contains("original request security intent")
            );
        }
        request.validate_reply(Some(valid), now).unwrap();
        assert!(
            request
                .validate_reply(Some(valid), now + Duration::from_secs(5))
                .is_err()
        );
        assert_eq!(request.cleanup_deadline, Some(now + Duration::from_secs(5)));
        assert_eq!(request.deadline, now + Duration::from_secs(1));
    }
    #[tokio::test]
    async fn actual_observer_original_deadline_bounds_negotiation_and_never_enqueues_late_value() {
        let (_state, state) = watch::channel(Status::Starting);
        let (queries, mut incoming) = mpsc::channel(8);
        let observer = Observer { state, queries };
        let end = Instant::now() + Duration::from_millis(20);
        let result =
            tokio::time::timeout(Duration::from_millis(250), observer.value(17, None, 0, end))
                .await
                .expect("must not start fresh five seconds");
        assert!(result.unwrap_err().contains("original deadline"));
        assert!(matches!(
            incoming.try_recv(),
            Err(mpsc::error::TryRecvError::Disconnected)
        ));
    }
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
            assert_eq!(info.6, [2, 7, 249, 0, 1, 2, 4, 0, 0, 0]);
            assert_eq!(info.7, [3, 7, 249, 0, 1, 2, 4, 0, 0, 0]);
            assert_eq!(info.8, [2, 7, 249, 0, 1, 2, 4, 0, 0, 0]);
            assert_eq!(info.9, [3, 7, 249, 0, 1, 2, 4, 0, 0, 0]);
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
                    reply: reply.into(),
                }),
                rx,
            )
        }
        let indication = [16, 3, 17, 0, 2, 0, 7, 8];
        let notification = [15, 3, 17, 0, 2, 0, 7, 8];
        let (mut w, mut rx) = wait(vec![17], 2);
        assert_eq!(
            incoming_packet(249, 249, &indication, None, &mut w).unwrap(),
            [17, 3, 1]
        );
        assert_eq!(rx.try_recv().unwrap().unwrap(), (true, indication.to_vec()));
        assert!(w.is_none());
        let (mut w, rx) = wait(vec![17], 2);
        drop(rx);
        assert_eq!(
            incoming_packet(249, 249, &indication, None, &mut w).unwrap(),
            [17, 3, 0]
        );
        let (mut w, _rx) = wait(vec![18], 2);
        assert_eq!(
            incoming_packet(249, 249, &indication, None, &mut w).unwrap(),
            [17, 3, 0]
        );
        assert!(w.is_some());
        let (mut w, _rx) = wait(vec![17], 1);
        assert_eq!(
            incoming_packet(249, 249, &indication, None, &mut w).unwrap(),
            [17, 3, 0]
        );
        assert!(w.is_some());
        w.as_mut().unwrap().deadline = Instant::now() - Duration::from_millis(1);
        assert!(
            incoming_packet(249, 249, &notification, None, &mut w)
                .unwrap()
                .is_empty()
        );
        assert!(w.is_some());
        let (mut w, mut rx) = wait(vec![17], 1);
        assert!(
            incoming_packet(249, 249, &notification, None, &mut w)
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
        assert_eq!(
            incoming_packet(249, 249, &event, None, &mut w).unwrap(),
            [17, 7, 0]
        );
        assert!(w.is_some());
        let (mut w, _rx) = wait(vec![17], 2);
        assert!(incoming_packet(249, 249, &indication[..7], None, &mut w).is_err());
        assert!(w.is_some());
        assert_eq!(
            incoming_packet(249, 249, &indication, None, &mut None).unwrap(),
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

    #[tokio::test]
    async fn partial_update_caller_or_owner_exit_retains_original_physical_obligation() {
        // Actual Owner watch and update bookkeeping; no Native/USB/credit stub.
        let bus = crate::event_loop::tests::PrivateBus::start();
        let server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let caller = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        let store = std::sync::Arc::new(std::sync::Mutex::new(
            crate::ssap_database::Database::default(),
        ));
        let slots = std::sync::Arc::new(tokio::sync::Semaphore::new(1));
        let first = Instant::now();
        let owner = crate::ssap_authorization::Owner::pin(
            &server,
            caller.unique_name().unwrap().to_string(),
            zbus::zvariant::OwnedObjectPath::try_from("/").unwrap(),
            &store,
            slots.clone().try_acquire_owned().unwrap(),
            first + Duration::from_secs(5),
        )
        .await
        .unwrap();
        for partial in [false, true] {
            let (reply, rx) = oneshot::channel();
            let mut current = UpdateRequest {
                submitted_all: false,
                handle: 17,
                owner: owner.clone(),
                mode: 2,
                epoch: 7,
                deadline: first + Duration::from_secs(4),
                drain: None,
                pdu: vec![16, 3, 17, 0, 0, 0],
                reply: Some(reply),
            };
            if partial {
                current.admit_part(first, false);
            }
            let mut pending = VecDeque::from([Pending {
                sent: usize::from(partial),
                bytes: current.pdu.clone(),
                deadline: current.deadline,
                purpose: Purpose::Update,
                constraint: None,
            }]);
            let mut update = Some(current);
            drop(rx);
            retire_update_wait(&mut update, &mut pending, first + Duration::from_secs(1));
            if partial {
                let current = update.as_mut().unwrap();
                assert!(current.reply.is_none() && !current.submitted_all);
                assert_eq!(pending.len(), 1);
                assert_eq!(
                    current.obligation_deadline(),
                    first + Duration::from_secs(5)
                );
                current.admit_part(first + Duration::from_secs(2), true);
                assert!(current.submitted_all);
                assert_eq!(current.drain, Some(first + Duration::from_secs(5)));
                assert_eq!(current.deadline, first + Duration::from_secs(4));
            } else {
                assert!(update.is_none() && pending.is_empty());
            }
        }
        let (reply, _rx) = oneshot::channel();
        let mut current = UpdateRequest {
            submitted_all: false,
            handle: 17,
            owner: owner.clone(),
            mode: 2,
            epoch: 7,
            deadline: first + Duration::from_secs(4),
            drain: None,
            pdu: vec![16, 3, 17, 0, 0, 0],
            reply: Some(reply),
        };
        current.admit_part(first, false);
        owner.revoke();
        let mut pending = VecDeque::from([Pending {
            sent: 1,
            bytes: current.pdu.clone(),
            deadline: current.deadline,
            purpose: Purpose::Update,
            constraint: None,
        }]);
        let mut update = Some(current);
        retire_update_wait(&mut update, &mut pending, first + Duration::from_secs(1));
        assert!(update.as_ref().unwrap().reply.is_none());
        assert_eq!(pending.len(), 1);
        assert_eq!(update.unwrap().drain, Some(first + Duration::from_secs(5)));
        owner.shutdown().await;
        assert_eq!(slots.available_permits(), 1);
    }
}

#[cfg(test)]
#[path = "ssap_authorization_tests.rs"]
mod authorization_tests;
