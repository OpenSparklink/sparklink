# Socket benchmark 指标与报告契约

适用：ADR0006 的规划契约；目前没有当前 HEAD 的性能资格。首个 ping-pong 工具切片见
[操作指南](../how-to/measure-socket-ping-pong.md)；固定速率/窗口/双向的应用循环及限定
Native 双端证据闭包已接通，完整性能门禁仍缺。准确构建与结果见唯一资格入口。
历史 channel-roundtrip／burst 与当前 slktest --check 是功能门禁，计时包含日志等开销，不能升级为基线。
[接口支持范围](interfaces.md)继续适用；此页不新增 socket 能力。

## 负载与时间

| 模式 | 负载约束 | 主要测量 |
|---|---|---|
| ping-pong | 一个未完成请求；实际对端校验并回复 | 同一发起者单调时钟应用 RTT |
| fixed-rate | 按绝对计划时刻发起；过载不推迟整个计划 | 排队/准入/拒绝、丢失、超时、迟到 |
| throughput / bidirectional | 明确每方向有限窗口、队列、持续时间 | 实际校验业务 goodput 与背压 |

每条记录独立的随机序号/载荷、计划时刻、syscall 开始、成功软件准入/errno、回复
读取及校验结果。准入不是 USB 发送，未知的时间必须 null，不能用 syscall 返回
冒充 USB submit。RTT 起点明确；成功样本分位数只覆盖成功样本，失败/未完成另列。
超时仍保留记录并观察迟到；重复、乱序、损坏单列。发端随机输入计时前准备，
对端真实校验，保留可核对的接收/回复记录。证据有界、不逐包输出或同步落盘。

## 报告字段与单位

schema 版本、run id、源角色及 controller/generation/lifetime/channel 身份；
编译源码/dirty 指纹、artifact、执行工具、报告提交分开。记录实际 SDK 版本及主固件、
两份校准的 hash；本线程按资源策略使用 SDK110 和明确的 E／US 板型，不能将历史
SDK111 结果转授新固件或混合型号。记录
两端连接角色/参数/PHY/MTU/MPS/PDU/分片、VM/QEMU/CPU/USB 拓扑、捕获和队列配置。
请求参数与实际生效参数分开；不能取得的值标 unknown 和剩余条件。

- ns：同域单调时间，独立标 clock domain；跨 host/guest 时间须映射与误差界。
- 时延：n、min、P50/P90/P95/P99、max；P99.9 至少 10000 个成功样本且明确尾部样本
  仅 10 个，样本不足置 null，不插值伪造精度。分位数算法固定并记录。
- bytes/s、messages/s：计划负载、准入、USB 字节与对端实际校验业务 goodput 分列；
  实际 PDU/HCC/USB 开销另列，USB 流量不是业务 goodput。
- 正确性：计划/尝试/准入/对端校验/回复、拒绝(errno)、超时、迟到、丢失、重复、
  乱序、损坏、未完成，所有尝试保留；缺任一必要输入不生成完整 PASS。
- 资源：CPU、RSS、fd、worker、timer、URB、各层队列/credit 峰值及结束后的收敛；
  未测项保持 null。完整 trace 与低扰动测量分运行，量化观测开销。

时间线：应用计划→syscall/准入→Session 出队→credit/Ticket→USB submit/complete→
对端 USB RX→Session 分流→应用读取/校验→回复；NOCP 独立。无 RF 观测时，中间
区间写作包含固件/调度/无线的合并区间，不能宣称独立空口时延。

## Fail-closed 与版本边界

删除对端记录、捕获缺失/掉包、截断日志、身份/hash 不符、payload 修改、重复序号、
漏超时、旧结果贴新源码、supervisor 异常退出/SKIP、必要场景缺失、单位或起点错误、
时钟混用和空样本必须由负对照拒绝。保留原失败及最小回归；无崩溃不是证明。
只测量的诊断报告可保留，但不完整不得成为性能资格 PASS。

正常资格、性能、sanitizer/lockdep 镜像独立，不能放宽原协议期限。基线稳定后才按
相同配置设回归阈值，环境或特殊调优变更独立报告；所有 WS73 操作 VM-only。


## 当前 CLI 参数与 schema2 边界

`--security`默认0；非零1/2仅用于固定`ping|peer --check`正确性，经同一普通授权fd
验证当前机制与冻结epoch。测量模式及动态路由明确拒绝非零要求，不降级或沿用普通
测量的资格；本页性能报告schema不变。具体等级、失效和资格见[接口契约](interfaces.md)。

