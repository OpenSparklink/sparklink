//! Shared transport contract, independent of application SDK and daemon.
//! Values describe observations, not authority or proof of physical completion.
use slk_protocol::SleAddr;
pub mod controller_events;
pub mod discovery;
pub mod link_parameter;
pub mod link_query;
pub mod security;

/// Absolute CLOCK_MONOTONIC ns, UUID high/low (big-endian bytes), namespace
/// device/inode. Five fixed uint64 fields avoid variable-length allocation and
/// Rust fixed-array/DBus-struct ambiguity. Pure transport, never authority.
pub type Deadline = (u64, u64, u64, u64, u64);
pub fn deadline_wire(stamp: slk_protocol::deadline::DeadlineStamp) -> Deadline {
    (
        stamp.monotonic_ns,
        u64::from_be_bytes(stamp.boot_id[..8].try_into().expect("fixed UUID half")),
        u64::from_be_bytes(stamp.boot_id[8..].try_into().expect("fixed UUID half")),
        stamp.time_namespace_device,
        stamp.time_namespace_inode,
    )
}
pub fn deadline_stamp(value: Deadline) -> slk_protocol::deadline::DeadlineStamp {
    let mut boot_id = [0; 16];
    boot_id[..8].copy_from_slice(&value.1.to_be_bytes());
    boot_id[8..].copy_from_slice(&value.2.to_be_bytes());
    slk_protocol::deadline::DeadlineStamp {
        monotonic_ns: value.0,
        boot_id,
        time_namespace_device: value.3,
        time_namespace_inode: value.4,
    }
}

pub const SERVICE: &str = "org.sparklink";
pub const MANAGER_PATH: &str = "/org/sparklink";
pub const MANAGER: &str = "org.sparklink.Manager";
pub const ADAPTER: &str = "org.sparklink.Adapter";
pub const CONNECTION: &str = "org.sparklink.Connection";
pub const GET_INFO: &str = "GetInfo";
pub const LIST_ADAPTERS: &str = "ListAdapters";
pub const OPEN_CHANNEL: &str = "OpenChannel";
pub const OPEN_CHANNEL_SCOPED: &str = "OpenChannelScoped";
pub const PREPARE_DYNAMIC_CHANNEL: &str = "PrepareDynamicChannel";

pub type ConnectionInfo = (u64, u64, u16, u8, u8, String, bool, bool);
/// generation, address type/address, valid advertisement, RSSI known/value,
/// raw WS73 header/data, Native sequence/kernel boottime/lost. Unknown RSSI's
/// numeric field is non-authoritative; the SDK presents it as None.
pub type PeerObservation = (
    u64,
    u8,
    String,
    bool,
    bool,
    i16,
    Vec<u8>,
    Vec<u8>,
    u64,
    u64,
    u64,
);
pub const MAX_PEERS: usize = 128;
pub const LIST_PEERS: &str = "ListPeers";
pub const PEER_OBSERVATION: &str = "GetObservation";
pub type PeerInfo = (u64, u8, String, bool, bool, Vec<String>);
pub type ConnectionObjects = (u64, u64, u64, bool, Vec<(String, u64, u16, u8, u8, String)>);
pub type SecurityState = (u64, u64, u16, u64, u32, u32, u32, u8, u8);
pub type DynamicRequest = (u16, u16, u16, u16, u16, u8, bool);

/// Existing daemon SSAP wire contract, not a second protocol implementation.
pub mod ssap {
    /// D-Bus service authorization context, not a kernel Grant or peer identity:
    /// controller, generation, lifetime, connection handle, original RX security
    /// epoch/level, local TCID, remote TCID, PI.
    pub type SsapAuthorizationIdentity = (u16, u64, u64, u16, u64, u32, u8, u8, u8);
    /// Request ID, original context, local property, write?, original monotonic
    /// deadline, proposed write value (empty for reads). Reads disclose no value
    /// to the authorizer before its decision. The final byte is the original
    /// SSAP data type (property value0 or client configuration2); it is part of the policy
    /// scope, not inferred from the handle or granted by a local decision.
    pub type SsapAuthorizationPrompt =
        (u64, SsapAuthorizationIdentity, u16, bool, u64, Vec<u8>, u8);

