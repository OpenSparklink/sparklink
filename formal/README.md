# SparkLink 验证边界与可复现入口

本目录补充 ADR 0002 和完整 S0–S6。形式化验证与真实数据面纵向开发并行，
只将本次改动相关的不变量作为门禁。VM-only 适用于实验驱动和真实设备 I/O；
这些纯模型/编译工具在主机运行，不安装内核、不加载模块、不操作 WS73。

本机使用 `/usr/local/bin` 中的 TLC、herd7、CBMC/goto 工具、Ghidra、
Tamarin/ProVerif/Maude 及 `~/.cargo/bin/cargo-kani`。
`/opt/opensparklink-verification-tools-20261013/system-smoke-tests.json` 的 13 项
检查仅证明安装可用，不是任何 SparkLink 性质的证明。Ghidra 用于核对 SDK111
封装/固件行为；Tamarin/ProVerif 随 S5 安全/Bond 接入，不由数据面模型继承资格。

```sh
python3 tools/run_formal.py --output ../.dev/formal-qualification-NEW
# 全部生产 credit harness，逐项最多 600 秒；超时记作未证明：
python3 tools/run_formal.py --credit-all --budget-seconds 600 \
  --output ../.dev/formal-credit-qualification-NEW
```

输出目录必须是新的目录。TLC 自身会初始化本机临时监听端口；受限沙箱拒绝时，
原始失败记录为失败，工具运行需要允许本机监听。工具不向设备或网络发送数据。
报告保存源码/模型/配置 hash、仓库 head 和 worktree、工具版本、准确命令、
输入预算、终态、原始输出 hash。需要连同本文件的范围和后续 VM 回归一起审阅。
`unsupported`、超时、未完成展开、缺少预期终态均为 `NOT_PROVEN`。
进程退出 0 也不能覆盖这些诊断。预计反例单独记为风险，不能计成被检查性质通过。
runner 本身只是记录入口；选中的检查存在 NOT_PROVEN 时退出2，报告仍保留。

| 检查 | 实际范围及源码映射 | 没有证明的范围 |
|---|---|---|
| channel/progress_cbmc.c | 直接包含生产 `sle_channel_state.h`，所有 unsigned maximum/MTU、事件、expired 输入；构造及合法表示状态的归纳保持；OPEN 必须三步骤完整，原期限过期则失败，FAILED/CLOSED 不复活。CBMC 6.11.0，unwind20、完整展开断言、边界/指针/有符号及无符号溢出检查 | jiffies 推进、worker 调度公平性、USB、整个 socket/VFS。expired 是实际 `sl_progress_event` 在锁内计算的输入，不假设硬件必回复 |
| credit/src/main.rs | 路径包含实际 `sle_data_credit.rs`，验证 harness 就在生产模块 `cfg(kani)` 内。16 debt slots，任意 u16 maximum/u8 capacity/u16 outstanding/u64 lifetime/12-bit 合法 debt handle，实际 reserve/complete/transport_failed；unwind17。只假设归纳表示不变量，不假设 NOCP 可靠/唯一/及时 | 当前 Kani 编译报告 unsupported，按用户规则记未证明；不得因初始 harness 显示 SUCCESSFUL 改为 PASS。两个 Rust ledger 不共享值的性质不等于整个 Runtime 隔离；命令/data 独立另由生产 Native 回归验证 |
| lkmm/ChannelSnapshot | 使用当前 Linux `tools/memory-model`，映射 socket `state_lock` 的发布和完整快照；看到 OPEN 时看到相应 MTU。故意无锁的 Weak 应允许坏结果 | 完整 socket 内存安全、所有能力组合、丢失唤醒、USB 票据、VM KCSAN/lockdep。spin_lock_bh 的内存序抽象为 spin_lock，软中断屏蔽本身不在此模型中 |
| lkmm/ChannelCloseAdmission | 同一锁保护 CLOSED 发布和最终软件准入；先看见 CLOSED 不能又看到 OPEN | 不证明已检查 lifetime 到 USB 提交的窗口；该风险保持开放 |
| lifecycle/ManagedLifetime | **抽象契约模型，未建立实现 refinement 证明**。两个 controller，两代 generation，每代一个作者请求，有界队列1，fd引用0..2。映射 command queue 的 push/pop/remove_cookie、Managed revoke/drain 与 generation 注册身份。Revoke 为显式 release，或 refs=1 时最后关闭；refs=2 的普通 close 只做 CloseDup。在途物理义务独立于作者终态；完成不覆盖 Cancelled；Free 必须无在途/清理/队列 | 不冒充真实深度64队列的证明。未涵盖部分初始化所有步骤、通道/fd分离迁移、设备故障状态、锁/实际异步回调和工作引用/UAF。允许回复永久缺失，不靠过强“必回复”假设宣布恢复或终止通过。当前检查为 safety，不是全系统 liveness |
| lifecycle/NOCPReuse | 风险模型允许 handle/count 没有身份：旧完成清掉旧 debt → handle复用新life → 旧重复完成抵扣新debt。四步反例必须保留，指导受控VM/实际生产 ledger 回归 | 不是已发生实机串包或固件重复事件的证据；没有可靠排空屏障/完成硬件证据前不宣布复用安全 |

