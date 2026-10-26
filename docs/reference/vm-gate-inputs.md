# VM 回归输入契约（集成／测试参考）

Managed 连接清理门禁当前逐字节要求 SLE 主动断链原因 `0x10`，与 Native daemon
一致；`0x13` 不是 SLE 的远端主动断链原因。历史捕获只在离线显式选择
`expected_cleanup_reason=0x13` 时按旧身份复核，当前执行器不从捕获内容自动放宽。
真实 Disconnect OUT、Status、双端 Down 和原期限仍分别核对，原因值正确不代表对端已断链。

新鲜 Native 载体的 `compiled_userspace_identity` 来自已核验 service bundle 的
构建提交；准备工具的当前 HEAD 单独记录。复用入口仍要求明确编译身份，缺失时拒绝，
不能用文档或工具提交给既有 ELF 重新标记身份。

## 显式链路发送载荷偏好

可选 `--link-payload-preference reported-acb-maximum` 仅用于独立的双设备 Native
连接／业务门禁。每个连接角色下，对两端各提交一次
`slctl link-payload-preference CONNECTION OCTETS 5000`；`OCTETS` 取该端真实
ReadBufferSize 返回的 ACB 最大长度，须能编码为非零 16 位值。这是参考 Host 的
显式实验参数，不是新的默认初始化步骤，也不证明该值在固件中有效。

命令复用现有 Managed 队列、物理 Session、命令 credit、提交票据和五秒原期限。
须使用包含新内核 ABI、CLI 与固定 helper 的新产物；旧查询 ioctl 已退休，不能
只替换一个二进制。启动参数、原始调用、完整 generation／lifetime／handle、
请求参数及双端捕获必须一致。每端原始 DLI `0x1804` 参数为 handle LE16、
requested octets LE16；实测 SDK110 E 的成功 Complete 返回 handle LE16，没有请求长度回显。

独立核对器要求两端、两角色共四次真实确认及原 handle 回显，不重试、降级或接受多余回复数据。
缺失、错身份、错参数、超时和部分场景均拒绝完整门禁。确认只表示保留请求的
控制器命令成功，不能更新或证明有效数据长度、DTAP／SSAP MTU、Ready、安全、
性能或对端业务交付；晚到／重复完成的硬件假设仍需单独验证。工作负载仍须通过
原有随机载荷及对端实际回复门禁。测试故障及旧资格保留，不由新名字或新确认覆盖。

## 有限链路观察

可选 `--link-measurements` 在现有双设备连接／应用门禁中、业务工作负载开始前，
经普通管理角色的真实 `slctl link-measurement` 对两端读取 RSSI 与 PHY，并交换连接角色。
须使用包含该契约的新镜像；准备工具固定 guest helper，启动参数与原始记录必须一致。
门禁关联原 generation／lifetime、真实 DLI 请求及 Complete；RSSI 无效值、固件拒绝、
缺包或不完整场景均不能通过。PHY 八字节仅保留线值，不授 PHY 策略或射频资格。
这些查询不刷新应用租约、协议原期限或负载参数；查询结果与对端业务校验分别验收。

读者：制作实验镜像与运行硬件门禁的集成、测试人员。本页解释 runner 的输入
及匹配约束，**不能据此从零构建可运行 VM**；完整构建操作链仍属唯一计划 DQ3
待交付。不再把输入清单命名为“准备 VM 操作指南”。适用当前未发布 runner；
具体资格按[唯一能力入口](../../project/current-capabilities.md)的准确提交逐项核对。

| 输入 | 内容与校验边界 |
|---|---|
| kernel build | 准确 Linux 源码、配置、工具链和独立输出目录中的镜像；不是宿主已运行的内核 |
| native_module_tree | 与镜像 vermagic/配置匹配、已按实验路径签名的模块依赖树 |
| native_boot_smoke | 成功 scratch-root 启动的 **manifest 文件**，不能传目录或用空 USB 结果代替真实 probe |
| native_service_bundle | 含 manifest 的准确 bundle 目录，记录编译用户态及 guest 工具；不能用文档提交代替编译身份 |
| SDK110 inputs | 显式选择已知 E/U 板卡对应主固件、两份校准及板级输入，记录 hash；不公开分发。不由 USB VID/PID 或运行期 HCC 查询推导冷 ROM 自动选择资格 |
| physical USB selection | 明确物理端口、VID/PID 与当前枚举；device number 可变，不是稳定身份 |
| execution tools | Host runner/独立核对器与 guest 程序身份分别记录，不假定等于编译服务提交 |
| captures | 两端 USB/HCC、完整 console、capture-stats、进程退出与实际对端应用随机校验回复 |

`tools/ws73_vm_native_root.py` 是内部 staging 模块，不是部署 CLI。
三个 native 输入共同描述实验 VM；它们不自动授予 Ready、连接或安全资格。
Installed、transport 可用和每设备 Ready 分开观察。内核及所有真实 WS73 操作保持
VM-only，主机不安装实验内核、驱动或服务。普通应用业务权限与环境管理/捕获权限分开。

该 VM profile 固定使用 `init=/init`。打包器在创建磁盘或调用 `mkfs.btrfs` 前，要求
staged root 的 `init` 是非空、具有执行位的普通文件；缺失、目录、符号链接和仅有读取
权限均拒绝。覆盖 helper 时须保留目标执行模式，字节 hash 相同不能证明模式正确。
此检查只保证入口的基本文件条件，不验证解释器、动态链接器、镜像可启动性或设备资格；
仍须保留打包错误并独立执行无 USB 启动检查，不把入口修复计作 WS73 故障恢复。

外部 C SDK 小程序的 `CC` 为单个编译器可执行文件，默认 `cc`；不接受隐式 shell
参数或缺失时回退。调用保留符号链接名称，使 `cc → ccache` 等按名称分发的入口
能正确工作。manifest 分别记录实际调用路径／参数、解析后入口文件的 hash 和该
调用返回的编译器版本；wrapper 的 hash 不是整条底层工具链已被认证的证明。

## 固件证据范围是必选输入

新物理 `run` 必须显式指定 `--firmware-evidence runtime-observation|rom-upload`。
缺失时在读取 prepared、加载内核辅助工具或启动 VM 前拒绝；旧封存工具和历史记录
保持原身份，不自动获得新资格。新 prepared 冻结对应核对器及输入契约版本。

`runtime-observation` 允许独立记录运行态功能，但不承诺本轮装载了 staged SDK110
字节。`rom-upload` 当前用于独立双设备普通 connection/socket 门禁，要求每个
观察到的 Runtime 都有同一 guest 拓扑路径上紧邻的 ROM 上传见证。它复用成功 USB
提交/完成、三份镜像字节核对及 HCC 型号核对；不按枚举编号大小或设备数量配对。
完整 kernel USB 路径日志、pcap 和固定 guest-slot 映射必须属于同一封存 VM。

最终 manifest 的 `firmware_evidence` 分别保存每次 Runtime 的来源、实际镜像输入、
模型及限定结果。缺上传为 `MISSING`，捕获/长度/归属不确定为 `UNPROVED`；丢包、
不匹配、空集合或缺少一个 controller 都不能得到完整上传通过。后续运行态重枚举
不继承前次上传资格；因此 QMP 重接即使业务成功，严格上传门禁仍可能失败。
`behavior_status_before_firmware_gate` 保留此前已核对的业务结果，不覆盖整轮失败。
保存记录的资格核对者还须从封存调用命令/产物绑定预期 mode，不能用记录自身的
mode 作为外部预期。生产终态检查使用原始参数；删除或降级新契约不能绕过该预期。
没有新契约的历史记录仅按旧范围解析，不自动获得上传资格。

该门禁只证明所观察到的成功 USB ROM 输入，不认证执行固件或真实冷断电；两项
标志持续为 false。不通过复位、切电、重新命名或放宽断言制造缺失见证。混合输入
须独立核对逐叶五文件闭包与新 HCC；暖态业务、实际上传和完整混合启动分别判定，
不互授资格。资源白名单与型号输入检查始终独立强制。

## 型号、地址和配置来源

HCC 型号／总线回复与 DLI 无线地址是不同证据。相同 VID/PID、固件输入通过或
地址查询成功，都不证明每板地址唯一，也不构成芯片身份认证。RAM 固件加载不
表示已经完成持久地址配置；主固件和两份校准的来源应与地址来源分开记录。

真实设备对开始发现／建链前必须核对双方地址；重复值保留为原失败，不自动生成
替代地址来取得通过。另行明确授权的临时运行期配置可使用现有类型化 Native
`--runtime-addresses` 门禁，须在 daemon／广播／建链前完成真实0405 Complete和0406
读回，按每设备核对同行未改变。它不证明出厂唯一或正式分配，不能改写原重复地址失败。
此门禁只接受本线程分配的两只 E 端口各一次（见下方资源边界），允许显式交换顺序；地址参数按所列端口顺序
对应 guest slot，不能按枚举编号或读回结果重新选配。交换顺序时，调用者须同时
排列每物理端口的预定地址，并将保存的原地址按物理端口映射后恢复。型号／固件、
占用、0405 Complete、0406 读回和同行隔离检查仍分别执行；排列支持本身不授予实机资格。
初始化常量、静态数据流、运行期读回和实际配置生效分别
标注：在固件中找到常量不证明动态分支已执行，固件读回零值也不证明物理 eFuse
为空。未查明时保留原始回复及准确镜像／板级输入身份，不诊断板卡损坏。

地址配置需单独核对规范、权限、原期限、真实 Complete、读回和生命周期条件；
本输入契约不开放 raw 写或eFuse／Flash／NV写；当前未发布的运行期入口及其
Setup／Diagnostic／原File／每注册一次限制见[接口契约](interfaces.md)。

### 运行期地址原值凭据

当前 guest 在任一 `0x0405` 前，将两端真实 `0x0406` 查询、原注册／HCC 观察、
请求地址和工具身份独立保存为 `runtime-address/originals.json`。文件以排他创建
方式写入，设为只读并同步文件及目录；失败或已有同名文件时停止，不覆盖旧凭据。
`run.json` 保留该文件的 hash，每次设置前重新核对。主机验收要求原凭据与实际
查询及捕获一致；缺失、篡改或核对期间变化均拒绝。旧 guest helper 在启动前按
源码 hash 拒绝；历史报告仍只能由其原工具按原范围重放。

子进程超时保存已有 stdout／stderr 及原始字节，物理结果记为 `unknown`；
不能据调用者退出推断控制器没有收到设置命令。凭据、文件权限和 hash 仅用于
保存及核对证据，不是身份认证、地址恢复或通信通过。guest／host 文件系统的
掉电持久性尚需实测；固定依赖的恢复入口和源码漂移时的清理仍待接通。
现有恢复须另有真实设置／读回及同行不变证据，不能
仅凭原值文件宣布已还原，也不因此放宽现有源码身份检查。

只读证据入口 `ws73_address_cleanup.inspect_setup()` 可单独检查失败 setup：调用者
提供先前固定的工具身份、临时地址及有序 guest／物理叶端口／序列号映射，函数复用
现有原值凭据和 USB decoder。它要求完整进度记录、零丢包的已停止捕获、双方原查询，
并逐一核对每个设置尝试与实际 `0x0405`、成功 Complete、`0x0406` 读回及同行前后
不变。`setters[]` 尚未追加或之后 CLI 清理报错，不会抹去已经证实的物理设置；
未知超时、缺终态、额外／重复 Complete、捕获或凭据缺失均拒绝。原 setup 状态和
全部输入保持不变。USB 提交至读回的有限检查不证明更早的软件准入原期限。

返回 `ORIGINALS_VALIDATED_CLEANUP_ELIGIBLE_NOT_RESTORED` 仅表示上述证据准入，
不启动恢复、不发送命令，也不表示已还原。尚需由受控维护入口核验固定执行依赖、
等待自己启动的 VM 退出、重新检查现行端口授权和占用，再独立验证实际恢复。
新 VM／新 generation 不能替代固件排空屏障；未知设置结果尚不允许据此再次设置。
这项文件及合成捕获测试不授予实机恢复、非人工自然恢复或生产身份资格。

## 冻结 daemon 配置

daemon 配置由现有 `prepare --native-discovery-config` 路径交给准确的 staged
`slkd` 校验，并冻结整份配置 hash 与策略预期。SSAP 安全等级等非无线字段的变化
也需要创建新的 prepared artifact、重新冻结这些凭据；已封存镜像保持原样。
guest 启动时核对配置与凭据，缺失或不一致即拒绝。准备校验通过仅证明该配置被
对应 daemon 接受；实际安全机制、固件兼容和对端业务仍需各自实机门禁。

## 当前共享硬件边界

本线程的 [资源配置](../../project/lab-resource-policy.json)固定允许 U
`1-1.1.1`、`1-1.1.2` 与 E `1-2.1.1`、`1-2.1.2`；两 hub 的 `.3/.4`
是另一线程专用。端口不是外壳编号，声明型号还需新 VM 的实际 HCC 核对。
新 runner 不接受任选设备、旧端口回退或枚举编号。每次 QMP 附加（包括重枚举）
重查端口、序列 hash、上游 hub、PCI 归属及占用；变化即停止，不能强制解绑。
每端口共享 lease、独立 VM 运行锁和目录用于协调，不防御不合作的特权操作者；
root fd 可能不可见，不能把只读进程快照称作绝对独占证明。

