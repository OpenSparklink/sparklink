---
name: sparklink-qemu-debug
description: 'SparkLink QEMU 测试失败调试工作流。当 run_qemu_test.sh 输出 FAIL、"No test result found"、内核 panic、oops、BUG、unknown ioctl、ioctl 返回意外错误码、QEMU 启动超时时使用。触发词：QEMU失败、测试挂住、No test result、panic、Oops、内核崩溃、测试回归、BUG at。'
argument-hint: '失败的测试名称或错误信息片段'
---

# SparkLink QEMU 测试失败调试

## 快速定位流程

```
run_qemu_test.sh 输出
      │
      ├─ "No test result found" ──→ 【A. 启动/崩溃类】
      ├─ "N FAIL"               ──→ 【B. 测试逻辑类】
      ├─ 超时无输出              ──→ 【C. 挂死类】
      └─ 构建失败               ──→ 先看 sparklink-kernel-dev
```

---

## A. 启动/崩溃类（"No test result found"）

### A1. 获取完整日志

```bash
bash ~/Documents/linux/tools/testing/selftests/sparklink/run_qemu_test.sh --verbose 2>&1 | tee /tmp/qemu_verbose.txt
```

### A2. 关键字过滤

```bash
# 内核 panic
grep -i 'panic\|BUG:\|Oops\|Call Trace\|RIP:\|kernel BUG' /tmp/qemu_verbose.txt

# 模块加载失败
grep -i 'sparklink\|insmod\|modprobe\|rmmod\|Unknown symbol' /tmp/qemu_verbose.txt

# 设备枚举失败
grep -i 'usb\|sle-dli\|sparklink_test\|/dev/sparklink' /tmp/qemu_verbose.txt
```

### A3. 常见原因 → 修复

| 现象 | 原因 | 修复 |
|------|------|------|
| `BUG: stack frame too large` | 函数局部变量 > 8KB | 提取 `#[inline(never)]` 子函数（参考 sparklink-kernel-dev Step 5） |
| `kernel BUG at net/sparklink/sparklink_core.rs:NNN` | unwrap/unreachable 触发 | 找到 BUG 行，替换为 `?` 或 `EINVAL` 返回 |
| `Oops: general protection fault` | 空指针或越界访问 | 检查 `as_mut().ok_or(ENODEV)?` 是否缺失 |
| `sparklink: unknown ioctl 0xXXXX` | ioctl 号在测试程序中与内核不匹配 | 同步 `sparklink_ioctl.h` 到 initramfs |
| `/dev/sparklink: No such file` | 模块未加载 | 检查 init 脚本中的 `insmod sparklink.ko` |
| `QEMU_TEST_RESULT: FAIL (exit=1)` | sparklink_test 自身返回非零 | 看 `sparklink_test` 输出的 FAIL 行 |

---

## B. 测试逻辑类（"N FAIL"）

### B1. 定位 FAIL 行

```bash
grep 'FAIL\|ERROR\|errno' /tmp/qemu_verbose.txt
```

### B2. ioctl 失败分析

| errno | 含义 | 常见原因 |
|-------|------|---------|
| `ENOTTY (25)` | ioctl 号未注册 | match 分支缺失，或 ioctl 号计算错误 |
| `EINVAL (22)` | 参数非法 | 字段越界、状态不满足前置条件 |
| `ENODEV (19)` | 子系统未初始化 | `as_mut().ok_or(ENODEV)` — 确认初始化顺序 |
| `EBUSY (16)` | 资源正在使用 | 竞态，检查锁持有顺序 |
| `ENOMEM (12)` | 内存分配失败 | KVec/kmalloc 失败，QEMU 内存可能不足 |
| `EPERM (1)` | 权限不足 | `/dev/sparklink` 权限，检查 udev 规则 |

### B3. 追踪具体 ioctl 失败

在 `sparklink_core.rs` 对应分支加临时日志（调试用，提交前删除）：

```rust
Err(e) => {
    pr_err!("sparklink: ioctl {:#x} failed: {:?}\n", cmd, e);
    Err(e)
}
```

---

## C. 挂死类（超时无输出）

```bash
# 延长超时
QEMU_TIMEOUT=300 bash run_qemu_test.sh --verbose

# 检查是否死锁（看挂在哪个 ioctl）
grep 'ioctl\|LOCK\|mutex\|spin_lock' /tmp/qemu_verbose.txt | tail -20
```

常见原因：
- Mutex 死锁（A 持锁等 B，B 持锁等 A）
- `SUBSYSTEM.lock()` 在中断上下文中调用
- USB bulk transfer 永久等待（无超时）

---

## D. 测试数量异常（比预期少）

正常基准：**738+ OK / 0 FAIL**（Build #262 后）

```bash
# 数量骤降 → 某个测试 Phase 提前退出
grep '^  OK:\|^  FAIL:\|Phase [0-9]' /tmp/qemu_verbose.txt

# RalRemove EBUSY 是已知偶发竞态，不计为回归
grep 'RalRemove\|EBUSY' /tmp/qemu_verbose.txt
```

---

## E. 构建验证（运行测试前先确保构建干净）

```bash
cd ~/Documents/linux/build && make LLVM=-16 -j$(nproc) 2>&1 | tail -5
# 期望：Kernel: arch/x86/boot/bzImage is ready  (#NNN)
# 任何 error: → 先修构建，再运行 QEMU
```

---

## F. 栈帧溢出专项检查

QEMU 以 `used greatest stack depth: NNNN bytes left` 结尾，关注 **<1000** 时：

```bash
# 找大局部变量
grep -n 'let.*=.*\[0u8; [0-9]\{3,\}\]\|SleConn\|SleAdv\|SleSec\|SleSync' \
    ~/Documents/linux/net/sparklink/sparklink_core.rs
```

凡是在一个 match arm 内分配 **>64B** 局部变量（含 `read_user_struct` 返回的大结构体），
必须提取为独立 `#[inline(never)]` 函数。参考 `sparklink-kernel-dev` Step 5。

---

## 调试完成后

1. 修复代码
2. 重新构建：`cd build && make LLVM=-16 -j$(nproc)`
3. 重跑 QEMU（不加 `--verbose`，确认 "0 FAIL"）
4. 按 sparklink-kernel-dev 的 GPG 提交规范提交
