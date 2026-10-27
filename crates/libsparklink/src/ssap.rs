//! Typed client view of the existing daemon SSAP actor. No wire Engine, database,
//! cache, retry or transaction state lives here. Broker errors are propagated.
//! A local wait ending cannot undo a remotely committed operation; protocol
//! response, queue admission and remote application processing remain distinct.
pub mod authorization;
pub mod local;
pub mod provider;
pub mod subscription;
use crate::{ApplicationConnection, ApplicationError};
use slk_contract::{self as contract, ssap as wire};

type Result<T> = std::result::Result<T, ApplicationError>;

// One decoder and scope check for both the one-shot and leased receive views.
// This validates a broker receipt; it does not grant Native security or delivery.
fn validate_update(handles: &[u16], modes: u8, indication: bool, raw: &[u8]) -> Result<()> {
    let packet = slk_protocol::ssap::updates::Update::decode(2048, raw)
        .map_err(|_| ApplicationError::Identity("malformed received SSAP update"))?;
    if packet.event
        || packet.indication != indication
        || modes & (if indication { 2 } else { 1 }) == 0
        || packet
            .items
            .iter()
            .any(|item| !handles.contains(&item.handle))
    {
        return Err(ApplicationError::Identity("received SSAP update scope"));
    }
    Ok(())
}

