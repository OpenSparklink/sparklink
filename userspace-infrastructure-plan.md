# SparkLink 用户态基础设施规划

## 一、当前内核态已实现功能

### 1.1 设备层 (Device Layer)

内核通过 `/dev/sparklink` 字符设备和 Generic Netlink 提供控制面和数据面接口。

| 类别 | ioctl 数量 | 说明 |
|------|-----------|------|
| 设备管理 | 8 | 设备注册/注销、固件加载、复位、电源模式、全局状态查询 |
| 广播/扫描 | 17 | 广播参数配置、启停、扫描参数/过滤、扫描启停、原始广播注入 |
| 连接管理 | 10 | 发起/接受/断开连接、更新参数、连接信息查询、数据注入 |
| 自适应跳频 | 6 | 信道分类、信道图设置/读取、模式设定 |
| 安全管理 | 16 | 配对发起/响应/确认、密钥分发/删除、加密启停、隐私地址 |
| SSAP 服务 | 15 | 服务注册/注销、特征值读写通知、服务发现、MTU 协商 |
| 功率管理 | 6 | 发射功率查询/设置、RSSI 读取、功率范围 |
| 同步链路 | 9 | 同步参数配置、同步建立/释放、同步数据路径 |
| 事件/DLI | 9 | 事件过滤、原始 DLI 帧收发、命令状态查询 |
| PHY | 8 | MCS 索引配置、带宽选择、调制参数、PHY 表查询 |
| 能力交换 | 4 | 能力查询/响应、特性协商 |
| 角色管理 | 2 | G-node/T-node 角色切换 |
| 地址管理 | 8 | RAL(地址解析列表)增删查、RPA 控制 |
| 测量 | 4 | RSSI/链路质量/信道统计测量 |
| **合计** | **~112** | |

### 1.2 DLI 协议栈

内核完整实现了 TXS-10003-2025 定义的 DLI 接口：

- **H4 风格帧封装**：0xA1(命令)、0xA2(事件)、0xA3-0xA5(数据)
- **命令分组**：OGF 1~10 共约 80+ 条命令操作码，涵盖设备控制、连接、安全、SSAP、PHY 等
- **事件体系**：50+ 种事件类型，含 CommandComplete、ConnectionComplete、EncryptionChange、SSAP 事件等
- **传输后端**：USB (`sle_usb.rs`)、UART/SerDev (`sle_serdev.rs`) 两种物理传输
- **命令队列**：异步命令派发 → 序列号追踪 → 事件回填 → 超时处理

### 1.3 Generic Netlink

内核注册了 `sparklink` Netlink family，提供：

- **Commands**：`GET_DEVICE_LIST`、`GET_DEVICE_INFO`、`GET_CONN_INFO`、`DLI_INFO`、`SEND_DLI_CMD`、`DLI_EVENT`
- **Multicast Groups**：`events`（设备状态变更）、`dli`（DLI 事件广播）、`monitor`（调试监控）
- **属性集**：设备 ID、MAC、总线类型、状态标志、连接信息、DLI 帧数据

### 1.4 安全模型

内核实现了 TXS-10002-2025 第 9 章定义的配对状态机：

| 阶段 | 状态 | 说明 |
|------|------|------|
| 1 | Idle → Pairing | 发起/接受配对请求 |
| 2 | Pairing → KeyExchange | 公钥交换 (SM2) |
| 3 | KeyExchange → Authenticating | 确认值校验 |
| 4 | Authenticating → Distributing | 密钥分发 (LTK/IRK) |
| 5 | Distributing → Bonded | 密钥存储完成 |
| 6 | Bonded → Encrypted | 链路加密激活 |

- **配对方式**：JustWorks、数字比较、PasskeyEntry、OOB、PinCode、数字比较+OOB（共 6 种）
- **密码学**：SM2 (椭圆曲线)、SM3 (哈希)、SM4 (对称加密)
- **隐私地址**：RAL 管理、RPA 生成/解析

### 1.5 SSAP 服务协议

内核实现了 SSAP (SparkLink Service Access Protocol) 的底层状态机：

- **服务数据库**：主服务/从服务/特征值/描述符的注册存储
- **PDU 类型**：16 种 SSAP 消息码（ServiceDiscovery、CharDiscovery、Read、Write、Notify、Indicate、MethodCall 等）
- **操作指示器**：Request、Response、Confirm、Indication 四种方向
- **内建服务**：设备信息服务（固件版本、硬件版本、序列号等）

### 1.6 传输通道

内核实现了 TXS-20002-2025 定义的传输通道管理：

- **固定通道**：CMTC (0x02, 管理)、SMTC (0x0A, 服务)、默认数据 (0x1F)
- **传输模式**：Basic (无确认)、Stream (序列号+超时)、Reliable (ACK+重传)、Transparent (透传)
- **信用授权流控**：自定义 0xFC 信令，8 字节 PDU 格式，对齐 TXS-20002-2025 §7.3.3 信令封装格式
- **SDU/PDU 分片与重组**

### 1.7 辅助子系统

