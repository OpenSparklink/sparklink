> 历史实施与逐轮证据汇编，绑定各节准确提交，不是当前使用指南。
> 当前资格见 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md)；
> 新读者按 [业务往返证据核对](how-to/check-business-roundtrip.md)与
> [证据边界解释](explanation/qualification-boundaries.md)阅读。原始记录保留。

# Native连接、撤销清理及用户态调用者

2026-10-12，当前实际验收内核 `1305136ce2c83d1180e84c62e96576def26816a4`。
WS73 negotiable 广播的[真实双向连接／断开](evidence/ws73-native-advertising-recreation-connection-20261012.json)
以及[已建立连接的 File 六例](evidence/ws73-connected-file-six-case-matrix-20261012.json)
已分别通过。后者实际服务／工具为 `c255811b7617211093a7e342fbdad65f2efa65cf`，
File 阶段在 slkd 启动前，不代表运行中 daemon 的完整生命周期或 canonical resync 通过。
当前在途回复结果按本文后续带源码和证据的记录核对，不能用历史无连接回归代替。

历史内核 `46db23ba8beda736908ea61465ca8815fba4d7d6`、服务88b9的VM80无连接
广播扫描20+2轮／SIGKILL交接回归保留：taint0、1293包无丢包，
[历史独立证据](evidence/ws73-native-advertising-modes-default-rf-regression-20261012.json)。
原VM75及更早的成功和失败记录也继续保留。

## 生产调用关系

Native typed UAPI → per-file affinity/generation/profile/CAP/Managed检查 →
driver-owned27字节Create及3字节Disconnect plan → 同一Host credit queue和
retained TX → 真实OUT、CommandStatus接受、匹配异步outcome。缺一不成功。
查询和广播扫描仍等Complete，raw DLI仍只允许metadata，不复用旧6字节连接。
32项有界作者历史与物理LinkObservation独立；淘汰不清除物理义务。作者取消
保留Cancelled/-ECANCELED，首fault不会被后续超时覆盖。0x1402的111支持
未证明，不宣布支持，也不把作者取消解释为硬件取消。

## release／最后File的清理

实际revoke入口取消never-selected作者请求，保留已发送/接受的procedure。
RX worker在process context调用driver prepare，IRQ Host/gate锁不跨callback；
然后按Host→gate重检handle和retirement，排入内部Disconnect。清理使用同一
三证据模型但不覆盖原作者结果，不分配公开请求ID。真实Disconnect优先于
radio stops，pending创建/物理link时不发送干扰radio控制。OUT、Status和精确
断开outcome均确认后才执行/保留真实OFF屏障，全部满足才允许Free。

原作者预算加固定5秒整体cleanup预算（最大15秒），不逐link延长。失联、
无法关联或不确定状态明确Faulted；未知link不丢弃，不假装Free。已锁存fault
不再次报普通timeout。物理事件在log失败时仍更新义务并唤醒RX。用户态观察
release最多20秒后明确报错，不能把观察超时当作清理成功。

## slkd／slctl接入

普通应用走原D-Bus控制策略，不直接获取kernel权限。每adapter Native lease
维护单调connection ID，先Allocate再Submit，调用者可在RPC丢失后按原ID
查询。租约gate保留到blocking ioctl结束，handoff busy时立即拒绝；业务锁
不跨I/O/等待。GetConnectionResult非破坏读取同一控制fd的作者记录。

```text
select <真实adapter路径>
connect <对端地址> <地址类型>
connection-result <原request-id>
disconnect <对端地址>
```

地址类型显式输入，不照抄参考lib报告解析器的固定PUBLIC假定。参数从
`[ws73.connection]`读取，模板明确列出WS73 111参考candidate：frame1、GT1、
scan32/32、interval12/12、latency0、supervision508、event0/0、10000ms。配置
校验/参考默认值不证明RF支持。WS73没有6字节legacy回退，旧无type的Device
Connect明确拒绝。旧CLI把地址发给handle签名的Disconnect错配已改成地址
入口；legacy请求也不在admission后提前设置Disconnected。

Connected由profile-specific真实物理event更新，不由Status或operation success
填充；另有ConnectionKnown/RssiKnown。失败断开不改变原Connected；loss、
类型/handle/role冲突或畸形成功保持Unknown，不继续使用旧handle。Native分支
不合成legacy ConnectionStateChanged，不自动注册未经接通的RemoteService或
Profile。D-Bus Device属性使用正确Device接口发失效信号，客户端异步缓存
在有界时间内更新。当前loss后没有kernel快照恢复，须继续实现canonical
physical查询/同步；不得把Unknown解释为已断开。

## 测试与剩余验收

11项生产operation、实际完整Host及其依赖30项（14直接Host+11operation+
5physical）、actual process-context helper2项、mixed queue21项、management
source47项、diagnostic48项、atomic ingress10项及driver全ASan/UBSan/Leak通过。
覆盖迟到建立、三证据六种顺序、handle0/65535、多link总预算、原作者保留、
prep期间断开/retire、loss仍wake、cleanup失败/在途OUT不确定、peer隔离和
radio顺序。依赖fixture范围明确，不是VFS、运行内核或空口证据。

188项Rust workspace、严格clippy和365工具测试通过；新private D-Bus验证
Connected/failed-down/Unknown、没有legacy RemoteService、正确属性接口和
有界缓存更新。原Default构造缺项、sandbox socket限制、错误Device信号接口/
即时缓存假设、helper布局lint等原失败保留，未放宽生产检查。

