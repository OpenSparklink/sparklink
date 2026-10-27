# SSAP 操作权限语义

权限位审查的历史基线：Linux `31769ea4b8c0`、用户态 `ac64b3566f33`。
本页维护仍复用的权限类型及当前入口契约；实际服务、安全与长写范围须分别核对
[当前资格](../../project/current-capabilities.md)，不能由权限位声明推导。
标准语义来源为项目审查使用的 T/XS 20001-2025 V1.2.0 表32；受限原材料不发布。

| 命名 | 值 | 含义 |
|---|---|---|
| READ | 0x01 | 读取 |
| WRITE_NO_RSP | 0x02 | 无响应写入 |
| WRITE_WITH_RSP | 0x04 | 有响应写入 |
| NOTIFY | 0x08 | 通知，无ACK |
| INDICATE | 0x10 | 指示，需ACK |
| BROADCAST | 0x20 | 广播 |
| DESC_WRITABLE | 0x100 | 数据值说明描述符可写 |
| CLIENT_CFG_WR | 0x200 | 客户端配置描述符可写 |
| SERVER_CFG_WR | 0x400 | 服务端配置描述符可写 |

有效mask=0x73f。b6、b7、b11..b31保留，必须拒绝。read+notify是0x09，不能获得
任何写权限；两种写权限不能相互替代。操作声明与认证/加密/授权是独立约束，
不能把设置权限位当作已经授予调用者访问。标准Engine须同时核对peer安全上下文。

## 当前源码与拒绝规则

系统总线角色与属性权限位是两层约束。`sparklink-apps` 只获得原期限约束的远端
读写、单次接收及持续接收租约调用；不获得 controller 管理、Owned 服务修改或
安全安装权限。服务拥有者、实际链路机制／epoch 和远端属性审批仍独立检查。
无原期限的发现／UUID／信息入口本批未扩权。确切方法见[接口参考](interfaces.md)。
实际 system bus 中错误预检只能证明策略允许请求到达 daemon；正向业务仍须对端
应用校验、回复及两端包证据，不能以 InvalidArgs、协议 ACK 或本地入队替代。

实际生产语义由 Rust `slk_protocol::SsapOperations` 与唯一用户态Engine消费。
旧内核 `SL_SSAP_OP_*` 和valid/allows/fits_legacy helper已退出公开头，只保留在
有来源hash的私有C测试见证中；它不是内核SSAP服务接口。
Python `bindings/python/sparklink/ssap.py` 拒绝 bool、负数、超32位和保留位；
`to_legacy_bits` 显式拒绝 descriptor 权向8位缩窄。
legacy narrowing 仅保留历史 ABI/权限回归，不再有生产 facade 消费者；不恢复已删除的数据库/业务 ioctl。

旧 AddProperty/WriteProperty/RemoteService.Write/CallMethod 等未发布入口已删除，
CLI 和观察者白名单同步退休。原权限、超限和不截断语义由实际 codec/数据库及
现有纯测试保留；不再把历史 248/252 输入限值描述成当前 Engine 的协商 MTU。

完整PDU阶段按opcode开销限制远端值：read最多为协商MTU减2字节，单项UUID读取
最多为MTU减4字节。本地数据库的2042字节预算不代表该值能装进任意响应。
未协商本地支持的有序号分片格式时，超过完整响应MTU的两种读取都返回READ_RSP错误16，
不截断、不换成通用错误响应、不更改属性值；同一actor仍可继续处理后续合法请求。
真实读写仍核对操作位、连接身份、安全上下文、原期限和本地授权；登记成功不能
代替对端收到。新开发路径对已协商分片序号的单值read/UUID/verified-write复用同一Engine，逻辑值
预算2042字节；每片独立经过Native约束。更新/发现分片、事务号并发、无序号分片和
完整失败矩阵仍未支持。机制见[分片解释](../explanation/ssap-value-fragments.md)，
实际资格仍只由当前能力页的准确产物记录决定。

`org.sparklink.ServiceManager.RegisterLocalService` 是现有唯一用户态数据库的
入口，当前只接通 READ 和 WRITE_WITH_RSP（mask `0x05`）；其他有效操作位返回
NotSupported，保留位返回 InvalidArgs。注册成功只表示本地 staging；远端真实
发现/读取/写入须经唯一 Engine 和对端业务核对，不能使用已退休的 facade 代替。

## 测试和证明边界

保留历史精确C helper、当前Rust/Python权限回归、独立表32预期、保留位、缩窄
和超长拒绝；历史C见证不升级为当前内核能力，离线一致性
不等于 SSAP 双端操作或安全证明。旧数据库调用和当时测试范围见
[权限整改原始记录](../../project/reference/ssap/ssap-operations.md)，已删路径见
[生产剥离审计](../../history/ssap/ssap-production-separation-20261013.md)。
当前实机资格仅由[能力入口](../../project/current-capabilities.md)维护。

## 唯一 SMTC 的通道安全要求

`main.conf` 的 `[ssap] channel_security` 在 daemon 启动时校验，允许整数
`0`、`1`、`2`，默认 `0`。未知字段、负数、错误类型及更高等级拒绝启动，
不回退默认值。该值复制到每个 Connection 对象，在首次 SMTC 绑定前固定；
只读 D-Bus 属性 `org.sparklink.Connection.SsapSecurityRequirement` 返回该要求，
不表示当前已满足。没有运行期热更新或同 lifetime 升级、重绑承诺。

| 要求 | SMTC 首次绑定行为 |
|---|---|
| `0` | 保留连接发布时自动启动的基本通道 |
| `1` | 要求内核当前 Session 的 SDK111 已安装加密机制；未满足不绑定 |
| `2` | 要求当前 Session 的 SDK111 数字比较机制；仅等级 1 不足 |

非零要求下，发布 Connection 不启动普通 SMTC。真实原生安全请求完成后，
daemon 提示同一 Engine 启动；显式 SSAP 请求也可尝试首次绑定。最终准入仍由
内核核对当前 generation、lifetime、lease、安全等级及 epoch。Agent 批准或缓存
结果不授予通道权限。绑定失败时 SSAP 调用失败，不降级、不新建另一套 Engine。
Engine 启动后的过期、撤权、断链和旧安全 epoch 由原 Grant/socket 路径拒绝；
失败 Engine 不在同一 lifetime 自动重开。两端须各自满足本地策略。

这是整个 SMTC 的最低传输要求，不是属性级认证/本地授权或 Bond 策略；
`policy.min_encryption` 的非零值仍明确不支持。READ/WRITE 等操作位不携带安全
等级。数字比较机制不等于已绑定命名身份，也不构成独立 RF 加密证明。
新增实现的离线、形式化和实机资格分别记录，不能继承旧普通 SSAP 通过结论。


## 原请求观察与响应限制

唯一Engine的生产Native Wire读取真实内核消息上下文；unknown、非current、身份/
lifetime/channel不匹配或control截断均失败，不从最新连接快照给旧请求升级资格。
响应、错误和指示ACK携带该原RX epoch与观察机制下限，并固定原响应义务的绝对
单调期限，由原Session/Grant/Ticket在实际USB提交时再次强制；软件准入不等于
物理或对端完成。显式AF_UNIX测试Wire不生成安全上下文，不进入生产构建。

