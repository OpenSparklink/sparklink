# 当前能力与资格

当前选择的功能子资格是[唯一 SSAP 属性访问与主动请求限制](../docs/evidence/ssap-attribute-access-20261017.json)：
准确 Linux `1bcb1cd84530`，编译用户态 `d4a13e941aef`，执行工具 `49a648826e42`。
编译用户态与执行工具提交间的 crates/data/Cargo 输入相同；runner 修复 guest 清单。
报告提交不替代编译身份。
编译 `9fd74a18a19e` 的生命周期首轮因新判定器错误要求相同errno而FAIL，原件保留；
修正工具 `8362502` 按生产检查阶段及逐调用单调时钟重跑，完成前不授整批资格。
上述资格仍仅限原 SDK111/Hi3873U 第2/3口。用户现要求统一1.10.110，已分别校验
SDK e/us 输入；第1口 Hi3873E 已授权独立测试，尚无本批实机资格，不继承四U资格。
HCC 自动型号查询及真实平台长度修复已实现于 Linux `f887b477f085`；严格构建及
942生产函数检查、ASan/UBSan通过。首个110 E实机因平台分配长度EPROTO失败保留；
观察到实际下载及型号回复，修复后新VM资格仍待取得。
正在进行的 SDK111 重跑在当前 VM 收尾后中止；保留所有子结果，不算整批通过。

| 范围 | 当前限定结果 |
|---|---|
| 原 RX 机制检查普通读、UUID读及写值；主动请求固定原 fd/epoch/期限 | 已实现，唯一 Engine，无 raw-send 回退；本地授权注册仍 NotSupported |
| 六组实机，各交换连接角色 | 72属性案例：36成功、36协议拒绝且原值不变；288远端操作双端USB匹配；44主动意图及72注册拒绝 |
| 既有真实路径回归 | 48次随机业务回复、96条RX上下文、96组原SSAP对端核对、249边界16拒绝、完整2042往返8次；广播扫描/建链断链保持 |
| 离线 | 713冻结工具、48封存共享库/跨语言（32位仅布局）、83protocol/92daemon/28slktest及入口/启动、严格all-features clippy；六原件重放、192复制证据负对照 |
| 形式化 | 生产constraint/Grant CBMC168及三负对照仅单快照有界通过；生产access Kani七性质/87低层检查虽成功，工具编译诊断保留，整体未证明 |
| 仍缺 | 本地属性授权/CPCD、命名身份/Bond、受保护更新、实际排队后撤权/rekey/off/最后fd/dup/Down/原期限/物理前缀组合、完整SSAP及所有原整项范围 |

第一轮缺 guest 模块的实机 FAIL、错误 fixture/路径/锁定输入、沙箱限制及工具诊断
均保留原件，不被后续成功覆盖。SDK111 数字比较等级2不是命名身份/Bond或独立RF证明；
USB/NOCP/协议ACK不是应用处理。旧 U331 晚 Down FAIL 和旧13快速反证继续保留，
根因未闭合；自然启动/重枚举/消失及非人工恢复继续 OPEN。完整 S0–S6/19WP/10FV/12DG
没有缩减，当前整体仍 NOT_REVALIDATED/INCOMPLETE。