当前新签名VM空USB和真实双设备无连接RF20+2已回归；必须继续本版本
物理隔离、真实连接/断开与release/最后fd/dup/在途回复。还缺handle lifetime/peer原子绑定、loss后
canonical同步、数据路径/SSAP、安全/Bond、PHY/PM/Proxy等原S0–S6范围。
默认四设备资格仍0；自然RCA和非人工自动恢复未通过，全部原28项继续OPEN。
全部实验kernel/daemon/device I/O VM-only，不以源码或单项成果关闭整项。


## 独立真实连接测试门禁（首轮失败）

`ws73_target.py run --qmp-hotplug --connection-verify` 在普通 uid1000 下先执行
两端交换角色的显式地址类型0 Create、非消费结果、两端 Device Connected、
精确handle Disconnect和两端Disconnected；原广告的STOP必须获得真实结果，
失败不改写为OFF。随后保留原RF20+2回归。parent与guest各自从usbmon复算
paired OUT、原始CommandStatus、两端真实物理peer/type/handle事件；少任一证据
不通过。三个negative fixture覆盖丢证据、错误身份/handle/status及重复事件，
它们不是硬件资格。该门禁不包含connected release/last-File/dup/in-flight或SSAP，
这些仍是后续独立必需验收。


VM76（实际496内核/5f6服务/f41工具）首轮失败：397包无丢包，Create真实OUT
成功，`0x0001`的`01140100`确认成功CommandStatus，10秒内没有任何连接outcome。
作者为Faulted/-ETIMEDOUT，`flags=1`表示Status字段存在；不是OUT标志。
另一只同generation的真实广告STOP仍获得匹配OUT/Complete，但这只是一项隔离
观察，不能替代完整release/last-File/dup/in-flight验收。
[失败捕获及复算摘要](evidence/ws73-native-connection-first-failure-20261012.json)。

进一步核对发现VM76测试选错了广播模式：默认beacon的mode=0是不可连接，
posture[33]/[34]为0/0。该失败不能作为可连接模式的互通结论；缺失outcome及
故障恢复仍须核对。新增显式`slctl advertise connectable [32-hex-marker]`，
走新的SubmitConnectableAdvertising→同一Managed/driver typed recipe，固定T
mode=1、gt=2、request posture1/0；原`advertise on`和初始化保持原字节。
参考事实为libws73-usb头中的connectable/non-scannable mode1、fixed T role2及
discovery编码器posture1/0，独立实现，没有合入参考代码。两个模式都保留
原generation/Ready/marker/config范围检查，不推断连接成功。新门禁改为显式
connectable命令，独立usbmon核对49字节全部字段及成功参数Complete；
negative fixture拒绝mode0或posture0冒充可连接。先VM复测，不延长预算、
不假造outcome；默认发现路径保持原资格和回归范围。
两只连接成功是有连接生命周期验收的前置条件；相关issues仍OPEN。


VM77（496内核/6517服务与工具）的mode1固定T对照仍失败：397包无丢包，
49字节参数逐字段符合mode1、role2、posture1/0且真实Complete成功；Create
OUT和Status成功，10秒内没有任何物理连接outcome。另一只真实STOP成功，
QEMU退出0。说明仅改广播模式/姿态不足以证明互通。
[固定T对照失败摘要](evidence/ws73-fixed-t-connection-failure-20261012.json)。
6517精确CI38194423197为9/9通过，仍不算硬件连接成功。

连接门禁继续加强前置证据：先以真实扫描听到可连接广播的随机marker、完整
数据、对端地址及RSSI，再获得真实扫描OFF Complete后发Create。离线再核对
对应RX捕获及scanner STOP。这可区分广播不可见与已可见但连接无结果，
不将额外等待算作更长Create预算。接下来比对参考Host协商角色、local address
设置和固件行为。connected release/last-File/dup/in-flight和自动恢复仍未验收。


VM78（496内核/6517服务/8066工具）进一步证明固定T可连接广播空口可见：
随机标识/data/address/RSSI-14在140ms匹配，usbmon真实RX与scanner OFF独立
复算，Create确在OFF之后；仍仅Status成功，10秒内无连接结果。411包/丢包0、
QEMU退出0。所有已捕获IN的HCC槽检查也只见Complete、discovery和Status，
没有被当前service/queue过滤掉的连接事件；这不证明未提交读取的端点无数据。
[空口可见后的失败](evidence/ws73-fixed-t-air-visible-connection-failure-20261012.json)。

新增显式`advertise negotiable [marker]`对照参考minimal_server的mode3/role0/
posture0/1、proposal100/100，使用同一typed recipe，默认beacon保持mode0。
同一未发布SubmitConnectableAdvertising接口现在显式带negotiable布尔选择，
slctl与daemon同步修改；公开C/UAPI布局未改。新的Rust角色枚举只有FixedTerminal
和NegotiableTerminal，其他能力没有模拟成功分支。

VM门禁的`--connection-advertising fixed-t|negotiable-t`必须与connection-verify
一起显式选择，parent/guest/捕获49字节必须相符。默认仍固定T；可协商对照
不复用固定T的通过声明。190项完整Rust回归、371项工具测试、严格clippy与
公开C头核对通过；这是源码检查，可协商真实连接仍待VM验收。


VM79可协商T对照也失败：mode3/role0/posture0/1/proposal100全字段和参数Complete
确认，随机广播/RSSI-13在140ms内匹配，真实scanner OFF后Create仅OUT/Status
成功，10秒无outcome；411包/0丢包/退出0。
[可协商T失败证据](evidence/ws73-negotiable-t-air-visible-connection-failure-20261012.json)。
下一做参考Host VM对照，检查完整启动、local address设置和连接序列，而非继续
改变未解释参数。原f4d85d0参考仓库保持clean，已在私有目录构建/哈希其两个
minimal示例及静态库；只编译，未在主机执行或触及USB。SDK代码没有合入生产。
Meson导入路径、只读ccache、staged header路径和共享/静态产物记录误判均保留。

