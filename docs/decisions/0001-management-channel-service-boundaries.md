# ADR 0001：管理、连接 socket 与应用服务分层

日期：2026-10-11。状态：目标架构已采用，分阶段实施；不代表 socket、SSAP、
安全或完整生态已交付。根据用户提供的 Linux Bluetooth / BlueZ 分析调整原方案，
保留 S0–S6、WS73 第一北极星及原 issues 全部验收范围。

## 决定及所有权

| 层 | 唯一职责 |
|---|---|
| drivers/sparklink | 总线匹配、固件、端点、HCC/BSLE、传输、设备电源与硬件恢复 |
| net/sparklink | 每设备 Runtime、DLI Host/方言、命令事务、连接/TCID、流控、安全机制与可信状态 |
| slkd | 唯一 Managed 管理者；启用/连接策略、Agent、trust、Bond 持久化、SSAP Engine/数据库、Profile |
| slk-vendord | 独立进程、Backend owner；厂商私有 ABI 限于内部，不加载到 slkd |
| 应用/工具 | 普通管理经授权 D-Bus/高层 API；数据使用授权通道；观察与诊断独立 |

内核拥有配对时序、密码学、有效凭据、加密安装及安全强制；slkd 决定认证方法、
用户确认、信任及持久化。SSAP codec、协商、事务、数据库和 Profile 回调迁入
用户态，内核提供完整 PDU 通道、顺序、背压、断链与安全上下文。

Bluetooth 的 [MGMT](https://github.com/bluez/bluez/blob/master/doc/mgmt-protocol.rst)、
用户态 [GATT 注册](https://github.com/bluez/bluez/blob/master/doc/org.bluez.GattManager.rst)
和 [Agent](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Agent.rst)提供分层参考，
不直接套用 Bluetooth wire 协议或据此宣称星闪符合性。

## 连接数据面的最终接口

每个逻辑通道独立 **socket fd**，绑定 controller、generation、peer、connection、
local/remote TCID。多个通道可复用底层连接，队列、等待、权限、关闭状态独立。
可靠有序、保留消息边界的通道优先 SOCK_SEQPACKET；连接式 SOCK_DGRAM 仅在
协商支持不可靠消息模式时开放。socket 类型不能替代协议的可靠性、重传、排序、
credit 实现。[L2CAP 接口语义](https://github.com/bluez/bluez/wiki/L2CAP)作参考。

契约必须定义非阻塞、poll/epoll、长度上限、内存预算、背压、关闭/断链错误和
安全选项。slkd 可授予范围受限的 socket fd；fd 授权不能绕过实际调用权限、
连接安全或旧 generation 检查。AF_SPARKLINK 仅是名称占位，地址族名称和编号
须协调，不能自行宣称已分配。管理 UAPI、事件订阅、诊断、Proxy 形式独立。
当前 discovery 不等待 socket；连接阶段迁移调用者后删除旧 CONN_SEND/RECV，
不保留两套长期生产数据面。UAPI 尚未发布，直接同步替换，无旧接口兼容期限。

## UAPI 冻结前的契约门禁

- 身份：controller id + generation；连接只属于该 controller 实例。
- 事务：本地 request id；接受、执行和最终完成分开；截止时间、取消明确。
- 事件：独立订阅、sequence/丢失计数、移除唤醒；结果只完成原请求者。
- 所有权：Managed、Backend Proxy、Connection PDU owner 分别管理。
- 权限：owner/token/generation/实际调用权限独立校验；诊断与冲突管理互斥。
- 能力：已知支持、已知不支持、未知分开，附来源；未知不能默认成功。
- ABI：固定宽度/对齐/version/length/flags/reserved；结构升级连同 ioctl 编号规则
  冻结。size 字段不能修复 ioctl 本身编码结构大小造成的编号变化。
- 厂商隔离：普通应用不理解 WS73 USB/HCC/BSLE；raw 操作仅受控诊断/协商扩展。

没有线上事务号时，本地 request id 不能关联固件回复。Host 限制在途、隔离迟到
回复并管理 generation；不得把同 opcode 的旧 Complete 匹配给新请求。
C/Rust/Python conformance 覆盖布局、编号、枚举、权限、错误和实际调用行为。

## 迁移顺序和验收

先修复确定性缺陷、拒绝不支持能力并恢复严格 CI；WS73 生命周期/自然故障根因
及有限恢复同时推进。随后冻结连接契约，实现最小 socket 开发门禁及真实双设备
数据闭环；再接通用户态 SSAP、每连接安全、可恢复 Bond、Profile，扩展四设备
两组并行，最后其他 Native backend 和厂商 Proxy 逐项验收。

socket 门禁覆盖消息边界、超长拒绝、持续发送/背压、取消/关闭、断链、迟到回调、
旧 generation、权限、多设备隔离、内存预算；按适用性运行 lockdep/KASAN/KCSAN。
纯模型、人工注入、真实 RF、物理拔插证据分别记录。VM-only；宿主原生对照未执行。

当前已证实 WS73 VM 双设备 20+2 轮/普通用户/同 daemon/物理重接，以及一次人工
传输错误后的有限恢复支持；自然启动超时、重枚举/消失根因及完整无人工恢复仍
未闭合，U10 保持 7/8。不提前关闭任何完整 issue。

执行清单见[调用审计与清理](../LEGACY_CLEANUP_20261011.md)、
[14 项整改](../REVIEW_REMEDIATION_20261011.md)、[联合方案](../IMPLEMENTATION_PLAN.md)。


## 标准核对与旧 Engine 开放条件

T/XS 20001-2025表72/75/76规定分片消息控制码；旧内核offset/短包结束格式不符合
这套格式。先删除不可靠wire Engine并拒绝操作，历史codec只供selftests。标准
Engine/数据库在slkd接通PDU socket后实施；本地staging不是服务发布。见
[整改和门禁](../SSAP_LEGACY_CONTAINMENT.md)。不通过修改旧格式的长度界限
继续保留第二套生产Engine。

## 再次核对（2026-10-11）

用户再次提供的分析内容与既有分析一致（文本SHA256
f8de2edb3e4c6a2cca1442ce06ba59c03407469b7f8631539e974743c993853a）。
本ADR继续采用，无架构回退。最新权限整改见[契约](../SSAP_OPERATIONS.md)，
14项最新实现/测试/未决条件见[整改记录](../REVIEW_REMEDIATION_20261011.md)。
声明位验证、框架存在和CI成功不证明服务互通或安全强制；实际socket、用户态
Engine、安全/Bond和自然恢复门禁仍需独立交付。已验证discovery持续回归。

最新已验证基线为K`78e729c06a5e`/编译U`2dfd6bd09e7b`，见
[诊断淘汰证据](../evidence/ws73-vm-diagnostic-eviction-20261011.json)。后续
K`54621800ee4c`修复旧poll的复制提交顺序；[6项新开发fixture和未决实机门禁](../EVENT_COPY_REMEDIATION.md)
明确区分，不将历史真实路径证据推广到尚未运行的新镜像。

实际取消/迟到回复/完整期限、事件与旧DLI调用者删除仍开放；socket、用户态SSAP、
每连接安全/Bond及自然故障根因/自主恢复未验收。历史物理xHCI警告和旧版本
证据保留，不能用新批无警告替代根因定位。部分成果不关闭完整issue。
