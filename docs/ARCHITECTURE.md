# SparkLink 架构

Canonical：本文件定义目标所有权与分层；[ADR0001](decisions/0001-management-channel-service-boundaries.md)
与[ADR0002](decisions/0002-session-socket-lifetime-and-proof-contract.md)定义决策和接口契约；
[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)是唯一执行/依赖/门禁入口，
[CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md)是唯一当前资格入口。
2026-10-13采用用户完整提案（hash f6f8e16d856072914cb30989595343e308c7535015cf47e5fcca2ea7cee19133）。
目标描述不表示代码已接通；最新事实与调整见[采用记录](ARCHITECTURE_ADOPTION_20261013.json)。

最新准确VM路径Kae5b24535a89/U967ad220保留fault同行8业务、40短及249/16拒绝。
标准和WS73的实际USB transport/driver归drivers，Core只管协议/Runtime/身份入口；标准独立模块，
Core取消USB=y依赖。精确注册/失败清理与PM拒绝不等于完整callback/IRQ/module/PM证明。
[准确源码与限制](evidence/standard-driver-move-offline-20261013.json)、[构建组合](evidence/standard-driver-move-build-matrix-20261013.json)。
standard0仅query，未接通typed/data明确拒绝；install不是Ready。
真正Virtual、canonical事件与旧ring、标准ticketed数据、完整lifetime/回调与自然恢复仍缺；
先完成目标架构整改，再扩展功能；完整S0–S6及原scope不变。

历史正常路径K9c0e616c/编译及工具U1cccf5d：动态Registration观察对象接通，Core直接核对
GetSnapshot和列表；pending无Runtime/Managed，Installed不宣称Ready。通知/目录只管拓扑，
不供权威状态。[准确实机与限制](evidence/registration-daemon-offline-20261013.json)。
普通控制及default observer的真实Fault/移除/复用+8业务、新40/249均通过；未覆盖所有Pending过渡。
标准Backend/bus拆分/真正Virtual/事件统一与完整回调/恢复仍待整改。

历史正常路径K9c0e616c/编译serviceU71ef24d/工具Uff5ab35保持40短/249资格。
Core注册诊断已通过未绑定的40-byte快照接通SDK/CLI；Pending/Fault、Installed和Retiring与
Host Ready分开，Core锁下原子观察按generation命名；[准确源码与证据](evidence/registration-diagnostic-offline-20261013.json)。
动态daemon pending/fault对象仍未接通，标准Backend/事件与完整callback/PM整改仍开放。

受控早期失败隔离已在K308e5398/编译serviceU420cc12/工具Uc07120f取得限定实机资格：
Core pending故障不发布Ready、精确取消/新gen重新接入、同行与恢复后共8真实业务往返、同slkd。
[证据与限制](evidence/ws73-early-bootstrap-fault-isolation-20261013.json)：不是自然恢复或完整部分初始化/回调证明，动态诊断/标准Backend/事件迁移仍待整改。

历史正常路径K308e5398dccc/编译与工具U420cc12：Runtime拥有ConnectionSession，Session唯一消费ACB并处理
CMTC，Channel独立有界队列，socket只持Binding；单基础通道限制继续保留。
实验AF/PF_SPARKLINK=46已经接入当前fork，正式分配尚待协调。基础模式SOCK_DGRAM；
未取得可靠模式资格的SOCK_SEQPACKET明确拒绝。新准确版本取得40轮短消息、8轮249-byte
及16次超限拒绝、dup保持收发和最后关闭后同life重开拒绝；不授予动态通道/关闭协议、
长包、多通道、四设备数据、安全、完整Grant或自然自动恢复资格。

Grant由内核强制核对完整scope/方向/Managed epoch；bf8663锁下最终发布已接通。
受控broker的SCM_RIGHTS交付/撤销六例已通过；真实共同slkd死亡/接任已取得两角色子门禁；可信安全及独立所有者隔离仍开放。
最后数据fd关闭仅释放Binding及本地队列，不重建CMTC；同lifetime基本通道重绑明确拒绝。

默认daemon从86bfbc8起拒绝未迁移profile0并只启动canonical事件游标；
旧事件actor仅test/显式实验构建，内核旧ring和其余调用者仍待迁移。
专用fd客户端/接收器及init监督已在VM完成两角色真实共同slkd死亡/接任；
两lease都撤销、旧fd不续权。首醒按Grant或物理lifetime先终止区分，见ADR0002。
独立管理所有者/四设备两组同行业务、在途提交与完整生命周期证明仍缺。

