# Setup 与 Managed 租约释放及 radio 清理

最新[四设备时序矩阵](WS73_PARALLEL_RF.md)保留默认并行超时和前一核对器 FAIL；
修复 retained OFF 的所属 domain 判定及有时限的同行 abort 后，默认失败重跑
在真实设备上完成四只 STOP、worker 回收、无强杀。它只认证此测试清理子集，
不替代整项 Managed/作者/事件/权限并发、物理拔插或自然故障自动恢复验收。
实际内核 K060011963b5e、服务 Uab1a34b07f1c，冻结工具 Uaf0756d7a484。

此前未触及 policy 的 Setup 修复：Linux `f822db7756d7c99eb6a7d0e1e9e32c513e91ad71`。该批镜像K`f822db7756d7`／编译U`ccb3d34ae1bc`的
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
原真实回复交还后，广播案例要求两域真实 STOP；扫描案例保留此前已证明的
广播 STOP/Off（整个前置至清理区间不允许额外 target 命令），只发送仍未知的
扫描 STOP。不要求重复已确认 Off 的命令，不伪造新 Complete；再Free/Ready。
保留原操作 Cancelled/-ECANCELED。peer持独立Diagnostic租约，前／在途／后三次
真实MAC查询及完整metadata/ownership检查均须匹配。任何原始status、EIO、代际退役
或超时均记失败，不通过忽略错误、合成成功或新注册替代旧cleanup。单案例通过也
不代表整个partial初始化／并发／removal／自动恢复矩阵完成。

专用支撑入口 `ws73_managed_queue_support.py --partial-case release|close|dup
--partial-domain advertising|scanning` 在无 host USB 的签名模块 scratch VM 中
运行同一 collector；`--idle-scan-stop-reject` 切换明确的模拟拒绝分支，失败原件
保留，不归零 status。正常模拟分支和拒绝分支都须执行，不能以模拟通过代替
真实固件资格。格式3显式区分 synthetic_support，记录完整 hold_acknowledgements；
模型只保留原始终结队列帧，不是实际成功 libusb IN81 hold，独立 method/日志/属性
及 USB 哈希核对禁止混用。相同 kernel fd 路径的实际开发支撑结果见下文；静态
Setup peer 的三次查询也不代表活动 Ready peer 或 RF，整项实机条件继续开放。

上述开发支撑现已执行：U f35ba6c／签名 K292 镜像的两个域×release／最后fd／
dup 六个第一步案例通过；原始模拟终结帧 hash 与交还后的 USB 抓包一致，
原期限未续期，Cancelled 保持，广播两域真实模型 STOP／扫描保留前置广播 Off
后模型 STOP，以及 Revoking→Free 都有实际 kernel fd 证据。它只覆盖第一步，
不是所有初始化步骤。U476ffcf 的新冻结包六个拒绝案例均保留 VM FAIL；独立
验证器严格要求最终 RecoveryBlocked、status0x0b、opcode1002、-EIO，以及
Faulted/credits0、Cancelled/Unknown、前／在途／后三次同伴匹配查询。不得将
任意失败视为预期拒绝，不能把拒绝结果改成成功／Off／Ready。首次负向运行在
guest 前因 Unix socket 长路径失败，原件保留并独立归为基础设施失败；socket
现移至短私有目录，进程 join 后清理。274工具测试及 Uf35 CI 九作业通过，
当前源头和执行冻结头分别记账。所有开发支撑均为模拟 USB，真实矩阵仍开放。

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

## 当前有限支撑执行结果（2026-10-11）

[完整字节及资产哈希](evidence/ws73-managed-queue-support-and-bulk-submit-20261011.json)
保留旧探针实际 EBUSY 失败，修正后的模拟 USB／实际内核六个 release／最后
fd／dup 案例通过，289 包完整抓包、零丢包，取消区间两个设备零 DLI。每个案例
另有两次非法 ScanInitializeOff 的 EBUSY/ENOENT 负向证明；全部仍 Unknown／
Setup。运行于冻结 U40ab1d15fa83 工具、签名 K292 镜像、编译 Ud749 服务包；
当前源码 K a370 的变化是测试依赖。源头、镜像和模拟资格均在证据中分开。

partial 扫描前置修正当时提交 Ucc3be5b，268工具测试通过，当时尚无该新路径的
VM／实机在途通过；后续模拟结果见下文。CI38123259995（U4fc）及38124100001（U40ab）已终结 success，
只提供源码支撑。实机 libusb 诊断仍是提交后超时、cancel/reap -ENOENT 和零
传输；未新增 Ready 或 Managed 实机案例。真实完整队列／partial／活动 peer／
普通用户 RF 回归和自动恢复、自然 RCA 继续开放。

## 第一阶段 partial 模拟 fd 矩阵封存（2026-10-11）

[完整证据](evidence/ws73-managed-partial-model-fd-matrix-20261011.json)封存六个
成功案例及六个独立拒绝案例，均使用模拟 USB 与实际签名内核 fd 路径。
广播／扫描各覆盖 release、最后 fd 关闭及 dup，暂停的都是初始化第一个步骤。
原模型终结帧、QMP 交还和 USB 抓包的字节／SHA 匹配，原请求保持 Cancelled。
扫描前置广播 Off 有原成功回复证明；同伴三次真实内核查询保持一致，但同伴
仅 Setup/Diagnostic，并非活动 Ready 或空口证明。

六个拒绝案例保留原 VM FAIL、STOP status 0x0b、-EIO、RecoveryBlocked/Faulted，
不能改写为 Free/Ready。另一次 Unix socket 过长导致的 guest 启动前失败独立
保留。274工具测试与 Uf35 CI 九作业通过；源码 K6c2、验证器 U86a、镜像 K292、
服务 Ud749、冻结工具及 QEMU hash 分别记录。没有新增真实 WS73 Managed 通过。
真实在途 libusb 回复、后续初始化步骤、活动同伴、自动恢复及自然 RCA 继续开放。

端点诊断另使用显式 `ws73.clear_halt_lab=1` 维护 VM。完整配置／五端点描述符
合格且 guest interface0 独占后，只对 EP01/EP81 各执行一次 CLEAR_HALT，随后
重读原配置；不与 interface rebind、USB reset、SDK wakeup 或 SoC 写入混用。
错误立即保留并停止。原 QEMU 忽略 `libusb_clear_halt` 返回值，guest ioctl 零
不能单独确认物理成功；需私有观察器实际返回与抓包独立核对。它不是生产恢复，
也不能建立 Ready、活动同伴或 Managed 验收。源码 278工具测试通过，实际结果
按独立 manifest 记录。

[真实端点对照](evidence/ws73-clear-halt-route-diagnostic-20261011.json)已终结：
EP01/EP81 实际 libusb 返回均零，69包零丢包抓包证明两个 CLEAR_FEATURE 完成，
前后完整运行态配置一致。但第一笔36字节路由 OUT 仍 errno110，USB取消回收
-ENOENT、host transferred0；未发第二帧、未加载模块或写 SoC。原 FAIL 保留。
parent/hub/target suspend-time 增量零，四只 host inventory 一致；不能当作
活动 Ready peer。私有观察器补丁／二进制封存，默认可变源码和二进制已精确
恢复。标准端点清理没有恢复本次传输，不能据此宣布自然根因或自动恢复完成。

