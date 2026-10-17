use std::collections::HashMap;
use zbus::interface;
use zbus::zvariant::Value;

use crate::state::{AdapterDirectory, RegistrationDirectory, SharedState};

/// Root D-Bus object at /org/sparklink
pub struct Root {
    adapters: AdapterDirectory,
    registrations: RegistrationDirectory,
}

impl Root {
    pub fn new(adapters: AdapterDirectory, registrations: RegistrationDirectory) -> Self {
        Self {
            adapters,
            registrations,
        }
    }
}

#[interface(name = "org.sparklink.Manager")]
impl Root {
    /// Get the daemon version
    fn version(&self) -> &str {
        env!("CARGO_PKG_VERSION")
    }

    /// Published observations, including pre-Runtime faults. Revalidate exact
    /// Core identity; the directory never supplies cached availability or Ready.
    async fn list_registrations(&self) -> zbus::fdo::Result<Vec<String>> {
        let entries = self.registrations.lock().await.clone();
        tokio::task::spawn_blocking(move || {
            let mut paths = Vec::new();
            for (path, entry) in entries {
                match entry
                    .adapter
                    .registration_snapshot(entry.index, entry.generation)
                {
                    Ok(_) => paths.push(path),
                    Err(slk_native::Error::Ioctl(nix::errno::Errno::ENODEV)) => {}
                    Err(error) => {
                        return Err(zbus::fdo::Error::Failed(format!(
                            "Core registration observation failed for {path}: {error}"
                        )));
                    }
                }
            }
            Ok(paths)
        })
        .await
        .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))?
    }

    /// List registrations still live in the kernel, even before the background
    /// manager removes their cached D-Bus objects. Held observer fds cannot keep
    /// a removed controller available. No business/directory lock crosses I/O.
    async fn list_adapters(&self) -> zbus::fdo::Result<Vec<String>> {
        let registrations = self.adapters.lock().await.clone();
        tokio::task::spawn_blocking(move || {
            let mut paths = Vec::new();
            for (path, registration) in registrations {
                match registration
                    .adapter
                    .controller_snapshot(registration.generation)
                {
                    Ok(_) => paths.push(path),
                    Err(slk_native::Error::Ioctl(nix::errno::Errno::ENODEV)) => {}
                    Err(error) => {
                        return Err(zbus::fdo::Error::Failed(format!(
                            "registration snapshot failed for {path}: {error}"
                        )));
                    }
                }
            }
            Ok(paths)
        })
        .await
        .map_err(|error| {
            zbus::fdo::Error::Failed(format!("registration snapshot worker failed: {error}"))
        })?
    }
}

/// Adapter D-Bus object at /org/sparklink/slk0
pub struct AdapterIface {
    state: SharedState,
}

impl AdapterIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.Adapter")]
impl AdapterIface {
    /// Manager operation on the physical scanner, not an application scan lease.
    async fn start_controller_scan(&self) -> zbus::fdo::Result<()> {
        if self.state.lock().await.controller.profile == 1 {
            let id = crate::radio::random_id().await?;
            crate::radio::scan(&self.state, id).await?;
            return crate::radio::wait(&self.state, id).await;
        }
        let mut st = self.state.lock().await;
        st.start_scan()
            .map_err(|e| zbus::fdo::Error::Failed(format!("scan start failed: {e}")))
    }

    /// Manager stop of the physical scanner; not a client session release.
    async fn stop_controller_scan(&self) -> zbus::fdo::Result<()> {
        if self.state.lock().await.controller.profile == 1 {
            let id = crate::radio::random_id().await?;
            crate::radio::stop(&self.state, id, slk_protocol::DISCOVERY_SCAN_STOP).await?;
            return crate::radio::wait(&self.state, id).await;
        }
        let mut st = self.state.lock().await;
        st.stop_scan()
            .map_err(|e| zbus::fdo::Error::Failed(format!("scan stop failed: {e}")))
    }

