# ADR 0002：连接会话、通道、fd 与验证契约

日期：2026-10-13。状态：目标架构采用；按下表整改，未实现项不宣称完成。
用户完整提案已合入canonical ARCHITECTURE/IMPLEMENTATION_PLAN；采用与历史状态调整见
[采用记录](../ARCHITECTURE_ADOPTION_20261013.json)。当前实现Kbf8663/编译用户态Udfb8636的40轮短消息、249边界与八项Grant scope门禁
以CURRENT_CAPABILITIES为准；后续工具提交独立记录，不覆盖下述历史review基线。
补充 ADR 0001，不缩减 S0–S6、drivers/net/slkd 分层或历史资格。
Review 基线为 Linux4a3dc86ade58、用户态8cf052c。随后 ec67348 仅新增长度验收应用/
工具；40轮资格仍绑定 K4a3dc86ade58、编译应用4426d97、工具c259bae。
40轮及首次注册panic、最后回复关闭丢弃证据保留。新代码必须重新实机核对。

## 唯一所有权

| 对象 | 所有权及失效规则 | 当前差距 |
|---|---|---|
| Runtime | controller generation、Backend生命周期、独立命令/data credit、设备故障及票据 | Host锁下准入与driver提交票据已接通；复用/迟到NOCP可信屏障仍待证明 |
| ConnectionSession | 物理connection lifetime、CMTC、能力、通道表、连接级唯一RX分流 | Runtime持有Session；Session worker唯一消费ACB并分流，当前仅单Channel；多通道仍待实现 |
| Channel | local/remote TCID、PI、模式、MTU/MPS、独立有界队列、协议关闭 | 目前仅固定CUTC31/PI241基础模式；动态/多通道未支持 |
| SocketBinding | VFS fd引用、dup/最后关闭、授权范围/失效 | 已与Session分离；dup共享Binding，最后关闭释放本地队列；无可靠通道关闭协议，拒绝同lifetime重绑 |
| slkd | 管理策略、授权、SSAP Engine/数据库、Agent、Bond、Profile | 内核Grant已核对全身份/方向/Managed epoch；可信安全与管理所有者死亡仍待验收 |

ConnectionSession 独立于应用fd。最后fd关闭释放Binding和其未提交TX，**不隐式关闭
物理连接或重建CMTC**。共享逻辑通道是否保留、关闭必须由明确的session/channel
状态决定；需要协议关闭时，实现关闭事务及迟到隔离后才能提供该操作。
同lifetime基本通道重绑当前明确EOPNOTSUPP，已实机验证拒绝；固定标识1换成递增编号也不足以防止残留业务数据。
Session需保留协商上下文、接收水位与通道归属，定义重新授权/重新绑定的排空屏障。

授权目标：fd绑定KernelGrant（controller/generation/lifetime/channel + authorization
 epoch），随对应Managed授权撤销失效。撤销阻止新准入/新提交、唤醒等待者；已提交
物理义务仍保留到真实完成或明确退休屏障。新lease不复活旧fd。Kbf8663已接通
全身份/方向/epoch检查、Host锁内发布及RX准入，release/最后管理fd/dup/新lease实机门禁通过；
受控broker的SCM_RIGHTS六例已通过（8f19590工具）；真实daemon死亡、可信安全与在途USB交错
未验收，整项issue继续开放。

## socket 四阶段及可靠性契约

1. `send()`成功仅表示有界软件队列准入，既不表示USB提交，也不表示远端收到。
2. USB提交/成功只能证明transport阶段；不归还ACB credit。
3. NOCP仅证明控制器报告handle/count完成。它没有generation/lifetime，也不证明
   远端应用收到。重复/迟到/准确性及复用排空屏障必须单独验证，不能默认硬件完美。
4. 业务成功由实际对端应用收到、校验并回复，原端核对完整回复证明。

基础DTAP没有本层重传/对端确认；RX可能因预算、坏帧、未绑定/关闭通道而丢弃。
当前未发布SOCK_SEQPACKET是实验消息边界接口，**不提供可靠递送承诺**，不可据此
发布为稳定可靠socket ABI。稳定类型决策：基础不可靠消息使用连接式SOCK_DGRAM；
SOCK_SEQPACKET仅在实际协商并实现可靠/有序模式后开放。迁移须复用现有真实路径、
取得准确新提交资格后移除实验类型；UAPI未发布，无历史兼容期限。