| 命令 | 路径后的位置参数 | 行为 |
|---|---|---|
| slktest channel ping / peer | CONNECTION --count N --bytes B --report FILE | schema1，单未完成请求／校验回复 |
| slktest channel rate | CONNECTION --count N --bytes B --window W --interval-us U --report FILE | schema2，绝对计划 |
| slktest channel window | CONNECTION --count N --bytes B --window W --report FILE | schema2，有限应用窗口 |
| slktest channel duplex | CONNECTION --count N --bytes B --window W --report FILE | schema2，两端独立发起/应答 |
| slktest channel peer --load | CONNECTION --count N --bytes B --window W --report FILE | schema2，应答rate/window |


count 1..10000，bytes 29..2042 且匹配实际通道 MTU/MPS。window 1..min(count,256)，
interval 10..1000000 µs，总计划不超过600秒；其它模式 interval 为0。schema2 等待
原30秒 `start\n` 屏障，消息原10秒期限，1秒尾部观察，测量循环上限612秒。
循环结束输出Quiescent，双方到达后监督器各发 `finish\n`，结束等待另有原30秒预算；
fd保持到结束授权，hex/JSON在其后生成。该预算不续消息期限，最终失败不覆盖原循环错误。测试中的
较短 AF_UNIX 期限是显式 fixture 参数，不替代真实模式常量或协议期限。

`outgoing` 全量保留计划/dispatch、首次及成功 syscall、准入、原 deadline、read、
校验、尝试/EAGAIN、errno、本地预算拒绝、超时、迟到及 reply_count。固定速率
即使未尝试也保留原计划。`incoming` 保留实际本地校验与回复准入时间；未知或
错误不能伪造成功行。counter 区分重复请求/回复、乱序、损坏、未知/非预期包、
记录和 reply 队列溢出；接收观测最多 count×4+16 包，达到预算后失败退出。

每轮 32 包预算，各应用队列预留容量，热循环无日志/hex/落盘，无全记录扫描；
逾期检查和最早期限查询仅遍历有限窗口。通知不映射协议 credit；应用超时释放
应用等待预算，不抹去内核或控制器的在途义务。

report 的 correctness 只是单个应用的限定检查。CPU user/system delta、RSS/fd 是
进程端点快照，含采样端点开销，maxrss 是进程 lifetime，不是本次峰值；内核资源
与 USB 字节率仍 null。每秒率分母 active_elapsed_ns 包含失败/超时，排除1秒尾窗；
pattern goodput 排除29字节应用测试头，datagram goodput另列；DLI/DTAP/HCC/USB
开销未取得时不得补猜。完整追踪与低扰动差值仍未测量。

schema1 双端核对含迟到拒绝；schema2 已有独立应用报告核对（载荷/方向/
逐消息期限/计数/分位数/goodput/进程端点/结束屏障结果）。它拒绝失败或缺字段
取得完整一致结果；原诊断报告仍保留。独立 Native 监督入口另核对来源/捕获/屏障，
不能把应用层一致直接当 Native 资格。限定真实 WS73 低负载闭包不等于完整性能资格。


## 工具所有权与迁移

`slktest` 是应用测试的唯一规范入口，使用内部库中的同一套旧 channel/benchmark
实现；`slctl` 不再接受旧测试命令，负责管理、连接、授权和日常交互。--adapter
必须给出当前完整对象路径，与 CONNECTION 的 generation/lifetime 一起核对。
`ping/peer --check` 保留原正确性门禁和 stdout receipts；测量不加 --check 且须 --report。
--exercise boundaries/prefix-close/burst 保留原约束；动态 --check 提供完整的
--source-port/--destination-port/--aid，--hold 仍等显式close。
动态正确性可选 `--start-barrier`：真实协商和能力/授权核对后输出
`NativeDynamicArmed: count=N bytes=B`，复用已有输入解析器等待精确 `start\n`，
原期限30秒，部分输入不续期、EOF撤回；等待期间不开始业务循环。该应用启动等待
不延长内核协商、队列或已准入PDU的原期限，不授予credit/Ready。固定CUTC和测量
入口拒绝此参数；默认行为不变，随机载荷与收发仍用同一正确性实现。

### 动态 basic 负载：实现入口与未验收边界

`rate`、`window`、`duplex` 与 `peer --load` 可同时指定三个非零 u16 路由参数
`--source-port`、`--destination-port`、`--aid`，并必须显式给出
`--channel-role active|passive`。两端源／目的端口互换、AID 相同，协商角色一主动
一被动；业务发起／应答、duplex 方向和物理连接角色与这个协商角色独立。
未指定路由仍使用基本 CUTC；缺字段、零值、单独角色、动态 schema1 ping 或
protected 动态测量都明确拒绝。旧 `--check` 继续从 ping／peer 推导协商角色，
拒绝该新增角色参数，原 stdout 契约不变。