    /// Typed nonconnectable policy; successful return is admission.
    async fn submit_advertising(
        &self,
        request_id: u64,
        marker: Vec<u8>,
    ) -> zbus::fdo::Result<Vec<u8>> {
        crate::radio::advertise(&self.state, request_id, marker, None).await
    }

    /// Explicit fixed or negotiable T announcement; no link success inferred.
    async fn submit_connectable_advertising(
        &self,
        request_id: u64,
        marker: Vec<u8>,
        negotiable: bool,
    ) -> zbus::fdo::Result<Vec<u8>> {
        let role = if negotiable {
            slk_native::Ws73ConnectableRole::NegotiableTerminal
        } else {
            slk_native::Ws73ConnectableRole::FixedTerminal
        };
        crate::radio::advertise(&self.state, request_id, marker, Some(role)).await
    }
    async fn submit_scanning(&self, request_id: u64) -> zbus::fdo::Result<()> {
        crate::radio::scan(&self.state, request_id).await
    }
    async fn submit_stop_advertising(&self, request_id: u64) -> zbus::fdo::Result<()> {
        crate::radio::stop(&self.state, request_id, slk_protocol::DISCOVERY_ADV_STOP).await
    }
    async fn submit_stop_scanning(&self, request_id: u64) -> zbus::fdo::Result<()> {
        crate::radio::stop(&self.state, request_id, slk_protocol::DISCOVERY_SCAN_STOP).await
    }
    /// Bounded per-device policy revocation/drain and Managed reacquisition.
    async fn cancel_discovery_policies(&self) -> zbus::fdo::Result<u64> {
        crate::radio::cancel_policies(&self.state).await
    }
    /// Actual non-destructive kernel state; never expose the owning credential.
    async fn get_management_status(&self) -> zbus::fdo::Result<crate::radio::ManagementRecord> {
        crate::radio::management(&self.state).await
    }
    async fn get_discovery_result(
        &self,
        request_id: u64,
    ) -> zbus::fdo::Result<slk_protocol::DiscoveryResultRecord> {
        crate::radio::result(&self.state, request_id).await
    }
    /// Read-only actual op5/6 provenance for an untouched business domain.
    async fn get_initialization_off(
        &self,
        operation: u32,
    ) -> zbus::fdo::Result<slk_protocol::DiscoveryResultRecord> {
        crate::radio::initialization_off(&self.state, operation).await
    }
    /// Matched final Complete receipt; never substitute daemon observation time.
    async fn get_discovery_timing(
        &self,
        request_id: u64,
    ) -> zbus::fdo::Result<(u64, u64, u64, u32, u32, u16, u8)> {
        crate::radio::timing(&self.state, request_id).await
    }
    #[zbus(property)]
    fn radio_policy_version(&self) -> u32 {
        slk_native::WS73_DISCOVERY_POLICY_VERSION
    }
    /// Immutable registration policy. Admission/Complete/RF are observed separately.
    async fn get_discovery_policy(&self) -> zbus::fdo::Result<(u32, u32, u32, i32, u32, u32)> {
        crate::radio::discovery_policy(&self.state).await
    }
    #[zbus(property)]
    async fn advertising_state(&self) -> u32 {
        self.state.lock().await.radio_advertising
    }
    #[zbus(property)]
    async fn scanning_state(&self) -> u32 {
        self.state.lock().await.radio_scanning
    }

