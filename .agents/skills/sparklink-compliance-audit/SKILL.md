---
name: sparklink-compliance-audit
description: 'SparkLink TXS 标准符合性审计工作流。当用户需要检查 SparkLink 实现与 TXS 标准的符合度、生成 gap 矩阵、找出未覆盖的字段/UUID/状态机、制定修复优先级列表时使用。触发词：审计、gap、哪些标准没实现、覆盖率、符合性、TXS-NNNNN、BLUEZ 对比、查漏补缺。'
argument-hint: '要审计的标准编号或功能域（如 TXS-20001、HID、传输层）'
---

# SparkLink 标准符合性审计

## 目标

对照 TXS 标准文档，输出：
1. **覆盖矩阵**：每条需求 → 代码位置 → 实现状态
2. **Gap 清单**：P0/P1/P2 优先级分类
3. **修复建议**：附具体文件路径和代码修改方向

---

## 标准文档位置

```
~/Documents/Summary-of-Sparkling-Information/Standard/
├── TXS-00001   系统架构（参考用）
├── TXS-10002   SLE 空口技术
├── TXS-10003   DLI 数据连接接口        ← 内核 ioctl 层
├── TXS-20001   设备发现与服务管理（SSAP）
├── TXS-20002   传输与控制规范（TCID/帧格式）
├── TXS-20006   网络多跳组网
├── TXS-20007   传输报文格式（CLTP/LWCTP）
├── TXS-30004   HID 数据交互服务
├── TXS-30013   HID 应用配置管理
├── TXS-50003   SLE 空口测试
└── TXS-50004   BSL 设备测试
```

---

## 步骤 1：确定审计范围

**A. 全局审计**（"查漏补缺"类请求）
→ 按标准逐一扫描，生成 AUDIT.md

**B. 单标准深审**（"TXS-20001 哪里没实现"类请求）
→ 只读该标准，与代码逐章对比

**C. 功能域审计**（"HID 实现完整吗"类请求）
→ 找到相关标准（查上表），聚焦该域

---

## 步骤 2：阅读标准

用 `fetch_webpage` 或文件工具读取 PDF，**优先提取**：

| 章节类型 | 关注要点 |
|---------|---------|
| 附录 A（UUID 表） | 服务 UUID、属性 UUID 是否与代码一致 |
| 报文格式章节 | 字段位宽、字节序、保留字段值 |
| 状态机图 | 状态名、迁移条件是否全部实现 |
| 错误码表 | 所有错误码是否在代码中有对应处理 |
| 必选/可选标注 | "M"(Mandatory) 缺失 = P0；"O"(Optional) 缺失 = P2 |

---

## 步骤 3：代码侧对照

### 内核侧检查

```bash
# 检查 UUID/常量
grep -n 'uuid\|UUID\|0x[0-9A-F]\{4\}' net/sparklink/sle_uapi.rs

# 检查状态机
grep -n 'enum.*State\|match.*state\|=> State::' net/sparklink/sle_*.rs

# 检查错误码处理
grep -n 'EINVAL\|ENODEV\|EBUSY\|ENOTSUPP' net/sparklink/sle_*.rs

# 检查 ioctl 覆盖（与标准 opcode 对照）
grep -n 'SL_IOCTL_' include/uapi/linux/sparklink_ioctl.h | wc -l
```

### 用户态侧检查

```bash
# 检查 D-Bus 方法
grep 'fn [a-z_]*(' ~/Documents/sparklink/crates/slkd/src/*.rs | grep -v test | grep -v '//'

# 检查 slctl 命令
grep '"[a-z-]*"' ~/Documents/sparklink/crates/slctl/src/main.rs | head -40

# 现有测试覆盖
cd ~/Documents/sparklink && cargo test --workspace 2>&1 | grep 'test result'
```

---

## 步骤 4：生成覆盖矩阵

使用如下格式（按功能分组）：

```markdown
| 需求 ID | 描述 | 标准章节 | 内核 | 用户态 | 状态 | 优先级 |
|---------|------|---------|------|--------|------|--------|
| REQ-001 | 服务 UUID 0x060B | TXS-30004 附录A | sle_uapi.rs:L42 | hid.rs:L18 | ✅ | — |
| REQ-002 | 连接状态散列验证 | TXS-20001 7.2.6.2 | ❌ | service_hash.rs | ⚠️ 用户态有，内核无 | P1 |
| REQ-003 | 流模式重排序缓冲 | TXS-20002 6.4.2 | ❌ | ❌ | ❌ | P2 |
```

**优先级定义：**
- **P0**：Mandatory 需求缺失，或已实现但与标准数值不符
- **P1**：Optional 但影响互操作性
- **P2**：Nice-to-have，不影响基本功能

---

## 步骤 5：输出格式

### 标准型输出（写入 `docs/AUDIT.md`）

```markdown
## 审计日期：YYYY-MM-DD
## 测试基准：N OK / 0 FAIL（Build #NNN）

### 总览
- 审计标准数：N
- 完全覆盖：N 条
- 部分覆盖：N 条（需关注）
- 未覆盖：N 条

### P0 问题（必须修复）
### P1 问题（建议修复）
### P2 问题（可选改进）
```

### 快速型输出（直接回答，不写文件）

对话回复格式：P0 列表 → P1 列表 → 已知良好的部分。

---

## 参考：已知的历史 Gap

| 问题 | 已修复 commit |
|------|-------------|
| SleConnInfo 缺少 ssap_reliable_mode 字段（56B→64B） | `2870f00` |
| AdvReport 事件解码将 raw data 当作设备名 | `e2af875` |
| EVT_ADV_REPORT 常量与内核编码不一致（0x02 vs 0x03） | `e2af875` |
| HID UUID 使用非标准值（0x0003 vs 0x060B） | `96dabf7` |
| inject_adv 不推 DLI 事件环导致 poll_event 拿不到广播 | 待提交 |
| 动态 TCID 断连不回收（64次后耗尽） | `35c5003` |
