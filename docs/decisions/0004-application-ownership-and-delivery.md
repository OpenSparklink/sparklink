# ADR 0004：应用资源、管理权限与交付阶段

状态：采用；实现和验收范围独立记录。完整 S0–S6、drivers/net/slkd、VM-only 和
WS73 路径不变；UserHost 仍 P4 规划，不是数据或安全 relay 的前置条件。

## 依据与适用范围

核对官方 BlueZ `9dc7e40962f11d1d9a5568f8a7633a695288329c` 的五份资料。BlueZ 已有共享发现会话及客户端过滤约定，
并提供可选的 GATT socket fd 和 Profile fd 路径；本 ADR 是 SparkLink 的需求取舍，
不声称 BlueZ 缺陷、SparkLink 独创 fd 路径或已优于 BlueZ。

- [Adapter](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.Adapter.rst)：释放一个发现会话与停止最后一个共享会话不同；合并过滤后客户端仍须检查自己的条件。
- [Device](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.Device.rst)：连接、配对、持久 Bond、可修改信任策略及服务解析使用不同属性。
- [GattCharacteristic](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.GattCharacteristic.rst)：可选 fd/MTU、关闭与断链 HUP、通知会话和确认契约；不将确认推导为业务处理完成。
- [Profile](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.Profile.rst)：向已授权服务连接交付 fd，并定义断开清理责任。
- [main.c](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/src/main.c)：daemon 主循环及信号退出；不能由内部 actor 划分推导进程故障隔离或性能结论。

源码 hash 与本项目精确 baseline 见[本批审查](../evidence/bluez-contract-review-20261014.json)。

## 决策

1. 应用的扫描租约、通道 Binding 与管理者的 controller/物理连接权限分别授权。
   合并硬件扫描不得扩大客户端过滤或取消范围；按 caller、controller generation、
   原始期限、预算记录应用租约。最后一个有效租约才申请停止硬件扫描；强制管理
   停止是另一个操作，需要使全部受影响租约得到明确终态。
2. 当前真实扫描接口属于管理权限，迁移为 `StartControllerScan/StopControllerScan`。
   移除未发布的旧混淆名称并迁移调用者。**尚未实现客户端发现租约**；不把管理
   STOP 当应用释放，也不把仅改名当共享扫描完成。未来客户端入口须先接实际租约。
3. `sparklink` 是管理组；可选 `sparklink-apps` 只开放 Connection 的 `OpenChannel`
   和 `OpenChannelScoped`，不开放广播/扫描/断链/控制器操作或 service 名称所有权。
   kernel 仍要求特权创建绑定，broker 传递 scoped fd，内核强制 epoch/方向/lifetime。
   分组是粗粒度准入，**不是完整逐应用/逐 Peer 策略**；固定通道机制要求按后文安全epoch决策；动态protected仍拒绝。
4. Peer 为身份/观察；ConnectionSession 为一次物理 lifetime、信令/能力/分流/安全；
   Channel 为 TCID/PI/模式/独立队列；SocketBinding 为 fd 引用、授予范围与关闭。
   已观察连接、协商、服务发现、配对、Bond、认证、加密、本地授权分别表达。
   路径/地址/handle/本地 Trusted 策略均不是 wire 身份或真实安装证据。当前 Session
   仍与 Managed epoch 耦合，完整授权分离及旧 wire/NOCP 复用屏障仍缺。
5. 交付分为软件准入、实际 USB 提交、控制器完成、对端协议接收、对端应用处理。
   `sendmsg` 成功只描述有限软件队列准入；USB、NOCP、协议 ACK 不代表后续阶段。
   basic DGRAM 不承诺可靠/重传/业务处理；未来可靠模式另行定义才能开放 SEQPACKET。
   SSAP/Profile 复用既有 DTAP/socket，安全控制信令的 DLI relay 不另造业务发送通路。
6. fd 的 dup/fork/SCM_RIGHTS 共享同一 Binding 权限与引用，最后关闭结束该 Binding，
   不隐式断物理连接/停止 controller。逻辑通道关闭与同 lifetime 重开需真实关闭协议
   和残留隔离；当前缺失时拒绝。取消不能抹除已提交义务或归还不确定 credit。
