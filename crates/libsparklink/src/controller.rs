//! Controller observations and explicit broker management. No control fd,
//! Native lease, retry Engine or invented hardware state is exposed.
use crate::{ApplicationConnection, ApplicationError, Client};
use slk_contract::{self as contract, ControllerId, controller as wire};
type Result<T> = std::result::Result<T, ApplicationError>;
#[derive(Clone)]
pub struct Controller {
    client: Client,
    id: ControllerId,
}
impl Controller {
    pub(crate) fn new(client: Client, id: ControllerId) -> Self {
        Self { client, id }
    }
    pub fn id(&self) -> ControllerId {
        self.id
    }
    pub fn path(&self) -> String {
        self.id.path()
    }
    /// This view grants no privilege. Every request still crosses the broker
    /// and its real policy/kernel authorization; no Native lease is returned.
    pub fn management(&self) -> Management {
        Management {
            controller: self.clone(),
        }
    }
    async fn call<B, R>(&self, interface: &'static str, method: &str, body: &B) -> Result<R>
    where
        B: serde::Serialize + zbus::zvariant::DynamicType,
        R: for<'d> zbus::zvariant::DynamicDeserialize<'d>,
    {
        self.client.check_generation(self.id).await?;
        let path = if interface == wire::CORE {
            format!("{}/controller", self.path())
        } else {
            self.path()
        };
        let result = self
            .client
            .proxy(&path, interface)
            .await?
            .call(method, body)
            .await?;
        self.client.check_generation(self.id).await?;
        Ok(result)
    }
    async fn property<T>(&self, name: &str) -> Result<T>
    where
        T: TryFrom<zbus::zvariant::OwnedValue>,
        T::Error: Into<zbus::Error>,
    {
        self.client.check_generation(self.id).await?;
        let value = self
            .client
            .proxy(&self.path(), contract::ADAPTER)
            .await?
            .get_property(name)
            .await?;
        self.client.check_generation(self.id).await?;
        Ok(value)
    }
    pub async fn peers(&self) -> Result<Vec<crate::peer::Peer>> {
        let paths: Vec<String> = self
            .call(contract::ADAPTER, contract::LIST_PEERS, &())
            .await?;
        if paths.len() > contract::MAX_PEERS {
            return Err(ApplicationError::Identity("Peer list budget"));
        }
        let mut peers = Vec::with_capacity(paths.len());
        for path in paths {
            let id = contract::PeerId::from_path(&path)
                .ok_or(ApplicationError::Identity("Peer path"))?;
            if id.controller != self.id || peers.iter().any(|p: &crate::peer::Peer| p.id() == id) {
                return Err(ApplicationError::Identity("foreign or duplicate Peer"));
            }
            peers.push(crate::peer::Peer {
                client: self.client.clone(),
                id,
            });
        }
        Ok(peers)
    }
    pub async fn generation(&self) -> Result<u64> {
        self.client.check_generation(self.id).await?;
        Ok(self.id.generation)
    }
    pub async fn name(&self) -> Result<String> {
        self.property("Name").await
    }
    pub async fn address(&self) -> Result<String> {
        self.property("Address").await
    }
    pub async fn state(&self) -> Result<String> {
        self.property("ControllerState").await
    }
    pub async fn scanning_state(&self) -> Result<u32> {
        self.property("ScanningState").await
    }
    pub async fn profile(&self) -> Result<u32> {
        self.property("Profile").await
    }
    pub async fn initialization_error(&self) -> Result<String> {
        self.property("InitializationError").await
    }
    pub async fn link_observation(&self) -> Result<(u64, u64, bool)> {
        self.property("NativeLinkObservation").await
    }
    pub async fn events_lost(&self) -> Result<u64> {
        self.property("EventsLost").await
    }
    pub async fn reports(&self) -> Result<wire::Reports> {
        self.call(contract::ADAPTER, wire::REPORTS, &()).await
    }
    pub async fn timed_reports(&self) -> Result<Vec<slk_protocol::TimedDiscoveryReportRecord>> {
        self.call(contract::ADAPTER, wire::TIMED_REPORTS, &()).await
    }
    pub async fn discovery_policy(&self) -> Result<wire::Policy> {
        self.call(contract::ADAPTER, wire::DISCOVERY_POLICY, &())
            .await
    }
    pub async fn management_status(&self) -> Result<wire::ManagementStatus> {
        let value: wire::ManagementStatus = self
            .call(contract::ADAPTER, wire::MANAGEMENT_STATUS, &())
            .await?;
        if value.0 != self.id.generation {
            return Err(ApplicationError::Identity("management result generation"));
        }
        Ok(value)
    }
    pub async fn links(&self) -> Result<wire::Links> {
        let value: wire::Links = self.call(contract::ADAPTER, wire::LINKS, &()).await?;
        if value.0 != self.id.generation {
            return Err(ApplicationError::Identity("link observation generation"));
        }
        Ok(value)
    }
    pub async fn connection_objects(&self) -> Result<contract::ConnectionObjects> {
        let value: contract::ConnectionObjects =
            self.call(contract::ADAPTER, wire::OBJECTS, &()).await?;
        if value.0 != self.id.generation {
            return Err(ApplicationError::Identity("connection object generation"));
        }
        Ok(value)
    }
    pub async fn link_summary(&self) -> Result<wire::LinkSummary> {
        let v: wire::LinkSummary = self.call(wire::CORE, wire::LINK_SUMMARY, &()).await?;
        if (v.0, v.1) != (self.id.index, self.id.generation) {
            return Err(ApplicationError::Identity("link summary controller"));
        }
        Ok(v)
    }
    pub async fn event_position(&self) -> Result<wire::EventPosition> {
        let v: wire::EventPosition = self.call(wire::CORE, wire::EVENT_POSITION, &()).await?;
        if (v.0, v.1) != (self.id.index, self.id.generation) {
            return Err(ApplicationError::Identity("event position controller"));
        }
        Ok(v)
    }
}
#[derive(Clone)]
pub struct Management {
    controller: Controller,
}
impl Management {
    pub async fn advertise(&self, id: u64, marker: Vec<u8>) -> Result<Vec<u8>> {
        self.controller
            .call(contract::ADAPTER, wire::ADVERTISE, &(id, marker))
            .await
    }
    pub async fn advertise_connectable(
        &self,
        id: u64,
        marker: Vec<u8>,
        negotiable: bool,
    ) -> Result<Vec<u8>> {
        self.controller
            .call(
                contract::ADAPTER,
                wire::CONNECTABLE,
                &(id, marker, negotiable),
            )
            .await
    }
    pub async fn stop_advertising(&self, id: u64) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::STOP_ADVERTISE, &(id,))
            .await
    }
    pub async fn scan(&self, id: u64) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::SCAN, &(id,))
            .await
    }
    pub async fn stop_scanning(&self, id: u64) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::STOP_SCAN, &(id,))
            .await
    }
    pub async fn start_controller_scan(&self) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::START_CONTROLLER_SCAN, &())
            .await
    }
    pub async fn stop_controller_scan(&self) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::STOP_CONTROLLER_SCAN, &())
            .await
    }
    pub async fn discovery_result(&self, id: u64) -> Result<slk_protocol::DiscoveryResultRecord> {
        let v: slk_protocol::DiscoveryResultRecord = self
            .controller
            .call(contract::ADAPTER, wire::DISCOVERY_RESULT, &(id,))
            .await?;
        if (v.0, v.1, v.13) != (self.controller.id.generation, id, 1) {
            return Err(ApplicationError::Identity("discovery request result"));
        }
        Ok(v)
    }
    pub async fn initialization_off(
        &self,
        operation: u32,
    ) -> Result<slk_protocol::DiscoveryResultRecord> {
        let v: slk_protocol::DiscoveryResultRecord = self
            .controller
            .call(contract::ADAPTER, wire::INITIALIZATION_OFF, &(operation,))
            .await?;
        if v.0 != self.controller.id.generation || v.2 != operation || v.13 != 1 {
            return Err(ApplicationError::Identity("initialization observation"));
        }
        Ok(v)
    }
    pub async fn discovery_timing(&self, id: u64) -> Result<wire::Timing> {
        let v: wire::Timing = self
            .controller
            .call(contract::ADAPTER, wire::DISCOVERY_TIMING, &(id,))
            .await?;
        if (v.0, v.1) != (self.controller.id.generation, id) {
            return Err(ApplicationError::Identity("discovery timing identity"));
        }
        Ok(v)
    }
    pub async fn cancel_discovery(&self) -> Result<u64> {
        let generation = self
            .controller
            .call(contract::ADAPTER, wire::CANCEL_DISCOVERY, &())
            .await?;
        if generation != self.controller.id.generation {
            return Err(ApplicationError::Identity("cancel generation"));
        }
        Ok(generation)
    }
    pub async fn allocate_connection_request(&self) -> Result<u64> {
        let id = self
            .controller
            .call(contract::ADAPTER, wire::ALLOCATE_CONNECTION, &())
            .await?;
        if id == 0 {
            return Err(ApplicationError::Identity("zero connection request"));
        }
        Ok(id)
    }
    pub async fn connect(&self, id: u64, address: &str, kind: u8) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::CONNECT, &(id, address, kind))
            .await
    }
    pub async fn disconnect(&self, id: u64, address: &str) -> Result<()> {
        self.controller
            .call(contract::ADAPTER, wire::DISCONNECT, &(id, address))
            .await
    }
    pub async fn disconnect_typed(&self, id: u64, address: &str, kind: u8) -> Result<()> {
        self.controller
            .call(
                contract::ADAPTER,
                wire::DISCONNECT_TYPED,
                &(id, address, kind),
            )
            .await
    }
    pub async fn disconnect_reference(
        &self,
        id: u64,
        address: &str,
        kind: u8,
        handle: u16,
        lifetime: u64,
        role: u8,
    ) -> Result<()> {
        self.controller
            .call(
                contract::ADAPTER,
                wire::DISCONNECT_REFERENCE,
                &(id, address, kind, handle, lifetime, role),
            )
            .await
    }
    pub async fn disconnect_object(&self, id: u64, path: &str) -> Result<()> {
        let link: ApplicationConnection = self
            .controller
            .client
            .connection(&self.controller.path(), path)
            .await?;
        let _: () = self
            .controller
            .client
            .proxy(link.path(), contract::CONNECTION)
            .await?
            .call(wire::DISCONNECT, &(id,))
            .await?;
        self.controller
            .client
            .check_generation(self.controller.id)
            .await?;
        Ok(())
    }
    pub async fn connection_result(&self, id: u64) -> Result<wire::ConnectionResult> {
        let v: wire::ConnectionResult = self
            .controller
            .call(contract::ADAPTER, wire::CONNECTION_RESULT, &(id,))
            .await?;
        if (v.0, v.1) != (self.controller.id.generation, id) {
            return Err(ApplicationError::Identity("connection request result"));
        }
        Ok(v)
    }
}
