# 当前能力与资格

R5f9 新增[准确 artifact 的有限实机记录](../docs/evidence/ssap-initialization-cmtc-revocation-20261018.json)：
7b90092 guest/Host、DA编译服务/应用、2fc内核，**仅本线程 U 两口**。发起端与接收端
CMTC等待期间实际 Managed 撤权，原能力回复完整保留/释放，真实 Status/双端 Down、
daemon fd `4→6→4→4` 及另一 controller RX/Ready 分别核对；随后同 daemon 交换角色，
8次实际随机应用回复、22次发现。4143USB包／零丢包、21证据负对照，独立重算两次；
6项资格聚合负对照拒绝旧源码、缺失/hash不符的artifact、错误范围、漏门禁和未证明。

850工具离线检查通过，新增形式化证明0。六轮实机共五次整体FAIL、一次有限PASS；
失败原样保留，纠正后重放不回写原结果。未新增生产 Engine/Runtime/ABI，未重编内核
或服务；记录准确编译来源，并核对当前生产范围字节相同，不转授整个HEAD资格。
本记录不证明 task join、内核引用/UAF/drain、bind内部、ExchangeInfo等待退休、
完整2×2角色/fd矩阵、E或混合型号、冷ROM自动选型、自然故障根因及非人工恢复。

R5f8 的[新独立记录](../docs/evidence/ssap-requester-drain-held-business-20261018.json)已登记：
B847 guest/Host、DA服务、2fc内核，两角色真实 requester 死亡后旧写回复排空、
新读独立校验及提示挂起期间8次真实业务回复；32证据负对照、6资格负对照通过。
首个e68整体FAIL原样保留，未回填升级。833工具fixtures及严格HTML只描述其离线范围，
同一新guest的[原owner/原期限保持](../docs/evidence/ssap-requester-owner-preservation-20261018.json)
另由准确1f15Host重验，27负对照通过；它是保持回归。
新增形式化证明0。完整取消/旧读新读/复用、部分Native初始化等仍缺，不能扩大为
整个当前树的资格。前批cd7及各历史资格保持原artifact范围。


2026-10-18 资源边界调整：本线程仅使用 U `1-1.1.1/.2`、E `1-2.1.1/.2`；
两组 `.3/.4` 属于另一线程，禁止操作。U 两口已由新 guest 的实际 HCC 确认为 U/USB，
E 两口仍仅按用户布置，尚未 HCC 复核；
`1-2.1.2` 不再是旧 U。旧报告保留当时拓扑和准确 artifact，不能转授给新设备。
[资源配置](lab-resource-policy.json)只限定执行权限，不授任何功能资格。
只读复核四只的序列号 pin 与上游 hub/PCI 一致；U 为五端点、E 为两端点 ROM。
已有两台 libvirt VM 的配置未占用这些设备或共享 PCI，部分 root fd 不可见；
每次直通仍需重新核对并获取端口租约。旧操作映射已归为历史，一致性检查拒绝再次
出现；本次无 USB I/O、固件下载或新实机验收。
[新 U 双设备记录](../docs/evidence/shared-allocation-u-gate-20261018.json)独立绑定 DA 服务、
cd7 guest/Host 与2fc内核：实际 HCC、两角色owner/原期限及8次业务回复；
该有限资格不覆盖 E、混合、晚到成功/drain或挂起期间的并发同行业务。
新固件下载限同型号、显式 SDK110 三文件；混合冷启动及无逐设备固件来源的
runtime-only 接管拒绝。冷 ROM 自动选择、自然根因及非人工恢复仍未验收。


本页是唯一当前资格入口。选定产物、原始门禁、源码和工具身份来自结构化记录；
报告/文档提交不替代编译身份，源码相同也不转授旧 artifact 的资格。

当前产物的结果、计数、层级和源码身份统一从下方生成记录读取；不再另写一份手工
“最新资格”计数表。以下只按任务指向接口与边界，历史 PASS 不转授新产物。

