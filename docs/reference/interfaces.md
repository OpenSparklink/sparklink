# 接口与能力的查找入口

| 接口 | 权威来源 | 使用边界 |
|---|---|---|
| 内核 UAPI／socket | 匹配的 Linux `include/uapi/linux/sparklink*.h`，及 Rust `slk-protocol` | 尚未发布，按当前调用路径核对 |
| D-Bus | `crates/slkd/src/dbus_iface.rs` 及相关对象模块 | 观察、管理与授权分开；对象绑定当前设备生命周期 |
| C应用 API | `crates/libsparklink/include/sparklink.h` | 当前 broker 查询/通道申请及已授权 fd 操作；无 Native 管理导出，非完整 SSAP/Agent 客户端 |
| C Native API | `crates/slk-native/include/sparklink_native.h` | 显式管理/观察库；匹配libslk_native，不授予访问权限 |
| Python | `bindings/python/sparklink/` 与 ABI 检查 | 与文档构建的 Python 项目分开 |
| CLI | 当前构建的 `slctl --help`、`slktest --help`、`slkconfig --help` | slctl管理/应用授权，slktest应用通道测试，slkconfig显式Native；已退休入口不保留旧别名 |
| 应用发现租约 | [DiscoverySession参考](application-discovery.md) | Rust／D-Bus／slctl已接线；独立caller预算/过滤/释放，非管理扫描；新实机与system bus权限资格仍缺 |
| 当前资格 | [CURRENT_CAPABILITIES](../../project/current-capabilities.md) | 区分源码、离线、模型、实机与未决条件 |
| 目标设计 | [ARCHITECTURE](../../project/architecture.md) 与 ADR | 不代表接口已接通 |

可选 UserHost 目前属于低优先级延期规划。旧 SSAP 业务入口的移除，也不意味着
新的用户态 SSAP Engine 已完整实现。错误和 NotSupported 行为以当前源码及资格为准。


## 已退休的 daemon 电源与历史元数据接口

`org.sparklink.Adapter.Powered` 已删除（getter/setter 均无替代别名），
`slctl show` 使用 `ControllerState` / `Generation` 等实际观察。Ready 不是物理上电证明；
当前没有电源控制契约，不能用 daemon 布尔值制造电源状态。
`Security.ListBonded` / `RemoveBond`、`slctl bonded` 和 `slkd --storage` 已删除。
默认及实验 daemon 均不读取、改写、删除或升级旧配对元数据；旧文件由管理员保留，
不作为真实密钥、可信身份、重连或撤销依据。历史存储仅用于单元测试的取消/退出回归。
未来真实 Bond 需独立的密钥安装、持久化、撤销及恢复门禁，不能恢复上述门面冒充实现。
实际 Agent、Connection 安全机制、唯一用户态 SSAP Engine、管理 staging 与 Owned
服务注册保持原职责。本段描述源码整改，实机资格仍按能力入口的准确 artifact。

## 应用、Native与共享契约

Rust `libsparklink::Client` 只通过实际slkd申请通道；保持调用者总线连接，绑定daemon
唯一owner和controller generation/connection lifetime。注册列表只表达成员观察，不是Ready；
选择连接及每次准入只重新核对自己的Generation，不查询同行属性作为前置条件。`open_channel`与动态staging
复用已有方法，接收fd检查实际AF_SPARKLINK；失败不降级，不暴露管理lease。
`slk-contract`是独立的值类型/路径/方法名契约；slkd直接依赖Native、Channel和契约，不依赖SDK。
SSAP审批的`SsapAuthorizationIdentity`和`SsapAuthorizationPrompt`也只由该层定义；
`slk-protocol`不再导出这两个D-Bus类型。未发布的审批元组末尾增加原始`data_type:y`，
当前只准入属性值0；旧的无类型元组明确拒绝。该字段不授予描述符访问或安全资格。
Rust Client提供成员/连接观察、fd申请与下述已有远端SSAP方法的类型化封装；
通用Operation/跨进程原始Deadline/EventStream尚未开放，future取消不承诺撤销已开始的物理义务。
内核/daemon/工具既有原期限、最后关闭和Grant规则继续执行。slktest移用SDK申请fd，负载、计时和验收断言仍在工具，业务不逐包过D-Bus。

daemon的Native通道创建在阻塞线程执行，实际工作持有同一管理准入guard直至
系统调用返回；取消等待不能提前释放它。排队工作及实际返回分别检查同一个owner
退休标志，退休后拒绝并关闭尚未发布的fd。SSAP初始化仍检查原期限，不通过取消
冒充已中止内核调用。它不改变D-Bus签名、Grant或socket完成语义，也不提供独立
进程故障域；准确实机范围仍以[资格入口](../../project/current-capabilities.md)为准。

Rust的目录观察由`Client::controller_events(Deadline)`提供，实际`slctl controller-events`
复用该接口。它只观察原daemon的Runtime adapter目录；C／Python经同一Rust stream
提供同步观察视图，新增入口的实机资格另验。
Gap、原期限、owner退出及与Native事件的区别见[事件契约](controller-events.md)。
这不表示应用发现租约、完整通用EventStream或新artifact实机资格已经完成。

### C/Python 同步应用入口

`slk_client_open_system` 创建一个调用者 bus 连接，固定当前 daemon unique owner；
`slk_client_controllers` 只列注册身份，不表示 Ready。`SlkControllerId` 的 generation、
index 和保留字节由绑定传递，不能代替权限。`slk_client_open_channel` 接收该身份及
已有的完整 Connection 对象路径，经同一 Rust `Client::connection/open_channel`
重新核对 generation/lifetime，再由同一 Channel 检查真实 socket domain。
当前提供固定应用通道申请和下述连接级远端SSAP读／短写封装；不新增管理租约、
动态通道便利封装、Agent或服务注册接口，也不从地址或 handle 猜一个对象路径。

| 调用/参数 | 当前契约 |
|---|---|
| `open_system(deadline_ns, output)` | 成功输出一个 opaque `SlkClient*`，失败不改输出 |
| `controllers(client, buffer, capacity, count, deadline_ns)` | capacity=0 查询数量；上限256。ENOBUFS 时只更新所需 count，不截断或改 buffer；其余错误输出不变。两次调用之间 registry 可变 |
| `open_channel(client, controller, path, path_length, directions, minimum, deadline_ns, output)` | path 是1..256个 UTF-8 字节，不含 NUL，不要求尾零；reserved 必须全零。TX=1/RX=2/双向=3，minimum=0..2。成功输出独立拥有的 fd，失败输出不变 |
| `close(client)` | 释放一次，NULL 可接受；调用者须排除并发调用/close。派生Connection仍持有原caller，最后引用释放才停止并join同一执行器；不关闭已交付fd、不强制断链 |
| `deadline_ns` | 原始绝对 `CLOCK_MONOTONIC` 纳秒，未来且至多30秒；覆盖本地排队与等待，不重置。到期 ETIMEDOUT，不保证取消远端操作，不自动重试 |

每个 C caller有一个本地执行线程，Client及派生Connection/ControllerEvents共享至多8个排队请求及1个执行请求；队满 EAGAIN。
它只桥接同步语言与现有异步 Client，owner 观察在调用间继续执行，不保存协议、
授权或连接状态。不在调用线程嵌套 Tokio runtime，不使用全局执行器。内核的
当前SDK链接的Tokio 1.51.0/full副本首次建立IO运行时会保留signal socketpair；
本批C/Python进程观察为2个固定fd，详见[原反例与来源](../evidence/application-client-runtime-resource-counterexample-20261018.json)。
不随每个Client退出销毁。每caller线程和其余运行时资源仍须最后释放收敛；不能把
该固定依赖成本当成每次增长的豁免。它不保存controller、授权或协议状态。
Grant/credit/Ticket、原期限及物理义务不由该队列改变。返回 fd 仅表示实际 fd
交付，不表示协商完成、安全安装、USB 提交或对端收到。

C 返回0或负 errno；Invalid→EINVAL、旧身份/丢失 owner→ESTALE、权限→EACCES、
NotSupported→EOPNOTSUPP、UnknownObject→ENOENT、缺服务→ENOTCONN，其他未分类
broker 错误→EIO；实际 Channel 系统调用 errno 保留。没有本地模拟成功或弱要求降级。
失去 daemon 后须显式创建新客户端；旧 scope 不随相同进程重新取得名称而复活。
超时后的远端执行结果可能不确定；晚到未交付 fd 在本地销毁，不据此退款或宣布
远端清理。当前同 lifetime 重绑限制仍有效，不能盲目重试。

Python `sparklink.Client(deadline_ns=...)`、`controllers(deadline_ns=...)` 和
`open_channel(ControllerId, connection_path, deadline_ns=..., directions=3, minimum=0)`
调用上述 C ABI，不自行拼 D-Bus。`controllers` 返回 immutable 身份 tuple，
`open_channel` 返回标准 `socket.socket`，由应用独立关闭/dup/传递。
固定通道以显式 family=46、SOCK_DGRAM、protocol=0 包装真实 fd；内核尚无 getname
操作，不能依赖 Python 的 fd 地址自动探测，也不承诺 getsockname/getpeername。
连接身份从固定 Connection 和内核 channel_info 核对，不从 socket 地址猜测。
当前 Python 运行库也不能为该未发布 family 计算 recvmsg/recvfrom/sendto 等地址
缓冲区；需要接收上下文时调用现有 `channel_recv_security(fd, ...)`，使用同一
Channel 的真实系统调用及截断/身份验证。它不是另一条业务通路，也不以缺失的
地址信息代替实际连接身份。普通无地址 send/recv、poll、dup、关闭按各自契约使用。
推荐 `with Client(...) as client`；方法与 close 串行，复用同一原始期限。
关闭不终结通道 fd；管理 lease 撤销/daemon 死亡的影响仍按内核契约。
客户端不能跨 fork 使用；fork 子进程先 exec，或用 spawn 创建进程后新建客户端。
仅 fd 的 fork/SCM_RIGHTS 保持内核 Binding 语义。进程边界在锁之前检查，不尝试 join
不存在的继承线程。输入指针须遵守 C 的有效区域/独占/生命周期契约；无效指针是
调用者 UB，和内核 EFAULT 测试分开。

### C/Python连接级远端SSAP读／短写

`slk_client_connection(client, controller, path, path_length, deadline_ns, output)`
创建opaque `SlkConnection`，沿用同一Rust `Client::connection`核对并固定原daemon、
generation、physical lifetime、handle和peer身份。它只是观察／调用视图，不拥有
物理连接或管理lease；关闭Client后仍保持原caller，`slk_connection_close`释放该
视图，最后本地引用关闭才join原执行器。不会自动断链、注销服务或撤销其他fd。
不支持fork后使用／关闭该对象，先exec／spawn再创建新Client。

`slk_connection_ssap_read`与`slk_connection_ssap_write`复用现有Rust `RemoteSsap`
的实际方法及返回字节，经slkd唯一Engine；绑定不解释另一个wire协议、不保存远端
缓存或事务、不echo写入、不自动重试／降级。minimum为0..2，非零handle为u16。
读写前后都沿用原身份检查，旧对象不因重连、handle复用或daemon更换复活。

输出参数为`buffer, capacity, length`，capacity必须1..65535。成功完整复制原返回
字节；`ENOBUFS`只更新所需length，buffer不变，**远端操作已经执行，不能把它当作
可安全重试的size query**。其他失败二者不变。超出65535的回复为EOVERFLOW。
write输入允许空值，长度超65535为EMSGSIZE；这个语言内存上限不是协商MTU或长写
支持，实际大小／安全要求继续由daemon及通道拒绝，不截断输入。
权限继续按实际system bus策略逐方法拒绝；`sparklink-apps`开放只读
`Connection.GetInfo` 预检与既有 `OpenChannel`／`OpenChannelScoped`／
`PrepareDynamicChannel`，以及已有原期限约束的 `ReadSsapValue`、`WriteSsapValue`、
`ReceiveSsapUpdate` 和下方四个持续接收方法。原身份、远端权限与机制事实仍由唯一
Engine 校验；组成员不是 Native Grant 或服务所有者。管理权未开放。`DiscoverSsap`、
`GetCachedSsap`、`ReadSsapByUuid`、`GetSsapInfo` 尚未通过本批原期限／调用者审计，
继续只由管理角色调用；不能宣称完整 SSAP 客户端权限迁移完成。
新规则的实际 system bus／应用组实机资格须单独取得，不继承管理组历史门禁。
C调用者须提供真实有效、独占、无别名且满足声明长度的内存区域；坏指针属于FFI
调用者契约，不能用来代替内核EFAULT门禁。

