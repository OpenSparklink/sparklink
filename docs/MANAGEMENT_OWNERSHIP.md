# 原生 WS73 管理 ownership v1

每个原生 WS73 registration 只接受一个 Managed 或 Diagnostic 控制 fd。
普通应用继续通过授权 D-Bus 使用 slkd；slkd 在发布 adapter 前取得 Managed
lease，初始化、广播/扫描和旧管理方法共用同一个每设备 fd。事件订阅使用
独立观察 fd。取得 lease 和每次受保护调用仍要求实际调用者的 CAP_NET_ADMIN。

lease 绑定 open file description 与固定 generation；dup、fork、传 fd 保留
同一 owner，不按 PID/UID 判定。把真正持有 owner 的 fd 传给无 capability
的进程不会转移管理权限。拥有 lease 期间 DEV_SELECT 返回 EBUSY，先释放
再选择；旧代次、错误 token、其他文件和错误 mode 均不能释放/写入。

三个新 ioctl 使用无指针、8 字节对齐的固定结构：ACQUIRE `_IOWR` 32 字节、
RELEASE `_IOW` 32 字节、QUERY `_IOWR` 48 字节。版本为 1，输入的 flags/
reserved 必须为零。ACQUIRE 输入 generation/mode，lease 输入零；内核生成
单 registration 单调 token，仅在 copyout 成功后提交 ownership，不提交
硬件命令。EFAULT 不留下不可见 lease。RELEASE 必须给出完整匹配的身份。
QUERY 的 generation=0 可探测当前绑定；token 只返回给 owning fd。

| QUERY state | 含义 |
|---|---|
| 0 Free | 可申请；上一 owner 已安全静默或恢复停止完成 |
| 1 Held | 同一个 fd 的 Managed=1 或 Diagnostic=2；flags bit 0 表示 owning fd |
| 2 Revoking | 已撤销用户写入，等待实际线上的回复和清理停止；后继不能申请 |
| 3 Faulted | 停止失败、超时或准备失败；保留原因，不能重新授予 lease |

QUERY error 是负 errno；flags bit 1 表示存在原始失败回复，此时 status/opcode
保留控制器值。缺失回复的 timeout 不伪造 status，保留已发命令 opcode。
首次故障不会被后续队列 deadline 覆盖。读取 QUERY 可以投影 Host 已完成的
revocation 状态；它不发命令或修改电源策略。QUERY、快照和事件观察不消费
raw 队列。原有135个 ioctl 加三个新入口后，明确分类为35观察、2fd选择和
101受保护操作。

Managed 使用 typed discovery；raw DLI send/poll/reset 属于 Diagnostic。
两种 mode 互斥，原生 genl 管理 bridge 无 registration-bound fd，返回 EPERM，
不成为另一条写入口。当前 native raw whitelist 只接受四个真实查询，未扩大
到广播/扫描的厂商参数。Virtual/标准 USB profile 0 仍处于旧接口迁移窗口，
新 lease ioctl 返回 EOPNOTSUPP；不能据此宣布所有 Backend 的 ownership 完成。
Proxy/PDU/Security owner、其余 canonical 迁移和完整权限 issues 继续待做。

RELEASE 和最后一个 owning fd 关闭使用相同撤销路径。已发送命令保留其回复
reservation/deadline，未发送的操作取消；driver 准备两个停止 recipe，Host
按同一 credit/调度逐个确认，不能在 submit/close 时标成 Off。两个停止完成后
才允许后继，已安全 Off 且 quiet 的 Managed 可以立即释放。quiet Diagnostic
只执行受限查询，可以立即释放；非 quiet 则走停止屏障。allocation/准备失败、
失败停止或缺失 Complete 都锁存 Fault/Unknown，不伪造 credits 或 Reset 恢复。
当前成功清理支持同 registration 后继；不确定故障的恢复依赖重新插入产生
新 generation，自动原地 reset/recover 尚未实现。其他 controller 独立运行。

