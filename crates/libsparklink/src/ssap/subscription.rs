//! A typed leased view of the existing daemon actor, not another SSAP Engine.
//! Destructive read cancellation can leave delivery uncertain. No automatic
//! retry, cached security grant, protocol ACK generation or physical disconnect.
use crate::{ApplicationConnection, ApplicationError, Deadline, client::bounded};
use slk_contract::{self as contract, ssap::subscription as wire};
use std::time::Duration;

pub use wire::{Batch, Info, Packet};
type Result<T> = std::result::Result<T, ApplicationError>;
#[cfg(test)]
#[path = "subscription_tests.rs"]
mod tests;

pub struct Subscription {
    link: ApplicationConnection,
    info: Info,
    sequence: u64,
    dropped: u64,
    refused: u64,
    discarded: u64,
    closed: bool,
    release_requested: bool,
}
impl Subscription {
    pub(super) async fn open(
        link: ApplicationConnection,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        original: Deadline,
    ) -> Result<Self> {
        if !wire::valid_request(&handles, modes, duration_ms) {
            return Err(ApplicationError::Invalid(
                "subscription handles/modes/duration",
            ));
        }
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        let info: Info = bounded(&link.client, original, async {
            link.live().await?;
            let value = link
                .client
                .proxy(&link.path, contract::CONNECTION)
                .await?
                .call(
                    wire::CREATE,
                    &(
                        &handles,
                        modes,
                        duration_ms,
                        contract::deadline_wire(original.stamp()),
                    ),
                )
                .await?;
            link.live().await?;
            Ok(value)
        })
        .await?;
        if !Self::binding(&link, &info)
            || info.handles != handles
            || info.modes != modes
            || info.state != wire::ACTIVE
            || info.token == 0
            || info.security_epoch == 0
            || !Self::bounded_expiry(info.expires_ns, duration_ms, original)
        {
            return Err(ApplicationError::Identity("subscription acquisition scope"));
        }
        Ok(Self {
            link,
            info,
            sequence: 0,
            dropped: 0,
            refused: 0,
            discarded: 0,
            closed: false,
            release_requested: false,
        })
    }
    fn binding(link: &ApplicationConnection, info: &Info) -> bool {
        (
            info.version,
            info.controller,
            info.generation,
            info.lifetime,
            info.handle,
            info.capacity,
        ) == (
            1,
            link.controller.index,
            link.identity.0,
            link.identity.1,
            link.identity.2,
            wire::CAPACITY as u16,
        )
    }
    fn bounded_expiry(value: u64, duration_ms: u32, original: Deadline) -> bool {
        value != 0
            && original
                .stamp()
                .monotonic_ns
                .checked_add(u64::from(duration_ms) * 1_000_000)
                .is_some_and(|max| value <= max)
    }
    fn same_scope(&self, info: &Info) -> bool {
        Self::binding(&self.link, info)
            && info.token == self.info.token
            && info.security_epoch == self.info.security_epoch
            && info.handles == self.info.handles
            && info.modes == self.info.modes
            && info.expires_ns != 0
    }
    /// Last validated observation, not an active authorization or Ready grant.
    pub fn info(&self) -> &Info {
        &self.info
    }
    /// Local read/renew admission has ended;not a remote cleanup receipt.
    pub fn is_closed(&self) -> bool {
        self.closed
    }

