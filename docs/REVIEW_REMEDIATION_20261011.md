# 2026-10-11 复核与当前整改计划

最新源码复核与新镜像回归（K`f822db7756d7`／编译U`ccb3d34ae1bc`）见[当前分层、整改与验收边界](BLUEZ_RECONCILIATION_20261011.md)；历史源码和证据范围保留，完整 S0–S6／自然恢复仍开放。

此前限定取消/迟到实机门禁见[实际记录与未决条件](DIAGNOSTIC_CANCEL_GATES.md)：
K`cc4018c4e3a6`/编译U`4a9de6a91617`使用专用QEMU暂留178字节真实回复，
在途/排队本地ECANCELED、旧槽隔离、新查询自己的回复及46组wire限定通过；
原20+2/read7/诊断/legacy poll3保持。完整deadline/held close/并发和自然恢复
仍OPEN，生产路径不变。全部issues和完整S0–S6保持开放。

这份复核基于用户提供的14项报告，逐项检查实现与调用者。原审查基线：
Linux `fc0b4d1a44b6cd417eb99ebee1378bda52a63300`、用户态
`157ec71c3b9a088e39318425299c17c9a70fcd4a`。复核时新增Linux
`2ba3978d22f2`及用户态`8042eb7`只改变QEMU诊断、VM控制/证据工具和文档；
该时点14项生产路径尚未修复。随后376bb1e8a544/c2c4aa4ad0bd已约束
R01/R02/R05，最新分项证据见文末；表中“确认”是原基线发现，不表示新代码
仍具有被删除的测试行为。每批生产提交重新核对，不能复用旧基线验收结论。

用户确认UAPI尚未发布：没有旧公开ABI兼容期要求。修改时同步内核头、Rust/C/
Python绑定、CLI、D-Bus调用者、测试和CI内核pin；迁移调用者后直接移除旧接口。
此前的WS73广播扫描及物理拔插证据继续保留，其范围不能推广到连接/安全/SSAP。

K代表OpenSparklink/linux，U代表OpenSparklink/sparklink。以下任务均为OPEN，
不是已经完成的修复。P1阻止相应能力开放；P2阻止该项功能验收。

| ID | 优先级/结论 | 核对位置与限定 | 既有issue | 修复及必须回归 |
|---|---|---|---|---|
| R01 | P1，确认 | `sle_security.rs`固定nonce、忽略远端DHKey check、ECDH失败测试密钥降级；`sle_workers.rs`普通配对事件调用。不是已证明的WS73实机攻击。 | K7/K18、U5 | 立即删除固定nonce和测试降级；在标准认证/每连接上下文完成前拒绝不可信配对，不能仅随机化nonce后宣称安全。验证错误proof、缺少proof、非法/截短公钥、ECDH失败、错连接/旧generation均不能Paired/生成Bond；实际随机源、标准向量和真实互通是开放条件。 |
| R02 | P1，确认 | `sle_crypto.rs`SM3/HMAC/SM4吞FFI错误，`sle_security.rs`仍推进计数。 | K7/K19、U5 | 所有密码学包装返回Result；检查长度转换，失败不提交密钥/状态/计数/可用密文。以实际包装及可控FFI错误覆盖分配、算法/密钥失败，校验缓冲和计数未被错误提交；测试crypto ioctl迁入专用测试接口或移除。 |
| R03 | P1，确认 | `sle_conn.rs::send`入64深度tx_queue无消费者，core同时直接send_data；先提交统计再发送。Native discovery不能因此被称为坏掉。 | K17/K4 | 明确一个每连接发送所有者；删除重复队列/直发路径，按credit、完整发送完成提交序号/统计。>64连续包、零credit后恢复、短写/发送失败、断链及旧generation清理，多连接隔离。 |
| R04 | P1，确认 | `sle_ssap.rs`ReadRsp追加后转u16，WriteReq追加后累加u16；WriteCmd也忽略扩展/写入错误；该路径没有事务总预算/期限。 | K6、U3 | 每片追加前检查属性上限、PDU大小、checked offset、每连接和全局内存预算；事务截止/断链取消。覆盖65535/65536边界、持续完整片、非法偏移、超MTU、OOM、超时、乱序/错连接；以迁往用户态Engine为最终所有者，旧内核Engine不长期并存。 |
| R05 | P1，确认 | `sle_uart.rs`/`sle_spi.rs`普通backend本地生成CommandComplete(Success)，数据发送只编码日志。 | K9/K12/K19 | 立即移除伪造成功和假数据发送；未接通硬件明确EOPNOTSUPP。模拟行为只进入专用测试backend。实际实现需真实回复/完成关联；无回复、拒绝/超时、短写证明不会成功，保留纯codec测试。 |
| R06 | P1，确认 | `slkd/config.rs`安全/auto_enable配置没有消费，main对所有读/解析错误用默认。 | U5/U6/U8 | 区分允许的默认路径不存在与显式缺失、权限错误、无效配置；明确拒绝未实现非默认安全/启用策略，不能静默弱化。覆盖显式文件缺失、无权限、语法/未知字段、auto_pair/min_encryption、auto_enable以及默认WS73启动回归。 |
| R07 | P2；开放SSAP前必须修复，确认 | profile/service/HID掩码0x04被当notify；内核READ=01、WRITE_NO_RSP=02、WRITE_WITH_RSP=04、NOTIFY=08、INDICATE=10。 | U3、K6/K19 | 建立规范命名常量及明确转换，禁止散落魔数；read+notify不能获得写权限。跨内核C头、Rust、Python的语义测试，涵盖Battery/HID、两种write和indicate，未知位拒绝。 |
| R08 | P2，确认 | `sle_workers.rs`先取notification再credit，失败丢弃且忽略send错误；通知缺少明确连接归属。 | K6/K17、U3 | 连接归属、credit预留、编码/发送提交后出队；失败归还预算并保留消息，indication等确认/期限。零credit恢复、失败/取消、两连接并行、重复/迟到ACK、断链清理。 |
| R09 | P2，确认 | core PHY set与SEC_ENCRYPT_ON在发送/设备确认前修改本地状态。 | U4、K7/K16 | 请求值/pending/已确认值分离；唯一提交由匹配成功Complete驱动。拒绝、超时、错误opcode/generation、发送失败查询不得显示已生效；同样审查其他设置。 |
| R10 | P2，确认 | core conn_send解析handle0后仍传原cd.handle。 | K17 | 解析后的handle用于同一发送事务、credit、队列和统计；默认/显式、无连接、两连接和断链复用回归，与R03一起修复。 |
| R11 | P2，确认 | serdev忽略ctx，共用parser，probe覆盖最新dev_id。 | K4/K10/K12 | parser、分片、waiter归属具体backend/runtime/generation，ctx有稳定生命周期；双设备交错字节/分片、移除/迟到回调、并发probe/remove及释放检查。不能将单设备成功推广为隔离完成。 |
| R12 | P2，确认 | core旧read_iter先dequeue，copy_to_iter零/部分结果消耗事件；Native专用事件已有复制提交语义。 | K3、U2 | 以统一按订阅者、完整记录、复制后提交为目标；迁移读取调用者并删除旧事件队列/UAPI。无效地址、部分copy、短buffer及重试不能丢失或交付半记录，多订阅隔离与退役唤醒。 |
| R13 | P2，确认但限定 | Kconfig核心依赖USB=y、核心持总线注册和backend枚举；drivers/sparklink Virtual模块只打印日志。核心内置Virtual另有实现，开发测试不是全无。 | K1/K9/K12、U7 | 先收敛注册/模块所有权接口，再迁移总线注册及删除枚举；Virtual驱动实际注册相同Runtime/生命周期，迁移模型测试后删除核心内置重复实现；核心USB=n、USB=m、driver=y/m、Virtual热插拔/卸载与WS73原路径回归，然后扩展Proxy。 |
| R14 | P2，确认并补远端证据 | release记录39个slkd warning；CI -D warnings。基线157ec71的run38072489528中cargo check失败，test/clippy/release被跳过，fmt和Python ABI成功。 | K19、U8 | 不降低-D warnings；整理未接通模块/死代码，再以固定依赖建立check/test/clippy/fmt/release基线。把工具、跨语言语义/ABI、生命周期及配置矩阵纳入CI；硬件VM测试使用专用有设备runner/手动门禁，普通CI不得把fixture当RF。 |