启动入口还要求可只读访问本机 libvirt system URI（`virsh`）。它在自己的 QEMU
启动前、取得端口 lease 后，在共同五秒预算内读取当前运行域 XML；不读取 inactive
配置来断言占用。当前 bus/device 只用于将分配反查为拓扑，不能取代序列号 pin。
本线程任一叶子、其上级 hub 或共享 PCI 被分配，或 WS73 选择器无法解析时，必须
停止协调。明确其他线程的叶子允许并行；查询缺失、失败、超时、损坏或超限也停止，
不会自动解绑或停止已有 VM。新 run manifest 的 `physical_resource_allocation`
保存此次观察与 XML hash，仍不是型号、业务、恢复或绝对独占资格。

`prepare --board-model U|E` 要求对应 SDK110 的主固件与两份校准全部 hash 一致；
新物理执行要求此 provenance 和新 guest 的 HCC 检查；准备镜像也须明确选择型号，
不能隐式选择 U。纯 support 不操作物理设备，不授型号或固件资格。
新 prepared/run 必须位于该配置的线程独立运行根；旧封存根保持原样。
每设备输入迁移后，驱动不读取全局默认镜像。旧单型号准备契约仍拒绝混合选择；
显式逐叶契约按下节核对各型号。无法证明逐设备来源的 runtime-only 接管继续拒绝。
源码接通不代表新产物或混合冷启动已实测；准确状态见唯一[资格入口](../../project/current-capabilities.md)。
不得修改旧 manifest 来绕过检查。
板级 `bsle_custom.bin`／`pm_config.bin` 仍须显式提供并记录，型号匹配不证明板级资格。

### 每设备 OS 输入配置

新 `ws73_native_service_bundle.py` 要求 `--board-model U|E`，输入暂存于
`usr/share/sparklink/firmware-inputs/<model>/`，不作为驱动默认搜索路径。准备工具核对
bundle 与明确的五份输入后，生成独立 USB2 端口目录及 `ws73-firmware-profiles.json`，
消费暂存文件；新镜像不保留旧全局镜像回退。旧 bundle 须用原版本工具重放，不能
将旧 manifest 改成新格式继续使用。

| 项目 | 新输入契约 |
| --- | --- |
| 驱动请求目录 | `sparklink/ws73/by-path/<controller>-usb2-<route>/`，相对 firmware loader 根；不是 USB device number 或 VID/PID。 |
| 实验 guest 布局 | 显式 xHCI PCI `0000:00:02.0`、USB2 直接端口 1–4；逐叶 QMP 附加仍须通过独立白名单及占用检查。 |
| `profile.bin` | 恰好 172 字节：8 字节 `WS73P001`，型号 U=0／E=2，USB=0，两字节保留零，再依次为下列五文件的完整 SHA256 原始32字节。 |
| 五文件顺序 | `ws73.bin`、`wifi_cali.bin`、`btc_cali.bin`、`bsle_custom.bin`、`pm_config.bin`；前三者保留原64字节小写 ASCII payload SHA 头。配置分别为140／4字节。 |
| 冷 ROM 下载 | 三个启动文件须全部校验成功才开始原 ROM 操作；同端口 ROM→运行期仅接受相同输入闭包。 |
| 暖态初始化 | 校验 profile 及两份运行配置，再以新 HCC 查询核对所选型号／USB；不伪造当次启动镜像上传。 |
| sysfs `firmware_profile` | 只观察 OS 输入目录、预期型号和本次文件校验位；`execution_attested=0`。不能代替 HCC、Native Ready、实际上传或执行镜像认证。 |

文件校验位属于本次 USB 接口实例。ROM 重枚举后，新的运行期实例可以仍只显示
`filesystem_checked=18`（两份运行配置）；不能据此判断此前未下载或已下载三镜像。
实际上传须另核对成功 OUT 字节、QUIT、同物理端口的新 USB 实例与后续 HCC／DLI
时间线。暖态首次接管和随后一次受控重载分别记录，不继承彼此的上传资格。

未知型号、SDIO／UART、短／非法配置、缺文件、hash 不符或待重枚举闭包变化均拒绝；
没有全局 U 回退。profile 不是冷 ROM 型号自动识别，也不认证芯片、地址或固件。
宿主不安装实验驱动；该布局只说明明确配置如何进入现有 VM 原生路径。
开发准备 API `ws73_lab_resources.prepare_device_inputs(root, selections)` 可以为新私有
root 明确列出每个物理叶子、型号、SDK110目录和板级输入目录，复用同一五文件
provisioner。列表顺序就是固定 guest USB2 端口顺序；不扫描挑选或按 device number
映射。`device_input_contract_version=1` 的 `device_inputs.entries` 同时保留逐叶固件和
板级 provenance，拒绝并存的单型号 `explicit_firmware`／`board_configuration` 别名。
该表示的板级和上传观察契约版本为2，必须完整保留端口、route、型号及文件身份；
单型号旧表示仍为1。每次附加重新检查实际准备目录，缺叶、交换顺序、错误型号、
残留全局文件或任一五文件变化均拒绝。标准 `prepare --from-prepared CARRIER
--device-inputs PLAN --output NEW` 复用此 API 和明确封存载体；不重新编译内核或 Rust。
`PLAN` 是精确 `{ "version": 1, "entries": [...] }`，每项只包含 `host_port`、`model`、
`firmware_dir`、`board_dir`；相对目录以计划文件所在目录为基准，列表顺序为 guest route。
不能并存 `--board-model`、全局固件／配置、构建或额外 staging 参数。载体须保留完整
ROM 输入、明确的 `compiled_userspace_identity`、原 manifest、磁盘和对应私有 root。
准备器校验原文件闭包、QEMU data、mode／symlink快照，复制到新目录，替换已验证的
旧输入目录，暂存当前共享工具再封存；不原地修改旧载体。原编译身份、父载体与新
工具提交／hash分别保留。失败写为FAIL，新目录不得作为PREPARED使用；不覆盖重试。
这不是另一套启动／Host，也不代表新载体已取得混合实机、冷启动或自动选型资格。

新 native bundle 要求同目录的 `ws73-board-config.json`、可取得的原始 INI 和当前
导出器。准备入口通过生产导出器重放编码，拒绝旧工具哈希、短文件、symlink、参数或
源文件不一致。显式板型的新 prepared/run 记录 `board_configuration_contract_version=1`，
将输入 proof 绑定所选 U/E；实际 Root 的两个目录均须匹配，并在每次 QMP 叶子接入前
复查。该 proof 的范围固定为输入 provenance，不是板级、镜像运行或 RF 资格。
历史捕获按原契约解码，不能通过给旧 manifest 补字段取得新资格。
新 guest 先记录实际 `HCC_GET_CHIP_TYPE`，与显式型号和 USB 总线不符则失败。
这不是冷 ROM 自动选择，也不是芯片认证。历史三设备 SDK111 reference 诊断
无法满足此分配下同型号/SDK110约束，须等待明确适配；原代码及证据保留。

同一运行期地址步骤也可用于已有的独立 Managed Grant 回归：显式选择
`--setup-release-verify --managed-connected-case close --managed-channel-grant`，
这条模式不与 `--qmp-hotplug`、普通 connection/socket 或 benchmark 模式混用。
runner 内部仍逐设备经受保护的 QMP 接入；该选项区别不授予其他端口权限。
启动顺序必须是：原有 untouched Setup／lease 检查 → 共享真实地址配置及读回 →
connected File／Grant 门禁 → 捕获封存及独立核对。此模式在 daemon 前结束；
成功配置地址不能替代撤权、实际业务、credit、原期限或清理结果。原 Native
connected 广播已经显式使用 negotiable-T 参数，不添加第二套广播实现或改变默认值。

禁止整 hub／主控制器透传、复位、切电；单口恢复若无法证明无连带影响先协调。
现有构建 wrapper 与物理 runner 通过共享 build lock 和 VM lease 握手：合计
最多12路，有任一真实 VM 最多8路；旧工具不持该锁时须另行核对，不能各开12路。
设备冲突不抢占，构建不因提速被中断。新拓扑、E和混合结果分别授予准确 artifact，
旧 PASS 和人工/受控操作不能充当新资格或自然恢复。

## 运行终态与退出凭据

完整 runner 记录必须有整数 `qemu_exit=0` 和 `supervisor_exit=0`。缺失、信号退出、
非零、布尔值、浮点或字符串均不能按完成 PASS 读取；这些要求适用于所有模式。
仅 `_run` 计算尚未写出的 supervisor 结果时，内部显式 pending 阶段可暂缺后者，
它仍要求实际 QEMU 成功退出，也不能忽略已经存在的失败。pending 不是 CLI 选项，
在 JSON 添加同名字段不能把未终结记录变成完成记录。

旧记录及冻结解析器保留原身份；不能给缺失的历史凭据补零来取得当前资格。
退出检查不替代用例、原件、scope、两端载荷和抓包校验。报告工具的新源码若只重放
旧原件，应标为离线校验，不能把新工具提交写成原 VM 的执行身份。

运行期地址核对只在共用捕获完成解码和计数核对后附加证据，不能生成其他专用
门禁的成功状态或跳过连接／业务核对。所解析记录的原字节与最终 hash 必须一致，
verifier pin 不符即拒绝。早期初始化故障与 daemon／fd 死亡等独立模式仍须经过
相同的清理、固件范围及 QEMU／supervisor 终态流程，并保留各自专用业务及范围摘要；
状态标签不能代替这些摘要。旧失败不因核对器修复而改写，新工具 artifact 须另验。

PB 分片门禁按每个实际发送 controller 的 DLI buffer 上限核对完整 DTAP PDU，
包含通道头；不能固定用 249／250 应用字节分界推断所有型号均分片。
`long_pdu_acceptance` 只表示全部相关业务 TX 确实分片且通过顺序／长度核对；
较大应用消息在 E 上单包通过时不授予该分片资格。NOCP 数量与对端应用仍另核对，
旧失败原件不因核对器修复升级。

运行期地址的 File 生命周期门禁在 daemon 启动前执行：只经现有 Native UAPI，
保留真实成功 IN81 回复后再触发 release、最后 fd 关闭、dup 或原始期限。
未核实设置的既有策略是隔离 controller，不能用 Free 或 Ready 代替未知清理；
迟到回复不得重新授予身份或改变原超时结果。同行实际 Ready 和扫描启停只能
证明控制隔离，不能描述为同行应用业务交付、引用排空或非人工恢复。
QMP 已释放不等于 guest 已收到；最终状态检查前须由独立 fd 的既有 Native seam
trace 确认当前 generation 的真实 RX，不能用固定 sleep 代替。该 ingress 观察仍不
等于 callback／worker 已排空，后者另有引用和退出门禁。
探针在终态断言前保存同一次 snapshot ioctl 的原始字节及墙钟／单调时钟区间；
即使断言失败，收集器也必须保留这组操作数。之后的新查询不能替换原点快照。
请求结果、Host 状态发布和 jiffies 期限分别核对，墙钟区间本身不证明精确的
内核到期时点；不得为得到通过而改断言、加固定等待或延长原始预算。
采用统一到期实现的内核在 Runtime→Host 锁内采样一次 jiffies，先处理该时点已
到期的物理义务／既有故障，再终结作者账本；worker、诊断准入和结果查询共用它。
快照查询仍只观察。排队但未选择的普通查询可以作者超时而不制造硬件故障；
已开始的义务不得被取消或超时凭空退款。实现状态与准确新 artifact 的实机资格
分别记录，源码或离线函数测试不能替代原期限、迟到 RX 及同行业务回归。
该开发探针及原始 USB／QMP 核对的实机状态由准确资格记录单独说明。

## Down 期限失败后的被动观察

`--connection-down-failure-observe-seconds` 仅用于现有真实双设备 Native VM 的
`--qmp-hotplug --connection-verify --channel-socket-verify` 普通门禁。
取值为0（默认关闭）、6或12秒。除下述明确组合外，不能叠加其他故障、Agent或生命周期子门禁。
新选项需要重新封存包含匹配 Host／guest 工具的 prepared root；旧镜像不会自动获得。

另一明确组合为 `--ssap-subscription-verify --ssap-subscription-inflight-release-verify`
与 `--security-agent numeric-approve`。它仍要求真实双设备、连接和 socket 门禁；
续租、满队列、进程退出及其他选择器不能混入。Host 与 guest 都重新校验同一
订阅场景，相关布尔值必须为真布尔类型；新增组合只改变失败后是否保留观察窗口，
不改变保护等级、在途释放断言、正常流量或原期限。实际执行资格单独记录。

原两端 canonical Down 共同5秒判定保持不变。只有它失败后，工具先保存原FAIL，
再在清理前休眠并继续已有抓包，期间不发起测试控制请求；随后仍抛出原失败。
失败记录的 `down_property_observation.passive_failure_capture` 含实际起止时刻、
请求时长、前后命令数及完成／中断状态。中断不是完整观察，迟到Down不补为原期限内成功。
没有触发原失败时，该选项不增加等待；一次成功也不能覆盖旧失败或证明根因消失。

工具自身没有发命令不等于总线静默；必须核对两端原始USB，排除daemon、内核及
其他控制流量的混杂。被动窗口、后续清理和实际Down分别标时，不能将清理触发的
流量解释为自然事件。此观察不授RF时延、自动恢复或多URB优化资格，实机范围按
准确 artifact 的[能力记录](../../project/current-capabilities.md)核对。

