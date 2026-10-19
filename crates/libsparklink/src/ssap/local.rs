//! Thin local service manager calls. No database, protocol Engine or cached
//! publication state; a successful register is local staging only.
use crate::{ApplicationError, client::bounded, controller::Controller};
use slk_channel::deadline::Deadline;
use slk_contract::ssap::local as wire;
type Result<T> = std::result::Result<T, ApplicationError>;
#[derive(Clone)]
pub struct StagingServices {
    controller: Controller,
}
impl StagingServices {
    pub(crate) fn new(controller: Controller) -> Self {
        Self { controller }
    }
    pub async fn list(&self) -> Result<Vec<wire::ServiceRecord>> {
        self.controller.call(wire::MANAGER, wire::LIST, &()).await
    }
    pub async fn register(
        &self,
        uuid: Vec<u8>,
        properties: Vec<wire::PropertyDefinition>,
    ) -> Result<wire::Registration> {
        self.controller
            .call(wire::MANAGER, wire::REGISTER, &(uuid, properties))
            .await
    }
    pub async fn read_local(&self, handle: u16) -> Result<Vec<u8>> {
        self.controller
            .call(wire::MANAGER, wire::READ, &(handle,))
            .await
    }
    pub async fn remove(&self, start: u16) -> Result<()> {
        self.controller
            .call(wire::MANAGER, wire::REMOVE, &(start,))
            .await
    }
}

/// Caller-owned service operations on this controller generation. The callback
/// object must be served on the same connection passed to Client.
#[derive(Clone)]
pub struct LocalServices {
    controller: Controller,
}
impl LocalServices {
    pub(crate) fn new(controller: Controller) -> Self {
        Self { controller }
    }
    /// Local registration only, not RF publication. The original absolute
    /// deadline includes generation/owner checks and broker admission. A lost
    /// reply/cancelled future can leave an owner-bound registration until caller
    /// exit. A received valid receipt on scope/deadline failure gets one separate
    /// <=1s withdrawal attempt; this never renews registration admission and is
    /// not a cleanup guarantee. Dropping this view does not close the caller.
    pub async fn register_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<wire::PropertyDefinition>,
        authorizer: zbus::zvariant::OwnedObjectPath,
        original: Deadline,
    ) -> Result<ServiceRegistration> {
        let id = self.controller.id();
        let path = format!("{}/services", self.controller.path());
        let expected = properties.len();
        let mut received = None;
        let result = bounded(&self.controller.client, original, async {
            self.controller.client.check_generation(id).await?;
            original.remaining()?;
            let receipt: wire::Registration = self
                .controller
                .client
                .proxy(&path, wire::MANAGER)
                .await?
                .call(
                    wire::REGISTER_OWNED,
                    &(
                        uuid,
                        properties,
                        authorizer,
                        slk_contract::deadline_wire(original.stamp()),
                    ),
                )
                .await?;
            // Never guess a cleanup target from a malformed/foreign receipt.
            if !valid_receipt(&receipt, expected) {
                return Err(ApplicationError::Identity(
                    "malformed owned-service receipt;remote effects uncertain",
                ));
            }
            received = Some(receipt);
            self.controller.client.check_generation(id).await?;
            original.remaining()?;
            Ok(())
        })
        .await;
        let Some(receipt) = received else {
            return Err(result.err().unwrap_or(ApplicationError::Identity(
                "owned registration missing receipt",
            )));
        };
        let mut registration = ServiceRegistration {
            controller: self.controller.clone(),
            receipt,
            state: RegistrationState::Active,
        };
        if let Err(error) = result {
            if let Ok(cleanup) = Deadline::after(std::time::Duration::from_secs(1)) {
                let _ = registration.unregister(cleanup).await;
            }
            return Err(error);
        }
        Ok(registration)
    }
}
fn valid_receipt(value: &wire::Registration, expected: usize) -> bool {
    (1..=64).contains(&expected)
        && value.0 != 0
        && value.1 > value.0
        && value.2.len() == expected
        && value.2.iter().all(|h| *h > value.0 && *h <= value.1)
        && value.2.windows(2).all(|w| w[0] < w[1])
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RegistrationState {
    Active,
    Withdrawing,
    Removed,
}

/// A receipt, not a wire Engine or a protocol lifetime. Explicit unregister (or
/// actual bus owner exit) removes it. Drop never starts untracked async cleanup.
/// This object is not Clone: a second handle must not silently own its removal.
pub struct ServiceRegistration {
    controller: Controller,
    receipt: wire::Registration,
    state: RegistrationState,
}
impl ServiceRegistration {
    pub fn receipt(&self) -> &wire::Registration {
        &self.receipt
    }
    pub async fn read_local(&self, handle: u16, original: Deadline) -> Result<Vec<u8>> {
        if self.state == RegistrationState::Removed || !self.receipt.2.contains(&handle) {
            return Err(ApplicationError::Invalid(
                "inactive or foreign service handle",
            ));
        }
        let result = bounded(
            &self.controller.client,
            original,
            self.controller.call(
                wire::MANAGER,
                wire::READ_OWNED,
                &(handle, slk_contract::deadline_wire(original.stamp())),
            ),
        )
        .await?;
        original.remaining()?;
        Ok(result)
    }
    /// Atomically replace this owner's local property value (0..2042 bytes).
    /// Peer READ/WRITE permissions stay unchanged. Success is local commit only;
    /// timeout/caller loss after commit has uncertain effects, never an implicit retry.
    pub async fn replace_local(
        &self,
        handle: u16,
        value: Vec<u8>,
        original: Deadline,
    ) -> Result<()> {
        if self.state != RegistrationState::Active
            || !self.receipt.2.contains(&handle)
            || value.len() > 2042
        {
            return Err(ApplicationError::Invalid(
                "inactive/foreign property or oversized value",
            ));
        }
        let request: wire::OwnedValueRequest =
            (handle, value, slk_contract::deadline_wire(original.stamp()));
        let _: () = bounded(
            &self.controller.client,
            original,
            self.controller
                .call(wire::MANAGER, wire::REPLACE_OWNED, &request),
        )
        .await?;
        original.remaining()?;
        Ok(())
    }
    /// Withdrawal is allowed after local owner-scope loss. It targets only the
    /// original unique daemon + immutable generation path + owner-bound start
    /// handle (not reused within that database). It cannot admit new work.
    pub async fn unregister(&mut self, original: Deadline) -> Result<()> {
        if self.state == RegistrationState::Removed {
            return Err(ApplicationError::Invalid("service already unregistered"));
        }
        let path = format!("{}/services", self.controller.path());
        original.remaining()?;
        // A started withdrawal permanently closes local mutation admission,
        // including an uncertain RPC result. Metadata reads and explicit cleanup
        // retries remain possible on this original receipt.
        self.state = RegistrationState::Withdrawing;
        // Withdrawal remains allowed after local owner/generation scope loss,
        // pinned to the original unique daemon and immutable generation path.
        tokio::time::timeout_at(original.instant().into(), async {
            let request: wire::OwnedHandleRequest = (
                self.receipt.0,
                slk_contract::deadline_wire(original.stamp()),
            );
            self.controller
                .client
                .original_proxy(&path, wire::MANAGER)
                .await?
                .call::<_, _, ()>(wire::UNREGISTER_OWNED, &request)
                .await?;
            Ok::<_, ApplicationError>(())
        })
        .await
        .map_err(|_| std::io::Error::from_raw_os_error(nix::libc::ETIMEDOUT))??;
        original.remaining()?;
        self.state = RegistrationState::Removed;
        Ok(())
    }
}
