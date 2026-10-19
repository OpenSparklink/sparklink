//! Foreground application-owned SSAP service, not a second protocol Engine.
use crate::security_agent::{Input, remaining};
use anyhow::{bail, ensure};
use slk_protocol::{
    SsapOperations,
    ssap::{SsapAuthorizationPrompt as Prompt, access::SsapAccess},
};
use std::sync::{Arc, Mutex};
use tokio::sync::{Semaphore, mpsc, oneshot, watch};
use zbus::Connection;

const PATH: &str = "/org/sparklink/slctl/ssap_authorizer";
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
struct Authorizer {
    daemon: String,
    lost: watch::Receiver<bool>,
    generation: u64,
    index: u16,
    property: Arc<Mutex<Option<u16>>>,
    operations: SsapOperations,
    access: SsapAccess,
    policy: Policy,
    prompts: mpsc::Sender<Pending>,
    slot: Arc<Semaphore>,
}
#[zbus::interface(name = "org.sparklink.SsapAuthorizer")]
impl Authorizer {
    async fn authorize_value(
        &self,
        prompt: Prompt,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<bool> {
        if header
            .sender()
            .is_none_or(|name| name.as_str() != self.daemon)
        {
            return Err(zbus::fdo::Error::AccessDenied(
                "not the original daemon".into(),
            ));
        }
        let property = *self
            .property
            .lock()
            .map_err(|_| zbus::fdo::Error::Failed("owner state poisoned".into()))?;
        let id = prompt.1;
        if *self.lost.borrow()
            || prompt.0 == 0
            || property != Some(prompt.2)
            || id.0 != self.index
            || id.1 != self.generation
            || id.2 == 0
            || id.4 == 0
            || id.5 > 2
            || (id.6, id.7, id.8) != (10, 10, 0)
            || prompt.5.len() > 2042
            || !prompt.3 && !prompt.5.is_empty()
            || self
                .access
                .check_authorization_result(id.5, prompt.3, true)
                .is_err()
            || !self.operations.contains(if prompt.3 {
                SsapOperations::WRITE_WITH_RSP
            } else {
                SsapOperations::READ
            })
        {
            return Ok(false);
        }
        let Ok(_slot) = self.slot.clone().try_acquire_owned() else {
            return Ok(false);
        };
        let Ok(budget) = remaining(prompt.4) else {
            return Ok(false);
        };
        if budget > std::time::Duration::from_secs(5) {
            return Ok(false);
        }
        let approved = match self.policy {
            Policy::Allow => true,
            Policy::Deny => false,
            Policy::Ask => {
                let (reply, result) = oneshot::channel();
                let deadline = prompt.4;
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
                let mut lost = self.lost.clone();
                tokio::select! {biased;
                    _=lost.changed()=>false,
                    result=tokio::time::timeout(remaining(deadline).unwrap_or_default(),result)=>matches!(result,Ok(Ok(true))),
                }
            }
        };
        let approved = approved && !*self.lost.borrow() && remaining(prompt.4).is_ok();
        println!(
            "SsapAuthorizationDecision: request={} property={} write={} security={} approved={approved}; local policy only",
            prompt.0, prompt.2, prompt.3, id.5
        );
        Ok(approved)
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
        operations.bits() & !5 == 0 && value.len() <= 2042,
        "only bounded READ/WRITE_WITH_RSP values supported"
    );
    let view = client.controller(controller).await?;
    let generation = view.id().generation;
    let index = view.id().index;
    let mut lost = client.owner_loss();
    let handle = Arc::new(Mutex::new(None));
    let (prompts, mut requests) = mpsc::channel(1);
    let authorizer = Authorizer {
        daemon: client.daemon_owner().to_owned(),
        lost: lost.clone(),
        generation,
        index,
        property: handle.clone(),
        operations,
        access: access_policy,
        policy,
        prompts,
        slot: Arc::new(Semaphore::new(1)),
    };
    ensure!(
        conn.object_server().at(PATH, authorizer).await?,
        "authorizer path already registered"
    );
    let result = view
        .local_services()
        .register_service(
            service,
            vec![(property, ops, access, value)],
            zbus::zvariant::OwnedObjectPath::try_from(PATH)?,
            libsparklink::Deadline::after(std::time::Duration::from_secs(5))?,
        )
        .await;
    let mut registration = match result {
        Ok(v) => v,
        Err(e) => {
            let _ = conn.object_server().remove::<Authorizer, _>(PATH).await;
            return Err(e.into());
        }
    };
    let registered = registration.receipt().clone();
    let result=async {
        ensure!(registered.2.len()==1,"one property required");
        *handle.lock().map_err(|_|anyhow::anyhow!("owner state poisoned"))?=Some(registered.2[0]);
        println!("SsapOwnedService: start={} end={} property={}; local registration only",registered.0,registered.1,registered.2[0]);
        let mut input=Input::stdin()?;
        let mut current:Option<Pending>=None;
        // Original request IDs are per Engine/lifetime. Never use them as
        // human reply tokens across multiple connections on this publisher.
        let mut next_token=0u64;
        loop {
            if current.as_ref().is_some_and(|p|p.reply.is_closed() || remaining(p.prompt.4).is_err()) {current.take();}
            let budget=current.as_ref().map(|p|remaining(p.prompt.4).unwrap_or_default()).unwrap_or(std::time::Duration::from_secs(3600));
            tokio::select! {biased;
                _=lost.changed()=>bail!("original daemon lost"),
                result=tokio::signal::ctrl_c()=>{result?;return Ok(());},
                _=tokio::time::sleep(budget),if current.is_some()=>{current.take();},
                next=requests.recv()=>{
                    let Some(mut next)=next else {bail!("authorizer stopped");};
                    if next.reply.is_closed() || remaining(next.prompt.4).is_err() {continue;}
                    next_token=next_token.checked_add(1).ok_or_else(||anyhow::anyhow!("local prompt namespace exhausted"))?;
                    next.token=next_token;
                    input.discard_before_prompt()?;
                    println!("SsapAuthorizationPrompt: token={} request={} index={} generation={} lifetime={} handle={} epoch={} security={} property={} write={} bytes={} deadline_ns={}; answer 'yes {}' or 'no {}'",next.token,next.prompt.0,next.prompt.1.0,next.prompt.1.1,next.prompt.1.2,next.prompt.1.3,next.prompt.1.4,next.prompt.1.5,next.prompt.2,next.prompt.3,next.prompt.5.len(),next.prompt.4,next.token,next.token);
                    current=Some(next);
                },
                line=input.line()=>{
                    let Some(line)=line? else {return Ok(());};
                    if line=="quit" {return Ok(());}
                    if line=="value" {
                        let value:Vec<u8>=registration.read_local(registered.2[0], libsparklink::Deadline::after(std::time::Duration::from_secs(5))?).await?;
                        println!("SsapOwnedValue: handle={} value={}",registered.2[0],crate::commands::hex_bytes(&value));
                        continue;
                    }
                    let Some(p)=current.as_ref() else {continue;};
                    let yes=input_decision(&line,p.token);
                    if let Some(yes)=yes && remaining(p.prompt.4).is_ok() && !p.reply.is_closed() {let p=current.take().unwrap();let _=p.reply.send(yes);}
                }
            }
        }
    }.await;
    let removed = registration
        .unregister(libsparklink::Deadline::after(
            std::time::Duration::from_secs(1),
        )?)
        .await;
    let _ = conn.object_server().remove::<Authorizer, _>(PATH).await;
    result?;
    removed?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn authorizer(policy: Policy) -> Authorizer {
        let (_, lost) = watch::channel(false);
        let (prompts, _) = mpsc::channel(1);
        Authorizer {
            daemon: ":1.10".into(),
            lost,
            generation: 7,
            index: 0,
            property: Arc::new(Mutex::new(Some(17))),
            operations: SsapOperations::from_bits(5).unwrap(),
            access: SsapAccess::from_bits(36).unwrap(),
            policy,
            prompts,
            slot: Arc::new(Semaphore::new(1)),
        }
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
        )
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
        let owner = authorizer(Policy::Allow);
        let original = message(":1.10");
        assert!(
            owner
                .authorize_value(prompt(), original.header())
                .await
                .unwrap()
        );
        assert!(
            !authorizer(Policy::Deny)
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
        let mut encrypted = authorizer(Policy::Allow);
        encrypted.access = SsapAccess::from_bits(45).unwrap();
        assert!(
            !encrypted
                .authorize_value(prompt(), original.header())
                .await
                .unwrap()
        );
    }
}
