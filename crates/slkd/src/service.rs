use zbus::interface;

use crate::state::SharedState;

/// D-Bus interface for SSAP service management at adapter level
pub struct SsapManagerIface {
    state: SharedState,
}

impl SsapManagerIface {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

#[interface(name = "org.sparklink.ServiceManager")]
impl SsapManagerIface {
    /// Get SSAP summary (service and property counts, MTU)
    async fn get_info(&self) -> zbus::fdo::Result<SsapInfo> {
        let st = self.state.lock().await;
        let summary = st
            .adapter
            .ssap_info()
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_info: {e}")))?;
        Ok(SsapInfo {
            service_count: summary.service_count,
            property_count: summary.property_count,
            total_entries: summary.total_entries,
            mtu: summary.mtu,
            notification_count: summary.notification_count,
        })
    }

    /// Register all configured services with the controller
    async fn register_services(&self) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ssap_register()
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_register: {e}")))
    }

    /// Add a service to the local database
    /// Returns the assigned start handle
    async fn add_service(&self, uuid16: u16, primary: bool) -> zbus::fdo::Result<u16> {
        let mut svc = slk_protocol::SsapAddService {
            uuid16,
            primary: primary as u8,
            _pad: 0,
            uuid128: [0; 16],
            start_handle: 0,
            _reserved: [0; 6],
        };
        let st = self.state.lock().await;
        st.adapter
            .ssap_add_svc(&mut svc)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_add_svc: {e}")))?;
        Ok(svc.start_handle)
    }

    /// Add a property (characteristic) to a service
    /// ops: bitmask of read(0x01)/write(0x02)/notify(0x04)/indicate(0x08)
    /// Returns the assigned handle
    async fn add_property(&self, uuid16: u16, ops: u8, value: Vec<u8>) -> zbus::fdo::Result<u16> {
        let len = value.len().min(248);
        let mut prop = slk_protocol::SsapAddProperty {
            uuid16,
            ops,
            value_len: len as u8,
            value: [0; 248],
            handle: 0,
            _reserved: [0; 2],
        };
        prop.value[..len].copy_from_slice(&value[..len]);
        let st = self.state.lock().await;
        st.adapter
            .ssap_add_prop(&mut prop)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_add_prop: {e}")))?;
        Ok(prop.handle)
    }

    /// Remove a service by its start handle
    async fn remove_service(&self, start_handle: u16) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ssap_remove_svc(start_handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_remove_svc: {e}")))
    }

    /// List local services
    async fn list_services(&self) -> zbus::fdo::Result<Vec<ServiceEntry>> {
        let st = self.state.lock().await;
        let list = st
            .adapter
            .ssap_find_svc()
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_find_svc: {e}")))?;
        let mut out = Vec::with_capacity(list.count as usize);
        for i in 0..list.count as usize {
            let s = &list.services[i];
            out.push(ServiceEntry {
                start_handle: s.start_handle,
                end_handle: s.end_handle,
                uuid16: s.uuid16,
                primary: s.primary != 0,
            });
        }
        Ok(out)
    }

    /// Read a local property value
    async fn read_property(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let st = self.state.lock().await;
        let rw = st
            .adapter
            .ssap_read(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_read: {e}")))?;
        Ok(rw.data[..rw.length as usize].to_vec())
    }

    /// Write a local property value
    async fn write_property(&self, handle: u16, value: Vec<u8>) -> zbus::fdo::Result<()> {
        let len = value.len().min(252);
        let mut rw = slk_protocol::SsapReadWrite {
            handle,
            length: len as u16,
            data: [0; 252],
        };
        rw.data[..len].copy_from_slice(&value[..len]);
        let st = self.state.lock().await;
        st.adapter
            .ssap_write(&rw)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_write: {e}")))
    }

    /// Send notification on a property handle
    async fn notify(&self, handle: u16) -> zbus::fdo::Result<()> {
        let st = self.state.lock().await;
        st.adapter
            .ssap_notify(handle)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_notify: {e}")))
    }

    /// Dequeue a pending notification
    async fn dequeue_notification(&self) -> zbus::fdo::Result<NotificationData> {
        let st = self.state.lock().await;
        let ntf = st
            .adapter
            .ssap_dequeue_ntf()
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_dequeue_ntf: {e}")))?;
        Ok(NotificationData {
            handle: ntf.handle,
            indication: ntf.indication != 0,
            data: ntf.data[..ntf.length as usize].to_vec(),
        })
    }
}

/// D-Bus interface for remote service operations on a specific connection
pub struct RemoteServiceIface {
    state: SharedState,
    conn_handle: u16,
}

impl RemoteServiceIface {
    pub fn new(state: SharedState, conn_handle: u16) -> Self {
        Self { state, conn_handle }
    }
}

#[interface(name = "org.sparklink.RemoteService")]
impl RemoteServiceIface {
    /// Exchange SSAP info with the remote peer (initiate service discovery handshake)
    async fn exchange_info(&self) -> zbus::fdo::Result<()> {
        let cmd = slk_protocol::SsapRemoteCmd {
            conn_handle: self.conn_handle,
            _reserved: [0; 2],
        };
        let st = self.state.lock().await;
        st.adapter
            .ssap_exchange_info(&cmd)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_exchange_info: {e}")))
    }