7. 当前单次 SSAP 更新观察中 ACK1 只表示有界本地队列准入，ACK0 表示拒绝；
   notification 无 ACK。已准入后 caller 退出仍保留应完成的协议义务。队列满、
   原期限或 owner 丢失不得假成功；此处正向更新/CCC/可靠应用交付仍未取得实机资格。
8. per-controller actor/工作队列和原期限限制故障传播；共享 slkd 仍是一个进程。
   其崩溃会释放管理 fd，当前 epoch 撤销作用于相应 Binding，不能承诺所有业务 fd
   跨 daemon 崩溃存活。重启以 kernel 注册/实际 snapshot 收敛，不复活旧授权。

## Managed File 与业务 Binding 的撤权边界

控制File的release或最终引用释放撤销所属Managed epoch；dup的第一次close不能
释放仍有引用的租约。这不同于业务Binding最终close只释放本地未提交队列，亦不同于
声称关闭已经发送的物理义务。已开始PDU可能留下无末片前缀，必须保留原credit债务与
真实完成归属，不能模拟补齐或按应用退出退款。新lease不得恢复旧fd。

物理断链是另一事件：管理者可保持租约并发出绑定connection lifetime的Disconnect。
真实Down终结两端该连接及其旧Binding，不应撤销任一controller的独立管理租约。
阻塞者可先观察Session停止错误，后续操作必须按旧lifetime拒绝；禁止将撤权EACCES
当作断链归属检查通过。两端相连导致peer连接一起结束，不代表peer设备故障；
该peer保留Ready/扫描又不等于它的另一条独立业务连接已获验收。

证据只能在其实际观察精度内表达：release syscall前后区间、返回后无新USB提交、
迟到NOCP及等待者终态可以验证子门禁；完整提交线性化、引用/复用与原期限组合仍需
实际实现与模型对应。同行租约/Ready/扫描保留不等于另一独立业务连接存活。
跨VM受控交错不得直接比较宿主与guest墙钟。QMP真实状态由host自己的时钟排序，
guest按实际收到确认的单调/墙钟收据建立请求—确认—结果因果；PDU原期限用其
实际准入和终态的同一guest单调时钟测量。迟到NOCP不是期限刷新或失败Session复活，
这类受控延迟证据仍不证明硬件准确性、全部credit守恒、复用或自然恢复。

限定通过和未完成范围见唯一CURRENT_CAPABILITIES，不在本ADR累积逐轮资格。

## 改动相关门禁与剩余依赖

| 门禁 | 实现/离线与形式化 | 实机及退出条件 |
|---|---|---|
| 独立应用权限 | 精确 XML 白名单、实际 RPC/跨语言调用迁移；kernel cap/方向/epoch 检查 | 仅 apps 组 UID/caps0 领取并双向业务；拒绝扫描/断链/raw/管理；不能用控制组用户代替 |
| 应用共享资源 | 接 client 租约/过滤/有限预算/取消，模型不许清另一作者；无需等控制竞争全集 | 两应用一只 controller，退出/超时只释放自身；管理停止明确影响范围 |
| Binding 与在途 | 实际转换、票据、NOCP debt、dup/SCM_RIGHTS/最后关闭；unsupported/timeout 未证明 | 关闭/撤权/断链旧 life、真实 credit 压力及同行隔离；旧 wire 归属另证 |
| 分阶段交付 | socket poll/error/linger/RX 丢弃与消息完整性文档及实现对应 | 双端随机序号/载荷、协议及应用校验和回复；不得以 USB/NOCP/ACK 代替 |
| 更新与 Profile | 复用同一 SSAP actor/socket，ACK/队列满/owner-loss 的实际语义 | 正向 CCC/更新/安全依赖及应用 ACK；实验 Profile 不当已支持 |
| daemon/设备隔离 | deadline/取消/清理联合模型，锁/回调及 epoch 失效 | daemon kill/restart 与另一设备；FD 是否拒绝/保持按明示契约，不能默认存活 |

这些门禁分别关联 K#3/#4/#5/#6/#7/#10/#17/#18/#19、U#1/#2/#3/#5/#6/#8。
只设本次改动相关门禁；S0–S6、19 WP、10 FV、12 DG 的其他条件原样保留。
自然启动/重枚举/消失根因、非人工自动恢复与未完成整项 issues 均继续开放。

