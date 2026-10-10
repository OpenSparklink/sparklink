# 旧内核实验实现：调用审计与清理清单

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