- **configfs** (`/config/sparklink/`)：设备名称、MAC、广播参数、安全策略、PHY 配置、调试开关
- **debugfs** (`/sys/kernel/debug/sparklink/`)：连接表/服务表转储、DLI 帧追踪、统计计数器、事件日志、命令历史
- **固件加载**：request_firmware 机制 + FW_MAX_SIZE=4MiB 校验
- **多控制器**：最多 16 个设备并行注册，per-fd 设备亲和绑定

---

## 二、标准对用户态的要求

根据 TXS-00001-2025 三层架构模型，SparkLink 协议栈分为：

```
┌─────────────────────────────────────────────┐
│         基本应用层 (Application Layer)        │  ← 用户态
│  音频 / 视频 / HID / 车钥匙 / 定位 / 电源    │
├─────────────────────────────────────────────┤
│         基本服务层 (Service Layer)            │  ← 用户态
│  设备发现 / 服务管理 / 连接管理 / 传输适配     │
├─────────────────────────────────────────────┤
│      数据链路接口 (DLI)                       │  ← 内核 (已实现)
├─────────────────────────────────────────────┤
│      无线接入层 (Radio Access Layer)          │  ← 固件/内核 (已实现)
└─────────────────────────────────────────────┘
```

**标准明确划分**：DLI 是 Host 与 Controller 的硬边界。DLI 以上的基本服务层和应用层均属于 Host 侧，需要在用户态实现。

当前内核已经将部分服务层功能（SSAP 状态机、传输通道管理、安全配对）下沉到了内核，这与 BlueZ 的做法类似——内核处理 L2CAP/SMP/ATT 核心协议，用户态守护进程处理 GAP/GATT/Profile 层。

---

## 三、用户态基础设施完整规划

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     应用程序 (Applications)                      │
│  slctl · sl-audio · sl-hid · sl-carkey · 第三方应用              │
├─────────────────┬───────────────────────┬───────────────────────┤
│   D-Bus API     │   libsparklink crate  │   C FFI / 语言绑定    │
│  (zbus IPC)     │   (Rust 原生 API)      │   (.so + .h)         │
├─────────────────┴───────────────────────┴───────────────────────┤
│                   sparklink-daemon (slkd)                        │
│  ┌──────────┬──────────┬──────────┬──────────┬────────────┐     │
│  │发现管理器 │连接管理器 │服务管理器 │安全管理器 │ 配置文件管理 │     │
│  │Discovery │ConnMgr   │SvcMgr   │SecMgr   │ ProfileMgr │     │
│  ├──────────┴──────────┴──────────┴──────────┴────────────┤     │
│  │                  核心协议引擎 (Core Engine)               │     │
│  │  ┌────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────┐  │     │
│  │  │SSAP    │ │Transport│ │Signaling │ │Event Router │  │     │
│  │  │Client/ │ │Channel  │ │Codec     │ │& Dispatcher │  │     │
│  │  │Server  │ │Manager  │ │(§7.3.3)  │ │             │  │     │
│  │  └────────┘ └─────────┘ └──────────┘ └─────────────┘  │     │
│  ├────────────────────────────────────────────────────────┤     │
│  │              内核接口适配层 (Kernel Adaptor)              │     │
│  │  ioctl fd · netlink socket · configfs · debugfs        │     │
│  └────────────────────────────────────────────────────────┘     │
├─────────────────────────────────────────────────────────────────┤
│                    Linux Kernel (已实现)                         │
│  /dev/sparklink · Generic Netlink · configfs · debugfs          │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 组件详细设计

---

#### 组件 1：sparklink-daemon (slkd)

**对标 BlueZ 中的 bluetoothd**

核心守护进程，是整个用户态协议栈的枢纽。所有其他组件通过 D-Bus 与之交互，它独占 `/dev/sparklink` 设备文件。

**职责**：

| 模块 | 功能 | 对应标准 |
|------|------|---------|
| Discovery Manager | 设备发现策略执行、广播数据 TLV 解析与过滤、发现级别管控 | TXS-20001-2025 §6 |
| Connection Manager | 连接生命周期管理、参数协商、角色切换协调 | TXS-20002-2025 §7 |
| Service Manager | SSAP 客户端/服务器协议编排、服务缓存、句柄分配 | TXS-20001-2025 §7 |
| Security Manager | 配对流程编排（6 种方式）、密钥持久化、隐私策略 | TXS-10002-2025 §9 |
| Profile Manager | 应用配置文件加载/卸载、能力协商 | TXS-00001-2025 |
| Transport Adapter | 传输通道动态创建/销毁、QoS 参数配置 | TXS-20002-2025 §6 |
| Event Router | 内核事件分发、D-Bus 信号广播、状态同步 | 全部标准 |

**关键设计决策**：

(1) **异步事件驱动**：基于 tokio 异步运行时，使用 AsyncFd 同时监听 ioctl fd、netlink socket、D-Bus fd，充分利用 Rust async/await 的零开销抽象。

