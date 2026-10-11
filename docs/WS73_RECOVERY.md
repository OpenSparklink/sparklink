# WS73 根因定位与每设备自动恢复

2026-10-10 用户追加要求。本文补充完整 S0–S6 与第一北极星；原 issues、
广播发现 20 轮与随后四设备两组并行保持。新增验收：**故障恢复不依赖人工
拔插，恢复单只不影响其他设备，恢复后无需重启 slkd**。未查明根因或仅
通过重插恢复时，不关闭相关 issue。每端口有限协议恢复已有初版实现及下述
合成运行验证及真实单对象人工传输故障后的恢复支持；设备消失后的完整自动恢复
及自然根因仍未完成。最新已验证北极星为7/8，见下方当前状态；早期4/8记录保留
为历史，不代表当前设备数量或本轮结果。

## 当前恢复范围与未决根因（2026-10-11）

保留[物理20+2轮记录](evidence/ws73-vm-physical-20261010.json)及其xHCI warning，
[整改后匹配内核/用户态记录](evidence/ws73-vm-strict-ci-regression-20261011.json)
提供另一条限定支持：一次guest IN81错误、命令超时-110、有限协议restore、
generation更新、幸存者及同daemon/普通应用和恢复后真实RF。该轮四个host USB
身份不变，没有设备消失/冷启动固件重传/物理拔插，不能据它关闭自然恢复。

[发送路径整改后新内核回归](evidence/ws73-vm-connection-tx-regression-20261011.json)
保留另一轮20+2真实RF、单对象人工错误、同daemon与幸存generation，以及四个
host USB身份不变。只读近期host诊断显示四口present/unbound，journal资料亦
关联保存；present不是Ready，也不能据近期无消失观测解释历史地址分配失败。

确定并已修复的边界分别是QEMU固定port重新打开新USB地址、autoscan重入及
枚举错误保留owner、BSLE ACK长度、WS73 0406空参数及广播实例/OFF初始化。
这些修复各有明确输入/失败证据，不能合并为一个已经闭合的“所有USB故障根因”。

仍需独立定位：host地址分配阶段失败/真正消失的电气、芯片或xHCI原因；历史
物理拔出时Set TR Deq等warning及幸存者错误触发链；自然启动失败与完全离线
之后的有限恢复。没有host handle时不能发送到其他device或复位整个hub。
当前只允许VM，原生宿主对照未执行；单/双/四设备与完整电源/PM矩阵继续OPEN。
复现时保存host port与地址、guest incarnation/generation、USB/QMP/xHCI时间线，
区分物理离线、QEMU owner关闭和协议退役；不以人工replug或单次人工注入代验。

## 来源与当前实机事实

标准、SDK、libws73-usb、OpenHarmony、合成模型与本项目实机分别标注。
私有 SDK 只用于读取调用约定和独立实现；不提交固件、校准、私有库或反汇编。
继续参考 libws73-usb 的 USB/HCC、BSLE、广播/扫描、命令状态和双端 gate；
其作者的实测结论不替代本项目实机验收，不能照搬进程全局状态。

历史冷启动阶段曾确认四只设备可读写、无主机接口驱动，固定端口为
1-2.1.1–4。早期一次用户回复插回后仍仅枚举 .1/.2/.3，.4 缺失；直接dmesg读取被限制，当时通过journalctl取得主机内核记录；.4重新枚举
在主机地址分配阶段失败，但电气/芯片/xHCI根因仍未确认。以下历史结果使用
SDK/us，与combined-1.10.110逐字节相同。随后修正111的非零SLE RX subtype
及初始化事务，已通过真实双端Ready/广播发现。最新测试 .1 保留曾实际
上传的111，.3 保留110，不能把暖态接入称为新上传111。
来源/hash/复现见[参考说明](NEARLINK_HOST_REFERENCE.md)。


- 旧透传停在重新枚举：同一端口已变成新 USB 地址，QEMU attached 仍 true，
  但未持有新节点 live fd。autoscan 把新设备计为 seen 后保留旧 handle。
  修复为固定 bus/port 下地址改变时调度既有 nodev 路径，先取消旧传输再自动
  打开新地址；不删除/重建 QMP 对象，不复位或解绑主机驱动。
- 实际 BSLE ACK 的 HCC pay_len 为32、tag body为4、整个有效状态为8字节。
  旧代码把填充算进 tag 长度而 EPROTO。现按 tag 长度读取四字节消息，
  允许 allocation 内非零填充；聚合包和 slot 边界仍全部验证后才消费。
- 修复上述两项后，冷启动设备通过 BSLE BOOT_FINISH，并成功返回真实
  0404(version)、0402(buffer)、0403(features)。随后旧0406参数00触发
  A2/000A/长度1/原始错误00，尚未发布 Runtime 或 Ready。
- SDK v660 ARM库与 stm32mp157 ARM静态库的 get-public-address 调用均为
  0406、空参数、长度0。这与标准及 OpenHarmony 的地址类型参数不同。
  WS73方言据此独立修正；下一轮实机四查询全部成功，真实地址为
  00:01:09:30:CE:85，发布 id0/generation1 的 Setup Runtime。标准路径保持原规则。
- 随后的首次 ADV_STOP(0c05, handle0) 返回原始状态1e，slkd保留Setup。
  OpenHarmony dli_errno.h 定义1e为 UNKNOWN_ADVERTISING_IDENTIFIER；
  libws73-usb 的 SetAdvParams(0c02) 与 Stop(0c05)是独立操作。下一步核验
  先创建广播实例、再实际成功关闭的初始化事务，不能将1e改成成功或跳过OFF。
- 本轮失败后主机仍能看到四只，其中三只已运行态五端点，最后一只仍启动态两端点。
  QEMU关闭时的 NO_DEVICE 不是主机设备消失的证据。此前真正消失的个案
  仍待结合主机事件、供电/拓扑和原生环境重现，不能宣称同一根因已解释。

相关原始证据在本地 .dev/ws73-real-replug-20261010、
ws73-real-reenumeration-fixed、ws73-real-padded-fixed、ws73-real-sdk-zero-param
和 SDK逆向记录。最后一轮失败为广播初始化，四项元数据成功不代表Ready。
失败测试现快速保存阶段、errno、DLI/Hardware Error、完整内核日志，并正常
停止抓包、保存 capture exit 与零丢包统计，保留失败而不覆盖。

## 故障归属与恢复状态

恢复协调对象跟随一个物理控制器端口，不依赖当前 active adapter 或可复用
的 controller index。Runtime/generation 与 USB incarnation 是不同身份：
每次重新发布 Runtime 都分配新 generation；旧 fd、lease、pending、事件不迁移。
预算须跨该端口的 boot/runtime 重新枚举保留，不能每次 probe 清零造成无限循环。

计划状态：Observed → Booting → Reenumerating → Configuring → Querying →
Setup → Ready；故障进入 Quiescing → Backoff → Recovering，然后重新走
完整初始化；超预算或证据确定不支持的方言进入 Failed。真实物理离线单列
Absent。每个状态有进入时间、原因和剩余预算；Ready仍要求完整元数据及
广播/扫描 OFF 两项成功 Complete，不能由 recovery callback 成功代替。

