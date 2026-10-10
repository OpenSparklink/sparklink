# SparkLink 架构与实施状态

2026-10-11：以[联合方案](IMPLEMENTATION_PLAN.md)和
[ADR 0001](decisions/0001-management-channel-service-boundaries.md)为目标设计。
旧全局 active device/swap-on-switch 描述不再作为目标；运行时遗留依赖仍须
逐项迁移，不能认为文档更新等于代码已经完成。

应用/slctl 经授权 D-Bus 到 slkd；slkd 是 Managed owner，拥有启用/连接策略、
Agent、trust、可恢复 Bond、SSAP Engine/数据库及 Profile。net/sparklink 拥有
每设备 Runtime、Host 方言/事务、连接/TCID、流控、安全机制及可信状态；
drivers/sparklink 拥有总线/固件/HCC/BSLE/传输/电源及硬件恢复。厂商用户态后端
由独立 slk-vendord 持 Backend owner；私有 ABI 不进入普通应用和 slkd。

连接阶段最终使用每逻辑通道独立 socket fd，绑定 controller/generation/peer/
connection/TCID。可靠模式优先 SOCK_SEQPACKET；连接式 SOCK_DGRAM 仅适用于
实际协商的不可靠能力。队列/背压/权限/关闭独立；AF_SPARKLINK 名称和编号
尚未分配，只作占位。管理、事件、观察、诊断与 Proxy 接口独立。未发布 UAPI
可同步替换，旧 CONN_SEND/RECV 调用者迁移后移除。

当前 WS73 Native discovery 已有 VM 真实双设备/普通用户/物理重接证据；一次
人工错误后有有限恢复支持。自然超时、重枚举和消失根因未闭合，北极星 7/8。
连接 socket、用户态 SSAP、每连接安全/Bond/Profile、Proxy、四设备两组及完整
部署仍待实现/验收。UART/SPI codec 和框架存在不等于硬件支持。

[14 项复核](REVIEW_REMEDIATION_20261011.md)区分实际生产缺陷与已验证 WS73
路径；[旧实现调用审计](LEGACY_CLEANUP_20261011.md)列出立即删除、移入测试、
等待替代三类。生产禁止固定测试 nonce/测试密钥降级/伪 Complete；未接通能力
明确不支持。开发模拟及注入仅专用测试后端，不作为 RF 或完整标准符合性证据。

真实测试遵守 VM-only。保留[物理历史证据](evidence/ws73-vm-physical-20261010.json)
与[人工恢复历史证据](evidence/ws73-vm-artificial-recovery-20261010.json)，源码
更新后重新核对。任何部分成果不提前关闭完整 issue；完整 goal 继续 active。
