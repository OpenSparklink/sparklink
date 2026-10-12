# ADR 0002：连接会话、通道、fd 与验证契约

日期：2026-10-13。状态：目标架构采用；按下表整改，未实现项不宣称完成。
用户完整提案已合入canonical ARCHITECTURE/IMPLEMENTATION_PLAN；采用与历史状态调整见
[采用记录](../ARCHITECTURE_ADOPTION_20261013.json)。当前新K d3abbdc/Uafb5ee2的40轮短消息
及249字节资格以CURRENT_CAPABILITIES为准，不覆盖下述历史review基线。
补充 ADR 0001，不缩减 S0–S6、drivers/net/slkd 分层或历史资格。
Review 基线为 Linux4a3dc86ade58、用户态8cf052c。随后 ec67348 仅新增长度验收应用/
工具；40轮资格仍绑定 K4a3dc86ade58、编译应用4426d97、工具c259bae。
40轮及首次注册panic、最后回复关闭丢弃证据保留。新代码必须重新实机核对。

## 唯一所有权

| 对象 | 所有权及失效规则 | 当前差距 |
|---|---|---|
| Runtime | controller generation、Backend生命周期、独立命令/data credit、设备故障及票据 | canonical验证到driver提交窗口与复用屏障待整改/证明 |
| ConnectionSession | 物理connection lifetime、CMTC、能力、通道表、连接级唯一RX分流 | 当前仍由一个socket独占ACB消费；必须迁移，不能直接放开注册限制 |
| Channel | local/remote TCID、PI、模式、MTU/MPS、独立有界队列、协议关闭 | 目前仅固定CUTC31/PI241基础模式；动态/多通道未支持 |
| SocketBinding | VFS fd引用、dup/最后关闭、授权范围/失效 | 不能继续由fd析构隐式创建/重建CMTC会话 |
| slkd | 管理策略、授权、SSAP Engine/数据库、Agent、Bond、Profile | 授权撤销需内核epoch检查，不能只靠daemon属性 |

ConnectionSession 独立于应用fd。最后fd关闭释放Binding和其未提交TX，**不隐式关闭
物理连接或重建CMTC**。共享逻辑通道是否保留、关闭必须由明确的session/channel
状态决定；需要协议关闭时，实现关闭事务及迟到隔离后才能提供该操作。
同 lifetime reopen 当前未验收；固定标识1换成递增编号也不足以防止残留业务数据。
Session需保留协商上下文、接收水位与通道归属，定义重新授权/重新绑定的排空屏障。

授权目标：fd绑定KernelGrant（controller/generation/lifetime/channel + authorization
 epoch），随对应Managed授权撤销失效。撤销阻止新准入/新提交、唤醒等待者；已提交
物理义务仍保留到真实完成或明确退休屏障。新lease不复活旧fd。现实现没有该epoch，
不宣称具备此性质；在接通内核grant验证和回归之前保持授权范围整改issue开放。

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

## RX准入切片（Kf1034577ecc1，新VM待验）

阻塞recv每次正常唤醒都调用Host代次门禁，在Host→data→gate→Session→RX锁下
unlink或取得PEEK引用，这一刻线性化RX准入。不持这些锁等待或复制用户内存。
撤销先发生则禁止新取包；取包先发生则已准入copy允许完成，不能撤回已复制字节。
标准queue-tail等待在锁外注册/重查；Host未知EAGAIN未提供tail时直接返回EAGAIN。
正常DGRAM零包、PEEK/TRUNC、EFAULT、信号与有限timeout保持；不支持OOB/ERRQUEUE等
未定义接收模式。只读PEEK_OFF未接通，不承诺。Actual函数体回归和LKMM锁抽象
不替代真实release/last-control-fd/owner死亡/dup/同行隔离和完整VFS引用资格。
