//! Thin explicit Agent registration. Human consent remains in the application;
//! the daemon owns policy requests and the kernel owns mechanism/installation.
use crate::{ApplicationError, controller::Controller};
use slk_contract::security as wire;
type Result<T> = std::result::Result<T, ApplicationError>;
impl Controller {
    /// Callback object must be exported on this Client's bus connection. A
    /// receipt is a local registration, never authentication or trusted Grant.
    pub async fn register_agent(
        &self,
        path: zbus::zvariant::OwnedObjectPath,
        method: &str,
    ) -> Result<AgentRegistration> {
        let id = self.id();
        self.client.check_generation(id).await?;
        let security = format!("{}/security", self.path());
        let epoch: u64 = self
            .client
            .proxy(&security, wire::INTERFACE)
            .await?
            .call(wire::REGISTER, &(path.clone(), method))
            .await?;
        if epoch == 0 {
            return Err(ApplicationError::Identity("zero Agent epoch"));
        }
        let mut registration = AgentRegistration {
            controller: self.clone(),
            path,
            epoch,
            active: true,
        };
        if let Err(error) = self.client.check_generation(id).await {
            let _ =
                tokio::time::timeout(std::time::Duration::from_secs(1), registration.unregister())
                    .await;
            return Err(error);
        }
        Ok(registration)
    }
}
/// Non-clone receipt. Explicit unregister or actual caller-bus exit revokes it.
/// Drop starts no detached cleanup; it does not reset a controller/connection.
pub struct AgentRegistration {
    controller: Controller,
    path: zbus::zvariant::OwnedObjectPath,
    epoch: u64,
    active: bool,
}
impl AgentRegistration {
    pub fn epoch(&self) -> u64 {
        self.epoch
    }
    /// Original unique owner only, including after local observation invalidates.
    /// Server checks original caller/path/epoch; old cleanup cannot revoke a
    /// later registration at the same path on the same caller connection.
    pub async fn unregister(&mut self) -> Result<()> {
        if !self.active {
            return Err(ApplicationError::Invalid("Agent already unregistered"));
        }
        let path = format!("{}/security", self.controller.path());
        self.controller
            .client
            .original_proxy(&path, wire::INTERFACE)
            .await?
            .call::<_, _, ()>(wire::UNREGISTER, &(self.path.clone(), self.epoch))
            .await?;
        self.active = false;
        Ok(())
    }
}
