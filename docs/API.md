# API 参考 — ioctl 命令

所有 ioctl 以 magic number `0x53` (`'S'`) 编号，通过 `/dev/sparklink` 字符设备执行。

这里的旧接口编号表不是生产能力清单，也不包含全部版本化 Native 管理／
诊断接口。部分旧入口已明确返回不支持，后续随调用者迁移删除；框架或绑定
存在不表示设备支持。当前 Native 契约见[管理所有权](MANAGEMENT_OWNERSHIP.md)、
[WS73 门禁](WS73_DISCOVERY_NORTH_STAR.md)和[诊断提交](DIAGNOSTIC_ADMISSION.md)。

## 旧接口编号概览（等待调用迁移）

| 分类 | 序号范围 | 数量 | 功能 |
|------|----------|------|------|
| 设备管理 | 0x03-0x08 | 6 | 枚举/查询/选择控制器 |
| 广播与扫描 | 0x10-0x1C | 13 | 传统广播/扫描 + 扩展广播全生命周期 |
| 扫描注入/过滤 | 0x20-0x24 | 5 | 注入模拟广播包、UUID 过滤 |
| 连接管理 | 0x30-0x39 | 10 | 连接/断开/数据收发/MTU/连接列表 |
| AFH | 0x3A-0x3F | 6 | 信道图设置/获取、RSSI 上报、跳频 |
| 安全 | 0x40-0x4F | 16 | PSK/配对/加密/Passkey/OOB/SM3/SM4/HMAC 测试 |
| SSAP 服务 | 0x50-0x5F, 0x6F, 0x72 | 18 | 服务注册/属性读写/远程发现/UUID 查询 |
| 功率管理 | 0x60-0x65 | 6 | 状态查询/切换/唤醒间隔/强制活跃 |
| 同步链路 | 0x66-0x6E | 9 | 单播/组播 CIG/BIG 配置与数据通路 |
| 事件队列 | 0x70-0x71 | 2 | 事件计数/统计 |
| DLI 控制器 | 0x80-0x87 | 8 | 控制器信息/事件轮询/重置/命令下发/统计/完整原生事件 |
| PHY 层 | 0x90-0x97 | 8 | 信息/MCS/功率/带宽/跳频/SINR |
| 能力协商 | 0x98-0x9B | 4 | 对端特性/版本/参数更新/PHY 更新 |
| 角色 | 0xA0-0xA1 | 2 | T/G 角色读写 |
| RAL/RPA | 0xB0-0xB7 | 8 | 地址解析列表与可解析私有地址管理 |
| 测距 | 0xC0-0xC3 | 4 | 能力查询/链路参数/动作/使能 |

## 设备管理 (0x03-0x08)

旧 0x01/0x02 注册/注销 ioctl 从未实施真实操作，现已同步删除；旧编号返回
ENOTTY，暂不复用。控制器由实际 backend 注册/移除。UAPI 尚未发布，无兼容期。

| CMD | 序号 | 方向 | 参数类型 | 说明 |
|-----|------|------|----------|------|
| `DEV_COUNT` | 0x03 | read | `u32` | 查询控制器数量 |
| `DEV_INFO` | 0x04 | read | `SciDevInfo` | 获取活跃设备信息 |
| `DEV_SWITCH` | 0x05 | write_int | dev_id | 切换活跃控制器 |
| `DEV_LIST` | 0x06 | read | `u16` | 获取设备 ID 列表 |
| `DEV_SELECT` | 0x07 | write_int | dev_id | 为本 fd 选择设备 |
| `DEV_GET_ACTIVE` | 0x08 | read | `u16` | 查询当前活跃 ID |

