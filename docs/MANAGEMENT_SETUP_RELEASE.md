# 未触及 radio policy 的 Setup 租约释放

源码实现：Linux `f822db7756d7c99eb6a7d0e1e9e32c513e91ad71`。本批新镜像K`f822db7756d7`／编译U`ccb3d34ae1bc`的
[两个独立新VM证据](evidence/ws73-vm-setup-release-20261011.json)已封存；
资格仅限未触及policy的Setup release/last-file/dup，不引用历史镜像代替新源码。

## 缺陷与修复边界

历史[失败记录](evidence/ws73-vm-uninitialized-managed-release-failed-20261011.json)
捕获未配置广播handle0的Setup租约release发出bare stop，真实Complete状态
0x1e后EIO退役。参考Host将0x1e定义为unknown advertising identifier，与捕获相符；
此解释不等于固件全根因闭合，自然启动/重枚举/消失RCA及完整恢复仍OPEN。

修复复用每设备Host已有状态：quiet，无fault/recipe/revocation，两个radio状态
Unknown且未初始化，policy cookies为0、没有任何保留的discovery操作。只有
全部成立才允许Managed租约直接Free；不添加第二套dirty状态，不设置Off或Ready。
Diagnostic元数据查询可能增加next_cookie，不能以cookie计数为1来判断policy历史。
已有确认Off使用原屏障；任何提交、取消、部分初始化、在途/待回复、错误或unknown
历史都仍需真实cleanup/退役。非零Complete和原errno不能改成成功。

同一revoke_management在显式release和PinnedDrop最后一个file reference关闭时
执行，仍持管理mutex，并检查Runtime存活及Host fault。dup持有同一File ownership，
关闭一个引用不能释放租约，最后引用关闭才撤销；独立观察fd不持有该租约。

## 开发门禁与专用实机门禁

10项selftest编译实际Host predicates、core快速释放block和真实operation/queue/
management模块；锁/周围driver依赖为fixture，不宣称VFS或硬件验收。覆盖
Unknown/Off/On矩阵、所有operation槽和terminal/cancel历史、cookie/recipe/
revocation/active/reply/queue、错误保留、token身份及observer权限。

专用C selftest只由明确VM工具启动，两只真实Setup各3项：显式release（错误token
先拒EPERM）、最后fd close、dup后第一次close仍Held及最后close Free。
独立观察完整snapshot/radio/lease与peer；每项保留完整UAPI字节与有界quiet时间。
严格verifier核对6项顺序、身份/字节、token隐藏、Unknown与Setup不变，USB捕获
包括每项间隙和两设备，整个probe窗口不得出现任何DLI command/Complete/failure。
测试不编入生产success路径。

可复现：先准备新签名scratch VM，run添加`--setup-release-verify --fault-recovery`。
本门禁可与独立active-deadline模式或原完整诊断模式分别结合；每轮都须普通用户
真实20+2、同RF slkd/peer隔离及独立capture。partial-init cleanup、held transport
fd-close/drain、并发/权限/32-bit和自然恢复不因本门禁通过而完成。

## 未决条件

未触及policy的Setup限定实机门禁通过；完整事件迁移/旧UAPI删除、C通用固件ACK/短传输、安全/
连接socket/SSAP/Bond/Profile、四设备/Native/Proxy/PM/sandbox及全部S0–S6保持。
VM-only，不改变host内核/服务/权限，不使用人工拔插作为恢复，不关闭整项issue。


首轮[失败证据](evidence/ws73-vm-setup-release-record-writer-failed-20261011.json)
发生于测试progress写入第二份metadata：误用one-shot握手writer，C probe尚未启动，
没有实机release/fd-close/RF资格。原RUNNING progress与terminal FAIL均保留；
修为原子replace并补实际重复文件写入/FAIL持久化与one-shot拒绝回归，再跑新VM。


## Setup 租约释放新镜像限定通过，完整生命周期仍 OPEN