主动 ExchangeInfo 和客户端请求也通过原 fd 的 PREPARE_TX ioctl 取得限制，实际
sendmsg 必须携带限制；没有 raw-send 回退。准备不预留 credit、不续 Grant、不升级
旧 protected fd 的 epoch。客户端回复须匹配原请求 epoch 和机制下限。操作位、命名
身份/Bond、实际机制和本地授权保持独立；失败响应不会回滚已发生的数据库写入，
请求超时也不能证明对端未执行。精确ABI/错误/原期限见[接口参考](interfaces.md)，资格只在唯一能力入口维护。

## 逐属性值访问要求

本地注册 properties 项现为 `(uuid:ay, operations:u32, access:u32, value:ay)`。
`ListLocalServices` 的属性项为 `(handle:u16,uuid:ay,operations:u32,access:u32)`。
未发布接口同步迁移，无旧签名兼容期。操作位仍用表32的 0x73f；access 是独立六位
本地 API 编码，复用固定 NearLink Host 的 NapiPermission，不把它写入远端属性声明。

| access 位 | 值 | 限制 |
|---|---:|---|
| WRITE_ENCRYPTED | 1 | 写原请求观察机制至少 1 |
| WRITE_AUTHENTICATED | 2 | 写原请求观察机制至少 2 |
| WRITE_AUTHORIZED | 4 | 仅 Owned 登记及有效原请求审批可满足；旧 staging 仍 NotSupported |
| READ_ENCRYPTED | 8 | 读原请求观察机制至少 1 |
| READ_AUTHENTICATED | 16 | 读原请求观察机制至少 2 |
| READ_AUTHORIZED | 32 | 仅 Owned 登记及有效原请求审批可满足；旧 staging 仍 NotSupported |

保留位返回 InvalidArgs；授权位不能由任意应用布尔值授予。当前内核的等级 2 表示
SDK111 数字比较机制，不能推导命名身份、Bond 或独立 RF 加密证明。服务端在读取
值或修改数据库之前检查真实原 RX 上下文；普通读取、按 UUID 读取、响应写共用同一
检查。认证不足返回表51错误 8，加密不足返回 10；未获本地授权返回 9；只有当前 Owned 登记的原审批者可满足该要求。公开发现元数据不包含受保护的值或 access 要求。

`slctl ssap-register SERVICE_HEX PROPERTY_HEX OPS ACCESS VALUE_HEX` 只配置本地库。
`ssap-list` 列出本地元数据，不能当作远端发现。`ssap-read`、`ssap-write` 和
`ssap-read-uuid` 末尾可指定 `MINIMUM`（0/1/2，默认 0），经唯一 Engine 和原 fd
约束实际发送；超出当前机制或输入范围明确失败，无明文降级。局部数据库检查、
访问谓词测试和工具有界结果不能替代真实双端请求/拒绝/修改及 USB 证据。

实现已接通；本批新源码的实机资格须单独取得。Kani 检查原生产谓词的七项性质，
工具仍有编译诊断，当前保持“未证明”，不升级为全生命周期或安全协议证明。


`sdk111-*` 是现有实验Agent方法的历史方言名称，不是执行固件的版本证明。
SDK110 U设备两机制的准确短消息/SSAP资格已单列；E、完整负向部署矩阵、命名身份/
Bond及属性授权不继承。当前版本适用范围仍只由能力入口的准确artifact记录决定。


## 应用拥有的本地服务与逐请求审批

SDK 的 `ssap::authorization` 复用 CLI 的准入检查和有界等待；CLI 不再另存一份
检查规则。`AuthorizationContext` 是调用者的只读观察快照，不是活动登记、kernel
Grant 或安全资格。它仅接受原 unique daemon、当前 controller/generation、已收到
的属性 handle 和基本 CUTC 上下文；仍检查同一 operation/access 类型及原五秒期限。
审批等待不执行应用代码，owner 丢失/关闭、答复释放和原期限到期均拒绝。答复后必须
重新取得快照并校验；批准不替代 daemon 对登记、物理 Session 和安全机制的最终检查。

CLI 退出时先停止本地审批准入，再异步撤回登记；撤回失败不重新开放审批。
这不表示远端清理已经完成，也不自动接通 C/Python callback、provider 或通知。

`RegisterOwnedLocalService(uuid:ay, properties:a(ayuuay), authorizer:o, deadline:(ttttt))` 的 properties
沿用上述四字段（实际 D-Bus 签名 `a(ayuuay)`），返回 `(start:q,end:q,handles:aq)`。
登记者来自真实消息 sender 的 unique name，不能指定其他 owner。`authorizer=/`
表示不提供审批；带授权位的登记此时返回 NotSupported。服务登记仍只表示本地配置。
`UnregisterOwnedLocalService(start:q, deadline:(ttttt))` 和
`ReadOwnedLocalValue(handle:q, deadline:(ttttt))->ay`、
`ReplaceOwnedLocalValue(handle:q,value:ay,deadline:(ttttt))` 只允许
原 owner；管理组的显式全局移除/本地读权限仍独立。`sparklink-services` 策略只允许
这四个 Owned 方法，不授 controller 管理或普通通道权限；[cd35/0568的guest最小角色门禁](../evidence/architecture-retirement-r1-20261017.json)
已核对实际system bus、组/凭据及设备权限，不代表service-only远端RF或完整发行版部署。

四个 Owned 方法均携带现有 clock-domain 身份和绝对原期限；客户端检查、D-Bus、
状态锁等待、owner 监听安装及数据库最终准入共用该期限。过期返回 Timeout，
不重置相对预算。监听安装另有两秒上限，只能缩短该请求。当前 zbus 在进入方法前
以 `org.freedesktop.zbus.Error` 拒绝旧签名（Signature mismatch）；不兼容回退。
注册的原期限只限制初次准入，不是已注册服务的 TTL。活动服务仍由原 owner、
显式移除和 controller 退休管理；后续本地读取、移除各带自己的原期限。

数据库最终检查和插入在同一短临界区，没有 await；期限后不接受新的准入。
已准入但回复丢失／迟到不等于回滚。SDK 仅在收到合法回执后，才可对原 unique daemon
及原 generation 的原登记做一次独立、最多一秒的移除尝试；这不延长注册准入期限，
也不保证清理完成。未知／畸形回执不得猜测删除目标；owner 退出的清理义务保留。
初始化取消只请求 abort，不能称 watch 已 drain；容量由 watch future 持有，直到实际
销毁后归还，不能在旧任务仍存在时补出第十七个监听。

审批调用原 unique owner 的 `org.sparklink.SsapAuthorizer.AuthorizeValue(prompt)->b`。
`prompt` 是 `(request_id:t, identity:(qttqtuyyy), property:q, write:b, deadline:t, value:ay)`；
identity 的实际签名为 `(qttqtuyyy)`，依次为 controller、generation、lifetime、connection
handle、原 RX security epoch、原 RX security level、local TCID、remote TCID、PI。
READ 不发送秘密值；WRITE 携带有界 proposed value。期限是原 RX 响应义务的绝对
CLOCK_MONOTONIC 纳秒，最长五秒；排队和审批不重置期限。超时/方法错误/退出不批准。