## 广播与扫描 (0x10-0x1C)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `START_ADV` | 0x10 | write_ptr | `SleAdvParams` |
| `STOP_ADV` | 0x11 | none | — |
| `START_SCAN` | 0x12 | write_ptr | `SleScanParams` |
| `STOP_SCAN` | 0x13 | none | — |
| `EXT_ADV_CONFIGURE` | 0x14 | write_ptr | `SleExtAdvConfig` |
| `EXT_ADV_SET_DATA` | 0x15 | write_ptr | `SleExtAdvData` |
| `EXT_ADV_ENABLE` | 0x16 | write_int | handle |
| `EXT_ADV_DISABLE` | 0x17 | write_int | handle |
| `EXT_ADV_REMOVE` | 0x18 | write_int | handle |
| `EXT_ADV_INFO` | 0x19 | readwrite | `SleExtAdvInfo` |
| `EXT_ADV_ENABLE_EX` | 0x1A | write_ptr | `SleExtAdvEnableParams` |
| `EXT_ADV_TICK` | 0x1B | none | — |
| `EXT_ADV_SET_SCAN_RSP` | 0x1C | write_ptr | `SleExtAdvData` |

## 扫描注入/过滤 (0x20-0x24)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `INJECT_ADV` | 0x20 | write_ptr | `SleInjectAdv` |
| `SCAN_RESULT_COUNT` | 0x21 | none | — |
| `INJECT_RAW_ADV` | 0x22 | write_ptr | `SleInjectRawAdv` |
| `SET_SCAN_FILTER` | 0x23 | write_ptr | `SleScanFilter` |
| `CLEAR_SCAN_FILTER` | 0x24 | none | — |

## 连接管理 (0x30-0x39)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `CONNECT` | 0x30 | write_ptr | `SleConnectParams` |
| `DISCONNECT` | 0x31 | write_int | handle |
| `CONN_INFO` | 0x32 | readwrite | `SleConnInfo` |
| `CONN_SEND` | 0x33 | write_ptr | `SleConnData` |
| `CONN_RECV` | 0x34 | readwrite | `SleConnData` |
| `INJECT_CONN_RESP` | 0x35 | write_ptr | `SleInjectConnResp` |
| `INJECT_CONN_DATA` | 0x36 | write_ptr | `SleConnData` |
| `CONN_COUNT` | 0x37 | none | — (返回值) |
| `CONN_LIST` | 0x38 | read | `SleConnList` |
| `SET_CONN_MTU` | 0x39 | write_ptr | `SleConnMtuParams` |

## AFH (0x3A-0x3F)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `AFH_SET_MAP` | 0x3A | write_ptr | `SleAfhMapParams` |
| `AFH_GET_MAP` | 0x3B | readwrite | `SleAfhMapParams` |
| `AFH_REPORT_RSSI` | 0x3C | write_ptr | `SleAfhRssiReport` |
| `AFH_CLASSIFY` | 0x3D | readwrite | `SleAfhClassifyParams` |
| `AFH_HOP_NEXT` | 0x3E | readwrite | `SleAfhHopInfo` |
| `AFH_REPORT_RETX` | 0x3F | write_ptr | `SleAfhRetxReport` |

## 安全 (0x40-0x4F)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `SEC_SET_PSK` | 0x40 | write_ptr | `SlePskParams` |
| `SEC_PAIR` | 0x41 | write_ptr | `SlePairParams` |
| `SEC_INFO` | 0x42 | read | `SleSecInfo` |
| `SEC_ENCRYPT_ON` | 0x43 | none | — |
| `SEC_SM3_TEST` | 0x44 | write_ptr | `SleHashTest` |
| `SEC_SM4_ENC_TEST` | 0x45 | write_ptr | `SleConnData` |
| `SEC_SM4_DEC_TEST` | 0x46 | write_ptr | `SleConnData` |
| `SEC_SM4_BLOCK_TEST` | 0x47 | readwrite | `SleSm4BlockTest` |
| `SEC_HMAC_TEST` | 0x48 | readwrite | `SleHmacTest` |
| `SEC_RESET` | 0x49 | none | — |
| `SEC_GET_PASSKEY` | 0x4A | read | `u32` |
| `SEC_CONFIRM_PASSKEY` | 0x4B | none | — |
| `SEC_REJECT_PASSKEY` | 0x4C | none | — |
| `SEC_SET_OOB` | 0x4D | write_ptr | `SleOobData` |
| `SEC_INPUT_PASSKEY` | 0x4E | write_ptr | `SlePasskeyInput` |
| `SEC_SET_PASSWORD` | 0x4F | write_ptr | `SlePasswordParams` |

