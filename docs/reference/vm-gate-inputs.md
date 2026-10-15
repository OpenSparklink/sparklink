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

`ws73_target.py run --security-agent cli-approve|cli-reject` 选择新门禁（尚待实机验收）。
它要求独立双设备 connection/socket 模式、当前 prepared 工具和 `/bin/slctl`，
不能复用不含正式 Agent/请求入口的旧镜像。`cli-approve`/`cli-reject` 只存在于
VM 测试协调器；协调器读取真实 CLI 提示后通过 stdin 给出显式测试回答，正式
CLI 本身没有自动批准功能。每端分别启动 Agent 和原作者请求，共四个实际进程。

原 stdout/stderr、退出码、原凭据、路径、提示、回答、期限与终态均保留；监督器
异常、缺失/截断记录、丢失对端 RX 或安装事件不能通过。既有独立 USB/relay/
安装和对端业务校验继续必需；无 MITM/可信身份/Bond/自然恢复资格。
原六种测试专用 Agent 模式保持单独范围，不将新 CLI 模式当作它们的重放。
