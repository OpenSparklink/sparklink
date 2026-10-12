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