当前 CBMC 的原始检查为 131 项 SUCCESS；锁 litmus 为 Never，弱对照为 Sometimes；
Managed 有限模型穷尽 784 个状态。结果严格绑定报告中的源码 hash，不能套用后续提交。
NOCP 风险反例应转换为实际 ledger 回归，同时继续验证固件完成行为及复用屏障。
已有生产 Native 回归覆盖真实函数体（USB/注册/锁依赖为 fixture）：20 项通过，
其中一项直接用生产 ledger 重现 NOCP 复用风险，保留风险并非证明该策略安全；
新增 C selftest 重现“能力已收到但本端响应未提交，期限仍须终结”的情况，并用
ASan/UBSan 执行。模型通过不代替 VM 实机、对端校验回复或空口/USB/HCC 证据。

下一批：生产有界队列取消的 Kani、generation/lifetime 票据模型与实现线性化点、
Session/Channel/Binding 的 dup/关闭/worker 引用模型、等待者唤醒 litmus，
以及 VM KCSAN/lockdep。与 249/250、各层253/254/255、长包/PB/SAR、credit
耗尽/满队列/断链矩阵并行。恢复自然故障根因、非人工自动恢复及未完成整项 issues
保持开放；历史40轮资格、首次启动panic和最后回复关闭丢弃证据均保留。

## 实际 ACB 提交点整改的限定验证

`--ticket-only`检查TxCommitWithdrawal与故意弱对照：实际目标为Host锁内身份验证、
credit预留与一次prepared atomic submit；Down、data撤销和fault在Host下发布，
controller退休由同次提交仍持有的scheduling gate阻挡。Never/Sometimes只证明
CPU锁序抽象；不证明C/Rust refinement、HCD内部、callback UAF、Grant epoch或NOCP复用。

`--credit-rollback-only`直接选择生产DataCredits的新增Kani harness：合法初态中reserve
成功、锁内已准备submit返回非零（从未queued）后，unsubmitted恢复准确原ledger。
假设是实际数据锁期间不发生其他ledger转换及LinuxURB未入队契约；没有假设NOCP
可靠、唯一或及时。工具unsupported/超时仍NOT_PROVEN，不用离线测试改标证明。

WS73实际C prepare/atomic-submit/completion/finite-wait/kill/join函数及wire codec
由`run_native_ticket_driver.py`以明确USB/锁/时钟依赖注入编译，ASan/UBSan/LSan覆盖
十类故障；不是硬件恢复或对端收到资格。Native25、Host49与Managed48调用实际生产
代码。Host撤销布尔是目前提交屏障，不能冒充SocketBinding的完整Grant epoch。
已提交/未知debt继续保留；原NOCP四步反例继续开放。真实VM按准确新提交重新验证。

## Runtime Session 与 Binding 迁移

--binding-only直接包含生产sle_channel_state.h的attach/retire/busy/space转换，检查构造和
合法表示状态归纳不变量；不是另一份实现。retired不可重绑定，busy在退休时保留至完成。
--session-only是抽象契约：两controller、各两physical lifetime，fd alias0..2，pending/
running work各0..1，Runtime table与draining owner ref分开。最后fd不重启CMTC，dup
不提前释放，join后才放owner ref。只检查有限safety，不证明C/Rust/VFS/kref refinement、
完整generation/Grant/NOCP/硬件或liveness。Session IRQ-save避免Host提交/RX IRQ反转。
实际Rust session表与C route/submit-consent由selftests编译，依赖明确；真实VM另验收。