VM80确认本提交实际88b9服务保留默认北极星RF20+2和无连接SIGKILL交接：
1293包无丢包、taint0、退出0；两条真实停止回复、非拥有者Free/Off/Ready，
后继服务四次initializer拒绝且该阶段没有新device command。guest-only退役
不算物理拔插或自动恢复。该通过与三次真实连接失败分别记录；连接/connected
release/last-File/dup/in-flight及原28项仍OPEN。下一同时补未执行连接队列的
真实VFS取消门禁：该项不需要先建立物理link，也不能以源码测试替代。


## 真实未执行连接队列门禁（待VM）

`--managed-queue-connections`扩展现有confirmed-Off/Ready-peer队列门禁：保留
原六项发现队列回归，再在两只设备交换target/peer各执行release、最后File关闭、
dup第一/最后关闭，共六项真实Create取消。单vCPU、特权FIFO临界区小于50ms
保证不会被TX worker选中；Queued结果与完整usbmon排除Create/Disconnect OUT。
这不是普通调度并发验收，也不制造credits、状态或控制器回复。

Connection结果是author-only：显式release仍保留fd，必须读取精确Cancelled/
-ECANCELED且无Status/outcome/handle。最后File关闭后作者结果不可读取，
记录null，依据350ms后实际Free/Ready/Off和无OUT确认队列清理；不伪造作者
观察。dup第一次关闭仍Held且同一请求Queued，最后关闭才清理；外部观察fd
前后都须ENOENT。peer在每次临界区前/中/后保持同generation的Ready、Held、
scanner On，并在正常调度下获得真实START/STOP回复。bootstrap和两组活动
分别逐帧复算。该项通过也不证明connected或在途回复清理，原issues保持OPEN。


VM81（496内核/88b9服务/903e工具）保留旧发现队列六项回归，但新连接第一项
Create入队返回EBUSY，尚未发生任何连接提交/取消资格；原失败保留。实际Free/
Ready/Off仍不能重新使用连接，是新租约提交未清除Host旧revoking造成。生产
修复在Linux46db23b：copyout后仍按Host→gate重检retirement/fault/quiet/physical
obligations，并仅在已settled的原撤销后清除旧cleanup bookkeeping；不重置credits、
radio truth、作者history，也不清除未知/在途physical义务。pending旧回复、link、
fault或未完成revocation均拒绝新提交。源码33项实际Host及依赖+2项worker helper、
48项management源码、11项operation及C codec ASan/UBSan/Leak通过；完整新内核
构建和VM重测尚待，不将修复意图记作实机通过。原FIFO和fixture/include/LSAN
环境失败保留，未放宽生产条件或关闭检查。


VM82已在实际46db内核/cd64065服务与工具上完成上述真实门禁：原Setup六项、
原发现队列六项以及新Native Create队列六项通过；每组peer有36条真实参数/启停
命令及匹配Complete。原发现矩阵后的新租约现在可接受Create为Queued。
显式release读取Cancelled/-ECANCELED，无Status/outcome/handle；last File关闭
后保持null而非虚构作者结果；dup首关仍Held/Queued，尾关后350ms内Free/Ready/
Off。外部fd前后ENOENT，peer完整metadata、租约和scanner On保持，且正常
调度下真实启停成功。所有临界区36.8–63.3微秒，小于50ms；支撑范围仍是特权
FIFO，不能宣称普通调度/在途/connected验收。
[旧内核EBUSY失败](evidence/ws73-native-queued-connection-first-admission-failure-20261012.json)，
[修复后独立复算证据](evidence/ws73-native-queued-connection-file-resume-20261012.json)。

新内核完整构建、source/config稳定、无warnings、八export/ELF/module验证和
受信模块空USB NVMe/Btrfs VM23通过，taint0。VM82完整1451包无丢包，quiet
连接窗口及整个扩展阶段均无Create/Disconnect OUT；parent与独立sealer的全部
queue/setup/peer/RF22证明相同，冻结输入逐hash复核。随后双设备RF20+2通过，
其中一次人为guest IN错误只是测试支撑：不记自然RCA或非人工自动恢复。
修复对应具体sticky-revoking缺陷的证据，不关闭任何完整issue。S0–S6/28、
真正连接与connected revoke、在途回复、canonical/peer lifetime和其余生态仍开放。

## 2026-10-12 当前源码部分初始化／在途 File 矩阵

Linux `46db23ba8beda736908ea61465ca8815fba4d7d6`、实际编译服务与冻结工具
`cd640655dcd153b8cfd06f6ae27224d34ef7cac1` 的 VM83–91 九例均通过：广播最后
OFF（step1）、扫描 ON（step1）和扫描最后 OFF（step2），各覆盖显式 release、
最后 File 关闭、dup 首关／尾关。双 vCPU 普通调度；QEMU 仅暂留一条真实成功
IN81 帧，不生成回复或 credits。作者取消不会改为成功，旧真实回复排空后按实际
radio truth 清理；仅广播已配置时仍是 Setup，禁止补造 Ready。

同行保持同 generation 的独立 Ready、Managed Held 和扫描 On，并获得真实
启停回复。每例随后 RF20+2，共198轮、10815捕获包、零丢包、taint0、QEMU退出0。
独立复算全部原帧哈希、UAPI 记录、setup／partial／peer／RF 证明及冻结输入。
普通应用 UID1000/caps0、同 slkd/bus；File探针与调度控制属于 VM 内测试工具。
[九例证据](evidence/ws73-current-later-partial-file-matrix-20261012.json)。
这是 discovery 部分初始化和在途真实回复取消的当前源码资格，补齐上一记录的
对应待验项；不代表连接在途／connected 撤销、完整 Managed 或普通调度下所有
未选择队列竞争。后续人为 guest IN 错误仅测试支撑，不是自然自动恢复。