## SSAP 服务 (0x50-0x5F, 0x6F, 0x72)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `SSAP_REGISTER_SVC` | 0x50 | none | — |
| `SSAP_INFO` | 0x51 | read | `SsapSummary` |
| `SSAP_READ` | 0x52 | readwrite | `SsapReadWrite` |
| `SSAP_WRITE` | 0x53 | write_ptr | `SsapReadWrite` |
| `SSAP_FIND_SVC` | 0x54 | read | `SsapServiceList` |
| `SSAP_NOTIFY` | 0x55 | write_int | prop_handle |
| `SSAP_DEQUEUE_NTF` | 0x56 | read | `SsapNotification` |
| `SSAP_ADD_SVC` | 0x57 | readwrite | `SsapAddService` |
| `SSAP_ADD_PROP` | 0x58 | readwrite | `SsapAddProperty` |
| `SSAP_REMOVE_SVC` | 0x59 | write_int | svc_handle |
| `SSAP_EXCHANGE_INFO` | 0x5A | write_ptr | `SsapRemoteCmd` |
| `SSAP_REMOTE_DISCOVER` | 0x5B | readwrite | `SsapRemoteDiscover` |
| `SSAP_REMOTE_READ` | 0x5C | readwrite | `SsapRemoteReadWrite` |
| `SSAP_REMOTE_WRITE` | 0x5D | write_ptr | `SsapRemoteReadWrite` |
| `SSAP_REMOTE_EVENT` | 0x5E | read | `SsapNotification` |
| `SSAP_CALL_METHOD` | 0x5F | readwrite | `SsapRemoteReadWrite` |
| `SSAP_FIND_BY_UUID` | 0x6F | readwrite | `SsapUuidOp` |
| `SSAP_READ_BY_UUID` | 0x72 | readwrite | `SsapUuidOp` |

## 功率管理 (0x60-0x65)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `PM_INFO` | 0x60 | read | `SlePmInfo` |
| `PM_SET_STATE` | 0x61 | write_ptr | `SlePmStateCmd` |
| `PM_SET_INTERVAL` | 0x62 | write_ptr | `SlePmInterval` |
| `PM_FORCE_ACTIVE` | 0x63 | write_int | — |
| `PM_TICK` | 0x64 | none | — |
| `PM_ACTIVITY` | 0x65 | none | — |

## 同步链路 (0x66-0x6E)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `SYNC_UCAST_PARAM` | 0x66 | readwrite | `SleSyncCigConfig` |
| `SYNC_UCAST_CREATE` | 0x67 | write_ptr | `SleSyncCreateCmd` |
| `SYNC_UCAST_REMOVE` | 0x68 | write_int | handle |
| `SYNC_MCAST_PARAM` | 0x69 | readwrite | `SleSyncBigConfig` |
| `SYNC_MCAST_CREATE` | 0x6A | write_ptr | `SleSyncCreateCmd` |
| `SYNC_MCAST_REMOVE` | 0x6B | write_int | handle |
| `SYNC_DATAPATH_CFG` | 0x6C | write_ptr | `SleSyncDatapathCmd` |
| `SYNC_DATAPATH_REMOVE` | 0x6D | write_int | handle |
| `SYNC_INFO` | 0x6E | readwrite | `SleSyncLinkInfo` |

