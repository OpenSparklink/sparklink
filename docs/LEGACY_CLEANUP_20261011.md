# 旧内核实验实现：调用审计与清理清单

最新源码复核与新镜像回归（K`f5f83d7eb970`／编译U`8641ec61e804`）见[当前分层、整改与验收边界](BLUEZ_RECONCILIATION_20261011.md)；历史源码和证据范围保留，完整 S0–S6／自然恢复仍开放。

审计日期：2026-10-11。基线 Linux fc0b4d1a44b6、用户态 157ec71c3b9a；
后续 Linux 376bb1e8a544 / c2c4aa4ad0bd 和用户态 9f57d1e / 34b54fd 已整改部分
生产调用链，以下分别记录原调用链、当前实现、
迁移条件及限定回归。UAPI 未发布，无兼容期。

## 立即删除：生产测试行为及错误完成

| 对象/调用链 | 本批措施 | 验收状态 |
|---|---|---|
| core ioctl_dispatch_security → SecurityInner::start_pairing；workers PairInfo/Option/Random/Confirm/DHKeyVerify → SecurityInner | 删除固定 nonce、ECDH 失败测试密钥降级和未验证 proof 的 Paired 转移；旧步骤 reset 后 EOPNOTSUPP，调用者不得发送认证成功回复 | 376bb1e8a544：实际编译和错误 proof/截短公钥/乱序步骤拒绝回归通过；完整每连接安全仍开放 |
| sle_crypto Rust wrappers → sle_crypto_ffi.c；security KDF/CTR/RPA 和 core 查询调用者 | Result 传播原 errno、检查长度/计数；CTR C 临时缓冲完整成功后才提交数据/IV；失败不提交 keys/counter/address | 376bb1e8a544：实际函数分配/算法/密钥/部分写入失败注入及 sanitizers 通过；不是标准密码算法验收 |
| core SEC_SM3/SM4/HMAC_TEST ioctl → SecurityInner 测试辅助/CTR counter=0 | 移除生产执行，返回 EOPNOTSUPP；删除 SecurityInner 测试辅助，迁算法/错误覆盖到 selftests；编号/绑定随调用者迁移删除 | 376bb1e8a544：生产执行已删；旧调用者/UAPI 与正向向量迁移仍待完成，不能用旧 ioctl 成功测试证明生产能力 |
| backend SleController::open/send_command/send_data/reset → UART/SPI 自制 CommandComplete(Success) | 删除伪成功及仅编码却报告发送成功；无真实硬件实现的操作 EOPNOTSUPP | c2c4aa4ad0bd：实际 trait 方法拒绝回归通过，虚假 firmware/capability 已删；纯 framing 留作测试，不宣称硬件支持 |
| slkd config → main defaults，未消费策略 | 显式配置错误拒绝；不支持的非默认策略拒绝。不得静默降级安全 | 9f57d1e 已签名推送：启动前拒绝无效/未知配置和未实现策略，10项配置/实际进程测试；完整策略仍待实现 |

## 移入测试：保留有效开发支撑

| 内容 | 专用位置/边界 | 状态 |
|---|---|---|
| crypto FFI 故障注入、私有状态计数检查 | tools/testing/selftests/sparklink；编译实际 Rust 包装/security 及实际 CTR C 函数，依赖用可控 stub，明确非 RF/非算法向量 | 已通过，stub 不编入生产内核 |
| UART/SPI 纯 codec、分片/边界 | selftests framing；硬件未接通不能用 codec 或本地 Complete 替代支持 | 待保留/迁移有效用例；伪 Complete 直接删除，无业务价值 |
| 核心 Virtual、连接/SSAP 模型及注入 ioctl | 专用 Virtual backend / selftests；相同 Runtime、生命周期和契约 | K1/K19 待迁；不先删除有价值失败用例 |
| QEMU 一次 bulk IN81 错误、autoscan/re-enum/open 故障工具 | 已在专用 qemu-sle-dli 和 VM 工具；默认关闭、单对象 guard、有故障边界回归 | 保留；人工故障支持与自然根因/自动恢复验收分开 |
| Profile callback 阻塞/cancel/drain/panic 测试、transport codec | 34b54fd移到slk-experimental；默认daemon无运行时依赖，无旧服务注册/actor。显式实验feature保留profile0注册和连接callback，Native不注册；请求回调仍未接通 | 实际actor/codec回归保留，严格all-target/all-feature测试，不加全局allow(dead_code)；服务互通仍待验 |