    /// Discover services on the remote peer
    async fn discover(&self, start_handle: u16, end_handle: u16) -> zbus::fdo::Result<u16> {
        let mut disc = slk_protocol::SsapRemoteDiscover {
            conn_handle: self.conn_handle,
            start_handle,
            end_handle,
            count: 0,
        };
        let st = self.state.lock().await;
        st.adapter
            .ssap_remote_discover(&mut disc)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_remote_discover: {e}")))?;
        Ok(disc.count)
    }

    /// Read a property from the remote peer
    async fn read(&self, handle: u16) -> zbus::fdo::Result<Vec<u8>> {
        let mut rw = slk_protocol::SsapRemoteReadWrite {
            conn_handle: self.conn_handle,
            handle,
            length: 0,
            _pad: [0; 2],
            data: [0; 248],
        };
        let st = self.state.lock().await;
        st.adapter
            .ssap_remote_read(&mut rw)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_remote_read: {e}")))?;
        Ok(rw.data[..rw.length as usize].to_vec())
    }

    /// Write a property on the remote peer
    async fn write(&self, handle: u16, value: Vec<u8>) -> zbus::fdo::Result<()> {
        let len = value.len().min(248);
        let rw = slk_protocol::SsapRemoteReadWrite {
            conn_handle: self.conn_handle,
            handle,
            length: len as u16,
            _pad: [0; 2],
            data: {
                let mut d = [0u8; 248];
                d[..len].copy_from_slice(&value[..len]);
                d
            },
        };
        let st = self.state.lock().await;
        st.adapter
            .ssap_remote_write(&rw)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_remote_write: {e}")))
    }

    /// Receive a remote notification/indication event
    async fn receive_event(&self) -> zbus::fdo::Result<NotificationData> {
        let st = self.state.lock().await;
        let ntf = st
            .adapter
            .ssap_remote_event()
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_remote_event: {e}")))?;
        Ok(NotificationData {
            handle: ntf.handle,
            indication: ntf.indication != 0,
            data: ntf.data[..ntf.length as usize].to_vec(),
        })
    }

    /// Invoke a method on a remote peer's SSAP service
    async fn call_method(&self, handle: u16, input: Vec<u8>) -> zbus::fdo::Result<Vec<u8>> {
        let st = self.state.lock().await;
        let mut rw: slk_protocol::SsapRemoteReadWrite = unsafe { std::mem::zeroed() };
        rw.conn_handle = self.conn_handle;
        rw.handle = handle;
        let copy_len = input.len().min(rw.data.len());
        rw.data[..copy_len].copy_from_slice(&input[..copy_len]);
        rw.length = copy_len as u16;
        st.adapter
            .ssap_call_method(&mut rw)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_call_method: {e}")))?;
        let out_len = rw.length as usize;
        Ok(rw.data[..out_len.min(rw.data.len())].to_vec())
    }

    /// Find a remote service by UUID (16-bit)
    async fn find_by_uuid(&self, uuid16: u16) -> zbus::fdo::Result<u16> {
        let st = self.state.lock().await;
        let mut op: slk_protocol::SsapUuidOp = unsafe { std::mem::zeroed() };
        op.conn_handle = self.conn_handle;
        op.uuid16 = uuid16;
        st.adapter
            .ssap_find_by_uuid(&mut op)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_find_by_uuid: {e}")))?;
        Ok(op.handle)
    }

    /// Read a remote property by UUID (16-bit)
    async fn read_by_uuid(&self, uuid16: u16) -> zbus::fdo::Result<Vec<u8>> {
        let st = self.state.lock().await;
        let mut op: slk_protocol::SsapUuidOp = unsafe { std::mem::zeroed() };
        op.conn_handle = self.conn_handle;
        op.uuid16 = uuid16;
        st.adapter
            .ssap_read_by_uuid(&mut op)
            .map_err(|e| zbus::fdo::Error::Failed(format!("ssap_read_by_uuid: {e}")))?;
        let out_len = (op.length as usize).min(op.data.len());
        Ok(op.data[..out_len].to_vec())
    }
}

// ----- D-Bus return types -----

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct SsapInfo {
    pub service_count: u16,
    pub property_count: u16,
    pub total_entries: u16,
    pub mtu: u16,
    pub notification_count: u16,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct ServiceEntry {
    pub start_handle: u16,
    pub end_handle: u16,
    pub uuid16: u16,
    pub primary: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, zbus::zvariant::Type)]
pub struct NotificationData {
    pub handle: u16,
    pub indication: bool,
    pub data: Vec<u8>,
}