## Managed lease authority

`--grant-only`直接编译生产`sle_grant.rs`，检查构造和所有合法u64状态的一步归纳、
撤销后successor不能复活旧epoch。仅pure authority性质；不证明Host锁/Managed复制提交、
C socket/VFS、blocked RX撤销、安全降级、NOCP或硬件。实际Host/Session/USB ticket锁下
准入/提交与旧debt保留由源码回归及VM门禁另验。非零安全要求和非TX|RX组合目前明确拒绝。
旧完整credit Kani的unsupported状态不因这两个新harness通过而升级。

## RX dequeue 与授权撤销

`--rx-only`检查RX准入/撤销Host锁CPU抽象及故意弱对照。准入点是队列unlink或
PEEK的skb引用；后续用户复制在锁外，已准入复制可完成。Never/Sometimes不证明
完整C/Rust/VFS/queue引用、等待唤醒、硬件或自然恢复。actual sl_recvmsg/sl_take在
selftest直接编译，Host授权、等待/锁/复制是显式依赖；含撤销后到包、零包/PEEK/TRUNC、
EFAULT/信号/timeout、unknown EAGAIN不得进入无tail等待。VM受控撤销仍单独验收。

## Immutable SocketBinding Grant

`--fd-grant-only`直接包含生产`sle_channel_grant.h`，任意u64/u32 scope/掩码验证
未mint状态拒绝、constructor接受范围及失败不改变旧值、全身份一致与TX/RX方向约束。
protected security目前不能mint。范围仅pure predicate/constructor；不是Host epoch、
C/VFS/kref refinement或可信安全状态/降级证明。实际C sl_permits/sl_tx_access、准入、
USB consent、RX分流/取包/poll由source selftest编译。真实方向与原数据保持验收独立。

Backend 注册整改的独立门禁：

```sh
python3 tools/run_formal.py --backend-only --budget-seconds 60 --output ../.dev/formal-backend-NEW
```

`formal/backend/descriptor_cbmc.c`直接包含生产 `sparklink_backend_validate`，
使用真实内部类型。任意 u32 版本/大小/bus/能力/方言、u16 缓冲长度、u8 数量
及每个回调的存在/缺失均进入状态空间；指针只允许 NULL 或有效且调用期间不变的
provider 对象。验证接受时版本/能力与回调、有限缓冲一致及明确拒绝。
它不执行 provider callback，不证明模块/上下文引用、分配、Runtime 发布/退休、
并发或硬件行为。TEST bus 只是显式测试 provider 标签，不代表已实现 VirtualBackend。
38 项实际验证函数回归在 Linux selftests 的 `sparklink_backend_test.c`；
工具报告不继承真实 WS73 数据资格。

注册入口的内存访问顺序由实际C函数回归补充：

```sh
python3 tools/backend_registration_contract.py --kernel ../linux
```

直接抽取生产 `sparklink_backend_register` 函数与transport结构，采用clang
ASan/UBSan，11个拒绝用例使用不可访问ops哨兵验证未知布局/bus/方言/能力不跟随指针，
拒绝不改变identity、不分配、不持引用或执行回调。分配/module/Rust调用为依赖fixture，
不能作为真实内核引用或并发退出证明。版本不符先拒绝，避免复制不同布局的尾部。

Runtime 共同入口与退休顺序的改动门禁：

```sh
python3 tools/run_formal.py --ingress-only --budget-seconds 60 --output ../.dev/formal-ingress-NEW
python3 ../linux/tools/testing/selftests/sparklink/run_runtime_ingress.py
```

LKMM映射生产 `publish_runtime` 的schedule_gate→routes嵌套，以及invalidate先关闭gate
后 exact-owner unpublish。单一有效identity、初始无route、一次发布/退休；弱对照刻意释放
gate后才发布，应产生反例。模型不是Rust Arc、IRQ嵌套、复用、workqueue、callback或硬件
证明。生产函数9项回归用std Mutex/Arc/queue/Host依赖fixture和显式rank/反序释放检查，保留各自明确边界。