(2) **设备对象模型**：每个 SparkLink 控制器创建一个 `Adapter` 对象，每个远端设备创建 `Device` 对象，每个连接创建 `Connection` 对象。与 BlueZ 的 Adapter/Device 对象模型一致。

(3) **持久化存储**：
- 配对密钥存储在 `/var/lib/sparklink/<adapter-mac>/<peer-mac>/info`
- 已知服务缓存在 `/var/lib/sparklink/<adapter-mac>/<peer-mac>/services`
- 全局配置在 `/etc/sparklink/main.conf`
- 使用 serde + TOML 格式序列化配置，密钥文件使用受限文件权限（0600）

(4) **插件机制**：Profile 实现基于 Rust trait object 动态分发。内建 Profile 通过 `inventory` crate 自动注册，外部 Profile 通过 `libloading` 加载共享库（`.so`），共享库导出 C ABI 入口并返回 trait object。

**实现语言选择**：Rust — 与内核侧 SparkLink 子系统保持语言统一，共享类型定义和协议常量；内存安全保证消除了守护进程中常见的 UAF/溢出类漏洞；async/await 天然适配事件驱动架构。对外通过 `cdylib` 导出 C ABI 供其他语言绑定调用。

**进程管理**：systemd unit, 启动类型 `Type=dbus`，Bus name `org.sparklink`。

---

#### 组件 2：D-Bus API

**对标 BlueZ 的 org.bluez D-Bus 接口**

D-Bus 是应用程序和守护进程之间的标准 IPC 通道。定义以下对象路径和接口：

```
/org/sparklink                          → org.sparklink.AgentManager
/org/sparklink/slk0                     → org.sparklink.Adapter
/org/sparklink/slk0/dev_AABBCCDDEEFF   → org.sparklink.Device
/org/sparklink/slk0/dev_.../service0001 → org.sparklink.Service
/org/sparklink/slk0/dev_.../char0002    → org.sparklink.Characteristic
/org/sparklink/slk0/dev_.../char0002/desc0003 → org.sparklink.Descriptor
```

**核心接口定义**：

```
interface org.sparklink.Adapter {
    // 方法
    StartDiscovery(dict filter)
    StopDiscovery()
    SetDiscoveryFilter(dict filter)       // MAC/名称/UUID 过滤
    RemoveDevice(object device)
    ConnectDevice(dict properties)        // 直接按 MAC 连接

    // 属性
    Address         : string              // 本机 MAC
    Name            : string              // 本机名称
    Powered         : boolean             // 电源开关
    Discoverable    : boolean             // 可发现
    DiscoverableLevel : byte              // TXS-20001 发现级别
    Discovering     : boolean             // 正在扫描
    Roles           : array<string>       // ["g-node", "t-node"]
    PhyConfig       : dict                // MCS/带宽/功率

    // 信号
    DeviceFound(object device)
    DeviceLost(object device)
}

interface org.sparklink.Device {
    // 方法
    Connect()
    Disconnect()
    Pair()
    CancelPairing()
    ConnectService(object service)

    // 属性
    Address         : string
    Name            : string
    Paired          : boolean
    Bonded          : boolean
    Connected       : boolean
    RSSI            : int16
    TxPower         : int16
    ServicesResolved : boolean
    ServiceUUIDs    : array<string>
    ManufacturerData : dict<uint16, bytes>
    AdvertisingData : dict<byte, bytes>   // TLV 广播字段
}

interface org.sparklink.Service {
    UUID            : string
    Primary         : boolean
    Device          : object
    Characteristics : array<object>
}

interface org.sparklink.Characteristic {
    // 方法
    ReadValue(dict options) → bytes
    WriteValue(bytes value, dict options)
    StartNotify()
    StopNotify()
    CallMethod(string name, bytes params) → bytes  // SSAP Method

    // 属性
    UUID            : string
    Service         : object
    Value           : bytes
    Flags           : array<string>       // ["read","write","notify","indicate","method"]
    Notifying       : boolean
}

interface org.sparklink.AgentManager {
    RegisterAgent(object agent, string capability)
    UnregisterAgent(object agent)
    RequestDefaultAgent(object agent)
}

interface org.sparklink.Agent {
    // 由应用程序实现，daemon 回调
    RequestPinCode(object device) → string
    RequestPasskey(object device) → uint32
    DisplayPasskey(object device, uint32 passkey)
    RequestConfirmation(object device, uint32 passkey)
    AuthorizeService(object device, string uuid)
    Cancel()
}
```

---

#### 组件 3：libsparklink

**对标 BlueZ 的 libbluetooth**

Rust crate，同时提供 Rust 原生 API 和 C FFI 导出层。Rust 应用直接依赖 crate，C/Python/Go 等语言通过 `libsparklink.so` 的 C ABI 接口调用。

**Crate 模块结构**：