参考未改动 `libws73-usb` f4d85d0 的 maintenance VM24 未进入连接：server 的
芯片 reset 后 guest 等待 boot-mode 重枚举超时，client 未启动。主机只读枚举看到
目标变成两个端点的 boot 状态，说明不能笼统判为“芯片完全未重枚举”。随后
当前驱动 VM92 从该状态完成启动、RF20+2 和 QMP guest 移除／重加：1369包，
零丢包、taint0、退出0、同 slkd/bus。
[参考失败及 Native 后续启动对照](evidence/ws73-reference-reset-native-boot-contrast-20261012.json)。
后续运行未再次切 hub 电源；它是受控启动对照，不能宣称服务自动恢复成功。

正常 VM 累计92／维护24。下一定位参考 guest reset/open 与主机重枚举／描述符
更新边界，再比较真实连接启动和地址／序列；同时推进 canonical 状态重同步、
peer/link lifetime 与旧实现迁移清理。S0–S6、原28项、SSAP／安全／Profile／PHY／
PM／Proxy、默认四设备并行、自然故障根因和非人工自动恢复保持开放。
整项不因这九例关闭；所有实验继续 VM-only，历史失败证据保留。

参考失败的 guest kernel 日志进一步确认：1-2 实际 disconnect 后重新枚举为
full-speed、bcdDevice1.00（device3→4）。故障定位应收窄到参考进程的 libusb
设备发现、描述符缓存和 wait/open，而不能宣称 QEMU 完全没有重枚举；根因
尚未查明。原失败状态和所有捕获不改写，日志哈希加入上述对照证据。

## 参考 VM 的 libusb 发现机制与真实连接对照

[设备发现实验与后续依赖](WS73_REFERENCE_DISCOVERY_LAB.md)：无udev VM26
直接记录旧 server context 在新boot出现后34次仍返回旧runtime对象，fresh context
和sysfs都已更新。补齐udev VM27原参考二进制通过启动，真实Create OUT/Status
和双端成功outcome独立核对，client退出0；719包/零丢包/taint0。参考SSAP日志
PASS仍只作线索，未声称本项目SSAP完成。此前的VM25 socket权限失败、离线
脚本syntax失败和旧参考启动失败保留；参考环境原因不关闭自然硬件RCA。
下一控制变量比对0x0405本机地址设置、扫描参数与广播数据；Create和广播
参数本体已经与Native旧失败逐字节一致，不再盲目试参数。

## 广播集合删除/重建的真实因果对照

[生命周期矩阵与接入设计](WS73_ADVERTISING_SET_LIFECYCLE.md)：VM28–31证明
地址调用省略、被动扫描、Native1600/800及marker数据均能在参考路径连接；
VM32/33/34/35前置mode0配置后均只有Status、无outcome，去掉OFF或改姿态/GT
策略未恢复。VM36只新增真实0x0c08删除集合，再重建mode3便恢复双端连接。
九例6183包/零丢包，每个非Create命令Complete单独核对；Native VM95仍失败，
411包，实际46db/cd64065。下一接入每设备Host的实际资源状态、原子重建recipe
和部分撤销清理，禁止通过改变默认mode0、raw任意写或推测Ready绕过。

## 当前生产接入（待新VM）

Linux签名1305136c将已确认的广播集合参数/缺失状态接到每注册Host；配置改变
时，在同Host锁和同cookie/原期限内前置真实Remove，再参数/数据/可选scan
response/启用。最多5步，驱动用内部重建标记独立校验，raw query白名单不变；
相同参数仍三步。实际匹配Complete且OUT成功后才更新集合状态，取消后的迟到
回复更新物理事实但不翻作者结果。删除后未重建保持Setup，清理保留真实缺失
而不发送无效STOP；已选中创建要等原回复，成功后按实际新集合清理。
广播admission改为Host→gate，与管理提交和物理ingress一致；未结算的旧参数
不允许新参数recipe根据旧缓存提前决定。新结果power step随前缀平移，旧配置
不会在租约交接时清空。

42实际Host及依赖+2cleanup helper、23queue/plan、48management、diagnostic
边界和11connection操作/实际C codec（ASan/UBSan/Leak）通过；451092个discovery
codec检查含前缀标记/错误步骤/失败shape。初始fixture未带集合事实、4→5界限
未同步及沙箱LSAN失败均保留，修正后不放宽生产校验或加全局allow(dead_code)。
工具验证仅显式接受3或重建4步，重建必须有实际删除/参数/数据/启用回复链、
次序和实际power；382工具测试通过。完整新内核构建source/config稳定，仍待
受信模块VM和真实Native连接、删除/重建FD门禁。不能以源码通过关闭整项。

## 新内核真实双向连接通过，connected FD门禁继续开放

VM97使用实际Linux `1305136ce2c83d1180e84c62e96576def26816a4`、服务与冻结
工具 `fdfd816c8d27ba6235b6d2a214b5dd56350ac2f9`，可协商T广播的两个方向
Connect/Disconnect均通过，handle0、结果flags7，随机空口数据/地址/RSSI先匹配
（139/140ms）。每次先真实Remove，再参数/data/enable及成功回复；两个方向
Create/Disconnect的OUT、Status及双端物理outcome由完整USB捕获复算。
随后mode3→默认mode0的删除/重建也经真实四步链和power回复核对，RF20+2及
QMP guest移除/重加通过。普通CLI UID1000/caps0、同slkd/bus，1377包/零丢包、
taint0、退出0；准备输入全部逐hash重查，parent/guest与独立sealer证明一致。
[新Native连接证据](evidence/ws73-native-advertising-recreation-connection-20261012.json)，
SHA256 `3e9b538d5ba518c30684586dc2950ce4bf374b2c0a8a8ad5b4568c8544a0f1b8`。

