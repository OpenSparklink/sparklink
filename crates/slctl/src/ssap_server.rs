//! Foreground application-owned SSAP service, not a second protocol Engine.
use crate::security_agent::{Input, remaining};
use anyhow::{bail, ensure};
use libsparklink::ssap::authorization::{self, AuthorizationContext, MethodAuthorizationContext};
use libsparklink::ssap::provider::frontend::{
    Dispatcher, Inbox, MethodInbox, MethodRequest, Request,
};
use slk_contract::ssap::{
    self as wire, MethodProviderReply, MethodProviderRequest, ReadProviderReply,
    ReadProviderRequest, SsapAuthorizationPrompt as Prompt,
};
use slk_protocol::{
    SsapOperations,
    ssap::access::{MethodAccess, SsapAccess},
};
use std::sync::{Arc, Mutex};
use tokio::sync::{Semaphore, mpsc, oneshot, watch};
use zbus::Connection;

const PATH: &str = "/org/sparklink/slctl/ssap_authorizer";
const PROVIDER_PATH: &str = "/org/sparklink/slctl/ssap_read_provider";
// A full 2045-byte method result plus command and the maximum local token length.
const INPUT_LIMIT: usize = 4160;
// Both frontend kinds share a process-wide namespace, including successive
// ssap-serve runs in an interactive slctl process. Wire IDs may be reused.
static NEXT_TOKEN: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
fn next_token() -> anyhow::Result<u64> {
    use std::sync::atomic::Ordering;
    NEXT_TOKEN
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
            value.checked_add(1)
        })
        .map(|previous| previous + 1)
        .map_err(|_| anyhow::anyhow!("local prompt namespace exhausted"))
}
#[derive(Clone, Copy)]
enum Policy {
    Ask,
    Allow,
    Deny,
}
struct Pending {
    token: u64,
    prompt: Prompt,
    reply: oneshot::Sender<bool>,
}
pub(crate) enum Definition {
    Property((Vec<u8>, u32, u32, Vec<u8>)),
    Method(Vec<u8>, u32),
}
#[derive(Clone, Copy)]
enum Requirements {
    Property(SsapOperations, SsapAccess),
    Method(MethodAccess),
}
struct PendingValue {
    token: u64,
    request: ApplicationRequest,
}
enum ApplicationRequest {
    Read(Request),
    Method(MethodRequest),
}
impl ApplicationRequest {
    fn active(&self) -> bool {
        match self {
            Self::Read(r) => r.is_active(),
            Self::Method(r) => r.is_active(),
        }
    }
    fn deadline(&self) -> u64 {
        match self {
            Self::Read(r) => r.request().deadline_ns,
            Self::Method(r) => r.request().deadline_ns,
        }
    }
    fn maximum(&self) -> u16 {
        match self {
            Self::Read(r) => r.request().maximum_bytes,
            Self::Method(r) => r.request().maximum_result_bytes,
        }
    }
    fn ceiling(&self) -> usize {
        match self {
            Self::Read(_) => wire::MAX_PROVIDER_VALUE_BYTES,
            Self::Method(_) => wire::MAX_METHOD_RESULT_BYTES,
        }
    }
    fn reply(&self, status: u16, value: &[u8]) -> std::io::Result<()> {
        match self {
            Self::Read(r) => r.reply(status, value),
            Self::Method(r) => r.reply(status, value),
        }
    }
    fn print_prompt(&self, token: u64) {
        match self {
            Self::Read(request) => {
                let r = request.request();
                println!(
                    "SsapReadProviderPrompt: token=p{} request={} index={} generation={} lifetime={} handle={} epoch={} security={} local_tcid={} remote_tcid={} pi={} property={} deadline_ns={} maximum_bytes={}; answer 'provide p{} HEX' ('-' for empty) or 'provider-error p{} AF..FF'",
                    token,
                    r.request_id,
                    r.identity.0,
                    r.identity.1,
                    r.identity.2,
                    r.identity.3,
                    r.identity.4,
                    r.identity.5,
                    r.identity.6,
                    r.identity.7,
                    r.identity.8,
                    r.property,
                    r.deadline_ns,
                    r.maximum_bytes,
                    token,
                    token
                );
            }
            Self::Method(request) => {
                let r = request.request();
                println!(
                    "SsapMethodProviderPrompt: token=p{} request={} index={} generation={} lifetime={} handle={} epoch={} security={} local_tcid={} remote_tcid={} pi={} method={} deadline_ns={} operation={} arguments={} maximum_result_bytes={}; answer 'provide p{} HEX' ('-' for empty) or 'provider-error p{} AF..FF'",
                    token,
                    r.request_id,
                    r.identity.0,
                    r.identity.1,
                    r.identity.2,
                    r.identity.3,
                    r.identity.4,
                    r.identity.5,
                    r.identity.6,
                    r.identity.7,
                    r.identity.8,
                    r.method,
                    r.deadline_ns,
                    r.operation,
                    crate::commands::hex_bytes(&r.arguments),
                    r.maximum_result_bytes,
                    token,
                    token
                );
            }
        }
    }
}
enum ApplicationInbox {
    Read(Inbox),
    Method(MethodInbox),
}