Python `Client.connection(ControllerId, full_connection_path, deadline_ns=...)`
返回可显式close或用`with`的`Connection`；`connection.ssap().read(handle, ...)`
和`.write(handle, bytes_like, ...)`使用同一C ABI并返回相同字节。每次只执行一次，
不按错误长度自动重试。关闭Connection后已有SSAP视图失效；不关闭物理连接。

**SSAP值读／短写**的原期限已传到现有daemon Query；e776产物只有分项正向与
原路径保持资格，受控期限、退出、部分初始化及晚到义务仍须单列验收。Rust方法显式接收`libsparklink::Deadline`，C/Python仍接收绝对
`CLOCK_MONOTONIC`纳秒。既有五秒协议上限在SDK操作入口确定，C/Python在进入
本地队列前确定；原期限更短时不延长。身份检查、总线排队、锁和协商等待共享该期限。
其余Client管理、发现／订阅等入口的完整端到端期限仍未由本批接通或验收。

D-Bus值方法新增末尾`(ttttt)`：到期纳秒、boot UUID高64位／低64位（各按UUID
字节的大端顺序解释）、time namespace设备号／inode。五个固定uint64避免可变
长度分配；无旧shape兼容。固定版本zbus对错误签名在dispatch前返回
`org.freedesktop.zbus.Error`及Signature mismatch；已解码的无效字段为InvalidArgs，
时钟域不一致为NotSupported，原期限结束为Timeout。要求可信procfs、相同boot和
当前time namespace；内核发送还要求进程／线程同域且monotonic/boottime偏移均零。
不支持或读取失败时明确拒绝，不能猜测时钟或从收到RPC时重新起算。

应用等待、发送准入和物理清理分开。未准入的过期／关闭请求从既有队列移除；可能
已准入者保留原请求与安全身份，等待匹配回复或有限清理期限。晚到回复不能完成
已超时的作者；清理期限不允许新业务提交，也不退款。无可归属回复时仍需退休该
协议通道；不承诺固件无重复／晚到行为已经证明。

共享SSAP初始化归Connection owner，只有一个存储的任务；请求超时不丢弃其
Native操作。初始化与ExchangeInfo共用独立的原五秒期限，不在fd返回后重启计时；
退休先拒绝新starter，join实际初始化再停止Engine。初始化完成不代表协议Ready；
Ready仍取决于真实协商。Native操作未返回时保留引用等待清理，不宣称Free或已
证明所有驱动路径的墙钟上界。超时、取消本地等待或写后输出失败均不撤销已发生的
远端副作用。协议结果也不等于对端应用已经处理业务。新入口的[17b4限定实机报告](../evidence/application-connection-ssap-clients-real-20261018.json)
单列管理组普通UID的32字节SSAP协议结果与对端本地反查，不继承旧CLI或basic资格。
它不授予apps-only权限，也不等于Owned／ServiceAuthorizer或独立应用语义ACK验收。
完整高阶发现、Owned 回调、Agent及通用API仍待整改，不能由这些方法推导已支持。

这些是当前源码接口，不把私有 bus 的拒绝/错误 fd 回归升级成实际部署权限或
WS73 正向交付资格。准确产物与未完成的高阶客户端见唯一能力入口。

### 控制器观察与显式管理

`Client::controller(path)`返回固定daemon owner及index/generation的`Controller`观察对象，
不是Ready或Native lease。属性不缓存；成员列举不读取同行属性作为本设备准入条件。
`registrations()`／`registration(path)`直接读取Core生命周期，Pending/Fault观察不要求
Ready Adapter存在。`peer_info()`及Connection采用共享的完整身份规则，不猜地址类型；foreign Peer路径在查询其他controller之前拒绝。

`controller.management()`只是显式请求管理的客户端视图。构造它不授予权限，每次仍经
实际D-Bus策略及内核检查。广播/扫描控制、取消、连接分配/提交/结果、强制断链均使用
现有typed方法；关闭自己的应用通道与全controller管理不混为一个操作。管理者按地址
断开时解析当前无歧义peer；要固定旧lifetime使用明确reference/object操作。

SDK在实际调用前后检查owner/generation，并校验结果中原请求身份。owner变化后旧
对象失败，需要显式创建新Client；不自动追随新daemon。已发生的提交不能因该错误
撤销或退款，原请求结果可能仍有物理义务；失败不是“确定未提交”。观察仅在检查点
有效，不承诺下一刻硬件状态。原协议期限不重置，CLI连接结果等待也覆盖身份RPC。

`slctl`管理/注册/Peer/Connection观察已迁移这些方法。旧地址Device/dev路径及devices/info已退休；本地
服务/Agent调用使用同一个Client scope；当前不提供generic Proxy或Native逃生口。
新方法源码和私有D-Bus检查不是完整新实机资格，范围以能力入口的准确artifact为准。

### 本地登记与安全回调客户端

`Controller.management().local_services()`是管理staging；`Controller.local_services()`
是应用Owned登记，分别保留原broker权限。`register_service(..., Deadline)`返回不可Clone的
`ServiceRegistration`，`receipt()`是本地登记回执，`read_local()`只查询该登记的属性，
`unregister()`显式撤销。它不表示远端服务发布，Drop不启动脱离调用者的异步RPC。
应用authorizer对象必须在创建Client的同一bus connection上导出；属性权限沿用既有类型。
Owned 的 register/read_local/unregister 显式接收原 Deadline；三条 D-Bus 请求携带
同一五字段 stamp。初次登记期限不充当服务 TTL。超时不表示已经发生的远端效果被
回滚，原 owner 定向清理与本地对象释放分开；完整规则见[SSAP 权限](ssap-permissions.md)。

C/Python 的基础 Owned 视图复用同一个 Rust `ServiceRegistration`：
`slk_client_register_local_service`／`Client.register_local_service`，随后通过
`slk_local_service_receipt/read/unregister/free`／`LocalService.receipt/read_local/unregister/close`
访问。支持有界初值及显式 `authorization=requests` 审批；没有审批入口时授权位与
更新能力明确拒绝。管理 staging 与安全 Agent 仍是独立用途。
回执不是远端发布；跨语言生命周期、错误和布局见[SSAP 权限](ssap-permissions.md)。
实机范围始终绑定准确编译 artifact，不从新增 API 名字推导资格。

`Controller.register_agent(path,method)`返回带daemon实际epoch的`AgentRegistration`。
旧epoch不能撤销同caller/path的新登记。`ApplicationConnection.allocate_reference_security()`
返回原作者的`SecurityRequest`；begin/observation/cancel仅封装现有broker流程，不另建安全
Engine或轮询器。批准、native准入、机制安装和对端业务收到分别表达，不能由注册推导。

Client在owner lookup前订阅名称变化；即使同一unique owner释放/重新取得服务名，旧scope
也永久失效。clone/派生对象共享一个有界终态通知。新准入和观察拒绝失效scope；已知回执的
unregister/cancel仍只定向原unique owner和原generation/请求身份，不跟随替换daemon。
这是本地观察契约，不替代内核Grant epoch或证明bus到USB提交原子化。

取消登记future或丢失回复可能使结果不确定；不得自动重试或假设回滚。已知回执可显式
撤销；未知回执需结束原caller bus owner，由broker原有owner退出清理收敛。Drop一个
view不等于退出该bus连接。CLI继续在前台处理原期限、人工输入与有限callback队列，
不隐式断开物理连接或退还credit。源码迁移、私有bus测试和真实artifact资格分别记录。

### Rust远端SSAP客户端与slctl

`Client::connection(controller_path, connection_path)`固定daemon unique owner、controller
index/generation和物理lifetime/handle/role/地址类型/地址。`connection.ssap()`借用该对象，
每次实际调用前后重新核对当前身份；旧对象不会追随替换daemon、重连或复用的handle。
这里只做观察检查，最终授权和发送仍由内核执行，不是跨D-Bus/内核原子事务证明。

| Rust客户端方法 | 现有daemon方法／结果 | 限制 |
|---|---|---|
| `discover(uuid, kind)` | `DiscoverSsap`，条目及实际事务trace | 仅daemon当前支持的种类；不创建客户端缓存 |
| `cached()` | `GetCachedSsap` | 该lifetime的建议性缓存，不能授予可用性/安全 |
| `read(handle, minimum)` | `ReadSsapValue` | 原机制要求；错误原样传播，无弱化fallback |
| `write(handle, value, minimum)` | `WriteSsapValue` | 原短写协议；不截断、不echo、不实现新长写 |
| `read_by_uuid(start, end, data_type, uuid, minimum)` | `ReadSsapByUuid` | 返回每项结果及原trace；不是本地构造成功 |
| `receive_update(handles, modes, wait_ms)` / `receive_until(..., Deadline)` | `ReceiveSsapUpdate` | 单次CPCD启用/接收/验证停用；需真实认证及拥有者授权；不覆盖已有配置 |
| `subscribe(handles, modes, duration_ms, Deadline)` | `SubscribeSsapUpdates` | 持有原 caller／lifetime 的有限接收租约；读取、续租与关闭复用同一 Engine，当前一 actor 一个租约 |
| `send_owned_update(handle, indication, Deadline)` | `SendOwnedSsapUpdate` | 同一原caller拥有的本地属性；stage1软件准入，stage2对端接收队列ACK，均非应用处理 |
| `owned_configuration(handle, Deadline)` | `GetOwnedSsapConfiguration` | 观察原caller属性在本Session的配置，不制造Ready、授权或新配置 |
| `exchange_info()` | `GetSsapInfo` | 真实协商观察，核对返回完整身份；不是服务发现或安全资格 |
| `connection.transport_status()` | `GetTransportStatus` | 只读现有Session，不能排空credit或证明复用屏障 |

相应slctl远端命令通过这一客户端调用，CLI仅解析参数和显示结果；唯一wire Engine、
事务/分片及服务数据库仍在slkd。共享wire元组由slk-contract提供，daemon直接消费契约，
不反向依赖应用SDK。Native管理、其他CLI控制入口、本地Owned/Agent及C/Python便利
客户端的完整收敛仍按唯一计划R5推进，不能据本表认定整架构完成。

本表描述源码入口。私有D-Bus/参数/错误/旧身份/独立签名检查不是WS73实机资格；
新artifact必须另外VM回归。服务端仍执行既有有限队列和原期限，SDK不重试或刷新期限；
当前客户端future结束不发送物理撤销，已经发生的远端写入可能不能回滚。

`slk-channel::Channel`持有一个fd引用，构造只检查实际domain，**不是Ready或交付**。
`try_clone`共享同一内核binding，`into_owned_fd`明确转移所有权；关闭仍服从内核最后
引用/Grant/credit/Ticket契约。已有操作层保留query与约束SCM收发，完整高级异步接口
仍按实际实现开放。

Python默认导出当前 Client/ControllerId、访问要求和授权fd操作；旧`Adapter`及默认`NativeAdapter`导出已删除。
Native需显式`from sparklink.native import NativeAdapter`并加载`libslk_native.so.0`；应用
fd操作用`libsparklink.so.0`。Python使用运行库major，不要求开发包的无版本链接。
`LIBSPARKLINK_PATH`与`LIBSLK_NATIVE_PATH`指定准确产物，
错误覆盖路径直接失败，不静默回退。两库C头/符号分别检查。**C/Python尚无完整broker、
远端SSAP或回调客户端**；不得从新库名称推导已实现所有目标API。Native旧不支持入口
仍按R4全链清单退休，不以移动文件表示整改全部完成。

基础绑定在准确668的干净Debian VM中已通过安装后的外部C/Native及Python wheel
消费，包括移除开发链接后加载两库major；这里只验证已实现纯导出和错误路径。
system bus角色分离也已在该VM实际核对，但无controller的允许调用到达UnknownObject
只证明总线准入，不证明OpenChannel、Kernel Grant或实际设备操作。
完整范围见[独立部署记录](../evidence/deployment-clean-vm-qualification-20261018.json)；
软件包升级回滚、当前新artifact实机及高阶语言客户端仍分别待验。


## 本批源码核对的状态（未发布 ABI）

本页描述WP18/R4当前入口与拒绝契约；新源码尚未取得的资格不继承任何历史镜像。实际实机范围只按能力入口的编译产物与门禁核对。

