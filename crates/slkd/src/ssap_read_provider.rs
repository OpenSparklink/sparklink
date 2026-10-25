//! Application-owned dynamic read value, not authorization or an SSAP Engine.
//! A binding is immutable and lives within the original Owned registration.
use crate::ssap_authorization::Owner;
use slk_contract::ssap::{self, ReadProviderRequest};
use std::sync::Arc;
use tokio::time::Instant;
use zbus::zvariant::OwnedObjectPath;

pub(crate) struct Binding {
    pub(crate) owner: Arc<Owner>,
    pub(crate) path: OwnedObjectPath,
}
pub(crate) struct Target {
    pub(crate) handle: u16,
    pub(crate) binding: Arc<Binding>,
}
pub(crate) struct ReadValue {
    pub(crate) target: Target,
    pub(crate) result: Result<Vec<u8>, u16>,
}
impl Binding {
    pub(crate) async fn read(
        &self,
        request: ReadProviderRequest,
        deadline: Instant,
    ) -> Result<Vec<u8>, u16> {
        let maximum = usize::from(request.maximum_bytes);
        if maximum > ssap::MAX_PROVIDER_VALUE_BYTES {
            return Err(ssap::PROVIDER_UNAVAILABLE);
        }
        let message = self
            .owner
            .callback(
                self.path.as_str(),
                ssap::READ_PROVIDER_INTERFACE,
                ssap::READ_PROVIDER_METHOD,
                &(request,),
                deadline,
            )
            .await
            .ok_or(ssap::PROVIDER_UNAVAILABLE)?;
        // Inspect the borrowed body before allocating a value. D-Bus transport
        // has its own message budget; this layer never clones an oversized ay.
        let body = message.body();
        let (status, value): (u16, &[u8]) =
            body.deserialize().map_err(|_| ssap::PROVIDER_UNAVAILABLE)?;
        match (status, value) {
            (0, value) if value.len() <= maximum => Ok(value.to_vec()),
            (0xaf..=0xff, []) => Err(status),
            _ => Err(ssap::PROVIDER_UNAVAILABLE),
        }
    }
}
