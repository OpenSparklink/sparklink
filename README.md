# SparkLink Userspace Infrastructure

SparkLink 无线通信协议的完整用户态基础设施，对标 BlueZ 的架构设计。

## 架构

```
                     ┌──────────────────────────────────────────────┐
   Applications      │  slctl        slkconfig     slkmon  slkdump  │
                     │  (REPL)       (CLI)         (monitor)(dump)  │
                     └──────┬──────────┬──────────────┬────────┬────┘
                            │ D-Bus    │ D-Bus        │        │
                     ┌──────▼──────────▼──────────────┘        │
    Daemon           │           slkd                          │
                     │      org.sparklink                      │
                     │  ┌──────────────────────────┐           │
                     │  │ AdapterIface             │           │
                     │  │ DeviceIface (per device) │           │
                     │  │ SecurityIface            │           │
                     │  │ SsapManagerIface         │           │
                     │  │ RemoteServiceIface       │           │
                     │  └──────────────────────────┘           │
                     └─────────────┬───────────────────────────┘
                                   │
                     ┌─────────────▼───────────────┐
    Library          │       libsparklink          │
                     │  Adapter (async, tokio)     │──── C FFI (ffi.rs)
                     │  Error / Event types        │──── Python bindings
                     └─────────────┬───────────────┘
                                   │
                     ┌─────────────▼───────────────┐
    Protocol         │       slk-protocol          │
                     │  99 ioctl wrappers (nix)    │
                     │  70+ repr(C) structs        │
                     │  Generic Netlink constants  │
                     └─────────────┬───────────────┘
                                   │ ioctl / chardev
                     ──────────────▼──────────────────────
                          Linux Kernel (net/sparklink/)
                          /dev/sparklink
```

## 代码统计

| 类别 | 行数 |
|------|------|
| Rust | ~5200 |
| Python | ~550 |
| 测试 | 55 个 (36 Rust + 19 Python) |
| Crate | 7 个 |

## 快速开始

### 构建

```bash
cargo build --release --workspace
```

### 安装

```bash
sudo make install
sudo systemctl enable --now sparklink
```

### 使用 slkconfig

```bash
# 列出注册的 controller 与 generation
slkconfig adapters

# 明确选择设备，独立只读观察（0 仅为示例 index）
slkconfig --adapter 0 controller
slkconfig --adapter 0 management
slkconfig --adapter 0 info

# 普通应用的原生 WS73 广播/扫描由 slkd 管理
slctl list

# 管理员离线诊断：先停止该设备的 Managed owner；generation 使用实际观察值
slkconfig --adapter 0 --generation 123 query mac

# 以下旧管理命令仅适用于 profile 0 迁移路径
slkconfig --adapter 0 scan --duration 5
slkconfig --adapter 0 connect AA:BB:CC:DD:EE:FF
slkconfig --adapter 0 security

# 列出 SSAP 服务
slkconfig --adapter 0 services
```

### 使用 slctl 交互式控制台

```bash
slctl
slctl> scan on
slctl> devices
slctl> connect AA:BB:CC:DD:EE:FF
slctl> info
slctl> disconnect 0x0001
```

### 使用 slkmon 协议分析

```bash
# 监控所有事件
slkmon

# 过滤连接事件
slkmon -t conn

# 输出到文件
slkmon -o capture.log
```

### 使用 slkdump 帧捕获

```bash
# 十六进制+ASCII 输出
slkdump

# 原始二进制输出
slkdump -r > raw.bin
```

## Crate 说明

### slk-protocol

内核 UAPI 绑定层。提供 99 个 ioctl 命令的类型安全包装 (基于 nix 宏)，70+ 个 `repr(C)` 结构体 (经 ABI 验证与内核一致)，以及 Generic Netlink 常量定义 (34 commands, 59 attributes)。

### libsparklink