寄存器只读对照另使用 `ws73.register_async_read_lab=1`，可加专用
`ws73.register_clear_halt_lab=1` 清理固定 EP02/EP82。后者必须与复位、SDK唤醒、
interface rebind 和路由模式互斥。异步 OUT16／IN4 保持原 ctypes URB／buffer
至取消完成或独占 fd 关闭，分别保存提交、完成、原错误、取消请求／回收及
关闭诊断；只读失败不降级为寄存器写或模块启动。源码／模型回归不能替代
实际 libusb 返回与 USB 抓包核对，两只真实 Ready／Managed 条件仍开放。

[两轮真实寄存器对照](evidence/ws73-register-read-contrasts-20261011.json)已终结：
基线与 EP02/EP82 清理后均在 OUT16／IN4 同时在途时超时，原 TimeoutError 与
两个取消回收保留；清理的实际 libusb 返回均0、完整配置不变，host 两笔 bulk
均 transferred0。guest 失败 OUT 的 actual=16、IN actual=0 原样保存，不能
解释为物理成功；QEMU 在提交前复制 OUT 数据，失败时字节数不代表已送达。
未写寄存器／复位／加载模块，四只 host inventory 一致；真实 Managed 仍零。
维护累计18，正常门禁仍7；283工具测试及 Ud8f CI 九作业通过仅提供源码支撑。
当前数据失败也涉及独立寄存器通道，不能仅归因于路由 recipe；设备／固件／
host／QEMU 自然根因及独立自动恢复继续 OPEN。

完整扫描初始化排队门禁新增显式 `--confirmed-off`／
`ws73.managed_queue_confirmed_off=1`。两只先在各自 Managed 租约内完成广播
配置／STOP、扫描参数／START／STOP，记录完整结果及同 generation Ready/Off。
随后在同一 CPU 的有界 FIFO 区间先排入扫描初始化、再广播配置，保持扫描
准入的无 pending 广播前提；release／最后fd／dup 都要求完整 Queued→Cancelled，
零已选 opcode/step，初次 dup close 仍 Held，最终 Free 且原 Off 不变。
USB核对必须保留两只原初始化的每笔成功回复及参数，禁止初始化后至门禁结束
发生额外目标命令。原 Unknown Setup／扫描 STOP 子门禁继续保留，格式2不能
冒充格式3完整初始化。此为开发支撑；仍需真实设备、活动 Ready peer、普通
调度并发、partial 后续步骤和 RF 验收，实际执行另以 manifest 判定。

[完整队列模拟 fd 执行证据](evidence/ws73-confirmed-off-queue-model-fd-20261011.json)
已封存：两只各完成五笔原初始化命令／成功回复，release／最后fd／dup 六案例
实际 Queued→Cancelled/-ECANCELED，ScanInitializeOff count3、广告配置 count2，
零已选 opcode/step；dup 初次关闭仍 Held，最终 Free 与原 Ready/Off 完整字节
保持。369包零丢包，原初始化结束至矩阵完成各目标零额外 DLI。模型仍开启
idle STOP 拒绝，保留 Off 没有依赖宽松模拟 STOP。冻结工具 U502、验证器 U55a、
签名镜像 K292、编译服务 Ud749 及 QEMU hash 分开。286工具测试通过；只证明
有界 FIFO／一CPU 模拟支撑，未增加真实 Managed／活动 Ready peer／普通并发
或恢复资格。既有真实路由／寄存器失败、partial 第一步及 Unknown Setup
证据不覆盖重写；后续初始化步骤、真实在途回复及完整实际 RF 仍需执行。

[后续终结帧模型选择支撑](evidence/ws73-later-terminal-model-selector-20261011.json)
记录 K092 的默认0、有界0..2 skip选择与只读消费计数。早期原帧正常交还，
只有后续原终结帧保留；Status/credit不消费，reset不补已消费预算。实际函数
clang ASan/UBSan/LSan与暂停QEMU的五类类型/范围/只读/未打开拒绝通过，实际
QEMU已构建冻结。访客、timer/wakeup/digest计数替代不算调度／物理证据；
暂停对象也未运行内核。前几次夹具编译／GCC库环境／运行器异常分类失败保留。
当时**后续步骤采集器、格式迁移及内核fd VM仍未接通／执行**（本批结果见下文），不能记扫描START
在途清理通过。已有第一步与完整队列证据保留，真实 Managed／恢复／RCA仍OPEN。


## 后续 partial 模拟 fd 矩阵（2026-10-11）

[本批封存证据](evidence/ws73-managed-later-partial-model-fd-20261011.json)包含九个
成功与三个独立拒绝案例：广告最后STOP、扫描START和扫描最后STOP，各覆盖
release／最后fd／dup。格式4只允许模拟USB后续step1/2；先前格式3十二案例
用新验证器全部复核。原500ms期限、完整UAPI Cancelled/-ECANCELED、早期
成功回复的power／SHA／长度、保留帧、命令窗口及同伴三次查询逐一核对。

扫描START取消后由新STOP确认Off；扫描原最后STOP取消后由其迟到成功回复
确认Off，无重复STOP，原请求不改为Succeeded。六个扫描案例均开启模型idle
STOP拒绝。广告最后STOP后仍需清理未知扫描域，三个idle拒绝案例保留原FAIL、
0x0b/-EIO、RecoveryBlocked/Faulted和Unknown，不伪造Free/Ready。289工具测试
及源码905b318的九个CI作业通过；签名镜像K292、编译服务Ud749、工具源码与
新测试QEMU分别封存。正式Linux/Rust WS73路径未改，历史真实RF证据保留。

本批未在真实USB执行实验门禁，只读核对四只仍枚举且有效主机权限正常：前三只
五端点runtime，第四只两端点ROM，power active。模拟同伴为Setup/Diagnostic，
尚无活动Ready／真实空口隔离；新增真实Managed通过数仍零。正常实机门禁7、
维护18的失败历史保留，既有ganged hub重枚举不证明VBUS/SoC冷启动或单设备
自动恢复。本批模型结果不改变这些资格，相关issues继续OPEN。

下一优先级仍为定位真实bulk超时并恢复两只独立启动／查询，然后执行完整
Queued及partial实机矩阵，核对活动Ready同行、同slkd普通用户RF20+2及四设备
两组。仅有新诊断假设时执行受控对照，有限重试和原始失败记录不能被模型
成功替代。原生Linux对照因VM-only约束仍未执行，自然RCA和每设备自动恢复
未通过；全部原S0–S6与14项整改范围不缩减。


本批[主机只读观察范围补充](evidence/ws73-managed-later-partial-host-scope-20261011.json)
明确记录调用stock `uhubctl -f -l 1-2.1`读取hub状态，未带action、未切换电源。
原封存证据“no new physical USB transfer”措辞过宽，限定为没有新增诊断bulk／
寄存器／固件／实验驱动传输；模型VM没有接host USB。原证据文件保持不变，
这次主机观察不增加真实Managed、Ready同行、RF或恢复资格。


