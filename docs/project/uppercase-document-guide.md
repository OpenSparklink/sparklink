# 大写原文：主题归纳与阅读顺序

核对日期：2026-10-14。用户态已提交基线 `ac64b3566f33`，Linux `31769ea4b8c0`。
当次文档审计保留了未提交的 SSAP actor 和工具改动；当时尚无该改动资格。
后续实现及准确验收仅见[当前资格](../../project/current-capabilities.md)。
这里逐篇整理 `docs/` 根目录全部 **46 份原大写 Markdown**，本次按用户要求已物理迁移并改为小写文件名；没有创建
另一套架构、实施计划和资格表。原始文件的固定版本和失败证据仍可取得。

## 怎样读

先看[当前资格](../../project/current-capabilities.md)，理解目标时看[架构](../../project/architecture.md)，
追踪剩余工作时看[唯一实施计划](../../project/implementation-plan.md)。
执行具体任务从[操作指南](../how-to/index.md)开始，核对证明范围看
[资格边界](../explanation/qualification-boundaries.md)，不要直接照旧轮次的命令操作。

“权威”表示唯一职责入口；“参考入口”只负责定位；“混合”包含可复用语义及历史
状态，尚需继续拆分；“历史”保留当时结论、失败和门禁，不等于已失效或可以删除。
历史中的原验收条件仍有效，其执行顺序以唯一计划为准。

## 按主题逐篇查找

### 权威入口

当前计划与资格仅在这三处维护。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [ARCHITECTURE](../../project/architecture.md) | 权威 | 目标分层、状态所有权和架构约束 | [阅读入口](../explanation/index.md) |
| [IMPLEMENTATION_PLAN](../../project/implementation-plan.md) | 权威 | 完整 S0–S6、工作包依赖和未完成门禁 | [阅读入口](index.md) |
| [CURRENT_CAPABILITIES](../../project/current-capabilities.md) | 权威 | 按准确源码区分实现、离线、限定证明和实机资格 | [阅读入口](../evidence/index.md) |

### 架构依据与实验边界

参考分析解释取舍，不能代替架构入口或实施计划。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [BLUEZ_COMPARISON](../../project/reference/architecture/bluez-comparison.md) | 混合 | Bluetooth/BlueZ 职责借鉴；夹有旧源码回归摘要 | [阅读入口](../../project/architecture.md) |
| [BLUEZ_RECONCILIATION_20261011](../../history/architecture/bluez-reconciliation-20261011.md) | 历史 | 竞争分析的复核、限定验收及待补条件 | [阅读入口](../../project/architecture.md) |
| [NEARLINK_HOST_REFERENCE](../../project/reference/architecture/nearlink-host-reference.md) | 混合 | OHOS、SDK111 与 libws73 的封装及固件对照 | [阅读入口](../../project/architecture.md) |
| [EXPERIMENTAL_CODE_BOUNDARY](../../project/reference/architecture/experimental-code-boundary.md) | 混合 | 实验 Profile/HID/transport 的编译隔离和回调测试边界 | [阅读入口](../reference/interfaces.md) |

### 接口、权限与管理

先查现有源码契约；旧编号表不能作为支持清单。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [API](../../project/reference/management/api.md) | 参考入口 | 替换旧全量 ioctl 表，按当前入口、删除与拒绝语义查找 | [阅读入口](../reference/interfaces.md) |
| [DBUS_AUTHORIZATION](../../project/reference/management/dbus-authorization.md) | 混合 | 观察与控制权限、服务名保护及历史权限回归 | [阅读入口](../reference/interfaces.md) |
| [MANAGEMENT_OWNERSHIP](../../project/reference/management/management-ownership.md) | 混合 | 每设备 lease、File 身份、撤销状态及迁移记录 | [阅读入口](../../project/architecture.md) |
| [MANAGEMENT_SETUP_RELEASE](../../history/management/management-setup-release.md) | 历史 | release/dup/最后关闭、初始化与在途物理义务的逐批验收 | [阅读入口](../../project/current-capabilities.md) |
| [DAEMON_ADMISSION_HANDOFF](../../history/management/daemon-admission-handoff.md) | 历史 | daemon 交权准入与另一只设备隔离的限定证据 | [阅读入口](../../project/current-capabilities.md) |
| [DAEMON_CRASH_HANDOFF](../../history/management/daemon-crash-handoff.md) | 历史 | SIGKILL、最后 File 和原代次接任的限定证据 | [阅读入口](../../project/current-capabilities.md) |
| [WS73_OBSERVER_POLICY](../../history/management/ws73-observer-policy.md) | 历史 | 普通观察者的权限参数与真实回归记录 | [阅读入口](../reference/interfaces.md) |

### 诊断、事件与抓包