## 依赖顺序与验收边界

1. **立即约束生产能力**（R01/R02/R05/R06）：删除生产测试nonce/密钥降级/伪造
   完成；完整实现未知时拒绝操作。失败证据与协议标准尚未确认时，不采用猜测的
   认证算法。WS73 Native discovery保留可用，安全等能力按独立状态暴露。
2. **基础正确性**：R03+R10共用一条发送事务，R04+R07约束SSAP，随后R08、R09、
   R12。只有实际错误传播和完成提交成立后，才能扩大连接/服务/加密验收。
3. **设备生命周期同时保持当前优先任务**：K10/K14/K15/K19、U10处理自然启动
   超时、重枚举、设备消失、幸存者及xHCI警告。R11归入每设备隔离。恢复预算、
   自动Ready、daemon不停机仍需单/双/四设备负向矩阵；只允许VM，原生主机对照
   未授权且未执行，不能用VM替代。真实四设备两组并行仍待验收。
4. **收敛架构和删除旧实现**：R13后逐一迁移SSAP到用户态、每连接安全/Bond、
   Profile/HID及transport。不能把旧内核Engine与用户态Engine作为永久双实现。
   迁移时保留真实WS73 gates、故障历史和有价值codec/协议回归。
5. **CI/文档作为每批提交的门禁**（R14），不等到最后统一清理。每个修复提交
   记录对应R编号、生产调用链、删除路径、失败/成功回归、能力开放条件和证据。

## 清理旧实现与死代码：当前工作项

- 生产固定nonce、测试密钥和模拟成功立即删除；需要的模拟移至明确测试backend。
- Profile注册/连接回调确实已接入旧profile0，不能误删有效生命周期回归；读写
  请求未接入，Native profile1不注册服务。下一步明确实验边界或接通，不能继续
  文档宣称完整Profile服务。transport目前无生产消费者，隔离到实验feature或测试
  crate，保留codec用例；不要用allow(dead_code)掩盖未接通能力。
- 按调用者和运行路径清单迁移旧crypto/SSAP/事件/tx队列/总线实现，删除重复逻辑；
  未发布UAPI不设置兼容期限，不保留永久适配层。文档和错误能力声明同批更正。
- AGENTS.md旧“七阶段完成”仅是历史文件进度，不是验收；删除该状态依据。
  原始故障证据保持可追溯，fixture、人工注入、真实RF、物理拔插分别标明范围。

## 已验证路径与新恢复支持的重审

物理证据仍为[2026-10-10物理闭环](evidence/ws73-vm-physical-20261010.json)，
20+2轮、两只真实WS73、普通UID/caps0、daemon/bus不变。新增
[人工传输错误支持](evidence/ws73-vm-artificial-recovery-20261010.json)已检查
单对象默认关闭/arm guard、close取消、其他对象隔离、guest普通应用与独立capture
校验；141项工具测试及新QEMU mock/QMP边界通过。实际一次IOERROR经guest
xHCI endpoint恢复后丢回复，触发-110命令超时，有限恢复至新generation并再做2轮
真实RF：这是额外开发证据，**U10仍7/8**，不关闭自动恢复或根因未明issues。

远端CI基线：[run38072489528](https://github.com/OpenSparklink/sparklink/actions/runs/38072489528)。
这里没有宣称完整生态、标准一致性认证、PHY嗅探证据、板级校准资格或安全实机验收。

## 架构与清理增补（2026-10-11）

采用 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)，最终连接
数据面是每逻辑通道独立 socket fd；SSAP/服务/Profile 用户态所有者，管理/事件/
诊断/Proxy 独立。 [三类调用审计](LEGACY_CLEANUP_20261011.md)细分立即删除、
移入 selftests、等待新路径替代；不增加未发布 UAPI 的兼容负担。
[BlueZ 对比](BLUEZ_COMPARISON.md)删除错误完整/优势宣称，参考官方 MGMT、
GATT、Agent、L2CAP 和 VM 测试语义。R01/R02/R05 首批已签名推送并完成限定开发/新镜像实机回归，仍未完成
每连接安全/真实其他 backend 验收；R06–R14、自然恢复及整项 issues 仍 OPEN。

### 首批实现、开发测试与实机状态

- 实现：Linux `376bb1e8a544`删除不安全配对/生产crypto测试执行并传播FFI错误；
  `c2c4aa4ad0bd`删除UART/SPI伪Complete/发送成功和虚假能力。未支持操作EOPNOTSUPP。
- 开发：实际Rust6项安全失败回归、实际C CTR5阶段失败和ASan/UBSan/LSan、UART/SPI
  实际方法2项、跨语言/32位ABI29项通过。kernel完整镜像/modules及对象无warning。
- 实机：[整改后新VM证据](evidence/ws73-vm-cleanup-regression-20261011.json)记录
  20+2真实RF（最长624ms）、单对象人工故障有限恢复、同daemon/幸存者、22份独立RX
  佐证及1163记录零drop，taint0。历史物理证据保留，本批未重做人工物理拔插。