## 真实 EP0 只读 credit 对照（2026-10-11）

[两只实机的完整诊断证据](evidence/ws73-readonly-ep0-credit-20261011.json)封存端口
1-2.1.2及1-2.1.1的独立VM：SDK class/interface IN request5各一次，均返回原
四字节00000000，HCC高优先级内存credit=0。每轮65包零丢包，原USB提交/成功
完成回执、actual usb-host req0xa105/length4及libusb控制回执匹配；零目标bulk
及class OUT，无复位／hub循环、SoC写入或WS73模块加载。完整runtime配置与
四只主机枚举、parent/hub/target suspend计数保持。这里只验证控制读取，
不算活动Ready同行、RF、每设备恢复或本次固件版本查询。

该结果证明本次SDK EP0控制读取可完成，而先前EP01/EP02 bulk仍有明确失败
证据。原HCC memory-credit零值不能改成默认值，也不能当成DLI command-credit
或Ready ACK；SDK data流控另外保留USB控制buffer，不能仅据零值认定路由／
寄存器bulk超时根因、强行开放流控或盲发RESET_BCPU。111文件SHA头静态校验
通过，但反汇编存在未识别扩展且关键USB路径调用ROM，缺少复位callback/ACK
证明；不提交SDK、固件或反汇编字节。私有验证器最初把QMP hostport当完整sysfs
路径，失败日志保留；修正为精确hostbus/hostport后复核原两轮，没有重跑VM或
改写原结果。

292工具测试与源码0a096ee九个CI作业通过。保持VM-only与历史真实WS73路径，
正式Linux/Rust行为未改。正常启动门禁仍7，维护尝试增为20；新增真实Managed
通过数仍零，当前没有双设备Ready／活动同行证据，所有恢复/RCA及原整项保持
OPEN。下一步需核对供电路径及成功状态基线/ROM分发或HCC资源初始化的可追溯
证据，再选择受控实机对照。不能靠重复ganged hub重枚举或模型通过代替根因。

## 当前实机门禁：ROM 首包也超时，供电拓扑已确认（2026-10-11）

[ROM 启动原失败与独立抓包核对](evidence/ws73-rom-startup-timeout-20261011.json)：
第4只两端点 ROM 模式在新隔离 VM 使用正式 K292 驱动，第一笔19字节
`READM 0x40019380 4 ` OUT 即超时，phase1/-110；77包零丢包，原取消回执-2。
失败 OUT 的 guest actual19 不代表物理成功；没有寄存器写入、111上传或 Setup。
第3只未接入，Managed release／最后fd／dup／在途及活动Ready同行均未执行。
正常启动累计8、维护20，新增真实Managed仍0；本批无hub循环或生产代码变更。

用户确认 hub 无外接电源、WS73 无其他供电线路；该事实不等于测量了 off 时
VBUS。ROM首包失败也不能仅用运行态HCC memory-credit0解释。现有ganged hub
整组切电仅是受授权的维护操作，不能作为隔离单只恢复实现或验收。

原boot budget记录uploads1、attempts0/cause0/result0，而boot_error=-110：
启动路径尚无已验收的有限恢复，预算result也未反映此次错误。整改须明确每阶段
可安全重试的边界、总期限、原错误记录及重枚举等待；部分固件/寄存器写入不能
直接重放。先定位共同bulk故障并恢复真实查询，再执行完整Managed和活动同行
门禁。自然RCA、无人工恢复、四设备及整项issues继续OPEN，历史RF证据保持。


## 2026-10-11 冷启动对照、真实队列子门禁与 partial 清理拒绝

[新封存证据](evidence/ws73-managed-cold-real-progress-20261011.json)保留原失败：
用户报告 hub/WS73 只有 USB 供电，并将上游物理断开至少 30 秒后重接；四只重新进入
ROM，两只在同一冻结镜像输入上成功上传 1.10.111、真实 DLI 查询。人工冷断电只用于
对照，不算自动恢复，也未实测 VBUS；先前软件 off/on 未恢复 bulk 的根因继续开放。

真实 Unknown Setup 的合法队列子集六案例、两域完成真实初始化/Off 后完整初始化队列
六案例分别核对 release、最后 fd 关闭和 dup。受控单 CPU/FIFO 窗口内未选中请求均保持
Cancelled/-ECANCELED，完整矩阵区间两只零 DLI；这不等于普通调度并发。两次各 20+2
随机空口轮次由抓包独立核对，应用同 UID1000/caps0、同 slkd，围绕人工 guest IN 错误；
不用于关闭自然恢复。冷启动第一次原宿主验证误用 ROM 旧地址，原 VM FAIL 不改写；
另一次 usbfs 所有权检查过严的捕获未封存失败亦保留，已修复精确 live fd/当前地址门禁。

首个真实 partial 广播 release 在原 C02 回复被保留后取消；原 C02 迟到成功及 C05 STOP
成功，但多余的未初始化 scan STOP1002 返回 0x0b，原目标 Faulted/Unknown、旧请求
Cancelled/-ECANCELED 保留。另只三次真实 MAC 查询与 Setup/Diagnostic 身份保持，
仍不是活动 Ready 同伴；剩余五案例当时未执行，不作为通过。

Kbea9fc6527f8 新修复保留每 Runtime 实际选择域的历史，撤销仅执行已选择/已知域；
跳过 untouched Unknown 只结束该域撤销等待，不制造 Off/Ready。24 项实际 Host 源码、
19 项严格命令计划及 296 项工具回归通过。U8e20b69 新 `--managed-selected-cleanup`
只用于实际第一步 partial、显式版本5记录：广播单域清理后 scan Unknown/Setup；扫描
已有真实广告 Off 前置，仍需扫描真实 STOP。原历史格式3/4、模型和失败证据保留。

新生产镜像尚未取得物理资格。初次复制目录构建因缺工具重新配置后丢失 CONFIG_RUST，
构建产物资格检查明确拒绝；原日志/配置保留，恢复已验证配置并重建后才可继续。
下一依赖：匹配镜像/签名模块的空USB启动检查 → 实际 release/last-fd/dup 与在途回复
→ 活动 Ready 同伴前/中/后真实工作 → 同 daemon RF20+2及拔插 → 四设备两组。
正常启动 VM 累计12、维护20，不归零历史失败；自动恢复、自然 RCA、完整 Managed
与原各 issue 整项仍 OPEN。VM-only，无主机实验安装、无生产模拟成功或固件字节发布。


## 2026-10-11 真实 partial 新镜像进展与扫描参数清理细化

[不可覆盖的新实机证据](evidence/ws73-managed-selected-domain-real-20261011.json)：
编译 Kbea9fc6527f8、服务 Uf04e6bba2233、冻结采集器 U0c609d0 的广播 release/last-fd/dup
三个案例完整 PASS，各有实际保留的原 C02 frame SHA、Cancelled/-ECANCELED、真实 C05
Off、scan Unknown/Setup、Revoking→Free、三次同行真实查询和同 daemon 普通用户 RF20+2。
首次新镜像的抓包窗口误计同行查询导致原 VM FAIL，单独独立核对成功、不改写原状态；
U0c修复窗口后重跑三案例，扫描 release 则保持真实 STOP1002 0x0b/-EIO、Faulted/Unknown
失败，最后两案例未执行。正常启动 VM 累计17、维护20，整项/活动 Ready 同伴仍未通过。

