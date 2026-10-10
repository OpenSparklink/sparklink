# 第一北极星：普通用户的双真实 WS73 广播与发现

用户确定于 2026-10-10。完整联合方案与全部原 issues 保留；本目标决定
第一条优先交付路径，不替代 SSAP、安全、Vendor Proxy 等后续验收。

普通用户通过 `slctl` 选择两只真实 WS73，让一只广播、另一只发现它；
交换角色和拔插后仍能重复成功。Virtual/QEMU 是开发支撑，不能替代此闭环。

## 必须满足的验收

- 两只真实设备各自独立 Ready。必须完成各自启动、SLE 握手和真实 DLI
  查询，记录 controller id/generation、物理 USB 路径、地址、版本与能力。
  USB runtime 枚举、驱动绑定或缓存默认值均不能单独作为 Ready。
- 每轮生成新随机标识，编码进广播数据；另一只硬件在 10 秒内上报匹配
  数据、广播方地址和 RSSI，`slctl` 可显示全部字段。超时从实际扫描启动
  事务成功起按 monotonic clock 计算；禁止缓存命中、Host echo 或注入代替。
- 连续 20 轮成功，每轮交换广播/扫描角色，使用新标识并留存原始数据。
  任一失败打断连续成功计数；不能通过重跑覆盖失败记录。
- 拔出一只时，另一只的 Ready、generation 与控制能力保持有效。
  另一只的管理/停止/启动事务仍正常响应；消失的 peer 不再被当作新发现。
  旧 fd、迟到 completion 与旧 generation 不能指向重插设备。
- 重插后 slkd 无需重启；动态移除/添加 adapter，完成该设备重新初始化
  后能再次选择并完成闭环。保留 slkd PID、总线连接与两设备生命周期日志。
- 应用运行无需 sudo、root、setuid 或附加 capability。安装内核/固件及
  初次部署权限规则与应用运行分别记录；D-Bus 管理授权不放开 raw DLI。
- 提供可复现测试与真实空口证据。记录实际接收端返回的原始 USB/HCC/DLI
  discovery report、双端时间线、随机标识、地址/RSSI、固件/校准来源及
  源码/构建 hash；增加广播停止的阴性对照和重新启用的新标识验证。
  USB capture 不冒称 PHY 嗅探器的原始空口 PDU；有独立嗅探器时另列其来源。

- 不依赖人工拔插的故障恢复：查明启动超时、重枚举失败和设备消失根因，
  每设备有限重试/截止时间/状态/诊断，恢复一只不影响其他设备，恢复后无需
  重启slkd；原生Linux与QEMU、单只与多只分别验收。根因未明或仅靠重插
  不得关闭相关issue。详见[自动恢复方案](WS73_RECOVERY.md)。

20 轮表示至少 20 次交替角色的成功发现。热插拔后的复验单列，不能用它
补齐之前失败的连续轮次。随后扩展四设备两组并行，验证交叉报告归属及
单设备移除对另外三只的隔离，仍不关闭尚有原验收未完成的整项 issue。

## 实施依赖与最小 Runtime

1. **最小每设备 Runtime**（K#4/#9/#10/#11/#12）：引用计数对象独立拥有
   Backend、Host 初始化/命令状态、generation、RX/event/command 队列、
   生命周期和广播/扫描状态。注册表仅索引对象，查询后释放注册表锁；
   per-fd 持稳定对象引用。彻底消除 active device 状态交换和全局 pending
   的命令归属。Ready 不与注册合并。停止先拒绝新请求并失效 generation，
   再在锁外取消/drain I/O 与 worker；USB callback 不取 sleeping mutex。
2. **WS73 启动/HCC/BSLE**（K#13/#14/#15）：先核验端点、镜像与校准，再
   启动 BSLE/customize/SLE；每实例独立 buffer、聚合解析、URB 和错误恢复。
   Boot/runtime 重新枚举与无线 Ready 分开。禁止共享静态接收缓存或校准。
3. **真实 DLI 查询**（K#16）：显式 WS73 dialect 与 typed 查询，匹配
   Status/Complete 的 opcode、实例和 generation；发送成功不等于完成。
   查询结果验证后才发布 Ready，错误/超时只使该设备 Fault。
4. **广播/扫描**（K#2/#16）：完整参数、数据和 enable/disable 顺序；
   两个 Runtime 可同时处于不同角色，交换角色先停止原事务再开始新事务。
   首条路径不以完整连接/SSAP/security policy 为前置依赖。
5. **内核事件**（K#3/#5、U#2）：事件带 controller/generation，独立订阅
   与有界队列；discovery payload/address/RSSI 原样保留、显式 overflow。
   内核状态路由与用户态 adapter 路由均不能依赖当前全局 active id。
6. **动态 adapter / slctl**（U#6、U#1/#2）：枚举 Ready 与非 Ready 对象，
   显式选择 adapter，广播参数/数据和 scan 结果可见，添加/移除无需重启；
   daemon 与 CLI 同时运行不争抢破坏性事件队列。以普通用户完成上述全部步骤。

K#n 指 OpenSparklink/linux，U#n 指 OpenSparklink/sparklink。阶段内可以用
Virtual 验证路由、乱序/迟到完成、队列满与取消；软件 PASS 只能支撑对应
机制，北极星必须由两只真实硬件跑完。完整 S0–S6 的其他事项保持开放，
严格 CI 警告也保留修复任务，不为完成北极星删除未实现协议或放宽验收。

## 可复现运行记录

最终 harness 应使用与用户相同的 slctl/D-Bus 路径，保存每轮角色、随机
标识、提交/完成/发现的 monotonic 时间、实际 scan 原文及运行 exit status。
动态 adapter/广播/扫描命令和[物理控制/抓包佐证工具](WS73_PHYSICAL_TEST.md)已实现。
本机真实运行仍待设备与有效部署/板级证据；不能以软件 gate 替代硬件验收。

每次实机运行先做 inventory，确认两只物理 WS73 与 guest/controller
映射。保存 Linux/用户态 commit、dirty diff、config、kernel/initramfs、
QEMU/原生部署环境、固件/校准 hash、USB 前后 inventory、console/QMP、
去敏 USB/HCC/DLI capture、slkd/slctl 日志与测试结果。设备或工具不可见
时明确记为未验收，不能以旧四设备 boot 日志替代本轮无线证据。

里程碑完成后记录实际命令和所有证据链接，再检查每个关联 issue 的全部
原 checklist；仅部分 Runtime/HCC/广播链路完成不能提前关闭整项 issue。

## Runtime 第一阶段开发记录（2026-10-10）

内核工作树新增固定堆分配的 `ControllerRuntime`：Backend、连接、发现、
安全、SSAP、PHY/电源、RPA、command/pending、DLI ring 与 broadcast ring
均归该设备所有。选择只改索引，不再分配或搬移协议字段；detach 不需分配
占位状态。CommandWorker 遍历各 Runtime 的队列，RX 按设备路由，停止丢弃
非 active 设备的连接生命周期事件。per-fd 绑定保存注册 generation，read/poll
按绑定选择事件环；USB ingress 尚未携带 generation。

这只是迁移第一阶段。仍有 `SUBSYSTEM` 全局锁和临时 `Deref` 选择桥，
旧 ioctl 的选择/执行竞争窗口尚未消除；fd 尚未持稳定 Arc，worker 尚未
按设备独立，Ready/lifecycle/锁外取消仍需实现。不得据此宣称完整 Runtime、
拔插隔离或第一北极星已通过。

实测开发支撑：内核 image #7 构建成功；静态 C `-Wall -Wextra -Werror`
通过；verdict/lab 共 41 个测试通过。新增两虚拟设备的
`test_runtime_command_isolation` 通过：相同 ReadMacAddr opcode 的回复分别
匹配各自 MAC，提交/完成计数各自增长。它使用 QEMU model，不是真实 WS73
DLI 查询，也不是空口证据。

完整 guest 清单 96 项，summary 96 项、3 条失败断言、0 skip，guest exit 1、
strict verdict FAIL；失败为 `test_ioctl_throughput`、`test_dev_switch_isolation`、
`test_per_fd_device_select`，另有 printk 打断 case marker。迟到 ConnComplete
在已清理的 outgoing connection 之后被当作 incoming 的日志已留存，controller
handle/Host handle 的对应关系仍需核验。不能通过丢弃合法异设备事件、忽略
清理错误或删除断言通过门禁。证据保存在本地 `.dev/qemu-runtime-first/` 和
`.dev/kernel-runtime-first-evidence.json`，含源码/dirty diff、config、image、
initramfs、console/stderr 与构建日志 hash；全套失败记录保留。

该轮主机只读 inventory 发现 0 只 WS73，KVM 存在且可读写。硬件闭环未运行。
内核保持未提交，等待现有 QEMU 门禁通过；方案与 issues 持续更新。

### 显式 ioctl 身份路由的后续进展（同日）

RuntimeContext 已显式传入 25 个控制辅助函数；每次取 SUBSYSTEM 锁时，
同时验证注册 generation 并确定请求所属设备，不再依赖 ioctl 入口先切换、
解锁后执行的窗口。默认选择也按请求捕获身份；无设备控制请求返回 ENODEV。
registry 查询保留独立范围。此步骤仍使用全局锁和 Deref 桥，不等于最终的
Arc/per-Runtime lock/worker 架构；多步骤事务、USB generation 与取消仍待完成。

image #9 的双进程并发测试通过：两个绑定 fd 各执行 10,000 次 DEV_INFO，
每次索引和 MAC 都匹配。完整回归 96 项、1 条失败断言、0 skip、strict FAIL：
Runtime 0 收到 MAC report，submitted 2→3，但 resolved 0→0。该失败未被
放宽断言处理。带定向日志的 image #10 又在 test_ioctl_throughput 停住，
120 秒 QEMU timeout，suite 未完成，不能计入通过次数。USB completion
仍直接获取 sleeping mutex，是否导致这次停住尚未证实，需先迁移 IRQ 安全
RX 入队与每设备 worker，再继续核验 pending/late completion。

两轮原始记录分别为 `.dev/qemu-runtime-context-first/` 与
`.dev/qemu-runtime-context-timeout/`，对应同名 evidence JSON；后者另保存
精确源码/image/config hashes。定向日志已移除，后续继续正常构建；失败
记录完整保留。北极星与全部原 issues 仍未完成，内核提交门禁仍未通过。

### IRQ RX 与 worker 停止的后续进展（同日）

通用 DLI USB completion 的接收队列和 wakeup 引用改用短 raw spinlock，
保存/恢复 IRQ flags；解析与 payload 分配使用 GFP_ATOMIC，OOM 丢弃整包，
拒绝声明长度不足的广播 report。Bulk OUT completion 保留传输状态，不再
将发送缓冲交给 RX 解码。新增 RX ring/command-complete/MAC-complete/decode
分类丢失计数，损失不合成为成功 completion。

现有 EventPump/CommandWorker 新增 IRQ 安全 scheduling gate：stop 先拒绝
新调度和 self-rearm，再在锁外 flush_delayed_work，让 Rust trampoline 回收
队列持有的 Arc。模块 guard 先移除 wakeup 引用、drain worker，再释放状态和
关闭 backend；worker 分配失败传播初始化错误，完整状态发布后才启动 pump。
这仍是全局 worker 的过渡实现，尚非每设备 worker；内建配置下未执行模块
teardown，RT/lockdep/atomic-debug 与异步 TX completion 的独立测试也未完成。

最新 image #16 构建成功；静态 C -Wall -Wextra -Werror 通过，harness 41 测试
通过。完整双虚拟设备回归：96 项、3 条失败断言、0 skip、guest exit 1、strict
FAIL，仍有 printk 打断 case marker。失败为 test_ioctl_throughput、
test_dev_switch_isolation、test_per_fd_device_select；残留连接/迟到 ConnComplete
仍需修复。test_runtime_command_isolation 在该轮 PASS：2×10,000 归属查询和
两设备 MAC 回复/独立完成计数均匹配；早先失败仍保留，不能宣称稳定全套通过。

RX 记录两次损失：ring=2/command=0/MAC=0/decode=0，以及
ring=24/command=11/MAC=0/decode=0。这证明该轮有管理完成丢失，没有证明此前
MAC 失败的具体因果关系。后续优先推进每设备 Arc、RX/command queues、独立
worker/锁和真实 Host 事务/credit；不靠扩大缓存或忽略丢失完成验收。

最终原始记录为 `.dev/qemu-irq-ingress-final/`，对应
`.dev/kernel-irq-ingress-final-evidence.json`，保存 25 个源码 hash、dirty diff、
config/image/initramfs/console/stderr 与构建/验证日志 hash。旧三轮 IRQ 相关
日志分别留存，均只支撑虚拟开发；真实双 WS73、拔插和空口验收仍未完成。

命令单项验收另已收紧：先等旧 pending 清零且不新增 timeout、清空旧报告，
再要求每设备恰好 +1 submitted/+1 resolved、pending=0、timeout 不变及一次
匹配 MAC，排除旧命令增长使总计数误判。收紧后的 image #16 回归仍为 96 项、
3 条失败断言、0 skip、strict FAIL；该命令单项 PASS，RX 丢失为 ring=6、
command/MAC/decode=0。最终精确记录另存 `.dev/qemu-irq-exact/` 和
`.dev/kernel-irq-exact-evidence.json`；上述旧记录不覆盖。该轮不证明模块 drain、
RT/lockdep、异步 TX callback 的独立行为或任何实机闭环。

### 稳定 Arc、每设备锁/队列/worker 与虚拟拔插（同日）

协议状态改为堆分配 `ControllerState`，由稳定 `Arc<ControllerRuntime>` 和
该 Runtime 的协议 mutex 持有。fd 的显式绑定保留 Arc 与 immutable generation；
移除时拒绝新访问、排空 worker、取走状态，旧 fd 不能跟随复用的索引。
注册表只持 owner 引用和元数据，RuntimeContext 不再切换默认索引或持全局锁
执行协议 I/O；临时 Deref/DerefMut 桥与无设备占位协议状态均已移除。
默认 genl/debugfs 路径同样先捕获 owner，再获取设备锁。

每设备持独立堆分配 IRQ-safe RX ring（容量未扩大）、command/pending/broadcast
队列和两份 delayed work。WorkItem ID 0/1 区分 RX/TX，队列暂持 owner Arc，
不建立 owner/worker 引用循环。completion 在短 IRQ 路由锁下 clone owner，
进入该设备 RX 环并唤醒其 worker。停止 gate 阻止入队和 self-rearm，锁外 flush
两份工作；USB remove 先 quiesce Runtime，保持索引保留，再 join/free C URBs，
最后移除注册。初始化先发布 subsystem，再注册 USB driver，以支持已有设备
在 driver 注册过程中立即 probe。inline 与 worker 在同一设备协议锁下取事件，
避免 worker 预取旧事件后被 inline 路径超越。仍需完整 generation/cookie、
Host 事务/credit、异步故障与 PM 验证；C completion context 尚以数值 ID 表示。

image #20 无警告构建；静态 C -Wall -Wextra -Werror 通过。判定器 25、lab 16、
新生命周期判定器 9 项测试均通过（50 项）。完整双虚拟设备回归：96 项、
9 条失败断言、0 skip、strict FAIL。精确命令单项 PASS：两个 fd 各查询 10,000
次身份，恰好 +1 submitted/+1 resolved、pending=0、无新增 timeout、各自 MAC
匹配。新增断言验证 bound-fd 操作不改写 unbound fd 所见的默认设备。残留连接、
迟到 ConnComplete 与 handle 对应关系仍导致其他失败；不能忽略或删除断言。
该轮记录 sle0 ring=2、command/MAC/decode=0，不能据此宣称压力下不会丢失。
先前 Arc/全局 worker 版本的 10 条失败断言和 command-complete 丢失仍完整保留。

独立虚拟生命周期 gate 在同一个 guest 进程内先查询设备 0，再动态加入设备 1；
移除设备 0 后，旧 fd 返回 ENODEV，设备 1 地址不变且完成 MAC 事务；重新加入
设备 0、复用索引后，旧 fd 仍 ENODEV，新 fd 查询到新实例，设备 1 再次完成
事务。最终严格单项 PASS、guest exit 0，QMP 设备删除完成事件和 kernel log
均保留。第一次测试在 registration 已可见而 Runtime 尚未发布时绑定失败，
记录未覆盖；后续按异步 probe 语义在 10 秒内等待控制可用，必须再完成 DLI
往返，registry bit 不视作 Ready。这个单次虚拟结果不证明 slkd 动态对象、
真实 WS73、20 轮、四设备、无 sudo 应用或 late-URB/PM 故障矩阵。

