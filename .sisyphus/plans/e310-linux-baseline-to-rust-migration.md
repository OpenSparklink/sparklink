# ANTSDR E310 全栈审计与后续执行计划（Linux基线优先 → 裸机Rust迁移）

## TL;DR

> **Quick Summary**: 当前关键事实是 AD9361 已初始化、系统可启动到 Linux、`sle_ctrl` 与 FunctionFS 可运行，但 TX/RX 链路异常且 `/dev/uio*` 初始缺失；先把 Linux 基线做成可复现可验证真机闭环，再分阶段迁移到 bare-metal Rust。
>
> **Deliverables**:
> - E310 Linux 运行基线证据包（启动、驱动、UIO、DMA、USB、日志）
> - TX/RX 异常根因收敛（优先 UIO/DT/PL 绑定路径）
> - 可重建 SD 镜像与制品溯源链
> - 标准-实现-测试追踪矩阵
> - 裸机 Rust 分阶段迁移蓝图（含回退策略）
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 3 implementation waves + FINAL verification wave
> **Critical Path**: T1 → T4 → T7/T8 → T11/T12 → T16 → F1-F4

---

## Context

### Original Request
用户要求对完整星闪软硬件项目进行全量 review（SDR 硬件、Linux 驱动/内核、用户态工具、文档标准），识别问题并给出完整后续规划；重点关注 SDR 固件/启动链未完全打通、ADI 驱动/BSP 历史受阻，并探索裸机 Rust 路线。

### Interview Summary
**Key Discussions**:
- 平台已明确：**ANTSDR E310 (Zynq Z-7020 + AD9361)**。
- 用户选择策略：**先打通 Linux 基线，再迁移到裸机 Rust**。
- 真实故障画像：**RF 能初始化，但 TX/RX 数据链路异常**。
- 用户允许继续在线诊断，优先串口日志路径。

**Research Findings**:
- SparkLink userspace 与 Linux SparkLink 协议实现总体成熟；主要风险在 SDR 真机集成层。
- SDR 仓库已有大量 HDL/BSP/脚本/文档；制品链存在但可追溯性与一致性需落地验证。
- High-accuracy 基线已锁定：**权威 SD 启动链采用 `sw/linux/bsp/Makefile sdimg` 产物集**（`BOOT.bin + boot.scr + sle_e310.itb`）；`mk_sdcard.sh` 的 `zImage/devicetree/uramdisk/uEnv` 流程视为 legacy 分支，仅用于兼容性对照，不作为主验收链。
- 实机证据：
  - 串口可登录，Linux 正常启动。
  - `ad9361_probe` 成功。
  - FunctionFS 端点存在。
  - `usb0` 为 `169.254.x.x`（非文档预期 `192.168.2.1`）。
  - `/dev/uio*` 初始缺失；手工 bind 后出现 `/dev/uio0-2`。
  - `uio_pdrv_genirq` 对 `40000000.sle-phy` 报错：**more than 5 I/O memory resources**。

### Metis Review
> 本会话中 Metis 子代理调用异常中断，改用主会话内人工 gap analysis（已在本计划中补齐 guardrails、验收与边界）。

---

## Work Objectives

### Core Objective
构建一个可重复、可证据化、可回退的 E310 Linux 真机基线，定位并修复 TX/RX 链路异常主因，并产出向 bare-metal Rust 的低风险迁移路径。

### Concrete Deliverables
- 运行时证据包（串口、dmesg、service、UIO、IIO、USB、网络、FPGA manager）
- UIO/DT/PL 绑定修复方案与验证结果
- TX/RX 双向链路验证报告与失败定位坐标
- SD 镜像重建流程与制品 manifest
- TXS 标准追踪矩阵 + SparkLink 集成适配检查单
- 裸机 Rust 迁移路线图（阶段、边界、退出条件）

### Definition of Done
- [ ] 在同一板卡上可重复完成“启动→服务→UIO→TX/RX链路验证”闭环，至少 3 次一致通过
- [ ] 关键异常（UIO 多资源、网络地址漂移、空日志）被修复或有明确、可自动检查的阻断条件
- [ ] 所有证据文件落地到 `.sisyphus/evidence/`
- [ ] 迁移计划含明确“继续 Linux / 进入裸机 Rust / 回退 Linux”判定门

### Must Have
- 保留并固化 Linux 路线作为真机基线
- 对 TX/RX 异常做可重复定位与验收
- 迁移到裸机 Rust 必须建立在 Linux 基线稳定之上

### Must NOT Have (Guardrails)
- 不以“换架构”掩盖当前 Linux 基线问题
- 不在无证据情况下宣称链路打通
- 不跳过可复现步骤与日志/证据沉淀
- 不引入无法回退的单向改动

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION in acceptance checks**: 任务验收由执行 agent 自动完成（已连接硬件为前提）；不允许“人工目测通过”作为验收标准。

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: YES (Tests-after)
- **Framework**: pytest/cocotb + shell diagnostics + service/driver runtime checks
- **If TDD**: N/A（本计划以系统集成与运行时验证为主，采用 tests-after）

### QA Policy
每个任务均包含 agent-executed QA scenarios（happy + negative），证据存放：
`.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`

- **Frontend/UI**: N/A
- **TUI/CLI**: interactive_bash / serial / shell commands
- **API/Backend**: curl/ssh/ip/ifconfig/system files
- **Driver/FPGA/Runtime**: dmesg/sysfs/procfs/dev nodes/log files

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (foundation, start immediately):
├── Task 1: Runtime baseline evidence bundle [unspecified-high]
├── Task 2: Boot/SD artifact provenance map [quick]
├── Task 3: Live DT/platform resource map [unspecified-high]
├── Task 4: UIO binding root-cause isolation [deep]
└── Task 5: USB network determinism baseline [quick]

Wave 2 (Linux baseline remediation):
├── Task 6: S99sle startup hardening [unspecified-high]
├── Task 7: DT/UIO compatibility refactor [deep]
├── Task 8: UIO driver binding strategy closure [deep]
├── Task 9: sle_ctrl observability closure [quick]
└── Task 10: DMA/PHY smoke-test harness [unspecified-high]

Wave 3 (end-to-end validation + migration preparation):
├── Task 11: TX chain end-to-end verification [unspecified-high]
├── Task 12: RX chain end-to-end verification [unspecified-high]
├── Task 13: SD image reproducibility pipeline [quick]
├── Task 14: Standards traceability matrix [writing]
├── Task 15: Bare-metal Rust staged migration blueprint [deep]
└── Task 16: SparkLink integration checkpoint [deep]