先关闭该 owner admission、解除等待者、通知 event/snoop，再在锁外停止
URB与worker。仅注销失败 generation；幸存设备的 generation、队列、命令
credit和控制权不变。slkd保持PID及D-Bus连接，看到原owner移除与新owner添加，
只重建相应adapter；已撤销操作明确失败，不把旧cookie当新操作继续。

当前协议策略为首次尝试加两次恢复，固定退避1秒、4秒；每阶段
与整体都有 monotonic deadline。BSLE阶段10秒、单OUT3秒、单查询10秒沿用
当前边界；恢复窗口总时长120秒，固件上传准入最多3次。所有限值须能
在测试中验证，不能只提供配置项。超过预算停止自动动作、保留 Failed。
正常稳定期后才重开预算；一条迟到成功或新USB地址不能重开预算。

| 类别 | 证据与处理计划 |
|---|---|
| BSLE/查询超时 | 记录等待消息/opcode、OUT结果和最后RX/IRQ；不能盲目重发结果不确定的命令。先停止/drain，再验证可以从该阶段安全重启的前置状态 |
| 短包/畸形HCC | 保存有界原始头/长度与解析拒绝原因，单owner失败；不得通过放宽边界或跳过坏包发布Ready |
| DLI Hardware Error/方言错误 | 原始event/error与errno分开；验证SDK参数和初始化前置条件。已证明不支持的操作不得按传输故障重复执行 |
| USB重枚举 | 固定bus/port等待新incarnation；主机节点/live fd、guest描述符和新Runtime分别确认；每端口有截止时间和有限重试 |
| 主机设备消失 | 同步主机USB事件与guest/QMP/供电资料，确认真正离线。无设备handle时不向别的设备发命令，不复位整个hub |
| 可用的软件恢复 | 优先设备协议的close/customize/open；验证原生驱动对自己设备的USB reset语义、guest透传差异与失败边界后才启用相应恢复层级 |
| 端口电源恢复 | 仅在hub支持独立端口且部署允许时考虑。ganged hub电源/全hub reset会影响幸存设备，不能作为合格的单设备自动恢复 |

没有可用的设备或独立端口恢复机制时，明确记录恢复失败和所缺部署能力；
仍保持 issue OPEN，不能把人工重插写成自动恢复。普通应用不因恢复增加sudo，
原生内核/固件部署所需权限另列；当前主机内核7.2.8并无本项目模块，原生
实机矩阵尚未执行，不能把KVM guest内核称为原生主机对照。

## 已实现的协议恢复初版（kernel97）

端口记录以USB控制器对象、bus及devpath为键，跨设备地址、probe和Runtime
变化保留；持有控制器引用防止指针复用。固定64条记录，满后拒绝新准入，
不通过淘汰失败端口重新发放预算。模块卸载才释放记录。

初次BSP超时的暖态恢复与运行期恢复共享两次预算。可恢复原因限定为
ETIMEDOUT、EPROTO、EREMOTEIO；EPIPE、EIO、Hardware Error、离线、取消
及不支持参数不会盲目重试。每次恢复先注销确切旧generation、加入旧Host
回调和URB，再仅对该接口执行drain/CLOSE30/新ACK、PM/customize/OPEN29、
BOOT_FINISH和四项真实查询，发布新的Setup。slkd仍需完成广播和扫描OFF
事务才能Ready；旧fd、lease、cookie与事件不会迁移。

1秒一次的观察型watchdog识别Host的命令超时/管理清理故障；它不提交I/O、
补credit或制造Ready。只有连续观察Ready满60秒才刷新预算，单条成功、新
地址或新generation均不刷新。同步恢复USB调用按120秒恢复窗口剩余时间
缩短超时；初始固件上传另有单次120秒I/O截止与3次准入上限。固件加载、
物理离线及端口电源恢复仍须独立资格验证，不能把这层称为全故障覆盖。

只读`recovery_budget`报告次数、上传次数、首因、协议恢复结果、耗尽、
截止和稳定期起点。`failure_diagnostics`的失败phase/errno/time在成功恢复
后仍保留；其TX、当前owner和最近启动查询字段仍是诊断采样，不能当作
原子故障包快照。`controller_information`在恢复改写时返回EAGAIN，元数据
无效时返回ENODATA；测试环境仅重试这些瞬态读及ENOENT，不吞掉EIO。

最终隔离KVM的13个Runtime场景全部通过，包括3种坏HCC/短或过长回复：
无需QMP操作即恢复generation1→3、查询相同地址、重新确认两项OFF为Ready，
幸存generation2不变，后续同端口重接保留预算。持续坏包场景实际进行1秒、
4秒两次恢复后停在Failed，持续查询幸存设备，旧fd保持失效且无第三owner；
QMP日志仅有加入幸存设备，未执行恢复用del/add。另覆盖OUT失败/短写/在途
拔出、早回复、广播扫描、事件、管理权、标准路径和recipe。

2038条独立策略检查、292个内核脚本和101个用户工具测试通过。错误工具链
导致驱动关闭的镜像93/94在前置检查中被拒绝；早期短OUT诊断假设和故障
用例遗漏广播初始化参数的失败也保留，未计为通过。

同一kernel97重新验证普通UID1000/capabilities0、slctl、同slkd/bus的真实
双WS73：20轮交换角色加QMP重接后2轮，306–607ms匹配标识/数据/地址/RSSI
（−14..−7），1315 USB packets、零丢包，两只最终STOP_CONFIRMED。合成支撑
也完成22轮、2557 packets/零丢包。暖态恢复耗时约1.16秒，同端口重接后的
第二次约4.16秒；它们不是运行期真实坏包注入或物理掉线自主恢复证据。
真实QMP仍为`physical_acceptance=false`；主机三只地址不变、未选 .2 未接管。

冻结源码57项、QEMU输入6项、kernel97镜像/配置/对象/编译指令及原始日志/
抓包在本地`.dev/port-recovery-evidence.json`关联。SDK、固件、校准与原始
二进制不提交。板级配置仍NOT_ASSERTED。完整北极星仍4/8；先前物理拔出
导致幸存设备IN −108、.4缺失根因、原生主机矩阵、真实运行期故障恢复及
四设备两组并行均保持OPEN。芯片寄存器复位和独立端口电源恢复尚未实现。

## QEMU autoscan 隔离问题与主机枚举证据

读取实际QEMU9.2.0的`usb_host_auto_check`/`usb_host_close`后找到确定的
重入错误：外层扫描发现A不存在，关闭A触发内层autoscan；内层清空B的seen，
外层继续遍历便把B也关闭并重新打开。另一个错误分支在
`libusb_get_device_list`返回负数时，把失败的枚举当成全设备消失。

新增`usb-host-autoscan.patch`防止嵌套扫描改动外层seen，并在枚举失败时保留
已有handle、继续有限周期观察。不会复位、解绑、改匹配端口或合成Ready。
`check-usb-host-autoscan.py`编译实际两个生产函数及原重枚举谓词，配计数USB
mock验证6种条件。旧函数在A缺失时实际关闭A/B各一次、重开B；新函数仅关闭A。
枚举错误旧函数关闭全部，新函数保留全部。健康、初始化失败后再试、暂停及
单owner重枚举也通过。四补丁的应用/幂等/漂移拒绝和实际未附着QMP探针通过。