## 显式 CLI Agent 的范围

CLI 是现有 broker 的客户端，不增加 wire Engine。Agent 注册和安全请求权限属于
controller 管理；不同于普通应用通道。每个客户端固定原 daemon 唯一所有者，
同一作者连接保留 Allocate/Begin/Result/Cancel，所有权变化后不跟随替换。
人工逐请求回答，原 CLOCK_MONOTONIC 期限不刷新；一次未回答提示有界，未知/过期
或身份不符拒绝。EOF/退出仅注销该 Agent，Ctrl-C 请求只撤回本作者操作；broker
继续持有原生在途义务。不能从策略批准推导身份认证或 Bond。实际 CLI/VM 资格
按唯一能力入口单列，不继承旧测试 Agent 的历史通过。

## CPCD 与策略批准的界限

按T/XS20001-2025 §7.2.5.2/表40，客户端配置写入具有认证和授权要求，
并按当前连接独立、断链恢复初始值。不能以Agent同意、SDK111未认证加密或
可修改Trusted替代真实安全资格及内核授权。通知/指示生产接线必须保留这一检查；
不提供弱化的默认CCC路径。现有receive-interest仍只表示本地有界接收准入，
并不修改远端配置。此特定前置不扩展为全部控制面或Bond完成的依赖。
参考Host f0872df 的type2/两字节mask及每对端副本仅用于差分；本项目仍绑定
controller/generation/物理lifetime，以独立指示账本保留已在途义务。

## 数字比较机制与身份策略

数字比较复用唯一物理Session，IO/方法/算法必须由明确的有限模式选择，禁止从
对端请求自动降级。内核计算公开transcript的六位码并等待原作者的明确决定，
不得将显示码、相同码、本地确认、peer proof、安装接受或加密开启合并为同一状态。
原File/request/generation/lifetime/Grant epoch和原期限共同约束确认；确认不能刷新期限。
T在自身确认前允许暂存一份本Session的实际G proof，绝不采用参考Host的全局缓存；
只有本地同意后才验证并回应，撤销/到期后不得继续准入，物理义务仍保留。

有限机制的独立VM见证可以自动核对两端数字及公开transcript，但不充当生产Agent或
人类身份检查。slkd负责后续提示、方法和认证要求；内核须根据实际安装和完整过程
发布连接安全等级，再供可撤销的授权/SSAP权限消费。不能因机制局部通过开放可信
Grant或弱化CPCD检查。交互所需的期限策略另行设计，不能延长已经开始的请求。
准确资格统一登记于CURRENT_CAPABILITIES；尚未完成的Agent/安全等级/Bond、drain、
NOCP及复用假设继续开放，新的转换门禁不扩展为全部控制面组合的开发前置。


数字Agent沿用原Registry/Entry和监督任务，两次决策不得合并：前置Authorize仅允许
开始交换，实际flags8提示出现后才请求ConfirmNumericComparison。注册方法/Agent
唯一owner及epoch在Allocate冻结；Begin拒绝换方法。两个callback和后续原File确认、
proof、安装共享最初绝对期限。未知callback/拒绝/丢失/到期走原请求清理，已开始的
ioctl必须join。数字码和FrozenOperation终态均不是活连接安全等级或可信Grant。
前台CLI必须核对实际六位码和原id，不能把预输入批准用作后续数字确认；人机期限
策略及真实操作单独验收，不通过刷新已开始请求解决5秒预算的可用性限制。


## 实时安全状态与历史请求结果

原请求的成功/失败/取消终态属于一次操作；当前连接的机制事实属于物理Session。
不得在后续off时改写旧成功来兼作live状态，也不得将旧成功缓存成永久Encrypted。
每lifetime在原生接收处更新revision，早于普通队列；处理时冻结的revision与当前Host
不一致则不再暴露正向快照。这样普通队列丢失/延迟不保留旧资格，且不将Session
mutex带入USB callback。查询按Host→gate→owner锁序，不创建新Engine或物理Session。