完整内核/source/config和8exports检查、受信模块空USB NVMe/Btrfs VM37通过；
服务重新实际编译fdfd。初次服务checksum输入拼错由校验在执行前拒绝，改为
实际三文件重新计算并与旧合格manifest核对，原失败保留。sealer初次将22条RF
与包含末尾connection proof的23条guest列表比较失败也保留，之后明确比较
RF22+完全相同connection proof，没有重跑或改写原捕获。精确源码CI38208556802
九项成功；参考/VM95失败不覆盖。

该通过仅解决当前可协商模式普通连接路径，不能转移到fixed-T、SSAP、安全、
connected release/last File/dup/inflight、新删除/重建真实FD边界、物理拔插或
非人工恢复。下一优先新源下FD/部分初始化与connected撤销/同行隔离门禁，
再canonical状态和peer/link lifetime、完整S0–S6原scope及旧实现清理。
默认四设备并行、自然启动/bulk/设备消失根因和非人工恢复仍OPEN。
正常VM累计97/维护37，所有实验VM-only，部分成果不关闭整项。

新源VM99另外独立通过原Setup六项、发现队列六项、Native Create队列六项和
独立Ready scanner-peer：每组36条真实peer命令/回复，1451包/零丢包/taint0、
退出0，随后RF22，普通CLI同slkd/bus。显式release作者Cancelled/-125，最后
File后仍记录不可观察null，dup首关Held/Queued、尾关Free/Ready/Off，外部fd
前后ENOENT；扩展窗口无Create/Disconnect OUT，未制造credits/Complete。
[新源File回归](evidence/ws73-native-advertising-state-queued-file-regression-20261012.json)，
SHA256 `da835edeeb854f091ffac7fe753ed99947570d1cff847681194a31546581b5ad`。
特权FIFO支撑及人工guest IN错误的限定不变，不证明connected/inflight/自然
恢复。prelaunch尝试98参数缩写歧义在VM/USB前拒绝，原log保留，99使用完整
参数；累计97→98→99不回退。新删除/重建真实FD与原partial当前源回归仍待。

删除/创建实际回复held的File矩阵现已独立通过六例（VM102–107，7302包、
RF132），资源缺失Setup/重新创建Ready、作者Cancelled与独立Ready peer均
核对。见[资源File矩阵](WS73_ADVERTISING_SET_LIFECYCLE.md)。两次验证器失败
保留，connected及运行中daemon fd清理、自然自动恢复不转移资格，下一优先。


## 2026-10-12 真实 Create 在途 Status／outcome 的十二例 File 验收

[独立重算完整证据](evidence/ws73-inflight-file-twelve-case-matrix-20261012.json)，
SHA256 `5ff072aca5136e9e673b156687f314a2a68d0db09c22b5720e63f3396d1714d7`。
实际编译内核 K1305136ce2c8、服务及冻结工具 U0a980e5d9b73，SDK111；源码
CI38221333345 精确 HEAD 九项通过，395 工具回归通过。后续文档／证据提交
不是另一次服务编译，不改写实际源码来源。

VM117–122 保留实际成功 host IN81 的 Create Status 原帧；VM123–128 先交付
实际 Status 原帧，再保留实际物理 Up 原帧。两种角色各 release／最后 fd／dup。
本组均由抓包证明 Status 和 Up 位于不同 USB 聚合帧；若以后合并，只能另记
combined-reply，用完整原帧验证，禁止拆帧制造“仅 Status”或“仅 outcome”。
全部 QMP skip／hold／release 读回、原帧大小／SHA256 与对应捕获一致，无自动
bounded release／drop；只保留及交付真实原始 bytes，未生成 DLI 或 credit。

Status 保留时作者 OnWire、presence flags0，实际目标 credit0；outcome 保留时
作者 AwaitingOutcome、presence flags1、实际 credit1。flags 的掩码1、2、4分别
表示 Status、outcome、handle 存在；**没有 OUT 标志**，OUT 成功单独用 usbmon
提交／完成证明。dup 首次关闭保留同一 File 作者结果和 Held，150ms 无 Disconnect；
最后关闭才撤销。显式 release 的作者变为 Cancelled/-ECANCELED，已销毁的最后
File 不伪造可查询作者。撤销保持 Revoking，晚到真实 Up 进入物理清理义务，之后
才发出匹配 handle 的实际 Disconnect；实际 OUT、Status、两端匹配 Down 完成后
Free／Ready，目标 credit1。显式 release 的最终作者仍 Cancelled，flags7 表示
实际 Status/outcome/handle 齐备，不能改记 Succeeded。

同行原 generation、完整 Ready 元数据、credit1、独立管理权保持一致；预期的
对端 Up/Down 不算无关设备重置，之后自己的广播 STOP、扫描 START/STOP 实际
成功。VM129–130 另做两个旧已建立连接 dup 回归。每例之后普通 UID1000/caps0
RF22 成功，共308轮、17234包、零drop、taint0、QEMU0；RF阶段 slkd/bus不重启。
**File 阶段在 slkd 启动前，仍未验收 daemon 跨 File 清理不中断。**

VM115/116 两次原失败保留：前者测试误把 OUT 作为 flags 位，错误期望 flags1；
后者把动态 command credit 当作不可变 metadata，错误期望保留 Status 时仍为1。
前者原失败后有 host bounded release，不属于合格帧交付；后者虽观察到晚到连接
正确清理，整例仍 FAIL。分别修正检查后重新跑十二例及两个回归，不回填旧成功。
usbmon 和 guest marker 只在 guest 时钟比较；host QMP 时间仅作来源，不能混用。

