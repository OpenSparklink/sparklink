# SparkLink 协议栈架构

## 概述

SparkLink（星闪）协议栈采用 Rust 编写内核子系统（net/sparklink/），配合用户态 Rust 工具链提供设备管理、协议控制和诊断能力，目前处于实验实现阶段。

本文记录迁移前的源码结构和历史统计，不表示标准符合性或实机功能已经验收。当前全局控制器切换、内核 SSAP 数据库和用户态事件接口将按 [联合实施方案](IMPLEMENTATION_PLAN.md) 迁移；功能完成情况以 issues 的逐项证据为准。

## 整体分层

```
┌───────────────────────────────────────────────────────────────────────┐
│                         用户态应用                                    │
│  slctl (CLI)  │  slkconfig  │  slkmon  │  slkdump  │  第三方应用     │
├───────────────┼─────────────┼──────────┼───────────┼─────────────────┤
│               │     slkd (D-Bus 守护进程)           │                 │
│               │  8 个 D-Bus 接口 @ org.sparklink    │                 │
├───────────────┴─────────────┴──────────┴───────────┴─────────────────┤
│                  libsparklink (Adapter + FFI)                        │
├──────────────────────────────────────────────────────────────────────┤
│                  slk-protocol (UAPI 类型 + ioctl)                     │
╞══════════════════════════════════════════════════════════════════════╡
│                  /dev/sparklink (字符设备)                            │
│                  126 个 ioctl 命令 (magic 'S')                       │
├──────────────────────────────────────────────────────────────────────┤
│                  sparklink_core.rs (内核核心)                        │
│           ┌──────┬──────┬──────┬──────┬──────┬──────┐               │
│           │ Adv  │ Conn │ SSAP │ Sec  │ PHY  │ PM   │               │
│           │ Scan │ AFH  │      │ RAL  │ Meas │ Sync │               │
│           └──┬───┴──┬───┴──┬───┴──┬───┴──┬───┴──┬───┘               │
│              └──────┴──────┴──────┴──────┴──────┘                    │
│                     Workers (EventPump + CmdWorker)                  │
│                     Management Plane (CmdPending)                    │
├──────────────────────────────────────────────────────────────────────┤
│                  DLI (SleController trait)                           │
│           ┌─────────┬─────────┬─────────┬───────────┐               │
│           │  USB    │  UART   │   SPI   │  Virtual  │               │
│           └─────────┴─────────┴─────────┴───────────┘               │
├──────────────────────────────────────────────────────────────────────┤
│                     硬件 / 射频前端                                   │
└──────────────────────────────────────────────────────────────────────┘
```

## 内核子系统 (net/sparklink/)

### 文件清单与行数

| 文件 | 行数 | 职责 |
|------|------|------|
| `sparklink_core.rs` | 3992 | 模块入口、全局子系统锁、ioctl 分发、多控制器切换、字符设备注册 |
| `sle_conn.rs` | 3071 | 连接管理器、传输信道 TCID、信用流控、数据收发 |
| `sle_uapi.rs` | 2880 | 80+ 个 `repr(C)` ioctl 结构体定义 |
| `sle_ssap.rs` | 2480 | SSAP 服务模型、属性/方法/通知、远程服务发现 |
| `sle_usb.rs` | 1625 | USB DLI 传输、帧编解码、事件环 |
| `sle_workers.rs` | 1515 | EventPump 后台轮询、CommandWorker 异步派发 |
| `sle_dli.rs` | 1503 | DLI 抽象层、`SleController` trait、50+ 事件变体 |
| `sle_event.rs` | 1387 | 40+ 事件类型、wire format、EventQueue |
| `sle_security.rs` | 977 | 安全状态机、配对方法、密钥派生、RPA 管理 |
| `sle_pdu.rs` | 896 | PDU 帧编解码、CRC-12 校验 |
| `sle_adv.rs` | 863 | 广播/扫描状态机、发现等级、扫描过滤 |
| `sle_phy.rs` | 684 | 13 级 MCS 表、频率跳频、天线配置 |
| `sle_serdev.rs` | 547 | Serdev 驱动骨架 |
| `sle_uart.rs` | 530 | UART H4 传输协议、帧解析 |
| `sle_spi.rs` | 474 | SPI 寄存器协议、控制/数据寄存器 |
| `sle_netlink.rs` | 364 | Generic Netlink 命令/属性枚举 |
| `sle_transport.rs` | 360 | 传输协议注册框架 |
| `sle_mgmt.rs` | 333 | 命令待决队列、jiffies 超时 |
| `sle_dev.rs` | 326 | 每控制器设备模型、全局注册表 |
| `sle_power.rs` | 314 | 功率状态、连接间隔、监督超时 |
| `sle_crypto.rs` | 267 | SM3/SM4/ECDH 内核密码 API FFI |
| `sle_configfs.rs` | 229 | configfs 接口 |
| `sle_fw.rs` | 185 | 固件加载 |
| `sle_usb_ffi.c` | 1093 | USB 完成回调、事件环 C 桥接 |
| `sparklink_genl.c` | 656 | Generic Netlink 家族注册 |
| `sle_serdev_ffi.c` | 600 | Serdev 回调 C 桥接 |
| `sle_crypto_ffi.c` | 419 | 内核密码 API C 封装 |
| **合计** | **28570** | |

