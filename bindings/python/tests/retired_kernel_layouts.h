/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact pre-retirement Kernel4b6 declarations; historical witnesses, not UAPI. */
#ifndef SPARKLINK_TEST_RETIRED_KERNEL_LAYOUTS_H
#define SPARKLINK_TEST_RETIRED_KERNEL_LAYOUTS_H
#include <linux/types.h>
struct sl_test_retired_sle_scan_params {
	__u16 dev_index;
	__u16 window_ms;
	__u16 interval_ms;
	__u8  filter_discovery_level;
	__u8  _reserved[9];
};
struct sl_test_retired_sle_connect_params {
	__u8  peer_addr[6];
	__u8  gt_role;
	__u8  bandwidth;
	__u8  mcs_index;
	__u8  _pad;
	__u16 timeout_10ms;
	__u8  _reserved[4];
};
struct sl_test_retired_sle_conn_info {
	__u64 tx_bytes;
	__u64 rx_bytes;
	__u16 handle;
	__u16 event_group_period;
	__u16 supervision_timeout;
	__u16 tx_pending;
	__u16 rx_pending;
	__u8  state;
	__u8  peer_addr[6];
	__u8  local_role;
	__u8  bandwidth_mhz;
	__u8  mcs_index;
	__u8  tx_seq;
	__u8  rx_seq;
	__u16 data_mtu;
	__u16 data_mps;
	__u16 svc_mtu;
	__u8  data_mode;
	__u16 smtc_tx_credits;
	__u16 smtc_rx_credits;
	__u16 dudtc_tx_credits;
	__u16 dudtc_rx_credits;
};
struct sl_test_retired_sle_dli_info {
	__u8  bus;
	__u8  _pad[3];
	__u32 firmware_version;
	__u64 features;
	__u8  max_connections;
	__u8  max_adv_sets;
	__u8  transport_modes;
	__u8  measurement_cap;
	__u16 max_mtu;
	__u16 max_mps;
	__u16 security_cap;
	__u16 features_ext;
	__u8  name[32];
	__u8  _reserved[4];
};
struct sl_test_retired_sle_phy_info {
	__u8  mcs_index;
	__u8  bandwidth_mhz;
	__u8  pilot_density;
	__s8  tx_power_dbm;
	__u8  mimo_mode;
	__u8  num_tx_ant;
	__u8  num_rx_ant;
	__u8  ofdm;
	__u32 data_rate_kbps;
	__u8  hop_channel;
	__u8  hop_increment;
	__u8  hop_used_channels;
	__u8  _pad;
	__u8  modulation;
	__u8  code_rate_num;
	__u8  code_rate_den;
	__u8  _reserved[5];
};
#endif
