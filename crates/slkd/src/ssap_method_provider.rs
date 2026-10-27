//! Method effect callback over the same Owner watch/deadline as other Providers.
//! No stored arguments/results, policy engine or additional worker.
use crate::ssap_authorization::Owner;
use slk_contract::ssap::{self, MethodProviderRequest};
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
pub(crate) struct MethodResult {
    pub(crate) target: Target,
    pub(crate) request: MethodProviderRequest,
    pub(crate) result: Result<Vec<u8>, u8>,
}
impl Binding {
    pub(crate) async fn invoke(
        &self,
        request: &MethodProviderRequest,
        deadline: Instant,
    ) -> Result<Vec<u8>, u8> {
        let unavailable = ssap::PROVIDER_UNAVAILABLE as u8;
        if !matches!(request.operation, 18 | 19)
            || request.arguments.len() > ssap::MAX_METHOD_ARGUMENT_BYTES
            || usize::from(request.maximum_result_bytes) > ssap::MAX_METHOD_RESULT_BYTES
            || request.operation == 18 && request.maximum_result_bytes != 0
        {
            return Err(unavailable);
        }
        let message = self
            .owner
            .callback(
                self.path.as_str(),
                ssap::METHOD_PROVIDER_INTERFACE,
                ssap::METHOD_PROVIDER_METHOD,
                &(request,),
                deadline,
            )
            .await
            .ok_or(unavailable)?;
        let body = message.body();
        let (status, value): (u8, &[u8]) = body.deserialize().map_err(|_| unavailable)?;
        match (status, value) {
            (0, value) if value.len() <= usize::from(request.maximum_result_bytes) => {
                Ok(value.to_vec())
            }
            (0xaf..=0xff, []) => Err(status),
            _ => Err(unavailable),
        }
    }
}