## 原始断链时序的离线观察

`ws73_connection_control.observe_down_timing()` 是内部只读核对函数，复用原捕获
解码器及 OUT／Status 关联。输入须有两端目标的有效 capture span、原 Create／
Disconnect 命令窗口及分别匹配对端地址和 handle 的真实 Up；后续 Up／handle 复用、
重复 Down、身份不符或原五秒预算被改写均拒绝。缺失 Down 只记作该区间未观察到，
不能升级为静默、成功或设备故障证明。

输出分别记录设备／generation、物理连接角色、请求 reason、真实 Down reason、
相对 USB Disconnect 与原观察起点的时间，以及原始状态／错误。阶段编号不是物理
连接角色；交换两只设备后，发起方可能仍是同一物理角色。控制器完成、两端 Down、
canonical 属性收敛和对端应用交付分别判断，迟到事件不补过原门禁。

观察始终返回 `gate_awarded=false`。其时间线属于原 guest 的捕获／wall clock，
不提供纯 RF 或精确单向时延；raw supervision 字段不自动换算成实际无线参数或根因。
重放旧捕获属于离线证据，不授新源码、固件、硬件或恢复资格。

## 公共 C/Python 客户端的专用门禁

`run --qmp-hotplug --connection-verify --connection-advertising negotiable-t --application-client-verify` 选择独立的
真实双设备 SDK 用例，要求完整 native VM 输入，不能与 socket benchmark、注入、
Agent 或其他生命周期选择器组合。QMP 拔插仅是 guest 控制对照，不是自然恢复。
本段描述 runner 输入，新增产物是否通过仍以准确资格记录为准。
`negotiable-t` 与既有 SDK110 封存建链条件一致；`fixed-t` 是独立对照，已有 Ready/
发现后连接超时失败，不能当作该已验证条件。广播参数和实际生效身份仍逐项核对。

共享 discovery 的 `--application-discovery-verify` 同样要求显式
`--connection-advertising negotiable-t` 才能执行其连接／业务保持门禁。早期 Fixed-T
尝试的失败仍是原条件下的真实失败；不能说成相同 Negotiable-T 条件的回归退化。
`--application-discovery-case release|owner-loss` 只选择该门禁内的退出方式。
后者仅SIGKILL本VM监督器启动的固定普通reader，不发管理STOP；需同一物理START、
首名消失后同行新标识、最后消失后的真实STOP/Complete及五秒清理期限证据。
该选项不表示TTL、管理撤销、完整生命周期或自然恢复已经验收。
`NativeConnectionResult` 的 `flags` 位1／2／4分别表示 Status／Outcome／handle
存在；Status0不代表连接完成。成功还要求真正的终态和对应 Outcome／handle，
USB提交、OUT完成及控制器Status不是这些字段的替代。

专用测试目录内的两个小应用调用公共 Client：固定连接对象申请 fd，dup 后关闭
原 fd 与 Client，等待双方原期限内的 start 屏障，验证一次随机请求及不同的随机
回复，最后关闭后确认同 lifetime 重绑拒绝。它们只做外部 SDK 消费，不提供另一个
Host、协议 codec 或负载循环；持续负载/计时仍由 slktest 完成。
两种语言交换发起/应答和连接角色；原发现、连接、长度及其他生命周期门禁另验。

原始输出、UID/GID/组/全部能力、执行程序/库 hash、两端 USB/HCC/ACB 证据必须
保留。缺一端实际校验或 capture 不能通过。linger 的有限清理等待不等于对端应用
收到，只有实际回复校验可证明该次交付；普通 UID 且无 capability 也不自动证明
apps-only 权限部署或所有撤权组合。未支持的模式、高阶 SDK 与恢复仍单列开放。

输入不存在、hash/源码不符、模块不匹配、启动失败或缺必要记录时停止资格传播，
保存原失败并使用新输出目录。人工拔插、hub 切电、QMP 操作只记录干预；不算自然恢复。
历史环境材料在[环境原文](../../project/reference/environment/ws73-target-environment.md)，
[原生主机安装历史](../../history/environment/ws73-native-lab.md)不属于允许执行路径。

当前缺口是“如何生成全部前置产物”的完整、干净环境重放指南；不能用本表或 --help
宣称该指南已经完成。首次业务实验也必须先由集成人员提供匹配且已经建链的 VM。

## 正式安全 CLI 子门禁输入

`ws73_target.py run --security-agent cli-approve|cli-reject` 选择正式CLI子门禁；准确编译/工具和限定结果见[当前资格](../../project/current-capabilities.md)。
它要求独立双设备 connection/socket 模式、当前 prepared 工具和已封存的版本化 CLI artifact，
实际路径及 SHA-256 必须与 prepared manifest 相符；`/bin/slctl` 软链解析后指向
`/usr/libexec/opensparklink/native-lab/<源码前缀>/slctl`，不能写死软链文本。
不能复用不含正式 Agent/请求入口的旧镜像。`cli-approve`/`cli-reject` 只存在于
VM 测试协调器；协调器读取真实 CLI 提示后通过 stdin 给出显式测试回答，正式
CLI 本身没有自动批准功能。每端分别启动 Agent 和原作者请求，共四个实际进程。

原 stdout/stderr、退出码、原凭据、路径、提示、回答、期限与终态均保留；监督器
异常、缺失/截断记录、丢失对端 RX 或安装事件不能通过。既有独立 USB/relay/
安装和对端业务校验继续必需；无 MITM/可信身份/Bond/自然恢复资格。
原六种测试专用 Agent 模式保持单独范围，不将新 CLI 模式当作它们的重放。

## 动态通道门禁输入

固定通道的 `--channel-socket-close-prefix` 是独立门禁：须显式选择一条2042字节
消息，保留首个USB提交、最后fd关闭／进程退出与末片提交的顺序，验证对端完整
数据及未开始队列不再提交。随后调用同一SSAP操作协调器，在另一SMTC上完成
真实读写；关闭前的业务或本地缓存不能替代。前缀校验、SSAP调用和其错误传播
均为完整门禁的一部分，缺少后续调用不能将前半段改记通过。
保存的最终报告还必须保留请求对应的连接、对象与通道证明；仅有成功标签和
进程退出码不够。prefix-close 明确计为对端完整交付，不计发送端已收到回复；
原始捕获重放负责校验实际时序和数据，最终摘要检查不能替代该重放。

`--dynamic-channel-verify` 要求独立 connection/socket VM 门禁，保留普通固定通道
回归；在同一真实 Session 上验证两动态通道、不对称 TCID 与 A关闭/B继续业务。
不能与四设备模式、安全 Agent、prefix-close 或固定通道 burst 特殊模式混用。

`--dynamic-channel-long-bytes 249|250|253|254|255|1024|2042` 显式扩展该门禁：
版本2记录保留 A/B，再建立第三动态通道 C（4轮）；其MTU等于所选应用长度、
MPS为长度加5。超过254字节的完整PDU须取得两端实际PB分片及对端应用完整校验回复；
249字节SDU对应完整PDU254，TX须为未分片，RX允许固件合法重分片。
在C仍存续时，发起超过本物理lifetime四槽预算的全新端点，要求ENOSPC且未暂存；
随后C仍完成实际业务。受控暂停仅限VM应用进程，原5秒预算与业务10秒期限不放宽。
这验证有限预算拒绝与隔离，不表示槽位已回收、安全TCID复用或完整credit证明。

编译服务、guest工具、Host校验器及输入/捕获身份分别记录。原版本1的48次子门禁
保持原报告和工具身份；版本2的56次结果、长包尺寸与槽位拒绝必须另外验收。
仅有参数、离线夹具或旧捕获重验不能授予新实机资格。


在线应用输出使用有界子进程管道，stdout/stderr各上限128KiB，同时逐字节保存
原文件。缺失EOF、无目标标记、预算超限、编码错误、短写或原文件被替换/截断
均失败；记录采集操作、errno和异常栈，不以丢弃输出继续取得PASS。
早期249字节整轮的ENODATA失败保持历史失败，底层I/O原因未查明；新的采集
方式须独立重跑，不能用“此前已收发”改判该轮通过。

## 动态通道 burst／credit 扩展

`--dynamic-channel-burst` 必须同时指定 `--dynamic-channel-verify` 与
`--dynamic-channel-long-bytes 2042`。版本3保留 A/B 工作量及四槽拒绝；C改为
16条2042字节突发消息，交换物理连接角色。历史镜像应用使用 `dynamic-burst`；当前等价入口为 `slktest channel ping --check --exercise burst`，复用既有
普通socket burst收发与 `query_tx_status`，对端仍使用 `dynamic-peer`。

门禁要求真实EAGAIN、poll撤下可写及恢复准入、源端新增credit池满拒绝、USB提交／
NOCP后恢复提交／最终排空，以及所有对端随机载荷校验回复。软件队列与控制器
credit分开验证，完整PDU2047与ACB254保持独立。NOCP计数匹配不证明固件完成
真值、重复／迟到或handle复用屏障；不授予可靠模式或自然恢复资格。

C输出包含32条完整十六进制收发记录，版本3的每stdout/stderr预算明确为256KiB，
其他版本仍128KiB。采集器的短写／EOF／身份／预算／编码失败规则不变。
离线夹具使用生产receipt与credit观察函数，但USB形状和调度为fixture，
不属于真实内核并发或空口资格。当前实现需在准确新编译artifact上另行VM实测。

## 同内核的撤权、断链、原期限与同行业务

开发入口 `--managed-channel-sibling-business` 只接受独立的
`--setup-release-verify --managed-connected-case close --managed-connected-index 0
--managed-channel-grant --managed-channel-revoke-prefix` 组合。要求新准备清单的
`channel_sibling_business_contract_version=4`、当前可执行 init 及一致的 helper hash。
它使用本线程四个明确叶端口；不与 QMP hotplug 测试、daemon、benchmark、安全、
queued-discard 或 Session 追踪组合。其中 case 必须显式选择 release、close 或 dup；
release 还可单独选择 `--managed-channel-link-down` 或 `--managed-channel-deadline`。
两种 transition 互斥，也不能与 close／dup 混用；上例 index 也可显式设为 `1`，其他 case／index 明确拒绝。
contract4 将 victim index 从请求、唯一 `ws73.connected_index=0|1` boot token、
`ws73.channel_sibling_contract=4`、guest argv、原始 `sibling_request` 与
`sibling_business.victim_index` 绑定到最终判定；缺失、重复或错配拒绝。
最终摘要同时保留原 owner 的 controller／generation／lifetime／handle 与 guest USB，
并核对实际 full-pool `TxStatus`、READ_LOCAL_BUFFER 双向 USB 记录、guest／HCC 映射、
受控 hold index 和启动时 host 端口；仅把 role0 标签改为 role1 不得通过。
受控组 index 选择 Create caller／受控 fd；独立 2／3 组自身的 Create index 仍为 0，
不能随 victim 改成 1。端口必须按受控组两端、独立组两端的显式顺序传入。

这是同一实验内核中、daemon 启动前的 Native 机制门禁。0／1 为原受控组，2／3 为
独立业务组；controller ID 来自明确选择的真实快照，不能使用组内端点号或枚举顺序替代。
两组复用原 Native 管理路径、唯一 Session、Grant／credit／Ticket 及同一套普通用户
socket worker 和载荷校验，不新增 Host 或协议 Engine。额外组仍逐叶核对 SDK110 输入、
HCC 型号／总线和实际地址；需要 E 临时地址时仍须保存、设置、读回及恢复。

dup 还要求第一次关闭管理 fd 后、最终关闭前，原 owner 保持、原物理连接未断，独立组实际双向回复；
最后一次关闭仍须命中原受控屏障，不能把第一次 close 当成撤权。release／close 各六次同行往返，
dup 八次，逐条关联原 worker、载荷和双端 USB。旧 contract1 的 R143 和 contract2 的 R144
以及 contract3 的历史记录保留原源码及限定资格；不能重标为 contract4。
新 contract4 的两种 victim 角色实现与准确产物实测分别记录，不能由扩展入口推导通过。

Down 沿用两秒真实 IN81 屏障，在原阻塞见证后、真实 Disconnect 前完成同行往返；
双端 Down 和旧 fd 拒绝后再完成同行往返，共六次。原租约仍保持，不能称为 Managed 撤权。
原期限使用独立八秒 fixture，PDU 原期限仍为五秒；在实际超时前、超时后但释放 held IN 前、
实际释放后各做双向同行业务，加上建立后的基线共八次。释放后的阶段还须在主连接清理前完成。
每个阶段与 guest 因果时间窗、原始回复、USB 两端证据绑定；过晚结果或自动有界释放一律失败，
不延长协议期限。这些有限阶段不等于连续五秒满负载隔离、NOCP 硬件准确性或完整 drain 证明。

门禁要求实际持有回复期间、以及目标 Managed 撤权后，独立组分别完成双向随机载荷
校验回复，保留原 fd／lease／generation／lifetime 和原物理连接；复用双端 USB 校验。
原未完成 PDU、两秒有界 IN81 暂留、阻塞 syscall、撤权后拒绝及不新增提交的断言保持。
控制器 Complete、NOCP 或 Root 日志不能代替对端应用回复。额外组最后也须以实际
Managed 清理收敛，不从“关闭了 Python 对象”推导 Free。