本批是相关功能切片退出，不能关闭整项 issue。下一批补当前路径的受控撤权/断链/
原期限交错及原物理义务，接同一 Engine 的本地授权与受保护服务更新；数据/credit/
多通道/四设备/可信性能和旧清理并行，不等控制面全集。UserHost 仍 P4 规划。
精确历史源码、失败和限定通过由以下结构化记录及[证据入口](../docs/evidence/index.md)
维护；移除先前叠加的“当前进度”文字不改写原报告或 git 历史。

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
| a0/3f10受控未完成PDU：release/最后管理fd/dup/Down/原期限双向10项 | `real_device` | `PASS` |
| a0/f355原保留矩阵：15通过/1前缀前提失败/9未运行，原失败保留 | `real_device` | `FAIL` |
| a0唤醒限定依赖验证：46生产fixture、CBMC300有界、TLC117649状态 | `formal_bounded` | `PASS` |
| bfaa事件/原期限：32项双WS73数据与生命周期限定门禁 | `real_device` | `PASS` |
| bfaa生产调度：20步CBMC301与32/64位期限各28检查 | `formal_bounded` | `PASS` |
| bfaa原32项矩阵：14通过/1前提前缀失败/17未运行 | `real_device` | `FAIL` |
| bfaa/2451实机工具误读ACTIVE失败保留，不改内核契约 | `real_device` | `FAIL` |
| bfaa/e34逐消息测量：窗口1/4与xHCI开关12项480往返（非完整性能） | `real_device` | `PASS` |
| 073首次窗口1：40次业务但trace请求/实际容量误判，原整轮FAIL保留 | `real_device` | `FAIL` |
| Hi3873U端口2/3：新工具双向十项生命周期与受控撤权屏障 | `real_device` | `PASS` |
| 型号更换后中止初始1/4矩阵：保留监督器中断与两项子结果 | `real_device` | `FAIL` |
| c4连续TX首批：双U三项48次真实业务，完整P2d未退出 | `real_device` | `PASS` |
| c4实际Rust48及C dispatch/enqueue依赖fixture | `offline` | `PASS` |
| c4生产预算12步69检查及排队/期限/游标限定证明 | `formal_bounded` | `PASS` |
| c4空USB启动与签名模块，仅虚拟集成 | `virtual_integration` | `PASS` |
| c4完整P2d：trace/生命周期/公平性/成本仍未证明 | `real_device` | `UNPROVED` |
| 首批burst缺16轮参数：启动前拒绝，原矩阵FAIL保留 | `real_device` | `FAIL` |
| c4双U：release/最后管理fd/dup/Down/原期限十项新实机门禁 | `real_device` | `PASS` |
| Session实际阶段与USB关联：新e08长包32次业务，零丢失限定通过 | `real_device` | `PASS` |
| 旧8a7长包追踪溢出9147条：原整轮FAIL保留 | `real_device` | `FAIL` |
| Session追踪成本/PDU公平/同配置性能仍未证明 | `real_device` | `UNPROVED` |
| c4动态七种长度：448次业务，整矩阵burst失败另列 | `real_device` | `PASS` |
| 动态burst最终物理debt未在窗口排空：原整轮FAIL | `real_device` | `FAIL` |
| 动态关闭排空屏障与完整公平/成本：仍未证明 | `real_device` | `UNPROVED` |
| 双真实短长通道：72并发＋8基线，有限交错进展 | `real_device` | `PASS` |
| slktest实际27测试ELF、669工具与严格clippy | `offline` | `PASS` |
| 已准入队列公平上界、关闭排空与性能：未证明 | `real_device` | `UNPROVED` |
| 14d9/42e动态burst：80＋8真实回复，受控关闭观测 | `real_device` | `PASS` |
| Session只读接口：生产C/Rust/跨语言与671工具限定检查 | `offline` | `PASS` |
| 物理callback/ref drain、复用、公平及性能：未证明 | `real_device` | `UNPROVED` |
| 14d9/42e：七长度/并行/十生命周期，552次真实回复 | `real_device` | `PASS` |
| 18份原件重放及172实际证据负对照 | `offline` | `PASS` |
| 物理callback/ref drain、复用、公平及性能：未证明 | `real_device` | `UNPROVED` |
| 同U42/f2的bfaa/14d9：十二有限负载，2560次真实回复 | `real_device` | `PASS` |
| Native可变负载：673工具、16实际重放及192证据负对照 | `offline` | `PASS` |
| 完整性能/观测成本/内核峰值/公平/恢复：未证明 | `real_device` | `UNPROVED` |
| SDK111真实回复选择器：实际callback sanitizer与暂停QMP（非实机） | `offline` | `PASS` |
| 历史aa0d636离线阶段：当时安装在途实机未运行；新U6166仅限定取消通过 | `real_device` | `UNPROVED` |
| K14d9/U6166：安装在途原请求取消两角色与三项保持，32次真实回复 | `real_device` | `PASS` |
| U6166：681冻结工具/严格clippy/2Rust、六历史重放及15实际证据负对照 | `offline` | `PASS` |
| 历史两次工具接线失败：init漏传及普通目录拒绝，原FAIL保留 | `real_device` | `FAIL` |
| 完整安装lease/fd/Down/期限与迟到后物理义务、认证/恢复：未证明 | `real_device` | `UNPROVED` |
| K323/U862：数字比较六门禁与三项路径保持，48次真实回复 | `real_device` | `PASS` |
| K323/U862：34转换/272Rust、684及685工具、54真实证据负对照 | `offline` | `PASS` |
| K323：实际crypto材料/数字向量及无USB签名模块VM | `virtual_integration` | `PASS` |
| 历史数字批次解析器/CI/环境失败：保留FAIL不升级 | `offline` | `FAIL` |
| 历史U862完整安全范围未闭合；后续b873限定Agent另记，等级/Grant/Bond仍缺 | `real_device` | `UNPROVED` |
| K323/Ub873：数字Agent六角色与三项保持，48次真实回复 | `real_device` | `PASS` |
| Ub873：生产privatebus/ENOTTY、688/689工具及38实际证据负对照 | `offline` | `PASS` |
| 历史私有重放输出元数据错误：原FAIL保留 | `offline` | `FAIL` |
| 安全等级/可撤销Grant/Bond、数字CLI与完整生命周期/恢复：仍缺 | `real_device` | `UNPROVED` |
| K6861/U13bb：32当前机制快照、48真实回复及两项长度保持 | `real_device` | `PASS` |
| 34状态/51入口/14link、跨语言与31实际证据负对照，准确13bb CI | `offline` | `PASS` |
| 实际安装/取消/当前机制Kani：unsupported，未证明 | `formal_bounded` | `UNPROVED` |
| 历史私有准备/见证所有权/沙箱失败：原FAIL保留 | `offline` | `FAIL` |
| 实时失效矩阵、安全Grant/SSAP消费及完整原范围：仍缺 | `real_device` | `UNPROVED` |
| K619/U73：固定安全epoch Grant，16真实受保护回复与20等级拒绝 | `real_device` | `PASS` |
| 53实际入口/Session sanitizer、279Rust、跨语言及39真实证据负对照 | `offline` | `PASS` |
| 生产纯Grant helper：CBMC79检查与三负对照，限定通过 | `formal_bounded` | `PASS` |
| 实际锁/引用/USB/credit/撤权/晚到/复用组合：未证明 | `formal_bounded` | `UNPROVED` |
| 原构造器/路径/fixture/LSan/证明监督器失败保留 | `offline` | `FAIL` |
| 受保护实时失效/SSAP消费者及完整原范围：仍缺 | `real_device` | `UNPROVED` |
| K619/U73普通通道十项生命周期：受保护矩阵不继承 | `real_device` | `PASS` |
| K619/U390：两等级两端20项受保护通道生命周期，48真实回复 | `real_device` | `PASS` |
| K619/U390：受保护249边界及完整2042双角色16回复 | `real_device` | `PASS` |
| 701冻结工具/42新共享库ABI/20重放360负对照；原失败保留 | `offline` | `PASS` |
| 实际锁/引用/提交撤权晚到与复用组合：未证明，无新形式化运行 | `formal_bounded` | `UNPROVED` |
| 原c51首个真实受保护release整轮FAIL：命令核算缺口 | `real_device` | `FAIL` |
| 唯一SSAP安全消费者与完整S0-S6/恢复等原范围：仍缺 | `real_device` | `UNPROVED` |
| K619/U331：唯一受保护SSAP首次绑定，两等级两角色32组读写及16 CUTC回复 | `real_device` | `PASS` |
| 干净331/f46：90daemon与704工具、准确CI及完整SMTC离线核对 | `offline` | `PASS` |
| U331默认短包整轮FAIL：对端Down超原5秒，249/2042未运行 | `real_device` | `FAIL` |
| 新SSAP消费者的实际锁/Grant/撤权/提交与晚到组合：未证明 | `formal_bounded` | `UNPROVED` |
| 默认回归、属性权限/Bond及完整S0-S6/恢复：仍缺 | `real_device` | `UNPROVED` |
| K619/U8bd：SLE主动断链10，六项SSAP/61/249/2042实机，48往返 | `real_device` | `PASS` |
| 干净8bd705工具、六原件重放42负对照及相同Create参数 | `offline` | `PASS` |
| 实际锁/引用/Grant/提交撤权/晚到复用及SSAP组合：未证明 | `formal_bounded` | `UNPROVED` |
| 原超时根因未闭合：新旧13对照反证单字节致因，仍需诊断 | `real_device` | `UNPROVED` |
| 内核清理迁移/属性权限/Bond及完整S0-S6/恢复：仍缺 | `real_device` | `UNPROVED` |
| K8c/U625接收机制上下文：六实机门禁48回复/96上下文/24控制拒绝 | `real_device` | `PASS` |
| 接收上下文：706冻结工具/43封存绑定/Session sanitizer/90实证负对照 | `offline` | `PASS` |
| 生产receipt/dequeue纯转换CBMC65及三负对照：限定有界通过 | `formal_bounded` | `PASS` |
| Owner真值/锁/引用/USB与撤权晚到复用组合：未证明 | `formal_bounded` | `UNPROVED` |
| SSAP属性策略/最终TX intent/实际失效矩阵与完整S0–S6：仍缺 | `real_device` | `UNPROVED` |
| K1bc/Ub4受约束响应：六实机门禁48回复/144旧意图拒绝 | `real_device` | `PASS` |
| 受约束响应：707冻结工具/44封存绑定/91Engine/132实证负对照 | `offline` | `PASS` |
| 生产constraint/Grant纯guard CBMC168及三负对照：限定有界通过 | `formal_bounded` | `PASS` |
| Owner真值/锁/引用/USB与撤权晚到复用组合：未证明 | `formal_bounded` | `UNPROVED` |
| SSAP属性策略/主动请求intent/实际失效矩阵与完整S0–S6：仍缺 | `real_device` | `UNPROVED` |
| K1bcb/Ud4/工具49：六实机72属性案例含36真实拒绝与48业务往返 | `real_device` | `PASS` |
| 属性访问：713冻结工具/48封存绑定/92Engine/192实证负对照 | `offline` | `PASS` |
| 生产constraint/Grant CBMC168及三负对照：单快照限定通过 | `formal_bounded` | `PASS` |
| 生产属性访问谓词Kani：诊断保留，未证明 | `formal_bounded` | `UNPROVED` |
| 实际Owner/引用/USB与撤权晚到复用组合：未证明 | `formal_bounded` | `UNPROVED` |
| 历史首轮VM缺guest模块：原FAIL保留，未执行属性门禁 | `real_device` | `FAIL` |
| 本地授权/Bond/新失效组合及完整S0–S6：仍缺 | `real_device` | `UNPROVED` |

保留镜像：K `1bcb1cd8453068aeefedb4a8da4dc3cb15ea600f`；编译 U `d4a13e941aefee3ef11ccf56d74b144322947cd3`；执行工具 `49a648826e42787a709e3e664eaacc5f2ad1a67f`。

**当前工作树整体资格：NOT_REVALIDATED；完整范围：INCOMPLETE。** 分项按各自准确源码记录。
公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。
本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见
[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。
预备/guest 工具 `49a648826e42787a709e3e664eaacc5f2ad1a67f`；上列执行工具为 Host 校验工具，分别记录。
<!-- qualification-summary:end -->

## 已封存数据子资格（以下均按各自准确镜像）

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

执行工具69314c4的[综合CI](https://github.com/OpenSparklink/sparklink/actions/runs/38921748547)、
[严格文档](https://github.com/OpenSparklink/sparklink/actions/runs/38921748917)、
[资格元数据](https://github.com/OpenSparklink/sparklink/actions/runs/38921748794)及
[限定codec探索](https://github.com/OpenSparklink/sparklink/actions/runs/38921748783)通过；
准确范围见事件调度报告，不能替代实机、实际内核并发或完整发布资格。后续文档提交
不改变该工具CI身份，也不自动更新编译artifact的资格。