## 等待替代：先迁调用者及回归，再删除

| 旧路径/调用者 | 唯一替代所有者与删除门禁 | issues |
|---|---|---|
| 原core CONN_SEND → conn.send 入 tx_queue + controller.send_data；队列无消费者/handle0错误 | 75b77fc19613已删影子TX ring/重复直发，统一单次backend提交、句柄映射及成功记账，短写/长度拒绝；实际函数回归通过。仍待每通道socket、真实可靠/credit/分片/断链/权限/旧generation及数据实机，迁调用者后删旧UAPI | K4/K17，R03/R10；完整验收OPEN |
| 原workers SERVICE_MGMT/动态reliable与core remote ioctl → 旧wire Engine；local staging留待迁移 | 4d8a0d61673d77c5fd104d219346e0a2d3e23ef2已删除未达标准的wire Engine、无界累积器/无归属通知与method echo，历史codec仅selftests，remote不支持。最终slkd标准Engine/数据库与kernel PDU socket仍待权限/预算/deadline/credit/ACK/Profile及实机门禁；本地staging及旧编号在调用者迁移后删除 | K6/K17、U3，R04/R07/R08 |
| SecurityInner controller-local 状态、SEC_ENCRYPT_ON 提前提交；Bond 仅元数据 | 每连接机制/匹配真实完成，Agent/policy/Bond 用户态；错误 proof、安装拒绝/超时、restore/revoke、真实互通后删旧状态及控制接口 | K7/K18、U5，R01/R02/R09 |
| core legacy read_iter → 旧 event dequeue/copy；Native subscription 另一实现 | 独立订阅、完整记录 copy 后提交、移除唤醒；迁 lib/工具 read 调用者，坏地址/部分 copy/短 buffer/多订阅后删旧队列/UAPI | K3、U2，R12 |
| backend enum、core USB/serdev 注册；serdev 回调忽略 ctx/全局 parser | 可引用 Backend 注册接口，bus 在 drivers；parser/waiter per-runtime+generation；USB=n/m、driver y/m、Virtual卸载和 WS73 原路径后删枚举/全局切换 | K1/K4/K9/K10/K12，R11/R13 |
| slkd transport 未消费、Profile/HID read/write/notify 未路由、过时配置和文档 | 接通、明确实验隔离或删除；保留有效 codec/生命周期测试，严格 check/test/clippy/fmt/release，不以 allow(dead_code) 消除报错 | U3/U8，R14 |

## 每批门禁和证据

本批只约束不可靠能力，不声称完成安全、其他总线或 SSAP。每批签名小提交记录
调用者、删除范围、回归、开放条件，推送后更新现有 issues 的实现/开发测试/实机/
未决状态；不关闭整项。旧源码历史由 git 保留，故障证据文件不删不覆盖。

WS73 Native HCC/BSLE/discovery 生产实现不改；新内核必须重新 VM 启动并用两只
真实 WS73 20 轮交换随机广播/扫描，再检查恢复/幸存者。编译或 fixture 不能证明
真实路径未退化。自然恢复/根因未明继续开放，四设备、服务 sandbox 未验收。
架构迁移按 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)。

### 首批新镜像复核证据

[新镜像回归](evidence/ws73-vm-cleanup-regression-20261011.json)：Linux c2c4aa4ad0bd，
完整 image/modules 构建无 warning；私有签名模块在空 USB VM 两次加载/卸载、
taint0/无 warning。新 VM 真双设备20+2轮全部匹配（最长624ms），一次人工
IN81故障后 generation1→3、幸存generation2不变，slkd PID525/start339不变；
1163 USB记录/零drop，host独立核对22份 RX。应用 UID1000/caps0，最终两只
STOP_CONFIRMED。没有本次物理拔插、自然根因或全自主恢复验收，北极星仍7/8。

实际Rust安全失败测试6项 + C CTR五阶段错误/ASan/UBSan/LSan、后端2项、Python
C/Rust布局/ioctl/32位ABI29项通过。新增CI生产代码失败门禁和同步kernel pin；
远端执行结果须单独核对，用户态39个warning/严格CI仍未闭合。旧正向配对/crypto
ioctl用例尚未迁入算法测试后端，不把其移除或失败改记为成功。R06–R14继续推进。

