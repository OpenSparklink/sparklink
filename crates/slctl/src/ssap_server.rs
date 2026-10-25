//! Foreground application-owned SSAP service, not a second protocol Engine.
use crate::security_agent::{Input, remaining};
use anyhow::{bail, ensure};
use libsparklink::ssap::authorization::{self, AuthorizationContext};
use libsparklink::ssap::provider;
use slk_contract::ssap::{
    self as wire, ReadProviderReply, ReadProviderRequest, SsapAuthorizationPrompt as Prompt,
};
use slk_protocol::{SsapOperations, ssap::access::SsapAccess};
use std::sync::{Arc, Mutex};
use tokio::sync::{Semaphore, mpsc, oneshot, watch};
use zbus::Connection;

const PATH: &str = "/org/sparklink/slctl/ssap_authorizer";
const PROVIDER_PATH: &str = "/org/sparklink/slctl/ssap_read_provider";
// A full 2042-byte value plus command and the maximum local token length.
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
struct PendingValue {
    token: u64,
    request: ReadProviderRequest,
    reply: oneshot::Sender<ReadProviderReply>,
}
#[derive(Clone)]
struct FrontendScope {
    daemon: String,
    lost: watch::Receiver<bool>,
    generation: u64,
    index: u16,
    property: Arc<Mutex<Option<u16>>>,
    operations: SsapOperations,
    access: SsapAccess,
}
impl FrontendScope {
    fn snapshot(&self) -> zbus::fdo::Result<AuthorizationContext<'_>> {
        let property = *self
            .property
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("owner state poisoned".into()))?;
        Ok(AuthorizationContext {
            daemon_owner: &self.daemon,
            owner_lost: *self.lost.borrow() || self.lost.has_changed().is_err(),
            controller: slk_contract::ControllerId {
                index: self.index,
                generation: self.generation,
            },
            property,
            operations: self.operations,
            access: self.access,
        })
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
        authorization::admit(&self.scope.snapshot()?, sender, prompt)
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
    scope: FrontendScope,
    prompts: mpsc::Sender<PendingValue>,
    slot: Arc<Semaphore>,
}
impl ReadProvider {
    fn admission(
        &self,
        request: &ReadProviderRequest,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<Option<std::time::Instant>> {
        provider::admit(&self.scope.snapshot()?, sender, request)
    }
}
#[zbus::interface(name = "org.sparklink.SsapReadProvider")]
impl ReadProvider {
    async fn read_value(
        &self,
        request: ReadProviderRequest,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<ReadProviderReply> {
        let sender = header.sender().map(|name| name.as_str());
        let Some(original) = self.admission(&request, sender)? else {
            return Ok((wire::PROVIDER_UNAVAILABLE, vec![]));
        };
        // Independent of the authorizer: a decision does not reserve the value
        // provider slot, and a pending value never implies authorization.
        let Ok(_slot) = self.slot.clone().try_acquire_owned() else {
            return Ok((wire::PROVIDER_UNAVAILABLE, vec![]));
        };
        let (reply, result) = oneshot::channel();
        if self
            .prompts
            .try_send(PendingValue {
                token: 0,
                request: request.clone(),
                reply,
            })
            .is_err()
        {
            return Ok((wire::PROVIDER_UNAVAILABLE, vec![]));
        }
        let response = provider::await_reply(
            result,
            self.scope.lost.clone(),
            original,
            request.maximum_bytes,
        )
        .await;
        if self.admission(&request, sender)?.is_none() {
            return Ok((wire::PROVIDER_UNAVAILABLE, vec![]));
        }
        println!(
            "SsapReadProviderResult: request={} property={} status={} bytes={}; application response only",
            request.request_id,
            request.property,
            response.0,
            response.1.len()
        );
        Ok(response)
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
    if token == 0 || usize::from(maximum_bytes) > wire::MAX_PROVIDER_VALUE_BYTES {
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
    if pending.reply.is_closed() || remaining(pending.request.deadline_ns).is_err() {
        current.take();
        return false;
    }
    let Some(value) = input_value(line, pending.token, pending.request.maximum_bytes) else {
        return false;
    };
    current
        .take()
        .is_some_and(|pending| pending.reply.send(value).is_ok())
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

fn stop_provider(requests: &mut mpsc::Receiver<PendingValue>) {
    requests.close();
    while let Ok(pending) = requests.try_recv() {
        drop(pending);
    }
}

pub(crate) async fn serve(
    conn: &Connection,
    client: &libsparklink::Client,
    controller: &str,
    service: Vec<u8>,
    definition: (Vec<u8>, u32, u32, Vec<u8>),
    policy: &str,
) -> anyhow::Result<()> {
    let (property, ops, access, value) = definition;
    let policy = match policy {
        "ask" => Policy::Ask,
        "allow" => Policy::Allow,
        "deny" => Policy::Deny,
        _ => bail!("policy must be ask, allow or deny"),
    };
    let access_policy = SsapAccess::from_bits(access).map_err(anyhow::Error::msg)?;
    let operations = SsapOperations::from_bits(ops)?;
    ensure!(
        slk_protocol::ssap::client_config::supported_owned(operations, true) && value.len() <= 2042,
        "unsupported operations or missing CPCD for updates"
    );
    let view = client.controller(controller).await?;
    let mut lost = client.owner_loss();
    let handle = Arc::new(Mutex::new(None));
    let scope = FrontendScope {
        daemon: client.daemon_owner().to_owned(),
        lost: lost.clone(),
        generation: view.id().generation,
        index: view.id().index,
        property: handle.clone(),
        operations,
        access: access_policy,
    };
    let authorizer_path = zbus::zvariant::OwnedObjectPath::try_from(PATH)?;
    let provider_path = zbus::zvariant::OwnedObjectPath::try_from(PROVIDER_PATH)?;
    let registration_deadline = libsparklink::Deadline::after(std::time::Duration::from_secs(5))?;
    let (prompts, mut requests) = mpsc::channel(1);
    let (values, mut value_requests) = mpsc::channel(1);
    let authorizer = Authorizer {
        scope: scope.clone(),
        policy,
        prompts,
        slot: Arc::new(Semaphore::new(1)),
    };
    let read_provider = ReadProvider {
        scope,
        prompts: values,
        slot: Arc::new(Semaphore::new(1)),
    };
    ensure!(
        conn.object_server().at(PATH, authorizer).await?,
        "authorizer path already registered"
    );
    match conn.object_server().at(PROVIDER_PATH, read_provider).await {
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
        .register_service(
            service,
            vec![(property, ops, access, value)],
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
            let _ = conn
                .object_server()
                .remove::<ReadProvider, _>(PROVIDER_PATH)
                .await;
            return Err(e.into());
        }
    };
    let registered = registration.receipt().clone();
    let result = async {
        ensure!(registered.2.len() == 1, "one property required");
        *handle.lock().map_err(|_| anyhow::anyhow!("owner state poisoned"))? = Some(registered.2[0]);
        println!("SsapOwnedService: start={} end={} property={}; local registration only", registered.0, registered.1, registered.2[0]);
        let mut input = Input::stdin_with_limit(INPUT_LIMIT)?;
        let mut current: Option<Pending> = None;
        let mut current_value: Option<PendingValue> = None;
        loop {
            if current.as_ref().is_some_and(|p| p.reply.is_closed() || remaining(p.prompt.4).is_err()) {
                current.take();
            }
            if current_value.as_ref().is_some_and(|p| p.reply.is_closed() || remaining(p.request.deadline_ns).is_err()) {
                current_value.take();
            }
            let budget = current.as_ref().map(|p| remaining(p.prompt.4).unwrap_or_default()).unwrap_or(std::time::Duration::from_secs(3600));
            let value_budget = current_value.as_ref().map(|p| remaining(p.request.deadline_ns).unwrap_or_default()).unwrap_or(std::time::Duration::from_secs(3600));
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
                next = value_requests.recv() => {
                    let Some(mut next) = next else { bail!("provider stopped"); };
                    if next.reply.is_closed() || remaining(next.request.deadline_ns).is_err() { continue; }
                    next.token = next_token()?;
                    input.discard_before_prompt()?;
                    let r = &next.request;
                    println!("SsapReadProviderPrompt: token=p{} request={} index={} generation={} lifetime={} handle={} epoch={} security={} local_tcid={} remote_tcid={} pi={} property={} deadline_ns={} maximum_bytes={}; answer 'provide p{} HEX' ('-' for empty) or 'provider-error p{} AF..FF'", next.token, r.request_id, r.identity.0, r.identity.1, r.identity.2, r.identity.3, r.identity.4, r.identity.5, r.identity.6, r.identity.7, r.identity.8, r.property, r.deadline_ns, r.maximum_bytes, next.token, next.token);
                    current_value = Some(next);
                },
                line = input.line() => {
                    let Some(line) = line? else { return Ok(()); };
                    if line == "quit" { return Ok(()); }
                    if line == "provider" {
                        ensure!(operations == SsapOperations::READ, "provider requires exactly READ operations (1)");
                        registration.bind_read_provider(registered.2[0], provider_path.clone(),
                            libsparklink::Deadline::after(std::time::Duration::from_secs(5))?).await?;
                        println!("SsapReadProviderBound: handle={}; stored value discarded, no rebind or fallback", registered.2[0]);
                        continue;
                    }
                    if line.starts_with("provide ") || line.starts_with("provider-error ") {
                        if !reply_value(&mut current_value, &line) {
                            println!("SsapReadProviderInput: rejected stale token, expired request or invalid value/status");
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
    // Ending the UI drops its current oneshot senders. Stop the shared handle
    // and drain queued senders before any asynchronous withdrawal; callbacks
    // wake and reject even when removal is slow or fails.
    let stopped = stop_admission(&handle, &mut requests);
    stop_provider(&mut value_requests);
    let removed = match libsparklink::Deadline::after(std::time::Duration::from_secs(1)) {
        Ok(deadline) => registration
            .unregister(deadline)
            .await
            .map_err(anyhow::Error::from),
        Err(error) => Err(error.into()),
    };
    let authorizer_removed = conn.object_server().remove::<Authorizer, _>(PATH).await;
    let provider_removed = conn
        .object_server()
        .remove::<ReadProvider, _>(PROVIDER_PATH)
        .await;
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
                    operations: SsapOperations::from_bits(5).unwrap(),
                    access: SsapAccess::from_bits(36).unwrap(),
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

    fn provider_setup() -> (
        ReadProvider,
        watch::Sender<bool>,
        mpsc::Receiver<PendingValue>,
    ) {
        let (mut authorizer, alive, _) = setup(Policy::Ask);
        authorizer.scope.operations = SsapOperations::READ;
        let (prompts, requests) = mpsc::channel(1);
        (
            ReadProvider {
                scope: authorizer.scope,
                prompts,
                slot: Arc::new(Semaphore::new(1)),
            },
            alive,
            requests,
        )
    }
    fn read_request() -> ReadProviderRequest {
        let p = prompt();
        ReadProviderRequest {
            request_id: p.0,
            identity: p.1,
            property: p.2,
            deadline_ns: p.4,
            maximum_bytes: 2042,
        }
    }
    fn provider_message(sender: &str) -> zbus::Message {
        zbus::Message::method_call(PROVIDER_PATH, wire::READ_PROVIDER_METHOD)
            .unwrap()
            .sender(sender)
            .unwrap()
            .build(&())
            .unwrap()
    }
    fn read_callback(
        provider: Arc<ReadProvider>,
        request: ReadProviderRequest,
    ) -> tokio::task::JoinHandle<ReadProviderReply> {
        tokio::spawn(async move {
            provider
                .read_value(request, provider_message(":1.10").header())
                .await
                .unwrap()
        })
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

    #[tokio::test]
    async fn provider_input_cannot_reuse_wrong_late_or_consumed_tokens() {
        let (reply, result) = oneshot::channel();
        let mut current = Some(PendingValue {
            token: 7,
            request: read_request(),
            reply,
        });
        assert!(!reply_value(&mut current, "provide p8 ab"));
        assert!(current.is_some());
        assert!(reply_value(&mut current, "provide p7 -"));
        assert_eq!(result.await.unwrap(), (0, vec![]));
        assert!(!reply_value(&mut current, "provide p7 ab"));
        for closed in [false, true] {
            let (reply, result) = oneshot::channel();
            let mut request = read_request();
            if !closed {
                request.deadline_ns = 1;
            }
            let mut current = Some(PendingValue {
                token: 9,
                request,
                reply,
            });
            if closed {
                drop(result);
                assert!(!reply_value(&mut current, "provide p9 ab"));
            } else {
                assert!(!reply_value(&mut current, "provide p9 ab"));
                assert!(result.await.is_err());
            }
            assert!(current.is_none());
        }
    }

    #[tokio::test]
    async fn actual_provider_endpoint_checks_admission_before_dispatch() {
        let (mut endpoint, _alive, mut requests) = provider_setup();
        assert!(
            endpoint
                .read_value(read_request(), provider_message(":1.11").header())
                .await
                .is_err()
        );
        for case in 0..8 {
            let mut request = read_request();
            match case {
                0 => request.request_id = 0,
                1 => request.maximum_bytes = 2043,
                2 => request.identity.3 = 0x1000,
                3 => request.identity.1 = 0,
                4 => request.property = 0,
                5 => request.deadline_ns = 1,
                6 => request.identity.4 = 0,
                _ => request.identity.5 = 3,
            }
            assert_eq!(
                endpoint
                    .read_value(request, provider_message(":1.10").header())
                    .await
                    .unwrap(),
                (wire::PROVIDER_UNAVAILABLE, vec![])
            );
            assert!(requests.try_recv().is_err());
        }
        endpoint.scope.operations = SsapOperations::from_bits(5).unwrap();
        assert_eq!(
            endpoint
                .read_value(read_request(), provider_message(":1.10").header())
                .await
                .unwrap(),
            (wire::PROVIDER_UNAVAILABLE, vec![])
        );
        assert_eq!(endpoint.slot.available_permits(), 1);
    }

    #[tokio::test]
    async fn actual_provider_endpoint_returns_explicit_empty_value_or_application_error() {
        // Actual endpoint and production SDK wait; no protocol Engine fixture.
        for (maximum, reply, expected) in [
            (0, (0, vec![]), (0, vec![])),
            (2042, (0, vec![0x5a; 2042]), (0, vec![0x5a; 2042])),
            (2042, (0xaf, vec![]), (0xaf, vec![])),
            (2042, (0xff, vec![]), (0xff, vec![])),
            (0, (0, vec![0]), (0xaf, vec![])),
            (2042, (0, vec![0; 2043]), (0xaf, vec![])),
            (2042, (1, vec![]), (0xaf, vec![])),
            (2042, (0xaf, vec![0]), (0xaf, vec![])),
        ] {
            let (endpoint, _alive, mut requests) = provider_setup();
            let endpoint = Arc::new(endpoint);
            let mut request = read_request();
            request.maximum_bytes = maximum;
            let original = request.clone();
            let work = read_callback(endpoint.clone(), request);
            let pending = requests.recv().await.unwrap();
            assert_eq!(pending.request, original);
            assert_eq!(endpoint.slot.available_permits(), 0);
            pending.reply.send(reply).unwrap();
            assert_eq!(work.await.unwrap(), expected);
            assert_eq!(endpoint.slot.available_permits(), 1);
        }
    }

    #[tokio::test]
    async fn actual_provider_permit_and_fresh_snapshot_survive_owner_exit_and_expiry() {
        for case in 0..5 {
            let (endpoint, alive, mut requests) = provider_setup();
            let endpoint = Arc::new(endpoint);
            let mut request = read_request();
            if case == 2 {
                request.deadline_ns =
                    libsparklink::Deadline::after(std::time::Duration::from_millis(30))
                        .unwrap()
                        .stamp()
                        .monotonic_ns;
            }
            let work = read_callback(endpoint.clone(), request);
            let pending = requests.recv().await.unwrap();
            assert_eq!(
                endpoint
                    .read_value(read_request(), provider_message(":1.10").header())
                    .await
                    .unwrap(),
                (wire::PROVIDER_UNAVAILABLE, vec![])
            );
            assert!(requests.try_recv().is_err());
            match case {
                0 => {
                    alive.send_replace(true);
                }
                1 => drop(alive),
                2 => (), // Keep sender live through the original expiry.
                3 => {
                    *endpoint.scope.property.lock().unwrap() = None;
                }
                _ => {
                    drop(pending);
                    assert_eq!(work.await.unwrap(), (wire::PROVIDER_UNAVAILABLE, vec![]));
                    assert_eq!(endpoint.slot.available_permits(), 1);
                    continue;
                }
            }
            if case == 3 {
                pending.reply.send((0, vec![1])).unwrap();
            } else {
                assert_eq!(
                    tokio::time::timeout(std::time::Duration::from_secs(1), work)
                        .await
                        .unwrap()
                        .unwrap(),
                    (wire::PROVIDER_UNAVAILABLE, vec![])
                );
                assert!(pending.reply.send((0, vec![1])).is_err());
                assert_eq!(endpoint.slot.available_permits(), 1);
                continue;
            }
            assert_eq!(work.await.unwrap(), (wire::PROVIDER_UNAVAILABLE, vec![]));
            assert_eq!(endpoint.slot.available_permits(), 1);
        }
    }

    #[tokio::test]
    async fn shared_handle_stops_both_queues_without_sharing_callback_permits() {
        let (mut authorizer, _alive, mut requests) = setup(Policy::Ask);
        authorizer.scope.operations = SsapOperations::READ;
        let (prompts, mut values) = mpsc::channel(1);
        let endpoint = Arc::new(ReadProvider {
            scope: authorizer.scope.clone(),
            prompts,
            slot: Arc::new(Semaphore::new(1)),
        });
        let authorizer = Arc::new(authorizer);
        let caller = authorizer.clone();
        let approval = tokio::spawn(async move {
            caller
                .authorize_value(prompt(), message(":1.10").header())
                .await
                .unwrap()
        });
        let decision = requests.recv().await.unwrap();
        assert_eq!(authorizer.slot.available_permits(), 0);
        let work = read_callback(endpoint.clone(), read_request());
        let value = values.recv().await.unwrap();
        value.reply.send((0, vec![1, 2])).unwrap();
        assert_eq!(work.await.unwrap(), (0, vec![1, 2]));
        assert_eq!(
            authorizer.slot.available_permits(),
            0,
            "provider does not complete approval"
        );
        decision.reply.send(false).unwrap();
        assert!(!approval.await.unwrap());

        let work = read_callback(endpoint.clone(), read_request());
        // Wait until the actual endpoint queued its request, without taking the
        // sender: shutdown must drain the queue and wake that callback itself.
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while values.is_empty() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("actual provider must queue its request");
        stop_admission(&authorizer.scope.property, &mut requests).unwrap();
        stop_provider(&mut values);
        assert_eq!(work.await.unwrap(), (wire::PROVIDER_UNAVAILABLE, vec![]));
        assert!(values.is_closed() && requests.is_closed());
        assert_eq!(endpoint.slot.available_permits(), 1);
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
        encrypted.scope.access = SsapAccess::from_bits(45).unwrap();
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
            owner.scope.operations = SsapOperations::from_bits(3).unwrap();
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
            authorizer.scope.operations = SsapOperations::from_bits(3).unwrap();
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
