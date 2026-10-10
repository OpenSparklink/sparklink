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