入口、离线 fixture 和机制实机资格分别登记。此门禁不等同实际 slkd／SDK 的管理策略、
每应用独立撤权、完整 fd／callback 排空、NOCP 真值、公平性或自然恢复资格；后续
release／最后管理 fd／dup／Down／原期限矩阵保持，不能因单个组合通过关闭整项。

### typed Disconnect 的提交边界

typed Disconnect 成功完成队列及作者请求准入后，内核在原 Host 锁内将目标
generation／lifetime 标为 `Closing`；该锁也保护 Ticket 的实际 USB 提交。
参数、身份或队列准入失败不关闭连接。`Closing` 通过现有 Session／Grant／Ticket
路径拒绝该 lifetime 的新业务提交，不撤销其他连接或 controller 的权限。

准入后的作者取消、控制器 Status 拒绝或原期限到期不会重新开放该 lifetime；
后续显式 Disconnect 仍可清理物理连接。物理 snapshot 在真实 Down 前仍可为 Up，
本地关闭不制造 Down 或成功结果。在 controller 和管理租约仍有效时，旧 fd 在
`Closing` 阶段返回 `ENOTCONN`，实际 Down 后返回 `ESTALE`；设备故障及租约撤权
仍按各自原错误处理。真正的新 lifetime 独立建立权限，不复活旧 fd。

已实际提交的 USB、命令回复及 data credit 债务仍需结清；取消和关闭不退款，
NOCP 仍沿原记账路径处理。本段描述源码契约，不能证明 NOCP 硬件准确性、完整
callback 排空或自然恢复。准确 artifact 的实机范围见[当前资格](../../project/current-capabilities.md)，
单个 Down 组合通过不代表完整生命周期回归闭合。

## 受控原期限与生产转换序列输入

新prepare记录`managed_prefix_geometry_contract_version=1`，对应运行凭据
`ws73.prefix_geometry=1`。当前受控前缀门禁在接管USB前拒绝缺少该版本的旧root；
历史报告仍保留原源码及固定条件，不能改字段升级资格。

门禁先通过原普通进程查询同一controller／generation／lifetime的空闲发送池，
有限0.5秒观察要求队列、busy、active PDU和旧debt均清空。ACB片长须为66..2046、
容量为2..32；这是有界夹具范围，超出时明确拒绝，不截断实际buffer声明。
当整个池足以提交2047字节PDU时，先由真实对端校验capacity−1条不同的61字节单向
消息，实际Native快照须显示相同未支付debt且没有active PDU，再以长PDU占用最后
一个slot。否则保留原来的多片耗尽路径。Direct Down仍要求预填充。

空池快照、原始0402回复、预填充的应用收据及双端包、满池快照与未完成offset必须
一致；任何完整PDU、额外源端包、缺失对端校验、提前NOCP或错误归还数量均拒绝。
0402可来自同一USB实例先前的共享Native初始化，不能人为把时间下界设为connected
子门禁开始后。片长不是RF包长、SSAP MTU或独立NOCP真实性证明。夹具观察、预填充
和下列2／8秒hold不改变生产5秒原期限，也不是正常通信的固定等待或性能优化。
离线输入域检查不授予真实内核并发、固件credit、完整复用或新实机资格。

`--managed-channel-deadline` 需要独立的pre-daemon Managed channel gate、
`--managed-connected-case release`、`--managed-channel-grant` 与
`--managed-channel-revoke-prefix`。原生产期限为5秒；QEMU需有独立8秒的
`usb-host.test-runtime-in-hold-ms` 能力并实际核对。缺属性或数值不符直接失败。
更换QEMU先重做同内核/签名模块的无USB root smoke及prepare，禁止沿用旧binary身份。
受控延迟、QMP与手工操作不属于自然恢复验收。

内核selftests的 `run_native_data.py --output NEW.json` 直接编译生产转换与显式依赖fixture。
固定种子7536913，1024条序列各先产生一项有效物理提交，再运行32个事件；两个controller、
handle0、epoch1/2、lifetime查询1..65、ACB容量5/上限254、8字节测试数据、NOCP count1。
它覆盖顺序组合，不承诺真实锁/USB/worker/VFS/时钟或全部输入域；原期限另由VM验证。
Host fixture仅使用生产 `admits_data`；`controller_status` 的初始化/Ready投影、完整
命令处理、注册查找与Poll唤醒仍为替代依赖。不能据此授予完整Host或初始化失败资格。

`NEW.bin` 与 `NEW.fixture.rs` 保留实际测试程序及生成源码，JSON绑定源码/工具链/hash。
已存在的证据文件拒绝覆盖；测试失败记录FAIL并保留这些输入。配置失败尝试与实际
原子callback拒绝分别计数，accepted-uncertain不能退款。源码变异须产生预期断言和
seed/case/操作轨迹，编译失败不算性质反例；PASS也不证明NOCP固件准确或安全复用。


## 未完成PDU的Down与空闲观测输入

`--managed-channel-link-down` 与上述独立Managed channel gate、release、Grant和
revoke-prefix组合使用普通2秒真实IN暂缓。当前工具要求primed模式：capacity−1条不同
61字节消息由对端真实校验，源端实际TX快照为相同未支付debt、空队列且flags=0；
长PDU先耗尽剩余一份，须观察ACTIVE/BEGUN、未完成offset和完整池debt。收到对端
真实Down后才显式释放原完成。缺前提、限时自动释放或前缀已完整均失败，不能
以guest成功标记覆盖USB核对。单向预备消息不计作往返；历史容量5的四条预备消息
保留原条件，不自动授予不同buffer的新设备资格。

`--managed-channel-idle-observe` 仅适用于独立release/Grant/revoke-prefix门禁，
指定index 0或1；不得和Down、deadline或其他专项模式合并。仅在带scratch标识
的QEMU VM内建立tracefs实例，绝不在宿主启用追踪。实际普通fd状态显示两端
credit、队列和在途PDU排空后，观察原2秒区间；前后仍需真实业务和受控前缀工作
作为正对照。保留trace原件/hash、CPU0/1丢失统计、时钟和过滤器读回。

观察器拒绝区间内任一次sl_work、丢失/截断、错误fd或generation及缺少前后工作。
同口径旧轮询镜像用于预期拒绝负对照，只记录该镜像身份和原FAIL，不授新内核
资格。完整CPU/时延/公平性、调度或USB callback drain证明均不在该观察范围。

## 安装已提交后的 Agent 取消门禁

`--security-agent install-cancel` 是专用 VM 测试入口，要求独立的真实连接和普通
应用通道门禁，以及已审查的安装回复选择器 QEMU。它不是 slctl 的自动批准策略，
不应部署测试用 `native_security_agent_probe` 为常驻 Agent。

与准入前 `cancel` 不同，该模式立即批准两端原请求，在 G 安装命令实际提交后，
由 Host 保留精确 SDK111 成功 Status/Complete 所在的原 IN81 aggregate，再取消
G 原请求并交还原 transfer。匹配以完整 HCC 边界和 role opcode 为准，不能靠第
几个帧或固定等待推定安装时点；同一 aggregate 的其他事件一起延迟，不拆分。
两秒 Host 保留预算与原五秒协商期限分开，不能重设协议期限。

报告要求原作者、request/generation/lifetime、原期限、完整 arm/held/release
握手、原 transfer hash、真实迟到接受事件、不可改写的取消结果、另一端实际
安装成功及同 Session 的随后对端应用校验回复。两个物理连接角色分别执行。
取消的是原操作，不能解释成硬件从未加密、密钥已经擦除、callback 已排空或
handle 可安全复用。完整 release/最后 fd/dup/Down/期限组合仍是独立未完成门禁。
工具实现与离线 synthetic oracle 通过都不授予 WS73 实机或认证/Bond/恢复资格；
准确结果仍只见仓库中的唯一当前资格入口。


## 受保护通道生命周期输入

`--managed-channel-security 1|2` 仅与独立pre-daemon `--managed-connected-case`、
`--managed-channel-grant`、`--managed-channel-revoke-prefix` 使用。1先完成现有无MITM
安装，2先完成现有数字机制；读取同物理Session当前等级/epoch后，首次绑定对应要求
的CUTC。随后执行原release/close/dup，或release模式加实际Down/原期限；不先绑定
普通CUTC再重开，不走另一条业务路径。0保留原普通门禁。

该操作是显式特权机制审批，数据worker仍为普通UID1000/caps0；不是daemon Agent或
人类确认资格。原2秒回复屏障与专用8秒期限屏障分别核验，生产5秒期限不刷新。
完整真实relay/对端RX/安装接受/0011及业务、旧fd、peer lease/Ready/扫描须分别成立。
同行不是另一个存活业务组，原始PDU前缀也不是已交付消息。

未知等级、组合模式不匹配、缺少当前机制、静默普通fd降级、原始deadline不符或
共享checker在运行中变化均失败。数字、无MITM及每个端点/生命周期各自记录；新工具
必须重新取得实机资格，不能继承旧测试名称的PASS。安全off/rekey、固件排空/复用与
自然恢复另验；SMTC安全权限消费者仍后续接线。

### 受保护 SSAP 首次绑定

`prepare --native-discovery-config CONFIG` 继续使用已有的冻结配置入口；
`CONFIG` 可包含 `[ssap] channel_security = 1` 或 `2`。目前该实机门禁分别要求
`run --security-agent approve` 或 `numeric-approve`，并使用既有
`--qmp-hotplug --connection-verify --connection-advertising negotiable-t
--channel-socket-verify`。配置名沿用历史工具，不表示 SSAP 策略属于无线扫描参数。
准备时以本次 slkd 实际校验配置；运行时核对冻结配置、普通用户探针读取的
`SsapSecurityRequirement`、安装前真实拒绝及安装后两端 SMTC 包。默认配置的
历史基本 SMTC 资格不升级为受保护资格；新路径必须另取准确源码/artifact 的报告。

复用原 SSAP discovery/读写/对端本地数据库核对及 CUTC 随机回复，不添加测试 Engine。
私有 USB 捕获含真实安全材料，不公开；协议 ACK、0011 或 USB 写入不代替业务核对。
该工具门禁不覆盖属性级授权、Bond 或自然恢复，注入与 QMP 操作也不授予恢复资格。

## 原发送意图的生命周期门禁

当前 `--managed-channel-grant` 的双向模式复用原普通工作进程，实际调用统一
`channel_prepare_tx`、`channel_send_constrained`、`channel_recv_security`。它是
pre-daemon File/Grant 受控测试，不等同实际 slkd Agent/授权部署或 daemon 崩溃资格。
工作进程是 uid1000/caps0，保留原 dup/最终管理引用、阻塞 syscall 见证及两端随机业务
校验；回复固定原 RX 机制和 epoch，发起端检查真实回复上下文。

`channel_grant.tx_constraint_required=true` 表示该轮必须提供每次业务发送的48字节
原始限制、40字节接收观察和单调时钟区间。前缀 PDU 也记录实际准入意图，绝对期限
只创建一次、最多5秒；撤权/Down/原期限后分别尝试新 prepare 和原缓存 intent，
不得改成新的 epoch/期限来冒充旧请求已被拒绝。原 raw send/recv/poll 拒绝检查保留。
新 basic Grant 请求可以观察新 epoch，不能因此更新缓存旧 intent 或 protected Grant。

原2秒/8秒 QEMU fixture 只暂扣真实成功 IN81，不能生成回复、NOCP、credit 或恢复。
必须保留完整的 held/released 因果握手、实际满池 debt、确切不完整前缀和原5秒
期限。旧固定几何记录仍按其原五个 debt 核对，新版本按同一 controller 的真实
buffer 报告与状态快照核对容量；不能降低断言以适应当前输出。两个 controller 的 Ready/lease/扫描隔离不代表
四设备独立业务隔离。USB 写成功/NOCP 与对端应用校验仍分开。此新增门禁的源码、
实机资格和旧失败记录分别维护；当前实现不等于新镜像已通过该矩阵。


原期限后的错误分阶段判断：内核 `98b8bb4afa89` 的首次发送准入与最终入队均先拒绝
已失效 Session／Binding（ENOTCONN），然后检查缓存 intent；同一有效且已授权 Session
上的过期 intent 仍返回 ETIMEDOUT。Session 失败不等于 Binding 已销毁。撤权／旧 lifetime
仍保留 EACCES／ESTALE 的更早检查，畸形 ancillary 保留解析错误。门禁分别记录新
prepare 与缓存 submit 的单调 before/after；期限用例必须证实原限制在重试前已过期，
不能简单要求所有阶段 errno 相同，也不能任意接受错误。跨期限不明确的样本不授通过。

## 混合型号的运行期接管

旧 `prepare --native-runtime-only` 现场入口及其生产镜像删除函数已退休，格式的历史
fixture及封存磁盘解码仍保留：曾移除三份 ROM 镜像、保留 BSLE/PM 输入。
当前物理守卫拒绝这种没有合格逐设备
来源交接的接管；五端点、删除镜像或先前另一 VM 的上传均不能补齐该来源。

