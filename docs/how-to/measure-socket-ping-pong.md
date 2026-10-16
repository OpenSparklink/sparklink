# 测量通道 socket 的时延与负载

目标：让一个普通应用发送随机消息，另一应用实际校验并回复，得到每消息的应用
RTT。当前是 benchmark 的第一个切片，已运行本地 AF_UNIX 应用回归，**尚未取得
此工具的完整性能资格**。已接通三类负载及进程资源端点快照；
schema2 的限定 Native VM 运行已具备双端捕获/来源/监督器核对，准确版本和结果见
[当前资格](../../project/current-capabilities.md)。内核资源峰值、追踪扰动及稳定性能门禁仍缺，
不能把所列命令或局部成功直接当作新构建的性能资格。

## 前置条件

仅在已部署匹配实验内核/用户态的 VM 内执行。两只真实 WS73 已独立 Ready、建链，
由 slkd 授权给普通用户；准备同次连接的两个不可变 adapter/connection 对象路径。
本页不负责安装 VM、加载固件或建立连接，不能直接在宿主运行实验驱动。
先核对[当前资格与限制](../../project/current-capabilities.md)和
[通道接口](../reference/interfaces.md)。

使用匹配的 `slktest` 构建；`slctl` 只管理设备、连接和授权。每端选择全新的 JSON
路径和单独 stderr/stdout 文件，保留编译 artifact、源码/dirty、执行工具、固件、
VM/USB/CPU 与连接实际参数身份。示例变量必须替换成该 VM 的实际对象及路径。
普通应用无需 sudo；不要用管理员身份替代授权验收。

## 操作

1. 对端终端先运行；在计时前看到 `SocketBenchmarkReady` 后再启发起端：

   ```sh
   slktest --adapter "$ADAPTER_B" channel peer "$CONNECTION_B" --count 100 --bytes 61 --report "$PEER_REPORT"
   ```

2. 发起端终端运行匹配的 count/bytes：

   ```sh
   slktest --adapter "$ADAPTER_A" channel ping "$CONNECTION_A" --count 100 --bytes 61 --report "$SOURCE_REPORT"
   ```

3. 两端保存退出码、完整 stdout/stderr 和 JSON。报告在循环后写出；不要因为等待
   时没有逐包日志而重启测试。每请求原期限 10 秒；首个失败停止这一闭环 workload，
   未尝试行仍保留。不会把超时样本丢弃后继续称完整通过。
4. 交换发起方向使用新连接 lifetime、新报告路径重做；当前同 lifetime 的 CUTC
   最后关闭后不支持重绑。不能把首次连接角色换标签当交换测试。

## 结果与失败处理

`count` 为 1..10000，`bytes` 为 29..2042 且不得超过实际 MTU/MPS；零长契约不由
该 workload 覆盖。随机 nonce/序号/载荷、缓冲与去重容量在计时前准备，热循环
无逐包打印、hex 或落盘。每条报告有计划时刻、首次 send syscall、成功 send syscall
及准入返回、读取、校验时刻、send 尝试/EAGAIN、errno、超时及循环后编码的帧。
发起端 RTT 为成功 send syscall 入口到校验完成，包含 peer 校验与回复开销；
不是 USB、NOCP 或纯空口时间。peer 的校验时刻先于其回复准入。

两端 `MEASURED_NOT_QUALIFIED`、全量 attempted/admitted/validated 与退出 0 只表示
工具循环完成；仍须核对双方随机帧、凭据/身份、两端 USB/HCC、捕获丢包、精确来源、
资源和观测开销。**报告始终 performance_qualified=false**。目前 unmeasured 字段列
出尚缺的 closure，不能把此输出直接用于性能资格或自动回归阈值。

缺回复、篡改、重复或断链使测试失败并保留已执行/未执行行；启动阶段失败留下
INCOMPLETE 标记及 stderr。文件存在直接拒绝，不覆盖前次运行。进程异常退出或
写出中断留下空/截断/INCOMPLETE 文件均不能当测量完成。保留失败再用新目录重跑。