| 范围 | 当前状态与限制 | 源码定位 |
|---|---|---|
| Native 管理／诊断 | 版本化请求，controller generation／所有权检查；已实现标准 Diagnostic，限查询；准确新实机范围见资格页 | `slk-native/src/ioctl.rs`、内核 `sparklink_core.rs` |
| Native WS73 发现／连接／通道 | 已接通路径；实机资格仅限能力页所列准确提交及场景 | `slkd/src/connection.rs`／`controller.rs`、`slk-native` API、内核 socket |
| D-Bus ServiceManager／RemoteService | RegisterLocalService/ListLocalServices/RemoveLocalService/ReadLocalValue 是本地数据库操作；Owned 三入口保留；旧 facade 方法与 RemoteService 已删除；真实远端操作走 Connection 唯一 SSAP actor | `slkd/src/service.rs` |
| 旧 SSAP ioctl | 业务命令已删除，旧编号 ENOTTY，不提供兼容 fallback；权限类型继续复用 | `slk-native/src/ioctl.rs`、内核 UAPI |
| 旧 property／write facade | 未发布入口与调用者已删除，历史 248/252 限制仅保留在原资格/纯测试；当前协商与长写限制单独表达 | 原 git／codec 回归 |
| Profile／transport 实验 | 独立 `slk-experimental`；不构成默认生产能力 | 实验 crate README、构建 feature |
| UserHost／厂商 Host 适配 | P4 规划，接口／实现／证明／实机均未完成 | ADR 0003 |
| 新用户态 SSAP Engine | 唯一用户态actor的ExchangeInfo、单值读写、UUID/结构发现已接线；发送通知/指示、CCC与长写仍缺；准确资格仅能力入口 | 唯一实施计划 WP08、准确能力入口 |

C 头、Rust FFI 和 Python 绑定应匹配准确源码，不能根据函数声明推导硬件支持。本表是状态查找参考，完整资格仍仅维护于能力入口；逐字段自动生成 API 及全错误矩阵尚待下一批。

旧0x82 DLI poll、Raw256类型、Rust Event/EventReceiver/poll/next_event、C slk_poll_event及Python旧Adapter.poll_event已删除，无兼容期。Python NativeAdapter.poll_event是现有非消费ControllerEvent路径，名称相似但契约不同；monitor的--legacy不再接受。详见当前资格与三类审计。

旧read(2)／44字节队列及0x70/0x71统计接口已删除。当前ControllerEventGet按每注册游标提供完整记录，失败copy不推进readiness；snoop保留独立权限。slctl events／D-Bus GetControllerEventPosition返回(index,generation,sequence)，来自实际LinkSnapshot.event_seq，不能解释为pending、delivered、ACK或完整resync屏障。

[Controller 事件字段、错误及删除入口](controller-events.md) 给出本批逐接口核对；完整 API 迁移仍未完成。

Netlink v2 核对 K `7c6d530ffe2e`／U `ffc0945dfdac`：仅注册数量和软件版本，
无 controller 控制或事件 multicast，请求多余属性返回 EINVAL。旧命令 EOPNOTSUPP。
它不报告 Ready、连接或固件能力；详见[实际迁移证据](../evidence/genl-retirement-progress-20261014.json)。

未发布 raw controller ABI 的101个旧连接、广播扫描、角色、PHY/AFH、PM、
安全/RPA、同步及注入入口已从生产声明、分类和分派退休，旧编码统一 `ENOTTY`，
在权限、选择和用户内存访问之前拒绝。旧编号不复用，也不保留兼容别名。
保留26个真实Typed Native、注册/每fd选择、观察和Diagnostic入口；不支持的**新模式**
仍按各自契约明确拒绝。`MGMT_STATS` 仅原有诊断账本，不是Native Ready或链路权威；
CLI统计使用实际LinkSnapshot。旧可写configfs参数不存在。

53个没有生产消费者的Rust raw布局只在私有 `cfg(test)` 模块保留；旧C/Rust/Python
布局、权限helper及回归均明确标为历史。它们不再要求从当前内核公开头获取退休类型。
跨语言检查分别验证当前ABI和历史见证，不能将两者合并为当前能力。
旧安全/隐私Rust/C/Python/CLI门面已删除，C不再提供这些导出函数；不是永久返回
`EOPNOTSUPP` 的兼容API。D-Bus Security只保留实际Agent登记/撤销；旧方法为
UnknownMethod，旧Encrypted/Paired属性为UnknownProperty。现行per-Connection机制
和内核安全事实保持原路径，持久Bond仍缺。新raw退休artifact的VM/真实WS73资格
须单独取得，不改变已封存历史记录。

### 显式 Agent 与 SDK111 限定流程

`org.sparklink.Security` 位于 `/org/sparklink/slk{index}_g{generation}/security`。
`RegisterAgent(o path, s method) → t epoch` 绑定该 controller 的一个 Agent 唯一总线所有者；
明确接受 `sdk111-no-mitm` 或 `sdk111-numeric-comparison`；未知方法不降级。`UnregisterAgent(o path, t epoch)` 核对原 caller/path/epoch 后撤销原注册，普通通道权限
不授予 controller 管理或 Agent 注册权。默认不自动批准。

上述字符串标识当前实现的具体机制配方，不能据其名称判断设备正在运行的固件版本
或兼容范围。选定镜像、实际上传、运行期 HCC 与真实协议交付分别留证；未知方法
仍明确拒绝，不自动选择另一机制。

`org.sparklink.Connection` 的原生命周期对象提供：

| 方法 | 输入 → 输出 | 成功的含义 |
|---|---|---|
| AllocateReferenceSecurity | `u timeout_ms` → `t request_id` | 分配原调用者专属请求；1–5000ms 原始期限从分配开始 |
| BeginReferenceSecurity | `t request_id, s method` → 无 | 开始异步策略流程；不是控制器成功 |
| GetReferenceSecurityResult | `t request_id` → 观察结构 | 策略终态和原生状态分别返回，不读取密钥 |
| CancelReferenceSecurity | `t request_id` → `b` | 请求撤销；不是硬件排空确认 |
| GetSecurityState | 无 → `(ttqtuuuyy)` | 当前内核机制快照；限定新镜像范围见下，不是授权或 Bond |

Agent 的 `org.sparklink.Agent.AuthorizeReferenceSecurity` 接收一个结构参数：
`(s connection_path, t request_id, t generation, t lifetime, q handle, y role,
y address_type, s address, s method, t deadline_monotonic_ns)`，返回 `b`。
原始期限为 CLOCK_MONOTONIC 纳秒，批准后不刷新；调用者、Agent 唯一总线连接、
注册 epoch 和完整连接引用共同约束请求。重复启动、撤销、原期限、替换 Agent、
旧身份和退出不能产生新成功。正式 `slctl agent [method]` 提供前台逐请求人工批准/拒绝，
`slctl security-request <connection-path> [timeout-ms] [method]` 在同一原作者连接内完成
分配、启动和查询；Ctrl-C 只尝试原请求取消。默认超时5000ms，范围1–5000ms。
这两个入口绑定原 daemon 唯一所有者，不自动跟随替换。见
[实验 VM 操作及退出契约](../how-to/request-reference-security.md)。新 CLI 的双模式限定实机范围仅见当前资格；
VM 专用 `native_security_agent_probe.rs` 是独立测试见证，不能安装为默认自动批准 Agent。

观察结构依次为 `t request_id, t generation, t lifetime, u phase, i error,
t deadline_monotonic_ns, b agent_approved, b native_admitted, u kernel_state,
i kernel_error, u kernel_flags, y kernel_status, i cleanup_error`。
`kernel_*` 是该请求监督器保留的最后原生观察，不是终态之后持续刷新的硬件状态。
取消终态不可被迟到回复改写，但这不表示已提交安装被回滚、物理密钥已擦除、
控制器当前未加密或物理 debt/回调已排空。`CancelReferenceSecurity` 返回 true 仅
确认取消请求已受理；需要实际原生取消观察后才能区分准入前和在途取消。
phase 1分配、2等Agent、3原生观察、4限定完成、5拒绝、6取消、7到期、8失败、
9调用者丢失、10Agent丢失；phase≥4为终态，不可据此一律判成功。
CLI成功要求phase4、error0、批准且准入、kernel_state9、kernel_error0、
flags含TX/真实Complete/peerRX三位、status0且cleanup_error0；这些仍不等于业务交付。

准确编译用户态 `85cdf627d70b`、内核 `8cbf53e6a088`、执行工具 `db6e333814cf`
已有批准、拒绝、超时、取消及两类总线 owner-loss 的限定双设备证据，入口见
[当前资格](../../project/current-capabilities.md)。owner-loss 用显式关闭总线连接，
并不覆盖 SIGKILL／进程死亡／fd 继承。批准只代表策略允许；真实 Complete、对端
relay RX、安装及未认证加密状态分别观察；不意味着身份认证、可信 Grant、Pair、
Bond、第三方互通或完整安全证明。未执行的新组合不能继承这些资格。

### 底层安全协商 ABI（未发布）

当前未发布接口以源码为准：`SL_IOCTL_SECURITY_NEGOTIATION_SUBMIT`（`0xd2`）为
**版本2、64字节**，携带原始`deadline_monotonic_ns`（CLOCK_MONOTONIC纳秒）。
`RESULT`（`0xd3`、72字节）和`CANCEL`（`0xd4`、32字节）仍为版本1。
旧56字节SUBMIT删除，不设兼容期；这些接口不能混用版本或布局。
C导出`slk_security_negotiation_submit/result/cancel`与Python NativeAdapter同步。
另有版本1、40字节的`SL_IOCTL_SECURITY_NUMERIC_CONFIRM`（`0xd5`），
C `slk_security_numeric_confirm`、Python `NativeAdapter.confirm_security_numeric`同步；
RESULT末尾4字节现为u32 `comparison_code`，总长仍72字节，UAPI未发布、不保留旧布局语义。
这是底层机制；显式 Agent 与 Connection 的 SDK111 限定流程已接线。旧 Pair／Encrypt门面已全链删除，无兼容期，不能用它启动新流程。实机范围见唯一当前资格入口。

原始绝对期限必须在策略/Agent等待前设置，不能在批准后刷新。`timeout_ms`为
1–5000ms剩余预算上界，实际期限仍是原始纳秒值；过期返回ETIMEDOUT，超过上界
返回EINVAL。Session的prepare/crypto/input/最终提交及查询使用同一单调时钟。
Host的jiffies仅安排清理，不延长准入；转换使用实际内核tick速率。CLOCK_MONOTONIC
不计系统挂起时间；完整PM取消/恢复仍待实现，不能据此承诺挂起期间继续安全过程。
当前新ABI/时钟改动不能继承旧56字节镜像资格。

- 必须显式选择`flags=1`（CAPABILITY_ONLY）、`2`（KEY_AGREEMENT_ONLY）、`3`（UNAUTHENTICATED_ENCRYPTION）或`4`（NUMERIC_COMPARISON），不能组合；
  由CAP_NET_ADMIN与原活跃Managed
  File调用；其他File或降权后的同一File返回EPERM。查询同样受保护，不开放原始RX或密钥。
- generation/lifetime/request_id非零，handle为12位；精确核对role/address/type/epoch。
  timeout为1–5000ms原始总期限。仅G action2发起134、T action1先批准并回应135。
  profile/角色组合不支持返回EOPNOTSUPP；无效字段/reserved返回EINVAL；失配连接
  返回ESTALE，错误generation返回ENODEV。同lifetime再次启动返回EBUSY。
- 模式1/2/3固定offer为`03 00 00 10 00 02 02 02 02 00`，不请求MITM、Bond、OOB或分发。
  只接受该已知offer，不承诺任意SDK/第三方配对互通或可信身份；模式1/2不执行安装/加密。
- result state：1批准待收、2进行中、3协商/确认/安装中、4能力观察完成、5失败、6撤销、7超时、8未认证候选
  proof完成、9控制器报告未认证加密开启；flags
  的1/2/4分别表示实际提交、真实成功Complete、对端能力RX。state4/8/9要求flags7。
  失败不产生trusted状态；撤权后查询也失去授权。该入口不是事件历史或可靠交付API。
- 同一物理Session/业务通道持续存在；探测后由管理者显式断链。应用fd析构不隐式
  完成安全协议。`Complete + RX`与业务应用校验/回复、配对、认证、加密、Bond分别表达。

准确资格及未证明范围见[唯一资格入口](../../project/current-capabilities.md)。

`flags=SECURITY_KEY_AGREEMENT_ONLY=2`（内核名带`SLE_`前缀）仅执行已知offer的
无入口/无MITM/无Bond候选协商，复用同一Session与原1–5000ms期限。
真实134/135后继续136/137、公钥确认/随机数及141/142 proof；state8表示内核验证
peer proof且本地relay实际Complete已排空，flags仍仅为提交/Complete/能力RX观察。
它不代表Agent已同意、远端身份认证、密钥安装、Encrypted或Bond；默认Pair/D-Bus
安全入口不因此开放。私钥/共享secret/LTK无读取或注入API。同lifetime仍拒绝重启。
C/Rust/Python的两种模式常量有实际编译契约检查；必须使用相应新库，旧库不能把
未知state8当作成功。普通业务Grant不授予协商批准权，完整身份和Managed授权检查不变。
历史K1cf/U02ac仅具有模式1；历史资格不自动升级为当前模式2。

