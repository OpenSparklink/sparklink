# 应用发现会话（开发接口）

本页描述已接线的 Rust／D-Bus／slctl 接口。显式release已有双U的限定真实证据，
完整生命周期和部署权限仍未完成；不同广告条件的成功、失败及限定范围不得省略。
此前管理者广播／扫描的历史 PASS 不覆盖这些入口。
准确来源及仍缺门禁以[当前能力](../../project/current-capabilities.md)为准。
C／Python 尚未提供这组会话 API。接口未发布，没有旧名称兼容期。

## 权限与身份

普通应用通过 `libsparklink::Client::discover` 申请会话，daemon 使用已有 Native
管理凭据和 WS73 recipe。客户端不取得管理凭据、Native fd、连接或通道 Grant。
会话绑定唯一 D-Bus caller、不可变 controller 路径及 generation；重启 daemon
或替换 controller 后不自动恢复。派生会话保留同一 Client，关闭父 Client 不转移身份。

`sparklink-apps` 精确增加 `AcquireDiscovery`、`ReadDiscovery`、`ReleaseDiscovery`。
`StartControllerScan`、`StopControllerScan`、`CancelDiscoveryPolicies` 仍属于管理者。
此授权不是完整逐应用／逐 Peer 策略，也不将公开广播变成私密数据；原管理观察接口
仍有各自权限。会话过滤约束本会话输出，不能据此承诺无线流量保密。

## 支持范围与预算

当前仅支持 Native WS73 固定策略的 passive frame-1 扫描。不同会话共享该策略；
没有动态合并 PHY、scan window、主动请求或 UUID filter 的能力。其他 profile 明确拒绝。

| 参数／资源 | 契约 |
| --- | --- |
| `prefix` | 原始 vendor report data 的字节前缀，0–64 字节；空前缀接受任意数据 |
| `minimum_rssi` | −128…20；−128 包括未知 RSSI，否则未知值不匹配 |
| `duration_ms` | 250…60000，从 daemon 准入起计的有限租期，不在 Ready 后重新开始 |
| 会话／owner watch | 每 controller 最多 16，每 caller 最多 2，包含 pending、active 和未排空 watch 引用 |
| 接收队列 | 每会话最多 32 条；每条 data 最多 255 字节、当前 WS73 header 为 23 字节 |
| 读取等待 | 每会话一个 reader，每 controller 最多 16 个；重复并发读取拒绝 |

这些是接收与资源预算，不是广告发送长度、固件最大 PDU 或业务可靠性资格。

加入已有扫描前重新观察 Kernel radio state，不从 daemon 布尔值制造 On。
新会话记录 Native event watermark，忽略准入前已排队的报告；序号属于所有 Native
事件，不要求两条广告的序号连续。重复、较旧或错误 generation 的报告不进入新队列。

## D-Bus 与 Rust

方法位于不可变 Adapter 路径的 `org.sparklink.Adapter`。共享类型定义在
`slk-contract::discovery`；`Deadline` 是既有五个 uint64 的绝对时间及 clock-domain 身份。

| 方法 | 输入 | 返回含义 |
| --- | --- | --- |
| `AcquireDiscovery` | prefix、minimum RSSI、duration、原始 Deadline | 非零 session id；首次启动须有真实匹配的最终 Complete，加入须核对现有 scope／Kernel radio state |
| `ReadDiscovery` | session id、wait、原始 Deadline | 有界 Batch；只消费该 caller 的该会话队列 |
| `ReleaseDiscovery` | session id、原始 Deadline | false：释放本会话，其他会话继续；true：最后会话释放且真实 STOP 在期限内确认 |

Batch 包含 version、session、generation、累计 `dropped`、累计 `kernel_lost` 和报告。
报告保留 Native sequence、Kernel boottime、地址类型／六字节地址、RSSI及其 known 标记、
raw header／data。未知 RSSI 原值为 127；它不是有效测量。