```
libsparklink/
├── src/
│   ├── lib.rs            // crate 入口，pub mod 导出
│   ├── adapter.rs        // 适配器管理
│   ├── device.rs         // 远端设备
│   ├── discovery.rs      // 扫描与发现
│   ├── connection.rs     // 连接管理
│   ├── service.rs        // SSAP 服务管理
│   ├── security.rs       // 配对与密钥
│   ├── transport.rs      // 传输通道
│   ├── dli.rs            // 原始 DLI 帧读写
│   ├── event.rs          // 事件订阅
│   ├── types.rs          // 公共类型 (SlkAddr, SlkUuid, Error)
│   └── ffi.rs            // C ABI 导出层 (#[no_mangle] extern "C")
├── include/
│   └── sparklink.h       // 自动生成的 C 头文件 (cbindgen)
└── Cargo.toml
```

**Rust API 示例**：

```rust
use libsparklink::{Adapter, ScanParams, ScanFilter, Connection, SsapClient};

// 打开适配器
let adapter = Adapter::open("/dev/sparklink")?;

// 扫描
let params = ScanParams::default();
adapter.start_scan(&params).await?;
let mut events = adapter.subscribe_events();
while let Some(event) = events.next().await {
    match event {
        Event::DeviceFound(dev) => println!("{}: {}", dev.addr(), dev.name()),
        _ => {}
    }
}
adapter.stop_scan().await?;

// 连接
let conn = adapter.connect(&addr, &ConnParams::default()).await?;

// SSAP 服务发现
let services = conn.discover_services(Uuid::MIN..Uuid::MAX).await?;
for svc in &services {
    let chars = conn.discover_characteristics(svc).await?;
    for ch in &chars {
        if ch.flags().contains(CharFlags::READ) {
            let val = conn.read_char(ch.handle()).await?;
            println!("  {} = {:?}", ch.uuid(), val);
        }
    }
}

// 订阅通知
let mut notifs = conn.subscribe_notify(handle).await?;
while let Some(value) = notifs.next().await {
    println!("notify: {:?}", value);
}
```

**C FFI 导出** (通过 cbindgen 自动生成头文件)：

```c
/* 自动生成的 sparklink.h */
typedef struct SlkAdapter SlkAdapter;
typedef struct SlkConnection SlkConnection;

SlkAdapter *slk_adapter_open(const char *dev);
void        slk_adapter_free(SlkAdapter *adapter);
int         slk_adapter_start_scan(SlkAdapter *adapter, const SlkScanParams *params);
int         slk_adapter_stop_scan(SlkAdapter *adapter);

SlkConnection *slk_connect(SlkAdapter *adapter, const SlkAddr *addr);
void            slk_connection_free(SlkConnection *conn);
int             slk_read_char(SlkConnection *conn, uint16_t handle,
                              SlkReadCallback cb, void *userdata);
```

**构建系统**：Cargo workspace，`crate-type = ["rlib", "cdylib"]`，安装产物：
- `libsparklink.so` — C FFI 共享库
- `sparklink.h` — cbindgen 生成的 C 头文件
- `sparklink.pc` — pkg-config 文件（面向 C 消费者）
- Rust crate 通过 `cargo add libsparklink` 直接依赖

---

#### 组件 4：slctl — 交互式控制工具

**对标 BlueZ 的 bluetoothctl**

命令行交互式管理工具，通过 D-Bus API 与 daemon 通信。

```
$ slctl
[slk]# list                          # 列出本机适配器
Controller AA:BB:CC:DD:EE:FF slk0 [default]

[slk]# show                          # 显示适配器详情
Controller AA:BB:CC:DD:EE:FF
  Name: SparkLink-Host
  Powered: yes
  Discoverable: yes (level: general)
  Role: g-node

[slk]# scan on                       # 启动扫描
Discovery started
[NEW] Device 11:22:33:44:55:66 SLK-Sensor

[slk]# scan off
[slk]# info 11:22:33:44:55:66        # 查看远端设备
Device 11:22:33:44:55:66
  Name: SLK-Sensor
  RSSI: -45 dBm
  Services: 0x180A (Device Info), 0x1810 (Custom Sensor)
  Paired: no

[slk]# pair 11:22:33:44:55:66        # 发起配对
Attempting to pair...
[agent] Confirm passkey 482610 (yes/no): yes
Pairing successful

[slk]# connect 11:22:33:44:55:66     # 建立连接
Connection successful

[slk]# services                       # 列出远端服务
Primary Service: 0x180A (Device Information)
  Characteristic: 0x2A29 (Manufacturer)  [read]
  Characteristic: 0x2A24 (Model Number)  [read]
Primary Service: 0x1810 (Sensor Data)
  Characteristic: 0x2B01 (Temperature)   [read, notify]
  Characteristic: 0x2B02 (Humidity)      [read, notify]

[slk]# read 0x2B01                    # 读取特征值
Value: 25.3°C (raw: 0xFD 0x00)

[slk]# notify on 0x2B01              # 订阅通知
Notification started
[CHG] 0x2B01 Value: 25.4°C
[CHG] 0x2B01 Value: 25.5°C

[slk]# disconnect
[slk]# quit
```

**实现**：Rust，使用 `rustyline` 提供交互补全和历史记录，通过 `zbus` crate 连接 daemon 的 D-Bus 接口。

