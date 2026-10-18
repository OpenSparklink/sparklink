# 文档整改历史与原始范围

本页是早期各批审计及失败的历史记录，保留当时路径、数量和结论；
不是现行实施计划，也不表示当前内容已完整。当前 DQ1–DQ5 与唯一待办见
[实施计划](../../project/implementation-plan.md)。下文旧“保持路径”已由后续迁移取代。


## 本批边界

第一批审计基线为用户态提交 `670674736ac90ec0f89ca0330849e22b1bc8f81b`，不代表当前 HEAD。第二批从干净 U `dc040002555c`／K `e78b88f050aa` 重审。
当前在活跃开发分支以独立文档提交调整入口、添加 uv/Sphinx/MyST 和严格 CI；不修改驱动、daemon、
UAPI 或资格事实；同步现有 issues 与 goal 的关联执行记录，不部署主机服务，不发布网站。

现有 Markdown 的 GitHub 路径保持稳定。四类目录提供读者入口，原文件仍是
单一来源；“已归入导航”不表示内容已经完成 Diátaxis 拆分。

## 迁移顺序与验收

| 批次 | 工作 | 完成条件 |
|---|---|---|
| D0 | 清单、四类入口、独立计划／记录入口、锁定依赖、HTML CI | 全部 64 份基线 Markdown 都有去向；严格构建通过；权威来源不重复 |
| D1 | README 收敛为项目入口；移除无依据的完整与数量声明 | 能找到文档站、当前资格及开发约束；不推荐未授权主机部署 |
| D2 | 拆分 VM 环境、双设备验收、抓包、板级输入页 | 每篇操作指南只服务一个任务；命令绑定可用版本；证据转入记录 |
| D3 | 审计 UAPI／D-Bus／C／Python／CLI 参考 | 区分当前、实验、明确不支持与已删除；源码或契约可验证 |
| D4 | 精简架构解释，ADR 保持决策原文 | 机制、策略、模式和边界清晰；计划／资格不混入解释正文 |
| D5 | 从当前真实通过路径提炼首次 WS73 教程 | 新读者能按固定前置条件完成；不会继承旧镜像的 PASS |
| D6 | 再审公开站点发布、离线图形与版本管理 | 明确发布入口与构建权限；迁移 URL 有兼容安排 |

本批完成 D0 的锁定安装／严格 HTML／内部资源检查和 D1 的 README 收敛；
第一批当时浏览器交互验收缺失；第二批已取得限定浏览器门禁，见下文。整个内容整改仍未完成。D2 已提取板级输入、VM 准备及发现证据核对三个任务指南；
D3 完成 SSAP facade、删除 ioctl、实验及规划接口的状态参考，完整字段／错误矩阵仍缺。
D4 从 ARCHITECTURE 移除实现／逐轮历史前言，保留目标正文及固定提交原文；其余混合解释仍待逐篇审计。
D5 增加真实路径的证据阅读教程，不冒充已经重验的设备启动教程。D6 正式发布、离线 Mermaid／许可证及真正首次硬件教程延期。

本文件是唯一 IMPLEMENTATION_PLAN 的文档工作附页，不建立第二套 S0–S6 规划。

## 每篇旧文档的处理

[文档清单源码](../documentation-map.toml) 为每篇基线文件记录读者、目的、类型、有效性、版本、权威来源、处置与原始 SHA-256。
49 份旧 docs 范围扩展到仓库内 64 份 Markdown（包括贡献、绑定、工具、formal 和实验说明），另有 405 个证据资产保留源码入口，不整体发布。
清单中的 hash 是审计基线 hash，不是后续修改后的当前内容 hash。根 README 已改写；其原文同样保留固定提交链接。
作为当前契约的混合文档先保持入口，拆分时只迁移仍成立的部分。
历史审计、逐轮失败、自然恢复根因和限定证明保留原记录及源码身份。

物理移动文件前必须核对仓库内链接、GitHub issues、工具中引用的路径和外部 URL。
优先逐篇迁移，不批量改名活跃的 ARCHITECTURE、IMPLEMENTATION_PLAN、
CURRENT_CAPABILITIES 或 GOAL_EXECUTION_STATE。


## 验证与未决项

Python 3.12.10 + uv 0.10.3，Sphinx 9.1.0／MyST 5.1.0／Furo 2025.12.19：新虚拟环境 `--locked --only-group docs` 安装及无缓存 doctree 的严格构建通过。
HTML 内部页面／anchor／静态资源和公开输出路径检查通过；这些不是浏览器视觉或 JS 搜索验收。
第一批 CUA 返回 browsers=[]，当时浏览器未验收；第二批使用独立 Firefox 完成这些门禁，详见其准确源码报告。
外链独立报告保留 HTTP 错误与限流；不全局忽略警告，不将 429 算作链接有效。