分位数只覆盖成功样本；空样本为 null，P99.9 至少 10000 成功样本，算法与单位见
[指标参考](../reference/socket-benchmark.md)。已接通内部 `tools/ws73_channel_socket.py` 的 `benchmark_application_reports(source, peer)`，
用于双端 JSON 的字段/帧/时钟契约与分位数核对；其一致结果仍不是资格。
下述 Native schema2 监督入口另有双端捕获/来源核对；跨层精确时间线仍缺。
不能从此手工 schema1 ping-pong 或低负载样本推断饱和吞吐和公平性。


## 运行固定速率、有限窗口及双向负载

以下命令的本地应用循环及限定 Native WS73 运行已分别回归，**完整性能资格仍缺**。
仍需上述已建链 VM、普通用户、匹配构建和全新的报告路径。每次重做需新连接 lifetime。
只使用 one-shot slktest CLI；两端看到 `SocketBenchmarkArmed` 后，各自在该进程 stdin 输入
一行 `start`，或由现有 VM 监督器在核对凭据后写入 `start\n`。启动等待原期限 30 秒，
部分输入不延长，EOF 为撤回；不要提前释放一端就将它当同步的双向起点。
两端随后会各输出 `SocketBenchmarkQuiescent`。监督器确认双方都到达该点后，
分别在 stdin 输入一行 `finish`；此后才做 hex/JSON 编码并关闭 fd。结束等待也只有
原 30 秒，部分输入不续期，EOF/超时留下失败报告；它不延长消息原期限。
不能把预先排入 stdin 的 `finish` 当成已经证明双端结束；该顺序还须由 VM 监督器记录。

- 固定速率：对端使用 `slktest channel peer --load`；发端的 interval 单位是 µs。

  ```sh
  slktest --adapter "$ADAPTER_B" channel peer "$CONNECTION_B" --load --count 1000 --bytes 61 --window 16 --report "$PEER_REPORT"
  slktest --adapter "$ADAPTER_A" channel rate "$CONNECTION_A" --count 1000 --bytes 61 --window 16 --interval-us 1000 --report "$SOURCE_REPORT"
  ```

- 有限窗口：保持相同对端，发端改用：

  ```sh
  slktest --adapter "$ADAPTER_A" channel window "$CONNECTION_A" --count 1000 --bytes 61 --window 16 --report "$SOURCE_REPORT"
  ```

- 双向：双方均发送独立随机消息并处理对方请求，在各自终端运行：

  ```sh
  slktest --adapter "$ADAPTER_A" channel duplex "$CONNECTION_A" --count 1000 --bytes 61 --window 16 --report "$SOURCE_REPORT"
  slktest --adapter "$ADAPTER_B" channel duplex "$CONNECTION_B" --count 1000 --bytes 61 --window 16 --report "$PEER_REPORT"
  ```

应用窗口 1..min(count,256) 独立于协议 credit。绝对速率不因回复推迟计划，窗口满
记录本地预算拒绝，真实 EAGAIN 记录内核拒绝，不伪装成对端丢包。窗口模式在有限
窗口内推进，EAGAIN 保留原计划/期限，等待 poll 可写后再尝试。过载、超时和拒绝
保留，不能因为闭环降速而隐藏负载。ppoll 使用 ns 等待，但不承诺实际发出时间精度；
每条 dispatch/准入时间显示真实调度偏差。

每应用请求从计划/首次可推进时刻保留 10 秒原期限。对端 reply 从实际 read 起算，
重复包不刷新该期限。对端等候下一个唯一请求的进度预算 10 秒，整个运行最多
612 秒；最后保留 1 秒迟到观察。该观察窗外的迟到不在范围内，不能称永久无丢包。
每轮最多处理 32 个接收/回复/发送包，队列和观测预算有限，溢出可见。分位数排除
超时/迟到，相关原始行及计数保留；异常、正确性失败与非零退出不覆盖测量文件。

