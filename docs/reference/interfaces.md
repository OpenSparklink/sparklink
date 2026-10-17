# 接口与能力的查找入口

| 接口 | 权威来源 | 使用边界 |
|---|---|---|
| 内核 UAPI／socket | 匹配的 Linux `include/uapi/linux/sparklink*.h`，及 Rust `slk-protocol` | 尚未发布，按当前调用路径核对 |
| D-Bus | `crates/slkd/src/dbus_iface.rs` 及相关对象模块 | 观察、管理与授权分开；对象绑定当前设备生命周期 |
| C应用fd API | `crates/libsparklink/include/sparklink.h` | 已授权通道操作；无Native管理导出，当前不含完整broker/SSAP客户端 |
| C Native API | `crates/slk-native/include/sparklink_native.h` | 显式管理/观察库；匹配libslk_native，不授予访问权限 |
| Python | `bindings/python/sparklink/` 与 ABI 检查 | 与文档构建的 Python 项目分开 |
| CLI | 当前构建的 `slctl --help`、`slkconfig --help` | 原生管理、离线诊断和迁移中的旧命令有不同限制 |
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
`slk-contract`是独立的值类型/路径/方法名契约；slkd直接依赖Native、Channel和契约，
不依赖SDK。当前Rust Client仅提供现有成员/连接观察及fd申请；通用Operation/原始Deadline/
EventStream和SSAP客户端尚未开放，future取消不承诺撤销已开始的物理义务。
内核/daemon/工具既有原期限、最后关闭和Grant规则继续执行。slktest移用SDK申请fd，负载、计时和验收断言仍在工具，业务不逐包过D-Bus。

`slk-channel::Channel`持有一个fd引用，构造只检查实际domain，**不是Ready或交付**。
`try_clone`共享同一内核binding，`into_owned_fd`明确转移所有权；关闭仍服从内核最后
引用/Grant/credit/Ticket契约。已有操作层保留query与约束SCM收发，完整高级异步接口
仍按实际实现开放。

Python默认导出仅访问要求和授权fd操作，旧`Adapter`及默认`NativeAdapter`导出已删除。
Native需显式`from sparklink.native import NativeAdapter`并加载`libslk_native.so`；应用
fd操作用`libsparklink.so`。`LIBSPARKLINK_PATH`与`LIBSLK_NATIVE_PATH`指定准确产物，
错误覆盖路径直接失败，不静默回退。两库C头/符号分别检查。**C/Python尚无完整broker、
远端SSAP或回调客户端**；不得从新库名称推导已实现所有目标API。Native旧不支持入口
仍按R4全链清单退休，不以移动文件表示整改全部完成。


## 本批源码核对的状态（未发布 ABI）

本批接口说明按WP18/R3源码及Linux `0cd4731dd3e6`核对；Native/API迁移未验收的部分不能继承17ed资格。仅描述可达性和拒绝契约。实机范围按当前资格的准确提交逐项核对。

| 范围 | 当前状态与限制 | 源码定位 |
|---|---|---|
| Native 管理／诊断 | 版本化请求，controller generation／所有权检查；已实现标准 Diagnostic，限查询；准确新实机范围见资格页 | `slk-native/src/ioctl.rs`、内核 `sparklink_core.rs` |
| Native WS73 发现／连接／通道 | 已接通路径；实机资格仅限能力页所列准确提交及场景 | `slkd/src/connection.rs`／`controller.rs`、`slk-native` API、内核 socket |
| D-Bus ServiceManager／RemoteService | 新 RegisterLocalService/ListLocalServices/RemoveLocalService/ReadLocalValue 是本地数据库操作；旧 facade 与 RemoteService 仍 NotSupported；真实远端操作走 Connection 唯一 SSAP actor | `slkd/src/service.rs` |
| 旧 SSAP ioctl | 业务命令已删除，旧编号 ENOTTY，不提供兼容 fallback；权限类型继续复用 | `slk-native/src/ioctl.rs`、内核 UAPI |
| 旧 property／write facade | property 超 248、write 超 252 字节拒绝；这是遗留输入校验，不是新 Engine MTU 承诺 | `slkd/src/service.rs` |
| Profile／transport 实验 | 独立 `slk-experimental`；不构成默认生产能力 | 实验 crate README、构建 feature |
| UserHost／厂商 Host 适配 | P4 规划，接口／实现／证明／实机均未完成 | ADR 0003 |
| 新用户态 SSAP Engine | 唯一用户态actor的ExchangeInfo、单值读写、UUID/结构发现已接线；发送通知/指示、CCC与长写仍缺；准确资格仅能力入口 | 唯一实施计划 WP08、准确能力入口 |

