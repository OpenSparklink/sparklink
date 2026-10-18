# SparkLink 用户态基础设施 — 开发规范

## 项目概述

SparkLink (星闪) 无线通信协议的用户态基础设施，对标 BlueZ 的架构设计。
基于 Rust 实现，通过 ioctl/chardev/genetlink 与内核子系统 (`net/sparklink/`) 交互。
遵循 T/XS 00001-2025、T/XS 10002-2025、T/XS 20002-2025 等星闪技术标准。

**代码边界**: 默认 daemon 与独立未发布 slk-experimental 开发 crate 分开；Python 绑定保留。

## 构建

```bash
python3 tools/build_resources.py -- cargo +1.96.1 check --locked --workspace
python3 tools/build_resources.py -- cargo +1.96.1 build --locked --workspace
python3 tools/build_resources.py -- cargo +1.96.1 clippy --locked --workspace --all-targets -- -D warnings
python3 tools/build_resources.py -- cargo +1.96.1 test --locked --workspace
```

资格工具链按具体 artifact 记录固定（当前保留镜像为 Rust 1.96.1）；浮动 stable
仅用于单独的前向兼容检查，不能替代资格构建。根 Cargo.lock 与文档 uv.lock 分开。

## Crate 结构

| Crate | 类型 | 职责 |
|-------|------|------|
| `slk-protocol` | lib | ABI/纯值/codec；Channel和Native系统调用均已迁出；纯ABI/codec层 |
| `slk-channel` | lib | 已授权fd查询、SCM安全上下文、原期限和系统调用；不打开controller或获取管理lease |
| `slk-native` | lib | Native管理、ioctl、观察、事件、抓包；无应用客户端或Channel依赖 |
| `libsparklink` | lib + cdylib | 真实D-Bus Client及授权fd操作；无Native依赖/管理导出；C/Python完整broker和SSAP客户端仍缺失 |
| `slk-contract` | lib | SDK独立的共享D-Bus值/路径/名字；producer/caller共同消费，独立signature检查保留 |
| `slkd` | bin | D-Bus 守护进程: org.sparklink, TOML 配置, tracing-journald, zbus 5 |
| `slkconfig` | bin | 显式 Native 管理/诊断，clap 4；旧安全及 SSAP 门面命令已删除，剩余历史入口继续审计 |
| `slctl` | bin | 交互式控制工具 (对标 bluetoothctl): rustyline 15, 通过 D-Bus 与 slkd 通信 |
| `slktest` | bin + internal lib | 应用通道正确性/时延/速率/窗口/双向测试；普通授权fd，不是Host或协议Engine |
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

### 主线程构建资源（2026-10-16）

本机16逻辑CPU：单独构建默认12路，与真实设备VM回归并行默认8路。使用共享
`tools/build_resources.py`（make的build/check/test/clippy已接入）；VM并行显式设
`SPARKLINK_BUILD_WITH_VM=1`，必要时`SPARKLINK_BUILD_JOBS`只下调。Cargo和make
使用同一预算，同一workspace `.dev/main-build.lock`只允许一个主线程重构建；不要
另开独立12路，直接调用历史脚本不受该锁保护。不要把已接入wrapper的根Makefile
再包一次；内核直接make命令可用wrapper。CI独立runner按实际CPU上限截断预算。

内核开发固定`O=../.dev/session-wake-kernel-build-v1`，Cargo Native固定
`.dev/cargo-native-dev`；每种必要debug配置各有稳定目录。先封存准确资格产物再
复用开发目录，不按每次commit更换O触发objtool/无关模块重编。新构建记录实际
jobs/CPU affinity/可用内存/命令/配置/工具链/来源；资源记录不授功能资格。
已运行a0e1ad7的-j4及f43冻结资格链jobs4原样完成，不中断、不回写旧资格。

### Rust 风格

- 使用标准 rustfmt 格式化
- 所有 pub 接口需通过 clippy 无警告
- ioctl 结构体使用 `#[repr(C)]` 保证 ABI 兼容
- 异步函数优先使用 `async fn` + `tokio`
- 错误处理: `thiserror` 定义错误类型, 库使用 `Result<T, Error>`, 应用使用 `anyhow::Result`
- nix v0.30 API: `open()` 返回 `OwnedFd`, ioctl 宏接受 `RawFd`

### Native ioctl 边界

Native管理及特权fd创建系统调用集中在slk-native内部；普通应用通过libsparklink申请授权fd，业务使用
slk-channel。不要恢复旧sl_start_adv/sl_stop_adv裸命令包装。显式Native管理者
使用现有typed入口，例如adapter.controller_snapshot(generation)和
adapter.diagnostic_submit(&mut request)。请求携带原generation、lease、request id
和期限；submit成功仅是软件准入，Complete及设备状态须按实际结果另行查询。
ABI结构、errno和输出身份校验集中在当前封装中，避免调用者再复制一套。

### D-Bus 接口规范