Kc2dd941e5784：不存在全局active/default controller。DEV_SELECT非负绑定精确
registration，-1清此File及观察模式；dup/fork/fd传递共享File，拥有lease则EBUSY。
DEV_GET_ACTIVE仅报告本File绑定id（可已退休），无绑定为0xffff；它不报告Ready。
旧DEV_SWITCH、DLI_INFO、DLI_RESET明确拒绝。MGMT_STATS仅保留实际标准profile0
事务统计，Native profile1不支持；CLI query的准入由Diagnostic lease与Host负责，
不从旧queue数值推导静默。完整新源码实机资格见能力入口，未完成项保持开放。

K654216743b68：MEAS_READ_CAP/SET_LINK_PARAM/ACTION/ENABLE没有合格的Native
机制，明确EOPNOTSUPP（Protected入口普通无CAP先EPERM），SDK/D-Bus也拒绝。
configfs仅软件version；max_connections/adv_interval_ms/scan_window_ms/power_mode/
controller_type删除，旧路径ENOENT，不保留none/0无动作成功。SPARKLINK_SLE与
SPARKLINK_DEBUGFS无效选项删除；用实际SPARKLINK/驱动及Linux DEBUG_FS配置。
WS73实际板级pm_config.bin不是旧全局power_mode，仍由驱动加载验证。

K6fe9696a04da 的未发布 socket v2 地址大小仍48字节。底层CAP_NET_ADMIN bind
支持两固定key：local/remote TCID31与PI241，或local/remote TCID10与PI0；
CMTC不交应用fd。每槽仅一个绑定，最后关闭只退休该槽；同连接lifetime重绑
EOPNOTSUPP，无热迁移。默认slkd的普通应用OpenChannel仍只授CUTC，服务SMTC
保留给唯一Engine；当时尚未取得的SSAP资格以当前能力入口重新核对。
字段/模式不存在公开兼容承诺。

通道socket只读 `SPARKLINK_CHANNEL_INFO`（S/e0）：固定40字节、8对齐，
version1/size40，返回controller/handle/generation/lifetime、实际有效MTU/MPS、
local/remote TCID/PI/basic mode/directions，reserved0，无lease/security承诺。
未bound/关闭ENOTCONN，协商前EAGAIN，撤权/旧身份按Runtime拒绝，copy故障EFAULT
不改变通道或消费队列。快照仅在授权准入点一致，不保证返回后的连接存续。

K90fda145 修正独立预算：本实现公布 SDU MTU2042、完整 DTAP PDU MPS2047，
并分别与对端能力取较小值。CHANNEL_INFO 的 mtu 是按通道帧头收紧后的有效
SDU 上限，mps 是完整 PDU 上限；CUTC 帧头5字节、SMTC帧头4字节。
例如对端 MPS254 时 CUTC 至多249字节，SMTC至多250字节。发送超限
EMSGSIZE，接收完整 PDU 超限丢弃；ACB254字节分片/控制器 credit 是另一层限制。
本地20字节 CMTC 响应决定当前实现所需最小 MPS20，并非标准全局最小值。
该修复有离线及限定证明，准确新镜像的真实设备资格仍须另行核对；历史回复
成功不能自动取得修复后的 MPS 一致性资格。
C `slk_channel_info`错误不改输出；Python `native.channel_info(fd)`用于delegated
socket，不是NativeAdapter的控制fd。32位仅C布局已验，真实compat调用仍待验收。

### 每条接收消息的机制观察

未发布 UAPI 在 K8c302d7cfc49 起增加 `recvmsg` ancillary：`SOL_SPARKLINK=288`、
`SPARKLINK_SCM_RX_SECURITY=1`，结构 `sparklink_message_security` 固定40字节、
8对齐，native/compat布局一致（真实compat调用仍待验收）。version1/size40，包含
本地 controller、generation、connection lifetime、handle、local/remote TCID、PI、
原 ACB 接收关联的 security_epoch 和 Runtime Owner 观察等级0/1/2。没有lease、
命名身份、Bond或属性授权；也不是对实际RF加密的独立证明。

`KNOWN`(1) 表示路由时可将原接收epoch与唯一Owner机制观察关联；不能关联时
security=0、flags=0。`CURRENT`(2) 在已授权 dequeue/PEEK 的线性化点重新核对
同epoch和足够机制；排队后的换钥不会提升旧消息等级。返回后可能再次失效，
因此这些事实不能授予后续TX权限；属性策略仍需要响应最终提交约束。

每个成功完整数据报（含零长及PEEK）带一条记录，原有无control的 `recv()` 可忽略。
control缓冲不足产生 `MSG_CTRUNC`；缺失/截断不是安全事实。Rust
`message_security::recv`、C `slk_channel_recv_security`、Python
`native.channel_recv_security` 拒绝缺失/畸形/截断上下文，不降级成假元数据。
Rust返回 `(syscall_count, context, msg_flags)`；C返回字节数或负errno，通过两个
输出参数返回上下文和flags；Python返回 `(copied_bytes, context, flags, count)`。
输入支持DONTWAIT/PEEK/TRUNC，TRUNC完整计数可能大于缓冲，不能据此越界索引。
fd必须在同步调用期间稳定持有；FFI指针须有效、独占且不别名。失败不更新C输出
对象，但payload可能已经复制/消费，不能声称回滚。非SparkLink fd明确拒绝。

K1bcd766d07bb新增唯一发送ancillary `SPARKLINK_SCM_TX_CONSTRAINT=2`，
结构 `sparklink_send_constraint` 固定48字节、8对齐：version1/size48、minimum0..2、
generation/lifetime/security_epoch、controller/handle/local/remote TCID/PI、reserved0、
`deadline_monotonic_ns`。期限是一次确定的CLOCK_MONOTONIC绝对值，首次准入时最多
剩余5秒；不能因等待/重试续期。它只收紧原fd Grant，minimum0也必须匹配原非零epoch，
不能降低原Grant最低机制/范围，不能用RX记录当授权或发出RX类型的control。

原始准入及每次实际USB提交（含PB后续分片）复核原epoch、机制、期限和原
Grant/Ticket；等待及Session排队清理由同一绝对期限收紧，最终提交不等定时器才拒绝。无前缀的异步失效仅退休本Channel并通过错误/
poll显露；已有前缀不伪装取消成功，不退款或抹去物理debt。机制/身份不符EACCES，
原期限已过ETIMEDOUT，非法版本/size/保留位/超过5秒范围EINVAL；未知level/type
EOPNOTSUPP，多记录/错误长度EINVAL。没有control仍按原fd Grant发送。

Rust `SleSendConstraint::from_receipt`拒绝unknown/non-current或机制不足的原接收，
`message_security::deadline_at`一次转换原Instant，`message_security::send`执行真实
受约束sendmsg；C `slk_channel_send_constrained`及Python
`native.channel_send_constrained`不作普通send降级。返回值只代表软件准入，异步提交
仍可能因撤权/换epoch/期限失败，不能据此宣称对端处理。32位仅布局测试，实际compat
调用仍待验。未知control继续明确拒绝；FFI输入必须有效，不能用坏用户地址模拟库指针。

唯一SSAP Engine开始严格读取实际RX上下文，响应/错误/指示ACK保留原epoch、原响应
期限与原观察机制下限至实际TX。主动ExchangeInfo/客户端请求仍使用原通道Grant，
逐属性策略/本地授权及主动请求细粒度intent尚缺；不能描述为完整属性安全。AF_UNIX
actor回归仅显式test-only Wire，生产没有模拟上下文或域降级。响应被撤权/期限拒绝
不回滚已发生的本地数据库写入；请求方超时不能推断对端没有应用，需实际读回或
上层业务序号确认，不能把异常改写成“未执行”。准确编译及限定门禁见
[当前资格](../../project/current-capabilities.md)，旧K8c接收资格不转授此新发送路径。

ServiceManager新增明确本地 RegisterLocalService/ListLocalServices/ReadLocalValue/RemoveLocalService；
Connection新增ReadSsapValue/WriteSsapValue经真实SMTC，写要求peer校验回复。
Connection 只读属性 `SsapSecurityRequirement`（D-Bus `u`）返回首次 SMTC 绑定前
固定的最低机制要求 `0|1|2`；它不是当前安全等级。启动配置、延迟启动、拒绝及
无降级/重绑行为见[SSAP权限与通道要求](ssap-permissions.md)。不改变本地 staging
与实际远端操作的区分，也不授属性级认证、本地授权或 Bond。

已退休的旧facade不再提供。数据库配置不是远端发布；原始门禁及安全/失败
语义见准确资格和证据，不转授为完整服务支持。

唯一 SSAP actor 因错误退出时，daemon 记录一次 `SSAP lifetime actor failed`，带
controller、generation、lifetime、handle、I/O kind、原始 errno（若有）及错误文本。
日志不含协议载荷或密钥，也不改变退出、撤权或原期限。调用者看到的
`actor stopped during ...` 可能只是待回复 oneshot 已关闭；定位根因须关联同一
lifetime 的终态记录和真实通道／USB证据，不能把日志或状态更新当作成功交付。

历史U8438594收紧本地注册：当时仅READ/WRITE_WITH_RSP（mask0x05）接通，
WRITE_NO_RSP、descriptor、notify/indicate等声明明确NotSupported；共享权限类型
仍保留标准完整语义。此拒绝只有生产数据库/实际D-Bus离线门禁，不转授Ub5实机资格。

Connection新增DiscoverSsap(uuid,kind)/GetCachedSsap，按实际SMTC响应产生元数据，
未知缓存失败；无参UUID+primary模式取得primary/property建议缓存，完整服务
数据库快照、方法/事件/引用生命周期与ServiceChanged一致性尚无承诺。
普通服务从handle16分配，保留旧流量证据但不转授旧范围为标准合格。

### ReadByUUID：有限完整PDU模式

U514cf733aab4新增Connection.ReadSsapByUuid(start:u16,end:u16,data_type:u8,uuid:ay,minimum:u32)，
返回逐条(handle,success,error,value)与原始请求/响应。普通用户CLI为
`slctl --adapter PATH ssap-read-uuid CONNECTION START END UUID_HEX [MINIMUM]`；数据类型为0。
UUID须2/16字节，范围非零且start≤end；无效本地参数为InvalidArgs，退休lifetime
或actor/队列失败为Failed。远端条目错误保留在每条结果，不描述成读成功。

服务器最多64个属性，复用现有READ权限；多条失败/成功混合列表按句柄有序。
完整响应超过协商MTU时按标准不支持分包规则发READ_RSP错误16，客户端明确失败；
无分片、无部分成功列表或截断。原事务期限5秒，关闭/退休不能发布旧结果。
原始trace用于证据，USB提交和NOCP均不代表对端应用收到。
实机只验每端一个custom property，其他类别与错误矩阵仍待扩大；
[源码映射和精确范围](../evidence/ssap-read-uuid-progress-20261014.json)。

<a id="单次客户端配置与更新事务新源码接线实机待验收"></a>

### 单次客户端配置与更新事务（实验接口）

Connection.ReceiveSsapUpdate(handles:aq,modes:y,deadline:(ttttt))返回单个结构`(bay)`
（indication:b、raw:ay），不是两个D-Bus返回参数。
1..32个唯一非零handle、modes1通知/2指示/3两者、绝对期限最多10秒；InvalidArgs拒绝
非法参数。准入使用本lifetime完整层级发现更新的建议性缓存；过滤发现的结果不替换
该缓存。必须有其中实际发现的property及匹配Notify/Indicate能力，缺少时
NotSupported。只允许一个call-owned等待者；busy、原期限、caller退出、Actor失败
或断链为Failed，不静默成功。CLI为`ssap-receive CONNECTION HANDLE [notify|indicate|both] [WAIT_MS]`。

同一actor依次读取CPCD，只有旧配置为零才启用，收到一包后验证停用再返回；读取、
启用与业务等待共用原绝对期限。取消或超时不抹去可能已生效的配置，清理有单独固定
5秒上限；无法确认时该SSAP actor失败，不能重开同lifetime伪装Free。不会清除已有
非零配置。一个call拥有客户端事务序列，其他竞争调用明确busy；尚无持续多应用聚合。

清理收到匹配原写请求和handle的类型化 `WriteError(4)` 时，该属性被明确报告为
不可用：当前接收仍返回失败，内部收到的值不会作为成功结果交付，也不宣称CPCD已
验证为零。该请求的失败回复已到达，其他handle仍按同一清理期限处理；独立业务
不因这个已知失败自动退休。未知失败、超时、错误handle及仅有相同字样的错误字符串
不适用这一分支，仍须保守退休。它不更改Native授权、安全等级或credit。