C 头、Rust FFI 和 Python 绑定应匹配准确源码，不能根据函数声明推导硬件支持。本表是状态查找参考，完整资格仍仅维护于能力入口；逐字段自动生成 API 及全错误矩阵尚待下一批。

旧0x82 DLI poll、Raw256类型、Rust EventReceiver/poll/next_event、C slk_poll_event及Python旧Adapter.poll_event已删除，无兼容期。Python NativeAdapter.poll_event是现有非消费ControllerEvent路径，名称相似但契约不同；monitor的--legacy不再接受。详见当前资格与三类审计。

旧read(2)／44字节队列及0x70/0x71统计接口已删除。当前ControllerEventGet按每注册游标提供完整记录，失败copy不推进readiness；snoop保留独立权限。slctl events／D-Bus GetControllerEventPosition返回(index,generation,sequence)，来自实际LinkSnapshot.event_seq，不能解释为pending、delivered、ACK或完整resync屏障。

[Controller 事件字段、错误及删除入口](controller-events.md) 给出本批逐接口核对；完整 API 迁移仍未完成。

Netlink v2 核对 K `7c6d530ffe2e`／U `ffc0945dfdac`：仅注册数量和软件版本，
无 controller 控制或事件 multicast，请求多余属性返回 EINVAL。旧命令 EOPNOTSUPP。
它不报告 Ready、连接或固件能力；详见[实际迁移证据](../evidence/genl-retirement-progress-20261014.json)。

PM与统计核对K `43e55d59fe95`／U `1dedbad3d41e`：默认软件PM与全局模式删除；
PM ioctl／configfs不支持，D-Bus PM明确NotSupported。`slctl stats`改为实际
GetLinkSummary，Unknown失败；旧混合内核统计尚待迁移，不能当Native状态权威。
[准确子门禁与未决](../evidence/power-retirement-progress-20261014.json)。

K `5582a10c5ec8`／U `cd77ed935740`：旧连接／发现／角色／AFH/sync模型不编入默认内核，
53旧入口明确拒绝，混合SubsysStats删除。角色按实际connection查询；两CLI统计使用已知LinkSnapshot。
[准确消费者迁移、失败与范围](../evidence/protocol-state-retirement-progress-20261014.json)。

K6f2f71298029 的默认Runtime不再包含旧安全/RPA模型。新版SDK拒绝旧安全/隐私
facade已删除（Rust/C/CLI/SDK旧类型同步），D-Bus Security只保留Agent登记/撤销；旧方法UnknownMethod、Encrypted/Paired为UnknownProperty。合法RAL/RPA
输入亦NotSupported，非法输入可InvalidArgs。C旧安全入口返回-EOPNOTSUPP且不改
输出，Python映射OSError(EOPNOTSUPP)。旧 facade 的拒绝不代表新 per-Connection 安全流程缺失；现行流程如下，Bond 重连仍缺失。

### 显式 Agent 与 SDK111 限定流程

`org.sparklink.Security` 位于 `/org/sparklink/slk{index}_g{generation}/security`。
`RegisterAgent(o path, s method)` 绑定该 controller 的一个 Agent 唯一总线所有者；
明确接受 `sdk111-no-mitm` 或 `sdk111-numeric-comparison`；未知方法不降级。`UnregisterAgent(o path)` 撤销原注册，普通通道权限
不授予 controller 管理或 Agent 注册权。默认不自动批准。

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

旧未接通facade仍NotSupported。数据库配置不是远端发布；原始门禁及安全/失败
语义见准确资格和证据，不转授为完整服务支持。

后续U8438594收紧本地注册：仅READ/WRITE_WITH_RSP（mask0x05）接通，
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

### 单次本地更新观察（U8e92f97；不是远端订阅）