这提供了原物理失败的候选机制：旧抓包13:10:33.225190 UTC显示A IN−71，
13:10:35.018964 UTC显示B IN−108，slkd随后把B重新注册为generation3；
间隔约1.79秒与autoscan 2秒周期相符。**尚未进行修复后的物理拔出复测，
不能把时间相符或mock复现直接认作完整物理根因关闭。**

通过可读的主机kernel journal还确认，.4在21:13:27–21:13:56本地时间尝试
地址93–96，出现SETUP超时、−62/−110/−32/−71，以及主机hub尝试power cycle，
最终unable to enumerate。此失败发生在我们的USB接口probe之前。当前port4
state=default、over_current_count=0；hub缓存描述符仅证明USB2单TT及声明
self-powered，class hub电源描述符因权限未读到，不能断言独立电源控制。
过流计数0不能排除欠压、芯片故障或xHCI问题，不启用整hub断电恢复。

新增只读主机诊断命令，保留精确USB端口及共享xHCI错误的独立归属::

    python3 tools/ws73_host_diagnostics.py --ports 1-2.1.1 1-2.1.2 1-2.1.3 1-2.1.4 \
      --since '2026-10-10 21:08:00' --until '2026-10-10 21:16:00' \
      --output <新私有证据文件.json>

命令不reset/detach/upload/改权限；journal不可读时明确记未观察，而不是制造
根因。返回的present/bound不是协议Ready，不会把公共控制器错误强加给某口。
新QEMU复用已冻结kernel97，13个Runtime gates及292内核脚本测试通过；真实
双WS73 QMP对照22轮、1331 packets/zero drops、158–616ms、RSSI−13..−7，
同slkd与幸存generation不变。108用户工具测试通过。复现和旧反例/源码/
QEMU对象/日志在本地`.dev/autoscan-evidence.json`关联；不是新内核构建，
不是物理拔插验收。物理北极星仍4/8，全部未完成原issues保持OPEN。

## 测试矩阵与验收

每个用例同时保留负例和修复后证据，固定固件/校准、端点、源码及工具hash。
原生主机Linux、真实USB经QEMU、纯合成QEMU三种路径分开记录；前两种各做
单只、双只、四只，不能用合成模型替代。QEMU自身的主机handle问题单独判定。

1. 冷启动、已有运行态接入、反复boot/runtime枚举：比较阶段时长、USB地址/
   incarnation、IRQ及HCC时序；失败不能计入20轮无线成功。
2. 注入无BSP、缺customize/BOOT_FINISH、缺/迟到Complete、短OUT、超时和
   Hardware Error；证明次数/退避/总时长受限、失败原因完整、无无限worker。
3. 恢复期间持续操作另外1–3只：普通slctl控制成功、真实RF报告归属不变，
   generation不变，无命令/事件/lease跨owner；四只两组互换与并行闭环。
4. 自动软件恢复完成后，保留同一slkd PID/总线，生成新generation、新随机
   广播标识；按10秒发现边界重跑双端闭环，确认旧fd/cookie仍失效。
5. 分别注入guest设备断开、物理USB掉线、固件主动重枚举及不支持参数；
   区分cause与effect，不把QMP device_del/add记作无需人工拔插的真实恢复。
6. 连续故障耗尽预算后保持Failed，CLI能读原因且幸存设备可用；用户显式
   重试须建立新恢复事务并记录来源，禁止后台悄悄复位全部设备。

当前新增恢复验收未完成。仅已定位的软件错误、诊断、有限透传等待和模拟
事件路由不能关闭 K#10/#14/#15/#16/#19 或 U#8/#10；其余原验收亦保留。

## 后续111验证与广播实例初始化切片

显式typed operation5 ADV_CONFIGURE_OFF已实现：参数配置0c02 → 成功Complete
→ OFF0c05 → 成功Complete；无data/response/duration/enable。使用真实查询的
地址及已有version1 basic policy，slkd随后执行SCAN_STOP。取消的配置前缀
迟到Complete不能确认OFF；原始1e失败仍保留。全新实例合成模型会对未创建
handle的stop返回1e，不能把旧模型“OFF总成功”当物理依据。

111实机下载/BSLE通过，旧parser因SLE subtype1拒绝buffer Complete，第一
只未发布Runtime，第二只未接入。SDK/libws73路由依据已核验并独立修正；
真实五帧生产C离线校验与合成16种subtype通过，不等于修复后实机启动。
现在四只均已warm，不追加人工重插作为通过手段；下一依赖是每设备warm
恢复及重新查询，再实测operation5/OFF和双端广播。原生主机对照、自动
有限恢复及真实北极星0/8仍未完成，issues不关闭。

### 每设备暖启动与真实初始20轮（kernel90，部分验收）

固件基线采用用户指定libws73-usb combined-1.10.111，制作方式保持
`cat ws73.bin wifi_cali.bin btc_cali.bin > combined-<版本>.bin`，各段64字节
hash头保留。暖启动不上传固件，不能仅凭准备目录将旧设备标成111。

已实现一次有界暖启动采纳：仅初始BSP_READY超时、尚未发布Runtime时，
每probe最多一次；先最多64包/1000ms排空旧输入，再发送SDK action30 CLOSE，
等待新type4/message3关闭ACK，重新PM/customize、OPEN29/BOOT_FINISH及四项
DLI查询。各阶段有截止时间和独立失败日志，`warm_recovery`导出attempts/
limit/cause/result/start。旧BOOT、OPEN ACK及排空前CLOSE不能代替新关闭回执，
panic/断开/超限均失败；不重置hub、不detach、不主动操作其他owner。
这是启动恢复切片，不是持久端口预算、运行期故障恢复或设备消失根因闭环。

真实111暖设备已验证关闭/重新启动/四项查询及广播配置/OFF成功。扫描初始
OFF返回原始0b；补参数1001成功Complete后OFF仍0b，否定仅缺参数假设。
新typed operation6 SCAN_INITIALIZE_OFF执行**被动参数 → ON → OFF**，三个
成功Complete后才确认OFF/Ready；短暂开启接收，无主动scan request。只接受
active=0/duplicates=0，必须先有广播OFF且无并行广播/扫描事务。中间ON在
发送时使扫描状态未知，取消/迟到ON不能建立Ready，失败最终OFF仍保持未知；
含enable的旧recipe不能在被替代后发送。operation5仍不启用广播。

真实`.dev/ws73-real-scan-probe`两只独立Ready、20轮交换角色成功，但物理
拔出1-2.1.4后幸存1-2.1.3的registration由slk1_g2变为slk0_g3，判FAIL。
等待人工操作超过会话时限，capture无最终丢包统计，不能冒充完整证据。
slkd日志保留两次退役和重新注册；QEMU/内核/USB供电归因尚未完成。