完整property packet进入有界内部槽；IND的ACK1只表示该接收准入，不代表调用者
处理、最终RPC返回或业务回复。未知、已知关闭、过期、不匹配或事件ACK0；NTF无回复。
旧ObserveSsapIncoming/ssap-observe入口已退休，无兼容别名；历史记录保留原命令身份。
多条同handle实例、事件投递及未协商序号的长报文仍不支持；已协商的单值序号
分片范围见[片段边界](../explanation/ssap-value-fragments.md)。malformed packet失败SSAP actor。
正向更新、传输及机制的限定资格按准确产物读取；不能继承旧本地观察的结果，
也不能把有限正向范围当作完整安全或生命周期资格。
受保护SMTC的初始化保留原错误类型；只有已完成且未返回fd的确定安全准入拒绝，
才能在真实安全完成事件后join并重新尝试。新bind仍由内核核对原租约及实际机制；
未知失败、超时、已启动Engine与退休owner不重开。原拒绝的公开错误名称/正文保持。
接口存在不授予资格，须核对当前能力入口中准确产物的限定记录；持续订阅、多应用和
完整生命周期仍有独立门禁。不得通过基本回退、第二Engine或同lifetime重绑绕过。


### 持续 SSAP 接收租约（开发中，未发布）

以下是同一 Connection／SSAP actor 的源码接线，不是新 Host 或 wire Engine。
Rust／C／Python／CLI 已复用同一客户端。系统总线策略以逐方法 allowlist 向
`sparklink-apps` 开放这四个原期限／原 caller 绑定的方法；实际权限与新的持续更新
实机门禁单独记录，源码、无副作用的错误预检或私有总线 fixture 不构成实机资格。
加入管理组的历史调用不能作为普通应用权限分离已完成的证明。
单次 `ReceiveSsapUpdate` 的原语义保留。当前源码允许一个物理 actor 的同属性集合、
同模式共享组最多8个租约；全daemon原watch预算仍16。只有已经实际启用且仍有有效
拥有者的组可以共享，controller／generation／lifetime／安全epoch必须一致。
不同属性集合或模式、初始化／清理中、无有效拥有者及容量已满明确拒绝；不覆盖旧
CPCD。这是分批实现范围，不能据此宣称动态过滤／模式合并或完整多应用资格。
同一集合的句柄顺序可以不同，各调用者保留自己的原顺序和token。

| 方法 | 输入 | 结果及限制 |
| --- | --- | --- |
| `SubscribeSsapUpdates` | `handles:aq, modes:y, duration_ms:u, deadline:(ttttt)` | 1..32 个实际发现的唯一 property；租期 250..60000 ms，创建原期限最多 5 秒；返回原 controller／generation／lifetime／安全 epoch、token、到期及状态 |
| `ReadSsapUpdates` | `token:t, wait:b, deadline:(ttttt)` | 一个在途 reader，原期限最多 10 秒；返回有限批次、序号及累计丢弃／拒绝计数；重新检查实际 Native 上下文及原 epoch |
| `RenewSsapSubscription` | `token:t, duration_ms:u, deadline:(ttttt)` | 原 caller 且仍 Active 才能续租；不会续订创建、读取、在途包或首次清理期限 |
| `CloseSsapSubscription` | `token:t, deadline:(ttttt)` | 仅关闭自己的 token；撤回自己的路由／配置引用；REMOTE_RETAINED区分共享保留与最后远端停用，不隐式断链 |

未发布接口的结构布局／大小保持，新增flags语义要求daemon和Rust／C／Python同步部署；
旧客户端遇到未知位应拒绝，不做静默降级。接口已接线与实机／形式化通过分别按
当前能力入口中的准确产物记录；原单租约历史资格不转授新的共享行为。

租约到期是本地单调时钟观察，独立于最多5秒的 Native 发送期限。创建和续租共用
250..60000ms 的过期计算；长租约不放宽每次实际发送、创建、读取或清理的原期限，
也不是长期发送授权。后续变更必须分别回归长租约和超过5秒 TX 仍被拒绝的负对照。

每个租约独立队列最多16个完整PDU／32768字节；一个队列满不阻塞其他接收者。
各队列独立记录通知丢弃／指示未准入。线上指示ACK1只表示至少一个匹配且有效的
队列接受了完整包，不保证每个订阅者接收，更不表示任何应用处理；全部拒绝才ACK0。
需要业务交付时，每个目标应用必须独立校验和回复。返回包带原 Native 安全收据及
递增序号；取消读取不释放租约，远端回复是否已被消费可能不确定，不能自动重试或
凭 RPC 超时补造交付。取消后实际未被本地 oneshot 接受的批次才允许原样放回队列。

原D-Bus unique owner退出或租约到期只清理自己的token及队列；丢弃排队包并报告数量。
仍有有效共享者时，关闭结果为CLOSED／flags=3：bit0 CLEANUP_CONFIRMED表示该租约的
路由／配置引用已撤回，bit1 REMOTE_RETAINED表示完成当时仍有兄弟租约保有远端CPCD。
这不是远端停用成功事件，也不承诺该观察之后的硬件状态。最后一个租约才发送实际
停用并等待验证回复，成功flags=1；bit1单独出现非法。首次物理清理最多5秒，
未知结果失败／隔离同一actor，不报告Free。每租约至多8个关闭等待者；actor仅保留
最后16个owner／token终态观察，淘汰后旧token不可用且绝不会重获权限。等待更新时让出原客户端请求
通道供普通读写使用，配置／清理仍通过同一请求序列。它是有限 D-Bus 租约，不提供
应用 socket 的 dup、SCM_RIGHTS 或最终 fd 释放承诺；不授 controller 管理权限。

Rust 通过 `connection.ssap().subscribe(handles, modes, duration_ms, Deadline)` 获取
`ssap::subscription::Subscription`，调用 `read(wait, Deadline)`、
`renew(duration_ms, Deadline)`、`close(Deadline)`。它保留原 caller，释放父 Connection
视图不会断链或结束此租约。`info()` 是最后验证的观察；`is_closed()` 仅表示本地读取／
续租准入已结束，不是远端清理证明。Drop 仅在已有 Tokio runtime 中尝试撤回，不能替代
显式清理；未知续租结果不自动重试，也不能刷新原读取、包或首次清理期限。

| 语言入口 | 结果与所有权 |
| --- | --- |
| C `slk_connection_ssap_subscribe` | 非零原句柄列表、modes1..3、租期250..60000ms；输出独占 `SlkSsapSubscription*`，父 Client／Connection 可先释放 |
| C `slk_ssap_subscription_info/read/renew/release/free` | Info为120字节；Packet为2072字节；完整Batch为33312字节，最多16包；read无peek／长度查询或截断。release观察远端清理，free只释放本地；错误保留输出，当前并发操作返回EAGAIN |
| Python `connection.ssap().subscribe(...)` | `read(deadline_ns=..., wait=True)`、`renew(duration_ms, deadline_ns=...)`、`release(deadline_ns=...)`；`close()`／context退出仅本地释放。禁止fork后使用；不另建D-Bus客户端或SSAP codec |

C 输出须为完整、独占、正确对齐的结构区域；无效地址属于调用者违反 FFI 契约，不等同于
内核坏用户地址测试。未使用的数组／保留字节归零。Rust 统一检查原身份、epoch、递增序号、
计数及包预算，复用现有 Update decoder；Python 只检查 ABI 表示并转换不可变值。
已被远端消费、但本地等待结束的批次可能不确定；不会偷偷重读或称为无损投递。

`slctl ssap-subscribe CONNECTION HANDLE [notify|indicate|both] [COUNT] [LEASE_MS]`
是有限交互命令：默认至少8个完整PDU、60000ms租期，无自动续租；COUNT1..4096，
LEASE_MS250..60000。完整批次可能超过COUNT，全部显示，不截断。先实际发现所需属性，
每次读取原期限最多5秒；到期／中断／错误后仍尝试同一token清理。未收到目标数量或
清理未确认时失败，不能把日志或协议ACK当作对端应用校验回复。日常交互不替代 slktest。

## Delegated channel TX status（未发布 v1）

源码契约：K `49467d4df595`／U `d74421c210ee`，不由接口存在推导实机资格。
`SPARKLINK_CHANNEL_TX_STATUS` 为只读 ioctl，固定64字节，native／compat布局一致。
Rust `query_tx_status(fd)`、C `slk_channel_tx_status` 与Python
`native.channel_tx_status(fd)`复用同一结构；不消费RX、不申请credit、不提交USB。

| 字段 | 含义与范围 |
|---|---|
| version／size | 1／64；未知或畸形返回值由SDK拒绝 |
| controller／generation／lifetime／handle | 该fd当前精确身份；不是可复用的裸handle资格 |
| packet_maximum／capacity | 当前Runtime已知的控制器ACB包长及包数上限；不是应用MTU |
| outstanding／connection_debt | 控制器全池保留债务／该物理连接债务；连接债务包含其各逻辑通道 |
| peak_reserved／pool_exhaustions | generation内饱和峰值／实际池满拒绝数；峰值包含明确未提交后回滚的reservation，不等于USB接受数 |
| queued／queue_limit／busy | 本逻辑通道软件排队／8项预算／在途项0或1；queued+busy不超过8 |
| active_pdu_bytes／active_pdu_offset／flags | 仅本通道的Session在途PDU；ACTIVE=1、BEGUN=2，offset为已提交前缀，不表示对端处理 |
| reserved | 0 |

Runtime依次持有Host／data／gate锁，回调再取得Session锁，以同一快照核对授权、
身份、协商及预算；游标修改也由Session锁保护。用户copy在解锁后进行，成功快照
不保证未来连通性。管理撤权／断链可随即发生，快照不能替代实际提交时的票据检查。
不返回lease、载荷或另一通道的在途长度。

未知ioctl为ENOTTY，未绑定／已退休不具备有效连接，协商未完成EAGAIN，授权失效
由Runtime及Binding拒绝，用户copy失败EFAULT；Runtime未知／fault不能生成有效预算。
具体错误优先级随精确入口核对；C／Python保留实际errno。EFAULT重试不改变credit
或队列；C输出对象在失败时保留原值。

POLLOUT只表达软件准入；software EAGAIN不是packet-credit耗尽。峰值小于capacity且
pool_exhaustions为0时不得宣称真实池满。NOCP归还不等于对端协议接收或应用处理。
实机资格仅见[唯一当前能力](../../project/current-capabilities.md)；同generation单调计数
也不能证明晚到／重复NOCP准确归属或handle复用屏障。

### 未认证安装接线（新实现，实机资格待验）

K `f5c79a50467b`新增显式管理模式3，仍要求原Managed File/CAP_NET_ADMIN和完整
身份。复用原Session、credit、原期限与最终票据：G真实1c03（21字节），T仅在真实
000e后1c05（20字节）。命令接受与0011分别记账；state9只表示同一lifetime的实际
初次加密事件和原命令接受，不能表示Agent、身份认证、可信Grant、Paired或Bond。
后续真实关闭/失败/更新事件会使原观察失效，迟到开启不能复活。默认Pair继续拒绝。

Host队列不保存密钥。驱动临时帧在最终提交前通过保留票据填入已验证Session材料，
真正提交仍重新核对撤权/Down/期限；USB join后清除临时及TX缓冲。SDK111的两种
安装命令在snoop中置`SNOOP_REDACTED=2`，保留原长度、只捕获真实头部；不可将省略
参数当作零长度USB包或全零密钥。USB原始抓包含秘密，保持私有，公开证据不输出LTK。
本节描述接线，不授予新镜像资格；当前准确实机范围仍见唯一资格入口。

## 数字比较机制（开发中，未发布 ABI）

`flags=4` 在同一物理Session使用明确offer `01 00 04 10 00 02 02 02 02 00`：
显示/是非确认、MITM请求、无OOB、无Bond。只接受精确匹配，不能降级为无入口模式。
协议为134/135、136/137、T的13C（confirm16+Rb16）、G的139（Ra16），然后等待确认。
C crypto依赖复用SDK111字节序适配器，依据公开公钥与两端随机数计算六位比较码；
不得将两端恰好相同的数值当作用户已核对身份。

RESULT flags8表示当前有效提示，`comparison_code`范围0–999999，000000有效。
提示只在state3、原期限内有效。原CAP_NET_ADMIN、原Managed File通过40字节CONFIRM
提交generation/lifetime/request_id/version=1/code/handle/accept与5字节零reserved；
accept=0拒绝，1同意。错误code/已确认返回ESTALE，错误作者请求ENOENT，其他File
或降权调用EPERM；字段/reserved错误EINVAL，不支持版本EOPNOTSUPP。原期限超时
ETIMEDOUT，已经关闭ECANCELED；调用不创建Session、不刷新期限、不提供密钥/proof。