    fn validate_batch(&self, batch: &Batch, cleanup: bool) -> Result<()> {
        let accounted = batch
            .dropped_notifications
            .checked_add(batch.refused_indications)
            .and_then(|n| n.checked_add(batch.discarded_on_close));
        if !self.same_scope(&batch.info)
            || (!cleanup && batch.info.expires_ns != self.info.expires_ns)
            || !(wire::ACTIVE..=wire::CLOSED).contains(&batch.info.state)
            || batch.flags & !wire::CLEANUP_CONFIRMED != 0
            || batch.last_sequence < self.sequence
            || batch.dropped_notifications < self.dropped
            || batch.refused_indications < self.refused
            || batch.discarded_on_close < self.discarded
            || batch.packets.len() > wire::CAPACITY
            || accounted.is_none_or(|n| n > batch.last_sequence)
        {
            return Err(ApplicationError::Identity(
                "subscription batch scope/budget/counters",
            ));
        }
        if batch.info.state == wire::ACTIVE {
            if batch.flags != 0 || batch.reason != 0 || batch.discarded_on_close != 0 {
                return Err(ApplicationError::Identity(
                    "active subscription has close result",
                ));
            }
        } else if !(wire::RELEASED..=wire::INITIALIZATION_CANCELLED).contains(&batch.reason)
            || !batch.packets.is_empty()
            || (batch.flags != 0 && batch.info.state != wire::CLOSED)
        {
            return Err(ApplicationError::Identity("subscription close result"));
        }
        if cleanup && (batch.info.state != wire::CLOSED || batch.flags != wire::CLEANUP_CONFIRMED) {
            return Err(ApplicationError::Identity(
                "subscription cleanup not confirmed",
            ));
        }
        let mut sequence = self.sequence;
        let mut bytes = 0usize;
        for p in &batch.packets {
            bytes = bytes
                .checked_add(p.pdu.len())
                .ok_or(ApplicationError::Identity("subscription byte overflow"))?;
            if p.sequence <= sequence
                || p.sequence > batch.last_sequence
                || p.security_epoch != self.info.security_epoch
                || p.security_level != 2
                || p.pdu.len() > 2048
                || bytes > wire::BYTE_BUDGET
            {
                return Err(ApplicationError::Identity(
                    "subscription packet identity/sequence/budget",
                ));
            }
            super::validate_update(&self.info.handles, self.info.modes, p.indication, &p.pdu)?;
            sequence = p.sequence;
        }
        Ok(())
    }
    fn observe(&mut self, batch: &Batch) {
        self.info = batch.info.clone();
        self.sequence = batch.last_sequence;
        self.dropped = batch.dropped_notifications;
        self.refused = batch.refused_indications;
        self.discarded = batch.discarded_on_close;
        self.closed |= batch.info.state >= wire::CLOSING;
    }
    /// One destructive reader; timeout/cancellation is not lease release or a
    /// retry promise. Sequence gaps can include uncertain earlier RPC delivery.
    pub async fn read(&mut self, wait: bool, original: Deadline) -> Result<Batch> {
        if self.closed {
            return Err(ApplicationError::Invalid("subscription closed"));
        }
        let original = original.capped(Duration::from_secs(10))?;
        let batch: Batch = bounded(&self.link.client, original, async {
            self.link.live().await?;
            let result = self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(
                    wire::READ,
                    &(
                        self.info.token,
                        wait,
                        contract::deadline_wire(original.stamp()),
                    ),
                )
                .await?;
            self.link.live().await?;
            Ok(result)
        })
        .await?;
        self.validate_batch(&batch, false)?;
        original.remaining()?;
        self.observe(&batch);
        Ok(batch)
    }
    /// Resource lease renewal only; never renews a pending read,packet or cleanup
    /// deadline. An uncertain renewal is not retried; explicit close remains valid.
    pub async fn renew(&mut self, duration_ms: u32, original: Deadline) -> Result<Info> {
        if self.closed || !(250..=60000).contains(&duration_ms) {
            return Err(ApplicationError::Invalid(
                "subscription closed/renew duration",
            ));
        }
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        let info: Info = bounded(&self.link.client, original, async {
            self.link.live().await?;
            let value = self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(
                    wire::RENEW,
                    &(
                        self.info.token,
                        duration_ms,
                        contract::deadline_wire(original.stamp()),
                    ),
                )
                .await?;
            self.link.live().await?;
            Ok(value)
        })
        .await?;
        if !self.same_scope(&info)
            || info.state != wire::ACTIVE
            || !Self::bounded_expiry(info.expires_ns, duration_ms, original)
        {
            return Err(ApplicationError::Identity("subscription renewal scope"));
        }
        original.remaining()?;
        self.info = info.clone();
        Ok(info)
    }
    /// Stop local admission before requesting remote cleanup. Error/timeout is
    /// not proof of cleanup and never starts a fresh lease. Close may report a
    /// different expiry after an uncertain renewal;it cannot reopen authority.
    pub async fn close(&mut self, original: Deadline) -> Result<Batch> {
        if self.release_requested || self.info.state == wire::CLOSED {
            return Err(ApplicationError::Invalid(
                "subscription close already requested/confirmed",
            ));
        }
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        self.release_requested = true;
        self.closed = true;
        let batch: Batch = bounded(&self.link.client, original, async {
            let value = self
                .link
                .client
                .original_proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(
                    wire::CLOSE,
                    &(self.info.token, contract::deadline_wire(original.stamp())),
                )
                .await?;
            self.link.client.check_owner().await?;
            Ok(value)
        })
        .await?;
        self.validate_batch(&batch, true)?;
        original.remaining()?;
        self.observe(&batch);
        Ok(batch)
    }
}
impl Drop for Subscription {
    fn drop(&mut self) {
        if self.closed {
            return;
        }
        self.closed = true;
        if let Ok(runtime) = tokio::runtime::Handle::try_current() {
            let client = self.link.client.clone();
            let path = self.link.path.clone();
            let token = self.info.token;
            runtime.spawn(async move {
                let Ok(until) = Deadline::after(slk_channel::deadline::PROTOCOL_WAIT) else {
                    return;
                };
                let _ = tokio::time::timeout_at(until.instant().into(), async {
                    let _: Batch = client
                        .original_proxy(&path, contract::CONNECTION)
                        .await?
                        .call(
                            wire::CLOSE,
                            &(token, contract::deadline_wire(until.stamp())),
                        )
                        .await?;
                    Ok::<_, ApplicationError>(())
                })
                .await;
            });
        }
    }
}
