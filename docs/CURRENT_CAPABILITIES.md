# 当前能力与资格

当前开发切片（尚未实机资格）：K6f2f71298029 已剥离旧 controller 安全/RPA模型；
SDK与daemon明确拒绝，crypto源码/历史测试保留。新镜像真实路径回归待完成；
下列历史通过仅适用于其明确源码，不迁移到此切片。见[当前整改](IMPLEMENTATION_PLAN.md)。

**唯一当前资格入口。** [ARCHITECTURE](ARCHITECTURE.md)与ADR定义目标/契约，
[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)是唯一执行入口；
[采用记录](ARCHITECTURE_ADOPTION_20261013.json)记录用户提案、在线scope及调整。
五个维度独立；源码、离线、模型、实机均不替代其他维度，不用一个“完成”字段。

## 当前子门禁：退休重复连接／发现状态与第二套数据分流

准确编译 K `5582a10c5ec8`／service+runner U `cd77ed935740`。
[三类调用审计](evidence/protocol-state-retirement-audit-20261014.json)、
[源码／实际门禁／首次失败／未决](evidence/protocol-state-retirement-progress-20261014.json)：
默认Runtime删除ConnManager／AdvScanInner／全局local_role，四个旧conn/adv/phy/pdu模块100%移入专用历史测试；
删除Host向模型复制的字段、worker连接／发现／DTAP／同步模型分支、第二数据队列消费者、inline drain。
实际Native Host／Session唯一RX、CMTC/TCID/DTAP、credit/ticket/socket/Grant与真正driver codecs保留。
53个无合格机制的旧入口在权限检查后EOPNOTSUPP，不更新buffer，不伪造Complete或本地staging成功。

旧混合SubsysStats(36-byte0x86)删除、C/Rust声明与SDK调用者同步移除，旧编码ENOTTY，无兼容期。
slkd ConnCount与两CLI统计来自已知LinkSnapshot，未知不当空表；全局Role D-Bus明确NotSupported，
角色从实际connection查询。旧DevInfo state=Unknown255，旧DLIInfo max_adv_sets不可用，不再声称固定8个。
无消费者的configfs max/adv/scan默认值明确不支持，不影响Native每controller参数。

严格all-features／35跨语言／460工具／准确CI九项通过；实际源码ingress9、Host连接51、撤销55与诊断边界保持。
历史TX11／SSAP8／PHY及原codec语义保留，不升级为当前数据资格。首个对象10警告与旧fixture/注释依赖失败保留，
清理后对象无警告、完整稳定配置构建通过；不存在新增全局lint忽略。
实际Virtual两轮42查询与原管理fd/取消/dup/在途/同行门禁保持；212次53旧入口拒绝且buffer不变
（root106 Unsupported，ordinary16 observe Unsupported/90 protected denied），4次旧统计ENOTTY；原PM/Netlink拒绝保持。
这些不是完整callback/IRQ/PM/实现形式化证明。

首次实机流水线两只同行Ready，但故障脚本仍解析已删统计，退出失败；原证据保留。
修正后从真实Core-backed D-Bus注册行核对identity/state并等待受控清单稳定两次，非原子多设备快照，未恢复旧API。
准确新实机 [40短消息](evidence/protocol-state-retirement-real-short-20261014.json)、
[8次249／16超限拒绝](evidence/protocol-state-retirement-real-boundary-20261014.json)、
[受控故障同行8](evidence/protocol-state-retirement-fault-real-20261014.json)通过。
随机序号／载荷对端实际校验回复；正常224 ACB SDU／112 NOCP、capture drops0／taint0，
8份实际旧入口拒绝（424系统调用）及已知链路摘要，32完整事件copy故障／重试保持。NOCP不是对端收到。

仍缺：SecurityInner/RPA/剩余默认选择及debugfs/旧诊断统计路由、其余未发布旧接口最终删除或接通；
完整canonical loss/resync/拓扑/owner-death和callback/IRQ/module/PM、标准typed/data真硬件／mixed real/Virtual；
真实PM/PHY/安全/Bond、长包/credit耗尽背压/多通道/四设备／唯一用户SSAP/S5–S6。
自然RCA／非人工恢复仍OPEN，人工/hub/QMP/注入不替代；整项目标不关闭，UserHost仍P4规划。

## 当前子门禁：删除软件 PM 模型与跨设备全局策略

准确编译 K `43e55d59fe95`／service+runner U `1dedbad3d41e`。
[三类审计](evidence/power-model-retirement-audit-20261014.json)、
[源码／门禁／初次失败／未决](evidence/power-retirement-progress-20261014.json)：
PowerInner／默认sle_power及软件状态、估计和计数已移入专用历史测试；6项PM ioctl
明确拒绝，先执行权限检查。configfs power_mode 的show/root store不支持，普通写入仍拒绝；
删除全局原子状态、Native提交门禁和保护操作中的模型同步，不再用一个开关影响所有controller。
真实驱动 pm_config.bin、USB资源和初始化机制保留；没有获得真实PM资格。
旧混合内核SubsysStats待最终迁移，其中power=Unknown255，transitions不可用而非测得零。

默认slkd PM方法明确NotSupported，非法参数InvalidArgs；旧GetStats及其模型DTO移除。
slctl stats／GetLinkSummary从实际身份绑定LinkSnapshot取得index/generation/revision/event_seq/count，
daemon锁外syscall；格式有效的Unknown仍必须失败，已知空表可成功；不是Ready、逻辑通道数、PM或ACK。
U6c的首轮正向实机证据保留，但其缺少Unknown守卫，未转授修正后资格。

严格all-features／35跨语言／459工具及准确CI九项通过；直接生产摘要函数Unknown/已知空表测试通过，
3个原始历史模型测试保留。首次pin初始化编译失败保留，修正后完整稳定配置构建通过。
空模块／实际Virtual两轮42查询、原管理fd／取消／dup／在途／同行门禁保持；
24个PM实际ioctl拒绝且buffer不变（root12 unsupported、ordinary2 observe unsupported/10 protected denied），
4个全局策略show/store Unsupported；这些不是硬件PM或完整callback证明。

修正后新实机 [40短消息](evidence/power-retirement-real-short-20261014.json)、
[8次249／16超限拒绝](evidence/power-retirement-real-boundary-20261014.json)、
[受控故障同行8](evidence/power-retirement-fault-real-20261014.json)通过。
真实随机序号／载荷由对端校验回复，正常224 ACB SDU／112 NOCP、zero capture drops／taint0，
8份新链路摘要和32实际完整事件copy故障／重试／独立重放。NOCP不是对端收到。

仍缺：conn/adv/security/RPA/local_role及ioctl/debugfs默认路由、混合旧统计最终迁移；
真实每设备PM／PHY／安全机制和策略、完整canonical loss/拓扑/owner-death及callback/IRQ/module/PM；
长包/credit耗尽/背压/多通道/四设备/唯一用户SSAP/S5–S6。自然RCA／非人工恢复继续OPEN；
QMP、注入、人工和hub干预不能替代自然恢复。完整目标与UserHost P4规划不变。

## 当前子门禁：退休无身份的 Netlink controller 投影

准确编译 K `7c6d530ffe2e`／service+runner U `ffc0945dfdac`。
[三类调用审计](evidence/genl-retirement-audit-20261014.json)与
[源码／实际门禁／限定范围](evidence/genl-retirement-progress-20261014.json)：
删除默认选中设备的 Netlink role／connection／PM／DLI 导出、广播／扫描／角色控制，
以及缺 generation/lifetime 的简化 multicast。未发布命令与属性同步移出 UAPI／SDK，
旧源和有价值测试隔离；v2 只保留注册数量和软件版本查询，不接收属性，数量不是 Ready。
Controller 操作、完整事件、诊断与数据继续走已接通的 Native 权威路径。

严格 default/all-features、35跨语言、459工具与准确CI九项通过。稳定配置完整构建；
空 WS73/standard 模块与实际 Virtual VM 两轮42查询通过；10份实际 Netlink 回执包含
UID0／UID1000、退休与复用、31个旧命令全部EOPNOTSUPP、额外属性EINVAL、无multicast。

新实机 [40短消息](evidence/genl-retirement-real-short-20261014.json)、
[8次249／16超限拒绝](evidence/genl-retirement-real-boundary-20261014.json)、
[受控故障同行8](evidence/genl-retirement-fault-real-20261014.json)通过。
普通应用随机序号／载荷对端校验并回复；正常224 ACB SDU／112 NOCP，零capture drops／taint0，
32实际完整事件copy故障／重试保持；4份普通用户Netlink拒绝回执。NOCP不是对端收到。

仍缺：其余normalized state及旧ioctl/debugfs默认路由、完整canonical loss/resync/拓扑／owner-death，
完整callback/IRQ/module/PM和mixed real/Virtual、标准真硬件typed/data、长包／多通道／四设备／用户SSAP。
自然RCA与非人工恢复继续OPEN，QMP／注入／人工／hub切电不替代。WP12及完整S0–S6不关闭，UserHost仍P4规划。

## 当前子门禁：完整事件替代旧 read／队列统计

精确编译内核 `e78b88f050aa`／service `bf7a189a4a52`。
[三类调用审计](evidence/read-retirement-audit-20261014.json)和
[当前源码、实际VFS门禁与未决](evidence/read-retirement-progress-20261014.json)：默认read(2)明确Unsupported，
删除44字节SleWireEvent／EventQueue／BroadcastRing／全局序号及per-fd旧poll队列，0x70/71及SDK统计类型删除。
ADV/RAW_ADV/CONN_RESP/CONN_DATA生产ioctl注入明确拒绝，旧源码及copy/overflow/actor价值测试隔离保存。
原9read-copy和6poll-copy仅历史资格；旧live supervisor明确拒绝，不恢复旧ABI。

Native完整ControllerEvent、私有DiagnosticResult和独立CAP snoop保留。
D-Bus／slctl events改为实际LinkSnapshot注册gen/index/event_seq水位，锁外syscall；水位不是投递ACK或pending/delivered统计。
被动uid1000 Cprobe在两个连接角色／两设备的正常两批执行8次，**32实际guarded-page部分copy故障**，
观测真实改写前缀、EFAULT readiness保留、完全重试、独立reader重放；旧read/stats拒绝且buffer不变。
真实新slctl events八份回执匹配对应设备。新empty模块／Virtual Core/Host两轮42查询通过。

准确新实机 [40短消息](evidence/read-retirement-real-short-20261014.json)、
[8次249／16边界拒绝](evidence/read-retirement-real-boundary-20261014.json)、
[受控启动失败同行8](evidence/read-retirement-fault-real-20261014.json)通过；随机序号／数据实际对端校验回复，
正常224 ACB SDU／112 NOCP、零kernel capture drops／taint0。原首次panic/最后回复关闭/旧prepare失败保留。
CI0174 pin Ke78九项通过。未升级完整形式化、并发overflow或自然恢复资格。

