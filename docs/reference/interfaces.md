# 接口与能力的查找入口

| 接口 | 权威来源 | 使用边界 |
|---|---|---|
| 内核 UAPI／socket | 匹配的 Linux `include/uapi/linux/sparklink*.h`，及 Rust `slk-protocol` | 尚未发布，按当前调用路径核对 |
| D-Bus | `crates/slkd/src/dbus_iface.rs` 及相关对象模块 | 观察、管理与授权分开；对象绑定当前设备生命周期 |
| C API | `crates/libsparklink/include/sparklink.h` 与生成配置 | 保持头文件、实际 cdylib 与匹配内核版本一致 |
| Python | `bindings/python/sparklink/` 与 ABI 检查 | 与文档构建的 Python 项目分开 |
| CLI | 当前构建的 `slctl --help`、`slkconfig --help` | 原生管理、离线诊断和迁移中的旧命令有不同限制 |
| 当前资格 | [CURRENT_CAPABILITIES](../../project/current-capabilities.md) | 区分源码、离线、模型、实机与未决条件 |
| 目标设计 | [ARCHITECTURE](../../project/architecture.md) 与 ADR | 不代表接口已接通 |

可选 UserHost 目前属于低优先级延期规划。旧 SSAP 业务入口的移除，也不意味着
新的用户态 SSAP Engine 已完整实现。错误和 NotSupported 行为以当前源码及资格为准。


## 本批源码核对的状态（未发布 ABI）

当前接口说明复核用户态 `8121ba0fc038` 与 Linux `8cbf53e6a088`；仅描述源码可达性和拒绝契约。实机范围按当前资格的准确提交逐项核对。

| 范围 | 当前状态与限制 | 源码定位 |
|---|---|---|
| Native 管理／诊断 | 版本化请求，controller generation／所有权检查；已实现标准 Diagnostic，限查询；准确新实机范围见资格页 | `slk-protocol/src/ioctl.rs`、内核 `sparklink_core.rs` |
| Native WS73 发现／连接／通道 | 已接通路径；实机资格仅限能力页所列准确提交及场景 | `slkd/src/connection.rs`／`controller.rs`、`libsparklink` Native API、内核 socket |
| D-Bus ServiceManager／RemoteService | 新 RegisterLocalService/ListLocalServices/RemoveLocalService/ReadLocalValue 是本地数据库操作；旧 facade 与 RemoteService 仍 NotSupported；真实远端操作走 Connection 唯一 SSAP actor | `slkd/src/service.rs` |
| 旧 SSAP ioctl | 业务命令已删除，旧编号 ENOTTY，不提供兼容 fallback；权限类型继续复用 | `slk-protocol/src/ioctl.rs`、内核 UAPI |
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
facade；D-Bus Security 方法及Encrypted/Paired属性明确NotSupported，合法RAL/RPA
输入亦NotSupported，非法输入可InvalidArgs。C旧安全入口返回-EOPNOTSUPP且不改
输出，Python映射OSError(EOPNOTSUPP)。旧 facade 的拒绝不代表新 per-Connection 安全流程缺失；现行流程如下，Bond 重连仍缺失。

### 显式 Agent 与 SDK111 限定流程

`org.sparklink.Security` 位于 `/org/sparklink/slk{index}_g{generation}/security`。
`RegisterAgent(o path, s method)` 绑定该 controller 的一个 Agent 唯一总线所有者；
仅接受 `sdk111-no-mitm`。`UnregisterAgent(o path)` 撤销原注册，普通通道权限
不授予 controller 管理或 Agent 注册权。默认不自动批准。

`org.sparklink.Connection` 的原生命周期对象提供：

| 方法 | 输入 → 输出 | 成功的含义 |
|---|---|---|
| AllocateReferenceSecurity | `u timeout_ms` → `t request_id` | 分配原调用者专属请求；1–5000ms 原始期限从分配开始 |
| BeginReferenceSecurity | `t request_id, s method` → 无 | 开始异步策略流程；不是控制器成功 |
| GetReferenceSecurityResult | `t request_id` → 观察结构 | 策略终态和原生状态分别返回，不读取密钥 |
| CancelReferenceSecurity | `t request_id` → `b` | 请求撤销；不是硬件排空确认 |

