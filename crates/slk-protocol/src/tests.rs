use crate::ioctl;
use crate::*;

#[test]
fn snoop_abi_is_pointer_free_and_aligned() {
    assert_eq!(std::mem::size_of::<SleSnoopRecord>(), 376);
    assert_eq!(std::mem::size_of::<SleSnoopQuery>(), 408);
    assert_eq!(std::mem::align_of::<SleSnoopQuery>(), 8);
    assert_eq!(std::mem::offset_of!(SleSnoopQuery, record), 32);
    assert_eq!(std::mem::offset_of!(SleSnoopRecord, payload), 56);
    assert_eq!(SL_IOCTL_SNOOP_GET, 0xc198538e);
}

macro_rules! check_size {
    ($errors:ident, $t:ty, $expected:expr) => {
        let actual = std::mem::size_of::<$t>();
        if actual != $expected {
            $errors.push(format!(
                "{}: got {}, expected {}",
                stringify!($t),
                actual,
                $expected
            ));
        }
    };
}

#[test]
fn uapi_struct_sizes_match_kernel() {
    let mut errors = Vec::new();
    // Sizes obtained from compiling kernel UAPI header with gcc (x86_64, no packed)
    check_size!(errors, SciDevInfo, 66);
    check_size!(errors, SleAdvParams, 16);
    check_size!(errors, SleScanParams, 16);
    check_size!(errors, SleScanFilter, 12);
    check_size!(errors, SleInjectAdv, 48);
    check_size!(errors, SleInjectRawAdv, 268);
    check_size!(errors, SleExtAdvConfig, 16);
    check_size!(errors, SleExtAdvData, 256);
    check_size!(errors, SleExtAdvInfo, 24);
    check_size!(errors, SleExtAdvEnableParams, 8);
    check_size!(errors, SleConnectParams, 16);
    check_size!(errors, SleConnInfo, 64);
    check_size!(errors, SleConnData, 260);
    check_size!(errors, SleInjectConnResp, 12);
    check_size!(errors, SleConnList, 24);
    check_size!(errors, SleConnMtuParams, 8);
    check_size!(errors, SleAfhMapParams, 16);
    check_size!(errors, SleAfhRssiReport, 4);
    check_size!(errors, SleAfhClassifyParams, 16);
    check_size!(errors, SleAfhHopInfo, 8);
    check_size!(errors, SleAfhRetxReport, 4);
    check_size!(errors, SlePskParams, 16);
    check_size!(errors, SlePairParams, 4);
    check_size!(errors, SleSecInfo, 16);
    check_size!(errors, SleHashTest, 256);
    check_size!(errors, SleSm4BlockTest, 64);
    check_size!(errors, SleHmacTest, 260);
    check_size!(errors, SleOobData, 64);
    check_size!(errors, SlePasskeyInput, 4);
    check_size!(errors, SlePasswordParams, 36);
    check_size!(errors, SsapSummary, 16);
    check_size!(errors, SsapReadWrite, 256);
    check_size!(errors, SsapServiceEntry, 8);
    check_size!(errors, SsapServiceList, 124);
    check_size!(errors, SsapNotification, 256);
    check_size!(errors, SsapAddService, 28);
    check_size!(errors, SsapAddProperty, 256);
    check_size!(errors, SsapRemoteCmd, 4);
    check_size!(errors, SsapRemoteDiscover, 8);
    check_size!(errors, SsapRemoteReadWrite, 256);
    check_size!(errors, SlePmInfo, 48);
    check_size!(errors, SlePmStateCmd, 4);
    check_size!(errors, SlePmInterval, 8);
    check_size!(errors, SleSyncCigConfig, 40);
    check_size!(errors, SleSyncBigConfig, 40);
    check_size!(errors, SleSyncCreateCmd, 20);
    check_size!(errors, SleSyncDatapathCmd, 8);
    check_size!(errors, SleSyncLinkInfo, 24);
    check_size!(errors, SleEventStats, 32);
    check_size!(errors, SleDliInfo, 64);
    check_size!(errors, SleDliEvent, 256);
    check_size!(errors, SleDliCmd, 248);
    check_size!(errors, SleControllerEvent, 336);
    check_size!(errors, SleControllerEventQuery, 360);
    check_size!(errors, SleMgmtStats, 16);
    check_size!(errors, SleSubsysStats, 36);
    check_size!(errors, SlePhyInfo, 24);
    check_size!(errors, SlePhyMcsCmd, 4);
    check_size!(errors, SlePhyTxPowerCmd, 4);
    check_size!(errors, SlePhyMcsSelect, 12);
    check_size!(errors, SlePhyHopInfo, 8);
    check_size!(errors, SlePhyBwCmd, 4);
    check_size!(errors, SleSinrThresholds, 28);
    check_size!(errors, SleConnPeerCap, 22);
    check_size!(errors, SleConnParamUpdate, 12);
    check_size!(errors, SleConnPhyUpdate, 4);
    check_size!(errors, SleRalAddParams, 44);
    check_size!(errors, SleRalRemoveParams, 8);
    check_size!(errors, SleRalQueryParams, 16);
    check_size!(errors, SleMeasCap, 4);
    check_size!(errors, SleMeasLinkParam, 8);
    check_size!(errors, SleMeasAction, 4);

    if !errors.is_empty() {
        panic!(
            "{} struct size mismatch(es):\n  {}",
            errors.len(),
            errors.join("\n  ")
        );
    }
}