复用现有应用 SDK `PrepareDynamicChannel` 和同一负载循环。请求 MTU 为
`max(bytes,249)`、MPS 为 MTU+5、SLQI 为1；这些是请求预算，不是已生效能力。
实际 fd 必须报告 basic／双向、PI241、两个动态 TCID（0x80..0xdf）、当前身份和
足够的 MTU/MPS，且不能超过请求预算。端口／AID 不是 TCID、身份或认证。

动态 schema2 新增可选 `channel_request`，仅记录原请求：version1、
kind=`dynamic_basic`、source_port、destination_port、aid、mtu、mps、slqi、passive。
`channel_identity` 仍取实际 fd。核对器要求两份请求同时出现、路由互补及实际
local／remote TCID 交叉一致；不能删除 tag 将动态结果降为普通 CUTC。基本 CUTC
报告不增加该字段，历史报告身份不变。业务记录、计时、失败记账和 schema 版本不变。

创建 fd 后、等待协商 Ready 前输出 `SocketBenchmarkStaged`。监督器需要先启动
被动端并收到该标记，再启动主动端；双端仍须实际 Armed 后统一 start、Quiescent
后统一 finish。Staged 只表示完成本地 fd 准备，不授予 Ready、credit 或对端存在。
新入口的真实设备资格单独登记，不能继承原基本 CUTC。Native benchmark runner
以 `--channel-benchmark-dynamic` 选择版本1目标：协议端口24576／24577、AID29441；
可用 `--channel-benchmark-active-endpoint 0|1` 指定独立的协商主动端，动态模式默认0。
未选动态时不接受主动端参数，原基本 CUTC 默认行为不变。目标跟随原连接拥有者
顺序，物理连接交换角色时不按 USB 枚举顺序重新选择设备。复用原普通应用监督器，
逐端记录实际 Staged、双端 Armed／start／Quiescent／finish，以及准确工具来源。
host 请求、guest cmdline、控制角色、Root 请求和终态证据必须一致，不允许删 tag 降级。
独立捕获门禁核对 CMTC 请求／回复、实际端口和能力，再核对
动态 TCID 上的双端 USB 与应用回复；新运行同时要求原追踪与进程检查点契约。
缺任一必要信令／对端数据、过早 Ready、错角色／路由或重复证据都失败。
本地 AF_UNIX 报告只能检验循环／序列化和
拒绝行为，不能替代这项实机门禁或完整多通道公平性／性能资格。

### 四应用、双动态通道的有限负载

专项 VM runner 的 `--channel-benchmark-parallel` 与单通道 `--channel-benchmark-dynamic`
互斥，要求 `--channel-benchmark window` 的默认主负载。版本2目标显式包含两组：

| 通道 | 协议端口 | AID | 每连接角色请求数 | 应用字节 | 应用窗口 |
|---|---|---|---|---|---|
| short | 24576／24577 | 29441 | 20 | 61 | 4 |
| long | 24578／24579 | 29441 | 16 | 2042 | 8 |

同一物理连接、每 controller 唯一 Session；四个普通应用复用同一 schema2 循环和
原监督器。`--channel-benchmark-active-endpoint 0|1` 同时选择两条通道的协商主动端，
不改变业务请求方向。先暂存每条通道的被动端，再启动对应主动端；全部四端 Armed
后才能释放任何 start，全部四端 Quiescent 后才能释放任何 finish。长负载先收到
start，仍须以捕获证明实际交叠，不能从释放顺序推导公平性。

请求目标、启动参数、Root 准入、执行工具及终态必须一致。应用报告仍是原 schema2，
没有新增业务 Engine。监督摘要版本2要求两连接角色共八个应用报告和检查点；旧版本1
四报告不能代替。逐通道核对原 CMTC 路由／能力、独立实际 TCID、随机业务及两端
USB；长消息须取得实际 PB 分片。复用既有短／长捕获判据，要求两个方向均有短 PDU
在长发送流期间完成。缺任一通道、原期限超时、证据重复／错投、分片交错或无实际
进展均失败。完整两角色共72次校验回复只是这项有限闭包，不能宣称稳定性能、完整
公平性、单通道关闭隔离、credit 真值或四只物理设备资格。

#### 版本3：短通道关闭期间长通道继续业务

