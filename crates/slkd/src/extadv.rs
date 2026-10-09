use zbus::interface;

use crate::state::SharedState;

/// D-Bus interface for extended advertising management
pub struct ExtAdvIface {
    state: SharedState,
}

impl ExtAdvIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.ExtAdv")]
impl ExtAdvIface {
    /// Configure an extended advertising set
    async fn configure(
        &self,
        handle: u8,
        discovery_level: u8,
        sid: u8,
        primary_phy: u8,
        secondary_phy: u8,
        tx_power_dbm: i8,
        interval_ms: u16,
    ) -> zbus::fdo::Result<()> {
        let config = slk_protocol::SleExtAdvConfig {
            handle,
            discovery_level,
            sid,
            broadcast_type: 0,
            primary_phy,
            secondary_phy,
            tx_power_dbm,
            include_tx_power: 1,
            interval_ms,
            ext_adv_timing: 0,
            _reserved: [0; 5],
        };
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_configure(&config)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_configure: {e}")))
    }

    /// Set advertising data for an extended advertising set
    async fn set_data(&self, handle: u8, data: Vec<u8>) -> zbus::fdo::Result<()> {
        let len = data.len().min(252);
        let mut adv_data = slk_protocol::SleExtAdvData {
            handle,
            _pad: 0,
            data_len: len as u16,
            data: [0; 252],
        };
        adv_data.data[..len].copy_from_slice(&data[..len]);
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_set_data(&adv_data)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_set_data: {e}")))
    }

    /// Set scan response data for an extended advertising set
    async fn set_scan_response(&self, handle: u8, data: Vec<u8>) -> zbus::fdo::Result<()> {
        let len = data.len().min(252);
        let mut adv_data = slk_protocol::SleExtAdvData {
            handle,
            _pad: 0,
            data_len: len as u16,
            data: [0; 252],
        };
        adv_data.data[..len].copy_from_slice(&data[..len]);
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_set_scan_rsp(&adv_data)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_set_scan_rsp: {e}")))
    }

    /// Enable an extended advertising set
    async fn enable(&self, handle: u8) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_enable(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_enable: {e}")))
    }

    /// Disable an extended advertising set
    async fn disable(&self, handle: u8) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_disable(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_disable: {e}")))
    }

    /// Remove an extended advertising set
    async fn remove(&self, handle: u8) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_remove(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_remove: {e}")))
    }

    /// Get extended advertising set info
    async fn get_info(&self, handle: u8) -> zbus::fdo::Result<ExtAdvInfo> {
        let st = self.state.lock().await;
        let info = st
            .adapter
            .ext_adv_info(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_info: {e}")))?;
        Ok(ExtAdvInfo {
            handle: info.handle,
            state: info.state,
            sid: info.sid,
            primary_phy: info.primary_phy,
            data_len: info.data_len,
            tx_count: info.tx_count,
            events_sent: info.events_sent,
        })
    }

    /// Enable with duration and max events
    async fn enable_ex(
        &self,
        handle: u8,
        max_adv_events: u8,
        duration_10ms: u16,
    ) -> zbus::fdo::Result<()> {
        let params = slk_protocol::SleExtAdvEnableParams {
            handle,
            max_adv_events,
            duration_10ms,
            _reserved: [0; 4],
        };
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_enable_ex(&params)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_enable_ex: {e}")))
    }

    /// Advance the ext adv tick timer
    async fn tick(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ext_adv_tick()
            .map_err(|e| zbus::fdo::Error::Failed(format!("ext_adv_tick: {e}")))
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct ExtAdvInfo {
    pub handle: u8,
    pub state: u8,
    pub sid: u8,
    pub primary_phy: u8,
    pub data_len: u16,
    pub tx_count: u64,
    pub events_sent: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ext_adv_info_fields() {
        let info = ExtAdvInfo {
            handle: 0,
            state: 1,
            sid: 2,
            primary_phy: 1,
            data_len: 31,
            tx_count: 500,
            events_sent: 100,
        };
        assert_eq!(info.handle, 0);
        assert_eq!(info.data_len, 31);
        assert_eq!(info.tx_count, 500);
    }
}
