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

## D1/D2 首个接入提交：实现与验收范围分开

Linux `1f78c540f1179aa7c8a37740b4c58eb64efb1a6b` 已接通 WS73 完整 SDU
A3 传输 callback、Native A3 RX 和 0x0009 完成入口。每 Runtime 独立持有数据
credit/debt 和最多 16 包、每包最多 2047 字节的 RX 队列。内部 DTAP seam 要求
controller/generation/lifetime/handle，旧 handle-only trait 仍不支持，未开放 raw
用户态数据 ioctl。完整 SDU 长度受真实查询值限制；缺 driver callback 不给发送容量。

USB 调用前记 outstanding，真实 NOCP 数量归还；零 count 不补 1，超额/未知完成或
不确定传输停止本 generation 数据 TX。旧 lifetime 的 debt 不因 Down 或 USB 成功
清零，阻止复用 handle 的新 lifetime 发送。RX 在 ingress 从 canonical table 绑定
lifetime；已知物理变更清理旧队列，Unknown 不推断新身份，断链/退休唤醒数据等待者。
Host→data→gate 的 IRQ 锁顺序不跨 USB I/O，发送与 native close 用 lifecycle 串行化。

17 个严格生产源码依赖测试、12 个原子 link ingress 回归，以及既有 12 connection
storage / 48 Host 与 ASan/UBSan/LSan codec 检查通过；实际 C/Rust 对象编译通过。
完整新 VM 内核正在独立构建，旧资格镜像未覆盖。离线测试中的 USB/owner/锁依赖
为 fixtures，不能证明真实数据收发或硬件完成语义。

仍缺：实机 A3/NOCP 捕获、必要 CMTC/能力/TCID/PI 路径、有限 socket TX 队列、
普通用户 socket/poll/close，以及对端应用校验并回复的业务数据闭环。
本提交没有提前完成 D1/D2，也不把内部 raw ACB seam 当成每逻辑通道 socket。
后续首先对新 VM 内核做既有建链/断链/RF 回归，再用独立测试 backend 验证实际
A3/NOCP；传输探测仍不代替普通用户业务数据验收。自然故障与自动恢复 issues 开放。

## 首个真实 ACB／PB／NOCP 双设备往返已验收，socket 仍待接通

[独立复算原始两端 USB 证据](evidence/ws73-acb-real-pb-transport-20261012.json)
绑定 Linux `e344e7b34dc6`、服务/工具 `5d9744fda824`。VM144 专用签名 external
selftest 在双方连接角色下完成 8 轮交替方向随机 nonce/载荷往返，对端实际接收、
校验并回传。64 个原始 A3 包独立重组为 32 个 SDU，16 个真实 NOCP 完成事件，
每设备每阶段准确 4 个完成计数；单次 finit_module 和卸载均成功。
其 taint4096 是明确的 external-test 标志，不作为 taint0 普通生产资格。
VM145 同源码不加载测试模块，普通 UID1000/caps0 的对象/建链/断链、RF22、QMP
回归及 taint0 通过；合计 RF44、2914 capture 包、零 drop，slkd/bus 不重启。
源码 CI9/9、19 严格数据源码及 413 工具回归通过。

失败历史保留：VM142 的 62-byte SDU 实际先收到 28-byte PB-first，full-only RX
错误拒绝导致接收设备退休；BusyBox 又重试了失败模块初始化。VM143 修复 RX 后
模块初始化成功，但工具缺 `/bin/rmmod`，整轮仍失败。后续独立重组、单次 syscall、
显式 BusyBox 卸载修复后才形成 VM144/145 证据。四只主机设备均保留连接，未切 hub。
即使短 PDU 也需要 DLI RX 重组，这是实机对依赖顺序的修正；TX 的 ACB254/5 查询
不能当作接收端始终提交完整 SDU 的保证。历史自然启动/bulk/消失根因仍未查明。

这一成果仅完成首个 D1 实机纵向传输并验证基础 D2 记账。发送/接收者为专用内核
测试后端；CUTC/实验 PI 未建立正式能力/通道协商，尚无普通用户 channel socket。
下一主线仍为必要 CMTC/能力/local-remote TCID/PI → 有限 TX 队列及 socket →
两端普通应用短 PDU 随机校验/回复 → 边界/长包/耗尽/关闭/断链/旧 lifetime →
四设备、用户态 SSAP、安全/Profile。完整 S0–S6、Managed、自动恢复和整改 issues
继续开放，不以这份底层传输证据关闭整项或替代业务验收。
