//! Application write effects, separate from policy approval and stored values.
//! Uses the same Owner cancellation/deadline contract as READ; no extra worker.
use crate::ssap_authorization::Owner;
use slk_contract::ssap::{self, WriteProviderRequest};
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
pub(crate) struct WriteResult {
    pub(crate) target: Target,
    pub(crate) request: WriteProviderRequest,
    pub(crate) result: Result<Vec<u8>, u8>,
}
impl Binding {
    pub(crate) async fn write(
        &self,
        request: &WriteProviderRequest,
        deadline: Instant,
    ) -> Result<Vec<u8>, u8> {
        let unavailable = ssap::PROVIDER_UNAVAILABLE as u8;
        if !matches!(request.operation, 12 | 13)
            || request.data_type != 0
            || request.offset != 0
            || (request.operation == 12 && request.verify)
            || request.value.len() > ssap::MAX_PROVIDER_VALUE_BYTES
        {
            return Err(unavailable);
        }
        let message = self
            .owner
            .callback(
                self.path.as_str(),
                ssap::WRITE_PROVIDER_INTERFACE,
                ssap::WRITE_PROVIDER_METHOD,
                &(request,),
                deadline,
            )
            .await
            .ok_or(unavailable)?;
        let body = message.body();
        let (status, value): (u8, &[u8]) = body.deserialize().map_err(|_| unavailable)?;
        match (status, value) {
            (0, value) if request.verify && value == request.value => Ok(value.to_vec()),
            (0, []) if !request.verify => Ok(vec![]),
            (0xaf..=0xff, []) => Err(status),
            _ => Err(unavailable),
        }
    }
}