独立重跑`.dev/ws73-real-initial20`：1-2.1.1当轮冷上传111，1-2.1.3保留110，
地址分别00:01:09:32:54:CD和00:01:09:30:CE:85；两个不同Runtime generation
均Ready。普通UID1000、全部capabilities=0，通过slctl交换角色20轮，随机标识
均不同，数据/地址/RSSI匹配，成功Scan Complete后298–615ms内观测。封存
1161 USB packets、zero kernel drops；独立执行生产corroborator原20轮块，
逐轮匹配实际TX/Complete/完整RX/所有权/时间/marker/四元信息查询，输出
`.dev/physical-initial20-evidence.json` INITIAL_20_RX_CORROBORATED。已验证2秒
TX-off负例。此轮有意不执行物理拔出，完整脚本在EOF及重复idle扫描OFF处
保留FAIL，不伪造replacement、cleanup或整体PASS。板级功率仍NOT_ASSERTED。

北极星只确认第1/2/3/6项（独立Ready、新数据10秒内、20轮角色交换、普通应用），
**4/8部分验收**；拔出隔离、同slkd重插、完整可复现验收包和自动恢复未完成。
所有整项issues/PR草稿及S0–S6保持OPEN，四设备两组尚待扩展。

kernel90验证：6078 BSLE/451067 discovery/115776既有DLI checks，11生产operation
和15 Host plan tests；19库/64slkd tests，96工具tests，282内核脚本tests通过。
四条WS73 discovery/management及标准Runtime/recipes回归PASS。clippy退出0，
42既有slkd warnings保留。此前kernel85/87合成20+2 receipts独立保存，不能
倒填成kernel90完整测试。新增idle-OFF=0b模型用于暴露管理清理前置条件。

测试工具清理可重新读取同一generation、同一request的已成功OFF及当前OFF
状态，确认无中间on/off，再保留其原始OFF命令关联；无需重复发送已idle的
OFF。不把新0b改成功，错误/未知/旧代次均拒绝；真实旧失败记录保持。管理
lease撤销及C/Python writer在此固件语义下的门禁继续独立验证。

最新idle模型门禁：kernel90合成普通用户20+2轮、同slkd/bus与热重加控制阶段
通过，独立复核2427 packets/191TX/179empty及4条保留OFF查询关联；整体
`.dev/scan-probe-idle-support` **FAIL**，因为随后C binding writer对已经OFF的
扫描器再次发送OFF，被模型返回0b。该失败未隐藏，管理撤销/绑定writer正确
前置条件继续作为依赖处理；不以此宣称完整C/Python writer或发布矩阵通过。


### 管理释放保留已确认 OFF（kernel92，合成门禁通过）

管理撤销曾对两个射频域都发送 STOP；扫描已经 OFF 时真实111和严格模型返回
原始0b，不能改成成功。现在仅内部撤销的一步 STOP、匹配本次租约撤销 cookie、
同一 owner 已确认 OFF，才保留该状态。决定发生在前一个线上的请求消耗之后；
未知/ON、取消的 enable、公有请求和多步 recipe 仍走正常调度。保留 OFF 不发送
USB OUT，不伪造 Complete、credits、时钟或公有请求结果；另一个域仍须成功停止。
故障或超时不能绕过，两个域均完成后才允许后继管理租约。

C binding writer 先真实配置并开启扫描，再验证公有 STOP；随后重新开启扫描，
在广播已 OFF、扫描 ON 时释放管理租约。USB 抓包要求实际扫描 OFF 成功，释放
窗口内无重复广播 OFF，同 generation 回到 Ready。management 原生门禁也使用
被动扫描初始化，并启用 idle-scan-stop=0b 模型；失败/取消/超时负例保留。

冻结 kernel92 和56源文件、QEMU及6编译输入后，`.dev/retained-off-support`
完整 SUPPORT_PASS：普通用户20+2轮、合成拔插、同 slkd/bus、暖启动、empty bulk
与 C/Python 绑定均通过；2557 USB packets、zero capture drops、192 empty
completions，22条独立控制抓包关联。12条 Runtime gates 全部 PASS；16 Host-plan、
11 operation、96用户工具、282内核脚本 tests 通过。旧 kernel90 整体失败证据保留。

这是合成开发门禁的修复；真实20轮证据仍是先前 kernel90 的111/110混合版本。
北极星仍4/8，物理拔出导致幸存 generation 改变的根因、物理重插、不依赖人工
拔插的恢复、原生主机与QEMU对照、四设备两组及完整S0–S6仍开放。本次主机
只枚举到1-2.1.1/.2/.3；.4仍未出现，不能把用户已插回解释为枚举恢复成功。


### 三层生命周期诊断与 kernel92 实机初始阶段

开发 runner 为真实 passthrough 自动记录 `host-inventory.jsonl`：初始、变化和
结束时的全部 WS73（包括未选择的设备）及 wall/monotonic 时间。QEMU 开启十个
显式白名单事件和时间戳，记录 open/close、端口 attach/detach、接口 claim/release、
传输完成状态/长度及 reset；不记录 payload，不改变 USB 权限或恢复行为。
日志写入独立文件并纳入 manifest SHA256；缺少事件则拒绝启动诊断测试。
guest console 使用 loglevel6，以保留异常结束时的生命周期线索。98工具测试通过。

旧隔离失败抓包显示：拔出侧在13:10:33.225190 UTC出现IN -71，幸存侧在
13:10:35.018964 UTC出现IN -108，随后以新generation注册。该观察将问题缩小到
USB/内核生命周期，但不能据此断言主机、QEMU或驱动的触发根因；原生主机对照
与受控单owner故障注入仍是下一依赖。

kernel92真实初始20轮再次逐轮独立复核：UID1000/capabilities0，111/110保留固件，
299–616ms匹配新数据、地址与RSSI；1019USB包、zero drops，两只最终
STOP_CONFIRMED。capture SHA256
`a23c4d502ca60ca5d1adace7f476f79118a050117180a9982be3d7b6e5d287d8`。
本地 `.dev/physical-retained-off-initial20-evidence.json` 仅证明初始阶段；未执行
物理拔插，完整control在确认拔出时EOF，整体environment也保留FAIL，不能升格
为完整北极星通过。北极星仍4/8；设备.4仍缺失、根因与自动恢复issues继续开放。


### 真实 RF / QMP 单 owner 断开对照（kernel92）

新增可复现命令：在当前源码准备的隔离环境执行
`ws73_target.py run --prepared <目录> --output <新目录> --ports <端口A> <端口B> --qmp-hotplug`。
两只均是真实 WS73，普通 UID1000/capabilities0 使用 slctl；主机物理连接保持，
仅 QMP 移除并在同固定 guest 端口重新加入 owner0。记录独立 scope、
`hotplug_method=QMP_DEVICE_DEL_ADD` 和 `physical_acceptance=false`。
独立抓包验证器拒绝把该结果作为物理拔插验收，即使只改 scope/status。
合成负例分别验证方法边界与 USB 描述符边界；本次校验器曾期待旧错误文本而
使整体合成 FAIL，日志保留，修复后重跑全套，不修改失败 receipt。