- 总线名称: `org.sparklink`
- 对象路径: `/org/sparklink`, `/org/sparklink/slk{index}_g{generation}`；Peer/Connection 按完整 lifetime 路径，不使用旧 adapterN 别名
- 接口: `org.sparklink.Manager`, `org.sparklink.Adapter`, `org.sparklink.Peer`, `org.sparklink.Connection`, `org.sparklink.Security`, `org.sparklink.ServiceManager`；远端 SSAP 使用具完整身份的 Connection，不再发布 RemoteService

### Commit 规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 风格:

```
<type>(sparklink): <简短描述>

<详细说明>

Signed-off-by: sanchuanhehe <wyihe5220@gmail.com>
Assisted-by: <实际使用的助手及邮箱>
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
│   ├── libsparklink/src/ (client.rs, ffi_channel.rs：应用 SDK，无 Native 管理)
│   ├── slkd/src/ (main.rs, config.rs, kernel.rs, dbus_iface.rs, state.rs, security.rs, service.rs)
│   └── slkconfig/src/ (main.rs)
│   ├── slctl/src/ (main.rs, commands.rs)
│   ├── slktest/src/ (channel.rs, benchmark/, cli.rs, connection.rs)
│   ├── slkmon/src/ (main.rs, decode.rs)
│   └── slkdump/src/ (main.rs)
├── bindings/
│   └── python/ (pyproject.toml, sparklink/channel.py, native.py：显式区分应用与 Native)
├── data/
│   ├── config/main.conf
│   ├── dbus/ (org.sparklink.service, sparklink.conf)
│   └── systemd/sparklink.service
└── project/implementation-plan.md (唯一实施计划)
```

## 内核侧对应关系

内核子系统位于 `~/Documents/opensparklink/linux/net/sparklink/`，提供:
- `/dev/sparklink` chardev (版本化 Native 管理/事件/诊断，旧 raw ioctl 已退休)
- Generic Netlink `sparklink` 定义（接通与验收按具体调用路径核对）
- debugfs `/sys/kernel/debug/sparklink/`
- configfs 旧配置消费者已退休；不能据目录或旧声明承诺固件/名称控制能力

Native管理通过`slk-native`，已授权fd操作通过`slk-channel`；`slk-protocol`保留纯ABI/值。

## 实施与验收状态

当前资格仅维护于 [能力入口](project/current-capabilities.md)及其结构化记录；
目标架构与待办分别见 [架构](project/architecture.md)和[唯一计划](project/implementation-plan.md)。
历史通过不升级新 HEAD。部分真实发现/连接/数据/SSAP/限定 Agent 门禁已封存，
整项恢复、安全/Bond、多通道、四设备、部署与发布仍开放。UAPI 未发布，无兼容期。

## 文档随开发维护

每批先注明生产行为、读者任务、受影响契约和文档退出条件；本批相关门禁通过后
继续下一条纵向链路，不等所有控制面或文档补齐。持续采用 Diátaxis：教程教会操作，
how-to 解决任务，reference 写准确契约，explanation 解释理由；计划/资格/ADR/历史独立。
接口变更同步签名、错误、权限、期限/退出、绑定、CLI、man 和示例；配置同步单位、
默认/范围、覆盖/加载/升级；状态/所有权同步参考和必要 ADR。修复补回归与排错，
测试补边界/准确证据，安装补升级/卸载；删除旧代码同步移除旧推荐，保留历史失败。
实现与文档在同一可 review 批次提交；内部变更无文档影响须在 PR 说明理由。
执行 `make docs`（包含静态示例和负对照），另记未执行的浏览器、外链和操作重放。
不能将静态/HTML 通过当作内容完整或功能资格。里程碑抽查读者全流程、man/网站、
版本/搜索/历史提示并重放适用教程；未具备条件就记缺口，不编造可用步骤。
仅按本批影响触发检查，文档不是 WS73 主线前置；所有真实设备和实验驱动保持 VM-only。

## 注意事项

- nix v0.30: `open()` 返回 `Result<OwnedFd>` 而非 `Result<RawFd>`，ioctl 宏需要 `RawFd` 参数，通过 `AsRawFd` trait 转换
- `AsyncFd<OwnedFd>` 拥有文件描述符生命周期，`get_ref().as_raw_fd()` 获取原始 fd
- zbus 5 使用 `#[interface]` proc macro 声明 D-Bus 接口
- UAPI 结构体大小变更会改变 ioctl 编号 (size 编码在 `_IOWR` 中)，修改 types.rs 后需同步内核侧

## 旧实验能力

默认slkd不链接slk-experimental，不自动注册未经互通验收的旧Profile/HID；
transport无生产消费者，仅实验crate。旧注册/连接callback仅专用测试/独立实验crate保留，不能宣称完整SSAP服务。
旧daemon experimental-legacy-profiles入口已退休，实验crate仅dev-dependency。
测试保留同一actor的阻塞/cancel/drain/panic回归，严格default/all-features
检查不得以全局allow(dead_code)掩盖。见[实验边界](project/reference/architecture/experimental-code-boundary.md)。