模块初始化现为空注册表；旧configfs假UART/SPI/None构造、忽略open错误注册及对应
selector arms已退出。实际bus注册后才创建Runtime；历史模型移selftests。后续调用审计证明旧serdev无实际driver入口，其Rust/C/ctx/parser
及最后消费者退出后的UART decoder全部隔离selftests；默认无serdev回调/全局parser符号。
H4/SPI无provider descriptor不再登记，transport全局dead_code掩盖移除、死成员删除。
实际空USB门禁与新40/249通过；不宣称新的每设备serdev实现。
剩余标准USB/Native静态分派、标准USB重复binding表、其他bus每设备parser/module与callback屏障仍待WP13，未完成整项Backend架构。

Common Backend 注册首批已落地于 K1c720574d72f：WS73 与显式 open 测试 provider
调用版本化 `sparklink_backend_register`；旧 `sparklink_native_register` 不再导出。
描述符和 ops 在调用期间有效且不可变，core 先复制并验证，再分配/持模块与 context 引用；
能力必须匹配真实回调，未知版本、方言、bus 与能力位明确拒绝，不产生 Runtime。
注册仍为 Setup；既有 generation、Host、ticket、credit、close/join 契约保留。
该内部接口不承诺兼容期，TEST 标签不表示已实现 VirtualBackend。标准 USB 尚未迁移；
K7e654fde93b9进一步先拒绝未知布局，再复制尾部/跟随ops；实际C拒绝11项通过，
前版负对照检出越界指针访问，仅主机纯fixture失败。K5f8e310仅迁移两项测试fixture，
生产源与K7e654fde逐字节一致，实机证据仍注明编译K7e654fde。
此批不授予其他 bus、模块卸载竞争或完整注册/停止回调证明资格。

共同入口整改K3b72c7fe/80a362ff：`sle_ingress`归Runtime，持exact owner Arc与generation，
Native/Session/worker不再导入USB模块来查找、入队或消费Runtime。发布持退休gate并拒绝
占用槽覆盖，unpublish只移除相同Arc；worker不再重新发布。解码丢包计数归各Runtime。
RX和Native/USB命令准入统一Host→gate（RX再取ingress），反序释放IRQ guard后调度；
旧gate→Host反转由前版实际函数rank负对照检出，未观察到实机死锁或自然根因。
锁模型仅单identity/有效引用/一次发布退休；实际函数8项是std锁/Arc/Host依赖回归。
准确80a362ff/f4c65fb VM40短/249八轮/16超限与CI9保持；不宣称IRQ/lockdep/KCSAN、
callback回收或完整USB独立构建通过。标准USBprobe/FFI/enum/binding下一批迁移。

最后观察者审计K7de1d1316412：health也改为Host→gate，保持只读；生产函数9项
覆盖Setup/Ready/radio/fault/retired/旧generation和同行。显式let gate→Host语法
扫描无剩余候选（不是完整间接锁证明），本版独立40短/249八轮/16拒绝与CI9通过。
历史80a362ff/f4c65fb证据保留，不把旧成功直接改授新提交。

标准USB注册整改Kb619aecf：先reserve pending id/generation，未知MAC/版本/能力为零，
不再生成地址或提前setup_complete。删除独立协议/binding表，Root统计从registry和
Runtime表派生；未发布36-byte stats同步改名pending_count/runtime_count，两者非Ready。
成功C注册后才允许失败清理；精确generation detach先标退休、join后释放index，
重复/迟到detach不清除别的owner。USBlistener open与close共用Backend生命周期屏障，
状态锁不跨I/O；两listener成功且gate仍活跃后才发布transport_open。
生产13项注册/allocator/detach/open依赖回归与bootstrap/metadata回归通过；两个直接
生产allocator Kani harness有unsupported警告，均未证明。实际模块/callback/IRQ未闭合。
首轮真实40数据子门禁完成，但peer USB Down1112ms越过原1s观察使全轮FAIL，证据保留。
工具552fc62使用两端共享、不可刷新的5s诊断预算并逐端对应真实Down/propertyfalse；
不是协议时限保证或生产提前置false。本版新40/249/16拒绝和CI9通过，QMP仅支撑。
标准USB全局C资源表已删除，实际调用者持每probe引用context；静态Usb分派仍在，
尚未完整迁common Backend或从core拆独立driver；
profile0默认daemon继续不支持，无标准USB物理资格，不恢复不可靠旧SSAP。

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

