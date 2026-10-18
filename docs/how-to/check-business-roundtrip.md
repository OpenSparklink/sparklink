# 核对两只 WS73 的业务往返证据

目标：从已经执行的 VM 测试中，判断双方应用是否实际交换并校验业务数据。
本任务只读取封存材料，不启动设备、不加载固件，也不安装服务。

## 前置条件

准备同一次运行的原始 run JSON、两端 USB pcap、capture-stats、VM console 和
manifest。记录内核、编译服务、测试工具的完整提交；三者可能不同。核对固件／
校准 hash，但不要把固件、受限标准或大型抓包复制到站点。
从[当前资格](../../project/current-capabilities.md)选择准确运行记录；没有公开原始材料时，
只能审阅其摘要和 hash，不能声称自己复算通过。

## 操作

1. 核对 manifest 的源码、配置和产物身份；检查输入 hash。保留原文件，创建新的离线输出目录。
2. 检查 `channel_socket` 的两个阶段：独立 controller index、generation、非零
   connection lifetime；交换的是连接角色，不是给同一份日志换标签。
3. 核对双方应用 UID 与 capabilities、进程退出结果和原始标准输出。
   每轮必须同时存在 `NativeChannelSent`、`NativeChannelReceived`、
   `NativeChannelReply`、`NativeChannelRoundTrip`，随机 nonce／序号／载荷匹配，
   回复由对端实际校验产生，往返小于 10 秒。
4. 使用所选提交中的 `tools/ws73_channel_socket.py`：`application_frames(row)`
   校验原始应用记录，`corroborate(run, capture)` 对照已由
   `tools/ws73_capture.py` 解码的两端 USB/HCC/A3 与 CMTC 记录。
   这是内部 Python 核对函数，不是独立命令行；调用方式须与该提交 runner 一致。
   广播发现的 `ws73_north_star.py verify` 不能单独替代此业务检查。
5. 检查 capture-stats 的内核丢包、完整 console 的 panic／taint，以及两端数据
   归属和完成计数。NOCP 仅用于控制器完成记账，不能代替步骤 3 的应用回复。
6. 分别按bus/device/handle/方向重组DLI PB；保留每个原始包的record、USB hash和完成记录。
   长PDU必须对应有序first/middle/last TX片，每片遵守控制器包上限，重组字节精确匹配
   对端应用载荷。完整PDU大小、DTAP header、控制器包大小与应用大小分别记录。
   同handle的TX/RX不能共用一个重组缓存，link变更和原期限使旧片失效。
7. NOCP按实际提交的控制器片数计账，不能按应用消息数计算。它仍不能代替应用回复，
   也不能证明重复/晚到NOCP和复用屏障；没有实际压力门禁时credit耗尽资格保持false。
8. 边界拒绝按该提交的实际ChannelInfo MTU核对，保留原始载荷和EMSGSIZE，证明没有
   USB提交。历史249字节上限的250/253/254/255拒绝不继承为新镜像；新镜像接受它们时
   必须另有实际对端校验与回复，不能改写历史记录。

## 结果检查与失败处理

必须区分应用校验、两端线上佐证、边界拒绝和仍未覆盖的场景。
核对器的 `long_pdu_acceptance`、`credit_exhaustion_acceptance`、
`four_device_acceptance` 为 false 时，不得由短消息成功扩展资格。
不匹配、缺少原始记录、丢包或来源不明时保留失败，停止传播 PASS；修正后使用新输出目录。
人工拔插、hub 切电和 QMP 操作记录为干预，不记作自然恢复。

[理解证据边界](../explanation/qualification-boundaries.md)、
[VM 输入准备](../reference/vm-gate-inputs.md)、[历史数据面规划](../../history/connections/data-socket-vertical-plan-20261012.md)。


## 核对begun PDU最后fd关闭的隔离证据

此子门禁不要求已关闭源应用取得业务回复，不能计为源应用round trip。
使用对应提交的prefix-close记录，检查首USB提交早于关闭开始，随后真实源进程退出、
同lifetime重绑被拒绝，末片USB提交晚于协调器回收该进程的时间。
仅有local drop或固定延时不足以证明最后引用释放。