在上述命令显式追加 `--channel-benchmark-close-short`，选择独立版本3目标；short仍为
20×61／窗口4，long改为64×2042／窗口8。四端全局Armed→start保持不变；short两端
均Quiescent后才分别finish并回收进程，long两端均Quiescent后再finish。每端原30秒
控制等待及消息期限不变，620秒业务监督预算不因短通道关闭续期。版本2仍要求四端
全局Quiescent后才finish，不能用版本3记录改写历史资格。

复用同一Root、普通应用UID1004、授权SDK、schema2收发循环与报告；没有新增协议
Engine。监督摘要为版本3。原始双端USB须有真实CMTC关闭交换，且long完整随机
请求／对端校验回复在短通道关闭前、关闭交换完成及短端进程退出后均存在。进入
本地队列、Root标记或NOCP不能代替。两连接角色完整负载为168次校验回复，缺任一
关闭后业务即失败。原应用开始／结束资源检查点按各自通道的双端屏障核对。

这是关闭隔离的有限正确性负载。短应用在长负载运行期间写报告和退出，会产生
观测及资源回收开销，不能当作原全局静止后写报告的低扰动性能基线。该入口不授予
完整公平性、引用／callback排空、安全复用、NOCP真值、自然恢复或稳定性能资格。

代码迁移不改 schema1/2、wire、socket/Grant/credit/Ticket 或原期限。历史证据中的
slctl 命令和 artifact/hash 保持不动，由原提交工具复核；当前 verifier 的旧 argv 分支
仅解读历史记录，不是运行时兼容入口。新 binary/runner/报告来源和实机资格单独登记。


schema2 的 `finalization` 为新增必要字段：completed、原 budget_ns、elapsed_ns、error；
CLI预算为30秒，显式本地fixture为1秒。旧schema2报告保持原身份，缺此字段不能授予
当前结束屏障资格，不另改schema版本。核对器支持rate/peer、window/peer或duplex/duplex，
允许方向交换；只在各进程的时间域内运算。应用报告核对不证明监督器确实等待双方，
该事实必须与实际输入/输出时序及artifact/capture一起单独核验。


## Native VM 首批监督入口

现有 `ws73_target.py run` 增加独立 `--channel-benchmark rate|window|duplex`，
须配合真实两设备 `--qmp-hotplug --connection-verify --connection-advertising negotiable-t`。
与 `--channel-socket-verify`、动态通道、Agent、外部probe、resync和四设备门禁分开运行；
不在已关闭CUTC的同lifetime重新绑定。默认每连接角色20条61字节、窗口4，rate间隔100ms；两种连接角色各新建一次连接。应用/管理仍使用各自的slktest/slctl二进制。

监督器保留实际进程凭据、启动及结束IO顺序、完整原始报告/hash/stdout/stderr；
大规模报告写出前双方先Quiescent。host和guest复用已有捕获校验，独立逐条匹配
请求与校验回复的USB TX/对端RX，并拒绝缺失、重复或无法归属的CUTC业务包。
真实运行状态及准确资格由唯一能力入口记录；建立入口/合成fixture通过不代表实机通过。
20条样本不是稳定性能阈值，完整追踪的干扰、分段时钟映射、资源峰值及长期压测仍需另验。

这里的“动态通道门禁分开”指原 `--dynamic-channel-verify` 正确性矩阵；动态测量使用
上述独立目标参数，不能同时打开旧矩阵或把旧正确性资格视为新测量结果。

## 单 bulk RX URB 空窗诊断

`tools/ws73_rx_gap.py RUN_DIRECTORY` 只读已有 Native benchmark 的 manifest、双端
应用报告、监督器记录、guest usbmon pcap 和停止后的捕获统计；不接触设备。
它先重放原双端业务证据，再在每连接角色的 start→双方 Quiescent 区间，分别按
guest bus/device/URB 配对完成和下一次提交。原捕获解析默认行为不变，诊断显式
请求 IN 提交元数据。缺提交、错身份、重叠 URB、倒序、区间内错误、捕获掉包或
业务重放不一致都拒绝；窗口末尾尚无重提交的完成单列为右删失，不能补造零空窗。

输出 ns 的样本数、min/P50/P95/P99/max、完成字节数、捕获记录/偏移及窗口空窗
占比，时间戳量化为1 µs。空窗包含 callback、USB core 和 VM 调度，不是 callback
CPU 时间，也不隔离固件或 RF。低负载样本不能证明饱和接收能力或多 URB 的收益；
解析/ingress/锁竞争分段、突发负载及低扰动对照仍需另测。该工具不改变接收顺序、
generation、buffer 或 stop/drain，也不产生新的驱动、形式化或性能资格。