当前/目标行为需分开：当前TX最多8条，RX受socket缓冲区预算约束；未知/不支持返回
明确错误。poll OUT表示已完整协商且软件可准入，不代表空口容量；IN表示完整已排队
消息。失败/断链唤醒ERR/HUP，旧fd不重绑定新lifetime。公开ABI前补RX丢弃诊断、
各错误优先级、MSG_TRUNC/PEEK、零消息、阻塞/非阻塞和安全选项矩阵。
显式linger最多5秒等待真实软件TX提交；默认/超时丢弃未提交部分，不清除在途debt，
不承诺控制器完成或远端递送。dup遵守VFS引用；仅最后fd关闭做Binding清理。

## 整改优先级与准确问题归类

| Review | 顺序、整改及门禁 | 现有issues |
|---|---|---|
| 1 期限 | P1：明确Negotiating/Open/Failed/Closed；所有必要步骤受原始期限约束 | K6/K17/K10 |
| 2 发布 | P1：统一锁保护能力/协商/关闭快照；准入与关闭在同一锁线性化；LKMM/实际回归 | K4/K6/K17 |
| 3 session/fd | Session迁移、reopen/迟到回复/残留数据；不能只换CMTC ID | K1/K6/K17/U3/U6 |
| 4 提交窗口 | P1待证明风险：定义Driver提交线性化、可撤销票据、Down/复用屏障；未有实机串包证据 | K4/K9/K14/K17/K10 |
| 5 授权 | KernelGrant epoch随撤销失效；已提交义务不伪取消 | K5/K6/K10/U6 |
| 6 NOCP | 保留旧debt；明确有限实测范围和硬件假设；重复/晚到/复用屏障矩阵 | K13/K16/K17/K19 |
| 7 多通道 | Session唯一RX分流先接通；保持现有单消费者限制直至迁移验收 | K1/K6/K17/U3 |
| 8 socket | 实验/稳定类型、四阶段、丢包、poll/error/linger/dup/linkdown契约 | K6/K17/K19/U3/U8 |

先修复1/2和相关最小不变量，同时推进249/250及各层253/254/255、长包/PB/SAR、
credit耗尽/满队列/断链/旧lifetime；不等待全部控制面竞争排列。Session分流后再
多通道、四设备两组、真实SSAP；随后S5/S6安全/Bond/Proxy/PM/恢复/发布。

## 验证不是硬件事实的替代

| 对象 | 方法与性质 | 边界 |
|---|---|---|
| CreditLedger | Kani直接编译生产Rust纯转换：构造/归纳保持debt总和=outstanding≤capacity，独立controller、USB不退款、不确定不退款、旧debt不迁移 | NoCP真实性/来源不能作为未证硬件假设被消掉 |
| Channel/Session | TLC状态/liveness、旧回复/关闭/dup/worker引用；实际内核回归 | 模型通过不证明C/VFS映射；固定ID/reopen现缺口须保留 |
| 提交/Down/复用 | TLC票据、线性化点与复用屏障；受控VM交错 | 允许迟到/重复/失败，反例记录为风险，不冒充实机发生 |
| 共享发布 | LKMM/herd7锁或release/acquire契约；VM KCSAN/lockdep | 只加READ_ONCE不能替代同步证明 |
| Codec/重组 | C CBMC、Rust Kani；fuzz/sanitizers；有限尺寸/原期限/超限不提交 | symbolic边界、unwind和unsupported必须明确 |
| Managed/取消 | 与数据生命周期组合：唯一终态，物理义务保留，未清理不Free，设备隔离 | 不用控制面组合全集阻挡当前数据纵向开发 |
| 安全/Bond | S5 Tamarin等：未认证不可信安装，安装失败不Encrypted，拒绝旧凭据 | 不由当前数据/credit模型继承 |
| 恢复/Proxy/PM | S5/S6模型及实测：有限重试、旧gen不复活、故障隔离、崩溃收敛 | 非人工硬件恢复仍需真实验收 |

每项报告必须记录源码/模型/harness hash、性质、假设、状态/输入边界、工具版本、
准确命令、终态/反例、源码映射及回归。超时、unsupported、未完整展开均为NOT_PROVEN，
禁止计PASS。优先直接验证生产纯转换，不复制更简单验证实现；反例转成实际回归。
证明与实机资格独立集中记录，部分成果不关闭整项issue。历史自然故障及自动恢复开放。