---

#### 组件 5：slkmon — 协议分析器

**对标 BlueZ 的 btmon**

DLI 协议帧的实时捕获和解码工具，直接通过 Netlink `monitor` 多播组接收内核旁路帧。

```
$ slkmon
< DLI Command: SLE_SET_ADV_PARAMS (OGF=0x02, OCF=0x001)
    Interval Min: 100 (62.5ms)
    Interval Max: 200 (125ms)
    ADV Type: Connectable Undirected
> DLI Event: Command Complete
    Opcode: 0x0801
    Status: Success (0x00)
< DLI Data (TCID=0x0A): SSAP Service Discovery Request
    Start UUID: 0x0001
    End UUID: 0xFFFF
> DLI Data (TCID=0x0A): SSAP Service Discovery Response
    Service: 0x180A, Primary, Handle: 0x0001-0x000F
```

**功能**：
- 实时 DLI 帧解码（命令/事件/数据）
- SSAP PDU 内容解析
- 信令 PDU 解析（§7.3.3 格式）
- 过滤（按 OGF/OCF/TCID/方向）
- pcap-ng 格式存储，供 Wireshark 离线分析
- `-w` 写文件 / `-r` 读文件回放

---

#### 组件 6：slkdump — 链路层捕获

**对标 BlueZ 的 hcidump**

轻量级 DLI 帧转储工具，面向嵌入式调试场景，不依赖 daemon。

```
$ slkdump -i slk0 -X
> 01 A1 01 08 00 04 64 00 C8 00         CMD Set_Adv_Params
< 01 A2 0E 04 01 01 08 00               EVT Cmd_Complete
```

---

#### 组件 7：slkconfig — 离线配置工具

**对标 BlueZ 的 hciconfig + btmgmt**

直接通过 ioctl 操作控制器，不依赖 daemon 运行，面向系统初始化和故障排查。

```
$ slkconfig slk0 up                   # 激活控制器
$ slkconfig slk0 down                 # 停用
$ slkconfig slk0 name "MyDevice"      # 设置设备名
$ slkconfig slk0 reset                # 硬复位
$ slkconfig slk0 features             # 查询能力
$ slkconfig slk0 phy mcs 4 bw 2       # 配置 PHY 参数
```

---

#### 组件 8：Profile 插件框架

**对标 BlueZ 的 GATT Profile 插件**

每个「原子能力标准」对应一个 Profile 插件：

| 插件 | 标准 | 说明 |
|------|------|------|
| `sl_audio` | TXS-3xxxx (待发布) | 音频编解码协商、流建立、同步播放 |
| `sl_hid` | TXS-3xxxx (待发布) | HID 报告描述符解析、输入事件转发到 evdev |
| `sl_carkey` | TXS-3xxxx (待发布) | 数字车钥匙认证流程、交易日志 |
| `sl_devinfo` | 内建 | 设备信息服务 (0x180A)：厂商、型号、固件版本 |
| `sl_battery` | 内建 | 电池服务：电量、充电状态 |
| `sl_location` | TXS-3xxxx (待发布) | 定位信息服务 |

**插件接口 (Rust trait)**：

```rust
/// Profile 插件 trait，内建和外部插件均实现此接口
pub trait SlkProfile: Send + Sync {
    fn name(&self) -> &str;
    fn uuids(&self) -> &[SlkUuid];

    /// 设备连接时，UUID 匹配后调用
    fn probe(&self, dev: &SlkDevice) -> Result<()>;
    /// 设备断开时调用
    fn remove(&self, dev: &SlkDevice);
    /// 远端发起服务连接时
    fn accept(&self, dev: &SlkDevice, tcid: u16) -> Result<()>;
}

// 内建 Profile 通过 inventory crate 自动注册
inventory::submit! {
    ProfileEntry::new::<DevInfoProfile>()
}

// 外部 .so 插件导出 C ABI 入口
#[no_mangle]
pub extern "C" fn slk_profile_create() -> *mut dyn SlkProfile {
    Box::into_raw(Box::new(MyCustomProfile::new()))
}
```

---

#### 组件 9：配对代理框架

**对标 BlueZ 的 Agent API**

配对代理 (Pairing Agent) 是处理用户交互（输入 PIN、确认数字）的独立进程，通过 D-Bus 的 `org.sparklink.Agent` 接口与 daemon 通信。

- **桌面环境**：GNOME/KDE 提供图形化配对对话框
- **嵌入式无屏**：自动 JustWorks 代理，或通过 LED/蜂鸣器反馈
- **slctl 内建代理**：命令行交互式确认
- 支持 6 种配对方式的代理回调

---

#### 组件 10：语言绑定

| 语言 | 库名 | 方式 | 适用场景 |
|------|------|------|---------|
| C | `libsparklink.so` + `sparklink.h` | cdylib FFI (cbindgen 生成头文件) | 嵌入式、系统集成 |
| Python | `sparklink-python` | D-Bus (dasbus) 或 ctypes 加载 .so | 原型开发、自动化测试 |
| Go | `go-sparklink` | D-Bus (godbus) 或 cgo 加载 .so | 微服务、IoT 网关 |
| Rust | 直接依赖 `libsparklink` crate | 原生 Rust API，零开销 | 高性能应用、嵌入式 |

