# Native连接、撤销清理及用户态调用者

2026-10-12，生产内核 `46db23ba8beda736908ea61465ca8815fba4d7d6`。
完整bzImage/modules构建通过，源码/配置稳定，无warnings；八export/ELF/module
产物验证通过。新签名空USB VM保留；最新实际88b9服务的真实双设备VM80默认回归通过：
广播扫描20+2轮、无连接SIGKILL交接、taint0、1293包无丢包。
[当前独立复算证据](evidence/ws73-native-advertising-modes-default-rf-regression-20261012.json)。
这是无连接回归，真实连接及有连接撤销清理尚未验收；原VM75/更早证据继续保留。

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