### 未接通用户态模块的隔离

[实验边界](EXPERIMENTAL_CODE_BOUNDARY.md)：旧Profile/HID/transport移到独立
slk-experimental；默认daemon运行时依赖图无该crate，默认停止旧内建服务注册。
显式experimental-legacy-profiles保留profile0旧注册/实际actor；Native profile1
仍不注册。原模型和actor回归保留，R07/SSAP请求路由/互通等待替代，不宣称完成。
严格检查覆盖default及all-targets/all-features，不增加dead-code lint压制。

本批R04/R08详细范围见[SSAP路径限制](SSAP_LEGACY_CONTAINMENT.md)；删除不可靠旧行为不等于替代Engine已经完成。

### 权限调用者迁移与实机复核

bde171beb2e0/aece3407e1c1将旧Profile声明和实际library/D-Bus调用入口统一到
[验证权限类型](SSAP_OPERATIONS.md)：保留位、descriptor缩窄及超长值拒绝，
不新增第二套Engine。2052组C/Rust/Python语义矩阵及实际syscall/锁前拒绝通过。
[新镜像20+2实机](evidence/ws73-vm-ssap-operations-regression-20261011.json)与
[9作业CI](https://github.com/OpenSparklink/sparklink/actions/runs/38081123658)
通过；默认daemon仍不链接实验Profile。残余local staging/旧UAPI、每peer数据库、
全局默认设备/总线枚举和内核现有global dead_code仍按替代门禁处理，未记为已清完。

### R12 read消费修复与旧DLI迁移

20f431f54af0修复实际read_iter，完整copy才提交head/delivered；无调用者的
drain_to_buf已删，dequeue只作私有提交。copy/锁模拟限selftests，9项实际代码
开发门禁通过。[调用审计](EVENT_COPY_REMEDIATION.md)区分Native typed subscription
与legacy EventReceiver的DLI_POLL_EVENT；后者先pop再copy和backend直读fallback
尚待替代，不能因read修复提前删除其有效测试或关闭完整事件issue。

本批[新镜像20+2](evidence/ws73-vm-event-copy-regression-20261011.json)和
[9作业CI](https://github.com/OpenSparklink/sparklink/actions/runs/38082158063)通过，
仅证明新代码边界开发回归及WS73真实路径保持；不替代live VFS或旧DLI迁移验收。

随后`3a6669114069`增加专用C selftest，`6c06b8f9ef83`接入VM测试工具；
[7类实际read门禁](EVENT_COPY_REMEDIATION.md#live-vfs门禁及新镜像验收)通过，
坏地址/部分复制保留记录及统计由独立fd逐字节核对。真实WS7320+2轮也保持。
该测试仅编入selftests；生产没有注入、伪造成功或额外状态来源。三类清单不变：
旧DLI_POLL_EVENT和调用者仍等待独立订阅替代，迁移后删除；完整事件/移除和
自然恢复仍OPEN，不能因read门禁通过保留两套长期生产消费路径。

### R09 PHY模型/提前加密清理

`f16ac912a8ff`/`f1704a2e44dc`删除生产默认PhyConfig与setter/模拟查询，隔离MCS/
MIMO/旧PHY codec到专用selftests，删除无人调用PHY/空参数加密命令helper。
8个旧PHY/SINR入口与adapter-global加密enable不支持，后者不改凭据/计数/状态。
仍有调用者的ChannelMap/Hopping保留等待连接迁移，并删phy模块global lint压制。
见[调用关系、开发回归及重新开放条件](LINK_STATE_REMEDIATION.md)。本批不把
拒绝未接通能力称为完成PHY/安全，也不删除有效历史测试或关闭整项issue。

[清理后新镜像](evidence/ws73-vm-link-state-cleanup-20261011.json)及固定提交9作业
CI通过，真实20+2/7类read保持。生产phy模块不再编入MCS/MIMO/PhyConfig模型；
待迁移的connection channel/hopping、security全局上下文和DLI路径仍明确记录。

### R12 Native query 调用者迁移（整项仍 OPEN）

[诊断结果迁移](DIAGNOSTIC_RESULT_MIGRATION.md)按 fd 作者、精确 generation 和
Host captured local sequence 查询，不出队/确认共享事件，copyout 失败可重试。
删除 slkconfig query 的 stale drain 与旧 poll；32槽完成结果有界保留/替换，
超长失败、超时失败、sequence 用尽拒绝。专用10项实际代码边界测试通过，
依赖 fixture 不替代实际 ioctl/CAP/退役验收。其余旧 DLI 调用者仍等待迁移，
先接通回归再删旧实现；部分成果不能关闭完整 R12/K3/U2 或自然恢复 issue。

### R12 当前限定 diagnostic 实机门禁（2026-10-11）

Linux `49cabad043f6` / 编译用户态 `d8c091a4b243` 的
[诊断迁移记录](DIAGNOSTIC_RESULT_MIGRATION.md#当前限定实机门禁通过完整-issue-仍-open)
与[新镜像证据](evidence/ws73-vm-diagnostic-live-20261011.json)补齐16个实际
syscall case、4次实际slkconfig查询和8组独立USB命令/回复。退役Runtime在租约
检查前返回ENODEV；原fd继承的UID1000/caps0子进程、另一个持自己Diagnostic
租约的root fd均拒EPERM；只读/部分输出EFAULT后的104字节结果重试保持。
模拟只在selftests；新测试程序仅在显式隔离VM运行，没有生产成功注入。

7类legacy read及真实20+2轮仍通过，最长606ms、22份RX/1279 USB零drop、
同slkd与幸存g2不变；9作业CI实际169 Rust/33 Python/155工具/诊断fixture11。
前两轮测试环境/证明窗口FAIL原记录保留。限定门禁通过不删除仍有调用者的
旧DLI路径，也不关闭R12/K3/U2：下一步补齐admission copyout可找回/幂等、
cancel/deadline及剩余消费者迁移，回归后删除重复实现。自然故障根因、完整
无人工拔插恢复、socket/SSAP/每连接安全/Bond/Profile/Proxy及全S0–S6仍OPEN。

### Native diagnostic admission 身份与取消（开发门禁，实机待复核）

[新提交契约](DIAGNOSTIC_ADMISSION.md)用调用者预先持有的request ID找回copyout
失败后的admission；保留重试不重发/不续期，淘汰旧ID拒绝ESTALE。取消排队命令
保持FIFO，在途取消保留真实Host回复槽，超时/取消/Host错误保留本地errno。
Native旧输出seq-only提交入口不支持，C/Rust/Python、CLI和专用probe同步迁移。
开发测试通过不引用K49/Ud8旧镜像证明新语义；完整实际取消/迟到回复及剩余DLI
迁移继续OPEN，当前真实路径须用新镜像独立回归。自然恢复根因和完整S0–S6不缩减。

[当前新入口回归](DIAGNOSTIC_ADMISSION.md#当前新镜像路径回归限定通过)已用Kc89/
编译Udf9新冻结镜像复核metadata8、结果syscall16、read7和真实20+2，最长620ms，
同daemon/幸存g2保持；固定源码9作业CI通过。新提交copyout幂等、实际取消/
迟到回复尚未验收，不能把已有结果copyout门禁当作提交门禁。迁移及完整issue
继续OPEN，自然恢复根因与S0–S6范围不变。原失败构建/环境记录保留。


## 最新限定提交故障验收与 BlueZ 分析复核（2026-10-11）

再次收到的BlueZ分析与已采用文本SHA256相同，ADR 0001和最终每通道socket、
用户态SSAP/服务/Profile、安全机制/策略边界保持；未发布UAPI可同步替换，
不保留永久双实现。基线更新为Linux `372d3cbcd557` / 编译用户态 `ee2793301e9a`。
[限定提交故障证据](evidence/ws73-vm-diagnostic-copyout-20261011.json)证明只读/
部分输出EFAULT后同ID取回原seq、三次重复完整返回，提交/完成各一次；完整
窗口实际USB只有一个OUT/成功Complete。结果16/CLI4/wire8/read7和真实20+2
保持，同slkd/幸存g2不变，最长620ms、1279 USB零drop；9作业CI成功（170
Rust/34 Python/159工具）。生产Kc89/Udf9未变，本批仅selftest/验证与证据。

实际淘汰旧ID、取消/迟到回复/期限/并发及剩余legacy DLI迁移仍待接通和回归，
随后删除共享结果/事件和重复UAPI。自然启动/重枚举/消失根因、无人工自主恢复
及历史xHCI警告继续OPEN；VM-only和北极星7/8不变。按严重程度继续拒绝未支持
安全/服务能力，生命周期与旧代码清理并行；socket/用户态SSAP/每连接安全/
Bond/Profile/四设备/其他Native/Proxy及全S0–S6保留全部原验收。


## 最新诊断槽淘汰与剩余旧入口审计（2026-10-11）

K78e729c06a5e/编译U2dfd6bd09e7b的[证据](evidence/ws73-vm-diagnostic-eviction-20261011.json)
补齐第二作者fd的33次真实metadata与旧ID三次ESTALE/旧seq ENOENT；保留ID2
完整40/104字节不变，100.261ms拒绝窗口零命令/回复、统计不变。33次填充各
唯一wire且全范围含间隙无额外命令；既有copyout2/result16/CLI4/read7、真实
20+2最长621ms/1411 USB零drop、同slkd及幸存g2保持。9作业CI日志170 Rust/
34 Python/165工具；生产Kc89/Udf9未变。这是限定顺序槽替换，不是完整事务验收。

[剩余调用审计](DIAGNOSTIC_RESULT_MIGRATION.md)
该批K78/U2df审计确认旧DLI_POLL_EVENT先消费后copy（含backend fallback）；后续修复见下文，EventReceiver、
profile0 C/Python/slkd、--legacy及旧raw selftests需迁移。新诊断结果不自动修复
旧入口；下一步分别闭合复制失败、统一订阅、实际取消/迟到/期限，再删共享队列
和重复UAPI。自然启动/重枚举/消失根因、自主恢复、物理xHCI警告、四设备及
完整socket/SSAP/安全/Bond/Profile/Proxy/S0–S6继续OPEN，VM-only/北极星7/8不变。


### R12 旧 poll 消费顺序修复与后续删除

Linux `54621800ee4c`修复共享ring的peek/copy/commit，并在同一ring暂存backend
fallback事件；复制失败后可重试，未增加生产模拟。实际代码依赖fixture新增6项，
read_iter原9项保持。详见[修复、锁与溢出边界及实机门禁](EVENT_COPY_REMEDIATION.md#旧-dli-poll-过渡修复k54621800ee4c实机故障门禁待执行)。
此处仅记录实现与开发测试，新镜像真实WS73回归和legacy ioctl/fallback实机故障
门禁待执行。先接通独立订阅调用者再删除旧ring/fallback/UAPI，整项R12仍OPEN。
最终职责及socket/用户态SSAP依赖按ADR0001；自然故障根因、自主恢复、历史
xHCI warning、四设备和全部S0–S6范围保持，VM-only不变。


K54621800ee4c/编译Udc8745986044的[新镜像回归证据](evidence/ws73-vm-legacy-poll-copy-20261011.json)
现已封存：真实20+2最长621ms、UID1000/caps0、同slkd、read7、result16/copyout2/
淘汰33及41组诊断wire通过，1411 USB零drop、warning0/taint0；9作业CI成功。
这一结果更新上文“新镜像回归待执行”，不更新legacy ioctl复制故障/fallback
资格门禁：它们仍待执行。详细锁、overflow、测试边界与最终删除条件见事件整改。


### R12 Native 旧 poll 实际复制故障限定通过

K9b16e634bfd3/编译U1d3a17b688ee的[新镜像证据](evidence/ws73-vm-legacy-poll-live-20261011.json)
验证真实MAC seed ID5..7/seq5..7，坏地址/只读页/128字节前缀EFAULT后256字节
原事件重试、成功后EAGAIN及一次提交/完成记账。每项唯一真实OUT/回复，并
核对整体三项阶段含间隙没有额外命令。Native共享ring之外的backend fallback
未验收，完整kernel并发/lockdep/移除/所有权及调用者迁移仍开放。详细字节、锁、
overflow与删除条件见[事件整改](EVENT_COPY_REMEDIATION.md)。

原result16/copyout2/淘汰33（第二作者seq8..40）/CLI4/read7及真实20+2保持，
最长620ms、同slkd/普通用户、1423 USB零drop、9作业CI成功。保留全部历史
故障和限定范围；自然根因/自主恢复/物理xHCI warning/四设备/完整sandbox与
全部S0–S6不因本项通过关闭。下一步实际cancel/late/deadline及独立订阅迁移，
迁完后删除共享ring/fallback/未发布UAPI，不保留永久双路径。

### 无实际操作的注册 UAPI 清理（新镜像验收待执行）

调用审计覆盖两个仓库全部 tracked 文件：旧 DEV_REGISTER/DEV_UNREGISTER ioctl
仅日志后返回成功，没有生产业务调用者；Rust 仅导出未使用的包装，旧 selftest
却将空成功作为通过。Generic Netlink 两个注册名称没有 ops 实现。UAPI 未发布，
本批同步删除 C/Rust 定义、授权/dispatch、Rust 包装和 Netlink 声明，撤下 API
能力声明；旧序号暂不复用，其他命令编号不变。真实 sle_usb_dev_register/
unregister、serdev 内部注册与 WS73 controller 生命周期保持。

清理分类：这两个空接口立即删除；旧成功 selftest 改为专用拒绝测试；
core 总线注册、backend enum、全局 serdev parser 等仍等待可靠替代和回归，
不因本批删除而标为完成。权限矩阵同时补入遗漏的 DIAGNOSTIC_SUBMIT。

严格编译 legacy/权限/live diagnostic 三个 C probe、完整 UAPI 分类和调用
权限矩阵检查通过。新 live diagnostic selftest 在 stderr 单独记录原 C 编码
0x00005301/0x40025302 及历史 Rust write_int 编码 0x40045302 的实际拒绝；
每种编码用 NULL、不可访问地址和有效 sentinel，共每个身份九次。覆盖
root CAP_NET_ADMIN、同 fd 的 UID0/caps0、UID1000/caps0；逐字节核对 snapshot
及统计、枚举数量/掩码不变。该 probe 仅显式 scratch-root VM 内运行，
没有生产注入或新的公开接口。历史 diagnostic 记录格式的资格不自动扩大。

尚未执行本批新镜像实机门禁时，不引用旧 RF 证据证明新生产源码。后续构建
完整 image/modules、私有签名模块 root smoke，再用真实双设备20+2轮及
原 read/diagnostic/cancel/recovery 门禁回归。自然故障根因及完整恢复仍 OPEN；
有限拒绝资格不关闭 K1/K3/K4/K9/K10/K12/K19 或全 S0–S6。

完整新内核重编译另发现 first_deadline 仅被独立 queue selftest 使用，生产 Host
已经采用实际 active 和 recipe 的截止时间，不调用此旧 accessor。本批删除
未使用方法，测试改为检查四个实际 pop 结果各自保留原 deadline，18 项
严格 Rust queue/progress 测试保持。首次有 warning 构建和 root smoke 保留，
最终镜像将重新构建和资格检查，不能把增量构建没有触发重编译当成无警告证明。

### 本批最终镜像实机复核：旧注册接口拒绝限定通过

Linux `257ab5d5e5c6`／编译用户态 `3506ec472957` 的
[冻结证据](evidence/ws73-vm-retired-registration-final-20261011.json)与
[九作业 CI](https://github.com/OpenSparklink/sparklink/actions/runs/38098082157)
通过；实际日志170 Rust、34 Python、185工具。首轮有 warning 的构建及两次
prepare 参数失败保留，最终完整 image/modules 重编译、私有签名模块资格与
新 VM 都重新执行；未安装或加载到宿主。

特权root、同fd UID0/caps0、UID1000/caps0各九次真实旧编号调用全部ENOTTY：
三种历史编码 × NULL/不可访问地址/有效sentinel；snapshot和命令统计逐字节
不变、枚举数量/掩码不变；三个记录的独立USB窗口没有命令或Complete。
三种身份的实际cap与时间记录来自live C stderr，仅限专用selftest，不扩大
历史diagnostic格式的资格。Netlink只删除未实施声明，未宣称本批实际genl
拒绝或完整权限/并发验收。真实内部USB/serdev注册不变。

原门禁继续保持：真WS7320+2轮均10秒内匹配随机数据/地址/RSSI，最长620ms；
read7、结果16、copyout2、legacy poll3、淘汰33＋静默及CLI4均通过；实际
同作者在途/排队取消和显式释放迟到回复的限定资格保持。独立1431 USB零drop、
22RX、46诊断wire对；warning0/taint0/traceoverrun0，同daemon与幸存g2不变，
人工IN81目标g1→3。host四只存在且释放，没有device_del、宿主部署或人工拔插。

这关闭两个空接口的生产假成功，不完成R13：drivers持有总线注册、可引用
Backend、全局parser与重复状态迁移仍待验收。完整截止时间/不续期、暂留USB
cancel/abort/close/drain、完整事件/所有权/并发、自然故障根因与自主恢复、
四设备及S0–S6仍OPEN；北极星7/8。下一步实际queued deadline不续期门禁，
然后剩余消费者与共享ring/fallback删除。

新增CI契约门禁的首轮38098456852暴露旧权限selftest的NLMSG_OK有符号比较，
Clang -Werror拒绝；4项完整分类、78项verifier和18项queue均已实际运行通过。
独立小提交只修复该专用probe：recv长度非负/非零校验后使用unsigned remaining，
不降低警告等级。GCC与Clang严格编译均通过；失败run/日志保留，新增门禁须
在匹配修复提交上重新通过。生产代码和已封存的WS73 live diagnostic probe
不变，实机证据仍指向实际编译K257ab5d5e5c6/U3506ec472957，不冒称后续镜像。

API旧编号概览撤下不完整的总数，明确不是生产能力清单，版本化Native管理／
诊断契约单独引用。用户态实验crate lint边界已收敛；内核transport/serdev/dev/
mgmt/fw等历史模块的全局dead_code压制仍待调用迁移清理，不能宣称全内核已清完。


## 最早原始期限调度生产修复及新镜像回归（整项仍开放）

[本批实际证据](evidence/ws73-vm-deadline-rearm-20261011.json)为K`016aa7ee6813`／
实际编译U`b6d6bf96101e`。本设备RX立即处理诊断提交/同ID重试，并按author、
active wire、recipe和revocation最早原期限重新排期；取消仍保留active reservation。
32项实际源码边界测试和匹配CI九作业通过；真实普通用户WS7320＋2轮最长470ms，
同slkd、幸存generation保持，人工IN81注入目标重获Ready约10.350秒。
排队请求静默800.173215ms后统计已计入一次expiry，早于首次RESULT；完整结果及
此前所有copyout、取消、淘汰、旧注册拒绝和wire门禁保持。USB1431零drop、
warning0/taint0/traceoverrun0，host四只释放在位；无宿主部署或人工拔插。

这是新生产调度的路径回归，不证明精确100ms或时延上界、active USB超时、held
cancel/abort/close/drain、完整并发/权限/移除。旧调用者/shared ring/fallback和内核
全局dead-code清理与生命周期并行；自然故障根因、无人工恢复、历史物理xHCI警告
仍OPEN。最小socket、用户态SSAP、安全/Bond/Profile及完整S0–S6继续推进，
北极星7/8、VM-only不变，部分成果不关闭整项 issue。

### 上批固件模块调用审计（清理候选，随后实施）

K`016aa7ee6813`复核：`sle_fw.load_usb_firmware`仍被旧Rust USB probe调用，
需等待drivers拥有固件迁移，不能盲删整个模块。立即删除候选是无人调用的
FW_BASE_PATH/FW_USB_DEFAULT/FW_UART_DEFAULT、实际上未选版本的
load_usb_firmware_versioned及无人读取的FwDownloadResult.success；调用者
只用size，可缩为Result<usize>，随后移除该模块全局allow(dead_code)。
Native WS73已有独立drivers固件路径保持。transport/dev/serdev/mgmt仍需
各自调用审计和迁移；本条是清单，不是已实施声明。下一小批执行后必须新内核
编译、VM和真实双设备回归，全部清理及恢复issues保持OPEN。

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

## 旧固件门面实际清理（源码实施记录；后续回归见下）

K`d38cada9120f`已删除无人调用的三组固件路径常量、未实际选版本的
load_usb_firmware_versioned，以及无人读取且恒为true的FwDownloadResult.success。
实际load_usb_firmware返回Result<usize>，唯一Rust USB probe接收size；错误和
调用者fallback策略保持。fw模块global allow(dead_code)已删除，仍有调用者的
真实固件加载没有盲删；Native WS73 drivers固件/HCC/BSLE路径未修改。模块
文档移除未实现UART固件和版本选择宣称，固件请求失败保留真实错误信息。

这是立即删除类的已实施小提交；仅编译/静态调用关系不能证明WS73路径保持，
新内核正在严格构建，新VM需分别回归active原期限/稳定预算与原完整诊断/真实
20+2。以前K016镜像资格不推广到新K。transport/serdev/dev/mgmt剩余lint、
旧调用者/shared ring/fallback、driver/backend/parser迁移仍等待替代；C旧通用
固件协议自身互通/回复验证尚未验收，不宣称本批完成其他backend固件支持。
早期Managed release0x1e与自然根因/自主恢复、全部S0–S6继续OPEN，VM-only。

全内核编译在首个清理提交捕获Error格式化E0277，未执行硬件；
K`f5f83d7eb970`改为数值to_errno日志，原失败record/log SHA保留于
[调用清理记录](evidence/legacy-firmware-facade-cleanup-20261011.json)。
新编译和新VM仍是验收门禁，不能将源码CI或失败构建记作实机通过。


## 旧固件门面清理：新内核限定回归通过（整项仍 OPEN）

[本批封存证据](evidence/ws73-vm-legacy-firmware-cleanup-20261011.json)使用
K`f5f83d7eb970`、实际编译U`8641ec61e804`及固定1.10.111 combined blob；后续仅文档。
三类清单更新：**立即删除已完成本批范围**为无人调用路径常量、伪版本选择loader、
恒true且无人读取的success字段及sle_fw全局dead_code lint；**移入测试**保留已有
专用QEMU/故障/边界测试；**等待替代**仍包括有真实probe调用者的loader、C通用
固件短传输/最终ACK校验、drivers-owned backend/parser和剩余global lint。
未发布UAPI未在本批改动，后续迁调用者与测试后直接删除；不保留永久双路径。
Native WS73 drivers固件/HCC/BSLE生产路径未改，真实错误仍传播，未增加模拟成功。

全内核构建与私有modules staging通过，空USB隔离VM接受签名模块、taint0。
首个E0277失败构建原record/log保留；修正日志为to_errno后重编。
编译器warning0；GNU make记录一次jobserver不可用警告，不宣称全部构建日志零警告。
两个独立新VM分别核对原500ms在途超时/Runtime关闭暂留回复/现有稳定期预算归零，
以及格式7原完整诊断63记录/50proof/46wire、read7/result16/copyout2/poll3/
淘汰33/CLI4/旧注册27拒绝/排队原期限。每VM普通UID1000/caps0真实20+2轮，
最长分别469ms、623ms，各自同RF slkd/peer generation不变；
两capture各1345/1431 USB、22RX、零drop，guest warning0/taint0/traceoverrun0，
host四只释放在位。主RF daemon在Diagnostic hold之后启动，本批不证明hold期间同daemon。
[精确源码CI38106781023](https://github.com/OpenSparklink/sparklink/actions/runs/38106781023)
九作业终结成功，实际170 Rust/34 Python/218工具/32实际内核期限边界。
USB/HCC/DLI证据仍不是独立PHY嗅探；原生主机对照未执行，VM-only保持。

按严重程度下一步：修复Setup下未触及radio policy的Managed release/fd-close；
不能对unknown/部分初始化一概快速释放，不能伪造Off/Ready/Complete。已捕获0x1e
未知广播handle与EIO继续OPEN，另需回归初始化中断/真实cleanup/旧generation/
peer隔离/同slkd及有限恢复。C通用固件还需拒绝短写、截短/错opcode/非零ACK，
并独立验收真实backend，不能沿用Native WS73资格。其余事件订阅调用者迁移、
共享ring/fallback/旧UAPI删除、socket/SSAP/每连接安全/Bond/Profile、四设备两组/
Native/Proxy/PM/sandbox及全部S0–S6保持。自然启动超时/重枚举/消失根因和无人工
拔插恢复、历史物理xHCI警告未闭合；北极星7/8，不关闭整项issue或合并draft。


### Setup 租约生命周期修复实施（新镜像待验）

K`f822db7756d7`按[唯一Host状态判据与门禁](MANAGEMENT_SETUP_RELEASE.md)实现未触及
radio policy的快速release；10项实际源码边界通过，6项两设备实际release/last-fd/
dup门禁已纳入专用VM工具。Unknown/部分初始化/在途仍需真实cleanup，不假Off/
Ready。新镜像回归未执行前不更新实机资格；自然恢复/根因和全部S0–S6仍OPEN。
