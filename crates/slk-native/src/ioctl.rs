/// SparkLink ioctl magic number: 'S' (0x53)
pub const SL_MAGIC: u8 = b'S';

nix::ioctl_readwrite!(
    sl_connection_security,
    SL_MAGIC,
    0xd6,
    slk_protocol::SleConnectionSecurity
);

// ----- Device Management (0x01 - 0x08) -----

// Removed unpublished no-op registration commands 0x01/0x02.
nix::ioctl_read!(sl_dev_count, SL_MAGIC, 0x03, u32);
nix::ioctl_read!(sl_dev_info, SL_MAGIC, 0x04, slk_protocol::SciDevInfo);
nix::ioctl_write_int!(sl_dev_switch, SL_MAGIC, 0x05);
nix::ioctl_read!(sl_dev_list, SL_MAGIC, 0x06, u16);
nix::ioctl_write_ptr!(sl_dev_select, SL_MAGIC, 0x07, i16);
nix::ioctl_read!(sl_dev_get_active, SL_MAGIC, 0x08, u16);
nix::ioctl_readwrite!(
    sl_registration_snapshot,
    SL_MAGIC,
    0x9f,
    slk_protocol::SleRegistrationSnapshot
);

// ----- Advertising (0x10 - 0x1B) -----

nix::ioctl_write_ptr!(sl_start_adv, SL_MAGIC, 0x10, slk_protocol::SleAdvParams);
nix::ioctl_none!(sl_stop_adv, SL_MAGIC, 0x11);
nix::ioctl_write_ptr!(sl_start_scan, SL_MAGIC, 0x12, slk_protocol::SleScanParams);
nix::ioctl_none!(sl_stop_scan, SL_MAGIC, 0x13);
nix::ioctl_write_ptr!(
    sl_ext_adv_configure,
    SL_MAGIC,
    0x14,
    slk_protocol::SleExtAdvConfig
);
nix::ioctl_write_ptr!(
    sl_ext_adv_set_data,
    SL_MAGIC,
    0x15,
    slk_protocol::SleExtAdvData
);
nix::ioctl_write_int!(sl_ext_adv_enable, SL_MAGIC, 0x16);
nix::ioctl_write_int!(sl_ext_adv_disable, SL_MAGIC, 0x17);
nix::ioctl_write_int!(sl_ext_adv_remove, SL_MAGIC, 0x18);
nix::ioctl_readwrite!(sl_ext_adv_info, SL_MAGIC, 0x19, slk_protocol::SleExtAdvInfo);
nix::ioctl_write_ptr!(
    sl_ext_adv_enable_ex,
    SL_MAGIC,
    0x1A,
    slk_protocol::SleExtAdvEnableParams
);
nix::ioctl_none!(sl_ext_adv_tick, SL_MAGIC, 0x1B);
nix::ioctl_write_ptr!(
    sl_ext_adv_set_scan_rsp,
    SL_MAGIC,
    0x1C,
    slk_protocol::SleExtAdvData
);

// ----- Scan Injection / Filtering (0x20 - 0x24) -----

nix::ioctl_write_ptr!(sl_inject_adv, SL_MAGIC, 0x20, slk_protocol::SleInjectAdv);
nix::ioctl_none!(sl_scan_result_count, SL_MAGIC, 0x21);
nix::ioctl_write_ptr!(
    sl_inject_raw_adv,
    SL_MAGIC,
    0x22,
    slk_protocol::SleInjectRawAdv
);
nix::ioctl_write_ptr!(
    sl_set_scan_filter,
    SL_MAGIC,
    0x23,
    slk_protocol::SleScanFilter
);
nix::ioctl_none!(sl_clear_scan_filter, SL_MAGIC, 0x24);

// ----- Connection Management (0x30 - 0x3F) -----

