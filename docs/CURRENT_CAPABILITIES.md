# 当前能力与资格

**唯一当前资格入口。** [ARCHITECTURE](ARCHITECTURE.md)与ADR定义目标/契约，
[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)是唯一执行入口；
[采用记录](ARCHITECTURE_ADOPTION_20261013.json)记录用户提案、在线scope及调整。
五个维度独立；源码、离线、模型、实机均不替代其他维度，不用一个“完成”字段。

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

当前正常路径 **K80a362ff3355 / 编译service与工具Uf4c65fb**：
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
| common Backend注册首批 | WS73/open测试provider实际迁移V1描述符；旧入口删除；标准USB未迁 | validator38、实际C拒绝11/sanitizer、Native33/连接operation12+Host、零warning/空VM3；fixture-only修正 | CBMC221限定准入，合法不变内核指针假设；不证明引用/并发/硬件 | 编译K7e654fde/U67165b6独立40短/8长度往返、16拒绝 | 标准USB/重复binding、真正Virtual/serdev、module/get-put/stopjoin全矩阵 |
| WS73发现/连接 | Native真实事务、动态adapter、typed Peer/Connection | 对应准确提交的生产源码/codec/ABI回归 | 不继承数据模型资格 | 当前K80a362ff/Uf4c65fb两次RF22、真实建链/断链与QMP支撑，历史物理证据保留 | 原NS1自然恢复、当前数据路径物理拔插/全部连接竞争 |
| 默认CUTC31/PI241 socket | A3/ACB、运行时254/5查询、独立命令/data credit、旧debt、有界TX与普通fd委托 | 当前33项Native/Runtime Session/epoch生产源码回归（USB/锁/注册依赖fixture）、CIdfb8636九项成功 | Credit守恒Kani仍未证明；不证明NOCP物理归属 | 新K80a362ff/Uf4c65fb DGRAM每角色20/共40轮61-byte实际对端往返，dup/最后关闭子门禁 | credit耗尽/满队列、完整票据/复用屏障、旧lifetime全矩阵 |
| 协商原期限/共享状态 | 38926b2完整三步骤与原期限；同锁快照、关闭/最终软件准入 | C编译、ASan/UBSan deadline/terminal selftest、完整新内核/空USB VM | FV01生产CBMC131项；FV03锁LKMM两性质，故意弱对照允许坏结果 | 上述新40轮及下述249路径保持 | 受控回复/credit阻塞期限、worker/VFS引用完整映射、唤醒及VM KCSAN/lockdep |
| application249/DTAP254 | 当前单ACB上限与精确长度拒绝，ec67348后工具/应用接通 | 196 workspace/423工具及严格clippy；准确dfb8636 CI9/9 | 不能从协商模型推出codec/分片性质 | 新版本8轮249字节及16次application250/253/254/255 EMSGSIZE，拒绝载荷捕获为零 | DG02同Binding短→最大→拒绝→短、其他层253/254/255、长包/PB TX/SAR |
| 提交票据切片 | K464d4d8a9de7 Runtime/Backend引用、一次commit、Host/data/gate内真正URB提交；Host数据撤销；未queued才回滚，已queued/不确定保留debt | Native25、driver10 sanitizer、Host49/连接12、Managed48；C/Rust严格对象及完整内核 | 精确K464/U854 Host撤销/提交锁序LKMM Never、弱对照Sometimes；credit回滚Kani仍NOT_PROVEN_UNSUPPORTED | 新40短/249八轮/16超限、发现连接路径保持 | controlled VM交错、完整Session/Channel/Grant引用证明、完整callback/VFS及NOCP复用屏障；不能宣布整项Ticket完成 |
| Session/Channel/Binding/Grant | K3c8da4fac302 Runtime持Session引用；CMTC/唯一ACB RX分流在Session，Channel独立队列/MTU/MPS；fd仅Binding；同life无协议前拒绝rebind，提交guard撤销检查 | Native/Session28、实际route/consent sanitizer、driver11、strict builds；引用模型只为依赖fixture | 新production Binding CBMC限定通过；2controller×2lifetime Session/fd/work TLC777924状态，仍无C/Rust/VFS refinement | 真实40短/249/16拒绝及每角色普通app dup后收发、last-close rebind拒绝；每端一次CMTC | 动态TCID/关闭协议/合格rebind、Grant epoch/安全、受控在途close/完整VFS/KCSAN/lockdep、NOCP/旧RX wire屏障与多通道 |
| Lease epoch/v2 Binding | K3ee1 Host单调Managed authority；Session带epoch；软件TX准入/真实USB提交锁下验证，successor拒绝旧代次；其他方向/安全拒绝 | Native33/Host51/Managed54、实际C准入队列与C/Rust v2编码一致、准确CI9/9 | 两个生产pure authority Kani限定通过；无完整Host/VFS/硬件证明 | 准确新40短/249/dup保持路径；不是DG09受控撤销 | blocked RX撤销、完整per-Binding Grant方向/安全、release/last-control-fd/daemon死亡/在途/peer隔离矩阵 |
| 受控Grant File子门禁 | 独立VM/普通应用kernel阻塞见证及真实收发工具；生产Kf103路径未变 | 新工具427与325d377 CI9/9，receipt/capture负向核对 | 不新增完整Grant/VFS证明，原pure authority/LKMM限定范围保留 | 六实机用例（两角色×release/last management fd/dup）；16业务往返；EACCES wake、旧fd不被新lease续期、同行原Ready/lease/scan保持 | daemon死亡/SCM_RIGHTS、方向/安全授权、在途USB/迟到真实RX及完整引用/恢复矩阵 |
| Binding scoped/directional Grant | Kernel bf8663唯一fd Grant、完整scope/方向检查、Host锁下发布、IRQ-save；OpenChannelScoped统一broker；protected拒绝 | actual C ctor/permission/admission/publish/TX/RX/poll sanitizer、early broker/D-Bus held-lock拒绝、C/Rust ABI与严格构建、428工具/CI9 | 生产pure ctor/identity/direction CBMC43限定通过；不证明Host/VFS/信任状态 | 新六项File撤销+两方向：TX-only→RX-only实际校验、禁反向EACCES/无载荷，invalid/protected bind拒绝；16往返+2单向，原40/249保持 | S5可信security/降级、独立owner死亡同行业务、受控在途/迟到真实RX、VFS/refinement/KCSAN/lockdep/NOCP/自然恢复 |
| NOCP/复用 | 旧debt保留，未知/过量/不确定Fault，不自动退款 | 生产ledger已重现四步复用风险 | FV07期望反例，不是安全证明；FV02 unsupported/超时NOT_PROVEN | 短40轮实际88完成、249八轮实际24完成，范围限定 | 同/跨life重复/迟到来源、准确性与可信排空屏障；无实机串包断言 |
| 旧SSAP业务 | K167f468剥离local DB/session/cache；K770364dcc152/U7d8857b删除18旧ioctl/业务字段/绑定，CLI/Profile拒绝；旧模型仅selftests；U56ea3e8默认facade NotSupported | 历史八项和生产依赖审计、Native20、连接边界及删除后用户态196/严格clippy；Python34含全Netlink声明一致性，facade私有D-Bus回归；实验callback回归保留 | 不能宣称已有生产用户Engine | 本批默认生产剥离通过：旧18 ioctl root/ordinary全部ENOTTY，新40短/249/发现建链路径保持；没有真实SSAP资格 | 本批退出条件通过；后续Session/Ticket/Grant/socket/Backend等目标架构整改，再WP08唯一用户Engine；相关整项issues仍开放 |
| SSAP/安全/Bond/Profile | 用户态目标层；旧Profile已隔离实验crate，Native不注册旧Profile | 部分机制/actor/类型测试，仅各自范围 | FV08/09完整协议证明未取得 | 尚无新真实通道服务/安全安装矩阵资格 | 唯一用户态Engine、真实read/write/notify/indicate、可信安装/Bond/Profile |
| Backend/事件/恢复/PM/四设备 | 现有Native及限定事件/生命周期基础保留 | 原完整方案/历史部分初始化和取消测试保留 | FV10及完整工作引用/恢复模型缺 | 历史物理/注入/部分清理仅其准确范围；本轮warm恢复不授予自然恢复 | 可注册seam/构建组合、事件迁移、四设备两组数据、自然RCA/非人工恢复、Proxy/PHY/PM/发布 |

历史Binding Grant基线：Kbf8663bb78eb、编译服务与工具Udfb8636；基础模式为SOCK_DGRAM。两次VM均保留原slkd、
同行generation/业务及真实断链/QMP支撑。QMP不是物理拔插，也不是自然恢复。
本批原期限/credit源码未改；形式化资格仍按原报告逐文件hash核对，未新增整体证明。

Netlink清理：K2d4817714963删除无消费者Rust副本/global dead_code；C bridge及UAPI/SDK保留，
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
