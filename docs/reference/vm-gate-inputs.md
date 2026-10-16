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
| native_service_bundle | 准确编译用户态及 guest 工具的 bundle manifest，不能用文档提交代替编译身份 |
| SDK111 inputs | 合法取得并记录 hash 的固件、校准和板级输入；不在公开文档分发 |
| physical USB selection | 明确物理端口、VID/PID 与当前枚举；device number 可变，不是稳定身份 |
| execution tools | Host runner/独立核对器与 guest 程序身份分别记录，不假定等于编译服务提交 |
| captures | 两端 USB/HCC、完整 console、capture-stats、进程退出与实际对端应用随机校验回复 |

`tools/ws73_vm_native_root.py` 是内部 staging 模块，不是部署 CLI。
三个 native 输入共同描述实验 VM；它们不自动授予 Ready、连接或安全资格。
Installed、transport 可用和每设备 Ready 分开观察。内核及所有真实 WS73 操作保持
VM-only，主机不安装实验内核、驱动或服务。普通应用业务权限与环境管理/捕获权限分开。

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
