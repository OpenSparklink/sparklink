---
name: sparklink-abi-fix
description: 'SparkLink C/Rust ABI 对齐检查与修复工作流。当用户遇到 size_of 断言失败、ioctl 返回 EFAULT 或错误数据、内核结构体与用户态结构体字段不一致、repr(C) padding 问题、新增内核字段但用户态未同步时使用。触发词：ABI、size_of、padding、结构体不匹配、EFAULT、字段缺失、struct 对齐、repr(C)、内核用户态不一致。'
argument-hint: '出问题的结构体名称（如 SleConnInfo）或 ioctl 名称'
---

# SparkLink C/Rust ABI 对齐检查与修复

## 核心原则

SparkLink 使用 `ioctl` 在内核和用户态之间传递结构体，内核持有权威定义，用户态必须逐字节匹配。

```
内核（权威）                        用户态（镜像）
include/uapi/linux/sparklink_ioctl.h  ←→  crates/slk-protocol/src/types.rs
         C struct                              #[repr(C)] Rust struct
         size: sizeof(struct X)               size: size_of::<X>()
             必须相等 ↑
```

---

## 步骤 1：定位不匹配的结构体

### A. `size_of` 测试失败

```bash
cd ~/Documents/sparklink && cargo test -p slk-protocol 2>&1 | grep -A3 'FAILED\|panicked'
# 输出示例：assertion failed: size_of::<SleConnInfo>() == 64
#                left: 56, right: 64
```

→ 用户态比内核少 8 字节，缺字段。

### B. ioctl 返回 `EFAULT` 或乱数据

`EFAULT` = `copy_from_user`/`copy_to_user` 因用户空间地址非法失败。常见原因：
- 用户态分配的缓冲区太小（结构体大小不匹配）
- 指针对齐不正确

### C. 测试 Phase 出现意外失败

```bash
bash run_qemu_test.sh --verbose 2>&1 | grep 'FAIL\|errno\|expected\|got'
```

---

## 步骤 2：对照检查

### 查看内核 C 定义（权威）

```bash
grep -A20 'struct sle_conn_info {' \
    ~/Documents/linux/include/uapi/linux/sparklink_ioctl.h
```

### 查看用户态 Rust 定义

```bash
grep -A20 'struct SleConnInfo' \
    ~/Documents/sparklink/crates/slk-protocol/src/types.rs
```

### 逐字段对比（人工）

| C 字段 | C 类型 | 字节数 | Rust 字段 | Rust 类型 | 字节数 | 偏移匹配？ |
|--------|--------|--------|----------|----------|--------|----------|
| handle | __u16 | 2 | handle | u16 | 2 | ✅ |
| state | __u8 | 1 | state | u8 | 1 | ✅ |
| _pad | __u8 | 1 | _pad | u8 | 1 | ✅ |
| ssap_reliable_mode | __u8 | 1 | **缺失** | — | 0 | ❌ |

---

## 步骤 3：识别 Padding 陷阱

### `repr(C)` 对齐规则

```
对齐 = max(所有字段的对齐)
每个字段的偏移 = 对齐到自身对齐的最小整数倍
结构体总大小 = 对齐到结构体对齐的最小整数倍
```

### 常见陷阱

**陷阱 1：u8 后跟 u16，中间有 1 字节 padding**

```c
// C
struct bad {
    __u8  a;      // offset 0
    // [padding 1 byte]
    __u16 b;      // offset 2
};
// sizeof = 4 (不是 3！)
```

```rust
// Rust repr(C) — 相同行为
#[repr(C)]
struct Bad { a: u8, b: u16 }
// size_of = 4
```

**修复**：显式添加 `_pad: u8`，或重排字段（u8 先聚在一起，u16/u32 放后面）。

**陷阱 2：结尾的小字段使整体扩展**

```c
struct borderline {
    __u8 data[62];
    __u16 len;    // offset 62 ← 正好对齐 u16，无 padding
};
// sizeof = 64
```

**陷阱 3：`__u8 _reserved[N]` 保留字段被遗漏**