最终冻结工具实机 PASSTHROUGH_SUPPORT_PASS：20初始+2重接轮，每轮新随机
标识、数据、地址、RSSI及实际成功 Complete 逐条 USB 关联，308–613ms。
1295包、zero drops，同 slkd PID97/start_ticks76及同 D-Bus owner；幸存
设备 generation2 不变，被移除的 generation1 失效，重接 generation3。
2秒 TX-off 负例与两只最终 STOP_CONFIRMED 通过。主机三只始终保留原 USB
地址，未选中的1-2.1.2保持无driver接管。QMP恰好执行初始两次add、一只del、
同属性一次add；guest-reset/guest-resets-all/host-reset/kernel-driver-detach均false，
时间戳 trace 无 usb_host_reset。

capture SHA256 `ecccbc19a3333c94cb51728db69f9dcfb58d03e669d92ee4f2aef4b7f4b44c7d`；本地`.dev/passthrough-control-evidence.json`。
100工具/282内核脚本 tests 通过，既有 kernel92 的12条 Runtime gates不倒填
成新内核构建；最终严格合成门禁也完整 SUPPORT_PASS：2557包、zero drops、
192 empty completions、22条独立控制证明及 C/Python 绑定、same daemon/bus通过。
实机固件仍111/110保留版本，board NOT_ASSERTED。

结论范围：静止射频域下 QMP guest 退出可单 owner 隔离，未复现旧物理拔出时
幸存设备 IN -108 / generation 改变。**并未定位该物理根因，也不是设备消失后
自主恢复。** 北极星仍4/8，物理隔离/重插、完整物理复现包、原生主机对照、
有限自动恢复和四设备两组及完整S0–S6继续开放；.4端口仍缺失。


## 本批恢复资格保持开放（2026-10-11）

[后续partial模型fd矩阵](evidence/ws73-managed-later-partial-model-fd-20261011.json)
九个成功和三个精确拒绝仅证明模拟USB下实际内核fd及迟到回复处理，不算真实
故障恢复。新只读host核对仍四只、有效权限正常、power active，第四只仍ROM；
未新增真实诊断bulk、复位、hub循环或主机实验安装。既有两次ganged四口hub off/on
只重新枚举，未恢复Ready或证明VBUS/SoC真正掉电；不能纳入单设备独立恢复。
自然bulk超时、完全离线／重新枚举与历史xHCI根因、无需人工拔插恢复继续OPEN。


本批[主机只读观察范围补充](evidence/ws73-managed-later-partial-host-scope-20261011.json)
明确记录调用stock `uhubctl -f -l 1-2.1`读取hub状态，未带action、未切换电源。
原封存证据“no new physical USB transfer”措辞过宽，限定为没有新增诊断bulk／
寄存器／固件／实验驱动传输；模型VM没有接host USB。原证据文件保持不变，
这次主机观察不增加真实Managed、Ready同行、RF或恢复资格。


## EP0 HCC memory-credit 只读诊断入口（2026-10-11）

为定位现有bulk超时，SDK `hcc_usb_get_credit` 是可追溯的只读class/interface
IN入口：bmRequestType=0xa1、request5、value/index0、length4。新增专用VM
`ws73.usb_credit_lab=1` 与 `--usb-credit-read-only` 必须精确匹配且排除USB
reset、wakeup、route、rebind、clear-halt及寄存器模式。必须先核对真实runtime
单interface0/alt0五端点，独占guest usbfs，仅执行一次有界2秒读取，核对前后
完整配置，随即退出；不写SoC、不加载实验模块、不重启hub。短回复和原errno
保留，不追加恢复性重试。292工具测试通过；本提交尚无该读取的实机证据。

返回值是原四字节HCC高优先级内存计数，0和任意u32都原样记录；它不是DLI
命令credits、BSP/BSLE ACK或Ready，不能触发生产Runtime注册或恢复成功。
后续实机结果必须核对actual usb-host/libusb、guest USB抓包及零bulk/复位，
异常VM不能转成成功。现有bulk超时、原Managed门禁、活动Ready同行、自动恢复
和自然RCA继续OPEN。静态111固件头SHA校验通过，但stock反汇编存在未识别
芯片扩展且USB控制路径调用ROM；`RESET_BCPU`仅枚举不足以证明处理或ACK，
不会据此盲发复位。固件/SDK二进制及反汇编仅私有本地研究，不提交到仓库。


## 真实 EP0 只读 credit 对照（2026-10-11）

[两只实机的完整诊断证据](evidence/ws73-readonly-ep0-credit-20261011.json)封存端口
1-2.1.2及1-2.1.1的独立VM：SDK class/interface IN request5各一次，均返回原
四字节00000000，HCC高优先级内存credit=0。每轮65包零丢包，原USB提交/成功
完成回执、actual usb-host req0xa105/length4及libusb控制回执匹配；零目标bulk
及class OUT，无复位／hub循环、SoC写入或WS73模块加载。完整runtime配置与
四只主机枚举、parent/hub/target suspend计数保持。这里只验证控制读取，
不算活动Ready同行、RF、每设备恢复或本次固件版本查询。

该结果证明本次SDK EP0控制读取可完成，而先前EP01/EP02 bulk仍有明确失败
证据。原HCC memory-credit零值不能改成默认值，也不能当成DLI command-credit
或Ready ACK；SDK data流控另外保留USB控制buffer，不能仅据零值认定路由／
寄存器bulk超时根因、强行开放流控或盲发RESET_BCPU。111文件SHA头静态校验
通过，但反汇编存在未识别扩展且关键USB路径调用ROM，缺少复位callback/ACK
证明；不提交SDK、固件或反汇编字节。私有验证器最初把QMP hostport当完整sysfs
路径，失败日志保留；修正为精确hostbus/hostport后复核原两轮，没有重跑VM或
改写原结果。

292工具测试与源码0a096ee九个CI作业通过。保持VM-only与历史真实WS73路径，
正式Linux/Rust行为未改。正常启动门禁仍7，维护尝试增为20；新增真实Managed
通过数仍零，当前没有双设备Ready／活动同行证据，所有恢复/RCA及原整项保持
OPEN。下一步需核对供电路径及成功状态基线/ROM分发或HCC资源初始化的可追溯
证据，再选择受控实机对照。不能靠重复ganged hub重枚举或模型通过代替根因。

## 当前实机门禁：ROM 首包也超时，供电拓扑已确认（2026-10-11）

[ROM 启动原失败与独立抓包核对](evidence/ws73-rom-startup-timeout-20261011.json)：
第4只两端点 ROM 模式在新隔离 VM 使用正式 K292 驱动，第一笔19字节
`READM 0x40019380 4 ` OUT 即超时，phase1/-110；77包零丢包，原取消回执-2。
失败 OUT 的 guest actual19 不代表物理成功；没有寄存器写入、111上传或 Setup。
第3只未接入，Managed release／最后fd／dup／在途及活动Ready同行均未执行。
正常启动累计8、维护20，新增真实Managed仍0；本批无hub循环或生产代码变更。

用户确认 hub 无外接电源、WS73 无其他供电线路；该事实不等于测量了 off 时
VBUS。ROM首包失败也不能仅用运行态HCC memory-credit0解释。现有ganged hub
整组切电仅是受授权的维护操作，不能作为隔离单只恢复实现或验收。