共同RX与软件命令入口统一采用Host→gate（RX随后取ingress），与数据提交
Host→data→gate一致。实际函数fixture检查队列准入/保留回复/退休拒绝以及
schedule/kick发生时已无锁；前版RX函数rank负对照应检出gate→Host反转。
这不是实际内核lockdep/KCSAN证明，也未观察到实机死锁；相应VM调试内核门禁仍开放。

周期health observer也按Host→gate采样。生产9项回归包含实际Native health函数
（只归一化extern签名/模块路径），Setup/Ready/radio/fault/retired/旧generation/同行
均检查；Host观察方法仍为依赖fixture，不能作为真实故障根因或IRQ/lockdep证明。

标准USB pending allocator门禁：

```sh
python3 tools/run_formal.py --usb-registry-only --budget-seconds 60 --output ../.dev/formal-usb-registry-NEW
python3 ../linux/tools/testing/selftests/sparklink/run_usb_registration.py
```

Kani crate的build.rs/generate.py直接抽取生产SleDev构造器、register_pending和registry
初始化，保持状态转换体；仅info/stats/log为依赖类型/无状态fixture。初态与任意u16 bitmap、
u64 next generation>=2的一步转换；slot与bitmap一致，既有generation设next-1是
允许旧generation重复的宽松状态集合，不证明既有全局唯一性。cap满/generation溢出
失败闭合、占用槽不变、新槽只有SETUP。实际registry并发、两阶段撤销、listener/callback
和真实硬件不在证明范围。unsupported警告即未证明，成功raw solver也不覆盖该状态。
13项实际production-body回归保留Ready/open准入、错误清理和精确detach等独立范围。

## Common Backend reservation/publication

`--backend-install-only` checks an abstract finite model: two slots, two candidate
builders, three globally increasing generations. Snapshot, construction success/failure,
retirement, reuse, competing installation and reservation cancellation may interleave.
Registry actions are atomic; no fairness/liveness is claimed, terminal states are
allowed and deadlock checking is intentionally off. `LiveMetadataCurrent` checks
that published metadata belongs to the current reserved generation. A deliberately
weak final generation guard must produce its stale-publication counterexample.

Mapping: `reserve_backend_identity/register_pending` → Reserve;
`install_backend_runtime` snapshot and out-of-registry constructor → Snapshot/Construct;
final identity/retiring/slot checks → Publish/Reject; `cancel_backend_reservation` →
Cancel; `sle_detach_device` → BeginRetire/FinishRetire. FinishRetire abstracts a
completed join; it does not prove C callbacks or references are joined. No allocator,
module/IRQ/VFS/callback, actual metadata-query/Ready, credit or physical behavior is
modeled, and C/Rust refinement is not proved. Actual production function tests in
`run_backend_install.py` cover constructor failure, retire/reuse, competing publish,
subsystem removal and out-of-registry destructor; these remain dependency regressions.
The weak trace corresponds to the actual stale-generation/reuse regression.

## 用户态 SSAP ExchangeInfo codec

`cargo kani --manifest-path formal/ssap_exchange/Cargo.toml` 直接包含生产
`crates/slk-protocol/src/ssap/exchange.rs`，不维护验证副本。符号输入覆盖原始长度
0–11、完整u16 MTU、任意 typed 字段与输出容量0–11，unwind16。两个 harness
求解完成，但 Kani0.68.0 输出 caller_location／foreign-function unsupported，
按项目门禁记为**未证明**，不得只摘取 SUCCESSFUL。无并发／传输／协商成功证明，
不构成 SSAP 实机互通。[准确源码与报告](../docs/evidence/ssap-exchange-codec-progress-20261014.json)。

可复现 fail-closed 入口：`python3 formal/ssap_exchange/check.py --output "$NEW_REPORT_DIR"`。
它只运行离线Kani，在新目录保存原log与hash；timeout、unsupported、未完整展开或
源码检查期间变化均退出非零。本次实际返回1／NOT_PROVEN，不能把该退出记录为工具门禁PASS。
