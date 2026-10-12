# 当前能力与资格

**唯一当前资格入口。** [ARCHITECTURE](ARCHITECTURE.md)与ADR定义目标/契约，
[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)是唯一执行入口；
[采用记录](ARCHITECTURE_ADOPTION_20261013.json)记录用户提案、在线scope及调整。
五个维度独立；源码、离线、模型、实机均不替代其他维度，不用一个“完成”字段。

当前源码资格K3ee1a60bf06f/U2a97786：Managed lease epoch、Host锁下软件TX准入和USB提交
检查、socket v2 lease字段已接通；Native33/Host51/Managed54及实际C准入/ABI离线通过。
两只真实WS73在VM取得新40短/8轮249/16超限及dup/最后关闭拒绝重开子门禁，CI9/9。
这是正常业务保持资格；完整方向/安全、blocked RX撤销、daemon死亡和在途/物理矩阵仍缺。
旧Session表中资格保留其原准确源码，不扩大到新的Grant撤销验收。

当前Kf1034577ecc1/Ud570819：RX每次正常唤醒后在Host授权锁下取包/PEEK引用，
等待/copy在锁外；actual C函数体sanitizer与限定LKMM通过，新VM40短/249保持回归、CI9/9。
原40/249资格为nonblocking recv；新下述六项File子门禁取得真正blocking recv见证，完整DG09仍缺。

开发切片Kaab814ac176b：canonical Grant存Binding，全scope/TX/RX检查接通；RX-only
发送先拒绝，不触碰用户payload。scoped broker入口统一；protected security仍NotSupported。
实际C/ABI/broker拒绝测试和pure CBMC限定通过，尚待准确新源码VM回归，不能继承旧资格。