参考 Host/WS73 接口明确区分 SetScanParam1001 与 EnableScan1002。新 K4ece91aa5c7c
将同一 Runtime 单调选择历史细分为广告、扫描参数、扫描控制：新 Runtime 仅选择过参数
时，取消等待原回复并清掉未选择的 START，扫描保持 Unknown；任何扫描控制历史或已知
扫描状态仍需真实/保留 Off 屏障。不是把0x0b解释为Off，也不将参数配置当扫描已关闭。
新 U5d29cb7 显式版本6扫描参数门禁检查无额外START/STOP、保留原广告Off和scan Unknown；
历史格式3/4/5、原失败和模型仍保留。25实际Host源码、19命令计划、299工具测试通过，
新合格Rust镜像/签名模块空USB VM加载卸载通过；编译器零警告、保留一条make jobserver警告。
新六案例正在独立冻结镜像上执行，尚不能计作新修复实机通过。后续真实初始化步骤、活动
Ready同伴、普通调度并发、四设备两组、自然自动恢复/RCA仍按原整项条件OPEN。VM-only。


## 2026-10-11 第一初始化步真实六案例通过；活动 Ready 同伴仍是下一门禁

[最新不可覆盖证据](evidence/ws73-managed-scan-parameter-real-20261011.json)以编译内核
K4ece91aa5c7c、服务/冻结工具U5d29cb7b3aa5完成广告/扫描各 release、最后fd关闭、dup：
六个原VM均PASS/QEMU0，原在途host成功帧SHA/长度与迟到Complete一致，原请求保持
Cancelled/-ECANCELED，dup首次close保留lease、最后close触发撤销，Revoking→Free。
广告只执行C02+C05、未触及scan保持Unknown；扫描先有真实广告Off，持有原1001配置
回复后取消，零已选START/STOP，scan保持Unknown/Setup。既不推断0x0b为Off，也不制造Ready。
每例三次同行实际MAC查询与身份保持；各1183/1187包零丢包，taint0、无内核fault。
每例同slkd/bus、普通UID1000/caps0随机RF20+2及人工guest IN故障支撑由捕获独立核对，
合计132轮；未使用人工拔插、hub切电或主机实验安装。原构建资格拒绝、抓包验证FAIL和
两种真实STOP0x0b失败完整保留。正常启动VM累计23、维护20。

**只验收初始化第一步六案例。** Unknown Setup/confirmed-Off未执行队列真实各六案例
仍是受控单CPU/FIFO支撑；普通调度并发未验收。本批同行仍Setup/Diagnostic，不能把MAC
查询或后续RF偷换为目标撤销期间活动Ready隔离；后续原广播最后STOP、扫描START/最后STOP
的物理门禁仍待执行。整项Managed、恢复/RCA及28项原scope继续OPEN，goal active。

下一门禁先用同行真实C02/C05/1001/START/STOP建立独立Ready，再持有同行Managed lease。
在目标原回复被保留期间让同行真实扫描START成功、保持On跨越目标release/last-fd/dup与
迟到回复清理；目标Free后核对同行同generation、Ready、owner和On，再STOP及重启扫描。
以完整命令/Complete窗口和radio状态证明工作持续，无跨设备STOP、换generation或重启daemon。
随后扩展后续原终结帧、普通调度取消/结果淘汰及四设备两组。25实际Host源码、19命令计划、
299工具测试与K4ece空USB启动通过；U5d CI38140975482九作业success，最新证据提交CI另核。
自然启动超时/重枚举/消失RCA和无需人工拔插的每设备恢复仍开放；原生主机对照受VM-only约束未执行。

### Real Ready peer cleanup gate (hardware result recorded below)

`ws73_target.py run --managed-ready-peer --managed-selected-cleanup`
with `--managed-partial-case release|close|dup` and the existing separate
Setup/recovery VM gate now initializes the second controller using five actual
advertising/scanning commands. For scanning targets also select
`--managed-scan-parameter-cleanup`. The peer holds its own Managed lease, starts
and stops scanning before the target hold, then keeps scanning On across target
cancellation, original late reply and the Free observation. Afterward it must
retain the same Ready registration/owner/current radio state and complete another
STOP/START/STOP sequence before releasing its lease.

Format 7 records preserve complete syscall inputs/results and causal intervals.
Capture verification requires all fourteen peer commands and successful replies,
rejects extra commands/replies (including cross-device STOP), and separates boot
metadata from the test window. This gate is development tooling in an explicitly
selected scratch VM; it introduces no production simulation or fake success.
Its existence and fixture tests alone do not establish hardware acceptance; the
six-case physical result is recorded below. The
previous six real first-step cases and original failures remain valid historical
evidence. Later initialization steps, ordinary queue concurrency, natural fault
recovery and the complete Managed issue remain open.


## 2026-10-11 第一初始化步：真实 Ready Managed 扫描同行隔离六案例通过

[独立实机证据](evidence/ws73-managed-ready-peer-real-20261011.json)
SHA256 `dbc48ecd6f748b75e7d70d61336e87da8337554c2cfd97de5cbca07f91b5e69f`，
编译内核 K4ece91aa5c7c、服务 U5d29cb7b3aa5、冻结工具 U44bf694f2652。
广告/扫描第一初始化步 × release/最后 fd 关闭/dup 六个原 VM 都 PASS、QEMU0；
每例同行先真实五命令初始化 Ready，独立持有 Managed lease，在目标保留原回复期间
真实 START 并保持扫描 On，跨越目标取消、原迟到回复与 Free。目标 Free 后独立
ioctl 仍观察到相同 generation/完整 Ready/owner/current On；继而实际 STOP/START/STOP
成功，才释放同行 lease。查询请求203的 radio 字段由当前 Host 状态填写
（`sparklink_core.rs::ioctl_discovery_result`），不是复用历史成功结果推断 On。
每例十四条同行命令与成功 Complete 精确匹配，整个窗口拒绝未记录命令/回复及跨设备 STOP。

目标原 held host 成功 IN 帧 SHA/长度与实际迟到 Complete 一致；原操作始终
Cancelled/-ECANCELED，dup 首次 close 保留 owner、最后 close 撤销，Revoking→Free。
广告目标只有 C02+C05；扫描目标先真实广告 Off，再只有原1001参数配置，无未选
START/STOP，扫描仍 Unknown/Setup，未制造 Off/Ready。
每例1207/1211包零丢包、taint0、无kernel fault；同slkd/bus、UID1000/caps0
RF20+2随机标识/数据/地址/RSSI成功，共132轮。人工 guest IN错误是开发支撑，
不等于自然故障自动恢复；本批无人工拔插、共享hub循环或主机实验安装。
25实际Host源码、19命令计划、303工具测试通过；U44bf694 CI38143384779九作业success。
正常启动VM累计29、维护20，历史失败不归零。