下一依赖：运行中 slkd 的 Create 撤销／晚到连接归属与清理、canonical loss resync
及 peer/handle lifetime 原子绑定；然后完成当前源原 partial 矩阵、物理和四设备
矩阵。旧内核调用迁移继续按[刷新审计](evidence/ws73-legacy-kernel-call-refresh-20261012.json)
及[三类清理清单](LEGACY_CLEANUP_20261011.md)推进：Native Host 仍经旧 mgmt 的
re-export 使用 canonical queue，core／USB 仍消费 dev/transport，serdev 仍有
全局 parser 初始化及 enum／FFI 调用。先迁真实调用者和源码测试，再删重复逻辑；
不能将整文件删除、global dead_code 或未接通其他总线记作完成。
自然启动/bulk/重枚举/消失 RCA、非人工恢复、SSAP/安全/Bond/Profile/PHY/PM/Proxy
与完整S0–S6仍OPEN，原28项issues和两个未合并draft不变。VM-only，本轮无hub切电
或人工拔插；正常尝试130、维护37，完整goal active。


## 2026-10-12 权威观察连接表／lifetime／事件屏障：双角色实机通过

[独立复算证据](evidence/ws73-atomic-link-snapshot-both-role-20261012.json)
SHA256 `b0daa69c596a9b7b0f049fe71ebba39f6ecb0afbe07eeda32e829cc7f61e6ab8`。
实际内核为本轮 fault-aware 快照源码（证据记录完整 HEAD），实际服务及冻结工具
`4dbf59765b4cad5a85ef3a307302d549a247756a`，SDK111。VM131/132交换真实Create角色，
维护VM38/39只做签名模块空USB加载卸载；VM-only，未安装主机实验内核。

`SL_IOCTL_LINK_SNAPSHOT` 是只读、非消费的同registration接口，C/Rust/Python
一致的432字节结构。在与physical ingress相同的 Host→gate→event-log 锁顺序下
复制观察连接表及event_seq屏障；释放所有IRQ锁后copyout。最多16条，每条含
lifetime、handle、local role、address_type、address，尾部及reserved全零。
它是已观察物理事实的快照，不是伪造的控制器List Complete，也不是命令作者结果。
重复相同Up不重分配lifetime；真正Down后handle重用得到新lifetime；冲突、容量或
计数耗尽、transport fault、procedure uncertainty明确Unknown，不假装已确认空表，
不清除内部physical cleanup义务。fault Unknown和handle重用当前由实际源码测试
验证，不声明本轮已做相应实机fault／重用VFS资格。

两例真实读表：Create前Known空表/revision0；两端实际Up后Known一条、lifetime1/
revision1，完整identity与物理原event一致；dup首次close保持File/Held，最后close
引发真实Disconnect/两端Down后Known空表/revision2。每次snapshot.event_seq覆盖
对应原Up/Down seq。坏pointer返回EFAULT，非零reserved／尾表返回EINVAL，旧gen
返回ENODEV；失败不改caller input，前后完整snapshot一致，不消耗事件或改变状态。
同行注册、元数据、管理权及真实radio控制保持；每例后普通UID1000/caps0 RF22，
共44轮、2462包零drop、taint0、QEMU0，RF阶段同slkd/bus。File仍在slkd启动前。

45实际Host+2prepare源码、link源码测试、4完整权限分类覆盖、192 Rust离线、37 Python
完整ABI（含i386静态布局）/实际shared-lib负向测试、395工具回归通过；最终image/
modules构建source/config稳定、无compiler warning，八export/ELF和签名空USB通过。
源码CI38232821945精确HEAD九项成功。首次重编译暴露两个旧FFI wrapper缺少prototype
的warning，准确声明后重建；C头缺array宏及本地ccache目录不可写的失败、缺测试
socket/私有dbus路径的环境失败均保留，不将它们记为合格产物或功能失败回填成功。

**这项是canonical snapshot基础，不等于slkd resync或原子peer-disconnect已完成。**
下一批：slkd在启动/事件丢失时用snapshot恢复并按event_seq拒绝旧link事件回放；
peer身份含address_type，支持每连接lifetime，不继续混用旧address-only/handle缓存；
disconnect经内核在admission原子检查generation/peer/lifetime，再接通cancel晚到link
清理和运行中daemon真实验收。迁移调用者和回归后删重复旧状态实现，未发布UAPI可
同步修改，无兼容期。自然启动/bulk/重枚举/消失RCA、非人工恢复、四设备及完整
S0–S6仍OPEN。正常尝试132/维护39；原28issues、两个未合并draft和完整goal保留。

## 2026-10-12 Peer/lifetime-bound Disconnect: qualified admission and selection

[Independently recomputed live evidence](evidence/ws73-peer-lifetime-binding-both-role-20261012.json)
uses compiled Linux `38997dc457be` and service/tools `d58fe5c76b5f`. Linux
`3840ec2ba70c` subsequently changes only the offline release fixture's errno
adapter; production sources are identical. The unpublished submit UAPI is v2,
128 bytes; the C symbol is `slk_connection_submit_v2`. Result and snapshot
versions remain v1. Historical 112-byte v1 captures remain historical evidence;
the adapted current unit fixture is explicitly offline, with an immutable v1 copy.