### 内核 5 层架构

**第 1 层 — 设备模型 (SleDev)**
- 全局设备注册表 `SLE_DEV_REGISTRY`
- 支持最多 8 个并发虚拟控制器
- 设备状态标志：REGISTERED / UP / ADVERTISING / SCANNING / CONNECTED 等

**第 2 层 — DLI 控制器抽象**
- `SleController` trait：统一的硬件访问接口
- 4 种传输实现：USB / UART / SPI / Virtual
- 5 种 DLI 包类型：Command(0xA1) / Event(0xA2) / AsyncUcast(0xA3) / SyncUcast(0xA4) / AsyncMcast(0xA5)

**第 3 层 — 管理面**
- `CmdPendingQueue`：命令排队与 jiffies 超时
- 请求-响应关联、自动重试

**第 4 层 — 工作线程**
- `EventPump`：后台轮询 DLI 事件，写入 EventQueue
- `CommandWorker`：异步命令派发

**第 5 层 — 协议子系统**
- 广播/扫描 (`sle_adv.rs`)：传统 + 扩展广播，发现等级过滤
- 连接 (`sle_conn.rs`)：TCID 信道 (0x02/0x0A/0x1F)，信用流控
- SSAP (`sle_ssap.rs`)：属性/方法/通知，17 种消息类型
- 安全 (`sle_security.rs`)：JustWorks / PSK / NumericComparison / OOB / Password
- PHY (`sle_phy.rs`)：13 级 MCS，AFH 跳频
- 功率管理 (`sle_power.rs`)：Active / Sniff / Idle / Suspended
- 同步链路：CIG (单播) / BIG (组播) 配置
- RAL/RPA：可解析私有地址自动刷新
- 测距：能力查询与测量控制

### 多控制器模型

```
SubsystemShared {
    active_dev_id: u16,
    saved_states: KVec<(u16, PerDeviceState)>,
    controller: Arc<dyn SleController>,
    ...
}
```

切换流程：保存当前状态到堆 → 恢复目标状态 → 派发操作。

### 构建配置

```
CONFIG_SPARKLINK=y          # 主开关
CONFIG_SPARKLINK_GENL=y     # Generic Netlink 接口
CONFIG_SPARKLINK_SLE=y      # SLE 空口支持
CONFIG_SPARKLINK_DEBUGFS=y  # debugfs 调试
```

依赖：`RUST`、`NET`、`CRYPTO`（SM3/SM4/ECDH/HMAC）。

## 用户态工具链 (/home/sanchuanhehe/Documents/sparklink/)

### Crate 依赖关系

```
slk-protocol (UAPI 类型层)
     │
     ▼
libsparklink (核心库)
     │
     ├──────┬──────┬──────┬──────┐
     ▼      ▼      ▼      ▼      ▼
   slkd  slctl slkconfig slkmon slkdump
```

### 各 Crate 职责

| Crate | 行数 | 角色 |
|-------|------|------|
| `slk-protocol` | 1633 | UAPI ABI 定义：80+ repr(C) 结构体、126 个 ioctl、GenNL 属性 |
| `libsparklink` | 1597 | 核心库：Adapter（100+ 方法）、Event 枚举、C FFI（50+ 导出） |
| `slkd` | 1928 | D-Bus 守护进程：8 个接口、事件循环、TOML 配置 |
| `slctl` | 572 | 交互式 CLI：30+ 命令、REPL、rustyline 历史 |
| `slkconfig` | 820 | 离线配置工具：直接 ioctl 操作，不依赖守护进程 |
| `slkdump` | 142 | 帧捕获：原始帧 hex/ASCII 显示、二进制输出 |
| `slkmon` | 234 | 协议监视：实时事件解码、过滤、时间戳 |
| **合计** | **7148** | |

### D-Bus 接口映射

| 接口名 | 对象路径 | 方法数 | 职责 |
|--------|---------|--------|------|
| `org.sparklink.Manager` | `/org/sparklink` | 3 | 版本、设备枚举、守护进程控制 |
| `org.sparklink.Adapter` | `/org/sparklink/slk0` | 12 | 广播/扫描/连接/断开/发送/角色 |
| `org.sparklink.Device` | `/org/sparklink/slk0/dev_*` | 6 | 单设备连接/配对/信息查询 |
| `org.sparklink.Security` | `/org/sparklink/slk0/security` | 8 | PSK/配对/加密/Passkey/OOB |
| `org.sparklink.ServiceManager` | `/org/sparklink/slk0/services` | 5 | SSAP 服务注册/发现 |
| `org.sparklink.RemoteService` | `/org/sparklink/slk0/remote` | 6 | 远程服务读写/通知/方法调用 |
| `org.sparklink.ExtAdv` | `/org/sparklink/slk0/extadv` | 9 | 扩展广播完整生命周期 |
| `org.sparklink.Controller` | `/org/sparklink/slk0/controller` | 30+ | PHY/PM/AFH/DLI/RAL/测距/统计 |