没有物理迁移活跃原文件，也没有新增发布 URL，因此原 GitHub 路径不变。
后续页面迁移须检查源码工具引用、issues 与外部链接，再提供旧 URL stub／重定向。本站的证据和历史链接使用固定提交；不可取得的私有材料明确标记。

第一批后续安排（浏览器部分已由第二批落实）：逐字段 API／错误／权限参考；从准确重新验收的 VM 镜像提炼首次真实 WS73 操作教程；其余混合文档逐篇提取；最后独立审查 Pages 子路径、版本和离线图形。
不关闭 U#8／K#19 或 SSAP 整项任务，不改变任何功能资格。

## 第一批可审查结果

[准确提交的门禁与范围](../evidence/diataxis-documentation-first-batch-20261013.json)记录签名提交8a89ee4、锁文件／构建配置 hash 和未决项。
[文档 CI及下载 HTML artifact](https://github.com/OpenSparklink/sparklink/actions/runs/38402594511) 已成功，artifact 保留14天；它是构建产物，不是正式站点发布。
准确提交外链隔离重跑：223项有效，56项HTTP429未核实，无其他失败；退出1，不记为全量PASS。较早重叠写入的损坏JSON报告已弃用。
U#8／K#19／U#3 更新已逐字回读，均OPEN。

## 第二批：当前接口与真实浏览器整改

保留第一批 64 份原文去向，本轮登记全部 87 份用户态 Markdown（包含新读者页），
以及单独 10 份内核 SparkLink／WS73 资料。检查器覆盖新嵌套页面；缺清单即失败。
内核旧总览替换为实际分层／接口入口，原始 2400 余行混合材料保留固定提交原文；
旧 read、SSAP containment 和早期 VM 说明明确为历史，不提升旧 PASS。
新的 ControllerEvent 参考按当前源码拆出字段、错误、已删入口和证明范围；
没有创建第二套架构、计划或资格矩阵，也没有移动活跃文件。

准确 U `311556185275` 已在全新 Python3.12 环境与独立干净 checkout 完成 locked 安装、
严格 HTML、内部链接／资源／公开路径门禁，独立 CI 成功并提供 HTML artifact。
Firefox 无头 BiDi 实际点击导航、英文完整接口词／中文搜索、代码块、表格、
Mermaid 和 390px 布局通过；截图经过查看。初次搜索 JS 异常和窄屏表格问题已保留，
修复局部构造器映射、锁定 jieba 和横向滚动表格。仅 DOM 检查不算视觉验收。

可复现浏览器工具为 `tools/check_docs_browser.py`，仅访问 localhost 文档预览，
与 `make docs`、设备操作和服务安装独立。Mermaid 仍依赖已声明的 CDN。
本轮外链独立检查 248 有效、60 HTTP429 未核实、其他失败0、退出1，非全量 PASS。
[第二批范围、准确提交与失败记录](../evidence/diataxis-documentation-second-batch-20261014.json)。

状态：基础设施／导航已具备门禁；内容拆分仅部分完成。完整 API 字段、其余混合
原文、首次实机执行教程、离线图形和正式发布继续开放。整个文档任务不关闭。

## 第三批：最新主线复核与 snoop 内容拆分

重新审计干净用户态 `ca72b4915854`／Linux `5582a10c5ec8`，未沿用侧分支完成声明。
沿用已锁定构建设施，拆出单控制器 capture how-to 与逐字段 snoop reference；旧 SNOOP
路径保留来源和历史门禁，导航链接新页面。修正第一批浏览器未验收表述及旧 C/Python
缺失声明。发现内核 query flags/reserved 未显式拒绝，按实际源码记录限制，运行代码未改。

最新清单补充逐篇具体处置与审计快照；原始 hash 仍保留，当前 hash 单独生成。
D0/D1 的设施与导航完成不意味着 D2–D6 全部完成。剩余 API、混合原文、首次硬件教程、
外链限流、离线图形及发布继续开放，不成为真实 WS73 或用户态 SSAP 的前置依赖。

[第三批准确提交、清单、浏览器与未决记录](../evidence/diataxis-documentation-third-batch-20261014.json)。

第三批准确文档提交 `0cbe7a823152` 的干净安装、严格构建、内部资源与实际浏览器
门禁通过；独立 CI 提供可下载 artifact。外链重试 253 有效、71 HTTP429、其他联网失败0，
退出1，未全量通过；首次沙箱 DNS 失败保留。U#8／K#19已更新回读，均OPEN。

## 第四批：最新主线与业务证据阅读

基线 U `99692b58e29e8d6725853d5748599a8d8b48df94`／K
`ce258f23e840a45cb8030a79c09277dd880aa9e3`，两仓库初始工作树干净。
主线已包含前三批基础设施，不重复合并侧分支。第四批拆出业务往返证据核对
how-to 与资格边界 explanation，历史连接汇编增加醒目的历史入口。
清单变为 91 份用户态／10 份内核资料；原始基线 hash 保留，当前 hash 由构建报告生成。
本批不改 Runtime、协议、工具核对逻辑或实机资格。

D0 基础设施、D1 首页导航具备门禁；D2–D4 内容拆分继续进行；D5 首次真实
设备执行教程、D6 离线图形与正式发布仍未完成。外链 HTTP429 未核实记录保留。
最新锁定安装、严格构建和浏览器结果另记第四批报告，未执行前不标 PASS。

第四批准确签名提交 `45f62ea9a56b`：全新 locked Python3.12 文档环境安装、
无缓存严格 HTML、91／10 清单及内部页面／anchor／资源／公开路径检查通过。
Firefox 实际导航、中英文搜索、代码块、表格、Mermaid、390px布局及新增页面通过；
桌面任务页与窄屏参考截图已查看。[独立 CI 与 HTML artifact](https://github.com/OpenSparklink/sparklink/actions/runs/38476729256)
成功，artifact 保留14天，本批没有发布。外链未重跑，历史71项429仍未核实。
[准确第四批结果与未决](../evidence/diataxis-documentation-fourth-batch-20261014.json)。
U#8／K#19／U#3 更新已回读，均OPEN；完整 goal 保持active，不改原始目标或预算。

## 第五批：46份大写原文逐篇归纳

基线U `ac64b3566f33`／K `31769ea4b8c0`；保留正在开发的SSAP actor dirty diff，
未将其列为资格。全部46份根目录大写Markdown按11个主题补摘要、范围和推荐入口。
旧API全量表改为源码定位，固定版本原文保留；SSAP权限语义抽为参考，旧数据库
消费者明确退休；原生主机部署内容明确历史和VM-only。权威路径不迁移。
清单覆盖93份用户态Markdown及10份内核材料，原始hash不重写。
内容仍为分批整改，未完成所有混合资料拆分；不改变硬件资格，不关闭整项issue。

第五批准确签名文档提交 `1d09c09369ce`：干净临时checkout的locked Python3.12
安装、严格HTML与清单/内部链接/资源通过；最初archive缺Git HEAD导致报告失败，
补准确提交元数据后重跑通过，失败日志保留。Firefox新增主题导航、权限搜索、
表格、代码、Mermaid与390px布局通过，截图已查看。
[独立CI及HTML artifact](https://github.com/OpenSparklink/sparklink/actions/runs/38487251357)
成功；无正式发布。[范围和未决](../evidence/diataxis-documentation-uppercase-batch-20261014.json)。
开发dirty文件hash保持一致，无运行代码变更，不要求重复硬件资格。

## 第六批：用户要求的物理迁移

用户在第五批后明确要求大写资料不再放docs/。因此修改原“先保留活跃路径”
安排：46份Markdown迁到顶层project/和history/并改为小写连字符文件名，
机器执行状态迁project/goal-execution-state.json，架构采用原始JSON归档history。
三权威文档仍唯一，docs/三个入口仅include读取外部原文并重写相对链接。
源码/工具/CI导航和内核文档引用同步，清单98份用户态Markdown及10内核资料。
原始baseline hash、固定旧提交、失败与资格范围保留，迁移不改运行代码。
旧HTML路径生成重定向；GitHub分支blob删除后无法自动转向，不保留大写stub，
以旧新路径表和固定旧提交安排兼容。准确构建/浏览器/CI结果另记，未执行前
不标PASS；完整混合内容拆分/外链/离线图形/正式发布仍OPEN。

第六批准确签名提交 U `45508f5f7b9a`／K `63aee16e1b3f` 仅改文档。干净clone的
locked安装、98／10清单、严格HTML和内部资源检查通过；Firefox主题导航、搜索、
图表、移动端及三个旧HTML重定向通过，截图已查看。
[文档CI与下载artifact](https://github.com/OpenSparklink/sparklink/actions/runs/38495063473)成功；
[准确范围和未决](../evidence/diataxis-physical-migration-20261014.json)。运行源码hash不变，
实机资格仍绑定K317／U7d87，不重新标记为最新文档HEAD通过。