| 任务/主题 | 支持范围的权威入口 | 仍需区分的边界 |
|---|---|---|
| 普通用户业务、长度、实际CLI、Peer观察 | 本页选定记录及其全部必需门禁/双端证据 | 功能回归不等于吞吐、可靠模式、全部地址/隐私或整个当前树资格 |
| Rust管理/应用、Owned与Agent | [实际接口](../docs/reference/interfaces.md)、选定记录的准确新入口范围 | 本地登记、策略批准、原生准入、机制安装、对端应用处理分别表达 |
| C/Python与显式Native | [SDK/Native边界](../docs/reference/interfaces.md)、[e776值期限整改后限定实机报告](../docs/evidence/ssap-value-deadline-apps-real-20261018.json)及原限定离线/R6a记录 | apps-only UID/GID1004、无附加组/capabilities，通过公共Client取得通道并完成独立随机回复；管理／SSAP／安全／裸设备／service所有权仍拒绝。SSAP单列管理UID1000的32字节读／短写；完整高阶Owned/Agent、逐应用策略、撤权/原期限等仍缺，不能由组门禁推导完成 |
| 同一SDK镜像原路径保持 | [e776七VM限定报告](../docs/evidence/ssap-value-deadline-preservation-real-20261018.json)、[历史原失败](../docs/evidence/application-owned-preservation-counterexample-20261018.json) | 同一e776服务及工具的七尺寸、原Owned分别通过；不继承旧Agent等范围。ENODATA根因未明，后续PASS不覆盖失败或授完整稳定性／架构资格 |
| Native特权创建/纯契约观察 | [81bd离线及边界](../docs/evidence/native-channel-creation-offline-20261018.json)、[动态/受保护实际路径](../docs/evidence/native-channel-creation-factory-real-20261018.json) | 原daemon创建器已删除；普通SDK无Native管理依赖。函数体/布局与有限实机不等于完整并发、NOCP准确性、所有权生命周期或安全证明 |
| 内核Runtime、Session、Grant、credit/Ticket | [唯一架构](architecture.md)、下面各自源码映射的限定记录 | 旧代际、在途义务、有限队列、撤权及未知完成不能由缓存/关闭抹去 |
| Codec、事件、故障与形式化 | 下方全部限定/历史记录及证明假设 | 旧codec/fixture、工具安装或模型通过不推导当前完整实现通过 |
| 部署、恢复与发布 | [唯一计划](implementation-plan.md)的R5/R6、[实际分包基础限定资格](../docs/evidence/debian-package-base-qualification-20261018.json)及原工作包 | 准确247分包的组、普通用户、基础SDK、同版本重装/remove已验；原缺组FAIL保留；跨版本升级回滚、发布/原生权限/新WS73与自然恢复仍开放 |

这些分项来自各自封存产物，未组成当前HEAD的合并资格；整体仍未完成。

R5f6值原期限／共享初始化的[源码审计与原反例](../docs/evidence/ssap-value-deadline-audit-20261018.json)
及下方四份e776限定记录分别表达离线、SDK正向、原尺寸/Owned和动态/参考受保护保持。
候选6b已复现本地等待超过有效五秒期限，原失败保留且未授实机资格。新有限PASS不
覆盖受控原期限、调用者退出、部分初始化、晚到义务或同行业务全集；完整架构仍缺。
未知C诊断及clock/取消/物理drain假设保持开放。保留中的屏障草稿单列接入；其
本地异常回归不授予最新工具的实机资格，当前工作树整体仍NOT_REVALIDATED。
R5f7的[原审计与失败](../docs/evidence/ssap-owner-deadline-gate-audit-20261018.json)、
[离线记录](../docs/evidence/ssap-owner-deadline-offline-20261018.json)及
[旧拓扑实机限定记录](../docs/evidence/ssap-owner-deadline-real-20261018.json)现已分别登记。
旧拓扑 v1 整体 FAIL 保留；独立 v2 为 DA 编译/guest、9a1 Host、2fc 内核，
两连接角色真实服务 publisher 退出、C/Python errno110 约五秒及8次正常CUTC回复；
没有观察到晚到 denial 物理回复，不覆盖 requester 退出、挂起期间同行业务或部分初始化。
本次新端口、HCC、固件与 guest/Host 工具保持单列待验，不能沿用这份旧拓扑 PASS。
离线记录仅描述原源码的离线范围，不用“实机仍缺”等相对时间标题覆盖后来的独立实机记录。

选定保留产物的编译／执行／校验来源只按下方生成记录读取。R4新raw退休产物已取得
四真实WS73路径保持及单列的模拟controller初始化、usercopy、权限交接资格；
101旧raw入口删除，53旧布局私有测试，26当前数值不变。
[14门禁范围报告](../docs/evidence/raw-uapi-retirement-qualification-20261018.json)保留
原失败、原WIP及准确产物，先前[离线进度快照](../docs/evidence/raw-uapi-retirement-progress-20261018.json)
仍保留其“待验”历史状态。高阶SDK/C-Python便利接口与R6剩余范围仍缺；当前基础部署
的[独立限定VM资格](../docs/evidence/deployment-clean-vm-qualification-20261018.json)不改变旧实机产物身份，
也不表示软件包、跨版本升级回滚、实际内核授权或新WS73产物通过。
[同一新产物的原路径保持](../docs/evidence/application-client-preservation-real-20261018.json)
单列七真实VM、七个应用尺寸及原短包/Owned条件；完整权限/撤权/原期限矩阵仍缺。
自然启动/重枚举/设备消失根因、非人工恢复继续开放；模拟及QMP不能替代。