## 事件队列 (0x70-0x71)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `EVENT_COUNT` | 0x70 | none | — (返回值) |
| `EVENT_STATS` | 0x71 | read | `SleEventStats` |

## DLI 控制器 (0x80-0x87)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `DLI_INFO` | 0x80 | read | `SleDliInfo` |
| `USB_DEV_COUNT` | 0x81 | none | — (返回值) |
| `DLI_POLL_EVENT` | 0x82 | read | `SleDliEvent` |
| `DLI_RESET` | 0x83 | none | — |
| `DLI_SEND_CMD` | 0x84 | readwrite | `SleDliCmd` |
| `MGMT_STATS` | 0x85 | read | `SleMgmtStats` |
| `SUBSYS_STATS` | 0x86 | read | `SleSubsysStats` |
| `CONTROLLER_EVENT_GET` | 0x87 | readwrite | `SleControllerEventQuery` (360 bytes) |

`CONTROLLER_EVENT_GET` version 1 是独立的完整原生事件通路，当前接入已校验的
WS73 `0x180b` 发现报告。它不会改变旧 44 字节普通事件或 256 字节 DLI 事件
布局，也不表示原生扫描已开放。`SleControllerEvent` 固定 336 字节，payload
最多 288 字节，保留设备 index/generation、profile、原始 event code、完整
参数、CLOCK_BOOTTIME 接收时间、每次注册独立的 sequence 和覆盖丢失计数。
管理回复仍走现有 Host 事务，不通过这个日志完成命令。

输入 version=1、flags=0；初次可使用 after_seq=0/generation=0，之后使用响应
generation 和上次 seq。多个读者独立读取或回放保留记录，不竞争出队。
日志保留 32 条；`lost` 表示请求游标到响应之间被覆盖的条数。EAGAIN 表示
没有更新，未知版本为 EOPNOTSUPP，未来游标/错误 flags 为 EINVAL，旧 generation
或设备移除为 ENODEV。copyout 失败不确认记录。C 的 64 位字段明确按 8 字节
对齐，32 位 C 检查和 Rust 镜像均保证相同大小、偏移和 ioctl 编号。

调用 GET（含 EAGAIN）会将该 fd 的 poll 切到该注册的原生流；此模式不报告
旧队列的可读状态。使用独立打开且已 `select_device` 的 fd。设备移除唤醒
POLLHUP/POLLERR；重新选择会清空订阅，复用 index 不会重定向旧绑定。

Rust 同步接口是 `Adapter::poll_controller_event(&mut ControllerEventCursor)`。
异步接口 `Adapter::into_controller_event_receiver()` 转移 fd 所有权，要求
Tokio I/O runtime；`try_next()` 非阻塞，`next_event().await` 使用内核的每设备
poll 唤醒，不使用旧 destructive DLI fallback。取消等待不会改游标；未知内核
接口返回 ioctl 错误。`SleControllerEvent::ws73_discovery()` 提供借用 header/data
和有符号 RSSI，严格验证长度与 profile/code，并保留分片状态及厂商字段。
应用必须处理 `lost`，并按完整事件状态/新标识判断新发现，不能把截断或旧记录
当作新一轮匹配。该接口尚未接入 slkd 的动态 adapter/slctl 业务。

## PHY 层 (0x90-0x97)

当前这些旧接口全部明确返回不支持（通过既有权限和Runtime检查后为EOPNOTSUPP）。
PHY_INFO不再把本地默认模型返回为硬件快照。legacy SEC_ENCRYPT_ON同样不支持，
不能在匹配硬件完成前标记加密。真实PHY/每连接认证安装仍待实现；见
[状态整改与开放门禁](LINK_STATE_REMEDIATION.md)。下表仅记录未发布旧编号。

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `PHY_INFO` | 0x90 | read | `SlePhyInfo` |
| `PHY_SET_MCS` | 0x91 | write_ptr | `SlePhyMcsCmd` |
| `PHY_SET_TXPOWER` | 0x92 | write_ptr | `SlePhyTxPowerCmd` |
| `PHY_MCS_SELECT` | 0x93 | readwrite | `SlePhyMcsSelect` |
| `PHY_HOP_NEXT` | 0x94 | read | `SlePhyHopInfo` |
| `PHY_SET_BW` | 0x95 | write_ptr | `SlePhyBwCmd` |
| `PHY_GET_SINR` | 0x96 | read | `SleSinrThresholds` |
| `PHY_SET_SINR` | 0x97 | write_ptr | `SleSinrThresholds` |