对端必须校验完整随机2042字节PDU并实际回复；未开始排队marker不得出现在USB。
检查原物理Session中关闭后的SMTC读写/发现/UUID及两端数据证据，不能用cached
ExchangeInfo或Ready日志代替同行业务。此结果仍不覆盖Managed撤权、断链、原期限
到达、真实credit耗尽或完整dup/fork/SCM_RIGHTS/linger组合。


## 区分软件队列背压与控制器credit

burst记录必须同时具有原始NativeBurstBlocked、对应NativeBurstResumed与summary，
至少一次EAGAIN后POLLOUT收回；恢复准入的每条消息仍需四份原始应用记录和两端USB。
检查两种连接角色各16个2042字节消息的nonce/序号、顺序、载荷和真实回复，不只计日志数量。
Root/kernel capture drops和taint仍需检查。

software_backpressure_acceptance为true不能覆盖credit_exhaustion_acceptance为false；
前者是有限软件队列，后者需另外观察真实controller budget、债务及实际完成的恢复。
没有该证据时保留未验收，不能将credit补满/模拟完成事件当作测试通过。


## 核对TX预算采样

现代runner要求`tx_status_required`并调用`tx_status_receipts`核对ready、burst blocked
及replied阶段的实际ioctl记录。先核对采样的controller／generation／lifetime／handle
与该阶段ChannelInfo，再检查connection debt≤outstanding≤peak≤capacity、queued+busy≤8，
以及该通道的active bytes／offset／flags。blocked时可同时出现软件队列满与硬件预算
仍有余量；replied时debt为0也是实际完成已经到达的合法观察。

对同一generation核对饱和peak／exhaustion单调性；跨重枚举不能比较计数。每个采样
只是瞬时快照，peak还包含回滚reservation。要验收硬件credit耗尽及完成后恢复，仍
必须核对真实提交／NOCP时间线和对端应用回复，不能只凭peak=capacity或日志数量。
旧封存记录没有此字段时保持历史范围，不补造采样，不将历史PASS升级为新门禁。
逐字段契约见[接口参考](../reference/interfaces.md)。


池满补充核对只读运行：

```sh
python3 tools/ws73_credit_observation.py --run-folder SAVED_VM_RUN --output NEW_REPORT.json
```

输入目录须包含原manifest、`guest-output/ws73.pcap`及原应用run JSON；输出必须是
新文件。核对器先复用现有两端应用／身份／USB核对，再要求两个角色的新池满拒绝、
满池快照、两端USB减NOCP债务始终不超容量且末尾归零，以及满→NOCP→再提交。
协商及SSAP包也纳入区间账，不把总包数描述成纯业务条数。旧manifest保持原范围；
补充报告记录其hash及限定假设。此检查仍不能证明NOCP硬件真实性、重复晚到、
复用屏障或自然恢复。

## 找到准确的历史练习材料

旧“读懂闭环”页属于测试人员核对证据的任务，不是操作设备的初学者教程。
原 Kae5b/U967 的 [40 轮短消息报告](../evidence/ws73-standard-driver-move-short-repeat-20261013.json)
和 [249 字节报告](../evidence/ws73-standard-driver-move-249-boundary-20261013.json)
在此直接保留入口，不要求从不断更新的当前资格页反查。原始材料不可取得时只能
审阅摘要与 hash，不能声称复算或重现。本页也不等于首次设备操作教程。


## 核对四设备两组业务记录

这是集成测试维护者的门禁；d01aa82已取得[首轮限定结果](../evidence/four-device-business-20261016.json)，
其他提交和配置必须重新核对，不能由历史结果继承资格。
前置条件是已冻结的 Native VM prepared 目录、四只另行授权且镜像来源合格的真实
WS73、原始捕获和普通用户工具。当前本线程只有两U和两E，混合下载未合格，且两组
其他端口属于另一线程，因此这里仅说明如何核对历史证据，不提供旧四口执行命令。
未来重新满足条件后，独立 `--four-device-business` 不与广播、QMP故障或双设备选项混用。