只通过**第一实际步骤 partial 六案例的活动 Ready 同行隔离**；整项 Managed 未完成。
下一优先顺序：confirmed-Off未选择队列取消期间同行保持 Ready/Managed/scanning On，
两角色 release/最后fd/dup，quiet区间两只零DLI且前后实际启停成功；继续保留
单CPU/FIFO限制，普通调度并发另验收。随后实际广告最后STOP、扫描START/最后STOP的
held回复/三fd/Ready同行，需真实原USB帧skip/hold/hash证明，不能用模型Complete替代。
再当前镜像物理拔插、四设备两组、结果淘汰和自然自动恢复/RCA。
之前三份证据及原0x0b拒绝、捕获窗口失败、不合格构建仍保留。
28项原scope、两个draft、自动恢复/自然超时-重枚举-消失RCA和历史xHCI warning继续OPEN；
原生主机对照受VM-only约束未执行，完整goal active。

### Ready scanning peer around never-selected queue cancellation (physical result recorded below)

`ws73_target.py run --managed-queue-verify --managed-queue-confirmed-off
--managed-queue-ready-peer` in the separate Setup/recovery VM gate performs two
actual five-command bootstraps, then both target roles and all three fd cases.
Each case starts the independently Managed peer scanner before the quiet window,
observes its complete ownership/current On before, inside and after the FIFO
section, and only after target Queued→Cancelled/Free issues peer STOP/START/STOP
and releases that lease. Format 4 records preserve all actual inputs/results.
The six quiet windows require zero DLI commands/replies/failures on either
controller. Between windows only the exact recorded peer commands and successful
replies are allowed; the complete bootstrap-to-final-release interval rejects
unmatched traffic. Ordinary scheduler concurrency remains a separate gate.
Old formats and immutable evidence remain intact. This is explicit development
VM tooling; no production backend or success event is simulated.


## 2026-10-11 未选择队列取消：双角色活动 Ready 扫描同行六案例通过

[新独立实机证据](evidence/ws73-managed-ready-queue-real-20261011.json)
SHA256 `dcb672a9adc8b5e8726ec54d7a6ac42bb8d625a97594605858206fa97c92d38a`。
编译内核K4ece91aa5c7c、服务U5d29cb7b3aa5、冻结工具U9a3b29c；原VM
FAULT_RECOVERY_SUPPORT_PASS、QEMU0，探针六案例全成功。
两只实际五命令初始化Ready；两种目标角色各release、最后fd关闭、dup。
每例同行先独立持有Managed并以真实CFG/START开始扫描，在目标Queued→Cancelled
及Free的完整窗口前、FIFO内、窗口后，实际ioctl都保持相同generation/Ready/owner/current On；
随后真实STOP/START/STOP成功，同行再实际释放为Free。错误token仍EPERM，dup第一次
close保持owner及Queued，最后close撤销；取消结果opcode0/step0/-ECANCELED，未选择执行。

十条实际bootstrap命令及三十六条同行活动命令/成功Complete逐项核对；六个约350ms
完整取消窗口两只均零命令/回复/失败；间隔只允许精确记录的同行活动，整个bootstrap
到最后同行释放区间拒绝多余命令、Complete或失败。FIFO关键段约0.041–0.101ms，
每例恢复SCHED_OTHER；这是受控单CPU开发支撑，**不等于普通调度并发通过**。
1307包零丢包、taint0、无kernel fault，同slkd/bus、UID1000/caps0的RF20+2通过。
306工具测试及严格C编译通过；25实际Host源码、19命令计划保持已有验证。
正常启动VM累计30、维护20，失败与旧证据不归零。

此前第一实际步骤partial六案例及活动Ready同行隔离、132RF仍有效，原Unknown Setup
队列子集6、confirmed-Off静默队列6、0x0b拒绝和捕获/构建失败全部保留。
当前仅通过受控未选择队列及第一实际初始化步骤的fd/同行门禁，**整项Managed仍OPEN**。
下一优先：真实广告最后STOP、扫描START/最后STOP，分别release/last-fd/dup及Ready
同行，保留原500ms deadline，需真实host成功USB帧skip/hold/hash证据，不用模型Complete。
随后普通调度/结果淘汰、当前镜像物理拔插、四设备两组、自然自动恢复/RCA及完整S0–S6。
VM-only不变；人工guest IN错误仅作开发支撑；上游人工冷断电只是诊断，VBUS未测，
软件切电未恢复bulk、自然启动超时/重枚举/消失根因仍OPEN；不执行共享hub循环代替单设备恢复。
28项原完整scope、两个draft未合并、整个goal active。

### Later original physical replies (nine-case result recorded below)

`--managed-real-later-step 1|2` requires the explicit selected partial gate and
`--managed-ready-peer`. Advertising uses only step1 (original final STOP);
scanning step1 holds original START and step2 holds original final STOP. This
format8 gate remains separate from all synthetic support and historical formats.
The host selector delivers one/two earlier successful original IN81 frames, then
retains the next original frame; each host hash/length must match the captured
Complete for that recipe step. All state/readbacks and original acknowledgments
are preserved; no model Complete can qualify this gate. The original operation
remains Cancelled, the 500ms deadline is unchanged, and only required Off barriers
are allowed. Actual Ready Managed peer scanning spans cancellation/late reply/
Free with exact successful peer traffic before and afterward. Fixtures cover nine
step/fd combinations and rejection of wrong budget/hash/device/extra frames,
model substitution, missing earlier replies, duplicate STOP and peer omission;
they do not establish hardware acceptance.


## 2026-10-11 真实后续初始化步骤九案例通过；CI夹具失败保留并修复

[九案例独立实机证据](evidence/ws73-managed-later-real-20261011.json)
SHA256 `a44921486b773a9b58cb82e8a400d21a2d70ddbcaba8f5327dad46ae28423e5b`。
编译内核K060011963b5e、服务/冻结工具U7bd441625951、QEMU二进制
`d53eb3d1b583ff87e26cc7aec1d5f4655867d0e0891bb2beb761172f8ba35ac3`。
广播原最后STOP、扫描原START、扫描原最后STOP，各release/最后fd关闭/dup，九个
原VM全PASS/QEMU0。每例前一/两条实际成功host IN81原帧照常交付，随后保留原成功帧；
所有skip/held帧长度/SHA与对应实际Complete逐项一致，selector预算/armed/held/released
host/guest原完整读回一致，零bounded release/drop/error，原500ms deadline不变。
原请求始终Cancelled/-ECANCELED，dup第一次close保留owner、最后close撤销，Revoking→Free。
广播仅C02/C05，未触碰扫描Unknown/Setup；扫描已有真实广告Off，原START取消后只发
必要STOP，原最后STOP的迟到成功保留为Off屏障，拒绝重复STOP或假Succeeded。
同行每例实际五命令Ready，独立Managed并scan On跨越取消、迟到回复和Free，之后
实际STOP/START/STOP成功；十四条同行命令/Complete完整匹配，无跨设备STOP/未记录交通。
每例同slkd/bus、UID1000/caps0、真实随机RF20+2成功，共198轮，抓包零丢包、taint0、
无kernel fault。没有人工拔插、ganged hub重置或主机实验安装。

