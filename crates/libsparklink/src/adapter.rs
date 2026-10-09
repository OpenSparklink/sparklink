use std::os::fd::{AsFd, BorrowedFd, OwnedFd};
use std::path::Path;

use nix::fcntl::{OFlag, open};
use nix::sys::stat::Mode;
use tracing::{debug, info};

use slk_protocol::ioctl;
use slk_protocol::*;

use crate::{Error, Event, EventReceiver, Result};

/// Default device path for SparkLink chardev
pub const DEFAULT_DEV_PATH: &str = "/dev/sparklink";

/// Represents an open SparkLink adapter (controller)
pub struct Adapter {
    fd: OwnedFd,
    dev_index: u16,
}

impl Adapter {
    /// Open a SparkLink device
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let owned = open(
            path.as_ref(),
            OFlag::O_RDWR | OFlag::O_CLOEXEC,
            Mode::empty(),
        )
        .map_err(|e| Error::OpenDevice(std::io::Error::from(e)))?;

        info!(path = %path.as_ref().display(), "opened SparkLink device");

        Ok(Self {
            fd: owned,
            dev_index: 0,
        })
    }

    /// Get the raw file descriptor (for use with poll/epoll)
    pub fn as_fd(&self) -> BorrowedFd<'_> {
        self.fd.as_fd()
    }

    /// Get the number of registered devices
    pub fn device_count(&self) -> Result<u32> {
        let mut count: u32 = 0;
        unsafe { ioctl::sl_dev_count(self.raw_fd(), &mut count)? };
        Ok(count)
    }

    /// Get device info for the active device
    pub fn device_info(&self) -> Result<SciDevInfo> {
        let mut info = unsafe { std::mem::zeroed::<SciDevInfo>() };
        unsafe { ioctl::sl_dev_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Switch active device by index
    pub fn switch_device(&mut self, index: u16) -> Result<()> {
        unsafe { ioctl::sl_dev_switch(self.raw_fd(), index as _)? };
        self.dev_index = index;
        debug!(index, "switched active device");
        Ok(())
    }

    /// Get the active device index
    pub fn active_device(&self) -> Result<u16> {
        let mut index: u16 = 0;
        unsafe { ioctl::sl_dev_get_active(self.raw_fd(), &mut index)? };
        Ok(index)
    }

    // ----- Advertising -----

    /// Start advertising with the given parameters
    pub fn start_adv(&self, params: &SleAdvParams) -> Result<()> {
        unsafe { ioctl::sl_start_adv(self.raw_fd(), params)? };
        debug!(interval = params.interval_ms, "advertising started");
        Ok(())
    }

    /// Stop advertising
    pub fn stop_adv(&self) -> Result<()> {
        unsafe { ioctl::sl_stop_adv(self.raw_fd())? };
        debug!("advertising stopped");
        Ok(())
    }

    // ----- Scanning -----

    /// Start scanning with the given parameters
    pub fn start_scan(&self, params: &SleScanParams) -> Result<()> {
        unsafe { ioctl::sl_start_scan(self.raw_fd(), params)? };
        debug!(
            window = params.window_ms,
            interval = params.interval_ms,
            "scanning started"
        );
        Ok(())
    }

    /// Stop scanning
    pub fn stop_scan(&self) -> Result<()> {
        unsafe { ioctl::sl_stop_scan(self.raw_fd())? };
        debug!("scanning stopped");
        Ok(())
    }

    /// Set scan UUID filter
    pub fn set_scan_filter(&self, filter: &SleScanFilter) -> Result<()> {
        unsafe { ioctl::sl_set_scan_filter(self.raw_fd(), filter)? };
        Ok(())
    }

    /// Clear scan filter
    pub fn clear_scan_filter(&self) -> Result<()> {
        unsafe { ioctl::sl_clear_scan_filter(self.raw_fd())? };
        Ok(())
    }

    // ----- Extended Advertising -----

    /// Configure an extended advertising set
    pub fn ext_adv_configure(&self, config: &SleExtAdvConfig) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_configure(self.raw_fd(), config)? };
        debug!(handle = config.handle, "ext adv configured");
        Ok(())
    }

    /// Set extended advertising data
    pub fn ext_adv_set_data(&self, data: &SleExtAdvData) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_set_data(self.raw_fd(), data)? };
        Ok(())
    }

    /// Set extended advertising scan response data
    pub fn ext_adv_set_scan_rsp(&self, data: &SleExtAdvData) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_set_scan_rsp(self.raw_fd(), data)? };
        Ok(())
    }

    /// Enable an extended advertising set
    pub fn ext_adv_enable(&self, handle: u8) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_enable(self.raw_fd(), handle as _)? };
        Ok(())
    }

    /// Disable an extended advertising set
    pub fn ext_adv_disable(&self, handle: u8) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_disable(self.raw_fd(), handle as _)? };
        Ok(())
    }

    /// Remove an extended advertising set
    pub fn ext_adv_remove(&self, handle: u8) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_remove(self.raw_fd(), handle as _)? };
        Ok(())
    }

    /// Get extended advertising set info
    pub fn ext_adv_info(&self, handle: u8) -> Result<SleExtAdvInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleExtAdvInfo>() };
        info.handle = handle;
        unsafe { ioctl::sl_ext_adv_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Enable ext adv with duration and max events
    pub fn ext_adv_enable_ex(&self, params: &SleExtAdvEnableParams) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_enable_ex(self.raw_fd(), params)? };
        Ok(())
    }

    /// Advance the ext adv tick timer
    pub fn ext_adv_tick(&self) -> Result<()> {
        unsafe { ioctl::sl_ext_adv_tick(self.raw_fd())? };
        Ok(())
    }

    // ----- Connection -----

    /// Initiate a connection to a peer
    pub fn connect(&self, params: &SleConnectParams) -> Result<()> {
        unsafe { ioctl::sl_connect(self.raw_fd(), params)? };
        debug!(peer = ?params.peer_addr, "connection initiated");
        Ok(())
    }

    /// Disconnect from a peer
    pub fn disconnect(&self, handle: u16) -> Result<()> {
        unsafe { ioctl::sl_disconnect(self.raw_fd(), handle as _)? };
        debug!(handle, "disconnected");
        Ok(())
    }

    /// Get connection info
    pub fn conn_info(&self, handle: u16) -> Result<SleConnInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleConnInfo>() };
        info.handle = handle;
        unsafe { ioctl::sl_conn_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Send data on a connection
    pub fn conn_send(&self, data: &SleConnData) -> Result<()> {
        unsafe { ioctl::sl_conn_send(self.raw_fd(), data)? };
        Ok(())
    }

    /// List active connections
    pub fn conn_list(&self) -> Result<SleConnList> {
        let mut list = unsafe { std::mem::zeroed::<SleConnList>() };
        unsafe { ioctl::sl_conn_list(self.raw_fd(), &mut list)? };
        Ok(list)
    }

    /// Receive data from a connection
    pub fn conn_recv(&self, handle: u16) -> Result<SleConnData> {
        let mut data = unsafe { std::mem::zeroed::<SleConnData>() };
        data.handle = handle;
        unsafe { ioctl::sl_conn_recv(self.raw_fd(), &mut data)? };
        Ok(data)
    }

    /// Get active connection count
    pub fn conn_count(&self) -> Result<i32> {
        let ret = unsafe { ioctl::sl_conn_count(self.raw_fd())? };
        Ok(ret)
    }

    /// Set connection MTU parameters
    pub fn set_conn_mtu(&self, params: &SleConnMtuParams) -> Result<()> {
        unsafe { ioctl::sl_set_conn_mtu(self.raw_fd(), params)? };
        Ok(())
    }

    // ----- AFH -----

    /// Set the AFH channel map
    pub fn afh_set_map(&self, params: &SleAfhMapParams) -> Result<()> {
        unsafe { ioctl::sl_afh_set_map(self.raw_fd(), params)? };
        Ok(())
    }

    /// Get the current AFH channel map
    pub fn afh_get_map(&self, handle: u16) -> Result<SleAfhMapParams> {
        let mut params = unsafe { std::mem::zeroed::<SleAfhMapParams>() };
        params.handle = handle;
        unsafe { ioctl::sl_afh_get_map(self.raw_fd(), &mut params)? };
        Ok(params)
    }

    /// Report an RSSI measurement on a channel
    pub fn afh_report_rssi(&self, report: &SleAfhRssiReport) -> Result<()> {
        unsafe { ioctl::sl_afh_report_rssi(self.raw_fd(), report)? };
        Ok(())
    }

    /// Classify channels based on RSSI threshold
    pub fn afh_classify(&self, params: &mut SleAfhClassifyParams) -> Result<()> {
        unsafe { ioctl::sl_afh_classify(self.raw_fd(), params)? };
        Ok(())
    }

    /// Get the next hopping channel
    pub fn afh_hop_next(&self, handle: u16) -> Result<SleAfhHopInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleAfhHopInfo>() };
        info.handle = handle;
        unsafe { ioctl::sl_afh_hop_next(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Report a retransmission on a channel
    pub fn afh_report_retx(&self, report: &SleAfhRetxReport) -> Result<()> {
        unsafe { ioctl::sl_afh_report_retx(self.raw_fd(), report)? };
        Ok(())
    }

    // ----- Security -----

    /// Initiate pairing
    pub fn pair(&self, params: &SlePairParams) -> Result<()> {
        unsafe { ioctl::sl_sec_pair(self.raw_fd(), params)? };
        Ok(())
    }

    /// Get security info
    pub fn sec_info(&self) -> Result<SleSecInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleSecInfo>() };
        unsafe { ioctl::sl_sec_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Enable encryption
    pub fn encrypt_on(&self) -> Result<()> {
        unsafe { ioctl::sl_sec_encrypt_on(self.raw_fd())? };
        Ok(())
    }

    /// Set PSK (Pre-Shared Key)
    pub fn set_psk(&self, psk: &SlePskParams) -> Result<()> {
        unsafe { ioctl::sl_sec_set_psk(self.raw_fd(), psk)? };
        Ok(())
    }

    /// Get passkey displayed by the controller
    pub fn get_passkey(&self) -> Result<u32> {
        let mut passkey: u32 = 0;
        unsafe { ioctl::sl_sec_get_passkey(self.raw_fd(), &mut passkey)? };
        Ok(passkey)
    }

    /// Confirm passkey match (numeric comparison)
    pub fn confirm_passkey(&self) -> Result<()> {
        unsafe { ioctl::sl_sec_confirm_passkey(self.raw_fd())? };
        Ok(())
    }

    /// Reject passkey match
    pub fn reject_passkey(&self) -> Result<()> {
        unsafe { ioctl::sl_sec_reject_passkey(self.raw_fd())? };
        Ok(())
    }

    /// Input passkey from user
    pub fn input_passkey(&self, passkey: u32) -> Result<()> {
        let input = SlePasskeyInput { passkey };
        unsafe { ioctl::sl_sec_input_passkey(self.raw_fd(), &input)? };
        Ok(())
    }

    /// Set OOB data for pairing
    pub fn set_oob(&self, data: &SleOobData) -> Result<()> {
        unsafe { ioctl::sl_sec_set_oob(self.raw_fd(), data)? };
        Ok(())
    }

    /// Set password for pairing
    pub fn set_password(&self, params: &SlePasswordParams) -> Result<()> {
        unsafe { ioctl::sl_sec_set_password(self.raw_fd(), params)? };
        Ok(())
    }

    /// Reset security state
    pub fn sec_reset(&self) -> Result<()> {
        unsafe { ioctl::sl_sec_reset(self.raw_fd())? };
        Ok(())
    }

    /// Run SM3 hash test
    pub fn sec_sm3_test(&self, test: &SleHashTest) -> Result<()> {
        unsafe { ioctl::sl_sec_sm3_test(self.raw_fd(), test)? };
        Ok(())
    }

    /// Run SM4 encrypt test
    pub fn sec_sm4_enc_test(&self, data: &SleConnData) -> Result<()> {
        unsafe { ioctl::sl_sec_sm4_enc_test(self.raw_fd(), data)? };
        Ok(())
    }

    /// Run SM4 decrypt test
    pub fn sec_sm4_dec_test(&self, data: &SleConnData) -> Result<()> {
        unsafe { ioctl::sl_sec_sm4_dec_test(self.raw_fd(), data)? };
        Ok(())
    }

    /// Run SM4 block encrypt/decrypt test
    pub fn sec_sm4_block_test(&self, test: &mut SleSm4BlockTest) -> Result<()> {
        unsafe { ioctl::sl_sec_sm4_block_test(self.raw_fd(), test)? };
        Ok(())
    }

    /// Run HMAC-SM3 test
    pub fn sec_hmac_test(&self, test: &mut SleHmacTest) -> Result<()> {
        unsafe { ioctl::sl_sec_hmac_test(self.raw_fd(), test)? };
        Ok(())
    }

    // ----- SSAP Service -----

    /// Register all configured services with the controller
    pub fn ssap_register(&self) -> Result<()> {
        unsafe { ioctl::sl_ssap_register_svc(self.raw_fd())? };
        debug!("SSAP services registered");
        Ok(())
    }

    /// Get SSAP summary information
    pub fn ssap_info(&self) -> Result<SsapSummary> {
        let mut info = unsafe { std::mem::zeroed::<SsapSummary>() };
        unsafe { ioctl::sl_ssap_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Read a property value by handle
    pub fn ssap_read(&self, handle: u16) -> Result<SsapReadWrite> {
        let mut rw = unsafe { std::mem::zeroed::<SsapReadWrite>() };
        rw.handle = handle;
        unsafe { ioctl::sl_ssap_read(self.raw_fd(), &mut rw)? };
        Ok(rw)
    }

    /// Write a property value by handle
    pub fn ssap_write(&self, rw: &SsapReadWrite) -> Result<()> {
        unsafe { ioctl::sl_ssap_write(self.raw_fd(), rw)? };
        Ok(())
    }

    /// Discover local services
    pub fn ssap_find_svc(&self) -> Result<SsapServiceList> {
        let mut list = unsafe { std::mem::zeroed::<SsapServiceList>() };
        unsafe { ioctl::sl_ssap_find_svc(self.raw_fd(), &mut list)? };
        Ok(list)
    }

    /// Send a notification/indication on a property handle
    pub fn ssap_notify(&self, handle: u16) -> Result<()> {
        unsafe { ioctl::sl_ssap_notify(self.raw_fd(), handle as _)? };
        Ok(())
    }

    /// Dequeue a pending notification
    pub fn ssap_dequeue_ntf(&self) -> Result<SsapNotification> {
        let mut ntf = unsafe { std::mem::zeroed::<SsapNotification>() };
        unsafe { ioctl::sl_ssap_dequeue_ntf(self.raw_fd(), &mut ntf)? };
        Ok(ntf)
    }

    /// Add a service to the local database
    pub fn ssap_add_svc(&self, svc: &mut SsapAddService) -> Result<()> {
        unsafe { ioctl::sl_ssap_add_svc(self.raw_fd(), svc)? };
        debug!(
            handle = svc.start_handle,
            uuid16 = svc.uuid16,
            "service added"
        );
        Ok(())
    }

    /// Add a property (characteristic) to a service
    pub fn ssap_add_prop(&self, prop: &mut SsapAddProperty) -> Result<()> {
        unsafe { ioctl::sl_ssap_add_prop(self.raw_fd(), prop)? };
        debug!(handle = prop.handle, uuid16 = prop.uuid16, "property added");
        Ok(())
    }

    /// Remove a service by start handle
    pub fn ssap_remove_svc(&self, start_handle: u16) -> Result<()> {
        unsafe { ioctl::sl_ssap_remove_svc(self.raw_fd(), start_handle as _)? };
        debug!(start_handle, "service removed");
        Ok(())
    }

    /// Exchange SSAP info with a remote peer (initiate service discovery)
    pub fn ssap_exchange_info(&self, cmd: &SsapRemoteCmd) -> Result<()> {
        unsafe { ioctl::sl_ssap_exchange_info(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Discover services on a remote peer
    pub fn ssap_remote_discover(&self, disc: &mut SsapRemoteDiscover) -> Result<()> {
        unsafe { ioctl::sl_ssap_remote_discover(self.raw_fd(), disc)? };
        Ok(())
    }

    /// Read a property on a remote peer
    pub fn ssap_remote_read(&self, rw: &mut SsapRemoteReadWrite) -> Result<()> {
        unsafe { ioctl::sl_ssap_remote_read(self.raw_fd(), rw)? };
        Ok(())
    }

    /// Write a property on a remote peer
    pub fn ssap_remote_write(&self, rw: &SsapRemoteReadWrite) -> Result<()> {
        unsafe { ioctl::sl_ssap_remote_write(self.raw_fd(), rw)? };
        Ok(())
    }

    /// Receive a remote event (notification/indication from peer)
    pub fn ssap_remote_event(&self) -> Result<SsapNotification> {
        let mut ntf = unsafe { std::mem::zeroed::<SsapNotification>() };
        unsafe { ioctl::sl_ssap_remote_event(self.raw_fd(), &mut ntf)? };
        Ok(ntf)
    }

    /// Invoke a method on a remote peer's SSAP service
    pub fn ssap_call_method(&self, rw: &mut SsapRemoteReadWrite) -> Result<()> {
        unsafe { ioctl::sl_ssap_call_method(self.raw_fd(), rw)? };
        Ok(())
    }

    /// Find a remote service by UUID
    pub fn ssap_find_by_uuid(&self, op: &mut SsapUuidOp) -> Result<()> {
        unsafe { ioctl::sl_ssap_find_by_uuid(self.raw_fd(), op)? };
        Ok(())
    }

    /// Read a remote property by UUID
    pub fn ssap_read_by_uuid(&self, op: &mut SsapUuidOp) -> Result<()> {
        unsafe { ioctl::sl_ssap_read_by_uuid(self.raw_fd(), op)? };
        Ok(())
    }

    // ----- Power Management -----

    /// Get power management info
    pub fn pm_info(&self) -> Result<SlePmInfo> {
        let mut info = unsafe { std::mem::zeroed::<SlePmInfo>() };
        unsafe { ioctl::sl_pm_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Set target power state
    pub fn pm_set_state(&self, cmd: &SlePmStateCmd) -> Result<()> {
        unsafe { ioctl::sl_pm_set_state(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Set power management interval parameters
    pub fn pm_set_interval(&self, interval: &SlePmInterval) -> Result<()> {
        unsafe { ioctl::sl_pm_set_interval(self.raw_fd(), interval)? };
        Ok(())
    }

    /// Force active power state
    pub fn pm_force_active(&self, enable: bool) -> Result<()> {
        unsafe { ioctl::sl_pm_force_active(self.raw_fd(), enable as _)? };
        Ok(())
    }

    /// Advance PM tick timer
    pub fn pm_tick(&self) -> Result<()> {
        unsafe { ioctl::sl_pm_tick(self.raw_fd())? };
        Ok(())
    }

    /// Report activity to the PM subsystem
    pub fn pm_activity(&self) -> Result<()> {
        unsafe { ioctl::sl_pm_activity(self.raw_fd())? };
        Ok(())
    }

    // ----- Sync Link -----

    /// Configure unicast sync link (CIG) parameters
    pub fn sync_ucast_param(&self, config: &mut SleSyncCigConfig) -> Result<()> {
        unsafe { ioctl::sl_sync_ucast_param(self.raw_fd(), config)? };
        Ok(())
    }

    /// Create unicast sync links
    pub fn sync_ucast_create(&self, cmd: &SleSyncCreateCmd) -> Result<()> {
        unsafe { ioctl::sl_sync_ucast_create(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Remove a unicast sync group
    pub fn sync_ucast_remove(&self, cig_id: u8) -> Result<()> {
        unsafe { ioctl::sl_sync_ucast_remove(self.raw_fd(), cig_id as _)? };
        Ok(())
    }

    /// Configure multicast sync link (BIG) parameters
    pub fn sync_mcast_param(&self, config: &mut SleSyncBigConfig) -> Result<()> {
        unsafe { ioctl::sl_sync_mcast_param(self.raw_fd(), config)? };
        Ok(())
    }

    /// Create multicast sync links
    pub fn sync_mcast_create(&self, cmd: &SleSyncCreateCmd) -> Result<()> {
        unsafe { ioctl::sl_sync_mcast_create(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Remove a multicast sync group
    pub fn sync_mcast_remove(&self, big_id: u8) -> Result<()> {
        unsafe { ioctl::sl_sync_mcast_remove(self.raw_fd(), big_id as _)? };
        Ok(())
    }

    /// Configure a sync link datapath
    pub fn sync_datapath_cfg(&self, cmd: &SleSyncDatapathCmd) -> Result<()> {
        unsafe { ioctl::sl_sync_datapath_cfg(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Remove a sync link datapath
    pub fn sync_datapath_remove(&self, sync_handle: u16) -> Result<()> {
        unsafe { ioctl::sl_sync_datapath_remove(self.raw_fd(), sync_handle as _)? };
        Ok(())
    }

    /// Get sync link info
    pub fn sync_info(&self, sync_handle: u16) -> Result<SleSyncLinkInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleSyncLinkInfo>() };
        info.sync_handle = sync_handle;
        unsafe { ioctl::sl_sync_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    // ----- Event Queue -----

    /// Get pending event count
    pub fn event_count(&self) -> Result<i32> {
        let ret = unsafe { ioctl::sl_event_count(self.raw_fd())? };
        Ok(ret)
    }

    /// Get event queue statistics
    pub fn event_stats(&self) -> Result<SleEventStats> {
        let mut stats = unsafe { std::mem::zeroed::<SleEventStats>() };
        unsafe { ioctl::sl_event_stats(self.raw_fd(), &mut stats)? };
        Ok(stats)
    }

    // ----- DLI -----

    /// Get DLI controller info
    pub fn dli_info(&self) -> Result<SleDliInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleDliInfo>() };
        unsafe { ioctl::sl_dli_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Poll for a DLI event (non-blocking)
    pub fn poll_event(&self) -> Result<Option<SleDliEvent>> {
        crate::receiver::poll_event(self.raw_fd())
    }

    /// Transfer this independently opened fd to a single async event consumer.
    ///
    /// Requires a Tokio runtime with I/O enabled. Control adapters and C/Python
    /// handles do not require a runtime. Until the kernel subscription UAPI is
    /// implemented, this receiver uses the legacy destructive DLI event ioctl.
    pub fn into_event_receiver(self) -> Result<EventReceiver> {
        EventReceiver::from_fd(self.fd)
    }

    /// Compatibility helper; prefer a persistent, independently owned receiver.
    #[deprecated(note = "Open a dedicated Adapter and use into_event_receiver")]
    pub async fn next_event(&self) -> Result<Event> {
        let fd = self.fd.try_clone().map_err(Error::OpenDevice)?;
        EventReceiver::from_fd(fd)?.next_event().await
    }

    /// Reset the DLI controller
    pub fn dli_reset(&self) -> Result<()> {
        unsafe { ioctl::sl_dli_reset(self.raw_fd())? };
        Ok(())
    }

    /// Send a DLI command
    pub fn dli_send_cmd(&self, cmd: &mut SleDliCmd) -> Result<()> {
        unsafe { ioctl::sl_dli_send_cmd(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Get the number of USB DLI devices
    pub fn usb_dev_count(&self) -> Result<i32> {
        let ret = unsafe { ioctl::sl_usb_dev_count(self.raw_fd())? };
        Ok(ret)
    }

    /// Get management queue statistics
    pub fn mgmt_stats(&self) -> Result<SleMgmtStats> {
        let mut stats = unsafe { std::mem::zeroed::<SleMgmtStats>() };
        unsafe { ioctl::sl_mgmt_stats(self.raw_fd(), &mut stats)? };
        Ok(stats)
    }

    // ----- PHY -----

    /// Get PHY info
    pub fn phy_info(&self) -> Result<SlePhyInfo> {
        let mut info = unsafe { std::mem::zeroed::<SlePhyInfo>() };
        unsafe { ioctl::sl_phy_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Set MCS index
    pub fn phy_set_mcs(&self, cmd: &SlePhyMcsCmd) -> Result<()> {
        unsafe { ioctl::sl_phy_set_mcs(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Set TX power
    pub fn phy_set_txpower(&self, cmd: &SlePhyTxPowerCmd) -> Result<()> {
        unsafe { ioctl::sl_phy_set_txpower(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Select optimal MCS for given SINR and bandwidth
    pub fn phy_mcs_select(&self, params: &mut SlePhyMcsSelect) -> Result<()> {
        unsafe { ioctl::sl_phy_mcs_select(self.raw_fd(), params)? };
        Ok(())
    }

    /// Get next hopping channel from PHY layer
    pub fn phy_hop_next(&self) -> Result<SlePhyHopInfo> {
        let mut info = unsafe { std::mem::zeroed::<SlePhyHopInfo>() };
        unsafe { ioctl::sl_phy_hop_next(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Set PHY bandwidth
    pub fn phy_set_bw(&self, cmd: &SlePhyBwCmd) -> Result<()> {
        unsafe { ioctl::sl_phy_set_bw(self.raw_fd(), cmd)? };
        Ok(())
    }

    /// Get SINR thresholds
    pub fn phy_get_sinr(&self) -> Result<SleSinrThresholds> {
        let mut thresholds = unsafe { std::mem::zeroed::<SleSinrThresholds>() };
        unsafe { ioctl::sl_phy_get_sinr(self.raw_fd(), &mut thresholds)? };
        Ok(thresholds)
    }

    /// Set SINR thresholds
    pub fn phy_set_sinr(&self, thresholds: &SleSinrThresholds) -> Result<()> {
        unsafe { ioctl::sl_phy_set_sinr(self.raw_fd(), thresholds)? };
        Ok(())
    }

    // ----- Role -----

    /// Set device role (0 = G-node, 1 = T-node)
    pub fn set_role(&self, role: u8) -> Result<()> {
        unsafe { ioctl::sl_set_role(self.raw_fd(), role as _)? };
        Ok(())
    }

    /// Get device role
    pub fn get_role(&self) -> Result<u8> {
        let mut role: u8 = 0;
        unsafe { ioctl::sl_get_role(self.raw_fd(), &mut role)? };
        Ok(role)
    }

    // ----- Subsystem Stats -----

    /// Get subsystem statistics
    pub fn subsys_stats(&self) -> Result<SleSubsysStats> {
        let mut stats = unsafe { std::mem::zeroed::<SleSubsysStats>() };
        unsafe { ioctl::sl_subsys_stats(self.raw_fd(), &mut stats)? };
        Ok(stats)
    }

    // ----- Capability / Connection Update -----

    /// Read peer features
    pub fn conn_read_peer_features(&self, handle: u16) -> Result<SleConnPeerCap> {
        let mut cap = unsafe { std::mem::zeroed::<SleConnPeerCap>() };
        cap.handle = handle;
        unsafe { ioctl::sl_conn_read_peer_features(self.raw_fd(), &mut cap)? };
        Ok(cap)
    }

    /// Read peer version
    pub fn conn_read_peer_version(&self, handle: u16) -> Result<SleConnPeerCap> {
        let mut cap = unsafe { std::mem::zeroed::<SleConnPeerCap>() };
        cap.handle = handle;
        unsafe { ioctl::sl_conn_read_peer_version(self.raw_fd(), &mut cap)? };
        Ok(cap)
    }

    /// Update connection parameters
    pub fn conn_update_params(&self, params: &SleConnParamUpdate) -> Result<()> {
        unsafe { ioctl::sl_conn_update_params(self.raw_fd(), params)? };
        Ok(())
    }

    /// Update connection PHY parameters
    pub fn conn_phy_update(&self, params: &SleConnPhyUpdate) -> Result<()> {
        unsafe { ioctl::sl_conn_phy_update(self.raw_fd(), params)? };
        Ok(())
    }

    // ----- RAL / RPA -----

    /// Add an entry to the Resolving Address List
    pub fn ral_add(&self, params: &SleRalAddParams) -> Result<()> {
        unsafe { ioctl::sl_ral_add(self.raw_fd(), params)? };
        Ok(())
    }

    /// Remove an entry from the RAL
    pub fn ral_remove(&self, params: &SleRalRemoveParams) -> Result<()> {
        unsafe { ioctl::sl_ral_remove(self.raw_fd(), params)? };
        Ok(())
    }

    /// Clear all RAL entries
    pub fn ral_clear(&self) -> Result<()> {
        unsafe { ioctl::sl_ral_clear(self.raw_fd())? };
        Ok(())
    }

    /// Get the current RAL size
    pub fn ral_size(&self) -> Result<u8> {
        let mut size: u8 = 0;
        unsafe { ioctl::sl_ral_size(self.raw_fd(), &mut size)? };
        Ok(size)
    }

    /// Read the peer RPA for a given identity
    pub fn ral_read_peer_rpa(&self, params: &mut SleRalQueryParams) -> Result<()> {
        unsafe { ioctl::sl_ral_read_peer_rpa(self.raw_fd(), params)? };
        Ok(())
    }

    /// Read the local RPA for a given identity
    pub fn ral_read_local_rpa(&self, params: &mut SleRalQueryParams) -> Result<()> {
        unsafe { ioctl::sl_ral_read_local_rpa(self.raw_fd(), params)? };
        Ok(())
    }

    /// Enable or disable RPA resolution
    pub fn rpa_enable(&self, enable: bool) -> Result<()> {
        unsafe { ioctl::sl_rpa_enable(self.raw_fd(), enable as _)? };
        Ok(())
    }

    /// Set RPA refresh timeout in seconds
    pub fn rpa_set_timeout(&self, timeout_secs: u16) -> Result<()> {
        unsafe { ioctl::sl_rpa_set_timeout(self.raw_fd(), timeout_secs as _)? };
        Ok(())
    }

    // ----- Measurement -----

    /// Read measurement capability
    pub fn meas_read_cap(&self) -> Result<SleMeasCap> {
        let mut cap = unsafe { std::mem::zeroed::<SleMeasCap>() };
        unsafe { ioctl::sl_meas_read_cap(self.raw_fd(), &mut cap)? };
        Ok(cap)
    }

    /// Set measurement link parameter
    pub fn meas_set_link_param(&self, param: &SleMeasLinkParam) -> Result<()> {
        unsafe { ioctl::sl_meas_set_link_param(self.raw_fd(), param)? };
        Ok(())
    }

    /// Execute a measurement action
    pub fn meas_action(&self, action: &SleMeasAction) -> Result<()> {
        unsafe { ioctl::sl_meas_action(self.raw_fd(), action)? };
        Ok(())
    }

    /// Enable or disable measurement
    pub fn meas_enable(&self, enable: bool) -> Result<()> {
        unsafe { ioctl::sl_meas_enable(self.raw_fd(), enable as _)? };
        Ok(())
    }

    // ----- Internal helpers -----

    fn raw_fd(&self) -> std::os::fd::RawFd {
        use std::os::fd::AsRawFd;
        self.fd.as_raw_fd()
    }
}

pub(crate) fn decode_event(raw: SleDliEvent) -> Result<Event> {
    let length = usize::from(raw.data_len);
    if length > raw.data.len() {
        return Err(Error::InvalidParam("event payload exceeds buffer"));
    }
    let minimum = match raw.event_type {
        EVT_ADV_REPORT => 2,
        EVT_ENCRYPTION_CHANGED | EVT_HW_ERROR => 1,
        _ => 0,
    };
    if length < minimum {
        return Err(Error::InvalidParam("truncated event payload"));
    }
    Ok(match raw.event_type {
        EVT_CONN_COMPLETE => Event::ConnectionStateChanged {
            handle: raw.handle,
            state: if raw.status == 0 {
                ConnState::Connected as u8
            } else {
                ConnState::Idle as u8
            },
            peer_addr: raw.addr,
        },
        EVT_DISCONNECTED => Event::ConnectionStateChanged {
            handle: raw.handle,
            state: ConnState::Idle as u8,
            peer_addr: raw.addr,
        },
        EVT_ADV_REPORT => {
            let rssi = raw.data[0] as i8;
            let discovery_level = raw.data[1];
            let adv_data_len = (raw.data_len as usize).saturating_sub(2);
            let adv_data = raw.data[2..2 + adv_data_len].to_vec();
            let (entries, _) = slk_protocol::parse_adv_data(&adv_data);
            let name = slk_protocol::find_local_name(&entries)
                .unwrap_or_default()
                .to_string();
            Event::AdvReport {
                addr: raw.addr,
                rssi,
                discovery_level,
                name,
                adv_data,
            }
        }
        EVT_DATA_RECV => Event::DataReceived {
            handle: raw.handle,
            data: raw.data[..raw.data_len as usize].to_vec(),
        },
        EVT_ENCRYPTION_CHANGED => Event::SecurityChanged {
            state: if raw.data[0] != 0 { 3 } else { 0 },
            method: 0,
            encrypted: raw.data[0] != 0,
        },
        EVT_HW_ERROR => Event::HwError { code: raw.data[0] },
        _ => Event::RawDli(raw),
    })
}