Wave FINAL (after all implementation tasks):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA execution (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present consolidated report -> explicit user okay

Critical Path: T1 → T4 → T7/T8 → T11/T12 → T16 → F1-F4
Parallel Speedup: ~60-70% vs sequential
Max Concurrent: 6
```

### Dependency Matrix (FULL)

- **T1**: Blocked By: None | Blocks: T4, T6, T9, T11, T12
- **T2**: Blocked By: None | Blocks: T13, T15
- **T3**: Blocked By: None | Blocks: T4, T7, T8
- **T4**: Blocked By: T1, T3 | Blocks: T7, T8, T10
- **T5**: Blocked By: None | Blocks: T11, T12, T16
- **T6**: Blocked By: T1 | Blocks: T9, T11, T12
- **T7**: Blocked By: T3, T4 | Blocks: T8, T10, T11, T12
- **T8**: Blocked By: T4, T7 | Blocks: T10, T11, T12
- **T9**: Blocked By: T1, T6 | Blocks: T11, T12, T16
- **T10**: Blocked By: T4, T7, T8 | Blocks: T11, T12
- **T11**: Blocked By: T5, T6, T7, T8, T9, T10 | Blocks: T16
- **T12**: Blocked By: T5, T6, T7, T8, T9, T10 | Blocks: T16
- **T13**: Blocked By: T2 | Blocks: T15
- **T14**: Blocked By: T1, T3, T11, T12 | Blocks: T16
- **T15**: Blocked By: T2, T13 | Blocks: T16
- **T16**: Blocked By: T5, T9, T11, T12, T14, T15 | Blocks: F1-F4

### Agent Dispatch Summary

- **Wave 1**: 5 tasks
  - T1 `unspecified-high`, T2 `quick`, T3 `unspecified-high`, T4 `deep`, T5 `quick`
- **Wave 2**: 5 tasks
  - T6 `unspecified-high`, T7 `deep`, T8 `deep`, T9 `quick`, T10 `unspecified-high`
- **Wave 3**: 6 tasks
  - T11 `unspecified-high`, T12 `unspecified-high`, T13 `quick`, T14 `writing`, T15 `deep`, T16 `deep`
- **Wave FINAL**: 4 tasks
  - F1 `oracle`, F2 `unspecified-high`, F3 `unspecified-high`, F4 `deep`

---

## TODOs

- [ ] 1. 建立 E310 运行时基线证据包

  **What to do**:
  - 固化一组只读诊断命令（串口登录、`dmesg`、`ifconfig`、`ps`、`/sys`、`/proc`），生成一次性证据包。
  - 将证据输出统一落地到 `.sisyphus/evidence/task-1-*`，并记录采集时间、板卡标识、内核版本。
  - 输出“当前状态摘要”：启动成功项、异常项、阻断项。

  **Must NOT do**:
  - 不执行会改变系统状态的持久化改动（写 flash、改分区、覆盖镜像）。
  - 不跳过失败命令；失败必须纳入证据与摘要。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 真机运行态诊断，信息面广且需高可靠收敛。
  - **Skills**: [`sparklink-kernel-dev`]
    - `sparklink-kernel-dev`: 涵盖内核/用户态/QEMU/接口联动思路，适合系统性证据采集。
  - **Skills Evaluated but Omitted**:
    - `sparklink-userspace-dev`: 该任务以运行态证据采集为主，不是新增用户态功能。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 T2/T3/T5）
  - **Blocks**: T4, T6, T9, T11, T12
  - **Blocked By**: None

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/README.md` - 运行后手动检查项（`/dev/uio*`、`/var/log/sle_ctrl.log`、FunctionFS）来源。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/README.md` - 预期系统架构（USB Gadget + IIO + UIO + daemon）基线。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/deploy.sh` - 期望运行时状态与实际诊断项对应（服务、bitstream、驱动绑定）。

  **Acceptance Criteria**:
  - [ ] 证据文件至少包含：`dmesg`、网络接口、进程状态、UIO/IIO 节点、FPGA manager 状态。
  - [ ] 证据汇总中明确标注“已确认正常 / 异常 / 未确认”三类条目。
  - [ ] 证据文件路径可被后续任务直接复用。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 基线采集成功
    Tool: Bash (serial + shell)
    Preconditions: 板卡上电并出现串口 login 提示
    Steps:
      1. 通过 /dev/ttyUSB2 登录并执行固定诊断命令集。
      2. 将输出保存为 .sisyphus/evidence/task-1-runtime-baseline.log。
      3. 断言日志内包含 "ad9361_probe"、"fpga_manager"、"sle_ctrl" 关键字。
    Expected Result: 形成完整基线日志并可复现。
    Failure Indicators: 串口不可用、日志不完整、关键字段缺失。
    Evidence: .sisyphus/evidence/task-1-runtime-baseline.log

  Scenario: 串口或登录失败路径
    Tool: Bash
    Preconditions: 串口节点缺失或登录失败
    Steps:
      1. 执行设备枚举（ls /dev/tty* + lsusb）。
      2. 保存失败上下文与时间戳。
    Expected Result: 失败原因可归类（设备不存在/权限/系统未启动）。
    Evidence: .sisyphus/evidence/task-1-runtime-baseline-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-1-runtime-baseline.log`
  - [ ] `.sisyphus/evidence/task-1-runtime-baseline-error.log`（若失败路径触发）

  **Commit**: YES (groups with 1)
  - Message: `fix(e310-baseline): add reproducible runtime evidence collection`
  - Files: `sw/linux/` scripts/docs + `.sisyphus/evidence/` manifest
  - Pre-commit: `shellcheck` / basic script lint

- [ ] 2. 建立启动制品与 SD 镜像溯源清单

  **What to do**:
  - 固定并盘点**权威产物链**：`sw/linux/bsp/Makefile sdimg` 输出 `BOOT.bin`、`boot.scr`、`sle_e310.itb`。
  - 对比并标注 legacy 产物链：`mk_sdcard.sh` 输出 `zImage/devicetree/uramdisk/uEnv`（仅兼容参考）。
  - 盘点介质侧产物：`BOOT.bin`、`boot.scr`、`sle_e310.itb`（及可见分区结构）。
  - 生成 artifact manifest（来源、生成命令、版本、校验值）。

  **Must NOT do**:
  - 不直接写 SD 卡或 flash。
  - 不把“存在文件”误判为“版本一致”。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 以清单化、核对为主，执行路径确定。
  - **Skills**: [`sparklink-kernel-dev`]
    - `sparklink-kernel-dev`: 覆盖 boot/QEMU/内核用户态链路的构建习惯。
  - **Skills Evaluated but Omitted**:
    - `writing`: 需要结合实际介质与脚本验证，不仅是文档编辑。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 T1/T3/T5）
  - **Blocks**: T13, T15
  - **Blocked By**: None

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/Makefile` - 权威 `sdimg` 产物定义（BOOT.bin + boot.scr + sle_e310.itb）。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/boot/boot.bif` - BOOT.BIN 组成来源。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/scripts/gen_fsbl.tcl` - FSBL 生成入口。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/scripts/sle_e310.its` - FIT 组合定义。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/scripts/mk_sdcard.sh` - legacy 镜像链对照来源。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/deploy_jtag.sh` - JTAG/QSPI 烧录流程和偏移。

  **Acceptance Criteria**:
  - [ ] `BOOT.bin + boot.scr + sle_e310.itb` 被明确标记为主验收链，并在 manifest 中标注为 authoritative。
  - [ ] 输出 `artifact-manifest`，包含“源码路径 → 生成命令 → 目标介质路径”。
  - [ ] 每个关键产物均有“已验证存在/缺失/版本未知”状态。
  - [ ] 明确区分 SD 启动与 QSPI 启动产物链，以及 legacy 分支状态。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 制品链路核对成功
    Tool: Bash
    Preconditions: 源码仓库可读，SD 卡可读（若在主机）
    Steps:
      1. 扫描并记录 boot/fsbl/fit/sdimg 相关脚本与模板。
      2. 读取介质上可见启动文件并计算 sha256。
      3. 生成 .sisyphus/evidence/task-2-artifact-manifest.md。
    Expected Result: 产物来源、命令、状态三者完整对应。
    Failure Indicators: 文件存在但来源不可追踪、关键制品无状态标注。
    Evidence: .sisyphus/evidence/task-2-artifact-manifest.md

  Scenario: 介质不可读/状态漂移
    Tool: Bash
    Preconditions: SD 卡读卡器异常或分区不可见
    Steps:
      1. 记录 lsblk/挂载状态与失败信息。
      2. 标记为“介质状态不稳定”并回退到源码侧清单。
    Expected Result: 问题被显式升级，不阻塞其余任务并可复查。
    Evidence: .sisyphus/evidence/task-2-artifact-media-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-2-artifact-manifest.md`
  - [ ] `.sisyphus/evidence/task-2-artifact-media-error.log`（如触发）

  **Commit**: YES (groups with 1)
  - Message: `docs(e310-boot): add artifact provenance manifest`
  - Files: BSP/boot docs + evidence manifests
  - Pre-commit: markdown lint/check links

- [ ] 3. 建立运行时设备树与平台资源实况映射

  **What to do**:
  - 采集 `/proc/device-tree`、`/sys/bus/platform/devices`、`/sys/class/fpga_manager` 的实况。
  - 明确 `sle-phy`、`sle-preamble`、`sle-aes-ccm` 等节点与驱动绑定关系。
  - 输出“声明 vs 运行时”差异报告（文档期望与实际节点对比）。

  **Must NOT do**:
  - 不仅看 dts 源文件，必须看运行时展开后的 device-tree。
  - 不忽略 missing-node 情况。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要跨 dts、sysfs、运行时状态做严格对照。
  - **Skills**: [`sparklink-kernel-dev`]
    - `sparklink-kernel-dev`: 适合做内核设备模型与运行态映射核查。
  - **Skills Evaluated but Omitted**:
    - `sparklink-userspace-dev`: 当前重点不是用户态接口新增。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 T1/T2/T5）
  - **Blocks**: T4, T7, T8
  - **Blocked By**: None

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/dts/zynq-sle-e310.dts` - 顶层 DT 入口。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/dts/zynq-sle-e310.dtsi` - AD9361/DMA/SLE 节点定义。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/overlay/sle-phy.dtsi` - overlay 模式预期。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/README.md` - 期望启动顺序与节点描述。

  **Acceptance Criteria**:
  - [ ] 产出运行时资源图（地址、节点名、绑定驱动、状态）。
  - [ ] 清晰标注文档与实况偏差（例如 overlay 路径不可用、节点路径差异）。
  - [ ] 后续 UIO 修复任务可直接引用该资源图。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 运行时节点映射成功
    Tool: Bash (serial shell)
    Preconditions: 已登录设备
    Steps:
      1. 读取 /proc/device-tree 与 /sys/bus/platform/devices 关键路径。
      2. 读取 /sys/class/fpga_manager/fpga0/state。
      3. 生成 .sisyphus/evidence/task-3-dt-platform-map.md。
    Expected Result: 节点地址与驱动绑定关系完整可读。
    Failure Indicators: 关键节点缺失或路径不一致未被标注。
    Evidence: .sisyphus/evidence/task-3-dt-platform-map.md

  Scenario: 节点缺失异常
    Tool: Bash
    Preconditions: 关键节点不存在
    Steps:
      1. 记录缺失节点名与预期来源 dts。
      2. 生成阻断报告。
    Expected Result: 能明确是 DT 编译、启动参数还是 overlay 机制问题。
    Evidence: .sisyphus/evidence/task-3-dt-platform-missing.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-3-dt-platform-map.md`
  - [ ] `.sisyphus/evidence/task-3-dt-platform-missing.log`（如触发）

  **Commit**: YES (groups with 1)
  - Message: `docs(e310-dt): add runtime platform resource map`
  - Files: mapping docs/evidence
  - Pre-commit: markdown consistency checks

- [ ] 4. 定位并闭环 UIO 绑定根因（多资源限制）

  **What to do**:
  - 复现实锤问题：`uio_pdrv_genirq ... more than 5 I/O memory resources`。
  - 确认 `sle-phy` 节点 `reg` 资源数量与 generic UIO driver 上限冲突。
  - 形成修复选项对比：
    1) 调整 DT 资源拆分；
    2) 使用/扩展专用 `sle_phy_uio` 驱动；
    3) 保留多节点分治并同步 userspace 映射。

  **Must NOT do**:
  - 不接受“手工 bind 一次成功”作为长期解。
  - 不引入会破坏 ADI DMA/ADC 节点的临时绕过。

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 涉及驱动模型、设备树资源、用户态映射一致性三方约束。
  - **Skills**: [`sparklink-kernel-dev`, `sparklink-abi-fix`]
    - `sparklink-kernel-dev`: 内核设备与驱动链路分析。
    - `sparklink-abi-fix`: 处理资源映射与结构约束的一致性检查思路。
  - **Skills Evaluated but Omitted**:
    - `sparklink-userspace-dev`: 根因在内核/DT/驱动绑定层。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1（关键串行）
  - **Blocks**: T7, T8, T10
  - **Blocked By**: T1, T3

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/driver/sle_phy_uio.c` - 专用 UIO 驱动路径与能力边界。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/dts/zynq-sle-e310.dtsi` - `sle-phy` 资源定义来源。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/README.md` - 期望 UIO 拓扑与寄存器区域说明。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/deploy.sh` - 当前运行流程中对驱动绑定的隐式假设。

  **Acceptance Criteria**:
  - [ ] 明确给出主因判定（资源数限制/驱动路径/节点定义不匹配）。
  - [ ] 给出唯一推荐修复路径及放弃路径理由。
  - [ ] 推荐路径可通过自动化命令验证 `/dev/uio*` 稳定出现。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 根因复现与归类
    Tool: Bash (serial shell)
    Preconditions: 平台节点已可见
    Steps:
      1. 执行当前绑定流程并捕获 dmesg。
      2. 捕获报错 "more than 5 I/O memory resources"。
      3. 对照 DT reg 资源数量与驱动限制，输出结论。
    Expected Result: 根因结论唯一且可被日志支持。
    Failure Indicators: 仅有现象无根因链路；结论不可复现。
    Evidence: .sisyphus/evidence/task-4-uio-root-cause.md

  Scenario: 修复候选否定验证
    Tool: Bash
    Preconditions: 存在多个候选修复路径
    Steps:
      1. 对每个候选定义最小验证命令。
      2. 记录失败候选的具体失败点。
    Expected Result: 至少 1 条路径可行，其他路径有证据否决。
    Evidence: .sisyphus/evidence/task-4-uio-option-comparison.md
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-4-uio-root-cause.md`
  - [ ] `.sisyphus/evidence/task-4-uio-option-comparison.md`

  **Commit**: YES (groups with 1)
  - Message: `fix(e310-uio): isolate root cause for multi-resource binding failure`
  - Files: dt/driver/runtime-doc updates
  - Pre-commit: dtc validation + runtime smoke checks

- [ ] 5. 固化 USB 网络行为与可达性基线

  **What to do**:
  - 明确当前 `usb0` 获取 `169.254.x.x` 的真实机制（RNDIS 自动链路本地地址 vs 期望静态地址）。
  - 对齐文档与脚本中的 `192.168.2.1` 假设，给出统一网络策略（静态/链路本地/双模式）。
  - 建立“可达性检测顺序”（USB 枚举→接口 up→IP 获取→SSH 可达）。

  **Must NOT do**:
  - 不强行写死单一 IP 而忽略固件实际行为。
  - 不把网络可达性当作 TX/RX 成功的替代指标。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 网络策略收敛与脚本文档一致性修正。
  - **Skills**: [`sparklink-userspace-dev`]
    - `sparklink-userspace-dev`: 适合处理工具脚本与用户态部署接口对齐。
  - **Skills Evaluated but Omitted**:
    - `sparklink-kernel-dev`: 该任务偏部署/运维策略，不是内核逻辑改造。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 T1/T2/T3）
  - **Blocks**: T11, T12, T16
  - **Blocked By**: None

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/README.md` - 当前文档网络假设。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/deploy.sh` - `E310_HOST=192.168.2.1` 假设来源。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/gadget/sle_gadget.sh` - gadget 创建流程。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/doc/sd_card_image_plan.md` - 设计阶段网络期望。

  **Acceptance Criteria**:
  - [ ] 网络策略文档明确“默认行为 + 异常行为 + 自动探测逻辑”。
  - [ ] 部署脚本具备可配置 IP/自动探测 fallback。
  - [ ] SSH 可达性检测不再依赖单一固定地址。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: USB网络自动探测成功
    Tool: Bash
    Preconditions: 板卡已枚举 0456:b674
    Steps:
      1. 识别主机侧 USB NIC 并检测 IPv4。
      2. 对候选地址执行 ping/ssh 探测。
      3. 输出当前有效管理地址。
    Expected Result: 在不硬编码单地址前提下得到可达路径。
    Failure Indicators: 只能依赖手工猜测地址。
    Evidence: .sisyphus/evidence/task-5-usb-network-baseline.log

  Scenario: 地址漂移容错
    Tool: Bash
    Preconditions: 设备重启后 IP 改变或回落 link-local
    Steps:
      1. 重新执行自动探测流程。
      2. 验证脚本自动更新连接目标。
    Expected Result: 流程可继续，无需手工改脚本。
    Evidence: .sisyphus/evidence/task-5-usb-network-fallback.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-5-usb-network-baseline.log`
  - [ ] `.sisyphus/evidence/task-5-usb-network-fallback.log`

  **Commit**: YES (groups with 1)
  - Message: `fix(e310-net): stabilize usb management path and address discovery`
  - Files: deploy/network docs and scripts
  - Pre-commit: shell lint + dry-run detection

- [ ] 6. 加固 S99sle 启动流程（显式依赖检查）

  **What to do**:
  - 在 S99sle 增加显式前置检查：FPGA manager state、关键 platform 节点、UIO 节点、FunctionFS ready。
  - 将失败路径标准化（退出码、日志、错误码标签）。
  - 保证 stop/start/restart 幂等且可重复。

  **Must NOT do**:
  - 不“吞掉错误”继续启动。
  - 不在失败场景下留下半初始化状态。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 启动流程影响全链路可靠性且需兼顾多失败分支。
  - **Skills**: [`sparklink-userspace-dev`, `sparklink-kernel-dev`]
    - `sparklink-userspace-dev`: 服务脚本/守护进程启动链。
    - `sparklink-kernel-dev`: 与内核节点/驱动状态一致性。
  - **Skills Evaluated but Omitted**:
    - `quick`: 失败路径和幂等要求超出简单修改。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 T7/T8/T9）
  - **Blocks**: T9, T11, T12
  - **Blocked By**: T1

  **References**:
  - `/etc/init.d/S99sle` (runtime) - 当前逻辑（ADC init + gadget + sle_ctrl）与缺失校验点。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/rootfs_overlay/etc/init.d/S99sle` - 源模板。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/sle_redeploy.sh` - 重部署顺序经验。

  **Acceptance Criteria**:
  - [ ] 启动前置检查失败时能明确报错并退出。
  - [ ] 成功路径可稳定创建 `sle_ctrl`、FunctionFS、UDC 绑定。
  - [ ] 连续三次 restart 不出现资源泄漏或僵尸状态。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 幂等启动成功
    Tool: Bash (serial/ssh)
    Preconditions: 设备已启动
    Steps:
      1. 连续执行 /etc/init.d/S99sle restart 三次。
      2. 每次检查 sle_ctrl 进程、/dev/sle_ffs/ep*、UDC 绑定。
      3. 验证日志中无未处理错误。
    Expected Result: 三次均成功，状态一致。
    Failure Indicators: 第二次后失败、端点缺失、进程丢失。
    Evidence: .sisyphus/evidence/task-6-s99sle-idempotent.log

  Scenario: 前置条件失败处理
    Tool: Bash
    Preconditions: 已知可恢复测试环境
    Steps:
      1. 执行 `echo "" > /sys/class/fpga_manager/fpga0/state 2>/dev/null || true`（若不可写则改为临时移除 `/usr/local/bin/sle_ctrl` 软链接到备份名）。
      2. 执行 `/etc/init.d/S99sle start`。
      3. 验证返回非零并输出错误标签（如 `E_PREREQ_*`）。
      4. 执行恢复步骤（还原 `sle_ctrl`、重启服务）。
    Expected Result: 快速失败、无半初始化残留。
    Evidence: .sisyphus/evidence/task-6-s99sle-failfast.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-6-s99sle-idempotent.log`
  - [ ] `.sisyphus/evidence/task-6-s99sle-failfast.log`

  **Commit**: YES (groups with 2)
  - Message: `fix(e310-init): harden S99sle startup with explicit prechecks`
  - Files: init scripts + docs
  - Pre-commit: shellcheck + runtime restart test

- [ ] 7. 修复 DT 资源建模以匹配 UIO 绑定能力

  **What to do**:
  - 根据 T4 结论重构 `sle-phy` 资源表达（拆分节点或缩减单节点资源数）。
  - 确保 `reg`、`interrupts`、`compatible` 与目标驱动一致。
  - 同步更新 dtsi/dts 与任何 overlay/文档引用。

  **Must NOT do**:
  - 不只改文档不改 DT。
  - 不破坏已工作的 ADI 节点（ad9361/dma/adc/dac）。

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 设备树资源设计直接决定驱动绑定成败。
  - **Skills**: [`sparklink-kernel-dev`, `sparklink-abi-fix`]
    - `sparklink-kernel-dev`: DT/driver 对齐。
    - `sparklink-abi-fix`: 资源映射一致性与边界检查。
  - **Skills Evaluated but Omitted**:
    - `quick`: 涉及系统级回归，不是小修。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 T6/T9）
  - **Blocks**: T8, T10, T11, T12
  - **Blocked By**: T3, T4

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/dts/zynq-sle-e310.dtsi`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/overlay/sle-phy.dtsi`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/README.md`

  **Acceptance Criteria**:
  - [ ] `dtc` 编译通过。
  - [ ] 启动后目标平台节点可稳定绑定目标 UIO 驱动。
  - [ ] 不再出现“more than 5 I/O memory resources”错误。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: DT重构后UIO绑定成功
    Tool: Bash
    Preconditions: 新 DT 已部署并生效
    Steps:
      1. 启动系统并检查 /sys/bus/platform/devices 与 /sys/class/uio。
      2. 断言存在预期 /dev/uio* 节点。
      3. 检查 dmesg 无资源数超限报错。
    Expected Result: UIO 自动/可控绑定稳定。
    Failure Indicators: 节点丢失、绑定失败、报错复现。
    Evidence: .sisyphus/evidence/task-7-dt-uio-bind.log

  Scenario: ADI路径回归
    Tool: Bash
    Preconditions: 系统完成重启
    Steps:
      1. 检查 ad9361 probe、iio:device* 与 DMA 节点。
      2. 比对修复前后状态。
    Expected Result: ADI 关键路径不退化。
    Evidence: .sisyphus/evidence/task-7-dt-adi-regression.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-7-dt-uio-bind.log`
  - [ ] `.sisyphus/evidence/task-7-dt-adi-regression.log`

  **Commit**: YES (groups with 2)
  - Message: `fix(e310-dt): align sle-phy resource model with UIO binding`
  - Files: dts/dtsi/overlay docs
  - Pre-commit: dtc + boot runtime checks

- [ ] 8. 关闭 UIO 驱动策略（generic vs 专用）

  **What to do**:
  - 选择并固化单一路径：`uio_pdrv_genirq` 或 `sle_phy_uio` 专用驱动。
  - 为选择路径补齐加载/绑定自动化（init 或模块加载顺序）。
  - 同步 **Rust `sle_ctrl`** 用户态映射逻辑，避免地址/region 名称漂移。

  **Must NOT do**:
  - 不保留两套冲突策略长期并存。
  - 不依赖手工 `driver_override` 作为最终方案。

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要跨内核驱动和用户态访问统一决策。
  - **Skills**: [`sparklink-kernel-dev`, `sparklink-userspace-dev`]
    - `sparklink-kernel-dev`: 驱动策略收敛。
    - `sparklink-userspace-dev`: 用户态访问路径同步。
  - **Skills Evaluated but Omitted**:
    - `quick`: 方案决策影响后续全部任务。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2（关键串行）
  - **Blocks**: T10, T11, T12
  - **Blocked By**: T4, T7

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/driver/sle_phy_uio.c`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/phy/mod.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/phy/uio.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/rootfs_overlay/etc/init.d/S99sle`

  **Acceptance Criteria**:
  - [ ] 选型文档明确且只有一条默认路径。
  - [ ] 冷启动后无需手工 override 即可得到稳定 UIO 节点。
  - [ ] `phy_ctrl` 可在选定路径下稳定访问目标寄存器。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 冷启动自动绑定
    Tool: Bash (serial)
    Preconditions: 新策略已部署
    Steps:
      1. 冷启动设备。
      2. 检查 /dev/uio* 与 /sys/class/uio/*/name。
      3. 执行最小寄存器读写检查。
    Expected Result: 无手工干预即可完成绑定与访问。
    Failure Indicators: 需要手工 bind、节点不稳定、访问失败。
    Evidence: .sisyphus/evidence/task-8-uio-policy-coldboot.log

  Scenario: 策略冲突检测
    Tool: Bash
    Preconditions: 系统中存在历史残留配置
    Steps:
      1. 检查重复绑定、冲突模块、重复节点。
      2. 输出冲突清单并验证清理流程。
    Expected Result: 系统只保留唯一策略路径。
    Evidence: .sisyphus/evidence/task-8-uio-policy-conflict.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-8-uio-policy-coldboot.log`
  - [ ] `.sisyphus/evidence/task-8-uio-policy-conflict.log`

  **Commit**: YES (groups with 2)
  - Message: `fix(e310-uio): finalize single binding strategy and auto-load path`
  - Files: driver/init/userspace mapping
  - Pre-commit: cold boot + register access smoke

- [ ] 9. 补齐 sle_ctrl 可观测性（日志非空、关键事件标签化）

  **What to do**:
  - 修复 `/var/log/sle_ctrl.log` 长期 0 字节问题（stdout/stderr、缓冲策略、启动参数）。
  - 在关键路径打点：UIO open/map、IIO init、DMA start/stop、DLI EP ready、TX/RX 进入/退出。
  - 增加可控 failpoint（如 `SLE_FAILPOINT=uio_open`）用于自动化负向验证。
  - 增加最小健康检查命令（返回 JSON/text summary）。

  **Must NOT do**:
  - 不只加“打印”，必须保证失败可定位。
  - 不输出含敏感信息的原始密钥材料。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 目标明确，围绕日志与健康检查能力增强。
  - **Skills**: [`sparklink-userspace-dev`]
    - `sparklink-userspace-dev`: 守护进程与 CLI/DBus 可观测实践。
  - **Skills Evaluated but Omitted**:
    - `writing`: 需要代码与运行态验证，不是仅文档。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 T6/T7）
  - **Blocks**: T11, T12, T16
  - **Blocked By**: T1, T6

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/main.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/dli/handler.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/usb/ffs.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/rootfs_overlay/etc/init.d/S99sle`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/deploy.sh`

  **Acceptance Criteria**:
  - [ ] `sle_ctrl.log` 在正常启动后非空且含关键阶段标记。
  - [ ] 失败场景可在日志中定位到子系统（UIO/IIO/DMA/USB）。
  - [ ] 健康检查输出可被脚本自动判断 pass/fail。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 正常启动日志可观测
    Tool: Bash
    Preconditions: 服务可启动
    Steps:
      1. 启动 S99sle。
      2. 检查 /var/log/sle_ctrl.log 大小与关键标签。
      3. 运行健康检查命令并断言 PASS。
    Expected Result: 日志非空且阶段完整。
    Failure Indicators: 日志空、健康检查无输出或失败。
    Evidence: .sisyphus/evidence/task-9-observability-happy.log

  Scenario: 子系统失败可定位
    Tool: Bash
    Preconditions: 支持 failpoint 环境变量
    Steps:
      1. 执行 `SLE_FAILPOINT=uio_open /usr/local/bin/sle_ctrl`（或等价 failpoint 参数）。
      2. 捕获 `/var/log/sle_ctrl.log`。
      3. 校验日志含 `SUBSYS=UIO` 错误标签。
    Expected Result: 错误被精确归因。
    Evidence: .sisyphus/evidence/task-9-observability-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-9-observability-happy.log`
  - [ ] `.sisyphus/evidence/task-9-observability-error.log`

  **Commit**: YES (groups with 2)
  - Message: `fix(e310-obs): make sle_ctrl runtime observable and diagnosable`
  - Files: daemon/init scripts/docs
  - Pre-commit: startup + log assertions

- [ ] 10. 构建 DMA/PHY 最小烟测基准

  **What to do**:
  - 建立最小 TX/RX smoke harness：寄存器配置、DMA 启停、状态寄存器断言。
  - 将 smoke 与 E2E 分层：先证明“数据能动”，再做协议链路验证。
  - 输出稳定基准指标（至少：启动成功率、状态位、错误计数）。

  **Must NOT do**:
  - 不把协议层失败混入底层 DMA smoke 结论。
  - 不忽略失败时寄存器快照。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 涉及硬件寄存器、DMA 状态和时序稳定性。
  - **Skills**: [`sparklink-kernel-dev`, `sparklink-userspace-dev`]
    - `sparklink-kernel-dev`: 内核/设备路径与 DMA 状态理解。
    - `sparklink-userspace-dev`: 用户态控制与脚本化验证。
  - **Skills Evaluated but Omitted**:
    - `quick`: 烟测本身需要严谨状态断言。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2（关键串行）
  - **Blocks**: T11, T12
  - **Blocked By**: T4, T7, T8

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/rtl/phy/sle_phy_top.sv` - 寄存器语义（含 soft_reset）。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/daemon/phy_ctrl.c` - 用户态控制路径。
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/AGENTS.md` - 历史已验证 DMA 状态样例。

  **Acceptance Criteria**:
  - [ ] smoke harness 可独立运行并输出 PASS/FAIL。
  - [ ] 失败时自动输出寄存器快照与错误位。
  - [ ] smoke 结果可作为 T11/T12 前置门。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: DMA/PHY最小通路通过
    Tool: Bash
    Preconditions: UIO/DT/服务路径已稳定
    Steps:
      1. 执行 smoke harness。
      2. 检查 DMA SR 与 PHY busy/idle 状态。
      3. 断言输出 PASS 标记。
    Expected Result: 最小通路稳定通过。
    Failure Indicators: SR 错误位、timeout、状态不一致。
    Evidence: .sisyphus/evidence/task-10-dma-phy-smoke.log

  Scenario: 错误注入路径
    Tool: Bash
    Preconditions: smoke harness 支持 `--inject` 参数
    Steps:
      1. 执行 `./scripts/dma_phy_smoke.sh --inject dma_timeout`。
      2. 验证返回码非零，且输出包含 DMA/PHY 寄存器快照。
    Expected Result: 失败可被自动识别并定位。
    Evidence: .sisyphus/evidence/task-10-dma-phy-smoke-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-10-dma-phy-smoke.log`
  - [ ] `.sisyphus/evidence/task-10-dma-phy-smoke-error.log`

  **Commit**: YES (groups with 2)
  - Message: `test(e310-datapath): add dma/phy smoke harness and assertions`
  - Files: harness scripts/tests/docs
  - Pre-commit: harness pass on reference setup

- [ ] 11. 完成 TX 链路端到端验证（Host→USB→DLI→DMA→PHY→AD9361）

  **What to do**:
  - 基于已稳定 baseline，执行 TX 方向完整链路验证并分层打点。
  - 验证从 host 发包到设备侧处理、DMA 发起、PHY 状态变化、RF 发射触发。
  - 输出“每一跳是否通过”的链路图与失败点坐标。

  **Must NOT do**:
  - 不仅验证 USB 收发成功就判定 TX 完成。
  - 不忽略 DMA 与 PHY 状态位的联动一致性。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 涉及多组件联调与跨层诊断。
  - **Skills**: [`sparklink-userspace-dev`, `sparklink-kernel-dev`]
    - `sparklink-userspace-dev`: DLI/daemon 路径。
    - `sparklink-kernel-dev`: 驱动与内核态状态核查。
  - **Skills Evaluated but Omitted**:
    - `quick`: 任务复杂度高，且失败定位需要深度上下文。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3（与 T12/T13/T14/T15）
  - **Blocks**: T16
  - **Blocked By**: T5, T6, T7, T8, T9, T10

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/dli/handler.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/usb/ffs.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/phy/mod.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/test_dli_usb.py` (if present in workflow)

  **Acceptance Criteria**:
  - [ ] TX 方向 E2E 至少 20 次连续测试通过（或定义的稳定门槛）。
  - [ ] 每次测试均有链路分层状态记录。
  - [ ] 失败时自动给出具体断点层级。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: TX链路连续通过
    Tool: Bash + Python test harness
    Preconditions: baseline 稳定，设备在线
    Steps:
      1. 运行 TX E2E 用例批次（N=20）。
      2. 采集 USB/DLI/DMA/PHY 状态摘要。
      3. 断言成功率达到阈值。
    Expected Result: 达到通过阈值且无系统性卡死。
    Failure Indicators: 某固定层反复失败或成功率低于阈值。
    Evidence: .sisyphus/evidence/task-11-tx-e2e.log

  Scenario: TX失败断点定位
    Tool: Bash
    Preconditions: TX harness 支持错误注入
    Steps:
      1. 执行 `./scripts/tx_e2e.sh --inject ep_block`。
      2. 输出断点层级（USB/DLI/DMA/PHY/RF）并保存。
    Expected Result: 自动定位失败层级。
    Evidence: .sisyphus/evidence/task-11-tx-e2e-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-11-tx-e2e.log`
  - [ ] `.sisyphus/evidence/task-11-tx-e2e-error.log`

  **Commit**: YES (groups with 3)
  - Message: `test(e310-tx): verify end-to-end tx datapath with layered assertions`
  - Files: test harness + diagnostic docs
  - Pre-commit: tx regression batch

- [ ] 12. 完成 RX 链路端到端验证（RF/PHY→DMA→DLI→USB→Host）

  **What to do**:
  - 验证 RX 方向链路，重点关注同步、解调、DMA 回传、DLI 上送。
  - 校验 RX 结果与预期载荷/统计的一致性（误码、丢包、时序）。
  - 建立 RX 异常分类（无包、包损、内容错、延迟异常）。

  **Must NOT do**:
  - 不以单次偶发成功替代稳定性验证。
  - 不忽略时序相关异常（启动后首包、长时间运行漂移）。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: RX 链路通常比 TX 更易受时序/同步影响。
  - **Skills**: [`sparklink-userspace-dev`, `sparklink-kernel-dev`]
    - `sparklink-userspace-dev`: 协议上报路径。
    - `sparklink-kernel-dev`: 驱动与数据面状态采样。
  - **Skills Evaluated but Omitted**:
    - `quick`: 需批量稳定性与异常分类。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3（与 T11/T13/T14/T15）
  - **Blocks**: T16
  - **Blocked By**: T5, T6, T7, T8, T9, T10

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/rtl/phy/sle_frame_sync.sv`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/rtl/phy/sle_ad9361_rx_bridge.sv`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/phy/sync.rs`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/dli/handler.rs`

  **Acceptance Criteria**:
  - [ ] RX 方向连续运行达到约定稳定阈值。
  - [ ] 形成可复用的 RX 异常分类报告。
  - [ ] RX 验证结果可被脚本自动判定。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: RX链路稳定性验证
    Tool: Bash + test harness
    Preconditions: TX/RX test environment ready
    Steps:
      1. 运行 RX 批量测试（含长时间窗口）。
      2. 记录包计数、错误率、延迟摘要。
      3. 断言指标在阈值内。
    Expected Result: 稳定通过并输出统计摘要。
    Failure Indicators: 统计超阈值、链路中断、无法复现。
    Evidence: .sisyphus/evidence/task-12-rx-e2e.log

  Scenario: RX异常归类
    Tool: Bash
    Preconditions: RX harness 支持错误注入
    Steps:
      1. 执行 `./scripts/rx_e2e.sh --inject sync_loss`。
      2. 输出异常类别（无包/包损/内容错/延迟异常）与定位依据。
    Expected Result: 异常可归类并有可操作后续。
    Evidence: .sisyphus/evidence/task-12-rx-e2e-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-12-rx-e2e.log`
  - [ ] `.sisyphus/evidence/task-12-rx-e2e-error.log`

  **Commit**: YES (groups with 3)
  - Message: `test(e310-rx): verify end-to-end rx datapath and stability metrics`
  - Files: rx harness + metrics docs
  - Pre-commit: rx regression batch

- [ ] 13. 固化 SD 镜像可重建流程与版本锁定

  **What to do**:
  - 打通从源码到 `BOOT.bin`/`boot.scr`/`sle_e310.itb`/`sdimg` 的**权威可重建流程**。
  - 将 `mk_sdcard.sh` 标记为 legacy 流程（仅兼容对照，不参与主验收）。
  - 固化工具版本（Vivado/Vitis/交叉编译器/buildroot/linux/u-boot 分支）。
  - 生成“重建脚本 + 校验清单 + 失败排查手册”。

  **Must NOT do**:
  - 不依赖“本机环境偶然可用”。
  - 不省略校验（hash/size/分区布局）。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 流程工程化与版本固定，重点在可复现。
  - **Skills**: [`sparklink-kernel-dev`]
    - `sparklink-kernel-dev`: 适配构建/测试流程固定化。
  - **Skills Evaluated but Omitted**:
    - `deep`: 不涉及新架构设计。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3（与 T11/T12/T14/T15）
  - **Blocks**: T15
  - **Blocked By**: T2

  **References**:
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/Makefile`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/scripts/boot.cmd`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/bsp/scripts/mk_sdcard.sh`（legacy 对照）
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/deploy_jtag.sh`

  **Acceptance Criteria**:
  - [ ] 一条命令或一套脚本可重建权威 SD 启动制品（`BOOT.bin + boot.scr + sle_e310.itb`）。
  - [ ] 产物 hash、大小、关键文件列表可自动校验。
  - [ ] 文档可让第三方在新环境复现。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 全量重建成功
    Tool: Bash
    Preconditions: 工具链满足版本要求
    Steps:
      1. 执行重建脚本。
      2. 校验产物存在、hash 和大小。
      3. 生成构建报告。
    Expected Result: 产物完整且可复验。
    Failure Indicators: 任一关键产物缺失或校验失败。
    Evidence: .sisyphus/evidence/task-13-sd-repro-build.log

  Scenario: 版本偏差告警
    Tool: Bash
    Preconditions: 人为变更工具版本
    Steps:
      1. 运行环境检查。
      2. 验证脚本阻断并给出明确版本差异。
    Expected Result: 非法版本不会进入正式构建。
    Evidence: .sisyphus/evidence/task-13-sd-repro-version-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-13-sd-repro-build.log`
  - [ ] `.sisyphus/evidence/task-13-sd-repro-version-error.log`

  **Commit**: YES (groups with 3)
  - Message: `chore(e310-build): make sd-image pipeline reproducible and version-locked`
  - Files: build scripts/docs/manifests
  - Pre-commit: dry-run + build verification

- [ ] 14. 建立 TXS 标准到实现的追踪矩阵

  **What to do**:
  - 对齐关键标准条目（TXS-00001/10002/10003/20002）与当前实现文件/测试。
  - 标记“已实现/部分实现/未实现/实现不确定”。
  - 对每个“未实现/不确定”给出优先级和风险说明。

  **Must NOT do**:
  - 不写抽象口号式对齐，必须精确到文件与测试。
  - 不把“理论支持”当作“运行时已验证”。

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 文档化追踪矩阵为主，需高精度表述。
  - **Skills**: [`sparklink-compliance-audit`]
    - `sparklink-compliance-audit`: 标准符合性审计最匹配。
  - **Skills Evaluated but Omitted**:
    - `quick`: 该任务要求系统化审计深度。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3（与 T11/T12/T13/T15）
  - **Blocks**: T16
  - **Blocked By**: T1, T3, T11, T12

  **References**:
  - `/home/sanchuanhehe/Documents/Summary-of-Sparkling-Information/Standard/`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/` implementation files
  - `/home/sanchuanhehe/Documents/sparklink/` userspace/kernel interface docs

  **Acceptance Criteria**:
  - [ ] 追踪矩阵至少覆盖核心链路必需条目。
  - [ ] 每条标准项有实现证据链接。
  - [ ] 输出优先级修复队列。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 追踪矩阵完整性检查
    Tool: Bash + Markdown validator
    Preconditions: 标准与实现路径可读
    Steps:
      1. 生成矩阵文档。
      2. 校验每行都含标准条目、实现路径、验证状态。
      3. 统计缺口项数量。
    Expected Result: 矩阵结构完整且可行动。
    Failure Indicators: 存在无证据项或无状态项。
    Evidence: .sisyphus/evidence/task-14-standards-matrix.md

  Scenario: 证据失配检测
    Tool: Bash
    Preconditions: 人为引入一条错误映射
    Steps:
      1. 运行映射校验脚本。
      2. 验证错误映射被标红。
    Expected Result: 错误映射可被自动发现。
    Evidence: .sisyphus/evidence/task-14-standards-matrix-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-14-standards-matrix.md`
  - [ ] `.sisyphus/evidence/task-14-standards-matrix-error.log`

  **Commit**: YES (groups with 4)
  - Message: `docs(compliance): add TXS traceability matrix and prioritized gaps`
  - Files: compliance docs/matrix
  - Pre-commit: markdown + link validation

- [ ] 15. 产出裸机 Rust 分阶段迁移蓝图（有门槛、有回退）

  **What to do**:
  - 定义迁移阶段：
    1) Linux 稳定基线；
    2) 裸机 PoC（最小控制平面）；
    3) 混合架构；
    4) 可选进一步迁移。
  - 明确每阶段入口条件、退出条件、回退条件。
  - 区分“必须保留 Linux 的环节”与“可迁移到 bare-metal Rust 的环节”。

  **Must NOT do**:
  - 不一次性全迁移。
  - 不在 Linux 基线未稳时进入高风险迁移阶段。

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 架构迁移含长期权衡与高风险路径控制。
  - **Skills**: [`sparklink-kernel-dev`, `sparklink-userspace-dev`]
    - `sparklink-kernel-dev`: 低层边界与内核依赖评估。
    - `sparklink-userspace-dev`: 控制面与工具链迁移影响评估。
  - **Skills Evaluated but Omitted**:
    - `quick`: 不适合架构决策。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3（与 T11/T12/T13/T14）
  - **Blocks**: T16
  - **Blocked By**: T2, T13

  **References**:
  - 当前实机证据与 T1-T13 结果
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/doc/hw_sw_partition_analysis.md`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/doc/vivado_upgrade_analysis.md`

  **Acceptance Criteria**:
  - [ ] 每阶段均有可测量 gate。
  - [ ] 回退策略可执行且已文档化。
  - [ ] 明确写出“现在不该迁移的部分”。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 迁移门槛可验证
    Tool: Bash + doc checks
    Preconditions: 基线任务结果可用
    Steps:
      1. 对每阶段 gate 绑定具体检测项。
      2. 用当前状态评估是否满足 gate。
      3. 输出 go/no-go 结论。
    Expected Result: 迁移决策可证据化。
    Failure Indicators: gate 抽象不可执行。
    Evidence: .sisyphus/evidence/task-15-migration-gates.md

  Scenario: 回退策略演练
    Tool: Bash (tabletop simulation)
    Preconditions: 指定一类迁移失败场景
    Steps:
      1. 执行回退 runbook 的命令级清单演练。
      2. 验证回退后系统回到 Linux 基线。
    Expected Result: 回退路径闭环且时间可控。
    Evidence: .sisyphus/evidence/task-15-migration-rollback.md
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-15-migration-gates.md`
  - [ ] `.sisyphus/evidence/task-15-migration-rollback.md`

  **Commit**: YES (groups with 4)
  - Message: `docs(architecture): define staged bare-metal rust migration with rollback gates`
  - Files: migration strategy docs
  - Pre-commit: consistency and traceability checks

- [ ] 16. SparkLink 与 E310 控制面集成检查点

  **What to do**:
  - 定义 SparkLink userspace 与 E310 控制器侧的接口适配边界（命令、事件、错误码、时序）。
  - 校验现有 SparkLink 工具链（slkd/slctl/slkconfig/libsparklink）对 E310 路径的接入可行性。
  - 给出“最小集成里程碑”与阻断清单。

  **Must NOT do**:
  - 不将 SparkLink 全功能一次性压到 E310 路径。
  - 不忽略协议层与底层链路状态不一致的问题。

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 跨仓库接口整合，需要系统设计视角。
  - **Skills**: [`sparklink-kernel-dev`, `sparklink-userspace-dev`]
    - `sparklink-kernel-dev`: 内核/协议层边界。
    - `sparklink-userspace-dev`: 用户态接口与 CLI/daemon 路径。
  - **Skills Evaluated but Omitted**:
    - `writing`: 任务含技术验证，不仅文档输出。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 末端集成
  - **Blocks**: F1, F2, F3, F4
  - **Blocked By**: T5, T9, T11, T12, T14, T15

  **References**:
  - `/home/sanchuanhehe/Documents/sparklink/crates/slk-protocol/`
  - `/home/sanchuanhehe/Documents/sparklink/crates/libsparklink/`
  - `/home/sanchuanhehe/Documents/sparklink/crates/slkd/`
  - `/home/sanchuanhehe/Documents/nearlink_sdr/nearlink_sdr_zynq/sw/linux/rust/sle-fw/src/`

  **Acceptance Criteria**:
  - [ ] 输出最小可行集成接口契约。
  - [ ] 至少 1 条关键命令链路完成端到端演示。
  - [ ] 阻断项与归属仓库/模块明确。

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: 最小接口契约验证
    Tool: Bash + CLI/API checks
    Preconditions: T11/T12 已通过
    Steps:
      1. 执行选定最小命令链路（命令→事件回读）。
      2. 校验返回码、事件格式、状态一致性。
      3. 输出接口契约验证报告。
    Expected Result: 最小链路可稳定通过。
    Failure Indicators: 命令成功但状态不一致、事件丢失。
    Evidence: .sisyphus/evidence/task-16-sparklink-integration.log

  Scenario: 集成阻断定位
    Tool: Bash
    Preconditions: 支持指定阻断注入参数
    Steps:
      1. 执行 `./scripts/integration_check.sh --inject contract_mismatch`。
      2. 捕获调用链各层日志并输出阻断归属模块。
    Expected Result: 阻断归属明确且可分派。
    Evidence: .sisyphus/evidence/task-16-sparklink-integration-error.log
  ```

  **Evidence to Capture**:
  - [ ] `.sisyphus/evidence/task-16-sparklink-integration.log`
  - [ ] `.sisyphus/evidence/task-16-sparklink-integration-error.log`

  **Commit**: YES (groups with 4)
  - Message: `feat(integration): define and validate sparklink-e310 minimum control contract`
  - Files: integration specs/tests/docs
  - Pre-commit: contract checks + e2e smoke

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results and wait for explicit user approval.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Verify Must Have / Must NOT Have / task completion / evidence-file presence.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run build/lint/tests, check slop patterns, unsafe shortcuts, dead code, ignored errors.
  Output: `Build | Lint | Tests | File hygiene | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ serial/ssh runtime checks)
  Execute all QA scenarios from T1-T16 on hardware-backed environment.
  Output: `Scenarios [N/N] | Integration [N/N] | Edge Cases [N] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  Ensure implementation is exactly per task scope; no missing/no creep/no contamination.
  Output: `Tasks compliant [N/N] | Unaccounted changes [N] | VERDICT`

---

## Commit Strategy

- **Commit Group 1 (T1-T5)**: `fix(e310-baseline): establish reproducible runtime and artifact baseline`
- **Commit Group 2 (T6-T10)**: `fix(e310-runtime): harden startup and resolve UIO/DT binding path`
- **Commit Group 3 (T11-T13)**: `test(e310-e2e): add tx/rx verification and reproducible sd-image flow`
- **Commit Group 4 (T14-T16)**: `docs(plan): add standards traceability and rust migration blueprint`

---

## Success Criteria

### Verification Commands
```bash
# Runtime baseline
lsusb | grep 0456:b674

# Serial evidence
# (capture file exists and contains boot + service + verification markers)

# Device path
ls /dev/uio*

# Service path
ps | grep sle_ctrl

# Data-path sanity
# (task-provided tx/rx harness commands return PASS markers)
```

### Final Checklist
- [ ] Linux baseline reproducible on ANTSDR E310
- [ ] TX/RX abnormal path has root-cause closure or explicit bounded blocker
- [ ] UIO/DT/PL binding path deterministic and automatically validated
- [ ] SD image and artifacts can be regenerated from source flow
- [ ] SparkLink integration checkpoint complete
- [ ] Bare-metal Rust migration plan has gate-based entry and rollback criteria