flags16仅表示本地明确确认；此后才准入DH proof。T可在自身确认前保存一份属于本
Session的真实G proof，确认后再验证并回应，重复/旧lifetime不混入新过程。flags32仅
表示实际peer proof验证；state11/flags119还要求真实安装接受、对应0011加密开启和
自身relay Complete排空。数字比较码在确认、拒绝、撤销、到期后清除；返回Native操作
结果不代表daemon身份、可信Grant或Bond，已开始的物理义务仍按现有票据清理。

内核机制已有单独准确镜像资格；新broker/Agent接线的准确实机范围另记于当前能力页。
`RegisterAgent(path,method)`新增明确方法`sdk111-numeric-comparison`，默认方法仍为
`sdk111-no-mitm`。Allocate冻结Agent唯一owner/epoch/方法；Begin必须精确匹配，不能
更换Agent或降级。原来的Allocate/Begin/Result/Cancel和13字段Observation不另造副本。

数字方法首先调用`AuthorizeReferenceSecurity(prompt)`允许开始交换；内核出现有效
flags8提示后，才调用`ConfirmNumericComparison(prompt,code:u32)`。prompt沿用原有
完整Connection路径、request_id、generation/lifetime/handle/role/address/type、明确方法
及原deadline。前置批准不是数字确认；确认true才经同一原Managed File提交实际CONFIRM，
false提交明确拒绝。未知callback、Agent/作者失联、取消和到期均走原请求清理；已开始
的ioctl必须join，不能通过丢弃任务抹去物理义务。kernel_state/flags才表示原生观察，
Observation.agent_approved仅表示前置批准；kernel_state11/flags119还不授予可信Grant。

CLI入口为`agent [method]`、`security-request <path> [ms] [method]`，省略method行为不变。
数字Agent分两次询问：先`approve <id>`允许交换，再展示真实六位码并要求
`confirm <id> <六位码>`或`reject <id>`；000000有效，`approve`不能代替数字确认，预输入
不沿用到下一提示。两个提示共享最初1–5000ms期限，不刷新。5秒也包含前置人工等待，
当前并非通用人机配对体验；更适合人类的期限策略仍须单独设计和验证。
Pair/全局GetPasskey门面已删除；命名可信身份/Bond仍未支持；固定CUTC机制要求及当前事实另见下文。
旧镜像资格不继承本批；形式化状态/锁/引用/硬件假设与真实两端交付分别记录。

## 单个安全作者请求取消（未发布 ABI）

匹配内核的 `SL_IOCTL_SECURITY_NEGOTIATION_CANCEL` 使用32字节
`sle_security_negotiation_cancel`：generation、lifetime、request_id为u64，version为u32，
handle和reserved为u16；version=1、reserved=0、12位handle。Rust、生成C头和Python
布局同步。现有 Connection broker 和正式 CLI 复用这一个取消机制；新 CLI 实机范围待验收，准确历史范围见当前资格入口。

原Managed File和CAP_NET_ADMIN均必需；普通业务fd不能调用，也不能从observer File
借用管理权限。取消校验原File/request与当前连接身份，不创建新Session；不释放controller
租约、不主动断开物理连接或清理其他通道，停止待提交作者工作。返回0是本地取消准入/处理成功，
不是wire取消、Complete、credit退款、已断链或已关闭加密；已提交物理义务继续保留。
终态请求幂等返回且不改写原结果，尤其state9不会被伪装成Off。原期限已过时保留到期
终态；通过原RESULT入口观察操作结果，取消不自动增加同lifetime重启资格。

无效字段/reserved返回EINVAL，版本不支持EOPNOTSUPP，错误generation返回ENODEV，
失配物理lifetime返回ESTALE；非原Managed File/无CAP返回EPERM，无原请求返回ENOENT。
撤权、设备移除及注册退休按原权限/生命周期错误返回；不要把失败当作物理过程已撤回。

## 客户端配置与 SSAP 更新的当前限制

单次CPCD事务及Owned发送的资格只由当前能力入口中的准确artifact记录授权，不能
继承历史属性读写或旧本地观察PASS。表40要求CPCD写认证和授权；no-mitm/Agent同意不满足。
配置由唯一物理actor按lifetime持有，拥有者退休或安全epoch变化使旧配置失效。
本地替换不自动通知。SendOwnedSsapUpdate只发送原caller当前拥有的属性快照，仍受
协商能力、CPCD、原期限及每次Native提交检查约束；没有序号分片协商时，超出线上
MTU明确拒绝。协商后仍限定单值2042字节，通知/指示逻辑PDU最多2048，不能截断。

一次最多一个待决指示，关闭/取消后仍等待匹配ACK或有限退休；ACK没有wire事务号，
重复/晚到ACK和可靠传输假设仍须独立验证，不宣称解决了所有复用竞争。C/Python的
未发布的SlkSsapUpdate改为2064字节，PDU数组2048字节，ACK偏移2056，显式保留5字节。
必须同步重编C调用者与共享库、更新Python绑定；不与旧2056字节布局混用，无兼容期。
stage1仅在全部片软件准入后返回，stage2还需真实匹配ACK，stage3为收到且已验证停用；
它们都不表示对端应用处理。首片启动一次原排空期限，部分流撤回不能忘记物理义务。
完整持续订阅、provider及多应用/故障矩阵继续开放；分片机制见
[原理解释](../explanation/ssap-value-fragments.md)，新artifact资格不由历史更新记录授予。

客户端值请求的部分 SSAP 片准入，与单个通道 PDU 的 ACB 前缀是不同阶段。
回复只有在原请求全部片软件准入、原排空期限尚未到达且安全上下文匹配时，
才能结清该请求。作者取消不能让部分请求获得成功，也不能抹去已准入流；后续片
仍受原发送期限约束，首片排空期限不续期。完整流的晚回复可以结清原义务，
但不能给已经退出或到期的作者补成功。无法确认部分流时，保守退休原 actor。
本地 socket 背压测试不验证 Native 准入、USB、credit 或空口；其结果不能升级为
真实 WS73 部分 SSAP 准入资格。

## 动态基础通道：已接线，实机待验收

Linux `400bd6812608` 的未发布 sockaddr v3 长64字节，保留原48字节 v2固定通道。
受管理 lease 约束的 daemon 使用 bind 暂存被动端点，或使用非阻塞 connect 发起
真实 CMTC（返回 EINPROGRESS）。`Connection.PrepareDynamicChannel` 接收单一
D-Bus struct `(qqqqqyb)`：source_port、destination_port、AID、MTU、MPS、
preferred SLQI、passive，并返回一个仍可能协商中的 fd；返回 fd 不是远端建立成功。
ports/AID必须非零，MTU1..2042、MPS不超过2047且至少MTU+5；首版仅basic、
未保护安全等级，不承诺preferred SLQI已配置硬件QoS。

CLI使用 `dynamic-peer <connection-path> <source-port> <destination-port> <aid>
[rounds] [bytes] [hold]`，主动端改用 `dynamic-roundtrip`。它们复用已有随机业务校验
与socket收发逻辑。`hold`供受控测试在双端校验后协调最终fd关闭；不是线上ACK。

只有实际协商完成及Runtime身份重新验证后，ChannelInfo才返回local/remote TCID
和Grant；此前INFO为EAGAIN，poll不返回可写。动态单播TCID为0x80..0xdf、PI241..250；
双方TCID可以不同，不能用handle或本地TCID代替对端TCID。四个动态槽位分别有
有限队列，唯一Session worker消费ACB并按本地TCID/PI分流。暂不在同一物理lifetime
重用已用槽位/TCID；耗尽ENOSPC，重用屏障仍待实现验证。

最后fd关闭撤销本应用准入并发起真实关闭；已开始物理PDU仍归Session。对端逻辑
关闭后允许排空此前已完整排队的RX，禁止新业务准入和迟到成功复活Grant。
资源拒绝、取消、原期限、撤权/断链与同行隔离分别验收；本段说明生产接线，
不把离线函数夹具、有界证明或USB提交升级为真实动态多通道资格。


## Session 发送观测（未发布 v1）

`SPARKLINK_SESSION_TX_STATUS`（E2）是当前已授权通道 fd 的只读 ioctl，固定
64 字节，native/compat 布局一致。Rust `query_session_tx_status`、C
`slk_session_tx_status`、Python `native.session_tx_status` 使用相同结构。
它不创建通道、申请 credit、启动 SSAP 或提交 USB；不输出 lease 或业务载荷。

返回原 controller/generation/lifetime/handle、controller capacity/outstanding、
connection debt、全 Session 的 queued/active PDU，以及 dynamic
open/pending/retired/failed/allocated 计数。当前动态槽预算为 4；计数和为 allocated。
flags 分别为 WORK_RUNNING=1、WORK_QUEUED=2、BASE_PENDING=4、STATE_UNKNOWN=8。
failed 不等于成功关闭，必须根据本次实际创建和拒绝的通道核对期望终态。

Runtime 按 Host/data/gate → Session → 单个 TX queue 的锁序检查身份、授权和预算。
worker 通过同一 Session 锁发布私有 pending 字段；运行中不读取这些字段，返回
WORK_RUNNING。队列合计是保守的瞬时观察，不能推导未来空闲、callback/引用排空、
固件 NOCP 准确性、Free 或 handle 安全复用。成功 copy 后仍可立即撤权或断链。
错误语义沿用通道只读检查：未连接/已退休、未协商、撤权和坏地址均明确失败。

`org.sparklink.Connection.GetTransportStatus` 经已有的唯一 SMTC actor 读取该快照。
没有该 owner 时返回 NotSupported，不隐式启动 Engine；退休或身份变化返回 Failed。
包括等待 state lock、actor 排队及回复在内，共享调用起点的 1 秒原始期限。CLI 为
`slctl --adapter ADAPTER_PATH transport-status CONNECTION_PATH`。
结构存在不代表新镜像已通过实机门禁；资格以项目记录中的准确 artifact 为准。

本批 ABI 检查在 LP64 下执行 C/Rust/Python 对照；ILP32 仅比较生成 C 头与内核头的
编译布局。32 位运行和 compat 系统调用仍待 VM 验收，不由布局检查升级为通过。


### 当前连接安全快照（机制实机范围与 Grant 分别验收）

`org.sparklink.Connection.GetSecurityState()`返回单一结构，依次为generation、
lifetime、handle、security_epoch、profile、level、flags、method、key_size。
使用slkd原Managed File查询唯一物理Session；调用不创建Session、启动配对或读取密钥。
整个只读调用有1秒原始预算；退役/未知连接或管理不可用返回Failed，旧内核ENOTTY/
EOPNOTSUPP映射NotSupported，不从缓存的Agent操作结果拼出正向状态。

对应未发布内核`SL_IOCTL_CONNECTION_SECURITY`（d6、48字节）、Rust
`Adapter::native_connection_security`、C `slk_connection_security`及Python
`NativeAdapter.connection_security(generation,lifetime,handle)`。原生查询仍要求
CAP_NET_ADMIN及活动Managed File；普通用户不由此获得控制器权限。
输入version1、精确非零generation/lifetime和handle≤0xfff，其余字段零。
失败不改写C输出；Rust/Python拒绝身份、epoch或事实组合不一致的内核输出。

| level | flags | method / key_size | 含义 |
|---|---|---|---|
| 0 | 0 | 0 / 0 | 未取得当前正向机制事实；不能假定可用或可信 |
| 1 | 13 | 3 / 16 | 本Session proof、安装接受和0011；无MITM机制 |
| 2 | 15 | 4 / 16 | 再加本地明确数字确认；不是命名身份或应用授权 |

flags为cipher1、数字确认2、peer proof4、自身安装接受8的组合。
security_epoch是本物理lifetime的接收revision：安全receipt在普通队列之前递增，
即使worker未执行或队列丢失，也不能保留旧正向快照。0为溢出毒化，查询拒绝。
新的加密失败/关闭/rekey、撤权、Down或退休不能由晚到on恢复旧资格；重复或丢失
事件可能保守地降为level0，需重新建链。旧操作终态保留，当前状态另查本接口。

快照只描述读取线性化时刻的机制事实，不是后续USB提交授权。K61905139消费端
在固定通道的实际准入/提交时重新检查安全epoch及全部原权限，新资格单独取得。
SDK111 handle-only0011/Complete的物理复用屏障、固件真实性及无线加密仍有未证明
假设；USB写入、NOCP或日志不代替对端业务校验。准确K6861/U13bb的批准/拒绝/原期限
及无MITM快照限定实机范围见[当前资格](../../project/current-capabilities.md)；实时撤权/
Down等完整失效矩阵及protected完整失效矩阵仍待验，正向固定CUTC另见下文。


