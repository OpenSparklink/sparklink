# Native连接、撤销清理及用户态调用者

2026-10-12，生产内核 `49699d6f11a5c1802508ac748d4a5e7d0b39d1d4`。
完整bzImage/modules构建通过，源码/配置稳定，无warnings；八export/ELF/module
产物验证通过。新签名空USB VM与实际5f6服务的真实双设备VM75回归通过：
广播扫描20+2轮、无连接SIGKILL交接、taint0、1397包无丢包。
[独立复算证据](evidence/ws73-native-connection-cleanup-rf-regression-20261012.json)。
这是无连接回归，真实连接及有连接撤销清理尚未验收；原D227/195证据继续保留。

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


## 独立真实连接测试门禁（尚待执行）

`ws73_target.py run --qmp-hotplug --connection-verify` 在普通 uid1000 下先执行
两端交换角色的显式地址类型0 Create、非消费结果、两端 Device Connected、
精确handle Disconnect和两端Disconnected；原广告的STOP必须获得真实结果，
失败不改写为OFF。随后保留原RF20+2回归。parent与guest各自从usbmon复算
paired OUT、原始CommandStatus、两端真实物理peer/type/handle事件；少任一证据
不通过。三个negative fixture覆盖丢证据、错误身份/handle/status及重复事件，
它们不是硬件资格。该门禁不包含connected release/last-File/dup/in-flight或SSAP，
这些仍是后续独立必需验收。
