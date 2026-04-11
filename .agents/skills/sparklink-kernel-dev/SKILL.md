---
name: sparklink-kernel-dev
description: 'SparkLink 子系统开发工作流：适用于 net/sparklink/ 内核子系统与 ~/Documents/sparklink/ 用户态工作区的功能开发、Bug 修复、标准符合性修复、ABI 对齐、栈帧安全检查、QEMU 自测和 GPG 提交。当用户提到 SparkLink、sle_uapi、sparklink_core、slkd、slctl、DLI ioctl、SSAP、TXS-标准 时触发。'
argument-hint: '要实现的功能或要修复的 Bug 描述'
---

# SparkLink 内核子系统开发工作流

## 关键约束（违反即构建失败）

| 规则 | 原因 |
|------|------|
| 构建命令：`cd build && make LLVM=-16 -j$(nproc)` | `make O=build` 会使 Rust 重编检测失效 |
| **不能**提交 AGENTS.md | 项目规定 |
| `#[inline(never)]` 每个函数只能出现一次 | 重复出现触发 `-D unused-attributes` → 构建失败 |
| ALL warnings are errors（`-D warnings`） | rustc 配置，警告即失败 |
| 内核提交须 GPG 签名（`git commit -S`） | 安全要求 |
| QEMU 自测通过后才能提交 | 严格测试门禁 |

## 开发环境

```
内核：  ~/Documents/linux/
用户态：~/Documents/sparklink/   (7-crate Cargo workspace)
标准文档：~/Documents/Summary-of-Sparkling-Information/Standard/
构建产物：~/Documents/linux/build/

内核构建：cd ~/Documents/linux/build && make LLVM=-16 -j$(nproc)
用户态构建：cd ~/Documents/sparklink && cargo test --workspace
QEMU 测试：bash ~/Documents/linux/tools/testing/selftests/sparklink/run_qemu_test.sh [--verbose]
GPG 密钥：EA9EB99D267F931672BB73531E2654D7B5C2EDC1
```

## 架构层次（从下到上）

```
[标准文档 TXS-*]
      ↓
[内核 net/sparklink/]
  ├── include/uapi/linux/sparklink_ioctl.h  ← C UAPI（C 测试程序共享）
  ├── sle_uapi.rs                           ← Rust 镜像（必须与 C 一致）
  ├── sle_dli.rs / sle_adv.rs / sle_conn.rs / sle_security.rs / ...
  └── sparklink_core.rs                     ← ioctl 分发（ioctl_dispatch_*）
      ↓  ioctl
[用户态 ~/Documents/sparklink/]
  ├── crates/slk-protocol/      ← ioctl 常量 + FFI 类型
  ├── crates/libsparklink/      ← Adapter 方法封装
  ├── crates/slkd/              ← D-Bus 守护进程（8 个接口）
  └── crates/slctl/             ← CLI（38+ 命令）
```

## 步骤 1：标准研究

在实现前，先阅读相关 TXS 标准 PDF：

```bash
ls ~/Documents/Summary-of-Sparkling-Information/Standard/
# 常用：TXS-10003（DLI）、TXS-20001（设备发现/SSAP）、
#        TXS-20002（传输控制）、TXS-20007（传输报文格式）、
#        TXS-30004（HID 数据交互）、TXS-30013（HID 应用配置）
```

重点提取：
- UUID/服务代码分配（附录 A）
- 字段位宽和枚举值
- 状态机图（连接/断连/重置流程）
- ABI 关键约束（字节序、对齐、保留字段）

## 步骤 2：评估现有实现

```bash
# 检查 ioctl 编号空间（避免冲突）
grep 'SL_IOCTL_' ~/Documents/linux/include/uapi/linux/sparklink_ioctl.h | sort

# 检查用户态现有方法
grep 'pub fn ' ~/Documents/sparklink/crates/libsparklink/src/adapter.rs

# 检查结构体大小（ABI 对齐）
grep 'size_of' ~/Documents/sparklink/crates/slk-protocol/src/tests.rs
```

## 步骤 3：实现（按层次顺序）

### 3a. 内核层（net/sparklink/）

**顺序必须严格遵守（ABI 传递链）：**

1. **`include/uapi/linux/sparklink_ioctl.h`** — 添加 C 结构体和 ioctl 宏
   ```c
   struct sle_new_feature {
       __u8  field_a;
       __u8  _pad;
       __le16 field_b;
   };
   #define SL_IOCTL_NEW_FEATURE  _IOWR('S', 0xNN, struct sle_new_feature)
   ```