**WP12／完整目标仍OPEN**：旧normalized state/genl调用者／通知权威迁移、canonical loss/resync/拓扑/快照/owner-death全集、
完整IRQ/module/PM/callback、标准typed/data真硬件及mixed real/Virtual仍缺。自然RCA／非人工恢复继续开放。
所有原S0–S6／19WP／10FV／12DG及真实WS73纵向路径保留，P4 UserHost仍只规划；不关闭整项issue。


## 当前子门禁：删除破坏性 DLI poll 与重复队列

编译内核 `96f18513c0a1`／service `bf117ad6254f`。
[三类调用审计](evidence/event-poll-retirement-audit-20261013.json)和
[准确源码、门禁、失败与未决](evidence/event-poll-retirement-progress-20261013.json)：删除旧0x82 ioctl／Raw256公开类型、
重复DLI队列及其producer、空backend poll钩子，同步删除Rust/C/Python poll、EventReceiver/50ms fallback、
monitor --legacy 和旧scan wire path。所有daemon构建均拒绝未接通的标准typed管理；实验feature不能复活旧订阅。
Native ControllerEvent、私有DiagnosticResult和CAP限制的独立snoop保留。

历史copy/codec/actor回归隔离到selftests／cfg(test)，旧类型仅私有测试头。
旧poll依赖的live诊断matrix明确拒绝；它不是新矩阵通过。原失败、反例和旧资格保留版本，不转授当前镜像。
首次准备在旧probe C编译失败，未接USB，已保留并修正测试依赖；不恢复生产接口。

当前源码严格Rust、35跨语言ABI、459离线工具、9实际read-copy＋6历史copy边界通过；
稳定配置完整镜像、空WS73/standard模块及真实Virtual Core/Host两轮42查询通过，旧编码ENOTTY且不改用户buffer。
新真实WS73 VM [40短消息](evidence/event-retirement-real-short-20261013.json)、
[8次249／16超限拒绝](evidence/event-retirement-real-boundary-20261013.json)、
[受控失败同行8](evidence/event-retirement-fault-real-20261013.json)通过，uid1000/caps0、随机数据双端校验回复。
正常224 ACB SDU／112 NOCP、零kernel capture drops／taint0；NOCP不代替对端收到。

**WP12仍未完成**：旧read/BroadcastRing、normalized state/genl镜像及loss/resync/拓扑/owner-death全门禁仍待迁移，
完整IRQ/PM/module/callback和混合真实/Virtual、标准真硬件typed/data仍缺。自然RCA/非人工恢复继续OPEN；
QMP、注入及hub切电不替代自然恢复。完整S0–S6、实际data路径和P4 UserHost不变，不关闭整项issue。


## 当前子门禁：标准 Diagnostic 统一与真实 Virtual 生命周期

生产内核 `1ed6963f0f7f`／service `231f61e03d80`：标准 profile0 查询统一到独占版本化 Diagnostic，
固定方言参数由内核提供，保留在途回复和原期限，撤销未执行队列；标准 Managed／typed／data 仍明确不支持。
旧 raw admission 生产函数已删除，旧编码／SDK wrapper 明确拒绝，最终 UAPI／绑定删除仍待迁移。

[准确源码、构建与限定范围](evidence/standard-diagnostic-progress-20261013.json)：配置37e9不变，完整构建、
空 USB WS73／standard 模块 VM、实际 Virtual Core/Host VM 两轮通过。追加仅 selftest 的 K4ea441验证管理 fd 的
*dup 保留租约、最后引用关闭撤销、两条排队取消及一条在途回复、同行查询隔离*；编译镜像仍为K1ed，不转授重建K4ea资格。
两轮42查询；Setup不伪装Ready。已进入callback的确定性join、完整IRQ/module/PM及mixed real/Virtual仍缺。

准确 K1ed/U231 的真实 WS73 VM： [40短消息](evidence/standard-diagnostic-real-short-20261013.json)、
[8次249字节／16超限拒绝](evidence/standard-diagnostic-real-boundary-20261013.json)、
[受控启动失败同行8业务](evidence/standard-diagnostic-fault-real-20261013.json) 通过。
普通uid1000/caps0，对端随机序号／载荷实际校验回复，交换连接角色，两端USB/HCC/A3与NOCP佐证；
正常两批224个ACB SDU／112个NOCP完成、零capture kernel drops／taint0。NOCP不代替对端收到。
QMP和注入重试不是自然恢复／物理拔插验收，原人工及首次panic/最后回复关闭失败证据保留。

CI pin K1ed 的U860f04f九项通过；离线函数50诊断／55撤销及连接边界回归不冒充VFS／空口／形式化实现证明。
标准真USB硬件、完整控制/数据Virtual、canonical事件、标准ticketed数据、旧接口最终删除及自然RCA仍开放；
部分子门禁通过不关闭WP13、K#3/K#8/K#19/U#8或完整S0–S6。


## 可选UserHost及厂商Host适配：只采纳延期规划

[ADR0003](decisions/0003-optional-exclusive-user-host.md) / [准确源码审计](evidence/userhost-planning-audit-20261013.json)。
K88372a9b7cbc/Ub967674无slk-vendord、Proxy/UserHost接口或Host adapter实现。仅规划WP14，P4低优先级，
不成为当前真实WS73/生命周期/用户态SSAP主线前置。本轮未实现、未建UserHost模型、未证明、未实机验收；
保留有价值的权限/隔离/故障/库ABI门禁，新增socket所有权与切换屏障门槛。范围调整不表示issue完成。
Native现有资格、历史失败证据和自然恢复开放条件均不变化；不删除代码、不承诺厂商API或slctl/slkd兼容。
[14项现有issues范围同步](evidence/userhost-issues-scope-20261013.json)已回读；原生范围/历史保留，均OPEN。

## 历史基线：K883 Virtual VM 失败及待验条件

K`88372a9b7cbcea7fcbca4f34cc9d5707488be46e` / U`5a985078756eb1d323b59e968db328d0aad3c7c9`：
旧仅日志Rust模块删除，专用可选C测试驱动已实现；默认关闭、root-only控制设备每个File注册独立TEST-bus
standard-DLI query Runtime，dup共享，最后关闭精确退休generation并join有限reply worker。
共同Backend/Host/credit/超时及带身份标准ingress复用；有限delay/drop/fail注入仅测试模块。
有界一个排队reply槽及正在执行的callback；不宣告Ready/RF/连接/data，daemon不自动生成回复。

[实际范围和未决门禁](evidence/virtual-provider-progress-20261013.json)：实际codec65819项ASan/UBSan检查、
工具456、准确CI38388711225九项成功；[直接生产codec100性质](evidence/virtual-provider-formal-20261013/production/report.json)
限定通过，弱unsupported守卫反例映射实际穷举拒绝测试。不证明Host credit、worker/cancel/join/IRQ/引用/lifetime。
[Virtual File有限抽象模型](evidence/virtual-file-model-20261013/report.json)32513状态、弱join反例；
依赖VFS/工作队列/精确ingress契约，不是实现证明，已进入callback的确定性join实测仍缺。
修正配置K883清洁构建及空USB WS73/standard模块VM通过；Virtual实际VM在Diagnostic acquire返回EOPNOTSUPP失败。
[最新门禁及失败](evidence/virtual-provider-vm-progress-20261013.json)：新VM生命周期及真实WS73回归尚未通过，不能沿用旧资格。
测试运行器已提供query/两controller/dup/最后关闭pending取消/旧gen/复用/drop/fail/迟到回复与模块reload门禁。

下一步先完成当前构建及这些VM门禁，再推进mixed real/Virtual、运行中callback join、Virtual控制/数据模拟与
WP12统一事件/旧ring/重复消费者；标准typed/ticketed及完整module/IRQ/PM/lifetime/自然RCA并行。
旧Kae5/U967真实WS73资格及证据保留，当前未把新source记作实机通过。
完整S0–S6/19WP/10FV/12DG与原28项scope保持，整体架构先整改再功能扩展；未完成整项保持OPEN。
[本批十二项issues回读](evidence/virtual-provider-issues-20261013.json)，原scope保持，当前原28项全部OPEN。

## 前批已验收：驱动归 drivers，Core 不依赖 USB

准确源码 K`ae5b24535a898fb05b9c4f08aa0e7e2004911072` / VM service及工具
U`967ad220271009498319f3bb71d93fbfb9c63e83`。实际 EP0/interrupt/context/URB 和 USB 注册已移入
`drivers/sparklink/standard_usb.c`，独立 `SPARKLINK_STANDARD_USB` 模块；Core 只保留
`sle_standard_dli` 协议解码及带身份入口，不包含 USB driver/objects，不再要求 USB=y。
probe在I/O前精确reserve，失败与disconnect先退休该身份再释放USB；PM明确-EBUSY。
旧Core注册/wrappers仅selftests历史；旧USB_DEV_COUNT明确Unsupported，用ListRegistrations观察。
标准profile0仍query-only，未接通typed/data/PM不授予能力；WS73路径保留。

[离线及准确构建](evidence/standard-driver-move-offline-20261013.json)：实际driver6、adapter14、
binding25/8、metadata44/context19、Core18/Native33等源码回归；工具456、[CI九项](evidence/standard-driver-move-ci-20261013.json)
通过。依赖fixture不证明完整Core/IRQ/module/refcount/lifetime。初次六项warning修正后准确build零compiler warning。
[模块VM门禁](evidence/standard-driver-move-module-smoke-20261013.json)：标准与WS73各一个空USB VM，
各两轮load/unload、三次空注册表检查；不是三次VM启动，不授予物理标准或PM资格。
[USB构建组合](evidence/standard-driver-move-build-matrix-20261013.json)：Core=y/USB=n及USB=m全量产物核对和独立增量退出码0，
首个USB=n被Kconfig重新select的配置失败保留，不计成功。

[metadata314](evidence/standard-driver-move-formal-20261013/metadata/report.json)、
[writer116](evidence/standard-driver-move-formal-20261013/writer/report.json)在准确源码限定重核；
锁/USB依赖模型、memcpy范围假设保持，不扩大为并发/module/URB/引用/lifetime/credit/物理证明。
[真实40短](evidence/ws73-standard-driver-move-short-repeat-20261013.json)、
[249边界](evidence/ws73-standard-driver-move-249-boundary-20261013.json)、
[故障同行8往返](evidence/ws73-standard-driver-move-fault-isolation-20261013.json)通过：VM-only普通用户、
两角色随机对端校验回复，40短/8次249/16拒绝，双端USB/HCC/A3、normal224 SDUs/112 NOCP、零drop/taint0。
RF/建链断链/dup/最后关闭同life拒绝、dynamic observer/newgen/旧path拒绝/同slkd及同行保持。
NOCP/USB成功不替代业务收到；缺文件/QMP不替代自然恢复。

