# Bluetooth／BlueZ 分析：本次复核与实施门禁

用户再次提供的分析与已采用文本相同，SHA256 为
`f8de2edb3e4c6a2cca1442ce06ba59c03407469b7f8631539e974743c993853a`。
最新源码复核与实际新镜像为 Linux `016aa7ee6813`、编译用户态 `b6d6bf96101e`；
后续仅文档，历史镜像资格保持原基线。
原 review 基线 `fc0b4d1a44b6`／`157ec71c3b9a` 仅是历史缺陷定位依据，
不能用于判断后续提交仍有相同缺陷或已经完成验收。

## 架构决定保持

采用 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)：
drivers 拥有总线、固件、HCC／BSLE、传输、PM 和硬件恢复；net 拥有每设备
Runtime、DLI 方言、事务、连接／TCID、流控和链路安全机制；slkd 拥有唯一
Managed 管理、Agent／trust／Bond 策略及 SSAP Engine／数据库／Profile；
slk-vendord 是独立 Backend owner，厂商 ABI 限于内部。

连接阶段最终数据面为每逻辑通道独立 socket fd，绑定 controller、generation、
peer、connection 和 TCID。SEQPACKET／连接式 DGRAM 必须对应实际协商能力；
socket 本身不提供缺失的重传、排序或 credit 协议。AF_SPARKLINK 仅是设计占位。
管理、独立事件、诊断和 Proxy 契约分别管理。discovery 不等待 socket。

内核保留可信的配对、密码学、凭据安装和安全强制；用户态决定认证方法、确认、
信任和持久化。SSAP codec／事务／服务数据库归用户态。UAPI 尚未发布，迁移
调用者和有效测试后同步删除旧接口，无兼容期限和永久双实现。

## 实现、开发测试、实机证据与未决条件

| 范围 | 已有整改或限定证据 | 整项仍需交付 |
|---|---|---|
| R01／R02 安全 | 固定 nonce、测试密钥降级及忽略 proof 后成功已删除；密码学失败传播 | 每连接标准认证、真实安装、Agent 和可恢复 Bond |
| R03／R10 发送 | 无消费者影子 TX ring 删除；真实 handle、backend 接受／短传输边界检查 | 协议流控、最小 socket 和真实双设备数据 |
| R04／R07／R08 SSAP | 不合标准旧 wire Engine、无界累积／无归属通知删除；跨语言权限对齐；历史 codec 限 selftests | 用户态 Engine、完整 PDU、预算／credit／ACK、服务互通 |
| R05 后端 | UART／SPI 伪成功 Complete 删除，未接通操作拒绝 | 实际硬件 backend 及独立验收 |
| R06／R09 策略状态 | 配置错误和未实现非默认策略拒绝；默认 PHY 模型／提前加密提交删除或隔离 | 每连接真实完成驱动的 PHY／安全状态和完整策略 |
| R11／R13 耦合清理 | 两个无业务调用者的注册空 ioctl／未实施声明及无人使用 queue accessor 删除 | drivers 注册所有权、Backend 解耦、每设备 serdev parser、Virtual 实际注册和剩余全局状态迁移 |
| R12 事件／事务 | 实际 read7、Native legacy poll3 复制故障、作者专属结果、提交幂等、槽淘汰、有限取消／迟到回复通过 | 独立 subscriber 调用者迁移、共享 ring／fallback 删除、完整期限／退役／并发／权限 |
| R14 构建／模块边界 | 默认 slkd 不链接旧实验 Profile／transport；严格 CI 基线恢复 | 完整矩阵、内核历史 dead-code 压制清理、服务 sandbox 和发布验收 |

[14 项清单](REVIEW_REMEDIATION_20261011.md)及[立即删除／移入测试／等待替代](LEGACY_CLEANUP_20261011.md)
保留具体调用关系、提交及历史失败。内核 transport／serdev／dev／mgmt／fw 的
历史全局 dead-code 压制尚未清完，不能将用户态严格检查推广为全内核清理完成。

