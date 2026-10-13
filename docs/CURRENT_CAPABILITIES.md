# 当前能力与资格

**唯一当前资格入口。** [ARCHITECTURE](ARCHITECTURE.md)与ADR定义目标/契约，
[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)是唯一执行入口；
[采用记录](ARCHITECTURE_ADOPTION_20261013.json)记录用户提案、在线scope及调整。
五个维度独立；源码、离线、模型、实机均不替代其他维度，不用一个“完成”字段。

## 本批架构整改验收：单设备早期失败隔离

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


当前正常路径 **K308e5398dccc / 编译service及运行工具U420cc12**：
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