Rust `DiscoverySession::read` 校验身份、长度、过滤、header 地址一致性、单调序号
和累计丢失计数。队列满丢弃最旧报告并计数；它不是无损或可靠业务交付通道。
`slctl discover` 遇到 gap 失败，不将缺包变成成功。业务数据仍使用每逻辑通道 socket。

RPC 最长等待五秒，且不会延长调用者原始期限。空的有界等待可返回 Timeout；
Rust 单次 read 不隐式重试。CLI 可在同一原始截止时间内继续观察。该用户态期限
不等于已将期限传给 Kernel recipe；Kernel 自身的监督期限与已开始物理义务仍须结清。

## 关闭、失败与限制

单个释放、调用者退出或租期到期只移除自己的会话；仍有其他会话时不发 STOP。
最后一个消失后由同一 controller worker 申请真实 STOP，不释放整个管理 lease，
不借机清理连接。管理者显式 STOP 则撤销受影响会话；Native lease 更换及设备退休
隔离旧 epoch，迟到工作不能重新发布旧会话。

显式 `close` 才能观察上述返回值。Drop 在现有 Tokio runtime 上尝试有界释放；
runtime 已结束或回复丢失时不承诺即时关闭，daemon 仍负责 owner-loss／有限租期。
丢失 Acquire 回复可能留下未知 id 的租约直到 caller 退出或原租期结束。
取消 destructive read 可能使已消费回复不确定；没有自动重放或隐式 resnapshot。

非法过滤／clock-domain 返回 InvalidArgs；过期、撤销或不属于该 caller 的会话返回
UnknownObject；等待超时返回 Timeout；busy、Native 失败或未知清理结果明确失败。
应用关闭不抹去已经开始的物理义务。不确定启动／STOP 失败会保留该 controller 的
故障状态与日志，不能宣布 Off 或 Free；完整部分初始化和取消／原期限组合仍待实机验收。

## CLI 语法

`slctl --adapter PATH discover [RAW_PREFIX_HEX|-] [COUNT] [DURATION_MS] [MIN_RSSI]`

COUNT 为 1…1024，CLI 租期为 250…30000ms；默认任意前缀、1 条、10000ms、RSSI −128。
输出 `DiscoverySession` 表示 broker 会话 active，不是 Native Ready 或持续空口接收证明。
`DiscoveryReleased` 分别显示是否拿到最后一次物理 STOP 确认。
这是接口语法参考；新流程尚未形成已验收教程，所有实机操作继续 VM-only。

## 受控验收入口与限定范围

现有 `ws73_target.py run` 的 `--application-discovery-verify` 是维护者验收选择器，
要求显式两只设备、Native VM、
`--qmp-hotplug --connection-verify --connection-advertising negotiable-t`；可附同一
artifact 的普通 socket／长度边界保持门禁，不能混入独立故障、Agent 或 benchmark。
本线程还须通过端口白名单、序列号、占用与 SDK110 全套固件校验；选项不会放开这些限制。

连接保持必须复用 SDK110 封存记录中显式的 `negotiable-t` 条件。`fixed-t` 是未完成
连接资格的独立对照；默认值、发现成功或 Command Status0 都不能代替该条件。
不指定或选择 Fixed-T 时，本门禁在硬件启动前拒绝，不自动回退或改变模式。

VM 监督器按固定命令启动两个 UID/GID1004、无附加组和 capabilities 的实际
`slctl discover`，先等待双方 active，再允许另一只广播随机标识。第一个读者
只收一条并显式释放；第二个保留会话，接收原标识及第一个释放后的新标识，最后
显式释放。随后交换 scanner 角色。START／最终 STOP、两端 marker 数据和逐条
接收均由原 USB/HCC/DLI 校验器核对；同一 RX 可由两个会话观察，同一读者的不同
Native 序号不能反复借用一条捕获记录。缺失原始文件或失败不能由日志摘要补齐。