下一批按架构整改推进：专用真正Virtual provider（当前仅placeholder）、WP12统一事件及旧ring/重复连接
消费者、标准typed policy/Session-ticketed ACB/canonical ingress、module/IRQ/PM/回调join与完整生命周期。
Ticket/Session/Grant/socket在途、NOCP复用屏障、真实credit/背压和自然RCA并行；已完成的驱动迁移不重复实现。
整体目标架构整改后再扩展长包、多通道/四设备和唯一用户态SSAP。
完整S0–S6、19WP/10FV/12DG及原28项scope保持；所有未完成整项保持OPEN，未取得自然恢复或完整部分初始化资格。
[本批十二项issues回读](evidence/standard-driver-move-issues-20261013.json)，原scope不变；原28项全部开放。

## 历史子门禁：共同标准provider注册与静态USB路径删除

K`a368cf5f178416d44c1ffe83536f22c074eebf5f` / VM编译service和工具U`168c8709`：
标准C adapter把同一锁下查询metadata及不可变reservation交共同descriptor/ops；standard0仅query caps0，
WS73_1保留已有typed/data路径。get/put保留同一C allocation，open精确核对id/generation并处理partial-open；
共同Runtime安装/open-adoption/close/命令port和RX身份路由接通，注册/install不宣布Ready。
Native provider metadata区分standard/WS73/Test标签，standard不把hardware buffers冒充软件PDU/模式能力。
Native callback异常正返回值明确EIO。**已删除** UsbController、ControllerBackend::Usb/new_usb、
Core sle_switch_controller_usb/open_usb_runtime；所有运行时消费者经同一provider，不是仅改enum名称。

[实际源码/离线/构建](evidence/common-standard-provider-offline-20261013.json)：actual adapter14、
生产descriptor40、C entry拒绝11+standard正向case、共同port2/projection5、Core18/pending9/Native33、
Host全源码与cleanup callback、binding25/8、metadata44、context19通过；历史static info11/open6等仅retired。
旧测试中的Unsupported backend variant已改为真正provider callback拒绝，默认生产无额外模拟provider。
初次integration未使用导入warning和fixture迁移错误保留、修正后准确清洁build零compiler warning/空VM三次。
[准确CI九项](evidence/common-standard-provider-ci-20261013.json)U168c/pin Ka368通过。

[descriptor242及capability弱guard反例](evidence/common-standard-provider-formal-20261013/descriptor/report.json)：
直接验证生产pure validator，任意ABI字段/callback有无，假设provider-owned内核对象指针有效。
standard0不得宣告未接通typed/data caps；删guard产生counterexample，对应实际standard+ACB flag拒绝回归。
metadata314/writer116按准确源码限定重核；copy/USB/锁等依赖假设保持，不证明Runtime/IRQ/module/URB/引用/
并发/lifetime/Host credit/Ready或物理。模型结果不扩大实际adapter依赖fixture的范围。

[新fault同行8业务](evidence/ws73-common-standard-provider-v2-fault-isolation-20261013.json)、
[新40短](evidence/ws73-common-standard-provider-v2-short-repeat-20261013.json)、
[新249与16拒绝](evidence/ws73-common-standard-provider-v2-249-boundary-20261013.json)：VM-only真实WS73、
普通用户，两角色随机对端校验回复及双端USB/HCC/A3；normal224 SDUs/112真实NOCP、capture零drop/taint0。
RF/建链断链/dup/最后关闭同life拒绝及动态fault/observer/newgen/oldpath/同行/同slkd保持。
受控缺文件/QMP仅开发支撑，不是标准USB物理、完整partial-open/引用或自然自动恢复资格。

下一批：将实际USB transport/driver registration移drivers并验证core USB=n/m，专用真正Virtual provider，
标准typed policy/Session-ticketed ACB/canonical RX事件、WP12旧ring/重复连接消费者与module/IRQ/PM矩阵。
已完成共同注册与static Usb删除不重复实现。Ticket/Session/Grant/socket剩余在途/lifetime/NOCP/真实背压和
自然RCA并行；整体目标架构整改完成后再扩展长包、多通道/四设备和唯一用户SSAP。
完整S0–S6/19WP/10FV/12DG保留，整个Backend/架构/自然恢复及原整项issues仍OPEN。
[十二项相关issues回读](evidence/common-standard-provider-issues-20261013.json)原scope保持，实际全部28项仍开放。

## 历史子门禁：纠正标准USB binding，隔离未合格实验wire

K`6db8a530f9c69df1fe09060dd3f09220a55ea946` / VM编译service和工具U`2484932`：
调用审计查明旧标准路径把UART标识A1和指令放bulk、从bulk读Complete，不符合用户提供的
T/XS10003-2025 §6.2/§7.2–7.3。已改为EP0四字节DLI头、class request0/value0，按descriptor选择
device20/index0或interface21/实际接口号；bootstrap回复取interrupt。设备及接口class ID均匹配。
USB wLength包含四字节头，参数65531可编码、65532及以上拒绝；这是transport bound，不冒充设备能力。
RX endpoint lane显式归属，事件URB预算65539（u16参数+header），不把maxPacketSize当完整event上限。
标准裸handle数据没有Session/lifetime/credit/PB所有权，TX明确Unsupported、bulk RX拒绝；
未接通标准typed mutation/recipe/connection拒绝，raw只准明确核对的query schema。
**这不是缩减最终标准后端目标：** standard typed policy和ticketed ACB仍按WP13/原issues继续接通。

默认net/sparklink/sle_fw.rs、假定F810/F811/A5通用下载及其C FFI删除；boot-ROM/FW归厂商driver。
历史74C/12Rust及旧C数据边界迁selftests/retired-*，不再称生产wire或标准firmware资格。
WS73 SDK111/HCC/BSLE/固件/真实ACB保持其独立driver路径，不能把标准binding错误当作WS73自然故障根因。
[三类清理/调用者/替代](STANDARD_USB_BINDING_CLEANUP_20261013.md)。

[准确实现/离线/构建](evidence/standard-binding-offline-20261013.json)：actual writer25/Rust prepare+lane8、
metadata44、context19/info11、port5/pending-open15/ingress9；完整清洁内核/空VM三次通过。
[准确CI九项](evidence/standard-binding-ci-20261013.json)U2484932/pin K6db通过并核对新binding和retired日志；
新proof classifier后工具456通过。decode/USB/allocator/registry替换是fixture依赖，不是物理或并发验证。

[actual metadata314](evidence/standard-binding-formal-20261013/metadata/production/report.json)限定范围重核；
[actual writer116](evidence/standard-binding-formal-20261013/writer/production/report.json)检验全int32参数长度/
USB return/timeout、u16 opcode/index/u8 target、NULL/active/alloc失败；valid source object65531。
memcpy仅抽象为读写范围断言，**不证明payload字节复制**；USB/LE primitive也是依赖模型，
不证明硬件、并发/IRQ/URB/module/引用/Host credit/Complete/Ready。
[忽略四字节头的反例](evidence/standard-binding-formal-20261013/writer/negative-control.json)映射实际65532/65535
预提交拒绝；弱模型均NOT_PROVEN，超时/unsupported/未展开不得PASS。solver/trace gzip保留原始hash。

[新fault同行8业务](evidence/ws73-standard-binding-fault-isolation-20261013.json)、
[新40短](evidence/ws73-standard-binding-short-repeat-20261013.json)、
[新249与16拒绝](evidence/ws73-standard-binding-249-boundary-20261013.json)：VM-only真实WS73，普通用户
两角色随机业务对端校验回复及双端USB/HCC/A3佐证；normal224 SDUs/112真实NOCP、capture零drop/taint0。
发现/建链断链/dup/最后关闭同life拒绝、dynamic fault/observer/旧path/newgen、同行与同slkd保持。
受控缺文件/QMP仅开发支撑，非物理/自然/非人工恢复；没有标准DLI物理资格。

下一批仍是common standard profile0 descriptor/Host/provider retained ops/RX-open-close/get-put，
迁调用者后删static Usb/core USB依赖；标准ticketed ACB/typed policy、真正Virtual、USB=n/m/moduleIRQPM及
WP12事件/旧ring并行。Ticket/Session/Grant/socket剩余在途/lifetime/NOCP/背压和自然RCA继续；
整体目标架构完成后才扩展长包、多通道/四设备和唯一用户SSAP。完整S0–S6/19WP/10FV/12DG不变，整项OPEN。
[十二项相关issues回读](evidence/standard-binding-issues-20261013.json)原scope不变，实际全部28项仍开放。

## 历史子门禁：单一不可变标准metadata生产消费者

K`1d6b3195484fa7ee63b675e5345dfc263850e44c` / VM编译service和工具U`8a7666e`：
C以一个io_lock快照返回查询的version/address/command credit/command最大长度/ACB/ICB/features；
Rust构造器读取一次、核对原bootstrap身份/版本/credit，冻结到provider，不在Runtime锁下重新取USB锁。
info保留80-bit features；controller snapshot保留完整版本、地址及buffer并标记queried metadata。
live Host credit/Ready/error由Host提供，getter和fill_snapshot不覆盖它们；buffer不推断SSAP MTU/MPS、
DTAP可靠模式、连接数或security policy。旧get_version/get_capabilities接口及调用者删除，UAPI未发布无兼容期。

[准确源码/离线/构建](evidence/standard-snapshot-offline-20261013.json)：实际C44，context18+实际Rust
构造器/info/snapshot11，固件74C/12Rust、Core18/pending-open15、port5、ingress9、Native33通过；
C/Rust metadata30-byte/align2及offset18/23/29核对。完整清洁准确内核编译、空VM三次通过。
初版K8e884ef构建因EPROTO不在kernel Rust prelude失败，K1d6b用bindings构造errno修正；失败原记录保留，
不能用离线fixture/模型通过覆盖内核编译失败。
[准确CI九项](evidence/standard-snapshot-ci-20261013.json)U8a7666e/pin K1d6b通过并核对44/74/11及工具454日志。

[实际C限定CBMC314](evidence/standard-snapshot-formal-20261013/production/report.json)：原bootstrap/validator
及combined getter，只提升static linkage，六次顺序查询、相关18-byte任意/length-return任意、unwind19，
getter的mutex是抽象依赖；验证成功一致快照、错误不覆盖输出、失效与有限查询。不证明USB/并发/LKMM/
callback/refcount/module/lifetime/Ready。[弱失效反例](evidence/standard-snapshot-formal-20261013/negative-control.json)
映射实际失败查询ENODATA/输出不变回归；弱源码仍NOT_PROVEN。原solver/反例以gzip保存并记录原始hash，
可用生产提取工具重现；超时/unsupported/未展开不得PASS。

