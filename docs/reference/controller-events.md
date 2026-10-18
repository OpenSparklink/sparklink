# Controller 事件与位置契约

本页依据用户态 `dc040002555c`（事件实现 `bf7a189a4a52`）与 Linux `e78b88f050aa`。
描述已实现接口，不转授历史镜像的资格；精确实机范围仍从
[当前能力](../../project/current-capabilities.md) 查找。UAPI 尚未发布。

## 不同事件来源与用途

| 用途 | 接口／来源 | 边界 |
|---|---|---|
| 获取完整事件 | `ControllerEventGet`／Rust、C、Python Native 接口 | controller 注册身份与独立读取游标；不是旧 `read(2)` |
| 查询注册内的位置 | D-Bus `org.sparklink.Controller.GetControllerEventPosition`；`slctl events` | 返回 `(index: u16, generation: u64, sequence: u64)` |
| 诊断复制流量 | 独立 snoop 订阅 | 单独权限；不能消费或替代 Host 的协议处理 |
| 应用目录变化 | Rust `Client::controller_events(Deadline)`、`slctl controller-events [count] [ms]` | daemon 的现有 `ListAdapters` 目录发布／撤回；不是 Native 事件、Ready、物理 Down 或资源 drain |

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

## 应用目录观察（Rust／slctl源码入口，资格另验）

`org.sparklink.Manager.GetControllerChanges(after, wait, deadline)`接受原绝对期限，
`deadline`使用既有五uint64时钟域绑定。返回版本、最早保留序号、当前尾序号、Gap
及至多64行`(sequence, index, generation, action)`；action 1为目录发布，2为目录撤回。
游标仅属于原daemon唯一总线owner，不是Kernel ControllerEvent序号。
此处只跟随已有Runtime adapter目录；初始化前的注册故障观察仍用`ListRegistrations`，
Supported／Enabled／Available／Powered和完整状态变化资格不由此补齐。

同一锁保护目录更新与journal追加。history只保存身份，不持Native fd、lease或连接。
SDK先取游标，再执行原Core校验的成员查询；初始Snapshot后的行可能重复该查询已见
的身份，不承诺原子Native快照。撤回在目录移除时产生，不能当owner退休、物理断链、
callback排空或fd清理完成的屏障。查询实际Ready、连接和安全状态仍走其各自来源。

慢观察者落后于64行窗口会收到明确Gap，当前stream终止，调用者须显式重新快照。
未知版本、未来游标、非连续序号、错误identity和序号耗尽不能静默跳过或重置。
每次服务端等待至多5秒，全局16个等待、每个真实总线caller至多2个；SDK对空响应
复用同一原期限，不延长等待。`next(Deadline)`的本地超时不推进游标；其他错误或
owner丢失会终止stream。取消等待／丢弃stream仅结束观察，不停止扫描、controller
或他人的通道；服务端未取消的等待可保留其预算至本次有界期限。

`slctl`的count为1..512，默认1（初始Snapshot）；ms为每次next的1..30000ms，
默认5000。输出`ControllerDirectorySnapshot`／`ControllerDirectoryEvent`；Gap、
超时和错误非零退出。它复用普通Rust Client，既不取得管理lease，也不自动重连。
C／Python入口复用同一Rust stream，具体交付及释放契约见下文。本分项实机／形式化
资格仍以[唯一能力入口](../../project/current-capabilities.md)的准确artifact记录为准；
旧fd0产物的Rust/slctl资格不转授新增语言入口。

### C／Python目录观察边界

`slk_client_controller_events(client, deadline_ns, output)`产生opaque观察句柄，
`slk_controller_events_next(observer, output, ids, capacity, count, flags, deadline_ns)`
读取，`slk_controller_events_close`释放。它们复用原Client的caller和有界executor；
先关闭Client不销毁仍被派生观察引用的caller。最终引用释放才join本地执行线程。
关闭观察者不停止扫描、撤销Grant或清理controller。

`SlkControllerEvent`为32字节：sequence／oldest／current为u64，kind／reserved为u32；
kind在偏移24。kind为1 Snapshot、2 Published、3 Withdrawn、4 Gap，reserved为零。
Snapshot的sequence是before游标，Gap的sequence是after；oldest/current仅Gap使用。
身份数组使用原16字节`SlkControllerId`。它不是Native事件或可信状态编码。

capacity为0..256，非零时buffer须为有效区域；flags=0成功复制后消费，flags=1为peek。
ENOBUFS只写所需count，不改metadata或buffer，也不消费；其余错误输出不变。
超时或peek保留已收到的单条观察；消费Gap后后续next为ESTALE，须显式新建观察。
无静默截断、跳过缺口、重新连接或自动重快照。同一C观察句柄并发next为EAGAIN；
所有同Client请求仍共用至多8个排队和1个执行请求，长等待读会延迟该caller的其他
请求，不承诺独立进程故障域或异步dispatch。

deadline_ns为原始绝对CLOCK_MONOTONIC，未来且至多30秒；本地队列、RPC和交付前
检查沿用同一期限。C错误返回后不消费本地待交付观察；成功复制后调用者丢弃结果、
信号中断后未处理或进程死亡，不等于重新交付承诺。观察到事件不等于应用已处理。
C输出指针须有效、对齐、独占且不别名；无效指针属于调用者UB，不是内核EFAULT门禁。

Python `Client.controller_events(deadline_ns=...)`返回`ControllerEvents`，
`next(deadline_ns=..., peek=False)`返回不可变`ControllerEvent`，其kind为
`snapshot`／`published`／`withdrawn`／`gap`，controllers为身份tuple。支持上下文管理器。
调用和close串行；fork后在触碰继承mutex前拒绝使用，先exec／spawn再创建新Client。
Python不自行调用D-Bus或解释另一套wire事件。畸形ABI输出明确报EPROTO并释放该
观察，不自动重试。当前新增语言入口尚须各自准确artifact的实机门禁，离线不授RF资格。
