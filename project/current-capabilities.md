# 当前能力与资格

本页是唯一当前资格入口；目标架构见 [ARCHITECTURE](architecture.md)，依赖与完整
退出条件见 [IMPLEMENTATION_PLAN](implementation-plan.md)。历史逐轮资格、失败及
反例保留于[历史快照](../history/architecture/progress-snapshots-20261014.md)和
[证据索引](../docs/evidence/index.md)，不能继承为新镜像 PASS。

## 准确源码与范围

本批准确镜像 K `49467d4df595f8988a7ad6310b53932f37d68283`／编译服务 U `d74421c210eeb1b706dbd90f3500442e28a214dc`。
原104轮全部已取得长度点及32超限拒绝重新回归，另32轮2042字节burst，共136轮
真实对端随机序号/载荷校验与回复；严格fd退出两角色及真实SSAP/发现/连接保持。
[准确源码、只读预算、两端时间线与限定门禁](../docs/evidence/tx-budget-observation-20261015.json)。

新增授权64字节TX_STATUS：同一锁序观察软件队列、Session在途PDU及Runtime ACB
债务，不申请/归还credit。burst两角色都出现outstanding=connection_debt=capacity=5
和新池满拒绝；源端计数增量29/30，随后观察NOCP与新的USB提交，最终债务归零。
每角色两端分别206包真实提交/NOCP（包括协商、SSAP及业务）；全部32条业务取得对端校验与回复。
这是当前SDK111/固定通道的池满后恢复子门禁，未覆盖晚到/重复NOCP、handle复用、
Managed撤权/断链/原期限期间在途物理义务或完整组合证明。

旧manifest的credit_exhaustion_acceptance=false保持原样；新独立只读核对器从原run
和pcap重算，资格来自补充报告，不能把旧软件EAGAIN记录自动升级。查询峰值包含
明确未提交回滚reservation；这里只因实际两端时间线和新池满拒绝共同成立而授予子门禁。

实际Native41、Session sanitizer、C/Rust/Python37项布局及482工具测试通过。
CBMC311标量检查直接映射本批C consent函数，排除锁/引用/Runtime/HCD/NOCP真值
和完整C/Rust组合；Kani unsupported继续未证明。失败CI及沙箱/缺少dbus记录保留，
测试预算和pin修正后CI通过；不改变编译服务d744的生产逻辑。
安全147/1ff对端交付历史失败继续保持；本批无新SMP/key/加密/Bond/Profile资格。
自然RCA与非人工恢复继续开放。

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础DGRAM、固定两通道、Session在途PDU/唯一分流、有限8项TX预算 | 实际Native/worker/consent限定检查；跨语言预算与482工具测试，完整组合仍缺 | 本批136轮/32超限、真实软件队列及controller池满恢复、严格fd退出保持；当前两角色burst池满/NOCP恢复子门禁；完整生命周期仍缺 |
| 用户态 SSAP | 唯一actor，ExchangeInfo、单值读写、发现、UUID | 实际codec/预算/生命周期限定检查 | 新镜像原路径保持；底层DLI PB不等于SSAP长写/分片；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一物理Session子对象、typed1812、命令credit/票据、真实Complete关联、0014观察lifetime；默认拒绝未批准配对 | 原实际Host/codec回归与限定CBMC保留，Kani unsupported仍未证明 | 历史147/1ff对端交付失败；本批无新SMP资格，授权配对、可信安装/Bond和加密业务缺失 |
| 应用权限与扫描 | controller scan RPC显式管理语义；可选sparklink-apps仅领取通道fd | XML白名单/实际调用迁移与严格daemon测试 | apps-only身份尚未实机验收；共享扫描租约/完整按应用策略仍缺，控制组caps0回归不能代替 |
| 设备与daemon生命周期 | per-controller Runtime、epoch撤销、有限工作/期限；单进程daemon | 当前限定模型和实际取消/清理回归 | actor不是进程隔离；不默认承诺socket跨daemon崩溃存活；组合交错仍缺 |
| 长包/真实credit压力/多通道/四设备业务 | 有界PB、Session持有begun operation、8项包含busy、原期限 | 游标/consent限定证明保持；software与controller credit分别表达 | 所列长度及真实软件背压通过；两角色burst硬件池满恢复已取得；撤权/Down/期限、重复晚到NOCP/复用、动态多通道/四设备及完整DG03–12开放 |
| 安全/恢复/PM/发布/UserHost | UserHost仅低优先级规划；实验代码不是生产能力 | 安装工具通过或模型通过不等于实现证明 | 原S0–S6全部未完成条件保持；自然RCA、非人工恢复及整项issues继续开放 |

本批正常业务两轮捕获零内核丢包，VM taint0；QMP与受控初始化故障只作隔离开发
支撑。USB写入、NOCP、协议ACK、本地准入和日志均不能替代真实对端应用检查与回复。
模型受信任基础和硬件假设必须明示；完整 Linux、运行库、固件和硬件未被证明。

[BlueZ官方来源、当前调用审查与剩余门禁](../docs/evidence/bluez-contract-review-20261014.json)。
本项目取舍采用[ADR0004](../docs/decisions/0004-application-ownership-and-delivery.md)，
不把它描述为BlueZ缺陷，也不宣称已优于BlueZ。
