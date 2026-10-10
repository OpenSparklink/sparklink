/// SparkLink ioctl magic number: 'S' (0x53)
pub const SL_MAGIC: u8 = b'S';

// ----- Device Management (0x01 - 0x08) -----

nix::ioctl_none!(sl_dev_register, SL_MAGIC, 0x01);
nix::ioctl_write_int!(sl_dev_unregister, SL_MAGIC, 0x02);
nix::ioctl_read!(sl_dev_count, SL_MAGIC, 0x03, u32);
nix::ioctl_read!(sl_dev_info, SL_MAGIC, 0x04, super::SciDevInfo);
nix::ioctl_write_int!(sl_dev_switch, SL_MAGIC, 0x05);
nix::ioctl_read!(sl_dev_list, SL_MAGIC, 0x06, u16);
nix::ioctl_write_ptr!(sl_dev_select, SL_MAGIC, 0x07, i16);
nix::ioctl_read!(sl_dev_get_active, SL_MAGIC, 0x08, u16);

// ----- Advertising (0x10 - 0x1B) -----

nix::ioctl_write_ptr!(sl_start_adv, SL_MAGIC, 0x10, super::SleAdvParams);
nix::ioctl_none!(sl_stop_adv, SL_MAGIC, 0x11);
nix::ioctl_write_ptr!(sl_start_scan, SL_MAGIC, 0x12, super::SleScanParams);
nix::ioctl_none!(sl_stop_scan, SL_MAGIC, 0x13);
nix::ioctl_write_ptr!(sl_ext_adv_configure, SL_MAGIC, 0x14, super::SleExtAdvConfig);
nix::ioctl_write_ptr!(sl_ext_adv_set_data, SL_MAGIC, 0x15, super::SleExtAdvData);
nix::ioctl_write_int!(sl_ext_adv_enable, SL_MAGIC, 0x16);
nix::ioctl_write_int!(sl_ext_adv_disable, SL_MAGIC, 0x17);
nix::ioctl_write_int!(sl_ext_adv_remove, SL_MAGIC, 0x18);
nix::ioctl_readwrite!(sl_ext_adv_info, SL_MAGIC, 0x19, super::SleExtAdvInfo);
nix::ioctl_write_ptr!(
    sl_ext_adv_enable_ex,
    SL_MAGIC,
    0x1A,
    super::SleExtAdvEnableParams
);
nix::ioctl_none!(sl_ext_adv_tick, SL_MAGIC, 0x1B);
nix::ioctl_write_ptr!(
    sl_ext_adv_set_scan_rsp,
    SL_MAGIC,
    0x1C,
    super::SleExtAdvData
);

// ----- Scan Injection / Filtering (0x20 - 0x24) -----

nix::ioctl_write_ptr!(sl_inject_adv, SL_MAGIC, 0x20, super::SleInjectAdv);
nix::ioctl_none!(sl_scan_result_count, SL_MAGIC, 0x21);
nix::ioctl_write_ptr!(sl_inject_raw_adv, SL_MAGIC, 0x22, super::SleInjectRawAdv);
nix::ioctl_write_ptr!(sl_set_scan_filter, SL_MAGIC, 0x23, super::SleScanFilter);
nix::ioctl_none!(sl_clear_scan_filter, SL_MAGIC, 0x24);

// ----- Connection Management (0x30 - 0x3F) -----

nix::ioctl_write_ptr!(sl_connect, SL_MAGIC, 0x30, super::SleConnectParams);
nix::ioctl_write_int!(sl_disconnect, SL_MAGIC, 0x31);
nix::ioctl_readwrite!(sl_conn_info, SL_MAGIC, 0x32, super::SleConnInfo);
nix::ioctl_write_ptr!(sl_conn_send, SL_MAGIC, 0x33, super::SleConnData);
nix::ioctl_readwrite!(sl_conn_recv, SL_MAGIC, 0x34, super::SleConnData);
nix::ioctl_write_ptr!(
    sl_inject_conn_resp,
    SL_MAGIC,
    0x35,
    super::SleInjectConnResp
);
nix::ioctl_write_ptr!(sl_inject_conn_data, SL_MAGIC, 0x36, super::SleConnData);
nix::ioctl_none!(sl_conn_count, SL_MAGIC, 0x37);
nix::ioctl_read!(sl_conn_list, SL_MAGIC, 0x38, super::SleConnList);
nix::ioctl_write_ptr!(sl_set_conn_mtu, SL_MAGIC, 0x39, super::SleConnMtuParams);

