//! One caller-owned bounded discovery lease through the pinned daemon.
//! Explicit close reports actual STOP only for the last lease. Drop schedules
//! best-effort withdrawal on an existing Tokio runtime; owner loss and the
//! original bounded lease expiry remain the daemon's cleanup obligations.
use crate::{ApplicationError, Client, client::bounded};
use slk_channel::deadline::Deadline;
use slk_contract::{ControllerId, discovery as wire};
use std::time::Duration;
type Result<T> = std::result::Result<T, ApplicationError>;
#[cfg(test)]
#[path = "discovery_tests.rs"]
mod tests;

pub struct DiscoverySession {
    client: Client,
    controller: ControllerId,
    id: u64,
    prefix: Vec<u8>,
    minimum_rssi: i16,
    sequence: u64,
    dropped: u64,
    kernel_lost: u64,
    closed: bool,
}
impl Client {
    /// WS73 passive frame-1 scan only. Duration is250..60000ms from daemon
    /// admission; -128 includes unknown RSSI. Prefix matches raw vendor data.
    /// An abandoned acquisition reply can leave a lease until owner loss or
    /// this finite expiry; a timeout is not a cleanup receipt.
    pub async fn discover(
        &self,
        controller: ControllerId,
        prefix: Vec<u8>,
        minimum_rssi: i16,
        duration_ms: u32,
        deadline: Deadline,
    ) -> Result<DiscoverySession> {
        if controller.generation == 0 || !wire::valid_filter(&prefix, minimum_rssi, duration_ms) {
            return Err(ApplicationError::Invalid(
                "discovery identity/filter/duration",
            ));
        }
        let id: u64 = bounded(self, deadline, async {
            let id = self
                .proxy(&controller.path(), slk_contract::ADAPTER)
                .await?
                .call(
                    wire::ACQUIRE,
                    &(
                        &prefix,
                        minimum_rssi,
                        duration_ms,
                        slk_contract::deadline_wire(deadline.stamp()),
                    ),
                )
                .await?;
            self.check_owner().await?;
            if id == 0 {
                return Err(ApplicationError::Identity("zero discovery session"));
            }
            Ok(id)
        })
        .await?;
        Ok(DiscoverySession {
            client: self.clone(),
            controller,
            id,
            prefix,
            minimum_rssi,
            sequence: 0,
            dropped: 0,
            kernel_lost: 0,
            closed: false,
        })
    }
}
impl DiscoverySession {
    pub fn id(&self) -> u64 {
        self.id
    }
    pub fn controller(&self) -> ControllerId {
        self.controller
    }
    /// One destructive reader. Cancelling a read does not release the lease;
    /// it can make a consumed remote reply uncertain. Counters expose gaps,
    /// and no report-only contiguous sequence is inferred from Native sequence.
    pub async fn read(&mut self, wait: bool, deadline: Deadline) -> Result<wire::Batch> {
        if self.closed {
            return Err(ApplicationError::Invalid("discovery session closed"));
        }
        let batch: wire::Batch = bounded(&self.client, deadline, async {
            let batch = self
                .client
                .proxy(&self.controller.path(), slk_contract::ADAPTER)
                .await?
                .call(
                    wire::REPORTS,
                    &(self.id, wait, slk_contract::deadline_wire(deadline.stamp())),
                )
                .await?;
            self.client.check_owner().await?;
            Ok(batch)
        })
        .await?;
        if batch.version != wire::VERSION
            || batch.session != self.id
            || batch.generation != self.controller.generation
            || batch.dropped < self.dropped
            || batch.kernel_lost < self.kernel_lost
            || batch.reports.len() > wire::CAPACITY
        {
            return Err(ApplicationError::Identity(
                "discovery batch identity/budget",
            ));
        }
        let mut last = self.sequence;
        for r in &batch.reports {
            if r.sequence <= last
                || r.address_type > 1
                || r.address.len() != 6
                || r.header.len() != 23
                || r.header[1] != r.address_type
                || r.header[2..8] != r.address
                || r.data.len() > wire::MAX_DATA
                || !r.data.starts_with(&self.prefix)
                || r.rssi_known != (r.rssi != 127)
                || !(-128..=127).contains(&r.rssi)
                || self.minimum_rssi != -128 && (!r.rssi_known || r.rssi < self.minimum_rssi)
            {
                return Err(ApplicationError::Identity(
                    "discovery report/filter/sequence",
                ));
            }
            last = r.sequence;
        }
        deadline.remaining()?;
        self.sequence = last;
        self.dropped = batch.dropped;
        self.kernel_lost = batch.kernel_lost;
        Ok(batch)
    }
    /// false releases only this lease; true additionally confirms last-lease
    /// physical STOP. Errors/timeouts are never translated to Off. Closing a
    /// lease neither disconnects links nor releases controller management.
    pub async fn close(&mut self, deadline: Deadline) -> Result<bool> {
        if self.closed {
            return Err(ApplicationError::Invalid("discovery session closed"));
        }
        deadline.remaining()?;
        self.closed = true;
        bounded(&self.client, deadline, async {
            let stopped = self
                .client
                .original_proxy(&self.controller.path(), slk_contract::ADAPTER)
                .await?
                .call(
                    wire::RELEASE,
                    &(self.id, slk_contract::deadline_wire(deadline.stamp())),
                )
                .await?;
            self.client.check_owner().await?;
            Ok(stopped)
        })
        .await
    }
}
impl Drop for DiscoverySession {
    fn drop(&mut self) {
        if self.closed {
            return;
        }
        self.closed = true;
        if let Ok(runtime) = tokio::runtime::Handle::try_current() {
            let client = self.client.clone();
            let path = self.controller.path();
            let id = self.id;
            runtime.spawn(async move {
                let Ok(until) = Deadline::after(Duration::from_secs(5)) else {
                    return;
                };
                let _ = tokio::time::timeout_at(until.instant().into(), async {
                    let proxy = client.original_proxy(&path, slk_contract::ADAPTER).await?;
                    let _: bool = proxy
                        .call(
                            wire::RELEASE,
                            &(id, slk_contract::deadline_wire(until.stamp())),
                        )
                        .await?;
                    Ok::<_, ApplicationError>(())
                })
                .await;
            });
        }
    }
}
