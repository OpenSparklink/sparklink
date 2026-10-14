# Controller snoop 契约

当前源码核对：Linux `53a110816ebf` 的 `sparklink_core.rs::ioctl_snoop_get`、
`sle_snoop.rs` 与用户态 `eb92d16f4d9f` 的 `types.rs`、`snoop.rs`、slkmon。
本页描述当前源码，不增加实机资格，也不构成已发布 ABI。
[操作步骤](../how-to/capture-controller-snoop.md)与[当前资格](../../project/current-capabilities.md)分别维护。

## 选择、权限和等待

每 fd 显式选择 controller，并提交非零 generation；接受profile 1 WS73及profile 0标准DLI；必须匹配新源码，旧记录只属于其准确提交。
每次 ioctl 和 poll 要求 CAP_NET_ADMIN。此权限与 Managed／Diagnostic lease
及普通应用通道授权分开。两个 reader 使用独立 cursor，互不消费记录。
同一 fd 的 ControllerEvent 与 snoop 模式互斥；重新 DEV_SELECT 重置观察模式。
无记录时 EAGAIN；异步 reader 等待 waitqueue，不以周期轮询制造事件。
拔出时 poll 为 ERR|HUP，查询 ENODEV；旧 reader 不随复用 index 转到新 generation。

## 数据来源与预算

每 registration 保留 64 条预分配记录，每条最多 320 字节。RX 位于 USB/HCC
解帧后的 service 10／queue 8 SLE slot，在 DLI schema 检查之前；不覆盖 ROM、
BSLE 握手、其他 queue 或非法 HCC aggregate。TX_RESULT 在阻塞 transport 返回后记录。
其 `status=0` 只说明该 transport 尝试成功，不能解释为 DLI Complete 或对端收到。
序号为观察顺序，时间为 CLOCK_BOOTTIME 纳秒，不是 UTC 或命令关联 ID。

## ABI 与文件

`SL_IOCTL_SNOOP_GET=0xc198538e`，native integer、8 字节对齐的 query 共 408 字节。

| Query offset | 字段 | 约束 |
|---|---|---|
| 0／8 | generation／after_seq (u64) | 当前非零 generation；cursor 不超过当前序号 |
| 16／20 | version／flags (u32) | version=1；调用者 flags=0 |
| 24 | reserved (u64) | 调用者置零 |
| 32 | record (376 bytes) | 请求内容不用于选取，返回下一可保留记录 |

**历史限制及整改**：K5582当时未拒绝query flags/reserved；K580b51已在订阅/输出前
明确EINVAL。准确新镜像已在Virtual验证这项拒绝，并完成合法WS73路径回归；不把软件/Virtual检查当标准物理资格。

| Record offset | 字段 | 含义 |
|---|---|---|
| 0／8／16／24 | seq／generation／timestamp_ns／lost (u64) | `lost=seq-after_seq-1`，明确 ring 覆盖缺口 |
| 32／36／40 | profile (u32)／original_length (u32)／status (i32) | 实际包长度与 transport 结果 |
| 44／46／47 | dev_index (u16)／direction (u8)／format (u8) | direction 1 RX、2 TX_RESULT；format 1 WS73 DLI，2标准DLI |
| 48／50／52 | captured_length (u16)／flags (u16)／reserved (u32) | flags bit0 TRUNCATED；reserved=0 |
| 56 | payload[320] | captured_length 后补零 |

文件逐字段 little-endian 编码，头部 16 字节：ASCII `SLKSNP01`、u32 version=1、
u32 payload_max=320；每条 376 字节，不能直接将 native query 内存写成文件。
新 capture 文件权限 0600，已有路径和写入／flush 失败均拒绝。

## 错误与 copyout

| 结果 | 当前含义 |
|---|---|
| EPERM | 无当前 raw 诊断权限；在 usercopy 之前检查 |
| EOPNOTSUPP | 不支持 query version 或 controller profile |
| EINVAL | 缺显式选择、generation=0、未来 cursor |
| ENODEV | 设备不存在／退休或 generation 不匹配 |
| EBUSY | 同 fd 已处于 ControllerEvent 模式 |
| EAGAIN | 暂无新记录，已激活等待订阅 |
| EFAULT | usercopy 失败；成功 copyout 才推进 fd cursor |

C `slk_snoop` 返回 1／0／负 errno，Python `NativeAdapter.poll_snoop()` 返回独立
record／None／OSError；C/Python 类型与错误完整覆盖仍按参考迁移计划继续审计。
不提供旧共享 DLI poll 或 `--legacy` fallback。

标准profile0/format2的command/event头为LE16 opcode/event + LE16参数长度，再接
参数，无WS73 A1/A2标识。RX是已注册标准interrupt event packet（非法schema亦
可抓取），不覆盖bulk data/启动包。TX记录匹配实际EP0四字节command编码。
Virtual记录有相同格式，但明确测试总线，不是标准USB物理资格。