逐接口参考已拆出；复制、取消和旧结果迁移记录保留原始失败。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [DIAGNOSTIC_ADMISSION](../../project/reference/diagnostics/diagnostic-admission.md) | 混合 | 诊断 request_id、原始期限、作者取消及复制准入契约 | [阅读入口](../reference/interfaces.md) |
| [DIAGNOSTIC_CANCEL_GATES](../../history/diagnostics/diagnostic-cancel-gates.md) | 历史 | 取消/迟到/期限/关闭的分批 VM 门禁 | [阅读入口](../../project/current-capabilities.md) |
| [DIAGNOSTIC_RESULT_MIGRATION](../../history/diagnostics/diagnostic-result-migration.md) | 历史 | 结果所有权迁移、槽淘汰和复制故障记录 | [阅读入口](../../project/current-capabilities.md) |
| [EVENT_COPY_REMEDIATION](../../history/diagnostics/event-copy-remediation.md) | 历史 | 已删除事件 read/poll 的复制提交整改证据 | [阅读入口](../reference/controller-events.md) |
| [EVENT_RECEIVER](../../history/diagnostics/event-receiver.md) | 历史 | 已删除旧 EventReceiver 管理 fd 的无硬件测试 | [阅读入口](../reference/controller-events.md) |
| [SNOOP](../../project/reference/diagnostics/snoop.md) | 混合 | 独立 DLI snoop 的契约和历次验证 | [阅读入口](../reference/controller-snoop.md) |

### WS73 环境与板级输入

操作内容已拆出；原生主机部署、参考 Host 和私有输入均不是当前推荐入口。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [WS73_BOARD_CONFIGURATION](../../project/reference/environment/ws73-board-configuration.md) | 混合 | SDK 板级配置导出、候选与真实资格的区别 | [阅读入口](../how-to/export-board-inputs.md) |
| [WS73_TARGET_ENVIRONMENT](../../project/reference/environment/ws73-target-environment.md) | 混合 | 隔离客体准备和旧开发门禁 | [阅读入口](../reference/vm-gate-inputs.md) |
| [WS73_NATIVE_LAB](../../history/environment/ws73-native-lab.md) | 历史 | 实验内核产物、空 USB VM 与旧主机部署设计 | [阅读入口](../reference/vm-gate-inputs.md) |
| [WS73_REFERENCE_DISCOVERY_LAB](../../project/reference/environment/ws73-reference-discovery-lab.md) | 混合 | 参考 Host 的 guest 发现对照与故障追踪 | [阅读入口](../reference/vm-gate-inputs.md) |

### 广播、发现与并行空口

第一北极星验收条件保留；旧轮次 PASS 不授予当前镜像。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [WS73_DISCOVERY_NORTH_STAR](../../history/discovery/ws73-discovery-north-star.md) | 历史 | 广播发现北极星原验收和逐轮源码/实机记录 | [阅读入口](../how-to/capture-and-check-discovery.md) |
| [WS73_PHYSICAL_TEST](../../project/reference/discovery/ws73-physical-test.md) | 混合 | 双端控制记录和原始接收核对步骤 | [阅读入口](../how-to/capture-and-check-discovery.md) |
| [WS73_DISCOVERY_POLICY](../../project/reference/discovery/ws73-discovery-policy.md) | 混合 | 每设备策略配置、范围校验及连续窗口失败对照 | [阅读入口](../reference/interfaces.md) |
| [WS73_ADVERTISING_SET_LIFECYCLE](../../history/discovery/ws73-advertising-set-lifecycle.md) | 历史 | 广播集合清理、连接失败及实际 Complete 对照 | [阅读入口](../../project/current-capabilities.md) |
| [WS73_PARALLEL_RF](../../project/reference/discovery/ws73-parallel-rf.md) | 混合 | 四只两组发现的操作与失败策略记录；不是业务数据资格 | [阅读入口](../how-to/capture-and-check-discovery.md) |
| [WS73_PARALLEL_POLICY_MATRIX](../../history/discovery/ws73-parallel-policy-matrix.md) | 历史 | 功率/扫描窗口单变量矩阵及清理失败 | [阅读入口](../../project/current-capabilities.md) |

### 连接、数据通道与业务证据

旧纵向计划并入唯一计划；Session/socket 和真实业务分层判断。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [WS73_NATIVE_LINK_FOUNDATION](../../history/connections/ws73-native-link-foundation.md) | 历史 | S4 连接生命周期初期范围与当时尚缺条件 | [阅读入口](../../project/current-capabilities.md) |
| [NATIVE_CONNECTION_IMPLEMENTATION](../../history/connections/native-connection-implementation.md) | 历史 | 连接/撤销/对象迁移和逐批控制、数据门禁 | [阅读入口](../how-to/check-business-roundtrip.md) |
| [DATA_SOCKET_VERTICAL_PLAN_20261012](../../history/connections/data-socket-vertical-plan-20261012.md) | 历史 | 短消息主线起点、封装对照和最初依赖；后续唯一计划接管 | [阅读入口](../../project/implementation-plan.md) |

### SSAP 语义与旧路径剥离