#[derive(Clone)]
struct FrontendScope {
    daemon: String,
    lost: watch::Receiver<bool>,
    generation: u64,
    index: u16,
    property: Arc<Mutex<Option<u16>>>,
    requirements: Requirements,
}
impl FrontendScope {
    fn admit(
        &self,
        prompt: &Prompt,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<Option<std::time::Instant>> {
        let handle = *self
            .property
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("owner state poisoned".into()))?;
        let controller = slk_contract::ControllerId {
            index: self.index,
            generation: self.generation,
        };
        let owner_lost = *self.lost.borrow() || self.lost.has_changed().is_err();
        match self.requirements {
            Requirements::Property(operations, access) => authorization::admit(
                &AuthorizationContext {
                    daemon_owner: &self.daemon,
                    owner_lost,
                    controller,
                    property: handle,
                    operations,
                    access,
                },
                sender,
                prompt,
            ),
            Requirements::Method(access) => authorization::admit_method(
                &MethodAuthorizationContext {
                    daemon_owner: &self.daemon,
                    owner_lost,
                    controller,
                    method: handle,
                    access,
                },
                sender,
                prompt,
            ),
        }
    }
}
struct Authorizer {
    scope: FrontendScope,
    policy: Policy,
    prompts: mpsc::Sender<Pending>,
    slot: Arc<Semaphore>,
}
impl Authorizer {
    fn admission(
        &self,
        prompt: &Prompt,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<Option<std::time::Instant>> {
        self.scope.admit(prompt, sender)
    }
}
#[zbus::interface(name = "org.sparklink.SsapAuthorizer")]
impl Authorizer {
    async fn authorize_value(
        &self,
        prompt: Prompt,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        let sender = header.sender().map(|name| name.as_str());
        let Some(original) = self.admission(&prompt, sender)? else {
            return Ok(false);
        };
        let Ok(_slot) = self.slot.clone().try_acquire_owned() else {
            return Ok(false);
        };
        let approved = match self.policy {
            Policy::Allow => true,
            Policy::Deny => false,
            Policy::Ask => {
                let (reply, result) = oneshot::channel();
                if self
                    .prompts
                    .try_send(Pending {
                        token: 0,
                        prompt: prompt.clone(),
                        reply,
                    })
                    .is_err()
                {
                    return Ok(false);
                }
                authorization::await_decision(result, self.scope.lost.clone(), original).await
            }
        };
        let approved = approved && self.admission(&prompt, sender)?.is_some();
        println!(
            "SsapAuthorizationDecision: request={} property={} data_type={} write={} security={} approved={approved}; local policy only",
            prompt.0, prompt.2, prompt.6, prompt.3, prompt.1.5
        );
        Ok(approved)
    }
}

struct ReadProvider {
    dispatcher: Arc<Dispatcher>,
}
#[zbus::interface(name = "org.sparklink.SsapReadProvider")]
impl ReadProvider {
    async fn read_value(
        &self,
        request: ReadProviderRequest,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<ReadProviderReply> {
        let sender = header.sender().map(|name| name.as_str());
        let request_id = request.request_id;
        let property = request.property;
        let outcome = self.dispatcher.dispatch(request, sender).await?;
        // The shared dispatcher has completed its fresh admission check. Keep
        // this local result before returning the callback, so a subsequent
        // request cannot print its decision ahead of this result. Local reply
        // acceptance alone is neither this outcome nor remote delivery.
        if outcome.reportable() {
            let response = outcome.reply();
            println!(
                "SsapReadProviderResult: request={} property={} status={} bytes={}; application response only",
                request_id,
                property,
                response.0,
                response.1.len()
            );
        }
        Ok(outcome.into_reply())
    }
}

struct MethodProvider {
    dispatcher: Arc<Dispatcher>,
}
#[zbus::interface(name = "org.sparklink.SsapMethodProvider")]
impl MethodProvider {
    async fn call_method(
        &self,
        request: MethodProviderRequest,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<MethodProviderReply> {
        let id = request.request_id;
        let method = request.method;
        let outcome = self
            .dispatcher
            .dispatch_method(request, header.sender().map(|n| n.as_str()))
            .await?;
        if outcome.reportable() {
            let response = outcome.reply();
            println!(
                "SsapMethodProviderResult: request={} method={} status={} bytes={}; application response only",
                id,
                method,
                response.0,
                response.1.len()
            );
        }
        let (status, value) = outcome.into_reply();
        let status = u8::try_from(status).map_err(|_| {
            zbus::fdo::Error::Failed("invalid method status from shared dispatcher".into())
        })?;
        Ok((status, value))
    }
}
async fn remove_provider(conn: &Connection, requirements: Requirements) -> zbus::Result<bool> {
    match requirements {
        Requirements::Property(..) => {
            conn.object_server()
                .remove::<ReadProvider, _>(PROVIDER_PATH)
                .await
        }
        Requirements::Method(..) => {
            conn.object_server()
                .remove::<MethodProvider, _>(PROVIDER_PATH)
                .await
        }
    }
}

fn input_decision(line: &str, token: u64) -> Option<bool> {
    if token == 0 {
        return None;
    }
    if line == format!("yes {token}") {
        Some(true)
    } else if line == format!("no {token}") {
        Some(false)
    } else {
        None
    }
}

fn input_value(line: &str, token: u64, maximum_bytes: u16) -> Option<ReadProviderReply> {
    input_result(line, token, maximum_bytes, wire::MAX_PROVIDER_VALUE_BYTES)
}
fn input_result(
    line: &str,
    token: u64,
    maximum_bytes: u16,
    ceiling: usize,
) -> Option<ReadProviderReply> {
    if token == 0 || usize::from(maximum_bytes) > ceiling {
        return None;
    }
    if let Some(value) = line.strip_prefix(&format!("provide p{token} ")) {
        if value == "-" {
            return Some((0, vec![]));
        }
        // Check the textual budget before decoding/allocating. Only exact hex
        // is accepted here; no extra fields, implicit empty value or prefix.
        if value.is_empty()
            || value.len() > usize::from(maximum_bytes) * 2
            || !value.bytes().all(|byte| byte.is_ascii_hexdigit())
        {
            return None;
        }
        return crate::commands::parse_hex_bytes(value)
            .ok()
            .map(|value| (0, value));
    }
    let status = line.strip_prefix(&format!("provider-error p{token} "))?;
    if status.len() != 2 || !status.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }
    let status = u16::from_str_radix(status, 16).ok()?;
    (wire::PROVIDER_UNAVAILABLE..=0xff)
        .contains(&status)
        .then(|| (status, vec![]))
}

fn reply_value(current: &mut Option<PendingValue>, line: &str) -> bool {
    let Some(pending) = current.as_ref() else {
        return false;
    };
    if !pending.request.active() || remaining(pending.request.deadline()).is_err() {
        current.take();
        return false;
    }
    let Some(value) = (match &pending.request {
        ApplicationRequest::Read(_) => input_value(line, pending.token, pending.request.maximum()),
        ApplicationRequest::Method(_) => input_result(
            line,
            pending.token,
            pending.request.maximum(),
            pending.request.ceiling(),
        ),
    }) else {
        return false;
    };
    current
        .take()
        .is_some_and(|pending| pending.request.reply(value.0, &value.1).is_ok())
}

fn stop_admission(
    handle: &Mutex<Option<u16>>,
    requests: &mut mpsc::Receiver<Pending>,
) -> anyhow::Result<()> {
    let stopped = handle
        .lock()
        .map(|mut handle| *handle = None)
        .map_err(|_| anyhow::anyhow!("owner state poisoned"));
    requests.close();
    while let Ok(pending) = requests.try_recv() {
        drop(pending);
    }
    stopped
}

fn stop_provider(inbox: &mut Option<ApplicationInbox>) {
    if let Some(inbox) = inbox.take() {
        match inbox {
            ApplicationInbox::Read(i) => i.close(),
            ApplicationInbox::Method(i) => i.close(),
        };
    }
}

async fn next_value(inbox: &Option<ApplicationInbox>) -> std::io::Result<ApplicationRequest> {
    match inbox {
        Some(ApplicationInbox::Read(i)) => i.next().await.map(ApplicationRequest::Read),
        Some(ApplicationInbox::Method(i)) => i.next().await.map(ApplicationRequest::Method),
        None => std::future::pending().await,
    }
}

pub(crate) async fn serve(
    conn: &Connection,
    client: &libsparklink::Client,
    controller: &str,
    service: Vec<u8>,
    definition: Definition,
    policy: &str,
) -> anyhow::Result<()> {
    let policy = match policy {
        "ask" => Policy::Ask,
        "allow" => Policy::Allow,
        "deny" => Policy::Deny,
        _ => bail!("policy must be ask, allow or deny"),
    };
    let (properties, methods, requirements) = match definition {
        Definition::Property((uuid, ops, access, value)) => {
            let operations = SsapOperations::from_bits(ops)?;
            let access_policy = SsapAccess::from_bits(access).map_err(anyhow::Error::msg)?;
            ensure!(
                slk_protocol::ssap::client_config::supported_owned(operations, true)
                    && value.len() <= 2042,
                "unsupported operations or missing CPCD for updates"
            );
            (
                vec![(uuid, ops, access, value)],
                vec![],
                Requirements::Property(operations, access_policy),
            )
        }
        Definition::Method(uuid, bits) => {
            let access = MethodAccess::from_bits(bits).map_err(anyhow::Error::msg)?;
            (vec![], vec![(uuid, bits)], Requirements::Method(access))
        }
    };
    let view = client.controller(controller).await?;
    let mut lost = client.owner_loss();
    let handle = Arc::new(Mutex::new(None));
    let scope = FrontendScope {
        daemon: client.daemon_owner().to_owned(),
        lost: lost.clone(),
        generation: view.id().generation,
        index: view.id().index,
        property: handle.clone(),
        requirements,
    };
    let authorizer_path = zbus::zvariant::OwnedObjectPath::try_from(PATH)?;
    let provider_path = zbus::zvariant::OwnedObjectPath::try_from(PROVIDER_PATH)?;
    let registration_deadline = libsparklink::Deadline::after(std::time::Duration::from_secs(5))?;
    let (prompts, mut requests) = mpsc::channel(1);
    let mut value_requests: Option<ApplicationInbox> = None;
    let dispatcher = Dispatcher::new(client, provider_path.clone())?;
    let _provider_watch = dispatcher.watch();
    let authorizer = Authorizer {
        scope,
        policy,
        prompts,
        slot: Arc::new(Semaphore::new(1)),
    };
    ensure!(
        conn.object_server().at(PATH, authorizer).await?,
        "authorizer path already registered"
    );
    let installed = match requirements {
        Requirements::Property(..) => {
            conn.object_server()
                .at(
                    PROVIDER_PATH,
                    ReadProvider {
                        dispatcher: dispatcher.clone(),
                    },
                )
                .await
        }
        Requirements::Method(..) => {
            conn.object_server()
                .at(
                    PROVIDER_PATH,
                    MethodProvider {
                        dispatcher: dispatcher.clone(),
                    },
                )
                .await
        }
    };
    match installed {
        Ok(true) => (),
        result => {
            // Only our authorizer was installed. An existing provider belongs
            // to another registration and must not be removed here.
            let _ = conn.object_server().remove::<Authorizer, _>(PATH).await;
            result?;
            bail!("provider path already registered");
        }
    }
    let result = view
        .local_services()
        .register_entries(
            service,
            properties,
            methods,
            authorizer_path,
            registration_deadline,
        )
        .await;
    let mut registration = match result {
        Ok(v) => v,
        Err(e) => {
            let _ = stop_admission(&handle, &mut requests);
            stop_provider(&mut value_requests);
            let _ = conn.object_server().remove::<Authorizer, _>(PATH).await;
            let _ = remove_provider(conn, requirements).await;
            return Err(e.into());
        }
    };
    let registered = registration.receipt().clone();
    let result = async {
        ensure!(registered.2.len() == 1, "one entry required");
        *handle.lock().map_err(|_| anyhow::anyhow!("owner state poisoned"))? = Some(registered.2[0]);
        match requirements {
            Requirements::Property(..) => println!("SsapOwnedService: start={} end={} property={}; local registration only", registered.0, registered.1, registered.2[0]),
            Requirements::Method(..) => println!("SsapOwnedMethod: start={} end={} method={}; local registration only", registered.0, registered.1, registered.2[0]),
        }
        let mut input = Input::stdin_with_limit(INPUT_LIMIT)?;
        let mut current: Option<Pending> = None;
        let mut current_value: Option<PendingValue> = None;
        loop {
            if current.as_ref().is_some_and(|p| p.reply.is_closed() || remaining(p.prompt.4).is_err()) {
                current.take();
            }
            if current_value.as_ref().is_some_and(|p| !p.request.active() || remaining(p.request.deadline()).is_err()) {
                current_value.take();
            }
            let budget = current.as_ref().map(|p| remaining(p.prompt.4).unwrap_or_default()).unwrap_or(std::time::Duration::from_secs(3600));
            let value_budget = current_value.as_ref().map(|p| remaining(p.request.deadline()).unwrap_or_default()).unwrap_or(std::time::Duration::from_secs(3600));
            tokio::select! {biased;
                _ = lost.changed() => bail!("original daemon lost"),
                result = tokio::signal::ctrl_c() => { result?; return Ok(()); },
                _ = tokio::time::sleep(budget), if current.is_some() => { current.take(); },
                _ = tokio::time::sleep(value_budget), if current_value.is_some() => { current_value.take(); },
                next = requests.recv() => {
                    let Some(mut next) = next else { bail!("authorizer stopped"); };
                    if next.reply.is_closed() || remaining(next.prompt.4).is_err() { continue; }
                    next.token = next_token()?;
                    input.discard_before_prompt()?;
                    println!("SsapAuthorizationPrompt: token={} request={} index={} generation={} lifetime={} handle={} epoch={} security={} property={} data_type={} write={} bytes={} deadline_ns={}; answer 'yes {}' or 'no {}'", next.token, next.prompt.0, next.prompt.1.0, next.prompt.1.1, next.prompt.1.2, next.prompt.1.3, next.prompt.1.4, next.prompt.1.5, next.prompt.2, next.prompt.6, next.prompt.3, next.prompt.5.len(), next.prompt.4, next.token, next.token);
                    current = Some(next);
                },
                next = next_value(&value_requests) => {
                    let request = next?;
                    if !request.active() || remaining(request.deadline()).is_err() { continue; }
                    let next = PendingValue { token: next_token()?, request };
                    input.discard_before_prompt()?;
                    next.request.print_prompt(next.token);
                    current_value = Some(next);
                },
                line = input.line() => {
                    let Some(line) = line? else { return Ok(()); };
                    if line == "quit" { return Ok(()); }
                    if line == "provider" {
                        let deadline = libsparklink::Deadline::after(std::time::Duration::from_secs(5))?;
                        value_requests = Some(match requirements {
                            Requirements::Property(operations, _) => {
                                ensure!(operations == SsapOperations::READ, "provider requires exactly READ operations (1)");
                                let inbox = dispatcher.bind(&mut registration, registered.2[0], deadline).await?;
                                println!("SsapReadProviderBound: handle={}; stored value discarded, no rebind or fallback", registered.2[0]);
                                ApplicationInbox::Read(inbox)
                            }
                            Requirements::Method(_) => {
                                let inbox = dispatcher.bind_method(&mut registration, registered.2[0], deadline).await?;
                                println!("SsapMethodProviderBound: handle={}; independent application result, no rebind or fallback", registered.2[0]);
                                ApplicationInbox::Method(inbox)
                            }
                        });
                        continue;
                    }
                    if line.starts_with("provide ") || line.starts_with("provider-error ") {
                        if !reply_value(&mut current_value, &line) {
                            println!("{}: rejected stale token, expired request or invalid value/status",
                                match requirements { Requirements::Property(..) => "SsapReadProviderInput", Requirements::Method(..) => "SsapMethodProviderInput" });
                        }
                        continue;
                    }
                    if line == "value" {
                        let value: Vec<u8> = registration.read_local(registered.2[0], libsparklink::Deadline::after(std::time::Duration::from_secs(5))?).await?;
                        println!("SsapOwnedValue: handle={} value={}", registered.2[0], crate::commands::hex_bytes(&value));
                        continue;
                    }
                    if let Some(description) = line.strip_prefix("description ") {
                        registration.set_description(registered.2[0], description.to_owned(),
                            libsparklink::Deadline::after(std::time::Duration::from_secs(5))?).await?;
                        println!("SsapOwnedDescription: handle={} bytes={}; local commit only", registered.2[0], description.len());
                        continue;
                    }
                    if let Some(value) = line.strip_prefix("replace ") {
                        let value = crate::commands::parse_hex_bytes(value)?;
                        registration.replace_local(registered.2[0], value,
                            libsparklink::Deadline::after(std::time::Duration::from_secs(5))?).await?;
                        println!("SsapOwnedReplaced: handle={}; local commit only", registered.2[0]);
                        continue;
                    }
                    if let Some((operation, path)) = line.split_once(' ')
                        && matches!(operation, "configuration" | "notify" | "indicate") {
                        let link = client.connection(controller, path).await?;
                        let remote = link.ssap();
                        let deadline = libsparklink::Deadline::after(std::time::Duration::from_secs(5))?;
                        if operation == "configuration" {
                            let modes = remote.owned_configuration(registered.2[0], deadline).await?;
                            println!("SsapOwnedConfiguration: handle={} modes={modes}; observation only", registered.2[0]);
                        } else {
                            let receipt = remote.send_owned_update(registered.2[0], operation == "indicate", deadline).await?;
                            println!("SsapOwnedUpdate: handle={} stage={} pdu={} ack={}; not application delivery",
                                registered.2[0], receipt.stage, crate::commands::hex_bytes(&receipt.pdu),
                                crate::commands::hex_bytes(&receipt.acknowledgement));
                        }
                        continue;
                    }
                    let Some(p) = current.as_ref() else { continue; };
                    let yes = input_decision(&line, p.token);
                    if let Some(yes) = yes && remaining(p.prompt.4).is_ok() && !p.reply.is_closed() {
                        let p = current.take().unwrap();
                        let _ = p.reply.send(yes);
                    }
                }
            }
        }
    }.await;
    // Ending the UI releases its current decisions and value requests. Stop
    // both frontends before asynchronous withdrawal; callbacks reject even
    // when removal is slow or fails. Local closure is not remote withdrawal.
    let stopped = stop_admission(&handle, &mut requests);
    stop_provider(&mut value_requests);
    dispatcher.stop();
    let removed = match libsparklink::Deadline::after(std::time::Duration::from_secs(1)) {
        Ok(deadline) => registration
            .unregister(deadline)
            .await
            .map_err(anyhow::Error::from),
        Err(error) => Err(error.into()),
    };
    let authorizer_removed = conn.object_server().remove::<Authorizer, _>(PATH).await;
    let provider_removed = remove_provider(conn, requirements).await;
    result?;
    stopped?;
    removed?;
    authorizer_removed?;
    provider_removed?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn setup(policy: Policy) -> (Authorizer, watch::Sender<bool>, mpsc::Receiver<Pending>) {
        let (owner, lost) = watch::channel(false);
        let (prompts, requests) = mpsc::channel(1);
        (
            Authorizer {
                scope: FrontendScope {
                    daemon: ":1.10".into(),
                    lost,
                    generation: 7,
                    index: 0,
                    property: Arc::new(Mutex::new(Some(17))),
                    requirements: Requirements::Property(
                        SsapOperations::from_bits(5).unwrap(),
                        SsapAccess::from_bits(36).unwrap(),
                    ),
                },
                policy,
                prompts,
                slot: Arc::new(Semaphore::new(1)),
            },
            owner,
            requests,
        )
    }
    fn message(sender: &str) -> zbus::Message {
        zbus::Message::method_call(PATH, "AuthorizeValue")
            .unwrap()
            .sender(sender)
            .unwrap()
            .build(&())
            .unwrap()
    }
    fn prompt() -> Prompt {
        let mut time = nix::libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        // SAFETY: live writable timespec; same clock as native request identity.
        assert_eq!(
            unsafe { nix::libc::clock_gettime(nix::libc::CLOCK_MONOTONIC, &mut time) },
            0
        );
        let deadline = time.tv_sec as u64 * 1_000_000_000 + time.tv_nsec as u64 + 1_000_000_000;
        (
            1,
            (0, 7, 13, 1, 41, 0, 10, 10, 0),
            17,
            false,
            deadline,
            vec![],
            0,
        )
    }

    #[test]
    fn provider_input_is_exact_bounded_and_separate_from_authorization() {
        assert_eq!(input_value("provide p1 -", 1, 0), Some((0, vec![])));
        assert_eq!(
            input_value("provide p1 aB09", 1, 2),
            Some((0, vec![0xab, 9]))
        );
        assert_eq!(
            input_value("provider-error p1 AF", 1, 0),
            Some((0xaf, vec![]))
        );
        assert_eq!(
            input_value("provider-error p1 ff", 1, 2042),
            Some((0xff, vec![]))
        );
        for line in [
            "provide 1 ab",
            "provide p01 ab",
            "provide p0 -",
            "provide p2 ab",
            "provide p1",
            "provide p1 ",
            "provide p1 a",
            "provide p1 0xab",
            "provide p1 ab extra",
            "provide p1 ab ",
            "provide p1  ab",
            "provide p1 āb",
            "provider-error p1 AE",
            "provider-error p1 100",
            "provider-error p1 0xAF",
            "provider-error p1 AF extra",
            "yes 1",
            "no 1",
        ] {
            assert_eq!(input_value(line, 1, 2042), None, "{line}");
        }
        assert_eq!(input_value("provide p1 00", 1, 0), None);
        assert_eq!(input_value("provide p1 -", 1, 2043), None);
        assert_eq!(input_value("provide p0 -", 0, 2042), None);
        assert_eq!(
            input_value(&format!("provide p1 {}", "ab".repeat(2043)), 1, 2042),
            None
        );
        let full = format!("provide p{} {}", u64::MAX, "ab".repeat(2042));
        assert!(full.len() < INPUT_LIMIT);
        assert_eq!(
            input_value(&full, u64::MAX, 2042),
            Some((0, vec![0xab; 2042]))
        );
        assert_eq!(input_decision("yes p1", 1), None);
        let first = next_token().unwrap();
        let second = next_token().unwrap();
        assert!(first > 0 && second > first);
    }

    #[test]
    fn method_input_budget_does_not_expand_read_or_command_contracts() {
        let full = format!("provide p1 {}", "a6".repeat(2045));
        assert!(full.len() < INPUT_LIMIT);
        assert_eq!(
            input_result(&full, 1, 2045, wire::MAX_METHOD_RESULT_BYTES),
            Some((0, vec![0xa6; 2045]))
        );
        assert_eq!(input_value(&full, 1, 2042), None);
        assert_eq!(
            input_result("provide p1 00", 1, 0, wire::MAX_METHOD_RESULT_BYTES),
            None
        );
        assert_eq!(
            input_result("provide p1 -", 1, 0, wire::MAX_METHOD_RESULT_BYTES),
            Some((0, vec![]))
        );
        assert_eq!(
            input_result("provide p1 -", 1, 2046, wire::MAX_METHOD_RESULT_BYTES),
            None
        );
    }

    #[tokio::test]
    async fn method_policy_checks_kind_arguments_security_and_original_context() {
        for (policy, allowed) in [(Policy::Allow, true), (Policy::Deny, false)] {
            let (mut owner, alive, mut requests) = setup(policy);
            owner.scope.requirements = Requirements::Method(MethodAccess::from_bits(4).unwrap());
            let mut valid = prompt();
            valid.3 = true;
            valid.6 = 3;
            valid.5 = vec![0x31; 2043];
            assert_eq!(
                owner
                    .authorize_value(valid.clone(), message(":1.10").header())
                    .await
                    .unwrap(),
                allowed
            );
            for kind in 0..5 {
                let mut p = valid.clone();
                match kind {
                    0 => p.6 = 0,
                    1 => p.3 = false,
                    2 => p.5.push(0),
                    3 => p.1.1 += 1,
                    _ => p.4 = 1,
                }
                assert!(
                    !owner
                        .authorize_value(p, message(":1.10").header())
                        .await
                        .unwrap()
                );
            }
            owner.scope.requirements = Requirements::Method(MethodAccess::from_bits(1).unwrap());
            assert!(
                !owner
                    .authorize_value(valid.clone(), message(":1.10").header())
                    .await
                    .unwrap()
            );
            owner.scope.requirements = Requirements::Method(MethodAccess::from_bits(4).unwrap());
            alive.send_replace(true);
            assert!(
                !owner
                    .authorize_value(valid, message(":1.10").header())
                    .await
                    .unwrap()
            );
            assert!(requests.try_recv().is_err());
            assert_eq!(owner.slot.available_permits(), 1);
        }
    }

    #[test]
    fn human_tokens_do_not_alias_engine_request_ids_or_expired_prompts() {
        assert_eq!(input_decision("yes 1", 1), Some(true));
        assert_eq!(input_decision("no 2", 2), Some(false));
        // A new lifetime may reuse wire request1; its next local prompt is2.
        assert_eq!(input_decision("yes 1", 2), None);
        for line in ["yes 0", "yes 2 extra", "yes 02", "yes -2", "approve 2"] {
            assert_eq!(input_decision(line, 2), None);
        }
        assert_eq!(input_decision("yes 0", 0), None);
    }
    #[tokio::test]
    async fn local_policy_requires_original_daemon_and_receipt_without_granting_security() {
        let (owner, _alive, _) = setup(Policy::Allow);
        let (denier, _deny_alive, _) = setup(Policy::Deny);
        let original = message(":1.10");
        assert!(
            owner
                .authorize_value(prompt(), original.header())
                .await
                .unwrap()
        );
        assert!(
            !denier
                .authorize_value(prompt(), original.header())
                .await
                .unwrap()
        );
        assert!(
            owner
                .authorize_value(prompt(), message(":1.11").header())
                .await
                .is_err()
        );
        for kind in 0..10 {
            let mut p = prompt();
            match kind {
                0 => p.0 = 0,
                1 => p.1.1 = 8,
                2 => p.1.2 = 0,
                3 => p.1.4 = 0,
                4 => p.1.6 = 31,
                5 => p.2 = 18,
                6 => p.4 = 1,
                7 => p.5 = vec![7],
                8 => p.5 = vec![7; 2043],
                _ => p.1.5 = 3,
            }
            assert!(!owner.authorize_value(p, original.header()).await.unwrap());
        }
        let (mut encrypted, _encrypted_alive, _) = setup(Policy::Allow);
        encrypted.scope.requirements = Requirements::Property(
            SsapOperations::from_bits(5).unwrap(),
            SsapAccess::from_bits(45).unwrap(),
        );
        assert!(
            !encrypted
                .authorize_value(prompt(), original.header())
                .await
                .unwrap()
        );
    }

    #[tokio::test]
    async fn command_only_property_cli_allow_and_deny_keep_write_value_boundaries() {
        // The actual CLI callback and shared admission, with explicit local
        // context fixtures; not a Native receipt or peer-delivery test.
        for (policy, allowed) in [(Policy::Allow, true), (Policy::Deny, false)] {
            let (mut owner, _alive, mut requests) = setup(policy);
            owner.scope.requirements = Requirements::Property(
                SsapOperations::from_bits(3).unwrap(),
                SsapAccess::from_bits(36).unwrap(),
            );
            for length in [0, 32, 2042, 2043] {
                let mut p = prompt();
                p.3 = true;
                p.5 = vec![0xa5; length];
                assert_eq!(
                    owner
                        .authorize_value(p.clone(), message(":1.10").header())
                        .await
                        .unwrap(),
                    allowed && length <= 2042
                );
                p.4 = 1;
                assert!(
                    !owner
                        .authorize_value(p, message(":1.10").header())
                        .await
                        .unwrap()
                );
                assert!(requests.try_recv().is_err());
            }
            assert_eq!(owner.slot.available_permits(), 1);
        }
    }

    #[tokio::test]
    async fn command_only_property_cli_ask_preserves_original_deadline_and_owner() {
        for case in 0..4 {
            let (mut authorizer, owner, mut requests) = setup(Policy::Ask);
            authorizer.scope.requirements = Requirements::Property(
                SsapOperations::from_bits(3).unwrap(),
                SsapAccess::from_bits(36).unwrap(),
            );
            let authorizer = Arc::new(authorizer);
            let caller = authorizer.clone();
            let mut p = prompt();
            p.3 = true; // Empty proposed write must remain a write prompt.
            if case == 2 {
                p.4 = libsparklink::Deadline::after(std::time::Duration::from_millis(500))
                    .unwrap()
                    .stamp()
                    .monotonic_ns;
            }
            let original = p.4;
            let work = tokio::spawn(async move {
                caller
                    .authorize_value(p, message(":1.10").header())
                    .await
                    .unwrap()
            });
            let pending = tokio::time::timeout(std::time::Duration::from_secs(1), requests.recv())
                .await
                .expect("actual CLI command prompt must be dispatched")
                .unwrap();
            assert!(pending.prompt.3 && pending.prompt.5.is_empty());
            assert_eq!(pending.prompt.4, original);
            if case < 2 {
                pending.reply.send(case == 0).unwrap();
                assert_eq!(work.await.unwrap(), case == 0);
            } else {
                if case == 3 {
                    owner.send_replace(true);
                } // Otherwise keep the reply pending through original expiry.
                assert!(
                    !tokio::time::timeout(std::time::Duration::from_secs(2), work)
                        .await
                        .unwrap()
                        .unwrap()
                );
                assert!(pending.reply.send(true).is_err());
            }
            assert_eq!(authorizer.slot.available_permits(), 1);
            assert!(requests.try_recv().is_err());
        }
    }

    #[tokio::test]
    async fn actual_cli_endpoint_keeps_one_pending_and_rechecks_receipt_after_policy() {
        let (authorizer, _owner, mut requests) = setup(Policy::Ask);
        let authorizer = Arc::new(authorizer);
        let caller = authorizer.clone();
        let work = tokio::spawn(async move {
            let message = message(":1.10");
            caller
                .authorize_value(prompt(), message.header())
                .await
                .unwrap()
        });
        let pending = requests.recv().await.unwrap();
        pending.reply.send(true).unwrap();
        assert!(work.await.unwrap());
        let caller = authorizer.clone();
        let work = tokio::spawn(async move {
            let message = message(":1.10");
            caller
                .authorize_value(prompt(), message.header())
                .await
                .unwrap()
        });
        let pending = requests.recv().await.unwrap();
        assert_eq!(pending.prompt.2, 17);
        // No second UI request while the actual first permit is held.
        assert!(
            !authorizer
                .authorize_value(prompt(), message(":1.10").header())
                .await
                .unwrap()
        );
        assert!(requests.try_recv().is_err());
        stop_admission(&authorizer.scope.property, &mut requests).unwrap();
        pending.reply.send(true).unwrap();
        assert!(
            !work.await.unwrap(),
            "policy yes cannot revive a retired binding"
        );
        assert_eq!(authorizer.slot.available_permits(), 1);
        assert!(requests.is_closed());
        assert!(authorizer.scope.property.lock().unwrap().is_none());
    }

    #[tokio::test]
    async fn actual_cli_owner_exit_expiry_and_closed_ui_do_not_approve_or_retain_permits() {
        for case in 0..3 {
            let (authorizer, owner, mut requests) = setup(Policy::Ask);
            let authorizer = Arc::new(authorizer);
            let caller = authorizer.clone();
            let mut p = prompt();
            if case == 1 {
                p.4 = libsparklink::Deadline::after(std::time::Duration::from_millis(20))
                    .unwrap()
                    .stamp()
                    .monotonic_ns;
            }
            let work = tokio::spawn(async move {
                let message = message(":1.10");
                caller.authorize_value(p, message.header()).await.unwrap()
            });
            let pending = requests.recv().await.unwrap();
            match case {
                0 => {
                    owner.send_replace(true);
                }
                1 => {} // Keep actual reply pending through its original expiry.
                _ => {
                    drop(pending);
                    assert!(!work.await.unwrap());
                    assert_eq!(authorizer.slot.available_permits(), 1);
                    continue;
                }
            }
            assert!(!work.await.unwrap());
            assert!(
                pending.reply.send(true).is_err(),
                "late yes cannot reach a completed callback"
            );
            assert_eq!(authorizer.slot.available_permits(), 1);
        }
    }
}