// ----- AFH (0x3A - 0x3F) -----

nix::ioctl_write_ptr!(sl_afh_set_map, SL_MAGIC, 0x3A, super::SleAfhMapParams);
nix::ioctl_readwrite!(sl_afh_get_map, SL_MAGIC, 0x3B, super::SleAfhMapParams);
nix::ioctl_write_ptr!(sl_afh_report_rssi, SL_MAGIC, 0x3C, super::SleAfhRssiReport);
nix::ioctl_readwrite!(sl_afh_classify, SL_MAGIC, 0x3D, super::SleAfhClassifyParams);
nix::ioctl_readwrite!(sl_afh_hop_next, SL_MAGIC, 0x3E, super::SleAfhHopInfo);
nix::ioctl_write_ptr!(sl_afh_report_retx, SL_MAGIC, 0x3F, super::SleAfhRetxReport);

// ----- Security (0x40 - 0x4F) -----

nix::ioctl_write_ptr!(sl_sec_set_psk, SL_MAGIC, 0x40, super::SlePskParams);
nix::ioctl_write_ptr!(sl_sec_pair, SL_MAGIC, 0x41, super::SlePairParams);
nix::ioctl_read!(sl_sec_info, SL_MAGIC, 0x42, super::SleSecInfo);
nix::ioctl_none!(sl_sec_encrypt_on, SL_MAGIC, 0x43);
nix::ioctl_write_ptr!(sl_sec_sm3_test, SL_MAGIC, 0x44, super::SleHashTest);
nix::ioctl_write_ptr!(sl_sec_sm4_enc_test, SL_MAGIC, 0x45, super::SleConnData);
nix::ioctl_write_ptr!(sl_sec_sm4_dec_test, SL_MAGIC, 0x46, super::SleConnData);
nix::ioctl_readwrite!(
    sl_sec_sm4_block_test,
    SL_MAGIC,
    0x47,
    super::SleSm4BlockTest
);
nix::ioctl_readwrite!(sl_sec_hmac_test, SL_MAGIC, 0x48, super::SleHmacTest);
nix::ioctl_none!(sl_sec_reset, SL_MAGIC, 0x49);
nix::ioctl_read!(sl_sec_get_passkey, SL_MAGIC, 0x4A, u32);
nix::ioctl_none!(sl_sec_confirm_passkey, SL_MAGIC, 0x4B);
nix::ioctl_none!(sl_sec_reject_passkey, SL_MAGIC, 0x4C);
nix::ioctl_write_ptr!(sl_sec_set_oob, SL_MAGIC, 0x4D, super::SleOobData);
nix::ioctl_write_ptr!(sl_sec_input_passkey, SL_MAGIC, 0x4E, super::SlePasskeyInput);
nix::ioctl_write_ptr!(
    sl_sec_set_password,
    SL_MAGIC,
    0x4F,
    super::SlePasswordParams
);

// ----- SSAP Service (0x50 - 0x5F) -----

nix::ioctl_none!(sl_ssap_register_svc, SL_MAGIC, 0x50);
nix::ioctl_read!(sl_ssap_info, SL_MAGIC, 0x51, super::SsapSummary);
nix::ioctl_readwrite!(sl_ssap_read, SL_MAGIC, 0x52, super::SsapReadWrite);
nix::ioctl_write_ptr!(sl_ssap_write, SL_MAGIC, 0x53, super::SsapReadWrite);
nix::ioctl_read!(sl_ssap_find_svc, SL_MAGIC, 0x54, super::SsapServiceList);
nix::ioctl_write_int!(sl_ssap_notify, SL_MAGIC, 0x55);
nix::ioctl_read!(sl_ssap_dequeue_ntf, SL_MAGIC, 0x56, super::SsapNotification);
nix::ioctl_readwrite!(sl_ssap_add_svc, SL_MAGIC, 0x57, super::SsapAddService);
nix::ioctl_readwrite!(sl_ssap_add_prop, SL_MAGIC, 0x58, super::SsapAddProperty);
nix::ioctl_write_int!(sl_ssap_remove_svc, SL_MAGIC, 0x59);
nix::ioctl_write_ptr!(sl_ssap_exchange_info, SL_MAGIC, 0x5A, super::SsapRemoteCmd);
nix::ioctl_readwrite!(
    sl_ssap_remote_discover,
    SL_MAGIC,
    0x5B,
    super::SsapRemoteDiscover
);
nix::ioctl_readwrite!(
    sl_ssap_remote_read,
    SL_MAGIC,
    0x5C,
    super::SsapRemoteReadWrite
);
nix::ioctl_write_ptr!(
    sl_ssap_remote_write,
    SL_MAGIC,
    0x5D,
    super::SsapRemoteReadWrite
);
nix::ioctl_read!(
    sl_ssap_remote_event,
    SL_MAGIC,
    0x5E,
    super::SsapNotification
);
nix::ioctl_readwrite!(
    sl_ssap_call_method,
    SL_MAGIC,
    0x5F,
    super::SsapRemoteReadWrite
);
nix::ioctl_readwrite!(sl_ssap_find_by_uuid, SL_MAGIC, 0x6F, super::SsapUuidOp);
nix::ioctl_readwrite!(sl_ssap_read_by_uuid, SL_MAGIC, 0x72, super::SsapUuidOp);