[新受控故障与同行8往返](evidence/ws73-standard-snapshot-v2-fault-isolation-20261013.json)、
[新40短](evidence/ws73-standard-snapshot-v2-short-repeat-20261013.json)、
[新249与16拒绝](evidence/ws73-standard-snapshot-v2-249-boundary-20261013.json)：VM-only真实SDK111 WS73、
普通用户、两角色随机载荷对端校验回复和双端USB/HCC/A3证据；normal224 SDUs/112真实NOCP，零drop/taint0。
发现/建链断链/dup/最后关闭同life拒绝、动态fault/observer/移除/新gen/oldpath、同行与同slkd保持。
受控缺文件/QMP仅测试支撑，非自然/物理/非人工恢复，不授予标准USB物理资格。

下一批：标准profile0共同descriptor/Host与provider ops/RX/open-close/get-put→迁调用者删static Usb及
core USB耦合→USB=n/m、真正Virtual/module/IRQ/PM；WP12事件/旧ring及剩余Ticket/Session/Grant/socket
lifetime/在途/NOCP/真实背压门禁并行。已完成的query/snapshot消费者不重复实现。
整体目标架构完成后再扩展长包、多通道/四设备和唯一用户SSAP Engine；自然RCA/非人工恢复、
整项issues及完整S0–S6/19WP/10FV/12DG仍开放。
[八项相关issues回读](evidence/standard-snapshot-issues-20261013.json)确认原scope不变；实际全部28项仍OPEN。

## 历史子门禁：标准 Backend 的真实能力查询基础

K`1f23fc2197ad43b18d187b235d231583147cc7d1` / VM编译service和工具U`afc491db`：
标准初始化现在真实查询0401指令最大长度、0402 ACB/ICB长度及个数、0403完整80-bit特性，
0404完整版本和带地址类型参数的0406。只在六个匹配Complete全部成功后提交metadata；
保留上一阶段command credit准入，失败重新查询使观察失效，getter不覆盖失败输出。
范围值/成对零buffer/无效地址均验证。WS73 SDK111的0406零参数方言保持在自己的driver。

[准确源码/构建/离线](evidence/standard-capabilities-offline-20261013.json)：实际查询/回滚/getter44，
C固件及参数编码74/Rust12，context18/metadata7、保留port5、Core18、pending/open15、ingress9、Native33；
清洁准确内核编译和空VM三次通过；工具454通过，
[新准确CI九项](evidence/standard-capabilities-ci-20261013.json)通过（U9a262dd/pin K1f23）。
[实际C限定CBMC](evidence/standard-capabilities-formal-20261013/production/report.json)218属性，
原函数只提升static linkage，六次顺序查询、每回复相关18字节/长度/返回值任意，unwind19。
调用者持锁且context存续是明确假设；不证明USB、并发、callback、module、lifetime或Ready。
[破坏失效处理反例](evidence/standard-capabilities-formal-20261013/negative-control.json)映射失败查询
ENODATA/输出不变的实际回归。超时/unsupported/未展开/弱实现均不得PASS；工具命令与hash随报告保存。

[新故障/同行8往返](evidence/ws73-standard-capabilities-fault-isolation-20261013.json)、
[新40短](evidence/ws73-standard-capabilities-short-repeat-20261013.json)、
[新249与16拒绝](evidence/ws73-standard-capabilities-249-boundary-20261013.json)均VM-only真实SDK111、
普通用户随机业务对端校验回复，两端USB/HCC/A3证据；normal224 SDUs/112真实NOCP，零capture drop/taint0。
发现/建链断链/dup/最后关闭同life拒绝路径保留；故障对象控制及默认observer、同行和slkd隔离保持。
受控缺文件/QMP不是自然、物理或非人工恢复，不授予标准USB物理资格。

**未完成：** 新C capabilities snapshot尚无生产Rust消费者，FULL_METADATA未发布；
下一批冻结真实metadata到provider，再接版本化共同descriptor/profile0 Host/RX/open-close/get-put，
迁移调用者后删除static Usb及core USB耦合。真正Virtual、USB=n/m、module/IRQ/PM和WP12事件/旧ring整改随后；
Ticket/Session/Grant/socket剩余lifetime/在途/NOCP/背压门禁并行。整体目标架构完成后才扩展长包、
多通道/四设备和唯一用户态SSAP Engine。完整S0–S6/19WP/10FV/12DG保留，整项issues不关闭。
自然RCA和非人工自动恢复仍未通过。
[八项相关issues回读](evidence/standard-capabilities-issues-20261013.json)确认原scope和OPEN不变。

## 历史子门禁：共同保留提交接口与标准metadata

K`0fdbcf9a477cb17cbe5bd757c5ed7a964c8055ef` / 编译service及工具U`bda960d`：
CommandPort提供独立保留的provider上下文，Native/标准USB同一TX worker在释放Runtime state后
才阻塞传输；不持Host/IRQ锁、不按复用index重新找资源。Transport成功不支付controller/data debt，
不代表Complete或对端收到。Native typed tag原样传递，标准provider未接的connection/multi-step/
recreate/standby明确不支持，单步ON/OFF精确核对参数；旧send/send_command_transport包装删除。

标准Reset/version/MAC真实查询后完整保留5-byte version，failed requery关闭metadata有效性，getter
未知/退休明确失败且不覆盖输出；完整tuple冻结到Rust，info不再在Runtime锁内等待USB I/O锁。
controller snapshot不再丢第五字节，identity/install不再推断Host Ready；features/buffers仍未完整查询，
FULL_METADATA不伪造。仍有ControllerBackend::Usb/profile0 descriptor拒绝和core USB耦合，不能称完整Backend迁移。

[准确源码/离线/限制](evidence/backend-command-port-offline-20261013.json)：实际port5、
bootstrap/strict reply/getter18、C资源18/Rustmetadata7、Core18/pending/open15、ingress9、firmware67C/12Rust、
Native33/actual ticket/C发送回归通过，准确清洁build/空VM三次/CI9通过。make j1 jobserver提示保留，
零compiler warning；fixtures仅替代allocator/USB/锁/response依赖，worker释放顺序仅源码检查。
没有新增形式化资格，不证明workqueue/IRQ/callback/module或跨语言lifetime refinement。
Fixture路径/type/static提取及sandbox LSan失败保留，修正后重核；没有归因硬件故障。

[新故障对象/普通双用户+8业务](evidence/ws73-backend-command-port-fault-isolation-20261013.json)、
[新40短](evidence/ws73-backend-command-port-short-repeat-20261013.json)、
[新249/16超限](evidence/ws73-backend-command-port-249-boundary-20261013.json)：VM-only真实SDK111
WS73，独立两端USB/HCC/A3/NOCP及应用随机载荷校验/回复；normal224 SDUs/112NOCP、零drop/taint0，
RF22/连接双端Down/dup/最后关闭同life拒绝、default observer/control Fault/移除/newgen/oldpath保持。
QMP/受控缺文件仅支撑，非物理/自然/非人工恢复；不授予标准USB物理、ROM、partial-open/URB/module/PM资格。

[16项现有issues回读](evidence/backend-command-port-issues-20261013.json)确认原scope/OPEN不变。

下一批主线保持完整标准Backend迁移：真实buffer/features/command能力查询及metadata有效字段→
标准provider版本化common descriptor/ops/get-put/RX/open-close/Host dialect→迁调用者删static Usb分派→
core USB=n/m与真正Virtual/module/IRQ/PM；WP12事件/旧ring和旧dead_code清理并行。
保留WS73路径，整体架构整改后扩展长包/多通道/四设备和唯一用户SSAP Engine；
自然RCA/有限恢复仍未闭合，整个WP13/原issues和完整S0–S6不缩小、不关闭。

## 历史切片：动态注册生命周期

K`9c0e616c8d36` / 编译service及实机工具U`1cccf5d79b254b96f8d94803bfaeae5046e6795e`：
新增generation-bound `org.sparklink.Registration` 与Manager.ListRegistrations；
每次GetSnapshot/列表都核对实际Core，不以拓扑目录或notification cache宣布可用/Ready。
Pending/Fault只发布只读观察对象，不创建Adapter/不获取Managed；仅Installed且再次匹配gen才启动Adapter。
Installed不是Ready，Retiring不是Free；GetSnapshot只给一份Core原子观察，之后仍可移除。
250ms轮询及SnapshotChanged是提示，不承诺捕获所有中间状态或完整事件拓扑。
普通用户：`slctl registrations` / `slctl registration /org/sparklink/slkN_gG`；业务选择继续只允许Adapter。

[源码/离线](evidence/registration-daemon-offline-20261013.json)：workspace201、Python36、工具451、
strict default/all-features clippy、准确CI9通过。实际private D-Bus配/dev/null ENOTTY证明缓存不能假成功、
无Ready/AcquireManagement接口、删除/复用不把旧path转给新身份；不是模拟控制器成功。
新SDK tuple别名后[实际predicate Kani重核](evidence/registration-daemon-sdk-formal-20261013/production/index.json)
83checks限定通过及weak-gen反例；仅SDK纯函数，未新增Core/daemon/refinement/lifetime/授权证明。
首个测试借用错误及clippy失败日志保留；未伪装为实机故障。

[三真实设备动态对象门禁](evidence/ws73-registration-daemon-fault-isolation-20261013.json)：
UID1000控制用户、UID1001/caps0且无直接kernel access的default observer均从actual slctl/D-Bus
读取精确Core ENOENT Fault；移除后旧对象直接调用拒绝、列表不包含；新gen Installed、旧gen仍拒绝。
fault期间及恢复后共8随机业务对端实际校验/回复，同行identity及slkd PID/start ticks保持。
实机本批覆盖Fault→移除→新gen Installed，不授予短暂Pending采样或所有中间过渡资格。
独立[新40短](evidence/ws73-registration-daemon-short-repeat-20261013.json)、
[新249/16超限](evidence/ws73-registration-daemon-249-boundary-20261013.json)：224两端SDU/112NOCP、
capture零drop/taint0，RF22/连接双端Down/dup/最后关闭同life重开拒绝保持；QMP仅支撑。

[16项现有issues回读](evidence/registration-daemon-issues-20261013.json)确认原scope/OPEN保持。

下一批：将标准USB迁入同一可注册Backend的真实ops/RX/stop及来源/metadata/生命周期，删除static Usb分派；
随后core USB=n/m、真正Virtual/module/IRQ/PM和WP12统一事件/旧ring迁移；旧dead_code/重复实现与
自然RCA/有限恢复并行。整体架构整改后扩展长包、多通道/四设备及唯一用户SSAP Engine。
ROM/部分open/URB/callback和自然/非人工恢复仍未通过，整项issues与完整S0–S6保持OPEN/active。

## 历史切片：Core权威注册诊断

K`9c0e616c8d36` / 编译service U`71ef24d` / 实机工具 U`ff5ab35`：40-byte/align8未发布
registration snapshot接通Core、Rust/C/Python和CLI。无需Runtime选择或lease，按index/gen在Core锁下
观察Pending/Fault/Installed/Retiring；phase/error仅pending，Installed不是Ready，Retiring不是Free。
控制器查询能力与Host Ready仍取独立controller snapshot；没有从sysfs或daemon缓存推断成功。
普通用户可执行 `slkconfig --adapter N --generation G registration`；adapters可显示pending/fault。