nix::ioctl_write_ptr!(sl_connect, SL_MAGIC, 0x30, slk_protocol::SleConnectParams);
nix::ioctl_write_int!(sl_disconnect, SL_MAGIC, 0x31);
nix::ioctl_readwrite!(sl_conn_info, SL_MAGIC, 0x32, slk_protocol::SleConnInfo);
nix::ioctl_write_ptr!(sl_conn_send, SL_MAGIC, 0x33, slk_protocol::SleConnData);
nix::ioctl_readwrite!(sl_conn_recv, SL_MAGIC, 0x34, slk_protocol::SleConnData);
nix::ioctl_write_ptr!(
    sl_inject_conn_resp,
    SL_MAGIC,
    0x35,
    slk_protocol::SleInjectConnResp
);
nix::ioctl_write_ptr!(
    sl_inject_conn_data,
    SL_MAGIC,
    0x36,
    slk_protocol::SleConnData
);
nix::ioctl_none!(sl_conn_count, SL_MAGIC, 0x37);
nix::ioctl_read!(sl_conn_list, SL_MAGIC, 0x38, slk_protocol::SleConnList);
nix::ioctl_write_ptr!(
    sl_set_conn_mtu,
    SL_MAGIC,
    0x39,
    slk_protocol::SleConnMtuParams
);

// ----- AFH (0x3A - 0x3F) -----

nix::ioctl_write_ptr!(
    sl_afh_set_map,
    SL_MAGIC,
    0x3A,
    slk_protocol::SleAfhMapParams
);
nix::ioctl_readwrite!(
    sl_afh_get_map,
    SL_MAGIC,
    0x3B,
    slk_protocol::SleAfhMapParams
);
nix::ioctl_write_ptr!(
    sl_afh_report_rssi,
    SL_MAGIC,
    0x3C,
    slk_protocol::SleAfhRssiReport
);
nix::ioctl_readwrite!(
    sl_afh_classify,
    SL_MAGIC,
    0x3D,
    slk_protocol::SleAfhClassifyParams
);
nix::ioctl_readwrite!(sl_afh_hop_next, SL_MAGIC, 0x3E, slk_protocol::SleAfhHopInfo);
nix::ioctl_write_ptr!(
    sl_afh_report_retx,
    SL_MAGIC,
    0x3F,
    slk_protocol::SleAfhRetxReport
);

// ----- Security (0x40 - 0x4F) -----

nix::ioctl_write_ptr!(sl_sec_sm3_test, SL_MAGIC, 0x44, slk_protocol::SleHashTest);
nix::ioctl_write_ptr!(
    sl_sec_sm4_enc_test,
    SL_MAGIC,
    0x45,
    slk_protocol::SleConnData
);
nix::ioctl_write_ptr!(
    sl_sec_sm4_dec_test,
    SL_MAGIC,
    0x46,
    slk_protocol::SleConnData
);
nix::ioctl_readwrite!(
    sl_sec_sm4_block_test,
    SL_MAGIC,
    0x47,
    slk_protocol::SleSm4BlockTest
);
nix::ioctl_readwrite!(sl_sec_hmac_test, SL_MAGIC, 0x48, slk_protocol::SleHmacTest);

// Removed unpublished kernel SSAP commands; no compatibility fallback.

// ----- Power Management (0x60 - 0x65) -----

nix::ioctl_read!(sl_pm_info, SL_MAGIC, 0x60, slk_protocol::SlePmInfo);
nix::ioctl_write_ptr!(sl_pm_set_state, SL_MAGIC, 0x61, slk_protocol::SlePmStateCmd);
nix::ioctl_write_ptr!(
    sl_pm_set_interval,
    SL_MAGIC,
    0x62,
    slk_protocol::SlePmInterval
);
nix::ioctl_write_int!(sl_pm_force_active, SL_MAGIC, 0x63);
nix::ioctl_none!(sl_pm_tick, SL_MAGIC, 0x64);
nix::ioctl_none!(sl_pm_activity, SL_MAGIC, 0x65);

// ----- Sync Link (0x66 - 0x6E) -----

nix::ioctl_readwrite!(
    sl_sync_ucast_param,
    SL_MAGIC,
    0x66,
    slk_protocol::SleSyncCigConfig
);
nix::ioctl_write_ptr!(
    sl_sync_ucast_create,
    SL_MAGIC,
    0x67,
    slk_protocol::SleSyncCreateCmd
);
nix::ioctl_write_int!(sl_sync_ucast_remove, SL_MAGIC, 0x68);
nix::ioctl_readwrite!(
    sl_sync_mcast_param,
    SL_MAGIC,
    0x69,
    slk_protocol::SleSyncBigConfig
);
nix::ioctl_write_ptr!(
    sl_sync_mcast_create,
    SL_MAGIC,
    0x6A,
    slk_protocol::SleSyncCreateCmd
);
nix::ioctl_write_int!(sl_sync_mcast_remove, SL_MAGIC, 0x6B);
nix::ioctl_write_ptr!(
    sl_sync_datapath_cfg,
    SL_MAGIC,
    0x6C,
    slk_protocol::SleSyncDatapathCmd
);
nix::ioctl_write_int!(sl_sync_datapath_remove, SL_MAGIC, 0x6D);
nix::ioctl_readwrite!(sl_sync_info, SL_MAGIC, 0x6E, slk_protocol::SleSyncLinkInfo);