| 范围 | 已实现 | 离线通过 | 形式化限定通过 | 实机通过 | 仍缺失 |
|---|---|---|---|---|---|
| WS73发现/连接 | Native真实事务、动态adapter、typed Peer/Connection | 对应准确提交的生产源码/codec/ABI回归 | 不继承数据模型资格 | 当前Kf1034577ecc1/Ud570819两次RF22、真实建链/断链与QMP支撑，历史物理证据保留 | 原NS1自然恢复、当前数据路径物理拔插/全部连接竞争 |
| 默认CUTC31/PI241 socket | A3/ACB、运行时254/5查询、独立命令/data credit、旧debt、有界TX与普通fd委托 | 当前33项Native/Runtime Session/epoch生产源码回归（USB/锁/注册依赖fixture）、CId570819九项成功 | Credit守恒Kani仍未证明；不证明NOCP物理归属 | 新Kf1034577ecc1/Ud570819 DGRAM每角色20/共40轮61-byte实际对端往返，dup/最后关闭子门禁 | credit耗尽/满队列、完整票据/复用屏障、Grant epoch、旧lifetime全矩阵 |
| 协商原期限/共享状态 | 38926b2完整三步骤与原期限；同锁快照、关闭/最终软件准入 | C编译、ASan/UBSan deadline/terminal selftest、完整新内核/空USB VM | FV01生产CBMC131项；FV03锁LKMM两性质，故意弱对照允许坏结果 | 上述新40轮及下述249路径保持 | 受控回复/credit阻塞期限、worker/VFS引用完整映射、唤醒及VM KCSAN/lockdep |
| application249/DTAP254 | 当前单ACB上限与精确长度拒绝，ec67348后工具/应用接通 | 196 workspace/423工具及严格clippy；准确d570819 CI9/9 | 不能从协商模型推出codec/分片性质 | 新版本8轮249字节及16次application250/253/254/255 EMSGSIZE，拒绝载荷捕获为零 | DG02同Binding短→最大→拒绝→短、其他层253/254/255、长包/PB TX/SAR |
| 提交票据切片 | K464d4d8a9de7 Runtime/Backend引用、一次commit、Host/data/gate内真正URB提交；Host数据撤销；未queued才回滚，已queued/不确定保留debt | Native25、driver10 sanitizer、Host49/连接12、Managed48；C/Rust严格对象及完整内核 | 精确K464/U854 Host撤销/提交锁序LKMM Never、弱对照Sometimes；credit回滚Kani仍NOT_PROVEN_UNSUPPORTED | 新40短/249八轮/16超限、发现连接路径保持 | controlled VM交错、完整Session/Channel/Grant引用证明、完整callback/VFS及NOCP复用屏障；不能宣布整项Ticket完成 |
| Session/Channel/Binding/Grant | K3c8da4fac302 Runtime持Session引用；CMTC/唯一ACB RX分流在Session，Channel独立队列/MTU/MPS；fd仅Binding；同life无协议前拒绝rebind，提交guard撤销检查 | Native/Session28、实际route/consent sanitizer、driver11、strict builds；引用模型只为依赖fixture | 新production Binding CBMC限定通过；2controller×2lifetime Session/fd/work TLC777924状态，仍无C/Rust/VFS refinement | 真实40短/249/16拒绝及每角色普通app dup后收发、last-close rebind拒绝；每端一次CMTC | 动态TCID/关闭协议/合格rebind、Grant epoch/安全、受控在途close/完整VFS/KCSAN/lockdep、NOCP/旧RX wire屏障与多通道 |
| Lease epoch/v2 Binding | K3ee1 Host单调Managed authority；Session带epoch；软件TX准入/真实USB提交锁下验证，successor拒绝旧代次；其他方向/安全拒绝 | Native33/Host51/Managed54、实际C准入队列与C/Rust v2编码一致、准确CI9/9 | 两个生产pure authority Kani限定通过；无完整Host/VFS/硬件证明 | 准确新40短/249/dup保持路径；不是DG09受控撤销 | blocked RX撤销、完整per-Binding Grant方向/安全、release/last-control-fd/daemon死亡/在途/peer隔离矩阵 |
| 受控Grant File子门禁 | 独立VM/普通应用kernel阻塞见证及真实收发工具；生产Kf103路径未变 | 新工具427与325d377 CI9/9，receipt/capture负向核对 | 不新增完整Grant/VFS证明，原pure authority/LKMM限定范围保留 | 六实机用例（两角色×release/last management fd/dup）；16业务往返；EACCES wake、旧fd不被新lease续期、同行原Ready/lease/scan保持 | daemon死亡/SCM_RIGHTS、方向/安全授权、在途USB/迟到真实RX及完整引用/恢复矩阵 |
| NOCP/复用 | 旧debt保留，未知/过量/不确定Fault，不自动退款 | 生产ledger已重现四步复用风险 | FV07期望反例，不是安全证明；FV02 unsupported/超时NOT_PROVEN | 短40轮实际88完成、249八轮实际24完成，范围限定 | 同/跨life重复/迟到来源、准确性与可信排空屏障；无实机串包断言 |
| 旧SSAP业务 | K167f468剥离local DB/session/cache；K770364dcc152/U7d8857b删除18旧ioctl/业务字段/绑定，CLI/Profile拒绝；旧模型仅selftests；U56ea3e8默认facade NotSupported | 历史八项和生产依赖审计、Native20、连接边界及删除后用户态196/严格clippy；Python34含全Netlink声明一致性，facade私有D-Bus回归；实验callback回归保留 | 不能宣称已有生产用户Engine | 本批默认生产剥离通过：旧18 ioctl root/ordinary全部ENOTTY，新40短/249/发现建链路径保持；没有真实SSAP资格 | 本批退出条件通过；后续Session/Ticket/Grant/socket/Backend等目标架构整改，再WP08唯一用户Engine；相关整项issues仍开放 |
| SSAP/安全/Bond/Profile | 用户态目标层；旧Profile已隔离实验crate，Native不注册旧Profile | 部分机制/actor/类型测试，仅各自范围 | FV08/09完整协议证明未取得 | 尚无新真实通道服务/安全安装矩阵资格 | 唯一用户态Engine、真实read/write/notify/indicate、可信安装/Bond/Profile |
| Backend/事件/恢复/PM/四设备 | 现有Native及限定事件/生命周期基础保留 | 原完整方案/历史部分初始化和取消测试保留 | FV10及完整工作引用/恢复模型缺 | 历史物理/注入/部分清理仅其准确范围；本轮warm恢复不授予自然恢复 | 可注册seam/构建组合、事件迁移、四设备两组数据、自然RCA/非人工恢复、Proxy/PHY/PM/发布 |

当前实现/资格：Kf1034577ecc1、编译服务与工具Ud570819；基础模式为SOCK_DGRAM。两次VM均保留原slkd、
同行generation/业务及真实断链/QMP支撑。QMP不是物理拔插，也不是自然恢复。
本批原期限/credit源码未改；形式化资格仍按原报告逐文件hash核对，未新增整体证明。

Netlink清理：K2d4817714963删除无消费者Rust副本/global dead_code；C bridge及UAPI/SDK保留，
Python契约核对实际C/SDK。U6bb7985拒绝ExtAdv静默截断，实际方法held-lock/ENOTTY回归通过。

证据索引：

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