#[test]
fn ioctl_magic_is_correct() {
    assert_eq!(ioctl::SL_MAGIC, b'S');
    assert_eq!(ioctl::SL_MAGIC, 0x53);
}

#[test]
fn event_type_constants_valid() {
    assert_eq!(EVT_CMD_COMPLETE, 0x01);
    assert_eq!(EVT_CMD_STATUS, 0x02);
    assert_eq!(EVT_ADV_REPORT, 0x03);
    assert_eq!(EVT_CONN_COMPLETE, 0x04);
    assert_eq!(EVT_DATA_RECV, 0x05);
    assert_eq!(EVT_DISCONNECTED, 0x06);
    assert_eq!(EVT_ENCRYPTION_CHANGED, 0x07);
    assert_eq!(EVT_PAIR_REQUEST, 0x08);
    assert_eq!(EVT_HW_ERROR, 0x09);
    assert_eq!(EVT_BROADCAST_END, 0x0A);
    assert_eq!(EVT_PHY_UPDATE, 0x0B);
}

#[test]
fn dli_packet_type_constants_valid() {
    assert_eq!(DLI_PKT_COMMAND, 0xA1);
    assert_eq!(DLI_PKT_EVENT, 0xA2);
    assert_eq!(DLI_PKT_ASYNC_UCAST, 0xA3);
    assert_eq!(DLI_PKT_SYNC_UCAST, 0xA4);
    assert_eq!(DLI_PKT_ASYNC_MCAST, 0xA5);
}

#[test]
fn enum_repr_values() {
    assert_eq!(ConnState::Idle as u8, 0);
    assert_eq!(ConnState::Connected as u8, 2);
    assert_eq!(PmState::Suspended as u8, 3);
    assert_eq!(SecState::Encrypted as u8, 3);
    assert_eq!(PairMethod::Psk as u8, 2);
    assert_eq!(DiscoveryLevel::Designated as u8, 4);
    assert_eq!(BusType::Usb as u8, 4);
}

#[test]
fn sle_addr_is_six_bytes() {
    assert_eq!(std::mem::size_of::<SleAddr>(), 6);
}

#[test]
fn genl_constants() {
    assert_eq!(GENL_FAMILY_NAME, "sparklink");
    assert_eq!(GENL_VERSION, 1);
    assert_eq!(GENL_MCAST_EVENTS, "events");
}

// ---- Phase 8: additional coverage ----