当前正常路径 **K06c901906b7e / 编译service及运行工具U0960ed9**：
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

当前正常路径 **Kc44b74509c41 / 编译service及运行工具U4d14b35**：
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

当前正常路径 **Ke5d1e3311261 / 编译service及运行工具Ue7275d2**：
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
动态daemon pending/fault adapter、新公开诊断绑定、ROM/自然冷启动、实际失败及partial-init/同行隔离、
标准方言/bus构建/真正Virtual/PM及自然根因/非人工恢复继续缺，整项issues保持开放。

## 目标分层及架构决策

### 总体结构

```mermaid
flowchart TB
    App[普通应用 / slctl / SDK]
    Daemon[slkd：策略、授权、SSAP、Agent、Bond、Profile]
    Sock[每逻辑通道 socket fd]
    Core[net/sparklink：Runtime、Host、Session、Channel、credit、安全机制]
    Driver[drivers/sparklink：总线、固件、HCC/BSLE、URB、硬件恢复]
    Hw[真实 WS73 / 后续硬件]
    Vendor[可选 slk-vendord]
    Observe[独立事件 / snoop / slkmon / slkdump]
    App -->|管理与服务 API| Daemon
    Daemon -->|管理事务与状态订阅| Core
    Daemon -->|授权并交付 fd| App
    App <-->|业务消息| Sock
    Sock <--> Core
    Core <--> Driver
    Driver <--> Hw
    Vendor <-->|受控 Backend Proxy| Core
    Core --> Observe
```

### 唯一职责

| 层 | 唯一所有者 | 禁止跨越 |
|---|---|---|
| drivers | 总线匹配、端点、固件、板配置、传输 framing、设备 I/O、电源和硬件恢复 | 应用策略、SSAP 数据库、Profile callback |
| net | Runtime、DLI 标准／厂商方言、命令事务、连接与通道、流控、安全机制、可信状态 | 用户服务数据库和厂商私有库 |
| slkd | Managed 策略、授权、SSAP Engine、Agent、trust、Bond store、Profile | USB/HCC 直接操作、伪造内核安全状态 |
| 应用 | 业务协议和 UI；使用授权 fd 或服务 API | raw DLI、隐式全局 adapter、私有 transport |
| vendord | 独立厂商库进程、受控 Backend adapter | 加载进 slkd、绕过 Host 能力／生命周期校验 |
| 观察工具 | 独立订阅和诊断 | 抢占协议 RX、隐式修改硬件 |

### 采用的关键决策

| ID | 决策 | 原因／影响 |
|---|---|---|
| AD-01 | drivers / net / slkd 三层保持 | 机制、传输、策略分离，厂商差异不侵入普通应用 |
| AD-02 | ConnectionSession 独立于 fd | 关闭应用不应重建物理连接或 CMTC |
| AD-03 | Session 唯一 RX 分流，Channel 独立对象 | 防止多个 socket 抢信令和数据 |
| AD-04 | 基础不可靠消息目标使用连接式 DGRAM | socket 类型不制造可靠递送；可靠模式才开放 SEQPACKET |
| AD-05 | 内核可撤销 Grant + epoch | fd 委托不应永远绕过 owner 撤销和安全降级 |
| AD-06 | TxTicket 与明确提交线性化点 | 消除只在入口检查身份／授权的窗口 |
| AD-07 | command、controller data、peer 流控分别记账 | 不从 USB 成功或命令 credit 发明数据容量 |
| AD-08 | 不确定结果保留物理义务 | 不伪取消、不退款、不静默重试有副作用动作 |
| AD-09 | SSAP 唯一生产 Engine 在用户态 | 删除内核重复数据库／协议路径，易于服务和 Profile 演进 |
| AD-10 | 证明、开发测试、实机资格独立 | 明确假设，避免模型替代硬件 |
| AD-11 | core 不依赖 USB=y，driver 可注册 | 后续 transport、Virtual、Proxy 使用同一契约 |
| AD-12 | 未发布 UAPI 同步替换 | 不引入长期双实现和无意义兼容负担 |

