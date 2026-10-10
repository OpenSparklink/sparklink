# 双真实 WS73：控制记录与原始接收证据

第一北极星与原七项条件见 [验收定义](WS73_DISCOVERY_NORTH_STAR.md)。本工具把
控制运行与 USB/HCC/DLI 接收佐证分成两份记录：`CONTROL_PASS_EVIDENCE_PENDING`
只表示普通用户的控制流程完成；`RX_CORROBORATED` 表示抓包与控制记录一致。
两者均不自动认证固件/板级校准，不自动关闭 issue，也不冒称 PHY 嗅探器。
当前本机未枚举到 WS73，工具没有实机 PASS。

离线verify也独立检查initial/replacement的完整manufacturer/product/serial
记录（值可为None）；拒绝synthetic/fixture，不仅信任scope/status成功标签。
这与实机registration的描述符拒绝规则一致，不认证可任意编辑的PCAP/JSON。
开发客体可用独立合成入口复用同一控制/时间窗佐证流程；其结果不能进入实机
RX_CORROBORATED，详见 [客体完整控制支撑门禁](WS73_TARGET_ENVIRONMENT.md)。

可使用 [隔离 KVM 开发客体](WS73_TARGET_ENVIRONMENT.md) 打包并启动系统总线、
普通应用和启动前 usbmon；它不安装主机服务，环境与实机验收分别记录。

## 准备

目标机器须运行本项目内核、驱动和 slkd，部署适用本板的固件、校准与权限。
这属于安装阶段；本工具、slctl 及其每一次应用调用以普通用户运行，不执行 sudo。
使用系统 D-Bus；工具拒绝 root、setid 身份与 effective/permitted/ambient capability。
slctl 可执行文件也不得带 setuid/setgid 或 file capability。

系统 D-Bus 使用[观察/控制策略](DBUS_AUTHORIZATION.md)：未授权用户仅查看，
管理员一次性加入 `sparklink` 组的用户可控制。安装后的新会话确认 `id` 包含
该组，再运行 slctl；不要用开放的 session bus 代替生产授权。原生 WS73 已有
fd/generation owner lease 与 CAP 检查；完整其他 profile/Proxy/PDU/Security
权限迁移仍待做，静态总线策略不能算完整权限 issue 已完成。

选定两个固定物理 USB 端口，例如 `1-2.1.1`、`1-2.1.2`。工具从 sysfs 验证
ffff:3733、真实原生驱动绑定、metadata、streaming、每代次地址/版本/80-bit features。
它拒绝标为 synthetic/fixture 的设备。`slctl daemon` 通过总线返回实际 slkd
unique owner、PID、UID；运行期间同时核对 PID/start_ticks，防止误认同名或重启进程。
正常 native_runtime 中 controller_error=100 表示未收到错误事件；真实错误
字节（包括0）不是正常状态。验证器按驱动实际 sentinel 检查，不伪造成功事件。
`slctl --adapter <path> show` 的 Ready/代次/地址须与该物理映射一致。

由有权限的捕获进程在测试 USB 总线上启动全长 usbmon 抓包，**在设备冷启动查询
之前开始**，运行/重插完成后停止，并保存 tcpdump stderr。使用隔离测试总线，
封存的抓包及统计文件提供给验收用户；不为应用开放全机 USB 捕获权限。示例：

```sh
tcpdump -i usbmon<BUS> -s 0 -w ws73.pcap 2> capture-stats.txt
```

上面的捕获进程需要预先具备相应权限，工具不会自动提权或修改权限。普通用户
运行下面的应用流程。usbmon 与 slctl 应在同一目标内核中记录时间和 USB 地址；
USB passthrough guest 使用 guest 内的捕获与端口映射，不能混入 host bus/device ID。

