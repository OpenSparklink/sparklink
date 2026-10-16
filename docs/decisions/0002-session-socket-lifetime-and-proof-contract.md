# ADR 0002：连接会话、通道、fd 与验证契约

日期：2026-10-13。状态：目标架构采用；按下表整改，未实现项不宣称完成。
用户完整提案已合入canonical ARCHITECTURE/IMPLEMENTATION_PLAN；采用与历史状态调整见
[采用记录](../../history/architecture/architecture-adoption-20261013.json)。当前准确实现与实机资格
以CURRENT_CAPABILITIES为准（下文旧hash只标历史审查）；后续工具提交独立记录，不覆盖下述历史review基线。
补充 ADR 0001，不缩减 S0–S6、drivers/net/slkd 分层或历史资格。
Review 基线为 Linux4a3dc86ade58、用户态8cf052c。随后 ec67348 仅新增长度验收应用/
工具；40轮资格仍绑定 K4a3dc86ade58、编译应用4426d97、工具c259bae。
40轮及首次注册panic、最后回复关闭丢弃证据保留。新代码必须重新实机核对。

## 唯一所有权

| 对象 | 所有权及失效规则 | 验收边界（当前状态只见资格入口） |
|---|---|---|
| Runtime | controller generation、Backend生命周期、独立命令/data credit、设备故障及票据 | 命令/data credit独立；实际提交、callback引用与NOCP可信复用屏障分别验证 |
| ConnectionSession | 物理connection lifetime、CMTC、能力、通道表、连接级唯一RX分流 | Runtime持有Session；唯一RX分流、固定/动态通道协商及旧回调隔离分别验收 |
| Channel | local/remote TCID、PI、模式、MTU/MPS、独立有界队列、协议关闭 | local/remote TCID独立，协商有原期限终态，关闭/安全复用须有可验证屏障 |
| SocketBinding | VFS fd引用、dup/最后关闭、授权范围/失效 | dup共享Binding；最后关闭不抹去已开始物理义务；同lifetime重绑须先验证排空屏障 |
| slkd | 管理策略、授权、SSAP Engine/数据库、Agent、Bond、Profile | 内核Grant已核对全身份/方向/Managed epoch；可信安全与管理所有者死亡仍待验收 |

ConnectionSession 独立于应用fd。最后fd关闭释放Binding和其未提交TX，**不隐式关闭
物理连接或重建CMTC**。共享逻辑通道是否保留、关闭必须由明确的session/channel
状态决定；需要协议关闭时，实现关闭事务及迟到隔离后才能提供该操作。
同lifetime基本通道重绑当前明确EOPNOTSUPP，已实机验证拒绝；固定标识1换成递增编号也不足以防止残留业务数据。
Session需保留协商上下文、接收水位与通道归属，定义重新授权/重新绑定的排空屏障。

### 安全能力交换沿用同一物理 Session

受限capability-only入口不是另一Engine，也不授予可信安全状态。管理批准必须由
内核验证原Managed File、CAP_NET_ADMIN及全连接身份/epoch，不能借用普通业务
Grant。原期限内分别记录实际提交、真实Complete和对端0014能力字节；只有后二者
均成立才发布本地观察完成。Status0、USB成功或本地批准均不足以替代它们。
授权取消/期限到期保留已提交义务，迟到回复不得复活终态。首版每物理lifetime仅一次，
拒绝同lifetime新request ID重启，直至实现并验证wire迟到/排空屏障。
只核对已知offer的实验入口不承诺通用互操作，也不替代Agent、方法选择、proof、
实际安装/加密及Bond门禁。当前代码和限定实机资格只见CURRENT_CAPABILITIES。

原期限采用调用者在Agent/策略等待前设置的CLOCK_MONOTONIC绝对纳秒值，未发布
SUBMIT同步替换为版本2/64字节，旧56字节入口删除；RESULT/CANCEL仍为版本1。
Session始终检查该原期限；Host粗粒度tick只安排清理，不充当批准有效期。内核速率
由实际timer API取得，不能用bindgen的userspace HZ。挂起时间与完整PM取消另行验收。

单请求取消与物理安全状态分离。当前File操作/Managed门序列化ioctl；Agent调用者退出
不能通过丢弃异步任务而遗失原提交结果/引用。已准入的提交必须被跟踪到可确认取消
或物理终态；取消只撤回原作者，不能释放全设备租约，也不能把已安装结果伪装成Off。
本批原期限算术限定形式化与真实等待门禁不是Agent正向接线/完整竞态/安全认证证明。