AD-01–AD-12已采用并映射ADR0001/0002；不新建重复决定，目标实现状态以能力入口为准。


## 对象、身份与引用

### 对象树

```text
ControllerSlot（接入定位、跨重枚举恢复预算）
  └─ Runtime(generation)
       ├─ BackendRef / Descriptor / Host / CommandQueue / CreditLedger
       ├─ StateSubscriptions / SnoopSubscriptions
       └─ ConnectionSession(lifetime, handle)
            ├─ CMTC / 能力 / SecurityContext / 唯一 RX 分流
            └─ Channel(local_tcid, remote_tcid, mode, incarnation)
                 └─ SocketBinding(grant, authorization_epoch)
                      └─ VFS file 引用：原 fd、dup、传递后的 fd
```

| 对象 | 资源及失效规则 |
|---|---|
| ControllerSlot | 定位同端口，记录当前 USB incarnation、恢复次数、阶段和期限；不是密码学身份 |
| Runtime | 一次注册 generation；Host、credit、worker、事件、连接表；退休后旧回调不得修改新实例 |
| PeerObservation | 某 Runtime 的发现缓存；同地址也分 controller；不是认证或连接事实 |
| ConnectionSession | 一次物理连接 lifetime；信令、协商、通道表、安全和 RX 分流；独立于 Binding |
| Channel | TCID、PI、模式、MTU/MPS、协议队列及关闭事务；重建产生新的本地 incarnation |
| SocketBinding | 一个授权应用绑定；拥有软件准入、等待和文件清理；新 lease 不复活旧 Binding |
| KernelGrant | 权限范围和撤销代次；与 Managed lease 和连接安全关联 |
| Operation | 请求者、request id、参数、原 deadline、唯一终态、结果保留期限 |
| TxTicket | 不可变提交归属、授权、credit reservation、编码结果和提交阶段 |

### 身份规则

- Registry 编号仅定位，不承载完整生命周期身份。
- 使用 controller id + generation，连接增加 lifetime；内核引用还关联实际对象。
- Wire handle、local TCID、remote TCID、PI 分开类型和转换，禁止散落魔数。
- USB 地址、handle、TCID 可复用；重枚举不继承旧 Runtime。
- generation/lifetime 不得静默回绕；跨内核重启的持久化增加 boot 作用域或稳定身份，不能只用计数。
- 地址相同不等于可信 peer，controller 与 peer 组合不丢失作用域。
- 软件 incarnation、epoch、request id 不被自动带入 wire，不能用于假关联。
- 稳定设备配置使用管理员别名／已确认设备身份；端口用于定位，不用于密码学认证。

### 引用和销毁

file、worker、timer、URB callback、Backend module 各持明确引用。注销顺序为禁止新准入、逻辑失效、通知等待者、锁外 stop/drain、撤销注册、最后释放。注销返回后是否仍允许清理回调必须由接口契约明确；不得回调已释放对象。


## 正交生命周期与权威状态

### 状态分离

| 维度 | 状态示例 |
|---|---|
| Backend | Absent / Booting / Reenumerating / Online / Quiescing / Failed |
| Host | Uninitialized / Initializing / Setup / Ready / Fault |
| Managed | Free / Owned / Revoking |
| Radio | Unknown / Configured / Off / On，广播和扫描独立 |
| Connection | Connecting / Connected / Disconnecting / Dead |
| Channel | Negotiating / Open / Closing / Failed / Closed |
| Security | Unauthenticated / Authenticating / CredentialReady / Installing / EncryptedConfirmed |

Ready、Enabled、Available、Powered 不互相替代。Controller 元数据有效不自动表示 Host Ready，更不表示 Radio 已 Off。

### requested / pending / confirmed

所有有副作用操作分开请求、在途和设备确认值。真实匹配 Complete／领域事件更新 confirmed。拒绝、短写、超时、错误 opcode／generation 不提前提交状态或成功统计。

### 部分初始化清理

记录每一步成功来源、资源创建和无线事实；清理只针对已创建／已确认资源。未知广播实例不能盲目 disable。未确认 Off 不发布 Off。未知或清理失败进入隔离／恢复，不能因为本地释放 lease 就 Free。

