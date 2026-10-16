# 当前能力与资格

本页是唯一当前资格入口；[架构](architecture.md)是目标，
[唯一计划](implementation-plan.md)是待办。当前摘要从
`project/qualification-records.json` 生成或校验，不以“最新 HEAD”推断实机资格。

文档 DQ1 的误导修正、严格构建和准确4a581c5书式主题UI已取得[限定结果](../docs/evidence/documentation-dq1-and-theme-20261016.json)，
完整内容/使用链仍缺，外链限流未核实；HTML仅四类。文档结果不授予协议/安装/恢复资格，
现有Agent与数据报告仍绑定各自准确编译和执行身份。

<!-- qualification-summary:start -->
以下摘要由 `project/qualification-records.json` 生成；不以文档提交替代编译身份。

| 契约（仅所列范围） | 证据层级 | 记录结果 |
|---|---|---|
| 历史2d81/575：原期限及21组限定实机门禁 | `real_device` | `PASS` |
| 生产原期限算术：四种HZ、100检查 | `formal_bounded` | `PASS` |
| 生产安装/取消组合：unsupported，1766检查不是证明 | `formal_bounded` | `UNPROVED` |
| Agent完整权限部署与在途安装退出矩阵：仍缺 | `implemented` | `MISSING` |
| 动态多通道/四设备故障与压力全矩阵：仍缺 | `implemented` | `MISSING` |
| 自然故障根因与非人工恢复：仍缺 | `implemented` | `MISSING` |
| Agent策略离线16175：15 private-D-Bus +1生产时钟用例 | `offline` | `PASS` |
| Agent实机85cdf/db6：六模式交换角色48次应用回复 | `real_device` | `PASS` |
| 数据保持85cdf/db6：11门禁136回复/32拒绝/2严格fd | `real_device` | `PASS` |
| 正式CLI实机6385/300a：批准拒绝两角色16次对端应用回复 | `real_device` | `PASS` |
| CLI镜像6385/300a数据保持：11门禁136回复/32拒绝/2严格fd | `real_device` | `PASS` |
| 生产C codec有界fuzz：19固定+20000探索无发现（非证明） | `offline` | `PASS` |
| 独立CI Clang18 codec有界探索：artifact/源码/目标执行已核对 | `offline` | `PASS` |
| 四设备d01aa82：两组两角色80次实际应用回复及USB业务重叠 | `real_device` | `PASS` |
| 四设备d01/ff13：轮换受控断链，48次对端实际校验回复 | `real_device` | `PASS` |
| 四设备d01/d42：64次2042字节往返、队列背压及预算观察 | `real_device` | `PASS` |
| 生产CMTC编号codec：256值与16字节输入有界限定通过 | `formal_bounded` | `PASS` |
| 当前MTU/MPS协商与准入：已确认缺陷，待修复 | `implemented` | `FAIL` |

保留镜像：K `8cbf53e6a088899229d398b0673a82e8e5aed9ff`；编译 U `d01aa82ec25bd7dfa1394b0ed7678c714e60f8da`；执行工具 `d42da67fc29f2958922e30f2ef370f21d10bb1bd`。