候选proof扩展复用此ledger及唯一RX归属；Session独占不导出的C密码材料，锁外
执行真实同步P-256/CMAC，回填以原job票据/身份/epoch/期限重新验证。队列只在前一
真实Complete清账后推进，特别是T公钥137与确认138。最后proof及所有本地Complete
排空才可发布未认证候选观察终态8；它不授予可信身份/加密资格。取消丢弃密码结果
并清零材料，仍保留在途命令。primitive向量、限定转换、完整协议证明与实机各自
记录；共享同一实现的两端通过不能自动升级为标准或第三方互通。

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

MTU、MPS和ACB包预算是三个契约：MTU约束SDU，MPS包含完整DTAP帧头，
ACB只约束一次控制器分片。能力响应不得用MTU填充MPS。Channel按模式帧头
收紧有效SDU预算，Session锁内同时发布两项及通道预算；最终准入与完整RX均检查。
这样长包的成功分片不会掩盖MPS违约。验证须覆盖独立能力、恰好边界及超一字节，
并保留原失败；旧对端回复不能自动成为修复后的协议一致性资格。

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

直接生产转换的序列探索从有效状态出发，再插入撤权/Down/晚到完成与提交失败；
实际callback失败次数必须与配置失败尝试分开。保留生成harness、测试二进制及
seed/操作轨迹，使用会触发指定性质失败的生产源码变异作为负对照；单纯编译失败
不算反例。USB/锁/owner/clock/consent的fixture不升级为真实内核并发或形式化证明。
受控VM延迟窗口与原协议期限是不同输入，QEMU能力需独立smoke及身份绑定。

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

### 标准USB transport与厂商FW边界复核（K6db8a530f9c6）

按本地T/XS10003-2025 §6.2/§7，USB command为EP0四字节DLI头，event为interrupt；UART/H4 marker
不能复用于此binding，bulk属于ACB。单/多功能recipient从descriptor归属选择，四字节头占用u16 wLength。
boot-ROM/FW必须由已匹配厂商driver实现；不存在可假定的通用F810/F811/A5协议。
默认旧FW删除，历史仅selftests；无Session/ticket/credit归属的标准裸handle TX/RX和未接通typed recipe明确不支持。
这项审计调整标准Backend迁移前的依赖，保留所有S0–S6/标准后端最终目标及已验证WS73，
[调用者/删除/等待替代](../../history/cleanup/standard-usb-binding-cleanup-20261013.md)与[实际证据/假设](../evidence/standard-binding-offline-20261013.json)
集中记录。限定模型/WS73回归不能替代标准USB物理与自然恢复资格。

### 共同provider实现迁移（Ka368cf5f1784）

标准和WS73在共同versioned descriptor/ops中分开dialect及software capabilities，保留上下文/安装/open-close
同一生命周期。static UsbController/enum bus branch/Core USB install-open已移除，snapshot/command/data消费者
经共同provider；standard0只query，buffers不冒充typed/data支持，未接通能力明确拒绝。
[准确实现和限定资格](../evidence/common-standard-provider-offline-20261013.json)不授予指针/refcount/module/IRQ/
真实standard或完整recovery证明。该历史版本transport/注册仍在net；后续Kae5b24535a89已迁移drivers，见下节。

### Driver/Core 构建边界落地（Kae5b24535a89）

USB context、EP0、URB、probe/disconnect归drivers；Core标准DLI codec仅处理带identity/generation/lane的
协议入口，共同Backend管理Runtime。标准模块在任何设备I/O前reserve，任何退出先按精确身份unregister/join
再释放驱动context；不能把Core退休交给对象析构猜测。PM未资格时-EBUSY，standard typed/data明确不支持。
Core取消USB=y构建依赖；[最终配置/产物](../evidence/standard-driver-move-build-matrix-20261013.json)为构建限定验收，
[空USB模块VM](../evidence/standard-driver-move-module-smoke-20261013.json)不证明物理/IRQ/PM/自然恢复。
剩余真正Virtual、统一事件及完整生命周期继续按原WP12/13推进，feature扩展后置。

### Virtual 控制 File 与物理 Runtime（K88372a9b7cbc，VM 尚待验收）

可选测试设备每次open创建一个common TEST-bus/query Runtime；dup共享控制File，最后close作为测试设备
detach，先Core精确unregister/invalidate/join，再put控制File引用。普通SparkLink fd不拥有测试设备。
close置live=false并在无driver mutex时cancel_delayed_work_sync，已捕获的callback保留原identity；
delivered计数只是callback尝试，submitted计数只是driver尝试，不等于Host结果/数据完成/对端收到。
控制参数有限，排队槽1；不带connection/data caps，不伪装WS73固件或物理恢复。
此实现复用Core生命周期；源码模型/fixture不证明真实工作队列/module引用，按独立VM矩阵核对。

