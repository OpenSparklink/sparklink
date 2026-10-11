# 四只 WS73、两组并行空口回归

这是双设备北极星之后的独立扩展门禁。当前工具和字节、时序、真实管道回归
已接通；尚未完成四只真实设备的资格运行，不表示自动恢复或完整子系统验收。
当前双设备物理拔插 VM 的冻结输入保持独立，必须先完成该进程再占用四只设备。

## 运行

使用 `ws73_target.py prepare` 生成包含本版本工具的合格 native scratch-root VM
包，保持已核对的内核、模块、服务、QEMU opt-outs 和 1.10.111 固件来源。
随后运行：

```sh
python3 tools/ws73_target.py run \
  --prepared /absolute/path/to/qualified-prepared \
  --output /absolute/path/to/new-evidence-directory \
  --ports 1-2.1.1 1-2.1.2 1-2.1.3 1-2.1.4 \
  --parallel-pairs --timeout 1800
```

只在 VM 内运行实验驱动和服务。父进程逐只接入，确认前一只独立 Ready 后
才接入下一只。应用由 UID 1000、无 capabilities 的两个实际进程执行，
共享同一认证 D-Bus owner 和 `slkd`，分别控制两个独立 adapter 对。
禁止混用模拟后端、故障注入、QMP 拔插或 Managed hold 门禁；不修改主机权限。

## 判定

每组交换角色 20 轮，每轮使用独立随机标识；扫描端在 10 秒内匹配数据、
地址和 RSSI。实际管道屏障在开始前等待两组，且在两组收到匹配后才允许
广告 OFF；屏障等待有 15 秒上限。任意失败保留原输出，不补造成功。

进程退出并回收后读取工件。两个 worker 的命令、注册、认证 daemon、
屏障和最终 OFF 必须完整一致。共享核对器逐轮核对实际 USB/HCC/DLI
OUT、Complete 和接收报告，并核对四只的实际注册查询。两组所有 40 个
标识及原始报告独立，不接受重复报告。每组保留两秒自身发射关闭的负例。

不仅要求两组各自成功，还要求对应的每一轮实际 START 回复至 OFF 命令
之间存在正时长重叠。两组顺序执行即使各自通过也必须失败。完整捕获无
内核丢包；沿用 VM 的 taint、内核故障、冻结来源与退出检查。

`FOUR_DEVICE_PARALLEL_RF_PASS` 仅表示此门禁。它不验证物理拔插、
自然启动故障根因或无需人工操作的恢复。相关 issues 保持开放。

## 开发回归

```sh
SPARKLINK_KERNEL_SOURCE=/absolute/path/to/linux \
  python3 -m unittest discover -s tools/tests
```

新增回归覆盖错配 worker/daemon/adapter、标识重复、屏障顺序、提前 OFF、
缺失查询、错误数据/地址、失败 URB、报告复用和无真实重叠轨迹。
真实子进程管道回归只证明协调协议，不产生硬件或空口验收证据。
共享核对逻辑已重算历史真实双设备 22 轮，所得证明与原封存结果逐项一致。
