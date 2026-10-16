# 测量已建链通道的应用 ping-pong

目标：让一个普通应用发送随机消息，另一应用实际校验并回复，得到每消息的应用
RTT。当前是 benchmark 的第一个切片，已运行本地 AF_UNIX 应用回归，**尚未取得
此工具的真实 WS73 性能资格**。固定速率、持续双向和资源采样仍待接通。

## 前置条件

仅在已部署匹配实验内核/用户态的 VM 内执行。两只真实 WS73 已独立 Ready、建链，
由 slkd 授权给普通用户；准备同次连接的两个不可变 adapter/connection 对象路径。
本页不负责安装 VM、加载固件或建立连接，不能直接在宿主运行实验驱动。
先核对[当前资格与限制](../../project/current-capabilities.md)和
[通道接口](../reference/interfaces.md)。

使用包含 `benchmark-peer` / `benchmark-ping` 的 slctl 构建。每端选择全新的 JSON
路径和单独 stderr/stdout 文件，保留编译 artifact、源码/dirty、执行工具、固件、
VM/USB/CPU 与连接实际参数身份。示例变量必须替换成该 VM 的实际对象及路径。
普通应用无需 sudo；不要用管理员身份替代授权验收。

## 操作

1. 对端终端先运行；在计时前看到 `SocketBenchmarkReady` 后再启发起端：

   ```sh
   slctl --adapter "$ADAPTER_B" benchmark-peer "$CONNECTION_B" 100 61 "$PEER_REPORT"
   ```

2. 发起端终端运行匹配的 count/bytes：

   ```sh
   slctl --adapter "$ADAPTER_A" benchmark-ping "$CONNECTION_A" 100 61 "$SOURCE_REPORT"
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
目前还没有完整双端捕获/来源聚合器、固定
速率/有限窗口双向、跨层时间线和资源采样；不要从 ping-pong 推断饱和吞吐或公平性。