原boot budget记录uploads1、attempts0/cause0/result0，而boot_error=-110：
启动路径尚无已验收的有限恢复，预算result也未反映此次错误。整改须明确每阶段
可安全重试的边界、总期限、原错误记录及重枚举等待；部分固件/寄存器写入不能
直接重放。先定位共同bulk故障并恢复真实查询，再执行完整Managed和活动同行
门禁。自然RCA、无人工恢复、四设备及整项issues继续OPEN，历史RF证据保持。

## 冷启动后的测试工具地址绑定修复

物理冷断电后原VM实际完成111上传和USB重枚举，target4主机地址123→124。
原验证器把运行态一次故障标记与启动前地址比较，整轮FAIL原记录保留。
新工具在arm前绑定当前固定端口、五端点runtime、实际child持有的USB fd；
故障/hold核对使用该快照，不接受其他设备或未持有的node。只允许初始ROM
owner各一次且发生在arm前的close；运行态close、任何reset/open failure、
重复close或缺少时间戳均拒绝。此改动仅测试工具，不更改正式Linux/Rust驱动。
294工具测试通过；冷启动原抓包的独立复核与新工具实机状态另行封存。
人工冷断电不计自动恢复，Unknown Setup队列子门禁不替代confirmed-Off完整
初始化或活动Ready同行。原bulk根因/自然恢复与整项issues继续OPEN。


## 2026-10-11 冷启动对照、真实队列子门禁与 partial 清理拒绝

[新封存证据](evidence/ws73-managed-cold-real-progress-20261011.json)保留原失败：
用户报告 hub/WS73 只有 USB 供电，并将上游物理断开至少 30 秒后重接；四只重新进入
ROM，两只在同一冻结镜像输入上成功上传 1.10.111、真实 DLI 查询。人工冷断电只用于
对照，不算自动恢复，也未实测 VBUS；先前软件 off/on 未恢复 bulk 的根因继续开放。

真实 Unknown Setup 的合法队列子集六案例、两域完成真实初始化/Off 后完整初始化队列
六案例分别核对 release、最后 fd 关闭和 dup。受控单 CPU/FIFO 窗口内未选中请求均保持
Cancelled/-ECANCELED，完整矩阵区间两只零 DLI；这不等于普通调度并发。两次各 20+2
随机空口轮次由抓包独立核对，应用同 UID1000/caps0、同 slkd，围绕人工 guest IN 错误；
不用于关闭自然恢复。冷启动第一次原宿主验证误用 ROM 旧地址，原 VM FAIL 不改写；
另一次 usbfs 所有权检查过严的捕获未封存失败亦保留，已修复精确 live fd/当前地址门禁。

首个真实 partial 广播 release 在原 C02 回复被保留后取消；原 C02 迟到成功及 C05 STOP
成功，但多余的未初始化 scan STOP1002 返回 0x0b，原目标 Faulted/Unknown、旧请求
Cancelled/-ECANCELED 保留。另只三次真实 MAC 查询与 Setup/Diagnostic 身份保持，
仍不是活动 Ready 同伴；剩余五案例当时未执行，不作为通过。

Kbea9fc6527f8 新修复保留每 Runtime 实际选择域的历史，撤销仅执行已选择/已知域；
跳过 untouched Unknown 只结束该域撤销等待，不制造 Off/Ready。24 项实际 Host 源码、
19 项严格命令计划及 296 项工具回归通过。U8e20b69 新 `--managed-selected-cleanup`
只用于实际第一步 partial、显式版本5记录：广播单域清理后 scan Unknown/Setup；扫描
已有真实广告 Off 前置，仍需扫描真实 STOP。原历史格式3/4、模型和失败证据保留。

新生产镜像尚未取得物理资格。初次复制目录构建因缺工具重新配置后丢失 CONFIG_RUST，
构建产物资格检查明确拒绝；原日志/配置保留，恢复已验证配置并重建后才可继续。
下一依赖：匹配镜像/签名模块的空USB启动检查 → 实际 release/last-fd/dup 与在途回复
→ 活动 Ready 同伴前/中/后真实工作 → 同 daemon RF20+2及拔插 → 四设备两组。
正常启动 VM 累计12、维护20，不归零历史失败；自动恢复、自然 RCA、完整 Managed
与原各 issue 整项仍 OPEN。VM-only，无主机实验安装、无生产模拟成功或固件字节发布。


## 2026-10-11 真实 partial 新镜像进展与扫描参数清理细化

[不可覆盖的新实机证据](evidence/ws73-managed-selected-domain-real-20261011.json)：
编译 Kbea9fc6527f8、服务 Uf04e6bba2233、冻结采集器 U0c609d0 的广播 release/last-fd/dup
三个案例完整 PASS，各有实际保留的原 C02 frame SHA、Cancelled/-ECANCELED、真实 C05
Off、scan Unknown/Setup、Revoking→Free、三次同行真实查询和同 daemon 普通用户 RF20+2。
首次新镜像的抓包窗口误计同行查询导致原 VM FAIL，单独独立核对成功、不改写原状态；
U0c修复窗口后重跑三案例，扫描 release 则保持真实 STOP1002 0x0b/-EIO、Faulted/Unknown
失败，最后两案例未执行。正常启动 VM 累计17、维护20，整项/活动 Ready 同伴仍未通过。

参考 Host/WS73 接口明确区分 SetScanParam1001 与 EnableScan1002。新 K4ece91aa5c7c
将同一 Runtime 单调选择历史细分为广告、扫描参数、扫描控制：新 Runtime 仅选择过参数
时，取消等待原回复并清掉未选择的 START，扫描保持 Unknown；任何扫描控制历史或已知
扫描状态仍需真实/保留 Off 屏障。不是把0x0b解释为Off，也不将参数配置当扫描已关闭。
新 U5d29cb7 显式版本6扫描参数门禁检查无额外START/STOP、保留原广告Off和scan Unknown；
历史格式3/4/5、原失败和模型仍保留。25实际Host源码、19命令计划、299工具测试通过，
新合格Rust镜像/签名模块空USB VM加载卸载通过；编译器零警告、保留一条make jobserver警告。
新六案例正在独立冻结镜像上执行，尚不能计作新修复实机通过。后续真实初始化步骤、活动
Ready同伴、普通调度并发、四设备两组、自然自动恢复/RCA仍按原整项条件OPEN。VM-only。


## 2026-10-11 第一初始化步真实六案例通过；活动 Ready 同伴仍是下一门禁

[最新不可覆盖证据](evidence/ws73-managed-scan-parameter-real-20261011.json)以编译内核
K4ece91aa5c7c、服务/冻结工具U5d29cb7b3aa5完成广告/扫描各 release、最后fd关闭、dup：
六个原VM均PASS/QEMU0，原在途host成功帧SHA/长度与迟到Complete一致，原请求保持
Cancelled/-ECANCELED，dup首次close保留lease、最后close触发撤销，Revoking→Free。
广告只执行C02+C05、未触及scan保持Unknown；扫描先有真实广告Off，持有原1001配置
回复后取消，零已选START/STOP，scan保持Unknown/Setup。既不推断0x0b为Off，也不制造Ready。
每例三次同行实际MAC查询与身份保持；各1183/1187包零丢包，taint0、无内核fault。
每例同slkd/bus、普通UID1000/caps0随机RF20+2及人工guest IN故障支撑由捕获独立核对，
合计132轮；未使用人工拔插、hub切电或主机实验安装。原构建资格拒绝、抓包验证FAIL和
两种真实STOP0x0b失败完整保留。正常启动VM累计23、维护20。