### 固定通道安全 epoch Grant（CUTC正向限定实机通过）

未发布48字节v2地址布局不变。`OpenChannelScoped(directions,security)` 的security0
不要求机制，1要求当前level≥1，2要求level2。只有原Managed管理者绑定；普通应用
通过slkd既有调用者/组策略接收fd，不获得控制器管理权限。未知security返回
NotSupported；当前等级不足时返回Failed，包含原生EACCES。动态protected仍不支持。
level2表示本机制的本地数字确认，不表示命名身份、Bond或任意应用授权。

内核在最终绑定的Host锁域内冻结security_epoch。软件发送准入、poll、接收出队、
状态观测及每次实际USB Ticket提交均重新核对当前机制和冻结epoch。epoch变化或
机制失效后只退休相关绑定并唤醒等待者；旧fd不因后续on事件恢复。ACB入口冻结
revision，跨revision的PB重组失败，旧RX不交给之后的受保护fd。已在线性化点准入
的用户copy可继续；已开始的物理发送义务不随关闭/取消消失，USB成功不返协议credit。
同lifetime固定通道最后关闭后重绑仍NotSupported，不由本改动引入热重绑。

`slktest --security 1|2 channel ping|peer ... --check` 复用原普通fd和校验回复。
新选项仅用于固定通道正确性，测量模式和动态路由明确拒绝非零要求，不静默降级。
默认0及原性能报告语义不变；历史报告保留原命令和工具身份。新名称/新选项不授予
新实机资格；真实release/最终fd/dup/Down/期限与同行隔离矩阵仍按唯一计划验收。

## 主动断链的请求原因与物理结果

Native 管理断链的 DLI 请求使用 SLE 远端用户主动终止原因 `0x10`
（SDK111 `sle_disc_reason_t`／指定 NearLink Host 的 DLI 定义）。不得沿用
Bluetooth 的 `0x13` 含义；参考 SLE DLI 将它定义为加密模式不接受。
这不改变通用诊断/UAPI `reason` 字节的编码，也不把请求原因投射为成功结果。
Command Status、调用端 Down、对端 Down 和 D-Bus 属性同步分别核对；
返回原因保留固件原字节，不能强制解释成请求原因或伪造对端断链。
本次只调整 daemon 的管理请求；内核内部清理及预 daemon 测试路径的 `0x13`
仍待 SDK111 对照证据后统一，不能声称所有主动清理已迁移。
K619/U8bda 新产物六项门禁实际取得请求10、本端11／对端10；原参数和五秒预算
未变。旧13产物的反向对照也快速断链并返回对端13，因此新请求语义正确不证明
原超时根因。原默认短包5秒失败继续保留，不授自动恢复或完整安全资格。


## 原 fd 准备发送限制与属性值要求

`SPARKLINK_CHANNEL_PREPARE_TX` 是 `_IOWR('S',0xe3,struct sparklink_send_constraint)`，
结构仍为 48 字节。输入仅 version=1、size=48、minimum=0..2 和非零原始
CLOCK_MONOTONIC 绝对期限；所有身份/epoch/TCID/保留字段须为零。成功填回原 fd
所属当前 Session/channel/epoch，期限不得续期，首次准备最多剩余 5 秒；不预留
credit、不授予权限、不重绑或续 Grant。实际发送仍须携带 `SCM_TX_CONSTRAINT`，
最终 USB 提交重新检查原身份、授权、epoch、期限；准备成功不是发送成功。
未绑定/未就绪、RX-only、过期、撤权及旧 protected epoch 均失败；非法形状 EINVAL，
用户地址错误 EFAULT。不支持的 fd/协议由实际 syscall 返回错误，无成功模拟。

Rust `message_security::prepare`、C `slk_channel_prepare_tx`、Python
`channel_prepare_tx` 使用同一 ioctl。C 输出仅成功时修改，调用者须提供稳定 fd 和
有效对齐存储。`slk_ssap_access_error` 是纯 access 谓词（0 或 SSAP 错误 8/9/10，
非法输入 -EINVAL），不能接收应用伪造等级并据此授予实际权限。