[离线/准确源码与限制](evidence/registration-diagnostic-offline-20261013.json)：actualCore18/authorization4、
workspace200、Python36（含C/Rust/Python/32-bit ABI）、工具450、strict default/all-features clippy；
清洁内核/空VM通过，零compiler warning，但一条make jobserver降为j1提示保留。SDK/工具准确CI9通过。
[SDK实际纯predicate Kani](evidence/registration-sdk-formal-20261013/production/index.json)83checks限定通过；
所有ABI字段/full u16/u64，无assume；[弱gen guard](evidence/registration-sdk-formal-20261013/weak-control/index.json)
失败一条expected-generation性质，映射现有SDK gen7/expected8回归。不是Core producer/锁/生命周期/授权/硬件证明。
原allocator Kani unsupported与NOCP假设继续开放；不将工具安装或模型通过代替实机。

[新真实Core ABI故障门禁](evidence/ws73-registration-diagnostic-fault-isolation-20261013.json)：三真实SDK111
WS73、UID1000/caps0经Python→C→Rust→kernel读实际ENOENT Fault及CLI相同诊断；不绑定Runtime，
取消后和同槽新gen复用后旧gen都ENODEV；故障期间及恢复后共8对端实际校验/回复，同行与同slkd保持。
首次SDK装载路径失败的整轮原证据保留，没有归因为内核/自然故障。
另独立[新40短](evidence/ws73-backend-diagnostic-short-repeat-20261013.json)、
[新249/16超限](evidence/ws73-backend-diagnostic-249-boundary-20261013.json)：随机载荷真实对端校验回复、
224两端SDU/112真实NOCP、零drop/taint0；RF22/连接双端Down/dup/最后关闭拒绝同life重开保持。
QMP仅支撑，不是物理拔插或自然自动恢复；未新增ROM/部分open/URB/module/IRQ/PM资格。

[16项现有issues回读](evidence/registration-diagnostic-issues-20261013.json)确认原scope/OPEN保持。
形式化CLI仅后续7baad48加强退出码，重跑相同SDK正/弱证明及unsupported模拟输出exit1；未改变硬件资格。

下一批先把同一Core快照接到slkd动态pending/fault对象及slctl普通用户流程，完成过渡/移除/复用与
同行数据回归；随后标准Backend真实ops/RX/stop、static Usb删除、USB=n/m/真正Virtual与WP12事件
迁移。旧dead_code/重复模块整改、自然RCA/有限恢复并行，整个目标架构整改后再扩展多通道、长包、
四设备两组与唯一用户SSAP Engine；完整S0–S6与原issues范围保持，整项保持OPEN。

## 历史切片：单设备早期失败隔离（工具c07120f）

K`308e5398dccc83a27ca3bd92f0611b93cf2d7bbe` / 编译service U`420cc1266347a00fbd3afbb0a9eae1ab06119aa9` / 工具 U`c07120f4f4ab3b1d11553d2c04c42e0fa9b096d0`：
三只真实SDK111 WS73在VM中完成受控缺custom文件的真实ENOENT，Core保留pending phase/error且无Runtime/Ready；
UID1000/caps0拒绝选择故障身份。另两只保持身份并交换角色完成4轮随机业务对端校验/回复；
恢复原文件、只移除/重加guest故障设备后pending计数清零、同槽新generation，恢复设备与健康设备再完成4轮。
slkd PID/start ticks不变，独立两端USB/HCC/A3/NOCP和1223包零丢失、taint0核对。
[原始记录、独立证明及四次整轮失败](evidence/ws73-early-bootstrap-fault-isolation-20261013.json)完整保留；
[16项现有issues回读](evidence/early-bootstrap-fault-issues-20261013.json)已确认原scope/OPEN不变。
失败依次为tail启动竞态、stats缺adapter、快照schema不一致、漏封存daemon凭据，未重写为PASS。
这是pre-metadata受控失败/精确取消子门禁，未覆盖ROM上传、URB部分open/回调/module/IRQ生命周期；
QMP重接不等于自然或非人工恢复。没有扩大形式化范围，也不替代原40短/249资格。

下一批接通Core权威只读pending诊断与跨语言调用者、slkd动态pending/fault对象，随后标准provider
operations/RX/stop、移除static Usb/core USB=n/m/真正Virtual及统一事件迁移。
仍需完整callback/module/IRQ/PM、自然故障根因与非人工恢复；WP13/WP18及原issues继续开放。
整体架构整改完成后再扩展长包、多通道、四设备数据与唯一用户态SSAP Engine；原S0–S6范围保持。

历史正常路径 **K7e654fde93b9 / 编译service与工具U67165b6**：生产WS73和显式open
fixture迁至版本化common Backend注册描述符，旧注册导出删除，Native取代WS73专用variant。
清洁内核零warning、空VM三次检查、生产validator38项、实际C入口11项及clang ASan/UBSan通过；
CBMC221性质限定通过（仅9项语义断言及内存/算术安全，不证明引用/并发/硬件）。
测试provider实际module编译为前版K1c720574资格；本版未执行该provider生命周期注入。
两只真实WS73在VM取得40轮61-byte、8轮249-byte对端实际校验/回复，16次超限拒绝
且标识不在空口证据；两轮共224两端SDU/112真实NOCP、捕获零drop、taint0。
RF22/建链断链、dup/最后关闭与QMP支撑保持；QMP不算物理拔插或自然恢复。
Uea77931/67165b6新pin CI检出两项测试fixture名称漂移，原失败保留；
K5f8e310只迁测试fixture、生产源与编译K7e654fde一致，Ubc99676 CI九项全部成功（含生产C准入/拒绝、实际Rust回归、release）；结果独立记录，
不将测试修正HEAD或远程CI与编译service HEAD混用。标准USB/重复binding、真正Virtual、
其他bus及完整module/context/generation/close-callback证明仍缺；全WP13保持开放。

历史正常路径 **K80a362ff3355 / 编译service与工具Uf4c65fb**：
共同RX路由/Host入队和worker从USB分离，实际Native、Session、USB调用者迁移；
退休gate保护发布、占用槽不覆盖、精确Arc撤销、worker不重发，decode统计归各设备。
RX与软件命令准入Host→gate，反序解锁后schedule/kick；源回归8项（stdrank依赖）、
Native33/link迁移/工具437、零warning/空VM3、准确CI9通过。
LKMM route单identity限定Never，弱对照Sometimes；前版RX rank反例检出gate→Host。
不是实际deadlock/自然根因，不证明IRQ/Arc/回调/workqueue；本VM配置无lockdep/KCSAN。
两次VM保留普通用户40轮61-byte及8轮249-byte对端实际校验回复、16超限拒绝无上空口；
224两端SDU/112真实NOCP，捕获零drop、taint0；RF22/建链断链/dup/最后关闭/QMP支撑。
标准USB完整Backend迁移、无USB core构建、真正Virtual/多通道/SSAP/自然恢复仍缺。
历史Grant/daemon死亡资格按原准确提交保留，不改授为此新HEAD。

历史正常路径 **K7de1d1316412 / 编译service与工具Ued815bc**：
包含共同入口和RX/命令Host→gate整改，最后只读health同序、不修改Ready/credit。
生产actual9项（rank/Host等依赖fixture）和显式锁位语法扫描记录；零warning/
空VM3/工具437/准确CI9通过。无剩余显式gate→Host候选不是间接锁/IRQ或回收证明。
本版独立普通用户两角色40短+8轮249对端真实校验回复，16超限拒绝无数据证据；
224两端SDU/112真实NOCP、零capture drop/taint0，RF22/建链断链/dup/最后关闭/QMP保留。
LKMM单identity范围不扩大；本VM仍未启用lockdep/KCSAN。标准USB/真正Virtual、
完整callback/module/IRQ/refinement、自然根因和非人工恢复继续未完成，整项issues开放。

历史正常路径 **Kb619aecf261f / 编译serviceU7e64b89 / 运行工具U552fc62**：
标准USB pending identity/open两阶段整改与重复proto/binding删除已实现，未知地址/
能力零、无预先setup完成；精确identity清理不跨设备，失败C注册不动别人的资源。
listener open状态锁不跨I/O，失败/退休清理，transport-open仅实际adopt后发布。
stats字段从canonical表派生，pending_count包含无Runtime退休identity，runtime_count
包含Setup/fault、都不是Ready。内核/Rust/CLI同步，36-byte布局不变，接口未发布。
实际13函数依赖/metadata7/bootstrap/Native33/ingress9、工具440、零warning/空VM3、
准确552fc62 CI9通过。生成生产allocator初态/转换两Kani harness均unsupported未证明；
Std USB callback/module/IRQ/PM/实际硬件及无USB core构建仍缺。
首轮实际40数据子门禁完成，但对端Down在1112ms才上USB、旧1s观察先到期，全轮FAIL
保留。新单5s不可刷新观察+逐端物理Down/propertyfalse关联下重新取得40短、8轮249
对端实际校验回复及16超限拒绝无数据证据，224两端SDU/112NOCP、零drop/taint0。
RF22/建链断链/dup/最后关闭/QMP支撑保留；5s非协议保证，QMP非自然恢复。


历史正常路径：

标准USB资源所有权本批 **K5a49caef5a6e / 编译service与运行工具U5e4d68b**：
删除全局C资源表；每次probe私有分配context，持有USB interface/device引用及不可变id/generation，
Rust UsbDevice通过get/put、Clone/Drop持引用，所有实际FFI/固件/PM调用者传context。
同一io_lock串行I/O与退休，退休关准入并kill/join URB，最终put释放资源；旧context不因index复用
指向新设备。固件内部使用已加锁入口，避免递归取锁；命令超限明确拒绝，不静默截断。
C实际注册/资源18项与metadata7、Core13、firmware67C/12Rust、TX11、Native33/ingress9依赖回归，
含受控I/O/退休交错及同行独立context；不是内核refcount/IRQ/module/callback的完整证明。
清洁构建零warning、空VM三次、工具440、准确CI9通过。新40轮短消息、8轮249及16超限拒绝，
对端应用真实校验/回复；224两端SDU/112NOCP，捕获零drop、taint0，RF22/连接/dup/最后关闭保持。
未新增context形式化证明，旧allocator两harness仍NOT_PROVEN_UNSUPPORTED。
common Backend标准USB注册、静态Usb分派删除、bus构建拆分、真正Virtual、模块/回调/IRQ/PM及
标准USB物理设备门禁仍缺；自然故障根因和非人工恢复继续开放，QMP只作测试支撑。

