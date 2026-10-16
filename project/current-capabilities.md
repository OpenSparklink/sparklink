# 当前能力与资格

本页是唯一当前资格入口；[架构](architecture.md)是目标，
[唯一计划](implementation-plan.md)是待办。当前摘要从
`project/qualification-records.json` 生成或校验，不以“最新 HEAD”推断实机资格。

文档 DQ1 的[限定结果](../docs/evidence/documentation-dq1-and-theme-20261016.json)与
Ue62a770的[GitBook风格主题检查](../docs/evidence/documentation-gitbook-refinement-20261016.json)分别封存；
完整内容/使用链仍缺，外链限流未核实；HTML仅四类。文档结果不授予协议/安装/恢复资格，
现有Agent与数据报告仍绑定各自准确编译和执行身份。

应用测试唯一入口已迁为 `slktest channel`；`slctl` 保留管理/连接/授权。
[入口迁移证据](../docs/evidence/slktest-migration-20261016.json)保留原限定离线和空USB VM范围；
新编译 U9385／工具 f43 的真实 WS73 结果独立登记，不重写旧命令或身份。

schema2 的[本批限定证据](../docs/evidence/schema2-application-closure-20261016.json)包括
生产结束屏障、实际AF_UNIX报告独立核对及准确25项空USB VM回归；首次旧测试输入失败保留。
其后取得的[Native 双端基线](../docs/evidence/native-slktest-baseline-20261016.json)绑定
编译 K400/U9385、执行 f43：五次完整捕获运行共240轮实际对端校验回复（window120、
rate40、duplex80），包含普通用户凭据、双端 start/finish、准确 artifact 与两端 USB 匹配。
这是限定低负载功能/测量闭包；追踪扰动、内核资源峰值、实际 PHY/参数、稳定性能阈值仍缺。
未授予完整性能资格或新增形式化证明。

同批17次真实VM尝试为16次门禁通过、1次失败。动态249/250/253/254/255/1024/2042、
长包burst与prefix-close已在各自新目录通过，但首次253整轮因对端Down迟到仍为FAIL：
对端事件在原5秒观察截止后65.220280ms才到达。重跑不覆盖失败，不放宽期限或关闭RCA。
五次基线的1920个单RX URB空窗样本P50=7µs、P99=24µs、最大87µs，包含callback、
USBcore与VM调度；仅低负载、1µs量化。尚无证据支持优先多URB，未修改RX驱动契约。

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
| 历史d75 MTU/MPS违约FAIL保留；当前K90由独立实机回归记录取代 | `implemented` | `FAIL` |
| 生产MTU/MPS修复：直接限长与六步状态转换限定证明 | `formal_bounded` | `PASS` |
| 历史K90/U2ee固定通道：328次往返及2次在途交付（准确原身份保留） | `real_device` | `PASS` |
| 动态CMTC生产纯转换：六步有界检查与取消复活负对照 | `formal_bounded` | `PASS` |
| 双真实WS73动态双通道：48次业务、不对称TCID及关闭同行隔离 | `real_device` | `PASS` |
| K400/Ucca8既有14组回归：328次往返、32次拒绝、2次在途交付 | `real_device` | `PASS` |
| 动态2042字节与四槽预算：56次总往返，含8次动态长包 | `real_device` | `PASS` |
| 动态七尺寸/槽位门禁：392次往返、14次拒绝，原失败保留 | `real_device` | `PASS` |
| 动态C突发/真实credit：80次往返（含32次2042突发） | `real_device` | `PASS` |
| 新编译CLI重验七尺寸：392次动态往返、14次槽位拒绝 | `real_device` | `PASS` |
| 受控数据生命周期：8项撤权/Down＋2项原期限，原整轮失败保留 | `real_device` | `PASS` |
| 生产NativeTX序列探索：1024×32事件、2个指定反例 | `offline` | `PASS` |
| 事件调度/可复现socket性能与压力：待基线，未授资格 | `implemented` | `MISSING` |
| 普通socket测量工具：13+5本地CLI、20报告检查及30负对照（无性能资格） | `offline` | `PASS` |
| 应用负载AF_UNIX循环：rate/window/duplex与24+5/32负对照（非性能资格） | `offline` | `PASS` |
| slktest独立入口：空USB KVM普通用户22项应用回归（非WS73/性能资格） | `virtual_integration` | `PASS` |
| schema2应用双端核对与结束屏障：生产报告重放/空USB VM25项（非Native或性能资格） | `virtual_integration` | `PASS` |
| slktest真实双端测量闭包：5次/240往返及RX空窗（非完整性能资格） | `real_device` | `PASS` |
| 新artifact保留路径矩阵：16通过/1对端Down迟到失败，原失败未覆盖 | `real_device` | `FAIL` |

保留镜像：K `400bd6812608935e2845d6d2b80ec58e7a6a6415`；编译 U `9385c8a9124332bab09c889fccba4848cb31b19c`；执行工具 `f43a72bd1ad224f9504c491652b4586a4864143d`。