Disconnect carries generation, handle, lifetime, role, address type and address.
The kernel checks the exact current observation at admission, and again when
selecting the queued command. Admission mismatch returns ESTALE without creating
an author record; selection mismatch fails locally without OUT or credit use.
Internal File-revocation cleanup retains its existing physically evidenced path.
This does not promise atomicity across the later selected-command/USB OUT/hardware
window. Actual queued handle reuse is covered by production Host source tests,
not a real firmware reuse race in this batch.

slkd no longer resolves native Disconnect through the address-only Device cache.
It queries the canonical kernel table and rejects unknown or ambiguous peers;
`disconnect <address> [type]` can select an explicit address type. Native bare
handle `DisconnectDevice` returns NotSupported. `slctl connections` prints the
canonical snapshot and full reference; `disconnect-link <address> <type> <handle>
<lifetime> <role>` submits the explicit tuple and waits for the actual result.
The Device property projection still has address-only/event-delta state. Its
startup/loss resync and address-type migration remain open; the new API does not
claim those are fixed.

Real VM attempts 133/134 each establish a physical link, then submit seven actual
VFS mismatches on the Managed author fd: lifetime/type/address/role return ESTALE,
zero lifetime EINVAL, stale generation ENODEV, old version EOPNOTSUPP. All fourteen
reject without an author result, table change or target/peer wire command. Each
case also repeats first-dup-close retention, last-close actual Disconnect and
both physical Down events, independent peer control and RF22. These File gates
run before slkd and do not prove a running daemon survives File revocation.

VM135 runs ordinary UID1000/capabilities-zero slctl through a running slkd. Both
roles obtain original `connections` snapshots, submit the exact displayed
reference, and complete Create/Disconnect with independently captured OUT,
Status and both peers' physical Up/Down. RF22 and QMP guest removal/readdition
succeed without restarting slkd or D-Bus. QMP removal is not physical unplug or
natural automatic recovery. All three VMs have taint0, exit0, 3,839 captured
packets and zero capture drops; total RF66. Signed empty-USB smoke raises the
maintenance count to40. No hub power cycle was used in this batch.

Offline checks: 193 Rust workspace tests, strict clippy, 37 Python/C/i386/shared
library ABI and negative tests, 398 tool tests, 12 production operation tests,
48 actual Host source tests plus two cleanup-prepare tests, and five portable
link-observation tests. Preserve the initial kernel build failure (old C size
assert), sandbox LeakSanitizer/ptrace failure and first CI failure (missing fixture
ESTALE); corrected checks are separate records. Final CI is recorded in the
issue progress receipt after independent readback.

Next: canonical startup/loss resync using the snapshot event barrier; typed peer
identity and deletion of the duplicated native Device event state; running-daemon
cancel/late-link/revoke gates; actual handle reuse and selected-to-OUT races;
current-source physical unplug and four-device parallel regression. Natural
boot/bulk/re-enumeration/disappearance RCA and nonmanual recovery remain open.
All original28 issue scopes and the unmerged drafts remain open; full S0–S6 goal
remains active. Existing WS73 RF/lifecycle evidence is retained at its exact source.

## 2026-10-12 Canonical daemon resync and actual subscriber overflow

[Independently recomputed evidence](evidence/ws73-canonical-resync-real-overflow-20261012.json)
qualifies compiled user source `a4f29fc` (VM136) and source/tools `9af145e`
(VM137), with the unchanged compiled kernel `38997dc457be` and SDK111 files.
The source hashes of all compiled crates/policies are identical between the two
service builds; only the explicit VM supervisor/tools change in the second.
Both source CI runs passed all nine jobs (`38243438290`, `38244700408`).

The daemon reads a complete canonical table when its native subscriber starts,
after a current physical link notification, and after a reported event gap.
It validates registration/index/profile, the triggering event minimum sequence,
and monotonic revision/replay position before replacing the observation. Link
notifications at or before the snapshot barrier do not update or re-query the
connection state. Failed reads remain Unknown and retry once per second in the
same per-adapter subscriber, with skipped timer backlog and cancellable shutdown.
No transport reset or command is used to refresh observation.

The previous Native Up/Down delta implementation, its native handle writes/lookups
and the Device role/type fields are deleted. The conn_handle field remains for
legacy-only callers. Native Connected/ConnectionKnown and device
listing derive from the canonical table. RSSI and opaque discovery bytes are
preserved during connection refresh. The existing address-only discovery object
is an alias: multiple current typed peers/lifetimes at that address are Unknown,
not arbitrarily selected. Full typed peer object paths remain to migrate; the
canonical tuple and explicit Disconnect retain type and lifetime. Native legacy
GetConnectionInfo is explicitly NotSupported. Legacy-only state/callers remain
pending their own replacement and regression, not claimed cleaned wholesale.

`NativeLinkObservation` reports daemon event barrier/revision/Known; slctl show
also prints actual EventsLost. Offline private D-Bus tests cover initial snapshot
publication, query failure then resync, a reused-handle/new-lifetime snapshot,
old Down replay suppression, generation/index/profile/revision/sequence/tail
rejection, ambiguous address aliases and preserved RSSI/data. These are actual
daemon code with injected ioctl dependencies, not real firmware replay races.
194 workspace tests, strict clippy and 402 tool tests pass.

VM136 preserves real two-direction canonical peer Disconnect and RF22 through
QMP removal/readdition. VM137 uses an explicit test supervisor: it SIGSTOPs only
the guest daemon while actual kernel/radio scanning continues, then SIGCONTs it.
The application remains UID1000/capabilities0. Both roles produce at least40
independently captured matching original radio reports after stopping, advancing
the actual32-event ring beyond capacity. Both actual subscriber lost counters
increase by8 and Known resumes at the full snapshot barrier. Non-owning observer
bytes show both registrations Ready/Managed Held and unchanged empty physical
connection tables throughout the pause. No USB command occurs during either
pause. This pauses the whole guest daemon, not an isolated per-device actor;
there is no production pause/injection/mock control.

