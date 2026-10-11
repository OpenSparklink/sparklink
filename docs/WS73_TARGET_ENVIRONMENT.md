# 隔离 WS73 开发客体

`tools/ws73_target.py` 创建本机 KVM 客体：运行选定内核、原生 WS73 驱动、系统
D-Bus 及项目生产权限策略、slkd、普通 uid1000 slctl、Python 实机验收工具和
tcpdump。它不安装主机内核/服务、不修改主机权限、不解绑主机驱动，也不需要
嵌套虚拟化。主机操作者使用已有 KVM/USB 权限；普通应用没有 sudo、setid 或
capability。**环境就绪不是七项真实北极星通过。**

主机仍负责一次性 USB 权限配置和提供适用板子的固件/校准/customize/PM 输入。
打包校验 SDK 文件的 64 字节 SHA256 header 和两个 raw 配置的大小，记录 hash；
不把文件格式正确当成板级认可，manifest 明确 `board_qualification=NOT_ASSERTED`。
文件仅复制到本机私有开发目录，不作为仓库发布内容。

## 准备

从 opensparklink 工作区执行，所有路径用实际本机路径替换：

```sh
python3 sparklink/tools/ws73_target.py prepare \
  --kernel-build /absolute/qualified-kernel-build \
  --qemu /absolute/custom-qemu-system-x86_64 \
  --busybox /absolute/static-busybox \
  --dbus-daemon /absolute/dbus-daemon \
  --firmware-dir /absolute/ws73_SDK/firmware/us \
  --runtime-config-dir /absolute/reviewed-board-config \
  --output /absolute/private/fresh-prepared
```

还需要本机 tcpdump、当前 Python、gcc/cargo 工具链依赖及 cpio/gzip/strip/ldd。
`--tcpdump` 可选择具体 binary；`--python` 必须与运行脚本的解释器一致，避免
stdlib ABI 混用。prepare 离线构建实际项目程序，复制动态依赖及 Python stdlib，
strip 的只是客体副本；不修改原 binary。默认内核须内建 SparkLink/WS73、usbmon
与 virtio/9p；缺任一配置就拒绝。支持自建 QEMU 的 `usb-ws73-test` 与 virtio-9p。

archive 的所有 inode 强制 root:root；普通应用不能改写 daemon、代码或固件。
密码账号锁定，交互入口由客体 supervisor 切换至 uid1000/gid1002，附属
sparklink 组为 gid1000。raw chardev 权限仍由内核 CAP/ownership 检查，不下放
usbmon。tcpdump 启动时打开限定客体 USB bus，随后显式降至 capture uid1003/
gid1003、零 capabilities。正在写的 pcap/statistics 为 root 私有；停捕获后才
封存为控制组可读。

manifest 封存 kernel/config/initramfs/QEMU、输入/source、原/strip 后程序及
guest-files 的 SHA256；run 再核对实际使用的 artifacts，不用文件名或旧 PASS
判断内容。失败、超时与未完成的运行保留，不自动重试并覆盖。输出目录必须全新。

## 两只真实设备