最新完成的[旧注册接口新镜像证据](evidence/ws73-vm-retired-registration-final-20261011.json)
是实际编译 K`257ab5d5e5c6`／U`3506ec472957`：三身份 27 次旧 ioctl 均 ENOTTY，
snapshot／统计／枚举不变、对应 USB 窗口零命令；真实双设备 20＋2 轮保持，
同 daemon、普通用户、幸存者 generation 不变。后续 K`e2bbbf7ecb12` 仅修复
权限 selftest，后续 K`7f9314309e30`／U`f8c7efb` 新增 queued 原始期限门禁。
新门禁的开发 fixture 不能替代旧镜像证据或新实机验收。

本次[新镜像实际证据](evidence/ws73-vm-queued-original-deadline-20261011.json)限定通过：
136 个连续样本、请求原 100ms 期限的同 ID 重试不续期、一次 timeout 计数、
完整字节结果保留及排队零发包；以[该门禁独立记录](DIAGNOSTIC_CANCEL_GATES.md)
为准。真实WS7320＋2／原门禁保持；源码CI九作业全部成功，170 Rust／34 Python／
195工具实际日志核对。它不证明后台自主过期、在途 USB timeout、暂留时
close／drain 或自然恢复。

## 严重程度及依赖顺序

1. 安全假成功、策略静默弱化、生产模拟立即拒绝或删除，严格 CI 每批执行。
2. WS73 生命周期／自然启动超时／重枚举失败／消失根因与旧代码清理并行；
   有限重试、超时、诊断及单设备恢复隔离逐项证明。人工注入不等于自然根因闭合。
3. 连接契约冻结后实现最小 socket；开发门禁通过再做真实双设备数据闭环。
4. 接通用户态 SSAP、每连接安全、可恢复 Bond、Profile 和应用互通。
5. 四设备两组并行，其他 Native backend／厂商 Proxy，完整 PM／部署／发布矩阵。

socket 回归至少覆盖消息边界、超长拒绝、持续发送／背压、关闭／取消、断链、
迟到回调、旧 generation、权限、多设备隔离及内存预算；适用时加入
lockdep／KASAN／KCSAN。每项 issue 分别记录实现、开发测试、实机证据和未决条件。

## 竞争判断及不变约束

[BlueZ 对比](BLUEZ_COMPARISON.md)以官方 MGMT、L2CAP、GATT、Agent 和测试器为依据。
Rust、接口数量、代码量、框架／配置文件存在不构成功能、安全或性能领先证据。
generation、owner、恢复状态和证据链必须通过行为与故障测试证明。
吞吐、延迟分位数和功耗只在具备同条件 Bluetooth 基线后比较。

WS73 第一北极星及完整 S0–S6 不缩减，北极星保持 7／8；自然故障根因、
不依赖人工拔插的恢复、四设备、完整 sandbox 仍开放。历史物理 xHCI 警告保留。
测试仅在 VM；原生宿主对照未执行。不提前关闭任何完整 issue，不合并 draft PR。


后续K`51119eecc251`／编译U`dcab9bb11a82`的
[后台queued到期新镜像证据](evidence/ws73-vm-passive-queued-expiry-20261011.json)
限定通过：800.148168ms静默窗口结束后的统计已计入一次超时，早于首次结果查询；
完整字节／原门禁／真实WS7320＋2保持。源码九作业CI成功，170 Rust／34 Python／
205工具。它不证明特定timer调用、精确到期时延、active USB timeout、held close/drain
或自然恢复。分层、清理三类、VM-only和完整S0–S6全部未决条件继续保持。


最新[生产期限调度修复新镜像](evidence/ws73-vm-deadline-rearm-20261011.json)
已实际回归：32项源码边界、源码CI38101815253九作业成功，170 Rust/34 Python/205工具。
真实WS7320＋2、旧注册27拒绝及诊断全部门禁保持，最长470ms。
生产RX按最早原期限排期并在admission后立即唤醒；实际800.173215ms静默窗口内
queued后台expiry已计入首次结果前统计。它不证明精确执行时延、active期限或held
close/drain。自然根因和无人工恢复仍OPEN，附件全文与采用文本SHA相同，架构、
清理三类及全部S0–S6范围不变；详细生产/证据边界以诊断门禁记录为准。
