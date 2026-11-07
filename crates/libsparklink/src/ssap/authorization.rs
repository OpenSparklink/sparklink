//! Application-side checks shared by SSAP authorizer frontends. This is an
//! observation snapshot and local policy boundary, not a Grant, security
//! authority, registration database or protocol Engine. The daemon still
//! validates the original registration and physical Session before committing.
use slk_contract::ControllerId;
use slk_contract::ssap::SsapAuthorizationPrompt as Prompt;
use slk_protocol::{SsapOperations, ssap::access::SsapAccess};
use std::time::Instant;
use tokio::sync::{oneshot, watch};
pub(crate) mod inbox;

pub(crate) fn check_sender(owner: &str, sender: Option<&str>) -> zbus::fdo::Result<()> {
    if sender != Some(owner) {
        return Err(zbus::fdo::Error::AccessDenied(
            "not the original daemon".into(),
        ));
    }
    Ok(())
}

/// Borrowed frontend observation. It owns no mutable registration state. The
/// frontend must take a fresh snapshot again before accepting a decision.
/// `property=None` rejects callbacks arriving before the registration receipt.
/// cbindgen:ignore
pub struct AuthorizationContext<'a> {
    pub daemon_owner: &'a str,
    pub owner_lost: bool,
    pub controller: ControllerId,
    pub property: Option<u16>,
    pub operations: SsapOperations,
    pub access: SsapAccess,
}

/// Validate the actual D-Bus sender and existing basic-CUTC callback contract.
/// Returns the original local deadline, never a renewed relative budget.
/// `None` means deny without dispatching application policy; a foreign sender
/// is AccessDenied. This does not check live kernel/connection state or grant
/// encryption, authentication, delivery, or permission to submit business data.
pub fn admit(
    context: &AuthorizationContext<'_>,
    sender: Option<&str>,
    prompt: &Prompt,
) -> zbus::fdo::Result<Option<Instant>> {
    check_sender(context.daemon_owner, sender)?;
    let id = prompt.1;
    let permitted = match prompt.6 {
        0 => {
            context
                .access
                .check_authorization_result(id.5, prompt.3, true)
                .is_ok()
                && if prompt.3 {
                    // This callback describes the write direction, not its
                    // wire opcode. The daemon checks the exact operation both
                    // before dispatch and before committing the property.
                    context.operations.contains(SsapOperations::WRITE_NO_RSP)
                        || context.operations.contains(SsapOperations::WRITE_WITH_RSP)
                } else {
                    context.operations.contains(SsapOperations::READ)
                }
        }
        2 => {
            prompt.3
                && context.operations.contains(SsapOperations::CLIENT_CFG_WR)
                && slk_protocol::ssap::client_config::decode(
                    &prompt.5,
                    slk_protocol::ssap::client_config::modes(context.operations),
                )
                .is_ok()
                && slk_protocol::ssap::client_config::WRITE_ACCESS
                    .check_authorization_result(id.5, true, true)
                    .is_ok()
        }
        _ => false,
    };
    admit_identity(
        context.controller,
        context.owner_lost,
        context.property,
        prompt,
        permitted,
        2042,
    )
}

/// Original method observation, distinct from property operation indicators.
/// Approval here is local policy only; the daemon retains final authority.
/// cbindgen:ignore
pub struct MethodAuthorizationContext<'a> {
    pub daemon_owner: &'a str,
    pub owner_lost: bool,
    pub controller: ControllerId,
    pub method: Option<u16>,
    pub access: slk_protocol::ssap::access::MethodAccess,
}

pub fn admit_method(
    context: &MethodAuthorizationContext<'_>,
    sender: Option<&str>,
    prompt: &Prompt,
) -> zbus::fdo::Result<Option<Instant>> {
    check_sender(context.daemon_owner, sender)?;
    let permitted = prompt.6 == slk_contract::ssap::METHOD_TARGET
        && prompt.3
        && prompt.2 != 0
        && prompt.1.1 != 0
        && prompt.1.3 <= 0x0fff
        && context.access.check(prompt.1.5, true).is_ok();
    admit_identity(
        context.controller,
        context.owner_lost,
        context.method,
        prompt,
        permitted,
        slk_contract::ssap::MAX_METHOD_ARGUMENT_BYTES,
    )
}

fn admit_identity(
    controller: ControllerId,
    owner_lost: bool,
    target: Option<u16>,
    prompt: &Prompt,
    permitted: bool,
    maximum: usize,
) -> zbus::fdo::Result<Option<Instant>> {
    let id = prompt.1;
    if owner_lost
        || prompt.0 == 0
        || target != Some(prompt.2)
        || !permitted
        || id.0 != controller.index
        || id.1 != controller.generation
        || id.2 == 0
        || id.4 == 0
        || id.5 > 2
        || (id.6, id.7, id.8) != (10, 10, 0)
        || prompt.5.len() > maximum
        || !prompt.3 && !prompt.5.is_empty()
    {
        return Ok(None);
    }
    let Ok(original) = slk_channel::deadline::local_instant_from_monotonic_ns(prompt.4) else {
        return Ok(None);
    };
    if original.saturating_duration_since(Instant::now()) > slk_channel::deadline::PROTOCOL_WAIT {
        return Ok(None);
    }
    Ok(Some(original))
}

/// Await one already-admitted application's decision. The frontend retains its
/// existing finite queue/permit and must re-run `admit` with a fresh snapshot
/// afterwards. A lost/closed owner scope, closed reply or original expiry denies.
/// No application code runs here; a synchronous language executor must not block
/// its own D-Bus progress by invoking foreign callbacks on that executor thread.
pub async fn await_decision(
    result: oneshot::Receiver<bool>,
    lost: watch::Receiver<bool>,
    original: Instant,
) -> bool {
    await_reply(result, lost, original).await.unwrap_or(false)
}

/// Keep one actual reply within the original owner scope and deadline.
pub(crate) async fn await_reply<T>(
    result: oneshot::Receiver<T>,
    mut lost: watch::Receiver<bool>,
    original: Instant,
) -> Option<T> {
    if *lost.borrow() || lost.has_changed().is_err() || original <= Instant::now() {
        return None;
    }
    tokio::select! {biased;
        _=lost.changed()=>None,
        result=tokio::time::timeout_at(original.into(),result)=> {
            if !*lost.borrow() && lost.has_changed().is_ok() && original > Instant::now() {
                result.ok().and_then(|reply| reply.ok())
            } else {
                None
            }
        },
    }
}

#[cfg(test)]
mod tests;
