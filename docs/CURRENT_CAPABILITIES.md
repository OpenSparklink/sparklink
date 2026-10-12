# 当前能力与资格

集中状态入口；详细来源见各证据/ADR，不能把文件/API存在等同于能力完成。
2026-10-13架构review纳入[ADR0002](decisions/0002-session-socket-lifetime-and-proof-contract.md)，
完整S0–S6和现有分层保持。

| 范围 | 已实现 / 离线 | 实机资格 / 仍缺 |
|---|---|---|
| WS73广播/扫描、建链/断链 | Native真实事务、动态adapter与typed Peer/Connection | 有准确提交的两端RF/连接/QMP及历史物理资格；新改动逐项重跑 |
| 默认基础CUTC31/PI241 | per-generation credit/debt、有界TX、socket fd委托 | K4a3dc86/U4426d97/工具c259bae：每角色20，共40轮61-byte普通用户真实往返；8轮前基线保留 |
| 249及超限边界 | ec67348工具/应用，197 workspace/423工具/严格clippy | 尚未实机通过；不当作长包或credit耗尽 |
| 会话、授权、同步 | ADR明确所有权和KernelGrant目标 | 协商期限/同步P1整改；Session/reopen/票据/epoch/多通道仍未完成 |
| 形式化验证 | 方法与报告门禁确定 | 各工具/性质未取得完整报告前均NOT_PROVEN；不继承测试/模型/hardware标签 |
| SSAP/安全/Bond/Profile | 用户态/机制分层方案 | 真实通道服务矩阵与安全安装尚未完成；实验实现不宣称生产能力 |
| 四设备、Proxy、PM、恢复 | 原S0–S6及有限诊断机制 | 当前源码四设备数据、自然根因/非人工恢复及发布矩阵仍开放 |

基础实验SOCK_SEQPACKET目前只承诺消息边界；没有可靠递送保证，不发布稳定ABI。
[四阶段与迁移契约](decisions/0002-session-socket-lifetime-and-proof-contract.md)。
失败证据保留：[注册panic](evidence/ws73-channel-registration-boot-failure-20261013.json)、
[最后回复关闭丢弃](evidence/ws73-channel-last-reply-close-failure-20261013.json)。
[40轮证据](evidence/ws73-ordinary-channel-repeat-20261013.json)。整项issues均不因局部资格关闭。