**当前工作树整体资格：NOT_REVALIDATED；完整范围：INCOMPLETE。** 分项按各自准确源码记录。
公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。
本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见
[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。
预备/guest 工具 `d42da67fc29f2958922e30f2ef370f21d10bb1bd`；上列执行工具为 Host 校验工具，分别记录。
<!-- qualification-summary:end -->

## 四设备业务首片（限定实机通过）

编译/guest/Host工具均为d01aa82，实验内核仍为8cbf53。
[首轮原始证据索引](../docs/evidence/four-device-business-20261016.json)封存四只独立Ready、
同一slkd、两组两角色各20轮61字节随机业务，共80次对端实际校验回复。
5949包、零捕获丢包、taint0、QEMU/监督器0；两个角色阶段分别有875.963ms和
868.616ms真实USB业务交集。六项损坏证据负对照均拒绝，非独立decoder或形式化证明。

四只warm启动均观察到-110后一次warm recovery result0；保留该事实，不升级为自然
故障根因闭合或通用自动恢复资格。单组故障下同行实际业务、四设备长包压力/公平性、
动态多通道和CPCD安全仍缺。旧6385/300a长度矩阵保留准确原身份，不改写为本轮执行。

## 四设备受控断链隔离（限定实机通过）

K8cbf、编译d01、guest/Host工具ff13的[受控断链报告](../docs/evidence/four-device-disconnect-20261016.json)
记录两组轮换断链方，合计48次实际往返。同行第一阶段6次早于Disconnect、13次
晚于双Down；第二阶段分别8次、11次，仍为同一物理Session/socket应用和slkd。
5305包零丢包、taint0、QEMU/监督器0；八项损坏证据拒绝，首次无效负对照失败保留。
这只支持受控物理Disconnect隔离，USB/设备故障隔离和自然恢复仍缺；四设备长包、
压力/公平性、多通道、保护CPCD及完整socket/权限范围继续开放。无新形式化证明。

## 四设备并行长包与背压（限定实机通过）

K8cbf、编译d01、guest/Host工具d42的[并行burst报告](../docs/evidence/four-device-burst-20261016.json)
封存两组两角色共64次2042字节实际校验回复、1152个business TX片；每消息9个
有序TX PB片，两端重组匹配，软件队列阻塞/恢复有原始记录。两阶段USB业务区间
各重叠3850.196/3856.544ms，29693包零drop、taint0、QEMU/监督器0。

源端新池满拒绝26/27/28/25；8个端点/角色上下文各206提交/206NOCP、容量与峰值5、
最终debt0。这是原始捕获和采样的限定观察，不证明NOCP真实性、重复/迟到/复用屏障
或整个credit正确性；公平性、慢消费者和长期收敛仍缺。十项损坏证据在核对器中拒绝，
不是内核注入故障测试。动态多通道、真实设备故障及自然恢复继续开放。无新形式化证明。

## 已确认的MTU/MPS契约缺陷

[源码与原捕获审计](../docs/evidence/cmtc-mtu-mps-audit-20261016.json)显示：当前capability
把MTU/MPS同报2042，最大业务基础帧实际2047字节。T/XS20002-2025 §6.1/7.3.4.1
的MPS约束完整PDU；ACB254字节分片是另一层，不能替代该限额。**协商/准入契约未通过**，
需拆开SDU MTU、PDU MPS与ACB包大小并重新回归。旧64次实际回复保持其真实交付范围，
不升级为MPS协商一致或标准互操作通过；编号0codec有界安全检查也不证明此语义。

## 新内核CMTC编号修复（实机待验）

K d75f7bd修复合法identifier0被拒绝和0值pending哨兵冲突，使用显式pending状态；
新工具记录请求编号并在捕获中匹配。动态通道仍未接通，固定CUTC/SMTC限制保持。
源码/离线及有界证明不升级现有8cbf实机报告；新镜像和0编号实际交换/数据回归待验。

## 正式安全 CLI 增量（双模式限定实机通过）

正式 `slctl agent`/`security-request` 已接线到既有 broker；新增的是显式人工输入和
原作者等待/撤回，不新增协议 Engine。编译用户态6385、guest/Host工具300a已取得
[双模式实机子门禁](../docs/evidence/security-cli-real-progress-20261016.json)：批准/拒绝各交换
连接角色、合计16次真实应用往返；批准组18条真实relay及对端RX、4次角色安装/0011，
拒绝组无安全提交且后续业务成功。输入由VM测试协调器逐提示写入，非默认自动批准。
新镜像[11项数据保持矩阵](../docs/evidence/security-cli-retained-data-20261016.json)亦已限定通过：
136次往返、32次超限拒绝、两次严格最后fd；burst另见实际pool耗尽/NOCP恢复观察，
source新拒绝计数30/26。原manifest的credit_exhaustion_acceptance=false保持，
不升级为硬件NOCP可信/重复迟到/复用证明。旧85cdf/db6资格保留原身份。
默认不批准、丢失原daemon停止、EOF只注销Agent；不产生认证身份/可信Grant/Bond。

通知订阅仍缺最小安全前置：T/XS20001表40的CPCD写入要求认证及授权；
已验证的未认证SDK111机制、Agent策略批准或本地Trusted不能满足。当前继续拒绝，
不能为了通知演示放开不安全CCC。此依赖不阻塞其他数据/多通道工作。

## 范围与尚缺条件

当前数据保持镜像 K8cbf53、编译/guest85cdf、Host校验db6e333，
[11组新镜像保持报告](../docs/evidence/agent-policy-retained-data-20261015.json)
取得136次对端应用校验回复、32次超限拒绝与两个严格最后fd阶段，
61/248/249/250/253/254/255/1024/2042及已接通SSAP子路径保持。

旧[21组机制/数据报告](../docs/evidence/security-absolute-deadline-regression-20261015.json)
仍仅适用其 K8cbf/编译2d81/执行575，不能因新文档或新镜像回归重命名。
旧机制的受控批准等待不是Agent，机制40次回复不表示全部经认证或加密。

新镜像burst独立重算：源端池满拒绝增量26/25、双端容量/实际峰值5、每端每角色
206提交/NOCP、最终debt0，32次实际burst回复。原manifest的credit_exhaustion=false
不改写；这是限定观察，不证明NOCP真值/重复迟到、旧debt复用或完整提交组合。
较早 Managed/断链/原期限受控交错继续绑定各自旧镜像；不继承到新镜像。

Agent 生产入口已接通原生 submit/cancel/result；已封存的离线范围见上表与
[16项策略/实际private-D-Bus及ENOTTY报告](../docs/evidence/agent-policy-offline-20261015.json)。
[新镜像Agent六模式实机报告](../docs/evidence/agent-policy-real-matrix-20261015.json)已封存：
K8cbf53、编译/guest85cdf、执行Host工具db6e333，两角色批准/拒绝/原期限/取消/Agent退出/
调用者退出，48次普通用户对端业务回复。批准路径核对18条真实relay/18对端接收、4次
角色安装及匹配初始0011；其余模式在批准前终止、无安全wire、随后业务保持。
[退出触发边界](../docs/evidence/agent-policy-owner-loss-boundary-20261015.json)：witness分别显式关闭
实际Agent/调用者D-Bus连接，进程保持运行以核对另一角色；这是NameOwner丢失，
未验证独立进程SIGKILL/fork/继承bus fd。调用者失联不暴露旧私有终态，验证新作者ID/
旧查询拒绝/零安全wire及后续业务。
两次真实失败（旧路径解析；manifest成功但退出1）均保留，没有追记PASS。
11组原长度/分片/credit/fd保持矩阵已在同一准确新镜像完成；完整部署权限尚未验收。
这不授予认证、安装成功或Bond；此前旧镜像资格不继承。动态多通道、四设备
两组业务、SSAP 正向 CCC/通知/指示、认证身份、可信 Grant、Bond 仍不合格。
普通应用组的真实 system-bus/udev/内核授权验收仍缺；控制组 UID1000/caps0 不替代。
默认 Pair 等未支持入口明确拒绝。批准、控制器完成、协议 ACK 都不表示应用已处理。

原版111选择与上传记录不等于完整执行读回证明；147/1ff 缺包、连续 RAM 实验失败、
首次期限探针失败、形式化 timeout/unsupported 均保留。
端口2人工重插后两只 Ready 及业务恢复只恢复实验条件；自然故障根因与非人工恢复
继续开放。没有宿主实验内核或驱动测试；所有真实设备操作保持 VM-only。

## 工程资格与证据访问

资格工具批次本身未新增协议资格；Agent及数据新镜像资格按上表两个独立报告封存。现有提取生产函数的
fixture 检查不包含真实锁、分配器、引用、USB 或内核调度；当前资格配置有 UBSAN，
尚未取得 KASAN/KCSAN/lockdep/故障注入/KCOV 新调试 VM 资格。
[形式化范围与未证明项](../docs/evidence/security-absolute-deadline-20261015.json)
不因工具安装、检查数量或其他局部 PASS 升级。

原材料可能含密钥，公开站点只提供摘要与指纹；没有公开下载或异地保留保证。
本机读取权限、保留位置和重放边界见结构化记录的 `access_policy`。
`python3 tools/check_qualifications.py --mode local` 核对原件；
`--require-current` 还检查声明范围内的源码，新的 Agent 源码应拒绝继承旧编译镜像资格。
本地核对成功不是实机重放；缺失原件或 hash 不符时不能授予当前 PASS。

## CI 与历史

质量首批的历史准确CI：签名提交 `92c75cab77ee5949ea636dee6b897b413f801fae`：
[CI 38749647782](https://github.com/OpenSparklink/sparklink/actions/runs/38749647782)、
[Documentation 38749648275](https://github.com/OpenSparklink/sparklink/actions/runs/38749648275)、
[Qualification integrity 38749648556](https://github.com/OpenSparklink/sparklink/actions/runs/38749648556)
全部成功；新质量 job 只核对公开元数据，不是实机重放。
监督器原子失败保护提交 `7a9ac120c5b6` 的
[综合CI](https://github.com/OpenSparklink/sparklink/actions/runs/38750325434)、
[文档CI](https://github.com/OpenSparklink/sparklink/actions/runs/38750325402)和
[资格元数据CI](https://github.com/OpenSparklink/sparklink/actions/runs/38750325375)均成功。
后续报告格式拒绝检查使专项负对照达23项本地通过；各结果只适用其记录的工具源码，
均不覆盖后续Agent新源码或增加运行资格。
[九个issues准确读回](../docs/evidence/qualification-quality-issues-20261015.json)
保留原scope及OPEN。后续提交不能继承这条CI观察为已运行。
准确编译镜像 `85cdf627d70b` 的[CI](https://github.com/OpenSparklink/sparklink/actions/runs/38757660942)、
[文档](https://github.com/OpenSparklink/sparklink/actions/runs/38757660956)、
[资格metadata](https://github.com/OpenSparklink/sparklink/actions/runs/38757660979)通过；
Host工具 `db6e333814cf` 的[CI](https://github.com/OpenSparklink/sparklink/actions/runs/38758974428)、
[文档](https://github.com/OpenSparklink/sparklink/actions/runs/38758974409)、
[资格metadata](https://github.com/OpenSparklink/sparklink/actions/runs/38758974464)通过。
后续证据/检查器维护按自己的源码和报告记录，不替换编译镜像或实机身份。
两仓库 master 的经典分支保护 API 返回 Branch not protected，rulesets 列表为空；
不宣称 required checks 已强制执行，也不自动修改仓库策略。

[历史页面原文及冲突快照](../history/architecture/qualification-snapshot-eaea706-20261015.md)
保留原始状态，不再混入当前矩阵；[证据索引](../docs/evidence/index.md)
保留其他旧资格、失败与反例。UserHost 仍仅 P4 规划；完整 S0–S6、19 WP、10 FV、
12 DG、原 issues 和自然恢复退出条件均不变。

## 生产 C codec 有界探索（非证明）

Linux ddea575bff55 的离线[准确结果](../docs/evidence/ws73-production-codec-fuzz-20261016.json)：
固定语料19次执行加20,000次有界探索无发现，ASAN/UBSAN/LSan及六个目标生产函数实际执行
已核对；5项监督器负对照单列。沙箱LSan工具失败及前序报告保留。未新增形式化、
内核sanitizer/并发/USB/恢复资格。独立[CI artifact已核对](../docs/evidence/ws73-codec-fuzz-ci-20261016.json)：
实际Clang18、相同ddea源码、19固定+20000探索、目标函数/二进制/语料/日志hash及5负对照
分别检查；这与本机Clang22分开，不等于形式化或实机资格。较长定时探索尚无实跑结果。