### 数据调用链

```
用户 CLI 命令
    │
    ▼
slctl (zbus proxy 调用)
    │ D-Bus IPC
    ▼
slkd (接口实现 → AdapterState)
    │
    ▼
libsparklink::Adapter (方法调用)
    │ nix::ioctl
    ▼
/dev/sparklink (字符设备)
    │ copy_from_user / copy_to_user
    ▼
sparklink_core.rs (ioctl 分发)
    │
    ▼
协议子系统 (adv/conn/ssap/sec/phy/pm/...)
    │
    ▼
DLI → 硬件
```

## 测试体系

| 层级 | 框架 | 用例数 | 范围 |
|------|------|--------|------|
| 内核 ioctl 测试 | C selftest (QEMU) | 96 | 全部 16 个 ioctl 分组、状态机、并发、安全、性能 |
| slk-protocol | Rust #[test] | 29 | 结构体布局、字段偏移、缓冲区容量、零初始化安全 |
| libsparklink | Rust #[test] | 6 | 错误转换、事件变体、FFI 空指针安全 |
| slkd | Rust #[test] | 18 | D-Bus 返回类型、配置解析、接口验证 |
| slkconfig | Rust #[test] | 7 | 参数解析 |
| **合计** | | **156** | |

构建命令：
- 内核：`cd build && make LLVM=-16 -j$(nproc)`
- 用户态：`cargo build --release`
- 内核测试：`bash tools/testing/selftests/sparklink/run_qemu_test.sh`
- 用户态测试：`cargo test`

## 标准符合性

| 标准编号 | 名称 | 覆盖状态 |
|---------|------|---------|
| T/XS 10002-2025 | SLE 空口规范 | 有源码实现，完整符合性与实机验收待完成 |
| T/XS 10003-2025 | DLI 驱动层接口 | 有源码实现，真实事务与方言验收待完成 |
| T/XS 20001-2025 | SSAP 服务访问协议 | 有内核实现，用户态 Engine 迁移与实机验收待完成 |
| T/XS 20002-2025 | 基础服务层传输与控制 | 有机制实现，TCID/传输模式与实机验收待完成 |
| T/XS 10002-2025 §9/§13 | SLE 信息安全与测试 | policy/Bond 与实机验收待完成 |
| T/XS 40001-2022 | 网络安全通用要求 | 授权、凭据与安全验收待完成 |
| T/XS 50003-2025 | SLE 一致性测试 | 部分覆盖 |
| T/XS 50004-2025 | 互操作测试 | 待补充 |

### Generation-specific adapters and native Ready (partial WS73 work)

slkd starts independently of controller presence. The registry worker reads the
allocated-device mask; each selected registration owns its control fd, bootstrap
and event task. Paths include both ID and generation, e.g.
`/org/sparklink/slk1_g2`. Removal stops that node's actors/subscription and removes
its D-Bus objects. Other nodes keep their identity and continue running.

`ControllerState` is Setup, Ready, Fault or Removed. Native Ready comes from the
kernel snapshot after actual metadata queries and both initialization stop
Complete events; `Powered` cannot establish Ready. `MetadataValidFields` bit 0
marks the full five-byte version/80-bit features. Host faults expose their errno;
initialization failures have a separate message. These states do not certify RF
or the supplied board calibration. Native profiles and legacy `scan on|off` are
unsupported while a reviewed WS73 radio policy/SSAP backend is pending.

The native subscriber uses the non-destructive full event stream with explicit
registration identity and loss. `GetReports` returns up to 128 exact native
reports (sequence, generation, receive wall-clock milliseconds, address, RSSI,
raw 23-byte header, data, lost count). Fragment/vendor/address-type/PHY bytes stay
opaque; the daemon does not treat native data as legacy name/SSAP TLVs. This
bounded history does not replace persistent USB/HCC/DLI evidence capture.

Interactive usage is `list`, `select slk1_g2`, `show`, `reports`. Selection stays
bound to that generation; after unplug, choose a new live path explicitly.
Reproducible one-shot calls are `slctl list` and
`slctl --adapter /org/sparklink/slk1_g2 show` (or `reports`). `--session` selects a
private test bus in both programs; production continues using the system bus.
The kernel selftest `run_daemon_lifecycle.py` runs these actual binaries as guest
uid 1000 on synthetic WS73 controllers and checks hotplug with the same slkd.
It is development support, not the seven real North Star acceptance criteria.
