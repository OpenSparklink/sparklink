//! Application-side checks shared by SSAP authorizer frontends. This is an
//! observation snapshot and local policy boundary, not a Grant, security
//! authority, registration database or protocol Engine. The daemon still
//! validates the original registration and physical Session before committing.
use slk_contract::ControllerId;
use slk_protocol::{
    SsapOperations,
    ssap::{SsapAuthorizationPrompt as Prompt, access::SsapAccess},
};
use std::time::Instant;
use tokio::sync::{oneshot, watch};

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
    if sender != Some(context.daemon_owner) {
        return Err(zbus::fdo::Error::AccessDenied(
            "not the original daemon".into(),
        ));
    }
    let id = prompt.1;
    if context.owner_lost
        || prompt.0 == 0
        || context.property != Some(prompt.2)
        || id.0 != context.controller.index
        || id.1 != context.controller.generation
        || id.2 == 0
        || id.4 == 0
        || id.5 > 2
        || (id.6, id.7, id.8) != (10, 10, 0)
        || prompt.5.len() > 2042
        || !prompt.3 && !prompt.5.is_empty()
        || context
            .access
            .check_authorization_result(id.5, prompt.3, true)
            .is_err()
        || !context.operations.contains(if prompt.3 {
            SsapOperations::WRITE_WITH_RSP
        } else {
            SsapOperations::READ
        })
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
    mut lost: watch::Receiver<bool>,
    original: Instant,
) -> bool {
    if *lost.borrow() || lost.has_changed().is_err() || original <= Instant::now() {
        return false;
    }
    tokio::select! {biased;
        _=lost.changed()=>false,
        result=tokio::time::timeout_at(original.into(),result)=>
            matches!(result,Ok(Ok(true))) && !*lost.borrow()
                && lost.has_changed().is_ok() && original > Instant::now(),
    }
}

#[cfg(test)]
mod tests;
