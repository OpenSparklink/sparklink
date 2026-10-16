# ADR 0004：应用资源、管理权限与交付阶段

状态：采用；实现和验收范围独立记录。完整 S0–S6、drivers/net/slkd、VM-only 和
WS73 路径不变；UserHost 仍 P4 规划，不是数据或安全 relay 的前置条件。

## 依据与适用范围

核对官方 BlueZ `9dc7e40962f11d1d9a5568f8a7633a695288329c` 的五份资料。BlueZ 已有共享发现会话及客户端过滤约定，
并提供可选的 GATT socket fd 和 Profile fd 路径；本 ADR 是 SparkLink 的需求取舍，
不声称 BlueZ 缺陷、SparkLink 独创 fd 路径或已优于 BlueZ。

- [Adapter](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.Adapter.rst)：释放一个发现会话与停止最后一个共享会话不同；合并过滤后客户端仍须检查自己的条件。
- [Device](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.Device.rst)：连接、配对、持久 Bond、可修改信任策略及服务解析使用不同属性。
- [GattCharacteristic](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.GattCharacteristic.rst)：可选 fd/MTU、关闭与断链 HUP、通知会话和确认契约；不将确认推导为业务处理完成。
- [Profile](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/doc/org.bluez.Profile.rst)：向已授权服务连接交付 fd，并定义断开清理责任。
- [main.c](https://github.com/bluez/bluez/blob/9dc7e40962f11d1d9a5568f8a7633a695288329c/src/main.c)：daemon 主循环及信号退出；不能由内部 actor 划分推导进程故障隔离或性能结论。

源码 hash 与本项目精确 baseline 见[本批审查](../evidence/bluez-contract-review-20261014.json)。

## 决策

1. 应用的扫描租约、通道 Binding 与管理者的 controller/物理连接权限分别授权。
   合并硬件扫描不得扩大客户端过滤或取消范围；按 caller、controller generation、
   原始期限、预算记录应用租约。最后一个有效租约才申请停止硬件扫描；强制管理
   停止是另一个操作，需要使全部受影响租约得到明确终态。
2. 当前真实扫描接口属于管理权限，迁移为 `StartControllerScan/StopControllerScan`。
   移除未发布的旧混淆名称并迁移调用者。**尚未实现客户端发现租约**；不把管理
   STOP 当应用释放，也不把仅改名当共享扫描完成。未来客户端入口须先接实际租约。
3. `sparklink` 是管理组；可选 `sparklink-apps` 只开放 Connection 的 `OpenChannel`
   和 `OpenChannelScoped`，不开放广播/扫描/断链/控制器操作或 service 名称所有权。
   kernel 仍要求特权创建绑定，broker 传递 scoped fd，内核强制 epoch/方向/lifetime。
   分组是粗粒度准入，**不是完整逐应用/逐 Peer 策略**；protected security 仍拒绝。
4. Peer 为身份/观察；ConnectionSession 为一次物理 lifetime、信令/能力/分流/安全；
   Channel 为 TCID/PI/模式/独立队列；SocketBinding 为 fd 引用、授予范围与关闭。
   已观察连接、协商、服务发现、配对、Bond、认证、加密、本地授权分别表达。
   路径/地址/handle/本地 Trusted 策略均不是 wire 身份或真实安装证据。当前 Session
   仍与 Managed epoch 耦合，完整授权分离及旧 wire/NOCP 复用屏障仍缺。
5. 交付分为软件准入、实际 USB 提交、控制器完成、对端协议接收、对端应用处理。
   `sendmsg` 成功只描述有限软件队列准入；USB、NOCP、协议 ACK 不代表后续阶段。
   basic DGRAM 不承诺可靠/重传/业务处理；未来可靠模式另行定义才能开放 SEQPACKET。
   SSAP/Profile 复用既有 DTAP/socket，安全控制信令的 DLI relay 不另造业务发送通路。
6. fd 的 dup/fork/SCM_RIGHTS 共享同一 Binding 权限与引用，最后关闭结束该 Binding，
   不隐式断物理连接/停止 controller。逻辑通道关闭与同 lifetime 重开需真实关闭协议
   和残留隔离；当前缺失时拒绝。取消不能抹除已提交义务或归还不确定 credit。
7. 当前单次 SSAP 更新观察中 ACK1 只表示有界本地队列准入，ACK0 表示拒绝；
   notification 无 ACK。已准入后 caller 退出仍保留应完成的协议义务。队列满、
   原期限或 owner 丢失不得假成功；此处正向更新/CCC/可靠应用交付仍未取得实机资格。
8. per-controller actor/工作队列和原期限限制故障传播；共享 slkd 仍是一个进程。
   其崩溃会释放管理 fd，当前 epoch 撤销作用于相应 Binding，不能承诺所有业务 fd
   跨 daemon 崩溃存活。重启以 kernel 注册/实际 snapshot 收敛，不复活旧授权。

## Managed File 与业务 Binding 的撤权边界

控制File的release或最终引用释放撤销所属Managed epoch；dup的第一次close不能
释放仍有引用的租约。这不同于业务Binding最终close只释放本地未提交队列，亦不同于
声称关闭已经发送的物理义务。已开始PDU可能留下无末片前缀，必须保留原credit债务与
真实完成归属，不能模拟补齐或按应用退出退款。新lease不得恢复旧fd。

物理断链是另一事件：管理者可保持租约并发出绑定connection lifetime的Disconnect。
真实Down终结两端该连接及其旧Binding，不应撤销任一controller的独立管理租约。
阻塞者可先观察Session停止错误，后续操作必须按旧lifetime拒绝；禁止将撤权EACCES
当作断链归属检查通过。两端相连导致peer连接一起结束，不代表peer设备故障；
该peer保留Ready/扫描又不等于它的另一条独立业务连接已获验收。

证据只能在其实际观察精度内表达：release syscall前后区间、返回后无新USB提交、
迟到NOCP及等待者终态可以验证子门禁；完整提交线性化、引用/复用与原期限组合仍需
实际实现与模型对应。同行租约/Ready/扫描保留不等于另一独立业务连接存活。
跨VM受控交错不得直接比较宿主与guest墙钟。QMP真实状态由host自己的时钟排序，
guest按实际收到确认的单调/墙钟收据建立请求—确认—结果因果；PDU原期限用其
实际准入和终态的同一guest单调时钟测量。迟到NOCP不是期限刷新或失败Session复活，
这类受控延迟证据仍不证明硬件准确性、全部credit守恒、复用或自然恢复。

限定通过和未完成范围见唯一CURRENT_CAPABILITIES，不在本ADR累积逐轮资格。

## 改动相关门禁与剩余依赖

| 门禁 | 实现/离线与形式化 | 实机及退出条件 |
|---|---|---|
| 独立应用权限 | 精确 XML 白名单、实际 RPC/跨语言调用迁移；kernel cap/方向/epoch 检查 | 仅 apps 组 UID/caps0 领取并双向业务；拒绝扫描/断链/raw/管理；不能用控制组用户代替 |
| 应用共享资源 | 接 client 租约/过滤/有限预算/取消，模型不许清另一作者；无需等控制竞争全集 | 两应用一只 controller，退出/超时只释放自身；管理停止明确影响范围 |
| Binding 与在途 | 实际转换、票据、NOCP debt、dup/SCM_RIGHTS/最后关闭；unsupported/timeout 未证明 | 关闭/撤权/断链旧 life、真实 credit 压力及同行隔离；旧 wire 归属另证 |
| 分阶段交付 | socket poll/error/linger/RX 丢弃与消息完整性文档及实现对应 | 双端随机序号/载荷、协议及应用校验和回复；不得以 USB/NOCP/ACK 代替 |
| 更新与 Profile | 复用同一 SSAP actor/socket，ACK/队列满/owner-loss 的实际语义 | 正向 CCC/更新/安全依赖及应用 ACK；实验 Profile 不当已支持 |
| daemon/设备隔离 | deadline/取消/清理联合模型，锁/回调及 epoch 失效 | daemon kill/restart 与另一设备；FD 是否拒绝/保持按明示契约，不能默认存活 |

这些门禁分别关联 K#3/#4/#5/#6/#7/#10/#17/#18/#19、U#1/#2/#3/#5/#6/#8。
只设本次改动相关门禁；S0–S6、19 WP、10 FV、12 DG 的其他条件原样保留。
自然启动/重枚举/消失根因、非人工自动恢复与未完成整项 issues 均继续开放。

## 显式 CLI Agent 的范围

CLI 是现有 broker 的客户端，不增加 wire Engine。Agent 注册和安全请求权限属于
controller 管理；不同于普通应用通道。每个客户端固定原 daemon 唯一所有者，
同一作者连接保留 Allocate/Begin/Result/Cancel，所有权变化后不跟随替换。
人工逐请求回答，原 CLOCK_MONOTONIC 期限不刷新；一次未回答提示有界，未知/过期
或身份不符拒绝。EOF/退出仅注销该 Agent，Ctrl-C 请求只撤回本作者操作；broker
继续持有原生在途义务。不能从策略批准推导身份认证或 Bond。实际 CLI/VM 资格
按唯一能力入口单列，不继承旧测试 Agent 的历史通过。

## CPCD 与策略批准的界限

按T/XS20001-2025 §7.2.5.2/表40，客户端配置写入具有认证和授权要求，
并按当前连接独立、断链恢复初始值。不能以Agent同意、SDK111未认证加密或
可修改Trusted替代真实安全资格及内核授权。通知/指示生产接线必须保留这一检查；
不提供弱化的默认CCC路径。现有receive-interest仍只表示本地有界接收准入，
并不修改远端配置。此特定前置不扩展为全部控制面或Bond完成的依赖。
参考Host f0872df 的type2/两字节mask及每对端副本仅用于差分；本项目仍绑定
controller/generation/物理lifetime，以独立指示账本保留已在途义务。

## 数字比较机制与身份策略

数字比较复用唯一物理Session，IO/方法/算法必须由明确的有限模式选择，禁止从
对端请求自动降级。内核计算公开transcript的六位码并等待原作者的明确决定，
不得将显示码、相同码、本地确认、peer proof、安装接受或加密开启合并为同一状态。
原File/request/generation/lifetime/Grant epoch和原期限共同约束确认；确认不能刷新期限。
T在自身确认前允许暂存一份本Session的实际G proof，绝不采用参考Host的全局缓存；
只有本地同意后才验证并回应，撤销/到期后不得继续准入，物理义务仍保留。

有限机制的独立VM见证可以自动核对两端数字及公开transcript，但不充当生产Agent或
人类身份检查。slkd负责后续提示、方法和认证要求；内核须根据实际安装和完整过程
发布连接安全等级，再供可撤销的授权/SSAP权限消费。不能因机制局部通过开放可信
Grant或弱化CPCD检查。交互所需的期限策略另行设计，不能延长已经开始的请求。
准确资格统一登记于CURRENT_CAPABILITIES；尚未完成的Agent/安全等级/Bond、drain、
NOCP及复用假设继续开放，新的转换门禁不扩展为全部控制面组合的开发前置。


数字Agent沿用原Registry/Entry和监督任务，两次决策不得合并：前置Authorize仅允许
开始交换，实际flags8提示出现后才请求ConfirmNumericComparison。注册方法/Agent
唯一owner及epoch在Allocate冻结；Begin拒绝换方法。两个callback和后续原File确认、
proof、安装共享最初绝对期限。未知callback/拒绝/丢失/到期走原请求清理，已开始的
ioctl必须join。数字码和FrozenOperation终态均不是活连接安全等级或可信Grant。
前台CLI必须核对实际六位码和原id，不能把预输入批准用作后续数字确认；人机期限
策略及真实操作单独验收，不通过刷新已开始请求解决5秒预算的可用性限制。