311工具回归与选择器实际函数ASan/UBSan依赖夹具、完整补丁链、暂停无匹配QMP属性
检查通过；新Rust/SparkLink/Virtual关闭构建及签名模块空USB VM双加载卸载通过。
编译器零警告，一条make jobserver警告保留；早期selector夹具编译错误、sandbox LSAN
限制、私有编译路径/ccache失败和构建记录log描述形状拒绝均保留，不冒充资格通过。
U7bd CI38147959246原failure也保留：共享runtime-error callback夹具漏加selector字段，
非实机失败。独立副本完整固定档案链/ASan/UBSan验证修复通过；K53a49a9bbfe4仅补零初始化
计数字段、不放宽断言，CI改为固定修复HEAD并重新验证，最终结果按精确HEAD另记录。

此前第一步骤partial+Ready同行六案例132RF、未选择队列+Ready同行六案例22RF及旧
Unknown/confirmed-Off静默队列各六例、原0x0b拒绝/捕获失败均有效且不改写。
正常启动VM累计39、维护20。当前通过受控队列和所有三个初始化recipe后续步骤的
三fd/原held帧/活动Ready同行门禁；**整项Managed、普通调度并发/结果淘汰仍OPEN**。
下一优先为普通调度与结果淘汰、当前资格镜像物理拔插/daemon不中断、四设备两组并行，
再继续完整S0–S6连接/SSAP/Profile、安全/Bond/PHY、drivers-owned backend/PM、
Native/Proxy/sandbox/发布验收。原生主机对照受VM-only约束未执行。
自然启动超时/重枚举/设备消失、软件off/on未恢复bulk、历史xHCI warning的RCA与无需
人工干预的单设备恢复继续OPEN；人工冷断电只是诊断且VBUS未测，人工guest IN错误仅
开发支撑。28项原scope及两个draft保持OPEN未合并，完整goal active。


## 普通调度下的未执行替代队列与结果淘汰门禁（待真实执行）

新增 `--managed-ordinary-eviction`，必须同时选择真实 first-step partial、
selected cleanup、活动 Ready peer；扫描使用 parameter-only cleanup。格式9
不接受模型、后续 selector、单CPU/FIFO或缺少任一完整原始记录。两CPU scratch VM
里 hold 一条原成功 IN81；先提交一个同域替代请求，读回原 Pending 请求变为
Cancelled，再让两个 SCHED_OTHER 线程通过 owning File 的独立 dup fd，各提交
32个不重复ID。直接 ioctl 故意绕开 Python adapter 的用户态 RLock，核对与
canonical C UAPI 的编号一致；不改变生产绑定的串行约定。

65个替代请求使64项终态结果表发生真实淘汰；广告原ID/首替代ID、扫描再加先前
初始化结果必须 ENOENT，不能恢复为新成功结果。其余64项包含唯一实际 Queued
替代请求和63项未选择 Cancelled；两个线程的实际 ioctl 调用时间窗必须重叠，
worker dup 均真正关闭，仍未执行的替代请求 opcode/step/power保持0。分别
release、最后fd关闭、dup首次关闭保留owner/末引用撤销后，64项全部
Cancelled/-ECANCELED；原回复排空和实际清理后仍保持。完整前/后集合与原
supersession Cancelled字节独立保留，不投影成已淘汰ID的实际结果。

复用同一份实际 USB recipe/host SHA验证；广告只原C02及必要C05，扫描先实际
广告Off、原1001且零未选择START/STOP。完整500ms原期限不延长；65替代burst
限定200ms，提交到释放仍小于400ms。活动同行跨原held回复/取消/Free保持
Ready/Managed/current scanning On，随后真实STOP/START/STOP。每新VM还需
同slkd/bus、普通UID1000/caps0的随机RF20+2；人工guest IN错误仅开发支撑。

开发支撑验证完整六个role/fd组合、错误/缺失/错身份/假成功/假Ready/额外
命令/错held SHA/同行失败/无实际调用重叠，并保留原历史格式。待六个原
source runner全部终态且独立USB/RF核对后，才记录此限定普通调度子集通过。
整项Managed、daemon运行中原hold、物理拔插、四设备两组和自然自动恢复/RCA
仍保持OPEN；完整S0–S6及28项原scope不缩减。


首轮广告三fd实际通过；扫描首次完整initializer替代被EBUSY拒绝，原FAIL/同行
Ready观察及未执行两例保留，不能作为通过。修为先核对重复initializer的
EBUSY/ENOENT无admission，然后使用合法同域STOP作65个未选择替代请求；不
放宽生产can_initialize_scan，不执行该STOP，也不制造scan Off。ABI测试首轮CI
失败由于忽略SPARKLINK_KERNEL_SOURCE，仅修为采用与runner相同的显式内核路径。
新扫描镜像和独立原source runner通过后才更新资格，旧失败不覆盖。


## 2026-10-11 普通调度的真实替代队列及结果淘汰六例通过

[独立原始证据](evidence/ws73-managed-ordinary-eviction-real-20261011.json)，
SHA256 `ecf708552083431d5280d94878379a00790f496679a07b79fe52f930f5a577e3`：广告/扫描各release、最后fd关闭、dup，六个
实际source runner PASS/QEMU0。两CPU、两个SCHED_OTHER线程，每例实际ioctl
时间窗重叠43–57对；65个同域合法替代提交耗时0.84–1.23ms。原在途请求先
Cancelled，再被真实64项终态表淘汰；原ID/首替代ID（扫描再加准备ID）
在release前/后和迟到回复排空后均ENOENT。其余64项仅最后一个实际Queued，
释放后全部Cancelled/-ECANCELED，opcode/step/power0，无未选择命令逃逸。
原提交到取消128–170ms，不延长500ms原期限；dup第一次关闭仍Held，末引用
关闭Revoking到Free。实际host成功IN81原SHA/长度与原回复一致。

广告只有原C02和必要C05，扫描先实际广告Off、原1001，零未选择START/STOP；
扫描仍Unknown/Setup，不制造Ready。活动同行跨原held回复/取消/Free保持同
generation/完整Ready/Managed/current scanning On，每例14条真实命令/
成功Complete，随后STOP/START/STOP。同RF slkd/bus、UID1000/caps0随机
RF20+2，共132轮均在10秒内匹配标识、数据、地址、RSSI；零抓包drop、taint0、
无kernel fault。hold发生在RF daemon前，不能据此宣称daemon并发在途验收。

原扫描initializer替代失败EBUSY及未执行两例保留；修正后先实际核对
EBUSY/ENOENT无admission，再以合法同域STOP作未选择替代，不放宽生产
can_initialize_scan。原首批广告冻结Ue18b25aa9c1b，新扫描冻结U542f7ae311ae；
编译内核K060011963b5e、服务U7bd441625951，生产源码哈希一致，QEMU d53eb3d1b583。
原prepare错误module-tree父目录参数保留（无VM/USB执行），新独立输出修正。
316工具回归、25实际Host、19命令计划支撑保持；ABI测试忽略显式路径的
CI38150415339失败及随后sparse checkout缺头文件的CI38151129591失败保留。
修正只补 canonical pinned UAPI 依赖，U303b94c50260 CI38151508403九项成功；
证据HEAD后续CI单独核对。正常VM累计46、维护20，失败不归零。

