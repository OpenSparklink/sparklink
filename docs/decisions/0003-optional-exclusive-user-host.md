# ADR 0003：Host模式、设备接入与唯一服务核心

原决定：2026-10-13；修订采用：2026-11-01。状态：架构采用，新增实现/证明/资格未完成。

## 2026-11-01 修订及理由

原P4独占接管/厂商分支保留，现命名KernelPacket；不再将全部用户态Host延期。正式新增项目自有Rust UserHost＋DirectUSB（Linux usbfs、Windows WinUSB），Windows首个目标11 x64/MSVC。完整Host由Host进程与服务核心共同组成；Host负责DLI/协议credit/连接/CMTC/DTAP/协议安全，SSAP/DB/Profile/Agent/Bond策略复用同一服务核心，不复制Engine。每controller一个Host进程，单controller仅一owner，活动路径不竞争两套状态机。

DirectUSB的固件/USB/HCC/BSLE在用户态设备适配；Native/KernelPacket在内核设备层。原“内核始终负责固件”和“UserHost拥有SSAP”概括被本修订替代。Native查询/SCM/授权不因跨平台而放宽；UserHost独立证明来源和提交/读取检查点，明文入IPC队列后不可追溯撤回。库drop/取消/重枚举不证明控制器状态清除；Native返回仍要求真实屏障和新身份。

服务核心不依赖自己的SDK；Linux D-Bus/Windows本地IPC只是同一handler前端。窄ServiceChannel及ConnectionUse按现有实际调用逐批收敛，拒绝机械拆crate、通用万能Adapter或成功依赖桩。Windows权限/HANDLE/IOCP、系统HID/音频分别验收；纯用户态Host不意味着系统集成无驱动。

采用原因：完整服务与Windows需要与内核机制分开的执行适配；DirectUSB无需先完成KernelPacket。复用生产纯逻辑能减少分叉，但锁/引用/USB/取消不等价，必须映射实测。nusb低层Endpoint为候选，先锁版本审查隐藏提交队列与drain；未完成前不承诺撤销后无物理提交。

完整三视图/状态所有权/安全差异见[唯一架构](../../project/architecture.md)，批次A–I/W、WP映射和新增验收见[唯一计划](../../project/implementation-plan.md)；本ADR不复制第二套规划。原S0–S6/19WP/10FV/12DG/预算和VM-only保留，有效范围明确增加；当前Native method v4不等待本扩展，U#7仅原KernelPacket/厂商scope，新增子项归U#8。

## DirectUSB库版本与提交边界审查（2026-11-01）

