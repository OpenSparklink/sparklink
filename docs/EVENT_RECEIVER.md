# Event receiver 与管理 fd

`Adapter::open()` 只持有同步 `OwnedFd`，C/Python 和同步 CLI 不需要 Tokio
runtime。异步接收通过独立打开的 Adapter 调用 `into_event_receiver()`，将
fd 转交给单 consumer 的 `EventReceiver`，只有这一步需要带 I/O 的 Tokio
runtime。旧 `Adapter::next_event()` 保留为弃用的兼容入口。

slkd 的 `EventTask` 独占 receiver。它等待事件时不引用或锁定 `SharedState`；
收到事件后才更新状态，D-Bus object 注册在解锁后进行。正常退出发送 cancel
并 join，确保 receiver/fd 释放后才释放 D-Bus connection；异常丢弃 task 会
abort。取消涵盖 pending receive 和异步 dispatch 等待。

当前内核仍使用破坏性 DLI ring 与不完整 poll wakeup。因此 receiver 尚不是
fan-out subscription，50ms legacy fallback 保留原值；该锁修复不依赖缩短它。
独立状态/snoop 订阅由 Linux #3 与用户态 #2 实现。Bond 元数据的 load/save/remove
现通过 blocking pool 执行，存储锁独立于业务状态锁；D-Bus 调用只在业务锁内
克隆存储 handle。存储服务捕获主 runtime 的 Handle，兼容 zbus 自有 executor。
已提交的写入即使调用方取消也会持有存储锁到磁盘和 cache 更新完成，防止
随后的 remove 越过写入。正常退出先停事件任务，再关闭 D-Bus，最后等待
存储锁并拒绝所有 handle 的后续写入。阻塞的文件系统仍可能延长退出等待。

旧安全事件不含 peer/connection 标识。只有恰好一个已连接 peer 时才记录
legacy metadata，多连接情况下拒绝猜测。此记录仍没有可恢复凭据，不能
作为 Bond/重连安全验收。

连接 Profile 回调现由 `ProfileService` 独占 registry，以独立锁和捕获的主
runtime Handle 在 blocking pool 串行执行。业务状态仅更新后克隆该 handle；
连接 D-Bus object 注册在 callback 之前。取消事件 dispatch 不会强行打断已
开始的 callback，后续断连不会越过它，退出等待 accepted callback 完成。
callback panic 在释放 registry 锁前关闭服务，所有 clone 拒绝再次调用。
事件任务即使 join 失败，主流程也先关闭 D-Bus 并 drain 两个独立服务再返回错误。

这是旧连接 callback 的执行隔离，不是用户态 SSAP Engine：服务数据库和
read/write 仍在内核，Profile request context、timeout/security 和真实 PDU
尚待迁移；对象仍固定 slk0。当前 event dispatcher 仍顺序等待存储与 callback，
所以慢 callback 会延迟后续事件分发，虽不再占业务锁或 Tokio worker。
S2/S4 的有界事件路由与 SSAP session 必须进一步隔离这种背压。永久阻塞的
可信 in-process callback 可以延长 daemon 退出；不能用任务 abort 假装停止它。

## 无硬件回归

```sh
cargo test --workspace --locked
```

需要 `dbus-daemon`。可通过 `SPARKLINK_TEST_DBUS_DAEMON=/path/to/dbus-daemon`
使用工作区内的二进制。测试只创建私有 session bus，不使用系统总线。

测试用有界 channel 作为可控制的事件源，并调用真实的 slkd D-Bus interface：

- 旧持锁等待路径稳定使 Name 查询超时；取消后同一查询恢复。
- 静默 30s 期间 Name、GetDliInfo、StartDiscovery、ConnectDevice 调用响应；
  `/dev/null` 的实际 ioctl 错误作为返回结果，不伪造成功的硬件控制器。
- 静默后广播事件更新共享状态并注册可查询的真实 D-Bus Device object。
- 正在等待接收或业务状态被锁定时 shutdown 均能 join，并释放事件源。
- 同步 Rust/C open 成功不需要 reactor，receiver drop 关闭其 transport，
  超长/截断事件返回错误而不越界。
- 阻塞存储线程时真实 D-Bus RemoveBond 等待，Name 查询和事件任务退出仍响应。
- 取消已提交的写入后 remove 必须等写入结束；shutdown 等待写入并拒绝新写入；
  写入失败不把成功记录发布到 cache。磁盘重载验证最终顺序。
- 零个/两个已连接 peer 的 legacy 安全事件不生成 metadata；单 peer 精确归属。
- 真正阻塞 Profile callback 时 Name 和连接状态仍可读，真实 D-Bus 连接对象
  已注册；事件 receiver shutdown 释放事件源，Profile shutdown 等待 callback。
- 取消 callback waiter 后 disconnect 保持序列；shutdown drain 并拒绝新回调；
  callback panic 使服务关闭，不重入可能不一致的插件。

这些证明锁、任务/FD 生命周期和接口响应，不是实际控制器、独立订阅、
RF、安全或完整 SSAP 的验收。