选择保守处理重复/丢失/未知后继receipt：即使旧操作仍成功，也可以不再提供当前
正向机制，禁止未经协议屏障再启用。管理撤权、断链和退休继续由原身份/所有权
收敛；独立revision不替代Grant epoch或实际USB Ticket。只有未来在实际准入/提交
核对当前安全状态的Grant才可使用这些事实。原K6861快照资格未开放protected通道；
后续K61905139实现固定通道安全epoch Grant，新实机资格不得从原快照继承。
固件只有handle的0011/Complete、复用/drain和真实RF加密仍是明确待验证的受信任
基础，不把当前软件屏障描述为已经证明的硬件归属。


## 固定通道的机制要求与不可变 epoch

选择在现有Grant内冻结安全receipt epoch，而非每次查询slkd缓存。Runtime→data→
gate锁域内借用同一Owner读取机制等级，不创建第二Session或Engine。C Session内
不得反向获取Host锁；Owner停止路径先释放Owner锁再清理C Session。轮询/准入/实际
USB提交共享原Host callback线性化点；状态通知只重新检查，不授予权限。

接收包同时保存入口revision，避免加密前排队的数据被之后绑定的protected通道消费；
PB跨revision拒绝。失效只退休受影响绑定，既有物理debt保持；并非固件擦除/排空或
可信身份的证明。CBMC只证明生产纯Grant helper的有界性质，不能覆盖Host锁、Owner
引用、USB callback及固件行为。实际VM与组合验证分别记录，不扩大证明范围。


## SSAP首次绑定的安全要求

同一Connection只有一个SMTC Engine；其绑定要求应在首次bind前冻结。现有
plain自动启动不能靠后续安全快照或新增“安全启动”名称升级，固定槽也没有合格
的关闭/重绑屏障。消费端应传递实际要求并在同一Engine内等待/拒绝；操作声明与
认证/加密/本地授权独立，保留CPCD拒绝。CUTC生命周期与完整长包通过只支持其
准确范围，不宣称SMTC/SSAP安全消费者已接通。该规则收敛原分层，不另造Host。

### SSAP 首次安全绑定的实现边界

采用启动配置 `[ssap] channel_security=0|1|2` 固定每 Connection 的唯一 SMTC
最低机制。选择非零时，移除该连接发布时的普通绑定，真实机制完成提示同一
Engine 启动；显式调用也可尝试。最终安全准入仍在原内核 Grant/socket 路径，
不得由 Agent 批准或历史结果代替。失败不降级、不自动同 lifetime 重绑。
该配置不是属性级 ACL、命名身份或 Bond；这些原始范围继续独立实施验收。
新源码必须另行实机回归，旧受保护 CUTC 或普通 SSAP 报告不证明此消费者通过。

### 断链原因的协议边界与因果证据

Native 管理者主动断开使用 SLE 远端用户原因 `0x10`，不套用 Bluetooth 的
`0x13` 语义。SDK 实际 Host 对象、指定 NearLink Host 与新 WS73 包分别核对，
原始返回原因保留；请求、Status、本端 Down、对端 Down 和应用处理互不替代。
新旧13对照均可能快速终止，故原因语义修正不构成原超时根因证明。内核内部
清理及预 daemon 探针仍需迁移和实际生命周期回归，不由管理路径通过转授。
这不改变现有分层、唯一 Session／SSAP Engine 或 UserHost P4 优先级。

### 属性策略不采用只读快照加普通发送的授权模型

固定 SMTC 最低要求只能表达其声明的整通道约束。属性级策略须绑定请求接收时
的可信机制归属，
并让原 Kernel Grant/Ticket 在响应实际提交时校验所需上下文，不能由事后查询
推导旧请求受保护或消除查询到提交的窗口。安全机制及最终准入留在内核，属性
权限和业务留在同一用户态 Engine；ABI 未发布，准确实现/资格见唯一能力入口，旧 fd
授权不能因新 lease／lifetime／密钥状态而复活。未知 ancillary 应明确拒绝，
当前未解析的输入不能作为可用功能。该依赖不扩大为全部控制面竞争前置。


## 接收事实与发送授权分离

