# 当前能力与资格

本页是唯一当前资格入口；[架构](architecture.md)是目标，
[唯一计划](implementation-plan.md)是待办。当前摘要从
`project/qualification-records.json` 生成或校验，不以“最新 HEAD”推断实机资格。

<!-- qualification-summary:start -->
以下摘要由 `project/qualification-records.json` 生成；不以文档提交替代编译身份。

| 契约（仅所列范围） | 证据层级 | 记录结果 |
|---|---|---|
| 原期限、两角色安全机制及保留数据：21组限定门禁 | `real_device` | `PASS` |
| 生产原期限算术：四种HZ、100检查 | `formal_bounded` | `PASS` |
| 生产安装/取消组合：unsupported，1766检查不是证明 | `formal_bounded` | `UNPROVED` |
| Agent/method/调用者：dirty 接线未验收 | `implemented` | `MISSING` |
| 动态多通道/四真实设备两组：仍缺 | `implemented` | `MISSING` |
| 自然故障根因与非人工恢复：仍缺 | `implemented` | `MISSING` |

保留镜像：K `8cbf53e6a088899229d398b0673a82e8e5aed9ff`；编译 U `2d81b3e6348b1c7437e598a6fd3cac53ce9b8fc7`；执行工具 `575ba337c05b09b6c3e96f4182ffcf7ffb6b466c`。

**当前工作树：NOT_REVALIDATED；完整范围：INCOMPLETE。** Agent 接线不继承旧实机资格。
公开 CI 只验证元数据（METADATA_ONLY_NOT_REVERIFIED）；私有原材料不可取得时不授予当前 PASS。
本地完整性核对也不等于重放、独立空口解码或实现证明。层级、假设及门禁见
[资格契约 ADR](../docs/decisions/0005-qualification-and-quality-gates.md)。
<!-- qualification-summary:end -->

## 范围与尚缺条件

准确保留镜像取得普通用户双角色短消息、已列长度/分片、软件背压及 SSAP
ExchangeInfo/单值读写/发现/UUID 子资格。真实 SDK111 的未认证安全机制、
提交前取消及受控等待原期限分别验收；等待探针不是 Agent 回调。
[21组准确矩阵及两端材料指纹](../docs/evidence/security-absolute-deadline-regression-20261015.json)
保留 40 次机制前后业务往返、136 次数据往返、32 次超限拒绝与两个严格最后 fd 阶段。
这些计数不表示全部业务经过认证或加密。

[池满与NOCP后恢复](../docs/evidence/security-deadline-credit-observation-20261015.json)
只覆盖所列固定通道/固件的实际观察；NOCP 真值、重复/迟到、旧 debt 与 handle 复用
屏障仍未证明。较早 Managed/断链/原期限受控交错继续绑定各自旧镜像；不继承到新镜像。

Agent 生产接线尚在工作树中，未提交、未取得新离线/实机资格；动态多通道、四设备
两组业务、SSAP 正向 CCC/通知/指示、认证身份、可信 Grant、Bond 仍不合格。
普通应用组的真实 system-bus/udev/内核授权验收仍缺；控制组 UID1000/caps0 不替代。
默认 Pair 等未支持入口明确拒绝。批准、控制器完成、协议 ACK 都不表示应用已处理。

原版111选择与上传记录不等于完整执行读回证明；147/1ff 缺包、连续 RAM 实验失败、
首次期限探针失败、形式化 timeout/unsupported 均保留。
端口2人工重插后两只 Ready 及业务恢复只恢复实验条件；自然故障根因与非人工恢复
继续开放。没有宿主实验内核或驱动测试；所有真实设备操作保持 VM-only。

## 工程资格与证据访问

本轮只增加资格完整性检查、文档和计划，不新增协议资格。现有提取生产函数的
fixture 检查不包含真实锁、分配器、引用、USB 或内核调度；当前资格配置有 UBSAN，
尚未取得 KASAN/KCSAN/lockdep/故障注入/KCOV 新调试 VM 资格。
[形式化范围与未证明项](../docs/evidence/security-absolute-deadline-20261015.json)
不因工具安装、检查数量或其他局部 PASS 升级。

原材料可能含密钥，公开站点只提供摘要与指纹；没有公开下载或异地保留保证。
本机读取权限、保留位置和重放边界见结构化记录的 `access_policy`。
`python3 tools/check_qualifications.py --mode local` 核对原件；
`--require-current` 还检查声明范围内的源码，当前 Agent 改动应拒绝继承旧资格。
本地核对成功不是实机重放；缺失原件或 hash 不符时不能授予当前 PASS。

## CI 与历史

质量首批签名提交 `92c75cab77ee5949ea636dee6b897b413f801fae`：
[CI 38749647782](https://github.com/OpenSparklink/sparklink/actions/runs/38749647782)、
[Documentation 38749648275](https://github.com/OpenSparklink/sparklink/actions/runs/38749648275)、
[Qualification integrity 38749648556](https://github.com/OpenSparklink/sparklink/actions/runs/38749648556)
全部成功；新质量 job 只核对公开元数据，不是实机重放。
监督器原子失败保护提交 `7a9ac120c5b6` 的
[综合CI](https://github.com/OpenSparklink/sparklink/actions/runs/38750325434)、
[文档CI](https://github.com/OpenSparklink/sparklink/actions/runs/38750325402)和
[资格元数据CI](https://github.com/OpenSparklink/sparklink/actions/runs/38750325375)均成功。
后续报告格式拒绝检查使专项负对照达23项本地通过；各结果只适用其记录的工具源码，
均不覆盖Agent dirty或增加运行资格。
[九个issues准确读回](../docs/evidence/qualification-quality-issues-20261015.json)
保留原scope及OPEN。后续提交不能继承这条CI观察为已运行。
两仓库 master 的经典分支保护 API 返回 Branch not protected，rulesets 列表为空；
不宣称 required checks 已强制执行，也不自动修改仓库策略。

[历史页面原文及冲突快照](../history/architecture/qualification-snapshot-eaea706-20261015.md)
保留原始状态，不再混入当前矩阵；[证据索引](../docs/evidence/index.md)
保留其他旧资格、失败与反例。UserHost 仍仅 P4 规划；完整 S0–S6、19 WP、10 FV、
12 DG、原 issues 和自然恢复退出条件均不变。
