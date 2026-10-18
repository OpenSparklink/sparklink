# VM 回归输入契约（集成／测试参考）

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

## 当前共享硬件边界

本线程的 [资源配置](../../project/lab-resource-policy.json)固定允许 U
`1-1.1.1`、`1-1.1.2` 与 E `1-2.1.1`、`1-2.1.2`；两 hub 的 `.3/.4`
是另一线程专用。端口不是外壳编号，声明型号还需新 VM 的实际 HCC 核对。
新 runner 不接受任选设备、旧端口回退或枚举编号。每次 QMP 附加（包括重枚举）
重查端口、序列 hash、上游 hub、PCI 归属及占用；变化即停止，不能强制解绑。
每端口共享 lease、独立 VM 运行锁和目录用于协调，不防御不合作的特权操作者；
root fd 可能不可见，不能把只读进程快照称作绝对独占证明。

`prepare --board-model U|E` 要求对应 SDK110 的主固件与两份校准全部 hash 一致；
新物理执行要求此 provenance 和新 guest 的 HCC 检查。纯 support 模拟入口不需
物理配置。新 prepared/run 必须位于该配置的线程独立运行根；旧封存根保持原样。
当前驱动只有一个固件目录，同一个 guest 只允许同型号；混合 E/U 及无法证明
每设备 RAM 固件来源的 runtime-only 接管拒绝。不得修改旧 manifest 来绕过检查。
板级 `bsle_custom.bin`／`pm_config.bin` 仍须显式提供并记录，型号匹配不证明板级资格。
新 guest 先记录实际 `HCC_GET_CHIP_TYPE`，与显式型号和 USB 总线不符则失败。
这不是冷 ROM 自动选择，也不是芯片认证。历史三设备 SDK111 reference 诊断
无法满足此分配下同型号/SDK110约束，须等待明确适配；原代码及证据保留。

禁止整 hub／主控制器透传、复位、切电；单口恢复若无法证明无连带影响先协调。
现有构建 wrapper 与物理 runner 通过共享 build lock 和 VM lease 握手：合计
最多12路，有任一真实 VM 最多8路；旧工具不持该锁时须另行核对，不能各开12路。
设备冲突不抢占，构建不因提速被中断。新拓扑、E和混合结果分别授予准确 artifact，
旧 PASS 和人工/受控操作不能充当新资格或自然恢复。

## 公共 C/Python 客户端的专用门禁

`run --qmp-hotplug --connection-verify --connection-advertising negotiable-t --application-client-verify` 选择独立的
真实双设备 SDK 用例，要求完整 native VM 输入，不能与 socket benchmark、注入、
Agent 或其他生命周期选择器组合。QMP 拔插仅是 guest 控制对照，不是自然恢复。
本段描述 runner 输入，新增产物是否通过仍以准确资格记录为准。
`negotiable-t` 与既有 SDK110 封存建链条件一致；`fixed-t` 是独立对照，已有 Ready/
发现后连接超时失败，不能当作该已验证条件。广播参数和实际生效身份仍逐项核对。

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

## 受控原期限与生产转换序列输入

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
revoke-prefix组合使用普通2秒真实IN暂缓。当前工具要求primed模式：四条不同
61字节消息由对端真实校验，源端实际TX快照为四份未支付debt、空队列且flags=0；
长PDU先耗尽剩余一份，须观察ACTIVE/BEGUN、未完成offset和五份debt。收到对端
真实Down后才显式释放原完成。缺前提、限时自动释放或前缀已完整均失败，不能
以guest成功标记覆盖USB核对。四条单向预备消息不计作四次往返。

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
必须保留完整的 held/released 因果握手、满池5个实际 debt、确切不完整前缀和原5秒
期限；不能降低断言以适应当前输出。两个 controller 的 Ready/lease/扫描隔离不代表
四设备独立业务隔离。USB 写成功/NOCP 与对端应用校验仍分开。此新增门禁的源码、
实机资格和旧失败记录分别维护；当前实现不等于新镜像已通过该矩阵。


原期限后的错误分阶段判断：生产 `sl_prepare_tx` 首先拒绝已失败 Session（ENOTCONN）；
携带原已过期限制的 send 在 `sl_tx_access` 检查限制时返回 ETIMEDOUT，先于之后的
准入状态检查。撤权/旧 lifetime 仍保留 EACCES/ESTALE 的原检查。门禁分别记录新
prepare 与缓存 submit 的单调 before/after；期限用例必须证实原限制在重试前已过期，
不能简单要求所有阶段 errno 相同，也不能任意接受错误。跨期限不明确的样本不授通过。

## 混合型号的运行期接管

`ws73_target.py prepare --native-runtime-only` 要求完整 Native VM profile；该产物
校验完输入后从 `/lib/firmware` 与 `/usr/lib/firmware` 两条查找路径移除三份 ROM
镜像，保留 BSLE/PM 板级输入，记录移除的原 hash。运行入口要求所选设备均已是
五端点运行期接口；两端点或未知描述符明确拒绝。意外回到ROM后缺镜像即失败，
不能借用另一型号的镜像自动下载。已封存磁盘的hash仍由原prepared校验检查。

先在每型号独立VM中受控下载匹配110及校准，并通过实际USB字节核对，再用该模式
执行混合E/U业务门禁。`ws73_model_evidence.py`复用现有成对USB读取器，要求唯一
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
