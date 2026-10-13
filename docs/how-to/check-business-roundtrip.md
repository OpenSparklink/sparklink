# 核对两只 WS73 的业务往返证据

目标：从已经执行的 VM 测试中，判断双方应用是否实际交换并校验业务数据。
本任务只读取封存材料，不启动设备、不加载固件，也不安装服务。

## 前置条件

准备同一次运行的原始 run JSON、两端 USB pcap、capture-stats、VM console 和
manifest。记录内核、编译服务、测试工具的完整提交；三者可能不同。核对固件／
校准 hash，但不要把固件、受限标准或大型抓包复制到站点。
从[当前资格](../CURRENT_CAPABILITIES.md)选择准确运行记录；没有公开原始材料时，
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
6. 长度边界记录需保留原始拒绝载荷与 errno，并证明该载荷没有提交到 USB 数据路径。
   某个长度被正确拒绝，不表示该长度已支持。

## 结果检查与失败处理

必须区分应用校验、两端线上佐证、边界拒绝和仍未覆盖的场景。
核对器的 `long_pdu_acceptance`、`credit_exhaustion_acceptance`、
`four_device_acceptance` 为 false 时，不得由短消息成功扩展资格。
不匹配、缺少原始记录、丢包或来源不明时保留失败，停止传播 PASS；修正后使用新输出目录。
人工拔插、hub 切电和 QMP 操作记录为干预，不记作自然恢复。

[理解证据边界](../explanation/qualification-boundaries.md)、
[VM 输入准备](prepare-vm-gate.md)、[历史数据面规划](../DATA_SOCKET_VERTICAL_PLAN_20261012.md)。