// ----- Power Management (0x60 - 0x65) -----

nix::ioctl_read!(sl_pm_info, SL_MAGIC, 0x60, super::SlePmInfo);
nix::ioctl_write_ptr!(sl_pm_set_state, SL_MAGIC, 0x61, super::SlePmStateCmd);
nix::ioctl_write_ptr!(sl_pm_set_interval, SL_MAGIC, 0x62, super::SlePmInterval);
nix::ioctl_write_int!(sl_pm_force_active, SL_MAGIC, 0x63);
nix::ioctl_none!(sl_pm_tick, SL_MAGIC, 0x64);
nix::ioctl_none!(sl_pm_activity, SL_MAGIC, 0x65);

// ----- Sync Link (0x66 - 0x6E) -----

nix::ioctl_readwrite!(sl_sync_ucast_param, SL_MAGIC, 0x66, super::SleSyncCigConfig);
nix::ioctl_write_ptr!(
    sl_sync_ucast_create,
    SL_MAGIC,
    0x67,
    super::SleSyncCreateCmd
);
nix::ioctl_write_int!(sl_sync_ucast_remove, SL_MAGIC, 0x68);
nix::ioctl_readwrite!(sl_sync_mcast_param, SL_MAGIC, 0x69, super::SleSyncBigConfig);
nix::ioctl_write_ptr!(
    sl_sync_mcast_create,
    SL_MAGIC,
    0x6A,
    super::SleSyncCreateCmd
);
nix::ioctl_write_int!(sl_sync_mcast_remove, SL_MAGIC, 0x6B);
nix::ioctl_write_ptr!(
    sl_sync_datapath_cfg,
    SL_MAGIC,
    0x6C,
    super::SleSyncDatapathCmd
);
nix::ioctl_write_int!(sl_sync_datapath_remove, SL_MAGIC, 0x6D);
nix::ioctl_readwrite!(sl_sync_info, SL_MAGIC, 0x6E, super::SleSyncLinkInfo);

// ----- Event Queue (0x70 - 0x71) -----

nix::ioctl_none!(sl_event_count, SL_MAGIC, 0x70);
nix::ioctl_read!(sl_event_stats, SL_MAGIC, 0x71, super::SleEventStats);

// ----- DLI Controller (0x80 - 0x86) -----

nix::ioctl_read!(sl_dli_info, SL_MAGIC, 0x80, super::SleDliInfo);
nix::ioctl_none!(sl_usb_dev_count, SL_MAGIC, 0x81);
nix::ioctl_read!(sl_dli_poll_event, SL_MAGIC, 0x82, super::SleDliEvent);
nix::ioctl_none!(sl_dli_reset, SL_MAGIC, 0x83);
nix::ioctl_readwrite!(sl_dli_send_cmd, SL_MAGIC, 0x84, super::SleDliCmd);
nix::ioctl_read!(sl_mgmt_stats, SL_MAGIC, 0x85, super::SleMgmtStats);
nix::ioctl_read!(sl_subsys_stats, SL_MAGIC, 0x86, super::SleSubsysStats);
nix::ioctl_readwrite!(
    sl_controller_event_get,
    SL_MAGIC,
    0x87,
    super::SleControllerEventQuery
);

// ----- PHY Layer (0x90 - 0x97) -----