新混合载体使用显式逐叶输入计划，保留每个固定 guest route 的五文件闭包，复用
原驱动和 Native 流程。暖态初始化与实际 ROM 上传分别记录；发生上传时逐叶核对
对应 SDK110 镜像、QUIT、新枚举及 HCC，不从暖态 Ready 或旧 VM 继承上传 PASS。
`ws73_model_evidence.py`复用现有成对USB读取器，要求唯一
GET_CHIP_TYPE请求、同一USB身份的实际成功回复和后续DLI查询，原消息/长度/状态/
型号/总线不符即拒绝。该工具没有设备访问；结果不认证硅片、执行固件或真实业务。

SDK110 型号差异不能由 U 型常量覆盖：本轮 E 的实际 DLI ACB 为1526字节/6 credit，
U 为254字节/5 credit。普通通道预算和分片证据必须逐发送controller匹配其原DLI
元数据；仍检查debt/outstanding/peak/capacity守恒、队列上限和实际物理分片限长。
错误的另一端容量、未知或缺失元数据不允许通过；E的较大容量不放宽U的限长。


## ROM 型号候选的专用维护探针

`ws73_vm_register_reset.py --rom-chip-expected E|U` 只用于专用QEMU scratch root；
内核命令行须同时含`ws73.register_reset_lab=1`、`ws73.rom_chip_probe=1`及恰好一个
匹配的`ws73.rom_chip_expected=E|U`。不能与wakeup、route、clear-halt或其他reset模式
混用；不在宿主运行。探针先三读运行期寄存器，软件寄存器复位后确认两端点ROM，
三次发送确切的`READM 0x40019000 4 `（尾部空格），再由显式匹配固件启动/HCC，
退役该测试driver后读取三次运行期寄存器。它不启动daemon或给生产路径自动选镜像。

IN请求512字节，实际回复必须恰好4字节；短/长/错误/型号不一致停止且无默认U。
已知U的全零仅保留为歧义观察，`candidate_variant`仍拒绝，所有结果的自动选择和
访问有效性标记为false/未证明。软件复位不是冷断电，HCC是固件自报。每设备路径、
真正冷启动、有效性及并行业务门禁未满足时继续显式板卡配置。证据核对使用现有
USB配对/HCC/上传读器；运行期字节是guest观察，不宣称另一独立寄存器decoder。


### Owned SSAP 的有界真实门禁

`run --qmp-hotplug --connection-verify --channel-socket-verify --ssap-owned-verify`
在原双设备交换连接角色门禁中运行真实前台 `slctl ssap-serve`。仅允许普通固定通道
基线组合；不与 prefix-close、burst、boundary 或动态/公平性专用模式混合。可另外
使用现有 Agent/SMTC policy 配置，但准确安全范围由实际镜像和安装证据决定。

每连接角色、每发送方向运行 allow/deny 两种本地 owner 策略，实际读、UUID读、写、
再读；owner 本进程通过 `value` 检查真实本地数据库。随后 SIGKILL 该前台进程，
验证登记移除且旧handle经真实SMTC拒绝。使用原Run记录、双端USB匹配和NOCP记账，
不能用日志或本地值核对替代远端 wire。该切片的发布者是 uid1000/caps0，实际 system
bus 上使用管理组；不能据此宣称 service-only组权限或完整取消/Down/期限矩阵通过。
所有实验驱动和真实硬件仍只在VM运行，不执行宿主安装或自动电源操作。


### 动态只读 Provider 的结果门禁

在上述普通61字节、每角色4轮的 Owned 门禁上，增加
`--ssap-read-provider-verify`。保持同一前台 Owner、原 caller/generation/lifetime、
真实 callback prompt 与原绝对期限；监督器只在实际提示之后提供显式应用结果。
C/Python 使用现有授权客户端读取，结果由对端 SDK 与双端 USB 同时核对。

新运行记录使用 Provider version2：每个 Owner 依次返回应用错误 `FF`、成功空值、
随机32字节；随后正常退出，旧 handle 的新读请求必须返回错误4。错误、空值与后续
成功分别记录，不能用错误后的成功覆盖错误步骤，也不能回退到绑定前的存储值。
成功空值仍有合法 SSAP 响应和完整双端捕获，不是缺包或日志空行。
现有 version1 历史报告保留原单次32字节读回语义；不能把它改标为 version2，
manifest 与每阶段结果必须匹配同一版本。

此入口不承诺 Owner 在途退出、迟到答复、全部长度、C/Python Provider 收件箱或
完整 SSAP 资格。原期限到期后不要求另发错误包；后续专用期限门禁须验证旧响应
不得新提交。上述命令只描述测试输入与判定，实际产物与结果由授权本地记录维护。

### SDK WRITE Provider 的结果门禁

`--ssap-sdk-write-provider-verify` 是现有 runner 的独立选择项，要求原 Owned、
普通61字节/每角色4轮通道及显式 passthrough 配置。guest 使用唯一
`ws73.ssap_sdk_write_provider=1`；不能混用 READ Provider、Owner-exit/unregister/
deadline、其他 SSAP 扩展、Agent 或性能/动态通道专用模式。它不另建 Host 或 Engine。

version1 的范围是 type0、`0x06` 写专用属性的 verified WriteReq。第一连接角色由
C Provider/Python requester 执行，交换后由 Python Provider/C requester 执行。
每角色先显式拒绝一次32字节拟写值（应用错误 FF），再接受独立随机31和32字节值。
审批、实际 Provider 请求、应用完整验值答复、有限应用内存值、对端 SDK 验证和
双端 USB/SSAP 捕获均单独记录。成功应用内存值不是 daemon staging；FF 步骤不改变它。

判定复用原 ACB 重组、SSAP 字节 oracle、进程/原期限和同 guest 时钟映射检查。
WriteRsp 的错误列表格式与 READ 错误格式不同，不能用通用错误字节代替。
每条请求/响应必须匹配实际 controller/generation/lifetime/handle、TCID/PI 和捕获
时间线；TX 物理分片用于提交计数，RX 分片不能重复计入 TX credit。NOCP 不代表应用处理。

所有三次请求结束后正常退出发布者，核对登记移除和旧 handle 的远端错误4。
完整日志、工具/编译输入身份及两连接角色缺一即失败；监督器/VM 终态、原 Owned
和普通业务门禁仍由统一资格判定检查。本地 reply 或应用值没有双端证据不能通过。

此项目前提供源码与离线 fixture 门禁，准确新产物的真实双设备执行须单独验收。
零长、command、长写、描述符/method、待决注销/Owner 退出、断链及原期限矩阵不在
version1 的正向范围，继续使用各自后续门禁；不称完整 SSAP、形式化或性能资格。
真实执行继续 VM-only，固定白名单端口及每设备显式 SDK110，禁止选择其他线程设备。

### Provider 等待应用时的 Owner 退出门禁

`--ssap-provider-owner-exit-verify` 是独立选择项，依赖上述
`--ssap-read-provider-verify` 和原 Owned、普通通道基线。当前 owner-exit version2
通过共享 SDK 启动真实 C/Python Provider，历史 owner-exit version1 的 CLI Owner
记录按原版本解释；主机和 guest 必须拒绝将旧行作为新版门禁。原正向 Provider
version1/2 报告的含义不变；旧报告或未执行场景不能补成新门禁通过。

两种连接角色各运行一例，分别由真实 C、Python 客户端发起 READ，覆盖不同的物理
Provider 接收设备；角色交换后按完整 controller 身份校验，不能只比较数组下标。监督器等待
原 Owner 的实际 Provider 提示；第一角色由 C 读取 Python Provider，交换角色后
由 Python 读取 C Provider。监督器核对原 SDK 绑定、成功审批、请求身份、基本 CUTC
预算和原期限，再 SIGKILL 该进程；
不发送值、应用错误或正常退出命令。退出必须为 `-9`，等待退出和观察清理均受原
SDK／Provider 期限约束。已预先登记的独立 Owner 保持存活，故障后再实际读取其值。

原请求须在期限内由双端捕获证明返回 READ_RSP 的 `AF` 或错误4，并与真实 SDK
错误对应。`EIO` 本身不能区分它们，也不能排除其他失败。回包可早于进程收尸；
使用发出 SIGKILL 前的时间作为因果下界。清理后的新请求读取旧 handle 必须返回
错误4，独立 Owner 与原普通通道门禁继续通过。完整日志、原身份或任一端捕获缺失
均不得通过，超时或 Engine 失败也不能改记为成功。

usbmon 使用 guest 实时时钟，SDK 期限和返回时刻使用同一 guest 的单调时钟。
门禁在故障前后记录夹取的时钟映射区间，并计入 usbmon 微秒时间戳的量化误差；
只有整个响应时间区间早于实际 SDK 返回和原期限才通过。映射依赖期间没有实时时钟
调整的显式环境假设；两次采样不一致、缺少映射或误差区间跨过界限时均拒绝通过。
监督器完成收尸的时间不能代替 SDK 返回时刻，也不据此报告精确单向无线时延。

新版工具接线及 fixture 反例检查不代表实机通过。新编译调用者、Python Provider
模块和门禁工具须全部进入原 bundle manifest 并重新校验；未取得准确新 artifact
的双端证据前，SDK Owner 退出资格仍缺失。显式服务注销和 SDK 原期限/晚到答复
仍是不同场景，不由本 SIGKILL 门禁推导完成。

这只覆盖原上下文仍有效、原期限尚未到达时的非协作退出；不证明 Owner 撤回能取消
已编码响应，也不证明 Native 物理义务被取消、并发公平性、完整多应用隔离或自然恢复。
原期限到期与迟到答复使用下面的独立场景，不以 Owner 退出门禁续期或强求期限后的错误包。

### Provider 原期限与迟到答复门禁

`--ssap-provider-deadline-verify` 依赖 `--ssap-provider-owner-exit-verify`、
`--ssap-read-provider-verify` 及原 Owned、普通通道基线。它是当前连接 lifetime 的
最后一个 SSAP 场景，不与其他破坏性的期限或生命周期门禁混用。每角色保留原六次
Provider 调用、两次 Owner 退出/独立服务读取，再增加一次超时 READ，共九次实际
C/Python SDK 调用。原版本报告及旧断言保持原义。

监督器只等待真实授权后的 Provider 提示便返回，不在 SDK 调用的到达屏障内等待
Provider 到期。它分别核对实际 SDK `ETIMEDOUT`、返回时刻不早于 SDK 原期限、
原 Provider 期限、接收端准确的期限失败诊断；任意 RPC 错误或监督器超时不能代替。
Owner 仍须存活，并在两个原期限及接收端终态之后，使用原 token 提交一次预先生成
的随机值；必须观察明确的过期输入拒绝，随后显式退出并确认登记移除。

双端捕获必须配对原 READ，并证明整个请求位于实际 SDK 调用与 Provider 提示之间。
同 guest 的时钟夹取、稳定偏移假设和 usbmon 量化误差沿用上节；边界不明确时不授
通过。在完整有限观察窗口内拒绝多余响应、旧值回退、迟到值或重复请求，不要求
期限后另发错误包。有限窗口内没有响应，不是无限时间内不存在迟到消息的证明。

随后只运行现有普通 CUTC 随机业务往返，保持原实际 TX/credit 记账；独立记录请求者
actor 的观察结果，不要求它仍健康，也不据此宣布物理义务已排空。外层正常断链后，
下一角色的新 lifetime 可作为后续正向使用见证；两阶段中只有第一阶段具有该后续
见证。此门禁不宣称旧 actor 恢复、全部控制竞争、C/Python Provider 收件箱、设备
自动恢复或当前分支已取得实机资格。准确产物、执行工具及实际结果由本地记录维护。


### Service-only 的实际 system bus 权限门禁

`--ssap-service-policy` 与原普通双设备连接/socket门禁组合，先在VM的`type=system`
实验总线（`/run/slkbus`）上验证权限，再运行原RF业务回归。使用正式`data/dbus/sparklink.conf`，
真实uid/gid1005、空附加组、零capabilities的前台`slctl ssap-serve`登记/读回/注销自己的
服务；独立unique owner、channel组及observer组客户端验证拒绝。覆盖well-known和
unique destination、接口缺省调用、controller管理/普通通道及直接设备访问的隔离。

root guest监督器只切换测试进程凭据，不实现业务或安全回复；宿主不创建组或安装
服务。这项证明的是该VM实验system bus上的本地角色契约，不能替代service-only
发布者的真实远端业务交付、完整多应用竞争、发行版systemd安装或sandbox验收。
必须保存准确probe ELF、生产程序、策略/账号文件和全部原始结果；缺失角色、拒绝、
凭据、正向登记/读回/清理或错误身份不得通过。原始WS73业务仍由普通用户实际校验。

## 受控 SSAP owner／原期限入口（开发门禁）

`--ssap-owner-lifecycle-verify` 要求独立的双设备 passthrough、connection 和普通
`--channel-socket-verify` 模式，不能混入 Agent、burst、关闭前缀、边界或动态通道。
旧prepared不含该新工具时不能使用；本段描述输入，不代表新artifact已经通过。

协调器使用真实ServiceAuthorizer提示作为到达屏障，再测试owner退出、旧token及
期限后批准；不会模拟远端回复。超时场景通过同一公共C/Python SDK取得实际errno，
原4500..5500ms进程门槛、绝对期限和对端数据库不变检查同时成立才可通过。
负向用例程序退出0只表示预期错误已被核对，`operation_success`必须为false；
提前出现的Timeout、错误errno或意外成功都不能通过。普通通道随后实际回复另验，
不能据此宣称挂起期间的并发隔离、部分初始化或完整取消清理已通过。