高层异步 API。`Adapter` 类型封装了设备管理、扫描、连接、安全配对、SSAP 服务、DLI 事件、PHY 配置等约 50 个方法。基于 tokio `AsyncFd` 实现非阻塞事件轮询。同时提供 C FFI 层 (`ffi.rs`，20 个导出函数) 和自动生成的 `sparklink.h` 头文件。

### slkd

D-Bus 管理守护进程，使用 zbus 5 在 `org.sparklink` 总线名称下暴露六个接口。支持 TOML 配置 (`/etc/sparklink/main.conf`)、systemd 集成、tracing-journald 结构化日志。设备和连接对象在事件驱动下动态注册。

### slkconfig

离线配置命令行工具。每设备命令要求 `--adapter`，可用 `--generation` 防止误用重插后的代次；`adapters/controller/management` 提供独立只读观察。原生 WS73 的 `query mac/features/version/buffers` 要求确切 generation、CAP_NET_ADMIN 和独占 Diagnostic lease，不能与 slkd 的 Managed owner 并行。旧 PHY/扫描/连接/配对/SSAP 管理命令仅在 profile 0 迁移路径保留。普通应用控制通过 slctl/slkd。基于 clap 4 的 derive API。

### slctl

交互式控制台 (对标 bluetoothctl)。基于 rustyline 15 的 REPL，通过 D-Bus 与 slkd 通信，支持 16 个命令，含自动补全和历史记录。

### slkmon

协议分析器 (对标 btmon)。从内核捕获 DLI 事件，支持事件类型过滤、结构化解码 (6 种事件类型)、hexdump 输出和文件写入。

### slkdump

轻量级帧转储工具 (对标 hcidump)。支持十六进制+ASCII 混合输出和原始二进制输出模式。

## 语言绑定

### C

```c
#include <sparklink.h>

SlkAdapter *adpt = slk_adapter_open("/dev/sparklink");
SciDevInfo info;
slk_device_info(adpt, &info);
printf("Device: %s\n", info.name);
slk_adapter_free(adpt);
```

编译: `gcc app.c -lsparklink -o app`

### Python

```python
from sparklink import Adapter

with Adapter("/dev/sparklink") as adpt:
    info = adpt.device_info()
    print(f"Device: {info.device_name}")
    adpt.start_scan()
    ev = adpt.poll_event()
    adpt.stop_scan()
```

安装: `pip install -e bindings/python/`

## D-Bus 接口

| 接口 | 对象路径 | 功能 |
|------|----------|------|
| org.sparklink.Manager | /org/sparklink | 适配器枚举 |
| org.sparklink.Adapter | /org/sparklink/slk0 | 扫描、连接管理 |
| org.sparklink.Device | /org/sparklink/slk0/dev_* | 设备属性 |
| org.sparklink.Security | /org/sparklink/slk0/security | 配对、加密 |
| org.sparklink.ServiceManager | /org/sparklink/slk0/services | SSAP 本地服务 |
| org.sparklink.RemoteService | /org/sparklink/slk0/conn_* | SSAP 远程服务 |

## 打包

### Debian

```bash
dpkg-buildpackage -us -uc
```

产出: `sparklink`, `libsparklink0`, `libsparklink-dev` 三个包。

### RPM

```bash
rpmbuild -ba sparklink.spec
```

产出: `sparklink`, `libsparklink`, `libsparklink-devel` 三个包。

## CI/CD

GitHub Actions 工作流 (`.github/workflows/ci.yml`) 包含 7 个 job:
- `check`: cargo check
- `test`: cargo test
- `clippy`: lint 检查
- `fmt`: rustfmt 格式检查
- `cbindgen`: C 头文件生成一致性验证
- `build-release`: release 构建 + artifact 上传
- `python-check`: Python 绑定语法验证

## 技术标准

遵循星闪技术联盟标准:
- T/XS 00001-2025 总体技术要求
- T/XS 10002-2025 星闪链路接口
- T/XS 10003-2025 安全规范
- T/XS 20001-2025 接入层通用要求
- T/XS 20002-2025 SLE 规范
- T/XS 50003-2025 SSAP 规范
- T/XS 50004-2025 配置传输协议