历史R5d Typed Peer资格以[原准确记录](../docs/evidence/typed-peer-retirement-qualification-20261018.json)
为准；[首轮漏迁runner失败](../docs/evidence/typed-peer-tool-retirement-failure-20261018.json)
仍为FAIL。当前新增复用范围以本页生成选定记录为准；生产artifact与修正工具分开，不能将首轮失败或整个HEAD改记通过。

标准parser原fixture以255代替生产240预算，原聚合已降UNPROVED并保留
[反例](../docs/evidence/parser-budget-fixture-review-20261017.json)。新2d268工具直接
提取生产常量/hash，14子集及2适配器单元方法重验；[修正后的限定记录](../docs/evidence/parser-budget-source-correction-20261017.json)
复用准确旧编译/Virtual/实机原件，没有重建或重跑这些门禁。标准255完整互通仍缺，
不把实际240预算或Native A3业务长度混为标准255资格。

## 选定产物与来源

<!-- qualification-summary:start -->
以下摘要由 `project/qualification-records.json` 生成；不以文档提交替代编译身份。

选定保留产物（不是当前工作树整体资格）：**K2fc/U41ae、工具268：现有Owned/Agent客户端六真实VM限定通过，完整架构开放**。
仅记录范围：`real_device` / `PASS`。
kernel `2fc210af68ee3bce0eed3553117d8be635dfdd15`。
compiled_userspace `41ae994b41b3064cae2dc52b5e0da657ef3961f2`。
executed_tools `26813e4ccaf669516ef78cbf9f5e5ae1842233e5`。
[准确范围与剩余条件](../docs/evidence/owned-agent-client-qualification-20261018.json)。

限定边界由同一记录生成；计数不代替必需门禁、假设或范围：
```json
{
  "actual_cli_agents": 8,
  "actual_cli_requests": 8,
  "cli_evidence_negatives": 20,
  "evidence_negative_controls": 261,
  "final_workspace_tests": 338,
  "honest_unknown_observations": 6,
  "new_formal_proofs": 0,
  "oversize_refusals": 16,
  "owned_cases": 40,
  "peer_evidence_negatives": 84,
  "peer_roundtrips": 48,
  "peer_sdk_observations": 24,
  "peer_usb_positive": 18,
  "real_runs": 6,
  "release_bindings_checks": 50,
  "seal_schema_negatives": 8,
  "service_role_denials": 68
}
```