K`f822db7756d7`／编译U`ccb3d34ae1bc`的[证据](evidence/ws73-vm-setup-release-20261011.json)
证明两个独立新VM各6项实际release/last-file/dup门禁：两只分别显式release前
错误token EPERM，最后fd close，dup第一次close仍Held/末引用close Free；独立
observer完整snapshot/radio/peer/generation保持Setup/Unknown。整个probe窗口
含间隙及两设备零DLI command/Complete/failure，不假Off/Ready，不归一化非零回复。
本批复用唯一Host已有policy状态，没有额外dirty authority；有操作/取消/部分初始化/
在途/错误历史仍走真实cleanup。完整锁/并发、held transport fd-close和unknown
cleanup不因此通过完成；初始0x1e失败和首轮测试记录writer失败均保留原证据。

新image/私有签名modules/空USBsmoke通过；编译器warning0，GNU make仍记录
一次jobserver警告。每新VM随后普通UID1000/caps0真实20+2，最长
622/769ms，各自同RF slkd/peer隔离；两capture各
1345/1431 USB、22RX/零drop、guest warning0/taint0/traceoverrun0，host四只释放在位。
原500ms在途超时/实际Runtime取消暂留回复/driver现有稳定预算归零，另一VM原
格式7完整诊断63记录/50proof/46wire、read7/result16/copyout2/poll3/淘汰33/
CLI4/旧注册27拒绝及queued期限保持；hold发生在主RF daemon前，同daemon期间
hold未验收。USB/HCC/DLI不是独立PHY嗅探，原生宿主对照未执行，VM-only保持。
[精确源码CI38108517103](https://github.com/OpenSparklink/sparklink/actions/runs/38108517103)
九作业成功，实际170 Rust/34 Python/228工具/32期限及10管理源码门禁。

开放issue集合重新核对为28项（Linux19、用户态9），此前近期批量更新列表漏了
K11方言/能力与K13差异/来源审查，本批补齐，原checklist不替换。K11的descriptor/
来源/caps/limits/quirks/不同firmware fallback及不支持设备行为仍逐项待验，不能
使用默认255/8或参考单链路限制作全设备能力。K13的字段级来源矩阵、去敏样本/
golden许可、最小基准抓包/连接ACB与pairing relay仍独立验收；FW111 combined
固定hash不证明board/运行时版本资格，原016c00a100查询不能唯一识别110/111。

下一步C通用固件拒绝短传输、截短/错opcode/非零最终ACK，并独立backend资格；
部分初始化真实cleanup/held fd-close、自然启动/重枚举/消失RCA、无人工拔插恢复
与历史物理xHCI warning继续OPEN。随后独立事件调用者迁移、shared ring/fallback/
旧UAPI删除、socket/SSAP/每连接安全/Agent/Bond/Profile、四设备两组/Native/Proxy/
PM/sandbox/发布及完整S0–S6保持，北极星7/8，整项不关闭，draft不合并。


## Diagnostic 已 Off 的在途关闭限定资格

[新门禁与证据边界](USB_DESCRIPTOR_CAPABILITY_CLEANUP.md)及
[新镜像实测](evidence/ws73-vm-descriptor-cleanup-held-close-20261011.json)仅将
Diagnostic already-Off 的原fd/最后dup在途关闭、保留原期限后Runtime有界退役
加入资格。Setup六案例保持；此前未资格记录保持历史，不改为成功。
close立即abort、Managed partial/unknown初始化真实cleanup、完整作者/权限/并发/
removal/32-bit与自然RCA/自动恢复继续OPEN。


## Managed 未选择取消的源码阶段记录（专用实机门禁仍待执行）

内核 `f6709397c6d6e33546744c79193b14ba9f573660` 在现有 admission/state/Host 串行化下扩展释放路径：
仅 Host 无 active/reply/fault/revocation、无已选择 recipe、未初始化且 radio 均
Unknown，保留的操作仅未执行 Queued 或 ECANCELED、无 opcode/step/status/power/
完成时间，policy cookies 有对应 operation，队列仅有其带 tag 的 typed 请求时，
允许直接取消队列和操作、将租约 Free。结果保留 Cancelled/ECANCELED，cookie、
credit、Unknown/Setup 不变，不发送不存在句柄的 stop，不合成 Complete/Off/Ready。
原 quiet pristine Setup、已确认 Off 和 Diagnostic 路径保持。

实际 TX `Host::next` 在返回给 transport 前设置 recipe 和 Pending/opcode；
recipe 不因取消或结果淘汰清空，因此任何已选中、部分初始化、在途、待回复、错误
或未知历史仍需真实 cleanup/退役。该判据依赖当前 Native raw whitelist 仅查询；
未跟踪 raw 或独立 legacy recipe 队列不能采用此例外。仍有调用者的 legacy 路径
等待迁移，未发布 UAPI 无兼容期；专用模拟和依赖 fixtures 留在 selftests。

[源码证据](evidence/managed-unsubmitted-source-20261011.json)编译实际 predicates、
取消、TX selection、InFlight、core release block，真实 operation/queue/lease 模块
及实际 opcode/timeout 常量：21 项严格 Rust 门禁通过；原期限/result 开发门禁
保持。锁、时钟缩放、周围 transport 是依赖 fixtures，不能据此宣称 VFS/RF。
初次 fixture 缺导入，以及扩展后缺模块层次/generic Result 的编译失败日志保留，
修正仅 fixture 适配后再运行。生产未增加全局 dead-code suppression 或第二份 dirty
状态。源码阶段当时新镜像尚待核对；最新镜像回归见当前证据段，专用 Managed pre-selection/partial-wire 实机门禁仍开放。

后续须在新冻结签名 VM 中证明实际 ioctl/last-file/dup、队列选择竞态、完整字节/
USB 证据、另一设备和同 slkd 隔离；部分初始化各步骤不能借未执行路径逃过真实
cleanup。保留真实 WS73 普通用户双设备 20+2 回归。已有 Diagnostic 原期限关闭
证据仅覆盖当时编译版本及 already-Off 模式，不替代这项 Managed 验收。
自然启动/重枚举/消失根因、无人工拔插的完整恢复、历史物理 xHCI warning、
完整能力来源/事件迁移/socket/SSAP/安全/Bond/Profile/四设备/Native/Proxy/PM/
sandbox/发布及 S0–S6、全部 28 项原 scope 仍 OPEN。VM-only、不关闭整项、不合并 draft。


新完整 Rust 内核构建暴露 serdev 的遗留 `MAX_PAYLOAD_LEN` 未使用导入；已在独立提交 `292f9fec84b67d325055bff69c17ce3c7c81706d` 移除。原成功构建及该警告日志保留；清理版本已重新构建，结果见当前证据段；此提交不修改 parser/frame/hardware 行为，Managed source gate 的实际 Host/core/queue/operation 字节保持。源码 CI38112681170 已九项 success；当前新镜像及 Managed 专用实机门禁尚未完成，整项保持开放。


## 当前 Managed 未选择取消源码修复与新镜像 WS73 回归

K`292f9fec84b6`／编译U`d749cbb102c5`的
[两个新 VM 封存](evidence/ws73-vm-managed-unsubmitted-regression-20261011.json)
已经通过；新 Managed 取消分支仍只有源码门禁资格，**专用实机 pre-selection、
partial-wire/unknown 初始化及 Managed held-close 不因以下回归而通过**。
21 项门禁编译实际 Host predicates/cancel/TX selection/InFlight/core release：
未选择才本地取消并保留 ECANCELED/Unknown/Setup；已选择证据跨取消/淘汰保留，
继续真实 cleanup/原期限退役。未跟踪 raw、错误、在途、radio/初始化历史均不放行。

完整新内核/private modules/签名无 USB scratch smoke、冻结显式38输入通过；
第一次 prepare 因 module-tree 参数层级错误在启动前被拒绝，原 FAIL 保存，按
staged lib/modules/release 在新目录重做，不篡改记录。Native WS73 driver 未变。
两新 VM 各 Setup6 零DLI完整窗口、普通UID1000/caps0真实20+2，最长均469ms；
各自同RF slkd/bus/peer隔离，USB1345/1431、各22RX/零drop、guest warning0/
taint0/traceoverrun0，host四只结束释放在位。第一 VM保持 Diagnostic already-Off
最后dup关闭→原500ms期限→一次真实IN81 abort/无reset-release-detach，稳定预算
归零；第二VM保持完整原诊断63记录/50proof/46wire/read7/result16/copyout2/poll3/
淘汰33/CLI4/旧注册27拒绝/queued100ms与首次RESULT前被动800ms到期。
Diagnostic hold发生在主RF daemon之前，不证明hold期间同daemon连续性。
USB/HCC/DLI不是独立PHY嗅探；完整传递性host-tool输入来源仍未资格。

[精确源码与日志核对CI38113618256](https://github.com/OpenSparklink/sparklink/actions/runs/38113618256)
九作业终结success，实际170 Rust/34 Python/240工具，32期限/21管理/固件69 C+
12 Rust/descriptor18 C+info5 Rust。离线计数绑定终结构建日志哈希，不重复计Rust
summary；本批编译器warning0、GNU make jobserver warning1、未知producer0，
因此不称整个log warning-free。[上一封存编译计数勘误](evidence/descriptor-cleanup-build-warning-erratum-20261011.json)
明确旧compiler0错误、实际1条unused import，原JSON保持，guest/RF证据独立。

下一步专用实机使用测试进程的有界调度约束证明真实 Queued/opcode0→关闭/取消，
完整UAPI/USB证明无OUT，恢复普通调度并验证peer；不能用调度fixture冒充正常
并发/应用权限。随后暂留真实0c02回复，在实际选中后验证释放/最后fd/dup、迟到
ACK及partial cleanup，记录实际status/errno，不把0x1e/EIO改成成功或无条件reset。
生产有限恢复需按实际原因分类、保留原错误与每port预算；自然启动/重枚举/消失
RCA、无人工拔插完整恢复及历史物理xHCI warning继续OPEN。

三类清单保持：明确测试/默认行为立即删，模拟/注入只在专用测试；有调用者的
backend/parser/默认路由/shared ring/旧UAPI等待新路径接通和回归后删。UAPI未发布，
无需兼容期。完整能力来源、独立事件、drivers-owned backend/PM、socket协商/
背压/所有权、SSAP/每连接安全/Agent/Bond/Profile、四设备两组、Native/Proxy/
sandbox/发布及全部S0–S6/28项原scope保持，北极星7/8，VM-only，不关闭整项、
不合并draft；用户已明确要求继续完整goal，部分成果不代表完成。

## Managed Queued 专用真实设备门禁（待实机执行）

**前置条件勘误（实际 VM fd 执行发现）**：旧探针同时在 Unknown Setup 排入
广播配置与扫描初始化，第二笔实际返回 EBUSY；扫描初始化会短暂启用扫描，
必须先有真实广播 Off 且无 pending 广播操作。旧探针失败证据保留，不能放宽
内核保护或将 EBUSY 算作取消成功。当前 Unknown Setup 子门禁排入合法的广播
配置与扫描 STOP，另严格验证扫描初始化在 Unknown／pending 广播时 EBUSY，
且没有结果记录（ENOENT）。完整扫描初始化排队取消须在正确的 confirmed-Off
前置条件下另行验收；它与 Ready 同伴活动隔离继续 OPEN。因此本子门禁不得
将 `managed_preselection_live_acceptance` 置 true，仅记录精确有限范围。

独立开发支撑入口 `tools/ws73_managed_queue_support.py --prepared <冻结包>
--output <新目录>` 只在签名 kernel 的 scratch VM 中添加两只 `usb-ws73-test`，
不接受 hostbus/hostport。它运行相同 C fd probe 的 release／最后fd／dup 六案例，
保留完整 UAPI、原期限与 USB 抓包；QMP 附着及成功回复必须与两个精确测试对象
一致。collector 显式标记 `synthetic_support`，验证器禁止模拟与真实状态标识
混用，模拟结果不能置 `managed_preselection_live_acceptance`。这里的静态 Setup
peer snapshot 不证明 Ready 同伴活动隔离；普通应用调度、partial 和真实在途
清理仍必须走下面的真实设备门禁。该模式在 daemon 启动前结束，不报告 RF。

新增显式 `--managed-queue-verify --setup-release-verify --fault-recovery`，仅可在
合格的签名模块 scratch VM 内启用。单 vCPU、root 测试探针用小于 50ms 的
FIFO 调度临界区排入两个 typed policy，实际读取 Queued/opcode=0/step=0 后
覆盖 release、最后 fd close、dup 第一次 close 保持 Held 和最后 close。
调度恢复后观察完整 Cancelled/-ECANCELED、Unknown/Setup 保持、peer metadata
及 lease 不变，并核对包括间隙的整个区间两设备零 DLI 流量。

这是特权测试调度支撑，不代表普通用户并发调度验收；不模拟 Complete、Off 或 Ready。
现有两设备普通用户 RF20+2 仍为后续回归门禁。新探针的验证器通过负向测试，
真实设备结果尚待执行。部分初始化及在途 reply 清理、自动恢复和自然故障根因仍开放。

## 部分初始化在途回复探针（待实机执行）

新增显式 `--managed-partial-case release|close|dup` 和
`--managed-partial-domain advertising|scanning`，需要独立 Setup/recovery scratch VM，
与既有 Diagnostic/active hold 门禁互斥。仅暂停真实第一步回复，读取完整 Pending
及 opcode/step，保留原命令500ms期限，在其前触发释放／关闭；dup第一次关闭仍Held。
扫描案例先在同一 Managed 租约中真实完成广播配置／STOP，保留 request2 完整
Succeeded 结果、selected power 及两笔有序成功 Complete 的抓包，再 arm request1
扫描第一步。Pending/Cancelled 时广播保持 confirmed Off、扫描 Unknown；不能
从 untouched Setup 直接假定广播 Off，或把 EBUSY 视为在途取消。格式2强制保存
这段前置证据；旧格式失败原件保留，不能重新包装为通过。广播案例仍从 untouched
Setup 开始。这是修正测试方案，完整真实六案例及 Ready 同伴活动隔离仍待执行。
原真实回复交还后，应只有真实广告／扫描停止及成功 Complete，再Free/Ready；
保留原操作 Cancelled/-ECANCELED。peer持独立Diagnostic租约，前／在途／后三次
真实MAC查询及完整metadata/ownership检查均须匹配。任何原始status、EIO、代际退役
或超时均记失败，不通过忽略错误、合成成功或新注册替代旧cleanup。单案例通过也
不代表整个partial初始化／并发／removal／自动恢复矩阵完成。

本次已有四次实机启动失败，尚未进入新Managed门禁：单vCPU、uhubctl短断电后重试、
原双vCPU对照和另一对设备都在Setup元数据前失败（warm恢复/再次启动均-110）。
延长断电间隔的后续尝试也失败。所有日志、捕获和原始manifest保留在私有.dev。
uhubctl直接执行可用，sudo非交互执行仍要求密码；两次off/on均使四口重新枚举，
这不证明WS73真的冷启动，也不代表自动恢复或根因已解决。后续VM失败现在自动
保存现有boot_stage/error、warm、budget、failure_diagnostics等只读sysfs诊断。

## 独立 VM 维护性寄存器复位（实验支撑，本轮读取失败）

专用 `rebootstrap-init`/`ws73_vm_register_reset.py` 使用现有签名kernel、scratch
NVMe/Btrfs及固件111。只允许显式QEMU scratch root、guest 1-1 WS73且无driver
owner，确认完整VID/PID/runtime endpoints及usbfs ABI；读取volatile reset寄存器
成功且reset位尚未置位时才写入。禁止libws73中读失败后直接写mask的降级。
之后必须在同一guest端口看到真实boot双endpoint、再加载已有WS73模块进行
固件/BSLE/真实DLI元数据初始化；设备消失或期限内不成功均失败。

这是一次性实验维护工具，与默认daemon及正常验收启动完全隔离；无模拟回复，
不代表自然故障RCA、无人工介入自动恢复、Managed cleanup或peer隔离通过。
所有原始控制传输、usbmon、sysfs与错误保留。维护工具暂未纳入生产恢复状态机。

## 维护对照终结状态

六次正常启动和七次独立维护尝试均已终结；新增Managed实机案例为零。
无guest WS73 driver时寄存器读setup在EP02超时，无SoC reset写入；一次精确
目标guest USB reset与EHCI对照亦失败。SDK USB wakeup request2已返回完整4字节
并由usbmon确认四字节零payload，但随后EP02仍超时；PM仅唤醒假设不成立为
充分恢复办法。当前代码未改生产WS73/Host路径，恢复／RCA／cleanup issues开放。

SDK异步寄存器读对照亦未通过：真实EP02 setup与EP82 IN同时提交，等待期限后
两笔以原始-ENOENT取消收敛，没有读回值或SoC复位写入。保留其他三只host
地址不变，但这不是Ready peer运行隔离证据。工具253项本地通过；U81d938f6b7ee
源码CI38118294865九作业全部success，CI不包含硬件验收。新诊断VM已终结失败：只读failure phase17映射为RECOVERY_WAIT_CLOSE，
原始-110、tx_sequence0、metadata_valid0、attempts2/limit2/exhausted1。
只定位到真实SLE_CLOSE回复等待阶段，未查明自然根因。

Uccfa29d7495c进一步严格核对peer完整UAPI字节、清理前／在途／后的查询时间窗
及完整Revoking→Free观察序列；目标失败时独立采集peer，并保留原错误与失败。
全部255工具测试本地通过。新Managed实机案例仍为零，当前peer Ready隔离不能
以host三只仍枚举替代。所有scope、恢复及RCA仍开放。

U44d7fb335c78加入参考实现的36字节HCC队列10选择及聚合重置对照。
独立维护VM第一笔真实EP01 OUT即-110，未执行第二帧／加载WS73模块／写SoC
复位；其他三只仅保持host枚举，不冒充Ready peer验收。本轮共六次正常启动
和七次维护尝试（含一次未接触设备的fixture失败），新增Managed实机案例零。
全部256工具测试本地通过；Uccfa29d的CI38118785456九作业success。源门禁与
硬件资格分开；继续优先启动根因→Queued六案例→partial两个域及三种释放
和真实迟到回复→同daemon双设备RF及四设备。恢复、自然RCA与原整项issues
保持OPEN，历史已封存WS73闭环路径和证据保留。

## 当前 Managed 门禁：USB 对照补充（2026-10-11）

[新封存证据](evidence/ws73-managed-bootstrap-usb-contrasts-20261011.json)补充八次
已终结尝试（七次维护、一轮正常门禁），保留此前失败和真实双设备 RF 证据。
**本批 Queued／partial 实机案例仍为零，当前没有 Ready peer 隔离资格。**
真实 GET_INTERFACE 不支持时保留 EPIPE；以完整描述符限定的 interface0/alt0
重设返回零，但后续两笔配置读取 EPROTO，未继续路由或加载模块。

允许所有枚举 reset 的实验触发五次复位并重枚举，已排除为生产策略。
K a3703a65ea69 的专用 VM 开关默认关闭，单对象最多一次，调用前消费预算，
源码禁止 close/autoscan 补预算，排斥在途 error/hold 注入。固定归档完整七补丁
新应用／幂等／所有前缀／漂移拒绝、实际函数依赖计数、ASan/UBSan 和暂停 QMP
检查通过；新 QEMU 的无 USB scratch-root VM 启动也通过。这些是开发支撑，
真实重新枚举后预算保持及完整自动恢复尚未验收。

第4只一次复位后实际出现 ROM 两端点、bcdDevice1.00；运行态专用探针判失败。
随后正常 VM 识别 ROM，但第一条 READM bulk OUT 即 -110，failure phase1=LOADING、
uploads1、无 metadata；未上传固件，未建立 Setup，未接入另一只。第1只一次
复位仍在运行态，参考 EP01 路由 OUT 超时。冻结111固件输入不代表当前固件版本
查询／上传成功，不能从第4只状态变化推断通用恢复或自然根因。

私有 QEMU 对照仅转发一次物理 SET_CONFIGURATION1，实际 libusb 返回0，但
EP01仍超时。候选没有接入生产，已恢复可变构建源码；精确补丁、二进制、源码、
抓包和失败均保留供复核。默认 Linux/Rust WS73 路径不变。正常门禁继续使用
默认禁止 reset/detach 的对象，不使用实验开关冒充 Managed cleanup。

优先顺序保持：真实独立启动／握手→Queued 两只×release／最后fd／dup 六案例
→partial 广播／扫描×三种释放及真实迟到回复、两个 STOP、Revoking→Free
→同 slkd 双设备 RF 和故障隔离→四设备两组。另一只必须真实活动且查询通过，
仅 host 枚举不算隔离；不以整 hub 复位或人工重插满足自动恢复。相关 issues
及完整 S0–S6 scope 保持开放，部分成果不提前关闭整项。
