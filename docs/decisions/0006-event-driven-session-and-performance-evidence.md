# ADR 0006：事件驱动 Session 与性能证据

状态：采用（2026-10-16）；调度改造、性能资格和 USB 优化尚未实现或验收。

## 范围与依据

保留 drivers／net／slkd、唯一物理 Session、credit／Ticket／Grant 与完整 S0–S6、
19 WP、10 FV、12 DG。UserHost 为低优先级规划。性能与 Agent、SSAP、多通道及
四设备并行；只门禁本批相关性质，不等待控制竞争全集。唯一排期仍是
[实施计划](../../project/implementation-plan.md#性能工作批次与退出条件)。

复核 K a474a8503637／U 44108b237b8c：sl_schedule 仍使用 10 ms delayed work，
Session 周期处理 RX／协商／TX，sendmsg 入队不直接唤醒；运行期 bulk RX 已异步。
编译资格 K400bd68／U25df09b 与两份未提交四设备工具改动分别保留。
历史 8 次 61 字节 38–44 ms 是功能样本，不能证明当前性能或全部延迟原因。

## 通知与原期限定时分离

目标：有可执行工作立即调度，无工作休眠。保留每连接唯一、串行 Session worker，
由软件入队、当前身份的可消费 RX、实际 NOCP 恢复 data credit、协商/关闭/撤权、
Down/退休及原期限到期触发。命令 credit、data credit、peer 流控、软件预算独立。
通知只提示重查生产状态，不授予 Ready、credit、Grant 或发送资格。

实现前固定以下契约，并由生产代码与相关模型核对：

- Runtime 注册项携带 controller/generation/lifetime 与受保护的 Session 引用；
  通知先在注册锁内取得临时引用，释放锁后只设置待办并排队，不在 USB callback
  或原子上下文执行可睡眠 Session 工作。
- 沿用 Host→data→gate→Session 的准入顺序；通知注册锁不能形成反向依赖。
  具体注册锁、引用和调用图须随实现提交映射，不能把此设计视为已验证锁序。
- 单一待办序号/位图在与 worker 休眠决定相同的同步域中更新。worker 清理通知、
  检查可前进状态并决定休眠；退出前重检，事件到达运行/退出窗口必须再次调度。
  重复通知合并。queue 返回已排队与真正失败区分；失败不得遗留虚假 pending。
- 即时工作与独立 deadline timer 分开；timer 指向最早原协商、发送、重组或清理期限，
  中间片、重复通知及重排队不延长原期限。禁止把 10 ms 改为 0 后无限自排队。
- 停止顺序：身份失效并停止准入→撤销通知注册→排空通知临时引用→同步取消 timer／
  join worker（不持 worker 需要的锁）→清理物理义务→最终释放。未 drain 不 Free。
  与部分初始化回滚、在途提交、callback 排空同批验证；另一 controller 不受影响。

每轮有包数、字节数和执行时间预算。仍有可执行工作且耗尽预算才重排；无 credit
等待真实事件。通道轮转、防饥饿及 PB 分片连续性兼顾，不能在同连接 PDU 中错误交错。
预算具体数值先作为可测实现参数，不冒充硬件最优值或实时调度保证。

## 发送及 USB 分期

先测旧路径，再消除轮询等待，再有界连续推进。每次实际提交仍经过原 Grant、
generation/lifetime、原期限与 Ticket 的原子门禁。USB 成功不归还协议 credit；
确定未提交和不确定失败分别记账，作者取消不抹去物理义务。

TX 预分配、多个在途 URB、HCC 聚合分别作为测量后的优化；需要独立的有限资源、
缓冲区/callback 所有权、取消/drain、顺序、短包尾延迟与公平性门禁，默认不启用。

WS73 当前一只 bulk RX URB：completion 内解析 aggregate／生产 ingress，随后重新
submit；notification URB 是另一用途，不能算第二个并行 bulk RX。首先记录 completion
到重提交、解析/ingress/锁竞争各段耗时、完成长度、突发流量与重提交失败，比较完整
追踪的扰动。空窗不预设为瓶颈。只有测量支持才缩短 callback 或引入有界多 RX URB。
多 URB 必须证明 controller 包顺序（含完成乱序与 aggregate 边界）、旧 generation
拒绝、每 buffer 唯一所有者、部分提交失败和 stop 后禁止重提交，join 后才释放。

## 性能证据与验证

使用普通应用的现有通道 socket，管理授权可经 slkd，逐包不走 D-Bus。三个负载及
时间线/报告契约见[指标参考](../reference/socket-benchmark.md)。固定随机输入在计时前
准备，热循环不用逐包日志、hex 或落盘；有界证据溢出必须计数并使完整资格失败。
完整追踪与低扰动测量分别运行。USB/HCC 不能单独量出 RF；没有时钟映射及误差界
不报告跨域单向时延，不用 RTT/2 代替。NOCP 不等于应用交付。

TLC/LKMM 处理通知/休眠、发布、引用/drain/关闭及唤醒，Kani/CBMC 直接验证适用
生产纯转换与 credit/预算。每份报告绑定源码、锁/线性化点、工具、边界、假设、
反例和实际回归。调度公平性、NOCP/固件行为、USB callback 排空不作为默认事实；
unsupported/timeout/未展开均未证明，模型通过不等于实现 refinement 或 RF 性能。

性能阈值待同配置重复基线稳定后设定；正确性不能由 goodput 抵消。不承诺 1 ms／
125 µs。正常/性能/调试镜像分别绑定，不放宽原期限。实验驱动与真实 WS73 全在 VM；
自然 RCA／非人工恢复继续开放，QMP、人工拔插、hub 切电与注入不替代自然恢复。

参考固定 NearLink Host f0872dfa 的 DTAP_SendCompleteCbk→SchedulerRun 与 libws73-usb
f4d85d0e 的 ACB pool gate，解释 SDK111 封装/调度差异；handle/count 回调不能证明
Linux lifetime 复用安全，也不把参考实现当性能裁判。


## 应用工具入口（2026-10-16）

应用正确性、ping-pong、绝对速率、有限窗口、双向与应答端统一归入独立
`slktest channel`，定位参考 BlueZ l2test；这是工具组织决策，不采用其协议实现。
`slctl` 保持管理、连接与授权。旧测试入口删除，不承诺未发布工具的兼容期。
迁移同一份循环/codec/报告实现至内部库；抓包、内核 selftests、形式化和资格聚合
继续使用现有设施。动态路由仅保留已有正确性门禁，测量仍受基本 CUTC 能力约束。

新二进制必须记录独立源码、artifact 与执行身份。历史报告和 argv 不重写；schema
语义不变。离线与空 USB VM 的入口/本地数据报回归不能继承旧 WS73 或性能资格。
入口整改结束后继续 P1 双端证据与基线，再推进 P2 事件驱动，不追加控制面全集门槛。


## schema2 测量结束与报告隔离

负载循环之后先发布Quiescent并保留fd，监督器核对双端均停止测量才发送finish。
结束等待保持独立原30秒预算；EOF/错误/超时记录于finalization，保留原drive错误和
全部计划行。该等待不延长消息期限，不算应用RTT/active_elapsed，不证明远端应用
已处理其它业务。资源端点仍明确包含采样开销；大规模hex/JSON延至双端结束授权后。
当前内存中的“结束成功”只表明收到本地控制输入；双端顺序须由监督器证据证明。
独立应用报告核对与artifact/凭据/USB捕获/监督器闭包分层，始终不授予性能资格。