---

### 3.3 数据流

#### 设备发现流

```
应用 → D-Bus:StartDiscovery(filter)
  → slkd: Discovery Manager
    → ioctl(SET_SCAN_PARAMS)
    → ioctl(SET_SCAN_FILTER)   // MAC/名称/UUID
    → ioctl(START_SCAN)
  ← netlink event: ADV_REPORT
    → slkd: TLV 解析 (TXS-20001 §6.5)
    → slkd: 发现级别过滤
    → slkd: 创建/更新 Device 对象
  ← D-Bus signal: DeviceFound
← 应用收到新设备
```

#### 连接+服务发现流

```
应用 → D-Bus:Connect()
  → slkd: Connection Manager
    → ioctl(CONNECT)
  ← netlink event: CONN_COMPLETE(handle)
    → slkd: 能力交换 (CMTC, ioctl CAPABILITY_QUERY)
    → slkd: SSAP 服务发现 (SMTC)
      → ioctl(SSAP_DISCOVER_SERVICES)
      ← event: SSAP_DISCOVER_RESP
      → ioctl(SSAP_DISCOVER_CHARACTERISTICS)
      ← event: SSAP_DISCOVER_CHARS_RESP
    → slkd: 匹配 Profile 插件 → probe()
    → slkd: 缓存服务到文件系统
  ← D-Bus property: ServicesResolved=true
← 应用收到服务就绪
```

#### 数据读写流

```
应用 → D-Bus:ReadValue(handle)
  → slkd: Service Manager
    → ioctl(SSAP_READ_CHAR, handle)
  ← event: SSAP_READ_RESP(handle, value)
  ← D-Bus return: bytes

应用 → D-Bus:StartNotify(handle)
  → slkd: ioctl(SSAP_SUBSCRIBE, handle)
  ← event: SSAP_NOTIFY(handle, value)  // 重复
  ← D-Bus signal: PropertiesChanged(Value=...)
```

---

### 3.4 文件系统布局

```
/etc/sparklink/
├── main.conf                    # 全局配置
├── input.conf                   # HID 设备配置
├── audio.conf                   # 音频 Profile 配置
└── network.conf                 # 网络 Profile 配置

/var/lib/sparklink/
├── AA:BB:CC:DD:EE:FF/           # 每个适配器
│   ├── settings                 # 适配器本地配置
│   ├── 11:22:33:44:55:66/       # 每个配对设备
│   │   ├── info                 # 设备信息 + 密钥
│   │   ├── attributes           # 远端 SSAP 服务缓存
│   │   └── services             # 已发现服务 UUID 列表
│   └── cache/
│       └── ...                  # 临时缓存

/usr/lib/sparklink/plugins/      # Profile 插件目录
├── sl_audio.so
├── sl_hid.so
├── sl_devinfo.so              # 内建，可由 daemon 直接包含
└── ...

/usr/bin/
├── slctl                        # 交互式管理工具 (Rust)
├── slkmon                       # 协议分析器 (Rust)
├── slkdump                      # 帧转储工具 (Rust)
└── slkconfig                    # 离线配置工具 (Rust)

/usr/sbin/
└── slkd                         # 守护进程 (Rust)

/usr/lib/
└── libsparklink.so              # C FFI 共享库 (Rust cdylib)

/usr/include/sparklink/
└── sparklink.h                  # cbindgen 生成的 C 头文件

/usr/share/dbus-1/system-services/
└── org.sparklink.service        # D-Bus 服务声明

/usr/share/dbus-1/system.d/
└── sparklink.conf               # D-Bus 安全策略

/usr/lib/systemd/system/
└── sparklink.service            # systemd 服务单元
```

### 3.5 Cargo Workspace 结构

```
sparklink-userspace/
├── Cargo.toml                    # workspace 根配置
├── Cargo.lock
├── crates/
│   ├── libsparklink/             # 核心库 crate (rlib + cdylib)
│   │   ├── Cargo.toml
│   │   ├── src/
│   │   ├── include/              # cbindgen 生成的 C 头文件
│   │   └── build.rs              # cbindgen 构建脚本
│   ├── slkd/                     # 守护进程 (bin)
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs
│   │       ├── adapter.rs
│   │       ├── discovery.rs
│   │       ├── connection.rs
│   │       ├── service.rs
│   │       ├── security.rs
│   │       ├── profile.rs
│   │       ├── dbus/             # D-Bus 接口定义
│   │       └── kernel/           # 内核接口适配层
│   ├── slctl/                    # 交互式控制工具 (bin)
│   ├── slkmon/                   # 协议分析器 (bin)
│   ├── slkdump/                  # 帧转储工具 (bin)
│   ├── slkconfig/                # 离线配置工具 (bin)
│   └── slk-protocol/            # 协议常量与类型定义 (rlib, 内核/用户态共享)
├── plugins/
│   ├── sl_devinfo/               # 设备信息 Profile (内建)
│   ├── sl_battery/               # 电池 Profile (内建)
│   ├── sl_hid/                   # HID Profile
│   └── sl_audio/                 # 音频 Profile
├── tests/                        # 集成测试
├── data/
│   ├── dbus/                     # D-Bus 策略与服务声明
│   └── systemd/                  # systemd 服务单元
└── doc/                          # 文档
```

