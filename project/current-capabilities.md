# 当前能力与资格

本页是唯一当前资格入口；目标架构见 [ARCHITECTURE](architecture.md)，依赖与完整
退出条件见 [IMPLEMENTATION_PLAN](implementation-plan.md)。历史逐轮资格、失败及
反例保留于[历史快照](../history/architecture/progress-snapshots-20261014.md)和
[证据索引](../docs/evidence/index.md)，不能继承为新镜像 PASS。

## 准确源码与范围

本批准确回归镜像 K `d926b5b09c8e9bdf09394b2d97fd8f9ee0f8bb6b`／编译服务 U `fdec8eea6781b0ef93ac5ea5c8b12d195cfcfd13`。
VM内普通用户两端实际校验和回复：40轮短消息，248/249字节各8轮，
250/253/254/255/1024/2042字节各8轮，共104轮；交换连接角色。
2042字节应用PDU含5字节DTAP头，拆成9个不超过254字节的ACB包；
两端USB/HCC/A3与每片NOCP核对通过，32次协商MTU以上拒绝无USB提交。
[准确源码、实际回归、限定证明及失败](../docs/evidence/long-pdu-production-20261015.json)。

当前DLI PB资格不代表可靠模式、SSAP长写、真实credit耗尽/背压、多动态通道或四设备。
新增软件准入期限和单Binding超时隔离通过实际生产C sanitizer；
在途分片关闭/撤权/超时的受控VM组合仍缺；当前已提交前缀中止会终止共享Session，
可能影响另一Channel，按应用最后关闭隔离尚未达成。
安全relay历史K2d上147/1ff匹配Complete但对端未收0014，门禁失败；本批不重标记SMP资格。
SDK/us固件与111不同，vendor ISA/ROM缺口仍未解。
[保留relay失败、有限证明和工具限制](../docs/evidence/relay-index-investigation-20261015.json)。
后续文档与CI提交不重新标记编译服务身份，QMP/注入不计自然恢复。

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础DGRAM、固定两通道、Session唯一RX分流/连接级TX分片游标、Grant/Binding | 实际Rust入口/credit39、C Session/USB sanitizer；生产游标所有unsigned标量输入CBMC48检查通过，锁/引用/固件不在此证明 | 本批104轮、应用248至2042所列长度，32次超限拒绝；不是可靠模式或真实credit压力资格 |
| 用户态 SSAP | 唯一actor，ExchangeInfo、单值读写、发现、UUID | 实际codec/预算/生命周期限定检查 | 新镜像原路径保持；底层DLI PB不等于SSAP长写/分片；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一物理Session子对象、typed1812、命令credit/票据、真实Complete关联、0014观察lifetime；默认拒绝未批准配对 | 原实际Host/codec回归与限定CBMC保留，Kani unsupported仍未证明 | 历史147/1ff对端交付失败；本批无新SMP资格，授权配对、可信安装/Bond和加密业务缺失 |
| 应用权限与扫描 | controller scan RPC显式管理语义；可选sparklink-apps仅领取通道fd | XML白名单/实际调用迁移与严格daemon测试 | apps-only身份尚未实机验收；共享扫描租约/完整按应用策略仍缺，控制组caps0回归不能代替 |
| 设备与daemon生命周期 | per-controller Runtime、epoch撤销、有限工作/期限；单进程daemon | 当前限定模型和实际取消/清理回归 | actor不是进程隔离；不默认承诺socket跨daemon崩溃存活；组合交错仍缺 |
| 长包/真实credit压力/多通道/四设备业务 | 有界DLI PB TX/RX，软件准入原期限，有限队列，未提交超时只退休本Binding | 生产游标纯转换限定证明；actual worker sanitizer，不是组合refinement | 两设备所列长PDU通过；真实credit耗尽/满队列、在途关闭撤权、动态多通道/四设备及完整DG03–12开放 |
| 安全/恢复/PM/发布/UserHost | UserHost仅低优先级规划；实验代码不是生产能力 | 安装工具通过或模型通过不等于实现证明 | 原S0–S6全部未完成条件保持；自然RCA、非人工恢复及整项issues继续开放 |

本批正常业务两轮捕获零内核丢包，VM taint0；QMP与受控初始化故障只作隔离开发
支撑。USB写入、NOCP、协议ACK、本地准入和日志均不能替代真实对端应用检查与回复。
模型受信任基础和硬件假设必须明示；完整 Linux、运行库、固件和硬件未被证明。

[BlueZ官方来源、当前调用审查与剩余门禁](../docs/evidence/bluez-contract-review-20261014.json)。
本项目取舍采用[ADR0004](../docs/decisions/0004-application-ownership-and-delivery.md)，
不把它描述为BlueZ缺陷，也不宣称已优于BlueZ。
