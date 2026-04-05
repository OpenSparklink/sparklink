use zbus::interface;

use crate::state::SharedState;

/// D-Bus interface for controller-level operations:
/// PHY, power management, AFH, DLI, measurement, statistics, sync link
pub struct ControllerIface {
    state: SharedState,
}

impl ControllerIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.Controller")]
impl ControllerIface {
    // ----- Role -----

    /// Get the current device role (0 = G-node, 1 = T-node)
    async fn get_role(&self) -> zbus::fdo::Result<u8> {
        let st = self.state.lock().await;
        st.adapter.get_role().map_err(map_err)
    }

    /// Set the device role
    async fn set_role(&self, role: u8) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.set_role(role).map_err(map_err)
    }

    // ----- Subsystem Stats -----

    /// Get subsystem statistics
    async fn get_stats(&self) -> zbus::fdo::Result<SubsysStats> {
        let st = self.state.lock().await;
        let s = st.adapter.subsys_stats().map_err(map_err)?;
        Ok(SubsysStats {
            dev_count: s.dev_count,
            active_connections: s.active_connections,
            total_conn_created: s.total_conn_created,
            total_mgmt_submitted: s.total_mgmt_submitted,
            total_mgmt_timeouts: s.total_mgmt_timeouts,
            crc_errors: s.crc_errors,
            power_state: s.power_state,
        })
    }

    /// Get event queue statistics
    async fn get_event_stats(&self) -> zbus::fdo::Result<EventStats> {
        let st = self.state.lock().await;
        let s = st.adapter.event_stats().map_err(map_err)?;
        Ok(EventStats {
            pending: s.pending,
            total_enqueued: s.total_enqueued,
            total_dropped: s.total_dropped,
            total_delivered: s.total_delivered,
        })
    }

    /// Get pending event count
    async fn event_count(&self) -> zbus::fdo::Result<i32> {
        let st = self.state.lock().await;
        st.adapter.event_count().map_err(map_err)
    }

    // ----- PHY -----

    /// Get PHY info
    async fn get_phy_info(&self) -> zbus::fdo::Result<PhyInfo> {
        let st = self.state.lock().await;
        let p = st.adapter.phy_info().map_err(map_err)?;
        Ok(PhyInfo {
            mcs_index: p.mcs_index,
            bandwidth_mhz: p.bandwidth_mhz,
            tx_power_dbm: p.tx_power_dbm,
            data_rate_kbps: p.data_rate_kbps,
            hop_channel: p.hop_channel,
            modulation: p.modulation,
        })
    }

    /// Set MCS index
    async fn set_mcs(&self, mcs_index: u8) -> zbus::fdo::Result<()> {
        let cmd = slk_protocol::SlePhyMcsCmd {
            mcs_index,
            _reserved: [0; 3],
        };
        let st = self.state.lock().await;
        st.adapter.phy_set_mcs(&cmd).map_err(map_err)
    }

    /// Set TX power in dBm
    async fn set_tx_power(&self, dbm: i8) -> zbus::fdo::Result<()> {
        let cmd = slk_protocol::SlePhyTxPowerCmd {
            tx_power_dbm: dbm,
            _reserved: [0; 3],
        };
        let st = self.state.lock().await;
        st.adapter.phy_set_txpower(&cmd).map_err(map_err)
    }

    /// Set PHY bandwidth in MHz
    async fn set_bandwidth(&self, bw_mhz: u8) -> zbus::fdo::Result<()> {
        let cmd = slk_protocol::SlePhyBwCmd {
            bandwidth_mhz: bw_mhz,
            _reserved: [0; 3],
        };
        let st = self.state.lock().await;
        st.adapter.phy_set_bw(&cmd).map_err(map_err)
    }

    /// Select optimal MCS for given SINR and bandwidth
    async fn mcs_select(
        &self,
        sinr_db_x10: i16,
        bandwidth_mhz: u8,
        min_kbps: u32,
    ) -> zbus::fdo::Result<McsSelectResult> {
        let mut params = slk_protocol::SlePhyMcsSelect {
            min_kbps,
            effective_kbps: 0,
            sinr_db_x10,
            bandwidth_mhz,
            selected_mcs: 0,
        };
        let st = self.state.lock().await;
        st.adapter.phy_mcs_select(&mut params).map_err(map_err)?;
        Ok(McsSelectResult {
            selected_mcs: params.selected_mcs,
            effective_kbps: params.effective_kbps,
        })
    }

    /// Get next hopping channel
    async fn phy_hop_next(&self) -> zbus::fdo::Result<HopInfo> {
        let st = self.state.lock().await;
        let h = st.adapter.phy_hop_next().map_err(map_err)?;
        Ok(HopInfo {
            channel: h.channel,
            freq_mhz: h.freq_mhz,
            event_counter: h.event_counter,
        })
    }

    // ----- Power Management -----

    /// Get power management info
    async fn get_pm_info(&self) -> zbus::fdo::Result<PmInfo> {
        let st = self.state.lock().await;
        let p = st.adapter.pm_info().map_err(map_err)?;
        Ok(PmInfo {
            state: p.state,
            force_active: p.force_active != 0,
            current_interval: p.current_interval,
            transitions: p.transitions,
        })
    }

    /// Set target power state (0=Active, 1=Sniff, 2=Idle, 3=Suspended)
    async fn pm_set_state(&self, target: u8) -> zbus::fdo::Result<()> {
        let cmd = slk_protocol::SlePmStateCmd {
            target_state: target,
            _reserved: [0; 3],
        };
        let st = self.state.lock().await;
        st.adapter.pm_set_state(&cmd).map_err(map_err)
    }

    /// Force active power state
    async fn pm_force_active(&self, enable: bool) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.pm_force_active(enable).map_err(map_err)
    }

    // ----- AFH -----

    /// Set AFH channel map for a connection
    async fn afh_set_map(&self, handle: u16, map: Vec<u8>) -> zbus::fdo::Result<()> {
        let mut params: slk_protocol::SleAfhMapParams = unsafe { std::mem::zeroed() };
        params.handle = handle;
        let len = map.len().min(10);
        params.map[..len].copy_from_slice(&map[..len]);
        let st = self.state.lock().await;
        st.adapter.afh_set_map(&params).map_err(map_err)
    }

    /// Get the current AFH channel map
    async fn afh_get_map(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let st = self.state.lock().await;
        let params = st.adapter.afh_get_map(handle).map_err(map_err)?;
        Ok(params.map.to_vec())
    }

    /// Get next AFH hopping channel
    async fn afh_hop_next(&self, handle: u16) -> zbus::fdo::Result<HopInfo> {
        let st = self.state.lock().await;
        let h = st.adapter.afh_hop_next(handle).map_err(map_err)?;
        Ok(HopInfo {
            channel: h.channel,
            freq_mhz: h.freq_mhz,
            event_counter: h.event_counter,
        })
    }

    // ----- Connection Capability -----

    /// Read peer features for a connection
    async fn conn_read_peer_features(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let st = self.state.lock().await;
        let cap = st.adapter.conn_read_peer_features(handle).map_err(map_err)?;
        Ok(cap.features.to_vec())
    }

    /// Update connection parameters
    async fn conn_update_params(
        &self,
        handle: u16,
        interval_min: u16,
        interval_max: u16,
        latency: u16,
        supervision_timeout: u16,
    ) -> zbus::fdo::Result<()> {
        let params = slk_protocol::SleConnParamUpdate {
            handle,
            interval_min,
            interval_max,
            latency,
            supervision_timeout,
            _reserved: [0; 2],
        };
        let st = self.state.lock().await;
        st.adapter.conn_update_params(&params).map_err(map_err)
    }

    /// Update connection PHY
    async fn conn_phy_update(
        &self,
        handle: u16,
        mcs_index: u8,
        bandwidth_mhz: u8,
    ) -> zbus::fdo::Result<()> {
        let params = slk_protocol::SleConnPhyUpdate {
            handle,
            mcs_index,
            bandwidth_mhz,
        };
        let st = self.state.lock().await;
        st.adapter.conn_phy_update(&params).map_err(map_err)
    }

    // ----- DLI -----

    /// Get DLI controller info
    async fn get_dli_info(&self) -> zbus::fdo::Result<DliInfo> {
        let st = self.state.lock().await;
        let d = st.adapter.dli_info().map_err(map_err)?;
        let name_end = d.name.iter().position(|&b| b == 0).unwrap_or(d.name.len());
        Ok(DliInfo {
            bus: d.bus,
            firmware_version: d.firmware_version,
            max_connections: d.max_connections,
            max_adv_sets: d.max_adv_sets,
            max_mtu: d.max_mtu,
            name: String::from_utf8_lossy(&d.name[..name_end]).into_owned(),
        })
    }

    /// Reset the DLI controller
    async fn dli_reset(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.dli_reset().map_err(map_err)
    }

    /// Get management queue statistics
    async fn get_mgmt_stats(&self) -> zbus::fdo::Result<MgmtStats> {
        let st = self.state.lock().await;
        let s = st.adapter.mgmt_stats().map_err(map_err)?;
        Ok(MgmtStats {
            pending: s.pending,
            total_submitted: s.total_submitted,
            total_resolved: s.total_resolved,
            total_timeouts: s.total_timeouts,
        })
    }

    // ----- RAL / RPA -----

    /// Clear all RAL entries
    async fn ral_clear(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.ral_clear().map_err(map_err)
    }

    /// Get current RAL size
    async fn ral_size(&self) -> zbus::fdo::Result<u8> {
        let st = self.state.lock().await;
        st.adapter.ral_size().map_err(map_err)
    }

    /// Enable or disable RPA resolution
    async fn rpa_enable(&self, enable: bool) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.rpa_enable(enable).map_err(map_err)
    }

    /// Set RPA refresh timeout in seconds
    async fn rpa_set_timeout(&self, timeout_secs: u16) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.rpa_set_timeout(timeout_secs).map_err(map_err)
    }

    // ----- Measurement -----

    /// Read measurement capability
    async fn meas_read_cap(&self) -> zbus::fdo::Result<MeasCap> {
        let st = self.state.lock().await;
        let c = st.adapter.meas_read_cap().map_err(map_err)?;
        Ok(MeasCap {
            meas_types: c.meas_types,
            max_instances: c.max_instances,
            antenna_count: c.antenna_count,
        })
    }

    /// Enable or disable measurement
    async fn meas_enable(&self, enable: bool) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.meas_enable(enable).map_err(map_err)
    }

    // ----- Sync Link -----

    /// Remove a unicast sync group
    async fn sync_ucast_remove(&self, cig_id: u8) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.sync_ucast_remove(cig_id).map_err(map_err)
    }

    /// Remove a multicast sync group
    async fn sync_mcast_remove(&self, big_id: u8) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter.sync_mcast_remove(big_id).map_err(map_err)
    }

    /// Get sync link info
    async fn sync_info(&self, sync_handle: u16) -> zbus::fdo::Result<SyncLinkInfo> {
        let st = self.state.lock().await;
        let s = st.adapter.sync_info(sync_handle).map_err(map_err)?;
        Ok(SyncLinkInfo {
            sync_handle: s.sync_handle,
            acl_handle: s.acl_handle,
            group_id: s.group_id,
            stream_id: s.stream_id,
            link_type: s.link_type,
            state: s.state,
        })
    }

    /// Get active connection count
    async fn conn_count(&self) -> zbus::fdo::Result<i32> {
        let st = self.state.lock().await;
        st.adapter.conn_count().map_err(map_err)
    }

    /// Get USB DLI device count
    async fn usb_dev_count(&self) -> zbus::fdo::Result<i32> {
        let st = self.state.lock().await;
        st.adapter.usb_dev_count().map_err(map_err)
    }
}