**核心依赖**：

| crate | 用途 |
|-------|------|
| `tokio` | 异步运行时、AsyncFd、信号处理 |
| `zbus` | 纯 Rust D-Bus 实现 (无 libdbus 依赖) |
| `nix` | ioctl/mmap/signal 等 POSIX 封装 |
| `netlink-generic` | Generic Netlink 通信 |
| `serde` + `toml` | 配置文件序列化 |
| `tracing` + `tracing-journald` | 结构化日志输出到 systemd-journal |
| `rustyline` | slctl 交互式命令行 |
| `clap` | CLI 参数解析 |
| `cbindgen` | 自动生成 C 头文件 |
| `libloading` | 运行时加载外部 Profile .so |
| `inventory` | 编译时自动注册内建 Profile |

---

### 3.5 开发阶段规划

#### 阶段 1：核心框架 (Foundation)

**目标**：建立 daemon 骨架和基础通信链路

| 任务 | 产出 | 依赖 |
|------|------|------|
| 1.1 daemon 主循环 | slkd 进程框架、tokio 异步事件循环、信号处理 | 无 |
| 1.2 内核接口适配层 | ioctl wrapper (nix crate)、netlink 订阅 (netlink-generic)、configfs 读写 | 1.1 |
| 1.3 D-Bus 骨架 | zbus 会话注册、对象路径、Introspection | 1.1 |
| 1.4 Adapter 对象 | 控制器枚举、Power on/off、基础属性 | 1.2 + 1.3 |
| 1.5 libsparklink 核心 | Adapter::open/close、事件循环、错误类型 | 无 |
| 1.6 slkconfig | 控制器基础操作（up/down/reset/name） | 1.5 |
| 1.7 构建系统 | Cargo workspace、cbindgen、安装规则、CI | 无 |

#### 阶段 2：发现与连接 (Discovery & Connection)

| 任务 | 产出 | 依赖 |
|------|------|------|
| 2.1 Discovery Manager | 扫描启停、参数配置、TLV 解析 | 1.4 |
| 2.2 发现级别与过滤 | TXS-20001 §6 发现级别管控 + 多条件过滤 | 2.1 |
| 2.3 Device 对象 | 远端设备生命周期、属性管理 | 2.1 |
| 2.4 Connection Manager | 连接/断开、参数协商、角色管理 | 2.3 |
| 2.5 slctl 发现/连接 | scan/connect/disconnect/info 命令 | 2.4 |

#### 阶段 3：服务管理 (Service Layer)

| 任务 | 产出 | 依赖 |
|------|------|------|
| 3.1 Service 对象 | D-Bus 服务/特征值/描述符对象树 | 2.4 |
| 3.2 SSAP 客户端 | 服务发现、特征值读写通知、Method 调用 | 3.1 |
| 3.3 SSAP 服务器 | 本地服务注册、远端请求处理 | 3.1 |
| 3.4 服务缓存 | 已发现服务持久化到 /var/lib | 3.2 |
| 3.5 slctl 服务操作 | services/read/write/notify 命令 | 3.2 |

#### 阶段 4：安全 (Security)

| 任务 | 产出 | 依赖 |
|------|------|------|
| 4.1 Security Manager | 配对流程编排、6 种方式分发 | 2.4 |
| 4.2 Agent 框架 | D-Bus Agent 注册/回调机制 | 4.1 |
| 4.3 密钥持久化 | LTK/IRK/CSRK 安全存储 | 4.1 |
| 4.4 自动重连加密 | Bonded 设备快速恢复 | 4.3 |
| 4.5 slctl 配对 | pair/trust/untrust/remove 命令 | 4.2 |

#### 阶段 5：Profile 与应用 (Profiles)

| 任务 | 产出 | 依赖 |
|------|------|------|
| 5.1 插件加载框架 | inventory 自动注册 + libloading 加载外部 .so、UUID 匹配、probe/remove | 3.2 |
| 5.2 设备信息插件 | sl_devinfo (内建, UUID 0x180A) | 5.1 |
| 5.3 电池插件 | sl_battery (内建) | 5.1 |
| 5.4 HID 插件 | sl_hid → uhid/evdev | 5.1 |
| 5.5 音频插件 | sl_audio → PipeWire/ALSA | 5.1 |

#### 阶段 6：调试与测试 (Tooling)

