# Bluetooth／BlueZ 分析：本次复核与实施门禁

用户再次提供的分析与已采用文本相同，SHA256 为
`f8de2edb3e4c6a2cca1442ce06ba59c03407469b7f8631539e974743c993853a`。
最新源码复核与实际新镜像为 Linux `f822db7756d7`、编译用户态 `ccb3d34ae1bc`；
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

## 本次 BlueZ 附件复核与新增生命周期风险

最新附件与已采用全文SHA相同，最终分层、每逻辑通道socket、用户态SSAP、
每连接安全机制/策略、独立Backend owner及完整S0–S6范围保持。未发布UAPI
迁移后直接删除，无兼容期；立即删除/移入测试/等待替代三类清理与生命周期并行。

新增[早期Managed释放实机失败](evidence/ws73-vm-uninitialized-managed-release-failed-20261011.json)
显示未配置广播handle0前发送disable，真实Complete status0x1e后-EIO退役。
[参考Host定义](evidence/ws73-early-managed-release-reference-20261011.json)将其解释
为未知广播标识，与捕获事实相符；修复和有限自动恢复尚未交付，相关issue继续OPEN。
优先验证Setup时lease release/fd close、初始化中断/未知无线状态清理，并保证
不伪造成功、不提交假Off、旧generation拒绝、另一设备不变及slkd无须重启。

独立active期限测试已修正控制台重定向握手；218工具开发测试通过，真实在途
暂留/退役与原诊断门禁须分别重新执行。七份失败均保留，详见
[诊断门禁](DIAGNOSTIC_CANCEL_GATES.md)。它们不削弱此前已封存WS73路径，也
不构成新恢复验收。原生主机对照未执行，VM-only、北极星7/8和未决根因不变。

## 新VM在途原期限退役限定通过，完整恢复仍开放

[最新实际证据](evidence/ws73-vm-active-usb-retirement-20261011.json)为
K`016aa7ee6813`／实际编译U`b68781ef5078`。复用既有slkd初始化两只实际Ready，
独立初始化进程先终结；随后root Diagnostic提交原500ms MAC，真实成功178字节
IN81被测试QEMU暂留。guest被动等待QMP/file ack加50ms，全静默窗口无
result/cancel/stats ioctl；实际Host超时与Runtime退役使payload一次drop，
零显式/保底释放、零detach/reset/device_del。40/104字节及原seq0请求重试
ENODEV、日志时间和payload全capture未交付由独立验证器核对；peer完整
snapshot/generation不变，退役前后两组实际MAC wire成功。

主RF daemon之后才启动，不宣称暂留阶段同daemon。真实20+2最长623ms，
UID1000/caps0、同PID534/start2859、目标g3→4而peer g2保持。165个真实预算
样本证明driver按现有60000ms稳定期自动归零，再进行下一独立IN81故障并恢复；
没有写预算或扩宽生产limit。另一个新VM原完整格式7门禁63记录/50proof/46wire、
read7/result16/copyout2/legacy poll3/淘汰33/CLI4/三身份旧注册27拒绝及排队
expiry保持，真实20+2最长619ms，同PID669/start1718。两VM各1345/1431 USB
零drop、22RX、warning0/taint0/traceoverrun0，host四只释放在位，VM-only。
[精确源码CI38105931415](https://github.com/OpenSparklink/sparklink/actions/runs/38105931415)
九作业终结成功；实际170 Rust/34 Python/218工具与32内核期限边界日志核对。

这限定证明实际在途超时触发Runtime关闭并取消暂留回复，不完成显式fd-close/
drain、全部owner/CAP/并发/removal/32-bit、精确期限上界或自然恢复验收。
早期Managed release的实际0x1e/EIO生产修复仍OPEN；参考Host“未知广播标识”
解释不替代固件全根因和安全清理/恢复门禁。七份失败记录不覆盖、不改成成功，
旧实现调用者迁移/dead-code清理与生命周期并行，最小socket、用户态SSAP、
每连接安全/Bond/Profile、四设备两组/Native/Proxy/PM/sandbox及完整S0–S6
继续OPEN，北极星7/8。不关闭整项issue或合并draft。USB/HCC/DLI证据不是
独立PHY嗅探；原生宿主对照未执行、历史物理xHCI warning仍未闭合。


## 本批旧固件门面清理与重新复核

K`f5f83d7eb970`／编译U`8641ec61e804`删除未使用固件路径、
伪版本loader、恒true success字段和sle_fw全局lint；真实probe加载保留，Native
WS73 driver未改。[三类清单、调用关系与未决条件](LEGACY_CLEANUP_20261011.md#旧固件门面清理新内核限定回归通过整项仍-open)
及[两独立新VM证据](evidence/ws73-vm-legacy-firmware-cleanup-20261011.json)已核对。
新内核/私有模块/签名smoke与每VM真实20+2（469/623ms）、完整原诊断及在途
原期限/稳定预算通过；UID1000/caps0、各自同RF slkd和peer隔离，USB/HCC/DLI
不等于独立PHY嗅探。[源码CI38106781023](https://github.com/OpenSparklink/sparklink/actions/runs/38106781023)
九作业成功，170 Rust/34 Python/218工具/32实际内核期限测试。E0277失败原记录
保留；修正后编译器warning0，GNU make仍有一次jobserver警告。

下一步先修Setup早期Managed release/fd-close，保留unknown/部分初始化真实清理；
C通用固件短传输/最终ACK校验需独立修复，不能沿用Native WS73资格。事件独立
订阅迁移/旧UAPI、socket/SSAP/每连接安全/Bond/Profile/四设备/Native/Proxy/PM/
sandbox及完整S0–S6仍开放；自然根因、无人工拔插恢复、历史物理xHCI警告未闭合。
附件分析SHA未变，ADR/分层保持，VM-only/北极星7/8，整项不关闭。


### 本批 Setup 释放限定实机复核及完整 issue 集合

K`f822db7756d7`／编译U`ccb3d34ae1bc`已通过[两个新VM的6项实际文件生命周期门禁及20+2](evidence/ws73-vm-setup-release-20261011.json)，
[完整条件和未决项](MANAGEMENT_SETUP_RELEASE.md#setup-租约释放新镜像限定通过完整生命周期仍-open)明确
仅未触及policy的Setup可Free，保持Unknown/Setup；partial/unknown cleanup和held
transport fd-close仍OPEN。原诊断/在途期限/稳定预算、普通UID1000/caps0及peer
隔离保持；[源码CI38108517103](https://github.com/OpenSparklink/sparklink/actions/runs/38108517103)
九作业成功，170 Rust/34 Python/228工具/32期限和10管理源码门禁。两次初始失败
证据保留，GNU make一次jobserver警告未隐藏，不把fixture当硬件或USB当独立PHY。

实际开放集合28项（K19/U9）；补齐近期维护清单漏掉的K11方言/caps/limits/quirks
及K13来源/协议差异/捕获/许可，各原门禁仍有效，不扩大未知能力或FW运行时资格。
C通用固件短传输/最终ACK、部分初始化/自然根因/无人工恢复、历史物理xHCI警告、
完整事件/socket/SSAP/每连接安全/Bond/Profile/四设备/Native/Proxy/PM/sandbox与
全部S0–S6继续OPEN；VM-only/北极星7/8，部分成果不关闭整项或合并draft。