## 能力协商 (0x98-0x9B)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `CONN_READ_PEER_FEATURES` | 0x98 | readwrite | `SleConnPeerCap` |
| `CONN_READ_PEER_VERSION` | 0x99 | readwrite | `SleConnPeerCap` |
| `CONN_UPDATE_PARAMS` | 0x9A | write_ptr | `SleConnParamUpdate` |
| `CONN_PHY_UPDATE` | 0x9B | write_ptr | `SleConnPhyUpdate` |

## 角色 (0xA0-0xA1)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `SET_ROLE` | 0xA0 | write_int | role (0=T, 1=G) |
| `GET_ROLE` | 0xA1 | read | `u8` |

## RAL/RPA (0xB0-0xB7)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `RAL_ADD` | 0xB0 | write_ptr | `SleRalAddParams` |
| `RAL_REMOVE` | 0xB1 | write_ptr | `SleRalRemoveParams` |
| `RAL_CLEAR` | 0xB2 | none | — |
| `RAL_SIZE` | 0xB3 | read | `u8` |
| `RAL_READ_PEER_RPA` | 0xB4 | readwrite | `SleRalQueryParams` |
| `RAL_READ_LOCAL_RPA` | 0xB5 | readwrite | `SleRalQueryParams` |
| `RPA_ENABLE` | 0xB6 | write_int | 0/1 |
| `RPA_SET_TIMEOUT` | 0xB7 | write_int | seconds |

## 测距 (0xC0-0xC3)

| CMD | 序号 | 方向 | 参数类型 |
|-----|------|------|----------|
| `MEAS_READ_CAP` | 0xC0 | read | `SleMeasCap` |
| `MEAS_SET_LINK_PARAM` | 0xC1 | write_ptr | `SleMeasLinkParam` |
| `MEAS_ACTION` | 0xC2 | write_ptr | `SleMeasAction` |
| `MEAS_ENABLE` | 0xC3 | write_int | 0/1 |

## 核心数据类型

```rust
pub type SleAddr = [u8; 6];

#[repr(C)]
pub struct SciDevInfo {
    pub index: u16,
    pub state: u8,
    pub bus: u8,
    pub addr: SleAddr,
    pub name: [u8; 32],
    pub _reserved: [u8; 24],
}

#[repr(C)]
pub struct SleScanParams {
    pub dev_index: u16,
    pub window_ms: u16,
    pub interval_ms: u16,
    pub filter_discovery_level: u8,
    pub _reserved: [u8; 9],
}

#[repr(C)]
pub struct SleConnInfo {
    pub handle: u16,
    pub state: u8,
    pub role: u8,
    pub peer_addr: SleAddr,
    pub mtu: u16,
    pub mps: u16,
    pub tx_credits: u16,
    pub rx_credits: u16,
    pub rssi: i8,
    pub _reserved: [u8; 7],
}
```

完整类型定义参见 `crates/slk-protocol/src/types.rs`（922 行，80+ 结构体）。
#[repr(C)]
pub struct SleConnectParams {
    pub peer_addr: SleAddr,
    pub peer_addr_type: u8,
    pub conn_interval_min: u16,
    pub conn_interval_max: u16,
    pub conn_latency: u16,
    pub supervision_timeout: u16,
}