每 adapter 最多16个正在登记/活跃 owner watch（单服务一个），同 actor 待发响应、
排队请求和正在审批请求合计最多8条。先监听 owner 退出再核对存活。句柄在同数据库
不复用；删除重建、原 owner 退出或失效审批不能访问新属性。controller退休时先撤销登记，
再在数据库锁之外等待owner watch退出；最终析构保留abort兜底。审批等待不持数据库锁，
不预留协议 credit；唯一 actor 继续处理其他 RX/client/ACK，但按服务请求顺序答复。
期限失败仍失败该 Engine，不承诺同 lifetime 自动重绑。

读/写前通过原 fd 重查 generation/lifetime/security epoch，数据库锁下再核对登记和
owner；这是一份准入快照，不是内核与数据库的原子事务。已经提交的本地写入不会因
随后撤权/断链回滚；原响应继续受原 Grant/Ticket/epoch/期限限制。超时的写入结果
可能不确定。批准只满足本地授权，不满足缺失的加密/认证，也不产生可信身份或 Bond。

`slctl --adapter PATH ssap-serve SERVICE_HEX PROPERTY_HEX OPS ACCESS VALUE_HEX [ask|allow|deny]`
以前台连接拥有服务。默认 ask 要求 `yes TOKEN` 或 `no TOKEN`；TOKEN是该前台进程内
不复用的提示序号，区别于每Engine可重置的原请求编号。提示同时显示原controller/
generation/lifetime/handle/security epoch及原期限。原期限外、旧token或附加字段无效。allow/deny 是服务所有者显式本地策略，不是安全 Agent 自动批准。标准
输入 `value` 通过同 owner 读取实际本地值，`quit` 主动注销；进程被杀时由 unique owner
退出清理。新入口沿用唯一 Engine，不新增远端协议引擎。实现、私有 D-Bus、VM 实机和
形式化结果分别记于能力入口，不继承旧 artifact 的资格。


### C/Python 的基础 Owned 登记

C 的 `slk_client_register_local_service` 接收明确 ControllerId、非零2/16字节服务 UUID
和1..64个 `SlkServiceProperty`。每属性沿用 `SsapOperations`／`SsapAccess`，初值0..2042
字节，超限拒绝，不截断；目前只支持 READ／WRITE_WITH_RSP。authorization 参数为
SLK_SERVICE_AUTHORIZATION_NONE(0) 时拒绝授权位；REQUESTS(1) 显式启用应用审批收件箱。
未知模式 EOPNOTSUPP，不能隐式批准。未发布 C 签名已迁移，不保留旧无模式调用形状。
加密／认证需求继续由现有 Engine 与真实 RX 机制状态核对。

`SlkServiceProperty` 大小2076，value偏移32；`SlkServiceReceipt`大小152，handles偏移24。
整个输入需初始化，reserved/tail必须为零。UUID／value只有指定长度部分有意义。
输出回执的未用字段归零，只是不可变本地身份；不表示 Ready、仍存续或远端发布。
C函数返回0／负errno，失败不改输出。读值容量0..2042，ENOBUFS仅更新所需长度，不改
buffer；再次读取可能观察到新值，不是无副作用的稳定size-query。其他错误不改两者。

Python通过 `Client.register_local_service(controller, uuid, [LocalProperty(...)], deadline_ns=...)`
取得 `LocalService`。属性使用已验证 `SsapOperations`／`SsapAccess` 类型，`receipt`为本地
不可变观察，`read_local(handle, deadline_ns=...)`读当前值，`unregister(deadline_ns=...)`
显式撤回原登记。C/Python均使用原绝对CLOCK_MONOTONIC纳秒，最多30秒，覆盖本地队列、
原receipt mutex及RPC；初次登记期限不是服务TTL。超时不能证明回滚／移除。

`slk_local_service_free`／Python close、context退出及析构只释放本地引用，不隐式做RPC。
派生view保留同caller，因此Client可先close；其他派生引用也可能让caller及服务继续存续。
最后executor释放时排空有界本地工作，真实bus owner退出由daemon清理。未知／丢失回执
不猜测删除目标。禁止C无效指针、并发free或fork后使用；Python在获取继承锁前拒绝fork
对象，析构也不操作继承副本。审批请求模式的 free 会先停本地审批并唤醒通知；不代表远端登记移除。
完整回调／通知、退出及部署矩阵仍单列验收。


(ssap-language-authorization-requests)=
### C/Python 的显式审批请求

Python 登记时选 authorization="requests"；默认仍为 "none"。每个 caller 使用一个
原总线连接上的审批入口，最多16个审批 scope（包括初始化、退休和被请求引用持有者）。
每服务只有一个待决 slot，容量直到实际 callback future 销毁且已交付请求释放后才归还。
没有新 SSAP Engine、数据库、读值 provider 或 Native 管理权。

C 用 slk_local_service_authorization_fd 取得调用者负责关闭的 CLOEXEC 通知 fd；只 poll，
不要读写 counter。fd不携带批准权限或保活 caller。先用非阻塞 next_authorization 取
SlkAuthorizationRequest，再等待通知；EAGAIN表示没有可交付请求。fd转交仅转交就绪观察，
不能据此在另一进程批准。对象禁止fork后使用；普通dup/exec不改变原sender或请求身份。

request_info 返回2120字节的只读原上下文，data_type偏移70、value偏移72；包含controller/generation、
lifetime/handle、epoch/level、TCID/PI、属性、数据类型、原期限和本地token。data_type为
属性值0或客户端配置2；其他类型拒绝。配置2只在声明更新/CPCD能力、真实等级2的
两字节写请求中交付，独立于属性access；不能由同句柄的属性值批准推导配置批准。读请求无值，写请求
只有被提议的0..2042字节；reserved/tail及未用字节归零。request_reply只接受0/1，
直接进入原pending的一次性答复，不经同步RPC executor。0只表示本地决策准入，
不是daemon提交、USB完成、协议确认或对端应用处理。重复／陈旧答复ESTALE，过期
ETIMEDOUT，停止后ESHUTDOWN（daemon scope失效ESTALE）。错误不改输出，不重置期限。

Python service.next_authorization() 非阻塞；带 deadline_ns 时按一个不超过30秒的
原绝对期限等待通知，不持service锁poll。返回AuthorizationRequest，使用其info读取
原快照、reply(bool)答复并close/context退出。未答复的请求被释放即拒绝；请求保活的是
本地审批上下文，不是Client、登记或物理连接。调用者应及时释放每个请求，不能靠保留
旧句柄后再使用新token取得资格。任何批准都要经过同一Rust guard及daemon最终复核。

未发布的`AuthorizeValue`输入为`(t(qttqtuyyy)qbtayy)`，末尾`y`是原SSAP数据类型，
写入方向仍由原`b`字段表达。旧六字段输入在签名解码阶段拒绝；固定zbus版本返回
`org.freedesktop.zbus.Error`及明确的旧/新签名差异，不进入审批队列，没有兼容期。daemon的批准
收据同时绑定当前服务owner、句柄、数据类型及方向；批准不能跨目标或读写方向使用。
C/Python及CLI快照显示该类型，SDK不依据对象路径或可修改的显示文字推断类型。

合法unregister请求先停止本地审批，再尝试异步撤回；失败也不重开审批。free与daemon
owner失效会唤醒等待者。该通知不是controller/connection状态流；物理退休、旧lifetime
和原安全状态仍由原Engine/Native检查。不要把同caller同步RPC的完成作为审批答复前置，
避免该RPC本身正在等待审批；答复入口不会排在该executor后面。