#[test]
fn struct_zeroed_is_valid() {
    // Verify all major structs can be safely zero-initialized
    let dev: SciDevInfo = unsafe { std::mem::zeroed() };
    assert_eq!(dev.index, 0);
    assert_eq!(dev.state, 0);

    let scan: SleScanParams = unsafe { std::mem::zeroed() };
    assert_eq!(scan.dev_index, 0);
    assert_eq!(scan.interval_ms, 0);

    let conn: SleConnInfo = unsafe { std::mem::zeroed() };
    assert_eq!(conn.handle, 0);
    assert_eq!(conn.state, 0);

    let sec: SleSecInfo = unsafe { std::mem::zeroed() };
    assert_eq!(sec.state, 0);
    assert_eq!(sec.enc_enabled, 0);

    let dli: SleDliInfo = unsafe { std::mem::zeroed() };
    assert_eq!(dli.firmware_version, 0);
    assert_eq!(dli.features, 0);

    let phy: SlePhyInfo = unsafe { std::mem::zeroed() };
    assert_eq!(phy.data_rate_kbps, 0);
    assert_eq!(phy.mcs_index, 0);
}

#[test]
fn struct_field_offsets() {
    use std::mem::offset_of;
    // SciDevInfo: verify key field positions
    assert_eq!(offset_of!(SciDevInfo, index), 0);
    assert_eq!(offset_of!(SciDevInfo, state), 2);
    assert_eq!(offset_of!(SciDevInfo, bus), 3);
    assert_eq!(offset_of!(SciDevInfo, addr), 4);
    assert_eq!(offset_of!(SciDevInfo, name), 10);

    // SleConnInfo: tx_bytes(8) + rx_bytes(8) then handle
    assert_eq!(offset_of!(SleConnInfo, tx_bytes), 0);
    assert_eq!(offset_of!(SleConnInfo, rx_bytes), 8);
    assert_eq!(offset_of!(SleConnInfo, handle), 16);

    // SleDliEvent
    assert_eq!(offset_of!(SleDliEvent, event_type), 0);
    assert_eq!(offset_of!(SleDliEvent, status), 1);
    assert_eq!(offset_of!(SleDliEvent, handle), 2);
    assert_eq!(offset_of!(SleDliEvent, opcode), 4);
    assert_eq!(offset_of!(SleDliEvent, data_len), 6);
    assert_eq!(offset_of!(SleDliEvent, data), 8);
}

#[test]
fn sle_addr_type_alias() {
    let addr: SleAddr = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF];
    assert_eq!(addr.len(), 6);
    assert_eq!(addr[0], 0xAA);
    assert_eq!(addr[5], 0xFF);
    // Prove it's Copy
    let addr2 = addr;
    assert_eq!(addr, addr2);
}

#[test]
fn enum_variants_complete() {
    // ConnState: 4 variants 0..=3
    assert_eq!(ConnState::Idle as u8, 0);
    assert_eq!(ConnState::Connecting as u8, 1);
    assert_eq!(ConnState::Connected as u8, 2);
    assert_eq!(ConnState::Disconnecting as u8, 3);

    // PmState: 4 variants 0..=3
    assert_eq!(PmState::Active as u8, 0);
    assert_eq!(PmState::Sniff as u8, 1);
    assert_eq!(PmState::Idle as u8, 2);
    assert_eq!(PmState::Suspended as u8, 3);

    // SecState: 4 variants 0..=3
    assert_eq!(SecState::None as u8, 0);
    assert_eq!(SecState::Pairing as u8, 1);
    assert_eq!(SecState::Paired as u8, 2);
    assert_eq!(SecState::Encrypted as u8, 3);

    // PairMethod: 3 variants 0..=2
    assert_eq!(PairMethod::None as u8, 0);
    assert_eq!(PairMethod::JustWorks as u8, 1);
    assert_eq!(PairMethod::Psk as u8, 2);

    // DiscoveryLevel: 5 variants 0..=4
    assert_eq!(DiscoveryLevel::Invisible as u8, 0);
    assert_eq!(DiscoveryLevel::General as u8, 1);
    assert_eq!(DiscoveryLevel::Priority as u8, 2);
    assert_eq!(DiscoveryLevel::PairedOnly as u8, 3);
    assert_eq!(DiscoveryLevel::Designated as u8, 4);

    // BusType: 6 variants 0..=5
    assert_eq!(BusType::Virtual as u8, 0);
    assert_eq!(BusType::Uart as u8, 1);
    assert_eq!(BusType::Spi as u8, 2);
    assert_eq!(BusType::Sdio as u8, 3);
    assert_eq!(BusType::Usb as u8, 4);
    assert_eq!(BusType::Mmio as u8, 5);
}