采用不可变的每消息接收epoch/机制观察。原epoch无法关联时保持unknown，换钥后
排队数据不获得新资格；CURRENT只描述已授权dequeue瞬间。普通recv可忽略记录，
需要安全上下文的调用者必须拒绝缺失/CTRUNC。RX上下文不充当未来TX授权，最终
提交仍由既有Runtime/Grant/Ticket强制。历史首批为 RX-only；当前类型化限制仅收紧
原授权，未知 ancillary 明确拒绝。纯 helper 有界模型的 Owner 真值/锁假设显式记录，
其通过不能替代真实内核并发、空口、固件或恢复验收。


### 响应原期限与最终提交约束

采用单个48字节TX constraint，与原fd Grant相交，minimum0也不解除epoch固定。
CLOCK_MONOTONIC绝对期限在响应义务创建时确定，最多剩余5秒；等待、排队清理和
每次实际USB提交复核，重试不续期。未知control及RX类型不能伪装此意图。
无物理前缀时过期/机制失效只退休该Channel；已有PB前缀继续按原物理错误路径处理，
不能为了隔离宣称义务消失或退款。SSAP 响应/错误/ACK 用原 RX 上下文，主动请求通过
原 fd 准备收紧原 Grant 的意图。本地授权尚缺，明确拒绝。模型仅证明候选快照的生产纯 guard，实际队列/锁/
Owner真实性/USB/credit/撤权晚到复用仍需实测与组合验证。


### 属性操作、值访问与准备发送保持独立

属性 operations 使用既有表32类型；access 使用独立六位 API 编码，参考固定
NearLink Host 的 NapiPermission，不误作 wire 声明。原请求 RX 机制限制值读取和
修改，公开发现元数据不暴露受保护值。本地授权未接通时注册 NotSupported，不能
通过布尔 policy 或 Agent 批准伪造授权。SDK111 等级2不等同命名身份/Bond。

PREPARE_TX 仅在原 fd 上填回当前 scope/epoch 并固定最初绝对期限；不预留 credit、
不续 Grant 或安全资格、不替代最终 USB 提交检查。主动请求和回复共用唯一 Engine，
客户端不接受与原意图 epoch/机制不符的回复。取消/超时和回复失败不能抹去已发生的
写入或物理义务。部分权限门禁、Kani/CBMC 和实际并发/恢复的强度分开；工具诊断、
缺性质或超时保持未证明，不凭局部谓词升级完整安全/身份/协议资格。

### 本地属性授权接线约束（2026-10-17）

继续参考固定 NearLink Host `f0872dfaac33` 的
`ssaps_server_write.c:SSAPS_WriteSingleItem`、
`ssaps_server_app.c:SsapServerAppWritePropertyCallback` 及
`ssaps_server.c:SSAPS_SendUserResponse`：先核对操作/安全要求，再保留请求并询问
本地服务端，批准后才读取或修改值。它的 requestId/address 查找不能原样作为本项目
的生命周期契约；授权必须绑定当前 controller/generation/physical lifetime、原 RX
security epoch、属性登记版本、方向及原请求身份，不由可复用地址/handle推导。
该参考是职责比较，不是标准裁判或本项目已有能力声明。

采用唯一 Engine 的有界异步授权义务，不另建 wire Engine。服务端登记与审批角色
须由管理策略授权，普通客户端、Agent 的安全协商批准及任意布尔值不能自授属性
访问。登记者绑定 D-Bus unique owner/登记epoch；先订阅退出再验证存活。服务消失、
撤销、重复/迟到批准、属性删除重建、Down/rekey 与旧 lifetime 均不能完成新请求。
本批引入 Owned 三方法与原 unique owner 的逐请求审批，保留独立管理 staging。
16 owner watch / 8 actor义务有界；实现不等于完整多应用部署或实机资格。

授权等待与物理响应义务分别记账，共用原始绝对期限及有限条目/字节预算。等待不得
阻塞其他 controller、Session RX、ACK 或已在途清理。批准在读值/改值之前再次核对
原请求和属性版本；响应继续携带原 RX epoch/机制下限/期限，经原 Grant/Ticket
准入。应用取消不撤销已发生的写入，队列接收不表示对端处理；重复批准只允许一个
终态。旧 staging 的授权位继续不支持；Owned 路径核对当前 owner/登记、原 RX 及期限。
CPCD 仍未接通，不增加配置布尔放行。