请求和通知 fd 副本均不保活原 caller。父 Client 已关闭、最后服务 view 再释放时，
旧请求的原快照仍可读；原 caller 失效后的答复返回 ESTALE。若 caller 尚被其他 view
持有而本服务已停审，则返回 ESHUTDOWN。两者都不是远端数据库清理的收据；要另外
观察原登记移除和对端拒绝。进程仍在运行、通知 fd 仍可用，也不代表登记仍活动。

专用 VM 门禁的 `ask` 前端只调用这些现有 SDK 入口，持有一个不透明请求。
旧 UI token 不匹配时没有调用答复 API；过期的当前请求则记录实际 API 的 ETIMEDOUT。
观测明确区分这两种拒绝。允许、拒绝、原期限和关闭的实机资格分别按准确产物读取，
不能用本地策略结果替代对端协议回复或应用交付。

新增接口、离线检查与实机资格分别记录于唯一能力入口；旧产物的PASS不覆盖新ABI，
审批模式也不代表完整provider、通知/指示、安全/Bond或生命周期资格。


`ReplaceOwnedLocalValue` 原子替换本地属性值，长度0..2042字节，服务值的共享总预算
8192字节；空值释放该属性原值占用，超限不截断、不更改数据。原unique owner、有效
controller/管理租约和登记必须仍有效，提交与远端写入/移除使用同一数据库锁。它不要求
属性授予对端写权限，也不改变READ/WRITE/安全/审批位；只读对端属性可由自己的服务
更新。InvalidArgs表示错误handle/长度，AccessDenied表示非拥有者/旧登记，LimitsExceeded
表示共享值预算不足。C/Python分别表现为EINVAL/EACCES/ENOBUFS，原期限为ETIMEDOUT。