fn map_err(e: libsparklink::Error) -> zbus::fdo::Error {
    zbus::fdo::Error::Failed(e.to_string())
}

// ----- D-Bus return types -----

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct SubsysStats {
    pub dev_count: u16,
    pub active_connections: u16,
    pub total_conn_created: u32,
    pub total_mgmt_submitted: u32,
    pub total_mgmt_timeouts: u32,
    pub crc_errors: u32,
    pub power_state: u8,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct EventStats {
    pub pending: u32,
    pub total_enqueued: u64,
    pub total_dropped: u64,
    pub total_delivered: u64,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct PhyInfo {
    pub mcs_index: u8,
    pub bandwidth_mhz: u8,
    pub tx_power_dbm: i8,
    pub data_rate_kbps: u32,
    pub hop_channel: u8,
    pub modulation: u8,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct McsSelectResult {
    pub selected_mcs: u8,
    pub effective_kbps: u32,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct HopInfo {
    pub channel: u8,
    pub freq_mhz: u16,
    pub event_counter: u16,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct PmInfo {
    pub state: u8,
    pub force_active: bool,
    pub current_interval: u16,
    pub transitions: u32,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct DliInfo {
    pub bus: u8,
    pub firmware_version: u32,
    pub max_connections: u8,
    pub max_adv_sets: u8,
    pub max_mtu: u16,
    pub name: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct MgmtStats {
    pub pending: u16,
    pub total_submitted: u32,
    pub total_resolved: u32,
    pub total_timeouts: u32,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct MeasCap {
    pub meas_types: u8,
    pub max_instances: u8,
    pub antenna_count: u8,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct SyncLinkInfo {
    pub sync_handle: u16,
    pub acl_handle: u16,
    pub group_id: u8,
    pub stream_id: u8,
    pub link_type: u8,
    pub state: u8,
}