Managed release、最后 fd、dup、在途回复、设备移除和 daemon crash 与这份初始化事实日志组合验收，保持活动 Ready 同行不变。


## Backend、固件与协议差异

### 注册接口目标

接口语义包括 register、start、submit、stop、recover、RX 和 fault。使用可引用 Backend handle，接口明确进程／原子上下文、错误、取消、回调次数、模块 pinning 和 drain 屏障。语言实现可采用小型版本化 C seam；不承诺稳定 Rust ABI。

### Descriptor

分别记录 bus、identity、dialect、capability、limit、quirk、firmware/board provenance、PM/recovery capability。支持三态 Supported / Unsupported / Unknown，每项附来源和 generation。

软件预算不是硬件限制；0 不自动表示无限或已知不支持。缺少可信发送上限／完成机制时不开放发送。

### WS73启动

```text
端点校验 → 镜像/板配置校验 → 下载 → 同端口新枚举确认
→ BSP_READY → customize → CUSTOMIZE_RECEIVED
→ SLE_OPEN → BOOT_FINISH → DLI真实查询
→ 按初始化事实确认Radio状态 → Ready
```

每阶段共享原始总期限，另有阶段预算、有限重试、完整长度和回复校验。启动通知应由正确接收窗口捕获，不能丢失后本地合成成功。

SDK111 qualification 绑定实际上传的镜像和配置 hash。暖态 version tuple 不证明刚刚上传111。combined 拼接、各段、校准、运行配置分别留来源。SHA 校验只证明内容完整性，不证明厂商签名、来源可信或板级校准。

### 标准、SDK、参考库及 OHOS

为每条事实维护标准版本/表格、SDK 调用约定、libws73-usb/OHOS 行为、本项目 bytes 和验证状态。0x0401 等冲突在 dialect 处理；标准路径保留独立测试。

私有 SDK 和逆向仅用于用户本地分析与独立实现，不公开固件、校准、私有库或不获许可的反汇编。参考代码复制／链接单独审查许可证；不把“协议参考”当作可直接搬运实现的许可。


## 数据与文件契约

Runtime→Session→Channel→Binding是目标TX/RX路径；Session唯一消费并分流CMTC及业务数据。
command credit、controller ACB credit、peer流控和软件包/字节预算分别记账。
软件准入、USB提交、NOCP及对端应用校验四阶段分开。

DLI PB、DTAP SAR、SSAP分片是不同层：每层记录长度/片数/字节预算/原期限，
按实际模式开放。当前实机上限为application249/DTAP254；仅应用250/253/254/255拒绝
已验证，其他分层边界和长包仍缺。EAGAIN保留游标，不确定已提交不从头重放。

完整Ticket/Grant、NOCP假设、socket语义、dup/关闭和同lifetime重开决策以
[ADR0002](decisions/0002-session-socket-lifetime-and-proof-contract.md)为准；验证与实机门禁
以IMPLEMENTATION_PLAN为准，避免在本文件维护另一套执行清单。
## 管理、事件与用户态

### 权威接口

管理API、数据socket、观察订阅、Diagnostic、BackendProxy分离。genl/ioctl等若保留多个前端，仅转发到同一内部权威状态和事务，不各自写状态。

UAPI采用固定宽度、对齐、version/length/flags/reserved和可验证上限。修改同步C、Rust、Python绑定、CLI、D-Bus和CI pin。ioctl结构大小影响编号；size字段不能修复旧编号静默变化。

configfs只承载明确配置，debugfs不当稳定生产API。raw Diagnostic需权限和冲突隔离；只读接口也不能公开密钥或敏感payload。

### 事件和快照

OperationResult归原请求者；StateEvent每订阅者独立游标；Snapshot以水位重同步；Snoop独立有界队列。sequence缺口可见，慢reader不阻塞Host。

复制失败不提交消费游标，短buffer不交付半记录。快照与后续sequence一致，避免 resync窗口漏事件。移除唤醒，终态结果保留与淘汰有明确预算。

### slkd运行模型

每Runtime/Session独立actor或串行协议执行上下文；D-Bus信号和耗时操作在锁外。同步fd避免阻塞Tokio工作线程，异步等待可取消。不存在active adapter全局协议状态交换。

重启时枚举、快照、确认旧owner撤销、新lease、订阅水位、重新应用策略。不能盲目重放连接／写属性等未知副作用；旧fd有效性由Grant决定。