完整记录为 `.dev/qemu-owner-workers/`、`.dev/kernel-owner-workers-evidence.json`；
前一版本为 `.dev/qemu-arc-runtime-first/` 与 `.dev/kernel-arc-runtime-evidence.json`。
生命周期记录为 `.dev/runtime-lifecycle-arc-first/`（失败）和
`.dev/runtime-lifecycle-arc-retry/`（PASS），各自 manifest 绑定源码/dirty diff、
config/image/QEMU/busybox/initramfs hash、exact argv、console/stderr/QMP。
本地 `.dev/kernel-owner-stack-constructors.log` 记录 image #20 的
ControllerState::new_boxed / inline drain 栈预留分别为 0x7b0 / 0x88，
不作为整个调用链的栈安全证明。内核完整门禁仍 FAIL，保持未提交；整项 issues
和全部北极星 checklist 仍开放。

可复现虚拟拔插命令（从 Linux 源码根运行，KBUILD/QEMU/BUSYBOX 需指定本地
构建产物；输出目录必须尚不存在，LIBRARY_PATH 仅本机静态链接环境需要）：

```sh
LIBRARY_PATH=../.dev/tools/qemu-deps/root/usr/lib64 \
python3 tools/testing/selftests/sparklink/run_runtime_lifecycle.py \
  --kernel-build ../.dev/kernel \
  --qemu tools/testing/selftests/sparklink/qemu-sle-dli/bin/bin/qemu-system-x86_64 \
  --busybox ../.dev/tools/qemu-deps/root/usr/bin/busybox \
  --output ../.dev/runtime-lifecycle-new-run
```

该 runner 只创建 QEMU 标准 DLI 虚拟设备，不接管主机 USB；guest 测试使用
开发 root 环境，不能据此完成应用无需 sudo 的验收。


## USB registration generation / 标准 DLI credit 开发记录（2026-10-10）

USB IN URB context 现在在 submit 前固定 `{registration_id, generation}`；
Rust callback 在 IRQ 路由锁下按完整 identity 获取 owner Arc，并将同一个
owner 传入解码/入队。旧 opaque 数值 context 不再路由 RX，inline drain
也匹配完整 identity。移除关闭 scheduling gate 后拒绝入队。此源码机制
尚未由专门的迟到 callback/地址复用故障注入证明，不能宣称完整 cookie/PM
矩阵通过。

probe 不再把 attach 失败替换成占位 MAX id，也不忽略 controller/listener
启动失败；错误路径 quiesce owner、join/free C URBs、撤销注册，然后返回
错误。Reset、版本、MAC 初始化逐条检查 event/opcode/length/status；全部
成功且 MAC 非零后才保存元数据。boot 注册和查询成功仍不等同于完整 Ready；
能力、WS73 dialect 和 Host 状态发布待完成。

本地 T/XS 10003-2025 §9.1.1/9.1.2 要求 Status/Complete 的 opcode 后有
1 字节可用指令数量；先前标准 USB parser 与 QEMU fixture 同时漏掉该字段，
Status 还使用旧的 status-first 排列。现修正为 opcode/credit/status，版本
查询按 §8.1.4 返回 1+2+2 共 5 字节；legacy u32 版本元数据仅投影前 4 字节，
不冒称完整 tuple。旧 QEMU 运行仍保留为当时 fixture 的证据，不能据此宣称
完整标准 DLI/credit 符合性；此修正不推定 WS73 vendor dialect 使用同一格式。

credit 按 controller 宣告的绝对数量更新，不累加；opcode=0 的更新不解析为
本地事务结果；成功 CommandStatus 只接受异步工作，不提前 resolve。原始
DLI 队列为零 credit 时停发，由 RX 更新后唤醒。同步 bootstrap 暂无 credit
等待器：Reset/版本后 credit=0 时以 EAGAIN 失败撤销 probe，不继续偷发下一条
查询；最后 MAC 后的 credit 可为零并传入 Runtime。直接广播/扫描/连接等路径
仍绕过统一调度，异步 terminal correlation、超时后排队命令取消、每事务
cookie 与恢复未完成。没有零 credit/unsolicited grant 的独立故障测试，不能
据此关闭 K#1/#16/#17 或宣称完整 Host 流控。

image #25 编译成功但启动在 ControllerState::new_boxed 栈溢出 double fault，
suite 未开始，strict FAIL。反汇编定位 64 槽 CmdRequestQueue 的大栈临时变量；
仅修改 DLI 环的 #26 仍预留 0x4560，未运行 guest。pending/request/broadcast/DLI
数组均改为显式原位初始化后，#27 构造函数预留为 0x7c0（另有寄存器保存）。
这不是整个调用链栈安全证明。#27 编译成功、匹配的新 QEMU 已重新构建；
完整双虚拟设备回归：96 项、10 条失败断言、0 skip、strict FAIL。精确命令
单项 FAIL：旧 pending=2/0 未清零；安全原始命令九条 EBUSY。日志记录 sle0
ring=37、command-complete=23、MAC=0、decode=0，证明管理回复丢失，但尚未
证明每条失败的完整因果链。全部失败保留，不扩大 ring、忽略 timeout、放宽
统计断言或把直接发送的 Bulk 成功当作事务完成来通过测试。

同一 image #27 和新标准 fixture 的独立虚拟单次生命周期 gate PASS、guest
exit=0：动态增加第二设备，移除第一设备后旧 fd ENODEV，第二设备继续 MAC
事务；复用第一索引后旧 fd 仍 ENODEV，新 fd 查询新 MAC，第二设备再次查询。
这是普通 QEMU 模型，不能替代真实 WS73/RF、slkd/no-sudo、20 轮、四设备，
也不能证明尚未注入的 stale-callback/零 credit/fault/PM 情形。

本地记录：`.dev/qemu-usb-credit-stack-failure/` 和
`.dev/kernel-usb-credit-evidence.json` 保存启动失败；
`.dev/qemu-usb-generation-credit/`、`.dev/kernel-usb-credit-final-evidence.json`
保存最终完整回归；`.dev/runtime-lifecycle-usb-generation-credit/manifest.json`
保存独立生命周期及 QMP。两份 source-snapshot 保留各次源码/dirty diff；
manifest 绑定 kernel/config/QEMU/initramfs 与日志 hash。
`.dev/kernel-usb-credit-stack-constructors.log` 保存最终构造函数反汇编。
主机只读 inventory `.dev/usb-credit-host-inventory.json`（2026-10-09T18:59:24Z）
仍为 0 只 WS73，KVM 可读写；未开展本轮 RF。内核完整门禁仍 FAIL，保持未提交，
整项 issues 和全部真实北极星 checklist 保持开放。下一步统一每设备 Host 的
直接/排队命令发送与 credit、事务归属，随后继续 WS73 HCC/BSLE/真实 DLI。


## 统一 USB command Host 与 pending 修复（2026-10-10）

Runtime 新增 IRQ-safe `CommandHost`，64 槽队列、绝对 credit、单个在途命令
及独立匹配回复槽均属于同一 registration owner。runtime USB 的 typed 与
raw 命令共用调度；只有 TX worker 在保留 owner 后调用实际 bulk OUT。
匹配回复保留到协议消费者取走后才释放在途槽，不因普通 discovery/data
ring 满而被丢弃。raw 回复按发出时捕获的 sequence 解析，internal/unmatched
回复不消费 raw pending。同步 bootstrap 三查询仍为 C 初始化路径，不据此
宣称所有 bootstrap/driver/profile 已统一到完整 Host。

满队列返回 EBUSY；入队失败回滚 raw pending/count，Host queue 拒绝超长输入。
待发送的已取消/过期 raw entry 不再发到设备。回复等待和排队有界，传输错误
或超时 latch 该 Host fault、停发和清理其队列，不补造 credits；完整 Fault
状态发布/恢复、PM、完整 raw ioctl schema 验证与错误码保真待完成。
单在途策略比 controller 可宣告的
多条窗口保守，不宣称已实现多在途吞吐和乱序 terminal correlation。

每个广播/扫描 enable/disable 记录内部 cookie 和 enable 意图；disable
或被新请求替代的 enable 回复不确认新的 pending start。停止命令的入队
错误不再忽略，也不把入队失败伪装为本地已停止。实际 disable 确认、完整
参数/data 配置、异步请求返回与事件 ABI仍待补全。成功 CommandStatus 仅
接受工作，后续 domain terminal 尚未全部关联；不能关闭 K#1/#2/#16/#17。

IRQ completion 的立即 RX kick 使用 mod_delayed_work，提前已有的长定时
工作；非零 heartbeat 不推迟已有 kick。借助 Rust RawWorkItem::__enqueue
转交引用：新排队才交出新的 Arc，已有 pending 保留原队列 Arc 并回收多余
输入引用。stop gate 与调度互斥，工作不使用 disable，锁外 flush 仍通过
Rust trampoline 回收引用。仍只有每设备 RX/TX 两份 work；中途 #29 的分离
maintenance 方案只构建，未跑 guest，最终源码不采用它。RT/lockdep、完整
引用回收故障矩阵及高压力晚回调尚未验收。

突发测试暴露 `CmdPendingEntry` 的逻辑错误：pending sentinel=u32::MAX，
旧 is_resolved 仅检测最高位，把 pending 也算作完成；GC 会删掉仍等待的
entry，计数却继续 pending。现排除 sentinel，并避免 tail 覆盖其他 live
slot。旧 #31 两设备均只收 1 个 internal Reset，MAC=0、pending=13、submitted
+13、resolved +0、timeout +0，在 4 秒截止严格失败。相同测试在修正后的
#32 和最终 #33 均通过，失败目录完整保留，不以重试覆盖。

最终 #33 无警告构建，构造函数栈预留保持 0x7c0（非全调用链证明）。
新的 guest 测试同时用两个子进程、各自绑定 fd，混合一个 internal Reset、
一个 raw Reset 和 12 条相同 MAC opcode；逐条核验各自地址及 2 条 Reset
回复，raw submitted/resolved 恰好各 +13、pending=0、无新增 timeout。
两设备均 PASS，随后旧 fd ENODEV、另一设备继续查询、重插索引复用与新 fd
查询通过，整体 VIRTUAL_RUNTIME_LIFECYCLE PASS、guest exit=0。测试仍为
QEMU 标准模型，不能证明真实 WS73/RF、slkd/no-sudo、20 轮、四设备，或专门
零 credit/迟到 callback/fault/PM 场景。

完整 #33 回归：96 项、21 条失败断言、0 skip、strict FAIL；精确命令归属
单项 PASS（2×10,000 身份查询、各自匹配 MAC、精确 +1 submitted/+1 resolved、
pending=0、无新增 timeout）。残留连接、异步 terminal 和压力/背压相关失败
仍存在；后续日志有 9 个 raw pending 超时，不能作为成功完成。仍有 printk
打断 marker，按严格判定保持失败。正常未知 ioctl 已改为 debug 日志，errno
不变；没有隐藏真实 kernel fault、删除断言或放宽判定。未知 DLI reply opcode
不再被归并到 VendorBase，短 bulk OUT 也不再返回成功；这些错误分支尚未完成
专门注入验证。verdict/lab/lifecycle verifier 共 25+16+14=55 项通过；新 guest
C 程序在 runner 内以静态链接、-Wall -Wextra -Werror 编译通过。

本地最终证据：`.dev/qemu-usb-host-final/`、
`.dev/kernel-usb-host-final-evidence.json`、
`.dev/runtime-lifecycle-usb-host-final/manifest.json`，
`.dev/usb-host-final-source-snapshot/`。最终完整 run 目录另冻结 image #33、
config 与 QEMU binary，manifest 绑定来源/dirty diff、原始 logs、initramfs
和每份文件 hash。旧 #28、#30、#32 完整失败分别在
`qemu-usb-host-first/`、`qemu-usb-host-wakeup/`、`qemu-usb-host-pending/`；
#31 突发失败在 `runtime-lifecycle-usb-host-{bursts,burst-counts}/`，
#30 原单次 gate 与 #32 新突发 gate 也分别保留。
内核完整门禁未通过，保持未提交；整项 issues/北极星验收保持开放。
下一步补全广播/扫描确认与参数/data 事务、Ready/fault 和 WS73 HCC/BSLE
接口，继续真实 DLI 纵向路径，完整方案原范围保留。


## WS73 原生 HCC/BSLE 启动实现（2026-10-10）

内核工作树新增独立实现的 `drivers/sparklink/ws73/wire.{c,h}` 与
`bsle.{c,h}`，从本地 SDK 的 `hcc_usb_host.h`、`hcc_comm.h`、
`customize_bsle_ext.h` 核对封装事实，以 libws73-usb 作者的 wire 观察作
额外参考；作者 capture 不作为本项目实机证据。USB TX package/descriptor、
queue switch/reset、queue-9 PM 和 queue-10 BSLE customize 均由本项目编码。
800 字节 customize allocation 的 TX pay_len 是明确的 vendor 行为，不用于
解释设备 RX 的 payload length。没有复制 SDK 或 LGPL 的实现代码。

五端点 runtime probe 现在启动每接口自己的 worker，buffers、TX sequence
和启动 phase 归该 USB instance 所有，没有参考实现的全局 TX 序号。流程为
BSP_READY → PM/BSLE 配置 → CUSTOMIZE_RECEIVED → class SLE_OPEN(ordinal 29)
→ BOOT_FINISH，各等待阶段使用独立 10 秒 monotonic deadline；持续无关流量
不延长截止时间，panic、短写、传输错误和 disconnect 中止该实例。
DEVICE_ACTION_STATUS(SLE_OPEN) 不代替 BOOT_FINISH；提前收到的 boot reply
不保存给尚未发出的 open。disconnect 阻止新 I/O，在释放 buffer 前 join
两个 bounded 同步 worker。完整异步 URB streaming、reference/fault/PM
矩阵和自动恢复仍待实现。

RX 只接受当前 SDK 的 92 字节 aggregate header 和最多 24 个 slot，先验证
全包 declared length、所有 slot 边界及 HCC 长度，才交给消费者。只读每个
slot 前端的 netbuf，忽略 padding 内像帧头的旧数据；没有盲扫或未核验的
raw-netbuf fallback。BSLE status 的 tag length、type 和 message 分别核对。
这已实现有界原生启动路径，尚未与 Rust ControllerRuntime 的 native
Backend/Host 注册和事件流衔接。

启动还要求部署提供 `sparklink/ws73/bsle_custom.bin` 原始 140 字节和
`pm_config.bin` 原始 4 字节，来自对应 board/SDK 或注明来源的 vendor
配置；驱动不猜默认校准/功率值。两份文件均验证大小并在 I/O 前记录 SHA256。
缺失/错误则该实例 Failed，不发布 Ready。本地 SDK 有
`build/config/ws73_cfg_default.ini`，但尚未导出并核验适配本硬件的两份 raw
payload；仅长度正确不证明 RF 校准正确。lab `pack --runtime-config-dir`
支持显式输入，按实际归档字节独立记录 source、大小和 hash。没有提交固件。

`boot_stage` 可观察完整握手阶段，完成为 `sle-awaiting-dli`，仍非 Ready。
新 `runtime_transport` 仅表示五端点 descriptor 验证/绑定；原 boot-only
harness 用它计数，避免把正在握手和最终 Ready 混为一谈。boot PASS 可以与
后续 BSLE Failed 同时存在，必须另看 phase、errno 和 kernel log；该 gate
不验收 SLE、DLI、RF。双端真实 DLI 查询仍是 Ready 的必备后续条件。

`ws73_bsle_test.c` 直接编译生产 codec/sequencer，3,198 条检查 PASS；输入
均合成，不能部署为 calibration。覆盖 padding 伪帧、坏后续 slot 导致整包
不推进握手、错误 ack 顺序、action-only、持续流量超时、panic、send/open
失败、断连及另一独立实例。GCC -Wall -Wextra -Werror、kselftest Makefile
目标通过；同一源码的 Clang ASan/UBSan/LSan 主机执行 PASS，不代表内核
sanitizer 验收。初次 GCC sanitizer 链接缺系统 runtime、隔离器 ptrace
使 LSan 停止的记录保留，随后用已安装的 Clang runtime 在主机通过。
verdict/lab/lifecycle 共 57 项 PASS；pack fixture 初次缺 parent 的测试错误
已修正，旧失败保留。三个 driver C 文件 checkpatch 为 0 error/0 warning。

