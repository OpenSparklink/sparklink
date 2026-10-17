/* Historical generated C layouts from6841e4e, tests only.
 * Current SDK must not declare these types. Kept with private Python fixtures
 * for raw-kernel/Rust/C layout,32-bit static and bounded-write regressions.
 * No function, protocol Engine or supported runtime API is defined here.
 */
#ifndef SPARKLINK_RETIRED_TEST_LAYOUTS_H
#define SPARKLINK_RETIRED_TEST_LAYOUTS_H
#include <stdint.h>
/* SleAddr is supplied by the actual current Native header. */
typedef struct SleScanParams {
    uint16_t dev_index;
    uint16_t window_ms;
    uint16_t interval_ms;
    uint8_t filter_discovery_level;
    uint8_t _reserved[9];
} SleScanParams;

typedef struct SleConnectParams {
    SleAddr peer_addr;
    uint8_t gt_role;
    uint8_t bandwidth;
    uint8_t mcs_index;
    uint8_t _pad;
    uint16_t timeout_10ms;
    uint8_t _reserved[4];
} SleConnectParams;

typedef struct SleConnInfo {
    uint64_t tx_bytes;
    uint64_t rx_bytes;
    uint16_t handle;
    uint16_t event_group_period;
    uint16_t supervision_timeout;
    uint16_t tx_pending;
    uint16_t rx_pending;
    uint8_t state;
    SleAddr peer_addr;
    uint8_t local_role;
    uint8_t bandwidth_mhz;
    uint8_t mcs_index;
    uint8_t tx_seq;
    uint8_t rx_seq;
    uint16_t data_mtu;
    uint16_t data_mps;
    uint16_t svc_mtu;
    uint8_t data_mode;
    uint16_t smtc_tx_credits;
    uint16_t smtc_rx_credits;
    uint16_t dudtc_tx_credits;
    uint16_t dudtc_rx_credits;
} SleConnInfo;

typedef struct SleDliInfo {
    uint8_t bus;
    uint8_t _pad[3];
    uint32_t firmware_version;
    uint64_t features;
    uint8_t max_connections;
    uint8_t max_adv_sets;
    uint8_t transport_modes;
    uint8_t measurement_cap;
    uint16_t max_mtu;
    uint16_t max_mps;
    uint16_t security_cap;
    uint16_t features_ext;
    uint8_t name[32];
    uint8_t _reserved[4];
} SleDliInfo;

typedef struct SlePhyInfo {
    uint8_t mcs_index;
    uint8_t bandwidth_mhz;
    uint8_t pilot_density;
    int8_t tx_power_dbm;
    uint8_t mimo_mode;
    uint8_t num_tx_ant;
    uint8_t num_rx_ant;
    uint8_t ofdm;
    uint32_t data_rate_kbps;
    uint8_t hop_channel;
    uint8_t hop_increment;
    uint8_t hop_used_channels;
    uint8_t _pad;
    uint8_t modulation;
    uint8_t code_rate_num;
    uint8_t code_rate_den;
    uint8_t _reserved[5];
} SlePhyInfo;
#endif