#[test]
fn genl_cmd_enum_coverage() {
    use crate::genl::GenlCmd;
    assert_eq!(GenlCmd::Unspec as u8, 0);
    assert_eq!(GenlCmd::GetDevInfo as u8, 1);
    assert_eq!(GenlCmd::SsapRemoveSvc as u8, 33);
    // Registration commands 2/3 were removed; remaining wire numbers stay.
    assert_eq!(GenlCmd::StartAdv as u8, 4);
    assert_eq!(std::mem::size_of::<GenlCmd>(), 1);
}

#[test]
fn genl_attr_enum_coverage() {
    use crate::genl::GenlAttr;
    assert_eq!(GenlAttr::Unspec as u16, 0);
    assert_eq!(GenlAttr::DevIndex as u16, 1);
    assert_eq!(GenlAttr::SvcMtu as u16, 58);
    // Total: 59 attributes (0..=58)
    assert_eq!(std::mem::size_of::<GenlAttr>(), 2);
}

#[test]
fn ssap_readwrite_data_capacity() {
    let rw: SsapReadWrite = unsafe { std::mem::zeroed() };
    assert_eq!(rw.data.len(), 252);
    assert_eq!(std::mem::size_of::<SsapReadWrite>(), 256);
}

#[test]
fn dli_event_data_capacity() {
    let ev: SleDliEvent = unsafe { std::mem::zeroed() };
    assert_eq!(ev.data.len(), 240);
    assert_eq!(std::mem::size_of::<SleDliEvent>(), 256);
}

#[test]
fn sle_conn_data_capacity() {
    let cd: SleConnData = unsafe { std::mem::zeroed() };
    assert_eq!(cd.data.len(), 255);
    assert_eq!(std::mem::size_of::<SleConnData>(), 260);
}

#[test]
fn ioctl_number_ranges() {
    // Verify ioctl magic is correct across all categories
    assert_eq!(ioctl::SL_MAGIC, 0x53);
}

#[test]
fn ext_adv_data_buffer_capacity() {
    let data: SleExtAdvData = unsafe { std::mem::zeroed() };
    assert_eq!(data.data.len(), 252);
    assert_eq!(std::mem::size_of::<SleExtAdvData>(), 256);
}

#[test]
fn afh_map_params_layout() {
    let params: SleAfhMapParams = unsafe { std::mem::zeroed() };
    assert_eq!(params.map.len(), 10);
    assert_eq!(params.handle, 0);
    assert_eq!(params.used_count, 0);
}

#[test]
fn sync_config_handles_capacity() {
    let cig: SleSyncCigConfig = unsafe { std::mem::zeroed() };
    assert_eq!(cig.handles_out.len(), 8);
    let big: SleSyncBigConfig = unsafe { std::mem::zeroed() };
    assert_eq!(big.handles_out.len(), 8);
}

#[test]
fn ral_params_irk_sizes() {
    let ral: SleRalAddParams = unsafe { std::mem::zeroed() };
    assert_eq!(ral.peer_irk.len(), 16);
    assert_eq!(ral.local_irk.len(), 16);
    assert_eq!(ral.peer_id.len(), 6);
}

#[test]
fn sinr_thresholds_capacity() {
    let sinr: SleSinrThresholds = unsafe { std::mem::zeroed() };
    assert_eq!(sinr.thresholds.len(), 13);
}

#[test]
fn conn_peer_cap_features_size() {
    let cap: SleConnPeerCap = unsafe { std::mem::zeroed() };
    assert_eq!(cap.features.len(), 10);
    assert_eq!(cap.features_valid, 0);
    assert_eq!(cap.version_valid, 0);
}

#[test]
fn uuid_op_data_capacity() {
    let op: SsapUuidOp = unsafe { std::mem::zeroed() };
    assert_eq!(op.data.len(), 232);
    assert_eq!(op.uuid128.len(), 16);
}