## 窗口1与xHCI观测对照

Native监督入口支持`--channel-benchmark-window 1|4`，默认4；1保持每应用最多一条
尚未收到校验回复的请求。两端CLI argv、Armed、schema2配置、guest cmdline与host
请求必须一致；仍固定20条61字节、两种物理连接角色。复用原应用循环与报告，不
新增wire Engine，也不把软件窗口解释为协议credit。

`--channel-benchmark-xhci on|off`只在该专项benchmark有效，默认on。仅在私有VM
内开关既有xHCI事件追踪及全局tracing_on；usbmon、双端业务、来源和完整捕获
断言保持。启动/封存读回、每boot UUID、on的前后标记与实际事件、off的空记录、
CPU0/1零丢失及trace条数必须一致。请求KiB与实际分配分别保存；按捕获的
header_page有效载荷、subbuffer大小及该内核DIV_ROUND_UP/读回KiB取整精确核对，
不能假设请求1024就读回1024，也不接受任意容量容差。缺文件、错误配置、丢失或截断拒绝。这个对照
只测xHCI追踪的增量影响，off仍有usbmon/QEMU等观测开销，不叫“无观测开销”。

`tools/ws73_benchmark_timeline.py RUN_DIRECTORY`只读重放原双端证明，输出每条请求
的OUT提交/完成、对端首/末片RX、对端回复OUT及源端首/末片RX间隔和原record索引。
分片 TX 使用原重组证明的首片提交作为起点，全部片的最后 USB 完成为完成点；另记
首末提交跨度及末片提交到对端完整 RX 的区间。检查每片身份、PB 顺序、时间及自身
完成，不把最后一片时间误作整条消息的发送起点。单片旧结果的字段含义保持原样。
61字节应用消息也可由SDK111分成28/28/10字节RX，必须沿原DLI PB重组证明处理，
不能假定短包单片。应用自己的单调时钟RTT/准入和guest usbmon墙钟间隔分开，
不跨时钟相减，不用RTT/2。OUT完成允许晚于对端IN，不表示协议credit归还。

NOCP单独保留handle/count事件，不擅自归给某条消息，也不作为业务交付。USB到
对端USB区间包含USB/固件/无线/VM；首末RX差含多层调度，不是纯RF分片时延。
该工具仅输出完整成功原运行的观测；失败运行仍保留原结果、不得从完整尝试清单
删除。样本量、扰动、资源峰值、饱和/公平性及所有旧未决资格继续由唯一能力入口
记录；时间线和配置开关建立不等于取得新artifact的实机或完整性能资格。


## Session 服务记录的限定关联

`--session-service-observe` 仅在显式 Native 数据门禁启用。采集器要求 VM root、
scratch 标识、QEMU DMI 和显式内核参数，禁止配置宿主 trace。独立实例使用 nop、
mono 时钟、请求每 CPU 2048 KiB 并按实际 page layout 精确核对读回。两个 CPU 的
零丢失计数、原始条数、唯一 begin/end、boot UUID 和原件 hash 都需闭合。

work 的 begin/end 配对实际 Session 服务编号；queue 区分软件准入、出队和操作
退休，保留原期限。尚未提交且 EAGAIN 的重新入队保留每次出队，不解释为重复
准入。tx 的 Native 调用开始、同步返回与实际提交回调分别关联；只有回调 result=0
是 USB 队列接受。已接受但同步返回失败仍列为不确定义务，不能算完整 PDU 或退款。
每轮八次/4096 字节是数据尝试预算；2 ms 仅在下一次调用前检查，不是整轮 WCET。

双方 controller/generation/lifetime 取自原普通应用收据，Managed 门禁另核对 epoch。
固定 CMTC 与数据的实际接受数、PB/长度和顺序须匹配原 USB OUT；PB 序列不能混入
其他操作。时钟映射只使用两次 guest realtime/monotonic 采样的共同偏移区间，含
trace 量化误差；无交集即拒绝，不伪造跨时钟精确点值。未记录的动态 CMTC 分支
显式排除，不能将该采集器泛化为所有通道的完整追踪。

`REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED` 只表示这些观测相互一致。
完整原业务门禁仍必需；它不是 USB 完成、NOCP、对端交付、纯 RF 时延、信用守恒、
并发证明或性能资格。进程异常、边界未封存、未知事件与缺少阶段均失败；不把
ABORTED/RUNNING 当作合格报告。