// ----- Event Queue (0x70 - 0x71) -----

// ----- DLI Controller (0x80 - 0x86) -----

nix::ioctl_read!(sl_dli_info, SL_MAGIC, 0x80, slk_protocol::SleDliInfo);
nix::ioctl_none!(sl_usb_dev_count, SL_MAGIC, 0x81);
nix::ioctl_none!(sl_dli_reset, SL_MAGIC, 0x83);
nix::ioctl_readwrite!(sl_dli_send_cmd, SL_MAGIC, 0x84, slk_protocol::SleDliCmd);
nix::ioctl_read!(sl_mgmt_stats, SL_MAGIC, 0x85, slk_protocol::SleMgmtStats);
nix::ioctl_readwrite!(
    sl_controller_event_get,
    SL_MAGIC,
    0x87,
    slk_protocol::SleControllerEventQuery
);

// ----- PHY Layer (0x90 - 0x97) -----

nix::ioctl_read!(sl_phy_info, SL_MAGIC, 0x90, slk_protocol::SlePhyInfo);
nix::ioctl_write_ptr!(sl_phy_set_mcs, SL_MAGIC, 0x91, slk_protocol::SlePhyMcsCmd);
nix::ioctl_write_ptr!(
    sl_phy_set_txpower,
    SL_MAGIC,
    0x92,
    slk_protocol::SlePhyTxPowerCmd
);
nix::ioctl_readwrite!(
    sl_phy_mcs_select,
    SL_MAGIC,
    0x93,
    slk_protocol::SlePhyMcsSelect
);
nix::ioctl_read!(sl_phy_hop_next, SL_MAGIC, 0x94, slk_protocol::SlePhyHopInfo);
nix::ioctl_write_ptr!(sl_phy_set_bw, SL_MAGIC, 0x95, slk_protocol::SlePhyBwCmd);
nix::ioctl_read!(
    sl_phy_get_sinr,
    SL_MAGIC,
    0x96,
    slk_protocol::SleSinrThresholds
);
nix::ioctl_write_ptr!(
    sl_phy_set_sinr,
    SL_MAGIC,
    0x97,
    slk_protocol::SleSinrThresholds
);

// ----- Capability / Connection Update (0x98 - 0x9B) -----

nix::ioctl_readwrite!(
    sl_conn_read_peer_features,
    SL_MAGIC,
    0x98,
    slk_protocol::SleConnPeerCap
);
nix::ioctl_readwrite!(
    sl_conn_read_peer_version,
    SL_MAGIC,
    0x99,
    slk_protocol::SleConnPeerCap
);
nix::ioctl_write_ptr!(
    sl_conn_update_params,
    SL_MAGIC,
    0x9A,
    slk_protocol::SleConnParamUpdate
);
nix::ioctl_write_ptr!(
    sl_conn_phy_update,
    SL_MAGIC,
    0x9B,
    slk_protocol::SleConnPhyUpdate
);

// ----- Role (0xA0 - 0xA1) -----

nix::ioctl_write_int!(sl_set_role, SL_MAGIC, 0xA0);
nix::ioctl_read!(sl_get_role, SL_MAGIC, 0xA1, u8);

// ----- RAL / RPA (0xB0 - 0xB7) -----

nix::ioctl_write_ptr!(sl_ral_add, SL_MAGIC, 0xB0, slk_protocol::SleRalAddParams);
nix::ioctl_write_ptr!(
    sl_ral_remove,
    SL_MAGIC,
    0xB1,
    slk_protocol::SleRalRemoveParams
);
nix::ioctl_none!(sl_ral_clear, SL_MAGIC, 0xB2);
nix::ioctl_read!(sl_ral_size, SL_MAGIC, 0xB3, u8);
nix::ioctl_readwrite!(
    sl_ral_read_peer_rpa,
    SL_MAGIC,
    0xB4,
    slk_protocol::SleRalQueryParams
);
nix::ioctl_readwrite!(
    sl_ral_read_local_rpa,
    SL_MAGIC,
    0xB5,
    slk_protocol::SleRalQueryParams
);
nix::ioctl_write_int!(sl_rpa_enable, SL_MAGIC, 0xB6);
nix::ioctl_write_int!(sl_rpa_set_timeout, SL_MAGIC, 0xB7);

