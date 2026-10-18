# Controller 事件与位置契约

本页依据用户态 `dc040002555c`（事件实现 `bf7a189a4a52`）与 Linux `e78b88f050aa`。
描述已实现接口，不转授历史镜像的资格；精确实机范围仍从
[当前能力](../../project/current-capabilities.md) 查找。UAPI 尚未发布。

## 三种不同用途

| 用途 | 接口／来源 | 边界 |
|---|---|---|
| 获取完整事件 | `ControllerEventGet`／Rust、C、Python Native 接口 | controller 注册身份与独立读取游标；不是旧 `read(2)` |
| 查询注册内的位置 | D-Bus `org.sparklink.Controller.GetControllerEventPosition`；`slctl events` | 返回 `(index: u16, generation: u64, sequence: u64)` |
| 诊断复制流量 | 独立 snoop 订阅 | 单独权限；不能消费或替代 Host 的协议处理 |

位置查询复制当前 adapter／generation 后释放 daemon 业务锁，再调用
`native_link_snapshot(generation)`。返回值来自实际 `LinkSnapshot.event_seq`，
不是缓存的成功事件、队列深度、已交付数量或对端业务 ACK。
未取得 Native 身份（generation 为零）时返回 D-Bus `NotSupported`；
内核或阻塞任务错误映射为 `Failed`，调用者不能将失败当作位置零。

## 完整事件与失败

`ControllerEventGet` 的请求必须使用本次 controller 注册的 generation。
完整记录、查询参数和字段布局以匹配 Linux 头文件及 `slk-protocol` 类型为准。
不要复用另一只设备或重新注册前的身份。发现事件缺口后不能仅查询水位来宣称
完成状态重同步；完整 resync 屏障和竞争矩阵仍有未完成范围。

用户内存复制失败返回 `EFAULT`，不得提前推进该读取者的 readiness。
当前实机回归覆盖四个只读页边界的部分复制、重试、独立 fd 重放及可读状态保留。
它没有证明并发溢出、所有关闭竞争、KCSAN 或完整状态迁移。

## 已删除与明确不支持

| 旧入口 | 当前行为 |
|---|---|
| 44 字节 `read(2)` 事件流 | `EOPNOTSUPP`，没有旧队列 fallback |
| `EVENT_COUNT`（0x70）、`EVENT_STATS`（0x71） | 已删除；原 ioctl 编号返回 `ENOTTY` |
| 旧 DLI poll（0x82）、Raw256 绑定 | 已删除，无兼容期 |
| 默认生产的广播／连接事件注入 | 特权检查后明确 `EOPNOTSUPP`，不生成成功事件 |

未激活完整事件或 snoop 订阅的旧 poll 使用方式返回 `POLLERR`，不能继续等待旧队列。
Python `NativeAdapter.poll_event` 是现有非消费完整事件接口，名称相似不代表旧 ABI。

源码：`crates/slkd/src/controller.rs`、`crates/slk-native/src/ioctl.rs`、
Linux `net/sparklink/sparklink_core.rs` 与 `include/uapi/linux/sparklink.h`。
[本批准确证据](../evidence/read-retirement-progress-20261014.json) 和
[历史 read 审计](../../history/diagnostics/event-copy-remediation.md) 分开阅读。