    /// Allocate an ID before admission so clients can recover a lost reply.
    async fn allocate_connection_request(&self) -> zbus::fdo::Result<u64> {
        crate::connection::allocate(&self.state).await
    }
    async fn submit_connect(
        &self,
        request_id: u64,
        address: &str,
        address_type: u8,
    ) -> zbus::fdo::Result<()> {
        let address =
            parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        crate::connection::submit(&self.state, request_id, address, address_type, None).await
    }
    async fn submit_disconnect(&self, request_id: u64, address: &str) -> zbus::fdo::Result<()> {
        let address =
            parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        crate::connection::submit_disconnect(&self.state, request_id, address).await
    }
    async fn submit_disconnect_typed(
        &self,
        request_id: u64,
        address: &str,
        address_type: u8,
    ) -> zbus::fdo::Result<()> {
        let address =
            parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        crate::connection::submit_disconnect_typed(
            &self.state,
            request_id,
            address,
            Some(address_type),
        )
        .await
    }
    async fn get_connection_result(
        &self,
        request_id: u64,
    ) -> zbus::fdo::Result<crate::connection::Record> {
        crate::connection::result(&self.state, request_id).await
    }
    async fn submit_disconnect_reference(
        &self,
        request_id: u64,
        address: &str,
        address_type: u8,
        handle: u16,
        lifetime: u64,
        role: u8,
    ) -> zbus::fdo::Result<()> {
        let address =
            parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        let reference = slk_protocol::SleLinkInfo {
            lifetime,
            handle,
            role,
            address_type,
            address,
            reserved: [0; 6],
        };
        crate::connection::submit(
            &self.state,
            request_id,
            address,
            address_type,
            Some(reference),
        )
        .await
    }
    /// Check flags/error before treating an empty vector as an empty table.
    async fn get_native_connections(&self) -> zbus::fdo::Result<crate::connection::SnapshotRecord> {
        let table = crate::connection::snapshot(&self.state).await?;
        let links = table.links[..table.count as usize]
            .iter()
            .map(|link| {
                (
                    link.lifetime,
                    link.handle,
                    link.role,
                    link.address_type,
                    format_addr(&link.address),
                )
            })
            .collect();
        Ok((
            table.generation,
            table.event_seq,
            table.revision,
            table.flags,
            table.error,
            links,
        ))
    }
    /// Typed physical objects published from the current daemon observation.
    async fn get_native_connection_objects(
        &self,
    ) -> zbus::fdo::Result<crate::connection_object::Objects> {
        let st = self.state.lock().await;
        if st.controller.profile != 1 {
            return Err(zbus::fdo::Error::NotSupported(
                "typed physical objects require Native".into(),
            ));
        }
        let objects = st
            .native_connection_objects
            .values()
            .filter(|entry| {
                entry.published
                    && st
                        .native_peer_objects
                        .get(&(entry.reference.address_type, entry.reference.address))
                        .is_some_and(|peer| peer.published)
            })
            .map(|entry| {
                let link = entry.reference;
                (
                    entry.path.clone(),
                    link.lifetime,
                    link.handle,
                    link.role,
                    link.address_type,
                    format_addr(&link.address),
                )
            })
            .collect();
        Ok((
            st.controller.generation,
            st.native_link_barrier,
            st.native_link_revision,
            st.native_links_known(),
            objects,
        ))
    }
    async fn connect_device_typed(&self, address: &str, address_type: u8) -> zbus::fdo::Result<()> {
        let id = crate::connection::allocate(&self.state).await?;
        self.submit_connect(id, address, address_type).await?;
        crate::connection::wait(&self.state, id).await
    }
    async fn disconnect_address(&self, address: &str) -> zbus::fdo::Result<()> {
        let address =
            parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        if self.state.lock().await.controller.profile == 1 {
            let id = crate::connection::disconnect_address(&self.state, address).await?;
            return crate::connection::wait(&self.state, id).await;
        }
        let mut s = self.state.lock().await;
        let h = s
            .devices
            .get(&address)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| zbus::fdo::Error::Failed("not connected".into()))?;
        s.disconnect_device(h)
            .map_err(|e| zbus::fdo::Error::Failed(e.to_string()))
    }

    /// Connect to a device by address string "AA:BB:CC:DD:EE:FF"
    async fn connect_device(&self, address: &str) -> zbus::fdo::Result<()> {
        let addr = parse_addr(address).map_err(|e| zbus::fdo::Error::InvalidArgs(e.to_string()))?;
        let mut st = self.state.lock().await;
        if st.controller.profile == 1 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "WS73 needs an explicit peer address type; use ConnectDeviceTyped".into(),
            ));
        }
        st.connect_device(&addr)
            .map_err(|e| zbus::fdo::Error::Failed(format!("connect failed: {e}")))
    }

    /// Disconnect a device by connection handle
    async fn disconnect_device(&self, handle: u16) -> zbus::fdo::Result<()> {
        if self.state.lock().await.controller.profile == 1 {
            return Err(zbus::fdo::Error::NotSupported(
                "native disconnect requires a peer and physical lifetime, not a bare handle".into(),
            ));
        }
        let mut st = self.state.lock().await;
        st.disconnect_device(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("disconnect failed: {e}")))
    }

    /// List discovered devices as (addr_hex, name, rssi, connected) tuples
    async fn get_devices(&self) -> Vec<(String, String, i16, bool)> {
        let st = self.state.lock().await;
        st.devices
            .values()
            .filter(|d| d.publication == crate::state::DevicePublication::Published)
            .map(|d| {
                let addr_hex = d
                    .addr
                    .iter()
                    .map(|b| format!("{b:02X}"))
                    .collect::<Vec<_>>()
                    .join(":");
                (
                    addr_hex,
                    d.name.clone(),
                    d.rssi as i16,
                    st.device_connection(&d.addr).1,
                )
            })
            .collect()
    }

    /// Exact received WS73 reports: sequence, generation, timestamp_ms,
    /// address, RSSI, complete header, data and explicit lost-record count.
    async fn get_reports(&self) -> Vec<(u64, u64, u64, String, i16, Vec<u8>, Vec<u8>, u64)> {
        self.state
            .lock()
            .await
            .native_reports
            .iter()
            .map(|r| {
                (
                    r.sequence,
                    r.generation,
                    r.received_at_ms,
                    format_addr(&r.address),
                    i16::from(r.rssi),
                    r.header.clone(),
                    r.data.clone(),
                    r.lost,
                )
            })
            .collect()
    }

    /// Versioned extension preserves the kernel CLOCK_BOOTTIME receipt time.
    async fn get_timed_reports(&self) -> Vec<slk_protocol::TimedDiscoveryReportRecord> {
        self.state
            .lock()
            .await
            .native_reports
            .iter()
            .map(|r| {
                (
                    r.sequence,
                    r.generation,
                    r.kernel_boottime_ns,
                    r.received_at_ms,
                    format_addr(&r.address),
                    i16::from(r.rssi),
                    r.header.clone(),
                    r.data.clone(),
                    r.lost,
                )
            })
            .collect()
    }

    #[zbus(property)]
    async fn ready(&self) -> bool {
        let st = self.state.lock().await;
        st.present && st.controller.flags == slk_protocol::CONTROLLER_READY
    }
    #[zbus(property)]
    async fn controller_state(&self) -> String {
        let st = self.state.lock().await;
        if !st.present {
            "Removed"
        } else {
            match st.controller.flags {
                slk_protocol::CONTROLLER_READY => "Ready",
                slk_protocol::CONTROLLER_FAULT => "Fault",
                _ => "Setup",
            }
        }
        .into()
    }
    #[zbus(property)]
    async fn generation(&self) -> u64 {
        self.state.lock().await.controller.generation
    }
    #[zbus(property)]
    async fn profile(&self) -> u32 {
        self.state.lock().await.controller.profile
    }
    #[zbus(property)]
    async fn address(&self) -> String {
        format_addr(&self.state.lock().await.controller.address)
    }
    #[zbus(property)]
    async fn controller_version(&self) -> Vec<u8> {
        self.state.lock().await.controller.version_tuple.to_vec()
    }
    #[zbus(property)]
    async fn features(&self) -> Vec<u8> {
        self.state.lock().await.controller.features.to_vec()
    }
    #[zbus(property)]
    async fn metadata_valid_fields(&self) -> u32 {
        self.state.lock().await.controller.valid_fields
    }
    #[zbus(property)]
    async fn command_credits(&self) -> u8 {
        self.state.lock().await.controller.command_credits
    }
    #[zbus(property)]
    async fn controller_error(&self) -> i32 {
        self.state.lock().await.controller.error
    }
    #[zbus(property)]
    async fn initialization_error(&self) -> String {
        self.state.lock().await.initialization_error.clone()
    }
    #[zbus(property)]
    async fn events_lost(&self) -> u64 {
        self.state.lock().await.events_lost
    }
    /// Daemon observation position; Known is false after any failed refresh.
    #[zbus(property)]
    async fn native_link_observation(&self) -> (u64, u64, bool) {
        let st = self.state.lock().await;
        (
            st.native_link_barrier,
            st.native_link_revision,
            st.native_links_known(),
        )
    }

    /// Bounded address-only discovery observations, not Runtime/Peer truth.
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_count(&self) -> u32 {
        self.state.lock().await.devices.len() as u32
    }
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_bytes(&self) -> u32 {
        self.state.lock().await.observation_bytes() as u32
    }
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_drops(&self) -> u64 {
        self.state.lock().await.observation_drops
    }
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_publication_errors(&self) -> u64 {
        self.state.lock().await.observation_publication_errors
    }
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_retirement_errors(&self) -> u64 {
        self.state.lock().await.observation_retirement_errors
    }

    /// Whether discovery is active
    #[zbus(property)]
    async fn discovering(&self) -> bool {
        let st = self.state.lock().await;
        if st.controller.profile == 1 {
            st.radio_scanning == slk_protocol::DISCOVERY_RADIO_ON
        } else {
            st.discovering
        }
    }

    /// Adapter name
    #[zbus(property)]
    async fn name(&self) -> String {
        self.state.lock().await.name.clone()
    }
}