schema2 的 `LOAD_OBSERVED_NOT_QUALIFIED` 只表示本地全量循环及正确性条件满足；
失败可能输出 `LOAD_OBSERVED_WITH_FAILURES_NOT_QUALIFIED` 或 `INCOMPLETE`，进程非零退出。
所有情况 `performance_qualified=false`。现有 schema1 核对器不能直接授予 schema2 资格。
资源是测量前后进程快照，maxrss 为进程存续期最大值，非本轮峰值；队列峰值仅应用
队列。goodput 区分含 29 字节测试头的 datagram 与真正 pattern payload，分母为同一
进程的 active interval，包含失败/超时且不含最后观察窗；USB 字节率仍未知。


## 核对 schema2 应用报告

保存双方原始文件，再在独立路径生成核对结果：

```sh
python3 tools/ws73_benchmark.py --left "$SOURCE_REPORT" --right "$PEER_REPORT" --output "$CHECK_REPORT"
```

仅完整成功的两端报告可以得到 `LOAD_APPLICATION_REPORTS_CONSISTENT_NOT_QUALIFIED`。
原失败/超时仍留在原始报告，核对工具会拒绝将其显示为完整通过。文件存在不覆盖，
截断或异常退出留下的 INCOMPLETE/FAIL 不能用于资格。`--fixture` 只供显式 AF_UNIX
测试身份使用，真实 VM 门禁不得开启。报告核对尚不绑定编译 artifact、凭据、捕获
或监督器；这些仍是取得可复现性能资格的必需条件。

## 由 Native VM 监督器收集配对证据

使用匹配源码已经 `prepare` 的独立 VM 环境，指定新输出目录和实际可用两端口：

```sh
python3 tools/ws73_target.py run --prepared "$PREPARED" --ports "$PORT_A" "$PORT_B" \
  --qmp-hotplug --connection-verify --connection-advertising negotiable-t \
  --channel-benchmark window --timeout 600 --output "$NEW_RUN_DIRECTORY"
```

该入口使用实际 `slktest`，完成普通用户凭据、双端 Arms→start、双方 Quiescent→finish、
原始报告/hash、两连接角色及两端 USB 逐条匹配。可分别换成 `rate` 或 `duplex`；
首批固定20条61字节、窗口4，rate间隔100ms，不与其它通道/Agent/four-device门禁混跑。
不覆盖旧目录；失败保留后使用新目录诊断，不放宽期限，也不把 QMP 当物理拔插或恢复。

完整捕获运行结束后，可只读观测单 bulk RX URB 空窗：

```sh
python3 tools/ws73_rx_gap.py "$NEW_RUN_DIRECTORY" > "$NEW_RX_OBSERVATION"
```

该命令重放应用/USB证据后输出相同 guest 时钟的完成→重提交间隔；不操作硬件。
时间含 callback、USB core 和 VM 调度，不能等同 callback CPU 时间或 RF 时延。
诊断失败保留 stderr 和原文件；缺失输入、配对错误或掉包不生成完整观测。
结果字段和限制见[指标参考](../reference/socket-benchmark.md)。


## 在封存VM门禁上做同口径对照

准备与[Native输入契约](../reference/vm-gate-inputs.md)匹配的新prepared目录；
复用原实验内核和运行程序时仍记录它们自己的编译身份，新runner另记执行身份。
使用现有`ws73_target.py run`专项benchmark，在同一prepared镜像、两只真实WS73和
相同VM配置上，分别选择`--channel-benchmark window --channel-benchmark-window 1`
及4，并各用`--channel-benchmark-xhci on`或off。每轮全新output目录，交替运行，
保留所有尝试；不要与构建或其它设备VM回归并行进行性能采样。

完整退出后运行`python3 tools/ws73_benchmark_timeline.py "$RUN_DIRECTORY"`并保存
输出。先检查原manifest、两端随机载荷和原期限、usbmon零丢包，再比较同窗口的
多轮应用RTT与USB分段；具体单位和不能推导的范围见[指标参考](../reference/socket-benchmark.md)。
追踪缺原件、配置读回不符或任何必要门禁失败都保留失败，不拿成功轮次覆盖。
on/off差异仅说明该配置的xHCI增量影响，不授予稳定阈值或最低硬件时延。


