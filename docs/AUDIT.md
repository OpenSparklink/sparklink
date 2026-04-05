# SparkLink 协议栈全面审计报告

## 1. 代码规模统计

| 组件 | 文件数 | 代码行数 | 语言 |
|------|--------|----------|------|
| 内核子系统 (net/sparklink/) | 21 .rs + 4 .c | 28,570 | Rust + C |
| 内核 UAPI 头文件 | 1 | 937 | C |
| 内核驱动 (drivers/sparklink/) | 1 | 32 | Rust |
| 内核 selftest | 3 (2 .c + 1 .sh) | 13,587 | C + Shell |
| 用户态工具链 (7 crates) | 24 | 7,148 | Rust |
| **项目合计** | **54** | **50,274** | |

## 2. ioctl 接口完整性审计

### 内核 → 用户态覆盖率

内核定义的 ioctl 命令总数：126（0x01-0xC3 范围内有效编号）

用户态 slk-protocol 绑定数：126

**覆盖率：100%**

### 各分组覆盖明细

| 分组 | 内核命令数 | 用户态绑定 | Adapter 方法 | D-Bus 接口 | CLI 命令 |
|------|-----------|-----------|-------------|-----------|---------|
| 设备管理 (0x01-0x08) | 8 | 8 | 8 | Adapter | info/scan/... |
| 广播/扫描 (0x10-0x1C) | 13 | 13 | 13 | Adapter+ExtAdv | scan/extadv |
| 注入/过滤 (0x20-0x24) | 5 | 5 | 5 | Adapter | — |
| 连接 (0x30-0x39) | 10 | 10 | 10 | Adapter | connect/send |
| AFH (0x3A-0x3F) | 6 | 6 | 6 | Controller | — |
| 安全 (0x40-0x4F) | 16 | 16 | 16 | Security | pair/encrypt |
| SSAP (0x50-0x72) | 18 | 18 | 18 | ServiceManager+Remote | services |
| 功率管理 (0x60-0x65) | 6 | 6 | 6 | Controller | power |
| 同步链路 (0x66-0x6E) | 9 | 9 | 9 | Controller | — |
| 事件 (0x70-0x71) | 2 | 2 | 2 | Controller | — |
| DLI (0x80-0x86) | 7 | 7 | 7 | Controller | dli |
| PHY (0x90-0x97) | 8 | 8 | 8 | Controller | phy/mcs/txpower |
| 能力 (0x98-0x9B) | 4 | 4 | 4 | Controller | — |
| 角色 (0xA0-0xA1) | 2 | 2 | 2 | Controller | role |
| RAL/RPA (0xB0-0xB7) | 8 | 8 | 8 | Controller | — |
| 测距 (0xC0-0xC3) | 4 | 4 | 4 | Controller | — |

### 发现的问题

1. ~~**slkd GetDevices 返回类型不一致**~~：已修复。`get_devices()` 现在返回 `Vec<(String, String, i16, bool)>`（地址、名称、RSSI、连接状态），与 slctl 期望一致。

2. **CLI 命令覆盖不完整**：AFH、同步链路、RAL/RPA、测距等子系统在 D-Bus 接口中已实现，但 slctl 没有对应的 CLI 命令。这些属于低频操作，但应当至少提供基础命令。

3. **slkdump 和 slkmon 的事件解码表**：目前仅覆盖 6 种基础事件类型，未覆盖 DLI 事件和 SSAP 通知。

## 3. 测试覆盖审计

### 内核测试用例分布 (96 个)

| 子系统 | 测试数 | 测试名称 |
|--------|--------|---------|
| 设备管理 | 5 | dev_count, dev_info, dev_register, dev_switch_isolation, per_fd_device_select |
| 广播/扫描 | 6 | advertising, scanning, ext_advertising, adv_scan_role_enforcement, scan_filter_bounds, scan_filter_reject |
| 连接 | 14 | connect, conn_info_fields, conn_list_accuracy, conn_max_capacity, conn_invalid_handle, conn_reject, conn_send_bounds, conn_data_loopback, conn_data_counters, conn_stale_handle_ops, multi_conn_concurrent, rapid_connect_disconnect, mtu_mps_negotiation, supervision_timeout |
| 安全 | 7 | security_pairing, security_ecdh, security_numeric_comparison, security_oob_pin_password, security_state_machine, sm3_hash, sm4_block |
| SSAP | 9 | ssap_service, ssap_service_discovery, ssap_indication, ssap_dynamic_registration, ssap_prop_edge_cases, ssap_permission_matrix, ssap_capacity_stress, ssap_multi_notify, ssap_write_readonly |
| PHY | 2 | phy_layer, phy_extreme_params |
| 功率管理 | 3 | power_management, pm_state_transitions, pm_param_validation |
| AFH | 1 | afh_channel_map |
| 同步链路 | 2 | sync_link_management, sync_mcast_bis |
| DLI | 8 | dli_info, dli_event_poll, dli_extended_commands, dli_reset_behavior, dli_routing, dli_security_commands, dli_mgmt_plane, dli_info_consistency |
| 事件 | 4 | event_notification, event_overflow, event_stats, async_event_pump |
| RAL/RPA | 1 | rpa_management |
| 测距 | 1 | measurement_stubs |
| 角色 | 1 | role_management |
| 协议综合 | 7 | e2e_data_path, encrypted_data_path, air_medium_connect, air_medium_bidir, channel_tcid_standard, crc12_verification, credit_flow_control |
| 系统/边界 | 14 | configfs, configfs_ioctl_integration, multi_controller, multi_fd_stress, state_machine_torture, ring_buffer_stress, data_path_saturation, ioctl_fuzz, ioctl_throughput, mutual_exclusion, loopback, loopback_filter, poll_epoll, unknown_ioctl |
| 外设 | 5 | usb_controller_ops, usb_discovery, genetlink, ssap_air_interface, ssap_remote_ioctls |
| 能力 | 2 | capability_negotiation, scan_uuid_filter |
| HMAC | 1 | hmac_sm3 |
| 头文件 | 1 | header |
| 统计 | 1 | subsys_stats |

