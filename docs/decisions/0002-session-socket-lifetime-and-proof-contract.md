# ADR 0002：连接会话、通道、fd 与验证契约

日期：2026-10-13。状态：目标架构采用；按下表整改，未实现项不宣称完成。
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
