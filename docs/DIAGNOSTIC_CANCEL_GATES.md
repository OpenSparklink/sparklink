# Native diagnostic 取消、迟到回复与期限门禁

日期：2026-10-11。整项 K2/K3/K19、U1/U2/U8/U10 保持 OPEN。
本工作落实 ADR0001 的事务关联要求；WS73 discovery、S0–S6 与 VM-only 保持。
用户再次提供的 BlueZ 分析 SHA256 为
`f8de2edb3e4c6a2cca1442ce06ba59c03407469b7f8631539e974743c993853a`，
与已采用分析相同，不新增重复架构或 issues。

## 实现和调用关系

生产内核仍为 `54621800ee4c` 的路径，用户态生产 crates/data 仍为
`df9cff7d750d`；本次 Linux `091a57bb52f4` 只修改专用 QEMU selftests 工具。
旧诊断/共享事件的最终删除仍依赖调用者迁移及回归，未发布 UAPI 无兼容期。

`ioctl_diagnostic_submit` 校验作者、generation、request id、opcode 和原 timeout；
保留的同一 admission 不重发、不续期。`CmdPendingQueue::cancel_seq` 为作者保留
ECANCELED 最终结果，不能由之后的成功回复改写。`CommandHost::cancel_diagnostic`
移除排队命令，但在途命令保留真实 wire 回复槽；只有实际匹配回复被消费或
真实超时引发故障退役，才释放这个槽。没有线上事务号，不能把本地 id 当作
固件回传 id，也不能提前发送同 opcode 并把旧回复完成给新作者。

实际成功回复经 Host transport 完成关联和原 sequence 返回；已取消/超时的
本地结果不能复活。这里是源码审计和已有开发测试结论，仍需以下实机门禁。

## 已完成的专用测试基础

新 QEMU patch 暂留一次实际成功、非空的 bulk IN81，不修改 transfer 的数据、
长度或成功状态，不构造 Complete。只允许实际 attached 的 ffff:3733 WS73，
全部 host/guest reset 和 kernel detach 关闭；默认不开启，与人工 IN81 error 互斥。

暂留保留原 request/transfer/buffer，日志记录字节数及实际 SHA256。显式 release
通过原 callback 交付；REALTIME timer 截止为两秒，由事件循环执行，不是硬实时
保证。取消/abort 先清理 timer 和暂留身份，再释放已完成 transfer 一次，不再
调用 libusb cancel。close 清除未消费脉冲，并通过原 abort/drain 路径清理对象。
disarm 不丢弃已暂留的数据；无实际暂留的 release 和对其他对象的 release 拒绝。

[开发证据](evidence/qemu-runtime-hold-development-20261011.json)记录：

- 完整 QEMU 9.2.0 编译及冻结 binary/object/source/configuration。
- 固定上游归档重建实际源码，与完整构建的 host 源码 SHA256 一致。
- 实际 hold/callback/abort/cancel/getter/setter 的计数依赖 fixture 和 ASan/UBSan。
- 原 runtime-error callback/setter 回归，hold 依赖在该 fixture 中必须不被调用。
- 七个完整补丁前缀升级/幂等、八类上下文漂移拒绝，失败不修改输入。
- 暂停、未 attached 的 TCG/QMP 默认、只读、拒绝 arm/release 检查，无真实 USB 匹配。

timer、transport、digest、USB combining 是依赖替身。上述结果不证明实际 QEMU
调度、完整 close drain、多设备并发、真实取消/迟到/期限或自然故障恢复。
[固定源码CI38095468362](https://github.com/OpenSparklink/sparklink/actions/runs/38095468362)
九作业全部成功；已读取终结日志确认新增QEMU门禁和170 Rust/34 Python/170工具
实际执行。CI运行固定归档依赖门禁，不编译完整QEMU、不执行USB或guest。
构建/fixture 的失败尝试保留，修正后重测；不能将它们抹成首次全部通过。

## 接下来执行的实际 VM 门禁

| 门禁 | 需要的实际证据 | 失败处理 |
|---|---|---|
| 在途取消 | arm 后真实 MAC OUT，QEMU 暂留的真实成功 IN；作者结果变 ECANCELED，重复查询字节/计数不变 | 记录原始 errno、完整结构及日志，不生成测试成功 |
| 排队取消 | 旧 wire 槽被暂留时排入新查询再取消；队列中移除，无该查询实际 OUT | 全窗口 USB 捕获，不仅检查局部样本 |
| 迟到隔离 | 同 opcode 新查询仍 Pending，无提前 OUT；显式释放旧回复后旧结果不复活，新查询仅由自己的 OUT/回复完成 | 对照 QMP 时间、暂留 SHA256、USB/HCC/DLI 与结果 sequence |
| 原截止时间 | 相同 id 重试不续期；排队过期不发包；在途过期走原有受控退役和有限恢复 | 记录实际截止/状态/计数；不使用人工拔插恢复 |
| 清理隔离 | 有实际暂留时关闭/取消/退役；旧 timer 不重放、另一设备不受影响 | 单/多设备分别记录，适用时运行内存/锁检查 |
| 路径回归 | 当前镜像普通 UID/caps0 WS73 20+2、随机数据/地址/RSSI、同 daemon、read 与 diagnostic 原门禁 | 新失败不得引用旧版本通过替代 |

测试协调只存在专用 guest/host 工具，不加入生产内核 hook。客体在 daemon 前
执行受控 root Diagnostic；应用 RF 回归仍由普通用户执行。显式 release 应在
timer 到期前完成且 bounded-release 计数为零；自动到期不能冒充显式释放验收。
实际 timer/close 行为另行验收。故障恢复后无需重启 slkd，幸存者 generation 保持。

最新真实基线仍是 K`9b16e634bfd3`/编译 U`1d3a17b688ee` 的
[20+2/read/结果/copyout/淘汰/legacy poll 证据](evidence/ws73-vm-legacy-poll-live-20261011.json)。
该镜像未使用本次新 QEMU binary；本次没有新增 RF 或取消实机验收声明。
自然启动/重枚举/消失根因、自主恢复、历史物理 xHCI warning、四设备两组、
socket/用户态 SSAP/每连接安全/Bond/Profile/Proxy/完整 sandbox 与发布仍 OPEN。