## Requester 退出与旧回复排空的独立门禁

`run --qmp-hotplug --connection-verify --connection-advertising negotiable-t
--channel-socket-verify --ssap-requester-lifecycle-verify` 选择独立用例。它要求新
prepared guest，不能与 owner 生命周期、Owned、安全、尺寸、burst、动态通道或
四设备选择器组合。本段说明输入与断言，当前资格仍按准确报告读取。

实际对端提示确认请求已到达后，终止 C/Python requester。旧回复未释放时，新
SSAP 读应软件忙且不得上 USB；既有唯一 slktest CUTC pair 在提示仍挂起期间
完成正常随机校验回复。批准原提示后，对端实际写入、旧回复实际返回并排空，再
完成另一 owner 的独立新读。客户端死亡不承诺撤回或回滚已到达对端的写入。

原五秒不延长，业务等待另受同一保守剩余预算限制；supervisor 失败必须保留输出
并回收自己的子进程。完整 dual-end USB、真实应用快照、所有 busy 尝试及捕获
统计缺一不能通过。本门禁不证明内部取消任务已在某个未观测微观时点完成，也
不证明 NOCP 真值、全复用屏障、完整退出/初始化组合或自然恢复。


## 实际 Native 返回屏障（受控验证范围）

`prepare --native-return-fixture`只为 native VM 编译并封存测试库及编译器身份；
`run --native-return-verify`要求独立真实双设备连接与普通 basic socket 保持门禁。
只在该 boot 标志下给原 slkd 设置一次 LD_PRELOAD；不是生产安装配置，也没有
全局 ld.so.preload。库先执行原 SYS_bind，只暂停明确 Service/User 绑定的返回，
保留原结果与 errno。VM-root 监督器保留固定 selector、原始 C 记录及 socket inode。
两秒到期、缺失/短记录、原 daemon 改变、无真实两端 Down 或后续业务不完整都失败。
普通 SDK 的 Down 拒绝、在途创建晚到 fd 拒绝、物理投影和实际应用交付分别核对。
原生动态 creator、controller 移除、Kernel 引用/UAF/callback 排空仍不在这项范围。
源码接线和离线通过不授实机资格；准确状态只见当前能力入口。
当前取得的Service/User四切片、旧服务反向原始FAIL及仍缺条件，见
[准确来源报告](../evidence/native-return-connection-retirement-20261018.json)。

## 无硬件部署VM

`tools/testing/deployment/debian_lifecycle_probe.py`属于独立的破坏性部署测试，
要求显式disposable-guest参数、专用guest标记和QEMU/KVM；不能在宿主或有管理员
数据的VM运行。它接收两份准确源码与实际Debian包的hash清单，逐阶段匹配SDK，
执行真实system bus、升级、显式confold回滚和remove；不附加USB，不制造controller。
这不是从零准备VM的教程，也不替代上述Kernel Grant和真实业务门禁。

运行日志之外须独立检查最终磁盘文件和原始权限元数据；安全解包会舍弃目录
权限，不能以解包目标目录的权限替代guest目录权限。仅某一开发修订pair通过，
不能推导任意迁移、稳定SDK、可信Bond存储或正式发布；准确记录见
[唯一资格入口](../../project/current-capabilities.md)。
## 目录观察者的新语言输入

`prepare --controller-directory-clients`仅为原Native实验VM封存实际C消费者、Python脚本、
解释器、应用共享库及编译输入。它要求显式Native service bundle，不授设备或ABI资格。
当前`run --controller-directory-events`复用原`--qmp-hotplug`与
`--native-controller-return initiator|acceptor`，要求该准备字段；不再把旧Rust-only
准备产物作为新语言门禁。历史工具、命令和资格保留原身份。

Root collector同时等待Rust、C、Python的实际初始输出屏障，三者均为UID1001、
无附加组/caps/Native fd。C/Python复用公开SDK并先关闭父Client，实际映像、脚本和
已映射应用库分别核对；原始maps有界保留，缺失、错误库、Native库或来源不符拒绝。
每个进程正常退出且原daemon、目录游标/身份、Native返回及对端业务门禁一致才通过。
该检查不是Native Ready/Down/drain、物理拔插、自然恢复或完整语言SDK资格。


## SSAP 通知／指示长度门禁

`--ssap-update-delivery-verify`复用同一真实numeric-approve、类型2审批和SDK消费者。
新prepared声明契约2，固定应用值32、2036、2037、2042字节，各测试通知与指示、两个
方向及交换连接角色。协商线上MTU2042时，2036是单项更新完整PDU上限，2037及2042
需要真实SSAP分片；回写业务回复仍经原verified-write。schema1保留原32字节语义，
不能转作新契约通过；包版本、工具、完整矩阵和分片缺失均拒绝。

新回执ABI和C/Python调用者必须一起封存。通知软件准入、指示接收队列ACK及对端
应用实际校验/回写分别核对；原始双端SSAP片与DLI片分别重组，并按实际TX片数记账。
单次协议原期限、日志/队列预算不放宽，USB成功或ACK不能替代业务回复。
该门禁不证明持续订阅、全部片数、其他MTU、完整生命周期、安全/Bond或自然恢复。
准确artifact及未决条件只见[当前资格](../../project/current-capabilities.md)。

## SSAP 持续订阅与应用回复门禁

`run --ssap-subscription-verify`是独立的有限场景，要求新 prepared 中的
`ssap_subscription_contract_version=1`、显式 protected2 SSAP 配置、
`--channel-socket-verify --security-agent numeric-approve`，不与其他专项场景组合。
它复用唯一 Session、现有订阅 SDK／Engine、原 C／Python 消费者及 VM role
监督器；选项存在及离线 fixture 通过均不授实机资格。

新 prepared 还必须声明 `ssap_subscription_snapshot_contract_version=1`，对应实际
boot token `ws73.subscription_snapshot=1`。监督器在32 MiB guest本地tmpfs中写入
热日志及进度；阶段内固定子进程结束、文件关闭后，只将结构化输出路径迁到
证据位置，原始进程字节不改写。每阶段最多64个文件／16 MiB、单文件4 MiB，
核对完整清单及hash后原子发布目录。根完成标记在本地存储成功卸载后才产生。
共享9p出口不再承载这条门禁的实时追加读取；不吞掉I/O错误或自动重试。

阶段 `snapshot.json`、实际生产工具hash、两阶段完成标记及真实监督器exit均
是必要条件；缺失、篡改、超限、异常退出或仅留下staging目录不能通过。
旧记录缺少该声明时仍绑定原身份，新执行不能用旧prepared或旧证明代替。
这里的封存契约不宣称断电持久化、全系统文件引用证明或自然硬件恢复。

固定矩阵是两个发送方向、交换连接角色、通知和指示各一个30秒租约，
每租约连续3条随机32字节更新，共24条。读取者 UID/GID1004、服务拥有者
UID/GID1005 均无附加组或 capability；发现观察仍由管理测试角色执行。
应用逐条检查完整载荷后经原 verified-write 回写不同载荷，拥有者再实际检查
存储值。协议 ACK 仅表示接收队列准入，不替代该应用检查和回复。

每个租约要求原5秒创建／读取／清理期限、连续序号、安全 epoch／等级、
零丢弃、一次启用与确认停用、真实进程原始输出和双端 USB／HCC 配对。
缺少原始流、角色、对端捕获、业务回复或清理不得通过。根监督器仅接受固定
身份和路径的有限请求，不提供任意命令服务，也不授普通应用管理或抓包权限。

该门禁不证明续租、满队列、多应用共享 CPCD、撤权／断链／epoch 变化、
完整引用排空、自然恢复或长期性能；准确 artifact 的结果仍只读取
[当前资格](../../project/current-capabilities.md)。

附加 `--ssap-subscription-renewal-verify` 要求新 prepared 显式声明
`ssap_subscription_renewal_contract_version=1`，并保留上述基础门禁。每租约先使用
1000ms 有限租期，第一条更新实际校验／回写后，通过同一 SDK、token 和安全 epoch
续为30000ms；两个后续更新必须发生在旧到期上界之后。上界取原获取实际返回时刻
加原租期，避免保守时间戳的采样误差被当成过期证据。等待屏障只用于有限测试调度，
不延长任一创建／读取／续租／发送／清理的原期限。

新门禁要求8次真实续租、16次旧到期上界后的校验回写、原24次业务、确认停用、
原始进程流及双端USB闭包；续租不应额外重写CPCD。旧连续订阅的contract1证据不能
升级为续租通过，缺失声明、boot／请求／记录不符或旧token／epoch均失败。
这仍不覆盖满队列、续租与到期／关闭竞争、多应用、全部生命周期或自然恢复。

附加 `--ssap-subscription-pressure-verify` 使用独立的新 prepared 声明
`ssap_subscription_pressure_contract_version=1`，与续租场景互斥。每个30秒租约
先发送16条更新，再发一条溢出更新；现有 SDK 一次读取真实有限 batch，C／Python
helper 将其有界保留并逐条调用原校验／verified-write。随后一条新随机更新必须
恢复交付。不得用新的读取覆盖尚未校验的缓存，也不能带未校验条目成功退出。

通知必须实际丢弃并计数；指示须收到真实拒绝 ACK 且原 API 返回错误，超时或
软件成功不算拒绝。原队列前16条不能被挤出，epoch／顺序保持，溢出条目不得
制造应用回复，恢复条目序号应为18。八租约共144次发送、136次实际校验回写，
四次通知丢弃、四次指示拒绝及八次确认停用分别核对；各操作原五秒期限不变。
缺少原 batch、真实拒绝、完整进程流、对端包或恢复交付不能通过。
缓冲期间多条消息的应用处理区间会重叠；相同字节的指示ACK必须在各自实际
SDK发送原始时间窗内唯一匹配，不能从整段填队列至回写区间任挑一条ACK。

这是订阅接收队列门禁，不能证明controller data credit、软件发送队列耗尽、
完整生命周期、多应用、公平性、性能或自然恢复。新增选项及离线检查不授实机
资格，旧连续／续租结果不能改名充当本场景结果。

## SSAP 接收者退出与确认清理门禁

未发布 runner 的 `--ssap-update-lifecycle-verify` 只能与
`--ssap-update-delivery-verify`、实际 numeric-approve 机制及普通短包双设备门禁
一起使用；不组合其他故障、长度或压力场景。它复用同一 Session、actor、SDK
消费者和双端核对器，不安装测试 Host。选项存在不代表新 artifact 已取得实机资格。

固定场景为启用审批挂起时接收进程退出、已观察真实启用回复后退出，以及原接收
期限到期。每个场景要求实际类型2审批、双端启用/停用回复、零配置观察和同一 actor
上的后续真实读取；审批挂起窗口还须完成普通通道应用校验回复。启用状态查询不能
代替接收端 USB 回复屏障。live capture 前缀的长度/hash 须从封存原始捕获重建，
最终仍须完整双端捕获与零丢包统计。原始捕获权限保持独立：现有 Host 测试协调循环只接受十二个有身份、固定类型及有限预算的回复观察请求，不接受路径或任意报文查询；普通应用不因此获得捕获读取权限。Host 解码时钟与 guest 接收屏障时钟分别记录，不跨时钟域相减。每次快照最多16MiB，单次请求最多2秒和64次观察；期限或预算耗尽保持失败，不放宽原协议期限。

专用 C/Python 消费者的 `update-error` 参数为 index、generation、Connection 路径、
handle、mode、errno 和原始毫秒预算；当前只接受 ETIMEDOUT 和50至5000毫秒。
错误必须来自真实公共 SDK，意外成功或其他错误均失败，不合成超时结果。
接收者退出不取消已经开始的物理义务；没有确认停用的场景不得计作清理通过。
作者原期限与固定清理预算分别记录，不能用延长原期限隐藏未知结果。

该有限场景不证明全部撤权、断链、安全 epoch、最后引用、无编号ACK/NOCP复用、
多应用订阅或故障恢复组合；准确资格与缺口仍只读取唯一能力记录。

<a id="ssap-完整-pdu-长度门禁"></a>

## 持续订阅接收进程退出门禁

维护者选项 `--ssap-subscription-owner-loss-verify` 仅与独立的
`--ssap-subscription-verify`、protected2 和 numeric-approve 门禁组合，
不能与 renewal 或 pressure 用例混用。需要新 prepared root、匹配的 Host／guest
工具及已关闭文件的本地 phase snapshot；这项接口不代表已有实机资格。

每个方向和连接角色分别测试通知与指示。UID1004 的真实 C／Python 接收进程先
校验三条随机更新并写回不同业务值；root VM 监督器随后只对自己持有的该子进程
发送 SIGKILL，记录实际 `-9` 退出。不能以正常 quit、SDK Drop 或伪造 release
替代进程死亡。UID1005 服务拥有者、daemon、generation、lifetime 与物理 Session
保持不变；之后新接收进程使用同一安全 epoch、新 token 完成三条新业务回复。

配置归零只说明服务端处理了停用。门禁还须在死亡时选定的原始五秒观察预算内，
经现有 UID1000 控制角色调用同一连接的真实值读取，作为接收 actor 释放客户端
事务的收敛屏障；保留最多16次原 Busy 拒绝及最终成功，其他错误或超时均失败。
最终双端 USB 原件须证明停用回复先于该读取请求，且读取完成先于替代进程启动。
UID1000 此次读取是测试屏障，不能替代 UID1004 应用实际校验和回复的交付证据。
不新增捕获代理、协议 Engine 或生产数据旁路。