首轮 1 MiB/CPU 的真实长包 burst 采集曾覆盖 9147 条，整轮 FAIL 保留；按实际
25188 条记录调整为 2 MiB/CPU，仍严格检查零丢失与最多 8 MiB 的文本原件。
该容量是本诊断的预算，不改变应用队列、credit 或协议期限；超过预算仍拒绝。


## 并发短包／长包的限定进展门禁

`ws73_target.py run --channel-fairness-verify` 要求独立真实双设备、connection 与固定
socket baseline 门禁；不能与动态旧矩阵、Agent、prefix-close、burst、边界检查、
Session trace 或其它专项混跑。它复用 `slktest --check`、唯一物理Session与动态通道，
两种连接角色各短20轮61字节及长16轮2042字节，四个普通用户端点协商后全部Armed
才逐一放行。每次stdin写入记录前后guest墙钟，原件保留实际凭据、pid、argv、stdout。

USB核对要求真实CMTC、不同且交叉匹配TCID、随机对端校验回复、长包连续PB与
软件队列背压；每个方向的短PDU必须在长TX流首末之间取得进展，缺重叠即拒绝。
协议解析仍来自现有捕获设施，未增加另一Engine。`full_fairness_acceptance=false`：
有限工作量的交错进展不证明所有已准入队列的饥饿上界、强公平、精确时延或性能。
原尺寸/credit/撤权/SSAP/四设备资格不由新参数推断，准确编译/执行身份另行验收。


## Native VM 可变负载请求

`--channel-benchmark-count` 为每发起端、每连接角色的请求数（1..10000，默认20）；
`--channel-benchmark-bytes` 为包含29字节测试头的应用 datagram 长度（29..2042，默认61）。
实际 Channel MTU 仍在应用启动时检查，超限拒绝，不截断。`--channel-benchmark-window`
为应用等待校验回复的预算（1..min(count,256)，默认4），与协议 credit 分开。
`--channel-benchmark-interval-us` 仅 rate 模式取10..1000000微秒，默认100000；
count×interval 不超过600秒。其它模式只接受0，省略时自动取0。

Host、guest cmdline、控制器监督器、实际 slktest argv、两端 schema2 和结果核对使用
相同完整配置；任一数值、类型或物理角色不一致均失败。未选择 benchmark 时拒绝负载
选项。schema2、收发循环、原30秒屏障/10秒消息期限/1秒尾窗/30秒结束期限不变。
历史默认20/61及窗口1/4的封存记录按原身份解读，新请求将完整配置写入 manifest。

新范围是工具能力，不由参数验证推出实机或性能资格。固定速率过载时的失败与原始
报告仍须保留；当前 Native 正向核对要求所有请求实际回复，不能将诊断失败改成完整
性能 PASS。10000条的上限不代表该配置已完成压力、捕获容量或资源资格。


## 接收机制正确性检查

`slktest channel ping|peer ... --check --message-security [--security 0|1|2]`
复用原随机载荷校验/回复循环，逐条核对真实recvmsg上下文与原fd身份、KNOWN/CURRENT
和最低机制，并测试发送control的明确EOPNOTSUPP及随机拒绝载荷未进入USB。
只支持固定CUTC regular/boundaries正确性门禁；动态、burst/prefix-close及性能报告
模式明确拒绝该选项。当前VM runner新固定regular/boundaries记录要求这些原始收据；
旧报告不增加新资格。新版本应答端将原RX上下文带到受约束响应发送；每轮分别
测试旧epoch、旧lifetime及过期期限的真实拒绝及对应载荷无USB。正常响应使用一次
确定的原期限；不增加收发循环或协议Engine。此检查不是属性级授权、完整密码证明
或性能资格。

## RX 重提交观测契约

`ws73_rx_gap.py RUN`仅接受原完整成功门禁。独立的`--failed-phase 0|1`只接受
QEMU正常退出且控制测试流程、指定阶段均为FAIL的原件；阶段快照必须明确
`success=false`，原始请求、owner与配置匹配，文件清单／长度／hash和零丢包捕获完整。
成功和失败快照校验入口互斥；失败诊断不能生成成功门禁回执。

失败诊断覆盖所有应用实际start至原阶段end，输出原FAIL、原错误、请求／控制／快照／
捕获hash及两个独立端点的样本。它不补造未完成应用报告、quiescent、清理或第二角色。
`window_fraction_without_submitted_rx`只统计已配对完成的间隔；边缘未闭合样本另列，
不能把被截取部分当作零。completion→submit含callback、USB core与VM调度，
不等于callback CPU、完整硬件无URB区间或独立RF时延。诊断退出0只表示取得限定
观测，不能解释为原业务通过或多URB优化收益。