`application/parallel-business/run.json` 必须包含两组 worker、原始四只 Ready身份、
未变更daemon身份及所有有序pipe屏障。每组两种连接角色各20轮61字节业务，合计80次；
每条均复用四份实际应用记录和两端USB核对。`parallel-business-proofs.json` 的两个
角色阶段须各有真实业务区间交集，且交集位于两条物理连接的Up/Down内。

只在所有这些证据及捕获完整性/内核日志门禁通过时接受
`FOUR_DEVICE_PARALLEL_BUSINESS_PASS`。缺记录、无区间重叠、worker超时或本组清理失败
均保留FAIL，使用新输出目录重跑；不得手改产物或改用广播证据。
该结果仍不覆盖单组故障隔离、长包压力、公平性、动态多通道及非人工自动恢复。


## 核对受控单组断链期间的同行业务

集成门禁 `--four-device-disconnect` 在编译d01/工具ff13取得[限定结果](../evidence/four-device-disconnect-20261016.json)；
其他提交/配置不继承该资格。准备条件同四设备业务门禁，
使用独立输出目录并以此选项替换 `--four-device-business`，禁止二者混用。
它不暂停应用：两阶段轮换断链方，断链方4次、持续业务方20次，共48次实际回复。

核对 `disconnect_proofs` 两条记录：持续业务方至少2个完整往返早于对方Disconnect
实际USB提交，至少4个完整往返的首提交晚于对方两个真实Down事件；序号和原始包
都必须对应同一既存物理Session/Channel，应用实际校验回复且无daemon重启。
监督器完成状态应是 `FOUR_DEVICE_DISCONNECT_ISOLATION_PASS`，不能用旧80次
正向状态替代。时序不足、任一端Down缺失、同行换lifetime或缺少应用记录均失败。

`controlled_disconnect_isolation_acceptance` 只表达受控断链隔离，不能扩展为设备故障、
USB故障、物理拔插或自然恢复。普通用户与管理者的权限、长包和动态多通道仍单列。


## 核对四设备并行长包burst和预算

`--four-device-burst` 在编译d01/工具d42取得[限定结果](../evidence/four-device-burst-20261016.json)；
其他提交/配置不继承该资格。准备条件同上；当前资源不满足，不能复制旧四口命令
执行。未来具备条件时仍使用独立输出目录和唯一 four-device 选项，不能组合。

两组两角色各16次2042字节业务，共64次对端实际校验回复。核对两组USB区间重叠、
长PDU两端重组和有序DLI PB分片；每组每角色须保留真实软件队列阻塞/恢复记录。
`budget_observations` 对应每个原controller/generation/lifetime/handle，须有新池满
拒绝、实际NOCP后继续USB提交、最终debt0及提交/完成计数一致。

只有应用、包、身份、预算、捕获完整性和内核检查均完成，才接受
`FOUR_DEVICE_PARALLEL_BURST_PASS`。无池满/恢复、缺端点、丢包或未完成就保留失败，
使用新输出目录；不能用继承的peak或局部日志代替。预算观察不授予NOCP真实性、
重复/迟到/复用证明或公平性；`controller_credit_correctness_proof` 和
`fairness_acceptance` 均应保持false。完整设备故障和自然恢复仍单独验收。


## 核对动态通道关闭后的观察边界

新执行的 dynamic-burst v4 使用实际 Native Session 观测：先在 C 通道尚打开时
保留两端正对照，再从第一次 C close 前设定不可续期的 5 秒观察期限，最多 64 组
两端查询。仅在本轮所创建通道达到准确期望终态、队列/活动 PDU/debt/outstanding
和 pending flags 均为零时封存 C 的结束边界；超时、身份变化或查询失败均失败。
这段期限属于诊断观察，不延长原协商、发送或关闭期限。

随后仍运行原独立 USB/CMTC/NOCP 核对，要求真实提交与完成账目和对端应用回复。
快照不代替这一核对，也不证明 callback 排空或完成事件准确性。不要通过固定睡眠、
延伸抓包窗口或重跑覆盖失败取得 PASS；历史 v3 的末尾债务失败保留原边界和结果。