完整有限矩阵为16个 lease、8次实际退出／重新订阅、48条更新及不同业务回复、
8次真实读取屏障，另有8次替代 lease 的显式释放。全部原始进程输出、请求、
源码／工具身份和双端捕获均须保留。它不证明在途退出、lease 自然到期、
Grant 撤销、断链、无编号回复复用、全部引用排空、多应用共享或自然恢复。

## 持续订阅的在途释放门禁

当前执行复用已有短通道前缀门禁固定的两秒 IN81 fixture，记录实际 binary hash 与
`fixture.version=1`、`hold_budget_ms=2000`、无协议匹配器的明确契约。旧 sequence
fixture 的未版本化回执仅保留原身份的离线验证，不能作为当前执行的 fallback。
当前 hash 缺少契约、契约与 hash 不符、八秒预算或未知 binary 均拒绝。身份与源码
核对不是实际暂扣证明：后续 QMP、原始字节、双端 ACK／disable 和期限断言仍全部必需。

`--ssap-subscription-inflight-release-verify` 是独立的 protected2／numeric-approve
订阅场景，不与续租、满队列、进程退出或其他选择器组合。新 prepared 必须声明
inflight-release contract1、闭合快照和准确新消费者／工具；仅接受现有固定 hash
的两秒真实 IN81 暂扣 fixture。源码接线和离线 fixture 不代表实机资格。

每个连接角色各一次：真实指示已到接收端，ACK 已从接收端发出，但尚未进入
服务端 guest 时，普通应用通过原 SDK 请求释放订阅。Host 必须在原始捕获中
观察到 CPCD 停用请求 TX，且此时服务端 ACK RX 仍不存在，才允许显式释放
暂扣的原 USB 数据。不能用配置查询、日志、固定睡眠或成功 USB 写入替代屏障。
暂扣 aggregate 可能包含 NOCP，不能自动称为 ACK 或证明 credit 的 lifetime 归属。

专用测试消费者的 `release-observe` 只额外输出调用起点和调用前选定的原五秒
期限，实际调用仍复用普通 `release` 的 SDK 路径。服务端实际指示完成、接收端
确认清理和新进程／新 token 在同一 Session／epoch 完成业务校验回复分别核对。
关闭导致已接受更新被丢弃时，必须记录 discard1，不能计作应用交付；这不抹去
原指示的物理义务。最终检查准确双端包、暂扣原件 hash、显式释放计数、零自动
释放／丢包／错误，以及 Host／guest 的原始握手与封存文件。

有限矩阵为10个 lease、32次更新，其中30次实际不同业务回写及两次已接受后
关闭丢弃；两次在途释放后均须新租约继续业务，另保留普通短通道与广播扫描。
这不包含 lease 自然到期、在途进程死亡、Grant／epoch／Down、共享 CPCD、
全部引用排空、无编号完成复用或自然恢复；这些仍有独立未决门禁。

## SSAP 应用值长度及分片门禁

未发布 runner 的 `--ssap-value-lengths-verify` 要求独立的
`--qmp-hotplug --connection-verify --channel-socket-verify` 普通基础模式，
4轮、61字节 CUTC；不能组合 Agent、SDK、其他生命周期、动态通道或压力选择器。
新 prepared root 必须封存匹配 Host／guest 工具。此选项描述开发门禁，不授予资格。

保留双方向各4次32字节事务，再测试应用值0、1、248至255、1024及2037至2042字节。
两端实际 ExchangeInfo 均须是当前 lifetime 的2042字节协商结果。SSAP verified
write 开销5字节，read response开销2字节，单项 UUID response开销4字节；
不能把应用长度、SSAP PDU、DTAP帧或DLI分片长度混作同一边界。零字节及1字节
无法容纳随机序号，使用原命令窗口、身份及精确载荷匹配；较长值保留随机载荷和序号。

版本4要求两端实际协商标准扩展消息控制码及分片序号；仅完整PDU内可容纳的值
不能代替分片门禁。应用值最大2042字节，规范化WRITE_REQ最大2047字节，每个实际
SSAP分片仍不超过2042字节物理MTU。起始/结束片各有独立双端USB/HCC/DLI证据，
序号、写入操作位和顺序均须匹配；credit仍按各片实际ACB数相加，不按逻辑SDU退款。
2043、2048、2050字节写入必须明确拒绝且对端完整原值不变，之后合法事务继续。
原来的2038/2042字节完整PDU拒绝仅属于版本1–3，不改写成新分片资格。

当前入口使用普通UID1000控制角色的真实CLI调用及本地管理staging，再经唯一
用户态Engine与对端实际读取、写入和UUID读取核对；staging本身不是远端交付证明。
其他协商MTU、完整C/Python写入及拒绝矩阵、更新/发现/无序号分片、完整重组故障和恢复资格继续开放。

历史版本3额外对两端本地2038至2042字节值执行真实发现、
按发现所得handle读取和UUID读取，再核对对端完整本地值。2042字节MTU下，read最大
完整值是2040字节，单项UUID最大完整值是2038字节；更大值必须返回READ_RSP的
不支持分片错误16，不能静默截断或换成通用错误响应。随后原32字节及写入长度矩阵
仍须成功。版本3还复用已有C/Python公开应用消费者，在2038、2039、2040字节上
实际读取完整值；两端及交换连接角色合计12次，保留原启动屏障、UID1000零cap凭据、
5秒期限、冻结SDK/执行文件身份、原输出和双端USB包。不得用CLI成功替代这些调用。
这不授予apps-only角色的SSAP权限或完整C/Python长度矩阵。旧版本1/2/3保留原契约、拒绝和源码身份，不补写新增门禁。
版本4在这五个长度上均要求完整read及UUID结果，以及实际C/Python读取，两方向与
交换角色合计20次；不能以CLI代替。新运行须记录版本4、准确新SDK/Host/guest、全部
片级原件及最后supervisor终态，历史捕获不能取得这一资格。分片语义见
[原理解释](../explanation/ssap-value-fragments.md)。

新prepare还记录`ssap_exchange_contract_version=2`，与真实协商输出的十字节序号能力
格式一致；旧封存root缺字段时仅按历史六字节格式1核对，不转授新源码资格。
原`--ssap-initialization-stage exchange`的QEMU selector精确匹配六字节回复，不能
用于格式2；新入口在USB接管前明确NotSupported，等待替换selector和新原期限／撤权
实机证据。原冻结selector、断言及失败/通过记录保留，CMTC专项和数据门禁继续并行；
不把该工具迁移冒充生命周期验收完成，也不以退回旧协议offer绕过。


### 在途订阅的自然租约到期

`--ssap-subscription-inflight-release-verify` 仍选择现有的有限在途清理夹具；
默认 `--ssap-subscription-inflight-case release` 保留原应用主动释放语义。
显式 `--ssap-subscription-inflight-case expiry` 使用独立的 expiry contract 1、
boot 身份与终态判据，不能将旧 release 报告改名为到期资格。必须重新准备完整
Host／guest 工具和镜像；`expiry` 不与额外 Down 被动观察窗口合并。

到期用例仅将每个角色第一只接收者的第一次 indication 租约设为原始 1000 ms。
真实 indication TX、对端 RX 和 ACK TX 均须在到期前发生；保持原 ACK RX 的
有界 USB 延迟期间，不向接收应用发送 release、renew 或 read。现有 Session actor
必须按原租约自主发出 CPCD disable。Host 捕获真实 disable TX 且原 ACK RX 尚未
到达，才允许交还原 USB 字节。之后原发送须完成、清理须获真实回复，接收应用
才能读取 EXPIRED 终态；在途已接受的一包记 discarded，不计业务交付。

终态已确认时不再发送 release；仍在 Closing 时，实际 release 仅等待原到期清理，
不能重启清理期限。两种结果都要求 reason=EXPIRED、discarded=1、空应用批次，
以及相同 Session／安全 epoch 下的新 token 和后续真实校验回写。完成到期及
清理仍受原 expires 加 5 秒上限约束。生产 SDK、Host、credit 和 Engine 不增加旁路。

捕获与应用均在同一 guest，使用有界 realtime／monotonic 采样区间核对 ACK TX
早于原 expires、disable TX 不早于 expires；不跨主机时钟计算单向时延。该检查
依赖记录的 guest 时钟映射，模型／parser fixture 通过不等于实际定时或实机通过。
这是明确的单租约在途到期门禁，仍不覆盖多应用共享 CPCD、Grant／epoch 撤销、
完整 fd／引用排空、NOCP 正确性或自然恢复。历史失败和原断链门禁保持。

### 两个应用共享同一 SSAP 配置

`--ssap-subscription-verify --ssap-subscription-shared-verify` 是独立的保护等级2、
`numeric-approve` 门禁，与续租、队列压力、owner-loss及在途夹具分开，保留普通
4×61字节通道回归。必须重新准备 contract 1 和相同Host／guest工具；不能通过旧
单租约记录改名获得共享资格。

同一物理actor上两个实际普通应用进程分别取得相同属性／模式的不同token和队列。
先让两者各自校验更新并写回不同随机值；第一应用实际release须得到flags=3，
另一应用随后继续完成业务；重新加入的进程须得到新token和原epoch。最后一个
引用释放须有实际双端CPCD停用及flags=1。通知／指示、两个方向和连接角色分别执行。

夹具复用原SDK的read/check/writeback和有限监督器，不增加协议发送捷径。每组7个
发布、12个实际独立业务回复、3个应用租约；完整矩阵8组、56发布、96回复，16次
共享保留释放和8次最终停用。原始USB中每组只允许一次启用和最后一次停用，不能
仅靠本地configuration观察、协议ACK或终态日志作证。每次release保留SDK实际原
5秒起止；子进程和热文件全部关闭后按原快照契约发布。

ACK1在共享组中只代表至少一个有效队列接受，不能证明所有应用收到。此门禁针对
相同过滤／模式、无队列溢出的实际交付；不同集合／模式动态合并、共享压力、
所有在途退出／Grant／epoch／引用排空、四设备和自然恢复仍各有独立门禁。

Shared-gate security epochs are local to each controller/connection. Each reader
lease is matched to its own endpoint’s actual Native SCM security receipt;
provider authorization is matched to the server endpoint’s receipt. Equal epochs
across peers are not required. Missing, stale or changed endpoint context fails
the gate; a verifier fix does not rewrite an earlier failed run.

The separate `--ssap-subscription-shared-case expiry` and `owner-exit` cases
require `--ssap-subscription-shared-verify` and a fresh prepared lifetime
contract. They retain the existing protected SDK, supervision and paired-wire
path. Each group publishes one additional unread update while both owners live,
then withdraws the first owner. The expiry case uses its original 2000 ms lease,
observes EXPIRED with retained configuration and one discarded packet, and never
issues release to cause expiry. The exit case kills only the known ordinary
reader child inside the disposable VM; its complete pre-exit stream and actual
exit are required. The surviving caller checks further payloads and replies,
a fresh caller joins, and only the final reference performs wire disable.

These cases each require eight groups, 24 leases, 56 publications and 96 actual
checked writebacks across both connection roles. An unread publication at owner
exit is not claimed as observed application delivery or an inspected dead-owner
tombstone. The expiry read does not prove timer execution before all possible
queries. Neither case is kernel Grant revocation, security-epoch withdrawal,
callback/reference drain, recovery or performance qualification. New gate source
and offline checks alone do not qualify a compiled artifact; use the canonical
capability record for the exact run. Existing release evidence keeps its original
case and identity.

The separate `--ssap-subscription-shared-case pressure` requires a fresh
`ssap_subscription_shared_pressure_contract_version=1` prepared bundle, the
same protected numeric-approve shared gate, and its exact boot/request/source
closure. It cannot relabel the single-reader pressure or lifetime cases.
Each group publishes 17 random 32-byte values while reader A does not read;
reader B must check and write back every value. A then drains exactly the first
16 packets, observes one notification drop or one locally refused indication,
and checks each cached value before sending a distinct writeback. The next
publication must reach both readers, with A's sequence gap and cumulative loss
preserved. A releases only its token; B continues, a fresh A joins, and only
the final B release disables the remote configuration.

The finite matrix requires 22 publications and 41 actual checked writebacks per
group: eight groups, 176 publications, 328 writebacks, eight ordered drains and
eight resumptions. B has no losses; the slow queues report four notification
drops and four local indication refusals in total. Wire indication ACK1 remains
required because B accepted the update; it is not evidence that A received the
overflow or that either application processed it. Root transcript and snapshot
budgets are explicitly bounded for this larger profile: at most 64 reader JSON
lines and 128 provider value observations (126 are required), with a 4 MiB
closed phase JSON limit. The provider marker and exact helper source are part
of the sealed closure; a missing marker or exhausted budget fails before
issuing another value command. Old profiles retain 24 reader lines, 80 maximum
provider observations and their original closed JSON limits. The ordinary
4×61-byte socket baseline remains separate.
Source/offline checks do not qualify a new artifact, full load/fairness,
controller credit, Grant withdrawal, drain, recovery, or performance.

