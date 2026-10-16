# Socket benchmark 指标与报告契约

适用：ADR0006 的规划契约；目前没有当前 HEAD 的性能资格或可用 benchmark 命令。
现有 channel-roundtrip／burst 是功能门禁，计时包含日志等开销，不能升级为基线。
[接口支持范围](interfaces.md)继续适用；此页不新增 socket 能力。

## 负载与时间

| 模式 | 负载约束 | 主要测量 |
|---|---|---|
| ping-pong | 一个未完成请求；实际对端校验并回复 | 同一发起者单调时钟应用 RTT |
| fixed-rate | 按绝对计划时刻发起；过载不推迟整个计划 | 排队/准入/拒绝、丢失、超时、迟到 |
| throughput / bidirectional | 明确每方向有限窗口、队列、持续时间 | 实际校验业务 goodput 与背压 |

每条记录独立的随机序号/载荷、计划时刻、syscall 开始、成功软件准入/errno、回复
读取及校验结果。准入不是 USB 发送，未知的时间必须 null，不能用 syscall 返回
冒充 USB submit。RTT 起点明确；成功样本分位数只覆盖成功样本，失败/未完成另列。
超时仍保留记录并观察迟到；重复、乱序、损坏单列。发端随机输入计时前准备，
对端真实校验，保留可核对的接收/回复记录。证据有界、不逐包输出或同步落盘。

## 报告字段与单位

schema 版本、run id、源角色及 controller/generation/lifetime/channel 身份；
编译源码/dirty 指纹、artifact、执行工具、报告提交分开。记录 SDK111 固件 hash、
两端连接角色/参数/PHY/MTU/MPS/PDU/分片、VM/QEMU/CPU/USB 拓扑、捕获和队列配置。
请求参数与实际生效参数分开；不能取得的值标 unknown 和剩余条件。

- ns：同域单调时间，独立标 clock domain；跨 host/guest 时间须映射与误差界。
- 时延：n、min、P50/P90/P95/P99、max；P99.9 至少 10000 个成功样本且明确尾部样本
  仅 10 个，样本不足置 null，不插值伪造精度。分位数算法固定并记录。
- bytes/s、messages/s：计划负载、准入、USB 字节与对端实际校验业务 goodput 分列；
  实际 PDU/HCC/USB 开销另列，USB 流量不是业务 goodput。
- 正确性：计划/尝试/准入/对端校验/回复、拒绝(errno)、超时、迟到、丢失、重复、
  乱序、损坏、未完成，所有尝试保留；缺任一必要输入不生成完整 PASS。
- 资源：CPU、RSS、fd、worker、timer、URB、各层队列/credit 峰值及结束后的收敛；
  未测项保持 null。完整 trace 与低扰动测量分运行，量化观测开销。

时间线：应用计划→syscall/准入→Session 出队→credit/Ticket→USB submit/complete→
对端 USB RX→Session 分流→应用读取/校验→回复；NOCP 独立。无 RF 观测时，中间
区间写作包含固件/调度/无线的合并区间，不能宣称独立空口时延。

## Fail-closed 与版本边界

删除对端记录、捕获缺失/掉包、截断日志、身份/hash 不符、payload 修改、重复序号、
漏超时、旧结果贴新源码、supervisor 异常退出/SKIP、必要场景缺失、单位或起点错误、
时钟混用和空样本必须由负对照拒绝。保留原失败及最小回归；无崩溃不是证明。
只测量的诊断报告可保留，但不完整不得成为性能资格 PASS。

正常资格、性能、sanitizer/lockdep 镜像独立，不能放宽原协议期限。基线稳定后才按
相同配置设回归阈值，环境或特殊调优变更独立报告；所有 WS73 操作 VM-only。
