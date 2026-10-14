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
[VM 输入准备](prepare-vm-gate.md)、[历史数据面规划](../../history/connections/data-socket-vertical-plan-20261012.md)。


## 核对begun PDU最后fd关闭的隔离证据

此子门禁不要求已关闭源应用取得业务回复，不能计为源应用round trip。
使用对应提交的prefix-close记录，检查首USB提交早于关闭开始，随后真实源进程退出、
同lifetime重绑被拒绝，末片USB提交晚于协调器回收该进程的时间。
仅有local drop或固定延时不足以证明最后引用释放。

对端必须校验完整随机2042字节PDU并实际回复；未开始排队marker不得出现在USB。
检查原物理Session中关闭后的SMTC读写/发现/UUID及两端数据证据，不能用cached
ExchangeInfo或Ready日志代替同行业务。此结果仍不覆盖Managed撤权、断链、原期限
到达、真实credit耗尽或完整dup/fork/SCM_RIGHTS/linger组合。