/// Borrows one pinned physical lifetime and the original daemon owner.
/// This is not a remote service registration or a security authorization.
pub struct RemoteSsap<'a> {
    link: &'a ApplicationConnection,
}
impl<'a> RemoteSsap<'a> {
    pub(crate) fn new(link: &'a ApplicationConnection) -> Self {
        Self { link }
    }
    /// Acquire a finite remote update lease on the existing physical actor.
    /// One lease per actor currently; no shared-CPCD or implicit reconnect.
    /// Dropping the parent connection view does not release this owned lease.
    pub async fn subscribe(
        &self,
        handles: Vec<u16>,
        modes: u8,
        duration_ms: u32,
        original: crate::Deadline,
    ) -> Result<subscription::Subscription> {
        subscription::Subscription::open(self.link.clone(), handles, modes, duration_ms, original)
            .await
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
    /// Send a snapshot of a property owned by this same original bus caller.
    /// A notification reports software admission; an indication reports peer
    /// receive-queue ACK. Neither is application delivery or a retry promise.
    pub async fn send_owned_update(
        &self,
        handle: u16,
        indication: bool,
        original: crate::Deadline,
    ) -> Result<wire::UpdateReceipt> {
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        let value = crate::client::bounded(
            &self.link.client,
            original,
            self.current(async {
                let value: wire::UpdateReceipt = self
                    .link
                    .client
                    .proxy(&self.link.path, contract::CONNECTION)
                    .await?
                    .call(
                        wire::OWNED_UPDATE,
                        &(
                            handle,
                            indication,
                            contract::deadline_wire(original.stamp()),
                        ),
                    )
                    .await?;
                if value.stage != if indication { 2 } else { 1 }
                    || value.pdu.len() > 2048
                    || value.acknowledgement != if indication { vec![17, 3, 1] } else { vec![] }
                {
                    return Err(ApplicationError::Identity("malformed owned update receipt"));
                }
                let decoded = slk_protocol::ssap::updates::Update::decode(2048, &value.pdu)
                    .map_err(|_| ApplicationError::Identity("malformed owned update PDU"))?;
                if decoded.event
                    || decoded.indication != indication
                    || decoded.items.len() != 1
                    || decoded.items[0].handle != handle
                {
                    return Err(ApplicationError::Identity("owned update receipt scope"));
                }
                Ok(value)
            }),
        )
        .await?;
        Ok(value)
    }
    /// Read-only configuration of a property owned by this caller; no enable,
    /// radio administration, security installation or readiness side effect.
    pub async fn owned_configuration(&self, handle: u16, original: crate::Deadline) -> Result<u8> {
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        crate::client::bounded(
            &self.link.client,
            original,
            self.current(async {
                let modes: u8 = self
                    .link
                    .client
                    .proxy(&self.link.path, contract::CONNECTION)
                    .await?
                    .call(
                        wire::OWNED_CONFIGURATION,
                        &(handle, contract::deadline_wire(original.stamp())),
                    )
                    .await?;
                if modes & !3 != 0 {
                    return Err(ApplicationError::Identity(
                        "reserved client configuration bits",
                    ));
                }
                Ok(modes)
            }),
        )
        .await
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
    /// Enable authenticated,owner-approved remote CPCD,receive one packet,and
    /// verify disable before returning. Pre-existing settings are not overwritten.
    /// Timeout/cancel may quarantine the physical SSAP actor if cleanup is unknown.
    pub async fn receive_update(
        &self,
        handles: Vec<u16>,
        modes: u8,
        wait_ms: u32,
    ) -> Result<wire::Incoming> {
        if !(10..=10000).contains(&wait_ms) {
            return Err(ApplicationError::Invalid("receive wait10..10000ms"));
        }
        let original =
            crate::Deadline::after(std::time::Duration::from_millis(u64::from(wait_ms)))?;
        self.receive_until(handles, modes, original).await
    }
    /// Same transaction with an original absolute deadline,including SDK queueing.
    pub async fn receive_until(
        &self,
        handles: Vec<u16>,
        modes: u8,
        original: crate::Deadline,
    ) -> Result<wire::Incoming> {
        let original = original.capped(std::time::Duration::from_secs(10))?;
        if handles.is_empty()
            || handles.len() > 32
            || handles.contains(&0)
            || handles
                .iter()
                .enumerate()
                .any(|(i, h)| handles[..i].contains(h))
            || modes == 0
            || modes & !3 != 0
        {
            return Err(ApplicationError::Invalid("receive handles/modes"));
        }
        let expected = handles.clone();
        let value: wire::Incoming = crate::client::bounded(
            &self.link.client,
            original,
            self.current(async {
                Ok(self
                    .link
                    .client
                    .proxy(&self.link.path, contract::CONNECTION)
                    .await?
                    .call(
                        wire::RECEIVE,
                        &(handles, modes, contract::deadline_wire(original.stamp())),
                    )
                    .await?)
            }),
        )
        .await?;
        validate_update(&expected, modes, value.0, &value.1)?;
        Ok(value)
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
    pub async fn read(
        &self,
        handle: u16,
        minimum: u32,
        original: crate::Deadline,
    ) -> Result<Vec<u8>> {
        self.value(handle, None, minimum, original, wire::READ)
            .await
    }
    /// Read the peer's public static description (SSAP data type1).
    /// Returns the same decoded value-byte contract as read, not a local value or
    /// authorizer/provider result. Minimum constrains the physical channel's
    /// mechanism; it does not grant a descriptor-specific trusted identity.
    pub async fn read_description(
        &self,
        handle: u16,
        minimum: u32,
        original: crate::Deadline,
    ) -> Result<Vec<u8>> {
        let value = self
            .value(handle, None, minimum, original, wire::READ_DESCRIPTION)
            .await?;
        if value.is_empty()
            || value.len() > wire::local::MAX_DESCRIPTION_BYTES
            || value.contains(&0)
            || std::str::from_utf8(&value).is_err()
        {
            return Err(ApplicationError::Io(std::io::Error::from_raw_os_error(
                nix::libc::EPROTO,
            )));
        }
        Ok(value)
    }
    /// Same five-second ceiling as the existing daemon protocol, established
    /// before identity checks or RPC queueing. No relative deadline is renewed.
    async fn value(
        &self,
        handle: u16,
        value: Option<Vec<u8>>,
        minimum: u32,
        original: crate::Deadline,
        method: &'static str,
    ) -> Result<Vec<u8>> {
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        let result = tokio::time::timeout_at(
            original.instant().into(),
            self.current(async {
                original.remaining()?;
                let proxy = self
                    .link
                    .client
                    .proxy(&self.link.path, contract::CONNECTION)
                    .await?;
                original.remaining()?;
                let deadline = contract::deadline_wire(original.stamp());
                let result: Vec<u8> = match value {
                    None => proxy.call(method, &(handle, minimum, deadline)).await?,
                    Some(value) => {
                        proxy
                            .call(method, &(handle, value, minimum, deadline))
                            .await?
                    }
                };
                original.remaining()?;
                Ok(result)
            }),
        )
        .await
        .map_err(|_| {
            ApplicationError::Io(std::io::Error::from_raw_os_error(nix::libc::ETIMEDOUT))
        })??;
        original.remaining()?;
        Ok(result)
    }
    /// Uses the daemon's bounded value contract and negotiated wire support.
    /// The SDK never truncates, fragments independently, retries an uncertain
    /// write or substitutes a local echo for the peer result.
    pub async fn write(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        original: crate::Deadline,
    ) -> Result<Vec<u8>> {
        self.value(handle, Some(value), minimum, original, wire::WRITE)
            .await
    }
    /// Invoke a remote method, returning its independent application result.
    /// No retry or input echo. A timeout may follow an executed remote effect.
    /// Current local daemon method providers are not yet supported.
    pub async fn call_method(
        &self,
        handle: u16,
        arguments: Vec<u8>,
        minimum: u32,
        original: crate::Deadline,
    ) -> Result<Vec<u8>> {
        Self::method_arguments(handle, minimum, &arguments)?;
        let result = self
            .value(
                handle,
                Some(arguments),
                minimum,
                original,
                wire::CALL_METHOD,
            )
            .await?;
        if result.len() > 2045 {
            return Err(ApplicationError::Io(std::io::Error::from_raw_os_error(
                nix::libc::EPROTO,
            )));
        }
        Ok(result)
    }
    fn method_arguments(handle: u16, minimum: u32, arguments: &[u8]) -> Result<()> {
        if handle == 0 || minimum > 2 {
            return Err(ApplicationError::Invalid("method handle/security"));
        }
        if arguments.len() > 2043 {
            return Err(ApplicationError::Io(std::io::Error::from_raw_os_error(
                nix::libc::EMSGSIZE,
            )));
        }
        Ok(())
    }
    /// Software admission only; no method response or delivery confirmation.
    pub async fn call_method_without_response(
        &self,
        handle: u16,
        arguments: Vec<u8>,
        minimum: u32,
        original: crate::Deadline,
    ) -> Result<()> {
        Self::method_arguments(handle, minimum, &arguments)?;
        self.command(
            handle,
            arguments,
            minimum,
            original,
            wire::CALL_METHOD_COMMAND,
        )
        .await
    }
    /// Submit one property WRITE_NO_RSP through the existing daemon actor.
    /// Success means all command fragments entered the software socket path;
    /// it is not USB/controller completion, peer receipt or application handling.
    /// The original deadline includes identity/RPC queueing, with the same5s
    /// ceiling as write. Failure may follow partial admission; never retry an
    /// uncertain command implicitly. No descriptor or multi-item operation.
    pub async fn write_without_response(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        original: crate::Deadline,
    ) -> Result<()> {
        self.command(handle, value, minimum, original, wire::WRITE_COMMAND)
            .await
    }
    async fn command(
        &self,
        handle: u16,
        value: Vec<u8>,
        minimum: u32,
        original: crate::Deadline,
        method: &'static str,
    ) -> Result<()> {
        let original = original.capped(slk_channel::deadline::PROTOCOL_WAIT)?;
        crate::client::bounded(
            &self.link.client,
            original,
            self.current(async {
                original.remaining()?;
                let proxy = self
                    .link
                    .client
                    .proxy(&self.link.path, contract::CONNECTION)
                    .await?;
                original.remaining()?;
                let _: () = proxy
                    .call(
                        method,
                        &(
                            handle,
                            value,
                            minimum,
                            contract::deadline_wire(original.stamp()),
                        ),
                    )
                    .await?;
                original.remaining()?;
                Ok(())
            }),
        )
        .await?;
        original.remaining()?;
        Ok(())
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