The supervisor pauses last13.32/12.61 seconds, are bounded by a90-second radio
progress deadline, and resume the original daemon on ordinary exceptions. Both
roles subsequently complete real Create/Disconnect, RF22 and QMP replacement;
slkd and D-Bus remain unchanged. Combined VM136/137: RF44, 2914 captured packets,
zero drops, taint0, exit0. Normal VM count137; maintenance40. No hub cycle used.
These are controlled **subscriber** loss/resync tests with Known empty tables.
Established-link loss reconstruction, real reused-handle/selected-to-OUT races,
and same-generation read-error retry on real hardware remain unqualified. QMP
removal observes Unknown and a new generation starts Known; it is not natural
same-device fault recovery or physical unplug acceptance.

Next dependencies: typed peer object namespace/callers → live established-link
loss and running-daemon cancellation/late-link/revoke gates → removal of migrated
legacy state → current-source physical and four-device tests. Keep natural boot,
bulk, re-enumeration/disappearance RCA and nonmanual hardware recovery open;
full S0–S6/28 original scopes and both draft PRs are unchanged, goal active.

## 2026-10-12 Typed Peer and immutable Connection objects, real handle reuse

[Independently recomputed evidence](evidence/ws73-typed-peer-lifetime-objects-20261012.json)
qualifies compiled service/tools `5f86cc5`, production implementation `28bdf6f`,
unchanged kernel `38997dc457be` and SDK111. Tool commit `5c5df94` first failed
VM138 because its strict GetInfo verifier omitted the real same-adapter Selected
preamble. Original correct GetInfo and the failed run remain preserved; `5f86cc5`
only corrects that parser and rejects foreign/duplicated selection. Compiled crate
and policy hashes are identical in the failed and successful service builds.
Both source CI runs (`38249716605`, `38250456167`) passed all nine jobs; this also
shows why green offline CI alone is not hardware acceptance.

Canonical physical links now publish `org.sparklink.Peer` at
`<adapter-generation-path>/peer_t<type>_<address>` and `org.sparklink.Connection`
children at `.../link_<lifetime>`. The typed peer reports its exact type/address
and associated lifetime paths. Connection generation, address/type, lifetime,
handle and role are immutable. GetInfo reads Known/Connected together from the
canonical table; neither an author result nor D-Bus publication metadata is a
physical state source. Same-lifetime identity changes invalidate the observation.
Address-only discovery objects remain explicit aliases, not typed identities;
discovery report address-type inference remains unqualified. No unsupported
Peer Connect or ambiguous Peer Disconnect capability is advertised.

Known Down retires the connection and peer interfaces. Unknown retains previous
identities with Known/Connected false, without inventing a successful Down.
Publication/removal errors retain pending work for per-adapter bounded-rate
refresh; cancellation/removal includes active and retiring object paths. Parent
Peer publishes before its Connection children; enumeration exposes a child only
once both interfaces are published. The metadata maps track publication only.
Connection SubmitDisconnect uses its immutable complete reference and existing
credential/lease gate; the kernel checks admission/selection as before. Removed
objects never redirect to a new connection even if the firmware reuses handle0.

CLI `connection-objects`, `peer-info <path>`, `connection-info <path>` and
`disconnect-object <path>` are connected to this production path. CLI checks
selected registration and canonical object identity, allocates the author request
only after object lookup, then waits for the original kernel result. The normal
real connection gate now uses object Disconnect rather than manual handle fields.
Direct canonical connections/reference APIs remain diagnostic consumers and do
not reintroduce a Device handle cache.

195 workspace tests and strict clippy pass. Actual daemon/private D-Bus dependency
tests cover same address with type0/type1, independent lifetime children, Unknown
retention, refusal to rebind an unchanged lifetime, both-interface retirement,
same-handle replacement and removal rejection. 406 tool tests verify original
both-owner publications, peer membership, physical Up matching, original receipts,
stale-refusal scopes and no-wire intervals. Multiple types at one address remain
source/dependency tests; the actual live firmware type in this batch is0.

VM139/140 independently validate both owners' typed Peer/GetInfo/Connection after
raw successful Up, exact object-targeted Disconnect and both raw Down outcomes.
Both real controllers reuse handle0 in the second role phase: lifetime1 objects
are retired and lifetime3 objects have different paths. Each VM checks two old
objects after first Down, two while the same-handle replacements are live, and
two after second Down. Combined12 stale cases/24 original CLI refusals emit no
USB command on either radio and no submitted author result. This is real handle
reuse and **removed-object** rejection, not a queued stale invocation or an atomic
selected-to-OUT race. Original role/type/address/handle and full path receipts
are independently cross-checked against actual captured outcomes.

VM140 also repeats the explicit whole-guest-daemon pause/real32-event-ring
subscriber overflow: both roles lose8 records and automatically regain Known
before object connections continue. Its overflow tables are empty, not an
established-link loss reconstruction. Both VMs complete RF22/QMP removal/readd
without restarting slkd/D-Bus, UID1000/caps0, taint0/exit0. Aggregate RF44,
2916 packets/0drops. Normal attempts140 (includes failed138); maintenance40.
No hub cycle, host kernel installation or native host test was used.

Next: real established-link subscriber loss/Unknown recovery and running-daemon
cancel/late-link/revoke; typed discovery identity and SSAP consumers on lifetime
objects; migrate remaining legacy callers/tests before deleting their fields;
current-source physical and four-device regression. Keep natural boot/bulk/
re-enumeration/disappearance RCA and nonmanual hardware recovery open. All28
original issues, two draft PRs and the complete S0–S6 goal remain unchanged/open.