以下为全部限定/历史记录索引；旧 PASS 不转授选定产物。


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
| F887/836/e513：110三机制两来源30项原意图生命周期 | `real_device` | `PASS` |
| 首110原期限实测5.509秒：原FAIL保留且根因开放 | `real_device` | `FAIL` |
| 真实时延根因/Owner晚完成复用/完整原范围：仍未闭合 | `real_device` | `UNPROVED` |
| K0cd/836/ee8：HCC逐笔期限修复新四门禁32真实业务回复 | `real_device` | `PASS` |
| 新HCC期限：1116生产函数/sanitizer、730冻结工具/48封存ABI | `offline` | `PASS` |
| 真实OUT阻塞/5.509秒数据失败根因与完整原范围：仍未闭合 | `real_device` | `UNPROVED` |
| K0cd/836/ee8：110两安全机制受保护SSAP及16真实业务回复 | `real_device` | `PASS` |
| 110受保护SSAP：两准确重放及64复制实证负对照 | `offline` | `PASS` |
| 逐属性授权/CPCD、完整安全范围及自然恢复仍未闭合 | `real_device` | `UNPROVED` |
| ROM候选：四轮E/U软件复位对照，非首次冷启动识别 | `real_device` | `PASS` |
| ROM候选：特殊指令/741工具/四重放60负对照 | `offline` | `PASS` |
| 首次冷启动、零值有效性及每设备自动固件选择未验收 | `real_device` | `UNPROVED` |
| 历史HCC110整包原文档日志丢失：原hash保留，整包重放未证明 | `implemented` | `UNPROVED` |
| Owned SSAP：基本/机制2两角色真实审批与owner退出 | `real_device` | `PASS` |
| 同c6产物：249/超限与2042完整往返回归 | `real_device` | `PASS` |
| Owned SSAP：严格构建、生产函数/私有D-Bus及冻结工具 | `offline` | `PASS` |
| 生产access审批性质：Kani诊断未消除，未证明 | `formal_bounded` | `UNPROVED` |
| Owned SSAP完整交错/权限部署/CPCD等范围仍缺 | `real_device` | `UNPROVED` |
| 退休R1：去虚假状态/元数据Bond；cd35四实机保持+服务组权限 | `real_device` | `PASS` |
| R2观察预算/发布生命周期；6aad四实机保持，非128地址压力资格 | `real_device` | `PASS` |
| R3a Channel操作层迁移；17ed四实机保持，SDK整体仍缺失 | `real_device` | `PASS` |
| R3c应用/Native/共享契约：6d30真实新SDK路径四门禁，整架构未完 | `real_device` | `PASS` |
| R4a旧controller安全入口退休：98c4b65四真实门禁，整架构未完 | `real_device` | `PASS` |
| R4b旧SSAP门面全链退休：6434055四真实门禁，整架构未完 | `real_device` | `PASS` |
| R4c旧Native Event及空Profile feature退休：6841e4e四真实门禁，整架构未完 | `real_device` | `PASS` |
| R4d旧Native接口全链退休：997ea19四真实门禁及C/CLI元数据，整架构未完 | `real_device` | `PASS` |
| R4e注册状态整改：K64/U0a/工具997四真实门禁，整架构未完 | `real_device` | `PASS` |
| R4e2命令接线退休：Kb35/UEf/工具997分层门禁，整架构未完 | `real_device` | `PASS` |
| R4f1 DLI元数据退休：K7025/Uc032/工具997分层门禁，整架构未完 | `real_device` | `PASS` |
| R4f2b critical fault: production34a/U8a/tools997,Virtual probea991;full architecture incomplete | `real_device` | `PASS` |
| 历史K4b6/U2bd总门禁：parser预算依赖不匹配，聚合未证明 | `real_device` | `UNPROVED` |
| K4b6/U2bd保留产物：2d268直接生产预算修正，实际240边界限定通过 | `real_device` | `PASS` |
| K2fc/U2c8旧rawABI退休：四真实VM与当前Native测试工具限定通过 | `real_device` | `PASS` |
| K2fc/Ua37远端SSAP应用客户端：四真实VM限定通过，完整R5/R6开放 | `real_device` | `PASS` |
| K2fc/U4736管理应用客户端：四真实VM限定通过，完整R5/R6开放 | `real_device` | `PASS` |
| K2fc/U0fe、工具8aa：Typed Peer四真实VM限定通过，完整R5/R6开放 | `real_device` | `PASS` |
| K2fc/U41ae、工具268：现有Owned/Agent客户端六真实VM限定通过，完整架构开放 | `real_device` | `PASS` |
| U668：干净Debian VM通用安装、四角色system bus与外部基础SDK限定通过；软件包/实机另验 | `virtual_integration` | `PASS` |
| U247：实际Debian分包基础安装/四角色bus/外部SDK/重装remove限定通过；升级发布仍开放 | `virtual_integration` | `PASS` |
| U40c公共Client桥接：限定离线证据，未包含部署权限或WS73资格 | `offline` | `PASS` |
| C/Python完整公开接口、部署与生命周期矩阵：仍未完成 | `implemented` | `MISSING` |
| U3ff/工具004c:C/Python真实授权fd与双端业务限定通过；完整矩阵仍缺 | `real_device` | `PASS` |
| U3ff/工具004c:七真实VM原短包与七尺寸保持，完整架构未退出 | `real_device` | `PASS` |
| 22cd固定Connection/SSAP读短写：限定private-bus序列化与生命周期，未包含RF或权限资格 | `offline` | `PASS` |
| 17b4:公共C/Python真实通道与16组SSAP32字节限定通过，原矩阵/权限/完整架构仍开放 | `real_device` | `PASS` |
| 17b4:八真实VM长度与独立Owned有限保持；ENODATA根因及完整架构开放 | `real_device` | `PASS` |
| fa310:真实apps-only公共SDK通道与管理SSAP限定通过；完整架构开放 | `real_device` | `PASS` |
| fa310:七真实VM原短包/Owned/七尺寸有限保持；完整生命周期开放 | `real_device` | `PASS` |
| 81bd Native创建器迁移：offline限定通过；完整架构开放 | `offline` | `PASS` |
| 81bd Native创建器迁移：apps-real限定通过；完整架构开放 | `real_device` | `PASS` |
| 81bd Native创建器迁移：preservation-real限定通过；完整架构开放 | `real_device` | `PASS` |
| 81bd Native创建器迁移：factory-real限定通过；完整架构开放 | `real_device` | `PASS` |
| e776 SSAP值期限/共享初始化：offline限定通过；完整架构开放 | `offline` | `PASS` |
| e776 SSAP值期限/共享初始化：apps-real限定通过；完整架构开放 | `real_device` | `PASS` |
| e776 SSAP值期限/共享初始化：preservation-real限定通过；完整架构开放 | `real_device` | `PASS` |
| e776 SSAP值期限/共享初始化：factory-real限定通过；完整架构开放 | `real_device` | `PASS` |
| 服务owner/SDK原期限：offline限定通过；完整架构开放 | `offline` | `PASS` |
| 服务owner/SDK原期限：real限定通过；完整架构开放 | `real_device` | `PASS` |
| 服务owner/SDK原期限：allocated-u限定通过；完整架构开放 | `real_device` | `PASS` |
| Requester进程退出／旧写回复排空／提示挂起期间业务：限定通过；完整架构开放 | `real_device` | `PASS` |
| 同一新guest的原服务owner／五秒期限保持：限定通过；完整架构开放 | `real_device` | `PASS` |
| CMTC等待期间撤权／原回复／daemon fd收敛：有限实机通过；完整部分初始化开放 | `real_device` | `PASS` |