    /// Local manager staging and caller-owned registration are distinct roles.
    pub mod local {
        pub const MANAGER: &str = "org.sparklink.ServiceManager";
        pub const LIST: &str = "ListLocalServices";
        pub const REGISTER: &str = "RegisterLocalService";
        pub const REMOVE: &str = "RemoveLocalService";
        pub const READ: &str = "ReadLocalValue";
        pub const REGISTER_OWNED: &str = "RegisterOwnedLocalService";
        pub const UNREGISTER_OWNED: &str = "UnregisterOwnedLocalService";
        pub const READ_OWNED: &str = "ReadOwnedLocalValue";
        pub const REPLACE_OWNED: &str = "ReplaceOwnedLocalValue";
        pub const SET_DESCRIPTION_OWNED: &str = "SetOwnedLocalDescription";
        /// Implementation bound in UTF-8 bytes, not a standard maximum.
        pub const MAX_DESCRIPTION_BYTES: usize = 244;
        pub type PropertyDefinition = (Vec<u8>, u32, u32, Vec<u8>);
        pub type PropertyRecord = (u16, Vec<u8>, u32, u32);
        pub type ServiceRecord = (u16, u16, Vec<u8>, Vec<PropertyRecord>);
        pub type Registration = (u16, u16, Vec<u16>);
        pub type OwnedRegistrationRequest = (
            Vec<u8>,
            Vec<PropertyDefinition>,
            zvariant::OwnedObjectPath,
            crate::Deadline,
        );
        pub type OwnedHandleRequest = (u16, crate::Deadline);
        pub type OwnedValueRequest = (u16, Vec<u8>, crate::Deadline);
        pub type OwnedDescriptionRequest = (u16, String, crate::Deadline);
    }
    pub const DISCOVER: &str = "DiscoverSsap";
    pub const CACHED: &str = "GetCachedSsap";
    pub const RECEIVE: &str = "ReceiveSsapUpdate";
    pub const OWNED_UPDATE: &str = "SendOwnedSsapUpdate";
    pub const OWNED_CONFIGURATION: &str = "GetOwnedSsapConfiguration";
    /// stage1: notification software admission only; stage2: indication accepted
    /// by the peer's protocol receive queue. Neither means application processing.
    #[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize, zvariant::Type)]
    pub struct UpdateReceipt {
        pub stage: u8,
        pub pdu: Vec<u8>,
        pub acknowledgement: Vec<u8>,
    }
    pub const READ_UUID: &str = "ReadSsapByUuid";
    pub const READ: &str = "ReadSsapValue";
    /// Public read-only type1 description, independent of property permissions.
    pub const READ_DESCRIPTION: &str = "ReadSsapDescription";
    pub const WRITE: &str = "WriteSsapValue";
    /// Empty return means all command fragments were admitted to the software
    /// socket path, not controller completion or peer receipt/processing.
    pub const WRITE_COMMAND: &str = "WriteSsapCommand";
    pub const EXCHANGE_INFO: &str = "GetSsapInfo";
    pub type Entry = (u8, u16, u16, Vec<u8>, u32, Vec<u8>, u8);
    pub type Discovery = (Vec<Entry>, Vec<(Vec<u8>, Vec<u8>)>);
    pub type Incoming = (bool, Vec<u8>);
    /// One caller-owned leased receive scope on the original physical actor.
    /// A protocol ACK means bounded queue acceptance,not application handling.
    pub mod subscription {
        pub const CREATE: &str = "SubscribeSsapUpdates";
        pub const READ: &str = "ReadSsapUpdates";
        pub const RENEW: &str = "RenewSsapSubscription";
        pub const CLOSE: &str = "CloseSsapSubscription";
        pub const CAPACITY: usize = 16;
        pub const BYTE_BUDGET: usize = 32768;
        pub const STARTING: u8 = 0;
        pub const ACTIVE: u8 = 1;
        pub const CLOSING: u8 = 2;
        pub const CLOSED: u8 = 3;
        pub const RELEASED: u8 = 1;
        pub const EXPIRED: u8 = 2;
        pub const OWNER_LOST: u8 = 3;
        pub const INITIALIZATION_CANCELLED: u8 = 4;
        /// This lease's routing and configuration ownership are released.
        /// Without REMOTE_RETAINED,the last remote configuration was verified off.
        pub const CLEANUP_CONFIRMED: u32 = 1;
        /// At this lease's terminal observation,other same-scope leases still
        /// owned the remote CPCD. Not a claim that it is currently enabled.
        pub const REMOTE_RETAINED: u32 = 2;
        #[derive(
            Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize, zvariant::Type,
        )]
        pub struct Info {
            pub version: u32,
            pub controller: u16,
            pub generation: u64,
            pub lifetime: u64,
            pub handle: u16,
            pub security_epoch: u64,
            pub token: u64,
            pub expires_ns: u64,
            pub handles: Vec<u16>,
            pub modes: u8,
            pub state: u8,
            pub capacity: u16,
        }
        #[derive(
            Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize, zvariant::Type,
        )]
        pub struct Packet {
            pub sequence: u64,
            pub security_epoch: u64,
            pub security_level: u32,
            pub indication: bool,
            pub pdu: Vec<u8>,
        }
        #[derive(
            Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize, zvariant::Type,
        )]
        pub struct Batch {
            pub info: Info,
            pub last_sequence: u64,
            pub dropped_notifications: u64,
            pub refused_indications: u64,
            pub discarded_on_close: u64,
            pub flags: u32,
            pub reason: u8,
            pub packets: Vec<Packet>,
        }
        pub fn valid_request(handles: &[u16], modes: u8, duration_ms: u32) -> bool {
            !handles.is_empty()
                && handles.len() <= 32
                && !handles.contains(&0)
                && handles
                    .iter()
                    .enumerate()
                    .all(|(i, h)| !handles[..i].contains(h))
                && (1..=3).contains(&modes)
                && (250..=60000).contains(&duration_ms)
        }
    }
    pub type UuidValues = (Vec<(u16, bool, u16, Vec<u8>)>, Vec<u8>, Vec<u8>);
    pub type ExchangeInfo = (
        u16,
        u64,
        u64,
        u16,
        u16,
        u16,
        Vec<u8>,
        Vec<u8>,
        Vec<u8>,
        Vec<u8>,
    );
}
pub const TRANSPORT_STATUS: &str = "GetTransportStatus";
pub type TransportInfo = (
    u16,
    u64,
    u64,
    u16,
    u16,
    u16,
    u16,
    u16,
    u16,
    u16,
    u16,
    u16,
    u16,
    u16,
    u32,
);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ControllerId {
    pub index: u16,
    pub generation: u64,
}
impl ControllerId {
    pub fn path(self) -> String {
        format!("{MANAGER_PATH}/slk{}_g{}", self.index, self.generation)
    }
    pub fn from_path(path: &str) -> Option<Self> {
        let suffix = path.strip_prefix(&format!("{MANAGER_PATH}/slk"))?;
        let (index, generation) = suffix.split_once("_g")?;
        let id = Self {
            index: index.parse().ok()?,
            generation: generation.parse().ok()?,
        };
        (id.generation != 0 && id.path() == path).then_some(id)
    }
}