### 低优先级UserHost范围调整（只规划）

[ADR0003](0003-optional-exclusive-user-host.md)定义未来互斥Host模式，WP14独立延期；本ADR现有Native
Session/Channel/Binding、Grant、ticket和资格继续有效。未来UserHost socket是controller所有权对象，
不是普通Channel socket或Native Backend；接管Grant独立、fd别名/SCM引用与lease revoke明确区分，
返Native必须真实状态屏障/新身份/重初始化，不继承connection/credit/key。本轮无UserHost实现或证明。


## DLI PB 的 Session 所有权（2026-10-15）

PB没有TCID，同连接不能按片交替发送两个Channel的PDU。首片实际USB接受时，
Session冻结该有限operation的Grant并标记begun；该标记与最后fd退役在同一锁下排序。
此前作者关闭可取消operation而无物理提交；此后缓冲区与剩余片由Session持有，
关闭fd只取消其未开始队列，不能清掉已经begun的物理义务，也不能清理另一Channel。
持续busy项计入原8项预算；后续片不持有SocketBinding裸指针，不添加新业务。

FD授权的新准入与begun operation分开。operation复制的Grant仅描述已批准的原PDU；
每片仍由Runtime检查原lease epoch/generation/lifetime，管理撤权和断链阻止新的USB
提交。它不继承新连接资格、不免除管理撤权，也不把USB成功记成NOCP或对端处理。
软件准入原期限不刷新，且在最终提交回调再检查；不确定失败不退款或重放前缀。
未开始超时只退休本Binding；真正物理失败或撤权后的部分PDU清除/复用仍待屏障验证。

实际C consent检查、worker sanitizer与VM fd退出/其他SMTC业务门禁分别记录，
不由模型通过推断完整VFS/refinement/硬件行为。基础DGRAM没有可靠业务交付承诺，
既有NOCP重复/晚到反例、全部S0–S6、共享应用完整权限/恢复条件继续开放。


## 发送预算快照的同步与权限

只读TX状态在Runtime Host/data/gate锁及随后Session锁下取得，含精确身份、
全池／connection debt及该Channel队列／游标。游标提交后的推进同样持Session锁；
不采用仅READ_ONCE／WRITE_ONCE的无依据发布。copy_to_user在锁外，失败不消费。
当前grant／Binding或协商不合格不能返回有效诊断；成功不续租、不准入业务、不改变credit。

峰值只计reservation，包含明确未提交回滚；actual池满计数与软件EAGAIN分开。
ACB完成仍由真实NOCP计账，不因查询或fd关闭清债。不向另一个Channel泄露PDU长度，
不发布新可信安全资格。实际C/Rust检查、scalar consent证明及VM观察分别记录；
此设计未证明完整锁实现、引用、内存序、USBcallback、NOCP真实性或长期调度。
原逐层交付、Managed撤权、begun物理义务及复用屏障退出条件保持。

## 固件假设与诊断版本隔离

协议包描述表、Host事件分派表及真正peer交付分别取证，不能从命令Complete推导
固件已支持某类型。形式化模型若假设类型可转发，必须绑定实际固件身份并列为环境
前提；Host模型通过不能消除固件缺表反例。实验替换现有有效表项只用于定位，不能
作为保留原能力的修复发布。原版、独立修正版和牺牲类型的诊断版资格分别记录；
当前事实只进入CURRENT_CAPABILITIES和证据索引，不将诊断通过改写成原版资格。

固件的加载前提还包括boot下载器工作区与允许的段范围，不能用运行态BSS/堆/栈布局
或文件格式上限替代。表项保留检查只证明相应字节关系，不证明下载、执行或恢复。
实际失败方案必须撤回生成/部署入口并保留反例；设备恢复未验证时明确记录，
不能继承此前原版恢复或Ready。该条件不阻塞其他controller和独立数据面工作。

## OpenHarmony DLI/HAL 参考补充（2026-10-15）

采用固定 `drivers_peripheral@879984db5c71` 作为 transport/厂商接口及 callback/关闭
语义的辅助参考；Host 协议继续核对既有 `communication_nearlink_service@f0872df`、
SDK111 与 `libws73-usb@f4d85d0`。请求返回、传输写入、控制器完成和对端应用处理仍
分别记账，不从 HDI 初始化或 onboard=true 推导原生 Ready。进程单例和 weak_ptr
不替代 per-controller 引用、generation/lifetime/epoch 与真实排空屏障。
[差异、许可证与源码身份](../explanation/openharmony-dli-reference.md)纳入原决策，
不复制框架、不新增 Engine、不改变 Native/UserHost 所有权；未来厂商 Host 适配仍延期。