nix::ioctl_read!(sl_phy_info, SL_MAGIC, 0x90, super::SlePhyInfo);
nix::ioctl_write_ptr!(sl_phy_set_mcs, SL_MAGIC, 0x91, super::SlePhyMcsCmd);
nix::ioctl_write_ptr!(sl_phy_set_txpower, SL_MAGIC, 0x92, super::SlePhyTxPowerCmd);
nix::ioctl_readwrite!(sl_phy_mcs_select, SL_MAGIC, 0x93, super::SlePhyMcsSelect);
nix::ioctl_read!(sl_phy_hop_next, SL_MAGIC, 0x94, super::SlePhyHopInfo);
nix::ioctl_write_ptr!(sl_phy_set_bw, SL_MAGIC, 0x95, super::SlePhyBwCmd);
nix::ioctl_read!(sl_phy_get_sinr, SL_MAGIC, 0x96, super::SleSinrThresholds);
nix::ioctl_write_ptr!(sl_phy_set_sinr, SL_MAGIC, 0x97, super::SleSinrThresholds);

// ----- Capability / Connection Update (0x98 - 0x9B) -----

nix::ioctl_readwrite!(
    sl_conn_read_peer_features,
    SL_MAGIC,
    0x98,
    super::SleConnPeerCap
);
nix::ioctl_readwrite!(
    sl_conn_read_peer_version,
    SL_MAGIC,
    0x99,
    super::SleConnPeerCap
);
nix::ioctl_write_ptr!(
    sl_conn_update_params,
    SL_MAGIC,
    0x9A,
    super::SleConnParamUpdate
);
nix::ioctl_write_ptr!(sl_conn_phy_update, SL_MAGIC, 0x9B, super::SleConnPhyUpdate);

// ----- Role (0xA0 - 0xA1) -----

nix::ioctl_write_int!(sl_set_role, SL_MAGIC, 0xA0);
nix::ioctl_read!(sl_get_role, SL_MAGIC, 0xA1, u8);

// ----- RAL / RPA (0xB0 - 0xB7) -----

nix::ioctl_write_ptr!(sl_ral_add, SL_MAGIC, 0xB0, super::SleRalAddParams);
nix::ioctl_write_ptr!(sl_ral_remove, SL_MAGIC, 0xB1, super::SleRalRemoveParams);
nix::ioctl_none!(sl_ral_clear, SL_MAGIC, 0xB2);
nix::ioctl_read!(sl_ral_size, SL_MAGIC, 0xB3, u8);
nix::ioctl_readwrite!(
    sl_ral_read_peer_rpa,
    SL_MAGIC,
    0xB4,
    super::SleRalQueryParams
);
nix::ioctl_readwrite!(
    sl_ral_read_local_rpa,
    SL_MAGIC,
    0xB5,
    super::SleRalQueryParams
);
nix::ioctl_write_int!(sl_rpa_enable, SL_MAGIC, 0xB6);
nix::ioctl_write_int!(sl_rpa_set_timeout, SL_MAGIC, 0xB7);

// ----- Measurement (0xC0 - 0xC3) -----

nix::ioctl_read!(sl_meas_read_cap, SL_MAGIC, 0xC0, super::SleMeasCap);
nix::ioctl_write_ptr!(
    sl_meas_set_link_param,
    SL_MAGIC,
    0xC1,
    super::SleMeasLinkParam
);
nix::ioctl_write_ptr!(sl_meas_action, SL_MAGIC, 0xC2, super::SleMeasAction);
nix::ioctl_write_int!(sl_meas_enable, SL_MAGIC, 0xC3);

// Versioned per-registration typed discovery. Submit has no output copy.
nix::ioctl_write_ptr!(
    sl_discovery_submit,
    SL_MAGIC,
    0x88,
    super::SleDiscoverySubmit
);
nix::ioctl_readwrite!(
    sl_discovery_result,
    SL_MAGIC,
    0x89,
    super::SleDiscoveryResult
);

nix::ioctl_readwrite!(
    sl_controller_snapshot,
    SL_MAGIC,
    0x8a,
    super::SleControllerSnapshot
);

nix::ioctl_readwrite!(
    sl_management_acquire,
    SL_MAGIC,
    0x8b,
    super::SleManagementRequest
);
nix::ioctl_write_ptr!(
    sl_management_release,
    SL_MAGIC,
    0x8c,
    super::SleManagementRequest
);
nix::ioctl_readwrite!(
    sl_management_query,
    SL_MAGIC,
    0x8d,
    super::SleManagementQuery
);
nix::ioctl_readwrite!(sl_snoop_get, SL_MAGIC, 0x8e, super::SleSnoopQuery);

nix::ioctl_readwrite!(
    sl_discovery_timing,
    SL_MAGIC,
    0x8f,
    super::SleDiscoveryTiming
);

nix::ioctl_readwrite!(
    sl_diagnostic_result,
    SL_MAGIC,
    0xd0,
    super::SleDiagnosticResult
);