历史registry基线（非当前资格）：K `0cd4731dd3e673d1309a2b570b38769f9a98681f`；编译 U `83625029e313552ffe7bb87d572245e232a58a49`；执行工具 `ee8c4d2d05d8b8dc38ea585d2964c0aa6b213eb1`。

**当前工作树整体资格：NOT_REVALIDATED；完整范围：INCOMPLETE。** 分项按各自准确源码记录。
公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。
本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见
[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。
预备/guest 工具 `ee8c4d2d05d8b8dc38ea585d2964c0aa6b213eb1`；上列执行工具为 Host 校验工具，分别记录。
<!-- qualification-summary:end -->

## 尚缺与验证边界

完整S0–S6、19WP、10FV、12DG和全部原验收条件保留，整体INCOMPLETE。
多通道/四设备、性能/压力、其他长度、安全/Agent、生命周期的旧资格均只属于各自原
源码和配置；不能从本轮四组保留门禁推导全部矩阵已经重验。缺失新模式持续明确拒绝。

Runtime/generation/lifetime、唯一Session、Grant/credit/Ticket和用户态唯一SSAP Engine
分层保持；UserHost仍为低优先级规划。R4e其余历史入口、R5完整契约/来源与R6干净VM
安装、外部SDK、升级/回滚/卸载和管理员配置/状态保留尚未闭合，部分结果不关闭整项。

没有新增形式化证明。unsupported、timeout和不完整展开仍未证明；生产函数fixture不
替代真实锁、分配器、引用、USB callback/drain、固件清除或NOCP准确性/复用屏障。
新KASAN/KCSAN/lockdep/故障注入/KCOV配置及完整门禁仍需单独验收。

全部实验驱动和真实WS73保持VM-only。人工拔插、hub切电、QMP和注入不代表自然恢复；
USB成功、NOCP或协议确认不代表对端应用已经处理。可靠业务仍以实际对端校验/回复为准。

## 历史、证据和CI

逐轮资格、失败和反例见[历史入口快照](../history/current-capabilities-before-registry-retirement-20261017.md)
及[结构化记录](qualification-records.json)。历史原文保留原身份；本页不继续堆叠逐轮进度。
[材料保留事故](../docs/evidence/hcc110-document-retention-incident-20261017.json)继续作为
required UNPROVED，原件损失不以新hash替换或豁免。

原始USB/安全材料可能受限，仅在授权工作区按报告hash保留；不承诺公开下载或异地永久
保留。公开CI核对元数据，local核对原件，require-current再核对源码；本机完整性检查
不等于重新执行硬件、独立空口解码或实现证明。准确CI运行单列在相应报告，不以“最新”
文档HEAD覆盖编译/执行身份。当前实际能力按上方选定产物和对应范围读取。

## 已封存数据子资格（以下均按各自准确镜像）

此旧锚点保留；逐轮数据叙述在[历史快照](../history/current-capabilities-before-registry-retirement-20261017.md)，
当前范围以选定记录为准。

## 安全与服务的限定范围

当前限定范围见上方矩阵和选定报告；旧逐轮资格保留于历史快照，不自动继承。

## 尚缺与工程边界

此旧锚点对应上方“尚缺与验证边界”；原始完整验收范围不变。

## 历史与失败保留

全部原始失败、反例和身份保留于历史/证据入口，不以随后成功覆盖。

## 证据访问与CI

此旧锚点对应上方“历史、证据和CI”；私有材料和源码匹配条件不变。