## 作者撤销与物理Session引用（2026-10-15）

Session注册表按物理lifetime/handle保持唯一所有者，授权epoch是该对象的不可继承
准入条件；撤权停止作者/数据工作但不抹掉对象和异步安装义务。事件处理先取得表中
已有对象的独立kref，再核对Host/gate/实际物理身份与原epoch；不因晚到000e/0011
分配Session或授权后继lease。stop/join在表/Host/gate锁外执行。真实Down/注册退休
与作者取消不同；完整USB排空和硬件复用屏障仍需单独证明/验收。

Agent接线必须区分调用者的安全请求与controller Managed所有权：一个调用者消失或
取消不能通过释放整个租约清理其他应用。下批以类型化单请求取消接同一Session状态
转换；请求取消不声称物理加密过程已撤回，命令Status不能消除待0011的物理义务。
原期限覆盖Agent等待及后续工作；明确批准只代表方法策略，不变成认证身份或Bond。
此段定义目标契约，不声明尚未接通的Agent/单请求取消已实现。


## 动态信令接线补充（2026-10-16）

最新调用审计确认Session worker已唯一消费ACB，通道表仅固定31/241和10/0两槽。
动态单播协商仍缺；不能把可变bind参数当作对端已分配通道。下一纵向链为实际
CMTC建立/释放、单播local/remote TCID、PI/业务授权、独立有界队列及同连接双通道
实际校验回复。仍无可靠关闭/排空屏障时，不承诺同lifetime重开或复用旧TCID。

T/XS20002-2025 §7.3.3允许identifier0；旧codec拒绝0、待回复字段用0作空值是实现
缺陷，先以显式pending状态修正。自发能力请求保留0，动态请求将另分配未在途编号；
编号只是关联字段，不能替代controller/generation/lifetime/epoch、原期限和物理屏障。
以生产codec全256值及直接CBMC有界检查、实际route函数和新VM两端0编号交换验收；
局部证明不授予动态多通道或完整Session并发资格，旧实机记录不升级为新内核资格。


### 2026-10-16 动态基础 CMTC 生产接线与限定验收

K400bd6812608复用已有物理Session、唯一RX分流、ACB credit及提交票据，
不另建Host/业务Engine。未发布sockaddr v3以64字节表达显式端点/端口/AID及
独立MTU/MPS；daemon仅暂存有授权范围的端点。实际建立回复、或实际响应提交
线性化后，才在Runtime→Session锁内发布完整local/remoteTCID Grant。
应用fd、CMTC事务和物理lifetime继续分离，dup不提前关闭；最后fd撤销本应用
准入并保留已开始的Session物理义务。对端关闭可排空此前完整RX，不能准入新RX
或通过晚到建立回复恢复Grant。现有v2固定CUTC/SMTC入口保持。

首片每物理lifetime最多4个动态槽位，TCID0x80..0xdf、用户PI241..250；
已使用槽/TCID和事务号保持墓碑，耗尽ENOSPC。该有限策略避免无依据复用，
不替代后续经过证明和实测的关闭/回收屏障或完整资源长期收敛要求。端口/AID
匹配不是认证；preferred SLQI不代表已配置硬件QoS，可靠/保护模式仍拒绝。

退出门禁为准确新镜像：真实未绑定端口拒绝、两条动态通道并存、不对称TCID、
普通用户随机校验回复、关闭A后B实际继续业务、交换连接角色及原已取得数据
矩阵回归。受控暂停仅限VM应用进程且受原期限约束，不暂停内核/设备，不作为
自然恢复或公平性资格。当前有界纯转换、实际函数夹具及codec fuzz不代表门禁通过。


该接线随后在[准确新镜像](../evidence/dynamic-cmtc-real-20261016.json)取得双设备
48次动态业务与关闭同行隔离的限定证据。它仍不证明动态资源完整复用或内核并发，
准确新镜像的[14组既有回归](../evidence/dynamic-runtime-retained14-20261016.json)也已完成。
工具d14的[2042字节动态PDU及槽位拒绝](../evidence/dynamic-long-2042-20261016.json)
验证了最大基础PDU的真实分片/回复；安全复用、完整并发与其余长度仍分开验收，
不得升级为本ADR全部性质完成。