**当前工作树整体资格：NOT_REVALIDATED；完整范围：INCOMPLETE。** 分项按各自准确源码记录。
公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。
本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见
[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。
预备/guest 工具 `f43a72bd1ad224f9504c491652b4586a4864143d`；上列执行工具为 Host 校验工具，分别记录。
<!-- qualification-summary:end -->

## 当前数据子资格

[本轮准确新镜像报告](../docs/evidence/dynamic-runtime-retained14-20261016.json)绑定
K400bd681、编译用户态Ucca8a20、guest/Host工具4b33733；文档提交不是编译身份。
11组双设备门禁取得136次普通用户随机业务往返、32次超限拒绝、两次最后关闭后
在途PDU真实交付；覆盖61/248/249/250/253/254/255/1024/2042字节、长包、
分片及软件背压。四设备两组再取得80次并行业务、48次受控断链隔离业务和
64次2042字节burst往返。合计328次普通往返；关闭作者的两次交付单独计数。

所有阶段实际捕获identifier0及独立SDU MTU2042/完整PDU MPS2047广告，
业务PDU最大2047字节；ACB254字节分片与协议credit独立。
[生产代码限定证明](../docs/evidence/cmtc-mtu-mps-fix-20261016.json)另记六步转换、
13项主性质/341项有界检查及原源码变异反例。两者不互相替代。

上述实机资格仅固定基础CUTC31/PI241与SMTC10/PI0。真实peer校验回复、PB分片与软件
背压已取得上述范围资格；均不证明可靠模式、NOCP准确性/重复迟到/复用屏障、
公平性、慢消费者、长期收敛或真实USB/设备故障隔离。受控连接断开不代表自然故障。

K400/Ucca8动态CMTC的[48次短包门禁](../docs/evidence/dynamic-cmtc-real-20261016.json)
与[56次含2042字节门禁](../docs/evidence/dynamic-long-2042-20261016.json)分别记录
工具4b33733/d14c988。后者含8次动态长包往返、两次四槽预算ENOSPC，拒绝后C
仍实际回复；TX9片/RX81片重组完整2047字节PDU。它不代表所有动态长度已验收。工具8297955的249整轮发生
[监督器ENODATA失败](../docs/evidence/dynamic249-monitor-failure-20261016.json)，底层原因未查明，
该历史矩阵保持FAIL。工具45a658e采用有界子进程管道采集后，独立的[七尺寸新矩阵](../docs/evidence/dynamic-seven-sizes-20261016.json)
已通过：249/250/253/254/255/1024/2042，共392次动态往返（其中56次C尺寸）、14次
槽位ENOSPC；拒绝后C仍实际回复，交换物理角色。249字节完整PDU254为单片TX，
其余尺寸按实际两端PB重组；不假定固件RX与TX分片数相同。119个离线证据负对照
拒绝，原失败未覆盖，也没有证明TCID安全复用、完整credit或自然恢复。
同镜像固定通道burst的[补充credit观察](../docs/evidence/dynamic-runtime-credit-observation-20261016.json)
核对两角色源端新增29/25次池满拒绝，各端206次提交/206包NOCP及最终排空；32次
应用往返属于原burst，不重复计数。NOCP准确性、迟到/重复和复用屏障仍待验证。
[限定离线证明](../docs/evidence/dynamic-cmtc-offline-20261016.json)与实际函数夹具、
fuzz仍分层；[负对照字段修正](../docs/evidence/dynamic-capture-field-audit-correction-20261016.json)
保留原尾分片载荷变异输出，重新针对首片TCID/PI拒绝；真实正向证据不变。

新编译U25df09b／工具25df09b在同一K400取得[动态burst/credit限定门禁](../docs/evidence/dynamic-burst-real-20261016.json)：
80次动态往返中32次为C的2042字节突发，两物理角色均取得真实EAGAIN/poll背压、
源端新增25/26次credit池满拒绝、NOCP后恢复提交与最终排空。实际对端逐条校验
回复，两端PB重组一致，20个离线证据负对照拒绝；不证明NOCP迟到/重复及安全复用。
同一新编译用户态又[独立重验七尺寸](../docs/evidence/dynamic-burst-retained-seven-sizes-20261016.json)，
392次动态往返、14次槽位拒绝与119个负对照；不继承或重命名旧Ucca8结果。
既有14组固定通道/四设备资格仍仅属于其原K400/Ucca8产物；当前整个树和原完整范围
未通过整体验收。下一批继续提交/撤权/断链/原期限组合，未查明根因与非人工恢复开放。


U b791cfa 的综合CI、资格一致性、文档与codec bounded-fuzz均成功，
[准确运行及issues回执](../docs/evidence/dynamic-burst-issues-ci-20261016.json)另外记录。
最终工具子树与25df09b逐文件一致，完整614项重跑通过；CI/离线结果不替代上述实机证据。

[受控数据生命周期](../docs/evidence/data-lifecycle-composition-20261016.json)另记录
K400/U25df09b／工具25df：release、最后File关闭、dup、物理Disconnect各方向共8例；
原矩阵在缺少QEMU 8秒hold属性时失败，保留FAIL。经独立无USB启动核对后，两项
原5秒期限另通过：实际5片1270字节、到期后旧操作不续交，释放后5包真实NOCP。
10个成功用例先各完成2次实际业务，共20次；部分PDU交付计数为0。42个离线证据
负对照拒绝。peer lease/Ready及适用的实际扫描通过，不等于第三组业务或daemon存活。

K a474a8503637只新增selftests，不改变上述编译运行代码。其[生产函数序列探索](../docs/evidence/native-sequence-lifecycle-20261016.json)
在有效初始提交后执行1024×32事件：1957次配置失败尝试中113次真正走到原子提交拒绝，
另125次已接受后不确定失败保留debt；两个指定生产源码变异由实际测试给出种子/轨迹反例。
这属于离线fixture探索，不是Kani/TLC证明或真实内核并发。首版变异编译失败不算反例。
本批退出，继续四设备两组动态业务；完整Ticket/NOCP复用、RCA与非人工恢复仍开放。

## 安全与服务的限定范围

正式slctl Agent批准/拒绝的[16次业务子门禁](../docs/evidence/security-cli-real-progress-20261016.json)
仍绑定K8cbf、编译6385、工具300a；[六模式48次业务门禁](../docs/evidence/agent-policy-real-matrix-20261015.json)
仍绑定各自85cdf/db6身份。上述新数据回归没有重跑全部Agent/安装/取消组合，
不把旧安全资格转授新镜像。策略批准不产生认证身份、可信Grant或Bond。

当前真实SSAP ExchangeInfo、读写/发现子路径的准确范围见结构化记录和原门禁；
本地服务数据库不表示远端发布。T/XS20001表40要求CPCD写入具备认证及授权；
未认证SDK111机制、策略批准和本地Trusted不能满足。通知/指示所需安全前置仍缺，
未支持入口继续明确拒绝，不为演示放开不安全CCC。

## 尚缺与工程边界

四槽/物理lifetime墓碑只是有限策略，完整关闭/复用屏障、多通道全矩阵、
认证/Bond、安全SSAP更新、正式部署权限/兼容及发布仍未完成。
普通应用组在真实system-bus/udev/内核授权环境的完整矩阵尚缺；UID1000/caps0
的VM业务不能替代全部部署权限。单daemon管理设备也不等于独立进程故障域。

自然启动超时、重枚举失败、设备消失的根因及非人工自动恢复继续开放。
人工拔插、hub切电、QMP和注入只用于其明确实验范围，不授予自然恢复资格。
当前资格配置及插桩范围以各报告为准；尚未取得KASAN/KCSAN/lockdep/故障注入/
KCOV的新调试VM资格。生产函数夹具不包含真实内核锁、分配器、引用或调度证明。

## 历史与失败保留

历史d75的[MTU/MPS违约](../docs/evidence/cmtc-mtu-mps-audit-20261016.json)保持FAIL；
当前固定基础通道由独立K90修复/新实机记录取代。旧[四设备80次](../docs/evidence/four-device-business-20261016.json)、
[受控隔离48次](../docs/evidence/four-device-disconnect-20261016.json)、
[burst64次](../docs/evidence/four-device-burst-20261016.json)及
[旧数据11组](../docs/evidence/security-cli-retained-data-20261016.json)均保留原身份。
旧成功不能覆盖旧MPS失败，也不能因本文整理升级为新镜像资格。

本轮首个prepare的QEMU身份不一致拒绝、监督器错误地将关闭在途交付判为普通
往返失败均保留。后者按原有独立prefix契约重验原捕获，并通过缺peer/最终关闭
负对照；未重跑已通过硬件用例或放宽物理断言。原RAM诊断、缺包、首次panic、
最后回复关闭丢弃、形式化timeout/unsupported和其他失败仍见原报告；1766检查
不因工具退出0或其他证明通过变成PASS。

## 证据访问与CI

公开摘要只包含身份、范围、hash与重放说明；原材料可能含受限材料或密钥，
只在获授权的原工作区保留，没有公开下载或异地永久保留承诺。访问条件见
结构化记录access_policy及各报告materials。缺文件/hash不符不能授予当前PASS。

`check_qualifications.py`公开CI只核对元数据；local核对原件，require-current再核对
声明范围源码。历史记录故意保留旧源码，不能把整库历史的当前匹配失败当作新记录
通过，或用当前docs HEAD替换编译身份。本地匹配也不是硬件重放或独立decoder证明。

U2ee780c的[综合CI](https://github.com/OpenSparklink/sparklink/actions/runs/38843688106)、
[文档](https://github.com/OpenSparklink/sparklink/actions/runs/38843688120)、
[资格元数据](https://github.com/OpenSparklink/sparklink/actions/runs/38843687996)及
[限定codec fuzz](https://github.com/OpenSparklink/sparklink/actions/runs/38843688130)通过；
这些结果不是328次真实业务证据的替代，也不是完整发布资格。