固定候选nusb **0.2.9**，归档SHA256 `1de8b6d15f559f50760dad6c1b56fde4041f99dc96a08e55c2b41f44c7417ad9`，上游提交[5dfee4c](https://github.com/kevinmehall/nusb/tree/5dfee4c1f82a1fdf019c3b5935ee4cd887908093)，双许可Apache-2.0/MIT。这是下一适配原型的审计pin，不是默认生产依赖；根Cargo.lock未改，未宣称完整依赖漏洞/许可或发布审查完成。文件hash、实际测试边界见[结构化审计](../../project/reference/architecture/directusb-library-audit-20261101.json)。

| 源码事实 | 实施约束／未证明项 |
|---|---|
| `Endpoint::submit`→Linux `USBDEVFS_SUBMITURB`／Windows `WinUsb_ReadPipe/WritePipe`，当前低层调用栈直接提交；错误延迟至Completion | actor持最终提交gate；调用后不能仅凭普通错误/零字节确认“从未提交”。OS请求提交与RF发送不是同一阶段 |
| control `TransferFuture::new`构造即调用submit，未poll也发生 | 权限、generation、原期限检查必须先于control方法调用；不能预建future后才检查，drop不能取消/证明排空 |
| Endpoint pending队列保留提交顺序；只取队首完成；没有项目预算 | 每controller明确包/字节/在途上限，初期单TX；排队头阻塞不解释为空口重排；单RX/多RX取舍须实测 |
| `cancel_all`仅请求取消；Endpoint drop发取消后Pending可转ABANDONED，payload留给completion释放 | 停准入、保留身份和buffer、逐个收取completion；期限耗尽隔离并保留义务，不宣布Free，不用drop/re-enumeration替代drain |
| WinUSB仅IN尝试RAW_IO，设置失败仅warn；OUT不能套用该策略 | 必须核对每方向实际OS队列语义及策略生效，当前不能宣称Windows无隐藏排队或取消总成功 |
| `transfer_blocking`超时后仍循环等待完成；reader/writer有额外缓冲 | 不作为有界actor执行路径；用低层Endpoint和原期限监督，明确请求结束与资源排空分离 |

优先继续低层Endpoint原型；libusb异步API保留备选，其submit返回值能提供另一种同步错误观测，但尚未完成固定版本后端源码审计，不能据API说明自动授予更强语义。Microsoft明确CancelIoEx不等待完成、可能正常完成，OVERLAPPED完成前不可释放；RAW_IO只适用IN且影响WinUSB排队。[取消契约](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex)、[管道策略](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/winusb-functions-for-pipe-policy-modification)、[libusb异步接口](https://libusb.sourceforge.io/api-1.0/group__libusb__asyncio.html)。

只在适配器预校验拒绝、尚未调用提交时确认NotSubmitted。已经调用且提交/执行失败无法区分时保留Unknown/物理义务，USB成功也不归还DLI credit。当前公开API不提供细粒度提交来源；需要更强分类则扩展可审查的适配或上游接口，不能用errno猜测。完成一次、OS不再访问buffer、内存序、调度及故障下最终回调都是信任基础/待验证条件，三项顺序离线测试不是并发或硬件证明。

固定NearLink Host与libws73-usb版本保持；前者LOCAL_TEST数据stub不用于真实性依据。后者`ws73_evt_stop`在有限等待后继续free，超限时未强制pending为零；这是静态风险而非本项目实机UAF证据，不复制成成功drain。参考源码许可/封装分别核对，未导入其业务实现。SDK110 E/US与四叶白名单、VM-only不变。

## 2026-10-13 原决定的保留部分（KernelPacket分支）

下列源码审计是历史身份；包接管、租约、真实屏障及厂商适配原门禁保留，不代表最新实现或资格。术语UserHost在本历史分支中指KernelPacket用户态Host。

### 历史源码及参考边界

审计K`88372a9b7cbcea7fcbca4f34cc9d5707488be46e`、U`b967674dede65884ac7fe0248fe6195bc082badd`，
两仓库clean。Cargo workspace无slk-vendord/Host-adapter crate；Kernel ControllerBackend
仅Native provider，公共头无UserHost接管接口。已实现的是共同Backend/驱动引用、Host/Session/
Grant/socket及其限定证据，不能宣称代理服务或UserHost已经存在。代码中的zbus::Proxy是D-Bus
客户端，不是厂商Backend。当前ControllerRuntime仍结合Native Host与传输引用；下述共享设备层
和NativeHostRuntime分离尚未实施。本轮不修改它，也不删除实现。

参考[Linux hci_sock.c](https://github.com/torvalds/linux/blob/master/net/bluetooth/hci_sock.c)：
user channel绑定要求权限与设备状态检查、设置独占标志，最终socket释放关闭设备并撤销独占。
本地hci_core.c的接收路径在monitor复制后绕过正常Host解析（driver setup有专门例外）。
采用其所有权/生命周期思路，不照搬HCI字节、socket编号或auto-off例外，不据此证明WS73状态清除。
本地参考hash、函数与审计记录见`evidence/userhost-planning-audit-20261013.json`。

## 两种互斥模式

| 责任 | Native（现有主线） | UserHost（未来可选） |
|---|---|---|
| DLI命令/事件、协议credit | 内核Native Host | 唯一用户态Host |
| connection/DTAP/TCID/协议安全 | 内核Native Host与Session | 用户态Host |
| SSAP/Profile/业务策略 | slkd/用户态；应用每逻辑通道socket | 同一服务核心/唯一SSAP Engine |
| 固件、USB/HCC/BSLE、传输资源/访问权限 | 共享内核设备/驱动层 | 同一共享内核设备/驱动层 |
| 可信原生Ready/link/security | 内核真实Native状态 | 不发布；用户态声明不得冒充原生可信状态 |

目标将共享DeviceRuntime（驱动、硬件generation、当前所有者、submit gate、传输限额、故障）
与NativeHostRuntime（DLI Host、协议credit、连接、DTAP、安全）分离。Native Backend继续服务
NativeHostRuntime；UserHostBinding接管共享设备包入口，**不是伪装成Native Backend**。
任何controller时刻只有一种协议Host；其他controller继续运行。driver必要固件/启动及HCC/BSLE
阶段与Host DLI初始化明确分开，不能在UserHost接管后继续偷偷查询/结算原生协议credit。

UserHost接口传递完整、有类型、方向、长度上限和方言来源的controller包。未来ABI必须明确
Command/Event/ACB及其他已支持包的合法方向、PB/长度/分片边界、身份/ownership epoch、
copy/非阻塞/poll/有限队列/错误。未知包或未接通能力明确拒绝；具体ABI/socket channel编号
本轮不冻结。内核保证物理传输 framing/资源边界，UserHost解释协议并独占消费回复。
monitor只复制流量，不能抢包、提交或影响Host credit；monitor丢包独立计数。
UserHost期间Native Managed、Diagnostic/raw命令及应用Channel不能继续控制该controller；
设备层紧急停用/恢复必须先撤销UserHost并走清理屏障，不能在背后reset再让其沿用旧credit。

## 接管与退出状态机（未来实施契约）

```
NativeActive → NativeDisabling → NativeIdle
NativeIdle → ToUserHost → UserHostOwned
UserHostOwned → Revoking → StateBarrier → NativeInitializing → NativeActive
任一切换/清理不确定 → Fault/Quarantined（不能直接Ready）
物理移除 → Removed（所有旧身份失效）
```

首版必须先显式停用，再请求接管。NativeIdle不是简单的软件flags=off：有活动连接、在途命令、
排队/已准入发送、未结清controller debt或未清理工作引用时拒绝切换；取消作者请求不抹掉
在途物理义务。首版不提供活动连接、FD通道、SSAP事务、Bond或credit热迁移。

接管线性化点位于共享设备所有权/提交gate：撤销Native授权，禁止新提交；join命令、事件、
DTAP与回调，清除Native RX消费和协议credit处理；确认控制器状态屏障后才交付UserHost所有权。
软件generation/epoch只能拒绝软件旧票据，不能证明固件队列/迟到回复/NOCP已排空。
切换失败若无法证明当前硬件与所有权状态，保持该设备不可用；不回滚为假Native Ready。

退出、lease撤销、最终socket释放或故障先撤权、关闭submit gate、失败本owner等待者并join传输。
状态屏障须逐型号/固件确认：真实停用/reset、驱动回调/队列join、旧协议包/debt与硬件密钥状态
清除。不得假设reset总会清credit/连接/密钥；不能确认就留Fault/Quarantined并走已验证的设备恢复。
返回Native创建新生命周期身份并重新查询/初始化，禁止继承旧connection lifetime、TCID、
Host credit、授权或安全状态。再次Ready必须有新的原生真实证据。自然恢复未闭合事项继续开放。

## Socket引用、租约与权限

- 所有权绑定socket对象及必要的内核租约/epoch，不绑定一个fd整数或仅PID。
- dup/fork共享同一socket所有权，不产生第二Host；关闭一个别名不触发最终释放。
- SCM_RIGHTS交付仍是同一socket，包括排队中的fd引用；不是新的接管或隐式扩权。
  首版委托范围由独立接管授权策略限定，接收者无接管授权不能靠普通Channel Grant获得Host写权。
  具体接收/使用时凭据和LSM检查、租约renew/revoke需在ABI评审定稿并进入内核准入/实际提交检查。
- 进程死亡释放该进程引用；其他合法别名/排队fd引用仍存在时，不等于最终socket释放。
  supervisor租约若因进程死亡撤销，则所有别名即刻失权；绝不只依据slkd缓存决定有效性。
- 最终引用释放与管理撤权是不同事件：前者结束对象引用，后者即使对象仍存活也关闭所有提交。
  两者走同一有界清理/屏障机制，不能双重完成、UAF或跨controller清理。
- 接管权限与普通业务通道权限分开；权限方案可参考CAP_NET_ADMIN，但本轮不新增固定能力号。
  保留独立service account、udev/LSM/systemd sandbox、root-owned硬件→库映射、凭据/日志隐私要求。

协议command/data/peer credit由当前Host单独记账；UserHost模式内核不解析NOCP来结算Native debt。
内核USB/HCC提交数、内存/字节预算、队列容量/背压是传输资源，不能冒充协议credit。
软件准入、USB提交、控制器完成、对端收到仍分开。UserHost自报可用/已连接/已加密不得进入Native
Ready、link表或可信安全快照。观察/管理UI可以显示模式及带来源的用户态声明。

## 厂商Host适配（独立延期任务）

不固定必须存在slk-vendord进程/框架；可选隔离进程只是适配部署选择。先审计每个Host/SDK是否
有可接入controller包的send/receive接口，谁做HCC/BSLE/DLI、谁管理credit/DTAP/security，
是否强占USB/vendor fd、是否需要callback或SDK修改。OHOS vendor lifecycle/channel参考并不证明
任意SDK是可替换的完整Host。只有高层私有API、无包注入入口的SDK不能假定直接可用。

保留库ABI size/version/symbol校验、可信库路径/identity/hash、许可证与架构/libc兼容、缺库/
初始化超时/partial I/O/EAGAIN/坏包/overflow/hangup/crash、重启隔离与性能预算验收。
私有opcode/void*不进入公共包ABI，不把闭源库加载进内核或默认slkd；没有真实库证明就明确未验证。
厂商API与slctl/slkd/SSAP/Bond的兼容是独立适配，不默认承诺；不能通过method echo、日志、
假Complete或用户态自报Ready代替互通。Raw libusb Host也不能未经改造就声称符合内核接管接口。

## 将来的证明与VM-only门禁（全部未实现/未证明/未验收）

| 范围 | 未来必要门禁 |
|---|---|
| 所有权FSM、模式与身份 | TLC：双重owner不可能，所有权互斥、原请求单终态、旧gen/epoch不能新提交，切换失败/不确定不能Ready；安全与有限清理，不用过强reset/drain假设 |
| submit/revoke/回调与File refs | TLC + 实际生产纯转换Kani/CBMC + LKMM：最终提交线性化、dup/fork/SCM排队引用/最终释放、进程死亡与lease撤权、worker/context/module保护；实际KCSAN/lockdep/内存sanitizer |
| 包与资源边界 | 实际codec CBMC/Kani/fuzz：类型/方向/长度、partial/EAGAIN、有限队列/内存预算；transport配额与协议credit互不混淆 |
| 双WS73切换/失败/故障 | VM-only真实两设备：Idle接管、活动连接/在途/debt拒绝、原生停止消费、旧提交/在途回复、失败/不确定屏障、最终释放、Native新gen重新初始化；另一只持续真实随机业务往返 |
| FD与拔插矩阵 | VM-only dup/fork/SCM_RIGHTS/载体排队/最后引用/lease revoke/owner crash、单只拔出重接、旧fd拒绝、不重启slkd；并发owner与重枚举竞争、四设备隔离后扩展 |
| UserHost业务与适配 | 两端应用随机序号/载荷实际校验回复、方向交换、USB/HCC/controller包证据；UserHost↔Native及所选Host互通单独记录；厂商兼容/安全声明不等于原生可信状态 |

沿用FV04/05/06/10及相关codec/FV安全任务，DG现有身份/授权/关闭/多设备/业务门禁增加mode维度；
不新增平行19WP/10FV/12DG方案。每项未来报告记录源码hash、映射、假设、状态空间/展开、版本、
反例及实现回归；timeout/unsupported/未展开记未证明，反例转成实际可复现测试。
本轮没有新增UserHost模型、UAPI、socket、Host服务、适配代码或实机测试，也不删除旧代码。
