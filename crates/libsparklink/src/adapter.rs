use std::os::fd::{AsFd, BorrowedFd, OwnedFd};
use std::path::Path;

use nix::fcntl::{open, OFlag};
use nix::sys::stat::Mode;
use tokio::io::unix::AsyncFd;
use tracing::{debug, info};

use slk_protocol::ioctl;
use slk_protocol::*;

use crate::{Error, Event, Result};

/// Default device path for SparkLink chardev
pub const DEFAULT_DEV_PATH: &str = "/dev/sparklink";

/// Represents an open SparkLink adapter (controller)
pub struct Adapter {
    fd: AsyncFd<OwnedFd>,
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

        let async_fd = AsyncFd::new(owned)
            .map_err(Error::OpenDevice)?;

        info!(path = %path.as_ref().display(), "opened SparkLink device");

        Ok(Self {
            fd: async_fd,
            dev_index: 0,
        })
    }

    /// Get the raw file descriptor (for use with poll/epoll)
    pub fn as_fd(&self) -> BorrowedFd<'_> {
        self.fd.get_ref().as_fd()
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
        debug!(handle = svc.start_handle, uuid16 = svc.uuid16, "service added");
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

    // ----- DLI -----

    /// Get DLI controller info
    pub fn dli_info(&self) -> Result<SleDliInfo> {
        let mut info = unsafe { std::mem::zeroed::<SleDliInfo>() };
        unsafe { ioctl::sl_dli_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Poll for a DLI event (non-blocking)
    pub fn poll_event(&self) -> Result<Option<SleDliEvent>> {
        let mut event = unsafe { std::mem::zeroed::<SleDliEvent>() };
        match unsafe { ioctl::sl_dli_poll_event(self.raw_fd(), &mut event) } {
            Ok(_) => Ok(Some(event)),
            Err(nix::Error::EAGAIN) => Ok(None),
            Err(e) => Err(Error::Ioctl(e)),
        }
    }

    /// Wait for the next event asynchronously
    pub async fn next_event(&self) -> Result<Event> {
        loop {
            let mut guard = self.fd.readable().await
                .map_err(Error::OpenDevice)?;

            match self.poll_event()? {
                Some(raw) => {
                    return Ok(self.decode_event(raw));
                }
                None => {
                    guard.clear_ready();
                }
            }
        }
    }

    // ----- PHY -----

    /// Get PHY info
    pub fn phy_info(&self) -> Result<SlePhyInfo> {
        let mut info = unsafe { std::mem::zeroed::<SlePhyInfo>() };
        unsafe { ioctl::sl_phy_info(self.raw_fd(), &mut info)? };
        Ok(info)
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

    // ----- Internal helpers -----

    fn raw_fd(&self) -> std::os::fd::RawFd {
        use std::os::fd::AsRawFd;
        self.fd.get_ref().as_raw_fd()
    }

    fn decode_event(&self, raw: SleDliEvent) -> Event {
        match raw.event_type {
            EVT_CONN_STATE => Event::ConnectionStateChanged {
                handle: raw.handle,
                state: raw.status,
                peer_addr: raw.addr,
            },
            EVT_ADV_REPORT => {
                let name_end = raw.data.iter().position(|&b| b == 0).unwrap_or(raw.data_len as usize);
                let name = String::from_utf8_lossy(&raw.data[..name_end]).into_owned();
                Event::AdvReport {
                    addr: raw.addr,
                    rssi: raw.status as i8,
                    discovery_level: raw.data[name_end.saturating_add(1).min(raw.data.len() - 1)],
                    name,
                }
            }
            EVT_DATA_RECV => Event::DataReceived {
                handle: raw.handle,
                data: raw.data[..raw.data_len as usize].to_vec(),
            },
            EVT_SEC_CHANGED => Event::SecurityChanged {
                state: raw.data[0],
                method: raw.data[1],
                encrypted: raw.data[2] != 0,
            },
            EVT_PWR_CHANGED => Event::PowerChanged {
                state: raw.data[0],
            },
            EVT_HW_ERROR => Event::HwError {
                code: raw.data[0],
            },
            _ => Event::RawDli(raw),
        }
    }
}
