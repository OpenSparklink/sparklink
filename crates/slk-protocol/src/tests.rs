#[cfg(test)]
mod tests {
    use crate::*;
    use crate::ioctl;

    macro_rules! check_size {
        ($errors:ident, $t:ty, $expected:expr) => {
            let actual = std::mem::size_of::<$t>();
            if actual != $expected {
                $errors.push(format!(
                    "{}: got {}, expected {}",
                    stringify!($t), actual, $expected
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
        check_size!(errors, SleConnInfo, 56);
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
        assert_eq!(EVT_CONN_STATE, 0x01);
        assert_eq!(EVT_ADV_REPORT, 0x02);
        assert_eq!(EVT_DATA_RECV, 0x03);
        assert_eq!(EVT_SEC_CHANGED, 0x04);
        assert_eq!(EVT_PWR_CHANGED, 0x05);
        assert_eq!(EVT_HW_ERROR, 0x06);
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
}
