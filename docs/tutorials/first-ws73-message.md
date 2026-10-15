# 在实验 VM 中让两只 WS73 交换短消息

你会启动两个用户态程序：一个发出随机消息，另一个校验并回复，再看到发送方
校验同一份回复。它们通过连接后的通道 socket 收发，广播载荷不参与这次业务。

**适用范围：受限教程草案。** 步骤提炼自已验收的 K `8cbf53e6a088`、编译用户态／
guest 工具 `85cdf627d70b`、Host 核对器 `db6e333814cf` 的真实短消息门禁。
[原始资格摘要](../evidence/agent-policy-retained-data-20261015.json)保留准确来源；
页面本身尚未在干净环境从头重放，不授予当前 HEAD 或整篇入门流程资格。
本篇不教构建文档，也不覆盖从源码制作 VM、首次发现和建立物理连接。

## 你开始前需要什么

请集成人员提供匹配上述输入的实验 VM：两只真实 WS73 独立 Ready，slkd 正在运行，
两端已建立一个新的物理 Connection，SMTC ExchangeInfo 已由环境准备流程完成，
应用 CUTC 通道尚未被其他程序占用或关闭。不是在宿主机执行这些操作。

在 VM 内用同一个普通用户打开两个终端；不运行 sudo。既有实机门禁使用 UID1000、
零 capabilities 的实验用户，具有 `sparklink` 组的实验访问权限。这**不是**仅加入
`sparklink-apps` 组的最小权限部署教程；后者只授权 OpenChannel/Scoped，当前
slctl 还查询身份，完整部署权限门禁尚未完成。权限配置由环境准备者负责。

如果没有这个已准备的环境，先停在这里：[VM 输入参考](../reference/vm-gate-inputs.md)
说明缺哪些产物，但尚不能替代完整构建指南。不要尝试安装宿主实验内核。

## 1. 找到两个不同的连接端点

在 VM 内运行：

```sh
slctl list
```

记录两只设备返回的实际 adapter 路径。每条含 index 和 generation，格式为
`/org/sparklink/slk{index}_g{generation}`；这里的花括号是格式说明，不是可复制的路径。
不要使用固定的 slk0、USB device number 或历史 generation。

把两条实际路径分别放入当前终端的 `ADAPTER_A`、`ADAPTER_B` shell 变量后查询：

```sh
slctl --adapter "$ADAPTER_A" connection-objects
slctl --adapter "$ADAPTER_B" connection-objects
```

将两端当前连接的完整路径分别放入 `CONNECTION_A`、`CONNECTION_B`。
路径含 `/peer_t.../link_...`，并对应当前非零 lifetime。两条路径属于同一次物理连接的
两端，不能复制 A 的路径给 B。找不到两个当前对象时，由准备者检查建链，先不要继续。

## 2. 先让 B 等待并回复

在第一个终端设置同样取得的 B 变量，然后运行：

```sh
slctl --adapter "$ADAPTER_B" channel-peer "$CONNECTION_B" 20
```

它打开授权 fd，打印 `NativeChannelOpened: role=peer rounds=20`，并等待真正收到的数据。
收到每条消息后，程序检查长度、随机标识、序号与载荷，再打印
`NativeChannelReceived` 和 `NativeChannelReply`。这不是 daemon 生成的模拟回复。
每轮只有 10 秒原期限；预先在第二个终端准备好下一步，启动 B 后立即执行。

## 3. 由 A 发出随机消息

在第二个终端使用 A 的变量运行：

```sh
slctl --adapter "$ADAPTER_A" channel-roundtrip "$CONNECTION_A" 20
```

默认每条应用消息为 61 字节。你会看到 `NativeChannelSent`，随后每轮出现：

```text
NativeChannelRoundTrip: sequence=0 elapsed_ms=... bytes=...
```

省略号是说明输出字段，不能作为期望载荷。程序实际使用 `/dev/urandom` 生成消息，
检查 B 返回的整条消息；序号日志从 0 到 19。`elapsed_ms` 必须小于 10000。
A 与 B 都应完成 20 轮并以零退出；只看 A 的 send 成功或 NOCP 计数不够。

## 4. 理解结果并结束

你已经走通了“应用发出 → B 实际校验并回复 → A 校验”的短消息路径。要把这次
实验列为新的实机资格，还需[独立核对两端捕获](../how-to/check-business-roundtrip.md)，
本教程的屏幕输出不能单独取代它。

测试客户端会检查 dup 后原 fd 关闭仍可用，并在最后关闭后验证
`NativeChannelLastClose: same_lifetime_reopen=NotSupported`。这是当前限制：
**不能直接在同一 lifetime 重跑两条命令**。要交换方向再练习，请准备者断链并重建
新物理 lifetime，再重新枚举路径；不必拔设备，也不能重启后沿用旧路径。
应用结束自己的通道不等于授权它停用整个 controller。

## 卡住时怎么办

- 权限拒绝：保存错误，让环境准备者检查实际 system-bus 策略、组和内核 Grant；不要改用 sudo 跳过教程权限。
- 旧对象、NotSupported 或重开拒绝：核对完整 generation/lifetime，检查是否已用过该通道；不要只换 handle 或请求编号。
- 10 秒内无回复：停止两端客户端，保留两端输出，核对 B 是否已启动、通道协商和连接是否仍有效；超时不是交付成功。
- 设备消失、断链或初始化失败：保存 VM/kernel/USB 证据并结束本次实验；人工重插、QMP、hub 切电不算自动恢复。

本篇之后仍缺首次广播发现、从零建链和完整环境制作教程；这些缺口在唯一计划 DQ3
保持开放，不表示 SSAP、安全、长包、多通道、四设备或自然恢复已经完成。