// ----- Measurement (0xC0 - 0xC3) -----

nix::ioctl_read!(sl_meas_read_cap, SL_MAGIC, 0xC0, slk_protocol::SleMeasCap);
nix::ioctl_write_ptr!(
    sl_meas_set_link_param,
    SL_MAGIC,
    0xC1,
    slk_protocol::SleMeasLinkParam
);
nix::ioctl_write_ptr!(sl_meas_action, SL_MAGIC, 0xC2, slk_protocol::SleMeasAction);
nix::ioctl_write_int!(sl_meas_enable, SL_MAGIC, 0xC3);

// Versioned per-registration typed discovery. Submit has no output copy.
nix::ioctl_write_ptr!(
    sl_discovery_submit,
    SL_MAGIC,
    0x88,
    slk_protocol::SleDiscoverySubmit
);
nix::ioctl_readwrite!(
    sl_discovery_result,
    SL_MAGIC,
    0x89,
    slk_protocol::SleDiscoveryResult
);

nix::ioctl_readwrite!(
    sl_controller_snapshot,
    SL_MAGIC,
    0x8a,
    slk_protocol::SleControllerSnapshot
);

nix::ioctl_readwrite!(
    sl_management_acquire,
    SL_MAGIC,
    0x8b,
    slk_protocol::SleManagementRequest
);
nix::ioctl_write_ptr!(
    sl_management_release,
    SL_MAGIC,
    0x8c,
    slk_protocol::SleManagementRequest
);
nix::ioctl_readwrite!(
    sl_management_query,
    SL_MAGIC,
    0x8d,
    slk_protocol::SleManagementQuery
);
nix::ioctl_readwrite!(sl_snoop_get, SL_MAGIC, 0x8e, slk_protocol::SleSnoopQuery);

nix::ioctl_readwrite!(
    sl_discovery_timing,
    SL_MAGIC,
    0x8f,
    slk_protocol::SleDiscoveryTiming
);

nix::ioctl_readwrite!(
    sl_diagnostic_result,
    SL_MAGIC,
    0xd0,
    slk_protocol::SleDiagnosticResult
);

nix::ioctl_readwrite!(
    sl_diagnostic_submit,
    SL_MAGIC,
    0xd1,
    slk_protocol::SleDiagnosticSubmit
);

// Unpublished typed Native connection; raw DLI mutation stays unsupported.
nix::ioctl_write_ptr!(
    sl_connection_submit,
    SL_MAGIC,
    0x9c,
    slk_protocol::SleConnectionSubmit
);
nix::ioctl_readwrite!(
    sl_connection_result,
    SL_MAGIC,
    0x9d,
    slk_protocol::SleConnectionResult
);
nix::ioctl_readwrite!(
    sl_link_snapshot,
    SL_MAGIC,
    0x9e,
    slk_protocol::SleLinkSnapshot
);

// Experimental capability-only procedure; same Managed File and CAP_NET_ADMIN.
nix::ioctl_write_ptr!(
    sl_security_negotiation_submit,
    SL_MAGIC,
    0xd2,
    slk_protocol::SleSecurityNegotiationSubmit
);
nix::ioctl_readwrite!(
    sl_security_negotiation_result,
    SL_MAGIC,
    0xd3,
    slk_protocol::SleSecurityNegotiationResult
);

// Local author withdrawal, original Managed File and CAP_NET_ADMIN required.
nix::ioctl_write_ptr!(
    sl_security_negotiation_cancel,
    SL_MAGIC,
    0xd4,
    slk_protocol::SleSecurityNegotiationCancel
);

// Original Managed File, admin and original numeric prompt required.
nix::ioctl_write_ptr!(
    sl_security_numeric_confirm,
    SL_MAGIC,
    0xd5,
    slk_protocol::SleSecurityNumericConfirm
);
