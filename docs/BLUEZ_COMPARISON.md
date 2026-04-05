# SparkLink 与 BlueZ 架构对比分析

## 1. 概览

BlueZ 是 Linux 官方蓝牙协议栈，已有 20+ 年历史，代码量超过 10 万行（内核 + 用户态）。SparkLink 协议栈参考了 BlueZ 的设计范式，但针对星闪协议的特点做了简化和重构。

| 维度 | BlueZ | SparkLink | 备注 |
|------|-------|-----------|------|
| 内核代码 | 62,144 行 C (net/bluetooth/) | 28,570 行 Rust (net/sparklink/) | SparkLink 约 BlueZ 的 46% |
| 内核语言 | C | Rust + C FFI | SparkLink 使用 Rust 增强安全性 |
| 协议栈年龄 | 2001 至今 (24 年) | 2024 至今 | BlueZ 经过长期迭代 |
| 用户态守护进程 | bluetoothd (C, ~130,000 行) | slkd (Rust, ~1,900 行) | SparkLink 自用标准更少 |
| CLI 工具 | bluetoothctl | slctl | 功能对等 |
| IPC 机制 | D-Bus | D-Bus | 架构一致 |
| 用户态库 | libbluetooth (C) | libsparklink (Rust + C FFI) | SparkLink 提供 Rust + C 双接口 |

## 2. 内核层对比

### 2.1 设备抽象

| 特性 | BlueZ | SparkLink |
|------|-------|-----------|
| 设备结构体 | `struct hci_dev` (~150 字段) | `SleDev` + `PerDeviceState` |
| 设备注册 | `hci_register_dev()` | ioctl `DEV_REGISTER` |
| 控制接口 | HCI socket + mgmt socket | `/dev/sparklink` ioctl |
| 多设备支持 | 每设备独立 hci_dev 实例 | 最多 8 个虚拟控制器，swap-on-switch |
| sysfs 集成 | `/sys/class/bluetooth/hci0/` | configfs `/sys/kernel/config/sparklink/` |

**差异分析**：BlueZ 为每个蓝牙控制器创建独立的 hci_dev 实例和独立的 socket 接口。SparkLink 使用单一字符设备 + 设备 ID 选择的模型，简化了用户态接口但牺牲了多进程并发操作不同控制器的能力。

### 2.2 传输层

| 传输 | BlueZ | SparkLink |
|------|-------|-----------|
| USB | `btusb.c` (3,800+ 行) | `sle_usb.rs` + `sle_usb_ffi.c` (2,718 行) |
| UART | `hci_ldisc.c` + `hci_uart.h` + 多协议 | `sle_uart.rs` (530 行) |
| SPI | 无标准支持 | `sle_spi.rs` (474 行) |
| SDIO | `btsdio.c` | 定义了 BusType::Sdio 但未实现 |
| 虚拟设备 | `hci_vhci.c` | `sparklink_virtual.rs` (32 行) |

**差异分析**：BlueZ 的 USB 驱动支持数百种蓝牙芯片的 vendor 特定初始化。SparkLink 的传输层更精简但缺少厂商适配层。

### 2.3 协议层

| 协议/功能 | BlueZ | SparkLink | 状态 |
|-----------|-------|-----------|------|
| 空口帧编解码 | HCI (标准化) | SLE PDU + DLI | 完整 |
| 连接管理 | `hci_conn.c` (4,500+ 行) | `sle_conn.rs` (3,071 行) | 完整 |
| 安全配对 | SMP (`smp.c` 3,847 行) | `sle_security.rs` (977 行) | 完整 |
| 广播/扫描 | HCI LE Adv | `sle_adv.rs` (863 行) | 完整 |
| 服务发现 | SDP / GATT | SSAP (`sle_ssap.rs` 2,480 行) | 完整 |
| L2CAP | `l2cap_core.c` (7,900+ 行) | 无独立 L2CAP | 星闪标准不需要 |
| RFCOMM | `rfcomm/` 子目录 | 不适用 | 星闪标准无此需求 |
| SCO 音频 | `sco.c` (1,608 行) | 同步链路 via Sync Link | 部分对应 |
| ISO 同步 | `iso.c` | CIG/BIG via Sync Link | 设计对应 |
| 6LoWPAN | `6lowpan.c` | 不适用 | 星闪标准无此需求 |
| 功率管理 | HCI Sniff/Hold/Park | `sle_power.rs` 4 状态 | 完整 |
| AFH 跳频 | HCI 命令实现 | `sle_phy.rs` + AFH ioctl | 完整 |
| RAL/RPA | 内核 + bluetoothd | `sle_security.rs` RPA 管理 | 完整 |
| Mesh 网络 | 用户态 mesh-cfgclient | 不适用 | 未来可能需要 |

