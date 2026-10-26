# 当前能力与资格

## 本批 issue 状态核对

本次在线复核 28 个原项和 7 个子项，更新六项正文的范围、验收映射及历史入口。
28 个原项仍按自身条件开放（15 有限收尾、3 拆分父项、10 长期跟踪）；
已有 U#21 关闭处置保持，其原六条 READ Provider 验收未改变，父 U#3 开放。
本次新增关闭 0 项、新建子项 0 项，复用已有七个职责子项。

[逐项处置/读回](issue-maintenance-20261026.json)与[唯一计划](implementation-plan.md)
记录当前剩余条件。U#1 Native retry 锁等待取消仍缺直接生产路径回归；
U#10 的自然故障根因与非人工恢复仍开放，均不成为 U#22 的全局前置。

维护仅核对源码、留存报告/形式化边界与 CI 状态，没有新增实机、形式化或完整回归资格。
具名离线结果仍绑定各自提交；WRITE VM runner 与双端 verifier 已提交；源码/离线范围与准确产物实机资格分别记录。
已有编译产物、执行工具、失败/反例、原资格选择和以下记录全部保留。

本页是唯一当前资格入口。源码、编译产物、执行工具、校验工具及必需门禁从下方
结构化记录读取；报告或文档提交不替代编译身份，局部 PASS 不授整个 HEAD 资格。