**只验收初始化第一步六案例。** Unknown Setup/confirmed-Off未执行队列真实各六案例
仍是受控单CPU/FIFO支撑；普通调度并发未验收。本批同行仍Setup/Diagnostic，不能把MAC
查询或后续RF偷换为目标撤销期间活动Ready隔离；后续原广播最后STOP、扫描START/最后STOP
的物理门禁仍待执行。整项Managed、恢复/RCA及28项原scope继续OPEN，goal active。

下一门禁先用同行真实C02/C05/1001/START/STOP建立独立Ready，再持有同行Managed lease。
在目标原回复被保留期间让同行真实扫描START成功、保持On跨越目标release/last-fd/dup与
迟到回复清理；目标Free后核对同行同generation、Ready、owner和On，再STOP及重启扫描。
以完整命令/Complete窗口和radio状态证明工作持续，无跨设备STOP、换generation或重启daemon。
随后扩展后续原终结帧、普通调度取消/结果淘汰及四设备两组。25实际Host源码、19命令计划、
299工具测试与K4ece空USB启动通过；U5d CI38140975482九作业success，最新证据提交CI另核。
自然启动超时/重枚举/消失RCA和无需人工拔插的每设备恢复仍开放；原生主机对照受VM-only约束未执行。


## 2026-10-11 第一初始化步：真实 Ready Managed 扫描同行隔离六案例通过

[独立实机证据](evidence/ws73-managed-ready-peer-real-20261011.json)
SHA256 `dbc48ecd6f748b75e7d70d61336e87da8337554c2cfd97de5cbca07f91b5e69f`，
编译内核 K4ece91aa5c7c、服务 U5d29cb7b3aa5、冻结工具 U44bf694f2652。
广告/扫描第一初始化步 × release/最后 fd 关闭/dup 六个原 VM 都 PASS、QEMU0；
每例同行先真实五命令初始化 Ready，独立持有 Managed lease，在目标保留原回复期间
真实 START 并保持扫描 On，跨越目标取消、原迟到回复与 Free。目标 Free 后独立
ioctl 仍观察到相同 generation/完整 Ready/owner/current On；继而实际 STOP/START/STOP
成功，才释放同行 lease。查询请求203的 radio 字段由当前 Host 状态填写
（`sparklink_core.rs::ioctl_discovery_result`），不是复用历史成功结果推断 On。
每例十四条同行命令与成功 Complete 精确匹配，整个窗口拒绝未记录命令/回复及跨设备 STOP。

目标原 held host 成功 IN 帧 SHA/长度与实际迟到 Complete 一致；原操作始终
Cancelled/-ECANCELED，dup 首次 close 保留 owner、最后 close 撤销，Revoking→Free。
广告目标只有 C02+C05；扫描目标先真实广告 Off，再只有原1001参数配置，无未选
START/STOP，扫描仍 Unknown/Setup，未制造 Off/Ready。
每例1207/1211包零丢包、taint0、无kernel fault；同slkd/bus、UID1000/caps0
RF20+2随机标识/数据/地址/RSSI成功，共132轮。人工 guest IN错误是开发支撑，
不等于自然故障自动恢复；本批无人工拔插、共享hub循环或主机实验安装。
25实际Host源码、19命令计划、303工具测试通过；U44bf694 CI38143384779九作业success。
正常启动VM累计29、维护20，历史失败不归零。

只通过**第一实际步骤 partial 六案例的活动 Ready 同行隔离**；整项 Managed 未完成。
下一优先顺序：confirmed-Off未选择队列取消期间同行保持 Ready/Managed/scanning On，
两角色 release/最后fd/dup，quiet区间两只零DLI且前后实际启停成功；继续保留
单CPU/FIFO限制，普通调度并发另验收。随后实际广告最后STOP、扫描START/最后STOP的
held回复/三fd/Ready同行，需真实原USB帧skip/hold/hash证明，不能用模型Complete替代。
再当前镜像物理拔插、四设备两组、结果淘汰和自然自动恢复/RCA。
之前三份证据及原0x0b拒绝、捕获窗口失败、不合格构建仍保留。
28项原scope、两个draft、自动恢复/自然超时-重枚举-消失RCA和历史xHCI warning继续OPEN；
原生主机对照受VM-only约束未执行，完整goal active。


## 2026-10-11 未选择队列取消：双角色活动 Ready 扫描同行六案例通过

[新独立实机证据](evidence/ws73-managed-ready-queue-real-20261011.json)
SHA256 `dcb672a9adc8b5e8726ec54d7a6ac42bb8d625a97594605858206fa97c92d38a`。
编译内核K4ece91aa5c7c、服务U5d29cb7b3aa5、冻结工具U9a3b29c；原VM
FAULT_RECOVERY_SUPPORT_PASS、QEMU0，探针六案例全成功。
两只实际五命令初始化Ready；两种目标角色各release、最后fd关闭、dup。
每例同行先独立持有Managed并以真实CFG/START开始扫描，在目标Queued→Cancelled
及Free的完整窗口前、FIFO内、窗口后，实际ioctl都保持相同generation/Ready/owner/current On；
随后真实STOP/START/STOP成功，同行再实际释放为Free。错误token仍EPERM，dup第一次
close保持owner及Queued，最后close撤销；取消结果opcode0/step0/-ECANCELED，未选择执行。

十条实际bootstrap命令及三十六条同行活动命令/成功Complete逐项核对；六个约350ms
完整取消窗口两只均零命令/回复/失败；间隔只允许精确记录的同行活动，整个bootstrap
到最后同行释放区间拒绝多余命令、Complete或失败。FIFO关键段约0.041–0.101ms，
每例恢复SCHED_OTHER；这是受控单CPU开发支撑，**不等于普通调度并发通过**。
1307包零丢包、taint0、无kernel fault，同slkd/bus、UID1000/caps0的RF20+2通过。
306工具测试及严格C编译通过；25实际Host源码、19命令计划保持已有验证。
正常启动VM累计30、维护20，失败与旧证据不归零。

此前第一实际步骤partial六案例及活动Ready同行隔离、132RF仍有效，原Unknown Setup
队列子集6、confirmed-Off静默队列6、0x0b拒绝和捕获/构建失败全部保留。
当前仅通过受控未选择队列及第一实际初始化步骤的fd/同行门禁，**整项Managed仍OPEN**。
下一优先：真实广告最后STOP、扫描START/最后STOP，分别release/last-fd/dup及Ready
同行，保留原500ms deadline，需真实host成功USB帧skip/hold/hash证据，不用模型Complete。
随后普通调度/结果淘汰、当前镜像物理拔插、四设备两组、自然自动恢复/RCA及完整S0–S6。
VM-only不变；人工guest IN错误仅作开发支撑；上游人工冷断电只是诊断，VBUS未测，
软件切电未恢复bulk、自然启动超时/重枚举/消失根因仍OPEN；不执行共享hub循环代替单设备恢复。
28项原完整scope、两个draft未合并、整个goal active。


