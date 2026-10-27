//! Operation-specific checks only. Queue, references, cancellation and reply
//! ownership are implemented once by frontend; this is not a protocol Engine.
use super::{admit, await_reply};
use crate::ssap::authorization::{self, AuthorizationContext, MethodAuthorizationContext};
use crate::ssap::local::EntryRequirements;
use slk_contract::ssap::{
    MAX_METHOD_ARGUMENT_BYTES, MAX_METHOD_RESULT_BYTES, MAX_PROVIDER_VALUE_BYTES, METHOD_TARGET,
    MethodProviderRequest, PROVIDER_UNAVAILABLE, ReadProviderReply, ReadProviderRequest,
    SsapAuthorizationIdentity, WriteProviderRequest,
};
use slk_protocol::SsapOperations;

pub(super) enum ProviderContext<'a> {
    Property(AuthorizationContext<'a>),
    Method(MethodAuthorizationContext<'a>),
}
use std::{io, time::Instant};
use tokio::sync::{oneshot, watch};

#[derive(Clone, Copy)]
pub(super) enum ProviderKind {
    Read,
    Write,
    Method,
}
impl ProviderKind {
    pub(super) fn supports(self, requirements: EntryRequirements) -> bool {
        match (self, requirements) {
            (Self::Read, EntryRequirements::Property(operations, _)) => {
                operations == SsapOperations::READ
            }
            (Self::Write, EntryRequirements::Property(operations, _)) => {
                operations.bits() != 0
                    && (SsapOperations::WRITE_WITH_RSP | SsapOperations::WRITE_NO_RSP)
                        .contains(operations)
            }
            (Self::Method, EntryRequirements::Method(_)) => true,
            _ => false,
        }
    }
}
pub(super) enum RequestData {
    Read(ReadProviderRequest),
    Write(WriteProviderRequest),
    Method(MethodProviderRequest),
}
impl RequestData {
    pub(super) fn kind(&self) -> ProviderKind {
        match self {
            Self::Read(_) => ProviderKind::Read,
            Self::Write(_) => ProviderKind::Write,
            Self::Method(_) => ProviderKind::Method,
        }
    }
    pub(super) fn identity(&self) -> SsapAuthorizationIdentity {
        match self {
            Self::Read(r) => r.identity,
            Self::Write(r) => r.identity,
            Self::Method(r) => r.identity,
        }
    }
    pub(super) fn property(&self) -> u16 {
        match self {
            Self::Read(r) => r.property,
            Self::Write(r) => r.property,
            Self::Method(r) => r.method,
        }
    }
    pub(super) fn admit(
        &self,
        context: &ProviderContext<'_>,
        sender: Option<&str>,
    ) -> zbus::fdo::Result<Option<Instant>> {
        match (self, context) {
            (Self::Read(r), ProviderContext::Property(context)) => admit(context, sender, r),
            (Self::Write(r), ProviderContext::Property(context)) => {
                // A foreign caller is rejected even for a malformed request.
                authorization::check_sender(context.daemon_owner, sender)?;
                let operation = match r.operation {
                    12 if !r.verify => SsapOperations::WRITE_NO_RSP,
                    13 => SsapOperations::WRITE_WITH_RSP,
                    _ => return Ok(None),
                };
                if !self.kind().supports(EntryRequirements::Property(
                    context.operations,
                    context.access,
                )) || !context.operations.contains(operation)
                    || r.property == 0
                    || r.identity.1 == 0
                    || r.identity.3 > 0x0fff
                    || r.data_type != 0
                    || r.offset != 0
                    || r.value.len() > MAX_PROVIDER_VALUE_BYTES
                {
                    return Ok(None);
                }
                // Same original-owner, identity, security and absolute deadline
                // validator as READ/policy. Its boolean result is admission,
                // never application write completion. Copy only after the bound.
                authorization::admit(
                    context,
                    sender,
                    &(
                        r.request_id,
                        r.identity,
                        r.property,
                        true,
                        r.deadline_ns,
                        r.value.clone(),
                        0,
                    ),
                )
            }
            (Self::Method(r), ProviderContext::Method(context)) => {
                authorization::check_sender(context.daemon_owner, sender)?;
                if !matches!(r.operation, 18 | 19)
                    || r.arguments.len() > MAX_METHOD_ARGUMENT_BYTES
                    || usize::from(r.maximum_result_bytes) > MAX_METHOD_RESULT_BYTES
                    || r.operation == 18 && r.maximum_result_bytes != 0
                {
                    return Ok(None);
                }
                authorization::admit_method(
                    context,
                    sender,
                    &(
                        r.request_id,
                        r.identity,
                        r.method,
                        true,
                        r.deadline_ns,
                        r.arguments.clone(),
                        METHOD_TARGET,
                    ),
                )
            }
            _ => Ok(None),
        }
    }
    pub(super) fn validate_reply(&self, status: u16, value: &[u8]) -> io::Result<()> {
        let invalid = || io::Error::from_raw_os_error(nix::libc::EINVAL);
        if status != 0 && (!(PROVIDER_UNAVAILABLE..=0xff).contains(&status) || !value.is_empty()) {
            return Err(invalid());
        }
        let maximum = match self {
            Self::Read(r) => usize::from(r.maximum_bytes),
            Self::Method(r) => usize::from(r.maximum_result_bytes),
            Self::Write(r) => {
                if r.verify {
                    r.value.len()
                } else {
                    0
                }
            }
        };
        if value.len() > maximum {
            return Err(io::Error::from_raw_os_error(nix::libc::EMSGSIZE));
        }
        if let Self::Write(r) = self
            && status == 0
            && r.verify
            && value != r.value
        {
            return Err(invalid());
        }
        Ok(())
    }
    pub(super) async fn await_reply(
        &self,
        result: oneshot::Receiver<ReadProviderReply>,
        lost: watch::Receiver<bool>,
        original: Instant,
    ) -> ReadProviderReply {
        match self {
            Self::Read(r) => await_reply(result, lost, original, r.maximum_bytes).await,
            Self::Write(_) | Self::Method(_) => authorization::await_reply(result, lost, original)
                .await
                .filter(|(status, value)| self.validate_reply(*status, value).is_ok())
                .unwrap_or_else(|| (PROVIDER_UNAVAILABLE, Vec::new())),
        }
    }
}