默认 `--application-discovery-case release` 保留上述显式释放流程。
`--application-discovery-case owner-loss` 则让两个reader保持等待，由VM内监督器
在实际收到报告后仅SIGKILL自己启动的child：先结束首名，确认同行收到新标识，
再结束同行。禁止用正常close、SIGTERM或管理STOP冒充caller消失。
最后一次SIGKILL后的五秒只是原清理期限的捕获窗口，不制造Off或成功收据；
必须独立捕获唯一START以及最后caller消失后的STOP和匹配Complete。
STOP还须早于两名caller原20秒租期可能到期的最早时刻，排除TTL清理混淆。
监督器退出、原始stdout或捕获缺失、晚STOP均不能通过。本选项尚待准确artifact实机验收。

监督器有环境预算，应用保留实际20秒租期；选中标识的交付另受原10秒门禁约束。
测试监督器退出不撤销已开始的物理义务。TTL、管理STOP、部分初始化、取消及
原期限交错是其他独立门禁，不能由显式release或受控SIGKILL切片替代。
**验收器离线检查不构成实机通过**；已执行轮次含整轮失败，显式release的正向切片
不替代其他退出条件。准确新镜像、完整system bus角色和原路径保持回归均以
[当前能力](../../project/current-capabilities.md)记录为准。

## C 与 Python 应用发现入口

这些入口复用同一 Rust `DiscoverySession`、Client caller 和 daemon 协调器，不创建
Native fd、扫描 Engine 或权限缓存。准确 artifact 的实机范围仍由当前能力入口维护。

| C 入口 | Python 对应 | 契约 |
| --- | --- | --- |
| `slk_client_discover` | `Client.discover` | 显式 controller identity，prefix 0–64 字节、RSSI −128…20、租期 250–60000 ms |
| `slk_discovery_identity` | `controller`、`session_id` | 不可变准入身份；不是扫描仍活跃、Ready 或清理证明 |
| `slk_discovery_read` | `read` | 每批至多32报告，单报告至多255数据字节；整批复制，不静默截断 |
| `slk_discovery_release` | `release` | 只释放自己的租约；返回 true 才表示 broker 确认最后租约的物理 STOP |
| `slk_discovery_free` | `close`／context exit | 仅释放本地引用，不返回或保证远端 STOP；未显式 release 时由 caller 消失或原租期清理 |

C 的 `flags` bit0 表示等待，bit1 表示 peek；其他位返回 EINVAL。
容量0–32，非零容量必须有有效输出区域。ENOBUFS 只写必需 count，保留整批；
其他错误不改输出。成功复制并消费，peek 保留。一个本地已收到的批次也在调用者
回复超时竞争中保留；尚未收到的远端 destructive read 则可能已消费，不能承诺无丢失。
`dropped` 与 `kernel_lost` 是已知丢弃观察，不是可靠交付保证。

Python 返回不可变 `DiscoveryBatch`／`DiscoveryReport` 值，未知 RSSI 为 `None`。
`read(wait=True, peek=False, deadline_ns=...)` 不另开后台 reader；同一 Client
有界执行器上的阻塞等待可能延迟其他调用。C 同一 view 的并行 read/release 返回
EAGAIN；Python 串行化调用。Client 可以先关闭，派生租约保留原 caller；跨 fork 使用拒绝。

所有调用沿用绝对 CLOCK_MONOTONIC 原期限（最多30秒，与 daemon 同 boot/time namespace），
包括本地排队。release 的超时或错误不能解释为已经 Off；底层 close 可能已经终结，
不得以重开或换 ID 重试来掩盖不确定结果。旧 owner、错 generation、过期 session 和非法
报告继续由原 Rust/broker 验证。C 任意坏地址或别名区域仍属于调用者违反指针契约，
与内核 syscall 的 EFAULT 测试不同。

新 C/Python artifact 的真实设备门禁须由独立 VM runner 与证据记录取得。
本源码切片只开放 SDK 与离线调用契约，不转授其他分支、历史 Rust 或本地 VM 的资格。