历史正常路径 **K06c901906b7e / 编译service及运行工具U0960ed9**：
删除无消费者Rust SleUrbCtx/同步bulk包装、对应C OUT/sync函数和无注册身份回调；
实际RX alloc/submit/kill/join仅C内部使用，保留不可变注册id/generation的RX入口、持引用context、
controller/固件/probe/PM调用者。USB模块级dead_code/unreachable_pub掩盖移除；
无消费者编码器/async header parser及常量从生产删除，原始codec片段隔离selftests，
三项历史截断/掩码见证不等于支持行为，实际live event parser四项边界独立回归。
实际资源18C/metadata7、Core13、firmware67C/12Rust、TX11、Native33/ingress9均通过；
清洁准确源码构建零warning、链接旧全局符号不存在、空VM三次、工具440、准确CI9通过。
新普通用户两角色40短、8轮249对端校验/回复、16超限拒绝无捕获数据；
224两端SDU/112真实NOCP，捕获零drop/taint0，RF22/连接/dup/最后关闭/QMP支撑保留。
未新增形式化证明，原allocator两harness仍NOT_PROVEN_UNSUPPORTED，IRQ/module/callback未证明。
标准USB完整common Backend/无USB构建/真正Virtual/PM/物理门禁及自然根因/非人工恢复仍开放。


历史正常路径 **Kc44b74509c41 / 编译service及运行工具U4d14b35**：
common Backend验证后的bus复制进持引用C transport，独立于wire profile；Rust安装Runtime前
检查并映射internal USB1/TEST2至public USB4/TEST6，未知来源拒绝。TEST名称sparklink-test，
不冒充物理USB/WS73或合格VirtualBackend。registry/SciDevInfo/DLI info/snapshot使用此info来源。
未发布UAPI/SDK结构尺寸和旧值不变；内核/Rust/生成C enum/Python同步Test=6，跨语言实际编译核对。
C实际注册原11拒绝+2来源复制（原descriptor修改后值不变）及Rust4转换/投影通过；
旧K06c90190 info在依赖fixture下将TEST返回USB，3通过/1预期失败见证保留，不称实机串标签。
Native33/ingress9/Core13、workspace199/Python35/工具440、strict default/all-features clippy，
清洁内核零warning/空VM三次/准确CI9通过。新普通用户40短+8 app249对端实际校验回复、
16超限拒绝无捕获数据，224两端SDU/112真实NOCP，capture零drop/taint0，RF22/连接/dup保持。
本批未新增形式化证明，原allocator仍NOT_PROVEN_UNSUPPORTED，依赖fixture不证明module/IRQ。
TEST provider实际VM注册、标准方言、统一早期reserve/install/fault生命周期、bus构建/真正Virtual
及自然根因/非人工恢复仍缺；本批来源修正不等于完整Backend迁移。


历史正常路径 **Ke5d1e3311261 / 编译service及运行工具Ue7275d2**：
Native与标准USB实际调用者共用reserve_backend_identity、install_backend_runtime及cancel/retire。
拥有值形式registration snapshot，Runtime分配/候选析构移出registry mutex；发布前再次核对
精确generation、退休和slot占用，失败不覆盖他人Runtime/选择/硬件metadata。Native注销复用
common detach，预留但无Runtime也释放精确identity；重复安装入口/无消费者identity helper删除。
actual10受控构造/析构、pending/open15、资源18C/metadata7、firmware67C/12Rust、Native33/
ingress9/bus4、工具443、清洁内核零warning/空VM三次/准确CI9通过；是依赖回归，不是内核回收证明。
旧Native注销在无Runtime预留状态留下slot，actual旧函数8通过/1预期失败见证保留，未声称实机可达。
TLC两slot/两候选/三全局generation的抽象safety模型16453状态检查完；弱最终gen校验有7步反例，
映射actual复用回归。Live仅表示安装，非Ready；无fairness/liveness、C/Rust refinement或callback证明，
FinishRetire抽象已join边界不证明join真实完成。原allocator Kani仍NOT_PROVEN_UNSUPPORTED。
新普通用户40短+8 app249对端实际校验回复、16超限拒绝无数据证据，224两端SDU/112NOCP，
capture零drop/taint0，RF22/连接/dup/最后关闭/QMP支撑保持。
WS73仍查询后才register Core；bootstrap前pending/故障可见性、实机partial-init失败、标准方言、
static Usb/bus拆分、真正Virtual、module/IRQ/callback/PM及自然根因/非人工恢复继续未完成。


历史正常路径 **K308e5398dccc / 编译service及运行工具U420cc12**：
C provider早期reserve/register_reserved/cancel及pending status/query接Canonical Core；保存未知能力、
明确bus/profile，查询后精确代际与来源验证，成功沿用reservation generation安装Runtime。
WS73 probe在启动work前预留，断开先join所有producer再cancel；Core保存pending phase/error，
sysfs读取Core诊断。诊断回调不能分配或复活已取消代际；显式已join故障/有界重试才可新预留。
失败open可退休旧预留，后续故障记录用新identity；不声明旧generation保活或自然恢复成功。
actual Core14/pending-open15/driver10及C入口11拒绝+2bus/3reserved拒绝/1复制、资源/固件/
Native33/ingress9/bus4、工具444、清洁内核零warning/空VM三次/准确CI9通过；依赖fixtures非回收证明。
新普通用户两设备两轮共8条runtime接口bootstrap观测：metadata_valid0、streaming0、Nativeid=-1
时Core pending query成功，UID1000/caps0读取，后续Ready沿用同id/gen；未覆盖ROM冷启动上传。
新40短/8 app249对端实际校验回复、16超限拒绝无捕获数据，224两端SDU/112NOCP，
capture零drop/taint0，RF22/连接/dup/最后关闭/QMP保持。
旧有限安装TLC模型按准确新hash重核，scope不扩大到新增C/driver/profile/diagnostic/recovery。
原allocator Kani仍NOT_PROVEN_UNSUPPORTED；模型与normal-path不替代callbacks/module/IRQ。
受控pre-metadata缺custom失败/精确取消/新gen及同行真实业务限定资格见本页本批门禁。
动态daemon pending/fault adapter、新公开诊断绑定、ROM/自然冷启动、部分open/URB/callback/module/IRQ、
标准方言/bus构建/真正Virtual/PM及自然根因/非人工恢复继续缺，整项issues保持开放。


历史资格K3ee1a60bf06f/U2a97786：Managed lease epoch、Host锁下软件TX准入和USB提交
检查、socket v2 lease字段已接通；Native33/Host51/Managed54及实际C准入/ABI离线通过。
两只真实WS73在VM取得新40短/8轮249/16超限及dup/最后关闭拒绝重开子门禁，CI9/9。
这是该历史提交的正常业务保持资格；后续scope/blocked RX资格见历史Kbf8663行，不能混用提交。
旧Session表中资格保留其原准确源码，不扩大到新的Grant撤销验收。

历史资格Kf1034577ecc1/Ud570819：RX每次正常唤醒后在Host授权锁下取包/PEEK引用，
等待/copy在锁外；actual C函数体sanitizer与限定LKMM通过，新VM40短/249保持回归、CI9/9。
原40/249资格为nonblocking recv；后续六项File子门禁取得真正blocking recv见证，完整DG09仍缺。

历史编译资格Kbf8663bb78eb/Udfb8636：canonical Grant存Binding，全scope/TX/RX、锁下最终发布、
发送前/队列/USB/RX/poll检查及统一IRQ-save接通。新准确40/249、六项撤销和两个方向实机
门禁通过，CI9/9；protected security明确NotSupported。完整可信安全/daemon死亡/在途仍缺。

新增工具8f19590的pre-daemon SCM_RIGHTS门禁：两角色×release/最后管理fd/dup六例，
应用先关闭继承设备/管理fd并降UID1000/caps0，再接收并dup真实channel fd；broker原fd已关闭。
16随机实际业务往返，112两端SDU/56真实NOCP/3110捕获零丢包，旧授权拒绝与同行Ready/lease/扫描保持。
Kernel与编译service仍bf8663/dfb8636；这是受控broker交付语义，不是实际slkd死亡或完整D-Bus授权策略资格。
首轮69ba2b3接收启动失败保留；没有原子进程errno收据，不新增硬件根因结论。

历史默认生产资格Kbf8663/U86bfbc8：旧破坏性事件消费者已隔离为实验/test，
profile0在授权/发布前明确拒绝。新40短、249八轮/16超限、RF22及建链断链/QMP支撑
完成独立seal（112真实NOCP两包合计），默认workspace199/实验62、严格clippy通过。
这不等于内核旧事件ring和全部调用者已删除；共同daemon死亡业务fd已有下述新子门禁；完整/独立所有者范围仍缺。
专用客户端/接收器/监督tools82aa65a已VM接通：真实共同slkd SIGKILL/reap、新daemon
Ready且generation不变；两个连接角色共4随机业务往返、32两端SDU/16真实NOCP/986捕获零丢包。
首醒[ESTALE,EACCES]：ESTALE有匹配物理Down先于唤醒；双方Free和接任后旧fd均严格EACCES/ERR-HUP。
首轮启动器失败和首轮死亡的原顺序断言失败保留，不覆盖为PASS。独立所有者同行业务未验收。

历史精确正常路径Kab9e5ec/U9124bc4：删除模块启动假UART/SPI/None注册和忽略open失败，
Runtime仅由实际bus注册创建；原模型隔离selftests、UART decoder保留/无模块级掩盖。
空USB VM三次实际检查：注册mask0/activeFFFF，缺设备select ENODEV，unbound snapshot EINVAL，
9 selector输入明确拒绝/接受而不造设备；签名load/unload/taint0、清洁零warning、CI9通过。
新40短/249八轮/16超限、RF22/建链断链/dup/同life重开拒绝通过。
历史共同daemon死亡与受控Grant证据仍绑定各自Kbf8663/用户态/工具版本，不扩大到新K全部竞争门禁。

历史精确正常路径K6d49b12/Uc830f09：旧serdev审计为未接通骨架（无bus driver注册），
core/FFI/全局parser/Serdev分派退出默认生产，最后消费者离开后的decoder移tests；
没有provider的H4/SPI descriptor与transport死成员删除，无全局dead_code掩盖。
四历史源与ab9e5ec逐字节一致，decoder/encoder5、方法2、生产USB+历史info回归保留，
vmlinux旧serdev符号不存在。清洁构建零warning、空USB三次实际门禁、CI9，
新40短/249八轮/16超限及原RF22/建链断链/fd生命周期通过。新serdev provider和Backend seam仍缺。