结构化报告若声明`qualification.level`，摘要必须保持同一证据等级；不能只改标签把
`offline`改成`real_device`。私有原件不可取得的元数据检查仍不是本地字节复核。

新准备产物的 `benchmark_trace_contract_version=1` 显式选择 ftrace `mono`，
在开始与结束分别保存并校验时钟 readback。Root 监督器在应用 `start` 前、双方
`Quiescent` 后写入本 boot cookie 和 phase 的固定 marker；写标记及读取配置均
在应用计时热循环之外。两个连接角色各有一对 marker，不能跨 boot 或 phase 配对。
旧捕获缺少这些材料时仍可按原契约重放，但不能获得此 RX 间隔资格。

`tools/ws73_benchmark_timeline.py RUN` 复用双端 schema2／USB 校验，再对开启追踪
的业务区间输出 `rx_resubmit_observation`。当前固定驱动的 bulk IN 请求容量为
20480 字节；每个端点、每个 phase 只接受一个观察到的 URB 身份。重复提交、重复
完成、区间内取消、指针混用、时间倒序或缺失端点会拒绝该间隔结果。首个完成可能
对应区间开始前的提交；末尾提交／完成可能尚未配对，分别计为 censored，不补造样本。
空完成单列；每个样本保留原时间及文本时间戳分辨率，不把量化后的零解释为零开销。

该数值是 **xHCI giveback 事件到下一次 enqueue 入口事件** 的观测间隔。前者在
USB core 分派 callback 前，后者在 HCD 加锁和实际入队前，并仍可能提交失败。
它包含 USB core 分派、callback 处理及部分重新提交准备，不能描述为精确 callback
耗时、完整的硬件无 URB 空窗或 RF 时延。generation／lifetime 来自已经独立校验的
本轮连接身份，trace 本身没有这些标签，也不证明引用排空或全部并发交错。

追踪关闭时输出 `NOT_OBSERVED_TRACE_OFF`，没有 RX 间隔样本。重复试验按 run 和
物理源方向分别报告，保留所有失败和未完成尝试；追踪开关比较仍包含 usbmon 开销，
不能升级为零观测开销、稳定性能阈值或多 URB 优化收益。源码、准确资格与剩余条件
仍由唯一能力入口记录。

## VM 应用进程资源检查点

新 Native benchmark 准备产物使用 `benchmark_process_resource_contract_version=1`。
既有 Root 监督器在双方 armed 后、写入任一 start 前读取两只实际 `slktest` 子进程，
在双方 quiescent 后、写入任一 finish 前再次读取。热循环内不增加采样线程或磁盘写入；
普通 CLI 的 schema2 应用报告和业务收发不变。

原始 `/proc` stat/status、fd 编号、可执行文件身份和单调时钟读取区间随既有 Root
phase receipt 封存。校验 PID、父进程、start tick、UID/GID1004、空附加组、零能力及
实际 executable；旧 PID 复用、计数回退、单位错误、缺失／超限或跨越业务屏障均失败。
新 live 入口要求新 proof 及准确 helper 来源，历史捕获不能补字段升级资格。

- CPU 记录 user/system tick 差和实际 `SC_CLK_TCK`，不是纳秒精度的逐消息耗时。
- Linux status 的 `kB` 按1024字节转换。VmHWM／VmPeak 是截至读取时的进程高水位，
  包含载荷预生成与准备，不能称为纯业务区间或进程退出时的最终峰值。
- RSS 和 fd 数量是两个检查点的快照；fd 相同不证明没有中间峰值或引用泄漏。
- 这些数据不覆盖 daemon、整个 VM／宿主、内核对象、worker、timer、URB、队列或 credit
  峰值，不授予性能阈值、完整压力、公平性、资源收敛或恢复资格。

时间线的 `process_resource_observations` 保留每 phase／每应用的独立结果。
观测开销和功能正确性仍需按准确产物分别验收；未测量的其他层资源保持缺失。

## Session 入队与提交时间

对已有 `--session-service-observe` 的成功 Native benchmark 捕获，可只读执行：

```sh
python3 tools/ws73_session_service.py analyze-benchmark RUN_DIRECTORY
```

该入口先重放原双端应用、角色、屏障、捕获及 USB 门禁，再重放原 Session 追踪校验。
原门禁失败、trace 丢失、缺少阶段、身份不符、USB 顺序或时间不符均拒绝输出完整结果。
分析不操作设备，不改原 manifest，不为旧 artifact 添加新功能资格；分析器与执行工具的
源码身份须分别记录。默认生产路径不启用该追踪。