### API和SDK

管理和服务经授权D-Bus/高层SDK，数据经授权fd。C/Rust/Python映射同一契约，不各自实现wire状态机。CLI显示请求、等待和实际状态；UNKNOWN/UNSUPPORTED/Fault明确呈现。


## SSAP、服务与Profile

唯一生产SSAP Engine归slkd；内核提供完整通道PDU、归属、安全上下文和实际模式能力，不保留双数据库。

Engine负责ExchangeInfo、MTU、扩展码、协商事务、SSAP分片、request-response、indication-ack、服务数据库、remote cache、handle分配、Profile路由。

没有协商事务号时按标准限定在途；不自行增加wire ID。原始事务deadline、标准规定的失败时限和分片timer分别遵守。notify/command不被无关等待无限阻塞。

ProfileRequest包含controller/generation/lifetime、attribute/op/offset/payload、security、request id、deadline。真正调用应用callback并经真实PDU返回，不用本地echo代替。

分别校验read、两种write、notify、indicate、认证、加密和授权。属性累积与offset使用checked计算和每事务/连接/全局预算，失败无假提交。

服务顺序：最小真实发现/读写 → notify → indication/ack → Battery和DeviceInfo → HID及其他Profile。必要可靠模式按所用标准接通；没有模式能力时只开放适用操作或明确不支持。Profile注册不等于服务互通。


## 安全、Bond、PHY和PM

### 安全职责

内核：协议时序、密码学、active credential、加密安装及强制安全。slkd：Agent、方法选择、用户确认、trust、持久化和撤销策略。

每连接安全状态只由真实协议与安装结果提交。无owner、拒绝、proof缺失/错误、超时、非法key、FFI失败或崩溃均fail closed。失败不提交密钥、计数或Encrypted。禁止测试密钥降级和固定nonce。

算法基于匹配标准与实际固件支持，不猜测；算法向量、协议证明和实机安装独立。

### Bond

保存可恢复的受保护凭据，fingerprint不是凭据。版本化、原子更新、0600或等价严格权限、密钥保护和敏感缓冲清理；明确KEK/保护机制的威胁边界，不把普通文件编码称为加密保护。

恢复核对controller身份、peer和安全上下文。撤销覆盖持久化、active credential、相关Grant及可选控制器token；opaque token仅在真实能力支持时使用。覆盖损坏store、重复记录、升级/回滚及撤销后重连。

### PHY

net校验真实capability、允许参数及适用约束，报告confirmed实际值。slkd执行Fixed/Balanced/Throughput/LowPower策略、hysteresis、minimum dwell、backoff和公平性。未知不自动切换，不能把requested当actual。

### PM

PM需覆盖system/runtime suspend、resume/reset-resume、未完成命令/数据/安全事务和热拔出。区分保留原Runtime可继续与必须新generation重建。不得resume后重新授予旧已撤销fd。仅在匹配控制器和固件资格成立后声明支持。


## 故障根因与每设备有限恢复

### 故障分类

| 类别 | 需要区分 |
|---|---|
| 初始化 | 镜像/板配置、ACK、通知窗口、方言、参数顺序 |
| 传输 | short、stall、timeout、URB取消、QEMU owner失效 |
| 枚举 | 同端口新地址、节点不存在、host地址分配失败 |
| 硬件 | 芯片状态、供电、电气、xHCI历史warning |
| 协议 | Host状态、迟到回复、credit不确定、连接复用 |
| 多设备 | 同时启动、RF参数、共享hub、同行错误传播 |

发现某一软件原因不代表所有自然故障同根因。保留冷/暖、单/双/四设备、QEMU与宿主诊断的对照；原生实验内核测试标为未授权/未执行。

### 恢复状态和预算

```text
Fault → CloseAdmission → Revoke/Quiesce → Stop/Drain
      → Backoff → VerifiedRecovery → FullInitialization → NewGenerationReady
      → BudgetExhausted/Absent/Failed
```

恢复Coordinator按ControllerSlot保留预算，跨boot/runtime probe不清零。每动作有最大次数、总deadline、适用条件和升级理由；稳定期归零依据明确。

### 恢复层级

依次考虑协议恢复、单endpoint/transport、已核验芯片reset、同端口重新枚举和完整固件启动。读失败、短读写和结果不确定不得盲目重写复位。未知寄存器访问不进入公共UAPI。