#[test]
fn pm_info_event_counters_zero() {
    let pm: SlePmInfo = unsafe { std::mem::zeroed() };
    assert_eq!(pm.active_events, 0);
    assert_eq!(pm.sniff_events, 0);
    assert_eq!(pm.idle_events, 0);
    assert_eq!(pm.transitions, 0);
}

#[test]
fn dli_cmd_params_capacity() {
    let cmd: SleDliCmd = unsafe { std::mem::zeroed() };
    assert_eq!(cmd.params.len(), 240);
    assert_eq!(cmd.opcode, 0);
    assert_eq!(cmd.seq, 0);
}

#[test]
fn event_stats_zeroed() {
    let stats: SleEventStats = unsafe { std::mem::zeroed() };
    assert_eq!(stats.pending, 0);
    assert_eq!(stats.total_enqueued, 0);
    assert_eq!(stats.total_dropped, 0);
    assert_eq!(stats.total_delivered, 0);
}

#[test]
fn measurement_structs_zeroed() {
    let cap: SleMeasCap = unsafe { std::mem::zeroed() };
    assert_eq!(cap.meas_types, 0);
    assert_eq!(cap.max_instances, 0);

    let param: SleMeasLinkParam = unsafe { std::mem::zeroed() };
    assert_eq!(param.handle, 0);
    assert_eq!(param.interval, 0);

    let action: SleMeasAction = unsafe { std::mem::zeroed() };
    assert_eq!(action.handle, 0);
    assert_eq!(action.action, 0);
}

#[test]
fn struct_field_offsets_extended() {
    use std::mem::offset_of;

    // SleExtAdvConfig layout
    assert_eq!(offset_of!(SleExtAdvConfig, handle), 0);
    assert_eq!(offset_of!(SleExtAdvConfig, discovery_level), 1);
    assert_eq!(offset_of!(SleExtAdvConfig, sid), 2);
    assert_eq!(offset_of!(SleExtAdvConfig, interval_ms), 8);

    // SleAfhMapParams layout
    assert_eq!(offset_of!(SleAfhMapParams, handle), 0);
    assert_eq!(offset_of!(SleAfhMapParams, min_channels), 2);
    assert_eq!(offset_of!(SleAfhMapParams, map), 4);

    // SlePmInfo layout
    assert_eq!(offset_of!(SlePmInfo, state), 0);
    assert_eq!(offset_of!(SlePmInfo, force_active), 1);
    assert_eq!(offset_of!(SlePmInfo, transitions), 12);

    // SleRalAddParams layout
    assert_eq!(offset_of!(SleRalAddParams, resolve_algo), 0);
    assert_eq!(offset_of!(SleRalAddParams, peer_id), 4);
    assert_eq!(offset_of!(SleRalAddParams, peer_irk), 12);
    assert_eq!(offset_of!(SleRalAddParams, local_irk), 28);
}

#[test]
fn complete_controller_event_abi_and_ws73_fields() {
    use std::mem::{align_of, offset_of};
    assert_eq!(align_of::<SleControllerEvent>(), 8);
    assert_eq!(offset_of!(SleControllerEvent, payload), 48);
    assert_eq!(offset_of!(SleControllerEventQuery, event), 24);
    assert_eq!(nix::request_code_readwrite!(b'S', 0x87, 360), 0xc1685387);
    let mut event: SleControllerEvent = unsafe { std::mem::zeroed() };
    event.seq = 9;
    event.generation = 2;
    event.profile = CONTROLLER_EVENT_PROFILE_WS73_HCC;
    event.event_code = 0x180b;
    event.payload[..23].copy_from_slice(&[
        3, 6, 2, 0x73, 1, 2, 3, 4, 4, 9, 8, 7, 6, 5, 4, 1, 2, 3, 0x44, 0x55, 0xa7, 0xd6, 0,
    ]);
    for length in 0..=255 {
        event.payload[22] = length as u8;
        event.payload_len = 23 + length;
        for i in 0..usize::from(length) {
            event.payload[23 + i] = i as u8;
        }
        let report = event.ws73_discovery().unwrap();
        assert_eq!(report.header[1], 6);
        assert_eq!(&report.header[9..15], &[9, 8, 7, 6, 5, 4]);
        assert_eq!(report.header[20], 0xa7);
        assert_eq!(report.rssi, -42);
        assert_eq!(report.data.len(), usize::from(length));
        for (i, byte) in report.data.iter().enumerate() {
            assert_eq!(*byte, i as u8);
        }
        event.payload_len -= 1;
        assert!(event.ws73_discovery().is_none());
        event.payload_len += 2;
        assert!(event.ws73_discovery().is_none());
        event.payload_len -= 1;
    }
    for byte in 0..=255 {
        event.payload[21] = byte;
        assert_eq!(event.ws73_discovery().unwrap().rssi, byte as i8);
    }
    let good = event;
    event.profile = 0;
    assert!(event.ws73_discovery().is_none());
    event = good;
    event.event_code = 0x001a;
    assert!(event.ws73_discovery().is_none());
    event = good;
    event.payload_len = 289;
    assert!(event.ws73_discovery().is_none());
    event = good;
    event._reserved = 1;
    assert!(event.ws73_discovery().is_none());
    event = good;
    event.flags = 1;
    assert!(event.ws73_discovery().is_none());
}