#[repr(C)]
pub struct SleConnInfo {
    pub tx_bytes: u64,
    pub rx_bytes: u64,
    pub handle: u16,
    pub role: u8,
    pub state: u8,
    pub peer_addr: SleAddr,
    pub peer_addr_type: u8,
    pub conn_interval: u16,
    pub conn_latency: u16,
    pub supervision_timeout: u16,
}
```

### Generic Netlink

- Family: `"sparklink"`
- GenlCmd: 32 variants (0..=33, removed 2/3)
- GenlAttr: 59 variants (0..=58)

## libsparklink

### Adapter

异步设备适配器，所有方法均通过 ioctl 与内核 `/dev/sparklink` 字符设备通信。

#### 创建与销毁

```rust
let adapter = Adapter::open("/dev/sparklink")?;
```

#### 设备管理 (6 方法)

| 方法 | 功能 |
|------|------|
| `device_info()` | 读取设备信息 |
| `device_version()` | 固件/硬件版本 |
| `reset()` | 复位设备 |
| `get_stats()` | 统计信息 |
| `get_features()` | 能力查询 |
| `set_device_name()` | 设置名称 |

#### 扫描 (4 方法)

| 方法 | 功能 |
|------|------|
| `set_scan_params(params)` | 配置扫描参数 |
| `start_scan()` | 启动扫描 |
| `stop_scan()` | 停止扫描 |
| `get_scan_results()` | 获取扫描结果 |

#### 连接 (5 方法)

| 方法 | 功能 |
|------|------|
| `connect(params)` | 发起连接 |
| `disconnect(handle)` | 断开连接 |
| `get_conn_info(handle)` | 查询连接信息 |
| `get_conn_list()` | 枚举活跃连接 |
| `update_conn_params(params)` | 更新连接参数 |

#### 安全 (11 方法)

| 方法 | 功能 |
|------|------|
| `set_psk(handle, psk)` | 设置预共享密钥 |
| `pair(handle)` | 发起配对 |
| `cancel_pair(handle)` | 取消配对 |
| `unpair(handle)` | 解除配对 |
| `encrypt(handle)` | 启用加密 |
| `set_security_level(handle, level)` | 设置安全等级 |
| `get_security_level(handle)` | 查询安全等级 |
| `set_auth_mode(handle, mode)` | 设置认证模式 |
| `get_auth_mode(handle)` | 查询认证模式 |
| `set_io_capability(cap)` | 设置 IO 能力 |
| `security_reset(handle)` | 重置安全状态 |

#### SSAP 服务 (15 方法)

| 方法 | 功能 |
|------|------|
| `register_service(svc)` | 注册本地服务 |
| `unregister_service(handle)` | 注销服务 |
| `add_characteristic(...)` | 添加特征 |
| `remove_characteristic(...)` | 移除特征 |
| `set_characteristic_value(...)` | 写入特征值 |
| `get_characteristic_value(...)` | 读取特征值 |
| `notify(...)` | 发送通知 |
| `indicate(...)` | 发送指示 |
| `discover_services(handle)` | 发现远端服务 |
| `discover_characteristics(...)` | 发现特征 |
| `read_remote(...)` | 读远端特征 |
| `write_remote(...)` | 写远端特征 |
| `subscribe(...)` | 订阅通知 |
| `unsubscribe(...)` | 取消订阅 |
| `list_services()` | 列出本地服务 |

### Event 枚举

```rust
pub enum Event {
    ConnectionStateChanged { handle: u16, connected: bool },
    AdvReport { addr: SleAddr, rssi: i8, data: Vec<u8> },
    DataReceived { handle: u16, data: Vec<u8> },
    SecurityChanged { handle: u16, level: u8, encrypted: bool },
    PowerChanged { powered: bool },
    HwError { code: u32 },
    RawDli { data: Vec<u8> },
    ConnInfoUpdate { info: SleConnInfo },
}
```

### Error 类型

```rust
pub enum Error {
    OpenDevice(std::io::Error),
    Ioctl(nix::Error),
    DeviceNotFound,
    ConnectionNotFound,
    InvalidParam,
    Timeout,
}
```

## C FFI

通过 `sparklink.h` 头文件提供 C 接口，20 个导出函数:

```c
// 生命周期
SlkAdapter *slk_adapter_open(const char *path);
void slk_adapter_free(SlkAdapter *adapter);