USB总线reset、芯片reset、hub断电分别记录。缺失设备没有handle时记Absent；不能复位另一只。ganged hub动作影响全部设备，不能授予单设备恢复资格。hub off/on不证明实际冷断电。

### 成功条件

新实例完成真实初始化/查询/必要无线状态确认，并由业务测试验证恢复后可用。同行的generation、lease、队列、credit及业务连续性保持；slkd PID/连接不变。

人工注入、QMP detach、人工拔插、冷断电、协议恢复分别保留标签。自然RCA与不依赖人工拔插恢复未闭合时不关闭K10/K14/K15/K19和相关跟踪。


## 开发、部署、观测与性能

### VM环境

宿主编译+单层headless QEMU即可；不需要以嵌套虚拟化作为开发前提。实验VM拥有私有内核、模块、固件、D-Bus、slkd、普通测试用户和工具；Bond测试用guest专属持久盘。

设备测试有独占锁，固定物理端口→guest端口→Runtime。不要默认共享宿主系统盘和全部USB控制器。udev仅对目标设备配置必要权限。

uhubctl权限可用于明确的实验对照；执行前停止相关VM owner、记录范围和前后inventory。共享hub切电不属于无扰单设备恢复，也不默认进入生产恢复策略。

### 包与服务

内核core/driver、用户态daemon/SDK/工具、实验功能、固件本地准备分别打包。显式配置错误不能静默回默认；未接通策略拒绝或明确实验状态。

slkd采用最小能力、受限文件路径及服务sandbox。privileged机制复杂度增长时再评估小型broker进程；不为当前纵向闭环无条件引入额外daemon。应用运行无需sudo，宿主安装/设备权限一次性管理员配置不等于应用需要root。

### 日志和指标

日志包含port/incarnation/controller/generation/lifetime/TCID/request/ticket、状态前后、阶段、原deadline、errno/raw status和恢复预算。秘密、长期key、未授权业务payload不默认进入journal。

指标分别计admitted/submitted/transport-completed/controller-completed/app-validated、队列字节、credit/debt、RX丢弃原因、reassembly失败、stale/duplicate、event loss和recover动作。

### 性能

测试软件准入、排队、transport、controller完成、应用RTT、吞吐、CPU/内存及延迟分位。容量和radio参数相同时再比较方案；无同条件Bluetooth基线不宣称领先。

先使用有界复制接口，测量后再决定零拷贝/mmap ring。优化不得删掉身份、预算和完成校验。


## 旧实现清理与14项整改

### 三类处理

| 类别 | 内容 | 删除／保留门禁 |
|---|---|---|
| 立即删除 | 固定nonce、test-key fallback、伪Complete、错误吞掉、提前成功状态 | 调用审计、失败无副作用、相关基线保持 |
| 移入测试 | codec/golden、故障注入、模型、callback actor生命周期 | 专用后端/selftests，不进入默认生产 |
| 等待替代 | 旧event ring、local SSAP staging、旧UAPI、总线enum/全局parser | 调用者迁移、同契约回归后删除 |

新旧生产状态不能长期双写或双消费。无调用者模块接通、隔离或删除，不用全局allow(dead_code)隐藏。原失败证据和有价值回归保留。

### 原14项对应工作

下表是历史发现→实施归属，不表示每项仍存在。先用新源码确认已修范围。

| 发现 | 内容 | 归入工作包/验收 |
|---|---|---|
| R01 | nonce、proof、测试密钥降级 | WP00/WP09；错误proof/旧连接/算法失败不可信 |
| R02 | crypto FFI错误吞掉 | WP00/WP09；实际包装错误传播，密钥/状态/计数不提交 |
| R03 | 重复TX与影子队列 | WP02/WP03/WP18；唯一TX、真实credit及完成阶段 |
| R04 | SSAP长度、累积与期限 | WP08；checked offset、总预算、断链和超时 |
| R05 | UART/SPI假Complete | WP00/WP13；明确unsupported，模拟移测试 |
| R06 | 配置静默降级 | WP00/WP16；显式缺失/权限/未知策略拒绝 |
| R07 | 权限位语义错误 | WP08/WP10；C/Rust/Python语义一致 |
| R08 | 通知出队/credit/归属 | WP08；保留未提交、实际确认、通知与指示分开 |
| R09 | PHY和加密提前状态 | WP09/WP15；requested/pending/confirmed |
| R10 | handle映射错误 | WP02/WP03；归属统一，无默认0偷换 |
| R11 | serdev全局parser | WP13；每设备ctx、晚回调/移除隔离 |
| R12 | event copy消费错误 | WP12/WP18；完整copy后commit，独立订阅 |
| R13 | core/USB/Virtual耦合 | WP13/WP14；可注册Backend、真实Virtual、构建矩阵 |
| R14 | dead code、严格CI与错误完成声明 | WP00/WP16/WP17/WP18；真实verdict与能力入口 |