已安装工具及当前范围见[验证入口](../../formal/README.md)：直接编译生产转换，
保留NOCP复用反例和实际ledger回归；Kani unsupported/超时不标PASS。
安装13项检查仅是工具可用性证据。Ghidra用于SDK111协议核对，Tamarin/ProVerif
随S5安全/Bond接入；不能把当前有限模型范围扩大为全系统或硬件恢复证明。

## 完整提案采用：AD-01–AD-12与提交契约

AD-01三层、AD-09用户态SSAP及AD-11可注册Backend与ADR0001一致；
AD-02/03 Session与唯一分流、AD-04 socket类型、AD-05 Grant、AD-06 Ticket、
AD-07三种流控、AD-08不确定物理义务、AD-10证据隔离及AD-12未发布UAPI迁移
采用本ADR现有契约。完整工作包/依赖只在IMPLEMENTATION_PLAN维护，不创建平行规划。

TxTicket绑定可引用Runtime/Session/Channel、controller/generation/lifetime、
Grant/epoch、reservation及不可变编码数据。提交前门禁必须与Revoke/Down有实际同步
线性化关系：撤销先发生则不得新commit，commit先发生则保留物理义务；
只读atomic标记后再无同步USB写入仍是不安全窗口。入口软件准入不替代driver commit。
明确未提交、已提交、不确定三个transport结果；不能证明零提交的失败不自动退款。
不得持registry/state锁跨USB等待、copy或cancel_sync。WP03先记录生产事件顺序表和
driver落点，FV05与受控VM交错验证同批接入；本ADR不宣称当前同步bulk路径已证明。

NOCP只有handle/count，同lifetime内重复与跨lifetime迟到分别记录硬件假设。
旧debt保留且未清算禁止复用；清算之后仍需可信排空/复位屏障。软件epoch或固定等待
不能凭空补wire身份。当前四步反例及实际ledger回归保留，没有固件来源/唯一性和
复用防护验收时FV07/DG08及相关issues保持开放。反例不是已观察实机串包。

Grant方向/安全要求及epoch由内核强制。显式Managed release、owner死亡、连接失效
和安全降级按契约撤销；fd传递/dup不扩大权限或续期，新lease不复活旧Binding。
同lifetime reopen的旧RX、PB/SAR、CMTC和TCID屏障尚缺，未接通前不得宣称支持。

Backend register/start/submit/stop/recover/RX/fault采用可引用对象及明确上下文、模块
pinning和drain回调契约；core不依赖USB=y为目标，当前源码仍待WP13迁移。
不承诺稳定Rust ABI。迁移调用者和必要回归后直接删除旧未发布UAPI/重复生产路径。

## 基础 socket 类型整改（未发布 ABI）

K4b4c6add8189将基础DTAP创建改为SOCK_DGRAM，并明确拒绝SOCK_SEQPACKET。
对应broker与应用回归使用datagram；不改变已验证CMTC/ACB编码、队列及链接身份。
本地AF_UNIX仅应用回归支撑，实际SO_TYPE/拒绝门禁及WS73回归在准确新VM中验证。
这只是类型契约迁移，不宣称可靠模式、Session/Grant/Ticket、RX丢包诊断或全部VFS
竞争已完成。K770364dcc152/U96ac968先前数据证据仍保存，不自动套用本提交。

准确K4b4c6add8189/U59479e0后续VM门禁已通过：root/ordinary DGRAM SO_TYPE、
SEQPACKET EPROTONOSUPPORT、40短/249八轮/16超限与发现连接路径。旧SSAP拒绝保持。
因此类型迁移子门禁通过；可靠模式及整个SocketBinding/Session/Grant契约仍未完成。

## ACB 实际提交点切片（K464d4d8a9de7）

Runtime/Backend引用随NativeTxTicket跨驱动准备、原子提交及等待完成保留；内核opaque
票据只在同一process线程的blocking callback存续，driver不得保存或异步重用票据。
调用顺序：driver tx_lock→ticket Host→data→scheduling gate；重新核对代次所属owner、
connection lifetime、data撤销与实际credit，驱动只在此段执行prepared
usb_submit_urb(GFP_ATOMIC)。等待、kill、callback join在Host/data/gate之外。失败未入队
才在同一锁内回滚本次预留；队列成功不退款，完成错误/超时不凭空清理物理义务。
Down/Host撤销先发布则拒绝提交；提交先线性化则保留在途义务。IRQ completion只更新
C transfer并complete，不重入Host。这是对原通用IRQ-lock约束的明确非阻塞提交例外；
禁止sleeping allocation、decode、wait或protocol callback进入此critical section。