2. **`net/sparklink/sle_uapi.rs`** — 添加 Rust 镜像结构体（必须与 C 逐字节一致）
   ```rust
   #[repr(C)]
   pub struct SleNewFeature {
       pub field_a: u8,
       pub _pad: u8,
       pub field_b: u16,
   }
   pub const SL_IOCTL_NEW_FEATURE: u32 = 0x534eNN;
   ```
   > ⚠️ `repr(C)` 中 u16 字段会引入 padding——把 u8 字段聚在一起，u16/u32 字段放后面，避免意外填充

3. **`net/sparklink/sle_*.rs`** — 在对应模块添加业务逻辑

4. **`net/sparklink/sparklink_core.rs`** — 在对应 `ioctl_dispatch_*` 函数中添加分支
   ```rust
   SL_IOCTL_NEW_FEATURE => {
       let req: SleNewFeature = read_user_struct(arg)?;
       // ... 调用模块逻辑
   }
   ```

5. **`tools/testing/selftests/sparklink/sparklink_ctl.c`** — 更新 C 测试程序结构体定义

### 3b. 用户态层（~/Documents/sparklink/）

**顺序：**

1. **`crates/slk-protocol/src/ioctl.rs`** — 添加 ioctl 函数和常量
2. **`crates/slk-protocol/src/types.rs`** — 添加 Rust 类型（若需要）
3. **`crates/libsparklink/src/adapter.rs`** — 添加 `Adapter` 方法
4. **`crates/slkd/src/dbus_iface.rs`** 或对应接口文件 — 添加 D-Bus 方法
5. **`crates/slctl/src/commands.rs`** — 添加 CLI 命令
6. **测试** — 在对应 crate 的 `tests.rs` 添加测试

## 步骤 4：ABI 安全检查

每次新增或修改结构体后必须验证：

```rust
// 在 crates/slk-protocol/src/tests.rs 中加断言
#[test]
fn struct_size_new_feature() {
    assert_eq!(size_of::<SleNewFeature>(), 4); // 必须与内核 C 结构体相同
}
```

**常见陷阱：**
- `repr(C)` 中 `u8, u16` 组合会产生 1 字节 padding → 用 `u8, u8, u16` 
- 内核 `__le16` = 用户态 `u16`（little-endian 平台）
- 结尾的 `u16` 字段可能导致 4 字节对齐，使结构体比预期大

## 步骤 5：栈帧安全检查

内核函数栈限制约 8KB。规则：

- 函数中出现 **>64B 局部变量**（如 `SleConnData = 260B`）时，将该分支提取为独立函数
- 用 `#[inline(never)]` 强制独立栈帧：
  ```rust
  /// 函数说明文档
  #[inline(never)]
  fn ioctl_conn_send(arg: usize) -> Result<isize> {
      let cd: SleConnData = read_user_struct(arg)?; // 260B on stack
      // ...
  }
  ```
- **`#[inline(never)]` 只能出现一次**，doc comment 必须放在它**之前**
- 提取后的分发函数保持轻量（仅路由，无大变量）

## 步骤 6：构建与测试

```bash
# 内核构建
cd ~/Documents/linux/build && make LLVM=-16 -j$(nproc)
# 成功标志：Kernel: arch/x86/boot/bzImage is ready  (#NNN)

# 用户态构建
cd ~/Documents/sparklink && cargo test --workspace
# 成功标志：test result: ok. N passed; 0 failed

# QEMU 自测（必须在内核提交前通过）
bash ~/Documents/linux/tools/testing/selftests/sparklink/run_qemu_test.sh
# 成功标志：Test results: N OK, 0 FAIL
# 如果失败加 --verbose 详查
```

**可接受的波动：** QEMU 测试数量 ±2（因为测试之间有时序依赖），0 FAIL 必须严格保证。

## 步骤 7：提交

### 内核提交（必须 GPG 签名）

```bash
cd ~/Documents/linux
git add net/sparklink/ include/uapi/linux/ tools/testing/selftests/sparklink/
# ❌ 永远不要 git add AGENTS.md
git commit -S -m "net: sparklink: <简短描述（<50字符）>

<详细说明，解释 what/why/how>

QEMU self-test: N OK / 0 FAIL.

Signed-off-by: sanchuanhehe <wyihe5220@gmail.com>
Assisted-by: GitHub Copilot <copilot@github.com>"
```

### 用户态提交