## 风险、假设与开放问题

| 风险 | 应对 | 关闭条件 |
|---|---|---|
| NOCP缺完整身份/重复 | 保留debt、复用屏障、模型反例、显式硬件假设 | SDK111实际语义和可执行防护验证；不能只靠账本证明 |
| 同lifetime重开残留包 | Session持续状态、旧RX排空、拒绝未支持reopen | 可信屏障与双端实际旧包隔离 |
| 撤销到submit窗口 | Ticket/Grant/driver门禁同一线性化契约 | 模型+VM交错+源码映射 |
| 长包/PB能力未知 | 分层实验，保持短包基线，失败明确 | 全payload往返和真实credit段数 |
| 标准SAR/方言歧义 | 版面、参考和独立capture核对 | 差异矩阵与对应golden/实机 |
| 自然启动/消失/xHCI | 时间线、冷暖/设备数量对照、有限恢复 | 可复现根因与非人工隔离恢复 |
| shared hub供电 | 不把ganged动作算单设备恢复 | 拓扑与电源能力确证；单设备恢复资格 |
| native对照不可执行 | 保持VM-only，宿主只读诊断 | 用户未来授权后另行资格；当前不宣称 |
| 私有SDK/固件许可 | 本地使用、事实独立实现、无未经授权分发 | 来源与许可审查 |
| 模型与代码漂移 | 同批hash、映射、CI变更触发 | 准确源码报告和回归 |
| 地址族/ABI未发布 | 实验明确、协调、同步迁移 | 类型语义及正式分配/发布决定 |

当前整改实现切片：K464d4d8a9de7以opaque Runtime/Backend保留票据，在驱动准备URB后
重新验证lifetime/撤销/credit并原子提交；非阻塞提交是明确的Host-lock临界区例外，
等待/cancel/join在锁外。完整Session/Channel/Grant refs、NOCP屏障和Backend组合仍按
ADR0002/IMPLEMENTATION_PLAN推进。无消费者RustNetlink副本已移除，实际C bridge保留。

Runtime Session迁移切片K3c8da4fac302/Ud1f9dde：Runtime table持session kref，Session唯一
接收/CMTC，Channel有界独立队列，fd仅Binding。close撤销先赢则不能新USB提交，
同life无协议前明确拒绝重开；Runtime退休在native_lifecycle之前join Session。
准确40/249业务与dup/last-close子门禁通过，不授予动态通道、完整Grant/NOCP/恢复资格。

Managed lease epoch切片K3ee1a60bf06f/U2a97786：Host持pure authority；Session保留不可变
lease token。Managed发布/撤销、软件TX准入和实际USB提交同Host锁排序；已提交债务不退款。
socket v2同步broker，未支持方向/安全组合明确拒绝。新真实正常业务保持资格通过；完整
KernelGrant scope/security/blocked RX/VFS与受控撤销矩阵继续按WP05，不宣称整体架构完成。

RX切片Kf1034577ecc1/Ud570819：取包/PEEK引用在Host授权及Session/RX锁下线性化，
每次唤醒重新验证；copy/wait在锁外，已准入copy可完成。新40/249路径保持验收通过，
受控阻塞recv/release/last-management-fd/dup/owner-death及完整Grant仍按WP05继续。

Binding Grant切片Kbf8663/Udfb8636：Scope/方向/安全要求唯一存fd Binding，Channel借用其
持有socket的同一Grant；真正发布在Host门禁下，所有Binding锁IRQ-save。新40/249及
六撤销/两个方向资格通过；S5信任与降级、SCM_RIGHTS/daemon死亡/在途/Backend事件迁移
保持完整原计划，不能宣布全架构完成。