Agent 的 `org.sparklink.Agent.AuthorizeReferenceSecurity` 接收一个结构参数：
`(s connection_path, t request_id, t generation, t lifetime, q handle, y role,
y address_type, s address, s method, t deadline_monotonic_ns)`，返回 `b`。
原始期限为 CLOCK_MONOTONIC 纳秒，批准后不刷新；调用者、Agent 唯一总线连接、
注册 epoch 和完整连接引用共同约束请求。重复启动、撤销、原期限、替换 Agent、
旧身份和退出不能产生新成功。正式 `slctl agent` 提供前台逐请求人工批准/拒绝，
`slctl security-request <connection-path> [timeout-ms]` 在同一原作者连接内完成
分配、启动和查询；Ctrl-C 只尝试原请求取消。默认超时5000ms，范围1–5000ms。
这两个入口绑定原 daemon 唯一所有者，不自动跟随替换。见
[实验 VM 操作及退出契约](../how-to/request-reference-security.md)。新 CLI 的双模式限定实机范围仅见当前资格；
VM 专用 `native_security_agent_probe.rs` 是独立测试见证，不能安装为默认自动批准 Agent。

观察结构依次为 `t request_id, t generation, t lifetime, u phase, i error,
t deadline_monotonic_ns, b agent_approved, b native_admitted, u kernel_state,
i kernel_error, u kernel_flags, y kernel_status, i cleanup_error`。
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
旧56字节SUBMIT删除，不设兼容期；三种接口不能混用版本或布局。
C导出`slk_security_negotiation_submit/result/cancel`与Python NativeAdapter同步。
这是底层机制；显式 Agent 与 Connection 的 SDK111 限定流程已接线。旧 Pair／Encrypt facade 仍 NotSupported，不能用它启动新流程。实机范围见唯一当前资格入口。

原始绝对期限必须在策略/Agent等待前设置，不能在批准后刷新。`timeout_ms`为
1–5000ms剩余预算上界，实际期限仍是原始纳秒值；过期返回ETIMEDOUT，超过上界
返回EINVAL。Session的prepare/crypto/input/最终提交及查询使用同一单调时钟。
Host的jiffies仅安排清理，不延长准入；转换使用实际内核tick速率。CLOCK_MONOTONIC
不计系统挂起时间；完整PM取消/恢复仍待实现，不能据此承诺挂起期间继续安全过程。
当前新ABI/时钟改动不能继承旧56字节镜像资格。

- 必须显式选择`flags=1`（CAPABILITY_ONLY）、`2`（KEY_AGREEMENT_ONLY）或`3`（UNAUTHENTICATED_ENCRYPTION），不能组合；
  由CAP_NET_ADMIN与原活跃Managed
  File调用；其他File或降权后的同一File返回EPERM。查询同样受保护，不开放原始RX或密钥。
- generation/lifetime/request_id非零，handle为12位；精确核对role/address/type/epoch。
  timeout为1–5000ms原始总期限。仅G action2发起134、T action1先批准并回应135。
  profile/角色组合不支持返回EOPNOTSUPP；无效字段/reserved返回EINVAL；失配连接
  返回ESTALE，错误generation返回ENODEV。同lifetime再次启动返回EBUSY。
- 本批固定offer为`03 00 00 10 00 02 02 02 02 00`，不请求MITM、Bond、OOB或分发。
  只接受该已知offer，不承诺任意SDK/第三方配对互通或可信身份；模式1/2不执行安装/加密。
- result state：1批准待收、2进行中、3安装中、4能力观察完成、5失败、6撤销、7超时、8未认证候选
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
C `slk_channel_info`错误不改输出；Python `native.channel_info(fd)`用于delegated
socket，不是NativeAdapter的控制fd。32位仅C布局已验，真实compat调用仍待验收。

ServiceManager新增明确本地 RegisterLocalService/ListLocalServices/ReadLocalValue/RemoveLocalService；
Connection新增ReadSsapValue/WriteSsapValue经真实SMTC，写要求peer校验回复。
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

U514cf733aab4新增Connection.ReadSsapByUuid(start:u16,end:u16,data_type:u8,uuid:ay)，
返回逐条(handle,success,error,value)与原始请求/响应。普通用户CLI为
`slctl --adapter PATH ssap-read-uuid CONNECTION START END UUID_HEX`；数据类型为0。
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