Rust `ServiceRegistration.replace_local`、C `slk_local_service_replace` 与 Python
`LocalService.replace_local` 使用这一入口，调用成功只表示本地提交，不发通知或指示。
超时/答复丢失可能发生在提交之后，效果不确定；不自动重试。对端须另行实际读取，仍
遵守协商能力、物理MTU和逻辑值预算；仅已协商的单值分片走上述路径，不能推断
通知/指示或provider也支持分片。动态只读值按下文独立的 Provider 契约处理；新CPCD及
Owned通知/指示源码契约见[接口参考](interfaces.md#客户端配置与-ssap-更新的当前限制)，
主动发送资格按当前能力入口的准确artifact及限定范围读取，旧本地替换PASS不升级
为主动发送、持续订阅或完整生命周期资格。

开始有效撤回后，SDK登记进入Withdrawing：后续本地替换被拒绝，即使撤回答复不确定；
仍可观察本地值或显式重试原对象清理。Removed后不再读取/替换，不因新caller复活。

### Owned read-only Provider

本节描述唯一 Engine 已接通的源码契约；准确产物的验证范围由资格记录维护，不继承旧存储值或
授权回调的资格。仅支持 Owned 属性的 type0 动态读取；操作位必须恰为 READ（`0x01`）。
属性的加密、认证和本地授权要求仍分别适用，type1 公开说明保持独立。

`ServiceManager.BindOwnedReadProvider(handle:q, provider:o, deadline:(ttttt))->()`
由原登记的同一 unique caller 调用。`provider` 是该 caller 同一总线连接上导出的对象
路径，必须非根路径且不超过255字节；不能指定另一 owner。原 controller、登记、管理
租约及准入期限必须仍有效。绑定在同一数据库锁下提交，释放该属性原存储值占用，
在本次登记内不可重复绑定、更换或解除。绑定后本地读取与替换返回 NotSupported，
没有缓存值或原初值回退；type1 说明仍可按原接口设置和读取。

零 handle、根路径或超长路径返回 InvalidArgs；未知非零 handle 或非原 owner 返回 AccessDenied；
非恰好 READ 的属性、已绑定或不支持的模式返回 NotSupported。这些拒绝不提交绑定；
原期限与现有 Owned 准入规则一致，超时或回复丢失不能证明绑定未发生。
Rust SDK 另以本地回执预检 inactive/foreign handle，返回 Invalid；该本地拒绝不等于
请求已到达 broker 或完成权限检查。

Engine 调用原 unique owner 的 `org.sparklink.SsapReadProvider.ReadValue`。请求是
单个结构体 `(t(qttqtuyyy)qtq)`，响应结构体为 `(qay)`：

| 请求字段 | 类型 | 含义 |
|---|---|---|
| request_id | `t` | 本 Engine 的原服务端请求编号，不是 wire 消息事务号 |
| identity | `(qttqtuyyy)` | controller、generation、connection lifetime、连接 handle、原 RX security epoch/level、local TCID、remote TCID、PI |
| handle | `q` | 当前请求的 type0 属性 handle |
| deadline_ns | `t` | 原服务端响应义务的绝对 CLOCK_MONOTONIC 纳秒期限 |
| maximum_bytes | `q` | 本次 callback 可返回的动态值字节预算 |

响应 `(status:q, value:ay)` 的 status 为0时接受0..maximum_bytes字节，空值是有效结果。
status 在 `0xAF..0xFF` 时表示应用错误，value 必须为空。其他状态、错误的响应形状、
超长值、非空错误值、方法失败或缺少可调用的 provider 均映射为应用错误 `0xAF`。
读取失败使用相应的 ReadRsp 或 ReadByUuidRsp，不返回旧值。原期限耗尽仍按既有
规则使 Engine 失败，不能改成应用错误后继续接受晚到结果或重置期限。

Provider 等待涉及三个不同起点的期限，不能互相替代：

| 期限 | 起点与约束 | 到期含义 |
| --- | --- | --- |
| SDK 请求 | 应用创建的绝对单调时钟期限，覆盖该调用的身份查询和 RPC 等待 | 当前 SDK 调用超时；不证明远端义务或在途数据已经撤销 |
| 服务端响应 | Engine 接收请求形成的原响应义务，受原重组预算约束；授权和 Provider 共用它 | 当前 SSAP actor 失败；不继续提交迟到的应用值，也不保证能再发错误包 |
| 请求者在途排空 | 当前 Engine 在首次软件准入后建立的五秒清理期限 | 作者超时或退出不能抹去该义务；无回复时请求者 actor 也可能失败 |

测试监督器的观察预算独立于这些协议期限。前台 Provider token 到期后只拒绝晚到
输入，原登记可继续存活至显式退出；该局部存活不代表原 SSAP actor 仍可收发。
后续新连接 lifetime 上的成功，也不能当作旧 actor 恢复或设备自然恢复。

单个动态值最多2042字节；一个服务端义务内所有 provider 返回值共用2042字节累计
预算，包含按 UUID 读取多个匹配属性的情况，maximum_bytes 是尚余预算。混合结果中的
原存储值不计入该动态分配预算，仍受数据库8192字节共享预算约束；完整编码响应、
协商分片和物理 MTU 继续独立限制最终响应，不能截断或由逻辑预算推导一定可发送。

需要本地授权时先完成原审批，再调用 provider；提供一个值不产生访问批准。等待
复用原 owner watch、原请求身份和绝对期限，计入原 actor 的8条服务器义务总预算，
不增加独立请求队列或 Engine。等待应用期间不持数据库锁；actor 可继续处理既有
RX/client/ACK。消费结果时重新核对原 Native 上下文、登记、owner 及同一个 provider
绑定对象，再按原顺序形成响应。该复核不是内核与数据库的原子事务，实际发送仍
由原 Grant/Ticket/epoch/期限约束；callback 返回不等于对端收到。

响应编码并进入原待发 Pending 后，已接受的字节成为不可变响应；随后注销服务不能
撤回这份响应。它与既有存储值读取具有相同边界，仍由原 Native 上下文和期限限制
实际发送；注销不保证已经接受的响应不会交付，也不产生对端已收到的证明。

正常退出会尝试撤回登记；SIGKILL 等非协作退出依靠原 unique owner 消失通知清理。
如果 READ 已通过本地审批并进入 Provider 等待，应用尚未答复就退出，在原 Native
上下文与期限仍有效时，回调调用先失败可产生应用错误 `AF`；数据库先删除该属性
则产生错误4。两者都不表示动态值成功交付，也不回退到绑定前的存储值。数据库
清理与撤销在同一锁内完成，此场景不沿用尚在等待审批时的错误9。原期限到达或
Native 上下文失效则按原义务失败处理，不保证还能发送错误响应。

Rust `ServiceRegistration.bind_read_provider` 封装原绑定方法；共享的
`ssap::provider::frontend` 实现具体 dispatcher、inbox 与一次性 request，SDK、C/Python
和 CLI 使用同一条值回调生命周期。`ssap::provider::admit` 复用 AuthorizationContext
检查原 sender、type0 读取、恰好 READ 和预算，`await_reply` 保留原期限/owner 丢失
等待；frontend 在答复前重新准入。它不授予审批，也不拥有协议 Engine。
SDK 在原 Client 总线导出 callback，不另建 Python 总线或 codec。
动态写入、描述符 provider 和主动更新仍不在本契约范围。

C `slk_local_service_bind_read_provider`／Python `LocalService.bind_read_provider`
返回原属性的 `SlkReadProvider`／`ReadProvider`。绑定仍要求原服务与明确的绝对
单调期限；该期限不是服务 TTL，也不替换各次回调的期限。SDK 保留已尝试的绑定，
同一登记内不自动重试，包括结果不确定的超时。SDK 重复尝试返回 EALREADY，
预留容量用尽为 EAGAIN，非 READ-only 模式为 EOPNOTSUPP；不属于原登记的属性在
SDK 入口以 EINVAL 拒绝。绑定成功只表示本地 broker 接受。

`slk_read_provider_next`／`next_request()` 非阻塞地取得一次性请求；未就绪为 EAGAIN。
通知 fd 是 caller-owned CLOEXEC duplicate，只用于 poll，禁止读写内部计数器；先
尝试取请求，再等待可读后重试。Python 可传不超过30秒的绝对本地等待期限，但它
不延长或重写请求 `info.deadline_ns`。poll 不持有对象锁，reply/free 不排入执行
原绑定 RPC 的队列；每个 inbox 只有一个待决请求，每个 dispatcher 最多16个 inbox
预留。请求视图释放和 callback 完成前均保留该槽位，不以 `reply()` 返回代替 drain。

`ReadProviderRequest.info`／`SlkReadProviderRequestInfo` 是原身份和预算快照；
80字节 C 布局含 `reserved[11]`，与实际头和 ctypes 逐字段核对。快照中的 token 是
本地不复用标识，不能仅凭数字、fd 或旧快照重新取得答复能力。C/Python 入口见
[接口表](interfaces.md#sdk-只读-provider-收件箱)。

`request.reply(bytes, status=0)`／`slk_read_provider_request_reply` 只接受显式值：
状态0允许0至 `maximum_bytes` 字节，`AF..FF` 必须为空。非法状态/非空错误为
EINVAL，超过原预算为 EMSGSIZE，均不消耗原请求；Python 预先以 TypeError／ValueError
拒绝非法类型或状态，超长值仍为 OSError(EMSGSIZE)。不得截短、隐式成功或回退存储值。
重复答复或原 daemon 丢失为 ESTALE，原期限耗尽为 ETIMEDOUT，本地停止为 ESHUTDOWN；
同时发生多个失效条件时不承诺错误优先次序。返回0或 Python 正常返回只表示本地
一次性答复被接受，仍须经过回调最终检查、daemon Native/数据库检查与真实发送。

应用须保持原服务视图存活。inbox、request 及通知 fd 不持有 Client 或服务引用；
service unregister/free 会先停止本地 Provider 准入，待决请求不继续获得答复权，
但这不是远端撤回完成。inbox close/free 只停本地准入，不撤回服务、不解除绑定或
恢复存储值。未答复 request 的释放表示不可用，不保证仍能发出 AF；原期限、数据库
和 Native 规则继续适用。请求的不可变 info 在原 scope 关闭后仍可读取。
Python 沿用原 PID 检查与 RLock，fork 继承对象在进入锁/C 前拒绝；C 对象不得与
free 并发或跨 fork 使用，非空 value 指针须覆盖实际 length 字节有效内存。

待决注销的受控检查须先实际取得原 Provider 请求，再在其原期限内调用服务注销。
分别检查注销结果、仍持有的不可变 info、通知 fd，以及旧 request 的答复拒绝；
单纯退出进程或先关闭 inbox 不能替代这一交错。现有外部 C/Python 回归通过真实
私有 D-Bus 检查 SDK callback 的停止，服务登记元数据仍是 fixture，不能据此声明
daemon 数据库删除、真实对端响应、独立服务隔离或空口生命周期验收通过。

专用 VM runner 的 `--ssap-provider-unregister-verify` 使用已有
`--ssap-read-provider-verify` / `--ssap-owned-verify` 与普通双设备通道基线。
该选择与 Owner SIGKILL、Provider 到期及正向 SDK 值序列分别运行；不得合并为
同一种生命周期结果。工具在原 SDK 请求实际到达后发送 `provider-unregister`，
保留 request/info/readiness fd 的检查，并要求旧回复返回 `ESHUTDOWN`；进程在
对端拒绝、退休 handle 拒绝和独立 guard 校验期间保持存活，最后正常退出。

准入的 SDK 错误只是一端观察。判定还要求两端原 USB READ/响应、原期限、同一
controller/generation/lifetime、guard 随机值实际校验，以及注销清理之后的普通
通道往返；缺包、旧身份、超时、错误收据或用 SIGKILL 替代均失败。工具接通及
fixture 检查不表示这个新 artifact 已通过实机，具体资格以唯一资格入口为准。

这些应用入口已在源码接通；离线封装/ABI/生命周期检查与实际产物资格独立维护，
不从基础远端读取或历史 CLI Provider 记录推导 C/Python 服务端 Provider 实机资格。

现有 `ssap-serve` 进程输入 `provider`，将原 READ-only 属性绑定到本进程 callback。
实际回调输出 `SsapReadProviderPrompt`，包含原身份、期限、maximum_bytes 和带 `p`
前缀的本地 token。`provide pTOKEN HEX` 返回显式值，`-` 表示成功空值；
`provider-error pTOKEN STATUS` 返回两位十六进制 `AF..FF` 应用错误。token 与审批
提示共用进程内不复用的计数，回复命令各自独立；过期、重复、错误 token 或超长输入
不能结清另一个请求。provider 与 authorizer 各有一个待决槽位，等待 stdin 不占用
回调执行线程；前台退出先停共享 handle、关闭本地待决答复，再尝试撤回并移除两端点。
审批 allow 不自动提供值；所有等待仍包含在原请求期限内。

SSAP stdin 管道单行上限4160字节，含换行。终端输入须少于4096字节，含换行；
达到 Linux canonical 行截断边界会拒绝，避免截短 hex 被当成成功短值。完整2042字节
值若加命令/token 达到该边界，应通过管道在实际提示后答复；预先排入的新提示前输入
会被丢弃。该输入限制不改变协议值预算。

标准 T/XS 20001-2025 §7.3 将应用层接口留给实现决定，§7.4.4.5/表51允许读取返回
上层应用错误。固定 NearLink Host `f0872dfaac33ffa99b80b352f6c05fba2df6414e` 的
`nlstk_ssap_app_server.c` 公开授权入口仅返回布尔决定；`ssaps_server.c` 的普通读取
先读取数据库并提交响应，再通知应用。内部可选值字段不是公开动态 provider 契约。
本实现据此区分授权与提供值，未将参考 Host 当作标准裁判，也不宣称完整符合性。

### Owned write-only Provider（源码接线，待新产物实机验收）

这一路径复用唯一 Engine、原 Owned 登记和同一连接的有界服务端义务队列。
它与审批回调分开：审批 `true` 不执行应用写入，也不能生成写成功。
当前提供 daemon 类型化 D-Bus 入口、Rust 低层绑定和共用 Dispatcher 的 Rust/C/Python
WRITE 收件箱；method 回调及完整长写事务仍缺失。READ Provider 的既有资格不转授这条新路径。

`ServiceManager.BindOwnedWriteProvider(handle:q, provider:o, deadline:(ttttt))->()`
仅允许原登记的 unique caller，经 `sparklink-services` 权限调用。属性须为 type0
写专用，操作位为 `0x02`、`0x04` 或 `0x06`；混合 READ/WRITE 属性不能绑定此 Provider。
未知/外来 handle、根路径、超长路径与原期限按 Owned 规则拒绝。绑定在原数据库锁下
一次提交，移除初始存储值；已绑定、重新绑定或不支持的模式返回 NotSupported。
此后本地读取/替换均不支持，没有原值回退。原绑定超时或回复丢失不能证明未提交，
不自动重试。撤回原登记仍使用现有卸载路径。

Rust `ServiceRegistration.bind_write_provider` 绑定同一 `Client::from_connection`
连接上的应用对象，不自动创建回调收件箱。应用须先导出
`org.sparklink.SsapWriteProvider.WriteValue` 并校验原 daemon unique sender；
不能把任意进程发来的 callback 当作授权。请求为单个结构体
`(t(qttqtuyyy)qtyyqayb)`：

| 字段 | 类型 | 含义 |
|---|---|---|
| request_id | t | 当前原服务端义务标识 |
| identity | (qttqtuyyy) | controller、generation、lifetime、handle、security epoch、机制、local/remote TCID、PI |
| property / deadline_ns | q / t | 原属性与单调时钟绝对期限 |
| operation | y | 12：无回复命令；13：有回复请求 |
| data_type / offset | y / q | 当前仅 0 / 0；不隐含长写或描述符支持 |
| value | ay | 原 PDU 的有界完整拟写值，最多2042字节且须满足实际协商 MTU |
| verify | b | 原请求要求回送已接受值；命令恒 false |

响应为 `(yay)`：状态0且 verify=false 必须附空数组；verify=true 必须附应用实际
接受的完整原值，逐字节不符则拒绝。`0xaf..0xff` 应用错误必须附空数组。
未知状态、错误附值、布尔答复、畸形答复、丢失或过期均不能作为成功，不截断值。
服务端只在实际有效答复后形成 WriteRsp；WRITE command 无论成功失败都不生成响应。
verify 的回送不能用方法 echo 或授权 allow 代替实际应用提交。

Engine 在请求应用副作用前重新查询 Native 身份与权限，并在完成答复前再次检查原
controller/generation/lifetime/epoch/通道和期限；当前测试传输的跳过仅存在于
`cfg(test)`。这些检查不是跨内核与应用的原子事务：应用已经执行后若撤权、断链、
退出或超时，可能不再发送成功响应，但不能宣称应用副作用已经回滚。调用者需处理
结果不确定性；不自动重放写操作。原 worker 取消会释放该义务持有的 Wire 引用，
不新增 detached worker、第二个 Session 或控制器发送路径。

固定 NearLink Host `f0872dfaac33ffa99b80b352f6c05fba2df6414e` 的
`ssaps_server_app.c` 将写操作和值交给上层回调，`ssaps_server_write.c` 按原请求的
返回标志形成应答。本项目保留该操作区分，但跨进程应用答复、原期限和撤回语义由
上述契约约束；参考行为不作为标准裁判。独立签名、实际私有 D-Bus 与生产 Engine
回归不等于内核并发证明或真实对端业务交付，新 artifact 必须单独取得 VM 实机资格。

#### SDK WRITE 收件箱

Rust `Dispatcher.bind_write`、C `slk_local_service_bind_write_provider` 和 Python
`LocalService.bind_write_provider` 使用原 Client/服务登记、原绑定期限及同一 Dispatcher。
READ/WRITE 共用16个登记槽及各槽单个待决请求，不另开 WRITE 容量池；原 authorizer
仍是独立审批。服务 stop、owner loss、绑定不确定性、通知 fd、原期限、队列唤醒和最终
引用释放使用同一前端实现，写类型只增加准入字段和实际接受值的检查。

| C | Python | 作用 |
|---|---|---|
| `slk_local_service_bind_write_provider` | `LocalService.bind_write_provider` | 一次原 owner 绑定；返回有限收件箱 |
| `slk_write_provider_fd` | `WriteProvider.notification_fd()` | 调用者持有 CLOEXEC fd，仅供 poll，不携带答复权 |
| `slk_write_provider_next` | `WriteProvider.next_request()` | 非阻塞取请求；Python 可选绝对期限仅限制本地等待，不续期原回调 |
| `slk_write_provider_request_info` | `WriteProviderRequest.info` | 原 request/context/operation/offset/verify/长度快照；不是当前授权 |
| `slk_write_provider_request_value` | `WriteProviderRequest.value` | 原拟写值的完整有界只读快照；C 短缓冲返回 ENOSPC，告知完整长度、不改缓冲 |
| `slk_write_provider_request_reply` | `WriteProviderRequest.reply(value, status=0)` | 一次本地答复，不能代替实际应用副作用或对端收到 |
| `slk_write_provider_request_free` / `slk_write_provider_free` | `request.close()` / `provider.close()` | 释放请求或停止本地准入；不回滚应用副作用，不隐含撤回服务 |

`SlkWriteProviderRequestInfo` 固定80字节、8对齐；所有 reserved 必须为0。包含原
controller、token、request id、lifetime、epoch、deadline、security level、handle、
property、offset、value_length、local/remote TCID、PI、operation、data_type、verify。
C 的非 NULL 指针仍须满足调用者内存契约，不能把调用者 UB 当作内核 EFAULT 支持。
Python `info` 冻结、`value` 为不可变 bytes，实例禁止 fork 后使用。

回复不通过同步 RPC executor，因此原 executor 等待其他调用时，本地答复不会排在其后。
status 必须是0或 AF..FF；错误携值/未知状态为 EINVAL，超原答复预算为 EMSGSIZE，
verify 的非一致接受值为 EINVAL；这些拒绝不消耗答复权。过期 ETIMEDOUT、停止
ESHUTDOWN、失去原 daemon 或旧请求 ESTALE；没有静默截断、重试或新期限参数。
同名 daemon 接任不更新既有 Client/Provider 的 owner：旧请求、注册及通知 fd 继续
绑定原 unique owner；新客户端须重新取得注册，旧请求号或相同 controller 元数据
不能恢复旧答复权。通知 fd 可因 owner 丢失而唤醒，其最后引用存活不代表权限存活。
实际 C 导出/private D-Bus 回归覆盖原 parent Client 关闭、owner 切换、旧请求 ESTALE、
新 sender 向旧端点的 AccessDenied，以及新 lifetime 只接受自己的答复。Adapter/服务
元数据为显式 fixture；这不是 slkd SIGKILL、内核清理或真实业务恢复资格。

返回0只表示本地接收了应用答复，若此后立即关闭最后 owner/bus，真实回调可能被丢弃。
测试若要求观察远端 callback，应通过实际接收屏障保持原 owner，不能用本地0或固定
sleep 假定已排空。真实 SSAP 对端业务确认仍须单独验证。

原请求释放和 callback drain 是两个条件，仍存活的任一引用都保留容量；fd 的 dup
只保留通知描述符，不能替代服务或恢复答复权。端点安装遇到已占用 WRITE 时仅移除
本次创建的 READ 接口，不删除外来对象；取消部分安装只留下已停止的有界端点，直到
原连接释放，不自动重试。同步 Client 打开失败会释放该原连接。

#### 现有验收调用者的 WRITE 模式

`tools/testing/application_client/client.c` 和 `client.py` 的
`owned-writeonly INDEX GENERATION SERVICE_UUID PROPERTY_UUID INITIAL_HEX [allow|deny|ask]`
复用原 Owned 登记、授权、poll 和清理循环；操作位固定为 `0x06`，不能冒充完整
method、描述符、动态通道或长写协议支持。运行身份来自明确参数，不再使用独立
WRITE 示例中固定的 controller/handle。测试工具不是生产服务数据库。

`provider` 通过实际 SDK 绑定，`provide pTOKEN HEX` 先将输入完整值与原拟写值比较，
相等后才答复；verify 返回接受值，其他成功答复为空。`-` 表示空值，
`provider-error pTOKEN AF..FF` 返回应用错误。错误 token/值不答复、不清除待决请求。
本地答复接受后更新该测试应用的有限内存值；`value` 单独报告它，不调用 daemon
staging 读接口。错误和过期答复不改变这个测试值；这不是通用业务副作用的回滚承诺。

`provider-unregister` 在已交付但未答复的 READ 或 WRITE 请求上沿同一服务撤回路径
停止准入，保留原请求快照和通知 fd 供观察，并实际尝试旧答复；WRITE 使用原拟写值，
防止参数校验错误掩盖应有的 `ESHUTDOWN`。`SdkWriteProviderUnregistered` 额外记录
`value_preserved`，表示原拟写快照仍可读取，不代表该值已应用。撤回后 `value` 必须
仍是之前实际接受的应用值，进程继续存活至 `quit`，正常输出 `SdkOwnedClosedExit`。
撤回和旧答复检查受原始请求及调用者期限约束；失败不得伪装成成功撤回。
实际 C/Python 私有 D-Bus 回归覆盖这条 SDK 路径；它不证明 daemon Engine、内核
取消、真实对端错误或同行隔离，后者仍需专用 VM 双端证据。
现有 runner 的 `--ssap-write-provider-unregister-verify` 复用共享 pending-case 和 guard，
独立检查双端 WRITE 错误及后续业务；见[执行契约](vm-gate-inputs.md#sdk-write-provider-待决撤回门禁)。
是否取得实机资格仍以准确编译产物与执行记录为准。

JSON 观察分别记录原请求、实际 SDK 调用与结果、接受值和应用内存值。
输入行有界，支持完整2042字节值及命令开销，不静默截断。`quit` 沿原清理路径
停止准入、释放请求/fd、撤回服务；监督器必须先观察对端结果再结束 owner。
现有 publisher 可显式选择 `write_provider=True, operations=6`；与 READ/updates
组合明确拒绝。现有 runner 已提供独立 `--ssap-sdk-write-provider-verify` 选择器及
双端 USB/SSAP 判定，范围是应用拒绝和31/32字节 verified WriteReq；见
[门禁契约](vm-gate-inputs.md#sdk-write-provider-的结果门禁)。源码/离线通过不等于
准确新产物实机通过；command、长写及待决生命周期的完整门禁仍缺，旧 READ 资格不转授。

### 显式公开的只读属性说明

`SetOwnedLocalDescription(handle:q, description:s, deadline:(ttttt))` 为原 Owned
属性设置 type1 说明。仅原 unique caller 可提交；controller、登记、管理租约及原期限
必须仍有效。说明与属性值共同占用现有 8192 字节预算，替换、删除和远端读取使用
同一数据库锁。它不分配新 handle，不改变属性值或 CPCD。

本实现接受 1..244 个 UTF-8 **字节**，禁止内嵌 NUL；244 是当前实现边界，不是标准
最大长度，NUL 拒绝来自 D-Bus String 契约。超限/空值/非法输入 EINVAL，非拥有者
EACCES，预算不足 ENOBUFS，过期 ETIMEDOUT。超时可能发生于提交之后，不能当作回滚。

说明由拥有者**显式选择公开**，远端只读，权限独立于属性值：即使属性读取需要审批
或没有 READ 位，已登记的公开说明仍可读。type1 不进入属性审批回调，也不接受
type0/type2 的批准收据。受保护说明、远端修改、动态 Provider 和其他描述符未因此开放。
已有 type2 CPCD 独立保留；发现列表可同时包含 type1 和 type2。

Rust `ServiceRegistration.set_description`、C `slk_local_service_set_description`、
Python `LocalService.set_description` 复用这一入口；成功只表示本地提交。
远端通过 `ReadSsapDescription(handle:q, minimum:u, deadline:(ttttt))->ay`、Rust
`RemoteSsap.read_description`、C `slk_connection_ssap_read_description` 或 Python
`connection.ssap().read_description` 读取。返回描述值字节，客户端验证本实现的 UTF-8
及长度契约，错误 EPROTO，不回退读取属性值。`minimum` 继续约束原通道安全要求，
不是给说明授予可信身份。缺失说明返回协议错误13，已退休 handle 错误4；不支持的
远端写入不修改说明、属性或 CPCD。原期限、请求归属、Grant 与唯一 Session 不变。

本段描述源码契约；准确编译产物的离线及实机资格分别读取唯一能力入口。


更新等待通过服务 owner 的撤销通知和调用者等待端关闭来唤醒，随后重新检查生产状态。
通知本身不授予发送权限，也不表示物理清理已完成。未准入的更新只移除自身待发工作；
已准入更新保留首片建立的排空期限，作者原期限不续期。owner 撤销时，尚未完成准入的
分片序列使该 SSAP actor 退休；已全部准入的指示继续履行有界 ACK 排空义务，退出的
作者不再收到成功结果。ACK、软件准入和对端应用实际处理继续分别表达。
调用者退出后，未完成准入的更新继续监听原 owner 撤销；全部准入且作者已退出时
停用该监听分支，保留 ACK 排空，避免重复通知导致空转。

## SDK READ Provider 原期限门禁

`--ssap-provider-deadline-verify` 复用原 VM runner，并要求
`--ssap-provider-owner-exit-verify`、READ Provider 与 Owned 基线。当前执行输出
version 2：两连接角色分别使用 Python Provider/C requester 和 C Provider/Python
requester。实际取得 SDK 请求和独立授权后不回复，分别保留 requester 调用期限、
服务端原响应期限和有界终态观察预算，不通过重新调用来延长期限。

晚答必须调用原 SDK request，返回 `ETIMEDOUT`；解析器拒绝、错 token、
`ESTALE`、`ESHUTDOWN` 或仅打印错误不能替代这个场景。Provider 保持存活至
普通 CUTC 业务完成，再显式注销。检查要求完整请求至清理窗口的双端原始捕获，
不能出现返回缓存值、迟到响应或重复请求；后续普通业务仍使用原应用校验和回复。
这不证明同一已终止 SSAP actor 恢复，也不证明物理在途义务已排空或自然恢复。

version 1 的 CLI Provider 历史报告继续按原契约读取；当前 host/guest 拒绝把它作为
SDK version 2 的执行结果。源码接线、离线 fixture、形式化和实际 VM/设备结果分开
记录，新工具名称或版本本身不授予 SDK 生命周期资格。

## 接收命令授权的原期限与终态

接收端首片建立的原期限覆盖重组、队列等待和所有者授权。当前 Engine 在服务器
义务到期后以 Failed 终止；命令没有响应，不能发 ErrorRsp 或 WriteRsp 冒充取消确认。
已有调用者再查询 `GetSsapInfo` 会得到 D-Bus `Failed`，通用 SDK 错误映射为 EIO，
不应将其当作发送端 SDK 自身期限耗尽的 ETIMEDOUT。具体原期限检查可能先发生在
actor 定时器或授权结果消费处；两者都不得修改属性、重置期限或接受晚到批准。

同一个物理 connection lifetime 不会因新 fd、重复查询或新的应用 deadline 隐式
替换 Failed Engine。显式断链并建立新 lifetime 后，沿原初始化流程重新协商。
普通 CUTC 属于同一 Native Session 的其他逻辑通道，其是否继续交付须以两端
应用校验和回复验证。SSAP actor 退出不结算 Native 已开始的提交、credit 或 NOCP
义务，也不等于完整物理清理已经完成。

## Pending WRITE original expiry gate

The optional `--ssap-write-provider-deadline-verify` VM gate reuses the existing
Provider original-deadline runner with a typed verified type0 WRITE request.
The application must receive the actual authorized request before expiry. The
requester call deadline, Provider deadline and finite terminal-observation budget
remain distinct. A late matching value must actually call the SDK and return
`ETIMEDOUT`; the application value must remain unchanged. Neither that local
error nor bounded absence of a wire response proves delivery or physical drain.

The gate records paired request USB evidence and the complete bounded response
window, then checks ordinary socket business in both connection roles. The
expired SSAP actor must remain terminal. It does not require or claim same-actor
SSAP recovery, and does not replace owner-loss, Down, long-write or natural
recovery acceptance. Historical READ deadline schemas remain unchanged. This
selector and offline tests are implementation scope; actual qualification remains
bound to its separately registered source, artifact, tools and retained evidence.

## 待决 WRITE owner 退出门禁

`--ssap-write-provider-owner-exit-verify` 是独立的 SDK/Owned 验收选择器，
复用既有 pending-case、唯一 Engine、真实 C/Python caller 和双端 USB 判定。
它以实际 verified type0 WRITE 回调为屏障，核对 controller/generation/lifetime、
request/epoch/property、完整 32 字节随机值及原期限后才终止 Provider 进程。
退出、服务移除和实际 peer 错误必须处于原请求/Provider/监督期限内；不能续期。

对端 WRITE 错误须由两端原始数据核对（AF 或 4），随后旧 handle READ 必须拒绝，
另一独立 Owned guard 必须返回其真实值，普通通道仍须完成原四轮随机业务。
进程死亡后无法查询其应用内存；不得据日志或无答复宣称应用值已回滚。
不发送伪答复，不恢复缓存值，不把策略批准、SIGKILL 或 USB 完成当作对端结果。

该选择器与其他 WRITE/READ 生命周期场景互斥；READ 历史 schema 1/2 保持不变。
源码/离线 gate 的存在不表示新产物实机通过；Down/restart、长值和完整 SSAP
生命周期仍按各自门禁验收。这里不提供新形式化或自然恢复资格。

### Engine 停止期间的待决 WRITE

连接所有者负责停止并 join 原 Engine；不能仅删除对象引用就宣布回调和 fd 已释放。
生产 `Engine::stop()` 的有界等待到期后会 abort 并 join 原任务。已退出的等待者不再
接收该任务的决策，新 lifetime 即使复用 request id 也不能接收旧回调结果。
远端 D-Bus 方法仍可能完成其副作用；停止等待和关闭 fd 不承诺撤销应用写入。

`engine_stop_drains_pending_write_without_reviving_it_or_stopping_another_callback`
直接检查该生产 stop 路径、实际私有 D-Bus Provider 回调和 OS fd 引用；同时检查独立
回调仍能返回、新 lifetime 的结果必须来自自己的答复、动态属性不退回 staging。
测试故意使用没有 graceful-stop receiver 的既有 task fixture，以覆盖 abort/join，
不会新增第二个 Engine 或把 Unix socket 当作 Native 通道。它不覆盖完整接收循环、
内核 Down、USB drain、daemon restart 或无线交付；这些条件继续由 VM 门禁验收。

### 待决 WRITE 与物理连接退出

连接会话退出与服务所有者退出具有不同作用域。`ConnectionOwner` 停止该 lifetime
的 Engine；controller 所属 Owned 注册及其 Provider 进程有自己的生命周期。
连接 Down 不能作为服务已注销、远端应用副作用已回滚或物理发送义务已排空的证据。

`--ssap-write-provider-down-verify` 沿同一回调屏障、原 typed Disconnect 和普通
用户 SDK 检查这一边界：先真实收到待决 WRITE，再断链；Provider 保持存活，
原请求在原期限内失败。v2 门禁随后在同一原期限内调用实际 SDK 的晚到答复，
分别记录本地接收或 stale/shutdown 拒绝与测试应用值；本地成功不代表远端成功。
双端完整捕获不得出现旧连接响应，最后显式清理服务。v1 历史资格没有执行这一步，
不能授予 v2 资格；daemon restart、应用副作用回滚及完整范围仍由 U#22 追踪。
测试参数与证据要求见 [VM 门禁输入](vm-gate-inputs.md#待决-write-的连接-down-门禁)。