内核常在结尾加保留字段以便未来扩展，Rust 侧必须原样添加 `_reserved: [u8; N]`。

---

## 步骤 4：修复用户态结构体

**修复步骤：**

1. **`crates/slk-protocol/src/types.rs`** — 添加缺失字段

```rust
#[repr(C)]
pub struct SleConnInfo {
    pub handle: u16,
    pub state: u8,
    pub _pad: u8,
    pub peer_addr: [u8; 6],
    pub mtu: u16,
    pub mps: u16,
    pub tcid: u8,
    pub _pad2: [u8; 3],
    pub features: u32,
    pub version_major: u8,
    pub version_minor: u8,
    pub ssap_version_major: u8,   // ← 之前缺失
    pub ssap_reliable_mode: u8,   // ← 之前缺失
    pub _reserved: [u8; 8],       // ← 保留字段也必须加
}
```

2. **`crates/slk-protocol/src/tests.rs`** — 更新/添加 `size_of` 断言

```rust
#[test]
fn struct_size_conn_info() {
    assert_eq!(size_of::<SleConnInfo>(), 64); // 必须等于 C sizeof
}
```

3. **同步 C 测试头文件**（如果 `tools/testing/selftests/sparklink/sparklink_ctl.c` 中有旧版定义）

```bash
grep -n 'sle_conn_info\|SleConnInfo' \
    ~/Documents/linux/tools/testing/selftests/sparklink/sparklink_ctl.c
```

如果有旧定义，手动更新（添加缺失字段）。

---

## 步骤 5：验证修复

```bash
# 用户态 size 断言
cd ~/Documents/sparklink && cargo test -p slk-protocol

# 全量测试（确认无回归）
cargo test --workspace

# 内核构建（确认 C 头文件未变动，不需要内核重编）
# 如果 C 头文件有变动：
cd ~/Documents/linux/build && make LLVM=-16 -j$(nproc)

# QEMU 最终验证
bash ~/Documents/linux/tools/testing/selftests/sparklink/run_qemu_test.sh
```

---

## 步骤 6：提交

```bash
# 用户态修复
cd ~/Documents/sparklink
git commit -m "slk-protocol: fix SleConnInfo ABI (add N missing fields, N bytes)

Kernel C struct has N bytes; Rust mirror was missing X, Y fields.
Add _reserved padding to match total size.

Tests: N passed."

# 内核侧 C 测试文件修复（如有）
cd ~/Documents/linux
git commit -S -m "net: sparklink: selftests: sync sparklink_ctl.c struct layout

Update SleConnInfo in sparklink_ctl.c to match current kernel definition.
Previous version was using packed 48B struct; now uses full 64B layout.

QEMU self-test: N OK / 0 FAIL.

Signed-off-by: sanchuanhehe <wyihe5220@gmail.com>
Assisted-by: GitHub Copilot <copilot@github.com>"
```

---

## 快速对照表：C 类型 → Rust 类型

| C 类型 | Rust 类型 | 大小 |
|--------|----------|------|
| `__u8` | `u8` | 1 |
| `__le16` / `__u16` | `u16` | 2 |
| `__le32` / `__u32` | `u32` | 4 |
| `__le64` / `__u64` | `u64` | 8 |
| `__s8` | `i8` | 1 |
| `__s16` | `i16` | 2 |
| `__s32` | `i32` | 4 |
| `__u8 arr[N]` | `[u8; N]` | N |
| `__u16 arr[N]` | `[u16; N]` | 2N |

---

## 历史已修复的 ABI 问题

| 结构体 | 问题 | 修复 commit |
|--------|------|-----------|
| `SleConnInfo` | 用户态 56B vs 内核 64B，缺 `ssap_reliable_mode`、`ssap_version_major` | `2870f00` |
| `sparklink_ctl.c` 内的 conn_info | packed 48B 旧定义 | `3a1dd82` |
| `SsapAddService` | 缺 `_pad: u8` 导致 u16 对齐 padding 不匹配 | 内联修复 |
| `SsapAddProperty` | 缺 `_reserved: [u8; 2]` | 内联修复 |
