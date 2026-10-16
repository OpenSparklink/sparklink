# Socket benchmark 指标与报告契约

适用：ADR0006 的规划契约；目前没有当前 HEAD 的性能资格。首个 ping-pong 工具切片见
[操作指南](../how-to/measure-socket-ping-pong.md)；固定速率/窗口/双向的应用循环已接通，完整证据闭包尚缺。
历史 channel-roundtrip／burst 与当前 slktest --check 是功能门禁，计时包含日志等开销，不能升级为基线。
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


## 当前 CLI 参数与 schema2 边界

| 命令 | 路径后的位置参数 | 行为 |
|---|---|---|
| slktest channel ping / peer | CONNECTION --count N --bytes B --report FILE | schema1，单未完成请求／校验回复 |
| slktest channel rate | CONNECTION --count N --bytes B --window W --interval-us U --report FILE | schema2，绝对计划 |
| slktest channel window | CONNECTION --count N --bytes B --window W --report FILE | schema2，有限应用窗口 |
| slktest channel duplex | CONNECTION --count N --bytes B --window W --report FILE | schema2，两端独立发起/应答 |
| slktest channel peer --load | CONNECTION --count N --bytes B --window W --report FILE | schema2，应答rate/window |


count 1..10000，bytes 29..2042 且匹配实际基本 CUTC MTU/MPS。window 1..min(count,256)，
interval 10..1000000 µs，总计划不超过600秒；其它模式 interval 为0。schema2 等待
原30秒 `start\n` 屏障，消息原10秒期限，1秒尾部观察，测量循环上限612秒。
循环结束输出Quiescent，双方到达后监督器各发 `finish\n`，结束等待另有原30秒预算；
fd保持到结束授权，hex/JSON在其后生成。该预算不续消息期限，最终失败不覆盖原循环错误。测试中的
较短 AF_UNIX 期限是显式 fixture 参数，不替代真实模式常量或协议期限。

`outgoing` 全量保留计划/dispatch、首次及成功 syscall、准入、原 deadline、read、
校验、尝试/EAGAIN、errno、本地预算拒绝、超时、迟到及 reply_count。固定速率
即使未尝试也保留原计划。`incoming` 保留实际本地校验与回复准入时间；未知或
错误不能伪造成功行。counter 区分重复请求/回复、乱序、损坏、未知/非预期包、
记录和 reply 队列溢出；接收观测最多 count×4+16 包，达到预算后失败退出。

每轮 32 包预算，各应用队列预留容量，热循环无日志/hex/落盘，无全记录扫描；
逾期检查和最早期限查询仅遍历有限窗口。通知不映射协议 credit；应用超时释放
应用等待预算，不抹去内核或控制器的在途义务。

report 的 correctness 只是单个应用的限定检查。CPU user/system delta、RSS/fd 是
进程端点快照，含采样端点开销，maxrss 是进程 lifetime，不是本次峰值；内核资源
与 USB 字节率仍 null。每秒率分母 active_elapsed_ns 包含失败/超时，排除1秒尾窗；
pattern goodput 排除29字节应用测试头，datagram goodput另列；DLI/DTAP/HCC/USB
开销未取得时不得补猜。完整追踪与低扰动差值仍未测量。

schema1 双端核对含迟到拒绝；schema2 已有独立应用报告核对（载荷/方向/
逐消息期限/计数/分位数/goodput/进程端点/结束屏障结果）。它拒绝失败或缺字段
取得完整一致结果；原诊断报告仍保留。来源/捕获/监督器闭包仍缺，不能把应用层
一致当 Native 或性能资格。新模式尚无真实 WS73 性能资格。


## 工具所有权与迁移

`slktest` 是应用测试的唯一规范入口，使用内部库中的同一套旧 channel/benchmark
实现；`slctl` 不再接受旧测试命令，负责管理、连接、授权和日常交互。--adapter
必须给出当前完整对象路径，与 CONNECTION 的 generation/lifetime 一起核对。
`ping/peer --check` 保留原正确性门禁和 stdout receipts；测量不加 --check 且须 --report。
--exercise boundaries/prefix-close/burst 保留原约束；动态只在 --check 下提供完整的
--source-port/--destination-port/--aid，--hold 仍等显式close，不承诺动态 benchmark。

代码迁移不改 schema1/2、wire、socket/Grant/credit/Ticket 或原期限。历史证据中的
slctl 命令和 artifact/hash 保持不动，由原提交工具复核；当前 verifier 的旧 argv 分支
仅解读历史记录，不是运行时兼容入口。新 binary/runner/报告来源和实机资格单独登记。


schema2 的 `finalization` 为新增必要字段：completed、原 budget_ns、elapsed_ns、error；
CLI预算为30秒，显式本地fixture为1秒。旧schema2报告保持原身份，缺此字段不能授予
当前结束屏障资格，不另改schema版本。核对器支持rate/peer、window/peer或duplex/duplex，
允许方向交换；只在各进程的时间域内运算。应用报告核对不证明监督器确实等待双方，
该事实必须与实际输入/输出时序及artifact/capture一起单独核验。