实施门禁只覆盖该链路：允许/拒绝/缺少审批者、审批者退出、原期限、晚到/重复批准、
删除重建、实际安全上下文改变及撤权/Down；真实两端验证值读取或写入、拒绝时不
泄漏/不修改，并保留普通业务同行。通知/指示发送与 CPCD 另取真实证据。无需等待
全部控制面组合，也不把此决策文字作为已实现、已证明或实机通过。


本批源码映射：`ssap_authorization.rs::Owner::pin/authorize` 订阅在存活检查之前，
owner watch持有连接，数据库仅持弱连接以避免对象服务循环；`Database::remove/revoke_owner`
与值准入共用数据库锁。`ssap_engine::authorize_server/complete_server` 保留原接收
身份/期限，真正发送继续经过唯一 Wire/Session/Grant/Ticket。`complete_server` 的
PREPARE 与数据库修改不是跨内核/daemon原子事务；后续失效不回滚已准入写入。
同数据库句柄不复用与 owner Arc 身份隔离旧审批；未证明的调度、kernel callback、
USB drain 和固件假设仍保持原未决条件。私有 D-Bus 测试中的 Ready/lease/RX上下文
是明确 fixture，不能升级为真实内核并发或安全证明。


## 2026-10-17：退休历史门面

采用“一状态一权威、一协议一实现、入口全链退休”。Powered的本地布尔量没有电源
语义，移除getter/setter及消费者；历史ListBonded/RemoveBond不等于可信Bond，连同
CLI/权限项/--storage删除，存储和旧配对写入只保留test编译。历史磁盘文件不迁移、不
删除、不升级为可信凭据。真正电源/持久Bond待实际机制及限定验收后定义新契约。
所有改动分有限批次；实际生产接口/调用者/绑定/测试/文档同时更新，不新增长期拒绝
门面。缓存预算/发布、Typed身份观察、SDK依赖方向与部署继续按唯一计划WP18清单
推进，不能以源码删除或私有bus通过代替新artifact的VM实机门禁；不阻塞SSAP和数据面。


## 2026-10-17：API三视图与依赖整改

采用唯一architecture中组件依赖、应用命名空间及运行时三视图。libsparklink是应用客户端，
不依赖Native或默认暴露管理lease；slkd直接依赖Native/Channel/独立共享契约，不依赖
自己的SDK；slk-protocol只含ABI/值/必要纯codec及转换，不执行设备、ioctl或D-Bus。
SSAP local/remote均是唯一daemon Engine的客户端，ServiceAuthorizer与安全Agent分开。
slktest经同一应用Channel，测试负载/计时/断言/报告留在工具，不把业务逐包送D-Bus。
目标API树不授予描述符、订阅、长写、可靠通道或Bond资格；缺实现的目标不先生成假门面。

按用户最新顺序先完成架构迁移，保留实测路径与在途工作，回归和必要修复继续；不等待
控制面竞争全集。R1a临时允许现有slkd→libsparklink Native包装只为连续迁移，R3调用者
接通后删该边并更新依赖门禁。每项例外须有明确替代和退出，不成为永久架构。


R3a实现先将现有已授权fd的查询、安全SCM/期限和系统调用迁到slk-channel；
slk-protocol保留同一ABI及纯校验，旧操作导出删除，不保留转发alias。Engine、
slktest和C桥用同一操作实现，测试/decoder一并迁移，不能复制循环或创建新Engine。
这只完成Channel操作边界；Native ioctl与SDK/共享D-Bus契约仍须下一切片迁移，
不能以一个新crate或离线通过宣称三视图架构全部达成。


R3b将已有Native Adapter、观察/事件/抓包与ioctl从旧混合层迁出，slkd、诊断和
实验调用者直接使用slk-native；不新造Runtime或状态机。protocol移除全部操作宏，
slctl共用纯marker编码不再依赖Native包装。剩余例外转为C/Python门面→Native，
仅限紧接的R3c完整调用者迁移；该门面不能以应用SDK名义发布，不是最终权限隔离。
R3c退出必须删除Native默认导出及依赖，不保留长期转发别名。旧未支持入口按R4全链
清单退休，不能将移动到Native误写成能力已验收。Native库自身不依赖Channel或客户端。


