# 当前能力与资格

本页是唯一当前资格入口；目标架构见 [ARCHITECTURE](architecture.md)，依赖与完整
退出条件见 [IMPLEMENTATION_PLAN](implementation-plan.md)。历史逐轮资格、失败及
反例保留于[历史快照](../history/architecture/progress-snapshots-20261014.md)和
[证据索引](../docs/evidence/index.md)，不能继承为新镜像 PASS。

## 准确源码与范围

新生产修复 K `aa3f8ff12d8d` 正在编译/实机复验，不能继承下述旧资格。
真实SDK111 `1812 Complete`返回handle/index四字节；此前空返回假设已被实机反例否定，
失败抓包保留，修复匹配冻结票据后才接受grant/终态。回显不证明lifetime复用屏障。

最新运行代码 K `9806e333a07230567fe79b76810b184bdf7a0988`、编译服务
U `a0f93e7b6bedd99d35b61904daa803a56593aa58` 已在 VM 内回归。
后续 K `c11672ead650be359f8fde4a18bd87dc91bca378` 仅修诊断/recipe测试依赖，用户态 CI pin
和文档改动不重新标记已编译二进制。实际生产源码 hash 见[本批证据](../docs/evidence/relay-production-20261014.json)。

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础 DGRAM、固定两通道、Session 唯一分流、Grant/Binding | 实际有限队列/credit/授权的限定检查，不是完整内核证明 | 本批角色交换共40轮短消息、8轮249字节、16次250/253/254/255超限无提交；不是长包/可靠业务交付资格 |
| 用户态 SSAP | 唯一 actor，ExchangeInfo、单值读写、发现、UUID | 实际 codec/预算/生命周期限定检查 | 本批原读取/写入/发现/UUID路径保持；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一物理Session子对象、typed1812、命令credit/实际票据、真实Complete关联、0014冻结观察lifetime；默认拒绝未批准配对 | 实际Host66/relay9/data38/release56/diagnostic54与C sanitizer通过；Complete C parser CBMC0..265有界598检查通过、旧提交反例保留，Kani unsupported仍未证明 | 新relay测试暴露Complete长度误判并退休Runtime；K `aa3f8ff12d8d`已修，尚待新镜像复验；未实现授权配对、默认crypto/可信安装/Bond或加密业务 |
| 应用权限与扫描 | controller scan RPC显式管理语义；可选sparklink-apps仅领取通道fd | XML白名单/实际调用迁移与严格daemon测试 | apps-only身份尚未实机验收；共享扫描租约/完整按应用策略仍缺，控制组caps0回归不能代替 |
| 设备与daemon生命周期 | per-controller Runtime、epoch撤销、有限工作/期限；单进程daemon | 当前限定模型和实际取消/清理回归 | actor不是进程隔离；不默认承诺socket跨daemon崩溃存活；组合交错仍缺 |
| 长包/真实credit压力/多通道/四设备业务 | 部分基础已接，不能据此称完成 | 本批相关实际转换继续验证 | 完整DG03–12及相应S4/S5门禁继续开放 |
| 安全/恢复/PM/发布/UserHost | UserHost仅低优先级规划；实验代码不是生产能力 | 安装工具通过或模型通过不等于实现证明 | 原S0–S6全部未完成条件保持；自然RCA、非人工恢复及整项issues继续开放 |

本批正常业务两轮捕获零内核丢包，VM taint0；QMP与受控初始化故障只作隔离开发
支撑。USB写入、NOCP、协议ACK、本地准入和日志均不能替代真实对端应用检查与回复。
模型受信任基础和硬件假设必须明示；完整 Linux、运行库、固件和硬件未被证明。

[BlueZ官方来源、当前调用审查与剩余门禁](../docs/evidence/bluez-contract-review-20261014.json)。
本项目取舍采用[ADR0004](../docs/decisions/0004-application-ownership-and-delivery.md)，
不把它描述为BlueZ缺陷，也不宣称已优于BlueZ。