// 设备
int32_t slk_device_info(SlkAdapter *adapter, SciDevInfo *info);
int32_t slk_device_reset(SlkAdapter *adapter);

// 扫描
int32_t slk_set_scan_params(SlkAdapter *adapter, const SleScanParams *params);
int32_t slk_start_scan(SlkAdapter *adapter);
int32_t slk_stop_scan(SlkAdapter *adapter);

// 连接
int32_t slk_connect(SlkAdapter *adapter, const SleConnectParams *params);
int32_t slk_disconnect(SlkAdapter *adapter, uint16_t handle);
int32_t slk_get_conn_info(SlkAdapter *adapter, uint16_t handle, SleConnInfo *info);

// 安全
int32_t slk_pair(SlkAdapter *adapter, uint16_t handle);
int32_t slk_cancel_pair(SlkAdapter *adapter, uint16_t handle);
int32_t slk_encrypt(SlkAdapter *adapter, uint16_t handle);
int32_t slk_set_psk(SlkAdapter *adapter, uint16_t handle,
                     const uint8_t *psk, uintptr_t psk_len);

// SSAP 服务
int32_t slk_discover_services(SlkAdapter *adapter, uint16_t handle);
int32_t slk_read_remote_char(SlkAdapter *adapter, uint16_t conn_handle,
                              uint16_t char_handle, uint8_t *buf, uintptr_t buf_len);
int32_t slk_write_remote_char(SlkAdapter *adapter, uint16_t conn_handle,
                               uint16_t char_handle, const uint8_t *data, uintptr_t data_len);

// 事件
int32_t slk_poll_event(SlkAdapter *adapter, SlkEvent *event);
int32_t slk_set_event_filter(SlkAdapter *adapter, uint32_t mask);

// 广播
int32_t slk_set_adv_data(SlkAdapter *adapter, const uint8_t *data, uintptr_t len);
```

所有函数返回 `0` 表示成功，负值表示 errno 错误码。`SlkAdapter` 为不透明指针类型。

## Python 绑定

基于 ctypes 的 Python 绑定提供与 C FFI 相同的 20 个方法。

```python
from sparklink import Adapter, SciDevInfo, SleScanParams

# 使用上下文管理器自动释放资源
with Adapter("/dev/sparklink") as adpt:
    info = adpt.device_info()
    
    params = SleScanParams()
    params.scan_type = 0
    params.interval = 100
    params.window = 50
    params.duration = 5
    adpt.set_scan_params(params)
    
    adpt.start_scan()
    event = adpt.poll_event()
    adpt.stop_scan()
```

结构体类型对照:

| Python | Rust | 大小 (bytes) |
|--------|------|-------------|
| `SciDevInfo` | `SciDevInfo` | 152 |
| `SleScanParams` | `SleScanParams` | 10 |
| `SleConnectParams` | `SleConnectParams` | 16 |
| `SleConnInfo` | `SleConnInfo` | 32 |
| `SleAdvReport` | `SleAdvReport` | 40 |
| `SleConnData` | `SleConnData` | 260 |
| `SleSecurityInfo` | `SleSecurityInfo` | 4 |
| `SleSsapService` | `SleSsapService` | 40 |
| `SleSsapCharacteristic` | `SleSsapCharacteristic` | 12 |
| `SlePhyParams` | `SlePhyParams` | 4 |
| `SleDeviceStats` | `SleDeviceStats` | 48 |
| `SlkEvent` | — (FFI only) | 268 |