image #34 无警告构建，独立双虚拟 Runtime gate PASS；完整回归在第 95 个
case 的 ioctl fuzz 因原 `ioctl_inject_conn_data` 对空 slice 访问 raw[0]
触发 panic，未产生完整 summary，strict FAIL。已归档该源码、binary 和
console。现入口在 handle lookup/TCID/SSAP 处理前拒绝空帧及超长输入，
超长不再截断；添加有效连接上的两条回归断言，不删除原 fuzz。

最终 image #35 无警告构建；新增两条断言、connection data case、ioctl
fuzz 和精确 command isolation case PASS，未再观察到该 panic。独立
双虚拟 Runtime 混合命令/13 条 raw 归属及单次拔插/索引复用再次 PASS。
完整 suite 96 项、24 条失败断言、strict FAIL：残留连接、迟到完成和
压力下状态转换仍未解决，且 printk 仍会打断 marker。summary 的 skipped=0
仅为当前 suite 字段；日志中两条 need 3+ controllers 的子路径没有执行，
不把它们计作完整分支覆盖。此标准 DLI fixture 不模拟原生 WS73 HCC/BSLE。

最终证据 `.dev/ws73-bsle-codec-evidence.json`、
`kernel-ws73-bsle-{,bounds-}evidence.json`、
`qemu-ws73-bsle-{panic,bounds}/`、
`runtime-lifecycle-ws73-bsle{,-bounds}/manifest.json` 和两份 source-snapshot
均保留；完整 run 冻结各自 image/config/QEMU binary，绑定 raw logs、
initramfs、源码/dirty diff 与文件 hashes。内核复现说明在
`Documentation/networking/ws73-development.rst`。

### 每设备初始化锁和撤销注册竞争（合成支撑进展）

Linux 原生 WS73 注册改为持有独立 transport 引用，在每设备 lifecycle mutex
下调用 `open()`，期间释放 Runtime 协议状态锁。SETUP 快照可查询；打开成功
前租约返回 `EAGAIN`，不消耗租约计数，也不允许无租约 raw send。成功打开
仅建立传输条件，不据此宣称 Ready。slkd 现有按 adapter 的注册协调会重试
未完成的租约获取；本批未修改其 Rust 实现。

注销先关闭 admission，再等待初始化结束。迟到成功只能进入清理路径并
关闭一次，失败自行清理部分资源；注册失败按旧 generation 撤销，不能
移除复用 index 的新设备。原生启动不重新发布已退役 owner。

新增 guest 内外部模块夹具及 C 测试：成功、EIO、打开中注销后成功、打开中
注销后 EIO 四路径，十次 EAGAIN/no-send、完整 SETUP 元数据、index 预留、
同 index 复用时旧 fd/旧注销身份、精确 get/put/close、幸存模型实际 DLI
查询及模块卸载均通过。最终 #74 四次快照0.002/0.001/0.001/0.002ms；旧#71使用相同 guest
可执行文件和 byte-identical 夹具 C object 阻塞10065.533ms并失败。模块
release 元数据按旧内核单独编译，未强制加载不匹配模块。

267 kernel harness / 四路径夹具 / 十二传输和生命周期回归通过；原96项
1058OK/0FAIL/0SKIP/3既存WARN通过。新内核普通应用合成20+2轮、同 slkd、
TX-off、重插、幸存设备、独立捕获和 C/Python 权限门禁通过。用户态 Rust
源码和实际程序 hash 不变，未新增 Rust tests/clippy、远端CI或32位验证。

复现入口为内核 `run_native_open_test.py`，详见内核开发文档；夹具只在
隔离 guest 中加载，不是产品传输驱动。本地
`.dev/native-open-final-evidence.json` 保存最终源文件、编译输入、内核、
模块、guest、capture 和旧反例 hash；早期#73及修正记录保留。真实硬件
入口仍未得到两只 WS73，真实七项0/7、board NOT_ASSERTED。真实空口、四
设备两组、完整 S0–S6 及每个原 issue 的剩余验收继续保留，整项不提前关闭。

### 初始化未结束时通知旧订阅退役（合成支撑进展）

Runtime 注销在关闭 admission 后，等待 native open/清理之前立即唤醒
controller-event 和 snoop 订阅，保留清理结束后的通知。旧订阅因此可在
初始化仍等待驱动返回时得知自身已经退役。

测试在注销前给同一 owner 两个独立 fd 建立 event/snoop 订阅并注册到
edge-triggered epoll，确认 ready list 为空。注销后仅等待原 epoll，不重加
或重新注册 interest；两种身份各收到精确 ERR|HUP，200ms 内完成，同时
open 仍阻塞、close/put 均0、index 仍预留，然后继续原有迟到成功/EIO、
资源计数、旧 fd/新 generation、幸存设备和模块卸载验收。

#75 两种打开中注销场景分别3.009/3.083ms唤醒。相同 guest 程序与
byte-identical 夹具 C object 在#74阻塞201.909ms并FAIL；负例主动释放并
join 后模块卸载成功，旧 release 元数据使用匹配模块，未强制加载。
四新增verdict使 kernel harness 达271；四种 open 路径、十二原传输/
生命周期门禁通过，原96项1059OK/0FAIL/0SKIP/3既存WARN通过。

新内核普通应用合成20+2轮/同 slkd/bus/owner、TX-off、幸存设备、重插、
capture及 C/Python 权限门禁通过；独立 Host 重算和 guest 佐证一致。
用户态 Rust 源码/实际程序和 QEMU 实际编译输入未变，未新增 Rust
tests/clippy、远端CI或32位运行验证。最终源码、编译输入、guest/module/
capture及旧反例 hash 位于本地 `.dev/open-wake-final-evidence.json`。
真实入口仍无 WS73：七项0/7、board NOT_ASSERTED；两只真实设备闭环仍
优先，随后四设备两组，完整 S0–S6 和各原整项 issue 继续保留开放。

2026-10-09T19:50:32Z 主机只读 inventory：WS73=[]，KVM 可读写。本轮没有
真实 USB、BSLE、DLI 或 RF 验收；slkd/no-sudo、20 轮和四设备仍未完成。
下一步导出并核验 SDK 板级配置、接入原生 DLI 查询与 Runtime 生命周期，
再补广播/扫描完整事务和动态 adapter；保留用户指定纵向依赖顺序。内核
完整 QEMU 门禁未过，保持未提交；全部原 issues 和七项北极星验收保持开放。

## 原生 WS73 查询与配置候选记录（2026-10-10）

