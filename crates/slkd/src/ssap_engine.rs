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
    Value {
        bytes: Vec<u8>,
        deadline: Instant,
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
    pub(crate) async fn value(
        self,
        handle: u16,
        value: Option<Vec<u8>>,
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
                reply,
            })
            .map_err(|_| "SSAP request queue unavailable/full".to_string())?;
        tokio::time::timeout_at(deadline, result)
            .await
            .map_err(|_| "SSAP value original deadline".to_string())?
            .map_err(|_| "SSAP actor stopped during value operation".to_string())?
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
struct ClientRequest {
    bytes: Vec<u8>,
    deadline: Instant,
    admitted: bool,
    reply: oneshot::Sender<Result<Vec<u8>, String>>,
}
struct Pending {
    bytes: Vec<u8>,
    deadline: Instant,
    purpose: Purpose,
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
fn receive(fd: &OwnedFd, bytes: &mut [u8]) -> io::Result<usize> {
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
                match ready.try_io(|fd| slk_protocol::channel::query(fd.get_ref().as_raw_fd())) {
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
        fd,
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
    fd: AsyncFd<OwnedFd>,
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
    }]);
    let mut request_admitted = false;
    let mut initial_done = false;
    let mut peer_reply: Option<(ExchangeInfo, Vec<u8>)> = None;
    let mut peer_request = Vec::new();
    let mut response_admitted = Vec::new();
    let mut client: Option<ClientRequest> = None;
    let mut buffer = [0; 2042];
    loop {
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
                if (!initial_done && Instant::now() >= original_deadline) || pending.iter().any(|p| Instant::now() >= p.deadline) || client.as_ref().is_some_and(|v|Instant::now()>=v.deadline) {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "original SSAP obligation deadline"));
                }
                slk_protocol::channel::query(fd.get_ref().as_raw_fd())?;
            }
            query = incoming.recv() => {
                let Some(query)=query else { return Ok(()); };
                if let Query::Value{bytes,deadline,reply}=query {
                    if client.is_some() || pending.len()>=8 || !initial_done || Instant::now()>=deadline {let _=reply.send(Err("SSAP busy/not-ready/expired".into()));continue;}
                    slk_protocol::channel::query(fd.get_ref().as_raw_fd())?;
                    if bytes.len()>usize::from(capabilities.mtu) {let _=reply.send(Err("SSAP request exceeds channel".into()));continue;}
                    pending.push_back(Pending{bytes:bytes.clone(),deadline,purpose:Purpose::Client});client=Some(ClientRequest{bytes,deadline,admitted:false,reply});continue;
                }
                let Query::Info(reply)=query else {unreachable!()};
                let result=match state.borrow().clone() {
                    Status::Negotiated(info) => slk_protocol::channel::query(fd.get_ref().as_raw_fd()).map_err(|e|e.to_string()).and_then(|current| {
                        if current != capabilities { Err("SMTC capability/lifetime changed".into()) } else { Ok(info) }
                    }),
                    Status::Starting => Err("SSAP response obligation pending".into()),
                    Status::Failed(error) => Err(error),
                };
                let _=reply.send(result);
            }
            ready = fd.writable(), if !pending.is_empty() => {
                let mut ready = ready?;
                let packet = pending.front().expect("guarded queue");
                if Instant::now() >= packet.deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "expired SSAP submit")); }
                if let Ok(result) = ready.try_io(|fd| send(fd.get_ref(), &packet.bytes)) {
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
            ready = fd.readable() => {
                let mut ready = ready?;
                if let Ok(result) = ready.try_io(|fd| receive(fd.get_ref(), &mut buffer)) {
                    let size = result?;
                    if size == 0 || size > usize::from(capabilities.mtu) { return Err(io::Error::other("invalid SSAP PDU length")); }
                    let raw = &buffer[..size];
                    if !initial_done && Instant::now() >= original_deadline { return Err(io::Error::new(io::ErrorKind::TimedOut, "late SSAP reply")); }
                    if matches!(raw[0],8|13) {
                        if !initial_done {return Err(io::Error::other("SSAP value before initial exchange"));}
                        if pending.len()>=8 {return Err(io::Error::other("SSAP response queue full"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
                        slk_protocol::channel::query(fd.get_ref().as_raw_fd())?;
                        let response=match ValuePdu::decode(negotiated,raw) {
                            Ok(request)=>database.lock().map_err(|_|io::Error::other("database poisoned"))?.answer(request,negotiated).map_err(io::Error::other)?,
                            Err(e)=> {let mut out=vec![0;6];ValuePdu::Error{request:raw[0],handle:0,error:if raw.get(1).is_some_and(|v|v&3!=3){16}else if matches!(e,slk_protocol::ssap::value::ValueError::Unsupported){2}else{1}}.encode(negotiated,&mut out).map_err(|_|io::Error::other("error response exceeds MTU"))?;out},
                        };
                        pending.push_back(Pending{bytes:response,deadline:Instant::now()+Duration::from_secs(5),purpose:Purpose::ValueResponse});
                    } else if matches!(raw[0],1|9|14) {
                        let Some(ClientRequest{bytes:request,deadline,admitted,reply})=client.take() else {return Err(io::Error::other("unsolicited SSAP value reply"));};
                        if !admitted || Instant::now()>=deadline {return Err(io::Error::other("SSAP reply before submit or after original deadline"));}
                        let negotiated=capabilities.mtu.min(peer_reply.as_ref().and_then(|(p,_)|p.mtu).unwrap_or(capabilities.mtu));
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
                                pending.push_back(Pending {bytes:vec![1,0,2,0,0,1],purpose:Purpose::Error,deadline:Instant::now()+Duration::from_secs(5)});
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
                            pending.push_back(Pending { bytes: response.clone(), purpose: Purpose::Response,
                                deadline: if initial_done { Instant::now() + Duration::from_secs(5) } else { original_deadline } });
                        }
                    } else if matches!(raw[0] & 0x7f, 4 | 6 | 8 | 10 | 13 | 19) {
                        if pending.len() >= 8 { return Err(io::Error::other("SSAP error queue full")); }
                        // T/XS20001 table50: complete ErrorRsp including RFU MCC.
                        pending.push_back(Pending { bytes: vec![1,0,raw[0],0,0,2], purpose: Purpose::Error,
                            deadline: Instant::now() + Duration::from_secs(5) });
                    } else if matches!(raw[0], 12 | 15 | 18) {
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
                AsyncFd::new(a).unwrap(),
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
                AsyncFd::new(b).unwrap(),
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
        assert!(observer.info().await.unwrap_err().contains("25")); // AF_UNIX is not Native.
        stop0.send(()).unwrap();
        stop1.send(()).unwrap();
        task0.await.unwrap().unwrap();
        task1.await.unwrap().unwrap();
    }
    #[tokio::test]
    async fn absent_peer_response_hits_original_deadline_and_joins() {
        let (a, _peer) = transport_pair();
        let (tx, _rx) = watch::channel(Status::Starting);
        let (_stop, mut done) = oneshot::channel();
        let (_queries, incoming) = mpsc::channel(8);
        let error = exchange_loop(
            AsyncFd::new(a).unwrap(),
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
