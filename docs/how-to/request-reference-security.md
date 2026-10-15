# 在实验 VM 中明确批准或拒绝一次安全请求

本指南面向已准备好双 WS73 VM 的开发者：两端已经 Ready、建立物理连接，且正在
使用同一 `slkd`。正式 CLI 已有准确新镜像的批准/拒绝双角色子门禁，范围仅见
[当前能力入口](../../project/current-capabilities.md)；其中回答由测试协调器逐提示写入，
人工终端全流程尚未整体重放。不能继承旧测试见证程序资格。驱动和设备操作保持 VM-only。

当前仅支持 `sdk111-no-mitm` 参考方法，无身份认证、可信 Grant 或 Bond。
不适合用来建立可信生产连接。Agent 批准只代表策略允许，不代表安装或业务交付。

## 准备当前连接身份和权限

在 guest 内运行 `slctl list`，使用返回的完整 adapter 路径。对两只设备分别运行：

```sh
slctl --adapter "$ADAPTER" connection-objects
slctl --adapter "$ADAPTER" connection-info "$CONNECTION"
```

`ADAPTER` 和 `CONNECTION` 必须填入实际输出的路径；后者含 generation、peer 类型、
地址及 lifetime。仅继续使用 known、connected 的当前对象；断链后重新查询，不能只
替换 handle。记录两端 role，0 为主动 G、1 为被动 T。

这些命令需要实验环境既有的 controller 管理/Agent 权限，普通业务通道权限不足。
现有 UID 1000 控制组资格不是通用部署或仅应用组权限的验收。不要在宿主加载驱动
或通过 sudo 绕开授权失败。

## 为两端分别运行显式 Agent

每个 controller 使用一个终端，保持命令运行：

```sh
slctl --adapter "$ADAPTER" agent
```

看到 `AgentReady` 才开始请求。没有 `--yes` 或默认批准；不能将 VM 测试专用的
`native_security_agent_probe` 安装为自动批准 Agent。输入必须来自可轮询的终端或
管道；常规文件不受支持。输入行上限 512 字节，提示前的已缓冲输入会丢弃。

## 在原始期限内请求并逐次回答

在另外的终端分别启动两端请求，先被动 T，再主动 G：

```sh
slctl --adapter "$ADAPTER" security-request "$CONNECTION" 5000
```

两端原期限各自从 Allocate 开始，包括 Agent 等待；最大 5000 毫秒，批准不会
重新计时。人工操作必须在该窗口内完成；超时应保留失败，不通过扩大协议期限
掩盖操作延迟。

核对 AgentPrompt 的完整路径、地址、role 和 method。只在确实愿意允许本次
**未认证参考流程**时输入 `approve REQUEST_ID`，否则输入 `reject REQUEST_ID`；
将 REQUEST_ID 替换为该提示的实际数字。错误编号、未知回答和迟到回答不会批准。
一次只接受一个未回答提示；额外并发请求明确拒绝，而不无限排队。

## 检查结果或失败

请求端的 `ReferenceSecurityResult` JSON 分开记录策略 phase、error、Agent 批准、
原生准入、kernel state/error/flags/status 和 cleanup error。只有完整成功条件满足
才退出 0 并打印 `ReferenceSecurityCompleted`；拒绝、超时或错误退出非零。
即使完成，也只表示该限定机制的控制器观察；对端业务处理必须另行实际校验和回复。
字段及各阶段含义见[接口参考](../reference/interfaces.md#显式-agent-与-sdk111-限定流程)。

- NotSupported：方法/能力未支持或未注册显式 Agent；不回退到旧 Pair facade。
- AccessDenied：权限、原调用者或生命周期不匹配；先核对权限及当前对象。
- 请求被拒绝或到期：记录原结果；不重用旧编号、不续期。新请求是否允许由原 Session 状态决定。
- daemon 所有权变化：本次 Agent 和请求停止，不自动跟随新 daemon 或旧路径。
- IPC watchdog：仅限客户端等待上限；能够取得原编号时尝试撤回该请求，不宣称物理清理完成。

请求端 Ctrl-C 只撤回自己的请求。Agent 端 `quit`、EOF 或 Ctrl-C 只注销自己的
Agent；不停止 controller、不主动断链、不释放他人通道或清除在途 credit debt。
注销失败会明确报错，不能当作已完成清理；退出该 CLI 总线连接后由 broker 收敛。

申请、启动、查询和取消必须保留同一个调用者连接，因此不要把 Allocate 和 Result
拆成不同进程。正式 `security-request` 已在一个进程中完成这些步骤。重复运行命令
不会继承旧结果或授权。更完整的安装失败、在途撤权/断链及进程被杀矩阵仍待实测。