R3c实际接线：独立slk-contract承载现有路径/tuple/method，slkd/SDK/CLI均消费；
libsparklink的真实Client只向当前唯一daemon owner请求，显式无缓存核对原gen/lifetime，
不跟随替换者。slktest复用SDK申请fd，保留原业务循环/计时/断言，无每包D-Bus。
Native C薄桥/头/库迁入slk-native，应用库仅Channel薄桥/纯要求；默认Python不再导出
Native/旧Adapter，显式两库路径错误不回退。实际Cargo闭包拒绝SDK→Native和slkd→SDK，
两份头及实际C导出独立负对照。fd域检查不授Ready；本地owner核对不是跨总线/内核
原子证明，内核Grant/最终提交仍强制权限。C/Python完整broker/SSAP便利接口尚缺，
不生成虚假方法；R4旧拒绝入口/事件、R5门禁、R6干净VM部署仍须按原scope完成。

R4b决定删除未发布旧SSAP门面，而不是将其永远保留为NotSupported：它们没有
业务实现，且错误注释声称Engine尚不存在；保留会制造第二API与状态来源。
实际管理staging和Owned注册有不同资源/权限用途，均保留；远端只经现有Connection
actor/Channel。旧handle callback不发布RemoteService，保留原callback退出/阻塞/drain
测试。旧codec/权限语义继续复用，缺失新模式仍明确拒绝；删除入口不复用编号。

R4c删除Native公开混合Event：它曾承载没有generation/lifetime的旧handle、配对和
PM模型。真实Native广告不必经过这个模型，改为直接调用同一有界观察消费者，
typed记录与快照继续负责身份。原旧codec/shape测试留在test-only Native模块；
daemon历史Source/callback fixture只在测试编译，不成为第二套生产协议或Runtime。
现有callback退出/drain回归保留，编译缺失导出负对照防止恢复旧API。

R4c同时退休没有Native消费者的daemon experimental-legacy-profiles构建入口，
独立实验crate与原actor测试保留为dev-dependency，不恢复旧profile0接线。
生产依赖门禁对default与all-features均执行实际normal闭包及原负对照；
这不是完整公开接口/生命周期/部署或协议证明，R5/R6剩余条件不变。

R4d选择删除未发布的旧Native/Controller/ExtAdv/地址控制门面，保留当前typed请求和
完整身份快照；不为兼容保留NotSupported别名。Device仍是观察关系，不独立拥有物理
连接。计数复用Core bitmap，避免scalar返回/未写buffer形成第二假状态；明确pending/
fault分配不等于Ready。C整数错误统一负errno，open用NULL+线程errno，Python不丢失
来源或截断路径。历史ABI五布局移test fixture，当前公开头/类必须缺失；rawKernel仍有
自测消费者，下一批同迁后删，不复用编号。声明级退休清单门禁只能防已知回流，不能
取代实际符号、D-Bus、权限、生命周期和准确新artifact回归。

R4e注册对象与测试边界：Core注册表只拥有index/generation、setup/retirement和观察
元数据；Host Ready、发现/连接、能力与统计由实际Runtime/Backend状态表达。未消费的
注册flags/能力副本/统计/便捷方法删除，注册模块以deny(dead_code)防回流；真实
generation复用、候选分配、退休及partial init状态不变。该变更须准确新Kernel VM回归，
不能沿用旧0cd资格。其余DLI/命令模块全局掩盖仍需实际调用审计，不能全模块换成
局部allow以消除诊断。

未链接的历史crypto Rust/C已逐字迁入selftests/retired-security-state。原故障依赖与
专用VM probe继续消费这一份代码；实际生产P256/CMAC保留唯一来源，并由probe明确
include。历史fixture的module属性不是生产豁免，测试通过不成为认证/Bond或WS73
当前资格。旧报告原路径/commit/hash保留，新报告明确测试路径及boot/probe不同身份。

R5a选择实际ELF导出与两份公开头独立对照，防止只有声明或隐藏额外入口。该门禁不
替代ABI布局、真实D-Bus、权限或应用调用；测试工具的错误/截断/材料变更均必须拒绝。
测试dependency fixtures和生产字节检查分别标识，不能以检查数量宣称架构完整。