解析器支持 classic pcap LINKTYPE_USB_LINUX_MMAPPED (220)，micro/nanosecond、
两种文件字节序。格式来源为 [Linux usbmon](https://docs.kernel.org/usb/usbmon.html)、
[libpcap USB header](https://github.com/the-tcpdump-group/libpcap/blob/master/pcap/usb.h)
及 [pcap-savefile](https://www.tcpdump.org/manpages/pcap-savefile.5.html)。pcapng、
截断 payload、错误类型、缺失 capture stats、非零 drop 或记录数与统计不一致均不算通过。

## 控制流程

```sh
slctl daemon
python3 tools/ws73_north_star.py run \
  --ports 1-2.1.1 1-2.1.2 \
  --slctl /absolute/path/slctl --slkd-pid <bus-returned-PID> \
  --artifact kernel_image=/absolute/path/bzImage \
  --artifact firmware=/absolute/path/ws73.bin \
  --artifact wifi_calibration=/absolute/path/wifi_cali.bin \
  --artifact btc_calibration=/absolute/path/btc_cali.bin \
  --artifact bsle_custom=/absolute/path/bsle_custom.bin \
  --artifact pm_config=/absolute/path/pm_config.bin \
  --output /absolute/private/evidence/control
```

请保留固件/校准来源、板级审查记录、实际部署日志与源码/构建 hash。`--artifact`
只封存文件内容 hash，不代表这些文件就是设备实际加载的内容或已获得校准认可。
部署/内核加载证据仍须单独审查。无附件也能开发控制工具，但不能因此通过完整七项。

工具连续运行 20 轮，每轮由 slctl 随机生成标识、另一只扫描精确匹配数据/地址/RSSI，
然后两端停止并交换角色。10 秒界限同时核对 CLI 内部时间和调用者 monotonic 时间；
失败立即停止连续计数，不用重跑补齐。每轮保存命令原文、完整 header、序号和代次。
20 轮后，两 TX 停止，RX 重新开启并观察至少 2 秒，无测试地址的新报告。

随后提示只拔掉第一只设备。另一只须保持原代次/地址并成功开始、停止扫描；旧选择
须失败。提示重插后，设备须获得新代次、同一 slkd PID/start_ticks/总线 owner，
再完成独立两轮与 TX-off 负向。工具不重启 slkd、不通过软件解绑代替真实拔插。
结束/失败时尝试对仍存在的真实设备完成停止，清理失败也记为 FAIL。

新输出目录不可复用；失败、超时、stdout/stderr、未完成操作和清理错误保留在
`run.json`。停止抓包后再进行离线验证，两个输入与统计文件必须保持内容不变。

## 原始证据佐证

```sh
python3 tools/ws73_north_star.py verify \
  --run /absolute/private/evidence/control/run.json \
  --pcap /absolute/private/evidence/ws73.pcap \
  --capture-stats /absolute/private/evidence/capture-stats.txt \
  --output /absolute/private/evidence/verified
```

佐证要求每个 RX 的成功 endpoint-1 bulk IN completion 中具有完整 USB aggregate。
先原子检查全部 HCC slot 边界，再检查 WS73 0x180b 的完整23字节头与声明长度。
地址、RSSI、43字节数据、物理 bus/device、每轮时间窗必须与 slctl 完全一致；
保留 record/file/slot offset 与 USB payload hash，方便独立核对。OUT/S submission
或发送者自己的数据不能充当 RX。控制命令的成功 Complete、各注册实际元数据
查询 Complete 也须存在；重插查询须在首次移除之后。

负向时间窗必须由原始 ScanEnable/ScanStop Complete 围住，并有封存的零丢包统计。
该窗内出现测试地址报告就失败。拔插导致的取消 URB 保留为失败记录；它可以在
预期的拔插区间出现，不能出现在已通过发现轮次中。

验证器不把手工声明的 PASS、Ready 或“真实”标签当作完整证据。抓包与运行记录
本身未加密认证，必须核对其实际来源、源码及部署 provenance。合成 fixture 只用于
解析器/判定测试，永远不作为本项目实际硬件/RF 验收记录。

开发检查：`python3 -m unittest discover -s tools/tests -p 'test*.py'`。完成真实
双设备验收后，再扩展四只两组并行及交叉报告/单设备拔插隔离；完整 S0–S6 保留。
