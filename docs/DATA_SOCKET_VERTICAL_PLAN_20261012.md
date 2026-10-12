# 真实 WS73 每逻辑通道 socket：近期实施顺序

2026-10-12 用户调整的优先级。保留完整 S0–S6 和现有分层；本节取代此前
“先穷尽控制面竞争组合，再开始数据面”的近期排序。完整目标及原 issues 均保持开放。

## 起点与证据

核对 Linux `3840ec2ba70ca7fcf033fac5dde23ba020f11412`、用户态
`24ef21c46ec8d4db6f3f84d95326db5676fc3bd4`。真实运行内核为 `38997dc457be`，
服务/工具为 `5f86cc500ed8`；后续源码变更需重新验证，不继承实机通过标签。
[Peer/Connection 证据](evidence/ws73-typed-peer-lifetime-objects-20261012.json)
记录 VM139/140、双方真实 handle 0 的 lifetime 1→3 复用、24 次旧对象 CLI 拒绝、
RF44、2916 个 USB 包及零 capture drop；VM138 的工具解析失败保留。
源码 CI 38250456167、证据 CI 38251740356 均成功。旧对象拒绝不等于在途撤销，
空表 subscriber loss 不等于已连接数据流恢复。

当前 Native `send_data` 明确不支持；Native RX 仅接受 A2 事件。
WS73 wire codec 尚无 A3 发送入口。旧 worker 的首字节 TCID 猜测及旧连接资源
不能充当 Native 数据归属或可用 socket 的证明。默认应用未提供已验收的数据通道。

## 封装与参考差异

* T/XS 10003-2025 §7.4、OHOS `dli_layer.c`：A3 后为 12-bit handle、
  分段标志及高位属性，随后 LE16 数据长度。OHOS 的 ts 位与标准保留位存在
  差异；首个最小路径使用完整 SDU、保留位零，其他模式在明确支持前拒绝。
* libws73-usb `f4d85d0` 的 A3 builder 使用 handle 0；其注释称固定 flag，
  不能据此丢弃连接身份。参考代码写入的内层 `[TCID LE16][length LE16]`
  不能解释为标准的 16-bit TCID：T/XS 20002-2025 §6.5.1 实际是 TCID u8、
  帧类型/O/C/RFU u8、长度 LE16。该 builder 的高字节零仅覆盖基础帧。
  TCID 0x01–0x1d 省略 PI；CUTC 0x1f 及动态业务通道需要 PI，不能将原始
  应用载荷直接按 SMTC 格式搬过去。单播线上携带对端 TCID，RX 查本端 TCID。
  零 handle 只能用于真实 handle 0 的连接，DTAP 标识不等于 connection handle。
* OHOS `f0872df` 的 DTAP 明确区分 src/local TCID 和 dst/remote TCID，
  CMTC=0x02、SMTC=0x0a、CUTC=0x1f；不能把这些编号一律当作已协商业务通道。
  `NEARLINK_SERVICE_STACK_LOCAL_TEST` 的数据 stub 不属于真实协议证据。
* 当前 SDK111 两只真实控制器查询为 ACB 254 bytes / 5 packets。
  使用运行时查询值，不硬编码池大小；无缓存或无可靠完成事件则不开放发送。
* T/XS 10003-2025 §9.1.8 的 0x0009 完成事件载荷为 handle LE16 + count u8。
  libws73 的缺字段默认补 1、零 count 补 1、池容量钳制均不能代替真实记账。

标准来自本地 `sparklink-standards`，提取文本位于开发目录 `.dev/standards`；
SDK 私有二进制不提交，libws73 仅用于布局/实机观察参考，不复制 LGPL 实现。

## 依赖顺序与门禁

| 步骤 | 实现范围 | 必须取得的证据 |
| --- | --- | --- |
| D1 | WS73 A3/ACB TX/RX；严格长度/handle/分段解析；显式控制器归属 | 独立 codec 回归，加两端实际 USB/HCC/A3 capture；USB 写入只算 transport |
| D2 | 每 controller 数据 credit/outstanding；与 command credit 分离；有限队列和背压 | 真正 0x0009 归还匹配 outstanding，零/超额/旧归属拒绝；无 credit 时停止提交 |
| D3 | 必要 CMTC 信令、能力协商及 local/remote TCID 映射 | 双方协商 capture；绑定 controller/generation/connection lifetime，禁止复用错投 |
| D4 | 最小每逻辑通道 socket，普通用户收发/poll/close/link-down | UID1000/caps0 的双方应用真实校验及回复；无 daemon 伪成功或模拟数据 |
| D5 | 先短 PDU 纵向闭环，再长包、边界、分片、满队列和失效身份 | 随机序号/载荷、交换方向重复；253/254/255、credit 耗尽、断链及旧 lifetime 拒绝 |
| D6 | 四设备两组并行，再用户态 SSAP、安全及 Profile | 两组独立归属/credit/故障隔离；真实通道上的 SSAP 读写/通知/指示证据 |

socket 的 fd 必须绑定已经确认的 controller/generation/lifetime 与通道身份。
选择 `SOCK_SEQPACKET` 式消息语义作为首个设计候选；具体内核 socket 注册、
地址结构与权限模型在 D3/D4 实现时核对当前 Rust/C API，不提前宣称 UAPI 稳定。
每个收发方向显式 local/remote TCID，队列按包数及字节双重限额。
关闭/断链唤醒等待者，旧 fd 不重绑定新 lifetime；poll 只能反映真实可读或可发送容量。
0x0009 在线上只有 handle/count，没有 generation/lifetime；软件不能伪称事件携带
完整身份。旧连接尚有未结清或结果不确定的 outstanding 时，需保留旧记账归属并
阻止该 handle 的新 lifetime 发送，直到有可靠的清算屏障或 controller generation
退休；不得把晚到旧完成事件归还给新连接。具体断链清算语义需用 SDK111 实机确认。

最小纵向验收必须由对端应用实际接收随机序号与载荷、校验后回复，并由原端再校验。
保存两端应用记录及 USB/HCC/数据包证据，提供可复算 decoder 和可复现 VM 命令。
日志、广播载荷、模拟回复、USB 写入成功均不能代替连接后的业务数据往返。

## 并行整改与开放边界

必要的连接身份、取消、清理和状态同步继续完善，但 linked loss、所有撤销竞争排列
及控制面负向测试全集不再作为 D1–D4 的前置条件。生产测试行为、旧重复路径和
未接通模块仍按既有整改清单迁移/隔离/删除；新数据路径不用旧 worker 的模拟成功。
保留广播扫描、真实建链断链回归。自然故障根因、非人工自动恢复、物理拔插及
当前源码四设备验收未完成时，相关 issues 继续开放。仅 VM 内运行实验内核与设备 I/O。
每个小提交分别标记“实现 / 离线回归 / 实机通过 / 缺失”，签名提交、推送并更新 issues。