- 未决：R01/R02完整认证/向量/凭据安装、旧正向测试与UAPI迁移；R05真实其他backend；
  R06–R14、自然根因/无人工恢复/四设备/全sandbox。严格CI39 warning不隐藏，
  新CI门禁不能代表全部质量基线已恢复，所有整项issue继续开放。

### 首批远端质量门禁历史

用户态 `082e6743e20b` 的 [CI run38075881263](https://github.com/OpenSparklink/sparklink/actions/runs/38075881263)：
新增 actual kernel security/backend failure 门禁、Python/内核ABI和rustfmt成功；
cargo check仍因slkd原有39个dead-code错误失败，test/clippy/header/release跳过。
没有降低-D warnings，R14仍开放；新增门禁成功不表示全部质量或标准验收通过。

## R06/R14 后续实施（2026-10-11）

R06的9f57d1e：仅缺失隐式默认文件可使用默认；显式缺失/权限/解析/未知字段
和未实现策略拒绝，启动前验证；Native拒绝未实现legacy过滤器后才允许管理lease。
10项单元/CLI/实际子进程回归通过。完整auto-enable、安全策略实现仍开放。

R14：[实验边界](EXPERIMENTAL_CODE_BOUNDARY.md)隔离未接通Profile/HID/transport，
保留实际actor与有效失败回归，不隐藏死代码；严格默认及all-target/all-feature
check/clippy/fmt及默认release已经通过，workspace all-features160项测试/零失败/
零ignored通过；工具/evidence测试纳入独立无硬件CI。新默认daemon的VM真实RF
和远端CI须重新核对。
原CI39错误是旧提交证据，不能据它断言本批仍有同样错误或已经绿；以新记录为准。

### 最新整改回归及完整质量基线

9f57d1e/34b54fd之后，7ad805e明确工具CI的固定内核输入，8a9cc28修复远端
Rust1.99新增广告UUID解析lint。首轮run38077097118的两类失败保留，没有跳过
用例或关闭-D warnings。[run38077403740](https://github.com/OpenSparklink/sparklink/actions/runs/38077403740)
对应8a9cc28，9个jobs全部success：check/test/clippy/fmt/default release、C header、
Python/32位C/Rust ABI、141项工具/evidence测试、实际内核失败边界。严格本地
Rust1.96与1.99 clippy均通过；all-feature workspace160项/零失败/零ignored，
配置实际进程回归和默认依赖隔离都保留。R14配置/生命周期/硬件完整矩阵仍开放。

[34b54fd默认daemon证据](evidence/ws73-vm-config-cleanup-regression-20261011.json)
和[8a9cc28最新生产代码证据](evidence/ws73-vm-strict-ci-regression-20261011.json)
分别保留20+2真实轮次。后者最长775ms、1163USB记录/零drop、22份host独立
RX/命令/元数据佐证；人工IN81错误后的新generation恢复耗时10301.731ms，
幸存generation2与slkd PID/start/bus不变，UID1000/caps0，最终停止均确认；
kernel warning0/taint0，四个host USB地址保持不变。这里的10秒是每次扫描
成功Complete之后的发现窗口，不能把设备故障恢复耗时宣称为小于10秒。

本轮没有物理拔插、自然故障根因或宿主原生验收；历史xHCI警告及物理证据不删，
U10仍7/8，自动恢复/根因相关issues继续OPEN。下一顺序：WS73自然根因与有限
恢复并行推进，R03/R10发送提交与socket契约、R04/R07/R08 SSAP预算/权限/credit，
R09/R12状态/事件提交、R11/R13每设备backend迁移；全部S0–S6范围不缩减。

## R03/R10 单次提交及旧 USB 边界整改

Linux 75b77fc19613删除没有消费者的TX ring，ConnManager只调用一次backend；
成功后才提交sequence/tx_bytes/activity。handle0选择真实已连接Host对象，command
Host backend使用学到的controller handle，未学到时拒绝；不再把0或Host编号误发。
无效长度拒绝而非截断；连接/通道、MTU/MPS、overflow先验证。旧ioctl没有可靠
framing/分片实现，明确拒绝，不能用TCID前缀冒充；tx_pending为0，tx_bytes只表示
backend接受，不证明peer接收，错误后的部分传输也不自动重发。

旧generic USB sender拒绝无效/超长/超范围handle，检查actual_len完全匹配并保留
原errno。Native WS73 HCC/BSLE/discovery未改，Native连接数据仍不支持。11项实际
Rust sender/resolver/ioctl回归及实际C USB范围/分配/errno/所有短写/exact/max-length
在ASan/UBSan/LSan通过；完整Rust kernel对象编译验证真实接线。依赖显式fixture，
不是socket、协商协议、USB硬件或RF验收。新CI固定对应内核并执行此门禁。

新完整image/modules已构建并冻结、空USB隔离VM签名模块加载/卸载通过。
[新内核实机记录](evidence/ws73-vm-connection-tx-regression-20261011.json)：
匹配用户态630bf7f，20+2真实RF、最长614ms、1163 USB/零drop、22份独立RX/
命令/metadata佐证，UID1000/caps0、slkd PID520/start331/bus及幸存generation2
不变，最终停止确认、warning0/taint0、四个host USB身份不变。人工故障从失败
命令开始到新Ready约11031.707ms，不将它宣称为小于10秒的恢复；发现窗口均满足。
构建仅有一条make jobserver unavailable警告，无代码编译warning/error。
[CI run38078588074](https://github.com/OpenSparklink/sparklink/actions/runs/38078588074)
对应630bf7f，9 jobs全success，已核对新增实际11项sender及C USB边界日志。
完整R03/R10、K4/K17
继续OPEN；下一步仍是socket每通道队列/背压/权限/generation/退役、真实连接数据。
保留旧正向连接/SSAP测试与历史失败，它们须接专用backend/真实controller事件，
禁止把底层失败却增加tx_bytes当作通过。WS73自然恢复/根因同步继续，不因本批关闭。

### R04/R08 旧协议路径限制与新标准核对

Linux 4d8a0d61673d77c5fd104d219346e0a2d3e23ef2 删除生产旧 SSAP codec/构造器/无界事务、全局无归属通知
队列、两套通知 drain 和未接通 method echo。remote/notify/indicate 明确不支持，
本地 staging OOM 保留旧值，超长输入拒绝。表72/75/76的消息控制码与旧 offset/
短包格式不一致，修复最终落在用户态标准 Engine；不把长度修补称为标准长读写。
[调用链、迁移和8项实际代码回归](SSAP_LEGACY_CONTAINMENT.md)；历史codec只保留
selftests。整项 R04/R07/R08 仍OPEN：socket/owner/预算/期限、标准codec、跨语言
权限、通知提交/ACK、Profile和真实服务互通待实施。
[本批新镜像WS73回归](evidence/ws73-vm-ssap-containment-regression-20261011.json)
已验证20+2、最长622ms、22独立RX/1163 USB零drop、同daemon/幸存者、warning0。
远端[CI38079779731](https://github.com/OpenSparklink/sparklink/actions/runs/38079779731)
9 jobs success，实际8项SSAP/11项sender日志已核对；自然根因及北极星7/8不变。

### R07 权限契约及调用入口整改

Linux bde171beb2e0aee6d10515235ec4f0bb03e99663 与本批用户态采用表32权限命名/32位类型，拒绝保留位和
旧8位接口的descriptor截断；修正Battery/HID声明、Battery UUID，实际library和
D-Bus入口拒绝无效/超长属性。Python超长write也拒绝u16回绕。[实现/语义门禁](SSAP_OPERATIONS.md)
记录C/Rust/Python2052输入、167 Rust/33 Python/9 kernel实际测试；不是wire Engine
或真实服务验收，R07与整项服务/socket/security issues保持OPEN。

[本批新镜像回归](evidence/ws73-vm-ssap-operations-regression-20261011.json)
确认两只真实WS73 20+2轮、最长620ms、22份独立RX/1163 USB零drop，普通用户、
同daemon、幸存generation保持，VM无warning/taint；人工恢复约10272.715ms。
[固定两仓库提交的CI](https://github.com/OpenSparklink/sparklink/actions/runs/38081123658)
9个作业成功且实际日志已核对。R07的声明/转换/入口拒绝已修，完整每peer权限、
descriptor配置和SSAP服务互通仍待替代Engine，不提前关闭整项。

### Bluetooth／BlueZ分析再次核对

2026-10-11再次收到的分析与已纳入的版本内容相同；逐项按
[ADR 0001](decisions/0001-management-channel-service-boundaries.md)核对，保留
第一北极星及完整S0–S6。R01/R02/R05/R06已限制危险或未接通入口；R03/R10已
统一backend提交和成功记账；R04/R08删除未达标准wire Engine和无归属通知；
R07本批对齐跨语言权限语义。上述均为限定整改，安全、连接、SSAP整项未验收。
R09/R12状态与事件提交、R11/R13每设备parser/总线所有权迁移仍待实现；
R14严格CI已恢复，但完整构建/发布/硬件矩阵仍OPEN。

后续优先闭合自然启动超时/重枚举/消失及单设备有限恢复，且并行推进旧代码清理；
再按socket开发门禁与真实双设备数据、用户态SSAP/每连接安全/Bond/Profile、
四设备两组、其他Native/Proxy顺序推进。无新UAPI兼容承诺，调用者同步迁移后
可直接删除旧接口。诊断观察不代替Ready，人工故障不代替自然根因，VM证据不
代替未授权的宿主原生对照；北极星仍7/8。

### R12 旧read记录提交（部分整改）

Linux20f431f54af0在完整copy_to_iter后才消费per-fd记录及delivered计数；首条
部分复制返回EFAULT，后续部分复制只返回前缀完整记录，失败head保留。短buffer
EINVAL而不是假EOF。无人调用drain_to_buf删除，dequeue私有，仅唯一copy_records
提交。9项编译实际event/read代码的依赖fixture回归及完整核心对象构建通过；
没有新增生产测试hook或global lint。见[调用审计和验收边界](EVENT_COPY_REMEDIATION.md)。
旧DLI_POLL_EVENT仍是另一消费路径，legacy lib receiver使用它，迁移/坏地址/断链/
移除唤醒仍待验收，R12/K3/U2整项OPEN。新镜像WS73回归和远端CI另行记录。

[本批新镜像](evidence/ws73-vm-event-copy-regression-20261011.json)通过真实20+2轮、
最长621ms、22独立RX/1163 USB零drop，同daemon/幸存者/普通用户，VM无warning/
taint；[CI38082158063](https://github.com/OpenSparklink/sparklink/actions/runs/38082158063)
9作业成功，实际新增event-copy9及既有回归日志核对。人工恢复约10572.148ms，
不是自然根因或live VFS坏地址验收。完整事件、自然恢复和北极星7/8保持OPEN。

### R12 实际read用户copy门禁与再次复核

本次附件与已采纳的Bluetooth／BlueZ分析相同，ADR及S0–S6不变。复核更新至
Linux `3a6669114069` / 用户态 `6c06b8f9ef83`：生产read修复保持，新增专用C
selftest与VM gate完成7类真实read(2)，包括坏地址及首条/后续跨页部分复制。
实际写入22字节，失败记录保留；后续fault只返回先前完整44字节，独立fd原始
字节和统计均匹配。没有增加生产模拟成功或测试注入。见
[错误语义和调用审计](EVENT_COPY_REMEDIATION.md)。

[本次新镜像](evidence/ws73-vm-live-event-copy-20261011.json)另通过真实20+2轮，
最长622ms、22独立RX/1247 USB零drop，同daemon/幸存者/普通用户，VM无warning/
taint；[固定提交CI](https://github.com/OpenSparklink/sparklink/actions/runs/38083436958)
9作业成功，167 Rust/33 Python/146工具及实际内核边界日志核对。
7类read门禁已验证；R12旧DLI调用者/复制提交、完整订阅/所有权/移除唤醒仍OPEN。
R09真实硬件完成前状态提交、R11/R13总线/parser迁移与自然故障根因继续整改。
人工恢复约10773.253ms不算完整自主恢复，历史物理xHCI warning继续保留。

### R09 提前状态提交及无依据的PHY快照

`f16ac912a8ff`/`f1704a2e44dc`删除ControllerState默认PhyConfig及全部setter/本地
估算查询，8个PHY/SINR ioctl不支持；legacy加密enable不再先置Encrypted，不改
凭据/计数/状态，不发空参数StartEncrypt。无人调用command wrappers删除，历史
MCS/MIMO/PHY codec移selftests；仍被连接调用的channel/hopping保留等待替代并
删除phy模块global lint压制。security新增预填Paired等状态回归、隔离模型边界及
实际拒绝分支开发测试通过。见[当前调用审计](LINK_STATE_REMEDIATION.md)。

这是删除错误状态来源并限制未接通能力；真实PHY/加密事务、每连接凭据安装及
匹配成功硬件完成尚未接通，R09/K7/K16/U4整项OPEN。新镜像/实机结果见下文，
自然恢复、旧DLI迁移、完整socket/SSAP/安全/Bond/Profile及S0–S6继续推进。

[R09新镜像回归](evidence/ws73-vm-link-state-cleanup-20261011.json)已重新核对7类
实际read及真实20+2轮，最长622ms，22份RX/1247 USB零drop；普通用户、同daemon/
幸存者，VM warning0/taint0。人工恢复约10168.645ms。固定源码的
[CI38084762680](https://github.com/OpenSparklink/sparklink/actions/runs/38084762680)
9作业通过，实际security7和隔离PHY模型3/拒绝arm1及既有回归日志核对。
这是清理后的路径保持，不是PHY/加密真实成功或自然故障根因验收。

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


### Setup 租约生命周期修复实施记录（后续限定验收见下）

K`f822db7756d7`按[唯一Host状态判据与门禁](MANAGEMENT_SETUP_RELEASE.md)实现未触及
radio policy的快速release；10项实际源码边界通过，6项两设备实际release/last-fd/
dup门禁已纳入专用VM工具。Unknown/部分初始化/在途仍需真实cleanup，不假Off/
Ready。新镜像回归未执行前不更新实机资格；自然恢复/根因和全部S0–S6仍OPEN。


### 上批 Setup 释放限定实机复核及完整 issue 集合

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


### 上批通用 USB 固件错误传播整改及新镜像回归

K`7f2ba1f81ce0`／编译U`ae542f568e03`修复实际C短写/最终ACK校验及Rust
loader/probe错误传播，只有ENOENT允许使用已bootstrap固件；上传后重新查询，
禁止发布旧身份或失败设备。[调用链、三类清单和限制](GENERIC_USB_FIRMWARE_REMEDIATION.md)
明确Native WS73 driver未改、专用fixture不等于通用固件真实方言资格。
69个ASan/UBSan/LSan C案例、12个严格Rust实际函数测试通过；首次缺少EPROTO
完整编译[失败记录](evidence/generic-firmware-kernel-build-failed-20261011.json)保留，
修正canonical binding后全内核/private modules/签名smoke通过。编译器warning0，
GNU make一次jobserver警告；一次过早smoke在缺少私有module时退出、未创建VM，
原日志保留，实际stage终结后才运行通过。

[新镜像两个独立VM证据](evidence/ws73-vm-generic-firmware-boundaries-20261011.json)
保留各6 Setup release/last-file/dup门禁和整个窗口零DLI，实际在途500ms超时/
Runtime退役/稳定预算归零，以及另一VM原诊断63记录/50proof/46wire、read7/
result16/copyout2/poll3/淘汰33/CLI4/旧注册27拒绝及queued原期限。每VM
UID1000/caps0真实20+2，最长773/622ms，各自同RF slkd及peer不变，USB1345/
1431、各22RX/零drop，guest warning0/taint0/traceoverrun0，结束四只释放在位。
[精确源码CI38109661941](https://github.com/OpenSparklink/sparklink/actions/runs/38109661941)
九作业终结成功，实际170 Rust/34 Python/228工具/32期限/10管理及新增69 C/
12 Rust固件源码门禁。USB/HCC/DLI不等于独立PHY嗅探；hold期间同daemon未资格。

下一批立即删除实际generic USB register描述符失败“test mode”硬编码端点fallback，
返回真实错误、实际register fixture和新镜像回归；register本身仅分配URB不提交，
不能据此虚构bootstrap并发竞态。有真实调用者的loader/backend/parser/全局fallback/
shared ring等待新路径接通及调用者迁移后删除，未发布UAPI直接弃用。并行推进
WS73 partial/unknown初始化真实cleanup、held transport last-file-close/drain、
有限恢复和自然RCA。完整分层/socket/SSAP/每连接安全/Agent/Bond/Profile/四设备
两组/其他Native/Proxy/PM/sandbox/发布及全部S0–S6保持；最新附件SHA与已采纳决策
相同。实际开放集合28（K19/U9），原scope不改；VM-only/北极星7/8，自然故障根因、
无人工拔插恢复、历史物理xHCI warning继续OPEN，不关闭整项、不合并draft。


### 当前端点／能力默认值清理与真实在途最后文件关闭

K`c5ec97f50c06`／编译U`ad5e28727229`已删除生产descriptor失败的“test mode”
端点回退，context私有准备成功后才发布；删除USB/serdev/default/attach未经查询
的feature、255/8/MTU/MPS/transport/measurement/crypto声明，保留实际身份/固件。
[调用清单、未知值和门禁范围](USB_DESCRIPTOR_CAPABILITY_CLEANUP.md)明确0不代表
无限制或已知不支持；完整caps/limit/quirk来源、旧DLI_INFO软件预算与UAPI迁移仍OPEN。
18个实际C register/unregister sanitizer案例、5个实际Rust info/default/attach测试
通过；原固件69 C/12 Rust及管理10门禁保持。6个在途close负例测试使工具总数234。
提取器void支持和测试入口错误、一次错误expected HEAD被快照校验器拒绝的原日志
均保留；修正后完整内核/private modules/签名smoke通过，编译器原0计数有误、实际1条warning（见下方勘误）；GNU make
一次jobserver警告。Native WS73 driver/已查询metadata未改。

[新镜像两个独立VM封存](evidence/ws73-vm-descriptor-cleanup-held-close-20261011.json)
首轮实际Diagnostic MAC回复由QEMU暂留：原fd关闭得到EBADF，dup保有Held100ms；
最后dup关闭EBADF、observer精确Revoking，原500ms Host deadline触发Runtime退役
并取消实际IN81，一次abort／零release-reset-detach、无新目标命令或旧回复交付，
旧generation拒绝、peer不变且两次真实MAC成功。此为already-Off Diagnostic有界
原期限drain，**不证明close立即abort、Managed部分初始化或完整生命周期**。
两新VM均各6 Setup release/last-file/dup及完整窗口零DLI；分别保留稳定预算归零
和完整原诊断63记录/50proof/46wire/read7/result16/copyout2/poll3/淘汰33/CLI4/
旧注册27拒绝、queued原期限。各UID1000/caps0真实20+2，最长470/774ms，各自
同RF slkd/peer，USB1345/1431、各22RX/零drop，guest warning0/taint0/traceoverrun0，
四只结束释放在位。USB/HCC/DLI不是独立PHY；hold期间同daemon未资格。
[精确源码CI38111118827](https://github.com/OpenSparklink/sparklink/actions/runs/38111118827)
九作业终结success，170 Rust/34 Python/234工具、32期限/10管理/固件69+12/
新增descriptor18+info5门禁。

下一步推进Managed部分初始化真实cleanup、不同radio/history/在途阶段的close与
有限恢复／自然RCA；迁移独立事件消费者后删shared ring/fallback/未发布旧UAPI，
并接通完整能力来源与显式不支持、drivers-owned backend/parser、最小socket、
SSAP/每连接安全/Agent/Bond/Profile、四设备两组及Native/Proxy/PM/sandbox/发布。
完整S0–S6与28项原scope保持，VM-only／北极星7/8，不关闭自然启动/重枚举/消失
根因、无人工拔插恢复或历史物理xHCI warning，部分成果不关闭整项或合并draft。


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


## 构建警告计数勘误（原封存保留）

上一批 K`c5ec97f50c06` 的“编译器 warning0”计数错误：原构建日志实际有
1 条 `MAX_PAYLOAD_LEN` 未使用导入警告，另有 1 条 GNU make jobserver 警告。
[勘误及原日志/封存哈希](evidence/descriptor-cleanup-build-warning-erratum-20261011.json)
保留原 JSON 字节，不把错误记录改成成功；文档和 issue 中的原编译器零计数应以
此勘误为准。原 guest warning/taint、RF/USB/VFS/deadline 证据来自独立实测，
不与编译器 warning 混同，也不因勘误宣称新源码或新 Managed 分支验收。

K`292f9fec84b6` 已删除导入，新完整构建 compiler warning0、make jobserver warning1。
离线 build checker 增加终结日志 SHA-256 验证与 diagnostics 分类：编译器 warning、
make warning、未分类 warning 分别记录，Rust/Clang 汇总行不当作第二条警告。
未知 producer 不能被宣称为 warning-free，活跃/失败/无哈希/日志篡改拒绝。
六项新增负例/计数测试及全部 240 工具测试通过。日志计数仍不等于全部 compiler
输入来源、实机或完整发布资格；自然 RCA、完整恢复和 S0–S6 原验收继续 OPEN。


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

## 2026-10-11 当前 Managed 实机门禁阻塞与推进顺序

Managed未选择取消、partial初始化release/last-file/dup/在途回复及peer隔离仍是
第一优先级，专用探针已接入独立VM门禁，但本轮六次完整启动尝试全部在第一只
设备Setup元数据前失败，未运行任何新增Managed案例。原K292签名内核和编译
生产Rust路径保持，原真实双设备20+2证据保留；当前设备状态不能重新Ready，
不得宣称本批实机闭环或恢复通过。

已比较单/双vCPU、两个物理pair、uhubctl短/长off-on（四口确实重新枚举但未证明
VBUS或SoC冷启动）。独立维护VM无WS73 driver owner时EP02寄存器读setup仍-110，
未写SoC复位；精确一次guest USB总线reset、EHCI与xHCI对照仍相同。SDK明确
class/interface request2、四字节DISALLOW_TO_SLEEP=0的请求已真实返回4且有
抓包，但仍未恢复EP02。不能把PM唤醒、CPU数、virtual hcd或hub切换认作已定位
根因。保留QEMU/libusb共同路径、设备状态及实际供电等待核对项。一次维护VM
抓包用户遗漏导致PID1退出panic，已修正；这是未接触设备的fixture失败，独立
保存，不归为WS73 driver panic。详见[本轮失败证据](evidence/ws73-managed-gate-startup-failures-20261011.json)。

下一步先建立可成功的每设备启动及真实握手诊断，随后执行两设备六项未执行
队列取消和partial初始化三种释放／两个域／真实在途回复矩阵。失败必须保留
原status/errno，不通过模拟成功、替换注册、绕过capture或无限重试满足验收。
不依赖人工拔插、另一只仍可用且slkd不重启的完整自动恢复及自然RCA仍OPEN。
旧代码三类清理继续并行；UAPI未发布，可迁调用者后直接删除。完整S0–S6、
所有28项issue原范围、四设备/安全/连接/SSAP/Profile/Proxy/PM/发布矩阵保留。

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

## Managed 队列实际 fd 支撑与前置条件纠正（2026-10-11）

[本批独立证据](evidence/ws73-managed-queue-support-and-bulk-submit-20261011.json)
记录首次实际内核执行暴露的探针前置错误：Unknown Setup／pending 广播时
ScanInitializeOff 返回 EBUSY，不生成结果。保持内核保护，修正子门禁为合法
广播配置／扫描 STOP，另验证 EBUSY/ENOENT。模拟 USB 上两只×release／最后
fd／dup 六案例实际通过，完整区间零 DLI、Unknown/Setup 及 peer 快照保持；
真实案例数不增加，整个 Managed 未执行队列验收仍 false。

partial 扫描探针格式2强制先用真实广播配置／STOP 成功 Complete 建立 Off，
再 arm 扫描第一步；完整结果、power 和有序抓包都须匹配。268 工具测试通过，
这段新前置路径当时还没有 VM／真实 held-reply 通过证据；后续模型结果见下文。不得把静态 Setup peer
当作 Ready 同伴活动隔离，也不得用扫描 STOP 子案例代替扫描初始化全矩阵。

新物理诊断确认 length36 bulk 实际提交到主机，再超时取消、回收 -ENOENT、
transferred0；该区间 parent/hub/target active 且 suspend-time 增量零。这只
缩小诊断范围，不证明实际 PHY 传输、冷启动、成功恢复或自然根因。VM-only、
历史真实 WS73 RF 证据和正式 Linux/Rust 路径保持；恢复、RCA、完整矩阵与原
28项 scope 开放。下一步按真实启动→合法子门禁／confirmed-Off 扫描初始化→
partial 六案例及活动 Ready peer→同 daemon RF／故障隔离／四设备推进。

## 第一阶段 partial fd 模型整改证据（2026-10-11）

[封存矩阵](evidence/ws73-managed-partial-model-fd-matrix-20261011.json)新增六个
成功和六个精确拒绝案例：实际内核 release／最后 fd／dup、Pending→Cancelled、
原模型终结帧交还后的哈希、完整 UAPI 和同伴查询均核对。负向原 VM FAIL 保留
0x0b/-EIO 与 RecoveryBlocked/Faulted，不模拟 Free/Ready。另有一次启动前
socket 路径错误，修正后重新执行，原失败不删除。274工具测试及 Uf35 CI 九作业
通过。模拟暂停只覆盖第一个初始化步骤；不能当作真实 libusb IN、活动 Ready
同伴或 RF。真实 Managed 通过数仍为零；14项整改、全清理、恢复、自然 RCA 和
原28项完整验收继续 OPEN，已封存真实 WS73 路径与历史故障证据保留。

[真实 clear-halt 对照](evidence/ws73-clear-halt-route-diagnostic-20261011.json)
保留原 FAIL：实际 EP01/EP81 libusb 返回0，完整配置与69包零丢包抓包核对，
但第一笔路由 bulk 仍超时并取消回收、传输量0。未加载模块／写 SoC／复位 hub；
无新增真实 Managed、Ready同伴或恢复资格。私有观察器与默认恢复构建哈希
封存，278工具测试通过。该尝试仅排除标准端点清理能直接恢复本次传输的
假设，未查明自然故障根因，相关问题继续 OPEN。

[两次真实只读寄存器对照](evidence/ws73-register-read-contrasts-20261011.json)保留
原 FAIL／TimeoutError、两个实际在途请求和取消回收，标准 EP02/EP82 清理
实际返回0仍未恢复数据。guest 失败 OUT actual16 与 host 两笔 transferred0
分别记录，失败长度不能代替真实成功。未写寄存器／复位／加载模块；283工具
测试及 Ud8f CI 九作业仅源码支撑。自然 RCA、Ready同行、Managed真实矩阵、
自动恢复、14项整改和全部原 issues 继续 OPEN；历史有效路径／证据保留。

[完整初始化队列模拟 fd 证据](evidence/ws73-confirmed-off-queue-model-fd-20261011.json)
封存两只各五笔原初始化成功回复与六个 release／最后fd／dup：全部从原确认
Ready/Off 排入扫描参数／START／STOP 全recipe，再排广告配置；Queued 请求
均 Cancelled/-ECANCELED、零已选 opcode/step、原 Off 与同伴完整快照保留，
369包零丢包，初始化后零目标 DLI。扫描准入 EBUSY 保护及模型 idle STOP
拒绝均保留。286工具测试通过；这只是有界 FIFO 一CPU 模型支撑，未验证真实
活动同伴、普通并发或后续 partial／物理回复。正式 Linux/Rust WS73 路径未改；
真实启动、Managed、恢复、自然 RCA、14项整改及原全部 issues 保持 OPEN。


## 后续 partial 步骤采集与回归支撑（2026-10-11）

模型专用 format4 增加原初始化 step1/2 的选择，保留原500ms请求期限与
Cancelled/-ECANCELED。广告晚一步须核对原power回复；扫描START取消后只能
由新STOP确认Off，原最终STOP取消后可由原迟到成功Complete确认Off，不重复
STOP且不把旧请求改成Succeeded。每个跳过/保留模型帧的哈希和长度都须逐一
匹配实际USB抓包，重复opcode按命令窗口匹配，额外Complete/STOP拒绝。
旧format3第一步证据继续可复核，非零步骤禁止用于真实USB采集入口。
289工具测试通过；此提交仅源码/回归支撑，后续步骤VM fd矩阵尚待运行，
更不能替代真实Managed、活动Ready同伴或自动恢复。历史真实WS73路径不改，
原28项及恢复/自然RCA继续OPEN。


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

## 2026-10-12 当前源真实已建立连接的 File 六例通过

[独立重算证据](evidence/ws73-connected-file-six-case-matrix-20261012.json)
SHA256 `837900525cc78eda3090276c77a89ba1b2c3d800553308fdf655dab2a06e9ce5`。
实际内核 `1305136ce2c83d1180e84c62e96576def26816a4`，实际服务及冻结工具
`c255811b7617211093a7e342fbdad65f2efa65cf`；后续离线测试路径和证据提交
不能替代这个实际编译来源。VM109–114 两种角色分别 release、最后 fd 关闭、dup。
每例先初始化两只独立 Ready，扫描匹配新的随机广播数据、地址和 RSSI，然后真实
Create 的 OUT、Status 及两端物理 Up 成功。撤销时实际发出 handle 对应的 Disconnect，
两端收到匹配的物理 Down，目标回到 Free/Ready。dup 首次关闭保留同一个 File 的
作者查询和 Held，150ms 内没有 Disconnect；最后关闭才执行连接清理。完成连接的
历史作者结果不改成虚构 Cancelled，最后 File 销毁后不冒充可查询作者。

同行保留原 generation、完整 Ready 元数据和独立管理权，目标清理后成功执行
自己的广播 STOP、扫描 START/STOP。每例之后 UID1000/caps0 的 RF20+2 通过，
共132轮、7386抓包、零丢包、taint0、QEMU退出0，后续 RF 内 slkd/bus 不重启。
**File 阶段在 slkd 启动前进行，不能宣称 slkd 跨 File 清理不中断。**
本轮六例不暂停在途 Status/outcome，也不替代物理拔插、自然故障或非人工恢复验收。

VM108 原失败保留：真实 Create/release 观察到成功，但测试脚本将扫描配置带入
广播 STOP，内核正确拒绝 EINVAL，整例未通过。修正后重新跑完整六例。
CI38217600018 和 CI38217926644 的离线测试路径失败也保留；仅修正测试对
`SPARKLINK_KERNEL_SOURCE` 的读取后，CI38218222317 精确源码九项成功。
记录 UAPI 的离线夹具及变异拒绝测试不计作真实设备验收，当前393工具回归通过。

后续依赖顺序：真实 Create 在途 Status/物理 outcome 下的三种 File 撤销和同行隔离；
运行中 slkd 的连接生命周期/事件一致性；canonical loss resync 和 peer/handle lifetime；
当前源原初始化后续步骤矩阵、物理和四设备并行；继续完整 SSAP、安全/Bond、Profile、
PHY/PM、Native/Proxy 与发布矩阵。旧内核清理继续按[调用审计清单](LEGACY_CLEANUP_20261011.md)
并行推进：处理仍编入核心的旧 mgmt/dev/transport/serdev 及其全局 dead_code 抑制，
不因函数存在宣称能力，不删除尚未迁移的调用者或有价值故障证据。未发布 UAPI 可
同步删除，无兼容期限承诺。自然启动/bulk/重枚举/消失 RCA 和无需人工拔插的恢复
继续 OPEN；VM-only、原28项 scope、两个未合并 draft 和完整 goal 不变。
正常尝试114、维护37。


## 2026-10-12 当前源 Create 在途 File 十二例已通过

当前首优先中的 Status/outcome 保留、双角色 release/最后fd/dup 已由
[十二例原帧证据](evidence/ws73-inflight-file-twelve-case-matrix-20261012.json)
及[实现／严格验收边界](NATIVE_CONNECTION_IMPLEMENTATION.md)补齐；另有两个已
建立连接 dup 回归，共308RF、17234包零丢包、taint0。实际K1305136ce2c8／U0a980e5d9b73，
VM117–130；VM115/116 原失败保留，不升级为通过。
仍是 pre-daemon File 范围：运行中 slkd 撤销、晚到 link 归属、canonical resync 和
peer/handle lifetime 为下一优先。旧 mgmt/dev/transport/serdev 实际调用者已复核，
按三类清单继续迁移后删除，全局 dead_code 未记为清完。自然自动恢复/RCA和
所有其余S0–S6/28 issues仍OPEN，不因本轮部分成果关闭整项；VM-only继续。


## 2026-10-12 Canonical观察连接快照基础已实机验证

[新快照、lifetime与原事件屏障证据](evidence/ws73-atomic-link-snapshot-both-role-20261012.json)
补齐了从内核读取权威观察连接表的基础，两角色/VFS输入与copy拒绝/dup/同行控制
及RF44通过；详见[生产调用与限定验收](NATIVE_CONNECTION_IMPLEMENTATION.md)。
仍未将snapshot接入slkd loss恢复，address-type peer身份及原子lifetime disconnect
尚待实现，这些与运行中daemon取消/晚到link为下一优先。旧状态调用者接通新路径
并回归后删除，不把新增API称为整项resync完成。自然自动恢复/RCA、原28项完整
scope保持OPEN，VM-only和持续小提交不变。

## 2026-10-12 Native Disconnect 已迁到 canonical peer/lifetime 引用

[真实双角色 VFS14／普通 slkd／RF66 证据](evidence/ws73-peer-lifetime-binding-both-role-20261012.json)
覆盖 Linux38997、服务/工具d58fe5：generation/handle/lifetime/role/type/address
在 admission 与 queued selection 两处检查。未发布 submit UAPI 改为v2/128字节，
C符号明确v2；旧v1证据不改写。slkd native Disconnect 的旧 Device cache handle
调用已删除，bare native handle RPC返回NotSupported，新增 canonical connections
和显式 disconnect-link。正常VM累计135，维护40；捕获3839包/0drop、RF66、taint0。

双角色各七种错误引用由实际VFS拒绝，表不变、无作者结果、两端无命令；随后dup
最后关闭真实清理及同行RF通过。普通UID1000/caps0应用双角色从原snapshot取得
引用后真实断开，QMP移除重加和RF22期间slkd/bus不重启。前置File gate尚不证明
运行中daemon跨File撤销；queued handle reuse目前仅实际Host源码测试，未覆盖
实际固件句柄复用或selected→OUT竞争。生产语义详见
[限定验收与迁移边界](NATIVE_CONNECTION_IMPLEMENTATION.md)。

仍等待替代并删除：native Device event-delta/address-only projection。下一依赖顺序
为snapshot启动/loss resync+event_seq屏障→typed peer identity→迁移调用者与测试后
删除重复状态→运行中daemon cancel/晚到link/revoke验收→当前源物理/四设备门禁。
本批保留首build、LSan沙箱及首CI失败，修复为独立记录。自然自动恢复/RCA、
整项Managed、所有其余S0–S6与原28issues保持OPEN，不以部分成果关闭整项。

## 2026-10-12 已接通 daemon canonical 重同步并删除 Native 增量投影

[真实事件环溢出与空口证据](evidence/ws73-canonical-resync-real-overflow-20261012.json)
在 Linux38997、编译服务a4f29fc/9af145e上独立复算通过。Native subscriber 启动、
link通知、lost后读取完整table，校验身份/单调revision/event_seq及触发事件屏障；
旧link回放不能覆盖新lifetime。失败保留Unknown，每adapter一秒有界频率刷新，
不复位硬件。旧Native Up/Down delta、native handle读写路径及Device role/type字段已删除；
conn_handle字段仍供legacy调用者使用，等待独立迁移回归；
连接属性由canonical table派生，RSSI和opaque discovery不被刷新清零。

VM136维持真实双角色连接/断开/RF22；VM137测试监督器仅暂停guest整个slkd，实际
WS73报告继续推进32-event ring，双角色各至少40条原capture报告，lost均增加8后
Known自动恢复，同pid/bus未重启。两次暂停13.32/12.61秒，两端观察Ready/Held且
空连接表不变、期间没有USB命令。后续双角色连接/断开、RF22、QMP重加通过。
合计RF44/2914包/0drop/taint0，正常137/维护40，无hub切电。194 workspace、
strict clippy、402 tools与两源CI9/9通过；测试行为只在显式VM工具，不进生产daemon。

此次仅真实空表subscriber loss；不扩大成已建立连接loss恢复、实际handle复用或
单actor隔离。旧address-only discovery仍是alias：当前typed连接歧义时返回Unknown；
完整typed peer object namespace仍待迁移。Native legacy GetConnectionInfo明确不支持。
下一为typed namespace/调用者→真实linked loss与运行中cancel/late-link/revoke→迁移
回归后删legacy状态→当前源物理与四设备。自然RCA/非人工硬件恢复、整项Managed、
原28项及其余S0–S6继续OPEN，完整goal active，VM-only。旧源历史证据保留原scope。

## 2026-10-12 Typed Peer／lifetime Connection 已接通并验证真实 handle 复用

[实际对象／复用／旧对象拒绝证据](evidence/ws73-typed-peer-lifetime-objects-20261012.json)
使用Linux38997、编译服务/工具5f86cc5，生产实现28bdf6f。Peer按generation/type/
address区分，Connection子对象再绑定lifetime，固定handle/role；Known/Connected
只由canonical table派生。Known Down移除接口，Unknown保留原身份且标不确定，
发布/移除失败按adapter刷新重试。旧对象不再绑定复用handle的新连接。普通CLI及
真实gate已迁到object Disconnect，直接reference接口保留诊断用途，无旧Device
handle查找回退。address-only discovery仍是alias；typed discovery解析仍待验收。

195 workspace/strict clippy、406 tools通过；同地址type0/type1为实际daemon/
private D-Bus依赖测试，真实设备此次type0。VM138为GetInfo工具遗漏合法Selected
前缀失败，原输出/失败保留；修复仅工具，compiled source hashes完全一致。
VM139/140两端都真实handle0复用：lifetime1→3，旧路径改变；合计12旧对象案例/
24原CLI拒绝，期间两只无USB命令/无作者成功。后续双角色Create/Disconnect、
RF44/QMP重加同slkd/bus不重启，UID1000/caps0、2916包/0drop/taint0；正常140/
维护40，无hub切电。VM140重复空表订阅溢出，双角色lost8自动Known恢复。

限定：真实removed-object拒绝不等于queued stale invocation或selected-to-OUT
竞争；真实linked loss、同generation硬件query失败恢复仍未通过。下一顺序为
linked loss与运行中cancel/late-link/revoke→typed discovery/SSAP lifetime消费者→
迁移回归后删legacy字段→当前源物理与四设备。自然RCA/非人工硬件恢复、整项
Managed、原28项及全部S0–S6继续OPEN，完整goal active、VM-only。

## 2026-10-12 近期优先级改为真实每通道 socket 数据往返

用户明确要求：完成本轮 Peer/Connection 实机验收后，按最小纵向闭环推进
WS73 A3/ACB→数据 credit/背压→通道协商/身份→普通用户每通道 socket→
双设备短 PDU 往返→边界/分片/故障→四设备及用户态 SSAP。
[最新源码核对、封装差异及验收门禁](DATA_SOCKET_VERTICAL_PLAN_20261012.md)
取代上文近期“先完成 linked loss/所有取消竞争”的顺序；保留完整 S0–S6。
控制面必要修复、旧代码整改及自动恢复根因继续推进，相关 issues 不提前关闭。
Native 数据发送及 A3 RX 当前仍未接通，不将对象或 USB 写成功算作业务数据通过。