权限类型继续复用；旧 staging、远端 Engine 和当前开发 actor 必须分别描述。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [SSAP_OPERATIONS](../../project/reference/ssap/ssap-operations.md) | 混合 | 仍有效权限位语义与已删除 staging 调用者的历史 | [阅读入口](../reference/ssap-permissions.md) |
| [SSAP_LEGACY_CONTAINMENT](../../history/ssap/ssap-legacy-containment.md) | 历史 | 旧不可靠 wire Engine 停用及当时限定 RF 回归 | [阅读入口](../../history/ssap/ssap-production-separation-20261013.md) |
| [SSAP_PRODUCTION_SEPARATION_20261013](../../history/ssap/ssap-production-separation-20261013.md) | 历史 | WP18 调用审计、三类剥离清单和已完成子门禁 | [阅读入口](../../project/implementation-plan.md) |

### 恢复与部分初始化

自然根因、非人工自动恢复仍开放；人工操作和注入不能替代。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [WS73_RECOVERY](../../history/recovery/ws73-recovery.md) | 历史 | 启动超时/消失的 RCA、有限恢复设计及失败证据 | [阅读入口](../../project/implementation-plan.md) |
| [WS73_INITIALIZATION_OFF](../../history/recovery/ws73-initialization-off.md) | 历史 | 初始化 OFF 出处、失败清理和独立 owner 实测 | [阅读入口](../../project/current-capabilities.md) |

### 审计与旧实现整改

清单按当时源码理解，剩余整改统一在当前计划跟踪。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [AUDIT](../../history/cleanup/audit.md) | 历史 | 早期规模和接口覆盖审计；数量不等于能力 | [阅读入口](../../project/current-capabilities.md) |
| [REVIEW_REMEDIATION_20261011](../../history/cleanup/review-remediation-20261011.md) | 历史 | 14 项审查的整改历程和后续追加验证 | [阅读入口](../../project/implementation-plan.md) |
| [LEGACY_CLEANUP_20261011](../../history/cleanup/legacy-cleanup-20261011.md) | 历史 | 删除/移测试/待替代的逐批调用迁移记录 | [阅读入口](../../project/implementation-plan.md) |
| [LINK_STATE_REMEDIATION](../../history/cleanup/link-state-remediation.md) | 历史 | 旧 PHY/安全状态清理和重新开放门禁 | [阅读入口](../reference/interfaces.md) |
| [GENERIC_USB_FIRMWARE_REMEDIATION](../../history/cleanup/generic-usb-firmware-remediation.md) | 历史 | 通用 USB 固件路径和复制/边界整改 | [阅读入口](../../project/current-capabilities.md) |
| [STANDARD_USB_BINDING_CLEANUP_20261013](../../history/cleanup/standard-usb-binding-cleanup-20261013.md) | 历史 | 标准 USB provider/驱动归属及默认实验依赖迁移 | [阅读入口](../../project/architecture.md) |
| [USB_DESCRIPTOR_CAPABILITY_CLEANUP](../../history/cleanup/usb-descriptor-capability-cleanup.md) | 历史 | 端点/能力默认值与在途文件关闭回归 | [阅读入口](../../project/current-capabilities.md) |

### 计划历史归档

原始顺序和失败保留，不复制活跃计划。

| 原文件 | 类型 | 内容摘要／处理 | 推荐入口 |
|---|---|---|---|
| [IMPLEMENTATION_HISTORY_PRE_20261013](../../history/plans/implementation-history-pre-20261013.md) | 历史 | 2026-10-13 前旧计划和验收汇编 | [阅读入口](../../project/implementation-plan.md) |

## 本批已做与后续拆分

- 46 份原文均增加阅读范围和替代入口，并迁出 docs/；历史源码身份、原始失败和限定 PASS 不改写。
- `API.md` 的旧全量命令表退役：旧版使用固定提交保存，现页只列源码入口及删除/拒绝语义。
- SSAP 权限语义独立为技术参考；旧内核数据库/staging 的描述改为历史，禁止解释为当前服务发布。
- 原生实验页明确 VM-only，旧主机部署段落作为历史，不能用于本轮执行。
- 清单逐篇补具体目的、有效性和拆分去向；原基线 hash 保留，当前 hash 独立生成。

剩余混合页面的完整配置/字段/错误拆分、第一份真实设备执行教程、外链限流、离线
Mermaid 与正式发布仍开放。本批未改变运行代码、功能资格、协议架构或硬件验收条件。
SSAP actor 的真实回归是开发主线的独立门禁，文档整理不成为其前置条件。

## 当前物理位置

唯一架构/计划/资格和机器状态在仓库顶层 `project/`；复核中的参考来源在
`project/reference/`；历史审计、验收与旧计划在顶层 `history/`，按主题归档。
`docs/`保留读者页面与证据入口，三个权威入口仅从外部唯一源渲染。
文件名改为小写连字符；具体旧新路径见[迁移表](../documentation-paths.json)。
旧分支blob链接无法在删除文件后自动跳转，固定旧提交保留原文；HTML旧入口
由构建生成重定向。未在docs/保留大写stub，也未复制权威内容。