### 2.4 管理接口

| 特性 | BlueZ | SparkLink |
|------|-------|-----------|
| 管理协议 | mgmt socket (`mgmt.c` 10,000+ 行) | ioctl (sparklink_core.rs 3,992 行) |
| 命令数量 | 70+ mgmt 操作码 | 126 个 ioctl |
| 事件推送 | mgmt 事件 + HCI 事件 | EventQueue + poll |
| Netlink | 无 | Generic Netlink（可选） |

## 3. 用户态对比

### 3.1 守护进程

| 特性 | bluetoothd | slkd |
|------|-----------|------|
| 代码量 | ~130,000 行 C | ~1,900 行 Rust |
| D-Bus 接口数 | 10+ | 8 |
| Profile 插件 | 30+ 个 profile 插件 | 无插件机制 |
| 配置 | `/etc/bluetooth/main.conf` | TOML 配置文件 |
| 音频集成 | PulseAudio/PipeWire 对接 | 不适用 |
| 网络 | PAN/BNEP 集成 | 不适用 |

**差异分析**：bluetoothd 的体量来自其庞大的 Profile 插件系统（A2DP、HFP、HID、PAN 等），每个 Profile 都是独立的 C 源文件。SparkLink 目前只实现了核心管理功能，没有引入 Profile 插件架构。

### 3.2 D-Bus 接口

| BlueZ D-Bus 接口 | SparkLink 对应 | 状态 |
|-------------------|---------------|------|
| `org.bluez.Adapter1` | `org.sparklink.Adapter` | 完整 |
| `org.bluez.Device1` | `org.sparklink.Device` | 完整 |
| `org.bluez.GattManager1` | `org.sparklink.ServiceManager` | 完整 |
| `org.bluez.GattService1` | `org.sparklink.RemoteService` | 完整 |
| `org.bluez.GattCharacteristic1` | SSAP 属性 via RemoteService | 简化合并 |
| `org.bluez.AgentManager1` | 安全功能合并至 Security | 简化 |
| `org.bluez.ProfileManager1` | 无 | **缺失** |
| `org.bluez.MediaControl1` | 不适用 | 星闪无音频 Profile |
| `org.bluez.NetworkServer1` | 不适用 | 星闪无 PAN Profile |
| `org.bluez.Input1` | 不适用 | 星闪无 HID Profile |
| — | `org.sparklink.ExtAdv` | SparkLink 独有 |
| — | `org.sparklink.Controller` | SparkLink 独有 |

### 3.3 CLI 工具

| 特性 | bluetoothctl | slctl |
|------|-------------|-------|
| 交互模式 | REPL + 菜单 | REPL |
| 命令数量 | 60+ | 30+ |
| Tab 补全 | 支持 | 基于 rustyline |
| 配色输出 | 支持 | 基础支持 |
| 设备列表 | `devices` | `devices` |
| 扫描 | `scan on/off` | `scan` |
| 配对 | `pair <addr>` | `pair <addr>` |
| 连接 | `connect <addr>` | `connect <addr>` |
| Agent | `agent on/off` | 通过 Security 接口 |
| GATT | `menu gatt` + 子命令 | `services`/`read`/`write` |
| 广播 | `advertise on/off` | `advertise`/`extadv` |

### 3.4 用户态库

| 特性 | libbluetooth | libsparklink |
|------|-------------|--------------|
| 语言 | C | Rust + C FFI |
| API 风格 | HCI socket + BSD socket | Adapter 方法 + unsafe FFI |
| 头文件 | `bluetooth/bluetooth.h` 等 | `sparklink.h` |
| pkg-config | `bluez` | 待添加 |
| 编程语言绑定 | Python (pybluez)、Go 等 | C FFI（可桥接任何语言） |