Connection.ReadSsapValue(handle,minimum)、WriteSsapValue(handle,value,minimum)
及 ReadSsapByUuid(...,minimum) 是未发布的新签名。ServiceManager 属性注册/列表
也增加独立 access 字段，详见[操作和访问要求](ssap-permissions.md)。只有唯一
slkd Engine 的真实内核 RX 观察可用于生产值访问；管理 staging 仍拒绝授权位，
逐请求本地授权经 Owned 注册接入，见[审批契约](ssap-permissions.md#应用拥有的本地服务与逐请求审批)。


### 原限制过期与失效 Session 的错误阶段

PREPARE_TX 在 Session 不再活动时返回 ENOTCONN；在原 Runtime/Grant 仍有效的情况下，
sendmsg 的 `sl_tx_access` 会先检查携带限制的原始期限，原限制过期返回 ETIMEDOUT，
先于后续 `sl_admit` 的活动状态判断。因此原 PDU 超时后，新 prepare 和缓存旧限制的
submit 可以分别返回 ENOTCONN 与 ETIMEDOUT；这不表示新准入或续期。撤权/旧 lifetime
等更早的范围检查仍可返回 EACCES/ESTALE，不能任意接受所有错误或猜测优先级。

一次重试被拒绝不能抹去之前已准入并开始的 USB/PB 前缀或未结清物理义务。errno
不能充当“对端没有执行”、协议 credit 退款、排空或安全 handle 复用的证据。可复现门禁
在同一单调时钟记录实际 prepare/submit 前后边界，并保留原5秒/满池/前缀及迟到NOCP。


## WS73 HCC 型号观察与110固件

运行期驱动在BSLE打开后、Runtime注册前发送HCC平台 GET_CHIP_TYPE（16），
校验Complete（10）、成功状态、两字节输出、U/S/E枚举和USB总线。每次查询只发
一条请求，原2秒期限不会因无关输入延长；失败/未知/非USB明确拒绝，不默认U，
不借用DLI command/data credit。`chip_information` sysfs只读快照由每设备phase锁
保护；忙时EAGAIN，元数据失效时ENODATA，不发布旧generation结果或授予Ready。
该型号由固件报告，不认证硅片、板级校准或正在执行的固件内容。

SDK110的真实E回复使用slot=96、HCC分配长度=96、平台分配长度=88，实际结果
仅为result/output_len后的两字节。解析仅对OAM平台子类型9/queue9归一化包含头的
长度；SLE/ACB仍采用原严格边界，填充不得作为型号、结果或额外消息消费。

用户当前选择1.10.110：U/S使用SDK `firmware/us`，E使用`firmware/e`，分别保留
ws73/wifi_cali/btc_cali原SHA头与组合hash。HCC尚未运行的ROM两端点阶段不能
使用该查询决定首次下载镜像；部署必须显式提供匹配输入，禁止按端口/VIDPID默认U。
切换固件后的资格需重新取得，旧111和旧四U结果不能转授110或混合E/U设备。


### 应用拥有的 SSAP 服务

`ServiceManager` 的 Owned 三方法和 `SsapAuthorizer.AuthorizeValue` 的精确字段、
权限、原期限、所有者退出及写入不确定性见[SSAP 服务所有权](ssap-permissions.md#应用拥有的本地服务与逐请求审批)。
旧 `RegisterLocalService` 继续拒绝授权位；新登记与等待审批复用唯一 Engine 和
实际约束发送，不代表 CPCD、长写、可信身份、Bond 或全部多应用部署已验收。


## 安装布局与卸载边界

通用Make与Debian都调用`install-files`；编译只走锁定Cargo与共享预算。
`make install`固定构建release/workspace，不接受build目标的CARGO_FLAGS改变profile；
只安装已封存产物用`install-files`。`CARGO_TARGET_DIR`默认采用固定开发目录，
`ARTIFACT_DIR`默认其release子目录，
资格产物须另行封存。`install-files`先核对实际ELF及SONAME，再渲染运行路径。
`DESTDIR`只是文件暂存根，不得进入运行期Exec或pkg-config字段。

`DOCDIR`默认`${PREFIX}/share/doc/sparklink`，保存上游`LICENSE`和归属说明；卸载只删除
本项目这两个文件，保留同目录其他文件。分包也携带这些说明，仍不表示第三方许可、
SBOM或发布来源审计完成。Debian用已验证的13.24.2或更新helper，在服务启动脚本
前处理唯一sysusers定义；文件存在或APT成功不能替代实际组与普通用户权限门禁。

准确247分包的[基础限定VM资格](../evidence/debian-package-base-qualification-20261018.json)
已覆盖上述实际组/服务/普通用户、运行包Python、开发包C和配置保留。分包许可证
按Debian惯例压缩为`LICENSE.gz`，解压字节与上游一致；通用Make保留未压缩文件。
同版本重装不等于跨版本升级/回滚；debug/依赖警告及完整许可来源审计、实际原生
权限和新设备产物资格分别待验。历史失败与原产物身份继续保留。

通用Make默认使用固定rustup工具链；Debian的清理、构建和测试都显式使用已安装
的`cargo`，版本仍由Build-Depends和准确构建记录约束，不要求发行版Cargo解析
rustup的`+版本`参数。该清理修正的源码回归与[原失败](../evidence/debian-clean-dispatch-failure-20261018.json)
分列；实际分包安装、升级/回滚仍待独立VM门禁。

| 文件/入口 | 当前源码契约 |
|---|---|
| daemon/工具 | `SBINDIR`/`BINDIR`来自PREFIX；systemd与D-Bus实际Exec匹配，带显式`--config SYSCONFDIR/sparklink/main.conf` |
| 应用C库 | Cargo产物`liblibsparklink.so`安装成`libsparklink.so.<version>`；SONAME `libsparklink.so.0`，开发链接名`libsparklink.so` |
| 显式Native库 | `libslk_native.so.<version>`；SONAME `libslk_native.so.0`，开发链接名`libslk_native.so`；不成为默认App管理权限 |
| 头/pc | `sparklink.h`、`sparklink_native.h`位于INCLUDEDIR；`sparklink.pc`/`sparklink-native.pc`分别表达两种API，`-I`指向真实头目录 |
| 系统集成 | 默认`/usr/share/dbus-1/{system-services,system.d}`及`/usr/lib/{systemd/system,udev/rules.d,sysusers.d}`，独立于程序PREFIX，可显式覆盖 |
| 配置/状态 | 既有main.conf、配置目录权限/symlink与状态不覆盖；默认示例单独安装；新建保留状态目录0700，目前不是合格Bond库 |

运行路径须为canonical绝对ASCII路径，不接受空格、`..`、systemd/pc元字符；不能安全
渲染的布局明确失败。暂存根可含空格。API尚未发布，SONAME0不表示旧未发布接口具有
兼容期；未来ABI升级和发布资格仍需独立评审。

`make uninstall`只删除明确版本的包拥有文件，保留管理员配置、状态、子目录/symlink
与其他版本库。没有自动purge、组成员加入、服务启用或真实设备操作。
Native Rust层的`slk_native::channel::{open,open_service,open_dynamic}`负责特权fd
创建，使用现有controller/generation/lifetime/handle与Managed token；它们不是普通
SDK入口，不决定D-Bus策略，也不返回Ready或业务完成。固定通道保留0..2机制要求，
动态仅基础模式/无protected降级；`DynamicConfig`沿用非零端口/AID、MTU1..2042、
MPS不超过2047且至少MTU+5的暂存限制。内核仍作最终准入和协商；active connect
接受EINPROGRESS返回的fd继续暂存，必须用现有poll/info检查实际结果。
这些Rust构造函数不新增C/Python管理导出。普通C/Python应用仍只通过broker取得fd。
同一 Connection 的 Native 创建资源有界；应用遇到进行中的创建返回明确 busy，
不排无界队列。唯一服务初始化器可以在首次五秒期限内等待资源。物理 Connection
对象发布不代表服务初始化、CMTC 或 ExchangeInfo 已完成；仍查询各自实际状态。
退休后的新创建及迟到 fd 接收被拒绝，清理等待实际创建及未消费结果，不由请求者
取消提前宣布完成。完整 Kernel/USB drain、fd 传递和撤权组合资格见当前能力入口。
本批只是职责迁移；迁移后新artifact的实机资格另取，不继承fa310资格。

三个既有角色组sparklink、sparklink-apps、sparklink-services用同一sysusers来源；
普通应用从slkd取得授权fd，默认udev只配置Native字符设备，不授予raw USB绕过路径。
实验USB直通是另行授权的实验室策略，不能由普通应用权限推导。

上述是当前源码与实际开发ELF的离线暂存检查范围；干净VM服务、包管理升级/回滚及
安装后的Python消费者仍须另验，旧WS73资格不转授此改动。D-Bus默认策略目录依据
[官方daemon文档](https://dbus.freedesktop.org/doc/dbus-daemon.1.html)，Debian的sysusers
集成由[debhelper](https://manpages.debian.org/testing/debhelper/dh_installsysusers.1.en.html)
处理；声明文件存在不等于实际组、bus权限或服务已经验收。


## Typed Peer观察与资源边界

`Adapter.ListPeers() -> as`仅返回已确认发布的Peer路径，格式为
`/org/sparklink/slk{index}_g{generation}/peer_t{type:02x}_{address:12hex}`。
同地址不同类型不合并；旧Device、GetDevices及dev路径已退休，无兼容期。
`Peer.GetInfo`的ConnectionKnown/Connected及Connection路径来自当前Native快照，
与广告/RSSI有效性分开；Peer对象及其地址不代表认证身份或授权。

`Peer.GetObservation() -> (tysbbnayayttt)`依次返回generation、地址类型、地址、广告
有效、RSSI已知、RSSI数值、原始WS73头、原始数据、Native序号、kernel boottime ns、
该报告lost。RSSI已知=false时数字字段没有意义；Rust SDK为None，CLI显示unknown。
SDK哨兵0x7f、仅连接而没有广告、过期观察不会显示为0 dBm。Header/data是单次
原始vendor报告，不重组分片、不推导名称、DiscoveryLevel、SSAP UUID或安全状态。
类型0/1使用公共前缀；其他类型保留在raw reports，不静默改成0。实际地址模式资格
仍见能力入口，不能由parser可解码推导全部类型/隐私已实机通过。

Rust使用`Controller.peers()`及`Peer.info()/observation()`；固定daemon owner、controller
和typed身份，无属性缓存或替代daemon回退。`slctl peers`和`peer-observation <path>`
消费同一SDK，旧devices/info已删除。C/Python完整broker/SSAP客户端仍待接通。

每controller最多128个Peer（含仅连接、pending和retiring），header/data/path实际
分配容量合计64KiB；固定对象/映射开销另由数量上限约束。这不是daemon整体内存
上限。容量不足拒绝整个更新并计数，最老且没有连接引用的Peer进入Retiring；实际
移除前不释放slot或收编foreign对象。无新广告60秒则广告失效；有当前或Unknown
旧连接引用的Peer继续保留，只有实际已知快照才能确认相应关系不存在。

Adapter的PeerCount、PeerBytes、PeerDrops、PeerPublicationErrors、PeerRetirementErrors
为RO统计，包含未完成发布/清理。Peer.ObservationValid/RssiKnown及这些统计声明
EmitsChangedSignal=false；调用者应直接Get或禁用属性缓存。动态zbus Proxy不会自动
按服务端注解禁缓存，原错误假设及失败证据保留。原始native_reports环保留其独立
证据职责，不是另一个连接状态来源。

同一个EventTask每轮最多8项、共享100ms本地维护期限，以既有1秒tick重试和清理；
这不是协议期限或恢复策略。未确认记账保留slot，轮转防止单个失败项目独占重试；
通知不能直接授予连接、credit或权限。操作失败、未知generation和发布冲突明确拒绝。
生产源码、离线/形式化和实机范围分别记录于唯一能力入口，新代码不继承历史资格。

## 退休 Native 控制门面与元数据错误

旧广播/扫描、bare-handle连接收发、ExtAdv、PHY/role/AFH、PM/sync、privacy/RAL、
measurement和测试crypto ioctl包装已删除。旧C九函数、相应CLI、Controller旧方法及
ExtAdv对象/白名单同步退休；不保留只返回不支持的门面。真正发现/连接/安全继续使用
版本化Native请求/结果；Controller仅GetLinkSummary/GetControllerEventPosition/ConnCount。
标准profile未接通的扫描/连接模式明确NotSupported，没有旧模型fallback。
旧Device观察对象和其Connect/Disconnect/GetConnectionInfo均已退休；按完整身份使用Peer/Connection。
`slctl show`读取ScanningState，不再消费旧Discovering布尔副本。

Native `slk_device_count`读取与枚举同一Core注册bitmap，包含pending/fault分配，不是
Ready或真实设备健康计数。原包装忽略scalar ioctl返回值的静态缺陷已修复；历史RF/ABI
资格并未覆盖该正向计数。count/info整数失败统一负errno；open失败为NULL并设置线程局部
errno，Python以OSError保留来源，拒绝内嵌NUL路径。C非空指针仍须合法、对齐和满足借用
契约；这不承诺任意坏指针安全。五个退休Python布局移入明确历史测试fixture，与原C/Rust
raw声明比对及宽度/边界回归保留，不再出现在当前Python或C头中。raw内核声明/selftests
须下一批同迁，旧编号不复用。当前生产与实机范围仍按准确artifact的资格记录，不能由
本节接口整理推导完整Native SDK、干净安装或C/Python真实业务资格。

## C 导出符号检查的范围

应用库与显式 Native 库分别由各自生成头描述；两者不互相补齐缺失导出。
`tools/check_public_symbols.py` 接受 `--application-library`、`--native-library` 和
可选 `--output`，调用真实 `nm -D --defined-only --format=posix` 与当前头独立对照。
当前仅支持无版本的函数导出；缺失、未声明或非函数符号、重复、空/截断输出、工具
诊断/失败、检查中材料变更均拒绝。报告路径已存在也拒绝覆盖。

此检查记录实际库、头、检查器hash及nm版本，不执行库函数。符号名称一致不等于
ABI布局、指针契约、权限、生命周期、外部消费者或实机资格；现有C/Rust/Python布局、
实际调用、原errno和VM门禁仍独立执行。CI在构建两库后运行实际导出检查；
`make arch-check`只运行其负对照，未构建库时不伪称已检查ELF。

标准profile的当前事件消费者限于命令结果、命令credit和控制器关键故障；其他
未接通业务事件被拒绝并计数。WS73 Native发现/连接/ACB/安全使用原本的独立
lifetime-bound入口，不能从历史标准事件名称推导当前能力。原始状态与限定资格见
[能力记录](../../project/current-capabilities.md)。

## 实验性运行期地址配置

Native Rust 管理封装 `Adapter::runtime_address_submit` 与
`slkconfig --adapter INDEX --generation GENERATION runtime-address ADDRESS`
接通未发布的 `SL_IOCTL_RUNTIME_ADDRESS_SUBMIT`（0xd7，48 字节）。
它只接受 WS73 profile 1 的未使用 Setup，要求 CAP_NET_ADMIN 及原 File 独占
Diagnostic lease；普通应用 SDK、C/Python 应用 API 不开放此管理操作。
六字节按显式控制器顺序传输，不套用 Wi-Fi/Bluetooth 的分配位规则，
不代表厂商、联盟或认证地址；没有 eFuse、Flash 或 NV 写入入口。

每次注册最多一次配置。请求携带 generation、单调 request_id、原始
1..5000 ms 期限；完全相同请求重试仅取回原 seq，不重复发送。
已有命令队列、credit 和提交票据发送 DLI 0x0405。真实 status-only Complete
只证明设置命令完成；随后必须在原期限内取得匹配六字节的真实 0x0406 回复，
才在 Runtime 锁与 Host 锁保护下发布当前地址。读回前元数据无效，Managed 被拒绝。
CLI 先真实查询并输出原地址，再设置、读回并检查 Runtime 快照。
libws 的本地地址缓存不能作为控制器读回证据。

取消或最后关闭不抹去已提交的物理义务；未核实设置在释放时隔离为不确定状态，
不能宣布 Free/Ready。进一步改变地址须经已有重新初始化流程获得新生命周期身份。
旧 own-address 的广播参数返回 ESTALE；不进行活动连接迁移。
CLI 成功也不证明发现、建链、对端应用交付、断电保持或生产唯一身份。
新入口的实际资格仍按项目能力记录的准确 artifact 单独核对。


## Managed 类型化链路命令

未发布的 `SL_IOCTL_LINK_COMMAND_SUBMIT`／`RESULT` 为 0xda／0xdb，当前结构为72／88字节。
旧查询专用0xd8／0xd9已退休，不复用编号或保留兼容门面。
Native Rust `link_command_submit`／`link_command_result`、显式 Native C
`slk_link_command_submit`／`slk_link_command_result` 和 Python `sparklink.native`
使用同一实现；普通应用 API 不会取得 Native fd 或管理 lease。

输入携带原 File 的 Managed epoch、generation、完整 connection lifetime、handle、
role、地址类型／地址，以及原始 `CLOCK_MONOTONIC` 纳秒期限。Native 调用者必须使用
同一内核时钟域；不得使用另一主机、旧启动或任意时钟偏移。`timeout_ms`1..5000限制
剩余预算，不是排队或 ioctl 等锁后重新授予的相对期限。完全相同的 request_id／
范围／期限重试只取回原 seq；不同参数拒绝，旧编号不复用。

kind1为RSSI、kind2为PHY，argument必须为0；kind3为链路payload偏好，argument是非零16位
请求值。action1提交，action2撤销原作者。命令仍通过原 Host 队列、
command credit 和原子提交票据，准入／出队／实际提交均检查原身份及权限。
成功 Status 只确认接受；查询的真实 Complete 必须匹配完整长度与 echoed handle。
kind3按当前SDK方言要求status-only Complete，不制造echo或有效长度；实际不同格式会
拒绝并保留失败，不能静默选择另一种解码。
不开放任意 opcode，也不在 Native Host 占用时取得 Diagnostic 或走 libusb 旁路。

结果不消费记录，可用 seq 或原 request_id查询，释放 lease 后同 File 仍可读取历史。
state1等待、2控制器成功、3本地／控制器失败；flags1仅表示锁内快照时连接与lease身份
仍当前，flags2表示值可用，flags4表示确有控制器状态。CURRENT 不表示样本新鲜度，
也不授权后续提交。本地负errno不能伪装成控制器 Complete。RSSI的127是无效哨兵；
PHY保留八个原始线字段，SDK方言解释和空口行为另行验证。取消、关闭、撤权或到期
不抹去已开始的物理义务；迟到回复不能覆盖原作者终态。

`org.sparklink.Connection.ReadLinkMeasurement(kind,timeout_ms)` 是 control-role 管理
RPC，虽以Read开头也不向默认观察者或apps-only组开放。daemon使用原Managed fd，
每controller的查询和偏好设置共用一个操作预算；等待回复时不持有租约准入锁。调用者退出／原期限结束会
通知实际阻塞任务撤销原请求；该任务保留fd与预算直至真正退出，不宣称USB drain。
显式管理客户端为 `Controller.management().read_link_measurement`；CLI是
`slctl --adapter ADAPTER link-measurement CONNECTION rssi|phy [timeout-ms]`。
CLI输出真实结果后，若没有成功、当前且有效的测量则失败退出，不生成默认值。

`org.sparklink.Connection.SetLinkPayloadPreference(requested_octets, deadline)` 也是control-role
管理RPC，默认观察者与apps-only组不获准调用。deadline复用现有五字段原始时钟域戳，
包含boot/time namespace身份和CLOCK_MONOTONIC期限，不是重新开始的相对预算。
SDK `Controller.management().set_link_payload_preference(path,octets,timeout_ms)` 在首次
工作前创建同一个原期限；连接查询、RPC和返回检查都受它约束，daemon验证时钟域并
将原始纳秒期限原样交给Kernel票据。CLI为
`slctl --adapter ADAPTER link-payload-preference CONNECTION OCTETS [TIMEOUT_MS]`。

回复 `Acknowledgment` 绑定完整连接身份、原request_id／期限和 `requested_octets`。
这个字段只复述原请求，不是协商结果。state2仅表示真实控制器命令成功；kind3永远不
设置value-available位，也不更改controller ACB上限、DTAP MTU／MPS、SSAP MTU、Ready
或安全状态。取消／关闭不能撤销已经生效的控制器偏好，也不能抹去在途义务。
编码范围1..65535不保证固件支持；未设置自动fallback或默认初始化步骤。

这些是开发源码契约。`ENOTTY`／`EOPNOTSUPP`表示接口或模式缺失，`EPERM`表示权限／
作者不符，`ESTALE`表示身份或epoch失效，`ETIMEDOUT`表示原期限结束，`ENOENT`表示
结果缺失／淘汰。准确实机资格只由[能力入口](../../project/current-capabilities.md)授予；
编译、ffi负向测试、有效线格式和命令 Complete 均不能替代对端应用交付或无线根因证据。
