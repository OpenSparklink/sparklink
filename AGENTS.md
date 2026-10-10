# SparkLink 用户态基础设施 — 开发规范

## 项目概述

SparkLink (星闪) 无线通信协议的用户态基础设施，对标 BlueZ 的架构设计。
基于 Rust 实现，通过 ioctl/chardev/genetlink 与内核子系统 (`net/sparklink/`) 交互。
遵循 T/XS 00001-2025、T/XS 10002-2025、T/XS 20002-2025 等星闪技术标准。

**代码边界**: 默认 daemon 与独立未发布 slk-experimental 开发 crate 分开；Python 绑定保留。

## 构建

```bash
cd ~/Documents/opensparklink/sparklink && cargo check
cargo build
cargo clippy -- -W clippy::all
cargo test
```

- Edition: 2024
- MSRV: 跟随 Rust stable 最新版
- Workspace 根: `~/Documents/opensparklink/sparklink/`

## Crate 结构

| Crate | 类型 | 职责 |
|-------|------|------|
| `slk-protocol` | lib | UAPI 绑定: ioctl 包装、repr(C) 结构体、Generic Netlink 常量；以当前源码及能力门禁为准 |
| `libsparklink` | lib + cdylib | 高层 API: 异步 Adapter 抽象, AsyncFd 事件循环, Error/Event 类型, C FFI (ffi.rs/ffi_native.rs), cbindgen 生成 sparklink.h |
| `slkd` | bin | D-Bus 守护进程: org.sparklink, TOML 配置, tracing-journald, zbus 5 |
| `slkconfig` | bin | CLI 工具: info/dli/phy/role/reset/stats/connections/scan/connect/disconnect/security/pair/encrypt/set-psk/sec-reset/services/list-services/read-prop/write-prop/remote-discover/remote-read/remote-write 子命令, clap 4 |
| `slctl` | bin | 交互式控制工具 (对标 bluetoothctl): rustyline 15, 通过 D-Bus 与 slkd 通信 |
| `slkmon` | bin | 协议分析器 (对标 btmon): DLI 帧解码、事件过滤、hexdump、文件填出 |
| `slkdump` | bin | 帧转储工具 (对标 hcidump): 轻量级、原始数据捕获、二进制输出 |

## 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| tokio | 1 (full) | 异步运行时 |
| zbus | 5 | D-Bus 绑定 (纯 Rust) |
| nix | 0.30 | ioctl/open/fcntl POSIX 绑定 |
| serde + toml | 1 / 0.8 | TOML 配置解析 |
| tracing | 0.1 | 结构化日志 |
| clap | 4 | CLI 参数解析 |
| thiserror | 2 | 错误类型派生 |

## 代码规范

### Rust 风格

- 使用标准 rustfmt 格式化
- 所有 pub 接口需通过 clippy 无警告
- ioctl 结构体使用 `#[repr(C)]` 保证 ABI 兼容
- 异步函数优先使用 `async fn` + `tokio`
- 错误处理: `thiserror` 定义错误类型, 库使用 `Result<T, Error>`, 应用使用 `anyhow::Result`
- nix v0.30 API: `open()` 返回 `OwnedFd`, ioctl 宏接受 `RawFd`

### ioctl 使用模式

```rust
// 读取型 ioctl
let mut info = unsafe { std::mem::zeroed::<SciDevInfo>() };
unsafe { ioctl::sl_dev_info(self.raw_fd(), &mut info)? };

// 写入型 ioctl
unsafe { ioctl::sl_start_adv(self.raw_fd(), params)? };

// 无参数 ioctl
unsafe { ioctl::sl_stop_adv(self.raw_fd())? };
```

### D-Bus 接口规范

- 总线名称: `org.sparklink`
- 对象路径: `/org/sparklink`, `/org/sparklink/adapter<N>`
- 接口: `org.sparklink.Manager`, `org.sparklink.Adapter`, `org.sparklink.Device`, `org.sparklink.Security`, `org.sparklink.ServiceManager`, `org.sparklink.RemoteService`

### Commit 规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 风格:

```
<type>(sparklink): <简短描述>

<详细说明>

Signed-off-by: sanchuanhehe <wyihe5220@gmail.com>
Assisted-by: GitHub Copilot <copilot@github.com>
```

type 取值:
- `feat`: 新功能 (ioctl 新增、D-Bus 方法、CLI 子命令等)
- `fix`: 缺陷修复 (ABI 不匹配、逻辑错误等)
- `docs`: 文档变更 (README、API.md 等)
- `refactor`: 重构 (不改变外部行为)
- `test`: 测试增补或修复
- `chore`: 构建/CI/依赖变更
- `perf`: 性能优化

Trailer 要求:
- 所有提交必须包含 `Signed-off-by` 和 `Assisted-by` 两行
- 邮箱地址不可省略

## 文件布局

```
~/Documents/opensparklink/sparklink/
├── Cargo.toml (workspace)
├── AGENTS.md
├── crates/
│   ├── slk-protocol/src/ (ioctl.rs, types.rs, genl.rs)
│   ├── libsparklink/src/ (adapter.rs, error.rs, event.rs)
│   ├── slkd/src/ (main.rs, config.rs, kernel.rs, dbus_iface.rs, state.rs, security.rs, service.rs)
│   └── slkconfig/src/ (main.rs)
│   ├── slctl/src/ (main.rs, commands.rs)
│   ├── slkmon/src/ (main.rs, decode.rs)
│   └── slkdump/src/ (main.rs)
├── bindings/
│   └── python/ (pyproject.toml, sparklink/__init__.py, structs.py, adapter.py)
├── data/
│   ├── config/main.conf
│   ├── dbus/ (org.sparklink.service, sparklink.conf)
│   └── systemd/sparklink.service
└── userspace-infrastructure-plan.md
```

## 内核侧对应关系

内核子系统位于 `~/Documents/opensparklink/linux/net/sparklink/`，提供:
- `/dev/sparklink` chardev (版本化 Native 管理/事件/诊断及待迁移旧 ioctl)
- Generic Netlink `sparklink` 定义（接通与验收按具体调用路径核对）
- debugfs `/sys/kernel/debug/sparklink/`
- configfs (设备固件/名称)

用户态通过 `slk-protocol` crate 的 ioctl 包装与内核交互。

## 实施与验收状态

文件、API 和独立测试的存在不表示功能完成。原“七阶段全部完成”记录已移除；
当前每设备 Native WS73 广播扫描/物理拔插已有 VM 真实设备证据，自动恢复根因、
连接、SSAP、安全/Bond、Profile/HID、PHY/PM、Proxy 和完整发布验收仍开放。
按 [当前复核与整改计划](docs/REVIEW_REMEDIATION_20261011.md) 和两仓库 issues
维护能力状态。清理旧实现/死代码属于当前整改，先迁移调用者和有效测试再删除。
UAPI 尚未发布，可同步修改或移除，无需保留旧接口兼容期。

## 注意事项

- nix v0.30: `open()` 返回 `Result<OwnedFd>` 而非 `Result<RawFd>`，ioctl 宏需要 `RawFd` 参数，通过 `AsRawFd` trait 转换
- `AsyncFd<OwnedFd>` 拥有文件描述符生命周期，`get_ref().as_raw_fd()` 获取原始 fd
- zbus 5 使用 `#[interface]` proc macro 声明 D-Bus 接口
- UAPI 结构体大小变更会改变 ioctl 编号 (size 编码在 `_IOWR` 中)，修改 types.rs 后需同步内核侧

## 旧实验能力

默认slkd不链接slk-experimental，不自动注册未经互通验收的旧Profile/HID；
transport无生产消费者，仅实验crate。旧注册/连接callback由显式
experimental-legacy-profiles构建feature保留，不能宣称完整SSAP服务。
测试保留同一actor的阻塞/cancel/drain/panic回归，严格default/all-features
检查不得以全局allow(dead_code)掩盖。见[实验边界](docs/EXPERIMENTAL_CODE_BOUNDARY.md)。
