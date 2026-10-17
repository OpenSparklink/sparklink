use std::os::fd::{AsFd, BorrowedFd, OwnedFd};
use std::path::Path;

use nix::fcntl::{OFlag, open};
use nix::sys::stat::Mode;
use tracing::debug;

use crate::ioctl;
use slk_protocol::*;

use crate::{Error, Result};

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

        debug!(path = %path.as_ref().display(), "opened SparkLink device");

        Ok(Self {
            fd: owned,
            dev_index: 0,
        })
    }

    /// Get the raw file descriptor (for use with poll/epoll)
    pub fn as_fd(&self) -> BorrowedFd<'_> {
        self.fd.as_fd()
    }

    /// Independent privileged trace read on this explicitly selected fd.
    pub fn poll_snoop(&self, cursor: &mut crate::SnoopCursor) -> Result<Option<SleSnoopRecord>> {
        crate::snoop::poll(self.raw_fd(), cursor, self.dev_index)
    }
    /// Activate trace poll readiness before epoll registration. Use a dedicated
    /// observation fd; mixing native controller-event and trace modes is rejected.
    pub fn into_snoop_receiver(self, generation: u64) -> Result<crate::SnoopReceiver> {
        crate::SnoopReceiver::from_fd(self.fd, generation, self.dev_index)
    }

    /// Get the number of registered devices
    pub fn device_count(&self) -> Result<u32> {
        let mut count: u32 = 0;
        unsafe { ioctl::sl_dev_count(self.raw_fd(), &mut count)? };
        Ok(count)
    }

    /// Own native management on this open file description. Clones of an Arc
    /// share this owner; separately opened observation fds do not. CAP_NET_ADMIN
    /// is checked on acquisition and every protected call. Kernel copyout faults
    /// do not acquire an invisible lease. Standard profile 0 supports Diagnostic
    /// queries; Managed radio recipes remain unsupported.
    pub fn acquire_management(&self, generation: u64, mode: u32) -> Result<u64> {
        let mut request = SleManagementRequest {
            version: MANAGEMENT_VERSION,
            generation,
            mode,
            ..Default::default()
        };
        unsafe { ioctl::sl_management_acquire(self.raw_fd(), &mut request)? };
        if request.version != MANAGEMENT_VERSION
            || request.generation != generation
            || request.mode != mode
            || request.lease == 0
            || request.flags != 0
            || request.reserved != 0
        {
            return Err(Error::InvalidParam(
                "invalid management acquisition response",
            ));
        }
        Ok(request.lease)
    }
    /// Observe ownership/revocation without consuming control results. A token
    /// is returned only to the owning file, and alone never grants authority.
    pub fn management_status(&self, generation: u64) -> Result<SleManagementQuery> {
        let mut query = SleManagementQuery {
            version: MANAGEMENT_VERSION,
            generation,
            ..Default::default()
        };
        unsafe { ioctl::sl_management_query(self.raw_fd(), &mut query)? };
        if query.version != MANAGEMENT_VERSION
            || query.generation == 0
            || (generation != 0 && query.generation != generation)
            || query.state > MANAGEMENT_FAULTED
            || query.mode > MANAGEMENT_DIAGNOSTIC
            || query.flags & !3 != 0
            || query.status > 255
            || query.opcode > 65535
            || (query.flags & 1 == 0 && query.lease != 0)
            || (query.state != MANAGEMENT_HELD && query.mode != 0)
            || (query.flags & 2 != 0
                && (query.state != MANAGEMENT_FAULTED
                    || query.error >= 0
                    || query.status == 0
                    || query.opcode == 0))
            || query.reserved != 0
            || (query.flags & 1 != 0 && (query.lease == 0 || query.state != MANAGEMENT_HELD))
        {
            return Err(Error::InvalidParam("invalid management status response"));
        }
        Ok(query)
    }
    /// Asynchronous release. A successor is admitted only after actual cleanup
    /// stop replies, or immediately when the owner was already safely quiet.
    pub fn release_management(&self, generation: u64, lease: u64, mode: u32) -> Result<()> {
        let request = SleManagementRequest {
            version: MANAGEMENT_VERSION,
            generation,
            lease,
            mode,
            ..Default::default()
        };
        unsafe { ioctl::sl_management_release(self.raw_fd(), &request)? };
        Ok(())
    }

    /// Get device info for this explicitly selected registration
    pub fn device_info(&self) -> Result<SciDevInfo> {
        let mut info = unsafe { std::mem::zeroed::<SciDevInfo>() };
        unsafe { ioctl::sl_dev_info(self.raw_fd(), &mut info)? };
        Ok(info)
    }

    /// Bind this File to one exact registration. There is no implicit default.
    /// dup/fork share the binding; replug invalidates it.
    pub fn select_device(&mut self, index: u16) -> Result<()> {
        let index_i16 = i16::try_from(index)
            .map_err(|_| Error::InvalidParam("device index exceeds signed affinity range"))?;
        unsafe { ioctl::sl_dev_select(self.raw_fd(), &index_i16)? };
        self.dev_index = index;
        Ok(())
    }

    /// Return registered indices (not a contiguous device count).
    pub fn device_indices(&self) -> Result<Vec<u16>> {
        let mut mask = 0u16;
        unsafe { ioctl::sl_dev_list(self.raw_fd(), &mut mask)? };
        Ok((0..16).filter(|i| mask & (1 << i) != 0).collect())
    }

    /// Observe Core registration without affinity or a management lease.
    /// generation=0 probes the named index; a nonzero value requires that exact
    /// registration. Installed does not assert Host Ready or controller metadata.
    pub fn registration_snapshot(
        &self,
        index: u16,
        generation: u64,
    ) -> Result<SleRegistrationSnapshot> {
        if index >= 16 {
            return Err(Error::InvalidParam("registration index must be 0..15"));
        }
        let mut out = SleRegistrationSnapshot {
            version: REGISTRATION_VERSION,
            dev_index: index,
            generation,
            ..Default::default()
        };
        unsafe { ioctl::sl_registration_snapshot(self.raw_fd(), &mut out)? };
        if !out.valid_for(index, generation) {
            return Err(Error::InvalidParam(
                "invalid registration snapshot response",
            ));
        }
        Ok(out)
    }

    /// Query only this selected registration. generation=0 probes its identity;
    /// a nonzero generation fails if the selected registration changed.
    pub fn controller_snapshot(&self, generation: u64) -> Result<SleControllerSnapshot> {
        let mut snapshot = SleControllerSnapshot {
            generation,
            version: CONTROLLER_SNAPSHOT_VERSION,
            ..Default::default()
        };
        unsafe { ioctl::sl_controller_snapshot(self.raw_fd(), &mut snapshot)? };
        if snapshot.version != CONTROLLER_SNAPSHOT_VERSION
            || snapshot.generation == 0
            || (generation != 0 && snapshot.generation != generation)
            || snapshot.dev_index != self.dev_index
            || !matches!(
                snapshot.flags,
                CONTROLLER_READY | CONTROLLER_SETUP | CONTROLLER_FAULT
            )
            || snapshot.valid_fields & !CONTROLLER_FULL_METADATA != 0
            || snapshot.reserved_byte != 0
            || snapshot.reserved != [0; 4]
        {
            return Err(Error::InvalidParam("invalid controller snapshot response"));
        }
        Ok(snapshot)
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
    pub fn pair(&self, _params: &SlePairParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Get security info
    pub fn sec_info(&self) -> Result<SleSecInfo> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Enable encryption
    pub fn encrypt_on(&self) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Set PSK (Pre-Shared Key)
    pub fn set_psk(&self, _psk: &SlePskParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Get passkey displayed by the controller
    pub fn get_passkey(&self) -> Result<u32> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Confirm passkey match (numeric comparison)
    pub fn confirm_passkey(&self) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Reject passkey match
    pub fn reject_passkey(&self) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Input passkey from user
    pub fn input_passkey(&self, _passkey: u32) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Set OOB data for pairing
    pub fn set_oob(&self, _data: &SleOobData) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Set password for pairing
    pub fn set_password(&self, _params: &SlePasswordParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Reset security state
    pub fn sec_reset(&self) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
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

    // ----- DLI -----

    /// Get DLI controller info
    pub fn dli_info(&self) -> Result<SleDliInfo> {
        Err(Error::NotSupported(
            "legacy aggregate retired; use selected Native snapshot/result",
        ))
    }

    /// Native metadata-only idempotent admission/cancel. Caller supplies an ID
    /// increasing for new requests on this fd, and reuses it after EFAULT.
    /// Retained retries return the same sequence; evicted old IDs fail ESTALE.
    /// Local cancel does not abort an on-wire command or release its reply slot.
    pub fn diagnostic_submit(&self, request: &mut SleDiagnosticSubmit) -> Result<()> {
        validate_diagnostic_submit(request)?;
        let original = *request;
        let mut value = original;
        unsafe { ioctl::sl_diagnostic_submit(self.raw_fd(), &mut value)? };
        if value.seq == 0 || (SleDiagnosticSubmit { seq: 0, ..value }) != original {
            return Err(Error::InvalidParam("invalid diagnostic admission response"));
        }
        *request = value;
        Ok(())
    }

    /// Fetch a result admitted by this exact fd/generation. Requires the same
    /// file to hold Diagnostic and CAP_NET_ADMIN; ENOENT means missing/evicted.
    /// No cursor, shared event dequeue or legacy response fallback is used.
    pub fn diagnostic_result(
        &self,
        generation: u64,
        seq: u32,
    ) -> Result<Option<SleDiagnosticResult>> {
        if generation == 0 || seq == 0 {
            return Err(Error::InvalidParam(
                "diagnostic result requires generation and sequence",
            ));
        }
        let mut result = SleDiagnosticResult {
            version: 1,
            generation,
            seq,
            ..Default::default()
        };
        match unsafe { ioctl::sl_diagnostic_result(self.raw_fd(), &mut result) } {
            Ok(_) => {
                validate_diagnostic_result(&result, generation, seq)?;
                Ok(Some(result))
            }
            Err(nix::Error::ENOENT) => Ok(None),
            Err(error) => Err(Error::Ioctl(error)),
        }
    }

    /// Non-destructively fetch complete native controller parameters.
    /// The cursor belongs to this registration; generation mismatch fails.
    /// Calling this selects native-stream poll readiness for this fd.
    pub fn poll_controller_event(
        &self,
        cursor: &mut crate::ControllerEventCursor,
    ) -> Result<Option<SleControllerEvent>> {
        crate::controller_events::poll(self.raw_fd(), cursor)
    }

    /// Probe the selected registration's identity and confirmed radio state.
    /// This interface does not itself establish SparkLink Ready.
    pub fn discovery_snapshot(&self) -> Result<SleDiscoveryResult> {
        let mut result = SleDiscoveryResult {
            version: DISCOVERY_VERSION,
            ..Default::default()
        };
        unsafe { ioctl::sl_discovery_result(self.raw_fd(), &mut result)? };
        Ok(result)
    }

    /// Submit a complete typed operation. A nonzero caller request_id identifies
    /// it within generation; successful admission is not completion. Select an
    /// adapter, probe its generation, and supply every profile parameter.
    pub fn submit_discovery(&self, request: &SleDiscoverySubmit) -> Result<()> {
        unsafe { ioctl::sl_discovery_submit(self.raw_fd(), request)? };
        Ok(())
    }

    /// Non-destructive result. None means absent/evicted, not pending. Terminal
    /// controller errors remain in status, host errors remain in error.
    pub fn discovery_result(
        &self,
        generation: u64,
        request_id: u64,
    ) -> Result<Option<SleDiscoveryResult>> {
        if generation == 0 || request_id == 0 {
            return Err(crate::Error::InvalidParam(
                "discovery identity must be nonzero",
            ));
        }
        let mut result = SleDiscoveryResult {
            version: DISCOVERY_VERSION,
            generation,
            request_id,
            ..Default::default()
        };
        match unsafe { ioctl::sl_discovery_result(self.raw_fd(), &mut result) } {
            Ok(_) => Ok(Some(result)),
            Err(nix::errno::Errno::ENOENT) => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    /// Typed Native connection admission with caller-supplied profile fields.
    /// The request ID must increase across this open fd. Status acceptance is
    /// not a connection outcome; query this same fd for terminal evidence.
    /// In-flight author cancellation does not physically cancel a connection.
    pub fn submit_native_connection(&self, request: &SleConnectionSubmit) -> Result<()> {
        // SAFETY: initialized repr(C) request is borrowed for this syscall only.
        unsafe { ioctl::sl_connection_submit(self.raw_fd(), request)? };
        Ok(())
    }

    /// Explicit capability/candidate/controller-encryption procedure, not authentication or Bond.
    /// Requires the current Managed File, exact physical reference and admin.
    /// One exchange per lifetime; client disconnects after this limited probe.
    pub fn submit_native_security_negotiation(
        &self,
        request: &SleSecurityNegotiationSubmit,
    ) -> Result<()> {
        // SAFETY: borrowed initialized integer-only ABI for this syscall.
        unsafe { ioctl::sl_security_negotiation_submit(self.raw_fd(), request)? };
        Ok(())
    }

    /// Withdraw only this original File/request. Success means local author
    /// cancellation; installed encryption, controller ownership and in-flight
    /// physical obligations are not undone. Terminal results stay unchanged.
    pub fn cancel_native_security_negotiation(
        &self,
        request: &SleSecurityNegotiationCancel,
    ) -> Result<()> {
        // SAFETY: initialized padding-free repr(C) request, borrowed for ioctl.
        unsafe { ioctl::sl_security_negotiation_cancel(self.raw_fd(), request)? };
        Ok(())
    }

    /// Decide the live original numeric prompt. Never refreshes its deadline.
    pub fn confirm_native_security_numeric(
        &self,
        request: &SleSecurityNumericConfirm,
    ) -> Result<()> {
        // SAFETY: initialized, padding-free, borrowed input for this syscall.
        unsafe { ioctl::sl_security_numeric_confirm(self.raw_fd(), request)? };
        Ok(())
    }

    /// Current mechanism facts under kernel identity/lease/ingress barriers.
    /// Requires Managed + CAP_NET_ADMIN. No pairing, identity, Bond or Grant
    /// is inferred from this informational snapshot; it may become stale.
    pub fn native_connection_security(
        &self,
        generation: u64,
        lifetime: u64,
        handle: u16,
    ) -> Result<SleConnectionSecurity> {
        if generation == 0 || lifetime == 0 || handle > 0x0fff {
            return Err(Error::InvalidParam("invalid security connection identity"));
        }
        let mut output = SleConnectionSecurity {
            version: 1,
            generation,
            lifetime,
            handle,
            ..Default::default()
        };
        // SAFETY: complete initialized writable scalar ABI for this syscall.
        unsafe { ioctl::sl_connection_security(self.raw_fd(), &mut output)? };
        validate_connection_security(&output, generation, lifetime, handle)?;
        Ok(output)
    }

    /// Read local real Complete/peer RX observations, never trusted security.
    /// Query requires the original live Managed File; revoke/Down invalidates it.
    pub fn native_security_negotiation(
        &self,
        generation: u64,
        lifetime: u64,
        handle: u16,
        request_id: u64,
    ) -> Result<SleSecurityNegotiationResult> {
        let mut output = SleSecurityNegotiationResult {
            version: 1,
            generation,
            lifetime,
            handle,
            request_id,
            ..Default::default()
        };
        // SAFETY: initialized writable padding-free repr(C) ABI.
        unsafe { ioctl::sl_security_negotiation_result(self.raw_fd(), &mut output)? };
        validate_security_observation(&output, generation, lifetime, handle, request_id)?;
        Ok(output)
    }

    /// Read observed physical links and the atomic event replay barrier for
    /// this registration. It does not consume events or require a writer lease.
    pub fn native_link_snapshot(&self, generation: u64) -> Result<SleLinkSnapshot> {
        if generation == 0 {
            return Err(crate::Error::InvalidParam(
                "link generation must be nonzero",
            ));
        }
        let mut snapshot = SleLinkSnapshot {
            version: 1,
            generation,
            ..Default::default()
        };
        // SAFETY: writable initialized padding-free ABI storage.
        unsafe { ioctl::sl_link_snapshot(self.raw_fd(), &mut snapshot)? };
        if !snapshot.valid_for(generation) {
            return Err(crate::Error::InvalidParam("malformed native link snapshot"));
        }
        Ok(snapshot)
    }

    /// Author-only bounded result. None is absent/evicted, never success.
    /// This is available after local cancellation, release and owner fault.
    pub fn native_connection_result(
        &self,
        generation: u64,
        request_id: u64,
    ) -> Result<Option<SleConnectionResult>> {
        if generation == 0 || request_id == 0 {
            return Err(crate::Error::InvalidParam(
                "connection identity must be nonzero",
            ));
        }
        let mut result = SleConnectionResult {
            version: 1,
            generation,
            request_id,
            ..Default::default()
        };
        // SAFETY: writable initialized repr(C) storage is valid for the syscall.
        match unsafe { ioctl::sl_connection_result(self.raw_fd(), &mut result) } {
            Ok(_) => Ok(Some(result)),
            Err(nix::errno::Errno::ENOENT) => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    /// Non-destructive correlated final Complete receipt; requires timing UAPI.
    pub fn discovery_timing(
        &self,
        generation: u64,
        request_id: u64,
    ) -> Result<slk_protocol::SleDiscoveryTiming> {
        if generation == 0 || request_id == 0 {
            return Err(crate::Error::InvalidParam(
                "discovery identity must be nonzero",
            ));
        }
        let mut timing = slk_protocol::SleDiscoveryTiming {
            version: 1,
            generation,
            request_id,
            ..Default::default()
        };
        unsafe {
            ioctl::sl_discovery_timing(self.raw_fd(), &mut timing)?;
        }
        Ok(timing)
    }

    /// Wait with a monotonic timeout; return failed/cancelled/faulted records
    /// intact so the caller can display the actual controller/host reason.
    pub async fn wait_discovery(
        &self,
        generation: u64,
        request_id: u64,
        timeout: std::time::Duration,
    ) -> Result<SleDiscoveryResult> {
        let deadline = tokio::time::Instant::now()
            .checked_add(timeout)
            .ok_or(crate::Error::InvalidParam("discovery timeout is too large"))?;
        loop {
            if let Some(result) = self.discovery_result(generation, request_id)? {
                if result.is_terminal() {
                    return Ok(result);
                }
            } else {
                return Err(crate::Error::InvalidParam(
                    "discovery result absent or evicted",
                ));
            }
            let now = tokio::time::Instant::now();
            if now >= deadline {
                return Err(crate::Error::Timeout);
            }
            tokio::time::sleep_until((now + std::time::Duration::from_millis(10)).min(deadline))
                .await;
        }
    }

    /// Transfer this selected fd to an independent native event subscriber.
    /// Requires the versioned kernel interface and a Tokio I/O runtime.
    pub fn into_controller_event_receiver(self) -> Result<crate::ControllerEventReceiver> {
        crate::ControllerEventReceiver::from_fd(self.fd)
    }

    /// Reset the DLI controller
    pub fn dli_reset(&self) -> Result<()> {
        Err(Error::NotSupported(
            "legacy reset cannot maintain Native generation/lifetimes; use Runtime recovery",
        ))
    }

    /// Send a DLI command
    /// Retired raw admission; current kernels reject this entry.
    /// Use versioned Diagnostic submit/result with explicit ownership.
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
        Err(Error::NotSupported(
            "legacy aggregate retired; use selected Native snapshot/result",
        ))
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
    pub fn ral_add(&self, _params: &SleRalAddParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Remove an entry from the RAL
    pub fn ral_remove(&self, _params: &SleRalRemoveParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Clear all RAL entries
    pub fn ral_clear(&self) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Get the current RAL size
    pub fn ral_size(&self) -> Result<u8> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Read the peer RPA for a given identity
    pub fn ral_read_peer_rpa(&self, _params: &mut SleRalQueryParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Read the local RPA for a given identity
    pub fn ral_read_local_rpa(&self, _params: &mut SleRalQueryParams) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Enable or disable RPA resolution
    pub fn rpa_enable(&self, _enable: bool) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    /// Set RPA refresh timeout in seconds
    pub fn rpa_set_timeout(&self, _timeout_secs: u16) -> Result<()> {
        Err(Error::NotSupported(
            "legacy controller security/privacy model retired; per-connection mechanism unavailable",
        ))
    }

    // ----- Measurement -----

    /// Read measurement capability
    pub fn meas_read_cap(&self) -> Result<SleMeasCap> {
        Err(Error::NotSupported(
            "typed measurement capability/control unavailable",
        ))
    }

    /// Set measurement link parameter
    pub fn meas_set_link_param(&self, _param: &SleMeasLinkParam) -> Result<()> {
        Err(Error::NotSupported(
            "typed measurement capability/control unavailable",
        ))
    }

    /// Execute a measurement action
    pub fn meas_action(&self, _action: &SleMeasAction) -> Result<()> {
        Err(Error::NotSupported(
            "typed measurement capability/control unavailable",
        ))
    }

    /// Enable or disable measurement
    pub fn meas_enable(&self, _enable: bool) -> Result<()> {
        Err(Error::NotSupported(
            "typed measurement capability/control unavailable",
        ))
    }

    // ----- Internal helpers -----

    fn raw_fd(&self) -> std::os::fd::RawFd {
        use std::os::fd::AsRawFd;
        self.fd.as_raw_fd()
    }
}

fn validate_security_observation(
    output: &SleSecurityNegotiationResult,
    generation: u64,
    lifetime: u64,
    handle: u16,
    request_id: u64,
) -> Result<()> {
    if output.version != 1
        || output.profile != 1
        || output.generation != generation
        || output.lifetime != lifetime
        || output.handle != handle
        || output.request_id != request_id
        || !matches!(output.state, 1..=9 | 11)
        || output.flags & !127 != 0
        || output.role > 1
        || (if output.flags & 8 != 0 {
            output.state != 3 || output.flags & 16 != 0 || output.comparison_code >= 1000000
        } else {
            output.comparison_code != 0
        })
        || !matches!(
            output.local_caps,
            [3, 0, 0, 16, 0, 2, 2, 2, 2, 0] | [1, 0, 4, 16, 0, 2, 2, 2, 2, 0]
        )
        || (output.local_caps[0] != 1 && (output.flags & !7 != 0 || output.state == 11))
        || (output.local_caps[0] == 1 && matches!(output.state, 4 | 8 | 9))
        || (output.flags & 4 != 0 && output.peer_caps != output.local_caps)
        || (output.flags & 32 != 0 && output.flags & 16 == 0)
        || (output.flags & 64 != 0 && output.state != 11)
        || (output.state == 11
            && (output.flags != 119
                || output.error != 0
                || output.status != 0
                || output.local_caps != [1, 0, 4, 16, 0, 2, 2, 2, 2, 0]
                || output.peer_caps != output.local_caps))
        || (matches!(output.state, 4 | 8 | 9)
            && (output.flags != 7
                || output.status != 0
                || output.error != 0
                || output.peer_caps != output.local_caps))
    {
        return Err(crate::Error::InvalidParam(
            "malformed limited security observation",
        ));
    }
    Ok(())
}

fn validate_diagnostic_submit(value: &SleDiagnosticSubmit) -> Result<()> {
    if value.version != 1
        || value.flags != 0
        || value.generation == 0
        || value.request_id == 0
        || value.seq != 0
        || value.reserved != 0
        || !(1..=5000).contains(&value.timeout_ms)
        || !matches!(value.action, 1 | 2)
        || !matches!(value.opcode, 0x0401..=0x0404 | 0x0406)
    {
        return Err(Error::InvalidParam(
            "invalid Native metadata diagnostic request",
        ));
    }
    Ok(())
}

fn validate_diagnostic_result(
    result: &SleDiagnosticResult,
    generation: u64,
    seq: u32,
) -> Result<()> {
    let state_valid = match result.state {
        1 => result.error == 0 && result.status == 0 && result.data_len == 0,
        2 => result.error == 0 && result.status == 0,
        3 => {
            (result.error < 0 && result.status == 0 && result.data_len == 0)
                || (result.error == 0 && result.status != 0)
        }
        _ => false,
    };
    if result.version != 1
        || result.flags != 0
        || result.generation != generation
        || result.seq != seq
        || result.opcode == 0
        || result._pad != 0
        || result._reserved != [0; 6]
        || usize::from(result.data_len) > result.data.len()
        || !state_valid
    {
        return Err(Error::InvalidParam("invalid diagnostic result response"));
    }
    Ok(())
}

#[cfg(test)]
mod native_validation_tests {
    use super::*;

    #[test]
    fn diagnostic_admission_guards_and_errno_preserve_caller_request() {
        let good = SleDiagnosticSubmit {
            version: 1,
            generation: 7,
            request_id: 1,
            timeout_ms: 5000,
            opcode: 0x0406,
            action: 1,
            ..Default::default()
        };
        let adapter = Adapter::open("/dev/null").unwrap();
        for bad in [
            SleDiagnosticSubmit { version: 2, ..good },
            SleDiagnosticSubmit { flags: 1, ..good },
            SleDiagnosticSubmit {
                generation: 0,
                ..good
            },
            SleDiagnosticSubmit {
                request_id: 0,
                ..good
            },
            SleDiagnosticSubmit { seq: 1, ..good },
            SleDiagnosticSubmit {
                reserved: 1,
                ..good
            },
            SleDiagnosticSubmit { action: 3, ..good },
            SleDiagnosticSubmit {
                opcode: 0x0c05,
                ..good
            },
            SleDiagnosticSubmit {
                timeout_ms: 0,
                ..good
            },
            SleDiagnosticSubmit {
                timeout_ms: 5001,
                ..good
            },
        ] {
            let mut value = bad;
            assert!(matches!(
                adapter.diagnostic_submit(&mut value),
                Err(Error::InvalidParam(_))
            ));
            assert_eq!(value, bad);
        }
        for (action, opcode) in [(1, 0x0401), (1, 0x0404), (2, 0x0406)] {
            let original = SleDiagnosticSubmit {
                action,
                opcode,
                ..good
            };
            let mut value = original;
            assert!(matches!(
                adapter.diagnostic_submit(&mut value),
                Err(Error::Ioctl(nix::errno::Errno::ENOTTY))
            ));
            assert_eq!(value, original);
        }
    }

    #[test]
    fn diagnostic_result_rejects_invalid_identity_and_states() {
        let good = SleDiagnosticResult {
            version: 1,
            generation: 7,
            seq: 9,
            opcode: 0x0403,
            state: 2,
            data_len: 10,
            ..Default::default()
        };
        assert!(validate_diagnostic_result(&good, 7, 9).is_ok());
        for bad in [
            SleDiagnosticResult { version: 2, ..good },
            SleDiagnosticResult { flags: 1, ..good },
            SleDiagnosticResult {
                generation: 8,
                ..good
            },
            SleDiagnosticResult { seq: 10, ..good },
            SleDiagnosticResult { opcode: 0, ..good },
            SleDiagnosticResult { _pad: 1, ..good },
            SleDiagnosticResult {
                _reserved: [1; 6],
                ..good
            },
            SleDiagnosticResult {
                data_len: 65,
                ..good
            },
            SleDiagnosticResult { state: 0, ..good },
            SleDiagnosticResult { state: 1, ..good },
            SleDiagnosticResult {
                error: -110,
                ..good
            },
            SleDiagnosticResult { status: 1, ..good },
            SleDiagnosticResult { state: 3, ..good },
            SleDiagnosticResult {
                state: 3,
                error: 1,
                ..good
            },
        ] {
            assert!(validate_diagnostic_result(&bad, 7, 9).is_err(), "{bad:?}");
        }
        let pending = SleDiagnosticResult {
            state: 1,
            data_len: 0,
            ..good
        };
        assert!(validate_diagnostic_result(&pending, 7, 9).is_ok());
        let failure = SleDiagnosticResult {
            state: 3,
            error: -110,
            data_len: 0,
            ..good
        };
        assert!(validate_diagnostic_result(&failure, 7, 9).is_ok());
        let rejected = SleDiagnosticResult {
            state: 3,
            status: 0xfd,
            ..good
        };
        assert!(validate_diagnostic_result(&rejected, 7, 9).is_ok());
        assert!(
            validate_diagnostic_result(
                &SleDiagnosticResult {
                    status: 1,
                    ..failure
                },
                7,
                9
            )
            .is_err()
        );
    }

    #[test]
    fn numeric_observation_separates_prompt_confirmation_proof_and_install() {
        let offer = [1, 0, 4, 16, 0, 2, 2, 2, 2, 0];
        let prompt = SleSecurityNegotiationResult {
            version: 1,
            profile: 1,
            generation: 2,
            lifetime: 3,
            request_id: 4,
            handle: 5,
            role: 0,
            state: 3,
            flags: 15,
            local_caps: offer,
            peer_caps: offer,
            ..Default::default()
        };
        let valid =
            |v: &SleSecurityNegotiationResult| validate_security_observation(v, 2, 3, 5, 4).is_ok();
        assert!(valid(&prompt)); // 000000 is a valid six-digit display value.
        assert!(valid(&SleSecurityNegotiationResult {
            comparison_code: 999999,
            ..prompt
        }));
        let installed = SleSecurityNegotiationResult {
            state: 11,
            flags: 119,
            ..prompt
        };
        assert!(valid(&installed));
        for bad in [
            SleSecurityNegotiationResult {
                comparison_code: 1000000,
                ..prompt
            },
            SleSecurityNegotiationResult {
                flags: 31,
                ..prompt
            },
            SleSecurityNegotiationResult {
                flags: 7,
                comparison_code: 123,
                ..prompt
            },
            SleSecurityNegotiationResult {
                state: 9,
                ..installed
            },
            SleSecurityNegotiationResult {
                flags: 55,
                ..installed
            },
            SleSecurityNegotiationResult {
                flags: 103,
                ..installed
            },
            SleSecurityNegotiationResult {
                error: -5,
                ..installed
            },
            SleSecurityNegotiationResult {
                status: 1,
                ..installed
            },
            SleSecurityNegotiationResult {
                local_caps: [1; 10],
                ..prompt
            },
            SleSecurityNegotiationResult {
                peer_caps: [3, 0, 0, 16, 0, 2, 2, 2, 2, 0],
                ..prompt
            },
            SleSecurityNegotiationResult {
                generation: 99,
                ..prompt
            },
            SleSecurityNegotiationResult {
                lifetime: 99,
                ..prompt
            },
            SleSecurityNegotiationResult {
                request_id: 99,
                ..prompt
            },
        ] {
            assert!(!valid(&bad), "accepted malformed observation: {bad:?}");
        }
        let old = SleSecurityNegotiationResult {
            state: 9,
            flags: 7,
            local_caps: [3, 0, 0, 16, 0, 2, 2, 2, 2, 0],
            peer_caps: [3, 0, 0, 16, 0, 2, 2, 2, 2, 0],
            ..prompt
        };
        assert!(valid(&old));
        assert!(!valid(&SleSecurityNegotiationResult { flags: 119, ..old }));
    }

    #[test]
    fn diagnostic_query_preserves_real_syscall_errors() {
        let adapter = Adapter::open("/dev/null").unwrap();
        for (generation, seq) in [(0, 1), (1, 0)] {
            assert!(matches!(
                adapter.diagnostic_result(generation, seq),
                Err(Error::InvalidParam(_))
            ));
        }
        assert!(matches!(
            adapter.diagnostic_result(1, 1),
            Err(Error::Ioctl(nix::errno::Errno::ENOTTY))
        ));
    }
}

fn validate_connection_security(
    value: &SleConnectionSecurity,
    generation: u64,
    lifetime: u64,
    handle: u16,
) -> Result<()> {
    if (
        value.version,
        value.generation,
        value.lifetime,
        value.handle,
    ) != (1, generation, lifetime, handle)
        || value.security_epoch == 0
        || value.profile != 1
        || value.error != 0
        || !matches!(
            (value.level, value.flags, value.method, value.key_size),
            (0, 0, 0, 0) | (1, 13, 3, 16) | (2, 15, 4, 16)
        )
    {
        return Err(nix::errno::Errno::EPROTO.into());
    }
    Ok(())
}

#[cfg(test)]
mod connection_security_tests {
    use super::*;
    #[test]
    fn snapshot_requires_exact_identity_epoch_and_supported_fact_conjunction() {
        let base = SleConnectionSecurity {
            version: 1,
            generation: 2,
            lifetime: 3,
            handle: 0,
            profile: 1,
            security_epoch: 1,
            ..Default::default()
        };
        for (level, flags, method, key_size) in [(0, 0, 0, 0), (1, 13, 3, 16), (2, 15, 4, 16)] {
            let v = SleConnectionSecurity {
                level,
                flags,
                method,
                key_size,
                ..base
            };
            assert!(validate_connection_security(&v, 2, 3, 0).is_ok());
            for bad in [
                SleConnectionSecurity {
                    generation: 99,
                    ..v
                },
                SleConnectionSecurity { lifetime: 99, ..v },
                SleConnectionSecurity { handle: 99, ..v },
                SleConnectionSecurity { version: 2, ..v },
                SleConnectionSecurity {
                    security_epoch: 0,
                    ..v
                },
                SleConnectionSecurity { profile: 0, ..v },
                SleConnectionSecurity { error: -5, ..v },
                SleConnectionSecurity { level: 99, ..v },
                SleConnectionSecurity { flags: 99, ..v },
                SleConnectionSecurity { method: 99, ..v },
                SleConnectionSecurity { key_size: 99, ..v },
            ] {
                assert!(validate_connection_security(&bad, 2, 3, 0).is_err());
            }
        }
    }
    #[test]
    fn snapshot_never_falls_back_on_missing_kernel_support() {
        let adapter = Adapter::open("/dev/null").unwrap();
        assert!(matches!(
            adapter.native_connection_security(1, 1, 0),
            Err(Error::Ioctl(nix::errno::Errno::ENOTTY))
        ));
        for identity in [(0, 1, 0), (1, 0, 0), (1, 1, 0x1000)] {
            assert!(matches!(
                adapter.native_connection_security(identity.0, identity.1, identity.2),
                Err(Error::InvalidParam(_))
            ));
        }
    }
}