Owned type1 说明的[新增源码契约](../docs/reference/ssap-permissions.md#显式公开的只读属性说明)
不能继承旧属性值或 CPCD 的实机资格。登记/构建/离线检查不等于真实发现和读回；
具体结果仍须绑定结构化记录中的准确产物，公共源码摘要不披露本地实机执行详情。

### 历史批次 R156：Owned type0 动态只读 Provider

当前批次以本页生成摘要为准；下文保留 R156 的源码职责与限定范围，不表示后续产物已验收。

[新增源码契约](../docs/reference/ssap-permissions.md#owned-read-only-provider)已接通，
严格 Rust 构建、私有 D-Bus 与现有跨语言调用回归通过。
实际产物身份与门禁结果只由授权的本地结构化记录维护。
范围仅为原 caller、恰好 READ 的属性和唯一 Engine；
Rust SDK 提供薄绑定/共享准入等待，CLI 提供显式应用回复；完整 C/Python Provider
收件箱与动态写入仍缺。旧存储值、审批
或说明的 PASS 不升级为此路径资格；完整服务、生命周期、自然根因与恢复保持开放。

| 任务 | 对应准确记录 | 必须保留的边界 |
| --- | --- | --- |
| 应用发现租约／共享 scanner | [d9明确Negotiable-T的限定实机与原路径保持](../docs/evidence/application-discovery-negotiable-20261019.json)、[原Fixed-T失败](../docs/evidence/application-discovery-real-attempts-20261019.json)、[接口边界](../docs/reference/application-discovery.md) | 两U的apps-only显式release正向及七尺寸/Owned/C-Python保持取得准确新artifact证据。旧保持测试误选Fixed-T，原失败仍有效；不称已证明其物理根因。caller-loss/TTL/管理STOP/期限/部分初始化、同行业务及完整部署权限仍缺，完整资格不升级 |
| C／Python目录观察视图 | [3bdSDK／80e运行／d912离线核对的限定实机](../docs/evidence/controller-language-observer-20261019.json)、[原限定离线](../docs/evidence/controller-language-offline-20261018.json) | 同一Rust stream/executor，实际普通进程与映射库、新generation及原业务保持。缺失proof异常与原失败保留；修复校验器未作为新运行工具。非完整SDK/状态流/扫描租约或形式化资格 |
| 普通观察者 Runtime 目录流 | [fd0服务／4d9工具的目录观察与原路径保持](../docs/evidence/controller-directory-observer-20261018.json) | 实际 Rust/slctl、同daemon与两角色新generation；不是Native Ready、Down或drain。该记录不涵盖新增C/Python或发现租约；pre-Runtime完整状态及发现租约的实机资格仍缺；该记录未取得新形式化证明 |
| User Native 返回跨 controller 退休 | [77服务／143工具两角色与原两FAIL](../docs/evidence/native-controller-return-20261018.json) | 固定target slot0、User CUTC；精确owner屏障、迟到fd拒绝、真实peer结清、同daemon新generation后16次回复。不是Service/dynamic、完整fd组合、Kernel ref/callback/UAF或自然恢复资格 |
| 实际 Native 返回与 Connection 退休 | [26b服务／ae40工具的四切片与旧版反向FAIL](../docs/evidence/native-return-connection-retirement-20261018.json) | Service/User各发起/接受，真实peer Down、迟到fd拒绝、旧对象/OS fd收敛及原业务；SDK live拒绝不是直接broker探针。Dynamic/controller移除、完整fd/期限及Kernel ref/callback/UAF/drain仍缺 |
| Connection 创建排空与独立物理投影 | [生产函数／原反例及限定离线](../docs/evidence/native-creation-drain-offline-20261018.json)、[26b原路径实机保持](../docs/evidence/native-creation-drain-real-20261018.json) | 同一owner创建guard、惰性初始化及物理发布解耦；原有限fixture/保持范围不变，后续真实切片见上行，原fd失败未归因 |
| 历史6dc Native 创建离开异步 worker | [生产 helper／guard／fd 离线](../docs/evidence/native-bind-offload-offline-20261018.json)、[原路径限定实机](../docs/evidence/native-bind-offload-real-20261018.json) | 原服务和VM执行源为6dc，终态修复d538仅离线；它们的资格不转授26b或整个当前HEAD |
| 终态检查与证据可信度 | 各自产物报告及[通用退出契约](../docs/reference/vm-gate-inputs.md#运行终态与退出凭据) | 原6dc接受篡改的反例保留；26b确由新VM执行，负对照仍属离线，不能回写旧VM身份或代替实际故障门禁 |
| 原 Down 超时 | [原七尺寸整体FAIL](../docs/evidence/native-service-owner-preservation-20261018.json)、[四轮未复现UNPROVED](../docs/evidence/down-passive-diagnostic-20261018.json) | 后续新产物的253门禁成功不覆盖原FAIL，不证明稳定性或根因修复；实机被动失败窗口仍未取得 |
| 普通应用、SDK、SSAP与权限 | [实际接口](../docs/reference/interfaces.md)、下方各自产物的资格及[证据入口](../docs/evidence/index.md) | 原生准入、策略批准、加密/认证、SSAP完成和对端应用处理分别表达；历史C/Python、Agent等资格不转授新产物 |
| Runtime／Session／Grant／credit／Ticket | [唯一架构](architecture.md)与对应限定报告 | 旧代际、在途义务和未知完成不因关闭或缓存而消失；NOCP真实性、复用屏障及完整竞争组合仍需各自门禁 |
| 部署、恢复与发布 | [唯一计划](implementation-plan.md)、原部署与分包记录 | 基础部署不等于跨版本升级回滚、发布或新硬件资格；自然故障根因和非人工恢复继续开放 |

本线程硬件范围仅由[资源配置](lab-resource-policy.json)授权；当前逐设备型号、占用和
实机资格在本地准确记录中核对，公开历史映射不作为当前启动依据。两组其他口属于
另一线程；同 VID/PID 或旧端口不证明型号。混合下载必须验证每设备固件来源；
运行期 HCC 不证明冷 ROM 自动选择。QMP、拔插和切电不能替代自然恢复。
启动前的 live libvirt 占用守卫及限定离线结果见
[资源边界记录](../docs/evidence/shared-allocation-launch-guard-20261019.json)；
它不更新上述服务/内核/实机资格，特权 fd 可见性和之后的非协作操作仍有限制。

各批准确身份、计数、原失败和限制只在对应报告及下方结构化记录维护；
后续顺序以唯一实施计划和 `qualification_view.current_batch` 为准，避免历史批次的
“下一批”文字成为第二套当前计划。目录撤回、精确owner拒绝、物理Down和引用排空
分别验收；原Core/owner混淆、扫描EBUSY/清理0x0b及共同5秒Down失败仍保留。
数据／SSAP／安全／多通道和四设备继续并行，不新增Engine或状态来源；
完整S0–S6及所有原始验收范围不变。

逐轮旧说明保留于[准确176f077快照](https://github.com/OpenSparklink/sparklink/blob/176f077b627c19b8be947075968d95a440a643b5/project/current-capabilities.md)
及证据/历史入口；以下生成记录保留原PASS、FAIL和UNPROVED及全部required范围。
本页不再堆叠逐轮进度或另维护“最新资格”计数表。

## 选定产物与来源

<!-- qualification-summary:start -->
以下摘要由 `project/qualification-records.json` 生成；不以文档提交替代编译身份。

当前实施批次（不是新产物资格，直接读取唯一记录）：
```json
{
  "id": "WP08-WP16-WP17-U22-write-original-deadline",
  "state": "WRITE_ORIGINAL_DEADLINE_SOURCE_OFFLINE_AVAILABLE",
  "production_behavior": "Extend the existing Provider original-deadline runner and actual C/Python caller checks to verified type0 WRITE. Preserve requester/Provider original deadlines; a matching late SDK call must return ETIMEDOUT, leave app value unchanged and preserve actor terminal. Require paired original request, complete bounded response window and subsequent ordinary channel business. No new Engine, success response or recovery claim.",
  "scope": "Full S0-S6,19WP,10FV,12DG and original acceptance unchanged; drivers/net/slkd,unique Session/Grant/credit/Ticket,VM-only,SDK110 explicit model,shared build lock and12/VM8 budget retained. UserHost remains low-priority planning.",
  "work_packages": [
    "WP08",
    "WP16",
    "WP17"
  ],
  "records": [],
  "predecessor_archive": {
    "history": "batch_history",
    "id": "WP08-WP16-WP17-U22-write-pending-withdrawal",
    "canonical_sha256": "7c2e080ed3d91d234981eb3b0d796531d39a5e4eaf2fba5b66642b6ed2b1a4f7"
  },
  "implementation_sources": {
    "public_source": "f128face4e28efa4d0e1ded2faa84cbc50ade401",
    "scope": "Source/offline identity; compiled/execution/report identities and private hardware scope remain separate."
  },
  "invariants": [
    "Original controller/generation/lifetime/security epoch/TCID/PI and original absolute deadline; Native admission before requesting application effects and before response. Snapshot checks cannot roll back an already started application effect.",
    "Write-only type0 property, original unique owner, one-time binding, no stored value fallback. Permission approval and application success remain separate.",
    "Bounded original server queue and callback; WriteCommand never owes a response. Verified WriteReq requires actual accepted bytes; malformed, late, mismatched replies cannot produce success.",
    "One front-of-queue future retains only its original Wire reference. Cancellation releases that reference; no detached task, extra Session or new data path.",
    "Original production paths and all original U22 conditions remain. Offline fixture transport is explicit cfg(test); it is not Native/RF proof.",
    "READ/WRITE use one bounded Dispatcher with 16 shared slots. Only final request and callback release returns a slot; readiness fd duplicates do not retain reply authority.",
    "Typed WRITE snapshot preserves original metadata and complete value, no truncation. Invalid reply does not consume reply authority; successful verify requires the exact proposed value.",
    "Local reply acceptance is separate from callback drain and peer application handling. Partial endpoint-install failure removes only this attempt's newly installed endpoint; owner-close and original deadline remain authoritative.",
    "Explicit write-only 0x06 publisher and original parameterized controller/generation. Wrong value/token does not consume the pending request; no implicit acceptance or staging readback.",
    "Input budget includes full 2042-byte value plus finite command overhead. Local accepted memory, SDK reply acceptance and actual remote callback receipt remain separate."
  ],
  "offline_checks": {
    "runner": {
      "result": "PASS",
      "tests": 160,
      "scope": "New typed verified WRITE deadline/late reply/no-effect, both-end absence/identity/clock/business/manifest negative controls, exact CLI/boot and retained READ/WRITE/unregister/channel/target checks."
    },
    "external": "Actual C/Python private-D-Bus SDK check PASS including verified WriteReq expiry and unchanged prior app value; broker metadata/transport fixtures, no Engine/kernel/RF claim.",
    "strict": "libsparklink --all-targets Clippy -D warnings, locked/offline Rust1.96.1, fmt, Python compile, shell syntax PASS. Eight-job global build lock retained.",
    "docs": "Locked strict HTML/inventory results recorded in final delivery; no device operation by docs.",
    "failures": "Wrong-worktree invocation and shared constant shadow failure retained; corrected invocation/import alias without assertion weakening. Formatting-only changes rechecked against actual C/Python test."
  },
  "offline_status": "ONLY_NAMED_CHECKS_PASS",
  "formal_status": "NO_NEW_PROOF",
  "hardware_status": "Exact-artifact qualification is maintained in authorized local records; public source/offline summary neither grants hardware qualification nor infers execution absent.",
  "exit_conditions": [
    "Actual typed verified WRITE callback before its original deadline; valid matching late answer invokes SDK and is rejected, no app value applied.",
    "Paired original request, bounded full response window, persistent terminal and after-expiry ordinary business; finite clock assumptions remain explicit.",
    "Fresh tool/input identity, complete terminal and fail-closed evidence reconstruction, negative controls and private retained material closure.",
    "Keep existing positive WRITE and READ/withdrawal qualification identities separate; complete owner-loss/Down and remaining original U22 operations next."
  ],
  "remaining_conditions": [
    "WRITE pending owner loss, connection Down and daemon/restart combinations with original deadlines, old replies and peer isolation.",
    "Command/long value/method/descriptor/update and all original U22 SSAP acceptance.",
    "Full S0-S6/19WP/10FV/12DG, natural root cause/nonmanual recovery and unchanged data/security/Profile/deployment/release scope."
  ],
  "next": [
    "Reuse original shared pending-case runner for WRITE owner exit, then Down and old-lifetime combinations.",
    "Continue long values and remaining SSAP operations through unique Engine/Session; data/security remain parallel.",
    "UserHost remains P4 and full control-plane competition is not a collective prerequisite."
  ],
  "issues": [
    "OpenSparklink/sparklink#22",
    "OpenSparklink/sparklink#3",
    "OpenSparklink/linux#6",
    "OpenSparklink/linux#17"
  ],
  "issue_sync": {
    "issue": "sparklink#22",
    "state": "open",
    "body_sha256": "c28c37ba25e135ec73be72c6a13e5be25f5ecc06b516d6644cf4a01d93b4681e",
    "source_offline_only": true,
    "original_six_criteria_unchanged": true
  },
  "public_scope": "Only source/offline/disposition. Private device details and execution identities remain local.",
  "issue_maintenance": {
    "record": "project/issue-maintenance-20261026.json",
    "state": "BOUNDED_MAINTENANCE_COMPLETE_ORIGINAL_SCOPE_OPEN",
    "last_readback": "project/issue-maintenance-20261026.json#/followup_readback",
    "scope": "Bounded maintenance remains complete; U22 current source/offline table replaced, original six criteria and parent stay open."
  },
  "qualification_boundary": "Public source/offline only; original private exact-artifact evidence does not qualify a whole latest tree."
}
```


选定保留产物（不是当前工作树整体资格）：**K2fc/Ud9：共享发现显式release及Negotiable-T七尺寸/Owned/C-Python限定实机**。
仅记录范围：`real_device` / `PASS`。
compiled_kernel `2fc210af68ee3bce0eed3553117d8be635dfdd15`。
compiled_userspace `d9dc373120cbb173be195647d22da10c25987641`。
executed_host_tools `d9dc373120cbb173be195647d22da10c25987641`。
executed_guest_tools `d9dc373120cbb173be195647d22da10c25987641`。
compiled_kernel_helpers `c39686a8095818d8aed9e42ac1d15e0eee47e1e6`。
evidence_validator `6c7a2e31bd7c99a171fd435a3e5c0fde14090290`。
[准确范围与剩余条件](../docs/evidence/application-discovery-negotiable-20261019.json)。

限定边界由同一记录生成；计数不代替必需门禁、假设或范围：
```json
{
  "app_discovery_observations": 18,
  "app_discovery_readers": 4,
  "application_sizes": [
    61,
    249,
    250,
    253,
    254,
    255,
    2042
  ],
  "business_round_trips": 66,
  "c_python_ssap_api_calls": 48,
  "c_python_ssap_operations": 16,
  "captured_usb_packets": 39537,
  "compiled_kernel": "2fc210af68ee3bce0eed3553117d8be635dfdd15",
  "compiled_userspace": "d9dc373120cbb173be195647d22da10c25987641",
  "connection_advertising": "explicit negotiable-t;wire mode3 role0/posture0-1",
  "distinct_discovery_RX": 16,
  "owned_ssap_checks": 8,
  "rf_rounds": 198,
  "vm_runs": 9
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
| ExchangeInfo等待期间撤权／原回复／daemon fd收敛：有限实机通过；完整部分初始化开放 | `real_device` | `PASS` |
| 稳定服务owner及取消清理：生产函数/私有D-Bus/OSfd限定离线通过 | `offline` | `PASS` |
| 稳定服务owner：CMTC/ExchangeInfo撤权及SSAP原期限有限实机保持 | `real_device` | `PASS` |
| 稳定服务owner：原七尺寸整体FAIL，253迟到Down保留；六轮限定通过 | `real_device` | `FAIL` |
| 被动Down诊断：四轮原门禁有限通过、未复现；真实失败观察与根因未证明 | `real_device` | `UNPROVED` |
| Native创建离开异步worker：生产guard/OSfd与通用终态有限离线通过 | `offline` | `PASS` |
| 6dc服务十轮有限实机保持；d538仅离线校验，不授Native完整排空资格 | `real_device` | `PASS` |
| 连接级Native创建排空与独立物理投影：限定离线通过 | `offline` | `PASS` |
| 26b十轮原路径实机保持：真实Native返回/parent屏障仍缺 | `real_device` | `PASS` |
| 26b服务/ae40工具：四个真实Native返回/Connection退休切片及旧发布耦合反向FAIL | `real_device` | `PASS` |
| 77服务/143工具：真实User返回跨controller退休两角色、新generation业务；原两FAIL保留 | `real_device` | `PASS` |
| U247→Udb724→U247：实际开发Debian修订升级/回滚、匹配SDK和状态保留限定通过 | `virtual_integration` | `PASS` |
| fd0服务/4d9工具：默认observer真实目录变化，两角色与七尺寸/Owned保持；原启动前FAIL保留 | `real_device` | `PASS` |
| 3bdSDK/80e运行/d912离线校验：真实C/Python目录观察及七尺寸保持，反例保留 | `real_device` | `PASS` |
| Scoped discovery daemon/Rust SDK/CLI：397+397及封存14项限定离线 | `offline` | `PASS` |
| 实际生产scanner epoch：初始/任意u64单步/八步及错误性质负对照 | `formal_bounded` | `PASS` |
| 真实共享发现显式release限定正向；整轮建链保持失败及其他门禁仍缺失 | `real_device` | `FAIL` |
| K2fc/Ud9：共享发现显式release及Negotiable-T七尺寸/Owned/C-Python限定实机 | `real_device` | `PASS` |

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
