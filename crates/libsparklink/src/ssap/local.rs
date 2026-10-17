//! Thin local service manager calls. No database, protocol Engine or cached
//! publication state; a successful register is local staging only.
use crate::{ApplicationError, controller::Controller};
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
    /// Local registration only, not RF publication. No implicit retry: a lost
    /// reply/cancelled future can leave an owner-bound registration until bus
    /// owner exit. Drop of this view does not close the caller's connection.
    pub async fn register_service(
        &self,
        uuid: Vec<u8>,
        properties: Vec<wire::PropertyDefinition>,
        authorizer: zbus::zvariant::OwnedObjectPath,
    ) -> Result<ServiceRegistration> {
        let id = self.controller.id();
        self.controller.client.check_generation(id).await?;
        let path = format!("{}/services", self.controller.path());
        let receipt: wire::Registration = self
            .controller
            .client
            .proxy(&path, wire::MANAGER)
            .await?
            .call(wire::REGISTER_OWNED, &(uuid, properties, authorizer))
            .await?;
        let mut registration = ServiceRegistration {
            controller: self.controller.clone(),
            receipt,
            active: true,
        };
        if let Err(error) = self.controller.client.check_generation(id).await {
            // We have a receipt: withdraw only it at the original unique owner,
            // bounded independently of any replacement daemon's availability.
            let _ =
                tokio::time::timeout(std::time::Duration::from_secs(1), registration.unregister())
                    .await;
            return Err(error);
        }
        Ok(registration)
    }
}
/// A receipt, not a wire Engine or a protocol lifetime. Explicit unregister (or
/// actual bus owner exit) removes it. Drop never starts untracked async cleanup.
/// This object is not Clone: a second handle must not silently own its removal.
pub struct ServiceRegistration {
    controller: Controller,
    receipt: wire::Registration,
    active: bool,
}
impl ServiceRegistration {
    pub fn receipt(&self) -> &wire::Registration {
        &self.receipt
    }
    pub async fn read_local(&self, handle: u16) -> Result<Vec<u8>> {
        if !self.active || !self.receipt.2.contains(&handle) {
            return Err(ApplicationError::Invalid(
                "inactive or foreign service handle",
            ));
        }
        self.controller
            .call(wire::MANAGER, wire::READ_OWNED, &(handle,))
            .await
    }
    /// Withdrawal is allowed after local owner-scope loss. It targets only the
    /// original unique daemon + immutable generation path + owner-bound start
    /// handle (not reused within that database). It cannot admit new work.
    pub async fn unregister(&mut self) -> Result<()> {
        if !self.active {
            return Err(ApplicationError::Invalid("service already unregistered"));
        }
        let path = format!("{}/services", self.controller.path());
        self.controller
            .client
            .original_proxy(&path, wire::MANAGER)
            .await?
            .call::<_, _, ()>(wire::UNREGISTER_OWNED, &(self.receipt.0,))
            .await?;
        self.active = false;
        Ok(())
    }
}