Native `--channel-benchmark rate|window|duplex` now requires a fresh apps-only
benchmark prepared contract. The existing fixed VM role supervisor starts the
actual `slktest` children as UID/GID 1004 with no extra groups or capabilities;
the controller manager stays UID 1000. No alternate live control-role benchmark
loop is retained. Historical control-role reports keep their original identity
and are decoded as such.

Both endpoints still arm before `start`, become quiescent before `finish`, and
keep the existing original protocol/application deadlines. Reports are written
by the applications in a bounded guest-local directory, then exported with full
raw streams after the children close. The benchmark snapshot profile bounds a
phase to 512 MiB, each file to 256 MiB and tmpfs to 768 MiB; its VM uses 2 GiB RAM.
The SSAP snapshot profile remains separate at its existing limits. Budget errors
fail the gate and never truncate reports. Unchanged schema2 metrics and the real
ordinary socket path are reused; no per-message D-Bus/data Engine is added.

The first qualification gate uses 20 messages, 61 bytes and window 4 across both
connection roles. It tests application permissions, paired report/capture
closure and measurement correctness. It does not qualify all load combinations,
a stable latency/throughput baseline, full stress or an optimization benefit.
Use the canonical capability record for exact compiled and executed identities.

### Queued PDU retirement during the File/Grant lifecycle gate

`--managed-channel-queued-discard` is an explicit test profile, requiring
`--managed-channel-grant`, `--managed-channel-revoke-prefix`,
`--session-service-observe` and an explicit connected File case. It reuses the
same ordinary constrained socket worker, physical Session, original five-second
TX intents and pinned real-IN81 barrier. Protected, directional, fd-transfer
and unrelated benchmark modes are not part of this profile.

The worker admits the original random 2042-byte begun PDU and two additional,
distinct random 2042-byte PDUs. Its actual TX status must show exactly two
queued objects, queue limit eight and the original busy PDU. Each queued send
has its own unchanged absolute intent. Later denial retries still use the
original begun-PDU intent, not the last queued send's newer intent.

The existing release, final File close, dup first/final close, physical Down
and original-deadline oracles remain mandatory. An additional Session trace
join matches each queued syscall's monotonic interval to exactly one original
generation/lifetime/epoch admission and one stage-3 terminal, with no accepted
USB prefix or sibling discard. The begun PDU has a separate admission and
partial physical prefix; it is not counted as a queued discard. The legacy
`partial_retired_operations` counter includes all not-fully-submitted objects,
including unsubmitted queued discards; `queued_discarded_operations` distinguishes
them explicitly.

Missing identities, queue status, terminals, accepted-packet accounting or trace
loss rejects the whole profile. Local retirement does not prove credit refunds,
controller completion, callback/reference drain or natural recovery. The test
adds no business round trips: existing peer-checked business remains separate.
This source contract alone does not qualify an artifact; consult the canonical
capability record for exact executed gates and remaining conditions.

## 无响应写命令的独立交付证据

`--ssap-write-command-verify` 是现有双设备普通 socket VM 门禁的显式选项。
它要求 `--qmp-hotplug --connection-verify --channel-socket-verify`；运行该交付门禁时
显式选择 `--connection-advertising negotiable-t`，不要依赖 runner 的 `fixed-t` 默认值。
`fixed-t` 保留为独立连接模式对照；模式选择及是否实际建链须分别记录，不能据此
推定固件／空口故障根因或自动恢复通过。该门禁保持原
4 轮、61 字节普通业务回归；不得与其他独立 SSAP、性能或故障选择器组合。
guest 使用同一版本的 `ws73.ssap_write_command=1`，缺失、重复、未知版本或
请求与报告不一致都拒绝验收。QMP 对照不代表物理拔插或自然恢复。

契约 1 包含两种连接角色、两端分别发起、实际 C／Python 应用入口，以及
0、32、2042 字节属性值，共 24 次 Write Command。对端原 Owned 注册仅声明
READ 和 WRITE_NO_RSP。非空值使用预先生成的序号和随机载荷；空值绑定本次
注册及非空初值，不宣称空载荷本身具有随机标识。所有应用保持原普通用户
和无 capabilities 条件；这不增加 apps-only 部署或安全等级资格。

每次 SDK 调用保留原五秒期限和启动屏障。其成功仅表示软件准入；必须另外
完成真实远端 Read，以及仍存活的原服务所有者本地读回。交付观察窗口包含
这些操作，不能以发送进程退出时刻截掉迟到 RX，也不能延长原 SDK 期限。
随后的 Read 是另一项协议操作，不是 Write Command 的确认。

双端 USB 证据独立匹配命令、Read 请求及响应，保留 ACB/PB 分片和实际物理
发送计数。2042 字节值还要求已协商的 SSAP 序号分片、顺序与完整性；残余
命令、意外 ErrorRsp／WriteRsp、缺腿、重复或窗口外证据均拒绝。NOCP 只用于
已有 credit 记账核对，不能替代应用读回。正常退出与注销也不代表故障恢复。

源码门禁和离线负对照不授予实机资格。历史报告保留原工具和编译身份；新
artifact 的执行结果须单独记录。范围不含完整权限矩阵、多通道、四设备、
性能、安全或自然恢复；这些原有验收条件继续保留。

## Write Command 本地拒绝与所有者决策

`--ssap-write-command-policy-verify` 是上述门禁的附加选择器，必须同时指定
`--ssap-write-command-verify`，并保留原普通 socket、连接和 QMP 前置条件。
它使用独立契约 1 和 guest token `ws73.ssap_command_policy=1`。缺少原正向门禁、
重复或未知 token、请求与报告不一致均拒绝；原 Write Command 契约 1 的
24 项正例、每阶段 4 轮 61 字节业务及其断言继续执行，不用 policy 结果代替。

每个连接阶段在原正例后运行四个独立 policy 组，覆盖 C／Python 和两个发送方向。
组内使用同一存活的 `slctl ssap-serve` Owned 注册、READ／WRITE_NO_RSP 能力及
`ask` 策略。先由实际 SDK 拒绝 2043 字节值并 Read 原 32 字节值，再拒绝一次随机
32 字节命令并 Read 原值，最后允许另一随机 32 字节命令并 Read 新值。两次命令值
彼此不同，也不同于初值。每组核对两条命令、三条 Read 请求和三条 Read 响应，
共八个双端配对的数据包组；两阶段合计八个 policy 组。
拒绝之后必须通过另一次真实远端 Read 和原所有者本地读回确认值不变；允许之后
也必须以两种读回确认新值。原注册不在两次决策之间注销、替换或重建。
所有进程继续使用普通 UID 1000／无 capabilities 的现有测试身份，不据此新增
apps-only 部署资格。

监督器等待完整的新 `SsapAuthorizationPrompt`，核对接收端 controller、generation、
connection lifetime／handle、security epoch、属性 handle、类型、方向、长度和原期限，
然后向原进程的 stdin 发送 `yes <token>` 或 `no <token>`。CLI 的本地 token 与
Engine request id 不同；不能预先灌入回答或将旧回答用于新提示。空值命令仍是
`write=true`。提示行只显示值长度；完整随机载荷由两端 USB 证据核对，不能把提示
日志描述为载荷校验。随后 Read 也需要独立批准，且拥有自己的原始请求期限。

命令返回成功仍只代表发送端软件准入。拒绝测试必须先证明 opcode 12 在两端完整
出现，随后 Read 返回旧值；缺少命令、缺少任一端捕获或观察窗口不完整不能算作
“成功拒绝”。完整捕获中还要检查重复、残余、意外命令响应和额外协商，保留 PB／SSAP
分片及 NOCP 记账。关于没有响应或没有额外包的结论仅适用于完整的本组观察窗口，
不是无限期的不发生证明。

连续性记录限定为相同连接 lifetime、原 Owned 注册／进程、连续的请求身份和没有
观察到额外 ExchangeInfo；当前接口不提供 Engine 实例 ID，不据此声称直接证明
对象实例从未重建。源码接线、离线回归和新选择器本身均不授实机资格；准确新产物
仍须单独执行并登记其限定结果，原失败与其他未完成验收继续保留。

## 显式 HCC 原始观测

未发布的 `--channel-benchmark-hcc-memory-observe` 是专用 VM 的诊断选项。它要求
已有 `--channel-benchmark-ssap-owned --channel-benchmark-credit-observe`、原
128 条 × 2042 字节／window 8 动态通道负载和 `full-load-v2` Session 观测；不改变
Owner、调用和业务原期限。默认未启用，常规故障采集也不会读取该属性。

该选项只在原两个 guest 端口 `1-1`、`1-2` 对应的 interface 0 读取
`hcc_memory_observation`。内核属性权限为 `0400`，每次读取发出固定的
class/interface-IN `a1/05/0000/0000` 四字节控制请求，USB 超时为 250 ms。
先保留实际普通用户的 `EACCES`，再由 root 子进程读取；管理诊断权限不授予普通
应用。采集复用既有有界监督器，最多每秒一组、128 组，无重试；任一端点首次出错
后，本阶段该端点后续槽位只生成实际进程的跳过记录，不再发出 USB 查询。

成功输出携带 controller id、generation、原始小端字、内核单调时间和固定
`semantics_verified=0`。全零、全一或其他四字节回复只表示收到了原始字，不能证明
其是有效剩余内存；错误、短回复、停止及旧 generation 不填零，也不授予 Ready。
该查询不是 DLI 命令／数据 credit、对端业务交付、自然恢复或硬件身份认证。
SDK SLE 的 HCC 流控开关与该诊断不同，不据原始字启用新的发送门控或归还 credit。

root 诊断进程、普通业务应用和对端 SDK 调用分别记录身份；原始输出、退出、期限、
访问拒绝、失败和跳过保留在该轮报告。采集完整与业务整轮成功分别检查。
观测增加控制流量及调度开销，不能将这一配置当成低扰动性能基线。离线夹具和
无 USB 启动检查也不代表真实固件支持、并发引用排空或业务资格已经通过。

## Write Command 原期限终态与普通通道保持

`--ssap-write-command-deadline-verify` 追加原期限门禁，必须同时选择上述正向和
policy 门禁。契约版本为 1，guest token 为 `ws73.ssap_command_deadline=1`；
缺少依赖、重复或未知 token、缺少一阶段证据均拒绝。每个阶段完成原有正例与
policy 用例后，由该阶段的连接发起端提交一次随机序号和载荷的 32 字节命令：
第一阶段使用原 C SDK，交换角色后第二阶段使用原 Python SDK。两阶段分别覆盖
两个物理发送方向，各端接收一次到期命令；不是每种 API × 每个方向的完整矩阵。
原 `ask` 所有者不答复，让接收端首片建立的五秒期限到期。

门禁核对接收端 `GetSsapInfo` 的真实 D-Bus `Failed`，只接受生产的
`original SSAP authorization deadline` 或 `original SSAP obligation deadline`。
独立的两秒观察预算允许有限次查询，但不延长协议期限；任意 RPC 错误、
权限失败或“睡够五秒”均不能代替终态。终态之后向原 CLI 写入晚到 `yes <token>`，
再读取原 Owned 值；该 CLI 会忽略过期输入，没有专门的“晚到答复已拒绝”回执。
因此判断同时依赖值不变、无批准、持续 Failed 与完整双端捕获。

随后仍由两端普通用户 `slktest` 在原物理 Session 上完成四轮 61 字节实际校验回复。
普通业务的完整 USB 数据片、应用记录和生命周期身份必须落在终态后的窗口。
窗口内只允许原 Write Command 的两个 SMTC 端点见证，不允许伪命令响应或隐式
ExchangeInfo 重启。Failed 后不通过该 Engine 发送远端 Read；本地 Owned 观察和
普通业务有各自明确职责，不能把普通业务成功写成失败的 SSAP actor 已恢复。

两阶段之间沿已有 Disconnect／新 lifetime 流程重新建链，第二阶段原正向命令
为第一次终态提供一次新 lifetime 的实际交付见证。第二次终态没有第三次重建，
不能宣称两次均已恢复。启动、发送、原期限、清理、capture 和程序身份仍由现有
设施记录；工具源码、离线 fixture 和模型均不授实机资格。该有限门禁不证明
完整 callback／Native drain、四设备故障域、apps-only 部署或自然自动恢复。


## SSAP 接收能力拒绝门禁版本

当前 `ws73_ssap_value` 使用接收能力拒绝 v2：对实际发现且没有 notify 能力的
属性，以 CLI 已有默认值 5000 ms 创建一次原始调用期限，并要求精确
`org.freedesktop.DBus.Error.NotSupported` 和对应能力拒绝原因。外层进程监督仍为
10 秒，不是延长期限或重试；超时、其他错误、成功、错误 controller 均判失败。
当前 VM runner 要求 v2，原命令、版本、期限及两端拒绝收据保留于原报告。

历史 v1 的 10 ms 请求及失败保留原样，只按 v1 重放，不能改标 v2。能力拒绝与
原期限耗尽是两个独立契约：SDK 身份检查、排队、D-Bus 和返回复核均消耗原期限；
到期后的内层成功或拒绝不能覆盖超时。相关 SDK/daemon 生产函数回归验证该优先性，
不证明实际设备运行时在哪一层耗尽。新门禁仍须准确新 artifact 的 VM 验收，不能
以输入期限调整、fixture 或历史通过宣布 SDK 生命周期成功。此变更不修改协议监督
期限、不授予性能资格，也不覆盖 Provider 自身的原期限门禁。