| 范围 | 已实现 | 离线通过 | 形式化限定通过 | 实机通过 | 仍缺失 |
|---|---|---|---|---|---|
| 当前standard USB binding/旧wire | K6db EP0/interrupt/显式lane、固定target归属；默认通用FW删除；无归属标准data/typed mutation拒绝 | actual25C/8Rust+metadata44+context19/info11，完整build/空VM/CI9；历史firmware74/12仅retired | actualmetadata314+writer116限定；copy仅范围模型，不证明payload/USB/并发/引用/Ready | K6db/U248 WS73 fault8+40短+249八/16拒绝；不授予standard物理 | common标准provider/profile0/typed policy/ticketed data、static Usb/coreUSB/事件/Virtual/moduleIRQPM及自然恢复仍缺 |
| common Backend注册首批 | WS73/open测试provider实际迁移V1描述符；旧入口删除；标准USB未迁 | validator38、实际C拒绝11/sanitizer、Native33/连接operation12+Host、零warning/空VM3；fixture-only修正 | CBMC221限定准入，合法不变内核指针假设；不证明引用/并发/硬件 | 编译K7e654fde/U67165b6独立40短/8长度往返、16拒绝 | 标准USB/重复binding、真正Virtual/serdev、module/get-put/stopjoin全矩阵 |
| WS73发现/连接 | Native真实事务、动态adapter、typed Peer/Connection | 对应准确提交的生产源码/codec/ABI回归 | 不继承数据模型资格 | 当前K308e5398/编译与工具U420cc12两次RF22、真实建链/断链与QMP支撑，历史物理证据保留 | 原NS1自然恢复、当前数据路径物理拔插/全部连接竞争 |
| 默认CUTC31/PI241 socket | A3/ACB、运行时254/5查询、独立命令/data credit、旧debt、有界TX与普通fd委托 | 当前33项Native/Runtime Session/epoch生产源码回归（USB/锁/注册依赖fixture）、准确U420cc12 CI九项成功 | Credit守恒Kani仍未证明；不证明NOCP物理归属 | 新K308e5398/编译与工具U420cc12 DGRAM每角色20/共40轮61-byte实际对端往返，dup/最后关闭子门禁 | credit耗尽/满队列、完整票据/复用屏障、旧lifetime全矩阵 |
| 协商原期限/共享状态 | 38926b2完整三步骤与原期限；同锁快照、关闭/最终软件准入 | C编译、ASan/UBSan deadline/terminal selftest、完整新内核/空USB VM | FV01生产CBMC131项；FV03锁LKMM两性质，故意弱对照允许坏结果 | 上述新40轮及下述249路径保持 | 受控回复/credit阻塞期限、worker/VFS引用完整映射、唤醒及VM KCSAN/lockdep |
| application249/DTAP254 | 当前单ACB上限与精确长度拒绝，ec67348后工具/应用接通 | 196 workspace/423工具及严格clippy；准确U420cc12 CI9/9 | 不能从协商模型推出codec/分片性质 | 新版本8轮249字节及16次application250/253/254/255 EMSGSIZE，拒绝载荷捕获为零 | DG02同Binding短→最大→拒绝→短、其他层253/254/255、长包/PB TX/SAR |
| 提交票据切片 | K464d4d8a9de7 Runtime/Backend引用、一次commit、Host/data/gate内真正URB提交；Host数据撤销；未queued才回滚，已queued/不确定保留debt | Native25、driver10 sanitizer、Host49/连接12、Managed48；C/Rust严格对象及完整内核 | 精确K464/U854 Host撤销/提交锁序LKMM Never、弱对照Sometimes；credit回滚Kani仍NOT_PROVEN_UNSUPPORTED | 新40短/249八轮/16超限、发现连接路径保持 | controlled VM交错、完整Session/Channel/Grant引用证明、完整callback/VFS及NOCP复用屏障；不能宣布整项Ticket完成 |
| Session/Channel/Binding/Grant | K3c8da4fac302 Runtime持Session引用；CMTC/唯一ACB RX分流在Session，Channel独立队列/MTU/MPS；fd仅Binding；同life无协议前拒绝rebind，提交guard撤销检查 | Native/Session28、实际route/consent sanitizer、driver11、strict builds；引用模型只为依赖fixture | 新production Binding CBMC限定通过；2controller×2lifetime Session/fd/work TLC777924状态，仍无C/Rust/VFS refinement | 真实40短/249/16拒绝及每角色普通app dup后收发、last-close rebind拒绝；每端一次CMTC | 动态TCID/关闭协议/合格rebind、Grant epoch/安全、受控在途close/完整VFS/KCSAN/lockdep、NOCP/旧RX wire屏障与多通道 |
| Lease epoch/v2 Binding | K3ee1 Host单调Managed authority；Session带epoch；软件TX准入/真实USB提交锁下验证，successor拒绝旧代次；其他方向/安全拒绝 | Native33/Host51/Managed54、实际C准入队列与C/Rust v2编码一致、准确CI9/9 | 两个生产pure authority Kani限定通过；无完整Host/VFS/硬件证明 | 准确新40短/249/dup保持路径；不是DG09受控撤销 | blocked RX撤销、完整per-Binding Grant方向/安全、release/last-control-fd/daemon死亡/在途/peer隔离矩阵 |
| 受控Grant File子门禁 | 独立VM/普通应用kernel阻塞见证及真实收发工具；生产Kf103路径未变 | 新工具427与325d377 CI9/9，receipt/capture负向核对 | 不新增完整Grant/VFS证明，原pure authority/LKMM限定范围保留 | 六实机用例（两角色×release/last management fd/dup）；16业务往返；EACCES wake、旧fd不被新lease续期、同行原Ready/lease/scan保持 | daemon死亡/SCM_RIGHTS、方向/安全授权、在途USB/迟到真实RX及完整引用/恢复矩阵 |
| Binding scoped/directional Grant | Kernel bf8663唯一fd Grant、完整scope/方向检查、Host锁下发布、IRQ-save；OpenChannelScoped统一broker；protected拒绝 | actual C ctor/permission/admission/publish/TX/RX/poll sanitizer、early broker/D-Bus held-lock拒绝、C/Rust ABI与严格构建、428工具/CI9 | 生产pure ctor/identity/direction CBMC43限定通过；不证明Host/VFS/信任状态 | 新六项File撤销+两方向：TX-only→RX-only实际校验、禁反向EACCES/无载荷，invalid/protected bind拒绝；16往返+2单向，原40/249保持 | S5可信security/降级、独立owner死亡同行业务、受控在途/迟到真实RX、VFS/refinement/KCSAN/lockdep/NOCP/自然恢复 |
| NOCP/复用 | 旧debt保留，未知/过量/不确定Fault，不自动退款 | 生产ledger已重现四步复用风险 | FV07期望反例，不是安全证明；FV02 unsupported/超时NOT_PROVEN | 短40轮实际88完成、249八轮实际24完成，范围限定 | 同/跨life重复/迟到来源、准确性与可信排空屏障；无实机串包断言 |
| 旧SSAP业务 | K167f468剥离local DB/session/cache；K770364dcc152/U7d8857b删除18旧ioctl/业务字段/绑定，CLI/Profile拒绝；旧模型仅selftests；U56ea3e8默认facade NotSupported | 历史八项和生产依赖审计、Native20、连接边界及删除后用户态196/严格clippy；Python34含全Netlink声明一致性，facade私有D-Bus回归；实验callback回归保留 | 不能宣称已有生产用户Engine | 本批默认生产剥离通过：旧18 ioctl root/ordinary全部ENOTTY，新40短/249/发现建链路径保持；没有真实SSAP资格 | 本批退出条件通过；后续Session/Ticket/Grant/socket/Backend等目标架构整改，再WP08唯一用户Engine；相关整项issues仍开放 |
| SSAP/安全/Bond/Profile | 用户态目标层；旧Profile已隔离实验crate，Native不注册旧Profile | 部分机制/actor/类型测试，仅各自范围 | FV08/09完整协议证明未取得 | 尚无新真实通道服务/安全安装矩阵资格 | 唯一用户态Engine、真实read/write/notify/indicate、可信安装/Bond/Profile |
| Backend/事件/恢复/PM/四设备 | 现有Native及限定事件/生命周期基础保留 | 原完整方案/历史部分初始化和取消测试保留 | FV10及完整工作引用/恢复模型缺 | 历史物理/注入/部分清理仅其准确范围；本轮warm恢复不授予自然恢复 | 可注册seam/构建组合、事件迁移、四设备两组数据、自然RCA/非人工恢复、未来可选UserHost/PHY/PM/发布 |

历史Binding Grant基线：Kbf8663bb78eb、编译服务与工具Udfb8636；基础模式为SOCK_DGRAM。两次VM均保留原slkd、
同行generation/业务及真实断链/QMP支撑。QMP不是物理拔插，也不是自然恢复。
本批原期限/credit源码未改；形式化资格仍按原报告逐文件hash核对，未新增整体证明。

历史Netlink切片：K2d4817714963删除无消费者Rust副本/global dead_code；本批K7c/Uffc已删除旧controller bridge与声明，v2只保留registry查询，
Python契约核对实际C/SDK。U6bb7985拒绝ExtAdv静默截断，实际方法held-lock/ENOTTY回归通过。

证据索引：

* [serdev骨架隔离新40](evidence/ws73-serdev-quarantined-short-repeat-20261013.json)、[新249](evidence/ws73-serdev-quarantined-249-boundary-20261013.json)、[调用审计/编译符号/精确历史源/离线/空VM/CI](evidence/serdev-quarantine-offline-20261013.json)：K6d49b12/Uc830f09，真实每设备serdev/Backend seam未取得资格。

* [退休假Backend新40轮](evidence/ws73-retired-backend-short-repeat-20261013.json)、[新249/超限](evidence/ws73-retired-backend-249-boundary-20261013.json)、[源码/空VM/历史codec/CI](evidence/backend-retirement-offline-20261013.json)：准确Kab9e5ec/U9124bc4；整个可注册seam/serdev隔离/模块引用仍未完成。

* [共同daemon真实死亡/接任两角色](evidence/ws73-daemon-channel-death-20261013.json)、[工具/离线范围](evidence/daemon-channel-death-offline-20261013.json)：Kbf8663/编译U86bfbc8/tools82aa65a；首醒因果不同、Free后授权拒绝一致，不作硬件自然恢复。

* [默认事件隔离40轮](evidence/ws73-default-event-isolated-short-repeat-20261013.json)、[249边界](evidence/ws73-default-event-isolated-249-boundary-20261013.json)、[生产源码/离线](evidence/default-event-isolation-offline-20261013.json)：准确Kbf8663/U86bfbc8；实验事件保留不授予生产能力。

* [SCM_RIGHTS六例](evidence/ws73-scm-rights-grant-20261013.json)、[对应离线范围](evidence/scm-rights-offline-20261013.json)：准确8f19590工具/Kbf8663/编译Udfb8636，首次启动失败保留，不扩大为实际daemon死亡。

* [当前Binding Grant40轮](evidence/ws73-binding-grant-short-repeat-20261013.json)、[249/超限](evidence/ws73-binding-grant-249-boundary-20261013.json)、[八项scope/方向](evidence/ws73-binding-scope-20261013.json)：精确Kbf866/Udfb8636，双向与单向资格分开。
* [当前源码映射](evidence/binding-grant-offline-20261013.json)、[限定pure Grant证明](evidence/binding-grant-formal-20261013/manifest.json)：43性质，CPU/VFS/可信安全/硬件证明不扩张；旧Kac9144数据收据保留但因IRQ契约排除资格。