## 在 VM 内收集 Session 服务与提交记录

需要具备 `sparklink_session_work/queue/tx` 观测点的匹配内核、重新 `prepare` 的工具
及两个真实端口。在上面的独立 Native benchmark 命令上添加
`--session-service-observe`，使用新的输出目录。也可用于独立固定 CUTC 的
`--channel-socket-verify` 或 Managed Grant 门禁；动态通道、Agent、prefix-close
及空闲观测暂不支持此组合。不能直接在宿主启动采集脚本。

监督器在私有 scratch VM 中创建独立 trace 实例，记录双方身份、原始格式、时钟
锚点与 CPU 丢失计数，退出后停止并移除实例。先通过原业务与 USB 门禁，再核对
Session 原件；任一失败整轮不能通过。输出位于 guest-output 的 `session-service/`
及 manifest 的 `session_service_observation`。缺失记录、无法关联或时钟跳变时保留
失败，不用另外一轮成功覆盖；具体阶段和限制见[指标参考](../reference/socket-benchmark.md)。

这是高扰动诊断，不授予稳定性能阈值、credit 准确性、callback drain 或公平性资格。
新入口的实机结果须按准确工具与编译 artifact 单独登记，不能继承历史资格。


## 检查短包与长包的并发进展

这是正确性任务，不输出新的性能资格。需要支持 `--start-barrier` 的匹配 `slktest`、
重新prepare的工具及真实双设备VM，使用新输出目录：

```sh
python3 tools/ws73_target.py run --prepared "$PREPARED" --ports "$PORT_A" "$PORT_B" \
  --qmp-hotplug --connection-verify --connection-advertising negotiable-t \
  --channel-socket-verify --channel-fairness-verify --timeout 600 --output "$NEW_RUN_DIRECTORY"
```

监督器先运行既有固定通道/SSAP回归，再在每次连接上协商独立短、长两个动态通道。
四个普通用户应用都Armed后才写start；测试结束后才释放保留fd。查看原manifest的
`channel_fairness_corroboration`和应用原件，核对每个方向短包确实在长包发送期间前进，
而非仅看总成功计数。缺捕获、错误载荷、原期限超时、无真实重叠都保留FAIL；
不得重复运行至通过后删掉原失败。详细范围见[指标参考](../reference/socket-benchmark.md)。

独立 `slktest --check` 动态端点也可加 `--start-barrier`，在Armed前不要写start。
只有启动调度被协调，不能由它推导公平性上界、credit真值或性能收益。新artifact的
实机资格与已封存工具分别登记，不因相同命令名称继承。


## 准备相同口径的 Native 对照

先列出两个内核 artifact 与同一用户态 bundle/执行工具、SDK111、VM/QEMU、USB端口、
CPU及Kconfig，保留完整 hash。现有硬件组合以U2/3为选定对象；第1口Hi3873E排除，
不能使用旧U1/4结果充当前测。默认USB捕获保持开启，分别记录可选xHCI及Session追踪。

Native runner 可显式设置 count/bytes/window/interval，详见[参数参考](../reference/socket-benchmark.md#native-vm-可变负载请求)。
先用每角色128条、61字节、window1/4的有限对照验证完整配置透传、计时和双端证据；
该配方已按[当前资格入口](../../project/current-capabilities.md)取得有限实机证据。采用预先确定的平衡顺序与重复次数，保留全部尝试。
复用同一个slktest二进制，不更改生产协议或消息期限。核对双方真实校验回复及两端USB，
按物理发送端/连接角色分别汇总，同一发起进程的单调时钟计算RTT；不相减不同进程时钟。

随后才按实际结果增加长包、负载扫描和观测开销对照；样本量不足时不发布P99.9，
不预设性能阈值。端点CPU/RSS/fd与内核峰值、队列/credit、URB资源分别列出；未测量项保留缺失。