[原后续步骤九例/198RF](evidence/ws73-managed-later-real-20261011.json)及
此前静默/活动Ready队列、首步、0x0b拒绝与捕获窗口失败证据保持。
当前通过限定于普通调度两个提交者的替代/淘汰/释放子集，**整项Managed和
完整并发/事件/权限/移除仍OPEN**。下一优先为daemon运行中的在途取消与作者
生命周期、当前资格镜像物理拔插/slkd不中断、四设备两组，然后自然
启动/消失RCA和有限单设备非人工恢复，以及其余完整S0–S6/28项原验收。
VM-only不变；人工guest IN错误只是开发支撑，hub切电和人工冷断电不是
自动恢复验收。未查明根因、历史xHCI warning及恢复事项继续OPEN，部分成果
不关闭整项、两个draft不合并。


## slkd 运行中的普通客户端取消与 Managed 排空

首个真实 `supersede` VM 的普通 `scan off` 返回固件 `0x0b`：原参数
1001 回复实际成功，未执行 START 的扫描 STOP 被拒绝。原请求保持
Cancelled/-ECANCELED，STOP 不成功；整例 FAIL，另一例未执行，原输出和
捕获保留。不能把这个状态当作 Off，也不能改成功判据。

新增 `slctl --adapter <path> cancel-discovery` / D-Bus
`CancelDiscoveryPolicies` 明确取消选定 Ready WS73 的两项 discovery policies。
它复用生产 Managed release/revoke/drain，等待真实内核清理后重新取得权限；
已有确认 Off 的内核屏障可保留，无需无效 STOP。它返回实际 handoff 的
registration generation，不创建成功 STOP/Complete 或新 operation ID。
原请求 ID 的结果保持可查询。非 Ready/未支持 backend 明确返回不支持。

RPC、bootstrap 和 Node removal 共用每设备唯一 credential/admission gate，
不持 SharedState/directory 锁跨 ioctl/排空；阻塞 ioctl 自己保留 gate，RPC
放弃不会提早交权。一旦 cancel 开始，即便调用者退出，独立 bounded task
也完成排空。清理/重新取得权限失败保留错误与日志并禁用该设备提交；
移除先撤下注册，再等待该 gate，不能因取消恢复旧注册的业务权限。
内核仍是 lease、radio、generation、reply 和 Ready 的状态来源。

`--daemon-hold-case supersede|caller-exit` 在独立真实 recovery VM 中验证：
普通 UID1000/caps0 随机 RF20 后保持同 slkd/bus。暂留原成功 IN81，实际
scan on Pending/1001/0-of-2；caller-exit 实际 SIGKILL/reap 原 slctl 后原操作
仍 Pending，客户端退出不撤销 daemon 的 File。另一个真实 Ready 设备在
hold 期间启动扫描并保持 On。普通 `cancel-discovery` 使原请求 Cancelled，
取消 CLI 必须仍等待原 reply。400ms 内 release，不延长500ms原期限；
原参数 Complete 后才确认 handoff，原 ID 仍 Cancelled，无目标未选择
START/STOP、虚构结果或跨设备命令。随后同 daemon 人工 guest IN 错误支持
和 RF2 单独核对；它们不替代自然故障或物理拔插验收。

[新镜像真实双案例证据](evidence/ws73-live-daemon-managed-cancel-real-20261012.json)
SHA256 `81ed71737254b74704f276fd57c081491095961db4334d9a22cf357fae692192`：
原客户端在线/退出两例均 source runner PASS、QEMU0，并独立核对完整
USB 窗口、真实原帧 SHA/长度、原取消结果和同行 On。原回复分别在
186.1ms/200.6ms 内明确释放，不延长500ms原期限。两例同 slkd/bus、
普通 UID1000/caps0 的 RF20+2 共44轮通过，随机标识/数据/地址/RSSI均
在10秒内匹配，capture各1179/零drop、taint0、无 kernel fault。
实际编译 K060011963b5e/新服务及冻结工具 U9cdccd942e21/QEMU d53eb3d1b583，
新服务源码/策略哈希一致；新镜像独立文件输出，旧服务与原 FAIL 不覆盖。
原普通 STOP0x0b VM 为另一独立失败，初始 RF20 不计入新通过44轮，
后续恢复/RF2未执行，原下一案例未执行。