可复现的合成 USB ownership 门禁：

```sh
python3 linux/tools/testing/selftests/sparklink/run_runtime_lifecycle.py \
  --kernel-build /absolute/path/qualified-kernel-build \
  --qemu /absolute/path/custom-qemu-system-x86_64 \
  --busybox /absolute/path/static-busybox \
  --native-ws73 --native-ws73-management \
  --output /absolute/path/new-evidence-directory
```

需要可用 static libc 与 KVM/QMP Unix socket。门禁实际执行 ioctl/fork/dup/
credential drop，验证竞争、错误 mode/token/generation、owner retarget 拒绝、
ACQUIRE EFAULT 不提交、无权限 inherited owner、最后关闭后实际停止、失败停止
原始 status/opcode、超过 deadline 后首次故障仍稳定、pending wire-slot 关闭
后的取消与 timeout，以及重插新代次。模型显式合成 USB/空口，绝不算 WS73
固件、普通用户实机部署或真实 RF 验收；北极星七项和完整方案继续开放。


当前隔离验证（2026-10-10）：181harness、146workspace与目标crate严格clippy
通过，11条集成门禁通过。完整原96-case QEMU 1056 OK/0 FAIL/0 SKIP/3旧WARN。
最终qualified源码/输入guard与#64镜像冻结；不完整两设备回归的SKIP及先前构建/
测试环境失败保留。全slkd已有strict-clippy问题仍未通过。实机WS73=[]，未做RF。

## daemon 正常撤销与接任

slkd 保存每个 native registration 的 lease。在对象撤销时，先从目录移除、
标记不在场并取消初始化，再显式 RELEASE；此时 SharedState、控制 Arc 和
可能在途的 RPC 仍可持有同一 fd。内核撤销 authority 后，这些引用不能继续
提交管理命令。事件/接口/actor 的异步退出在释放后进行，最后关闭仅作为
崩溃时的兜底。部分 D-Bus 发布失败也显式释放，而非等引用消失。

RELEASE 后每设备独立观察 QUERY，最多6秒等待 Free；不持有目录/SharedState
锁跨 ioctl 或等待。设备已拔出（ENODEV）视为该 registration 已失效；Faulted
或观察超时记录原因，不将 radio 改成 Off，也不强行重置/重新授权。若其他
fd 已成为新 owner，旧 fd 观察到 Held 但没有 owner flag，即已成功交接。
SIGTERM（systemd 正常停止信号）与 SIGINT 使用同一正常 shutdown 路径。

新增实际 daemon 门禁：

```sh
python3 linux/tools/testing/selftests/sparklink/run_daemon_lifecycle.py \
  --kernel-build /absolute/path/qualified-kernel-build \
  --qemu /absolute/path/custom-qemu-system-x86_64 \
  --busybox /absolute/path/static-busybox \
  --userspace /absolute/path/sparklink \
  --dbus-daemon /absolute/path/dbus-daemon \
  --radio-policy --production-policy --kernel-authorization --management-handoff \
  --output /absolute/path/new-evidence-directory
```

先运行原20轮换向与同 daemon 重插2轮，再保持一只广播、另一只扫描，SIGTERM
停止；独立 C 观察 fd 校验隐去 token 的 Held→Free、真实 Host stop 完成后的
Off/Ready，daemon 自己在保留控制 fd 时确认释放。新 PID/新 D-Bus owner 在
同 generation 重新取得两个 Managed lease，无 USB 重插；随后 SIGINT 停止
并再次观察 Free/Off/Ready。合成 fixture 的数据与 RSSI 不属于真实空口证据。
该扩展验证成功清理；daemon 故障清理、强制终止及完整 Backend 接任矩阵
仍待扩展，已有内核失败停止/在途关闭/缺失 Complete 门禁继续保留。

## slkconfig 的显式选择与离线 Diagnostic 查询