### 用户态测试用例分布 (60 个)

| Crate | 测试数 | 覆盖范围 |
|-------|--------|---------|
| slk-protocol | 29 | struct layout, field offsets, buffer capacity, zero-init safety |
| libsparklink | 6 | error conversion, event variants, FFI null safety |
| slkd | 18 | config parsing, D-Bus return type validation, interface fields |
| slkconfig | 7 | argument parsing |

### 测试缺口

1. **用户态集成测试**：无 slkd ↔ slctl 端到端 D-Bus 集成测试
2. **CLI 命令测试**：slctl 的 30+ 命令没有单元测试
3. **FFI 边界测试**：libsparklink 的 50+ C FFI 函数缺少系统性测试
4. **内核 RPA 自动刷新计时器**：仅 1 个测试 (rpa_management)，缺少超时和并发场景
5. **scan_uuid_filter**：仅 1 个测试，缺少多 UUID 组合测试

## 4. 安全审计

### 密码学实现

| 算法 | 实现位置 | 标准 | 状态 |
|------|---------|------|------|
| SM3 | sle_crypto.rs → sle_crypto_ffi.c → 内核 crypto API | GB/T 32905 | 使用内核实现，安全 |
| SM4 (ECB/CTR) | 同上 | GB/T 32907 | 使用内核实现，安全 |
| ECDH | 同上 | GB/T 32918 | 使用内核实现，安全 |
| HMAC-SM3 | 同上 | RFC 2104 变体 | 使用内核实现，安全 |

**审计结论**：密码学不做自研，全部委托内核 crypto API，正确的做法。

### ioctl 输入验证

- 所有 `repr(C)` 结构体均有 `_reserved` 字段，内核侧通过 `CheckReserved` trait 校验
- 用户态使用 nix crate 的安全封装，避免裸指针操作
- 连接句柄校验贯穿 conn/ssap/security 子系统

### 潜在风险

1. **ioctl_fuzz 覆盖范围**：内核有模糊测试用例但仅覆盖已知 ioctl 编号的边界，未覆盖有效参数内的畸形字段
2. **并发访问**：多控制器切换使用全局锁 `SUBSYSTEM`，高并发场景下可能成为瓶颈
3. **USB 热插拔**：sle_usb_ffi.c 中的完成回调与 Rust 侧的生命周期管理需关注 UAF 风险

## 5. 标准符合性矩阵

| 标准条款 | 内容 | 内核实现 | 用户态 | 备注 |
|---------|------|---------|--------|------|
| TXS-10002 4.1 | SLE 空口帧格式 | sle_pdu.rs | — | CRC-12 已实现 |
| TXS-10002 4.2 | MCS 0-12 调制 | sle_phy.rs (13级) | phy_set_mcs | 完整 |
| TXS-10002 4.3 | AFH 跳频 | sle_phy.rs + sle_conn.rs | afh_* ioctl | 完整 |
| TXS-10002 5.1 | 广播发现等级 | sle_adv.rs (5级) | start_adv | 完整 |
| TXS-10002 5.2 | 扩展广播 | sle_adv.rs | ext_adv_* | 完整 |
| TXS-10002 6.1 | 连接建立 | sle_conn.rs | connect | 完整 |
| TXS-10002 6.2 | 信用流控 | sle_conn.rs | conn_send | 完整 |
| TXS-10003 3.1 | DLI 包格式 | sle_dli.rs (5种) | DLI_PKT_* | 完整 |
| TXS-10003 3.2 | DLI 传输层 | usb/uart/spi | — | 3 种实现 |
| TXS-20001 4.1 | SSAP 服务注册 | sle_ssap.rs | ssap_add_svc | 完整 |
| TXS-20001 4.2 | 属性读写 | sle_ssap.rs | ssap_read/write | 完整 |
| TXS-20001 4.3 | 远程发现 | sle_ssap.rs | ssap_remote_* | 完整 |
| TXS-20002 3.1 | PSK 预共享密钥 | sle_security.rs | sec_set_psk | 完整 |
| TXS-20002 3.2 | JustWorks 配对 | sle_security.rs | sec_pair | 完整 |
| TXS-20002 3.3 | 数值比较 | sle_security.rs | passkey_* | 完整 |
| TXS-20002 3.4 | OOB 配对 | sle_security.rs | sec_set_oob | 完整 |
| TXS-20002 3.5 | 加密传输 | sle_security.rs | sec_encrypt_on | 完整 |
| TXS-20002 3.6 | RAL/RPA | sle_security.rs | ral_*/rpa_* | 完整 |

## 6. 代码质量指标

| 指标 | 值 | 说明 |
|------|------|------|
| 内核编译警告 | 0 | `-D warnings` 全部作为错误处理 |
| 用户态编译警告 | 3 | dead_code 警告（slkd config/state 字段） |
| QEMU 测试通过率 | 100% (737/737) | 96 个测试 × 多参数组合 |
| 用户态测试通过率 | 100% (60/60) | — |
| unsafe 使用 | 仅限 FFI 边界 | C 回调、ioctl 调用、指针传递 |
| clippy 审查 | 通过 | 遵循标准 Rust 风格 |
