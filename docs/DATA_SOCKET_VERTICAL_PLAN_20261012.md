> 本文件为2026-10-12纵向拆分历史参考；现已合入[唯一执行计划](IMPLEMENTATION_PLAN.md)。
> 后续优先级/工作包/门禁仅维护IMPLEMENTATION_PLAN，当前事实以CURRENT_CAPABILITIES为准。

# 真实 WS73 每逻辑通道 socket：近期实施顺序

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** 短消息主线起点、封装对照和最初依赖；后续唯一计划接管。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](IMPLEMENTATION_PLAN.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

2026-10-12 用户调整的优先级。保留完整 S0–S6 和现有分层；本节取代此前
“先穷尽控制面竞争组合，再开始数据面”的近期排序。完整目标及原 issues 均保持开放。

## 历史起点与证据（以下描述绑定当时源码）

核对 Linux `3840ec2ba70ca7fcf033fac5dde23ba020f11412`、用户态
`24ef21c46ec8d4db6f3f84d95326db5676fc3bd4`。真实运行内核为 `38997dc457be`，
服务/工具为 `5f86cc500ed8`；后续源码变更需重新验证，不继承实机通过标签。
[Peer/Connection 证据](evidence/ws73-typed-peer-lifetime-objects-20261012.json)
记录 VM139/140、双方真实 handle 0 的 lifetime 1→3 复用、24 次旧对象 CLI 拒绝、
RF44、2916 个 USB 包及零 capture drop；VM138 的工具解析失败保留。
源码 CI 38250456167、证据 CI 38251740356 均成功。旧对象拒绝不等于在途撤销，
空表 subscriber loss 不等于已连接数据流恢复。

在上述历史起点，Native `send_data` 明确不支持；Native RX 仅接受 A2 事件。
WS73 wire codec 尚无 A3 发送入口。旧 worker 的首字节 TCID 猜测及旧连接资源
不能充当 Native 数据归属或可用 socket 的证明。默认应用未提供已验收的数据通道。

## 封装与参考差异

* T/XS 10003-2025 §7.4、OHOS `dli_layer.c`：A3 后为 12-bit handle、
  分段标志及高位属性，随后 LE16 数据长度。OHOS 的 ts 位与标准保留位存在
  差异；首个最小路径使用完整 SDU、保留位零，其他模式在明确支持前拒绝。
* libws73-usb `f4d85d0` 的 A3 builder 使用 handle 0；其注释称固定 flag，
  不能据此丢弃连接身份。参考代码写入的内层 `[TCID LE16][length LE16]`
  不能解释为标准的 16-bit TCID：T/XS 20002-2025 §6.5.1 实际是 TCID u8、
  帧类型/O/C/RFU u8、长度 LE16。该 builder 的高字节零仅覆盖基础帧。
  TCID 0x01–0x1d 省略 PI；CUTC 0x1f 及动态业务通道需要 PI，不能将原始
  应用载荷直接按 SMTC 格式搬过去。单播线上携带对端 TCID，RX 查本端 TCID。
  零 handle 只能用于真实 handle 0 的连接，DTAP 标识不等于 connection handle。
* OHOS `f0872df` 的 DTAP 明确区分 src/local TCID 和 dst/remote TCID，
  CMTC=0x02、SMTC=0x0a、CUTC=0x1f；不能把这些编号一律当作已协商业务通道。
  `NEARLINK_SERVICE_STACK_LOCAL_TEST` 的数据 stub 不属于真实协议证据。
* 当前 SDK111 两只真实控制器查询为 ACB 254 bytes / 5 packets。
  使用运行时查询值，不硬编码池大小；无缓存或无可靠完成事件则不开放发送。
* T/XS 10003-2025 §9.1.8 的 0x0009 完成事件载荷为 handle LE16 + count u8。
  libws73 的缺字段默认补 1、零 count 补 1、池容量钳制均不能代替真实记账。

标准来自本地 `sparklink-standards`，提取文本位于开发目录 `.dev/standards`；
SDK 私有二进制不提交，libws73 仅用于布局/实机观察参考，不复制 LGPL 实现。

## 依赖顺序与门禁

| 步骤 | 实现范围 | 必须取得的证据 |
| --- | --- | --- |
| D1 | WS73 A3/ACB TX/RX；严格长度/handle/分段解析；显式控制器归属 | 独立 codec 回归，加两端实际 USB/HCC/A3 capture；USB 写入只算 transport |
| D2 | 每 controller 数据 credit/outstanding；与 command credit 分离；有限队列和背压 | 真正 0x0009 归还匹配 outstanding，零/超额/旧归属拒绝；无 credit 时停止提交 |
| D3 | 必要 CMTC 信令、能力协商及 local/remote TCID 映射 | 双方协商 capture；绑定 controller/generation/connection lifetime，禁止复用错投 |
| D4 | 最小每逻辑通道 socket，普通用户收发/poll/close/link-down | UID1000/caps0 的双方应用真实校验及回复；无 daemon 伪成功或模拟数据 |
| D5 | 先短 PDU 纵向闭环，再长包、边界、分片、满队列和失效身份 | 随机序号/载荷、交换方向重复；253/254/255、credit 耗尽、断链及旧 lifetime 拒绝 |
| D6 | 四设备两组并行，再用户态 SSAP、安全及 Profile | 两组独立归属/credit/故障隔离；真实通道上的 SSAP 读写/通知/指示证据 |

socket 的 fd 必须绑定已经确认的 controller/generation/lifetime 与通道身份。
选择 `SOCK_SEQPACKET` 式消息语义作为首个设计候选；具体内核 socket 注册、
地址结构与权限模型在 D3/D4 实现时核对当前 Rust/C API，不提前宣称 UAPI 稳定。
每个收发方向显式 local/remote TCID，队列按包数及字节双重限额。
关闭/断链唤醒等待者，旧 fd 不重绑定新 lifetime；poll 只能反映真实可读或可发送容量。
0x0009 在线上只有 handle/count，没有 generation/lifetime；软件不能伪称事件携带
完整身份。旧连接尚有未结清或结果不确定的 outstanding 时，需保留旧记账归属并
阻止该 handle 的新 lifetime 发送，直到有可靠的清算屏障或 controller generation
退休；不得把晚到旧完成事件归还给新连接。具体断链清算语义需用 SDK111 实机确认。

最小纵向验收必须由对端应用实际接收随机序号与载荷、校验后回复，并由原端再校验。
保存两端应用记录及 USB/HCC/数据包证据，提供可复算 decoder 和可复现 VM 命令。
日志、广播载荷、模拟回复、USB 写入成功均不能代替连接后的业务数据往返。

## 并行整改与开放边界

必要的连接身份、取消、清理和状态同步继续完善，但 linked loss、所有撤销竞争排列
及控制面负向测试全集不再作为 D1–D4 的前置条件。生产测试行为、旧重复路径和
未接通模块仍按既有整改清单迁移/隔离/删除；新数据路径不用旧 worker 的模拟成功。
保留广播扫描、真实建链断链回归。自然故障根因、非人工自动恢复、物理拔插及
当前源码四设备验收未完成时，相关 issues 继续开放。仅 VM 内运行实验内核与设备 I/O。
每个小提交分别标记“实现 / 离线回归 / 实机通过 / 缺失”，签名提交、推送并更新 issues。

## D1/D2 首个接入提交：实现与验收范围分开

Linux `1f78c540f1179aa7c8a37740b4c58eb64efb1a6b` 已接通 WS73 完整 SDU
A3 传输 callback、Native A3 RX 和 0x0009 完成入口。每 Runtime 独立持有数据
credit/debt 和最多 16 包、每包最多 2047 字节的 RX 队列。内部 DTAP seam 要求
controller/generation/lifetime/handle，旧 handle-only trait 仍不支持，未开放 raw
用户态数据 ioctl。完整 SDU 长度受真实查询值限制；缺 driver callback 不给发送容量。

USB 调用前记 outstanding，真实 NOCP 数量归还；零 count 不补 1，超额/未知完成或
不确定传输停止本 generation 数据 TX。旧 lifetime 的 debt 不因 Down 或 USB 成功
清零，阻止复用 handle 的新 lifetime 发送。RX 在 ingress 从 canonical table 绑定
lifetime；已知物理变更清理旧队列，Unknown 不推断新身份，断链/退休唤醒数据等待者。
Host→data→gate 的 IRQ 锁顺序不跨 USB I/O，发送与 native close 用 lifecycle 串行化。

17 个严格生产源码依赖测试、12 个原子 link ingress 回归，以及既有 12 connection
storage / 48 Host 与 ASan/UBSan/LSan codec 检查通过；实际 C/Rust 对象编译通过。
完整新 VM 内核正在独立构建，旧资格镜像未覆盖。离线测试中的 USB/owner/锁依赖
为 fixtures，不能证明真实数据收发或硬件完成语义。

仍缺：实机 A3/NOCP 捕获、必要 CMTC/能力/TCID/PI 路径、有限 socket TX 队列、
普通用户 socket/poll/close，以及对端应用校验并回复的业务数据闭环。
本提交没有提前完成 D1/D2，也不把内部 raw ACB seam 当成每逻辑通道 socket。
后续首先对新 VM 内核做既有建链/断链/RF 回归，再用独立测试 backend 验证实际
A3/NOCP；传输探测仍不代替普通用户业务数据验收。自然故障与自动恢复 issues 开放。

## 首个真实 ACB／PB／NOCP 双设备往返已验收，socket 仍待接通

[独立复算原始两端 USB 证据](evidence/ws73-acb-real-pb-transport-20261012.json)
绑定 Linux `e344e7b34dc6`、服务/工具 `5d9744fda824`。VM144 专用签名 external
selftest 在双方连接角色下完成 8 轮交替方向随机 nonce/载荷往返，对端实际接收、
校验并回传。64 个原始 A3 包独立重组为 32 个 SDU，16 个真实 NOCP 完成事件，
每设备每阶段准确 4 个完成计数；单次 finit_module 和卸载均成功。
其 taint4096 是明确的 external-test 标志，不作为 taint0 普通生产资格。
VM145 同源码不加载测试模块，普通 UID1000/caps0 的对象/建链/断链、RF22、QMP
回归及 taint0 通过；合计 RF44、2914 capture 包、零 drop，slkd/bus 不重启。
源码 CI9/9、19 严格数据源码及 413 工具回归通过。

失败历史保留：VM142 的 62-byte SDU 实际先收到 28-byte PB-first，full-only RX
错误拒绝导致接收设备退休；BusyBox 又重试了失败模块初始化。VM143 修复 RX 后
模块初始化成功，但工具缺 `/bin/rmmod`，整轮仍失败。后续独立重组、单次 syscall、
显式 BusyBox 卸载修复后才形成 VM144/145 证据。四只主机设备均保留连接，未切 hub。
即使短 PDU 也需要 DLI RX 重组，这是实机对依赖顺序的修正；TX 的 ACB254/5 查询
不能当作接收端始终提交完整 SDU 的保证。历史自然启动/bulk/消失根因仍未查明。

这一成果仅完成首个 D1 实机纵向传输并验证基础 D2 记账。发送/接收者为专用内核
测试后端；CUTC/实验 PI 未建立正式能力/通道协商，尚无普通用户 channel socket。
下一主线仍为必要 CMTC/能力/local-remote TCID/PI → 有限 TX 队列及 socket →
两端普通应用短 PDU 随机校验/回复 → 边界/长包/耗尽/关闭/断链/旧 lifetime →
四设备、用户态 SSAP、安全/Profile。完整 S0–S6、Managed、自动恢复和整改 issues
继续开放，不以这份底层传输证据关闭整项或替代业务验收。

## D3/D4 当前源码：默认逻辑通道初版，实机验收待运行

2026-10-13 重新核对 Linux `c7d5868113c8`、用户态生产 `aa3c3ab5295e`、
验收工具 `b054181`。已实现 AF_SPARKLINK/SOCK_SEQPACKET 的默认 CUTC31、
PI241 基础通道；地址独立携带 controller/generation/lifetime/handle 及
local/remote TCID。其他通道、可选模式和非初始网络命名空间明确返回不支持。
这只是首个逻辑通道纵向切片，不宣称多通道或动态通道完成。

内核按实际 ACB 查询限制单条消息（当前 SDK111：254−5=249 bytes），TX 最多
8 条，RX 受 socket 接收缓冲区限制，沿用独立数据 credit/debt。CMTC 交换基础
模式、MTU/MPS/version；5 秒有限协商期限，协商完成且回复提交后才开放发送。
slkd 验证现存 Connection 和 Managed lease，以 CAP_NET_ADMIN 绑定 socket 后
通过 D-Bus 委托 fd；普通应用仅对 fd 收发，无需 sudo 或设备原始写权限。
关闭丢弃未发送队列；generation/lifetime 失效使旧 socket 报错并唤醒等待者。
这些行为已有源码实现，但关闭/断链/并发及旧 fd 的新实机标签仍待单独验收。

`slctl channel-peer <connection-path> 4` 与
`slctl channel-roundtrip <connection-path> 4` 为独立应用。每轮 61-byte 消息包含
16-byte 随机 nonce、序号和校验载荷；对端校验后修改回复标志，原端核对完整回复。
VM 工具新增显式 `--channel-socket-verify`，与 external ACB selftest 分开；
双方 uid1000/caps0、原始应用输出、两端 USB/HCC/A3、CMTC、真实 NOCP 均需独立
核对才记成功。两次真实连接交换 caller/peer 方向；失败保留，不自动重试掩盖。

实际 C/Rust 对象编译、严格 workspace clippy、195 workspace 测试、19 数据源码
回归、CMTC/基础帧 ASan/UBSan/LSan 及 415 工具测试通过。完整新内核仍在构建，
**目前新 socket 尚无实机通过证据**。旧 e344/5d97 的 ACB transport 和 taint0
控制面/RF 标签仅属于其对应提交。新路径下一步先短 PDU，再长包、253/254/255、
credit 耗尽、满队列、关闭/断链/旧 lifetime、四设备两组、SSAP、安全/Profile。
固定 CMTC 请求标识及同 lifetime reopen 的晚回复隔离仍需后续完善；不把所有控制面
竞争排列设为短 PDU 启动条件。自然故障、非人工自动恢复、旧代码整改和完整 S0–S6
仍开放，不关闭部分实现所在的整项 issue。

## D5 边界与长包：分清 DLI PB 与 DTAP SAR

2026-10-13 补充核对 T/XS 10003-2025 §7.4、T/XS 20002-2025
§6.4.1/6.5.1/6.7.3，以及 OHOS `dtap_frame_basic.c` 和 libws73-usb
`f4d85d0` 的发送/完成实现。DLI PB 是单个 DTAP PDU 在主机与控制器之间的分段；
DTAP SAR 是流/可靠模式中把应用 SDU 切成多个 DTAP PDU。二者不能混用。
基础帧明确不执行 DTAP 分包，当前 socket 只声明基础模式；不能私自给基础帧增加
SAR、直接复制 SSAP 分片头，或把已经通过的 DLI RX PB 重组称为长应用 SDU 支持。

短包业务验收后，先分层记录应用 SDU 长度、DTAP PDU 长度、DLI 每段长度和 HCC/USB
长度。CUTC 基础帧的 DTAP 开销为 5 bytes，当前单次真实查询 ACB254 导致应用
单消息上限249。253/254/255 必须分别测试明确标注的层，不通过删减 PI/长度或扩大
硬编码发送预算绕过限制。249/250 的应用边界也需验证；超限返回 EMSGSIZE，禁止
USB 提交、credit 预留或队列残留，再验证短包仍可收发。

扩展长业务数据时，先验证有界 DLI TX PB 分段的 SDK111 实际控制器行为：每个提交
的 ACB 段独立消耗实际 credit；USB 成功仍不归还，NOCP 必须准确覆盖实际提交段数。
分段中的 EAGAIN 保留明确的未发送游标，关闭/断链只丢弃尚未预留的段，不清空已经
在途的 debt；同一 connection 的 PDU 不得交错分段。若部分 USB 提交结果不确定，
停止该 generation 数据发送并保留诊断，禁止本地宣称整条消息发送完成。
DLI RX PB、DTAP PDU 和应用消息各层分别校验尺寸、归属及重组期限，防止复用 handle
时续片进入新 lifetime。这个实现仍需真实 SDK111 对照，不提前承诺支持。

如果需要 DTAP 层流/可靠模式的 SDU SAR，必须先接通真实能力与通道模式协商、TxSeq、
首片长度及模式要求的超时/确认，再声明该模式。标准 §6.5.2 的 SAR 表与 §6.7.3.2
文字中“首片 SAR”描述存在不一致，实施时应核对原始版面、OHOS 帧编码和真实数据，
保留标准差异记录，不能根据单处提取文本推断线上编码。

后续真实矩阵保留：短包双向重复、各层253/254/255、长 SDU、credit耗尽/恢复、
TX满队列/poll唤醒、最后fd关闭/dup、断链与旧lifetime、四设备两组并行。每项都要求
随机线上 sequence/nonce/载荷，对端应用实际校验与回复、两端原始 USB/HCC/A3 和
准确完成记账。压力/边界用例未实机运行前，不继承短包或本地 socketpair 的标签。

## 新 socket 的空 USB VM 首次启动失败与修复

c7d5868113c8 完整内核编译通过（无编译器告警，保留一条 make jobserver 告警），
但空 USB VM 在 sock_register 注册 AF_SPARKLINK 时触发 UBSAN 越界并 panic：
`net/socket.c` 推导大小的协议族名称表仍止于 PF_MCTP45，新增46被越界索引。
没有挂入真实 WS73；整个流水线判失败，qemu进程exit0不覆盖guest panic。
[失败记录](evidence/ws73-channel-registration-boot-failure-20261013.json)保留准确镜像、
配置与console哈希。21e0600c82ef已签名推送修复：补充注册及lockdep名称，并加编译期
表长度守卫。修复后的构建、启动与普通用户真实socket验收分别重新核对，不继承旧标签。
这个可定位的软件启动bug不代表历史WS73自然bulk超时/消失根因已经查明。

## 首次普通用户 socket 实机：3轮通过，最后关闭丢包，整轮失败

21e0600c82ef/28a0d47 的真实两只 WS73 独立 Ready、双方 handle0/lifetime1，
两个 uid1000/caps0 应用完成 CMTC 能力交换与前三轮随机线上序号/nonce/载荷往返。
第4轮对端确实接收并校验请求，send返回后立即关闭；软件TX中的最后回复被清理。
原端十秒超时，整轮判FAIL，未进行角色交换或后续RF/QMP资格。
[独立失败记录](evidence/ws73-channel-last-reply-close-failure-20261013.json)保留
527包/零drop的capture及应用记录哈希。22条两端SDU记录覆盖CMTC和已提交数据；
发送方实际NOCP6，对端5，最后回复无USB TX/对端RX，不能用应用send日志冒充成功。

4a3dc86ade58已签名推送显式SO_LINGER支持：最后fd关闭允许真实worker在有界时间内
提交已准入TX（上限5秒），超时或故障仍丢弃未发送部分；不清除在途debt，也不宣称
USB成功等于对端收到。slctl应用显式请求2秒linger；本地seqpacket回归同时修复
POLLIN|HUP下完整消息未读取就提前失败的问题。实际对端收包与NOCP仍需重新验收。
未设置linger的关闭保持丢弃未发送队列语义，dup/断链/耗尽等仍需独立真实矩阵。

## 默认逻辑通道普通用户短 PDU 首轮实机通过

[完整可复算证据](evidence/ws73-ordinary-channel-socket-20261013.json)绑定 Linux
`4a3dc86ade58`、服务/工具 `4426d9731fad`：两个独立 UID1000/caps0 应用，在双方
真实连接角色（handle0、lifetime1→3）下共8轮61-byte短消息往返。每轮线上sequence、
nonce随机，实际对端校验载荷并回复，原端完整校验。只使用默认基础CUTC31/PI241，
有真实双端CMTC能力/MTU/MPS交换；没有external test module，taint0。

主机对原始pcap重新解码并独立复算，与运行时证明一致：80个A3包重组48条双端SDU
（业务16次发送各有TX/RX、协商8次发送各有TX/RX），24个真实NOCP计数合计24，
每controller每phase准确6；1585 capture包、零drop。旧对象、建链/断链、RF22和QMP
支撑检查同轮通过，slkd/bus未重启。QMP不能替代物理拔插；该证据不继承旧head的
物理标签。源码CI38278961181终态9/9，418工具回归含对这份记录的独立复算及篡改拒绝。

首次注册panic、首次实机最后reply关闭丢弃的失败记录均保留，之后修复才取得本轮
资格。linger等待软件TX真实提交，不将USB成功当作对端收到；最终发送依靠实际对端
应用与USB RX证明成功。关闭/dup/断链/旧fd/耗尽竞争全集仍需后续独立矩阵。
短消息首个纵向切片已通过，下一主线扩展重复轮次及长度边界，再有界长包、credit
耗尽/满队列、断链/旧lifetime、四设备两组和用户态SSAP；动态多通道、可选模式、
安全/Profile、自然故障/非人工自动恢复和完整S0–S6均未完成，整项issues继续开放。

## 2026-10-13架构review排序增补

采用[ADR0002](decisions/0002-session-socket-lifetime-and-proof-contract.md)与[集中能力状态](CURRENT_CAPABILITIES.md)。先修复协商期限/共享发布P1、加入本次相关的最小实际代码验证；同时继续249/250/分层边界和长包/压力矩阵。Session分流先于多通道/四设备SSAP。保留40轮与失败证据、S0–S6、现有分层和VM-only；提交窗口为待证明风险，不描述为已实机串包。所有控制面组合仍不是数据面前置。
