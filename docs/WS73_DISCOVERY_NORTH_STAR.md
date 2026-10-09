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
目前该硬件 harness 和动态 adapter 命令尚未实现，此文不是可执行测试。

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
