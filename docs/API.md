# API 参考

## slk-protocol

### ioctl 命令

所有 ioctl 以 magic number `0x53` (`'S'`) 编号，基于 nix 宏生成。

| 分类 | 序号范围 | 数量 | 功能 |
|------|----------|------|------|
| 设备 | 0x00-0x0F | 6 | 基本信息、版本、重置、统计 |
| 广播 | 0x10-0x1F | 2 | 广播参数配置、控制 |
| 扫描 | 0x20-0x2F | 4 | 扫描参数、启停、结果获取 |
| 连接 | 0x30-0x3F | 5 | 连接建立、断开、信息查询 |
| 安全 | 0x40-0x5F | 11 | PSK、配对、加密、认证 |
| SSAP | 0x60-0x7F | 15 | 服务注册/注销、特性读写、通知 |
| DLI | 0x80-0x8F | 3 | DLI 配置与事件 |
| PHY | 0x90-0x9F | 1 | PHY 层参数 |
| 角色 | 0xA0-0xAF | 2 | T/G 角色切换 |

### 核心结构体

```rust
pub type SleAddr = [u8; 6];

#[repr(C)]
pub struct SciDevInfo {
    pub device_name: [u8; 32],
    pub firmware_rev: [u8; 16],
    pub hardware_rev: [u8; 16],
    pub software_rev: [u8; 16],
    pub manufacturer: [u8; 32],
    pub serial_number: [u8; 32],
    pub addr: SleAddr,
    pub addr_type: u8,
    pub role: u8,
    pub state: u32,
    pub flags: u32,
}

#[repr(C)]
pub struct SleScanParams {
    pub scan_type: u8,
    pub scan_phy: u8,
    pub interval: u16,
    pub window: u16,
    pub duration: u16,
    pub filter_policy: u8,
}

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
- GenlCmd: 34 variants (0..=33)
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