```bash
cd ~/Documents/sparklink
git add -A
git commit -m "<crate/action>: <简短描述>

<详细说明>

Tests: N passed."
```

## 常见问题速查

| 问题 | 排查方法 | 解决方案 |
|------|---------|---------|
| 构建错误 `unused-attributes` | `#[inline(never)]` 重复 | 删除重复的，确保 doc comment 在属性之前 |
| 构建错误 `unused_imports` | 新增 use 但未使用 | 删除未使用的 use |
| QEMU `No test result found` | 内核 panic 或启动失败 | 加 `--verbose` 查看 dmesg |
| 用户态 ABI 不匹配 (`size_of` assert 失败) | 结构体 padding 不一致 | 用 `#[repr(C, packed)]` 或重排字段 |
| ioctl 返回 `ENOTTY` | ioctl 号未注册 | 检查 `ioctl_dispatch_*` 中的 match 分支 |
| ioctl 返回 `EINVAL` | 参数校验失败 | 检查 `read_user_struct` 和字段范围 |
| QEMU `unknown ioctl 0xXXXX` | 测试程序用了旧 ioctl 号 | 同步 `sparklink_ioctl.h` 到虚拟机镜像 |
| `alloc_dynamic_tcid` 用尽 | 断连未回收 | 在 `close_all()` 中重置 `next_dynamic_tcid = 0x80` |
| `SleConnInfo` 大小不匹配 | 缺失 trailing 字段 | 对齐内核 C 头文件与 Rust 结构体字段 |

## ioctl 号分配约定

格式：`0x53 << 8 | NR`（`'S' = 0x53`）

| 范围 | 用途 |
|------|------|
| 0x00-0x7F | 控制/配置类 ioctl |
| 0x80-0xFF | 数据/事件类 ioctl |
| 0x1A-0x1F | 扩展广播（EXT ADV）子命令 |
| 0x80-0x89 | 事件轮询 / 数据收发 |

检查空闲号：`grep -o '0x[0-9A-Fa-f][0-9A-Fa-f])' sparklink_ioctl.h | sort -u`

## 文件索引

| 文件 | 作用 |
|------|------|
| `include/uapi/linux/sparklink_ioctl.h` | C UAPI（内核+测试共享） |
| `net/sparklink/sle_uapi.rs` | Rust UAPI 镜像 |
| `net/sparklink/sparklink_core.rs` | ioctl 分发（~22 个 ioctl_* 函数） |
| `net/sparklink/sle_adv.rs` | 广播/扫描逻辑 |
| `net/sparklink/sle_conn.rs` | 连接/TCID/信令 |
| `net/sparklink/sle_security.rs` | 配对/加密/PSK/ECDH |
| `net/sparklink/sle_dli.rs` | DLI 设备接口/事件环 |
| `net/sparklink/sle_workers.rs` | SSAP 工作线程/可靠通道 |
| `crates/slk-protocol/src/ioctl.rs` | 用户态 ioctl wrapper |
| `crates/slk-protocol/src/advdata.rs` | TLV 广播数据解析器 |
| `crates/libsparklink/src/adapter.rs` | 公开 API（Adapter 结构体） |
| `crates/slkd/src/dbus_iface.rs` | D-Bus 适配器接口 |
| `crates/slkd/src/bonding.rs` | 配对信息持久化（TOML） |
| `crates/slkd/src/profile.rs` | Profile 插件框架 |
| `crates/slkd/src/transport.rs` | TXS-20007 传输协议 |
| `crates/slkd/src/hid.rs` | TXS-30004 HID 数据交互 |
| `crates/slkd/src/controller.rs` | Controller/ExtAdv D-Bus 接口 |
| `crates/slkd/src/security.rs` | Security D-Bus 接口 |
| `crates/slctl/src/commands.rs` | CLI 命令实现 |
| `tools/testing/selftests/sparklink/sparklink_ctl.c` | C 自测程序（QEMU 内运行） |
| `data/systemd/slkd.service` | systemd 服务文件 |
| `data/dbus/sparklink.conf` | D-Bus 策略文件 |
| `data/udev/99-sparklink.rules` | udev 规则 |
| `data/pkgconfig/sparklink.pc` | pkg-config 文件 |
| `docs/API.md` | ioctl 参考（126 命令） |
| `docs/ARCHITECTURE.md` | 架构总览 |
| `docs/AUDIT.md` | 覆盖率审计 |
| `docs/BLUEZ_COMPARISON.md` | BlueZ 对比分析 |