## 4. SparkLink 相对于 BlueZ 的缺失功能

### 4.1 必须补充的功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| **~~Profile 插件框架~~** | ~~高~~ | ✅ 已实现。Profile trait + ProfileRegistry + BatteryProfile + DeviceInfoProfile + HidProfile |
| **~~pkg-config 支持~~** | ~~高~~ | ✅ 已添加 sparklink.pc |
| **~~systemd 服务文件~~** | ~~高~~ | ✅ 已存在 sparklink.service |
| **~~udev 规则~~** | ~~高~~ | ✅ 已添加 99-sparklink.rules |
| **~~D-Bus 策略文件~~** | ~~高~~ | ✅ 已更新 sparklink.conf（包含 ExtAdv + Controller 接口） |
| **~~man page~~** | ~~中~~ | ✅ 已添加 slkd(8), slctl(1), sparklink.conf(5) |
| **~~设备 bonding 持久化~~** | ~~中~~ | ✅ 已实现。BondingStore 保存到 /var/lib/sparklink/ |
| **Agent 代理机制** | 中 | BlueZ 的 Agent 允许用户态应用接管配对交互流程 |

### 4.2 建议参考的功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 蓝牙/星闪共存管理 | 低 | 如果设备同时支持 BT 和 SLE，需要频谱共存策略 |
| 网络桥接 (PAN) | 低 | 星闪标准暂无网络桥接需求 |
| 音频支持 | 低 | 星闪标准暂无音频 Profile |
| HID Profile | 低 | ✅ 已实现。基于 T/XS 30013-2025 标准，支持键盘/鼠标/触控笔/高刷新率鼠标 |
| LED 状态指示 | 低 | BlueZ 的 `leds.c` 控制蓝牙指示灯 |
| coredump 支持 | 低 | BlueZ 提供 controller coredump 机制 |
| AOSP 扩展 | 不需要 | Android 专用 |
| MSFT 扩展 | 不需要 | Microsoft 专用 |

### 4.3 SparkLink 独有的优势

| 功能 | 说明 |
|------|------|
| Rust 类型安全 | 内核层使用 Rust，编译期消除内存安全和并发问题 |
| 统一 ioctl 接口 | 126 个 ioctl 覆盖全部功能，比 BlueZ 的 HCI socket + mgmt socket 更统一 |
| 内核内置测试 | 96 个 selftest 用例在 QEMU 中运行，BlueZ 缺少内核侧的系统测试 |
| 扩展广播管理 | 独立的 ExtAdv 接口提供比 BlueZ 更细粒度的广播控制 |
| 控制器全面暴露 | Controller 接口直接暴露 PHY/PM/AFH/DLI/RAL/测距，BlueZ 隐藏内部实现 |
| Sync Link | CIG/BIG 统一管理接口，比 BlueZ ISO socket 更简洁 |
| SPI 传输 | 原生 SPI 控制器支持，BlueZ 无此功能 |

## 5. 架构改进建议

### 短期 (P0) —— 全部完成

1. ~~**添加 systemd 服务文件**~~ ✅
2. ~~**添加 D-Bus 策略文件**~~ ✅
3. ~~**添加 udev 规则**~~ ✅
4. ~~**添加 pkg-config 文件**~~ ✅
5. ~~**修复 GetDevices 返回类型**~~ ✅

### 中期 (P1) —— 全部完成

1. ~~**实现配对信息持久化**~~ ✅ bonding.rs
2. ~~**引入 Profile 注册框架**~~ ✅ profile.rs + hid.rs
3. ~~**补全 CLI 命令**~~ ✅ 39 个命令
4. ~~**编写 man page**~~ ✅ slkd(8), slctl(1), sparklink.conf(5)
5. **HID Profile** ✅ 基于 T/XS 30013-2025 标准

### 长期 (P2)

1. **SSAP Profile 标准化** — 定义 SLE 等价的 GATT Profile 规范
2. **蓝牙共存** — 与 BlueZ 协调频谱使用
3. **跨平台 CI** — 在多架构上运行 QEMU 测试
