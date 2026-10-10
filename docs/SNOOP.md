# 原生 WS73 独立 DLI snoop

`slkmon` 和 `slkdump` 默认使用每设备独立记录，而不是读取 Host 的命令回复队列。
先用 `slkconfig adapters` 查询 index/generation，再显式选择两者：

```sh
slkmon --adapter 0 --generation 7 --write mon.snoop --count 32
slkdump --adapter 0 --generation 7 --write dump.snoop --count 32
slkmon --adapter 1 --generation 8 --filter 0x180b
```

每条 snoop ioctl 需要 CAP_NET_ADMIN，poll 也检查当前调用者权限。该权限是独立
raw 诊断权限；普通用户通过 slctl/slkd 广播与扫描无需 sudo。工具不拿 Managed
或 Diagnostic lease、不发命令、不清历史回复、不切换全局 adapter。两个工具可与
slkd 并行观察同一 registration，各自使用 cursor；reader 的读取不消费任何其他
reader 的记录。C/Python snoop 绑定尚未提供。

当前只支持 WS73 profile 1。旧内核返回 ENOTTY 时工具报错，无破坏性 fallback。
必须使用单独 fd：同一 fd 已使用 ControllerEventGet 时，SnoopGet 返回 EBUSY，
反向也同样拒绝。DEV_SELECT 重置该 fd 的观察模式。generation=0、未来 cursor、
flags/reserved 非零拒绝；旧 generation 返回 ENODEV。EAGAIN 表示暂时没有记录；
库先激活 snoop 模式再注册 AsyncFd，通过内核 waitqueue/epoll 等待，不使用定时轮询。
拔出唤醒旧 fd，poll 返回 ERR|HUP，下一查询 ENODEV；工具以错误结束。重插必须
重新查询并选择新 generation，旧 observer 不会转向复用 index 的新设备。

兼容 `--legacy` 仅允许确切 generation 的 profile 0；它仍使用旧消费型队列，
不具有原生 snoop 的独立观察、唤醒、文件格式或完整错误处理保证。原生 `--filter`
接受十六位十六进制 WS73 A1 opcode 或 A2 event code（如扫描报告 `0x180b`），
旧模式为八位 event type。过滤与 `--count` 在用户态生效。原生记录总是显示完整
已捕获前缀的 hex；`-X`/`--hexascii`/`--raw` 是旧模式的渲染选项。

## 记录来源与限制

每个 Runtime 有 64 条预分配 ring，producer 不分配、不发 I/O、不改变协议状态。
RX 来源是 WS73 USB/HCC 解帧后、service=10/queue=8 的完整 SLE slot，在 DLI
schema/domain 解析前记录，包含 A2 header；非法 DLI 仍能被观察。HCC 无效包、
其他 service/queue 和 WS73 启动/ROM/BSLE 握手不属于此通道。

TX_RESULT 记录 blocking transport 尝试的结果，包含与 wire codec 相同的 A1
header/opcode/parameters。其内核时间戳在 transfer 返回之后，因此对应 RX 可能
先出现。status=0 只代表 transport 成功，不代表控制器 DLI Complete 成功，也不
代表空口发射成功；负数是传输错误。序列号是观察顺序，不是命令关联 ID。

每条保存最多 320 字节，保留 original_length、captured_length、TRUNCATED。
当前广播/扫描和查询包可完整保存；更大的 packet 明确记录前缀，不能当成完整包。
`lost = seq - after_seq - 1`，精确报告 ring 覆盖掉的记录数；不把丢失悄悄吞掉。
timestamp_ns 为 CLOCK_BOOTTIME，不能与 UTC 直接比较。工具输出 raw 数据含
无线数据，capture 新建时权限 0600，已有路径拒绝覆盖。写入/flush 失败会结束工具。

这个格式是 **DLI seam capture**，不是 PCAP、原始 USB/HCC aggregate 或真实
RF 抓包。真实北极星仍需同时保留接收端 USB/HCC trace、slctl marker/address/RSSI/
时限记录、TX-off、物理 USB 身份/拓扑和固件 provenance。合成 QEMU 数据不计入
七项真实验收。

## 可移植文件与 UAPI

文件首先写 16 字节 header：ASCII `SLKSNP01`，LE u32 version=1、LE u32
payload_max=320；后面每条固定 376 字节，所有整数为 little-endian。UAPI 自身
是固定大小的 native integer 结构体，8 字节对齐，无用户指针；文件逐字段编码，
不直接依赖主机 ABI。

| 记录 offset | 类型 | 字段 |
|---|---|---|
| 0/8/16/24 | u64 | seq/generation/timestamp_ns/lost |
| 32/36/40 | u32/u32/i32 | profile/original_length/transport status |
| 44/46/47 | u16/u8/u8 | dev_index/direction(1 RX,2 TX_RESULT)/format(1 WS73 DLI) |
| 48/50/52 | u16/u16/u32 | captured_length/flags(bit0 TRUNCATED)/reserved=0 |
| 56 | byte[320] | payload；captured_length 后全零 |

`SL_IOCTL_SNOOP_GET=0xc198538e`：408 字节 query（generation/after_seq u64、
version/flags u32、reserved u64、offset32 的 record）。请求 record 内容被忽略。
query 成功后返回一条 `seq > after_seq` 的最早可保留记录。独立 fd 的 poll cursor
只在成功 copyout 后前进；EFAULT 保持该请求的未读 cursor，允许重试。权限检查
在 usercopy 之前，继承 fd 后丢失 CAP_NET_ADMIN 不得继续读取 payload。

## 可复现虚拟门禁

使用合格内核配置和带 runtime-policy/medium 的自建 QEMU，不安装主机服务：

```sh
LIBRARY_PATH=/path/to/static-libc python3 \
  linux/tools/testing/selftests/sparklink/run_daemon_lifecycle.py \
  --kernel-build /path/to/qualified-build --qemu /path/to/custom-qemu \
  --busybox /path/to/busybox --userspace /path/to/sparklink \
  --dbus-daemon /path/to/dbus-daemon --output /path/to/fresh-evidence \
  --radio-policy --production-policy --kernel-authorization \
  --management-handoff --diagnostic-tools --snoop-tools
```

`--snoop-tools` 要求 `--radio-policy`。门禁同时运行实际 slkd、普通 uid1000 slctl、
实际两种 root capture 工具和 C syscall probe。先建立两个独立 observer，再执行
原有 20 轮角色交换；逐字节比较两份 32-record 文件并核对 raw RX 报告与独立
slctl 的地址/RSSI/data，验证慢 reader 丢失、copyout 重试、CAP/继承 fd、模式
混用拒绝、无管理 admission。拔出时核对旧 fd ERR|HUP/ENODEV 和实际工具终止，
重插验证旧 generation 拒绝、新 generation 可抓取。完整 console、QMP、capture
文件及 source/input/program SHA256 保存在 fresh output 中；host parser 校验
真正导出的文件字节，不只接受成功文字。

虚拟协议、安全/故障/PM/发布矩阵、其他 profile 与真实四设备并行仍需后续工作。
本阶段不关闭任何整项 issue，也不声称达到真实空口验收。