真实入口要求 QEMU 编入 libusb 的 `usb-host` 并带有项目的
`kernel-driver-detach` / `host-reset` / `host-retry` 扩展。Linux 自建 QEMU 脚本强制启用
libusb，并应用[可复现边界补丁与检查](https://github.com/OpenSparklink/linux/blob/3d765538b178182eb86342ffe912bcf01f6a1cab/tools/testing/selftests/sparklink/qemu-sle-dli/README.md)。
`run` 先执行 `-device usb-host,help` 记录实际属性；缺设备类型或任一所需
属性就留下 FAIL、不启动 VM。原合成 QEMU 没有 libusb，这个前置条件未满足；
仅 support 成功不能作为它支持透传的证据。

物理对象限定 hostbus/hostport **和** ffff:3733，所有首次/重加路径同时关闭
`kernel-driver-detach`、`host-reset`、`guest-reset`、`guest-resets-all`。
QEMU 默认值保持兼容，真实 runner 显式设置 false；不允许省略选项回退。
这阻止 QEMU 的自动重连/配置/退出路径解绑、重新绑定主机驱动或执行生命周期
reset。另一主机驱动已占用时，保留占用并等待/报错；guest 不能借此获得该接口。
ROM 自身重新枚举与实际物理拔插仍需测试；补丁/暂停 QMP 检查不是实机证明。

物理重连保留同一个固定端口 usb-host 对象，最多等待20秒确认 attached 与
启动的QEMU子进程持有当前USB节点的live fd；udev/usbfs状态交接继续等待。
6秒后仍未占用、未attached、无该live fd时仅请求一次 `host-retry=true`。
这是恢复单对象failed-open预算的脉冲，读回false，既有autoscan负责再开；
并发开成功时setter不做任何操作。请求不代表接管/Ready，不通过删掉重加
对象刷新状态。外部驱动和权限/所有权超时保留失败；另一个端口独立轮询。
两个launcher复用同一Watcher和预检，旧guarded binary缺host-retry也会拒绝。

```sh
python3 sparklink/tools/ws73_target.py run \
  --prepared /absolute/private/fresh-prepared \
  --ports 1-2.1.1 1-2.1.2 \
  --output /absolute/private/fresh-physical-run --timeout 1800
```

必须在有 stdin 的终端运行。两个端口须是可写的 ffff:3733，且启动前没有主机
驱动占用。进程与旧固件 lab 共用真实 flock，防止同时透传同一设备；锁文件本身
不当作“正在运行”证据。客体无网卡，只把本轮空的 guest-output 目录通过 mapped
9p 导出；不暴露主机仓库或其他目录。所有复制、9p 写入与 VM 都由主机普通用户
执行。涉及 root 的初始化/daemon/打开捕获只发生在一次性客体中。

VM 启动时不附 USB。tcpdump 确认监听后才添加第一只，普通 slctl 证明第一只
独立 Ready 后才加第二只。固定 hostbus/hostport 对应客体 1-1/1-2，不使用容易
变化的 host address。ROM/重插枚举地址变化时，已有本 QEMU 的 live fd 和
attached backend 继续保留；未被占用的端口可刷新 QMP，未知 usbfs/其他主机
驱动不会被解绑。这个真实透传/ROM/重插路径尚待实机检验，合成 support 不能
证明它。

两只 Ready 后，程序显示普通用户的完整 North Star 命令，包含实际 daemon PID、
客体端口、kernel/firmware/config artifact 路径与新的输出目录。进入的交互 shell
只有 uid1000。执行所显示命令，按提示真实拔出/重插第一只；Host 不自动代替
物理拔插或回复确认。10 秒随机标识匹配、20 轮交换、同 daemon owner/PID 与
survivor 隔离由 [实机 recorder](WS73_PHYSICAL_TEST.md) 验证。需要延长环境
使用时间时显式调整有限正数 timeout，不把 timeout 当作成功。

物理交互环境超时后，Host在普通用户shell已经就绪时发送取消信号，等待
应用清理完毕后新出现的shell提示符，再退出shell让supervisor封存抓包。
不会回复物理拔出/重插提示，也不会以旧提示符推断应用已经退出。
普通shell返回0仅用于正常封存；被取消应用的FAIL仍保存在run.json，Host
仍返回非零并记录原环境超时。最多额外等待30秒，超出后保留部分证据并
停止guest。尚未就绪、合成及QMP自动控制路径继续保留原总超时边界。
只有guest完整退出、封存统计为零丢包且pcap数量一致时，诊断state才为
SEALED；这始终不是物理验收成功，也不清除原失败原因。

应用测试完退出 shell。supervisor 停 slkd 并等待清理，随后 SIGINT 停 tcpdump、
封存零丢失统计与完整 dmesg。Host 保留 console、QMP、前后 USB inventory、
host/guest/controller 物理映射、自动重新枚举记录、pcap 和应用证据。状态至多
为 ENVIRONMENT_FINISHED，`physical_acceptance` 始终 false；单纯退出 shell
不代表广播发现通过。

之后在主机普通用户下验证实际导出的 run/pcap/statistics：

```sh
python3 sparklink/tools/ws73_north_star.py verify \
  --run /absolute/fresh-physical-run/guest-output/application/control/run.json \
  --pcap /absolute/fresh-physical-run/guest-output/ws73.pcap \
  --capture-stats /absolute/fresh-physical-run/guest-output/capture-stats.txt \
  --output /absolute/private/fresh-verified
```

USB 地址使用 run 中的客体映射，不混用 host bus/device。RX_CORROBORATED 仍不
自动认可板级参数/实际部署 provenance，也不自动关闭 issue。详细边界见
[物理证据](WS73_PHYSICAL_TEST.md)和[完整验收定义](WS73_DISCOVERY_NORTH_STAR.md)。

## 开发支撑门禁

```sh
python3 sparklink/tools/ws73_target.py support \
  --prepared /absolute/private/fresh-prepared \
  --output /absolute/private/fresh-support --timeout 120
python3 -m unittest discover -s sparklink/tools/tests -p 'test*.py'
```

support 只添加两只明确标记的合成模型，不接触主机 WS73。它验证系统 D-Bus
观察/控制策略、uid1000/零 capabilities 的串口 TTY 输入、代码/固件不可改写、
应用无 usbmon 权限、capture 进程降权、两只 Ready、20 次普通应用交换及 TX-off、
实际客体 usbmon 原始数据与应用结果、两种独立 snoop 文件字节一致。Python
实机 recorder 必须明确拒绝这些 synthetic USB 描述符并保留 FAIL，不能把
SUPPORT_PASS 当成真实 firmware/ROM/USB 透传/RF 或拔插七项验收。

可单独增加 `support --empty-bulk`：自建 QEMU 须包含新 `runtime-zlp` 属性。
模型在每条 post-bootstrap 命令回复前排入成功零长度 bulk IN 完成，不清除
in-flight 命令、不伪造 DLI。它覆盖异步初始化停止与后续管理事务，避免把合法
空 USB transfer 当成坏 HCC。客体与主机都从封存 usbmon 验证两只设备实际收到
空完成，仍须满足全部20轮、原始RX对应与独立snoop条件。该选项仅用于 support，
真实 run 不提供注入选项。普通 support 不依赖新属性。

`support --hotplug` 复用实机 recorder 的完整控制流程，但入口是单独的
`ws73_target_control.py` 合成 subclass，scope/status 始终不同。它只接受明确的
OpenSparklink/WS73 fixture 描述符，仍执行实际 sysfs 原生身份与普通 slctl
Ready核验；实机 `run` 继续拒绝这些描述符，没有绕过开关。普通uid1000 TTY
进程完成20轮交换/TX-off后发出合成移除请求；Host只对自己的QEMU移除slot0，
确认删除后回应。应用确认客体sysfs中的该端口已消失、幸存身份/generation
与scan事务保持、旧adapter选择拒绝，之后请求同端口合成重加、等新代次Ready，
完成两轮与第二次TX-off。全程要求同一slkd PID/start_ticks及总线owner。

可与 `--empty-bulk` 合用，显式 timeout 180。此时封存capture包含三代次USB
身份：原两只与重加slot0。共同控制佐证必须核验22个唯一标识、全部参数/数据/
enable/disable Complete的命令时间窗、每代次四个实际metadata查询、两次阴性
区间、最终stop确认与生命周期记录。三代次有空完成时也分别核对。原20轮
support基线保留；QMP操作仅为开发支撑，不能冒称物理拔插/重新枚举/RF。

合成佐证单独保存在 `support-control-proofs.json`，`physical_acceptance=false`。
实机 `verify` 拒绝该记录；即使仅将scope/status改成physical成功标签，仍根据
原始descriptor拒绝fixture。缺失/格式错误的三项记录descriptor也拒绝。
这个检查不认证PCAP或防止任意篡改；完整来源与真实硬件证据仍须独立审查。

捕获解析器单列 `empty_bulk_completions`（USB身份、时间、URB与文件偏移）；
不将它计入 HCC/DLI Complete 或 discovery report。成功空完成须无 payload、
完整64字节usbmon header且两种时间误差不超过1ms；失败空完成仍进入 transport failures，
非空畸形数据仍拒绝。驱动先处理 URB status，再跳过成功空 bulk、重投相同URB；
八字节interrupt notification的约束保持。USB短读约定见
[Linux USB API](https://docs.kernel.org/driver-api/usb/usb.html)。

原生 sysfs `controller_error=100` 是 0x100 sentinel：尚未观察到错误事件。
它不是“成功 status=0”。真实 controller error byte（包括 0）会使 transport
Fault；就绪判定拒绝任何错误字节、broken、不 streaming、零 generation。
旧 recorder 错误要求 error=0 的问题已修正，保留 sentinel，并有实际模型与
filesystem fixture 验证。

## 实际 C/Python 原生绑定门禁

prepare另构建实际cdylib与链接生成C头文件的`native-bindings-probe`，复制Python
包及动态依赖。所有库、源、probe与客体副本纳入manifest/hash；Cargo输出名为
`liblibsparklink.so`，客体同时提供`libsparklink.so`别名，不影响旧C符号。

显式support在20轮（hotplug时20+2轮）完成后、同slkd仍持Managed时，执行两语言/
两设备/root及uid1000共八次实际观察：完整snapshot、generation拒绝、另fd没有
lease token、root忙锁、普通writer/snoop EPERM、独立事件/trace相同、quiet时不改
cursor/output和模式混用拒绝。事件比较必须在真正模型RX之后，setup Complete
不能冒称spontaneous事件。hotplug还保留四个C/Python event/trace旧handle，实测
移除后poll ERR|HUP、ENODEV；重加后旧fd/旧代次仍拒绝，新实例匹配新generation。

slkd实际TERM清理后，root两语言各在两只live注册上获得Managed、完成typed
scan/adv stop、查询终态，再释放/等Free并接任Diagnostic；另fd拿相同token仍
EPERM。四次writer的Complete必须存在于封存USB的对应USB身份、opcode及调用
时间窗，返回成功文字不够。后继probe不重新启动daemon，不作为普通应用运行
权限声明。8次observe/4次writer及旧handle日志保存在`bindings-*.json/log`；
全部作为开发支撑，真实run不执行这些probe，也不改变七项实机验收。