R4e2命令所有权收敛：未消费的裸命令链和按opcode寻找作者的结果入口退休；当前
Runtime Host仍是唯一调度/credit/物理义务来源。Diagnostic、发现、连接和relay使用
原typed准入、原期限和实际提交票据；Backend视图仅元数据/受控关闭，Runtime open
不由应用fd触发。历史raw ingress回归独立命名为测试，不能重新接入生产。该批准确
门禁在相应报告，DLI目录/全局掩盖及rawUAPI其余消费者仍待迁移，不宣称整架构完成。

注册元数据不得维护第二套协议能力：Provider的注册视图仅承担已验证总线来源、
地址；写入却无消费者的packed版本副本已退休，完整wire version/features及ACB/ICB仍由现有Native
快照提供。未消费的MTU/MPS、安全位等投影已退休，不能从全零/默认字段推导能力。
历史UART/SPI/USB元数据只属隔离selftests；实际标准DLI codec和Runtime/Session/
Grant/credit/Ticket保持原责任。剩余事件模型/全局掩盖及rawABI按唯一计划逐条退休。

关键控制器故障采用同一Host锁和故障状态：回调仅做有界状态转换，关闭新提交并
保留一项关键code观察，避免普通RX满队列吞掉处理义务。现有worker消费故障及
作者ledger，原取消/期限/终态和在途引用遵循原契约。取走诊断观察不解除Fault，
晚到credit不恢复Ready；其他controller不共享此状态。回调返回、控制器完成和
对端交付仍是不同阶段，任何恢复Ready仍需已有生命周期与已验证控制器屏障。

默认标准DLI只构造有实际消费者的命令结果/credit及关键故障；未接通业务事件在
ingress拒绝并计数，不把解析成功当作连接或安全状态。WS73 Native的现有
发现、连接、数据及安全仍经原lifetime-bound路径。未归属ring助手和旧业务
decoder只在隔离selftests；生产DLI以deny死代码/可见性约束防回流。


## 未发布入口与历史见证的边界

迁移调用者后删除旧controller/raw ioctl和跨语言门面，不保留永久拒绝别名；
历史编码保持保留、不可复用。当前Typed Native管理和授权Channel是唯一生产入口，
未知旧编码须在权限、对象选择和usercopy前ENOTTY。新模式的不支持错误仍属其
实际接口契约。无生产消费者的旧布局不得仅为ABI测试留在公开SDK；历史C/Rust/
Python见证私有化，保留来源与原断言。Codec/权限语义和有效SSAP actor不机械删除。

## R4 raw ABI有限退休与R5调用者边界（2026-10-18）

101个未发布raw入口已从生产声明/授权/分派全链删除；26个当前入口数值保持，
53个无消费者布局仅在私有历史测试中保留。旧编号不复用；无兼容期或只拒绝的旧SDK门面。
当前Native统计不投影假零值，测试用实际typed request/result replay及观察快照，
不把它们描述为物理credit/debt证明。编译源码与测试工具身份分开记录。

后续调用者整改采用已有Client、Channel和共享D-Bus契约；SSAP客户端仅发起daemon
操作并表达限定结果，不另维护wire Engine/远端事务状态。slctl与语言绑定逐条迁移，
迁移后删除重复身份规则、tuple与方法字符串；不为赶进度公开万能Proxy或Native逃生口。
局部迁移必须以实际新入口验收；普通应用业务fd仍直达socket，逐包不经D-Bus。


R5首批应用迁移只覆盖现有远端SSAP及Session观察：SDK借用固定Connection，
调用前后核对owner/generation/lifetime/handle/role/地址，不拥有wire事务或缓存；
slctl移除该部分重复proxy/身份规则，参数显示仍留在CLI。共享wire元组在独立契约，
实际daemon introspection保留独立字面签名门禁，避免两端共享同一错误。
现有方法及错误不改，通知观察不是远端订阅；其他管理/Owned/Agent/C-Python便利
接口继续迁移，不能据此宣布完整R5。参考固定NearLink Host客户端/IPC职责分离，
不复制其缓存权威、等待时长或按地址识别策略。