## 2026-10-11 真实后续初始化步骤九案例通过；CI夹具失败保留并修复

[九案例独立实机证据](evidence/ws73-managed-later-real-20261011.json)
SHA256 `a44921486b773a9b58cb82e8a400d21a2d70ddbcaba8f5327dad46ae28423e5b`。
编译内核K060011963b5e、服务/冻结工具U7bd441625951、QEMU二进制
`d53eb3d1b583ff87e26cc7aec1d5f4655867d0e0891bb2beb761172f8ba35ac3`。
广播原最后STOP、扫描原START、扫描原最后STOP，各release/最后fd关闭/dup，九个
原VM全PASS/QEMU0。每例前一/两条实际成功host IN81原帧照常交付，随后保留原成功帧；
所有skip/held帧长度/SHA与对应实际Complete逐项一致，selector预算/armed/held/released
host/guest原完整读回一致，零bounded release/drop/error，原500ms deadline不变。
原请求始终Cancelled/-ECANCELED，dup第一次close保留owner、最后close撤销，Revoking→Free。
广播仅C02/C05，未触碰扫描Unknown/Setup；扫描已有真实广告Off，原START取消后只发
必要STOP，原最后STOP的迟到成功保留为Off屏障，拒绝重复STOP或假Succeeded。
同行每例实际五命令Ready，独立Managed并scan On跨越取消、迟到回复和Free，之后
实际STOP/START/STOP成功；十四条同行命令/Complete完整匹配，无跨设备STOP/未记录交通。
每例同slkd/bus、UID1000/caps0、真实随机RF20+2成功，共198轮，抓包零丢包、taint0、
无kernel fault。没有人工拔插、ganged hub重置或主机实验安装。

311工具回归与选择器实际函数ASan/UBSan依赖夹具、完整补丁链、暂停无匹配QMP属性
检查通过；新Rust/SparkLink/Virtual关闭构建及签名模块空USB VM双加载卸载通过。
编译器零警告，一条make jobserver警告保留；早期selector夹具编译错误、sandbox LSAN
限制、私有编译路径/ccache失败和构建记录log描述形状拒绝均保留，不冒充资格通过。
U7bd CI38147959246原failure也保留：共享runtime-error callback夹具漏加selector字段，
非实机失败。独立副本完整固定档案链/ASan/UBSan验证修复通过；K53a49a9bbfe4仅补零初始化
计数字段、不放宽断言，CI改为固定修复HEAD并重新验证，最终结果按精确HEAD另记录。

此前第一步骤partial+Ready同行六案例132RF、未选择队列+Ready同行六案例22RF及旧
Unknown/confirmed-Off静默队列各六例、原0x0b拒绝/捕获失败均有效且不改写。
正常启动VM累计39、维护20。当前通过受控队列和所有三个初始化recipe后续步骤的
三fd/原held帧/活动Ready同行门禁；**整项Managed、普通调度并发/结果淘汰仍OPEN**。
下一优先为普通调度与结果淘汰、当前资格镜像物理拔插/daemon不中断、四设备两组并行，
再继续完整S0–S6连接/SSAP/Profile、安全/Bond/PHY、drivers-owned backend/PM、
Native/Proxy/sandbox/发布验收。原生主机对照受VM-only约束未执行。
自然启动超时/重枚举/设备消失、软件off/on未恢复bulk、历史xHCI warning的RCA与无需
人工干预的单设备恢复继续OPEN；人工冷断电只是诊断且VBUS未测，人工guest IN错误仅
开发支撑。28项原scope及两个draft保持OPEN未合并，完整goal active。


## 2026-10-11 普通调度的真实替代队列及结果淘汰六例通过

[独立原始证据](evidence/ws73-managed-ordinary-eviction-real-20261011.json)，
SHA256 `ecf708552083431d5280d94878379a00790f496679a07b79fe52f930f5a577e3`：广告/扫描各release、最后fd关闭、dup，六个
实际source runner PASS/QEMU0。两CPU、两个SCHED_OTHER线程，每例实际ioctl
时间窗重叠43–57对；65个同域合法替代提交耗时0.84–1.23ms。原在途请求先
Cancelled，再被真实64项终态表淘汰；原ID/首替代ID（扫描再加准备ID）
在release前/后和迟到回复排空后均ENOENT。其余64项仅最后一个实际Queued，
释放后全部Cancelled/-ECANCELED，opcode/step/power0，无未选择命令逃逸。
原提交到取消128–170ms，不延长500ms原期限；dup第一次关闭仍Held，末引用
关闭Revoking到Free。实际host成功IN81原SHA/长度与原回复一致。

广告只有原C02和必要C05，扫描先实际广告Off、原1001，零未选择START/STOP；
扫描仍Unknown/Setup，不制造Ready。活动同行跨原held回复/取消/Free保持同
generation/完整Ready/Managed/current scanning On，每例14条真实命令/
成功Complete，随后STOP/START/STOP。同RF slkd/bus、UID1000/caps0随机
RF20+2，共132轮均在10秒内匹配标识、数据、地址、RSSI；零抓包drop、taint0、
无kernel fault。hold发生在RF daemon前，不能据此宣称daemon并发在途验收。

原扫描initializer替代失败EBUSY及未执行两例保留；修正后先实际核对
EBUSY/ENOENT无admission，再以合法同域STOP作未选择替代，不放宽生产
can_initialize_scan。原首批广告冻结Ue18b25aa9c1b，新扫描冻结U542f7ae311ae；
编译内核K060011963b5e、服务U7bd441625951，生产源码哈希一致，QEMU d53eb3d1b583。
原prepare错误module-tree父目录参数保留（无VM/USB执行），新独立输出修正。
316工具回归、25实际Host、19命令计划支撑保持；ABI测试忽略显式路径的
CI38150415339失败及随后sparse checkout缺头文件的CI38151129591失败保留。
修正只补 canonical pinned UAPI 依赖，U303b94c50260 CI38151508403九项成功；
证据HEAD后续CI单独核对。正常VM累计46、维护20，失败不归零。

[原后续步骤九例/198RF](evidence/ws73-managed-later-real-20261011.json)及
此前静默/活动Ready队列、首步、0x0b拒绝与捕获窗口失败证据保持。
当前通过限定于普通调度两个提交者的替代/淘汰/释放子集，**整项Managed和
完整并发/事件/权限/移除仍OPEN**。下一优先为daemon运行中的在途取消与作者
生命周期、当前资格镜像物理拔插/slkd不中断、四设备两组，然后自然
启动/消失RCA和有限单设备非人工恢复，以及其余完整S0–S6/28项原验收。
VM-only不变；人工guest IN错误只是开发支撑，hub切电和人工冷断电不是
自动恢复验收。未查明根因、历史xHCI warning及恢复事项继续OPEN，部分成果
不关闭整项、两个draft不合并。
