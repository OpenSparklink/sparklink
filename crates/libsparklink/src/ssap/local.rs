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