Connection.ObserveSsapIncoming(handles:aq,modes:y,wait_ms:u)返回(indication:b,raw:ay)。
1..32个唯一非零handle、modes1通知/2指示/3两者、wait10..10000ms；InvalidArgs拒绝
非法参数。必须有本lifetime实际发现的property及匹配Notify/Indicate能力，缺少时
NotSupported。只允许一个call-owned等待者；busy、原期限、caller退出、Actor失败
或断链为Failed，不静默成功。CLI为`ssap-observe CONNECTION HANDLE [notify|indicate|both] [WAIT_MS]`。

本地兴趣不写CCC。D-Bus owner-loss匹配先于owner检查/等待安装，已知调用者退出
撤销等待。完整property packet原子交给一个oneshot接收槽；没有持续订阅/多应用
router，满槽没有承诺无丢包。NTF不产生回复；IND只有活接收槽接受后ACK1，未知、
过期、不匹配或不支持事件ACK0。ACK1不是CLI处理成功；确认发送仍受原物理期限。
多条同handle实例、分包和事件投递未支持；malformed packet当前失败SSAP actor。
真实正向更新/TX/CCC/security尚未验收。仅原路径回归与能力拒绝有实机证据。


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

`ObserveSsapIncoming` 是本地限时接收兴趣，既不是远端CPCD写入，也不保证应用处理。
远端配置、生产通知发送与指示确认账本仍未接通。标准T/XS20001-2025表40对CPCD
写入要求认证和授权；`sdk111-no-mitm`和Agent同意均不足以满足，当前拒绝保持。
只读写公开值的历史资格不能升级成通知订阅、安全或Profile资格。配置须由唯一
ConnectionSession按物理lifetime独立持有，不按可复用handle或地址继承。

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


## 通用卸载的配置保留边界

`make uninstall` 保留管理员配置和状态目录，包括配置子目录及其symlink，不自动清除
历史元数据。实际Makefile已在临时DESTDIR回归；这不是干净VM安装、服务启动、升级、
回滚或外部C/Python消费者资格。PREFIX/服务路径、共享库命名/SONAME和pkg-config
仍在整改，不能据此推荐通用安装已可投入使用。实验bundle与通用安装资格分别记录。


## 地址观察缓存（R2源码整改；实机资格按准确产物）

Device是按地址的兼容观察对象，不能代替含地址类型的Peer或connection lifetime。
每controller上限128条，名称/广告/UUID/path的实际容量合计64KiB；单名称256字节、
opaque广告2048字节。超限拒绝整个更新并计数，不静默截断。Pending和Retiring也占
预算；容量压力使最老的无当前连接观察进入Retiring，确认移除前不接收替换条目。
无新报告60秒且没有已知canonical连接引用时退役；已连接观察可保留，过期的广告值
仍会失去有效性。Raw native_reports环与Typed Peer/Connection保持各自职责。

GetDevices只列Published。Device.ObservationValid表示该广告观察仍在60秒预算内且
对象已确认发布、确有广告而非仅连接别名、controller仍在；不是连接成功、当前空口可达、授权或安全等级。
缓存值需结合有效性读取；连接观察仍依据ConnectionKnown/实际typed快照。
Adapter的ObservationCount、ObservationBytes、ObservationDrops、ObservationPublicationErrors、
ObservationRetirementErrors为RO计数，包含pending/retiring占用。上述动态属性声明
EmitsChangedSignal=false；客户端须禁用对应属性缓存或直接调用Properties.Get，
不承诺未经发出的变化信号。动态zbus Proxy默认不会自动按服务端注解禁缓存，不能
把其缓存值当新观察；共享客户端必须固定这项策略。原错误假设的回归失败日志保留。

现有EventTask每轮最多8项与同一100ms本地维护期限，既有1秒tick重试/清理；这不是
协议期限或硬件恢复策略。失败保留占用，不能靠重复缓存插入宣布发布成功；记账锁竞争时不释放slot，下一轮
重新核对实际对象，诊断日志记录未确认结果，错误计数只计已记账失败。foreign
对象不被收编或删除。数量/字节是资源上限，不承诺所有报告都进入观察列表。数据
通道、Managed权限、扫描租约与实际业务交付资格不由这些观察计数决定。