/// D-Bus object representing a discovered device
pub struct DeviceIface {
    state: SharedState,
    addr: slk_protocol::SleAddr,
}

impl DeviceIface {
    pub fn new(state: SharedState, addr: slk_protocol::SleAddr) -> Self {
        Self { state, addr }
    }
    pub(crate) fn belongs_to(&self, state: &SharedState, address: slk_protocol::SleAddr) -> bool {
        self.addr == address && std::sync::Arc::ptr_eq(&self.state, state)
    }
}

#[interface(name = "org.sparklink.Device")]
impl DeviceIface {
    /// Connect to this device
    async fn connect(&self) -> zbus::fdo::Result<()> {
        let mut st = self.state.lock().await;
        if st.controller.profile == 1 {
            return Err(zbus::fdo::Error::InvalidArgs(
                "use adapter ConnectDeviceTyped with explicit address type".into(),
            ));
        }
        st.connect_device(&self.addr)
            .map_err(|e| zbus::fdo::Error::Failed(format!("connect failed: {e}")))
    }

    /// Disconnect from this device
    async fn disconnect(&self) -> zbus::fdo::Result<()> {
        if self.state.lock().await.controller.profile == 1 {
            let id = crate::connection::disconnect_address(&self.state, self.addr).await?;
            return crate::connection::wait(&self.state, id).await;
        }
        let mut st = self.state.lock().await;
        let handle = st
            .devices
            .get(&self.addr)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| zbus::fdo::Error::Failed("not connected".into()))?;
        st.disconnect_device(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("disconnect failed: {e}")))
    }

    /// Validity of advertisement observations only; never connection/security.
    #[zbus(property(emits_changed_signal = "false"))]
    async fn observation_valid(&self) -> bool {
        let state = self.state.lock().await;
        state.present
            && state
                .devices
                .get(&self.addr)
                .is_some_and(|d| d.observation_valid())
    }

    /// Device MAC address "AA:BB:CC:DD:EE:FF"
    #[zbus(property)]
    async fn address(&self) -> String {
        format_addr(&self.addr)
    }

    /// Device name from advertisement
    #[zbus(property)]
    async fn name(&self) -> String {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.name.clone())
            .unwrap_or_default()
    }

    /// Last seen RSSI
    #[zbus(property)]
    async fn rssi(&self) -> i16 {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.rssi as i16)
            .unwrap_or(0)
    }

    #[zbus(property)]
    async fn connection_known(&self) -> bool {
        self.state.lock().await.device_connection(&self.addr).0
    }

    #[zbus(property)]
    async fn rssi_known(&self) -> bool {
        self.state
            .lock()
            .await
            .devices
            .get(&self.addr)
            .is_some_and(|d| d.rssi_known)
    }

    /// Whether the device is currently connected
    #[zbus(property)]
    async fn connected(&self) -> bool {
        self.state.lock().await.device_connection(&self.addr).1
    }

    /// Discovery level from advertisement
    #[zbus(property)]
    async fn discovery_level(&self) -> u8 {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.discovery_level)
            .unwrap_or(0)
    }

    /// Raw advertisement data bytes
    async fn get_adv_data(&self) -> Vec<u8> {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.adv_data.clone())
            .unwrap_or_default()
    }

    /// Parsed 16-bit service UUIDs from advertisement TLV data
    #[zbus(property)]
    async fn service_uuids(&self) -> Vec<u16> {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .map(|d| d.service_uuids.clone())
            .unwrap_or_default()
    }

    /// TX power level from advertisement (dBm), -128 if absent
    #[zbus(property)]
    async fn tx_power(&self) -> i16 {
        let st = self.state.lock().await;
        st.devices
            .get(&self.addr)
            .and_then(|d| d.tx_power)
            .map(|p| p as i16)
            .unwrap_or(-128)
    }

    /// Query connection info as a property dict.
    ///
    /// Returns key-value pairs: handle, state, data_mtu, data_mps,
    /// data_mode, smtc_tx_credits,
    /// smtc_rx_credits, dudtc_tx_credits, dudtc_rx_credits,
    /// tx_bytes, rx_bytes.
    async fn get_connection_info(&self) -> zbus::fdo::Result<HashMap<String, Value<'static>>> {
        let st = self.state.lock().await;
        if st.controller.profile != 0 {
            return Err(zbus::fdo::Error::NotSupported("native connection parameters require a typed current lifetime; legacy conn_info is unsupported".into()));
        }
        let handle = st
            .devices
            .get(&self.addr)
            .and_then(|d| d.conn_handle)
            .ok_or_else(|| zbus::fdo::Error::Failed("not connected".into()))?;
        let info = st
            .conn_info(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("conn_info failed: {e}")))?;
        let mut m = HashMap::new();
        m.insert("handle".into(), Value::from(info.handle));
        m.insert("state".into(), Value::from(info.state));
        m.insert("data_mtu".into(), Value::from(info.data_mtu));
        m.insert("data_mps".into(), Value::from(info.data_mps));
        m.insert("data_mode".into(), Value::from(info.data_mode));
        m.insert("svc_mtu".into(), Value::from(info.svc_mtu));
        m.insert("smtc_tx_credits".into(), Value::from(info.smtc_tx_credits));
        m.insert("smtc_rx_credits".into(), Value::from(info.smtc_rx_credits));
        m.insert(
            "dudtc_tx_credits".into(),
            Value::from(info.dudtc_tx_credits),
        );
        m.insert(
            "dudtc_rx_credits".into(),
            Value::from(info.dudtc_rx_credits),
        );
        m.insert("tx_bytes".into(), Value::from(info.tx_bytes));
        m.insert("rx_bytes".into(), Value::from(info.rx_bytes));
        m.insert("bandwidth_mhz".into(), Value::from(info.bandwidth_mhz));
        m.insert("mcs_index".into(), Value::from(info.mcs_index));
        m.insert(
            "supervision_timeout".into(),
            Value::from(info.supervision_timeout),
        );
        Ok(m)
    }
}

fn parse_addr(s: &str) -> Result<slk_protocol::SleAddr, &'static str> {
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 6 {
        return Err("address must be AA:BB:CC:DD:EE:FF");
    }
    let mut addr = [0u8; 6];
    for (i, part) in parts.iter().enumerate() {
        addr[i] = u8::from_str_radix(part, 16).map_err(|_| "invalid hex byte")?;
    }
    Ok(addr)
}

pub(crate) fn format_addr(addr: &slk_protocol::SleAddr) -> String {
    format!(
        "{:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X}",
        addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]
    )
}