* [六项受控File Grant](evidence/ws73-controlled-grant-20261013.json)：Kf103、编译runtimeUd570819、tools325d377/22635f8，16实际业务、真实阻塞见证、successor拒绝旧fd；不扩为daemon死亡/安全/在途USB或自然恢复。

* [当前授权RX 40轮](evidence/ws73-authorized-rx-short-repeat-20261013.json)、[249/超限](evidence/ws73-authorized-rx-249-boundary-20261013.json)：准确Kf103/Ud570正常真实路径，不是blocked RX撤销实机验收。
* [授权RX源码回归](evidence/authorized-rx-offline-20261013.json)、[限定锁序](evidence/authorized-rx-formal-20261013/manifest.json)：实际函数体与Host-lock抽象分开，完整VFS/唤醒/受控硬件矩阵仍缺。

* [当前lease epoch 40轮](evidence/ws73-grant-epoch-short-repeat-20261013.json)、[249/超限](evidence/ws73-grant-epoch-249-boundary-20261013.json)：准确K3ee1/U2a977，正常路径保持；不是DG09受控撤销通过。
* [Grant离线映射](evidence/grant-epoch-offline-20261013.json)、[生产pure authority Kani](evidence/grant-epoch-formal-20261013/manifest.json)：两个harness限定通过，完整Host/VFS/硬件未证明。

* [历史Session迁移40轮](evidence/ws73-session-owned-short-repeat-20261013.json)、[249/超限](evidence/ws73-session-owned-249-boundary-20261013.json)：K3c8da4fac302/Ud1f9dde，原始dup/last-close拒绝收据与两端CMTC/数据/NOCP对应，零drop/taint0。
* [当前Session源码回归](evidence/session-offline-20261013.json)、[限定形式化](evidence/session-formal-20261013/manifest.json)：Binding实际生产转换与TLC抽象契约分开；不扩成全实现证明。

* [实际ticket提交后40轮](evidence/ws73-ticket-commit-short-repeat-20261013.json)、[249/超限](evidence/ws73-ticket-commit-249-boundary-20261013.json)：历史精确K464/U854，保留原资格范围。
* [提交点离线映射](evidence/native-ticket-offline-20261013.json)、[限定形式化](evidence/native-ticket-formal-20261013/manifest.json)：LKMM范围与unsupported保持分开。

* [当前DGRAM 40轮](evidence/ws73-basic-dgram-short-repeat-20261013.json)：K4b4c6add8189/U59479e0；普通应用真实校验/回复，336 A3、176两端SDU、88 NOCP；零drop/taint0。
* [当前DGRAM 249/超限](evidence/ws73-basic-dgram-249-boundary-20261013.json)：同源码八轮/16拒绝；192 A3、48两端SDU、24 NOCP。两VM均含root/ordinary类型检查和旧18 ioctl拒绝。

* [SSAP剥离后40轮](evidence/ws73-ssap-separated-short-repeat-20261013.json)：当前准确源码；336 raw A3、176两端SDU、88真实NOCP、2225包/零drop/taint0。
* [SSAP剥离后249/超限](evidence/ws73-ssap-separated-249-boundary-20261013.json)：当前准确源码；8往返、16超限拒绝，192 raw A3、48两端SDU、24真实NOCP、1809包/零drop/taint0。
* [本批离线/源码映射](evidence/ssap-abi-separation-offline-20261013.json)：196workspace、34Python、423tooling及CI9/9；历史模型不算新用户Engine。

* [P1历史准确版本40轮短业务](evidence/ws73-ordinary-channel-state-repeat-20261013.json)：K d3abbdc0c13a、编译应用/工具afb5ee2，336 raw A3→176两端SDU、88真实NOCP，2225包/零drop/taint0。
* [P1历史准确版本249及超限](evidence/ws73-ordinary-channel-249-boundary-20261013.json)：同源码，192 raw A3→48两端SDU、24真实NOCP，1809包/零drop/taint0。
* [形式化报告及原始输出](evidence/formal-20261013/manifest.json)：K d3abbdc/U40c7fba，源码hash/工具/假设/界限见formal/README；安装13项不计实现证明。
* [旧40轮](evidence/ws73-ordinary-channel-repeat-20261013.json)、[首次注册panic](evidence/ws73-channel-registration-boot-failure-20261013.json)、[最后回复关闭丢弃](evidence/ws73-channel-last-reply-close-failure-20261013.json)均保留。
* [历史实施/故障索引](IMPLEMENTATION_HISTORY_PRE_20261013.md)保留原scope、partial/release/最后fd/dup/在途与所有失败；不会把旧源码资格倒填新版本。

K4b4c6add8189/U59479e0基础DGRAM已通过root/ordinary SO_TYPE及SEQPACKET拒绝、
准确版本40短/249业务VM门禁。完整Session/Grant/Ticket、VFS/poll/丢包契约仍待整改。
历史实验SOCK_SEQPACKET证据只证明消息边界/业务往返，不能授予可靠递送承诺。
实验AF/PF46已实现，正式协调未完成。SDK111镜像/配置来源与本轮冷/暖/实际上传分别记录，warm tuple不证明本轮上传。
实验驱动与真实I/O保持VM-only。全部原28项issues及goal保持开放/active，自然启动/重枚举/消失根因和
非人工自动恢复未闭合。人工拔插、hub切电、QMP、注入、模型及USB写成功均不替代业务/自然恢复资格。

Backend注册首批准确证据：

- [生产准入/构建/空VM](evidence/backend-descriptor-offline-20261013.json)
- [生产验证函数限定证明](evidence/backend-descriptor-formal-20261013.json)
- [真实40轮](evidence/ws73-backend-descriptor-short-repeat-20261013.json)
- [真实249/超限](evidence/ws73-backend-descriptor-249-boundary-20261013.json)

历史封存资格保持各自准确提交；本批不重新授予旧Grant/daemon死亡门禁的新版本资格。
自然故障根因、非人工自动恢复、在途/复用和整项issues继续开放。

布局访问顺序修正后的当前证据：

- [准确构建/空VM/实际C与Rust回归](evidence/backend-layout-guard-offline-20261013.json)
- [生产准入限定证明与负对照](evidence/backend-layout-guard-formal-20261013.json)
- [准确编译版本40轮](evidence/ws73-backend-layout-guard-short-repeat-20261013.json)
- [准确编译版本249/超限](evidence/ws73-backend-layout-guard-249-boundary-20261013.json)

首批K1c720574证据是历史切片；当前K7e654fde已有独立实机回归。

共同入口当前证据：

- [准确构建/实际函数回归/CI](evidence/core-ingress-offline-20261013.json)
- [限定LKMM/rank反例与源码映射](evidence/core-ingress-formal-20261013.json)
- [真实40轮](evidence/ws73-core-ingress-short-repeat-20261013.json)
- [真实249/超限](evidence/ws73-core-ingress-249-boundary-20261013.json)

最终观察者准确证据：

- [准确构建/actual9/CI9](evidence/core-ingress-observer-offline-20261013.json)
- [限定模型与锁位审计](evidence/core-ingress-observer-formal-20261013.json)
- [准确40轮](evidence/ws73-core-ingress-observer-short-repeat-20261013.json)
- [准确249/超限](evidence/ws73-core-ingress-observer-249-boundary-20261013.json)

USB pending本批证据：

- [实际注册/open与接口/CI](evidence/usb-pending-offline-20261013.json)
- [生产allocator未证明报告](evidence/usb-pending-formal-20261013.json)
- [首轮完整失败与1112ms真实Down](evidence/usb-pending-first-down-failure-20261013.json)
- [新准确40轮](evidence/ws73-usb-pending-short-repeat-20261013.json)
- [新准确249/超限](evidence/ws73-usb-pending-249-boundary-20261013.json)

USB context本批证据：

- [资源引用、受控交错、构建与CI](evidence/usb-context-offline-20261013.json)
- [准确新40轮](evidence/ws73-usb-context-short-repeat-20261013.json)
- [准确新249与超限](evidence/ws73-usb-context-249-boundary-20261013.json)
- [15项现有issue读回回执](evidence/usb-context-issues-20261013.json)：原scope保持，全部OPEN，未关闭整项。

USB旧包装/codec隔离本批证据：

- [清理、live parser、历史codec、源码/构建/符号/CI](evidence/usb-isolation-offline-20261013.json)
- [新准确40](evidence/ws73-usb-isolation-short-repeat-20261013.json)、[249与超限](evidence/ws73-usb-isolation-249-boundary-20261013.json)
- [下一批Backend实际接入审计](evidence/usb-isolation-next-backend-audit-20261013.json)：descriptor bus未传至Rust（TEST当前硬编码USB）须修正；profile0尚不能注册，先统一reservation/install再删enum和拆bus。
- [本批15项issue读回回执](evidence/usb-isolation-issues-20261013.json)：原scope保留、全部OPEN，局部清理/实机通过不关闭整项。

Backend来源本批证据：

- [实际C/Rust来源、旧失败见证、跨语言/构建/CI](evidence/backend-bus-offline-20261013.json)
- [准确新40](evidence/ws73-backend-bus-short-repeat-20261013.json)、[249/超限](evidence/ws73-backend-bus-249-boundary-20261013.json)
- [下一批统一注册实际调用审计](evidence/backend-bus-next-registration-audit-20261013.json)：bus遗失已修；标准USB先reserve、WS73查询后register的早期故障/清理差异继续整改。
- [16项现有issue读回回执](evidence/backend-bus-issues-20261013.json)：含K#11总线/方言scope，全部OPEN，原body不变，未关闭整项。

共同Core注册本批证据：

- [actual安装/退休、旧pending失败见证、构建/CI](evidence/backend-install-offline-20261013.json)
- [准确抽象模型与弱反例](evidence/backend-install-formal-20261013/manifest.json)
- [新40](evidence/ws73-backend-install-short-repeat-20261013.json)、[249/超限](evidence/ws73-backend-install-249-boundary-20261013.json)
- [16项issue原scope/OPEN读回回执](evidence/backend-install-issues-20261013.json)：有限模型/源码和正常实机切片不关闭整项。

早期Core预留本批证据：

- [source/fixtures/构建/CI及限制](evidence/backend-early-offline-20261013.json)
- [普通用户8条真实pending→同代际Ready](evidence/backend-early-pending-observation-20261013.json)
- [原有限安装模型重核](evidence/backend-early-formal-20261013/manifest.json)
- [新40](evidence/ws73-backend-early-short-repeat-20261013.json)、[249/超限](evidence/ws73-backend-early-249-boundary-20261013.json)
- [本批16项issue读回回执](evidence/backend-early-issues-20261013.json)：原scope保留/全部OPEN；early normal-path/模型不关闭整项。