320工具回归、完整Rust170项及新生产admission两项通过，严格clippy通过；
[精确U9cd CI38154578944](https://github.com/OpenSparklink/sparklink/actions/runs/38154578944)
九项成功。busy/disabled/removed/unsupported-fd用例不产生成功 ioctl；它们
是源码支撑。沙箱 Unix socket 禁止、首次缺测试 dbus-daemon 的本地失败保留，
随后私有 session bus 完整重跑通过，不安装主机服务。正常VM累计49、维护20。

本批只验证 first scan-parameter held reply 和原客户端生命周期。**放弃取消
CLI本身、取消/移除及其余RPC并发仍未实机验收**。完整Managed/作者/权限/
事件/removal、当前镜像物理拔插、四设备两组、自然RCA/无人工恢复及其余
S0–S6/28项保持OPEN。VM-only；部分成果不关闭整项，两个draft不合并。

## 取消调用者退出与 busy 拒绝：新双案例资格

`slctl management` / `GetManagementStatus` 读取当前选定 kernel File 的
实际 MANAGEMENT_QUERY，仅返回 generation/mode/state/flags/errno/status/opcode。
不返回 lease token，不用 daemon credential 缓存替代内核结果，也不持 admission
锁；因此可以在原 reply 未排空时观察 Revoking。flags1 表示该 File 实际拥有
权限，不能把 Free 或另一个 File 的 Held 解释为已恢复 daemon 的管理权。

新 `--daemon-hold-case cancel-caller-exit|cancel-busy` 沿用独立真实 recovery VM：
原请求先被取消且原 CLI 返回 ECANCELED，再分别实际 kill/reap 取消 CLI，或
由第二个普通 CLI 请求取消并要求立即 busy 失败。原 reply 仍被暂留时，
内核必须仍 Revoking；取消 CLI 退出不伪造 handoff 成功。实际 release 后，
普通 CLI 查询必须看到同 generation、Managed/owned Held，再实际扫描
START/STOP 验证业务权限。另一只真实 Ready 设备保持 scanning On，完整
目标窗口仅原1001和排空后的1001/START/STOP，busy请求无额外DLI。

在取消调用者退出案例不要求被杀 CLI 伪造成功输出；通过实际内核状态与
后续成功业务证明交权。管理查询不消费原 operation result。500ms 原 DLI
期限不延长，host/QMP/捕获原SHA和所有时序独立核对，RF20+2同daemon/bus
作为单独 gate。历史 schema2 的双案例证据继续可离线验证；新 lifecycle
案例必须 schema3，不能将旧 token 字段或缺失观察记录默认成成功。

复现时使用已资格化的新服务包和 signed module tree 准备独立 `PREPARED`
目录，再分别执行（`PREPARED`/`OUT` 为自己的独立输出目录）：

```sh
python3 tools/ws73_target.py run --prepared PREPARED --output OUT \
  --ports 1-2.1.4 1-2.1.3 --timeout 450 --fault-recovery \
  --setup-release-verify --daemon-hold-case cancel-caller-exit
# 另一独立 VM/OUT 使用 --daemon-hold-case cancel-busy；首失败停止批次。
```

[新实机作者生命周期证据](evidence/ws73-daemon-cancel-author-real-20261012.json)
SHA256 `70b9c6f4be10eee572cdaabd338d1f0cbc687dfd38b7eaa86ba51b29639ab9a1`：
取消CLI实际SIGKILL/reap与第二个取消实际busy失败两例均通过，source runner
PASS/QEMU0，独立核对原host帧SHA/长度、完整target四条与peer三条DLI。
被杀取消CLI没有伪造确认；实际观察同generation Revoking/flags0保持到
release后，再实际Managed Held/flags1，随后target真实扫描START/STOP成功。
另一只独立Ready保持scanning On，原operation排空后仍Cancelled/-ECANCELED。

新镜像编译K060011963b5e/服务及冻结工具Uab1a34b07f1c，QEMU d53eb3d1b583，
source/策略哈希一致。两例同slkd/bus、普通UID1000/caps0各RF20+2，共44轮
随机标识/匹配数据/地址/RSSI在10秒内，capture零drop、taint0/无kernel fault。
实际held window时间和逐包证据见JSON，不改500ms原DLI deadline。322工具、
完整Rust174项、4项 production admission/query 与严格clippy通过；
[精确源码CI38155998741](https://github.com/OpenSparklink/sparklink/actions/runs/38155998741)
九项success。首次新fixture遗漏同步nested completion timestamp而被严格guard
拒绝的原FAIL保留，修正fixture后重跑通过，未放宽生产或捕获判据。
原schema2双案例已用新verifier重新读回，proof完全相同，旧资格不倒填为
新镜像完整矩阵。正常VM累计51/维护20，失败不归零。

上述双案例批次没有执行取消/移除并发或该镜像物理拔插。当时安排的下一独立VM门禁将暂留原
reply并启动cancel，再只移除目标的guest USB对象，要求取消实际失败且
无虚构generation确认、旧选择退役、同行仍可控制，重接后新Ready及同slkd
RF。此QMP退役是开发支撑，与人工真实物理拔插、自然设备消失RCA和有限
非人工单设备恢复分开。其余RPC/admission/result/event/权限并发、四设备
两组和完整S0–S6/28项保持OPEN，VM-only，部分成果不提前关闭整项。


## 2026-10-12 取消中移除目标：真实双设备 guest 生命周期支撑

[独立读回的真实设备证据](evidence/ws73-daemon-cancel-removal-real-20261012.json)
SHA256 `9b71ad70680c975c1c10f7d6e0bcceb21e93867915cc0bf0b6ed5cc6534d6859`。仅 `--qmp-hotplug --daemon-cancel-remove` 专用 VM 模式：
普通 UID1000/caps0 的 slctl 发扫描；暂扣原真实成功1001参数回复后，
原请求先返回 Cancelled/-ECANCELED，实际管理查询为 Revoking。只删除目标
`ws73_0` guest owner，取消 RPC 必须实际返回 ENODEV，不得输出
NativePoliciesCancelled。原host缓冲区178字节只丢弃一次，DROP与HOLD的SHA
相同；完整guest捕获仅原1001 OUT，没有目标成功Complete、START或STOP。
同行保持原generation Ready/scanning On，实际查询和STOP成功，QMP未修改
同行对象，其hold/error计数保持零。只重加原物理端口，全部host/guest reset
及kernel-driver-detach关闭，新generation Ready，旧选择重接后仍被拒绝。

最终source runner PASS/QEMU0和独立最终JSON重算均通过：目标generation1→3，
同行一直generation2；同slkd/bus普通用户RF20+2，共22轮随机标识/数据/地址/
RSSI在10秒内匹配，捕获1279包/零drop、taint0、无kernel fault。实际编译
K060011963b5e、服务Uab1a34b07f1c；冻结工具U7bcc7866c368，当前K4ee4af55f38c
仅selftests变化，生产内核和69份用户态/策略源码哈希一致。专用QEMU
SHA256 `05a3b654eb2801ed1ddb60fc6c6fa9bd5cd48eefa8194f999170eab90b26185a`。
实际host回调四条取消/abort清理路径通过ASan/UBSan/LSan，无重放/双重free；
无USB边界和签名模块隔离启动均通过。329工具测试；
[精确源码CI38159520269](https://github.com/OpenSparklink/sparklink/actions/runs/38159520269)
九项success，包括完整Rust、严格clippy和release build。

host/guest墙钟不假定相等：原子marker/ack交叉约束offset为789.5–799.5ms，
保守原请求到delete上界206.37ms，原500ms DLI期限不延长。保留三次实际
尝试，其中两次不验收：首次直接跨墙钟比较导致原runner FAIL；第二次
在线PASS后重复初始化清空最终manifest，独立读回拒绝并撤回临时结论。
原文件不改写、不倒填；移除重复初始化，最终落盘前JSON重算拒绝缺失或
变化的proof，再以新冻结镜像重跑通过。历史STOP0b、EBUSY、超时和warning
证据保持。正常VM累计54/维护20，失败不归零。

复现需要使用带DROP诊断补丁的专用QEMU、匹配该QEMU的隔离native-root
boot smoke，以及已验证的签名module tree/service bundle准备新的PREPARED；
不能复用旧QEMU哈希的boot proof。随后只运行独立VM：

```sh
python3 tools/ws73_target.py run --prepared PREPARED --output OUT \
  --ports 1-2.1.4 1-2.1.3 --timeout 450 --qmp-hotplug --daemon-cancel-remove
```

VM退出后以`ws73_daemon_removal.verify_sealed_record`重算最终manifest和
run.json，捕获用`ws73_capture.read_capture`，RF另由`corroborate_passthrough`
验证。只认原runner终态与独立读回均通过，不能仅凭console PASS宣称验收。

本项是**真实无线设备上的QMP guest退役支撑**，不算物理拔插、自然设备
消失根因或自动恢复。此前release/最后fd/dup及Ready同行矩阵保留原资格，
不能倒填为本镜像完整矩阵。下一优先为当前资格镜像物理拔插/slkd不中断、
四设备两组并行、其他RPC/result/event/权限并发，同时继续自然启动超时/
重枚举/消失RCA与有限非人工单设备恢复。最新冷断电回复仅保留用户报告，
当前枚举地址与既有基线一致，不追加冷启动成功次数；VBUS未测。完整S0–S6、
28项原scope/14项整改/旧代码三类清理保持，未发布UAPI迁移后删除继续。
自动恢复/根因未明/整项Managed仍OPEN，部分成果不关闭整项；goal active，
VM-only，两个draft不合并。