SDK 配置导出工具已签名提交并推送：
[`91999ed`](https://github.com/OpenSparklink/sparklink/commit/91999edbb5c381449b2da0efae9ecf51aef72a1d)。
`tools/ws73-board-config.py` 要求显式 INI、board 来源和 USB link-check 编译开关；
输出原始 140 字节 BSLE 与 4 字节 PM payload 及 source/exporter/配置/hash manifest。
选中配置缺失、重复、越界、启用未知 per-device flash/MAC、或已有输出目录则拒绝；
没有用默认值补齐校准。18 项测试通过，从实际 SDK INI 导出并打包后逐字节回读相等。
使用方法和限制见 [WS73_BOARD_CONFIGURATION.md](WS73_BOARD_CONFIGURATION.md)。
当前默认 SDK 的 PM 是 `0x215`（GPIO 10），与参考 dongle 的 `0x1` 不同；
仍是未验证板级候选，不代表这批硬件的 PM、功率和 RF 校准已合格。没有提交 blobs，
没有用这份候选执行 USB/RF 测试。

内核工作树新增原生 `ws73/dli.c`：BSLE 成功后用该实例 buffer/sequence 选择
SLE queue 8，依次查询版本 `0x0404`（5 字节）、缓存 `0x0402`（6 字节）、
80 位特性 `0x0403`（10 字节）、带 `address_type=0` 的地址 `0x0406`（6 字节）。
最后一条来自 T/XS 10003-2025 §8.1.6，**WS73 固件是否支持仍需实机验证**；
不支持时直接失败，不借用缓存或合成地址。没有把 WS73 SetEventMask 的 `0x0401`
当标准 ReadCmdLen 发出，也不宣称完整长度协商。fresh BSLE 后仅提供首个 probe slot；
后续绝对 credit 只来自校验过的回复，零窗口等待真实 grant，不自动重发不确定事务。

CmdStatus 成功不代替 CmdComplete；匹配 opcode、完整 aggregate 边界及精确返回长度，
opcode-zero 仅更新 credit。保留未知 controller status 原值；失败、panic、断连、
迟到完成和 10 秒 monotonic 超时终止该实例。四次查询的候选元数据全部有效才一次性发布，
检查 buffer 长度/count、拒绝全零/全 FF 地址。`metadata_valid` 与
`controller_information` 可读，阶段完成为 `dli-awaiting-runtime`。
**仍没有注册 native Rust Runtime 或发布 Ready**，异步 RX/Host/lifecycle 接入继续作为
下一项依赖；真实双设备 Ready 和广播/发现均未验收。

`ws73_dli_test.c` 直接编译生产 codec/query，2,830 项合成检查通过；
BSLE 回归 3,198 项通过。覆盖零/final-zero credit、无关事件、先 Status 后 Complete、
错 opcode、原始失败状态、坏长度/重复回复、send error、断连、panic、无效地址/容量、
持续等待及迟到完成，并核对另一独立实例不变。GCC 严格警告、kselftest Makefile
目标、Clang ASan/UBSan/LSan 主机执行均通过；三个 C 文件 checkpatch 0 error/0 warning。
这些检查没有执行物理 USB，也没有启用内核 sanitizer。

最终 image #36 无警告构建；独立双虚拟 Runtime 混合命令/归属/拔插/索引复用 PASS。
完整标准 DLI QEMU 回归 96 项、19 条失败断言、strict FAIL：事件等待、高频连接和
角色/扫描切换仍有失败；不能把与上一轮的计数差异当修复证据。summary skipped=0
仍不表示所有子路径覆盖，日志中两条 need 3+ controllers 子路径未执行。
未观察到 kernel panic/warning，但这不代替完整门禁。此 QEMU 模型不模拟 WS73
vendor USB/HCC/BSLE，不能证明原生查询在硬件成功。

本地证据 `.dev/kernel-ws73-native-query-evidence.json`、
`ws73-native-query-source-snapshot/`（45 个修改/新增源文件及 tracked diff）、
`qemu-ws73-native-query/`（冻结 image/config/QEMU binary、实际测试 binary、
initramfs、完整 console）、`runtime-lifecycle-ws73-native-query/manifest.json`，
以及配置 candidate/归档 roundtrip 均保留并绑定 SHA256。
2026-10-09T20:16Z 附近主机只读 inventory 仍为 `WS73=[]`；未做真实 DLI 或 RF。
内核完整 QEMU 提交门禁未过，工作树保留未提交；工具与进度文档持续签名提交推送。
所有原 issues 与七项北极星验收继续开放，不提前关闭整项 issue。

## 原生 WS73 Runtime 接入记录（2026-10-10，部分成果）

内核工作树新增内部 Native 注册接口，显式选择 WS73 HCC profile；C/Rust
元数据布局为 32 字节，保留五字节版本与完整 80-bit features。注册时仅创建
SETUP 对象；独立 Runtime/Host、id/generation、credit 和查询结果不借用其他
设备的状态，也不改变它的默认选择。C context 与模块引用一直保留到 owner
撤销并排空 callback/worker 后，旧 fd 不跟随复用索引。

WS73 完成 bootstrap 后启用每实例 bulk/notification RX URB。Host 在 TX worker
串行发送查询，成功 Status 仅表示接受，继续等对应 Complete；credit-only
事件不能完成查询。未知非零 status 原字节保留，不归一成成功。原生查询白名单
在占用 pending/credit 前拒绝不支持的命令，`0x0401` 不误作 ReadCmdLen。
畸形 HCC、USB 错误与硬件错误在 work context 撤销该实例，不能在 USB callback
中同步注销。未知合法业务事件当前只计数，尚未提供完整诊断保留和 discovery
解码；完整广播/扫描事务、自动恢复和 PM 矩阵均未完成。

新增独立 `usb-ws73-test` 合成 QEMU 模型运行生产 WS73 driver 的 HCC/BSLE/
DLI/异步 URB 路径；它使用假元数据与不可部署的配置，不执行真实 ROM/固件，
没有 RF medium。冻结 image #40 无警告构建，52 个修改/新增源码和全部输入
hash 在测试前后保持一致。最终三条独立 gate 均 PASS、guest exit 0：

- 原生双设备各 18 次实际模型 DLI 往返，验证完整 version/features、精确 pending
  增量和无新增 timeout；status `0xfe` 原样保留，拒绝方言误用。A 移除后旧 fd
  ENODEV，B 保持 generation 并继续查询；A 重加使用新 generation。
- A 收到畸形 HCC 聚合包后以 EPROTO 撤销，旧 fd 失效，B 保持 generation 并
  完成查询；物理模型移除/重加 A 后，新 fd 可查询且旧 fd 仍失效。
- 标准 DLI 双虚拟 Runtime 的独立 Host burst 与拔插/索引复用通过。

verdict/lab 的 78 项 Python 测试通过，C harness 静态编译使用
`-Wall -Wextra -Werror`。完整标准 DLI 回归仍为 96 项、21 条失败断言、strict
FAIL，集中在异步事件等待、扫描/广播切换和连接清理；summary skipped=0
不能代表两条要求 3+ controllers 的子路径已覆盖。日志没有 kernel fault。
不能用上述三条单项 PASS 替代完整门禁或真实北极星。

最终证据 `.dev/kernel-native-runtime-final-evidence.json`、
`native-runtime-final-source-snapshot/`、`qemu-native-runtime-final/`，以及
`runtime-lifecycle-native-{final-v2,fault-final-v2,standard-final-v2}/manifest.json`
保存源码/构建/实际 guest binary/initramfs/console/QMP 与 SHA256。早期故障注入
因模型在改坏包头前唤醒接收端而失败，修正构包/唤醒顺序后重测，未削弱驱动
校验。一次中间测试与重链接重叠，实际加载 #38，已明确排除为最终源码证据。
归档 QEMU 失去 BIOS 相对路径导致的启动失败也保留；最终运行用原构建位置的
哈希相同二进制，冻结源码与镜像没有变化。

本轮只读 inventory 仍为 `WS73=[]`；SDK 板级配置候选仍未合格。没有真实 DLI、
Ready、slkd 动态 adapter、普通用户 slctl 或空口结果，七项北极星验收全部未完成。
内核受“QEMU 自测通过后才能提交”的现有门禁约束，完整回归通过前保留工作树；
进度文档签名提交并推送，issues 继续开放。下一步核验回归中的异步事务/清理，
并继续板级核验/真实查询 → 广播扫描 → 事件 → 动态 adapter/slctl。

### 异步事务清理与首次内核交付（2026-10-10）

已签名提交并推送 [7918bb9757bf](https://github.com/OpenSparklink/linux/commit/7918bb9757bfe3c365521b66d30ffee4f1e3d0c6)，
开发分支 `codex/sparklink-ws73-runtime`，可审阅 [Draft PR #20](https://github.com/OpenSparklink/linux/pull/20)。
测试前冻结的 53 个源码 hash 与该提交逐一匹配；内核工作树干净，未合入 master。

后续修复保留 outgoing connection 条目与控制器实际 handle，等待 Disconnected
才删除；建立完成前的 disconnect 延后到获知 handle 时发送，迟到建立事件不能
据此制造新 incoming。失败的 typed CreateConnection 关联 Host 捕获的 peer，
清理对应未建立条目。该步骤只处理最小建立/断开归属，不宣称完整 data/control
handle 映射、domain transaction FSM 或连接/安全矩阵已完成。

测试原先忽略 1000 轮启停的 ioctl 错误，现每轮必须收到真正的 enable/disable
Complete；stale-handle、连接清理与压力测试也等待实际断开，错误/超时仍 FAIL。
不能把 enqueue 成功当作完成。三设备子路径的条件不满足现记显式 SKIP。
串口静默仅隔离 case marker，全部 printk 仍留在 kernel ring；verdict 必须收到
完整 ring dump 与早期记录，并继续拒绝其中的 WARNING/BUG/panic。

最终冻结 image #42 无警告构建，使用三个标准 DLI QEMU controller，原 96 case
清单全部执行：0 failed assertions、0 skips、guest exit 0、strict PASS。1000 轮
广播启停、200 轮连接/断开和 30 轮角色切换均通过。**旧 air-medium 案例仍有
4 条 WARN，跨设备连接/数据断言不够严格；全套 harness PASS 不证明该链路成功。**
它们保留在 K#19 的后续测试工作中，不据此认定 RF 或连接实现完成。
WS73 生产驱动的合成双设备查询/拔插、畸形 HCC 单设备撤销、标准 Runtime 生命周期
三条独立 gate 均 PASS，输入与源码 hash 前后不变；Python harness 80 项 PASS，
静态 C `-Wall -Wextra -Werror` 通过。

本地最终证据 `.dev/kernel-runtime-submit-evidence.json`、
`runtime-submit-source-snapshot/`、`qemu-runtime-submit/` 与
`runtime-lifecycle-submit-{native,native-fault,standard}/manifest.json` 保留来源、
实际测试 binary、image/config/initramfs、全部 console/QMP 和 hash。六个选定函数
栈 prologue 归档不视为完整调用链安全证明。#41 的 120 秒超时/99 条失败记录、
#42 第一轮的 1 FAIL/1 SKIP，以及此前全部失败均保留，没有放宽断言或覆盖失败。

第一北极星七项验收仍全部未完成；真实 WS73 清点仍为空，SDK 板级候选未合格。
Native Runtime 仍仅 SETUP，没有真实 Ready、广播/扫描、空口数据、slkd 动态 adapter
或普通用户 slctl 结果。全部原 issues 与 S0–S6 保持开放，Draft PR 不带自动关闭词。

### WS73 发现方言准备（2026-10-10，部分成果）

[cef9dc445968](https://github.com/OpenSparklink/linux/commit/cef9dc4459686ab44db89b38f7c8a58ea58bac99)
把原生命令校验迁入被引用保留的 driver ops，核心在分配 pending/credit 前及
实际传输前调用。WS73 Runtime 仍只允许四项元数据查询；正确编码的扫描命令
也返回 EOPNOTSUPP，等待发现事务及事件通路接齐。raw DLI ioctl 的声明参数
超过 240 字节现返回 EINVAL，消除原先静默截短行为。

独立实现生产 `discovery.c/h`，按 `libws73-usb@f4d85d0`、
`communication_nearlink_service@f0872df` 和 T/XS 10003-2025 8.2/8.3/9.1.19
核对协议事实，没有复制参考实现代码。厂商差异保留在 WS73 profile：

| 内容 | WS73 profile | 限制 |
| --- | --- | --- |
| 广播参数 `0x0c02` | 固定 49 字节结构 | 当前只检查长度；参数能力由控制器确认，完整参数 builder/事务待实现 |
| 完整广播数据 `0x0c03` | `[handle, operation=3, length, payload]`，三字节头 | 标准/完整 Host 使用四字节头；编码器最多 251 字节数据，旧 raw ioctl 不能承载最大长度 |
| 查询回复 `0x0c04` | 参考共享三字节数据格式 | 本机未独立实机核验；不能把参考实现的假设写成验收 |
| 广播使能 `0x0c05` | 五字节，含 handle、LE16 duration 和 max events | 不使用旧标准虚拟 Backend 的单字节快捷格式 |
| 扫描参数 `0x1001` | 八字节、frame type 1 单配置 | 多帧类型明确拒绝，不像参考实现那样只取第一个 PHY |
| 扫描使能 `0x1002` | enable、filter duplicates 两字节 | 尚未开放原生 Runtime 支持 |
| 发现报告 `0x180b` | 23 字节参数头 + 声明数据；最多 278 字节参数 | 标准事件号 `0x001a`、22 字节头；不能套用标准布局 |

新编码器不补入功率、地址或时间默认值。报告 decoder 完整保留 header，包括
地址类型、定向地址、PHY 和 offset 20 的未解释厂商字节，读取 offset 21 的
有符号 RSSI；长度必须精确，短包/尾随字节失败且输出不变。借用视图只在
输入存活期间有效，未做分片重组、字段归一化或发现等级推断。decoder 尚未
接入原生 RX 和用户事件 ABI：现有 260 字节 slot 上限和旧事件参数缓冲不足以
容纳全部合法报告，需要显式扩展后才能开放扫描，不能截短后宣称发现成功。

新增纯内存合成测试：38,293 项协议检查与 ASan/UBSan/LSan PASS，覆盖手工
marker/control/report 向量、所有数据/报告长度、RSSI 全字节域、错误输出不变
及生产 HCC 编帧。元数据查询 3,097 项、BSLE 3,198 项、Python harness 80 项
PASS。image #43 无警告构建；原生双实例查询/拔插、畸形 HCC 单实例隔离和
标准 Runtime 生命周期三 gate PASS，完整标准三控制器 96 case/0 FAIL/0 SKIP
strict PASS，四条旧 air-medium WARN 的断言局限继续保留。16 个冻结源码 hash
与提交匹配，源码和测试输入在 gates 前后未变。

证据位于 `.dev/ws73-discovery-profile-evidence.json`、
`ws73-discovery-profile-source-snapshot/`、`ws73-discovery-profile/v2/`、
`qemu-ws73-discovery-profile/` 和
`runtime-lifecycle-discovery-profile-{native,native-fault,standard}/manifest.json`。
第一次 C 测试编译的有符号比较警告及 sandbox ptrace 导致 LSan 启动失败均
保留；修正测试比较类型后通过，相同 sanitizer binary 在 sandbox 外通过。

本轮只读清点仍是 WS73=[]，没有真实 DLI/Ready/广播扫描/空口/slkd/slctl 证据，
北极星七项验收全部未完成。完整 S0–S6 继续保留，不关闭整项 issue。下一步是
完整广播参数构造与 SetParam → SetData → Enable 异步事务，再接齐完整发现
事件与动态 adapter/slctl；实际硬件及板级配置仍需要恢复后核验。
下一步继续真实设备/板级核验与 DLI 查询，并实现完整广播/扫描参数与异步完成、
discovery 事件和动态 adapter/slctl；之后才执行真实交替 20 轮及热插拔闭环。

### 完整原生事件通路（2026-10-10，部分成果）

[ece59f703711](https://github.com/OpenSparklink/linux/commit/ece59f7037110ad7db3e64b653347aa10f902511)
让 WS73 driver 的已校验 `0x180b` 报告进入每注册的预分配完整事件日志，绕开
只适用于管理回复的 260 字节 slot 上限。32 条日志使用 IRQ-safe lock；直接
复制完整 23 字节厂商头和最多 255 字节数据，无 per-report 分配和借用指针遗留。
管理回复保留在 Host 的匹配槽，不被报告压力抢走。

新增 version 1 `CONTROLLER_EVENT_GET`：固定 360 字节 query / 336 字节 record，
288 字节 payload，带真实设备 index/generation、profile、原始 code、接收
boottime、每注册 sequence 和游标覆盖 `lost`。读者独立取相同记录；参数尾部、
flags/reserved 清零；拒绝错误版本/flags、未来游标和错代注册。copyout EFAULT
不确认记录；GET 含 EAGAIN 切到该设备的原生 poll，直接 RX 唤醒，移除时
HUP/ENODEV，重选清订阅，旧 fd 不跟随 index 复用。GET 不触发 radio power
同步或命令。旧事件布局保留。当前日志只接 WS73 发现报告，不是完整 snoop、
标准/原生事件统一、重组或数据通路完成。

用户态 `slk-protocol` 同步 ABI、严格 WS73 report view；`libsparklink` 增加
caller-owned cursor 的同步读取和独立 OwnedFd/Tokio receiver，不使用旧 destructive
或截短流 fallback。header 保留原始地址类型、定向地址、PHY、未知厂商字节与
报告数据状态，有符号 RSSI 不被归一化。文档见 [API](API.md#dli-控制器-0x80-0x87)。
尚未接入 slkd 动态 adapter 或 slctl。

生产驱动合成 gate 在两个设备各注入 40 条最大报告：保留 seq 9..40，首记录
lost=8，每条 payload=278；两个独立 fd 读取内容完全一致。验证 copyout 失败
重试、空/就绪 poll、错代与未来游标、旧注册 HUP 和重插新 generation/独立序号。
这些是无 RF fixture 的 USB/HCC/driver/UAPI 证据，不能冒充真实扫描结果。

最终冻结 image #45 无警告构建；完整事件、原生 metadata Host、畸形 HCC 单
实例撤销和标准生命周期四 gate PASS，15 个源码 hash 与提交一致，输入/源码
前后未变。完整标准三控制器 96 case / 0 FAIL / 0 SKIP、strict PASS，本轮保留
3 条旧 air-medium WARN，其弱断言仍不证明跨设备连接/数据。中间 image #44
曾有 5 条 WARN，包括一个旧 data-loopback 在异步断开未完成时读到 EPIPE；
现等待真正移除，并把错误的断开后发送/空接收结果记 FAIL，没有削弱断言。
native verdict 也强制完整 kernel log 和早期记录。91 项 Python harness、32 位
C ABI 检查 PASS；用户态 workspace 137 项 PASS、fmt 和改动两 crate 的 strict
clippy PASS。全 workspace strict clippy 因未改动 slkd 的未使用项仍 FAIL。

证据 `.dev/native-event-stream-final-evidence.json`、
`native-event-stream-final-source-snapshot/`、`qemu-native-event-stream-final/`、
`runtime-lifecycle-native-event-final-{events,native,native-fault,standard}/manifest.json`。
初次内核编译错误、缺少 static libc 路径、sandbox socketpair 拒绝、D-Bus daemon
不在 PATH 的失败均保留，修正构建/测试环境后重测通过；#44 中间记录不作最终
源码证据。选定 getter 的 0x448 栈 frame 仅是局部检查，不是完整调用链证明。

主机级 inventory 仍 WS73=[]。Runtime 仍 metadata-only SETUP，发现命令仍拒绝；
没有真实 Ready/空口/20 轮交换/拔插或普通用户应用结果。七项验收全部未完成，
完整 S0–S6 和全部原 issues 继续开放。下一步接完整广播参数与 SetParam →
SetData → Enable、扫描参数/使能的异步事务，随后接动态 adapter/slctl 和实机验收。

## 完整参数编码与驱动回复规则（2026-10-10，部分成果）

内核 [b7b7708ffaa8](https://github.com/OpenSparklink/linux/commit/b7b7708ffaa821e3baa5e1714d8cdb5c35b9b415)
补齐 WS73 49 字节广播参数 encoder。显式传入两个 24 位周期、两类地址及其
原始字节、TX power、PHY/帧类型、查询请求通知/数量/持续时间和七个 16 位
持续时间/连接字段；宽 host 字段先检查溢出，再写整个输出。零功率保留为零，
127 才是明确无偏好；字节 33/34 不从角色推导厂商默认值，地址类型不套用
标准枚举映射。此 encoder 只表达协议字段，不证明控制器支持或板级/RF 校准。
毫秒到 125μs 单位转换拒绝溢出：扫描最大整毫秒值 8191，广播 2097151。

WS73 driver 在管理回复进入 Host 前校验本方言的成功返回长度，移除 generic
native core 中的厂商 opcode/返回长度表。0x0C02 成功 Complete 必须保留一个
实际 TX power 字节；0x0C03/04/05、0x1001/02 成功后无额外返回数据；四项
metadata 查询保持原精确长度。Status 接受仍不终结事务；错误 status 及 opaque
data 原样保留，未知返回格式不增加命令权限。广播数据仍使用 WS73 三字节头，
不能混入完整 Host 标准版本的 selection 字节。测试 marker 是 opaque 数据，
不据此宣称已完成 T/XS 20001 内层公开信息和 SLE 外层 type 255 的封装。

image #47 无警告构建。六 gate PASS：metadata Host、HCC 畸形单实例撤销、
完整事件、多设备标准生命周期，加上有效 HCC/DLI 内短一字节或多一字节的
成功地址 Complete 两条负例。两条新负例都要求 EPROTO 撤销且只撤销出错
实例，另一实例完成 18 次查询与后续地址查询，替换设备使用新 generation。
完整标准三控制器原 96 case / 0 FAIL / 0 SKIP strict PASS，1056 OK / 3 WARN；
旧 air-medium 警告及跨设备数据弱断言保留。生产 codec 47,568 项、DLI 110,654
项、91 项 harness 及 ASan/UBSan/LSan PASS。初次 sandbox 下 LSan 因 ptrace
限制失败，原日志保留；主机运行 sanitizer 后通过。用户态代码未变，本轮未重跑
workspace；上一阶段全 workspace strict clippy 的 slkd 未使用项仍未解决。

证据 `.dev/ws73-params-final-evidence.json`、`ws73-params-source-snapshot/`、
`ws73-params-full-qemu/` 和 `ws73-params-gate-*/manifest.json`，12 个冻结源码
hash 与提交一致，六 gate 前后源码/输入未变。参考只提取协议事实，pin 保持
libws73-usb@f4d85d0、完整 Host@f0872df；未复制参考实现或固件/校准数据。

本轮主机清点仍 WS73=[]。原生 Runtime 仍 metadata-only SETUP，发现命令仍
拒绝；**分步异步事务尚未接入，不能把参数 encoder 视为已启用广播/扫描**。
下一步把 SetParam → SetData（按需 ScanRsp）→ Enable 和 ScanParam → Enable
接入每设备 Host，逐步等待匹配 Complete；任一步错误中止后续使能，处理超时、
取消及新旧 start/stop intent，再接动态 adapter/slctl 和真实双设备验收。七项
北极星和全部原 issues 继续开放，完整 S0–S6 及后续四设备两组目标保留。

## 每设备 Host 分步事务基础（2026-10-10，部分成果）

内核 [fee81e705a03](https://github.com/OpenSparklink/linux/commit/fee81e705a031634b6b1d7334bc82e1c97a1dae9) 为每设备 Host 增加有界分步事务与原子整组入队，
共享整组 5 秒期限，逐步等待对应 Complete；成功 Status 仅确认受理，不能释放
在途槽位。失败取消剩余步骤，替换 start 保留先前 stop 屏障；仅当前 intent
完成才能确认广播/扫描。队列继续直接堆上初始化，生产路径不构造约 20KB 队列。
标准 USB typed 广播/扫描控制已使用单步骤事务；真实 WS73 完整多步骤事务尚未
接入，不能把该标准模型测试称为原生 RF 测试。公开 operation cookie/result、
驱动 typed 参数准备与发送校验、停止失败状态及原生故障恢复仍待实现。

冻结 image #50 无警告构建；生产队列/进度模块 14 项 Rust 测试、100 项 harness、
七条独立 gate PASS（标准 recipe、标准生命周期、原生 metadata、HCC fault、
短/长成功回复和完整事件）。recipe fixture 在 Status 后延迟 Complete，并断言
期间不收到下一命令。相同 fixture/测试程序对旧 image #47 因提前发送命令触发
断言而预期失败，完整负对照证据保留。多步骤/取消/队列边界覆盖来自生产模块
单元测试；在 USB 上实际跑通的 recipe 是单步骤。完整标准三控制器原 96 case /
0 FAIL / 0 SKIP strict PASS，1056 OK / 3 条旧 WARN，跨设备数据弱断言的局限保留。

证据 `.dev/host-recipe-final-evidence.json`、`host-recipe-source-snapshot/`、
`host-recipe-final-full-qemu/`、`host-recipe-final-gate-*/manifest.json` 及
`host-recipe-negative-verdict.json`；14 个冻结源码 hash 与提交一致。初次静态
链接缺少 libc 路径、中间 image #48/#49、预期负对照失败均保留；修正环境后
最终门禁通过。QEMU 构建旧 unused helper 警告保留。选定局部栈帧最大 312 字节，
不据此宣称完整调用链安全。用户态仅更新文档，未重复 workspace 测试；此前
全 workspace strict clippy 的未改动 slkd 未使用项失败仍保留。

主机级清点仍 WS73=[]。原生 Runtime 仍 metadata-only SETUP，RF 命令继续拒绝。
下一步接 driver-owned typed SetParam → SetData（按需 ScanRsp）→ Enable、
ScanParam → Enable 及结果接口，再接动态 adapter/slctl；按原七项验收进行真实
双设备空口、20 轮角色交换和拔插测试，随后四设备两组。七项均未完成，不关闭
整项 issue，完整 S0–S6、全部原验收与两组并行目标保持。

## 驱动拥有完整发现事务准备与发送边界（2026-10-10，部分成果）

内核 [edd8cf016f1d](https://github.com/OpenSparklink/linux/commit/edd8cf016f1d6c0610622d4ba049af5e80c6ffa2) 增加内部 typed 发现准备接口（非用户态/线上 ABI）。
WS73 callback 生成 SetParam → SetData →（显式可选 ScanRsp）→ Enable，
ScanParam → Enable 或独立 stop。使用一个 255 字节 scratch 先检查整组，再
写入调用者 plan，晚步骤错误不改变任何输出；未使用字节/步骤清零。所有
参数由调用者显式提供，不插入角色、功率、地址或板级默认。输入在调用期间
须不可变且与输出不重叠；callback 不进行 I/O，也不保留借用指针。

TX worker 把 Host 私有 recipe tag 经 Backend 交给原生驱动，在实际 transfer
前校验操作种类、步骤位置/数量、方言 schema 及 enable 方向。typed 回调成对
可选，缺少支持拒绝操作；raw DLI 仍使用原 metadata 白名单。核心没有新增
WS73 opcode/布局表，准备出合法 RF 帧也不扩大 raw 权限。原广播参数 host
结构移到内部公共请求层，其 wire 编码仍归 WS73；不存在标准 USB/厂商数据
头混用。公开 UAPI 未改，生产用户态代码未改。

冻结 image #51 无警告构建；生产 compiler/codec 450,104 次检查、ASan/UBSan/
LSan、100 项 harness 和七独立 QEMU gate PASS。测试检查全部 0..251 数据长度、
显式空/完整 response、原始参数字段、整组错误原子性、unused 字段拒绝、每
步骤序号/数量与全部 256 enable 值；每个合法 RF 步骤同时验证 raw 拒绝。
完整标准三控制器原 96 case / 0 FAIL / 0 SKIP strict PASS，1057 OK / 3 条旧
WARN，旧 air-medium/跨设备数据弱断言继续保留。七 gate 仍为支持门禁，**没有
执行新的原生多步骤 RF 事务**。选定 build 局部栈分配 272 字节，不宣称完整
调用链已验证。用户态仅文档变更未重跑 workspace，旧 slkd strict-clippy 未使用
项失败继续保留。

证据 `.dev/typed-discovery-final-evidence.json`、`typed-discovery-source-snapshot/`、
`typed-discovery-full-qemu/`、`typed-discovery-final-gate-*/manifest.json`；13 个冻结
源码 hash 与提交一致，七 gate 源码/输入前后不变。最初 standalone 全局 kernel
include 路径污染 libc header，改为受限访问公共内部 header 后构建通过；首次
QEMU 因 sandbox QMP socket bind EPERM 在来宾启动前失败，确认 session 终止
后在新目录使用主机权限重测通过。失败、中间辅助脚本断言与最终日志均保留。

主机清点 WS73=[]。核心提交 API 尚未调用 prepare callback 或排入原生 recipe；
下一步必须接版本化 typed 操作提交与 cookie/result、原生参数能力策略、停止
失败/故障恢复，随后动态 adapter/slctl。Runtime 仍 metadata-only SETUP，RF
仍拒绝。全部七项真实双设备验收、随后四设备两组和完整 S0–S6 保持；所有原
issues 开放，不以 preparation 或支持 QEMU PASS 提前关闭整项。

## 原生 typed 操作提交与结果（2026-10-10，部分成果）

内核 [6b927a4d07f4](https://github.com/OpenSparklink/linux/commit/6b927a4d07f43cfa602f5c6d7c52e1c14af0cabf) 接通版本化
DISCOVERY_SUBMIT/RESULT（704/64字节，32/64位ABI一致）。显式选择fd，probe获取
profile/generation，再使用非零调用者request_id提交完整参数/数据。write-only
提交不在admission后copyout；结果独立重复读，64条保留，非终态不淘汰，最旧
终态可淘汰ENOENT。duplicate保留id返回EEXIST，wrong generation/旧fd不跟随重插。
核心现在实际调用driver prepare，将完整原生recipe排入同一owner Host，经TX
worker发送USB/HCC/DLI；不扩大raw metadata白名单。结果保留成功/失败步骤、
原始status、负host errno、取消和driver标注步骤的实际TX power（不取请求功率）。
两radio domain初始Unknown，先等两个stop完成再start；成功Status不终结操作，
stop提交不宣称Off，失败stop保留先前确认状态。取消在途enable成功后标为Unknown，
physical stop完成才Off；timeout锁存单owner故障并将radio标Unknown，不发后续使能。
这些字段是确认的命令状态，不代表PHY实时活动；自主终止事件仍待接。

用户态同步ABI、ioctl、Adapter probe/submit/non-destructive query/async wait，
deadline溢出返回错误且不执行ioctl；尚未接动态slkd adapter与slctl命令。冻结image
#55无警告构建；8独立QEMU gate PASS，包括**实际虚拟WS73 USB完整typed事务**：
3/4步广播、扫描、每步骤0xfd失败、stop失败重试、取消、selected power=-42、
结果EFAULT重试、独立request_id、timeout故障隔离及重插新generation/结果状态。
每owner五个控制循环为合成支持测试，绝不是20轮真实角色交换或空口证据。
模型检查参数、数据、地址与次序，延迟Complete并断言未提前发下一命令；reserved
模式显式触发合成故障，禁止用于真实设备。另7条原支持gate保持通过。
完整原96-case标准三控制器回归strict PASS，1056 OK/0 FAIL/0 SKIP/3旧WARN；
旧air-medium/跨设备数据弱断言保持。14项生产Host、7项生产result-store、450105
次codec检查与ASan/UBSan/LSan、110项harness、32/64位C ABI、139项workspace
和改动crates strict clippy PASS。此前全workspace slkd strict-clippy未使用项仍未解决。

证据 `.dev/discovery-submit-final-evidence.json`、`discovery-submit-source-snapshot/`、
`discovery-submit-full-qemu/`、`discovery-submit-v3-gate-*/manifest.json`；19冻结内核
源码hash与提交一致、8 gate输入/源码前后不变。初次sandbox socket EPERM、CLI
条件tuple错误、guest缩进-Werror以及未绑定fd错返ENODEV的#54失败全部保留；
修正后#55通过。#52/53/54是中间镜像，不作最终证据。选定submit/result/prepare
局部栈分配1416/104/88字节，不宣称完整调用链安全。

本机WS73=[]。Native仍SETUP；新typed接口可实验执行完整命令，legacy bare-enable
与raw RF仍拒绝。真正Ready/能力和板级校准策略、自主终止、动态adapter/slctl、
AD内外层封装、普通用户与全部七项真实验收待完成。下一步处理原生Ready/故障
可见性并把新接口与完整发现事件接入动态adapter/slctl，再做真实双设备闭环和
四设备两组；全部原issues和完整S0–S6保持开放，不能以virtual事务提前关闭整项。

## slctl 原生广播/扫描闭环（2026-10-10，部分成果）

实现基本 WS73 policy v1、D-Bus caller request id 提交/结果与 slctl
`advertise on|off`、`scan on|off`、`result <id>`。广播采用 handle0、不可连接/
不可查询、fixed T、150ms、三广播信道、控制器选择功率127、frame1编码0；
被动扫描 frame1 bitmap1、200ms interval/100ms window、保留重复。
参数由用户态完整提供，驱动仍独立验证/编码；不发送 raw RF、不伪造 UUID。
随机16字节标识封装为 type255 接入层数据及发现等级/完整名称 `slk-<hex>`，
依据 T/XS 10002 §7.1.4、20001 §6.5 和 10003 §8.2.1。真实固件支持必须由
实际结果/空口证明，拒绝时保留原始 status，不偷偷切换参数。

`slctl --adapter <TX> advertise on` 输出 marker/data/request 和实际功率；
`slctl --adapter <RX> scan on <marker> <TX-address>` 等匹配 Complete 后，只
接受该代次、历史 watermark 之后且完整数据/地址一致的新报告，显示 RSSI。
10秒单调时间界限从扫描 admission 前开始；GetTimedReports 独立保留内核
CLOCK_BOOTTIME receipt ns 和 daemon wall time。超时不撤销已接收操作，可以
用 request id 查询或显式 stop。拔插须重新选择新代次，无需重启 slkd。

新增可复现软件门禁 `run_daemon_lifecycle.py --radio-policy`：实际 slkd/slctl
由 guest uid1000 运行，两只 synthetic USB/HCC/DLI model 经显式合成介质互收。
20轮交换角色、每轮随机标识；拔插同 PID 新代次后再交换2轮；两阶段分别关闭
TX 后观察2秒无新报告。验证器核对每个实际发送者地址、接收者代次/递增序号/
内核时间、22个不同标识、43字节数据、10秒界限、88项 matched Complete 结果与
admission ID，并拒绝缺失/重复/失败/跨生命周期证据。

初次测试发现 zbus 默认执行器不在 Tokio runtime 中，导致 handler panic；
启用 Tokio 后，又发现 AsyncFd 先订阅旧队列再切换 native queue，收不到 wakeup。
现先激活 native subscription 再 epoll 注册，非破坏日志从0重读而不丢初始事件。
所有失败与最终 source/image/program hash、QMP、完整内核日志保留在
`.dev/radio-control-*`。软件闭环仅为开发支撑；本机 inventory=[]，七项真实验收
全部继续未勾选，四设备并行与完整 S0–S6 保留，所有整项 issues 保持开放。

本阶段冻结验证：原96-case完整QEMU strict PASS（1056 OK / 0 FAIL / 0 SKIP /
3旧WARN）、8条原native/standard gate全部PASS、135项harness、145项workspace
和protocol/library/slctl strict clippy PASS；最终双设备合成CLI gate保存于
`.dev/radio-control-daemon-final-v2/manifest.json`，source/input前后不变。
完整slkd strict clippy仍FAIL（旧未使用代码/测试helper/参数数目问题），不计为通过。

## 物理控制与原始 RX 佐证工具（2026-10-10，部分成果）

新增 `tools/ws73_north_star.py` 的普通用户控制记录与独立 `verify`；物理端口/
原生 sysfs 元数据/Ready 相互核对，经 slctl 连续20轮角色交换、人工单设备
拔插/同进程新代次后2轮及两阶段TX-off。`slctl daemon` 给出D-Bus实际owner/
PID/UID，另检查内核process start_ticks。控制PASS仍是EVIDENCE_PENDING。

独立解析classic usbmon pcap完整IN USB/HCC/DLI，核对每轮真实RX字节、
原始成功Complete、初始/重插实际查询、负向围住时间窗与零drop统计，输出
RX_CORROBORATED；不代表固件/板级资格或PHY嗅探器。抓包来源仍须审查，
合成fixture只验证解析和拒绝错误，不能满足七项实机验收。本机WS73=[]，
整项issues与完整S0–S6继续OPEN。见[可复现操作与边界](WS73_PHYSICAL_TEST.md)。

## 生产 D-Bus 观察/控制授权（2026-10-10，部分成果）

系统策略从全用户任意控制改为默认逐项观察、sparklink 组控制、root 持有服务。
Properties.Set、敏感或有副作用的读取、新方法、省略接口与 unique-owner 写入
均需授权。公开属性仍是公共读取，静态 XML 不过滤属性消息体。管理员一次性
部署和组加入与应用运行分开，应用无需 sudo/capability。

实际 guest 门禁显式加载生产 XML：root slkd、uid1000 主组1002/补充组1000
控制、uid1001 非组观察。两种应用的 UID/GID 与四类 capability=0 被检查；
未授权用户不能直接访问 chardev，但观察成功，16条总线拒绝和组用户服务名
拒绝成功，状态未变/无 admission。组用户再完成合成20轮、同 daemon PID/
owner 的拔插后2轮与 TX-off。原 uid1000 daemon/CLI 会话门禁也通过。

145 harness、145 workspace、36物理工具测试与改动crate strict clippy PASS；
完整原96-case QEMU strict PASS（1054 OK/0 FAIL/0 SKIP/3旧WARN）。首轮
guest 调试镜像过大解包失败被保留，guest 副本裁掉调试符号后最终门禁通过；
源码/策略/输入前后不变。见 `.dev/bus-policy-production-gate-v3/manifest.json`、
`.dev/bus-policy-session-gate/manifest.json` 与[授权文档](DBUS_AUTHORIZATION.md)。
静态策略不实现内核 Managed/Diagnostic writer lease 或全部 raw DLI/其他入口
隔离，不能关闭 K#5/U#6。主机 WS73=[]，未运行真实控制或抓包，七项仍待验。

## 内核实际调用者权限（2026-10-10，部分成果）

新增显式授权表，135个唯一声明 ioctl 分为34观察、2fd选择和99受保护操作。
受保护调用在复制参数、同步电源或提交命令前检查初始user namespace的
CAP_NET_ADMIN；raw DLI、远端读、破坏性出队与口令同样受保护。未知命令
保持ENOTTY，观察不再同步全局电源。五个configfs store与五个genl mutation
bridge也检查权限；genl已实现的管理请求保留GENL_ADMIN_PERM。UAPI中两条
重复但相同的discovery宏已去重，数值/布局未变，后续新ioctl须显式审查。

真实syscall门禁继承实际fd，再分别变为uid1001、补充组uid1000、uid0且清空
capability；每名99条protected ioctl、5个configfs写、5条genl管理拒绝，
34观察和fd选择可用。注册/metadata/command admission未变；待同步idle
配置不被观察激活。普通slctl仍通过root daemon完成合成20轮、同PID/owner
拔插后2轮与TX-off。开发session fixture也改用root daemon，旧uid1000 slkd
直接管理成功记录仅为历史状态；节点组不授予直接管理权限。

八条原native/standard/recipe/event/fault门禁、生产权限组合门禁及开发session
闭环均PASS；168harness通过，完整原96-case QEMU strict PASS（1056 OK /
0 FAIL / 0 SKIP / 3旧WARN）。事件门禁首轮报告尚未全部接收就检查overflow，
ReadFeatures Complete不能作40条报告接收屏障；独立观察fd限时确认seq40后，
原32条完整payload/loss/fanout/copyfault/poll/旧代次HUP断言保持且通过。

构建漂移曾因stable缺rust-src静默禁用Rust/SparkLink；错误配置/日志保留，
runner已增加必需配置拒绝及实际负向命令。显式工具链恢复后，冻结合格#60
镜像/配置/对象/编译指令，所有最终输入/源码guard通过。详见
`.dev/kernel-auth-final-evidence.json`、`kernel-auth-image/`与
[当前授权与迁移边界](DBUS_AUTHORIZATION.md)。
多个特权writer尚未被独占lease协调，Managed/Diagnostic/Proxy/PDU owner及
撤销/崩溃恢复、接口迁移继续待做。主机完整拓扑确认WS73四口hub在但其下
设备未枚举，未运行实机；七项、四设备和所有原issues继续OPEN。


### 原生 WS73 的文件 ownership 与撤销（2026-10-10，部分成果）

三个固定布局入口提供 Managed/Diagnostic acquire/release/query，文件描述
绑定 generation 与单调 token。slkd 每设备初始化、typed discovery、旧管理
统一控制 fd，观察订阅独立；原生 unowned genl bridge 返回 EPERM。关闭或
release 撤销 queued intent，但保留 active wire reply，以 driver-prepared
停止 recipe 确认 Off 后才允许后继。失败/缺失 Complete 保留 Fault/Unknown、
首次错误及 raw reply status/opcode；成功清理同代次可换 owner，不确定故障
目前通过重插新代次恢复。profile0、Proxy/PDU/Security、自动原地恢复和其余
canonical 迁移继续待做。可复现命令见[ownership 契约](MANAGEMENT_OWNERSHIP.md)。
实机北极星七项、四设备两组与完整S0–S6保持；合成验证不替代真实固件/RF。


当前最终验证：181harness、146workspace及protocol/library/slctl strict-clippy
PASS；九条native/standard/事件/故障/ownership与生产/默认session两daemon
门禁全部PASS。真实syscall新增六项schema拒绝、owner fd降权传递、dup最后关闭、
两个实际停止确认、失败停止原始status=253/opcode=0x0c05、超过原deadline首次
errno稳定、pending wire回复缺失时取消/timeout、重插代次隔离。普通slctl合成
20轮交换+同PID/owner重插2轮/TX-off保持通过。完整原96-case 1056 OK/0 FAIL/
0 SKIP/3旧WARN；两控制器初轮严格SKIP(2)保留，完整使用三控制器配置通过。
合格#64镜像/配置/对象、最终source/input guards与日志保留于
`.dev/management-final-evidence.json`。原完整slkd strict-clippy旧问题仍待处理。
实际主机完整USB拓扑仍WS73=[]，未做实机控制/RF；七项及全部整项issues保持OPEN。


### daemon 显式撤销与同代次接任（2026-10-10，部分成果）

每设备保存 native lease；对象撤销/部分发布失败显式 RELEASE，不等在途 RPC
共享的控制 fd 最后关闭。释放后按每设备独立 QUERY 观察清理，最多6秒；
不跨 ioctl/等待持有目录或 SharedState 锁。ENODEV 结束旧 registration，
Fault/timeout 记录原错误，不伪造 Off/恢复；SIGTERM 与 SIGINT 共用正常清理。

新增实际 root slkd + uid1000 slctl + 原生 USB 合成模型门禁：20轮换向、同
daemon 重插2轮及 TX-off 之后保持广播/扫描运行，SIGTERM 后独立 C observer
确认两个 Free/Off/Ready、隐藏 owner token；daemon 在 fd 仍保留时确认释放。
新 PID/新 D-Bus owner 不经 USB 重插接管原 generation，SIGINT 再次清理。
生产策略/内核凭据降权矩阵一起验证，复现参数及边界见
[ownership 契约](MANAGEMENT_OWNERSHIP.md)。198 harness、146 workspace 与原
完整96-case回归通过（0 FAIL/0 SKIP，3既有WARN）；首次阶段顺序判定错误
记录保留；早期接任记录发现缺失sort导致一项列表比较无效，最终改用
BusyBox并让判定器拒绝shell依赖缺失，早期PASS不计入最终证据。daemon故障/强制终止、profile0/Proxy/PDU/Security
及完整后续矩阵仍待做。主机真实 WS73 仍未枚举；实机七项、四设备两组与
全部原S0–S6/整项issues仍开放，合成成功不算真实空口验收。


### slkconfig 显式绑定与原生 Diagnostic（2026-10-10，部分成果）

每设备CLI必须明确adapter，原生四种白名单查询还必须给出实际generation并
取得独占Diagnostic。只读controller/management不拿lease、不消费raw；普通
uid1000/CapEff=0观察成功，但raw查询EPERM。Managed冲突EBUSY，缺参数、
旧代次与原生legacy reset均不增加命令/改变snapshot。普通应用经slctl/slkd。

旧raw回复无sequence，工具不伪造关联：独占后清历史、检查quiet、一次一条
查询；成功Status不算完成，等待Complete并验证6/10/5/6字节返回。零opcode
credit通知只作非查询投影处理，credits归Host。失败/timeout仍release，未
完成清理不打印成功。两设备八次实际查询、未读Status/Complete旧对清理与
同代次daemon接任在生产/session合成门禁通过。209harness/148workspace、
slkconfig严格clippy及原96-case 1058 OK/0 FAIL/0 SKIP/3旧WARN通过。早期
Status、历史回复与credit数量假设的失败记录保留；runtime内核仍合格#64。

见[ownership/复现与兼容边界](MANAGEMENT_OWNERSHIP.md)。旧profile0管理仅
保留迁移入口；全部工具独立snoop、C/Python owner、完整Backend与故障矩阵
尚待做。实机七项、四设备两组及完整S0–S6/全部整项issues继续开放，合成
查询不算真实WS73固件/RF验收。


### WS73 独立 snoop 与实际工具迁移（2026-10-10，部分成果）

新增 CAP_NET_ADMIN 的被动每 Runtime DLI seam ring；不拿管理 lease、不发命令、
不消耗 Host raw reply 或其他 reader。必须显式 index/generation，保留 seq/
boottime/方向/transport结果/长度/截断与精确丢失。64 条预分配记录、每条最多
320 字节；RX 是 HCC 验证后的 service10/queue8 SLE slot（DLI 解析前），
TX_RESULT 为命令提交/传输尝试返回后的 A1 bytes，不能当成 DLI Complete 或
空口发射证据。没有启动/USB aggregate/HCC header/PCAP/RF 捕获的声明。

slkmon/slkdump 默认使用独立 fd/AsyncFd 和内核唤醒；旧内核不作消费型 fallback。
两种实际工具在 slkd 持 Managed 时均能观察；native capture 新建 0600，禁止
覆盖，固定可移植 SLKSNP01 格式，所有写入/flush 错误终止。旧 profile0 仅保留
显式 --legacy，仍是旧消费型模式。普通 uid1000 的 raw 抓取 EPERM，不创建
capture；普通应用 slctl 广播/扫描继续无需 sudo。

最终生产/内核凭据矩阵和 session 两个合成 daemon 门禁 PASS，仍保留原来的
20 轮交换、同 daemon PID/owner 重插 2 轮、TX-off 和 TERM/INT 管理接任。
两份 32-record 真正导出的文件逐字节相同，host parser 重新核对每条 metadata、
framing 与 raw RX 的 address/RSSI/data 对应独立 slctl 结果；旧 observer 拔出
poll ERR|HUP/查询 ENODEV，实际工具终止，新 generation 重新抓取，旧代次拒绝。
C probe 验证独立 reader、5 项 schema、模式混用、EFAULT 可读重试、继承 fd
降权拒绝、无 command admission、明确慢 reader lost 和重新打开独立读取。
大包截断目前有 ABI/library 校验，尚未声称 live producer 大包注入已验证。

冻结内核 #67，9 个原 Runtime/ownership/标准 recipe/发现/事件/故障门禁 PASS；
228 harness、152 workspace、slk-protocol/libsparklink/slkmon/slkdump 全 target
strict-clippy、32/64 位 C ABI 编译断言 PASS。原 96-case QEMU 1056 OK /
0 FAIL / 0 SKIP / 3 既有 WARN。保留最初 C signedness 构建错误、缺 busybox
PATH 的回归先决条件失败和沙箱 Unix socket 受限失败；用缓存依赖与授权的
隔离测试重跑，最终门禁不使用失败结果。完整 slkd strict-clippy 未声明通过。

详见 [SNOOP 契约与复现](SNOOP.md)。本地 .dev/snoop-final-evidence.json、
snoop-source-snapshot-v2、snoop-final-image、两个 snoop-*-gate/、9 个
snoop-qualified-gate-* 与 snoop-full-qemu-archive 保留完整日志和 SHA256。
C/Python snoop/owner 绑定、其他 profile、Proxy/PDU/Security ownership 和全
故障/PM/发布矩阵仍待完成；不提前关闭任何整项 issue。最新主机只读枚举 WS73
仍为 []，没有真实固件/空口证据；真实七项仍 0/7，四设备两组和完整 S0–S6 保留。


### 隔离开发客体 / 实机入口 sentinel 修正（2026-10-10，部分成果）

新增 tools/ws73_target.py prepare/run/support、guest supervisor 和 readiness/
probe。只准备本机私有 KVM capsule，不装主机服务，不要求嵌套虚拟化；严格
固定 kernel/config/initramfs/QEMU 输入路径与 SHA，防止核对旧路径却启动另一份
文件。实际系统 D-Bus 使用生产策略，root slkd 与 uid1000/gid1002/附属组1000
应用分开；archive 强制 root inode、账号锁定、代码/固件不可由普通应用改写。

客体启动时无 USB，tcpdump 在 guest usbmon1 全长启动并降权 uid1003/零
capabilities 后才透传第一只，第一只经普通 slctl 独立 Ready 后再加第二只。
固定 host-port/guest-port/registration 映射，带本 QEMU live fd 的自动重新
枚举保持，不解绑未知主机占用。只有本轮空的 mapped-9p evidence 目录导出，
不暴露工作区；普通串口 shell可运行原有完整物理 recorder，退出后封存 PCAP/
统计、dmesg/daemon/console/QMP。ENVIRONMENT_FINISHED 不等于北极星通过。

实际客体发现旧实机 recorder 要求 controller_error=0，而 driver 明确定义
0x100 为“未收到错误事件”，导致正常设备拒绝。现在共用 healthy native parser
保留 sentinel=100；任何错误字节（包括0）、broken、不streaming、零代次拒绝。
新增完整 filesystem fixture与实际模型sysfs读回；不把未收到的错误事件写成成功。

冻结 #67/core crates 未修改。最终 capsule support PASS：两个真实执行的
模型 Runtime 独立 Ready；系统总线控制/观察策略、普通应用只读代码/固件、无
usbmon权限、collector降权、普通 uid1000/零caps TTY输入、20轮交换/TX-off，
实际导出的1505条客体USB记录/20个完整RX报告对应应用，mon/dump32条一致。
之前同guest-code的完整支持门禁可重复，最终输入路径/manifest guards也重跑。
47个工具测试通过。模型没有ROM/firmware执行/RF，实机 recorder明确拒绝其
描述符且保留FAIL。初次tcpdump缺降权账号、两次sentinel误判超时记录均保留；
并验证真实flock阻止并行lab。真实入口在当前WS73=[]时启动VM前拒绝，留FAIL。

见 [客体准备/真实端口与支持门禁](WS73_TARGET_ENVIRONMENT.md)。本地
.dev/target-final-evidence.json、target-source-snapshot、target-prepared-qualified、
target-support-qualified与前期重复/失败记录保留。capsule仅验证文件hash/格式，
不认可SDK默认候选板参；board_qualification始终NOT_ASSERTED。真正冷启动/
透传重新枚举/物理拔插与完整七项仍待硬件；原S0–S6、四设备两组与全部整项issues
保持OPEN，七项0/7，不提前关闭。

## 成功空 bulk 完成的 Runtime 修复（2026-10-10）

检查真实接收链路发现 native URB 将成功零长度 bulk IN 送入 HCC parser，导致
该设备撤销 Runtime。修复只跳过成功空 bulk 并重投同一URB；不发布DLI数据、
credit、Complete或snoop。URB错误仍优先，interrupt必须八字节，非空畸形HCC/
DLI仍Fault。新增模型runtime-zlp在post-bootstrap命令回复前注入空USB完成，
不清除in-flight；用户态support --empty-bulk必须从actual guest usbmon确认
两只身份都实际收到该完成，真实run不提供注入选项。

同一新模型/guest程序对照：旧冻结#67，实际capture有一条成功empty completion，
紧接着driver报native RX stopped: -22，sysfs为id=-1/streaming=0/broken=1；
无法Ready，30秒环境deadline留FAIL。不是把QEMU退出或缺标记当作缺陷复现。
新#68下双设备独立Ready与普通20轮/TX-off PASS：1799条实际guestUSB记录，
147条成功空完成、20个RX报告与应用地址/RSSI/data对应，独立mon/dump32条相同。
无空包基线仍1505条/20报告/32snoop PASS；工具50项PASS。正常、事件、ownership
及HCC/short-reply/trailing-reply六条native生命周期门禁PASS，保留survivor、
stale generation与非空错误边界。重复运行和原始证据留在.dev/zlp-*。

构建时缺meson搜索路径、sandbox ccache目录不可写、独立QEMU缺默认BIOS目录的
失败均留存；修正本地构建环境后另起新目录，未覆盖。新QEMU binary单独保存，
原资格QEMU binary与cached model已按原hash恢复；新BIOS文件hash也保存。
SDK板参仍NOT_ASSERTED；模型没有真实ROM/firmware/RF。当前实机为空，真正
双设备七项0/7；S0–S6/四设备两组/整项issues继续OPEN。

## 同客体的完整控制/重插佐证门禁（2026-10-10）

原target support只用独立shell做20轮，未在同一套系统总线/权限/捕获环境执行
整个Python实机控制orchestrator。现单独SyntheticControlRun复用Run的所有
phase/negative/wait/Ready/daemon/cleanup逻辑；scope/status明确为synthetic
control support，只有read_registration与合成TTY确认入口不同。实机CLI仍固定
Run、拒绝fixture、没有允许模型的开关。合成入口要求精确fixture描述符和真实
sysfs/查询的原生身份。Host QMP只对自己VM移除/重加slot0，普通进程观察USB
消失、执行幸存设备scan/stop、旧adapter拒绝、新代次Ready及两轮重插复验。

最终guest代码普通hotplug支撑门禁PASS：20+2个唯一marker、两次TX-off、同一PID/
start_ticks/bus owner、幸存generation稳定、旧选择拒绝、新generation及最终
双设备stop。1865条封存客体USB记录中22个RX精确对应应用；对三代次四项启动
查询、每轮全部DLI Complete命令时间窗和阴性区间做共同佐证。32条独立mon/
dump仍一致。叠加empty-bulk门禁同样PASS：2211条USB记录、173条成功空完成
（三代次均有）、22RX/22应用匹配、相同生命周期和独立snoop。原无hotplug基线
继续保留。55工具测试PASS。Linux/core crates未改，继续冻结#68，不冒称新全仓
Rust/clippy/96-case/kernel build。

另修正离线物理验收只依scope/status分流的弱处：检查initial/replacement完整
USB描述符并拒绝fixture。实际主机CLI针对合成run留FAIL；仅改scope/status的
副本同样因fixture描述符留FAIL，不能将合成佐证提升为RX_CORROBORATED。
这不认证任意可编辑capture/JSON。此前开发run的原始console/QMP/run/capture
均保留；最终共同控制proof与全部source/input/artifact hash保存在.dev/control-*。
当前真实设备仍为空、SDK板参NOT_ASSERTED、真实七项0/7，全方案及整项issuesOPEN。

## 原生 C/Python 绑定与旧 adapter 存活修复（2026-10-10，部分成果）

新增11个C原生符号和独立Python NativeAdapter：每fd显式select/generation、完整
snapshot、Managed/Diagnostic query/acquire/异步release、typed discovery
admission/result、非消费完整event/snoop和借用poll fd。新符号负errno，旧符号
0/-1不变；quiet/失败不改output或cursor。Python的index/generation/request_id/lease
参数拒绝越界，返回独立record
副本，并在ctypes释放GIL时将free和本handle调用串行。八字节对齐不能由旧32位
ctypes表达时明确拒绝；不宣称32位库/interpreter运行通过。

真正generated C / Rust / Python / canonical kernel UAPI共21结构全部字段/size/
align/offset相符，freestanding i386 C静态断言也通过。29绑定测试使用actual
cdylib、/dev/null验证errno、null/output与失败constructor的fd清理；安装别名
同样29通过。发现Cargo实际产物liblibsparklink.so与旧安装/加载/CI名字不同，
修正source路径保留安装libsparklink.so别名；make install只在私有DESTDIR执行。
cbindgen0.29.4固定并重生成逐字节一致；libsparklink全target strict-clippy通过。

实际模型客体增加C/Python库调用：slkd持Managed期间两语言/两设备/root和
uid1000共8次观察、授权/Busy/另fd无token、独立reader/quiet/模式拒绝；daemon
TERM清理后4次root writer取得Managed，完成scan/adv stop、释放等Free并接任
Diagnostic，每次Complete由对应USB身份/opcode/实际调用时间窗佐证。

保留四个跨拔插旧C/Python event/trace句柄时，旧版ListAdapters只读directory
cache的缺陷被复现：sysfs端口消失/幸存scan成功后，旧slctl show仍exit0且Ready，
严格recorder留FAIL。修复directory存不可变selected fd/generation，ListAdapters
在锁外blocking worker查询实际kernel身份；ENODEV不列出，其他错误显式返回，
不等待business state/USB命令或使用默认可用值。没有放松recorder旧选择断言。
同流程最终通过旧adapter立即拒绝、四旧fd ERR|HUP/ENODEV、新gen及同daemon
20+2发现；原失败console/QMP/run/未封存部分capture、旧源码与实际guest程序保留。

Linux仍冻结#68，152workspace、55工具测试通过。初次sandbox socket、缺dbus
路径、cbindgen alignment/依赖常量、CCACHE只读、旧库文件名与首次无spontaneous
event的探针错误均留原记录，修正环境/生成配置或测试时序后另起最终输出，不
使用失败结果。最终capture与各模式数量/源码hash见本地.dev/bindings-*；本批
没有重跑原96-case/full kernel build，CI更改尚未声称远端CI通过。没有实机Ready/
firmware/RF/物理拔插；板参NOT_ASSERTED，WS73=[]、七项0/7，完整S0–S6/四设备
两组/全部整项issues仍OPEN。profile0、Diagnostic raw/PDU/Security、Proxy和
完整故障/PM/兼容/发布矩阵继续保留。

最终同一prepared capsule三模式均PASS：hotplug+empty为2251条封存USB/
177成功空完成/22应用-RX匹配，普通hotplug1897条/22匹配，无hotplug基线
1537条/20匹配；各自32条独立snoop相同、8观察/4writer，hotplug各有四个旧
handle终态证明。新增4个writer stop带来32条USB（empty时另有8条），不将
这些额外Complete计作发现或用它们补齐连续20轮。C++17生成头也能编译。

### 防止 daemon 延迟读取旧 RX 被误判为本轮发现

`slctl scan on <marker> <address>` 在提交前记录 Linux `CLOCK_BOOTTIME`
下界，与原生 event 的 `timestamp_ns` 使用同一时钟。匹配同时要求本次
watermark 之后的序号、正确 generation/address/data、零 lost，以及 RX 时间
位于本次提交前下界与读取后的当前 boottime 之间。不能把 wall clock 或
Tokio Instant 与 kernel boottime 混比；不修改现有 command/report UAPI。

`NativeScanWindow` 记录 generation/request/start_boottime_ns；实机 recorder
和离线 USB 佐证要求该记录唯一且与成功 scan result 相关，拒绝时间下界以前
的 RX。较旧的完整控制记录若缺此字段，当前 verifier 会拒绝；旧已冻结证据
仍保留其原源码/判定器版本，不回填记录或宣称通过新检查。

新增 `crates/slctl/tests/scan_freshness.rs` 使用私有 D-Bus 合成 peer 和实际
one-shot slctl，覆盖延迟旧报告、未来时间、lost、错误 generation/address/data
及真正本次时间窗口内的记录。旧实际 CLI 接受 timestamp=1 的记录，反例保留；
修复后的 CLI 只接受最后一条有效记录。这证明应用过滤，不能当作真实 RX/RF。
复现：`cargo test -p slctl --test scan_freshness -- --nocapture`；需要 dbus-daemon，
可通过 `SPARKLINK_TEST_DBUS_DAEMON` 指定私有 binary。

10 秒整体命令限制暂仍从提交前计时，比北极星要求的实际 scan Complete 后
10 秒更早；此次没有实现精确 Complete 时间导出。该差异继续待修正，不能以
收紧窗口代替完整时间语义或据此关闭 issue。真实七项0/7、四设备两组及完整
S0–S6保留，所有原整项 issues 继续开放。

### Scan Complete 后的完整十秒窗口

补齐上节保留的时间语义：Host 在匹配 opcode 的回复进入保留槽时记录
CLOCK_BOOTTIME，worker稍后消费时只为最终成功 Complete 保留该接收时间。
新48字节只读 `SleDiscoveryTiming`/0x8f 使用显式generation/request，原64字节
result不变；Status、失败、取消、过期或迟到回复不能构成成功时间。

slkd新增GetDiscoveryTiming，生产观察策略允许查询。slctl校验相同generation/
request、scan-start、Succeeded、0x1002及status=0，禁止零/早期/未来时间。
匹配RX必须位于实际Complete与观察时间之间，观察须在Complete后十秒以内；
查询延迟也计入预算。NativeScanWindow/Complete/Observed三条记录分别关联
提交前下界、实际Complete和观察，recorder记录command的boottime/monotonic/wall
边界，整体命令timeout30秒只用于防挂死，不代替发现期限。USB佐证另外核对
唯一成功Scan Complete及十秒内完整原始RX；当前verifier不回填历史缺字段记录。

实际one-shot CLI/private D-Bus新回归模拟提交6秒、Complete后8秒发现：总14秒
成功。旧已封存CLI在约10秒提前超时，保留FAIL；这不是把原期限改得更短。
纯Operation测试覆盖Status、各步骤失败、取消/旧intent、完整成功、重复回复及
后续fault，成功时间不被重写。C/Python同步12项原生接口和22结构ABI，包括
i386静态布局；新时间查询保持负errno及失败时输出不变。Kernel image #69
保留匹配config及原始96-case；各门禁实际结果冻结后另见issue进展记录。

以上均为开发支撑，真实WS73/固件/RF/物理拔插仍待验；真实七项0/7，完整
S0–S6、四设备两组和所有原整项issues保持OPEN，不以时间机制完成关闭整项。

### 中断与启动失败的可复现记录（部分成果）

所有 recorder slctl 路径现在共用先记录后启动的采集器，包括 daemon 身份查询
和退役选择。超时/KeyboardInterrupt 回收实际 CLI、保留输出与 child returncode，
启动错误记录 errno，意外采集错误同样回收进程；三种结束时间写入原记录。
终止 CLI 不撤销已提交无线操作，仍需逐设备停止。清理成功也不能把中断运行
改为成功或补齐连续轮次。持续存储故障无法保证证据落盘，必须另列失败。

9 项真实本地子进程测试、全部 66 项工具测试 PASS。旧精确源码反例复现中断
缺 exit、启动失败缺分类、总线查询中断未入记录，原失败日志保留。最终新客体
使用未变的 image #69、实际 slkd/slctl，合成 20+2 轮、同 daemon/owner 重插、
两次 TX-off 及原始 USB 佐证 PASS：2251 USB、177 空完成、22 匹配、32 独立
snoop 一致；152 个 selected 调用、2 次 daemon 查询和退役选择均记录 PID/退出
状态/三种时间。源码与当前 capsule/捕获/旧反例封存于本地
`.dev/command-failure-final-evidence.json`。本批未修改 Rust/Linux，未重跑全仓
Rust/clippy/96-case，也不宣称远端 CI 或实机通过。真实 WS73 仍未枚举，七项
0/7、板参 NOT_ASSERTED；四设备及完整 S0–S6 与全部原 issues 继续保留。

### 可用的真实 USB 透传入口与主机生命周期边界（部分成果）

源码与实际二进制核对发现，早先合成 QEMU 未编入 libusb，没有 usb-host 类型。
QEMU 9.2 的 usb-host 还会默认解绑内核驱动，并在打开失败/关闭/退出时 reset。
自建脚本现强制 --enable-libusb，并应用可重复、拒绝上下文漂移的两个 opt-out
属性补丁；默认 true 保留兼容。WS73 入口限定物理端口和 ffff:3733，显式关闭
kernel-driver-detach/host-reset/guest-reset/guest-resets-all，所有重加路径一致。
真实入口先封存 help introspection，缺设备类型或属性时 FAIL、不启动 VM。

依赖仅使用工作区解包、签名验证的 libusb1-devel 1.0.30 与同版本主机 runtime，
无 sudo/主机安装。实际生产函数体计数 mock 的7项、三处生命周期路由、补丁
新应用/重复/漂移拒绝及暂停/未attached QMP属性读回 PASS；它们不打开目标USB。
68工具/228harness通过。最终正确模型的新QEMU和未变#69内核：原96-case
1056 OK/0 FAIL/0 SKIP/3旧WARN，合成20+2轮/同daemon重插/TX-off、2251USB/
177空完成/22匹配/32独立snoop一致及C/Python门禁 PASS。首轮缓存模型缺zlp
属性失败和编译/依赖/链接/PCI probe失败记录保留，不覆盖为成功。

物理入口旧binary拒绝于缺usb-host，新最终binary通过预检后因WS73缺席FAIL，
均未启动VM。当前源码、source/实际binary/依赖/guest/捕获/失败hash封存于本地
`.dev/usb-host-boundary-final-evidence.json`。没有重跑Rust/clippy/远端CI或新内核
构建；真实ROM/重新枚举/外部占用竞争/RF/物理拔插仍待验，七项0/7、板参
NOT_ASSERTED、四设备与完整S0–S6及全部原issues OPEN。


### 重插状态交接：保留物理透传对象（部分成果）

上一版真实 launcher 在新USB地址出现、QEMU尚未同时附着/持有live fd时会
立即device_del/device_add。使用准确旧提交58ffa152的physical分支与模拟QMP
重现该删除；当前分支等待，6秒后仅对未占用对象发一次host-retry脉冲，仍不
更新已确认地址。两个launcher共用非阻塞Watcher与9属性预检；每端口20秒
权限/所有权期限，usbfs交接等待、外部驱动拒绝，失踪设备不删除对象。

QEMU生产setter在QMP/auto-open序列化下检查handle/attached：busy时无操作，
仅autoscan对象的errcount恢复0，由已有timer重试；不close/reset/detach，
不改变其他对象/global timer。生产7guard+5retry计数mock、两个补丁的fresh/
repeat/各自drift拒绝4项、实际暂停/未attached QMP脉冲读回false通过。16种
确定性交接测试含并发opener胜出、usbfs/fd/attach顺序、权限/所有权超时、
新地址重开预算与幸存端口，244harness/68工具通过。

实际新libusb QEMU+未变#69内核/compiled Rust：原96-case仍1056OK/0FAIL/
0SKIP/3旧WARN；合成20+2轮、同daemon重加/旧选择拒绝/幸存控制/两次TX-off，
2251USB/177空完成/22匹配/32独立snoop与8C/Python观察/4writer通过。
首次暂停probe受sandbox socket限制失败和预检fixture断言调整记录保留。
`.dev/usb-reattach-final-evidence.json`封存13相关源码、实际production/binary/
object/config/guest/raw捕获及失败hash；SDK/firmware/binary不上传。

真实入口9属性通过后因WS73缺席FAIL，未启动VM；真实ROM重新枚举、主机
绑定竞争、空口及物理拔插尚未验证。未重跑Rust/clippy/远端CI或重编内核。
七项仍0/7、board NOT_ASSERTED，四设备和完整S0–S6及所有原整项issues OPEN。


### 真实闭环证据必须关联主机 TX（部分成果）

原 verifier 只寻找成功 DLI Complete 与匹配 report，没有检查实际主机命令。
当前严格配对 endpoint-1 OUT S/C（USB身份+URB，完整提交/成功实际长度），
仅解码固定 TX header/HCC/SLE slot，不搜索padding；失败/提交错误/未完成/
短写/跨设备/重复pending拒绝。完成后URB复用正常。每步唯一TX→DLI Complete、
前一步Complete→下一TX均核对；IN与OUT callback可竞争，不错误假定回调先后。

17新增byte/顺序/URB/元数据/随机标识/幸存控制测试，去重85工具用例通过。
实际旧35a520 verifier对上一轮模型PCAP的五种坏证据仍接受support：去掉全
OUT、改发送随机标识、OUT失败、去掉metadata TX、去掉survivor TX；新工具
全部拒绝。原始PCAP、旧确切源码与五派生文件hash保留，这不是实机证据。

新工具封存客体在未变#69内核/libusb retry QEMU/compiled Rust上运行合成
20+2轮、同daemon/owner、两次TX-off与普通应用权限门禁PASS。客体与Host独立
重算佐证完全一致：189成功TX、154radio步骤、12metadata查询、4negative
scan/stop、2survivor scan步骤；2251USB/177空完成/22report匹配、32独立
snoop及8C/Python观察/4writer仍通过。每轮JSON保存发送/USB完成/设备回复
偏移、sequence和hash、两端注册查询及完整数据/地址/selected power检查。

`.dev/native-tx-final-evidence.json`冻结6相关源码、当前guest/捕获/佐证与
五反例来源；本批没有修改Linux/QEMU/Rust、重编内核、重跑原96-case、Rust/
clippy或远端CI，未变kernel/QEMU的原96证据明确引用上一轮。真实入口通过
工具预检后因无WS73 FAIL且未开VM；真实七项仍0/7，board NOT_ASSERTED，
ROM/重新枚举/物理拔插/RF和四设备两组待验，完整S0–S6及全部原issues OPEN。

### WS73 发送释放 Runtime 状态锁（部分成果）

原 native TX worker 在 owner 状态锁内等待阻塞 USB OUT，同设备 snapshot 与
RX 状态处理也会等待。当前先取得独立引用计数 transport，再释放状态锁发送；
注销仍先停止接纳、等待 worker 结束，然后关闭 Backend。C context/module
由最后一个引用释放，不通过设备 id 重新查找 transport。

Complete 可能先于 OUT callback：Host 保留回复和原始 BOOTTIME，但匹配 cookie
的 OUT 成功前不发布 terminal result、不释放在途命令。提前回复也不能屏蔽
超时；fault/invalidation 清掉 pending 后，迟到的发送成功不能复活旧 Host。
接受 Status 与独立 credit grant 可见，但不能当作命令完成。

新合成门禁确实把第一次 post-bootstrap ReadLocalFeatures OUT 延后两秒，
先通过 IN 交付 Complete，再经 QMP 状态和独立 UART 同步 guest。要求本设备
snapshot 小于200ms、另一设备真实 DLI 查询正常、100ms内保持 pending、OUT
完成后正确返回十字节 features；随后跑原移除/重加。这里初始状态是 SETUP，
要求状态不变，不把原始诊断查询当作 Ready。相同最终测试/模型：旧#69查询
阻塞约1.97秒 FAIL，新#71为0.004ms PASS。六新增 verdict 用例/250 harness
通过，九个标准/原生生命周期、recipe、故障、事件、发现和权限 gate 通过。
本轮重跑三控制器原96-case：1056OK、0FAIL/0SKIP、3条既存WARN。

新#71/延迟属性默认关闭的新QEMU/未改Rust实现：普通用户 slctl 合成20+2轮、
同slkd及owner、两次TX-off和重插复验 PASS；Host重算与guest相同，189成功TX、
172条命令链、2251USB/177空完成/22report/32独立snoop及8observe/4writer。
真实入口通过预检后因无WS73 FAIL，未开VM；实机七项仍0/7、board NOT_ASSERTED。
这批只迁移 WS73 发送；标准 USB/旧 Backend 和 native open 的锁迁移、真实
拔插/RF、四设备两组及全部原整项 issue 仍开放。未重跑远端CI/clippy。

`.dev/tx-unlock-final-evidence.json`保存56内核输入、新kernel/config/QEMU/guest/
捕获、旧反例及失败hash。首轮误用缺rust-src的stable proxy，自动配置删掉Rust，
预检拒绝于开VM前；已恢复原config并用固定工具链构建，失败不覆盖。初始
测试对SETUP/Status解释不准确的失败也保留；最终测试显式区分 Status 与 Complete。
复现见内核 `Documentation/networking/ws73-development.rst` 的
`--native-ws73 --native-ws73-tx-barrier`，编译显式选择具有matching rust-src的
`--rustc`。没有提前关闭整项issue或把开发支撑提升为真实北极星验收。

### 提前 Complete 后发送失败及在途拔插（部分成果）

新增三个独立真实驱动路径的合成门禁：先经 IN 交付成功 Complete、保留 OUT，
再返回 STALL、成功但短写一字节，或在 OUT 尚未完成时移除模型。普通成功
路径默认不变。USB worker/Host 的实现仍是上一批 #71，没有重编内核或改
用户态 Rust；模型、静态 C 测试和严格 verifier 是本批变化。

三种最终场景均 PASS：接受 Status 可见而 query 仍 pending；不会发布成功
features；只有目标 Runtime 注销，旧 raw result/admission/snapshot 返回
ENODEV，旧 event subscription HUP。失败 driver 两次读取保留首个 EPIPE /
EREMOTEIO，夹着幸存设备的18个实际 DLI 查询。拔插模式在 device_del 前
再次经 QMP 确认 OUT 仍 pending，必须留下实际 CANCEL、不能接受迟到成功。
从 pending barrier 后测得注销分别1849.309 / 1847.687 / 26.692ms。

重加后新 generation/address、正确十字节 features 与另一设备原 generation
均保持隔离；保留旧 fd 并按 monotonic 实测至少2200ms，跨过旧包原始 deadline
后再次检查旧 fd 不复活、幸存设备可查询、新查询仍属于新实例。相同最终
compiled unplug 测试对旧#69检测到1967.032ms阻塞并 FAIL。

九新增verifier用例/259 kernel harness通过；成功OUT race及原生发现、事件、
管理权限回归通过；新QEMU原96-case本轮1058OK/0FAIL/0SKIP/3既存WARN。
新客体普通应用合成20+2轮/同slkd及owner/TX-off/重插、189TX/172命令链、
2251USB/177空完成/22匹配/32独立snoop和8observe/4writer通过，Host/guest
佐证一致。真实入口仍无 WS73；真实七项0/7、board NOT_ASSERTED。合成取消
不能冒称物理拔插，模型成功不能冒称 RF；四设备两组及完整 S0–S6 和全部
原整项 issues 继续开放。未重跑Rust tests/clippy/远端CI。

本地 `.dev/tx-terminal-final-evidence.json`冻结本批源码、实际model/object/QEMU/
内核/guest/capture与旧反例hash；首次三场景运行与加强后的最终记录都保留。
复现：内核 `run_runtime_lifecycle.py --native-ws73` 加
`--native-ws73-tx-terminal out-error`、`short-out` 或 `unplug`，其余参数见
`Documentation/networking/ws73-development.rst`。

### 管理 ioctl 页故障与拔插并发（部分成果）

QUERY 在管理锁内生成整数快照，锁外复制用户内存；已经生成的旧 generation
快照可返回，但不代表控制权限。退役关闭 admission 后先通知 event/snoop，
再等待管理事务和 native lifecycle。ACQUIRE 复制候选 token 后，在 admission
锁内重查存活并提交；若期间退役则返回 ENODEV，失败 ioctl 复制出的候选
token 必须丢弃，不算获得租约。

新增隔离 guest 的 `run_native_open_test.py --userfault`：通过实际 userfaultfd
WP 停住内核 ioctl copyout，核对地址、WRITE/WP 和线程；未解除故障时要求
独立查询及已注册的 event/snoop epoll 继续工作。解除后检查旧快照/ENODEV、
恰好一次 get/put/close、旧 fd、新 generation/首个租约、幸存模型 DLI 和模块
卸载。仅在测试 guest 启用 USERFAULTFD，由 guest root 运行夹具，不改变
普通应用或主机权限。

同配置旧 #76 阻塞第二查询 200.668ms、退役通知超时并错误返回成功租约；
新 #77 查询 1.088ms、两场景通知 0.096/0.101ms、迟到申请 ENODEV。两版 guest
executable/夹具 C object 相同，模块各自匹配内核；负例清理并卸载成功。
277 verifier、Werror C、四个 open 场景、十二 runtime gates、原96项
（1059OK/0FAIL/0SKIP/3既存WARN）及普通用户 slctl 合成20+2轮通过。
同slkd/bus、TX-off、幸存设备、重插和独立USB捕获证据保存在本地
`.dev/rpc-fault-final-evidence.json`；Rust companion/QEMU实现未变。

真实入口仍未枚举到 WS73，物理 guest 未启动，实机七项仍 **0/7**、board
**NOT_ASSERTED**。第一北极星仍是普通用户选择两只真实 WS73 完成随机广播、
10秒内数据/地址/RSSI匹配、20轮互换及同slkd拔插恢复，随后四设备两组并行。
完整方案及原整项 issues 保持开放；未宣称远端CI或新Rust tests/clippy通过。

### 重插后的实机启动根因与恢复扩展（部分成果）

本次四只ffff:3733恢复可访问后，实机依次暴露并验证三项修复：固定端口
重枚举时QEMU保留旧handle；BSLE ACK的32字节allocation只有8字节有效
tag/status；WS73 SDK的0406必须空参数。修复后的实机四个元数据查询全部
成功、真实地址00:01:09:30:CE:85、Runtime id0/gen1处于Setup。随后初始化
ADV_STOP返回原始1e（未知广播实例），slkd不误报Ready；须补广播实例创建
前置步骤。最后一只仍未启动，不宣称双设备或20轮真实RF通过。主机仍可
见全部四只，QEMU关闭的NO_DEVICE不能算主机设备消失。

SDK与libws73-usb交叉核验见[来源说明](NEARLINK_HOST_REFERENCE.md)。追加的
“不依赖人工拔插”验收及单设备预算/退避/状态/日志、原生Linux与QEMU、
单/多设备矩阵见[恢复设计](WS73_RECOVERY.md)。自动恢复状态机尚未实现；
历史实际消失的根因仍未查明；完整S0–S6与原整项issues全部保持开放。

冻结kernel #81通过直接生产codec：BSLE3572、DLI115104 checks；282 verifier、
新增原生link事件观察门禁、12 runtime gates及原96项1058OK/0FAIL/0SKIP/
3既存WARN通过。原生link事件测试保留完整前缀/扩展、未知status/role/type，
覆盖双订阅、overflow、EFAULT重试与退役，不等于真实连接/SSAP实现。
用户工具86tests、slkconfig9tests及普通用户合成20+2轮/同slkd/bus/TX-off/
幸存与重加通过；合成模型不是实机空口证据。物理失败抓包与诊断封存，
board仍NOT_ASSERTED、真实北极星追加恢复后0/8。未宣称远端CI、原生主机
驱动部署或完整自动恢复通过。

### 111固件与显式广播实例OFF初始化（部分成果）

根据用户提供版本，将参考实机基线切到combined-1.10.111；旧SDK/us与110
逐字节相同，所有历史实测保持标为110。111完整性验证/拆分与receipt已
完成，实机下载及BSLE通过，第一只在buffer回复tag=a1处EPROTO，第二只
未接入，抓包271packets/零drops。SDK SLE RX与libws73都按service/queue
路由、不要求subtype0；修正后五帧实际抓包生产C离线复核成功，尚未重跑
实机完整启动。全部设备现warm，下一阶段解决每设备软件恢复。

新operation5显式配置广播实例后等待OFF成功Complete，之后SCAN_STOP；
不发enable，不吞原始1e，取消的配置Complete不能确认OFF。新模型支持
全新广播handle及非零SLE subtype，不假设stop总成功。kernel#84与用户态
18库/64守护测试、10生产operation状态测试、450548 discovery/115776 DLI
checks、93工具测试通过；clippy执行成功但有既存warnings，不宣称零警告。
新普通用户合成20+2轮与同slkd/bus、独立capture重算及相关四条原生/标准
回归另存`.dev/111-final-*`。原#81原96项证据仍保留，不倒填成#84全量测试。
operation5实机成功OFF、双设备Ready、真实20轮和自动恢复均待验收，完整
S0–S6、所有原整项issue及新增不依赖人工拔插要求保持开放。

### 每设备暖启动与真实初始20轮（kernel90，部分验收）

固件基线采用用户指定libws73-usb combined-1.10.111，制作方式保持
`cat ws73.bin wifi_cali.bin btc_cali.bin > combined-<版本>.bin`，各段64字节
hash头保留。暖启动不上传固件，不能仅凭准备目录将旧设备标成111。

已实现一次有界暖启动采纳：仅初始BSP_READY超时、尚未发布Runtime时，
每probe最多一次；先最多64包/1000ms排空旧输入，再发送SDK action30 CLOSE，
等待新type4/message3关闭ACK，重新PM/customize、OPEN29/BOOT_FINISH及四项
DLI查询。各阶段有截止时间和独立失败日志，`warm_recovery`导出attempts/
limit/cause/result/start。旧BOOT、OPEN ACK及排空前CLOSE不能代替新关闭回执，
panic/断开/超限均失败；不重置hub、不detach、不主动操作其他owner。
这是启动恢复切片，不是持久端口预算、运行期故障恢复或设备消失根因闭环。

真实111暖设备已验证关闭/重新启动/四项查询及广播配置/OFF成功。扫描初始
OFF返回原始0b；补参数1001成功Complete后OFF仍0b，否定仅缺参数假设。
新typed operation6 SCAN_INITIALIZE_OFF执行**被动参数 → ON → OFF**，三个
成功Complete后才确认OFF/Ready；短暂开启接收，无主动scan request。只接受
active=0/duplicates=0，必须先有广播OFF且无并行广播/扫描事务。中间ON在
发送时使扫描状态未知，取消/迟到ON不能建立Ready，失败最终OFF仍保持未知；
含enable的旧recipe不能在被替代后发送。operation5仍不启用广播。

真实`.dev/ws73-real-scan-probe`两只独立Ready、20轮交换角色成功，但物理
拔出1-2.1.4后幸存1-2.1.3的registration由slk1_g2变为slk0_g3，判FAIL。
等待人工操作超过会话时限，capture无最终丢包统计，不能冒充完整证据。
slkd日志保留两次退役和重新注册；QEMU/内核/USB供电归因尚未完成。

独立重跑`.dev/ws73-real-initial20`：1-2.1.1当轮冷上传111，1-2.1.3保留110，
地址分别00:01:09:32:54:CD和00:01:09:30:CE:85；两个不同Runtime generation
均Ready。普通UID1000、全部capabilities=0，通过slctl交换角色20轮，随机标识
均不同，数据/地址/RSSI匹配，成功Scan Complete后298–615ms内观测。封存
1161 USB packets、zero kernel drops；独立执行生产corroborator原20轮块，
逐轮匹配实际TX/Complete/完整RX/所有权/时间/marker/四元信息查询，输出
`.dev/physical-initial20-evidence.json` INITIAL_20_RX_CORROBORATED。已验证2秒
TX-off负例。此轮有意不执行物理拔出，完整脚本在EOF及重复idle扫描OFF处
保留FAIL，不伪造replacement、cleanup或整体PASS。板级功率仍NOT_ASSERTED。

北极星只确认第1/2/3/6项（独立Ready、新数据10秒内、20轮角色交换、普通应用），
**4/8部分验收**；拔出隔离、同slkd重插、完整可复现验收包和自动恢复未完成。
所有整项issues/PR草稿及S0–S6保持OPEN，四设备两组尚待扩展。

kernel90验证：6078 BSLE/451067 discovery/115776既有DLI checks，11生产operation
和15 Host plan tests；19库/64slkd tests，96工具tests，282内核脚本tests通过。
四条WS73 discovery/management及标准Runtime/recipes回归PASS。clippy退出0，
42既有slkd warnings保留。此前kernel85/87合成20+2 receipts独立保存，不能
倒填成kernel90完整测试。新增idle-OFF=0b模型用于暴露管理清理前置条件。

测试工具清理可重新读取同一generation、同一request的已成功OFF及当前OFF
状态，确认无中间on/off，再保留其原始OFF命令关联；无需重复发送已idle的
OFF。不把新0b改成功，错误/未知/旧代次均拒绝；真实旧失败记录保持。管理
lease撤销及C/Python writer在此固件语义下的门禁继续独立验证。

最新idle模型门禁：kernel90合成普通用户20+2轮、同slkd/bus与热重加控制阶段
通过，独立复核2427 packets/191TX/179empty及4条保留OFF查询关联；整体
`.dev/scan-probe-idle-support` **FAIL**，因为随后C binding writer对已经OFF的
扫描器再次发送OFF，被模型返回0b。该失败未隐藏，管理撤销/绑定writer正确
前置条件继续作为依赖处理；不以此宣称完整C/Python writer或发布矩阵通过。


### 管理释放保留已确认 OFF（kernel92，合成门禁通过）

管理撤销曾对两个射频域都发送 STOP；扫描已经 OFF 时真实111和严格模型返回
原始0b，不能改成成功。现在仅内部撤销的一步 STOP、匹配本次租约撤销 cookie、
同一 owner 已确认 OFF，才保留该状态。决定发生在前一个线上的请求消耗之后；
未知/ON、取消的 enable、公有请求和多步 recipe 仍走正常调度。保留 OFF 不发送
USB OUT，不伪造 Complete、credits、时钟或公有请求结果；另一个域仍须成功停止。
故障或超时不能绕过，两个域均完成后才允许后继管理租约。

C binding writer 先真实配置并开启扫描，再验证公有 STOP；随后重新开启扫描，
在广播已 OFF、扫描 ON 时释放管理租约。USB 抓包要求实际扫描 OFF 成功，释放
窗口内无重复广播 OFF，同 generation 回到 Ready。management 原生门禁也使用
被动扫描初始化，并启用 idle-scan-stop=0b 模型；失败/取消/超时负例保留。

冻结 kernel92 和56源文件、QEMU及6编译输入后，`.dev/retained-off-support`
完整 SUPPORT_PASS：普通用户20+2轮、合成拔插、同 slkd/bus、暖启动、empty bulk
与 C/Python 绑定均通过；2557 USB packets、zero capture drops、192 empty
completions，22条独立控制抓包关联。12条 Runtime gates 全部 PASS；16 Host-plan、
11 operation、96用户工具、282内核脚本 tests 通过。旧 kernel90 整体失败证据保留。

这是合成开发门禁的修复；真实20轮证据仍是先前 kernel90 的111/110混合版本。
北极星仍4/8，物理拔出导致幸存 generation 改变的根因、物理重插、不依赖人工
拔插的恢复、原生主机与QEMU对照、四设备两组及完整S0–S6仍开放。本次主机
只枚举到1-2.1.1/.2/.3；.4仍未出现，不能把用户已插回解释为枚举恢复成功。


### 三层生命周期诊断与 kernel92 实机初始阶段

开发 runner 为真实 passthrough 自动记录 `host-inventory.jsonl`：初始、变化和
结束时的全部 WS73（包括未选择的设备）及 wall/monotonic 时间。QEMU 开启十个
显式白名单事件和时间戳，记录 open/close、端口 attach/detach、接口 claim/release、
传输完成状态/长度及 reset；不记录 payload，不改变 USB 权限或恢复行为。
日志写入独立文件并纳入 manifest SHA256；缺少事件则拒绝启动诊断测试。
guest console 使用 loglevel6，以保留异常结束时的生命周期线索。98工具测试通过。

旧隔离失败抓包显示：拔出侧在13:10:33.225190 UTC出现IN -71，幸存侧在
13:10:35.018964 UTC出现IN -108，随后以新generation注册。该观察将问题缩小到
USB/内核生命周期，但不能据此断言主机、QEMU或驱动的触发根因；原生主机对照
与受控单owner故障注入仍是下一依赖。

kernel92真实初始20轮再次逐轮独立复核：UID1000/capabilities0，111/110保留固件，
299–616ms匹配新数据、地址与RSSI；1019USB包、zero drops，两只最终
STOP_CONFIRMED。capture SHA256
`a23c4d502ca60ca5d1adace7f476f79118a050117180a9982be3d7b6e5d287d8`。
本地 `.dev/physical-retained-off-initial20-evidence.json` 仅证明初始阶段；未执行
物理拔插，完整control在确认拔出时EOF，整体environment也保留FAIL，不能升格
为完整北极星通过。北极星仍4/8；设备.4仍缺失、根因与自动恢复issues继续开放。


### 真实 RF / QMP 单 owner 断开对照（kernel92）

新增可复现命令：在当前源码准备的隔离环境执行
`ws73_target.py run --prepared <目录> --output <新目录> --ports <端口A> <端口B> --qmp-hotplug`。
两只均是真实 WS73，普通 UID1000/capabilities0 使用 slctl；主机物理连接保持，
仅 QMP 移除并在同固定 guest 端口重新加入 owner0。记录独立 scope、
`hotplug_method=QMP_DEVICE_DEL_ADD` 和 `physical_acceptance=false`。
独立抓包验证器拒绝把该结果作为物理拔插验收，即使只改 scope/status。
合成负例分别验证方法边界与 USB 描述符边界；本次校验器曾期待旧错误文本而
使整体合成 FAIL，日志保留，修复后重跑全套，不修改失败 receipt。

最终冻结工具实机 PASSTHROUGH_SUPPORT_PASS：20初始+2重接轮，每轮新随机
标识、数据、地址、RSSI及实际成功 Complete 逐条 USB 关联，308–613ms。
1295包、zero drops，同 slkd PID97/start_ticks76及同 D-Bus owner；幸存
设备 generation2 不变，被移除的 generation1 失效，重接 generation3。
2秒 TX-off 负例与两只最终 STOP_CONFIRMED 通过。主机三只始终保留原 USB
地址，未选中的1-2.1.2保持无driver接管。QMP恰好执行初始两次add、一只del、
同属性一次add；guest-reset/guest-resets-all/host-reset/kernel-driver-detach均false，
时间戳 trace 无 usb_host_reset。

capture SHA256 `ecccbc19a3333c94cb51728db69f9dcfb58d03e669d92ee4f2aef4b7f4b44c7d`；本地`.dev/passthrough-control-evidence.json`。
100工具/282内核脚本 tests 通过，既有 kernel92 的12条 Runtime gates不倒填
成新内核构建；最终严格合成门禁也完整 SUPPORT_PASS：2557包、zero drops、
192 empty completions、22条独立控制证明及 C/Python 绑定、same daemon/bus通过。
实机固件仍111/110保留版本，board NOT_ASSERTED。

结论范围：静止射频域下 QMP guest 退出可单 owner 隔离，未复现旧物理拔出时
幸存设备 IN -108 / generation 改变。**并未定位该物理根因，也不是设备消失后
自主恢复。** 北极星仍4/8，物理隔离/重插、完整物理复现包、原生主机对照、
有限自动恢复和四设备两组及完整S0–S6继续开放；.4端口仍缺失。