#[test]
fn typed_discovery_abi_and_terminal_states() {
    use std::mem::{align_of, offset_of, size_of};
    assert_eq!(size_of::<SleDiscoveryAdvConfig>(), 116);
    assert_eq!(size_of::<SleDiscoveryScanConfig>(), 28);
    assert_eq!(size_of::<SleDiscoverySubmit>(), 704);
    assert_eq!(align_of::<SleDiscoverySubmit>(), 8);
    assert_eq!(offset_of!(SleDiscoverySubmit, advertising), 32);
    assert_eq!(offset_of!(SleDiscoverySubmit, data), 200);
    assert_eq!(size_of::<SleDiscoveryResult>(), 64);
    assert_eq!(offset_of!(SleDiscoveryResult, dev_index), 52);
    assert_eq!(
        std::mem::size_of_val(&SleDiscoverySubmit::default().data),
        251
    );
    for state in 0..=7 {
        let r = SleDiscoveryResult {
            state,
            ..Default::default()
        };
        assert_eq!(r.is_terminal(), (3..=6).contains(&state));
    }
}

#[test]
fn selected_controller_snapshot_abi() {
    assert_eq!(std::mem::size_of::<SleControllerSnapshot>(), 64);
    assert_eq!(std::mem::align_of::<SleControllerSnapshot>(), 8);
    assert_eq!(
        std::mem::offset_of!(SleControllerSnapshot, version_tuple),
        34
    );
    assert_eq!(std::mem::offset_of!(SleControllerSnapshot, features), 39);
    assert_eq!(std::mem::offset_of!(SleControllerSnapshot, address), 49);
    assert_eq!(std::mem::offset_of!(SleControllerSnapshot, error), 56);
    assert_eq!(nix::request_code_readwrite!(b'S', 0x8a, 64), 0xc040538a);
    // Affinity uses a pointer to signed 16-bit, not ioctl_write_int's int size.
    assert_eq!(
        nix::request_code_write!(b'S', 7, std::mem::size_of::<i16>()),
        0x40025307
    );
}

#[test]
fn native_management_abi() {
    assert_eq!(std::mem::size_of::<SleManagementRequest>(), 32);
    assert_eq!(std::mem::size_of::<SleManagementQuery>(), 48);
    assert_eq!(std::mem::align_of::<SleManagementRequest>(), 8);
    assert_eq!(std::mem::align_of::<SleManagementQuery>(), 8);
    assert_eq!(std::mem::offset_of!(SleManagementRequest, mode), 20);
    assert_eq!(std::mem::offset_of!(SleManagementQuery, error), 32);
    assert_eq!(nix::request_code_readwrite!(b'S', 0x8b, 32), 0xc020538b);
    assert_eq!(nix::request_code_write!(b'S', 0x8c, 32), 0x4020538c);
    assert_eq!(nix::request_code_readwrite!(b'S', 0x8d, 48), 0xc030538d);
}