pub fn peer_path(base: &str, kind: u8, address: SleAddr) -> String {
    let address = address
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect::<String>();
    format!("{base}/peer_t{kind:02x}_{address}")
}
/// Stable observation identity only. Not a connection lifetime or a Grant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PeerId {
    pub controller: ControllerId,
    pub address_type: u8,
    pub address: SleAddr,
}
impl PeerId {
    pub fn path(self) -> String {
        peer_path(&self.controller.path(), self.address_type, self.address)
    }
    pub fn from_path(path: &str) -> Option<Self> {
        let (base, suffix) = path.rsplit_once("/peer_t")?;
        let (kind, address) = suffix.split_once('_')?;
        if kind.len() != 2 || address.len() != 12 || !address.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return None;
        }
        let address_type = u8::from_str_radix(kind, 16).ok()?;
        if address_type > 1 {
            return None;
        }
        let mut bytes = [0; 6];
        for (i, b) in bytes.iter_mut().enumerate() {
            *b = u8::from_str_radix(&address[i * 2..i * 2 + 2], 16).ok()?;
        }
        let id = Self {
            controller: ControllerId::from_path(base)?,
            address_type,
            address: bytes,
        };
        (id.path() == path).then_some(id)
    }
}
pub fn connection_path(base: &str, kind: u8, address: SleAddr, lifetime: u64) -> String {
    format!("{}/link_{lifetime:016x}", peer_path(base, kind, address))
}
pub fn parse_address(value: &str) -> Option<SleAddr> {
    let mut result = [0; 6];
    let mut components = value.split(':');
    for octet in &mut result {
        let value = components.next()?;
        if value.len() != 2 || !value.bytes().all(|b| b.is_ascii_hexdigit()) {
            return None;
        }
        *octet = u8::from_str_radix(value, 16).ok()?;
    }
    components.next().is_none().then_some(result)
}
/// Identity only, not Ready, security, authorization or future connection state.
pub fn matches_connection(controller: ControllerId, path: &str, info: &ConnectionInfo) -> bool {
    info.0 == controller.generation
        && info.1 != 0
        && parse_address(&info.5).is_some_and(|address| {
            connection_path(&controller.path(), info.4, address, info.1) == path
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn authorizer_contract_preserves_literal_field_order_and_signatures() {
        use zvariant::Type;
        let identity: ssap::SsapAuthorizationIdentity = (2, 7, 11, 3, 19, 1, 10, 10, 0);
        let prompt: ssap::SsapAuthorizationPrompt = (23, identity, 29, true, 31, vec![37], 0);
        assert_eq!(
            prompt,
            (
                23,
                (2, 7, 11, 3, 19, 1, 10, 10, 0),
                29,
                true,
                31,
                vec![37],
                0
            )
        );
        assert_eq!(
            ssap::SsapAuthorizationIdentity::SIGNATURE.to_string(),
            "(qttqtuyyy)"
        );
        assert_eq!(
            ssap::SsapAuthorizationPrompt::SIGNATURE.to_string(),
            "(t(qttqtuyyy)qbtayy)"
        );
    }

    #[test]
    fn deadline_has_literal_field_order_and_dbus_shape() {
        use zvariant::Type;
        let value = slk_protocol::deadline::DeadlineStamp {
            monotonic_ns: 19,
            boot_id: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            time_namespace_device: 23,
            time_namespace_inode: 29,
        };
        assert_eq!(
            deadline_wire(value),
            (19, 0x0001020304050607, 0x08090a0b0c0d0e0f, 23, 29)
        );
        assert_eq!(
            deadline_stamp((19, 0x0001020304050607, 0x08090a0b0c0d0e0f, 23, 29)),
            value
        );
        assert_eq!(Deadline::SIGNATURE.to_string(), "(ttttt)");
    }
    #[test]
    fn literal_identity_and_alias_rejection() {
        let id = ControllerId {
            index: 2,
            generation: 7,
        };
        assert_eq!(id.path(), "/org/sparklink/slk2_g7");
        assert_eq!(ControllerId::from_path(&id.path()), Some(id));
        for p in [
            "/org/sparklink/slk02_g7",
            "/org/sparklink/slk2_g0",
            "/org/sparklink/slk2_g7/extra",
        ] {
            assert_eq!(ControllerId::from_path(p), None);
        }
        let path = "/org/sparklink/slk2_g7/peer_t01_010203040506/link_000000000000000b";
        let info = (7, 11, 3, 0, 1, "01:02:03:04:05:06".into(), true, true);
        assert!(matches_connection(id, path, &info));
        for index in [0, 1] {
            let mut bad = info.clone();
            if index == 0 {
                bad.0 += 1;
            } else {
                bad.1 += 1;
            }
            assert!(!matches_connection(id, path, &bad));
        }
        for address in [
            "010203040506",
            "01:02:03:04:05",
            "01:02:03:04:05:06:07",
            "01:02:03:04:05:gg",
            "1:02:03:04:05:06",
        ] {
            assert!(parse_address(address).is_none());
        }
    }
}

/// Current controller observations and explicit privileged management requests.
/// Values are wire observations, never a Native lease or readiness authority.
pub mod controller {
    pub const REGISTRATION: &str = "org.sparklink.Registration";
    pub const CORE: &str = "org.sparklink.Controller";
    pub const PEER: &str = "org.sparklink.Peer";
    pub const LIST_REGISTRATIONS: &str = "ListRegistrations";
    pub const REGISTRATION_SNAPSHOT: &str = "GetSnapshot";
    pub const REPORTS: &str = "GetReports";
    pub const TIMED_REPORTS: &str = "GetTimedReports";
    pub const DISCOVERY_POLICY: &str = "GetDiscoveryPolicy";
    pub const MANAGEMENT_STATUS: &str = "GetManagementStatus";
    pub const ADVERTISE: &str = "SubmitAdvertising";
    pub const CONNECTABLE: &str = "SubmitConnectableAdvertising";
    pub const STOP_ADVERTISE: &str = "SubmitStopAdvertising";
    pub const SCAN: &str = "SubmitScanning";
    pub const STOP_SCAN: &str = "SubmitStopScanning";
    pub const START_CONTROLLER_SCAN: &str = "StartControllerScan";
    pub const STOP_CONTROLLER_SCAN: &str = "StopControllerScan";
    pub const DISCOVERY_RESULT: &str = "GetDiscoveryResult";
    pub const INITIALIZATION_OFF: &str = "GetInitializationOff";
    pub const DISCOVERY_TIMING: &str = "GetDiscoveryTiming";
    pub const CANCEL_DISCOVERY: &str = "CancelDiscoveryPolicies";
    pub const ALLOCATE_CONNECTION: &str = "AllocateConnectionRequest";
    pub const CONNECT: &str = "SubmitConnect";
    pub const DISCONNECT: &str = "SubmitDisconnect";
    pub const DISCONNECT_TYPED: &str = "SubmitDisconnectTyped";
    pub const DISCONNECT_REFERENCE: &str = "SubmitDisconnectReference";
    pub const CONNECTION_RESULT: &str = "GetConnectionResult";
    pub const LINKS: &str = "GetNativeConnections";
    pub const OBJECTS: &str = "GetNativeConnectionObjects";
    pub const LINK_SUMMARY: &str = "GetLinkSummary";
    pub const EVENT_POSITION: &str = "GetControllerEventPosition";
    pub type Reports = Vec<(u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64)>;
    pub type Links = (u64, u64, u64, u32, i32, Vec<(u64, u16, u8, u8, String)>);
    pub type Policy = (u32, u32, u32, i32, u32, u32);
    pub type ManagementStatus = (u64, u32, u32, u32, i32, u32, u32);
    pub type Timing = (u64, u64, u64, u32, u32, u16, u8);
    pub type ConnectionResult = (u64, u64, u32, u32, i32, i32, u32, u32, u32, u32);
    pub type LinkSummary = (u16, u64, u64, u64, u32);
    pub type EventPosition = (u16, u64, u64);
}

/// Identity/observation only; a peer's connection paths are still separately
/// resolved and checked before any authorization or operation.
pub fn matches_peer(controller: ControllerId, path: &str, info: &PeerInfo) -> bool {
    info.0 == controller.generation
        && parse_address(&info.2)
            .is_some_and(|address| peer_path(&controller.path(), info.1, address) == path)
}

#[cfg(test)]
mod peer_identity_tests {
    use super::*;
    #[test]
    fn typed_peer_ids_require_canonical_controller_type_address_and_no_link_alias() {
        let p = "/org/sparklink/slk2_g7/peer_t01_010203040506";
        let id = PeerId::from_path(p).unwrap();
        assert_eq!(id.address_type, 1);
        assert_eq!(id.path(), p);
        for bad in [
            p.replace("t01_", "t06_"),
            p.replace("slk2_", "slk02_"),
            p.replace("g7/", "g0/"),
            p.replace("010203040506", "01020304050F"),
            format!("{p}/link_0000000000000001"),
            p.replace("010203040506", "中文中文"),
        ] {
            assert!(PeerId::from_path(&bad).is_none(), "{bad}");
        }
    }
}

/// D-Bus mechanism observation, not an SSAP capability or a readiness grant.
pub fn transport_info(v: slk_protocol::SleSessionTxStatus) -> TransportInfo {
    (
        v.controller,
        v.generation,
        v.lifetime,
        v.handle,
        v.capacity,
        v.outstanding,
        v.connection_debt,
        v.queued,
        v.active_pdus,
        v.dynamic_open,
        v.dynamic_pending,
        v.dynamic_retired,
        v.dynamic_failed,
        v.dynamic_allocated,
        v.flags,
    )
}

#[cfg(test)]
mod owned_deadline_contract {
    use zvariant::Type;
    #[test]
    fn owned_requests_have_one_original_stamp_and_no_legacy_shape() {
        assert_eq!(
            super::ssap::local::OwnedRegistrationRequest::SIGNATURE.to_string(),
            "(aya(ayuuay)o(ttttt))"
        );
        assert_eq!(
            super::ssap::local::OwnedHandleRequest::SIGNATURE.to_string(),
            "(q(ttttt))"
        );
        assert_eq!(
            super::ssap::local::OwnedValueRequest::SIGNATURE.to_string(),
            "(qay(ttttt))"
        );
        assert_eq!(
            super::ssap::local::OwnedDescriptionRequest::SIGNATURE.to_string(),
            "(qs(ttttt))"
        );
    }
}