所有每设备命令现在要求 `--adapter INDEX`，不改变全局默认 controller。
`adapters` 列出 registration/generation；`controller` 显示选定 snapshot 与
每设备命令队列，`management` 只读观察 owner 状态。可用 `--generation G`
拒绝误用重插后的代次，0不合法。只读观察不取得 lease，也不消耗 raw 回复。

```sh
slkconfig adapters
slkconfig --adapter 0 controller
slkconfig --adapter 0 --generation 123 management
slkconfig --adapter 0 --generation 123 query features
```

以上 index/generation 为示例，使用实际观察值。原生 `query` 必须提供确切
generation；只支持 WS73 profile 1 的 mac/features/version/buffers。它取得
独占 Diagnostic lease，Managed owner 存在则 EBUSY；无 CAP_NET_ADMIN 则 EPERM。
普通应用仍通过 slctl/slkd 控制，不需要 sudo；离线 raw 诊断是管理员入口，
不靠设备组权限获得 capability，也不抢占/停止其他 owner。

旧 raw POLL ABI 没有 reply sequence。工具不伪造请求关联：取得 exclusive
lease 后最多清空256条历史回复，检查 pending=0，然后只提交一个白名单查询。
输出 `admission_seq` 仅为内核接受时的编号，不是回复中的字段。匹配 opcode
的成功 Status 只表示接受，继续等待 Complete；失败 Status/Complete 保留
原 status。成功 Complete 严格校验 MAC/features/version/buffer 的6/10/5/6
字节，不截短80位 features或版本。已由内核验证的零opcode空 credit 通知可
夹在命令之间，它不是查询回复，credits 始终由 Host 管理。其他意外回复拒绝。
`drained` 是提交前清掉的历史投影记录数，可以包含 credit 通知。

回复与清理各有6秒观察期限；错误路径也 RELEASE，清理失败不打印成功。
旧 PHY、扫描、连接、配对与 SSAP 管理命令仅在 profile0迁移路径保留，原生
路径在调用旧 ioctl 前明确拒绝。旧 profile0 scan 参数使用选定设备 index。
缺省设备选择已移除，原调用应加 `--adapter`；原生 reset未实现，不宣称恢复。

在上述 daemon 复现命令后增加 `--diagnostic-tools`（要求
`--management-handoff --radio-policy`），运行实际 slkconfig：普通UID1000/
CapEff=0可观察、查询被拒绝；Managed冲突、缺目标/代次、旧generation与
legacy reset均不增加命令或改变snapshot。随后 C Diagnostic owner先清空
历史管理回复，再留下一条未读查询；工具清空其 Status/Complete 对及可能的
credit通知，分别完成两设备八次查询。后继slkd同代次 Ready接管，正常退出。
生产/session两条门禁、209harness、148workspace、slkconfig严格clippy及原
96-case回归通过。早期Status、历史队列/credit数量假设失败保留；slkmon/
slkdump独立snoop、C/Python ownership绑定、profile0完整迁移与故障矩阵仍待做。

### 原生 C/Python 绑定（2026-10-10，部分成果）

新C符号返回负errno；旧符号保留原0/-1约定。`slk_adapter_select`绑定每fd注册，
snapshot/management query/acquire/release和typed discovery result保留generation、
lease、状态/原始失败原因与异步清理；另fd拿token不获authority。Python独立
`NativeAdapter`包装同一实际cdylib，避免静默u16/u64截断，close与ctypes调用串行。
完整事件及snoop非消费读另见[Python契约](../bindings/python/README.md)。
两语言/root及ordinary读写授权、Busy、接任/Diagnostic与真实模型Complete在
[客体门禁](WS73_TARGET_ENVIRONMENT.md)验证；不是实际硬件完成。旧profile0、
Diagnostic raw query binding、Proxy/PDU/Security ownership和完整故障矩阵仍待做。
