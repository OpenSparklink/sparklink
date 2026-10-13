# ADR 0003：可选 controller 独占 UserHost

日期：2026-10-13。状态：**采纳目标规划；P4/低优先级，本轮不实现、不删代码。**
本决定调整WP14的固定`UserspaceProxyBackend → slk-vendord`方案，不表示原issue完成。
ARCHITECTURE仍定义目标分层，IMPLEMENTATION_PLAN仍为唯一执行计划，CURRENT_CAPABILITIES
仍是唯一资格入口。完整S0–S6、19工作包/10类形式化/12组数据门禁保留；Native WS73数据、
生命周期整改及用户态SSAP不依赖UserHost完成。本ADR只替换厂商代理分支的所有权设计，
不追溯扩大旧证据、不恢复旧SSAP wire Engine。

## 最新源码及参考边界

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
| SSAP/Profile/业务策略 | slkd/用户态；应用每逻辑通道socket | 用户态Host及独立上层适配 |
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