LinuxURB API的非零submit返回未queued，零返回queued，与最终完成分开。
依据本仓库Documentation/driver-api/usb/URB.rst及[Linux USB URB文档](https://www.kernel.org/doc/html/latest/driver-api/usb/URB.html)。

Host的data撤销在revoke_connections首个Host临界区发布；只有新lease的resume条件
（无物理links、清理收敛）满足才重新开放。并未实现每Binding的Grant epoch/方向/安全
验证，也未取得全部controlled VM交错/NOCP复用屏障资格；这两个scope继续开放。
离线25 Native、10 driver故障、49 Host/12连接与48 Managed测试和限定LKMM不能代替
对应K464/U854新版本真实40短/249回归。Session迁移后续切片见下节，不放开多通道。

## Runtime-owned Session 切片（K3c8da4fac302）

Runtime拥有16个canonical lifetime/handle索引的C kref sessions。Session持CMTC/原期限、
唯一ACB消费和解码；Channel持local/remote TCID、PI、MTU/MPS和有界队列/本地关闭；
socket只持Binding ref。仍只开放基础CUTC31/PI241，不直接放开多socket竞争ACB队列。
最后VFS file关闭（dup alias不触发）撤销Binding/丢未提交TX和未读RX，Runtime会话不重启。
无合格close/drain协议前，同life基础CUTC重绑定NotSupported；不声称关闭对端逻辑通道。
RX16条及socket内存限制；TX八条包含busy skb，linger也含busy，不承诺NOCP/对端收到。
提交顺序Host→data→schedule→Session；Session访问IRQ-save，提交guard持锁，关闭先发生
不能新USB提交。不得持Session锁跨Runtime查找、阻塞I/O或cancel_sync。table mutex→Host
读取最新快照，释放后stop/join；Runtime关gate并join Session后再取native_lifecycle，防止互等。
动态TCID/关闭协议、Grant epoch/安全、NOCP/旧RX wire屏障及全refinement/KCSAN/lockdep
继续开放。K3c8da4fac302/Ud1f9dde已重新取得VM真实40短/249及dup/最后关闭拒绝重开的
子门禁；两端每端一次CMTC、实际对端校验回复与准确捕获见CURRENT_CAPABILITIES。
正常业务资格不等于受控在途关闭、完整引用或自然恢复通过。

## Lease epoch 接通切片（K3ee1a60bf06f/U2a97786）

Host IRQ锁串行化实际LeaseAuthority单调token发布/撤销；Managed acquire在copyout后、
身份/无links/清理完成核对中发布，revoke在等待process state/preparation之前失效。
Session记录不可变epoch，bind v2显式带lease；软件TX准入和真正USB ticket提交均在Host下
检查epoch，再进入Session锁，撤销先赢不准入/提交。已queued和不确定物理义务不退款。
Session worker退休并唤醒；send/recv/poll也核对代次。successor不续期旧Session/Binding。
当前仅TX|RX/security0，其他组合NotSupported；不宣称已实现完整方向授权或安全降级。
阻塞接收撤销交错、daemon死亡/最后control fd、fd传递/dup、真实隔离和完整
Grant矩阵仍待验证。Kani仅生产pure转换归纳，不证明完整VFS/Host实现或硬件。

本切片新VM正常数据保持门禁通过：40短、8轮249/16超限、dup/last-close拒绝重开、
RF22/建链断链及QMP支撑，精确U2a977 CI9/9。仅正常路径；前述受控撤销/blocked RX、
owner死亡、方向/安全和全Grant退出条件仍开放，不能以正常业务成功代替。

## RX准入切片（Kf1034577ecc1/Ud570819）

阻塞recv每次正常唤醒都调用Host代次门禁，在Host→data→gate→Session→RX锁下
unlink或取得PEEK引用，这一刻线性化RX准入。不持这些锁等待或复制用户内存。
撤销先发生则禁止新取包；取包先发生则已准入copy允许完成，不能撤回已复制字节。
标准queue-tail等待在锁外注册/重查；Host未知EAGAIN未提供tail时直接返回EAGAIN。
正常DGRAM零包、PEEK/TRUNC、EFAULT、信号与有限timeout保持；不支持OOB/ERRQUEUE等
未定义接收模式。只读PEEK_OFF未接通，不承诺。Actual函数体回归和LKMM锁抽象
不替代真实release/last-control-fd/owner死亡/dup/同行隔离和完整VFS引用资格。

本切片准确新VM已通过40短、249八轮/16超限、发现建链断链/dup子门禁，CI9/9；
实际普通应用使用nonblocking recv，这只保持正常路径，受控blocked RX撤销仍未验收。

## 受控File撤销实机子门禁（Kf1034577ecc1，tool325d377/22635f8）

两只真实SDK111 WS73，VM-only/pre-daemon，独立Managed Files。两种连接角色×
release/最后management fd/dup六用例：普通UID1000/caps0、继承fd先清理、应用data fd
自身dup/original EBADF；/proc实际recvfrom45+fd/wchan/TASK_INTERRUPTIBLE两次见证。
原管理授权撤销后blocked recv EACCES；新lease不续期旧fd，send/recv EACCES、poll ERR/HUP，
两类拒绝载荷在真实SDU捕获中为零。dup第一次管理fd关闭后另有实际双向往返。
同行原generation/Ready/Managed租约与真实scan启停保持；物理连接按清理协议实际断开，
不宣称对端物理连接仍保留。16业务往返、112双端SDU、56真实NOCP计数；无人工故障注入。
源码Runtime编译Ud570819，验收工具分325d377/22635f8，后者仅修CLI成功状态exit映射。
历史supervisor exit1留存，前两项设备及独立封存通过；没有重跑未变化设备行为。
完整Grant仍缺方向/安全、daemon死亡/SCM_RIGHTS、受控在途USB/迟到真实RX及完整VFS证明。

## Binding Grant 所有权与方向切片（Kaab814ac176b，新实机待验）

Grant存在SocketBinding，scope含controller/generation/lifetime/epoch/handle及local/
remote TCID/PI；bind发布后不可变。Channel持sock引用并在Session锁下借用同一Grant，
不复制策略。每次软件TX准入/实际USB提交、RX路由/取包与poll按方向和全scope核对。
RX-only发送在分配/复制用户内存和等待协商前拒绝；最终队列与USB仍重新验证。
TX-only/RX-only或两者有效；零/未知位EINVAL。Session CMTC不借应用TX/RX权限。
securityNONE是现有未加密语义，ENCRYPTED/AUTHENTICATED定义但未接可信状态前明确
NotSupported；不安装测试密钥或宣布Encrypted。S5接可信状态后再实现满足要求及降级。
slkd OpenChannel保留双向/NONE行为，新OpenChannelScoped(directions,security)统一路径；
invalid/protected在锁/系统调用前拒绝。当前源码回归与pure CBMC限定通过，新真实资格待验。

最终发布修复Kac9144e60012：分配/查找后在Host/data/gate→Binding→Session锁序下
重新验证租约及link identity并实际发布；撤销先发生不返回成功Binding。无阻塞操作在
这些锁内。既有release仅Binding→Session且不取得Host，借用Grant不取得Binding锁。
actual publish source fixture覆盖拒绝先发生、成功一次、重绑/退休拒绝；全锁/VFS证明未取得。

IRQ契约修正Kbf8663bb78eb：Binding查找/发布/释放均用IRQ-save，嵌套Binding与Session
保存独立flags。Host callback内不恢复BH；stock __local_bh_enable_ip要求IRQ enabled，
且可执行softirq。Kac9144完整249流水线留存但因该契约未修不授予当前资格；修正源码
actual fixture通过，仍需准确新VM回归与KCSAN/lockdep/完整锁证明。

最终精确新VM资格Kbf8663/Udfb8636：40短/249八轮与16超限，六项File撤销保持，
两种连接角色的TX-only→RX-only实际校验、反向EACCES及无载荷；invalid/protected bind
各4请求/endpoint明确拒绝。CMTC每端一次不受应用方向限制。43生产pure Grant性质
限定通过，CI9/9。单向送达不计作业务roundtrip，不宣称可信安全或全Grant退出通过。


## 多控制器共同管理所有者退出与首个错误

实际最后管理File关闭逐个发生；不能把一个slkd SIGKILL建模成两控制器授权同时原子撤销。
`Kbf8663 sle_sessions.rs::session_limits`在注册/故障/已知状态通过后，先检查Grant epoch，
再检查物理lifetime。因此活跃且已知注册中：授权已撤销返回EACCES；授权尚活跃而连接
已Down/寿命已不匹配返回ESTALE。已退休注册仍ENODEV，故障按原错误，不由新Grant重置。

实测失败收据（工具9f65ec2的首次death VM）保留：另一个controller先Disconnect，目标Down
15.288717ms，阻塞recv首醒15.417828ms/ESTALE，双方随后约93.8ms观测Free。原测试错误地
要求共同管理者退出时首醒一律EACCES，忽略合法的物理Down先行。测试82aa65a改为：
首醒若ESTALE，必须捕获本controller/handle的成功Down且早于首醒；首醒若EACCES，仍需
后续规范状态校验。双方观测canonical Ready/Free/空物理表后，每个旧fd发送与接收
必须严格EACCES、poll ERR/HUP；新slkd接任不重置注册generation，旧fd继续EACCES。
尚未完整实测通过前仅为契约/门禁接通，不宣称资格；状态见CURRENT_CAPABILITIES。

本门禁两控制器同一个slkd，双方lease撤销是预期。独立管理所有者或四设备两组的另一组
业务持续验收仍单独开放。受控daemon SIGKILL/接任也不等于自然硬件故障自动恢复。

## Backend 注册迁移决定（2026-10-13）

在真实 Native 注册与引用实现上扩展版本化描述符，不新增无调用者的平行接口。
生产 WS73 和显式 open fixture 同步迁移，旧注册符号直接删除。验证在 module/context
持引用和 Runtime 发布前执行；复制后的 ops 由已有引用拥有。未知版本/方言/bus/能力
返回不支持，声明能力与可用回调不一致返回无效，数据缓冲矛盾返回协议错误。
内核内部接口未发布，不设兼容包装。TEST provider 是测试身份，不是硬件支持声明。
标准 USB 后续必须迁同一所有权路径再删除重复 enum/binding/FFI；不得恢复孤立 serdev。
生产验证函数 CBMC 仅覆盖静态准入，合法且调用期间不变的内核指针是假设，
不从限定证明推导 get/put、注销竞态、callback join、NOCP 或自然恢复通过。

## Runtime 共同入口与锁序整改（2026-10-13）

IRQ-safe route是已安装Runtime的持引用入口，不是bus状态或Ready来源；所有注册路径
经 `sle_ingress` 发布，首次提交RX前发布，关闭gate后精确移除。拒绝未清理槽覆盖，
拒绝退休后再发布，相同Arc发布幂等；单凭同identity的另一个对象不能撤销该route。
不由worker重复publish，不把decode丢包跨设备清零。

统一顺序：Host→data→gate（数据）；Host→gate→ingress（事件）；Host→gate（命令）；
gate→routes（发布），查找释放routes后再走Host等路径，不逆向嵌套。所有嵌套IRQ guards
反序释放，schedule/kick在解锁后执行。生产8函数依赖回归与rank负对照、LKMM锁抽象
各自限定；实际IRQ保存/恢复、内核lockdep/KCSAN、Arc/workqueue/callback回收仍需VM门禁。
标准USB还需迁注册/独立资源/模块所有权、probe/setup/RX/stop与PM，未提前完成整项WP13。

最后watchdog观察者也遵守Host→gate，不能因“只读”逆序；仍不得发布Ready/credit或
产生恢复成功。实际health函数归一化仅extern签名/模块路径，依赖Host方法为fixture；
9项回归和显式锁位置语法审计不是完整IRQ/lockdep/KCSAN或自然根因证明。

## 标准USB pending与open整改（2026-10-13）

reserve身份不等于metadata/open/Ready；未知地址为零，不能使用生成MAC或由registry
构造器调用setup_complete。全局协议/binding重复表删除，counts从identity和Runtime
派生。pending_count包含退休中无Runtime的保留identity；runtime_count包含Setup/fault，
都不等于Ready数。接口未发布，同步kernel/Rust/CLI并删除旧名，36-byte布局未改。

实际USBopen在共同Backend生命周期mutex下，克隆该reservation的持引用transport
值后释放state锁，再进行listener I/O。部分失败join第一listener；退休胜出则close两者
且不发布open，generation identity保持至所有清理后释放。失败C注册不能unregister
别人的表项。完整C表资源/module引用、并发PM/callback/IRQ/真实标准USB仍须后续门禁。

双端Down异步：不能由本端Disconnect成功推断对端属性立即false。验收使用单一原始
5s观察预算和逐端真实USB Down/propertyfalse证据，限时不刷新；不是标准保证。
第一次1112ms peer Down超过旧1s期限，全轮FAIL保留，40数据子门禁与整轮资格分开。

## 标准USB引用context决策（2026-10-13）

资源属于probe allocation，registry只索引身份。不可变id/generation不作为资源lookup key；
持引用UsbDevice贯穿Runtime/controller/固件/PM，Clone获取引用，Drop释放。退休与释放分开：
io_lock串行实际操作和关准入/URB join，退休后旧引用只能失败，最终put释放USB引用与allocation。
内部locked固件入口避免递归锁。调用者必须全程持引用，API限定process context。
本批不宣称URB回调、module unload、IRQ、PM或无USB构建已证明；保持common Backend迁移门禁。
18项C依赖fixture和受控I/O/退休交错、新准确40/249业务回归仅各自范围；
原panic/最后回复丢失/1112ms Down失败及未证明Kani报告继续保留。

## 旧USB包装退出与Backend来源（2026-10-13）

实际C context是唯一USB资源所有者；没有调用者的Rust低层URB/sync API、C OUT/sync
及无注册身份回调删除。Live注册RX继续携带不可变id/generation；旧codec从默认内核
隔离，历史截断/掩码见证不得成为生产功能、长包支持或标准认证。USB模块级死代码掩盖退出。

Backend descriptor的bus是验证后的来源，必须传至保留的transport/Runtime metadata；
TEST不能因NativeController.info硬编码而报告物理USB。当前注册链遗失bus，下一批整改。
不能只放宽profile校验：标准USB先统一pending reservation/install/失败清理与RX引用，再
实际接入common Backend，删除静态分派并拆bus构建。完整module/callback/IRQ仍需门禁。

## 已接通的Backend来源与后续注册（2026-10-13）

Kc44b74509c41将验证后的descriptor bus复制到持引用transport，get/register回调之前完成；
Rust读取持引用immutable字段并在Runtime发布前验证，未知值拒绝。internal IDs不是公开bus值，
不得直接cast。USB4保持，TEST6明确非物理/非真正Virtual，name与info一致；结构布局不变。
C/Rust源回归与跨语言实际编译限定其范围，原源码TEST→USB失败见证不当作实机故障。

标准USB在bootstrap前reserve而WS73查询后register；统一生命周期必须包含早期pending身份、
失败资源与fault可见性，保持真实查询后能力和Ready，不由descriptor或open成功推断Ready。
先接通统一reserve/install/retire及真实标准方言operations，再删除静态Usb和拆bus；
module/IRQ/callback/PM、真正Virtual、自然根因/非人工恢复继续要求独立门禁。

## 共同Core预留、安装与退休（2026-10-13）

实际Native/标准USB共享reserve/install/cancel/retire。Registry只保护身份与发布；
拥有值snapshot离锁后分配Runtime，最终精确generation/退休/slot recheck才发布及更新
queried metadata/selection；失败候选在registry guard退出后析构，driver put不在该锁内。
取消只清无Runtime、未退休的精确reservation，不能删除已有或draining owner。
Native unregister复用相同detach，不由“没有Runtime”推断身份已释放。

有限TLC只检查抽象安装metadata属于当前generation，Live不是Host Ready；2 slots/2
candidates/3 generations，无fairness/liveness/allocator/refcount/module/IRQ/callback
或C/Rust refinement。Retire finish抽象join边界仍要求实机证明；弱gen反例转actual复用回归。
WS73 early bootstrap Core reservation/fault可见性仍缺，不能由这批共同Core入口宣称接通。

## Provider早期预留与诊断（2026-10-13）

C provider reserve已连接同一Core allocator。未知地址/能力不填充；pending profile/bus属于
预留来源，实际查询后register_reserved校验精确id/gen/bus/profile，不能覆盖其他或retiring owner。
Preinstall失败仍由caller持预留；若open失败已退休，则新故障记录要新identity，不能复活旧代际。

WS73 probe先reserve后work；backend_lock仅保护元数据，不跨firmware/USB/open。断开先join
producer与旧Runtime后cancel。诊断回调只更新已有代际，不能隐式reserve；显式已join fault或
有界retry才新建预留。Pending sysfs从Core查询；phase为profile定义的raw诊断，不是Ready。
普通用户runtime接口已观察8条未查询pending并同代际Ready；没有ROM/失败/callback资格。
动态slkd pending/fault对象和公开诊断接口待接，不能因sysfs可读宣称全用户管理流程完成。

## 受控早期失败隔离的实施门禁（2026-10-13）

K308e5398/编译serviceU420cc12/工具Uc07120f的三实设备VM：缺custom文件产生真实ENOENT、
Core pending phase/error而非Ready；ordinary故障选择拒绝，同行故障期间4往返；target-only
QMP移除后pending取消、新generation重新Ready、恢复后4往返且slkd未重启。
见[限定证据](../evidence/ws73-early-bootstrap-fault-isolation-20261013.json)。
这只覆盖pre-metadata失败；不证明已打开URB/部分Runtime、module/IRQ/callback清理或自然恢复。
动态pending/fault对象必须取Core权威诊断，不能自行推断Ready或以sysfs投影冒充全管理链路。

## 注册观察与Runtime Ready分离（2026-10-13）

Core registration snapshot无需fd affinity/lease，输入version1/index/可选精确generation，其余零；
输出Pending/Fault/Installed/Retiring、来源bus/profile和pending raw phase/error。40-byte/align8，
copy_to_user前释放Core锁；输出generation命名该次观察，设备可能随后移除，不授予存续或管理权。
Installed不等于Host Ready，也不暴露猜测能力；Retiring不等于Free。已安装控制器的Host故障仍来自
controller snapshot。SDK拒绝错id/gen、未知state/bus、reserved和矛盾诊断。
K9c0e616c/U71ef24d/工具Uff5ab35的ordinary真实fault/cancel/reuse及8业务往返已通过；
动态daemon对象未完成。SDK pure validator Kani限定83checks及弱gen对照不证明Core/授权/硬件。

## 注册对象与Adapter分层（2026-10-13）

RegistrationDirectory只是已发布拓扑及不可变index/gen/观察fd，无业务状态/管理lease。
Registration.GetSnapshot和Manager.ListRegistrations直接查Core；held fd/缓存/迟到通知不保活旧身份。
同路径可以在安装后增加Adapter接口；Pending/Fault不能因观察对象存在而创建Runtime/获取Managed。
每设备worker独立处理发布与移除，仅Core Installed并再次matching gen才创建Adapter；未知查询不当作删除。
SnapshotChanged按250ms观察变化提示，不保证全部中间状态；调用者重新GetSnapshot，不把通知当权威。
实机U1cccf5d已覆盖default observer/control Fault、删除、同槽新gen、旧path拒绝及同行8业务和新40/249。
不授予自然恢复、完整事件拓扑或Core/daemon lifetime形式化refinement资格。

## Provider提交句柄与metadata边界（2026-10-13）

CommandPort是当前worker独占的保留句柄，保留provider context/module（Native引用或USB私有context），
只借不可变请求字节；取得句柄不I/O，Runtime/Host/IRQ锁不跨阻塞submit。失败交回原owner的Host，
transport成功不能代替controller Complete或偿还data debt。标准路径不能无声丢弃typed connection或
厂商multi-step义务；缺实施的tag明确不支持。此切片未删除static bus分派，也非完整module/IRQ证明。
标准version5只有全部匹配成功Reset/version/MAC后提交，失败重查invalidates；immutable Rust info不
再获取USB I/O锁，Installed/identity不是Ready。buffer/features等未查询内容不宣称FULL_METADATA。
准确K0fdbcf9/Ubda960d新WS73故障8/40短/249通过；标准descriptor/能力查询及物理资格继续开放。

### 标准 Backend 能力观察的实现范围（K1f23fc2197ad）

标准bootstrap在同一I/O锁下原子提交实际0401/0402/0403/0404/0406结果，失败关闭观察有效性；
WS73厂商方言单独保留。C snapshot有查询来源，不等于应用policy、Host Ready或注册迁移。
生产Rust消费者/共同profile0/标准RX与open-close仍待接通，不能把未消费能力宣称已支持。
六查询状态转换的CBMC218仅在明确的顺序依赖边界内；[报告与反例](../evidence/standard-capabilities-formal-20261013/production/report.json)。
[真实WS73回归](../evidence/ws73-standard-capabilities-short-repeat-20261013.json)保持既有分层，
不扩大标准硬件、并发lifetime或自然恢复资格。

### 标准metadata消费者迁移（K1d6b3195484f）

完整查询观察以30-byte内部C/Rust快照一次冻结，constructor核对bootstrap身份/版本/credit；
get_version/get_capabilities被唯一get_metadata替代并删除。info/controller snapshot消费真实features/buffer，
不推断SSAP/DTAP/security policy或覆盖Host live credit/Ready/error；不等于standard common注册完成。
[限定C证明和初版构建失败](../evidence/standard-snapshot-offline-20261013.json)保留，
[准确实机回归](../evidence/ws73-standard-snapshot-v2-short-repeat-20261013.json)只授予原WS73范围。
