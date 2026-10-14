# 当前能力与资格

本页是唯一当前资格入口；目标架构见 [ARCHITECTURE](architecture.md)，依赖与完整
退出条件见 [IMPLEMENTATION_PLAN](implementation-plan.md)。历史逐轮资格、失败及
反例保留于[历史快照](../history/architecture/progress-snapshots-20261014.md)和
[证据索引](../docs/evidence/index.md)，不能继承为新镜像 PASS。

## 准确源码与范围

本批准确回归镜像 K `40474895224799879cf63d74b85b17932121f726`／编译服务 U `995eac1cce39cbe309fe813491517fa957f54f48`，
严格关闭核对工具 `447e1f0a60096042e3042c0d2287c441a1dc406d`。普通用户两端104轮实际业务往返保持：
40短消息、248/249各8轮、250/253/254/255/1024/2042各8轮；32次超限拒绝无USB提交。

新增两种连接角色的begun PDU最后fd关闭门禁：首USB提交在关闭前，真实源进程退出并
确认同lifetime重绑被拒绝后仍有末片提交；对端应用校验完整2042字节PDU并回复。
未开始队列没有USB提交，原Session的真实SMTC读写/发现/UUID随后成功。
源端fd已关闭，**这两例不计为源应用业务往返**；原104轮另行回归。
[源码、真实时间顺序、限定证明和未决项](../docs/evidence/pdu-owner-close-20261015.json)。

Session持有begun operation及冻结Grant，fd关闭不再清掉其前缀或终止同行Channel。
每片仍由Runtime检查原lease epoch/generation/lifetime；真实管理撤权、断链、期限到达
期间的物理义务/清理仍待组合实测，不能将fd退出通过推广为这些门禁通过。
生产C consent的311标量检查通过，不证明锁/引用/Runtime/USB组合。

安全relay的147/1ff对端交付历史失败保留，本批无新SMP/可信安装/加密资格。
真实credit耗尽/满队列、多动态通道、四设备、自然RCA及非人工恢复继续开放。
[前批长PDU证据](../docs/evidence/long-pdu-production-20261015.json)、
[保留relay失败与工具限制](../docs/evidence/relay-index-investigation-20261015.json)。

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础DGRAM、固定两通道、Session唯一分流/在途PDU owner、Grant/Binding | 实际Native39、C worker/USB sanitizer；生产consent311标量检查，非完整组合证明 | 本批104轮及32超限；两种角色最后fd退出后begun PDU完整到达，其他SMTC业务保持；完整dup/fork/SCM_RIGHTS/linger、撤权/Down矩阵仍缺 |
| 用户态 SSAP | 唯一actor，ExchangeInfo、单值读写、发现、UUID | 实际codec/预算/生命周期限定检查 | 新镜像原路径保持；底层DLI PB不等于SSAP长写/分片；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一物理Session子对象、typed1812、命令credit/票据、真实Complete关联、0014观察lifetime；默认拒绝未批准配对 | 原实际Host/codec回归与限定CBMC保留，Kani unsupported仍未证明 | 历史147/1ff对端交付失败；本批无新SMP资格，授权配对、可信安装/Bond和加密业务缺失 |
| 应用权限与扫描 | controller scan RPC显式管理语义；可选sparklink-apps仅领取通道fd | XML白名单/实际调用迁移与严格daemon测试 | apps-only身份尚未实机验收；共享扫描租约/完整按应用策略仍缺，控制组caps0回归不能代替 |
| 设备与daemon生命周期 | per-controller Runtime、epoch撤销、有限工作/期限；单进程daemon | 当前限定模型和实际取消/清理回归 | actor不是进程隔离；不默认承诺socket跨daemon崩溃存活；组合交错仍缺 |
| 长包/真实credit压力/多通道/四设备业务 | 有界PB TX/RX，Session持有begun PDU，持续busy计入8项预算，原期限最终提交检查 | 生产游标及consent限定证明、实际worker回归 | 所列长PDU及fd退出子门禁通过；真实压力、满队列、撤权/Down、动态多通道/四设备及完整DG03–12开放 |
| 安全/恢复/PM/发布/UserHost | UserHost仅低优先级规划；实验代码不是生产能力 | 安装工具通过或模型通过不等于实现证明 | 原S0–S6全部未完成条件保持；自然RCA、非人工恢复及整项issues继续开放 |

本批正常业务两轮捕获零内核丢包，VM taint0；QMP与受控初始化故障只作隔离开发
支撑。USB写入、NOCP、协议ACK、本地准入和日志均不能替代真实对端应用检查与回复。
模型受信任基础和硬件假设必须明示；完整 Linux、运行库、固件和硬件未被证明。

[BlueZ官方来源、当前调用审查与剩余门禁](../docs/evidence/bluez-contract-review-20261014.json)。
本项目取舍采用[ADR0004](../docs/decisions/0004-application-ownership-and-delivery.md)，
不把它描述为BlueZ缺陷，也不宣称已优于BlueZ。