每个操作保留 controller／generation／lifetime／epoch、slot、入队观察序号、DTAP
字节数、原 jiffies 期限及各阶段的单调时间。观察序号不是应用序号；仅通过原 USB
fragment record 的完整有序匹配关联业务 phase、源方向、请求／回复和应用序号。
建链后的其他受控通道数据保留为未关联业务，不能冒充 benchmark 请求。

- 入队到出队、首次尝试、首次原子接受分别记录；本地退休不是对端交付。
- 每次同步调用返回及实际接受分开；不确定失败仍保留已经接受的 USB 义务。
- 分片接受跨度、重试间隔和 worker 预算分开。`wait=credit` 是 Native 返回的原因，
  不是独立验证的控制器 credit 真值；其后到下一次尝试的间隔也含调度及其他工作。
- 时间差给出原观测值与按 trace 分辨率计算的上下界。量化后的零不能称为零耗时。
  jiffies 期限不当作纳秒，未取得首次接受时保持 null，不补零。

这些观测不能隔离固件、RF 或 USB 延迟，不证明 NOCP 准确性、完整 credit 守恒、
引用排空、公平性或性能阈值。需要优化时，应先定位等待段，再用准确新 artifact
重新验收原业务及相关生命周期门禁。

动态 CMTC 的建立、回复和关闭也须进入同一提交观测命名空间，分别记录尝试、
实际 Runtime／Ticket consent 结果及同步返回。成功 USB 接受必须有对应 consent；
失败 consent 不能作为成功提交。核对器仍要求记录身份上的全部已接受 USB 包与
trace 逐项对应，不因它是动态信令而过滤。新记录按实际匹配的 CMTC envelope
说明覆盖范围；旧基本通道记录保留原 scope 与源码身份。观测覆盖不证明协商成功、
硬件 credit 真值或对端交付，这些仍由各自原门禁核对。

控制面失败后，可以只读核对已闭合的应用快照及同一份 CMTC／载荷匹配结果；
这类诊断使用独立的 `DIAGNOSTIC_CLOSED_PAYLOAD_COMPONENT_ONLY` 状态，明确
`overall_run_acceptance=false`。它不补造缺失的 daemon-after 观察，不恢复 Ready，
不放宽原 Down 期限，也不授完整连接生命周期、追踪或整轮资格。正常验收入口仍
要求原控制角色完成和真实 daemon-after 身份；终态核对器拒绝将诊断状态当作成功。

## 动态通道与 Owned SSAP 并发正确性

显式 `--channel-benchmark-ssap-owned` 要求 `window`、`--channel-benchmark-dynamic`、
128条／2042字节／窗口8，以及原动态端点角色0或1。它与 parallel、close、rate、
duplex 和安全 Agent 场景分开，当前要求预先冻结的 SSAP `channel_security=0`；
本地 Owned 审批不能描述为认证、加密或 Bond。新 prepared 必须声明
`benchmark_ssap_contract_version=1`，boot、原请求、helper、C／Python消费者及
SDK库均按准确输入绑定。旧 benchmark 不因新标识取得服务并发资格。

每连接角色仍由两个 UID1004／空附加组／零能力的实际 slktest 进程完成128条长消息
校验回复；同一 Session 的两个 UID1005 Owned 服务，由现有 C／Python客户端以
UID1004执行四轮、两个方向的读／写／读。管理 UID1000 只承担原有发现／UUID观察。
两个连接角色共256次通道往返、48次 SDK 读写调用、16个值周期及80个实际审批；
Owner 本地值检查、真实收据、源文件关闭与退出仍必须完整。

原全端 Armed→start／Quiescent→finish 屏障和原始期限不变。监督器在业务期间执行
真实 SDK／审批和证据写入，因此它是正确性负载，不能作为低扰动性能基线。
接收和业务发送继续使用原 Session／Grant／credit／Ticket 与唯一 SSAP Engine。

重放必须在同一 guest USB wall 时钟下，找到 SSAP 实际读写窗口之前、期间、之后的
完整通道请求和对端校验回复；仅应用存活、Root事件或 NOCP 不够。普通动态TCID与
SMTC10必须不同，长PDU按完整分片末尾判定时序。缺真实交叠则失败，不增加负载或
插入延时直到通过。该门禁不覆盖通知／指示并发、完整公平性、credit真值、引用排空、
安全撤销、四设备、冷启动或自然恢复；准确实机范围仍只由资格入口记录。