| 任务 | 产出 | 依赖 |
|------|------|------|
| 6.1 slkmon | DLI 帧解码、SSAP PDU 解析、pcap 输出 | 1.2 |
| 6.2 slkdump | 轻量帧转储 | 1.5 |
| 6.3 测试框架 | `#[tokio::test]` 单元测试 + pytest D-Bus 集成测试 / QEMU 联动 | 2.5 |
| 6.4 认证测试套件 | TXS-50003/50004 测试用例覆盖 | 全部 |

#### 阶段 7：生态集成 (Ecosystem)

| 任务 | 产出 | 依赖 |
|------|------|------|
| 7.1 C FFI | libsparklink.so + sparklink.h (cbindgen) | 3.5 |
| 7.2 Python 绑定 | sparklink-python (D-Bus 或 ctypes 封装) | 3.5 |
| 7.3 Go 绑定 | go-sparklink (godbus 或 cgo 封装) | 3.5 |
| 7.4 NetworkManager 集成 | SparkLink 网络设备自动管理 | 5.x |
| 7.5 GNOME/KDE 集成 | 设置面板、配对对话框、系统托盘 | 4.2 |

---

### 3.6 与 BlueZ 的对应关系

| BlueZ 组件 | SparkLink 对应 | 状态 |
|------------|---------------|------|
| 内核 bluetooth.ko | net/sparklink/ (Rust) | 已完成 |
| HCI socket | /dev/sparklink + netlink | 已完成 |
| L2CAP (内核) | 传输通道管理 (内核) | 已完成 |
| SMP (内核) | 安全状态机 (内核) | 已完成 |
| ATT/GATT (内核) | SSAP 状态机 (内核) | 已完成 |
| bluetoothd | slkd (Rust) | **待开发** |
| org.bluez D-Bus | org.sparklink D-Bus (zbus) | **待开发** |
| libbluetooth.so | libsparklink crate + .so (Rust cdylib) | **待开发** |
| bluetoothctl | slctl (Rust) | **待开发** |
| btmon | slkmon (Rust) | **待开发** |
| hcidump | slkdump (Rust) | **待开发** |
| hciconfig+btmgmt | slkconfig (Rust) | **待开发** |
| GATT Profiles | Profile 插件 (Rust trait + .so) | **待开发** |
| Agent API | org.sparklink.Agent (zbus) | **待开发** |

---

### 3.7 技术选型总结

| 决策项 | 选择 | 理由 |
|--------|------|------|
| daemon 语言 | Rust | 与内核子系统语言统一，共享协议常量和类型定义；内存安全消除守护进程漏洞类别 |
| 工具链语言 | Rust | 全栈统一，编译产物为静态链接二进制，无运行时依赖，适合嵌入式部署 |
| IPC 机制 | D-Bus (system bus) | Linux 桌面/嵌入式标准，成熟的安全策略，使用 zbus crate (纯 Rust D-Bus 实现) |
| 构建系统 | Cargo workspace | Rust 原生构建，多 crate 共享依赖，册到 crates.io |
| 异步运行时 | tokio (multi-thread) | 成熟的异步生态，AsyncFd 对接内核 fd | 
| 序列化 | serde + TOML | 配置文件可读性好，Rust 生态事实标准 |
| 密钥存储 | TOML 文件 + 受限权限 (0600) | 简单可审计，文件权限保证安全 |
| C FFI | cbindgen 自动生成 | 头文件与 Rust 源码同步，避免手动维护 |
| 日志 | tracing crate + tracing-journald | 结构化日志，直接输出到 systemd-journal |
| 测试 | `#[tokio::test]` + pytest (D-Bus) | 分层测试策略 |
| 文档 | man pages + D-Bus Introspect + rustdoc | 标准 Unix 文档 + Rust API 文档 |

---

## 四、标准覆盖矩阵

| 标准文档 | 涉及章节 | 内核已覆盖 | 用户态需覆盖 |
|---------|---------|-----------|-------------|
| TXS-00001-2025 架构 | 全部 | 无线接入层 + DLI | 基本服务层 + 应用层 |
| TXS-10002-2025 SLE | §1-8 PHY/MAC | 全部 | 无 (纯控制器侧) |
| TXS-10002-2025 SLE | §9 安全 | 配对状态机 + 密码学 | 配对流程编排、Agent 交互、密钥持久化 |
| TXS-10003-2025 DLI | 全部 | 帧封装 + 命令/事件 | 无 (内核完整实现) |
| TXS-20001-2025 发现 | §6 设备发现 | 扫描硬件控制 | TLV 解析、发现级别策略、过滤逻辑 |
| TXS-20001-2025 SSAP | §7 服务管理 | SSAP 底层收发 | 服务注册编排、特征值管理、权限校验 |
| TXS-20002-2025 传输 | §6 传输模式 | PDU 分片/重组 | 传输通道创建策略、QoS 参数选择 |
| TXS-20002-2025 控制 | §7 信令 | 信令 PDU 编解码 | 能力协商决策、通道生命周期管理 |
| TXS-50003-2025 SLE 测试 | 全部 | 底层测试框架 | 测试用例编排、结果判定 |
| TXS-50004-2025 服务测试 | 全部 | 无 | 全部 (服务层测试) |
