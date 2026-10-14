# 在 VM 内保存单个控制器的 DLI snoop

目标：获得一个绑定明确 controller generation 的私有 `SLKSNP01` 文件。
本页适用于用户态 `ca72b4915854`／Linux `5582a10c5ec8` 的源码契约；实际资格仅由
[当前能力](../../project/current-capabilities.md)指定，不因执行本页步骤获得新资格。

## 前置条件

已启动隔离 VM，并加载匹配内核、工具和真实 WS73。VM 内 capture 进程具有
CAP_NET_ADMIN；普通业务应用的授权不足以读取 raw snoop。不在主机运行这些命令，
也不通过本文安装服务、授予权限或加载固件。保留相应 VM 的源码、固件和模块 hash。

## 操作

1. 在 VM 中运行 `slkconfig adapters`，取得目标设备的实际 index 和非零 generation。
2. 将下列占位变量设为本轮身份，选择尚不存在的输出文件：

```sh
slkmon --adapter "$INDEX" --generation "$GENERATION" --write "$NEW_CAPTURE" --count 32
```

3. 保持另一个终端的业务测试运行。工具等待记录并在写满 32 条后退出；没有记录时
不会自动制造完成，也没有 32 条所需时限保证。可用 Ctrl-C 中止等待，保留部分文件并标明中止。
4. 若需另一个独立 reader，使用新的输出路径运行 `slkdump` 的同名参数。
5. 保存文件 hash、完整 stdout/stderr、退出状态及业务测试报告；受限载荷不上传公开站点。

## 结果检查

正常退出码为零；文件长度是 `16 + 376 × 记录数`，头部为 `SLKSNP01`。
核对每条记录的 index、generation、lost 和 TRUNCATED。过滤会跳过非匹配记录，
`--count` 统计过滤后的记录，因此不能据过滤文件推断完整流量。
详见[字段与错误契约](../reference/controller-snoop.md)。

## 失败处理

- EPERM：capture 进程缺独立诊断权限；不要把普通应用权限扩大成 raw 权限。
- 已有输出路径：工具拒绝覆盖；另选新路径，保留旧文件。
- EBUSY：同一 fd 已激活 ControllerEvent 模式；另开独立 fd。
- ENODEV／拔出：保留旧 reader 失败；重插后重新枚举 generation、启动新 reader。
- lost 或截断：声明证据不完整；补充对应原始 USB/HCC 及两端应用记录，不以日志填补。

这个结果证明获取了协议 seam 记录。TX_RESULT 成功不证明控制器完成、空口发送
或对端业务收到；snoop 文件不替代双设备应用实际校验与回复。
