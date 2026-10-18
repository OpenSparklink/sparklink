//! Typed client view of the existing daemon SSAP actor. No wire Engine, database,
//! cache, retry or transaction state lives here. Broker errors are propagated.
//! A local wait ending cannot undo a remotely committed operation; protocol
//! response, queue admission and remote application processing remain distinct.
pub mod local;
use crate::{ApplicationConnection, ApplicationError};
use slk_contract::{self as contract, ssap as wire};

type Result<T> = std::result::Result<T, ApplicationError>;

/// Borrows one pinned physical lifetime and the original daemon owner.
/// This is not a remote service registration or a security authorization.
pub struct RemoteSsap<'a> {
    link: &'a ApplicationConnection,
}
impl<'a> RemoteSsap<'a> {
    pub(crate) fn new(link: &'a ApplicationConnection) -> Self {
        Self { link }
    }
    // All calls use the same production identity checks. No late reply can
    // silently be relabelled as a replacement daemon/connection observation.
    async fn current<T>(
        &self,
        operation: impl std::future::Future<Output = Result<T>>,
    ) -> Result<T> {
        self.link.live().await?;
        let result = operation.await?;
        self.link.live().await?;
        Ok(result)
    }
    pub async fn discover(&self, uuid: Vec<u8>, kind: u8) -> Result<wire::Discovery> {
        self.current(async {
            Ok(self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(wire::DISCOVER, &(uuid, kind))
                .await?)
        })
        .await
    }
    /// Advisory daemon cache for this lifetime; not availability or a grant.
    pub async fn cached(&self) -> Result<Vec<wire::Entry>> {
        self.current(async {
            Ok(self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(wire::CACHED, &())
                .await?)
        })
        .await
    }
    /// Observe incoming notification/indication. This does not subscribe the
    /// peer or prove another application processed an indication.
    pub async fn observe(
        &self,
        handles: Vec<u16>,
        modes: u8,
        wait_ms: u32,
    ) -> Result<wire::Incoming> {
        self.current(async {
            Ok(self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(wire::OBSERVE, &(handles, modes, wait_ms))
                .await?)
        })
        .await
    }
    pub async fn read_by_uuid(
        &self,
        start: u16,
        end: u16,
        data_type: u8,
        uuid: Vec<u8>,
        minimum: u32,
    ) -> Result<wire::UuidValues> {
        self.current(async {
            Ok(self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(wire::READ_UUID, &(start, end, data_type, uuid, minimum))
                .await?)
        })
        .await
    }
    pub async fn read(&self, handle: u16, minimum: u32) -> Result<Vec<u8>> {
        self.current(async {
            Ok(self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(wire::READ, &(handle, minimum))
                .await?)
        })
        .await
    }
    /// Uses the daemon's existing short-write contract. No truncation, long
    /// write fallback or local echo is performed by the SDK.
    pub async fn write(&self, handle: u16, value: Vec<u8>, minimum: u32) -> Result<Vec<u8>> {
        self.current(async {
            Ok(self
                .link
                .client
                .proxy(&self.link.path, contract::CONNECTION)
                .await?
                .call(wire::WRITE, &(handle, value, minimum))
                .await?)
        })
        .await
    }
    /// Actual ExchangeInfo, never inferred service discovery or security.
    pub async fn exchange_info(&self) -> Result<wire::ExchangeInfo> {
        let value: wire::ExchangeInfo = self
            .current(async {
                Ok(self
                    .link
                    .client
                    .proxy(&self.link.path, contract::CONNECTION)
                    .await?
                    .call(wire::EXCHANGE_INFO, &())
                    .await?)
            })
            .await?;
        let info = self.link.info().await?;
        if !info.6
            || !info.7
            || value.0 != self.link.controller.index
            || (value.1, value.2, value.3) != (info.0, info.1, info.2)
        {
            return Err(ApplicationError::Identity("SSAP exchange lifetime"));
        }
        Ok(value)
    }
}
