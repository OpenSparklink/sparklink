//! Typed observations from the pinned broker, never cached connection authority.
use crate::{ApplicationError, Client};
use slk_contract::{self as contract, PeerId};
type Result<T> = std::result::Result<T, ApplicationError>;
#[derive(Clone)]
pub struct Peer {
    pub(crate) client: Client,
    pub(crate) id: PeerId,
}
#[derive(Debug)]
pub struct Observation {
    pub id: PeerId,
    pub valid: bool,
    pub rssi: Option<i16>,
    pub header: Vec<u8>,
    pub data: Vec<u8>,
    pub sequence: u64,
    pub kernel_boottime_ns: u64,
    pub lost: u64,
}
impl Peer {
    pub fn id(&self) -> PeerId {
        self.id
    }
    pub fn path(&self) -> String {
        self.id.path()
    }
    pub async fn info(&self) -> Result<contract::PeerInfo> {
        self.client
            .peer_info(&self.id.controller.path(), &self.path())
            .await
    }
    pub async fn observation(&self) -> Result<Observation> {
        self.client.check_generation(self.id.controller).await?;
        let v: contract::PeerObservation = self
            .client
            .proxy(&self.path(), contract::controller::PEER)
            .await?
            .call(contract::PEER_OBSERVATION, &())
            .await?;
        if v.0 != self.id.controller.generation
            || v.1 != self.id.address_type
            || contract::parse_address(&v.2) != Some(self.id.address)
            || (v.4 && (!v.3 || !(-128..=126).contains(&v.5)))
        {
            return Err(ApplicationError::Identity("typed Peer observation"));
        }
        self.client.check_generation(self.id.controller).await?;
        Ok(Observation {
            id: self.id,
            valid: v.3,
            rssi: v.4.then_some(v.5),
            header: v.6,
            data: v.7,
            sequence: v.8,
            kernel_boottime_ns: v.9,
            lost: v.10,
        })
    }
}
