# WS73 根因定位与每设备自动恢复

2026-10-10 用户追加要求。本文补充完整 S0–S6 与第一北极星；原 issues、
广播发现 20 轮与随后四设备两组并行保持。新增验收：**故障恢复不依赖人工
拔插，恢复单只不影响其他设备，恢复后无需重启 slkd**。未查明根因或仅
通过重插恢复时，不关闭相关 issue。当前本文中的恢复状态机是待实现设计，
不能把已存在的动态 adapter 或重新枚举支持算作完整自动恢复。

## 来源与当前实机事实

标准、SDK、libws73-usb、OpenHarmony、合成模型与本项目实机分别标注。
私有 SDK 只用于读取调用约定和独立实现；不提交固件、校准、私有库或反汇编。
继续参考 libws73-usb 的 USB/HCC、BSLE、广播/扫描、命令状态和双端 gate；
其作者的实测结论不替代本项目实机验收，不能照搬进程全局状态。

用户重插后四只设备可读写、无主机接口驱动。固定端口为 1-2.1.1–4。
以下实机结果使用SDK/us，已确认与combined-1.10.110逐字节相同。用户追加
指定111后，已验证拆出111并实机执行，当前失败在非零SLE RX subtype，
尚未完成Ready；版本不得混写。
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

初始策略上限拟为首次尝试加两次恢复，退避1秒、4秒并加有限jitter；每阶段
与整体都有 monotonic deadline。BSLE阶段10秒、单OUT3秒、单查询10秒沿用
当前边界；整体预算由固件下载次数和总时长固定上限约束。所有限值须能
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
