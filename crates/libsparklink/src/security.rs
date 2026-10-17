//! Original-author broker request receipts. No waiting loop, crypto, credentials
//! or physical cancellation is implemented here. The original daemon owns it.
use crate::{ApplicationConnection, ApplicationError, Client};
use slk_contract::{self as contract, security as wire};
pub use wire::Observation;
type Result<T> = std::result::Result<T, ApplicationError>;
impl ApplicationConnection {
    pub async fn allocate_reference_security(&self, timeout_ms: u32) -> Result<SecurityRequest> {
        if !(1..=5000).contains(&timeout_ms) {
            return Err(ApplicationError::Invalid("timeout must be 1..5000 ms"));
        }
        self.live().await?;
        let id = self
            .client
            .proxy(&self.path, contract::CONNECTION)
            .await?
            .call(wire::ALLOCATE, &(timeout_ms,))
            .await?;
        if id == 0 {
            return Err(ApplicationError::Identity("zero security request"));
        }
        Ok(SecurityRequest {
            client: self.client.clone(),
            path: self.path.clone(),
            identity: (self.identity.0, self.identity.1),
            id,
        })
    }
}
/// Cancellation still addresses the original unique daemon after owner loss.
/// No local terminal state, debt refund, retry or new authorization is created.
pub struct SecurityRequest {
    client: Client,
    path: String,
    identity: (u64, u64),
    id: u64,
}
impl SecurityRequest {
    pub fn id(&self) -> u64 {
        self.id
    }
    pub async fn begin(&self, method: &str) -> Result<()> {
        self.client
            .proxy(&self.path, contract::CONNECTION)
            .await?
            .call::<_, _, ()>(wire::BEGIN, &(self.id, method))
            .await?;
        self.client.check_owner().await?;
        Ok(())
    }
    pub async fn observation(&self) -> Result<Observation> {
        let o: Observation = self
            .client
            .proxy(&self.path, contract::CONNECTION)
            .await?
            .call(wire::RESULT, &(self.id,))
            .await?;
        if (o.request_id, o.generation, o.lifetime) != (self.id, self.identity.0, self.identity.1) {
            return Err(ApplicationError::Identity("security request identity"));
        }
        self.client.check_owner().await?;
        Ok(o)
    }
    pub async fn cancel(&self) -> Result<bool> {
        Ok(self
            .client
            .original_proxy(&self.path, contract::CONNECTION)
            .await?
            .call(wire::CANCEL, &(self.id,))
            .await?)
    }
}
